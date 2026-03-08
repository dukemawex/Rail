"""
Physics-based wheel-rail contact and dynamics simulation.

Implements a simplified but physically grounded model of wheel-rail
interaction based on Hertz contact theory and Kalker's linear creep
theory, suitable for derailment risk studies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Physical constants & default parameters
# ---------------------------------------------------------------------------

G = 9.81  # gravitational acceleration [m/s²]


@dataclass
class WheelRailParams:
    """Physical parameters for the wheel-rail contact model."""

    # Vehicle
    mass_kg: float = 15_000.0  # unsprung mass per wheelset [kg]
    axle_load_kN: float = 160.0  # static axle load [kN]
    wheel_radius_m: float = 0.46  # new wheel radius [m]
    flange_angle_deg: float = 70.0  # wheel flange contact angle [°]

    # Rail / track
    rail_radius_m: float = 0.30  # lateral rail head radius [m]
    track_gauge_m: float = 1.435  # track gauge [m]
    curve_radius_m: float = 1000.0  # horizontal curve radius [m]
    cant_mm: float = 50.0  # applied superelevation [mm]

    # Contact mechanics
    friction_coeff: float = 0.30  # dry wheel-rail friction
    young_modulus_Pa: float = 2.1e11  # steel Young's modulus [Pa]
    poisson_ratio: float = 0.28  # Poisson's ratio

    # Suspension
    primary_stiffness_N_m: float = 8e6  # lateral primary spring stiffness [N/m]
    primary_damping_Ns_m: float = 1.5e4  # lateral primary damper [N·s/m]

    @property
    def axle_load_N(self) -> float:
        return self.axle_load_kN * 1000.0

    @property
    def wheel_load_N(self) -> float:
        """Normal wheel load (half axle load)."""
        return self.axle_load_N / 2.0

    @property
    def flange_angle_rad(self) -> float:
        return np.deg2rad(self.flange_angle_deg)


# ---------------------------------------------------------------------------
# Contact mechanics
# ---------------------------------------------------------------------------


def hertz_contact_radius(params: WheelRailParams) -> float:
    """
    Compute Hertz contact semi-axis length [m] for wheel-rail contact.

    Uses the combined curvature approximation for an elliptical contact patch.
    """
    E_star = params.young_modulus_Pa / (2 * (1 - params.poisson_ratio**2))
    # Combined curvature: 1/R_sum = 1/R_wheel + 1/R_rail (lateral radii)
    R_sum = 1.0 / (1.0 / params.wheel_radius_m + 1.0 / params.rail_radius_m)
    a = (3 * params.wheel_load_N * R_sum / (4 * E_star)) ** (1.0 / 3.0)
    return float(a)


def contact_patch_area(params: WheelRailParams) -> float:
    """Elliptical contact patch area [m²]."""
    a = hertz_contact_radius(params)
    # Assume aspect ratio b/a ≈ 0.7 (typical for wheel-rail)
    return float(np.pi * a * 0.7 * a)


def normal_contact_pressure(params: WheelRailParams) -> float:
    """Peak Hertz contact pressure [Pa]."""
    a = hertz_contact_radius(params)
    area = contact_patch_area(params)
    if area <= 0:
        return 0.0
    return float(1.5 * params.wheel_load_N / area)


# ---------------------------------------------------------------------------
# Nadal derailment criterion
# ---------------------------------------------------------------------------


def nadal_limit(params: WheelRailParams) -> float:
    """
    Compute the Nadal flange-climb derailment limit (Q/P ratio).

    References: Nadal (1908), EN 14363.
    """
    mu = params.friction_coeff
    alpha = params.flange_angle_rad
    return float((np.tan(alpha) - mu) / (1.0 + mu * np.tan(alpha)))


def lateral_wheel_force_N(
    params: WheelRailParams, speed_ms: float
) -> float:
    """
    Estimate quasi-static lateral wheel force on the outer rail of a curve.

    Includes centrifugal force contribution and track cant correction.
    """
    # Cant angle
    cant_rad = np.arctan(params.cant_mm / 1e3 / params.track_gauge_m)
    # Centrifugal acceleration in curve
    if params.curve_radius_m > 0:
        a_centrifugal = speed_ms**2 / params.curve_radius_m
    else:
        a_centrifugal = 0.0
    # Lateral force component
    Q = params.wheel_load_N * (a_centrifugal / G - np.tan(cant_rad))
    return float(Q)


def derailment_quotient(
    params: WheelRailParams, speed_ms: float
) -> float:
    """
    Compute the derailment quotient Q/P at a given speed.

    Returns the ratio of lateral wheel force Q to vertical wheel load P.
    """
    Q = lateral_wheel_force_N(params, speed_ms)
    P = params.wheel_load_N
    return float(Q / P) if P > 0 else 0.0


# ---------------------------------------------------------------------------
# Single-wheelset lateral dynamics (ODE model)
# ---------------------------------------------------------------------------


def simulate_wheelset_dynamics(
    params: WheelRailParams,
    speed_ms: float,
    duration_s: float = 2.0,
    track_irregularity: np.ndarray | None = None,
    t_eval: np.ndarray | None = None,
    seed: int = 42,
) -> dict[str, np.ndarray]:
    """
    Simulate lateral wheelset dynamics using a 2-DOF ODE model.

    State vector: [y (lateral disp.), vy (lateral vel.)]

    Parameters
    ----------
    params:
        Wheel-rail physical parameters.
    speed_ms:
        Train speed in m/s.
    duration_s:
        Simulation duration in seconds.
    track_irregularity:
        Optional array of lateral track irregularity values (m) sampled at
        ``t_eval`` time steps.  If ``None``, white noise is generated.
    t_eval:
        Time evaluation points.  Defaults to 200 points over ``duration_s``.
    seed:
        Random seed for reproducible noise generation.

    Returns
    -------
    dict with keys: ``t``, ``y``, ``vy``, ``lateral_force_N``
    """
    rng = np.random.default_rng(seed)

    if t_eval is None:
        t_eval = np.linspace(0.0, duration_s, 200)

    # Build track irregularity signal
    if track_irregularity is None:
        # Simple coloured noise: amplitude σ = 3 mm
        sigma = 3e-3
        raw = rng.standard_normal(len(t_eval))
        # Low-pass filter via cumulative sum with normalisation
        irreg = np.cumsum(raw) / np.sqrt(np.arange(1, len(raw) + 1))
        irreg = irreg / (irreg.std() + 1e-12) * sigma
    else:
        irreg = track_irregularity

    def odes(t: float, state: list[float]) -> list[float]:
        y, vy = state
        # Interpolate irregularity at current time
        w = float(np.interp(t, t_eval, irreg))
        # Relative lateral displacement to track centre
        y_rel = y - w
        # Spring + damper restoring force from primary suspension
        F_spring = -params.primary_stiffness_N_m * y_rel
        F_damp = -params.primary_damping_Ns_m * vy
        # Creep force (simplified Kalker linear theory)
        creep_coeff = 8e4  # N (simplified creep coefficient)
        y_dot = vy
        vy_dot = (F_spring + F_damp + creep_coeff * w) / params.mass_kg
        return [y_dot, vy_dot]

    sol = solve_ivp(
        odes,
        t_span=(t_eval[0], t_eval[-1]),
        y0=[0.0, 0.0],
        t_eval=t_eval,
        method="RK45",
        max_step=0.02,
    )

    lateral_force = params.primary_stiffness_N_m * sol.y[0]

    return {
        "t": sol.t,
        "y": sol.y[0],
        "vy": sol.y[1],
        "lateral_force_N": lateral_force,
    }
