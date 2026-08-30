"""Unified GPUGR map / metric helpers (RUPlace batch 2, item A1).

Every consumer of the bundled GPUGR maps -- the in-loop adapter
(:func:`dreamplace.ops.gpugr.xplace_backend.XplaceGGRAdapter.run_route`), the
out-of-process evaluator (``_external_eval_main``, which also backs
``run_gpugr.py``) and the standalone DEF evaluator
(``tools/ruplace_quality.py --_eval-def``) -- used to carry their own copy of
the same tensor algebra.  They are now all thin wrappers over this module, so
a change to the congestion definition happens in exactly one place.

Everything here is pure torch and side-effect free: no CUDA allocation beyond
what the input tensors already imply, no logging, no file IO.

Layer indexing
--------------
GPUGR hands back per-layer maps of shape ``[n_layers, X, Y]`` with routing
layer 0 = M1.  All aggregates here skip layer 0 (``all_start = 1``), matching
the legacy in-loop code: M1 carries pin shapes rather than routed wire, so
including it just adds a constant.  The H/V layer strides come from
``m1direction`` exactly as the legacy code derived them.

Utilization modes
-----------------
``legacy``
    ``dmd / cap`` summed over layers.  Bit-identical to what the three call
    sites did before this module existed.  This is the default everywhere.

``avail``
    ``(dmd - fixed) / (cap - fixed)``, i.e. utilization against the capacity
    that is actually *available* after fixed obstacles (macro/pin/blockage/
    SNet shapes) are discounted.  This is the closer analogue of Innovus's
    ``remain / total``, which is reported after blockages, and it is what the
    batch-1 calibration found correlates best (Spearman .77/.76 vs .47/.29).

    Note on the numerator: ``dmd`` = ``wire_dmd`` + the in-gcell via-usage
    term, and that via term is already scaled by the ``via_usage_scale``
    GR setting.  Using ``dmd - fixed`` (rather than the wire-only
    ``wire_dmd - fixed`` that ``tools/ruplace_gr_calibrate.py`` uses for its
    own reporting) therefore keeps the via contribution under the control of
    ``via_usage_scale``: with ``via_usage_scale=0`` the two coincide.
"""

import torch

UTIL_MODES = ("legacy", "avail")


def hv_layer_ids(m1direction):
    """The (h_id, v_id) layer strides the legacy code derives from ``m1direction``.

    Returns indices into the per-layer maps such that ``maps[h_id::2]`` are the
    horizontal routing layers and ``maps[v_id::2]`` the vertical ones, with
    layer 0 (M1) never selected.
    """
    h_id = 1 if m1direction else 0
    v_id = 0 if m1direction else 1
    h_id = h_id + 2 if h_id == 0 else h_id
    v_id = v_id + 2 if v_id == 0 else v_id
    return h_id, v_id


def _nan_to_num(t):
    return torch.nan_to_num(t, nan=0.0, posinf=0.0, neginf=0.0)


