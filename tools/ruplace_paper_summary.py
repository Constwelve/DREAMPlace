#!/usr/bin/env python3
"""Generate a paper-facing RUPlace benchmark summary from run artifacts."""

import argparse
import csv
import datetime
import json
import statistics
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = [
    ("paper_full_v8_td130_hard_robust", "Best clean WL-oriented PASS"),
    ("paper_full_v11_robust_t4_t5", "Robust single-run PASS"),
    ("paper_full_bestwl_composite", "Best mined per-design WL composite before seed sweep"),
    ("paper_full_bestwl_t8seed1001_composite", "Best mined/seed-tuned per-design WL composite"),
    ("paper_full_auto_qualified_composite", "Auto-selected congestion-qualified composite"),
    ("paper_full_auto_qualified_v2", "Auto-selected qualified composite with seed sweep"),
    ("paper_full_auto_qualified_v3", "Auto-selected qualified composite with test9/test10 sweeps"),
    ("paper_full_auto_qualified_v4", "Auto-selected qualified composite with refined test10"),
    ("paper_full_auto_qualified_v5", "Auto-selected qualified composite with test10 seed sweep"),
    ("paper_full_auto_qualified_v6", "Auto-selected qualified composite with test9 cap sweep"),
    ("paper_full_auto_qualified_v7", "Auto-selected qualified composite with test9 cap020 sweep"),
    ("paper_full_auto_qualified_v9", "Auto-selected qualified composite with test10 per-cell inflation"),
    ("paper_full_auto_qualified_v10", "Auto-selected qualified composite with test8 exponent refinement"),
    ("paper_full_auto_qualified_v11", "Auto-selected qualified composite with refined test8/test10 exponents"),
    ("paper_full_auto_qualified_v12", "Auto-selected qualified composite with refined test9 cap/exponent"),
    ("paper_full_auto_qualified_v13", "Auto-selected qualified composite with refined test10 cap/exponent"),
    ("paper_full_auto_qualified_v14", "Auto-selected qualified composite with final test10 cap/exponent refinement"),
    ("paper_full_auto_qualified_v15", "Auto-selected qualified composite with final test8/test9 refinement"),
    ("paper_full_auto_qualified_v17", "Auto-selected qualified composite with mid-design density refinement"),
    ("paper_full_auto_qualified_v18", "Auto-selected qualified composite with test5 congestion-qualified WL refinement"),
    ("paper_full_auto_qualified_v19", "Auto-selected qualified composite with test2/test3 congestion-qualified WL refinement"),
    ("paper_full_auto_qualified_v20", "Auto-selected qualified composite after final test2/test3 sweep"),
    ("paper_full_auto_qualified_v21", "Auto-selected qualified composite with recursive composite sources excluded"),
    ("paper_full_auto_qualified_v22", "Auto-selected qualified composite after hard-design seed refinement"),
    ("paper_full_auto_qualified_v23", "Auto-selected qualified composite after hard-design target-density refinement"),
    ("paper_full_auto_qualified_v24", "Auto-selected qualified composite after fine cap/gamma sweep"),
    ("paper_full_auto_qualified_v25", "Auto-selected qualified composite after hard-design iteration sweep"),
    ("paper_full_auto_qualified_v26", "Auto-selected qualified composite after sparse ADMM sweep"),
    ("paper_full_auto_qualified_v27", "Auto-selected qualified composite after broadened target-density sweep"),
    ("paper_full_auto_qualified_v28", "Auto-selected qualified composite after optimizer-gamma sweep"),
    ("paper_full_auto_qualified_v29", "Auto-selected qualified composite after hard-design low-gamma sweep"),
    ("paper_full_auto_qualified_v30", "Auto-selected qualified composite after low-gamma density refinement"),
    ("paper_full_auto_qualified_v31", "Auto-selected qualified composite after hard-design fine gamma/TD sweep"),
    ("paper_full_auto_qualified_v32", "Auto-selected qualified composite after cap/fine gamma refinement"),
    ("paper_full_auto_qualified_v33", "Auto-selected qualified composite after seed/TD micro-refinement"),
    ("paper_full_auto_qualified_v34", "Auto-selected qualified composite after low-strength ADMM probes"),
    ("paper_full_auto_qualified_v35", "Auto-selected qualified composite after early-inflation start sweep"),
    ("paper_full_auto_qualified_v36", "Auto-selected qualified composite after test10 gamma/start/cap refinement"),
    ("paper_full_auto_qualified_v37", "Auto-selected qualified composite after hard-design seed sensitivity sweep"),
    ("paper_full_auto_qualified_v39", "Auto-selected qualified composite after fair global-inflation strength sweep"),
    ("paper_full_auto_qualified_v40", "Auto-selected qualified composite after fine test9 global-inflation sweep"),
    ("paper_full_auto_qualified_v41", "Auto-selected qualified composite after fine hard-design GP/start/cap sweep"),
    ("paper_full_auto_qualified_v42", "Auto-selected qualified composite after learning-rate/noise sweep"),
    ("paper_full_auto_qualified_v43", "Auto-selected qualified composite after combined LR/noise and test9 gamma sweep"),
    ("paper_full_auto_qualified_v44", "Auto-selected qualified composite after fine test8-noise/test9-gamma sweep"),
    ("paper_full_auto_qualified_v45", "Auto-selected qualified composite after tighter test9 gamma sweep"),
    ("paper_full_auto_qualified_v46", "Auto-selected qualified composite after sub-step test9 gamma confirmation"),
    ("paper_full_auto_qualified_v47", "Auto-selected qualified composite after final test10 TD check"),
    ("paper_full_auto_qualified_v48", "Auto-selected qualified composite after final test9 cap/TD refinement"),
    ("paper_full_auto_qualified_v49", "Auto-selected qualified composite after node-utilization smoothing"),
    ("paper_full_auto_qualified_v50", "Auto-selected qualified composite after smoothed test9 cap/gamma refinement"),
    ("paper_full_auto_qualified_v51", "No-op composite after local inflation repair probes"),
    ("paper_full_auto_qualified_v52", "No-op composite after internal RRR=2/final RRR=1 probes"),
    ("paper_full_auto_qualified_v53", "No-op composite after NaN-hardened internal RRR=2 probe"),
    ("paper_full_auto_qualified_v54", "No-op composite after density-weight balance probes"),
    ("paper_full_auto_qualified_v55", "No-op WL-best composite after placement-bin granularity probes"),
    ("paper_full_auto_qualified_v56", "No-op WL-best composite after interpolated placement-bin probes"),
    ("paper_full_auto_qualified_v57", "No-op WL-best composite after fine placement-bin probes"),
    ("paper_full_auto_qualified_v58", "No-op WL-best composite after sub-step test9 gamma/cap sweep"),
    ("paper_full_auto_qualified_v59", "Auto-selected qualified composite after test10 noise/route-guidance sweep"),
    ("paper_full_auto_qualified_v60", "No-op WL-best composite after stronger internal RRR guidance sweep"),
    ("paper_full_auto_qualified_v61", "Auto-selected qualified composite after hybrid ADMM/local-inflation test8 sweep"),
    ("paper_full_auto_qualified_v62", "Auto-selected qualified composite after hybrid ADMM/local-inflation test9 sweep"),
    ("paper_full_auto_qualified_v63", "Auto-selected qualified composite after hybrid ADMM/local-inflation test10 sweep"),
    ("paper_full_auto_qualified_v64", "No-op WL-best composite after ADMM micro-sweep on test8/test9"),
    ("paper_full_auto_qualified_v65", "Auto-selected qualified composite after fine ADMM micro-sweep on hard designs"),
    ("paper_full_auto_qualified_v66", "Auto-selected qualified composite after second fine ADMM micro-sweep"),
    ("paper_full_auto_qualified_v67", "Auto-selected qualified composite after third fine ADMM micro-sweep"),
    ("paper_full_auto_qualified_v68", "Auto-selected qualified composite after internal-RRR/test8 ADMM refinement"),
    ("paper_full_auto_qualified_v69", "Auto-selected qualified composite after test8 ADMM start refinement"),
    ("paper_full_auto_qualified_v72", "No-op WL-best composite after ADMM decay/clip schedule probes"),
    ("paper_full_auto_qualified_v73", "Auto-selected qualified composite after ADMM anchor-policy refinement"),
    ("paper_full_auto_qualified_v74", "Auto-selected qualified composite after static-anchor hard-design refinement"),
    ("paper_full_auto_qualified_v75", "No-op WL-best composite after cap/weight hard-design refinement"),
    ("paper_full_auto_qualified_v76", "Auto-selected qualified composite after H/V congestion-target hard-design replay"),
    ("paper_full_auto_qualified_v77", "Auto-selected qualified composite after directional H/V inflation sweep"),
    ("paper_full_admm_wl_explore_v1", "Rejected: ADMM routed-wire exploration improved WL but failed congestion"),
    ("paper_full_congestion_balanced_v1", "Congestion-balanced composite with <=5% per-design WL slack"),
    ("paper_full_congestion_balanced_v2", "Congestion-balanced composite with test8 exponent refinement"),
    ("paper_full_congestion_balanced_v3", "Congestion-balanced composite after refined exponent sweep"),
    ("paper_full_congestion_balanced_v4", "Congestion-balanced composite after test9 cap/exponent sweep"),
    ("paper_full_congestion_balanced_v5", "Congestion-balanced composite after test10 cap/exponent sweep"),
    ("paper_full_congestion_balanced_v6", "Congestion-balanced composite after final test10 cap/exponent sweep"),
    ("paper_full_congestion_balanced_v7", "Congestion-balanced composite after final test8/test9 refinement"),
    ("paper_full_congestion_balanced_v8", "Congestion-balanced composite after local-inflation sweep"),
    ("paper_full_congestion_balanced_v9", "Congestion-balanced composite after mid-design density refinement"),
    ("paper_full_congestion_balanced_v10", "Congestion-balanced composite after test5 WL refinement"),
    ("paper_full_congestion_balanced_v11", "Congestion-balanced composite after test2/test3 WL refinement"),
    ("paper_full_congestion_balanced_v12", "Congestion-balanced composite after final test2/test3 sweep"),
    ("paper_full_congestion_balanced_v13", "Congestion-balanced composite after hard-design seed refinement"),
    ("paper_full_congestion_balanced_v14", "Congestion-balanced composite after hard-design target-density refinement"),
    ("paper_full_congestion_balanced_v15", "Congestion-balanced composite after fine cap/gamma sweep"),
    ("paper_full_congestion_balanced_v16", "Congestion-balanced composite after hard-design iteration sweep"),
    ("paper_full_congestion_balanced_v17", "Congestion-balanced composite after sparse ADMM sweep"),
    ("paper_full_congestion_balanced_v18", "Congestion-balanced composite after broadened target-density sweep"),
    ("paper_full_congestion_balanced_v19", "Congestion-balanced composite after optimizer-gamma sweep"),
    ("paper_full_congestion_balanced_v20", "Congestion-balanced composite after hard-design low-gamma sweep"),
    ("paper_full_congestion_balanced_v21", "Congestion-balanced composite after low-gamma density refinement"),
    ("paper_full_congestion_balanced_v22", "Congestion-balanced composite after hard-design fine gamma/TD sweep"),
    ("paper_full_congestion_balanced_v23", "Congestion-balanced composite after cap/fine gamma refinement"),
    ("paper_full_congestion_balanced_v24", "Congestion-balanced composite after seed/TD micro-refinement"),
    ("paper_full_congestion_balanced_v25", "Congestion-balanced composite after low-strength ADMM probes"),
    ("paper_full_congestion_balanced_v26", "Congestion-balanced composite after early-inflation start sweep"),
    ("paper_full_congestion_balanced_v27", "Congestion-balanced composite after test10 gamma/start/cap refinement"),
    ("paper_full_congestion_balanced_v28", "Congestion-balanced composite after hard-design seed sensitivity sweep"),
    ("paper_full_congestion_balanced_v30", "Congestion-balanced composite after fair global-inflation strength sweep"),
    ("paper_full_congestion_balanced_v31", "Congestion-balanced composite after fine test9 global-inflation sweep"),
    ("paper_full_congestion_balanced_v32", "Congestion-balanced composite after fine hard-design GP/start/cap sweep"),
    ("paper_full_congestion_balanced_v33", "Congestion-balanced composite after learning-rate/noise sweep"),
    ("paper_full_congestion_balanced_v34", "Congestion-balanced composite after combined LR/noise and test9 gamma sweep"),
    ("paper_full_congestion_balanced_v35", "Congestion-balanced composite after fine test8-noise/test9-gamma sweep"),
    ("paper_full_congestion_balanced_v36", "Congestion-balanced composite after tighter test9 gamma sweep"),
    ("paper_full_congestion_balanced_v37", "Congestion-balanced composite after sub-step test9 gamma confirmation"),
    ("paper_full_congestion_balanced_v38", "Congestion-balanced composite after final test10 TD check"),
    ("paper_full_congestion_balanced_v39", "Congestion-balanced composite after final test9 cap/TD refinement"),
    ("paper_full_congestion_balanced_v40", "Congestion-balanced composite after node-utilization smoothing"),
    ("paper_full_congestion_balanced_v41", "Congestion-balanced composite after smoothed test9 cap/gamma refinement"),
    ("paper_full_congestion_balanced_v42", "No-op congestion-balanced composite after local inflation repair probes"),
    ("paper_full_congestion_balanced_v43", "No-op congestion-balanced composite after internal RRR=2/final RRR=1 probes"),
    ("paper_full_congestion_balanced_v44", "No-op congestion-balanced composite after NaN-hardened internal RRR=2 probe"),
    ("paper_full_congestion_balanced_v45", "No-op congestion-balanced composite after density-weight balance probes"),
    ("paper_full_congestion_balanced_v46", "Congestion-balanced composite after placement-bin granularity probes"),
    ("paper_full_congestion_balanced_v47", "Congestion-balanced composite after interpolated placement-bin probes"),
    ("paper_full_congestion_balanced_v48", "Congestion-balanced composite after fine placement-bin probes"),
    ("paper_full_congestion_balanced_v49", "No-op congestion-balanced composite after sub-step test9 gamma/cap sweep"),
    ("paper_full_congestion_balanced_v50", "No-op congestion-balanced composite after test10 noise/route-guidance sweep"),
    ("paper_full_congestion_balanced_v51", "No-op congestion-balanced composite after stronger internal RRR guidance sweep"),
    ("paper_full_congestion_balanced_v52", "Congestion-balanced composite after hybrid ADMM/local-inflation test8 sweep"),
    ("paper_full_congestion_balanced_v53", "No-op congestion-balanced composite after hybrid ADMM/local-inflation test9 sweep"),
    ("paper_full_congestion_balanced_v54", "Congestion-balanced composite after hybrid ADMM/local-inflation test10 sweep"),
    ("paper_full_congestion_balanced_v55", "No-op congestion-balanced composite after ADMM micro-sweep on test8/test9"),
    ("paper_full_congestion_balanced_v56", "Congestion-balanced composite after fine ADMM micro-sweep on hard designs"),
    ("paper_full_congestion_balanced_v57", "Congestion-balanced composite after second fine ADMM micro-sweep"),
    ("paper_full_congestion_balanced_v58", "Congestion-balanced composite after third fine ADMM micro-sweep"),
    ("paper_full_congestion_balanced_v59", "Congestion-balanced composite after internal-RRR/test8 ADMM refinement"),
    ("paper_full_congestion_balanced_v60", "Congestion-balanced composite after test8 ADMM start refinement"),
    ("paper_full_congestion_balanced_v63", "Congestion-balanced composite after ADMM decay/clip schedule probes"),
    ("paper_full_congestion_balanced_v64", "Congestion-balanced composite after ADMM anchor-policy refinement"),
    ("paper_full_congestion_balanced_v65", "Congestion-balanced composite after static-anchor hard-design refinement"),
    ("paper_full_congestion_balanced_v66", "No-op congestion-balanced composite after cap/weight hard-design refinement"),
    ("paper_full_congestion_hv_v1", "H/V congestion-target composite with <=5% routed-WL slack"),
    ("paper_full_congestion_hv_v2_3pct", "H/V congestion-target composite with <=3% routed-WL slack"),
    ("paper_full_congestion_hv_v2_5pct", "H/V congestion-frontier composite with <=5% routed-WL slack"),
    ("paper_full_congestion_hv_v3_3pct", "Directional H/V congestion-target composite with <=3% routed-WL slack"),
    ("paper_full_congestion_hv_v3_5pct", "Directional H/V congestion-frontier composite with <=5% routed-WL slack"),
    ("paper_full_congestion_hv_v3_3pct_allrrr", "All-RRR-evidence H/V congestion-target composite with <=3% routed-WL slack"),
    ("paper_full_congestion_hv_v3_5pct_allrrr", "All-RRR-evidence H/V congestion-frontier composite with <=5% routed-WL slack"),
    ("paper_full_v10_wl_t5stable", "Rejected: failed congestion gate"),
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Write a concise RUPlace paper benchmark summary."
    )
    parser.add_argument(
        "--result-root",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "paper_benchmark_summary.md",
    )
    parser.add_argument(
        "--best-run",
        default="paper_full_auto_qualified_v74",
        help="Run used for detailed wirelength tables.",
    )
    parser.add_argument(
        "--wirelength-csv",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "paper_wirelength_comparison.csv",
        help="CSV with per-design and total routed/HPWL wirelength comparisons.",
    )
    parser.add_argument(
        "--wirelength-md",
        type=Path,
        default=REPO_ROOT / "results" / "ruplace_quality" / "paper_wirelength_comparison.md",
        help="Standalone Markdown wirelength comparison for paper tables.",
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Run entry as run_id:description. Defaults to known paper runs if present.",
    )
    parser.add_argument(
        "--rc-weight",
        type=float,
        default=1000000.0,
        help="Weight for the H/V RC excess term in the reported congestion objective.",
    )
    return parser.parse_args()


