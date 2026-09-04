#!/usr/bin/env bash
# v126 (local, yifan405): Phase 2 lever test on regression_s14 (OpenC910 ct_top, 735k cells, core
# utilization 49.7%). GOAL: Innovus [NR-eGR] "low" congestion -- BOTH H and V <= 5% ("medium" <= 2%)
# at the smallest routed WL. Reference frontier (legalized, seed 1001, NR-eGR H/V %, WL um):
#     dp_hpwl                 11,166,016  13.02/7.35
#     v116 thr06_g070_w1      11,706,819  10.11/5.59  (+4.8% WL)
#     v123 adaptive medium    13,758,326   6.11/3.14  (+23% WL)
#     Innovus place_design                 0.30/0.59  (+15.7% WL)
# Every v119-v125 point is pure *cell inflation*. v126 tests the two levers that are NOT inflation.
#
# LEVER 1 -- congestion soft blockage (--ruplace-congestion-blockage B, defaults threshold 0.7,
#   max 0.5, smooth 1, decay 0.5, start_overflow 0.5). At each congestion-map refresh the hot bins
#   get extra *fixed* density, so the existing electrostatic density force spreads cells out of them
#   instead of the cells being grown. Log line: "RUPlace congestion blockage refresh N: bins blocked
#   .../..., extra mean/max .../..., removed area ... (X% of the placement region), overflow before
#   refresh ...". Expect the reported GP overflow to step UP at the refresh iteration (capacity was
#   just removed).
#
# LEVER 2 -- Innovus closed-loop proxy (--ruplace-inflate-proxy innovus). The *inflation* congestion
#   map comes from an Innovus eGR (dumpCongestArea) of the current placement instead of GPUGR; ADMM
#   keeps using GPUGR (it needs per-net routes, which eGR does not return). ~100 s + one DEF + an
#   83 MB dump per call under <result_dir>/<design>/ruplace/innovus/call_NNNN/. Log line:
#   "RUPlace Innovus eGR: call N iter I | ...s | NR-eGR H/V x/y% | WL ... um | ...".
#
# ---- IMPORTANT MECHANISM NOTE (read before interpreting any blockage row) ----------------------
# ruplace_op.maybe_adjust_area() does:  self._last_route_for_blockage = None; maybe_inflate();
# _maybe_update_blockage().  Only _maybe_inflate_legacy()'s route call sets _last_route_for_blockage.
# So a blockage refresh can ONLY happen on an iteration where the inflation path actually routed.
# Once _maybe_inflate_legacy() early-returns (global_inflation_done AND inflation_rounds >=
# max_rounds) there are no more routes and therefore NO more blockage refreshes, ever.
# Consequence for the "blockage without inflation" isolation cell: with
# --ruplace-global-inflate-gamma 0.0 every node ratio is 1.0, so RUPlaceInflation.apply() returns
# False, and the state machine walks
#     call 1: route (refresh #1), global_pass -> "global inflation made no area adjustment",
#             global_inflation_done = True
#     call 2: route (refresh #2), not global_pass -> else-branch sets inflation_rounds = max_rounds,
#             "RUPlace inflation converged; no further area adjustment"
#     call 3+: early return, no route, no refresh
# i.e. exactly TWO refreshes, and raising --ruplace-local-inflate-max-rounds does not help because
# the else-branch slams inflation_rounds to max_rounds. That is a weaker DOSE of the lever, not an
# isolation of it. v126 therefore runs BOTH cells (they fit in the same number of 2-worker waves):
#     B_blk050_noinfl   literal: cap 0.005 + global gamma 0.0   -> ~0% area, ~2 refreshes
#     B_blk050_lowinfl  matched: cap 0.005, gamma left at the ruplace_t10 base 0.35
#                       -> ~0.5%/round x ~4 rounds ~= +2% area, ~4-5 refreshes (same refresh count
#                          as B_blk050, so the blockage dose is comparable and only the inflation
#                          area differs)  <-- this is the row to read for "blockage alone".
# Second interaction to remember when reading B_blk050_r3thr05: _maybe_update_blockage() calls
# inflation.set_blocked_area(), and legacy apply_node_ratios() uses
# max_inc = min(whitespace, cap * movable_area), so blockage EATS the inflation whitespace budget.
# The stacked row will inflate less than v125's L_r3_thr05_g070 did at the same cap.
#
# CONFIGS (all: common + ruplace_t10 + s14_gr + v126_base(==v125_base) + per-config overrides)
#  Phase A (NUM_WORKERS=2, no proxy):
#   B_blk050          blockage 0.5                                   <- main dose
#   B_blk050_r3thr05  blockage 0.5 + v125 L_r3_thr05_g070 overrides   <- stacking
#   B_blk050_lowinfl  blockage 0.5 + cap 0.005 (gamma at base 0.35)   <- blockage alone, matched
#   B_blk050_noinfl   blockage 0.5 + cap 0.005 + gamma 0.0            <- blockage alone, literal
#   B_blk030          blockage 0.3                                    <- dose-response
#   B_blk050_thr06    blockage 0.5 + threshold 0.6                    <- threshold sweep
#  Phase B (NUM_WORKERS=1, SCORE_INLINE=1, proxy on -- must be the ONLY Innovus user of ours):
#   P_innovus_r3thr05 v125 L_r3_thr05_g070 overrides + the three proxy flags
#   P_innovus_blk050  blockage 0.5 + the three proxy flags
#
# PHASE B SERIALIZATION: innovus_proxy._FileLock guards
# /mnt/nvme0n1/yifan/projs/DREAMPlace/results/locks/ruplace_innovus.lock, but
# tools/ruplace_s14_innovus_eval.sh (the SCORER) does not take it, so NUM_WORKERS=1 +
# MAX_SCORE_JOBS=1 alone would still let the drainer score run A while run B's proxy calls Innovus.
# SCORE_INLINE=1 makes the worker score right after its own placement and skips the queue entirely,
# so Phase B is strictly one Innovus process at a time. (The proxy's own lock has a 3600 s timeout
# and run_route() swallows TimeoutError into a SILENT GPUGR fallback, which would quietly turn a
# Phase B row into a Phase A row -- hence the guard below greps for the fallback warnings.)
#
# SEEDS: seed 1001 only in this pass. Afterwards, the two lowest-(H+V) configs with WL <= +16% vs
# dp_hpwl 11,166,016 get seed 1002 via
#   SEEDS=1002 PHASE=A CONFIGS="<cfg> <cfg>" ./run_ruplace_v126_s14_reg_levers_local.sh
# (skip-if-exists on raw_metrics.csv makes the 1001 rows no-ops).
#
# CSV: results/s14_innovus/<case>.csv, 13 columns
#   run_id,method,seed,case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,
#   runtime_sec,egr_h_pct,egr_v_pct
# ensure_header() migrates an old 11-column header in place under the shared append lock (verbatim
# from v125). Verdicts use egr_h_pct/egr_v_pct (the Innovus [NR-eGR] percentages), NOT the raw
# horizontal_overflow/vertical_overflow counts.
#
# Run ids are s14_<case>_v126_<config>_s<seed>; queue dir, worklist and their locks are v126- and
# phase-specific, so this is disjoint from every other batch. The CSV append lock is shared on
# purpose. Nothing here touches or kills any other batch's processes.
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
PHASE="${PHASE:-A}"
# 6 h. v125 lost TWO rows to its 14400s ceiling: L_td070_thr06_g070 placed fine (Placer.py
# elapsed_sec 10043) but was killed during the post-placement GGR eval, and L_r3_thr05_g070 never
# even reached the end of placement. A run killed at the wall writes no raw_metrics.csv, so it
# yields no CSV row at all -- a fully wasted 4-6 h, strictly worse than letting a slow run finish.
# Heavy inflation is what drives both the GP slowdown and the eval blowup; the blockage configs grow
# little area and should land near cap50's 4209 s, so this ceiling only ever pays out on
# B_blk050_r3thr05 and on Phase B (~4-8 Innovus calls = ~1200 s on top).
RUN_TIMEOUT="${RUN_TIMEOUT:-21600s}"
case "$PHASE" in
  A) DEF_CONFIGS="B_blk050 B_blk050_r3thr05 B_blk050_lowinfl B_blk050_noinfl B_blk030 B_blk050_thr06"
     DEF_WORKERS=2; DEF_SCORE_JOBS=3; DEF_INLINE=0 ;;
  B) DEF_CONFIGS="P_innovus_r3thr05 P_innovus_blk050"
     DEF_WORKERS=1; DEF_SCORE_JOBS=1; DEF_INLINE=1 ;;
  *) echo "unknown PHASE $PHASE (want A or B)" >&2; exit 2 ;;
