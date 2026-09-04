##
# @file   congestion_blockage.py
# @brief  Congestion-driven soft blockage for the electrostatic density term.
#
# RUPlace's legacy answer to routing congestion is cell inflation: grow the
# cells that sit in congested bins so the density force spreads them.  That is
# an indirect and expensive lever -- on SMIC14 regression_s14 it bloats 55% of
# the movable area for +24% routed WL and still leaves 6.1/3.1% NR-eGR
# overflow, while Innovus place_design reaches 0.30/0.59% at +15.7% by simply
# spreading cells into open area.
#
# The analogue of "spread into open area" inside DREAMPlace is to *reduce the
# capacity of congested bins*.  The electrostatic density term already has a
# per-bin capacity notion: a bin can hold ``target_density * bin_area`` of cell
# area, and fixed cells eat into that through ``initial_density_map``.  So a
# soft blockage is nothing more than extra fixed density injected into
# congested bins; the existing density gradient then pushes movable cells out
# of them with no cell resizing at all.
#
# Everything in this module is pure torch (no compiled extension), so it can be
# unit tested from the source tree.
#

import torch


def resample_router_map(
    util_map,
    routing_xl,
    routing_yl,
    routing_xh,
    routing_yh,
    num_bins_x,
    num_bins_y,
    xl,
    yl,
    xh,
    yh,
    mode="bilinear",
):
    """Resample a router-grid map onto the density-bin grid.

    @param util_map [RX, RY] tensor on the *router* grid (x-major), covering
           the routing grid extents ``routing_x/y l/h``.
    @param num_bins_x, num_bins_y density grid dimensions covering the
           *placement region* ``x/y l/h``.  The two grids generally have both
           different resolutions and different extents.
    @return [num_bins_x, num_bins_y] tensor.

    Sampling is at density-bin centers, with border clamping outside the
    routing grid extents (density bins outside the routing grid take the value
    of the nearest router bin).
    """
    if util_map.dim() != 2:
        raise ValueError("util_map must be 2D [RX, RY], got %s" % (tuple(util_map.shape),))
    rx, ry = util_map.shape
    device = util_map.device
    dtype = util_map.dtype

    route_w = float(routing_xh) - float(routing_xl)
    route_h = float(routing_yh) - float(routing_yl)
    if not (route_w > 0.0 and route_h > 0.0):
        raise ValueError("degenerate routing grid extents")

    bin_size_x = (float(xh) - float(xl)) / num_bins_x
    bin_size_y = (float(yh) - float(yl)) / num_bins_y

    # density-bin centers in placement coordinates
    cx = float(xl) + (torch.arange(num_bins_x, device=device, dtype=dtype) + 0.5) * bin_size_x
    cy = float(yl) + (torch.arange(num_bins_y, device=device, dtype=dtype) + 0.5) * bin_size_y

    # continuous index into the router grid (bin-center convention)
    gx = (cx - float(routing_xl)) / route_w * rx - 0.5
    gy = (cy - float(routing_yl)) / route_h * ry - 0.5

    if mode == "nearest":
        ix = gx.round().long().clamp_(0, rx - 1)
        iy = gy.round().long().clamp_(0, ry - 1)
        return util_map[ix[:, None], iy[None, :]].contiguous()

    x0f = torch.floor(gx)
    y0f = torch.floor(gy)
    wx = (gx - x0f).clamp_(0.0, 1.0)
    wy = (gy - y0f).clamp_(0.0, 1.0)
    x0 = x0f.long().clamp(0, rx - 1)
    x1 = (x0f.long() + 1).clamp(0, rx - 1)
    y0 = y0f.long().clamp(0, ry - 1)
    y1 = (y0f.long() + 1).clamp(0, ry - 1)

    # border clamping: where the sample falls outside the grid both taps
    # collapse onto the same edge bin, so the blend degenerates to that value.
    v00 = util_map[x0[:, None], y0[None, :]]
    v01 = util_map[x0[:, None], y1[None, :]]
    v10 = util_map[x1[:, None], y0[None, :]]
    v11 = util_map[x1[:, None], y1[None, :]]

    wx_c = (1.0 - wx)[:, None]
    wx_n = wx[:, None]
    wy_c = (1.0 - wy)[None, :]
    wy_n = wy[None, :]

    out = v00 * (wx_c * wy_c) + v01 * (wx_c * wy_n) + v10 * (wx_n * wy_c) + v11 * (wx_n * wy_n)
    return out.contiguous()


def directional_utilization(hv_utilization_map, utilization_map=None, mode="max"):
    """Collapse a [2, X, Y] H/V *utilization* map to a single [X, Y] score.

    Utilization is capacity-normalized (1.0 == at capacity), which is what the
    threshold below expects.  ``hv_overflow_map`` is deliberately *not*
    accepted here: it is ``(util - 1).clamp_min(0)`` and lives on a different
    scale.
    """
    if hv_utilization_map is None:
        if utilization_map is None:
            return None
        return utilization_map
    hv = hv_utilization_map
    if hv.dim() == 3 and hv.shape[0] >= 2:
        mode = str(mode).lower()
        if mode in ("mean", "avg", "average"):
            return hv[:2].mean(dim=0)
        if mode in ("h", "hor", "horizontal"):
            return hv[0]
        if mode in ("v", "ver", "vertical"):
            return hv[1]
        return hv[:2].max(dim=0).values
    if hv.dim() == 2:
        return hv
    if utilization_map is not None:
        return utilization_map
    return None


