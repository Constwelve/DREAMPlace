##
# @file   ruplace_op.py
# @brief  RUPlace routability optimization op built on GPUGR backends.
#

import json
import logging
import os

import torch
import torch.nn.functional as F

import dreamplace.ops.electric_potential.congestion_blockage as congestion_blockage
from dreamplace.ops.gpugr.gpugr import build_gpugr_backend
from dreamplace.ops.routability_opt.innovus_proxy import build_inflation_proxy
from dreamplace.ops.routability_opt.inflation_calibration import (
    EFFORT_PROFILES,
    InflationCalibration,
    adaptive_budget,
    normalize_effort,
    overflow_coverage_pct,
)


def close_quietly(obj, what="router resource"):
    """Call obj.close() if it exists, never raising.

    Used to drop the exclusive GPU lock (see
    dreamplace/ops/gpugr/gpu_lock.py) as soon as global placement no longer
    needs the router, instead of holding it until the process exits.  Only
    ruplace_gpu_lock_mode=run still holds a placement-wide lock; the default
    call mode locks per router call and close() is then a no-op.
    """
    if obj is None:
        return False
    closer = getattr(obj, "close", None)
    if not callable(closer):
        return False
    try:
        closer()
    except Exception as e:  # never let cleanup break the placement flow
        logging.warning("RUPlace failed to close %s: %s", what, e)
        return False
    return True


