//==========================================================================
// generic_cells.v - hand-written BEHAVIOURAL models of Yosys generic cells
//
// Why this file exists
// --------------------
// syn/run_synth.py maps the RTL to Yosys generic gate cells and writes a
// structural netlist (write_verilog -noexpr -noattr). A netlist made of
// \$_AND_ / \$_DFFE_* instances cannot be simulated by Icarus Verilog unless
// somebody supplies primitives. Instead of copying a vendor or tool file into
// this repository, we define the small set of primitives ourselves, directly
// from their documented port semantics.
//
// Scope: SIMULATION ONLY. These are plain Verilog behavioural models with no
// timing, no drive strength, no PDK and no cell area. They exist to answer one
// question in CI: "does the post-synthesis structural netlist still compute
// the same values as the RTL?" They are NOT a standard-cell library and are
// NOT used to derive any area / timing / power number.
//
// Deliberate design choice: syn/run_synth.py parses every \$_* instance in
// every generated netlist and FAILS if a cell type is not defined here. A
// future Yosys version that introduces a new primitive therefore produces a
// loud, explicit error instead of an unresolved module and a false PASS.
//
// Naming: Yosys writes escaped identifiers such as `\$_DFFE_PN0P_ `. The
// trailing whitespace terminates the escaped name - keep the space.
//==========================================================================

