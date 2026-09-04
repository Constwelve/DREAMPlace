#!/usr/bin/env bash
# v125 (local, yifan405): Phase 2 screening on regression_s14 (OpenC910 ct_top, 735k cells, core
# utilization 49.7%). GOAL: reach Innovus [NR-eGR] "low" congestion -- BOTH H and V <= 5% -- at the
# smallest routed WL. "medium" is <= 2%.
#
# WHY THESE LEVERS (evidence from the existing regression_s14 rows + dreamplace.log inflation lines):
#   The known frontier (legalized, seed 1001, NR-eGR H/V %, WL um) is
#     dp_hpwl                       11,166,016  13.02/7.35
#     v119 thr08_g025               11,329,420  11.53/6.52
#     v116 thr06_g070_w1            11,706,819  10.11/5.59   (+4.8% WL)
#     v117 dp_rudy node_adj 0.25    11,968,073   9.06/5.21
#     v123 adaptive medium          13,758,326   6.11/3.14   (+23% WL, +55% cell area)
#   Nothing reaches low. The inflation logs say why. Under --ruplace-inflation-effort legacy,
#   RUPlaceInflation.apply_node_ratios() enforces
#       max_inc = min(whitespace, ruplace_inflate_area_cap * current_movable_area)
#   PER ROUND (the cumulative_area_cap argument is only passed on the adaptive branch), and clamps
#   raw_ratio at ruplace_max_inflate_ratio. On v116 thr06_g070_w1 the four rounds logged
#       round 1 (global): 0.1500 budget-limited  grow_sum 1.3550E+07 vs max_inc 4.7283E+06
#       rounds 2-4:       0.0110 / 0.0088 / 0.0075, all "ratio-limited", ratio max 1.53 -> 1.73
#   i.e. the GLOBAL pass is cap-limited (it wanted 2.9x the budget it got) and every LOCAL round is
#   ratio-limited against the 2.0 ceiling. Cumulative area = 1.15*1.011*1.0088*1.0075 = +18.7%.
#   The v123 adaptive point that actually got to 6.11/3.14 spent +55% area via cap 0.25 x 2 rounds at
#   ratio 4.0 (logged 0.2500 budget-limited, then 0.2424 ratio-limited at ratio max 4.0).
#   So on THIS design both budgets bind, and cap/ratio are real levers, not decoration -- config 7
#   (cap 0.50 + ratio 3.0 + thr 0.4) is the legacy-path attempt to reach the v123 area neighborhood.
#   Second, untried axis: target density. Core utilization is only 49.7%, so whitespace is cheap and
#   --target-density 0.80 / 0.70 spreads cells before any inflation happens. ref_td080_hpwl is the
#   CONTROL for that axis: without it, configs 3/4/5 cannot be read (spreading vs more inflation room).
#
# CONFIGS (all RUPlace ones: common + ruplace_t10 + s14_gr + v125_base + per-config overrides)
#   1 L_r3_thr05_g070        thr 0.5 gamma 0.70 ratio 3.0 cap 0.30
#   2 L_r3_thr04_g100_w1     thr 0.4 gamma 1.00 ratio 3.0 cap 0.30 + node_util_window 1 / blend 1.0
#   3 L_td080_thr06_g070     target-density 0.80, thr 0.6 gamma 0.70 ratio 2.0 cap 0.15
#   4 L_td070_thr06_g070     target-density 0.70, same
#   5 L_td080_r3_thr05_g070  target-density 0.80 + config 1
#   6 L_r3_thr05_g070_hv10   config 1 + hv-inflate-gamma 1.0 (base is 0.5, mode max)
#   7 L_r3_thr04_g070_cap50  thr 0.4 gamma 0.70 ratio 3.0 cap 0.50   <- closest to the v123 area point
#   8 ref_td080_hpwl         dp_hpwl, target-density 0.80. PROTOCOL: ruplace_t10 + s14_gr +
#                            --stop-overflow 0.10 and NO v125_base, byte-identical to the existing
#                            v119 `ref_stop010` dp_hpwl row (11,105,708 / 12.82 / 7.24) so that
#                            --target-density is the ONLY delta. Deliberately NOT the v116 `ref`
#                            protocol, which also differs in --stop-overflow.
#
# WORKLIST ORDER is information-first, not config-number order: wave 1 = {7, 8} (the single most
# promising RUPlace point + the td control, and 8 is a dp_hpwl run so it is much cheaper than the
# ~1.75 h RUPlace runs), wave 2 = {3, 4} (the orthogonal td axis), waves 3-4 = {1, 2, 5, 6}. If the
# campaign is cut short, both lever readings still exist.
#
# SEEDS: seed 1001 only in this pass (SEEDS=1001). After all 8 rows are scored, seed 1002 is given to
# any config with H,V <= 5% and to the two lowest-(H+V) configs, by re-running with
#   SEEDS=1002 CONFIGS="<those cfgs>" ./run_ruplace_v125_s14_reg_low_local.sh
# (skip-if-exists on raw_metrics.csv makes the 1001 rows no-ops).
#
# GUARD: the first RUPlace run to finish is checked for status ok + "legalization takes" in
# dreamplace.log + at least one "RUPlace plugin inflation: area increment" line with a nonzero
# cumulative area increase. Failing the guard writes $QUEUE/.abort, which makes pop() return empty so
# no further placements start (already-running ones finish and get scored).
#
# CSV: tools/ruplace_s14_innovus_eval.sh now prints TEN fields
#   case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec,egr_h_pct,egr_v_pct
# so a scored row is 13 columns with run_id,method,seed prefixed. results/s14_innovus/regression_s14.csv
# still carries the old 11-column header, so score() migrates the header in place (read -> temp -> mv
# under the same flock) and leaves the existing 11-wide rows untouched. Verdicts use egr_h_pct/egr_v_pct
# (== metrics.egr_horizontal_congestion / egr_vertical_congestion, the Innovus [NR-eGR] percentages),
# NOT the raw horizontal_overflow/vertical_overflow counts.
#
# PARALLELISM: 2 placement workers popping from one flock-guarded work list; scoring decoupled through
# a marker queue drained by one background drainer holding at most MAX_SCORE_JOBS (3) concurrent
# Innovus calls. A GPU flock inside the driver serializes the in-process router across workers.
# Run ids are s14_regression_s14_v125_<config>_s<seed>; queue dir, worklist and their locks are
# v125-specific, so this is disjoint from every other batch. The CSV append lock is shared on purpose.
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
CONFIGS="${CONFIGS:-L_r3_thr04_g070_cap50 ref_td080_hpwl L_td080_thr06_g070 L_td070_thr06_g070 L_r3_thr05_g070 L_r3_thr04_g100_w1 L_td080_r3_thr05_g070 L_r3_thr05_g070_hv10}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
NUM_WORKERS="${NUM_WORKERS:-2}"
RUN_TIMEOUT="${RUN_TIMEOUT:-14400s}"

mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v125_queue
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" 2>/dev/null || true
WORKLIST=results/ruplace_quality/logs/v125_worklist.txt
WLOCK=results/ruplace_quality/logs/.v125_worklist.lock
: > "$WLOCK" 2>/dev/null || true
GLOCK=results/ruplace_quality/logs/.v125_guard.lock
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
# Decided s14 in-loop GR settings (batches 1-2): 5 Innovus row-height gcells = 2880 dbu.
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 --ruplace-router-backend gpugr)
# v125 RUPlace base == v116_base == v118_base, byte-identical (sched + cap 0.15 + 3 local rounds +
# hv 0.5 mode max + inflate start 0.5). Per-config overrides are emitted AFTER it so argparse (last
# flag wins) takes them; `common` is appended last by run_cmd and intentionally re-asserts
# --ruplace-inflation-effort legacy on every single run.
v125_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)

config_flags(){  # sets cfg_flags and cfg_method
  local w1=(--ruplace-param-overrides "${CASE}.ruplace_node_util_window:1,${CASE}.ruplace_node_util_blend:1.0")
  local r3=(--ruplace-max-inflate-ratio 3.0 --ruplace-inflate-area-cap 0.30)
  cfg_method=ruplace
  case "$1" in
    L_r3_thr05_g070)
      cfg_flags=("${r3[@]}" --ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.70) ;;
    L_r3_thr04_g100_w1)
      cfg_flags=("${r3[@]}" --ruplace-inflate-util-threshold 0.4 --ruplace-global-inflate-gamma 1.00 "${w1[@]}") ;;
    L_td080_thr06_g070)
      cfg_flags=(--target-density 0.80 --ruplace-max-inflate-ratio 2.0 --ruplace-inflate-area-cap 0.15 \
                 --ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70) ;;
    L_td070_thr06_g070)
      cfg_flags=(--target-density 0.70 --ruplace-max-inflate-ratio 2.0 --ruplace-inflate-area-cap 0.15 \
                 --ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70) ;;
    L_td080_r3_thr05_g070)
      cfg_flags=(--target-density 0.80 "${r3[@]}" --ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.70) ;;
    L_r3_thr05_g070_hv10)
      cfg_flags=("${r3[@]}" --ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.70 \
                 --ruplace-hv-inflate-gamma 1.0) ;;
    L_r3_thr04_g070_cap50)
      cfg_flags=(--ruplace-max-inflate-ratio 3.0 --ruplace-inflate-area-cap 0.50 \
                 --ruplace-inflate-util-threshold 0.4 --ruplace-global-inflate-gamma 0.70) ;;
    ref_td080_hpwl)
      cfg_method=dp_hpwl; cfg_flags=(--stop-overflow 0.10 --target-density 0.80) ;;
    *) echo "unknown config $1" >&2; return 1 ;;
  esac
}

cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }

run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v125_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout "$RUN_TIMEOUT" python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}

# --- guard: run once, on the first RUPlace run that finishes -------------------------------------
guard_check(){  # $1 = runid ; prints a verdict, returns nonzero on failure
  local runid="$1" raw="results/ruplace_quality/$1/raw_metrics.csv"
  local dlog="results/ruplace_quality/$1/dreamplace/ruplace/${CASE}/dreamplace.log"
  local ok=1
  echo "[guard] runid=${runid}"
  if [[ -f "$raw" ]] && grep -q ",ok," "$raw"; then echo "[guard] status ok: PASS"; else echo "[guard] status ok: FAIL"; ok=0; fi
  if [[ -f "$dlog" ]] && grep -q "legalization takes" "$dlog"; then echo "[guard] legalization logged: PASS"; else echo "[guard] legalization logged: FAIL"; ok=0; fi
  if [[ -f "$dlog" ]]; then
    local cum
    cum=$(grep -o "inflation: area increment [0-9.E+-]* ([0-9.]*)" "$dlog" \
          | sed -E 's/.*\(([0-9.]*)\)/\1/' \
          | awk '{p=(p==""?1:p)*(1+$1)} END{if(p=="")print ""; else printf "%.4f", p-1}')
    grep "inflation: area increment" "$dlog" | sed 's/^/[guard]   /'
    if [[ -n "$cum" ]] && awk -v c="$cum" 'BEGIN{exit !(c>0)}'; then
      echo "[guard] cumulative area increase: ${cum} (PASS)"
    else
      echo "[guard] cumulative area increase: none logged (FAIL)"; ok=0
    fi
  fi
  (( ok == 1 ))
}
maybe_guard(){  # $1 = runid, $2 = method ; one-shot, only for RUPlace runs
  [[ "$2" == "ruplace" ]] || return 0
  ( flock 9
    [[ -f "$QUEUE/.guard_done" ]] && exit 0
    : > "$QUEUE/.guard_done"
    if guard_check "$1" 2>&1 | tee "results/ruplace_quality/logs/v125_guard.log"; then
      echo "[$(date +%T)] GUARD PASS on $1"
    else
      echo "[$(date +%T)] GUARD FAIL on $1 -- aborting further placements" | tee -a "results/ruplace_quality/logs/v125_guard.log"
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

worker(){  # $1 = worker id; placements only, scoring is queued for the drainer
  local wid="$1" item cfg seed runid
  while :; do
    item="$(pop)"
    [[ -n "$item" ]] || break
    cfg="${item%%:*}"; seed="${item##*:}"
    config_flags "$cfg" || continue
    runid="s14_${CASE}_v125_${cfg}_s${seed}"
    if [[ "$cfg_method" == "ruplace" ]]; then
      run_cmd "$runid" --designs "$CASE" --methods ruplace --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${v125_base[@]}" "${cfg_flags[@]}"
    else
      # reference protocol: ruplace_t10 + s14_gr only (NO v125_base); cfg_flags carries
      # --stop-overflow 0.10 so this matches v119 ref_stop010 exactly except for --target-density.
      run_cmd "$runid" --designs "$CASE" --methods "$cfg_method" --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${cfg_flags[@]}"
    fi
    maybe_guard "$runid" "$cfg_method"
    # atomic enqueue: write hidden then rename, so the drainer never reads a partial marker
    echo "$CASE" > "$QUEUE/.tmp_${runid}"; mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/${runid}"
  done
  touch "$QUEUE/.worker${wid}_done"
  echo "[$(date +%T)] worker ${wid} done"
}

drain(){  # single consumer: at most MAX_SCORE_JOBS concurrent Innovus evaluations
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

# --- build the work list: information-first order (see header) -----------------------------------
: > "$WORKLIST"
for cfg in $CONFIGS; do for seed in $SEEDS; do echo "${cfg}:${seed}" >> "$WORKLIST"; done; done
rm -f "$QUEUE"/.worker*_done "$QUEUE/.abort" "$QUEUE/.guard_done"
echo "[$(date +%T)] v125 start: $(wc -l < "$WORKLIST") items, ${NUM_WORKERS} workers, case=${CASE}, seeds=[${SEEDS}]"
df -h /mnt/nvme0n1 | tail -1
cat "$WORKLIST"
pids=()
for ((i=1;i<=NUM_WORKERS;i++)); do worker "$i" & pids+=("$!"); done
( drain ) & dp=$!
for p in "${pids[@]}"; do wait "$p" || true; done
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} v125 ----"
grep -E "^run_id|_v125_" "results/s14_innovus/${CASE}.csv" || true
[[ -f "$QUEUE/.abort" ]] && echo "[$(date +%T)] NOTE: campaign was ABORTED by the guard; see results/ruplace_quality/logs/v125_guard.log"
echo "[$(date +%T)] V125_DONE"