class RUPlaceInflation(object):
    def __init__(self, params, placedb, data_collections):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.original_movable_area = (
            data_collections.node_size_x[: placedb.num_movable_nodes]
            * data_collections.node_size_y[: placedb.num_movable_nodes]
        ).sum()
        filler_area = (
            data_collections.node_size_x[-placedb.num_filler_nodes:]
            * data_collections.node_size_y[-placedb.num_filler_nodes:]
        ).sum() if placedb.num_filler_nodes > 0 else self.original_movable_area.new_tensor(0.0)
        extra_capacity = float(getattr(params, "ruplace_inflate_extra_capacity", 0.0))
        self.total_place_area = (
            (self.original_movable_area + filler_area) / data_collections.target_density
            + extra_capacity * self.original_movable_area
        )
        # Congestion soft blockage eats into the placeable area, so keep the
        # pristine budget around and derive total_place_area from it.
        self.base_total_place_area = self.total_place_area
        # Filler budget: always net of the blocked area (see set_blocked_area).
        # In the default `shared` budget mode it stays equal to
        # total_place_area, so nothing changes.
        self.filler_place_area = self.total_place_area
        self.blocked_place_area = 0.0
        self.cluster_ids = None
        self.original_node_size_x = data_collections.node_size_x[: placedb.num_movable_nodes].clone()
        self.original_node_size_y = data_collections.node_size_y[: placedb.num_movable_nodes].clone()
        self.current_inflate_ratio = torch.ones(
            placedb.num_movable_nodes,
            dtype=data_collections.node_size_x.dtype,
            device=data_collections.node_size_x.device,
        )

    def _node_name(self, node_id):
        name = self.placedb.node_names[node_id]
        if isinstance(name, bytes):
            return name.decode("utf8", errors="ignore")
        return str(name)

    def _build_cluster_ids(self, pos):
        num_nodes = self.placedb.num_nodes
        num_movable = self.placedb.num_movable_nodes
        keys = []
        has_hierarchy = False
        for node_id in range(num_movable):
            name = self._node_name(node_id)
            if "/" in name:
                has_hierarchy = True
                keys.append(name.rsplit("/", 1)[0])
            else:
                keys.append(None)

        if not has_hierarchy:
            row_height = max(float(getattr(self.placedb, "row_height", 1.0)), 1.0)
            y = pos[num_nodes : num_nodes + num_movable]
            keys = ["rowgrp_%d" % int((float(v.item())) / (4 * row_height)) for v in y]

        cluster_map = {}
        cluster_ids = torch.empty(num_movable, dtype=torch.long, device=pos.device)
        for node_id, key in enumerate(keys):
            if key not in cluster_map:
                cluster_map[key] = len(cluster_map)
            cluster_ids[node_id] = cluster_map[key]
        logging.info("RUPlace built %d inflation clusters", len(cluster_map))
        return cluster_ids

    def _build_adaptive_cluster_ids(self, pos, min_cells=256, max_cells=4096):
        """Build bounded hierarchy modules, splitting oversized groups spatially."""
        num_nodes = self.placedb.num_nodes
        num_movable = self.placedb.num_movable_nodes
        paths = []
        counts = {}
        for node_id in range(num_movable):
            parts = self._node_name(node_id).split("/")[:-1]
            prefixes = ["/".join(parts[:depth]) for depth in range(1, len(parts) + 1)]
            paths.append(prefixes)
            for prefix in prefixes:
                counts[prefix] = counts.get(prefix, 0) + 1

        x = pos[:num_movable]
        y = pos[num_nodes : num_nodes + num_movable]
        x_values = x.detach().cpu().tolist()
        y_values = y.detach().cpu().tolist()
        xl, xh = float(self.placedb.routing_grid_xl), float(self.placedb.routing_grid_xh)
        yl, yh = float(self.placedb.routing_grid_yl), float(self.placedb.routing_grid_yh)
        keys = []
        for node_id, prefixes in enumerate(paths):
            bounded = [key for key in prefixes if min_cells <= counts[key] <= max_cells]
            if bounded:
                key = bounded[-1]
            else:
                large = [key for key in prefixes if counts[key] >= min_cells]
                key = large[-1] if large else "spatial"
            if key == "spatial" or counts.get(key, max_cells + 1) > max_cells:
                tx = int(8 * (x_values[node_id] - xl) / max(xh - xl, 1.0))
                ty = int(8 * (y_values[node_id] - yl) / max(yh - yl, 1.0))
                tx, ty = min(max(tx, 0), 7), min(max(ty, 0), 7)
                key = "%s#tile_%d_%d" % (key, tx, ty)
            keys.append(key)

        # An 8x8 spatial tile can still exceed max_cells on a very large flat
        # design.  Split such tiles deterministically so the advertised module
        # cap is a hard bound rather than only a target.
        key_members = {}
        for node_id, key in enumerate(keys):
            key_members.setdefault(key, []).append(node_id)
        for key, members in key_members.items():
            if len(members) <= max_cells:
                continue
            members.sort(key=lambda node_id: (
                x_values[node_id], y_values[node_id], node_id
            ))
            for offset, node_id in enumerate(members):
                keys[node_id] = "%s#chunk_%d" % (key, offset // max_cells)

        cluster_map = {}
        cluster_values = []
        for key in keys:
            if key not in cluster_map:
                cluster_map[key] = len(cluster_map)
            cluster_values.append(cluster_map[key])
        cluster_ids = torch.tensor(cluster_values, dtype=torch.long, device=pos.device)
        logging.info(
            "RUPlace adaptive inflation built %d modules (%d-%d cells target)",
            len(cluster_map), min_cells, max_cells,
        )
        return cluster_ids

    def _cluster_uniform_ratio(self, raw_ratio, pos):
        if self.cluster_ids is None or self.cluster_ids.numel() != raw_ratio.numel():
            self.cluster_ids = self._build_cluster_ids(pos)
        out = raw_ratio.clone()
        for cluster_id in torch.unique(self.cluster_ids).tolist():
            mask = self.cluster_ids == cluster_id
            # Uniform inflation per cluster follows the paper's coarse global step.
            out[mask] = raw_ratio[mask].mean()
        return out

    def _node_bin_utilization(self, pos, utilization_map, hv_overflow_map=None):
        num_nodes = self.placedb.num_nodes
        num_bins_x, num_bins_y = utilization_map.shape
        util = torch.nan_to_num(
            utilization_map.to(pos.device, dtype=pos.dtype),
            nan=1.0,
            posinf=1.0,
            neginf=1.0,
        )
        hv_gamma = float(getattr(self.params, "ruplace_hv_inflate_gamma", 0.0))
        if hv_gamma > 0.0 and hv_overflow_map is not None:
            hv = torch.nan_to_num(
                hv_overflow_map.to(pos.device, dtype=pos.dtype),
                nan=0.0,
                posinf=0.0,
                neginf=0.0,
            )
            mode = str(getattr(self.params, "ruplace_hv_inflate_mode", "max")).lower()
            if hv.dim() == 3 and hv.shape[0] >= 2:
                if mode in ("mean", "avg", "average"):
                    hv_score = hv[:2].mean(dim=0)
                elif mode in ("sum", "add"):
                    hv_score = hv[:2].sum(dim=0)
                elif mode in ("h", "hor", "horizontal"):
                    hv_score = hv[0]
                elif mode in ("v", "ver", "vertical"):
                    hv_score = hv[1]
                else:
                    hv_score = hv[:2].max(dim=0).values
            elif hv.shape == util.shape:
                hv_score = hv
            else:
                hv_score = None
            if hv_score is not None:
                util = util + hv_gamma * hv_score.clamp_min(0.0)
        window = int(getattr(self.params, "ruplace_node_util_window", 0))
        if window > 0:
            pooled = F.max_pool2d(
                util.view(1, 1, num_bins_x, num_bins_y),
                kernel_size=2 * window + 1,
                stride=1,
                padding=window,
            ).view(num_bins_x, num_bins_y)
            blend = float(getattr(self.params, "ruplace_node_util_blend", 1.0))
            blend = max(0.0, min(1.0, blend))
            util = util * (1.0 - blend) + pooled * blend
        bin_size_x = (self.placedb.routing_grid_xh - self.placedb.routing_grid_xl) / num_bins_x
        bin_size_y = (self.placedb.routing_grid_yh - self.placedb.routing_grid_yl) / num_bins_y
        node_x = pos[: self.placedb.num_movable_nodes]
        node_y = pos[num_nodes : num_nodes + self.placedb.num_movable_nodes]
        center_x = node_x + self.data_collections.node_size_x[: self.placedb.num_movable_nodes] * 0.5
        center_y = node_y + self.data_collections.node_size_y[: self.placedb.num_movable_nodes] * 0.5
        bin_x = ((center_x - self.placedb.routing_grid_xl) / bin_size_x).long().clamp_(0, num_bins_x - 1)
        bin_y = ((center_y - self.placedb.routing_grid_yl) / bin_size_y).long().clamp_(0, num_bins_y - 1)
        return util[bin_x, bin_y]

    def _scale_movable_nodes(self, pos, target_ratio, max_ratio=None):
        dc = self.data_collections
        num_nodes = self.placedb.num_nodes
        num_movable = self.placedb.num_movable_nodes
        num_filler = self.placedb.num_filler_nodes
        min_ratio = float(getattr(self.params, "ruplace_min_inflate_ratio", 1.0))
        if max_ratio is None:
            max_ratio = float(self.params.ruplace_max_inflate_ratio)
        target_ratio = target_ratio.to(pos.device, dtype=pos.dtype).clamp_(
            min=min_ratio, max=float(max_ratio)
        )
        current_ratio = self.current_inflate_ratio.to(pos.device, dtype=pos.dtype).clamp_min(1e-6)
        ratio = target_ratio / current_ratio
        size_ratio = torch.sqrt(ratio.clamp_min(1e-6))
        old_size_x = dc.node_size_x[:num_movable].clone()
        old_size_y = dc.node_size_y[:num_movable].clone()
        old_center_x = pos.data[:num_movable] + old_size_x * 0.5
        old_center_y = pos.data[num_nodes : num_nodes + num_movable] + old_size_y * 0.5

        dc.node_size_x[:num_movable].mul_(size_ratio)
        dc.node_size_y[:num_movable].mul_(size_ratio)
        dc.node_areas = dc.node_size_x * dc.node_size_y
        pos.data[:num_movable].copy_(old_center_x - dc.node_size_x[:num_movable] * 0.5)
        pos.data[num_nodes : num_nodes + num_movable].copy_(old_center_y - dc.node_size_y[:num_movable] * 0.5)

        for node_id in range(num_movable):
            start = int(dc.flat_node2pin_start_map[node_id].item())
            end = int(dc.flat_node2pin_start_map[node_id + 1].item())
            if end <= start:
                continue
            pins = dc.flat_node2pin_map[start:end]
            shift_ratio = (size_ratio[node_id] - 1.0) * 0.5
            dc.pin_offset_x[pins] += shift_ratio * old_size_x[node_id]
            dc.pin_offset_y[pins] += shift_ratio * old_size_y[node_id]

        if num_filler > 0:
            new_movable_area = (dc.node_size_x[:num_movable] * dc.node_size_y[:num_movable]).sum()
            filler_start = num_nodes - num_filler
            old_filler_area = (dc.node_size_x[filler_start:num_nodes] * dc.node_size_y[filler_start:num_nodes]).sum()
            if old_filler_area.item() > 0:
                new_filler_area = torch.clamp(self._filler_budget() - new_movable_area, min=0)
                filler_ratio = torch.sqrt(new_filler_area / old_filler_area).to(pos.device, dtype=pos.dtype)
                filler_size_x = dc.node_size_x[filler_start:num_nodes]
                filler_size_y = dc.node_size_y[filler_start:num_nodes]
                filler_center_x = pos.data[filler_start:num_nodes] + filler_size_x * 0.5
                filler_center_y = pos.data[num_nodes + filler_start : 2 * num_nodes] + filler_size_y * 0.5
                filler_size_x.mul_(filler_ratio)
                filler_size_y.mul_(filler_ratio)
                pos.data[filler_start:num_nodes].copy_(filler_center_x - filler_size_x * 0.5)
                pos.data[num_nodes + filler_start : 2 * num_nodes].copy_(filler_center_y - filler_size_y * 0.5)
                dc.node_areas = dc.node_size_x * dc.node_size_y
        self.current_inflate_ratio.copy_(target_ratio.detach())

    def _blockage_budget_mode(self):
        """`shared` (default) or `independent` whitespace accounting."""
        mode = str(
            getattr(
                self.params, "ruplace_congestion_blockage_budget_mode", "shared"
            )
        ).lower()
        if mode in ("independent", "indep", "separate"):
            return "independent"
        return "shared"

    def _filler_budget(self):
        """Placeable area the fillers may occupy.

        Identical to ``total_place_area`` in the default ``shared`` mode (so
        anything that adjusts ``total_place_area`` still moves the fillers);
        in ``independent`` mode it is the only budget the blockage shrinks.
        """
        if self._blockage_budget_mode() != "independent":
            return self.total_place_area
        return getattr(self, "filler_place_area", self.total_place_area)

    def set_blocked_area(self, blocked_area):
        """Shrink the placeable-area budget by the soft-blockage area.

        ``blocked_area`` is raw placement area (bin-area fraction x bin area),
        the same units as ``total_place_area``.  Folding it in here means the
        filler rescale inside ``_scale_movable_nodes`` also honours the
        blockage, so blockage and inflation compose instead of fighting.

        ``ruplace_congestion_blockage_budget_mode`` picks how the blocked area
        is charged:

        * ``shared`` (default, previous behaviour bit-for-bit): the blocked
          area comes off both the filler budget and the inflation whitespace
          budget (``apply_node_ratios``' ``max_inc``), so the two levers draw
          on the same pool.
        * ``independent``: only the filler budget shrinks; inflation keeps the
          pristine ``base_total_place_area`` whitespace, so turning blockage on
          does not silently starve the inflation budget.
        """
        blocked = max(float(blocked_area), 0.0)
        self.blocked_place_area = blocked
        budget = self.base_total_place_area - blocked
        floor = self.original_movable_area
        if torch.is_tensor(budget):
            shrunk = torch.maximum(budget, floor)
        else:
            shrunk = max(budget, float(floor))
        # fillers always give up the blocked area
        self.filler_place_area = shrunk
        if self._blockage_budget_mode() == "independent":
            self.total_place_area = self.base_total_place_area
        else:
            self.total_place_area = shrunk
        return self.total_place_area

    def rescale_fillers(self, pos):
        """Shrink fillers to fit the current placeable-area budget.

        Mirrors ``adjust_node_area``: shrink only (guarded by the same
        ``movable + filler > total_place_area`` condition), one shared ratio,
        cell centers preserved.  Fillers carry no pins, so no pin-offset fixup
        is needed.  Returns True if the filler sizes changed.
        """
        dc = self.data_collections
        num_nodes = self.placedb.num_nodes
        num_movable = self.placedb.num_movable_nodes
        num_filler = self.placedb.num_filler_nodes
        if num_filler <= 0:
            return False
        filler_start = num_nodes - num_filler
        movable_area = (
            dc.node_size_x[:num_movable] * dc.node_size_y[:num_movable]
        ).sum()
        filler_size_x = dc.node_size_x[filler_start:num_nodes]
        filler_size_y = dc.node_size_y[filler_start:num_nodes]
        old_filler_area = (filler_size_x * filler_size_y).sum()
        if float(old_filler_area) <= 0.0:
            return False
        budget = self._filler_budget()
        budget_value = float(budget)
        if float(movable_area) + float(old_filler_area) <= budget_value:
            return False
        new_filler_area = torch.clamp(budget - movable_area, min=0)
        ratio = torch.sqrt(new_filler_area / old_filler_area).to(
            pos.device, dtype=pos.dtype
        )
        filler_center_x = pos.data[filler_start:num_nodes] + filler_size_x * 0.5
        filler_center_y = (
            pos.data[num_nodes + filler_start : 2 * num_nodes] + filler_size_y * 0.5
        )
        filler_size_x.mul_(ratio)
        filler_size_y.mul_(ratio)
        pos.data[filler_start:num_nodes].copy_(filler_center_x - filler_size_x * 0.5)
        pos.data[num_nodes + filler_start : 2 * num_nodes].copy_(
            filler_center_y - filler_size_y * 0.5
        )
        dc.node_areas = dc.node_size_x * dc.node_size_y
        logging.info(
            "RUPlace blockage filler rescale: ratio %.6f, filler area %.4E -> %.4E, "
            "budget %.4E (blocked %.4E)",
            float(ratio),
            float(old_filler_area),
            float(new_filler_area),
            budget_value,
            self.blocked_place_area,
        )
        return True

    def apply(self, pos, route, global_pass):
        util = route.utilization_map
        hv_overflow = getattr(route, "hv_overflow_map", None)
        # Utilization threshold: bins whose utilization exceeds this fraction of capacity
        # are treated as congested. 1.0 reproduces the legacy "only overfull bins inflate"
        # behaviour; smaller values widen the set of cells that receive inflation.
        util_threshold = float(getattr(self.params, "ruplace_inflate_util_threshold", 1.0))
        if not (util_threshold > 0.0):
            util_threshold = 1.0
        if global_pass:
            # Convex-inflation surrogate: distribute bounded area growth by
            # cluster-level route utilization while enforcing whitespace budget.
            node_util = (
                self._node_bin_utilization(pos, util, hv_overflow) / util_threshold
            ).clamp_min(1.0)
            cluster_mode = str(getattr(self.params, "ruplace_global_cluster_mode", "mean")).lower()
            if cluster_mode in ("none", "off", "0", "false"):
                cluster_util = node_util
            elif cluster_mode in ("max", "maximum"):
                if self.cluster_ids is None or self.cluster_ids.numel() != node_util.numel():
                    self.cluster_ids = self._build_cluster_ids(pos)
                cluster_util = node_util.clone()
                for cluster_id in torch.unique(self.cluster_ids).tolist():
                    mask = self.cluster_ids == cluster_id
                    cluster_util[mask] = node_util[mask].max()
            else:
                cluster_util = self._cluster_uniform_ratio(node_util, pos)
            exponent = float(getattr(self.params, "ruplace_global_util_exponent", 1.0))
            if exponent != 1.0:
                cluster_util = 1.0 + torch.pow((cluster_util - 1.0).clamp_min(0.0), exponent)
            global_gamma = float(getattr(self.params, "ruplace_global_inflate_gamma", 1.0))
            raw_ratio = 1.0 + global_gamma * (cluster_util - 1.0)
            fallback_ratio = float(getattr(self.params, "ruplace_congested_uniform_inflate_ratio", 1.0))
            if fallback_ratio > 1.0:
                raw_ratio.clamp_(min=fallback_ratio)
        else:
            local_gamma = float(self.params.ruplace_local_inflate_gamma)
            if int(getattr(self.params, "ruplace_allow_shrink", 0)):
                desired_ratio = (
                    self._node_bin_utilization(pos, util, hv_overflow) / util_threshold
                ).clamp_min(1.0)
                raw_ratio = (1.0 - local_gamma) * self.current_inflate_ratio.to(
                    pos.device, dtype=pos.dtype
                ) + local_gamma * desired_ratio
            else:
                overflow = route.overflow_map
                local_ratio = (
                    1.0
                    + local_gamma
                    * self._node_bin_utilization(pos, overflow, hv_overflow)
                )
                raw_ratio = torch.maximum(
                    self.current_inflate_ratio.to(pos.device, dtype=pos.dtype),
                    local_ratio,
                )
        num_raw = max(int(raw_ratio.numel()), 1)
        logging.info(
            "RUPlace inflation targets (%s, util_threshold %.3f): "
            "inflated frac %.4f, raw ratio mean/max %.4f/%.4f",
            "global" if global_pass else "local",
            util_threshold,
            float((raw_ratio > 1.001).sum().item()) / num_raw,
            float(raw_ratio.mean().item()),
            float(raw_ratio.max().item()),
        )
        return self.apply_node_ratios(pos, raw_ratio)

    def apply_node_ratios(
        self, pos, raw_ratio, area_cap=None, max_ratio=None, cumulative_area_cap=None
    ):
        """Apply externally computed cumulative area ratios with RUPlace budgets."""
        raw_ratio = torch.nan_to_num(raw_ratio, nan=1.0, posinf=1.0, neginf=1.0)
        if max_ratio is None:
            max_ratio = float(self.params.ruplace_max_inflate_ratio)
        raw_ratio.clamp_(
            min=float(getattr(self.params, "ruplace_min_inflate_ratio", 1.0)),
            max=float(max_ratio),
        )

        dc = self.data_collections
        num_movable = self.placedb.num_movable_nodes
        old_area = dc.node_size_x[:num_movable] * dc.node_size_y[:num_movable]
        target_area = self.original_node_size_x.to(pos.device, dtype=pos.dtype) * self.original_node_size_y.to(
            pos.device, dtype=pos.dtype
        ) * raw_ratio
        inc_area = target_area - old_area
        grow_area = inc_area.clamp_min(0.0)
        shrink_area = inc_area.clamp_max(0.0)
        grow_sum = grow_area.sum()
        change_sum = inc_area.abs().sum()
        if change_sum.item() <= 0:
            return False

        current_movable_area = old_area.sum()
        whitespace = (self.total_place_area - current_movable_area).clamp_min(0)
        if area_cap is None:
            area_cap = float(getattr(self.params, "ruplace_inflate_area_cap", 0.1))
        max_inc = torch.minimum(whitespace, area_cap * current_movable_area)
        if cumulative_area_cap is not None:
            cumulative_limit = self.original_movable_area * (1.0 + float(cumulative_area_cap))
            cumulative_remaining = (cumulative_limit - current_movable_area).clamp_min(0.0)
            max_inc = torch.minimum(max_inc, cumulative_remaining)
        if grow_sum.item() > 0 and max_inc.item() <= 0:
            logging.warning("RUPlace inflation skipped: no remaining whitespace budget")
            return False
        budget_limited = bool((grow_sum > max_inc).item())
        if budget_limited:
            grow_area.mul_(max_inc / grow_sum)
        final_area = old_area + grow_area + shrink_area
        final_area = torch.maximum(
            final_area,
            self.original_node_size_x.to(pos.device, dtype=pos.dtype)
            * self.original_node_size_y.to(pos.device, dtype=pos.dtype)
            * float(getattr(self.params, "ruplace_min_inflate_ratio", 1.0)),
        )
        target_cumulative_ratio = final_area / (
            self.original_node_size_x.to(pos.device, dtype=pos.dtype)
            * self.original_node_size_y.to(pos.device, dtype=pos.dtype)
        ).clamp_min(1e-12)
        target_cumulative_ratio = torch.nan_to_num(
            target_cumulative_ratio, nan=1.0, posinf=1.0, neginf=1.0
        )
        actual_change = (final_area - old_area).abs().sum()
        if (actual_change / old_area.sum()).item() < 1e-4:
            return False
        self._scale_movable_nodes(pos, target_cumulative_ratio, max_ratio=max_ratio)
        logging.info(
            "RUPlace %s inflation: area increment %.4E (%.4f), ratio avg/max %.4f/%.4f, "
            "grow_sum/max_inc %.4E/%.4E (%s)",
            "plugin",
            (final_area - old_area).sum().item(),
            ((final_area - old_area).sum() / old_area.sum()).item(),
            target_cumulative_ratio.mean().item(),
            target_cumulative_ratio.max().item(),
            grow_sum.item(),
            max_inc.item(),
            "budget-limited" if budget_limited else "ratio-limited",
        )
        return True

    def adaptive_node_ratios(self, pos, route, phase, budget_fraction, profile):
        """Allocate one adaptive inflation budget with module/cell water filling."""
        pressure = self._node_bin_utilization(
            pos, route.utilization_map, getattr(route, "hv_overflow_map", None)
        ).clamp_min(0.0)
        quantile = 0.50 if phase == "module" else 0.70
        threshold = torch.quantile(pressure, quantile)
        score = (pressure - threshold).clamp_min(0.0)

        if phase == "module":
            if self.cluster_ids is None or self.cluster_ids.numel() != score.numel():
                self.cluster_ids = self._build_adaptive_cluster_ids(pos)
            num_clusters = int(self.cluster_ids.max().item()) + 1 if self.cluster_ids.numel() else 0
            sums = torch.zeros(num_clusters, dtype=score.dtype, device=score.device)
            counts = torch.zeros_like(sums)
            sums.scatter_add_(0, self.cluster_ids, score)
            counts.scatter_add_(0, self.cluster_ids, torch.ones_like(score))
            module_score = sums / counts.clamp_min(1.0)
            contribution = sums.clamp_min(0.0)
            self.last_adaptive_stats = {
                "top_module_fraction": float(
                    (contribution.max() / contribution.sum().clamp_min(1e-12)).item()
                ) if contribution.numel() else 0.0,
                "module_count": num_clusters,
                "pressure_threshold": float(threshold.item()),
            }
            score = module_score[self.cluster_ids]
        else:
            self.last_adaptive_stats = {
                "top_module_fraction": 0.0,
                "module_count": 0,
                "pressure_threshold": float(threshold.item()),
            }

        max_score = score.max()
        if not torch.isfinite(max_score) or max_score.item() <= 0.0:
            return False
        score = score / max_score.clamp_min(1e-12)
        current = self.current_inflate_ratio.to(pos.device, dtype=pos.dtype)
        if phase == "cell":
            cool = score <= 0.0
            base = current.clone()
            base[cool] = 1.0 + 0.90 * (base[cool] - 1.0)
        else:
            base = current

        original_area = (
            self.original_node_size_x.to(pos.device, dtype=pos.dtype)
            * self.original_node_size_y.to(pos.device, dtype=pos.dtype)
        )
        current_area = original_area * current
        target_growth = float(budget_fraction) * current_area.sum()
        max_ratio = float(profile["max_ratio"])

        def ratios(scale):
            return torch.minimum(base * torch.exp(score * scale), base.new_full(base.shape, max_ratio))

        high = 1.0
        for _ in range(12):
            candidate = ratios(high)
            growth = (original_area * (candidate - current)).clamp_min(0.0).sum()
            if growth >= target_growth or high >= 64.0:
                break
            high *= 2.0
        low = 0.0
        for _ in range(32):
            mid = 0.5 * (low + high)
            candidate = ratios(mid)
            growth = (original_area * (candidate - current)).clamp_min(0.0).sum()
            if growth < target_growth:
                low = mid
            else:
                high = mid
        target = ratios(high)
        return self.apply_node_ratios(
            pos,
            target,
            area_cap=float(budget_fraction),
            max_ratio=max_ratio,
            cumulative_area_cap=float(profile["cumulative_area_cap"]),
        )


class RUPlaceController(object):
    def __init__(self, params, placedb, data_collections):
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        backend = str(getattr(params, "ruplace_router_backend", "xplace")).lower()
        if backend not in ("gpugr", "xplace"):
            raise RuntimeError(
                "RUPlace routability optimization requires ruplace_router_backend=gpugr or xplace; "
                "InstantGR is available only through the standalone GPUGR op until LEF/DEF map export is implemented"
            )
        self.adapter = build_gpugr_backend(params, placedb=placedb, data_collections=data_collections)
        self.inflation = RUPlaceInflation(params, placedb, data_collections)
        self.inflation_rounds = 0
        self.global_inflation_done = False
        self.grad_iteration = 0
        self.admm_applications = 0
        self.admm_active = False
        self.inflation_effort = normalize_effort(
            getattr(params, "ruplace_inflation_effort", "legacy")
        )
        self.adaptive_profile = EFFORT_PROFILES.get(self.inflation_effort)
        self.calibration = None
        if self.adaptive_profile is not None:
            self.calibration = InflationCalibration.load_default()
            if not self.calibration.valid:
                raise RuntimeError("adaptive RUPlace inflation requires a valid calibration profile")
        self.inflation_phase = "module" if self.adaptive_profile is not None else "legacy"
        self.module_rounds = 0
        self.cell_rounds = 0
        self.inflation_stopped = False
        self.inflation_stop_reason = ""
        self.proxy_target_met = False
        self.target_confirmations = 0
        self.stagnation_rounds = 0
        self.error_integral = 0.0
        self.last_controller_score = None
        self.last_prediction = None
        self.last_rudy_prediction = None
        self.rudy_deferred_checks = 0
        self.gpugr_checks = 0
        self.inflation_history = []
        # Phase 2 lever 1: optionally take the *inflation* congestion map from an
        # Innovus early global route instead of GPUGR, so the placer optimizes
        # against the map that scores it.  Returns None (and changes nothing) for
        # the default ruplace_inflate_proxy=gpugr.  ADMM keeps using GPUGR either
        # way -- it needs per-net routes, which eGR does not hand back.
        self.innovus_proxy = build_inflation_proxy(
            params, placedb, self.adapter, adaptive_profile=self.adaptive_profile
        )
        # Phase 2 lever 2: congestion-driven soft blockage.  Instead of growing
        # cells in congested bins, remove capacity from those bins in the
        # electrostatic density term, so the existing density force spreads
        # cells out of them.  Off unless ruplace_congestion_blockage > 0.
        self.blockage_map = None
        self.blockage_refreshes = 0
        # Standalone blockage refresh schedule (off unless
        # ruplace_congestion_blockage_refresh_interval > 0): counts
        # _maybe_update_blockage() calls, i.e. maybe_adjust_area() calls.
        self.blockage_calls = 0
        self.last_blockage_refresh_call = None
        self._last_route_for_blockage = None

    def close(self):
        """Release router resources once global placement is over.

        Chiefly the exclusive GPU lock the in-process GGR adapter holds; the
        Innovus proxy only takes its flock inside a with block per call, so
        it has nothing to release here (the close probe is defensive).
        """
        close_quietly(getattr(self, "adapter", None), "GPUGR adapter")
        close_quietly(getattr(self, "innovus_proxy", None), "Innovus eGR proxy")

    def _inflation_route(self, pos, model):
        """The congestion map inflation consumes.  Only this dispatch is switchable."""
        if self.innovus_proxy is None:
            route = self.adapter.run_route(pos)
        else:
            route = self.innovus_proxy.run_route(
                pos, iteration=int(getattr(model, "iteration", 0) or 0)
            )
        # Remember the freshest congestion map so the soft blockage can refresh
        # from it even on iterations where no inflation is applied.
        self._last_route_for_blockage = route
        return route

    def _overflow_value(self, overflow):
        if overflow is None:
            return 1.0
        if torch.is_tensor(overflow):
            return float(overflow.max().item())
        return float(overflow)

    def _inflate_start_overflow(self):
        value = float(self.params.ruplace_inflate_start_overflow)
        if value < 0:
            value = float(self.params.node_area_adjust_overflow)
        return value

    def _maybe_inflate_legacy(self, pos, model):
        max_rounds = int(self.params.ruplace_local_inflate_max_rounds)
        if self.global_inflation_done and self.inflation_rounds >= max_rounds:
            return False
        if self._overflow_value(getattr(model, "overflow", None)) > self._inflate_start_overflow():
            return False

        route = self._inflation_route(pos, model)
        mean_overflow = float(route.overflow_map.mean().item())
        ovfl_nets = float(route.metrics.get("num_ovfl_nets", 0.0))
        est_shorts = float(route.metrics.get("est_shorts", 0.0))
        if (
            mean_overflow < float(self.params.ruplace_local_congestion_stop)
            and ovfl_nets <= float(getattr(self.params, "ruplace_local_ovfl_nets_stop", 0.0))
            and est_shorts <= float(getattr(self.params, "ruplace_local_est_shorts_stop", 0.0))
        ):
            self.global_inflation_done = True
            self.inflation_rounds = max_rounds
            logging.info(
                "RUPlace inflation skipped: route congestion below stop thresholds "
                "(mean_overflow %.4E, ovfl_nets %.0f, est_shorts %.0f)",
                mean_overflow,
                ovfl_nets,
                est_shorts,
            )
            return False

        global_pass = not self.global_inflation_done
        adjust_area_flag = self.inflation.apply(pos, route, global_pass)
        if adjust_area_flag:
            if not global_pass:
                self.inflation_rounds += 1
            self.global_inflation_done = True
            self.adapter.anchor_pos = None
            self.adapter.last_route = None
            logging.info("RUPlace inflation round %d applied", self.inflation_rounds)
        elif global_pass:
            self.global_inflation_done = True
            logging.info("RUPlace global inflation made no area adjustment")
        else:
            self.inflation_rounds = max_rounds
            logging.info("RUPlace inflation converged; no further area adjustment")
        return adjust_area_flag

    def _rudy_prediction(self, pos, model):
        op = getattr(model.op_collections, "route_utilization_map_op", None)
        if op is None or self.calibration is None:
            return None
        try:
            horizontal, vertical, route_map = op(pos, return_hv=True)
        except (TypeError, RuntimeError):
            return None
        coverage = (
            100.0 * float((horizontal > 1.0).sum().item()) / max(int(horizontal.numel()), 1),
            100.0 * float((vertical > 1.0).sum().item()) / max(int(vertical.numel()), 1),
        )
        route_sum = route_map.sum()
        route_overflow = float(
            ((route_map - 1.0).clamp_min(0.0).sum() / route_sum.clamp_min(1e-12)).item()
        )
        predicted = self.calibration.predict(
            "rudy", route_overflow, route_overflow, upper=True
        )
        return {"coverage_h": coverage[0], "coverage_v": coverage[1],
                "route_overflow": route_overflow,
                "ucb_h": predicted[0], "ucb_v": predicted[1]}

    def _route_prediction(self, route):
        coverage = overflow_coverage_pct(getattr(route, "hv_overflow_map", None))
        predicted = self.calibration.predict("gpugr", coverage[0], coverage[1], upper=True)
        return {"coverage_h": coverage[0], "coverage_v": coverage[1],
                "ucb_h": predicted[0], "ucb_v": predicted[1]}

    def _current_area_growth(self):
        original = self.inflation.original_node_size_x * self.inflation.original_node_size_y
        current = original * self.inflation.current_inflate_ratio.to(original.device)
        return float((current.sum() / original.sum() - 1.0).item())

    def _status_path(self):
        result_dir = getattr(self.params, "result_dir", "")
        if not result_dir:
            return ""
        try:
            design = self.params.design_name()
        except Exception:
            design = ""
        return os.path.join(result_dir, design, "ruplace_inflation_status.json")

    def _write_status(self):
        path = self._status_path()
        if not path:
            return
        payload = {
            "schema_version": 1,
            "effort": self.inflation_effort,
            "target_pct": self.adaptive_profile["target_pct"] if self.adaptive_profile else None,
            "phase": self.inflation_phase,
            "module_rounds": self.module_rounds,
            "cell_rounds": self.cell_rounds,
            "cumulative_area_growth": self._current_area_growth(),
            "proxy_target_met": self.proxy_target_met,
            "target_confirmations": self.target_confirmations,
            "stagnation_rounds": self.stagnation_rounds,
            "inflation_stopped": self.inflation_stopped,
            "stop_reason": self.inflation_stop_reason,
            "last_prediction": self.last_prediction,
            "last_rudy_prediction": self.last_rudy_prediction,
            "rudy_deferred_checks": self.rudy_deferred_checks,
            "gpugr_checks": self.gpugr_checks,
            "calibration": self.calibration.name if self.calibration else "legacy",
            "history": self.inflation_history,
        }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except OSError as error:
            logging.warning("RUPlace could not write inflation status %s: %s", path, error)

    def _stop_adaptive_inflation(self, reason, proxy_target_met=False):
        self.inflation_stopped = True
        self.inflation_stop_reason = reason
        self.proxy_target_met = bool(proxy_target_met)
        self.inflation_phase = "stopped"
        logging.info(
            "RUPlace adaptive inflation stopped: reason=%s proxy_target_met=%s",
            reason, self.proxy_target_met,
        )
        self._write_status()

    def _rudy_requests_gpugr(self, prediction, target):
        """Use RUDY to defer at most one expensive GPUGR checkpoint.

        GPUGR remains mandatory for the first sample, target confirmation, and
        stagnation decisions.  A material RUDY change also triggers GPUGR so
        the controller can react immediately after a useful placement move.
        """
        if prediction is None or self.last_prediction is None:
            return True
        if max(prediction["ucb_h"], prediction["ucb_v"]) <= 1.25 * float(target):
            return True
        if self.last_rudy_prediction is None:
            return True
        previous_score = max(
            self.last_rudy_prediction["ucb_h"], self.last_rudy_prediction["ucb_v"]
        )
        current_score = max(prediction["ucb_h"], prediction["ucb_v"])
        relative_change = abs(current_score - previous_score) / max(abs(previous_score), 1e-12)
        directional_change = max(
            abs(prediction["ucb_h"] - self.last_rudy_prediction["ucb_h"]),
            abs(prediction["ucb_v"] - self.last_rudy_prediction["ucb_v"]),
        )
        return (
            relative_change >= 0.03
            or directional_change >= 0.10
            or self.rudy_deferred_checks >= 1
        )

    def _maybe_inflate_adaptive(self, pos, model):
        if self.inflation_stopped:
            return False
        if self._overflow_value(getattr(model, "overflow", None)) > self._inflate_start_overflow():
            return False

        target = float(self.adaptive_profile["target_pct"])
        rudy = self._rudy_prediction(pos, model)
        if not self._rudy_requests_gpugr(rudy, target):
            self.rudy_deferred_checks += 1
            self.last_rudy_prediction = rudy
            self.inflation_history.append({
                "phase": self.inflation_phase,
                "module_round": self.module_rounds,
                "cell_round": self.cell_rounds,
                "rudy": rudy,
                "gpugr": None,
                "route_decision": "deferred_by_rudy",
                "cumulative_area_growth": self._current_area_growth(),
            })
            self._write_status()
            logging.info(
                "RUPlace RUDY screen deferred GPUGR once: predicted H/V %.3f/%.3f%%",
                rudy["ucb_h"], rudy["ucb_v"],
            )
            return False
        self.last_rudy_prediction = rudy
        self.rudy_deferred_checks = 0
        route = self.adapter.run_route(pos)
        self._last_route_for_blockage = route
        self.gpugr_checks += 1
        prediction = self._route_prediction(route)
        score = max(prediction["ucb_h"] / target, prediction["ucb_v"] / target)
        area_growth = self._current_area_growth()

        relative_improvement = None
        absolute_h = absolute_v = None
        if self.last_prediction is not None and self.last_controller_score is not None:
            relative_improvement = (
                self.last_controller_score - score
            ) / max(abs(self.last_controller_score), 1e-12)
            absolute_h = self.last_prediction["ucb_h"] - prediction["ucb_h"]
            absolute_v = self.last_prediction["ucb_v"] - prediction["ucb_v"]
            insufficient = (
                relative_improvement < 0.03
                and absolute_h < 0.10
                and absolute_v < 0.10
            ) or absolute_h < -0.10 or absolute_v < -0.10
            self.stagnation_rounds = self.stagnation_rounds + 1 if insufficient else 0

        target_now = prediction["ucb_h"] < target and prediction["ucb_v"] < target
        self.target_confirmations = self.target_confirmations + 1 if target_now else 0
        history_item = {
            "phase": self.inflation_phase,
            "module_round": self.module_rounds,
            "cell_round": self.cell_rounds,
            "rudy": rudy,
            "gpugr": prediction,
            "route_decision": "gpugr",
            "controller_score": score,
            "relative_improvement": relative_improvement,
            "absolute_improvement_h": absolute_h,
            "absolute_improvement_v": absolute_v,
            "cumulative_area_growth": area_growth,
        }
        self.inflation_history.append(history_item)
        self.last_prediction = prediction
        self.last_controller_score = score

        if self.target_confirmations >= 2:
            self._stop_adaptive_inflation("proxy_target_met", proxy_target_met=True)
            return False
        if self.target_confirmations == 1:
            self._write_status()
            logging.info(
                "RUPlace adaptive inflation awaiting second target confirmation: H/V %.3f/%.3f%%",
                prediction["ucb_h"], prediction["ucb_v"],
            )
            return False
        if self.stagnation_rounds >= 2 and area_growth >= 0.05:
            self._stop_adaptive_inflation("stagnated")
            return False
        if area_growth >= float(self.adaptive_profile["cumulative_area_cap"]) - 1e-6:
            self._stop_adaptive_inflation("capacity_exhausted")
            return False

        if (
            self.inflation_phase == "module"
            and self.module_rounds > 0
            and (
                self.module_rounds >= int(self.adaptive_profile["module_rounds"])
                or (relative_improvement is not None and relative_improvement < 0.05)
                or float(getattr(self.inflation, "last_adaptive_stats", {}).get(
                    "top_module_fraction", 1.0
                )) < 0.25
            )
        ):
            self.inflation_phase = "cell"
        if self.inflation_phase == "cell" and self.cell_rounds >= int(self.adaptive_profile["cell_rounds"]):
            self._stop_adaptive_inflation("capacity_exhausted")
            return False

        self.error_integral += max(score - 1.0, 0.0)
        budget = adaptive_budget(self.adaptive_profile, self.error_integral, score)
        adjusted = self.inflation.adaptive_node_ratios(
            pos, route, self.inflation_phase, budget, self.adaptive_profile
        )
        history_item["budget_fraction"] = budget
        history_item["adjusted"] = bool(adjusted)
        history_item["allocation"] = getattr(self.inflation, "last_adaptive_stats", {})
        if not adjusted:
            self._stop_adaptive_inflation("capacity_exhausted")
            return False
        if self.inflation_phase == "module":
            self.module_rounds += 1
        else:
            self.cell_rounds += 1
        self.adapter.anchor_pos = None
        self.adapter.last_route = None
        self._write_status()
        logging.info(
            "RUPlace adaptive inflation: effort=%s phase=%s target=%.2f%% "
            "predicted H/V %.3f/%.3f%% score=%.3f budget=%.3f area=%.3f",
            self.inflation_effort, self.inflation_phase, target,
            prediction["ucb_h"], prediction["ucb_v"], score, budget,
            self._current_area_growth(),
        )
        return True

    def maybe_inflate(self, pos, model):
        if self.adaptive_profile is None:
            return self._maybe_inflate_legacy(pos, model)
        return self._maybe_inflate_adaptive(pos, model)

    # ------------------------------------------------------------------
    # Congestion-driven soft blockage (per-bin capacity reduction)
    # ------------------------------------------------------------------
    def _blockage_enabled(self):
        return float(getattr(self.params, "ruplace_congestion_blockage", 0.0)) > 0.0

    def _blockage_refresh_interval(self):
        """>0 decouples the blockage refresh from the inflation schedule."""
        return int(
            getattr(
                self.params, "ruplace_congestion_blockage_refresh_interval", 0
            )
            or 0
        )

    def _blockage_interval_due(self):
        """True when the standalone schedule wants a refresh on this call."""
        interval = self._blockage_refresh_interval()
        if interval <= 0:
            return False
        if self.last_blockage_refresh_call is None:
            return True
        return (self.blockage_calls - self.last_blockage_refresh_call) >= interval

    @staticmethod
    def _density_ops(model):
        """Every density op whose fixed-density map must carry the blockage."""
        ops = []
        collections = getattr(model, "op_collections", None)
        if collections is None:
            return ops
        for name in ("density_op", "density_overflow_op"):
            op = getattr(collections, name, None)
            if op is not None and hasattr(op, "set_congestion_blockage_map"):
                ops.append(op)
        for op in getattr(collections, "fence_region_density_ops", None) or []:
            if hasattr(op, "set_congestion_blockage_map"):
                ops.append(op)
        return ops

    def _maybe_update_blockage(self, pos, model):
        """Refresh the soft-blockage map from the latest congestion map.

        Returns True when the map changed materially, which makes
        maybe_adjust_area() report an area adjustment so NonLinearPlace resets
        the density ops and re-initializes the density weight.
        """
        self.blockage_calls += 1
        if not self._blockage_enabled():
            return False
        start_overflow = float(
            getattr(self.params, "ruplace_congestion_blockage_start_overflow", 0.5)
        )
        overflow_before = self._overflow_value(getattr(model, "overflow", None))
        if overflow_before > start_overflow:
            return False
        # Optional late-GP stop: once density overflow has fallen this far the
        # placement is nearly frozen and another blockage-driven density reset
        # costs more than it buys.  0.0 (default) never stops.
        stop_overflow = float(
            getattr(self.params, "ruplace_congestion_blockage_stop_overflow", 0.0)
        )
        if stop_overflow > 0.0 and overflow_before < stop_overflow:
            return False
        # Optional budget on how many times the map may materially change.
        max_refreshes = int(
            getattr(self.params, "ruplace_congestion_blockage_max_refreshes", 0) or 0
        )
        if max_refreshes > 0 and self.blockage_refreshes >= max_refreshes:
            return False
        ops = self._density_ops(model)
        if not ops:
            return False

        # Route acquisition.  Legacy (interval 0): refresh only on calls where
        # inflation happened to route, which stops for good once the inflation
        # rounds are exhausted.  Interval > 0: refresh on the schedule, forcing
        # a router / Innovus-proxy call when inflation produced no map.
        interval = self._blockage_refresh_interval()
        route = self._last_route_for_blockage
        if interval > 0:
            if not self._blockage_interval_due():
                return False
            # mark the attempt, not the success, so a no-op refresh does not
            # re-fire on every subsequent call
            self.last_blockage_refresh_call = self.blockage_calls
            if route is None:
                logging.info(
                    "RUPlace congestion blockage: routing for the standalone "
                    "refresh schedule (call %d, interval %d, refreshes so far %d)",
                    self.blockage_calls,
                    interval,
                    self.blockage_refreshes,
                )
                route = self._inflation_route(pos, model)
        if route is None:
            return False

        blockage = float(getattr(self.params, "ruplace_congestion_blockage", 0.0))
        threshold = float(
            getattr(self.params, "ruplace_congestion_blockage_threshold", 0.7)
        )
        blockage_max = float(
            getattr(self.params, "ruplace_congestion_blockage_max", 0.5)
        )
        smooth = int(getattr(self.params, "ruplace_congestion_blockage_smooth", 1))
        decay = float(getattr(self.params, "ruplace_congestion_blockage_decay", 0.5))

        # deliberately max(util_h, util_v), independent of
        # ruplace_hv_inflate_mode: a bin is blocked if *either* direction is
        # short of tracks.  Utilization (1.0 == at capacity), not overflow.
        util = congestion_blockage.directional_utilization(
            getattr(route, "hv_utilization_map", None),
            getattr(route, "utilization_map", None),
            mode="max",
        )
        if util is None:
            logging.warning(
                "RUPlace congestion blockage: router returned no utilization map; skipped"
            )
            return False

        reference = ops[0]
        device = reference.bin_center_x.device
        dtype = reference.bin_center_x.dtype
        util = torch.nan_to_num(
            util.detach().to(device=device, dtype=dtype), nan=0.0, posinf=0.0, neginf=0.0
        )

        num_bins_x = int(reference.num_bins_x)
        num_bins_y = int(reference.num_bins_y)
        util_bins = congestion_blockage.resample_router_map(
            util,
            self.placedb.routing_grid_xl,
            self.placedb.routing_grid_yl,
            self.placedb.routing_grid_xh,
            self.placedb.routing_grid_yh,
            num_bins_x,
            num_bins_y,
            self.placedb.xl,
            self.placedb.yl,
            self.placedb.xh,
            self.placedb.yh,
        )
        extra = congestion_blockage.compute_blockage_map(
            util_bins, blockage, threshold, blockage_max, smooth
        )
        if extra is None:
            return False
        # never block capacity that fixed cells already consume
        extra = congestion_blockage.cap_by_fixed_headroom(
            extra,
            getattr(reference, "fixed_density_map", None),
            reference.capacity_per_bin(),
            blockage_max,
        )
        new_map = congestion_blockage.blend_decay(self.blockage_map, extra, decay)

        if self.blockage_map is None:
            changed = float(new_map.max()) > 1e-6
        else:
            changed = float((new_map - self.blockage_map).abs().max()) > 1e-4
        if not changed:
            return False

        self.blockage_map = new_map
        self.blockage_refreshes += 1
        for op in ops:
            if int(getattr(op, "num_bins_x", num_bins_x)) != num_bins_x or int(
                getattr(op, "num_bins_y", num_bins_y)
            ) != num_bins_y:
                logging.warning(
                    "RUPlace congestion blockage: skipping density op with %dx%d bins "
                    "(map is %dx%d)",
                    int(getattr(op, "num_bins_x", -1)),
                    int(getattr(op, "num_bins_y", -1)),
                    num_bins_x,
                    num_bins_y,
                )
                continue
            op.set_congestion_blockage_map(new_map, blockage_max)

        bin_area = float(reference.bin_size_x) * float(reference.bin_size_y)
        blocked_area = float(new_map.sum()) * bin_area
        place_area = float(self.placedb.xh - self.placedb.xl) * float(
            self.placedb.yh - self.placedb.yl
        )
        num_blocked = int((new_map > 1e-6).sum())
        logging.info(
            "RUPlace congestion blockage refresh %d: bins blocked %d/%d, "
            "extra mean/max %.4f/%.4f of bin capacity, removed area %.4E "
            "(%.3f%% of the placement region), overflow before refresh %.4f",
            self.blockage_refreshes,
            num_blocked,
            num_bins_x * num_bins_y,
            float(new_map.mean()),
            float(new_map.max()),
            blocked_area,
            100.0 * blocked_area / max(place_area, 1e-12),
            overflow_before,
        )
        # keep the filler / whitespace budget honest: the blocked area is no
        # longer available to movable cells or fillers
        self.inflation.set_blocked_area(blocked_area)
        self.inflation.rescale_fillers(pos)
        return True

    def maybe_adjust_area(self, pos, model):
        self._last_route_for_blockage = None
        inflate_flag = bool(self.maybe_inflate(pos, model))
        blockage_flag = bool(self._maybe_update_blockage(pos, model))
        return inflate_flag or blockage_flag

    def apply_admm_gradient(self, pos, model):
        if getattr(self.adapter, "external_route_eval", False):
            return
        self.grad_iteration += 1
        overflow = self._overflow_value(getattr(model, "overflow", None))
        if overflow > float(self.params.ruplace_admm_start_overflow):
            return
        apply_freq = max(1, int(getattr(self.params, "ruplace_admm_apply_freq", 1)))
        if self.grad_iteration % apply_freq != 0:
            return
        self.admm_active = True
        refresh = (
            self.adapter.last_route is None
            or self.grad_iteration % max(1, int(self.params.ruplace_admm_route_freq)) == 0
        )
        grad = self.adapter.admm_gradient(pos, refresh=refresh)
        grad = self._clip_admm_gradient(grad)
        weight = self._admm_weight()
        if pos.grad is None:
            pos.grad = torch.zeros_like(pos)
        pos.grad.add_(grad, alpha=weight)
        self.admm_applications += 1
        logging.debug("RUPlace ADMM gradient norm %.6E weight %.6E", grad.norm().item(), weight)

    def apply_gradient(self, pos, model):
        return self.apply_admm_gradient(pos, model)

    def _admm_weight(self):
        base = float(self.params.ruplace_admm_weight)
        decay = float(getattr(self.params, "ruplace_admm_weight_decay", 1.0))
        min_weight = float(getattr(self.params, "ruplace_admm_min_weight", 0.0))
        if decay <= 0.0:
            decay = 1.0
        weight = base * (decay ** max(0, self.admm_applications))
        if min_weight > 0.0:
            weight = max(weight, min_weight)
        return weight

    def _clip_admm_gradient(self, grad):
        clip_norm = float(getattr(self.params, "ruplace_admm_grad_clip_norm", 0.0))
        if clip_norm <= 0.0:
            return grad
        norm = grad.norm()
        if torch.isfinite(norm) and norm.item() > clip_norm:
            return grad * (clip_norm / norm.clamp_min(1e-12))
        return grad




# Compatibility alias for older code/tests.
RoutabilityOptOp = RUPlaceController
