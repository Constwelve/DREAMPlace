#!/usr/bin/env bash
# cadence — run a Cadence tool (genus/innovus/quantus/...) LOCALLY in a docker container.
#
#   cadence [-v 21|22|25] <tool> [args...]
#
# Default version = 22 (matches the wuxi flow's Innovus 22). All versions run in the
# rockylinux-xfce:8.10 image, which (unlike the bare Ubuntu host) provides libXp.so.6 that
# Cadence 25.1 needs, and centos7.9-style glibc that 21/22 tolerate. Licensing uses the
# container-local license file (CDS_LIC_ONLY=1); the host CDS_LIC_FILE/LM_LICENSE_FILE are
# deliberately NOT forwarded (a host 5280@... value clobbers the file and breaks checkout).
#
#   cadence genus -f run.tcl              # genus 22 (default)
#   cadence -v 25 innovus -no_gui -files run.tcl
#   cadence -v 21 innovus -init x.tcl
#   cadence -v 25 quantus -cmd run.ccl 5_route.def
#
# GUI: pass -gui and the tool's own GUI flag; the host X11 socket is mounted when present.

set -euo pipefail

# Machine-specific settings, all env-overridable: CADENCE_IMAGE, plus the host
# install roots and repo mount defined a few lines below.
IMAGE="${CADENCE_IMAGE:-rockylinux-xfce:8.10}"
VER="22"
WANT_GUI="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--version) VER="$2"; shift 2 ;;
    -v2[125]) VER="${1#-v}"; shift ;;          # allow -v21 / -v22 / -v25
    --gui) WANT_GUI="1"; shift ;;
    --image) IMAGE="$2"; shift 2 ;;
    --) shift; break ;;
    -*) break ;;                                # first tool flag → stop parsing wrapper opts
    *) break ;;
  esac
done

TOOL="${1:-}"; shift || true
if [[ -z "$TOOL" ]]; then
  echo "usage: cadence [-v 21|22|25] <genus|innovus|quantus|...> [args...]" >&2
  exit 2
fi

# ---- host paths (edit here if installs move) ----
# Host install roots and the repo mount; override any of them in the environment.
EDA_EXPORT_HOST="${EDA_EXPORT_HOST:-/mnt/nvme0n1/yifan/projs/EDASoftware/export}"   # -> /export (v21 tools + license.dat)
DDI22_HOST="${DDI22_HOST:-/mnt/nvme0n1/yifan/projs/EDASoftware/DDI22.10.000}"
DDI25_HOST="${DDI25_HOST:-/mnt/nvme0n1/yifan/projs/EDASoftware/cadence/DDI/2025.10.000}"
REPO="${REPO:-/mnt/nvme0n1/yifan/projs/DREAMPlace}"   # mounted rw so runs stage inside this repo
LIC="/export/SoftWare/Cadence/license/license.dat"

# ---- per-version tool root + binary ----
VER_MOUNTS=()
case "$VER" in
  21)
    ROOT="/export/SoftWare/Cadence"
    declare -A BINS=([genus]="$ROOT/GENUS21.15.000/bin/genus" [innovus]="$ROOT/INNOVUS21.15.000/bin/innovus")
    TOOLPATH="$ROOT/GENUS21.15.000/bin:$ROOT/INNOVUS21.15.000/bin:$ROOT/INNOVUS21.15.000/tools.lnx86/bin"
    ;;
  22)
    ROOT="/eda/DDI22.10.000"
    VER_MOUNTS+=(-v "${DDI22_HOST}:${ROOT}:ro")
    declare -A BINS=([genus]="$ROOT/GENUS221/bin/genus" [innovus]="$ROOT/INNOVUS221/bin/innovus")
    TOOLPATH="$ROOT/GENUS221/bin:$ROOT/INNOVUS221/bin:$ROOT/INNOVUS221/tools.lnx86/bin"
    ;;
  25)
    ROOT="${DDI25_HOST}"
    VER_MOUNTS+=(-v "${DDI25_HOST}:${DDI25_HOST}:ro")
    declare -A BINS=([genus]="$ROOT/bin/genus" [innovus]="$ROOT/bin/innovus" [quantus]="$ROOT/bin/quantus" [tempus]="$ROOT/bin/tempus")
    TOOLPATH="$ROOT/bin:$ROOT/tools.lnx86/bin"
    ;;
  *) echo "cadence: unknown version '$VER' (use 21|22|25)" >&2; exit 2 ;;
esac

BIN="${BINS[$TOOL]:-}"
if [[ -z "$BIN" ]]; then
  # fall back to <root>/bin/<tool> for tools not in the map
  BIN="${ROOT%/}/bin/${TOOL}"
fi

# ---- optional mounts ----
EXTRA_MOUNTS=()
[[ -d /home/yifan/data ]] && EXTRA_MOUNTS+=(-v /home/yifan/data:/home/yifan/data:ro)
[[ -d /home/yifan/.claude/jobs ]] && EXTRA_MOUNTS+=(-v /home/yifan/.claude/jobs:/home/yifan/.claude/jobs)

# ---- X11 (only if --gui) ----
X11_ARGS=()
if [[ "$WANT_GUI" == "1" && -d /tmp/.X11-unix ]]; then
  _D="${DISPLAY:-:0}"; X11_ARGS+=(-v /tmp/.X11-unix:/tmp/.X11-unix -e "DISPLAY=${_D}")
  [[ -f "${XAUTHORITY:-$HOME/.Xauthority}" ]] && X11_ARGS+=(-v "${XAUTHORITY:-$HOME/.Xauthority}:/tmp/.Xauthority:ro" -e "XAUTHORITY=/tmp/.Xauthority")
fi

# ---- forward exported env EXCEPT container-breakers and the license vars (avoid 5280 leak) ----
ENV_ARGS=()
while IFS= read -r v; do
  case "$v" in
    PATH|LD_LIBRARY_PATH|LD_PRELOAD|HOME|USER|LOGNAME|HOSTNAME|TERM|TERMINFO|\
    SHELL|SHLVL|PWD|OLDPWD|_|DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS|\
    CDS_LIC_FILE|LM_LICENSE_FILE|SNPSLMD_LICENSE_FILE|\
    SSH_AUTH_SOCK|SSH_CLIENT|SSH_CONNECTION|SSH_TTY|XDG_*|LESSOPEN|LESSCLOSE|\
    OPENROAD_EXE|YOSYS_EXE|STA_EXE|GENUS_EXE|INNOVUS_EXE|PYTHON_EXE) continue ;;
  esac
  ENV_ARGS+=(-e "$v")
done < <(compgen -e)

exec docker run --rm \
  --hostname "cadence${VER}-rocky8" \
  -v /etc/passwd:/etc/passwd:ro -v /etc/group:/etc/group:ro \
  --tmpfs /tmp:exec,mode=1777 \
  --workdir "$(pwd)" \
  -v "${EDA_EXPORT_HOST}:/export:ro" \
  "${VER_MOUNTS[@]}" \
  -v "${REPO}:${REPO}" \
  "${EXTRA_MOUNTS[@]}" "${X11_ARGS[@]}" \
  -e "CDS_LIC_FILE=${LIC}" -e "CDS_LIC_ONLY=1" \
  -e "SOFT_INST_DIR=${ROOT}" \
  -e "USER=${USER:-root}" -e "HOME=${HOME:-/root}" -e "LOGNAME=${LOGNAME:-${USER:-root}}" \
  -e "PATH=${TOOLPATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  "${ENV_ARGS[@]}" \
  "${IMAGE}" \
  "${BIN}" "$@"
