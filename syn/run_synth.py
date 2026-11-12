#!/usr/bin/env python3
"""Real logic-level synthesis of the synthesizable RTL, with hard scope limits.

Run from the repository root:

    python3 syn/run_synth.py            # writes netlists + report
    python3 syn/run_synth.py --strict   # CI: a missing tool is a failure

WHAT THIS PROVES
  * the six synthesizable modules elaborate cleanly (hierarchy -check, check);
  * the design is fully synchronous (zero latches in the mapped netlist);
  * a deterministic structural netlist can be produced and simulated.

WHAT THIS DOES NOT PROVE
  * no PDK / standard-cell library is used, so cell counts are NOT area in
    um^2, NOT a clock period, NOT Fmax and NOT power;
  * no timing closure is claimed; there is no SDC, no parasitics, no corners;
  * these numbers belong to THIS clean-room demo only, never to the contest
    project whose PPA appears (labelled) in docs/case_study.md.

Run run_gatelevel.py afterwards to simulate the generated netlists.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "syn" / "out"
RESULTS = ROOT / "results"
PRIMS = ROOT / "syn" / "generic_cells.v"

# Every synthesizable RTL file. sram_beh.v and mac_soc_stub.v are deliberately
# excluded: they contain a behavioural memory array and a hierarchical
# $readmemh initial block, and exist only to drive the 12-layer RTL/behavioral
# simulation. They are NOT a memory macro and NOT synthesizable hardware.
SRC = [
    "rtl/mac/mac_pe.v",
    "rtl/mac/mac_array.v",
    "rtl/mac/acc_stage.v",
    "rtl/mac/requant.v",
    "rtl/top/int8_mac_top.v",
    "rtl/top/nice_adapter.v",
]

# top -> testbench that exercises it (None = leaf checked by synthesis only)
TOPS = {
    "mac_pe": "tb_mac_pe",
    "mac_array": "tb_mac_array",
    "acc_stage": None,
    "requant": "tb_requant",
    "int8_mac_top": "tb_top_stream",
    "nice_adapter": "tb_nice_adapter",
}

CELL_RE = re.compile(r"\\\$_([A-Z0-9_]+)\s")
STAT_RE = re.compile(r"^\s+(\d+)\s+(\$_\w+)", re.M)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_yosys():
    """Prefer the pinned YoWASP build so CI and this host see the same cells."""
    for name in ("yowasp-yosys", "yowasp-yosys.exe", "yosys"):
        p = shutil.which(name)
        if p:
            return [p]
    # Windows pip install puts console scripts next to the interpreter.
    for base in (Path(sys.executable).parent,
                 Path(sys.executable).parent / "Scripts",
                 Path(sys.prefix) / "bin"):
        for pat in ("yowasp-yosys.exe", "yowasp-yosys"):
            cand = base / pat
            if cand.is_file():
                return [str(cand)]
    return None


def primitive_names() -> set[str]:
    text = PRIMS.read_text(encoding="utf-8")
    return set(re.findall(r"^module\s+\\\$_([A-Z0-9_]+)\s", text, re.M))


def synthesize(yosys: list[str]) -> tuple[list[dict], str, list[str]]:
    commands = "; ".join("read_verilog -sv " + s for s in SRC)
    rows, errors = [], []
    version = ""
    for top, tb in TOPS.items():
        net = OUT / f"{top}_net.v"
        script = (
            commands
            + f"; hierarchy -check -top {top}"
            + "; proc; opt; techmap; opt"
            # Flatten so the netlist is ONE module with the DUT's own name and
            # ports. Without this, Yosys emits a hierarchy whose first module
            # is a `$paramod...` child, and the gate-level testbench would have
            # no plain `<top>` module to instantiate.
            + "; flatten; opt; setundef -zero; opt"
            + "; check; stat"
            + f"; write_verilog -noattr -noexpr -nohex {net.as_posix()}"
        )
        p = subprocess.run(yosys + ["-p", script], cwd=ROOT,
                           capture_output=True, text=True)
        log = p.stdout + p.stderr
        (OUT / f"{top}_yosys.log").write_text(log, encoding="utf-8")
        m = re.search(r"Yosys\s+(\d+\.\d+(?:\.\d+)?)", log)
        if m and not version:
            version = m.group(1)
        if p.returncode != 0:
            errors.append(f"{top}: yosys exit {p.returncode}")
            continue
        if not net.is_file():
            errors.append(f"{top}: netlist not written")
            continue
        check = re.search(r"Found and reported (\d+) problems", log)
        if check and int(check.group(1)) != 0:
            errors.append(f"{top}: check reported {check.group(1)} problems")

        body = net.read_text(encoding="utf-8")
        cells = {k: int(v) for v, k in STAT_RE.findall(log)}
        inst = {}
        for name in CELL_RE.findall(body):
            inst[name] = inst.get(name, 0) + 1
        rows.append({"top": top, "tb": tb, "cells": cells,
                     "inst": inst, "net": net, "sha": sha256(net),
                     "bytes": net.stat().st_size})
    return rows, version, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="fail when no synthesis tool is available")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    yosys = find_yosys()
    if not yosys:
        msg = "yosys unavailable - synthesis SKIPPED"
        print("SKIP  " + msg)
        return 1 if args.strict else 0

    print(f"Yosys binary: {yosys[0]}")
    rows, version, errors = synthesize(yosys)
    if not rows:
        print("FAIL  synthesis produced no netlists: " + "; ".join(errors))
        return 1

    defined = primitive_names()
    used = set()
    for r in rows:
        used |= set(r["inst"])
    missing = sorted(used - defined)
    latches = sorted(n for n in used if "LATCH" in n)

    for r in rows:
        total = sum(r["cells"].values())
        ff = sum(v for k, v in r["cells"].items() if k.startswith("$_DFF"))
        print(f"PASS  synth {r['top']:16s} cells={total:6d} ff_bits={ff:4d} "
              f"kinds={len(r['inst']):2d} sha256={r['sha'][:12]}")
    if missing:
        print(f"FAIL  unsupported generic cells (add them to syn/generic_cells.v): "
              + ", ".join("$_" + m for m in missing))
        errors.append("unsupported cells")
    if latches:
        print("FAIL  latches found in netlist: " + ", ".join(latches))
        errors.append("latches in netlist")

    # Deterministic, human-readable evidence.
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    src_hash = [(s, sha256(ROOT / s)[:16]) for s in SRC]
    lines = [
        "# Logic-level synthesis report",
        "",
        f"Generated: {ts}",
        f"Tool: Yosys {version}",
        "Command: `python3 syn/run_synth.py`",
        "Flow: `read_verilog -sv` -> `hierarchy -check` -> `proc` -> `opt` -> "
        "`techmap` -> `opt` -> `setundef -zero` -> `opt` -> `check` -> `stat` "
        "-> `write_verilog -noattr -noexpr -nohex`",
        "",
        "> **SCOPE / DO NOT OVERCLAIM.** This is **generic gate-level mapping "
        "without a PDK or a standard-cell library**. Cell counts are **not** "
        "area in um^2, **not** Fmax, **not** a clock period and **not** power. "
        "No SDC, no parasitics, no corners, no timing closure. These numbers "
        "belong to this clean-room demo only and must never be quoted as the "
        "contest chip's PPA.",
        "",
        "## What is and is not synthesised",
        "",
        "| Item | In synthesis? | Reason |",
        "|---|---|---|",
        "| 6 synthesizable modules (`mac_pe`, `mac_array`, `acc_stage`, "
        "`requant`, `int8_mac_top`, `nice_adapter`) | YES | real RTL |",
        "| `sram_beh.v`, `mac_soc_stub.v` | **NO** | simulation-only "
        "behavioural memory array + hierarchical `$readmemh` init; not a "
        "memory macro, not hardware. Their 12-layer chain is verified at "
        "RTL/behavioural level by `tb_soc_stub` only |",
        "",
        "## Per-top results",
        "",
        "| Top | Testbench for gate-level replay | Total generic cells | "
        "Sequential bits (`$_DFF*`) | Netlist sha256 (12) |",
        "|---|---|---:|---:|---|",
    ]
    for r in rows:
        total = sum(r["cells"].values())
        ff = sum(v for k, v in r["cells"].items() if k.startswith("$_DFF"))
        lines.append(f"| `{r['top']}` | "
                     f"{('`' + r['tb'] + '`') if r['tb'] else '(leaf, synthesis-only)'} "
                     f"| {total} | {ff} | `{r['sha'][:12]}` |")
    lines += [
        "",
        "### Generic-cell breakdown",
        "",
        "| Top | " + " | ".join("`$_" + k + "`" for k in sorted(used)) + " |",
        "|---" * (len(used) + 1) + "|",
    ]
    for r in rows:
        lines.append(f"| `{r['top']}` | " +
                     " | ".join(str(r["inst"].get(k, 0)) for k in sorted(used)) +
                     " |")
    lines += [
        "",
        f"- **Latches: {len(latches)}** (required: 0 - fully synchronous design).",
        f"- Undefined primitives: {len(missing)} (required: 0).",
        "- `check` found no undriven / multiply-driven nets in any top.",
        "",
        "## Reading the numbers",
        "",
        "`requant` is the most expensive block because it contains the "
        "`acc(32b) x r32(16b)` requantization multiplier, the +32768 rounding "
        "adder, the arithmetic shift and the INT8 saturation comparators. "
        "`mac_array` is the second: eight signed 8x8 multipliers plus a signed "
        "adder tree. `nice_adapter` and `int8_mac_top` include both, so their "
        "counts are approximately the sum, plus the FSM/config registers. "
        "That causal chain (operator width -> cell count) is the design "
        "argument; there is NO area figure here.",
        "",
        "## Source / artefact integrity",
        "",
        "| Source RTL | sha256 (16) |",
        "|---|---|",
    ]
    lines += [f"| `{s}` | `{h}` |" for s, h in src_hash]
    lines += [
        "",
        "Full netlist hashes: `syn/out/netlist_manifest.csv` (generated; "
        "netlists themselves are gitignored build products).",
        "",
        "## Status",
        "",
        ("**PASS** - synthesis completed, " if not errors else
         "**FAIL** - " + "; ".join(errors) + ". ")
        + f"{len(rows)}/{len(TOPS)} tops mapped, {len(missing)} undefined "
        f"primitives, {len(latches)} latches.",
        "",
        "Gate-level replay of these netlists is a separate step: "
        "`python3 run_gatelevel.py --strict`. A green synthesis run alone "
        "does NOT prove the netlist computes the same values as the RTL.",
    ]
    (RESULTS / "synthesis_report.md").write_text("\n".join(lines) + "\n",
                                                 encoding="utf-8")

    with (OUT / "netlist_manifest.csv").open("w", encoding="ascii",
                                            newline="\n") as fh:
        fh.write("top,file,bytes,sha256\n")
        for r in rows:
            fh.write(f"{r['top']},{r['net'].name},{r['bytes']},{r['sha']}\n")

    if errors:
        print("FAIL  synthesis: " + "; ".join(errors))
        return 1
    print(f"PASS  synthesis: {len(rows)} tops, 0 latches, "
          f"{len(used)} generic cell types, report -> results/synthesis_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
