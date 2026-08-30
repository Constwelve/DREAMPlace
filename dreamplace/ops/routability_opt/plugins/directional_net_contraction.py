"""Direction-specific contraction of nets crossing congested routing regions."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins.net_weighting import (
    net_congestion_scores,
    smooth_congestion_map,
)
from dreamplace.ops.routability_opt.plugins.utils import map_on_placement_device


def directional_net_pressures(horizontal_score, vertical_score, active_nets,
                              mode, normalization, max_pressure):
    """Return independent x/y contraction pressure for every net."""
    mode = str(mode).lower()
    if mode not in ("both", "max_hv", "horizontal", "vertical"):
        raise ValueError(
            "unsupported ruplace_directional_net_contraction_mode: %s" % mode
        )
    max_pressure = float(max_pressure)
    if max_pressure <= 0.0:
        raise ValueError(
            "ruplace_directional_net_contraction_max_pressure must be positive"
        )
    active = active_nets.to(device=horizontal_score.device, dtype=torch.bool)
    if normalization == "absolute":
        horizontal_scale = horizontal_score.new_tensor(1.0)
        vertical_scale = vertical_score.new_tensor(1.0)
    elif normalization == "design_mean":
        if bool(torch.any(active)):
            shared_scale = 0.5 * (
                horizontal_score[active].mean()
                + vertical_score[active].mean()
            )
        else:
            shared_scale = horizontal_score.new_tensor(1.0)
        shared_scale = shared_scale.clamp_min(
            torch.finfo(horizontal_score.dtype).eps
        )
        horizontal_scale = shared_scale
        vertical_scale = shared_scale
    elif normalization == "axis_mean":
        if bool(torch.any(active)):
            horizontal_scale = horizontal_score[active].mean()
            vertical_scale = vertical_score[active].mean()
        else:
            horizontal_scale = horizontal_score.new_tensor(1.0)
            vertical_scale = vertical_score.new_tensor(1.0)
        horizontal_scale = horizontal_scale.clamp_min(
            torch.finfo(horizontal_score.dtype).eps
        )
        vertical_scale = vertical_scale.clamp_min(
            torch.finfo(vertical_score.dtype).eps
        )
    else:
        raise ValueError(
            "unsupported directional net-contraction normalization: %s"
            % normalization
        )

    horizontal = (
        horizontal_score / horizontal_scale - 1.0
    ).clamp(0.0, max_pressure)
    vertical = (
        vertical_score / vertical_scale - 1.0
    ).clamp(0.0, max_pressure)
    zeros = torch.zeros_like(horizontal)
    horizontal = torch.where(active, horizontal, zeros)
    vertical = torch.where(active, vertical, zeros)
    if mode == "horizontal":
        vertical = zeros
    elif mode == "vertical":
        horizontal = zeros
    elif mode == "max_hv":
        raw_horizontal = horizontal
        raw_vertical = vertical
        horizontal = torch.where(
            raw_horizontal >= raw_vertical, raw_horizontal, zeros
        )
        vertical = torch.where(
            raw_vertical >= raw_horizontal, raw_vertical, zeros
        )
    return horizontal, vertical, horizontal_scale, vertical_scale


def extreme_pin_subgradient(pin_coordinate, flat_pins, net_ids, degrees,
                            net_pressure):
    """Compute a balanced HPWL subgradient for one coordinate axis."""
    incidence = pin_coordinate[flat_pins]
    num_nets = degrees.numel()
    net_min = torch.full(
        (num_nets,), torch.inf, dtype=incidence.dtype, device=incidence.device
    )
    net_max = torch.full(
        (num_nets,), -torch.inf, dtype=incidence.dtype, device=incidence.device
    )
    net_min.scatter_reduce_(
        0, net_ids, incidence, reduce="amin", include_self=True
    )
    net_max.scatter_reduce_(
        0, net_ids, incidence, reduce="amax", include_self=True
    )
    at_min = incidence == net_min[net_ids]
    at_max = incidence == net_max[net_ids]
    count_min = torch.zeros(
        num_nets, dtype=incidence.dtype, device=incidence.device
    )
    count_max = torch.zeros_like(count_min)
    count_min.scatter_add_(0, net_ids, at_min.to(incidence.dtype))
    count_max.scatter_add_(0, net_ids, at_max.to(incidence.dtype))
    return net_pressure[net_ids] * (
        at_max.to(incidence.dtype) / count_max[net_ids].clamp_min(1.0)
        - at_min.to(incidence.dtype) / count_min[net_ids].clamp_min(1.0)
    )


class DirectionalNetContractionPlugin(RoutabilityPlugin):
    name = "directional_net_contraction"

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
        self.original_weights = data_collections.net_weights.detach().clone()

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_directional_net_contraction_weight", 0.01
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        hv_utilization = signal.hv_utilization_map
        if hv_utilization is None:
            raise ValueError(
                "directional_net_contraction requires H/V utilization feedback"
            )
        hv_utilization = map_on_placement_device(hv_utilization, pos)
        if hv_utilization.ndim != 3 or hv_utilization.shape[0] != 2:
            raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")
        smooth = getattr(
            self.params, "ruplace_directional_net_contraction_smooth", 1
        )
        horizontal_map = smooth_congestion_map(hv_utilization[0], smooth)
        vertical_map = smooth_congestion_map(hv_utilization[1], smooth)

        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = horizontal_map.shape
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
        score_mode = str(getattr(
            self.params, "ruplace_directional_net_contraction_score_mode",
            "bbox_pmean",
        )).lower()
        bbox_power = float(getattr(
            self.params, "ruplace_directional_net_contraction_bbox_power", 4.0
        ))
        horizontal_score = net_congestion_scores(
            horizontal_map, pin_bx, pin_by, flat_pins, net_ids, degrees,
            score_mode, bbox_power,
        )
        vertical_score = net_congestion_scores(
            vertical_map, pin_bx, pin_by, flat_pins, net_ids, degrees,
            score_mode, bbox_power,
        )
        active_nets = self.active_nets.to(device=pos.device)
        mode = str(getattr(
            self.params, "ruplace_directional_net_contraction_mode", "max_hv"
        )).lower()
        normalization = str(getattr(
            self.params, "ruplace_directional_net_contraction_normalization",
            "design_mean",
        )).lower()
        max_pressure = float(getattr(
            self.params, "ruplace_directional_net_contraction_max_pressure", 2.0
        ))
        (horizontal_pressure, vertical_pressure, horizontal_score_scale,
         vertical_score_scale) = (
            directional_net_pressures(
                horizontal_score, vertical_score, active_nets, mode,
                normalization, max_pressure,
            )
        )
        original_weights = self.original_weights.to(device=pos.device, dtype=pos.dtype)
        horizontal_pressure = horizontal_pressure * original_weights
        vertical_pressure = vertical_pressure * original_weights

        incidence_gx = extreme_pin_subgradient(
            pin_pos[:num_pins], flat_pins, net_ids, degrees,
            horizontal_pressure,
        )
        incidence_gy = extreme_pin_subgradient(
            pin_pos[num_pins:], flat_pins, net_ids, degrees, vertical_pressure,
        )
        pin2node = self.data_collections.pin2node_map.to(device=pos.device)
        nodes = pin2node[flat_pins].long()
        movable = nodes < self.placedb.num_movable_nodes
        nodes = nodes[movable]
        node_gx = torch.zeros(
            self.placedb.num_movable_nodes, dtype=pos.dtype, device=pos.device
        )
        node_gy = torch.zeros_like(node_gx)
        node_gx.scatter_add_(0, nodes, incidence_gx[movable])
        node_gy.scatter_add_(0, nodes, incidence_gy[movable])

        field_norm = (node_gx.square() + node_gy.square()).sum().sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "mode_id": {
                "both": 0, "max_hv": 1, "horizontal": 2, "vertical": 3,
            }[mode],
            "score_scale": float(
                (0.5 * (horizontal_score_scale + vertical_score_scale)).item()
            ),
            "horizontal_score_scale": float(horizontal_score_scale.item()),
            "vertical_score_scale": float(vertical_score_scale.item()),
            "score_scale_ratio": float(
                (horizontal_score_scale / vertical_score_scale).item()
            ),
            "horizontal_active_nets": int((horizontal_pressure > 0).sum().item()),
            "vertical_active_nets": int((vertical_pressure > 0).sum().item()),
            "horizontal_max_pressure": float(horizontal_pressure.max().item()),
            "vertical_max_pressure": float(vertical_pressure.max().item()),
            **schedule_metrics,
            **force_metrics,
        }
        return changed
