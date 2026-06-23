"""Backend-neutral GPU global-routing API."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GPUGRRequest:
    """Inputs for a standalone global-routing evaluation."""

    design_name: str
    lef_input: List[str] = field(default_factory=list)
    def_input: str = ""
    verilog_input: str = ""
    cap_input: str = ""
    net_input: str = ""
    output_dir: str = ""
    backend: str = "xplace"
    gpu: int = 0
    num_threads: int = 8
    route_x_size: int = 0
    route_y_size: int = 0
    rrr_iters: int = 1

    def output_path(self, name: str) -> Path:
        base = Path(self.output_dir or ".")
        base.mkdir(parents=True, exist_ok=True)
        return base / name


@dataclass
class GPUGRResult:
    """Normalized global-routing result returned by any backend."""

    overflow_map: Any = None
    utilization_map: Any = None
    hv_overflow_map: Any = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    routeforce: Any = None
    artifacts: Dict[str, str] = field(default_factory=dict)


class GPUGRBackend:
    """Abstract backend contract for DREAMPlace global-routing integration."""

    supports_admm_gradient = False

    def route(self, request: GPUGRRequest, pos=None) -> GPUGRResult:
        raise NotImplementedError
