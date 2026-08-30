"""Common contracts and tensor helpers for routability optimization plugins."""

from dataclasses import dataclass, field
import math

import torch


def restore_original_node_geometry(pos, placedb, data_collections):
    """Restore inflated geometry without perturbing an unchanged placement."""
    size_changed = (
        not torch.equal(
            data_collections.node_size_x,
            data_collections.original_node_size_x,
        )
        or not torch.equal(
            data_collections.node_size_y,
            data_collections.original_node_size_y,
        )
    )
    pin_changed = (
        not torch.equal(
            data_collections.pin_offset_x,
            data_collections.original_pin_offset_x,
        )
        or not torch.equal(
            data_collections.pin_offset_y,
            data_collections.original_pin_offset_y,
        )
    )
    if not size_changed and not pin_changed:
        return False

    with torch.no_grad():
        if size_changed:
            movable = placedb.num_movable_nodes
            num_nodes = placedb.num_nodes
            pos[:movable].add_(data_collections.node_size_x[:movable] * 0.5)
            pos[num_nodes:num_nodes + movable].add_(
                data_collections.node_size_y[:movable] * 0.5
            )
            data_collections.node_size_x.copy_(
                data_collections.original_node_size_x
            )
            data_collections.node_size_y.copy_(
                data_collections.original_node_size_y
            )
            pos[:movable].sub_(data_collections.node_size_x[:movable] * 0.5)
            pos[num_nodes:num_nodes + movable].sub_(
                data_collections.node_size_y[:movable] * 0.5
            )
        if pin_changed:
            data_collections.pin_offset_x.copy_(
                data_collections.original_pin_offset_x
            )
            data_collections.pin_offset_y.copy_(
                data_collections.original_pin_offset_y
            )
    return True


@dataclass
class CongestionSignal:
    utilization_map: torch.Tensor
    overflow_map: torch.Tensor = None
    hv_overflow_map: torch.Tensor = None
    hv_utilization_map: torch.Tensor = None
    pin_utilization_map: torch.Tensor = None
    metrics: dict = field(default_factory=dict)
    source: str = "unknown"
    native: object = None

    def __post_init__(self):
        self.utilization_map = torch.nan_to_num(
            self.utilization_map, nan=0.0, posinf=0.0, neginf=0.0
        )
        if self.overflow_map is None:
            self.overflow_map = (self.utilization_map - 1.0).clamp_min(0.0)
        else:
            self.overflow_map = torch.nan_to_num(
                self.overflow_map, nan=0.0, posinf=0.0, neginf=0.0
            ).clamp_min(0.0)
        if self.hv_overflow_map is not None:
            self.hv_overflow_map = torch.nan_to_num(
                self.hv_overflow_map, nan=0.0, posinf=0.0, neginf=0.0
            ).clamp_min(0.0)
        if self.hv_utilization_map is not None:
            self.hv_utilization_map = torch.nan_to_num(
                self.hv_utilization_map, nan=0.0, posinf=0.0, neginf=0.0
            ).clamp_min(0.0)


