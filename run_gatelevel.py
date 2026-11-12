#!/usr/bin/env python3
"""Gate-level replay: prove RTL and the synthesised netlist agree, bit-exactly.

Run AFTER:

    python3 model/gen_vectors.py
    python3 run_regress.py --strict       # FULL RTL regression, all vectors
    python3 syn/run_synth.py --strict     # flattened structural netlists
    python3 run_gatelevel.py --strict

WHY A REDUCED VECTOR SET
  A zero-delay netlist maps the 32x16 requant multiplier into thousands of
  gate primitives. Replaying all 17,459 requant vectors produces tens of
  millions of delta-cycle events and exceeded 300 s in the first real CI run
  (43233148388) - a simulation-cost problem, not a functional failure. Gate
  replay is an EQUIVALENCE check, not a re-run of the full regression, so it
  uses a representative boundary subset. The full 17,459-point sweep still
  runs at RTL level in `run_regress.py --strict`. Only tb_requant is reduced;
  the other four netlists keep their full vectors. The TBs hard-code their
  loop bound (N_VEC), so generated TB copies for BOTH runs are patched to the
  reduced count, with a consistency check against the full corpus first.

HOW EQUIVALENCE IS STILL RIGOROUS
  For each TB we run TWO simulations on the SAME reduced vector file, in two
  isolated directories:
    * an RTL reference (original TB + original RTL sources)
    * the gate-level netlist (generated TB copy + netlist + generic_cells.v)
  Then, per TB, five checks must all be green:
    1. RTL reference prints `RESULT <tb> PASS`;
    2. gate-level prints `RESULT <tb> PASS`;
    3. independent scoreboard on the RTL-reference dump: 0 errors;
    4. independent scoreboard on the gate-level dump: 0 errors;
    5. RTL ACTUAL column == gate-level ACTUAL column, row by row, under the
       same ready/valid protocol rule (streaming dumps ignore payload while
       valid=0).
  Any mismatch fails the build. Nothing is relaxed.

SCOPE: functional equivalence on THIS vector set under a zero-delay
behavioural primitive model. NOT formal equivalence, NOT timing, NOT
PDK synthesis, NOT a claim about the contest chip.
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
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

# Same synthesizable source set used by syn/run_synth.py (the behavioural
# sram_beh / mac_soc_stub are simulation-only and deliberately excluded).
RTL_SOURCES = [
    "rtl/mac/mac_pe.v",
    "rtl/mac/mac_array.v",
    "rtl/mac/acc_stage.v",
    "rtl/mac/requant.v",
    "rtl/top/int8_mac_top.v",
    "rtl/top/nice_adapter.v",
]

# Representative r32 scales for the gate-level requant sweep. Everything else
# (all 17 acc edges) is kept for every selected scale. The FULL 1,027-scale
# sweep is still exercised at RTL level by run_regress.py --strict.
GL_R32_SUBSET = {0, 1, 2, 3, 16, 64, 256, 512, 1023, 1024, 32767, 65535}

# Primary stimulus file of each TB. The TBs hard-code the vector count in a
# `localparam integer N_VEC` / `for (i = 0; i < N; ...)` loop, so a reduced
# vector file MUST be accompanied by a reduced loop bound in the generated TB
# copy. Both the RTL reference and the gate-level run use that copy, which
# keeps the two dumps row-for-row comparable.
TB_VECTOR = {
    "tb_mac_pe":       "pe_full.hex",
    "tb_mac_array":    "array_rand.hex",
    "tb_requant":      "requant_scan.hex",
    "tb_top_stream":   "top_seq.hex",
    "tb_nice_adapter": "nice_seq.hex",
}

GLDIR = ROOT / "build" / "gl_run"
RTLDIR = GLDIR / "rtl_ref"
GATEDIR = GLDIR / "gate"

# Parameter values the RTL was synthesised with. A flattened structural
# netlist has NO parameters, so the replay TB must drop its `#(.PARAM(v))`
# override. We parse and CHECK that override before dropping it - otherwise a
# TB that changed a width could appear to pass against the wrong hardware.
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
        return text, overrides, (
            f"{top}: TB overrides differ from synthesised defaults: {bad}")
    hash_pos = m.end() - 2
    return text[:hash_pos] + text[i + 1:], overrides, None


def patch_vec_count(text: str, tb: str, notes: dict):
    """Keep a TB's hard-coded loop bound in sync with its (possibly reduced)
    stimulus file. Returns (patched_text, old_count, new_count, error)."""
    vec = TB_VECTOR[tb]
    if vec not in notes:
        return text, None, None, None          # not reduced -> no patch
    full, kept = notes[vec]
    if full == kept:
        return text, None, None, None
    pattern = r"(localparam\s+integer\s+N_VEC\s*=\s*)(\d+)(\s*;)"
    m = re.search(pattern, text)
    if not m:
        return text, None, None, (
            f"{tb}: vector file reduced to {kept} but no `N_VEC` localparam "
            "to patch - refusing to run with a wrong loop bound")
    old = int(m.group(2))
    if old != full:
        return text, None, None, (
            f"{tb}: TB declares N_VEC={old} but {vec} has {full} lines - "
            "the corpus and the TB are out of sync")
    patched = text[:m.start()] + m.group(1) + str(kept) + m.group(3) + text[m.end():]
    return patched, old, kept, None


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
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # Filename must retain the dump name: check_one_dump switches to the
        # ready/valid protocol rule for streaming dumps by name.
        p = Path(tmp) / name
        with p.open("w", newline="", encoding="ascii") as fh:
            w = csv.writer(fh)
            w.writerow(["test", "index", "expected", "actual"])
            for i, (a, b) in enumerate(zip(rtl, gl)):
                w.writerow(["rtl_vs_gate", i, a, b])
        return check_results.check_one_dump(str(p))


def prepare_vectors() -> dict:
    """Copy vectors into both isolated dirs; reduce the expensive requant sweep."""
    src = ROOT / "vectors" / "gen"
    notes = {}
    for base in (RTLDIR, GATEDIR):
        (base / "results").mkdir(parents=True, exist_ok=True)
        (base / "vectors" / "gen").mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        data = f.read_text(encoding="ascii")
        if f.name == "requant_scan.hex":
            all_lines = [l for l in data.splitlines() if l.strip()]
            kept = [l for l in all_lines
                    if int(l.split()[1], 16) in GL_R32_SUBSET]
            notes[f.name] = (len(all_lines), len(kept))
            data = "\n".join(kept) + "\n"
        for base in (RTLDIR, GATEDIR):
            (base / "vectors" / "gen" / f.name).write_text(data,
                                                           encoding="ascii")
    return notes


def run_one(iverilog, vvp, tb, top, dump, rtl_sources, notes):
    """Return a result dict for one testbench."""
    net = ROOT / "syn" / "out" / f"{top}_net.v"
    prims = ROOT / "syn" / "generic_cells.v"
    orig_tb = ROOT / "tb" / f"{tb}.v"
    res = {"tb": tb, "top": top, "note": ""}

    raw_tb = orig_tb.read_text(encoding="utf-8")
    rtl_src, old_n, new_n, perr = patch_vec_count(raw_tb, tb, notes)
    if perr:
        res.update(status="VEC_COUNT_MISMATCH", note=perr)
        return res
    gl_src, overrides, err = strip_dut_params(rtl_src, top)
    if err:
        res.update(status="PARAM_MISMATCH", note=err)
        return res
    net_text = net.read_text(encoding="utf-8")
    if f"module {top}(" not in net_text:
        res.update(status="NO_TOP",
                   note=f"netlist has no plain top module '{top}' "
                        "(run_synth.py must flatten)")
        return res

    # Both simulations use generated TB copies in isolated directories, so
    # they see the same reduced stimulus and the same loop bound. The RTL copy
    # keeps its parameter overrides; the gate copy drops them (a flattened
    # structural netlist has no parameters).
    rtl_tb = RTLDIR / "tb_rtl" / f"{tb}.v"
    gl_tb = GATEDIR / "tb_gl" / f"{tb}.v"
    rtl_tb.parent.mkdir(parents=True, exist_ok=True)
    gl_tb.parent.mkdir(parents=True, exist_ok=True)
    rtl_tb.write_text(rtl_src, encoding="utf-8")
    gl_tb.write_text(gl_src, encoding="utf-8")
    if new_n is not None:
        res["note"] = f"N_VEC {old_n}->{new_n} (reduced stimulus)"

    # ---- RTL reference (TB copy WITH parameter overrides) ----
    rtl_exe = RTLDIR / f"{tb}_rtl.vvp"
    comp = subprocess.run(
        [iverilog, "-g2012", "-o", str(rtl_exe), "-s", tb,
         str(rtl_tb)] + [str(ROOT / s) for s in rtl_sources],
        cwd=ROOT, capture_output=True, text=True)
    if comp.returncode != 0:
        res.update(status="COMPILE_FAIL",
                   note="RTL ref: " + (comp.stderr or comp.stdout).strip()[:300])
        return res
    # ---- gate-level (TB copy + netlist + primitives) ----
    gl_exe = GATEDIR / f"{tb}_gl.vvp"
    comp = subprocess.run(
        [iverilog, "-g2012", "-o", str(gl_exe), "-s", tb,
         str(gl_tb), str(net), str(prims)],
        cwd=ROOT, capture_output=True, text=True)
    if comp.returncode != 0:
        res.update(status="COMPILE_FAIL",
                   note="gate: " + (comp.stderr or comp.stdout).strip()[:300])
        return res

    try:
        rtl_run = subprocess.run([vvp, rtl_exe.name], cwd=RTLDIR,
                                 capture_output=True, text=True, timeout=600)
        gl_run = subprocess.run([vvp, gl_exe.name], cwd=GATEDIR,
                                capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as e:
        res.update(status="TIMEOUT", note=f"simulation exceeded 600 s: {e.cmd}")
        return res

    rtl_out = rtl_run.stdout + rtl_run.stderr
    gl_out = gl_run.stdout + gl_run.stderr
    (ROOT / "results" / f"gl_{tb}.log").write_text(
        "=== RTL reference ===\n" + rtl_out + "\n=== gate-level ===\n" + gl_out,
        encoding="utf-8")
    rtl_pass = f"RESULT {tb} PASS" in rtl_out and f"RESULT {tb} FAIL" not in rtl_out
    gl_pass = f"RESULT {tb} PASS" in gl_out and f"RESULT {tb} FAIL" not in gl_out

    rtl_dump = RTLDIR / "results" / dump
    gl_dump = GATEDIR / "results" / dump
    if not (rtl_dump.is_file() and gl_dump.is_file()):
        res.update(status="NO_DUMP",
                   note=f"rtl_dump={rtl_dump.is_file()} gl_dump={gl_dump.is_file()}")
        return res

    rtl_score = check_results.check_one_dump(str(rtl_dump))
    gl_score = check_results.check_one_dump(str(gl_dump))
    equiv = compare_actual(read_actual(rtl_dump), read_actual(gl_dump), dump)
    shutil.copy2(gl_dump, ROOT / "results" / f"gl_{dump}")
    shutil.copy2(rtl_dump, ROOT / "results" / f"gl_rtl_{dump}")

    ok = (rtl_pass and gl_pass and rtl_run.returncode == 0
          and gl_run.returncode == 0 and rtl_score["errors"] == 0
          and gl_score["errors"] == 0 and equiv["errors"] == 0)
    res.update(status="PASS" if ok else "FAIL",
               points=gl_score["points"],
               rtl_score=rtl_score["errors"], gl_score=gl_score["errors"],
               diff=equiv["errors"], rtl_pass=rtl_pass, gl_pass=gl_pass,
               note="" if ok else
               f"rtl_pass={rtl_pass} gl_pass={gl_pass} "
               f"rtl_score={rtl_score['errors']} gl_score={gl_score['errors']} "
               f"rtl_vs_gl={equiv['errors']}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="CI: missing simulator / failed replay is a failure")
    args = ap.parse_args()
    (ROOT / "results").mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    iverilog, vvp = find_sim()
    if not (iverilog and vvp):
        (ROOT / "results" / "gatelevel_report.md").write_text(
            "# Gate-level replay report\n\n"
            f"Generated: {ts}\n\n"
            "**SKIPPED on this host** - `iverilog`/`vvp` are unavailable. "
            "This is the author's Windows snapshot and is NOT authoritative. "
            "GitHub Actions runs `python3 run_gatelevel.py --strict` on "
            "`ubuntu-latest`; see `results/ci_evidence.md` and the CI "
            "artifact for the real result.\n",
            encoding="utf-8")
        print("SKIPPED  gate-level replay (iverilog/vvp unavailable)")
        return 1 if args.strict else 0

    missing = []
    for tb, (top, dump) in TARGETS.items():
        for p in (ROOT / "syn" / "out" / f"{top}_net.v",
                  ROOT / "tb" / f"{tb}.v",
                  ROOT / "syn" / "generic_cells.v"):
            if not p.is_file():
                missing.append(str(p.relative_to(ROOT)))
    if missing:
        print("FAIL  gate-level prerequisites missing: " + ", ".join(missing))
        return 1

    if GLDIR.exists():
        shutil.rmtree(GLDIR)
    GLDIR.mkdir(parents=True)
    notes = prepare_vectors()

    rows = []
    for tb, (top, dump) in TARGETS.items():
        r = run_one(iverilog, vvp, tb, top, dump, RTL_SOURCES, notes)
        rows.append(r)
        if r["status"] == "PASS":
            print(f"PASS  gate-level {tb:18s} points={r['points']:6d} "
                  f"rtl_score={r['rtl_score']} gl_score={r['gl_score']} "
                  f"rtl_vs_gl_diff={r['diff']}")
        else:
            print(f"FAIL  gate-level {tb:18s} {r['status']}: {r['note']}")
    failed = [f"{r['tb']}: {r['status']}" for r in rows
              if r["status"] != "PASS"]

    lines = [
        "# Gate-level replay report",
        "",
        f"Generated: {ts}",
        "Flow: Yosys generic mapping (`syn/run_synth.py`, flattened) -> "
        "structural netlist -> Icarus Verilog with hand-written "
        "`syn/generic_cells.v` -> the SAME self-checking testbench.",
        "",
        "> **Scope.** Functional equivalence on this vector set under a "
        "zero-delay behavioural primitive model. NOT formal equivalence, "
        "NOT timing, NOT PDK synthesis, NOT the contest chip. "
        "`sram_beh` / `mac_soc_stub` are not synthesised, so `tb_soc_stub` is "
        "RTL/behavioural only.",
        "",
        "## Why the gate-level vector set is smaller",
        "",
        "A zero-delay netlist maps the 32x16 requant multiplier to thousands "
        "of gate primitives; replaying all 17,459 requant vectors exceeded "
        "300 s in CI run `43233148388` (a simulation-cost issue, not a "
        "functional failure). Gate replay is an **equivalence** check, so it "
        "uses a representative boundary subset. The **full** 17,459-point "
        "sweep still runs at RTL level in `run_regress.py --strict`.",
        "",
    ]
    for name, (full, kept) in notes.items():
        lines.append(f"- `{name}`: {full} RTL points -> {kept} gate-level "
                     f"points (all 17 `acc` edges kept for each of "
                     f"{len(GL_R32_SUBSET)} representative `r32` scales).")
    if not notes:
        lines.append("- No vector reduction was applied.")
    lines += [
        "",
        "The TBs hard-code their vector count (`N_VEC`). For every reduced "
        "stimulus file, the generated TB copy for **both** runs is patched "
        "to the new loop bound; `patch_vec_count()` first verifies that the "
        "original bound equals the full corpus size and fails loudly if the "
        "corpus and TB are out of sync. A short vector file therefore cannot "
        "silently produce a false PASS.",
        "",
        "Both simulations (RTL reference and gate-level) use **the same "
        "vector file, the same loop bound and the same check logic** in "
        "isolated directories, so their dumps can be compared row by row.",
        "",
        "| Testbench | Netlist top | Result | Points | RTL scoreboard | "
        "Gate scoreboard | RTL-vs-gate differences |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        if r["status"] == "PASS":
            lines.append(f"| `{r['tb']}` | `{r['top']}` | PASS | "
                         f"{r['points']} | {r['rtl_score']} | "
                         f"{r['gl_score']} | {r['diff']} |")
        else:
            lines.append(f"| `{r['tb']}` | `{r['top']}` | {r['status']} | "
                         "- | - | - | - |")
    lines += [
        "",
        "Five checks per TB, all mandatory: (1) RTL reference `RESULT ... "
        "PASS`; (2) gate-level `RESULT ... PASS`; (3) independent scoreboard "
        "on the RTL dump; (4) independent scoreboard on the gate dump; "
        "(5) bit-exact comparison of the two ACTUAL columns under the same "
        "ready/valid protocol rule. This is not a relaxation of the RTL "
        "regression - it is a separate equivalence experiment.",
        "",
        "The netlists are **flattened**, so each is one module named exactly "
        "like the DUT. The gate-level TB is a generated copy with the DUT's "
        "`#(.PARAM(v))` override removed; `run_gatelevel.py` parses the "
        "override first and fails if it differs from the synthesised default.",
        "",
        "Gate-level dumps: `results/gl_dump_*.csv` and `gl_rtl_dump_*.csv`; "
        "raw simulator output: `results/gl_tb_*.log` (build products, "
        "gitignored; uploaded as CI artifacts).",
    ]
    details = [r for r in rows if r["status"] != "PASS"]
    if details:
        lines += ["", "## Failure details", ""]
        lines += [f"- `{r['tb']}` ({r['status']}): {r['note']}" for r in details]
    lines += [
        "",
        "## Status",
        "",
        (f"**PASS** - {len(rows)} netlists replayed; RTL and gate-level "
         "agree bit-exactly on the reduced vector set."
         if not failed else "**FAIL** - " + "; ".join(failed)),
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
