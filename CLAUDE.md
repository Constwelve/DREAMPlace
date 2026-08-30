# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DREAMPlace is a deep-learning-toolkit-enabled VLSI placement tool. It casts nonlinear global
placement as a PyTorch training problem: cell coordinates are the trainable parameters, and a
weighted objective (wirelength + electrostatic density + optional timing) is minimized with a
Nesterov optimizer on CPU or GPU. It also includes ABCDPlace (GPU detailed placement) and a
timing-driven mode. This checkout is DREAMPlace 4.x with HeteroSTA timing (4.3) plus in-progress
research work.

**This is a research checkout, not a clean upstream clone.** The owner's active line is **RUPlace**,
a routability-driven global placement effort layered on DREAMPlace: congestion feedback from a
bundled GPU global router, cell inflation, and route-aware gradient terms. Most of that work lives
on other branches — see *Branches and worktrees* below before assuming a file is missing.

## Scope constraint (do not violate)

**All work for the current effort stays inside `/mnt/nvme0n1/yifan/projs/DREAMPlace`** - sources,
configs, staging, benchmark copies, Innovus run directories, and results. Do not write into
`/mnt/nvme0n1/yifan/projs/TaiWei-Pin-3D`, `~/data`, `~/proj`, or any other tree, even when an
existing default points there. Two known defaults do point outside and must be overridden:

- The `routability_eval` Innovus adapter stages into `cadence_mounted_root =
  /mnt/nvme0n1/yifan/projs/TaiWei-Pin-3D` by default - override it to a path under this repo.
- The Cadence launcher at `~/.codex/skills/cadence-local/cadence` mounts TaiWei-Pin-3D rw and does
  **not** mount this repo, so a container `--workdir` under DREAMPlace does not exist and every run
  fails. Use `tools/cadence_local.sh` instead - a copy of that launcher with the TaiWei-Pin-3D
  mounts replaced by `/mnt/nvme0n1/yifan/projs/DREAMPlace:rw`. Verified: Innovus 22.10 launches,
  checks out `Innovus_Impl_System`, and writes into the repo.

Reading from outside is fine: `~/data/benchmarks/` is an input source (the container mounts it `ro`),
and the Cadence installs under `/mnt/nvme0n1/yifan/projs/EDASoftware` are read-only tool trees.

## Current objective

Improve RUPlace on two metrics - **routed wirelength** and **directional congestion overflow (H/V)** -
and qualify the result with **Cadence Innovus as the final (golden) evaluator** rather than the Xplace
GGR estimate used in `reports/ruplace_results/`. GGR and RUDY stay as in-loop feedback and cheap
screens; Innovus decides. See *Innovus evaluation* below for what currently runs and what does not.

## Build

Building compiles a large tree of C++/CUDA PyTorch extensions and installs a runnable copy into
`install/`. **You must build and install before running** — `dreamplace/Placer.py` is executed from
the install directory, not the source tree.

- **Local dev build** (this machine: TITAN RTX `sm_75`, CUDA 11.8, gcc-9, conda env `placement`):
  ```
  ./build.sh              # configure + make -j + make install into ./install
  ./build.sh --clean      # wipe ./build first
  ./build.sh --no-install # compile only
  ```
  `build.sh` hardcodes the local toolchain (`/home/yifan/miniconda3/envs/placement`,
  `/usr/local/cuda-11.8`, `gcc-9`/`g++-9`, `CMAKE_CUDA_ARCHITECTURES=7.5`, `CMAKE_CXX_ABI=0`).
  It skips `cmake` configure when `build/CMakeCache.txt` already exists — use `--clean` after
  changing any CMake option.
- **Manual / other machines** — see `README.md`. Key CMake options: `CMAKE_CUDA_ARCHITECTURES`
  (or `CMAKE_CUDA_FLAGS`), `CMAKE_CXX_ABI` (must match the PyTorch `_GLIBCXX_USE_CXX11_ABI`, default 0),
  `CMAKE_INSTALL_PREFIX`, `Python_EXECUTABLE`. `build-wuxi.sh` is the config for the "wuxi" cluster
  (gcc-9.4.0, `sm_80`, `ENABLE_PYTHON_TARGET=OFF`).
- On the RUPlace branches the bundled GPU router is built too: `-DRUPLACE_ENABLE_GPUGR=ON` (default)
  with `-DRUPLACE_GPUGR_CUDA_ARCHITECTURES="75;86"`, installing into
  `install/dreamplace/ops/gpugr/xplace_gpugr` (see `README_RUPLACE.md` on those branches).
- CMake requires C++17, but CUDA host code is forced to a lower standard in places — the top-level
  `CMakeLists.txt` strips stray `-std=c++NN` flags to work around this. Boost (>=1.55) and Bison
  (>=3.3) must be installed on the host; other third-party deps build from submodules.

Submodules are required (`thirdparty/`: Limbo, cub, pybind11, OpenTimer, munkres-cpp, plus vendored
Flute, HeteroSTA, NCTUgr, InstantGR, XplaceGPUGR). If missing: `git submodule update --init --recursive`.

## Run

```
cd install
python dreamplace/Placer.py test/ispd2005/adaptec1.json
```

Everything is driven by a JSON config (see `dreamplace/params.json` for all keys and defaults, or
`python dreamplace/Placer.py --help`). Inputs are either Bookshelf (`aux_input`) or LEF/DEF
(`lef_input`/`def_input`/`verilog_input`). Benchmarks are fetched separately:
`python benchmarks/ispd2005_2015.py`. Example configs live under `test/<benchmark>/`.

Notable flags (JSON keys): `gpu`, `global_place_flag`/`legalize_flag`/`detailed_place_flag`,
`timing_opt_flag` + `timer_engine` (`"heterosta"` or `"opentimer"`), `use_bb` + `macro_place_flag`
(2-stage macro flow, ICCAD2023), `gift_init_flag` (GiFt init, ICCAD2024), `deterministic_flag`,
`dtype` (`float32`/`float64`). On the RUPlace branches also `routability_opt_flag`, `ruplace_flag`,
and `ruplace_router_backend` (`"gpugr"` bundled, or `"xplace"` + `ruplace_xplace_root` for the
legacy external backend).

## Tests

Upstream tests are per-operator PyTorch unit tests, run from the **install** directory:

```
cd install
python unittest/ops/hpwl_unittest.py             # a single op's tests
python unittest/unittests.py                     # discover + run all *_unittest.py under unittest/ops
```

The research branches add plain-Python test scripts under `unittest/` that run from the **source**
tree and do not need a build — `python unittest/routability_<x>_test.py`,
`python unittest/ruplace_quality_test.py`, `python unittest/ruplace_unit_test.py`. These are the
fast gate for tooling changes; the op unit tests are the gate for kernel changes.

There is no lint step configured in-repo.

## Architecture

### Python flow (`dreamplace/`)
`Placer.py` is the entry point. The pipeline is: `Params` (load JSON) -> `PlaceDB` (C++-backed
placement database, populated via the `place_io` op) -> optional `Timer` -> `NonLinearPlace`.

- **`BasicPlace.py`** — base class (`nn.Module`). Owns two central wrappers:
  `PlaceDataCollection` (all device tensors: positions, pin offsets, net/pin maps, bins) and
  `PlaceOpCollection` (all the callable operators). Builds move-boundary, wirelength, legalization,
  detailed-placement, and timing ops from the DB.
- **`PlaceObj.py`** — the optimization objective (`nn.Module`). Combines wirelength, density
  (electrostatic), and timing terms with the density-weight / gamma schedules and preconditioning.
- **`NonLinearPlace.py`** — derives from `BasicPlace`; runs the multi-level Nesterov optimization
  loop with the nested `Lgamma`/`Llambda`/`Lsub` stopping criteria, plateau/divergence detection,
  and entropy injection to escape saddle points.
- **`NesterovAcceleratedGradientOptimizer.py`** — custom optimizer used by the loop.
- **`EvalMetrics.py`** — per-iteration metric bookkeeping (HPWL, overflow, etc.).
- **`Timer.py`** — thin Python wrapper over OpenTimer or HeteroSTA raw timers (lazy-imported by engine).
- **`RUPlace.py`** (research branches only) — the RUPlace controller invoked from the placement loop.

### Operators (`dreamplace/ops/<op>/`)
This is where nearly all the compute lives. Each op is a self-contained PyTorch C++/CUDA extension
with a consistent layout:
- `CMakeLists.txt` — declares the extension(s) via the `add_pytorch_extension` helper
  (from `cmake/TorchExtension.cmake`). Typical targets: `<op>_cpp`, `<op>_cpp_atomic`, and
  `<op>_cuda` (guarded by `TORCH_ENABLE_CUDA`), installed into `dreamplace/ops/<op>/`.
- `src/` — the C++/CUDA kernels.
- `<op>.py` / `__init__.py` — the `autograd.Function` / `nn.Module` wrapper that imports the compiled
  `.so` and picks CPU vs. GPU vs. atomic variant. **CUDA availability is checked at import time via
  `dreamplace.configure.compile_configurations["CUDA_FOUND"]`** — `configure.py` is generated at build
  time from `dreamplace/configure.py.in` and records the compile-time config (CUDA/Cairo found, ABI,
  flags). Follow this same pattern (CMakeLists + src + guarded import) when adding a new operator.

Op families: wirelength (`weighted_average_wirelength`, `logsumexp_wirelength`, `hpwl`, `rmst_wl`),
density (`electric_potential`, `density_map`, `density_overflow`, `density_potential`, `dct`),
legalization (`greedy_legalize`, `abacus_legalize`, `macro_legalize`, `legality_check`),
detailed placement / ABCDPlace (`independent_set_matching`, `global_swap`, `k_reorder`),
routability (`rudy`, `pinrudy`, `pin_utilization`, `routability_opt`, `nctugr_binary`, `gpugr`),
I/O and infra (`place_io`, `move_boundary`, `pin_pos`, `utility`, `draw_place`), timing
(`timing`, `timing_heterosta`), and research adds (`gift_init`, `fence_region`, `adjust_node_area`).

## Branches and worktrees

The checkout root is **not** where the RUPlace source lives. Check `git branch` and `git worktree
list` before concluding a file is missing — an empty `dreamplace/ops/routability_opt/` holding only
`__pycache__` means you are on a branch without that code, not that the code was deleted.

- `feature/auto-macro-place-bb` — the branch checked out at the repo root. Upstream 4.x plus the
  auto macro-placement/BB work. Used day-to-day for **results reporting**, not RUPlace development.
- `feat/routability-lab` — checked out at `.worktrees/ruplace-routability/`. The active routability
  lab: plugins, proxies, evaluators, campaign tooling, docs.
- `feat/ruplace` - the RUPlace line proper (`dreamplace/RUPlace.py`, `tools/ruplace_*`). It is the
  **merge-base ancestor** of `feat/routability-lab` (merge-base `14bfd0d` = its own tip), so the lab
  branch is a strict superset: same RUPlace core, plus the plugins and the `routability_eval` package.
  `feat/ruplace` has no `routability_eval` at all, so it cannot reach Innovus - work on
  `feat/routability-lab` unless you specifically need the pre-lab state.
