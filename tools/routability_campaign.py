#!/usr/bin/env python3
"""Run contest and real-design routability campaigns from case manifests."""

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATORS = "openroad,innovus,rudy,gpugr"


def as_list(value):
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def parse_path_maps(values):
    mappings = []
    for value in values or []:
        if "=" not in value:
            raise ValueError("--path-map requires OLD=NEW, got %s" % value)
        old, new = value.split("=", 1)
        mappings.append((str(Path(old).expanduser()), str(Path(new).expanduser())))
    return mappings


def apply_path_maps(value, path_maps):
    value = str(Path(value).expanduser())
    for old, new in path_maps:
        prefix = old.rstrip("/") + "/"
        if value == old:
            return new
        if value.startswith(prefix):
            return new.rstrip("/") + "/" + value[len(prefix):]
    return value


def resolve_path(value, manifest_dir, path_maps=()):
    if not value:
        return ""
    path = Path(apply_path_maps(value, path_maps))
    return str((manifest_dir / path).resolve()) if not path.is_absolute() else str(path.resolve())


def resolve_template_paths(template, template_dir):
    result = dict(template)
    for key in (
        "ruplace_xplace_root", "routability_eval_cugr_root",
        "routability_eval_nctugr_root", "routability_eval_openroad_binary",
        "routability_eval_cadence_wrapper", "routability_eval_cadence_mounted_root",
    ):
        value = result.get(key)
        if value and ("/" in str(value) or str(value).startswith(".")):
            result[key] = resolve_path(value, template_dir)
    return result


def load_cases(manifests, selected, path_maps=()):
    cases = []
    for manifest in manifests:
        data = json.loads(manifest.read_text())
        for raw in data.get("cases", []):
            if selected and raw.get("name") not in selected:
                continue
            case = dict(raw)
            case["manifest"] = str(manifest)
            case["lef_input"] = [
                resolve_path(path, manifest.parent, path_maps)
                for path in as_list(raw.get("lef_input"))
            ]
            for key in ("def_input", "verilog_input", "eval_verilog_input", "aux_input"):
                case[key] = resolve_path(raw.get(key, ""), manifest.parent, path_maps)
            cases.append(case)
    return cases


def write_status(path, rows):
    fields = [
        "case", "class", "benchmark", "random_seed", "placement_status", "reason",
        "manifest", "result_dir",
    ]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument(
        "--template", type=Path, default=ROOT / "configs/routability_campaign_template.json"
    )
    parser.add_argument(
        "--presets", type=Path,
        default=ROOT / "configs/routability_plugins/presets.json",
    )
    parser.add_argument("--cases", default="")
    parser.add_argument("--methods", default="hpwl,dreamplace_rudy_inflation,route_inflation")
    parser.add_argument("--evaluators", default=DEFAULT_EVALUATORS)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dreamplace-entry", type=Path, default=ROOT / "install/dreamplace/Placer.py")
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--path-map", action="append", default=[])
    args = parser.parse_args(argv)

    selected = {name.strip() for name in args.cases.split(",") if name.strip()}
    path_maps = parse_path_maps(args.path_map)
    cases = load_cases([path.resolve() for path in args.manifest], selected, path_maps)
    template_path = args.template.resolve()
    template = resolve_template_paths(json.loads(template_path.read_text()), template_path.parent)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    statuses = []

    for case in cases:
        enabled = case.get("enabled", True)
        placement_enabled = case.get("placement_enabled", True)
        case_class = "contest" if "ispd" in str(case.get("benchmark", "")).lower() else "real"
        case_dir = (args.output_dir / case["name"]).resolve()
        reason = ""
        if not enabled and not args.include_disabled:
            statuses.append({
                "case": case["name"], "class": case_class,
                "benchmark": case.get("benchmark", ""), "random_seed": args.random_seed,
                "placement_status": "disabled",
                "reason": case.get("notes", "disabled by manifest"),
                "manifest": case["manifest"], "result_dir": str(case_dir),
            })
            continue
        if not placement_enabled:
            statuses.append({
                "case": case["name"], "class": case_class,
                "benchmark": case.get("benchmark", ""), "random_seed": args.random_seed,
                "placement_status": "input_reference_only",
                "reason": case.get("notes", "placement disabled by manifest"),
                "manifest": case["manifest"], "result_dir": str(case_dir),
            })
            continue
        missing = [path for path in case["lef_input"] + [case.get("def_input", "")] if path and not Path(path).exists()]
        if missing:
            statuses.append({
                "case": case["name"], "class": case_class,
                "benchmark": case.get("benchmark", ""), "random_seed": args.random_seed,
                "placement_status": "missing_input",
                "reason": "; ".join(missing), "manifest": case["manifest"],
                "result_dir": str(case_dir),
            })
            continue
        config = dict(template)
        config.update({
            "lef_input": case["lef_input"],
            "def_input": case.get("def_input", ""),
            "verilog_input": case.get("verilog_input", ""),
            "ruplace_eval_verilog_input": case.get("eval_verilog_input", ""),
            "aux_input": case.get("aux_input", ""),
        })
        if args.random_seed is not None:
            config["random_seed"] = args.random_seed
        case_dir.mkdir(parents=True, exist_ok=True)
        base_config = case_dir / "base_config.json"
        base_config.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        command = [
            sys.executable, str(ROOT / "tools/routability_compare.py"),
            "--base-config", str(base_config),
            "--design-name", case.get("design_name", ""),
            "--presets", str(args.presets.resolve()),
            "--methods", args.methods, "--evaluators", args.evaluators,
            "--output-dir", str(case_dir / "methods"),
            "--dreamplace-entry", str(args.dreamplace_entry),
            "--num-threads", str(args.num_threads), "--continue-on-error",
        ]
        if args.timeout_sec:
            command.extend(["--timeout-sec", str(args.timeout_sec)])
        status = "planned" if args.dry_run else "completed"
        if not args.dry_run:
            completed = subprocess.run(command, check=False)
            if completed.returncode:
                status = "completed_with_failures"
                reason = "comparison runner exit status %d" % completed.returncode
        statuses.append({
            "case": case["name"], "class": case_class,
            "benchmark": case.get("benchmark", ""), "random_seed": args.random_seed,
            "placement_status": status,
            "reason": reason, "manifest": case["manifest"], "result_dir": str(case_dir),
        })
        write_status(args.output_dir / "campaign_status.csv", statuses)

    write_status(args.output_dir / "campaign_status.csv", statuses)
    (args.output_dir / "campaign_status.json").write_text(
        json.dumps({"cases": statuses}, indent=2, sort_keys=True) + "\n"
    )
    failed_states = {"completed_with_failures", "missing_input"}
    return 1 if any(row["placement_status"] in failed_states for row in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
