"""Aggregate congestion force focused on the utilization-tail CVaR surrogate."""

import math

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


def validated_aggregate_cvar_inputs(utilization, overflow, quantile,
                                    tail_blend):
    """Validate and sanitize aggregate CVaR pressure inputs."""
    if utilization.ndim != 2 or overflow.ndim != 2:
        raise ValueError("aggregate utilization and overflow must be 2D tensors")
    if utilization.shape != overflow.shape:
        raise ValueError("aggregate utilization and overflow shapes must match")
    quantile = float(quantile)
    tail_blend = float(tail_blend)
    if not math.isfinite(quantile) or not 0.0 <= quantile < 1.0:
        raise ValueError("aggregate CVaR quantile must be in [0, 1)")
    if not math.isfinite(tail_blend) or not 0.0 <= tail_blend <= 1.0:
        raise ValueError("aggregate CVaR tail blend must be in [0, 1]")

    utilization = torch.nan_to_num(
        utilization, nan=0.0, posinf=0.0, neginf=0.0
    ).clamp_min(0.0)
    overflow = torch.nan_to_num(
        overflow, nan=0.0, posinf=0.0, neginf=0.0
    ).clamp_min(0.0)
    return utilization, overflow, quantile, tail_blend


def blend_aggregate_cvar_pressure(overflow, tail, tail_blend):
    """RMS-match aggregate tail pressure to overflow before blending."""
    if tail_blend == 0.0:
        return overflow
    if tail_blend == 1.0:
        return tail

    overflow_rms = overflow.square().mean().sqrt()
    tail_rms = tail.square().mean().sqrt()
    tail_scaled = tail * (overflow_rms / tail_rms.clamp_min(1e-12))
    return (1.0 - tail_blend) * overflow + tail_blend * tail_scaled


def aggregate_cvar_pressure(utilization, overflow, quantile, tail_blend):
    """Blend aggregate overflow with excess above an all-bin quantile."""
    utilization, overflow, quantile, tail_blend = (
        validated_aggregate_cvar_inputs(
            utilization, overflow, quantile, tail_blend
        )
    )
    threshold = torch.quantile(
        utilization.reshape(-1), quantile
    ).detach().clamp_min(1.0)
    tail = (utilization - threshold).clamp_min(0.0)
    pressure = blend_aggregate_cvar_pressure(overflow, tail, tail_blend)
    return pressure, threshold, tail


class AggregateCVaRGradientPlugin(RoutabilityPlugin):
    """Move cells down the aggregate overflow and utilization-tail field."""

    name = "aggregate_cvar_gradient"

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_aggregate_cvar_gradient_weight", 0.05
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        if signal.utilization_map is None or signal.overflow_map is None:
            raise ValueError(
                "aggregate_cvar_gradient requires aggregate utilization and "
                "overflow"
            )
        utilization = map_on_placement_device(signal.utilization_map, pos)
        overflow = map_on_placement_device(signal.overflow_map, pos)
        quantile = float(getattr(
            self.params, "ruplace_aggregate_cvar_gradient_quantile", 0.99
        ))
        tail_blend = float(getattr(
            self.params, "ruplace_aggregate_cvar_gradient_tail_blend", 0.5
        ))
        pressure, threshold, tail = aggregate_cvar_pressure(
            utilization, overflow, quantile, tail_blend
        )

        gate_passed, gate_metrics = self.congestion_stagnation_gate(
            context,
            pressure,
            utilization_map=False,
            parameter_name=self.name,
        )
        if not gate_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {**schedule_metrics, **gate_metrics}
            return False

        radius = int(getattr(
            self.params, "ruplace_aggregate_cvar_gradient_smooth", 1
        ))
        padding = str(getattr(
            self.params, "ruplace_force_smoothing_padding", "replicate"
        )).lower()
        pressure = smooth_map(pressure, radius, padding)
        bx, by = routing_bin_sizes(self.placedb, pressure.shape)
        field_x, field_y = normalize_field(*map_gradient(pressure, bx, by))
        node_gx, node_gy = context.sample_vector_field(
            pos, field_x, field_y
        )
        field_norm = (field_x.square() + field_y.square()).sum().sqrt()
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
            "cvar_threshold": float(threshold.item()),
            "cvar_active_bins": int((tail > 0).sum().item()),
            "cvar_tail_sum": float(tail.sum().item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **gate_metrics,
            **force_metrics,
        }
        return changed
