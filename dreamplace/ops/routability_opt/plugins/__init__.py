"""Registry for independently selectable routability plugins."""

from .aggregate_cvar_gradient import AggregateCVaRGradientPlugin
from .aggregate_pnorm_gradient import AggregatePNormGradientPlugin
from .connection_routeforce import ConnectionRouteForcePlugin
from .directional_cvar_gradient import DirectionalCVaRGradientPlugin
from .directional_excess_cvar_gradient import DirectionalExcessCVaRGradientPlugin
from .directional_net_contraction import DirectionalNetContractionPlugin
from .directional_local_gradient import DirectionalLocalCongestionGradientPlugin
from .directional_path_spreading import DirectionalPathSpreadingPlugin
from .directional_virtual_cell import DirectionalVirtualCellNetMovingPlugin
from .local_gradient import LocalCongestionGradientPlugin
from .momentum_inflation import MomentumInflationPlugin
from .multisegment_connection_routeforce import MultiSegmentConnectionRouteForcePlugin
from .net_overlap import NetOverlapRemovalPlugin
from .net_relaxation import CongestionNetRelaxationPlugin
from .net_weighting import CongestionNetWeightingPlugin
from .path_inflation import RoutingPathInflationPlugin
from .pin_porosity import PinDensityPorosityPlugin
from .poisson_force import PoissonCongestionForcePlugin
from .projected_connection_routeforce import ProjectedConnectionRouteForcePlugin
from .route_inflation import RouteInflationPlugin
from .routeforce import RouteForcePlugin
from .routed_overflow_net_contraction import RoutedOverflowNetContractionPlugin
from .virtual_cell import VirtualCellNetMovingPlugin
from .whitespace import WhitespaceAllocationPlugin


PLUGIN_REGISTRY = {
    "aggregate_cvar_gradient": AggregateCVaRGradientPlugin,
    "aggregate_pnorm_gradient": AggregatePNormGradientPlugin,
    "connection_routeforce": ConnectionRouteForcePlugin,
    "multisegment_connection_routeforce": MultiSegmentConnectionRouteForcePlugin,
    "projected_connection_routeforce": ProjectedConnectionRouteForcePlugin,
    "directional_cvar_gradient": DirectionalCVaRGradientPlugin,
    "directional_excess_cvar_gradient": DirectionalExcessCVaRGradientPlugin,
    "directional_net_contraction": DirectionalNetContractionPlugin,
    "directional_local_gradient": DirectionalLocalCongestionGradientPlugin,
    "directional_path_spreading": DirectionalPathSpreadingPlugin,
    "directional_virtual_cell": DirectionalVirtualCellNetMovingPlugin,
    "route_inflation": RouteInflationPlugin,
    "momentum_inflation": MomentumInflationPlugin,
    "path_inflation": RoutingPathInflationPlugin,
    "local_gradient": LocalCongestionGradientPlugin,
    "poisson_force": PoissonCongestionForcePlugin,
    "net_weighting": CongestionNetWeightingPlugin,
    "net_relaxation": CongestionNetRelaxationPlugin,
    "net_overlap": NetOverlapRemovalPlugin,
    "pin_porosity": PinDensityPorosityPlugin,
    "whitespace": WhitespaceAllocationPlugin,
    "routeforce": RouteForcePlugin,
    "routed_overflow_net_contraction": RoutedOverflowNetContractionPlugin,
    "virtual_cell": VirtualCellNetMovingPlugin,
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
    net_weight_mutators = {"net_weighting", "net_relaxation"}.intersection(names)
    if len(net_weight_mutators) > 1:
        raise ValueError(
            "net_weighting and net_relaxation are mutually exclusive"
        )
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
