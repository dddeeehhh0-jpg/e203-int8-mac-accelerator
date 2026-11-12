#!/usr/bin/env python3
"""Independent scoreboard for the regression.

Two modes:

  python3 model/check_results.py --verify-vectors
      Recompute every golden value in vectors/gen/ FROM THE RAW INPUTS using
      int8_ref, and compare with the stored golden. For the 12-layer case the
      inputs are read back out of soc_mem.hex, so this is a genuinely
      independent path from gen_vectors.py (which wrote the image).

  python3 model/check_results.py
      Read results/dump_*.csv written by the Verilog testbenches and do a
      point-by-point comparison. Reports the FIRST mismatch with its index.

  python3 model/check_results.py --selftest
      Mutation test: inject one wrong value into a synthetic dump and make
      sure the checker actually catches it.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import int8_ref as ref

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "vectors", "gen")
RESULTS = os.path.join(ROOT, "results")


def hex_lines(name: str) -> list[list[str]]:
    path = os.path.join(GEN, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="ascii") as fh:
        return [line.split() for line in fh if line.strip()]


def verify_vectors() -> list[tuple[str, int, str]]:
    """Return (check name, point count, PASS/FAIL text) tuples."""
    out: list[tuple[str, int, str]] = []

    # 1. exhaustive products
    n, bad = 0, 0
    for row in hex_lines("pe_full.hex"):
        a, b, p = (int(v, 16) for v in row)
        # mac_pe returns a signed value; take its low 16 bits.
        want = ref.mac_pe(ref.as_s8(a), ref.as_s8(b)) & 0xFFFF
        if want != p:
            bad += 1
        n += 1
    out.append(("pe_full.hex golden", n, "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 2. adder tree
    n, bad = 0, 0
    for row in hex_lines("array_rand.hex"):
        xp, wp, s = (int(v, 16) for v in row)
        x = ref.unpack_lanes(xp)
        w = ref.unpack_lanes(wp)
        want = ref.mac_array(x, w) & 0xFFFFFFFF
        if want != s:
            bad += 1
        n += 1
    out.append(("array_rand.hex golden", n, "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 3. requant sweep
    n, bad = 0, 0
    for row in hex_lines("requant_scan.hex"):
        acc_bits, r32, y_bits, sat = (int(v, 16) for v in row)
        acc = ref.wrap_signed(acc_bits, 32)
        y, s = ref.requant(acc, r32)
        if (y & 0xFF) != y_bits or int(s) != sat:
            bad += 1
        n += 1
    out.append(("requant_scan.hex golden", n, "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 4. 12-layer golden, recomputed from the memory image (independent path)
    mem = [int(row[0], 16) for row in hex_lines("soc_mem.hex")]
    golden = hex_lines("soc_expect.hex")
    n, bad = 0, 0
    prev_y = 0
    for layer, row in enumerate(golden):
        _, acc_bits, y_bits, sat = (int(v, 16) for v in row)
        x_word = (mem[layer * 5 + 1] << 32) | mem[layer * 5 + 0]
        w_word = (mem[layer * 5 + 3] << 32) | mem[layer * 5 + 2]
        cfg = mem[layer * 5 + 4]
        r32 = (cfg >> 16) & 0xFFFF
        bias = ref.wrap_signed(cfg & 0xFFFF, 16)
        x = ref.unpack_lanes(x_word) if layer == 0 else [ref.as_s8(prev_y)] * 8
        w = ref.unpack_lanes(w_word)
        acc = ref.wrap_signed(ref.mac_array(x, w) + bias, 32)
        y, s = ref.requant(acc, r32)
        if (acc & 0xFFFFFFFF) != acc_bits or (y & 0xFF) != y_bits or int(s) != sat:
            bad += 1
        prev_y = y
        n += 1
    out.append(("soc_expect.hex vs soc_mem.hex", n, "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 5. NICE-style legal sequence golden
    row = hex_lines("nice_expect.hex")[0]
    y_bits, sat, xlo, xhi, wlo, whi, r32, bias_bits = (int(v, 16) for v in row)
    x_word = (xhi << 32) | xlo
    w_word = (whi << 32) | wlo
    acc = ref.wrap_signed(
        ref.mac_array(ref.unpack_lanes(x_word), ref.unpack_lanes(w_word))
        + ref.wrap_signed(bias_bits, 16), 32
    )
    y, s = ref.requant(acc, r32)
    ok = (y & 0xFF) == y_bits and int(s) == sat
    out.append(("nice_expect.hex golden", 1, "PASS" if ok else "FAIL"))

    # 5b. command stream consistency: every rejected command must expect the
    #     error word, and the one legal READ must expect signext(nice_y).
    seq = hex_lines("nice_seq.hex")
    bad = 0
    legal_reads = 0
    for row in seq:
        f, _r1, _r2, err, data = (int(v, 16) for v in row)
        if err:
            if data != 0xDEADBEEF:
                bad += 1
        elif f == 0x06:
            legal_reads += 1
            if data != (y & 0xFFFFFFFF):
                bad += 1
    if len(seq) != 13 or legal_reads != 1:
        bad += 1
    out.append(("nice_seq.hex consistency", len(seq), "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 6. streaming scenario: same model, format/consistency check only
    top_lines = hex_lines("top_seq.hex")
    bad = sum(1 for r in top_lines if len(r) != 13)
    out.append(("top_seq.hex field count", len(top_lines), "PASS" if bad == 0 else f"FAIL ({bad})"))

    # 7. reproducibility: manifest hashes must match the files on disk
    import hashlib
    manifest = os.path.join(GEN, "manifest.csv")
    n, bad = 0, 0
    if os.path.isfile(manifest):
        with open(manifest, newline="", encoding="ascii") as fh:
            for rec in csv.DictReader(fh):
                path = os.path.join(GEN, rec["file"])
                if not os.path.isfile(path):
                    bad += 1
                    continue
                with open(path, "rb") as bf:
                    digest = hashlib.sha256(bf.read()).hexdigest()
                if digest != rec["sha256"]:
                    bad += 1
                n += 1
    out.append(("manifest.csv sha256", n, "PASS" if bad == 0 and n > 0 else "FAIL"))

    return out


def check_one_dump(path: str) -> dict:
    """Compare one RTL dump against its expected word.

    Most dumps are plain equal-width vectors, so ``expected == actual``.

    ``dump_top_stream.csv`` is different: its word packs
    ``{valid, y[7:0], sat}`` into 10 bits. The streaming interface defines
    the payload as don't-care while ``valid == 0`` -- int8_mac_top keeps the
    previous data register instead of spending logic to clear it, and
    tb_top_stream deliberately skips y/sat on those cycles. Comparing the
    held bits would report false failures on idle/stall/reset/drain beats.

    The scoreboard therefore follows the protocol: the valid bit is ALWAYS
    compared, and on valid cycles the FULL 10-bit word is compared. A wrong
    result, a wrong saturation flag or a wrongly asserted valid still fails
    the build. See docs/verification.md section 1.
    """
    is_stream = "top_stream" in os.path.basename(path)
    errors = 0
    first = None
    n = 0
    with open(path, newline="", encoding="ascii") as fh:
        for row in csv.DictReader(fh):
            n += 1
            try:
                exp = int(row["expected"], 16)
                act = int(row["actual"], 16)
            except (KeyError, ValueError):
                errors += 1
                if first is None:
                    first = (n, "bad row", row)
                continue
            if is_stream:
                exp_v = (exp >> 9) & 1
                act_v = (act >> 9) & 1
                ok = (exp_v == act_v) and (exp_v == 0 or exp == act)
            else:
                ok = exp == act
            if not ok:
                errors += 1
                if first is None:
                    first = (n, f"expected={exp:x} actual={act:x}", row)
    return {"name": os.path.basename(path), "points": n, "errors": errors, "first": first}


def check_dumps() -> list[dict]:
    paths = sorted(glob.glob(os.path.join(RESULTS, "dump_*.csv")))
    return [check_one_dump(p) for p in paths]


def selftest() -> bool:
    """A checker that cannot detect a wrong value is worthless."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "dump_selftest.csv")
        with open(p, "w", encoding="ascii", newline="") as fh:
            fh.write("test,index,expected,actual\n")
            fh.write("selftest,0,ff,ff\n")
            fh.write("selftest,1,12,13\n")      # injected mismatch
            fh.write("selftest,2,00,00\n")
        r = check_one_dump(p)
        caught = r["errors"] == 1 and r["first"][0] == 2
        print(f"checker mutation test: {'PASS' if caught else 'FAIL'} "
              f"(errors={r['errors']}, first={r['first'][0] if r['first'] else None})")

        # The streaming rule must tolerate held payload ONLY on idle cycles.
        # Verify it still catches (a) a bad payload on a valid cycle and
        # (b) a wrongly asserted valid bit. Otherwise the relaxation above
        # would be a way to hide a real RTL bug.
        sp = os.path.join(tmp, "dump_top_stream_selftest.csv")
        with open(sp, "w", encoding="ascii", newline="") as fh:
            fh.write("test,index,expected,actual\n")
            fh.write("top_stream,0,000,1fc\n")   # idle: held payload, tolerated
            fh.write("top_stream,1,200,202\n")   # valid: wrong y, must fail
            fh.write("top_stream,2,000,200\n")   # valid bit wrong, must fail
        rs = check_one_dump(sp)
        caught_s = rs["errors"] == 2 and rs["first"][0] == 2
        print(f"streaming protocol mutation test: {'PASS' if caught_s else 'FAIL'} "
              f"(errors={rs['errors']}, first={rs['first'][0] if rs['first'] else None})")
        return caught and caught_s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-vectors", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    rc = 0

    if args.selftest:
        if not selftest():
            rc = 1

    if args.verify_vectors:
        print("== independent golden verification ==")
        for name, n, status in verify_vectors():
            print(f"{status:6s}  {name:34s}  points={n}")
            if not status.startswith("PASS"):
                rc = 1

    if not args.verify_vectors and not args.selftest:
        dumps = check_dumps()
        if not dumps:
            print("SKIP  no results/dump_*.csv found (RTL simulation not run)")
        else:
            print("== RTL dump scoreboard ==")
            for d in dumps:
                status = "PASS" if d["errors"] == 0 else "FAIL"
                line = f"{status:6s}  {d['name']:32s}  points={d['points']}  mismatches={d['errors']}"
                if d["first"]:
                    line += f"  first={d['first'][0]} {d['first'][1]}"
                print(line)
                if d["errors"]:
                    rc = 1

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
