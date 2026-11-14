# Interview Q&A: defending this project under follow-up questions

Organised the way a digital-IC interviewer actually drills: start with the
one-line summary, then go deeper until something breaks. Answers point at a
file you can open. **If a question is not covered by evidence here, the answer
is "not done / not claimed" - never improvise a number.**

> Read `docs/project_limitations.md`, `docs/case_study.md` and
> `docs/PUBLICATION_AUDIT.md` first. Three hard lines are repeated throughout:
> (1) Python model verification is not RTL simulation; (2) module-level /
> SoC-sample verification is not full-chip verification; (3) the team
> project's power figure is accelerator-local, not system power.

---

## 0. The 30-second pitch

> "A clean-room INT8 MAC channel: 8 parallel signed multiply lanes, a 32-bit
> accumulator, `r32` requantisation with round-to-nearest and one INT8
> saturation, wrapped in a ready/valid streaming top with a NICE-style command
> adapter. I wrote a bit-exact Python reference model, deterministic vectors,
> six self-checking testbenches, an independent scoreboard, real generic-cell
> synthesis and post-synthesis gate-level replay. Everything runs in CI on
> Icarus Verilog + Yosys, and the README maps each claim to a file."

**What NOT to say:** "I verified the whole chip", or any team-project
Fmax / area / power / NRMSE figure presented as a result of this repository.
This project has no clock period, no area, no power and no accuracy metric.

---

## 1. Fixed-point / quantisation

**Q1. Walk through the requantisation arithmetic.**
`q = acc*r32 + 2^15` in 49 signed bits, `y_pre = q >>> 16` (arithmetic shift
= floor), then one clip to `[-128,127]` with a `sat` flag. See
`rtl/mac/requant.v` and `docs/quantization_error_analysis.md`.

**Q2. Why 49 bits?** `|acc| <= 2^31`, `r32 < 2^16`, so `|acc*r32| < 2^47`;
adding `2^15` stays below `2^48`; signed 49 bits covers it. It's derived
(`Q_W = ACC_W + R32_W + 1`), not a magic constant.

**Q3. Why `>>>` and not `>>`?** On a signed operand both are arithmetic in
Verilog, but `>>>` states intent explicitly. The key is that it's **floor**,
not truncation toward zero - that's what makes `floor(x+0.5)` a round-to-nearest.

**Q4. Is your rounding unbiased?** No, and this is a good catch. `floor(x+0.5)`
is round-to-nearest with **ties toward +infinity**: `+0.5 -> +1` but
`-0.5 -> 0`, not `-1`. Negative ties carry a +1 LSB bias. It is neither
round-half-to-even nor half-away-from-zero. Error is bounded by
`-0.5 < e <= +0.5` LSB. I'd use a sign-dependent correction or convergent
rounding if the accumulation of that bias mattered.

**Q5. Why add `+32768`?** It's `2^(SHIFT-1)`, the round-to-nearest offset for
a 16-bit fractional shift. One constant adder, no sign-dependent control.

**Q6. Where does saturation happen, and why only once?** Only at the INT8
output in `requant`. `mac_array` and `acc_stage` keep exact sums. Clipping at
each stage would inject a truncation error into every subsequent layer of the
12-layer chain.

**Q7. What is the error bound?** Per operation, `<= 0.5` output LSB from
rounding. **Saturation error is unbounded** relative to the true value - which
is exactly why `r32` must be calibrated and why `sat` is observable. I make
no end-to-end network error claim: that needs a dataset and a statistical
argument this repo does not have.

**Q8. Why a real `r32` multiplier instead of a power-of-two shift?** A shifter
can only express scales `2^-s`; a 16-bit multiplier approximates an arbitrary
per-layer scale to ~16 bits. Cost: `requant` is the biggest block (~3.9k
generic cells). It's the central accuracy/area trade-off.

**Q9. Where do the `r32` values come from?** From outside this repo. They are
runtime config registers (`cfg_r32` / `SET_R32`). This project supplies the
arithmetic and the write path; it does **no calibration**, uses **no dataset**,
reports **no accuracy metric**.

**Q10. How do you detect accumulator overflow?** `acc_stage` widens to 33 bits
and compares the two sign bits, raising a **sticky** `ovf`. Limitation: the top
only exposes it as `dbg_ovf`; it does not interrupt or correct the result.

**Q11. What if `r32=0` or `acc=-2^31`?** Both are in `requant_scan.hex` (1,027
`r32` values x 17 `acc` edges, including full-scale). Tested bit-exactly.

---

## 2. Timing and handshaking

