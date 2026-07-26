"""Common evaluator request/result types and subprocess support."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import subprocess
import time


@dataclass
class EvaluationRequest:
    design_name: str
    lef_input: list = field(default_factory=list)
    def_input: str = ""
    verilog_input: str = ""
    aux_input: str = ""
    output_dir: str = ""
    num_threads: int = 8
    timeout_sec: int = 0
    options: dict = field(default_factory=dict)

    def artifact(self, name):
        path = Path(self.output_dir or ".")
        path.mkdir(parents=True, exist_ok=True)
        return path / name


@dataclass
class EvaluationResult:
    backend: str
    design_name: str
    status: str = "ok"
    runtime_sec: float = 0.0
    metrics: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    error: str = ""
    schema_version: int = 1

    def to_dict(self):
        return asdict(self)

    def write_json(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


class RoutabilityEvaluator:
    name = "base"

    def evaluate(self, request):
        raise NotImplementedError

    def run(self, request, command, cwd=None, env=None):
        log = request.artifact("%s.log" % self.name)
        start = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=request.timeout_sec or None,
                check=False,
            )
            log.write_text(completed.stdout or "")
            if completed.returncode:
                return None, EvaluationResult(
                    backend=self.name,
                    design_name=request.design_name,
                    status="failed",
                    runtime_sec=time.time() - start,
                    artifacts={"log": str(log)},
                    error="command exited with status %d" % completed.returncode,
                )
            return completed.stdout or "", None
        except subprocess.TimeoutExpired as error:
            output = error.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            log.write_text(output)
            return None, EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="timeout",
                runtime_sec=time.time() - start,
                artifacts={"log": str(log)},
                error="timeout after %s seconds" % request.timeout_sec,
            )


def map_statistics(value_map, overflow_threshold=1.0):
    import torch

    value = torch.nan_to_num(value_map.detach().float().cpu(), nan=0.0, posinf=0.0, neginf=0.0)
    flat = value.flatten()
    overflow = (flat - float(overflow_threshold)).clamp_min(0.0)
    mean = float(flat.mean().item()) if flat.numel() else 0.0
    p90 = float(torch.quantile(flat, 0.90).item()) if flat.numel() else 0.0
    p95 = float(torch.quantile(flat, 0.95).item()) if flat.numel() else 0.0
    p99 = float(torch.quantile(flat, 0.99).item()) if flat.numel() else 0.0
    return {
        "utilization_mean": mean,
        "utilization_max": float(flat.max().item()) if flat.numel() else 0.0,
        "utilization_p90": p90,
        "utilization_p95": p95,
        "utilization_p99": p99,
        "overflow_sum": float(overflow.sum().item()),
        "overflow_bins": int((overflow > 0).sum().item()),
        "congestion_score": p99 / max(mean, 1e-12) if flat.numel() else 0.0,
        "congestion_score_p95": p95 / max(mean, 1e-12) if flat.numel() else 0.0,
        "congestion_score_p99": p99 / max(mean, 1e-12) if flat.numel() else 0.0,
    }
