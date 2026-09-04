##
# @file   innovus_proxy.py
# @brief  Innovus early-global-route (eGR) congestion map as an in-loop RUPlace signal.
#
# Phase 2 lever 1: RUPlace inflation normally consumes the GPUGR map, but the
# campaign is judged by Innovus NR-eGR overflow.  This module runs the *scoring*
# router in the loop so the placer optimizes against the same map that grades it.
#
# Cost: one ``defIn`` + ``earlyGlobalRoute`` per call -- ~60 s on nvdla_s, ~100 s
# on regression_s14 -- versus ~5-20 s for GPUGR.  It is therefore strictly
# opt-in (``ruplace_inflate_proxy``) and rate-limited
# (``ruplace_innovus_proxy_min_interval`` placement iterations).
#
# Definitions
# -----------
# Innovus ``dumpCongestArea -all`` reports, per Innovus gcell (576 dbu on
# SMIC14, x origin snapped to the track origin at 72 dbu), the *remaining* and
# *total* track counts per direction.  ``remain`` goes negative where the gcell
# is over capacity.  A router gcell covering several Innovus gcells therefore
# has ``sum(total)`` track slots and ``sum(remain)`` free ones, so
#
#     util  = 1 - sum(remain) / sum(total)          (clamped at 0)
#     ovfl  = max(0, util - 1)
#
# which is exactly the semantics of ``gr_metrics.hv_maps(..., util_mode='avail')``:
# there ``util = (dmd - fixed) / (cap - fixed)`` and ``overflow = (util-1)+``.
# Both are dimensionless ratios against the capacity that survives blockages,
# so the inflation code needs no rescaling.
#

import ctypes  # noqa: F401  (kept for symmetry with xplace_backend imports)
import errno
import fcntl
import json
import logging
import os
import re
import subprocess
import time

import numpy as np
import torch

try:
    from dreamplace.ops.gpugr.xplace_backend import RUPlaceRouteResult
except Exception:  # pragma: no cover - standalone/unit-test import without the bundle
    class RUPlaceRouteResult(object):
        def __init__(self, routeforce, overflow_map, utilization_map, hv_overflow_map,
                     metrics, hv_utilization_map=None, route_maps=None):
            self.routeforce = routeforce
            self.overflow_map = overflow_map
            self.utilization_map = utilization_map
            self.hv_overflow_map = hv_overflow_map
            self.hv_utilization_map = hv_utilization_map
            self.route_maps = route_maps
            self.metrics = metrics


# --------------------------------------------------------------------------- dump parsing

# Same row grammar as tools/ruplace_gr_calibrate.py::DUMP_ROW.  The ``-?`` on the
# remain fields is load-bearing: overflowed gcells report a negative remainder.
DUMP_ROW = re.compile(
    r"\((-?\d+),\s*(-?\d+)\)\s*\((-?\d+),\s*(-?\d+)\)\s*"
    r"V:\s*(-?\d+)/(-?\d+)\s*H:\s*(-?\d+)/(-?\d+)"
)


class InnovusDumpError(RuntimeError):
    pass


def parse_congest_dump(path):
    """Parse ``dumpCongestArea -all`` into a uniform grid.

    Port of ``tools/ruplace_gr_calibrate.py::parse_congest_dump`` -- same regex,
    same uniformity checks -- but raising :class:`InnovusDumpError` instead of
    ``SystemExit`` so an in-loop failure can be caught and fall back.

    Returns a dict with ``nx, ny, step_x, step_y, x0, y0, n_rows`` and the four
    ``(nx, ny)`` int64 arrays ``h_remain/h_total/v_remain/v_total``.
    """
    with open(path) as fh:
        text = fh.read()
    rows = DUMP_ROW.findall(text)
    if not rows:
        raise InnovusDumpError("no data rows parsed from %s" % path)
    arr = np.asarray(rows, dtype=np.int64)  # [N, 8]
    x1, y1, x2, y2 = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]

    xs = np.unique(x1)
    ys = np.unique(y1)
    nx, ny = len(xs), len(ys)
    if arr.shape[0] != nx * ny:
        raise InnovusDumpError(
            "dump is not a full grid: %d rows but %d x %d = %d"
            % (arr.shape[0], nx, ny, nx * ny))

    step_x = _uniform_step(xs, "x")
    step_y = _uniform_step(ys, "y")
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
        raise InnovusDumpError("only %d distinct %s coordinates in dump" % (len(coords), axis))
    d = np.diff(coords)
    if d.min() != d.max():
        raise InnovusDumpError("non-uniform %s grid in dump: steps %d..%d" % (axis, d.min(), d.max()))
    return int(d[0])


