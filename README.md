# E203-Based INT8 MAC Accelerator (clean-room demo)

[![regress](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/workflows/ci.yml/badge.svg)](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/workflows/ci.yml)

*The badge is visible to signed-in viewers while the repository is private.*

A small, independently written INT8 MAC channel: 8 parallel signed multiply
lanes, a 32-bit accumulator, `r32` requantization with round-to-nearest and a
single output saturation, plus a NICE-style command adapter and a minimal
host FSM that runs a 12-layer feed-forward chain end to end. Every datapath
rule has a bit-exact Python reference model, deterministic vectors and a
self-checking Verilog testbench.

> **This repository is not the contest project.** It contains no E203 core,
> no official NICE RTL, no PDK, no netlist, no dataset and no trained weights.
> See [What is NOT included](#what-is-not-included) and
> [docs/PUBLICATION_AUDIT.md](docs/PUBLICATION_AUDIT.md).

---

## Status

Read this first. "Done" always points at a file you can open.

| Component | Status | Evidence |
|---|---|---|
| Bit-exact Python model | Done, 8 exhaustive self-checks | `model/int8_ref.py` |
| Deterministic vector corpus | Done, 8 files with sha256 | `vectors/gen/manifest.csv` |
| Independent golden recomputation | Done (88k+ points) | `model/check_results.py --verify-vectors` |
| 8 RTL modules | Written, grammar-parsed 14/14 | `results/parse_report.txt` |
| Structural lint | Done, 0 errors | `results/lint_report.txt` |
| 6 self-checking testbenches | **PASS, 6/6** in real simulation (Icarus Verilog 12.0) | [`results/ci_evidence.md`](results/ci_evidence.md) |
| CI regression on Linux | **Green** — run `43226906536`, `--strict`, 6 TBs + scoreboard all PASS | [`results/ci_evidence.md`](results/ci_evidence.md), `.github/workflows/ci.yml` |
| Logic-level synthesis | Yosys script + DC template only; **no PDK, no PPA numbers** | `syn/` |
| Documentation | Done | `docs/` |

**Honest caveat:** on the author's Windows host, `iverilog`/`vvp` could not be
installed (the installer was blocked by the OS security policy), so the six
Verilog testbenches were **not run locally** — the local snapshot in
`results/regression_summary.md` says `SKIPPED`. They were executed for real on
GitHub Actions (`ubuntu-latest`, Icarus Verilog 12.0): all six PASS, and the
independent Python scoreboard reports 0 mismatches on all six RTL dumps.
Full per-TB results, run IDs, commit hashes and the (failed, then fixed) first
run are recorded in [`results/ci_evidence.md`](results/ci_evidence.md). The fix
was in the checker, not in the RTL.

---

## Why this design

- **INT8, not FP16** — activations and weights fit in one byte. That halves
  memory traffic and lets a lane be a single small multiplier. The premise is
  that quantisation error stays acceptable, which is why the requantizer is
  the most heavily tested module in this repository.
- **32-bit accumulator** — with 8 lanes, `|sum| <= 8 * 16384 = 131072 < 2^18`,
  so thousands of groups can be accumulated before a 32-bit accumulator is
  even close to overflow. No intermediate clipping, so truncation error does
  not compound across layers.
- **`r32` as a real multiplier, not a shift** — `1 << shamt` can only express
  powers of two. A 16-bit runtime scale approximates an arbitrary per-layer
  scale continuously. This is the one design decision with the most
  interview-relevant trade-off (one multiplier vs. much better scale fit).
- **One saturation, at the output** — saturating between layers would inject
  clipping error into the next layer's activations.

---

## Architecture

![Architecture: host, adapter, streaming channel, datapath](docs/images/fig1_architecture.png)

The host (`mac_soc_stub`) reads a 5-word-per-layer record from a behavioural
SRAM, configures the channel, pushes one group of 8 lane pairs, waits for the
INT8 result, feeds it back as the next layer's activations and writes all
results back to memory. `nice_adapter.v` is an alternative integration path:
a request/response command interface with explicit rejection of illegal
sequences. Both paths use the **same** `requant.v` arithmetic — the adapter
taps the module's combinational outputs instead of duplicating the formula.

---

## Fixed-point contract

![Dataflow and widths](docs/images/fig2_dataflow.png)

```
acc   = sum_i(x_i * w_i) + bias          // wrap to signed 32 bits
q     = acc * r32 + 2^15                // wrap to signed 49 bits
y_pre = q >>> 16                        // ARITHMETIC right shift
y     = clip(y_pre, -128, 127)          // saturate ONCE
```

| Signal | Width | Format | Note |
|---|---|---|---|
| `x[i]`, `w[i]` | 8 | signed INT8 | lane `i` = `[i*8 +: 8]` |
| lane product | 16 | signed | `(-128)*(-128)=16384` still fits |
| `acc` | 32 | signed | includes bias, no intermediate clip |
| `r32` | 16 | unsigned | runtime scale, typically 1..1024 |
| `q` | 49 | signed | `2^31 * 2^16 + 2^15 < 2^48` |
| `y` | 8 | signed INT8 | `sat_flag` reports clipping |

`+2^15` is round-to-nearest, not truncation: truncation adds a systematic
negative bias to every layer. `>>>` (not `>>`) keeps negative intermediates
correct. The r32-sweep testbench checks both boundaries explicitly.

Full derivation and the width proof: [docs/fixed_point_design.md](docs/fixed_point_design.md).

---

## Verification

![Verification flow](docs/images/fig3_verification.png)

The rule is **one number, one evidence file**. Golden values are produced by
`model/int8_ref.py`; the testbenches never recompute them. A separate Python
scoreboard re-reads the RTL dumps so a bug inside a testbench cannot hide.

| Testbench | Coverage | Points |
|---|---|---|
| `tb_mac_pe` | all 256x256 signed products | 65,536 |
| `tb_mac_array` | 5,000 random groups + 4 extremes | 5,004 |
| `tb_requant` | r32 0..1024 + 32767/65535 x 17 acc boundaries | 17,459 |
| `tb_top_stream` | 24 cycle-accurate beats: cfg, back-to-back groups, stall, mid-stream reset | 24 |
| `tb_nice_adapter` | 1 legal sequence + 5 illegal classes | 13 commands |
| `tb_soc_stub` | 12-layer end-to-end, including write-back memory | 12 layers |

Real output from `python3 run_regress.py` on the author's host:

```text
PASS  mac_pe: all 65536 signed 8x8 products exact
PASS  requant: round-to-nearest boundary on positive and negative q
PASS  requant: arithmetic shift for negative intermediates
checker mutation test: PASS (errors=1, first=2)
PASS    pe_full.hex golden                  points=65536
PASS    array_rand.hex golden               points=5004
PASS    requant_scan.hex golden             points=17459
PASS    soc_expect.hex vs soc_mem.hex       points=12
PASS    nice_expect.hex golden              points=1
PASS    nice_seq.hex consistency            points=13
PASS    manifest.csv sha256                 points=8
[WARN] iverilog/vvp not found -> RTL simulation SKIPPED on this host.
  PASS     rtl_lint.py
  PASS     verilog_parse_check.py grammar
  SKIPPED  RTL simulation (6 TBs)
```

Real output from `python3 run_regress.py --strict` on GitHub Actions
(run `43226906536`, commit `a8639b0`) — **this is the authoritative RTL result**:

```text
Icarus Verilog version 12.0 (stable)
RESULT tb_mac_pe PASS
RESULT tb_mac_array PASS
RESULT tb_requant PASS
RESULT tb_top_stream PASS
RESULT tb_nice_adapter PASS
RESULT tb_soc_stub PASS
PASS    dump_mac_pe.csv        points=65536  mismatches=0
PASS    dump_mac_array.csv     points=5004   mismatches=0
PASS    dump_requant.csv       points=17459  mismatches=0
PASS    dump_top_stream.csv    points=24     mismatches=0
PASS    dump_nice_adapter.csv  points=13     mismatches=0
PASS    dump_soc_stub.csv      points=12     mismatches=0
  PASS     RTL simulation (6 TBs)
  PASS     check_results.py (RTL dumps)
```

No coverage percentage is claimed: there is no commercial coverage tool in
this project. See [docs/verification.md](docs/verification.md) and
[`results/ci_evidence.md`](results/ci_evidence.md).

---

## What is NOT included

1. **No E203 core and no official NICE implementation.** `nice_adapter.v` is
   a simplified, independently written NICE-*style* adapter with its own
   funct7 encoding. Semantics are not the official ones.
2. **No PDK, no SRAM macro, no netlist, no gate-level replay.** `sram_beh.v`
   is a behavioural model; `syn/` is logic-level only.
3. **No dataset, no trained weights, no audio.** All stimuli are generated
   deterministically from `SEED = 20261112`.
4. **No contest source code, no screenshots, no server paths.** The related
   team project is described only as method and conclusions in
   [docs/case_study.md](docs/case_study.md).

---

## Quick start

Only `python3` is required for the host-side checks. `iverilog` is required
for the RTL testbenches.

```bash
# Actually executed on the author's host (Windows, Python 3.13):
python3 model/int8_ref.py                              # model self-test
python3 model/gen_vectors.py                           # deterministic corpus
python3 -m pip install pyverilog                       # optional grammar check
python3 model/check_results.py --verify-vectors --selftest
python3 model/rtl_lint.py
python3 run_regress.py                                  # full pipeline + summary
```

On Linux (or in CI), where `iverilog` is available:

```bash
# runs in .github/workflows/ci.yml (green in run 43226906536); not run locally
sudo apt-get install -y iverilog
python3 run_regress.py --strict     # fails if RTL simulation is skipped
make regress                        # equivalent entry point
make parse                          # pyverilog grammar check, 14 files
```

`--strict` is what CI uses: it turns "simulation skipped" into a failure, so
a green CI badge means the six testbenches really ran.

---

## Repository map

| Path | Contents |
|---|---|
| `rtl/mac/` | `mac_pe`, `mac_array`, `acc_stage`, `requant` |
| `rtl/top/` | `int8_mac_top` (streaming), `nice_adapter` (command path) |
| `rtl/memory/` | behavioural single-port SRAM |
| `rtl/soc_stub/` | minimal host FSM driving 12 layers |
| `model/` | reference model, vector generator, scoreboard, lint, grammar check |
| `tb/` | 6 self-checking Verilog testbenches |
| `vectors/smoke/` | 12 committed hand-written examples |
| `vectors/gen/` | generated corpus (gitignored, reproducible) |
| `syn/` | Yosys script and a DC template with the library path left blank |
| `docs/` | architecture, fixed-point, verification, limitations, audit; `make_figures.py` regenerates the 3 PNGs |
| `results/` | generated lint / parse / regression reports |

---

## Related work

Only the *organisation* of these repositories was studied; no code, figure or
README text was copied.

- [riscv-mcu/e203_hbirdv2](https://github.com/riscv-mcu/e203_hbirdv2) — Apache-2.0, the upstream E203 SoC (not vendored here).
- [GregAC/tiny-nn](https://github.com/GregAC/tiny-nn) — the `rtl / dv / model` split and a two-level testbench structure.
- [AnilS454/pe-asic-sky130](https://github.com/AnilS454/pe-asic-sky130) — writing optimisation as a causal chain rather than a bare percentage.

---

## License

MIT, see [LICENSE](LICENSE). Replace the copyright holder with your own name
before publishing.