class RoutabilityPlugin:
    """Independent placement transformation driven by a congestion signal."""

    name = "base"

    def __init__(self, params, placedb, data_collections):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.metrics = {}
        self.force_applications = 0
        self._congestion_gate_history = []
        self._congestion_gate_observation = None
        self._tail_guard_reference = None
        self._tail_guard_observation = None
        self._tail_guard_passed = True

    def apply_gradient(self, pos, model, context):
        return False

    def commit_post_gradient(self, pos, model, context):
        """Commit state queued while constructing the current gradient."""
        return False

    def prepare_objective(self, pos, model, context):
        """Update objective inputs before the objective graph is constructed."""
        return False

    def objective_phase_enabled(self):
        return type(self).prepare_objective is not RoutabilityPlugin.prepare_objective

    def gradient_phase_enabled(self):
        return type(self).apply_gradient is not RoutabilityPlugin.apply_gradient

    def scheduled_force_weight(self, context, weight, parameter_name=None):
        """Return an annealed force weight, or None on unscheduled iterations."""
        prefix = "ruplace_%s_" % (parameter_name or self.name)
        interval = max(1, int(getattr(
            self.params, prefix + "apply_interval",
            getattr(self.params, "ruplace_force_apply_interval", 1),
        )))
        offset = int(getattr(
            self.params, prefix + "apply_offset",
            getattr(self.params, "ruplace_force_apply_offset", 0),
        ))
        max_applications = int(getattr(
            self.params, prefix + "max_applications",
            getattr(self.params, "ruplace_force_max_applications", -1),
        ))
        decay = float(getattr(
            self.params, prefix + "decay",
            getattr(self.params, "ruplace_force_decay", 1.0),
        ))
        min_ratio = float(getattr(
            self.params, prefix + "min_ratio",
            getattr(self.params, "ruplace_force_min_ratio", 0.0),
        ))
        if decay < 0.0 or decay > 1.0:
            raise ValueError("routability force decay must be in [0, 1]")
        if min_ratio < 0.0 or min_ratio > 1.0:
            raise ValueError("routability force minimum ratio must be in [0, 1]")
        if offset < 0 or offset >= interval:
            raise ValueError(
                "routability force application offset must be in [0, interval)"
            )
        if max_applications < -1:
            raise ValueError(
                "routability force maximum applications must be -1 or nonnegative"
            )
        phase_hit = context.iteration % interval == offset
        budget_exhausted = (
            max_applications >= 0
            and self.force_applications >= max_applications
        )
        scheduled = phase_hit and not budget_exhausted
        multiplier = max(decay ** self.force_applications, min_ratio)
        metrics = {
            "force_schedule_applied": int(scheduled),
            "force_schedule_phase_hit": int(phase_hit),
            "force_scheduled_iteration": (
                int(context.iteration) if scheduled else 0
            ),
            "force_apply_interval": interval,
            "force_apply_offset": offset,
            "force_max_applications": max_applications,
            "force_application_budget_exhausted": int(budget_exhausted),
            "force_iteration": int(context.iteration),
            "force_weight_multiplier": multiplier,
            "force_applications": self.force_applications,
        }
        return (float(weight) * multiplier if scheduled else None), metrics

    def record_force_application(self):
        self.force_applications += 1

    def congestion_stagnation_gate(self, context, congestion_map,
                                   utilization_map=False,
                                   parameter_name=None):
        """Gate a force on persistent, non-improving proxy congestion."""
        prefix = "ruplace_%s_" % (parameter_name or self.name)

        def parameter(suffix, default):
            return getattr(
                self.params,
                prefix + suffix,
                getattr(self.params, "ruplace_force_" + suffix, default),
            )

        window = int(parameter("stagnation_window", 1))
        tolerance = float(parameter("stagnation_tolerance", 0.0))
        min_sum = float(parameter("min_overflow_sum", 0.0))
        min_bins = int(parameter("min_overflow_bins", 0))
        utilization_threshold = float(parameter(
            "gate_utilization_threshold", 1.0
        ))
        if window < 1:
            raise ValueError("routability force stagnation window must be positive")
        if not math.isfinite(tolerance) or not 0.0 <= tolerance <= 1.0:
            raise ValueError(
                "routability force stagnation tolerance must be in [0, 1]"
            )
        if not math.isfinite(min_sum) or min_sum < 0.0:
            raise ValueError(
                "routability force minimum overflow sum must be finite and nonnegative"
            )
        if min_bins < 0:
            raise ValueError(
                "routability force minimum overflow bins must be nonnegative"
            )
        if (not math.isfinite(utilization_threshold)
                or utilization_threshold < 0.0):
            raise ValueError(
                "routability force gate utilization threshold must be finite "
                "and nonnegative"
            )

        pressure = torch.nan_to_num(
            congestion_map, nan=0.0, posinf=0.0, neginf=0.0
        )
        if utilization_map:
            pressure = (pressure - utilization_threshold).clamp_min(0.0)
        else:
            pressure = pressure.clamp_min(0.0)
        overflow_sum = float(pressure.sum().item())
        overflow_peak = float(pressure.max().item()) if pressure.numel() else 0.0
        overflow_bins = int((pressure > 0.0).sum().item())

        enabled = window > 1 or min_sum > 0.0 or min_bins > 0
        proxy = getattr(context, "proxy", None)
        observation = getattr(proxy, "last_iteration", context.iteration)
        fresh = observation != self._congestion_gate_observation
        if enabled and fresh:
            self._congestion_gate_observation = observation
            self._congestion_gate_history.append(overflow_sum)
            self._congestion_gate_history = self._congestion_gate_history[-window:]

        enough_history = len(self._congestion_gate_history) >= window
        nonimproving = window == 1
        if window > 1 and enough_history:
            nonimproving = all(
                current >= previous * (1.0 - tolerance)
                for previous, current in zip(
                    self._congestion_gate_history,
                    self._congestion_gate_history[1:],
                )
            )
        severity = (
            overflow_peak > 0.0
            and overflow_sum >= min_sum
            and overflow_bins >= min_bins
        )
        passed = True if not enabled else severity and nonimproving
        return passed, {
            "congestion_gate_enabled": int(enabled),
            "congestion_gate_passed": int(passed),
            "congestion_gate_fresh_observation": int(fresh),
            "congestion_gate_observations": len(self._congestion_gate_history),
            "congestion_gate_window": window,
            "congestion_gate_stagnation_tolerance": tolerance,
            "congestion_gate_min_overflow_sum": min_sum,
            "congestion_gate_min_overflow_bins": min_bins,
            "congestion_gate_utilization_threshold": utilization_threshold,
            "congestion_gate_overflow_sum": overflow_sum,
            "congestion_gate_overflow_peak": overflow_peak,
            "congestion_gate_overflow_bins": overflow_bins,
            "congestion_gate_enough_history": int(enough_history),
            "congestion_gate_nonimproving": int(nonimproving),
        }

    def congestion_tail_gate(self, context, signal, parameter_name=None):
        """Block forces that worsen the best observed directional tail."""
        prefix = "ruplace_%s_" % (parameter_name or self.name)

        def parameter(suffix, default):
            return getattr(
                self.params,
                prefix + suffix,
                getattr(self.params, "ruplace_force_" + suffix, default),
            )

        enabled = bool(int(parameter("tail_guard", 0)))
        mode = str(parameter("tail_metric", "max_p99")).lower()
        tolerance = float(parameter("tail_tolerance", 0.0))
        if mode not in ("max", "p99", "max_p99"):
            raise ValueError("unsupported routability tail metric: %s" % mode)
        if not math.isfinite(tolerance) or tolerance < 0.0:
            raise ValueError(
                "routability tail tolerance must be finite and nonnegative"
            )

        metrics = {
            "tail_guard_enabled": int(enabled),
            "tail_guard_metric_id": {
                "max": 0,
                "p99": 1,
                "max_p99": 2,
            }[mode],
            "tail_guard_tolerance": tolerance,
            "tail_guard_fresh_observation": 0,
            "tail_guard_initialized": int(
                self._tail_guard_reference is not None
            ),
            "tail_guard_passed": 1,
        }
        if not enabled:
            return True, metrics

        hv = signal.hv_utilization_map
        if hv is None:
            raise ValueError(
                "routability tail guard requires H/V utilization feedback"
            )
        if hv.ndim != 3 or hv.shape[0] < 2:
            raise ValueError(
                "H/V utilization feedback must have shape [2, bins_x, bins_y]"
            )
        hv = torch.nan_to_num(
            hv[:2], nan=0.0, posinf=0.0, neginf=0.0
        ).clamp_min(0.0)
        flat = hv.reshape(2, -1)
        maxima = flat.max(dim=1).values
        p99 = torch.quantile(flat, 0.99, dim=1)
        values = torch.cat((maxima, p99)).detach()
        selected = {
            "max": (0, 1),
            "p99": (2, 3),
            "max_p99": (0, 1, 2, 3),
        }[mode]

        proxy = getattr(context, "proxy", None)
        observation = getattr(proxy, "last_iteration", context.iteration)
        fresh = observation != self._tail_guard_observation
        if fresh:
            self._tail_guard_observation = observation
            if self._tail_guard_reference is None:
                self._tail_guard_reference = values.clone()
                self._tail_guard_passed = True
            else:
                reference = self._tail_guard_reference
                self._tail_guard_passed = all(
                    float(values[index])
                    <= float(reference[index]) * (1.0 + tolerance)
                    for index in selected
                )
                if self._tail_guard_passed:
                    self._tail_guard_reference = torch.minimum(
                        reference, values
                    )

        decision = self._tail_guard_passed and fresh
        reference = self._tail_guard_reference
        labels = (
            "horizontal_max", "vertical_max",
            "horizontal_p99", "vertical_p99",
        )
        metrics.update({
            "tail_guard_fresh_observation": int(fresh),
            "tail_guard_initialized": 1,
            "tail_guard_passed": int(decision),
        })
        for index, label in enumerate(labels):
            metrics["tail_guard_%s" % label] = float(values[index])
            metrics["tail_guard_reference_%s" % label] = float(
                reference[index]
            )
        return decision, metrics

    def maybe_adjust_area(self, pos, model, context):
        return False


