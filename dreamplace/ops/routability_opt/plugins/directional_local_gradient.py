"""Node-level local gradients from separate horizontal and vertical pressure."""

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


def directional_local_gradient_field(horizontal, vertical, smooth_radius,
                                     padding_mode, bin_size_x=1.0,
                                     bin_size_y=1.0, mode="both",
                                     axis_balance=1.0,
                                     axis_mapping="cross_track",
                                     polarity="repel",
                                     normalization="joint",
                                     aggregate=None,
                                     aggregate_blend=0.0):
    """Return directional gradients with selectable route-to-motion mapping."""
    if horizontal.shape != vertical.shape or horizontal.ndim != 2:
        raise ValueError("directional local-gradient maps must be equal 2D tensors")
    mode = str(mode).lower()
    if mode not in ("both", "horizontal", "vertical"):
        raise ValueError(
            "unsupported ruplace_directional_local_gradient_mode: %s" % mode
        )
    axis_mapping = str(axis_mapping).lower()
    if axis_mapping not in ("cross_track", "matching_axis"):
        raise ValueError(
            "unsupported ruplace_directional_local_gradient_axis_mapping: %s"
            % axis_mapping
        )
    polarity = str(polarity).lower()
    if polarity not in ("repel", "attract"):
        raise ValueError(
            "unsupported ruplace_directional_local_gradient_polarity: %s"
            % polarity
        )
    normalization = str(normalization).lower()
    if normalization not in ("joint", "per_axis"):
        raise ValueError(
            "unsupported ruplace_directional_local_gradient_normalization: %s"
            % normalization
        )
    axis_balance = float(axis_balance)
    if not math.isfinite(axis_balance) or axis_balance <= 0.0:
        raise ValueError(
            "ruplace_directional_local_gradient_axis_balance must be finite "
            "and positive"
        )
    aggregate_blend = float(aggregate_blend)
    if not math.isfinite(aggregate_blend) or not 0.0 <= aggregate_blend <= 1.0:
        raise ValueError(
            "ruplace_directional_local_gradient_aggregate_blend must be "
            "finite and in [0, 1]"
        )

    horizontal = smooth_map(horizontal, smooth_radius, padding_mode)
    vertical = smooth_map(vertical, smooth_radius, padding_mode)
    horizontal_gx, horizontal_gy = map_gradient(
        horizontal, bin_size_x, bin_size_y
    )
    vertical_gx, vertical_gy = map_gradient(
        vertical, bin_size_x, bin_size_y
    )
    if axis_mapping == "cross_track":
        field_x = (
            vertical_gx if mode in ("both", "vertical")
            else torch.zeros_like(vertical_gx)
        )
        field_y = (
            horizontal_gy if mode in ("both", "horizontal")
            else torch.zeros_like(horizontal_gy)
        )
    else:
        field_x = (
            horizontal_gx if mode in ("both", "horizontal")
            else torch.zeros_like(horizontal_gx)
        )
        field_y = (
            vertical_gy if mode in ("both", "vertical")
            else torch.zeros_like(vertical_gy)
        )
    if aggregate_blend > 0.0:
        if aggregate is None:
            raise ValueError(
                "directional local-gradient aggregate blend requires an "
                "aggregate feedback map"
            )
        if aggregate.shape != horizontal.shape or aggregate.ndim != 2:
            raise ValueError(
                "directional local-gradient aggregate map must match H/V maps"
            )
        aggregate = smooth_map(aggregate, smooth_radius, padding_mode)
        aggregate_gx, aggregate_gy = map_gradient(
            aggregate, bin_size_x, bin_size_y
        )
        directional_scale = 1.0 - aggregate_blend
        field_x = directional_scale * field_x + aggregate_blend * aggregate_gx
        field_y = directional_scale * field_y + aggregate_blend * aggregate_gy
    if normalization == "per_axis":
        field_x = field_x / field_x.square().mean().sqrt().clamp_min(1e-12)
        field_y = field_y / field_y.square().mean().sqrt().clamp_min(1e-12)
    polarity_scale = 1.0 if polarity == "repel" else -1.0
    axis_scale = math.sqrt(axis_balance)
    return normalize_field(
        field_x * axis_scale * polarity_scale,
        field_y / axis_scale * polarity_scale,
    )


