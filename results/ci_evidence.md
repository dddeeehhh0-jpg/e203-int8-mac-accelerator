# CI evidence - first real RTL simulation

Repository: `dddeeehhh0-jpg/e203-int8-mac-accelerator` (private), branch `main`,
workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## 1. Timeline

| # | Commit | Actions run | Conclusion | Note |
|---|---|---|---|---|
| 1 | `73fd21e4b89d6b5a2d5ecb36468ff36ea239c617` | [43226072305](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43226072305) | failure | First real RTL execution: **all six testbenches passed**, but the independent scoreboard reported 9 mismatches in `dump_top_stream.csv`. |
| 2 | `a8639b0067223c500a9a711b0e0fbf773c8ec37b` | [43226906536](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/runs/43226906536) | **success** | Scoreboard fixed to follow the handshake protocol. No RTL changed. |

Run 1 is kept on purpose: it proves the very first CI run was a **real
simulation** (`iverilog` was installed and all six testbenches produced dumps),
not a skipped one. The defect was in the checker, not in the RTL.

### What run 1 actually found

`int8_mac_top` keeps its output data register while `m_valid == 0`, so idle,
stall, reset and drain beats carry the previous `y`. That payload is a protocol
don't-care and `tb_top_stream` correctly skips it. The scoreboard originally
compared the whole 10-bit `{valid, y[7:0], sat}` word on every cycle, so it
flagged 9 idle cycles. Inspection of the CI artifact confirmed **all 9 had
`valid = 0` on both expected and actual**, with zero mismatches on valid
cycles. `model/check_results.py` now always compares the valid bit and compares
the full word on valid cycles; a second mutation test asserts that a wrong
payload on a valid cycle and a wrongly asserted valid bit are still caught.
No RTL source was modified to make CI green. See
[`docs/verification.md`](../docs/verification.md) section 1.

## 2. Run 2 environment

| Item | Value |
|---|---|
| Runner | `ubuntu-latest` |
| Python | 3.11.18 (`actions/setup-python@v5`) |
| Simulator | Icarus Verilog **12.0 (stable)**, installed via `apt-get install iverilog` |
| Grammar checker | pyverilog (pip) |
| Command | `python3 run_regress.py --strict` |
| Started / finished | 2026-11-12 13:23:55Z / 13:24:32Z |

All job steps succeeded: Set up job, Checkout, Set up Python,
**Install Icarus Verilog and optional grammar checker**,
**Full regression (RTL simulation mandatory)**, Upload evidence.

## 3. Six testbenches (run 2, real simulation)

| Testbench | Result | Points |
|---|---|---|
| `tb_mac_pe` | PASS | 65,536 |
| `tb_mac_array` | PASS | 5,004 |
| `tb_requant` | PASS | 17,459 |
| `tb_top_stream` | PASS | 24 cycles |
| `tb_nice_adapter` | PASS | 13 commands |
| `tb_soc_stub` | PASS | 12 layers |

## 4. Independent scoreboard (RTL dumps re-read by Python)

| Dump | Points | Mismatches |
|---|---|---|
| `dump_mac_pe.csv` | 65,536 | 0 |
| `dump_mac_array.csv` | 5,004 | 0 |
| `dump_requant.csv` | 17,459 | 0 |
| `dump_top_stream.csv` | 24 | 0 |
| `dump_nice_adapter.csv` | 13 | 0 |
| `dump_soc_stub.csv` | 12 | 0 |

Both checker mutation tests PASS (`errors=1, first=2` and `errors=2, first=2`).

## 5. Regression summary emitted by run 2

```text
PASS  int8_ref.py self-test
PASS  gen_vectors.py determinism
PASS  check_results.py --verify-vectors
PASS  rtl_lint.py
PASS  verilog_parse_check.py grammar
PASS  RTL simulation (6 TBs)
PASS  check_results.py (RTL dumps)
```

`--strict` turns a skipped simulation into a failure, so a green run cannot be
produced by a host without `iverilog`.

## 6. Where the raw evidence lives

- Actions run 2 page (above) holds the full job log.
- Artifact `regression-evidence` of run 2 holds `results/tb_*.log`,
  `results/dump_*.csv`, `results/lint_report.txt`, `results/parse_report.txt`,
  `results/regression_summary.md` and `vectors/gen/manifest.csv`.
- `results/regression_summary.md` committed at `73fd21e` is the **author's
  Windows host** snapshot and still shows `SKIPPED` for RTL simulation. That is
  expected: no simulator was available locally. The authoritative RTL result
  is run 2 on GitHub Actions, not that local snapshot.

## 7. Scope boundaries

- This CI demonstrates that the **six self-checking testbenches of this
  clean-room repository** compile, elaborate and pass under Icarus Verilog.
- It is **not** full-chip verification of the related contest project, not
  gate-level replay, not timing closure and not a power measurement.
- No power number is claimed here. Any local accelerator-only figure mentioned
  in [`docs/case_study.md`](../docs/case_study.md) belongs to the team project
  and is not a system power number.