def _assert_uniform(values, expected, what):
    if int(values.min()) != expected or int(values.max()) != expected:
        raise InnovusDumpError("non-uniform %s: got %d..%d, expected %d"
                               % (what, values.min(), values.max(), expected))


# --------------------------------------------------------------------------- grid mapping

def dump_to_router_grid(dump, nx, ny, die_lx, die_ly, die_hx, die_hy):
    """Aggregate the Innovus dump onto the router's ``nx x ny`` gcell grid.

    Assignment is by *gcell centre*: Innovus gcell ``i`` spans
    ``[x0 + step*i, x0 + step*(i+1))``, so its centre is ``x0 + step*(i+0.5)``
    and it belongs to router column ``floor((centre - die_lx) / pitch_x)``,
    clamped into range.  This absorbs the 72 dbu x-origin offset (Innovus snaps
    gcells to the track origin, GRDatabase tiles the die box uniformly from
    ``die_lx``) as a nearest-gcell assignment, and -- unlike a reshape-based
    ``k x k`` block sum -- it also handles a die span that is not an integer
    multiple of the Innovus gcell (regression_s14: 799200 / 576 = 1387.5).

    When the two grids *are* commensurate (nvdla_s: 1250 Innovus columns ->
    250 router columns, 2880/576 = 5) this reproduces the block sum exactly.

    Returns a dict of ``(nx, ny)`` int64 track counts plus bookkeeping.
    """
    nx, ny = int(nx), int(ny)
    if nx < 1 or ny < 1:
        raise InnovusDumpError("bad router grid %d x %d" % (nx, ny))
    pitch_x = (float(die_hx) - float(die_lx)) / nx
    pitch_y = (float(die_hy) - float(die_ly)) / ny
    if not (pitch_x > 0 and pitch_y > 0):
        raise InnovusDumpError("bad die box (%s, %s)-(%s, %s)" % (die_lx, die_ly, die_hx, die_hy))

    ci = dump["x0"] + dump["step_x"] * (np.arange(dump["nx"], dtype=np.float64) + 0.5)
    cj = dump["y0"] + dump["step_y"] * (np.arange(dump["ny"], dtype=np.float64) + 0.5)
    ix = np.clip(np.floor((ci - float(die_lx)) / pitch_x).astype(np.int64), 0, nx - 1)
    iy = np.clip(np.floor((cj - float(die_ly)) / pitch_y).astype(np.int64), 0, ny - 1)
    flat = (ix[:, None] * ny + iy[None, :]).ravel()

    out = {"nx": nx, "ny": ny, "pitch_x": pitch_x, "pitch_y": pitch_y,
           "src_nx": int(dump["nx"]), "src_ny": int(dump["ny"]),
           "src_step_x": int(dump["step_x"]), "src_step_y": int(dump["step_y"]),
           "src_x0": int(dump["x0"]), "src_y0": int(dump["y0"]),
           "n_src_gcells": int(dump["nx"]) * int(dump["ny"]),
           "n_empty_bins": 0}
    for name in ("h_remain", "h_total", "v_remain", "v_total"):
        acc = np.bincount(flat, weights=dump[name].ravel().astype(np.float64),
                          minlength=nx * ny)
        out[name] = np.rint(acc).astype(np.int64).reshape(nx, ny)
    counts = np.bincount(flat, minlength=nx * ny)
    out["n_empty_bins"] = int((counts == 0).sum())
    out["src_per_bin_min"] = int(counts.min())
    out["src_per_bin_max"] = int(counts.max())
    return out


