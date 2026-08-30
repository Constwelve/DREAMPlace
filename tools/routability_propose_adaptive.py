#!/usr/bin/env python3
"""Propose a bounded development-only tuning pass from proxy near misses."""

import argparse
import json
import math
from pathlib import Path


WEIGHT_KEYS = {
    "local_gradient": "ruplace_local_gradient_weight",
    "net_overlap": "ruplace_net_overlap_weight",
    "poisson_force": "ruplace_poisson_weight",
    "whitespace": "ruplace_whitespace_weight",
    "net_weighting": "ruplace_net_weight_gamma",
}

MISSING_FAMILY_PLUGINS = (
    "route_inflation",
    "momentum_inflation",
    "path_inflation",
    "pin_porosity",
    "routeforce",
)

SUPPORTED_PLUGINS = tuple(sorted(set(WEIGHT_KEYS) | set(MISSING_FAMILY_PLUGINS)))

SMOOTH_KEYS = {
    "local_gradient": ("ruplace_local_gradient_smooth", 1),
    "net_overlap": ("ruplace_net_overlap_smooth", 2),
    "poisson_force": ("ruplace_poisson_smooth", 1),
    "whitespace": ("ruplace_whitespace_radius", 5),
}

ABSOLUTE_DIRECTIONAL_MODES = (
    "utilization_hv_max",
    "utilization_hv_mean",
    "utilization_horizontal",
    "utilization_vertical",
)

AREA_DIRECTIONAL_MODES = ("max", "mean", "h", "v")

# RUPlaceInflation ignores cumulative area changes below this relative value.
# Policy v7 samples immediately above the implementation boundary so gentle
# variants remain observable instead of collapsing into selected no-ops.
AREA_EFFECT_FLOOR = 1e-4


