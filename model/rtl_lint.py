#!/usr/bin/env python3
"""Lightweight structural lint for this repository (stdlib only).

This is NOT a Verilog compiler and does not replace iverilog/Verilator. It
catches the structural mistakes that are easy to make when adding modules:
missing `default_nettype` guards, unbalanced module/generate blocks, a file
whose name does not match its module, and instances of modules that do not
exist anywhere under rtl/.

Run: python3 model/rtl_lint.py
Output: results/lint_report.txt
"""

from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = ["rtl", "tb"]


def strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        # No block comments are used in this repository; strip // comments.
        idx = line.find("//")
        out.append(line[:idx] if idx >= 0 else line)
    return "\n".join(out)


def main() -> int:
    files = sorted(
        p for folder in SRC
        for p in glob.glob(os.path.join(ROOT, folder, "**", "*.v"), recursive=True)
    )
    if not files:
        print("FAIL  no .v files found")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    lines: list[str] = ["# Structural lint report", ""]

    # Collect all defined module names first.
    defined: dict[str, str] = {}
    for path in files:
        text = strip_comments(open(path, encoding="utf-8").read())
        for name in re.findall(r"^\s*module\s+(\w+)", text, re.M):
            if name in defined and not defined[name].endswith(os.path.basename(path)):
                errors.append(f"duplicate module '{name}' in {path} and {defined[name]}")
            defined[name] = path

    inst_re = re.compile(r"\b(" + "|".join(sorted(defined)) + r")\b\s*(?:#\s*\(|\w+\s*\()")

    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        raw = open(path, encoding="utf-8").read()
        text = strip_comments(raw)
        base = os.path.basename(path)[:-2]

        mods = re.findall(r"^\s*module\s+(\w+)", text, re.M)
        n_end = len(re.findall(r"^\s*endmodule\b", text, re.M))
        file_errors = []

        if not mods:
            file_errors.append("no module declaration")
        if n_end != len(mods):
            file_errors.append(f"module/endmodule count {len(mods)}/{n_end}")
        if base not in mods:
            file_errors.append(f"file name '{base}' does not match module(s) {mods}")

        n_none = len(re.findall(r"`default_nettype\s+none", text))
        n_wire = len(re.findall(r"`default_nettype\s+wire", text))
        if n_none != 1 or n_wire != 1:
            file_errors.append(f"default_nettype guards none={n_none} wire={n_wire}")

        n_gen = len(re.findall(r"^\s*generate\b", text, re.M))
        n_egen = len(re.findall(r"^\s*endgenerate\b", text, re.M))
        if n_gen != n_egen:
            file_errors.append(f"generate/endgenerate count {n_gen}/{n_egen}")

        # Bracket balance (paren / square) on comment-free text.
        for op, cl in (("(", ")"), ("[", "]")):
            if text.count(op) != text.count(cl):
                file_errors.append(f"unbalanced {op}{cl}: {text.count(op)}/{text.count(cl)}")

        # Every instantiated module must be defined.
        for m in inst_re.finditer(text):
            prefix = text[max(0, m.start() - 10):m.start()]
            if re.search(r"\bmodule\s+$", prefix):
                continue  # this is the declaration itself
            inst_name = m.group(1)
            if inst_name not in defined:
                file_errors.append(f"instance of undefined module '{inst_name}'")

        if file_errors:
            errors.extend(f"{rel}: {e}" for e in file_errors)
            lines.append(f"[FAIL] {rel}")
            for e in file_errors:
                lines.append(f"       - {e}")
        else:
            lines.append(f"[ OK ] {rel}  module(s): {', '.join(mods)}")

    lines += [
        "",
        f"files   : {len(files)}",
        f"modules : {len(defined)}",
        f"errors  : {len(errors)}",
        f"warnings: {len(warnings)}",
        "",
        "Note: structural only. A real compile/simulation is performed by",
        "`python3 run_regress.py` / `make regress` when iverilog is present,",
        "and unconditionally by the GitHub Actions CI job on ubuntu-latest.",
    ]

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    out_path = os.path.join(ROOT, "results", "lint_report.txt")
    with open(out_path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