esac
CONFIGS="${CONFIGS:-$DEF_CONFIGS}"
NUM_WORKERS="${NUM_WORKERS:-$DEF_WORKERS}"
MAX_SCORE_JOBS="${MAX_SCORE_JOBS:-$DEF_SCORE_JOBS}"
SCORE_INLINE="${SCORE_INLINE:-$DEF_INLINE}"

mkdir -p results/ruplace_quality/logs results/s14_innovus
QUEUE="results/ruplace_quality/logs/v126${PHASE}_queue"
mkdir -p "$QUEUE"
LOCK="results/s14_innovus/.${CASE}.csv.lock"
: > "$LOCK" 2>/dev/null || true
WORKLIST="results/ruplace_quality/logs/v126${PHASE}_worklist.txt"
WLOCK="results/ruplace_quality/logs/.v126${PHASE}_worklist.lock"
: > "$WLOCK" 2>/dev/null || true
GLOCK="results/ruplace_quality/logs/.v126${PHASE}_guard.lock"
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
# v126_base == v125_base == v116_base, byte-identical (sched + cap 0.15 + 3 local rounds + hv 0.5
# mode max + inflate start 0.5). Per-config overrides are emitted AFTER it so argparse (last flag
# wins) takes them; `common` is appended last by run_cmd and intentionally re-asserts
# --ruplace-inflation-effort legacy on every single run.
v126_base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)

