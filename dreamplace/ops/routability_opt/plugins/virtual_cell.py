"""Virtual-cell translation force for congested two-pin nets."""

import torch

from dreamplace.ops.routability_opt.plugin_base import (
    RoutabilityPlugin,
    map_gradient,
    poisson_potential,
)
from dreamplace.ops.routability_opt.plugins.utils import (
    force_map_options,
    map_on_placement_device,
    normalize_field,
    routing_bin_sizes,
    select_congestion_map,
    smooth_map,
)


def virtual_net_node_gradients(pin_x, pin_y, two_pin_pins, pin2node,
                               field_x, field_y, num_movable_nodes,
                               bounds, reduction="mean"):
    """Transfer midpoint field samples equally to both movable endpoints."""
    if two_pin_pins.ndim != 2 or two_pin_pins.shape[1] != 2:
        raise ValueError("two_pin_pins must have shape [nets, 2]")
    if field_x.shape != field_y.shape or field_x.ndim != 2:
        raise ValueError("virtual-cell field maps must be equal 2D shapes")
    reduction = str(reduction).lower()
    if reduction not in ("mean", "sum"):
        raise ValueError("virtual-cell reduction must be mean or sum")
    node_grad_x = field_x.new_zeros(num_movable_nodes)
    node_grad_y = field_y.new_zeros(num_movable_nodes)
    counts = field_x.new_zeros(num_movable_nodes)
    if two_pin_pins.numel() == 0:
        return node_grad_x, node_grad_y, counts, field_x.new_zeros((), dtype=torch.long)

    nodes = pin2node[two_pin_pins].long()
    eligible = (
        (nodes[:, 0] < num_movable_nodes)
        & (nodes[:, 1] < num_movable_nodes)
        & (nodes[:, 0] != nodes[:, 1])
    )
    pins = two_pin_pins[eligible]
    nodes = nodes[eligible]
    if pins.numel() == 0:
        return node_grad_x, node_grad_y, counts, eligible.sum()

    midpoint_x = 0.5 * (pin_x[pins[:, 0]] + pin_x[pins[:, 1]])
    midpoint_y = 0.5 * (pin_y[pins[:, 0]] + pin_y[pins[:, 1]])
    grid_xl, grid_yl, grid_xh, grid_yh = (float(value) for value in bounds)
    nx, ny = field_x.shape
    bx = ((midpoint_x - grid_xl) * nx / (grid_xh - grid_xl)).long()
    by = ((midpoint_y - grid_yl) * ny / (grid_yh - grid_yl)).long()
    bx.clamp_(0, nx - 1)
    by.clamp_(0, ny - 1)
    net_grad_x = 0.5 * field_x[bx, by]
    net_grad_y = 0.5 * field_y[bx, by]

    flat_nodes = nodes.reshape(-1)
    repeated_x = net_grad_x[:, None].expand(-1, 2).reshape(-1)
    repeated_y = net_grad_y[:, None].expand(-1, 2).reshape(-1)
    node_grad_x.scatter_add_(0, flat_nodes, repeated_x)
    node_grad_y.scatter_add_(0, flat_nodes, repeated_y)
    counts.scatter_add_(
        0, flat_nodes, torch.ones_like(flat_nodes, dtype=field_x.dtype)
    )
    if reduction == "mean":
        node_grad_x /= counts.clamp_min(1.0)
        node_grad_y /= counts.clamp_min(1.0)
    return node_grad_x, node_grad_y, counts, eligible.sum()


class VirtualCellNetMovingPlugin(RoutabilityPlugin):
    """Translate movable two-pin nets using a virtual midpoint cell."""

    name = "virtual_cell"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        starts = data_collections.flat_net2pin_start_map.long()
        degrees = starts[1:] - starts[:-1]
        active = data_collections.net_mask_ignore_large_degrees.bool()
        two_pin_nets = torch.nonzero((degrees == 2) & active, as_tuple=False).flatten()
        if two_pin_nets.numel():
            first = starts[two_pin_nets]
            flat_pins = data_collections.flat_net2pin_map.long()
            self.two_pin_pins = torch.stack((
                flat_pins[first], flat_pins[first + 1]
            ), dim=1)
        else:
            self.two_pin_pins = starts.new_empty((0, 2))

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(self.params, "ruplace_virtual_cell_weight", 0.0025))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False
        threshold = float(getattr(
            self.params, "ruplace_virtual_cell_threshold", 0.8
        ))
        power = float(getattr(self.params, "ruplace_virtual_cell_power", 2.0))
        if threshold < 0.0:
            raise ValueError("ruplace_virtual_cell_threshold must be nonnegative")
        if power <= 0.0:
            raise ValueError("ruplace_virtual_cell_power must be positive")

        signal = context.signal(pos)
        map_mode, padding_mode, physical_bins = force_map_options(self.params)
        utilization = map_on_placement_device(
            select_congestion_map(signal, map_mode), pos
        )
        charge = (utilization - threshold).clamp_min(0.0).pow(power)
        charge = smooth_map(
            charge,
            int(getattr(self.params, "ruplace_virtual_cell_smooth", 2)),
            padding_mode,
        )
        potential = poisson_potential(charge)
        bin_size_x, bin_size_y = routing_bin_sizes(
            self.placedb, charge.shape
        )
        if not physical_bins:
            bin_size_x = bin_size_y = 1.0
        field_x, field_y = normalize_field(*map_gradient(
            potential, bin_size_x, bin_size_y
        ))

        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        node_grad_x, node_grad_y, counts, eligible_nets = (
            virtual_net_node_gradients(
                pin_pos[:num_pins], pin_pos[num_pins:],
                self.two_pin_pins.to(device=pos.device),
                self.data_collections.pin2node_map.to(device=pos.device),
                field_x, field_y, self.placedb.num_movable_nodes,
                (
                    self.placedb.routing_grid_xl,
                    self.placedb.routing_grid_yl,
                    self.placedb.routing_grid_xh,
                    self.placedb.routing_grid_yh,
                ),
            )
        )
        field_x_norm = node_grad_x.square().sum().sqrt()
        field_y_norm = node_grad_y.square().sum().sqrt()
        field_norm = (field_x_norm.square() + field_y_norm.square()).sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_grad_x, node_grad_y, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "two_pin_nets": int(self.two_pin_pins.shape[0]),
            "eligible_virtual_nets": int(eligible_nets.item()),
            "active_nodes": int((counts > 0).sum().item()),
            "charge_max": float(charge.max().item()),
            "potential_rms": float(potential.square().mean().sqrt().item()),
            "field_x_norm": float(field_x_norm.item()),
            "field_y_norm": float(field_y_norm.item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **force_metrics,
        }
        return changed
