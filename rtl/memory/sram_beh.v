//==========================================================================
// sram_beh.v  -  behavioural single-port SRAM (replaceable)
//
// Deliberately NOT a real SRAM macro and NOT synthesised as one. It exists so
// the SoC stub can run end-to-end without any vendor memory or PDK.
//
//   - synchronous write, combinational (asynchronous) read
//   - read-during-write returns the OLD contents; the new value is visible
//     from the next cycle on
//   - out-of-range addresses are guarded by the addr width, and the testbench
//     explicitly probes the last valid address DEPTH-1
//
// Initialisation is performed by the parent (mac_soc_stub) with $readmemh so
// that there is exactly one initial block owning the memory array.
//==========================================================================
`default_nettype none

module sram_beh #(
    parameter integer DEPTH = 1024,
    parameter integer WIDTH = 32,
    parameter integer AW    = $clog2(DEPTH)
) (
    input  wire                clk,
    input  wire                en,
    input  wire                we,
    input  wire [AW-1:0]       addr,
    input  wire [WIDTH-1:0]    din,
    output wire [WIDTH-1:0]    dout
);

    reg [WIDTH-1:0] mem [0:DEPTH-1];

    assign dout = mem[addr];

    always @(posedge clk) begin
        if (en && we) begin
            mem[addr] <= din;
        end
    end

endmodule

`default_nettype wire
