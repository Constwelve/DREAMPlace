#!/usr/bin/env bash
# v128 (local, yifan405): the last untried mechanism CLASS on regression_s14 (OpenC910 ct_top,
# 735k cells, core utilization 49.7%) -- CONGESTION-AWARE NET WEIGHTING, judged by Innovus
# [NR-eGR] overflow.  GOAL: H and V <= 5% ("low"), <= 2% ("medium"), <= 1% ("high") at the
# smallest routed WL.  Reference frontier (legalized, seed 1001, NR-eGR H/V %, routed WL um):
#     dp_hpwl (v116_ref, same base flags)   11,166,016  13.02/7.35
#     v126 B_blk050_r3thr05  (best RUPlace) 12,936,643   7.05/3.41   (+15.9% WL)
#     Innovus place_design                              0.30/0.59   (+15.7% WL)
# Every lever from v119 through v127 moves or grows CELL AREA (inflation, congestion soft
# blockage, global density target, row spreading, ADMM anchor) and they all sit on one trade
# curve: ~0.4 pp of H overflow bought per 1% of routed WL, saturating near H 7%.  Net weighting
# is the first actuator that does not touch area: it scales the wirelength weight of the nets
# whose pins sit in congested gcells, so those nets are pulled SHORTER instead of the cells being
# grown or pushed.  The question this batch answers is whether that bends the 0.4 pp / 1% curve.
#
# ================= MECHANISM / PLUMBING NOTES (read before interpreting any row) =================
#
# (1) THE PIPELINE REPLACES THE CONTROLLER -- IT DOES NOT STACK.
#     dreamplace/ops/routability_opt/__init__.py::build_routability_opt_op():
#         if params.ruplace_plugins:  return RoutabilityOptimizationPipeline(...)
#         return RUPlaceController(...)
#     So on every run below the legacy RUPlaceController is NOT constructed, and with it go
#     legacy inflation, congestion soft blockage, the Innovus inflation proxy and ADMM.  The
#     ruplace_t10 / v128_base inflation, blockage and ADMM flags are still emitted into the config
#     (the driver writes them unconditionally for the ruplace method) but NOTHING READS THEM.
#     Consequences:
#       - the "NW alone" isolation is automatic; the explicit off-flags in nw_off are cosmetic and
#         are passed only so the driver log records the intent.
#       - the originally-planned 6th cell "B_blk050_r3thr05 + net weighting" is IMPOSSIBLE without
#         a dreamplace design change (running both objects would need two BundledGPUGRBackend
#         instances, ~2x GPU memory, and PlaceObj.py:266 / NonLinearPlace.py:876 both assume a
#         single routability_opt_op).  Such a row would have been a mislabeled duplicate of
#         NW_h_g050.  That slot is spent on NW_h_g050_bbox instead (see below).
#     MATCHED CONTROL: because the pipeline runs plain GP plus net weighting, the correct
#     denominator for "pp of H per 1% WL" is the dp_hpwl row at these same base flags,
#     s14_regression_s14_v116_ref_s1001 = 11,166,016 um, H 13.02 / V 7.35.  A gamma-0 run would
#     reproduce it exactly (ratio == 1.0 everywhere -> net_weights never change), so no GPU time
#     is spent re-measuring it.
#
# (2) THE PLUGIN GATE MUST BE CLOSED EARLY OR THE RUN NEVER STARTS.
#     ruplace_plugin_start_overflow defaults to 1.0, i.e. "always on".  Overflow is ~0.9997 at
#     iteration 0, so the pipeline routes the initial center-init blob: measured on this design
#     that single GPUGR call had not returned after 4 minutes (735k cells inside ~140k x 186k dbu
#     of an 800k x 750k die).  Every config below therefore passes
#     --ruplace-plugin-start-overflow 0.55, the same overflow at which v126_base turns ADMM on.
#
# (3) context.iteration COUNTS OBJECTIVE EVALUATIONS, NOT PLACEMENT ITERATIONS.
#     RoutabilityOptimizationPipeline.prepare_objective() increments self.iteration and PlaceObj
#     calls it once per objective evaluation, ~3 per placement iteration on this design.  So
#     --ruplace-net-weight-freq 20 / --ruplace-proxy-refresh-interval 20 is a refresh every ~6
#     placement iterations, and the f10 cell is every ~3.  Router-call counts in the report come
#     from "RUPlace GR grid:" lines in dreamplace.log, not from these numbers.
#
# (4) HOW THE WEIGHT IS COMPUTED (dreamplace/ops/routability_opt/plugins/net_weighting.py):
#       utilization = select_congestion_map(signal, direction_mode)   # horizontal -> hv_util[0]
#       net_score   = mean of utilization over the net's pin gcells   # score_mode pin_mean
#       ratio       = clamp(1 + gamma * max(net_score/scale - 1, 0), 1, max)
#       net_weights = original_net_weights * ratio
#     With --ruplace-net-weight-normalization absolute (the default) scale == 1.0, so ONLY nets
#     whose mean pin utilization EXCEEDS 1.0 are touched at all -- gamma is irrelevant for every
#     other net.  pin_mean averaging pulls scores toward the design mean, so this can silently be
#     a no-op.  The guard below asserts it is not (max_ratio > 1 and weight_updates > 0), and the
#     plugin now reports score_mean / score_max / score_over_one_fraction so a failure is
#     diagnosable from one log.
#
# ================= CONFIGS (all: common + ruplace_t10 + s14_gr + v128_base + nw_common) =========
#   NW_h_g050       horizontal, gamma 0.50                       <- centre of the dose sweep
#   NW_h_g100       horizontal, gamma 1.00                       <- dose up
#   NW_h_g025       horizontal, gamma 0.25 (plugin default)      <- dose down
#   NW_maxhv_g050   max_hv,     gamma 0.50                       <- direction-mode control
#   NW_h_g050_f10   horizontal, gamma 0.50, freq/refresh 10      <- schedule (2x the routes)
#   NW_h_g050_bbox  horizontal, gamma 0.50, score_mode bbox_pmean (power 4)
#                   pin_mean only sees a net's PIN gcells; bbox_pmean sees the whole net bounding
#                   box, i.e. the nets that CROSS congested gcells -- which is the mechanism the
#                   batch is actually testing.  Replaces the impossible stacked cell of note (1).
#
# ================= NOTE (5): WAVE 1 CAME BACK NULL, WAVE 2 IS design_mean =======================
# First scored row, NW_h_g100 (the most aggressive gamma of wave 1):
#     WL 11,193,994 (+0.25% vs dp_hpwl 11,166,016), NR-eGR H 13.00 / V 7.47
# versus dp_hpwl's own 13.02 / 7.35 -- i.e. no effect at all.  The cause is visible in the
# per-activation log: with ruplace_net_weight_normalization=absolute the trigger is a raw score
# above 1.0, and as global placement spreads the cells the mean horizontal utilization falls from
# ~0.96 to ~0.64, so score_over_one_fraction collapses 0.33 -> 0.12 and mean_ratio relaxes
# 1.19 -> 1.03.  The lever switches itself off exactly over the second half of GP, which is when
# the final overflow is decided.  Lower gammas and the freq / bbox variants share that cause, so
# NW_h_g025 and NW_maxhv_g050 were left to finish (low-gamma and direction controls) and the
# queued NW_h_g050_f10 / NW_h_g050_bbox were dropped from the worklist mid-batch.
# Wave 2 is the design_mean cells below: net_weight_ratios() then divides by the MEAN active-net
# score, so roughly the above-average half of the nets is always weighted and the pressure cannot
# decay just because the whole map cooled.  Run as
#     CONFIGS="NWdm_h_g025 NWdm_h_g050 NWdm_h_g100" ./run_ruplace_v128_s14_netweight_local.sh
#
# SEEDS: seed 1001 in this pass.  Afterwards seed 1002 goes to every config with egr_h_pct <= 5,
# else to the two lowest-H, via
#   SEEDS=1002 CONFIGS="<cfg> <cfg>" ./run_ruplace_v128_s14_netweight_local.sh
# (skip-if-exists on raw_metrics.csv makes the 1001 rows no-ops).
#
# CSV: results/s14_innovus/<case>.csv, 13 columns
#   run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,
#   runtime_sec,egr_h_pct,egr_v_pct
# ensure_header() migrates an old 11-column header in place under the shared append lock
# (verbatim from v126).  Verdicts use egr_h_pct/egr_v_pct, NOT the raw overflow counts.
#
# Run ids are s14_<case>_v128_<config>_s<seed>; the queue dir, worklist and their locks are
# v128-specific, so this batch is disjoint from every other one.  The CSV append lock is shared
# on purpose.  Nothing here touches or kills any other batch's processes.
set -eo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
set +u; source "$HOME/miniconda3/etc/profile.d/conda.sh"; conda activate placement; set -u
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
XPLACE_ROOT=/mnt/nvme0n1/yifan/projs/Xplace
# Must NOT contain the external Xplace cpp_to_py/cpybin/build dirs: they shadow the bundled
# libxplace_common.so and segfault the in-loop router in GRDatabase::addMovObs (see v113).
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE

