"""Classical route-map-driven cell inflation plugin."""

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from dreamplace.ops.routability_opt.ruplace_op import RUPlaceInflation


class RouteInflationPlugin(RoutabilityPlugin):
    name = "route_inflation"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.engine = RUPlaceInflation(params, placedb, data_collections)
        self.rounds = 0

    def maybe_adjust_area(self, pos, model, context):
        max_rounds = int(getattr(self.params, "ruplace_local_inflate_max_rounds", 0))
        if self.rounds > max_rounds:
            return False
        signal = context.signal(pos, refresh=True)
        changed = self.engine.apply(pos, signal, global_pass=self.rounds == 0)
        self.rounds += 1
        self.metrics = {"rounds": self.rounds, "changed": bool(changed)}
        return changed
