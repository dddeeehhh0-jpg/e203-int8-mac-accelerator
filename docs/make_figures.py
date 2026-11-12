#!/usr/bin/env python3
"""Regenerate the five README/docs figures from the ACTUAL repository contents.

    python3 -m pip install Pillow     # optional, figures are committed
    python3 docs/make_figures.py

Keep this script in sync with rtl/, tb/, syn/ and model/. Earlier planning
figures mentioned a C host driver, five testbenches, `>>` instead of `>>>`
and a 4xINT8 output pack; none of those exist in the code, so they were
redrawn. fig4 is plotted from the REAL stimulus in vectors/gen/top_seq.hex
rather than from a hand-drawn approximation.
"""

from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")

W, H = 1240, 780
BG = "#ffffff"
INK = "#1f2937"
MUTED = "#64748b"
BLUE = "#1f4e79"
BLUE_BG = "#eef4fb"
RED = "#c0392b"
RED_BG = "#fdf1ef"
GREEN = "#1e7d5a"
GREEN_BG = "#eef8f3"
GREY = "#94a3b8"
GREY_BG = "#f6f8fa"


def font(size: int, bold: bool = False, mono: bool = False):
    if mono:
        path = "C:/Windows/Fonts/consola.ttf"
    elif bold:
        path = "C:/Windows/Fonts/arialbd.ttf"
    else:
        path = "C:/Windows/Fonts/segoeui.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def center(d, cx, y, text, f, color=INK):
    bbox = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bbox[2] - bbox[0]) / 2, y), text, font=f, fill=color)


def box(d, x, y, w, h, title, sub="", outline=BLUE, fill=BLUE_BG,
        tcolor=INK, tsize=17, ssize=13):
    d.rounded_rectangle([x, y, x + w, y + h], radius=10,
                        fill=fill, outline=outline, width=2)
    ft = font(tsize, bold=True)
    fs = font(ssize)
    lines = sub.split("\n") if sub else []
    total = 24 + (18 * len(lines))
    top = y + (h - total) / 2
    center(d, x + w / 2, top, title, ft, tcolor)
    for i, line in enumerate(lines):
        center(d, x + w / 2, top + 26 + 18 * i, line, fs, MUTED)


def arrow(d, x1, y1, x2, y2, color=GREY, width=2):
    d.line([x1, y1, x2, y2], fill=color, width=width)
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 9
    p1 = (x2 - L * math.cos(ang - 0.45), y2 - L * math.sin(ang - 0.45))
    p2 = (x2 - L * math.cos(ang + 0.45), y2 - L * math.sin(ang + 0.45))
    d.polygon([(x2, y2), p1, p2], fill=color)


def header(d, title, sub):
    center(d, W / 2, 22, title, font(28, bold=True))
    center(d, W / 2, 60, sub, font(14), MUTED)
    d.line([40, 92, W - 40, 92], fill="#e2e8f0", width=2)


def footer(d, text):
    center(d, W / 2, H - 26, text, font(13), MUTED)


