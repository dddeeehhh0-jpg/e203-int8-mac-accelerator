# Regression summary

- Generated: `2026-11-12T21:23:17+08:00`
- Platform: `Windows 11`, Python `3.13.14`
- Simulator: `not installed on this host`
- Command: `python3 run_regress.py` (or `make regress`)

> This file is generated. Do not edit by hand. Every PASS below is
> derived from a process exit code or a file produced in this run.

| Step | Status | Evidence |
|---|---|---|
| int8_ref.py self-test | PASS | 8 checks; PASS  wrap_signed: 32-bit two's-complement rollover |
| gen_vectors.py determinism | PASS | two runs produced identical sha256 manifests |
| check_results.py --verify-vectors | PASS | checker mutation test: PASS (errors=1, first=2); PASS    pe_full.hex golden                  points=65536; PASS    array_rand.hex golden               points=5004; PASS    requant_ |
| rtl_lint.py | PASS | files   : 14; modules : 14; errors  : 0 |
| verilog_parse_check.py grammar | PASS | 14 files parsed; failures=0 |
| RTL simulation (6 TBs) | SKIPPED | iverilog/vvp not available on this host |
| check_results.py (RTL dumps) | SKIPPED | no dumps (simulation not run) |

## Testbench detail

| Testbench | Status | Result line |
|---|---|---|
| (none) | SKIPPED | No iverilog/vvp on this host; see CI job. |

## Evidence index

- `results/lint_report.txt` — structural lint
- `results/parse_report.txt` — optional pyverilog grammar parse
- `results/tb_*.log` — raw simulator output (only when simulation ran)
- `results/dump_*.csv` — point-by-point RTL vs golden (only when simulation ran)
- `vectors/gen/manifest.csv` — sha256 of every generated corpus
- `.github/workflows/ci.yml` — Linux CI with iverilog installed

## Honest status on this host

**RTL simulation was NOT executed here** (no `iverilog`/`vvp`).
The Python model, deterministic vectors, independent golden
recomputation and structural lint all ran and passed; the six
Verilog testbenches are compiled and run by the CI job on
`ubuntu-latest`. Do not quote this run as RTL-verified.
