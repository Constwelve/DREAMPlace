"""Low-frequency whitespace-allocation force for congested regions."""

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin, map_gradient
from dreamplace.ops.routability_opt.plugins.utils import normalize_field, smooth_map


class WhitespaceAllocationPlugin(RoutabilityPlugin):
    name = "whitespace"

    def apply_gradient(self, pos, model, context):
        signal = context.signal(pos)
        radius = int(getattr(self.params, "ruplace_whitespace_radius", 5))
        regional_congestion = smooth_map(signal.overflow_map, radius)
        gx, gy = normalize_field(*map_gradient(regional_congestion))
        node_gx, node_gy = context.sample_vector_field(pos, gx, gy)
        weight = float(getattr(self.params, "ruplace_whitespace_weight", 0.03))
        field_norm = (gx.square() + gy.square()).sum().sqrt()
        changed = weight != 0.0 and bool(field_norm > 0)
        if changed:
            context.add_movable_gradient(pos, node_gx, node_gy, weight)
        self.metrics = {
            "regional_peak": float(regional_congestion.max().item()),
            "field_norm": float(field_norm.item()),
        }
        return changed
