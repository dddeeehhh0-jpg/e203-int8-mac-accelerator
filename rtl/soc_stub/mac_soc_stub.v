//==========================================================================
// mac_soc_stub.v  -  minimal host FSM, end-to-end driver for int8_mac_top
//
// Stands in for the processor + DMA so the streaming channel can be exercised
// without an E203 core, a bus or a toolchain. It is a BEHAVIOURAL stub: the
// $readmemh initialisation and hierarchical memory access are simulation-only
// constructs and are not intended for synthesis.
//
// Memory map (32-bit words, one 5-word record per layer):
//   +0  x[31:0]        (layer 0 only; later layers feed back the previous y)
//   +1  x[63:32]
//   +2  w[31:0]
//   +3  w[63:32]
//   +4  {r32[15:0], bias[15:0]}
//   OUT_BASE + L  <-  sign-extended y of layer L
//
// Layer recurrence (mirrored exactly by model/int8_ref.py):
//   acc_L = sum_i(x_L[i] * w_L[i]) + bias_L
//   y_L   = sat8((acc_L * r32_L + 32768) >>> 16)
//   x_{L+1}[i] = y_L  for all 8 lanes
//==========================================================================
`default_nettype none

module mac_soc_stub #(
    parameter integer N_LAYER    = 12,
    parameter integer DEPTH      = 1024,
    parameter integer WPERL      = 5,
    parameter          INIT_FILE = "vectors/gen/soc_mem.hex"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,

    output reg          busy,
    output reg          done,
    output reg          layer_valid,
    output reg  [7:0]   layer_idx,
    output reg signed [7:0] layer_y
);

    localparam integer OUT_BASE = N_LAYER * WPERL;
    localparam integer AW       = $clog2(DEPTH);

    localparam [3:0] S_IDLE  = 4'd0,
                     S_CFG   = 4'd1,
                     S_L0    = 4'd2,
                     S_L1    = 4'd3,
                     S_L2    = 4'd4,
                     S_L3    = 4'd5,
                     S_FIRE  = 4'd6,
                     S_WAIT  = 4'd7,
                     S_STORE = 4'd8,
                     S_DONE  = 4'd9;

    reg [3:0]  state;
    reg [7:0]  layer_q;
    reg [31:0] x_lo_q, x_hi_q, w_lo_q, w_hi_q;
    reg [15:0] r32_q;
    reg signed [15:0] bias_q;
    reg signed [7:0]  y_prev;

    reg [AW-1:0]    sram_addr;
    reg             sram_en, sram_we;
    reg [31:0]      sram_din;
    wire [31:0]     sram_dout;

    reg             cfg_valid;
    reg [15:0]      cfg_r32;
    reg signed [15:0] cfg_bias;
    reg             s_valid;
    wire            s_ready;
    wire [63:0]     x_vec, w_vec;
    wire            m_valid;
    wire signed [7:0] m_y;
    wire            m_sat, m_last;

    assign x_vec = (layer_q == 8'd0) ? {x_hi_q, x_lo_q} : {8{y_prev[7:0]}};
    assign w_vec = {w_hi_q, w_lo_q};

    // ---- memory address / write control (combinational) ----------------
    integer rec_base;
    always @* begin
        rec_base  = layer_q * WPERL;
        sram_addr = {AW{1'b0}};
        sram_en   = 1'b0;
        sram_we   = 1'b0;
        sram_din  = 32'h0;
        case (state)
            S_CFG  : sram_addr = rec_base + 4;
            S_L0   : sram_addr = rec_base + 0;
            S_L1   : sram_addr = rec_base + 1;
            S_L2   : sram_addr = rec_base + 2;
            S_L3   : sram_addr = rec_base + 3;
            S_STORE: begin
                sram_addr = OUT_BASE + layer_q;
                sram_en   = 1'b1;
                sram_we   = 1'b1;
                sram_din  = {{24{y_prev[7]}}, y_prev[7:0]};
            end
            default: sram_addr = {AW{1'b0}};
        endcase
    end

    sram_beh #(.DEPTH(DEPTH), .WIDTH(32)) u_sram (
        .clk  (clk),
        .en   (sram_en),
        .we   (sram_we),
        .addr (sram_addr),
        .din  (sram_din),
        .dout (sram_dout)
    );

    int8_mac_top #(.N_LANE(8), .IN_W(8), .ACC_W(32), .R32_W(16), .BIAS_W(16)) u_top (
        .clk       (clk),
        .rst_n     (rst_n),
        .cfg_valid (cfg_valid),
        .cfg_r32   (cfg_r32),
        .cfg_bias  (cfg_bias),
        .cfg_ready (),
        .s_valid   (s_valid),
        .s_ready   (s_ready),
        .s_x       (x_vec),
        .s_w       (w_vec),
        .s_last    (1'b1),
        .m_valid   (m_valid),
        .m_ready   (1'b1),
        .m_y       (m_y),
        .m_sat     (m_sat),
        .m_last    (m_last),
        .dbg_acc   (),
        .dbg_ovf   ()
    );

    // ---- simulation-only memory image ----------------------------------
    initial begin : load_image
        integer i;
        for (i = 0; i < DEPTH; i = i + 1) begin
            u_sram.mem[i] = 32'h0000_0000;
        end
        $readmemh(INIT_FILE, u_sram.mem);
    end

    // ---- FSM -----------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            layer_q     <= 8'd0;
            x_lo_q      <= 32'h0;
            x_hi_q      <= 32'h0;
            w_lo_q      <= 32'h0;
            w_hi_q      <= 32'h0;
            r32_q       <= 16'd1;
            bias_q      <= 16'sd0;
            y_prev      <= 8'sd0;
            cfg_valid   <= 1'b0;
            s_valid     <= 1'b0;
            layer_valid <= 1'b0;
            layer_idx   <= 8'd0;
            layer_y     <= 8'sd0;
            busy        <= 1'b0;
            done        <= 1'b0;
        end else begin
            cfg_valid   <= 1'b0;
            s_valid     <= 1'b0;
            layer_valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        layer_q <= 8'd0;
                        y_prev  <= 8'sd0;
                        busy    <= 1'b1;
                        state   <= S_CFG;
                    end
                end

                S_CFG: begin
                    r32_q     <= sram_dout[31:16];
                    bias_q    <= sram_dout[15:0];
                    cfg_r32   <= sram_dout[31:16];
                    cfg_bias  <= sram_dout[15:0];
                    cfg_valid <= 1'b1;
                    state     <= S_L0;
                end

                S_L0: begin x_lo_q <= sram_dout; state <= S_L1; end
                S_L1: begin x_hi_q <= sram_dout; state <= S_L2; end
                S_L2: begin w_lo_q <= sram_dout; state <= S_L3; end
                S_L3: begin w_hi_q <= sram_dout; state <= S_FIRE; end

                S_FIRE: begin
                    s_valid <= 1'b1;
                    if (s_ready) begin
                        state <= S_WAIT;
                    end
                end

                S_WAIT: begin
                    if (m_valid) begin
                        y_prev      <= m_y;
                        layer_y     <= m_y;
                        layer_idx   <= layer_q;
                        layer_valid <= 1'b1;
                        state       <= S_STORE;
                    end
                end

                S_STORE: begin
                    if (layer_q == N_LAYER - 1) begin
                        state <= S_DONE;
                    end else begin
                        layer_q <= layer_q + 8'd1;
                        state   <= S_CFG;
                    end
                end

                S_DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
