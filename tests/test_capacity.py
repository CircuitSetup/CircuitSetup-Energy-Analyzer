from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.capacity import (
    CapacitySettings,
    evaluate_circuit_capacity,
)


def test_evaluate_circuit_capacity_flags_current_above_warning_ratio() -> None:
    result = evaluate_circuit_capacity(
        circuit_id="ev",
        current_amps=34.0,
        real_power_w=None,
        voltage_v=None,
        settings=CapacitySettings(breaker_amps=40.0, warning_ratio=0.8),
    )

    assert result.status == "over_limit"
    assert result.current_amps == 34.0
    assert result.breaker_amps == 40.0
    assert result.warning_threshold_amps == 32.0
    assert result.capacity_usage_percent == 85.0
    assert result.current_source == "current_sensor"
    assert result.features == {
        "current_amps": 34.0,
        "breaker_amps": 40.0,
        "warning_threshold_amps": 32.0,
        "capacity_usage_percent": 85.0,
        "warning_ratio": 0.8,
    }


def test_evaluate_circuit_capacity_estimates_current_from_watts_and_voltage() -> None:
    result = evaluate_circuit_capacity(
        circuit_id="well",
        current_amps=None,
        real_power_w=1800.0,
        voltage_v=120.0,
        settings=CapacitySettings(breaker_amps=20.0, warning_ratio=0.8),
    )

    assert result.status == "tracking"
    assert result.current_amps == 15.0
    assert result.current_source == "estimated_from_power_voltage"
    assert result.capacity_usage_percent == 75.0


def test_evaluate_circuit_capacity_reports_unconfigured_and_missing_current() -> None:
    unconfigured = evaluate_circuit_capacity(
        circuit_id="fridge",
        current_amps=3.0,
        real_power_w=None,
        voltage_v=None,
        settings=CapacitySettings(),
    )
    missing_current = evaluate_circuit_capacity(
        circuit_id="fridge",
        current_amps=None,
        real_power_w=None,
        voltage_v=120.0,
        settings=CapacitySettings(breaker_amps=15.0),
    )

    assert unconfigured.status == "unconfigured"
    assert missing_current.status == "missing_current"
