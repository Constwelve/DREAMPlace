#!/usr/bin/env bash
# v116 (local, yifan405): Phase B batch 6 -- confirmation of the best RUPlace configs on the SECOND
# SMIC14 design, regression_s14 (ct_top, 766k COMPONENTS, ~4x more congested per area than nvdla_s).
# Protocol is identical to v115 (legalized DEFs via --legalize-flag 1, Innovus 22 earlyGlobalRoute
# scoring), only the case and the config list change:
#   * CASE=regression_s14. Rows go to results/s14_innovus/regression_s14.csv. NOTE that file already
#     holds 4 rows from v112 which were scored WITHOUT legalization; only v116_* rows are comparable.
#   * References (config name `ref`, METHODS=dp_hpwl,dp_rudy) are re-run under the legalized protocol
#     because the v112 rows are not comparable. They are run FIRST, sequentially, and deliberately
#     WITHOUT v116_base: v116_base carries --stop-overflow 0.10, which is a global-placement stop
#     criterion that also applies to dp_hpwl/dp_rudy and would make the references incomparable to
#     the v114 nvdla_s legalized references. References therefore get exactly ruplace_t10 + s14_gr
#     (+ --legalize-flag 1 from `common`), which is what v114's `ref` pass used.
#   * RUPlace configs are the three v115 winners, byte-identical in flags to v115: thr08_g035,
#     thr08_g070, thr06_g070_w1. Base = ruplace_t10 + s14_gr + v115's `sched` schedule + v115's
#     inflation budget (area cap 0.15, 3 local rounds, hv gamma 0.5 mode max, inflate start 0.5).
#     thr06_g070_w1 keys its --ruplace-param-overrides on ${CASE}; parse_ruplace_param_overrides()
#     matches that key against the --designs value, i.e. the manifest case name, so on this case the
#     emitted string is regression_s14.ruplace_node_util_window:1,regression_s14.ruplace_node_util_blend:1.0
#     (verified applied on nvdla_s in v115: the emitted DREAMPlace params carry window 1 / blend 1.0).
#   * run ids are s14_regression_s14_v116_<config>_s<seed>; disjoint from the concurrently running
#     v115 (nvdla_s_s14) sweep, which also uses a different queue dir and a different CSV + lock.
#   * PARALLELISM: same structure as v115 -- 2 placement workers, each draining its own (cfg,seed)
#     work list with skip-if-exists on raw_metrics.csv; scoring decoupled through a marker queue
#     drained by a single background drainer that keeps at most MAX_SCORE_JOBS (3) concurrent
#     Innovus calls. Work items are cfg:seed pairs (not cfg lists) so the 6 RUPlace runs split 3/3.
#   * Driver timeout stays 14400s == 4 h, which is already the batch-6 requirement.
#   * W1_ITEMS/W2_ITEMS use ${VAR-default} (unset-only), NOT ${VAR:-default}: passing W2_ITEMS=""
#     to run a single placement with no second worker must not fall back to the default list.
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
CASE="${CASE:-regression_s14}"
SEEDS="${SEEDS:-1001 1002}"
REF_METHODS="${REF_METHODS:-dp_hpwl,dp_rudy}"
METHODS="${METHODS:-ruplace}"
RUN_REFS="${RUN_REFS:-1}"
W1_ITEMS="${W1_ITEMS-thr08_g035:1001 thr08_g035:1002 thr08_g070:1001}"
W2_ITEMS="${W2_ITEMS-thr08_g070:1002 thr06_g070_w1:1001 thr06_g070_w1:1002}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v116_queue
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" || true

common=(--case-manifest test/ruplace/s14_cases.json --iterations 1000 --gpu 0 --num-threads 16 \
        --learning-rate 0.010 --xplace-root "$XPLACE_ROOT" --ruplace-router-backend gpugr \
        --ruplace-global-cluster-mode none --eval-route-rrr-iters 1 --ruplace-external-route-eval 0 \
        --ruplace-allow-shrink 1 --legalize-flag 1 --continue-on-error)
ruplace_t10=(--gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030 \
  --ruplace-global-util-exponent 0.745 --ruplace-inflate-area-cap 0.005 --ruplace-inflate-start-overflow 0.30 --ruplace-global-inflate-gamma 0.35 \
  --ruplace-admm-start-overflow 0.33 --ruplace-admm-route-freq 50 --ruplace-admm-apply-freq 5 --ruplace-admm-weight 0.03 --ruplace-admm-anchor-weight 0.10 \
  --ruplace-local-inflate-max-rounds 1 --ruplace-local-inflate-gamma 0.05 --route-rrr-iters 1)
# Decided s14 in-loop GR settings (batches 1-2): 5 Innovus row-height gcells = 2880 dbu.
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 --ruplace-router-backend gpugr)
# v116 base == v115 base: v114 `sched` schedule + v114 `infl_heavy` inflation budget. RUPlace only.
v116_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
# Emitted after ruplace_t10/s14_gr/v116_base so argparse takes the override (later flag wins).
config_flags(){
  local w1=(--ruplace-param-overrides "${CASE}.ruplace_node_util_window:1,${CASE}.ruplace_node_util_blend:1.0")
  case "$1" in
    thr08_g035)     cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.35) ;;
    thr08_g070)     cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.70) ;;
    thr06_g070_w1)  cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70 "${w1[@]}") ;;
    *)              echo "unknown config $1" >&2; return 1 ;;
  esac
}
cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }
run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v116_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
enqueue(){ echo "$CASE" > "$QUEUE/.tmp_$1"; mv -f "$QUEUE/.tmp_$1" "$QUEUE/$1"; }
csv_append(){  # $1 = line; serialize appends against the other v116 scoring jobs
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
worker(){  # $1 = worker id, $2.. = cfg:seed items; placements only, scoring is queued for the drainer
  local wid="$1"; shift
  local item cfg seed runid
  for item in "$@"; do
    cfg="${item%%:*}"; seed="${item##*:}"
    config_flags "$cfg"
    runid="s14_${CASE}_v116_${cfg}_s${seed}"
    run_cmd "$runid" --designs "$CASE" --methods "$METHODS" --random-seed "$seed" \
      "${ruplace_t10[@]}" "${s14_gr[@]}" "${v116_base[@]}" ${cfg_flags[@]+"${cfg_flags[@]}"}
    enqueue "$runid"
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
rm -f "$QUEUE"/.worker*_done
echo "[$(date +%T)] v116 start: case=$CASE refs=$RUN_REFS w1=[$W1_ITEMS] w2=[$W2_ITEMS] seeds=[$SEEDS]"
# Phase 1: legalized references, sequential, NO v116_base (see header).
if [[ "$RUN_REFS" == "1" ]]; then
  for seed in $SEEDS; do
    runid="s14_${CASE}_v116_ref_s${seed}"
    run_cmd "$runid" --designs "$CASE" --methods "$REF_METHODS" --random-seed "$seed" \
      "${ruplace_t10[@]}" "${s14_gr[@]}"
    enqueue "$runid"
  done
fi
# Phase 2: RUPlace placements on 2 workers; refs get scored in parallel with the first placement.
worker 1 $W1_ITEMS & w1=$!
w2=""
if [[ -n "$W2_ITEMS" ]]; then worker 2 $W2_ITEMS & w2=$!; else touch "$QUEUE/.worker2_done"; fi
( drain ) & dp=$!
wait "$w1" || true
[[ -n "$w2" ]] && { wait "$w2" || true; }
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} ----"; cat "results/s14_innovus/${CASE}.csv"
echo "[$(date +%T)] V116_DONE"
