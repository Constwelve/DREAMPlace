#!/usr/bin/env bash
# Score one placed DEF of an s14 case with Cadence Innovus early global route, entirely inside this repo.
#   tools/ruplace_s14_innovus_eval.sh <case> <placed.def> <output_dir> [global|detailed]
# Uses the routability_eval Innovus adapter with its two outside-the-repo defaults overridden
# (staging root -> data/s14/innovus_stage, launcher -> tools/cadence_local.sh). Prints one CSV line:
#   case,def,status,wirelength,horizontal_overflow,vertical_overflow,vias,runtime_sec,egr_h_pct,egr_v_pct
set -uo pipefail
case_name="${1:?case}"; placed_def="${2:?placed def}"; out_dir="${3:?output dir}"; mode="${4:-global}"
# Machine-specific root, env-overridable:
#   REPO  checkout that holds the staged s14 data (data/s14/<case>.meta.json, data/s14/innovus_stage),
#         i.e. the one tools/ruplace_s14_prep.py staged into -- not necessarily this worktree.
WT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${REPO:-/mnt/nvme0n1/yifan/projs/DREAMPlace}"
meta="$REPO/data/s14/${case_name}.meta.json"
[[ -f "$meta" ]] || { echo "missing $meta (run tools/ruplace_s14_prep.py --case $case_name)" >&2; exit 2; }
stage="$REPO/data/s14/innovus_stage"; mkdir -p "$stage" "$out_dir"
# conda's deactivate hook is not set -u clean; only (re)activate when needed, with -u off.
if [[ "${CONDA_DEFAULT_ENV:-}" != "placement" ]]; then
  set +u; source "$HOME/miniconda3/etc/profile.d/conda.sh"; conda activate placement; set -u
fi
unset CDS_LIC_FILE LM_LICENSE_FILE
mapfile -t lef_args < <(python3 -c "import json,sys; [print('--lef-input', p) for p in json.load(open(sys.argv[1]))['lef_input']]" "$meta" | tr ' ' '\n')
top=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['top_cell'])" "$meta")
verilog=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['eval_verilog_input'])" "$meta")
cd "$WT"
python3 tools/routability_evaluate.py --backend innovus --design-name "$top" "${lef_args[@]}" \
  --def-input "$placed_def" --verilog-input "$verilog" --output-dir "$out_dir" --num-threads 8 \
  --option "cadence_mounted_root=$stage" --option "cadence_wrapper=$REPO/tools/cadence_local.sh" \
  --option "innovus_route_mode=$mode" --option innovus_version=22 \
  --option "innovus_dump_congest_area=${DUMP_CONGEST:-0}" > "$out_dir/evaluate.stdout" 2>&1
rc=$?
python3 - "$case_name" "$placed_def" "$out_dir/innovus.json" "$rc" <<'PY'
import json, sys
case, d, path, rc = sys.argv[1:]
try:
    r = json.load(open(path)); m = r.get("metrics", {})
    # egr_h_pct/egr_v_pct are the Innovus NR-eGR H/V congestion percentages; appended at the
    # END of the line so existing positional consumers of fields 1-8 keep working.
    print(",".join(str(x) for x in (case, d, r.get("status"), m.get("wirelength", ""), m.get("horizontal_overflow", ""),
                                    m.get("vertical_overflow", ""), m.get("vias", ""), round(r.get("runtime_sec", 0), 1),
                                    m.get("egr_horizontal_congestion", ""), m.get("egr_vertical_congestion", ""))))
    if r.get("error"): print("error:", r["error"], file=sys.stderr)
except Exception as e:
    print(",".join((case, d, "no_result(rc=%s)" % rc, "", "", "", "", "", "", "")))
PY
