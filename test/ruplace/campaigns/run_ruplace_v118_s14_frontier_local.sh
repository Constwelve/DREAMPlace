#!/usr/bin/env bash
# v118 (local, yifan405): Phase B batch 8 -- nvdla_s_s14 frontier at MATCHED WL, Innovus scored,
# legalized protocol (--legalize-flag 1).
#
# Why: on nvdla_s_s14 the v115 RUPlace frontier (worst seed) tops out at
#   thr08_g035 WL 4,535,773 / H 33,381 / V 14,661  and  thr06_g070_w1 4,608,371 / 25,696 / 12,525,
# while a FAIR dp_rudy (v117, --node-area-adjust-overflow 0.25, so the RUDY rounds actually fire)
# reaches H 18,107 / V 9,022 at WL 4,813,582. The two methods therefore sit at different WL and the
# comparison is not yet apples-to-apples. Two things are needed:
#   (a) push RUPlace further along its own WL/congestion trade-off. In v115 the binding constraint at
#       thr <= 0.6 was --ruplace-max-inflate-ratio (logs show "ratio avg/max 1.1234/2.0000",
#       "ratio-limited"), NOT the area cap (max cumulative area was ~13.5% against a 0.15 cap).
#       So every RUPlace config here runs --ruplace-max-inflate-ratio 3.0 --ruplace-inflate-area-cap 0.30
#       and sweeps the threshold down (0.6/0.5/0.4) at gamma 0.70/1.00.
#   (b) fill in the dp_rudy curve so a matched-WL comparison can be interpolated: node_area_adjust_overflow
#       0.20 and 0.30 bracket the existing 0.25 anchor, and rudy025_r5 raises max_num_area_adjust to 5
#       (new --max-num-area-adjust driver flag, default 3 = legacy) at overflow 0.25.
#
# PROTOCOL NOTE: the dp_rudy points deliberately reuse v117's exact protocol
# (common + ruplace_t10 + s14_gr, NO v118_base, --stop-overflow left at its 0.15 default) so that
# rudy020/rudy025_r5/rudy030 are directly comparable with the existing v117 `_ref_rudy025_` and
# v114 `_ref_` dp_hpwl/dp_rudy rows in results/s14_innovus/nvdla_s_s14.csv. The RUPlace points reuse
# v115's protocol (common + ruplace_t10 + s14_gr + v118_base == v115_base) plus the r3 overrides.
#
# References already in the CSV and NOT rerun here: v114 `_ref_` (dp_hpwl, dp_rudy default),
# v117 `_ref_rudy025_` (dp_rudy @ 0.25), and the v115 thr* RUPlace points.
#
# PARALLELISM: 2 placement workers popping from a single flock-guarded work list (dp_rudy items are
# ordered first so the cheap frontier anchors land early), scoring decoupled through a marker queue
# drained by one background drainer holding at most MAX_SCORE_JOBS (3) concurrent Innovus calls.
# routability_eval/innovus.py mkdtemps its work dir under cadence_mounted_root, so concurrent Innovus
# calls (including the concurrently running v116/v117 batch's) do not collide. CSV appends take an flock.
# Run ids are s14_<case>_v118_<config>_s<seed>; disjoint from every other batch.
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
RUDY_CONFIGS="${RUDY_CONFIGS:-rudy025_r5 rudy020 rudy030}"
RUPLACE_CONFIGS="${RUPLACE_CONFIGS:-r3_thr06_g070 r3_thr05_g070 r3_thr04_g070 r3_thr05_g100 r3_thr04_g100_w1}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-3}"
NUM_WORKERS="${NUM_WORKERS:-2}"
mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE=results/ruplace_quality/logs/v118_queue
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" 2>/dev/null || true
WORKLIST=results/ruplace_quality/logs/v118_worklist.txt
WLOCK=results/ruplace_quality/logs/.v118_worklist.lock
: > "$WLOCK" 2>/dev/null || true

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
# v118 RUPlace base: byte-identical to v115_base (sched + cap 0.15 + 3 local rounds + hv 0.5 max + start 0.5).
v118_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
# Batch-8 lever: lift the ratio ceiling that bound every v115 thr<=0.6 run, and widen the area cap
# so the ratio is the only thing being tested. Emitted after v118_base so argparse takes it.
r3_over=(--ruplace-max-inflate-ratio 3.0 --ruplace-inflate-area-cap 0.30)
config_flags(){  # sets cfg_flags and cfg_method
  local w1=(--ruplace-param-overrides "${CASE}.ruplace_node_util_window:1,${CASE}.ruplace_node_util_blend:1.0")
  case "$1" in
    r3_thr06_g070)    cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70) ;;
    r3_thr05_g070)    cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.70) ;;
    r3_thr04_g070)    cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.4 --ruplace-global-inflate-gamma 0.70) ;;
    r3_thr05_g100)    cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 1.0) ;;
    r3_thr04_g100_w1) cfg_method=ruplace; cfg_flags=(--ruplace-inflate-util-threshold 0.4 --ruplace-global-inflate-gamma 1.0 "${w1[@]}") ;;
    rudy020)          cfg_method=dp_rudy; cfg_flags=(--node-area-adjust-overflow 0.20) ;;
    rudy030)          cfg_method=dp_rudy; cfg_flags=(--node-area-adjust-overflow 0.30) ;;
    rudy025_r5)       cfg_method=dp_rudy; cfg_flags=(--node-area-adjust-overflow 0.25 --max-num-area-adjust 5) ;;
    *)                echo "unknown config $1" >&2; return 1 ;;
  esac
}
cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }
run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v118_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout 14400s python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}
csv_append(){ ( flock 9; echo "$1" >> "results/s14_innovus/${CASE}.csv" ) 9>"$LOCK"; }
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
pop(){  # atomically remove and echo the first work item; empty output == list exhausted
  ( flock 9
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
    runid="s14_${CASE}_v118_${cfg}_s${seed}"
    if [[ "$cfg_method" == "dp_rudy" ]]; then
      # v117 protocol exactly: no v118_base, no r3_over, --stop-overflow at its 0.15 default.
      run_cmd "$runid" --designs "$CASE" --methods dp_rudy --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${cfg_flags[@]}"
    else
      run_cmd "$runid" --designs "$CASE" --methods ruplace --random-seed "$seed" \
        "${ruplace_t10[@]}" "${s14_gr[@]}" "${v118_base[@]}" "${r3_over[@]}" "${cfg_flags[@]}"
    fi
    # atomic enqueue: write hidden then rename, so the drainer never reads a partial marker
    echo "$CASE" > "$QUEUE/.tmp_${runid}"; mv -f "$QUEUE/.tmp_${runid}" "$QUEUE/${runid}"
  done
  touch "$QUEUE/.worker${wid}_done"
  echo "[$(date +%T)] worker ${wid} done"
}
drain(){  # single consumer: at most MAX_SCORE_JOBS concurrent Innovus evaluations
  local pending=() f runid case_name n
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
# Build the work list: cheap dp_rudy frontier anchors first, then the long RUPlace runs.
: > "$WORKLIST"
for cfg in $RUDY_CONFIGS;    do for seed in $SEEDS; do echo "${cfg}:${seed}" >> "$WORKLIST"; done; done
for cfg in $RUPLACE_CONFIGS; do for seed in $SEEDS; do echo "${cfg}:${seed}" >> "$WORKLIST"; done; done
rm -f "$QUEUE"/.worker*_done
echo "[$(date +%T)] v118 start: $(wc -l < "$WORKLIST") items, ${NUM_WORKERS} workers, case=${CASE}"
cat "$WORKLIST"
pids=()
for ((i=1;i<=NUM_WORKERS;i++)); do worker "$i" & pids+=("$!"); done
( drain ) & dp=$!
for p in "${pids[@]}"; do wait "$p" || true; done
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} ----"
grep -E "^run_id|_v118_" "results/s14_innovus/${CASE}.csv" || true
echo "[$(date +%T)] V118_DONE"
