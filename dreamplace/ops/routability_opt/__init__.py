"""Routability optimization ops."""

from .ruplace_op import RUPlaceController, RUPlaceInflation, RoutabilityOptOp


def build_routability_opt_op(params, placedb, data_collections):
    if getattr(params, "ruplace_flag", 0):
        return RUPlaceController(params, placedb, data_collections)
    return None


__all__ = ["RUPlaceController", "RUPlaceInflation", "RoutabilityOptOp", "build_routability_opt_op"]
