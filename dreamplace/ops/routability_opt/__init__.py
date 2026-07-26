"""Routability optimization ops."""

from .ruplace_op import RUPlaceController, RUPlaceInflation, RoutabilityOptOp
from .pipeline import RoutabilityOptimizationPipeline


def build_routability_opt_op(params, placedb, data_collections, op_collections=None):
    if getattr(params, "ruplace_flag", 0):
        if getattr(params, "ruplace_plugins", []):
            return RoutabilityOptimizationPipeline(
                params, placedb, data_collections, op_collections
            )
        return RUPlaceController(params, placedb, data_collections)
    return None


__all__ = [
    "RUPlaceController",
    "RUPlaceInflation",
    "RoutabilityOptOp",
    "RoutabilityOptimizationPipeline",
    "build_routability_opt_op",
]
