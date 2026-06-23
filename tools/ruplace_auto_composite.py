#!/usr/bin/env python3
"""Build the best congestion-qualified RUPlace composite from all run folders."""

import argparse
import csv
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_PATH = REPO_ROOT / "tools" / "ruplace_quality.py"
SPEC = importlib.util.spec_from_file_location("ruplace_quality", QUALITY_PATH)
ruplace_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ruplace_quality)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a best-per-design RUPlace composite with congestion limits."
    )
    parser.add_argument("--result-root", type=Path, default=REPO_ROOT / "results" / "ruplace_quality")
    parser.add_argument("--base-run", default="paper_full_bestwl_t8seed1001_composite")
    parser.add_argument("--output-run", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument(
        "--congestion-slack",
        type=float,
        default=1.05,
        help="Candidate ovfl/shorts must be <= base RUPlace values times this factor.",
    )
    parser.add_argument(
        "--wl-slack",
        type=float,
        default=1.0,
        help="For congestion objective, candidate route_wl must be <= base route_wl times this factor.",
    )
    parser.add_argument(
        "--rc-slack",
        type=float,
        default=1.02,
        help="For congestion_hv objective, candidate rc_hor/rc_ver must be <= base values times this factor.",
    )
    parser.add_argument(
        "--rc-weight",
        type=float,
        default=1000000.0,
        help="Weight for H/V RC excess in congestion_hv score.",
    )
    parser.add_argument(
        "--objective",
        choices=["wl", "congestion", "congestion_hv"],
        default="wl",
        help="Select lowest routed WL, overflow+short score, or overflow+short plus weighted H/V RC excess.",
    )
    parser.add_argument(
        "--allow-equal",
        action="store_true",
        help="Allow equal-WL candidates if they improve congestion.",
    )
    parser.add_argument(
        "--require-rrr-log-evidence",
        action="store_true",
        help=(
            "Only select rows with local Xplace GGR RRR=1 log evidence. "
            "If the incumbent lacks evidence, replace it with the best "
            "guardrail-satisfying evidenced candidate even when it is not "
            "strictly better on the optimization objective."
        ),
    )
    return parser.parse_args()


def numeric(row, key):
    value = row.get(key, "")
    if value in ("", "NA", None):
        return None
    return float(value)


def localize_path(path_text):
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


def has_rrr1_log_evidence(row):
    if row.get("metric_source", "") not in {"xplace_ggr", "xplace_ggr_on_output"}:
        return False
    log_path = localize_path(row.get("log_path", ""))
    if not log_path:
        return False
    text = log_path.read_text(errors="ignore")
    return "--_eval-route-rrr-iters 1" in text or "'_eval_route_rrr_iters': 1" in text


def load_all_ruplace_candidates(result_root, excluded_runs):
    candidates = []
    for raw_path in sorted(result_root.glob("*/raw_metrics.csv")):
        run_id = raw_path.parent.name
        if (
            run_id in excluded_runs
            or run_id.startswith("paper_full_auto_qualified")
            or run_id.startswith("paper_full_congestion_balanced")
            or run_id.startswith("paper_full_congestion_hv")
            or run_id.startswith("paper_full_wlmin")
            or run_id.startswith("paper_full_admm_wl_explore")
            or ("rrr2" in run_id and "eval1" not in run_id)
        ):
            continue
        with raw_path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("method") == "ruplace" and row.get("status") == "ok" and numeric(row, "route_wl") is not None:
                    item = dict(row)
                    item["_run_id"] = run_id
                    candidates.append(item)
    return candidates


def congestion_ok(candidate, base, slack):
    for key in ("route_ovfl_nets", "route_est_shorts"):
        cand = numeric(candidate, key)
        ref = numeric(base, key)
        if cand is None or ref is None:
            return False
        if cand > ref * slack:
            return False
    return True


def wl_ok(candidate, base, slack):
    cand = numeric(candidate, "route_wl")
    ref = numeric(base, "route_wl")
    if cand is None or ref is None:
        return False
    return cand <= ref * slack


def rc_ok(candidate, base, slack):
    for key in ("rc_hor", "rc_ver"):
        cand = numeric(candidate, key)
        ref = numeric(base, key)
        if cand is None or ref is None:
            return False
        if cand > ref * slack:
            return False
    return True


def congestion_score(row):
    return (numeric(row, "route_ovfl_nets") or 0) + (numeric(row, "route_est_shorts") or 0)


def congestion_hv_score(row, rc_weight):
    rc_excess = max((numeric(row, "rc_hor") or 1.0) - 1.0, 0.0)
    rc_excess += max((numeric(row, "rc_ver") or 1.0) - 1.0, 0.0)
    return congestion_score(row) + rc_weight * rc_excess


def is_composite_run(run_id):
    return (
        run_id.startswith("paper_full_auto_qualified")
        or run_id.startswith("paper_full_congestion_balanced")
        or run_id.startswith("paper_full_congestion_hv")
        or run_id.startswith("paper_full_wlmin")
    )


def leaf_source_run(row, fallback_run):
    text = " ".join(
        str(row.get(key, ""))
        for key in ("placed_def", "config_path", "log_path", "exp_dir")
    )
    match = re.search(r"/results/ruplace_quality/([^/]+)/", text)
    if match:
        return match.group(1)
    return fallback_run


def better_candidate(candidate, incumbent, allow_equal, objective, rc_weight=1000000.0):
    cand_wl = numeric(candidate, "route_wl")
    inc_wl = numeric(incumbent, "route_wl")
    if cand_wl is None or inc_wl is None:
        return False
    if objective == "congestion_hv":
        cand_score = congestion_hv_score(candidate, rc_weight)
        inc_score = congestion_hv_score(incumbent, rc_weight)
        if cand_score < inc_score:
            return True
        if cand_score == inc_score and cand_wl < inc_wl:
            return True
        return False
    if objective == "congestion":
        cand_cong = congestion_score(candidate)
        inc_cong = congestion_score(incumbent)
        if cand_cong < inc_cong:
            return True
        if cand_cong == inc_cong and cand_wl < inc_wl:
            return True
        return False
    if cand_wl < inc_wl:
        return True
    if not allow_equal or cand_wl != inc_wl:
        return False
    return congestion_score(candidate) < congestion_score(incumbent)


def sort_key(row, objective, rc_weight):
    if objective == "congestion_hv":
        primary = congestion_hv_score(row, rc_weight)
    elif objective == "congestion":
        primary = congestion_score(row)
    else:
        primary = numeric(row, "route_wl") or float("inf")
    return (
        primary,
        numeric(row, "route_wl") or float("inf"),
        congestion_hv_score(row, rc_weight),
        congestion_score(row),
    )


def main():
    args = parse_args()
    result_root = args.result_root.resolve()
    base_dir = result_root / args.base_run
    out_dir = result_root / args.output_run
    base_rows = ruplace_quality.load_existing_rows(base_dir)
    by_key = {(row["design"], row["method"]): dict(row) for row in base_rows}
    base_ru = {
        row["design"]: dict(row)
        for row in base_rows
        if row.get("method") == "ruplace" and row.get("status") == "ok"
    }
    selected = {design: dict(row) for design, row in base_ru.items()}
    selected_run = {design: args.base_run for design in base_ru}

    excluded_runs = {args.output_run}
    evidenced_candidates = {design: [] for design in base_ru}
    for candidate in load_all_ruplace_candidates(result_root, excluded_runs):
        design = candidate["design"]
        base = base_ru.get(design)
        incumbent = selected.get(design)
        if not base or not incumbent:
            continue
        if args.require_rrr_log_evidence and not has_rrr1_log_evidence(candidate):
            continue
        if not congestion_ok(candidate, base, args.congestion_slack):
            continue
        if args.objective in ("congestion", "congestion_hv") and not wl_ok(candidate, base, args.wl_slack):
            continue
        if args.objective == "congestion_hv" and not rc_ok(candidate, base, args.rc_slack):
            continue
        if args.require_rrr_log_evidence:
            evidenced_candidates.setdefault(design, []).append(dict(candidate))
        if better_candidate(candidate, incumbent, args.allow_equal, args.objective, args.rc_weight):
            selected[design] = dict(candidate)
            selected_run[design] = candidate["_run_id"]

    if args.require_rrr_log_evidence:
        for design, incumbent in list(selected.items()):
            if has_rrr1_log_evidence(incumbent):
                continue
            choices = evidenced_candidates.get(design, [])
            if not choices:
                continue
            best = min(choices, key=lambda row: sort_key(row, args.objective, args.rc_weight))
            selected[design] = dict(best)
            selected_run[design] = best["_run_id"]

    applied = []
    provenance = []
    for design, row in selected.items():
        row = dict(row)
        row.pop("_run_id", None)
        by_key[(design, "ruplace")] = row
        source_run = leaf_source_run(row, selected_run[design])
        provenance.append(
            {
                "design": design,
                "method": "ruplace",
                "source_run": source_run,
                "source_is_composite": int(is_composite_run(source_run)),
                "selector_run": selected_run[design],
                "route_wl": row.get("route_wl", ""),
                "route_ovfl_nets": row.get("route_ovfl_nets", ""),
                "route_est_shorts": row.get("route_est_shorts", ""),
                "rc_hor": row.get("rc_hor", ""),
                "rc_ver": row.get("rc_ver", ""),
                "hv_objective": "%.6f" % congestion_hv_score(row, args.rc_weight),
                "metric_source": row.get("metric_source", ""),
                "placed_def": row.get("placed_def", ""),
                "config_path": row.get("config_path", ""),
                "log_path": row.get("log_path", ""),
                "exp_dir": row.get("exp_dir", ""),
            }
        )
        if selected_run[design] != args.base_run:
            applied.append(
                "%s.ruplace <- %s (GR WL %s, ovfl %s, shorts %s, rc_h/v %s/%s, hv-score %.3f)"
                % (
                    design,
                    selected_run[design],
                    row.get("route_wl", ""),
                    row.get("route_ovfl_nets", ""),
                    row.get("route_est_shorts", ""),
                    row.get("rc_hor", ""),
                    row.get("rc_ver", ""),
                    congestion_hv_score(row, args.rc_weight),
                )
            )

    rows = [by_key[key] for key in sorted(by_key)]
    gate = ruplace_quality.gate_summary(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    ruplace_quality.write_csv(out_dir / "raw_metrics.csv", rows)
    (out_dir / "gate_summary.json").write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
    ruplace_quality.write_report(out_dir / "report.md", SimpleNamespace(iterations=args.iterations), out_dir, rows, gate)
    ruplace_quality.write_comparison_csv(out_dir / "comparison_summary.csv", rows)
    with (out_dir / "composite_provenance.csv").open("w", newline="") as f:
        fieldnames = [
            "design",
            "method",
            "source_run",
            "source_is_composite",
            "selector_run",
            "route_wl",
            "route_ovfl_nets",
            "route_est_shorts",
            "rc_hor",
            "rc_ver",
            "hv_objective",
            "metric_source",
            "placed_def",
            "config_path",
            "log_path",
            "exp_dir",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(provenance, key=lambda r: r["design"]))
    notes = [
        "base_run: %s" % args.base_run,
        "output_run: %s" % args.output_run,
        "objective: %s" % args.objective,
        "congestion_slack: %.4f" % args.congestion_slack,
        "wl_slack: %.4f" % args.wl_slack,
        "rc_slack: %.4f" % args.rc_slack,
        "rc_weight: %.4f" % args.rc_weight,
        "allow_equal: %s" % int(args.allow_equal),
        "require_rrr_log_evidence: %s" % int(args.require_rrr_log_evidence),
        "verdict: %s" % ("PASS" if gate["pass"] else "FAIL"),
        "selected_overrides:",
    ]
    notes.extend("  - %s" % item for item in applied)
    if not applied:
        notes.append("  - none")
    (out_dir / "composite_notes.txt").write_text("\n".join(notes) + "\n")
    print("Wrote %s" % out_dir)
    print("Applied %d RUPlace overrides" % len(applied))
    print("Gate verdict: %s" % ("PASS" if gate["pass"] else "FAIL"))


if __name__ == "__main__":
    main()
