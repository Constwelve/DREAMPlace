#!/usr/bin/env python3
"""RUPlace A0 calibration harness: GPUGR global route vs Cadence Innovus earlyGlobalRoute.

Runs both routers on the same DEF and the same gcell grid, then reports how well the
GPU router's congestion picture agrees with the sign-off tool's:

  (a) Innovus EGR with ``dumpCongestArea -all``  -> per-gcell remain/total tracks, H and V
  (b) GPUGR on the SAME uniform grid, ``--dump-maps``  -> per-layer demand/capacity tensors
  (c) rank correlation, overflow-set agreement, top-k IoU, wirelength ratio, runtimes

Every stage is skip-if-exists, so re-running only redoes what is missing.

Usage:
  tools/ruplace_gr_calibrate.py --case nvdla_s_s14 --def <placed.def> --tag <tag> \
      [--route-x-size N --route-y-size N] [--rrr-iters 1] [--gr-param key=value ...]
"""

import argparse
import csv
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time

import numpy as np

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "/mnt/nvme0n1/yifan/projs/DREAMPlace"

# Pass thresholds for the A0 acceptance gate.
THRESHOLDS = {
    "spearman_min": 0.60,
    "top2pct_iou_min": 0.30,
    "wl_ratio_lo": 0.95,
    "wl_ratio_hi": 1.15,
    "run_ggr_max_sec": 60.0,
}


def log(msg, *a):
    logging.info(msg, *a)


# --------------------------------------------------------------------------- meta / DEF


def load_meta(case):
    path = os.path.join(REPO, "data", "s14", "%s.meta.json" % case)
    if not os.path.isfile(path):
        raise SystemExit("missing case meta: %s" % path)
    with open(path) as fh:
        return json.load(fh)


def read_die_area(def_path):
    """Return (lx, ly, hx, hy) in dbu from the DEF DIEAREA line (scanned from the head)."""
    pat = re.compile(r"^DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    with open(def_path) as fh:
        for _ in range(2000):
            line = fh.readline()
            if not line:
                break
            m = pat.match(line.strip())
            if m:
                return tuple(int(v) for v in m.groups())
    raise SystemExit("no DIEAREA found in %s" % def_path)


def nonempty(path, min_bytes=1):
    return os.path.isfile(path) and os.path.getsize(path) >= min_bytes


# --------------------------------------------------------------------------- (a) Innovus

def run_innovus(case, def_path, out_dir):
    """Run the Innovus EGR wrapper with the congestion-area dump enabled. Idempotent."""
    dump = os.path.join(out_dir, "innovus_congest_area.txt")
    if nonempty(dump, 1024):
        log("skip innovus: %s exists (%.1f MB)", dump, os.path.getsize(dump) / 1e6)
        return dump, 0.0
    os.makedirs(out_dir, exist_ok=True)
    cmd = [os.path.join(WT, "tools", "ruplace_s14_innovus_eval.sh"), case, def_path, out_dir, "global"]
    log("innovus: %s", " ".join(shlex.quote(c) for c in cmd))
    env = dict(os.environ, DUMP_CONGEST="1")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=WT, capture_output=True, text=True)
    elapsed = time.time() - t0
    log("innovus: rc=%s %.1f s | %s", proc.returncode, elapsed, (proc.stdout or "").strip().splitlines()[-1:] or "")
    if not nonempty(dump, 1024):
        raise SystemExit("Innovus produced no congestion dump at %s\nstderr:\n%s" % (dump, proc.stderr[-4000:]))
    return dump, elapsed


DUMP_ROW = re.compile(
    r"\((-?\d+),\s*(-?\d+)\)\s*\((-?\d+),\s*(-?\d+)\)\s*"
    r"V:\s*(-?\d+)/(-?\d+)\s*H:\s*(-?\d+)/(-?\d+)"
)


def parse_congest_dump(path):
    """Parse ``dumpCongestArea -all`` into a uniform grid.

    Returns a dict with nx, ny, step_x, step_y, x0, y0 and (nx, ny) int arrays
    h_remain/h_total/v_remain/v_total.  Note the ``-?`` on remain: overflowed gcells
    report a negative remaining track count and must not be dropped.
    """
    with open(path) as fh:
        text = fh.read()
    rows = DUMP_ROW.findall(text)
    if not rows:
        raise SystemExit("no data rows parsed from %s" % path)
    arr = np.asarray(rows, dtype=np.int64)  # [N, 8]
    x1, y1, x2, y2 = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]

    xs = np.unique(x1)
    ys = np.unique(y1)
    nx, ny = len(xs), len(ys)
    if arr.shape[0] != nx * ny:
        raise SystemExit("dump is not a full grid: %d rows but %d x %d = %d" % (arr.shape[0], nx, ny, nx * ny))

    step_x = _uniform_step(xs, "x")
    step_y = _uniform_step(ys, "y")
    # widths must equal the step (a ragged last row/column would break index alignment)
    _assert_uniform(x2 - x1, step_x, "gcell width")
    _assert_uniform(y2 - y1, step_y, "gcell height")

    ix = (x1 - xs[0]) // step_x
    iy = (y1 - ys[0]) // step_y
    out = {"nx": int(nx), "ny": int(ny), "step_x": int(step_x), "step_y": int(step_y),
           "x0": int(xs[0]), "y0": int(ys[0]), "n_rows": int(arr.shape[0])}
    for name, col in (("v_remain", 4), ("v_total", 5), ("h_remain", 6), ("h_total", 7)):
        grid = np.zeros((nx, ny), dtype=np.int64)
        grid[ix, iy] = arr[:, col]
        out[name] = grid
    return out


def _uniform_step(coords, axis):
    if len(coords) < 2:
        raise SystemExit("only %d distinct %s coordinates in dump" % (len(coords), axis))
    d = np.diff(coords)
    if d.min() != d.max():
        raise SystemExit("non-uniform %s grid in dump: steps %d..%d" % (axis, d.min(), d.max()))
    return int(d[0])


