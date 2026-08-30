"""Xplace routeforce gradient exposed as an independent plugin."""

import torch

from dreamplace.ops.routability_opt.plugin_base import RoutabilityPlugin


class RouteForcePlugin(RoutabilityPlugin):
    name = "routeforce"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self.applications = 0

    def apply_gradient(self, pos, model, context):
        backend = getattr(context.proxy, "backend", None)
        if backend is None or not hasattr(backend, "admm_gradient"):
            raise RuntimeError("routeforce plugin requires the in-process gpugr/xplace proxy")
        if getattr(backend, "external_route_eval", False):
            return False
        freq = max(1, int(getattr(self.params, "ruplace_admm_apply_freq", 1)))
        if context.iteration % freq:
            return False
        route_freq = max(1, int(self.params.ruplace_admm_route_freq))
        refresh = (
            getattr(backend, "last_route", None) is None
            or context.iteration % route_freq == 0
        )
        grad = backend.admm_gradient(pos, refresh=refresh)
        if not torch.isfinite(grad).all():
            raise RuntimeError("routeforce produced a non-finite gradient")
        # The backend returns an objective gradient, not a displacement vector.
        # Keep Xplace's positive gradient convention; the optimizer subtracts it.
        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        grad_x = grad[:m]
        grad_y = grad[n:n + m]
        clip = float(getattr(self.params, "ruplace_admm_grad_clip_norm", 0.0))
        norm = torch.linalg.vector_norm(torch.cat((grad_x, grad_y)))
        if clip > 0 and torch.isfinite(norm) and norm.item() > clip:
            scale = clip / norm.clamp_min(1e-12)
            grad_x = grad_x * scale
            grad_y = grad_y * scale
        weight = float(self.params.ruplace_admm_weight) * (
            float(getattr(self.params, "ruplace_admm_weight_decay", 1.0)) ** self.applications
        )
        weight = max(weight, float(getattr(self.params, "ruplace_admm_min_weight", 0.0)))
        scaling = context.add_scaled_movable_gradient(
            pos,
            grad_x,
            grad_y,
            weight,
            scale_mode=getattr(self.params, "ruplace_admm_scale_mode", "absolute"),
            max_ratio=float(getattr(self.params, "ruplace_admm_max_ratio", 0.25)),
        )
        changed = scaling["applied_scale"] != 0.0 and scaling["field_rms"] != 0.0
        if changed:
            self.applications += 1
        self.metrics = {
            "applications": self.applications,
            "gradient_norm": float(norm.item()),
            **scaling,
        }
        return changed