**Q12. Draw the ready/valid equations.**
`stall = out_valid && !m_ready`; `fire = s_valid && s_ready`;
`cfg_ready = !stall`; `s_ready = !stall && !cfg_valid`. See
`docs/timing_handshake.md` and `docs/images/fig4_stream_waveform.png`.

**Q13. Why is there no combinational loop on valid/ready?** `m_valid` is the
register `out_valid`; `s_ready` depends on `out_valid` (a reg), `m_ready` and
`cfg_valid` - **not** on `s_valid`. So neither
`s_valid->s_ready->s_valid` nor `m_ready->m_valid->m_ready` loops exist.

**Q14. What happens on backpressure?** One `stall` freezes the whole channel:
`s_ready=0` -> `fire=0` -> accumulator holds; `requant` skips its
`!stall` branch; output regs hold; config blocked. The single output slot is a
one-deep skid buffer via held registers: no result lost, none duplicated.

**Q15. Latency and throughput?** Two register stages from `s_last` to
`m_valid` (requant output regs, then top-level output regs). Because
`acc_stage.clear` means "restart from `din`" rather than "zero", back-to-back
single-beat groups sustain **1 result/clock** with `m_ready=1`. A `cfg_valid`
cycle injects exactly one bubble. These are structural properties, not Fmax.

**Q16. Why does `m_y` keep an old value when `m_valid=0`?** Clearing it would
cost logic and would be wrong for a held result during `stall`. The protocol
defines the payload as don't-care while valid is low. My scoreboard compares
the `valid` bit always and the full word only on valid cycles.
`docs/timing_handshake.md` §4.

**Q17. Reset strategy and its weakness?** Asynchronous active-low `rst_n`,
asserted in every sequential block's sensitivity list. Weakness: **no reset
de-assertion synchroniser** and no recovery/removal check; a real tapeout needs
a per-domain reset synchroniser. Also single clock domain, **no CDC**.

**Q18. Do you have formal verification?** No. The no-deadlock argument is
structural (from the equations) plus directed/random simulation. No SVA, no
`yosys-smtbmc` proof. Listed as future work.

---

## 3. Verification

**Q19. What did you actually run, and where?** On the author's Windows host:
Python model self-tests, vector determinism, independent golden recomputation,
structural lint, grammar parse and **the real Yosys synthesis** (YoWASP build).
No `iverilog` there. **All RTL simulation and all gate-level replay run in
GitHub Actions on `ubuntu-latest`** (Icarus Verilog 12.0); the latest green run
`43238295802` ran all three `--strict` steps with 5/5 netlists bit-exact.
`results/regression_summary.md` labels the local snapshot `SKIPPED`;
`results/ci_evidence.md` is the authoritative record.

**Q20. Six testbenches - what do they cover?** `tb_mac_pe` (exhaustive 256x256
products), `tb_mac_array` (5,004 vectors), `tb_requant` (17,459-point sweep),
`tb_top_stream` (24-beat handshake scenario), `tb_nice_adapter` (13 commands),
`tb_soc_stub` (12-layer end-to-end). See `docs/functional_coverage.md`.

**Q21. How do you know the checker isn't just printing PASS?** Two mutation
tests inject wrong values (including a wrong payload on a valid cycle and a
wrongly-asserted `valid`) and assert the checker catches exactly the right
number of errors at the right index. `--selftest`.

**Q22. Why is the scoreboard separate from the testbench?** A self-checking TB
can agree with a bug in its own expectations. `check_results.py` recomputes
goldens from raw operands independently of `gen_vectors.py`, and re-reads the
dump CSVs written by the simulator.

**Q23. Tell me about a failing CI run and what you learned.** Run
`43226072305`: six TBs all passed but the scoreboard reported 9 mismatches in
`dump_top_stream.csv`. I downloaded the artifact and inspected line by line:
all 9 were `m_valid=0` cycles holding a stale payload - a protocol don't-care.
The RTL was right, the checker was too strict. I fixed **only the checker**,
added a second mutation test so it wasn't a relaxation, and touched no RTL.
Also run `43232254680`: gate-level compiles failed because Yosys emitted a
hierarchy (`$paramod` child) and TBs used parameter overrides that a flattened
netlist cannot have. Fixed by flattening + generating an equivalent TB copy
that validates the override values first. A later run (`43233148388`) had two
netlists passing but timed out after 300 s on the 17,459-point zero-delay
requant sweep - a simulation-cost problem, not a functional failure. The fix
kept the full sweep at RTL level and replayed a 204-point boundary subset at
gate level, with the TB's `N_VEC` loop bound patched in lockstep so a short
vector file cannot silently look like a PASS. The next run (`43238295802`)
was fully green: 6/6 TBs, 6 synthesised tops, 5/5 netlists bit-exact.
Every run and fix is logged in `results/ci_evidence.md`.

