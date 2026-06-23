#!/usr/bin/env python3
"""Validate RUPlace paper targets against WL and H/V congestion guardrails."""

import argparse
import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = [
    "paper_full_congestion_hv_v2_3pct:1.03",
    "paper_full_congestion_hv_v2_5pct:1.05",
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--result-root",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality",
    )
    parser.add_argument("--best-run", default="paper_full_auto_qualified_v74")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target as run_id:wl_slack, e.g. paper_full_congestion_hv_v2_3pct:1.03.",
    )
    parser.add_argument("--rc-weight", type=float, default=1000000.0)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "paper_target_validation.json",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "paper_target_validation.csv",
    )
    parser.add_argument(
        "--strict-log-rrr",
        action="store_true",
        help="Require every RUPlace row to have an available eval log proving --_eval-route-rrr-iters 1.",
    )
    parser.add_argument(
        "--no-auto-targets",
        action="store_true",
        help="Validate only explicitly requested --target entries; do not auto-append detected v3 targets.",
    )
    return parser.parse_args()


def read_rows(run_dir):
    path = run_dir / "raw_metrics.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def fval(row, key):
    value = row.get(key, "")
    if value in ("", "NA", None):
        return None
    return float(value)


def ruplace_rows(run_dir):
    return [
        row for row in read_rows(run_dir)
        if row.get("method") == "ruplace" and row.get("status") == "ok"
    ]


def totals(rows, rc_weight):
    route_wl = 0.0
    ovfl = 0.0
    shorts = 0.0
    rc_penalty = 0.0
    rc_h = []
    rc_v = []
    for row in rows:
        route_wl += fval(row, "route_wl") or 0.0
        ovfl += fval(row, "route_ovfl_nets") or 0.0
        shorts += fval(row, "route_est_shorts") or 0.0
        h = fval(row, "rc_hor")
        v = fval(row, "rc_ver")
        if h is not None:
            rc_h.append(h)
        if v is not None:
            rc_v.append(v)
        rc_penalty += rc_weight * (max((h or 1.0) - 1.0, 0.0) + max((v or 1.0) - 1.0, 0.0))
    score = ovfl + shorts
    return {
        "design_count": len(rows),
        "route_wl": route_wl,
        "ovfl": ovfl,
        "shorts": shorts,
        "score": score,
        "rc_penalty": rc_penalty,
        "hv_objective": score + rc_penalty,
        "mean_rc_h": sum(rc_h) / len(rc_h) if rc_h else None,
        "mean_rc_v": sum(rc_v) / len(rc_v) if rc_v else None,
    }


def localize_log(path_text):
    if not path_text:
        return None
    path = Path(path_text)
    if path.exists():
        return path
    marker = "/results/ruplace_quality/"
    if marker in path_text:
        candidate = REPO_ROOT / "results" / "ruplace_quality" / path_text.split(marker, 1)[1]
        if candidate.exists():
            return candidate
    return None


def rrr_evidence(rows):
    evidence = {"metric_source_ok": 0, "metric_source_bad": 0, "rrr1_logs": 0, "missing_logs": 0}
    bad_sources = []
    missing_logs = []
    for row in rows:
        source = row.get("metric_source", "")
        if source in {"xplace_ggr", "xplace_ggr_on_output"}:
            evidence["metric_source_ok"] += 1
        else:
            evidence["metric_source_bad"] += 1
            bad_sources.append({"design": row.get("design"), "metric_source": source})
        log_path = localize_log(row.get("log_path", ""))
        if not log_path:
            evidence["missing_logs"] += 1
            missing_logs.append(row.get("design"))
            continue
        text = log_path.read_text(errors="ignore")
        if "--_eval-route-rrr-iters 1" in text or "'_eval_route_rrr_iters': 1" in text:
            evidence["rrr1_logs"] += 1
    evidence["bad_sources"] = bad_sources
    evidence["missing_log_designs"] = missing_logs
    return evidence


def provenance_evidence(run_dir):
    path = run_dir / "composite_provenance.csv"
    evidence = {
        "provenance_rows": 0,
        "direct_leaf_sources": 0,
        "composite_leaf_sources": 0,
        "missing_provenance": int(not path.exists()),
    }
    if not path.exists():
        return evidence
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("method") != "ruplace":
                continue
            evidence["provenance_rows"] += 1
            if str(row.get("source_is_composite", "0")) in {"1", "true", "True"}:
                evidence["composite_leaf_sources"] += 1
            else:
                evidence["direct_leaf_sources"] += 1
    return evidence


