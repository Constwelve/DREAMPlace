#!/usr/bin/env python3
"""Aggregate routability campaigns without mixing evaluator backends."""

import argparse
import csv
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dreamplace.ops.routability_eval.innovus import (
    parse_innovus_connectivity_report,
    parse_innovus_drc_report_file,
    parse_innovus_log,
)
from dreamplace.ops.routability_eval.openroad import (
    parse_openroad_congestion_report,
    parse_openroad_detailed_route_metrics,
)


PRIMARY_METRICS = {
    "placement": ("placement_hpwl", "density_overflow", "runtime_sec"),
    "rudy": (
        "overflow_sum", "overflow_bins", "congestion_score", "utilization_max",
        "utilization_p99",
    ),
    "gpugr": (
        "gr_wirelength", "gr_vias", "est_shorts", "num_ovfl_nets",
        "rc_hor", "rc_ver", "overflow_sum", "overflow_bins",
        "congestion_score",
        "utilization_max", "utilization_p99",
        "horizontal_congestion_score", "vertical_congestion_score",
        "horizontal_congestion_score_p95", "vertical_congestion_score_p95",
        "horizontal_congestion_score_p99", "vertical_congestion_score_p99",
        "horizontal_overflow_sum", "vertical_overflow_sum",
        "horizontal_overflow_bins", "vertical_overflow_bins",
        "horizontal_utilization_max", "vertical_utilization_max",
        "horizontal_utilization_p99", "vertical_utilization_p99",
        "horizontal_ace", "vertical_ace",
    ),
    "openroad": (
        "wirelength", "vias", "total_overflow", "horizontal_overflow",
        "vertical_overflow", "horizontal_overflow_edges",
        "vertical_overflow_edges", "drc_violations", "unrouted_nets",
        "short_violations",
    ),
    "innovus": (
        "wirelength", "vias", "total_overflow", "horizontal_overflow",
        "vertical_overflow", "horizontal_congestion", "vertical_congestion",
        "drc_violations", "unrouted_nets", "short_violations",
        "connectivity_violations", "open_violations",
    ),
}

T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

DELTA_TOLERANCE = 1e-12
GOLDEN_BACKENDS = ("openroad", "innovus")
GOLDEN_REQUIRED_ARTIFACTS = {
    "openroad": (
        "log", "drc", "metrics", "congestion", "guide", "script",
    ),
    "innovus": ("log", "drc", "metrics", "connectivity", "script"),
}


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def normalized_plugin_names(value):
    """Return a canonical plugin tuple, rejecting malformed declarations."""
    if value is None:
        return ()
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError("plugin names must be non-empty strings")
        values = [item.strip() for item in value]
    else:
        raise ValueError("plugin declaration must be a list or comma-separated string")
    if len(values) != len(set(values)):
        raise ValueError("plugin declaration contains duplicates")
    return tuple(sorted(values))


def placement_plugin_activation_error(placement, config):
    """Validate that a frozen placement activated exactly its configured plugins."""
    method = str(placement.get("method", "missing"))
    if placement.get("status") != "ok":
        return "%s placement status is %s" % (
            method, placement.get("status", "missing")
        )
    try:
        expected = normalized_plugin_names(config.get("ruplace_plugins"))
        selected = normalized_plugin_names(
            placement.get("routability_plugin_selected", "")
        )
    except ValueError as error:
        return "%s has invalid plugin provenance: %s" % (method, error)
    status = placement.get("routability_plugin_status", "")
    summary = placement.get("routability_plugin_summary")
    plugins = summary.get("plugins") if isinstance(summary, dict) else None
    if not expected:
        if status != "not_selected" or selected:
            return "%s baseline unexpectedly selected or activated plugins" % method
        if not isinstance(plugins, dict) or plugins:
            return "%s baseline lacks empty plugin-summary evidence" % method
        return ""
    if status != "active":
        return "%s plugin status is %s, expected active" % (
            method, status or "missing"
        )
    if selected != expected:
        return "%s selected plugins %s, expected %s" % (
            method, ",".join(selected) or "none", ",".join(expected)
        )
    if not isinstance(plugins, dict):
        return "%s lacks per-plugin activation summary" % method
    try:
        summarized = normalized_plugin_names(list(plugins))
    except ValueError as error:
        return "%s has invalid plugin summary: %s" % (method, error)
    if summarized != expected:
        return "%s summarized plugins %s, expected %s" % (
            method, ",".join(summarized) or "none", ",".join(expected)
        )
    for plugin in expected:
        evidence = plugins.get(plugin)
        activations = evidence.get("activations") if isinstance(evidence, dict) else None
        if (
            not isinstance(evidence, dict)
            or evidence.get("status") != "active"
            or not finite_number(activations)
            or activations <= 0
        ):
            return "%s plugin %s lacks positive active evidence" % (method, plugin)
    return ""


