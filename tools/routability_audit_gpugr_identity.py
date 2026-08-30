#!/usr/bin/env python3
"""Audit evaluator equivalence across two ABI-specific GPUGR builds."""

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_MAPS = (
    "utilization_map",
    "overflow_map",
    "hv_utilization_map",
    "hv_overflow_map",
)
IGNORED_METRICS = {"time"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_result(path):
    data = json.loads(Path(path).read_text())
    if data.get("status") != "ok" or data.get("backend") != "gpugr":
        raise ValueError("expected a successful gpugr result: %s" % path)
    return data


def _native_identity(provenance_path):
    data = json.loads(Path(provenance_path).read_text())
    native = data.get("native_extensions", {}).get("gpugr", {})
    if native.get("status") != "resolved" or not native.get("sha256"):
        raise ValueError(
            "provenance lacks a resolved GPUGR extension: %s" % provenance_path
        )
    return data, native


def _request_identity(provenance):
    """Compare request content while allowing host-specific absolute paths."""
    request = provenance.get("request", {})

    def input_identity(value):
        if isinstance(value, list):
            return [input_identity(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            "sha256": value.get("sha256", ""),
            "size_bytes": value.get("size_bytes", 0),
        }

    return {
        "design_name": request.get("design_name", ""),
        "lef_input": input_identity(request.get("lef_input", [])),
        "def_input": input_identity(request.get("def_input", {})),
        "verilog_input": input_identity(request.get("verilog_input", {})),
        "aux_input": input_identity(request.get("aux_input", {})),
        "num_threads": request.get("num_threads"),
        "options": request.get("options", {}),
    }


def audit_identity(left_result, left_tensor, left_provenance,
                   right_result, right_tensor, right_provenance,
                   output=None, left_label="left", right_label="right"):
    import torch

    left_result = Path(left_result).resolve()
    right_result = Path(right_result).resolve()
    left_tensor = Path(left_tensor).resolve()
    right_tensor = Path(right_tensor).resolve()
    left_provenance = Path(left_provenance).resolve()
    right_provenance = Path(right_provenance).resolve()

    left_json = _load_result(left_result)
    right_json = _load_result(right_result)
    left_prov, left_native = _native_identity(left_provenance)
    right_prov, right_native = _native_identity(right_provenance)
    left_maps = torch.load(left_tensor, map_location="cpu")
    right_maps = torch.load(right_tensor, map_location="cpu")

    map_comparison = {}
    for name in REQUIRED_MAPS:
        if name not in left_maps or name not in right_maps:
            raise ValueError("required GPUGR map is missing: %s" % name)
        left = left_maps[name].detach().cpu()
        right = right_maps[name].detach().cpu()
        if tuple(left.shape) != tuple(right.shape):
            exact = False
            mismatch_count = None
            max_abs_diff = None
            mean_abs_diff = None
        else:
            difference = (left.float() - right.float()).abs()
            exact = bool(torch.equal(left, right))
            mismatch_count = int(torch.count_nonzero(left != right).item())
            max_abs_diff = float(difference.max().item()) if difference.numel() else 0.0
            mean_abs_diff = float(difference.mean().item()) if difference.numel() else 0.0
        map_comparison[name] = {
            "left_shape": list(left.shape),
            "right_shape": list(right.shape),
            "exact": exact,
            "mismatch_count": mismatch_count,
            "max_abs_diff": max_abs_diff,
            "mean_abs_diff": mean_abs_diff,
        }

    left_metrics = {
        key: value for key, value in left_json.get("metrics", {}).items()
        if key not in IGNORED_METRICS
    }
    right_metrics = {
        key: value for key, value in right_json.get("metrics", {}).items()
        if key not in IGNORED_METRICS
    }
    metric_keys_equal = set(left_metrics) == set(right_metrics)
    metric_comparison = {
        key: {
            "left": left_metrics.get(key),
            "right": right_metrics.get(key),
            "exact": left_metrics.get(key) == right_metrics.get(key),
        }
        for key in sorted(set(left_metrics) | set(right_metrics))
    }
    metrics_exact = metric_keys_equal and all(
        item["exact"] for item in metric_comparison.values()
    )
    maps_exact = all(item["exact"] for item in map_comparison.values())
    left_request_identity = _request_identity(left_prov)
    right_request_identity = _request_identity(right_prov)
    request_equal = left_request_identity == right_request_identity
    passed = maps_exact and metrics_exact and request_equal

    report = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "scope": "gpugr_evaluator_and_proxy_map_equivalence",
        "optimization_native_gradient_equivalence": "not_proven",
        "left": {
            "label": left_label,
            "result": str(left_result),
            "tensor": str(left_tensor),
            "provenance": str(left_provenance),
            "binary": left_native,
        },
        "right": {
            "label": right_label,
            "result": str(right_result),
            "tensor": str(right_tensor),
            "provenance": str(right_provenance),
            "binary": right_native,
        },
        "request_exact": request_equal,
        "request_identity": {
            "left": left_request_identity,
            "right": right_request_identity,
        },
        "maps_exact": maps_exact,
        "metrics_exact": metrics_exact,
        "map_comparison": map_comparison,
        "metric_comparison": metric_comparison,
        "sha256": {
            "left_result": sha256(left_result),
            "left_tensor": sha256(left_tensor),
            "left_provenance": sha256(left_provenance),
            "right_result": sha256(right_result),
            "right_tensor": sha256(right_tensor),
            "right_provenance": sha256(right_provenance),
        },
    }
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-result", type=Path, required=True)
    parser.add_argument("--left-tensor", type=Path, required=True)
    parser.add_argument("--left-provenance", type=Path, required=True)
    parser.add_argument("--right-result", type=Path, required=True)
    parser.add_argument("--right-tensor", type=Path, required=True)
    parser.add_argument("--right-provenance", type=Path, required=True)
    parser.add_argument("--left-label", default="left")
    parser.add_argument("--right-label", default="right")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_identity(
        args.left_result, args.left_tensor, args.left_provenance,
        args.right_result, args.right_tensor, args.right_provenance,
        args.output, args.left_label, args.right_label,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
