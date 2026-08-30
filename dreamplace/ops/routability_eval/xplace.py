"""Xplace GGR and bundled GPUGR evaluator adapters."""

from pathlib import Path
import sys
import time

from .base import (
    EvaluationResult,
    RoutabilityEvaluator,
    directional_map_statistics,
    map_statistics,
)


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
            "--def-input", str(Path(request.def_input).resolve()),
            "--output", str(result_path),
            "--gpu", str(request.options.get("gpu", 0)),
            "--num-threads", str(request.num_threads),
            "--rrr-iters", str(request.options.get("rrr_iters", 1)),
            "--route-x-size", str(route_x_size),
            "--route-y-size", str(route_y_size),
        ]
        for lef in request.lef_input:
            command.extend(["--lef-input", str(Path(lef).resolve())])
        if request.verilog_input:
            command.extend([
                "--verilog-input", str(Path(request.verilog_input).resolve())
            ])
        root = request.options.get("xplace_root", "")
        if root:
            command.extend(["--xplace-root", str(Path(root).resolve())])
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
            required_directional_schema = int(request.options.get(
                "required_directional_metric_schema_version", 0
            ))
            if required_directional_schema >= 2 and "hv_utilization_map" not in data:
                raise KeyError(
                    "hv_utilization_map required by directional metric schema v%d"
                    % required_directional_schema
                )
            metrics = dict(data.get("metrics", {}))
            metrics.update(map_statistics(data["utilization_map"]))
            metrics.update({
                "route_x_size": route_x_size,
                "route_y_size": route_y_size,
            })
            if "hv_utilization_map" in data:
                metrics.update(directional_map_statistics(data["hv_utilization_map"]))
                metrics["directional_metric_schema_version"] = 2
            if (
                required_directional_schema
                and metrics.get("directional_metric_schema_version")
                != required_directional_schema
            ):
                raise ValueError(
                    "directional metric schema version %s does not match required v%d"
                    % (
                        metrics.get("directional_metric_schema_version"),
                        required_directional_schema,
                    )
                )
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
