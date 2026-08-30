#!/usr/bin/env python3
"""Materialize declarative, independently auditable post-placement operations."""

import hashlib
import json
from pathlib import Path

from tools.routability_legal_refine_def import refine_def
from tools.routability_openroad_oracle import (
    generate_oracle,
    resolve_openroad_binary,
)


SUPPORTED_OPERATIONS = {
    "legal_whitespace_slide",
    "openroad_routability_direction_oracle",
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def post_placement_spec(config):
    spec = config.get("ruplace_post_placement")
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError("ruplace_post_placement must be an object")
    return spec


def validate_post_placement_order(methods, presets):
    """Require every derived method to name already-materialized source methods."""
    seen = set()
    for method in methods:
        if method not in presets:
            raise KeyError("unknown method preset %s" % method)
        spec = post_placement_spec(presets[method])
        if spec is not None:
            operation = spec.get("operation")
            if operation not in SUPPORTED_OPERATIONS:
                raise ValueError(
                    "unsupported post-placement operation for %s: %s"
                    % (method, operation)
                )
            baseline = spec.get("baseline_method")
            oracle = spec.get("oracle_method")
            if not baseline or (
                operation == "legal_whitespace_slide" and not oracle
            ):
                raise ValueError(
                    "%s lacks required source methods" % method
                )
            sources = [baseline]
            if oracle:
                sources.append(oracle)
            missing = [name for name in sources if name not in seen]
            if missing:
                raise ValueError(
                    "%s source methods must precede it: %s"
                    % (method, ", ".join(missing))
                )
            if (
                operation == "legal_whitespace_slide"
                and not spec.get("acceptance_group")
            ):
                raise ValueError("%s requires acceptance_group" % method)
        seen.add(method)


def materialize_post_placement(method, config, placed_defs, placement_dir,
                               output_name, lef_inputs, report_path):
    spec = post_placement_spec(config)
    if spec is None:
        raise ValueError("%s has no post-placement operation" % method)
    baseline_method = spec["baseline_method"]
    oracle_method = spec.get("oracle_method")
    try:
        baseline_def = placed_defs[baseline_method]
        oracle_def = placed_defs[oracle_method] if oracle_method else None
    except KeyError as error:
        raise ValueError(
            "%s source placement is unavailable: %s" % (method, error.args[0])
        ) from error
    if isinstance(lef_inputs, str):
        lef_inputs = [lef_inputs]

    output = placement_dir / output_name / (output_name + ".gp.def")
    operation = spec["operation"]
    if operation == "legal_whitespace_slide":
        report = refine_def(
            baseline_def,
            oracle_def,
            lef_inputs,
            output,
            max_steps=int(spec.get("max_steps", 1)),
            max_moved_fraction=float(spec.get("max_moved_fraction", 1.0)),
            min_moved_fraction=float(spec.get("min_moved_fraction", 0.0)),
            moved_fraction_windows=spec.get("moved_fraction_windows"),
            direction=str(spec.get("direction", "both")),
            sweep_order=str(spec.get("sweep_order", "right_left")),
            rank_mode=str(spec.get("rank_mode", "displacement")),
            max_net_bbox_delta_dbu=spec.get("max_net_bbox_delta_dbu"),
            report_path=report_path,
        )
    elif operation == "openroad_routability_direction_oracle":
        report = generate_oracle(
            baseline_def,
            lef_inputs,
            output,
            report_path=report_path,
            openroad_binary=spec.get("openroad_binary", "openroad"),
            threads=int(spec.get("threads", 8)),
            log_path=Path(report_path).with_suffix(".openroad.log"),
        )
    else:  # guarded by validate_post_placement_order
        raise ValueError("unsupported post-placement operation %s" % operation)
    report.update({
        "method": method,
        "baseline_method": baseline_method,
        "oracle_method": oracle_method,
        "acceptance_group": spec.get("acceptance_group"),
        "metric_profile": spec.get("metric_profile", "absolute_directional_v2"),
    })
    Path(report_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return output, report


def reusable_post_placement(report_path, output, method, spec, placed_defs,
                            lef_inputs):
    report_path = Path(report_path)
    output = Path(output).resolve()
    if not report_path.is_file() or not output.is_file():
        return False
    try:
        report = json.loads(report_path.read_text())
        baseline = Path(placed_defs[spec["baseline_method"]]).resolve()
        oracle_method = spec.get("oracle_method")
        oracle = (
            Path(placed_defs[oracle_method]).resolve()
            if oracle_method else None
        )
    except (KeyError, OSError, json.JSONDecodeError, TypeError):
        return False
    if isinstance(lef_inputs, str):
        lef_inputs = [lef_inputs]
    expected_lefs = {
        str(Path(path).resolve()): _sha256(path) for path in lef_inputs
    }
    operation = spec["operation"]
    if operation == "openroad_routability_direction_oracle":
        try:
            resolved_binary = resolve_openroad_binary(
                spec.get("openroad_binary", "openroad")
            )
        except FileNotFoundError:
            return False
        return bool(
            report.get("schema_version") == 1
            and report.get("method") == method
            and report.get("operation") == operation
            and report.get("baseline_method") == spec["baseline_method"]
            and Path(report.get("baseline_def", "")).resolve() == baseline
            and Path(report.get("output_def", "")).resolve() == output
            and report.get("baseline_sha256") == _sha256(baseline)
            and report.get("output_sha256") == _sha256(output)
            and report.get("lef_sha256") == expected_lefs
            and report.get("openroad_binary")
            == str(spec.get("openroad_binary", "openroad"))
            and report.get("openroad_binary_resolved") == str(resolved_binary)
            and report.get("openroad_binary_sha256") == _sha256(resolved_binary)
            and int(report.get("threads", -1)) == int(spec.get("threads", 8))
        )
    expected_windows = spec.get("moved_fraction_windows")
    if expected_windows is None:
        expected_windows = [[
            float(spec.get("min_moved_fraction", 0.0)),
            float(spec.get("max_moved_fraction", 1.0)),
        ]]
    else:
        expected_windows = [
            [float(start), float(stop)] for start, stop in expected_windows
        ]
    return bool(
        report.get("schema_version") == 2
        and report.get("method") == method
        and report.get("operation") == "route_directed_legal_whitespace_slide"
        and report.get("baseline_method") == spec["baseline_method"]
        and report.get("oracle_method") == spec["oracle_method"]
        and Path(report.get("baseline_def", "")).resolve() == baseline
        and Path(report.get("candidate_def", "")).resolve() == oracle
        and Path(report.get("output_def", "")).resolve() == output
        and report.get("baseline_sha256") == _sha256(baseline)
        and report.get("candidate_sha256") == _sha256(oracle)
        and report.get("output_sha256") == _sha256(output)
        and report.get("lef_sha256") == expected_lefs
        and int(report.get("max_steps", -1)) == int(spec.get("max_steps", 1))
        and float(report.get("max_moved_fraction", -1.0))
        == float(spec.get("max_moved_fraction", 1.0))
        and float(report.get("min_moved_fraction", -1.0))
        == float(spec.get("min_moved_fraction", 0.0))
        and report.get("moved_fraction_windows") == expected_windows
        and report.get("direction") == str(spec.get("direction", "both"))
        and report.get("sweep_order")
        == str(spec.get("sweep_order", "right_left"))
        and report.get("rank_mode", "displacement")
        == str(spec.get("rank_mode", "displacement"))
        and report.get("max_net_bbox_delta_dbu")
        == spec.get("max_net_bbox_delta_dbu")
        and report.get("acceptance_group") == spec["acceptance_group"]
        and report.get("metric_profile")
        == spec.get("metric_profile", "absolute_directional_v2")
    )


def placement_record(method, report, runtime_sec):
    if report["operation"] == "openroad_routability_direction_oracle":
        moved = int(report.get("output_sha256") != report.get("baseline_sha256"))
        attempts = 1
    else:
        moved = int(report.get("moved_components", 0))
        attempts = int(report.get("move_attempts", 0))
    return {
        "method": method,
        "evaluator": "placement",
        "validation_role": "placement_metric",
        "authoritative_for_comparison": False,
        "status": "ok",
        "runtime_sec": runtime_sec,
        "error": "",
        "routability_plugin_status": "active" if moved else "selected_no_activation",
        "routability_plugin_selected": report["operation"],
        "routability_plugin_attempts": attempts,
        "routability_plugin_activations": moved,
        "routability_plugin_summary": {
            "post_placement_operation": report,
        },
    }
