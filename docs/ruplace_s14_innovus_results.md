# RUPlace on SMIC14, judged by Innovus early global route

Result document for the `feat/ruplace-s14-innovus` branch. Every number below is a measured
value from the v110-v119 campaign; the campaign drivers are committed at the repo root as
`run_ruplace_v11*.sh`.

**Benchmark data is private.** The SMIC14 cases live outside this repository
(`~/data/benchmarks/s14/<case>/`) and their staged copies under `data/s14/` are not tracked.
The only shipped file from that tree is `data/s14/s14_extra_sites.lef`, a 15-line site alias.
Nothing here is reproducible on public data.

## 1. Protocol

- **Designs.** `nvdla_s_s14` (top cell `NV_nvdla`, 269,397 instances / 301,898 nets / 108
  macros by Innovus; 269,935 nodes / 288,877 nets / 1,050,713 pins by DREAMPlace) and
  `regression_s14` (OpenC910, top cell `ct_top`, 735,219 / 816,978 / 32 by Innovus;
  736,561 / 750,758 / 3,028,832 by DREAMPlace). Innovus instance counts equal DREAMPlace's
  movable-node counts exactly on both.
- **Inputs.** Innovus 22.10 `defOut -floorplan -routing -unplaced` dumps: fully specified
  floorplan, PG routed, standard cells unplaced. `tools/ruplace_s14_prep.py` decompresses the
  DEF, rewrites COMPONENTS so the macros are FIXED (they ship as `+ PLACED`, which would make
  it a mixed-size run) and emits the params and meta JSON.
- **Placement.** `tools/ruplace_quality.py --case-manifest configs/ruplace_s14_cases.json`,
  `target_density 1.0`, 1000-iteration cap, seeds 1001 and 1002.
- **Legalized DEFs.** All scored placements use `--legalize-flag 1`. DREAMPlace writes one
  solution DEF: `Placer.py` emits `<design>.gp.def` after `NonLinearPlace.__call__` has already
  legalized, so with `legalize_flag=1` the legalized placement is in `.gp.def` - the filename
  proves nothing, the log does (`legalization takes ...`, wHPWL jumps ~+10%). Legalization
  raises WL ~7% and roughly halves the Innovus overflow counts relative to the unlegalized
  v112/v113 rows, which are excluded from every comparison here.
- **Scoring.** Innovus 22 (`DDI22.10.000`, `INNOVUS221`) `earlyGlobalRoute` through
  `tools/ruplace_s14_innovus_eval.sh`, i.e. the `routability_eval` Innovus adapter driven by
  the `tools/cadence_local.sh` docker launcher. Reported metrics are
  `reportCongestion -overflow` **counts** for H and V, and routed wirelength from
  `dbget top.nets.wires.length` (um). These are not the `[NR-eGR]` percentages; the two
  measurements are never mixed in one table. One EGR on `nvdla_s_s14` costs about 48 s.
- **In-loop router grid.** The bundled GPUGR runs at gcell step 2880 dbu (5 SMIC14 row
  heights; 250x260 gcells on `nvdla_s_s14`), `rrr=1`, `avail` utilization,
  `wire_cost_sat=1`, `m1_routable=0`, `max_route_len_per_pin=256`, `via_usage_scale=0`,
  guides off - about 17 s per call.

### Router calibration (v111)

Agreement of the in-loop router map with the Innovus EGR map on `nvdla_s_s14`, all rows at
`m1_routable=0 max_route_len_per_pin=256 via_usage_scale=0 wire_cost_sat=1`, util `avail`,
quiet GPU; k = Innovus gcells per GPUGR gcell.

| grid | k | rrr | Spearman H/V | IoU 2% H/V | WL ratio | ovfl nets | run_ggr |
|---|---|---|---|---|---:|---:|---:|
| 1250x1300 | 1 | 1 | .776/.777 | .365/.290 | 1.029 | 9,346 | 176 s |
| 625x650 | 2 | 1 | .817/.864 | .349/.375 | 1.027 | 8,819 | 79 s |
| 625x650 | 2 | 0 | .913/.899 | .274/.496 | 0.958 | 25,417 | 7.9 s |
| **250x260** | **5** | **1** | **.843/.909** | **.332/.499** | **1.034** | **8,780** | **16.9 s** |
| 250x260 | 5 | 0 | .922/.938 | .342/.550 | 0.952 | 17,814 | 4.2 s |

