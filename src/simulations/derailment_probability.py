"""
Derailment probability models.

Implements statistical and probabilistic methods to compute the
probability of derailment as a function of speed, axle load,
and track irregularity amplitude.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from src.simulations.wheel_rail_dynamics import (
    WheelRailParams,
    derailment_quotient,
    nadal_limit,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DerailmentProbabilityResult:
    """Output of the derailment probability calculation."""

    speed_kmh: float
    axle_load_kN: float
    irregularity_mm: float
    derailment_quotient: float
    nadal_limit: float
    probability: float  # 0–1
    safety_margin: float  # nadal_limit - derailment_quotient (positive = safe)

    def is_safe(self, threshold: float = 0.0) -> bool:
        return self.safety_margin > threshold

    def to_dict(self) -> dict:
        return {
            "speed_kmh": round(self.speed_kmh, 2),
            "axle_load_kN": round(self.axle_load_kN, 2),
            "irregularity_mm": round(self.irregularity_mm, 2),
            "derailment_quotient": round(self.derailment_quotient, 4),
            "nadal_limit": round(self.nadal_limit, 4),
            "probability": round(self.probability, 6),
            "safety_margin": round(self.safety_margin, 4),
        }


# ---------------------------------------------------------------------------
# Probability models
# ---------------------------------------------------------------------------


class DerailmentProbabilityModel:
    """
    Probabilistic derailment model based on Monte Carlo sampling of the
    Nadal criterion.

    The derailment quotient Q/P is treated as a random variable with a
    Gaussian distribution.  The probability of derailment is P(Q/P > limit).

    Parameters
    ----------
    base_params:
        Nominal wheel-rail parameters.
    variability_cv:
        Coefficient of variation applied to the lateral force estimate
        (accounts for stochastic track irregularity effects).
    n_samples:
        Number of Monte Carlo samples.
    seed:
        RNG seed for reproducibility.
    """

    def __init__(
        self,
        base_params: WheelRailParams | None = None,
        variability_cv: float = 0.15,
        n_samples: int = 5000,
        seed: int = 42,
    ) -> None:
        self.params = base_params or WheelRailParams()
        self.variability_cv = variability_cv
        self.n_samples = n_samples
        self.rng = np.random.default_rng(seed)

    def compute(
        self,
        speed_kmh: float,
        axle_load_kN: float | None = None,
        irregularity_mm: float | None = None,
    ) -> DerailmentProbabilityResult:
        """
        Compute derailment probability for given operating conditions.

        Parameters
        ----------
        speed_kmh:
            Train speed in km/h.
        axle_load_kN:
            Axle load override in kN (uses base_params default if None).
        irregularity_mm:
            Track irregularity amplitude in mm (amplifies lateral force if given).
        """
        params = WheelRailParams(
            axle_load_kN=axle_load_kN if axle_load_kN is not None else self.params.axle_load_kN,
            wheel_radius_m=self.params.wheel_radius_m,
            flange_angle_deg=self.params.flange_angle_deg,
            rail_radius_m=self.params.rail_radius_m,
            track_gauge_m=self.params.track_gauge_m,
            curve_radius_m=self.params.curve_radius_m,
            cant_mm=self.params.cant_mm,
            friction_coeff=self.params.friction_coeff,
            young_modulus_Pa=self.params.young_modulus_Pa,
            poisson_ratio=self.params.poisson_ratio,
            primary_stiffness_N_m=self.params.primary_stiffness_N_m,
            primary_damping_Ns_m=self.params.primary_damping_Ns_m,
        )

        speed_ms = speed_kmh / 3.6
        dq_nominal = derailment_quotient(params, speed_ms)
        limit = nadal_limit(params)

        # Irregularity amplification: scale DQ proportional to irregularity
        if irregularity_mm is not None:
            reference_irr = 4.0  # mm (nominal condition)
            amp_factor = 1.0 + 0.05 * max(0.0, irregularity_mm - reference_irr)
            dq_nominal *= amp_factor

        # Analytical approach using normal distribution (fast, closed-form)
        sigma = abs(dq_nominal) * self.variability_cv + 1e-6
        prob = float(1.0 - norm.cdf(limit, loc=dq_nominal, scale=sigma))
        prob = float(np.clip(prob, 0.0, 1.0))

        return DerailmentProbabilityResult(
            speed_kmh=speed_kmh,
            axle_load_kN=params.axle_load_kN,
            irregularity_mm=irregularity_mm if irregularity_mm is not None else 0.0,
            derailment_quotient=dq_nominal,
            nadal_limit=limit,
            probability=prob,
            safety_margin=limit - dq_nominal,
        )

    def sweep_speed(
        self,
        speeds_kmh: np.ndarray,
        axle_load_kN: float | None = None,
        irregularity_mm: float | None = None,
    ) -> list[DerailmentProbabilityResult]:
        """Compute derailment probability for a range of speeds."""
        return [
            self.compute(float(v), axle_load_kN, irregularity_mm)
            for v in speeds_kmh
        ]

    def sweep_load(
        self,
        loads_kN: np.ndarray,
        speed_kmh: float = 120.0,
        irregularity_mm: float | None = None,
    ) -> list[DerailmentProbabilityResult]:
        """Compute derailment probability for a range of axle loads."""
        return [
            self.compute(speed_kmh, float(load), irregularity_mm)
            for load in loads_kN
        ]

    def sweep_irregularity(
        self,
        irregularities_mm: np.ndarray,
        speed_kmh: float = 120.0,
        axle_load_kN: float | None = None,
    ) -> list[DerailmentProbabilityResult]:
        """Compute derailment probability for a range of irregularity amplitudes."""
        return [
            self.compute(speed_kmh, axle_load_kN, float(irr))
            for irr in irregularities_mm
        ]

    def combined_risk_surface(
        self,
        speeds_kmh: np.ndarray,
        loads_kN: np.ndarray,
        irregularity_mm: float = 4.0,
    ) -> np.ndarray:
        """
        Compute a 2-D probability surface over speed × axle_load.

        Returns an array of shape ``(len(speeds_kmh), len(loads_kN))``.
        """
        surface = np.zeros((len(speeds_kmh), len(loads_kN)))
        for i, speed in enumerate(speeds_kmh):
            for j, load in enumerate(loads_kN):
                result = self.compute(float(speed), float(load), irregularity_mm)
                surface[i, j] = result.probability
        return surface
