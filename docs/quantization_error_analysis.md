# Fixed-point error analysis (rounding, saturation, width, bias)

Companion to `docs/fixed_point_design.md`. Every claim here is about the
**bit-exact arithmetic in `rtl/mac/requant.v`**, validated by
`model/int8_ref.py` and `vectors/gen/requant_scan.hex`. It is deliberately
*not* a statistical accuracy claim - see [§7 Scope](#7-scope-what-this-is-not).

---

## 1. The exact arithmetic contract

```
T      = acc * r32                 (mathematical integer, signed)
q      = T + 2^(SHIFT-1)          (SHIFT = 16, so +32768)
y_pre  = q >>> SHIFT              (ARITHMETIC right shift = floor(q / 2^16))
y      = clip(y_pre, -128, 127)
sat    = (y_pre > 127) | (y_pre < -128)
```

`acc` is the signed 32-bit running sum **including bias** (added by
`int8_mac_top` on the first beat of a group). `r32` is a 16-bit **unsigned
real multiplier**, not a power-of-two shamt. Both operands are extended to
signed `Q_W` bits before the multiply; that is essential, because mixing an
unsigned operand into a Verilog multiply silently makes the whole expression
unsigned.

---

## 2. Width proof (why Q_W = 49 is enough)

| Term | Bound |
|---|---|
| `acc` (signed 32 b) | `abs(acc) <= 2^31` |
| `r32` (unsigned 16 b) | `r32 < 2^16` |
| `T = acc*r32` | `abs(T) < 2^47` |
| `q = T + 2^15` | `abs(q) < 2^47 + 2^15 < 2^48` |

A signed 49-bit container represents `[-2^48, 2^48-1)`, so `q` cannot
overflow. `Q_W = ACC_W + R32_W + 1 = 32 + 16 + 1 = 49` is derived, not a magic
number. The RTL declares `localparam integer Q_W = ACC_W + R32_W + 1` and
`wire signed [Q_W-1:0] q`.

Accumulator headroom: one lane product is bounded by `128*128 = 16384`;
eight lanes give `abs(sum) <= 131072 < 2^18`. A 32-bit accumulator therefore
admits roughly `2^31 / 2^18 = 16384` worst-case beats before overflow.
`acc_stage` widens to 33 bits to detect signed overflow and raises a **sticky**
`ovf` flag (cleared only by reset or `clear`). Note the limitation: `ovf` is
exposed only as `dbg_ovf` in the top - it does **not** raise an interrupt or
alter the result. That is a documented simplification (§7).

---

## 3. Rounding: what `+32768` then `>>>` really does

Let `x = T / 2^16` (the exact, un-rounded real value in output LSB units).

```
y_pre = floor((T + 2^15) / 2^16) = floor(x + 0.5)
```

This is **round-to-nearest with ties toward +infinity**, implemented as
`floor(x+0.5)`. Properties worth being able to derive at a whiteboard:

- Quantisation error `e = y_pre - x` satisfies `-0.5 < e <= +0.5`.
- It is **not** round-half-to-even and **not** round-half-away-from-zero.
  At a tie: `x = +0.5 -> y_pre = +1`, but `x = -0.5 -> y_pre = 0` (not `-1`).
  Negative ties are biased upward by one output LSB. This is a real,
  asymmetric bias near zero introduced by choosing an arithmetic shift
  (floor) instead of a sign-aware rounding correction.
- Why keep it anyway? It is one adder constant, no sign-dependent control,
  fully combinational, deterministic, and the bias is bounded by 1 LSB and
  only occurs on exact ties (`T mod 2^16 == 2^15`). For a symmetric
  alternative one would need `T>=0 ? +2^15 : +(2^15-1)`, a convergent
  (round-half-even) scheme, or stochastic rounding - each costs logic.
- `>>>` is **arithmetic**, so it is `floor`, not truncation toward zero.
  Using `>>` on a signed value would still be arithmetic in Verilog when the
  operand is signed, but writing `>>>` makes the intent explicit and is what
  the bit-exact Python model mirrors. Confusing the two is a classic bug:
  truncation toward zero would give a different negative-side error curve.

**Saturation error is the one that is NOT bounded.** If `abs(y_pre)` exceeds
the INT8 range, `clip` introduces an error that can be arbitrarily large
relative to `x`. That is why `sat` exists as an observable flag and why `r32`
must be calibrated so that normal activations stay inside the range. A design
that saturates frequently has a broken scale, not a rounding problem.

---

## 4. Why saturation happens exactly once

`mac_array` returns the exact signed sum with **no clipping**; `acc_stage`
accumulates with no clipping; `requant` clips **only at the output to INT8**.
Intermediate clipping would inject a truncation error into every subsequent
layer of the 12-layer chain. The single-clip rule is what makes the bit-exact
model and the RTL agree layer after layer.

The flip side: a 32-bit accumulator overflow (`ovf`) is detected but **not**
corrected. In a real product you would either widen the accumulator or
saturate the accumulate; here it is a debug signal by design.

---

## 5. Choosing `r32`: real multiplier vs power-of-two shift

A legacy-style requantiser uses `y = (acc + 2^(s-1)) >> s`, i.e. only scales
by powers of two. That is cheap (a shifter) but can only represent scales
`2^-s`, so post-training per-layer scales must be snapped to the nearest power
of two - a coarse approximation.

This design uses a **16-bit real multiplier** `acc * r32`, so `r32/2^16` can
approximate an arbitrary per-layer scale to ~15-16 bits of relative
precision. That is the single most important accuracy/area trade-off in the
project, and it is visible in the synthesis numbers: `requant` alone maps to
~3.9k generic cells (the 32x16 multiply, the rounding adder, the shift and
the saturation comparators), while a pure power-of-two shifter would be a few
dozen. See `results/synthesis_report.md`.

Where `r32` comes from: **outside this repository.** It is a runtime
configuration register loaded through `cfg_valid/cfg_r32` (or the
NICE-style `SET_R32` command). This project supplies the arithmetic and the
write path; it performs **no calibration**, uses **no dataset** and reports
**no accuracy metric**. Do not attach any contest accuracy figure to it.

---

## 6. How this is verified bit-exactly

`vectors/gen/requant_scan.hex` = **17,459 points**: every `r32` in `0..1024`
plus `32767` and `65535` (1,027 values), crossed with 17 `acc` edges
(`0, +/-1, +/-32768, +/-32769, +/-65536, +/-131072, +/-2^31, ...`), including
exact tie values `32768`, `32769`, `-32768`, `-32769` and the full-scale
`2^31-1`/`-2^31` cases. `tb_requant` compares the RTL against the Python
model; `check_results.py --verify-vectors` independently recomputes all
17,459 goldens from the raw operands; the gate-level replay repeats the same
sweep on the synthesised netlist. Positive saturation, negative saturation,
rounding ties and the linear region are all covered (see
`docs/functional_coverage.md`).

---

## 7. Scope (what this is NOT)

- **No statistical accuracy claim.** There is no NRMSE, no PSNR, no
  dataset-level metric in this repository. Error bounds here are
  *per-operation worst-case* bounds, not end-to-end network accuracy.
- **No end-to-end error bound for the 12-layer chain.** Each layer adds at
  most ~0.5 LSB of rounding error, but those errors are amplified by the next
  layer's weights. Bounding the accumulated error requires a dataset and a
  statistical argument, which this clean-room demo does not have.
- **No contest numbers.** The 600-sample validation results, the 3% threshold
  discussion, the per-layer `r32` lists and the 0.462 mW local power figure
  belong to a *different* team project and appear only (labelled, scoped) in
  `docs/case_study.md`. They must never be quoted as properties of this RTL.
- **No floating-point reference.** The model is integer-only; there is no
  FP32 golden in this repository.
