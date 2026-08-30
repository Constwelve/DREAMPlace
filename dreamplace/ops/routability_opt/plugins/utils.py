"""Shared numerical helpers for routability plugins."""

import torch
import torch.nn.functional as F


def map_on_placement_device(value_map, pos):
    """Move an external congestion map to the placement tensor contract."""
    return value_map.to(device=pos.device, dtype=pos.dtype)


def normalize_field(gx, gy):
    rms = vector_field_rms(gx, gy).clamp_min(1e-12)
    return gx / rms, gy / rms


def vector_field_rms(gx, gy):
    if gx.numel() == 0:
        return gx.new_zeros(())
    return torch.sqrt((gx.square() + gy.square()).mean())


def select_congestion_map(signal, mode="aggregate"):
    """Select aggregate, overflow-directional, or utilization-directional data."""
    mode = str(mode).lower()
    if mode in ("aggregate", "overflow", "combined"):
        return signal.overflow_map
    if mode in ("utilization", "aggregate_utilization"):
        return signal.utilization_map

    utilization_modes = {
        "utilization_hv_max": "max",
        "hv_utilization_max": "max",
        "utilization_hv_mean": "mean",
        "hv_utilization_mean": "mean",
        "utilization_horizontal": "horizontal",
        "horizontal_utilization": "horizontal",
        "utilization_vertical": "vertical",
        "vertical_utilization": "vertical",
    }
    directional_mode = utilization_modes.get(mode)
    hv = (
        signal.hv_utilization_map
        if directional_mode is not None else signal.hv_overflow_map
    )
    if hv is None:
        raise RuntimeError(
            "directional congestion mode %s requires %s" % (
                mode,
                "hv_utilization_map"
                if directional_mode is not None else "hv_overflow_map",
            )
        )
    if hv.dim() != 3 or hv.shape[0] < 2:
        raise RuntimeError("directional congestion map must have shape [2, bins_x, bins_y]")
    if directional_mode == "max" or mode in ("hv_max", "max"):
        return hv[:2].max(dim=0).values
    if directional_mode == "mean" or mode in ("hv_mean", "mean", "average"):
        return hv[:2].mean(dim=0)
    if directional_mode == "horizontal" or mode in ("horizontal", "h"):
        return hv[0]
    if directional_mode == "vertical" or mode in ("vertical", "v"):
        return hv[1]
    raise ValueError("unsupported routability congestion-map mode: %s" % mode)


def smooth_map(value_map, radius, padding_mode="zero"):
    radius = max(0, int(radius))
    padding_mode = str(padding_mode).lower()
    if padding_mode not in ("zero", "replicate"):
        raise ValueError("unsupported routability smoothing padding: %s" % padding_mode)
    if radius == 0:
        return value_map
    kernel = 2 * radius + 1
    if padding_mode == "replicate":
        value_map = F.pad(
            value_map[None, None], (radius, radius, radius, radius),
            mode="replicate",
        )
        return F.avg_pool2d(value_map, kernel_size=kernel, stride=1)[0, 0]
    return F.avg_pool2d(
        value_map[None, None], kernel_size=kernel, stride=1, padding=radius
    )[0, 0]


def force_map_options(params):
    return (
        str(getattr(params, "ruplace_force_congestion_mode", "aggregate")),
        str(getattr(params, "ruplace_force_smoothing_padding", "zero")),
        bool(getattr(params, "ruplace_force_physical_bins", False)),
    )


def routing_bin_sizes(placedb, shape):
    return (
        (placedb.routing_grid_xh - placedb.routing_grid_xl) / shape[0],
        (placedb.routing_grid_yh - placedb.routing_grid_yl) / shape[1],
    )


