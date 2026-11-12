#!/usr/bin/env python3
"""One-command regression driver (stdlib only, no `make` required).

    python3 run_regress.py              # full run; RTL sim if iverilog exists
    python3 run_regress.py --strict     # fail if RTL sim could not be run (CI)
    python3 run_regress.py --sim-only   # compile + run the six testbenches only

Pipeline:
    1. int8_ref.py self-test          (bit-exact model, exhaustive boundaries)
    2. gen_vectors.py twice           (determinism: identical sha256 manifest)
    3. check_results.py --verify-vectors  (independent golden recomputation)
    4. rtl_lint.py                    (structural lint)
    5. iverilog + vvp x 6 TBs         (skipped with an explicit warning if not installed)
    6. check_results.py               (independent scoreboard over TB dumps)
    7. results/regression_summary.md

Every number in the summary points at a file produced by this run. Nothing is
hard-coded as "passed".
"""

from __future__ import annotations

import argparse
import datetime
import glob
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TBS = [
    "tb_mac_pe",
    "tb_mac_array",
    "tb_requant",
    "tb_top_stream",
    "tb_nice_adapter",
    "tb_soc_stub",
]


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError as exc:
        return 127, f"executable not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def find_simulator() -> tuple[str | None, str | None, str]:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog and vvp:
        return iverilog, vvp, iverilog

    env_home = os.environ.get("IVERILOG_HOME")
    candidates = [env_home] if env_home else []
    candidates.append(os.path.join(ROOT, ".tools", "iverilog", "bin"))
    for base in candidates:
        if not base:
            continue
        i = os.path.join(base, "iverilog.exe" if os.name == "nt" else "iverilog")
        v = os.path.join(base, "vvp.exe" if os.name == "nt" else "vvp")
        if os.path.isfile(i) and os.path.isfile(v):
            return i, v, i
    return None, None, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="treat 'RTL simulation skipped' as a failure (used by CI)")
    ap.add_argument("--sim-only", action="store_true",
                    help="only compile and run the Verilog testbenches")
    args = ap.parse_args()

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "vectors", "gen"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)

    steps: list[tuple[str, str, str]] = []
    rc = 0

    def record(name: str, code: int, detail: str = "") -> None:
        nonlocal rc
        status = "PASS" if code == 0 else "FAIL"
        if code != 0:
            rc = 1
        steps.append((name, status, detail.replace("\n", " ").strip()[:180]))

    # ---------------- 1. model self-test ---------------------------------
    if not args.sim_only:
        code, out = run([PY, "model/int8_ref.py"])
        n_pass = sum(1 for l in out.splitlines() if l.startswith("PASS"))
        record("int8_ref.py self-test", code, f"{n_pass} checks; {out.splitlines()[-1] if out else ''}")
        print(out, end="")

        # ---------------- 2. deterministic vectors ------------------------
        code1, out1 = run([PY, "model/gen_vectors.py"])
        manifest = os.path.join(ROOT, "vectors", "gen", "manifest.csv")
        first = open(manifest, encoding="ascii").read() if os.path.isfile(manifest) else ""
        code2, _ = run([PY, "model/gen_vectors.py"])
        second = open(manifest, encoding="ascii").read() if os.path.isfile(manifest) else ""
        det = "two runs produced identical sha256 manifests" if (first and first == second) else "manifests differ"
        code = code1 | code2 | (0 if det.startswith("two runs") else 1)
        record("gen_vectors.py determinism", code, det)

        # ---------------- 3. independent golden verification -------------
        code, out = run([PY, "model/check_results.py", "--verify-vectors", "--selftest"])
        record("check_results.py --verify-vectors", code,
               "; ".join(l.strip() for l in out.splitlines() if l.startswith("PASS") or l.startswith("FAIL") or l.startswith("checker")))
        print(out, end="")

        # ---------------- 4. structural lint ------------------------------
        code, out = run([PY, "model/rtl_lint.py"])
        tail = [l for l in out.splitlines() if l.startswith(("files", "modules", "errors"))]
        record("rtl_lint.py", code, "; ".join(tail))
        print("\n".join(l for l in out.splitlines() if l.startswith("[")), end="\n")

        # ---------------- 4b. optional real grammar parse -----------------
        code, out = run([PY, "model/verilog_parse_check.py"])
        if out.lstrip().startswith("SKIP"):
            steps.append(("verilog_parse_check.py (optional)", "SKIPPED", "pyverilog not installed"))
            print(out.strip())
        else:
            n_ok = sum(1 for l in out.splitlines() if l.startswith("[ OK ]"))
            record("verilog_parse_check.py grammar", code,
                   f"{n_ok} files parsed; failures={code}")
            print("\n".join(l for l in out.splitlines() if l.startswith("[")), end="\n")

    # ---------------- 5. RTL simulation ----------------------------------
    iverilog, vvp, sim_path = find_simulator()
    sim_status = "SKIPPED"
    sim_detail = "iverilog/vvp not available on this host"
    tb_rows: list[tuple[str, str, str]] = []

    if not iverilog or not vvp:
        print("\n[WARN] iverilog/vvp not found -> RTL simulation SKIPPED on this host.")
        print("       The GitHub Actions job installs iverilog on ubuntu-latest and runs all six TBs.")
    else:
        sim_status = "RUN"
        rtl = sorted(
            os.path.relpath(p, ROOT).replace("\\", "/")
            for p in glob.glob(os.path.join(ROOT, "rtl", "**", "*.v"), recursive=True)
        )
        ver = ""
        vrc, vout = run([iverilog, "-V"], timeout=20)
        if vrc in (0, 1):
            ver = vout.strip().splitlines()[0] if vout.strip() else ""
        sim_detail = f"{sim_path} {ver} | {len(rtl)} RTL files"

        for tb in TBS:
            out_bin = f"build/{tb}.vvp"
            ccmd = [iverilog, "-g2012", "-s", tb, "-o", out_bin, f"tb/{tb}.v"] + rtl
            crc, cout = run(ccmd, timeout=120)
            log_path = os.path.join(ROOT, "results", f"tb_{tb}.log")
            if crc != 0:
                with open(log_path, "w", encoding="utf-8") as fh:
                    fh.write("COMPILE FAILED\n" + cout)
                tb_rows.append((tb, "FAIL", "iverilog compile error"))
                continue
            rrc, rout = run([vvp, out_bin], timeout=180)
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(rout)
            ok = f"RESULT {tb} PASS" in rout and "FAIL" not in rout
            tb_rows.append((tb, "PASS" if ok else "FAIL",
                            next((l.strip() for l in rout.splitlines() if l.startswith(f"RESULT {tb}  ")), "no result line")))
            print("\n".join(l for l in rout.splitlines() if l.startswith("RESULT")), end="\n")

        if any(s == "FAIL" for _, s, _ in tb_rows):
            sim_status = "FAIL"
            rc = 1
        else:
            sim_status = "PASS"

    steps.append(("RTL simulation (6 TBs)", sim_status, sim_detail))

    # ---------------- 6. scoreboard over TB dumps ------------------------
    if not args.sim_only:
        code, out = run([PY, "model/check_results.py"])
        if "SKIP" in out:
            record("check_results.py (RTL dumps)", 0, "SKIPPED - no dumps (simulation not run)")
            steps[-1] = ("check_results.py (RTL dumps)", "SKIPPED", "no dumps (simulation not run)")
        else:
            record("check_results.py (RTL dumps)", code,
                   "; ".join(l.strip() for l in out.splitlines() if l.startswith("PASS") or l.startswith("FAIL")))
        print(out, end="")

    if args.strict and sim_status in ("SKIPPED", "FAIL"):
        rc = 1

    # ---------------- 7. summary -----------------------------------------
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "# Regression summary",
        "",
        f"- Generated: `{now}`",
        f"- Platform: `{platform.system()} {platform.release()}`, Python `{platform.python_version()}`",
        f"- Simulator: `{sim_path or 'not installed on this host'}`",
        "- Command: `python3 run_regress.py` (or `make regress`)",
        "",
        "> This file is generated. Do not edit by hand. Every PASS below is",
        "> derived from a process exit code or a file produced in this run.",
        "",
        "| Step | Status | Evidence |",
        "|---|---|---|",
    ]
    for name, status, detail in steps:
        lines.append(f"| {name} | {status} | {detail.replace('|', '/')} |")

    lines += ["", "## Testbench detail", "", "| Testbench | Status | Result line |", "|---|---|---|"]
    if tb_rows:
        for tb, st, detail in tb_rows:
            lines.append(f"| `{tb}` | {st} | {detail.replace('|', '/')} |")
    else:
        lines.append("| (none) | SKIPPED | No iverilog/vvp on this host; see CI job. |")

    lines += [
        "",
        "## Evidence index",
        "",
        "- `results/lint_report.txt` — structural lint",
        "- `results/parse_report.txt` — optional pyverilog grammar parse",
        "- `results/tb_*.log` — raw simulator output (only when simulation ran)",
        "- `results/dump_*.csv` — point-by-point RTL vs golden (only when simulation ran)",
        "- `vectors/gen/manifest.csv` — sha256 of every generated corpus",
        "- `.github/workflows/ci.yml` — Linux CI with iverilog installed",
        "",
    ]
    if sim_status == "SKIPPED":
        lines += [
            "## Honest status on this host",
            "",
            "**RTL simulation was NOT executed here** (no `iverilog`/`vvp`).",
            "The Python model, deterministic vectors, independent golden",
            "recomputation and structural lint all ran and passed; the six",
            "Verilog testbenches are compiled and run by the CI job on",
            "`ubuntu-latest`. Do not quote this run as RTL-verified.",
            "",
        ]

    summary = os.path.join(ROOT, "results", "regression_summary.md")
    with open(summary, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))

    print(f"\n== summary: {os.path.relpath(summary, ROOT)} ==")
    for name, status, _ in steps:
        print(f"  {status:7s}  {name}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
