# Resume wording and interview prep

Everything below must remain defensible. Do not upgrade "written + CI
configured" into "verified on silicon", and do not attach the team project's
PPA numbers to this repository.

---

## Chinese resume (3 lines)

> 独立实现 INT8 MAC 加速器开源工程（Verilog + Python 位精确参考模型）：8 lane
> 乘加阵列、32 位累加、r32 再量化与单次饱和；6 个自检 testbench、
> 确定性向量与独立逐点比对脚本，一条命令完成回归。
> 另在 E203 + NICE 团队项目中负责 12 层前馈网络线性层的 RTL、定点方案、
> 门级回放与综合（团队项目，数字见项目文档）。

## English resume (3 lines)

> Built a clean-room INT8 MAC accelerator (Verilog + bit-exact Python model):
> 8-lane array, INT32 accumulation, r32 requantization with single-stage
> saturation, six self-checking testbenches and a point-by-point scoreboard
> driven by one `run_regress.py`.
> On a team project, designed the RTL and fixed-point scheme for a 12-layer
> FFN accelerator on an E203 + NICE platform, and carried it through gate-level
> replay and Design Compiler synthesis.

---

## 30-second version

Say three things: **what** it computes (the linear layers of a 12-layer
feed-forward net), **where the difficulty is** (fixed-point rounding and the
coprocessor interface overhead), **how it was checked** (point-by-point
comparison against a bit-exact Python model, plus gate-level replay on the team
project).

## 1-minute version

Add the iteration story and the boundary: V1 -> V2 -> V3, why the scale field
was narrowed from 16 to 10 bits (all 12 calibrated values were below 1024),
what that did to the multiplier and timing, and what is still not done (no
PDK-based PPA in the open repository, no full-chip verification claim).

---

## Eight likely interview questions

1. **Why INT8 rather than FP16?** Bandwidth (one byte per operand), multiplier
   area, and energy; the premise is that quantisation error stays within the
   layer's budget. Point at `docs/fixed_point_design.md`.
2. **Why a 32-bit accumulator?** Derive the bound: `8 * 128 * 128 = 131072 <
   2^18`; thousands of groups fit comfortably in INT32. Width proof in the
   same document.
3. **What does `+ 2^15` do before `>>> 16`?** Round-to-nearest instead of
   floor. Truncation adds a systematic -0.5 LSB bias per layer. Show the
   four-row table in `fixed_point_design.md`.
4. **Why saturate only once?** Intermediate clipping is irreversible and would
   be amplified by the next layer's scale. `sat_flag` is reported, not hidden.
5. **Why `r32` instead of a shift amount?** `1 << shamt` only represents powers
   of two; a 16-bit runtime scale fits arbitrary per-layer scales. Cost: one
   multiplier per group, shared by all 8 lanes.
6. **How does the coprocessor interface work?** req/rsp handshake, config and
   operands separated from the compute command, and illegal sequences rejected
   with an error response. Stress that this is NICE-*style*, not official NICE.
7. **How do you keep RTL and the software model consistent?** One written
   integer contract; Python exhaustive self-test first; deterministic vectors
   with sha256; independent golden recomputation; RTL dumps re-checked by a
   separate scoreboard; a mutation test proves the checker can fail.
8. **How did you reduce area?** As a causal chain: narrower scale field ->
   narrower multiplier and operand registers -> shorter path / fewer cells.
   Never "we changed a tool option". Note that this repository itself has no
   PPA numbers.

---

## Two answers to have ready (they are traps)

- *"Did you verify the whole chip?"* -> No. Module-level 12-layer continuous
  inference passed; SoC level was **sampled**. See `docs/case_study.md`.
- *"What was the power?"* -> 0.462 mW was **accelerator-and-interface local**,
  not full-chip. The preliminary round did not require full-chip power.

## One honest caveat to volunteer

The six Verilog testbenches are run by CI on Linux, not on the author's Windows
host. Say so before being asked; it reads as rigour, not as a gap.
