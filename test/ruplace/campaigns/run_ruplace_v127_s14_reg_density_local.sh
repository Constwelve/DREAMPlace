#!/usr/bin/env bash
# v127: does a global local-density cap remove the bimodal density (and H overflow) on regression_s14?
# dp_hpwl only (no router), legalized, Innovus EGR scored with DUMP_CONGEST=1. Single worker.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
set +u; source "$HOME/miniconda3/etc/profile.d/conda.sh"; conda activate placement; set -u
export CUDA_HOME="$CONDA_PREFIX"; export PATH="$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE
CASE=regression_s14; CSV=results/s14_innovus/${CASE}.csv; LOCK=results/s14_innovus/.${CASE}.csv.lock; : > "$LOCK"
mkdir -p results/ruplace_quality/logs
run_one(){  # name td bins
  local name="$1" td="$2" bins="$3"
  local runid="s14_${CASE}_v127_${name}_s1001"
  if [[ ! -f results/ruplace_quality/$runid/raw_metrics.csv ]]; then
    echo "[$(date +%T)] start $runid"
    CUDA_VISIBLE_DEVICES=0 timeout 14400 python3 tools/ruplace_quality.py --run-id "$runid" \
      --case-manifest test/ruplace/s14_cases.json --designs $CASE --methods dp_hpwl --random-seed 1001 \
      --iterations 1000 --gpu 0 --num-threads 16 --learning-rate 0.010 --gp-gamma 0.92 --gp-noise-ratio 0.030 \
      --target-density "$td" --num-bins "$bins" --stop-overflow 0.15 --legalize-flag 1 \
      --xplace-root /mnt/nvme0n1/yifan/projs/Xplace --ruplace-router-backend gpugr --eval-route-rrr-iters 1 \
      --continue-on-error > results/ruplace_quality/logs/${runid}.driver.log 2>&1 || echo "[$(date +%T)] WARN $runid rc=$?"
  fi
  local def; def=$(ls results/ruplace_quality/$runid/dreamplace/dp_hpwl/$CASE/results/*/*.gp.def 2>/dev/null | head -1)
  [[ -n "$def" ]] || { echo "[$(date +%T)] $runid: no DEF"; return; }
  local out=results/s14_innovus/${runid}_dp_hpwl
  grep -q "^$runid," "$CSV" && { echo "[$(date +%T)] $runid already scored"; return; }
  DUMP_CONGEST=1 tools/ruplace_s14_innovus_eval.sh $CASE "$def" "$out" global > "$out.stdout" 2>&1 || true
  local line; line=$(tail -1 "$out.stdout")
  [[ -n "$line" ]] && flock "$LOCK" bash -c "echo \"$runid,dp_hpwl,1001,$line\" >> \"$CSV\"" && echo "[$(date +%T)] $runid: $line"
}
run_one td060_b512 0.60 512
run_one td050_b512 0.50 512
run_one td080_b1024 0.80 1024
run_one td060_b1024 0.60 1024
echo "V127_DONE"
