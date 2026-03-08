"""
Scenario runner: orchestrates all simulation scenarios and persists results.

Each scenario is a named study combining a parameter sweep with post-
processing into JSON-serialisable results files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from src.simulations.derailment_probability import DerailmentProbabilityModel
from src.simulations.wheel_rail_dynamics import (
    WheelRailParams,
    derailment_quotient,
    nadal_limit,
    simulate_wheelset_dynamics,
)

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """
    Executes predefined simulation scenarios and writes results to disk.

    Parameters
    ----------
    output_dir:
        Directory where JSON result files are written.
    seed:
        Random seed for reproducible simulations.
    """

    def __init__(self, output_dir: str | Path = "data/simulation_results", seed: int = 42) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.seed = seed

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_all(self) -> list[str]:
        """Execute every scenario and return a list of output file paths."""
        scenarios = [
            ("speed_sweep", self._scenario_speed_sweep),
            ("load_sweep", self._scenario_load_sweep),
            ("irregularity_sweep", self._scenario_irregularity_sweep),
            ("combined_risk_surface", self._scenario_combined_risk_surface),
            ("wheelset_dynamics", self._scenario_wheelset_dynamics),
        ]

        artifacts: list[str] = []
        for name, fn in scenarios:
            try:
                path = fn()
                artifacts.append(str(path))
                logger.info("Scenario '%s' complete → %s", name, path)
            except Exception as exc:  # noqa: BLE001
                logger.error("Scenario '%s' failed: %s", name, exc)
        return artifacts

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------

    def _scenario_speed_sweep(self) -> Path:
        """Derailment probability vs. train speed for several irregularity levels."""
        model = DerailmentProbabilityModel(seed=self.seed)
        speeds = np.linspace(40, 350, 50)

        results = {}
        for irr_mm in [2.0, 4.0, 8.0, 12.0]:
            sweep = model.sweep_speed(speeds, irregularity_mm=irr_mm)
            results[f"irregularity_{irr_mm:.0f}mm"] = [r.to_dict() for r in sweep]

        return self._save("speed_sweep.json", results)

    def _scenario_load_sweep(self) -> Path:
        """Derailment probability vs. axle load for several speeds."""
        model = DerailmentProbabilityModel(seed=self.seed)
        loads = np.linspace(60, 260, 40)

        results = {}
        for speed_kmh in [80.0, 120.0, 160.0, 200.0]:
            sweep = model.sweep_load(loads, speed_kmh=speed_kmh)
            results[f"speed_{speed_kmh:.0f}kmh"] = [r.to_dict() for r in sweep]

        return self._save("load_sweep.json", results)

    def _scenario_irregularity_sweep(self) -> Path:
        """Derailment probability vs. track irregularity amplitude."""
        model = DerailmentProbabilityModel(seed=self.seed)
        irregularities = np.linspace(0.5, 20, 40)

        results = {}
        for speed_kmh in [80.0, 120.0, 200.0]:
            sweep = model.sweep_irregularity(irregularities, speed_kmh=speed_kmh)
            results[f"speed_{speed_kmh:.0f}kmh"] = [r.to_dict() for r in sweep]

        return self._save("irregularity_sweep.json", results)

    def _scenario_combined_risk_surface(self) -> Path:
        """2-D risk surface over speed × axle load."""
        model = DerailmentProbabilityModel(seed=self.seed)
        speeds = np.linspace(60, 300, 25)
        loads = np.linspace(80, 240, 20)

        surface = model.combined_risk_surface(speeds, loads, irregularity_mm=5.0)
        results = {
            "speeds_kmh": speeds.tolist(),
            "loads_kN": loads.tolist(),
            "probability_surface": surface.tolist(),
        }
        return self._save("combined_risk_surface.json", results)

    def _scenario_wheelset_dynamics(self) -> Path:
        """Time-domain wheelset dynamics simulation at three speeds."""
        params = WheelRailParams()
        results = {}

        for speed_kmh in [80.0, 160.0, 240.0]:
            speed_ms = speed_kmh / 3.6
            sim = simulate_wheelset_dynamics(
                params,
                speed_ms=speed_ms,
                duration_s=3.0,
                seed=self.seed,
            )
            dq = float(derailment_quotient(params, speed_ms))
            limit = float(nadal_limit(params))
            results[f"speed_{speed_kmh:.0f}kmh"] = {
                "t": sim["t"].tolist(),
                "lateral_displacement_m": sim["y"].tolist(),
                "lateral_velocity_ms": sim["vy"].tolist(),
                "lateral_force_N": sim["lateral_force_N"].tolist(),
                "derailment_quotient": dq,
                "nadal_limit": limit,
            }

        return self._save("wheelset_dynamics.json", results)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _save(self, filename: str, data: dict) -> Path:
        path = self.output_dir / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
