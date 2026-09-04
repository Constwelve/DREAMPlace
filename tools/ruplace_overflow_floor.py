#!/usr/bin/env python3
"""Classify Innovus early-global-route overflow gcells by their structural cause.

    tools/ruplace_overflow_floor.py --case <case> --congest <dumpCongestArea file> \
        --def <def the dump came from> --out <json> [--label <name>]

Reads the ``dumpCongestArea -all`` dump (rows ``(x1, y1) (x2, y2) V: r/t H: r/t``, DBU),
builds the per-direction overflow masks (remain < 0) and classifies every overflow gcell:

* blocked      -- zero total tracks in that direction (no placement can route there)
* macro d<=k   -- Chebyshev distance k gcells from the nearest fixed-macro gcell
* channel      -- in a macro-to-macro gap narrower than --channel-width gcells
* open         -- everything else

The dump percentages are the metric of record: verified on
results/s14_final_report_replay that ``overflow_gcells / gcells_with_nonzero_total``
reproduces the ``[NR-eGR] Overflow after Early Global Route X% H + Y% V`` line exactly.
Every class share is therefore reported both as a share of the overflow population and,
multiplied by that denominator, as an absolute NR-eGR percentage point contribution.
"""
import argparse, json, re, sys
import numpy as np

RX_CELL = re.compile(r"\((-?\d+), (-?\d+)\) \((-?\d+), (-?\d+)\) V: (-?\d+)/(-?\d+) H: (-?\d+)/(-?\d+)")
SWAP_ORIENT = {"E", "W", "FE", "FW"}


def read_lef_macros(paths):
    """{macro name: (width_dbu_um_float, height, class)} from LEF SIZE/CLASS."""
    macros = {}
    rx_macro = re.compile(r"^\s*MACRO\s+(\S+)")
    rx_size = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)")
    rx_class = re.compile(r"^\s*CLASS\s+(.+?)\s*;")
    rx_end = re.compile(r"^\s*END\s+(\S+)")
    for p in paths:
        cur = None
        with open(p, errors="replace") as fh:
            for line in fh:
                m = rx_macro.match(line)
                if m:
                    cur = m.group(1); macros[cur] = [None, None, ""]
                    continue
                if cur is None:
                    continue
                m = rx_size.match(line)
                if m:
                    macros[cur][0] = float(m.group(1)); macros[cur][1] = float(m.group(2)); continue
                m = rx_class.match(line)
                if m and macros[cur][2] == "":
                    macros[cur][2] = m.group(1).strip(); continue
                m = rx_end.match(line)
                if m and m.group(1) == cur:
                    cur = None
    return {k: tuple(v) for k, v in macros.items() if v[0] is not None}


def read_def_fixed(def_path):
    """[(cell, x_dbu, y_dbu, orient)] for + FIXED COMPONENTS, plus DEF units."""
    units = 1000.0
    out = []
    rx_units = re.compile(r"^UNITS DISTANCE MICRONS\s+([0-9]+)")
    rx_comp = re.compile(r"^-\s+(\S+)\s+(\S+)\s")
    rx_fixed = re.compile(r"\+\s+(FIXED|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)")
    in_comp = False
    buf = ""
    with open(def_path, errors="replace") as fh:
        for line in fh:
            m = rx_units.match(line)
            if m:
                units = float(m.group(1))
            if line.startswith("COMPONENTS "):
                in_comp = True; continue
            if line.startswith("END COMPONENTS"):
                break
            if not in_comp:
                continue
            buf += line
            if ";" not in line:
                continue
            rec, buf = buf, ""
            mc = rx_comp.match(rec.strip())
            mf = rx_fixed.search(rec)
            if mc and mf:
                out.append((mc.group(2), int(mf.group(2)), int(mf.group(3)), mf.group(4)))
    return out, units


def dilate(mask, k):
    """k-step Chebyshev (8-connected) binary dilation, numpy only."""
    m = mask
    for _ in range(k):
        n = m.copy()
        n[1:, :] |= m[:-1, :]; n[:-1, :] |= m[1:, :]
        n[:, 1:] |= m[:, :-1]; n[:, :-1] |= m[:, 1:]
        n[1:, 1:] |= m[:-1, :-1]; n[:-1, :-1] |= m[1:, 1:]
        n[1:, :-1] |= m[:-1, 1:]; n[:-1, 1:] |= m[1:, :-1]
        m = n
    return m