def hv_fields(tracks, clamp=True):
    """H/V utilization + overflow from aggregated remain/total track counts.

    ``clamp`` mirrors ``gr_metrics.hv_maps(util_mode='avail')``, which does
    ``util.clamp_min(0)``; the calibration harness
    (``ruplace_gr_calibrate.py::innovus_fields``) does *not* clamp, so the
    verification path passes ``clamp=False`` to reproduce its numbers exactly.
    """
    out = {}
    tot_r = np.zeros_like(tracks["h_total"], dtype=np.float64)
    tot_t = np.zeros_like(tracks["h_total"], dtype=np.float64)
    for d in ("h", "v"):
        total = tracks["%s_total" % d].astype(np.float64)
        remain = tracks["%s_remain" % d].astype(np.float64)
        tot_r += remain
        tot_t += total
        with np.errstate(divide="ignore", invalid="ignore"):
            util = np.where(total > 0, 1.0 - remain / np.maximum(total, 1e-12), 0.0)
        util = np.nan_to_num(util, nan=0.0, posinf=0.0, neginf=0.0)
        if clamp:
            util = np.maximum(util, 0.0)
        out["%s_util" % d] = util
        out["%s_overflow" % d] = np.maximum(util - 1.0, 0.0)
        out["%s_ovfl_tracks" % d] = np.maximum(0.0, -remain)
        out["%s_cap" % d] = total
        out["%s_mask" % d] = total > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        util2 = np.where(tot_t > 0, 1.0 - tot_r / np.maximum(tot_t, 1e-12), 0.0)
    util2 = np.nan_to_num(util2, nan=0.0, posinf=0.0, neginf=0.0)
    if clamp:
        util2 = np.maximum(util2, 0.0)
    out["util"] = util2
    out["overflow"] = np.maximum(util2 - 1.0, 0.0)
    out["mask"] = tot_t > 0
    return out


def maps_from_dump(dump, nx, ny, die, clamp=True):
    """``parse_congest_dump`` output -> the four maps the RUPlace loop consumes.

    ``die`` is ``(die_lx, die_hx, die_ly, die_hy)``, i.e. the tuple layout of
    ``gpdb.dieInfo()``.  Returns ``(fields, tracks)``.
    """
    die_lx, die_hx, die_ly, die_hy = die
    tracks = dump_to_router_grid(dump, nx, ny, die_lx, die_ly, die_hx, die_hy)
    return hv_fields(tracks, clamp=clamp), tracks


# --------------------------------------------------------------------------- case resolution

_META_KEYS = ("def_fixed_macro", "def_raw", "def_input")


def _meta_dir(params):
    explicit = str(getattr(params, "ruplace_innovus_meta_dir", "") or "").strip()
    if explicit:
        return explicit
    repo = _repo_root(params)
    return os.path.join(repo, "data", "s14") if repo else ""


