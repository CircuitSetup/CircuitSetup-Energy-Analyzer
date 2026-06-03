from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.demand import (
    DEFAULT_DEMAND_WINDOW_MINUTES,
    DEFAULT_PEAK_RANK_COUNT,
    DEFAULT_PEAK_WARNING_RATIO,
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


def test_record_demand_sample_ranks_current_window_against_monthly_peaks() -> None:
    history = {
        "samples": [],
        "daily_peaks": [],
        "monthly_peak_windows": [
            {
                "timestamp": "2026-06-01T18:15:00+00:00",
                "demand_w": 5000.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-02T17:30:00+00:00",
                "demand_w": 4500.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-03T07:45:00+00:00",
                "demand_w": 4000.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-05-31T20:00:00+00:00",
                "demand_w": 8000.0,
                "window_minutes": 15,
            },
        ],
    }

    result = record_demand_sample(
        history,
        circuit_id="mains",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=4100.0,
        settings=DemandSettings(),
    )

    assert DEFAULT_PEAK_RANK_COUNT == 3
    assert DEFAULT_PEAK_WARNING_RATIO == 0.9
    assert result.monthly_peak_rank == 3
    assert result.monthly_peak_status == "monthly_peak"
    assert result.monthly_peak_cutoff_w == 4000.0
    assert result.monthly_peak_usage_percent == 102.5
    assert result.monthly_peak_warning is not None
    assert result.monthly_peak_warning.features == {
        "current_demand_w": 4100.0,
        "monthly_peak_rank": 3.0,
        "monthly_peak_cutoff_w": 4000.0,
        "monthly_peak_usage_percent": 102.5,
        "peak_rank_count": 3.0,
        "peak_warning_ratio": 0.9,
        "demand_window_minutes": 15.0,
    }
    assert history["monthly_peak_windows"][:4] == [
        {
            "timestamp": "2026-05-31T20:00:00+00:00",
            "demand_w": 8000.0,
            "window_minutes": 15,
        },
        {
            "timestamp": "2026-06-01T18:15:00+00:00",
            "demand_w": 5000.0,
            "window_minutes": 15,
        },
        {
            "timestamp": "2026-06-02T17:30:00+00:00",
            "demand_w": 4500.0,
            "window_minutes": 15,
        },
        {
            "timestamp": "2026-06-03T12:15:00+00:00",
            "demand_w": 4100.0,
            "window_minutes": 15,
        },
    ]


def test_record_demand_sample_marks_near_monthly_peak_without_new_top_rank() -> None:
    history = {
        "samples": [],
        "daily_peaks": [],
        "monthly_peak_windows": [
            {
                "timestamp": "2026-06-01T18:15:00+00:00",
                "demand_w": 5000.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-02T17:30:00+00:00",
                "demand_w": 4500.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-03T07:45:00+00:00",
                "demand_w": 4000.0,
                "window_minutes": 15,
            },
        ],
    }

    result = record_demand_sample(
        history,
        circuit_id="mains",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=3700.0,
        settings=DemandSettings(),
    )

    assert result.monthly_peak_rank == 4
    assert result.monthly_peak_status == "near_monthly_peak"
    assert result.monthly_peak_cutoff_w == 4000.0
    assert result.monthly_peak_usage_percent == 92.5
    assert result.monthly_peak_warning is not None


def test_record_demand_sample_keeps_low_monthly_demand_quiet() -> None:
    history = {
        "samples": [],
        "daily_peaks": [],
        "monthly_peak_windows": [
            {
                "timestamp": "2026-06-01T18:15:00+00:00",
                "demand_w": 5000.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-02T17:30:00+00:00",
                "demand_w": 4500.0,
                "window_minutes": 15,
            },
            {
                "timestamp": "2026-06-03T07:45:00+00:00",
                "demand_w": 4000.0,
                "window_minutes": 15,
            },
        ],
    }

    result = record_demand_sample(
        history,
        circuit_id="mains",
        timestamp=datetime(2026, 6, 3, 12, 15, tzinfo=UTC),
        real_power_w=3000.0,
        settings=DemandSettings(),
    )

    assert result.monthly_peak_rank == 4
    assert result.monthly_peak_status == "below_monthly_peak"
    assert result.monthly_peak_cutoff_w == 4000.0
    assert result.monthly_peak_usage_percent == 75.0
    assert result.monthly_peak_warning is None
