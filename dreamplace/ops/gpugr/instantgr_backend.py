"""Optional InstantGR backend.

V1 supports InstantGR's native .cap/.net inputs only. LEF/DEF export is kept
outside this backend until the format bridge is implemented.
"""

import os
import re
import subprocess
from pathlib import Path

from dreamplace.ops.gpugr.base import GPUGRBackend, GPUGRRequest, GPUGRResult


class InstantGRBackend(GPUGRBackend):
    supports_admm_gradient = False

    def __init__(self, params=None):
        self.params = params
        self.root = getattr(params, "ruplace_instantgr_root", "thirdparty/InstantGR") if params else "thirdparty/InstantGR"
        self.binary = getattr(params, "ruplace_instantgr_binary", "") if params else ""

    def _root_path(self):
        return Path(os.path.expandvars(os.path.expanduser(str(self.root))))

    def _binary(self):
        if self.binary:
            return os.path.expandvars(os.path.expanduser(str(self.binary)))
        root = self._root_path()
        candidates = [
            root / "run" / "InstantGR",
            root / "InstantGR",
        ]
        for candidate in candidates:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        return str(candidates[0])

    def _evaluator(self):
        root = self._root_path()
        candidates = [
            root / "run" / "evaluator",
            root / "evaluator",
        ]
        for candidate in candidates:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        return ""

    @staticmethod
    def _parse_for_stat(text):
        match = re.search(r"FOR_STAT\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", text)
        if not match:
            return {}
        wl, via, overflow, total = (float(match.group(i)) for i in range(1, 5))
        return {
            "wirelength_cost": wl,
            "via_cost": via,
            "overflow_cost": overflow,
            "total_cost": total,
        }

    def route(self, request: GPUGRRequest, pos=None):
        cap = request.cap_input or getattr(self.params, "ruplace_instantgr_cap_input", "")
        net = request.net_input or getattr(self.params, "ruplace_instantgr_net_input", "")
        if not cap or not net:
            raise RuntimeError(
                "InstantGR backend requires native .cap/.net inputs; LEF/DEF export is not implemented in v1"
            )
        cap = os.path.abspath(cap)
        net = os.path.abspath(net)
        if not os.path.exists(cap) or not os.path.exists(net):
            raise FileNotFoundError("InstantGR cap/net input missing: %s %s" % (cap, net))
        out_dir = Path(request.output_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        route_out = out_dir / (request.design_name + ".instantgr.out")
        log_path = out_dir / (request.design_name + ".instantgr.log")
        eval_log_path = out_dir / (request.design_name + ".instantgr_eval.log")
        binary = self._binary()
        if not os.path.exists(binary):
            raise FileNotFoundError(
                "InstantGR executable missing: %s; run tools/build_instantgr.sh %s"
                % (binary, self._root_path())
            )
        cmd = [binary, "-cap", cap, "-net", net, "-out", str(route_out)]
        with log_path.open("w") as log:
            log.write("$ %s\n\n" % " ".join(cmd))
            log.flush()
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            raise RuntimeError("InstantGR failed with code %d; see %s" % (proc.returncode, log_path))
        metrics = {"backend": "instantgr"}
        artifacts = {"route_output": str(route_out), "log": str(log_path)}
        evaluator = self._evaluator()
        if evaluator:
            eval_cmd = [evaluator, cap, net, str(route_out)]
            with eval_log_path.open("w") as log:
                log.write("$ %s\n\n" % " ".join(eval_cmd))
                log.flush()
                eval_proc = subprocess.run(eval_cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
            artifacts["eval_log"] = str(eval_log_path)
            if eval_proc.returncode == 0:
                metrics.update(self._parse_for_stat(eval_log_path.read_text(errors="ignore")))
        return GPUGRResult(
            metrics=metrics,
            artifacts=artifacts,
        )
