"""Congestion-aware net-weighting objective."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin


class CongestionNetWeightingPlugin(RoutabilityPlugin):
    name = "net_weighting"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.original_weights = data_collections.net_weights.clone()
        starts = data_collections.flat_net2pin_start_map.long()
        self.degrees = starts[1:] - starts[:-1]
        self.net_ids = torch.repeat_interleave(
            torch.arange(self.degrees.numel(), device=starts.device), self.degrees
        )

    def apply_gradient(self, pos, model, context):
        freq = max(1, int(getattr(self.params, "ruplace_net_weight_freq", 20)))
        if context.iteration % freq:
            return False
        signal = context.signal(pos)
        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = signal.utilization_map.shape
        bx = ((pin_pos[:num_pins] - self.placedb.routing_grid_xl) * nx /
              (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl)).long()
        by = ((pin_pos[num_pins:] - self.placedb.routing_grid_yl) * ny /
              (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl)).long()
        bx.clamp_(0, nx - 1)
        by.clamp_(0, ny - 1)
        pin_score = signal.utilization_map[bx, by]
        flat_pins = self.data_collections.flat_net2pin_map.long()
        net_score = torch.zeros_like(self.original_weights)
        net_score.scatter_add_(0, self.net_ids, pin_score[flat_pins])
        net_score /= self.degrees.clamp_min(1).to(net_score.dtype)
        gamma = float(getattr(self.params, "ruplace_net_weight_gamma", 0.25))
        max_ratio = float(getattr(self.params, "ruplace_net_weight_max", 3.0))
        ratio = (1.0 + gamma * (net_score - 1.0).clamp_min(0.0)).clamp(1.0, max_ratio)
        target_weights = self.original_weights * ratio
        changed = bool(torch.any(target_weights != self.data_collections.net_weights))
        if changed:
            self.data_collections.net_weights.copy_(target_weights)
        self.metrics = {
            "mean_ratio": float(ratio.mean().item()),
            "max_ratio": float(ratio.max().item()),
        }
        return changed
