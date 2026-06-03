from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.utility_comparison import (
    UtilityComparisonSettings,
    compare_utility_energy,
)


def test_compare_utility_energy_flags_mismatch_above_tolerance() -> None:
    result = compare_utility_energy(
        settings=UtilityComparisonSettings(
            utility_energy_entity="sensor.opower_current_bill_usage",
            measured_energy_entities=("sensor.mains_import_energy",),
            tolerance_percent=10.0,
        ),
        utility_kwh=100.0,
        measured_kwh=112.5,
        measured_entity_ids=("sensor.mains_import_energy",),
        comparison_source="explicit_entities",
    )

    assert result.status == "mismatch"
    assert result.utility_kwh == 100.0
    assert result.measured_kwh == 112.5
    assert result.difference_kwh == 12.5
    assert result.difference_percent == 12.5
    assert result.absolute_difference_percent == 12.5
    assert result.features == {
        "utility_kwh": 100.0,
        "measured_kwh": 112.5,
        "difference_kwh": 12.5,
        "difference_percent": 12.5,
        "absolute_difference_percent": 12.5,
        "tolerance_percent": 10.0,
        "measured_entity_count": 1.0,
    }


def test_compare_utility_energy_tracks_within_tolerance() -> None:
    result = compare_utility_energy(
        settings=UtilityComparisonSettings(
            utility_energy_entity="sensor.opower_current_bill_usage",
            tolerance_percent=10.0,
        ),
        utility_kwh=100.0,
        measured_kwh=106.0,
        measured_entity_ids=("sensor.fridge_energy", "sensor.hvac_energy"),
        comparison_source="circuit_energy_sum",
    )

    assert result.status == "tracking"
    assert result.difference_kwh == 6.0
    assert result.difference_percent == 6.0
    assert result.comparison_source == "circuit_energy_sum"


def test_compare_utility_energy_reports_missing_inputs() -> None:
    unconfigured = compare_utility_energy(
        settings=UtilityComparisonSettings(),
        utility_kwh=None,
        measured_kwh=10.0,
        measured_entity_ids=("sensor.fridge_energy",),
        comparison_source="circuit_energy_sum",
    )
    missing_utility = compare_utility_energy(
        settings=UtilityComparisonSettings(
            utility_energy_entity="sensor.opower_current_bill_usage"
        ),
        utility_kwh=None,
        measured_kwh=10.0,
        measured_entity_ids=("sensor.fridge_energy",),
        comparison_source="circuit_energy_sum",
    )
    missing_measured = compare_utility_energy(
        settings=UtilityComparisonSettings(
            utility_energy_entity="sensor.opower_current_bill_usage"
        ),
        utility_kwh=100.0,
        measured_kwh=None,
        measured_entity_ids=(),
        comparison_source="circuit_energy_sum",
    )

    assert unconfigured.status == "unconfigured"
    assert missing_utility.status == "missing_utility"
    assert missing_measured.status == "missing_measured"