- `ruplace` - **not** the RUPlace branch despite the name: April 2026 upstream, zero RUPlace files.
- `master` / `remotes/origin/*` — upstream limbo018/DREAMPlace. `remotes/constwelve/*` is the owner's
  fork used to move branches between machines.

Each worktree has its own `build/`, `install/`, `results/`, and `configs/`. A build in one does not
serve the other.

## Where RUPlace can actually run (checked 2026-08-28)

- **`cecaTitan01`** (hostname `gastly`, 2x RTX A6000, reachable by `ssh cecaTitan01` from yifan405):
  full working RUPlace at `/home/yifanchen/proj/DREAMPlace` with `../Xplace` and the `placement` env.
  This is where every archived ISPD18 result was produced and where `run_remote_map_reproduction.sh`
  runs. test8 takes ~866 s and test10 ~733 s per RUPlace run there. Reproduction on 2026-08-28
  matched the archived scalars (test8 rWL 66,345,299 / test10 59,723,840).
- **yifan405, repo root** (`feature/auto-macro-place-bb`): cannot run RUPlace - no `RUPlace.py` in
  source or `install/`.
- **yifan405, `.worktrees/ruplace-routability`** (`feat/routability-lab`): *can* run RUPlace once
  `install/` is refreshed. Everything it needs is already present: bundled GPUGR is built
  (`install/dreamplace/ops/gpugr/xplace_gpugr/cpp_to_py/cpybin/gpugr*.so`), the sibling
  `/mnt/nvme0n1/yifan/projs/Xplace` has a built `build/` and the ISPD18 inputs under `data/`, and the
  `placement` env is the same. The only defect is the stale Python install (missing plugin module) -
  a `make install` in `.worktrees/ruplace-routability/build` fixes it; no CMake reconfigure needed
  unless C++/CUDA changed. Note: an outside summary claiming "the local machine has `feat/ruplace` but
  needs a separate worktree and full rebuild" missed this existing worktree.

Innovus exists **only on yifan405**, so the s14/Innovus work has to run here regardless; cecaTitan01
is the faster place for ISPD18 GGR sweeps if the single TITAN RTX becomes the bottleneck.

## RUPlace research line

### Where things live (on `feat/routability-lab`)
- `dreamplace/ops/routability_opt/` — `pipeline.py` (controller), `plugin_base.py`, `proxy.py`,
  `ruplace_op.py`, and `plugins/` (`local_gradient`, `net_weighting`, `net_overlap`, `whitespace`,
  `pin_porosity`, `poisson_force`, `routeforce`, ...). The lab's core design is a separation of
  three concerns: **optimization plugins** change a placement, **congestion proxies** supply
  in-loop feedback, and **evaluators** score finished DEFs independently.
- `dreamplace/ops/routability_eval/` — `rudy`, `xplace`, `openroad`, `innovus` evaluator backends.
- `dreamplace/ops/gpugr/` — the bundled Xplace-derived GPU global router (`thirdparty/XplaceGPUGR`).
- `configs/routability_plugins/presets.json` — frozen plugin presets; `configs/routability_*_pilot_v*.json`
  are the individual pilot sweeps (one JSON per parameter study, numbered `v1`..`v108`).
- `tools/routability_*.py` — ~45 campaign/audit/selection/reporting drivers, each paired with a
  `unittest/routability_*_test.py`.
- `tools/ruplace_*.py` — the quality-campaign layer: `ruplace_quality.py` (main driver: builds
  comparable ISPD18 LEF/DEF configs, runs DREAMPlace variants, scores GP DEFs with Xplace GGR, runs
  an Xplace inflation baseline, writes CSV/Markdown + a quality-gate verdict), plus
  `ruplace_composite.py`, `ruplace_auto_composite.py`, `ruplace_collect_best.py`,
  `ruplace_paper_summary.py`, `ruplace_validate_targets.py`, `ruplace_gather_benchmarks.py`.
- `docs/routability_optimization_lab.md` — the lab's design doc and literature-to-plugin matrix,
  including an explicit fidelity column (mechanism implementation vs. reproduction). Read this
  before adding a plugin or making a claim about what a plugin reproduces.
  `docs/routability_validation_*.md` hold the validation status/finals.

### At the repo root (`feature/auto-macro-place-bb`)
- `reports/ruplace_results/` — the write-up of the `paper_full_congestion_hv_v1` campaign:
  `RUPLACE_RESULTS_REPORT.md`, `data/` (raw metrics, comparison summaries, gate JSON, ablation,
  GGR maps), `figures/`, and `run_remote_map_reproduction.sh` (re-runs the two map cases on a
  remote host with the tuned per-design parameters).
- `tools/ruplace_export_ggr_maps.py`, `ruplace_plot_ggr_maps.py`, `ruplace_plot_results_summary.py` —
  the figure/map generators for that report.
- `configs/ruplace_taiwei_2d_netlists/` — private netlists for the TaiWei-2D study.

## Experiment conventions

- **Run scripts.** `run_ruplace_v<N>.sh`, `run_ruplace_v<N>_local.sh`, `run_ruplace_v<N>_remote.sh`
  — one per sweep, numbered monotonically and never edited after a sweep completes. `_local` runs on
  this box, `_remote` targets a GPU host. The root tree is at v77; the routability-lab worktree is at
  v108. **Always create a new `v<N+1>` script rather than mutating an existing one** — old scripts are
  the record of how archived results were produced. They are untracked by design; don't commit them.
- **Environment.** Every script does `source ~/miniconda3/etc/profile.d/conda.sh && conda activate
  placement`, then exports `CUDA_HOME=$CONDA_PREFIX` and prepends the Xplace build dirs
  (`../Xplace/cpp_to_py/cpybin`, `../Xplace/build`) to `LD_LIBRARY_PATH`. Copy that preamble verbatim
  into new scripts.
- **Results.** On the run host, `results/ruplace_quality/<run_id>/raw_metrics.csv` is the unit of work;
  driver logs go to `results/ruplace_quality/logs/<run_id>.driver.log`. That tree lives on whichever
  GPU host executed the sweep (and is what gets rsynced back) — it is not present in this checkout;
  locally you will only find `results/routability_lab/` and `results/routability_completion/` in the
  routability-lab worktree. Runs are **resumable by skipping**: a run
  whose `raw_metrics.csv` already exists is skipped, so re-running a sweep only fills gaps. Delete the
  run directory to force a redo. `results/` is untracked and machine-local; the curated subset is what
  gets promoted into `reports/`.
- **Benchmarks** come from a sibling Xplace checkout (`../Xplace/data/ispd18_*.input.{lef,def}`),
  not from `benchmarks/`.
- **Remote sweeps.** `sync_launch_ruplace_v77.sh <host> <remote_dir>` is the pattern: rsync only the
  touched Python files + `tools/` + tests + run scripts, run a preflight on the remote
  (`py_compile` + the plain-Python unit tests + an artifact-existence check), `nohup` the sweep, then
  print the tail/sync-back commands. Note it rsyncs the changed `dreamplace/*.py` into **both** the
  remote source tree and its `install/dreamplace/` — pure-Python changes therefore need no remote
  rebuild, but any C++/CUDA change does.
  **Run it from the `feat/routability-lab` worktree, not the repo root.** It rsyncs
  `dreamplace/RUPlace.py` and `unittest/ruplace_*.py`, which do not exist on the root branch, so under
  `set -eo pipefail` the first rsync fails and the sweep never launches.
- **The TITAN RTX is shared.** Other projects' jobs (e.g. `heteroplace3d`) run on it unannounced; check
  `nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv` before launching, and
  size runs assuming ~16 GB rather than the full 24 GB.
- **Innovus EGR evaluations may run in parallel** (user, 2026-08-29): the licence allows it (8 CPU jobs per
  seat; other projects' Innovus jobs coexist). From v115 on, campaign scripts decouple scoring from placement:
  placements run as 2 concurrent GPU workers (the v77 `worker0/worker1` pattern; ~5 GB each on the shared
  TITAN RTX), and a scoring queue runs up to 3 Innovus EGRs concurrently. Per-call router timings from such
  runs are not comparable to quiet-GPU numbers - never use them for the harness runtime gate.
- **Do not babysit long runs.** Launch detached (`nohup`/`tmux`), then report from status CSV/JSON and
  log tails (`tail`, `rg`) — never poll in a sleep loop, never dump whole logs. If a run is still
  active, report once (completed/total, active case, latest artifact, blocker) and stop.

## Assessment of the current RUPlace result (2026-08-28)

`reports/ruplace_results/RUPLACE_RESULTS_REPORT.md` headlines -6.1% mean routed WL and 9/10 design
wins over `dp_hpwl`. Read on its own that looks finished. Three things in the same campaign say it is
not yet good enough for the stated goal (routed WL *and* H/V overflow), ranked by how much they matter:

**1. The comparison that matters is against `xplace_inflate`, and it is not currently winning.**
`dp_hpwl` is stock analytical placement with no routability mechanism - a weak reference. The campaign
already contains a routability-driven competitor. RUPlace/Xplace routed-WL ratio by design
(>1 = RUPlace worse): test1 1.069, test2 1.088, test3 1.066, test4 1.020, test5 1.038, test6 0.988,
test7 0.991, test8 1.207, test9 1.254, test10 1.150 - mean 1.087, median 1.067, RUPlace ahead on
2/10, and furthest behind on exactly the three congested designs.

**Caveat, and the first thing to fix:** the two sides are not measured the same way.
`tools/ruplace_quality.py` routes every DREAMPlace-family DEF through the shared evaluator
(`metric_source=xplace_ggr`, pinned `--_eval-route-rrr-iters` / `--_eval-num-bins`), but takes
`xplace_inflate` numbers from Xplace's own run log (`metric_source=xplace_log`) and retains no
`placed_def` for it, so the result cannot be re-scored. The report's protocol section - "Each placer
produced a global-placement DEF. The same Xplace GGR evaluator then routed every DEF" - does not hold
for `xplace_inflate`. Export a DEF from the Xplace baseline and route it through the same evaluator
before treating the 8.7% gap as real; it is currently a cross-source signal, not a measurement.

The honest counterweight: against the same Xplace baseline RUPlace has ~2x fewer overflowing nets
(mean ratio 0.468), ~2x fewer estimated shorts (0.495), and 0.94x the placement HPWL. The position is
Pareto-ambiguous, not dominated - but it is not ahead on the metric the current goal names first.

**2. The ablation says the novel machinery contributes almost nothing.** Means over test8/9/10
relative to `no_route`: inflation only -0.032% rWL / **+0.333%** overflow nets; ADMM only -1.122% /
-6.031%; full RUPlace -1.109% / -6.183%. Xplace's `routeforce.admm_route_grad` accounts for
essentially the entire effect; the clustered/directional inflation stack adds ~0.15% overflow-net
reduction and slightly *worsens* routed WL. Before more parameter tuning, establish whether any
inflation component earns its place - that is an ablation on existing infrastructure, not a sweep.

**3. Congestion is not improved where congestion exists, and the result is a per-design composite.**
On the only congested designs, RC-H worsens (test8 1.024/1.019, test9 1.041/1.040, test10 1.104/1.081)
and test10 also worsens RC-V (1.054/1.041) and overflowing nets (+29%). The median "wins" come from
easy designs where both placers sit at 0 overflow and RC 1.000. And per
`data/paper_full_congestion_hv_v1_composite_notes.txt`, each design's reported number comes from a
*different* tuned run (`tune_test10_v68_...`, `tune_test8_v73_...`, `tune_test9_opt_...`) - there is no
single parameter set that produces the table.

### What this implies for the next step
Not "tune harder". In order: (a) make the Xplace comparison apples-to-apples; (b) settle the mechanism
question the ablation raises; (c) only then re-qualify under Innovus on s14, where a 48 s EGR per
evaluation makes an honest campaign affordable. The Innovus move is right - the current evidence is
all GGR estimate - but it will not fix a mechanism that the ablation says is carrying ~0.15%.

## Step-1 ISPD18 campaign: stopped, superseded by s14 (2026-08-28 night)

Step 0 is done: the worktree's `install/` was refreshed with a **Python-only** sync (no C++/CUDA
source was newer than the built `.so`s, verified before syncing). `Placer.py` imports, the two
`ruplace_*` unit-test suites pass, and RUPlace runs GGR feedback in-loop on the TITAN RTX.
cecaTitan01 is not required.

