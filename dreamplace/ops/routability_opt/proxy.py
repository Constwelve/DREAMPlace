"""Congestion-signal providers used by routability plugins."""

import torch

from dreamplace.ops.gpugr.gpugr import build_gpugr_backend
from dreamplace.ops.routability_opt.plugin_base import CongestionSignal


class CongestionProxy:
    def evaluate(self, pos, iteration, refresh=False):
        raise NotImplementedError


class CachedProxy(CongestionProxy):
    def __init__(self, refresh_interval):
        self.refresh_interval = max(1, int(refresh_interval))
        self.last_iteration = -1
        self.last_signal = None

    def should_refresh(self, iteration, refresh):
        return (
            refresh
            or self.last_signal is None
            or iteration - self.last_iteration >= self.refresh_interval
        )


class GPUGRProxy(CachedProxy):
    def __init__(self, params, placedb, data_collections):
        super().__init__(getattr(params, "ruplace_proxy_refresh_interval", 20))
        self.backend = build_gpugr_backend(
            params, placedb=placedb, data_collections=data_collections
        )

    def evaluate(self, pos, iteration, refresh=False):
        if self.should_refresh(iteration, refresh):
            route = self.backend.run_route(pos)
            self.last_signal = CongestionSignal(
                utilization_map=route.utilization_map,
                overflow_map=route.overflow_map,
                hv_overflow_map=getattr(route, "hv_overflow_map", None),
                metrics=dict(getattr(route, "metrics", {})),
                source="gpugr",
                native=route,
            )
            self.last_iteration = iteration
        return self.last_signal


class MapOpProxy(CachedProxy):
    def __init__(self, name, op, refresh_interval=1, pin_op=None):
        super().__init__(refresh_interval)
        self.name = name
        self.op = op
        self.pin_op = pin_op

    def evaluate(self, pos, iteration, refresh=False):
        if self.should_refresh(iteration, refresh):
            utilization = self.op(pos)
            pin_map = self.pin_op(pos) if self.pin_op is not None else None
            self.last_signal = CongestionSignal(
                utilization_map=utilization,
                pin_utilization_map=pin_map,
                source=self.name,
                metrics={"mean_utilization": float(utilization.mean().item())},
            )
            self.last_iteration = iteration
        return self.last_signal


class CompositeProxy(CachedProxy):
    def __init__(self, proxies, weights, refresh_interval=1):
        super().__init__(refresh_interval)
        self.proxies = proxies
        total = sum(weights)
        self.weights = [w / total for w in weights]

    def evaluate(self, pos, iteration, refresh=False):
        if self.should_refresh(iteration, refresh):
            signals = [p.evaluate(pos, iteration, refresh) for p in self.proxies]
            shape = signals[0].utilization_map.shape
            maps = []
            for signal in signals:
                value = signal.utilization_map
                if value.shape != shape:
                    value = torch.nn.functional.interpolate(
                        value[None, None], size=shape, mode="bilinear", align_corners=False
                    )[0, 0]
                maps.append(value)
            utilization = sum(w * value for w, value in zip(self.weights, maps))
            self.last_signal = CongestionSignal(
                utilization_map=utilization,
                source="composite",
                metrics={"sources": [s.source for s in signals]},
            )
            self.last_iteration = iteration
        return self.last_signal


def build_congestion_proxy(params, placedb, data_collections, op_collections):
    name = str(getattr(params, "ruplace_proxy", "gpugr")).lower()
    refresh = int(getattr(params, "ruplace_proxy_refresh_interval", 20))
    if name in ("gpugr", "xplace"):
        return GPUGRProxy(params, placedb, data_collections)
    if name == "rudy":
        return MapOpProxy(
            "rudy", op_collections.route_utilization_map_op, refresh,
            op_collections.pin_utilization_map_op,
        )
    if name in ("pin", "pin_density"):
        return MapOpProxy("pin_density", op_collections.pin_utilization_map_op, refresh)
    if name == "nctugr":
        if op_collections.nctugr_congestion_map_op is None:
            raise RuntimeError("nctugr proxy requires adjust_nctugr_area_flag=1")
        return MapOpProxy("nctugr", op_collections.nctugr_congestion_map_op, refresh)
    if name in ("rudy_pin", "rudy+pin"):
        return CompositeProxy(
            [
                MapOpProxy("rudy", op_collections.route_utilization_map_op, refresh),
                MapOpProxy("pin_density", op_collections.pin_utilization_map_op, refresh),
            ],
            [
                float(getattr(params, "ruplace_proxy_route_weight", 0.75)),
                float(getattr(params, "ruplace_proxy_pin_weight", 0.25)),
            ],
            refresh,
        )
    raise ValueError("Unknown routability proxy: %s" % name)