**Q24. Do you report code coverage?** No. There is no commercial coverage tool
here. `docs/functional_coverage.md` is a **scenario checklist**, explicitly
not statement/branch/toggle coverage. I don't quote any coverage percentage.

**Q25. What is gate-level replay, and what does it prove?** `run_synth.py`
produces a flattened structural netlist; `run_gatelevel.py` compiles it with
hand-written behavioural generic-cell models and a generated copy of the same
TB, then runs **both** an RTL reference and the netlist on the **same** vectors
in isolated directories. Five checks must all be green: RTL `RESULT PASS`,
gate `RESULT PASS`, independent scoreboard on the RTL dump, independent
scoreboard on the gate dump, and a bit-exact row-by-row comparison of the two
ACTUAL columns under the same ready/valid protocol rule. It proves functional
equivalence **on this vector set under a zero-delay primitive model**. Only
`tb_requant` uses a reduced 204-point boundary subset; the other four netlists
keep their full vectors and the complete 17,459-point requant sweep stays in
the RTL regression. It is NOT formal equivalence, NOT timing, NOT PDK synthesis.

**Q26. Why hand-write `generic_cells.v`?** To stay clean-room (no vendor/tool
file copied) and to make `run_synth.py` fail loudly if a future Yosys emits a
primitive that has no model - or emits a latch. Zero latches is a requirement.

---

## 4. Synthesis, PPA, physical design

**Q27. What synthesis did you run?** Yosys generic mapping (no PDK):
`hierarchy -check`, `proc`, `opt`, `techmap`, `flatten`, `setundef -zero`,
`check`, `stat`, `write_verilog -noexpr`. Six synthesizable tops, 0 latches,
0 undriven/multiply-driven nets. `results/synthesis_report.md`.

**Q28. What's the area / Fmax / power?** **None that belongs to this project.**
There is no standard-cell library, no drive strength, no wireload, no SDC,
no parasitics, no corners, no timing closure. The cell counts are relative
complexity indicators only. Any um^2 / MHz / mW number belongs to a different
team project and is labelled as such in `docs/case_study.md`.

**Q29. So what are the cell counts good for?** Confirming the design
elaborates, that the 8-multiplier + balanced-tree structure is really there,
that `requant`'s multiplier dominates, and comparing two versions of *this*
RTL under the same script. The causal chain "operator width -> cell count" is
the design argument.

**Q30. What's the critical path?** The group-final combinational path:
`mac_array -> acc+bias -> acc_next mirror -> acc*r32 multiply -> +32768 ->
arithmetic shift -> saturation comparators`. The adder tree is balanced to
shorten it. I have not run STA; I can't quote a delay.

**Q31. What's in `syn/dc_template.tcl`?** A scaffold with the library path
deliberately empty. It is NOT runnable - no vendor library is committed
(licence + contest-rule reasons). Someone with a legitimate `.db`/`.lib` could
start from it.

**Q32. How would you actually close timing?** Get a real library + constraints,
run STA, then pipeline the `acc*r32` multiply (one extra latency cycle in
exchange for removing the longest operator). Not done here.

---

## 5. Architecture / integration

**Q33. Why 8 lanes?** 8 x 8-bit = 64 bits, one bus word each for `s_x` and
`s_w`. Good utilisation with a 3-level adder tree. 16/32 lanes would raise
throughput but cost multipliers and interconnect.

**Q34. Is this a NICE accelerator for E203?** No. `nice_adapter.v` defines its
own `funct7` encoding (SET_R32 / SET_BIAS / LOAD_X / LOAD_W / MAC / READ) for
demonstration. It is **not** the official NICE interface and there is no E203
core in this repo. The title describes the domain, not a claimed integration.

**Q35. What's `mac_soc_stub`?** A minimal host FSM driving `int8_mac_top`
through a 12-layer chain, with a **behavioural** single-port SRAM. It is
simulation-only (hierarchical `$readmemh`), explicitly excluded from synthesis.
Its 12-layer result is module/behavioural-level evidence, not full-chip.

**Q36. Is 1 result/cycle impressive?** It's a clean structural property of
one channel, not a system throughput claim. A systolic array would be much
higher throughput at much higher area and needs a real memory-bandwidth model.
I chose small + verifiable. See `docs/design_tradeoffs.md`.

