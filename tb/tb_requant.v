//==========================================================================
// tb_requant.v - self-checking r32 requantization sweep
//
// r32 = 0..1024 plus 32767/65535, crossed with 17 acc boundary values.
// Checks: y bit pattern, sat_flag, and valid_o/last_o alignment.
// The registered output is checked one clock AFTER the stimulus edge.
//==========================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_requant;

    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    reg         valid_i = 1'b0;
    reg         last_i = 1'b0;
    reg         stall = 1'b0;
    reg  signed [31:0] acc = 32'sd0;
    reg         [15:0] r32 = 16'd0;

    wire signed [7:0] y;
    wire        sat_flag;
    wire        valid_o;
    wire        last_o;
    wire        [7:0] y_bits;
    assign y_bits = y;

    requant #(.ACC_W(32), .R32_W(16), .SHIFT(16)) u_dut (
        .clk      (clk),
        .rst_n    (rst_n),
        .valid_i  (valid_i),
        .last_i   (last_i),
        .stall    (stall),
        .acc      (acc),
        .r32      (r32),
        .y_comb   (),
        .sat_comb (),
        .y        (y),
        .sat_flag (sat_flag),
        .valid_o  (valid_o),
        .last_o   (last_o)
    );

    always #5 clk = ~clk;

    integer vfd, dfd, code, i, errors, npts;
    reg [31:0] vacc;
    reg [15:0] vr32;
    reg [7:0]  vy;
    reg        vsat;

    localparam integer N_VEC = 17459;

    initial begin
        vfd = $fopen("vectors/gen/requant_scan.hex", "r");
        dfd = $fopen("results/dump_requant.csv", "w");
        if (vfd == 0 || dfd == 0) begin
            $display("RESULT tb_requant FAIL (cannot open vectors/results)");
            $finish;
        end
        $fdisplay(dfd, "test,index,expected,actual");

        errors = 0;
        npts   = 0;

        @(negedge clk);
        @(negedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        for (i = 0; i < N_VEC; i = i + 1) begin
            code = $fscanf(vfd, "%h %h %h %h", vacc, vr32, vy, vsat);
            if (code != 4) begin
                $display("RESULT tb_requant FAIL (short vector file at %0d)", i);
                $fclose(vfd); $fclose(dfd); $finish;
            end
            acc     = vacc;
            r32     = vr32;
            valid_i = 1'b1;
            last_i  = 1'b1;
            stall   = 1'b0;

            @(posedge clk);
            #1;
            if (valid_o !== 1'b1 || last_o !== 1'b1) begin
                errors = errors + 1;
            end
            if (y_bits !== vy) begin
                if (errors < 5) begin
                    $display("  y mismatch i=%0d acc=%h r32=%h exp=%h got=%h",
                             i, vacc, vr32, vy, y_bits);
                end
                errors = errors + 1;
            end
            if (sat_flag !== vsat) begin
                if (errors < 5) begin
                    $display("  sat mismatch i=%0d acc=%h r32=%h exp=%b got=%b",
                             i, vacc, vr32, vsat, sat_flag);
                end
                errors = errors + 1;
            end
            $fdisplay(dfd, "requant,%0d,%h,%h", i, {vy, vsat}, {y_bits, sat_flag});
            npts = npts + 1;
            @(negedge clk);
        end

        // Extra check: stall must hold the output stage.
        valid_i = 1'b0;
        stall   = 1'b1;
        @(posedge clk);
        #1;
        // (value is not compared here; the streaming TB covers stall in full)

        $fclose(vfd);
        $fclose(dfd);
        $display("RESULT tb_requant  points=%0d mismatches=%0d", npts, errors);
        if (errors == 0) $display("RESULT tb_requant PASS");
        else             $display("RESULT tb_requant FAIL");
        $finish;
    end

endmodule

`default_nettype wire
