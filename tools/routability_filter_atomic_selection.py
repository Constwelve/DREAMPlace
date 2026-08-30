#!/usr/bin/env python3
"""Filter invalidated plugins from an audited atomic development selection."""

import argparse
import hashlib
import json
from pathlib import Path

from tools.routability_audit_corrected import audit_strict_selection
from tools.routability_select_survivors import ROUTABILITY_METRIC_PROFILES


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def filter_atomic_selection(selection, presets, generated, excluded_plugins):
    excluded_plugins = set(excluded_plugins)
    if not excluded_plugins:
        raise ValueError("at least one excluded plugin is required")
    selected = selection["selected_methods"]
    kept = []
    removed = []
    for method in selected:
        if method not in presets or method not in generated:
            raise ValueError("selected method lacks preset provenance: %s" % method)
        plugins = presets[method].get("ruplace_plugins")
        provenance_plugins = generated[method].get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1:
            raise ValueError("selected method is not atomic: %s" % method)
        if provenance_plugins != plugins:
            raise ValueError("selected method plugin provenance differs: %s" % method)
        if excluded_plugins.intersection(plugins):
            removed.append(method)
        else:
            kept.append(method)

    qualified_by_method = {
        row.get("method"): row for row in selection.get("qualified", [])
    }
    result = dict(selection)
    result["selected_methods"] = kept
    result["pareto_frontier"] = kept
    result["qualified"] = [qualified_by_method[method] for method in kept]
    result["combination_plugins"] = [
        presets[method]["ruplace_plugins"][0] for method in kept
    ]
    result["combination_plugin_grids"] = {}
    result["filter_policy"] = {
        "development_only": True,
        "reason": "implementation_lifecycle_invalidated_prior_evidence",
        "excluded_plugins": sorted(excluded_plugins),
        "removed_methods": removed,
        "kept_methods": kept,
        "heldout_or_golden_evidence_used": False,
        "numeric_backend_mixing": False,
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--preset-manifest", type=Path, required=True)
    parser.add_argument("--exclude-plugin", action="append", required=True)
    parser.add_argument("--expected-comparisons", type=int, default=6)
    parser.add_argument(
        "--metric-profile",
        choices=tuple(sorted(ROUTABILITY_METRIC_PROFILES)),
        default="absolute_directional_v2",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    selection = audit_strict_selection(
        args.selection,
        args.expected_comparisons,
        allow_empty=True,
        required_metric_profile=args.metric_profile,
    )
    presets = json.loads(args.presets.read_text())
    manifest = json.loads(args.preset_manifest.read_text())
    generated = manifest.get("generated")
    if not isinstance(generated, dict):
        raise ValueError("preset manifest lacks generated provenance")
    result = filter_atomic_selection(
        selection, presets, generated, args.exclude_plugin
    )
    result["filter_policy"].update({
        "source_selection": str(args.selection.resolve()),
        "source_selection_sha256": sha256(args.selection),
        "source_presets": str(args.presets.resolve()),
        "source_presets_sha256": sha256(args.presets),
        "source_manifest": str(args.preset_manifest.resolve()),
        "source_manifest_sha256": sha256(args.preset_manifest),
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    audit_strict_selection(
        args.output,
        args.expected_comparisons,
        allow_empty=True,
        required_metric_profile=args.metric_profile,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
