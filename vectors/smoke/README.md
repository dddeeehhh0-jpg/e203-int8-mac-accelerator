# Committed smoke vectors

These are six hand-written examples per datapath stage. They are NOT
the regression corpus. Run `python3 model/gen_vectors.py` (or
`make vectors`) to regenerate the full deterministic set into
`vectors/gen/`; that directory is gitignored on purpose.

Line formats:
- pe_smoke.hex      : `a b p`        (8-bit patterns, 16-bit product)
- requant_smoke.hex : `acc r32 y sat` (32/16/8-bit patterns, 1-bit flag)

All values are hexadecimal two's-complement bit patterns, so they can
be compared against RTL outputs without signed/unsigned ambiguity.