**Q37. Where's the memory macro?** There isn't one. Committing a vendor SRAM
macro would be a licence and contest-rule problem; `sram_beh` is a behavioural
model. No memory PPA is claimed.

---

## 6. Scope, honesty, process

**Q38. Is this the project you submitted to a competition?** No. This is a
clean-room rewrite. `docs/case_study.md` describes the *contest experience*
(method, scope, lessons) without shipping any contest source, PDK, netlist,
dataset, weights or screenshot. `docs/PUBLICATION_AUDIT.md` is a file-by-file
licence/permission audit.

**Q39. What exactly did you verify in the contest?** Only what's written there:
module-level 12-layer continuous inference and SoC-level sampled verification;
a team-chosen validation set (NOT the organiser's evaluation); and an
**accelerator-local** power figure. Never say "full-chip verified",
"organiser evaluation passed" or "system power".

**Q40. What's the biggest weakness of this portfolio repo?** No PPA (no PDK),
no formal verification, no CDC/reset synchronisation, no real coverage tool,
and no statistical accuracy metric. All are written down in
`docs/project_limitations.md`. Being explicit about them is the point - a
project that can state its own boundaries survives follow-up better than one
that overclaims.

**Q41. If you had two more weeks?** Reset synchronisation, an output FIFO/skid
buffer, SVA/formal on the handshake, pipelining the requant multiply with a
real STA loop, and coverage-driven verification. In that order. None is done.

**Q42. How do I reproduce everything?** `make ci` (or three `--strict`
commands): `run_regress.py`, `syn/run_synth.py`, `run_gatelevel.py`. Needs
`iverilog`, `yosys`/`yowasp-yosys`, Python 3. `results/*` and the CI artifacts
contain the generated evidence. `make help` lists every target.


---

## Formal verification (added 2026-11-14)

**Q: Why is a 204-point gate-level replay not enough, and what did you add?**
It samples a boundary subset; it cannot say anything about untested input
combinations or about state sequences. I added two scoped SymbiYosys proofs:
an unbounded combinational equivalence proof for `requant` (all 2^48 input
pairs) and a k-induction safety proof for the ready/valid FSM. This does NOT
replace the replay - it answers a different question.

**Q: Why is the formal reference model written differently from the RTL?**
`requant_check.v` uses a 51-bit wide multiply, an explicit shift and comparison
branches; the RTL uses a 49-bit intermediate with `sat_hi`/`sat_lo` wires. If I
had copied the RTL expression, the SAT solver would prove a tautology. The
different structure and width are what make the equivalence proof meaningful,
and P6 in the same checker proves the 49-bit width cannot wrap.

**Q: What does k-induction prove, and what does it not prove?**
Basecase + induction show the asserted safety properties hold for every step
of the modelled system, not just the first N cycles. It does not prove
liveness/throughput, does not cover behaviours excluded by the assumptions,
and does not prove the checker itself is complete.

**Q: Why did you abstract the data path in the sequential proof?**
A 32x16 multiplier is expensive for an SMT solver. I tied the arithmetic
operands to constants so Yosys constant-folds them, leaving the control FSM
for the solver. Numeric correctness is proved separately by the combinational
proof and the 88,048-point RTL regression. The abstraction is stated in
`formal/README.md` instead of being hidden.

**Q: How do you know the assertions can actually fail?**
Each positive job has a mutated twin. The driver verifies the mutation anchor
matches exactly once, requires the mutated job to FAIL and requires a real VCD
counterexample. Removing the rounding bias trips the tie-case assertion;
forcing `s_ready` high trips the priority/backpressure assertions.

**Q: What exactly did the formal work NOT prove?**
No RTL-vs-netlist formal equivalence (`equiv_make`/`equiv_induct`), no
full-chip verification, no STA/timing closure, no power/PPA, no code or
functional coverage percentage, no mid-stream reset behaviour in the proof
(that is covered by `tb_top_stream`), and no liveness. I say this explicitly
in the README and in `results/formal_report.md`.

**Q: What did Yosys actually change during synthesis?**
It lowered behavioural RTL into generic cells (`$_MUL_`, `$add`, `$mux`,
DFFs), flattened hierarchy and removed unused logic. The gate-level replay
compiles those generic cells against hand-written zero-delay models. `$paramod`
hierarchy had to be removed by flattening, and the testbench parameter
overrides had to be stripped, before the netlist could be replayed by the same
testbench. None of this is timing closure: there is no SDC, no Liberty and no
delays.
