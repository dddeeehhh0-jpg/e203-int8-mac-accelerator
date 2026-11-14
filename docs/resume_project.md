# Resume wording and interview prep

This document is split in two on purpose. **Section A describes only this
clean-room repository**: everything in it is reproducible here, with a file
you can open. **Section B describes the separate team contest project** and
is deliberately kept to method and conclusions. Never carry a number from B
into a sentence about A.

Hard red lines (from `docs/PUBLICATION_AUDIT.md` and `docs/interview_qa.md`):

- "six testbenches pass" means **CI-verified RTL simulation of this repository**,
  not silicon and not full-chip verification.
- Generic-cell counts are **not** area in um^2, **not** Fmax, **not** power.
- Gate-level replay here is functional equivalence on a finite vector set,
  not formal equivalence and not timing closure.
- The team project's accuracy / area / timing / power figures belong to the
  **team project** (exact values only in `docs/case_study.md`); its power
  figure is accelerator-local, not chip power.

---

## A. This repository - say it as decision / reason / result

| Decision | Reason | Result (and where to check) |
|---|---|---|
| 8 parallel INT8 lanes + one INT32 accumulator | `8 * 128 * 128 = 131072 < 2^18`, so no intermediate clipping is needed; one byte per operand halves the operand traffic vs FP16 | exhaustive 256x256 lane test, 65,536 points, 0 mismatch (`tb_mac_pe`, `results/ci_evidence.md`) |
| `r32` as a real 16-bit multiplier instead of `1 << shamt` | a shift only expresses powers of two; a runtime scale fits any per-layer scale continuously. Cost: one 32x16 multiplier per group, shared by 8 lanes | 17,459-point `r32` x `acc` boundary sweep at RTL level (`docs/quantization_error_analysis.md`) |
| `+2^15` then arithmetic `>>> 16`, and saturate only at the output | round-to-nearest (ties to +inf) instead of a systematic -0.5 LSB truncation bias per layer; intermediate clipping would be amplified by the next layer | bias derivation, exact-tie and full-scale vectors, `sat_flag` reported rather than hidden |
| ready/valid with registered output and no combinational `valid <- ready` path | backpressure without a combinational loop or a bubble on every stall | 24 cycle-accurate beats incl. stall / cfg bubble / mid-stream reset, plotted from the real stimulus (`docs/images/fig4_stream_waveform.png`) |
| Python golden + deterministic vectors + independent scoreboard | a bug inside a testbench must not be able to declare its own DUT correct | `--verify-vectors` recomputes the corpus; `check_results.py` re-reads dumps; 2 checker mutation tests prove it can fail |
| Real Yosys generic mapping + hand-written cell models + netlist replay | "I wrote a synthesis script" is not evidence; a synthesised netlist that disagrees with RTL is a real bug | 6 flattened tops, 0 latches, 8 generic cell types (`results/synthesis_report.md`); 5 netlists replayed with 5 mandatory checks each (`results/gatelevel_report.md`) |
| Gate replay uses a 204-point boundary subset for `tb_requant` | a zero-delay netlist expands the 32x16 multiplier into thousands of gates; 17,459 points exceeded 300 s in CI. Equivalence is not a second full regression | **full** 17,459-point sweep remains in `run_regress.py --strict`; the TB loop bound is patched in lockstep with the reduced corpus, and both RTL and gate runs use the same vectors |

### Chinese resume (3 lines)

> 独立实现 INT8 MAC 加速器开源工程（Verilog + Python 位精确参考模型）：8 lane
> 乘加阵列、INT32 累加、r32 再量化与单次饱和；6 个自检 testbench、
> 确定性向量与独立逐点 scoreboard，一条命令完成回归。
> 用 Yosys 真实综合 6 个顶层并展平，自写 generic cell 行为模型完成综合后网表
> 回放（RTL 与网表逐点一致）；三个 `--strict` 步骤在 GitHub Actions 全绿。
> **无 PDK、无面积/Fmax/功耗数字；门级回放不是形式等价，也不是流片验证。**

### English resume (3 lines)

