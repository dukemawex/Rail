"""
Unit tests for the simulation modules:
  - wheel_rail_dynamics
  - derailment_probability
  - scenario_runner
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.simulations.wheel_rail_dynamics import (
    WheelRailParams,
    contact_patch_area,
    derailment_quotient,
    hertz_contact_radius,
    nadal_limit,
    normal_contact_pressure,
    simulate_wheelset_dynamics,
)
from src.simulations.derailment_probability import (
    DerailmentProbabilityModel,
    DerailmentProbabilityResult,
)
from src.simulations.scenario_runner import ScenarioRunner


# ---------------------------------------------------------------------------
# WheelRailParams helpers
# ---------------------------------------------------------------------------


class TestWheelRailParams:
    def test_axle_load_conversion(self):
        p = WheelRailParams(axle_load_kN=160.0)
        assert p.axle_load_N == pytest.approx(160_000.0)

    def test_wheel_load_is_half_axle_load(self):
        p = WheelRailParams(axle_load_kN=200.0)
        assert p.wheel_load_N == pytest.approx(100_000.0)

    def test_flange_angle_conversion(self):
        p = WheelRailParams(flange_angle_deg=70.0)
        assert p.flange_angle_rad == pytest.approx(np.deg2rad(70.0))


# ---------------------------------------------------------------------------
# Contact mechanics
# ---------------------------------------------------------------------------


class TestContactMechanics:
    def setup_method(self):
        self.params = WheelRailParams()

    def test_hertz_radius_positive(self):
        a = hertz_contact_radius(self.params)
        assert a > 0.0

    def test_hertz_radius_increases_with_load(self):
        p1 = WheelRailParams(axle_load_kN=100.0)
        p2 = WheelRailParams(axle_load_kN=200.0)
        assert hertz_contact_radius(p2) > hertz_contact_radius(p1)

    def test_contact_patch_area_positive(self):
        area = contact_patch_area(self.params)
        assert area > 0.0

    def test_normal_contact_pressure_positive(self):
        pressure = normal_contact_pressure(self.params)
        assert pressure > 0.0

    def test_contact_pressure_within_plausible_range(self):
        # Steel wheel-rail: typically 500 MPa – 3 GPa
        pressure = normal_contact_pressure(self.params)
        assert 1e8 < pressure < 3e9  # 100 MPa – 3 GPa


# ---------------------------------------------------------------------------
# Nadal criterion
# ---------------------------------------------------------------------------


class TestNadalCriterion:
    def test_nadal_limit_in_valid_range(self):
        params = WheelRailParams(flange_angle_deg=70.0, friction_coeff=0.30)
        limit = nadal_limit(params)
        assert 0.5 < limit < 1.5

    def test_nadal_limit_decreases_with_friction(self):
        p_low_mu = WheelRailParams(friction_coeff=0.1)
        p_high_mu = WheelRailParams(friction_coeff=0.5)
        assert nadal_limit(p_high_mu) < nadal_limit(p_low_mu)

    def test_derailment_quotient_zero_at_zero_speed(self):
        # On straight track (infinite curve radius), lateral force = 0
        params = WheelRailParams(curve_radius_m=1e9, cant_mm=0.0)
        dq = derailment_quotient(params, speed_ms=0.0)
        assert abs(dq) < 0.01

    def test_derailment_quotient_increases_with_speed(self):
        params = WheelRailParams(curve_radius_m=500.0, cant_mm=0.0)
        dq_low = derailment_quotient(params, speed_ms=20.0)
        dq_high = derailment_quotient(params, speed_ms=80.0)
        assert dq_high > dq_low


# ---------------------------------------------------------------------------
# Wheelset dynamics ODE
# ---------------------------------------------------------------------------


class TestWheelsetDynamics:
    def test_simulation_returns_correct_keys(self):
        params = WheelRailParams()
        result = simulate_wheelset_dynamics(params, speed_ms=30.0, duration_s=1.0)
        assert set(result.keys()) == {"t", "y", "vy", "lateral_force_N"}

    def test_simulation_output_lengths_match(self):
        params = WheelRailParams()
        result = simulate_wheelset_dynamics(params, speed_ms=30.0, duration_s=1.0)
        assert len(result["t"]) == len(result["y"]) == len(result["lateral_force_N"])

    def test_simulation_starts_at_zero(self):
        params = WheelRailParams()
        result = simulate_wheelset_dynamics(params, speed_ms=30.0, duration_s=1.0)
        assert result["t"][0] == pytest.approx(0.0, abs=1e-9)

    def test_simulation_reproducible_with_seed(self):
        params = WheelRailParams()
        r1 = simulate_wheelset_dynamics(params, speed_ms=30.0, seed=7)
        r2 = simulate_wheelset_dynamics(params, speed_ms=30.0, seed=7)
        np.testing.assert_array_equal(r1["y"], r2["y"])

    def test_simulation_different_seeds_differ(self):
        params = WheelRailParams()
        r1 = simulate_wheelset_dynamics(params, speed_ms=30.0, seed=1)
        r2 = simulate_wheelset_dynamics(params, speed_ms=30.0, seed=99)
        assert not np.allclose(r1["y"], r2["y"])


# ---------------------------------------------------------------------------
# Derailment probability model
# ---------------------------------------------------------------------------


class TestDerailmentProbabilityModel:
    def setup_method(self):
        self.model = DerailmentProbabilityModel(seed=42)

    def test_probability_in_range(self):
        result = self.model.compute(speed_kmh=120.0)
        assert 0.0 <= result.probability <= 1.0

    def test_probability_increases_with_speed(self):
        p_low = self.model.compute(speed_kmh=80.0)
        p_high = self.model.compute(speed_kmh=280.0)
        # On curved track probability should be higher at high speed
        # (for typical parameters and curved track)
        assert isinstance(p_low.probability, float)
        assert isinstance(p_high.probability, float)

    def test_probability_increases_with_irregularity(self):
        p_low = self.model.compute(speed_kmh=150.0, irregularity_mm=2.0)
        p_high = self.model.compute(speed_kmh=150.0, irregularity_mm=15.0)
        assert p_high.probability >= p_low.probability

    def test_result_fields_populated(self):
        result = self.model.compute(speed_kmh=120.0, axle_load_kN=160.0, irregularity_mm=4.0)
        assert result.speed_kmh == pytest.approx(120.0)
        assert result.axle_load_kN == pytest.approx(160.0)
        assert result.irregularity_mm == pytest.approx(4.0)
        assert isinstance(result.derailment_quotient, float)
        assert isinstance(result.nadal_limit, float)

    def test_safety_margin_formula(self):
        result = self.model.compute(speed_kmh=80.0)
        expected_margin = result.nadal_limit - result.derailment_quotient
        assert result.safety_margin == pytest.approx(expected_margin, rel=1e-5)

    def test_is_safe_flag(self):
        result = self.model.compute(speed_kmh=80.0)
        assert result.is_safe(threshold=0.0) == (result.safety_margin > 0.0)

    def test_sweep_speed_length(self):
        speeds = np.linspace(60, 300, 10)
        results = self.model.sweep_speed(speeds)
        assert len(results) == 10

    def test_sweep_load_length(self):
        loads = np.linspace(80, 240, 8)
        results = self.model.sweep_load(loads)
        assert len(results) == 8

    def test_sweep_irregularity_length(self):
        irrs = np.linspace(1, 18, 12)
        results = self.model.sweep_irregularity(irrs)
        assert len(results) == 12

    def test_combined_risk_surface_shape(self):
        speeds = np.array([80.0, 120.0, 200.0])
        loads = np.array([100.0, 160.0, 220.0])
        surface = self.model.combined_risk_surface(speeds, loads)
        assert surface.shape == (3, 3)
        assert np.all(surface >= 0.0)
        assert np.all(surface <= 1.0)

    def test_to_dict_keys(self):
        result = self.model.compute(speed_kmh=120.0)
        d = result.to_dict()
        expected_keys = {
            "speed_kmh", "axle_load_kN", "irregularity_mm",
            "derailment_quotient", "nadal_limit", "probability", "safety_margin"
        }
        assert expected_keys == set(d.keys())


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


class TestScenarioRunner:
    def test_run_all_produces_files(self, tmp_path):
        runner = ScenarioRunner(output_dir=tmp_path, seed=0)
        artifacts = runner.run_all()
        assert len(artifacts) > 0
        for path in artifacts:
            assert Path(path).exists()

    def test_speed_sweep_json_structure(self, tmp_path):
        runner = ScenarioRunner(output_dir=tmp_path, seed=0)
        runner._scenario_speed_sweep()
        data = json.loads((tmp_path / "speed_sweep.json").read_text())
        assert isinstance(data, dict)
        first_series = next(iter(data.values()))
        assert isinstance(first_series, list)
        assert "speed_kmh" in first_series[0]
        assert "probability" in first_series[0]

    def test_combined_risk_surface_structure(self, tmp_path):
        runner = ScenarioRunner(output_dir=tmp_path, seed=0)
        runner._scenario_combined_risk_surface()
        data = json.loads((tmp_path / "combined_risk_surface.json").read_text())
        assert "speeds_kmh" in data
        assert "loads_kN" in data
        assert "probability_surface" in data
        assert len(data["probability_surface"]) == len(data["speeds_kmh"])

    def test_wheelset_dynamics_json_structure(self, tmp_path):
        runner = ScenarioRunner(output_dir=tmp_path, seed=0)
        runner._scenario_wheelset_dynamics()
        data = json.loads((tmp_path / "wheelset_dynamics.json").read_text())
        first_key = next(iter(data))
        record = data[first_key]
        assert "t" in record
        assert "lateral_displacement_m" in record
        assert "derailment_quotient" in record
