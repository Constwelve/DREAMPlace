#!/usr/bin/env python3
"""Generate a route-feedback placement used only as a direction oracle."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_blend_def import file_sha256


DEFAULT_OPTIONS = {
    "routability_target_rc_metric": 1.005,
    "routability_check_overflow": 0.20,
    "routability_snapshot_overflow": 0.25,
    "routability_max_density": 0.99,
    "routability_inflation_ratio_coef": 1.0,
    "routability_max_inflation_ratio": 1.02,
    "overflow": 0.10,
}


def resolve_openroad_binary(value):
    resolved = shutil.which(str(value))
    if not resolved:
        raise FileNotFoundError("OpenROAD binary is unavailable: %s" % value)
    return Path(resolved).resolve()


def openroad_tcl(lef_inputs, baseline_def, output, options=None):
    options = dict(DEFAULT_OPTIONS if options is None else options)
    required = set(DEFAULT_OPTIONS)
    if set(options) != required:
        raise ValueError("OpenROAD oracle option keys must match the frozen set")
    commands = ["read_lef {%s}" % Path(path).resolve() for path in lef_inputs]
    commands.append("read_def {%s}" % Path(baseline_def).resolve())
    commands.append(
        "global_placement -incremental -skip_initial_place "
        "-routability_driven -routability_use_grt "
        "-routability_target_rc_metric {routability_target_rc_metric} "
        "-routability_check_overflow {routability_check_overflow} "
        "-routability_snapshot_overflow {routability_snapshot_overflow} "
        "-routability_max_density {routability_max_density} "
        "-routability_inflation_ratio_coef {routability_inflation_ratio_coef} "
        "-routability_max_inflation_ratio {routability_max_inflation_ratio} "
        "-overflow {overflow}".format(**options)
    )
    commands.extend([
        "detailed_placement",
        "check_placement -verbose",
        "write_def {%s}" % Path(output).resolve(),
        "exit",
    ])
    return "\n".join(commands) + "\n"


def generate_oracle(baseline_def, lef_inputs, output, report_path=None,
                    openroad_binary="openroad", threads=8, options=None,
                    log_path=None):
    baseline_def = Path(baseline_def).resolve()
    output = Path(output).resolve()
    if output == baseline_def:
        raise ValueError("oracle output must differ from the baseline DEF")
    if isinstance(lef_inputs, (str, Path)):
        lef_inputs = [lef_inputs]
    lef_inputs = [Path(path).resolve() for path in lef_inputs]
    if not lef_inputs:
        raise ValueError("OpenROAD oracle requires at least one LEF")
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path or output.with_suffix(".openroad.log")).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    frozen_options = dict(DEFAULT_OPTIONS if options is None else options)
    tcl = openroad_tcl(lef_inputs, baseline_def, output, frozen_options)
    resolved_binary = resolve_openroad_binary(openroad_binary)

    version = subprocess.run(
        [str(resolved_binary), "-version"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    completed = subprocess.run(
        [
            str(resolved_binary), "-no_init", "-no_splash",
            "-threads", str(int(threads)), "-log", str(log_path),
        ],
        input=tcl,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode or not output.is_file():
        raise RuntimeError(
            "OpenROAD oracle failed with status %d: %s"
            % (completed.returncode, (completed.stdout or "")[-2000:])
        )
    report = {
        "schema_version": 1,
        "operation": "openroad_routability_direction_oracle",
        "baseline_def": str(baseline_def),
        "baseline_sha256": file_sha256(baseline_def),
        "lef_inputs": [str(path) for path in lef_inputs],
        "lef_sha256": {str(path): file_sha256(path) for path in lef_inputs},
        "output_def": str(output),
        "output_sha256": file_sha256(output),
        "openroad_binary": str(openroad_binary),
        "openroad_binary_resolved": str(resolved_binary),
        "openroad_binary_sha256": file_sha256(resolved_binary),
        "openroad_version": (version.stdout or "").strip(),
        "threads": int(threads),
        "options": frozen_options,
        "tcl": tcl,
        "log": str(log_path),
        "log_sha256": file_sha256(log_path) if log_path.is_file() else "",
    }
    if report_path:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-def", type=Path, required=True)
    parser.add_argument("--lef-input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--openroad-binary", default="openroad")
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args(argv)
    generate_oracle(
        args.baseline_def,
        args.lef_input,
        args.output,
        report_path=args.report,
        openroad_binary=args.openroad_binary,
        threads=args.threads,
        log_path=args.log,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