CASE="${CASE:-regression_s14}"
SEEDS="${SEEDS:-1001}"
# 6 h, same reasoning as v126: a run killed at the wall writes no raw_metrics.csv and therefore
# yields no CSV row at all, which is strictly worse than letting a slow run finish.  These runs
# grow no area, so they should be near the v126 B_blk050_noinfl cost (~3500 s) plus the router
# calls; f10 is the one that can drift long.
RUN_TIMEOUT="${RUN_TIMEOUT:-21600s}"
# GPU: the in-process router locks per call (ruplace_gpu_lock_mode=call), ~5-8 GB per worker on
# the 24 GB card, so two concurrent placements fit.
CONFIGS="${CONFIGS:-NW_h_g050 NW_h_g100 NW_h_g025 NW_maxhv_g050 NW_h_g050_f10 NW_h_g050_bbox}"
NUM_WORKERS="${NUM_WORKERS:-2}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
SCORE_INLINE="${SCORE_INLINE:-0}"

mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE="results/ruplace_quality/logs/v128_queue"
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" 2>/dev/null || true
WORKLIST="results/ruplace_quality/logs/v128_worklist.txt"
WLOCK="results/ruplace_quality/logs/.v128_worklist.lock"
: > "$WLOCK" 2>/dev/null || true
GLOCK="results/ruplace_quality/logs/.v128_guard.lock"
: > "$GLOCK" 2>/dev/null || true
CSV_HEADER13="run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec,egr_h_pct,egr_v_pct"

