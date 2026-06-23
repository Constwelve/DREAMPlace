#!/usr/bin/env bash
set -euo pipefail

ROOT=${1:-thirdparty/InstantGR}
ARCH=${CUDA_ARCH:-sm_80}

if [[ ! -d "$ROOT/src" ]]; then
  echo "InstantGR source not found at $ROOT" >&2
  echo "Initialize submodules first: git submodule update --init thirdparty/InstantGR" >&2
  exit 1
fi

mkdir -p "$ROOT/run"
(
  cd "$ROOT/src"
  nvcc main.cpp -o ../run/InstantGR -std=c++17 -x cu -O3 -arch="$ARCH"
)
(
  cd "$ROOT/run"
  g++ -o evaluator evaluator.cpp -O3 -std=c++17
)

echo "Built $ROOT/run/InstantGR and $ROOT/run/evaluator with CUDA_ARCH=$ARCH"
