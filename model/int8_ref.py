#!/usr/bin/env python3
"""Bit-exact integer reference model for the clean-room INT8 MAC channel.

Standard library only. No numpy, no floating point anywhere in the datapath.

This module is the single source of truth for the arithmetic contract:
    acc = wrap32( sum_i(x_i * w_i) + bias )
    q   = wrap49( acc * r32 + 2^15 )
    y   = sat8( q >> 16 )                 # >> is arithmetic on Python ints

RTL (rtl/mac/requant.v) and the generator (model/gen_vectors.py) both follow
this file. If you change a width or the rounding constant here, change the
RTL too and re-run `make regress`.
"""

from __future__ import annotations

N_LANE = 8
IN_W = 8
ACC_W = 32
R32_W = 16
Q_W = ACC_W + R32_W + 1          # 49
SHIFT = 16
ROUND = 1 << (SHIFT - 1)         # 32768

INT8_MIN, INT8_MAX = -128, 127


def wrap_signed(value: int, width: int) -> int:
    """Two's-complement wrap to `width` bits and return a signed Python int."""
    mask = (1 << width) - 1
    v = value & mask
    if v >= (1 << (width - 1)):
        v -= 1 << width
    return v


def as_s8(value: int) -> int:
    return wrap_signed(value, IN_W)


def u16_of_s8(value: int) -> int:
    return value & 0xFF


def sat8(value: int) -> tuple[int, bool]:
    """Return (clipped INT8 value, saturation flag)."""
    if value > INT8_MAX:
        return INT8_MAX, True
    if value < INT8_MIN:
        return INT8_MIN, True
    return wrap_signed(value, IN_W), False


def mac_pe(a: int, b: int) -> int:
    """Signed 8x8 -> exact 16-bit product."""
    return as_s8(a) * as_s8(b)


def pack_lanes(lanes: list[int]) -> int:
    """8 INT8 lanes -> 64-bit packed word, lane 0 in the least significant byte."""
    assert len(lanes) == N_LANE
    word = 0
    for i, v in enumerate(lanes):
        word |= (u16_of_s8(v) & 0xFF) << (8 * i)
    return word


def unpack_lanes(word: int) -> list[int]:
    word &= (1 << (8 * N_LANE)) - 1
    return [as_s8((word >> (8 * i)) & 0xFF) for i in range(N_LANE)]


def mac_array(x: list[int], w: list[int]) -> int:
    """Exact sum of 8 lane products, wrapped to ACC_W bits (no saturation)."""
    total = sum(mac_pe(a, b) for a, b in zip(x, w))
    return wrap_signed(total, ACC_W)


def requant(acc: int, r32: int) -> tuple[int, bool]:
    """r32 multiply + round-to-nearest + arithmetic shift + single saturation."""
    acc = wrap_signed(acc, ACC_W)
    r32 = r32 & ((1 << R32_W) - 1)
    q = wrap_signed(acc * r32 + ROUND, Q_W)
    y_pre = q >> SHIFT                     # arithmetic shift for negative q
    return sat8(y_pre)


def layer_forward(x: list[int], w: list[int], bias: int, r32: int) -> dict:
    """One layer: 8-lane MAC -> +bias -> requant -> INT8."""
    acc = wrap_signed(mac_array(x, w) + wrap_signed(bias, 16), ACC_W)
    y, sat = requant(acc, r32)
    return {"acc": acc, "y": y, "sat": sat}


