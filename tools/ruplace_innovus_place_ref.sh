#!/usr/bin/env bash
# Innovus place_design reference point for an s14 case: place std cells with Innovus
# (macros stay FIXED from the floorplan DEF), then score the result with the SAME
# early-global-route commands the RUPlace evaluator uses.
#
#   tools/ruplace_innovus_place_ref.sh <case> <outdir> [cong_effort]
#
# cong_effort: auto (default) | low | medium | high  -> setPlaceMode -place_global_cong_effort
#
# Writes into <outdir>: place_ref.tcl, innovus.log, place_design.def, congest_area.txt,
# summary.json.  Innovus 22.10 place_design has no -noCongRepair option (its parameter
# list is [-help][-concurrent_macros][-incremental][-noPrePlaceOpt][-sdp]), so the second
# variant is the congestion-effort knob instead.
#
# ROW SITE FIX: the s14 floorplan DEFs declare core ROWs with SITE "core7T" while every
# scc14nsfp standard cell declares SITE "90s9t_CoreSite" (identical 0.090 x 0.576
# geometry).  Innovus then raises IMPSP-365 and refinePlace treats every std cell as
# illegal, which blew nvdla_s HPWL from 4.10e6 to 1.00e7 um.  This script renames the ROW
# site in its staged copy of the DEF (geometry unchanged).  RUPLACE_ROW_SITE=keep
# reproduces the broken behaviour.
set -uo pipefail
case_name="${1:?case}"; out_dir="${2:?output dir}"; effort="${3:-auto}"
row_site_fix="${RUPLACE_ROW_SITE:-fix}"
WT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${REPO:-/mnt/nvme0n1/yifan/projs/DREAMPlace}"
meta="$REPO/data/s14/${case_name}.meta.json"
[[ -f "$meta" ]] || { echo "missing $meta" >&2; exit 2; }
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"
work="$REPO/data/s14/innovus_stage/place_ref_${case_name}_${effort}_${row_site_fix}"
rm -rf "$work"; mkdir -p "$work"
if [[ "${CONDA_DEFAULT_ENV:-}" != "placement" ]]; then
  set +u; source "$HOME/miniconda3/etc/profile.d/conda.sh"; conda activate placement; set -u
fi
unset CDS_LIC_FILE LM_LICENSE_FILE
python3 "$WT/tools/ruplace_innovus_place_ref_stage.py" "$meta" "$work" "$out_dir" "$effort" "$row_site_fix" || exit 3
cd "$work"
"$WT/tools/cadence_local.sh" -v 22 innovus -no_gui -batch -files "$work/place_ref.tcl" > "$out_dir/innovus.stdout" 2>&1
rc=$?
for f in innovus.log innovus.logv; do [[ -f "$work/$f" ]] && cp -f "$work/$f" "$out_dir/"; done
python3 "$WT/tools/ruplace_innovus_place_ref_parse.py" --case "$case_name" --effort "$effort" \
    --log "$out_dir/innovus.log" --stdout "$out_dir/innovus.stdout" \
    --congest "$out_dir/congest_area.txt" --rc "$rc" --out "$out_dir/summary.json"
echo "rc=$rc  out=$out_dir"