Coarsening improves agreement: the Innovus EGR map is smooth at 576 dbu, so block-summing
strips the router's fine-grain noise. `rrr=0` correlates better still but underestimates WL by
5% and doubles the overflow nets, so it is only usable if the signal feeds inflation maps
alone. Getting here also required fixing an integer overflow in `PatternRoute.cu` (a per-gcell
`INF = 1e9` truncated into `int` wrapped negative across three or more blocked gcells and won
the min): failed nets 5,200 -> 0.

## 2. References

### nvdla_s_s14 (v114, legalized, Innovus EGR)

| method | seed | WL (um) | H | V |
|---|---|---:|---:|---:|
| dp_hpwl | 1001 | 4,511,063 | 44,074 | 19,889 |
| dp_hpwl | 1002 | 4,514,946 | 44,858 | 18,564 |
| dp_rudy | 1001 | 4,543,560 | 33,461 | 14,702 |
| dp_rudy | 1002 | 4,521,139 | 43,025 | 20,710 |
| dp_rudy | 1003 | 4,541,080 | 31,788 | 14,670 |

Seed 1002 of `dp_rudy` is an outlier: it ran one RUDY area-adjust round (+14% area, stop at
iteration 612) where 1001 and 1003 ran two (+29%, iteration ~759). The reference used from
v114 onward is therefore **dp_rudy's consistent seeds (1001/1003), worst of the two:
WL 4,543,560 / H 33,461 / V 14,702**; the strict best-seed check is H 31,788 / V 14,670 /
WL 4,541,080.

### regression_s14 (v116, legalized, Innovus EGR)

| method | seed 1001 / 1002 | WL (um) | H | V |
|---|---|---|---|---|
| dp_hpwl | 1001 / 1002 | 11,166,016 / 11,008,852 | 478,268 / 515,505 | 267,790 / 279,254 |
| dp_rudy | 1001 / 1002 | 11,161,538 / 11,020,658 | 478,572 / 517,255 | 266,746 / 281,455 |

**`dp_rudy` equals `dp_hpwl` on this design.** Both seeds run exactly one RUDY area-adjust
round at iteration 518 and global placement stops at 519, because DREAMPlace's
`node_area_adjust_overflow` (0.15) equals `stop_overflow` (0.15): +10% area is applied with no
iterations left to re-spread it. A fair `dp_rudy` needs `node_area_adjust_overflow` above
`stop_overflow`.

### Fair dp_rudy (v117, `--node-area-adjust-overflow 0.25`)

| design | WL (s1001 / s1002) | H | V | vs dp_hpwl |
|---|---|---:|---:|---|
| nvdla_s_s14 | 4,780,816 / 4,813,582 | 17,156 / 18,107 | 9,022 / 8,919 | WL +6..7%, H -61%, V -55% |
| regression_s14 | 11,968,073 / 12,007,761 | 310,811 / 323,261 | 177,382 / 175,681 | WL +7..9%, H -35..-40%, V -34..-37% |

With its rounds actually firing, RUDY inflation buys far more relief than the default - at
6-9% WL. "Beat dp_rudy" is therefore not one bar but a frontier: the honest comparison is
congestion at matched WL.

### Schedule-matched reference (v119, dp_hpwl at `--stop-overflow 0.10`)

| design | WL (s1001 / s1002) | H | V |
|---|---|---|---|
| nvdla_s_s14 | 4,491,598 / 4,482,928 | 42,767 / 42,115 | 20,727 / 18,780 |
| regression_s14 | 11,105,708 / 10,963,954 | 470,531 / 502,919 | 262,423 / 277,255 |

Tightening `stop_overflow` from 0.15 to 0.10 on `dp_hpwl` alone moves WL -0.4..-0.7%,
H -1.6..-6%, V -2..+4% (worse on nvdla_s). It explains about **1/10 of RUPlace's H gain and
none of the V gain**. Against this tighter reference the best in-band nvdla_s point,
`thr06_g070`, is WL +2.5%, H -40%, V -39%.

## 3. RUPlace frontier

### nvdla_s_s14, threshold-inflation sweep (v115, worst seed, 16/16 runs ok)

| config | WL | H | V | cum. area | inflated cells | H+V |
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

