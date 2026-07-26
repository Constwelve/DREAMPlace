"""Registry for independently selectable routability plugins."""

from .local_gradient import LocalCongestionGradientPlugin
from .momentum_inflation import MomentumInflationPlugin
from .net_overlap import NetOverlapRemovalPlugin
from .net_weighting import CongestionNetWeightingPlugin
from .path_inflation import RoutingPathInflationPlugin
from .pin_porosity import PinDensityPorosityPlugin
from .poisson_force import PoissonCongestionForcePlugin
from .route_inflation import RouteInflationPlugin
from .routeforce import RouteForcePlugin
from .whitespace import WhitespaceAllocationPlugin


PLUGIN_REGISTRY = {
    "route_inflation": RouteInflationPlugin,
    "momentum_inflation": MomentumInflationPlugin,
    "path_inflation": RoutingPathInflationPlugin,
    "local_gradient": LocalCongestionGradientPlugin,
    "poisson_force": PoissonCongestionForcePlugin,
    "net_weighting": CongestionNetWeightingPlugin,
    "net_overlap": NetOverlapRemovalPlugin,
    "pin_porosity": PinDensityPorosityPlugin,
    "whitespace": WhitespaceAllocationPlugin,
    "routeforce": RouteForcePlugin,
}


def parse_plugin_names(value):
    if isinstance(value, str):
        return [name.strip().lower() for name in value.split(",") if name.strip()]
    return [str(name).strip().lower() for name in (value or []) if str(name).strip()]


def build_plugins(params, placedb, data_collections):
    plugins = []
    names = parse_plugin_names(getattr(params, "ruplace_plugins", []))
    if len(names) != len(set(names)):
        raise ValueError("ruplace_plugins contains duplicate plugin names")
    for name in names:
        try:
            plugin_cls = PLUGIN_REGISTRY[name]
        except KeyError:
            raise ValueError(
                "Unknown routability plugin %s; choices: %s"
                % (name, ", ".join(sorted(PLUGIN_REGISTRY)))
            )
        plugins.append(plugin_cls(params, placedb, data_collections))
    return plugins


__all__ = ["PLUGIN_REGISTRY", "build_plugins", "parse_plugin_names"]
