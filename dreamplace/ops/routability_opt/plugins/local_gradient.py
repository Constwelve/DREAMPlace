"""Local congestion-gradient spreading objective."""

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin, map_gradient
from dreamplace.ops.routability_opt.plugins.utils import (
    force_map_options,
    normalize_field,
    routing_bin_sizes,
    select_congestion_map,
    smooth_map,
)


class LocalCongestionGradientPlugin(RoutabilityPlugin):
    name = "local_gradient"

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(self.params, "ruplace_local_gradient_weight", 0.05))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False
        signal = context.signal(pos)
        radius = int(getattr(self.params, "ruplace_local_gradient_smooth", 1))
        map_mode, padding_mode, _ = force_map_options(self.params)
        selected_map = select_congestion_map(signal, map_mode)
        gate_passed, gate_metrics = self.congestion_stagnation_gate(
            context,
            selected_map,
            utilization_map="utilization" in str(map_mode).lower(),
        )
        if not gate_passed:
            schedule_metrics["force_applications"] = self.force_applications
            self.metrics = {**schedule_metrics, **gate_metrics}
            return False
        congestion = smooth_map(selected_map, radius, padding_mode)
        bx, by = routing_bin_sizes(self.placedb, congestion.shape)
        gx, gy = normalize_field(*map_gradient(congestion, bx, by))
        node_gx, node_gy = context.sample_vector_field(pos, gx, gy)
        field_norm = (gx.square() + gy.square()).sum().sqrt()
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = force_metrics["applied_scale"] != 0.0 and bool(field_norm > 0)
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "field_norm": float(field_norm.item()),
            **schedule_metrics,
            **gate_metrics,
            **force_metrics,
        }
        return changed
