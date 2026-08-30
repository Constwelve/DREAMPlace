#!/usr/bin/env bash
# v111 (local, yifan405): A0 calibration harness -- bundled GPUGR global route vs Innovus EGR.
#   Runs tools/ruplace_gr_calibrate.py on one DEF: Innovus earlyGlobalRoute with
#   `dumpCongestArea -all`, then GPUGR on the SAME gcell grid, then agreement metrics.
#   This measures the proxy, it does not place anything.
# Env: CASE, DEF, TAG, OUT_ROOT, RRR_ITERS, GPU. Extra args are passed to the harness.
set -eo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate placement
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
GPUGR_BUNDLE="$PWD/install/dreamplace/ops/gpugr/xplace_gpugr"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib:$GPUGR_BUNDLE/cpp_to_py/cpybin:$PWD/build:${LD_LIBRARY_PATH:-}"
unset CDS_LIC_FILE LM_LICENSE_FILE

REPO=/mnt/nvme0n1/yifan/projs/DREAMPlace
CASE="${CASE:-nvdla_s_s14}"
DEF="${DEF:-$REPO/data/s14/results/nvdla_s_gp_baseline/NV_nvdla_s.fixedmacro/NV_nvdla_s.fixedmacro.gp.def}"
TAG="${TAG:-prefix_baseline}"
OUT_ROOT="${OUT_ROOT:-$PWD/results/gr_calib}"
RRR_ITERS="${RRR_ITERS:-1}"
GPU="${GPU:-0}"

mkdir -p "$OUT_ROOT/logs"
LOG="$OUT_ROOT/logs/${TAG}.log"
echo "[$(date +%T)] v111 start CASE=$CASE TAG=$TAG DEF=$DEF" | tee "$LOG"
CUDA_VISIBLE_DEVICES="$GPU" timeout 5400 python3 tools/ruplace_gr_calibrate.py \
  --case "$CASE" --def "$DEF" --tag "$TAG" --rrr-iters "$RRR_ITERS" --gpu 0 \
  --out-root "$OUT_ROOT" "$@" >>"$LOG" 2>&1 && rc=0 || rc=$?
[[ "$rc" == 0 ]] || echo "[$(date +%T)] WARN harness failed or timed out (rc=$rc)" | tee -a "$LOG"
echo "[$(date +%T)] V111_DONE ${TAG}" | tee -a "$LOG"
