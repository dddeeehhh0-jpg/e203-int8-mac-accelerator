//==========================================================================
// requant_check.v - FORMAL wrapper for the COMBINATIONAL requant contract.
//
// This file is NOT part of the synthesised design. SymbiYosys reads it with
// `read_verilog -formal`, which turns every `assert` into a proof obligation.
//
// The reference model below is deliberately written with a DIFFERENT
// structure and a DIFFERENT intermediate width (51 bits) than the RTL
// (49 bits): it uses a wide multiply, an explicit 51-bit shift and two
// comparison branches instead of the RTL's sat_hi / sat_lo wires. A SAT
// proof of equality therefore proves the arithmetic contract, not a
// tautology between two copies of the same expression.
//
// Scope: all 2^48 combinations of (acc, r32). No assumptions on the inputs.
//==========================================================================
`default_nettype none

module requant_check (
    input wire signed [31:0] acc,
    input wire        [15:0] r32
);

    wire signed [7:0] y_comb;
    wire              sat_comb;

    // The registered outputs are irrelevant here; only y_comb / sat_comb are
    // observed. clk is tied low so the output stage cannot introduce state.
    requant #(
        .ACC_W (32),
        .R32_W (16),
        .SHIFT (16)
    ) u_dut (
        .clk      (1'b0),
        .rst_n    (1'b1),
        .valid_i  (1'b0),
        .last_i   (1'b0),
        .stall    (1'b0),
        .acc      (acc),
        .r32      (r32),
        .y_comb   (y_comb),
        .sat_comb (sat_comb),
        .y        (),
        .sat_flag (),
        .valid_o  (),
        .last_o   ()
    );

    // ---- independent golden expression --------------------------------
    reg signed [50:0] ref_q;
    reg signed [50:0] ref_shifted;
    reg signed [7:0]  ref_y;
    reg               ref_sat;

    always @* begin
        // {35'b0, r32} is a 51-bit unsigned extension of the 16-bit scale.
        // Expression width is 51 bits, so acc is sign-extended automatically.
        ref_q       = $signed(acc) * $signed({35'b0, r32}) + 51'sd32768;
        ref_shifted = ref_q >>> 16;

        if (ref_shifted > 51'sd127) begin
            ref_y   = 8'sd127;
            ref_sat = 1'b1;
        end else if (ref_shifted < (-51'sd128)) begin
            ref_y   = 8'b10000000;      // -128 as an 8-bit bit pattern
            ref_sat = 1'b1;
        end else begin
            ref_y   = ref_shifted[7:0];
            ref_sat = 1'b0;
        end
    end

    // ---- P1 / P2: unbounded bit-exact equivalence ----------------------
    // Proved by k-induction for every (acc, r32) pair, not sampled.
    always @* begin
        assert(y_comb  == ref_y);
        assert(sat_comb == ref_sat);
    end

    // ---- P3: saturation flag implies a rail value ---------------------
    always @* begin
        if (sat_comb)
            assert((y_comb == 8'sd127) || (y_comb == 8'b10000000));
    end

    // ---- P4: the exact half-way case rounds toward +infinity ----------
    // acc*r32 = 32768, q = 65536, y_pre = 1. Without the +2^15 rounding
    // bias the result would be 0. This is the negative-test tripwire.
    wire tie_case = (acc == 32'sd32768) && (r32 == 16'd1);
    always @* if (tie_case) begin
        assert(y_comb == 8'sd1);
        assert(!sat_comb);
    end

    // ---- P5: negative intermediates use an arithmetic (floor) shift ---
    // acc*r32 = -65536, q = -32768, -32768 >>> 16 = -1.
    // A logical shift would produce a large positive number and saturate.
    wire neg_case = (acc == (-32'sd65536)) && (r32 == 16'd1);
    always @* if (neg_case) begin
        assert(y_comb == 8'b11111111);   // -1
        assert(!sat_comb);
    end

    // ---- P6: the RTL's 49-bit intermediate can never wrap -------------
    // |acc| <= 2^31 and r32 < 2^16 => |acc*r32| < 2^47, so 49 signed bits
    // (range +/- 2^48) are sufficient. This justifies Q_W = 49.
    always @* begin
        assert(ref_q <  (51'sd1 << 48));
        assert(ref_q >= (-51'sd1 << 48));
    end

endmodule

`default_nettype wire
