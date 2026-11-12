//==========================================================================
// acc_stage.v  -  32-bit accumulator with restart / enable / sticky overflow
//
// Contract:
//   clear  : RESTART the accumulation, i.e. acc <= din (not "acc <= 0").
//            This lets a new group start on the very cycle after the previous
//            group ends, so the streaming top can sustain 1 group/cycle.
//   en     : acc <= acc + din
//   clear has priority over en.
//   ovf    : sticky signed-overflow flag, cleared only by reset or clear.
//
// Overflow detection: widen by one bit and compare the two sign bits.
//   sum[ACC_W] != sum[ACC_W-1]  ->  signed overflow.
//
// Bias is NOT added here; the parent adds it into din on the first beat of a
// group. That keeps this module reusable for bias-free reductions.
//==========================================================================
`default_nettype none

module acc_stage #(
    parameter integer ACC_W = 32
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     clear,
    input  wire                     en,
    input  wire signed [ACC_W-1:0]  din,
    output reg  signed [ACC_W-1:0]  acc,
    output reg                      ovf
);

    wire signed [ACC_W:0] sum_ext = {acc[ACC_W-1], acc} + {din[ACC_W-1], din};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= {ACC_W{1'b0}};
            ovf <= 1'b0;
        end else if (clear) begin
            acc <= din;
            ovf <= 1'b0;
        end else if (en) begin
            acc <= sum_ext[ACC_W-1:0];
            ovf <= ovf | (sum_ext[ACC_W] ^ sum_ext[ACC_W-1]);
        end
    end

endmodule

`default_nettype wire
