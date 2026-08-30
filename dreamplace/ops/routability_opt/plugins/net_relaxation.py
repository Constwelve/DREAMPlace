"""Congestion-aware relaxation of the wirelength objective."""

from dreamplace.ops.routability_opt.plugins.net_weighting import (
    CongestionNetWeightingPlugin,
    net_relaxation_ratios,
)


class CongestionNetRelaxationPlugin(CongestionNetWeightingPlugin):
    """Let density spreading dominate on nets that cross congested regions."""

    name = "net_relaxation"
    parameter_prefix = "ruplace_net_relaxation"

    def _ratio_limit(self):
        return float(self._param("min_weight", 0.5))

    def _ratios(self, net_score, active_nets, gamma, ratio_limit,
                normalization):
        return net_relaxation_ratios(
            net_score, active_nets, gamma, ratio_limit, normalization
        )

    def _saturated(self, active_ratio, ratio_limit):
        return active_ratio <= ratio_limit
