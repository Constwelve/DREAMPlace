#!/usr/bin/env python3
"""Gather RUPlace large-case benchmarks under install/benchmarks."""

import json
import os
import re
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TAIWEI_ROOT = Path("/home/yifan/projs/TaiWei-Pin-3D")
OUT_ROOT = REPO_ROOT / "install" / "benchmarks" / "ruplace"
CONFIG_DIR = REPO_ROOT / "configs"


TAIWEI_CASES = [
    ("bp_quad", "bp_quad", "nangate45_bp_quad_cds2d.v", True),
    ("openc910", "openC910", "nangate45_openc910_cds2d.v", True),
    ("nvdla_l", "NV_nvdla", "nangate45_nvdla_l_cds2d.v", True),
    ("mempool_group", "mempool_group", None, False),
    ("xscore", "xscore", None, False),
]

TAIWEI_2D_REFERENCE_DEFS = {
    "openc910": {
        "innovus_2d_place": TAIWEI_ROOT
        / "results"
        / "nangate45"
        / "ct_top"
        / "eval_openc910_2d_dp_gp_20260621_r5"
        / "eval_2D_DP_preCTS.def",
    },
}


def rel(path):
    return os.path.relpath(Path(path).resolve(), CONFIG_DIR)


def is_2d_reference_def(path):
    path = Path(path)
    if not path.exists():
        return False
    with path.open("r", errors="ignore") as f:
        for i, line in enumerate(f):
            if "_upper" in line or "_bottom" in line:
                return False
            if i > 20000:
                break
    return True


