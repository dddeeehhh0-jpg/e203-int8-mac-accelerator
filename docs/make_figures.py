#!/usr/bin/env python3
"""Regenerate the three README figures from the ACTUAL repository contents.

    python3 -m pip install Pillow     # optional, figures are committed
    python3 docs/make_figures.py

The earlier planning figures mentioned a C host driver, five testbenches,
`>>` instead of `>>>` and a 4xINT8 output pack. None of those exist in the
code, so the figures were redrawn. Keep this script in sync with rtl/ and tb/.
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

    box(d, 40, 630, 1160, 76, ".github/workflows/ci.yml",
        "ubuntu-latest + iverilog + pyverilog  ->  python3 run_regress.py --strict "
        "(fails if RTL simulation is skipped)", GREEN, GREEN_BG, GREEN)
    footer(d, "Local host ran: model self-test, vectors, golden recomputation, lint, grammar parse. RTL simulation: CI only.")
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
        "q = wrap49( acc * r32 + 2^15 )      y_pre = q >>> 16      (+2^15 avoids a systematic -0.5 LSB bias)",
        RED, RED_BG, tsize=18)
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
        "1 << shamt expresses powers of two only; a runtime scale fits any\n"
        "per-layer value exactly. Cost: one 32x16 multiplier per GROUP,\n"
        "shared by all 8 lanes. Width proof: 2^31 * 2^16 + 2^15 < 2^48.",
        GREY, GREY_BG, tsize=16, ssize=12)

    footer(d, "Contract implemented identically in rtl/mac/requant.v and model/int8_ref.py; 17,459 (acc, r32) pairs are swept.")
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
        "structural lint 0 error; 14/14 files parsed", BLUE, BLUE_BG)
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
        "Author's Windows host: steps 1-4 + iverilog/vvp UNAVAILABLE -> six TBs NOT run locally.\n"
        "CI on ubuntu-latest installs iverilog and runs `python3 run_regress.py --strict`, "
        "which fails if simulation is skipped.\n"
        "No coverage percentage, no formal proof, no gate-level replay in this repository.",
        GREY, GREY_BG, INK, tsize=17, ssize=12)
    footer(d, "No PDK, no PPA numbers, no accuracy claim. Every PASS points at a file produced in that run.")
    im.save(os.path.join(OUT, "fig3_verification.png"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig1()
    fig2()
    fig3()
    print("wrote 3 figures to", OUT)
