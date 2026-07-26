"""Momentum-smoothed cell inflation inspired by differentiable net-moving."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation


class MomentumInflationPlugin(RoutabilityPlugin):
    name = "momentum_inflation"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.engine = RUPlaceInflation(params, placedb, data_collections)
        self.velocity = None
        self.rounds = 0

    def maybe_adjust_area(self, pos, model, context):
        max_rounds = int(getattr(self.params, "ruplace_momentum_rounds", 8))
        if self.rounds >= max_rounds:
            return False
        signal = context.signal(pos, refresh=True)
        desired = self.engine._node_bin_utilization(
            pos, signal.utilization_map, signal.hv_overflow_map
        ).clamp_min(1.0)
        current = self.engine.current_inflate_ratio.to(pos.device, pos.dtype)
        beta = float(getattr(self.params, "ruplace_momentum_beta", 0.8))
        step = float(getattr(self.params, "ruplace_momentum_step", 0.5))
        delta = desired - current
        self.velocity = delta if self.velocity is None else beta * self.velocity + (1.0 - beta) * delta
        target = current + step * self.velocity
        changed = self.engine.apply_node_ratios(pos, target)
        self.rounds += 1
        self.metrics = {
            "rounds": self.rounds,
            "velocity_norm": float(self.velocity.norm().item()),
            "changed": bool(changed),
        }
        return changed