`run_ruplace_v109_local.sh` (1a: Xplace re-score, 1b: seed robustness on test8/9/10) was started and
then **killed** after `step1a` test1-6 on the user's direction to move to s14, because ISPD18 has no
Verilog and cannot reach the Innovus evaluator. Two things from the partial run are worth keeping:

- `parse_xplace_exp_dir` was fixed to take `--xplace-root` (it resolved against `REPO_ROOT/../Xplace`,
  which from a worktree is nonexistent). Even so, all six `xplace_inflate` rows still came back
  `metric_source=xplace_log` with `place_hpwl=0` and numbers far from the archive (test2 rWL 2.97M vs
  archived 5.77M; overflow nets 885 vs 157). So the local Xplace either did not write a DEF the driver
  can find, or its inflation flow differs from cecaTitan01's. **The RUPlace-vs-Xplace comparison
  remains unresolved**; the archived Xplace rows are still cross-source numbers.
- A RUPlace smoke on `ispd18_test1` with **driver defaults** (no tuned flags) produced rWL 1,155,326 vs
  `dp_hpwl` 369,287 - 3.1x worse. RUPlace's default parameter set is destructive; every good number in
  the archive comes from per-design tuning. Never run it untuned and read the result as "RUPlace".

## s14 + RUPlace: the in-loop router crashed, root-caused and patched (2026-08-28 night)

RUPlace's in-loop router (Xplace GGR, also the bundled `XplaceGPUGR` fork) **segfaulted** on the s14
`nvdla_s` GP DEF at `GRDatabase::addMovObs -> addCellObs` (gdb). Two independent defects in the fork's
LEF reader `cpp_to_py/common/io/file_lefdef_db.cpp`, both triggered by the SMIC14 libraries:

1. **Null layer on pin shapes.** `scc14nsfp_...rvt_ant.lef` puts PIN PORT geometry on `NW` and `SN`
   (MASTERSLICE) in every cell. `db->getLayer()` returns null for non-routing/cut layers and the only
   guard was `assert(layer)` - compiled out in Release - so `addShape(*layer, ...)` bound a null
   reference that `addCellObs` later dereferenced. Fix: skip geometry after an unknown LAYER item,
   warning once per layer name.
2. **Reversed OBS rectangles.** `SARM2_new.lef` has 90 `RECT` lines with `x1 > x2`
   (`RECT 4.0 0.0 -0.352 42.560`). The fork stores corners unnormalized, so after the FN/FS orientation
   transform the box has a negative span; `markObs` catches that with the `continue, obs: ...` error
   and **silently drops the SRAM's OBS**, i.e. the router saw macros as routable. Fix: normalize
   `min/max` at the OBS and PIN rect call sites.

The fix is `cmake/xplace_gpugr_lef_robustness.patch` (worktree), applied-or-verified by
`CMakeLists.txt` exactly like `xplace_gpugr_negative_span.patch`; the root tree's untouched copy of
the fork was the pristine base for it. The worktree's fork already has it applied. Rebuild only the
affected targets: `make -C build xplace_common gpugr io_parser` then
`make -C build/thirdparty/XplaceGPUGR install` (~20 s). Verified: the rebuilt GPUGR loads the s14 case
with zero `continue, obs` errors and proceeds into maze routing.

### The bundled GPUGR is not usable in-loop on s14 (measured 2026-08-28 22:27-22:35)
With the parser fixed, `run_gpugr --backend gpugr` on the `nvdla_s_s14` baseline GP DEF ran to
completion (`--rrr-iters 1`): **425 s** total, 352 s of it in one "MR Cost calc", and it reported
`num_ovfl_nets 65,459, gr_wirelength 7,358,435, est_shorts 402,465, rc_hor 0.0014, rc_ver 0.0017`,
plus `ERROR: there are 5 nets use too many route segments (MAX_ROUTE_LEN_PER_PIN)`. Innovus EGR on
the *same DEF*: wirelength 4,375,359, 1.50% H / 0.68% V overflow, 48 s. GPUGR's routed WL is 1.68x
Innovus's and its RC values are ~0.001 where 1.0 means "at capacity" - the capacity model is not
producing sane numbers on this tech. Two conclusions, both firm:

1. **Speed:** RUPlace calls the router every `ruplace_admm_route_freq` iterations (50 in the tuned sets)
   over 1000 iterations - ~20 calls x 7 min = hours per run on a 270k-cell design, before any tuning.
2. **Fidelity:** GPUGR's congestion picture on this SMIC14 tech disagrees with Innovus by orders of
   magnitude. Most likely a capacity-model mismatch (9 routing layers incl. `TM2`/`ALPA`, dense PG
   stripes as fixed OBS, LEF58 rules ignored) rather than a real routability difference. The
   RC ~0.001 readings say the normalization itself is off, not just the routing.

Until (2) is understood, an in-loop GPUGR result on s14 would be optimizing against the wrong map.
The driver's *final* GGR scoring (`run_xplace_eval`) uses the **external** Xplace at `--xplace-root`,
whose parser is unpatched, so on s14 it segfaults; rows come back `status=failed` but `placed_def`
is still set and the Innovus scorer uses that. Expect and ignore those failures on s14 runs.

Options from here, in the order I would try them: (a) RUDY as the in-loop proxy (`ruplace_proxy=rudy`
works today; loses the ADMM route-gradient term, which is the part the ISPD18 ablation credits);
(b) an Innovus-EGR in-loop proxy - 48 s per call is affordable at refresh 50-100, aligns the
objective with the judge, needs Innovus to dump a per-gcell congestion map; (c) debug GPUGR's capacity
model on s14 by comparing its H/V demand-capacity maps against Innovus's on the same DEF.

### Phase A/B plan approved 2026-08-29 (see `/Users/yifan/.claude/plans/dazzling-snacking-pearl.md` on the Mac)
Decisions: fix GPUGR on s14 first; acceptance for any RUPlace config = **strict dominance vs `dp_rudy` at the
worst of two seeds** on Innovus WL *and* H *and* V overflow; **no ISPD18 regression runs** (risk accepted).
Detailed implementation is delegated to Opus subagents; analysis/decisions/bookkeeping stay with the lead.

Corrections to earlier notes, from the exploration passes:
- GPUGR's `gr_wirelength` is in **gcell steps**, not dbu: 7,358,435 x 640 dbu = 4.71e6 um vs Innovus 4.375e6
  um -> ratio **1.08**, not 1.68. The probe ran on the DEF GCELLGRID (1126x1171), not 512 bins.
- `rc_hor/rc_ver ~ 0.001` is a metric-definition port bug (in-loop uses a plain mean of clamped overflow;
  Xplace and the eval path use ACE), not a capacity bug.
- Innovus EGR's congestion grid on nvdla_s is **576 x 576 dbu = 1250 x 1300 gcells** (row-height based), not
  the DEF GCELLGRID (640). `dumpCongestArea -all` rows: `(x1, y1) (x2, y2) V: remain/total H: remain/total`
  in dbu, 1,625,000 rows; sample at `data/s14/innovus_egr/nvdla_s_dumpfmt/congest_area_all.txt`. Since
  720000/1250 = 748800/1300 = 576 exactly, GPUGR reproduces that grid with `route_xSize=1250, route_ySize=1300`.
- `dp_hpwl` seed 1001 from v110 (GP-only, **unlegalized** DEF): WL 4,208,411 um, 82,395 H / 31,976 V overflow
  counts - overflow ~2x the legalized stock baseline. Unlegalized GP DEFs inflate Innovus overflow; every method
  in a comparison must use the same protocol, and legalization before EGR should be revisited for realism.

### Innovus reference on `nvdla_s_s14` (v110, GP-only unlegalized DEFs, 2 seeds, 2026-08-29 00:00-00:10)
`results/s14_innovus/nvdla_s_s14.csv`. Seeds agree to <0.3% on WL and <2% on overflow, so two seeds are
enough for this design.

| method | seed | WL (um) | H overflow | V overflow |
|---|---|---:|---:|---:|
| dp_hpwl | 1001 | 4,208,411 | 82,395 | 31,976 |
| dp_hpwl | 1002 | 4,200,042 | 81,860 | 30,914 |
| dp_rudy | 1001 | 4,304,225 | 74,897 | 23,746 |
| dp_rudy | 1002 | 4,299,597 | 73,744 | 23,326 |

**Acceptance bar (dp_rudy worst seed): WL <= 4,304,225 um AND H <= 74,897 AND V <= 23,746**, at the worse of a
config's two seeds. Under Innovus, RUDY inflation costs +2.3% WL for -9% H / -26% V overflow - the trade RUPlace
must beat on all three.

### A0 calibration harness: pre-fix baseline (2026-08-29 01:00, `results/gr_calib/prefix_baseline/`)
`tools/ruplace_gr_calibrate.py` (+ `run_ruplace_v111_gr_calib_local.sh`) routes one DEF with GPUGR on
Innovus's own EGR grid (1250x1300, step 576 dbu, x-origin 72 dbu - GPUGR starts at 0; the 12.5%-gcell offset
moves Spearman by <0.005, ignored) and compares per-gcell maps against `dumpCongestArea -all`. Pre-fix GPUGR on
the nvdla_s baseline DEF, rrr=1:

| | H | V |
|---|---|---|
| Spearman (utilization) | **0.634** (pass >=0.6) | **0.465** (fail) |
| top-2% overflow-gcell IoU | **0.323** (pass >=0.30) | **0.221** (fail) |
| capacity mean, GPUGR / Innovus (tracks/gcell) | 24.2 / 15.5 = **1.56x** | 22.7 / 17.6 = 1.29x |
| overflow gcells, GPUGR / Innovus | 19,748 / 24,430 | 24,344 / 10,944 |
| WL um, GPUGR / Innovus | 4,771,626 / 4,375,359 = **1.091** (pass) | |
| `run_ggr` | **487 s** (fail; 29 s at 128x128) | |

Diagnoses that the fix order now rests on:
- **Via demand is almost all of GPUGR's overflow.** Wire-only overflow is 453 H / 3,521 V tracks vs 55,339 /
  65,199 with vias; Innovus's `remain/total` counts wire tracks. GPUGR charges `sqrt(n)*1.5` tracks per via cell
  (`InCellUsage.cuh`). The via term also carries most of the usable correlation, so it must be re-weighted, not
  dropped. -> new `via_usage_scale` knob, calibrate.
