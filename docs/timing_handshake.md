# Timing, handshaking and backpressure (formal-ish treatment)

This document explains the ready/valid equations and the structural argument
behind backpressure, using only the equations actually present in
`rtl/top/int8_mac_top.v` and `rtl/mac/requant.v`. It is the answer to
"walk me through your ready/valid" in an interview. A waveform is in
`docs/images/fig4_stream_waveform.png`.

**Scope note:** the structural argument is not a liveness proof. The formal
work in `formal/` proves six **safety** properties of the protocol-control
logic with an abstracted datapath — not deadlock freedom and not
RTL-vs-netlist equivalence.

> All signals are in ONE clock domain with a single asynchronous active-low
> reset `rst_n`. There is no CDC and no reset synchroniser. See
> [§7 Limitations](#7-limitations-what-this-design-does-not-claim).

---

## 1. Signal classification

| Signal | Direction | Registered? | Drives |
|---|---|---|---|
| `m_valid` | out | **yes** (`out_valid` reg) | downstream `m_ready` consumer |
| `m_ready` | in | (external) | `stall` |
| `m_y`, `m_sat`, `m_last` | out | **yes** (payload regs) | downstream |
| `s_valid` | in | (external) | `fire` |
| `s_ready` | out | **combinational** | upstream |
| `cfg_valid` | in | (external) | `s_ready` (priority) |
| `cfg_ready` | out | combinational | config master |
| `out_valid` | internal | **yes** | `stall`, `m_valid` |

The single most important fact for a no-combinational-loop argument:
**`m_valid` is a register output.** `stall` depends on `out_valid` (a
register), not on a combinational function of `m_valid`.

---

## 2. The four equations (verbatim from the RTL)

```
stall    = out_valid && !m_ready
fire     = s_valid && s_ready
cfg_ready = !stall
s_ready   = !stall && !cfg_valid
```

Consequences, each of which is a deliberate design decision:

1. **`s_ready` does not depend on `s_valid`.** It depends on `out_valid`
   (reg), `m_ready` (input) and `cfg_valid` (input). Therefore there is no
   `s_valid -> s_ready -> s_valid` combinational cycle. A commonly-seen bug
   is `assign s_ready = ... s_valid ...`, which creates an opaque loop that
   synthesisers and lint tools must break; that pattern is absent here.
2. **`m_valid` does not depend on `m_ready`.** It is `out_valid`, a register.
   So there is no `m_ready -> m_valid -> m_ready` loop either. This is the
   standard AXI-stream "valid must not combinatorially depend on ready"
   rule, satisfied structurally.
3. **Configuration has priority over data.** When `cfg_valid=1`, `s_ready=0`,
   so `fire=0` and no data beat is consumed that cycle. `r32_q`/`bias_q` are
   loaded instead. This makes a config write atomic w.r.t. a running group:
   you cannot change the scale halfway through an accumulation, because the
   accumulator is frozen on config cycles.
4. **Backpressure freezes the WHOLE pipeline in one cycle.** When
   `out_valid=1 && m_ready=0`:
   - `s_ready=0` -> `fire=0` -> `acc_en=0`, accumulator holds;
   - `requant` sees `stall=1` -> `else if (!stall)` branch not taken, so
     `y`/`sat_flag`/`valid_o` hold;
   - the `always` block's `if (!stall)` guard is false, so `first`,
     `out_valid`, `out_y` hold;
   - `cfg_ready=0`, so config is also blocked (no config can slip in during
     a stall).
   Nothing upstream can advance and nothing downstream is lost: the single
   output slot is a one-deep skid buffer implemented by holding the registers.

---

## 3. Latency and throughput

Pipeline stages (comment in `int8_mac_top.v`): input handshake ->
accumulator -> requantizer -> output buffer.

- From a data beat with `s_last=1` to `m_valid` asserting, the result passes
  **two register stages**: `requant`'s `y`/`valid_o` regs (one edge) and the
  top-level `out_valid`/`out_y` regs (second edge). The RTL comment says
  "the result appears on `m_*` two cycles later".
- `acc_stage` uses `clear` = **restart from `din`**, not "clear to zero".
  Because of that, the cycle immediately after a group finishes can be the
  first beat of the next group with no dead cycle. Combined with the single
  output slot being reloaded on the same edge that `requant` de-asserts
  `valid_o`, **back-to-back single-beat groups sustain 1 result per clock**
  when `m_ready` stays high. This is exercised in `vectors/gen/top_seq.hex`.
- A `cfg_valid` cycle inserts exactly one bubble (`s_ready=0`), which is the
  intended cost of making config atomic.

### Why "1 result/cycle" is a statement about this RTL, not about a chip
It is a structural property of the handshake under `m_ready=1`. It says
nothing about Fmax (no timing closure) and nothing about system throughput
(no memory bandwidth model, no bus, no E203). Do not upgrade it.

---

## 4. The "invalid-cycle payload is don't-care" rule (and why CI run 1 was red)

`int8_mac_top` keeps `out_y`/`out_sat` registers at their previous value when
`m_valid=0`. Clearing them would cost extra logic (and, for a held result
during `stall`, would be wrong). The protocol therefore defines:

> On cycles with `m_valid=0`, the payload `m_y`/`m_sat` is a **don't-care**.
> Only `m_valid` is meaningful.

`tb_top_stream.v` skips payload comparison on those cycles. The independent
scoreboard (`model/check_results.py::check_one_dump`) mirrors the rule:

- the `valid` bit (bit 9 of the packed word) is **always** compared;
- on `valid=1` cycles the **full 10-bit word** is compared;
- on `valid=0` cycles the stale payload bits are ignored.

The first real CI run (`43226072305`) failed because the scoreboard compared
the full word on idle/stall/reset/drain cycles and reported 9 false
mismatches. The RTL was correct; the checker was wrong. The fix (commit
`a8639b0`) changed **only the checker**, added a second mutation test proving
a wrong payload on a *valid* cycle is still caught, and did not touch any RTL.
This is a good interview story: a green testbench does not automatically mean
a correct *scoreboard*, and "fix the test" is only legitimate when you can
show the DUT obeys the documented protocol.

---

## 5. Reset behaviour

`rst_n` is asynchronous, active-low, in the sensitivity list of every
sequential `always` block. On reset: `r32_q=1`, `bias_q=0`, `first=1`,
`out_valid=0`, `out_y=0`, `out_sat=0`, `out_last=0`; `requant` clears
`y/sat_flag/valid_o/last_o`; `acc_stage` clears `acc` and sticky `ovf`.
`top_seq.hex` includes a reset assertion mid-stream (beat t13) to prove a
reset in the middle of traffic does not leave a stuck `valid`.

---

## 6. What the waveform (`fig4`) shows

Four annotated regions over 24 beats of `top_seq.hex`:

1. **Normal**: reset -> config load (`r32=1024,bias=7`) -> a 3-beat group ->
   `m_valid` appears two cycles after the `s_last` beat.
2. **Backpressure**: three consecutive beats with `m_ready=0` while results
   are pending; `s_ready` drops, the accumulator holds, `m_valid` stays high
   with a stable payload (no result duplicated, none lost).
3. **Drain / config reload**: `m_ready=1` resumes, then a new `cfg_valid`
   reload changes `r32` to 512 and `bias` to -3, followed by a fresh group.
4. **Reset mid-stream**: `rst_n=0` de-asserts all valid flags, then a clean
   restart.

---

## 7. Limitations (what this design does NOT claim)

- **No CDC**: one clock only. Crossing clock domains would need synchronisers
  and an async FIFO; none is present.
- **No reset de-assertion synchroniser**: `rst_n` is async-asserted with no
  reset-release synchronisation. A real design needs a reset synchroniser per
  domain to avoid recovery/removal violations. This is a known simplification.
- **Scoped formal proof only**: `formal/stream_check.v` proves six safety
  properties (reset, backpressure stability, config priority, `m_last`
  gating, stalled-output stability, accumulator hold) by k-induction with
  `smtbmc z3`. Liveness / deadlock freedom, RTL-vs-netlist equivalence and
  mid-stream reset are **not** proved here; see `formal/README.md`.
- **No skid-buffer decoupling**: `stall` freezes the entire channel; a
  registered ready/valid skid stage or a small FIFO would let upstream keep
  running one more beat. Chosen for clarity, not for maximum throughput.
- **Not timing-closed**: the comments about stages and 1 result/cycle are
  structural; no SDC, no clock period, no Fmax is claimed anywhere.

If asked "what would you change first if you taped this out", the honest
answer is: reset synchronisation, then a FIFO/skid buffer for throughput,
then SVA/formal for the handshake, then real CDC if more than one clock.
