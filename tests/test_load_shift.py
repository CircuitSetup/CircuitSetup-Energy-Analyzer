from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.load_shift import (
    FlexibleLoadInput,
    evaluate_solar_load_shift,
)


def test_evaluate_solar_load_shift_finds_idle_load_opportunity() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=1300.0,
        solar_surplus_status="high_surplus",
        grid_import_w=0.0,
        flexible_loads=[
            FlexibleLoadInput("water_heater", "Water heater", "water_heater", 0.0),
            FlexibleLoadInput("pool", "Pool pump", "pool_pump", 25.0),
        ],
    )

    assert result.status == "surplus_candidate"
    assert result.active_flexible_load_power_w == 0.0
    assert result.solar_load_shift_available_w == 1300.0
    assert result.active_flexible_load_count == 0
    assert result.idle_flexible_load_count == 2
    assert result.solar_coverage_percent == 0.0
    assert result.candidate_loads == [
        {
            "circuit_id": "water_heater",
            "name": "Water heater",
            "appliance_profile": "water_heater",
            "current_power_w": 0.0,
            "state": "idle",
        },
        {
            "circuit_id": "pool",
            "name": "Pool pump",
            "appliance_profile": "pool_pump",
            "current_power_w": 25.0,
            "state": "idle",
        },
    ]


def test_evaluate_solar_load_shift_estimates_active_load_solar_coverage() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=500.0,
        solar_surplus_status="surplus_available",
        grid_import_w=0.0,
        flexible_loads=[
            FlexibleLoadInput("pool", "Pool pump", "pool_pump", 800.0),
            FlexibleLoadInput("ev", "EV charger", "ev_charger", 0.0),
        ],
    )

    assert result.status == "active_solar_supported"
    assert result.active_flexible_load_power_w == 800.0
    assert result.active_flexible_load_count == 1
    assert result.idle_flexible_load_count == 1
    assert result.solar_coverage_percent == 100.0


def test_evaluate_solar_load_shift_requires_valid_solar_flow() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=0.0,
        solar_surplus_status="missing_generation",
        grid_import_w=0.0,
        flexible_loads=[
            FlexibleLoadInput("pool", "Pool pump", "pool_pump", 800.0),
        ],
    )

    assert result.status == "solar_flow_unavailable"
    assert result.active_flexible_load_power_w == 800.0
    assert result.solar_coverage_percent == 0.0
    assert result.features["solar_surplus_status"] == "missing_generation"


def test_evaluate_solar_load_shift_reports_active_load_grid_support() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=0.0,
        solar_surplus_status="no_surplus",
        grid_import_w=800.0,
        flexible_loads=[
            FlexibleLoadInput("ev", "EV charger", "ev_charger", 2000.0),
        ],
    )

    assert result.status == "active_grid_supported"
    assert result.active_flexible_load_power_w == 2000.0
    assert result.solar_coverage_percent == 60.0


def test_evaluate_solar_load_shift_does_not_treat_missing_power_as_idle() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=1300.0,
        solar_surplus_status="high_surplus",
        grid_import_w=0.0,
        flexible_loads=[
            FlexibleLoadInput("water_heater", "Water heater", "water_heater", None),
        ],
    )

    assert result.status == "insufficient_flexible_load_data"
    assert result.idle_flexible_load_count == 0
    assert result.candidate_loads == [
        {
            "circuit_id": "water_heater",
            "name": "Water heater",
            "appliance_profile": "water_heater",
            "current_power_w": None,
            "state": "unavailable",
        }
    ]


def test_evaluate_solar_load_shift_reports_missing_flexible_loads() -> None:
    result = evaluate_solar_load_shift(
        solar_load_shift_available_w=1300.0,
        solar_surplus_status="high_surplus",
        grid_import_w=0.0,
        flexible_loads=[],
    )

    assert result.status == "no_flexible_loads"
    assert result.active_flexible_load_power_w == 0.0
    assert result.idle_flexible_load_count == 0
