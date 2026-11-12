# Functional scenario coverage (a checklist, NOT code coverage)

> **Read this first:** this is a list of **functional scenarios** that the
> directed/exhaustive vectors exercise. It is **NOT** statement / branch /
> toggle / FSM code coverage. There is no commercial coverage tool in this
> project, no coverage database and **no coverage percentage is claimed
> anywhere**. Line counts below are vector points, not coverage numbers.

Generated vectors: `model/gen_vectors.py` (deterministic, seed-fixed).
Recomputed independently: `model/check_results.py --verify-vectors`.
Simulated: `tb/*.v` under Icarus Verilog in CI.
Replayed on synthesised netlists: `run_gatelevel.py`.

---

## 1. Exhaustive / boundary scenarios

| Scenario | Where | Points | What it proves |
|---|---|---:|---|
| **Every** INT8 x INT8 product | `pe_full.hex`, `tb_mac_pe` | 65,536 | 256 x 256 full cross-product, including `-128 x -128 = 16384`, sign extremes and zero |
| Adder tree, random + extremes | `array_rand.hex`, `tb_mac_array` | 5,004 | 4 hand-picked extreme vectors (all `+127`/`-128`) + 5,000 seeded random; exact signed sum, no intermediate clip |
| Requantisation sweep | `requant_scan.hex`, `tb_requant` | 17,459 | 1,027 `r32` values (`0..1024`, `32767`, `65535`) x 17 `acc` edges |

The 17 `acc` edges are `0, 1, -1, 32767, 32768, 32769, -32768, -32769,
65535, 65536, -65536, 131072, -131072, 2^31-1, -2^31, 1234567, -987654`.
They deliberately include:

- exact rounding ties (`32768`, `-32768`) and their neighbours;
- both INT8 saturation boundaries in both directions;
- `r32=0` (zero scale), `r32=1`, `r32=65535` (max scale);
- full-scale signed accumulator values.

So the rounding bias near zero, positive saturation, negative saturation and
the linear region are all exercised bit-exactly. See
`docs/quantization_error_analysis.md`.

---

## 2. Streaming / handshake scenarios (`top_seq.hex`, 24 beats)

| # | Scenario | Beats | Expected behaviour checked |
|---|---|---|---|
| 1 | Power-on reset | t0 | all valid flags de-asserted, config reset to `r32=1,bias=0` |
| 2 | Config load, priority over data | t1, t13 | `cfg_valid=1` -> `s_ready=0`, `r32`/`bias` updated atomically |
| 3 | Multi-beat group (accumulate) | t2..t4 | three beats, `s_last` only on the last; bias added on the first |
| 4 | Back-to-back single-beat groups | t5, t6+t7 | 1 result/clock with no dead cycle (`clear` = restart from `din`) |
| 5 | Sustained backpressure | t8..t10 | three consecutive `m_ready=0` beats; `s_ready` drops, pipeline freezes, `m_valid`/payload held |
| 6 | Drain / resume | t11 | `m_ready=1` releases the stall without losing or duplicating a result |
| 7 | Config reload mid-stream | t12 | `r32` 1024 -> 512, `bias` 7 -> -3, followed by a fresh group |
| 8 | **Reset asserted mid-stream** | t13 | `rst_n=0` while traffic is in flight; no stuck valid, clean restart |
| 9 | Post-reset group + idle drain | t14..t23 | a fresh group, then idle beats to drain the pipeline |

The TB checks `m_valid`, `m_y`, `m_sat` (packed into a 10-bit word),
`s_ready` and the idle/drain behaviour. Invalid-cycle payload is a protocol
don't-care and is skipped by both the TB and the scoreboard
(see `docs/timing_handshake.md` §4).

---

## 3. Command-path scenarios (`nice_seq.hex`, 13 commands)

