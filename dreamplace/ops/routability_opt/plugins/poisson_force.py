"""Global Poisson/Coulomb congestion-force objective."""

import math

import torch

from dreamplace.ops.routability_opt.plugin_base import (
    RoutabilityPlugin,
    map_gradient,
    poisson_field_neumann,
    poisson_potential,
)
from dreamplace.ops.routability_opt.plugins.utils import (
    force_map_options,
    map_on_placement_device,
    normalize_field,
    routing_bin_sizes,
    select_congestion_map,
    smooth_map,
)


class PoissonCongestionForcePlugin(RoutabilityPlugin):
    name = "poisson_force"

    def __init__(self, params, placedb, data_collections):
        super().__init__(params, placedb, data_collections)
        self._dct_operators = {}

    def _neumann_operators(self, charge):
        key = (tuple(charge.shape), charge.device, charge.dtype)
        operators = self._dct_operators.get(key)
        if operators is None:
            import dreamplace.ops.dct.dct2_fft2 as dct
            operators = (
                dct.DCT2(), dct.IDCT2(), dct.IDXST_IDCT(), dct.IDCT_IDXST()
            )
            self._dct_operators[key] = operators
        return operators

    def _solve(self, charge, bin_size_x, bin_size_y, solver):
        if solver == "periodic":
            potential = poisson_potential(charge)
            gradient_x, gradient_y = map_gradient(
                potential, bin_size_x, bin_size_y
            )
            return potential, gradient_x, gradient_y, solver
        if solver in ("neumann", "neumann_dct", "dct"):
            potential, gradient_x, gradient_y = poisson_field_neumann(
                charge,
                bin_size_x,
                bin_size_y,
                self._neumann_operators(charge),
            )
            return potential, gradient_x, gradient_y, "neumann_dct"
        raise ValueError("unsupported ruplace_poisson_solver: %s" % solver)

    def apply_gradient(self, pos, model, context):
        weight = float(getattr(self.params, "ruplace_poisson_weight", 0.05))
        weight, schedule_metrics = self.scheduled_force_weight(context, weight)
        if weight is None:
            self.metrics = schedule_metrics
            return False
        signal = context.signal(pos)
        radius = int(getattr(self.params, "ruplace_poisson_smooth", 1))
        map_mode, padding_mode, _ = force_map_options(self.params)
        solver = str(getattr(
            self.params, "ruplace_poisson_solver", "periodic"
        )).lower()
        directional_mode = str(getattr(
            self.params, "ruplace_poisson_directional_mode", "scalar"
        )).lower()
        if directional_mode not in ("scalar", "cross_track"):
            raise ValueError(
                "unsupported ruplace_poisson_directional_mode: %s"
                % directional_mode
            )
        axis_balance = float(getattr(
            self.params, "ruplace_poisson_axis_balance", 1.0
        ))
        if not math.isfinite(axis_balance) or axis_balance <= 0.0:
            raise ValueError("ruplace_poisson_axis_balance must be positive")

        directional_metrics = {
            "poisson_directional_cross_track": int(
                directional_mode == "cross_track"
            ),
            "poisson_axis_balance": axis_balance,
        }
        if directional_mode == "scalar":
            charge = smooth_map(
                select_congestion_map(signal, map_mode), radius, padding_mode
            )
            bx, by = routing_bin_sizes(self.placedb, charge.shape)
            potential, gx, gy, solver = self._solve(charge, bx, by, solver)
            potential_rms = potential.square().mean().sqrt()
        else:
            hv_utilization = signal.hv_utilization_map
            if hv_utilization is None:
                raise ValueError(
                    "cross-track Poisson feedback requires H/V utilization"
                )
            hv_utilization = map_on_placement_device(hv_utilization, pos)
            if hv_utilization.ndim != 3 or hv_utilization.shape[0] != 2:
                raise ValueError("H/V utilization must have shape [2, bins_x, bins_y]")
            horizontal_charge = smooth_map(
                hv_utilization[0], radius, padding_mode
            )
            vertical_charge = smooth_map(
                hv_utilization[1], radius, padding_mode
            )
            bx, by = routing_bin_sizes(self.placedb, horizontal_charge.shape)
            horizontal_potential, _, horizontal_gy, solver = self._solve(
                horizontal_charge, bx, by, solver
            )
            vertical_potential, vertical_gx, _, solver = self._solve(
                vertical_charge, bx, by, solver
            )
            gx = vertical_gx
            gy = horizontal_gy
            potential_rms = torch.sqrt(0.5 * (
                horizontal_potential.square().mean()
                + vertical_potential.square().mean()
            ))
            directional_metrics = {
                "poisson_directional_cross_track": 1,
                "poisson_axis_balance": axis_balance,
                "horizontal_potential_rms": float(
                    horizontal_potential.square().mean().sqrt().item()
                ),
                "vertical_potential_rms": float(
                    vertical_potential.square().mean().sqrt().item()
                ),
            }
        axis_scale = math.sqrt(axis_balance)
        gx = gx * axis_scale
        gy = gy / axis_scale
        gx, gy = normalize_field(gx, gy)
        node_gx, node_gy = context.sample_vector_field(pos, gx, gy)
        force_metrics = context.add_scaled_movable_gradient(
            pos, node_gx, node_gy, weight
        )
        changed = (
            force_metrics["applied_scale"] != 0.0 and bool(potential_rms > 0)
        )
        if changed:
            self.record_force_application()
        schedule_metrics["force_applications"] = self.force_applications
        self.metrics = {
            "potential_rms": float(potential_rms.item()),
            "poisson_solver_neumann_dct": int(solver == "neumann_dct"),
            **directional_metrics,
            **schedule_metrics,
            **force_metrics,
        }
        return changed
