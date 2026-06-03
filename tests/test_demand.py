from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.demand import (
    DEFAULT_DEMAND_WINDOW_MINUTES,
    DemandSettings,
    record_demand_sample,
)


def test_record_demand_sample_uses_time_weighted_window_and_tracks_peak() -> None:
    history = {
        "samples": [
            {"timestamp": "2026-06-03T12:00:00+00:00", "real_power_w": 1000.0},
            {"timestamp": "2026-06-03T12:05:00+00:00", "real_power_w": 2000.0},
            {"timestamp": "2026-06-03T12:10:00+00:00", "real_power_w": 3000.0},
        ],
        "daily_peaks": [],
    }

    result = record_demand_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=3000.0,
        settings=DemandSettings(),
    )

    assert DEFAULT_DEMAND_WINDOW_MINUTES == 15
    assert result.current_demand_w == 2000.0
    assert result.peak_demand_w == 2000.0
    assert result.limit_exceeded is None
    assert history["daily_peaks"] == [
        {"date": "2026-06-03", "peak_demand_w": 2000.0}
    ]


def test_record_demand_sample_flags_configured_limit() -> None:
    history = {
        "samples": [
            {"timestamp": "2026-06-03T12:00:00+00:00", "real_power_w": 2200.0},
            {"timestamp": "2026-06-03T12:05:00+00:00", "real_power_w": 2400.0},
            {"timestamp": "2026-06-03T12:10:00+00:00", "real_power_w": 2600.0},
        ],
        "daily_peaks": [],
    }

    result = record_demand_sample(
        history,
        circuit_id="ev_charger",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=2600.0,
        settings=DemandSettings(demand_limit_w=2000.0),
    )

    assert result.current_demand_w == 2400.0
    assert result.demand_limit_usage == 120.0
    assert result.limit_exceeded is not None
    assert result.limit_exceeded.features == {
        "current_demand_w": 2400.0,
        "peak_demand_w": 2400.0,
        "demand_limit_w": 2000.0,
        "demand_limit_usage": 120.0,
        "demand_window_minutes": 15.0,
    }


def test_record_demand_sample_prunes_old_window_samples() -> None:
    history = {
        "samples": [
            {"timestamp": "2026-06-03T11:00:00+00:00", "real_power_w": 9000.0},
            {"timestamp": "2026-06-03T12:10:00+00:00", "real_power_w": 1000.0},
        ],
        "daily_peaks": [
            {"date": "2026-05-01", "peak_demand_w": 7000.0},
            {"date": "2026-06-02", "peak_demand_w": 4000.0},
        ],
    }

    result = record_demand_sample(
        history,
        circuit_id="pool_pump",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=1000.0,
        settings=DemandSettings(),
        retention_days=14,
    )

    assert result.current_demand_w == 1000.0
    assert history["samples"] == [
        {"timestamp": "2026-06-03T12:10:00+00:00", "real_power_w": 1000.0},
        {"timestamp": "2026-06-03T12:15:00+00:00", "real_power_w": 1000.0},
    ]
    assert history["daily_peaks"] == [
        {"date": "2026-06-02", "peak_demand_w": 4000.0},
        {"date": "2026-06-03", "peak_demand_w": 1000.0},
    ]