def narrow_channels(macro, max_w):
    """Gcells in a macro-to-macro gap narrower than max_w, scanned along both axes.
    A gap counts only when BOTH ends abut a macro (a run that reaches the die edge is
    open area, not a channel)."""
    ch = np.zeros_like(macro)
    for axis in (0, 1):
        m = macro if axis == 0 else macro.T
        c = ch if axis == 0 else ch.T
        n = m.shape[1]
        for i in range(m.shape[0]):
            row = m[i]
            if not row.any():
                continue
            j = 0
            while j < n:
                if row[j]:
                    j += 1; continue
                s = j
                while j < n and not row[j]:
                    j += 1
                if s > 0 and j < n and (j - s) < max_w:   # both ends are macros
                    c[i, s:j] = True
    return ch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--congest", required=True)
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--meta", help="data/s14/<case>.meta.json (default: derived from --case)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--channel-width", type=int, default=6)
    ap.add_argument("--repo", default="/mnt/nvme0n1/yifan/projs/DREAMPlace")
    a = ap.parse_args()
    meta_path = a.meta or "%s/data/s14/%s.meta.json" % (a.repo, a.case)
    meta = json.load(open(meta_path))

    # --- grid from the dump: index by sorted unique corners, never by arithmetic
    #     (the first column starts at a nonzero offset and edge gcells are clipped).
    rows = []
    xs, ys = set(), set()
    with open(a.congest) as fh:
        for line in fh:
            m = RX_CELL.match(line.strip())
            if not m:
                continue
            v = tuple(map(int, m.groups()))
            rows.append(v); xs.add(v[0]); ys.add(v[1])
    xs = sorted(xs); ys = sorted(ys)
    xi = {v: i for i, v in enumerate(xs)}; yi = {v: i for i, v in enumerate(ys)}
    nx, ny = len(xs), len(ys)
    x2 = np.zeros(nx, dtype=np.int64); y2 = np.zeros(ny, dtype=np.int64)
    ht = np.zeros((nx, ny), dtype=np.int32); vt = np.zeros((nx, ny), dtype=np.int32)
    hr = np.zeros((nx, ny), dtype=np.int32); vr = np.zeros((nx, ny), dtype=np.int32)
    for (bx, by, ex, ey, vrem, vtot, hrem, htot) in rows:
        i, j = xi[bx], yi[by]
        x2[i] = ex; y2[j] = ey
        ht[i, j] = htot; vt[i, j] = vtot; hr[i, j] = hrem; vr[i, j] = vrem
    x1 = np.array(xs, dtype=np.int64); y1 = np.array(ys, dtype=np.int64)

    # --- fixed macros: BLOCK-class only (taps/endcaps/fillers are not macros)
    comps, units = read_def_fixed(a.def_path)
    lef = read_lef_macros(meta["lef_input"])
    macro = np.zeros((nx, ny), dtype=bool)
    kept, skipped, cls_count = 0, {}, {}
    for cell, cx, cy, orient in comps:
        info = lef.get(cell)
        if info is None:
            skipped.setdefault("no_lef", []).append(cell); continue
        w, h, cls = info
        if "BLOCK" not in cls.upper():
            skipped.setdefault(cls or "noclass", []).append(cell); continue
        if orient in SWAP_ORIENT:
            w, h = h, w
        wd, hd = int(round(w * units)), int(round(h * units))
        cls_count[cell] = cls_count.get(cell, 0) + 1
        kept += 1
        i0 = max(int(np.searchsorted(x1, cx, "right") - 1), 0)
        i1 = min(int(np.searchsorted(x1, cx + wd, "left")), nx)
        j0 = max(int(np.searchsorted(y1, cy, "right") - 1), 0)
        j1 = min(int(np.searchsorted(y1, cy + hd, "left")), ny)
        macro[i0:i1, j0:j1] = True

    channel = narrow_channels(macro, a.channel_width) & ~macro
    near = {k: dilate(macro, k) & ~macro for k in (1, 2, 3)}

    result = {"case": a.case, "label": a.label or a.case, "congest": a.congest,
              "def": a.def_path, "grid": {"nx": nx, "ny": ny, "gcells": nx * ny,
              "gcell_dbu_x": int(x2[0] - x1[0]), "gcell_dbu_y": int(y2[0] - y1[0])},
              "macros": {"fixed_components": len(comps), "block_macros_used": kept,
                         "distinct_cells": sorted(cls_count),
                         "skipped_classes": {k: len(v) for k, v in skipped.items()},
                         "macro_gcells": int(macro.sum()),
                         "macro_gcell_pct": round(100.0 * macro.sum() / (nx * ny), 3),
                         "narrow_channel_gcells": int(channel.sum()),
                         "channel_width_gcells": a.channel_width},
              "directions": {}}

    for d, rem, tot in (("H", hr, ht), ("V", vr, vt)):
        live = tot > 0
        ov = (rem < 0)
        denom = int(live.sum())
        n_ov = int(ov.sum())
        pct = 100.0 * n_ov / denom if denom else 0.0
        blocked = ov & ~live                       # overflow in zero-track gcells
        inmacro = ov & macro
        cum = {}
        for k in (1, 2, 3):
            cum["d<=%d" % k] = int((ov & near[k] & ~macro).sum())
        cls = {
            "overflow_gcells": n_ov,
            "denominator_gcells": denom,
            "nr_egr_pct": round(pct, 4),
            "blocked_zero_track": int(blocked.sum()),
            "inside_macro_footprint": int(inmacro.sum()),
            "within_0_gcells_cum": int(inmacro.sum()),
            "within_1_gcells_cum": int(inmacro.sum()) + cum["d<=1"],
            "within_2_gcells_cum": int(inmacro.sum()) + cum["d<=2"],
            "within_3_gcells_cum": int(inmacro.sum()) + cum["d<=3"],
            "narrow_channel": int((ov & channel).sum()),
            "open_area": int((ov & ~macro & ~near[3]).sum()),
        }
        share = {}
        contrib = {}
        for k, v in cls.items():
            if k in ("overflow_gcells", "denominator_gcells", "nr_egr_pct"):
                continue
            share[k] = round(100.0 * v / n_ov, 2) if n_ov else 0.0
            contrib[k] = round(100.0 * v / denom, 4) if denom else 0.0
        cls["share_of_overflow_pct"] = share
        cls["nr_egr_pct_points"] = contrib
        result["directions"][d] = cls

    with open(a.out, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