def _strip_def_suffixes(name):
    base = os.path.basename(str(name))
    for suffix in (".def.gz", ".def"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    for tail in (".gp", ".dp", ".lg", ".fixedmacro", ".ruplace"):
        while base.endswith(tail):
            base = base[: -len(tail)]
    return base


def resolve_case(params, meta_dir=None):
    """Resolve the s14 case name the Innovus scorer needs.

    ``ruplace_innovus_case`` wins.  Otherwise every ``<meta_dir>/*.meta.json`` is
    matched against ``params.def_input``, in decreasing order of confidence:

    1. exact realpath of one of the meta DEF entries;
    2. the DEF lives under ``<meta_dir>/<case>/`` or a ``<case>`` path segment;
    3. the DEF basename, with ``.gp/.dp/.lg/.fixedmacro`` tails stripped, equals
       the same reduction of a meta DEF entry (this is what fires for a GP
       output such as ``NV_nvdla_s.fixedmacro.gp.def``).

    Raises ``RuntimeError`` if nothing matches: silently scoring the wrong
    design would be far worse than failing at setup.
    """
    explicit = str(getattr(params, "ruplace_innovus_case", "") or "").strip()
    if explicit:
        return explicit
    def_input = str(getattr(params, "def_input", "") or "")
    if not def_input:
        raise RuntimeError("ruplace_inflate_proxy=innovus needs def_input or ruplace_innovus_case")
    if meta_dir is None:
        meta_dir = _meta_dir(params)
    if not meta_dir or not os.path.isdir(meta_dir):
        raise RuntimeError("cannot resolve ruplace_innovus_case: no meta dir at %r" % meta_dir)

    real = os.path.realpath(def_input)
    stem = _strip_def_suffixes(def_input)
    parts = set(os.path.realpath(def_input).split(os.sep))
    by_path, by_dir, by_stem = [], [], []
    for path in sorted(os.listdir(meta_dir)):
        if not path.endswith(".meta.json"):
            continue
        case = path[: -len(".meta.json")]
        try:
            with open(os.path.join(meta_dir, path)) as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            continue
        case = str(meta.get("case") or case)
        for key in _META_KEYS:
            value = meta.get(key)
            if not value:
                continue
            if os.path.realpath(str(value)) == real:
                by_path.append(case)
            if _strip_def_suffixes(value) == stem:
                by_stem.append(case)
        if case in parts:
            by_dir.append(case)
    for candidates, how in ((by_path, "exact def path"), (by_dir, "path segment"),
                            (by_stem, "def basename stem")):
        uniq = sorted(set(candidates))
        if len(uniq) == 1:
            logging.info("RUPlace Innovus proxy: resolved case %r from %s (%s)",
                         uniq[0], def_input, how)
            return uniq[0]
        if len(uniq) > 1:
            raise RuntimeError(
                "ambiguous ruplace_innovus_case for %s: %s matched by %s; set "
                "ruplace_innovus_case explicitly" % (def_input, uniq, how))
    raise RuntimeError(
        "cannot resolve ruplace_innovus_case for def_input=%s against %s; set "
        "ruplace_innovus_case explicitly" % (def_input, meta_dir))


# --------------------------------------------------------------------------- locations

# The scoring script lives in the *worktree* (tools/ruplace_s14_innovus_eval.sh) but
# reads its case metadata and Innovus staging area from the checkout that
# tools/ruplace_s14_prep.py staged into -- which is the main repo, not the worktree.
# The script encodes that split itself (WT from its own path, REPO overridable), so
# these two roots are resolved separately here too.
_DEFAULT_REPO = "/mnt/nvme0n1/yifan/projs/DREAMPlace"


def _has_s14_data(root):
    return bool(root) and os.path.isdir(os.path.join(root, "data", "s14"))


def _repo_root(params):
    """Checkout holding data/s14/<case>.meta.json and data/s14/innovus_stage."""
    explicit = str(getattr(params, "ruplace_innovus_repo", "") or "").strip()
    if explicit:
        return explicit
    for env in (os.environ.get("RUPLACE_S14_REPO"), os.environ.get("REPO")):
        if _has_s14_data(env):
            return env
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(8):
        if _has_s14_data(here):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return _DEFAULT_REPO


def _eval_script(params):
    explicit = str(getattr(params, "ruplace_innovus_eval_script", "") or "").strip()
    if explicit:
        return explicit
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        cand = os.path.join(here, "tools", "ruplace_s14_innovus_eval.sh")
        if os.path.isfile(cand):
            return cand
        here = os.path.dirname(here)
    return os.path.join(_repo_root(params), "tools", "ruplace_s14_innovus_eval.sh")


class _FileLock(object):
    """Advisory flock, so this proxy never runs two Innovus jobs at once.

    The Innovus licence is shared with other agents' CPU jobs; ``gpu_lock.py``
    only serializes the GPU router.  ``timeout <= 0`` means block forever.
    """

    def __init__(self, path, timeout=1800.0, poll=2.0):
        self.path = path
        self.timeout = float(timeout)
        self.poll = float(poll)
        self.fd = None

    def __enter__(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError as error:
            logging.warning("RUPlace Innovus proxy: cannot open lock %s (%s); running unlocked",
                            self.path, error)
            self.fd = None
            return self
        deadline = time.time() + self.timeout if self.timeout > 0 else None
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
            if deadline is not None and time.time() > deadline:
                raise TimeoutError("timed out after %.0fs waiting for %s" % (self.timeout, self.path))
            time.sleep(self.poll)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None
        return False


# --------------------------------------------------------------------------- the proxy

class InnovusEGRProxy(object):
    """Innovus early-global-route congestion map, as a drop-in for ``adapter.run_route``.

    ``run_route(pos, iteration=...)`` writes the current (unlegalized) placement
    as a DEF through the GPUGR adapter's own DEF path, scores it with
    ``tools/ruplace_s14_innovus_eval.sh <case> <def> <outdir> global`` under
    ``DUMP_CONGEST=1``, and folds ``innovus_congest_area.txt`` onto the router
    gcell grid.  The returned object has the same fields as
    ``RUPlaceRouteResult`` so ``RUPlaceInflation.apply`` needs no changes.
    """

    def __init__(self, params, placedb, adapter):
        self.params = params
        self.placedb = placedb
        self.adapter = adapter
        self.case = resolve_case(params)
        self.script = _eval_script(params)
        self.repo = _repo_root(params)
        self.min_interval = max(0, int(getattr(params, "ruplace_innovus_proxy_min_interval", 100)))
        self.timeout = float(getattr(params, "ruplace_innovus_proxy_timeout", 1800.0))
        self.lock_timeout = float(getattr(params, "ruplace_innovus_proxy_lock_timeout", 3600.0))
        self.workdir = self._resolve_workdir()
        self.lock_path = str(getattr(params, "ruplace_innovus_proxy_lock", "") or "").strip() \
            or os.path.join(self.repo, "results", "locks", "ruplace_innovus.lock")
        self.call_count = 0
        self.last_route = None
        self.last_iteration = None
        self.history = []
        if not os.path.isfile(self.script):
            raise RuntimeError("Innovus eval script not found: %s" % self.script)
        os.makedirs(self.workdir, exist_ok=True)
        logging.info(
            "RUPlace Innovus proxy: case=%s script=%s workdir=%s min_interval=%d iters",
            self.case, self.script, self.workdir, self.min_interval)

    # -- setup ------------------------------------------------------------
    def _resolve_workdir(self):
        explicit = str(getattr(self.params, "ruplace_innovus_proxy_workdir", "") or "").strip()
        if explicit:
            return explicit
        result_dir = str(getattr(self.params, "result_dir", "") or "")
        try:
            design = self.params.design_name()
        except Exception:
            design = ""
        if not result_dir:
            return os.path.join(self.repo, "results", "ruplace_innovus_proxy", design or self.case)
        return os.path.join(result_dir, design, "ruplace", "innovus")

    def _router_grid(self):
        nx, ny = self.adapter._gr_grid_size()
        if int(nx) <= 0 or int(ny) <= 0:
            raise RuntimeError(
                "ruplace_inflate_proxy=innovus needs an explicit router grid; "
                "ruplace_gr_grid=%r resolves to %sx%s"
                % (getattr(self.params, "ruplace_gr_grid", None), nx, ny))
        return int(nx), int(ny)

    def _die(self):
        return tuple(float(v) for v in self.adapter.gpdb.dieInfo())

    # -- rate limiting ----------------------------------------------------
    def should_run(self, iteration):
        if self.last_route is None:
            return True
        if iteration is None or self.last_iteration is None:
            return True
        return int(iteration) - int(self.last_iteration) >= self.min_interval

    # -- main entry point -------------------------------------------------
    def run_route(self, pos, iteration=None):
        if not self.should_run(iteration):
            logging.info(
                "RUPlace Innovus proxy: reusing call %d map (iteration %s, last %s, "
                "min interval %d)", self.call_count, iteration, self.last_iteration,
                self.min_interval)
            return self.last_route
        try:
            return self._run(pos, iteration)
        except Exception as error:  # never let an eGR failure kill the placement
            logging.warning("RUPlace Innovus proxy failed (%s: %s)",
                            type(error).__name__, error, exc_info=True)
            if self.last_route is not None:
                logging.warning("RUPlace Innovus proxy: falling back to the cached map")
                return self.last_route
            logging.warning("RUPlace Innovus proxy: falling back to GPUGR for this round")
            return self.adapter.run_route(pos)

    def _run(self, pos, iteration):
        t0 = time.time()
        self.call_count += 1
        call_dir = os.path.join(self.workdir, "call_%04d" % self.call_count)
        os.makedirs(call_dir, exist_ok=True)
        prefix = os.path.join(call_dir, "placement")

        self.adapter.gpdb.apply_node_lpos(self.adapter._scaled_to_raw_lpos(pos))
        self.adapter.gpdb.write_placement(prefix)
        def_path = prefix + ".def"
        if not os.path.isfile(def_path):
            raise RuntimeError("adapter wrote no DEF at %s" % def_path)
        t_def = time.time() - t0

        env = dict(os.environ)
        env["DUMP_CONGEST"] = "1"
        if _has_s14_data(self.repo):
            env["REPO"] = self.repo
        cmd = [self.script, self.case, os.path.abspath(def_path), call_dir, "global"]
        log_path = os.path.join(call_dir, "proxy.log")
        t_egr = time.time()
        with _FileLock(self.lock_path, timeout=self.lock_timeout):
            with open(log_path, "w") as log:
                log.write("$ DUMP_CONGEST=1 REPO=%s %s\n\n" % (self.repo, " ".join(cmd)))
                log.flush()
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                      env=env, text=True,
                                      timeout=self.timeout if self.timeout > 0 else None)
        egr_sec = time.time() - t_egr
        dump_path = os.path.join(call_dir, "innovus_congest_area.txt")
        if not os.path.isfile(dump_path):
            raise RuntimeError("Innovus produced no congestion dump (rc=%d); see %s"
                               % (proc.returncode, log_path))

        nx, ny = self._router_grid()
        dump = parse_congest_dump(dump_path)
        fields, tracks = maps_from_dump(dump, nx, ny, self._die(), clamp=True)
        route = self._to_result(fields, tracks, call_dir, egr_sec, t_def, t0, pos)
        self.last_route = route
        self.last_iteration = int(iteration) if iteration is not None else None
        self._log_call(route, fields, tracks, iteration, dump, nx, ny)
        return route

    # -- result assembly --------------------------------------------------
    def _to_result(self, fields, tracks, call_dir, egr_sec, def_sec, t0, pos=None):
        # Land the maps on the same device/dtype GPUGR would have returned: every
        # consumer (RUPlaceInflation, the plugin CongestionSignal path) mixes them
        # with placement tensors, and a CPU/CUDA split there is a hard error.
        device = pos.device if torch.is_tensor(pos) else None
        dtype = pos.dtype if torch.is_tensor(pos) else torch.float32

        def to_t(arr):
            t = torch.from_numpy(np.ascontiguousarray(arr, dtype=np.float32))
            if device is not None:
                t = t.to(device=device, dtype=dtype)
            return t

        util = to_t(fields["util"])
        overflow = to_t(fields["overflow"])
        hv_util = torch.stack((to_t(fields["h_util"]), to_t(fields["v_util"]))).contiguous()
        hv_overflow = (hv_util - 1.0).clamp_min(0.0).contiguous()

        summary = _read_innovus_json(call_dir)
        n_bins = max(int(util.numel()), 1)
        metrics = {
            # The two GPUGR-scale stop thresholds have no Innovus analogue; report 0
            # so ruplace_local_congestion_stop alone decides (reporting map-derived
            # counts here would make the stop condition unreachable instead).
            "num_ovfl_nets": 0,
            "est_shorts": 0.0,
            "gr_wirelength": float(summary.get("wirelength") or 0.0),
            "gr_vias": float(summary.get("vias") or 0.0),
            "rc_hor": float(hv_overflow[0].mean().item()),
            "rc_ver": float(hv_overflow[1].mean().item()),
            "source": "innovus_egr",
            "innovus_egr_h": float(summary.get("egr_horizontal_congestion")
                                   if summary.get("egr_horizontal_congestion") is not None
                                   else float("nan")),
            "innovus_egr_v": float(summary.get("egr_vertical_congestion")
                                   if summary.get("egr_vertical_congestion") is not None
                                   else float("nan")),
            "innovus_wl": float(summary.get("wirelength") or 0.0),
            "innovus_h_overflow": float(summary.get("horizontal_overflow")
                                        if summary.get("horizontal_overflow") is not None
                                        else float("nan")),
            "innovus_v_overflow": float(summary.get("vertical_overflow")
                                        if summary.get("vertical_overflow") is not None
                                        else float("nan")),
            "innovus_ovfl_gcells_h": int((fields["h_overflow"] > 0).sum()),
            "innovus_ovfl_gcells_v": int((fields["v_overflow"] > 0).sum()),
            "innovus_ovfl_tracks_h": float(fields["h_ovfl_tracks"].sum()),
            "innovus_ovfl_tracks_v": float(fields["v_ovfl_tracks"].sum()),
            "coverage_h_pct": 100.0 * float((fields["h_overflow"] > 0).sum()) / n_bins,
            "coverage_v_pct": 100.0 * float((fields["v_overflow"] > 0).sum()) / n_bins,
            "call": self.call_count,
            "call_dir": call_dir,
            "egr_time": egr_sec,
            "def_time": def_sec,
            "time": time.time() - t0,
        }
        return RUPlaceRouteResult(
            None, overflow.contiguous(), util.contiguous(), hv_overflow,
            metrics, hv_util, None,
        )

    def _log_call(self, route, fields, tracks, iteration, dump, nx, ny):
        m = route.metrics
        logging.info(
            "RUPlace Innovus eGR: call %d iter %s | %.1fs (def %.1fs, eGR %.1fs) | "
            "NR-eGR H/V %.3f/%.3f%% | WL %.1f um | grid %dx%d <- innovus %dx%d step %d "
            "(x0 %d) | overflow coverage H/V %.2f/%.2f%% (%d/%d gcells, %.0f/%.0f tracks) | "
            "mean util H/V %.4f/%.4f",
            m["call"], iteration, m["time"], m["def_time"], m["egr_time"],
            m["innovus_egr_h"], m["innovus_egr_v"], m["innovus_wl"],
            nx, ny, dump["nx"], dump["ny"], dump["step_x"], dump["x0"],
            m["coverage_h_pct"], m["coverage_v_pct"],
            m["innovus_ovfl_gcells_h"], m["innovus_ovfl_gcells_v"],
            m["innovus_ovfl_tracks_h"], m["innovus_ovfl_tracks_v"],
            float(fields["h_util"].mean()), float(fields["v_util"].mean()),
        )
        if tracks["n_empty_bins"]:
            logging.warning("RUPlace Innovus proxy: %d of %d router gcells got no Innovus gcell "
                            "(grid mismatch?)", tracks["n_empty_bins"], nx * ny)
        self.history.append({k: m[k] for k in (
            "call", "time", "egr_time", "innovus_egr_h", "innovus_egr_v", "innovus_wl",
            "coverage_h_pct", "coverage_v_pct", "rc_hor", "rc_ver")})
        self.history[-1]["iteration"] = iteration
        try:
            with open(os.path.join(self.workdir, "calls.json"), "w") as fh:
                json.dump(self.history, fh, indent=2, sort_keys=True)
                fh.write("\n")
        except OSError:
            pass


def _read_innovus_json(call_dir):
    path = os.path.join(call_dir, "innovus.json")
    try:
        with open(path) as fh:
            return json.load(fh).get("metrics", {}) or {}
    except (OSError, ValueError):
        logging.warning("RUPlace Innovus proxy: no metrics at %s", path)
        return {}


# --------------------------------------------------------------------------- factory

INFLATE_PROXY_MODES = ("gpugr", "innovus", "both")


def resolve_inflate_proxy(params):
    mode = str(getattr(params, "ruplace_inflate_proxy", "gpugr") or "gpugr").strip().lower()
    if mode in ("", "xplace"):
        mode = "gpugr"
    if mode not in INFLATE_PROXY_MODES:
        raise ValueError("ruplace_inflate_proxy must be one of %s, got %r"
                         % (INFLATE_PROXY_MODES, mode))
    return mode


def build_inflation_proxy(params, placedb, adapter, adaptive_profile=None):
    """Return the object supplying the inflation map, or ``None`` for plain GPUGR.

    ``None`` means "the controller keeps calling ``adapter.run_route`` exactly as
    before", so ``ruplace_inflate_proxy=gpugr`` (the default) is a strict no-op.

    ``innovus`` and ``both`` are rejected together with adaptive inflation:
    ``_maybe_inflate_adaptive`` feeds the map's overflow coverage into
    ``InflationCalibration.predict("gpugr", ...)``, a fitted GPUGR-coverage ->
    Innovus-congestion mapping.  Handing it Innovus coverage would apply that
    mapping twice.
    """
    mode = resolve_inflate_proxy(params)
    if mode == "gpugr":
        return None
    if adaptive_profile is not None:
        raise RuntimeError(
            "ruplace_inflate_proxy=%s is only supported with ruplace_inflation_effort=legacy: "
            "adaptive inflation predicts Innovus congestion *from* the GPUGR map via the "
            "calibration profile, so an Innovus map would be double-mapped" % mode)
    return InnovusEGRProxy(params, placedb, adapter)
