# Fixed-point design

This document is the derivation behind `rtl/mac/requant.v` and
`model/int8_ref.py`. They implement exactly the same contract:

```
acc   = wrap32( sum_i( s8(x_i) * s8(w_i) ) + s16(bias) )
q     = wrap49( acc * u16(r32) + 2^15 )
y_pre = q >>> 16                       // arithmetic shift
y     = clip(y_pre, -128, 127)
```

`wrapN` is two's-complement wrap to a signed N-bit value; Python integers are
unbounded, so the model performs the wrap explicitly to stay bit-exact with
the RTL.

---

## 1. Width proof

| Step | Worst case | Required bits |
|---|---|---|
| `s8 * s8` | `(-128)*(-128) = +16384`, `(-128)*(127) = -16256` | 16 (15 would be enough; 16 keeps slicing clean) |
| 8-lane sum | `8 * 16384 = 131072 < 2^18` | 18 |
| + bias | `131072 + 32767 < 2^18` | 18 |
| running accumulation | 32-bit signed holds >16,000 worst-case groups | 32 |
| `acc * r32` | `< 2^31 * 2^16 = 2^47` | 48 |
| `+ 2^15` | still `< 2^48` | 49 signed (`Q_W = ACC_W + R32_W + 1`) |
| `>>> 16` | `< 2^32`, compared against 127 / -128 | 8 after saturation |

That extra `+1` in `Q_W` is not padding: a 48-bit signed value tops out at
`2^47 - 1`, while `acc*r32` can reach `2^47`. Every operand in the multiply
expression is declared `signed` in the RTL. In Verilog, a single unsigned
operand silently promotes the whole expression to unsigned arithmetic, which
would break negative `acc` completely.

---

## 2. Why `+ 2^15` (round-to-nearest, not truncation)

`q >>> 16` is a division by 65536 with floor rounding. Adding half a divisor
before the shift turns floor into round-to-nearest:

| `acc*r32` | no rounding | with `+32768` | exact |
|---|---|---|---|
| `32768` | 0 | **1** | 0.5 |
| `65536` | 1 | 1 | 1.0 |
| `-32768` | -1 | **0** | -0.5 |
| `-32769` | -1 | -1 | -0.500015 |

Without the constant, every layer would inherit a systematic negative bias of
roughly -0.5 LSB. Over 12 layers that bias compounds. `model/int8_ref.py`
self-test asserts these four cases, and `tb_requant` sweeps 17,459
`(acc, r32)` combinations against the Python golden.

Note the negative case: Python's `>>` and Verilog's `>>>` are both arithmetic
(floor for negative values), while Verilog's `>>` would be a logical shift.
Using the wrong operator is the single most common bug in this datapath.

---

## 3. Why saturation happens once

Saturation is a **non-linear** operation. Clipping `acc` between layers would
inject an irreversible error into the next layer's activations, and the error
would be amplified by that layer's `r32`. Here the accumulator stays a plain
32-bit sum; only the final INT8 output is clipped, and `sat_flag` records that
it happened so a system can react (for example by re-calibrating `r32`).

`tb_soc_stub` deliberately drives the last layer into saturation, so the
end-to-end check covers both the linear region and the clipping path.

---

## 4. Why `r32` is a multiplier, not a shift amount

A shift-based requantizer can only express scales of `2^k`. If the true
per-layer scale is 192/65536, the closest powers of two are 128/65536 and
256/65536 — an error of 25% or 33% on that layer. A 16-bit runtime scale
represents 192 exactly. The cost is one `32 x 16` multiplier per output, which
is paid **once per group**, not once per lane: 8 lanes share one requantizer.

This is the trade-off to be able to defend in an interview:

| | Shift-only | `r32` multiplier |
|---|---|---|
| Scale granularity | powers of two | any integer 0..65535 |
| Area | shifter + wiring | one multiplier |
| Calibration | discrete search | continuous least-squares fit |
| Runtime update | change `shamt` register | change `r32` register |

`tb_requant` sweeps `r32 = 0..1024` plus `32767` and `65535` precisely to
prove that non-power-of-two values behave as a real scale.

---

## 5. What this model does NOT claim

- It is an **integer** model of a linear layer, not a model of network
  accuracy. There is no accuracy claim in this repository.
- It does not model a training pipeline, per-channel quantization, zero-point
  offsets, or floating-point reference inference.
- Width wrapping is implemented but never exercised at overflow in the
  generated corpus: realistic groups stay far below `2^31`. The overflow flag
  in `acc_stage` is defensive, not a verified claim about 12-layer worst cases.

---

## 6. Relationship to the contest design

The contest project used a similar family of ideas (INT8 MAC, 32-bit
accumulation, a runtime requantization scale, single output saturation) on an
E203 + NICE platform. This repository is a **clean-room re-implementation**:
the module partition, interface encoding, width choices and verification
strategy here are independently designed for teaching and reproducibility.
In particular, bias is folded into `din` here and applied at a different point
in the contest RTL. Do not treat the two implementations as the same code.