class PluginContext:
    def __init__(self, params, placedb, data_collections, op_collections, proxy):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.op_collections = op_collections
        self.proxy = proxy
        self.iteration = 0
        self._signal = None
        self._reference_gradient = None

    def begin_iteration(self, iteration):
        self.iteration = iteration
        self._signal = None
        self._reference_gradient = None

    def begin_gradient(self, pos):
        self._reference_gradient = (
            None if pos.grad is None else pos.grad.detach().clone()
        )

    def reference_movable_gradient(self):
        """Return the placement gradient captured before plugins modify it."""
        if self._reference_gradient is None:
            return None
        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        return (
            self._reference_gradient[:m],
            self._reference_gradient[n:n + m],
        )

    def signal(self, pos, refresh=False):
        if self._signal is None or refresh:
            self._signal = self.proxy.evaluate(pos, self.iteration, refresh=refresh)
        return self._signal

    def pin_positions(self, pos):
        return self.op_collections.pin_pos_op(pos)

    def movable_centers(self, pos):
        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        x = pos[:m] + self.data_collections.node_size_x[:m] * 0.5
        y = pos[n:n + m] + self.data_collections.node_size_y[:m] * 0.5
        return x, y

    def sample_map(self, pos, value_map):
        value_map = value_map.to(device=pos.device, dtype=pos.dtype)
        bins_x, bins_y = value_map.shape[-2:]
        x, y = self.movable_centers(pos)
        bx = ((x - self.placedb.routing_grid_xl) * bins_x /
              (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl)).long()
        by = ((y - self.placedb.routing_grid_yl) * bins_y /
              (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl)).long()
        bx.clamp_(0, bins_x - 1)
        by.clamp_(0, bins_y - 1)
        return value_map[bx, by]

    def sample_vector_field(self, pos, field_x, field_y):
        return self.sample_map(pos, field_x), self.sample_map(pos, field_y)

    def add_movable_gradient(self, pos, grad_x, grad_y, weight=1.0):
        if pos.grad is None:
            pos.grad = torch.zeros_like(pos)
        n = self.placedb.num_nodes
        m = self.placedb.num_movable_nodes
        pos.grad[:m].add_(grad_x, alpha=float(weight))
        pos.grad[n:n + m].add_(grad_y, alpha=float(weight))

    def add_scaled_movable_gradient(self, pos, grad_x, grad_y, weight,
                                    scale_mode=None, max_ratio=None):
        """Add a force using legacy absolute or objective-relative scaling."""
        from dreamplace.ops.routability_opt.plugins.utils import vector_field_rms

        mode = str(
            scale_mode if scale_mode is not None else getattr(
                self.params, "ruplace_force_scale_mode", "absolute"
            )
        ).lower()
        ratio_limit = float(
            max_ratio if max_ratio is not None else getattr(
                self.params, "ruplace_force_max_ratio", 0.25
            )
        )
        field_rms = vector_field_rms(grad_x, grad_y)
        reference_rms = torch.zeros((), dtype=pos.dtype, device=pos.device)
        if self._reference_gradient is not None:
            n = self.placedb.num_nodes
            m = self.placedb.num_movable_nodes
            reference_rms = vector_field_rms(
                self._reference_gradient[:m],
                self._reference_gradient[n:n + m],
            )

        if mode == "absolute":
            scale = float(weight)
        elif mode in ("relative", "gradient_relative"):
            if weight < 0.0:
                raise ValueError("relative routability force weight must be nonnegative")
            if ratio_limit <= 0.0:
                raise ValueError("routability force max ratio must be positive")
            target_ratio = min(float(weight), ratio_limit)
            if field_rms.item() == 0.0 or reference_rms.item() == 0.0:
                scale = 0.0
            else:
                scale = target_ratio * float(reference_rms / field_rms)
        else:
            raise ValueError(
                "unsupported ruplace_force_scale_mode: %s" % mode
            )

        if scale != 0.0 and field_rms.item() != 0.0:
            self.add_movable_gradient(pos, grad_x, grad_y, scale)
        applied_rms = abs(scale) * float(field_rms.item())
        reference_value = float(reference_rms.item())
        return {
            "reference_rms": reference_value,
            "field_rms": float(field_rms.item()),
            "applied_scale": float(scale),
            "applied_ratio": (
                applied_rms / reference_value if reference_value > 0.0 else 0.0
            ),
        }


