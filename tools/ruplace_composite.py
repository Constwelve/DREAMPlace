#!/usr/bin/env python3
"""
Build a reproducible RUPlace composite benchmark from validated run folders.

The composite keeps all rows from a base full-suite run, then replaces available
rows for selected designs from focused tuning runs. This is useful for paper
tables that report the best per-design RUPlace profile while preserving the
same report and gate logic as tools/ruplace_quality.py.
"""

import argparse
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_PATH = REPO_ROOT / "tools" / "ruplace_quality.py"
SPEC = importlib.util.spec_from_file_location("ruplace_quality", QUALITY_PATH)
ruplace_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ruplace_quality)


def parse_args():
    parser = argparse.ArgumentParser(description="Create a composite RUPlace benchmark run.")
    parser.add_argument("--result-root", type=Path, default=REPO_ROOT / "results" / "ruplace_quality")
    parser.add_argument("--base-run", required=True, help="Base run id to start from.")
    parser.add_argument("--output-run", required=True, help="Composite run id to write.")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help=(
            "Design/run override in design:run_id or design.method:run_id form. "
            "May be repeated. Rows present for that design in the override run replace "
            "base rows by method; design.method limits replacement to one method."
        ),
    )
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--note", default="", help="Optional note copied into composite_notes.txt.")
    return parser.parse_args()


def parse_overrides(items):
    overrides = []
    for item in items:
        if ":" not in item:
            raise ValueError("Bad override '%s'; expected design[:method]:run_id" % item)
        lhs, run_id = item.split(":", 1)
        if "." in lhs:
            design, method = lhs.split(".", 1)
            method = method.strip()
        else:
            design, method = lhs, ""
        design = design.strip()
        run_id = run_id.strip()
        if not design or not run_id:
            raise ValueError("Bad override '%s'; expected design[:method]:run_id" % item)
        overrides.append((design, method, run_id))
    return overrides


def main():
    args = parse_args()
    result_root = args.result_root.resolve()
    base_dir = result_root / args.base_run
    out_dir = result_root / args.output_run
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = ruplace_quality.load_existing_rows(base_dir)
    by_key = {(row["design"], row["method"]): row for row in rows}
    applied = []
    for design, method, run_id in parse_overrides(args.override):
        override_dir = result_root / run_id
        override_rows = [
            row for row in ruplace_quality.load_existing_rows(override_dir)
            if row.get("design") == design and (not method or row.get("method") == method)
        ]
        if not override_rows:
            label = "%s.%s" % (design, method) if method else design
            raise RuntimeError("Override %s:%s has no matching rows" % (label, run_id))
        for row in override_rows:
            by_key[(row["design"], row["method"])] = row
        applied.append(
            "%s <- %s (%s)"
            % (
                "%s.%s" % (design, method) if method else design,
                run_id,
                ",".join(sorted({r["method"] for r in override_rows})),
            )
        )

    rows = [by_key[key] for key in sorted(by_key)]
    gate = ruplace_quality.gate_summary(rows)
    report_args = SimpleNamespace(iterations=args.iterations)
    ruplace_quality.write_csv(out_dir / "raw_metrics.csv", rows)
    (out_dir / "gate_summary.json").write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n"
    )
    ruplace_quality.write_report(out_dir / "report.md", report_args, out_dir, rows, gate)
    ruplace_quality.write_comparison_csv(out_dir / "comparison_summary.csv", rows)

    notes = [
        "base_run: %s" % args.base_run,
        "output_run: %s" % args.output_run,
        "verdict: %s" % ("PASS" if gate["pass"] else "FAIL"),
        "overrides:",
    ]
    notes.extend("  - %s" % item for item in applied)
    if args.note:
        notes.extend(["note:", args.note])
    (out_dir / "composite_notes.txt").write_text("\n".join(notes) + "\n")

    base_launch = base_dir / "launch.sh"
    if base_launch.exists():
        shutil.copy2(base_launch, out_dir / "base_launch.sh")

    print("Wrote %s" % out_dir)
    print("Gate verdict: %s" % ("PASS" if gate["pass"] else "FAIL"))
    print("Applied %d overrides" % len(applied))


if __name__ == "__main__":
    main()
