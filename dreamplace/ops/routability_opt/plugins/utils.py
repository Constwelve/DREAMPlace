"""Shared numerical helpers for routability plugins."""

import torch
import torch.nn.functional as F


def normalize_field(gx, gy):
    rms = torch.sqrt((gx.square() + gy.square()).mean()).clamp_min(1e-12)
    return gx / rms, gy / rms


def smooth_map(value_map, radius):
    radius = max(0, int(radius))
    if radius == 0:
        return value_map
    kernel = 2 * radius + 1
    return F.avg_pool2d(
        value_map[None, None], kernel_size=kernel, stride=1, padding=radius
    )[0, 0]


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
