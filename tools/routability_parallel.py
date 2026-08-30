#!/usr/bin/env python3
"""Run case/seed routability campaigns concurrently on assigned GPUs."""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_campaign import (
    baseline_first_methods,
    load_cases,
    parse_path_maps,
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_int_list(value):
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def write_status(output_dir, jobs):
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": utc_now(), "jobs": jobs}
    (output_dir / "parallel_status.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    fields = [
        "job_id", "case", "seed", "gpu", "status", "returncode",
        "started_at", "finished_at", "result_dir", "log",
    ]
    with (output_dir / "parallel_status.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(jobs)

    counts = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    active = [job for job in jobs if job["status"] == "running"]
    lines = [
        "# Routability Campaign Handoff",
        "",
        "- Updated: `%s`" % payload["updated_at"],
        "- Repository: `%s`" % ROOT,
        "- Artifact root: `%s`" % output_dir.resolve(),
        "- Progress: `%d/%d complete`" % (
            counts.get("completed", 0), len(jobs)
        ),
        "- Failed: `%d`" % counts.get("failed", 0),
        "- Running: `%d`" % counts.get("running", 0),
        "",
        "## Active Jobs",
        "",
    ]
    if active:
        lines.extend(
            "- `%s` on GPU `%s`; log `%s`" %
            (job["job_id"], job["gpu"], job["log"])
            for job in active
        )
    else:
        lines.append("- None")
    (output_dir / "HANDOFF_STATUS.md").write_text("\n".join(lines) + "\n")


def build_command(args, case_name, seed, result_dir):
    command = [
        sys.executable, str(ROOT / "tools/routability_campaign.py"),
        "--template", str(args.template.resolve()),
        "--presets", str(args.presets.resolve()),
        "--cases", case_name,
        "--methods", args.methods,
        "--evaluators", args.evaluators,
        "--output-dir", str(result_dir),
        "--dreamplace-entry", str(args.dreamplace_entry.resolve()),
        "--num-threads", str(args.num_threads),
        "--random-seed", str(seed),
    ]
    for manifest in args.manifest:
        command.extend(["--manifest", str(manifest.resolve())])
    for mapping in args.path_map:
        command.extend(["--path-map", mapping])
    if args.timeout_sec:
        command.extend(["--timeout-sec", str(args.timeout_sec)])
    if args.resume:
        command.append("--resume")
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument(
        "--presets", type=Path,
        default=ROOT / "configs/routability_plugins/presets.json",
    )
    parser.add_argument("--cases", default="")
    parser.add_argument("--seeds", default="1000,2000,3000")
    parser.add_argument("--gpus", default="0,1,2,3")
    parser.add_argument("--methods", required=True)
    parser.add_argument("--evaluators", default="rudy,gpugr")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dreamplace-entry", type=Path, required=True)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    args.methods = baseline_first_methods(args.methods)

    selected = {item.strip() for item in args.cases.split(",") if item.strip()}
    path_maps = parse_path_maps(args.path_map)
    cases = load_cases(
        [path.resolve() for path in args.manifest], selected, path_maps
    )
    eligible = [
        case for case in cases
        if case.get("enabled", True) and case.get("placement_enabled", True)
    ]
    if selected:
        found = {case["name"] for case in eligible}
        missing = selected - found
        if missing:
            raise ValueError(
                "selected cases are missing or disabled: %s" % ", ".join(sorted(missing))
            )
    seeds = parse_int_list(args.seeds)
    gpus = parse_int_list(args.gpus)
    if not eligible or not seeds or not gpus:
        raise ValueError("at least one eligible case, seed, and GPU are required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for case in eligible:
        for seed in seeds:
            job_id = "%s__seed_%d" % (case["name"], seed)
            result_dir = (args.output_dir / case["name"] / ("seed_%d" % seed)).resolve()
            jobs.append({
                "job_id": job_id,
                "case": case["name"],
                "seed": seed,
                "gpu": "",
                "status": "pending",
                "returncode": "",
                "started_at": "",
                "finished_at": "",
                "result_dir": str(result_dir),
                "log": str(result_dir / "parallel_job.log"),
            })
    write_status(args.output_dir, jobs)

    pending = list(range(len(jobs)))
    available_gpus = list(gpus)
    running = {}
    while pending or running:
        while pending and available_gpus:
            index = pending.pop(0)
            gpu = available_gpus.pop(0)
            job = jobs[index]
            result_dir = Path(job["result_dir"])
            result_dir.mkdir(parents=True, exist_ok=True)
            stream = Path(job["log"]).open("w")
            env = dict(os.environ)
            env["CUDA_VISIBLE_DEVICES"] = str(gpu)
            process = subprocess.Popen(
                build_command(args, job["case"], job["seed"], result_dir),
                stdout=stream, stderr=subprocess.STDOUT, env=env,
            )
            job.update({"gpu": gpu, "status": "running", "started_at": utc_now()})
            running[index] = (process, stream, gpu)
            write_status(args.output_dir, jobs)

        completed = []
        for index, (process, stream, gpu) in running.items():
            returncode = process.poll()
            if returncode is None:
                continue
            stream.close()
            jobs[index].update({
                "status": "completed" if returncode == 0 else "failed",
                "returncode": returncode,
                "finished_at": utc_now(),
            })
            available_gpus.append(gpu)
            completed.append(index)
        for index in completed:
            del running[index]
        if completed:
            available_gpus.sort()
            write_status(args.output_dir, jobs)
        elif running:
            time.sleep(1.0)

    return 0 if all(job["status"] == "completed" for job in jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
