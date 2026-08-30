"""Pin-density and macro-porosity cell-padding plugin."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins.utils import (
    rectangle_overlap_map,
    smooth_map,
)
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation


class PinDensityPorosityPlugin(RoutabilityPlugin):
    name = "pin_porosity"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.engine = RUPlaceInflation(params, placedb, data_collections)
        self.rounds = 0

    def _macro_porosity_map(self, pos, shape):
        nx, ny = shape
        result = pos.new_zeros(shape)
        first = self.placedb.num_movable_nodes
        last = self.placedb.num_physical_nodes
        if last <= first:
            return result
        area = self.data_collections.node_size_x[first:last] * self.data_collections.node_size_y[first:last]
        movable_area = (
            self.data_collections.node_size_x[:first] * self.data_collections.node_size_y[:first]
        )
        threshold = movable_area.median() * float(
            getattr(self.params, "ruplace_macro_area_threshold", 16.0)
        )
        macro = area >= threshold
        if not macro.any():
            return result
        n = self.placedb.num_nodes
        width = self.data_collections.node_size_x[first:last][macro]
        height = self.data_collections.node_size_y[first:last][macro]
        xl = pos[first:last][macro]
        yl = pos[n + first:n + last][macro]
        result = rectangle_overlap_map(
            xl, yl, xl + width, yl + height, shape,
            (
                self.placedb.routing_grid_xl,
                self.placedb.routing_grid_yl,
                self.placedb.routing_grid_xh,
                self.placedb.routing_grid_yh,
            ),
            dtype=pos.dtype,
            device=pos.device,
        )
        result = smooth_map(result, int(getattr(self.params, "ruplace_porosity_radius", 3)))
        return result / result[result > 0].mean().clamp_min(1e-12) if (result > 0).any() else result

    def maybe_adjust_area(self, pos, model, context):
        if self.rounds >= int(getattr(self.params, "ruplace_pin_porosity_rounds", 4)):
            return False
        signal = context.signal(pos, refresh=True)
        pin_map = signal.pin_utilization_map
        if pin_map is None:
            pin_map = context.op_collections.pin_utilization_map_op(pos)
        pin_overflow = (pin_map - 1.0).clamp_min(0.0)
        porosity = self._macro_porosity_map(pos, pin_map.shape)
        combined = pin_overflow + float(
            getattr(self.params, "ruplace_porosity_weight", 0.25)
        ) * porosity
        exposure = context.sample_map(pos, combined)
        target = self.engine.current_inflate_ratio.to(pos.device, pos.dtype) + float(
            getattr(self.params, "ruplace_pin_porosity_gamma", 0.25)
        ) * exposure
        changed = self.engine.apply_node_ratios(pos, target)
        self.rounds += 1
        self.metrics = {"rounds": self.rounds, "changed": bool(changed)}
        return changed
