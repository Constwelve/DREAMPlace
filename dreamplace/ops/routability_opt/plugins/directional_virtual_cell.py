"""Directional virtual-cell translation for congested two-pin nets."""

import math

from dreamplace.ops.routability_opt.plugin_base import (
    map_gradient,
    poisson_potential,
)
from dreamplace.ops.routability_opt.plugins.utils import (
    map_on_placement_device,
    normalize_field,
    routing_bin_sizes,
    select_congestion_map,
    smooth_map,
)
from dreamplace.ops.routability_opt.plugins.virtual_cell import (
    VirtualCellNetMovingPlugin,
    virtual_net_node_gradients,
)


def directional_virtual_cell_field(horizontal_utilization, vertical_utilization,
                                   threshold, power, smooth_radius,
                                   padding_mode, bin_size_x=1.0,
                                   bin_size_y=1.0, axis_balance=1.0):
    """Build a cross-track Poisson field from separate H/V utilization."""
    if horizontal_utilization.shape != vertical_utilization.shape:
        raise ValueError("directional virtual-cell maps must have equal shapes")
    if horizontal_utilization.ndim != 2:
        raise ValueError("directional virtual-cell maps must be 2D")
    threshold = float(threshold)
    power = float(power)
    if threshold < 0.0:
        raise ValueError(
            "ruplace_directional_virtual_cell_threshold must be nonnegative"
        )
    if power <= 0.0:
        raise ValueError(
            "ruplace_directional_virtual_cell_power must be positive"
        )
    axis_balance = float(axis_balance)
    if axis_balance <= 0.0:
        raise ValueError(
            "ruplace_directional_virtual_cell_axis_balance must be positive"
        )

    horizontal_charge = smooth_map(
        (horizontal_utilization - threshold).clamp_min(0.0).pow(power),
        smooth_radius,
        padding_mode,
    )
    vertical_charge = smooth_map(
        (vertical_utilization - threshold).clamp_min(0.0).pow(power),
        smooth_radius,
        padding_mode,
    )
    horizontal_potential = poisson_potential(horizontal_charge)
    vertical_potential = poisson_potential(vertical_charge)
    vertical_gx, _ = map_gradient(
        vertical_potential, bin_size_x, bin_size_y
    )
    _, horizontal_gy = map_gradient(
        horizontal_potential, bin_size_x, bin_size_y
    )
    axis_scale = math.sqrt(axis_balance)
    vertical_gx = vertical_gx * axis_scale
    horizontal_gy = horizontal_gy / axis_scale
    return (
        normalize_field(vertical_gx, horizontal_gy),
        (horizontal_charge, vertical_charge),
        (horizontal_potential, vertical_potential),
    )


class DirectionalVirtualCellNetMovingPlugin(VirtualCellNetMovingPlugin):
    """Translate virtual two-pin cells across congested route tracks."""

    name = "directional_virtual_cell"

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_directional_virtual_cell_weight", 0.0025
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        hv_utilization = signal.hv_utilization_map
        directional_feedback = hv_utilization is not None
        if directional_feedback:
            hv_utilization = map_on_placement_device(hv_utilization, pos)
            if hv_utilization.ndim != 3 or hv_utilization.shape[0] != 2:
                raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")
            horizontal_utilization = hv_utilization[0]
            vertical_utilization = hv_utilization[1]
        else:
            aggregate = map_on_placement_device(
                select_congestion_map(
                    signal,
                    getattr(self.params, "ruplace_force_congestion_mode", "utilization"),
                ),
                pos,
            )
            horizontal_utilization = aggregate
            vertical_utilization = aggregate

        bin_size_x, bin_size_y = routing_bin_sizes(
            self.placedb, horizontal_utilization.shape
        )
        if not bool(getattr(self.params, "ruplace_force_physical_bins", False)):
            bin_size_x = bin_size_y = 1.0
        (field_x, field_y), charges, potentials = directional_virtual_cell_field(
            horizontal_utilization,
            vertical_utilization,
            getattr(self.params, "ruplace_directional_virtual_cell_threshold", 0.8),
            getattr(self.params, "ruplace_directional_virtual_cell_power", 2.0),
            int(getattr(self.params, "ruplace_directional_virtual_cell_smooth", 2)),
            str(getattr(
                self.params, "ruplace_force_smoothing_padding", "replicate"
            )).lower(),
            bin_size_x,
            bin_size_y,
            getattr(
                self.params, "ruplace_directional_virtual_cell_axis_balance", 1.0
            ),
        )

        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        reduction = str(getattr(
            self.params, "ruplace_directional_virtual_cell_reduction", "sum"
        )).lower()
        node_grad_x, node_grad_y, counts, eligible_nets = (
            virtual_net_node_gradients(
                pin_pos[:num_pins],
                pin_pos[num_pins:],
                self.two_pin_pins.to(device=pos.device),
                self.data_collections.pin2node_map.to(device=pos.device),
                field_x,
                field_y,
                self.placedb.num_movable_nodes,
                (
                    self.placedb.routing_grid_xl,
                    self.placedb.routing_grid_yl,
                    self.placedb.routing_grid_xh,
                    self.placedb.routing_grid_yh,
                ),
                reduction=reduction,
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
        horizontal_charge, vertical_charge = charges
        horizontal_potential, vertical_potential = potentials
        self.metrics = {
            "two_pin_nets": int(self.two_pin_pins.shape[0]),
            "eligible_virtual_nets": int(eligible_nets.item()),
            "active_nodes": int((counts > 0).sum().item()),
            "directional_feedback": int(directional_feedback),
            "reduction_id": {"mean": 0, "sum": 1}[reduction],
            "axis_balance": float(getattr(
                self.params, "ruplace_directional_virtual_cell_axis_balance", 1.0
            )),
            "horizontal_charge_max": float(horizontal_charge.max().item()),
            "vertical_charge_max": float(vertical_charge.max().item()),
            "horizontal_potential_rms": float(
                horizontal_potential.square().mean().sqrt().item()
            ),
            "vertical_potential_rms": float(
                vertical_potential.square().mean().sqrt().item()
            ),
            "field_x_norm": float(field_x_norm.item()),
            "field_y_norm": float(field_y_norm.item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **force_metrics,
        }
        return changed