- **GPUGR over-counts capacity 1.3-1.6x.** It counts every LEF track; Innovus's `total` evidently excludes tracks
  blocked by PG stripes/obstructions. GPUGR puts blockage into *demand* (`fixed`) rather than subtracting it from
  capacity, so utilization definitions differ. -> export the `fixed` map and compare `wire/(cap-fixed)`.
- **V is the weak channel, and the mapping is verified correct** (2x2 Spearman: diag 1.099 > off-diag 0.934;
  swapping would worsen). Two known defects act on V specifically: M1 (vertical) is a free, unobstructed
  10-track layer that absorbs vertical wires Innovus would put on M3/M5, and ALPA (vertical) has garbage capacity
  from mixed X/Y tracks. -> `m1_routable=0` and the ALPA direction fix are the first V experiments.
- The two tools even disagree on which direction is worse (Innovus: H; GPUGR: V) - consistent with the above.
- 5,200 pattern-route `failed` lines; 75,165 "overflow nets" includes them.

### Fix batch 1 results (2026-08-29 02:30, `results/gr_calib/nvdla_s_s14.csv`, patch `cmake/xplace_gpugr_s14_fidelity.patch`)
New `load_gr_params` keys, all defaulting to legacy: `max_route_len_per_pin` (130), `m1_routable` (1),
`via_usage_scale` (1.5). New binding `fixed_map()` (per-layer blocked tracks). `RUPLACE_GR_DEBUG_FAILED=N`
prints failed nets. Harness now also reports the `avail` utilization `(wire_dmd - fixed)/(cap - fixed)`.
The patch covers the fork only; `run_gpugr.py`, `xplace_backend.py`, `tools/ruplace_gr_calibrate.py` are
uncommitted worktree edits. `data/s14/fork_snapshot_before_batch1/` is the patch base - keep it.

| tag (all rrr=1, 1250x1300) | Sp H/V (dmd) | Sp H/V (avail) | IoU2% H/V (avail) | ovfl nets | WL ratio | run_ggr |
|---|---|---|---|---:|---:|---:|
| prefix_baseline | .634/.465 | .746/.751 | .305/.237 | 75,165 | 1.091 | 487 s |
| + streams | identical | identical | identical | 75,165 | 1.091 | 291 s |
| + routelen 256, m1_routable 0 | .634/.465 | .745/.751 | .305/.240 | 75,258 | 1.091 | ~250 s |
| + via_usage_scale 0.5 | .536/.349 | .757/.758 | .349/.276 | 19,071 | 1.046 | 312 s |
| + via_usage_scale 0.0 | .470/.291 | **.766/.762** | **.365/.295** | 9,199 | 1.029 | 355 s |

What this settles:
- **The capacity/utilization definition, not the routing, was the V problem.** Against available capacity
  both Spearman gates pass at every setting; capacity-mean ratio to Innovus drops from 1.56/1.29 to 1.20/1.05.
  The in-loop maps must adopt this definition (`ruplace_gr_util_mode=avail`).
- **Via weight is a trade**: lower = better agreement with Innovus's wire-track accounting and sane overflow-net
  counts, worse for the legacy dmd-based maps. Treat 0.0-0.5 as the s14 range; decide after the M1-pin fix.
- **Defect F (ALPA mixed tracks) was wrong**: the tech LEF declares `DIRECTION VERTICAL`; per-layer capacity log
  (M1/M2 9.0, M3 8.2, M4-M7 7.2, TM2 0.8, ALPA 0.13 tracks/gcell) is correct. The direction-inference guard is
  defensive only.
- `m1_routable=0` changes nothing measurable (the maps already exclude layer 0) and does not affect failed nets.
- **All 5,200 `failed` nets have a Steiner node whose pin access-layer range is `[0,0]` (M1-only pin)**;
  pattern routing's sweeps run `for i = 1; i < LAYER` and never touch layer 0, so the node is unreachable
  regardless of capacity. Real routers go M1 pin -> V1 -> M2. Fix: extend M1-only pin access to layer 1.
- Streams: bitwise-identical maps, MR time 394 -> ~200-380 s (GPU contention makes single timings noisy by
  +-40%; compare `MR Cost calc` across runs, not wall clock). At Innovus resolution GPUGR stays at 250-350 s;
  the in-loop grid must be coarser (128x128 ran `run_ggr` in 29 s).
- `max_route_len_per_pin=130` corrupted 11 nets' route lists (reporting), not the demand maps.

### Fix batch 2 results (2026-08-29 04:00) - Phase A fidelity gate MET on `nvdla_s_s14`
- **Failed nets were an integer-overflow bug, not M1 pin access.** The count (5,200) was bit-identical across
  every M1/via setting, so the plan's A6.2 premise was wrong. Real cause: `PatternRoute.cu` truncates
  `int64 costSum` into `int` at 8 sites; `INF = 1e9` per blocked gcell overflows `INT_MAX` on spans crossing
  >= 3 blocked gcells, the wrapped value wins the min and trips `failed`. `MazeRoute.cu` already guards this.
  Fix: saturating `ruplaceWireCost()/ruplaceAdd()` behind key `wire_cost_sat` (default 0). failed 5,200 -> **0**;
  Spearman avail .766/.762 -> .776/.777. Load-bearing at rrr=0 (no maze pass to recover dropped nets).
- `dreamplace/ops/gpugr/gr_metrics.py` is now the single metric implementation (`hv_maps` with
  `util_mode legacy|avail`, `gr_wirelength_um`, ACE `rc_means`, area-weighted `estimate_num_shorts`) used by
  `run_route`, `_external_eval_main`, and `ruplace_quality.eval_def_cli`. Proven identical to the old code on
  ISPD18 test1 (eval JSON diff empty) and on the s14 DEF (full float precision). `unittest/gr_metrics_test.py`: 9 pass.
- New `params.json` keys (defaults = legacy): `ruplace_gr_util_mode` (`legacy`), `ruplace_gr_grid` (`bins` |
  `def` | `NxM`), `ruplace_write_guides` (1), `ruplace_gr_wire_cost_sat` (0). Driver flags
  `--ruplace-gr-util-mode/--ruplace-gr-grid/--ruplace-write-guides/--ruplace-gr-wire-cost-sat`; eval path has
  `--_eval-util-mode/--_eval-gr-grid`. Harness: `--innovus-downsample K` (+`-crop`). Note: run the harness driver
  without a literal `--` separator (it is passed through and breaks argparse).
- **Grid/rrr sweep** (all `m1_routable=0 max_route_len_per_pin=256 via_usage_scale=0 wire_cost_sat=1`, util `avail`,
  quiet GPU; k = Innovus gcells per GPUGR gcell):

| grid | k | rrr | Sp H/V | IoU2% H/V | WL ratio | ovfl nets | run_ggr |
|---|---|---|---|---|---:|---:|---:|
| 1250x1300 | 1 | 1 | .776/.777 | .365/.290 | 1.029 | 9,346 | 176 s |
| 625x650 | 2 | 1 | .817/.864 | .349/.375 | 1.027 | 8,819 | 79 s |
| 625x650 | 2 | 0 | .913/.899 | .274/.496 | 0.958 | 25,417 | 7.9 s |
| **250x260** | **5** | **1** | **.843/.909** | **.332/.499** | **1.034** | **8,780** | **16.9 s** |
| 250x260 | 5 | 0 | .922/.938 | .342/.550 | 0.952 | 17,814 | 4.2 s |

  Every A0 threshold passes at 250x260/rrr=1 (Spearman >= .6, IoU >= .30, WL 0.95-1.15, <= 25 s). Coarsening
  *improves* agreement: Innovus's EGR map is smooth at 576 dbu, so block-summing strips GPUGR's fine-grain noise.
  rrr=0 is better correlated still but underestimates WL by 5% and doubles overflow nets (never relieved) - use it
  only if the signal feeds inflation maps alone. `via_usage_scale=0.5` buys nothing over 0.
- **s14 in-loop GR defaults (decision):** gcell ~2880 dbu (5 row heights; 250x260 on nvdla_s), rrr=1, util `avail`,
  `wire_cost_sat=1`, `m1_routable=0`, `max_route_len_per_pin=256`, `via_usage_scale=0`, guides off. ~17 s/call
  -> ~6 min of routing per 1000-iteration RUPlace run at route_freq 50. Skipped for now (diminishing returns at
  Sp .84/.91): A5.2 top-layer policy, A5.5 obstacle margins, A7 cost sweep - revisit only if Phase B stalls.
- Timing caveat: GPU contention inflates `run_ggr` up to 2x (176 s vs 355 s for identical maps). Compare
  `MR Cost calc` and only on a quiet GPU.

### Batch 3a (2026-08-29 06:00): plumbing done, regression_s14 reference done, first RUPlace run blocked
- In-loop keys added: `ruplace_gr_via_usage_scale` (1.5), `ruplace_gr_m1_routable` (1),
  `ruplace_gr_max_route_len_per_pin` (130); `ruplace_gr_grid` accepts `step:<dbu>` (sizes from `gpdb.dieInfo()`,
  the *die* not the core). `run_route` logs the resolved `load_gr_params` once and times each call.
  Driver flags `--ruplace-gr-via-usage-scale/--ruplace-gr-m1-routable/--ruplace-gr-max-route-len-per-pin`.
  New campaign script `run_ruplace_v112_s14_ref_local.sh` (`CASES`/`METHODS`/`SEEDS`, `s14_gr` flag array).
- Name-mapping fix (not flag-gated, identity on names without backslashes): s14 DEFs escape `/` inside leaf
  names (`...\/U28`); `_norm_name` now unescapes any `\x`. Verified 0 unmapped on both cases.
- **Innovus reference on `regression_s14`** (`results/s14_innovus/regression_s14.csv`, GP-only DEFs):

| method | seed | WL (um) | H overflow | V overflow |
|---|---|---:|---:|---:|
| dp_hpwl | 1001 | 10,088,053 | 589,131 | 330,575 |
| dp_hpwl | 1002 | 10,093,203 | 596,096 | 339,730 |
| dp_rudy | 1001 | 10,084,552 | 587,545 | 333,733 |
| dp_rudy | 1002 | 10,099,038 | 595,203 | 341,738 |

  Seeds agree (<0.2% WL, <3% overflow). **RUDY inflation buys nothing on this design** (WL -0.03%, H -0.3%,
  V +1%), so "dominate dp_rudy at worst seed" is effectively "dominate dp_hpwl" here: WL <= 10,099,038, H <=
  595,203, V <= 341,738. This design is ~4x more congested per area than nvdla_s (589k H overflow tracks).
- Calibration on regression_s14 (`results/gr_calib/reg_k5_rrr1/`, 277x260, k=5 crop): Spearman avail
  **.914/.919** (pass), IoU2% .292/.282 (marginal fail; the die is not a multiple of 2880 so the x grids
  misregister by up to half a gcell, which penalizes IoU directly), **WL ratio 1.165 (fail)**, 0 failed nets,
  run_ggr 113 s (parse 15.7). GPUGR overestimates WL on the heavily congested design; fine for a congestion
  signal, not for WL-based decisions. Harness alignment check is now a pitch-ratio tolerance (0.5%) with a WARN.
