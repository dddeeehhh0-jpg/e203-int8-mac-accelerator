# Design decisions and trade-offs (the "why" behind the RTL)

This is the document to read before an interview. Every decision below is a
choice with an alternative and a cost; none is presented as the only possible
design. Synthesis cell counts come from `results/synthesis_report.md` and are
**generic Yosys cells without a PDK** - they are relative complexity
indicators, never area in um^2, Fmax or power.

---

## 1. Decision table

| Decision | Chosen | Alternative rejected | Why | Cost |
|---|---|---|---|---|
| Lane count | 8 parallel INT8 multiplies | 1 lane (serial), 16/32 lanes | 8 x 8-bit = 64 bits, exactly one 64-bit bus word for `s_x` and one for `s_w`; good utilisation with a small adder tree | 8 multipliers, ~4.9k generic cells for `mac_array` |
| Reduction | explicit 3-level balanced tree | serial `for`-loop chain | `log2(8)=3` adder levels instead of 7; shorter combinational path, structure visible in the netlist | slightly more wires; a generic fallback exists for non-8 lane counts |
| Accumulator | 32-bit signed, `clear` = restart from `din` | 18-bit (just enough for one group), `clear` = zero | 32-bit leaves ~16k worst-case beats of headroom; "restart from din" removes the dead cycle between back-to-back groups, enabling 1 result/cycle | wider adder, 33-bit overflow detection |
| Requant scale | 16-bit **real multiplier** `acc*r32` | power-of-two shifter | approximates an arbitrary per-layer scale to ~16 bits instead of snapping to `2^-s` | largest single block: `requant` ~3.9k generic cells |
| Rounding | `+2^15` then `>>> 16`, one clip | round-half-even, sign-aware correction, per-stage clipping | one adder constant, no sign control, single output saturation avoids injecting error into later layers | ties biased toward +infinity; see `docs/quantization_error_analysis.md` |
| Output buffering | single register slot, whole-pipeline `stall` | FIFO / skid buffer | simplest provable no-loss handshake; one cycle of freeze is easy to reason about | upstream stalls immediately; throughput degrades if the consumer is slow |
| Command interface | self-defined "NICE-style" funct7 | official NICE core interface | keeps the demo self-contained and explainable without vendor RTL | **not** an official NICE implementation; encoding is local |
| Memory | behavioural single-port `sram_beh`, **not synthesised** | real SRAM macro | lets the 12-layer host FSM run end-to-end without PDK | simulation-only; no memory macro, no memory PPA |

---

## 2. Area/throughput positioning (qualitative, deliberately)

This is a **single small co-processor channel**, not a systolic array.

- A systolic/fully-parallel array would keep many PEs busy every cycle and
  reach much higher throughput, at the cost of many more multipliers, a
  mesh of interconnect and a data-staging scheme. It also needs a real
  memory bandwidth model to be meaningful - absent here.
- This design reuses one 8-lane MAC channel over successive beats, favouring
  a small, fully synchronous, easy-to-verify datapath. Its steady-state
  throughput is **1 result per clock** while `m_ready` stays high
  (structural property of the handshake, not a measured Fmax).
- The critical combinational path is the group-final beat: `mac_array` ->
  `acc + bias` -> `acc_next` mirror -> `requant`'s 32x16 multiply -> `+32768`
  -> arithmetic shift -> saturation comparators. The adder tree is balanced
  specifically to keep that path shallow; `requant` dominates it.

If asked "where would you pipeline further", the honest first answer is:
split the `acc*r32` multiply into two registered stages. It costs one extra
cycle of latency but removes the longest combinational operator. This
repository does **not** do that - it is single-cycle combinational requant -
and there is no timing closure to prove either choice is faster.

---

## 3. What the synthesis numbers actually say

From `results/synthesis_report.md` (Yosys generic mapping, flattened):

| Top | Generic cells | Sequential bits | Reading |
|---|---:|---:|---|
| `mac_pe` | 456 | 0 | one 8x8 signed multiplier |
| `mac_array` | ~4.9k | 0 | 8 multipliers + balanced adder tree |
| `requant` | ~3.9k | 11 | 32x16 multiply dominates |
| `int8_mac_top` | ~9.5k | 88 | array + accumulator + requant + FSM |
| `nice_adapter` | ~9.3k | ~184 | same datapath plus command/response regs |

The near-additivity of `int8_mac_top` is a useful sanity check: it is roughly
`mac_array + requant + control`. **These are not um^2.** There is no standard
cell library, no drive strength, no wireload, no SDC, no corners and no timing
optimisation. Quoting them as "area" or deriving Fmax from them would be wrong.

---

## 4. Verification-driven decisions

- `sram_beh` and `mac_soc_stub` are explicitly **excluded from synthesis**.
  They contain a behavioural memory array and a hierarchical `$readmemh`
  initial block. Consequently `tb_soc_stub` (12-layer end-to-end) is verified
  at RTL/behavioural level only, while the five synthesizable DUTs get both
  RTL simulation and gate-level replay. This boundary is stated in
  `results/synthesis_report.md` and checked by `run_gatelevel.py`.
- Hand-written `syn/generic_cells.v` instead of a vendor/tool cell library:
  keeps the repository clean-room and lets `run_synth.py` **fail loudly** on
  any undefined primitive or any latch. Zero latches is a design requirement.
- Flattened netlists: one module named exactly like the DUT, so the same
  testbench can be reused with only its parameter override removed
  (the override value is parsed and checked against the synthesised default
  before it is dropped). This was a real CI failure and is documented in
  `results/ci_evidence.md`.

---

## 5. If I rebuilt it, in priority order

1. **Reset synchronisation** - async assertion with synchronised de-assertion
   per clock domain, plus recovery/removal checks. Currently absent.
2. **Skid buffer / small FIFO** on the output - decouple upstream from a
   stalled consumer instead of freezing the whole channel.
3. **SVA + formal** on the ready/valid handshake (no deadlock, no duplication,
   no loss) instead of relying on directed scenarios plus a structural argument.
4. **Pipeline the requant multiply** and run a real STA loop with an SDC
   (requires a legitimate library - not in this repo).
5. **CDC** if a second clock domain is ever introduced.
6. **Coverage-driven verification** with a real coverage tool, not a scenario
   checklist.

None of these is implemented. Listing them is not a claim that they are done.

---

## 6. Boundary with the contest project

This repository is a **clean-room demo**: no E203 core, no official NICE RTL,
no PDK, no netlist from the contest, no dataset, no weights. The contest
experience is described only as method and scope in `docs/case_study.md`, with
three hard limits: module-level / SoC-sample verification is not full-chip
verification; the team project's power figure is accelerator-local, not system
power; and a team-chosen validation set is not the organiser's evaluation
result. No PPA or accuracy number from the team project is reused here.
