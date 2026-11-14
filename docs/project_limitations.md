# Known limitations

Read this before quoting anything from the repository.

## Verification status

- **The six Verilog testbenches and the gate-level replay were not executed
  on the author's Windows host.** No `iverilog`/`vvp` was available there (the
  installer was blocked by the OS security policy). The committed
  `results/regression_summary.md` and `results/gatelevel_report.md` are that
  host's snapshots, both labelled `SKIPPED` / not authoritative. The real
  Yosys synthesis **did** run there.
- They **were** executed on GitHub Actions: the latest green run
  `43238295802` (Icarus Verilog 12.0 + Yosys 0.70) ran all three `--strict`
  steps - six TBs PASS with 0 mismatches across all six RTL dumps (88,048
  points), six synthesised tops with 0 latches, and 5/5 flattened netlists
  replayed bit-exactly. The earlier RTL-only green run was `43226906536`.
  See `results/ci_evidence.md`.
- It is accurate to say "the six testbenches pass in CI" and "RTL and the
  generic netlist agree on the replayed vector set". It is still NOT accurate
  to say "silicon verified", "full-chip verified", "formally equivalent",
  "timing closed" or "PPA measured".
- **No code coverage number, and only scoped formal proofs.**
  `docs/functional_coverage.md` is a scenario checklist; coverage percentages
  are not reported. The two SymbiYosys proofs in `formal/` cover specific RTL
  properties only (see `results/formal_report.md`) — no RTL-vs-netlist
  equivalence, no full-chip proof, no liveness.
- **Gate-level replay uses a reduced vector set.** A zero-delay netlist
  expands the 32x16 multiplier into thousands of gates; replaying all 17,459
  requant vectors exceeded 300 s in CI. The gate sweep is therefore a
  204-point boundary subset; the full sweep stays in the RTL regression.
- **The grammar check is Verilog-2001 subset** (pyverilog). It does not check
  elaboration, width rules, or X-propagation.

## Design scope

- `nice_adapter.v` is **NICE-style, not NICE**. Custom funct7 encoding,
  simplified handshake, no compatibility with E203 NICE RTL.
- `sram_beh.v` is a behavioural model with an asynchronous read. It is not a
  synthesizable SRAM macro and has no timing, no collision arbitration beyond
  read-during-write semantics and no power model.
- `mac_soc_stub.v` uses `$readmemh`, an `initial` block and hierarchical
  references into the SRAM array. These are simulation-only constructs; that
  module is a host *stub*, not a synthesizable SoC.
- The 12-layer chain is a **small recurrence** (8 lanes per layer, previous
  INT8 output replicated into all lanes). It demonstrates dataflow and
  error propagation; it is not a real keyword-spotting network and produces
  no accuracy claim.
- **Single-slot output buffer.** The streaming channel supports backpressure
  but has no FIFO depth; a slow downstream stalls the whole pipeline. Adding
  a FIFO and a skid buffer is the obvious next step.
- `int8_mac_top` hard-codes `SHIFT = 16` at the requant instance. `requant.v`
  itself is parameterised, but changing `SHIFT` at the top requires revisiting
  the rounding constant and the Python model together.
- `mac_array.v` exposes an explicit 3-level tree only for `N_LANE == 8`.
  Other lane counts work but fall back to a serial reduction.
- `acc_stage.ovf` is defensive. The generated corpus never drives the
  32-bit accumulator into overflow, so the flag's behaviour at the boundary
  is reasoned about, not exhaustively verified.

## Result scope

- **No PDK, no standard-cell library, and no area/timing/power results.**
  The repository *does* generate **generic** structural netlists with Yosys
  and replays them in simulation, but those are gate-level structures with no
  drive strength, no wireload, no parasitics, no SDC and no timing closure.
  Cell counts are relative complexity indicators, never um^2 / MHz / mW.
  `syn/dc_template.tcl` is a blank scaffold. See
  `docs/synthesis_analysis.md` and `results/synthesis_report.md`.
- All vectors are synthetic and derived from `SEED = 20261112`. There is no
  audio, no dataset and no trained weight anywhere in the tree.
- Numbers in `docs/case_study.md` belong to a separate team project, are
  labelled as such, and must not be presented as results of this repository.

## Publication status

- The repository has **not** been pushed to GitHub yet. The CI badge and the
  "CI green" claim become meaningful only after the first workflow run.
- `LICENSE` uses a generic copyright holder; replace it with your own name
  before publishing.