- **Blocker: the first in-loop router call segfaults** in `GRDatabase::addMovObs -> addCellObs`, preceded by the
  same inverted-box `continue, obs:` errors that the LEF-parser patch removed - i.e. the in-loop process is
  running the **unpatched** parser. Standalone runs of the identical DEF are clean. See the next entry for the
  cause.

### Cause of the in-loop segfault: LD_LIBRARY_PATH hijacks the bundled parser (2026-08-29 06:30)
`gpugr.cpython-38...so` links `libxplace_common.so` dynamically with `RUNPATH=$ORIGIN`. `DT_RUNPATH` is searched
*after* `LD_LIBRARY_PATH`, and every campaign script exports `$XPLACE_ROOT/cpp_to_py/cpybin:$XPLACE_ROOT/build`
(the external Xplace, needed only for the ISPD18 `xplace` backend). `ldd` under that environment resolves the
bundled router's parser to `/mnt/nvme0n1/yifan/projs/Xplace/cpp_to_py/cpybin/libxplace_common.so`, which has
none of the LEF fixes -> null-layer crash in `addMovObs`, exactly as before the patch. Standalone probes never
set that path, which is why they were clean. The driver's `eval_def_cli` crashes for the same reason plus it
loads the external root outright.
**Rules:** (1) for `ruplace_router_backend=gpugr` never put the external Xplace on `LD_LIBRARY_PATH`;
(2) the loader preloads the bundled `libxplace_common.so`/`libxplace_flute.so` with `ctypes` (RTLD_GLOBAL)
before importing `gpugr`, so the environment cannot hijack it; (3) the eval path must use the bundled root on s14.

### Batch 3b (2026-08-29 11:00): RUPlace runs on s14; first Innovus verdicts (v113, all FAIL)
Loader fix: `_preload_xplace_shared_libs` dlopens the bundled `libxplace_flute.so`/`libxplace_common.so`
(RTLD_GLOBAL) before any extension import - proven under the hijacking `LD_LIBRARY_PATH` (16 obs errors +
SIGSEGV before, clean after). `eval_def_cli` takes `--_eval-gpugr-root` and uses the bundled root for
`ruplace_router_backend=gpugr`. `run_ruplace_v113_s14_ruplace_local.sh` (CONFIGS/SEEDS/CASES) drops the
external Xplace dirs from `LD_LIBRARY_PATH`. RUPlace on nvdla_s: 5 router calls (30 s each at 250x260/rrr=1
on a contended GPU), 1 inflation round (area +0.21%), ~11 min per run.

| config (worst of 2 seeds) | WL (um) | H | V | vs dp_rudy bar |
|---|---:|---:|---:|---|
| base (ISPD18 test10 set + s14 GR) | 4,155,046 | 86,433 | 30,296 | FAIL H,V |
| admm w 0.06 / 0.015, anchor 0.20, freq 100, start 0.45, hv-inflate 0.5 | 4,146k-4,151k | 85.8k-87.3k | 29.7k-30.6k | FAIL H,V (all null within seed noise) |
| target_density 1.10 | 4,086,636 | 90,907 | 34,083 | FAIL H,V |

Reading: RUPlace beats both baselines on WL (-1.3% vs dp_hpwl, -3.5% vs dp_rudy) and loses congestion to
dp_rudy by +15% H / +28% V (it is +5% H / -5% V vs dp_hpwl). Two structural causes, both visible in the logs:
1. **No window.** GP hits `stop_overflow 0.15` at iteration ~610; ADMM starts at ~537 (`admm_start_overflow
   0.33`). Five router calls total, three of them from inflation. Sweeping ADMM weights inside 80 iterations
   returns nulls; the lever is the schedule (`stop_overflow`, `admm_start_overflow`, `route_freq`, iterations).
2. **Inflation is off.** `inflate_area_cap 0.005` (0.5% area, the ISPD18-tuned value) vs dp_rudy's ~10% area
   adjust, which is what buys dp_rudy -9% H / -26% V. RUPlace's inflation now uses maps that correlate .84/.91
   with Innovus; it needs a budget.
Also: the in-loop proxy's final overflow-net count does not rank these near-identical configs the way Innovus
does (start045 best in-loop, worst H) - expected at this spread; do not tune on it. `RC(H)` on the first router
call prints garbage (1419/2064) - reporting only, tensors are fine. v113 `route_wl`/`rc_*` columns in
`raw_metrics.csv` come from the bundled router and are not comparable with v110/v112's external-Xplace columns;
Innovus columns are the only cross-version numbers.

**Protocol change for v114 onward:** Innovus scores **legalized** DEFs (`legalize_flag 1`) for every method.
Unlegalized overlaps inflate Innovus overflow ~2x (stock legalized baseline 40k/17k vs GP-only dp_hpwl 82k/32k)
and add noise unrelated to routability. References are re-run under the same protocol.

### v114 legalized protocol: references (2026-08-29 ~12:30, sweep in progress)
Driver: `--legalize-flag` (default 0) applies to every DREAMPlace method; `find_dreamplace_def` prefers
`*.lg.def` then `*.gp.def`. **DREAMPlace writes one solution DEF**: `Placer.py` writes `<design>.gp.def` after
`NonLinearPlace.__call__` has already legalized, so with `legalize_flag=1` the legalized placement is in
`.gp.def` - the filename proves nothing, the log does (`legalization takes ...`, wHPWL jumps ~+10%).

| method (legalized) | seed | WL (um) | H | V |
|---|---|---:|---:|---:|
| dp_hpwl | 1001 | 4,511,063 | 44,074 | 19,889 |
| dp_hpwl | 1002 | 4,514,946 | 44,858 | 18,564 |
| dp_rudy | 1001 | 4,543,560 | 33,461 | 14,702 |
| dp_rudy | 1002 | 4,521,139 | 43,025 | 20,710 |

Legalization raises WL ~7% and roughly halves Innovus overflow counts (the unlegalized overlap noise is gone).
**Bar (dp_rudy per-metric worst seed): WL <= 4,543,560, H <= 43,025, V <= 20,710.** Caveat that matters:
dp_rudy's two seeds differ by 28% in H and 41% in V - larger than most config effects. With two seeds the
"worst seed" of a noisy method is a weak bar; a config that passes it must also be checked for its own seed
spread, and a third seed for dp_rudy is warranted before any final claim.

### v119 final + overall result as of 2026-08-30 10:33 (all runs done; nothing running)
regression_s14 band fill (legalized, Innovus EGR, ADMM on, s1001 / s1002; dp_hpwl worst = 11,166,016 /
515,505 / 279,254):

| config | WL | H | V | worst-seed vs dp_hpwl worst |
|---|---|---|---|---|
| thr08_g025 | 11,329,420 / 11,329,094 | 392,096 / 412,732 | 206,588 / 214,850 | **+1.5% / -20% / -23%** |
| thr085_g030 | 11,291,512 / 11,341,023 | 396,348 / 418,760 | 202,982 / 211,721 | +1.6% / -19% / -24% |
| thr09_g035 | 11,366,852 / 11,332,720 | 408,550 / 416,652 | 209,008 / 216,853 | +1.8% / -19% / -22% |
| thr08_g035 (v116) | 11,411,040 / 11,463,261 | 381,660 / 406,682 | 197,836 / 203,253 | +2.7% / -21% / -27% |
| thr06_g070_w1 (v116) | 11,706,819 / 11,673,346 | 336,244 / 342,469 | 173,997 / 174,108 | +4.8% / -34% / -38% |

All three new points sit inside the +2% band; `thr08_g025` is the best by H+V. The frontier on this design is
smooth: +1.5% -> -20%/-23%, +2.7% -> -21%/-27%, +4.8% -> -34%/-38%.

**Overall result (the claim the write-up can make):** on two SMIC14 designs, judged by Innovus 22 EGR on
legalized placements, RUPlace with calibrated-router threshold inflation gives, inside a +2% routed-WL budget
vs plain DREAMPlace, **-42% H / -36% V on nvdla_s** (`thr06_g070`, +1.9%) and **-20% H / -23% V on
regression_s14** (`thr08_g025`, +1.5%). Default DREAMPlace-RUDY buys -4%/-1% (nvdla_s) and ~0% (regression)
in that band; a RUDY tuned to fire its rounds has no operating point below +6% WL. Above ~+5.6% WL the two
methods are indistinguishable. The mechanism is threshold inflation on a router map that correlates
.84/.91 (Spearman H/V) with Innovus; ADMM route gradients contribute ~1%; the schedule ~1/10 of the H gain.
Caveats: 2 seeds per point (spreads: nvdla_s <3%, regression H up to 8%); dp_rudy above +6% mostly
unconverged at the 1000-iteration cap; area bases of the two inflation methods are not comparable.

### v119 interim (2026-08-30 ~04:00): v115 validated post-fix; schedule confound resolved
- **Post-fix spot check (nvdla_s s1001):** thr08_g035 4,535,773/33,381/14,661 -> 4,532,864/33,166/14,470;
  thr06_g070_w1 4,608,371/25,696/12,525 -> 4,611,977/25,466/12,131. All deltas inside each config's own seed
  spread (a small systematic improvement is possible - all four congestion deltas go the same way). v115/v118
  tables stand.
- **Schedule confound:** `dp_hpwl` at `stop_overflow 0.10` (`_v119_ref_stop010_`): nvdla_s 4,491,598/42,767/
  20,727 and 4,482,928/42,115/18,780; regression 11,105,708/470,531/262,423 and 10,963,954/502,919/277,255.
  Effect of 0.15->0.10 on dp_hpwl alone: WL -0.4..-0.7%, H -1.6..-6%, V -2..+4% (worse on nvdla_s). It explains
  ~1/10 of RUPlace's H gain and none of the V gain. Best in-band nvdla_s point vs this tighter reference:
  `thr06_g070` WL +2.5%, H -40%, V -39%.
- `--stop-overflow` is confirmed to reach dp_hpwl (`routability_opt_flag 0`, so these references never touch
  the in-loop router). v112/v113 rows are unlegalized and excluded from every comparison.

### v118 matched-WL frontier on nvdla_s (2026-08-30 02:30, 16/16 ok; new binary for RUPlace rows)
Worst seed, legalized, Innovus EGR. dp_hpwl = 4,514,946 / 44,858 / 19,889.

| point | WL | dWL vs dp_hpwl | H | V | note |
|---|---:|---:|---:|---:|---|
| dp_rudy default | 4,543,560 | +0.6% | 43,025 | 20,710 | 1-2 RUDY rounds |
| v115 thr08_g070 | 4,562,981 | +1.1% | 29,209 | 13,278 | |
| v115 thr06_g070 | 4,602,377 | +1.9% | 25,844 | 12,660 | max ratio 2.0 |
| **v118 r3_thr06_g070** | **4,618,383** | **+2.3%** | **24,386** | **11,114** | max ratio 3.0 - best inside ~+2% |
| v118 r3_thr05_g070 | 4,677,978 | +3.6% | 22,625 | 10,126 | |
| v118 r3_thr05_g100 | 4,723,692 | +4.6% | 22,204 | 9,513 | |
| v118 r3_thr04_g070 | 4,766,200 | +5.6% | 20,420 | 9,657 | |
| rudy020 | 4,785,472 | +6.0% | 20,887 | 9,354 | **unconverged** (1000-iter cap, ovf 0.31-0.35) |
| rudy030 | 4,803,743 | +6.4% | 19,245 | 9,102 | converged |
| rudy025 | 4,813,582 | +6.6% | 18,107 | 9,022 | s1001 unconverged |
| rudy025_r5 (4 rounds) | 5,403,887 | +19.7% | 82,425 | 33,384 | diverged - dominated |

