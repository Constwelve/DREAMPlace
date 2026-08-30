"""RUDY and pin-RUDY evaluators over a placed LEF/DEF design."""

import time
import sys

from .base import EvaluationResult, RoutabilityEvaluator, map_statistics


def zero_map_for_nonempty_design(utilization, num_nets):
    return int(num_nets) > 0 and utilization.numel() > 0 and not bool(
        (utilization > 0).any().item()
    )


def routing_pin_coverage(pin_x, pin_y, xl, yl, xh, yh):
    """Summarize whether parsed pins can contribute to the routing grid."""
    import torch

    finite = torch.isfinite(pin_x) & torch.isfinite(pin_y)
    inside = finite & (pin_x >= xl) & (pin_x <= xh) & (pin_y >= yl) & (pin_y <= yh)
    num_pins = int(pin_x.numel())
    pins_in_region = int(inside.sum().item())
    return {
        "parsed_pins": num_pins,
        "pins_in_routing_region": pins_in_region,
        "pins_in_routing_region_ratio": pins_in_region / max(num_pins, 1),
    }


def zero_map_error(coverage):
    if coverage["parsed_pins"] and not coverage["pins_in_routing_region"]:
        return (
            "RUDY has no parsed pins inside the routing region; the DEF appears "
            "unplaced/collapsed or uses an incompatible coordinate system"
        )
    return (
        "RUDY produced an all-zero map for a nonempty design; "
        "the parsed routing-capacity/net contract is unsupported"
    )


def requested_routing_grid(placedb, options):
    route_size = options.get("route_size")
    default_x = int(placedb.num_routing_grids_x)
    default_y = int(placedb.num_routing_grids_y)
    num_bins_x = int(options.get(
        "route_x_size", route_size if route_size is not None else default_x
    ))
    num_bins_y = int(options.get(
        "route_y_size", route_size if route_size is not None else default_y
    ))
    if num_bins_x <= 0 or num_bins_y <= 0:
        raise ValueError("RUDY routing-grid dimensions must be positive")
    return num_bins_x, num_bins_y


class RudyEvaluator(RoutabilityEvaluator):
    name = "rudy"
    pin_rudy = False

    def evaluate(self, request):
        start = time.time()
        try:
            import numpy as np
            import torch
            import dreamplace
            sys.path.insert(0, str(__import__("pathlib").Path(dreamplace.__file__).resolve().parent))
            from dreamplace import Params, PlaceDB
            from dreamplace.ops.rudy.rudy import Rudy

            params = Params.Params()
            params.fromJson({
                "lef_input": request.lef_input,
                "def_input": request.def_input,
                "verilog_input": request.verilog_input,
                "gpu": 0,
                "num_threads": request.num_threads,
                "routability_opt_flag": 1,
            })
            placedb = PlaceDB.PlaceDB()
            placedb(params)
            dtype = torch.float64 if placedb.dtype == np.float64 else torch.float32
            node_x = torch.as_tensor(placedb.node_x, dtype=dtype)
            node_y = torch.as_tensor(placedb.node_y, dtype=dtype)
            pin2node = torch.as_tensor(placedb.pin2node_map, dtype=torch.long)
            pin_x = node_x[pin2node] + torch.as_tensor(placedb.pin_offset_x, dtype=dtype)
            pin_y = node_y[pin2node] + torch.as_tensor(placedb.pin_offset_y, dtype=dtype)
            pin_pos = torch.cat((pin_x, pin_y)).contiguous()
            coverage = routing_pin_coverage(
                pin_x, pin_y, placedb.routing_grid_xl, placedb.routing_grid_yl,
                placedb.routing_grid_xh, placedb.routing_grid_yh,
            )
            num_bins_x, num_bins_y = requested_routing_grid(
                placedb, request.options
            )
            common = dict(
                netpin_start=torch.as_tensor(placedb.flat_net2pin_start_map, dtype=torch.int32),
                flat_netpin=torch.as_tensor(placedb.flat_net2pin_map, dtype=torch.int32),
                net_weights=torch.as_tensor(placedb.net_weights, dtype=dtype),
                xl=placedb.routing_grid_xl,
                yl=placedb.routing_grid_yl,
                xh=placedb.routing_grid_xh,
                yh=placedb.routing_grid_yh,
                num_bins_x=num_bins_x,
                num_bins_y=num_bins_y,
                unit_horizontal_capacity=placedb.unit_horizontal_capacity,
                unit_vertical_capacity=placedb.unit_vertical_capacity,
                deterministic_flag=1,
            )
            utilization = Rudy(**common)(pin_pos)
            map_path = request.artifact("rudy_map.pt")
            torch.save(utilization, map_path)
            metrics = map_statistics(utilization)
            metrics.update({
                "route_x_size": num_bins_x,
                "route_y_size": num_bins_y,
            })
            metrics.update(coverage)
            if zero_map_for_nonempty_design(utilization, placedb.num_nets):
                return EvaluationResult(
                    backend=self.name,
                    design_name=request.design_name,
                    status="failed",
                    runtime_sec=time.time() - start,
                    metrics=metrics,
                    artifacts={"map": str(map_path)},
                    error=zero_map_error(coverage),
                )
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                runtime_sec=time.time() - start,
                metrics=metrics,
                artifacts={"map": str(map_path)},
            )
        except Exception as error:
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                error=str(error),
            )


