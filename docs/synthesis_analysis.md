# Synthesis analysis (real generic mapping: results, scope and limits)

> **Status changed.** This repository used to contain only synthesis *scripts*.
> It now runs a **real Yosys logic-level mapping** in CI and on the author's
> host, produces structural netlists, and replays them in simulation. The
> numbers are real - but they are **generic gate counts, not PPA**. Read the
> scope box below before quoting anything.

---

## 1. What is actually run

```
python3 syn/run_synth.py --strict     # real synthesis
python3 run_gatelevel.py --strict     # replay the synthesised netlists
```

Flow (`syn/run_synth.py`, tool pinned to Yosys 0.70 via `yowasp-yosys`):

```
read_verilog -sv (6 synthesizable files)
  -> hierarchy -check -top <top>
  -> proc -> opt -> techmap -> opt -> flatten -> opt
  -> setundef -zero -> opt -> check -> stat
  -> write_verilog -noattr -noexpr -nohex
```

Six tops are mapped: `mac_pe`, `mac_array`, `acc_stage`, `requant`,
`int8_mac_top`, `nice_adapter`. `flatten` makes each netlist a **single module
named after the DUT with its ports intact** (without it Yosys emits a
`$paramod...` hierarchy that no plain testbench can instantiate). `setundef
-zero` removes X literals so the netlist is deterministic in simulation.

Outputs (all generated, deterministic):

| File | Content |
|---|---|
| `syn/out/<top>_net.v` | flattened structural netlist (gitignored build product, uploaded as CI artifact) |
| `syn/out/<top>_yosys.log` | full tool log including `check` and `stat` |
| `syn/out/netlist_manifest.csv` | per-netlist sha256 + byte count |
| `results/synthesis_report.md` | per-top cell counts, sequential bits, source hashes, scope box |

`check` reported **0 problems on all six tops** (no undriven / multiply-driven
nets) and the mapped netlists contain **0 latches** - the design is fully
synchronous. `run_synth.py` fails loudly if a future Yosys emits a generic
primitive that has no model in `syn/generic_cells.v`, or if any latch appears.

Exact cell counts are in `results/synthesis_report.md` (regenerated every
run). As an order of magnitude: `mac_pe` ~0.5k, `mac_array` ~4.9k,
`requant` ~3.9k, `int8_mac_top` ~9.5k, `nice_adapter` ~9.3k generic cells.

---

## 2. What the gate-level replay adds

A netlist made of `\$_AND_` / `\$_DFFE_*` instances cannot be simulated
without primitives. `syn/generic_cells.v` defines them **by hand** (zero-delay
behavioural models), keeping the repository clean-room and letting the tool
fail loudly on an unknown cell. `run_gatelevel.py` then:

1. generates a TB copy with the parameter override removed (after checking
   the override equals the synthesised default width);
2. runs an **RTL reference** and the **gate-level netlist** on the *same*
   vector file in isolated directories;
3. requires five checks per TB: RTL `RESULT PASS`, gate `RESULT PASS`,
   independent scoreboard on both dumps, and bit-exact equality of the two
   ACTUAL columns.

Because a zero-delay netlist expands the 32x16 requant multiplier into
thousands of gates, replaying all 17,459 requant vectors exceeded 300 s in CI
run `43233148388`. Gate replay therefore uses a **204-point boundary subset**
(12 representative `r32` scales x all 17 `acc` edges); the full 17,459-point
sweep remains in the RTL regression. The TBs hard-code `N_VEC`, so the
generated TB copies for **both** runs are patched to the reduced loop bound
after a consistency check against the full corpus. This is an *equivalence*
experiment, not a second full regression, and `results/gatelevel_report.md`
states the reduced point count explicitly. CI run `43238295802` is fully green
with 5/5 netlists bit-exact. See `docs/verification.md`,
`docs/functional_coverage.md` and `results/ci_evidence.md`.

---

## 3. What is and is NOT included - the hard scope

**Included:** generic gate-level mapping, cell counts, structural netlists,
netlist simulation, source/netlist hashes, latch and connectivity checks.

**NOT included / NOT claimed:**

- No PDK, no standard-cell library, no `.lib`/`.db`, no drive strength, no
  wireload, no capacitance.
- Therefore **no area in um^2, no Fmax, no clock period, no power in mW**.
  Cell counts are *relative complexity indicators* for this design under this
  exact script, comparable only between two runs of the same script.
- No SDC, no STA, no parasitics, no corners, no timing closure, no
  optimisation loop. `syn/dc_template.tcl` is a scaffold with an empty
  library path, not a runnable flow.
- No formal RTL-vs-netlist equivalence proof; the replay is simulation on a
  finite vector set under a zero-delay primitive model.
- `sram_beh.v` and `mac_soc_stub.v` are **simulation-only** (behavioural memory
  array + hierarchical `$readmemh`). They are explicitly excluded from
  synthesis; the 12-layer host chain is verified at RTL/behavioural level by
  `tb_soc_stub`, not at gate level.

Any um^2 / MHz / mW number you may see in `docs/case_study.md` comes from a
**different, team project** and is labelled as such. It must never be attached
to this repository, and this repository's cell counts must never be used as
the team project's PPA.

---

## 4. How to talk about an optimisation properly

Bad: "area went down 11%".
Good: "narrowing the requantisation scale from 16 bits to 10 bits narrows the
multiplier and its operand registers; that shortens the combinational path
through the multiply-add stage and reduces cell count. The improvement is a
consequence of the width change, not of a tool switch."

That causal chain (width -> operator/register -> path -> result) is what an
interviewer is testing for. It is also why `requant.v` keeps every width as a
parameter with a written proof in `docs/fixed_point_design.md` and
`docs/quantization_error_analysis.md` rather than magic constants.

The same reasoning explains the current numbers: `requant` is expensive
because of the `acc(32b) x r32(16b)` multiplier; `mac_array` is next because
of eight signed 8x8 multipliers plus a balanced adder tree; `int8_mac_top`
and `nice_adapter` contain both, so their counts are approximately the sum
plus FSM/config registers. That near-additivity is a useful sanity check on
the mapping, not an area figure.

If you later run a real PDK synthesis, record it as a table with the exact
library, corner, constraints and script hash alongside the numbers. A number
without that context is not evidence.

---

## 5. DC template

`syn/dc_template.tcl` contains placeholder variables at the top:

```tcl
set TARGET_LIBRARY ""     ;# fill in with YOUR OWN .db path
set LINK_LIBRARY   ""     ;# fill in
set CLOCK_PERIOD   6.67   ;# ns, example only
```

It is a scaffold, not a runnable flow. It is provided so someone with a
legitimate library can start from a clean script instead of this
repository's guesses. Committing a vendor library here would be both a
licence problem and a contest-rule problem, so `*.lib` / `*.db` / `pdk/` are
hard-excluded in `.gitignore`.
