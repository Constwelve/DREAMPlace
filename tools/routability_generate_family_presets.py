#!/usr/bin/env python3
"""Generate bounded explicit variants for independent routability families."""

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESETS = ROOT / "configs/routability_plugins/presets.json"
IDENTITY_KEYS = {
    "ruplace_flag", "routability_opt_flag", "ruplace_proxy", "ruplace_plugins",
}
ALLOWED_PROXIES = {
    "gpugr", "xplace", "rudy", "pin_density", "nctugr", "rudy_pin",
}


def slug(value):
    result = re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_").lower()
    if not result:
        raise ValueError("variant name must contain an alphanumeric character")
    return result


def generate_family_presets(base_presets, spec, max_presets=128):
    copied = [str(value) for value in spec.get("copy_presets", ["hpwl"])]
    missing = sorted(set(copied) - set(base_presets))
    if missing:
        raise ValueError("unknown copied presets: %s" % ", ".join(missing))
    if len(copied) != len(set(copied)):
        raise ValueError("copy_presets contains duplicates")

    families = spec.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("families must be a non-empty list")
    family_names = [row.get("plugin") for row in families if isinstance(row, dict)]
    if len(family_names) != len(families) or any(not name for name in family_names):
        raise ValueError("every family must name one plugin")
    if len(family_names) != len(set(family_names)):
        raise ValueError("families contains duplicate plugins")

    shared = spec.get("shared_overrides", {})
    if not isinstance(shared, dict):
        raise ValueError("shared_overrides must be an object")
    forbidden_shared = sorted(set(shared) & IDENTITY_KEYS)
    if forbidden_shared:
        raise ValueError(
            "shared_overrides changes identity keys: %s"
            % ", ".join(forbidden_shared)
        )

    # Copied presets are cross-campaign identities.  In particular, HPWL must
    # remain identical so independently screened survivor bundles can merge.
    output = {name: dict(base_presets[name]) for name in copied}
    generated = {}
    prefix = slug(spec.get("name_prefix", "family"))
    for family_index, family in enumerate(families):
        plugin = family["plugin"]
        if plugin not in base_presets:
            raise ValueError("plugin has no base preset: %s" % plugin)
        base = base_presets[plugin]
        configured_plugins = base.get("ruplace_plugins")
        if configured_plugins != [plugin]:
            raise ValueError("base preset is not atomic: %s" % plugin)
        proxy = str(family.get("proxy", base.get("ruplace_proxy", ""))).lower()
        if proxy not in ALLOWED_PROXIES:
            raise ValueError("unsupported proxy for %s: %s" % (plugin, proxy))
        if plugin == "routeforce" and proxy not in ("gpugr", "xplace"):
            raise ValueError("routeforce requires an in-process GPUGR/Xplace proxy")
        variants = family.get("variants")
        if not isinstance(variants, list) or not variants:
            raise ValueError("%s variants must be a non-empty list" % plugin)
        labels = []
        seen_points = set()
        for variant_index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                raise ValueError("%s variant must be an object" % plugin)
            label = slug(variant.get("name", "variant_%d" % variant_index))
            if label in labels:
                raise ValueError("%s variant names are not unique" % plugin)
            labels.append(label)
            overrides = variant.get("overrides", {})
            if not isinstance(overrides, dict):
                raise ValueError("%s variant overrides must be an object" % plugin)
            forbidden = sorted(set(overrides) & IDENTITY_KEYS)
            if forbidden:
                raise ValueError(
                    "%s variant changes identity keys: %s"
                    % (plugin, ", ".join(forbidden))
                )
            point_key = json.dumps(overrides, sort_keys=True, separators=(",", ":"))
            if point_key in seen_points:
                raise ValueError("%s contains duplicate parameter points" % plugin)
            seen_points.add(point_key)

            name = "%s_%02d_%02d_%s_%s" % (
                prefix, family_index, variant_index, slug(plugin), label,
            )
            config = dict(base)
            config["ruplace_proxy"] = proxy
            config.update(shared)
            config.update(overrides)
            if plugin == "routeforce":
                config["ruplace_external_route_eval"] = 0
            output[name] = config
            generated[name] = {
                "family": plugin,
                "plugins": [plugin],
                "proxy": proxy,
                "variant": label,
                "overrides": overrides,
                "development_only": True,
            }
            if len(generated) > max_presets:
                raise ValueError(
                    "generated preset count exceeds --max-presets=%d" % max_presets
                )
    return output, {
        "schema_version": 1,
        "required_families": family_names,
        "heldout_or_golden_evidence_used": False,
        "numeric_backend_mixing": False,
        "generated": generated,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--base-presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-presets", type=int, default=128)
    args = parser.parse_args(argv)

    presets, manifest = generate_family_presets(
        json.loads(args.base_presets.read_text()),
        json.loads(args.spec.read_text()),
        args.max_presets,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(presets, indent=2, sort_keys=True) + "\n")
    manifest.update({
        "base_presets": str(args.base_presets.resolve()),
        "spec": str(args.spec.resolve()),
    })
    args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
