#!/usr/bin/env bash
# v121: adaptive-medium s14 qualification, two designs x two seeds.
# Each work item reruns dp_hpwl, dp_rudy, and ruplace with the same legalized
# placement protocol, then scores every resulting DEF with Innovus 22 NR-eGR.
set -eo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root (script lives in test/ruplace/campaigns/)
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate placement
export CUDA_HOME=/usr/local/cuda-11.8
export PATH="$CONDA_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE

XPLACE_ROOT=/mnt/nvme0n1/yifan/projs/Xplace
ITEMS="${ITEMS-nvdla_s_s14:1001 nvdla_s_s14:1002 regression_s14:1001 regression_s14:1002}"
NUM_WORKERS="${NUM_WORKERS:-2}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
TIMEOUT_SEC="${TIMEOUT_SEC:-21600}"

mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v121_queue
WORKLIST=results/ruplace_quality/logs/v121_worklist.txt
WLOCK=results/ruplace_quality/logs/.v121_worklist.lock
STATUS=results/ruplace_quality/logs/v121_status.txt
mkdir -p "$QUEUE"
: > "$WLOCK"
for case_name in nvdla_s_s14 regression_s14; do
  : > "results/s14_innovus/.${case_name}.csv.lock"
done

common=(
  --case-manifest test/ruplace/s14_cases.json
  --iterations 1000 --gpu 0 --num-threads 16 --learning-rate 0.010
  --gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030
  --stop-overflow 0.10 --legalize-flag 1
  --xplace-root "$XPLACE_ROOT" --methods dp_hpwl,dp_rudy,ruplace
  --ruplace-router-backend gpugr --ruplace-inflation-effort medium
  --ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail
  --ruplace-gr-wire-cost-sat 1 --ruplace-gr-m1-routable 0
  --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0
  --ruplace-write-guides 0 --ruplace-external-route-eval 0
  --ruplace-inflate-start-overflow 0.5 --ruplace-hv-inflate-gamma 0.5
  --ruplace-hv-inflate-mode max --ruplace-allow-shrink 1
  --ruplace-admm-start-overflow 0.55 --ruplace-admm-route-freq 25
  --ruplace-admm-apply-freq 5 --ruplace-admm-weight 0.03
  --ruplace-admm-anchor-weight 0.10 --route-rrr-iters 1
  --eval-route-rrr-iters 1 --continue-on-error
)

write_status() {
  local phase="$1"
  local remaining running scored
  remaining=$(wc -l < "$WORKLIST" 2>/dev/null || echo 0)
  running=$(jobs -rp | wc -l)
  scored=$(find results/s14_innovus -maxdepth 1 -type d -name 's14_*_v121_adaptive_medium_s*_*' | wc -l)
  {
    echo "phase=$phase"
    echo "updated=$(date -Is)"
    echo "remaining=$remaining"
    echo "shell_jobs=$running"
    echo "scored_dirs=$scored"
  } > "$STATUS"
}

cleanup_guides() {
  find "results/ruplace_quality/$1" -type f -name latest.guide -delete 2>/dev/null || true
}

run_item() {
  local case_name="$1" seed="$2"
  local runid="s14_${case_name}_v121_adaptive_medium_s${seed}"
  local log="results/ruplace_quality/logs/v121_${runid}.driver.log"
  if [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]]; then
    echo "[$(date +%T)] skip placement $runid"
    return 0
  fi
  echo "[$(date +%T)] start placement $runid" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout "${TIMEOUT_SEC}s" python3 tools/ruplace_quality.py \
    --run-id "$runid" --designs "$case_name" --random-seed "$seed" \
    "${common[@]}" >> "$log" 2>&1 \
    || echo "[$(date +%T)] WARN placement failed/timed out $runid" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done placement $runid" | tee -a "$log"
}

csv_append() {
  local case_name="$1" line="$2"
  ( flock 9; echo "$line" >> "results/s14_innovus/${case_name}.csv" ) \
    9>"results/s14_innovus/.${case_name}.csv.lock"
}

