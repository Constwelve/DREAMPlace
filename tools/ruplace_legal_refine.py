#!/usr/bin/env python3
"""Congestion-driven legal refinement (DEF -> DEF).

Row-wise 1D redistribution of standard cells against a congestion-derived target
cell-area profile.  Cell order, row assignment, orientation and legality are all
preserved; only x coordinates change.

Two ways of building the per-gcell target cell-area profile:

  --target cap        (literal spec)  target_g proportional to
                      cap_g * S_g with cap_g = 1/(1+alpha*excess_g).
                      NOTE: degenerate -- in a segment with no overflow gcell
                      every cap_g == 1, so this is *uniform* spreading of the
                      whole segment (== the failed ruplace_row_spread.py `even`
                      mode).  Kept for reference/measurement.

  --target transport  (default)  evict cell area only from overflowing gcells and
                      transport it outward to the nearest gcells with real free
                      space in the same row segment:
                         E_g       = A_g * alpha*excess_g / (1 + alpha*excess_g)
                         room_g    = max(0, fill_ceiling*S_g - A_g)  (non-overflow only)
                         target_g  = A_g - E_g + received_g
                      With no overflow in a segment, target_g == A_g and the
                      segment comes back (essentially) unchanged.

excess_g = max(0, -h_remain/h_total) + max(0, -v_remain/v_total) from the Innovus
congest_area dump; 0 wherever the gcell is not overflowing.

Usage:
  python3 tools/ruplace_legal_refine.py --def IN.def --dump congest_area.txt \
      --out OUT.def [--alpha 2.0] [--max-shift-um 30] [--wl-weight 0.5] \
      [--iters 1] [--target transport|cap] [--report report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from bisect import bisect_right

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ruplace_row_spread as rs  # noqa: E402  (load_lefs, parse_rows, rewrite_def, wh_dbu)

# Innovus early-GR gcell grid for regression_s14 (matches ruplace_spread_analysis.py).
GC = 576
X0, Y0 = 72, 0
NX, NY = 1388, 1300

META_JSON = rs.META_JSON

HALO_RE = re.compile(r"\+\s*HALO\s+(?:SOFT\s+)?(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")
DUMP_RE = re.compile(r"\((-?\d+),\s*(-?\d+)\)\s*\((-?\d+),\s*(-?\d+)\)\s*"
                     r"V:\s*(-?\d+)/(-?\d+)\s*H:\s*(-?\d+)/(-?\d+)")


# --------------------------------------------------------------------------- #
def parse_components(path):
    """Same record semantics as rs.parse_components (so rs.rewrite_def stays in
    sync), plus per-component DEF HALO."""
    names, macs, xs, ys, ors, fixed = [], [], [], [], [], []
    halos = {}
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
            mh = rs.COMP_HDR_RE.match(rec)
            if not mh:
                continue
            mp = rs.PLACE_RE.search(rec)
            if not mp or mp.group(2) is None:
                continue
            names.append(mh.group(1).replace("\\", ""))
            macs.append(mh.group(2))
            xs.append(int(mp.group(2)))
            ys.append(int(mp.group(3)))
            ors.append(mp.group(4).upper())
            fixed.append(mp.group(1) in ("FIXED", "COVER"))
            hm = HALO_RE.search(rec)
            if hm:
                halos[len(names) - 1] = tuple(int(v) for v in hm.groups())
    return names, macs, xs, ys, ors, fixed, halos


def parse_dump(path):
    """-> excess[iy][ix] as a dict-of-rows list; also raw remain/total for reporting."""
    excess = [None] * NY
    h_rem = [None] * NY
    h_tot = [None] * NY
    n = 0
    n_of = 0
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
            if excess[iy] is None:
                excess[iy] = [0.0] * NX
                h_rem[iy] = [0] * NX
                h_tot[iy] = [0] * NX
            e = 0.0
            if h_t > 0 and h_r < 0:
                e += -h_r / h_t
            if v_t > 0 and v_r < 0:
                e += -v_r / v_t
            excess[iy][ix] = e
            h_rem[iy][ix] = h_r
            h_tot[iy][ix] = h_t
            if e > 0:
                n_of += 1
            n += 1
    return excess, h_rem, h_tot, n, n_of


# --------------------------------------------------------------------------- #
def build_profile(L, R, cells, exrow, alpha, mode, fill_ceiling, d_max):
    """Return (bnds, target) for the gcell columns spanning [L, R).

    bnds: list of m+1 x boundaries; target[g] = cell width to place in column g.
    Sum(target) == sum of cell widths."""
    g0 = (L - X0) // GC
    g1 = (R - 1 - X0) // GC
    m = g1 - g0 + 1
    bnds = [L] + [X0 + (g0 + j + 1) * GC for j in range(m - 1)] + [R]
    S = [bnds[j + 1] - bnds[j] for j in range(m)]

    # occupied width per column from the current cell positions
    A = [0.0] * m
    for (cx, cw, _idx) in cells:
        a = cx
        b = cx + cw
        ja = max(0, min(m - 1, (a - X0) // GC - g0))
        jb = max(0, min(m - 1, (b - 1 - X0) // GC - g0))
        for j in range(ja, jb + 1):
            ov = min(b, bnds[j + 1]) - max(a, bnds[j])
            if ov > 0:
                A[j] += ov
    W = sum(c[1] for c in cells)

    ex = [0.0] * m
    if exrow is not None:
        for j in range(m):
            gi = g0 + j
            if 0 <= gi < NX:
                ex[j] = exrow[gi]

    if mode == "cap":
        cap = [1.0 / (1.0 + alpha * ex[j]) for j in range(m)]
        wsum = sum(cap[j] * S[j] for j in range(m))
        if wsum <= 0:
            return bnds, [W / m] * m
        target = [W * cap[j] * S[j] / wsum for j in range(m)]
        return bnds, target

    # ---- transport mode ----
    E = [0.0] * m
    for j in range(m):
        if ex[j] > 0 and A[j] > 0:
            f = alpha * ex[j] / (1.0 + alpha * ex[j])
            E[j] = A[j] * f
    if not any(E):
        return bnds, list(A)

    room = [0.0] * m
    for j in range(m):
        if ex[j] <= 0:
            room[j] = max(0.0, fill_ceiling * S[j] - A[j])
    recv = [0.0] * m
    moved = [0.0] * m
    for j in range(m):
        need = E[j]
        if need <= 0:
            continue
        d = 1
        while need > 1e-9 and d <= d_max:
            for jj in (j - d, j + d):
                if not (0 <= jj < m) or room[jj] <= 0:
                    continue
                take = min(room[jj], need)
                room[jj] -= take
                recv[jj] += take
                need -= take
                if need <= 1e-9:
                    break
            d += 1
        moved[j] = E[j] - need

    target = [A[j] - moved[j] + recv[j] for j in range(m)]
    tot = sum(target)
    if tot > 0 and abs(tot - W) > 1e-6:
        target = [t * W / tot for t in target]
    return bnds, target


def invert_cdf(bnds, target, qs):
    """qs: increasing cumulative widths in [0, W].  -> x positions."""
    m = len(target)
    cum = [0.0] * (m + 1)
    for j in range(m):
        cum[j + 1] = cum[j] + target[j]
    out = []
    j = 0
    for q in qs:
        while j < m - 1 and q >= cum[j + 1]:
            j += 1
        t = target[j]
        span = bnds[j + 1] - bnds[j]
        if t <= 0:
            out.append(float(bnds[j]))
        else:
            out.append(bnds[j] + (q - cum[j]) / t * span)
    return out


# --------------------------------------------------------------------------- #
def refine(rows, pitch, macs, xs, ys, ors, fixed, halos, lef, excess,
           alpha, mode, wl_weight, max_shift_dbu, iters, fill_ceiling, log):
    row_by_y = {r.y: r for r in rows}
    row_ys_sorted = sorted(row_by_y)

    blocks_by_row = {}
    std_by_row = {}
    n_unknown_macro = n_std_off_grid = n_taller_than_row = 0

    def add_block(x0, x1, y0, y1):
        i = bisect_right(row_ys_sorted, y0 - pitch)
        while i < len(row_ys_sorted):
            ry = row_ys_sorted[i]
            if ry >= y1:
                break
            if ry + pitch > y0:
                blocks_by_row.setdefault(ry, []).append((x0, x1))
            i += 1

    for i, mac in enumerate(macs):
        wh = rs.wh_dbu(mac, ors[i], lef)
        if wh is None:
            n_unknown_macro += 1
            continue
        w, h = wh
        x, y = xs[i], ys[i]
        if fixed[i]:
            hl = halos.get(i)
            if hl:
                lft, bot, rgt, top = hl
                add_block(x - lft, x + w + rgt, y - bot, y + h + top)
            else:
                add_block(x, x + w, y, y + h)
            continue
        if h > pitch:
            # movable but multi-row-tall: freeze it and treat it as a blockage
            n_taller_than_row += 1
            add_block(x, x + w, y, y + h)
            continue
        if y not in row_by_y:
            n_std_off_grid += 1
            continue
        std_by_row.setdefault(y, []).append((x, w, i))

    for ry in blocks_by_row:
        blocks_by_row[ry].sort()

    new_x = list(xs)
    n_seg = 0
    n_seg_fallback = 0
    n_seg_neg_free = 0
    n_moved = 0
    abs_dx = []
    area_out_of_overflow = 0.0
    area_in_overflow_before = 0.0
    area_in_overflow_after = 0.0
    d_max = max(1, int(round(max_shift_dbu / GC)) + 1)

    for ry in sorted(std_by_row):
        row = row_by_y[ry]
        iy = (ry - Y0) // GC
        exrow = excess[iy] if 0 <= iy < NY else None
        cellist = sorted(std_by_row[ry], key=lambda t: t[0])
        site = row.site if row.site > 0 else 90

        # free segments within [row.x0, row.x1)
        segs = []
        cur = row.x0
        for (bx0, bx1) in blocks_by_row.get(ry, []):
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
        if not segs:
            continue

        seg_cells = [[] for _ in segs]
        si = 0
        for (cx, cw, idx) in cellist:
            while si < len(segs) - 1 and cx >= segs[si][1]:
                si += 1
            seg_cells[si].append((cx, cw, idx))

        for s_i, (L0, R0) in enumerate(segs):
            cells0 = seg_cells[s_i]
            k = len(cells0)
            if k == 0:
                continue
            n_seg += 1
            L = L0 + ((-(L0 - row.x0)) % site)
            R = R0 - ((R0 - row.x0) % site)
            W = sum(c[1] for c in cells0)
            if (R - L) - W < 0:
                n_seg_neg_free += 1
                continue

            orig = [(c[0], c[1], c[2]) for c in cells0]
            cur_cells = list(orig)
            ok = True
            for _it in range(iters):
                bnds, target = build_profile(L, R, cur_cells, exrow, alpha, mode,
                                             fill_ceiling, d_max)
                qs = []
                acc = 0.0
                for (_cx, cw, _idx) in cur_cells:
                    qs.append(acc + cw / 2.0)
                    acc += cw
                stars = invert_cdf(bnds, target, qs)

                want = []
                for n_i, (cx, cw, idx) in enumerate(cur_cells):
                    xc_star = stars[n_i]
                    xc_orig = orig[n_i][0] + cw / 2.0
                    xc = (1.0 - wl_weight) * xc_star + wl_weight * xc_orig
                    xl = xc - cw / 2.0
                    ox = orig[n_i][0]
                    if xl - ox > max_shift_dbu:
                        xl = ox + max_shift_dbu
                    elif ox - xl > max_shift_dbu:
                        xl = ox - max_shift_dbu
                    xi = int(xl)
                    xi -= (xi - row.x0) % site
                    if xi < L:
                        xi = L
                    want.append(xi)

                # left-to-right sweep
                pos = [0] * k
                cursor = L
                for n_i in range(k):
                    cw = cur_cells[n_i][1]
                    p = want[n_i] if want[n_i] > cursor else cursor
                    p += (-(p - row.x0)) % site
                    pos[n_i] = p
                    cursor = p + cw
                # right-to-left corrective sweep
                if cursor > R:
                    limit = R
                    for n_i in range(k - 1, -1, -1):
                        cw = cur_cells[n_i][1]
                        p = pos[n_i]
                        if p + cw > limit:
                            p = limit - cw
                            p -= (p - row.x0) % site
                            pos[n_i] = p
                        limit = pos[n_i]
                    if pos[0] < L:
                        ok = False
                        break
                cur_cells = [(pos[n_i], cur_cells[n_i][1], cur_cells[n_i][2])
                             for n_i in range(k)]

            if not ok:
                n_seg_fallback += 1
                continue

            # commit + stats
            g0 = (L - X0) // GC
            for n_i in range(k):
                cx0, cw, idx = orig[n_i]
                nx = cur_cells[n_i][0]
                new_x[idx] = nx
                d = abs(nx - cx0)
                if d:
                    n_moved += 1
                abs_dx.append(d / 1000.0)
                if exrow is not None:
                    for (aa, sign) in ((cx0, 1), (nx, -1)):
                        b = aa + cw
                        ja = (aa - X0) // GC
                        jb = (b - 1 - X0) // GC
                        for gi in range(ja, jb + 1):
                            if not (0 <= gi < NX) or exrow[gi] <= 0:
                                continue
                            ov = min(b, X0 + (gi + 1) * GC) - max(aa, X0 + gi * GC)
                            if ov > 0:
                                if sign > 0:
                                    area_in_overflow_before += ov * 576.0
                                else:
                                    area_in_overflow_after += ov * 576.0
    area_out_of_overflow = area_in_overflow_before - area_in_overflow_after

    abs_dx.sort()
    n = len(abs_dx)
    stats = dict(
        n_std_cells=sum(len(v) for v in std_by_row.values()),
        n_moved=n_moved,
        frac_moved=(n_moved / n) if n else 0.0,
        mean_abs_dx_um=(sum(abs_dx) / n) if n else 0.0,
        median_abs_dx_um=(abs_dx[n // 2] if n else 0.0),
        p90_abs_dx_um=(abs_dx[int(0.9 * n)] if n else 0.0),
        max_abs_dx_um=(abs_dx[-1] if n else 0.0),
        n_rows_with_std=len(std_by_row),
        n_segments=n_seg,
        n_segments_fallback=n_seg_fallback,
        n_segments_neg_free=n_seg_neg_free,
        n_unknown_macro=n_unknown_macro,
        n_std_off_grid=n_std_off_grid,
        n_taller_than_row=n_taller_than_row,
        cell_area_in_overflow_before_um2=area_in_overflow_before / 1e6,
        cell_area_in_overflow_after_um2=area_in_overflow_after / 1e6,
        cell_area_moved_out_of_overflow_um2=area_out_of_overflow / 1e6,
    )
    return new_x, stats


# --------------------------------------------------------------------------- #
def verify(out_path, rows, pitch, lef, ref, log):
    row_by_y = {r.y: r for r in rows}
    names, macs, xs, ys, ors, fixed, halos = parse_components(out_path)
    res = dict(n_components=len(names))
    r_names, r_ys, r_ors, r_macs = ref
    res["count_match"] = (len(names) == len(r_names))
    res["n_y_changed"] = sum(1 for i in range(min(len(ys), len(r_ys))) if ys[i] != r_ys[i])
    res["n_orient_changed"] = sum(1 for i in range(min(len(ors), len(r_ors))) if ors[i] != r_ors[i])
    res["n_name_mismatch"] = sum(1 for i in range(min(len(names), len(r_names))) if names[i] != r_names[i])

    by_row = {}
    blocks = {}
    n_offgrid = 0
    for i, mac in enumerate(macs):
        wh = rs.wh_dbu(mac, ors[i], lef)
        if wh is None:
            continue
        w, h = wh
        if fixed[i] or h > pitch:
            hl = halos.get(i) if fixed[i] else None
            x0, x1 = xs[i], xs[i] + w
            y0, y1 = ys[i], ys[i] + h
            if hl:
                x0 -= hl[0]; y0 -= hl[1]; x1 += hl[2]; y1 += hl[3]
            for ry in row_by_y:
                if ry < y1 and ry + pitch > y0:
                    blocks.setdefault(ry, []).append((x0, x1))
            continue
        row = row_by_y.get(ys[i])
        if row is None:
            continue
        if (xs[i] - row.x0) % (row.site or 90) != 0:
            n_offgrid += 1
        by_row.setdefault(ys[i], []).append((xs[i], w))

    n_overlap = n_outside = n_macro = 0
    for ry, cells in by_row.items():
        row = row_by_y[ry]
        cells.sort()
        prev_end = None
        blk = sorted(blocks.get(ry, []))
        for (x, w) in cells:
            if x < row.x0 or x + w > row.x1:
                n_outside += 1
            if prev_end is not None and x < prev_end:
                n_overlap += 1
            prev_end = x + w if prev_end is None else max(prev_end, x + w)
            for (bx0, bx1) in blk:
                if x < bx1 and x + w > bx0:
                    n_macro += 1
                    break
    res.update(n_overlap=n_overlap, n_outside_row=n_outside,
               n_overlap_blockage=n_macro, n_off_site_grid=n_offgrid,
               n_rows_checked=len(by_row))
    log("  verify: %s" % json.dumps(res))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", dest="def_in", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--max-shift-um", type=float, default=30.0)
    ap.add_argument("--wl-weight", type=float, default=0.5)
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--target", choices=["transport", "cap"], default="transport")
    ap.add_argument("--fill-ceiling", type=float, default=0.9)
    ap.add_argument("--report", default=None)
    ap.add_argument("--meta", default=META_JSON)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    t0 = time.time()
    lef = rs.load_lefs(rs.lef_paths_from_meta(args.meta))
    log("lef: %d macros (%.0fs)" % (len(lef), time.time() - t0))

    rows, pitch = rs.parse_rows(args.def_in)
    log("rows: %d, pitch=%d, x0=%d, x1=%d, site=%d"
        % (len(rows), pitch, rows[0].x0, rows[0].x1, rows[0].site))
    bad = [r for r in rows if (r.y - Y0) % GC != 0]
    if pitch != GC or bad:
        log("FATAL: DEF rows are not 1:1 with the %d dbu gcell grid "
            "(pitch=%d, %d rows off-grid)" % (GC, pitch, len(bad)))
        sys.exit(3)

    t = time.time()
    names, macs, xs, ys, ors, fixed, halos = parse_components(args.def_in)
    log("components: %d (%d fixed, %d halos) (%.0fs)"
        % (len(names), sum(fixed), len(halos), time.time() - t))

    t = time.time()
    excess, h_rem, h_tot, ndump, n_of = parse_dump(args.dump)
    log("dump: %d gcells, %d overflowing (%.2f%%) (%.0fs)"
        % (ndump, n_of, 100.0 * n_of / max(1, ndump), time.time() - t))

    t = time.time()
    new_x, stats = refine(rows, pitch, macs, xs, ys, ors, fixed, halos, lef, excess,
                          args.alpha, args.target, args.wl_weight,
                          int(round(args.max_shift_um * 1000)), args.iters,
                          args.fill_ceiling, log)
    log("plan (%.0fs): %s" % (time.time() - t, json.dumps(stats)))

    changed = rs.rewrite_def(args.def_in, args.out, names, xs, new_x, fixed, log)

    ver = {}
    if not args.no_verify:
        ver = verify(args.out, rows, pitch, lef, (names, ys, ors, macs), log)

    report = dict(input=args.def_in, dump=args.dump, output=args.out,
                  alpha=args.alpha, target=args.target, wl_weight=args.wl_weight,
                  max_shift_um=args.max_shift_um, iters=args.iters,
                  fill_ceiling=args.fill_ceiling,
                  dump_gcells=ndump, dump_overflow_gcells=n_of,
                  coord_substitutions=changed, **stats, verify=ver)
    if args.report:
        with open(args.report, "w") as fh:
            json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