def normalized_overflow(value_map, threshold=1.0):
    value_map = torch.nan_to_num(value_map, nan=0.0, posinf=0.0, neginf=0.0)
    return (value_map - float(threshold)).clamp_min(0.0)


def map_gradient(value_map, bin_size_x=1.0, bin_size_y=1.0):
    """Central-difference gradient with one-sided boundary differences."""
    value_map = torch.nan_to_num(value_map, nan=0.0, posinf=0.0, neginf=0.0)
    gx = torch.zeros_like(value_map)
    gy = torch.zeros_like(value_map)
    if value_map.shape[0] > 1:
        gx[1:-1] = (value_map[2:] - value_map[:-2]) / (2.0 * bin_size_x)
        gx[0] = (value_map[1] - value_map[0]) / bin_size_x
        gx[-1] = (value_map[-1] - value_map[-2]) / bin_size_x
    if value_map.shape[1] > 1:
        gy[:, 1:-1] = (value_map[:, 2:] - value_map[:, :-2]) / (2.0 * bin_size_y)
        gy[:, 0] = (value_map[:, 1] - value_map[:, 0]) / bin_size_y
        gy[:, -1] = (value_map[:, -1] - value_map[:, -2]) / bin_size_y
    return gx, gy


def poisson_potential(charge):
    """Solve -Laplacian(phi)=charge on a periodic grid with zero DC term."""
    charge = torch.nan_to_num(charge, nan=0.0, posinf=0.0, neginf=0.0)
    charge = charge - charge.mean()
    nx, ny = charge.shape
    spectrum = torch.fft.rfft2(charge)
    kx = 2.0 * torch.pi * torch.fft.fftfreq(nx, device=charge.device, dtype=charge.dtype)
    ky = 2.0 * torch.pi * torch.fft.rfftfreq(ny, device=charge.device, dtype=charge.dtype)
    denom = 4.0 * torch.sin(kx[:, None] * 0.5).square()
    denom = denom + 4.0 * torch.sin(ky[None, :] * 0.5).square()
    denom[0, 0] = 1.0
    spectrum = spectrum / denom
    spectrum[0, 0] = 0.0
    return torch.fft.irfft2(spectrum, s=(nx, ny))