score_item() {
  local runid="$1" case_name="$2"
  local seed="${runid##*_s}"
  local raw="results/ruplace_quality/${runid}/raw_metrics.csv"
  [[ -f "$raw" ]] || { echo "[$(date +%T)] no raw metrics $runid"; return 0; }
  ( flock 9
    [[ -f "results/s14_innovus/${case_name}.csv" ]] || \
      echo "run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec" \
        > "results/s14_innovus/${case_name}.csv"
  ) 9>"results/s14_innovus/.${case_name}.csv.lock"

  local method def out line
  while IFS=, read -r method def; do
    [[ -n "$method" && -f "$def" ]] || continue
    out="results/s14_innovus/${runid}_${method}"
    if [[ -f "$out/innovus.json" ]]; then
      echo "[$(date +%T)] skip Innovus $runid/$method"
      continue
    fi
    echo "[$(date +%T)] start Innovus $runid/$method"
    line=$( (tools/ruplace_s14_innovus_eval.sh "$case_name" "$def" "$out" global \
      2>>"results/s14_innovus/${runid}.err" || true) | tail -1 )
    [[ -n "$line" ]] || line="${case_name},${def},score_failed,,,,,"
    csv_append "$case_name" "${runid},${method},${seed},${line}"
    echo "[$(date +%T)] done Innovus $runid/$method"
  done < <(python3 - "$raw" <<'PY'
import csv
import sys
for row in csv.DictReader(open(sys.argv[1])):
    if row.get("placed_def"):
        print("%s,%s" % (row["method"], row["placed_def"]))
PY
  )
}

pop_item() {
  ( flock 9
    local item=""
    [[ -s "$WORKLIST" ]] && item=$(head -n 1 "$WORKLIST")
    if [[ -n "$item" ]]; then
      tail -n +2 "$WORKLIST" > "${WORKLIST}.tmp"
      mv -f "${WORKLIST}.tmp" "$WORKLIST"
    fi
    printf '%s' "$item"
  ) 9>"$WLOCK"
}

worker() {
  local worker_id="$1" item case_name seed runid
  while :; do
    item=$(pop_item)
    [[ -n "$item" ]] || break
    case_name=${item%%:*}
    seed=${item##*:}
    runid="s14_${case_name}_v121_adaptive_medium_s${seed}"
    run_item "$case_name" "$seed"
    echo "$case_name" > "$QUEUE/.tmp_${runid}"
    mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/$runid"
    write_status placements_running
  done
  touch "$QUEUE/.worker${worker_id}_done"
  echo "[$(date +%T)] worker $worker_id done"
}

drain_scores() {
  local pending=() marker runid case_name done_workers worker_id
  while :; do
    shopt -s nullglob
    pending=("$QUEUE"/s14_*)
    shopt -u nullglob
    if (( ${#pending[@]} == 0 )); then
      done_workers=0
      for ((worker_id=1; worker_id<=NUM_WORKERS; worker_id++)); do
        [[ -f "$QUEUE/.worker${worker_id}_done" ]] && done_workers=$((done_workers + 1))
      done
      (( done_workers == NUM_WORKERS )) && break
      sleep 20
      continue
    fi
    for marker in "${pending[@]}"; do
      runid=$(basename "$marker")
      case_name=$(cat "$marker")
      rm -f "$marker"
      while (( $(jobs -rp | wc -l) >= MAX_SCORE_JOBS )); do sleep 10; done
      score_item "$runid" "$case_name" &
    done
    write_status scoring
  done
  wait || true
  echo "[$(date +%T)] score drainer done"
}

: > "$WORKLIST"
for item in $ITEMS; do echo "$item" >> "$WORKLIST"; done
rm -f "$QUEUE"/.worker*_done "$QUEUE"/s14_*
write_status starting
echo "[$(date +%T)] V121 start: $(wc -l < "$WORKLIST") items"
cat "$WORKLIST"

worker_pids=()
for ((worker_id=1; worker_id<=NUM_WORKERS; worker_id++)); do
  worker "$worker_id" &
  worker_pids+=("$!")
done
drain_scores &
drainer_pid=$!
for pid in "${worker_pids[@]}"; do wait "$pid" || true; done
wait "$drainer_pid" || true
write_status complete

for case_name in nvdla_s_s14 regression_s14; do
  echo "[$(date +%T)] ---- $case_name ----"
  grep -E '^run_id|_v121_' "results/s14_innovus/${case_name}.csv" || true
done
echo "[$(date +%T)] V121_DONE"