def campaign_identity(path, root):
    parts = path.relative_to(root).parts
    seed_index = next(
        (index for index, part in enumerate(parts) if part.startswith("seed_")),
        None,
    )
    if seed_index is None or seed_index == 0:
        raise ValueError("cannot infer case and seed from %s" % path)
    return parts[seed_index - 1], int(parts[seed_index][len("seed_"):])


def flatten_result(case, seed, method, backend, metrics, result):
    row = {
        "case": case,
        "seed": seed,
        "method": method,
        "backend": backend,
        "status": result.get("status", ""),
        "runtime_sec": result.get("runtime_sec", ""),
    }
    for key, value in metrics.items():
        if finite_number(value):
            row[key] = value
    return row


def artifact_path(result, name):
    value = result.get("artifacts", {}).get(name)
    if not value:
        return None
    path = Path(value)
    return path if path.is_file() else None


def artifact_text(result, name):
    path = artifact_path(result, name)
    return path.read_text(errors="replace") if path else ""


def golden_artifact_contract_error(backend, derived):
    required = {
        "openroad": (
            "wirelength", "vias", "drc_violations", "unrouted_nets",
            "short_violations", "horizontal_overflow", "vertical_overflow",
        ),
        "innovus": (
            "wirelength", "vias", "drc_violations", "unrouted_nets",
            "short_violations", "connectivity_violations", "open_violations",
        ),
    }.get(backend, ())
    missing = [name for name in required if not finite_number(derived.get(name))]
    if backend == "innovus" and not (
        all(finite_number(derived.get(name)) for name in (
            "horizontal_overflow", "vertical_overflow"
        ))
        or all(finite_number(derived.get(name)) for name in (
            "horizontal_congestion", "vertical_congestion"
        ))
    ):
        missing.append("horizontal/vertical congestion")
    return "missing artifact-derived %s" % ", ".join(missing) if missing else ""


