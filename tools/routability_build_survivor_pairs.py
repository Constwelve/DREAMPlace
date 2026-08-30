#!/usr/bin/env python3
"""Build compatible atomic-survivor pairs without changing shared controls."""

import argparse
from itertools import combinations
import json
from pathlib import Path


IDENTITY_KEYS = {
    "ruplace_flag", "routability_opt_flag", "ruplace_proxy", "ruplace_plugins",
}


def _strict_selection(selection):
    policy = selection.get("selection_policy", {})
    return (
        policy.get("name") == "routability_first"
        and policy.get("numeric_backend_mixing") is False
        and policy.get("max_primary_worst_regression") == 0.0
        and all(
            policy.get("backend_improvement_constraints", {})
            .get(backend, {}).get("minimum_improvements") == 1
            for backend in ("gpugr", "rudy")
        )
    )


def _merge_pair(left_name, right_name, presets):
    left = presets[left_name]
    right = presets[right_name]
    left_plugins = list(left.get("ruplace_plugins", []))
    right_plugins = list(right.get("ruplace_plugins", []))
    if len(left_plugins) != 1 or len(right_plugins) != 1:
        return None, ["parents must be atomic plugins"]
    if left_plugins[0] == right_plugins[0]:
        return None, ["parents use the same plugin"]
    if left.get("ruplace_proxy") != right.get("ruplace_proxy"):
        return None, ["parents use different proxies"]
    conflicts = []
    for key in sorted((set(left) & set(right)) - IDENTITY_KEYS):
        if left[key] != right[key]:
            conflicts.append("%s differs" % key)
    if conflicts:
        return None, conflicts
    merged = dict(left)
    merged.update(right)
    merged["ruplace_flag"] = 1
    merged["routability_opt_flag"] = 1
    merged["ruplace_proxy"] = left["ruplace_proxy"]
    merged["ruplace_plugins"] = left_plugins + right_plugins
    return merged, []


def build_survivor_pairs(selection, presets, manifest):
    if not _strict_selection(selection):
        raise ValueError("selection does not satisfy the strict proxy policy")
    selected = list(selection.get("selected_methods", []))
    if len(selected) < 2:
        raise ValueError("fewer than two strict atomic survivors")
    generated_source = manifest.get("generated", {})
    missing = sorted(
        method for method in selected
        if method not in presets or method not in generated_source
    )
    if missing:
        raise ValueError("selected methods lack preset provenance: %s" % ", ".join(missing))
    output = {"hpwl": dict(presets["hpwl"])}
    generated = {}
    atomic = []
    for method in selected:
        config = presets[method]
        plugins = list(config.get("ruplace_plugins", []))
        if len(plugins) != 1:
            raise ValueError("selected method is not atomic: %s" % method)
        output[method] = dict(config)
        provenance = dict(generated_source[method])
        provenance.update({
            "copied_atomic_survivor": True,
            "development_only": True,
        })
        generated[method] = provenance
        atomic.append(method)

    pair_methods = []
    incompatible = []
    pair_index = 0
    for left, right in combinations(selected, 2):
        merged, reasons = _merge_pair(left, right, presets)
        if merged is None:
            incompatible.append({
                "parents": [left, right],
                "reasons": reasons,
            })
            continue
        plugins = merged["ruplace_plugins"]
        name = "survivor_pair_%04d_%s_%s__%s" % (
            pair_index, merged["ruplace_proxy"], plugins[0], plugins[1]
        )
        output[name] = merged
        generated[name] = {
            "plugins": plugins,
            "proxy": merged["ruplace_proxy"],
            "parents": [left, right],
            "compatible_shared_configuration": True,
            "development_only": True,
        }
        pair_methods.append(name)
        pair_index += 1
    metadata = {
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "source_atomic_survivors": atomic,
        "pair_methods": pair_methods,
        "incompatible_pairs": incompatible,
        "pair_count": len(pair_methods),
    }
    return output, generated, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--preset-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    presets, generated, metadata = build_survivor_pairs(
        json.loads(args.selection.read_text()),
        json.loads(args.presets.read_text()),
        json.loads(args.preset_manifest.read_text()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(presets, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(
        json.dumps({
            "selection": str(args.selection.resolve()),
            "source_presets": str(args.presets.resolve()),
            "source_manifest": str(args.preset_manifest.resolve()),
            "metadata": metadata,
            "generated": generated,
        }, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
