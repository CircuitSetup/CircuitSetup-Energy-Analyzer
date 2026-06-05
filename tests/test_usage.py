from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.usage import (
    DEFAULT_DAILY_USAGE_SPIKE_RATIO,
    DEFAULT_USAGE_WINDOW_DAYS,
    EnergyUsageSettings,
    record_energy_usage,
)


def test_record_energy_usage_flags_day_above_window_share() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-03T00:00:00+00:00",
        "days": [
            {"date": "2026-05-27", "usage_kwh": 6.0},
            {"date": "2026-05-28", "usage_kwh": 7.0},
            {"date": "2026-05-29", "usage_kwh": 8.0},
            {"date": "2026-05-30", "usage_kwh": 7.0},
            {"date": "2026-05-31", "usage_kwh": 6.0},
            {"date": "2026-06-01", "usage_kwh": 8.0},
            {"date": "2026-06-02", "usage_kwh": 8.0},
        ],
    }

    result = record_energy_usage(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 3, 18, 0, tzinfo=UTC),
        energy_kwh=112.6,
        settings=EnergyUsageSettings(),
    )

    assert DEFAULT_USAGE_WINDOW_DAYS == 7
    assert DEFAULT_DAILY_USAGE_SPIKE_RATIO == 0.25
    assert result.daily_usage_kwh == 12.6
    assert result.baseline_total_kwh == 50.0
    assert result.spike is not None
    assert result.spike.threshold_kwh == 12.5
    assert result.spike.daily_usage_share == 0.252
    assert result.spike.features == {
        "daily_usage_kwh": 12.6,
        "baseline_total_kwh": 50.0,
        "baseline_window_days": 7.0,
        "baseline_day_count": 7.0,
        "threshold_kwh": 12.5,
        "threshold_ratio": 0.25,
        "daily_usage_share": 0.252,
    }


def test_record_energy_usage_waits_for_full_baseline_window() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-03T00:00:00+00:00",
        "days": [
            {"date": "2026-06-01", "usage_kwh": 8.0},
            {"date": "2026-06-02", "usage_kwh": 8.0},
        ],
    }

    result = record_energy_usage(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 3, 18, 0, tzinfo=UTC),
        energy_kwh=112.6,
        settings=EnergyUsageSettings(),
    )

    assert result.baseline_total_kwh == 16.0
    assert result.spike is None


def test_record_energy_usage_marks_first_sample_waiting_for_delta() -> None:
    result = record_energy_usage(
        {},
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        energy_kwh=108.4,
        settings=EnergyUsageSettings(),
    )

    assert result is not None
    assert result.daily_usage_kwh == 0.0
    assert result.tracking_status == "waiting_for_delta"
    assert result.status_reason == "first_cumulative_sample"


def test_record_energy_usage_distinguishes_true_zero_after_tracking() -> None:
    history = {
        "last_energy_kwh": 108.4,
        "last_sample_at": "2026-06-05T08:00:00+00:00",
        "days": [
            {"date": "2026-05-29", "usage_kwh": 7.1},
            {"date": "2026-05-30", "usage_kwh": 6.9},
            {"date": "2026-05-31", "usage_kwh": 7.4},
            {"date": "2026-06-01", "usage_kwh": 8.0},
            {"date": "2026-06-02", "usage_kwh": 7.8},
            {"date": "2026-06-03", "usage_kwh": 8.3},
            {"date": "2026-06-04", "usage_kwh": 7.5},
        ],
    }

    result = record_energy_usage(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        energy_kwh=108.4,
        settings=EnergyUsageSettings(),
    )

    assert result is not None
    assert result.daily_usage_kwh == 0.0
    assert result.baseline_day_count == 7
    assert result.tracking_status == "tracking"
    assert result.status_reason == "no_delta_today"


def test_record_energy_usage_ignores_meter_reset_delta() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-03T12:00:00+00:00",
        "days": [{"date": "2026-06-02", "usage_kwh": 8.0}],
    }

    result = record_energy_usage(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 3, 18, 0, tzinfo=UTC),
        energy_kwh=2.0,
        settings=EnergyUsageSettings(),
    )

    assert result.daily_usage_kwh == 0.0
    assert history["last_energy_kwh"] == 2.0
    assert history["days"] == [{"date": "2026-06-02", "usage_kwh": 8.0}]
