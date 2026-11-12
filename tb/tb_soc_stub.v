//==========================================================================
// tb_soc_stub.v - self-checking 12-layer end-to-end testbench
//
// A minimal host FSM reads a 5-word-per-layer image from a behavioural SRAM,
// drives the streaming channel, feeds each INT8 result back as the next
// layer's activations, and writes all 12 results back to memory.
//
// Golden values come from model/int8_ref.py (vectors/gen/soc_expect.hex).
// Both the observable layer stream AND the write-back memory contents are
// checked, so a broken store path cannot pass unnoticed.
//==========================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_soc_stub;

    reg  clk = 1'b0;
    reg  rst_n = 1'b0;
    reg  start = 1'b0;

    wire busy, done, layer_valid;
    wire [7:0] layer_idx;
    wire signed [7:0] layer_y;
    wire [7:0] ly_bits;
    assign ly_bits = layer_y;

    mac_soc_stub #(
        .N_LAYER   (12),
        .DEPTH     (1024),
        .WPERL     (5),
        .INIT_FILE ("vectors/gen/soc_mem.hex")
    ) u_dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .busy        (busy),
        .done        (done),
        .layer_valid (layer_valid),
        .layer_idx   (layer_idx),
        .layer_y     (layer_y)
    );

    always #5 clk = ~clk;

    localparam integer OUT_BASE = 60;

    integer vfd, dfd, code, i, errors, npts, cy, timeout;
    reg [7:0]  vl, vexpy;
    reg [31:0] vacc;
    reg        vsat;
    reg [7:0]  exp_y [0:11];
    reg [7:0]  got_y [0:11];

    initial begin
        for (i = 0; i < 12; i = i + 1) begin
            exp_y[i] = 8'h00;
            got_y[i] = 8'h00;
        end

        vfd = $fopen("vectors/gen/soc_expect.hex", "r");
        dfd = $fopen("results/dump_soc_stub.csv", "w");
        if (vfd == 0 || dfd == 0) begin
            $display("RESULT tb_soc_stub FAIL (cannot open vectors/results)");
            $finish;
        end
        $fdisplay(dfd, "test,index,expected,actual");

        for (i = 0; i < 12; i = i + 1) begin
            code = $fscanf(vfd, "%h %h %h %h", vl, vacc, vexpy, vsat);
            if (code != 4) begin
                $display("RESULT tb_soc_stub FAIL (short golden file at %0d)", i);
                $finish;
            end
            exp_y[vl] = vexpy;
        end
        $fclose(vfd);

        errors  = 0;
        npts    = 0;
        timeout = 0;

        @(negedge clk);
        @(negedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        start = 1'b1;
        @(posedge clk);
        #1;
        start = 1'b0;

        for (cy = 0; (cy < 5000) && (done !== 1'b1); cy = cy + 1) begin
            @(posedge clk);
        end
        if (done !== 1'b1) begin
            timeout = 1;
            $display("  TIMEOUT: done never asserted");
        end
        #1;

        if (npts != 12) begin
            $display("  layer stream count %0d (expected 12)", npts);
            errors = errors + 1;
        end

        // Write-back memory is checked independently of the layer stream.
        for (i = 0; i < 12; i = i + 1) begin
            if (u_dut.u_sram.mem[OUT_BASE + i][7:0] !== exp_y[i]) begin
                $display("  memory mismatch layer=%0d exp=%h got=%h", i,
                         exp_y[i], u_dut.u_sram.mem[OUT_BASE + i][7:0]);
                errors = errors + 1;
            end
        end

        $fclose(dfd);
        $display("RESULT tb_soc_stub  layers=%0d timeout=%0d mismatches=%0d",
                 npts, timeout, errors);
        if ((errors == 0) && (timeout == 0)) $display("RESULT tb_soc_stub PASS");
        else                                $display("RESULT tb_soc_stub FAIL");
        $finish;
    end

    always @(negedge clk) begin
        if (layer_valid === 1'b1) begin
            if (layer_idx < 12) begin
                got_y[layer_idx] = ly_bits;
                if (ly_bits !== exp_y[layer_idx]) begin
                    $display("  layer mismatch layer=%0d exp=%h got=%h",
                             layer_idx, exp_y[layer_idx], ly_bits);
                    errors = errors + 1;
                end
                $fdisplay(dfd, "soc_stub,%0d,%h,%h", layer_idx,
                          exp_y[layer_idx], ly_bits);
                npts = npts + 1;
            end else begin
                $display("  layer index out of range: %0d", layer_idx);
                errors = errors + 1;
            end
        end
    end

endmodule

`default_nettype wire
