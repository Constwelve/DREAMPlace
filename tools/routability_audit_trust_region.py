#!/usr/bin/env python3
"""Audit a baseline-anchored DEF trust-region experiment."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_select_survivors import routability_metric_profile


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_ok_result(path, backend):
    data = json.loads(Path(path).read_text())
    if data.get("status") != "ok" or data.get("backend") != backend:
        raise ValueError("expected successful %s result: %s" % (backend, path))
    return data


def metric_delta(candidate, baseline):
    candidate = float(candidate)
    baseline = float(baseline)
    raw = candidate - baseline
    if baseline == 0.0:
        percent = 0.0 if candidate == 0.0 else math.copysign(math.inf, raw)
    else:
        percent = 100.0 * raw / baseline
    return {"baseline": baseline, "candidate": candidate,
            "delta": raw, "delta_pct": percent}


def audit_trust_region(baseline_evaluation, experiment_root, output=None,
                       metric_profile="absolute_directional_v2"):
    baseline_evaluation = Path(baseline_evaluation).resolve()
    experiment_root = Path(experiment_root).resolve()
    profile = routability_metric_profile(metric_profile)
    baseline = {
        backend: load_ok_result(baseline_evaluation / (backend + ".json"), backend)
        for backend in ("rudy", "gpugr")
    }
    rows = []
    for alpha_root in sorted(experiment_root.glob("alpha_*")):
        if not alpha_root.is_dir():
            continue
        blend_path = alpha_root / "blend.json"
        evaluation = alpha_root / "evaluation"
        if not blend_path.is_file():
            raise ValueError("missing blend report: %s" % blend_path)
        blend = json.loads(blend_path.read_text())
        results = {
            backend: load_ok_result(evaluation / (backend + ".json"), backend)
            for backend in ("rudy", "gpugr")
        }
        deltas = {}
        missing = []
        for backend, metric in profile["primary"]:
            base_value = baseline[backend].get("metrics", {}).get(metric)
            candidate_value = results[backend].get("metrics", {}).get(metric)
            if base_value is None or candidate_value is None:
                missing.append("%s:%s" % (backend, metric))
                continue
            deltas["%s:%s" % (backend, metric)] = metric_delta(
                candidate_value, base_value
            )
        improvements = {
            backend: sorted(
                name for name, item in deltas.items()
                if name.startswith(backend + ":") and item["delta"] < 0.0
            )
            for backend in ("rudy", "gpugr")
        }
        gpugr_regressions = sorted(
            name for name, item in deltas.items()
            if name.startswith("gpugr:") and item["delta"] > 0.0
        )
        proxy_pass = bool(
            not missing
            and improvements["rudy"]
            and improvements["gpugr"]
            and not gpugr_regressions
        )
        orientation_mismatches = int(blend.get(
            "orientation_mismatch_count", 0
        ))
        promotion_eligible = proxy_pass and orientation_mismatches == 0
        reasons = []
        if missing:
            reasons.append("missing primary metrics")
        if not improvements["rudy"]:
            reasons.append("no RUDY primary improvement")
        if not improvements["gpugr"]:
            reasons.append("no GPUGR primary improvement")
        if gpugr_regressions:
            reasons.append("positive GPUGR primary regressions")
        if orientation_mismatches:
            reasons.append("candidate orientations were not preserved")
        rows.append({
            "alpha": float(blend["alpha"]),
            "directory": str(alpha_root),
            "proxy_pass": proxy_pass,
            "promotion_eligible": promotion_eligible,
            "orientation_mismatch_count": orientation_mismatches,
            "rudy_improvements": improvements["rudy"],
            "gpugr_improvements": improvements["gpugr"],
            "gpugr_regressions": gpugr_regressions,
            "missing_metrics": missing,
            "reasons": reasons,
            "deltas": deltas,
            "sha256": {
                "blend": sha256(blend_path),
                "rudy": sha256(evaluation / "rudy.json"),
                "gpugr": sha256(evaluation / "gpugr.json"),
                "placement": sha256(alpha_root / "placement.def"),
            },
        })
    if not rows:
        raise ValueError("trust-region experiment has no alpha directories")
    report = {
        "schema_version": 1,
        "status": "complete",
        "decision": (
            "survivor" if any(row["promotion_eligible"] for row in rows)
            else "rejected"
        ),
        "metric_profile": metric_profile,
        "scope": "displacement_response_diagnostic",
        "baseline_evaluation": str(baseline_evaluation),
        "experiment_root": str(experiment_root),
        "evaluated_alphas": len(rows),
        "proxy_survivors": [
            row["alpha"] for row in rows if row["proxy_pass"]
        ],
        "promotion_survivors": [
            row["alpha"] for row in rows if row["promotion_eligible"]
        ],
        "rows": rows,
        "sha256": {
            backend: sha256(baseline_evaluation / (backend + ".json"))
            for backend in ("rudy", "gpugr")
        },
    }
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-evaluation", type=Path, required=True)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--metric-profile", default="absolute_directional_v2")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_trust_region(
        args.baseline_evaluation, args.experiment_root, args.output,
        args.metric_profile,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