| funct7 | Command | Cases exercised |
|---|---|---|
| `01` | `SET_R32` | scale load |
| `02` | `SET_BIAS` | bias load |
| `03` / `04` | `LOAD_X` / `LOAD_W` | 8 packed INT8 operands from `{rs2,rs1}` |
| `05` | `MAC` | compute one group, latch INT8 result |
| `06` | `READ` | pop the sign-extended result |
| `7f` | **unknown funct7** | `nice_rsp_err=1`, `rsp_data=32'hDEAD_BEEF` |

All five classes of **illegal sequence** are interleaved with the one legal
setup/compute/read sequence (13 commands total):

1. `MAC` with nothing configured;
2. `MAC` after `SET_R32` but before `SET_BIAS`/operands;
3. `MAC` before `LOAD_X`/`LOAD_W`, and `MAC` with X but without W;
4. `READ` with no result latched, and `READ` again after the result was
   already consumed;
5. an unknown `funct7`.

Every illegal command must set `nice_rsp_err=1` and return `ERR_WORD`.
`nice_expect.hex` holds the independent golden for the single computed result;
each `nice_seq.hex` row also encodes the expected `err` and `data`.

---

## 4. End-to-end host / 12-layer scenarios (`tb_soc_stub`)

- `soc_mem.hex`: 1,024 words of behavioural SRAM image, laid out as
  12 layers x 5 words per layer (2 words of packed INT8 activations `x`,
  2 words of packed INT8 weights `w`, 1 word of `{r32[15:0], bias[15:0]}`),
  plus the output area. The TB reads it back with `$readmemh`.
- `soc_expect.hex`: 12 golden rows `layer acc32 y8 sat`.
- 11 layers use seeded random small weights; **the final layer is deliberately
  driven into saturation** (`w = +/-127/-128`, `r32=1024`, `bias=30000`) so
  the end-to-end path exercises both the linear region and the saturation
  path, not just the easy case.
- The FSM is checked for `busy`/`done`, `layer_valid`, a timeout guard, and
  one result per layer.

**Scope:** this uses the *behavioural* SRAM and host FSM, which are
**not synthesised**. It is RTL/behavioural-level evidence of a 12-layer chain,
not full-chip verification and not a gate-level result. `run_gatelevel.py`
deliberately excludes `tb_soc_stub` and says so in its report.

---

## 5. Independent checks (not scenarios, but part of the evidence chain)

| Check | File | Notes |
|---|---|---|
| Bit-exact model self-test (8 exhaustive checks) | `model/int8_ref.py` | runs on every `make regress` |
| Vector generation determinism | `run_regress.py` | generate twice, compare sha256 |
| Golden recomputation from raw operands | `check_results.py --verify-vectors` | independent of `gen_vectors.py`; 88k+ points |
| Checker mutation tests (2) | `check_results.py --selftest` | wrong value / wrong valid bit must be caught |
| Structural lint | `model/rtl_lint.py` | no latches, no undriven/multi-driven nets by construction |
| Grammar parse | `model/verilog_parse_check.py` | all `.v` sources incl. `syn/generic_cells.v` |
| Generic-cell synthesis + latch check | `syn/run_synth.py` | 6 tops, 0 latches, cell manifest |
| Gate-level replay (**5 checks x 5 netlists**) | `run_gatelevel.py` | RTL reference + netlist on the same vectors; both scoreboards pass and the two ACTUAL columns match bit-exactly. `tb_requant` uses a 204-point subset, full 17,459-point sweep stays at RTL level |

---

## 6. What is deliberately NOT covered

- Statement / branch / condition / toggle / FSM coverage (no tool, no number).
- Formal properties (no SVA, no `smtbmc` proof).
- CDC, reset de-assertion synchronisation, recovery/removal timing.
- Timing closure, STA, SDC, corners, parasitics, power intent (UPF/CPF).
- Real memory macros, real bus fabric, interrupts, DMA.
- Statistical network accuracy (no dataset, no NRMSE, no FP32 reference).
- Multi-clock, low-power, DFT/scan, physical design.

Adding any of these would require a real toolchain and/or a legitimate
library; this clean-room demo states that openly rather than implying it.