common=(--case-manifest test/ruplace/s14_cases.json --iterations 1000 --gpu 0 --num-threads 16 \
        --learning-rate 0.010 --xplace-root "$XPLACE_ROOT" --ruplace-router-backend gpugr \
        --ruplace-global-cluster-mode none --eval-route-rrr-iters 1 --ruplace-external-route-eval 0 \
        --ruplace-allow-shrink 1 --ruplace-inflation-effort legacy --legalize-flag 1 --continue-on-error)
ruplace_t10=(--gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030 \
  --ruplace-global-util-exponent 0.745 --ruplace-inflate-area-cap 0.005 --ruplace-inflate-start-overflow 0.30 --ruplace-global-inflate-gamma 0.35 \
  --ruplace-admm-start-overflow 0.33 --ruplace-admm-route-freq 50 --ruplace-admm-apply-freq 5 --ruplace-admm-weight 0.03 --ruplace-admm-anchor-weight 0.10 \
  --ruplace-local-inflate-max-rounds 1 --ruplace-local-inflate-gamma 0.05 --route-rrr-iters 1)
# Decided s14 in-loop GR settings (batches 1-2): 5 Innovus row-height gcells = 2880 dbu.  Verified
# to be honored on the pipeline path: "RUPlace GR grid: step 2880 dbu ... -> 278 x 260 gcells" and
# "GR settings (resolved): ... util_mode=avail" appear in a pipeline run's dreamplace.log.
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 --ruplace-router-backend gpugr)
# v128_base == v126_base == v125_base == v116_base, byte-identical.  Its inflation/blockage/ADMM
# half is inert here (note 1); it is kept so the GP schedule (stop-overflow 0.10) and the flag set
# are literally the same as every earlier s14 batch.
v128_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
# Selects the plugin pipeline and closes the early-iteration gate (note 2).  nw_off is the
# literal "inflation and blockage OFF" spec; it is inert on this path and is passed for the record.
nw_common=(--ruplace-plugins net_weighting --ruplace-plugin-start-overflow 0.55)
nw_off=(--ruplace-inflate-area-cap 0.005 --ruplace-global-inflate-gamma 0.0 \
        --ruplace-local-inflate-max-rounds 0 --ruplace-congestion-blockage 0.0)

