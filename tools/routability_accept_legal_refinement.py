#!/usr/bin/env python3
"""Accept a legal refinement only when both proxy gates pass strictly."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.routability_select_survivors import routability_metric_profile


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_evaluation(directory):
    directory = Path(directory).resolve()
    results = {}
    for backend in ("rudy", "gpugr"):
        path = directory / (backend + ".json")
        data = json.loads(path.read_text())
        if data.get("backend") != backend or data.get("status") != "ok":
            raise ValueError("expected successful %s result: %s" % (backend, path))
        results[backend] = data
    return results


def audit_candidate(name, def_path, evaluation_dir, refinement_report,
                    baseline_def, baseline, profile):
    def_path = Path(def_path).resolve()
    evaluation_dir = Path(evaluation_dir).resolve()
    refinement_report = Path(refinement_report).resolve()
    proposal = json.loads(refinement_report.read_text())
    candidate_source = Path(proposal.get("candidate_def", ""))
    lef_hashes = proposal.get("lef_sha256", {})
    lef_hashes_match = bool(lef_hashes) and all(
        Path(path).is_file() and sha256(path) == digest
        for path, digest in lef_hashes.items()
    )
    proposal_hash_matches = (
        proposal.get("schema_version") == 2
        and proposal.get("output_sha256") == sha256(def_path)
        and Path(proposal.get("output_def", "")).resolve() == def_path
        and proposal.get("baseline_sha256") == sha256(baseline_def)
        and Path(proposal.get("baseline_def", "")).resolve() == baseline_def
        and candidate_source.is_file()
        and proposal.get("candidate_sha256") == sha256(candidate_source)
        and lef_hashes_match
    )
    legality_preserved = (
        proposal.get("operation") == "route_directed_legal_whitespace_slide"
        and int(proposal.get("baseline_overlap_pairs", -1)) == 0
        and int(proposal.get("output_overlap_pairs", -1)) == 0
    )
    results = load_evaluation(evaluation_dir)
    deltas = {}
    missing = []
    improvements = {"rudy": [], "gpugr": []}
    gpugr_regressions = []
    for backend, metric in profile["primary"]:
        base_value = baseline[backend].get("metrics", {}).get(metric)
        candidate_value = results[backend].get("metrics", {}).get(metric)
        key = "%s:%s" % (backend, metric)
        if base_value is None or candidate_value is None:
            missing.append(key)
            continue
        raw = float(candidate_value) - float(base_value)
        deltas[key] = {
            "baseline": float(base_value),
            "candidate": float(candidate_value),
            "delta": raw,
            "delta_pct": (
                100.0 * raw / float(base_value)
                if float(base_value) != 0.0 else None
            ),
        }
        if raw < 0.0:
            improvements[backend].append(metric)
        elif backend == "gpugr" and raw > 0.0:
            gpugr_regressions.append(metric)
    accepted = bool(
        proposal_hash_matches
        and legality_preserved
        and not missing
        and improvements["rudy"]
        and improvements["gpugr"]
        and not gpugr_regressions
    )
    reasons = []
    if not proposal_hash_matches:
        reasons.append("proposal hash or output identity mismatch")
    if not legality_preserved:
        reasons.append("legality evidence does not preserve overlap count")
    if missing:
        reasons.append("missing primary metrics")
    if not improvements["rudy"]:
        reasons.append("no RUDY primary improvement")
    if not improvements["gpugr"]:
        reasons.append("no GPUGR primary improvement")
    if gpugr_regressions:
        reasons.append("positive GPUGR primary regressions")
    return {
        "name": name,
        "def": str(def_path),
        "evaluation_dir": str(evaluation_dir),
        "refinement_report": str(refinement_report),
        "accepted": accepted,
        "proposal_hash_matches": proposal_hash_matches,
        "legality_preserved": legality_preserved,
        "rudy_improvements": sorted(improvements["rudy"]),
        "gpugr_improvements": sorted(improvements["gpugr"]),
        "gpugr_regressions": sorted(gpugr_regressions),
        "missing_metrics": sorted(missing),
        "reasons": reasons,
        "deltas": deltas,
        "sha256": {
            "def": sha256(def_path),
            "refinement_report": sha256(refinement_report),
            "rudy": sha256(evaluation_dir / "rudy.json"),
            "gpugr": sha256(evaluation_dir / "gpugr.json"),
        },
    }


def accept_legal_refinement(baseline_def, baseline_evaluation, candidates,
                            output=None, metric_profile="absolute_directional_v2"):
    baseline_def = Path(baseline_def).resolve()
    baseline_evaluation = Path(baseline_evaluation).resolve()
    profile = routability_metric_profile(metric_profile)
    baseline = load_evaluation(baseline_evaluation)
    rows = [
        audit_candidate(
            name, def_path, evaluation, proposal, baseline_def, baseline, profile
        )
        for name, def_path, evaluation, proposal in candidates
    ]
    accepted = [row for row in rows if row["accepted"]]
    selected = accepted[0] if accepted else None
    selected_def = Path(selected["def"]) if selected else baseline_def
    materialized = None
    if output:
        output = Path(output).resolve()
        if output == selected_def:
            raise ValueError("materialized output must differ from selected input")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(selected_def, output)
        materialized = str(output)
    return {
        "schema_version": 1,
        "status": "complete",
        "decision": "accepted" if selected else "rollback_to_baseline",
        "metric_profile": metric_profile,
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "selection_policy": "first strict candidate in declared order",
        "strict_gate": {
            "rudy_primary_improvement_required": True,
            "gpugr_primary_improvement_required": True,
            "gpugr_positive_worst_regression_allowed": False,
            "legality_evidence_required": True,
        },
        "baseline_def": str(baseline_def),
        "baseline_evaluation": str(baseline_evaluation),
        "selected_candidate": selected["name"] if selected else "baseline",
        "selected_def": str(selected_def),
        "selected_sha256": sha256(selected_def),
        "materialized_def": materialized,
        "candidate_count": len(rows),
        "accepted_count": len(accepted),
        "candidates": rows,
    }


def parse_candidate(value):
    fields = value.split("::")
    if len(fields) != 4 or not all(fields):
        raise ValueError(
            "--candidate requires NAME::DEF::EVALUATION_DIR::REFINEMENT_REPORT"
        )
    return tuple(fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-def", type=Path, required=True)
    parser.add_argument("--baseline-evaluation", type=Path, required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--metric-profile", default="absolute_directional_v2")
    parser.add_argument("--materialized-def", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = accept_legal_refinement(
        args.baseline_def,
        args.baseline_evaluation,
        [parse_candidate(value) for value in args.candidate],
        output=args.materialized_def,
        metric_profile=args.metric_profile,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