Roughly **+1% WL per +5% inflated area**, buying up to -23% H / -15% V against dp_rudy.
Threshold sets the inflated population, gamma the magnitude; `node_util_window=1` doubles the
population but is redundant with a lower threshold. The area cap 0.15 never bound (max 13.5%);
`ruplace_max_inflate_ratio=2.0` bound at thr <= 0.6 (7/16 runs at exactly 2.0000). Every run
took 14-17 router calls and 740-770 iterations, 37-70 min on a 4-way shared GPU.
Against dp_rudy's seed spread the robust claim is **variance**: dp_rudy's H swings 29% across
seeds, RUPlace's 2.6%.

### nvdla_s_s14, matched-WL frontier (v118, worst seed, 16/16 ok)

Reference `dp_hpwl` = 4,514,946 / 44,858 / 19,889.

| point | WL | dWL vs dp_hpwl | H | V | note |
|---|---:|---:|---:|---:|---|
| dp_rudy default | 4,543,560 | +0.6% | 43,025 | 20,710 | 1-2 RUDY rounds |
| v115 thr08_g070 | 4,562,981 | +1.1% | 29,209 | 13,278 | |
| v115 thr06_g070 | 4,602,377 | +1.9% | 25,844 | 12,660 | max ratio 2.0 |
| **v118 r3_thr06_g070** | **4,618,383** | **+2.3%** | **24,386** | **11,114** | max ratio 3.0 |
| v118 r3_thr05_g070 | 4,677,978 | +3.6% | 22,625 | 10,126 | |
| v118 r3_thr05_g100 | 4,723,692 | +4.6% | 22,204 | 9,513 | |
| v118 r3_thr04_g070 | 4,766,200 | +5.6% | 20,420 | 9,657 | |
| rudy020 | 4,785,472 | +6.0% | 20,887 | 9,354 | **unconverged** (1000-iter cap, ovf 0.31-0.35) |
| rudy030 | 4,803,743 | +6.4% | 19,245 | 9,102 | converged |
| rudy025 | 4,813,582 | +6.6% | 18,107 | 9,022 | s1001 unconverged |
| rudy025_r5 (4 rounds) | 5,403,887 | +19.7% | 82,425 | 33,384 | diverged - dominated |

**Below ~4.62M WL (+2.3%) RUPlace has the frontier to itself**: RUDY inflation has no operating
point between +0.6% (43k H) and +6% (21k H), because `node_area_adjust_overflow` jumps it from
one round to three. Interpolated at matched WL, RUPlace's advantage is ~-11.8k H / -6k V at
+1.7% WL, decays as it is pushed harder, and **saturates around 4.77M WL (+5.6%)**, where
`r3_thr04_g070` vs `rudy020` is a wash (-467 H, +303 V) and `rudy030` wins above that. Every
RUPlace run converged (737-803 iterations, overflow ~0.10); the dp_rudy points above 4.7M
mostly did not.

### regression_s14, +2% band fill (v119, legalized, ADMM on)

`dp_hpwl` worst seed = 11,166,016 / 515,505 / 279,254.

| config | WL (s1001 / s1002) | H | V | worst seed vs dp_hpwl worst |
|---|---|---|---|---|
| thr08_g025 | 11,329,420 / 11,329,094 | 392,096 / 412,732 | 206,588 / 214,850 | **+1.5% / -20% / -23%** |
| thr085_g030 | 11,291,512 / 11,341,023 | 396,348 / 418,760 | 202,982 / 211,721 | +1.6% / -19% / -24% |
| thr09_g035 | 11,366,852 / 11,332,720 | 408,550 / 416,652 | 209,008 / 216,853 | +1.8% / -19% / -22% |
| thr08_g035 (v116) | 11,411,040 / 11,463,261 | 381,660 / 406,682 | 197,836 / 203,253 | +2.7% / -21% / -27% |
| thr06_g070_w1 (v116) | 11,706,819 / 11,673,346 | 336,244 / 342,469 | 173,997 / 174,108 | +4.8% / -34% / -38% |

The frontier on this design is smooth: +1.5% -> -20%/-23%, +2.7% -> -21%/-27%,
+4.8% -> -34%/-38%.

## 4. Recommendation inside the +2% WL band

The accepted operating rule is **WL <= dp_hpwl worst seed + 2%**, then minimise H and V.
Bands: nvdla_s WL <= 4,605,245; regression_s14 WL <= 11,389,336.

| design | config | WL (worst seed) | dWL | H | V |
|---|---|---:|---:|---|---|
| nvdla_s_s14 | `thr06_g070` | 4,602,377 | +1.9% | 25,844 (-42%) | 12,660 (-36%) |
| regression_s14 | `thr08_g025` | 11,329,420 | +1.5% | 412,732 (-20%) | 214,850 (-23%) |

