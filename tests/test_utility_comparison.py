from __future__ import annotations

from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.utility_comparison import (
    UtilityComparisonSettings,
    compare_utility_energy,
    select_latest_statistics_energy,
    select_statistics_energy_for_period,
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


def test_select_latest_statistics_energy_uses_latest_opower_period() -> None:
    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    period_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)

    reading = select_latest_statistics_energy(
        "opower:utility_elec_consumption",
        {
            "opower:utility_elec_consumption": [
                {
                    "start": int(
                        datetime(2026, 6, 1, 0, 0, tzinfo=UTC).timestamp()
                        * 1000,
                    ),
                    "end": int(period_start.timestamp() * 1000),
                    "change": 22.0,
                },
                {
                    "start": int(period_start.timestamp() * 1000),
                    "end": int(period_end.timestamp() * 1000),
                    "change": 30.25,
                    "sum": 1400.0,
                },
            ]
        },
        now,
    )

    assert reading.energy_kwh == 30.25
    assert reading.period_start == period_start
    assert reading.period_end == period_end
    assert reading.source_metric == "change"
    assert reading.data_lag_hours == 48.0


def test_select_latest_statistics_energy_skips_rows_without_energy_values() -> None:
    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    valid_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)

    reading = select_latest_statistics_energy(
        "opower:utility_elec_consumption",
        {
            "opower:utility_elec_consumption": [
                {
                    "start": int(
                        datetime(2026, 6, 2, 0, 0, tzinfo=UTC).timestamp()
                        * 1000,
                    ),
                    "end": int(valid_end.timestamp() * 1000),
                    "change": 30.25,
                },
                {
                    "start": int(valid_end.timestamp() * 1000),
                    "end": int(
                        datetime(2026, 6, 4, 0, 0, tzinfo=UTC).timestamp()
                        * 1000,
                    ),
                },
            ]
        },
        now,
    )

    assert reading.energy_kwh == 30.25
    assert reading.period_end == valid_end


def test_select_statistics_energy_for_period_ignores_adjacent_periods() -> None:
    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    period_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)
    next_period_end = datetime(2026, 6, 4, 0, 0, tzinfo=UTC)

    reading = select_statistics_energy_for_period(
        "sensor.mains_import_energy",
        {
            "sensor.mains_import_energy": [
                {
                    "start": int(period_start.timestamp() * 1000),
                    "end": int(period_end.timestamp() * 1000),
                    "change": 36.0,
                },
                {
                    "start": int(period_end.timestamp() * 1000),
                    "end": int(next_period_end.timestamp() * 1000),
                    "change": 88.0,
                },
            ]
        },
        now,
        period_start=period_start,
        period_end=period_end,
    )

    assert reading.energy_kwh == 36.0
    assert reading.period_start == period_start
    assert reading.period_end == period_end


def test_compare_utility_energy_records_statistic_source_evidence() -> None:
    result = compare_utility_energy(
        settings=UtilityComparisonSettings(
            utility_statistic_id="opower:utility_elec_consumption",
            utility_source_type="statistics",
            tolerance_percent=10.0,
        ),
        utility_kwh=30.0,
        measured_kwh=36.0,
        measured_entity_ids=("sensor.mains_import_energy",),
        comparison_source="explicit_entities",
        utility_source_type="statistics",
        measured_source_type="statistics",
        period_start="2026-06-02T00:00:00+00:00",
        period_end="2026-06-03T00:00:00+00:00",
        utility_data_lag_hours=48.0,
    )

    assert result.status == "mismatch"
    assert result.utility_energy_entity == ""
    assert result.utility_statistic_id == "opower:utility_elec_consumption"
    assert result.utility_source_id == "opower:utility_elec_consumption"
    assert result.utility_source_type == "statistics"
    assert result.measured_source_type == "statistics"
    assert result.period_start == "2026-06-02T00:00:00+00:00"
    assert result.period_end == "2026-06-03T00:00:00+00:00"
    assert result.utility_data_lag_hours == 48.0


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