config_flags(){  # sets cfg_flags and cfg_method
  # v125's best-hope legacy overrides (config L_r3_thr05_g070): ratio 3.0, cap 0.30, thr 0.5, g 0.70
  local r3thr05=(--ruplace-max-inflate-ratio 3.0 --ruplace-inflate-area-cap 0.30 \
                 --ruplace-inflate-util-threshold 0.5 --ruplace-global-inflate-gamma 0.70)
  # all blockage knobs are given explicitly, even where they equal the params.json default, so the
  # driver log records the full dose and a later default change cannot silently move these rows.
  local blk_common=(--ruplace-congestion-blockage-max 0.5 --ruplace-congestion-blockage-smooth 1 \
                    --ruplace-congestion-blockage-decay 0.5 \
                    --ruplace-congestion-blockage-start-overflow 0.5)
  local blk050=(--ruplace-congestion-blockage 0.5 --ruplace-congestion-blockage-threshold 0.7 "${blk_common[@]}")
  local proxy=(--ruplace-inflate-proxy innovus --ruplace-innovus-proxy-min-interval 0 \
               --ruplace-innovus-case "$CASE")
  cfg_method=ruplace
  case "$1" in
    B_blk050)          cfg_flags=("${blk050[@]}") ;;
    B_blk030)          cfg_flags=(--ruplace-congestion-blockage 0.3 --ruplace-congestion-blockage-threshold 0.7 "${blk_common[@]}") ;;
    B_blk050_thr06)    cfg_flags=(--ruplace-congestion-blockage 0.5 --ruplace-congestion-blockage-threshold 0.6 "${blk_common[@]}") ;;
    # inflation effectively off, literal spec: cap 0.005 AND global gamma 0.0 -> zero area growth.
    # Keeps 3 local rounds so the map *could* refresh, but see the mechanism note: it yields ~2.
    B_blk050_noinfl)   cfg_flags=("${blk050[@]}" --ruplace-inflate-area-cap 0.005 \
                                  --ruplace-global-inflate-gamma 0.0 --ruplace-local-inflate-max-rounds 3) ;;
    # inflation effectively off, refresh-matched: cap 0.005 only (gamma stays at the base 0.35), so
    # apply() keeps returning True, rounds advance, and the blockage refresh count matches B_blk050.
    B_blk050_lowinfl)  cfg_flags=("${blk050[@]}" --ruplace-inflate-area-cap 0.005 \
                                  --ruplace-local-inflate-max-rounds 3) ;;
    B_blk050_r3thr05)  cfg_flags=("${blk050[@]}" "${r3thr05[@]}") ;;
    P_innovus_r3thr05) cfg_flags=("${r3thr05[@]}" "${proxy[@]}") ;;
    P_innovus_blk050)  cfg_flags=("${blk050[@]}" "${proxy[@]}") ;;
    *) echo "unknown config $1" >&2; return 1 ;;
  esac
}

