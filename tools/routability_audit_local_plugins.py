#!/usr/bin/env python3
"""Audit terminal development pilots for local-only routability plugins."""

import argparse
import datetime
import json
import math
from pathlib import Path


from tools.routability_audit_corrected import (
    audit_strict_selection,
    canonical_json_sha256,
    metric_delta,
    read_status,
    sha256,
)


EXPECTED_TERMINAL_PILOTS = {
    "connection_routeforce": ("v35", 7),
    "projected_connection_routeforce": ("v40", 9),
    "routed_overflow_net_contraction": ("v53", 7),
    "net_relaxation": ("v59", 6),
    "directional_net_contraction": ("v63", 8),
    "directional_path_spreading": ("v67", 5),
    "virtual_cell": ("v69", 12),
    "directional_virtual_cell": ("v71", 18),
}
EVIDENCE_NAMES = {
    "status": "HANDOFF_STATUS.md",
    "presets": "presets.json",
    "manifest": "presets.json.manifest.json",
    "pilot_audit": "pilot_audit.json",
    "selection": "summary/pilot_survivors.json",
    "near_misses": "summary/near_misses.json",
    "placement_effect": "summary/placement_effect_audit.json",
    "screening_summary": "summary/screening_summary.json",
    "screening_raw": "summary/screening_raw.csv",
    "parallel_status": "campaign/parallel_status.json",
}


def load_json(path):
    return json.loads(Path(path).read_text())


