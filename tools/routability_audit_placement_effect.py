#!/usr/bin/env python3
"""Audit that active routability plugins change their emitted placements."""

import argparse
import hashlib
import json
from pathlib import Path

from tools.routability_summarize import (
    normalized_plugin_names,
    placement_plugin_activation_error,
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_source_index(campaign_dir):
    """Return hash-verified source records for a partial campaign snapshot."""
    manifest_path = Path(campaign_dir) / "snapshot_manifest.json"
    if not manifest_path.is_file():
        return None, None
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported placement snapshot manifest schema")
    index = {}
    for comparison in manifest.get("comparisons", []):
        key = (comparison.get("case"), int(comparison.get("seed")))
        if key in index:
            raise ValueError("duplicate placement snapshot comparison: %s" % (key,))
        sources = comparison.get("sources", [])
        by_method = {row.get("method"): row for row in sources}
        if not sources or len(by_method) != len(sources) or None in by_method:
            raise ValueError("invalid placement snapshot sources: %s" % (key,))
        index[key] = {
            "comparison": comparison.get("comparison"),
            "comparison_sha256": comparison.get("comparison_sha256"),
            "sources": by_method,
        }
    if not index:
        raise ValueError("placement snapshot manifest contains no comparisons")
    return index, sha256(manifest_path)


def verified_snapshot_path(record, path_key, hash_key, description):
    path = Path(record.get(path_key, ""))
    expected = record.get(hash_key)
    if not path.is_file() or not expected or sha256(path) != expected:
        raise ValueError("placement snapshot %s hash mismatch: %s" % (
            description, path,
        ))
    return path


def placed_def(method_dir):
    candidates = sorted((Path(method_dir) / "placement").glob("**/*.gp.def"))
    if len(candidates) != 1:
        raise ValueError(
            "%s has %d placed DEF candidates" % (method_dir, len(candidates))
        )
    return candidates[0]


def campaign_identity(methods_dir, campaign_dir):
    parts = methods_dir.relative_to(campaign_dir).parts
    seed_index = next(
        (index for index, part in enumerate(parts) if part.startswith("seed_")),
        None,
    )
    if seed_index is None or seed_index == 0:
        raise ValueError("cannot infer case and seed from %s" % methods_dir)
    return parts[seed_index - 1], int(parts[seed_index][len("seed_"):])


def area_budget_runtime_error(placement, config):
    """Validate explicitly enabled area budgets against runtime provenance."""
    if not int(config.get("ruplace_enforce_area_adjust_budget", 0)):
        return None
    summary = placement.get("routability_plugin_summary")
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            return "invalid runtime plugin summary JSON"
    if not isinstance(summary, dict) or not isinstance(
        summary.get("pipeline"), dict
    ):
        return "missing runtime pipeline summary"
    pipeline = summary["pipeline"]
    expected = int(config.get("max_num_area_adjust", -1))
    observations = pipeline.get("area_budget_observations")
    if observations is not None:
        if not isinstance(observations, list) or not observations:
            return "missing runtime area budget observations"
        for observation in observations:
            if not isinstance(observation, dict):
                return "invalid runtime area budget observation"
            if int(observation.get("area_budget_enabled", 0)) != 1:
                return "configured area budget was not enabled at runtime"
            if int(observation.get("max_area_adjustments", -1)) != expected:
                return "runtime area budget does not match configured maximum"
            actual = int(observation.get("area_adjustments", -1))
            if actual < 0 or actual > expected:
                return "runtime area adjustments exceed configured maximum"
        return None
    if int(pipeline.get("area_budget_enabled", 0)) != 1:
        return "configured area budget was not enabled at runtime"
    if int(pipeline.get("max_area_adjustments", -1)) != expected:
        return "runtime area budget does not match configured maximum"
    actual = int(pipeline.get("area_adjustments", -1))
    if actual < 0 or actual > expected:
        return "runtime area adjustments exceed configured maximum"
    return None


def configured_force_budgets(config):
    """Return effective nonnegative force caps for configured plugins."""
    plugins = normalized_plugin_names(config.get("ruplace_plugins"))
    budgets = {}
    for plugin in plugins:
        plugin_key = "ruplace_%s_max_applications" % plugin
        if plugin_key in config:
            maximum = int(config[plugin_key])
        elif "ruplace_force_max_applications" in config:
            maximum = int(config["ruplace_force_max_applications"])
        else:
            continue
        if maximum >= 0:
            budgets[plugin] = maximum
    return budgets


def force_budget_runtime_error(placement, config):
    """Validate configured force-application caps against runtime provenance."""
    budgets = configured_force_budgets(config)
    if not budgets:
        return None
    summary = placement.get("routability_plugin_summary")
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            return "invalid runtime plugin summary JSON"
    plugins = summary.get("plugins") if isinstance(summary, dict) else None
    if not isinstance(plugins, dict):
        return "missing runtime plugin summary"
    for plugin, expected in sorted(budgets.items()):
        runtime = plugins.get(plugin)
        metrics = runtime.get("metrics") if isinstance(runtime, dict) else None
        if not isinstance(metrics, dict):
            return "missing runtime force budget summary for %s" % plugin
        try:
            runtime_maximum = int(metrics["force_max_applications"])
            actual = int(metrics["force_applications"])
        except (KeyError, TypeError, ValueError):
            return "missing runtime force budget metrics for %s" % plugin
        if runtime_maximum != expected:
            return "runtime force budget for %s does not match configured maximum" % plugin
        if actual < 0 or actual > expected:
            return "runtime force applications for %s exceed configured maximum" % plugin
    return None


def placement_geometry_error(placement, placed_def):
    """Require hash-matching, independently parsed legal placement geometry."""
    placed_def = Path(placed_def).resolve()
    if placement.get("placed_def_sha256") != sha256(placed_def):
        return "placed DEF hash does not match comparison provenance"
    geometry = placement.get("placement_geometry_provenance")
    if not isinstance(geometry, dict) or geometry.get("status") != "ok":
        return "missing successful placement geometry provenance"
    if geometry.get("def_sha256") != placement.get("placed_def_sha256"):
        return "placement geometry DEF hash mismatch"
    for key in (
        "overlap_pair_count",
        "unplaced_component_count",
        "uncovered_component_count",
    ):
        if int(geometry.get(key, -1)) != 0:
            return "placement geometry has nonzero %s" % key
    return None


def audit_placement_effect(
    campaign_dir,
    expected_comparisons,
    baseline="hpwl",
    allow_active_identical=False,
):
    campaign_dir = Path(campaign_dir).resolve()
    comparison_paths = sorted(campaign_dir.glob("**/methods/comparison.json"))
    if len(comparison_paths) != int(expected_comparisons):
        raise ValueError(
            "placement-effect comparison coverage mismatch: %d != %d" % (
                len(comparison_paths), expected_comparisons,
            )
        )

    snapshot_index, snapshot_manifest_hash = snapshot_source_index(campaign_dir)
    rows = []
    active_identical = []
    area_budget_errors = []
    force_budget_errors = []
    slots = []
    for comparison_path in comparison_paths:
        methods_dir = comparison_path.parent
        case, seed = campaign_identity(methods_dir, campaign_dir)
        comparison = json.loads(comparison_path.read_text())
        if comparison.get("validation", {}).get("status") != "validated":
            raise ValueError("comparison is not validated: %s" % comparison_path)
        required_provenance = (
            "placement_input_provenance",
            "placement_implementation_provenance",
            "placement_runtime_provenance",
        )
        missing_provenance = [
            key for key in required_provenance
            if not isinstance(comparison.get(key), dict)
        ]
        if missing_provenance:
            raise ValueError(
                "comparison lacks placement provenance %s: %s" % (
                    ", ".join(missing_provenance), comparison_path,
                )
            )
        placements = comparison.get("placements", [])
        placement_index = {
            row.get("method"): row for row in placements if row.get("method")
        }
        if len(placement_index) != len(placements) or baseline not in placement_index:
            raise ValueError("invalid placement provenance: %s" % comparison_path)
        snapshot = None
        if snapshot_index is not None:
            snapshot = snapshot_index.get((case, seed))
            if snapshot is None:
                raise ValueError(
                    "placement snapshot lacks comparison: %s/%s" % (case, seed)
                )
            recorded_comparison = Path(snapshot.get("comparison", ""))
            if (recorded_comparison.resolve() != comparison_path.resolve()
                    or sha256(comparison_path) != snapshot.get("comparison_sha256")):
                raise ValueError(
                    "placement snapshot comparison hash mismatch: %s"
                    % comparison_path
                )
            if set(snapshot["sources"]) != set(placement_index):
                raise ValueError(
                    "placement snapshot method coverage mismatch: %s"
                    % comparison_path
                )

        if snapshot is None:
            baseline_dir = methods_dir / baseline
            baseline_config_path = baseline_dir / "config.json"
            baseline_def = placed_def(baseline_dir)
        else:
            baseline_source = snapshot["sources"][baseline]
            baseline_config_path = verified_snapshot_path(
                baseline_source, "config", "config_sha256", "baseline config"
            )
            baseline_def = verified_snapshot_path(
                baseline_source, "placed_def", "placed_def_sha256",
                "baseline DEF",
            )
        baseline_config = json.loads(baseline_config_path.read_text())
        baseline_error = placement_plugin_activation_error(
            placement_index[baseline], baseline_config
        )
        if baseline_error:
            raise ValueError("invalid placement baseline: %s" % baseline_error)
        baseline_hash = sha256(baseline_def)
        baseline_geometry_error = placement_geometry_error(
            placement_index[baseline], baseline_def
        )
        if baseline_geometry_error:
            raise ValueError(
                "invalid placement baseline geometry: %s" % baseline_geometry_error
            )
        slots.append({"case": case, "seed": seed})

        for method in sorted(placement_index):
            if method == baseline:
                continue
            if snapshot is None:
                method_dir = methods_dir / method
                config_path = method_dir / "config.json"
                method_def = placed_def(method_dir)
            else:
                source = snapshot["sources"][method]
                config_path = verified_snapshot_path(
                    source, "config", "config_sha256", "%s config" % method
                )
                method_def = verified_snapshot_path(
                    source, "placed_def", "placed_def_sha256",
                    "%s DEF" % method,
                )
            config = json.loads(config_path.read_text())
            placement = placement_index[method]
            geometry_error = placement_geometry_error(placement, method_def)
            if geometry_error:
                raise ValueError(
                    "invalid placement geometry: %s/%s/%s: %s" % (
                        case, seed, method, geometry_error,
                    )
                )
            activation_error = placement_plugin_activation_error(
                placement, config
            )
            method_hash = sha256(method_def)
            changed = method_hash != baseline_hash
            active = not activation_error
            budget_error = area_budget_runtime_error(placement, config)
            force_budgets = configured_force_budgets(config)
            force_budget_error = force_budget_runtime_error(placement, config)
            row = {
                "case": case,
                "seed": seed,
                "method": method,
                "active": active,
                "changed_from_baseline": changed,
                "activation_error": activation_error,
                "area_budget_configured": bool(int(config.get(
                    "ruplace_enforce_area_adjust_budget", 0
                ))),
                "area_budget_runtime_error": budget_error,
                "force_budget_configured": bool(force_budgets),
                "force_budget_checked_count": len(force_budgets),
                "force_budget_checked_plugins": sorted(force_budgets),
                "force_budget_runtime_error": force_budget_error,
                "placement_geometry_status": "legal",
                "baseline_def_sha256": baseline_hash,
                "method_def_sha256": method_hash,
            }
            rows.append(row)
            if active and not changed:
                active_identical.append(row)
            if budget_error:
                area_budget_errors.append(row)
            if force_budget_error:
                force_budget_errors.append(row)

    if active_identical and not allow_active_identical:
        first = active_identical[0]
        raise ValueError(
            "active plugin emitted the baseline placement: %s/%s/%s" % (
                first["case"], first["seed"], first["method"],
            )
        )
    if area_budget_errors:
        first = area_budget_errors[0]
        raise ValueError(
            "invalid runtime area budget: %s/%s/%s: %s" % (
                first["case"], first["seed"], first["method"],
                first["area_budget_runtime_error"],
            )
        )
    if force_budget_errors:
        first = force_budget_errors[0]
        raise ValueError(
            "invalid runtime force budget: %s/%s/%s: %s" % (
                first["case"], first["seed"], first["method"],
                first["force_budget_runtime_error"],
            )
        )
    return {
        "schema_version": 2,
        "source_provenance": (
            "snapshot_manifest" if snapshot_index is not None else "campaign_tree"
        ),
        "snapshot_manifest_sha256": snapshot_manifest_hash,
        "status": (
            "passed_with_active_identical_candidates_excluded"
            if active_identical else "passed"
        ),
        "contract": (
            "active placements identical to HPWL are recorded for exclusion"
            if allow_active_identical else
            "every active plugin placement differs from HPWL"
        ),
        "baseline": baseline,
        "expected_comparisons": int(expected_comparisons),
        "validated_comparisons": len(comparison_paths),
        "validated_slots": slots,
        "placement_count": len(rows),
        "active_changed_count": sum(
            row["active"] and row["changed_from_baseline"] for row in rows
        ),
        "active_changed_methods": sorted({
            row["method"] for row in rows
            if row["active"] and row["changed_from_baseline"]
        }),
        "active_identical_count": len(active_identical),
        "active_identical_methods": sorted({
            row["method"] for row in active_identical
        }),
        "inactive_identical_count": sum(
            not row["active"] and not row["changed_from_baseline"] for row in rows
        ),
        "inactive_identical_methods": sorted({
            row["method"] for row in rows
            if not row["active"] and not row["changed_from_baseline"]
        }),
        "inactive_changed_count": sum(
            not row["active"] and row["changed_from_baseline"] for row in rows
        ),
        "inactive_changed_methods": sorted({
            row["method"] for row in rows
            if not row["active"] and row["changed_from_baseline"]
        }),
        "inactive_methods": sorted({
            row["method"] for row in rows if not row["active"]
        }),
        "area_budget_checked_count": sum(
            row["area_budget_configured"] for row in rows
        ),
        "force_budget_checked_count": sum(
            row["force_budget_checked_count"] for row in rows
        ),
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--expected-comparisons", type=int, required=True)
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument(
        "--allow-active-identical",
        action="store_true",
        help=(
            "record active candidates identical to HPWL for exclusion instead "
            "of failing the audit"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.expected_comparisons <= 0:
        raise ValueError("expected comparisons must be positive")
    result = audit_placement_effect(
        args.campaign_dir,
        args.expected_comparisons,
        args.baseline,
        allow_active_identical=args.allow_active_identical,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
