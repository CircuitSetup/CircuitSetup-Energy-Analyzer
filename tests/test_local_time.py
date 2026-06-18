from __future__ import annotations

from datetime import UTC, date, datetime, time

from custom_components.circuitsetup_energy_analyzer.local_time import (
    as_ha_local,
    local_date,
    local_day_time,
    local_day_type,
    local_time_bucket,
)


def test_local_calendar_uses_ha_timezone_when_utc_date_differs() -> None:
    timestamp = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)

    assert as_ha_local(timestamp, "America/New_York").isoformat() == (
        "2026-05-31T23:30:00-04:00"
    )
    assert local_date(timestamp, "America/New_York") == date(2026, 5, 31)
    assert local_day_type(timestamp, "America/New_York") == "weekend"
    assert local_time_bucket(timestamp, "America/New_York") == "evening"


def test_local_day_time_returns_utc_instant_for_wall_clock_time() -> None:
    assert local_day_time(
        date(2026, 5, 24),
        time(12, 0),
        "America/New_York",
    ) == datetime(2026, 5, 24, 16, 0, tzinfo=UTC)


def test_local_calendar_keeps_dst_transition_samples_on_same_local_day() -> None:
    assert local_date(
        datetime(2026, 3, 8, 6, 30, tzinfo=UTC),
        "America/New_York",
    ) == date(2026, 3, 8)
    assert local_date(
        datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
        "America/New_York",
    ) == date(2026, 3, 8)

    assert local_date(
        datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        "America/New_York",
    ) == date(2026, 11, 1)
    assert local_date(
        datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        "America/New_York",
    ) == date(2026, 11, 1)

    assert local_date(
        datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
        "Europe/London",
    ) == date(2026, 3, 29)
    assert local_date(
        datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        "Europe/London",
    ) == date(2026, 3, 29)

    assert local_date(
        datetime(2026, 10, 3, 16, 30, tzinfo=UTC),
        "Australia/Sydney",
    ) == date(2026, 10, 4)
    assert local_date(
        datetime(2026, 10, 3, 17, 30, tzinfo=UTC),
        "Australia/Sydney",
    ) == date(2026, 10, 4)
