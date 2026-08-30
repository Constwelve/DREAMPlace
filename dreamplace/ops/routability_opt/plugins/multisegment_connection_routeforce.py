"""Connection routeforce that retains every routed branch at a global pin."""

from dreamplace.ops.routability_opt.plugins.connection_routeforce import (
    ConnectionRouteForcePlugin,
)


class MultiSegmentConnectionRouteForcePlugin(ConnectionRouteForcePlugin):
    """Retain multiple same-axis route branches with selectable reduction."""

    name = "multisegment_connection_routeforce"

    def segment_reduction(self):
        return str(getattr(
            self.params,
            "ruplace_multisegment_connection_routeforce_reduction",
            "sum",
        )).lower()

    def segment_blend(self):
        return float(getattr(
            self.params,
            "ruplace_multisegment_connection_routeforce_blend",
            0.5,
        ))
