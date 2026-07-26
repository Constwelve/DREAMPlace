#!/usr/bin/env python3
"""Freeze selector-approved methods from one or more preset sources."""

import argparse
import json
from pathlib import Path


def load_selected_methods(paths):
    selected = []
    for path in paths:
        data = json.loads(path.read_text())
        methods = data.get("selected_methods")
        if not isinstance(methods, list):
            raise ValueError("selection lacks selected_methods: %s" % path)
        for method in methods:
            method = str(method)
            if method not in selected:
                selected.append(method)
    return selected


def load_presets(paths):
    presets = {}
    origins = {}
    for path in paths:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("preset source must be an object: %s" % path)
        for method, config in data.items():
            if method in presets and presets[method] != config:
                raise ValueError(
                    "conflicting preset definitions for %s in %s and %s"
                    % (method, origins[method], path)
                )
            presets[method] = config
            origins.setdefault(method, str(path.resolve()))
    return presets, origins


def freeze_presets(preset_paths, selection_paths, baseline="hpwl"):
    presets, origins = load_presets(preset_paths)
    selected = load_selected_methods(selection_paths)
    methods = [baseline] + [method for method in selected if method != baseline]
    missing = [method for method in methods if method not in presets]
    if missing:
        raise ValueError("selected methods missing from presets: %s" % ", ".join(missing))
    frozen = {method: presets[method] for method in methods}
    provenance = {
        "baseline": baseline,
        "preset_sources": [str(path.resolve()) for path in preset_paths],
        "selections": [str(path.resolve()) for path in selection_paths],
        "methods": [
            {"method": method, "source": origins[method]} for method in methods
        ],
    }
    return frozen, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset-source", type=Path, action="append", required=True)
    parser.add_argument("--selection", type=Path, action="append", required=True)
    parser.add_argument("--baseline", default="hpwl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    frozen, provenance = freeze_presets(
        args.preset_source, args.selection, baseline=args.baseline
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(args.output.suffix + ".provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