class DirectionalLocalCongestionGradientPlugin(RoutabilityPlugin):
    """Move individual cells across congested horizontal and vertical tracks."""

    name = "directional_local_gradient"

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(
            self.params, "ruplace_directional_local_gradient_weight", 0.05
        ))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False

        signal = context.signal(pos)
        feedback = str(getattr(
            self.params,
            "ruplace_directional_local_gradient_feedback",
            "overflow",
        )).lower()
        if feedback == "overflow":
            hv = signal.hv_overflow_map
            utilization_map = False
        elif feedback == "utilization":
            hv = signal.hv_utilization_map
            utilization_map = True
        else:
            raise ValueError(
                "unsupported ruplace_directional_local_gradient_feedback: %s"
                % feedback
            )
        if hv is None:
            raise ValueError(
                "directional_local_gradient requires H/V %s feedback" % feedback
            )
        hv = map_on_placement_device(hv, pos)
        if hv.ndim != 3 or hv.shape[0] != 2:
            raise ValueError("H/V feedback must have shape [2, bins_x, bins_y]")

        mode = str(getattr(
            self.params, "ruplace_directional_local_gradient_mode", "both"
        )).lower()
        axis_mapping = str(getattr(
            self.params,
            "ruplace_directional_local_gradient_axis_mapping",
            "cross_track",
        )).lower()
        polarity = str(getattr(
            self.params,
            "ruplace_directional_local_gradient_polarity",
            "repel",
        )).lower()
        normalization = str(getattr(
            self.params,
            "ruplace_directional_local_gradient_normalization",
            "joint",
        )).lower()
        aggregate_blend = float(getattr(
            self.params,
            "ruplace_directional_local_gradient_aggregate_blend",
            0.0,
        ))
        aggregate = None
        if aggregate_blend > 0.0:
            aggregate = map_on_placement_device(
                signal.utilization_map if utilization_map else signal.overflow_map,
                pos,
            )
        if mode == "horizontal":
            gate_map = hv[0]
        elif mode == "vertical":
            gate_map = hv[1]
        elif mode == "both":
            gate_map = hv.max(dim=0).values
        else:
            raise ValueError(
                "unsupported ruplace_directional_local_gradient_mode: %s" % mode
            )
        gate_passed, gate_metrics = self.congestion_stagnation_gate(
            context,
            gate_map,
            utilization_map=utilization_map,
            parameter_name=self.name,
        )
        if not gate_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {**schedule_metrics, **gate_metrics}
            return False

        tail_passed, tail_metrics = self.congestion_tail_gate(
            context, signal, parameter_name=self.name
        )
        if not tail_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {
                **schedule_metrics,
                **gate_metrics,
                **tail_metrics,
            }
            return False

        bx, by = routing_bin_sizes(self.placedb, hv.shape[-2:])
        field_x, field_y = directional_local_gradient_field(
            hv[0],
            hv[1],
            int(getattr(
                self.params, "ruplace_directional_local_gradient_smooth", 1
            )),
            str(getattr(
                self.params, "ruplace_force_smoothing_padding", "replicate"
            )).lower(),
            bx,
            by,
            mode,
            getattr(
                self.params,
                "ruplace_directional_local_gradient_axis_balance",
                1.0,
            ),
            axis_mapping,
            polarity,
            normalization,
            aggregate,
            aggregate_blend,
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
            "directional_feedback_utilization": int(utilization_map),
            "directional_mode_id": {
                "both": 0,
                "horizontal": 1,
                "vertical": 2,
            }[mode],
            "directional_axis_mapping_id": {
                "cross_track": 0,
                "matching_axis": 1,
            }[axis_mapping],
            "directional_polarity_id": {
                "repel": 0,
                "attract": 1,
            }[polarity],
            "directional_normalization_id": {
                "joint": 0,
                "per_axis": 1,
            }[normalization],
            "directional_aggregate_blend": aggregate_blend,
            "axis_balance": float(getattr(
                self.params,
                "ruplace_directional_local_gradient_axis_balance",
                1.0,
            )),
            "field_x_norm": float(field_x_norm.item()),
            "field_y_norm": float(field_y_norm.item()),
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **gate_metrics,
            **tail_metrics,
            **force_metrics,
        }
        return changed
