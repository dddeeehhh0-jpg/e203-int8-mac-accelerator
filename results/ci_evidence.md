# CI evidence - real RTL simulation, synthesis and gate-level replay

Repository: `dddeeehhh0-jpg/e203-int8-mac-accelerator` (private), branch `main`,
workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

**Reference green run: [43238295802](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43238295802)**
on commit `1399057a00f756c0ab571546e33bd136c4dc9069` — this is the run that
introduced and validated the full chain. All three `--strict` steps succeeded:
full RTL regression, real Yosys synthesis, and post-synthesis gate-level
replay of five flattened netlists. Later commits are documentation-only and
keep the same three steps green (e.g. run
[43239632568](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43239632568));
the Actions tab is the up-to-date list, so no "latest run" claim is frozen
into this file.

---

## 1. Full timeline (failures kept on purpose)

| # | Commit | Actions run | Conclusion | Note |
|---|---|---|---|---|
| 1 | `73fd21e` | [43226072305](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43226072305) | failure | First real RTL simulation: **all six TBs passed**, but the scoreboard reported 9 mismatches in `dump_top_stream.csv`. |
| 2 | `a8639b0` | [43226906536](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43226906536) | **success** | Scoreboard fixed to follow the ready/valid protocol. No RTL changed. |
| 3 | `dd2a777` | [43228025533](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43228025533) | **success** | Evidence/badge commit; regression stayed green. |
| 4 | `e0ea56e` | [43232254680](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43232254680) | failure | RTL regress + synthesis green, but all five gate-level compiles failed. |
| 5 | `b493b32` | [43233148388](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43233148388) | failure | Two netlists replayed and PASS; `tb_requant` zero-delay gate simulation timed out after 300 s. |
| 6 | `1399057` | [43238295802](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43238295802) | **success** | Three `--strict` steps all green; 5/5 netlists bit-exact vs RTL. |

Run 1 is retained because it proves the first CI run was a **real simulation**
(iverilog installed, six dumps produced), not a skipped one. Runs 4 and 5 are
retained because they are the honest record of what the first gate-level
attempt actually did.

---

## 2. What each failure found (and exactly what was fixed)

**Run 1 - checker, not RTL.** `int8_mac_top` keeps its output data register
while `m_valid == 0`. That payload is a protocol don't-care, which
`tb_top_stream` deliberately skips. The scoreboard compared the whole 10-bit
`{valid, y[7:0], sat}` word and flagged 9 idle/stall/reset/drain cycles.
Artifact inspection confirmed all 9 had `valid = 0` on BOTH sides and zero
mismatches on valid cycles. `model/check_results.py` now always compares the
valid bit and compares the full word on valid cycles; a second mutation test
asserts a wrong payload on a valid cycle and a wrongly asserted valid are
still caught. **No RTL source was modified.**

**Run 4 - two structural causes.** (a) `write_verilog` emitted a hierarchy whose
first module was a `$paramod...` child, so there was no plain `<top>` module to
instantiate; (b) the TBs instantiate the DUT with `#(.PARAM(v))` while a
flattened structural netlist has no parameters. Fix: add `flatten` to the
synthesis flow (one module per DUT, ports intact) and generate a TB copy whose
override is stripped **after** parsing it and asserting it equals the
synthesised default. Compile stderr is now recorded in the report.

**Run 5 - simulation cost, not a functional error.** `tb_mac_pe` (65,536
points) and `tb_mac_array` (5,004 points) already passed with
`scoreboard_err=0` and `rtl_vs_gl_diff=0`. The 17,459-point zero-delay requant
netlist expands the 32x16 multiplier into thousands of gate primitives and
exceeded the 300 s per-simulation limit. Fix: gate replay became an
**equivalence experiment** - it runs BOTH an RTL reference and the netlist on
the same vectors and compares them, and `tb_requant` uses a 204-point boundary
subset (12 representative `r32` scales x all 17 `acc` edges). The full
17,459-point sweep stays in `run_regress.py --strict`. Because the TBs
hard-code `N_VEC`, generated TB copies for both runs are patched to the reduced
loop bound, with a consistency check against the full corpus first so a short
vector file cannot silently look like a PASS.