def fig1():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "Clean-room INT8 MAC accelerator - module map",
           "Independent rewrite. E203 core, official NICE RTL, PDK, netlist, dataset and contest source are NOT included.")

    box(d, 40, 112, 270, 132, "model/",
        "int8_ref.py    bit-exact contract\ngen_vectors.py  SEED 20261112\ncheck_results.py scoreboard + lint helpers")
    box(d, 40, 262, 270, 82, "vectors/gen/",
        "8 deterministic files + sha256 manifest\n(gitignored, reproducible)", GREY, GREY_BG)
    box(d, 40, 362, 270, 82, "vectors/smoke/",
        "12 committed hand-written examples", GREY, GREY_BG)

    box(d, 350, 112, 290, 132, "tb/  -  6 self-checking TBs",
        "mac_pe | mac_array | requant\ntop_stream | nice_adapter | soc_stub")
    box(d, 350, 262, 290, 82, "iverilog -g2012 + vvp",
        "elaborate + simulate (runs in CI)", GREEN, GREEN_BG)
    box(d, 350, 362, 290, 82, "results/dump_*.csv",
        "point-by-point RTL vs golden", GREEN, GREEN_BG)
    box(d, 350, 462, 290, 82, "check_results.py",
        "independent scoreboard + mutation test", GREEN, GREEN_BG)

    box(d, 690, 112, 510, 76, "rtl/soc_stub/mac_soc_stub.v",
        "host FSM: 12-layer recurrence, 5-word/layer memory image", GREY, GREY_BG)
    box(d, 690, 200, 245, 76, "rtl/memory/sram_beh.v",
        "behavioural single-port SRAM", GREY, GREY_BG)
    box(d, 955, 200, 245, 76, "rtl/top/nice_adapter.v",
        "NICE-STYLE, custom funct7\nNOT official NICE", GREY, GREY_BG)
    box(d, 690, 288, 510, 76, "rtl/top/int8_mac_top.v",
        "streaming cfg / s_ / m_ handshake, single-slot output buffer")
    box(d, 690, 376, 510, 168, "rtl/mac/  -  shared arithmetic",
        "mac_array.v   8 x mac_pe.v, explicit 3-level adder tree\n"
        "acc_stage.v   INT32 accumulate, clear = restart from din\n"
        "requant.v     q = acc*r32 + 2^15 ;  y_pre = q >>> 16\n"
        "y = clip(y_pre, -128, 127)   (saturate ONCE)", RED, RED_BG)
    box(d, 690, 556, 510, 52, "nice_adapter taps requant y_comb / sat_comb",
        "the formula exists exactly once in the RTL", GREY, GREY_BG, ssize=12)

    arrow(d, 310, 180, 345, 180, BLUE)
    arrow(d, 310, 300, 345, 300, GREEN)
    arrow(d, 640, 180, 685, 180, GREY)
    arrow(d, 640, 300, 685, 405, GREY)
    arrow(d, 495, 244, 495, 258, GREEN)
    arrow(d, 495, 344, 495, 358, GREEN)
    arrow(d, 495, 444, 495, 458, GREEN)

    box(d, 40, 630, 1160, 84, ".github/workflows/ci.yml  -  3 mandatory steps",
        "ubuntu-latest: Icarus Verilog 12.0 + Yosys 0.70 + pyverilog\n"
        "run_regress.py --strict  ->  syn/run_synth.py --strict  ->  run_gatelevel.py --strict\n"
        "(RTL simulation skipped, synthesis missing, or gate-level replay skipped => CI FAILS)",
        GREEN, GREEN_BG, GREEN, tsize=16, ssize=12)
    footer(d, "This host: model/vectors/golden/lint/grammar/Yosys synthesis. RTL simulation + gate-level replay: CI only.")
    im.save(os.path.join(OUT, "fig1_architecture.png"))


