"""Net-level movement away from overlapping congested regions."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin, map_gradient
from dreamplace.ops.routability_opt.plugins.utils import (
    force_map_options,
    map_on_placement_device,
    normalize_field,
    routing_bin_sizes,
    select_congestion_map,
    smooth_map,
)


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
        weight = float(getattr(self.params, "ruplace_net_overlap_weight", 0.05))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False
        signal = context.signal(pos)
        map_mode, padding_mode, physical_bins = force_map_options(self.params)
        congestion = smooth_map(
            select_congestion_map(signal, map_mode),
            int(getattr(self.params, "ruplace_net_overlap_smooth", 2)),
            padding_mode,
        )
        congestion = map_on_placement_device(congestion, pos)
        bx, by = routing_bin_sizes(self.placedb, congestion.shape)
        if not physical_bins:
            bx = by = 1.0
        gx, gy = normalize_field(*map_gradient(congestion, bx, by))
        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = congestion.shape
        bx = ((pin_pos[:num_pins] - self.placedb.routing_grid_xl) * nx /
              (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl)).long()
        by = ((pin_pos[num_pins:] - self.placedb.routing_grid_yl) * ny /
              (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl)).long()
        bx.clamp_(0, nx - 1)
        by.clamp_(0, ny - 1)
        flat_pins = self.data_collections.flat_net2pin_map.to(
            device=pos.device, dtype=torch.long
        )
        net_ids = self.net_ids.to(device=pos.device)
        degrees = self.degrees.to(device=pos.device)
        net_gx = torch.zeros(self.degrees.numel(), dtype=pos.dtype, device=pos.device)
        net_gy = torch.zeros_like(net_gx)
        net_gx.scatter_add_(0, net_ids, gx[bx[flat_pins], by[flat_pins]])
        net_gy.scatter_add_(0, net_ids, gy[bx[flat_pins], by[flat_pins]])
        degree = degrees.clamp_min(1).to(pos.dtype)
        net_gx /= degree
        net_gy /= degree

        pin2node = self.data_collections.pin2node_map.to(device=pos.device)
        nodes = pin2node[flat_pins].long()
        movable = nodes < self.placedb.num_movable_nodes
        nodes = nodes[movable]
        incidence_nets = net_ids[movable]
        node_gx = torch.zeros(self.placedb.num_movable_nodes, dtype=pos.dtype, device=pos.device)
        node_gy = torch.zeros_like(node_gx)
        counts = torch.zeros_like(node_gx)
        node_gx.scatter_add_(0, nodes, net_gx[incidence_nets])
        node_gy.scatter_add_(0, nodes, net_gy[incidence_nets])
        counts.scatter_add_(0, nodes, torch.ones_like(nodes, dtype=pos.dtype))
        node_gx /= counts.clamp_min(1.0)
        node_gy /= counts.clamp_min(1.0)
        field_norm = (node_gx.square() + node_gy.square()).sum().sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "active_nodes": int((counts > 0).sum().item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **force_metrics,
        }
        return changed