cleanup_guides(){ find "results/ruplace_quality/$1" -type f -name "latest.guide" -delete 2>/dev/null || true; }

# Innovus proxy artifacts: one DEF + one ~83 MB dumpCongestArea per call. The trajectory we report
# comes from dreamplace.log ("RUPlace Innovus eGR: call ..."), which survives, and innovus.json is
# kept; only the bulky DEF/dump are removed, and only after the run is finished.
cleanup_proxy_artifacts(){
  local d="results/ruplace_quality/$1"
  [[ -d "$d" ]] || return 0
  local before after
  before=$(du -sm "$d" 2>/dev/null | cut -f1)
  find "$d" -path "*/ruplace/innovus/call_*" -type f \
       \( -name "*.def" -o -name "innovus_congest_area.txt" \) -delete 2>/dev/null || true
  after=$(du -sm "$d" 2>/dev/null | cut -f1)
  echo "[$(date +%T)] proxy artifact cleanup ${1}: ${before} MB -> ${after} MB"
}

run_cmd(){
  local runid="$1"; shift
  local log="results/ruplace_quality/logs/v126_${runid}.driver.log"
  [[ -f "results/ruplace_quality/${runid}/raw_metrics.csv" ]] && { echo "[$(date +%T)] skip ${runid}"; return 0; }
  echo "[$(date +%T)] start ${runid}" | tee "$log"
  CUDA_VISIBLE_DEVICES=0 timeout "$RUN_TIMEOUT" python3 tools/ruplace_quality.py --run-id "$runid" "$@" "${common[@]}" >>"$log" 2>&1 \
    || echo "[$(date +%T)] WARN ${runid} failed/timed out" | tee -a "$log"
  cleanup_guides "$runid"
  echo "[$(date +%T)] done ${runid}" | tee -a "$log"
}

