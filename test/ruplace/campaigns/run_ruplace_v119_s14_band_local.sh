#!/usr/bin/env bash
# v119 (local, yifan405): Phase B batch 9 -- three questions, one sweep, legalized protocol
# (--legalize-flag 1) + Innovus 22 earlyGlobalRoute scoring. Unlike v115/v116/v118 this batch spans
# BOTH s14 designs, so every work item carries its own case and the CSV/lock are derived per item.
#
# Item 3 (first in the work list, cheapest): POST-FIX SPOT CHECK on nvdla_s_s14. The bundled gpugr
#   router was rebuilt at 19:02 on 2026-08-29 (ADMM guard fix); the v115 table was produced before
#   that. Re-run two v115 configs, byte-identical in flags (thr08_g035, thr06_g070_w1), seed 1001
#   only, and compare with the v115 rows to decide whether the v115 table survives the fix.
#   v115 s1001 rows: thr08_g035 4,535,773 / 33,381 / 14,661; thr06_g070_w1 4,608,371 / 25,696 / 12,525.
#   (The six v116 regression_s14 RUPlace runs all finished 20:47 or later, i.e. POST-fix, so this
#   check is only needed for the v115 nvdla_s table.)
# Item 2 (second): SCHEDULE CONFOUND. Every reference so far stops global placement at overflow 0.15
#   (the driver default) while the RUPlace base carries --stop-overflow 0.10, i.e. ~170 extra GP
#   iterations. config `ref_stop010` runs dp_hpwl with --stop-overflow 0.10 on BOTH designs, seeds
#   1001/1002, so the H/V gain attributable to the tighter schedule can be separated from the gain
#   attributable to RUPlace. Verified plumbed: tools/ruplace_quality.py sets "stop_overflow" in the
#   shared cfg dict for every method (v116 ref JSON shows 0.15, v116 ruplace JSON shows 0.1), so the
#   flag really does take on dp_hpwl. ref_stop010 gets ruplace_t10 + s14_gr + --stop-overflow 0.10
#   and deliberately NOT v119_base -- the base carries RUPlace inflation/ADMM flags that must not be
#   attached to a reference -- and --methods dp_hpwl only (v116 ref also ran dp_rudy; not needed).
# Item 1 (last, longest): FILL THE +2% WL BAND on regression_s14. The user accepts WL up to
#   dp_hpwl + ~2%. The best existing point, v116 thr08_g035, sits at worst-seed WL 11,463,261 vs the
#   dp_hpwl worst seed 11,166,016 == +2.66%, just outside the band, at H -15% / V -24%. Three
#   configs walk the threshold/gamma knobs back toward lower WL: thr08_g025 (0.8, 0.25),
#   thr09_g035 (0.9, 0.35), thr085_g030 (0.85, 0.30), seeds 1001/1002.
#
# Base for every RUPlace point == v115_base == v116_base, byte-identical: sched (--stop-overflow 0.10
# --ruplace-admm-start-overflow 0.55 --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5) +
# area cap 0.15 + 3 local rounds + hv gamma 0.5 mode max + inflate start 0.5.
#
# PARALLELISM: 2 placement workers popping from a single flock-guarded work list (ordered item 3 ->
# item 2 -> item 1, so the fast nvdla_s answers land first); scoring decoupled through a marker queue
# drained by one background drainer holding at most MAX_SCORE_JOBS (3) concurrent Innovus calls.
# routability_eval/innovus.py mkdtemps its work dir under cadence_mounted_root, so concurrent Innovus
# calls do not collide. CSV appends take a per-case flock. Run ids are s14_<case>_v119_<config>_s<seed>;
# disjoint from every other batch. Every placement is skip-if-exists on raw_metrics.csv and every
# score is skip-if-exists on innovus.json, so the script is safe to re-run to resume.
set -eo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate placement
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
XPLACE_ROOT=/mnt/nvme0n1/yifan/projs/Xplace
# Must NOT contain the external Xplace cpp_to_py/cpybin/build dirs: they shadow the bundled
# libxplace_common.so and segfault the in-loop router in GRDatabase::addMovObs (see v113).
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE
# Work items are case:config:seed. ITEMS may be overridden wholesale to resume a subset.
ITEMS="${ITEMS-\
nvdla_s_s14:thr08_g035:1001 nvdla_s_s14:thr06_g070_w1:1001 \
nvdla_s_s14:ref_stop010:1001 nvdla_s_s14:ref_stop010:1002 \
regression_s14:ref_stop010:1001 regression_s14:ref_stop010:1002 \
regression_s14:thr08_g025:1001 regression_s14:thr08_g025:1002 \
regression_s14:thr09_g035:1001 regression_s14:thr09_g035:1002 \
regression_s14:thr085_g030:1001 regression_s14:thr085_g030:1002}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
NUM_WORKERS="${NUM_WORKERS:-2}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v119_queue
mkdir -p "$QUEUE"
WORKLIST=results/ruplace_quality/logs/v119_worklist.txt
WLOCK=results/ruplace_quality/logs/.v119_worklist.lock
: > "$WLOCK" 2>/dev/null || true
for c in nvdla_s_s14 regression_s14; do : > "results/s14_innovus/.${c}.csv.lock" 2>/dev/null || true; done

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
# v119 RUPlace base: byte-identical to v115_base / v116_base / v118_base.
v119_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
config_flags(){  # $1 = config, $2 = case; sets cfg_flags and cfg_method
  # node_util_window override keys on the manifest case name, so it must use THIS item's case.
  local w1=(--ruplace-param-overrides "${2}.ruplace_node_util_window:1,${2}.ruplace_node_util_blend:1.0")
  case "$1" in
    # item 3: exact v115 definitions
    thr08_g035)     cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.35) ;;
    thr06_g070_w1)  cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70 "${w1[@]}") ;;
    # item 1: new +2% band points
    thr08_g025)     cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.25) ;;
    thr09_g035)     cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.9 --ruplace-global-inflate-gamma 0.35) ;;
    thr085_g030)    cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.85 --ruplace-global-inflate-gamma 0.30) ;;
    # item 2: schedule-matched reference (no v119_base; only the stop criterion is added)
    ref_stop010)    cfg_method=dp_hpwl; cfg_flags=(--stop-overflow 0.10) ;;
    *)              echo "unknown config $1" >&2; return 1 ;;
  esac
}
cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }
run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v119_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
csv_append(){ ( flock 9; echo "$2" >> "results/s14_innovus/${1}.csv" ) 9>"results/s14_innovus/.${1}.csv.lock"; }
score(){  # score every placed DEF of a run with Innovus EGR; append to results/s14_innovus/<case>.csv
  local runid="$1" case_name="$2"
  local raw="results/ruplace_quality/${runid}/raw_metrics.csv"
  [[ -f "$raw" ]] || { echo "[$(date +%T)] no raw_metrics for ${runid}; skip score"; return 0; }
  ( flock 9
    [[ -f "results/s14_innovus/${case_name}.csv" ]] || \
      echo "run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec" \
        > "results/s14_innovus/${case_name}.csv"
  ) 9>"results/s14_innovus/.${case_name}.csv.lock"
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
    [[ -n "$line" ]] || line="${case_name},${def},score_failed,,,,,"
    csv_append "$case_name" "${runid},${method},${runid##*_s},${line}"
  done
}
pop(){  # atomically remove and echo the first work item; empty output == list exhausted
  ( flock 9
    local it=""
    [[ -s "$WORKLIST" ]] && it="$(head -n 1 "$WORKLIST")"
    if [[ -n "$it" ]]; then tail -n +2 "$WORKLIST" > "${WORKLIST}.tmp"; mv -f "${WORKLIST}.tmp" "$WORKLIST"; fi
    printf '%s' "$it"
  ) 9>"$WLOCK"
}
worker(){  # $1 = worker id; placements only, scoring is queued for the drainer
  local wid="$1" item case_name cfg seed runid
  while :; do
    item="$(pop)"
    [[ -n "$item" ]] || break
    case_name="${item%%:*}"; seed="${item##*:}"; cfg="${item#*:}"; cfg="${cfg%%:*}"
    config_flags "$cfg" "$case_name" || continue
    runid="s14_${case_name}_v119_${cfg}_s${seed}"
    if [[ "$cfg_method" == "ruplace" ]]; then
      run_cmd "$runid" --designs "$case_name" --methods ruplace --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${v119_base[@]}" "${cfg_flags[@]}"
    else
      # reference: v116 ref protocol (ruplace_t10 + s14_gr + common), plus only the stop criterion.
      run_cmd "$runid" --designs "$case_name" --methods "$cfg_method" --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${cfg_flags[@]}"
    fi
    # atomic enqueue: write hidden then rename, so the drainer never reads a partial marker
    echo "$case_name" > "$QUEUE/.tmp_${runid}"; mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/${runid}"
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
: > "$WORKLIST"
for it in $ITEMS; do echo "$it" >> "$WORKLIST"; done
rm -f "$QUEUE"/.worker*_done
echo "[$(date +%T)] v119 start: $(wc -l < "$WORKLIST") items, ${NUM_WORKERS} workers"
cat "$WORKLIST"
pids=()
for ((i=1;i<=NUM_WORKERS;i++)); do worker "$i" & pids+=("$!"); done
( drain ) & dp=$!
for p in "${pids[@]}"; do wait "$p" || true; done
wait "$dp" || true
for c in nvdla_s_s14 regression_s14; do
  echo "[$(date +%T)] ---- ${c} ----"
  grep -E "^run_id|_v119_" "results/s14_innovus/${c}.csv" || true
done
echo "[$(date +%T)] V119_DONE"
