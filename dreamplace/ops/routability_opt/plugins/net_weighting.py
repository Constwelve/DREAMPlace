"""Congestion-aware net-weighting objective."""

import torch
import torch.nn.functional as F

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins.utils import map_on_placement_device


def select_congestion_map(utilization, hv_utilization, mode):
    """Select aggregate or directional utilization for net scoring."""
    mode = str(mode).lower()
    if mode == "aggregate":
        return utilization
    if hv_utilization is None:
        raise ValueError(
            "ruplace_net_weight_direction_mode=%s requires H/V utilization"
            % mode
        )
    if hv_utilization.ndim != 3 or hv_utilization.shape[0] != 2:
        raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")
    if mode == "max_hv":
        return hv_utilization.max(dim=0).values
    if mode == "mean_hv":
        return hv_utilization.mean(dim=0)
    if mode == "horizontal":
        return hv_utilization[0]
    if mode == "vertical":
        return hv_utilization[1]
    raise ValueError(
        "unsupported ruplace_net_weight_direction_mode: %s" % mode
    )


def smooth_congestion_map(utilization, radius):
    """Apply replicate-padded box smoothing without changing map dimensions."""
    raw_radius = float(radius)
    if raw_radius < 0.0 or not raw_radius.is_integer():
        raise ValueError("ruplace_net_weight_smooth must be a nonnegative integer")
    radius = int(raw_radius)
    if radius == 0:
        return utilization
    kernel = 2 * radius + 1
    value = utilization.unsqueeze(0).unsqueeze(0)
    value = F.pad(value, (radius, radius, radius, radius), mode="replicate")
    return F.avg_pool2d(value, kernel_size=kernel, stride=1)[0, 0]


def net_congestion_scores(utilization, pin_bx, pin_by, flat_pins, net_ids,
                          degrees, mode, bbox_power=4.0):
    """Aggregate a congestion map into one score per net."""
    mode = str(mode).lower()
    if mode not in ("pin_mean", "bbox_mean", "bbox_pmean"):
        raise ValueError("unsupported ruplace_net_weight_score_mode: %s" % mode)
    bbox_power = float(bbox_power)
    if mode == "bbox_pmean" and bbox_power <= 0.0:
        raise ValueError("ruplace_net_weight_bbox_power must be positive")

    num_nets = degrees.numel()
    incidence_bx = pin_bx[flat_pins]
    incidence_by = pin_by[flat_pins]
    if mode == "pin_mean":
        pin_score = utilization[pin_bx, pin_by]
        net_score = utilization.new_zeros(num_nets)
        net_score.scatter_add_(0, net_ids, pin_score[flat_pins])
        return net_score / degrees.clamp_min(1).to(net_score.dtype)

    nx, ny = utilization.shape
    net_xl = torch.full(
        (num_nets,), nx, dtype=torch.long, device=utilization.device
    )
    net_yl = torch.full(
        (num_nets,), ny, dtype=torch.long, device=utilization.device
    )
    net_xh = torch.full(
        (num_nets,), -1, dtype=torch.long, device=utilization.device
    )
    net_yh = torch.full(
        (num_nets,), -1, dtype=torch.long, device=utilization.device
    )
    net_xl.scatter_reduce_(
        0, net_ids, incidence_bx, reduce="amin", include_self=True
    )
    net_yl.scatter_reduce_(
        0, net_ids, incidence_by, reduce="amin", include_self=True
    )
    net_xh.scatter_reduce_(
        0, net_ids, incidence_bx, reduce="amax", include_self=True
    )
    net_yh.scatter_reduce_(
        0, net_ids, incidence_by, reduce="amax", include_self=True
    )
    nonempty = degrees > 0
    zeros = torch.zeros_like(net_xl)
    net_xl = torch.where(nonempty, net_xl, zeros)
    net_yl = torch.where(nonempty, net_yl, zeros)
    net_xh = torch.where(nonempty, net_xh, zeros)
    net_yh = torch.where(nonempty, net_yh, zeros)

    score_map = utilization
    power_scale = None
    if mode == "bbox_pmean":
        # Scaling before exponentiation keeps high-utilization maps finite;
        # multiplying after the root is mathematically equivalent.
        nonnegative = utilization.clamp_min(0.0)
        power_scale = nonnegative.max().clamp_min(
            torch.finfo(utilization.dtype).eps
        )
        score_map = (nonnegative / power_scale).pow(bbox_power)

    # The leading zero row/column makes every inclusive rectangle sum four
    # vectorized gathers from the 2D summed-area table.
    integral = score_map.new_zeros((nx + 1, ny + 1))
    integral[1:, 1:] = score_map.cumsum(0).cumsum(1)
    xh = net_xh + 1
    yh = net_yh + 1
    bbox_sum = (
        integral[xh, yh]
        - integral[net_xl, yh]
        - integral[xh, net_yl]
        + integral[net_xl, net_yl]
    )
    bbox_area = (xh - net_xl) * (yh - net_yl)
    bbox_mean = bbox_sum / bbox_area.clamp_min(1).to(bbox_sum.dtype)
    if mode == "bbox_pmean":
        bbox_mean = bbox_mean.clamp_min(0.0).pow(1.0 / bbox_power) * power_scale
    return torch.where(nonempty, bbox_mean, torch.zeros_like(bbox_mean))


