//==========================================================================
// requant.v  -  r32 requantization + round-to-nearest + INT8 saturation
//
// Fixed-point contract (the single source of truth for RTL, model and docs):
//
//     q     = acc * r32 + 2^(SHIFT-1)          // signed, Q_W bits
//     y_pre = q >>> SHIFT                       // ARITHMETIC shift
//     y     = clip(y_pre, -128, 127)
//
//   acc : signed ACC_W-bit running sum (already includes bias)
//   r32 : unsigned R32_W-bit scale, applied as a real multiplier (NOT a
//         power-of-two shift). This is why r32 can approximate an arbitrary
//         per-layer scale much better than `1 << shamt`.
//
// Width reasoning: |acc| <= 2^31, r32 < 2^16  =>  |acc*r32| < 2^47.
// Adding 2^15 still fits in 2^48, so Q_W = ACC_W + R32_W + 1 = 49 signed
// bits is enough. Every operand below is declared `signed`; mixing an
// unsigned operand into this expression would silently turn the whole
// multiply into unsigned arithmetic in Verilog.
//
// Saturation happens ONCE, at the output. Intermediate clipping would inject
// truncation error into every following layer.
//
// Also exposes the pure combinational result (y_comb / sat_comb) so that
// nice_adapter.v can use exactly the same arithmetic without duplicating it.
//==========================================================================
`default_nettype none

module requant #(
    parameter integer ACC_W = 32,
    parameter integer R32_W = 16,
    parameter integer SHIFT = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     valid_i,
    input  wire                     last_i,
    input  wire                     stall,          // hold the output stage
    input  wire signed [ACC_W-1:0]  acc,
    input  wire        [R32_W-1:0]  r32,

    output wire signed [7:0]        y_comb,
    output wire                     sat_comb,

    output reg  signed [7:0]        y,
    output reg                      sat_flag,
    output reg                      valid_o,
    output reg                      last_o
);

    localparam integer Q_W = ACC_W + R32_W + 1;

    localparam signed [7:0]   Y_MAX =  127;
    localparam signed [7:0]   Y_MIN = -128;
    localparam signed [Q_W-1:0] SAT_HI =  127;
    localparam signed [Q_W-1:0] SAT_LO = -128;
    localparam signed [Q_W-1:0] ROUND  = (1 << (SHIFT-1));

    wire signed [Q_W-1:0] acc_ext = {{(Q_W-ACC_W){acc[ACC_W-1]}}, acc};
    wire signed [Q_W-1:0] r32_ext = {{(Q_W-R32_W){1'b0}}, r32};

    wire signed [Q_W-1:0] q     = (acc_ext * r32_ext) + ROUND;
    wire signed [Q_W-1:0] y_pre = q >>> SHIFT;

    wire sat_hi = (y_pre > SAT_HI);
    wire sat_lo = (y_pre < SAT_LO);

    assign y_comb   = sat_hi ? Y_MAX : (sat_lo ? Y_MIN : y_pre[7:0]);
    assign sat_comb = sat_hi | sat_lo;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            y       <= 8'sd0;
            sat_flag <= 1'b0;
            valid_o <= 1'b0;
            last_o  <= 1'b0;
        end else if (!stall) begin
            valid_o <= valid_i;
            last_o  <= valid_i ? last_i : 1'b0;
            if (valid_i) begin
                y        <= y_comb;
                sat_flag <= sat_comb;
            end
        end
    end

endmodule

`default_nettype wire
