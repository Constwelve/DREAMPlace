#!/usr/bin/env python3
"""Build rough monotone RUDY/GPUGR to Innovus NR-eGR calibration curves."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

import numpy as np


NR_RE = re.compile(
    r"Overflow after Early Global Route\s+([0-9.]+)%\s+H\s+\+\s+([0-9.]+)%\s+V"
)
RUDY_RE = re.compile(r"RouteOverflow\s+([0-9.eE+-]+)")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def last_match(path, pattern):
    value = None
    with Path(path).open(errors="replace") as stream:
        for line in stream:
            match = pattern.search(line)
            if match:
                value = tuple(float(item) for item in match.groups())
    return value


def pava_curve(samples, ucb_floor=0.0):
    grouped = {}
    for x, y in samples:
        grouped.setdefault(float(x), []).append(float(y))
    points = sorted((x, float(np.mean(values)), len(values)) for x, values in grouped.items())
    blocks = []
    for x, y, weight in points:
        blocks.append({"xs": [x], "weight": weight, "sum": y * weight})
        while len(blocks) >= 2:
            left = blocks[-2]["sum"] / blocks[-2]["weight"]
            right = blocks[-1]["sum"] / blocks[-1]["weight"]
            if left <= right:
                break
            b = blocks.pop()
            a = blocks.pop()
            blocks.append({
                "xs": a["xs"] + b["xs"],
                "weight": a["weight"] + b["weight"],
                "sum": a["sum"] + b["sum"],
            })
    knots, values = [], []
    for block in blocks:
        value = block["sum"] / block["weight"]
        for x in block["xs"]:
            knots.append(x)
            values.append(value)
    predicted = [np.interp(x, knots, values) for x, _ in samples]
    residual = np.asarray([y - pred for pred, (_, y) in zip(predicted, samples)])
    return {
        "knots": knots,
        "values": values,
        "underprediction_q95": float(max(np.quantile(residual, 0.95), float(ucb_floor))),
        "n_samples": len(samples),
    }


def collect_rudy(worktree):
    samples = {"h": [], "v": []}
    evidence = []
    result_root = worktree / "results/s14_innovus"
    for case in ("nvdla_s_s14", "regression_s14"):
        with (result_root / (case + ".csv")).open(newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("status") != "ok" or not row.get("def"):
                    continue
                def_path = Path(row["def"])
                placement_log = def_path.parents[2] / "dreamplace.log"
                innovus_dir = result_root / (row["run_id"] + "_" + row["method"])
                innovus_log = innovus_dir / "innovus.log"
                if not placement_log.is_file() or not innovus_log.is_file():
                    continue
                rudy = last_match(placement_log, RUDY_RE)
                nr = last_match(innovus_log, NR_RE)
                if not rudy or not nr:
                    continue
                samples["h"].append((rudy[0], nr[0]))
                samples["v"].append((rudy[0], nr[1]))
                evidence.append({
                    "case": case, "run_id": row["run_id"], "method": row["method"],
                    "rudy_route_overflow": rudy[0], "innovus_h": nr[0], "innovus_v": nr[1],
                })
    return samples, evidence


def collect_gpugr(worktree):
    samples = {"h": [], "v": []}
    evidence = []
    preferred = [
        worktree / "results/gr_calib/b2_k5_rrr1/calib.json",
        worktree / "results/gr_calib/reg_k5_rrr1/calib.json",
    ]
    for path in preferred:
        if not path.is_file():
            continue
        data = json.loads(path.read_text())
        nr = data["innovus"]["metrics"]
        row = {"case": data["case"], "source": str(path)}
        for direction in ("h", "v"):
            info = data["avail"][direction]
            total = data[direction]["n_gcells"]
            coverage = 100.0 * info["ovfl_gcells"] / max(total, 1)
            target = nr["egr_horizontal_congestion" if direction == "h" else "egr_vertical_congestion"]
            samples[direction].append((coverage, target))
            row["gpugr_" + direction] = coverage
            row["innovus_" + direction] = target
        evidence.append(row)
    return samples, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    output = args.output or (
        worktree / "dreamplace/ops/routability_opt/calibration/smic14_v1.json"
    )
    rudy, rudy_evidence = collect_rudy(worktree)
    gpugr, gpugr_evidence = collect_gpugr(worktree)
    if min(len(rudy["h"]), len(rudy["v"]), len(gpugr["h"]), len(gpugr["v"])) < 2:
        raise RuntimeError("insufficient retained calibration evidence")
    for proxy in (rudy, gpugr):
        proxy["h"].append((0.0, 0.0))
        proxy["v"].append((0.0, 0.0))
    payload = {
        "schema_version": 1,
        "name": "smic14-v1",
        "valid": True,
        "description": "Monotone rough calibration from retained s14 evidence; no new Innovus runs.",
        "curves": {
            "rudy": {"h": pava_curve(rudy["h"]), "v": pava_curve(rudy["v"])},
            "gpugr": {
                "h": pava_curve(gpugr["h"], ucb_floor=0.5),
                "v": pava_curve(gpugr["v"], ucb_floor=0.5),
            },
        },
        "validation": {
            "status": "rough-retained-evidence-fit",
            "rudy_samples": len(rudy_evidence),
            "gpugr_samples": len(gpugr_evidence),
            "note": "Proxy-only runtime target; not an Innovus certification.",
        },
        "provenance": {
            "s14_csv_sha256": {
                case: sha256(worktree / "results/s14_innovus" / (case + ".csv"))
                for case in ("nvdla_s_s14", "regression_s14")
            },
            "rudy_evidence": rudy_evidence,
            "gpugr_evidence": gpugr_evidence,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output)
    print("rudy samples", len(rudy_evidence), "gpugr samples", len(gpugr_evidence))


if __name__ == "__main__":
    main()
