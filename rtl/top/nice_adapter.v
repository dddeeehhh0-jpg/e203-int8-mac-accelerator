//==========================================================================
// nice_adapter.v  -  NICE-STYLE request/response coprocessor adapter
//
// IMPORTANT: this is NOT the official NICE implementation. It is a small,
// independently written adapter that mimics the req/rsp handshake shape and
// defines its own funct7 encoding for demonstration purposes. Semantics are
// deliberately simplified; see docs/architecture.md.
//
// Instruction encoding (funct7 = inst[31:25]):
//   7'h01 SET_R32  : rs2[15:0]        -> r32 scale
//   7'h02 SET_BIAS : rs1[15:0]        -> bias
//   7'h03 LOAD_X   : {rs2, rs1}       -> 8 packed INT8 activations
//   7'h04 LOAD_W   : {rs2, rs1}       -> 8 packed INT8 weights
//   7'h05 MAC      : compute one group, latch INT8 result
//   7'h06 READ     : pop the result (sign-extended to 32 bits)
//   anything else  : illegal
//
// Illegal sequences are REJECTED with rsp_err=1 and rsp_data=32'hDEAD_BEEF,
// and they never mutate internal state:
//   1. MAC before SET_R32
//   2. MAC before SET_BIAS
//   3. MAC before LOAD_X / LOAD_W (or re-using consumed operands)
//   4. READ with no pending result
//   5. unknown funct7
//
// The MAC arithmetic is not duplicated: requant.v exposes y_comb/sat_comb
// and this module taps those wires, so RTL, model and adapter share one
// arithmetic definition.
//==========================================================================
`default_nettype none

module nice_adapter #(
    parameter integer N_LANE = 8,
    parameter integer IN_W   = 8,
    parameter integer ACC_W  = 32,
    parameter integer R32_W  = 16
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         nice_req_valid,
    output wire         nice_req_ready,
    input  wire [31:0]  nice_req_inst,
    input  wire [31:0]  nice_req_rs1,
    input  wire [31:0]  nice_req_rs2,

    output reg          nice_rsp_valid,
    input  wire         nice_rsp_ready,
    output reg  [31:0]  nice_rsp_data,
    output reg          nice_rsp_err,

    // Observability (not part of the NICE-style interface)
    output wire signed [ACC_W-1:0] dbg_acc
);

    localparam [6:0] F_SET_R32  = 7'h01;
    localparam [6:0] F_SET_BIAS = 7'h02;
    localparam [6:0] F_LOAD_X   = 7'h03;
    localparam [6:0] F_LOAD_W   = 7'h04;
    localparam [6:0] F_MAC      = 7'h05;
    localparam [6:0] F_READ     = 7'h06;
    localparam [31:0] ERR_WORD  = 32'hDEAD_BEEF;

    wire [6:0] funct7 = nice_req_inst[31:25];

    reg        [R32_W-1:0] r32_q;
    reg signed [15:0]      bias_q;
    reg        [63:0]      x_q, w_q;
    reg                    r32_set, bias_set, x_set, w_set;
    reg signed [7:0]       result_y;
    reg                    result_sat, result_valid;

    // ---- combinational datapath ---------------------------------------
    wire signed [ACC_W-1:0] mac_sum;
    mac_array #(.N_LANE(N_LANE), .IN_W(IN_W), .ACC_W(ACC_W)) u_array (
        .x   (x_q),
        .w   (w_q),
        .sum (mac_sum)
    );

    wire signed [ACC_W-1:0] bias_ext = {{16{bias_q[15]}}, bias_q};
    wire signed [ACC_W-1:0] acc_comb = mac_sum + bias_ext;

    wire signed [7:0] y_comb;
    wire              sat_comb;

    requant #(.ACC_W(ACC_W), .R32_W(R32_W), .SHIFT(16)) u_requant (
        .clk      (clk),
        .rst_n    (rst_n),
        .valid_i  (1'b0),
        .last_i   (1'b0),
        .stall    (1'b0),
        .acc      (acc_comb),
        .r32      (r32_q),
        .y_comb   (y_comb),
        .sat_comb (sat_comb),
        .y        (),
        .sat_flag (),
        .valid_o  (),
        .last_o   ()
    );

    assign dbg_acc = acc_comb;

    // ---- legality check ------------------------------------------------
    reg          illegal;
    reg  [31:0]  rsp_next;

    always @* begin
        illegal  = 1'b0;
        rsp_next = 32'h0000_0000;
        case (funct7)
            F_SET_R32 : begin end
            F_SET_BIAS: begin end
            F_LOAD_X  : begin end
            F_LOAD_W  : begin end
            F_MAC     : begin
                if (!r32_set || !bias_set || !x_set || !w_set) illegal = 1'b1;
            end
            F_READ    : begin
                if (!result_valid) illegal = 1'b1;
                else rsp_next = {{24{result_y[7]}}, result_y};
            end
            default   : illegal = 1'b1;
        endcase
        if (illegal) rsp_next = ERR_WORD;
    end

    // ---- handshake / state --------------------------------------------
    assign nice_req_ready = !(nice_rsp_valid && !nice_rsp_ready);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            r32_q         <= {{(R32_W-1){1'b0}}, 1'b1};
            bias_q        <= 16'sd0;
            x_q           <= 64'h0;
            w_q           <= 64'h0;
            r32_set       <= 1'b0;
            bias_set      <= 1'b0;
            x_set         <= 1'b0;
            w_set         <= 1'b0;
            result_y      <= 8'sd0;
            result_sat    <= 1'b0;
            result_valid  <= 1'b0;
            nice_rsp_valid<= 1'b0;
            nice_rsp_data <= 32'h0;
            nice_rsp_err  <= 1'b0;
        end else begin
            if (nice_rsp_valid && nice_rsp_ready) begin
                nice_rsp_valid <= 1'b0;
            end

            if (nice_req_valid && nice_req_ready) begin
                nice_rsp_valid <= 1'b1;
                nice_rsp_err   <= illegal;
                nice_rsp_data  <= rsp_next;

                if (!illegal) begin
                    case (funct7)
                        F_SET_R32 : begin
                            r32_q   <= nice_req_rs2[15:0];
                            r32_set <= 1'b1;
                        end
                        F_SET_BIAS: begin
                            bias_q   <= nice_req_rs1[15:0];
                            bias_set <= 1'b1;
                        end
                        F_LOAD_X  : begin
                            x_q   <= {nice_req_rs2, nice_req_rs1};
                            x_set <= 1'b1;
                        end
                        F_LOAD_W  : begin
                            w_q   <= {nice_req_rs2, nice_req_rs1};
                            w_set <= 1'b1;
                        end
                        F_MAC     : begin
                            result_y     <= y_comb;
                            result_sat   <= sat_comb;
                            result_valid <= 1'b1;
                            x_set        <= 1'b0;
                            w_set        <= 1'b0;
                        end
                        F_READ    : begin
                            result_valid <= 1'b0;
                        end
                        default   : begin end
                    endcase
                end
            end
        end
    end

endmodule

`default_nettype wire