def fig2():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "INT8 MAC dataflow and fixed-point contract",
           "One group = N beats of 8 lane pairs. One signed INT8 result per group. No 4x packing, no intermediate saturation.")

    step = 143
    for i in range(8):
        x = 40 + i * step
        box(d, x, 122, 128, 62, f"x{i} * w{i}", "INT8 x INT8", BLUE, BLUE_BG, tsize=14, ssize=11)
        arrow(d, x + 64, 184, x + 64, 216, GREY)

    box(d, 40, 220, 1144, 66, "mac_array.v  -  balanced 3-level adder tree over 8 exact 16-bit products",
        "worst |sum| = 8 * 16384 = 131072  <  2^18", tsize=17)
    arrow(d, 612, 286, 612, 314, GREY)

    box(d, 40, 318, 1144, 66, "acc_stage.v  -  signed INT32 running sum",
        "bias is folded into din on the FIRST beat of a group; clear means restart-from-din, enabling back-to-back groups", tsize=17)
    arrow(d, 612, 384, 612, 412, GREY)

    box(d, 40, 416, 1144, 92, "requant.v  -  round-to-nearest, arithmetic shift",
        "q = wrap49( acc * r32 + 2^15 )      y_pre = q >>> 16\n"
        "floor(x+0.5): |e| <= 0.5 LSB, ties go toward +infinity (NOT round-half-even)",
        RED, RED_BG, tsize=18, ssize=12)
    arrow(d, 612, 508, 612, 536, GREY)

    box(d, 40, 540, 1144, 66, "sat8 -> m_y",
        "y = clip(y_pre, -128, 127)   |   sat_flag reports clipping   |   saturate ONCE, at the output",
        GREEN, GREEN_BG, tsize=18)

    box(d, 40, 626, 540, 118, "Bit widths",
        "x, w : 8-bit signed       lane product : 16-bit signed\n"
        "acc, bias : 32-bit signed (bias is 16-bit, sign-extended)\n"
        "r32 : 16-bit unsigned     q : 49-bit signed     y : 8-bit signed",
        GREY, GREY_BG, tsize=16, ssize=12)
    box(d, 600, 626, 584, 118, "Why r32, not a shift amount?",
        "1 << shamt expresses powers of two only; a 16-bit multiplier\n"
        "approximates an arbitrary per-layer scale to ~16 bits.\n"
        "Cost: one 32x16 multiply per GROUP (largest block, ~3.9k cells).\n"
        "Width proof: 2^31 * 2^16 + 2^15 < 2^48.",
        GREY, GREY_BG, tsize=16, ssize=12)

    footer(d, "Same contract in rtl/mac/requant.v and model/int8_ref.py; 17,459 (acc, r32) pairs swept. Bias analysis: docs/quantization_error_analysis.md")
    im.save(os.path.join(OUT, "fig2_dataflow.png"))


def fig3():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "Verification chain - one number, one evidence file",
           "Golden values are produced by the Python model; a testbench never recomputes its own golden value.")

    box(d, 40, 112, 250, 88, "1  int8_ref.py",
        "8 exhaustive / boundary self-checks", BLUE, BLUE_BG)
    box(d, 330, 112, 250, 88, "2  gen_vectors.py",
        "8 files, SEED 20261112, sha256 manifest", BLUE, BLUE_BG)
    box(d, 620, 112, 250, 88, "3  golden recompute",
        "reads soc_mem.hex back, re-derives all 12 layers", BLUE, BLUE_BG)
    box(d, 910, 112, 290, 88, "4  rtl_lint + grammar",
        "structural lint 0 error; 15/15 files parsed", BLUE, BLUE_BG)
    arrow(d, 290, 156, 325, 156, BLUE)
    arrow(d, 580, 156, 615, 156, BLUE)
    arrow(d, 870, 156, 905, 156, BLUE)

    labels = [
        ("tb_mac_pe.v", "all 256x256 signed products", "65,536"),
        ("tb_mac_array.v", "5,000 random + 4 extreme groups", "5,004"),
        ("tb_requant.v", "r32 0..1024 x 17 acc boundaries", "17,459"),
        ("tb_top_stream.v", "cfg / back-to-back / stall / reset", "24 cycles"),
        ("tb_nice_adapter.v", "legal + 5 illegal sequence classes", "13 commands"),
        ("tb_soc_stub.v", "12 layers + write-back memory check", "12 layers"),
    ]
    for i, (name, sub, pts) in enumerate(labels):
        col, row = i % 3, i // 3
        x = 40 + col * 400
        y = 240 + row * 128
        outline = RED if name == "tb_requant.v" else BLUE
        fill = RED_BG if name == "tb_requant.v" else BLUE_BG
        box(d, x, y, 380, 104, name, sub, outline, fill, tsize=16, ssize=12)
        d.rounded_rectangle([x + 300, y + 12, x + 372, y + 34], radius=8,
                            fill="#ffffff", outline=outline, width=1)
        center(d, x + 336, y + 15, pts, font(11, bold=True), outline)

    arrow(d, 1055, 200, 1055, 220, GREEN)
    box(d, 40, 510, 1160, 88, "results/dump_*.csv  ->  check_results.py  ->  results/regression_summary.md",
        "independent scoreboard reports the FIRST mismatch with its index; the checker itself is mutation-tested",
        GREEN, GREEN_BG, GREEN, tsize=18)

    box(d, 40, 618, 1160, 92, "Honest execution status",
        "This host (Windows): steps 1-4 + Yosys synthesis; iverilog unavailable -> RTL simulation SKIPPED here.\n"
        "CI (ubuntu-latest, Icarus 12.0 + Yosys 0.70): 6 TBs, 6 synthesised tops, 5 netlists replayed, all --strict.\n"
        "Evidence: results/ci_evidence.md, regression_summary.md, synthesis_report.md, gatelevel_report.md.\n"
        "No coverage %, no formal proof, no PDK PPA. Gate-level = equivalence on THIS vector set only.",
        GREY, GREY_BG, INK, tsize=17, ssize=12)
    footer(d, "No PDK, no PPA numbers, no accuracy claim. Every PASS points at a file produced in that run.")
    im.save(os.path.join(OUT, "fig3_verification.png"))


