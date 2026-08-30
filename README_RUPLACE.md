# RUPlace: Routability-Driven Global Placement

**What it is.** RUPlace makes DREAMPlace's global placement routability-aware. A bundled GPU
global router (`thirdparty/XplaceGPUGR`, a patched Xplace GPUGR fork built when
`RUPLACE_ENABLE_GPUGR=ON`, the default) routes the current placement every few iterations. Its
per-gcell utilization map, calibrated against Cadence Innovus early global route, drives two
mechanisms: **threshold inflation** (cells in bins above a utilization threshold are grown, so
density spreading moves them out of routing-scarce regions) and an **ADMM routing gradient**.

**How to use it.** Set `routability_opt_flag: 1` and `ruplace_flag: 1`; everything else
defaults to the calibrated *congestion* preset (see "Run RUPlace"). For a smaller wirelength
cost use the *balanced* overrides. Three keys are technology-dependent and listed below.

**What to expect.** On SMIC14 designs judged by Innovus global route, the congestion preset
gives roughly -40% H / -35% V routing overflow on a 270k-cell design and -20% / -23% on a
735k-cell design, for about +2% routed wirelength versus plain DREAMPlace; the balanced preset
about half the congestion gain for about +1.5% wirelength. Runs are 3-5x slower than plain
global placement because of the in-loop routing.

## Build

```bash
conda activate placement          # CUDA-enabled PyTorch lives here
git submodule update --init       # Limbo, OpenTimer, cub, munkres-cpp, pybind11
mkdir -p build && cd build
cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=/usr/bin/gcc-9 \
  -DCMAKE_CXX_COMPILER=/usr/bin/g++-9 \
  -DCUDA_TOOLKIT_ROOT_DIR=/usr/local/cuda-11.8 \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda-11.8/bin/nvcc \
  -DCMAKE_CUDA_ARCHITECTURES=7.5 \
  -DCMAKE_CXX_ABI=0 \
  -DCMAKE_PREFIX_PATH="$CONDA_PREFIX" \
  -DPython_EXECUTABLE="$CONDA_PREFIX/bin/python" \
  -DRUPLACE_ENABLE_GPUGR=ON \
  -DCMAKE_INSTALL_PREFIX=../install
make -j16 && make install
```

`CMAKE_CXX_ABI=0` must match the `_GLIBCXX_USE_CXX11_ABI` of the PyTorch in the
environment, and `CMAKE_CUDA_ARCHITECTURES` the GPU (7.5 = TITAN RTX). The
bundled router installs into `install/dreamplace/ops/gpugr/xplace_gpugr`, so
normal runs need no external Xplace checkout.

`thirdparty/XplaceGPUGR` is vendored in-tree, not a submodule; `thirdparty/InstantGR`
is optional and can stay uninitialised.

## Run RUPlace

Enable RUPlace with two switches. Everything else is a default:

```json
{
  "lef_input": ["tech.lef", "stdcells.lef"],
  "def_input": "design.def",
  "routability_opt_flag": 1,
  "ruplace_flag": 1
}
```

```bash
cd install
python dreamplace/Placer.py ../test/ruplace/s14_congestion_example.json
```

`dreamplace/params.json` ships the s14-calibrated **congestion preset** as the
default for every `ruplace_*` key, so no tuning flag is needed. When
`ruplace_flag` is set, `dreamplace/Params.py` additionally fills in the
non-RUPlace DREAMPlace keys the same calibration assumes - `target_density 1.0`,
`gamma 0.92`, `gp_noise_ratio 0.03`, `stop_overflow 0.10`, `legalize_flag 1`,
`num_bins_x/y 512`, and one 1000-iteration `nesterov` `global_place_stages`
entry. Keys you set yourself always win, every applied override is logged at
INFO ("RUPlace preset 'congestion': target_density 0.8 -> 1.0"), and
`"ruplace_preset": "none"` turns the step off. Nothing runs when `ruplace_flag`
is 0, so plain DREAMPlace behaviour is unchanged.

`test/ruplace/s14_congestion_example.json` is a ready-made template.

**Balanced alternative.** The default preset buys routability at some
wirelength. For a point closer to the baseline, override two keys:

```json
{
  "ruplace_inflate_util_threshold": 0.8,
  "ruplace_global_inflate_gamma": 0.25
}
```

**Technology-dependent keys.** Three preset values are calibrated to SMIC14 and
must be retuned on another technology:

| Key | s14 default | Why |
| --- | --- | --- |
| `ruplace_gr_grid` | `step:2880` | 2880 dbu = 5 SMIC14 row heights per GR gcell |
| `ruplace_gr_m1_routable` | `0` | M1 is not a routing layer on SMIC14 |
| `ruplace_gr_max_route_len_per_pin` | `256` | suits that coarse gcell grid; 130 is the ISPD18 calibration |

`test/ruplace/ispd18_test1_gpugr.json` pins the ISPD18 values explicitly and is
the reference for a non-s14 technology.

The legacy external Xplace backend remains available for reproducibility:

```json
{
  "ruplace_router_backend": "xplace",
  "ruplace_xplace_root": "../Xplace"
}
```

## Reproducing the published s14 result

From a fresh clone, with the s14 case staged under `data/s14/` (see
`tools/ruplace_s14_prep.py`):

```bash
git clone -b feat/ruplace <repo> repro_clone
cd repro_clone
git submodule update --init
# then the Build section's cmake + make -j16 + make install

cat > test/ruplace/nvdla_s_repro.json <<'JSON'
{
  "lef_input": ["<pdk>.lef", "data/s14/s14_extra_sites.lef", "<stdcells>.lef", "<macros>.lef"],
  "def_input": "<...>/NV_nvdla_s.fixedmacro.def",
  "result_dir": "results/nvdla_s_repro",
  "gpu": 1,
  "num_threads": 16,
  "random_seed": 1001,
  "routability_opt_flag": 1,
  "ruplace_flag": 1
}
JSON

# environment: no external Xplace dir on LD_LIBRARY_PATH (it shadows the bundled
# libxplace_common.so and segfaults the in-loop router), and no CDS/LM license vars.
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib"
unset CDS_LIC_FILE LM_LICENSE_FILE
cd install && python dreamplace/Placer.py ../test/ruplace/nvdla_s_repro.json
```

The log must show the `RUPlace preset 'congestion': ...` lines, ~15-18 in-loop
router calls (`RUPlace GR: call N, ...`) and a legalization step.

Innovus EGR (`global`) reference for `nvdla_s_s14`, seed 1001, the published
v115 `thr06_g070` run:

| metric | reference |
| --- | --- |
| wirelength | 4,602,377 |
| horizontal overflow | 25,844 |
| vertical overflow | 12,660 |

Reproduction is **within seed noise, not bit-exact**. `deterministic_flag` is 0
in the published runs, so even a same-seed GPU rerun differs by roughly 1%, and
the published numbers come from seeds 1001/1002; expect agreement within about
1-3% per metric. `random_seed` is deliberately not part of the preset.

## Standalone GPUGR

The router can be called without enabling RUPlace:

```bash
python -m dreamplace.ops.gpugr.run_gpugr \
  --backend gpugr \
  --design-name ispd18_test1 \
  --lef-input ../Xplace/data/ispd18_test1.input.lef \
  --def-input ../Xplace/data/ispd18_test1.input.def \
  --output /tmp/ispd18_test1.gpugr.pt
```

For development without `make install`, set `DREAMPLACE_GPUGR_ROOT` or
`ruplace_gpugr_root` to a built GPUGR root containing `cpp_to_py/cpybin`.
