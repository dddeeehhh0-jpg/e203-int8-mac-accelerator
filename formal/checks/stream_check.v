//==========================================================================
// stream_check.v - FORMAL wrapper for the ready/valid protocol of
// int8_mac_top. This is the SEQUENTIAL object of the formal flow.
//
// Assumptions (stated explicitly so the proof is not overclaimed):
//   1. rst_n is low for the first clock edge and high afterwards. There is
//      no mid-stream reset in this proof. Mid-stream reset is exercised by
//      tb_top_stream in the RTL regression instead.
//   2. The arithmetic operands are tied to constants. Yosys constant-folds
//      the 8-lane multiplier and the 32x16 requant multiplier away, leaving
//      the control FSM and the handshake logic for the SMT solver. Numeric
//      correctness is proved separately by requant_check (unbounded SAT) and
//      by the 88,048-point RTL regression.
//   3. cfg_valid, s_valid, s_last and m_ready are completely free inputs;
//      the solver explores every legal combination of them.
//
// Only SAFETY properties are asserted. No liveness / throughput claim is
// made: k-induction proves that "nothing bad happens", not that a result
// must eventually arrive.
//==========================================================================
`default_nettype none

module stream_check (
    input wire clk,
    input wire rst_n,
    input wire cfg_valid,
    input wire s_valid,
    input wire s_last,
    input wire m_ready
);

    // ---- data-path abstraction (see assumption 2) ----------------------
    wire [63:0]         s_x      = 64'd0;
    wire [63:0]         s_w      = 64'd0;
    wire [15:0]         cfg_r32  = 16'd1;
    wire signed [15:0]  cfg_bias = 16'sd0;

    wire                cfg_ready;
    wire                s_ready;
    wire                m_valid;
    wire                m_sat;
    wire                m_last;
    wire signed [7:0]   m_y;
    wire signed [31:0]  dbg_acc;
    wire                dbg_ovf;

    int8_mac_top #(
        .N_LANE (8), .IN_W (8), .ACC_W (32), .R32_W (16), .BIAS_W (16)
    ) u_dut (
        .clk      (clk),
        .rst_n    (rst_n),
        .cfg_valid(cfg_valid),
        .cfg_r32  (cfg_r32),
        .cfg_bias (cfg_bias),
        .cfg_ready(cfg_ready),
        .s_valid  (s_valid),
        .s_ready  (s_ready),
        .s_x      (s_x),
        .s_w      (s_w),
        .s_last   (s_last),
        .m_valid  (m_valid),
        .m_ready  (m_ready),
        .m_y      (m_y),
        .m_sat    (m_sat),
        .m_last   (m_last),
        .dbg_acc  (dbg_acc),
        .dbg_ovf  (dbg_ovf)
    );

    // ---- environment --------------------------------------------------
    reg f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;

    always @(posedge clk) begin
        if (!f_past_valid) assume(!rst_n);
        else               assume(rst_n);   // one reset, at t = 0
    end

    // Shadow registers: an explicit, tool-independent substitute for $past.
    // They are synchronised with the DUT's reset branch.
    reg               p_m_valid, p_m_ready, p_m_sat, p_m_last;
    reg               p_stall, p_fire;
    reg signed [7:0]  p_m_y;
    reg signed [31:0] p_acc;

    always @(posedge clk) begin
        if (!rst_n) begin
            p_m_valid <= 1'b0;
            p_m_ready <= 1'b0;
            p_m_sat   <= 1'b0;
            p_m_last  <= 1'b0;
            p_stall   <= 1'b0;
            p_fire    <= 1'b0;
            p_m_y     <= 8'sd0;
            p_acc     <= 32'sd0;
        end else begin
            p_m_valid <= m_valid;
            p_m_ready <= m_ready;
            p_m_sat   <= m_sat;
            p_m_last  <= m_last;
            p_stall   <= m_valid && !m_ready;
            p_fire    <= s_valid && s_ready;
            p_m_y     <= m_y;
            p_acc     <= dbg_acc;
        end
    end

    // ---- A1: reset leaves a deterministic, empty output stage ---------
    always @(posedge clk) begin
        if (!rst_n) begin
            assert(!m_valid);
            assert(m_y == 8'sd0);
            assert(!m_sat);
            assert(!m_last);
            assert(dbg_acc == 32'sd0);
        end
    end

    // ---- A2: backpressure freezes the whole channel -------------------
    // stall = m_valid && !m_ready. Both ready signals must drop.
    always @* begin
        if (m_valid && !m_ready) begin
            assert(!s_ready);
            assert(!cfg_ready);
        end
    end

    // ---- A3: configuration has priority over the input stream ---------
    always @* assert(!(cfg_valid && s_ready));

    // ---- A4: m_last is never asserted without m_valid -----------------
    always @* if (!m_valid) assert(!m_last);

    // ---- A5: valid + data stay stable for the whole stalled cycle -----
    always @(posedge clk) begin
        if (f_past_valid && rst_n && p_stall) begin
            assert(m_valid == p_m_valid);
            assert(m_y     == p_m_y);
            assert(m_sat   == p_m_sat);
            assert(m_last  == p_m_last);
        end
    end

    // ---- A6: no handshake => the accumulator must not advance ---------
    always @(posedge clk) begin
        if (f_past_valid && rst_n && !p_fire)
            assert(dbg_acc == p_acc);
    end

endmodule

`default_nettype wire
