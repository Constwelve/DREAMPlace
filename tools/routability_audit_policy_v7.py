#!/usr/bin/env python3
"""Audit the complete corrected Policy V7 net-weight development campaign."""

import argparse
from itertools import product
import json
import math
from pathlib import Path

from tools.routability_audit_corrected import (
    EXPECTED_PROXY_RESOLUTIONS,
    EXPECTED_PROXY_STAGE_SLOTS,
    POLICY_V7_CANDIDATE_COUNT,
    POLICY_V7_COMPARISON_COUNT,
    POLICY_V7_EVALUATOR_RESULT_COUNT,
    POLICY_V7_METHOD_COUNT,
    POLICY_V7_PLACEMENT_COUNT,
    POLICY_V7_STAGE,
    audit_policy_v7_attestation_record,
    audit_proxy_resolution_evidence,
    audit_strict_selection,
    canonical_json_sha256,
    read_status,
    sha256,
)
from tools.routability_audit_placement_effect import audit_placement_effect
from tools.routability_select_survivors import (
    ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS,
    load_plugin_states,
    select_survivors,
)
from tools.routability_summarize import campaign_identity


EXPECTED_CASE_SEEDS = EXPECTED_PROXY_STAGE_SLOTS[POLICY_V7_STAGE]
EXPECTED_RESOLUTION = EXPECTED_PROXY_RESOLUTIONS[POLICY_V7_STAGE]
FACTORIAL_DIMENSIONS = {
    "feedback_proxies": ["gpugr", "rudy"],
    "gammas": [0.005, 0.025],
    "frequencies": [10, 40],
    "activation_thresholds": [0.4, 0.8],
    "normalizations": ["absolute", "design_mean"],
    "lifecycle_phases": ["post_gradient", "pre_objective"],
    "score_modes": ["bbox_mean", "bbox_pmean", "pin_mean"],
}
GRID_KEYS = (
    "ruplace_net_weight_freq",
    "ruplace_net_weight_gamma",
    "ruplace_net_weight_normalization",
    "ruplace_net_weight_phase",
    "ruplace_net_weight_score_mode",
    "ruplace_plugin_start_overflow",
)
OPTIMIZATION_SOURCE_FILES = (
    "dreamplace/PlaceObj.py",
    "dreamplace/ops/routability_opt/plugin_base.py",
    "dreamplace/ops/routability_opt/pipeline.py",
    "dreamplace/ops/routability_opt/proxy.py",
    "dreamplace/ops/routability_opt/plugins/net_weighting.py",
    "dreamplace/params.json",
)
GPUGR_RUNTIME_LABELS = {
    "gpugr_extension",
    "io_parser_extension",
    "xplace_common",
    "xplace_flute",
}


def load_json(path):
    return json.loads(Path(path).read_text())


def finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def factorial_point(proxy, config):
    return (
        proxy,
        config.get("ruplace_net_weight_gamma"),
        config.get("ruplace_net_weight_freq"),
        config.get("ruplace_plugin_start_overflow"),
        config.get("ruplace_net_weight_normalization"),
        config.get("ruplace_net_weight_phase"),
        config.get("ruplace_net_weight_score_mode"),
    )


def expected_factorial_points():
    return set(product(
        FACTORIAL_DIMENSIONS["feedback_proxies"],
        FACTORIAL_DIMENSIONS["gammas"],
        FACTORIAL_DIMENSIONS["frequencies"],
        FACTORIAL_DIMENSIONS["activation_thresholds"],
        FACTORIAL_DIMENSIONS["normalizations"],
        FACTORIAL_DIMENSIONS["lifecycle_phases"],
        FACTORIAL_DIMENSIONS["score_modes"],
    ))


def audit_optimization_source_install(manifest_path, source_root):
    rows = {}
    for line in Path(manifest_path).read_text().splitlines():
        fields = line.split(None, 1)
        if len(fields) != 2 or len(fields[0]) != 64:
            raise ValueError("malformed Policy V7 source/install manifest")
        digest, name = fields
        if name in rows or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("invalid Policy V7 source/install manifest")
        rows[name] = digest

    expected = set(OPTIMIZATION_SOURCE_FILES) | {
        "install/" + name for name in OPTIMIZATION_SOURCE_FILES
    }
    if set(rows) != expected:
        raise ValueError("Policy V7 source/install coverage mismatch")

    source_root = Path(source_root).resolve()
    verified = {}
    for name in OPTIMIZATION_SOURCE_FILES:
        source_path = source_root / name
        installed_path = source_root / ("install/" + name)
        if (
            not source_path.is_file()
            or not installed_path.is_file()
            or rows[name] != rows["install/" + name]
            or sha256(source_path) != rows[name]
            or sha256(installed_path) != rows[name]
        ):
            raise ValueError(
                "Policy V7 source/install identity mismatch: %s" % name
            )
        verified[name] = rows[name]
    return verified


