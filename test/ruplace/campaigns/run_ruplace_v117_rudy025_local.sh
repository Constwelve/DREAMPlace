#!/usr/bin/env bash
# v117 (local, yifan405): Phase B batch 7 item 2 -- FAIR dp_rudy reference on both SMIC14 designs.
#
# Why: DREAMPlace's RUDY/pin area adjustment (routability_opt_flag=1) only runs while the density
# overflow is ABOVE params.node_area_adjust_overflow, which the driver hard-coded to 0.15 -- exactly
# the default --stop-overflow. On regression_s14 that means dp_rudy performs a single adjustment
# round at iteration 518 and global placement then stops at 519: the +10% area inflation is paid for
# and never exploited. tools/ruplace_quality.py now exposes --node-area-adjust-overflow (default
# 0.15, i.e. unchanged behaviour); this batch runs the dp_rudy reference with 0.25 so the inflated
# placement actually gets iterations to spread into.
#
# Protocol is byte-identical to the v116/v114 `ref` pass otherwise: ruplace_t10 + s14_gr + common
# (--legalize-flag 1), stop_overflow left at its 0.15 default, NO v116_base. Only --methods dp_rudy
# and --node-area-adjust-overflow 0.25 are added. Run ids: s14_<case>_v117_ref_rudy025_s<seed>.
# Rows are appended to results/s14_innovus/<case>.csv, the same files v114/v115/v116 use.
#
# PARALLELISM: same as v116 -- 2 placement workers draining their own (case,seed) work lists with
# skip-if-exists on raw_metrics.csv, scoring decoupled through a marker queue drained by a single
# background drainer holding at most MAX_SCORE_JOBS (3) concurrent Innovus calls. The marker file
# holds the case name so the drainer knows which CSV/lock to use.
set -eo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate placement
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
XPLACE_ROOT=/mnt/nvme0n1/yifan/projs/Xplace
# Must NOT contain the external Xplace cpp_to_py/cpybin/build dirs (see v113).
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE
NAAO="${NAAO:-0.25}"
CFGNAME="${CFGNAME:-ref_rudy025}"
W1_ITEMS="${W1_ITEMS-regression_s14:1001 regression_s14:1002}"
W2_ITEMS="${W2_ITEMS-nvdla_s_s14:1001 nvdla_s_s14:1002}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v117_rudy_queue
mkdir -p "$QUEUE"

common=(--case-manifest test/ruplace/s14_cases.json --iterations 1000 --gpu 0 --num-threads 16 \
        --learning-rate 0.010 --xplace-root "$XPLACE_ROOT" --ruplace-router-backend gpugr \
        --ruplace-global-cluster-mode none --eval-route-rrr-iters 1 --ruplace-external-route-eval 0 \
        --ruplace-allow-shrink 1 --ruplace-inflation-effort legacy --legalize-flag 1 --continue-on-error)
ruplace_t10=(--gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030 \
  --ruplace-global-util-exponent 0.745 --ruplace-inflate-area-cap 0.005 --ruplace-inflate-start-overflow 0.30 --ruplace-global-inflate-gamma 0.35 \
  --ruplace-admm-start-overflow 0.33 --ruplace-admm-route-freq 50 --ruplace-admm-apply-freq 5 --ruplace-admm-weight 0.03 --ruplace-admm-anchor-weight 0.10 \
  --ruplace-local-inflate-max-rounds 1 --ruplace-local-inflate-gamma 0.05 --route-rrr-iters 1)
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 --ruplace-router-backend gpugr)

run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v117_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
enqueue(){ echo "$2" > "$QUEUE/.tmp_$1"; mv -f "$QUEUE/.tmp_$1" "$QUEUE/$1"; }
score(){
  local runid="$1" case_name="$2"
  local raw="results/ruplace_quality/${runid}/raw_metrics.csv"
  local csv="results/s14_innovus/${case_name}.csv"
  local lock="results/s14_innovus/.${case_name}.csv.lock"
  : > "$lock" 2>/dev/null || true
  [[ -f "$raw" ]] || { echo "[$(date +%T)] no raw_metrics for ${runid}; skip score"; return 0; }
  ( flock 9
    [[ -f "$csv" ]] || \
      echo "run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec" > "$csv"
  ) 9>"$lock"
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
    ( flock 9; echo "${runid},${method},${runid##*_s},${line}" >> "$csv" ) 9>"$lock"
  done
}
worker(){
  local wid="$1"; shift
  local item case_name seed runid
  for item in "$@"; do
    case_name="${item%%:*}"; seed="${item##*:}"
    runid="s14_${case_name}_v117_${CFGNAME}_s${seed}"
    run_cmd "$runid" --designs "$case_name" --methods dp_rudy --random-seed "$seed" \
      --node-area-adjust-overflow "$NAAO" "${ruplace_t10[@]}" "${s14_gr[@]}"
    enqueue "$runid" "$case_name"
  done
  touch "$QUEUE/.worker${wid}_done"
  echo "[$(date +%T)] worker ${wid} done"
}
drain(){
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
echo "[$(date +%T)] v117 rudy${NAAO} start: w1=[$W1_ITEMS] w2=[$W2_ITEMS]"
worker 1 $W1_ITEMS & w1=$!
w2=""
if [[ -n "$W2_ITEMS" ]]; then worker 2 $W2_ITEMS & w2=$!; else touch "$QUEUE/.worker2_done"; fi
( drain ) & dp=$!
wait "$w1" || true
[[ -n "$w2" ]] && { wait "$w2" || true; }
wait "$dp" || true
echo "[$(date +%T)] V117_RUDY_DONE"