def fig4():
    """Waveform plotted from the REAL stimulus, not a hand-drawn guess.

    Columns of vectors/gen/top_seq.hex:
      0 rst_n | 1 cfg_valid | 2 r32 | 3 bias | 4 s_valid | 5 x | 6 w
      7 s_last | 8 m_ready | 9 exp m_valid | 10 exp m_y | 11 exp m_sat
      12 exp s_ready
    """
    W4, H4 = 1400, 900
    im = Image.new("RGB", (W4, H4), BG)
    d = ImageDraw.Draw(im)
    center(d, W4 / 2, 18, "Streaming ready/valid waveform (24 real stimulus beats)",
           font(27, bold=True))
    center(d, W4 / 2, 56, "Plotted directly from vectors/gen/top_seq.hex; "
           "m_valid / m_y / s_ready are the bit-exact model's expected values, "
           "confirmed by tb_top_stream in CI.", font(13), MUTED)

    path = os.path.join(ROOT, "vectors", "gen", "top_seq.hex")
    with open(path, encoding="ascii") as fh:
        rows = [l.split() for l in fh if l.strip()]
    n = len(rows)
    col = lambda i: [int(r[i], 16) if len(r[i]) > 1 else int(r[i], 16)
                     for r in rows]

    rst = [int(r[0], 16) for r in rows]
    cfg = [int(r[1], 16) for r in rows]
    sv = [int(r[4], 16) for r in rows]
    sl = [int(r[7], 16) for r in rows]
    mr = [int(r[8], 16) for r in rows]
    mv = [int(r[9], 16) for r in rows]
    ys = [int(r[10], 16) for r in rows]
    sat = [int(r[11], 16) for r in rows]
    sr = [int(r[12], 16) for r in rows]
    stall = [1 if (mv[t] and not mr[t]) else 0 for t in range(n)]

    X0, BW = 200, 48
    x_end = X0 + n * BW

    # Region bands (indices into top_seq.hex).
    regions = [
        (0, 0, "reset", "#f3f4f6"),
        (1, 1, "config", "#eef4fb"),
        (2, 7, "groups A/B/C", "#eef8f3"),
        (8, 10, "BKP m_ready=0", "#fdf1ef"),
        (11, 11, "drain", "#f6f8fa"),
        (12, 13, "cfg+D", "#eef4fb"),
        (14, 14, "reset", "#f3f4f6"),
        (15, 16, "cfg+E", "#eef8f3"),
        (17, n - 1, "idle", "#f6f8fa"),
    ]
    for a, b, label, fill in regions:
        d.rectangle([X0 + a * BW, 92, X0 + (b + 1) * BW, 116], fill=fill)
        center(d, X0 + (a + b + 1) * BW / 2, 95, label,
               font(10, bold=True), MUTED)
    for t in range(n + 1):
        x = X0 + t * BW
        d.line([x, 92, x, 690], fill="#eef1f5", width=1)

    def bit_row(y, label, bits, color=INK):
        hi, lo = y + 6, y + 30
        d.text((24, y + 8), label, font=font(13, mono=True), fill=MUTED)
        for t, b in enumerate(bits):
            x1, x2 = X0 + t * BW, X0 + (t + 1) * BW
            yy = hi if b else lo
            d.line([x1, yy, x2, yy], fill=color, width=2)
            if t and b != bits[t - 1]:
                d.line([x1, hi if bits[t - 1] else lo, x1, yy],
                       fill=color, width=2)
        d.line([X0, lo, x_end, lo], fill="#e2e8f0", width=1)

    # clock: one full pulse per beat.
    yclk = 128
    d.text((24, yclk + 8), "clk", font=font(13, mono=True), fill=MUTED)
    for t in range(n):
        x1, xm, x2 = X0 + t * BW, X0 + t * BW + BW / 2, X0 + (t + 1) * BW
        d.line([x1, yclk + 6, xm, yclk + 6, xm, yclk + 30, x2, yclk + 30],
               fill=INK, width=2)

    rows_spec = [
        (180, "rst_n", rst, BLUE),
        (226, "cfg_valid", cfg, BLUE),
        (272, "s_valid", sv, GREEN),
        (318, "s_last", sl, GREEN),
        (364, "m_ready", mr, RED),
        (410, "m_valid", mv, RED),
        (456, "s_ready", sr, GREEN),
        (502, "stall", stall, RED),
    ]
    for y, name, bits, c in rows_spec:
        bit_row(y, name, bits, c)

    # bus row for m_y
    y = 548
    d.text((24, y + 8), "m_y / INT8", font=font(13, mono=True), fill=MUTED)
    for t in range(n):
        x1, x2 = X0 + t * BW, X0 + (t + 1) * BW
        d.rectangle([x1 + 2, y + 2, x2 - 2, y + 32],
                    fill=("#fdf1ef" if sat[t] else "#eef8f3") if mv[t]
                    else "#f6f8fa", outline="#e2e8f0", width=1)
        if mv[t]:
            val = ys[t] - 256 if ys[t] >= 128 else ys[t]
            txt = f"{val:+d}" + ("!" if sat[t] else "")
            center(d, (x1 + x2) / 2, y + 8, txt, font(12, bold=True, mono=True),
                   RED if sat[t] else GREEN)
        else:
            center(d, (x1 + x2) / 2, y + 9, "held", font(11), GREY)
    center(d, W4 / 2, 594,
           "m_valid=0  ->  payload is a protocol DON'T-CARE (held data register); "
           "the scoreboard compares only the valid bit on those cycles",
           font(13), MUTED)

    # cycle indices
    for t in range(n):
        center(d, X0 + (t + 0.5) * BW, 626, f"t{t}", font(10, mono=True), MUTED)

    box(d, 40, 662, 640, 106, "What the waveform proves",
        "1 result/cycle while m_ready=1 (t5 back-to-back group)\n"
        "3 stalled beats freeze s_ready and hold m_valid + payload\n"
        "cfg_valid inserts exactly one bubble (s_ready=0)\n"
        "mid-stream reset (t14) leaves no stuck valid", GREY, GREY_BG, tsize=15, ssize=11)
    box(d, 700, 662, 660, 106, "What it does NOT prove",
        "No Fmax / clock period / timing closure\n"
        "No formal handshake proof (structural argument + simulation only)\n"
        "No CDC and no reset de-assertion synchroniser\n"
        "See docs/timing_handshake.md section 7", GREY, GREY_BG, tsize=15, ssize=11)
    center(d, W4 / 2, H4 - 26,
           "Stimulus: model/gen_vectors.py::build_stream_scenario (24 beats). "
           "Regenerate with: python3 docs/make_figures.py", font(12), MUTED)
    im.save(os.path.join(OUT, "fig4_stream_waveform.png"))