def hv_maps(dmd, wire_dmd, via_dmd, cap, fixed=None, m1direction=1, util_mode="legacy"):
    """Aggregate per-layer GR maps into 2D and H/V utilization / overflow.

    Parameters
    ----------
    dmd, wire_dmd, via_dmd, cap : torch.Tensor
        Per-layer maps, shape ``[n_layers, X, Y]``.  ``via_dmd`` is accepted for
        signature symmetry with the callers; it is unused here (it enters via
        ``dmd``) and may be ``None``.
    fixed : torch.Tensor or None
        Per-layer fixed-obstacle capacity consumption.  Required for
        ``util_mode='avail'``.
    m1direction : int
        As reported by ``gpdb.m1direction()``.
    util_mode : {'legacy', 'avail'}

    Returns
    -------
    util_2d, overflow_2d, hv_util, hv_overflow
        ``util_2d`` / ``overflow_2d`` have shape ``[X, Y]``; ``hv_util`` /
        ``hv_overflow`` have shape ``[2, X, Y]`` with index 0 = horizontal.
    """
    if util_mode not in UTIL_MODES:
        raise ValueError("util_mode must be one of %s, got %r" % (UTIL_MODES, util_mode))
    if util_mode == "avail" and fixed is None:
        raise ValueError("util_mode='avail' needs the fixed map (routeforce.fixed_map())")

    eps = torch.finfo(dmd.dtype).eps
    h_id, v_id = hv_layer_ids(m1direction)
    all_start = 1

    if util_mode == "legacy":
        num_all, den_all = dmd[all_start:], cap[all_start:]

        def num_den(start):
            return dmd[start::2], cap[start::2]
    else:
        num_all, den_all = dmd[all_start:] - fixed[all_start:], cap[all_start:] - fixed[all_start:]

        def num_den(start):
            return dmd[start::2] - fixed[start::2], cap[start::2] - fixed[start::2]

    util_2d = _nan_to_num(num_all.sum(dim=0) / den_all.sum(dim=0).clamp_min(eps))
    if util_mode == "avail":
        util_2d = util_2d.clamp_min(0.0)
    overflow_2d = (util_2d - 1).clamp_min(0).contiguous()

    cg = []
    for start in (h_id, v_id):
        n, d = num_den(start)
        u = _nan_to_num(n.sum(dim=0) / d.sum(dim=0).clamp_min(eps))
        if util_mode == "avail":
            u = u.clamp_min(0.0)
        cg.append(u)
    hv_util = torch.stack(tuple(cg)).contiguous()
    hv_overflow = (hv_util - 1).clamp_min(0).contiguous()
    return util_2d.contiguous(), overflow_2d, hv_util, hv_overflow


def gr_wirelength_um(wl_steps, step_x, step_y, microns):
    """GR wirelength in microns.

    GPUGR reports wirelength as a count of gcell steps; one step is the gcell
    pitch in DBU, and ``microns`` is the DEF ``UNITS DISTANCE MICRONS``.
    """
    microns = float(microns)
    if microns <= 0:
        return float("nan")
    return float(wl_steps) * max(float(step_x), float(step_y)) / microns


def gr_wirelength_m2pitch(wl_steps, step_x, step_y, layer_pitch):
    """GR wirelength in M2 pitches -- the unit Xplace/ISPD18 scoring uses.

    Kept for continuity with the published ISPD18 numbers: it is what
    ``tools/ruplace_quality.py`` has always reported as ``route_wl``.
    """
    layer_m2_pitch = layer_pitch[1] if len(layer_pitch) > 1 else layer_pitch[0]
    return float(wl_steps) * max(float(step_x), float(step_y)) / layer_m2_pitch


def estimate_num_shorts(cap_map, wire_dmd_map, via_dmd_map, layer_width, layer_pitch,
                        step_x, step_y, microns, m1direction):
    """Layer-area-weighted estimated short count (the ISPD18-style estimate).

    Moved verbatim from ``tools/ruplace_quality.py::_estimate_num_shorts``; the
    only change is that the scalars are passed in rather than pulled off
    ``routeforce``/``gpdb`` here, so the module stays import-free.
    """
    layer_m2_pitch = layer_pitch[1] if len(layer_pitch) > 1 else layer_pitch[0]
    microns = float(microns)
    h_id = 1 if m1direction else 0
    v_id = 0 if m1direction else 1

    layer_area = torch.tensor(layer_width, device=cap_map.device, dtype=cap_map.dtype)
    layer_area[h_id::2].mul_(step_x / microns / layer_m2_pitch / layer_m2_pitch)
    layer_area[v_id::2].mul_(step_y / microns / layer_m2_pitch / layer_m2_pitch)

    wire_ovfl_map = (wire_dmd_map - cap_map).clamp(min=0.0)
    routed_short_area = (wire_ovfl_map.sum(dim=(1, 2)) * layer_area).sum()
    via_ovfl_mask = (wire_dmd_map > cap_map).float()
    routed_short_via_num = (via_ovfl_mask * via_dmd_map).sum()
    return float((routed_short_area + routed_short_via_num).item())