def net_weight_ratios(net_score, active_nets, gamma, max_ratio, normalization):
    """Return congestion weight ratios and the applied design scale."""
    if gamma < 0.0:
        raise ValueError("ruplace_net_weight_gamma must be nonnegative")
    if max_ratio < 1.0:
        raise ValueError("ruplace_net_weight_max must be at least 1")
    active = active_nets.to(device=net_score.device, dtype=torch.bool)
    if normalization == "absolute":
        scale = net_score.new_tensor(1.0)
    elif normalization == "design_mean":
        scale = (
            net_score[active].mean()
            if bool(torch.any(active)) else net_score.new_tensor(1.0)
        ).clamp_min(torch.finfo(net_score.dtype).eps)
    else:
        raise ValueError(
            "unsupported ruplace_net_weight_normalization: %s" % normalization
        )
    normalized_score = net_score / scale
    ratio = (
        1.0 + gamma * (normalized_score - 1.0).clamp_min(0.0)
    ).clamp(1.0, max_ratio)
    ratio = torch.where(active, ratio, torch.ones_like(ratio))
    return ratio, scale


def net_relaxation_ratios(net_score, active_nets, gamma, min_ratio,
                          normalization):
    """Reduce weights on congested nets while preserving inactive nets."""
    if gamma < 0.0:
        raise ValueError("ruplace_net_relaxation_gamma must be nonnegative")
    if min_ratio <= 0.0 or min_ratio > 1.0:
        raise ValueError(
            "ruplace_net_relaxation_min_weight must be in (0, 1]"
        )
    active = active_nets.to(device=net_score.device, dtype=torch.bool)
    if normalization == "absolute":
        scale = net_score.new_tensor(1.0)
    elif normalization == "design_mean":
        scale = (
            net_score[active].mean()
            if bool(torch.any(active)) else net_score.new_tensor(1.0)
        ).clamp_min(torch.finfo(net_score.dtype).eps)
    else:
        raise ValueError(
            "unsupported ruplace_net_relaxation_normalization: %s"
            % normalization
        )
    normalized_score = net_score / scale
    ratio = (
        1.0 / (1.0 + gamma * (normalized_score - 1.0).clamp_min(0.0))
    ).clamp(min_ratio, 1.0)
    ratio = torch.where(active, ratio, torch.ones_like(ratio))
    return ratio, scale