> Built a clean-room INT8 MAC accelerator (Verilog + bit-exact Python model):
> 8-lane array, INT32 accumulation, `r32` requantization with single-stage
> saturation, six self-checking testbenches and an independent point-by-point
> scoreboard driven by `run_regress.py`.
> Performed real Yosys generic-cell synthesis of six tops (flattened, 0 latches)
> and post-synthesis netlist replay against the RTL using hand-written
> zero-delay cell models; regression / synthesis / replay run as three
> `--strict` CI steps. **No PDK, no PPA numbers, no formal equivalence claim.**

### 30-second version

Say three things: **what** it computes (8-lane INT8 dot product plus
requantization), **where the difficulty is** (fixed-point rounding bias and
ready/valid backpressure), **how it was checked** (bit-exact Python golden,
deterministic vectors, an independent scoreboard, and a synthesised netlist
replayed against the RTL).

### 1-minute version

Add the iteration story: the first CI run was a real simulation but the
scoreboard compared a protocol don't-care payload and reported 9 false
mismatches; the fix was in the checker, not the RTL. Later gate-level runs
exposed parameter overrides on a flattened netlist, a hierarchical `$paramod`
top and finally a simulation-cost problem. Every run ID and every fix is
recorded in `results/ci_evidence.md`.
Close with what is NOT done: no PDK, no STA, no formal equivalence, no code
coverage percentage.

---

## B. Team contest project - separate, and only in this section

May be mentioned as "on a team project" with `docs/case_study.md` as the
reference. Keep the scope qualifiers attached:

- 12-layer FFN linear layers on an E203 + NICE platform; I owned the RTL,
  the fixed-point scheme, gate-level replay and synthesis flow.
- Module-level 12-layer continuous inference passed; SoC level was **sampled**,
  not "full-chip verification passed".
- The validation set was **team-selected**; the organiser's evaluation list
  is not published. Never say "passed the organiser's evaluation".
- Any power figure is **accelerator-and-interface local**, not chip power; the
  preliminary round did not require full-chip power.

---

## Eight questions to have ready

1. **Why INT8 rather than FP16?** Bandwidth (one byte per operand), multiplier
   cost; the premise is that quantisation error stays inside the layer budget.
   `docs/fixed_point_design.md`.
2. **Why a 32-bit accumulator?** `8 * 128 * 128 = 131072 < 2^18`; thousands of
   groups fit comfortably, so no intermediate clipping.
3. **What does `+2^15` do before `>>> 16`?** Round-to-nearest with ties to
   +inf; truncation would inject a systematic -0.5 LSB bias per layer.
   `docs/quantization_error_analysis.md`.
4. **Why saturate only once?** Intermediate clipping is irreversible and is
   amplified by the next layer's scale. `sat_flag` is reported.
5. **Why a real `r32` multiplier?** `1 << shamt` only represents powers of two.
   Cost: one multiplier per group, shared by 8 lanes. See the trade-off table
   in `docs/design_tradeoffs.md`.
6. **How does backpressure work?** Fire-on-`ready && valid`, registered
   output, `valid` never depends combinationally on `ready`; structural
   no-loop argument in `docs/timing_handshake.md`, plus six checked safety
   properties in `formal/`. No liveness / deadlock-freedom proof is claimed.
7. **How do you keep RTL, model and netlist consistent?** One written integer
   contract; exhaustive Python self-test; deterministic vectors with sha256;
   independent golden recomputation; dumps re-read by a separate scoreboard;
   mutation tests; then a synthesised netlist replayed with a bit-exact
   RTL-vs-gate ACTUAL comparison.
8. **Is this an ASIC tapeout / do you have PPA?** No. Generic cells only, no
   PDK, no STA, no um^2, no Fmax, no power. Cell counts are relative complexity
   indicators for this clean-room demo. The 42-question set with "do not say"
   lines is `docs/interview_qa.md`.

### Two trap answers

- *"Did you verify the whole chip?"* -> No. This repository verifies six
  testbenches and five netlists. The team project reached module-level
  continuous inference and SoC-level sampling. `docs/case_study.md`.
- *"What was the power?"* -> the team project's figure was
  accelerator-and-interface local, not full-chip. This repository claims no
  power number at all.

### One honest caveat to volunteer

RTL simulation, synthesis and gate-level replay are executed on Linux in CI,
not on the author's Windows host; the committed local snapshots are labelled
`SKIPPED` / not authoritative. Say so before being asked.
