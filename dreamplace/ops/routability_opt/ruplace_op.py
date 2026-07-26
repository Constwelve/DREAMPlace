##
# @file   ruplace_op.py
# @brief  RUPlace routability optimization op built on GPUGR backends.
#

import logging

import torch
import torch.nn.functional as F

from dreamplace.ops.gpugr.gpugr import build_gpugr_backend


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

    def _scale_movable_nodes(self, pos, target_ratio):
        dc = self.data_collections
        num_nodes = self.placedb.num_nodes
        num_movable = self.placedb.num_movable_nodes
        num_filler = self.placedb.num_filler_nodes
        min_ratio = float(getattr(self.params, "ruplace_min_inflate_ratio", 1.0))
        target_ratio = target_ratio.to(pos.device, dtype=pos.dtype).clamp_(
            min=min_ratio, max=float(self.params.ruplace_max_inflate_ratio)
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
                new_filler_area = torch.clamp(self.total_place_area - new_movable_area, min=0)
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

    def apply(self, pos, route, global_pass):
        util = route.utilization_map
        hv_overflow = getattr(route, "hv_overflow_map", None)
        if global_pass:
            # Convex-inflation surrogate: distribute bounded area growth by
            # cluster-level route utilization while enforcing whitespace budget.
            node_util = self._node_bin_utilization(pos, util, hv_overflow).clamp_min(1.0)
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
                desired_ratio = self._node_bin_utilization(pos, util, hv_overflow).clamp_min(1.0)
                raw_ratio = (1.0 - local_gamma) * self.current_inflate_ratio.to(
                    pos.device, dtype=pos.dtype
                ) + local_gamma * desired_ratio
            else:
                overflow = route.overflow_map
                raw_ratio = 1.0 + local_gamma * self._node_bin_utilization(pos, overflow, hv_overflow)
        return self.apply_node_ratios(pos, raw_ratio)

    def apply_node_ratios(self, pos, raw_ratio):
        """Apply externally computed cumulative area ratios with RUPlace budgets."""
        raw_ratio = torch.nan_to_num(raw_ratio, nan=1.0, posinf=1.0, neginf=1.0)
        raw_ratio.clamp_(
            min=float(getattr(self.params, "ruplace_min_inflate_ratio", 1.0)),
            max=float(self.params.ruplace_max_inflate_ratio),
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
        area_cap = float(getattr(self.params, "ruplace_inflate_area_cap", 0.1))
        max_inc = torch.minimum(whitespace, area_cap * current_movable_area)
        if grow_sum.item() > 0 and max_inc.item() <= 0:
            logging.warning("RUPlace inflation skipped: no remaining whitespace budget")
            return False
        if (grow_sum > max_inc).item():
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
        self._scale_movable_nodes(pos, target_cumulative_ratio)
        logging.info(
            "RUPlace %s inflation: area increment %.4E (%.4f), ratio avg/max %.4f/%.4f",
            "plugin",
            (final_area - old_area).sum().item(),
            ((final_area - old_area).sum() / old_area.sum()).item(),
            target_cumulative_ratio.mean().item(),
            target_cumulative_ratio.max().item(),
        )
        return True


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

    def maybe_inflate(self, pos, model):
        max_rounds = int(self.params.ruplace_local_inflate_max_rounds)
        if self.global_inflation_done and self.inflation_rounds >= max_rounds:
            return False
        if self._overflow_value(getattr(model, "overflow", None)) > self._inflate_start_overflow():
            return False

        route = self.adapter.run_route(pos)
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

    def maybe_adjust_area(self, pos, model):
        return self.maybe_inflate(pos, model)

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
