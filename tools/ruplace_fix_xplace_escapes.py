#!/usr/bin/env python3
"""Normalize escaped Verilog identifiers for Xplace on very large netlists.

Genus can emit escaped scalar bus-bit names immediately followed by a comma,
semicolon, parenthesis, or newline. Xplace's Verilog parser expects escaped
identifiers to be whitespace-terminated. This streaming fixer avoids the full
in-memory bus scalarization path used by ruplace_sanitize_verilog.py, which is
too slow for hundred-MB TaiWei 2D netlists.
"""

import argparse
import re
from pathlib import Path


BEFORE_DELIM_RE = re.compile(r"(\\[^\s,;()]+)(?=([,;()]))")
BEFORE_EOL_RE = re.compile(r"(\\[^\s,;()]+)(?=\n?$)")


def fix_line(line):
    line = BEFORE_DELIM_RE.sub(r"\1 ", line)
    line = BEFORE_EOL_RE.sub(r"\1 ", line)
    while "\\\\" in line:
        line = line.replace("\\\\", "\\")
    return line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open("r", errors="ignore") as src, args.output.open("w") as dst:
        for line in src:
            dst.write(fix_line(line))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