---

## 3. Latest green run environment

| Item | Value |
|---|---|
| Runner | `ubuntu-latest` |
| Python | 3.11.18 (`actions/setup-python@v5`) |
| Simulator | Icarus Verilog **12.0 (stable)** (`apt-get install iverilog`) |
| Synthesis | **Yosys 0.70** via pinned `yowasp-yosys==0.70.0.0.post1259` |
| Grammar checker | pyverilog (pip) |
| Started / finished | 2026-11-12 14:32:46Z / 14:36:00Z |
| Conclusion | **success** (all 8 job steps) |

Job steps: Set up job, Checkout, Set up Python, **Install simulator /
synthesis tool / grammar checker**, **Full RTL regression (simulation
mandatory)**, **Logic synthesis (generic cells, NO PDK / NO PPA)**,
**Gate-level replay of the synthesised netlists**, Upload evidence - all
`success`.

`--strict` turns a skipped simulation, a missing synthesis tool or a skipped
replay into a **failure**, so a green badge cannot be produced by a host that
did not run all three.

---

## 4. RTL regression (step 5)

| Testbench | Result | Points |
|---|---|---|
| `tb_mac_pe` | PASS | 65,536 |
| `tb_mac_array` | PASS | 5,004 |
| `tb_requant` | PASS | 17,459 |
| `tb_top_stream` | PASS | 24 cycles |
| `tb_nice_adapter` | PASS | 13 commands |
| `tb_soc_stub` | PASS | 12 layers |

Independent Python scoreboard on the six RTL dumps: 0 mismatches on all six
(88,048 points total). Both checker mutation tests PASS.

---

## 5. Real logic synthesis (step 6)

`python3 syn/run_synth.py --strict` - Yosys generic mapping, flattened
structural netlists, **no PDK**.

| Top | Generic cells | FF bits | Cell kinds | Netlist sha256 (prefix) |
|---|---:|---:|---:|---|
| `mac_pe` | 456 | 0 | 4 | `5328e36ad792` |
| `mac_array` | 4,928 | 0 | 4 | `797d6a8a1a8f` |
| `acc_stage` | 338 | 33 | 5 | `8832d896d863` |
| `requant` | 3,856 | 11 | 7 | `a94f58f9d1a9` |
| `int8_mac_top` | 9,479 | 88 | 8 | `1167c6f9fe82` |
| `nice_adapter` | 9,268 | 184 | 7 | `1d5d14d0c092` |

Result line: `PASS synthesis: 6 tops, 0 latches, 8 generic cell types`.
`hierarchy -check` / `check` report no undriven or multiply-driven nets.
`sram_beh.v` and `mac_soc_stub.v` are behavioural and **excluded**.

> These are **generic gate counts, not PPA**: no um^2, no Fmax, no power, no
> STA, no SDC, no corners. Cell counts are relative complexity indicators for
> this clean-room demo only.

---

## 6. Gate-level replay (step 7)

`python3 run_gatelevel.py --strict` - five netlists compiled with the
hand-written zero-delay models in `syn/generic_cells.v`. For each TB an RTL
reference and the netlist run on the **same** vectors in isolated directories;
five mandatory checks: RTL `RESULT PASS`, gate `RESULT PASS`, independent
scoreboard on the RTL dump, independent scoreboard on the gate dump, and a
row-by-row bit-exact comparison of the two ACTUAL columns under the same
ready/valid protocol rule.