config_flags(){  # sets cfg_flags and cfg_method
  cfg_method=ruplace
  case "$1" in
    NW_h_g025)      cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.25) ;;
    NW_h_g050)      cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.50) ;;
    NW_h_g100)      cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 1.00) ;;
    NW_maxhv_g050)  cfg_flags=(--ruplace-net-weight-direction-mode max_hv --ruplace-net-weight-gamma 0.50) ;;
    NW_h_g050_f10)  cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.50 \
                               --ruplace-net-weight-freq 10 --ruplace-proxy-refresh-interval 10) ;;
    NW_h_g050_bbox) cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.50 \
                               --ruplace-net-weight-score-mode bbox_pmean --ruplace-net-weight-bbox-power 4.0) ;;
    # ---- design_mean pass (v128 wave 2, see note (5)) -------------------------------------------
    # scale = mean net score over the active nets, so the trigger point RIDES the placement instead
    # of sitting at the absolute 1.0 that the spreading placement walks away from.
    NWdm_h_g025)    cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.25 \
                               --ruplace-net-weight-normalization design_mean) ;;
    NWdm_h_g050)    cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 0.50 \
                               --ruplace-net-weight-normalization design_mean) ;;
    NWdm_h_g100)    cfg_flags=(--ruplace-net-weight-direction-mode horizontal --ruplace-net-weight-gamma 1.00 \
                               --ruplace-net-weight-normalization design_mean) ;;
    *) echo "unknown config $1" >&2; return 1 ;;
  esac
  cfg_flags=("${nw_off[@]}" "${nw_common[@]}" "${cfg_flags[@]}")
}

cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }

run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v128_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout "$RUN_TIMEOUT" python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}

# --- guard: run once, on the first run that produced metrics -------------------------------------
# The constructor line "RUPlace plugin pipeline: proxy=... plugins=..." fires unconditionally and
# therefore proves only that the pipeline was BUILT.  The guard instead reads the end-of-GP
# ROUTABILITY_PLUGIN_SUMMARY json and demands that a weight actually moved.
guard_check(){  # $1 = runid, $2 = config ; prints a verdict, returns nonzero on failure
  local runid="$1" cfg="$2" raw="results/ruplace_quality/$1/raw_metrics.csv"
  local dlog="results/ruplace_quality/$1/dreamplace/ruplace/${CASE}/dreamplace.log"
  local ok=1
  echo "[guard] runid=${runid} config=${cfg}"
  if [[ -f "$raw" ]] && grep -q ",ok," "$raw"; then echo "[guard] status ok: PASS"; else echo "[guard] status ok: FAIL"; ok=0; fi
  if [[ -f "$dlog" ]] && grep -q "legalization takes" "$dlog"; then echo "[guard] legalization logged: PASS"; else echo "[guard] legalization logged: FAIL"; ok=0; fi
  [[ -f "$dlog" ]] || { echo "[guard] no dreamplace.log at $dlog"; (( ok == 1 )); return; }

  grep -q "RUPlace plugin pipeline: proxy=" "$dlog" \
    && { grep -m1 "RUPlace plugin pipeline: proxy=" "$dlog" | sed 's/^/[guard]   /'; } \
    || { echo "[guard] pipeline never constructed: FAIL"; ok=0; }
  echo "[guard] router calls: $(grep -c 'RUPlace GR grid:' "$dlog" || true)"
  echo "[guard] plugin activations logged: $(grep -c 'RUPlace plugin activation:' "$dlog" || true)"
  grep "RUPlace plugin activation:" "$dlog" | head -3 | sed 's/^/[guard]   /'
  grep "RUPlace plugin activation:" "$dlog" | tail -3 | sed 's/^/[guard]   /'

  if ! grep -q "ROUTABILITY_PLUGIN_SUMMARY" "$dlog"; then
    echo "[guard] ROUTABILITY_PLUGIN_SUMMARY: MISSING (FAIL)"; ok=0
  else
    grep -o "ROUTABILITY_PLUGIN_SUMMARY .*" "$dlog" | tail -1 | cut -d' ' -f2- > "${dlog}.plugin_summary.json"
    python3 - "${dlog}.plugin_summary.json" <<'PY' || ok=0
import json, sys
summary = json.load(open(sys.argv[1]))
nw = summary.get("plugins", {}).get("net_weighting")
if nw is None:
    print("[guard] net_weighting absent from the summary: FAIL"); sys.exit(1)
stats = nw.get("metric_stats", {})
def stat(key, field="max"):
    return stats.get(key, {}).get(field)
updates = stat("weight_updates")
max_ratio = stat("max_ratio")
print("[guard]   status=%s attempts=%s activations=%s" % (nw.get("status"), nw.get("attempts"), nw.get("activations")))
for key in ("score_mean", "score_max", "score_over_one_fraction", "mean_ratio", "max_ratio",
            "saturated_fraction", "effective_gamma", "weight_updates"):
    if key in stats:
        s = stats[key]
        print("[guard]   %-24s min=%.6g mean=%.6g max=%.6g last=%.6g" % (key, s["min"], s["mean"], s["max"], s["last"]))
bad = 0
if nw.get("status") != "active":
    print("[guard] plugin status is %r, not 'active': FAIL" % nw.get("status")); bad = 1
if not updates:
    print("[guard] weight_updates never exceeded 0: FAIL (the plugin ran but changed no weight)"); bad = 1
if max_ratio is None or max_ratio <= 1.0:
    print("[guard] max net weight ratio %r <= 1.0: FAIL (no net was reweighted)" % max_ratio); bad = 1
print("[guard] net weighting fired: %s" % ("FAIL" if bad else "PASS"))
sys.exit(bad)
PY
  fi
  (( ok == 1 ))
}
maybe_guard(){  # $1 = runid, $2 = config ; one-shot, on the first run that produced metrics
  # A driver timeout or a hard crash leaves no raw_metrics.csv.  Guarding on such a run would fail
  # "status ok" and write .abort, killing the batch over an infrastructure timeout rather than a
  # mechanism defect.  Skip WITHOUT consuming the one-shot marker.
  if [[ ! -f "results/ruplace_quality/$1/raw_metrics.csv" ]]; then
    echo "[$(date +%T)] guard skipped for $1 (no raw_metrics.csv -- timeout/crash); guard still pending"
    return 0
  fi
  ( flock 9
    [[ -f "$QUEUE/.guard_done" ]] && exit 0
    : > "$QUEUE/.guard_done"
    if guard_check "$1" "$2" 2>&1 | tee "results/ruplace_quality/logs/v128_guard.log"; then
      echo "[$(date +%T)] GUARD PASS on $1"
    else
      echo "[$(date +%T)] GUARD FAIL on $1 -- aborting further placements" | tee -a "results/ruplace_quality/logs/v128_guard.log"
      : > "$QUEUE/.abort"
    fi
  ) 9>"$GLOCK"
}