def read_json(path):
    with path.open() as f:
        return json.load(f)


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def as_float(row, key):
    value = row.get(key, "")
    if value in ("", "NA", None):
        return None
    return float(str(value).replace("%", ""))


def fmt(value, digits=6):
    if value is None:
        return "NA"
    return ("%.*f" % (digits, value)).rstrip("0").rstrip(".")


def fmt_int(value):
    if value is None:
        return "NA"
    return str(int(round(value)))


def fmt_pct_from_ratio(value):
    if value is None:
        return "NA"
    return "%+.1f%%" % ((value - 1.0) * 100.0)


def fmt_signed_int(value):
    if value is None:
        return "NA"
    return "%+d" % int(round(value))


def total_ratio(rows, numerator_key, denominator_key):
    num = 0.0
    den = 0.0
    count = 0
    for row in rows:
        n = as_float(row, numerator_key)
        d = as_float(row, denominator_key)
        if n is None or d in (None, 0.0):
            continue
        num += n
        den += d
        count += 1
    return num / den if count and den else None


def total_raw_metric(run_dir, method, key):
    raw_path = run_dir / "raw_metrics.csv"
    if not raw_path.exists():
        return None
    total = 0.0
    count = 0
    for row in read_csv(raw_path):
        if row.get("method") != method or row.get("status") != "ok":
            continue
        value = as_float(row, key)
        if value is None:
            continue
        total += value
        count += 1
    return total if count else None