def parse_targets(items, result_root, auto_targets=True):
    parsed = []
    for item in items or DEFAULT_TARGETS:
        if ":" in item:
            run_id, slack = item.split(":", 1)
            parsed.append((run_id.strip(), float(slack)))
        else:
            parsed.append((item.strip(), 1.05 if "5pct" in item else 1.03))
    if auto_targets:
        for run_id in ["paper_full_congestion_hv_v3_3pct", "paper_full_congestion_hv_v3_5pct"]:
            if (result_root / run_id / "raw_metrics.csv").exists() and run_id not in {r for r, _s in parsed}:
                parsed.append((run_id, 1.05 if "5pct" in run_id else 1.03))
    return parsed


def main():
    args = parse_args()
    result_root = args.result_root.resolve()
    base_dir = result_root / args.best_run
    base_rows = ruplace_rows(base_dir)
    base = totals(base_rows, args.rc_weight)
    base_evidence = rrr_evidence(base_rows)

    records = []
    failures = []
    for run_id, wl_slack in parse_targets(args.target, result_root, auto_targets=not args.no_auto_targets):
        run_dir = result_root / run_id
        rows = ruplace_rows(run_dir)
        metrics = totals(rows, args.rc_weight)
        evidence = rrr_evidence(rows)
        provenance = provenance_evidence(run_dir)
        wl_ratio = metrics["route_wl"] / base["route_wl"] if base["route_wl"] else None
        obj_ratio = metrics["hv_objective"] / base["hv_objective"] if base["hv_objective"] else None
        pass_wl = wl_ratio is not None and wl_ratio <= wl_slack + 1e-9
        pass_obj = obj_ratio is not None and obj_ratio <= 1.0 + 1e-9
        pass_source = evidence["metric_source_bad"] == 0
        rrr1_log_evidence_complete = evidence["missing_logs"] == 0 and evidence["rrr1_logs"] == len(rows)
        pass_log_requirement = (not args.strict_log_rrr) or rrr1_log_evidence_complete
        passed = pass_wl and pass_obj and pass_source and pass_log_requirement
        if not passed:
            failures.append(run_id)
        records.append({
            "run": run_id,
            "wl_slack": wl_slack,
            "pass": passed,
            "pass_wl": pass_wl,
            "pass_hv_objective": pass_obj,
            "pass_metric_source": pass_source,
            "pass_rrr1_log_requirement": pass_log_requirement,
            "rrr1_log_evidence_complete": rrr1_log_evidence_complete,
            "route_wl": metrics["route_wl"],
            "wl_vs_best": wl_ratio,
            "ovfl": metrics["ovfl"],
            "shorts": metrics["shorts"],
            "score": metrics["score"],
            "rc_penalty": metrics["rc_penalty"],
            "hv_objective": metrics["hv_objective"],
            "hv_objective_vs_best": obj_ratio,
            "mean_rc_h": metrics["mean_rc_h"],
            "mean_rc_v": metrics["mean_rc_v"],
            "design_count": metrics["design_count"],
            "metric_source_ok": evidence["metric_source_ok"],
            "metric_source_bad": evidence["metric_source_bad"],
            "rrr1_logs": evidence["rrr1_logs"],
            "missing_logs": evidence["missing_logs"],
            "provenance_rows": provenance["provenance_rows"],
            "direct_leaf_sources": provenance["direct_leaf_sources"],
            "composite_leaf_sources": provenance["composite_leaf_sources"],
            "missing_provenance": provenance["missing_provenance"],
        })

    payload = {
        "pass": not failures,
        "best_run": args.best_run,
        "rc_weight": args.rc_weight,
        "best_metrics": base,
        "best_rrr_evidence": base_evidence,
        "targets": records,
        "failures": failures,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with args.output_csv.open("w", newline="") as f:
        fieldnames = list(records[0].keys()) if records else ["run", "pass"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print("Wrote %s" % args.output_json)
    print("Wrote %s" % args.output_csv)
    for record in records:
        print(
            "%s: %s wl=%.6f/%.3f hv_obj=%.6f sources=%d bad=%d rrr1_logs=%d missing_logs=%d direct_leaf=%d/%d"
            % (
                record["run"],
                "PASS" if record["pass"] else "FAIL",
                record["wl_vs_best"],
                record["wl_slack"],
                record["hv_objective_vs_best"],
                record["metric_source_ok"],
                record["metric_source_bad"],
                record["rrr1_logs"],
                record["missing_logs"],
                record["direct_leaf_sources"],
                record["provenance_rows"],
            )
        )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
