"""Global Poisson/Coulomb congestion-force objective."""

from dreamplace.ops.routability_opt.plugin_base import (
    RoutabilityPlugin,
    map_gradient,
    poisson_potential,
)
from dreamplace.ops.routability_opt.plugins.utils import normalize_field, smooth_map


class PoissonCongestionForcePlugin(RoutabilityPlugin):
    name = "poisson_force"

    def apply_gradient(self, pos, model, context):
        signal = context.signal(pos)
        radius = int(getattr(self.params, "ruplace_poisson_smooth", 1))
        charge = smooth_map(signal.overflow_map, radius)
        potential = poisson_potential(charge)
        bx = (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl) / charge.shape[0]
        by = (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl) / charge.shape[1]
        gx, gy = normalize_field(*map_gradient(potential, bx, by))
        node_gx, node_gy = context.sample_vector_field(pos, gx, gy)
        weight = float(getattr(self.params, "ruplace_poisson_weight", 0.05))
        potential_rms = potential.square().mean().sqrt()
        changed = weight != 0.0 and bool(potential_rms > 0)
        if changed:
            context.add_movable_gradient(pos, node_gx, node_gy, weight)
        self.metrics = {"potential_rms": float(potential_rms.item())}
        return changed
