//==========================================================================
// tb_mac_pe.v - self-checking, exhaustive 256x256 signed multiply
//
// Golden values come from model/int8_ref.py via model/gen_vectors.py
// (vectors/gen/pe_full.hex). The TB never recomputes the golden product.
// Also emits results/dump_mac_pe.csv for the independent Python scoreboard.
//==========================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_mac_pe;

    reg  [7:0]  a, b;
    wire signed [15:0] p;

    mac_pe #(.IN_W(8)) u_dut (
        .a (a),
        .b (b),
        .p (p)
    );

    integer vfd, dfd, code, i, errors, npts;
    reg  [7:0]  va, vb;
    reg  [15:0] vp;

    initial begin
        vfd = $fopen("vectors/gen/pe_full.hex", "r");
        dfd = $fopen("results/dump_mac_pe.csv", "w");
        if (vfd == 0 || dfd == 0) begin
            $display("RESULT tb_mac_pe FAIL (cannot open vectors/results)");
            $finish;
        end
        $fdisplay(dfd, "test,index,expected,actual");

        errors = 0;
        npts   = 0;
        a = 8'h00;
        b = 8'h00;

        for (i = 0; i < 65536; i = i + 1) begin
            code = $fscanf(vfd, "%h %h %h", va, vb, vp);
            if (code != 3) begin
                $display("RESULT tb_mac_pe FAIL (short vector file at %0d)", i);
                $fclose(vfd); $fclose(dfd); $finish;
            end
            a = va;
            b = vb;
            #1;
            if (p !== vp) begin
                if (errors < 5) begin
                    $display("  mismatch a=%h b=%h exp=%h got=%h", va, vb, vp, p);
                end
                errors = errors + 1;
            end
            $fdisplay(dfd, "mac_pe,%0d,%h,%h", i, vp, p);
            npts = npts + 1;
        end

        $fclose(vfd);
        $fclose(dfd);
        $display("RESULT tb_mac_pe  points=%0d mismatches=%0d", npts, errors);
        if (errors == 0) $display("RESULT tb_mac_pe PASS");
        else             $display("RESULT tb_mac_pe FAIL");
        $finish;
    end

endmodule

`default_nettype wire
