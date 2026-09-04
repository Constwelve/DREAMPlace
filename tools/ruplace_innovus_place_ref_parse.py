#!/usr/bin/env python3
"""Parse an Innovus place_design reference log into summary.json (see ruplace_innovus_place_ref.sh)."""
import argparse, json, re, os

RX_EGR = re.compile(r"Overflow after Early Global Route\s+([0-9.eE+-]+)%\s+H\s*\+\s*([0-9.eE+-]+)%\s+V", re.I)
RX_RC = re.compile(r"^Overflow:\s*([0-9.eE+-]+)\s*=\s*([0-9.eE+-]+)\s*\(([0-9.eE+-]+)%\s*H\)\s*\+\s*([0-9.eE+-]+)\s*\(([0-9.eE+-]+)%\s*V\)", re.I | re.M)
RX_WL = re.compile(r"RLEVAL_ROUTED_WIRELENGTH\s+([0-9.eE+-]+)")
RX_PL = re.compile(r"RLEVAL_PLACE_SECONDS\s+([0-9]+)")
RX_PT = re.compile(r"RLEVAL_PLACE_TOTAL_SECONDS\s+([0-9]+)")
RX_VIA = re.compile(r"Total length:\s*[0-9.eE+-]+\s*(?:um)?,\s*number of vias:\s*([0-9.eE+-]+)", re.I)
RX_FATAL = re.compile(r"^\*\*(?:ERROR|FATAL):.*$", re.M)
RX_CELL = re.compile(r"\((-?\d+), (-?\d+)\) \((-?\d+), (-?\d+)\) V: (-?\d+)/(-?\d+) H: (-?\d+)/(-?\d+)")


def congest_pct(path):
    """Recompute the NR-eGR H/V overflow percentages from the per-gcell dump.
    Verified to reproduce the [NR-eGR] line exactly: denominator is the number of
    gcells with a nonzero total track count in that direction."""
    n = hov = vov = hz = vz = 0
    with open(path) as fh:
        for line in fh:
            m = RX_CELL.match(line.strip())
            if not m:
                continue
            _, _, _, _, vr, vt, hr, ht = map(int, m.groups())
            n += 1
            hz += ht == 0
            vz += vt == 0
            hov += hr < 0
            vov += vr < 0
    if not n:
        return {}
    return {"gcells": n, "h_overflow_gcells": hov, "v_overflow_gcells": vov,
            "h_zero_track_gcells": hz, "v_zero_track_gcells": vz,
            "dump_h_pct": round(100.0 * hov / max(n - hz, 1), 4),
            "dump_v_pct": round(100.0 * vov / max(n - vz, 1), 4)}


def main():
    ap = argparse.ArgumentParser()
    for a in ("case", "effort", "log", "stdout", "congest", "rc", "out"):
        ap.add_argument("--" + a)
    args = ap.parse_args()
    text = ""
    for p in (args.log, args.stdout):
        if p and os.path.exists(p):
            text += open(p, errors="replace").read()
    s = {"case": args.case, "effort": args.effort, "rc": int(args.rc or 0)}
    m = RX_EGR.findall(text)
    if m:
        s["egr_horizontal_congestion"], s["egr_vertical_congestion"] = (float(v) for v in m[-1])
    m = RX_RC.findall(text)
    if m:
        tot, h, hp, v, vp = (float(x) for x in m[-1])
        s.update({"total_overflow": tot, "horizontal_overflow": h, "vertical_overflow": v,
                  "reportcongestion_h_pct": hp, "reportcongestion_v_pct": vp})
    for key, rx in (("wirelength", RX_WL), ("place_design_sec", RX_PL),
                    ("place_plus_refine_sec", RX_PT), ("vias", RX_VIA)):
        mm = rx.findall(text)
        if mm:
            s[key] = float(mm[-1])
    if args.congest and os.path.exists(args.congest):
        s.update(congest_pct(args.congest))
    f = RX_FATAL.search(text)
    if f:
        s["fatal"] = f.group(0).strip()
    s["status"] = "ok" if s.get("wirelength", 0) > 0 and "egr_horizontal_congestion" in s else "failed"
    with open(args.out, "w") as fh:
        json.dump(s, fh, indent=2, sort_keys=True)
    print(json.dumps(s, sort_keys=True))


if __name__ == "__main__":
    main()
