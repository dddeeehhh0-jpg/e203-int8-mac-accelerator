# Formal verification report (SVA + SymbiYosys)

Generated: 2026-11-14 18:11:53 on Windows-11-10.0.26300-SP0 by `python3 formal/run_formal.py --strict`

> This committed file is the author's host snapshot. CI re-runs the same flow on
> `ubuntu-latest` and uploads its own report, logs and counterexamples as the
> `formal-evidence` artifact; that artifact is authoritative for the published run.

**Overall: PASS** — 4/4 jobs met their expected outcome.

> Scope warning: these are formal proofs of *properties of this repository's RTL*.
> They are **not** RTL-vs-netlist formal equivalence, **not** full-chip verification,
> **not** a coverage number and **not** timing/PPA. Gate-level replay remains a
> finite-vector experiment (204-point boundary subset).

## 1. Toolchain

| Item | Version / command |
|---|---|
| Python | 3.13.14 |
| SymbiYosys | `yowasp-sby.exe (yowasp-yosys 0.70.0.0.post1259)` |
| yowasp-yosys | 0.70.0.0.post1259 |
| Yosys | Yosys 0.70 (git sha1 28ba3cb92, Release, Clang /workspace/YoWASP/yosys/wasi-sdk-33.0-x86_64-linux/share/cmake/../..//bin/clang++ 22.1.0) |
| SMT solver | Z3 version 4.13.4 - 64 bit |
| Engine | `smtbmc z3`, k-induction (mode prove) / BMC (negative tests) |

## 2. Results

| Job | Object | Mode | Depth | Expected | Actual | Time | Outcome |
|---|---|---|---|---|---|---|---|
| `requant_comb` | `requant_check` | prove | 8 | PASS | PASS | 5.7 s | OK |
| `requant_comb_bad` | `requant_check` | bmc | 4 | FAIL | FAIL | 5.35 s | OK |
| `stream_protocol` | `stream_check` | prove | 20 | PASS | PASS | 5.81 s | OK |
| `stream_protocol_bad` | `stream_check` | bmc | 6 | FAIL | FAIL | 5.37 s | OK |

## 3. What is proved

**`requant_comb` (combinational, unbounded over all 2^48 input pairs)**

- P1/P2: `y_comb` and `sat_comb` equal an independently written 51-bit
  reference for every `(acc, r32)` — no input assumptions, no sampling.
- P3: an asserted saturation flag always implies a rail value (127 / -128).
- P4: the exact half-way case `acc=32768, r32=1` rounds to 1 (ties toward +infinity).
- P5: `acc=-65536, r32=1` yields -1, confirming arithmetic (floor) shift.
- P6: the 49-bit RTL intermediate never wraps, justifying `Q_W = 49`.

**`stream_protocol` (sequential safety, k-induction)**

- A1: reset leaves a deterministic, empty output stage.
- A2: backpressure drops both `s_ready` and `cfg_ready`.
- A3: `cfg_valid` has priority over the input stream (no simultaneous handshake).
- A4: `m_last` is never asserted without `m_valid`.
- A5: `m_valid`, `m_y`, `m_sat`, `m_last` hold stable through a stalled cycle.
- A6: without an input handshake the accumulator does not advance.

Only **safety** properties are asserted. No liveness / throughput claim is made:
k-induction proves that nothing bad happens, not that a result must arrive.

## 4. Assumptions and abstractions

1. `stream_protocol` assumes `rst_n` is low at the first edge and high afterwards.
   Mid-stream reset is NOT covered by the proof; it is covered by `tb_top_stream`
   in the RTL regression.
2. Arithmetic operands (`s_x`, `s_w`, `cfg_r32`, `cfg_bias`) are tied to constants
   so Yosys constant-folds the 8-lane multiplier and the 32x16 requant multiplier.
   This keeps the SMT problem on the control FSM. Numeric correctness is proved
   separately by `requant_comb` and by the 88,048-point RTL regression.
3. `cfg_valid`, `s_valid`, `s_last`, `m_ready` are free inputs: the solver explores
   every combination of them.
4. The checkers use immediate `assert` / `assume` statements plus explicit shadow
   registers instead of `$past`, so the flow is independent of SVA frontend
   differences between Yosys builds.

## 5. Negative tests (checker effectiveness)

A formal checker that cannot fail is worthless. Each positive job therefore has a
mutated twin. The driver verifies the mutation anchor matches exactly once before
running, requires the mutated job to FAIL, and requires a real VCD counterexample.

- `requant_comb_bad`: Negative control: delete the +2^15 rounding bias. The checker must produce a counterexample.
  - Injected: requant.v: `(acc_ext * r32_ext) + ROUND` -> `(acc_ext * r32_ext)`
  - Result: **FAIL**, 1 trace(s); verdict OK
  - Counterexample: `formal/out/jobs/requant_comb_bad/engine_0\trace.vcd`
- `stream_protocol_bad`: Negative control: force s_ready high. Backpressure/priority assertions must produce a counterexample.
  - Injected: int8_mac_top.v: `assign s_ready   = !stall && !cfg_valid;` -> `assign s_ready   = 1'b1;  // MUTANT: ignore backpressure and cfg priority`
  - Result: **FAIL**, 1 trace(s); verdict OK
  - Counterexample: `formal/out/jobs/stream_protocol_bad/engine_0\trace.vcd`

## 6. Commands and evidence

### `requant_comb`

- Purpose: Unbounded combinational proof: RTL requant == independent 51-bit reference, over all 2^48 (acc,r32) pairs.
- Config: `formal/out/jobs/requant_comb.sby` (mode `prove`, depth 8, expect pass)
- Yosys script: `read_verilog -formal requant.v requant_check.v; prep -top requant_check`
- Command: `yowasp-sby.exe -f formal/out/jobs/requant_comb.sby`
- Console log: `formal/out/jobs/requant_comb_console.log`; workdir: `formal/out/jobs/requant_comb/`

### `requant_comb_bad`

- Purpose: Negative control: delete the +2^15 rounding bias. The checker must produce a counterexample.
- Config: `formal/out/jobs/requant_comb_bad.sby` (mode `bmc`, depth 4, expect fail)
- Yosys script: `read_verilog -formal requant.v requant_check.v; prep -top requant_check`
- Command: `yowasp-sby.exe -f formal/out/jobs/requant_comb_bad.sby`
- Console log: `formal/out/jobs/requant_comb_bad_console.log`; workdir: `formal/out/jobs/requant_comb_bad/`

### `stream_protocol`

- Purpose: Sequential k-induction proof of ready/valid safety properties on int8_mac_top.
- Config: `formal/out/jobs/stream_protocol.sby` (mode `prove`, depth 20, expect pass)
- Yosys script: `read_verilog -formal mac_pe.v mac_array.v acc_stage.v requant.v int8_mac_top.v stream_check.v; prep -top stream_check`
- Command: `yowasp-sby.exe -f formal/out/jobs/stream_protocol.sby`
- Console log: `formal/out/jobs/stream_protocol_console.log`; workdir: `formal/out/jobs/stream_protocol/`

### `stream_protocol_bad`

- Purpose: Negative control: force s_ready high. Backpressure/priority assertions must produce a counterexample.
- Config: `formal/out/jobs/stream_protocol_bad.sby` (mode `bmc`, depth 6, expect fail)
- Yosys script: `read_verilog -formal mac_pe.v mac_array.v acc_stage.v requant.v int8_mac_top.v stream_check.v; prep -top stream_check`
- Command: `yowasp-sby.exe -f formal/out/jobs/stream_protocol_bad.sby`
- Console log: `formal/out/jobs/stream_protocol_bad_console.log`; workdir: `formal/out/jobs/stream_protocol_bad/`

## 7. Source integrity

The `.sby` files are generated from the RTL at run time; a stale copy can never be
proved by accident. SHA-256 of the sources used for this run:

| File | SHA-256 |
|---|---|
| `formal/checks/requant_check.v` | `d5a00becf915d9bcd526fa1b8228e802e28787bbce0d340c1f4e00fdbad28d6b` |
| `formal/checks/stream_check.v` | `88975aa2aac484d62fe1431a9574554964701d5a0d0cc6ff75c056d8b5eb74ad` |
| `rtl/mac/acc_stage.v` | `029938b229a3fb8223b274a15bd388e76ebcc999c84a17779208d2b21a70c088` |
| `rtl/mac/mac_array.v` | `f4c510f11b1410f2484d30513169f1c1a54336b9faf29b4a24bbb481fdd77d3d` |
| `rtl/mac/mac_pe.v` | `31f6064ff5d351c6fec86b63690dcbb8724469b66f4775855564fcec629a4066` |
| `rtl/mac/requant.v` | `0271445fdd1d0a972c408d9e66c1cf5ae0bdb171890c8c77f673f4d0d2dd1e6f` |
| `rtl/top/int8_mac_top.v` | `b6f60c81a2afed641be17332a7f569e5e468b1499c760b1c22560836ca6f9602` |

## 8. Deliberate limitations

- No RTL-vs-netlist formal equivalence (`equiv_make` / `equiv_induct`); the
  gate-level replay is still a finite 204-point boundary subset.
- No SDC / STA, no Liberty library, no PDK, no timing or power claim.
- No liveness / throughput proof, no code or functional coverage percentage.
- No CDC, no FIFO, no SDF back-annotation: the design has a single clock domain.
- A successful proof is conditional on the assumptions in section 4.

