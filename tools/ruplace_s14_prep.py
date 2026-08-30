#!/usr/bin/env python3
"""Prepare an SMIC14 (s14) case as a DREAMPlace routability benchmark.

Reads the shipped case from ``~/data/benchmarks/s14/<case>`` (read only), writes
everything it produces under ``<repo>/data/s14/<case>``:

* the gzipped Innovus floorplan DEF, decompressed (Limbo's DEF parser cannot read .gz);
* a ``*.fixedmacro.def`` in which every preplaced COMPONENT becomes ``+ FIXED`` --
  the shipped DEFs mark macros ``+ PLACED``, which DREAMPlace reads as movable
  (``num_terminals=0``), turning a fixed-macro routability study into a mixed-size run;
* a DREAMPlace params JSON with the LEF list in Innovus order (tech LEF first --
  Innovus aborts with IMPLF-26 "No technology information is defined in the first LEF
  file" otherwise, and the same order parses fine in DREAMPlace).

Usage:
    python tools/ruplace_s14_prep.py --case nvdla_s_s14
    python tools/ruplace_s14_prep.py --all
"""

import argparse
import glob
import gzip
import json
import os
import re
import shutil
from pathlib import Path

# Machine-specific roots, all env-overridable so the script is not tied to one host:
#   RUPLACE_REPO      repo root                (default: the repo this script lives in)
#   RUPLACE_S14_SRC   read-only shipped cases  (default: ~/data/benchmarks/s14)
#   RUPLACE_S14_OUT   staging output root      (default: <repo>/data/s14)
REPO = Path(os.environ.get("RUPLACE_REPO") or Path(__file__).resolve().parents[1])
SRC_ROOT = Path(os.environ.get("RUPLACE_S14_SRC") or os.path.expanduser("~/data/benchmarks/s14"))
OUT_ROOT = Path(os.environ.get("RUPLACE_S14_OUT") or (REPO / "data" / "s14"))
# Shipped with the repo (15-line SMIC14 site alias), next to the s14 case manifest.
SITE_ALIAS_LEF = Path(__file__).resolve().parents[1] / "test" / "ruplace" / "s14_extra_sites.lef"

# Gate A: the Innovus evaluator refuses a case without a Verilog netlist, so only these
# four of the eight shipped cases can be scored by Innovus.
CASES = {
    "nvdla_s_s14": {"top": "NV_nvdla", "def_gz": "NV_nvdla_s.def.gz", "verilog": "NV_nvdla_s.v"},
    "nvdla_l_s14": {"top": "NV_nvdla", "def_gz": "NV_nvdla_l.def.gz", "verilog": "NV_nvdla_l.v"},
    "vortex_l_s14": {"top": "Vortex", "def_gz": "Vortex_l.def.gz", "verilog": "Vortex_l.v"},
    "regression_s14": {"top": "ct_top", "def_gz": "ct_top.def.gz", "verilog": "ct_top.v"},
}

COMPONENT_STATUS_RE = re.compile(r"\+ PLACED\b")


def lef_list(case):
    """LEF paths in Innovus load order: tech LEF, site alias, std cells, macros."""
    src = SRC_ROOT / case
    lefs = sorted(glob.glob(str(src / "lef_lib" / "pdk" / "*.lef")))
    lefs.append(str(SITE_ALIAS_LEF))
    for sub in ("all_lef", "Rocc_lef"):
        lefs.extend(sorted(glob.glob(str(src / "lef_lib" / sub / "*.lef"))))
    lefs.extend(sorted(glob.glob(str(src / "*.lef"))))
    return lefs


def decompress(case, def_gz, out_dir):
    out = out_dir / def_gz[:-3]
    if out.exists() and out.stat().st_size:
        return out
    with gzip.open(SRC_ROOT / case / def_gz, "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 22)
    return out


def fix_macros(def_path):
    """Rewrite preplaced COMPONENTS as FIXED. Only the COMPONENTS section is touched;
    PINS and SPECIALNETS use the same '+ PLACED' token and must keep their status."""
    out = def_path.with_suffix(".fixedmacro.def")
    if out.exists() and out.stat().st_size:
        return out, -1
    changed = 0
    in_components = False
    with open(def_path) as src, open(out, "w") as dst:
        for line in src:
            if line.startswith("COMPONENTS "):
                in_components = True
            elif line.startswith("END COMPONENTS"):
                in_components = False
            if in_components and "+ PLACED" in line:
                line, n = COMPONENT_STATUS_RE.subn("+ FIXED", line)
                changed += n
            dst.write(line)
    return out, changed


def prepare(case):
    spec = CASES[case]
    out_dir = OUT_ROOT / case
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_def = decompress(case, spec["def_gz"], out_dir)
    fixed_def, changed = fix_macros(raw_def)
    config = {
        "lef_input": lef_list(case),
        "def_input": str(fixed_def),
        "verilog_input": "",
        "gpu": 1,
        "num_threads": 8,
        "global_place_flag": 1,
        "legalize_flag": 1,
        "detailed_place_flag": 0,
        "plot_flag": 0,
        "dtype": "float32",
        "result_dir": str(OUT_ROOT / "results"),
    }
    config_path = OUT_ROOT / ("%s.json" % case)
    config_path.write_text(json.dumps(config, indent=4) + "\n")
    meta = {
        "case": case,
        "top_cell": spec["top"],
        "def_raw": str(raw_def),
        "def_fixed_macro": str(fixed_def),
        "eval_verilog_input": str(SRC_ROOT / case / spec["verilog"]),
        "lef_input": config["lef_input"],
        "components_fixed": changed,
    }
    (OUT_ROOT / ("%s.meta.json" % case)).write_text(json.dumps(meta, indent=4) + "\n")
    print("%-16s def=%s fixed_components=%s config=%s"
          % (case, fixed_def.name, changed if changed >= 0 else "cached", config_path.name))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", choices=sorted(CASES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not args.case and not args.all:
        parser.error("pass --case <name> or --all")
    for case in (sorted(CASES) if args.all else [args.case]):
        prepare(case)


if __name__ == "__main__":
    main()