Reading: **below ~4.62M WL (+2.3%) RUPlace has the frontier to itself** - RUDY inflation has no operating point
between +0.6% (43k H) and +6% (21k H) because `node_area_adjust_overflow` jumps it from one round to three.
Interpolated at matched WL, RUPlace's advantage is ~-11.8k H / -6k V at +1.7% WL, decays as it is pushed
harder, and **saturates around 4.77M WL (+5.6%)** where `r3_thr04_g070` vs `rudy020` is a wash (-467 H, +303 V)
and `rudy030` beats it above that. Every RUPlace run converged (737-803 iterations, overflow ~0.10); the dp_rudy
points above 4.7M mostly did not. Area bases differ (RUPlace cumulative 10-28% vs RUDY per-round ratio ~1.45)
and cannot be netted. Driver gained `--max-num-area-adjust` (default 3).
**Inside the user's +2% band on nvdla_s the answer is `thr06_g070` (+1.9%, H -42%, V -36% vs dp_hpwl) or
`r3_thr06_g070` if +2.3% is acceptable (H -46%, V -44%).**

### Batch 7 final (2026-08-30 00:30): ADMM fault root cause + regression_s14 confirmation
- **Root cause** (not the plan's `numGbPin` hypothesis, which was verified correct): `GPURouter::setFromNets`
  leaves `plPinId2gbPinId = -1` for placement pins whose net is not in the GR database; regression_s14 has
  exactly **1** such pin (nvdla_s 0), and `assignRouteForceToPlPin` then reads `gbpin_grad[-1]` -> deterministic
  illegal address. A `rrr_iters=0` run reproduced it, ruling out rip-up staleness. Fix in
  `cmake/xplace_gpugr_s14_fidelity.patch`: skip unmapped pins; defensive bounds in `compGcellAdmmRouteForce` /
  `compGcellRouteForce` (numRoutes clamp, live-segment check, grid/weight bounds), PatternRoute 5th-route write
  bounded, `numGbPin` = max+1, node-grad pin bound. Router maps bit-identical on nvdla_s before/after.
  **Caveat:** the ADMM guards skip stale route records on ripped-up nets (~9% on nvdla_s), so nvdla_s ADMM
  gradients can differ from v115's pre-fix runs; v118 runs on the new binary. compute-sanitizer never finished
  (the ADMM kernel is pathologically slow under it); evidence is the falsification + unmapped-pin counter + fix.
- **Fair dp_rudy** stops at `max_num_area_adjust 3` (round cap), cumulative +30% (regression) / +43% (nvdla_s)
  area, nvdla_s s1001 hit the 1000-iteration cap. Its cost is 7-9% WL.
- **regression_s14 RUPlace (legalized, ADMM on, worst seed):**

| config | WL | H | V | vs dp_hpwl s1001 | vs dp_rudy-0.25 s1001 |
|---|---:|---:|---:|---|---|
| thr08_g035 | 11,463,261 | 406,682 | 203,253 | +2.7% / -15% / -24% | -4.2% / +31% / +15% |
| thr08_g070 | 11,726,631 | 376,923 | 183,408 | +5.0% / -21% / -32% | -2.0% / +21% / +3% |
| **thr06_g070_w1** | 11,706,819 | 342,469 | 174,108 | +4.8% / **-28% / -35%** | -2.2% / +10% / -2% |

  `thr06_g070_w1` dominates `thr08_g070` on all three axes here (on nvdla_s it cost more WL). H/V ordering
  reproduces across designs; WL ordering does not. Inflation is ratio-limited (max 2.0) in every run.
- **ADMM contribution on regression_s14** (thr08_g035 s1001 with vs without): -0.7% WL, -1.5% H, -0.6% V for
  4.5x the router calls and 1.7x the runtime. The mechanism that works is threshold inflation on the calibrated
  map; ADMM is a weak lever on s14 (consistent with v113/v114 nulls).
- Inside the user's +2% WL band on regression_s14 there is no point yet (thr08_g035 is +2.7%); a
  `thr08_g025`/`thr09_g035` pair is needed. Confound still open: references stop at overflow 0.15, RUPlace at
  0.10.

### Acceptance criterion updated by the user (2026-08-29 22:40)
"我可以接受 wl 稍微差一些对比 dreamplace 本体": a **small WL penalty relative to dp_hpwl is acceptable** if
congestion improves. Operating assumption until told otherwise: **WL <= dp_hpwl worst seed + 2%**, then
minimize H and V (report H+V and each). Bands: nvdla_s WL <= 4,605,245; regression_s14 WL <= 11,389,336.
Best points inside the band today (Innovus, legalized, worst seed):
- nvdla_s: `thr06_g070` WL 4,602,377 (+1.9%), H 25,844 (-42% vs dp_hpwl), V 12,660 (-36%);
  `thr08_g070` at +1.1% gives H 29,209 (-35%) / V 13,278 (-33%).
- regression_s14 (n=1 so far): `thr08_g035` s1001 WL 11,411,040 (+2.2%, just outside), H -20%, V -26%.
The v118 frontier sweep decides whether more relief is available inside the +2% band (max ratio 3, thr 0.4-0.5)
and where dp_rudy-with-rounds lands at the same WL.

### Batch 7 interim (2026-08-29 22:24): ADMM fault fixed; a fair dp_rudy changes the comparison
- The fork patch was regenerated at 19:02 (ADMM buffer-sizing fix; sanitizer evidence under
  `results/ruplace_quality/logs/v117_sanit*`); the regression_s14 confirmation is running again with ADMM on.
- **Fair dp_rudy (`--node-area-adjust-overflow 0.25`, so RUDY area-adjust actually fires before GP stops):**

| design | dp_rudy 0.25 (s1001 / s1002) | WL | H | V | vs dp_hpwl |
|---|---|---:|---:|---:|---|
| nvdla_s | v117_ref_rudy025 | 4,780,816 / 4,813,582 | 17,156 / 18,107 | 9,022 / 8,919 | WL +6..7%, H -61%, V -55% |
| regression_s14 | v117_ref_rudy025 | 11,968,073 / 12,007,761 | 310,811 / 323,261 | 177,382 / 175,681 | WL +7..9%, H -35..-40%, V -34..-37% |

  With its rounds firing, RUDY inflation buys far more congestion relief than the default dp_rudy - at 6-9% WL.
  So "beat dp_rudy" is not one bar but a **frontier**: the honest comparison is congestion at matched WL.
  RUPlace's frontier so far spans WL +0..+1.4% (nvdla_s) / +2..+6% (regression); dp_rudy-0.25 sits at +6..9%.
  RUPlace points at +3..6% WL are needed (raise `ruplace_max_inflate_ratio` to 3, thr 0.4-0.5, gamma 0.7-1.0,
  cap 0.3) and dp_rudy points below +6% (`node_area_adjust_overflow` 0.20, 0.30; `max_num_area_adjust`).
- regression_s14 RUPlace rows so far (legalized, ADMM on): thr08_g035 s1001 WL 11,411,040 / H 381,660 /
  V 197,836 (vs dp_hpwl s1001: +2.2% / -20% / -26%); thr08_g070 s1002 11,703,020 / 376,923 / 183,408 (vs dp_hpwl
  s1002: +6.3% / -27% / -34%). Against dp_rudy-0.25, RUPlace has lower WL but higher H/V - frontier, again.

### v116 regression_s14 confirmation: blocked by an ADMM CUDA fault; dp_rudy degenerate there (2026-08-29 17:30)
Legalized references (`results/s14_innovus/regression_s14.csv`, `_v116_` rows; the v112 rows are unlegalized):

| method | seed | WL (um) | H | V |
|---|---|---:|---:|---:|
| dp_hpwl | 1001 / 1002 | 11,166,016 / 11,008,852 | 478,268 / 515,505 | 267,790 / 279,254 |
| dp_rudy | 1001 / 1002 | 11,161,538 / 11,020,658 | 478,572 / 517,255 | 266,746 / 281,455 |

Seed spread is large here (H 8%), and **dp_rudy = dp_hpwl on this design**: both seeds run exactly one RUDY
area-adjust round at iteration 518 and GP stops at 519, because DREAMPlace's `node_area_adjust_overflow`
(0.15) equals `stop_overflow` (0.15) - +10% area applied with no iterations left to re-spread. A fair dp_rudy
baseline needs `node_area_adjust_overflow` > `stop_overflow` (e.g. 0.25) so it gets its rounds; on nvdla_s the
consistent seeds got 2 rounds by luck of the overflow trajectory.
**RUPlace fails 7/7 on regression_s14** at the first ADMM gradient after router call 1 (iteration 406):
`admm_gradient` -> `routeforce.admm_route_grad` -> `CUDA error: an illegal memory access`. Router call itself
completes (224,196 overflow nets, 246 s). Not contention (serial retry identical), not grid bounds. Leading
hypothesis (unverified): `GPURouter.cu:935` sizes `numGbPin` from the *last* GR net's `pin2gbpinId`, assuming
it carries the maximum id; PatternRoute then writes `gbpinRoutes` past the end silently and
`compGcellAdmmRouteForce` (`GPURouterTorch.cu:218`) reads garbage `routeId`. nvdla_s survives by luck.
Diagnostic with ADMM disabled (`--ruplace-admm-start-overflow 0.0`, run id `..._v116diag_noadmm_s1001`) runs:
first inflation touched **48% of movable cells for +9.6% area** (ratio-limited at 2.0) - the threshold lever
bites far harder on the dense design than on nvdla_s (14%, +3%). Its Innovus row doubles as an ADMM ablation.
**No-ADMM diagnostic scored** (`_v116diag_noadmm_s1001`, thr08_g035 with ADMM off, 686 iterations, 4 router
calls, +9.6% area on 48% of cells): WL 11,490,878, H 387,452, V 199,085 -> vs dp_hpwl/dp_rudy seeds **WL +2.9..4.4%,
H -19..-25%, V -25..-29%**. Same trade shape as nvdla_s at 2-3x the magnitude on both axes; gains are 2-3x the
seed noise. n=1 and ADMM-free, so a diagnostic, not a batch-6 row. Confound to keep in mind: the RUPlace base
uses `stop_overflow 0.10` while references stop at 0.15 (~170 more iterations) - part of the delta is
schedule, not inflation; identical confound in v115/nvdla_s. A "references at stop 0.10" pair would isolate it.
Evidence: `results/ruplace_quality/logs/v116_failure_evidence/`. Resume after the fix:
`rm -rf results/ruplace_quality/s14_regression_s14_v116_thr08_g035_s1001; RUN_REFS=0 bash run_ruplace_v116_s14_reg_local.sh`.

### v115 final (2026-08-29 15:00, 16/16 ok) - the full threshold-inflation frontier on nvdla_s
| config (worst seed) | WL | H | V | cum. area | inflated cells | H+V |
|---|---:|---:|---:|---:|---:|---:|
| dp_rudy (consistent seeds) | 4,543,560 | 33,461 | 14,702 | +29% (RUDY) | - | 48,163 |
| thr08_g035 | 4,535,773 | 33,381 | 14,661 | 3.1% | 14% | 48,042 |
| thr08_g070 | 4,562,981 | 29,209 | 13,278 | 5.1% | 14% | 42,487 |
| thr06_g035 | 4,562,891 | 29,168 | 14,283 | 5.8% | 30% | 43,451 |
| thr07_g050 | 4,567,771 | 30,017 | 13,538 | 5.3% | 20% | 43,555 |
| thr05_g035 | 4,586,465 | 27,829 | 12,790 | 8.8% | 42% | 40,619 |
| thr08_g070_w1 | 4,590,569 | 28,323 | 12,967 | 7.7% | 25% | 41,290 |
| thr06_g070 | 4,602,377 | 25,844 | 12,660 | 9.8% | 31% | 38,504 |
| thr06_g070_w1 | 4,608,371 | 25,696 | 12,525 | 13.5% | 53% | 38,221 |

- Every config beats dp_rudy's consistent seeds on H and V; only `thr08_g035` also keeps WL under
  dp_rudy's. `thr08_g035` = dp_rudy's good seed within noise (H -0.2%, V -0.3%, WL -0.2%) - the robust claim
  is **variance**: dp_rudy's H swings 29% across seeds, RUPlace's 2.6%; RUPlace lands there every time.
- Frontier: roughly **+1% WL per +5% inflated area**, buying up to -23% H / -15% V (`thr06_g070_w1`).
- Mechanics: threshold sets the inflated *population*, gamma the *magnitude*; `node_util_window=1` doubles the
  population but is redundant with a lower threshold (H+V gain 0.7% at thr06 for more WL); area cap 0.15
  never bound (max 13.5%); **`ruplace_max_inflate_ratio=2.0` binds at thr <= 0.6** (7/16 runs at exactly
  2.0000) - the next knob. Local `allow_shrink` rounds ignore `global_inflate_gamma`/`util_exponent`.
- Runtime: 14-17 router calls, 740-770 iterations, 37-70 min per run on a 4-way shared GPU.
- Unit tests: 16 pass; the 1 failure (`test_scaled_and_raw_position_conversion`, fixture missing
  `num_movable_nodes`) is pre-existing and unrelated.

### v114 final + dp_rudy seed 1003: the bar is re-based (2026-08-29 14:30)
dp_rudy s1003 (legalized): WL 4,541,080, H 31,788, V 14,670 - agrees with s1001. **s1002 was an outlier**: it
ran 1 RUDY area-adjust round (+14% area, stop at iter 612) where s1001/s1003 ran 2 (+29%, iter ~759). Under the
formal rule "worst seed" that outlier made every v114 config pass, including the untuned control - the column
separated nothing. **Reference from here on = dp_rudy's consistent seeds (1001/1003):** WL 4,543,560,
H 33,461, V 14,702 (worst of the two); strict "best seed" check H 31,788 / V 14,670 / WL 4,541,080.
v114 complete (16/16 ok): all configs beat dp_hpwl at worst seed; against the re-based reference only
`infl_heavy` (34,077 H / 15,932 V worst, WL 4,537,032) is in range and still loses H by 2-7%. Lever reading
confirmed: inflation *strength and start* (`global_inflate_gamma` 0.35->0.5, `inflate_start_overflow`
0.3->0.5) moved things, the area cap never bound; schedule -6% H at 2x runtime; ADMM weight and density null.
**v115 `thr08_g035` vs the re-based reference:** worst-seed WL 4,535,773 < 4,543,560, H 33,381 < 33,461,
V 14,661 < 14,702 - passes strictly but by <1% on H/V; vs dp_rudy's best seed it loses H (33,381 vs 31,788).
`thr08_g070` beats every dp_rudy seed on H (29,209) and V (13,278) at WL +0.4% (4,562,981). The defensible
claim is the Pareto front, not a single point. Caveat for any write-up: dp_rudy was run at its defaults; its
own inflation was not tuned.

### v115 threshold inflation: first strict win over dp_rudy's BEST seed (2026-08-29 13:52, 10/16 scored)
`ruplace_inflate_util_threshold` (default 1.0): node utilization is divided by the threshold before the
`clamp_min(1)` in both global and local inflation, so bins above `thr` (not only above 1.0) inflate. Base for
v115 = test10 set + s14 GR + `sched` + area cap 0.15, 3 local rounds, hv 0.5 max, inflate start 0.5.

| config (Innovus, legalized, s1001 / s1002) | WL (um) | H | V |
|---|---|---|---|
| dp_rudy (reference) | 4,543,560 / 4,521,139 | 33,461 / 43,025 | 14,702 / 20,710 |
| v114 infl_heavy | 4,537,032 / 4,522,400 | 34,007 / 34,077 | 15,932 / 14,286 |
| **v115 thr08_g035** | **4,535,773 / 4,513,570** | **33,381 / 32,547** | **14,661 / 14,068** |
| v115 thr08_g070 | 4,562,981 / 4,551,387 | 29,209 / 28,500 | 13,278 / 12,823 |
| v115 thr08_g070_w1 | 4,590,569 / 4,588,031 | 28,323 / 27,287 | 12,967 / 12,570 |
| v115 thr06_g070_w1 | 4,608,371 / 4,597,674 | 25,696 / 25,236 | 12,525 / 11,782 |

- **`thr08_g035` strictly dominates dp_rudy on all three metrics against dp_rudy's *best* seed, at both of its
  own seeds** (WL 4,535,773 < 4,543,560 and < 4,521,139 at s1002; H 33,381 < 33,461; V 14,661 < 14,702). It
  passes the formal worst-seed bar by a wide margin and, vs dp_hpwl worst seed: WL +0.5%, H -26%, V -26%.
- Raising gamma / lowering the threshold / adding the util window trades WL for congestion roughly linearly:
  +0.5-1.4% WL buys -13% to -24% H and -10% to -20% V relative to dp_rudy's best seed. This is the Pareto
  front the paper/report should show; `thr08_g035` is the "no-WL-loss" point, `thr06_g070_w1` the congestion
  point.
- Inflation is finally real: ratio avg ~1.03, max ~1.97, 3 rounds. (The v114 lever ordering stands:
  inflation budget + threshold >> schedule > ADMM weights.)
Pending: v115 thr06_g035, thr06_g070, thr07_g050, thr05_g035; v114 td090_cap10; dp_rudy s1003. Next:
confirm `thr08_g035` and `thr06_g070_w1` on `regression_s14` (2 seeds) under the same protocol.

### v114 interim (2026-08-29 10:36, 9/16 RUPlace runs scored; legalized protocol, Innovus EGR, nvdla_s)
| config | WL s1001 / s1002 | H s1001 / s1002 | V s1001 / s1002 |
|---|---|---|---|
| dp_hpwl | 4,511,063 / 4,514,946 | 44,074 / 44,858 | 19,889 / 18,564 |
| dp_rudy | 4,543,560 / 4,521,139 | 33,461 / 43,025 | 14,702 / 20,710 |
| base_lg | 4,485,646 / 4,482,215 | 41,518 / 41,895 | 19,626 / 19,258 |
| cap05 | 4,483,428 / 4,480,188 | 41,214 / 41,965 | 19,042 / 18,585 |
| cap10_hv05 | 4,486,013 / 4,476,299 | 40,282 / 40,235 | 19,328 / 18,819 |
| sched | 4,466,013 / 4,464,165 | 39,456 / 38,514 | 19,340 / 19,139 |
| **infl_heavy** | **4,537,032** / pending | **34,007** / pending | **15,932** / pending |

Every RUPlace config strictly dominates dp_hpwl at worst seed (WL -0.6..-1.1%, H -7..-14%, V -3..-5%) with
seed spreads under 1% on H. `sched` (stop_overflow 0.10, ADMM start 0.55, route_freq 25) is the best
"cheap" config. `infl_heavy` (area cap 0.15, global gamma 0.5, 3 local rounds, hv 0.5, inflate start 0.5)
reaches dp_rudy's *good* seed on congestion (34,007 H / 15,932 V vs 33,461 / 14,702) at lower WL than
dp_rudy (4,537,032 vs 4,543,560) - the first config in the dp_rudy-level congestion regime; seed 1002 pending.
### Why RUPlace inflation is ~0.2% regardless of the cap (read from `ruplace_op.py`, 2026-08-29)
v114 interim: `cap05` inflates +0.22%/+0.18%, `base_lg` +0.20%/+0.21% - the cap is never binding. Mechanism
(`RUPlaceInflation.apply`, ~:196-236, and `_node_bin_utilization`, ~:84-130): the global ratio is
`1 + global_gamma * (node_util - 1)^exponent` with `node_util = bin utilization at the node, clamped >= 1`.
Only nodes in bins with utilization > 1 get any inflation; everything else is exactly 1.0. Under `avail`
utilization (mean 0.127 on nvdla_s at 250x260) overflow bins are a small minority, and a bin at util 1.3 gives
only `1 + 0.35 * 0.3^0.745 = 1.14`. The local rounds (`allow_shrink=1` path) use the same clamped utilization,
so they add nothing and the controller logs "converged". The stop test (`local_congestion_stop`) is *not* what
fires - it also requires `ovfl_nets <= 0`.
Contrast: DREAMPlace's RUDY area-adjust (`dp_rudy`) inflates ~10% of area because its map is coarse and hot, and
that blind inflation buys -9% H / -26% V on nvdla_s. RUPlace's map is far better correlated with Innovus (.84/.91)
but reacts only to *existing* overflow. **Next lever: inflate on utilization above a threshold below 1**
(`ruplace_inflate_util_threshold`, legacy 1.0; ratio from `util/threshold`), optionally spread with the existing
`ruplace_node_util_window` max-pool, with a real area budget (cap 0.10-0.15) - a targeted version of what
dp_rudy does blindly. Sweep threshold x gamma x window after v114 reports.

### s14 campaign tooling (worktree, all verified on `nvdla_s_s14`)
- `configs/ruplace_s14_cases.json` - case manifest for `tools/ruplace_quality.py --case-manifest`,
  generated from `data/s14/<case>.meta.json`: fixed-macro DEF, Innovus LEF order, Verilog only as
  `eval_verilog_input` (`dreamplace_verilog_input=false`, the DEF carries NETS).
- `tools/ruplace_s14_innovus_eval.sh <case> <def> <out_dir> [global|detailed]` - scores one DEF through
  the `routability_eval` Innovus adapter with the two outside-repo defaults overridden
  (`cadence_mounted_root=data/s14/innovus_stage`, `cadence_wrapper=tools/cadence_local.sh`). Prints
  one CSV line. Smoke on the baseline GP DEF: `ok`, wirelength 4,375,359, H/V overflow 40,482 / 16,950,
  49.9 s - identical to the hand-run EGR. Note the adapter's `horizontal_overflow`/`vertical_overflow`
  are the `reportCongestion -overflow` **counts**, not the `[NR-eGR]` percentages.
- `run_ruplace_v110_s14_local.sh` - first campaign: `METHODS` (default `dp_hpwl,dp_rudy`; add `ruplace`
  only once an in-loop router works on s14) x `SEEDS` (default `1001 1002`) on `CASE` (default
  `nvdla_s_s14`), `target_density 1.0`, then Innovus EGR on every placed DEF, accumulated in
  `results/s14_innovus/<case>.csv`. Skips finished placements and finished scores. Launched
  2026-08-28 22:36 for the two dp baselines; log
  `results/ruplace_quality/logs/run_ruplace_v110_s14_local.nohup.log`.

## Innovus evaluation

### How Innovus is invoked
`dreamplace/ops/routability_eval/innovus.py` (routability-lab branch) stages LEF/DEF/Verilog into a
temp dir, emits a TCL script, and runs it through a **docker launcher** - the host cannot run modern
Cadence (missing `libXp.so.6`), so everything goes through the `rockylinux-xfce:8.10` image. Reference
launcher: `~/.codex/skills/cadence-local/cadence [-v 21|22|25] <tool> [args]`, default **v22**
(`/mnt/nvme0n1/yifan/projs/EDASoftware/DDI22.10.000`, `INNOVUS221`). Gotchas it encodes:

- It licenses from the file `/export/SoftWare/Cadence/license/license.dat` with `CDS_LIC_ONLY=1` and
  deliberately does **not** forward host `CDS_LIC_FILE`/`LM_LICENSE_FILE`; a host `5280@...` value
  clobbers the file path and the checkout fails. Never export those before a run.
- Rootless docker: the container runs as root, which maps to host `yifan`. Do not add `--user`.
- `--workdir "$(pwd)"` - the working directory must be inside a mounted rw path (see *Scope constraint*).

The evaluator's own requirements: `route_mode` is `global` (`earlyGlobalRoute`, reporting
`reportCongestion -overflow` and `reportWire -summary`) or `detailed` (`globalDetailRoute` plus
`verify_drc` and `verifyConnectivity`); it **requires a Verilog netlist** alongside LEF/DEF
(`init_design` with `init_top_cell`, then `defIn`) and returns `status="unsupported"` without one.

