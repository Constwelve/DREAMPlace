#!/usr/bin/env python3
"""Stage LEF/Verilog/DEF and emit the place_ref.tcl for ruplace_innovus_place_ref.sh."""
import json
import shutil
import sys
from pathlib import Path

meta, work, out_dir, effort, row_site_fix = sys.argv[1:6]
m = json.load(open(meta))
work = Path(work)
out = Path(out_dir)

lefs = []
for i, lef in enumerate(m["lef_input"]):
    dst = work / ("lef_%d_%s" % (i, Path(lef).name))
    shutil.copy2(lef, dst)
    lefs.append(dst)

dv = work / ("input_" + Path(m["def_fixed_macro"]).name)
if row_site_fix == "fix":
    # ROW site core7T -> 90s9t_CoreSite (identical 0.090 x 0.576 geometry) so that
    # place_design / refinePlace see rows matching the site the std cells declare.
    n = 0
    with open(m["def_fixed_macro"]) as src, open(dv, "w") as dst:
        for line in src:
            if line.startswith("ROW ") and " core7T " in line:
                line = line.replace(" core7T ", " 90s9t_CoreSite ", 1)
                n += 1
            dst.write(line)
    print("row site renamed on %d ROW lines" % n)
else:
    shutil.copy2(m["def_fixed_macro"], dv)

vv = work / ("input_" + Path(m["eval_verilog_input"]).name)
shutil.copy2(m["eval_verilog_input"], vv)


def q(p):
    return "{%s}" % p


L = [
    "set init_lef_file [list %s]" % " ".join(q(p) for p in lefs),
    "set init_verilog %s" % q(vv),
    "set init_design_netlisttype Verilog",
    "set init_design_settop 1",
    "set init_top_cell %s" % q(m["top_cell"]),
    "set init_mmmc_file {}",
    "init_design",
    "defIn %s" % q(dv),
    "setMultiCpuUsage -localCpu 8",
    # No MMMC / no SDC -> place_design reports IMPSP-9514 and runs non-timing-driven by
    # itself (22.10 doc); -place_global_timing_effort only takes {medium|high} so it is
    # deliberately not set.  Scan reorder off keeps the netlist identical to the one
    # DREAMPlace placed, so wirelength stays comparable.
    "setPlaceMode -place_global_cong_effort %s" % effort,
    "setPlaceMode -place_global_reorder_scan false",
    "set t0 [clock seconds]",
    "place_design",
    "set t1 [clock seconds]",
    "puts \"RLEVAL_PLACE_SECONDS [expr $t1 - $t0]\"",
    "catch {refinePlace}",
    "catch {checkPlace}",
    "set t2 [clock seconds]",
    "puts \"RLEVAL_PLACE_TOTAL_SECONDS [expr $t2 - $t0]\"",
    "defOut -floorplan -placement %s" % q(out / "place_design.def"),
    # --- identical to dreamplace/ops/routability_eval/innovus.py global mode ---
    "setNanoRouteMode -grouteExpWithTimingDriven false",
    "earlyGlobalRoute",
    "catch {dumpCongestArea -all %s}" % q(out / "congest_area.txt"),
    "catch {reportWire -summary}",
    "catch {reportCongestion -overflow}",
    "set rleval_wl 0",
    "catch {set rleval_wl [expr [join [dbget top.nets.wires.length] +]]}",
    "puts \"RLEVAL_ROUTED_WIRELENGTH $rleval_wl\"",
    "exit",
]
(work / "place_ref.tcl").write_text("\n".join(L) + "\n")
shutil.copy2(work / "place_ref.tcl", out / "place_ref.tcl")