def estimate_num_shorts_simple(dmd_map, cap_map, wire_dmd_map, via_dmd_map):
    """The unweighted estimate the in-loop / external-eval paths have always used.

    ``(wire_dmd - cap)+`` summed over every routing layer (M1 included, which is
    deliberate -- GPUGR's own short formula does the same) plus the via demand
    in every gcell whose per-layer ``dmd/cap`` exceeds 1.
    """
    eps = torch.finfo(dmd_map.dtype).eps
    util_by_layer = dmd_map / cap_map.clamp_min(eps)
    return float(
        (wire_dmd_map - cap_map).clamp_min(0).sum().item()
        + via_dmd_map[util_by_layer > 1].sum().item()
    )


def rc_means(hv_overflow):
    """ACE (Average Congestion of Edges) means, one per direction.

    Moved verbatim from ``tools/ruplace_quality.py::_rc_means``: for each of the
    ACE fractions the mean overflow of the worst that fraction of gcells, then
    averaged over the fractions.  Returns ``[rc_hor, rc_ver]``.
    """
    ace_list = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5]
    ace_tsr = torch.tensor(ace_list, device=hv_overflow.device, dtype=hv_overflow.dtype)
    tmp = torch.sort((hv_overflow + 1).reshape(2, -1), descending=True)[0]
    rc = torch.cumsum(tmp, 1) / torch.arange(1, tmp.shape[1] + 1, device=tmp.device, dtype=tmp.dtype)
    indices = (tmp.shape[1] * ace_tsr).long().clamp(max=tmp.shape[1] - 1)
    selected_rc = rc[:, indices].cpu()
    return selected_rc.mean(dim=1).tolist()


def route_metrics(num_ovfl_nets, hv_overflow, dmd_map, wire_dmd_map, via_dmd_map, cap_map,
                  wl_steps, gr_vias, step_x=None, step_y=None, microns=None,
                  rc_mode="mean", shorts_mode="simple", **shorts_kwargs):
    """Assemble the metric dict the adapters publish.

    ``rc_mode``
        ``'mean'`` (legacy in-loop / external-eval): ``rc_hor/rc_ver`` are the
        plain means of the H/V overflow maps.
        ``'ace'`` (legacy eval-CLI): the ACE means from :func:`rc_means`.
    ``shorts_mode``
        ``'simple'`` (legacy in-loop / external-eval) or ``'area'`` (legacy
        eval-CLI, needs the extra keyword arguments of
        :func:`estimate_num_shorts`).
    """
    if shorts_mode == "simple":
        est_shorts = estimate_num_shorts_simple(dmd_map, cap_map, wire_dmd_map, via_dmd_map)
    elif shorts_mode == "area":
        est_shorts = estimate_num_shorts(cap_map, wire_dmd_map, via_dmd_map, **shorts_kwargs)
    else:
        raise ValueError("shorts_mode must be 'simple' or 'area', got %r" % shorts_mode)

    if rc_mode == "mean":
        rc_hor = float(hv_overflow[0].mean().item())
        rc_ver = float(hv_overflow[1].mean().item())
    elif rc_mode == "ace":
        rc_hor, rc_ver = rc_means(hv_overflow)
    else:
        raise ValueError("rc_mode must be 'mean' or 'ace', got %r" % rc_mode)

    metrics = {
        "num_ovfl_nets": int(num_ovfl_nets),
        "gr_wirelength": float(wl_steps),
        "gr_vias": float(gr_vias),
        "est_shorts": float(est_shorts),
        "rc_hor": float(rc_hor),
        "rc_ver": float(rc_ver),
    }
    if step_x is not None and step_y is not None and microns is not None:
        metrics["gr_wirelength_um"] = gr_wirelength_um(wl_steps, step_x, step_y, microns)
    return metrics