# --- guard: run once per phase, on the first RUPlace run that finishes ---------------------------
guard_check(){  # $1 = runid, $2 = config ; prints a verdict, returns nonzero on failure
  local runid="$1" cfg="$2" raw="results/ruplace_quality/$1/raw_metrics.csv"
  local dlog="results/ruplace_quality/$1/dreamplace/ruplace/${CASE}/dreamplace.log"
  local ok=1
  echo "[guard] phase=${PHASE} runid=${runid} config=${cfg}"
  if [[ -f "$raw" ]] && grep -q ",ok," "$raw"; then echo "[guard] status ok: PASS"; else echo "[guard] status ok: FAIL"; ok=0; fi
  if [[ -f "$dlog" ]] && grep -q "legalization takes" "$dlog"; then echo "[guard] legalization logged: PASS"; else echo "[guard] legalization logged: FAIL"; ok=0; fi
  [[ -f "$dlog" ]] || { echo "[guard] no dreamplace.log at $dlog"; (( ok == 1 )); return; }

  # cumulative inflated area (product of the per-round increments), informational for the *_noinfl
  # cells where ~0 is the intended outcome.
  local cum
  cum=$(grep -o "inflation: area increment [0-9.E+-]* ([0-9.]*)" "$dlog" \
        | sed -E 's/.*\(([0-9.]*)\)/\1/' \
        | awk '{p=(p==""?1:p)*(1+$1)} END{if(p=="")print "0"; else printf "%.4f", p-1}')
  grep "inflation: area increment" "$dlog" | sed 's/^/[guard]   /'
  echo "[guard] cumulative area increase: ${cum}"
  grep -q "RUPlace global inflation made no area adjustment" "$dlog" \
    && echo "[guard] NOTE: global inflation made no area adjustment (inflation loop shut down early)"

  # lever 1: blockage refreshes
  if [[ "$cfg" == B_* || "$cfg" == *blk* ]]; then
    local nblk
    nblk=$(grep -c "RUPlace congestion blockage refresh" "$dlog" || true)
    grep "RUPlace congestion blockage refresh" "$dlog" | sed 's/^/[guard]   /'
    if (( nblk > 0 )); then echo "[guard] blockage refreshes: ${nblk} (PASS)"
    else echo "[guard] blockage refreshes: 0 (FAIL)"; ok=0; fi
  fi

  # lever 2: Innovus proxy calls, and NO silent fallback to GPUGR / the cached map
  if [[ "$cfg" == P_* ]]; then
    local ncall
    ncall=$(grep -c "RUPlace Innovus eGR: call" "$dlog" || true)
    grep "RUPlace Innovus proxy: case=" "$dlog" | sed 's/^/[guard]   /'
    grep "RUPlace Innovus eGR: call" "$dlog" | sed 's/^/[guard]   /'
    if (( ncall > 0 )); then echo "[guard] Innovus proxy calls: ${ncall} (PASS)"
    else echo "[guard] Innovus proxy calls: 0 (FAIL)"; ok=0; fi
    if grep -q "RUPlace Innovus proxy: falling back" "$dlog"; then
      grep "RUPlace Innovus proxy" "$dlog" | grep -E "failed|falling back" | sed 's/^/[guard]   /'
      echo "[guard] proxy fallback to GPUGR/cache: DETECTED (FAIL -- this row is not a proxy row)"; ok=0
    else
      echo "[guard] no proxy fallback: PASS"
    fi
  fi
  (( ok == 1 ))
}
maybe_guard(){  # $1 = runid, $2 = config ; one-shot per phase, on the first run that produced metrics
  # A driver timeout or a hard crash leaves no raw_metrics.csv. Guarding on such a run would fail
  # the "status ok" check and write .abort, killing the rest of the phase over an infrastructure
  # timeout rather than a lever defect. Skip it WITHOUT consuming the one-shot marker so the guard
  # lands on the next run that actually produced metrics.
  if [[ ! -f "results/ruplace_quality/$1/raw_metrics.csv" ]]; then
    echo "[$(date +%T)] guard skipped for $1 (no raw_metrics.csv -- timeout/crash); guard still pending"
    return 0
  fi
  ( flock 9
    [[ -f "$QUEUE/.guard_done" ]] && exit 0
    : > "$QUEUE/.guard_done"
    if guard_check "$1" "$2" 2>&1 | tee "results/ruplace_quality/logs/v126${PHASE}_guard.log"; then
      echo "[$(date +%T)] GUARD PASS on $1"
    else
      echo "[$(date +%T)] GUARD FAIL on $1 -- aborting further placements" | tee -a "results/ruplace_quality/logs/v126${PHASE}_guard.log"
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
    runid="s14_${CASE}_v126_${cfg}_s${seed}"
    run_cmd "$runid" --designs "$CASE" --methods ruplace --random-seed "$seed" \
      "${ruplace_t10[@]}" "${s14_gr[@]}" "${v126_base[@]}" "${cfg_flags[@]}"
    maybe_guard "$runid" "$cfg"
    [[ "$cfg" == P_* ]] && cleanup_proxy_artifacts "$runid"
    if [[ "$SCORE_INLINE" == "1" ]]; then
      # Phase B: score here so this process is the only Innovus user at any instant.
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

# --- build the work list: information-first order (see header) -----------------------------------
: > "$WORKLIST"
for cfg in $CONFIGS; do for seed in $SEEDS; do echo "${cfg}:${seed}" >> "$WORKLIST"; done; done
rm -f "$QUEUE"/.worker*_done "$QUEUE/.abort" "$QUEUE/.guard_done"
echo "[$(date +%T)] v126 phase ${PHASE} start: $(wc -l < "$WORKLIST") items, ${NUM_WORKERS} workers, \
score_jobs=${MAX_SCORE_JOBS}, inline_score=${SCORE_INLINE}, case=${CASE}, seeds=[${SEEDS}]"
df -h /mnt/nvme0n1 | tail -1
cat "$WORKLIST"
pids=()
for ((i=1;i<=NUM_WORKERS;i++)); do worker "$i" & pids+=("$!"); done
( drain ) & dp=$!
for p in "${pids[@]}"; do wait "$p" || true; done
wait "$dp" || true
echo "[$(date +%T)] ---- ${CASE} v126 phase ${PHASE} ----"
grep -E "^run_id|_v126_" "results/s14_innovus/${CASE}.csv" || true
[[ -f "$QUEUE/.abort" ]] && echo "[$(date +%T)] NOTE: phase ${PHASE} was ABORTED by the guard; see results/ruplace_quality/logs/v126${PHASE}_guard.log"
echo "[$(date +%T)] V126_${PHASE}_DONE"
