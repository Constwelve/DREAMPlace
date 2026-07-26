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
        refresh = self.applications % max(1, int(self.params.ruplace_admm_route_freq)) == 0
        grad = backend.admm_gradient(pos, refresh=refresh)
        if not torch.isfinite(grad).all():
            raise RuntimeError("routeforce produced a non-finite gradient")
        clip = float(getattr(self.params, "ruplace_admm_grad_clip_norm", 0.0))
        norm = grad.norm()
        if clip > 0 and torch.isfinite(norm) and norm.item() > clip:
            grad = grad * (clip / norm.clamp_min(1e-12))
        weight = float(self.params.ruplace_admm_weight) * (
            float(getattr(self.params, "ruplace_admm_weight_decay", 1.0)) ** self.applications
        )
        weight = max(weight, float(getattr(self.params, "ruplace_admm_min_weight", 0.0)))
        changed = weight != 0.0 and bool(norm > 0)
        if changed:
            if pos.grad is None:
                pos.grad = torch.zeros_like(pos)
            pos.grad.add_(grad, alpha=weight)
        self.applications += 1
        self.metrics = {"applications": self.applications, "gradient_norm": float(norm.item())}
        return changed