def enrich_golden_metrics(result, require_complete=False):
    """Backfill metrics and reject disagreement with retained artifacts."""
    backend = result.get("backend", "")
    if require_complete and backend not in GOLDEN_BACKENDS:
        raise ValueError("unsupported golden backend: %s" % (backend or "missing"))
    metrics = dict(result.get("metrics", {}))
    log_text = artifact_text(result, "log")
    derived = {}
    if backend == "openroad":
        raw_path = artifact_path(result, "metrics")
        try:
            raw_metrics = json.loads(raw_path.read_text()) if raw_path else {}
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("openroad metrics artifact is unreadable: %s" % error)
        persisted_raw = metrics.get("openroad_metrics")
        if persisted_raw is not None and persisted_raw != raw_metrics:
            raise ValueError(
                "openroad persisted raw metrics disagree with metrics artifact"
            )
        metrics["openroad_metrics"] = raw_metrics
        for source, target in (
            ("route__wirelength", "wirelength"),
            ("route__vias", "vias"),
            ("route__drc_errors", "drc_violations"),
        ):
            if source in raw_metrics:
                derived[target] = raw_metrics[source]
        congestion_path = artifact_path(result, "congestion")
        if congestion_path:
            derived.update(parse_openroad_congestion_report(
                congestion_path.read_text(errors="replace")
            ))
        derived.update(parse_openroad_detailed_route_metrics(
            log_text, raw_metrics
        ))
    elif backend == "innovus":
        derived.update(parse_innovus_log(log_text))
        drc_path = artifact_path(result, "drc")
        if drc_path:
            report_metrics = parse_innovus_drc_report_file(
                drc_path, known_short_violations=derived.get("short_violations")
            )
            for key, value in report_metrics.items():
                if key in derived and not math.isclose(
                    float(derived[key]), float(value), rel_tol=1e-9, abs_tol=1e-9
                ):
                    raise ValueError(
                        "innovus log %s %r disagrees with DRC report %r" % (
                            key, derived[key], value
                        )
                    )
            derived.update(report_metrics)
        elif metrics.get("drc_violations") == 0:
            derived["short_violations"] = 0.0
        connectivity_text = artifact_text(result, "connectivity")
        if connectivity_text:
            derived.update(parse_innovus_connectivity_report(connectivity_text))
    for key, value in derived.items():
        if key in metrics:
            persisted = metrics[key]
            if (
                not finite_number(persisted)
                or not finite_number(value)
                or not math.isclose(
                    float(persisted), float(value), rel_tol=1e-9, abs_tol=1e-9
                )
            ):
                raise ValueError(
                    "%s:%s persisted metric %r disagrees with artifact metric %r"
                    % (backend, key, persisted, value)
                )
        else:
            metrics[key] = value
    if require_complete:
        contract_error = golden_artifact_contract_error(backend, derived)
        if contract_error:
            raise ValueError("%s:%s" % (backend, contract_error))
    return metrics


