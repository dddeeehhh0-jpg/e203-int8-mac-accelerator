# Logic-level synthesis report

Generated: 2026-11-12 13:55:47 UTC
Tool: Yosys 0.70
Command: `python3 syn/run_synth.py`
Flow: `read_verilog -sv` -> `hierarchy -check` -> `proc` -> `opt` -> `techmap` -> `opt` -> `setundef -zero` -> `opt` -> `check` -> `stat` -> `write_verilog -noattr -noexpr -nohex`

> **SCOPE / DO NOT OVERCLAIM.** This is **generic gate-level mapping without a PDK or a standard-cell library**. Cell counts are **not** area in um^2, **not** Fmax, **not** a clock period and **not** power. No SDC, no parasitics, no corners, no timing closure. These numbers belong to this clean-room demo only and must never be quoted as the contest chip's PPA.

## What is and is not synthesised

| Item | In synthesis? | Reason |
|---|---|---|
| 6 synthesizable modules (`mac_pe`, `mac_array`, `acc_stage`, `requant`, `int8_mac_top`, `nice_adapter`) | YES | real RTL |
| `sram_beh.v`, `mac_soc_stub.v` | **NO** | simulation-only behavioural memory array + hierarchical `$readmemh` init; not a memory macro, not hardware. Their 12-layer chain is verified at RTL/behavioural level by `tb_soc_stub` only |

## Per-top results

| Top | Testbench for gate-level replay | Total generic cells | Sequential bits (`$_DFF*`) | Netlist sha256 (12) |
|---|---|---:|---:|---|
| `mac_pe` | `tb_mac_pe` | 456 | 0 | `5328e36ad792` |
| `mac_array` | `tb_mac_array` | 4928 | 0 | `dac24501dc49` |
| `acc_stage` | (leaf, synthesis-only) | 338 | 33 | `8832d896d863` |
| `requant` | `tb_requant` | 3856 | 11 | `a94f58f9d1a9` |
| `int8_mac_top` | `tb_top_stream` | 9700 | 88 | `50772fe4007d` |
| `nice_adapter` | `tb_nice_adapter` | 9284 | 195 | `850940965e41` |

### Generic-cell breakdown

| Top | `$_AND_` | `$_DFFE_PN0N_` | `$_DFFE_PN0P_` | `$_DFFE_PN1P_` | `$_MUX_` | `$_NOT_` | `$_OR_` | `$_XOR_` |
|---|---|---|---|---|---|---|---|---|
| `mac_pe` | 222 | 0 | 0 | 0 | 0 | 8 | 70 | 156 |
| `mac_array` | 793 | 0 | 0 | 0 | 0 | 8 | 402 | 533 |
| `acc_stage` | 115 | 0 | 33 | 0 | 66 | 0 | 59 | 65 |
| `requant` | 1956 | 2 | 9 | 0 | 17 | 33 | 583 | 1256 |
| `int8_mac_top` | 3083 | 2 | 84 | 2 | 164 | 44 | 1149 | 1980 |
| `nice_adapter` | 2871 | 2 | 192 | 1 | 46 | 58 | 1070 | 1852 |

- **Latches: 0** (required: 0 - fully synchronous design).
- Undefined primitives: 0 (required: 0).
- `check` found no undriven / multiply-driven nets in any top.

## Reading the numbers

`requant` is the most expensive block because it contains the `acc(32b) x r32(16b)` requantization multiplier, the +32768 rounding adder, the arithmetic shift and the INT8 saturation comparators. `mac_array` is the second: eight signed 8x8 multipliers plus a signed adder tree. `nice_adapter` and `int8_mac_top` include both, so their counts are approximately the sum, plus the FSM/config registers. That causal chain (operator width -> cell count) is the design argument; there is NO area figure here.

## Source / artefact integrity

| Source RTL | sha256 (16) |
|---|---|
| `rtl/mac/mac_pe.v` | `31f6064ff5d351c6` |
| `rtl/mac/mac_array.v` | `f4c510f11b1410f2` |
| `rtl/mac/acc_stage.v` | `029938b229a3fb82` |
| `rtl/mac/requant.v` | `0271445fdd1d0a97` |
| `rtl/top/int8_mac_top.v` | `b6f60c81a2afed64` |
| `rtl/top/nice_adapter.v` | `10db018b966ccc63` |

Full netlist hashes: `syn/out/netlist_manifest.csv` (generated; netlists themselves are gitignored build products).

## Status

**PASS** - synthesis completed, 6/6 tops mapped, 0 undefined primitives, 0 latches.

Gate-level replay of these netlists is a separate step: `python3 run_gatelevel.py --strict`. A green synthesis run alone does NOT prove the netlist computes the same values as the RTL.