def poisson_field_neumann(charge, bin_size_x=1.0, bin_size_y=1.0,
                          operators=None):
    """Solve zero-flux Poisson potential and return its spatial gradient."""
    charge = torch.nan_to_num(charge, nan=0.0, posinf=0.0, neginf=0.0)
    charge = charge - charge.mean()
    nx, ny = charge.shape
    bin_size_x = float(bin_size_x)
    bin_size_y = float(bin_size_y)
    if bin_size_x <= 0.0 or bin_size_y <= 0.0:
        raise ValueError("Poisson field bin sizes must be positive")

    if operators is None:
        import dreamplace.ops.dct.dct2_fft2 as dct
        operators = (
            dct.DCT2(), dct.IDCT2(), dct.IDXST_IDCT(), dct.IDCT_IDXST()
        )
    dct2, idct2, idxst_idct, idct_idxst = operators

    coefficients = dct2(charge)
    wx = torch.arange(
        nx, dtype=charge.dtype, device=charge.device
    ).mul(2.0 * torch.pi / (nx * bin_size_x)).reshape(nx, 1)
    wy = torch.arange(
        ny, dtype=charge.dtype, device=charge.device
    ).mul(2.0 * torch.pi / (ny * bin_size_y)).reshape(1, ny)
    denominator = wx.square() + wy.square()
    denominator[0, 0] = 1.0
    inverse = denominator.reciprocal()
    inverse[0, 0] = 0.0

    potential = idct2(coefficients * inverse)
    # DREAMPlace's mixed inverse transforms return the electric field
    # E=-grad(phi). Gradient plugins are added to the placement objective and
    # therefore need grad(phi), matching map_gradient(poisson_potential(...)).
    gradient_x = -idxst_idct(coefficients * wx * inverse * 0.5)
    gradient_y = -idct_idxst(coefficients * wy * inverse * 0.5)
    return potential, gradient_x, gradient_y
