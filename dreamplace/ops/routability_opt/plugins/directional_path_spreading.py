"""Move routed net neighborhoods across congested track directions."""

import torch

from dreamplace.ops.routability_opt.plugin_base import (
    RoutabilityPlugin,
    map_gradient,
)
from dreamplace.ops.routability_opt.plugins.utils import (
    map_on_placement_device,
    normalize_field,
    routing_bin_sizes,
    smooth_map,
)


def directional_cross_axis_field(horizontal_utilization, vertical_utilization,
                                 threshold, power, smooth_radius,
                                 padding_mode, bin_size_x=1.0,
                                 bin_size_y=1.0, mode="both"):
    """Return x/y gradients that move routes across alternative tracks."""
    threshold = float(threshold)
    power = float(power)
    if threshold < 0.0:
        raise ValueError(
            "ruplace_directional_path_spreading_threshold must be nonnegative"
        )
    if power <= 0.0:
        raise ValueError(
            "ruplace_directional_path_spreading_power must be positive"
        )
    mode = str(mode).lower()
    if mode not in ("both", "horizontal", "vertical"):
        raise ValueError(
            "unsupported ruplace_directional_path_spreading_mode: %s" % mode
        )

    horizontal_pressure = (
        horizontal_utilization - threshold
    ).clamp_min(0.0).pow(power)
    vertical_pressure = (
        vertical_utilization - threshold
    ).clamp_min(0.0).pow(power)
    horizontal_pressure = smooth_map(
        horizontal_pressure, smooth_radius, padding_mode
    )
    vertical_pressure = smooth_map(
        vertical_pressure, smooth_radius, padding_mode
    )
    vertical_gx, _ = map_gradient(
        vertical_pressure, bin_size_x, bin_size_y
    )
    _, horizontal_gy = map_gradient(
        horizontal_pressure, bin_size_x, bin_size_y
    )
    zeros_x = torch.zeros_like(vertical_gx)
    zeros_y = torch.zeros_like(horizontal_gy)
    if mode == "horizontal":
        vertical_gx = zeros_x
    elif mode == "vertical":
        horizontal_gy = zeros_y
    return normalize_field(vertical_gx, horizontal_gy), (
        horizontal_pressure, vertical_pressure
    )


class DirectionalPathSpreadingPlugin(RoutabilityPlugin):
    """Translate net neighborhoods perpendicular to congested route tracks."""

    name = "directional_path_spreading"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        starts = data_collections.flat_net2pin_start_map.long()
        self.degrees = starts[1:] - starts[:-1]
        self.net_ids = torch.repeat_interleave(
            torch.arange(self.degrees.numel(), device=starts.device), self.degrees
        )
        self.active_nets = (
            data_collections.net_mask_ignore_large_degrees.bool().clone()
        )

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_directional_path_spreading_weight", 0.0025
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        hv_utilization = signal.hv_utilization_map
        if hv_utilization is None:
            raise ValueError(
                "directional_path_spreading requires H/V utilization feedback"
            )
        hv_utilization = map_on_placement_device(hv_utilization, pos)
        if hv_utilization.ndim != 3 or hv_utilization.shape[0] != 2:
            raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")

        radius = int(getattr(
            self.params, "ruplace_directional_path_spreading_smooth", 1
        ))
        padding = str(getattr(
            self.params, "ruplace_force_smoothing_padding", "replicate"
        )).lower()
        bin_size_x, bin_size_y = routing_bin_sizes(
            self.placedb, hv_utilization.shape[-2:]
        )
        (field_x, field_y), pressure = directional_cross_axis_field(
            hv_utilization[0], hv_utilization[1],
            getattr(
                self.params,
                "ruplace_directional_path_spreading_threshold",
                0.8,
            ),
            getattr(
                self.params, "ruplace_directional_path_spreading_power", 2.0
            ),
            radius,
            padding,
            bin_size_x,
            bin_size_y,
            getattr(
                self.params, "ruplace_directional_path_spreading_mode", "both"
            ),
        )

        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = field_x.shape
        pin_bx = ((pin_pos[:num_pins] - self.placedb.routing_grid_xl) * nx /
                  (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl)).long()
        pin_by = ((pin_pos[num_pins:] - self.placedb.routing_grid_yl) * ny /
                  (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl)).long()
        pin_bx.clamp_(0, nx - 1)
        pin_by.clamp_(0, ny - 1)

        flat_pins = self.data_collections.flat_net2pin_map.to(
            device=pos.device, dtype=torch.long
        )
        net_ids = self.net_ids.to(device=pos.device)
        degrees = self.degrees.to(device=pos.device)
        net_gx = pos.new_zeros(degrees.numel())
        net_gy = pos.new_zeros(degrees.numel())
        net_gx.scatter_add_(
            0, net_ids, field_x[pin_bx[flat_pins], pin_by[flat_pins]]
        )
        net_gy.scatter_add_(
            0, net_ids, field_y[pin_bx[flat_pins], pin_by[flat_pins]]
        )
        degree = degrees.clamp_min(1).to(pos.dtype)
        net_gx /= degree
        net_gy /= degree
        active_nets = self.active_nets.to(device=pos.device)
        active_force = active_nets & ((net_gx != 0.0) | (net_gy != 0.0))
        net_gx = torch.where(active_force, net_gx, torch.zeros_like(net_gx))
        net_gy = torch.where(active_force, net_gy, torch.zeros_like(net_gy))

        pin2node = self.data_collections.pin2node_map.to(device=pos.device)
        nodes = pin2node[flat_pins].long()
        movable = (
            (nodes < self.placedb.num_movable_nodes)
            & active_force[net_ids]
        )
        nodes = nodes[movable]
        incidence_nets = net_ids[movable]
        node_gx = pos.new_zeros(self.placedb.num_movable_nodes)
        node_gy = pos.new_zeros(self.placedb.num_movable_nodes)
        counts = pos.new_zeros(self.placedb.num_movable_nodes)
        node_gx.scatter_add_(0, nodes, net_gx[incidence_nets])
        node_gy.scatter_add_(0, nodes, net_gy[incidence_nets])
        counts.scatter_add_(0, nodes, torch.ones_like(nodes, dtype=pos.dtype))
        node_gx /= counts.clamp_min(1.0)
        node_gy /= counts.clamp_min(1.0)

        field_x_norm = node_gx.square().sum().sqrt()
        field_y_norm = node_gy.square().sum().sqrt()
        field_norm = (field_x_norm.square() + field_y_norm.square()).sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        horizontal_pressure, vertical_pressure = pressure
        self.metrics = {
            "active_nets": int(active_force.sum().item()),
            "active_nodes": int((counts > 0).sum().item()),
            "horizontal_pressure_max": float(horizontal_pressure.max().item()),
            "vertical_pressure_max": float(vertical_pressure.max().item()),
            "field_x_norm": float(field_x_norm.item()),
            "field_y_norm": float(field_y_norm.item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **force_metrics,
        }
        return changed
