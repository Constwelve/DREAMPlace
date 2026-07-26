"""Routing-path footprint padding inspired by Ripple 2.0 and PUFFER."""

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins.utils import node_footprint_average
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation


class RoutingPathInflationPlugin(RoutabilityPlugin):
    name = "path_inflation"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.engine = RUPlaceInflation(params, placedb, data_collections)
        self.rounds = 0

    def maybe_adjust_area(self, pos, model, context):
        if self.rounds >= int(getattr(self.params, "ruplace_path_inflate_rounds", 8)):
            return False
        signal = context.signal(pos, refresh=True)
        exposure = node_footprint_average(context, pos, signal.overflow_map)
        gamma = float(getattr(self.params, "ruplace_path_inflate_gamma", 0.35))
        target = self.engine.current_inflate_ratio.to(pos.device, pos.dtype) + gamma * exposure
        changed = self.engine.apply_node_ratios(pos, target)
        self.rounds += 1
        self.metrics = {
            "rounds": self.rounds,
            "mean_path_exposure": float(exposure.mean().item()),
            "changed": bool(changed),
        }
        return changed