def audit_active_net_mask(path):
    record = load_json(path)
    if (
        record.get("status") != "passed"
        or record.get("active_net_mask") != "net_mask_ignore_large_degrees"
        or record.get("active_nets") != [True, True, False]
        or record.get("masked_net_affects_scale") is not False
        or record.get("masked_net_ratio") != 1.0
        or record.get("ratios") != [1.0, 1.25, 1.0]
        or record.get("score_scale") != 2.0
        or record.get("rudy_feedback_net_weights") != "frozen_input"
        or record.get("rudy_feedback_after_objective_weight_change") != 2.0
        or record.get("net_weight_score_modes")
        != ["pin_mean", "bbox_mean", "bbox_pmean"]
        or record.get("pin_mean_corridor_example") != 1.0
        or record.get("bbox_mean_corridor_example") != 12.0
        or not finite_number(record.get("bbox_pmean_corridor_example"))
        or record["bbox_pmean_corridor_example"] <= 12.0
    ):
        raise ValueError("invalid Policy V7 active-net-mask audit")
    return record


def audit_gpugr_runtime(specs):
    paths = {}
    for spec in specs:
        fields = spec.split("=", 1)
        if len(fields) != 2 or not all(fields):
            raise ValueError("GPUGR runtime file must be label=path")
        label, path = fields
        if label in paths:
            raise ValueError("duplicate GPUGR runtime label")
        paths[label] = Path(path)
    if set(paths) != GPUGR_RUNTIME_LABELS:
        raise ValueError("GPUGR runtime coverage mismatch")
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("GPUGR runtime file is missing")
    return {label: sha256(path) for label, path in sorted(paths.items())}


def audit_factorial(presets, manifest):
    generated = manifest.get("generated")
    metadata = manifest.get("metadata", {})
    if (
        not isinstance(generated, dict)
        or len(generated) != POLICY_V7_CANDIDATE_COUNT
        or set(presets) != {"hpwl"} | set(generated)
        or metadata.get("generated_count") != POLICY_V7_CANDIDATE_COUNT
        or metadata.get("development_only") is not True
        or metadata.get("heldout_or_golden_evidence_used") is not False
        or metadata.get("numeric_backend_mixing") is not False
    ):
        raise ValueError("Policy V7 preset/manifest coverage mismatch")

    points = set()
    for method, provenance in generated.items():
        config = presets[method]
        grid = provenance.get("grid")
        if (
            provenance.get("plugins") != ["net_weighting"]
            or provenance.get("development_only") is not True
            or provenance.get("proxy") not in ("rudy", "gpugr")
            or not isinstance(grid, dict)
            or set(grid) != set(GRID_KEYS)
            or config.get("ruplace_plugins") != ["net_weighting"]
            or config.get("ruplace_proxy") != provenance.get("proxy")
            or any(config.get(key) != grid[key] for key in GRID_KEYS)
            or int(config.get("ruplace_flag", 0)) != 1
            or int(config.get("routability_opt_flag", 0)) != 1
            or config.get("ruplace_net_weight_bbox_power") != 4.0
            or config.get("ruplace_net_weight_max") != 1.25
            or config.get("ruplace_proxy_refresh_interval") != 20
        ):
            raise ValueError("invalid Policy V7 method provenance: %s" % method)
        point = factorial_point(provenance["proxy"], config)
        if point in points:
            raise ValueError("duplicate Policy V7 factorial point")
        points.add(point)
    if points != expected_factorial_points():
        raise ValueError("Policy V7 factorial coverage mismatch")
    return points


def index_placements(comparison, expected_methods):
    placements = comparison.get("placements", [])
    by_method = {
        row.get("method"): row for row in placements
        if isinstance(row, dict) and row.get("method")
    }
    if len(by_method) != len(placements) or set(by_method) != expected_methods:
        raise ValueError("Policy V7 placement method coverage mismatch")
    return by_method