csv_append(){ ( flock 9; echo "$1" >> "results/s14_innovus/${CASE}.csv" ) 9>"$LOCK"; }

ensure_header(){  # create the 13-column CSV, or migrate an old 11-column header in place
  ( flock 9
    local f="results/s14_innovus/${CASE}.csv"
    if [[ ! -f "$f" ]]; then echo "$CSV_HEADER13" > "$f"; exit 0; fi
    head -1 "$f" | grep -q "egr_h_pct" && exit 0
    { echo "$CSV_HEADER13"; tail -n +2 "$f"; } > "${f}.hdrtmp" && mv -f "${f}.hdrtmp" "$f"
    echo "[$(date +%T)] migrated ${f} header to 13 columns (old 11-wide rows left as-is)"
  ) 9>"$LOCK"
}

score(){  # score every placed DEF of a run with Innovus EGR; append to results/s14_innovus/<case>.csv
  local runid="$1" case_name="$2"
  local raw="results/ruplace_quality/${runid}/raw_metrics.csv"
  [[ -f "$raw" ]] || { echo "[$(date +%T)] no raw_metrics for ${runid}; skip score"; return 0; }
  ensure_header
  local pairs=()
  mapfile -t pairs < <(python3 - "$runid" <<'PY'
import csv, sys
run = sys.argv[1]
for r in csv.DictReader(open("results/ruplace_quality/%s/raw_metrics.csv" % run)):
    if r.get("placed_def"): print("%s,%s" % (r["method"], r["placed_def"]))
PY
)
  local pair method def out line
  for pair in "${pairs[@]}"; do
    [[ -n "$pair" ]] || continue
    method="${pair%%,*}"; def="${pair#*,}"
    out="results/s14_innovus/${runid}_${method}"
    if [[ -f "$out/innovus.json" ]]; then echo "[$(date +%T)] skip score ${runid}/${method}"; continue; fi
    echo "[$(date +%T)] innovus ${runid}/${method}"
    line=$( (tools/ruplace_s14_innovus_eval.sh "$case_name" "$def" "$out" global 2>>"results/s14_innovus/${runid}.err" || true) | tail -1)
    [[ -n "$line" ]] || line="${case_name},${def},score_failed,,,,,,,"
    csv_append "${runid},${method},${runid##*_s},${line}"
  done
}

