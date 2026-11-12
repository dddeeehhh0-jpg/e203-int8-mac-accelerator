#!/usr/bin/env python3
"""Deterministic vector generator (stdlib only).

Run from the repository root:
    python3 model/gen_vectors.py

All outputs go to vectors/gen/ (gitignored, reproducible) and a tiny set of
fixed examples goes to vectors/smoke/ (committed, so a fresh clone has
something to look at before running anything).

Every generated file is hashed into vectors/gen/manifest.csv. With SEED fixed,
running the generator twice must produce byte-identical files.
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import int8_ref as ref

SEED = 20261112
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "vectors", "gen")
SMOKE = os.path.join(ROOT, "vectors", "smoke")

N_LAYER = 12
SOC_DEPTH = 1024
WPERL = 5
OUT_BASE = N_LAYER * WPERL


def u(value: int, width: int) -> int:
    return value & ((1 << width) - 1)


def write_lines(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def gen_pe() -> list[str]:
    lines = []
    for a in range(256):
        sa = ref.as_s8(a)
        for b in range(256):
            sb = ref.as_s8(b)
            p = u(sa * sb, 16)
            lines.append(f"{a:02x} {b:02x} {p:04x}")
    return lines


def gen_array(rng: random.Random, count: int = 5000) -> list[str]:
    lines = []
    extremes = [
        ([127] * 8, [127] * 8),
        ([-128] * 8, [127] * 8),
        ([-128] * 8, [-128] * 8),
        ([127, -128] * 4, [127, -128] * 4),
    ]
    for x, w in extremes:
        xp, wp = ref.pack_lanes(x), ref.pack_lanes(w)
        lines.append(f"{xp:016x} {wp:016x} {u(ref.mac_array(x, w), 32):08x}")
    for _ in range(count):
        x = [rng.randint(-128, 127) for _ in range(8)]
        w = [rng.randint(-128, 127) for _ in range(8)]
        xp, wp = ref.pack_lanes(x), ref.pack_lanes(w)
        lines.append(f"{xp:016x} {wp:016x} {u(ref.mac_array(x, w), 32):08x}")
    return lines


def gen_requant() -> list[str]:
    acc_edges = [
        0, 1, -1, 32767, 32768, 32769, -32768, -32769,
        65535, 65536, -65536, 131072, -131072,
        (1 << 31) - 1, -(1 << 31), 1234567, -987654,
    ]
    r32_values = list(range(0, 1025)) + [32767, 65535]
    lines = []
    for r32 in r32_values:
        for acc in acc_edges:
            y, sat = ref.requant(acc, r32)
            lines.append(
                f"{u(acc, 32):08x} {u(r32, 16):04x} {u(y, 8):02x} {int(sat):01x}"
            )
    return lines


def build_stream_scenario() -> tuple[list[dict], list[dict]]:
    """Hand-designed scenario: cfg, 3-beat group, back-to-back groups,
    stall, cfg reload, mid-stream reset, drain.
    """
    beats: list[dict] = []
    cfg: list[dict] = []

    def beat(rst_n=1, cv=0, r32=0, bias=0, sv=0, x=None, w=None,
             last=0, m_ready=1):
        beats.append({
            "rst_n": rst_n,
            "valid": sv,
            "x": x if x is not None else [0] * 8,
            "w": w if w is not None else [0] * 8,
            "last": last,
            "m_ready": m_ready,
        })
        cfg.append({"valid": cv, "r32": r32, "bias": bias})

    # t0  reset
    beat(rst_n=0)
    # t1  load r32=1024, bias=7 (large enough to produce non-zero INT8 results)
    beat(cv=1, r32=1024, bias=7)
    # t2..t4  group A (3 beats)
    beat(sv=1, x=[1, 2, 3, 4, 5, 6, 7, 8], w=[2] * 8)
    beat(sv=1, x=[-1, -2, -3, -4, -5, -6, -7, -8], w=[3] * 8)
    beat(sv=1, x=[4] * 8, w=[5] * 8, last=1)
    # t5  group B: single beat, immediately after A (back-to-back)
    beat(sv=1, x=[10] * 8, w=[-2] * 8, last=1)
    # t6..t7  group C (2 beats)
    beat(sv=1, x=[7] * 8, w=[1] * 8)
    beat(sv=1, x=[-3] * 8, w=[6] * 8, last=1)
    # t8..t10  downstream not ready -> stall, upstream keeps trying to push
    beat(sv=1, x=[9] * 8, w=[9] * 8, last=1, m_ready=0)
    beat(sv=1, x=[9] * 8, w=[9] * 8, last=1, m_ready=0)
    beat(sv=1, x=[9] * 8, w=[9] * 8, last=1, m_ready=0)
    # t11  drain resumes
    beat(m_ready=1)
    # t12  reload configuration
    beat(cv=1, r32=512, bias=-3)
    # t13  group D
    beat(sv=1, x=[20] * 8, w=[3] * 8, last=1)
    # t14  reset in the middle of the stream
    beat(rst_n=0)
    # t15  fresh configuration
    beat(cv=1, r32=256, bias=1)
    # t16  group E
    beat(sv=1, x=[-5] * 8, w=[4] * 8, last=1)
    # t17..t23  drain
    for _ in range(7):
        beat()
    return beats, cfg


def gen_top_seq() -> list[str]:
    beats, cfg = build_stream_scenario()
    expect = ref.sim_stream(beats, cfg)
    lines = []
    for t, b in enumerate(beats):
        c = cfg[t]
        e = expect[t]
        fields = [
            f"{b['rst_n']:01x}",
            f"{c['valid']:01x}",
            f"{u(c['r32'], 16):04x}",
            f"{u(c['bias'], 16):04x}",
            f"{b['valid']:01x}",
            f"{ref.pack_lanes(b['x']):016x}",
            f"{ref.pack_lanes(b['w']):016x}",
            f"{b['last']:01x}",
            f"{b['m_ready']:01x}",
            f"{int(e['valid']):01x}",
            f"{u(e['y'], 8):02x}",
            f"{int(e['sat']):01x}",
            f"{int(e['s_ready']):01x}",
        ]
        lines.append(" ".join(fields))
    return lines


def gen_soc(rng: random.Random) -> tuple[list[str], list[str]]:
    """12-layer feed-forward chain with feedback of the previous INT8 output.

    The final layer is deliberately driven into saturation so the end-to-end
    testbench exercises both the linear region and the saturation path.
    """
    mem = [0] * SOC_DEPTH
    x0 = [rng.randint(-8, 8) for _ in range(8)]
    x = list(x0)
    golden = []

    for layer in range(N_LAYER):
        if layer == N_LAYER - 1:
            w = [127 if (i % 2 == 0) else -128 for i in range(8)]
            r32 = 1024
            bias = 30000
        else:
            w = [rng.randint(-6, 6) for _ in range(8)]
            r32 = rng.randint(256, 1024)
            bias = rng.randint(-256, 256)

        rec = [
            u(ref.pack_lanes(x), 32),
            u(ref.pack_lanes(x) >> 32, 32),
            u(ref.pack_lanes(w), 32),
            u(ref.pack_lanes(w) >> 32, 32),
            (u(r32, 16) << 16) | u(bias, 16),
        ]
        for j, word in enumerate(rec):
            mem[layer * WPERL + j] = word

        res = ref.layer_forward(x, w, bias, r32)
        golden.append({
            "layer": layer,
            "acc": res["acc"],
            "y": res["y"],
            "sat": int(res["sat"]),
        })
        x = [res["y"]] * 8

    mem_lines = [f"{word & 0xFFFFFFFF:08x}" for word in mem]
    # Space-separated hex: `layer acc32 y8 sat`. The testbench reads these
    # with %h, so bit patterns compare without signed/unsigned ambiguity.
    return mem_lines, [
        f"{g['layer']:02x} {u(g['acc'], 32):08x} {u(g['y'], 8):02x} {g['sat']:01x}"
        for g in golden
    ]


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    os.makedirs(GEN, exist_ok=True)
    os.makedirs(SMOKE, exist_ok=True)
    rng = random.Random(SEED)

    jobs: list[tuple[str, list[str]]] = []
    jobs.append(("pe_full.hex", gen_pe()))
    jobs.append(("array_rand.hex", gen_array(rng)))
    jobs.append(("requant_scan.hex", gen_requant()))
    jobs.append(("top_seq.hex", gen_top_seq()))

    # Legal NICE-style sequence used by tb_nice_adapter.
    nice_x = [10] * 8
    nice_w = [3] * 8
    nice_y, nice_sat = ref.requant(
        ref.wrap_signed(ref.mac_array(nice_x, nice_w) + 7, 32), 1024
    )
    nice_xw = ref.pack_lanes(nice_x)
    nice_ww = ref.pack_lanes(nice_w)
    xlo, xhi = u(nice_xw, 32), u(nice_xw >> 32, 32)
    wlo, whi = u(nice_ww, 32), u(nice_ww >> 32, 32)
    jobs.append(("nice_expect.hex", [
        f"{u(nice_y, 8):02x} {int(nice_sat):01x} "
        f"{xlo:08x} {xhi:08x} {wlo:08x} {whi:08x} "
        f"{1024:04x} {u(7, 16):04x}"
    ]))

    # Command stream: `funct7 rs1 rs2 exp_err exp_data`
    # One legal sequence interleaved with five classes of illegal sequence.
    err_word = 0xDEADBEEF
    read_data = u(nice_y, 32)          # sign-extended INT8 result
    nice_seq: list[str] = []

    def cmd(f: int, r1: int, r2: int, err: bool, data: int = 0) -> None:
        nice_seq.append(
            f"{u(f, 7):02x} {u(r1, 32):08x} {u(r2, 32):08x} "
            f"{int(err):01x} {u(data if not err else err_word, 32):08x}"
        )

    cmd(0x05, 0, 0, True)                       # 1. MAC with nothing set up
    cmd(0x01, 0, 1024, False)                  #    SET_R32
    cmd(0x05, 0, 0, True)                       # 2. MAC before bias/operands
    cmd(0x02, 7, 0, False)                      #    SET_BIAS
    cmd(0x05, 0, 0, True)                       # 3. MAC before LOAD_X/LOAD_W
    cmd(0x03, xlo, xhi, False)                  #    LOAD_X
    cmd(0x05, 0, 0, True)                       # 3b. MAC without W
    cmd(0x06, 0, 0, True)                       # 4. READ with no result
    cmd(0x7f, 0, 0, True)                       # 5. unknown funct7
    cmd(0x04, wlo, whi, False)                  #    LOAD_W
    cmd(0x05, 0, 0, False)                      #    MAC (legal)
    cmd(0x06, 0, 0, False, read_data)           #    READ (legal)
    cmd(0x06, 0, 0, True)                       # 4b. READ after result consumed
    jobs.append(("nice_seq.hex", nice_seq))

    soc_mem, soc_expect = gen_soc(rng)
    jobs.append(("soc_mem.hex", soc_mem))
    jobs.append(("soc_expect.hex", soc_expect))

    manifest = ["file,lines,sha256"]
    for name, lines in jobs:
        path = os.path.join(GEN, name)
        write_lines(path, lines)
        manifest.append(f"{name},{len(lines)},{sha256_of(path)}")

    # Committed smoke samples: fixed, tiny, human-readable.
    write_lines(os.path.join(SMOKE, "pe_smoke.hex"), [
        "00 00 0000", "7f 7f 3f01", "80 7f c040",
        "80 80 4000", "ff ff 0001", "01 80 ff80",
    ])
    write_lines(os.path.join(SMOKE, "requant_smoke.hex"), [
        "00000000 0001 00 0",
        "00008000 0001 01 0",
        "ffff8000 0001 ff 0",
        "00010000 0003 03 0",
        "40000000 0400 7f 1",
        "c0000000 0400 80 1",
    ])
    write_lines(os.path.join(SMOKE, "README.md"), [
        "# Committed smoke vectors",
        "",
        "These are six hand-written examples per datapath stage. They are NOT",
        "the regression corpus. Run `python3 model/gen_vectors.py` (or",
        "`make vectors`) to regenerate the full deterministic set into",
        "`vectors/gen/`; that directory is gitignored on purpose.",
        "",
        "Line formats:",
        "- pe_smoke.hex      : `a b p`        (8-bit patterns, 16-bit product)",
        "- requant_smoke.hex : `acc r32 y sat` (32/16/8-bit patterns, 1-bit flag)",
        "",
        "All values are hexadecimal two's-complement bit patterns, so they can",
        "be compared against RTL outputs without signed/unsigned ambiguity.",
    ])

    write_lines(os.path.join(GEN, "manifest.csv"), manifest)
    for row in manifest:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
