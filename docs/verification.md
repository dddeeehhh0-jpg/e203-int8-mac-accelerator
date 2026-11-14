# Verification

## 1. Principle

> One number, one evidence file. A testbench never computes its own golden
> value, and a checker is not trusted until it has been shown to catch a bug.

The chain has five independent layers:

1. **Model self-test** — `model/int8_ref.py` checks the arithmetic contract on
   exhaustive and boundary inputs (all 65,536 signed 8x8 products, rounding
   boundaries, arithmetic-shift behaviour, both saturation ends, 32-bit wrap).
2. **Corpus generation** — `model/gen_vectors.py` writes 8 deterministic files
   from `SEED = 20261112` and records sha256 for each in
   `vectors/gen/manifest.csv`. Running the generator twice must produce the
   same manifest; `run_regress.py` enforces that.
3. **Independent golden recomputation** —
   `model/check_results.py --verify-vectors` re-derives every golden value
   from the raw inputs. For the 12-layer case it reads the parameters back out
   of `soc_mem.hex` and re-runs the recurrence, a genuinely different path
   from the generator that wrote the file.
4. **RTL vs golden** — the six Verilog testbenches dump
   `results/dump_*.csv`; `model/check_results.py` re-reads those dumps and
   reports the first mismatch with its index. A bug in a testbench's own
   comparison cannot hide, because the scoreboard is a separate program.
5. **RTL vs synthesised netlist** — `syn/run_synth.py` produces flattened
   generic netlists, and `run_gatelevel.py` runs an RTL reference and the
   gate-level netlist on the *same* vectors, applying five mandatory checks
   per TB (section 4a). This is functional equivalence on a finite vector
   set, not formal equivalence.

The scoreboard itself is mutation-tested: `--selftest` injects one wrong value
into a synthetic dump and asserts that exactly one mismatch is reported at the
correct index. A checker that always prints PASS is worthless.

**Streaming dumps follow the handshake protocol, not blind equality.**
`tb_top_stream` packs `{valid, y[7:0], sat}` into one 10-bit word. While
`valid == 0` the payload is a don't-care: `int8_mac_top` keeps the previous
data register instead of clearing it, so idle, stall, reset and drain beats
can legitimately carry a stale `y`. The scoreboard therefore always compares
the valid bit and compares the full word on valid cycles, but ignores the
held payload on idle cycles. This is not a way to hide a bug: `--selftest`
also injects a wrong payload on a valid cycle and a wrongly asserted valid
bit, and asserts that both are still reported. The rule was added after the
first real CI run flagged 9 false mismatches, all of them idle cycles with
`valid = 0` on both expected and actual.

---

## 2. Testbenches

| # | TB | Stimulus | Pass criterion | Points |
|---|---|---|---|---|
| 1 | `tb_mac_pe` | all 256x256 signed combinations | 0 mismatch vs `pe_full.hex` | 65,536 |
| 2 | `tb_mac_array` | 5,000 random groups + 4 extremes | 0 mismatch vs `array_rand.hex` | 5,004 |
| 3 | `tb_requant` | r32 0..1024, 32767, 65535 x 17 acc boundaries; `valid_o`/`last_o` alignment | y, `sat_flag` and handshake all match | 17,459 |
| 4 | `tb_top_stream` | 24 cycle-accurate beats: cfg, 3-beat group, back-to-back groups, 3 stalled cycles, cfg reload, mid-stream reset, drain | `s_ready` pre-edge and `m_valid`/`m_y`/`m_sat` post-edge match on every cycle | 24 |
| 5 | `tb_nice_adapter` | 13 commands: legal sequence + 5 illegal classes | all 5 illegals rejected, legal READ returns the Python result | 13 |
| 6 | `tb_soc_stub` | 12-layer chain from a memory image | 12 layer outputs AND 12 write-back words match | 12 |

Every TB is self-checking, prints `RESULT <name> PASS|FAIL`, writes a dump and
calls `$finish`. `run_regress.py` compiles all RTL files explicitly with
`iverilog -g2012` (no library search path surprises) and runs each with `vvp`.

---

## 3. Additional static checks

| Check | Tool | What it catches |
|---|---|---|
| `model/rtl_lint.py` | stdlib | missing `default_nettype` guards, unbalanced `module`/`generate`/brackets, filename != module name, instances of undefined modules |
| `model/verilog_parse_check.py` | pyverilog (optional) | a **real LALR parse** of all 15 `.v` files (including `syn/generic_cells.v`); useful on hosts without a simulator |
| `syn/run_synth.py` | Yosys 0.70 | `hierarchy -check`, `flatten`, `check`, `stat`; 0 latches, 0 connectivity problems, per-netlist sha256 |

Neither static check is a substitute for elaboration or simulation.
`results/lint_report.txt`, `results/parse_report.txt` and
`results/synthesis_report.md` say so in plain text.

---

## 4. What actually ran, and where

On the author's Windows host (Python 3.13):

