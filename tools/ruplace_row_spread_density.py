#!/usr/bin/env python3
"""Packed-gcell density fraction (frac of placeable gcells with std-cell density
> 0.95) for a list of DEFs, on the same 576-dbu Innovus gcell grid and the same
placeable/valid mask convention as tools/ruplace_spread_analysis.py.

Usage: python3 tools/ruplace_row_spread_density.py --out results/row_spread/density
    (edit DEFS below, or pass --defs key=path pairs)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from ruplace_spread_analysis import (
    LEFS, GC_AREA, NX, NY, parse_lef, parse_def_components, rasterize, rect_coverage,
)


def build_area_map(def_path, cells, log):
    t = time.time()
    names, macs, xs, ys, ors, fixed, halos = parse_def_components(def_path)
    w = np.zeros(len(names)); h = np.zeros(len(names))
    cls = np.empty(len(names), object)
    miss = 0
    for i, mc in enumerate(macs):
        c = cells.get(mc)
        if c is None:
            miss += 1
            cls[i] = "MISSING"
            continue
        w[i], h[i], cls[i], _ = c
        w[i] *= 1000.0
        h[i] *= 1000.0
    rot = np.isin(ors, ["E", "W", "FE", "FW"])
    w2 = np.where(rot, h, w); h2 = np.where(rot, w, h)
    is_macro = np.array([str(c).split()[0] in ("BLOCK", "PAD", "RING", "COVER") for c in cls])
    is_std = ~is_macro & (w2 > 0)
    area_map = rasterize(xs[is_std], ys[is_std], w2[is_std], h2[is_std], (w2 * h2)[is_std])
    macro_rects = np.stack([xs[is_macro], ys[is_macro], w2[is_macro], h2[is_macro]], 1).astype(np.float64)
    macro_cov = rect_coverage(macro_rects)
    log("  %s: %d comps (%d std, %d macro, %d missLEF) in %.0fs"
        % (os.path.basename(def_path), len(names), int(is_std.sum()), int(is_macro.sum()),
           miss, time.time() - t))
    return area_map, macro_cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--defs", nargs="+", required=True, help="key=path pairs")
    ap.add_argument("--out", required=True, help="output json path")
    args = ap.parse_args()

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    cells = parse_lef(LEFS)
    log("loaded %d LEF macros" % len(cells))

    pairs = [kv.split("=", 1) for kv in args.defs]
    results = {}
    macro_cov_ref = None
    core = rect_coverage([(1800.0, 1152.0, 8840 * 90.0, 747648.0 - 1152.0)])  # computed once
    placeable = None
    valid = None
    for key, path in pairs:
        area_map, macro_cov = build_area_map(path, cells, log)
        if macro_cov_ref is None:
            macro_cov_ref = macro_cov
            placeable = np.clip(core - macro_cov_ref, 0.0, 1.0)
            valid = placeable > 0.5
        den = np.zeros((NY, NX))
        np.divide(area_map, placeable * GC_AREA, out=den, where=placeable > 0)
        d = den[valid]
        results[key] = dict(
            def_path=path,
            valid_gcells=int(valid.sum()),
            mean=float(d.mean()),
            frac_gt_080=float((d > 0.8).mean()),
            frac_gt_090=float((d > 0.9).mean()),
            frac_gt_095=float((d > 0.95).mean()),
            macro_cov_matches_ref=bool(np.allclose(macro_cov, macro_cov_ref, atol=1e-6)),
        )
        log("  %s: frac_gt_095=%.4f  macro_cov_matches_ref=%s"
            % (key, results[key]["frac_gt_095"], results[key]["macro_cov_matches_ref"]))

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
