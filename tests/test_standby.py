from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.standby import (
    DEFAULT_STANDBY_THRESHOLD_W,
    DEFAULT_STANDBY_WINDOW_HOURS,
    StandbySettings,
    record_standby_sample,
)


def test_record_standby_sample_estimates_always_on_from_low_bin() -> None:
    history = {
        "samples": [
            {"timestamp": f"2026-06-03T{hour:02d}:00:00+00:00", "real_power_w": value}
            for hour, value in enumerate(
                [3, 4, 5, 5, 6, 8, 12, 20, 45, 80, 120, 300]
            )
        ],
    }

    result = record_standby_sample(
        history,
        circuit_id="office",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        real_power_w=6.0,
        settings=StandbySettings(min_samples=6),
    )

    assert DEFAULT_STANDBY_WINDOW_HOURS == 48
    assert DEFAULT_STANDBY_THRESHOLD_W == 8.0
    assert result.always_on_power_w == 3.0
    assert result.standby_threshold_w == 8.0
    assert result.status == "standby"
    assert result.features == {
        "always_on_power_w": 3.0,
        "current_power_w": 6.0,
        "standby_threshold_w": 8.0,
        "sample_count": 13.0,
        "window_hours": 48.0,
    }


def test_record_standby_sample_uses_lowest_power_in_default_48h_window() -> None:
    history = {
        "samples": [
            {
                "timestamp": "2026-06-01T06:00:00+00:00",
                "real_power_w": 1.0,
            },
            {
                "timestamp": "2026-06-02T04:00:00+00:00",
                "real_power_w": 2.4,
            },
            {
                "timestamp": "2026-06-02T20:00:00+00:00",
                "real_power_w": 4.0,
            },
        ],
    }

    result = record_standby_sample(
        history,
        circuit_id="router",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        real_power_w=6.0,
        settings=StandbySettings(min_samples=3),
    )

    assert result.always_on_power_w == 2.4
    assert result.window_hours == 48
    assert history["samples"] == [
        {"timestamp": "2026-06-02T04:00:00+00:00", "real_power_w": 2.4},
        {"timestamp": "2026-06-02T20:00:00+00:00", "real_power_w": 4.0},
        {"timestamp": "2026-06-03T12:00:00+00:00", "real_power_w": 6.0},
    ]


def test_record_standby_sample_uses_absolute_low_watermark_not_percentile() -> None:
    history = {
        "samples": [
            {
                "timestamp": "2026-06-02T00:00:00+00:00",
                "real_power_w": 1.1,
            },
            *[
                {
                    "timestamp": (
                        f"2026-06-02T{minute // 60:02d}:"
                        f"{minute % 60:02d}:00+00:00"
                    ),
                    "real_power_w": 4.0 + minute,
                }
                for minute in range(1, 101)
            ],
        ],
    }

    result = record_standby_sample(
        history,
        circuit_id="router",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        real_power_w=6.0,
        settings=StandbySettings(min_samples=3),
    )

    assert result.always_on_power_w == 1.1


def test_record_standby_sample_marks_on_above_threshold() -> None:
    result = record_standby_sample(
        {"samples": []},
        circuit_id="office",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        real_power_w=15.0,
        settings=StandbySettings(standby_threshold_w=8.0, min_samples=1),
    )

    assert result.status == "on"
    assert result.current_power_w == 15.0


def test_record_standby_sample_flags_configured_always_on_limit() -> None:
    history = {
        "samples": [
            {"timestamp": f"2026-06-03T{hour:02d}:00:00+00:00", "real_power_w": 45.0}
            for hour in range(8)
        ],
    }

    result = record_standby_sample(
        history,
        circuit_id="garage",
        timestamp=datetime(2026, 6, 3, 8, 0, tzinfo=UTC),
        real_power_w=46.0,
        settings=StandbySettings(always_on_alert_w=25.0, min_samples=6),
    )

    assert result.always_on_power_w == 45.0
    assert result.always_on_limit_usage == 180.0
    assert result.limit_exceeded is not None
    assert result.limit_exceeded.features == {
        "always_on_power_w": 45.0,
        "always_on_alert_w": 25.0,
        "always_on_limit_usage": 180.0,
        "current_power_w": 46.0,
        "sample_count": 9.0,
        "window_hours": 48.0,
    }


def test_record_standby_sample_prunes_old_samples_and_waits_for_learning() -> None:
    history = {
        "samples": [
            {"timestamp": "2026-06-01T00:00:00+00:00", "real_power_w": 2.0},
            {"timestamp": "2026-06-03T11:00:00+00:00", "real_power_w": 4.0},
        ],
    }

    result = record_standby_sample(
        history,
        circuit_id="office",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        real_power_w=5.0,
        settings=StandbySettings(min_samples=4),
    )

    assert result.status == "learning"
    assert result.always_on_power_w == 0.0
    assert history["samples"] == [
        {"timestamp": "2026-06-03T11:00:00+00:00", "real_power_w": 4.0},
        {"timestamp": "2026-06-03T12:00:00+00:00", "real_power_w": 5.0},
    ]
