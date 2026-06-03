from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

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
    cycle_cost: float
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
) -> CostResult | None:
    """Fold a cumulative kWh sample into billing-cycle cost history."""
    if energy_kwh is None:
        return None

    start_day = _cycle_start_day(settings.cycle_start_day)
    cycle_start = _cycle_start_for_date(timestamp.date(), start_day)
    cycle_end = _next_cycle_start(cycle_start, start_day)
    current_rate, rate_name, is_tou_active = _active_rate(timestamp, settings)
    cycle_cost = _existing_cycle_cost(history, cycle_start)

    last_energy = _float_or_none(history.get("last_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("last_sample_at"))
    delta_kwh = 0.0
    if (
        current_rate is not None
        and last_energy is not None
        and last_sample_at is not None
        and last_sample_at.date() >= cycle_start
    ):
        delta_kwh = max(float(energy_kwh) - last_energy, 0.0)
        cycle_cost += delta_kwh * current_rate

    cycle_cost = _round_money(cycle_cost)
    delta_cost = _round_money(delta_kwh * (current_rate or 0.0))
    elapsed_days = max((timestamp.date() - cycle_start).days + 1, 1)
    cycle_days = max((cycle_end - cycle_start).days, 1)
    projected_cycle_cost = _round_money(cycle_cost * cycle_days / elapsed_days)
    history["cycle_start"] = cycle_start.isoformat()
    history["cycle_end"] = cycle_end.isoformat()
    history["cycle_cost"] = cycle_cost
    history["last_energy_kwh"] = float(energy_kwh)
    history["last_sample_at"] = timestamp.isoformat()

    return CostResult(
        circuit_id=circuit_id,
        cycle_start=cycle_start.isoformat(),
        cycle_end=cycle_end.isoformat(),
        current_rate_per_kwh=round(current_rate or 0.0, 4),
        active_rate_name=rate_name,
        delta_kwh=_round_kwh(delta_kwh),
        delta_cost=delta_cost,
        cycle_cost=cycle_cost,
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
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
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