`default_nettype none

// --------------------------------------------------------------------------
// Combinational primitives
// --------------------------------------------------------------------------
module \$_BUF_ (A, Y);
  input  A;
  output Y;
  assign Y = A;
endmodule

module \$_NOT_ (A, Y);
  input  A;
  output Y;
  assign Y = ~A;
endmodule

module \$_AND_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = A & B;
endmodule

module \$_OR_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = A | B;
endmodule

module \$_XOR_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = A ^ B;
endmodule

module \$_NAND_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = ~(A & B);
endmodule

module \$_NOR_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = ~(A | B);
endmodule

module \$_XNOR_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = ~(A ^ B);
endmodule

module \$_ANDNOT_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = A & ~B;
endmodule

module \$_ORNOT_ (A, B, Y);
  input  A, B;
  output Y;
  assign Y = A | ~B;
endmodule

module \$_MUX_ (A, B, S, Y);
  input  A, B, S;
  output Y;
  assign Y = S ? B : A;
endmodule

module \$_NMUX_ (A, B, S, Y);
  input  A, B, S;
  output Y;
  assign Y = S ? ~B : ~A;
endmodule

module \$_MUX4_ (A, B, C, D, S, Y);
  input  A, B, C, D;
  input  [1:0] S;
  output Y;
  assign Y = (S == 2'd0) ? A :
             (S == 2'd1) ? B :
             (S == 2'd2) ? C : D;
endmodule

module \$_MUX8_ (A, B, C, D, E, F, G, H, S, Y);
  input  A, B, C, D, E, F, G, H;
  input  [2:0] S;
  output Y;
  assign Y = (S == 3'd0) ? A : (S == 3'd1) ? B : (S == 3'd2) ? C :
             (S == 3'd3) ? D : (S == 3'd4) ? E : (S == 3'd5) ? F :
             (S == 3'd6) ? G : H;
endmodule

module \$_AOI3_ (A, B, C, Y);
  input  A, B, C;
  output Y;
  assign Y = ~((A & B) | C);
endmodule

module \$_OAI3_ (A, B, C, Y);
  input  A, B, C;
  output Y;
  assign Y = ~((A | B) & C);
endmodule

module \$_AOI4_ (A, B, C, D, Y);
  input  A, B, C, D;
  output Y;
  assign Y = ~((A & B) | (C & D));
endmodule

module \$_OAI4_ (A, B, C, D, Y);
  input  A, B, C, D;
  output Y;
  assign Y = ~((A | B) & (C | D));
endmodule

// --------------------------------------------------------------------------
// Sequential primitives, older Yosys naming
//   $_DFF_[PN]_        posedge/negedge clock, no reset
//   $_DFFE_[PN][PN]_   with enable (2nd letter = enable polarity)
//   $_DFFSR_[PN][PN][PN]_  async set/reset, 3 letters = clk/set/reset polarity
// --------------------------------------------------------------------------
module \$_DFF_P_ (C, D, Q);
  input  C, D;
  output reg Q;
  always @(posedge C) Q <= D;
endmodule

module \$_DFF_N_ (C, D, Q);
  input  C, D;
  output reg Q;
  always @(negedge C) Q <= D;
endmodule

module \$_DFFE_PP_ (C, D, E, Q);
  input  C, D, E;
  output reg Q;
  always @(posedge C) if (E) Q <= D;
endmodule

module \$_DFFE_PN_ (C, D, E, Q);
  input  C, D, E;
  output reg Q;
  always @(posedge C) if (~E) Q <= D;
endmodule

module \$_DFFE_NP_ (C, D, E, Q);
  input  C, D, E;
  output reg Q;
  always @(negedge C) if (E) Q <= D;
endmodule

module \$_DFFE_NN_ (C, D, E, Q);
  input  C, D, E;
  output reg Q;
  always @(negedge C) if (~E) Q <= D;
endmodule

module \$_DFFSR_PPP_ (C, S, R, D, Q);
  input  C, S, R, D;
  output reg Q;
  always @(posedge C or posedge S or posedge R)
    if (R) Q <= 1'b0; else if (S) Q <= 1'b1; else Q <= D;
endmodule

module \$_DFFSR_PNN_ (C, S, R, D, Q);
  input  C, S, R, D;
  output reg Q;
  always @(posedge C or negedge S or negedge R)
    if (~R) Q <= 1'b0; else if (~S) Q <= 1'b1; else Q <= D;
endmodule

module \$_DFFSR_NPP_ (C, S, R, D, Q);
  input  C, S, R, D;
  output reg Q;
  always @(negedge C or posedge S or posedge R)
    if (R) Q <= 1'b0; else if (S) Q <= 1'b1; else Q <= D;
endmodule

// --------------------------------------------------------------------------
// Sequential primitives, current Yosys naming
//   $_DFFE_[clk P/N][reset P/N][reset value 0/1][enable P/N]_
//   Ports: D, C, R, E, Q.  R is an ASYNCHRONOUS reset (active level given by
//   the second letter); E gates the clock edge.
// --------------------------------------------------------------------------
module \$_DFFE_PN0P_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or negedge R)
    if (~R) Q <= 1'b0; else if (E) Q <= D;
endmodule

module \$_DFFE_PN0N_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or negedge R)
    if (~R) Q <= 1'b0; else if (~E) Q <= D;
endmodule

module \$_DFFE_PN1P_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or negedge R)
    if (~R) Q <= 1'b1; else if (E) Q <= D;
endmodule

module \$_DFFE_PN1N_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or negedge R)
    if (~R) Q <= 1'b1; else if (~E) Q <= D;
endmodule

module \$_DFFE_PP0P_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or posedge R)
    if (R) Q <= 1'b0; else if (E) Q <= D;
endmodule

module \$_DFFE_PP0N_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or posedge R)
    if (R) Q <= 1'b0; else if (~E) Q <= D;
endmodule

module \$_DFFE_PP1P_ (D, C, R, E, Q);
  input  D, C, R, E;
  output reg Q;
  always @(posedge C or posedge R)
    if (R) Q <= 1'b1; else if (E) Q <= D;
endmodule

// Latches are listed only so that a latch in a netlist is a NAMED, detected
// primitive instead of an unresolved module. run_synth.py treats ANY latch as
// a hard failure: this design is required to be fully synchronous.
module \$_DLATCH_P_ (E, D, Q);
  input  E, D;
  output reg Q;
  always @* if (E) Q <= D;
endmodule

module \$_DLATCH_N_ (E, D, Q);
  input  E, D;
  output reg Q;
  always @* if (~E) Q <= D;
endmodule

`default_nettype wire
