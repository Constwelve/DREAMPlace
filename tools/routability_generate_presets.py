#!/usr/bin/env python3
"""Generate deterministic routability plugin-combination sweep presets."""

import argparse
from itertools import combinations, product
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESETS = ROOT / "configs/routability_plugins/presets.json"


def as_list(value, name):
    if not isinstance(value, list) or not value:
        raise ValueError("%s must be a non-empty list" % name)
    return value


def known_plugins(presets):
    return {
        plugin
        for preset in presets.values()
        for plugin in preset.get("ruplace_plugins", [])
    }


def grid_points(grid):
    if not grid:
        return [dict()]
    keys = sorted(grid)
    values = [as_list(grid[key], "grid.%s" % key) for key in keys]
    return [dict(zip(keys, point)) for point in product(*values)]


def generate_presets(base_presets, spec, max_presets=256):
    plugins = [str(value) for value in as_list(spec.get("plugins"), "plugins")]
    if len(plugins) != len(set(plugins)):
        raise ValueError("plugins contains duplicates")
    unknown = sorted(set(plugins) - known_plugins(base_presets))
    if unknown:
        raise ValueError("unknown plugins: %s" % ", ".join(unknown))

    sizes = [int(value) for value in as_list(
        spec.get("combination_sizes"), "combination_sizes"
    )]
    if any(size < 2 or size > len(plugins) for size in sizes):
        raise ValueError("combination sizes must be between 2 and plugin count")
    proxies = [str(value).lower() for value in as_list(spec.get("proxies"), "proxies")]
    if len(proxies) != len(set(proxies)):
        raise ValueError("proxies contains duplicates")
    allowed_proxies = {"gpugr", "xplace", "rudy", "pin_density", "nctugr", "rudy_pin"}
    unknown_proxies = sorted(set(proxies) - allowed_proxies)
    if unknown_proxies:
        raise ValueError("unknown proxies: %s" % ", ".join(unknown_proxies))

    copied = [str(value) for value in spec.get("copy_presets", ["hpwl"])]
    missing = sorted(set(copied) - set(base_presets))
    if missing:
        raise ValueError("unknown copied presets: %s" % ", ".join(missing))
    result = {name: dict(base_presets[name]) for name in copied}
    manifest = {}
    shared = dict(spec.get("shared_overrides", {}))
    grid = dict(spec.get("grid", {}))
    reserved = {
        "ruplace_flag", "routability_opt_flag", "ruplace_proxy", "ruplace_plugins",
    }
    overridden = sorted((set(shared) | set(grid)) & reserved)
    if overridden:
        raise ValueError(
            "combination identity keys cannot be overridden: %s"
            % ", ".join(overridden)
        )
    points = grid_points(grid)
    prefix = str(spec.get("name_prefix", "combo"))

    index = 0
    for size in sorted(set(sizes)):
        for selected in combinations(plugins, size):
            for proxy in proxies:
                if "routeforce" in selected and proxy not in ("gpugr", "xplace"):
                    continue
                for point in points:
                    name = "%s_%04d_%s_%s" % (
                        prefix, index, proxy, "__".join(selected)
                    )
                    config = {
                        "ruplace_flag": 1,
                        "routability_opt_flag": 1,
                        "ruplace_proxy": proxy,
                        "ruplace_plugins": list(selected),
                    }
                    config.update(shared)
                    config.update(point)
                    result[name] = config
                    manifest[name] = {
                        "plugins": list(selected),
                        "proxy": proxy,
                        "grid": point,
                    }
                    index += 1
                    if index > max_presets:
                        raise ValueError(
                            "generated preset count exceeds --max-presets=%d" % max_presets
                        )
    if not manifest:
        raise ValueError("spec generated no valid plugin combinations")
    return result, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--base-presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-presets", type=int, default=256)
    args = parser.parse_args(argv)

    presets, manifest = generate_presets(
        json.loads(args.base_presets.read_text()),
        json.loads(args.spec.read_text()),
        args.max_presets,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(presets, indent=2, sort_keys=True) + "\n")
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps({
        "base_presets": str(args.base_presets.resolve()),
        "spec": str(args.spec.resolve()),
        "generated": manifest,
    }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
