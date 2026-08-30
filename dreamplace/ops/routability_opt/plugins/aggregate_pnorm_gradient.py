"""Aggregate congestion force using an Lp overflow pressure objective."""

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


def aggregate_pnorm_pressure(utilization, exponent, threshold=1.0):
    """Raise capacity excess to an Lp exponent to emphasize peak bins."""
    if utilization.ndim != 2:
        raise ValueError("aggregate utilization must be a 2D tensor")
    exponent = float(exponent)
    threshold = float(threshold)
    if not math.isfinite(exponent) or exponent < 1.0:
        raise ValueError("aggregate Lp exponent must be finite and at least one")
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("aggregate Lp threshold must be finite and nonnegative")
    utilization = torch.nan_to_num(
        utilization, nan=0.0, posinf=0.0, neginf=0.0
    ).clamp_min(0.0)
    excess = (utilization - threshold).clamp_min(0.0)
    return excess.pow(exponent), excess


class AggregatePNormGradientPlugin(RoutabilityPlugin):
    """Move cells down an aggregate Lp overflow-pressure field."""

    name = "aggregate_pnorm_gradient"

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_aggregate_pnorm_gradient_weight", 0.05
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        if signal.utilization_map is None or signal.overflow_map is None:
            raise ValueError(
                "aggregate_pnorm_gradient requires aggregate utilization and "
                "overflow"
            )
        utilization = map_on_placement_device(signal.utilization_map, pos)
        overflow = map_on_placement_device(signal.overflow_map, pos)
        exponent = float(getattr(
            self.params, "ruplace_aggregate_pnorm_gradient_exponent", 2.0
        ))
        threshold = float(getattr(
            self.params, "ruplace_aggregate_pnorm_gradient_threshold", 1.0
        ))
        pressure, excess = aggregate_pnorm_pressure(
            utilization, exponent, threshold
        )

        # Keep activation invariant across the exponent sweep so the campaign
        # measures objective shape rather than a changing severity gate.
        gate_passed, gate_metrics = self.congestion_stagnation_gate(
            context,
            overflow,
            utilization_map=False,
            parameter_name=self.name,
        )
        if not gate_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {**schedule_metrics, **gate_metrics}
            return False

        radius = int(getattr(
            self.params, "ruplace_aggregate_pnorm_gradient_smooth", 1
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
            "pnorm_exponent": exponent,
            "pnorm_threshold": threshold,
            "pnorm_active_bins": int((excess > 0).sum().item()),
            "pnorm_excess_sum": float(excess.sum().item()),
            "pnorm_pressure_sum": float(pressure.sum().item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **gate_metrics,
            **force_metrics,
        }
        return changed
