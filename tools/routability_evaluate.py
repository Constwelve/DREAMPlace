#!/usr/bin/env python3
"""Evaluate one placed design with independent routability backends."""

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON_ROOT = (
    ROOT / "install" if (ROOT / "install/dreamplace").is_dir() else ROOT
)
PYTHON_ROOT = Path(
    os.environ.get("DREAMPLACE_EVALUATOR_PYTHON_ROOT", DEFAULT_PYTHON_ROOT)
).resolve()
if not (PYTHON_ROOT / "dreamplace").is_dir():
    raise RuntimeError(
        "DREAMPlace evaluator Python root has no dreamplace package: %s"
        % PYTHON_ROOT
    )
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from dreamplace.ops.routability_eval import EvaluationRequest, build_evaluator


def file_provenance(path):
    """Record one evaluator input without assuming that it exists."""
    if not path:
        return {"path": "", "sha256": "", "size_bytes": 0}
    origin = Path(path).resolve()
    return {
        "path": str(origin),
        "sha256": (
            hashlib.sha256(origin.read_bytes()).hexdigest()
            if origin.is_file() else ""
        ),
        "size_bytes": origin.stat().st_size if origin.is_file() else 0,
    }


def gpugr_extension_provenance():
    """Identify the native GPUGR extension selected for this Python ABI."""
    try:
        from dreamplace.ops.gpugr.gpugr_backend import BundledGPUGRBackend

        root = Path(BundledGPUGRBackend.resolve_bundle_root()).resolve()
        cpybin = root / "cpp_to_py/cpybin"
        spec = importlib.machinery.PathFinder.find_spec("gpugr", [str(cpybin)])
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        if not origin or not origin.is_file():
            raise RuntimeError("Python import machinery found no GPUGR extension")
        return {
            "status": "resolved",
            "python_cache_tag": getattr(sys.implementation, "cache_tag", ""),
            "bundle_root": str(root),
            **file_provenance(origin),
        }
    except Exception as error:
        return {
            "status": "unavailable",
            "python_cache_tag": getattr(sys.implementation, "cache_tag", ""),
            "error": str(error),
        }


def import_provenance(args=None, options=None):
    """Record the package origins used to produce evaluator evidence."""
    modules = {}
    for name in (
        "dreamplace",
        "dreamplace.ops.routability_eval",
        "dreamplace.ops.gpugr.xplace_backend",
    ):
        spec = importlib.util.find_spec(name)
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        modules[name] = {
            "path": str(origin) if origin else "",
            "sha256": (
                hashlib.sha256(origin.read_bytes()).hexdigest()
                if origin and origin.is_file() else ""
            ),
        }
    result = {
        "schema_version": 2,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_root": str(PYTHON_ROOT),
        "modules": modules,
        "native_extensions": {"gpugr": gpugr_extension_provenance()},
    }
    if args is not None:
        result["request"] = {
            "design_name": args.design_name,
            "lef_input": [file_provenance(path) for path in args.lef_input],
            "def_input": file_provenance(args.def_input),
            "verilog_input": file_provenance(args.verilog_input),
            "aux_input": file_provenance(args.aux_input),
            "num_threads": args.num_threads,
            "timeout_sec": args.timeout_sec,
            "options": options or {},
        }
    return result


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
    options = parse_key_values(args.option)
    provenance_path = args.output_dir / "evaluator_import_provenance.json"
    provenance_path.write_text(
        json.dumps(
            import_provenance(args=args, options=options),
            indent=2,
            sort_keys=True,
        ) + "\n"
    )
    request = EvaluationRequest(
        design_name=args.design_name,
        lef_input=args.lef_input,
        def_input=args.def_input,
        verilog_input=args.verilog_input,
        aux_input=args.aux_input,
        output_dir=str(args.output_dir.resolve()),
        num_threads=args.num_threads,
        timeout_sec=args.timeout_sec,
        options=options,
    )
    results = []
    for item in args.backend:
        for backend in item.split(","):
            backend = backend.strip()
            if not backend:
                continue
            result = build_evaluator(backend).evaluate(request)
            result.artifacts["import_provenance"] = str(provenance_path)
            result.write_json(args.output_dir / (backend + ".json"))
            results.append(result.to_dict())
    summary = args.output_dir / "summary.json"
    summary.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n")
    print(summary)
    return 0 if all(result["status"] == "ok" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
