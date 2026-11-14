# Formal verification (SVA + SymbiYosys)

## Why this exists

The RTL regression runs 88,048 deterministic points and the gate-level replay
runs a 204-point boundary subset. A finite vector set cannot answer an
interview question like *"how do you know the rounding rule is right for every
possible accumulator value?"* This directory adds proof obligations that are
**not** sampled: a combinational unbounded equivalence proof and a sequential
safety proof by k-induction.

It does **not** replace the gate-level replay. RTL-vs-netlist formal
equivalence (`equiv_make` / `equiv_induct`) is deliberately still out of scope;
see [Scope limits](#scope-limits).

## What is proved

| Job | Object | Engine | Result |
|---|---|---|---|
| `requant_comb` | `requant` combinational outputs | `smtbmc z3`, `mode prove` | PASS — k-induction |
| `requant_comb_bad` | same checker, rounding bias removed | `smtbmc z3`, `mode bmc` | FAIL + VCD counterexample |
| `stream_protocol` | `int8_mac_top` protocol-control logic (abstracted datapath) | `smtbmc z3`, `mode prove` | PASS — k-induction |
| `stream_protocol_bad` | same checker, `s_ready` forced high | `smtbmc z3`, `mode bmc` | FAIL + VCD counterexample |

`requant_check.v` compares the RTL against an **independently written**
51-bit reference model (wide multiply, explicit shift, comparison branches)
instead of re-using the RTL's 49-bit `sat_hi` / `sat_lo` structure. P1/P2
therefore prove the arithmetic contract over all 2^48 `(acc, r32)` pairs.
P3–P6 pin down the saturation flag, the tie-toward-+infinity rounding case,
the arithmetic (floor) shift on negative intermediates, and the fact that the
49-bit intermediate never wraps.

`stream_check.v` asserts six safety properties: deterministic reset state,
backpressure freezing both ready signals, `cfg_valid` priority, `m_last`
gating, output stability during a stall, and accumulator hold when no
handshake occurs. Only **safety** is proved — no liveness or throughput claim.

## Assumptions (read before quoting the result)

1. `rst_n` is low at the first clock edge and high afterwards. Mid-stream
   reset is **not** in the proof; `tb_top_stream` covers it by simulation.
2. In `stream_check.v` the arithmetic operands (`s_x`, `s_w`, `cfg_r32`,
   `cfg_bias`) are tied to constants so Yosys constant-folds the 8-lane
   multiplier and the 32x16 requant multiplier. This is a standard data-path
   abstraction: it keeps the SMT problem on the control FSM. Numeric
   correctness is proved separately by `requant_comb` and the RTL regression.
3. `cfg_valid`, `s_valid`, `s_last`, `m_ready` are completely free inputs.
4. Checkers use immediate `assert` / `assume` plus explicit shadow registers
   rather than `$past`, so the flow does not depend on SVA frontend differences
   between Yosys builds.

A proof is only as strong as its assumptions. Do not describe it as
"the whole SoC is formally verified".

## Negative tests

A checker that cannot fail proves nothing. Each positive job has a mutated
twin generated at run time by `run_formal.py`:

- `requant_comb_bad`: `q = (acc_ext * r32_ext) + ROUND` becomes
  `q = (acc_ext * r32_ext)`. The tie-case assertion (P4) and P1 fail.
- `stream_protocol_bad`: `assign s_ready = !stall && !cfg_valid;` becomes
  `assign s_ready = 1'b1;`. The priority / backpressure assertions fail.

The driver refuses to start a negative job unless its mutation anchor matches
**exactly once**, requires the job to FAIL, and requires a real VCD trace.
This guards against a "negative test" that silently passed.

## Reproducing

Requirements: Python 3, `yowasp-yosys` (ships `yowasp-sby`,
`yowasp-yosys-smtbmc`) and a Z3 executable on `PATH`.

```bash
python3 -m pip install "yowasp-yosys==0.70.0.0.post1259"
# Linux: sudo apt-get install -y z3
python3 formal/run_formal.py --strict
python3 formal/run_formal.py --only requant_comb      # single job
```

The driver creates thin `yosys` / `yosys-smtbmc` shims in the gitignored
`formal/out/bin/` so that SymbiYosys finds the YoWASP wrappers. On a host that
already provides its own tool wrappers, pass `--toolbin <dir>` (or set
`FORMAL_TOOLBIN`) to prepend that directory to `PATH` instead.

Outputs, all gitignored and uploaded as the `formal-evidence` CI artifact:

```
formal/out/jobs/<job>.sby            generated config (RTL embedded at run time)
formal/out/jobs/<job>/              workdir, status, logfile.txt
formal/out/jobs/<job>/engine_0/trace.vcd   counterexample (negative jobs only)
formal/out/jobs/<job>_console.log   full sby console output
formal/out/summary.json             machine-readable verdict
results/formal_report.md            committed host snapshot of the report
```

The `.sby` files are regenerated **from the current RTL on every run**, and the
report records SHA-256 for every source used. A stale copy of the RTL can
never be "proved" by accident.

## CI

`.github/workflows/ci.yml` has a dedicated `formal` job. It installs Z3 and the
YoWASP Yosys package, then runs `python3 formal/run_formal.py --strict`.
A positive proof that fails, a negative test that unexpectedly passes, or a
missing counterexample makes the job fail — so the green badge cannot hide a
broken checker.

## Scope limits

- **Not** RTL-vs-netlist formal equivalence. Gate-level replay is still a
  finite 204-point boundary subset under zero-delay behavioural primitives.
- **Not** full-chip verification, code/functional coverage, STA, timing
  closure, power, or PPA. No PDK and no Liberty library are used.
- **No** liveness / throughput proof. Only safety properties are asserted.
- **No** CDC, FIFO or SDF back-annotation: the design has one clock domain and
  no real delay model.
- The k-induction result is conditional on the assumptions above and on the
  correctness of the checkers themselves.

## Interview questions this answers

- Why is a 204-point gate-level replay not a proof, and what did you add?
- Why is the formal reference model written with a different width and
  structure than the RTL?
- What exactly does k-induction prove, and what does it not prove?
- Why did you abstract the data path in the sequential proof?
- How do you know your assertions can actually fail?
- Why is `Q_W = 49` sufficient, and how is that proved rather than asserted?
