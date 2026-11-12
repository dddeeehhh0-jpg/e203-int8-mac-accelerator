//==========================================================================
// tb_mac_array.v - self-checking 8-lane adder-tree reduction
//
// 5000 random groups + 4 hand-picked extreme groups. Golden = exact 32-bit
// signed sum of 8 INT8 products, produced by the Python reference model.
//==========================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_mac_array;

    reg  [63:0] x, w;
    wire signed [31:0] sum;

    mac_array #(.N_LANE(8), .IN_W(8), .ACC_W(32)) u_dut (
        .x   (x),
        .w   (w),
        .sum (sum)
    );

    integer vfd, dfd, code, i, errors, npts;
    reg [63:0] vx, vw;
    reg [31:0] vsum;

    initial begin
        vfd = $fopen("vectors/gen/array_rand.hex", "r");
        dfd = $fopen("results/dump_mac_array.csv", "w");
        if (vfd == 0 || dfd == 0) begin
            $display("RESULT tb_mac_array FAIL (cannot open vectors/results)");
            $finish;
        end
        $fdisplay(dfd, "test,index,expected,actual");

        errors = 0;
        npts   = 0;
        x = 64'h0;
        w = 64'h0;

        for (i = 0; i < 5004; i = i + 1) begin
            code = $fscanf(vfd, "%h %h %h", vx, vw, vsum);
            if (code != 3) begin
                $display("RESULT tb_mac_array FAIL (short vector file at %0d)", i);
                $fclose(vfd); $fclose(dfd); $finish;
            end
            x = vx;
            w = vw;
            #1;
            if (sum !== vsum) begin
                if (errors < 5) begin
                    $display("  mismatch i=%0d x=%h w=%h exp=%h got=%h",
                             i, vx, vw, vsum, sum);
                end
                errors = errors + 1;
            end
            $fdisplay(dfd, "mac_array,%0d,%h,%h", i, vsum, sum);
            npts = npts + 1;
        end

        $fclose(vfd);
        $fclose(dfd);
        $display("RESULT tb_mac_array  points=%0d mismatches=%0d", npts, errors);
        if (errors == 0) $display("RESULT tb_mac_array PASS");
        else             $display("RESULT tb_mac_array FAIL");
        $finish;
    end

endmodule

`default_nettype wire
