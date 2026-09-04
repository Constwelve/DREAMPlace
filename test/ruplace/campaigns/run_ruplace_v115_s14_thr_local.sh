#!/usr/bin/env bash
# v115 (local, yifan405): Phase B batch 5 -- third RUPlace sweep on s14 (nvdla_s_s14), Innovus scored,
# legalized protocol (--legalize-flag 1), same body as v114 with these changes:
#   * NEW LEVER: --ruplace-inflate-util-threshold. RUPlaceInflation.apply divides the node bin
#     utilization by this threshold before clamp_min(1.0), in the global path and in the local
#     allow_shrink path. 1.0 == legacy (only cells in bins with utilization > 1 inflate). Under the
#     calibrated `avail` utilization on s14 the mean bin utilization is ~0.13, so legacy inflated
#     ~0.2-0.4% of movable area no matter how large --ruplace-inflate-area-cap was (v113/v114 logs
#     show increments of 0.0019-0.0035 against a 0.005 cap: ratio-limited, not budget-limited).
#     dp_rudy inflates ~10% of area blindly and buys -9% H / -26% V, so this batch tests whether a
#     sub-unity threshold widens the inflated set enough to close that gap.
#   * base = ruplace_t10 + s14_gr + v114's `sched` overrides + v114's `infl_heavy` inflation budget
#     (area cap 0.15, 3 local rounds, hv gamma 0.5 mode max, inflate start overflow 0.5).
#   * configs sweep (threshold, global inflate gamma) and two node_util_window:1 variants.
#   * run ids are s14_<case>_v115_<config>_s<seed>; disjoint from the concurrently running v114.
#   * PARALLELISM: placements run as 2 concurrent workers (each loops its own config list x seeds,
#     skip-if-exists on raw_metrics.csv). Innovus scoring is decoupled: each finished placement is
#     queued via a marker file and drained by a single background drainer that keeps at most
#     MAX_SCORE_JOBS (3) concurrent tools/ruplace_s14_innovus_eval.sh calls. The drainer runs in its
#     own subshell so its `jobs -rp` counts only scoring jobs, not the two placement workers.
#     routability_eval/innovus.py mkdtemps its work dir under cadence_mounted_root, so concurrent
#     Innovus calls (including v114's) do not collide. CSV appends take an flock.
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
CASE="${CASE:-nvdla_s_s14}"
SEEDS="${SEEDS:-1001 1002}"
METHODS="${METHODS:-ruplace}"
W1_CONFIGS="${W1_CONFIGS:-thr08_g035 thr08_g070 thr06_g035 thr06_g070}"
W2_CONFIGS="${W2_CONFIGS:-thr08_g070_w1 thr06_g070_w1 thr07_g050 thr05_g035}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v115_queue
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" || true

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
# v115 base: v114 `sched` schedule + v114 `infl_heavy` inflation budget, shared by every config.
v115_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
# Emitted after ruplace_t10/s14_gr/v115_base so argparse takes the override (later flag wins).
config_flags(){
  local w1=(--ruplace-param-overrides "${CASE}.ruplace_node_util_window:1,${CASE}.ruplace_node_util_blend:1.0")
  case "$1" in
    ref)            cfg_flags=() ;;
    thr08_g035)     cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.35) ;;
    thr08_g070)     cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.70) ;;
    thr06_g035)     cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.35) ;;
    thr06_g070)     cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70) ;;
    thr08_g070_w1)  cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.70 "${w1[@]}") ;;
    thr06_g070_w1)  cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70 "${w1[@]}") ;;
    thr07_g050)     cfg_flags=(--ruplace-inflate-util-threshold 0.7 --ruplace-global-inflate-gamma 0.50) ;;
    thr05_g035)     cfg_flags=(--ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.35) ;;
    *)              echo "unknown config $1" >&2; return 1 ;;
  esac
}
cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }
run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v115_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
csv_append(){  # $1 = line; serialize appends against the other v115 scoring jobs
  ( flock 9; echo "$1" >> "results/s14_innovus/${CASE}.csv" ) 9>"$LOCK"
}
score(){  # score every placed DEF of a run with Innovus EGR; append to results/s14_innovus/<case>.csv
  local runid="$1" case_name="$2"
  local raw="results/ruplace_quality/${runid}/raw_metrics.csv"
  [[ -f "$raw" ]] || { echo "[$(date +%T)] no raw_metrics for ${runid}; skip score"; return 0; }
  ( flock 9
    [[ -f "results/s14_innovus/${case_name}.csv" ]] || \
      echo "run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec" \
        > "results/s14_innovus/${case_name}.csv"
  ) 9>"$LOCK"
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
    csv_append "${runid},${method},${runid##*_s},${line}"
  done
}
worker(){  # $1 = worker id, $2.. = configs; placements only, scoring is queued for the drainer
  local wid="$1"; shift
  local cfg seed runid
  for cfg in "$@"; do
    config_flags "$cfg"
    for seed in $SEEDS; do
      runid="s14_${CASE}_v115_${cfg}_s${seed}"
      run_cmd "$runid" --designs "$CASE" --methods "$METHODS" --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${v115_base[@]}" ${cfg_flags[@]+"${cfg_flags[@]}"}
      # atomic enqueue: write hidden then rename, so the drainer never reads a partial marker
      echo "$CASE" > "$QUEUE/.tmp_${runid}"; mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/${runid}"
    done
  done
  touch "$QUEUE/.worker${wid}_done"
  echo "[$(date +%T)] worker ${wid} done"
}
drain(){  # single consumer: at most MAX_SCORE_JOBS concurrent Innovus evaluations
  local pending=() f runid case_name
  while :; do
    shopt -s nullglob; pending=("$QUEUE"/s14_*); shopt -u nullglob
    if (( ${#pending[@]} == 0 )); then
      [[ -f "$QUEUE/.worker1_done" && -f "$QUEUE/.worker2_done" ]] && break
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
[[ "$METHODS" == *ruplace* ]] || { W1_CONFIGS="ref"; W2_CONFIGS=""; }
rm -f "$QUEUE"/.worker*_done
echo "[$(date +%T)] v115 start: worker1=[$W1_CONFIGS] worker2=[$W2_CONFIGS] seeds=[$SEEDS]"
worker 1 $W1_CONFIGS & w1=$!
w2=""
if [[ -n "$W2_CONFIGS" ]]; then worker 2 $W2_CONFIGS & w2=$!; else touch "$QUEUE/.worker2_done"; fi
( drain ) & dp=$!
wait "$w1" || true
[[ -n "$w2" ]] && { wait "$w2" || true; }
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} ----"; cat "results/s14_innovus/${CASE}.csv"
echo "[$(date +%T)] V115_DONE"