def load_comparison(path, root):
    case, seed = campaign_identity(path, root)
    data = json.loads(path.read_text())
    validation = data.get("validation", {})
    if validation.get("status") != "validated":
        return [], {
            "case": case,
            "seed": seed,
            "path": str(path),
            "status": validation.get("status", "missing"),
        }

    golden_methods = {
        result.get("method") for result in data.get("results", [])
        if result.get("backend") in GOLDEN_BACKENDS
    }
    if golden_methods:
        placements = data.get("placements", [])
        placement_methods = [placement.get("method") for placement in placements]
        if (
            None in golden_methods
            or len(placement_methods) != len(set(placement_methods))
            or set(placement_methods) != golden_methods
        ):
            return [], {
                "case": case,
                "seed": seed,
                "path": str(path),
                "status": "plugin_activation_contract",
                "error": "golden result methods do not exactly match placement provenance",
            }
        for placement in placements:
            method = placement["method"]
            config_path = path.parent / method / "config.json"
            try:
                config = json.loads(config_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                return [], {
                    "case": case,
                    "seed": seed,
                    "path": str(path),
                    "status": "plugin_activation_contract",
                    "error": "%s config is unavailable: %s" % (method, error),
                }
            activation_error = placement_plugin_activation_error(placement, config)
            if activation_error:
                return [], {
                    "case": case,
                    "seed": seed,
                    "path": str(path),
                    "status": "plugin_activation_contract",
                    "error": activation_error,
                }

    rows = []
    for placement in data.get("placements", []):
        if placement.get("status") != "ok":
            continue
        metrics = {
            key: placement.get(key)
            for key in PRIMARY_METRICS["placement"]
            if finite_number(placement.get(key))
        }
        row = flatten_result(
            case, seed, placement.get("method", ""), "placement", metrics,
            placement,
        )
        row["plugin_status"] = placement.get("routability_plugin_status", "")
        row["plugin_selected"] = placement.get("routability_plugin_selected", "")
        rows.append(row)

    for result in data.get("results", []):
        if result.get("status") != "ok" or not result.get(
            "authoritative_for_comparison", False
        ):
            continue
        backend = result.get("backend", "")
        if backend in GOLDEN_BACKENDS:
            invalid = next((
                metric for metric in PRIMARY_METRICS[backend]
                if finite_number(result.get("metrics", {}).get(metric))
                and result["metrics"][metric] < 0
            ), None)
            if invalid is not None:
                return [], {
                    "case": case,
                    "seed": seed,
                    "path": str(path),
                    "status": "invalid_metric",
                    "error": "%s:%s is negative" % (backend, invalid),
                }
            missing_artifacts = [
                name for name in GOLDEN_REQUIRED_ARTIFACTS[backend]
                if artifact_path(result, name) is None
            ]
            if missing_artifacts:
                return [], {
                    "case": case,
                    "seed": seed,
                    "path": str(path),
                    "status": "missing_artifact",
                    "error": "%s missing retained artifact(s): %s" % (
                        backend, ", ".join(missing_artifacts)
                    ),
                }
        try:
            metrics = enrich_golden_metrics(
                result, require_complete=backend in GOLDEN_BACKENDS
            )
        except ValueError as error:
            return [], {
                "case": case,
                "seed": seed,
                "path": str(path),
                "status": "artifact_metric_mismatch",
                "error": str(error),
            }
        if backend in GOLDEN_BACKENDS:
            invalid = next((
                metric for metric in PRIMARY_METRICS[backend]
                if finite_number(metrics.get(metric)) and metrics[metric] < 0
            ), None)
            if invalid is not None:
                return [], {
                    "case": case,
                    "seed": seed,
                    "path": str(path),
                    "status": "invalid_metric",
                    "error": "%s:%s is negative" % (backend, invalid),
                }
        rows.append(flatten_result(
            case,
            seed,
            result.get("method", ""),
            backend,
            metrics,
            result,
        ))
    return rows, None


def add_baseline_deltas(rows, baseline):
    baselines = {
        (row["case"], row["seed"], row["backend"]): row
        for row in rows if row["method"] == baseline
    }
    for row in rows:
        base = baselines.get((row["case"], row["seed"], row["backend"]))
        if not base:
            continue
        for metric in PRIMARY_METRICS.get(row["backend"], ()):
            value = row.get(metric)
            base_value = base.get(metric)
            if finite_number(value) and finite_number(base_value):
                row[metric + "_baseline"] = base_value
                row[metric + "_delta"] = value - base_value
                if base_value != 0:
                    row[metric + "_delta_pct"] = (value / base_value - 1.0) * 100.0
    return baselines


def mean_ci95(values):
    if len(values) < 2:
        return None, None
    mean = statistics.fmean(values)
    critical = T_CRITICAL_95.get(len(values) - 1, 1.96)
    margin = critical * statistics.stdev(values) / math.sqrt(len(values))
    return mean - margin, mean + margin


def summarize(rows, baselines, expected_override=None, campaign_complete=True):
    groups = defaultdict(list)
    for row in rows:
        for metric in PRIMARY_METRICS.get(row["backend"], ()):
            delta_value = row.get(metric + "_delta")
            delta = row.get(metric + "_delta_pct")
            if finite_number(delta_value):
                groups[(row["backend"], metric, row["method"])].append({
                    "case": row["case"],
                    "seed": row["seed"],
                    "value": row[metric],
                    "baseline": row[metric + "_baseline"],
                    "delta": delta_value,
                    "delta_pct": delta if finite_number(delta) else None,
                })

    expected = defaultdict(int)
    for _, _, backend in baselines:
        expected[backend] += 1
    if expected_override is not None:
        for backend in list(expected):
            expected[backend] = expected_override

    summary = []
    for (backend, metric, method), observations in sorted(groups.items()):
        values = [
            item["delta_pct"] for item in observations
            if finite_number(item["delta_pct"])
        ]
        delta_values = [item["delta"] for item in observations]
        case_groups = defaultdict(list)
        raw_case_groups = defaultdict(list)
        observation_case_groups = defaultdict(list)
        for item in observations:
            raw_case_groups[item["case"]].append(item["delta"])
            observation_case_groups[item["case"]].append(item)
            if finite_number(item["delta_pct"]):
                case_groups[item["case"]].append(item["delta_pct"])
        case_means = [statistics.fmean(case_groups[case]) for case in sorted(case_groups)]
        raw_case_means = [
            statistics.fmean(raw_case_groups[case]) for case in sorted(raw_case_groups)
        ]
        case_results = []
        for case in sorted(raw_case_groups):
            raw_values = raw_case_groups[case]
            percent_values = case_groups.get(case, [])
            case_observations = observation_case_groups[case]
            case_results.append({
                "case": case,
                "valid_count": len(raw_values),
                "percent_valid_count": len(percent_values),
                "mean_value": statistics.fmean(
                    item["value"] for item in case_observations
                ),
                "mean_baseline": statistics.fmean(
                    item["baseline"] for item in case_observations
                ),
                "mean_delta": statistics.fmean(raw_values),
                "mean_delta_pct": (
                    statistics.fmean(percent_values)
                    if len(percent_values) == len(raw_values) else None
                ),
            })
        ci_low, ci_high = mean_ci95(case_means)
        raw_ci_low, raw_ci_high = mean_ci95(raw_case_means)
        wins = sum(value < -DELTA_TOLERANCE for value in delta_values)
        ties = sum(abs(value) <= DELTA_TOLERANCE for value in delta_values)
        case_wins = sum(value < -DELTA_TOLERANCE for value in raw_case_means)
        case_ties = sum(abs(value) <= DELTA_TOLERANCE for value in raw_case_means)
        full_coverage = len(observations) == expected[backend]
        percent_complete = len(values) == len(observations)
        evidence_ci_high = ci_high if percent_complete else raw_ci_high
        worst_pair = max(
            observations,
            key=lambda item: (
                item["delta_pct"] if percent_complete else item["delta"]
            ),
        )
        worst_case = max(
            case_results,
            key=lambda item: (
                item["mean_delta_pct"]
                if percent_complete else item["mean_delta"]
            ),
        )
        summary.append({
            "backend": backend,
            "metric": metric,
            "method": method,
            "valid_count": len(observations),
            "percent_valid_count": len(values),
            "expected_count": expected[backend],
            "mean_delta_pct": statistics.fmean(values) if values else None,
            "median_delta_pct": statistics.median(values) if values else None,
            "best_delta_pct": min(values) if values else None,
            "worst_delta_pct": max(values) if values else None,
            "mean_value": statistics.fmean(item["value"] for item in observations),
            "median_value": statistics.median(item["value"] for item in observations),
            "mean_baseline": statistics.fmean(
                item["baseline"] for item in observations
            ),
            "mean_delta": statistics.fmean(item["delta"] for item in observations),
            "median_delta": statistics.median(item["delta"] for item in observations),
            "best_delta": min(delta_values),
            "worst_delta": max(delta_values),
            "case_count": len(raw_case_means),
            "case_results": case_results,
            "case_mean_delta_pct": statistics.fmean(case_means) if case_means else None,
            "case_ci95_low_pct": ci_low,
            "case_ci95_high_pct": ci_high,
            "case_mean_delta": statistics.fmean(raw_case_means),
            "case_ci95_low": raw_ci_low,
            "case_ci95_high": raw_ci_high,
            "statistical_evidence_unit": (
                "percent" if percent_complete else "absolute"
            ),
            "case_wins": case_wins,
            "case_ties": case_ties,
            "case_losses": len(raw_case_means) - case_wins - case_ties,
            "worst_case": worst_case["case"],
            "worst_case_mean_delta": worst_case["mean_delta"],
            "worst_case_mean_delta_pct": worst_case["mean_delta_pct"],
            "worst_pair_case": worst_pair["case"],
            "worst_pair_seed": worst_pair["seed"],
            "worst_pair_value": worst_pair["value"],
            "worst_pair_baseline": worst_pair["baseline"],
            "worst_pair_delta": worst_pair["delta"],
            "worst_pair_delta_pct": worst_pair["delta_pct"],
            "statistically_supported": bool(
                campaign_complete and full_coverage
                and evidence_ci_high is not None and evidence_ci_high < 0
            ),
            "consistent_improvement": bool(
                campaign_complete and full_coverage and wins == len(delta_values)
            ),
            "wins": wins,
            "ties": ties,
            "losses": len(delta_values) - wins - ties,
        })
    return summary


def write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({
            key: (
                json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list)) else value
            )
            for key, value in row.items()
        } for row in rows)


