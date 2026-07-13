from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from .local_time import TimeZone, as_ha_local

DEFAULT_COST_CYCLE_START_DAY = 1
DEFAULT_RATE_NAME = "Default"


@dataclass(frozen=True, slots=True)
class CostSettings:
    """User-tunable energy cost settings for one circuit."""

    cycle_start_day: int = DEFAULT_COST_CYCLE_START_DAY
    default_rate_per_kwh: float | None = None
    tou_rate_per_kwh: float | None = None
    tou_start: str | None = None
    tou_end: str | None = None
    tou_weekdays: tuple[int, ...] = ()
    tou_name: str = "Peak"


@dataclass(frozen=True, slots=True)
class CostResult:
    """Latest billing-cycle cost estimate for one circuit."""

    circuit_id: str
    cycle_start: str
    cycle_end: str
    current_rate_per_kwh: float
    active_rate_name: str
    delta_kwh: float
    delta_cost: float
    cost_today: float | None
    cost_today_status: str
    cycle_cost: float
    cycle_cost_status: str
    projected_cycle_cost: float
    elapsed_days: int
    cycle_days: int
    cycle_start_day: int
    status: str


def record_cost_sample(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    energy_kwh: float | None,
    settings: CostSettings,
    time_zone: TimeZone = None,
) -> CostResult | None:
    """Fold a cumulative kWh sample into billing-cycle cost history."""
    if energy_kwh is None:
        return None

    start_day = _cycle_start_day(settings.cycle_start_day)
    calendar_timestamp = _calendar_datetime(timestamp, time_zone)
    cycle_start = _cycle_start_for_date(calendar_timestamp.date(), start_day)
    cycle_end = _next_cycle_start(cycle_start, start_day)
    current_rate, rate_name, is_tou_active = _active_rate(
        calendar_timestamp,
        settings,
    )
    cycle_key = cycle_start.isoformat()
    same_cycle = history.get("cycle_start") == cycle_key
    cycle_cost = _existing_cycle_cost(history, cycle_start)

    last_energy = _float_or_none(history.get("last_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("last_sample_at"))
    initial_sample = last_energy is None or last_sample_at is None
    delta_kwh = 0.0
    ambiguous_rate = False
    if (
        current_rate is not None
        and last_energy is not None
        and last_sample_at is not None
    ):
        delta_kwh = max(float(energy_kwh) - last_energy, 0.0)
        ambiguous_rate = (
            _calendar_datetime(last_sample_at, time_zone).date() < cycle_start
            or _interval_rate_is_ambiguous(
                last_sample_at,
                calendar_timestamp,
                settings,
                time_zone=time_zone,
            )
        )
        if not ambiguous_rate:
            cycle_cost += delta_kwh * current_rate

    cycle_cost = _round_money(cycle_cost)
    delta_cost = _round_money(
        0.0 if ambiguous_rate else delta_kwh * (current_rate or 0.0)
    )
    today = calendar_timestamp.date().isoformat()
    _update_completed_cost_days(
        history,
        timestamp=timestamp,
        today=today,
        delta_kwh=delta_kwh,
        time_zone=time_zone,
    )
    accumulated_today = (
        max(_float_or_none(history.get("cost_today")) or 0.0, 0.0)
        if history.get("cost_today_date") == today
        else 0.0
    )
    accumulated_today = _round_money(accumulated_today + delta_cost)
    crossed_local_date = (
        last_sample_at is not None
        and _calendar_datetime(last_sample_at, time_zone).date()
        != calendar_timestamp.date()
    )
    incomplete_interval = ambiguous_rate and delta_kwh > 0.0
    incomplete_daily_interval = (
        initial_sample
        or incomplete_interval
        or crossed_local_date and delta_kwh > 0.0
    )
    cost_today_status = (
        "unavailable"
        if current_rate is None
        or incomplete_daily_interval
        or (
            history.get("cost_today_date") == today
            and history.get("cost_today_status") == "unavailable"
        )
        else "actual"
    )
    cycle_cost_status = (
        "unavailable"
        if current_rate is None or initial_sample or incomplete_interval
        or (same_cycle and history.get("cycle_cost_status") == "unavailable")
        else "actual"
    )
    elapsed_days = max((calendar_timestamp.date() - cycle_start).days + 1, 1)
    cycle_days = max((cycle_end - cycle_start).days, 1)
    projected_cycle_cost = _round_money(cycle_cost * cycle_days / elapsed_days)
    history["cycle_start"] = cycle_key
    history["cycle_end"] = cycle_end.isoformat()
    history["cycle_cost"] = cycle_cost
    history["cost_today_date"] = today
    history["cost_today"] = accumulated_today
    history["cost_today_status"] = cost_today_status
    history["cycle_cost_status"] = cycle_cost_status
    history["last_energy_kwh"] = float(energy_kwh)
    history["last_sample_at"] = timestamp.isoformat()

    return CostResult(
        circuit_id=circuit_id,
        cycle_start=cycle_key,
        cycle_end=cycle_end.isoformat(),
        current_rate_per_kwh=round(current_rate or 0.0, 4),
        active_rate_name=rate_name,
        delta_kwh=_round_kwh(delta_kwh),
        delta_cost=delta_cost,
        cost_today=(
            accumulated_today if cost_today_status == "actual" else None
        ),
        cost_today_status=cost_today_status,
        cycle_cost=cycle_cost,
        cycle_cost_status=cycle_cost_status,
        projected_cycle_cost=projected_cycle_cost,
        elapsed_days=elapsed_days,
        cycle_days=cycle_days,
        cycle_start_day=start_day,
        status=_status(current_rate, is_tou_active),
    )


def _active_rate(
    timestamp: datetime,
    settings: CostSettings,
) -> tuple[float | None, str, bool]:
    tou_rate = _positive_float_or_none(settings.tou_rate_per_kwh)
    if tou_rate is not None and _tou_period_active(timestamp, settings):
        return tou_rate, str(settings.tou_name or "Peak"), True
    default_rate = _positive_float_or_none(settings.default_rate_per_kwh)
    if default_rate is None:
        return None, "", False
    return default_rate, DEFAULT_RATE_NAME, False


def _tou_period_active(timestamp: datetime, settings: CostSettings) -> bool:
    start = _time_or_none(settings.tou_start)
    end = _time_or_none(settings.tou_end)
    if start is None or end is None:
        return False
    weekdays = tuple(_weekday_value(day) for day in settings.tou_weekdays)
    if weekdays and timestamp.weekday() not in weekdays:
        return False
    current = timestamp.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _interval_rate_is_ambiguous(
    last_sample_at: datetime,
    timestamp: datetime,
    settings: CostSettings,
    *,
    time_zone: TimeZone,
) -> bool:
    last_calendar = _calendar_datetime(last_sample_at, time_zone)
    if last_calendar.date() != timestamp.date():
        return _positive_float_or_none(settings.tou_rate_per_kwh) is not None
    last_rate, _last_name, _last_tou = _active_rate(last_calendar, settings)
    current_rate, _current_name, _current_tou = _active_rate(timestamp, settings)
    if last_rate != current_rate:
        return True
    boundary_times = (
        _time_or_none(settings.tou_start),
        _time_or_none(settings.tou_end),
    )
    for boundary_time in boundary_times:
        if boundary_time is None:
            continue
        boundary = datetime.combine(
            timestamp.date(),
            boundary_time,
            tzinfo=timestamp.tzinfo,
        )
        if not last_calendar < boundary < timestamp:
            continue
        before_rate, _before_name, _before_tou = _active_rate(
            boundary - timedelta(microseconds=1),
            settings,
        )
        after_rate, _after_name, _after_tou = _active_rate(boundary, settings)
        if before_rate != after_rate:
            return True
    return False


def _existing_cycle_cost(history: dict[str, Any], cycle_start: date) -> float:
    if history.get("cycle_start") != cycle_start.isoformat():
        return 0.0
    return max(_float_or_none(history.get("cycle_cost")) or 0.0, 0.0)


def _cycle_start_for_date(current: date, start_day: int) -> date:
    candidate = date(
        current.year,
        current.month,
        _clamped_month_day(current, start_day),
    )
    if current >= candidate:
        return candidate
    previous = _shift_month(current.year, current.month, -1)
    return date(
        previous[0],
        previous[1],
        _clamped_month_day(date(previous[0], previous[1], 1), start_day),
    )


def _next_cycle_start(cycle_start: date, start_day: int) -> date:
    next_month = _shift_month(cycle_start.year, cycle_start.month, 1)
    return date(
        next_month[0],
        next_month[1],
        _clamped_month_day(date(next_month[0], next_month[1], 1), start_day),
    )


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    shifted = month + offset
    while shifted < 1:
        year -= 1
        shifted += 12
    while shifted > 12:
        year += 1
        shifted -= 12
    return year, shifted


def _clamped_month_day(value: date, start_day: int) -> int:
    return min(start_day, monthrange(value.year, value.month)[1])


def _cycle_start_day(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COST_CYCLE_START_DAY
    return min(max(parsed, 1), 31)


def _time_or_none(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            return None
        hour, minute = parts[:2]
        second = parts[2] if len(parts) == 3 else 0
        return time(hour=int(hour), minute=int(minute), second=int(second))
    except (TypeError, ValueError):
        return None


def _weekday_value(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return -1
    return parsed if 0 <= parsed <= 6 else -1


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calendar_datetime(value: datetime, time_zone: TimeZone) -> datetime:
    if time_zone is None or value.tzinfo is None:
        return value
    return as_ha_local(value, time_zone)


def _update_completed_cost_days(
    history: dict[str, Any],
    *,
    timestamp: datetime,
    today: str,
    delta_kwh: float,
    time_zone: TimeZone,
) -> None:
    """Retain a cost day only when samples bracket both midnights cleanly."""
    calendar_timestamp = _calendar_datetime(timestamp, time_zone)
    coverage_date = str(history.get("cost_coverage_date") or "")
    first_sample = _datetime_or_none(history.get("cost_coverage_first_sample_at"))
    last_sample = _datetime_or_none(history.get("cost_coverage_last_sample_at"))
    if coverage_date and coverage_date < today and first_sample and last_sample:
        first_calendar = _calendar_datetime(first_sample, time_zone)
        last_calendar = _calendar_datetime(last_sample, time_zone)
        bracketed = (
            coverage_date == last_calendar.date().isoformat()
            and first_calendar.date() == last_calendar.date()
            and last_calendar.date() + timedelta(days=1)
            == calendar_timestamp.date()
            and _seconds_after_midnight(first_calendar) <= 15 * 60
            and _seconds_after_midnight(last_calendar) >= 23 * 3600 + 45 * 60
            and _seconds_after_midnight(calendar_timestamp) <= 15 * 60
            and 0.0 <= (timestamp - last_sample).total_seconds() <= 30 * 60
            and delta_kwh == 0.0
            and history.get("cost_today_date") == coverage_date
            and history.get("cost_today_status") == "actual"
        )
        if bracketed:
            days = history.get("days")
            if not isinstance(days, list):
                days = []
            days = [
                item
                for item in days
                if isinstance(item, dict) and item.get("date") != coverage_date
            ]
            days.append(
                {
                    "date": coverage_date,
                    "cost": _round_money(
                        max(_float_or_none(history.get("cost_today")) or 0.0, 0.0)
                    ),
                    "complete": True,
                }
            )
            history["days"] = sorted(
                days,
                key=lambda item: str(item.get("date") or ""),
            )[-45:]

    if coverage_date != today:
        history["cost_coverage_date"] = today
        history["cost_coverage_first_sample_at"] = timestamp.isoformat()
    history["cost_coverage_last_sample_at"] = timestamp.isoformat()


def _seconds_after_midnight(timestamp: datetime) -> int:
    return timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second


def _positive_float_or_none(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(current_rate: float | None, is_tou_active: bool) -> str:
    if current_rate is None:
        return "unconfigured"
    return "tou_peak" if is_tou_active else "tracking"


def _round_kwh(value: float) -> float:
    return round(float(value), 3)


def _round_money(value: float) -> float:
    return round(float(value), 2)
