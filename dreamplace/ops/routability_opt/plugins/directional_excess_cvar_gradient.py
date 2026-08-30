"""Directional CVaR force conditioned on bins above routing capacity."""

import torch

from .directional_cvar_gradient import (
    DirectionalCVaRGradientPlugin,
    blend_directional_cvar_pressure,
    validated_directional_cvar_inputs,
)


def directional_excess_cvar_pressure(hv_utilization, hv_overflow, quantile,
                                     tail_blend):
    """Blend overflow with per-axis tails conditioned on utilization > 1."""
    utilization, overflow, quantile, tail_blend = (
        validated_directional_cvar_inputs(
            hv_utilization, hv_overflow, quantile, tail_blend
        )
    )
    thresholds = []
    for axis in range(2):
        congested = utilization[axis][utilization[axis] > 1.0]
        if congested.numel():
            threshold = torch.quantile(congested, quantile).detach()
        else:
            threshold = utilization.new_tensor(1.0)
        thresholds.append(threshold.clamp_min(1.0))
    thresholds = torch.stack(thresholds)
    tail = (utilization - thresholds[:, None, None]).clamp_min(0.0)
    pressure = blend_directional_cvar_pressure(overflow, tail, tail_blend)
    return pressure, thresholds, tail


class DirectionalExcessCVaRGradientPlugin(DirectionalCVaRGradientPlugin):
    """Move cells down a CVaR field conditioned on capacity-exceeding bins."""

    name = "directional_excess_cvar_gradient"
    parameter_prefix = "ruplace_directional_excess_cvar_gradient"
    pressure_function = staticmethod(directional_excess_cvar_pressure)
    conditioned_on_overflow = 1