def _unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _interval_variants(value, maximum=160):
    value = max(1, int(value))
    return [
        candidate for candidate in _unique([
            max(1, value // 2), min(maximum, value * 2),
            min(maximum, value * 4),
        ])
        if candidate != value
    ]


def _effective_refresh_interval(refresh_interval, application_interval):
    """Return the refresh cadence observable at application iterations."""
    refresh_interval = max(1, int(refresh_interval))
    application_interval = max(1, int(application_interval))
    return (
        refresh_interval * application_interval
        // math.gcd(refresh_interval, application_interval)
    )


def _refresh_variants(refresh_interval, application_interval, maximum=160):
    """Return distinct effective refresh cadences at application iterations."""
    refresh_interval = max(1, int(refresh_interval))
    application_interval = max(1, int(application_interval))
    current_effective = _effective_refresh_interval(
        refresh_interval, application_interval
    )
    candidates = _interval_variants(refresh_interval, maximum=maximum)
    candidates.extend([
        min(maximum, application_interval * 2),
        min(maximum, application_interval * 4),
    ])
    effective = []
    for value in candidates:
        value = _effective_refresh_interval(value, application_interval)
        if (
            value <= application_interval
            or value > maximum
            or value == current_effective
            or value in effective
        ):
            continue
        effective.append(value)
    return effective


def _balanced_changes(changes):
    """Round-robin tuning dimensions so bounded grids retain joint variants."""
    groups = {}
    order = []
    for change in changes:
        label, updates = change
        direction_mode = updates.get("ruplace_force_congestion_mode")
        # Each absolute H/V mode is a distinct required dimension. Grouping all
        # direction variants together allowed a 16-candidate bound to retain
        # only the first mode while still claiming directional coverage.
        category = (
            "direction:%s" % direction_mode
            if direction_mode in ABSOLUTE_DIRECTIONAL_MODES
            else label.split("_", 1)[0]
        )
        if category not in groups:
            groups[category] = []
            order.append(category)
        groups[category].append(change)
    result = []
    depth = 0
    while True:
        added = False
        for category in order:
            values = groups[category]
            if depth < len(values):
                result.append(values[depth])
                added = True
        if not added:
            return result
        depth += 1


def _frontier_candidates(frontier, backend_names):
    cross = frontier.get("cross_backend_frontier_intersection", {})
    candidates = list(cross.get("mean", []))
    candidates.extend(cross.get("worst", []))
    if not candidates:
        for backend in backend_names:
            backend_data = frontier.get("backends", {}).get(backend, {})
            candidates.extend(backend_data.get("mean_pareto_frontier", []))
            candidates.extend(backend_data.get("worst_pareto_frontier", []))
    return _unique(candidates)


def _parent_names(analysis, max_parents):
    backend_names = sorted(analysis["backends"])
    mean_intersection = set(
        analysis["cross_backend_frontier_intersection"]["mean"]
    )
    worst_intersection = set(
        analysis["cross_backend_frontier_intersection"]["worst"]
    )
    mean_union = set()
    worst_union = set()
    for backend in backend_names:
        row = analysis["backends"][backend]
        mean_union.update(row["mean_pareto_frontier"])
        worst_union.update(row["worst_pareto_frontier"])
    preferred = mean_intersection | worst_intersection
    if not preferred:
        competitive = [
            set(analysis["backends"][backend]["mean_pareto_frontier"])
            | set(analysis["backends"][backend]["worst_pareto_frontier"])
            for backend in backend_names
        ]
        preferred = set.intersection(*competitive) if competitive else set()
    if not preferred:
        preferred = mean_union | worst_union

    def rank(method):
        return (
            method not in mean_intersection,
            method not in worst_intersection,
            method not in mean_union,
            method not in worst_union,
            method,
        )

    records = {
        row["method"]: row for row in analysis.get("methods", [])
        if row.get("eligible") and len(row.get("plugins", [])) == 1
    }
    coverage = []
    proxy_frontiers = analysis.get("plugin_proxy_frontiers", {})
    if proxy_frontiers:
        for plugin in SUPPORTED_PLUGINS:
            for feedback_proxy, group in sorted(
                proxy_frontiers.get(plugin, {}).items()
            ):
                candidates = [
                    method for method in _frontier_candidates(group, backend_names)
                    if records.get(method, {}).get("plugins") == [plugin]
                    and records.get(method, {}).get("feedback_proxy")
                    == feedback_proxy
                ]
                if candidates:
                    coverage.append(min(candidates, key=rank))
    else:
        for plugin in SUPPORTED_PLUGINS:
            plugin_data = analysis.get("plugin_frontiers", {}).get(plugin, {})
            candidates = [
                method for method in _frontier_candidates(
                    plugin_data, backend_names
                )
                if records.get(method, {}).get("plugins") == [plugin]
            ]
            if candidates:
                coverage.append(min(candidates, key=rank))
    ordered = coverage + sorted(preferred, key=rank)
    ordered.extend(sorted((mean_union | worst_union), key=rank))
    ordered = _unique(ordered)
    return ordered[:max_parents]


def _force_changes(plugin, config, proposal_policy_version=6):
    weight_key = WEIGHT_KEYS[plugin]
    weight = float(config[weight_key])
    apply_interval = int(config.get("ruplace_force_apply_interval", 1))
    refresh_interval = int(config.get("ruplace_proxy_refresh_interval", 20))
    start = float(config.get("ruplace_plugin_start_overflow", 1.0))
    decay = float(config.get("ruplace_force_decay", 1.0))
    minimum = float(config.get("ruplace_force_min_ratio", 0.0))
    max_ratio = float(config.get("ruplace_force_max_ratio", 0.25))
    changes = []
    for factor in (0.0625, 0.125, 0.25, 0.5, 2.0):
        changes.append(("strength_x%g" % factor, {weight_key: weight * factor}))
    for value in _unique([0.4, 0.6, 0.8, 1.0]):
        if value != start:
            changes.append(("start_%g" % value, {
                "ruplace_plugin_start_overflow": value,
            }))
    for value in _interval_variants(apply_interval):
        changes.append(("apply_%d" % value, {
            "ruplace_force_apply_interval": value,
        }))
    for value in _refresh_variants(refresh_interval, apply_interval):
        changes.append(("refresh_%d" % value, {
            "ruplace_proxy_refresh_interval": value,
        }))
    for value in (0.9, 0.95, 0.99, 0.999):
        if value != decay:
            changes.append(("decay_%g" % value, {"ruplace_force_decay": value}))
    # Floors near one bind within tens of applications; 0.05/0.1 generally do
    # not bind for the tested 0.99x decay schedules and only duplicate runs.
    for value in (0.8, 0.9, 0.95):
        if value != minimum:
            changes.append(("minimum_%g" % value, {
                "ruplace_force_min_ratio": value,
            }))
    scale_mode = str(config.get("ruplace_force_scale_mode", "absolute")).lower()
    if scale_mode in ("relative", "gradient_relative"):
        effective_cap = min(weight, max_ratio)
        for value in (effective_cap * 0.25, effective_cap * 0.5):
            if value != max_ratio and value < weight:
                changes.append(("trust_%g" % value, {
                    "ruplace_force_max_ratio": value,
                }))
    smooth_key, smooth_default = SMOOTH_KEYS[plugin]
    smooth = int(config.get(smooth_key, smooth_default))
    for value in _unique([max(0, smooth - 1), smooth + 1, smooth * 2]):
        if value != smooth:
            changes.append(("smooth_%d" % value, {smooth_key: value}))
    feedback_proxy = str(config.get("ruplace_proxy", "")).lower()
    if feedback_proxy == "gpugr":
        direction = str(config.get(
            "ruplace_force_congestion_mode", "aggregate"
        )).lower()
        # Put absolute-utilization variants first so the bounded balanced grid
        # cannot silently retain only thresholded-overflow feedback.
        for value in (
            *ABSOLUTE_DIRECTIONAL_MODES,
            "hv_max", "hv_mean", "horizontal", "vertical",
            "aggregate", "utilization",
        ):
            if value != direction:
                changes.append(("direction_%s" % value, {
                    "ruplace_force_congestion_mode": value,
                }))
    elif proposal_policy_version >= 8 and feedback_proxy == "rudy":
        direction = str(config.get(
            "ruplace_force_congestion_mode", "aggregate"
        )).lower()
        for value in ("utilization", "aggregate"):
            if value != direction:
                changes.append(("direction_%s" % value, {
                    "ruplace_force_congestion_mode": value,
                }))
    if proposal_policy_version >= 8 and plugin == "poisson_force":
        solver = str(config.get(
            "ruplace_poisson_solver", "periodic"
        )).lower()
        solver = "neumann_dct" if solver in ("neumann", "dct") else solver
        for value in ("neumann_dct", "periodic"):
            if value != solver:
                changes.append(("solver_%s" % value, {
                    "ruplace_poisson_solver": value,
                }))
    changes = [
        ("joint_gentle", {
            weight_key: weight * 0.25,
            "ruplace_plugin_start_overflow": min(start, 0.4),
            "ruplace_force_apply_interval": min(160, apply_interval * 4),
            "ruplace_proxy_refresh_interval": min(
                160, max(refresh_interval * 4, apply_interval * 4)
            ),
            "ruplace_force_decay": min(decay, 0.95),
            "ruplace_force_min_ratio": 0.0,
            **({
                "ruplace_force_max_ratio": min(max_ratio, weight * 0.25),
            } if scale_mode in ("relative", "gradient_relative") else {}),
        }),
        ("joint_frequent_small", {
            weight_key: weight * 0.0625,
            "ruplace_force_apply_interval": max(1, apply_interval // 2),
            "ruplace_proxy_refresh_interval": max(
                refresh_interval, max(1, apply_interval // 2)
            ),
            "ruplace_force_decay": min(decay, 0.99),
            "ruplace_force_min_ratio": 0.0,
            **({
                "ruplace_force_max_ratio": min(max_ratio, weight * 0.0625),
            } if scale_mode in ("relative", "gradient_relative") else {}),
        }),
    ] + changes
    return _balanced_changes(changes)


def _net_weight_changes(config):
    gamma = float(config["ruplace_net_weight_gamma"])
    frequency = int(config.get("ruplace_net_weight_freq", 20))
    refresh = int(config.get("ruplace_proxy_refresh_interval", frequency))
    start = float(config.get("ruplace_plugin_start_overflow", 1.0))
    normalization = config.get("ruplace_net_weight_normalization", "absolute")
    maximum = float(config.get("ruplace_net_weight_max", 3.0))
    phase = str(config.get("ruplace_net_weight_phase", "post_gradient")).lower()
    if phase not in ("pre_objective", "post_gradient"):
        raise ValueError("unsupported ruplace_net_weight_phase: %s" % phase)
    alternate_phase = (
        "post_gradient" if phase == "pre_objective" else "pre_objective"
    )
    changes = []
    for factor in (0.0625, 0.125, 0.25, 0.5, 2.0):
        changes.append(("gamma_x%g" % factor, {
            "ruplace_net_weight_gamma": gamma * factor,
        }))
    for value in _interval_variants(frequency):
        changes.append(("frequency_%d" % value, {
            "ruplace_net_weight_freq": value,
        }))
    for value in _refresh_variants(refresh, frequency):
        changes.append(("refresh_%d" % value, {
            "ruplace_proxy_refresh_interval": value,
        }))
    for value in _unique([0.4, 0.6, 0.8, 1.0]):
        if value != start:
            changes.append(("start_%g" % value, {
                "ruplace_plugin_start_overflow": value,
            }))
    for value in (1.25, 1.5, 2.0, 3.0):
        if value != maximum:
            changes.append(("maximum_%g" % value, {
                "ruplace_net_weight_max": value,
            }))
    other_normalization = (
        "design_mean" if normalization == "absolute" else "absolute"
    )
    changes.append(("normalization_%s" % other_normalization, {
        "ruplace_net_weight_normalization": other_normalization,
    }))
    changes.append(("phase_%s" % alternate_phase, {
        "ruplace_net_weight_phase": alternate_phase,
    }))
    changes = [
        ("joint_gentle", {
            "ruplace_net_weight_gamma": gamma * 0.25,
            "ruplace_net_weight_freq": min(160, frequency * 4),
            "ruplace_proxy_refresh_interval": min(
                160, max(refresh * 4, frequency * 4)
            ),
            "ruplace_plugin_start_overflow": min(start, 0.4),
            "ruplace_net_weight_max": min(maximum, 1.25),
        }),
        ("joint_alternate_phase_gentle", {
            "ruplace_net_weight_gamma": gamma * 0.125,
            "ruplace_net_weight_normalization": "design_mean",
            "ruplace_net_weight_max": min(maximum, 1.25),
            "ruplace_net_weight_phase": alternate_phase,
        }),
    ] + changes
    return _balanced_changes(changes)


def _scaled_updates(config, keys, factor):
    return {
        key: float(config[key]) * factor
        for key in keys if key in config and float(config[key]) != 0.0
    }


def _area_schedule_changes(config, strength_keys, rounds_key):
    start = float(config.get("ruplace_inflate_start_overflow", 0.8))
    area_cap = float(config.get("ruplace_inflate_area_cap", 0.1))
    rounds = max(1, int(config.get(rounds_key, 1)))
    area_adjustments = max(1, int(config.get("max_num_area_adjust", rounds)))
    changes = [
        ("joint_gentle", {
            **_scaled_updates(config, strength_keys, 0.25),
            "ruplace_inflate_area_cap": area_cap * 0.25,
            rounds_key: 1,
            "max_num_area_adjust": 1,
            "ruplace_inflate_start_overflow": min(start, 0.4),
        }),
        ("joint_early_gentle", {
            **_scaled_updates(config, strength_keys, 0.125),
            "ruplace_inflate_area_cap": area_cap * 0.125,
            rounds_key: 1,
            "max_num_area_adjust": 1,
            "ruplace_inflate_start_overflow": max(start, 0.8),
        }),
    ]
    for factor in (0.0625, 0.125, 0.25, 0.5, 2.0):
        updates = _scaled_updates(config, strength_keys, factor)
        if updates:
            changes.append(("strength_x%g" % factor, updates))
    for factor in (0.125, 0.25, 0.5, 2.0):
        changes.append(("area_x%g" % factor, {
            "ruplace_inflate_area_cap": area_cap * factor,
        }))
    for value in (0.3, 0.5, 0.8, 1.0):
        if value != start:
            changes.append(("start_%g" % value, {
                "ruplace_inflate_start_overflow": value,
            }))
    for value in _unique([1, 2, 4, max(1, rounds // 2)]):
        if value != rounds:
            changes.append(("rounds_%d" % value, {rounds_key: value}))
    for value in _unique([1, 2, 4, max(1, area_adjustments // 2)]):
        if value != area_adjustments:
            changes.append(("adjustments_%d" % value, {
                "max_num_area_adjust": value,
            }))
    return changes


def _coordinated_area_changes(config, strength_keys, rounds_key,
                              plugin_changes=()):
    """Tune coupled area controls without generating dormant one-key rows."""
    start = float(config.get("ruplace_inflate_start_overflow", 0.8))

    def make(label, cap, factor, rounds=1, threshold=1.0, extra=None):
        updates = {
            **_scaled_updates(config, strength_keys, factor),
            "ruplace_inflate_area_cap": float(cap),
            rounds_key: int(rounds),
            "max_num_area_adjust": int(rounds),
            "ruplace_enforce_area_adjust_budget": 1,
            "ruplace_inflate_start_overflow": float(threshold),
        }
        updates.update(extra or {})
        return label, updates

    # Caps are absolute relative-area budgets. The smallest one is 25% above
    # the implementation effect floor; larger values remain much gentler than
    # the 0.25%-0.5% cap-limited parents observed in policy v6.
    changes = [
        make("joint_floor_early", 1.25e-4, 1.0, threshold=1.0),
        make("joint_floor_h08", 1.25e-4, 1.0, threshold=max(start, 0.8)),
        make("joint_cap_2e4", 2.0e-4, 1.0, threshold=1.0),
        make("joint_cap_3e4", 3.0e-4, 1.0, threshold=1.0),
        make("joint_cap_5e4", 5.0e-4, 1.0, threshold=1.0),
        make("joint_cap_7p5e4", 7.5e-4, 1.0, threshold=1.0),
        make("joint_cap_1e3", 1.0e-3, 1.0, threshold=1.0),
        make("joint_strength_x0.03125", 2.0e-4, 0.03125, threshold=1.0),
        make("joint_strength_x0.0625", 2.0e-4, 0.0625, threshold=1.0),
        make("joint_strength_x0.125", 2.0e-4, 0.125, threshold=1.0),
        make("joint_two_round_floor", 1.25e-4, 0.25, rounds=2, threshold=1.0),
        make("joint_two_round_cap_2e4", 2.0e-4, 0.125, rounds=2, threshold=1.0),
    ]
    for label, extra in plugin_changes:
        changes.append(make(
            "joint_%s" % label, 2.0e-4, 0.125, threshold=1.0,
            extra=extra,
        ))
    changes.extend([
        make("joint_four_round_floor", 1.25e-4, 0.125,
             rounds=4, threshold=1.0),
        make("joint_four_round_cap_2e4", 2.0e-4, 0.0625,
             rounds=4, threshold=1.0),
        make("joint_start_0.9", 2.0e-4, 0.25, threshold=0.9),
        make("joint_strength_x0.25", 3.0e-4, 0.25, threshold=1.0),
        make("joint_strength_x0.5", 5.0e-4, 0.5, threshold=1.0),
    ])
    return changes


def _coordinated_route_inflation_changes(config):
    window = int(config.get("ruplace_node_util_window", 0))
    global_gamma = float(config.get("ruplace_global_inflate_gamma", 0.1))
    hv_gamma = float(config.get("ruplace_hv_inflate_gamma", 0.0))
    # The selected global-only parent has no directional term. Reserve the four
    # bounded plugin-specific slots for explicit H/V behavior instead of merely
    # scaling the parent's zero value. Window-only variants were already covered
    # by policy v6 and cannot exercise directional feedback.
    directional_gamma = max(hv_gamma * 0.125, global_gamma * 0.125, 1e-4)
    extras = [
        ("hv_%s" % mode, {
            "ruplace_hv_inflate_gamma": directional_gamma,
            "ruplace_hv_inflate_mode": mode,
        })
        for mode in AREA_DIRECTIONAL_MODES
    ]
    extras.extend([
        ("window_%d" % value, {"ruplace_node_util_window": value})
        for value in (0, 1, 2, 4) if value != window
    ])
    changes = _coordinated_area_changes(
        config,
        (
            "ruplace_global_inflate_gamma",
            "ruplace_local_inflate_gamma",
            "ruplace_hv_inflate_gamma",
        ),
        "ruplace_local_inflate_max_rounds",
        extras,
    )
    # Route inflation defines its round knob as the number of local passes after
    # a mandatory global pass. The pipeline budget counts successful adjustment
    # rounds in total, so reserve one additional slot for that global pass.
    for _, updates in changes:
        updates["max_num_area_adjust"] = (
            int(updates["ruplace_local_inflate_max_rounds"]) + 1
        )
    return changes


def _coordinated_momentum_changes(config):
    beta = float(config.get("ruplace_momentum_beta", 0.8))
    extras = [
        ("beta_%g" % value, {"ruplace_momentum_beta": value})
        for value in (0.25, 0.5, 0.8, 0.95) if value != beta
    ]
    return _coordinated_area_changes(
        config, ("ruplace_momentum_step",), "ruplace_momentum_rounds",
        extras,
    )


def _coordinated_path_inflation_changes(config):
    return _coordinated_area_changes(
        config, ("ruplace_path_inflate_gamma",),
        "ruplace_path_inflate_rounds",
    )


def _coordinated_pin_porosity_changes(config):
    radius = max(0, int(config.get("ruplace_porosity_radius", 3)))
    extras = [
        ("radius_%d" % value, {"ruplace_porosity_radius": value})
        for value in (0, 1, 3, 5) if value != radius
    ]
    porosity = float(config.get("ruplace_porosity_weight", 0.25))
    extras.extend([
        ("porosity_%g" % value, {"ruplace_porosity_weight": value})
        for value in (0.05, 0.1, 0.25) if value != porosity
    ])
    return _coordinated_area_changes(
        config,
        ("ruplace_pin_porosity_gamma", "ruplace_porosity_weight"),
        "ruplace_pin_porosity_rounds",
        extras,
    )


def _route_inflation_changes(config):
    strength_keys = (
        "ruplace_global_inflate_gamma",
        "ruplace_local_inflate_gamma",
        "ruplace_hv_inflate_gamma",
    )
    changes = _area_schedule_changes(
        config, strength_keys, "ruplace_local_inflate_max_rounds"
    )
    window = int(config.get("ruplace_node_util_window", 0))
    for value in (0, 1, 2, 4):
        if value != window:
            changes.append(("window_%d" % value, {
                "ruplace_node_util_window": value,
            }))
    return _balanced_changes(changes)


def _momentum_changes(config):
    changes = _area_schedule_changes(
        config, ("ruplace_momentum_step",), "ruplace_momentum_rounds"
    )
    beta = float(config.get("ruplace_momentum_beta", 0.8))
    for value in (0.25, 0.5, 0.8, 0.95):
        if value != beta:
            changes.append(("beta_%g" % value, {
                "ruplace_momentum_beta": value,
            }))
    return _balanced_changes(changes)


def _path_inflation_changes(config):
    return _balanced_changes(_area_schedule_changes(
        config, ("ruplace_path_inflate_gamma",), "ruplace_path_inflate_rounds"
    ))


def _pin_porosity_changes(config):
    strength_keys = ("ruplace_pin_porosity_gamma", "ruplace_porosity_weight")
    changes = _area_schedule_changes(
        config, strength_keys, "ruplace_pin_porosity_rounds"
    )
    radius = max(0, int(config.get("ruplace_porosity_radius", 3)))
    for value in _unique([0, 1, 3, 5, max(0, radius // 2)]):
        if value != radius:
            changes.append(("radius_%d" % value, {
                "ruplace_porosity_radius": value,
            }))
    porosity = float(config.get("ruplace_porosity_weight", 0.25))
    for value in (0.0, 0.05, 0.1, 0.25, 0.5):
        if value != porosity:
            changes.append(("porosity_%g" % value, {
                "ruplace_porosity_weight": value,
            }))
    return _balanced_changes(changes)


def _routeforce_changes(config):
    weight = float(config.get("ruplace_admm_weight", 0.01))
    max_ratio = float(config.get("ruplace_admm_max_ratio", 0.25))
    apply_frequency = max(1, int(config.get("ruplace_admm_apply_freq", 1)))
    route_frequency = max(1, int(config.get("ruplace_admm_route_freq", 20)))
    start = float(config.get("ruplace_plugin_start_overflow", 1.0))
    decay = float(config.get("ruplace_admm_weight_decay", 1.0))
    changes = [
        ("joint_gentle", {
            "ruplace_admm_weight": weight * 0.125,
            "ruplace_admm_max_ratio": min(max_ratio, weight * 0.125),
            "ruplace_admm_apply_freq": min(320, apply_frequency * 4),
            "ruplace_admm_route_freq": min(320, route_frequency * 4),
            "ruplace_admm_weight_decay": min(decay, 0.95),
            "ruplace_admm_min_weight": 0.0,
            "ruplace_plugin_start_overflow": min(start, 0.4),
        }),
        ("joint_early_gentle", {
            "ruplace_admm_weight": weight * 0.0625,
            "ruplace_admm_max_ratio": min(max_ratio, weight * 0.0625),
            "ruplace_admm_apply_freq": min(320, apply_frequency * 4),
            "ruplace_admm_route_freq": min(320, route_frequency * 4),
            "ruplace_admm_weight_decay": min(decay, 0.99),
            "ruplace_admm_min_weight": 0.0,
            "ruplace_plugin_start_overflow": max(start, 0.8),
        }),
    ]
    for factor in (0.03125, 0.0625, 0.125, 0.25, 0.5, 2.0):
        changes.append(("strength_x%g" % factor, {
            "ruplace_admm_weight": weight * factor,
        }))
    for value in _interval_variants(apply_frequency, maximum=320):
        changes.append(("apply_%d" % value, {
            "ruplace_admm_apply_freq": value,
        }))
    for value in _refresh_variants(
        route_frequency, apply_frequency, maximum=320
    ):
        changes.append(("route_%d" % value, {
            "ruplace_admm_route_freq": value,
        }))
    for value in (0.3, 0.5, 0.8, 1.0):
        if value != start:
            changes.append(("start_%g" % value, {
                "ruplace_plugin_start_overflow": value,
            }))
    for value in (0.9, 0.95, 0.99, 0.999):
        if value != decay:
            changes.append(("decay_%g" % value, {
                "ruplace_admm_weight_decay": value,
            }))
    for factor in (0.125, 0.25, 0.5):
        value = min(max_ratio, weight * factor)
        if value != max_ratio:
            changes.append(("trust_%g" % value, {
                "ruplace_admm_max_ratio": value,
            }))
    return _balanced_changes(changes)


ADAPTIVE_CHANGE_GENERATORS = {
    "route_inflation": _route_inflation_changes,
    "momentum_inflation": _momentum_changes,
    "path_inflation": _path_inflation_changes,
    "pin_porosity": _pin_porosity_changes,
    "routeforce": _routeforce_changes,
}

COORDINATED_AREA_CHANGE_GENERATORS = {
    "route_inflation": _coordinated_route_inflation_changes,
    "momentum_inflation": _coordinated_momentum_changes,
    "path_inflation": _coordinated_path_inflation_changes,
    "pin_porosity": _coordinated_pin_porosity_changes,
}


def propose_adaptive(analysis, presets, manifest, max_parents=8,
                     max_variants_per_parent=16, proposal_policy_version=6):
    if proposal_policy_version not in (6, 7, 8):
        raise ValueError("proposal policy version must be 6, 7, or 8")
    policy = analysis.get("policy", {})
    if policy.get("numeric_backend_mixing") is not False:
        raise ValueError("near-miss analysis must prohibit backend mixing")
    if policy.get("selection_or_admission_decision") is not False:
        raise ValueError("near-miss input must be diagnostic-only")
    if policy.get("metric_profile") != "absolute_directional_v2":
        raise ValueError("near-miss analysis must use absolute_directional_v2")
    if int(analysis.get("expected_comparisons", 0)) != 6:
        raise ValueError("near-miss analysis must cover six development comparisons")
    if not isinstance(analysis.get("plugin_frontiers"), dict):
        raise ValueError("near-miss analysis lacks plugin-local Pareto frontiers")
    if not isinstance(analysis.get("plugin_proxy_frontiers"), dict):
        raise ValueError(
            "near-miss analysis lacks plugin-and-feedback-proxy Pareto frontiers"
        )
    generated_provenance = manifest.get("generated", {})
    analysis_records = {
        row["method"]: row for row in analysis.get("methods", [])
    }
    parents = _parent_names(analysis, max_parents)
    if not parents:
        raise ValueError("near-miss analysis contains no competitive parents")

    output = {"hpwl": dict(presets["hpwl"])}
    generated = {}
    signatures = set()
    index = 0
    used_parents = []
    for parent in parents:
        if parent not in presets or parent not in generated_provenance:
            raise ValueError("competitive parent lacks preset provenance: %s" % parent)
        provenance = generated_provenance[parent]
        plugins = provenance.get("plugins", [])
        if len(plugins) != 1:
            continue
        plugin = plugins[0]
        if plugin not in SUPPORTED_PLUGINS:
            continue
        if analysis_records.get(parent, {}).get("plugins") != plugins:
            raise ValueError("near-miss and preset plugin provenance differ: %s" % parent)
        if (
            analysis_records.get(parent, {}).get("feedback_proxy")
            != provenance.get("proxy")
        ):
            raise ValueError(
                "near-miss and preset feedback provenance differ: %s" % parent
            )
        config = dict(presets[parent])
        if plugin == "net_weighting":
            if WEIGHT_KEYS[plugin] not in config:
                continue
            changes = _net_weight_changes(config)
        elif plugin in WEIGHT_KEYS:
            if WEIGHT_KEYS[plugin] not in config:
                continue
            changes = _force_changes(
                plugin, config,
                proposal_policy_version=proposal_policy_version,
            )
        elif (
            proposal_policy_version >= 7
            and plugin in COORDINATED_AREA_CHANGE_GENERATORS
        ):
            changes = COORDINATED_AREA_CHANGE_GENERATORS[plugin](config)
        else:
            changes = ADAPTIVE_CHANGE_GENERATORS[plugin](config)
        used_parents.append(parent)
        parent_count = 0
        for label, updates in changes:
            candidate = dict(config)
            candidate.update(updates)
            signature = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            if signature in signatures:
                continue
            signatures.add(signature)
            name = "adaptive_dev_%04d_%s_%s" % (index, plugin, label)
            output[name] = candidate
            generated[name] = {
                "plugins": [plugin],
                "proxy": candidate["ruplace_proxy"],
                "parent": parent,
                "change": label,
                "updates": updates,
                "development_only": True,
                "proposal_policy_version": proposal_policy_version,
            }
            index += 1
            parent_count += 1
            if parent_count >= max_variants_per_parent:
                break
    if not generated:
        raise ValueError("competitive parents produced no supported variants")
    used_plugins = sorted({row["plugins"][0] for row in generated.values()})
    tuned_keys = sorted({
        key for row in generated.values() for key in row["updates"]
    })
    tuned_absolute_directional_modes = [
        mode for mode in ABSOLUTE_DIRECTIONAL_MODES
        if any(
            row["updates"].get("ruplace_force_congestion_mode") == mode
            for row in generated.values()
        )
    ]
    tuned_area_directional_modes = [
        mode for mode in AREA_DIRECTIONAL_MODES
        if any(
            row["updates"].get("ruplace_hv_inflate_mode") == mode
            and float(row["updates"].get("ruplace_hv_inflate_gamma", 0.0)) > 0.0
            for row in generated.values()
        )
    ]
    metadata = {
        "proposal_policy_version": proposal_policy_version,
        "source_expected_comparisons": analysis["expected_comparisons"],
        "numeric_backend_mixing": False,
        "heldout_or_golden_evidence_used": False,
        "atomic_plugins_only": True,
        "balanced_tuning_dimensions": True,
        "effective_refresh_cadences_only": True,
        "effective_refresh_cadence_definition": (
            "lcm(refresh_interval,application_interval)"
        ),
        "joint_variants_prioritized": True,
        "coordinated_area_controls_tuned": (
            proposal_policy_version >= 7
            and bool(set(used_plugins) & set(COORDINATED_AREA_CHANGE_GENERATORS))
        ),
        "area_effect_floor": (
            AREA_EFFECT_FLOOR if proposal_policy_version >= 7 else None
        ),
        "dormant_single_parameter_area_variants": (
            proposal_policy_version < 7
        ),
        "net_weight_lifecycle_tuned": (
            "net_weighting" in used_plugins
            and "ruplace_net_weight_phase" in tuned_keys
        ),
        "directional_feedback_tuned": (
            "ruplace_force_congestion_mode" in tuned_keys
        ),
        "absolute_directional_feedback_tuned": (
            tuple(tuned_absolute_directional_modes)
            == ABSOLUTE_DIRECTIONAL_MODES
        ),
        "absolute_directional_feedback_modes": tuned_absolute_directional_modes,
        "continuous_rudy_feedback_tuned": any(
            row["proxy"] == "rudy"
            and row["updates"].get("ruplace_force_congestion_mode")
            == "utilization"
            for row in generated.values()
        ),
        "poisson_boundary_solver_tuned": any(
            "ruplace_poisson_solver" in row["updates"]
            for row in generated.values()
        ),
        "directional_area_feedback_tuned": (
            tuple(tuned_area_directional_modes) == AREA_DIRECTIONAL_MODES
        ),
        "directional_area_feedback_modes": tuned_area_directional_modes,
        "used_plugins": used_plugins,
        "missing_family_adaptive_tuning": sorted(
            set(used_plugins) & set(MISSING_FAMILY_PLUGINS)
        ),
        "used_plugin_feedback_groups": sorted({
            "%s:%s" % (row["plugins"][0], row["proxy"])
            for row in generated.values()
        }),
        "tuned_parameter_keys": tuned_keys,
        "parent_policy": (
            "per-plugin and placement-feedback-proxy coverage followed by "
            "backend-local mean and worst Pareto set membership without "
            "cross-backend scalarization"
        ),
        "competitive_parents": parents,
        "used_parents": used_parents,
        "generated_count": len(generated),
    }
    return output, generated, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--presets", type=Path, required=True)
    parser.add_argument("--preset-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-parents", type=int, default=8)
    parser.add_argument("--max-variants-per-parent", type=int, default=16)
    parser.add_argument(
        "--proposal-policy-version", type=int, choices=(6, 7, 8), default=6,
    )
    args = parser.parse_args(argv)
    if args.max_parents <= 0 or args.max_variants_per_parent <= 0:
        raise ValueError("proposal bounds must be positive")

    presets, generated, metadata = propose_adaptive(
        json.loads(args.analysis.read_text()),
        json.loads(args.presets.read_text()),
        json.loads(args.preset_manifest.read_text()),
        max_parents=args.max_parents,
        max_variants_per_parent=args.max_variants_per_parent,
        proposal_policy_version=args.proposal_policy_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(presets, indent=2, sort_keys=True) + "\n")
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps({
        "analysis": str(args.analysis.resolve()),
        "source_presets": str(args.presets.resolve()),
        "source_manifest": str(args.preset_manifest.resolve()),
        "metadata": metadata,
        "generated": generated,
    }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