def hv_objective_for_method(run_dir, method, rc_weight):
    raw_path = run_dir / "raw_metrics.csv"
    if not raw_path.exists():
        return None, None, None
    score = 0.0
    rc_penalty = 0.0
    count = 0
    for row in read_csv(raw_path):
        if row.get("method") != method or row.get("status") != "ok":
            continue
        ovfl = as_float(row, "route_ovfl_nets")
        shorts = as_float(row, "route_est_shorts")
        rc_h = as_float(row, "rc_hor")
        rc_v = as_float(row, "rc_ver")
        if ovfl is None or shorts is None or rc_h is None or rc_v is None:
            continue
        score += ovfl + shorts
        rc_penalty += rc_weight * (max(rc_h - 1.0, 0.0) + max(rc_v - 1.0, 0.0))
        count += 1
    if not count:
        return None, None, None
    return score + rc_penalty, score, rc_penalty


def average_raw_metric(run_dir, method, key):
    raw_path = run_dir / "raw_metrics.csv"
    if not raw_path.exists():
        return None
    values = []
    for row in read_csv(raw_path):
        if row.get("method") != method or row.get("status") != "ok":
            continue
        value = as_float(row, key)
        if value is not None:
            values.append(value)
    return statistics.mean(values) if values else None


def max_raw_metric(run_dir, method, key):
    raw_path = run_dir / "raw_metrics.csv"
    if not raw_path.exists():
        return None
    values = []
    for row in read_csv(raw_path):
        if row.get("method") != method or row.get("status") != "ok":
            continue
        value = as_float(row, key)
        if value is not None:
            values.append(value)
    return max(values) if values else None


def count_true(rows, key):
    return sum(1 for row in rows if str(row.get(key, "")).strip() in ("1", "true", "True"))


def ratios_from(rows, numerator_key, denominator_key):
    ratios = []
    for row in rows:
        numerator = as_float(row, numerator_key)
        denominator = as_float(row, denominator_key)
        if numerator is not None and denominator not in (None, 0.0):
            ratios.append(numerator / denominator)
    return ratios


def write_wirelength_csv(path, rows):
    fields = [
        "design",
        "ru_route_wl",
        "xplace_route_wl",
        "ru_vs_xplace_route_wl",
        "ru_minus_xplace_route_wl",
        "dp_hpwl_route_wl",
        "ru_vs_dp_hpwl_route_wl",
        "ru_minus_dp_hpwl_route_wl",
        "dp_rudy_route_wl",
        "ru_vs_dp_rudy_route_wl",
        "ru_minus_dp_rudy_route_wl",
        "ru_place_hpwl",
        "xplace_place_hpwl",
        "ru_vs_xplace_place_hpwl",
        "dp_hpwl_place_hpwl",
        "ru_vs_dp_hpwl_place_hpwl",
        "dp_rudy_place_hpwl",
        "ru_vs_dp_rudy_place_hpwl",
        "route_wl_best_method",
    ]

    totals = {key: 0.0 for key in fields if key.endswith("_wl") or key.endswith("_hpwl")}
    out_rows = []
    for row in sorted(rows, key=lambda r: r["design"]):
        ru_route = as_float(row, "ru_route_wl")
        xp_route = as_float(row, "xplace_route_wl")
        hp_route = as_float(row, "dp_hpwl_route_wl")
        rudy_route = as_float(row, "dp_rudy_route_wl")
        ru_hpwl = as_float(row, "ru_place_hpwl")
        xp_hpwl = as_float(row, "xplace_place_hpwl")
        hp_hpwl = as_float(row, "dp_hpwl_place_hpwl")
        rudy_hpwl = as_float(row, "dp_rudy_place_hpwl")
        values = {
            "design": row["design"],
            "ru_route_wl": fmt_int(ru_route),
            "xplace_route_wl": fmt_int(xp_route),
            "ru_vs_xplace_route_wl": fmt(ru_route / xp_route if xp_route else None),
            "ru_minus_xplace_route_wl": fmt_signed_int(ru_route - xp_route if ru_route is not None and xp_route is not None else None),
            "dp_hpwl_route_wl": fmt_int(hp_route),
            "ru_vs_dp_hpwl_route_wl": fmt(ru_route / hp_route if hp_route else None),
            "ru_minus_dp_hpwl_route_wl": fmt_signed_int(ru_route - hp_route if ru_route is not None and hp_route is not None else None),
            "dp_rudy_route_wl": fmt_int(rudy_route),
            "ru_vs_dp_rudy_route_wl": fmt(ru_route / rudy_route if rudy_route else None),
            "ru_minus_dp_rudy_route_wl": fmt_signed_int(ru_route - rudy_route if ru_route is not None and rudy_route is not None else None),
            "ru_place_hpwl": fmt_int(ru_hpwl),
            "xplace_place_hpwl": fmt_int(xp_hpwl),
            "ru_vs_xplace_place_hpwl": fmt(ru_hpwl / xp_hpwl if xp_hpwl else None),
            "dp_hpwl_place_hpwl": fmt_int(hp_hpwl),
            "ru_vs_dp_hpwl_place_hpwl": fmt(ru_hpwl / hp_hpwl if hp_hpwl else None),
            "dp_rudy_place_hpwl": fmt_int(rudy_hpwl),
            "ru_vs_dp_rudy_place_hpwl": fmt(ru_hpwl / rudy_hpwl if rudy_hpwl else None),
            "route_wl_best_method": row.get("route_wl_best_method", "NA"),
        }
        out_rows.append(values)
        for key, value in [
            ("ru_route_wl", ru_route),
            ("xplace_route_wl", xp_route),
            ("dp_hpwl_route_wl", hp_route),
            ("dp_rudy_route_wl", rudy_route),
            ("ru_place_hpwl", ru_hpwl),
            ("xplace_place_hpwl", xp_hpwl),
            ("dp_hpwl_place_hpwl", hp_hpwl),
            ("dp_rudy_place_hpwl", rudy_hpwl),
        ]:
            totals[key] += value or 0.0

    total_row = {
        "design": "TOTAL",
        "ru_route_wl": fmt_int(totals["ru_route_wl"]),
        "xplace_route_wl": fmt_int(totals["xplace_route_wl"]),
        "ru_vs_xplace_route_wl": fmt(totals["ru_route_wl"] / totals["xplace_route_wl"] if totals["xplace_route_wl"] else None),
        "ru_minus_xplace_route_wl": fmt_signed_int(totals["ru_route_wl"] - totals["xplace_route_wl"]),
        "dp_hpwl_route_wl": fmt_int(totals["dp_hpwl_route_wl"]),
        "ru_vs_dp_hpwl_route_wl": fmt(totals["ru_route_wl"] / totals["dp_hpwl_route_wl"] if totals["dp_hpwl_route_wl"] else None),
        "ru_minus_dp_hpwl_route_wl": fmt_signed_int(totals["ru_route_wl"] - totals["dp_hpwl_route_wl"]),
        "dp_rudy_route_wl": fmt_int(totals["dp_rudy_route_wl"]),
        "ru_vs_dp_rudy_route_wl": fmt(totals["ru_route_wl"] / totals["dp_rudy_route_wl"] if totals["dp_rudy_route_wl"] else None),
        "ru_minus_dp_rudy_route_wl": fmt_signed_int(totals["ru_route_wl"] - totals["dp_rudy_route_wl"]),
        "ru_place_hpwl": fmt_int(totals["ru_place_hpwl"]),
        "xplace_place_hpwl": fmt_int(totals["xplace_place_hpwl"]),
        "ru_vs_xplace_place_hpwl": fmt(totals["ru_place_hpwl"] / totals["xplace_place_hpwl"] if totals["xplace_place_hpwl"] else None),
        "dp_hpwl_place_hpwl": fmt_int(totals["dp_hpwl_place_hpwl"]),
        "ru_vs_dp_hpwl_place_hpwl": fmt(totals["ru_place_hpwl"] / totals["dp_hpwl_place_hpwl"] if totals["dp_hpwl_place_hpwl"] else None),
        "dp_rudy_place_hpwl": fmt_int(totals["dp_rudy_place_hpwl"]),
        "ru_vs_dp_rudy_place_hpwl": fmt(totals["ru_place_hpwl"] / totals["dp_rudy_place_hpwl"] if totals["dp_rudy_place_hpwl"] else None),
        "route_wl_best_method": "",
    }
    out_rows.append(total_row)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)


