"""Adaptive RUPlace inflation effort profiles and proxy calibration."""

import json
import math
import os

import torch


EFFORT_PROFILES = {
    "low": {
        "target_pct": 5.0,
        "module_rounds": 3,
        "cell_rounds": 5,
        "cumulative_area_cap": 0.35,
        "max_ratio": 3.0,
        "budget_min": 0.02,
        "budget_max": 0.15,
        "kp": 0.08,
        "ki": 0.01,
    },
    "medium": {
        "target_pct": 2.0,
        "module_rounds": 4,
        "cell_rounds": 7,
        "cumulative_area_cap": 0.60,
        "max_ratio": 4.0,
        "budget_min": 0.03,
        "budget_max": 0.25,
        "kp": 0.12,
        "ki": 0.02,
    },
    "high": {
        "target_pct": 1.0,
        "module_rounds": 5,
        "cell_rounds": 10,
        "cumulative_area_cap": 1.00,
        "max_ratio": 6.0,
        "budget_min": 0.05,
        "budget_max": 0.35,
        "kp": 0.18,
        "ki": 0.03,
    },
}


def normalize_effort(value):
    effort = str(value or "medium").strip().lower()
    if effort not in set(EFFORT_PROFILES) | {"legacy"}:
        raise ValueError(
            "ruplace_inflation_effort must be high, medium, low, or legacy; got %r"
            % value
        )
    return effort


def overflow_coverage_pct(hv_overflow_map):
    """Return H/V percentages of routing bins with positive overflow."""
    if hv_overflow_map is None or hv_overflow_map.dim() != 3 or hv_overflow_map.shape[0] < 2:
        return (float("nan"), float("nan"))
    values = []
    for direction in range(2):
        grid = torch.nan_to_num(hv_overflow_map[direction], nan=0.0, posinf=0.0, neginf=0.0)
        values.append(100.0 * float((grid > 0).sum().item()) / max(int(grid.numel()), 1))
    return tuple(values)


class MonotoneCurve(object):
    def __init__(self, knots, values, underprediction_q95=0.0):
        if len(knots) != len(values) or not knots:
            raise ValueError("calibration curve needs equal non-empty knots and values")
        pairs = sorted((float(x), float(y)) for x, y in zip(knots, values))
        self.knots = [item[0] for item in pairs]
        self.values = [item[1] for item in pairs]
        if any(self.values[index] > self.values[index + 1] for index in range(len(self.values) - 1)):
            raise ValueError("calibration curve values must be monotone")
        self.underprediction_q95 = max(float(underprediction_q95), 0.0)

    def predict(self, value):
        x = float(value)
        if not math.isfinite(x):
            return float("inf")
        if x <= self.knots[0]:
            return self.values[0]
        if x >= self.knots[-1]:
            return self.values[-1]
        for index in range(1, len(self.knots)):
            if x <= self.knots[index]:
                x0, x1 = self.knots[index - 1], self.knots[index]
                y0, y1 = self.values[index - 1], self.values[index]
                alpha = (x - x0) / max(x1 - x0, 1e-12)
                return y0 + alpha * (y1 - y0)
        return self.values[-1]

    def predict_ucb(self, value):
        return self.predict(value) + self.underprediction_q95


class InflationCalibration(object):
    def __init__(self, payload):
        self.payload = payload
        self.name = str(payload.get("name", "unknown"))
        self.valid = bool(payload.get("valid", False))
        self.curves = {}
        for proxy in ("rudy", "gpugr"):
            proxy_data = payload.get("curves", {}).get(proxy, {})
            self.curves[proxy] = {}
            for direction in ("h", "v"):
                data = proxy_data.get(direction)
                if data:
                    self.curves[proxy][direction] = MonotoneCurve(
                        data["knots"], data["values"], data.get("underprediction_q95", 0.0)
                    )

    @classmethod
    def load_default(cls):
        path = os.path.join(os.path.dirname(__file__), "calibration", "smic14_v1.json")
        with open(path) as stream:
            return cls(json.load(stream))

    def predict(self, proxy, h_value, v_value, upper=True):
        if proxy not in self.curves or not all(d in self.curves[proxy] for d in ("h", "v")):
            return (float("inf"), float("inf"))
        fn = "predict_ucb" if upper else "predict"
        return (
            getattr(self.curves[proxy]["h"], fn)(h_value),
            getattr(self.curves[proxy]["v"], fn)(v_value),
        )


def adaptive_budget(profile, error_integral, controller_score):
    error = max(float(controller_score) - 1.0, 0.0)
    raw = profile["kp"] * error + profile["ki"] * max(float(error_integral), 0.0)
    return min(max(raw, profile["budget_min"]), profile["budget_max"])