def audit_evaluation(method_dir, case, method):
    evaluation_dir = method_dir / "evaluation"
    combined = load_json(evaluation_dir / "summary.json")
    rows = combined.get("results", [])
    by_backend = {
        row.get("backend"): row for row in rows
        if isinstance(row, dict) and row.get("backend")
    }
    if len(by_backend) != len(rows) or set(by_backend) != {"rudy", "gpugr"}:
        raise ValueError("Policy V7 evaluator backend coverage mismatch")

    primary_count = 0
    for backend in ("rudy", "gpugr"):
        direct = load_json(evaluation_dir / (backend + ".json"))
        row = by_backend[backend]
        if (
            row.get("backend") != backend
            or direct.get("backend") != backend
            or row.get("status") != "ok"
            or direct.get("status") != "ok"
            or row.get("error")
            or direct.get("error")
            or row.get("metrics") != direct.get("metrics")
        ):
            raise ValueError(
                "Policy V7 evaluator identity mismatch: %s/%s/%s"
                % (case, method, backend)
            )
        metrics = direct["metrics"]
        if (
            metrics.get("route_x_size"), metrics.get("route_y_size")
        ) != EXPECTED_RESOLUTION:
            raise ValueError("Policy V7 evaluator resolution mismatch")
        required = [
            metric for metric_backend, metric
            in ABSOLUTE_DIRECTIONAL_PRIMARY_METRICS
            if metric_backend == backend
        ]
        if any(not finite_number(metrics.get(metric)) for metric in required):
            raise ValueError("Policy V7 evaluator has a nonfinite primary metric")
        if backend == "gpugr" and metrics["gr_wirelength"] <= 0:
            raise ValueError("Policy V7 GPUGR routed wirelength is not positive")
        primary_count += len(required)
    return 2, primary_count