def _assert_uniform(values, expected, what):
    if int(values.min()) != expected or int(values.max()) != expected:
        raise SystemExit("non-uniform %s: got %d..%d, expected %d" % (what, values.min(), values.max(), expected))


def downsample_dump(dump, k, allow_crop=False):
    """Aggregate the Innovus per-gcell dump over k x k blocks (RUPlace batch 2, item 4).

    Innovus reports ``remain``/``total`` tracks per gcell.  A k x k block of gcells has
    ``sum(total)`` track-slots and ``sum(remain)`` free ones, so summing both per block and
    per direction gives the coarse-grid analogue directly -- utilization stays
    ``1 - remain/total`` and overflow stays ``max(0, -remain)`` in tracks.  This lets a
    GPUGR run on a ``nx/k x ny/k`` grid be compared index-to-index against Innovus's fine
    grid, which is what the coarse-grid runtime/fidelity sweep needs.

    ``k`` must divide both grid dimensions unless ``allow_crop`` is set, in which case the
    trailing partial blocks are dropped (recorded as ``downsample_crop_{x,y}``).
    """
    k = int(k)
    if k <= 1:
        return dump
    nx, ny = int(dump["nx"]), int(dump["ny"])
    cx, cy = nx % k, ny % k
    if (cx or cy) and not allow_crop:
        raise SystemExit(
            "--innovus-downsample %d: the Innovus grid is %d x %d, which k does not divide "
            "(remainder %d x %d).  Use a k that divides both, or pass "
            "--innovus-downsample-crop to drop the trailing partial blocks." % (k, nx, ny, cx, cy))
    ox, oy = nx // k, ny // k
    if ox < 1 or oy < 1:
        raise SystemExit("--innovus-downsample %d leaves a %d x %d grid" % (k, ox, oy))
    out = dict(dump)
    out.update({"nx": ox, "ny": oy,
                "step_x": int(dump["step_x"]) * k, "step_y": int(dump["step_y"]) * k,
                "n_rows": ox * oy,
                "downsample_k": k, "downsample_crop_x": int(cx), "downsample_crop_y": int(cy)})
    for name in ("v_remain", "v_total", "h_remain", "h_total"):
        g = dump[name][: ox * k, : oy * k]
        out[name] = g.reshape(ox, k, oy, k).sum(axis=(1, 3))
    return out


def innovus_fields(dump):
    """Utilization / overflow(tracks) / capacity per gcell, from remain/total."""
    fields = {}
    for d in ("h", "v"):
        total = dump["%s_total" % d].astype(np.float64)
        remain = dump["%s_remain" % d].astype(np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            util = np.where(total > 0, 1.0 - remain / np.maximum(total, 1e-12), 0.0)
        fields["%s_util" % d] = util
        fields["%s_ovfl" % d] = np.maximum(0.0, -remain)
        fields["%s_cap" % d] = total
    fields["mask"] = (dump["h_total"] > 0) | (dump["v_total"] > 0)
    fields["h_mask"] = dump["h_total"] > 0
    fields["v_mask"] = dump["v_total"] > 0
    return fields


# --------------------------------------------------------------------------- (b) GPUGR

def run_gpugr(meta, def_path, out_dir, route_x, route_y, rrr_iters, gpu, gr_params):
    """Run the standalone GPUGR frontend with --dump-maps. Idempotent."""
    maps = os.path.join(out_dir, "gr_maps.pt")
    logf = os.path.join(out_dir, "gpugr.log")
    if nonempty(maps, 1024):
        log("skip gpugr: %s exists", maps)
        return maps, logf
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, "-m", "dreamplace.ops.gpugr.run_gpugr", "--backend", "gpugr",
           "--design-name", meta["top_cell"], "--def-input", def_path,
           "--output", os.path.join(out_dir, "ggr.pt"), "--dump-maps", maps,
           "--route-x-size", str(route_x), "--route-y-size", str(route_y),
           "--rrr-iters", str(rrr_iters), "--gpu", str(gpu)]
    for lef in meta["lef_input"]:
        cmd += ["--lef-input", lef]
    cmd += gr_params
    install = os.path.join(WT, "install")
    log("gpugr: (cwd=%s) %s", install, " ".join(shlex.quote(c) for c in cmd))
    log("gpugr: log -> %s", logf)
    t0 = time.time()
    with open(logf, "w") as fh:
        fh.write("# %s\n" % " ".join(shlex.quote(c) for c in cmd))
        fh.flush()
        rc = subprocess.call(cmd, cwd=install, stdout=fh, stderr=subprocess.STDOUT)
    log("gpugr: rc=%s wall %.1f s", rc, time.time() - t0)
    if not nonempty(maps, 1024):
        raise SystemExit("GPUGR produced no map dump at %s (rc=%s, see %s)" % (maps, rc, logf))
    return maps, logf


def gpugr_fields(maps_path):
    """Aggregate the per-layer GPUGR tensors into H/V utilization, overflow and capacity.

    Layer 0 (M1) is excluded exactly as the in-loop code does (``all_start = 1``); the
    H/V layer strides come straight from the dump, which recorded the values the router
    itself derived from ``m1direction``.
    """
    import torch

    d = torch.load(maps_path, map_location="cpu")
    dmd, cap = d["dmd_map"].double(), d["cap_map"].double()
    h_id, v_id, all_start = int(d["h_id"]), int(d["v_id"]), int(d["all_start"])
    if h_id < all_start or v_id < all_start:
        raise SystemExit("unexpected layer ids h=%d v=%d with all_start=%d" % (h_id, v_id, all_start))
    out = {"raw": d}
    for name, start in (("h", h_id), ("v", v_id)):
        dsum = dmd[start::2].sum(dim=0).numpy()
        csum = cap[start::2].sum(dim=0).numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            util = np.where(csum > 0, dsum / np.maximum(csum, 1e-12), 0.0)
        util = np.nan_to_num(util, nan=0.0, posinf=0.0, neginf=0.0)
        out["%s_util" % name] = util
        out["%s_cap" % name] = csum
        out["%s_dmd" % name] = dsum
        # overflow in tracks, so it is on the same scale as Innovus's remain deficit
        out["%s_ovfl" % name] = np.maximum(util - 1.0, 0.0) * csum
    return out


