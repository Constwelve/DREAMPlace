"""Composable routability optimization pipeline."""

import logging

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
                "gradient_attempts": 0,
                "gradient_activations": 0,
                "area_attempts": 0,
                "area_activations": 0,
            }
            for plugin in self.plugins
        }
        self.gradient_calls = 0
        self.gradient_gate_skips = 0
        self.area_calls = 0
        self.area_gate_skips = 0
        logging.info(
            "RUPlace plugin pipeline: proxy=%s plugins=%s",
            getattr(params, "ruplace_proxy", "gpugr"),
            ",".join(plugin.name for plugin in self.plugins),
        )

    @staticmethod
    def _overflow(model):
        value = getattr(model, "overflow", None)
        if value is None:
            return 1.0
        return float(value.max().item()) if torch.is_tensor(value) else float(value)

    def apply_gradient(self, pos, model):
        self.gradient_calls += 1
        self.iteration += 1
        start = float(getattr(self.params, "ruplace_plugin_start_overflow", 1.0))
        if self._overflow(model) > start:
            self.gradient_gate_skips += 1
            return False
        self.context.begin_iteration(self.iteration)
        changed = False
        for plugin in self.plugins:
            if type(plugin).apply_gradient is RoutabilityPlugin.apply_gradient:
                continue
            stats = self.counters[plugin.name]
            stats["gradient_attempts"] += 1
            plugin_changed = bool(plugin.apply_gradient(pos, model, self.context))
            stats["gradient_activations"] += int(plugin_changed)
            changed = plugin_changed or changed
        return changed

    def maybe_adjust_area(self, pos, model):
        self.area_calls += 1
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
            plugin_changed = bool(plugin.maybe_adjust_area(pos, model, self.context))
            stats["area_activations"] += int(plugin_changed)
            changed = plugin_changed or changed
            if plugin_changed:
                self.context.begin_iteration(self.iteration)
        if changed:
            backend = getattr(self.proxy, "backend", None)
            if backend is not None:
                backend.last_route = None
                backend.anchor_pos = None
        return changed

    def metrics(self):
        plugins = {}
        for plugin in self.plugins:
            stats = dict(self.counters[plugin.name])
            stats["attempts"] = stats["gradient_attempts"] + stats["area_attempts"]
            stats["activations"] = (
                stats["gradient_activations"] + stats["area_activations"]
            )
            stats["status"] = (
                "active" if stats["activations"]
                else "attempted_no_change" if stats["attempts"]
                else "not_reached"
            )
            stats["metrics"] = dict(plugin.metrics)
            plugins[plugin.name] = stats
        return {
            "pipeline": {
                "gradient_calls": self.gradient_calls,
                "gradient_gate_skips": self.gradient_gate_skips,
                "area_calls": self.area_calls,
                "area_gate_skips": self.area_gate_skips,
            },
            "plugins": plugins,
        }
