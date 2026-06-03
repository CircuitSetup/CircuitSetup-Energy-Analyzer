from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

DEFAULT_BILLING_CYCLE_START_DAY = 1
DEFAULT_BUDGET_ALERT_RATIO = 1.0
DEFAULT_BUDGET_MIN_ELAPSED_DAYS = 3


@dataclass(frozen=True, slots=True)
class BillingCycleSettings:
    """User-tunable billing-cycle energy budget settings."""

    cycle_start_day: int = DEFAULT_BILLING_CYCLE_START_DAY
    budget_kwh: float | None = None
    budget_alert_ratio: float = DEFAULT_BUDGET_ALERT_RATIO
    min_elapsed_days: int = DEFAULT_BUDGET_MIN_ELAPSED_DAYS


@dataclass(frozen=True, slots=True)
class BillingCycleBudgetEvidence:
    """Evidence that current-cycle usage is likely to exceed a configured budget."""

    circuit_id: str
    cycle_start: str
    cycle_end: str
    cycle_usage_kwh: float
    projected_cycle_kwh: float
    budget_kwh: float
    budget_usage_percent: float
    projected_budget_usage_percent: float
    budget_alert_ratio: float
    elapsed_days: int
    cycle_days: int
    features: dict[str, float]


@dataclass(frozen=True, slots=True)
class BillingCycleResult:
    """Latest billing-cycle usage and forecast for a circuit."""

    circuit_id: str
    cycle_start: str
    cycle_end: str
    cycle_usage_kwh: float
    projected_cycle_kwh: float
    elapsed_days: int
    cycle_days: int
    cycle_start_day: int
    budget_kwh: float | None = None
    budget_alert_ratio: float = DEFAULT_BUDGET_ALERT_RATIO
    budget_usage_percent: float = 0.0
    projected_budget_usage_percent: float = 0.0
    status: str = "no_budget"
    budget_exceeded: BillingCycleBudgetEvidence | None = None


def record_billing_cycle_usage(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    energy_kwh: float | None,
    settings: BillingCycleSettings,
) -> BillingCycleResult | None:
    """Fold a cumulative kWh sample into current billing-cycle usage."""
    if energy_kwh is None:
        return None

    start_day = _cycle_start_day(settings.cycle_start_day)
    cycle_start = _cycle_start_for_date(timestamp.date(), start_day)
    cycle_end = _next_cycle_start(cycle_start, start_day)
    cycle_usage = _existing_cycle_usage(history, cycle_start)

    last_energy = _float_or_none(history.get("last_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("last_sample_at"))
    if (
        last_energy is not None
        and last_sample_at is not None
        and last_sample_at.date() >= cycle_start
    ):
        cycle_usage += max(float(energy_kwh) - last_energy, 0.0)

    cycle_usage = _round_kwh(cycle_usage)
    history["cycle_start"] = cycle_start.isoformat()
    history["cycle_end"] = cycle_end.isoformat()
    history["cycle_usage_kwh"] = cycle_usage
    history["last_energy_kwh"] = float(energy_kwh)
    history["last_sample_at"] = timestamp.isoformat()

    elapsed_days = max((timestamp.date() - cycle_start).days + 1, 1)
    cycle_days = max((cycle_end - cycle_start).days, 1)
    projected_cycle = _round_kwh(cycle_usage * cycle_days / elapsed_days)
    budget_kwh = _positive_float_or_none(settings.budget_kwh)
    budget_alert_ratio = max(float(settings.budget_alert_ratio), 0.0)
    min_elapsed_days = max(int(settings.min_elapsed_days), 1)
    result = BillingCycleResult(
        circuit_id=circuit_id,
        cycle_start=cycle_start.isoformat(),
        cycle_end=cycle_end.isoformat(),
        cycle_usage_kwh=cycle_usage,
        projected_cycle_kwh=projected_cycle,
        elapsed_days=elapsed_days,
        cycle_days=cycle_days,
        cycle_start_day=start_day,
        budget_kwh=budget_kwh,
        budget_alert_ratio=budget_alert_ratio,
    )
    if budget_kwh is None:
        return result

    budget_usage = round((cycle_usage / budget_kwh) * 100, 1)
    projected_budget_usage = round((projected_cycle / budget_kwh) * 100, 1)
    alert_threshold_kwh = budget_kwh * budget_alert_ratio
    status = _budget_status(
        cycle_usage,
        projected_cycle,
        budget_kwh,
        alert_threshold_kwh,
        elapsed_days,
        min_elapsed_days,
    )
    result = replace(
        result,
        budget_usage_percent=budget_usage,
        projected_budget_usage_percent=projected_budget_usage,
        status=status,
    )
    if status not in {"over_budget", "projected_over_budget"}:
        return result

    evidence = BillingCycleBudgetEvidence(
        circuit_id=circuit_id,
        cycle_start=cycle_start.isoformat(),
        cycle_end=cycle_end.isoformat(),
        cycle_usage_kwh=cycle_usage,
        projected_cycle_kwh=projected_cycle,
        budget_kwh=budget_kwh,
        budget_usage_percent=budget_usage,
        projected_budget_usage_percent=projected_budget_usage,
        budget_alert_ratio=budget_alert_ratio,
        elapsed_days=elapsed_days,
        cycle_days=cycle_days,
        features={
            "cycle_usage_kwh": cycle_usage,
            "projected_cycle_kwh": projected_cycle,
            "budget_kwh": budget_kwh,
            "budget_usage_percent": budget_usage,
            "projected_budget_usage_percent": projected_budget_usage,
            "budget_alert_ratio": budget_alert_ratio,
            "elapsed_days": float(elapsed_days),
            "cycle_days": float(cycle_days),
        },
    )
    return replace(result, budget_exceeded=evidence)


def _existing_cycle_usage(history: dict[str, Any], cycle_start: date) -> float:
    if history.get("cycle_start") != cycle_start.isoformat():
        return 0.0
    return max(_float_or_none(history.get("cycle_usage_kwh")) or 0.0, 0.0)


def _budget_status(
    cycle_usage_kwh: float,
    projected_cycle_kwh: float,
    budget_kwh: float,
    alert_threshold_kwh: float,
    elapsed_days: int,
    min_elapsed_days: int,
) -> str:
    if elapsed_days < min_elapsed_days:
        return "learning"
    if cycle_usage_kwh >= budget_kwh:
        return "over_budget"
    if projected_cycle_kwh >= alert_threshold_kwh:
        return "projected_over_budget"
    return "tracking"


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
        return DEFAULT_BILLING_CYCLE_START_DAY
    return min(max(parsed, 1), 31)


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


def _round_kwh(value: float) -> float:
    return round(float(value), 3)