pop(){  # atomically remove and echo the first work item; empty output == exhausted or aborted
  ( flock 9
    [[ -f "$QUEUE/.abort" ]] && { printf ''; exit 0; }
    local it=""
    [[ -s "$WORKLIST" ]] && it="$(head -n 1 "$WORKLIST")"
    if [[ -n "$it" ]]; then tail -n +2 "$WORKLIST" > "${WORKLIST}.tmp"; mv -f "${WORKLIST}.tmp" "$WORKLIST"; fi
    printf '%s' "$it"
  ) 9>"$WLOCK"
}

worker(){  # $1 = worker id
  local wid="$1" item cfg seed runid
  while :; do
    item="$(pop)"
    [[ -n "$item" ]] || break
    cfg="${item%%:*}"; seed="${item##*:}"
    config_flags "$cfg" || continue
    runid="s14_${CASE}_v128_${cfg}_s${seed}"
    run_cmd "$runid" --designs "$CASE" --methods ruplace --random-seed "$seed" \
      "${ruplace_t10[@]}" "${s14_gr[@]}" "${v128_base[@]}" "${cfg_flags[@]}"
    maybe_guard "$runid" "$cfg"
    if [[ "$SCORE_INLINE" == "1" ]]; then
      score "$runid" "$CASE"
    else
      # atomic enqueue: write hidden then rename, so the drainer never reads a partial marker
      echo "$CASE" > "$QUEUE/.tmp_${runid}"; mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/${runid}"
    fi
  done
  touch "$QUEUE/.worker${wid}_done"
  echo "[$(date +%T)] worker ${wid} done"
}

drain(){  # single consumer: at most MAX_SCORE_JOBS concurrent Innovus evaluations
  [[ "$SCORE_INLINE" == "1" ]] && { echo "[$(date +%T)] drainer disabled (SCORE_INLINE=1)"; return 0; }
  local pending=() f runid case_name n i
  while :; do
    shopt -s nullglob; pending=("$QUEUE"/s14_*); shopt -u nullglob
    if (( ${#pending[@]} == 0 )); then
      n=0
      for ((i=1;i<=NUM_WORKERS;i++)); do [[ -f "$QUEUE/.worker${i}_done" ]] && n=$((n+1)); done
      (( n == NUM_WORKERS )) && break
      sleep 20; continue
    fi
    for f in "${pending[@]}"; do
      runid="$(basename "$f")"; case_name="$(cat "$f")"; rm -f "$f"
      while (( $(jobs -rp | wc -l) >= MAX_SCORE_JOBS )); do sleep 10; done
      score "$runid" "$case_name" &
    done
  done
  wait || true
  echo "[$(date +%T)] drainer done"
}

# --- stale-install guard --------------------------------------------------------------------
# Placer.py is executed out of install/, NOT out of the source tree (CLAUDE.md "Building"), so a
# pure-Python edit under dreamplace/ that was not copied into install/dreamplace/ runs the OLD
# code SILENTLY -- and the plugin guard below would still pass, because the old code also moves
# weights.  That is the one failure mode in this batch that produces plausible-looking wrong rows
# instead of a crash.  Cost of the check: two cmp calls.
for f in ops/routability_opt/pipeline.py ops/routability_opt/plugins/net_weighting.py; do
  cmp -s "dreamplace/$f" "install/dreamplace/$f" || {
    echo "STALE INSTALL: dreamplace/$f != install/dreamplace/$f -- run make install in build/ or copy the file" >&2
    exit 3
  }
done

# --- build the work list: information-first order (dose centre first) ----------------------------
: > "$WORKLIST"
for cfg in $CONFIGS; do for seed in $SEEDS; do echo "${cfg}:${seed}" >> "$WORKLIST"; done; done
rm -f "$QUEUE"/.worker*_done "$QUEUE/.abort" "$QUEUE/.guard_done"
echo "[$(date +%T)] v128 start: $(wc -l < "$WORKLIST") items, ${NUM_WORKERS} workers, \
score_jobs=${MAX_SCORE_JOBS}, inline_score=${SCORE_INLINE}, case=${CASE}, seeds=[${SEEDS}]"
df -h /mnt/nvme0n1 | tail -1
cat "$WORKLIST"
pids=()
for ((i=1;i<=NUM_WORKERS;i++)); do worker "$i" & pids+=("$!"); done
( drain ) & dp=$!
for p in "${pids[@]}"; do wait "$p" || true; done
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} v128 ----"
grep -E "^run_id|_v128_" "results/s14_innovus/${CASE}.csv" || true
[[ -f "$QUEUE/.abort" ]] && echo "[$(date +%T)] NOTE: v128 was ABORTED by the guard; see results/ruplace_quality/logs/v128_guard.log"
echo "[$(date +%T)] V128_DONE"
