#!/usr/bin/env python3
"""Evaluate one placed design with independent routability backends."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "install" if (ROOT / "install/dreamplace").is_dir() else ROOT
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from dreamplace.ops.routability_eval import EvaluationRequest, build_evaluator


def parse_key_values(values):
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--option requires KEY=VALUE, got %s" % value)
        key, raw = value.split("=", 1)
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            result[key] = raw
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="append", required=True)
    parser.add_argument("--design-name", required=True)
    parser.add_argument("--lef-input", action="append", default=[])
    parser.add_argument("--def-input", default="")
    parser.add_argument("--verilog-input", default="")
    parser.add_argument("--aux-input", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--option", action="append", default=[])
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    request = EvaluationRequest(
        design_name=args.design_name,
        lef_input=args.lef_input,
        def_input=args.def_input,
        verilog_input=args.verilog_input,
        aux_input=args.aux_input,
        output_dir=str(args.output_dir.resolve()),
        num_threads=args.num_threads,
        timeout_sec=args.timeout_sec,
        options=parse_key_values(args.option),
    )
    results = []
    for item in args.backend:
        for backend in item.split(","):
            backend = backend.strip()
            if not backend:
                continue
            result = build_evaluator(backend).evaluate(request)
            result.write_json(args.output_dir / (backend + ".json"))
            results.append(result.to_dict())
    summary = args.output_dir / "summary.json"
    summary.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n")
    print(summary)
    return 0 if all(result["status"] == "ok" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
