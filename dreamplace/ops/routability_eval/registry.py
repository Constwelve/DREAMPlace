"""Evaluator registry."""

from .cugr import CUGREvaluator
from .innovus import InnovusEvaluator
from .nctugr import NCTUgrEvaluator
from .openroad import OpenROADEvaluator
from .rudy import PinRudyEvaluator, RudyEvaluator
from .xplace import BundledGPUGREvaluator, XplaceEvaluator


EVALUATOR_REGISTRY = {
    "rudy": RudyEvaluator,
    "pin_rudy": PinRudyEvaluator,
    "xplace": XplaceEvaluator,
    "gpugr": BundledGPUGREvaluator,
    "cugr": CUGREvaluator,
    "nctugr": NCTUgrEvaluator,
    "openroad": OpenROADEvaluator,
    "innovus": InnovusEvaluator,
}


VALIDATION_ROLES = {
    "golden": ("openroad", "innovus"),
    "fallback_reference": ("rudy", "gpugr"),
    "diagnostic_only": ("pin_rudy", "xplace", "cugr", "nctugr"),
}

DEFAULT_VALIDATION_EVALUATORS = (
    VALIDATION_ROLES["golden"] + VALIDATION_ROLES["fallback_reference"]
)


def validation_role(name):
    """Return the policy role for an evaluator backend."""
    normalized = name.lower()
    for role, backends in VALIDATION_ROLES.items():
        if normalized in backends:
            return role
    raise ValueError(
        "Unknown evaluator %s; choices: %s"
        % (name, ", ".join(sorted(EVALUATOR_REGISTRY)))
    )


def select_common_validation_role(results_by_method):
    """Select the strongest tier containing a shared OK backend for every method.

    Mixing a golden result for one method with a fallback result for another is
    not a valid comparison. Neither is comparing OpenROAD for one method against
    Innovus for another. Diagnostic-only evaluators are intentionally never selected.
    """
    if not results_by_method:
        return None
    for role in ("golden", "fallback_reference"):
        if common_validation_backends(results_by_method, role):
            return role
    return None


def common_validation_backends(results_by_method, role):
    """Return same-tool backends with an OK result for every compared method."""
    if not results_by_method:
        return ()
    return tuple(
        backend for backend in VALIDATION_ROLES[role]
        if all(any(
            result.status == "ok" and result.backend.lower() == backend
            for result in results
        ) for results in results_by_method.values())
    )


def build_evaluator(name):
    try:
        return EVALUATOR_REGISTRY[name.lower()]()
    except KeyError:
        raise ValueError(
            "Unknown evaluator %s; choices: %s"
            % (name, ", ".join(sorted(EVALUATOR_REGISTRY)))
        )