def fig5():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    header(d, "Synthesis and gate-level replay - the evidence chain",
           "Real Yosys mapping with NO PDK; the netlist is simulated with the SAME testbench and an independent scoreboard.")

    box(d, 40, 112, 260, 92, "RTL (6 synthesizable tops)",
        "mac_pe / mac_array / acc_stage\nrequant / top / nice_adapter", BLUE, BLUE_BG)
    box(d, 340, 112, 260, 92, "Yosys 0.70 (pinned)",
        "proc / techmap / flatten /\nsetundef / check / stat", BLUE, BLUE_BG)
    box(d, 640, 112, 260, 92, "6 flattened netlists",
        "one module per DUT,\nports intact, sha256 manifest", BLUE, BLUE_BG)
    box(d, 940, 112, 260, 92, "results/synthesis_report.md",
        "cell counts, 0 latches,\nsource + netlist hashes", BLUE, BLUE_BG)
    for x in (300, 600, 900):
        arrow(d, x, 158, x + 35, 158, BLUE)

    box(d, 40, 246, 360, 92, "syn/generic_cells.v",
        "hand-written zero-delay behavioural\nmodels of every generic primitive", GREY, GREY_BG)
    box(d, 440, 246, 360, 92, "TB copy, params validated then stripped",
        "a structural netlist has no parameters;\noverride values checked against synthesis", GREY, GREY_BG)
    box(d, 840, 246, 360, 92, "iverilog -g2012 + vvp",
        "compile netlist + primitives + TB\nrun in an isolated directory", GREEN, GREEN_BG)
    arrow(d, 400, 292, 435, 292, GREY)
    arrow(d, 800, 292, 835, 292, GREY)
    arrow(d, 1020, 204, 1020, 242, GREEN)

    box(d, 40, 372, 1160, 92, "FIVE mandatory checks per netlist (RTL ref + gate run on the SAME vectors)",
        "(1) RTL RESULT PASS  (2) gate RESULT PASS  (3) RTL dump scoreboard  "
        "(4) gate dump scoreboard  (5) the two ACTUAL columns equal bit-exactly\n"
        "5 netlists replayed; only tb_requant uses a 204-point boundary subset "
        "(17,459 zero-delay gate points exceeded 300 s in CI).\n"
        "The other 4 netlists keep their FULL vectors; the complete 17,459-point "
        "requant sweep stays in the RTL regression. tb_soc_stub is behavioural only.",
        GREEN, GREEN_BG, GREEN, tsize=16, ssize=11)

    box(d, 40, 490, 1160, 76, "results/gatelevel_report.md  +  results/gl_dump_*.csv  +  CI artifacts",
        "Authoritative copies are produced on ubuntu-latest; this host's snapshot is SKIPPED and labelled as not authoritative.",
        GREEN, GREEN_BG, GREEN, tsize=16, ssize=12)

    box(d, 40, 592, 1160, 120, "HARD SCOPE - do not overclaim",
        "Generic cells only: NO PDK, NO um^2, NO Fmax, NO power, NO timing closure, NO SDC/corners.\n"
        "Functional equivalence on THIS vector set under a ZERO-DELAY primitive model - NOT formal equivalence.\n"
        "Cell counts are relative complexity indicators for THIS clean-room demo, never the contest chip's PPA.\n"
        "CI: run_regress.py --strict -> syn/run_synth.py --strict -> run_gatelevel.py --strict.",
        GREY, GREY_BG, INK, tsize=16, ssize=12)
    footer(d, "Three CI failures were fixed from real logs: scoreboard protocol (a8639b0), flattened netlists / parameter overrides (b493b32), gate-replay cost (this commit).")
    im.save(os.path.join(OUT, "fig5_synthesis_gatelevel.png"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
    print("wrote 5 figures to", OUT)
