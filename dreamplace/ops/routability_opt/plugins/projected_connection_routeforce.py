"""Connection routeforce projected against the placement-objective gradient."""

import math

import torch

from .connection_routeforce import ConnectionRouteForcePlugin


PROJECTION_MODES = {
    "global_nonopposing",
    "node_nonopposing",
    "global_orthogonal",
    "node_orthogonal",
}


def project_route_gradient(route_x, route_y, reference_x, reference_y, mode,
                           epsilon=1.0e-12, strength=1.0,
                           strength_x=None, strength_y=None):
    """Remove selected route-gradient components parallel to the reference."""
    mode = str(mode).lower()
    if mode not in PROJECTION_MODES:
        raise ValueError(
            "unsupported connection routeforce projection mode: %s" % mode
        )
    if route_x.shape != reference_x.shape or route_y.shape != reference_y.shape:
        raise ValueError("route and reference gradient shapes must match")
    if route_x.shape != route_y.shape:
        raise ValueError("x and y route gradient shapes must match")
    epsilon = float(epsilon)
    strength = float(strength)
    strength_x = strength if strength_x is None else float(strength_x)
    strength_y = strength if strength_y is None else float(strength_y)
    if not math.isfinite(epsilon) or epsilon < 0.0:
        raise ValueError("connection routeforce projection epsilon must be nonnegative")
    for axis, value in (("scalar", strength), ("x", strength_x), ("y", strength_y)):
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(
                "connection routeforce projection %s strength must be finite and in [0, 1]"
                % axis
            )

    reference_x = reference_x.to(device=route_x.device, dtype=route_x.dtype)
    reference_y = reference_y.to(device=route_y.device, dtype=route_y.dtype)
    threshold = max(float(epsilon), torch.finfo(route_x.dtype).eps)
    dot_per_node = route_x * reference_x + route_y * reference_y
    reference_norm_sq = reference_x.square() + reference_y.square()
    route_norm_before = torch.sqrt(route_x.square().sum() + route_y.square().sum())
    dot_before = dot_per_node.sum()

    if mode.startswith("global_"):
        denominator = reference_norm_sq.sum()
        valid = bool(denominator.item() > threshold)
        should_project = valid and (
            mode == "global_orthogonal" or dot_before.item() < 0.0
        )
        if should_project:
            coefficient_x = strength_x * dot_before / denominator
            coefficient_y = strength_y * dot_before / denominator
            projected_x = route_x - coefficient_x * reference_x
            projected_y = route_y - coefficient_y * reference_y
        else:
            projected_x = route_x
            projected_y = route_y
        projected_count = int(should_project)
        projected_fraction = float(projected_count)
        valid_count = int(valid)
    else:
        valid = reference_norm_sq > threshold
        if mode == "node_nonopposing":
            selected = valid & (dot_per_node < 0.0)
        else:
            selected = valid
        coefficient_x = torch.where(
            selected,
            strength_x * dot_per_node /
            reference_norm_sq.clamp_min(threshold),
            torch.zeros_like(dot_per_node),
        )
        coefficient_y = torch.where(
            selected,
            strength_y * dot_per_node /
            reference_norm_sq.clamp_min(threshold),
            torch.zeros_like(dot_per_node),
        )
        projected_x = route_x - coefficient_x * reference_x
        projected_y = route_y - coefficient_y * reference_y
        projected_count = int(selected.sum().item())
        projected_fraction = (
            projected_count / float(route_x.numel()) if route_x.numel() else 0.0
        )
        valid_count = int(valid.sum().item())

    dot_after = (
        projected_x * reference_x + projected_y * reference_y
    ).sum()
    route_norm_after = torch.sqrt(
        projected_x.square().sum() + projected_y.square().sum()
    )
    before_value = float(route_norm_before.item())
    metrics = {
        "projection_dot_before": float(dot_before.item()),
        "projection_dot_after": float(dot_after.item()),
        "projection_projected_count": projected_count,
        "projection_projected_fraction": projected_fraction,
        "projection_reference_valid_count": valid_count,
        "projection_norm_retained": (
            float(route_norm_after.item()) / before_value
            if before_value > 0.0 else 0.0
        ),
        "projection_strength": strength,
        "projection_strength_x": strength_x,
        "projection_strength_y": strength_y,
    }
    return projected_x, projected_y, metrics


class ProjectedConnectionRouteForcePlugin(ConnectionRouteForcePlugin):
    """Condition the routed-edge gradient before objective-relative scaling."""

    name = "projected_connection_routeforce"

    def condition_gradient(self, pos, context, grad_x, grad_y):
        reference = context.reference_movable_gradient()
        if reference is None:
            raise RuntimeError(
                "projected_connection_routeforce requires a placement gradient"
            )
        mode = getattr(
            self.params,
            "ruplace_projected_connection_routeforce_mode",
            "node_nonopposing",
        )
        epsilon = float(getattr(
            self.params,
            "ruplace_projected_connection_routeforce_epsilon",
            1.0e-12,
        ))
        strength = float(getattr(
            self.params,
            "ruplace_projected_connection_routeforce_strength",
            1.0,
        ))
        strength_x = getattr(
            self.params,
            "ruplace_projected_connection_routeforce_strength_x",
            None,
        )
        strength_y = getattr(
            self.params,
            "ruplace_projected_connection_routeforce_strength_y",
            None,
        )
        projected_x, projected_y, metrics = project_route_gradient(
            grad_x,
            grad_y,
            reference[0],
            reference[1],
            mode,
            epsilon,
            strength,
            strength_x,
            strength_y,
        )
        metrics["projection_mode"] = str(mode).lower()
        return projected_x, projected_y, metrics