def rectangle_overlap_map(xl, yl, xh, yh, shape, bounds, dtype=None, device=None):
    """Rasterize rectangle overlap area onto a regular grid."""
    nx, ny = shape
    grid_xl, grid_yl, grid_xh, grid_yh = (float(value) for value in bounds)
    if dtype is None:
        dtype = xl.dtype
    if device is None:
        device = xl.device
    result = torch.zeros((nx, ny), dtype=dtype, device=device)
    if nx <= 0 or ny <= 0 or xl.numel() == 0:
        return result

    bin_size_x = (grid_xh - grid_xl) / nx
    bin_size_y = (grid_yh - grid_yl) / ny
    rectangles = zip(
        xl.detach().to(device=device, dtype=dtype),
        yl.detach().to(device=device, dtype=dtype),
        xh.detach().to(device=device, dtype=dtype),
        yh.detach().to(device=device, dtype=dtype),
    )
    for rect_xl, rect_yl, rect_xh, rect_yh in rectangles:
        clipped_xl = rect_xl.clamp(grid_xl, grid_xh)
        clipped_yl = rect_yl.clamp(grid_yl, grid_yh)
        clipped_xh = rect_xh.clamp(grid_xl, grid_xh)
        clipped_yh = rect_yh.clamp(grid_yl, grid_yh)
        if (clipped_xh <= clipped_xl).item() or (clipped_yh <= clipped_yl).item():
            continue
        first_x = max(0, min(nx - 1, int(torch.floor(
            (clipped_xl - grid_xl) / bin_size_x
        ).item())))
        first_y = max(0, min(ny - 1, int(torch.floor(
            (clipped_yl - grid_yl) / bin_size_y
        ).item())))
        last_x = max(first_x + 1, min(nx, int(torch.ceil(
            (clipped_xh - grid_xl) / bin_size_x
        ).item())))
        last_y = max(first_y + 1, min(ny, int(torch.ceil(
            (clipped_yh - grid_yl) / bin_size_y
        ).item())))
        bins_x = torch.arange(first_x, last_x, device=device, dtype=dtype)
        bins_y = torch.arange(first_y, last_y, device=device, dtype=dtype)
        overlap_x = (
            torch.minimum(clipped_xh, grid_xl + (bins_x + 1) * bin_size_x)
            - torch.maximum(clipped_xl, grid_xl + bins_x * bin_size_x)
        ).clamp_min(0)
        overlap_y = (
            torch.minimum(clipped_yh, grid_yl + (bins_y + 1) * bin_size_y)
            - torch.maximum(clipped_yl, grid_yl + bins_y * bin_size_y)
        ).clamp_min(0)
        result[first_x:last_x, first_y:last_y].add_(
            overlap_x[:, None] * overlap_y[None, :]
        )
    return result


def node_footprint_average(context, pos, value_map):
    """Average a grid map over each movable node's bounding box."""
    db = context.placedb
    dc = context.data_collections
    n = db.num_nodes
    m = db.num_movable_nodes
    nx, ny = value_map.shape
    sx = nx / float(db.routing_grid_xh - db.routing_grid_xl)
    sy = ny / float(db.routing_grid_yh - db.routing_grid_yl)
    x0 = ((pos[:m] - db.routing_grid_xl) * sx).floor().long().clamp(0, nx - 1)
    y0 = ((pos[n:n + m] - db.routing_grid_yl) * sy).floor().long().clamp(0, ny - 1)
    x1 = ((pos[:m] + dc.node_size_x[:m] - db.routing_grid_xl) * sx).ceil().long()
    y1 = ((pos[n:n + m] + dc.node_size_y[:m] - db.routing_grid_yl) * sy).ceil().long()
    x1.clamp_(1, nx)
    y1.clamp_(1, ny)
    x1 = torch.maximum(x1, x0 + 1)
    y1 = torch.maximum(y1, y0 + 1)
    integral = F.pad(value_map.cumsum(0).cumsum(1), (1, 0, 1, 0))
    total = integral[x1, y1] - integral[x0, y1] - integral[x1, y0] + integral[x0, y0]
    return total / ((x1 - x0) * (y1 - y0)).to(value_map.dtype)