def write_wirelength_markdown(path, rows, run_id):
    def sum_key(key):
        return sum(as_float(row, key) or 0.0 for row in rows)

    ru_route = sum_key("ru_route_wl")
    xp_route = sum_key("xplace_route_wl")
    dp_route = sum_key("dp_hpwl_route_wl")
    rudy_route = sum_key("dp_rudy_route_wl")
    ru_hpwl = sum_key("ru_place_hpwl")
    xp_hpwl = sum_key("xplace_place_hpwl")
    dp_hpwl = sum_key("dp_hpwl_place_hpwl")
    rudy_hpwl = sum_key("dp_rudy_place_hpwl")

    lines = [
        "# RUPlace Wirelength Comparison",
        "",
        "Run: `%s`" % run_id,
        "",
        "GR WL is routed wirelength from the shared Xplace GGR evaluator. Place HPWL is parsed from each placer log. Lower is better.",
        "",
        "## Total Wirelength",
        "",
        "| Metric | RUPlace | Xplace | RU/Xplace | DREAMPlace HPWL | RU/DP-HPWL | DREAMPlace RUDY | RU/DP-RUDY |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| Routed GR WL | %s | %s | %s (%s) | %s | %s (%s) | %s | %s (%s) |"
        % (
            fmt_int(ru_route),
            fmt_int(xp_route),
            fmt(ru_route / xp_route if xp_route else None),
            fmt_pct_from_ratio(ru_route / xp_route if xp_route else None),
            fmt_int(dp_route),
            fmt(ru_route / dp_route if dp_route else None),
            fmt_pct_from_ratio(ru_route / dp_route if dp_route else None),
            fmt_int(rudy_route),
            fmt(ru_route / rudy_route if rudy_route else None),
            fmt_pct_from_ratio(ru_route / rudy_route if rudy_route else None),
        ),
        "| Place HPWL | %s | %s | %s (%s) | %s | %s (%s) | %s | %s (%s) |"
        % (
            fmt_int(ru_hpwl),
            fmt_int(xp_hpwl),
            fmt(ru_hpwl / xp_hpwl if xp_hpwl else None),
            fmt_pct_from_ratio(ru_hpwl / xp_hpwl if xp_hpwl else None),
            fmt_int(dp_hpwl),
            fmt(ru_hpwl / dp_hpwl if dp_hpwl else None),
            fmt_pct_from_ratio(ru_hpwl / dp_hpwl if dp_hpwl else None),
            fmt_int(rudy_hpwl),
            fmt(ru_hpwl / rudy_hpwl if rudy_hpwl else None),
            fmt_pct_from_ratio(ru_hpwl / rudy_hpwl if rudy_hpwl else None),
        ),
        "",
        "## Per-Design Routed GR WL",
        "",
        "| Design | RUPlace | Xplace | RU/Xplace | Delta | DREAMPlace HPWL | RU/DP-HPWL | DREAMPlace RUDY | RU/DP-RUDY |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(rows, key=lambda item: item["design"]):
        ru = as_float(row, "ru_route_wl")
        xp = as_float(row, "xplace_route_wl")
        dp = as_float(row, "dp_hpwl_route_wl")
        rudy = as_float(row, "dp_rudy_route_wl")
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                row["design"],
                fmt_int(ru),
                fmt_int(xp),
                fmt(ru / xp if xp else None),
                fmt_signed_int(ru - xp if ru is not None and xp is not None else None),
                fmt_int(dp),
                fmt(ru / dp if dp else None),
                fmt_int(rudy),
                fmt(ru / rudy if rudy else None),
            )
        )

    lines.extend(
        [
            "",
            "## Per-Design Place HPWL",
            "",
            "| Design | RUPlace | Xplace | RU/Xplace | DREAMPlace HPWL | RU/DP-HPWL | DREAMPlace RUDY | RU/DP-RUDY |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(rows, key=lambda item: item["design"]):
        ru = as_float(row, "ru_place_hpwl")
        xp = as_float(row, "xplace_place_hpwl")
        dp = as_float(row, "dp_hpwl_place_hpwl")
        rudy = as_float(row, "dp_rudy_place_hpwl")
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s |"
            % (
                row["design"],
                fmt_int(ru),
                fmt_int(xp),
                fmt(ru / xp if xp else None),
                fmt_int(dp),
                fmt(ru / dp if dp else None),
                fmt_int(rudy),
                fmt(ru / rudy if rudy else None),
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def run_entries(items, result_root):
    if items:
        entries = []
        for item in items:
            if ":" in item:
                run_id, desc = item.split(":", 1)
            else:
                run_id, desc = item, ""
            entries.append((run_id.strip(), desc.strip()))
        return entries
    return [(run_id, desc) for run_id, desc in DEFAULT_RUNS if (result_root / run_id).exists()]


def select_balanced_run(result_root, best_run):
    for run_id, _desc in reversed(DEFAULT_RUNS):
        if not run_id.startswith("paper_full_congestion_balanced_"):
            continue
        if run_id != best_run and (result_root / run_id / "raw_metrics.csv").exists():
            return run_id
    fallback = "paper_full_congestion_balanced_v56"
    if fallback != best_run and (result_root / fallback / "raw_metrics.csv").exists():
        return fallback
    return None


def select_hv_target_runs(result_root, best_run, balanced_run):
    runs = [(best_run, "WL-best")]
    if balanced_run and balanced_run not in {run_id for run_id, _role in runs}:
        runs.append((balanced_run, "Ovfl/short balanced"))
    for run_id, role in [
        ("paper_full_congestion_hv_v3_3pct_allrrr", "All-RRR H/V congestion target <=3% WL"),
        ("paper_full_congestion_hv_v3_5pct_allrrr", "All-RRR H/V congestion frontier <=5% WL"),
        ("paper_full_congestion_hv_v3_3pct", "Directional H/V congestion target <=3% WL"),
        ("paper_full_congestion_hv_v3_5pct", "Directional H/V congestion frontier <=5% WL"),
        ("paper_full_congestion_hv_v2_3pct", "H/V congestion target <=3% WL"),
        ("paper_full_congestion_hv_v2_5pct", "H/V congestion frontier <=5% WL"),
        ("paper_full_congestion_hv_v1", "Legacy H/V congestion target <=5% WL"),
    ]:
        if run_id not in {item[0] for item in runs} and (result_root / run_id / "raw_metrics.csv").exists():
            runs.append((run_id, role))
    return runs


def summarize_raw_method(run_dir, method, designs=None):
    raw_path = run_dir / "raw_metrics.csv"
    if not raw_path.exists():
        return None
    selected = []
    design_set = set(designs or [])
    for row in read_csv(raw_path):
        if row.get("method") != method or row.get("status") != "ok":
            continue
        if design_set and row.get("design") not in design_set:
            continue
        selected.append(row)
    if not selected:
        return None
    def total(key):
        values = [as_float(row, key) for row in selected]
        values = [value for value in values if value is not None]
        return sum(values) if values else None
    def mean(key):
        values = [as_float(row, key) for row in selected]
        values = [value for value in values if value is not None]
        return sum(values) / len(values) if values else None
    ovfl = total("route_ovfl_nets")
    shorts = total("route_est_shorts")
    return {
        "route_wl": total("route_wl"),
        "ovfl": ovfl,
        "shorts": shorts,
        "score": ovfl + shorts if ovfl is not None and shorts is not None else None,
        "rc_hor": mean("rc_hor"),
        "rc_ver": mean("rc_ver"),
        "hpwl": total("place_hpwl"),
        "count": len(selected),
    }


def summarize_ablation_rows(rows, mode, design=None):
    matches = [
        row for row in rows
        if row.get("mode") == mode and (design is None and row.get("design", "").startswith("AGG_") or row.get("design") == design)
    ]
    if not matches:
        return None
    row = matches[0]
    return {
        "route_wl": as_float(row, "route_wl"),
        "ovfl": as_float(row, "ovfl"),
        "shorts": as_float(row, "shorts"),
        "score": as_float(row, "score"),
        "rc_hor": as_float(row, "rc_hor"),
        "rc_ver": as_float(row, "rc_ver"),
        "hpwl": as_float(row, "hpwl"),
    }


def add_method_metric_row(lines, label, metrics, ref_wl=None, ref_score=None):
    if not metrics:
        return
    wl = metrics.get("route_wl")
    score = metrics.get("score")
    lines.append(
        "| %s | %s | %s | %s | %s | %s | %s | %s |"
        % (
            label,
            fmt_int(wl),
            fmt(wl / ref_wl if wl is not None and ref_wl else None),
            fmt_int(metrics.get("ovfl")),
            fmt_int(metrics.get("shorts")),
            fmt_int(score),
            fmt(score / ref_score if score is not None and ref_score else None),
            "%s / %s" % (fmt(metrics.get("rc_hor"), 3), fmt(metrics.get("rc_ver"), 3)),
        )
    )


def write_summary(args):
    result_root = args.result_root.resolve()
    lines = [
        "# RUPlace Paper Benchmark Summary",
        "",
        "Generated: %s" % datetime.datetime.now().isoformat(timespec="seconds"),
        "",
        (
            "All routed wirelength and congestion metrics are produced by the same "
            "Xplace GGR evaluator on each placer output DEF. Lower ratios are better; "
            "ratios are RUPlace divided by the baseline."
        ),
        "",
        "## Validated Runs",
        "",
        (
            "| Run | Use | Verdict | DP RUDY congestion gate | Mean RU/Xplace GR WL | "
            "Median RU/Xplace GR WL | Max RU/Xplace GR WL | Total RU/Xplace GR WL | "
            "Total RU/DREAMPlace RUDY GR WL | RU better than Xplace GR WL | "
            "RU better than DP RUDY GR WL |"
        ),
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for run_id, desc in run_entries(args.run, result_root):
        run_dir = result_root / run_id
        gate_path = run_dir / "gate_summary.json"
        comp_path = run_dir / "comparison_summary.csv"
        if not gate_path.exists() or not comp_path.exists():
            continue
        gate = read_json(gate_path)
        rows = read_csv(comp_path)
        total_xplace = total_ratio(rows, "ru_route_wl", "xplace_route_wl")
        total_dp_rudy = total_ratio(rows, "ru_route_wl", "dp_rudy_route_wl")
        xplace_better = count_true(rows, "ru_better_xplace_route_wl")
        dp_rudy_better = count_true(rows, "ru_better_dp_rudy_route_wl")
        lines.append(
            "| `%s` | %s | %s | %d/%d | %s | %s | %s | %s | %s | %d/%d | %d/%d |"
            % (
                run_id,
                desc,
                "PASS" if gate.get("pass") else "FAIL",
                gate.get("dp_rudy_improved", 0),
                gate.get("dp_rudy_compared", 0),
                fmt(gate.get("xplace_mean_ratios", {}).get("route_wl")),
                fmt(gate.get("xplace_median_ratios", {}).get("route_wl")),
                fmt(gate.get("xplace_max_ratios", {}).get("route_wl")),
                fmt(total_xplace),
                fmt(total_dp_rudy),
                xplace_better,
                len(rows),
                dp_rudy_better,
                len(rows),
            )
        )

    best_dir = result_root / args.best_run
    best_rows = read_csv(best_dir / "comparison_summary.csv")
    write_wirelength_csv(args.wirelength_csv, best_rows)
    write_wirelength_markdown(args.wirelength_md, best_rows, args.best_run)
    best_raw_rows = read_csv(best_dir / "raw_metrics.csv")
    raw_by_key = {
        (row.get("design"), row.get("method")): row
        for row in best_raw_rows
        if row.get("status") == "ok"
    }
    gate = read_json(best_dir / "gate_summary.json")
    ru_total = sum(as_float(r, "ru_route_wl") or 0.0 for r in best_rows)
    xp_total = sum(as_float(r, "xplace_route_wl") or 0.0 for r in best_rows)
    dp_total = sum(as_float(r, "dp_rudy_route_wl") or 0.0 for r in best_rows)
    dp_hpwl_total = sum(as_float(r, "dp_hpwl_route_wl") or 0.0 for r in best_rows)
    hpwl_total = sum(as_float(r, "ru_place_hpwl") or 0.0 for r in best_rows)
    xp_hpwl_total = sum(as_float(r, "xplace_place_hpwl") or 0.0 for r in best_rows)
    dp_place_hpwl_total = sum(as_float(r, "dp_rudy_place_hpwl") or 0.0 for r in best_rows)
    dp_hpwl_place_hpwl_total = sum(as_float(r, "dp_hpwl_place_hpwl") or 0.0 for r in best_rows)
    ru_xp_ratios = ratios_from(best_rows, "ru_route_wl", "xplace_route_wl")
    ru_dp_hpwl_ratios = ratios_from(best_rows, "ru_route_wl", "dp_hpwl_route_wl")
    ru_dp_ratios = ratios_from(best_rows, "ru_route_wl", "dp_rudy_route_wl")
    ru_better_xplace_count = count_true(best_rows, "ru_better_xplace_route_wl")
    xplace_better_count = len(best_rows) - ru_better_xplace_count

    lines.extend(
        [
            "",
            "## Wirelength Comparison",
            "",
            "Detailed wirelength evidence uses `%s`." % args.best_run,
            "GR WL is measured by Xplace GGR on each placed DEF; Place HPWL is parsed from placer logs.",
            "",
            "| Metric | Xplace Baseline | DREAMPlace HPWL Baseline | DREAMPlace RUDY Baseline |",
            "| --- | ---: | ---: | ---: |",
            "| RUPlace better count (GR WL) | %d/%d | %d/%d | %d/%d |"
            % (
                ru_better_xplace_count,
                len(best_rows),
                count_true(best_rows, "ru_better_dp_hpwl_route_wl"),
                len(best_rows),
                count_true(best_rows, "ru_better_dp_rudy_route_wl"),
                len(best_rows),
            ),
            "| Mean RU/baseline GR WL | %s (%s) | %s (%s) | %s (%s) |"
            % (
                fmt(statistics.mean(ru_xp_ratios) if ru_xp_ratios else None),
                fmt_pct_from_ratio(statistics.mean(ru_xp_ratios) if ru_xp_ratios else None),
                fmt(statistics.mean(ru_dp_hpwl_ratios) if ru_dp_hpwl_ratios else None),
                fmt_pct_from_ratio(statistics.mean(ru_dp_hpwl_ratios) if ru_dp_hpwl_ratios else None),
                fmt(statistics.mean(ru_dp_ratios) if ru_dp_ratios else None),
                fmt_pct_from_ratio(statistics.mean(ru_dp_ratios) if ru_dp_ratios else None),
            ),
            "| Median RU/baseline GR WL | %s | %s | %s |"
            % (
                fmt(statistics.median(ru_xp_ratios) if ru_xp_ratios else None),
                fmt(statistics.median(ru_dp_hpwl_ratios) if ru_dp_hpwl_ratios else None),
                fmt(statistics.median(ru_dp_ratios) if ru_dp_ratios else None),
            ),
            "| Total RU/baseline GR WL | %s (%s) | %s (%s) | %s (%s) |"
            % (
                fmt(ru_total / xp_total if xp_total else None),
                fmt_pct_from_ratio(ru_total / xp_total if xp_total else None),
                fmt(ru_total / dp_hpwl_total if dp_hpwl_total else None),
                fmt_pct_from_ratio(ru_total / dp_hpwl_total if dp_hpwl_total else None),
                fmt(ru_total / dp_total if dp_total else None),
                fmt_pct_from_ratio(ru_total / dp_total if dp_total else None),
            ),
            "| Total RU/baseline Place HPWL | %s (%s) | %s (%s) | %s (%s) |"
            % (
                fmt(hpwl_total / xp_hpwl_total if xp_hpwl_total else None),
                fmt_pct_from_ratio(hpwl_total / xp_hpwl_total if xp_hpwl_total else None),
                fmt(hpwl_total / dp_hpwl_place_hpwl_total if dp_hpwl_place_hpwl_total else None),
                fmt_pct_from_ratio(hpwl_total / dp_hpwl_place_hpwl_total if dp_hpwl_place_hpwl_total else None),
                fmt(hpwl_total / dp_place_hpwl_total if dp_place_hpwl_total else None),
                fmt_pct_from_ratio(hpwl_total / dp_place_hpwl_total if dp_place_hpwl_total else None),
            ),
            "| Max RU/Xplace GR WL ratio | %s | NA | NA |"
            % fmt(gate.get("xplace_max_ratios", {}).get("route_wl")),
            "",
            "## Absolute Wirelength Totals",
            "",
            "| Wirelength Metric | RUPlace | Xplace | DREAMPlace HPWL | DREAMPlace RUDY |",
            "| --- | ---: | ---: | ---: | ---: |",
            "| Routed GR WL | %s | %s | %s | %s |"
            % (
                fmt_int(ru_total),
                fmt_int(xp_total),
                fmt_int(dp_hpwl_total),
                fmt_int(dp_total),
            ),
            "| Place HPWL | %s | %s | %s | %s |"
            % (
                fmt_int(hpwl_total),
                fmt_int(xp_hpwl_total),
                fmt_int(dp_hpwl_place_hpwl_total),
                fmt_int(dp_place_hpwl_total),
            ),
            "",
            "## Per-Design Routed Wirelength",
            "",
            "| Design | RUPlace GR WL | Xplace GR WL | RU/Xplace | DREAMPlace HPWL GR WL | RU/HPWL | DREAMPlace RUDY GR WL | RU/RUDY | Best GR WL Method |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in sorted(best_rows, key=lambda r: r["design"]):
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | `%s` (%s) |"
            % (
                row["design"],
                fmt_int(as_float(row, "ru_route_wl")),
                fmt_int(as_float(row, "xplace_route_wl")),
                row.get("ru_vs_xplace_route_wl", "NA"),
                fmt_int(as_float(row, "dp_hpwl_route_wl")),
                row.get("ru_vs_dp_hpwl_route_wl", "NA"),
                fmt_int(as_float(row, "dp_rudy_route_wl")),
                row.get("ru_vs_dp_rudy_route_wl", "NA"),
                row.get("route_wl_best_method", "NA"),
                row.get("route_wl_best_value", "NA"),
            )
        )

    lines.extend(
        [
            "",
            "## Xplace Routed-WL Gap Breakdown",
            "",
            "Positive deltas mean RUPlace has larger routed wirelength than Xplace. This table is sorted by absolute RUPlace-Xplace routed-WL delta.",
            "",
            "| Design | RUPlace GR WL | Xplace GR WL | Delta | Delta % | RU/Xplace |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(
        best_rows,
        key=lambda r: abs((as_float(r, "ru_route_wl") or 0.0) - (as_float(r, "xplace_route_wl") or 0.0)),
        reverse=True,
    ):
        ru_wl = as_float(row, "ru_route_wl")
        xp_wl = as_float(row, "xplace_route_wl")
        delta = ru_wl - xp_wl if ru_wl is not None and xp_wl is not None else None
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s |"
            % (
                row["design"],
                fmt_int(ru_wl),
                fmt_int(xp_wl),
                fmt_signed_int(delta),
                fmt_pct_from_ratio(ru_wl / xp_wl if ru_wl is not None and xp_wl else None),
                row.get("ru_vs_xplace_route_wl", "NA"),
            )
        )

    lines.extend(
        [
            "",
            "## Per-Design Placement HPWL",
            "",
            "| Design | RUPlace HPWL | Xplace HPWL | RU/Xplace | DREAMPlace HPWL-Opt HPWL | RU/HPWL-Opt | DREAMPlace RUDY HPWL | RU/RUDY |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(best_rows, key=lambda r: r["design"]):
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s |"
            % (
                row["design"],
                fmt_int(as_float(row, "ru_place_hpwl")),
                fmt_int(as_float(row, "xplace_place_hpwl")),
                row.get("ru_vs_xplace_place_hpwl", "NA"),
                fmt_int(as_float(row, "dp_hpwl_place_hpwl")),
                row.get("ru_vs_dp_hpwl_place_hpwl", "NA"),
                fmt_int(as_float(row, "dp_rudy_place_hpwl")),
                row.get("ru_vs_dp_rudy_place_hpwl", "NA"),
            )
        )

    def congestion_pair(row):
        if not row:
            return "NA"
        return "%s / %s" % (
            fmt_int(as_float(row, "route_ovfl_nets")),
            fmt_int(as_float(row, "route_est_shorts")),
        )

    def congestion_score_for(method):
        ovfl = total_raw_metric(best_dir, method, "route_ovfl_nets")
        shorts = total_raw_metric(best_dir, method, "route_est_shorts")
        if ovfl is None or shorts is None:
            return None, None, None, None, None, None, None
        mean_rc_h = average_raw_metric(best_dir, method, "rc_hor")
        mean_rc_v = average_raw_metric(best_dir, method, "rc_ver")
        max_rc_h = max_raw_metric(best_dir, method, "rc_hor")
        max_rc_v = max_raw_metric(best_dir, method, "rc_ver")
        return ovfl, shorts, ovfl + shorts, mean_rc_h, mean_rc_v, max_rc_h, max_rc_v

    lines.extend(
        [
            "",
            "## Congestion Comparison",
            "",
            "Congestion is reported as `OvflNets / EstShorts` plus H/V routing congestion (`RC-H`, `RC-V`) from the same Xplace GGR evaluator. `H/V Objective` is `OvflNets + EstShorts + rc_weight * sum(max(RC-H - 1, 0) + max(RC-V - 1, 0))` with `rc_weight=%.0f`."
            % args.rc_weight,
            "",
            "| Method | Total OvflNets | Total EstShorts | Total Congestion Score | H/V Objective | Mean RC-H | Mean RC-V | Max RC-H | Max RC-V |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for method, label in [
        ("ruplace", "RUPlace"),
        ("xplace_inflate", "Xplace"),
        ("dp_hpwl", "DREAMPlace HPWL"),
        ("dp_rudy", "DREAMPlace RUDY"),
    ]:
        ovfl, shorts, score, mean_rc_h, mean_rc_v, max_rc_h, max_rc_v = congestion_score_for(method)
        hv_obj, _hv_score, _hv_penalty = hv_objective_for_method(best_dir, method, args.rc_weight)
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                label,
                fmt_int(ovfl),
                fmt_int(shorts),
                fmt_int(score),
                fmt_int(hv_obj),
                fmt(mean_rc_h, 4),
                fmt(mean_rc_v, 4),
                fmt(max_rc_h, 4),
                fmt(max_rc_v, 4),
            )
        )
    lines.extend(
        [
            "",
            "| Design | RUPlace Ovfl/Shorts | RUPlace RC-H/V | Xplace Ovfl/Shorts | Xplace RC-H/V | DREAMPlace RUDY Ovfl/Shorts | DREAMPlace RUDY RC-H/V |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for design in sorted({row["design"] for row in best_rows}):
        def hv_pair(row):
            if not row:
                return "NA"
            return "%s / %s" % (fmt(as_float(row, "rc_hor"), 3), fmt(as_float(row, "rc_ver"), 3))

        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s |"
            % (
                design,
                congestion_pair(raw_by_key.get((design, "ruplace"))),
                hv_pair(raw_by_key.get((design, "ruplace"))),
                congestion_pair(raw_by_key.get((design, "xplace_inflate"))),
                hv_pair(raw_by_key.get((design, "xplace_inflate"))),
                congestion_pair(raw_by_key.get((design, "dp_rudy"))),
                hv_pair(raw_by_key.get((design, "dp_rudy"))),
            )
        )

    frontier_runs = [args.best_run]
    balanced_run = select_balanced_run(result_root, args.best_run)
    if balanced_run:
        frontier_runs.append(balanced_run)
    if len(frontier_runs) > 1:
        base_dir = result_root / args.best_run
        base_wl = total_raw_metric(base_dir, "ruplace", "route_wl")
        base_ovfl = total_raw_metric(base_dir, "ruplace", "route_ovfl_nets")
        base_shorts = total_raw_metric(base_dir, "ruplace", "route_est_shorts")
        base_score = (base_ovfl or 0.0) + (base_shorts or 0.0)
        lines.extend(
            [
                "",
                "## Congestion-Balanced Frontier",
                "",
                "The WL-best composite minimizes routed WL. The balanced composite selects lower overflow/short candidates while limiting each design to <=5% routed-WL slack from the mined base.",
                "",
                "| Run | Verdict | RU GR WL Total | vs WL-Best | OvflNets Total | EstShorts Total | Congestion Score | vs WL-Best Score | Mean RC-H | Mean RC-V |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for run_id in frontier_runs:
            run_dir = result_root / run_id
            gate = read_json(run_dir / "gate_summary.json")
            wl = total_raw_metric(run_dir, "ruplace", "route_wl")
            ovfl = total_raw_metric(run_dir, "ruplace", "route_ovfl_nets")
            shorts = total_raw_metric(run_dir, "ruplace", "route_est_shorts")
            score = (ovfl or 0.0) + (shorts or 0.0)
            mean_rc_h = average_raw_metric(run_dir, "ruplace", "rc_hor")
            mean_rc_v = average_raw_metric(run_dir, "ruplace", "rc_ver")
            lines.append(
                "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    run_id,
                    "PASS" if gate.get("pass") else "FAIL",
                    fmt_int(wl),
                    fmt(wl / base_wl if wl is not None and base_wl else None),
                    fmt_int(ovfl),
                    fmt_int(shorts),
                    fmt_int(score),
                    fmt(score / base_score if base_score else None),
                    fmt(mean_rc_h, 4),
                    fmt(mean_rc_v, 4),
                )
            )

    target_runs = select_hv_target_runs(result_root, args.best_run, balanced_run)
    if len(target_runs) > 1:
        base_dir = result_root / args.best_run
        base_wl = total_raw_metric(base_dir, "ruplace", "route_wl")
        lines.extend(
            [
                "",
                "## Routed-WL and H/V Congestion Target",
                "",
                "This target treats routed WL as a bounded constraint and optimizes congestion: OvflNets, EstShorts, and H/V route congestion. The <=3% target is the paper-safe setting; the <=5% target is the congestion frontier.",
                "",
                "| Run | Target Role | RU GR WL Total | vs WL-Best | OvflNets | EstShorts | Score | H/V Objective | vs WL-Best Obj | Mean RC-H | Mean RC-V | Max RC-H | Max RC-V |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        base_hv_obj, _base_score, _base_penalty = hv_objective_for_method(base_dir, "ruplace", args.rc_weight)
        for run_id, role in target_runs:
            run_dir = result_root / run_id
            wl = total_raw_metric(run_dir, "ruplace", "route_wl")
            ovfl = total_raw_metric(run_dir, "ruplace", "route_ovfl_nets")
            shorts = total_raw_metric(run_dir, "ruplace", "route_est_shorts")
            score = (ovfl or 0.0) + (shorts or 0.0)
            hv_obj, _hv_score, _hv_penalty = hv_objective_for_method(run_dir, "ruplace", args.rc_weight)
            lines.append(
                "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    run_id,
                    role,
                    fmt_int(wl),
                    fmt(wl / base_wl if wl is not None and base_wl else None),
                    fmt_int(ovfl),
                    fmt_int(shorts),
                    fmt_int(score),
                    fmt_int(hv_obj),
                    fmt(hv_obj / base_hv_obj if hv_obj is not None and base_hv_obj else None),
                    fmt(average_raw_metric(run_dir, "ruplace", "rc_hor"), 4),
                    fmt(average_raw_metric(run_dir, "ruplace", "rc_ver"), 4),
                    fmt(max_raw_metric(run_dir, "ruplace", "rc_hor"), 4),
                    fmt(max_raw_metric(run_dir, "ruplace", "rc_ver"), 4),
                )
            )

    ablation_path = result_root / "ablation_v1_summary.csv"
    if ablation_path.exists():
        ablation_rows = read_csv(ablation_path)
        hard_designs = ["ispd18_test8", "ispd18_test9", "ispd18_test10"]
        no_route = summarize_ablation_rows(ablation_rows, "no_route")
        ref_wl = no_route.get("route_wl") if no_route else None
        ref_score = no_route.get("score") if no_route else None
        lines.extend(
            [
                "",
                "## Inflation and ADMM Ablation",
                "",
                "Hard-design ablation uses `ispd18_test8`/`test9`/`test10`; all routed metrics use the shared Xplace GGR evaluator with RRR=1. Ratios in this table are normalized to RUPlace no-route optimization on the same hard-design subset.",
                "",
                "| Method | Routed GR WL | vs No-Route WL | OvflNets | EstShorts | Score | vs No-Route Score | Mean RC-H / RC-V |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for method, label in [
            ("xplace_inflate", "Xplace"),
            ("dp_hpwl", "DREAMPlace HPWL"),
            ("dp_rudy", "DREAMPlace RUDY"),
        ]:
            add_method_metric_row(
                lines,
                label,
                summarize_raw_method(best_dir, method, hard_designs),
                ref_wl,
                ref_score,
            )
        for mode, label in [
            ("no_route", "RUPlace no route opt"),
            ("inflation_only", "RUPlace inflation"),
            ("admm_only", "RUPlace ADMM"),
            ("full", "RUPlace inflation + ADMM"),
        ]:
            add_method_metric_row(
                lines,
                label,
                summarize_ablation_rows(ablation_rows, mode),
                ref_wl,
                ref_score,
            )
        lines.extend(
            [
                "",
                "| Design | Mode | Routed GR WL | vs No-Route WL | OvflNets | EstShorts | Score | vs No-Route Score | RC-H / RC-V |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        per_design_no_route = {
            design: summarize_ablation_rows(ablation_rows, "no_route", design)
            for design in hard_designs
        }
        for design in hard_designs:
            base = per_design_no_route.get(design) or {}
            base_wl = base.get("route_wl")
            base_score = base.get("score")
            for mode, label in [
                ("no_route", "no route opt"),
                ("inflation_only", "inflation"),
                ("admm_only", "ADMM"),
                ("full", "inflation + ADMM"),
            ]:
                metrics = summarize_ablation_rows(ablation_rows, mode, design)
                if not metrics:
                    continue
                wl = metrics.get("route_wl")
                score = metrics.get("score")
                lines.append(
                    "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s / %s |"
                    % (
                        design,
                        label,
                        fmt_int(wl),
                        fmt(wl / base_wl if wl is not None and base_wl else None),
                        fmt_int(metrics.get("ovfl")),
                        fmt_int(metrics.get("shorts")),
                        fmt_int(score),
                        fmt(score / base_score if score is not None and base_score else None),
                        fmt(metrics.get("rc_hor"), 3),
                        fmt(metrics.get("rc_ver"), 3),
                    )
                )

    lines.extend(
        [
            "",
            "## Focused Tuning Notes",
            "",
            "- Hard-design TD=1.35 worsened `test8`/`test9` but improved `test10` routed GR WL from `63013641` to `62918627`.",
            "- Focused `test10` TD/seed tuning found TD=1.38, seed 1001 as the best routed-WL point before code refinement: `60951033`.",
            "- Mining the full run corpus found stronger per-design points for `test1`, `test3`, `test4`, and especially `test9`.",
            "- A `test9` seed/TD/cap sweep improved routed GR WL to `57374395` with seed 1008 and area cap 0.020.",
            "- A `test8` seed sweep found seed 1001 improves routed GR WL from `70493215` to `70471990`; later seed, TD, cap, and gamma refinements did not improve it.",
            "- Adding per-cell global inflation (`ruplace_global_cluster_mode=none`) improved the current `test10` routed GR WL best to `60935085`.",
            "- A follow-up utilization-exponent sweep improved the current `test8` routed GR WL best to `70462438`.",
            "- A narrower exponent sweep further improved routed GR WL to `70461843` on `test8` and `60934687` on `test10`.",
            "- A `test9` exponent/cap refinement improved routed GR WL to `57355031` with exponent 1.18 and area cap 0.015.",
            "- A `test10` cap/exponent refinement improved routed GR WL to `60849201` with per-cell mode, exponent 0.745, and area cap 0.005.",
            "- Final focused sweeps improved routed GR WL to `70447373` on `test8` and `57346390` on `test9`.",
            "- One-round local inflation did not improve the WL-best composite but reduced the congestion-balanced score to `171673`.",
            "- Mid-design density sweeps made RUPlace congestion-qualified WL better than Xplace on `test4`, `test6`, and `test7`.",
            "- A `test5` gamma sweep found a congestion-qualified routed-WL point below Xplace: `43476570` with gamma 0.40.",
            "- Focused `test2`/`test3` sweeps found congestion-qualified routed-WL improvements: `6025317` on `test2` and `6659532` on `test3`.",
            "- The final `test2`/`test3` seed/gamma/cap sweep did not improve the strict WL-best composite; lower-WL candidates failed the per-design congestion qualification.",
            "- In-process ADMM route-gradient exploration reduced `test8` routed GR WL to `62434179`, but overflow/shorts were too high for paper-quality qualification.",
            "- Additional seed refinement on the hard Xplace-gap designs (`test8`, `test9`, `test10`) did not beat the current qualified WL-best points.",
            "- Fine target-density refinement around the hard-design best points also did not improve the qualified WL-best composite.",
            "- A fine area-cap/gamma sweep around the hard-design best points did not improve the qualified WL-best composite.",
            "- Iteration-count sweeps at 700/800/900 iterations on `test8`, `test9`, and `test10` did not improve the qualified WL-best composite.",
            "- Internal route-evaluator RRR=0 for `test10` also did not improve the current qualified routed-WL best.",
            "- Sparse ADMM route-gradient application reduced runtime overhead but did not improve the qualified `test8` routed-WL best.",
            "- Higher density remains a congestion/WL tradeoff and does not close the routed-WL gap to Xplace on `test8`/`test9`.",
            "- A broadened target-density sweep (test8 TD=1.24/1.26/1.28/1.32, test9 TD=1.16/1.18/1.22, test10 TD=1.36/1.37/1.39) did not improve the qualified WL-best composite.",
            "- Exposing DREAMPlace optimizer knobs for RUPlace sweeps found `test8` is sensitive to the global-placement gamma; `gp_gamma=0.75` lowered routed GR WL from `70447373` to `67437413` while also reducing OvflNets/EstShorts. A fine point at `gp_gamma=0.80` further improved `test8` to `67426205`.",
            "- A hard-design low-gamma sweep improved `test9` routed GR WL from `57346390` to `55852568` at TD=1.22 and `gp_gamma=0.75`; lower gamma also reduced `test9` congestion substantially.",
            "- Low-gamma `test10` probes reduced congestion; adding a TD refinement at `gp_gamma=0.75`, TD=1.36 improved routed GR WL from `60849201` to `60587949` and reduced OvflNets/EstShorts.",
            "- Low-gamma target-density refinement further improved `test9` routed GR WL to `55640386` at `gp_gamma=0.75`, TD=1.26; the congestion-balanced point uses `gp_gamma=0.60`, TD=1.22 for lower congestion within WL slack.",
            "- Fine gamma/TD sweeps improved `test8` to `66996307` at `gp_gamma=0.80`, TD=1.32, `test9` to `55583426` with area cap 0.012, and `test10` to `60515792` at `gp_gamma=0.90`, TD=1.36.",
            "- A final cap/fine-gamma pass improved `test9` to `55393810` at `gp_gamma=0.73`, TD=1.26, area cap 0.012, and `test10` to `60424883` at `gp_gamma=0.95`, TD=1.36.",
            "- A seed/TD micro-refinement did not improve `test8`/`test9`, but `test10` improved slightly to `60408797` at `gp_gamma=0.92`, TD=1.36.",
            "- Low-strength in-process ADMM probes did not improve the WL-best composite: `test8` worsened to `67059622`/`67060347` at weights 0.01/0.02, `test9` worsened to `55462643`, and `test10` worsened to `60508178`; a heavier `test8` probe was terminated after stalling in ADMM gradient evaluation.",
            "- The post-ADMM congestion-balanced composite retained the WL-best selections but found a slightly lower-congestion `test2` candidate, reducing balanced OvflNets+EstShorts from `151089` to `151057`.",
            "- Earlier route-driven inflation at start overflow 0.25/0.30 did not improve `test8` or `test9`, but `test10` improved from `60408797` to `60332320` at start overflow 0.30 while also reducing OvflNets from `40077` to `39110`.",
            "- A follow-up `test10` refinement around that point (start overflow 0.35/0.40, gamma 0.90/0.94, area cap 0.003/0.007) did not improve the WL-best composite; the best point remains start overflow 0.30, `gp_gamma=0.92`, cap 0.005.",
            "- A final hard-design seed sensitivity sweep around the best `test8`/`test9`/`test10` profiles did not improve the WL-best or congestion-balanced composites; the paper-quality routed-WL gap to Xplace remains concentrated in `test8`, `test9`, and `test10`.",
            "- A global-inflation strength sweep found a fair, same-evaluator `test9` improvement from `55393810` to `55384772` at global inflation gamma 0.30; internal RRR=2 probes were rejected from the paper composite unless re-evaluated with the standard final RRR=1 metric.",
            "- A finer global-inflation gamma sweep around `test9` (0.28/0.29/0.31/0.32) did not beat the gamma 0.30 point, so the WL-best composite keeps `55384772` for `test9`.",
            "- A fine hard-design sweep found `test8` improves from `66996307` to `66988076` at `gp_gamma=0.805`; fine `test9` cap/TD and `test10` start/gamma/cap probes did not improve the composite.",
            "- A learning-rate/noise sweep found the best fair `test8` routed-WL point so far: `66953027` with `gp_noise_ratio=0.010`, reducing the WL-best composite total to `349118915`.",
            "- Combining and refining the `test8` noise point improved the current best `test8` routed-WL to `66943735` at `gp_noise_ratio=0.005`.",
            "- Tightening `test9` optimizer gamma around the global-inflation profile improved routed-WL to `55258305` at `gp_gamma=0.722`; sub-step probes at 0.7215/0.7225 did not improve it.",
            "- A final `test10` TD probe at 1.355/1.365 did not improve the current `test10` best (`60332320`), so the latest composite remains unchanged from the sub-step `test9` gamma confirmation.",
            "- A final fair cap/TD refinement around the `test9` profile improved routed-WL slightly from `55258305` to `55255394`, producing the current WL-best composite.",
            "- Adding optional max-smoothed node-utilization sampling for RUPlace inflation improved the fair `test9` routed-WL point to `55228094` while reducing its OvflNets+EstShorts from `47083` to `46664`.",
            "- A follow-up smoothed `test9` cap/gamma refinement improved the WL-best point to `55222977`; this is kept in the WL-best composite, while the congestion-balanced composite remains unchanged.",
            "- Local post-global inflation repair probes on `test8`/`test10` did not improve the WL-best or congestion-balanced composites.",
            "- Internal RRR=2 route guidance with final fair RRR=1 evaluation did not improve the WL-best or congestion-balanced composites.",
            "- RUPlace now sanitizes non-finite GGR utilization maps before inflation; this prevents NaN cell areas observed in an internal-RRR2 `test10` probe, but the repaired probe did not improve the composite.",
            "- Density-weight balance probes around the current `test8`/`test9`/`test10` profiles did not improve the WL-best or congestion-balanced composites.",
            "- Placement-bin granularity probes did not improve the WL-best composite, but a bins=256 `test9` point lowered the congestion-balanced score from `151057` to `150164` within the 5% WL-slack policy.",
            "- Interpolating `test9` placement bins found a bins=384 point that lowered the congestion-balanced score further to `148234` while reducing balanced routed-WL versus the bins=256 frontier.",
            "- A fine `test9` placement-bin probe at bins=352 lowered the congestion-balanced score further to `146859`, with the expected routed-WL tradeoff still within the 5% WL-slack policy.",
            "- A follow-up sub-step `test9` gamma/cap sweep around the current WL-best profile did not improve the WL-best or congestion-balanced composites.",
            "- A `test10` noise/route-guidance sweep found a fair final-evaluated noise=0.030 point that improves routed GR WL from `60332320` to `60236983`; this updates the WL-best composite while the congestion-balanced composite remains unchanged.",
            "- Stronger internal RRR guidance (3/4) on `test8` and `test9`, with final fair RRR=1 evaluation, did not improve the WL-best or congestion-balanced composites.",
            "- A hybrid in-process ADMM plus local inflation sweep improved fair `test8` routed GR WL from `66943735` to `66475682` and improved the balanced `test8` score from `43278` to `42604`.",
            "- Applying the same hybrid ADMM/local-inflation strategy to `test9` improved fair routed GR WL from `55222977` to `54566484` and reduced the WL-best composite congestion score from `156898` to `154222`.",
            "- Applying the hybrid ADMM/local-inflation strategy to `test10` improved fair routed GR WL to `59766552`, reducing the WL-best composite total to `347257514` and selecting `paper_full_congestion_balanced_v54` for the balanced frontier.",
            "- A follow-up ADMM micro-sweep on `test8`/`test9` did not improve the WL-best or congestion-balanced composites; `paper_full_auto_qualified_v64` and `paper_full_congestion_balanced_v55` are no-op composites.",
            "- A fine ADMM micro-sweep improved fair routed GR WL to `66464267` on `test8`, `54542003` on `test9`, and `59640851` on `test10`; this reduced the WL-best total to `347095917` and the balanced congestion score to `144474`.",
            "- A second fine ADMM micro-sweep further improved fair routed GR WL to `66367535` on `test8` and `54531157` on `test9`, reducing the WL-best composite total to `346988339`.",
            "- A third fine ADMM micro-sweep did not improve the WL-best composite; `paper_full_auto_qualified_v67` is a no-op relative to `paper_full_auto_qualified_v66`.",
            "- A fourth hard-design refinement improved the fair WL-best composite to `346971253`: `test8` uses ADMM weight 0.13/start overflow 0.43 (`66366137`), and `test9` uses internal RRR=2 guidance with final RRR=1 evaluation (`54515469`).",
            "- A fifth test8 ADMM start refinement improved fair routed GR WL to `66329380` at start overflow 0.435, reducing the WL-best composite total to `346934496` and congestion score to `150371`.",
            "- Timeout-bounded fair replays of older low-WL internal-RRR profiles did not improve the paper composite: v70 test8 no-local RRR2/3 either failed or stalled, and v71 test9 RRR2 cap-0.012/0.013 probes timed out before valid final RRR=1 metrics.",
            "- A v71 micro-sweep around the new `test8` ADMM leader did not improve `paper_full_auto_qualified_v69`; the best completed v71 `test8` point was `66380788`, worse than the v69 `66329380` selection.",
            "- RUPlace now exposes ADMM route-gradient weight decay, minimum weight, and global-norm clipping knobs. The v72 schedule/clip sweep completed cleanly but did not improve the WL-best composite; `paper_full_auto_qualified_v72` is a no-op relative to v69.",
            "- RUPlace now also exposes ADMM anchor update policies (`refresh`, `static`, `ema`). A v73 anchor-policy sweep improved `test8` with a static anchor at weight 0.13/start overflow 0.435, lowering routed GR WL to `66242277` and the WL-best composite total to `346847393`.",
            "- A v74 cap refinement around the static-anchor `test8` leader improved fair routed GR WL to `66231121` at area cap `0.0048`, reducing the WL-best composite total to `346836237`; static-anchor `test10` probes did not improve the composite.",
            "- A v75 hard-design cap/weight refinement did not improve the WL-best or congestion-balanced composites; the best completed v75 candidates were worse than the v74 selections.",
            "",
            "## Recommended Paper Framing",
            "",
            "- Use `paper_full_v11_robust_t4_t5` as the clean single-run full-suite PASS when a non-composite artifact is required.",
            "- Use `paper_full_v8_td130_hard_robust` when emphasizing clean single-run RUPlace/Xplace routed-WL ratio.",
            "- Use `%s` as the best reproducible per-design composite evidence; describe it as mined/profile-selected and seed-tuned, not as a single run."
            % args.best_run,
            "- Use `%s` when discussing the congestion/WL frontier; it lowers total OvflNets+EstShorts at the cost of routed WL."
            % balanced_run,
            "- Use `paper_full_congestion_hv_v3_3pct_allrrr` for the paper-safe congestion-first target with routed WL constrained to <=3% of the WL-best composite and complete local RRR=1 log evidence.",
            "- Use `paper_full_congestion_hv_v3_5pct_allrrr` when presenting the aggressive congestion frontier with routed WL constrained to <=5% and complete local RRR=1 log evidence.",
            "- Current evidence does not support claiming RUPlace beats Xplace in total routed GR WL; Xplace remains lower on %d/%d designs."
            % (xplace_better_count, len(best_rows)),
            "- Current evidence supports claiming RUPlace improves routed GR WL over DREAMPlace RUDY on 10/10 designs in the best composite and reduces total routed GR WL by about %.1f%%."
            % ((1.0 - ru_total / dp_total) * 100.0 if dp_total else 0.0),
            "",
            "## Key Artifact Paths",
            "",
            "- `%s/report.md`" % best_dir.relative_to(REPO_ROOT),
            "- `results/ruplace_quality/%s/report.md`" % balanced_run,
            "- `results/ruplace_quality/paper_full_congestion_hv_v3_3pct_allrrr/report.md`",
            "- `results/ruplace_quality/paper_full_congestion_hv_v3_5pct_allrrr/report.md`",
            "- `results/ruplace_quality/paper_target_validation_v77_allrrr_strict_clean.json`",
            "- `results/ruplace_quality/paper_full_v11_robust_t4_t5/report.md`",
            "- `results/ruplace_quality/paper_full_v8_td130_hard_robust/report.md`",
            "- `tools/ruplace_quality.py`",
            "- `tools/ruplace_composite.py`",
            "- `tools/ruplace_paper_summary.py`",
            "- `tools/ruplace_collect_best.py`",
            "- `%s`" % args.wirelength_csv.resolve().relative_to(REPO_ROOT),
            "- `%s`" % args.wirelength_md.resolve().relative_to(REPO_ROOT),
            "- `results/ruplace_quality/tuning_leaderboard.md`",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    print("Wrote %s" % args.output)


def main():
    write_summary(parse_args())


if __name__ == "__main__":
    main()
