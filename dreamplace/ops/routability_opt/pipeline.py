"""Composable routability optimization pipeline."""

import logging
import math

import torch

from dreamplace.ops.routability_opt.plugin_base import PluginContext, RoutabilityPlugin
from dreamplace.ops.routability_opt.plugins import build_plugins
from dreamplace.ops.routability_opt.proxy import build_congestion_proxy


class RoutabilityOptimizationPipeline:
    def __init__(self, params, placedb, data_collections, op_collections):
        if op_collections is None:
            raise ValueError("routability plugin pipeline requires op_collections")
        self.params = params
        self.placedb = placedb
        self.data_collections = data_collections
        self.proxy = build_congestion_proxy(params, placedb, data_collections, op_collections)
        self.context = PluginContext(
            params, placedb, data_collections, op_collections, self.proxy
        )
        self.plugins = build_plugins(params, placedb, data_collections)
        if not self.plugins:
            raise ValueError("ruplace_plugins did not select any plugin")
        # Area transformations must share cumulative size state. Independent
        # engines would make a later plugin recompute from the original sizes
        # and partially overwrite an earlier plugin in the same pipeline.
        shared_area_engine = None
        for plugin in self.plugins:
            engine = getattr(plugin, "engine", None)
            if engine is None:
                continue
            if shared_area_engine is None:
                shared_area_engine = engine
            else:
                plugin.engine = shared_area_engine
        self.iteration = 0
        self.counters = {
            plugin.name: {
                "objective_attempts": 0,
                "objective_activations": 0,
                "gradient_attempts": 0,
                "gradient_activations": 0,
                "area_attempts": 0,
                "area_activations": 0,
            }
            for plugin in self.plugins
        }
        self.metric_history = {plugin.name: {} for plugin in self.plugins}
        self.gradient_calls = 0
        self.gradient_gate_skips = 0
        self.objective_calls = 0
        self.objective_gate_skips = 0
        self.area_calls = 0
        self.area_gate_skips = 0
        self.area_adjustments = 0
        self._objective_prepared = False
        logging.info(
            "RUPlace plugin pipeline: proxy=%s plugins=%s",
            getattr(params, "ruplace_proxy", "gpugr"),
            ",".join(plugin.name for plugin in self.plugins),
        )

    def _record_plugin_metrics(self, plugin):
        history = self.metric_history[plugin.name]
        for key, value in plugin.metrics.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                continue
            value = float(value)
            stats = history.setdefault(
                key,
                {
                    "count": 0,
                    "nonzero_count": 0,
                    "sum": 0.0,
                    "min": value,
                    "max": value,
                    "last": value,
                },
            )
            stats["count"] += 1
            stats["nonzero_count"] += int(value != 0.0)
            stats["sum"] += value
            stats["min"] = min(stats["min"], value)
            stats["max"] = max(stats["max"], value)
            stats["last"] = value

    @staticmethod
    def _overflow(model):
        value = getattr(model, "overflow", None)
        if value is None:
            return 1.0
        return float(value.max().item()) if torch.is_tensor(value) else float(value)

    def _begin_objective_iteration(self):
        self.iteration += 1
        self.context.begin_iteration(self.iteration)

    def prepare_objective(self, pos, model):
        self.objective_calls += 1
        self._begin_objective_iteration()
        self._objective_prepared = True
        start = float(getattr(self.params, "ruplace_plugin_start_overflow", 1.0))
        if self._overflow(model) > start:
            self.objective_gate_skips += 1
            return False
        changed = False
        for plugin in self.plugins:
            if not plugin.objective_phase_enabled():
                continue
            stats = self.counters[plugin.name]
            stats["objective_attempts"] += 1
            plugin.metrics = {}
            plugin_changed = bool(plugin.prepare_objective(pos, model, self.context))
            self._record_plugin_metrics(plugin)
            stats["objective_activations"] += int(plugin_changed)
            changed = plugin_changed or changed
        return changed

    def apply_gradient(self, pos, model):
        self.gradient_calls += 1
        if not self._objective_prepared:
            # Preserve direct callers that predate the objective-phase hook.
            self._begin_objective_iteration()
        self._objective_prepared = False
        start = float(getattr(self.params, "ruplace_plugin_start_overflow", 1.0))
        if self._overflow(model) > start:
            self.gradient_gate_skips += 1
            return False
        self.context.begin_gradient(pos)
        changed = False
        for plugin in self.plugins:
            if not plugin.gradient_phase_enabled():
                continue
            stats = self.counters[plugin.name]
            stats["gradient_attempts"] += 1
            plugin.metrics = {}
            plugin_changed = bool(plugin.apply_gradient(pos, model, self.context))
            self._record_plugin_metrics(plugin)
            stats["gradient_activations"] += int(plugin_changed)
            changed = plugin_changed or changed
        return changed

    def commit_post_gradient(self, pos, model):
        """Commit mutations that must not affect current-gradient preconditioning."""
        changed = False
        for plugin in self.plugins:
            if type(plugin).commit_post_gradient is RoutabilityPlugin.commit_post_gradient:
                continue
            changed = bool(
                plugin.commit_post_gradient(pos, model, self.context)
            ) or changed
        return changed

    def maybe_adjust_area(self, pos, model):
        self.area_calls += 1
        enforce_budget = bool(int(getattr(
            self.params, "ruplace_enforce_area_adjust_budget", 0
        )))
        max_adjustments = max(0, int(getattr(
            self.params, "max_num_area_adjust", 3
        )))
        if enforce_budget and self.area_adjustments >= max_adjustments:
            self.area_gate_skips += 1
            return False
        start = float(getattr(self.params, "ruplace_inflate_start_overflow", -1.0))
        if start < 0:
            start = float(self.params.node_area_adjust_overflow)
        if self._overflow(model) > start:
            self.area_gate_skips += 1
            return False
        self.context.begin_iteration(self.iteration)
        changed = False
        for plugin in self.plugins:
            if type(plugin).maybe_adjust_area is RoutabilityPlugin.maybe_adjust_area:
                continue
            stats = self.counters[plugin.name]
            stats["area_attempts"] += 1
            plugin.metrics = {}
            plugin_changed = bool(plugin.maybe_adjust_area(pos, model, self.context))
            self._record_plugin_metrics(plugin)
            stats["area_activations"] += int(plugin_changed)
            changed = plugin_changed or changed
            if plugin_changed:
                self.context.begin_iteration(self.iteration)
        if changed:
            self.area_adjustments += 1
            backend = getattr(self.proxy, "backend", None)
            if backend is not None:
                backend.last_route = None
                backend.anchor_pos = None
        return changed

    def metrics(self):
        plugins = {}
        for plugin in self.plugins:
            stats = dict(self.counters[plugin.name])
            stats["attempts"] = (
                stats["objective_attempts"]
                + stats["gradient_attempts"]
                + stats["area_attempts"]
            )
            stats["activations"] = (
                stats["objective_activations"]
                + stats["gradient_activations"]
                + stats["area_activations"]
            )
            stats["status"] = (
                "active" if stats["activations"]
                else "attempted_no_change" if stats["attempts"]
                else "not_reached"
            )
            stats["metrics"] = dict(plugin.metrics)
            stats["metric_stats"] = {
                key: {
                    "count": values["count"],
                    "nonzero_count": values["nonzero_count"],
                    "min": values["min"],
                    "max": values["max"],
                    "mean": values["sum"] / values["count"],
                    "last": values["last"],
                }
                for key, values in self.metric_history[plugin.name].items()
            }
            plugins[plugin.name] = stats
        return {
            "pipeline": {
                "objective_calls": self.objective_calls,
                "objective_gate_skips": self.objective_gate_skips,
                "gradient_calls": self.gradient_calls,
                "gradient_gate_skips": self.gradient_gate_skips,
                "area_calls": self.area_calls,
                "area_gate_skips": self.area_gate_skips,
                "area_adjustments": self.area_adjustments,
                "area_budget_enabled": int(bool(int(getattr(
                    self.params, "ruplace_enforce_area_adjust_budget", 0
                )))),
                "max_area_adjustments": (
                    max(0, int(getattr(self.params, "max_num_area_adjust", 3)))
                    if bool(int(getattr(
                        self.params, "ruplace_enforce_area_adjust_budget", 0
                    ))) else -1
                ),
            },
            "plugins": plugins,
        }