class PinRudyEvaluator(RudyEvaluator):
    name = "pin_rudy"

    def evaluate(self, request):
        start = time.time()
        try:
            import numpy as np
            import torch
            import dreamplace
            sys.path.insert(0, str(__import__("pathlib").Path(dreamplace.__file__).resolve().parent))
            from dreamplace import Params, PlaceDB
            from dreamplace.ops.pinrudy.pinrudy import PinRudy

            params = Params.Params()
            params.fromJson({
                "lef_input": request.lef_input,
                "def_input": request.def_input,
                "verilog_input": request.verilog_input,
                "gpu": 0,
                "num_threads": request.num_threads,
                "routability_opt_flag": 1,
            })
            placedb = PlaceDB.PlaceDB()
            placedb(params)
            dtype = torch.float64 if placedb.dtype == np.float64 else torch.float32
            node_x = torch.as_tensor(placedb.node_x, dtype=dtype)
            node_y = torch.as_tensor(placedb.node_y, dtype=dtype)
            pin2node = torch.as_tensor(placedb.pin2node_map, dtype=torch.long)
            pin_pos = torch.cat((
                node_x[pin2node] + torch.as_tensor(placedb.pin_offset_x, dtype=dtype),
                node_y[pin2node] + torch.as_tensor(placedb.pin_offset_y, dtype=dtype),
            )).contiguous()
            num_pins = pin_pos.numel() // 2
            coverage = routing_pin_coverage(
                pin_pos[:num_pins], pin_pos[num_pins:],
                placedb.routing_grid_xl, placedb.routing_grid_yl,
                placedb.routing_grid_xh, placedb.routing_grid_yh,
            )
            num_bins_x, num_bins_y = requested_routing_grid(
                placedb, request.options
            )
            utilization = PinRudy(
                netpin_start=torch.as_tensor(placedb.flat_net2pin_start_map, dtype=torch.int32),
                flat_netpin=torch.as_tensor(placedb.flat_net2pin_map, dtype=torch.int32),
                net_weights=torch.as_tensor(placedb.net_weights, dtype=dtype),
                xl=placedb.routing_grid_xl,
                yl=placedb.routing_grid_yl,
                xh=placedb.routing_grid_xh,
                yh=placedb.routing_grid_yh,
                num_bins_x=num_bins_x,
                num_bins_y=num_bins_y,
                unit_horizontal_capacity=placedb.unit_horizontal_capacity,
                unit_vertical_capacity=placedb.unit_vertical_capacity,
                deterministic_flag=1,
            )(pin_pos)
            mean = utilization.mean().clamp_min(1e-12)
            normalized = utilization / mean
            map_path = request.artifact("pin_rudy_map.pt")
            torch.save(utilization, map_path)
            metrics = map_statistics(normalized)
            metrics["raw_mean"] = float(mean.item())
            metrics.update({
                "route_x_size": num_bins_x,
                "route_y_size": num_bins_y,
            })
            metrics.update(coverage)
            if zero_map_for_nonempty_design(utilization, placedb.num_nets):
                return EvaluationResult(
                    backend=self.name,
                    design_name=request.design_name,
                    status="failed",
                    runtime_sec=time.time() - start,
                    metrics=metrics,
                    artifacts={"map": str(map_path)},
                    error=zero_map_error(coverage).replace("RUDY", "pin-RUDY", 1),
                )
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                runtime_sec=time.time() - start,
                metrics=metrics,
                artifacts={"map": str(map_path)},
            )
        except Exception as error:
            return EvaluationResult(
                backend=self.name,
                design_name=request.design_name,
                status="failed",
                runtime_sec=time.time() - start,
                error=str(error),
            )
