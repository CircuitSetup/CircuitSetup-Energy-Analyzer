"""Home Assistant local-calendar helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, tzinfo
from zoneinfo import ZoneInfo

TimeZone = str | tzinfo | None


def as_utc(dt: datetime) -> datetime:
    """Return a timezone-aware datetime normalized to UTC."""
    if dt.tzinfo is None:
        msg = "local calendar helpers require timezone-aware datetimes"
        raise ValueError(msg)
    return dt.astimezone(UTC)


def as_ha_local(dt: datetime, time_zone: TimeZone) -> datetime:
    """Return a timestamp converted to the configured Home Assistant timezone."""
    return as_utc(dt).astimezone(_time_zone_info(time_zone))


def local_date(dt: datetime, time_zone: TimeZone) -> date:
    """Return the Home Assistant local calendar date for a timestamp."""
    return as_ha_local(dt, time_zone).date()


def local_day_start(dt: datetime, time_zone: TimeZone) -> datetime:
    """Return the UTC instant for midnight on the Home Assistant local day."""
    local_dt = as_ha_local(dt, time_zone)
    return datetime.combine(
        local_dt.date(),
        time.min,
        tzinfo=local_dt.tzinfo,
    ).astimezone(UTC)


def local_day_end(day: date, time_zone: TimeZone) -> datetime:
    """Return the UTC instant for the end of a Home Assistant local day."""
    return datetime.combine(
        day,
        time.max,
        tzinfo=_time_zone_info(time_zone),
    ).astimezone(UTC)


def local_day_time(day: date, clock_time: time, time_zone: TimeZone) -> datetime:
    """Return the UTC instant for a Home Assistant local wall-clock time."""
    return datetime.combine(
        day,
        clock_time,
        tzinfo=_time_zone_info(time_zone),
    ).astimezone(UTC)


def local_month_key(dt: datetime, time_zone: TimeZone) -> str:
    """Return YYYY-MM for the Home Assistant local calendar month."""
    return as_ha_local(dt, time_zone).strftime("%Y-%m")


def _time_zone_info(time_zone: TimeZone) -> tzinfo:
    if isinstance(time_zone, str):
        normalized = time_zone.strip()
        return ZoneInfo(normalized) if normalized else UTC
    return time_zone or UTC