class CongestionNetWeightingPlugin(RoutabilityPlugin):
    name = "net_weighting"
    parameter_prefix = "ruplace_net_weight"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.original_weights = data_collections.net_weights.clone()
        self.pending_weights = None
        self.weight_updates = 0
        starts = data_collections.flat_net2pin_start_map.long()
        self.degrees = starts[1:] - starts[:-1]
        self.active_nets = data_collections.net_mask_ignore_large_degrees.bool().clone()
        self.net_ids = torch.repeat_interleave(
            torch.arange(self.degrees.numel(), device=starts.device), self.degrees
        )

    def _param(self, suffix, default):
        return getattr(
            self.params, "%s_%s" % (self.parameter_prefix, suffix), default
        )

    def _ratio_limit(self):
        return float(self._param("max", 3.0))

    def _ratios(self, net_score, active_nets, gamma, ratio_limit,
                normalization):
        return net_weight_ratios(
            net_score, active_nets, gamma, ratio_limit, normalization
        )

    def _saturated(self, active_ratio, ratio_limit):
        return active_ratio >= ratio_limit

    def _phase(self):
        phase = str(self._param("phase", "post_gradient")).lower()
        if phase not in ("post_gradient", "pre_objective"):
            raise ValueError(
                "unsupported %s_phase: %s" % (self.parameter_prefix, phase)
            )
        return phase

    def prepare_objective(self, pos, model, context):
        if self._phase() != "pre_objective":
            return False
        return self._update_weights(pos, context)

    def objective_phase_enabled(self):
        return self._phase() == "pre_objective"

    def gradient_phase_enabled(self):
        return self._phase() == "post_gradient"

    def apply_gradient(self, pos, model, context):
        if self._phase() != "post_gradient":
            return False
        return self._update_weights(pos, context, defer=True)

    def commit_post_gradient(self, pos, model, context):
        if self.pending_weights is None:
            return False
        changed = bool(torch.any(
            self.pending_weights != self.data_collections.net_weights
        ))
        if changed:
            self.data_collections.net_weights.copy_(self.pending_weights)
        self.pending_weights = None
        return changed

    def _update_weights(self, pos, context, defer=False):
        freq = max(1, int(self._param("freq", 20)))
        if context.iteration % freq:
            if defer:
                self.pending_weights = None
            return False
        signal = context.signal(pos)
        aggregate_utilization = map_on_placement_device(
            signal.utilization_map, pos
        )
        hv_utilization = (
            map_on_placement_device(signal.hv_utilization_map, pos)
            if signal.hv_utilization_map is not None else None
        )
        direction_mode = str(self._param("direction_mode", "aggregate")).lower()
        utilization = select_congestion_map(
            aggregate_utilization, hv_utilization, direction_mode
        )
        smooth_radius = self._param("smooth", 0)
        utilization = smooth_congestion_map(utilization, smooth_radius)
        pin_pos = context.pin_positions(pos)
        num_pins = pin_pos.numel() // 2
        nx, ny = utilization.shape
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
        score_mode = str(self._param("score_mode", "pin_mean")).lower()
        bbox_power = float(self._param("bbox_power", 4.0))
        net_score = net_congestion_scores(
            utilization, bx, by, flat_pins, net_ids, degrees, score_mode,
            bbox_power,
        )
        active_nets = self.active_nets.to(device=pos.device)
        base_gamma = float(self._param("gamma", 0.25))
        decay = float(self._param("decay", 1.0))
        min_ratio = float(self._param("min_ratio", 0.0))
        if decay <= 0.0 or decay > 1.0:
            raise ValueError("ruplace_net_weight_decay must be in (0, 1]")
        if min_ratio < 0.0 or min_ratio > 1.0:
            raise ValueError("ruplace_net_weight_min_ratio must be in [0, 1]")
        gamma_multiplier = max(decay ** self.weight_updates, min_ratio)
        gamma = base_gamma * gamma_multiplier
        ratio_limit = self._ratio_limit()
        normalization = str(self._param("normalization", "absolute")).lower()
        ratio, score_scale = self._ratios(
            net_score, active_nets, gamma, ratio_limit, normalization
        )
        target_weights = self.original_weights * ratio
        changed = bool(torch.any(target_weights != self.data_collections.net_weights))
        if changed:
            if defer:
                self.pending_weights = target_weights.detach().clone()
            else:
                self.data_collections.net_weights.copy_(target_weights)
        elif defer:
            self.pending_weights = None
        update_index = self.weight_updates
        if changed:
            self.weight_updates += 1
        active_ratio = ratio[active_nets]
        self.metrics = {
            "score_mode_id": {
                "pin_mean": 0, "bbox_mean": 1, "bbox_pmean": 2,
            }[score_mode],
            "bbox_power": bbox_power,
            "direction_mode_id": {
                "aggregate": 0, "max_hv": 1, "mean_hv": 2,
                "horizontal": 3, "vertical": 4,
            }[direction_mode],
            "smooth_radius": int(float(smooth_radius)),
            "base_gamma": base_gamma,
            "effective_gamma": gamma,
            "gamma_multiplier": gamma_multiplier,
            "weight_update_index": update_index,
            "weight_updates": self.weight_updates,
            "ratio_limit": ratio_limit,
            "mean_ratio": float(
                active_ratio.mean().item() if active_ratio.numel() else 1.0
            ),
            "min_ratio": float(
                active_ratio.min().item() if active_ratio.numel() else 1.0
            ),
            "max_ratio": float(
                active_ratio.max().item() if active_ratio.numel() else 1.0
            ),
            "score_scale": float(score_scale.item()),
            "saturated_fraction": float(
                self._saturated(active_ratio, ratio_limit)
                .to(ratio.dtype).mean().item()
                if active_ratio.numel() else 0.0
            ),
        }
        return changed
