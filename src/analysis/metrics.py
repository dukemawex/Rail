"""
Safety metrics calculator.

Reads simulation result JSON files and computes summary statistics
relevant to railway safety assessments.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Safety thresholds (EN 14363 / UIC 518)
NADAL_LIMIT_DEFAULT = 0.8
MAX_ACCEPTABLE_PROBABILITY = 1e-6  # 1 per million vehicle-km (illustrative)


class MetricsCalculator:
    """
    Computes safety metrics from stored simulation results.

    Parameters
    ----------
    results_dir:
        Directory containing simulation result JSON files.
    """

    def __init__(self, results_dir: str | Path) -> None:
        self.results_dir = Path(results_dir)

    def compute_all(self) -> dict[str, Any]:
        """Compute and return all metrics as a nested dict."""
        metrics: dict[str, Any] = {}
        metrics["speed_sweep"] = self._metrics_speed_sweep()
        metrics["load_sweep"] = self._metrics_load_sweep()
        metrics["irregularity_sweep"] = self._metrics_irregularity_sweep()
        metrics["wheelset_dynamics"] = self._metrics_wheelset_dynamics()
        return metrics

    # ------------------------------------------------------------------
    # Per-scenario metrics
    # ------------------------------------------------------------------

    def _metrics_speed_sweep(self) -> dict[str, Any]:
        data = self._load("speed_sweep.json")
        if not data:
            return {}
        out: dict[str, Any] = {}
        for series_name, records in data.items():
            probs = [r["probability"] for r in records]
            speeds = [r["speed_kmh"] for r in records]
            critical_speed = _find_threshold_speed(speeds, probs, threshold=0.01)
            out[series_name] = {
                "max_probability": round(float(max(probs)), 6),
                "mean_probability": round(float(np.mean(probs)), 6),
                "critical_speed_kmh": critical_speed,
                "min_safety_margin": round(
                    float(min(r["safety_margin"] for r in records)), 4
                ),
            }
        return out

    def _metrics_load_sweep(self) -> dict[str, Any]:
        data = self._load("load_sweep.json")
        if not data:
            return {}
        out: dict[str, Any] = {}
        for series_name, records in data.items():
            probs = [r["probability"] for r in records]
            loads = [r["axle_load_kN"] for r in records]
            critical_load = _find_threshold_value(loads, probs, threshold=0.01)
            out[series_name] = {
                "max_probability": round(float(max(probs)), 6),
                "critical_load_kN": critical_load,
                "min_safety_margin": round(
                    float(min(r["safety_margin"] for r in records)), 4
                ),
            }
        return out

    def _metrics_irregularity_sweep(self) -> dict[str, Any]:
        data = self._load("irregularity_sweep.json")
        if not data:
            return {}
        out: dict[str, Any] = {}
        for series_name, records in data.items():
            probs = [r["probability"] for r in records]
            irrs = [r["irregularity_mm"] for r in records]
            critical_irr = _find_threshold_value(irrs, probs, threshold=0.01)
            out[series_name] = {
                "max_probability": round(float(max(probs)), 6),
                "critical_irregularity_mm": critical_irr,
            }
        return out

    def _metrics_wheelset_dynamics(self) -> dict[str, Any]:
        data = self._load("wheelset_dynamics.json")
        if not data:
            return {}
        out: dict[str, Any] = {}
        for series_name, record in data.items():
            lat = np.array(record.get("lateral_displacement_m", [0.0]))
            forces = np.array(record.get("lateral_force_N", [0.0]))
            out[series_name] = {
                "max_lateral_displacement_mm": round(float(np.max(np.abs(lat)) * 1000), 3),
                "rms_lateral_displacement_mm": round(
                    float(np.sqrt(np.mean(lat**2)) * 1000), 3
                ),
                "max_lateral_force_kN": round(float(np.max(np.abs(forces)) / 1000), 3),
                "derailment_quotient": round(record.get("derailment_quotient", 0.0), 4),
                "nadal_limit": round(record.get("nadal_limit", NADAL_LIMIT_DEFAULT), 4),
                "is_safe": record.get("derailment_quotient", 0.0)
                < record.get("nadal_limit", NADAL_LIMIT_DEFAULT),
            }
        return out

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _load(self, filename: str) -> dict:
        path = self.results_dir / filename
        if not path.exists():
            logger.warning("Results file not found: %s", path)
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read %s: %s", path, exc)
            return {}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _find_threshold_speed(
    speeds: list[float], probs: list[float], threshold: float
) -> float | None:
    """Return the lowest speed at which probability first exceeds *threshold*."""
    for speed, prob in zip(speeds, probs):
        if prob >= threshold:
            return round(float(speed), 1)
    return None


def _find_threshold_value(
    values: list[float], probs: list[float], threshold: float
) -> float | None:
    """Return the lowest value at which probability first exceeds *threshold*."""
    for val, prob in zip(values, probs):
        if prob >= threshold:
            return round(float(val), 2)
    return None