def parse_pilot_spec(spec):
    parts = spec.split("=", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError("pilot must be plugin=terminal_version=root")
    return parts[0], parts[1], Path(parts[2])


def evidence_root(root):
    candidates = [root, root / "pilot"]
    matches = [path for path in candidates if (path / "pilot_audit.json").is_file()]
    if len(matches) != 1:
        raise ValueError("pilot root has ambiguous or missing terminal evidence: %s" % root)
    return matches[0]


def strict_candidate_passes(record, policy, expected_comparisons):
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("candidate lacks metric records")
    primary = policy["primary_objectives"]
    guarded_backends = set(policy["worst_regression_backends"])
    blockers = []
    for name in primary:
        metric = metrics.get(name)
        if not isinstance(metric, dict):
            raise ValueError("candidate lacks primary metric %s" % name)
        if metric.get("valid_count") != expected_comparisons:
            raise ValueError("candidate primary metric coverage mismatch: %s" % name)
        worst, _unit = metric_delta(metric, "worst")
        if not math.isfinite(worst):
            raise ValueError("candidate primary metric is not finite: %s" % name)
        backend = name.split(":", 1)[0]
        if (
            backend in guarded_backends
            and worst > policy["max_primary_worst_regression"]
        ):
            blockers.append("worst_regression:%s" % name)

    for backend, constraint in policy["backend_improvement_constraints"].items():
        improvements = 0
        for metric_name in constraint["metrics"]:
            name = "%s:%s" % (backend, metric_name)
            metric = metrics.get(name)
            if not isinstance(metric, dict):
                raise ValueError("candidate lacks backend metric %s" % name)
            prefix = "median" if name == "rudy:overflow_sum" else "mean"
            value, _unit = metric_delta(metric, prefix)
            if not math.isfinite(value):
                raise ValueError("candidate backend metric is not finite: %s" % name)
            improvements += value < 0.0
        if improvements < constraint["minimum_improvements"]:
            blockers.append("no_improvement:%s" % backend)
    return not blockers, blockers


def audit_terminal_pilot(plugin, version, root):
    expected_version, expected_candidates = EXPECTED_TERMINAL_PILOTS[plugin]
    if version != expected_version:
        raise ValueError("terminal version mismatch for %s" % plugin)
    root = root.resolve()
    terminal = evidence_root(root)
    paths = {
        name: (root if name in ("status", "presets", "manifest") else terminal) / rel
        for name, rel in EVIDENCE_NAMES.items()
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError("terminal pilot lacks evidence: %s" % ", ".join(missing))

    status = read_status(paths["status"])
    if not status.get("phase", "").startswith("completed_"):
        raise ValueError("terminal pilot status is not complete")
    if status.get("metric_profile") != "absolute_directional_v2":
        raise ValueError("terminal pilot status has wrong metric profile")
    if set(status.get("evaluators", "").split(",")) != {"rudy", "gpugr"}:
        raise ValueError("terminal pilot did not use separate RUDY and GPUGR evaluators")
    if "development_only" not in status.get("scope", ""):
        raise ValueError("terminal pilot status is not development-only")

    presets = load_json(paths["presets"])
    manifest = load_json(paths["manifest"])
    generated = manifest.get("generated")
    metadata = manifest.get("metadata", {})
    if not isinstance(generated, dict) or len(generated) != expected_candidates:
        raise ValueError("terminal pilot manifest candidate count mismatch")
    if set(presets) != {"hpwl"} | set(generated):
        raise ValueError("terminal pilot preset and manifest methods differ")
    if (
        metadata.get("generated_count") != expected_candidates
        or metadata.get("development_only") is not True
        or metadata.get("heldout_or_golden_evidence_used") is not False
        or metadata.get("numeric_backend_mixing") is not False
    ):
        raise ValueError("terminal pilot manifest violates development policy")
    feedback_proxies = set()
    for method, provenance in generated.items():
        config = presets[method]
        feedback_proxy = config.get("ruplace_proxy")
        if (
            provenance.get("plugins") != [plugin]
            or provenance.get("development_only") is not True
            or provenance.get("proxy") != feedback_proxy
            or config.get("ruplace_plugins") != [plugin]
            or feedback_proxy not in ("rudy", "gpugr")
        ):
            raise ValueError("invalid terminal method provenance: %s" % method)
        feedback_proxies.add(feedback_proxy)

    selection = audit_strict_selection(
        paths["selection"], 1, allow_empty=True,
        required_metric_profile="absolute_directional_v2",
    )
    if (
        selection.get("selected_methods")
        or selection.get("qualified")
        or selection.get("pareto_frontier")
    ):
        raise ValueError("terminal pilot has a strict survivor")
    excluded = selection.get("excluded")
    if not isinstance(excluded, list) or {
        row.get("method") for row in excluded if isinstance(row, dict)
    } != set(generated):
        raise ValueError("terminal pilot rejection coverage mismatch")
    rejection_counts = {}
    for row in excluded:
        if row.get("is_atomic_plugin") is not True:
            raise ValueError("terminal pilot contains a non-atomic candidate")
        passes, blockers = strict_candidate_passes(
            row, selection["selection_policy"], 1
        )
        if passes:
            raise ValueError("excluded candidate satisfies the strict proxy gate")
        for blocker in blockers:
            rejection_counts[blocker] = rejection_counts.get(blocker, 0) + 1

    pilot_audit = load_json(paths["pilot_audit"])
    selected_fields = [
        pilot_audit[name] for name in (
            "selected_in_stage_only", "selected_in_pilot_only"
        ) if name in pilot_audit
    ]
    if (
        pilot_audit.get("status") != "passed"
        or pilot_audit.get("candidate_count") != expected_candidates
        or pilot_audit.get("scope") != "development_only_test1_seed1000"
        or pilot_audit.get("heldout_or_golden_evidence_used") is not False
        or pilot_audit.get("numeric_backend_mixing") is not False
        or pilot_audit.get("selection_or_final_admission_decision") is not False
        or len(selected_fields) != 1
        or selected_fields[0] != []
    ):
        raise ValueError("terminal pilot runtime audit violates policy")
    for backend in ("rudy", "gpugr"):
        count = pilot_audit.get(backend + "_result_count")
        if count is not None and count != expected_candidates + 1:
            raise ValueError("terminal pilot %s result count mismatch" % backend)
    gpugr_hash = pilot_audit.get("gpugr_binary_sha256")
    if not isinstance(gpugr_hash, str) or len(gpugr_hash) != 64:
        raise ValueError("terminal pilot lacks GPUGR binary identity")

    effect = load_json(paths["placement_effect"])
    activity_count = sum(
        int(effect.get(name, -expected_candidates * 10))
        for name in (
            "active_changed_count", "active_identical_count",
            "inactive_changed_count", "inactive_identical_count",
        )
    )
    if (
        effect.get("status") not in {
            "passed", "passed_with_active_identical_candidates_excluded"
        }
        or effect.get("expected_comparisons") != 1
        or effect.get("validated_comparisons") != 1
        or effect.get("placement_count") != expected_candidates
        or activity_count != expected_candidates
    ):
        raise ValueError("terminal pilot placement-effect audit mismatch")

    near = load_json(paths["near_misses"])
    near_policy = near.get("policy", {})
    if (
        near.get("expected_comparisons") != 1
        or near_policy.get("metric_profile") != "absolute_directional_v2"
        or near_policy.get("numeric_backend_mixing") is not False
        or near_policy.get("selection_or_admission_decision") is not False
        or near_policy.get("complete_campaign_required") is not True
    ):
        raise ValueError("terminal pilot near-miss policy mismatch")

    screening = load_json(paths["screening_summary"])
    if (
        screening.get("expected_comparisons") != 1
        or screening.get("validated_comparisons") != 1
        or screening.get("missing_comparisons")
        or screening.get("incomplete_jobs")
    ):
        raise ValueError("terminal pilot screening matrix is incomplete")
    parallel = load_json(paths["parallel_status"])
    jobs = parallel.get("jobs")
    if (
        not isinstance(jobs, list) or len(jobs) != 1
        or jobs[0].get("status") != "completed"
        or jobs[0].get("returncode") != 0
        or jobs[0].get("case") != "data_ispd19_test1"
        or jobs[0].get("seed") != 1000
    ):
        raise ValueError("terminal pilot parallel job did not complete")

    plugin_path = (
        root / "python_install/dreamplace/ops/routability_opt/plugins"
        / (plugin + ".py")
    )
    if not plugin_path.is_file():
        raise ValueError("terminal pilot lacks evaluated plugin source")
    return {
        "terminal_version": version,
        "root": str(root),
        "evidence_root": str(terminal),
        "candidate_count": expected_candidates,
        "selected_methods": [],
        "strict_recomputed_survivor_count": 0,
        "metric_profile": "absolute_directional_v2",
        "validators": ["gpugr", "rudy"],
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "feedback_proxies": sorted(feedback_proxies),
        "placement_effect_status": effect["status"],
        "placement_activity": {
            name: effect[name] for name in (
                "active_changed_count", "active_identical_count",
                "inactive_changed_count", "inactive_identical_count",
            )
        },
        "rejection_blocker_counts": dict(sorted(rejection_counts.items())),
        "gpugr_binary_sha256": gpugr_hash,
        "terminal_evaluated_plugin_sha256": sha256(plugin_path),
        "selection_content_sha256": canonical_json_sha256(selection),
        "evidence_sha256": {
            name: sha256(path) for name, path in sorted(paths.items())
        },
    }


def audit_local_plugins(pilot_specs, source_dir):
    parsed = [parse_pilot_spec(spec) for spec in pilot_specs]
    supplied = [plugin for plugin, _version, _root in parsed]
    if len(supplied) != len(set(supplied)) or set(supplied) != set(
        EXPECTED_TERMINAL_PILOTS
    ):
        raise ValueError("terminal pilot plugin coverage mismatch")
    pilots = {
        plugin: audit_terminal_pilot(plugin, version, root)
        for plugin, version, root in parsed
    }
    gpugr_hashes = {row["gpugr_binary_sha256"] for row in pilots.values()}
    if len(gpugr_hashes) != 1:
        raise ValueError("terminal pilots used different GPUGR binaries")

    source_dir = Path(source_dir).resolve()
    for plugin, row in pilots.items():
        current = source_dir / (plugin + ".py")
        if not current.is_file():
            raise ValueError("current plugin source is missing: %s" % plugin)
        current_hash = sha256(current)
        if row["terminal_evaluated_plugin_sha256"] != current_hash:
            raise ValueError(
                "terminal pilot did not evaluate current source: %s" % plugin
            )
        row["current_source_sha256"] = current_hash
        row["current_source_snapshot_witnesses"] = [plugin]
        row["terminal_source_matches_current"] = True

    return {
        "schema_version": 1,
        "status": "passed",
        "stage": "local_plugin_terminal_pilots",
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "conclusion": "no_strict_local_plugin_survivor",
        "metric_profile": "absolute_directional_v2",
        "validators": ["gpugr", "rudy"],
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "selected_methods": [],
        "terminal_versions": {
            plugin: version
            for plugin, (version, _count) in EXPECTED_TERMINAL_PILOTS.items()
        },
        "source_dir": str(source_dir),
        "gpugr_binary_sha256": next(iter(gpugr_hashes)),
        "plugins": dict(sorted(pilots.items())),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pilot", action="append", required=True,
        help="plugin=terminal_version=root",
    )
    parser.add_argument(
        "--source-dir", type=Path,
        default=Path("dreamplace/ops/routability_opt/plugins"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_local_plugins(args.pilot, args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
