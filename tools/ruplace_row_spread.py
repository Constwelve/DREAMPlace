#!/usr/bin/env python3
"""Spread standard cells evenly (or proportionally) within each row segment of a
legalized DEF, keeping their left-to-right order, macros (FIXED components) and
row/segment boundaries fixed. Only the x coordinate of PLACED std-cell components
is changed; the rest of the file is byte-preserved via a line-streaming rewrite.

Usage:
    python3 tools/ruplace_row_spread.py --def IN.def --out OUT.def \
        [--mode even|proportional] [--max-shift-um X] [--report report.json]

DEF units: UNITS DISTANCE MICRONS 1000 (1000 dbu / um). Row height / site step
are read from the ROW records themselves (not hardcoded), though for this
design they are 576 dbu row pitch, 90 dbu site width.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from bisect import bisect_left

META_JSON = "/mnt/nvme0n1/yifan/projs/DREAMPlace/data/s14/regression_s14.meta.json"

ROW_RE = re.compile(
    r"^ROW\s+(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(-?\d+)\s+(-?\d+)"
)
COMP_HDR_RE = re.compile(r"^\s*-\s+(\S+)\s+(\S+)")
PLACE_RE = re.compile(r"\b(PLACED|FIXED|COVER|UNPLACED)\b\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)")


# --------------------------------------------------------------------------- #
# LEF: macro -> (w_dbu, h_dbu)
# --------------------------------------------------------------------------- #
def load_lefs(paths):
    cells = {}
    for path in paths:
        cur = None
        w = h = 0.0
        with open(path, errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("MACRO "):
                    cur, w, h = s.split()[1], 0.0, 0.0
                elif cur is None:
                    continue
                elif s.startswith("SIZE "):
                    p = s.replace(";", "").split()
                    if len(p) >= 4 and p[2].upper() == "BY":
                        w, h = float(p[1]), float(p[3])
                elif s.startswith("END ") and s.split()[1] == cur:
                    cells[cur] = (w, h)
                    cur = None
    return cells


def lef_paths_from_meta(meta_path):
    with open(meta_path) as fh:
        return json.load(fh)["lef_input"]


ROT = {"E", "W", "FE", "FW"}


def wh_dbu(macro, orient, lef):
    wh = lef.get(macro)
    if wh is None:
        return None
    w_um, h_um = wh
    w, h = int(round(w_um * 1000)), int(round(h_um * 1000))
    if orient in ROT:
        w, h = h, w
    return w, h


# --------------------------------------------------------------------------- #
# ROW records
# --------------------------------------------------------------------------- #
class Row:
    __slots__ = ("name", "y", "x0", "x1", "site", "orient", "height")

    def __init__(self, name, y, x0, n, step, orient):
        self.name = name
        self.y = y
        self.x0 = x0
        self.x1 = x0 + n * step
        self.site = step
        self.orient = orient
        self.height = None  # filled in after all rows parsed


def parse_rows(path):
    rows = []
    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.startswith("ROW "):
                if line.startswith("COMPONENTS "):
                    break
                continue
            m = ROW_RE.match(line)
            if not m:
                continue
            name, site, x, y, orient, nx, ny, sx, sy = m.groups()
            rows.append(Row(name, int(y), int(x), int(nx), int(sx), orient))
    rows.sort(key=lambda r: r.y)
    if len(rows) >= 2:
        pitch = rows[1].y - rows[0].y
    else:
        pitch = 576
    for r in rows:
        r.height = pitch
    return rows, pitch


# --------------------------------------------------------------------------- #
# COMPONENTS: first pass, collect what we need (name, macro, x, y, orient, fixed)
# --------------------------------------------------------------------------- #
def parse_components(path):
    names, macs, xs, ys, ors, fixed = [], [], [], [], [], []
    inside = False
    buf = []
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
            rec = " ".join(x.strip() for x in buf)
            buf = []
            mh = COMP_HDR_RE.match(rec)
            if not mh:
                continue
            mp = PLACE_RE.search(rec)
            if not mp or mp.group(2) is None:
                continue
            names.append(mh.group(1).replace("\\", ""))
            macs.append(mh.group(2))
            xs.append(int(mp.group(2)))
            ys.append(int(mp.group(3)))
            ors.append(mp.group(4).upper())
            fixed.append(mp.group(1) in ("FIXED", "COVER"))
    return names, macs, xs, ys, ors, fixed


# --------------------------------------------------------------------------- #
# Row assignment + segment building + new-x computation
# --------------------------------------------------------------------------- #
def build_plan(rows, pitch, names, macs, xs, ys, ors, fixed, lef, mode, max_shift_dbu, log):
    row_by_y = {r.y: r for r in rows}
    row_ys_sorted = sorted(row_by_y)

    macro_spans = {}  # row.y -> list of (x0, x1) blocked spans (fixed components)
    std_by_row = {}    # row.y -> list of (x, w, idx) for movable std cells

    n_std_off_grid = 0
    n_unknown_macro = 0
    n_taller_than_row = 0

    for i, mac in enumerate(macs):
        wh = wh_dbu(mac, ors[i], lef)
        if wh is None:
            n_unknown_macro += 1
            continue
        w, h = wh
        y = ys[i]
        if fixed[i]:
            # Blocks every row band it overlaps.
            r0 = y
            r1 = y + h
            for ry in row_ys_sorted:
                if ry >= r1:
                    break
                if ry + pitch > r0:
                    macro_spans.setdefault(ry, []).append((xs[i], xs[i] + w))
            continue
        # Movable standard cell: must land exactly on one row's y and be <= 1 row tall.
        if h > pitch:
            n_taller_than_row += 1
            continue
        row = row_by_y.get(y)
        if row is None:
            n_std_off_grid += 1
            continue
        std_by_row.setdefault(y, []).append((xs[i], w, i))

    for ry in macro_spans:
        macro_spans[ry].sort()

    new_x = [None] * len(xs)
    seg_reports = []
    n_moved = 0
    abs_dx = []
    n_shift_gt1um = 0
    overlap_warnings = 0
    bounds_warnings = 0

    for ry, cellist in std_by_row.items():
        row = row_by_y[ry]
        cellist.sort(key=lambda t: t[0])
        blocks = macro_spans.get(ry, [])
        # Build free segments within [row.x0, row.x1) by cutting out blocked spans.
        segs = []
        cur = row.x0
        for (bx0, bx1) in blocks:
            bx0c, bx1c = max(bx0, row.x0), min(bx1, row.x1)
            if bx1c <= cur:
                continue
            if bx0c > cur:
                segs.append((cur, min(bx0c, row.x1)))
            cur = max(cur, bx1c)
            if cur >= row.x1:
                break
        if cur < row.x1:
            segs.append((cur, row.x1))

        # Assign cells to segments by their (already-legal) position.
        seg_idx = 0
        seg_cells = [[] for _ in segs]
        ci = 0
        cellist_sorted = cellist
        for (cx, cw, idx) in cellist_sorted:
            while seg_idx < len(segs) - 1 and cx >= segs[seg_idx][1]:
                seg_idx += 1
            seg_cells[seg_idx].append((cx, cw, idx))

        site = row.site if row.site > 0 else 90
        for si, (L0, R0) in enumerate(segs):
            cells = seg_cells[si]
            k = len(cells)
            if k == 0:
                continue
            # Snap the segment bounds inward to the absolute site grid (phase = row.x0)
            # so every placed x we compute below lands on a legal site, even when a
            # bounding macro's edge is not itself site-aligned. Sacrifices at most one
            # site's width of otherwise-unusable sliver at each snapped edge.
            L = L0 + ((-(L0 - row.x0)) % site)
            R = R0 - ((R0 - row.x0) % site)
            sumw = sum(c[1] for c in cells)
            free = (R - L) - sumw
            seg_report = dict(row=row.name, y=ry, L=L0, R=R0, k=k, free_dbu=free)
            seg_reports.append(seg_report)
            if free < 0:
                overlap_warnings += 1
                continue  # leave these cells untouched; shouldn't happen post-legalization

            if mode == "even":
                n_sites_free = free // site
                # Evenly distribute n_sites_free "extra sites" into k+1 gaps using the
                # floor((i+1)*N/(k+1)) - floor(i*N/(k+1)) trick -> exact, no overlap.
                def gap_sites(i, N=n_sites_free, K=k):
                    return (( (i + 1) * N) // (K + 1)) - ((i * N) // (K + 1))

                x = L
                for gi, (cx, cw, idx) in enumerate(cells):
                    x += gap_sites(gi) * site
                    new_x[idx] = x
                    x += cw
            elif mode == "proportional":
                # Original gaps (including edges) define the distribution weight,
                # with a floor of half the even share so degenerate (zero-gap) runs
                # still get some spreading.
                orig_gaps = []
                prev_r = L
                for (cx, cw, idx) in cells:
                    orig_gaps.append(max(0, cx - prev_r))
                    prev_r = cx + cw
                orig_gaps.append(max(0, R - prev_r))
                site = row.site if row.site > 0 else 90
                n_sites_free = free // site
                even_share = n_sites_free / (k + 1) if (k + 1) else 0
                floor_w = even_share / 2.0
                weights = [max(g, floor_w) for g in orig_gaps]
                tw = sum(weights) or 1.0
                # Convert weights to integer site counts summing exactly to n_sites_free
                raw = [n_sites_free * (wgt / tw) for wgt in weights]
                floors = [int(r) for r in raw]
                rem = n_sites_free - sum(floors)
                # distribute remainder to largest fractional parts
                fracs = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i]), reverse=True)
                for i in fracs[:rem]:
                    floors[i] += 1
                x = L
                for gi, (cx, cw, idx) in enumerate(cells):
                    x += floors[gi] * site
                    new_x[idx] = x
                    x += cw
            else:
                raise ValueError(mode)

        # Apply max-shift cap + left-to-right overlap resolution, per segment.
        if max_shift_dbu is not None:
            for si, (L0, R0) in enumerate(segs):
                cells = seg_cells[si]
                if not cells:
                    continue
                # Same inward site-grid snap as above (phase = row.x0), so every
                # capped/pushed position we compute here stays grid-legal.
                L = L0 + ((-(L0 - row.x0)) % site)
                R = R0 - ((R0 - row.x0) % site)
                capped = []
                for (cx, cw, idx) in cells:
                    nx = new_x[idx]
                    if nx is None:
                        capped.append((cx, cw, idx))
                        continue
                    dx = nx - cx
                    if dx > max_shift_dbu:
                        nx = cx + max_shift_dbu
                    elif dx < -max_shift_dbu:
                        nx = cx - max_shift_dbu
                    # snap to the absolute site grid (phase = row.x0), rounding toward L
                    off = (nx - row.x0) % site
                    nx -= off
                    nx = max(nx, L)
                    capped.append((nx, cw, idx))
                # left-to-right sweep, push right minimally
                cursor = L
                fixed_positions = []
                for (nx, cw, idx) in capped:
                    x = max(nx, cursor)
                    fixed_positions.append((x, cw, idx))
                    cursor = x + cw
                if cursor > R0:
                    bounds_warnings += 1
                for (x, cw, idx) in fixed_positions:
                    new_x[idx] = x

        # tally move stats for this row's cells
        for (cx, cw, idx) in cellist_sorted:
            if new_x[idx] is None:
                continue
            dx = abs(new_x[idx] - cx)
            if dx > 0:
                n_moved += 1
            abs_dx.append(dx / 1000.0)
            if dx / 1000.0 > 1.0:
                n_shift_gt1um += 1

    stats = dict(
        n_std_cells=sum(len(v) for v in std_by_row.values()),
        n_moved=n_moved,
        mean_abs_dx_um=(sum(abs_dx) / len(abs_dx)) if abs_dx else 0.0,
        max_abs_dx_um=(max(abs_dx) if abs_dx else 0.0),
        frac_shift_gt1um=(n_shift_gt1um / len(abs_dx)) if abs_dx else 0.0,
        n_rows_with_std=len(std_by_row),
        n_segments=len(seg_reports),
        n_unknown_macro=n_unknown_macro,
        n_std_off_grid=n_std_off_grid,
        n_taller_than_row=n_taller_than_row,
        n_overlap_warnings_neg_free=overlap_warnings,
        n_bounds_warnings=bounds_warnings,
    )
    free_vals = [s["free_dbu"] / 1000.0 for s in seg_reports]
    if free_vals:
        free_vals_sorted = sorted(free_vals)
        stats["seg_free_um_mean"] = sum(free_vals) / len(free_vals)
        stats["seg_free_um_median"] = free_vals_sorted[len(free_vals_sorted) // 2]
        stats["seg_free_um_max"] = free_vals_sorted[-1]
    return new_x, stats


# --------------------------------------------------------------------------- #
# Rewrite DEF: stream-copy, substitute x for the components we changed.
# --------------------------------------------------------------------------- #
def rewrite_def(in_path, out_path, names, xs, new_x, fixed, log):
    # names[i] corresponds to component #i in file order (only PLACED/FIXED/COVER
    # records with a coordinate were collected, matching what we scan for below).
    idx_ptr = 0
    n = len(names)
    inside = False
    changed = 0
    t0 = time.time()
    with open(in_path, errors="replace") as fin, open(out_path, "w") as fout:
        for line in fin:
            if not inside:
                fout.write(line)
                if line.startswith("COMPONENTS "):
                    inside = True
                continue
            if line.startswith("END COMPONENTS"):
                fout.write(line)
                inside = False
                continue
            if idx_ptr < n and not fixed[idx_ptr] and new_x[idx_ptr] is not None:
                mp = PLACE_RE.search(line)
                if mp and mp.group(1) == "PLACED":
                    old_x_str = mp.group(2)
                    new_val = new_x[idx_ptr]
                    if new_val != int(old_x_str):
                        start, end = mp.span(2)
                        line = line[:start] + str(new_val) + line[end:]
                        changed += 1
            if PLACE_RE.search(line):
                idx_ptr += 1
            fout.write(line)
    log("  rewrite: %d coordinate substitutions in %.0fs" % (changed, time.time() - t0))
    return changed


# --------------------------------------------------------------------------- #
# Verification: re-parse output, check no overlaps / all inside segment / row unchanged.
# --------------------------------------------------------------------------- #
def verify(out_path, rows, pitch, lef, log):
    row_by_y = {r.y: r for r in rows}
    names, macs, xs, ys, ors, fixed = parse_components(out_path)
    by_row = {}
    macro_spans = {}
    for i, mac in enumerate(macs):
        wh = wh_dbu(mac, ors[i], lef)
        if wh is None:
            continue
        w, h = wh
        if fixed[i]:
            r0, r1 = ys[i], ys[i] + h
            for ry in row_by_y:
                if ry < r1 and ry + pitch > r0:
                    macro_spans.setdefault(ry, []).append((xs[i], xs[i] + w))
            continue
        if h > pitch:
            continue
        row = row_by_y.get(ys[i])
        if row is None:
            continue
        by_row.setdefault(ys[i], []).append((xs[i], w))

    n_overlap = 0
    n_outside = 0
    n_outside_macro = 0
    for ry, cells in by_row.items():
        row = row_by_y[ry]
        cells.sort()
        prev_end = None
        blocks = sorted(macro_spans.get(ry, []))
        for (x, w) in cells:
            if x < row.x0 or x + w > row.x1:
                n_outside += 1
            if prev_end is not None and x < prev_end:
                n_overlap += 1
            prev_end = max(prev_end or x, x + w)
            for (bx0, bx1) in blocks:
                if x < bx1 and x + w > bx0:
                    n_outside_macro += 1
                    break
    log("  verify: overlaps=%d outside_row=%d overlapping_macro=%d (rows checked=%d)"
        % (n_overlap, n_outside, n_outside_macro, len(by_row)))
    return dict(n_overlap=n_overlap, n_outside_row=n_outside, n_overlap_macro=n_outside_macro)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", dest="def_in", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["even", "proportional"], default="even")
    ap.add_argument("--max-shift-um", type=float, default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--meta", default=META_JSON)
    args = ap.parse_args()

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    t0 = time.time()
    lef_paths = lef_paths_from_meta(args.meta)
    lef = load_lefs(lef_paths)
    log("loaded %d LEF macros from %d files (%.0fs)" % (len(lef), len(lef_paths), time.time() - t0))

    rows, pitch = parse_rows(args.def_in)
    log("parsed %d rows, pitch=%d dbu" % (len(rows), pitch))

    names, macs, xs, ys, ors, fixed = parse_components(args.def_in)
    log("parsed %d placed/fixed components" % len(names))

    max_shift_dbu = None if args.max_shift_um is None else int(round(args.max_shift_um * 1000))

    new_x, stats = build_plan(rows, pitch, names, macs, xs, ys, ors, fixed, lef,
                               args.mode, max_shift_dbu, log)
    log("plan: %s" % json.dumps(stats, indent=None))

    changed = rewrite_def(args.def_in, args.out, names, xs, new_x, fixed, log)

    ver = verify(args.out, rows, pitch, lef, log)

    report = dict(
        input=args.def_in, output=args.out, mode=args.mode,
        max_shift_um=args.max_shift_um, coord_substitutions=changed,
        **stats, verify=ver,
    )
    if args.report:
        with open(args.report, "w") as fh:
            json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
