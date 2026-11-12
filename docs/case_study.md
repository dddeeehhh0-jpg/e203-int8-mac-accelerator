# Case study: a team contest project (method and conclusions only)

> **Scope.** This is a *different* project from the clean-room repository you
> are reading. It was a team effort on an E203 + NICE platform. No source code,
> netlist, PDK file, dataset, screenshot, server path or teammate material
> from that project is included here. The numbers below are from internal team
> records and are **not** results reproduced by this repository's
> `run_regress.py`.
>
> The author has confirmed permission to describe this work publicly.

---

## 1. Problem and my role

Accelerate the linear layers of a 12-layer feed-forward keyword-spotting
network on an E203 core through its NICE coprocessor interface, under a
submission format that required RTL, a driver, a verification project, a
synthesis report, a numerical-format description, a software model and a
parameter-conversion script.

My work covered the INT8 MAC datapath, the fixed-point contract, the
bit-exact software model, and the verification chain from module level to
gate-level replay.

---

## 2. Design decisions (the method, not the code)

| Decision | Reason | Trade-off |
|---|---|---|
| INT8 activations/weights, 32-bit accumulation | bandwidth and multiplier area; 8 lanes worst case `8*16384 < 2^18` leaves huge headroom | requires per-layer scale calibration |
| Requantization scale as a runtime register (`r32`), not `1 << shamt` | powers of two cannot fit an arbitrary per-layer scale | one multiplier per group instead of a shifter |
| Round-to-nearest with `+2^15` before arithmetic shift | truncation injects a systematic negative bias into every layer | one extra adder |
| Saturate once, at the output | intermediate clipping compounds across 12 layers | the accumulator must be wide enough |
| Narrow the scale field from 16 to 10 bits once all 12 calibrated values were below 1024 | narrower multiplier and operand registers -> shorter path, less area | only valid while the calibrated values stay in range |

That last row is the causal chain worth remembering: the improvement was a
*consequence of the width reduction*, not of a synthesis-tool option.

---

## 3. Version chain

| Version | Role |
|---|---|
| V1 | historical baseline |
| V2 | functional control (16-bit scale field) |
| V3 | release candidate, 10-bit scale field, numerically equivalent to V2 because all 12 scale values were < 1024 |

The old power-of-two shift representation was a separate, incompatible
numerical format. Its results must never be mixed into the same table as the
`r32` results: the exponent-domain difference was 166,579 of 304,128 points.

---

## 4. Numerical results and their exact wording

The calibration set was drawn from the **training split** only (560 samples,
35 classes x 16, gradient-free calibration); the test split (11,005 samples)
never participated in parameter fitting. Public data, not an organiser-provided
evaluation set, was used for self-checking.

| Item | Value | Required qualification |
|---|---|---|
| Self-selected validation set | 600 samples, stratified from the official validation partition, seed `20261111` | **team-selected**, not the organiser's evaluation list |
| Worst 12-layer NRMSE (aggregate over the set) | **2.9975% (L5)** | margin to the 3% requirement is only **0.0025 percentage points** |
| Per-sample behaviour | some individual samples exceed 3% | disclosed in the report; an aggregate pass is not a per-sample pass |
| Organiser evaluation | not published at the time of writing | **never write "passed the organiser's evaluation"** |

The scale parameters were runtime registers: updating them did not require an
RTL change or re-synthesis.

---

## 5. Verification boundary (wording matters)

| Level | What was actually done |
|---|---|
| Module level | 12-layer continuous inference driven directly by a testbench instantiating the MAC DUTs - **no E203, NICE, SRAM, bus or driver** in that path |
| Module level | 304,128 points compared against the FP32 reference |
| SoC level | **sampling** verification, 2,816 points through the integrated path |
| Gate level | replay of 861,614 lines against the same stimulus |

Correct wording: "module-level 12-layer continuous inference passed" and
"SoC-level sampled verification". Incorrect wording: "the whole chip was fully
verified". The report was corrected to the former.

---

## 6. Implementation results (team project, internal records)

| Item | Value | Scope |
|---|---|---|
| Synthesised area | 7,945.53 um^2 | accelerator block, with the team's library and constraints |
| Timing | 150 MHz target, arrival 5.04 ns, slack +1.59 ns, 0 latches | same flow |
| Local power | 0.462 mW | **accelerator and interface local only** - NOT full-chip power |
| Power annotation completeness | SAIF: 3,417 nets / 134 ports / 12,111 pins, 100% of annotated scope | local scope only |

The preliminary round did **not** require full-chip power: the guidelines ask
for RTL, driver, verification project, synthesis report, numerical-format
description, software model and parameter-conversion script. SAIF/VCD-based
power reports are a final-round requirement. Writing 0.462 mW as chip power
would be wrong.

---

## 7. Three rules this document follows

1. No contest source code is presented as this repository's code. The RTL
   here is an independent clean-room rewrite.
2. No claim of "full-chip verification" - only module-level continuous
   inference and SoC-level sampling.
3. No claim that 0.462 mW is chip power - it is accelerator-local.

For the complete file-by-file publication audit, see
[PUBLICATION_AUDIT.md](PUBLICATION_AUDIT.md).