def _blur_axis(map2d, radius, dim):
    """Box average along one axis with edge replication."""
    n = map2d.shape[dim]
    acc = torch.zeros_like(map2d)
    base = torch.arange(n, device=map2d.device)
    for off in range(-radius, radius + 1):
        idx = (base + off).clamp_(0, n - 1)
        acc += map2d.index_select(dim, idx)
    return acc / float(2 * radius + 1)


def box_blur(map2d, radius):
    """Separable box blur with edge replication, radius in density bins."""
    radius = int(radius)
    if radius <= 0:
        return map2d
    out = _blur_axis(map2d, radius, 0)
    out = _blur_axis(out, radius, 1)
    return out.contiguous()


def compute_blockage_map(
    util_bins,
    blockage,
    threshold,
    blockage_max,
    smooth=0,
):
    """Congestion -> per-bin capacity reduction, in units of bin-area fraction.

    ``extra_b = blockage * clamp((util_b - threshold) / (1 - threshold), 0, 1)``
    then clamped to ``blockage_max`` and box-blurred.  The blur is applied
    *after* threshold+cap so that the cap stays meaningful (a blur can only
    lower the peak) and so isolated hot bins bleed into their neighbours.
    """
    blockage = float(blockage)
    if blockage <= 0.0:
        return None
    threshold = float(threshold)
    denom = max(1.0 - threshold, 1e-6)
    extra = ((util_bins - threshold) / denom).clamp_(0.0, 1.0).mul_(blockage)
    cap = float(blockage_max)
    if cap > 0.0:
        extra.clamp_(max=cap)
    extra = box_blur(extra, smooth)
    return extra


def blend_decay(previous, current, decay):
    """``new = max(decay * previous, current)``.

    Multiplicative decay on the standing map means a bin that has become clean
    fades over successive refreshes instead of latching, while the max keeps
    the result inside the cap (both operands already are).
    """
    if previous is None:
        return current
    if current is None:
        return previous * float(decay)
    return torch.maximum(previous * float(decay), current)


def cap_by_fixed_headroom(extra, fixed_density_map, capacity_per_bin, blockage_max):
    """Limit ``extra`` so ``fixed_fraction + extra <= blockage_max`` per bin.

    @param extra [X, Y] requested capacity reduction, bin-area fraction.
    @param fixed_density_map [X, Y] fixed-cell density in *area* units, already
           scaled by target_density (i.e. DREAMPlace's ``initial_density_map``
           before any blockage).  May be None.
    @param capacity_per_bin ``target_density * bin_area`` (float or 0-d/1-elem
           tensor).
    """
    if extra is None:
        return None
    cap = float(blockage_max)
    if cap > 0.0:
        extra = extra.clamp(max=cap)
    if fixed_density_map is None:
        return extra
    if torch.is_tensor(capacity_per_bin):
        capacity = capacity_per_bin.to(extra.device, dtype=extra.dtype).reshape(-1)[0]
    else:
        capacity = float(capacity_per_bin)
        if capacity <= 0.0:
            return extra
    occupied = (
        fixed_density_map.to(extra.device, dtype=extra.dtype) / capacity
    ).clamp_(0.0, 1.0)
    headroom = (cap - occupied).clamp_(min=0.0)
    return torch.minimum(extra, headroom)


def apply_blockage_to_density_map(
    initial_density_map,
    blockage_map,
    capacity_per_bin,
    blockage_max=1.0,
):
    """Add the soft blockage to a fixed-cell density map, in place.

    @param initial_density_map [X, Y] fixed density in area units, already
           multiplied by target_density.  Modified in place.
    @param blockage_map [X, Y] capacity reduction as a bin-area fraction, or
           None (in which case the map is returned untouched, bit-for-bit).
    @param capacity_per_bin ``target_density * bin_area``.
    @return the applied extra area per bin ([X, Y], area units), or None.
    """
    if blockage_map is None or initial_density_map is None:
        return None
    if torch.is_tensor(capacity_per_bin):
        capacity = capacity_per_bin.to(
            initial_density_map.device, dtype=initial_density_map.dtype
        ).reshape(-1)[0]
        capacity_value = float(capacity)
    else:
        capacity = float(capacity_per_bin)
        capacity_value = capacity
    if not (capacity_value > 0.0):
        return None
    extra = blockage_map.to(
        initial_density_map.device, dtype=initial_density_map.dtype
    ).clone()
    extra = cap_by_fixed_headroom(
        extra, initial_density_map, capacity, blockage_max
    )
    extra_area = extra * capacity
    initial_density_map.add_(extra_area)
    return extra_area
