//==========================================================================
// mac_pe.v  -  single INT8 multiply lane
//
// Contract:
//   a, b are signed two's-complement 8-bit operands.
//   p    is the signed 16-bit product, valid in the same cycle (combinational).
//
// Why 16 bits:  (-128)*(-128) = +16384 < 2^14,  and
//               (-128)*(127)  = -16256 > -2^14.
// So the exact product always fits in 15 bits; 16 is kept for clean slicing
// into the 8-lane array.
//==========================================================================
`default_nettype none

module mac_pe #(
    parameter integer IN_W = 8
) (
    input  wire signed [IN_W-1:0]   a,
    input  wire signed [IN_W-1:0]   b,
    output wire signed [2*IN_W-1:0] p
);

    // Context width of the multiplication is 2*IN_W, so the product is
    // evaluated at full precision instead of being truncated to IN_W.
    assign p = a * b;

endmodule

`default_nettype wire