Prefer `route_mode: global` for sweep-scale evaluation. `docs/routability_validation_status.md`
records the existing Innovus campaign retaining only 19/75 then 33/75 valid routes, and the lab doc
attributes the NVDLA-L / XScore losses to status 137 (OOM kill) - detailed routing on large designs is
what breaks. Check retention before scaling a campaign up.

### SMIC 14nm (s14) benchmark cases
Source (read-only): `~/data/benchmarks/s14/<case>/` - SMIC 14nm, 8-metal PDK tech LEF
(`lef_lib/pdk/1P8M_...lef`, 40 layers, `MANUFACTURINGGRID 0.001`) plus std-cell LEF
(`lef_lib/all_lef/scc14nsfp_90sdb_9tc16_rvt_ant.lef`, 1017 macros) plus SRAM macros
(`SARM2_new.lef`). DEFs are gzipped Innovus 22.10 `defOut -floorplan -routing -unplaced` dumps:
fully specified floorplan, PG routed, std cells unplaced - i.e. proper placement inputs.

`python tools/ruplace_s14_prep.py --all` stages a case into `data/s14/<case>/`: decompresses the DEF
(Limbo cannot read `.gz`), writes a `*.fixedmacro.def`, and emits `data/s14/<case>.json` (params) and
`<case>.meta.json` (top cell, Verilog path, LEF list). Re-runs are idempotent.

