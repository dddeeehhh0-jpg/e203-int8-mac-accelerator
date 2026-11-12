//==========================================================================
// int8_mac_top.v  -  streaming INT8 MAC channel
//
// One "group" is a sequence of beats. Each beat carries N_LANE pairs (x,w).
// On the first beat of a group the configured bias is folded into `din`;
// on the last beat the running sum is handed to the requantizer. The result
// appears on m_* two cycles later. Because `clear` in acc_stage means
// "restart from din" (not "go to zero"), a new group can start on the very
// next cycle: back-to-back single-beat groups sustain 1 result per cycle.
//
// Interface contract
//   cfg_*  : load r32/bias. cfg_valid has priority over s_valid.
//   s_*    : input stream, s_last marks the last beat of a group.
//   m_*    : output stream. One result per group, m_last is always 1.
//   stall  : derived from a full output buffer; freezes the whole pipeline
//            (input handshake, accumulator, requantizer, output buffer).
//   dbg_*  : observability only, not part of the functional interface.
//
// Fixed-point contract is defined in rtl/mac/requant.v.
//==========================================================================
`default_nettype none

module int8_mac_top #(
    parameter integer N_LANE  = 8,
    parameter integer IN_W    = 8,
    parameter integer ACC_W   = 32,
    parameter integer R32_W   = 16,
    parameter integer BIAS_W  = 16
) (
    input  wire                          clk,
    input  wire                          rst_n,

    input  wire                          cfg_valid,
    input  wire        [R32_W-1:0]       cfg_r32,
    input  wire signed [BIAS_W-1:0]      cfg_bias,
    output wire                          cfg_ready,

    input  wire                          s_valid,
    output wire                          s_ready,
    input  wire [N_LANE*IN_W-1:0]        s_x,
    input  wire [N_LANE*IN_W-1:0]        s_w,
    input  wire                          s_last,

    output wire                          m_valid,
    input  wire                          m_ready,
    output wire signed [7:0]             m_y,
    output wire                          m_sat,
    output wire                          m_last,

    output wire signed [ACC_W-1:0]       dbg_acc,
    output wire                          dbg_ovf
);

    reg        [R32_W-1:0]  r32_q;
    reg  signed [BIAS_W-1:0] bias_q;
    reg                      first;
    reg                      out_valid;
    reg  signed [7:0]        out_y;
    reg                      out_sat;
    reg                      out_last;

    wire stall    = out_valid && !m_ready;
    wire fire     = s_valid && s_ready;

    assign cfg_ready = !stall;
    assign s_ready   = !stall && !cfg_valid;

    // ---- datapath ------------------------------------------------------
    wire signed [ACC_W-1:0] mac_sum;
    mac_array #(
        .N_LANE (N_LANE),
        .IN_W   (IN_W),
        .ACC_W  (ACC_W)
    ) u_array (
        .x   (s_x),
        .w   (s_w),
        .sum (mac_sum)
    );

    wire signed [ACC_W-1:0] bias_ext = {{(ACC_W-BIAS_W){bias_q[BIAS_W-1]}}, bias_q};
    wire signed [ACC_W-1:0] din      = mac_sum + (first ? bias_ext : {ACC_W{1'b0}});

    wire signed [ACC_W-1:0] acc_now;
    wire                     acc_ovf;
    wire                     acc_clear = fire && first;
    wire                     acc_en    = fire;

    acc_stage #(.ACC_W(ACC_W)) u_acc (
        .clk   (clk),
        .rst_n (rst_n),
        .clear (acc_clear),
        .en    (acc_en),
        .din   (din),
        .acc   (acc_now),
        .ovf   (acc_ovf)
    );

    // Combinational mirror of what acc_stage will hold at the next edge.
    // On the last beat this exact value is sampled by the requantizer.
    wire signed [ACC_W-1:0] acc_next =
        acc_clear ? din : (acc_en ? (acc_now + din) : acc_now);

    wire                     rq_valid;
    wire signed [7:0]        rq_y;
    wire                     rq_sat;
    wire                     rq_last;

    requant #(
        .ACC_W (ACC_W),
        .R32_W (R32_W),
        .SHIFT (16)
    ) u_requant (
        .clk      (clk),
        .rst_n    (rst_n),
        .valid_i  (fire && s_last),
        .last_i   (s_last),
        .stall    (stall),
        .acc      (acc_next),
        .r32      (r32_q),
        .y_comb   (),
        .sat_comb (),
        .y        (rq_y),
        .sat_flag (rq_sat),
        .valid_o  (rq_valid),
        .last_o   (rq_last)
    );

    // ---- control -------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            r32_q     <= {{(R32_W-1){1'b0}}, 1'b1};
            bias_q    <= {BIAS_W{1'b0}};
            first     <= 1'b1;
            out_valid <= 1'b0;
            out_y     <= 8'sd0;
            out_sat   <= 1'b0;
            out_last  <= 1'b0;
        end else begin
            if (cfg_valid && cfg_ready) begin
                r32_q  <= cfg_r32;
                bias_q <= cfg_bias;
            end

            if (!stall) begin
                if (fire) begin
                    first <= s_last;
                end

                // Single-slot output buffer. When rq_valid is high the buffer
                // is (re)loaded; requant deasserts valid_o on the same edge
                // unless a new group also finished that cycle, so no result
                // is ever duplicated.
                if (rq_valid) begin
                    out_valid <= 1'b1;
                    out_y     <= rq_y;
                    out_sat   <= rq_sat;
                    out_last  <= rq_last;
                end else if (m_ready) begin
                    out_valid <= 1'b0;
                    out_last  <= 1'b0;
                end
            end
        end
    end

    assign m_valid = out_valid;
    assign m_y     = out_y;
    assign m_sat   = out_sat;
    assign m_last  = out_last;

    assign dbg_acc = acc_now;
    assign dbg_ovf = acc_ovf;

endmodule

`default_nettype wire
