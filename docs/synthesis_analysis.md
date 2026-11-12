# Synthesis analysis (scope and limits)

## 1. What this repository actually contains

| File | Purpose | Requires |
|---|---|---|
| `syn/synth_yosys.ys` | generic **logic-level** mapping, prints a `stat` cell-count table | Yosys, no library |
| `syn/dc_template.tcl` | a Design Compiler template with the library path deliberately left blank | your own `.db`/`.lib`, a license |

**No PDK, no standard-cell library, no netlist, no parasitics, no timing
report and no power report are in this repository.** Consequently there is no
area in um^2, no Fmax in MHz and no power in mW that belongs to this project.
Any such number you may see in `docs/case_study.md` comes from a *different*,
team project and is labelled as such.

---

## 2. What the Yosys script can and cannot tell you

```
yosys -s syn/synth_yosys.ys
```

It runs `read_verilog`, `hierarchy -check`, `proc`, `opt`, `techmap` and
`stat`, then writes a structural JSON/RTLIL dump. The output is a count of
**generic** cells (`$add`, `$mul`, `$mux`, `$dff`, ...), useful for:

- confirming the design elaborates without undriven or multiply-driven nets;
- seeing that `mac_array.v` really produced 8 multipliers and a balanced
  adder tree rather than a serial chain;
- comparing two versions of *this* RTL against each other (relative cell
  counts under the same script).

It is **not** useful for:

- comparing with a synthesised PDK netlist (no drive strength, no cap, no
  wireload, no real cell areas);
- quoting an absolute area or a clock period;
- claiming timing closure.

The script prints a comment saying exactly this. Do not strip it.

---

## 3. How to talk about an optimisation properly

Bad: "area went down 11%".
Good: "narrowing the requantization scale from 16 bits to 10 bits narrowed the
multiplier and its operand registers; that shortened the critical path through
the multiply-add stage and reduced cell count. The improvement is a
consequence of the width change, not of a tool switch."

That causal chain (width -> operator/register -> path -> result) is what an
interviewer is actually testing for. It is also why `requant.v` keeps every
width as a parameter with a written proof in `docs/fixed_point_design.md`
rather than magic constants.

If you later run a real synthesis, record it as a table with the exact
library, corner, constraints and script hash alongside the numbers. A number
without that context is not evidence.

---

## 4. DC template

`dc_template.tcl` contains placeholder variables at the top:

```tcl
set TARGET_LIBRARY ""     ;# fill in with YOUR OWN .db path
set LINK_LIBRARY   ""     ;# fill in
set CLOCK_PERIOD   6.67   ;# ns, example only
```

It is a scaffold, not a runnable flow. It is provided so that someone with a
legitimate library can start from a clean script instead of from this
repository's guesses. Committing a vendor library here would be both a licence
problem and a contest-rule problem, so it is explicitly listed in
`.gitignore`.
