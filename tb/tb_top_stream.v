//==========================================================================
// tb_top_stream.v - self-checking streaming/channel testbench
//
// Drives one cycle per line of vectors/gen/top_seq.hex and checks, on every
// cycle, both the combinational handshake (s_ready) and the registered output
// (m_valid / m_y / m_sat). Scenario covers:
//   - configuration load and reload
//   - a 3-beat group, back-to-back single-beat and 2-beat groups
//   - downstream stall (m_ready=0) with upstream still pushing
//   - reset in the middle of the stream
//   - drain until the output buffer is empty
//==========================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_top_stream;

    reg         clk   = 1'b0;
    reg         rst_n = 1'b0;
    reg         cfg_valid = 1'b0;
    reg  [15:0] cfg_r32  = 16'd0;
    reg  signed [15:0] cfg_bias = 16'sd0;
    reg         s_valid = 1'b0;
    reg  [63:0] s_x = 64'h0;
    reg  [63:0] s_w = 64'h0;
    reg         s_last = 1'b0;
    reg         m_ready = 1'b1;

    wire        cfg_ready, s_ready;
    wire        m_valid, m_sat, m_last;
    wire signed [7:0] m_y;
    wire [7:0]  m_y_bits;
    assign m_y_bits = m_y;

    int8_mac_top #(.N_LANE(8), .IN_W(8), .ACC_W(32), .R32_W(16), .BIAS_W(16)) u_dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .cfg_valid (cfg_valid),
        .cfg_r32   (cfg_r32),
        .cfg_bias  (cfg_bias),
        .cfg_ready (cfg_ready),
        .s_valid   (s_valid),
        .s_ready   (s_ready),
        .s_x       (s_x),
        .s_w       (s_w),
        .s_last    (s_last),
        .m_valid   (m_valid),
        .m_ready   (m_ready),
        .m_y       (m_y),
        .m_sat     (m_sat),
        .m_last    (m_last),
        .dbg_acc   (),
        .dbg_ovf   ()
    );

    always #5 clk = ~clk;

    integer vfd, dfd, code, i, errors, npts;
    reg        vrst, vcfg, vsvalid, vlast, vmready, vexpvalid, vexpsat, vexpsready;
    reg [15:0] vr32;
    reg [15:0] vbias;
    reg [63:0] vx, vw;
    reg [7:0]  vexpy;

    localparam integer N_VEC = 24;

    initial begin
        vfd = $fopen("vectors/gen/top_seq.hex", "r");
        dfd = $fopen("results/dump_top_stream.csv", "w");
        if (vfd == 0 || dfd == 0) begin
            $display("RESULT tb_top_stream FAIL (cannot open vectors/results)");
            $finish;
        end
        $fdisplay(dfd, "test,index,expected,actual");

        errors = 0;
        npts   = 0;

        for (i = 0; i < N_VEC; i = i + 1) begin
            code = $fscanf(vfd, "%h %h %h %h %h %h %h %h %h %h %h %h %h",
                           vrst, vcfg, vr32, vbias, vsvalid, vx, vw,
                           vlast, vmready, vexpvalid, vexpy, vexpsat, vexpsready);
            if (code != 13) begin
                $display("RESULT tb_top_stream FAIL (short vector file at %0d)", i);
                $fclose(vfd); $fclose(dfd); $finish;
            end

            // Drive all inputs on the falling edge, well before the next posedge.
            @(negedge clk);
            rst_n     = vrst;
            cfg_valid = vcfg;
            cfg_r32   = vr32;
            cfg_bias  = vbias;
            s_valid   = vsvalid;
            s_x       = vx;
            s_w       = vw;
            s_last    = vlast;
            m_ready   = vmready;

            // Combinational handshake check (pre-edge).
            #1;
            if (s_ready !== vexpsready) begin
                $display("  s_ready mismatch cycle=%0d exp=%b got=%b",
                         i, vexpsready, s_ready);
                errors = errors + 1;
            end

            // Registered output check (post-edge).
            @(posedge clk);
            #1;
            if (m_valid !== vexpvalid) begin
                $display("  m_valid mismatch cycle=%0d exp=%b got=%b",
                         i, vexpvalid, m_valid);
                errors = errors + 1;
            end
            if (vexpvalid && (m_y_bits !== vexpy || m_sat !== vexpsat)) begin
                $display("  payload mismatch cycle=%0d exp_y=%h got_y=%h exp_sat=%b got_sat=%b",
                         i, vexpy, m_y_bits, vexpsat, m_sat);
                errors = errors + 1;
            end
            $fdisplay(dfd, "top_stream,%0d,%h,%h", i,
                      {vexpvalid, vexpy, vexpsat},
                      {m_valid, m_y_bits, m_sat});
            npts = npts + 1;
        end

        $fclose(vfd);
        $fclose(dfd);
        $display("RESULT tb_top_stream  cycles=%0d mismatches=%0d", npts, errors);
        if (errors == 0) $display("RESULT tb_top_stream PASS");
        else             $display("RESULT tb_top_stream FAIL");
        $finish;
    end

endmodule

`default_nettype wire
