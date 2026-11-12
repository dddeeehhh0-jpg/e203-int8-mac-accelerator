# Verification

## 1. Principle

> One number, one evidence file. A testbench never computes its own golden
> value, and a checker is not trusted until it has been shown to catch a bug.

The chain has four independent layers:

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

The scoreboard itself is mutation-tested: `--selftest` injects one wrong value
into a synthetic dump and asserts that exactly one mismatch is reported at the
correct index. A checker that always prints PASS is worthless.

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
| `model/verilog_parse_check.py` | pyverilog (optional) | a **real LALR parse** of all 14 `.v` files; useful on hosts without a simulator |

Neither is a substitute for elaboration or simulation. `results/lint_report.txt`
and `results/parse_report.txt` say so in plain text.

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
testbenches were **not executed locally**. `.github/workflows/ci.yml` installs
`iverilog` on `ubuntu-latest` and runs `python3 run_regress.py --strict`,
which fails if simulation is skipped. Once that job is green, the claim
"the six testbenches pass" is backed by `results/tb_*.log` and
`results/dump_*.csv` uploaded as CI artifacts.

`results/regression_summary.md` is regenerated on every run and records this
status automatically. Nothing is hard-coded as "passed".

---

## 5. What is deliberately NOT claimed

- **No coverage percentage.** A functional-corpus count is not code coverage;
  without a commercial coverage tool the honest answer is "not measured".
- **No formal proof.** There is no assertion-based formal run or equivalence
  check against a netlist in this repository.
- **No gate-level replay.** That belongs to the team project described in
  `docs/case_study.md`, not here.
- **No PPA numbers from this repository.** `syn/` is logic-level only.

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