def copy_file(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return True
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    tmp.replace(dst)
    return True


def remove_stale_taiwei_refs(case_dir):
    """Drop old copied 3D/tier DEFs so the install bundle stays 2D-only."""
    for rel_path in (
        "innovus/3_place.def",
        "innovus/4_cts.def",
        "innovus/5_route.def",
    ):
        path = case_dir / rel_path
        if path.exists():
            path.unlink()
    for path in (case_dir / "innovus").glob("*_3D*.def"):
        path.unlink()


def fakeram_lefs_for(paths):
    masters = set()
    pattern = re.compile(r"\bfakeram45_[A-Za-z0-9_]+")
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        with path.open("r", errors="ignore") as f:
            for line in f:
                masters.update(pattern.findall(line))

    lef_dir = OUT_ROOT / "common" / "nangate45" / "lef" / "fakeram"
    lefs = []
    for master in sorted(masters):
        lef = lef_dir / f"{master}.lef"
        if lef.exists():
            lefs.append(rel(lef))
    return lefs


def copy_common_lefs():
    src_dir = TAIWEI_ROOT / "platforms" / "nangate45" / "lef"
    dst_dir = OUT_ROOT / "common" / "nangate45" / "lef"
    lefs = [
        "NangateOpenCellLibrary.tech.lef",
        "NangateOpenCellLibrary.macro.mod.lef",
    ]
    for name in lefs:
        copy_file(src_dir / name, dst_dir / name)
    for src in sorted((src_dir / "fakeram").glob("*.lef")):
        copy_file(src, dst_dir / "fakeram" / src.name)
    return [
        rel(dst_dir / "NangateOpenCellLibrary.tech.lef"),
        rel(dst_dir / "NangateOpenCellLibrary.macro.mod.lef"),
    ]


def taiwei_case_entry(design, design_name, netlist_name, compare_enabled, common_lefs):
    src_dir = TAIWEI_ROOT / "results" / "nangate45_3D" / design / "cadence"
    dst_dir = OUT_ROOT / "taiwei2d" / "nangate45" / design
    remove_stale_taiwei_refs(dst_dir)
    copy_file(src_dir / "2_2_floorplan_io.def", dst_dir / "input" / "2_2_floorplan_io.def")
    if netlist_name:
        netlist_src = CONFIG_DIR / "ruplace_taiwei_2d_netlists" / netlist_name
    else:
        netlist_src = src_dir / "1_synth.v"
    copy_file(netlist_src, dst_dir / "input" / "1_synth.v")

    reference_defs = {}
    reference_paths = []
    for ref_name, ref_src in TAIWEI_2D_REFERENCE_DEFS.get(design, {}).items():
        if is_2d_reference_def(ref_src):
            dst_name = "%s.def" % ref_name
            dst_path = dst_dir / "innovus" / dst_name
            if copy_file(ref_src, dst_path):
                reference_defs[ref_name] = rel(dst_path)
                reference_paths.append(dst_path)

    log_dir = TAIWEI_ROOT / "logs" / "nangate45_3D" / design / "cadence"
    for pattern in ("3_place*.log", "4*cts*.log", "5_route.log"):
        for src in sorted(log_dir.glob(pattern)):
            copy_file(src, dst_dir / "logs" / src.name)

    input_def = dst_dir / "input" / "2_2_floorplan_io.def"
    input_netlist = dst_dir / "input" / "1_synth.v"
    lef_input = common_lefs + fakeram_lefs_for([input_def] + reference_paths)

    return {
        "name": f"taiwei_nangate45_{design}_install",
        "tech": "nangate45",
        "source": "taiwei_config2d_install",
        "stage": "2_2_floorplan_io",
        "design_name": design_name,
        "benchmark": "taiwei2d_install",
        "lef_input": lef_input,
        "def_input": rel(input_def),
        "verilog_input": rel(input_netlist),
        "eval_verilog_input": rel(input_netlist),
        "dreamplace_verilog_input": False,
        "enabled": True,
        "compare_enabled": bool(compare_enabled),
        "placement_enabled": False,
        "reference_defs": reference_defs,
        "notes": (
            "Installed TaiWei 2D handoff case. DREAMPlace placement is disabled "
            "because these DEFs have no regular NETS and the available Cadence "
            "Verilog is not DREAMPlace-parser clean; Xplace GGR/input/reference "
            "evaluation still uses the netlist. Only explicitly audited 2D "
            "Innovus checkpoint DEFs are copied as reference baselines."
        ),
    }


def tilos_entry():
    src_dir = Path("/mnt/sda/yifan/benchmarks/TILOS/NV_NVDLA_partition_c")
    dst_dir = OUT_ROOT / "data_large" / "tilos_nvdla_partition_c"
    copy_file(src_dir / "NV_NVDLA_partition_c.lef", dst_dir / "NV_NVDLA_partition_c.lef")
    copy_file(src_dir / "NV_NVDLA_partition_c.floorplan.def", dst_dir / "NV_NVDLA_partition_c.floorplan.def")
    return {
        "name": "tilos_nvdla_partition_c_install",
        "source": "tilos_nvdla_install",
        "benchmark": "tilos",
        "design_name": "NV_NVDLA_partition_c",
        "lef_input": rel(dst_dir / "NV_NVDLA_partition_c.lef"),
        "def_input": rel(dst_dir / "NV_NVDLA_partition_c.floorplan.def"),
        "enabled": True,
        "placement_enabled": True,
        "notes": "Installed TILOS NVDLA partition large case.",
    }


def write_manifest(path, cases):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cases": cases}, indent=2) + "\n")


def main():
    common_lefs = copy_common_lefs()
    taiwei_cases = [
        taiwei_case_entry(*case, common_lefs=common_lefs)
        for case in TAIWEI_CASES
    ]
    smoke_cases = [tilos_entry()] + taiwei_cases
    compare_cases = [smoke_cases[0]] + [case for case in taiwei_cases if case.get("compare_enabled")]
    write_manifest(CONFIG_DIR / "ruplace_large_install_smoke_cases.json", smoke_cases)
    write_manifest(CONFIG_DIR / "ruplace_large_install_compare_cases.json", compare_cases)
    print("Wrote", CONFIG_DIR / "ruplace_large_install_smoke_cases.json")
    print("Wrote", CONFIG_DIR / "ruplace_large_install_compare_cases.json")


if __name__ == "__main__":
    main()
