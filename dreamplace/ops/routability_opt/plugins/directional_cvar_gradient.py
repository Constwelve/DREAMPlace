"""Directional congestion force focused on the utilization-tail CVaR surrogate."""

import math

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins.directional_local_gradient import (
    directional_local_gradient_field,
)
from dreamplace.ops.routability_opt.plugins.utils import (
    map_on_placement_device,
    routing_bin_sizes,
)


def validated_directional_cvar_inputs(hv_utilization, hv_overflow, quantile,
                                      tail_blend):
    """Validate and sanitize the shared directional CVaR inputs."""
    if hv_utilization.ndim != 3 or hv_utilization.shape[0] < 2:
        raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")
    if hv_overflow.ndim != 3 or hv_overflow.shape[0] < 2:
        raise ValueError("H/V overflow must have shape [2, bins_x, bins_y]")
    if hv_utilization.shape != hv_overflow.shape:
        raise ValueError("H/V utilization and overflow shapes must match")
    quantile = float(quantile)
    tail_blend = float(tail_blend)
    if not math.isfinite(quantile) or not 0.0 <= quantile < 1.0:
        raise ValueError("directional CVaR quantile must be in [0, 1)")
    if not math.isfinite(tail_blend) or not 0.0 <= tail_blend <= 1.0:
        raise ValueError("directional CVaR tail blend must be in [0, 1]")

    utilization = torch.nan_to_num(
        hv_utilization[:2], nan=0.0, posinf=0.0, neginf=0.0
    ).clamp_min(0.0)
    overflow = torch.nan_to_num(
        hv_overflow[:2], nan=0.0, posinf=0.0, neginf=0.0
    ).clamp_min(0.0)
    return utilization, overflow, quantile, tail_blend


def blend_directional_cvar_pressure(overflow, tail, tail_blend):
    """RMS-match tail pressure to overflow before blending the two maps."""
    if tail_blend == 0.0:
        return overflow
    if tail_blend == 1.0:
        return tail

    # Match the tail pressure RMS to the existing overflow pressure before
    # blending, preserving the established force scale while changing where
    # the force is concentrated.
    overflow_rms = overflow.reshape(2, -1).square().mean(dim=1).sqrt()
    tail_rms = tail.reshape(2, -1).square().mean(dim=1).sqrt()
    tail_scale = overflow_rms / tail_rms.clamp_min(1e-12)
    tail_scaled = tail * tail_scale[:, None, None]
    return (1.0 - tail_blend) * overflow + tail_blend * tail_scaled


def directional_cvar_pressure(hv_utilization, hv_overflow, quantile,
                              tail_blend):
    """Blend overflow with excess above an all-bin per-axis quantile."""
    utilization, overflow, quantile, tail_blend = (
        validated_directional_cvar_inputs(
            hv_utilization, hv_overflow, quantile, tail_blend
        )
    )
    thresholds = torch.quantile(
        utilization.reshape(2, -1), quantile, dim=1
    ).detach().clamp_min(1.0)
    tail = (utilization - thresholds[:, None, None]).clamp_min(0.0)
    pressure = blend_directional_cvar_pressure(overflow, tail, tail_blend)
    return pressure, thresholds, tail


class DirectionalCVaRGradientPlugin(RoutabilityPlugin):
    """Move cells down a blended overflow and top-quantile pressure field."""

    name = "directional_cvar_gradient"
    parameter_prefix = "ruplace_directional_cvar_gradient"
    pressure_function = staticmethod(directional_cvar_pressure)
    conditioned_on_overflow = 0

    def parameter(self, suffix, default):
        return getattr(
            self.params, "%s_%s" % (self.parameter_prefix, suffix), default
        )

    def apply_gradient(self, pos, model, context):
        weight = float(self.parameter("weight", 0.05))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        if signal.hv_utilization_map is None or signal.hv_overflow_map is None:
            raise ValueError(
                "%s requires H/V utilization and overflow" % self.name
            )
        utilization = map_on_placement_device(signal.hv_utilization_map, pos)
        overflow = map_on_placement_device(signal.hv_overflow_map, pos)
        quantile = float(self.parameter("quantile", 0.99))
        tail_blend = float(self.parameter("tail_blend", 0.5))
        pressure, thresholds, tail = self.pressure_function(
            utilization, overflow, quantile, tail_blend
        )

        mode = str(self.parameter("mode", "both")).lower()
        if mode == "horizontal":
            gate_map = pressure[0]
        elif mode == "vertical":
            gate_map = pressure[1]
        elif mode == "both":
            gate_map = pressure.max(dim=0).values
        else:
            raise ValueError(
                "unsupported %s mode: %s" % (self.name, mode)
            )
        gate_passed, gate_metrics = self.congestion_stagnation_gate(
            context,
            gate_map,
            utilization_map=False,
            parameter_name=self.name,
        )
        if not gate_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {**schedule_metrics, **gate_metrics}
            return False

        axis_mapping = str(self.parameter(
            "axis_mapping", "matching_axis"
        )).lower()
        polarity = str(self.parameter("polarity", "repel")).lower()
        normalization = str(self.parameter("normalization", "joint")).lower()
        axis_balance = float(self.parameter("axis_balance", 1.0))
        smooth = int(self.parameter("smooth", 1))
        bx, by = routing_bin_sizes(self.placedb, pressure.shape[-2:])
        field_x, field_y = directional_local_gradient_field(
            pressure[0],
            pressure[1],
            smooth,
            str(getattr(
                self.params, "ruplace_force_smoothing_padding", "replicate"
            )).lower(),
            bx,
            by,
            mode,
            axis_balance,
            axis_mapping,
            polarity,
            normalization,
        )
        node_gx, node_gy = context.sample_vector_field(
            pos, field_x, field_y
        )
        field_x_norm = field_x.square().sum().sqrt()
        field_y_norm = field_y.square().sum().sqrt()
        field_norm = (field_x_norm.square() + field_y_norm.square()).sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "cvar_quantile": quantile,
            "cvar_tail_blend": tail_blend,
            "cvar_conditioned_on_overflow": self.conditioned_on_overflow,
            "cvar_horizontal_threshold": float(thresholds[0]),
            "cvar_vertical_threshold": float(thresholds[1]),
            "cvar_horizontal_active_bins": int((tail[0] > 0).sum().item()),
            "cvar_vertical_active_bins": int((tail[1] > 0).sum().item()),
            "cvar_horizontal_tail_sum": float(tail[0].sum().item()),
            "cvar_vertical_tail_sum": float(tail[1].sum().item()),
            "directional_mode_id": {
                "both": 0, "horizontal": 1, "vertical": 2,
            }[mode],
            "directional_axis_mapping_id": {
                "cross_track": 0, "matching_axis": 1,
            }[axis_mapping],
            "directional_polarity_id": {
                "repel": 0, "attract": 1,
            }[polarity],
            "directional_normalization_id": {
                "joint": 0, "per_axis": 1,
            }[normalization],
            "axis_balance": axis_balance,
            "field_x_norm": float(field_x_norm.item()),
            "field_y_norm": float(field_y_norm.item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **gate_metrics,
            **force_metrics,
        }
        return changed
