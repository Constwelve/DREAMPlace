"""Common contracts and tensor helpers for routability optimization plugins."""

from dataclasses import dataclass, field

import torch


@dataclass
class CongestionSignal:
    utilization_map: torch.Tensor
    overflow_map: torch.Tensor = None
    hv_overflow_map: torch.Tensor = None
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


class RoutabilityPlugin:
    """Independent placement transformation driven by a congestion signal."""

    name = "base"

    def __init__(self, params, placedb, data_collections):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.metrics = {}

    def apply_gradient(self, pos, model, context):
        return False

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

    def begin_iteration(self, iteration):
        self.iteration = iteration
        self._signal = None

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
