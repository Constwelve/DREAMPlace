"""Summarize the v128 net-weighting batch. Run from the worktree root."""
import csv, json, os, re, sys, glob

CASE = "regression_s14"
CSV = "results/s14_innovus/%s.csv" % CASE
BASE_WL = 11166015.781   # s14_regression_s14_v116_ref_s1001, dp_hpwl, same base flags
BASE_H, BASE_V = 13.02, 7.35

rows = {}
with open(CSV) as fh:
    for r in csv.DictReader(fh):
        if "_v128_" in (r.get("run_id") or ""):
            rows[r["run_id"]] = r

def logstats(run_id):
    log = "results/ruplace_quality/%s/dreamplace/ruplace/%s/dreamplace.log" % (run_id, CASE)
    out = {"routes": None, "iters": None, "place_s": None, "updates": None,
           "mean_ratio": None, "max_ratio": None, "sat": None, "score_over1": None,
           "grad_attempts": None}
    if not os.path.exists(log):
        return out
    routes = 0
    last_iter = None
    elapsed = None
    summary = None
    with open(log, errors="ignore") as fh:
        for line in fh:
            if "RUPlace GR grid:" in line:
                routes += 1
            elif "DREAMPlace - iteration" in line:
                m = re.search(r"iteration\s+(\d+)", line)
                if m:
                    last_iter = int(m.group(1))
            elif "[elapsed_sec]" in line:
                m = re.search(r"\[elapsed_sec\]\s+([\d.]+)", line)
                if m:
                    elapsed = float(m.group(1))
            elif "ROUTABILITY_PLUGIN_SUMMARY" in line:
                summary = line.split("ROUTABILITY_PLUGIN_SUMMARY", 1)[1].strip()
    out["routes"], out["iters"], out["place_s"] = routes, last_iter, elapsed
    if summary:
        try:
            nw = json.loads(summary)["plugins"]["net_weighting"]
        except Exception:
            return out
        st = nw.get("metric_stats", {})
        out["grad_attempts"] = nw.get("gradient_attempts")
        out["updates"] = st.get("weight_updates", {}).get("max")
        out["mean_ratio"] = st.get("mean_ratio", {}).get("mean")
        out["max_ratio"] = st.get("max_ratio", {}).get("max")
        out["sat"] = st.get("saturated_fraction", {}).get("max")
        out["score_over1"] = st.get("score_over_one_fraction", {}).get("mean")
    return out

def f(v, spec="%.2f"):
    return "-" if v is None or v == "" else (spec % float(v))

hdr = ("config", "seed", "WL um", "dWL%", "H%", "V%", "pp H /1%WL",
       "upd", "meanR", "maxR", "sat", ">1frac", "routes", "iters", "place_s", "status")
print(" | ".join(hdr))
for run_id in sorted(rows):
    r = rows[run_id]
    m = re.match(r"s14_%s_v128_(.+)_s(\d+)$" % CASE, run_id)
    cfg, seed = (m.group(1), m.group(2)) if m else (run_id, r.get("seed"))
    st = logstats(run_id)
    try:
        wl = float(r["wirelength"]); h = float(r["egr_h_pct"]); v = float(r["egr_v_pct"])
        dwl = 100.0 * (wl - BASE_WL) / BASE_WL
        slope = (BASE_H - h) / dwl if dwl > 0 else None
    except (TypeError, ValueError, KeyError):
        wl = h = v = dwl = slope = None
    print(" | ".join([
        cfg, str(seed), f(wl, "%.0f"), f(dwl), f(h), f(v), f(slope, "%.3f"),
        f(st["updates"], "%.0f"), f(st["mean_ratio"], "%.4f"), f(st["max_ratio"], "%.3f"),
        f(st["sat"], "%.3f"), f(st["score_over1"], "%.3f"),
        f(st["routes"], "%.0f"), f(st["iters"], "%.0f"), f(st["place_s"], "%.0f"),
        r.get("status", "?"),
    ]))
print()
print("baseline dp_hpwl v116_ref_s1001: %.0f um  H %.2f  V %.2f" % (BASE_WL, BASE_H, BASE_V))
