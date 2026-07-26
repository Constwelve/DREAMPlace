"""Local congestion-gradient spreading objective."""

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin, map_gradient
from dreamplace.ops.routability_opt.plugins.utils import normalize_field, smooth_map


class LocalCongestionGradientPlugin(RoutabilityPlugin):
    name = "local_gradient"

    def apply_gradient(self, pos, model, context):
        signal = context.signal(pos)
        radius = int(getattr(self.params, "ruplace_local_gradient_smooth", 1))
        congestion = smooth_map(signal.overflow_map, radius)
        bx = (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl) / congestion.shape[0]
        by = (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl) / congestion.shape[1]
        gx, gy = normalize_field(*map_gradient(congestion, bx, by))
        node_gx, node_gy = context.sample_vector_field(pos, gx, gy)
        weight = float(getattr(self.params, "ruplace_local_gradient_weight", 0.05))
        field_norm = (gx.square() + gy.square()).sum().sqrt()
        changed = weight != 0.0 and bool(field_norm > 0)
        if changed:
            context.add_movable_gradient(pos, node_gx, node_gy, weight)
        self.metrics = {"field_norm": float(field_norm.item())}
        return changed