def flatten_per_design(summary):
    rows = []
    for metric_row in summary:
        for case in metric_row.get("case_results", []):
            rows.append({
                "backend": metric_row["backend"],
                "metric": metric_row["metric"],
                "method": metric_row["method"],
                "case": case["case"],
                "valid_count": case["valid_count"],
                "percent_valid_count": case["percent_valid_count"],
                "mean_value": case["mean_value"],
                "mean_baseline": case["mean_baseline"],
                "mean_delta": case["mean_delta"],
                "mean_delta_pct": case["mean_delta_pct"],
                "is_worst_case": case["case"] == metric_row["worst_case"],
            })
    return rows


def write_report(path, comparisons, rows, summary, excluded, baseline, gate):
    def percent(value):
        return "n/a" if not finite_number(value) else "%.3f%%" % value

    def delta(value, percent_value):
        return percent(percent_value) if finite_number(percent_value) else (
            "n/a" if not finite_number(value) else "%+.3f" % value
        )

    def absolute(value):
        return "n/a" if not finite_number(value) else "%.6g" % value

    def comparison(value, baseline, delta_value, delta_pct):
        return "%s / %s (%s)" % (
            absolute(value), absolute(baseline), delta(delta_value, delta_pct),
        )

    expected = gate["expected_comparisons"]
    comparison_text = str(comparisons) if expected is None else "%d/%d" % (
        comparisons, expected
    )
    lines = [
        "# Routability Screening Summary",
        "",
        "- Baseline: `%s`" % baseline,
        "- Validated comparisons: `%s`" % comparison_text,
        "- Raw backend rows: `%d`" % len(rows),
        "- Excluded comparisons: `%d`" % len(excluded),
        "- Negative deltas are improvements; backends are ranked separately.",
        "- Confidence intervals use per-design means, so repeated seeds are not treated as independent designs.",
        "",
    ]
    for backend, metrics in PRIMARY_METRICS.items():
        for metric in metrics:
            ranking = [
                row for row in summary
                if row["backend"] == backend and row["metric"] == metric
            ]
            if not ranking:
                continue
            ranking.sort(key=lambda row: (
                row["mean_delta_pct"] if finite_number(row["mean_delta_pct"])
                else row["mean_delta"],
                row["method"],
            ))
            lines.extend([
                "## %s: %s" % (backend, metric),
                "",
                "| Method | Mean candidate / HPWL | Mean delta | Case 95% CI | Median | Worst | Worst pair candidate / HPWL | Per-design candidate / HPWL | Pair W/T/L | Case W/T/L | Coverage |",
                "|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|",
            ])
            for row in ranking:
                if finite_number(row["case_ci95_low_pct"]):
                    interval = "%.3f%% to %.3f%%" % (
                        row["case_ci95_low_pct"], row["case_ci95_high_pct"]
                    )
                elif finite_number(row["case_ci95_low"]):
                    interval = "%+.3f to %+.3f" % (
                        row["case_ci95_low"], row["case_ci95_high"]
                    )
                else:
                    interval = "n/a"
                worst_pair = "%s/%s %s" % (
                    row["worst_pair_case"], row["worst_pair_seed"],
                    comparison(
                        row["worst_pair_value"], row["worst_pair_baseline"],
                        row["worst_pair_delta"], row["worst_pair_delta_pct"],
                    ),
                )
                per_design = "; ".join(
                    "%s %s" % (
                        item["case"],
                        comparison(
                            item["mean_value"], item["mean_baseline"],
                            item["mean_delta"], item["mean_delta_pct"],
                        ),
                    )
                    for item in row["case_results"]
                )
                lines.append(
                    "| %s | %s | %s | %s | %s | %s | %s | %s | %d/%d/%d | %d/%d/%d | %d/%d |" % (
                        row["method"], comparison(
                            row["mean_value"], row["mean_baseline"],
                            row["mean_delta"], row["mean_delta_pct"],
                        ), delta(
                            row["mean_delta"], row["mean_delta_pct"]
                        ), interval, delta(
                            row["median_delta"], row["median_delta_pct"]
                        ), delta(
                            row["worst_delta"], row["worst_delta_pct"]
                        ), worst_pair, per_design,
                        row["wins"], row["ties"], row["losses"],
                        row["case_wins"], row["case_ties"], row["case_losses"],
                        row["valid_count"], row["expected_count"],
                    )
                )
            lines.append("")
    path.write_text("\n".join(lines) + "\n")


