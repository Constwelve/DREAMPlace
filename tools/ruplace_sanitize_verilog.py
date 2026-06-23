#!/usr/bin/env python3
"""Flatten internal Verilog bus wires for DREAMPlace's simple Verilog reader.

Cadence Genus can emit internal declarations such as `wire [15:0] foo;` and
instance pins like `foo[3]`. DREAMPlace accepts scalar net declarations but its
LEF/DEF Verilog callback rejects multi-bit internal net declarations. This
script leaves module port buses intact and rewrites only internal wire buses to
escaped scalar names (`\\foo[3]`).
"""

import argparse
import re
from pathlib import Path

DECL_RE = re.compile(r"^(\s*)(wire|input|output|inout)\s*\[(\d+)\s*:\s*(\d+)\]\s*(.*?)\s*;\s*$")
PORT_RE = re.compile(r"^\s*(input|output|inout)\s*(?:\[[^]]+\]\s*)?(.*?)\s*;\s*$")
NAME_RE = re.compile(r"[A-Za-z_\\][A-Za-z0-9_$\\]*(?:\[[^\]]+\])?")


def split_names(text):
    return [name.strip() for name in text.split(',') if name.strip()]


def is_simple_identifier(name):
    return name and not name.startswith('\\') and '[' not in name and ']' not in name


def is_declarable_identifier(name):
    return is_simple_identifier(name) or (name.startswith('\\') and not any(ch.isspace() for ch in name))


def safe_escaped_identifier(name):
    name = name[1:] if name.startswith("\\") else name
    return re.sub(r"[^A-Za-z0-9_$]", "_", name)


def sanitize(src, style="xplace"):
    port_bits = {}
    for line in src.splitlines():
        match = PORT_RE.match(line)
        if not match:
            continue
        range_match = re.search(r"\[(\d+)\s*:\s*(\d+)\]", line)
        if not range_match:
            continue
        hi = int(range_match.group(1))
        lo = int(range_match.group(2))
        step = 1 if hi >= lo else -1
        bits = list(range(lo, hi + step, step) if step == 1 else range(lo, hi - 1, step))
        for name in split_names(match.group(2)):
            if is_simple_identifier(name):
                port_bits[name] = bits

    replacements_by_base = {}
    module_port_replacements = {}
    out_lines = []
    for line in src.splitlines():
        if style == "dreamplace" and re.match(r"^\s*assign\s+", line):
            continue
        match = DECL_RE.match(line)
        if not match:
            out_lines.append(line)
            continue
        indent, keyword, hi_text, lo_text, names_text = match.groups()
        names = split_names(names_text)
        if not names or not all(is_declarable_identifier(name) for name in names):
            out_lines.append(line)
            continue
        hi = int(hi_text)
        lo = int(lo_text)
        step = 1 if hi >= lo else -1
        bits = range(lo, hi + step, step) if step == 1 else range(lo, hi - 1, step)
        scalar_names = []
        for name in names:
            escaped_base = safe_escaped_identifier(name) if name.startswith("\\") else name
            for bit in bits:
                if style == "dreamplace":
                    new = f"{escaped_base}[{bit}]"
                else:
                    new = f"\\{escaped_base}[{bit}] "
                replacements_by_base.setdefault(name, {})[str(bit)] = new
                scalar_names.append(new)
            if name in port_bits:
                if style == "dreamplace":
                    module_port_replacements[name] = ", ".join(
                        f"{name}[{bit}]" for bit in port_bits[name]
                    )
                else:
                    module_port_replacements[name] = ", ".join(
                        f"\\{name}[{bit}] " for bit in port_bits[name]
                    )
        out_lines.append(f"{indent}{keyword} {', '.join(scalar_names)};")
    text = "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")

    module_match = re.search(r"\bmodule\b.*?\);", text, flags=re.S)
    if module_match and module_port_replacements:
        header = module_match.group(0)
        for name, expanded in module_port_replacements.items():
            header = re.sub(
                rf"(?<![A-Za-z0-9_$\\]){re.escape(name)}(?![A-Za-z0-9_$])",
                lambda _match, expanded=expanded: expanded,
                header,
            )
        text = text[: module_match.start()] + header + text[module_match.end() :]

    if replacements_by_base:
        # Replace bus-bit uses in one pass. Large TaiWei netlists can contain
        # tens of thousands of bits, so repeated full-file str.replace calls
        # become prohibitively slow.
        base_names = sorted(
            replacements_by_base,
            key=len,
            reverse=True,
        )
        bus_use_re = re.compile(
            r"(?<![A-Za-z0-9_$\\])("
            + "|".join(re.escape(name) for name in base_names)
            + r")\s*\[(\d+)\]"
        )

        def replace_bus_use(match):
            return replacements_by_base.get(match.group(1), {}).get(
                match.group(2), match.group(0)
            )

        text = bus_use_re.sub(replace_bus_use, text)

    if style == "dreamplace":
        def replace_escaped_token(match):
            token = match.group(1)
            port_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_$]*)\[(\d+)\]", token)
            if port_match and port_match.group(1) in port_bits:
                return f"{port_match.group(1)}[{port_match.group(2)}]"
            return safe_escaped_identifier(token)

        text = re.sub(r"\\([^\s,;()]+)", replace_escaped_token, text)
    else:
        # Xplace expects escaped bus-bit tokens and explicit escaped-name
        # termination before punctuation or end-of-line.
        text = re.sub(r"(\\[^\s,;()]+)(?=([,;()]))", r"\1 ", text)
        text = re.sub(r"(\\[^\s,;()]+)(?=\n)", r"\1 ", text)
        while "\\\\" in text:
            text = text.replace("\\\\", "\\")
    return text, sum(len(bits) for bits in replacements_by_base.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--style",
        choices=["xplace", "dreamplace"],
        default="xplace",
        help="xplace keeps escaped scalar bus names; dreamplace uses parser-friendly safe names.",
    )
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    text, count = sanitize(args.input.read_text(), style=args.style)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"wrote {args.output} with {count} scalarized bus bits")


if __name__ == '__main__':
    main()
