"""Net-level movement away from overlapping congested regions."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin, map_gradient
from dreamplace.ops.routability_opt.plugins.utils import normalize_field, smooth_map


class NetOverlapRemovalPlugin(RoutabilityPlugin):
    name = "net_overlap"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        starts = data_collections.flat_net2pin_start_map.long()
        self.degrees = starts[1:] - starts[:-1]
        self.net_ids = torch.repeat_interleave(
            torch.arange(self.degrees.numel(), device=starts.device), self.degrees
        )

    def apply_gradient(self, pos, model, context):
        signal = context.signal(pos)
        congestion = smooth_map(
            signal.overflow_map, int(getattr(self.params, "ruplace_net_overlap_smooth", 2))
        )
        gx, gy = normalize_field(*map_gradient(congestion))
        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = congestion.shape
        bx = ((pin_pos[:num_pins] - self.placedb.routing_grid_xl) * nx /
              (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl)).long()
        by = ((pin_pos[num_pins:] - self.placedb.routing_grid_yl) * ny /
              (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl)).long()
        bx.clamp_(0, nx - 1)
        by.clamp_(0, ny - 1)
        flat_pins = self.data_collections.flat_net2pin_map.long()
        net_gx = torch.zeros(self.degrees.numel(), dtype=pos.dtype, device=pos.device)
        net_gy = torch.zeros_like(net_gx)
        net_gx.scatter_add_(0, self.net_ids, gx[bx[flat_pins], by[flat_pins]])
        net_gy.scatter_add_(0, self.net_ids, gy[bx[flat_pins], by[flat_pins]])
        degree = self.degrees.clamp_min(1).to(pos.dtype)
        net_gx /= degree
        net_gy /= degree

        nodes = self.data_collections.pin2node_map[flat_pins].long()
        movable = nodes < self.placedb.num_movable_nodes
        nodes = nodes[movable]
        incidence_nets = self.net_ids[movable]
        node_gx = torch.zeros(self.placedb.num_movable_nodes, dtype=pos.dtype, device=pos.device)
        node_gy = torch.zeros_like(node_gx)
        counts = torch.zeros_like(node_gx)
        node_gx.scatter_add_(0, nodes, net_gx[incidence_nets])
        node_gy.scatter_add_(0, nodes, net_gy[incidence_nets])
        counts.scatter_add_(0, nodes, torch.ones_like(nodes, dtype=pos.dtype))
        node_gx /= counts.clamp_min(1.0)
        node_gy /= counts.clamp_min(1.0)
        weight = float(getattr(self.params, "ruplace_net_overlap_weight", 0.05))
        field_norm = (node_gx.square() + node_gy.square()).sum().sqrt()
        changed = weight != 0.0 and bool(field_norm > 0)
        if changed:
            context.add_movable_gradient(pos, node_gx, node_gy, weight)
        self.metrics = {
            "active_nodes": int((counts > 0).sum().item()),
            "field_norm": float(field_norm.item()),
        }
        return changed
