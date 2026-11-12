# Architecture

## 1. Three layers

```
                 +---------------------------------------------+
   integration   |  nice_adapter.v   (command / req-rsp path)      |
                 +------------------------+--------------------+
                                          | taps y_comb / sat_comb
   host          |  mac_soc_stub.v  <-->  sram_beh.v (behavioural)  |
                 +------------------------+--------------------+
                                          | streaming cfg/s_/m_
   datapath      |  int8_mac_top.v                                   |
                 |    mac_array.v -> acc_stage.v -> requant.v        |
                 |      (8 x mac_pe.v)                               |
                 +---------------------------------------------+
```

`requant.v` is instantiated **twice** (once inside `int8_mac_top`, once inside
`nice_adapter`), but the arithmetic exists only once: the adapter connects the
module's combinational outputs `y_comb` / `sat_comb` and never uses the
registered stage. There is no second copy of the formula to drift out of sync.

Two integration paths are intentional:

| Path | Module | When to look at it |
|---|---|---|
| Streaming | `int8_mac_top.v` | throughput, `last`, backpressure, `cfg` reload |
| Command | `nice_adapter.v` | processor coupling, illegal-sequence rejection |

They are alternatives, not a cascade. Neither instantiates the other.

---

## 2. Port tables

### `int8_mac_top`

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk`, `rst_n` | in | 1 | rising edge, asynchronous active-low reset |
| `cfg_valid` | in | 1 | load `cfg_r32` / `cfg_bias`; has priority over `s_valid` |
| `cfg_r32` | in | 16 | unsigned requantization scale |
| `cfg_bias` | in | 16 | **signed** bias, sign-extended into `din` on the first beat |
| `cfg_ready` | out | 1 | `!stall` |
| `s_valid`, `s_ready` | in/out | 1 | input handshake |
| `s_x`, `s_w` | in | 64 | 8 packed INT8 lanes, lane 0 in bits `[7:0]` |
| `s_last` | in | 1 | last beat of a group |
| `m_valid`, `m_ready` | out/in | 1 | output handshake, one result per group |
| `m_y` | out | 8 | signed INT8 result |
| `m_sat`, `m_last` | out | 1 | saturation flag / group delimiter |
| `dbg_acc`, `dbg_ovf` | out | 32 / 1 | observability only |

**Latency**: two cycles from the `s_last` beat to `m_valid`. Because
`acc_stage.clear` means "restart from `din`" rather than "go to zero", the
next group can start on the immediately following cycle: back-to-back
single-beat groups sustain one result per cycle.

**Backpressure**: `stall = m_valid && !m_ready`. It freezes the input
handshake, the accumulator, the requantizer output register and the output
buffer in the same cycle, so no result is lost or duplicated. `tb_top_stream`
drives three consecutive stalled cycles and checks `s_ready` on every one.

### `nice_adapter` (NICE-*style*, not official)

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `nice_req_valid` / `nice_req_ready` | in / out | 1 | request handshake |
| `nice_req_inst` | in | 32 | `funct7 = inst[31:25]` |
| `nice_req_rs1`, `nice_req_rs2` | in | 32 | operands / packed lane halves |
| `nice_rsp_valid` / `nice_rsp_ready` | out / in | 1 | response handshake |
| `nice_rsp_data` | out | 32 | result (sign-extended) or `32'hDEAD_BEEF` |
| `nice_rsp_err` | out | 1 | 1 = request rejected |

#### funct7 encoding (defined by this project)

| funct7 | Mnemonic | Action |
|---|---|---|
| `7'h01` | `SET_R32` | `rs2[15:0]` -> r32 |
| `7'h02` | `SET_BIAS` | `rs1[15:0]` -> bias |
| `7'h03` | `LOAD_X` | `{rs2, rs1}` -> 8 packed activations |
| `7'h04` | `LOAD_W` | `{rs2, rs1}` -> 8 packed weights |
| `7'h05` | `MAC` | compute one group, latch the INT8 result |
| `7'h06` | `READ` | pop the pending result, sign-extended |
| other | — | rejected |

A `MAC` consumes the loaded X/W operands. Five illegal classes are rejected
without touching state:

1. `MAC` before `SET_R32`
2. `MAC` before `SET_BIAS`
3. `MAC` before `LOAD_X` / `LOAD_W` (including re-using consumed operands)
4. `READ` with no pending result (or after the result was consumed)
5. unknown `funct7`

> **Semantics disclaimer.** The official NICE interface has its own encoding,
> timing and response rules. This adapter borrows only the request/response
> shape and is explicitly *not* compatible with E203 NICE RTL. It exists to
> demonstrate coprocessor handshaking and defensive sequencing.

### `sram_beh`

| Port | Dir | Meaning |
|---|---|---|
| `clk`, `en`, `we` | in | synchronous write when `en && we` |
| `addr` | in | `$clog2(DEPTH)` bits, default `DEPTH=1024` |
| `din`, `dout` | in/out | 32-bit; **combinational read** |

Read-during-write returns the old contents. The host FSM reads one word per
cycle, so an asynchronous read keeps the FSM simple; this is a behavioural
model, not a synthesizable SRAM macro.

### `mac_soc_stub` memory map

One 5-word record per layer, `OUT_BASE = N_LAYER * 5 = 60`:

| Offset | Contents |
|---|---|
| `+0` | `x[31:0]` (layer 0 only) |
| `+1` | `x[63:32]` |
| `+2` | `w[31:0]` |
| `+3` | `w[63:32]` |
| `+4` | `{r32[15:0], bias[15:0]}` |
| `OUT_BASE + L` | sign-extended `y` of layer L (written back by the stub) |

For layers >= 1 the activations are the previous INT8 result replicated into
all 8 lanes, so the chain can be checked against the Python model without any
external dataset. The `$readmemh` initialisation and the hierarchical memory
write-back checks are **simulation-only constructs**; this module is not
intended for synthesis.

---

## 3. Why the adder tree is explicit

For `N_LANE == 8`, `mac_array.v` instantiates 8 multipliers and a hand-written
3-level reduction tree (`l0 -> l1 -> l2`). A `for`-loop accumulate inside an
`always @*` would be functionally identical but would synthesise into a serial
carry chain. Keeping the levels explicit makes the structure visible in a
synthesis report, which is the point of a portfolio project. Other lane counts
fall back to a portable generic reduction (functionally identical, not
balanced).