Each column is the **per-metric worst seed**, not one run: on regression_s14 the WL figure is
seed 1001 (11,329,420 vs 11,329,094) while the H and V figures are seed 1002 (412,732 and
214,850 vs 392,096 and 206,588). The percentages are against the per-metric worst seed of
`dp_hpwl` on the same design. The nvdla_s row happens to be a single run (seed 1001).

If +2.3% is acceptable on nvdla_s, `r3_thr06_g070` gives H -46% / V -44%.

### Overall result

On two SMIC14 designs, judged by Innovus 22 EGR on legalized placements, RUPlace with
calibrated-router threshold inflation gives, inside a +2% routed-WL budget versus plain
DREAMPlace, **-42% H / -36% V on nvdla_s** (`thr06_g070`, +1.9%) and **-20% H / -23% V on
regression_s14** (`thr08_g025`, +1.5%). Default DREAMPlace-RUDY buys -4%/-1% (nvdla_s) and
about 0% (regression) in that band; a RUDY tuned to fire its rounds has no operating point
below +6% WL. Above ~+5.6% WL the two methods are indistinguishable.

### Mechanism attribution

- **Threshold inflation is the mechanism.** `ruplace_inflate_util_threshold` divides the node
  bin utilization by the threshold before the `clamp_min(1.0)` in both the global and the local
  `allow_shrink` path, so bins above the threshold inflate rather than only bins above 1.0.
  With the legacy threshold of 1.0 and `avail` utilization (mean bin utilization ~0.13 on
  nvdla_s at 250x260) only a small minority of bins ever inflated: v113/v114 logs show
  increments of 0.0019-0.0035 against a 0.005 cap, i.e. ~0.2% of movable area regardless of the
  cap. The router map it acts on correlates .84 H / .91 V (Spearman) with Innovus.
- **ADMM route gradients contribute ~1%.** On regression_s14, `thr08_g035` s1001 with ADMM
  versus without: -0.7% WL, -1.5% H, -0.6% V, for 4.5x the router calls and 1.7x the runtime.
  Consistent with the v113/v114 nulls.
- **The schedule contributes ~1/10 of the H gain and none of the V gain** (see the
  schedule-matched reference above).
- Lever ordering, confirmed across v114/v115: inflation budget and threshold >> schedule >
  ADMM weights; density and area cap were null (the cap never bound).

### Caveats

- **Two seeds per point.** Seed spreads are under 3% on nvdla_s but reach 8% in H on
  regression_s14 - larger than several of the config effects being compared. The dp_rudy
  reference needed a third seed (1003) before its bar was trustworthy.
- **The dp_rudy points above +6% WL are mostly unconverged** at the 1000-iteration cap
  (`rudy020` overflow 0.31-0.35; `rudy025` s1001 likewise), so the high-WL end of the RUDY
  frontier is optimistic for RUDY in WL and pessimistic in congestion.
- **The two inflation methods have different area bases** and cannot be netted: RUPlace
  reports a cumulative inflated area (10-28%), RUDY a per-round ratio (~1.45).
- Inflation is ratio-limited, not budget-limited, in the v115 runs (`max_inflate_ratio` 2.0
  binds at thr <= 0.6); the v118 rows raise it to 3.0.
- The ADMM guards added in `cmake/xplace_gpugr_s14_fidelity.patch` skip stale route records on
  ripped-up nets (~9% on nvdla_s), so nvdla_s ADMM gradients can differ slightly from the
  pre-fix v115 runs. The v119 post-fix spot check reproduced v115 within each config's own seed
  spread (thr08_g035 4,535,773/33,381/14,661 -> 4,532,864/33,166/14,470; thr06_g070_w1
  4,608,371/25,696/12,525 -> 4,611,977/25,466/12,131), so the v115 and v118 tables stand.
- DREAMPlace writes back only the cells it loaded and drops physical-only cells (fill, tap,
  antenna: 85,158 of 354,555 COMPONENTS on nvdla_s_s14), so EGR sees slightly less occupied
  area than the shipped floorplan implies. This is uniform across every method compared here.

## 5. Exact flag sets for the recommended configs

Both recommendations share the same base. The order matters: `config_flags` is emitted last so
argparse takes the override.