def audit_campaign(args):
    campaign = args.campaign.resolve()
    presets = load_json(args.presets)
    manifest = load_json(args.manifest)
    points = audit_factorial(presets, manifest)
    optimization_sources = audit_optimization_source_install(
        args.optimization_source_install_manifest,
        args.optimization_source_root,
    )
    audit_active_net_mask(args.active_net_mask_audit)
    gpugr_runtime = audit_gpugr_runtime(args.gpugr_runtime_file)
    expected_methods = set(presets)

    selection = audit_strict_selection(
        args.selection, POLICY_V7_COMPARISON_COUNT, allow_empty=True,
        required_metric_profile="absolute_directional_v2",
    )
    resolution = audit_proxy_resolution_evidence(
        args.selection, selection, POLICY_V7_STAGE,
        POLICY_V7_COMPARISON_COUNT, EXPECTED_RESOLUTION,
    )
    if set(resolution["methods"]) != expected_methods:
        raise ValueError("Policy V7 summary did not cover the frozen methods")

    recomputed = select_survivors(
        load_json(args.summary), load_plugin_states(args.raw),
        max_survivors=5, max_primary_worst_regression=0.0,
        preset_provenance=manifest["generated"],
        metric_profile="absolute_directional_v2",
        selection_policy="routability_first",
    )
    if canonical_json_sha256(recomputed) != canonical_json_sha256(selection):
        raise ValueError("Policy V7 selection does not match recomputation")

    comparison_paths = sorted(campaign.rglob("methods/comparison.json"))
    comparisons = {
        campaign_identity(path, campaign): path for path in comparison_paths
    }
    if (
        len(comparisons) != len(comparison_paths)
        or set(comparisons) != set(EXPECTED_CASE_SEEDS)
    ):
        raise ValueError("Policy V7 campaign case/seed coverage mismatch")

    evaluator_results = 0
    primary_metric_values = 0
    placement_hpwl_count = 0
    for (case, seed), comparison_path in sorted(comparisons.items()):
        comparison = load_json(comparison_path)
        validation = comparison.get("validation", {})
        if (
            validation.get("status") != "validated"
            or validation.get("selected_backends") != ["rudy", "gpugr"]
            or set(validation.get("selected_backends_by_method", {}))
            != expected_methods
            or any(
                value != ["rudy", "gpugr"]
                for value in validation["selected_backends_by_method"].values()
            )
        ):
            raise ValueError("Policy V7 comparison validation mismatch")
        placements = index_placements(comparison, expected_methods)
        for method in sorted(expected_methods):
            method_dir = comparison_path.parent / method
            config = load_json(method_dir / "config.json")
            if (
                config.get("random_seed") != seed
                or any(
                    config.get(key) != value
                    for key, value in presets[method].items()
                )
                or (
                    config.get("route_num_bins_x"),
                    config.get("route_num_bins_y"),
                ) != EXPECTED_RESOLUTION
                or (
                    config.get("routability_eval_route_x_size"),
                    config.get("routability_eval_route_y_size"),
                ) != EXPECTED_RESOLUTION
            ):
                raise ValueError(
                    "Policy V7 config mismatch: %s/%s/%s"
                    % (case, seed, method)
                )
            placement = placements[method]
            if (
                placement.get("status") != "ok"
                or not finite_number(placement.get("placement_hpwl"))
                or placement["placement_hpwl"] <= 0
            ):
                raise ValueError("Policy V7 placement HPWL contract mismatch")
            placement_hpwl_count += 1
            result_count, metric_count = audit_evaluation(
                method_dir, case, method
            )
            evaluator_results += result_count
            primary_metric_values += metric_count

    placement_effect = load_json(args.placement_effect_audit)
    recomputed_effect = audit_placement_effect(
        campaign, POLICY_V7_COMPARISON_COUNT,
        allow_active_identical=True,
    )
    if canonical_json_sha256(placement_effect) != canonical_json_sha256(
        recomputed_effect
    ):
        raise ValueError("Policy V7 placement-effect audit mismatch")
    placement_class_keys = (
        "active_changed_count",
        "active_identical_count",
        "inactive_identical_count",
        "inactive_changed_count",
    )
    placement_class_counts = [
        placement_effect.get(key) for key in placement_class_keys
    ]
    inactive_methods = {
        row["method"] for row in placement_effect.get("rows", [])
        if not row.get("active")
    }
    excluded_methods = inactive_methods | set(
        placement_effect.get("active_identical_methods", [])
    )
    if (
        placement_effect.get("placement_count") != POLICY_V7_PLACEMENT_COUNT
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in placement_class_counts
        )
        or sum(placement_class_counts) != POLICY_V7_PLACEMENT_COUNT
        or set(placement_effect.get("inactive_methods", []))
        != inactive_methods
        or excluded_methods & set(selection["selected_methods"])
    ):
        raise ValueError("Policy V7 placement-effect contract mismatch")

    selection_audit = load_json(args.selection_audit)
    status = read_status(args.terminal_status)
    if (
        selection_audit.get("status") != "passed"
        or selection_audit.get("selected_methods")
        != selection["selected_methods"]
        or selection_audit.get("metric_profile")
        != "absolute_directional_v2"
        or selection_audit.get("net_weight_lifecycle_corrected") is not True
        or selection_audit.get("max_primary_worst_regression") != 0.0
        or selection_audit.get("numeric_backend_mixing") is not False
        or selection_audit.get("heldout_or_golden_evidence_used") is not False
        or selection_audit.get("placement_effect_audit_sha256")
        != sha256(args.placement_effect_audit)
        or status.get("phase") not in (
            "completed_no_atomic_survivor", "completed_atomic_survivors",
        )
        or status.get("proposal_policy_version") != "7"
    ):
        raise ValueError("Policy V7 terminal selection evidence mismatch")

    result = {
        "schema_version": 1,
        "status": "passed",
        "stage": POLICY_V7_STAGE,
        "proposal_policy_version": 7,
        "metric_profile": "absolute_directional_v2",
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "candidate_count": POLICY_V7_CANDIDATE_COUNT,
        "method_count": POLICY_V7_METHOD_COUNT,
        "comparison_count": POLICY_V7_COMPARISON_COUNT,
        "candidate_placement_count": POLICY_V7_PLACEMENT_COUNT,
        "evaluator_result_count": evaluator_results,
        "placement_hpwl_count": placement_hpwl_count,
        "primary_metric_value_count": primary_metric_values,
        "factorial_dimensions": FACTORIAL_DIMENSIONS,
        "factorial_unique_point_count": len(points),
        "optimization_source_install_match": True,
        "optimization_source_sha256": optimization_sources,
        "active_net_mask_audit_status": "passed",
        "gpugr_runtime_sha256": gpugr_runtime,
        "selected_methods": selection["selected_methods"],
        "selection_recomputed": True,
        "placement_effect_recomputed": True,
        "placement_effect_status": placement_effect["status"],
        "active_changed_count": placement_effect["active_changed_count"],
        "active_identical_count": placement_effect["active_identical_count"],
        "inactive_identical_count": placement_effect["inactive_identical_count"],
        "inactive_changed_count": placement_effect["inactive_changed_count"],
        "placement_effect_excluded_methods": sorted(excluded_methods),
        "sha256": {
            "presets": sha256(args.presets),
            "manifest": sha256(args.manifest),
            "summary": sha256(args.summary),
            "screening_raw": sha256(args.raw),
            "selection": sha256(args.selection),
            "placement_effect_audit": sha256(args.placement_effect_audit),
            "selection_audit": sha256(args.selection_audit),
            "terminal_status": sha256(args.terminal_status),
            "optimization_source_install": sha256(
                args.optimization_source_install_manifest
            ),
            "active_net_mask_audit": sha256(args.active_net_mask_audit),
        },
    }
    if evaluator_results != POLICY_V7_EVALUATOR_RESULT_COUNT:
        raise ValueError("Policy V7 evaluator result count mismatch")
    return audit_policy_v7_attestation_record(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--placement-effect-audit", type=Path, required=True)
    parser.add_argument("--selection-audit", type=Path, required=True)
    parser.add_argument("--terminal-status", type=Path, required=True)
    parser.add_argument(
        "--optimization-source-install-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--optimization-source-root", type=Path, default=Path(".")
    )
    parser.add_argument("--active-net-mask-audit", type=Path, required=True)
    parser.add_argument(
        "--gpugr-runtime-file", action="append", required=True,
        help="label=path; supply all four pinned GPUGR runtime libraries",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_campaign(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
