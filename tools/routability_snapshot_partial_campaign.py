#!/usr/bin/env python3
"""Freeze the common completed prefix of an active proxy campaign."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_compare import (
    find_placed_def,
    parse_placement_metrics,
    parse_plugin_summaries,
    placement_output_name,
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_identity(methods_dir, campaign_dir):
    relative = methods_dir.relative_to(campaign_dir).parts
    seed_index = next(
        (index for index, part in enumerate(relative) if part.startswith("seed_")),
        None,
    )
    if seed_index is None or seed_index == 0:
        raise ValueError("cannot infer case and seed from %s" % methods_dir)
    return relative[seed_index - 1], int(relative[seed_index][len("seed_"):])


def completed_methods(methods_dir, evaluators):
    completed = set()
    for summary in methods_dir.glob("*/evaluation/summary.json"):
        method_dir = summary.parent.parent
        if not (method_dir / "config.json").is_file():
            continue
        if not (method_dir / "placement.log").is_file():
            continue
        if not (method_dir / "placement_provenance.json").is_file():
            continue
        try:
            results = json.loads(summary.read_text()).get("results", [])
        except json.JSONDecodeError:
            continue
        by_backend = {row.get("backend"): row for row in results}
        if set(by_backend) != set(evaluators):
            continue
        if any(
            by_backend[backend].get("status") != "ok"
            for backend in evaluators
        ):
            continue
        completed.add(method_dir.name)
    return completed


def placement_record(method_dir):
    config = json.loads((method_dir / "config.json").read_text())
    log_path = method_dir / "placement.log"
    text = log_path.read_text(errors="replace")
    metrics = parse_placement_metrics(text)
    if "placement_hpwl" not in metrics:
        raise ValueError("placement log lacks final HPWL: %s" % log_path)
    placed_def = find_placed_def(
        method_dir / "placement", placement_output_name(config)
    )
    provenance_path = method_dir / "placement_provenance.json"
    if not provenance_path.is_file():
        raise ValueError(
            "completed method lacks placement provenance: %s" % method_dir
        )
    provenance = json.loads(provenance_path.read_text())
    if provenance.get("schema_version") != 1:
        raise ValueError(
            "unsupported placement provenance schema: %s" % provenance_path
        )
    if provenance.get("method") != method_dir.name:
        raise ValueError(
            "placement provenance method mismatch: %s" % provenance_path
        )
    config_path = (method_dir / "config.json").resolve()
    placed_def = placed_def.resolve()
    if (
        Path(provenance.get("config", "")).resolve() != config_path
        or provenance.get("config_sha256") != sha256(config_path)
    ):
        raise ValueError(
            "placement provenance config mismatch: %s" % provenance_path
        )
    if (
        Path(provenance.get("placed_def", "")).resolve() != placed_def
        or provenance.get("placed_def_sha256") != sha256(placed_def)
    ):
        raise ValueError(
            "placement provenance DEF mismatch: %s" % provenance_path
        )
    geometry = provenance.get("placement_geometry_provenance")
    if (
        not isinstance(geometry, dict)
        or geometry.get("def_sha256") != provenance["placed_def_sha256"]
    ):
        raise ValueError(
            "placement provenance geometry mismatch: %s" % provenance_path
        )
    required = (
        "placement_input_provenance",
        "placement_implementation_provenance",
        "placement_runtime_provenance",
    )
    if any(not isinstance(provenance.get(key), dict) for key in required):
        raise ValueError(
            "placement provenance lacks global provenance: %s" % provenance_path
        )
    plugin = parse_plugin_summaries(text)
    return {
        "method": method_dir.name,
        "evaluator": "placement",
        "validation_role": "placement_metric",
        "authoritative_for_comparison": False,
        "status": "ok",
        "runtime_sec": 0.0,
        "error": "",
        **metrics,
        **plugin,
        "placed_def": str(placed_def),
        "placed_def_sha256": provenance["placed_def_sha256"],
        "placement_geometry_provenance": geometry,
    }, {
        "config": str(config_path),
        "config_sha256": sha256(config_path),
        "placement_log": str(log_path.resolve()),
        "placement_log_sha256": sha256(log_path),
        "placed_def": str(placed_def),
        "placed_def_sha256": sha256(placed_def),
        "placement_provenance": str(provenance_path.resolve()),
        "placement_provenance_sha256": sha256(provenance_path),
    }, {key: provenance[key] for key in required}


def evaluation_records(method_dir, evaluators):
    summary = method_dir / "evaluation" / "summary.json"
    results = json.loads(summary.read_text()).get("results", [])
    by_backend = {row["backend"]: row for row in results}
    return [
        {
            "method": method_dir.name,
            **by_backend[backend],
            "validation_role": "fallback_reference",
            "authoritative_for_comparison": True,
        }
        for backend in evaluators
    ], {
        "evaluation_summary": str(summary.resolve()),
        "evaluation_summary_sha256": sha256(summary),
    }


def snapshot_partial_campaign(campaign_dir, presets, output_dir,
                              expected_comparisons=6,
                              evaluators=("rudy", "gpugr"),
                              completed_comparisons_only=False):
    campaign_dir = campaign_dir.resolve()
    all_methods_dirs = sorted(campaign_dir.glob("*/seed_*/*/methods"))
    all_identities = [
        source_identity(path, campaign_dir) for path in all_methods_dirs
    ]
    if len(all_methods_dirs) != expected_comparisons:
        raise ValueError(
            "expected %d comparison directories, found %d"
            % (expected_comparisons, len(all_methods_dirs))
        )
    if len(all_identities) != len(set(all_identities)):
        raise ValueError("campaign contains duplicate case/seed comparisons")
    all_completed = [
        completed_methods(path, evaluators) for path in all_methods_dirs
    ]
    entries = list(zip(all_methods_dirs, all_identities, all_completed))
    if completed_comparisons_only:
        candidates = set(presets) - {"hpwl"}
        entries = [
            entry for entry in entries
            if "hpwl" in entry[2] and candidates.intersection(entry[2])
        ]
        if not entries:
            raise ValueError(
                "no comparison has a completed hpwl baseline and candidate"
            )
    methods_dirs = [entry[0] for entry in entries]
    identities = [entry[1] for entry in entries]
    completed = [entry[2] for entry in entries]
    common = set.intersection(*completed)
    if "hpwl" not in common:
        raise ValueError("common completed methods lack the hpwl baseline")
    method_order = ["hpwl"] + [
        method for method in presets if method in common and method != "hpwl"
    ]
    if len(method_order) < 2:
        raise ValueError("no completed candidate is common to every comparison")
    unknown = common - set(presets)
    if unknown:
        raise ValueError("completed methods lack presets: %s" % sorted(unknown))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("snapshot output directory is not empty: %s" % output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_campaign": str(campaign_dir),
        "evaluators": list(evaluators),
        "expected_comparisons": expected_comparisons,
        "completed_comparisons_only": completed_comparisons_only,
        "selected_methods": method_order,
        "omitted_comparisons": [
            {"case": case, "seed": seed}
            for case, seed in all_identities if (case, seed) not in set(identities)
        ],
        "comparisons": [],
    }
    completed_status = {}
    for methods_dir, (case, seed) in zip(methods_dirs, identities):
        placements = []
        results = []
        sources = []
        comparison_provenance = None
        for method in method_order:
            method_dir = methods_dir / method
            placement, placement_source, provenance = placement_record(method_dir)
            if comparison_provenance is None:
                comparison_provenance = provenance
            elif provenance != comparison_provenance:
                raise ValueError(
                    "placement provenance differs within comparison: %s"
                    % methods_dir
                )
            evaluations, evaluation_source = evaluation_records(
                method_dir, evaluators
            )
            placements.append(placement)
            results.extend(evaluations)
            sources.append({
                "method": method,
                **placement_source,
                **evaluation_source,
            })
        destination = output_dir / case / ("seed_%d" % seed) / case / "methods"
        destination.mkdir(parents=True, exist_ok=True)
        comparison = destination / "comparison.json"
        comparison.write_text(json.dumps({
            "validation": {
                "status": "validated",
                "snapshot_partial_campaign": True,
                "mandatory_proxy_gate": {
                    "status": "passed",
                    "requested_evaluators": list(evaluators),
                },
            },
            "snapshot_provenance": {
                "source_methods_dir": str(methods_dir.resolve()),
                "selected_methods": method_order,
            },
            **comparison_provenance,
            "placements": placements,
            "results": results,
        }, indent=2, sort_keys=True) + "\n")
        manifest["comparisons"].append({
            "case": case,
            "seed": seed,
            "comparison": str(comparison.resolve()),
            "comparison_sha256": sha256(comparison),
            "sources": sources,
        })
        completed_status[(case, seed)] = {
            "case": case,
            "seed": seed,
            "status": "completed",
            "returncode": 0,
            "snapshot_partial_campaign": True,
        }
    status_jobs = [
        completed_status.get((case, seed), {
            "case": case,
            "seed": seed,
            "status": "running",
            "returncode": "",
            "snapshot_partial_campaign": False,
        })
        for case, seed in all_identities
    ]
    (output_dir / "parallel_status.json").write_text(json.dumps({
        "jobs": status_jobs,
        "snapshot_partial_campaign": True,
        "source_campaign": str(campaign_dir),
    }, indent=2, sort_keys=True) + "\n")
    (output_dir / "snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-comparisons", type=int, default=6)
    parser.add_argument("--evaluators", default="rudy,gpugr")
    parser.add_argument("--completed-comparisons-only", action="store_true")
    args = parser.parse_args(argv)
    evaluators = tuple(
        value.strip() for value in args.evaluators.split(",") if value.strip()
    )
    if not evaluators:
        parser.error("--evaluators must not be empty")
    snapshot_partial_campaign(
        args.campaign_dir,
        json.loads(args.presets.read_text()),
        args.output_dir,
        expected_comparisons=args.expected_comparisons,
        evaluators=evaluators,
        completed_comparisons_only=args.completed_comparisons_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