```bash
common=(--case-manifest configs/ruplace_s14_cases.json --iterations 1000 --gpu 0 --num-threads 16 \
        --learning-rate 0.010 --xplace-root "$XPLACE_ROOT" --ruplace-router-backend gpugr \
        --ruplace-global-cluster-mode none --eval-route-rrr-iters 1 --ruplace-external-route-eval 0 \
        --ruplace-allow-shrink 1 --legalize-flag 1 --continue-on-error)

ruplace_t10=(--gp-gamma 0.92 --target-density 1.0 --gp-noise-ratio 0.030 \
  --ruplace-global-util-exponent 0.745 --ruplace-inflate-area-cap 0.005 \
  --ruplace-inflate-start-overflow 0.30 --ruplace-global-inflate-gamma 0.35 \
  --ruplace-admm-start-overflow 0.33 --ruplace-admm-route-freq 50 --ruplace-admm-apply-freq 5 \
  --ruplace-admm-weight 0.03 --ruplace-admm-anchor-weight 0.10 \
  --ruplace-local-inflate-max-rounds 1 --ruplace-local-inflate-gamma 0.05 --route-rrr-iters 1)

# Decided s14 in-loop GR settings: 5 Innovus row-height gcells = 2880 dbu.
s14_gr=(--ruplace-gr-grid step:2880 --ruplace-gr-util-mode avail --ruplace-gr-wire-cost-sat 1 \
  --ruplace-gr-m1-routable 0 --ruplace-gr-max-route-len-per-pin 256 --ruplace-gr-via-usage-scale 0 \
  --ruplace-write-guides 0 --route-rrr-iters 1 --ruplace-external-route-eval 0 \
  --ruplace-router-backend gpugr)

# Identical in v115, v116, v118 and v119.
base=(--stop-overflow 0.10 --ruplace-admm-start-overflow 0.55 \
  --ruplace-admm-route-freq 25 --ruplace-admm-apply-freq 5 \
  --ruplace-inflate-area-cap 0.15 --ruplace-local-inflate-max-rounds 3 \
  --ruplace-hv-inflate-gamma 0.5 --ruplace-hv-inflate-mode max --ruplace-inflate-start-overflow 0.5)
```

nvdla_s_s14, `thr06_g070`:

```bash
cfg_flags=(--ruplace-inflate-util-threshold 0.6 --ruplace-global-inflate-gamma 0.70)
python3 tools/ruplace_quality.py --run-id s14_nvdla_s_s14_thr06_g070_s1001 \
  --designs nvdla_s_s14 --methods ruplace --random-seed 1001 \
  "${ruplace_t10[@]}" "${s14_gr[@]}" "${base[@]}" "${cfg_flags[@]}" "${common[@]}"
```

regression_s14, `thr08_g025`:

```bash
cfg_flags=(--ruplace-inflate-util-threshold 0.8 --ruplace-global-inflate-gamma 0.25)
python3 tools/ruplace_quality.py --run-id s14_regression_s14_thr08_g025_s1001 \
  --designs regression_s14 --methods ruplace --random-seed 1001 \
  "${ruplace_t10[@]}" "${s14_gr[@]}" "${base[@]}" "${cfg_flags[@]}" "${common[@]}"
```

The reference runs use `--methods dp_hpwl` or `dp_rudy` with `ruplace_t10` + `s14_gr` +
`common` only - never the RUPlace `base` array, which carries inflation and ADMM flags that
must not be attached to a baseline.

## 6. How to run

### 6.1 Minimal enablement (v120 and later)

`dreamplace/params.json` now ships this campaign's `thr06_g070` settings as the
default of every `ruplace_*` key, and `dreamplace/Params.py` applies the
matching global keys when `ruplace_flag` is set. Enabling RUPlace is therefore
two switches in an otherwise plain LEF/DEF config:

```json
{
  "lef_input": ["tech.lef", "stdcells.lef"],
  "def_input": "design.def",
  "routability_opt_flag": 1,
  "ruplace_flag": 1
}
```

The preset fills in `target_density 1.0`, `gamma 0.92`, `gp_noise_ratio 0.03`,
`stop_overflow 0.10`, `legalize_flag 1`, `num_bins_x/y 512` and one
1000-iteration `nesterov` global-place stage for any of those keys the config
does not set. Values in the config always win; each applied override is logged
at INFO; `"ruplace_preset": "none"` disables the step; nothing happens when
`ruplace_flag` is 0. Section 5's flag arrays are the equivalent explicit form
and remain valid.

