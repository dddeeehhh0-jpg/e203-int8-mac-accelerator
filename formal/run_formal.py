#!/usr/bin/env python3
"""Reproducible SVA / SymbiYosys formal flow for the INT8 MAC channel.

Standard library only. The script:

  1. reads the CURRENT RTL sources from ../../rtl (never a stale copy),
  2. embeds them into generated .sby jobs together with formal checkers,
  3. runs positive proofs and negative (mutation) tests with smtbmc + z3,
  4. verifies that positive jobs PASS and negative jobs FAIL with a real
     counterexample trace,
  5. writes results/formal_report.md and formal/out/summary.json.

Positive proof of `requant_comb` is an unbounded combinational equivalence
proof against an independently written 51-bit reference model.
`stream_protocol` proves safety properties of the ready/valid control FSM
under the assumptions documented in checks/stream_check.v.

Neither job is RTL-vs-netlist formal equivalence. Gate-level replay remains a
finite-vector experiment; see results/gatelevel_report.md.

Usage:
    python3 formal/run_formal.py --strict
    python3 formal/run_formal.py --only requant_comb
    FORMAL_TOOLBIN=/path/to/bin python3 formal/run_formal.py --strict
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "formal"
JOBS_DIR = FORMAL / "out" / "jobs"
RESULTS = ROOT / "results"

MAC_RTL = [
    "rtl/mac/mac_pe.v",
    "rtl/mac/mac_array.v",
    "rtl/mac/acc_stage.v",
    "rtl/mac/requant.v",
    "rtl/top/int8_mac_top.v",
]
REQUANT_RTL = ["rtl/mac/requant.v"]

# (target file, exact old text, replacement). The driver refuses to run if the
# mutation anchor is missing or ambiguous, so a negative test can never
# silently turn into a positive one.
MUT_REQUANT = (
    "rtl/mac/requant.v",
    "(acc_ext * r32_ext) + ROUND",
    "(acc_ext * r32_ext)",
)
MUT_STREAM = (
    "rtl/top/int8_mac_top.v",
    "assign s_ready   = !stall && !cfg_valid;",
    "assign s_ready   = 1'b1;  // MUTANT: ignore backpressure and cfg priority",
)

JOBS = [
    {
        "name": "requant_comb",
        "top": "requant_check",
        "check": "formal/checks/requant_check.v",
        "rtl": REQUANT_RTL,
        "mode": "prove",
        "depth": 8,
        "expect": "PASS",
        "mutant": None,
        "purpose": "Unbounded combinational proof: RTL requant == independent 51-bit reference, over all 2^48 (acc,r32) pairs.",
    },
    {
        "name": "requant_comb_bad",
        "top": "requant_check",
        "check": "formal/checks/requant_check.v",
        "rtl": REQUANT_RTL,
        "mode": "bmc",
        "depth": 4,
        "expect": "FAIL",
        "mutant": MUT_REQUANT,
        "purpose": "Negative control: delete the +2^15 rounding bias. The checker must produce a counterexample.",
    },
    {
        "name": "stream_protocol",
        "top": "stream_check",
        "check": "formal/checks/stream_check.v",
        "rtl": MAC_RTL,
        "mode": "prove",
        "depth": 20,
        "expect": "PASS",
        "mutant": None,
        "purpose": "Sequential k-induction proof of ready/valid safety properties on int8_mac_top.",
    },
    {
        "name": "stream_protocol_bad",
        "top": "stream_check",
        "check": "formal/checks/stream_check.v",
        "rtl": MAC_RTL,
        "mode": "bmc",
        "depth": 6,
        "expect": "FAIL",
        "mutant": MUT_STREAM,
        "purpose": "Negative control: force s_ready high. Backpressure/priority assertions must produce a counterexample.",
    },
]


def find_sby(explicit: str | None) -> str:
    candidates = [
        explicit,
        os.environ.get("SBY"),
        shutil.which("sby"),
        shutil.which("yowasp-sby"),
    ]
    scripts = Path(sys.executable).parent / "Scripts"
    candidates += [
        str(scripts / "yowasp-sby.exe"),
        str(scripts / "yowasp-sby"),
        str(Path(sys.executable).parent / "yowasp-sby"),
        str(Path(sys.executable).parent / "yowasp-sby.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    raise RuntimeError(
        "SymbiYosys not found. Install yowasp-yosys (provides yowasp-sby) "
        "or set --sby / SBY."
    )


def ensure_yosys_shims() -> str | None:
    """Expose the YoWASP wrappers under the bare names sby expects.

    SymbiYosys invokes `yosys` and `yosys-smtbmc` as plain commands. The
    pip-installable YoWASP build only ships `yowasp-yosys` and
    `yowasp-yosys-smtbmc`, so thin shims are created in the gitignored
    formal/out/bin directory. This keeps the CI and the author's host on the
    same Yosys build instead of mixing an apt Yosys with a YoWASP smtbmc.
    """
    bin_dir = FORMAL / "out" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    scripts = Path(sys.executable).parent / "Scripts"
    targets = {
        "yosys": ["yowasp-yosys", "yowasp-yosys.exe"],
        "yosys-smtbmc": ["yowasp-yosys-smtbmc", "yowasp-yosys-smtbmc.exe"],
        "yosys-witness": ["yowasp-yosys-witness", "yowasp-yosys-witness.exe"],
    }
    made = False
    for bare, candidates in targets.items():
        exe = next((p for p in (shutil.which(c) for c in candidates) if p), None)
        if exe is None:
            exe = next((str(scripts / c) for c in candidates
                        if (scripts / c).exists()), None)
        if exe is None:
            continue
        if os.name == "nt":
            path = bin_dir / (bare + ".bat")
            path.write_text('@echo off\n"%s" %%*\n' % exe, encoding="ascii")
        else:
            path = bin_dir / bare
            path.write_text('#!/bin/sh\nexec "%s" "$@"\n' % exe, encoding="utf-8")
            path.chmod(0o755)
        made = True
    return str(bin_dir) if made else None


def probe_version(candidates: list[list[str]], env: dict) -> str:
    """Try several command spellings; Windows .bat shims need cmd.exe."""
    for cmd in candidates:
        exe = shutil.which(cmd[0], path=env.get("PATH"))
        if not exe:
            continue
        argv = [exe] + cmd[1:]
        if exe.lower().endswith(".bat") or exe.lower().endswith(".cmd"):
            argv = ["cmd.exe", "/c"] + argv
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
            out = (p.stdout or p.stderr).strip().splitlines()
            if out and out[0].strip():
                return out[0].strip()
        except Exception:
            continue
    return "unavailable"


def read_sources(spec: dict) -> tuple[dict[str, str], str | None]:
    """Return {basename: current source text} and the applied mutation text."""
    files: dict[str, str] = {}
    for rel in spec["rtl"]:
        files[Path(rel).name] = (ROOT / rel).read_text(encoding="utf-8")
    files[Path(spec["check"]).name] = (ROOT / spec["check"]).read_text(encoding="utf-8")

    mutation = None
    if spec["mutant"]:
        target, old, new = spec["mutant"]
        name = Path(target).name
        if name not in files:
            raise RuntimeError(f"mutation target {name} is not part of this job")
        text = files[name]
        if text.count(old) != 1:
            raise RuntimeError(
                f"mutation anchor in {name} matched {text.count(old)} times (expected 1); "
                "refusing to run a negative test that may not be negative"
            )
        files[name] = text.replace(old, new, 1)
        mutation = f"{name}: `{old}` -> `{new}`"
    return files, mutation


def build_sby(spec: dict, files: dict[str, str]) -> str:
    expect = "pass" if spec["expect"] == "PASS" else "fail"
    lines = [
        "[options]",
        f"mode {spec['mode']}",
        f"depth {spec['depth']}",
        f"expect {expect}",
        "",
        "[engines]",
        "smtbmc z3",
        "",
        "[script]",
        "read_verilog -formal " + " ".join(files.keys()),
        f"prep -top {spec['top']}",
        "",
    ]
    for name, content in files.items():
        lines.append(f"[file {name}]")
        lines.append(content.rstrip("\n"))
        lines.append("")
    return "\n".join(lines) + "\n"


def collect_traces(workdir: Path) -> list[str]:
    return sorted(
        str(p.relative_to(workdir)) for p in workdir.rglob("trace*.vcd")
    )


def run_job(spec: dict, sby: str, env: dict, timeout: int) -> dict:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    files, mutation = read_sources(spec)
    sby_path = JOBS_DIR / f"{spec['name']}.sby"
    sby_path.write_text(build_sby(spec, files), encoding="utf-8")

    workdir = JOBS_DIR / spec["name"]
    if workdir.exists():
        shutil.rmtree(workdir)

    cmd = [sby, "-f", str(sby_path)]
    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(JOBS_DIR), capture_output=True, text=True,
        timeout=timeout, env=env,
    )
    elapsed = round(time.time() - t0, 2)

    console = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (JOBS_DIR / f"{spec['name']}_console.log").write_text(console, encoding="utf-8")

    status_path = workdir / "status"
    if status_path.exists():
        # sby writes e.g. "PASS 0 0" (status plus assertion counters).
        raw = status_path.read_text(encoding="utf-8", errors="replace").strip().upper()
        status = raw.split()[0] if raw else "UNKNOWN"
    else:
        m = "DONE (PASS" in console
        status = "PASS" if m else ("FAIL" if "DONE (FAIL" in console else "UNKNOWN")

    traces = collect_traces(workdir)
    ok = status == spec["expect"]
    if spec["expect"] == "FAIL" and not traces:
        ok = False  # a negative test without a counterexample proves nothing

    return {
        "name": spec["name"],
        "purpose": spec["purpose"],
        "top": spec["top"],
        "mode": spec["mode"],
        "depth": spec["depth"],
        "expect": spec["expect"],
        "actual": status,
        "ok": ok,
        "elapsed_s": elapsed,
        "returncode": proc.returncode,
        "command": f"{Path(sby).name} -f {sby_path.relative_to(ROOT).as_posix()}",
        "command_actual": " ".join(cmd),
        "sby_file": str(sby_path.relative_to(ROOT)).replace("\\", "/"),
        "script": "read_verilog -formal " + " ".join(files.keys()) + f"; prep -top {spec['top']}",
        "mutation": mutation,
        "traces": traces,
        "log": f"formal/out/jobs/{spec['name']}_console.log",
        "workdir": f"formal/out/jobs/{spec['name']}",
    }


def write_report(results: list[dict], meta: dict, strict: bool) -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    positives = [r for r in results if r["expect"] == "PASS"]
    negatives = [r for r in results if r["expect"] == "FAIL"]
    all_ok = all(r["ok"] for r in results)

    L: list[str] = []
    L.append("# Formal verification report (SVA + SymbiYosys)")
    L.append("")
    L.append(f"Generated: {ts} on {meta['platform']} by `python3 formal/run_formal.py"
             + (" --strict`" if strict else "`"))
    L.append("")
    L.append("> This committed file is the author's host snapshot. CI re-runs the same flow on")
    L.append("> `ubuntu-latest` and uploads its own report, logs and counterexamples as the")
    L.append("> `formal-evidence` artifact; that artifact is authoritative for the published run.")
    L.append("")
    L.append(f"**Overall: {'PASS' if all_ok else 'FAIL'}** — "
             f"{sum(r['ok'] for r in results)}/{len(results)} jobs met their expected outcome.")
    L.append("")
    L.append("> Scope warning: these are formal proofs of *properties of this repository's RTL*.")
    L.append("> They are **not** RTL-vs-netlist formal equivalence, **not** full-chip verification,")
    L.append("> **not** a coverage number and **not** timing/PPA. Gate-level replay remains a")
    L.append("> finite-vector experiment (204-point boundary subset).")
    L.append("")
    L.append("## 1. Toolchain")
    L.append("")
    L.append("| Item | Version / command |")
    L.append("|---|---|")
    L.append(f"| Python | {meta['python']} |")
    L.append(f"| SymbiYosys | `{meta['sby']}` |")
    L.append(f"| yowasp-yosys | {meta['yowasp']} |")
    L.append(f"| Yosys | {meta['yosys']} |")
    L.append(f"| SMT solver | {meta['z3']} |")
    L.append(f"| Engine | `smtbmc z3`, k-induction (mode prove) / BMC (negative tests) |")
    L.append("")
    L.append("## 2. Results")
    L.append("")
    L.append("| Job | Object | Mode | Depth | Expected | Actual | Time | Outcome |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        L.append(f"| `{r['name']}` | `{r['top']}` | {r['mode']} | {r['depth']} | "
                 f"{r['expect']} | {r['actual']} | {r['elapsed_s']} s | "
                 f"{'OK' if r['ok'] else 'NOT OK'} |")
    L.append("")
    L.append("## 3. What is proved")
    L.append("")
    L.append("**`requant_comb` (combinational, unbounded over all 2^48 input pairs)**")
    L.append("")
    L.append("- P1/P2: `y_comb` and `sat_comb` equal an independently written 51-bit")
    L.append("  reference for every `(acc, r32)` — no input assumptions, no sampling.")
    L.append("- P3: an asserted saturation flag always implies a rail value (127 / -128).")
    L.append("- P4: the exact half-way case `acc=32768, r32=1` rounds to 1 (ties toward +infinity).")
    L.append("- P5: `acc=-65536, r32=1` yields -1, confirming arithmetic (floor) shift.")
    L.append("- P6: the 49-bit RTL intermediate never wraps, justifying `Q_W = 49`.")
    L.append("")
    L.append("**`stream_protocol` (sequential safety, k-induction)**")
    L.append("")
    L.append("- A1: reset leaves a deterministic, empty output stage.")
    L.append("- A2: backpressure drops both `s_ready` and `cfg_ready`.")
    L.append("- A3: `cfg_valid` has priority over the input stream (no simultaneous handshake).")
    L.append("- A4: `m_last` is never asserted without `m_valid`.")
    L.append("- A5: `m_valid`, `m_y`, `m_sat`, `m_last` hold stable through a stalled cycle.")
    L.append("- A6: without an input handshake the accumulator does not advance.")
    L.append("")
    L.append("Only **safety** properties are asserted. No liveness / throughput claim is made:")
    L.append("k-induction proves that nothing bad happens, not that a result must arrive.")
    L.append("")
    L.append("## 4. Assumptions and abstractions")
    L.append("")
    L.append("1. `stream_protocol` assumes `rst_n` is low at the first edge and high afterwards.")
    L.append("   Mid-stream reset is NOT covered by the proof; it is covered by `tb_top_stream`")
    L.append("   in the RTL regression.")
    L.append("2. Arithmetic operands (`s_x`, `s_w`, `cfg_r32`, `cfg_bias`) are tied to constants")
    L.append("   so Yosys constant-folds the 8-lane multiplier and the 32x16 requant multiplier.")
    L.append("   This keeps the SMT problem on the control FSM. Numeric correctness is proved")
    L.append("   separately by `requant_comb` and by the 88,048-point RTL regression.")
    L.append("3. `cfg_valid`, `s_valid`, `s_last`, `m_ready` are free inputs: the solver explores")
    L.append("   every combination of them.")
    L.append("4. The checkers use immediate `assert` / `assume` statements plus explicit shadow")
    L.append("   registers instead of `$past`, so the flow is independent of SVA frontend")
    L.append("   differences between Yosys builds.")
    L.append("")
    L.append("## 5. Negative tests (checker effectiveness)")
    L.append("")
    L.append("A formal checker that cannot fail is worthless. Each positive job therefore has a")
    L.append("mutated twin. The driver verifies the mutation anchor matches exactly once before")
    L.append("running, requires the mutated job to FAIL, and requires a real VCD counterexample.")
    L.append("")
    for r in negatives:
        L.append(f"- `{r['name']}`: {r['purpose']}")
        if r["mutation"]:
            L.append(f"  - Injected: {r['mutation']}")
        L.append(f"  - Result: **{r['actual']}**, {len(r['traces'])} trace(s); "
                 f"verdict {'OK' if r['ok'] else 'NOT OK'}")
        for t in r["traces"][:3]:
            L.append(f"  - Counterexample: `{r['workdir']}/{t}`")
    L.append("")
    L.append("## 6. Commands and evidence")
    L.append("")
    for r in results:
        L.append(f"### `{r['name']}`")
        L.append("")
        L.append(f"- Purpose: {r['purpose']}")
        L.append(f"- Config: `{r['sby_file']}` (mode `{r['mode']}`, depth {r['depth']}, expect {r['expect'].lower()})")
        L.append(f"- Yosys script: `{r['script']}`")
        L.append(f"- Command: `{r['command']}`")
        L.append(f"- Console log: `{r['log']}`; workdir: `{r['workdir']}/`")
        L.append("")
    L.append("## 7. Source integrity")
    L.append("")
    L.append("The `.sby` files are generated from the RTL at run time; a stale copy can never be")
    L.append("proved by accident. SHA-256 of the sources used for this run:")
    L.append("")
    L.append("| File | SHA-256 |")
    L.append("|---|---|")
    for rel, digest in meta["hashes"].items():
        L.append(f"| `{rel}` | `{digest}` |")
    L.append("")
    L.append("## 8. Deliberate limitations")
    L.append("")
    L.append("- No RTL-vs-netlist formal equivalence (`equiv_make` / `equiv_induct`); the")
    L.append("  gate-level replay is still a finite 204-point boundary subset.")
    L.append("- No SDC / STA, no Liberty library, no PDK, no timing or power claim.")
    L.append("- No liveness / throughput proof, no code or functional coverage percentage.")
    L.append("- No CDC, no FIFO, no SDF back-annotation: the design has a single clock domain.")
    L.append("- A successful proof is conditional on the assumptions in section 4.")
    L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any job misses its expected outcome (used by CI)")
    ap.add_argument("--sby", help="explicit path to the sby executable")
    ap.add_argument("--toolbin", help="directory with yosys / yosys-smtbmc / z3 shims")
    ap.add_argument("--z3", help="path to a z3 executable whose directory is added to PATH")
    ap.add_argument("--only", help="run a single job by name (for debugging)")
    ap.add_argument("--timeout", type=int, default=420, help="per-job timeout in seconds")
    args = ap.parse_args()

    env = os.environ.copy()
    shim_dir = ensure_yosys_shims()
    prefix = [p for p in [
        args.toolbin or os.environ.get("FORMAL_TOOLBIN"),
        str(Path(args.z3).parent) if args.z3 else None,
        shim_dir,
    ] if p]
    if prefix:
        env["PATH"] = os.pathsep.join(prefix + [env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"

    sby = find_sby(args.sby)
    try:
        yowasp_ver = importlib.metadata.version("yowasp-yosys")
    except Exception:
        yowasp_ver = "unknown"
    meta = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        # Only the command name is published: never leak a local absolute path.
        "sby": f"{Path(sby).name} (yowasp-yosys {yowasp_ver})",
        "yowasp": yowasp_ver,
        "yosys": probe_version([["yosys", "-V"], ["yowasp-yosys", "-V"]], env),
        "z3": probe_version([["z3", "-version"], ["z3.exe", "-version"]], env),
        "hashes": {},
    }
    rels = sorted({r for j in JOBS for r in j["rtl"]} |
                  {j["check"] for j in JOBS})
    for rel in rels:
        data = (ROOT / rel).read_bytes()
        meta["hashes"][rel] = hashlib.sha256(data).hexdigest()

    jobs = [j for j in JOBS if not args.only or j["name"] == args.only]
    if not jobs:
        print(f"unknown job: {args.only}", file=sys.stderr)
        return 2

    print(f"SymbiYosys: {sby}")
    print(f"Yosys:      {meta['yosys']}")
    print(f"Z3:         {meta['z3']}")
    print(f"Jobs:       {', '.join(j['name'] for j in jobs)}\n")

    results = []
    for spec in jobs:
        try:
            r = run_job(spec, sby, env, args.timeout)
        except subprocess.TimeoutExpired:
            r = {
                "name": spec["name"], "purpose": spec["purpose"], "top": spec["top"],
                "mode": spec["mode"], "depth": spec["depth"], "expect": spec["expect"],
                "actual": "TIMEOUT", "ok": False, "elapsed_s": args.timeout,
                "returncode": -1, "command": "TIMEOUT",
                "sby_file": f"formal/out/jobs/{spec['name']}.sby",
                "script": "", "mutation": None, "traces": [],
                "log": "", "workdir": f"formal/out/jobs/{spec['name']}",
            }
        except Exception as exc:
            r = {
                "name": spec["name"], "purpose": spec["purpose"], "top": spec["top"],
                "mode": spec["mode"], "depth": spec["depth"], "expect": spec["expect"],
                "actual": "ERROR", "ok": False, "elapsed_s": 0,
                "returncode": -1, "command": type(exc).__name__ + ": " + str(exc),
                "sby_file": f"formal/out/jobs/{spec['name']}.sby",
                "script": "", "mutation": None, "traces": [],
                "log": "", "workdir": f"formal/out/jobs/{spec['name']}",
            }
        results.append(r)
        print(f"  {r['name']:24s} expect={r['expect']:4s} actual={r['actual']:8s} "
              f"traces={len(r['traces'])} {r['elapsed_s']}s "
              f"{'OK' if r['ok'] else 'NOT OK'}")

    JOBS_DIR.parent.mkdir(parents=True, exist_ok=True)
    (JOBS_DIR.parent / "summary.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2), encoding="utf-8"
    )
    if not args.only:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "formal_report.md").write_text(
            write_report(results, meta, args.strict), encoding="utf-8"
        )

    all_ok = all(r["ok"] for r in results)
    print("\nOverall:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
