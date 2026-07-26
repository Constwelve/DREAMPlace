"""Xplace GGR and bundled GPUGR evaluator adapters."""

from pathlib import Path
import sys
import time

from .base import EvaluationResult, RoutabilityEvaluator, map_statistics


DEFAULT_ROUTE_SIZE = 128


class XplaceEvaluator(RoutabilityEvaluator):
    name = "xplace"
    backend = "xplace"

    def evaluate(self, request):
        start = time.time()
        result_path = request.artifact("%s.pt" % self.name)
        route_size = int(request.options.get("route_size", DEFAULT_ROUTE_SIZE))
        route_x_size = int(request.options.get("route_x_size", route_size))
        route_y_size = int(request.options.get("route_y_size", route_size))
        command = [
            sys.executable, "-m", "dreamplace.ops.gpugr.run_gpugr",
            "--backend", self.backend,
            "--design-name", request.design_name,
            "--def-input", request.def_input,
            "--output", str(result_path),
            "--gpu", str(request.options.get("gpu", 0)),
            "--num-threads", str(request.num_threads),
            "--rrr-iters", str(request.options.get("rrr_iters", 1)),
            "--route-x-size", str(route_x_size),
            "--route-y-size", str(route_y_size),
        ]
        for lef in request.lef_input:
            command.extend(["--lef-input", lef])
        if request.verilog_input:
            command.extend(["--verilog-input", request.verilog_input])
        root = request.options.get("xplace_root", "")
        if root:
            command.extend(["--xplace-root", root])
        # Launch from the package root that supplied this adapter. Otherwise a
        # source-worktree cwd can shadow the installed package and make the
        # bundled native GPUGR assets appear to be missing.
        package_root = Path(__file__).resolve().parents[3]
        output, failure = self.run(request, command, cwd=package_root)
        if failure:
            return failure
        try:
            import torch

            data = torch.load(result_path, map_location="cpu")
            if "utilization_map" not in data:
                raise KeyError("utilization_map")
            metrics = dict(data.get("metrics", {}))
            metrics.update(map_statistics(data["utilization_map"]))
        except Exception as error:
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                artifacts={"result": str(result_path),
                           "log": str(request.artifact("%s.log" % self.name))},
                error="invalid %s result artifact: %s" % (self.name, error),
            )
        return EvaluationResult(
            backend=self.name,
            design_name=request.design_name,
            runtime_sec=time.time() - start,
            metrics=metrics,
            artifacts={"result": str(result_path), "log": str(request.artifact("%s.log" % self.name))},
        )


class BundledGPUGREvaluator(XplaceEvaluator):
    name = "gpugr"
    backend = "gpugr"