The `balanced` alternative from section 4 is now two overrides on top of the
default:

```json
{ "ruplace_inflate_util_threshold": 0.8, "ruplace_global_inflate_gamma": 0.25 }
```

Three preset keys are technology-dependent and must be retuned outside SMIC14:

| Key | s14 default | Why |
| --- | --- | --- |
| `ruplace_gr_grid` | `step:2880` | 2880 dbu = 5 SMIC14 row heights per GR gcell |
| `ruplace_gr_m1_routable` | `0` | M1 is not a routing layer on SMIC14 |
| `ruplace_gr_max_route_len_per_pin` | `256` | suits that coarse gcell grid; 130 is the ISPD18 calibration |

`tools/ruplace_quality.py` reads its `--ruplace-*` argparse defaults straight
out of `dreamplace/params.json`, so the driver and the preset cannot drift
apart; explicit flags still override. Running the driver with no `--ruplace-*`
flag reproduces the `thr06_g070` config byte for byte apart from `random_seed`,
`num_threads` and `result_dir`.

### 6.2 Reproducing the published numbers from a fresh clone

```bash
git clone -b feat/ruplace-s14-innovus <repo> repro_clone
cd repro_clone && git submodule update --init
# build per README_RUPLACE.md "Build": cmake with gcc-9/g++-9, CUDA 11.8,
# CMAKE_CUDA_ARCHITECTURES=7.5, CMAKE_CXX_ABI=0, then make -j16 && make install

# minimal config: LEF/DEF + result_dir + gpu/num_threads/random_seed + the two switches
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$CONDA_PREFIX/targets/x86_64-linux/lib"
unset CDS_LIC_FILE LM_LICENSE_FILE
cd install && python dreamplace/Placer.py ../test/ruplace/nvdla_s_repro.json
```

The log must show the `RUPlace preset 'congestion': ...` lines, ~15-18
`RUPlace GR: call N` in-loop router evaluations and a legalization step. Score
the resulting DEF with `tools/ruplace_s14_innovus_eval.sh` (below).

Reference, `nvdla_s_s14` seed 1001, v115 `thr06_g070`, Innovus EGR `global`:
WL 4,602,377 / H 25,844 / V 12,660.

Reproduction is **within seed noise, not bit-exact**: `deterministic_flag` is 0
in every published run, so a same-seed GPU rerun already moves by around 1%, and
the published medians use seeds 1001 and 1002. Expect agreement within about
1-3% per metric. `random_seed` is deliberately left out of the preset.

### 6.3 Campaign drivers

```bash
set +u; source ~/miniconda3/etc/profile.d/conda.sh; conda activate placement; set -u

# 1. Stage a private s14 case into data/s14/ (idempotent; a few minutes).
python tools/ruplace_s14_prep.py --case nvdla_s_s14      # or --all

# 2. Run a batch. The v119 driver is the most recent shape: work items are
#    case:config:seed, two placement workers, Innovus scoring drained by a
#    bounded background queue, resumable.
bash run_ruplace_v119_s14_band_local.sh
ITEMS="regression_s14:thr08_g025:1001" bash run_ruplace_v119_s14_band_local.sh   # subset

# 3. Score any single DEF with Innovus EGR (one CSV line on stdout).
tools/ruplace_s14_innovus_eval.sh nvdla_s_s14 <placed.def> <out_dir> global
```

Two environment rules the drivers encode and that a hand-run must repeat:

- Never export `CDS_LIC_FILE` or `LM_LICENSE_FILE`. The docker launcher licenses from the
  license file with `CDS_LIC_ONLY=1`; a host value clobbers the file path and the checkout
  fails.
- `LD_LIBRARY_PATH` must not contain an external Xplace `cpp_to_py`/`cpybin`/`build`
  directory. Those shadow the bundled `libxplace_common.so` and segfault the in-loop router in
  `GRDatabase::addMovObs`.

Build with the cmake invocation in README_RUPLACE.md (CUDA 11.8, gcc-9,
`CMAKE_CUDA_ARCHITECTURES 7.5`, `CMAKE_CXX_ABI 0`).
Configure prints three "XplaceGPUGR ... already present" lines: the vendored router in
`thirdparty/XplaceGPUGR` already carries the patches in `cmake/`, and CMake verifies rather
than applies them. After editing anything under `dreamplace/ops/`, rebuild and reinstall - the
running code is the copy in `install/`, not the source.
