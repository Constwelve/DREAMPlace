#!/usr/bin/env python3
"""Audit strict legal-refinement acceptance across multiple development seeds."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_seed_acceptance(value):
    fields = value.split("::", 1)
    if len(fields) != 2 or not all(fields):
        raise ValueError("--seed-acceptance requires SEED::PATH")
    return int(fields[0]), Path(fields[1]).resolve()


def audit_multiseed(seed_acceptances):
    if len(seed_acceptances) < 2:
        raise ValueError("multi-seed audit requires at least two seeds")
    if len({seed for seed, _ in seed_acceptances}) != len(seed_acceptances):
        raise ValueError("seed identifiers must be unique")
    loaded = []
    expected_methods = None
    expected_profile = None
    for seed, path in seed_acceptances:
        data = json.loads(path.read_text())
        if (
            data.get("status") != "complete"
            or data.get("numeric_backend_mixing") is not False
            or data.get("heldout_or_golden_evidence_used") is not False
            or data.get("strict_gate", {}).get(
                "gpugr_positive_worst_regression_allowed"
            ) is not False
        ):
            raise ValueError("seed %d has an invalid strict acceptance" % seed)
        methods = [row.get("name") for row in data.get("candidates", [])]
        if not methods or len(methods) != len(set(methods)):
            raise ValueError("seed %d has invalid candidate coverage" % seed)
        if expected_methods is None:
            expected_methods = methods
            expected_profile = data.get("metric_profile")
        if methods != expected_methods or data.get("metric_profile") != expected_profile:
            raise ValueError("seed acceptance coverage or policy differs")
        by_method = {row["name"]: row for row in data["candidates"]}
        loaded.append((seed, path, data, by_method))

    common = [
        method for method in expected_methods
        if all(by_method[method].get("accepted") is True
               for _, _, _, by_method in loaded)
    ]
    return {
        "schema_version": 1,
        "status": "complete",
        "decision": "accepted" if common else "rollback_to_baseline",
        "selected_candidate": common[0] if common else "baseline",
        "common_strict_survivors": common,
        "candidate_order": expected_methods,
        "metric_profile": expected_profile,
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "seed_count": len(loaded),
        "seeds": [
            {
                "seed": seed,
                "acceptance": str(path),
                "acceptance_sha256": sha256(path),
                "decision": data["decision"],
                "accepted_candidates": [
                    method for method in expected_methods
                    if by_method[method].get("accepted") is True
                ],
            }
            for seed, path, data, by_method in loaded
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-acceptance", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_multiseed([
        parse_seed_acceptance(value) for value in args.seed_acceptance
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
