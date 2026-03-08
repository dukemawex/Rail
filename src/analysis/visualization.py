"""
Visualisation module: generates publication-quality figures from simulation results.

All figures are saved as PNG files in the ``figures/`` directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")  # Non-interactive backend for headless CI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style configuration
# ---------------------------------------------------------------------------

FIGURE_DPI = 150
FIGURE_SIZE = (8, 5)

PALETTE = {
    "primary": "#1f4e79",
    "secondary": "#2e75b6",
    "accent": "#c00000",
    "neutral": "#808080",
    "safe": "#2e7d32",
    "danger": "#c62828",
}


class Visualizer:
    """
    Generates all figures for the research paper from simulation JSON files.

    Parameters
    ----------
    results_dir:
        Directory containing simulation result JSON files.
    figures_dir:
        Output directory for generated PNG figures.
    """

    def __init__(
        self,
        results_dir: str | Path,
        figures_dir: str | Path,
    ) -> None:
        self.results_dir = Path(results_dir)
        self.figures_dir = Path(figures_dir)
        self.figures_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(self) -> list[str]:
        """Generate all figures and return a list of file paths."""
        generators = [
            ("speed_sweep", self._plot_speed_sweep),
            ("load_sweep", self._plot_load_sweep),
            ("irregularity_sweep", self._plot_irregularity_sweep),
            ("combined_risk_surface", self._plot_combined_risk_surface),
            ("wheelset_dynamics", self._plot_wheelset_dynamics),
        ]
        paths: list[str] = []
        for name, fn in generators:
            try:
                path = fn()
                paths.append(str(path))
            except Exception as exc:  # noqa: BLE001
                logger.error("Figure '%s' failed: %s", name, exc)
        return paths

    # ------------------------------------------------------------------
    # Plot methods
    # ------------------------------------------------------------------

    def _plot_speed_sweep(self) -> Path:
        data = self._load("speed_sweep.json")
        fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)

        colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["accent"], PALETTE["neutral"]]
        for idx, (series, records) in enumerate(data.items()):
            speeds = [r["speed_kmh"] for r in records]
            probs = [r["probability"] * 100 for r in records]  # %
            label = series.replace("_", " ").replace("irregularity ", "Irr. ")
            ax.plot(speeds, probs, color=colors[idx % len(colors)], linewidth=2, label=label)

        ax.axhline(1.0, color=PALETTE["danger"], linestyle="--", linewidth=1.5,
                   label="1% risk threshold")
        ax.set_xlabel("Train Speed (km/h)", fontsize=12)
        ax.set_ylabel("Derailment Probability (%)", fontsize=12)
        ax.set_title("Derailment Probability vs. Train Speed", fontsize=14, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        plt.tight_layout()
        return self._save(fig, "fig_speed_sweep.png")

    def _plot_load_sweep(self) -> Path:
        data = self._load("load_sweep.json")
        fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)

        colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["accent"], PALETTE["neutral"]]
        for idx, (series, records) in enumerate(data.items()):
            loads = [r["axle_load_kN"] for r in records]
            probs = [r["probability"] * 100 for r in records]
            label = series.replace("_", " ").replace("speed ", "").replace("kmh", " km/h")
            ax.plot(loads, probs, color=colors[idx % len(colors)], linewidth=2, label=label)

        ax.axhline(1.0, color=PALETTE["danger"], linestyle="--", linewidth=1.5,
                   label="1% risk threshold")
        ax.set_xlabel("Axle Load (kN)", fontsize=12)
        ax.set_ylabel("Derailment Probability (%)", fontsize=12)
        ax.set_title("Derailment Probability vs. Axle Load", fontsize=14, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return self._save(fig, "fig_load_sweep.png")

    def _plot_irregularity_sweep(self) -> Path:
        data = self._load("irregularity_sweep.json")
        fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)

        colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["accent"]]
        for idx, (series, records) in enumerate(data.items()):
            irrs = [r["irregularity_mm"] for r in records]
            probs = [r["probability"] * 100 for r in records]
            label = series.replace("_", " ").replace("speed ", "").replace("kmh", " km/h")
            ax.plot(irrs, probs, color=colors[idx % len(colors)], linewidth=2, label=label)

        ax.axhline(1.0, color=PALETTE["danger"], linestyle="--", linewidth=1.5,
                   label="1% risk threshold")
        ax.set_xlabel("Track Irregularity Amplitude (mm)", fontsize=12)
        ax.set_ylabel("Derailment Probability (%)", fontsize=12)
        ax.set_title("Derailment Probability vs. Track Irregularity", fontsize=14, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return self._save(fig, "fig_irregularity_sweep.png")

    def _plot_combined_risk_surface(self) -> Path:
        data = self._load("combined_risk_surface.json")
        speeds = np.array(data["speeds_kmh"])
        loads = np.array(data["loads_kN"])
        surface = np.array(data["probability_surface"]) * 100  # %

        fig, ax = plt.subplots(figsize=(9, 6), dpi=FIGURE_DPI)
        mesh = ax.contourf(loads, speeds, surface, levels=20, cmap="RdYlGn_r")
        ax.contour(loads, speeds, surface, levels=[1.0], colors=[PALETTE["danger"]],
                   linewidths=2, linestyles="--")
        cbar = plt.colorbar(mesh, ax=ax)
        cbar.set_label("Derailment Probability (%)", fontsize=11)
        ax.set_xlabel("Axle Load (kN)", fontsize=12)
        ax.set_ylabel("Train Speed (km/h)", fontsize=12)
        ax.set_title("Combined Risk Surface: Speed × Axle Load\n(dashed = 1% threshold)",
                     fontsize=13, fontweight="bold")
        plt.tight_layout()
        return self._save(fig, "fig_combined_risk_surface.png")

    def _plot_wheelset_dynamics(self) -> Path:
        data = self._load("wheelset_dynamics.json")
        fig, axes = plt.subplots(2, 1, figsize=(9, 7), dpi=FIGURE_DPI, sharex=True)

        colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["accent"]]
        for idx, (series, record) in enumerate(data.items()):
            t = record["t"]
            disp_mm = np.array(record["lateral_displacement_m"]) * 1000
            force_kN = np.array(record["lateral_force_N"]) / 1000
            label = series.replace("_", " ").replace("speed ", "").replace("kmh", " km/h")
            color = colors[idx % len(colors)]
            axes[0].plot(t, disp_mm, color=color, linewidth=1.5, label=label)
            axes[1].plot(t, force_kN, color=color, linewidth=1.5, label=label)

        axes[0].set_ylabel("Lateral Displacement (mm)", fontsize=11)
        axes[0].set_title("Wheelset Lateral Dynamics Simulation", fontsize=13, fontweight="bold")
        axes[0].legend(fontsize=9)
        axes[0].grid(True, alpha=0.3)
        axes[1].set_xlabel("Time (s)", fontsize=11)
        axes[1].set_ylabel("Lateral Force (kN)", fontsize=11)
        axes[1].legend(fontsize=9)
        axes[1].grid(True, alpha=0.3)
        plt.tight_layout()
        return self._save(fig, "fig_wheelset_dynamics.png")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load(self, filename: str) -> dict[str, Any]:
        path = self.results_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Simulation results not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, fig: plt.Figure, filename: str) -> Path:
        path = self.figures_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved figure: %s", path)
        return path