```text
PASS  mac_pe: all 65536 signed 8x8 products exact
PASS  requant: round-to-nearest boundary on positive and negative q
PASS  requant: arithmetic shift for negative intermediates
PASS  requant: saturation hi/lo and saturation flag
PASS  requant: non-power-of-two r32 scales are representable
PASS  mac_array: all-max and all-min lane extremes
PASS  pack/unpack: lane ordering preserved
PASS  wrap_signed: 32-bit two's-complement rollover
checker mutation test: PASS (errors=1, first=2)
PASS    pe_full.hex golden                  points=65536
PASS    array_rand.hex golden               points=5004
PASS    requant_scan.hex golden             points=17459
PASS    soc_expect.hex vs soc_mem.hex       points=12
PASS    nice_expect.hex golden              points=1
PASS    nice_seq.hex consistency            points=13
PASS    top_seq.hex field count             points=24
PASS    manifest.csv sha256                 points=8
  PASS     int8_ref.py self-test
  PASS     gen_vectors.py determinism
  PASS     check_results.py --verify-vectors
  PASS     rtl_lint.py
  PASS     verilog_parse_check.py grammar
  SKIPPED  RTL simulation (6 TBs)
```

**The last line is important.** `iverilog`/`vvp` could not be installed on
that host (the OS security policy blocked the installer), so the six Verilog
testbenches and the gate-level replay were **not executed locally**. The
committed `results/regression_summary.md` and `results/gatelevel_report.md`
are that host's snapshots, both labelled `SKIPPED` / not authoritative. The
**real Yosys synthesis** did run on this host (`results/synthesis_report.md`).

`.github/workflows/ci.yml` runs three mandatory `--strict` steps on
`ubuntu-latest` (Icarus Verilog 12.0 + pinned Yosys 0.70 + pyverilog):

```
python3 run_regress.py --strict        # 6 TBs + scoreboard
python3 syn/run_synth.py --strict      # real generic-cell synthesis
python3 run_gatelevel.py --strict      # 5 netlists replayed
```

Any skipped step fails the job. The latest green run `43238295802` (commit
`1399057`) executed all three `--strict` steps: six testbenches all printed
`RESULT ... PASS` with 0 scoreboard mismatches on all six dumps (88,048
points), six tops synthesised with 0 latches, and **5/5 flattened netlists
replayed bit-exactly** (per-TB points and all five checks in
`results/gatelevel_report.md`). The first run (`43226072305`) failed for the
protocol reason described in section 1; the fix was in the checker, not in the
RTL. Two further CI failures (netlist hierarchy / parameter overrides, and
gate-replay simulation cost) were fixed from the real logs. All run IDs,
commit hashes, cell counts and logs are in
[`results/ci_evidence.md`](../results/ci_evidence.md).

---

## 4a. Gate-level replay, precisely

Two simulations per TB on the **same** vector file, in isolated directories:

| # | Check | Must be |
|---|---|---|
| 1 | RTL reference prints `RESULT <tb> PASS` | true |
| 2 | gate-level netlist prints `RESULT <tb> PASS` | true |
| 3 | independent scoreboard on the RTL dump | 0 errors |
| 4 | independent scoreboard on the gate dump | 0 errors |
| 5 | RTL ACTUAL column == gate ACTUAL column, row by row | 0 differences |

`run_gatelevel.py` generates a TB copy with the DUT parameter override removed
(after asserting the override equals the synthesised default), because a
flattened netlist has no parameters. A zero-delay netlist expands the 32x16
multiplier into thousands of gates, so the gate-level requant sweep uses a
**204-point boundary subset** (12 representative `r32` x all 17 `acc` edges);
the full 17,459-point sweep remains in the RTL regression. The TBs hard-code
their loop bound in `N_VEC`, so the generated copies for **both** runs are
patched to the reduced count; `patch_vec_count()` first verifies that the
original bound equals the full corpus size and fails loudly otherwise. A short
vector file therefore cannot silently produce a false PASS. This is an
equivalence experiment, not a second full regression, and
`results/gatelevel_report.md` records the reduced point count. `tb_soc_stub`
is excluded: its behavioural SRAM and host FSM are not synthesised.

---

## 5. What is deliberately NOT claimed

- **No coverage percentage.** A functional-corpus count is not code coverage;
  without a commercial coverage tool the honest answer is "not measured".
  `docs/functional_coverage.md` is a scenario checklist only.
- **No RTL-vs-netlist formal equivalence and no full-chip formal proof.**
  The SymbiYosys work in `formal/` proves two scoped RTL properties only; it
  is not `equiv_make`/`equiv_induct` equivalence, not liveness and not a
  coverage number. Gate-level replay remains simulation on a finite
  204-point vector set.
- **No PDK PPA from this repository.** Generic cell counts are not um^2, Fmax
  or power; there is no STA, no SDC, no timing closure.
- **No full-chip or silicon verification.** Six testbenches plus a gate-level
  replay of five small modules is not full-chip verification. The contest
  numbers in `docs/case_study.md` belong to a different team project.

---

## 6. Reproducing a failure on purpose

A quick sanity check that the chain is live:

```bash
python3 model/gen_vectors.py
python3 model/check_results.py --selftest
# then flip one hex digit in vectors/gen/array_rand.hex and run:
python3 model/check_results.py --verify-vectors
# -> FAIL with a nonzero count, because the manifest/golden no longer matches
```

Restoring the file is as simple as re-running `python3 model/gen_vectors.py`.