`data/` is untracked and holds several GB of decompressed DEFs and run output. Do not commit it - and
if a `git clean` wipes it, `ruplace_s14_prep.py` regenerates the staged inputs in a couple of minutes.

Three gates decide usability. **Gate A** DEF *and* Verilog present (the Innovus adapter returns
`unsupported` without a netlist). **Gate B** Innovus `init_design` + `defIn` succeed. **Gate C**
DREAMPlace `place_io` parses the LEF/DEF. All three verified 2026-08-28:

| Case | Top cell | Gate A | Gate B (Innovus insts / nets / macros) | Gate C (DREAMPlace nodes / nets / pins, parse) |
|---|---|---|---|---|
| `nvdla_s_s14` | `NV_nvdla` | pass | 269,397 / 301,898 / 108 | 269,935 / 288,877 / 1,050,713, 10 s |
| `regression_s14` (OpenC910) | `ct_top` | pass | 735,219 / 816,978 / 32 | 736,561 / 750,758 / 3,028,832, 31 s |
| `vortex_l_s14` | `Vortex` | pass | 1,021,053 / 1,427,363 / 376 | 1,022,295 / 1,098,249 / 3,900,477, 56 s |
| `nvdla_l_s14` | `NV_nvdla` | pass | 1,539,185 / 1,722,723 / 80 | 1,540,919 / 1,695,098 / 6,035,812, 58 s |
| `c910_s14` | `ct_top` | **fail** - no DEF | - | - |
| `gemmini_s14` | - | **fail** - no Verilog | - | - |
| `largeboom_s14` | - | **fail** - no Verilog | - | - |
| `vortex_s14` | `Vortex` | **fail** - no Verilog | - | - |

Innovus instance counts equal DREAMPlace's movable-node counts exactly on all four, and Innovus's
macro count equals the number of components `ruplace_s14_prep.py` converts to FIXED - the netlist and
the DEF describe the same design. DREAMPlace's net count is lower because it drops nets with fewer
than two pins (6,653 on `nvdla_s_s14`). The DEF's raw COMPONENTS count is higher than both (354,555
vs 269,397 on `nvdla_s_s14`) because the DEF also carries physical-only cells - fill, tap, antenna -
that are not in the netlist.

The four Gate-A failures can still be placed and scored with GGR/RUDY; they just cannot reach the
Innovus evaluator as it stands.

### Verified end-to-end path (2026-08-28, `nvdla_s_s14`)
The whole loop runs, entirely inside this repo:

```bash
python tools/ruplace_s14_prep.py --case nvdla_s_s14         # DEF + config into data/s14/
cd install && python dreamplace/Placer.py \
    ../data/s14/run_nvdla_s_gp.json                          # GP+LG -> *.gp.def
cd data/s14/innovus_egr/nvdla_s_baseline && \
  ../../../../tools/cadence_local.sh -v 22 innovus -no_gui -batch -files ../../egr_nvdla_s.tcl
```

Baseline (`target_density 1.0`, 512x512 bins, `stop_overflow 0.1`, run from the root-tree
`install/`). This is the **no-routability reference point**, not the DREAMPlace-RUDY baseline the
`reports/` comparisons use: `routability_opt_flag=0`, which also leaves `adjust_rudy_area_flag` and
`adjust_pin_area_flag` inert. No RUPlace, no RUDY inflation, no `AdjustNodeArea`. Re-run with
routability enabled before quoting any RUPlace delta against it.

| Stage | Result |
|---|---|
| Global placement | converged at iteration 634, overflow 0.0799, wHPWL 3.789e7, 19.9 s on the TITAN RTX |
| Innovus `earlyGlobalRoute` | `EGR_UNPLACED 0`; 48 s wall, 2.8 GB peak |
| `[NR-eGR]` overflow after EGR | **1.50% H + 0.68% V** |
| `reportCongestion -overflow` | 57,432 total = 40,482 (**2.49% H**) + 16,950 (**1.05% V**) |
| Routed wirelength (`dbget top.nets.wires.length`) | **4,375,359.37** |

The two overflow numbers are not the same measurement - the `[NR-eGR]` line is the router's own
post-route summary, `reportCongestion -overflow` re-reports over the congestion map. Pick one and
keep it fixed across a comparison; do not mix them in one table.

A 48 s Innovus EGR on `nvdla_s_s14` is cheap enough to sit inside a tuning loop, which is the point
of preferring `route_mode: global` over detailed routing for sweeps.

The GP DEF is faithful to the input for everything the router reads: `SPECIALNETS` (2), `TRACKS`,
`GCELLGRID`, `VIAS` (84), `PINS` (538), and `NETS` (288,877) all carry through unchanged, so PG and
routing resources are the shipped floorplan's. The one difference is `COMPONENTS`: 269,397 out versus
354,555 in, because DREAMPlace only writes back the cells it loaded and drops the 85,158 physical-only
cells (fill, tap, antenna). That is the right behaviour for a placement benchmark - their original
positions are meaningless once cells move, and a real flow re-inserts fill after placement - but it
does mean EGR sees slightly less occupied area than the shipped floorplan implies. Keep it in mind
when comparing against an Innovus-native `place_design` result.

**Known gap:** the routability-lab worktree's `install/` is stale - it lacks
`ops/routability_opt/plugins/multisegment_connection_routeforce.py`, so `Placer.py` there dies at
import with `ModuleNotFoundError`. The baseline above therefore used the root tree's `install/`.
Fix it with a clean `./build.sh` in the worktree before running RUPlace on s14: one missing plugin
means the install predates an unknown set of source changes, so hand-copying that one file yields a
silently mixed tree - the exact failure `sync_launch`'s `py_compile` preflight exists to catch.

### Two s14 quirks (both handled by `tools/ruplace_s14_prep.py`)
- **Site-name mismatch.** The DEFs declare core rows with `SITE core7T`, which no shipped s14 LEF
  defines, so `PlaceDB::add_def_row()` asserts out. The geometry is identical to the library's
  `90s9t_CoreSite` (0.090 x 0.576 um = the DEF's `STEP 90` and 576-unit row pitch), so
  `data/s14/s14_extra_sites.lef` declares `SITE core7T` as an alias. It adds a name, not geometry.
- **LEF order matters for Innovus, not for DREAMPlace.** The tech LEF must be first or Innovus aborts
  with `IMPLF-26 No technology information is defined in the first LEF file` (and then reports
  spurious `Layer 'M1' is not defined`). The site-alias LEF goes second. DREAMPlace accepts any order,
  so the prep tool emits the Innovus order for both.
- **Macros come in movable.** Macro instances are `+ PLACED`, not `+ FIXED`, so DREAMPlace reports
  `num_terminals=0` and treats them as movable - a mixed-size run, not the fixed-macro routability
  study intended. The prep tool rewrites the COMPONENTS section only (PINS and SPECIALNETS use the
  same token and must keep their status); `nvdla_s_s14` then parses with `num_terminals=108`.

## Working notes

- After editing any C++/CUDA under `dreamplace/ops/`, you must rebuild+reinstall (`./build.sh`) before
  the change takes effect at runtime — the running code is the copy in `install/`, not the source.
  Pure-Python edits still need to reach `install/dreamplace/` (rebuild, or rsync as the launch script
  does).
- `dreamplace/configure.py` in the source/install tree is generated; never hand-edit it.
- The root tree carries a lot of untracked research state (`run_ruplace_*.sh`, `configs/`, `tools/`,
  `reports/`, `results/`, `.worktrees/`). None of it is upstream. Don't commit it, don't `git clean`
  it, and don't assume it is canonical.
- Stale `__pycache__` directories survive branch switches and can make a deleted module look present.
  Trust `git ls-files` / the branch, not the directory listing.
- Result claims in `reports/` are **Xplace GGR estimates**, not OpenROAD/Innovus detailed-route
  signoff. Keep that distinction when writing or editing any summary.
- `AGENTS.md` at the repo root is a copy of this file, kept byte-identical for other agent tools.
  Update both together.
