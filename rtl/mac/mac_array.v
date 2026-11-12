//==========================================================================
// mac_array.v  -  N_LANE parallel INT8 multiplies + balanced adder tree
//
// x and w are packed vectors: lane i occupies x[i*IN_W +: IN_W].
// sum is the EXACT signed sum of all lane products (no saturation here).
//
// Width reasoning (N_LANE=8, IN_W=8):
//   |product| <= 16384, 8 lanes -> |sum| <= 131072 < 2^18.
//   A 32-bit accumulator is therefore safe for thousands of groups.
//
// For the default N_LANE=8 the reduction is an EXPLICIT 3-level tree: the
// structure is visible in the synthesis netlist instead of being flattened
// into a serial carry chain. Other lane counts fall back to a portable
// generic reduction (functionally identical, structurally not balanced).
//==========================================================================
`default_nettype none

module mac_array #(
    parameter integer N_LANE = 8,
    parameter integer IN_W   = 8,
    parameter integer ACC_W  = 32
) (
    input  wire [N_LANE*IN_W-1:0]  x,
    input  wire [N_LANE*IN_W-1:0]  w,
    output wire signed [ACC_W-1:0] sum
);

    wire signed [2*IN_W-1:0] prod [0:N_LANE-1];

    genvar gi;
    generate
        for (gi = 0; gi < N_LANE; gi = gi + 1) begin : g_lane
            mac_pe #(.IN_W(IN_W)) u_pe (
                .a (x[gi*IN_W +: IN_W]),
                .b (w[gi*IN_W +: IN_W]),
                .p (prod[gi])
            );
        end
    endgenerate

    generate
        if (N_LANE == 8) begin : g_tree8

            wire signed [ACC_W-1:0] l0 [0:7];
            wire signed [ACC_W-1:0] l1 [0:3];
            wire signed [ACC_W-1:0] l2 [0:1];

            genvar j;
            for (j = 0; j < 8; j = j + 1) begin : g_sext
                assign l0[j] = {{(ACC_W-2*IN_W){prod[j][2*IN_W-1]}}, prod[j]};
            end

            assign l1[0] = l0[0] + l0[1];
            assign l1[1] = l0[2] + l0[3];
            assign l1[2] = l0[4] + l0[5];
            assign l1[3] = l0[6] + l0[7];

            assign l2[0] = l1[0] + l1[1];
            assign l2[1] = l1[2] + l1[3];

            assign sum = l2[0] + l2[1];

        end else begin : g_tree_generic

            reg signed [ACC_W-1:0] sum_r;
            integer i;
            always @* begin
                sum_r = {ACC_W{1'b0}};
                for (i = 0; i < N_LANE; i = i + 1) begin
                    sum_r = sum_r + {{(ACC_W-2*IN_W){prod[i][2*IN_W-1]}}, prod[i]};
                end
            end
            assign sum = sum_r;

        end
    endgenerate

endmodule

`default_nettype wire
