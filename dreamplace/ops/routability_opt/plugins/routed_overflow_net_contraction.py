"""Directional contraction of routed segments crossing overflow resources."""

import math

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin
from .projected_connection_routeforce import PROJECTION_MODES, project_route_gradient


class RoutedOverflowNetContractionPlugin(RoutabilityPlugin):
    """Contract H/V routed segments using the matching GPUGR overflow map."""

    name = "routed_overflow_net_contraction"

    def apply_gradient(self, pos, model, context):
        backend = getattr(context.proxy, "backend", None)
        if backend is None or not hasattr(
                backend, "routed_overflow_contraction_gradient"):
            raise RuntimeError(
                "routed_overflow_net_contraction requires the in-process "
                "gpugr/xplace proxy"
            )
        if getattr(backend, "external_route_eval", False):
            raise RuntimeError(
                "routed_overflow_net_contraction requires "
                "ruplace_external_route_eval=0"
            )

        weight = float(getattr(
            self.params, "ruplace_routed_overflow_net_contraction_weight", 0.0025
        ))
        weight, schedule_metrics = self.scheduled_force_weight(
            context, weight, parameter_name="routed_overflow_net_contraction"
        )
        if weight is None:
            self.metrics = schedule_metrics
            return False

        x_scale = float(getattr(
            self.params, "ruplace_routed_overflow_net_contraction_x_scale", 1.0
        ))
        y_scale = float(getattr(
            self.params, "ruplace_routed_overflow_net_contraction_y_scale", 1.0
        ))
        if (not math.isfinite(x_scale) or not math.isfinite(y_scale) or
                x_scale < 0.0 or y_scale < 0.0):
            raise ValueError(
                "routed overflow net contraction axis scales must be finite "
                "and nonnegative"
            )
        if x_scale == 0.0 and y_scale == 0.0:
            raise ValueError(
                "routed overflow net contraction requires a nonzero axis scale"
            )

        route_freq = max(1, int(getattr(
            self.params, "ruplace_routed_overflow_net_contraction_route_freq", 80
        )))
        refresh = (
            getattr(backend, "last_route", None) is None
            or context.iteration % route_freq == 0
        )
        grad, route_metrics = backend.routed_overflow_contraction_gradient(
            pos,
            refresh=refresh,
            mode=getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_mode",
                "directional",
            ),
            overflow_threshold=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_threshold",
                0.0,
            )),
            overflow_exponent=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_exponent",
                1.0,
            )),
            max_wire_span=int(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_max_wire_span",
                19,
            )),
            distance_weighting=getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_distance_weighting",
                "uniform",
            ),
            matching_contraction_scale=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_matching_scale",
                1.0,
            )),
            orthogonal_spread_scale=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_orthogonal_spread_scale",
                0.0,
            )),
            smoothing_radius=int(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_smoothing_radius",
                0,
            )),
            smoothing_padding=getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_smoothing_padding",
                "replicate",
            ),
            utilization_pressure_scale=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_utilization_pressure_scale",
                0.0,
            )),
            utilization_threshold=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_utilization_threshold",
                1.0,
            )),
            utilization_exponent=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_utilization_exponent",
                1.0,
            )),
        )
        if not torch.isfinite(grad).all():
            raise RuntimeError(
                "routed_overflow_net_contraction produced a non-finite gradient"
            )
        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        grad_x = grad[:m] * x_scale
        grad_y = grad[n:n + m] * y_scale
        projection_mode = str(getattr(
            self.params,
            "ruplace_routed_overflow_net_contraction_projection_mode",
            "none",
        )).lower()
        projection_strength = float(getattr(
            self.params,
            "ruplace_routed_overflow_net_contraction_projection_strength",
            0.0,
        ))
        if projection_mode == "none":
            if (not math.isfinite(projection_strength)
                    or projection_strength < 0.0
                    or projection_strength > 1.0):
                raise ValueError(
                    "routed overflow contraction projection strength must be "
                    "finite and in [0, 1]"
                )
            projection_metrics = {
                "objective_projection_strength": projection_strength,
                "objective_projection_projected_count": 0,
                "objective_projection_projected_fraction": 0.0,
                "objective_projection_mode": projection_mode,
            }
        else:
            if projection_mode not in PROJECTION_MODES:
                raise ValueError(
                    "unsupported routed overflow contraction projection mode: %s"
                    % projection_mode
                )
            reference = context.reference_movable_gradient()
            if reference is None:
                raise RuntimeError(
                    "routed overflow contraction objective projection requires "
                    "a placement gradient"
                )
            grad_x, grad_y, projection_metrics = project_route_gradient(
                grad_x,
                grad_y,
                reference[0],
                reference[1],
                projection_mode,
                strength=projection_strength,
            )
            projection_metrics.update({
                "objective_projection_strength": projection_strength,
                "objective_projection_projected_count": projection_metrics[
                    "projection_projected_count"
                ],
                "objective_projection_projected_fraction": projection_metrics[
                    "projection_projected_fraction"
                ],
                "objective_projection_mode": projection_mode,
            })
        scaling = context.add_scaled_movable_gradient(
            pos,
            grad_x,
            grad_y,
            weight,
            scale_mode=getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_scale_mode",
                "relative",
            ),
            max_ratio=float(getattr(
                self.params,
                "ruplace_routed_overflow_net_contraction_max_ratio",
                0.05,
            )),
        )
        changed = scaling["applied_scale"] != 0.0 and scaling["field_rms"] != 0.0
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "contraction_x_scale": x_scale,
            "contraction_y_scale": y_scale,
            **route_metrics,
            **projection_metrics,
            **schedule_metrics,
            **scaling,
        }
        return changed
