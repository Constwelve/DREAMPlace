#!/usr/bin/env bash
# v112 (local, yifan405): Phase B batch 3a -- first RUPlace-on-s14 run, plus s14 references.
#   Placement: dp_hpwl / dp_rudy / ruplace (bundled GPUGR in-loop) on one or more s14 cases.
#   Scoring:   every placed DEF -> tools/ruplace_s14_innovus_eval.sh (Innovus 22 earlyGlobalRoute).
# Same body as v110 with two changes:
#   * CASES (space-separated list) replaces the single CASE; score() takes the case as an argument
#     so each case writes into its own results/s14_innovus/<case>.csv;
#   * the s14_gr flag array carries the batch-1/2 decided in-loop GR settings (2880 dbu gcells via
#     --ruplace-gr-grid step:2880, avail utilization, wire-cost saturation, M1 unroutable,
#     max_route_len_per_pin 256, no extra via demand, no guide writes, rrr=1, in-process eval).
# RUPlace placement parameters are still the ISPD18 test10 composite set: untuned on s14.
set -eo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate placement
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
XPLACE_ROOT=/mnt/nvme0n1/yifan/projs/Xplace
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$XPLACE_ROOT/cpp_to_py/cpybin:$XPLACE_ROOT/build:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE
CASES="${CASES:-nvdla_s_s14}"
SEEDS="${SEEDS:-1001 1002}"
METHODS="${METHODS:-dp_hpwl,dp_rudy}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
common=(--case-manifest test/ruplace/s14_cases.json --iterations 1000 --gpu 0 --num-threads 16 \
        --learning-rate 0.010 --xplace-root "$XPLACE_ROOT" --ruplace-router-backend gpugr \
        --ruplace-global-cluster-mode none --eval-route-rrr-iters 1 --ruplace-external-route-eval 0 \
        --ruplace-allow-shrink 1 --ruplace-inflation-effort legacy --continue-on-error)
ruplace_t10=(--gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030 \
  --ruplace-global-util-exponent 0.745 --ruplace-inflate-area-cap 0.005 --ruplace-inflate-start-overflow 0.30 --ruplace-global-inflate-gamma 0.35 \
  --ruplace-admm-start-overflow 0.33 --ruplace-admm-route-freq 50 --ruplace-admm-apply-freq 5 --ruplace-admm-weight 0.03 --ruplace-admm-anchor-weight 0.10 \
  --ruplace-local-inflate-max-rounds 1 --ruplace-local-inflate-gamma 0.05 --route-rrr-iters 1)
# Decided s14 in-loop GR settings (batches 1-2): 5 Innovus row-height gcells = 2880 dbu.
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 --ruplace-router-backend gpugr)
cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }
run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
score(){  # score every placed DEF of a run with Innovus EGR; append to results/s14_innovus/<case>.csv
  local runid="$1" case="$2" csv
  csv="results/s14_innovus/${case}.csv"
  [[ -f "$csv" ]] || echo "run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec" > "$csv"
  python3 - "$runid" <<"PY" | while IFS=, read -r method def; do
import csv, sys
run = sys.argv[1]
for r in csv.DictReader(open("results/ruplace_quality/%s/raw_metrics.csv" % run)):
    if r.get("placed_def"): print("%s,%s" % (r["method"], r["placed_def"]))
PY
    local out="results/s14_innovus/${runid}_${method}"
    if [[ -f "$out/innovus.json" ]]; then echo "[$(date +%T)] skip score ${runid}/${method}"; continue; fi
    echo "[$(date +%T)] innovus ${runid}/${method}"
    local line; line=$( (tools/ruplace_s14_innovus_eval.sh "$case" "$def" "$out" global 2>>"results/s14_innovus/${runid}.err" || true) | tail -1)
    [[ -n "$line" ]] || line="${case},${def},score_failed,,,,,"
    echo "${runid},${method},${runid##*_s},${line}" >> "$csv"
  done
}
for CASE in $CASES; do
  for seed in $SEEDS; do
    run_cmd "s14_${CASE}_v112_s${seed}" --designs "$CASE" --methods "$METHODS" --random-seed "$seed" \
      "${ruplace_t10[@]}" "${s14_gr[@]}"
    score "s14_${CASE}_v112_s${seed}" "$CASE" || true
  done
  echo "[$(date +%T)] ---- ${CASE} ----"; cat "results/s14_innovus/${CASE}.csv"
done
echo "[$(date +%T)] V112_DONE"
