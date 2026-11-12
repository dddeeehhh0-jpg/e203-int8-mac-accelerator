#!/usr/bin/env python3
"""Optional real grammar check for every .v file, using pyverilog.

This does NOT replace a simulator. It parses each source file with a real
Verilog-2001 grammar (LALR), which catches syntax errors on hosts where
iverilog is unavailable. It is deliberately OPTIONAL:

  - if pyverilog is not installed -> exits 0 and prints SKIP
  - if installed -> every file must parse, otherwise exit 1

pyverilog's bundled preprocessor shells out to `iverilog -E`, which may not
exist here. We feed it already-stripped text (compiler directives removed,
line count preserved) so the grammar check stays pure Python.

Install:  python3 -m pip install pyverilog
Run:      python3 model/verilog_parse_check.py
Output:   results/parse_report.txt
"""

from __future__ import annotations

import glob
import io
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        from pyverilog.vparser.parser import VerilogCodeParser
    except ImportError:
        print("SKIP  pyverilog not installed (optional grammar check); "
              "install with `python3 -m pip install pyverilog`")
        return 0

    files = sorted(
        p for folder in ("rtl", "tb", "syn")
        for p in glob.glob(os.path.join(ROOT, folder, "**", "*.v"), recursive=True)
        # syn/out holds generated netlists (build products), not sources.
        if os.sep + "out" + os.sep not in p
    )
    lines = ["# Verilog grammar check (pyverilog, Verilog-2001 subset)", ""]

    # PLY writes its LALR tables (parser.out / parsetab.py) next to the
    # process cwd by default. Redirect them to a throwaway directory so a
    # grammar check never dirties the repository.
    ply_dir = tempfile.mkdtemp(prefix="pyverilog_ply_")

    try:
        return _parse_all(files, lines, ply_dir)
    finally:
        shutil.rmtree(ply_dir, ignore_errors=True)


def _parse_all(files, lines, ply_dir):
    from pyverilog.vparser.parser import VerilogCodeParser
    failures = 0

    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        source = io.open(path, encoding="utf-8").read().splitlines()
        # Keep blank lines where directives were, so reported line numbers
        # still match the original source file.
        stripped = "\n".join(
            "" if line.lstrip().startswith("`") else line for line in source
        )
        parser = VerilogCodeParser([path], debug=False, outputdir=ply_dir)
        parser.preprocess = lambda t=stripped: t
        try:
            parser.parse()
            lines.append(f"[ OK ] {rel}")
        except Exception as exc:
            failures += 1
            m = re.search(r"line:(\d+)", str(exc))
            n = int(m.group(1)) if m else 0
            context = source[n - 1].strip() if 0 < n <= len(source) else ""
            lines.append(f"[FAIL] {rel}: {exc}")
            if context:
                lines.append(f"       line {n}: {context}")

    lines += [
        "",
        f"files   : {len(files)}",
        f"failures: {failures}",
        "",
        "Scope: grammar only. Elaboration, width rules and simulation are",
        "checked by iverilog/vvp in `make regress` / CI.",
    ]
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    out = os.path.join(ROOT, "results", "parse_report.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