# --------------------------------------------------------------------------- (d) metrics

def pearson(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.size < 2 or a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman(a, b):
    from scipy.stats import rankdata

    return pearson(rankdata(a), rankdata(b))


def set_agreement(pred, ref):
    """precision / recall / IoU of two boolean gcell sets."""
    tp = int(np.count_nonzero(pred & ref))
    npred, nref = int(np.count_nonzero(pred)), int(np.count_nonzero(ref))
    union = npred + nref - tp
    return {"n_pred": npred, "n_ref": nref, "tp": tp,
            "precision": tp / npred if npred else float("nan"),
            "recall": tp / nref if nref else float("nan"),
            "iou": tp / union if union else float("nan")}


def topk_iou(pred_ovfl, pred_util, ref_ovfl, ref_util, frac):
    """IoU of the worst-`frac` gcells under each tool, ranked by overflow, ties by utilization."""
    k = max(1, int(round(frac * pred_ovfl.size)))
    a = _top_indices(pred_ovfl, pred_util, k)
    b = _top_indices(ref_ovfl, ref_util, k)
    inter = len(a & b)
    return {"k": k, "iou": inter / len(a | b) if (a | b) else float("nan")}


def _top_indices(primary, secondary, k):
    order = np.lexsort((-secondary, -primary))
    return set(order[:k].tolist())


def direction_metrics(gp, iv, mask, d):
    """All per-direction metrics, restricted to gcells Innovus reports capacity for."""
    gu, iu = gp["%s_util" % d][mask], iv["%s_util" % d][mask]
    go, io = gp["%s_ovfl" % d][mask], iv["%s_ovfl" % d][mask]
    m = {
        "n_gcells": int(mask.sum()),
        "pearson_util": pearson(gu, iu),
        "spearman_util": spearman(gu, iu),
        "gpugr_util_mean": float(gu.mean()), "innovus_util_mean": float(iu.mean()),
        "gpugr_util_p99": float(np.percentile(gu, 99)), "innovus_util_p99": float(np.percentile(iu, 99)),
        "gpugr_ovfl_tracks": float(go.sum()), "innovus_ovfl_tracks": float(io.sum()),
        "gpugr_ovfl_gcells": int((go > 0).sum()), "innovus_ovfl_gcells": int((io > 0).sum()),
        # cap-magnitude diagnostic: absolute overflow-track sums only mean something if
        # the two tools count capacity on the same scale.
        "gpugr_cap_mean": float(gp["%s_cap" % d][mask].mean()),
        "innovus_cap_mean": float(iv["%s_cap" % d][mask].mean()),
    }
    m["cap_ratio"] = m["gpugr_cap_mean"] / m["innovus_cap_mean"] if m["innovus_cap_mean"] else float("nan")
    m["ovfl_bin"] = set_agreement(go > 0, io > 0)
    for frac in (0.01, 0.02, 0.05):
        m["top%.1fpct_iou" % (frac * 100)] = topk_iou(go, gu, io, iu, frac)["iou"]
    return m


PITCH_TOL = 0.005  # 0.5%: max gpugr-vs-Innovus gcell pitch ratio error


def check_grid_alignment(raw, dump, tol_dbu):
    """Compare GPUGR gridlines against the Innovus dump coordinates.

    Shape mismatch is fatal (the whole comparison is index-to-index).  A constant small
    offset is not: Innovus snaps its gcell grid to the track origin while GRDatabase
    starts its uniform gridlines at 0, so a sub-gcell shift is expected and harmless.
    """
    gx = np.asarray(raw.get("gridlines_x") or [], dtype=np.int64)
    gy = np.asarray(raw.get("gridlines_y") or [], dtype=np.int64)
    info = {"gpugr_x_size": raw.get("x_size"), "gpugr_y_size": raw.get("y_size"),
            "innovus_nx": dump["nx"], "innovus_ny": dump["ny"],
            "tol_dbu": tol_dbu, "warnings": []}
    if int(raw.get("x_size") or 0) != dump["nx"] or int(raw.get("y_size") or 0) != dump["ny"]:
        raise SystemExit("grid shape mismatch: gpugr %sx%s vs innovus %dx%d"
                         % (raw.get("x_size"), raw.get("y_size"), dump["nx"], dump["ny"]))
    for axis, gl, n, x0, step in (("x", gx, dump["nx"], dump["x0"], dump["step_x"]),
                                  ("y", gy, dump["ny"], dump["y0"], dump["step_y"])):
        if gl.size != n + 1:
            info["warnings"].append("%s gridlines has %d entries, expected %d" % (axis, gl.size, n + 1))
            continue
        ref = x0 + step * np.arange(n + 1, dtype=np.int64)
        off = gl - ref
        info["grid_%s_offset_dbu" % axis] = int(np.abs(off).max())
        info["grid_%s_offset_constant" % axis] = bool(off.min() == off.max())
        # RUPlace batch 3a: on a die whose span is not an integer multiple of the Innovus
        # gcell (regression_s14: 799200 / 576 = 1387.5), no integer grid can align exactly.
        # GRDatabase always tiles [0, span] uniformly, so its pitch differs from the dump
        # pitch by a fixed ratio and the absolute offset drifts linearly to a large value at
        # the far edge.  Judge the *pitch*, not the absolute offset: a pitch ratio within
        # PITCH_TOL means the two grids describe the same physical gcells to within a small
        # fraction of one gcell on average, which keeps the index-to-index comparison
        # meaningful; anything larger is a real grid mismatch and stays fatal.
        gl_pitch = float(gl[-1] - gl[0]) / max(n, 1)
        info["grid_%s_pitch_gpugr" % axis] = gl_pitch
        info["grid_%s_pitch_innovus" % axis] = int(step)
        info["grid_%s_pitch_ratio" % axis] = gl_pitch / step if step else float("nan")
        if np.abs(off).max() > tol_dbu:
            pitch_err = abs(gl_pitch / step - 1.0) if step else float("inf")
            if pitch_err > PITCH_TOL:
                raise SystemExit(
                    "grid %s pitch mismatch: gpugr %.2f dbu vs innovus %d dbu (%.3f%% > %.3f%%), "
                    "max offset %d dbu"
                    % (axis, gl_pitch, step, 100.0 * pitch_err, 100.0 * PITCH_TOL,
                       np.abs(off).max()))
            info["warnings"].append(
                "%s gridlines offset by up to %d dbu (%.1f%% of step %d), pitch %.2f vs %d dbu "
                "(%.3f%%) -- Innovus snaps gcells to the track origin and the die span is not an "
                "integer multiple of the gcell, so a linear drift is structural"
                % (axis, np.abs(off).max(), 100.0 * np.abs(off).max() / step, step,
                   gl_pitch, step, 100.0 * pitch_err))
    for w in info["warnings"]:
        logging.warning("grid alignment: %s", w)
    return info


# --------------------------------------------------------------------------- reporting

def wire_only_fields(raw):
    """Same H/V aggregation as gpugr_fields but from wire_dmd_map, i.e. excluding via demand.

    Innovus's remain/total counts wire tracks, so this says how much of GPUGR's congestion
    signal comes from vias -- which the sign-off numbers do not count the same way.
    """
    import torch

    wd, cp = raw["wire_dmd_map"].double(), raw["cap_map"].double()
    out = {}
    for name, start in (("h", int(raw["h_id"])), ("v", int(raw["v_id"]))):
        dsum = wd[start::2].sum(dim=0).numpy()
        csum = cp[start::2].sum(dim=0).numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            util = np.where(csum > 0, dsum / np.maximum(csum, 1e-12), 0.0)
        util = np.nan_to_num(util, nan=0.0, posinf=0.0, neginf=0.0)
        out["%s_util" % name] = util
        out["%s_cap" % name] = csum
        out["%s_ovfl" % name] = np.maximum(util - 1.0, 0.0) * csum
    return out


def avail_fields(raw, fixed_raw=None):
    """H/V utilization against *available* capacity, i.e. discounting blocked tracks.

    GPUGR's ``cap_map`` is the raw DEF track count per gcell; ``fixed_map`` is the part of
    it consumed by fixed obstacles (macro/pin/blockage/SNet shapes).  ``wire_dmd_map``
    already includes ``fixed``, so the routed-wire-only demand is ``wire_dmd - fixed``.
    Innovus's remain/total is reported after blockages, so ``(wire_dmd - fixed) /
    (cap - fixed)`` is the closer analogue.  Returns None if no fixed map is available.

    ``fixed_raw`` allows borrowing the fixed map from another tag's dump: it depends only
    on the design/placement, not on any routing setting, so it is identical across tags.
    """
    fx = raw.get("fixed_map")
    if fx is None and fixed_raw is not None:
        fx = fixed_raw.get("fixed_map")
    if fx is None:
        return None
    fx = fx.double()
    wd, cp = raw["wire_dmd_map"].double(), raw["cap_map"].double()
    out = {}
    for name, start in (("h", int(raw["h_id"])), ("v", int(raw["v_id"]))):
        fsum = fx[start::2].sum(dim=0).numpy()
        dsum = wd[start::2].sum(dim=0).numpy() - fsum
        csum = cp[start::2].sum(dim=0).numpy() - fsum
        incl = wd[start::2].sum(dim=0).numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            util = np.where(csum > 0, dsum / np.maximum(csum, 1e-12), 0.0)
            util_incl = np.where(csum > 0, incl / np.maximum(csum, 1e-12), 0.0)
        util = np.nan_to_num(util, nan=0.0, posinf=0.0, neginf=0.0)
        util_incl = np.nan_to_num(util_incl, nan=0.0, posinf=0.0, neginf=0.0)
        out["%s_util" % name] = util
        out["%s_util_incl_fixed" % name] = util_incl
        out["%s_cap" % name] = csum
        out["%s_fixed" % name] = fsum
        out["%s_ovfl" % name] = np.maximum(util - 1.0, 0.0) * np.maximum(csum, 0.0)
    return out


def avail_metrics(av, iv):
    """Spearman / top-2% IoU / cap means for the `avail` utilization variant."""
    if av is None:
        return None
    res = {}
    for d in ("h", "v"):
        mask = iv["%s_mask" % d]
        au, ao = av["%s_util" % d][mask], av["%s_ovfl" % d][mask]
        res[d] = {
            "util_mean": float(au.mean()),
            "spearman_util": spearman(au, iv["%s_util" % d][mask]),
            "pearson_util": pearson(au, iv["%s_util" % d][mask]),
            "top2.0pct_iou": topk_iou(ao, au, iv["%s_ovfl" % d][mask], iv["%s_util" % d][mask], 0.02)["iou"],
            "top1.0pct_iou": topk_iou(ao, au, iv["%s_ovfl" % d][mask], iv["%s_util" % d][mask], 0.01)["iou"],
            "ovfl_tracks": float(ao.sum()),
            "ovfl_gcells": int((ao > 0).sum()),
            "cap_avail_mean": float(av["%s_cap" % d][mask].mean()),
            "fixed_mean": float(av["%s_fixed" % d][mask].mean()),
            "innovus_cap_mean": float(iv["%s_cap" % d][mask].mean()),
            # same denominator, but demand still includes the fixed usage (the literal
            # wire_dmd/(cap-fixed) reading) -- kept as a cross-check
            "spearman_util_incl_fixed": spearman(av["%s_util_incl_fixed" % d][mask],
                                                 iv["%s_util" % d][mask]),
        }
        res[d]["cap_avail_ratio"] = (res[d]["cap_avail_mean"] / res[d]["innovus_cap_mean"]
                                     if res[d]["innovus_cap_mean"] else float("nan"))
    return res


def diagnostics(gp, iv, raw):
    """Cheap checks that say whether a weak correlation is a real modelling gap or a harness bug.

    hv_swap:   Spearman for all four (gpugr dir, innovus dir) pairings.  If the diagonal does
               not dominate, the H/V layer mapping is wrong and nothing else here is meaningful.
    wire_only: the same metrics computed from wire demand alone, isolating via demand's share.
    """
    swap = {}
    for gd in ("h", "v"):
        for idd in ("h", "v"):
            mask = iv["%s_mask" % idd]
            swap["gpugr_%s_vs_innovus_%s" % (gd, idd)] = spearman(gp["%s_util" % gd][mask],
                                                                  iv["%s_util" % idd][mask])
    diag = swap["gpugr_h_vs_innovus_h"] + swap["gpugr_v_vs_innovus_v"]
    off = swap["gpugr_h_vs_innovus_v"] + swap["gpugr_v_vs_innovus_h"]
    # The mapping question is binary: is the unswapped pairing better than the swapped one?
    # (Per-cell dominance is a stricter, noisier test kept alongside it as a weak-channel hint.)
    swap_would_improve = bool(off > diag)
    diagonal_dominates = all(swap["gpugr_%s_vs_innovus_%s" % (d, d)] > swap["gpugr_%s_vs_innovus_%s" % (d, o)]
                             and swap["gpugr_%s_vs_innovus_%s" % (d, d)] > swap["gpugr_%s_vs_innovus_%s" % (o, d)]
                             for d, o in (("h", "v"), ("v", "h")))
    wire = wire_only_fields(raw)
    wm = {}
    for d in ("h", "v"):
        mask = iv["%s_mask" % d]
        wu, wo = wire["%s_util" % d][mask], wire["%s_ovfl" % d][mask]
        wm[d] = {
            "util_mean": float(wu.mean()),
            "spearman_util": spearman(wu, iv["%s_util" % d][mask]),
            "ovfl_tracks": float(wo.sum()),
            "top2.0pct_iou": topk_iou(wo, wu, iv["%s_ovfl" % d][mask], iv["%s_util" % d][mask], 0.02)["iou"],
        }
    return {"hv_swap_spearman": swap, "hv_swap_would_improve": swap_would_improve,
            "hv_diag_sum": diag, "hv_offdiag_sum": off,
            "hv_diagonal_dominates_cellwise": bool(diagonal_dominates), "wire_only": wm}


def evaluate_gates(res):
    t = THRESHOLDS
    gates = []
    for d in ("h", "v"):
        gates.append(("spearman_%s >= %.2f" % (d, t["spearman_min"]),
                      res[d]["spearman_util"], res[d]["spearman_util"] >= t["spearman_min"]))
    for d in ("h", "v"):
        gates.append(("top2pct_iou_%s >= %.2f" % (d, t["top2pct_iou_min"]),
                      res[d]["top2.0pct_iou"], res[d]["top2.0pct_iou"] >= t["top2pct_iou_min"]))
    wl = res["wirelength"]["ratio"]
    gates.append(("wl_ratio in [%.2f, %.2f]" % (t["wl_ratio_lo"], t["wl_ratio_hi"]),
                  wl, t["wl_ratio_lo"] <= wl <= t["wl_ratio_hi"]))
    rg = res["runtime"]["gpugr_run_ggr_sec"]
    gates.append(("gpugr run_ggr <= %.0f s" % t["run_ggr_max_sec"], rg, rg <= t["run_ggr_max_sec"]))
    return [{"criterion": c, "value": None if v is None else float(v), "pass": bool(p)} for c, v, p in gates]


def print_summary(res):
    w = print
    w("")
    w("=" * 78)
    w("RUPlace A0 GR calibration -- case=%s tag=%s" % (res["case"], res["tag"]))
    w("=" * 78)
    g = res["grid"]
    w("grid        innovus %d x %d step (%d, %d) dbu origin (%d, %d) | gpugr %s x %s"
      % (g["innovus_nx"], g["innovus_ny"], res["innovus_grid"]["step_x"], res["innovus_grid"]["step_y"],
         res["innovus_grid"]["x0"], res["innovus_grid"]["y0"], g["gpugr_x_size"], g["gpugr_y_size"]))
    w("            offset x=%s dbu y=%s dbu (constant: x=%s y=%s)"
      % (g.get("grid_x_offset_dbu"), g.get("grid_y_offset_dbu"),
         g.get("grid_x_offset_constant"), g.get("grid_y_offset_constant")))
    for warn in g["warnings"]:
        w("  WARN      %s" % warn)
    w("")
    hdr = ("metric", "H", "V")
    rows = [
        ("gcells compared", "%d", "n_gcells"),
        ("pearson  (util)", "%.4f", "pearson_util"),
        ("spearman (util)", "%.4f", "spearman_util"),
        ("gpugr util mean", "%.4f", "gpugr_util_mean"),
        ("innovus util mean", "%.4f", "innovus_util_mean"),
        ("gpugr util p99", "%.4f", "gpugr_util_p99"),
        ("innovus util p99", "%.4f", "innovus_util_p99"),
        ("gpugr cap mean (tracks)", "%.2f", "gpugr_cap_mean"),
        ("innovus cap mean (tracks)", "%.2f", "innovus_cap_mean"),
        ("cap ratio gpugr/innovus", "%.3f", "cap_ratio"),
        ("gpugr ovfl gcells", "%d", "gpugr_ovfl_gcells"),
        ("innovus ovfl gcells", "%d", "innovus_ovfl_gcells"),
        ("gpugr ovfl tracks (sum)", "%.1f", "gpugr_ovfl_tracks"),
        ("innovus ovfl tracks (sum)", "%.1f", "innovus_ovfl_tracks"),
        ("top-1% IoU", "%.4f", "top1.0pct_iou"),
        ("top-2% IoU", "%.4f", "top2.0pct_iou"),
        ("top-5% IoU", "%.4f", "top5.0pct_iou"),
    ]
    w("%-28s %14s %14s" % hdr)
    w("-" * 60)
    for label, fmt, key in rows:
        w("%-28s %14s %14s" % (label, fmt % res["h"][key], fmt % res["v"][key]))
    w("%-28s %14s %14s" % ("ovfl-bin precision", "%.4f" % res["h"]["ovfl_bin"]["precision"],
                           "%.4f" % res["v"]["ovfl_bin"]["precision"]))
    w("%-28s %14s %14s" % ("ovfl-bin recall", "%.4f" % res["h"]["ovfl_bin"]["recall"],
                           "%.4f" % res["v"]["ovfl_bin"]["recall"]))
    w("%-28s %14s %14s" % ("ovfl-bin IoU", "%.4f" % res["h"]["ovfl_bin"]["iou"],
                           "%.4f" % res["v"]["ovfl_bin"]["iou"]))
    w("")
    wl = res["wirelength"]
    w("wirelength  gpugr %.1f um (%.0f gcell steps x %d dbu) | innovus %.1f um | ratio %.4f"
      % (wl["gpugr_um"], wl["gpugr_wl_steps"], wl["step_dbu"], wl["innovus_um"], wl["ratio"]))
    w("vias        gpugr %.0f | innovus %s" % (wl["gpugr_vias"], wl["innovus_vias"]))
    rt = res["runtime"]
    w("runtime     gpugr total %.1f s (parse %.1f, create_grdb %.1f, run_ggr %.1f) | innovus %.1f s"
      % (rt["gpugr_total_sec"], rt["gpugr_parse_sec"], rt["gpugr_create_grdatabase_sec"],
         rt["gpugr_run_ggr_sec"], rt["innovus_sec"]))
    w("gpugr       num_ovfl_nets %d | 'failed' log lines %d | route %dx%d rrr=%d"
      % (res["gpugr"]["num_ovfl_nets"], res["gpugr"]["failed_log_lines"],
         res["gpugr"]["route_x_size"], res["gpugr"]["route_y_size"], res["gpugr"]["rrr_iters"]))
    w("gpu at start: %s" % res["gpu_state"])
    w("")
    dg = res["diagnostics"]
    w("H/V mapping  swap would improve: %s (diag %.3f vs off-diag %.3f) | cellwise dominance: %s"
      % (dg["hv_swap_would_improve"], dg["hv_diag_sum"], dg["hv_offdiag_sum"],
         dg["hv_diagonal_dominates_cellwise"]))
    w("             spearman %s"
      % " ".join("%s=%.3f" % (k.replace("gpugr_", "g").replace("_vs_innovus_", "/i"), v)
                 for k, v in sorted(dg["hv_swap_spearman"].items())))
    for d in ("h", "v"):
        wo = dg["wire_only"][d]
        w("wire-only %s  util mean %.4f  spearman %.4f  top-2%% IoU %.4f  ovfl tracks %.0f  (vs dmd: %.4f / %.4f / %.0f)"
          % (d.upper(), wo["util_mean"], wo["spearman_util"], wo["top2.0pct_iou"], wo["ovfl_tracks"],
             res[d]["spearman_util"], res[d]["top2.0pct_iou"], res[d]["gpugr_ovfl_tracks"]))
    av = res.get("avail")
    if av:
        w("")
        for d in ("h", "v"):
            a = av[d]
            w("avail %s     util mean %.4f  spearman %.4f  top-2%% IoU %.4f  cap-avail mean %.2f "
              "(fixed %.2f, innovus %.2f, ratio %.3f)  ovfl gcells %d"
              % (d.upper(), a["util_mean"], a["spearman_util"], a["top2.0pct_iou"],
                 a["cap_avail_mean"], a["fixed_mean"], a["innovus_cap_mean"],
                 a["cap_avail_ratio"], a["ovfl_gcells"]))
    else:
        w("")
        w("avail        n/a (dump has no fixed_map; pass --fixed-map-from <gr_maps.pt>)")
    w("")
    w("NOTE: correlation / IoU metrics are unit-free. The absolute overflow-track sums are")
    w("      only comparable if the cap ratio above is near 1.0.")
    w("")
    w("-- PASS/FAIL --")
    for gate in res["gates"]:
        w("  %-4s %-34s value=%.4f" % ("PASS" if gate["pass"] else "FAIL", gate["criterion"], gate["value"]))
    n_pass = sum(1 for x in res["gates"] if x["pass"])
    w("  overall: %d/%d criteria pass" % (n_pass, len(res["gates"])))
    w("=" * 78)


CSV_COLUMNS = [
    "tag", "case", "def", "route_x_size", "route_y_size", "rrr_iters",
    "nx", "ny", "step_x", "step_y", "innovus_downsample_k",
    "h_pearson", "h_spearman", "v_pearson", "v_spearman",
    "h_ovfl_iou", "v_ovfl_iou", "h_top2pct_iou", "v_top2pct_iou",
    "h_gpugr_ovfl_tracks", "h_innovus_ovfl_tracks", "v_gpugr_ovfl_tracks", "v_innovus_ovfl_tracks",
    "h_cap_ratio", "v_cap_ratio",
    "gpugr_wl_um", "innovus_wl_um", "wl_ratio", "gpugr_vias", "innovus_vias",
    "gpugr_total_sec", "gpugr_run_ggr_sec", "innovus_sec",
    "num_ovfl_nets", "failed_log_lines", "n_pass", "n_gates",
    # RUPlace batch 1, item 6: available-capacity (cap - fixed) utilization variant
    "h_avail_spearman", "v_avail_spearman", "h_avail_top2pct_iou", "v_avail_top2pct_iou",
    "h_cap_avail_mean", "v_cap_avail_mean", "h_avail_util_mean", "v_avail_util_mean",
]


def csv_row(res):
    h, v, wl, rt, gr = res["h"], res["v"], res["wirelength"], res["runtime"], res["gpugr"]
    nan = float("nan")
    av = res.get("avail") or {"h": {"spearman_util": nan, "top2.0pct_iou": nan,
                                    "cap_avail_mean": nan, "util_mean": nan},
                              "v": {"spearman_util": nan, "top2.0pct_iou": nan,
                                    "cap_avail_mean": nan, "util_mean": nan}}
    return {
        "tag": res["tag"], "case": res["case"], "def": res["def"],
        "route_x_size": gr["route_x_size"], "route_y_size": gr["route_y_size"], "rrr_iters": gr["rrr_iters"],
        "nx": res["innovus_grid"]["nx"], "ny": res["innovus_grid"]["ny"],
        "step_x": res["innovus_grid"]["step_x"], "step_y": res["innovus_grid"]["step_y"],
        "innovus_downsample_k": (res.get("innovus_downsample") or {}).get("k", 1),
        "h_pearson": h["pearson_util"], "h_spearman": h["spearman_util"],
        "v_pearson": v["pearson_util"], "v_spearman": v["spearman_util"],
        "h_ovfl_iou": h["ovfl_bin"]["iou"], "v_ovfl_iou": v["ovfl_bin"]["iou"],
        "h_top2pct_iou": h["top2.0pct_iou"], "v_top2pct_iou": v["top2.0pct_iou"],
        "h_gpugr_ovfl_tracks": h["gpugr_ovfl_tracks"], "h_innovus_ovfl_tracks": h["innovus_ovfl_tracks"],
        "v_gpugr_ovfl_tracks": v["gpugr_ovfl_tracks"], "v_innovus_ovfl_tracks": v["innovus_ovfl_tracks"],
        "h_cap_ratio": h["cap_ratio"], "v_cap_ratio": v["cap_ratio"],
        "gpugr_wl_um": wl["gpugr_um"], "innovus_wl_um": wl["innovus_um"], "wl_ratio": wl["ratio"],
        "gpugr_vias": wl["gpugr_vias"], "innovus_vias": wl["innovus_vias"],
        "gpugr_total_sec": rt["gpugr_total_sec"], "gpugr_run_ggr_sec": rt["gpugr_run_ggr_sec"],
        "innovus_sec": rt["innovus_sec"],
        "num_ovfl_nets": gr["num_ovfl_nets"], "failed_log_lines": gr["failed_log_lines"],
        "n_pass": sum(1 for x in res["gates"] if x["pass"]), "n_gates": len(res["gates"]),
        "h_avail_spearman": av["h"]["spearman_util"], "v_avail_spearman": av["v"]["spearman_util"],
        "h_avail_top2pct_iou": av["h"]["top2.0pct_iou"], "v_avail_top2pct_iou": av["v"]["top2.0pct_iou"],
        "h_cap_avail_mean": av["h"]["cap_avail_mean"], "v_cap_avail_mean": av["v"]["cap_avail_mean"],
        "h_avail_util_mean": av["h"]["util_mean"], "v_avail_util_mean": av["v"]["util_mean"],
    }


def append_csv(path, row):
    """Append one row, migrating the file in place if CSV_COLUMNS has grown since it was
    written (older rows keep their values; new columns are left blank)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old_rows = []
    header_ok = False
    if os.path.isfile(path):
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            header_ok = (reader.fieldnames == CSV_COLUMNS)
            if not header_ok:
                old_rows = [dict(r) for r in reader]
    if header_ok:
        with open(path, "a", newline="") as fh:
            csv.DictWriter(fh, fieldnames=CSV_COLUMNS).writerow(row)
        return
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in old_rows:
            writer.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
        writer.writerow(row)


# --------------------------------------------------------------------------- glue

def gpu_state():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"], text=True)
        return out.strip().splitlines()[0]
    except Exception as exc:
        return "unavailable (%s)" % exc


def count_failed_lines(path):
    if not os.path.isfile(path):
        return -1
    n = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if line.strip() == "failed" or line.strip().startswith("failed"):
                n += 1
    return n


def read_innovus_json(out_dir):
    path = os.path.join(out_dir, "innovus.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def choose_route_size(dump, die, args):
    """Route on the Innovus grid: nx/ny cells, which must tile the die at the dump's step."""
    nx = args.route_x_size or dump["nx"]
    ny = args.route_y_size or dump["ny"]
    lx, ly, hx, hy = die
    if not args.route_x_size and not args.route_y_size:
        if (lx, ly) != (0, 0):
            raise SystemExit("die origin is (%d, %d); GRDatabase's uniform grid always starts at 0" % (lx, ly))
        for axis, n, span, step in (("x", nx, hx, dump["step_x"]), ("y", ny, hy, dump["step_y"])):
            if span % n:
                raise SystemExit("die %s span %d is not divisible by %d gcells" % (axis, span, n))
            if span // n != step:
                raise SystemExit("die %s span %d / %d = %d != dump step %d" % (axis, span, n, span // n, step))
    return int(nx), int(ny)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="nvdla_s_s14")
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--route-x-size", type=int, default=0, help="default: the Innovus grid's nx")
    ap.add_argument("--route-y-size", type=int, default=0, help="default: the Innovus grid's ny")
    ap.add_argument("--rrr-iters", type=int, default=1)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--gr-param", action="append", default=[], metavar="KEY=VALUE",
                    help="extra flag forwarded to run_gpugr, e.g. --gr-param num-threads=16")
    ap.add_argument("--out-root", default=os.path.join(WT, "results", "gr_calib"))
    ap.add_argument("--grid-tol-dbu", type=int, default=1)
    ap.add_argument("--innovus-downsample", type=int, default=1, metavar="K",
                    help="aggregate the Innovus per-gcell remain/total over K x K blocks before "
                         "comparing, and route GPUGR on the resulting nx/K x ny/K grid "
                         "(default 1 = the native Innovus grid)")
    ap.add_argument("--innovus-downsample-crop", action="store_true",
                    help="allow --innovus-downsample K when K does not divide the grid, by "
                         "dropping the trailing partial blocks")
    ap.add_argument("--fixed-map-from", default="",
                    help="borrow fixed_map from another tag's gr_maps.pt when this tag's dump "
                         "predates the fixed_map binding (the map is routing-independent)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    def_path = os.path.abspath(args.def_path)
    if not os.path.isfile(def_path):
        raise SystemExit("no such DEF: %s" % def_path)
    meta = load_meta(args.case)
    tag_dir = os.path.join(args.out_root, args.tag)
    inn_dir, gr_dir = os.path.join(tag_dir, "innovus"), os.path.join(tag_dir, "gpugr")
    os.makedirs(tag_dir, exist_ok=True)
    gpu_at_start = gpu_state()
    log("case=%s tag=%s def=%s", args.case, args.tag, def_path)
    log("gpu at start: %s", gpu_at_start)

    # (a) Innovus
    dump_path, inn_wall = run_innovus(args.case, def_path, inn_dir)
    inn_json = read_innovus_json(inn_dir)

    # (b) parse the dump
    dump = parse_congest_dump(dump_path)
    log("innovus grid: %d x %d gcells, step (%d, %d) dbu, origin (%d, %d), %d rows",
        dump["nx"], dump["ny"], dump["step_x"], dump["step_y"], dump["x0"], dump["y0"], dump["n_rows"])
    if args.innovus_downsample > 1:
        dump = downsample_dump(dump, args.innovus_downsample, args.innovus_downsample_crop)
        log("innovus downsample k=%d -> %d x %d gcells, step (%d, %d) dbu (cropped %d x %d)",
            args.innovus_downsample, dump["nx"], dump["ny"], dump["step_x"], dump["step_y"],
            dump["downsample_crop_x"], dump["downsample_crop_y"])
    iv = innovus_fields(dump)

    # (c) GPUGR on the same grid
    die = read_die_area(def_path)
    route_x, route_y = choose_route_size(dump, die, args)
    log("die area %s dbu -> gpugr route grid %d x %d", die, route_x, route_y)
    gr_flags = []
    for kv in args.gr_param:
        key, _, val = kv.partition("=")
        gr_flags += ["--" + key.strip().lstrip("-"), val.strip()]
    maps_path, logf = run_gpugr(meta, def_path, gr_dir, route_x, route_y, args.rrr_iters, args.gpu, gr_flags)
    gp = gpugr_fields(maps_path)
    raw = gp["raw"]

    grid_info = check_grid_alignment(raw, dump, args.grid_tol_dbu)

    # (e) metrics
    timings = raw.get("timings", {}) or {}
    step_dbu = max(dump["step_x"], dump["step_y"])
    wl_steps = float(raw["report_gr_stat"]["wl_steps"])
    gpugr_um = wl_steps * step_dbu / 1000.0
    innovus_um = float(inn_json.get("metrics", {}).get("wirelength") or 0.0)
    res = {
        "case": args.case, "tag": args.tag, "def": def_path,
        "die_area_dbu": list(die), "gpu_state": gpu_at_start,
        "innovus_grid": {k: dump[k] for k in ("nx", "ny", "step_x", "step_y", "x0", "y0", "n_rows")},
        "innovus_downsample": {"k": int(args.innovus_downsample),
                               "crop_x": int(dump.get("downsample_crop_x", 0)),
                               "crop_y": int(dump.get("downsample_crop_y", 0))},
        "grid": grid_info,
        "h": direction_metrics(gp, iv, iv["h_mask"], "h"),
        "v": direction_metrics(gp, iv, iv["v_mask"], "v"),
        "wirelength": {
            "gpugr_wl_steps": wl_steps, "step_dbu": step_dbu, "gpugr_um": gpugr_um,
            "innovus_um": innovus_um,
            "ratio": gpugr_um / innovus_um if innovus_um else float("nan"),
            "gpugr_vias": float(raw["report_gr_stat"]["vias"]),
            "innovus_vias": inn_json.get("metrics", {}).get("vias"),
        },
        "runtime": {
            "gpugr_parse_sec": float(timings.get("parse_sec", 0.0)),
            "gpugr_create_grdatabase_sec": float(timings.get("create_grdatabase_sec", 0.0)),
            "gpugr_create_routeforce_sec": float(timings.get("create_routeforce_sec", 0.0)),
            "gpugr_run_ggr_sec": float(timings.get("run_ggr_sec", 0.0)),
            "gpugr_total_sec": float(sum(timings.values())),
            "innovus_sec": float(inn_json.get("runtime_sec") or inn_wall),
        },
        "gpugr": {
            "num_ovfl_nets": int(raw.get("num_ovfl_nets", -1)),
            "route_x_size": route_x, "route_y_size": route_y, "rrr_iters": args.rrr_iters,
            "failed_log_lines": count_failed_lines(logf),
            "maps": maps_path, "log": logf,
            "m1direction": raw.get("m1direction"), "h_id": raw.get("h_id"), "v_id": raw.get("v_id"),
            "n_layers": raw.get("n_layers"),
        },
        "innovus": {
            "metrics": inn_json.get("metrics", {}), "runtime_sec": inn_json.get("runtime_sec"),
            "congest_area": dump_path,
        },
        "thresholds": THRESHOLDS,
    }
    fixed_raw = None
    if args.fixed_map_from and raw.get("fixed_map") is None:
        import torch

        fixed_raw = torch.load(args.fixed_map_from, map_location="cpu")
        log("borrowing fixed_map from %s", args.fixed_map_from)
    res["avail"] = avail_metrics(avail_fields(raw, fixed_raw), iv)
    res["diagnostics"] = diagnostics(gp, iv, raw)
    res["gates"] = evaluate_gates(res)

    calib = os.path.join(tag_dir, "calib.json")
    with open(calib, "w") as fh:
        json.dump(res, fh, indent=2, sort_keys=True, default=str)
    append_csv(os.path.join(args.out_root, "%s.csv" % args.case), csv_row(res))
    print_summary(res)
    log("wrote %s", calib)
    log("appended %s", os.path.join(args.out_root, "%s.csv" % args.case))
    # A failed gate is a calibration finding, not a harness error: always exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
