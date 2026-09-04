#!/usr/bin/env python3
"""Where does the whitespace go?  Compare Innovus place_design against DREAMPlace
dp_hpwl and RUPlace on the SMIC14 regression_s14 (OpenC910) case.

Rasterises every placement onto the Innovus early-GR gcell grid (576 dbu cells,
1388 x 1300, origin x=72 y=0), overlays the per-gcell H/V remaining-track dumps,
and quantifies:
  * cell-area density and pin density statistics (placeable-area normalised),
  * density inside / outside each placement's own overflow gcells,
  * a displaced-area budget over the dp_hpwl hotspots with distance bands,
  * cell-centre HPWL per net (mean / p99 / hotspot-net split),
  * macro-halo occupancy (Innovus honours DEF HALO, DREAMPlace drops it).

CPU only; no Innovus is invoked.  All heavy parses are cached as .npz / .npy in
the output directory, so re-runs are cheap.

Usage:
    python3 tools/ruplace_spread_analysis.py [--out DIR] [--no-figures]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------- #
# Constants: the Innovus early-GR gcell grid for regression_s14.
# --------------------------------------------------------------------------- #
GC = 576          # gcell pitch, dbu (== one std-cell row height, == M2 track group)
X0, Y0 = 72, 0    # grid origin, dbu
NX, NY = 1388, 1300
NGC = NX * NY     # 1_804_400, matches summary.json "gcells"
GC_AREA = float(GC * GC)

REPO = "/mnt/nvme0n1/yifan/projs/DREAMPlace"
WT = os.path.join(REPO, ".worktrees/ruplace-routability")

LEFS = [
    "/home/yifan/data/benchmarks/s14/regression_s14/lef_lib/pdk/1P8M_DV_3DM_Q1_3Q2_TMa_ALPA1.lef",
    os.path.join(WT, "test/ruplace/s14_extra_sites.lef"),
    "/home/yifan/data/benchmarks/s14/regression_s14/lef_lib/all_lef/scc14nsfp_90sdb_9tc16_rvt_ant.lef",
    "/home/yifan/data/benchmarks/s14/regression_s14/SARM2_new.lef",
]

SRC_DEF = os.path.join(REPO, "data/s14/regression_s14/ct_top.fixedmacro.def")


@dataclass
class Method:
    key: str
    label: str
    def_path: str
    dump: str | None = None          # innovus congest_area dump for THIS placement
    metrics: dict = field(default_factory=dict)


METHODS = [
    Method(
        "innovus", "Innovus place_design",
        os.path.join(WT, "results/phase0_placeref/reg_auto/place_design.def"),
        os.path.join(WT, "results/phase0_placeref/reg_auto/congest_area.txt"),
    ),
    Method(
        "dp_hpwl", "DREAMPlace dp_hpwl (s1001)",
        os.path.join(WT, "results/ruplace_quality/s14_regression_s14_v116_ref_s1001/dreamplace/"
                         "dp_hpwl/regression_s14/results/ct_top.fixedmacro/ct_top.fixedmacro.gp.def"),
        os.path.join(WT, "results/s14_final_report_replay/regression_s14/dp_hpwl_s1001/"
                         "innovus_congest_area.txt"),
    ),
    Method(
        "ruplace_v126B", "RUPlace v126_B blk050 r3thr05 (best)",
        os.path.join(WT, "results/ruplace_quality/s14_regression_s14_v126_B_blk050_r3thr05_s1001/"
                         "dreamplace/ruplace/regression_s14/results/ct_top.fixedmacro/"
                         "ct_top.fixedmacro.gp.def"),
        os.path.join(WT, "results/analysis_spread/ruplace_best_dump/innovus_congest_area.txt"),
    ),
    Method(
        "ruplace_v125L", "RUPlace v125_L r3 thr04 g070 cap50 (+48% area)",
        os.path.join(WT, "results/ruplace_quality/s14_regression_s14_v125_L_r3_thr04_g070_cap50_s1001/"
                         "dreamplace/ruplace/regression_s14/results/ct_top.fixedmacro/"
                         "ct_top.fixedmacro.gp.def"),
        None,   # no congestion dump for this control point (density-only)
    ),
]

# Innovus-reported metrics for each point (from the scored innovus.json / summary.json).
REPORTED = {
    "innovus":       dict(wl=12915765.036, egr_h=0.30, egr_v=0.59, hof=6778.0, vof=13534.0),
    "dp_hpwl":       dict(wl=11166015.781, egr_h=13.02, egr_v=7.35, hof=478268.0, vof=267790.0),
    "ruplace_v126B": dict(wl=12936642.657, egr_h=7.05, egr_v=3.41, hof=200900.0, vof=89793.0),
    "ruplace_v125L": dict(wl=None, egr_h=7.40, egr_v=3.95, hof=None, vof=None),
}


# --------------------------------------------------------------------------- #
# LEF: cell sizes, classes, signal-pin counts
# --------------------------------------------------------------------------- #
def parse_lef(paths):
    """-> {macro: (w_um, h_um, cls, n_signal_pins)}"""
    cells = {}
    for path in paths:
        cur = None
        cls = ""
        w = h = 0.0
        npin = 0
        in_pin = None
        pin_use = ""
        with open(path, errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("MACRO "):
                    cur, cls, w, h, npin, in_pin = s.split()[1], "", 0.0, 0.0, 0, None
                elif cur is None:
                    continue
                elif in_pin is not None:
                    if s.startswith("USE "):
                        pin_use = s.replace(";", "").split()[1].upper()
                    elif s.startswith("END ") and s.split()[1] == in_pin:
                        if pin_use not in ("POWER", "GROUND"):
                            npin += 1
                        in_pin, pin_use = None, ""
                elif s.startswith("CLASS "):
                    cls = " ".join(s.replace(";", "").split()[1:]).upper()
                elif s.startswith("SIZE "):
                    p = s.replace(";", "").split()
                    if len(p) >= 4 and p[2].upper() == "BY":
                        w, h = float(p[1]), float(p[3])
                elif s.startswith("PIN "):
                    in_pin, pin_use = s.split()[1], ""
                elif s.startswith("END ") and s.split()[1] == cur:
                    cells[cur] = (w, h, cls or "UNKNOWN", npin)
                    cur = None
    return cells


# --------------------------------------------------------------------------- #
# DEF: components (name, macro, x, y, orient)
# --------------------------------------------------------------------------- #
COMP_RE = re.compile(r"^-\s+(\S+)\s+(\S+)")
PLACE_RE = re.compile(r"\b(PLACED|FIXED|COVER|UNPLACED)\b(?:\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+))?")
HALO_RE = re.compile(r"\+\s*HALO\s+(?:SOFT\s+)?(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")


def unesc(name: str) -> str:
    return name.replace("\\", "")


def parse_def_components(path):
    """Stream the COMPONENTS section.  -> (names, macros, x, y, orient, fixedflag, halos)."""
    names, macs, xs, ys, ors, fixed = [], [], [], [], [], []
    halos = {}
    buf = []
    inside = False
    with open(path, errors="replace") as fh:
        for line in fh:
            if not inside:
                if line.startswith("COMPONENTS "):
                    inside = True
                continue
            if line.startswith("END COMPONENTS"):
                break
            buf.append(line)
            if ";" not in line:
                continue
            rec = " ".join(x.strip() for x in buf).strip()
            buf = []
            m = COMP_RE.match(rec)
            if not m:
                continue
            p = PLACE_RE.search(rec)
            if not p or p.group(2) is None:
                continue
            nm = unesc(m.group(1))
            names.append(nm)
            macs.append(m.group(2))
            xs.append(int(p.group(2)))
            ys.append(int(p.group(3)))
            ors.append(p.group(4).upper())
            fixed.append(p.group(1) in ("FIXED", "COVER"))
            hm = HALO_RE.search(rec)
            if hm:
                halos[nm] = tuple(int(v) for v in hm.groups())
    return (names, np.array(macs), np.array(xs, np.int64), np.array(ys, np.int64),
            np.array(ors), np.array(fixed), halos)


def parse_def_pins(path):
    """DEF PINS section -> {pin_name: (x, y)} (fixed I/O pins)."""
    out = {}
    inside = False
    buf = []
    with open(path, errors="replace") as fh:
        for line in fh:
            if not inside:
                if line.startswith("PINS "):
                    inside = True
                continue
            if line.startswith("END PINS"):
                break
            buf.append(line)
            if ";" not in line:
                continue
            rec = " ".join(x.strip() for x in buf).strip()
            buf = []
            m = re.match(r"^-\s+(\S+)", rec)
            if not m:
                continue
            p = re.search(r"\b(?:PLACED|FIXED|COVER)\b\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", rec)
            if p:
                out[unesc(m.group(1))] = (int(p.group(1)), int(p.group(2)))
    return out


def parse_def_nets(path, name2idx, pin_xy):
    """NETS section -> CSR (net_ptr, pin_inst) of instance indices, plus fixed
    I/O pin coordinates folded into a per-net running bbox.

    Returns (ptr, idx, io_lo_x, io_hi_x, io_lo_y, io_hi_y, n_unresolved)."""
    ptr = [0]
    idx = []
    iolx, iohx, ioly, iohy = [], [], [], []
    unresolved = 0
    inside = False
    buf = []
    cx = cy = None
    with open(path, errors="replace") as fh:
        for line in fh:
            if not inside:
                if line.startswith("NETS "):
                    inside = True
                continue
            if line.startswith("END NETS"):
                break
            buf.append(line)
            if ";" not in line:
                continue
            rec = " ".join(x.strip() for x in buf)
            buf = []
            if not rec.lstrip().startswith("- "):
                continue
            lo_x = lo_y = np.inf
            hi_x = hi_y = -np.inf
            for a, b in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", rec):
                if a == "PIN":
                    xy = pin_xy.get(unesc(b))
                    if xy is not None:
                        lo_x = min(lo_x, xy[0]); hi_x = max(hi_x, xy[0])
                        lo_y = min(lo_y, xy[1]); hi_y = max(hi_y, xy[1])
                    continue
                j = name2idx.get(unesc(a))
                if j is None:
                    unresolved += 1
                else:
                    idx.append(j)
            ptr.append(len(idx))
            iolx.append(lo_x); iohx.append(hi_x); ioly.append(lo_y); iohy.append(hi_y)
    return (np.array(ptr, np.int64), np.array(idx, np.int64),
            np.array(iolx), np.array(iohx), np.array(ioly), np.array(iohy), unresolved)


# --------------------------------------------------------------------------- #
# Rasterisation: exact rectangle / gcell area overlap
# --------------------------------------------------------------------------- #
def rasterize(x, y, w, h, val):
    """Deposit `val` per rectangle, split across gcells in proportion to the
    geometric overlap area.  x,y = lower-left dbu; w,h = dbu; val = per-rect."""
    grid = np.zeros(NGC, np.float64)
    x0 = (x - X0).astype(np.float64); x1 = x0 + w
    y0 = (y - Y0).astype(np.float64); y1 = y0 + h
    area = np.maximum(w * h, 1.0)
    c0 = np.floor(x0 / GC).astype(np.int64); c1 = np.ceil(x1 / GC).astype(np.int64)
    r0 = np.floor(y0 / GC).astype(np.int64); r1 = np.ceil(y1 / GC).astype(np.int64)
    nk = int(max(1, (c1 - c0).max())); nl = int(max(1, (r1 - r0).max()))
    for k in range(nk):
        cc = c0 + k
        ovx = np.minimum(x1, (cc + 1) * GC) - np.maximum(x0, cc * GC)
        np.clip(ovx, 0, None, out=ovx)
        okx = (ovx > 0) & (cc >= 0) & (cc < NX)
        if not okx.any():
            continue
        for l in range(nl):
            rr = r0 + l
            ovy = np.minimum(y1, (rr + 1) * GC) - np.maximum(y0, rr * GC)
            np.clip(ovy, 0, None, out=ovy)
            m = okx & (ovy > 0) & (rr >= 0) & (rr < NY)
            if not m.any():
                continue
            wgt = val[m] * (ovx[m] * ovy[m]) / area[m]
            grid += np.bincount(rr[m] * NX + cc[m], weights=wgt, minlength=NGC)
    return grid.reshape(NY, NX)


def rect_coverage(rects):
    """Fractional gcell coverage of a list of (x, y, w, h) dbu rectangles."""
    if not len(rects):
        return np.zeros((NY, NX))
    r = np.asarray(rects, np.float64)
    return rasterize(r[:, 0], r[:, 1], r[:, 2], r[:, 3], r[:, 2] * r[:, 3]) / GC_AREA


# --------------------------------------------------------------------------- #
# Innovus congestion dump
# --------------------------------------------------------------------------- #
DUMP_RE = re.compile(r"\((-?\d+),\s*(-?\d+)\)\s*\((-?\d+),\s*(-?\d+)\)\s*"
                     r"V:\s*(-?\d+)/(-?\d+)\s*H:\s*(-?\d+)/(-?\d+)")


def parse_dump(path):
    vr = np.zeros(NGC, np.int32); vt = np.zeros(NGC, np.int32)
    hr = np.zeros(NGC, np.int32); ht = np.zeros(NGC, np.int32)
    seen = np.zeros(NGC, bool)
    n = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.startswith("("):
                continue
            m = DUMP_RE.match(line)
            if not m:
                continue
            x1, y1, _, _, v_r, v_t, h_r, h_t = (int(g) for g in m.groups())
            ix = (x1 - X0) // GC
            iy = (y1 - Y0) // GC
            if not (0 <= ix < NX and 0 <= iy < NY):
                continue
            k = iy * NX + ix
            vr[k], vt[k], hr[k], ht[k] = v_r, v_t, h_r, h_t
            seen[k] = True
            n += 1
    return (dict(v_remain=vr.reshape(NY, NX), v_total=vt.reshape(NY, NX),
                 h_remain=hr.reshape(NY, NX), h_total=ht.reshape(NY, NX)),
            n, int(seen.sum()))


# --------------------------------------------------------------------------- #
# per-method rasterisation with caching
# --------------------------------------------------------------------------- #
def build_method(m: Method, cells, outdir, log):
    cache = os.path.join(outdir, "cache_%s.npz" % m.key)
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        log("  cache hit %s" % os.path.basename(cache))
        return {k: z[k] for k in z.files}

    t = time.time()
    names, macs, xs, ys, ors, fixed, halos = parse_def_components(m.def_path)
    log("  parsed %d components in %.0fs" % (len(names), time.time() - t))

    w = np.zeros(len(names)); h = np.zeros(len(names))
    npins = np.zeros(len(names))
    cls = np.empty(len(names), object)
    miss = 0
    for i, mc in enumerate(macs):
        c = cells.get(mc)
        if c is None:
            miss += 1
            cls[i] = "MISSING"
            continue
        w[i], h[i], cls[i], npins[i] = c[0] * 1000.0, c[1] * 1000.0, c[2], c[3]
    rot = np.isin(ors, ["E", "W", "FE", "FW"])
    w2 = np.where(rot, h, w); h2 = np.where(rot, w, h)

    is_macro = np.array([str(c).split()[0] in ("BLOCK", "PAD", "RING", "COVER") for c in cls])
    is_std = ~is_macro & (w2 > 0)

    area_map = rasterize(xs[is_std], ys[is_std], w2[is_std], h2[is_std],
                         (w2 * h2)[is_std])
    pin_map = rasterize(xs[is_std], ys[is_std], w2[is_std], h2[is_std], npins[is_std])
    macro_rects = np.stack([xs[is_macro], ys[is_macro], w2[is_macro], h2[is_macro]], 1).astype(np.float64)
    macro_cov = rect_coverage(macro_rects)

    # halo ring (macro bbox grown by the DEF HALO, minus the macro itself)
    halo_rects = []
    for i in np.nonzero(is_macro)[0]:
        hl = halos.get(names[i], (0, 0, 0, 0))
        if max(hl) <= 0:
            continue
        halo_rects.append((xs[i] - hl[0], ys[i] - hl[1],
                           w2[i] + hl[0] + hl[2], h2[i] + hl[1] + hl[3]))
    halo_cov = rect_coverage(halo_rects) if halo_rects else np.zeros((NY, NX))

    cx = xs + w2 * 0.5
    cy = ys + h2 * 0.5

    out = dict(area=area_map, pins=pin_map, macro_cov=macro_cov, halo_cov=halo_cov,
               cx=cx, cy=cy, is_std=is_std, is_macro=is_macro, npins=npins,
               cellw=w2, cellh=h2, fixed=fixed,
               stats=np.array([len(names), miss, int(is_std.sum()), int(is_macro.sum()),
                               float((w2 * h2)[is_std].sum()), float(npins[is_std].sum()),
                               len(halo_rects)]))
    np.savez_compressed(cache, **out)
    # names cached separately (object arrays compress badly in npz)
    np.save(os.path.join(outdir, "cache_%s_names.npy" % m.key), np.array(names))
    log("  rasterised %s in %.0fs (missing LEF: %d)" % (m.key, time.time() - t, miss))
    return out


def build_dump(m: Method, outdir, log):
    if not m.dump:
        return None
    cache = os.path.join(outdir, "dump_%s.npz" % m.key)
    if os.path.exists(cache):
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    t = time.time()
    d, n, seen = parse_dump(m.dump)
    log("  dump %s: %d rows, %d unique gcells (%.0fs)" % (m.key, n, seen, time.time() - t))
    np.savez_compressed(cache, **d)
    return d


# --------------------------------------------------------------------------- #
def pct(a, q):
    return float(np.percentile(a, q)) if a.size else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(WT, "results/analysis_spread"))
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()
    outdir = args.out
    os.makedirs(outdir, exist_ok=True)
    logf = open(os.path.join(outdir, "analysis.log"), "w")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    log("== LEF ==")
    cells = parse_lef(LEFS)
    log("  %d macros from LEF" % len(cells))
    hs = {}
    for k, (w, h, c, p) in cells.items():
        if str(c).split()[0] == "CORE":
            hs[round(h * 1000)] = hs.get(round(h * 1000), 0) + 1
    log("  CORE cell heights (dbu): %s" % sorted(hs.items()))

    log("== placements ==")
    M = {}
    for m in METHODS:
        log(" %s" % m.key)
        M[m.key] = build_method(m, cells, outdir, log)
    D = {}
    for m in METHODS:
        d = build_dump(m, outdir, log)
        if d is not None:
            D[m.key] = d

    res = {"grid": dict(gc=GC, x0=X0, y0=Y0, nx=NX, ny=NY, ngc=NGC)}

    # ---------------- validation gates ---------------- #
    log("== validation ==")
    val = {}
    base = M["dp_hpwl"]
    for k, v in M.items():
        st = v["stats"]
        val[k] = dict(components=int(st[0]), missing_lef=int(st[1]), std_cells=int(st[2]),
                      macros=int(st[3]), std_area_dbu2=float(st[4]),
                      total_signal_pins=float(st[5]), halo_macros=int(st[6]))
        val[k]["std_area_rel_dp_hpwl"] = float(st[4] / base["stats"][4] - 1.0)
        val[k]["macro_cov_equal_dp_hpwl"] = bool(
            np.allclose(v["macro_cov"], base["macro_cov"], atol=1e-6))
        log("  %-14s comps=%d std=%d macro=%d missLEF=%d stdArea=%.6e (rel %.2e) macrosEqual=%s haloMacros=%d"
            % (k, st[0], st[2], st[3], st[1], st[4], val[k]["std_area_rel_dp_hpwl"],
               val[k]["macro_cov_equal_dp_hpwl"], st[6]))
    for k, d in D.items():
        hof = int(((d["h_remain"] < 0) & (d["h_total"] > 0)).sum())
        vof = int(((d["v_remain"] < 0) & (d["v_total"] > 0)).sum())
        hz = int((d["h_total"] == 0).sum()); vz = int((d["v_total"] == 0).sum())
        val[k].update(dump_h_overflow_gcells=hof, dump_v_overflow_gcells=vof,
                      dump_h_zero_track=hz, dump_v_zero_track=vz,
                      dump_h_pct=round(100.0 * hof / NGC, 4),
                      dump_v_pct=round(100.0 * vof / NGC, 4),
                      dump_h_overflow_tracks=float(np.abs(d["h_remain"][d["h_remain"] < 0]).sum()),
                      dump_v_overflow_tracks=float(np.abs(d["v_remain"][d["v_remain"] < 0]).sum()))
        log("  %-14s dump H-of gcells=%d (%.4f%%)  V-of=%d (%.4f%%)  zeroTrack H=%d V=%d"
            % (k, hof, 100.0 * hof / NGC, vof, 100.0 * vof / NGC, hz, vz))
    res["validation"] = val

    # ---------------- placeable-area map ---------------- #
    # core rows: 1800..(1800+8840*90) in x, 1152..747648 in y (from the DEF ROWs)
    core = np.zeros((NY, NX))
    core += rect_coverage([(1800.0, 1152.0, 8840 * 90.0, 747648.0 - 1152.0)])
    placeable = np.clip(core - M["dp_hpwl"]["macro_cov"], 0.0, 1.0)
    valid = placeable > 0.5           # gcells with >half a gcell of legal row area
    res["placeable"] = dict(core_gcells=int((core > 0.5).sum()),
                            valid_gcells=int(valid.sum()),
                            macro_gcells=int((M["dp_hpwl"]["macro_cov"] > 0.5).sum()))
    log("  core gcells=%d  valid (placeable>0.5)=%d  macro-covered=%d"
        % ((core > 0.5).sum(), valid.sum(), (M["dp_hpwl"]["macro_cov"] > 0.5).sum()))

    den = {}
    pden = {}
    for k, v in M.items():
        d = np.zeros((NY, NX))
        np.divide(v["area"], placeable * GC_AREA, out=d, where=placeable > 0)
        den[k] = d
        p = np.zeros((NY, NX))
        np.divide(v["pins"], placeable * (GC_AREA / 1e6), out=p, where=placeable > 0)
        pden[k] = p     # signal pins per um^2 of placeable area

    # ---------------- (1) density statistics ---------------- #
    def blur5(a):
        from scipy.ndimage import uniform_filter
        return uniform_filter(a, size=5, mode="nearest")

    tab1 = {}
    for k in M:
        d = den[k][valid]
        b = blur5(den[k])[valid]
        tab1[k] = dict(
            mean=float(d.mean()), p50=pct(d, 50), p90=pct(d, 90), p99=pct(d, 99),
            p999=pct(d, 99.9), max=float(d.max()),
            frac_gt_080=float((d > 0.8).mean()), frac_gt_090=float((d > 0.9).mean()),
            frac_gt_095=float((d > 0.95).mean()),
            std_raw=float(d.std()), std_blur5=float(b.std()),
            smoothness_ratio=float(b.std() / max(d.std(), 1e-12)),
            raw_mean_over_all_gcells=float((M[k]["area"] / GC_AREA).mean()),
        )
    res["density_stats"] = tab1

    tabp = {}
    for k in M:
        p = pden[k][valid]
        b = blur5(pden[k])[valid]
        tabp[k] = dict(mean=float(p.mean()), p50=pct(p, 50), p90=pct(p, 90), p99=pct(p, 99),
                       max=float(p.max()), std_raw=float(p.std()), std_blur5=float(b.std()),
                       cov=float(p.std() / max(p.mean(), 1e-12)),
                       frac_gt_1p5x=float((p > 1.5 * p.mean()).mean()),
                       frac_gt_2x=float((p > 2.0 * p.mean()).mean()))
    res["pin_density_stats"] = tabp

    # ---------------- (2) density vs own overflow ---------------- #
    own = {}
    for k, d in D.items():
        hm = (d["h_remain"] < 0) & (d["h_total"] > 0) & valid
        vm = (d["v_remain"] < 0) & (d["v_total"] > 0) & valid
        anym = (hm | vm)
        own[k] = dict(
            h_gcells=int(hm.sum()), v_gcells=int(vm.sum()), any_gcells=int(anym.sum()),
            den_in_h=float(den[k][hm].mean()) if hm.any() else None,
            den_in_v=float(den[k][vm].mean()) if vm.any() else None,
            den_in_any=float(den[k][anym].mean()) if anym.any() else None,
            den_out=float(den[k][valid & ~anym].mean()),
            pden_in_any=float(pden[k][anym].mean()) if anym.any() else None,
            pden_out=float(pden[k][valid & ~anym].mean()),
        )
    res["own_overflow_overlay"] = own

    # ---------------- (2b) dp_hpwl hotspots: displaced-area budget ---------------- #
    from scipy.ndimage import distance_transform_edt
    dh = D["dp_hpwl"]
    hot_h = (dh["h_remain"] < 0) & (dh["h_total"] > 0)
    hot_v = (dh["v_remain"] < 0) & (dh["v_total"] > 0)
    hot = (hot_h | hot_v) & valid
    # severe hotspots: worst 10% of the overflow magnitude
    sev_mag = np.maximum(-dh["h_remain"], 0) + np.maximum(-dh["v_remain"], 0)
    thr = np.percentile(sev_mag[hot], 90) if hot.any() else 0
    hot_sev = hot & (sev_mag >= thr)

    dist = distance_transform_edt(~hot)          # gcells to nearest hotspot
    bands = [("0 (hotspot)", dist == 0), ("1-2", (dist > 0) & (dist <= 2)),
             ("3-5", (dist > 2) & (dist <= 5)), ("6-10", (dist > 5) & (dist <= 10)),
             (">10", dist > 10)]
    budget = {}
    for k in M:
        rows = []
        da = M[k]["area"] - M["dp_hpwl"]["area"]     # signed area change vs dp_hpwl, dbu^2
        for name, msk in bands:
            m2 = msk & valid
            rows.append(dict(band=name, gcells=int(m2.sum()),
                             delta_area_um2=float(da[m2].sum()) / 1e6,
                             dp_hpwl_density=float(den["dp_hpwl"][m2].mean()),
                             density=float(den[k][m2].mean()),
                             pin_density=float(pden[k][m2].mean())))
        budget[k] = dict(bands=rows,
                         total_delta_um2=float(da[valid].sum()) / 1e6,
                         total_delta_all_um2=float(da.sum()) / 1e6,
                         hotspot_removed_um2=float(-da[hot].sum()) / 1e6,
                         hotspot_den_dp=float(den["dp_hpwl"][hot].mean()),
                         hotspot_den=float(den[k][hot].mean()),
                         hotspot_den_drop=float(den["dp_hpwl"][hot].mean() - den[k][hot].mean()),
                         severe_den_dp=float(den["dp_hpwl"][hot_sev].mean()),
                         severe_den=float(den[k][hot_sev].mean()),
                         hotspot_pden_dp=float(pden["dp_hpwl"][hot].mean()),
                         hotspot_pden=float(pden[k][hot].mean()))
    res["hotspot_budget"] = dict(
        hot_gcells=int(hot.sum()), hot_frac_of_valid=float(hot.sum() / valid.sum()),
        hot_h_gcells=int((hot_h & valid).sum()), hot_v_gcells=int((hot_v & valid).sum()),
        severe_gcells=int(hot_sev.sum()), per_method=budget)

    # ---------------- (3) halo occupancy ---------------- #
    halo_ring = np.clip(M["innovus"]["halo_cov"] - M["innovus"]["macro_cov"], 0, 1)
    ring = (halo_ring > 0.25) & valid
    res["halo"] = dict(
        halo_macros_innovus=int(M["innovus"]["stats"][6]),
        halo_macros_ruplace=int(M["ruplace_v126B"]["stats"][6]),
        ring_gcells=int(ring.sum()),
        density_in_ring={k: float(den[k][ring].mean()) for k in M},
        area_in_ring_um2={k: float(M[k]["area"][ring].sum()) / 1e6 for k in M},
    )

    # ---------------- (4) net-level HPWL ---------------- #
    ncache = os.path.join(outdir, "cache_nets.npz")
    if os.path.exists(ncache):
        z = np.load(ncache)
        ptr, nidx = z["ptr"], z["idx"]
        iolx, iohx, ioly, iohy = z["iolx"], z["iohx"], z["ioly"], z["iohy"]
        unres = int(z["unres"])
    else:
        t = time.time()
        names = np.load(os.path.join(outdir, "cache_dp_hpwl_names.npy"), allow_pickle=True)
        name2idx = {n: i for i, n in enumerate(names)}
        pin_xy = parse_def_pins(METHODS[1].def_path)
        ptr, nidx, iolx, iohx, ioly, iohy, unres = parse_def_nets(
            METHODS[1].def_path, name2idx, pin_xy)
        np.savez_compressed(ncache, ptr=ptr, idx=nidx, iolx=iolx, iohx=iohx,
                            ioly=ioly, iohy=iohy, unres=np.array(unres))
        log("  nets: %d, pin refs %d, unresolved %d, IO pins %d (%.0fs)"
            % (len(ptr) - 1, len(nidx), unres, len(pin_xy), time.time() - t))

    nnet = len(ptr) - 1
    seg = np.repeat(np.arange(nnet), np.diff(ptr))
    hpwl = {}
    net_hp = {}
    for k, v in M.items():
        cx, cy = v["cx"][nidx], v["cy"][nidx]
        lox = np.full(nnet, np.inf); hix = np.full(nnet, -np.inf)
        loy = np.full(nnet, np.inf); hiy = np.full(nnet, -np.inf)
        np.minimum.at(lox, seg, cx); np.maximum.at(hix, seg, cx)
        np.minimum.at(loy, seg, cy); np.maximum.at(hiy, seg, cy)
        lox = np.minimum(lox, iolx); hix = np.maximum(hix, iohx)
        loy = np.minimum(loy, ioly); hiy = np.maximum(hiy, iohy)
        ok = np.isfinite(lox) & np.isfinite(loy)
        w = np.zeros(nnet); w[ok] = (hix[ok] - lox[ok]) + (hiy[ok] - loy[ok])
        net_hp[k] = w
        hpwl[k] = dict(total_um=float(w.sum()) / 1000.0, nets=int(ok.sum()),
                       mean_um=float(w[ok].mean()) / 1000.0,
                       p50_um=pct(w[ok], 50) / 1000.0, p90_um=pct(w[ok], 90) / 1000.0,
                       p99_um=pct(w[ok], 99) / 1000.0,
                       p999_um=pct(w[ok], 99.9) / 1000.0,
                       max_um=float(w[ok].max()) / 1000.0)
    for k in hpwl:
        hpwl[k]["rel_dp_hpwl"] = hpwl[k]["total_um"] / hpwl["dp_hpwl"]["total_um"] - 1.0
        r = REPORTED[k]["wl"]
        hpwl[k]["innovus_routed_wl_um"] = r
        hpwl[k]["routed_rel_dp_hpwl"] = (r / REPORTED["dp_hpwl"]["wl"] - 1.0) if r else None
        hpwl[k]["detour_ratio_routed_over_hpwl"] = (r / hpwl[k]["total_um"]) if r else None
    res["hpwl"] = hpwl

    # hotspot nets: nets with >=1 pin in a dp_hpwl hotspot gcell (dp_hpwl positions)
    bx = np.clip(((M["dp_hpwl"]["cx"][nidx] - X0) // GC).astype(np.int64), 0, NX - 1)
    by = np.clip(((M["dp_hpwl"]["cy"][nidx] - Y0) // GC).astype(np.int64), 0, NY - 1)
    inhot = hot[by, bx]
    net_hot = np.zeros(nnet, bool)
    np.logical_or.at(net_hot, seg, inhot)
    split = {}
    for k in M:
        w = net_hp[k]
        split[k] = dict(
            hot_nets=int(net_hot.sum()),
            hot_total_um=float(w[net_hot].sum()) / 1000.0,
            cold_total_um=float(w[~net_hot].sum()) / 1000.0,
            hot_mean_um=float(w[net_hot].mean()) / 1000.0,
            cold_mean_um=float(w[~net_hot].mean()) / 1000.0)
    for k in split:
        split[k]["hot_rel_dp"] = split[k]["hot_total_um"] / split["dp_hpwl"]["hot_total_um"] - 1
        split[k]["cold_rel_dp"] = split[k]["cold_total_um"] / split["dp_hpwl"]["cold_total_um"] - 1
        split[k]["share_of_delta_from_hot"] = (
            (split[k]["hot_total_um"] - split["dp_hpwl"]["hot_total_um"]) /
            (hpwl[k]["total_um"] - hpwl["dp_hpwl"]["total_um"])
            if abs(hpwl[k]["total_um"] - hpwl["dp_hpwl"]["total_um"]) > 1 else None)
    res["hpwl_hotspot_split"] = split

    # displacement of individual cells vs dp_hpwl
    disp = {}
    for k, v in M.items():
        if k == "dp_hpwl":
            continue
        dx = v["cx"] - M["dp_hpwl"]["cx"]
        dy = v["cy"] - M["dp_hpwl"]["cy"]
        r = np.hypot(dx, dy)[M["dp_hpwl"]["is_std"]]
        disp[k] = dict(mean_um=float(r.mean()) / 1000.0, p50_um=pct(r, 50) / 1000.0,
                       p90_um=pct(r, 90) / 1000.0, p99_um=pct(r, 99) / 1000.0,
                       frac_moved_gt_1um=float((r > 1000).mean()),
                       frac_moved_gt_5um=float((r > 5000).mean()))
    res["displacement_vs_dp_hpwl"] = disp

    # equivalent blockage fraction Innovus applies in the hotspots
    eq = {}
    for k in M:
        b = budget[k]
        eq[k] = dict(
            hotspot_density_drop=b["hotspot_den_drop"],
            equiv_blockage_frac=float(b["hotspot_den_drop"] / max(b["hotspot_den_dp"], 1e-9)),
            severe_equiv_blockage_frac=float((b["severe_den_dp"] - b["severe_den"]) /
                                             max(b["severe_den_dp"], 1e-9)))
    res["equivalent_blockage"] = eq
    res["reported"] = REPORTED

    with open(os.path.join(outdir, "spread_metrics.json"), "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    log("wrote %s" % os.path.join(outdir, "spread_metrics.json"))

    if not args.no_figures:
        make_figures(outdir, den, pden, hot, hot_h, hot_v, valid, M, bands, budget, net_hp, net_hot, log)

    logf.close()
    return res


# --------------------------------------------------------------------------- #
def make_figures(outdir, den, pden, hot, hot_h, hot_v, valid, M, bands, budget,
                 net_hp, net_hot, log):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import uniform_filter

    order = ["dp_hpwl", "innovus", "ruplace_v126B"]
    titles = {"dp_hpwl": "dp_hpwl (13.0/7.4%)", "innovus": "Innovus (0.30/0.59%)",
              "ruplace_v126B": "RUPlace v126_B (7.05/3.41%)",
              "ruplace_v125L": "RUPlace v125_L (7.40/3.95%)"}

    # fig 1: density maps + dp_hpwl H-hotspot contour
    fig, ax = plt.subplots(1, 3, figsize=(16.5, 5.6), constrained_layout=True)
    hotc = uniform_filter((hot_h & valid).astype(float), 3)
    for a, k in zip(ax, order):
        d = np.where(valid, den[k], np.nan)
        im = a.imshow(d, origin="lower", vmin=0.3, vmax=1.0, cmap="inferno",
                      interpolation="nearest")
        a.contour(hotc, levels=[0.15], colors="#00e5ff", linewidths=0.35)
        a.set_title("%s\nmean %.3f  p99 %.3f  >0.9: %.2f%%"
                    % (titles[k], den[k][valid].mean(), np.percentile(den[k][valid], 99),
                       100 * (den[k][valid] > 0.9).mean()), fontsize=10)
        a.set_xticks([]); a.set_yticks([])
        fig.colorbar(im, ax=a, fraction=0.045)
    fig.suptitle("Cell-area density on the Innovus eGR gcell grid (576 dbu), "
                 "cyan = dp_hpwl H-overflow gcells", fontsize=11)
    fig.savefig(os.path.join(outdir, "fig1_density_maps.png"), dpi=130)
    plt.close(fig)

    # fig 2: displaced-area bands
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6), constrained_layout=True)
    labels = [b[0] for b in bands]
    xpos = np.arange(len(labels))
    for i, k in enumerate(["innovus", "ruplace_v126B", "ruplace_v125L"]):
        vals = [r["delta_area_um2"] / 1e3 for r in budget[k]["bands"]]
        ax[0].bar(xpos + (i - 1) * 0.27, vals, width=0.26, label=titles.get(k, k))
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_xticks(xpos); ax[0].set_xticklabels(labels)
    ax[0].set_xlabel("distance from a dp_hpwl overflow gcell (gcells)")
    ax[0].set_ylabel("cell area moved in (+) / out (-)  [10^3 um^2]")
    ax[0].set_title("Displaced-area budget vs dp_hpwl")
    ax[0].legend(fontsize=8)
    for i, k in enumerate(["dp_hpwl", "innovus", "ruplace_v126B", "ruplace_v125L"]):
        vals = [r["density"] for r in budget[k]["bands"]]
        ax[1].plot(xpos, vals, "o-", label=titles.get(k, k))
    ax[1].set_xticks(xpos); ax[1].set_xticklabels(labels)
    ax[1].set_xlabel("distance band"); ax[1].set_ylabel("mean cell-area density")
    ax[1].set_title("Density by distance band")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3)
    fig.savefig(os.path.join(outdir, "fig2_displaced_area.png"), dpi=130)
    plt.close(fig)

    # fig 3: density CDF + pin density CDF + net HPWL delta
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5), constrained_layout=True)
    for k in ["dp_hpwl", "innovus", "ruplace_v126B", "ruplace_v125L"]:
        d = np.sort(den[k][valid])
        ax[0].plot(d, np.linspace(0, 1, d.size), label=titles.get(k, k), lw=1.2)
        p = np.sort(pden[k][valid])
        ax[1].plot(p, np.linspace(0, 1, p.size), lw=1.2)
    ax[0].set_xlim(0.2, 1.15); ax[0].set_ylim(0.5, 1.0)
    ax[0].set_xlabel("cell-area density"); ax[0].set_ylabel("CDF over placeable gcells")
    ax[0].set_title("Density CDF (upper half)"); ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
    ax[1].set_ylim(0.5, 1.0)
    ax[1].set_xlabel("signal pins / um^2"); ax[1].set_title("Pin-density CDF (upper half)")
    ax[1].grid(alpha=0.3)
    for k in ["innovus", "ruplace_v126B"]:
        d = (net_hp[k] - net_hp["dp_hpwl"]) / 1000.0
        ax[2].hist(np.clip(d, -20, 60), bins=160, histtype="step", log=True,
                   label=titles.get(k, k))
    ax[2].set_xlabel("per-net HPWL change vs dp_hpwl [um]")
    ax[2].set_ylabel("nets"); ax[2].set_title("Where the +15.7/15.9% WL comes from")
    ax[2].legend(fontsize=8); ax[2].grid(alpha=0.3)
    fig.savefig(os.path.join(outdir, "fig3_cdfs.png"), dpi=130)
    plt.close(fig)
    log("wrote figures")


if __name__ == "__main__":
    main()
