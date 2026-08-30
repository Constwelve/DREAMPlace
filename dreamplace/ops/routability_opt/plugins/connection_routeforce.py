"""Xplace routed-segment overflow force as an independent plugin."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin


class ConnectionRouteForcePlugin(RoutabilityPlugin):
    """Move routed pin connections using edge demand and capacity feedback."""

    name = "connection_routeforce"

    def segment_reduction(self):
        """Preserve Xplace's last-segment reference behavior."""
        return "last"

    def segment_blend(self):
        """Reference plugin does not mix last- and summed-branch gradients."""
        return 0.0

    def condition_gradient(self, pos, context, grad_x, grad_y):
        """Hook for independently registered route-gradient conditioners."""
        return grad_x, grad_y, {}

    def apply_gradient(self, pos, model, context):
        backend = getattr(context.proxy, "backend", None)
        if backend is None or not hasattr(backend, "connection_route_gradient"):
            raise RuntimeError(
                "connection_routeforce requires the in-process gpugr/xplace proxy"
            )
        if getattr(backend, "external_route_eval", False):
            raise RuntimeError(
                "connection_routeforce requires ruplace_external_route_eval=0"
            )

        weight = float(getattr(
            self.params, "ruplace_connection_routeforce_weight", 0.0025
        ))
        weight, schedule_metrics = self.scheduled_force_weight(
            context, weight, parameter_name="connection_routeforce"
        )
        if weight is None:
            self.metrics = schedule_metrics
            return False

        x_scale = float(getattr(
            self.params, "ruplace_connection_routeforce_x_scale", 1.0
        ))
        y_scale = float(getattr(
            self.params, "ruplace_connection_routeforce_y_scale", 1.0
        ))
        if x_scale < 0.0 or y_scale < 0.0:
            raise ValueError("connection routeforce axis scales must be nonnegative")
        if x_scale == 0.0 and y_scale == 0.0:
            raise ValueError("connection routeforce requires a nonzero axis scale")

        route_freq = max(1, int(getattr(
            self.params, "ruplace_connection_routeforce_route_freq", 100
        )))
        refresh = (
            getattr(backend, "last_route", None) is None
            or context.iteration % route_freq == 0
        )
        grad, route_metrics = backend.connection_route_gradient(
            pos,
            refresh=refresh,
            overflow_threshold=float(getattr(
                self.params,
                "ruplace_connection_routeforce_overflow_threshold",
                0.0,
            )),
            max_wire_span=int(getattr(
                self.params, "ruplace_connection_routeforce_max_wire_span", 19
            )),
            distance_weighting=str(getattr(
                self.params,
                "ruplace_connection_routeforce_distance_weighting",
                "uniform",
            )),
            field_mode=str(getattr(
                self.params,
                "ruplace_connection_routeforce_field_mode",
                "aggregate",
            )),
            segment_reduction=self.segment_reduction(),
            segment_blend=self.segment_blend(),
            utilization_threshold=float(getattr(
                self.params,
                "ruplace_connection_routeforce_utilization_threshold",
                1.0,
            )),
            pressure_exponent=float(getattr(
                self.params,
                "ruplace_connection_routeforce_pressure_exponent",
                1.0,
            )),
            via_utilization_threshold=float(getattr(
                self.params,
                "ruplace_connection_routeforce_via_utilization_threshold",
                0.0,
            )),
            dilation_radius=int(getattr(
                self.params,
                "ruplace_connection_routeforce_dilation_radius",
                0,
            )),
            unit_wire_cost=float(getattr(
                self.params, "ruplace_connection_routeforce_wire_cost", 1.0
            )),
            unit_via_cost=float(getattr(
                self.params, "ruplace_connection_routeforce_via_cost", 1.0
            )),
        )
        if not torch.isfinite(grad).all():
            raise RuntimeError("connection_routeforce produced a non-finite gradient")

        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        grad_x = grad[:m] * x_scale
        grad_y = grad[n:n + m] * y_scale
        grad_x, grad_y, condition_metrics = self.condition_gradient(
            pos, context, grad_x, grad_y
        )
        if not torch.isfinite(grad_x).all() or not torch.isfinite(grad_y).all():
            raise RuntimeError(
                "%s produced a non-finite conditioned gradient" % self.name
            )
        scaling = context.add_scaled_movable_gradient(
            pos,
            grad_x,
            grad_y,
            weight,
            scale_mode=getattr(
                self.params,
                "ruplace_connection_routeforce_scale_mode",
                "relative",
            ),
            max_ratio=float(getattr(
                self.params,
                "ruplace_connection_routeforce_max_ratio",
                0.05,
            )),
        )
        changed = scaling["applied_scale"] != 0.0 and scaling["field_rms"] != 0.0
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "route_refreshed": int(refresh),
            "routeforce_x_scale": x_scale,
            "routeforce_y_scale": y_scale,
            **route_metrics,
            **schedule_metrics,
            **condition_metrics,
            **scaling,
        }
        return changed
