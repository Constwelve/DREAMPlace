#!/usr/bin/env python3
"""Merge independently screened atomic survivors for pair and held-out stages."""

import argparse
import hashlib
import json
from pathlib import Path


from tools.routability_audit_corrected import audit_strict_selection
from tools.routability_select_survivors import ROUTABILITY_METRIC_PROFILES


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def admission_policy(policy):
    """Return strict admission semantics without the source selection cap."""
    return {
        key: value for key, value in policy.items()
        if key != "max_survivors"
    }


def merge_atomic_survivors(bundles, expected_comparisons=6,
                           metric_profile="absolute_directional_v2"):
    if len(bundles) < 2:
        raise ValueError("atomic survivor merge requires at least two sources")
    output_presets = None
    output_generated = {}
    selected_methods = []
    qualified = []
    source_rows = []
    policy = None
    policy_admission = None
    union_max_survivors = 0
    for selection_path, presets_path, manifest_path in bundles:
        selection = audit_strict_selection(
            selection_path,
            expected_comparisons,
            allow_empty=True,
            required_metric_profile=metric_profile,
        )
        presets = json.loads(Path(presets_path).read_text())
        manifest = json.loads(Path(manifest_path).read_text())
        generated = manifest.get("generated")
        if not isinstance(generated, dict):
            raise ValueError("source preset manifest lacks generated provenance")
        if "hpwl" not in presets:
            raise ValueError("source presets lack HPWL")
        if output_presets is None:
            output_presets = {"hpwl": dict(presets["hpwl"])}
            policy = dict(selection["selection_policy"])
            policy_admission = admission_policy(policy)
        elif presets["hpwl"] != output_presets["hpwl"]:
            raise ValueError("source HPWL presets differ")
        source_policy = selection["selection_policy"]
        if admission_policy(source_policy) != policy_admission:
            raise ValueError("source strict admission policies differ")
        source_max_survivors = source_policy.get("max_survivors")
        if (
            not isinstance(source_max_survivors, int)
            or isinstance(source_max_survivors, bool)
            or source_max_survivors < 1
        ):
            raise ValueError("source selection has invalid survivor cap")
        source_selected = selection["selected_methods"]
        if len(source_selected) > source_max_survivors:
            raise ValueError("source selection exceeds survivor cap")
        union_max_survivors += source_max_survivors

        qualified_by_method = {
            row.get("method"): row for row in selection.get("qualified", [])
        }
        for method in source_selected:
            if method in output_presets:
                raise ValueError("atomic survivor name collision: %s" % method)
            if method not in presets or method not in generated:
                raise ValueError("atomic survivor lacks preset provenance: %s" % method)
            config = presets[method]
            plugins = config.get("ruplace_plugins")
            if not isinstance(plugins, list) or len(plugins) != 1:
                raise ValueError("survivor is not atomic: %s" % method)
            record = qualified_by_method.get(method)
            if record is None:
                raise ValueError("selected survivor lacks qualified metrics: %s" % method)
            output_presets[method] = dict(config)
            provenance = dict(generated[method])
            provenance.update({
                "copied_atomic_survivor": True,
                "development_only": True,
                "source_selection": str(Path(selection_path).resolve()),
            })
            output_generated[method] = provenance
            selected_methods.append(method)
            qualified.append(record)
        source_rows.append({
            "selection": str(Path(selection_path).resolve()),
            "selection_sha256": sha256(selection_path),
            "presets": str(Path(presets_path).resolve()),
            "presets_sha256": sha256(presets_path),
            "manifest": str(Path(manifest_path).resolve()),
            "manifest_sha256": sha256(manifest_path),
            "max_survivors": source_max_survivors,
            "selected_methods": source_selected,
        })

    policy["max_survivors"] = union_max_survivors
    merged_selection = {
        "schema_version": 1,
        "baseline": "hpwl",
        "expected_comparisons": expected_comparisons,
        "selection_policy": policy,
        "qualified": qualified,
        "excluded": [],
        "pareto_frontier": selected_methods,
        "selected_methods": selected_methods,
        "admission_union": {
            "development_only": True,
            "heldout_or_golden_evidence_used": False,
            "numeric_backend_mixing": False,
            "source_max_survivors": [
                row["max_survivors"] for row in source_rows
            ],
            "union_max_survivors": union_max_survivors,
            "sources": source_rows,
        },
    }
    merged_manifest = {
        "schema_version": 1,
        "generated": output_generated,
        "metadata": {
            "development_only": True,
            "heldout_or_golden_evidence_used": False,
            "numeric_backend_mixing": False,
            "atomic_survivors": selected_methods,
            "source_count": len(source_rows),
        },
    }
    return output_presets, merged_manifest, merged_selection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle", action="append", required=True,
        help="selection.json,presets.json,presets.json.manifest.json",
    )
    parser.add_argument("--output-presets", type=Path, required=True)
    parser.add_argument("--output-selection", type=Path, required=True)
    parser.add_argument("--expected-comparisons", type=int, default=6)
    parser.add_argument(
        "--metric-profile",
        choices=tuple(sorted(ROUTABILITY_METRIC_PROFILES)),
        default="absolute_directional_v2",
    )
    args = parser.parse_args(argv)
    bundles = []
    for value in args.bundle:
        parts = value.split(",", 2)
        if len(parts) != 3:
            parser.error("--bundle must contain selection,presets,manifest")
        bundles.append(tuple(Path(part) for part in parts))
    presets, manifest, selection = merge_atomic_survivors(
        bundles, args.expected_comparisons, args.metric_profile
    )
    args.output_presets.parent.mkdir(parents=True, exist_ok=True)
    args.output_selection.parent.mkdir(parents=True, exist_ok=True)
    args.output_presets.write_text(json.dumps(presets, indent=2, sort_keys=True) + "\n")
    args.output_presets.with_suffix(
        args.output_presets.suffix + ".manifest.json"
    ).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    args.output_selection.write_text(
        json.dumps(selection, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