| Testbench | Netlist top | Points | RTL scoreboard | Gate scoreboard | RTL-vs-gate diffs |
|---|---|---:|---:|---:|---:|
| `tb_mac_pe` | `mac_pe` | 65,536 | 0 | 0 | 0 |
| `tb_mac_array` | `mac_array` | 5,004 | 0 | 0 | 0 |
| `tb_requant` | `requant` | 204 (subset) | 0 | 0 | 0 |
| `tb_top_stream` | `int8_mac_top` | 24 | 0 | 0 | 0 |
| `tb_nice_adapter` | `nice_adapter` | 13 | 0 | 0 | 0 |

Final line: `PASS gate-level replay: 5/5 netlists match the RTL bit-for-bit`.
Only `tb_requant` uses the reduced set; the other four keep their full vectors.
`tb_soc_stub` is not synthesised (behavioural SRAM + host FSM), so it is
RTL/behavioural evidence only.

---

## 7. Where the raw evidence lives

- [Run 43238295802](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43238295802)
  holds the full job log; a local copy of that log is kept outside the
  repository as `.tools/ci_run_final.log` (gitignored).
- Artifact `regression-evidence` of that run holds `results/` (RTL dumps,
  lint/parse/regression summary, `synthesis_report.md`,
  `gatelevel_report.md`, `gl_*` dumps and simulator logs),
  `vectors/gen/manifest.csv`, the flattened `syn/out/*_net.v`, the Yosys logs
  and `netlist_manifest.csv`.
- The committed `results/regression_summary.md` and
  `results/gatelevel_report.md` are the **author's Windows host** snapshots:
  no `iverilog` there (installer blocked by the OS security policy), so both
  say `SKIPPED` and are explicitly labelled *not authoritative*. The real
  Yosys synthesis did run on that host, so `results/synthesis_report.md` is a
  genuine local result. **The CI artifact is authoritative for simulation and
  replay.**

---

## 8. Scope boundaries

- This CI proves the six self-checking testbenches of this clean-room
  repository pass under Icarus Verilog, that six modules elaborate into generic
  gate-level netlists with no latches, and that five of those netlists compute
  the same values as the RTL on the replayed vector set.
- It is **not** full-chip verification of the related contest project, **not**
  formal RTL-vs-netlist equivalence, **not** timing closure, **not** a coverage
  number, **not** a PPA measurement and **not** silicon validation.
- Gate-level replay is functional equivalence on a finite vector set under a
  zero-delay behavioural primitive model. No SDF, no delays, no PDK.
- No power number is claimed here. Any local accelerator-only figure in
  [`docs/case_study.md`](../docs/case_study.md) belongs to the separate team
  project and is not a system power number.


---

## 9. Formal job (added 2026-11-14)

A fourth mandatory CI job, `formal`, runs
`python3 formal/run_formal.py --strict` on `ubuntu-latest`. It installs Z3 and
the `yowasp-yosys` package, then executes four SymbiYosys jobs:

| Job | Expected | What it proves |
|---|---|---|
| `requant_comb` | PASS | k-induction: RTL requant == independent 51-bit reference, unbounded over all 2^48 `(acc,r32)` pairs |
| `requant_comb_bad` | FAIL + VCD | negative control, rounding bias removed |
| `stream_protocol` | PASS | k-induction: 6 ready/valid safety properties |
| `stream_protocol_bad` | FAIL + VCD | negative control, `s_ready` forced high |

A positive proof that fails, a mutation that unexpectedly passes, or a missing
counterexample makes the job fail. The `formal-evidence` artifact holds the
generated `.sby` configs, console logs, solver status and VCD counterexamples.

**Boundary:** these proofs concern this repository's RTL only. They are NOT
RTL-vs-netlist formal equivalence, NOT full-chip verification, NOT liveness and
NOT a coverage number. The gate-level replay described in sections 1-8 remains
a finite 204-point boundary subset. Full assumptions, tool versions, commands
and source hashes: [`formal_report.md`](formal_report.md) and
[`../formal/README.md`](../formal/README.md).
