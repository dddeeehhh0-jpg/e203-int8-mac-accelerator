#!/usr/bin/env python3
"""Gate-level replay: simulate the Yosys-mapped netlists with the SAME TBs.

Run AFTER both of these:

    python3 model/gen_vectors.py
    python3 run_regress.py --strict       # RTL simulation, writes results/dump_*.csv
    python3 syn/run_synth.py --strict     # writes syn/out/<top>_net.v
    python3 run_gatelevel.py --strict

Three independent checks per testbench:
  1. the testbench's own self-check prints ``RESULT <tb> PASS``;
  2. the independent scoreboard (model/check_results.py) re-checks the
     gate-level dump against the golden word (including the ready/valid
     protocol rule for the streaming dump);
  3. the gate-level ACTUAL column is compared bit-for-bit with the RTL
     ACTUAL column, using the same protocol rule. This is the actual
     RTL-vs-netlist equivalence evidence.

Gate-level TBs run in build/gl_run/ so their ``$fopen("results/...")`` cannot
overwrite the RTL dumps. The gate-level dumps are copied to
``results/gl_dump_*.csv`` for the CI artifact.

SCOPE: this proves functional equivalence ON THIS VECTOR SET under a
zero-delay behavioural primitive model. It is NOT formal equivalence, NOT a
timing check, NOT synthesis-with-PDK, and NOT a claim about the contest chip.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model"))
import check_results  # noqa: E402

# tb -> (netlist top, dump file name)
TARGETS = {
    "tb_mac_pe":       ("mac_pe",       "dump_mac_pe.csv"),
    "tb_mac_array":    ("mac_array",    "dump_mac_array.csv"),
    "tb_requant":      ("requant",      "dump_requant.csv"),
    "tb_top_stream":   ("int8_mac_top", "dump_top_stream.csv"),
    "tb_nice_adapter": ("nice_adapter", "dump_nice_adapter.csv"),
}

GLDIR = ROOT / "build" / "gl_run"

# Parameter values the RTL was synthesised with. A structural netlist has NO
# parameters (Yosys has already specialised them), so the replay TB must drop
# its `#(.PARAM(v))` override. We PARSE that override and assert it equals the
# synthesised value instead of silently discarding it - otherwise a TB that
# changed a width would appear to pass against the wrong hardware.
DEFAULTS = {
    "mac_pe":       {"IN_W": 8},
    "mac_array":    {"N_LANE": 8, "IN_W": 8, "ACC_W": 32},
    "requant":      {"ACC_W": 32, "R32_W": 16, "SHIFT": 16},
    "int8_mac_top": {"N_LANE": 8, "IN_W": 8, "ACC_W": 32, "R32_W": 16,
                     "BIAS_W": 16},
    "nice_adapter": {"N_LANE": 8, "IN_W": 8, "ACC_W": 32, "R32_W": 16},
}


def strip_dut_params(text: str, top: str):
    """Return (tb_source_without_override, overrides_dict, error)."""
    m = re.search(r"(?m)^(\s*)" + re.escape(top) + r"\s+#\(", text)
    if not m:
        return text, {}, f"{top}: no parameter override found in TB"
    open_paren = m.end() - 1
    depth, i = 0, open_paren
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        return text, {}, f"{top}: unbalanced '#(...)' in TB"
    block = text[open_paren + 1:i]
    overrides = {n: int(v, 0) for n, v in
                 re.findall(r"\.([A-Za-z_]\w*)\s*\(\s*([^()]+?)\s*\)", block)}
    bad = {n: (v, DEFAULTS[top].get(n)) for n, v in overrides.items()
           if DEFAULTS[top].get(n) != v}
    if bad:
        return text, overrides, f"{top}: TB overrides differ from synthesised "
        f"defaults: {bad}"
    hash_pos = m.end() - 2
    return text[:hash_pos] + text[i + 1:], overrides, None


def find_sim():
    return shutil.which("iverilog"), shutil.which("vvp")


def read_actual(path: Path) -> list[str]:
    with path.open(newline="", encoding="ascii") as fh:
        return [r["actual"] for r in csv.DictReader(fh)]


def compare_actual(rtl: list[str], gl: list[str], name: str) -> dict:
    """Reuse the scoreboard's protocol rule instead of inventing a looser one."""
    if len(rtl) != len(gl):
        return {"name": name, "points": min(len(rtl), len(gl)),
                "errors": abs(len(rtl) - len(gl)) + 1,
                "first": ("row count differs", len(rtl), len(gl))}
    with tempfile.TemporaryDirectory() as tmp:
        # The filename must retain the dump name: check_one_dump switches to
        # the ready/valid protocol rule for streaming dumps by name.
        p = Path(tmp) / name
        with p.open("w", newline="", encoding="ascii") as fh:
            w = csv.writer(fh)
            w.writerow(["test", "index", "expected", "actual"])
            for i, (a, b) in enumerate(zip(rtl, gl)):
                w.writerow(["rtl_vs_gate", i, a, b])
        return check_results.check_one_dump(str(p))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="CI: missing simulator / failed replay is a failure")
    args = ap.parse_args()

    iverilog, vvp = find_sim()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if not (iverilog and vvp):
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / "gatelevel_report.md").write_text(
            "# Gate-level replay report\n\n"
            f"Generated: {ts}\n\n"
            "**SKIPPED on this host** - `iverilog`/`vvp` are unavailable. "
            "This is the author's Windows snapshot and is NOT authoritative. "
            "GitHub Actions runs `python3 run_gatelevel.py --strict` on "
            "`ubuntu-latest`; see `results/ci_evidence.md` and the "
            "`gatelevel-evidence` CI artifact for the real result.\n",
            encoding="utf-8")
        print("SKIPPED  gate-level replay (iverilog/vvp unavailable)")
        return 1 if args.strict else 0

    # Preconditions: RTL dumps, vectors and netlists must all exist.
    missing = []
    for tb, (top, dump) in TARGETS.items():
        for p in (ROOT / "results" / dump,
                  ROOT / "syn" / "out" / f"{top}_net.v",
                  ROOT / "tb" / f"{tb}.v"):
            if not p.is_file():
                missing.append(str(p.relative_to(ROOT)))
    if missing:
        print("FAIL  gate-level prerequisites missing: " + ", ".join(missing))
        return 1

    # Isolated working directory so gate-level $fopen cannot clobber RTL dumps.
    if GLDIR.exists():
        shutil.rmtree(GLDIR)
    (GLDIR / "results").mkdir(parents=True)
    (GLDIR / "vectors" / "gen").mkdir(parents=True)
    for f in (ROOT / "vectors" / "gen").iterdir():
        if f.is_file():
            shutil.copy2(f, GLDIR / "vectors" / "gen" / f.name)

    (GLDIR / "tb_gl").mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for tb, (top, dump) in TARGETS.items():
        net = ROOT / "syn" / "out" / f"{top}_net.v"
        prims = ROOT / "syn" / "generic_cells.v"

        # A flattened Yosys netlist has no parameters. Make a TB copy whose
        # DUT instantiation drops the override - but only after asserting the
        # override equals the value the netlist was synthesised with.
        tb_src, overrides, err = strip_dut_params(
            (ROOT / "tb" / f"{tb}.v").read_text(encoding="utf-8"), top)
        if err:
            print("FAIL  " + err)
            failed.append(err)
            rows.append((tb, "PARAM_MISMATCH", 0, -1, -1, err))
            continue
        net_text = net.read_text(encoding="utf-8")
        if f"module {top}(" not in net_text:
            e = f"{tb}: netlist has no plain top module '{top}' " \
                "(run_synth.py must flatten)"
            print("FAIL  " + e)
            failed.append(e)
            rows.append((tb, "NO_TOP", 0, -1, -1, e))
            continue

        tbf = GLDIR / "tb_gl" / f"{tb}.v"
        tbf.write_text(tb_src, encoding="utf-8")
        exe = GLDIR / f"{tb}_gl.vvp"
        comp = subprocess.run(
            [iverilog, "-g2012", "-o", str(exe), "-s", tb,
             str(tbf), str(net), str(prims)],
            cwd=ROOT, capture_output=True, text=True)
        if comp.returncode != 0:
            detail = (comp.stderr or comp.stdout).strip()[:600]
            print(f"FAIL  iverilog compile {tb}: {detail}")
            failed.append(f"{tb}: iverilog compile failed")
            rows.append((tb, "COMPILE_FAIL", 0, -1, -1, detail[:200]))
            continue
        run = subprocess.run([vvp, exe.name], cwd=GLDIR,
                            capture_output=True, text=True, timeout=300)
        out = run.stdout + run.stderr
        (ROOT / "results" / f"gl_{tb}.log").write_text(out, encoding="utf-8")
        tb_pass = f"RESULT {tb} PASS" in out and f"RESULT {tb} FAIL" not in out
        pm = re.search(rf"RESULT {tb}\s+points=(\d+) mismatches=(\d+)", out)
        pts, mism = (int(pm.group(1)), int(pm.group(2))) if pm else (0, -1)

        gldump = GLDIR / "results" / dump
        if not gldump.is_file():
            failed.append(f"{tb}: no gate-level dump")
            rows.append((tb, "NO_DUMP", pts, -1, -1, ""))
            continue
        score = check_results.check_one_dump(str(gldump))
        rtl_actual = read_actual(ROOT / "results" / dump)
        gl_actual = read_actual(gldump)
        equiv = compare_actual(rtl_actual, gl_actual, dump)
        shutil.copy2(gldump, ROOT / "results" / f"gl_{dump}")

        ok = tb_pass and run.returncode == 0 and mism == 0 \
            and score["errors"] == 0 and equiv["errors"] == 0
        if not ok:
            failed.append(f"{tb}: selfcheck={tb_pass} scoreboard="
                          f"{score['errors']} rtl_vs_gl={equiv['errors']}")
        status = "PASS" if ok else "FAIL"
        print(f"{status}  gate-level {tb:18s} points={score['points']:6d} "
              f"scoreboard_err={score['errors']} rtl_vs_gl_diff={equiv['errors']}")
        rows.append((tb, status, score["points"], score["errors"],
                     equiv["errors"], ""))

    lines = [
        "# Gate-level replay report",
        "",
        f"Generated: {ts}",
        "Flow: Yosys generic mapping (`syn/run_synth.py`) -> structural "
        "netlist -> Icarus Verilog with hand-written `syn/generic_cells.v` "
        "-> the SAME self-checking testbench and the SAME scoreboard.",
        "",
        "> **Scope.** Functional equivalence on this vector set under a "
        "zero-delay behavioural primitive model. NOT formal equivalence, "
        "NOT timing, NOT PDK synthesis, NOT the contest chip. "
        "The simulation-only blocks `sram_beh` / `mac_soc_stub` are not "
        "synthesised and `tb_soc_stub` is therefore RTL/behavioural only.",
        "",
        "| Testbench | Netlist top | Result | Points | Scoreboard errors | "
        "RTL-vs-netlist differences |",
        "|---|---|---|---:|---:|---:|",
    ]
    for tb, status, pts, se, de, _ in rows:
        lines.append(f"| `{tb}` | `{TARGETS[tb][0]}` | {status} | {pts} | "
                     f"{se} | {de} |")
    lines += [
        "",
        "Three checks per TB: (1) in-TB `RESULT ... PASS`, (2) independent "
        "scoreboard re-check of the gate-level dump against golden, "
        "(3) bit-exact comparison of the gate-level ACTUAL column with the "
        "RTL ACTUAL column under the same ready/valid protocol rule. A "
        "mismatch in ANY of the three fails the build.",
        "",
        "Gate-level dumps: `results/gl_dump_*.csv`; raw simulator output: "
        "`results/gl_tb_*.log` (build products, gitignored; uploaded as CI "
        "artifacts).",
        "",
        "The netlists are **flattened** (`syn/run_synth.py`), so each is one "
        "module named exactly like the DUT. The replay TB is a generated copy "
        "with the DUT's `#(.PARAM(v))` override removed, because a structural "
        "netlist has no parameters; `run_gatelevel.py` parses the override "
        "first and fails if it differs from the synthesised default width.",
    ]
    details = [r for r in rows if len(r) > 5 and r[5]]
    if details:
        lines += ["", "## Failure details", ""]
        lines += [f"- `{r[0]}`: {r[5]}" for r in details]
    lines += [
        "",
        "## Status",
        "",
        (f"**PASS** - {len(rows)} netlists replayed, all three checks green."
         if not failed else
         "**FAIL** - " + "; ".join(failed)),
    ]
    (ROOT / "results" / "gatelevel_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    if failed:
        print("FAIL  gate-level replay: " + "; ".join(failed))
        return 1
    print(f"PASS  gate-level replay: {len(rows)}/{len(TARGETS)} netlists "
          "match the RTL bit-for-bit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