def campaign_gate(root, comparison_keys):
    status_path = root / "parallel_status.json"
    if not status_path.exists():
        return {
            "parallel_status": "not_present",
            "expected_comparisons": None,
            "expected_case_seeds": [],
            "incomplete_jobs": [],
            "missing_comparisons": [],
        }
    jobs = json.loads(status_path.read_text()).get("jobs", [])
    expected = {(str(job["case"]), int(job["seed"])) for job in jobs}
    incomplete = [
        {
            "case": str(job["case"]),
            "seed": int(job["seed"]),
            "status": str(job.get("status", "missing")),
            "returncode": job.get("returncode", ""),
        }
        for job in jobs if job.get("status") != "completed"
    ]
    missing = [
        {"case": case, "seed": seed}
        for case, seed in sorted(expected - comparison_keys)
    ]
    return {
        "parallel_status": str(status_path),
        "expected_comparisons": len(expected),
        "expected_case_seeds": [
            {"case": case, "seed": seed} for case, seed in sorted(expected)
        ],
        "incomplete_jobs": incomplete,
        "missing_comparisons": missing,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", default="hpwl")
    args = parser.parse_args(argv)

    root = args.campaign_dir.resolve()
    paths = sorted(root.rglob("comparison.json"))
    rows = []
    excluded = []
    valid_comparisons = 0
    for path in paths:
        loaded, exclusion = load_comparison(path, root)
        if exclusion:
            excluded.append(exclusion)
        else:
            rows.extend(loaded)
            valid_comparisons += 1

    baselines = add_baseline_deltas(rows, args.baseline)
    comparison_keys = {(row["case"], row["seed"]) for row in rows}
    gate = campaign_gate(root, comparison_keys)
    backends_by_comparison = defaultdict(set)
    for row in rows:
        backends_by_comparison[(row["case"], row["seed"])].add(row["backend"])
    baseline_gaps = []
    for case, seed in sorted(comparison_keys):
        for backend in sorted(backends_by_comparison[(case, seed)]):
            if (case, seed, backend) not in baselines:
                baseline_gaps.append({
                    "case": case, "seed": seed, "backend": backend,
                    "baseline": args.baseline,
                })
    campaign_complete = not gate["incomplete_jobs"] and not gate["missing_comparisons"]
    expected_override = None if campaign_complete else gate["expected_comparisons"]
    summary = summarize(
        rows, baselines, expected_override=expected_override,
        campaign_complete=campaign_complete,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "screening_raw.csv", rows)
    write_csv(args.output_dir / "screening_summary.csv", summary)
    write_csv(
        args.output_dir / "screening_per_design.csv",
        flatten_per_design(summary),
    )
    (args.output_dir / "screening_summary.json").write_text(json.dumps({
        "baseline": args.baseline,
        "comparison_files": len(paths),
        "validated_comparisons": valid_comparisons,
        "validated_case_seeds": [
            {"case": case, "seed": seed}
            for case, seed in sorted(comparison_keys)
        ],
        "excluded": excluded,
        "baseline_gaps": baseline_gaps,
        "plugin_activation_contract": (
            "validated" if any(
                row.get("backend") in GOLDEN_BACKENDS for row in rows
            ) else "not_applicable"
        ),
        **gate,
        "rows": summary,
    }, indent=2, sort_keys=True) + "\n")
    write_report(
        args.output_dir / "report.md", valid_comparisons, rows, summary,
        excluded, args.baseline, gate,
    )
    return 0 if (
        paths
        and valid_comparisons == len(paths)
        and not baseline_gaps
        and not gate["incomplete_jobs"]
        and not gate["missing_comparisons"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
