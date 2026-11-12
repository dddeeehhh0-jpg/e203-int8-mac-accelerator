# Known limitations

Read this before quoting anything from the repository.

## Verification status

- **The six Verilog testbenches were not executed on the author's Windows
  host.** No `iverilog`/`vvp` was available there (the installer was blocked
  by the OS security policy). They **were** executed on GitHub Actions: run
  `43226906536` under Icarus Verilog 12.0, all six PASS, with 0 mismatches
  across all six RTL dumps (88,048 points). See `results/ci_evidence.md`.
  It is now accurate to say "the six testbenches pass in CI"; it is still NOT
  accurate to say "silicon verified", "full-chip verified" or "gate-level
  verified".
- **No code coverage, no formal proof, no gate-level replay.** Functional
  corpus sizes are reported; coverage percentages are not.
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

- **No PDK, no netlist, no area/timing/power results in this repository.**
  `syn/` is a logic-level Yosys script and a blank DC template. See
  `docs/synthesis_analysis.md`.
- All vectors are synthetic and derived from `SEED = 20261112`. There is no
  audio, no dataset and no trained weight anywhere in the tree.
- Numbers in `docs/case_study.md` belong to a separate team project, are
  labelled as such, and must not be presented as results of this repository.

## Publication status

- The repository has **not** been pushed to GitHub yet. The CI badge and the
  "CI green" claim become meaningful only after the first workflow run.
- `LICENSE` uses a generic copyright holder; replace it with your own name
  before publishing.