# --------------------------------------------------------------------------
# Streaming cycle model. Mirrors int8_mac_top's pipeline so gen_vectors.py can
# pre-compute expected outputs for tb_top_stream. Kept deliberately simple:
# one group per `last` beat, 2-cycle output latency, single-slot output buffer.
# --------------------------------------------------------------------------
def sim_stream(beats: list[dict], cfg: list[dict]) -> list[dict]:
    """Return one expected result dict per cycle.

    beats : list of {x, w, last, valid, m_ready}
    cfg   : list of {valid, r32, bias} aligned to beats (valid for one cycle)
    """
    r32, bias = 1, 0
    first, acc = True, 0
    rq_valid, rq_y, rq_sat = False, 0, False
    out_valid, out_y, out_sat = False, 0, False
    expect = []

    for t, beat in enumerate(beats):
        c = cfg[t]

        if not beat.get("rst_n", True):
            # Reset is asynchronous in the RTL for the registers, but the
            # model evaluates at clock edges: one full cycle of rst_n=0
            # wipes configuration, accumulator and all pipeline state.
            r32, bias = 1, 0
            first, acc = True, 0
            rq_valid, rq_y, rq_sat = False, 0, False
            out_valid, out_y, out_sat = False, 0, False
            expect.append({
                "cycle": t,
                "valid": False,
                "y": 0,
                "sat": False,
                # Asynchronous reset clears out_valid, so stall deasserts
                # immediately; s_ready follows cfg_valid only.
                "s_ready": not c["valid"],
            })
            continue

        if c["valid"]:
            r32, bias = c["r32"], c["bias"]

        stall = out_valid and not beat["m_ready"]
        # RTL s_ready = (!stall && !cfg_valid); a beat fires only when the
        # master asserts valid while s_ready is high.
        fire = beat["valid"] and (not stall) and (not c["valid"])

        din = mac_array(beat["x"], beat["w"])
        if first:
            din = wrap_signed(din + wrap_signed(bias, 16), ACC_W)
        acc_next = din if (fire and first) else (wrap_signed(acc + din, ACC_W) if fire else acc)

        # Cycle-accurate ordering: at the edge, the requant input stage and the
        # output buffer both update from their PRE-edge values.
        rq_valid_next, rq_y_next, rq_sat_next = rq_valid, rq_y, rq_sat
        if not stall:
            if fire and beat["last"]:
                rq_valid_next = True
                rq_y_next, rq_sat_next = requant(acc_next, r32)
            else:
                rq_valid_next = False

            if rq_valid:
                out_valid, out_y, out_sat = True, rq_y, rq_sat
            elif beat["m_ready"]:
                out_valid = False

        acc = acc_next
        if fire:
            first = beat["last"]
        rq_valid, rq_y, rq_sat = rq_valid_next, rq_y_next, rq_sat_next

        expect.append({
            "cycle": t,
            "valid": out_valid,
            "y": out_y if out_valid else 0,
            "sat": bool(out_sat) if out_valid else False,
            "s_ready": (not stall) and (not c["valid"]),
        })

    return expect


def self_test() -> list[str]:
    """Exhaustive / boundary self-checks. Returns a list of PASS lines."""
    out = []

    # 1. All 256x256 signed products.
    bad = 0
    for a in range(-128, 128):
        for b in range(-128, 128):
            p = mac_pe(a, b)
            if p != a * b or not (-16256 <= p <= 16384):
                bad += 1
    assert bad == 0, f"mac_pe mismatches: {bad}"
    out.append("PASS  mac_pe: all 65536 signed 8x8 products exact")

    # 2. Rounding boundary: +32768 must round, not truncate.
    #    acc*r32 = 65536 -> q = 98304 -> y_pre = 1 ; without ROUND it is 1 too.
    #    acc*r32 = 32768 -> q = 65536 -> y_pre = 1 ; truncation would give 0.
    assert requant(32768, 1)[0] == 1
    assert requant(-32768, 1)[0] == 0          # -32768+32768 = 0 -> 0
    assert requant(-32769, 1)[0] == -1         # -1 -> -1 (floor, not trunc)
    out.append("PASS  requant: round-to-nearest boundary on positive and negative q")

    # 3. Arithmetic (not logical) right shift on negative intermediate.
    assert requant(-65536, 1)[0] == -1
    assert requant(-131072, 1)[0] == -2
    out.append("PASS  requant: arithmetic shift for negative intermediates")

    # 4. Saturation both ends + sat flag.
    assert requant(1 << 30, 1024) == (127, True)
    assert requant(-(1 << 30), 1024) == (-128, True)
    assert requant(0, 1) == (0, False)
    out.append("PASS  requant: saturation hi/lo and saturation flag")

    # 5. r32 is a real multiplier, not a power-of-two shift.
    assert requant(65536, 3)[0] == 3
    assert requant(65536, 7)[0] == 7
    out.append("PASS  requant: non-power-of-two r32 scales are representable")

    # 6. Adder tree extremes.
    x = [127] * 8
    w = [127] * 8
    assert mac_array(x, w) == 8 * 127 * 127
    assert mac_array([-128] * 8, [127] * 8) == 8 * (-128) * 127
    out.append("PASS  mac_array: all-max and all-min lane extremes")

    # 7. Pack / unpack round trip.
    for v in (-128, -1, 0, 1, 127):
        assert unpack_lanes(pack_lanes([v] * 8)) == [v] * 8
    out.append("PASS  pack/unpack: lane ordering preserved")

    # 8. 32-bit wrap matches RTL acc_stage behaviour.
    assert wrap_signed(0x7FFFFFFF + 1, 32) == -2147483648
    assert wrap_signed(-2147483648 - 1, 32) == 2147483647
    out.append("PASS  wrap_signed: 32-bit two's-complement rollover")

    return out


if __name__ == "__main__":
    for line in self_test():
        print(line)
