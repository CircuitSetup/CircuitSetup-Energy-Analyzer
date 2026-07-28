from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from .local_time import TimeZone, as_ha_local, local_date

DEFAULT_USAGE_WINDOW_DAYS = 7
DEFAULT_DAILY_USAGE_SPIKE_RATIO = 0.25
_MAX_DERIVED_ENERGY_INTERVAL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class EnergyUsageSettings:
    """User-tunable daily energy usage spike settings."""

    window_days: int = DEFAULT_USAGE_WINDOW_DAYS
    daily_spike_ratio: float = DEFAULT_DAILY_USAGE_SPIKE_RATIO


@dataclass(frozen=True, slots=True)
class EnergyUsageSpike:
    """Evidence that today's energy use is high versus the learned window."""

    circuit_id: str
    date: str
    daily_usage_kwh: float
    baseline_total_kwh: float
    baseline_day_count: int
    window_days: int
    threshold_ratio: float
    threshold_kwh: float
    daily_usage_share: float
    features: dict[str, float]


@dataclass(frozen=True, slots=True)
class EnergyUsageResult:
    """Latest compact usage summary for a circuit."""

    circuit_id: str
    date: str
    daily_usage_kwh: float
    average_kwh_per_day: float | None
    baseline_total_kwh: float
    baseline_day_count: int
    window_days: int
    threshold_ratio: float
    threshold_kwh: float
    daily_usage_share: float
    tracking_status: str
    status_reason: str
    spike: EnergyUsageSpike | None = None


def derive_cumulative_energy_from_power(
    history: dict[str, Any],
    *,
    timestamp: datetime,
    power_w: float | None,
) -> float | None:
    """Maintain a cumulative kWh helper for a power-only circuit."""
    energy_kwh = _float_or_none(history.get("derived_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("derived_energy_last_sample_at"))
    last_power_w = _float_or_none(history.get("derived_energy_last_power_w"))

    if power_w is None:
        history["derived_energy_last_sample_at"] = timestamp.isoformat()
        history.pop("derived_energy_last_power_w", None)
        return energy_kwh

    energy_kwh = energy_kwh or 0.0
    if last_sample_at is not None and last_power_w is not None:
        elapsed = timestamp - last_sample_at
        if timedelta(0) < elapsed <= _MAX_DERIVED_ENERGY_INTERVAL:
            average_power_w = (max(last_power_w, 0.0) + max(power_w, 0.0)) / 2
            energy_kwh += average_power_w * elapsed.total_seconds() / 3_600_000

    history["derived_energy_kwh"] = round(energy_kwh, 6)
    history["derived_energy_last_sample_at"] = timestamp.isoformat()
    history["derived_energy_last_power_w"] = float(power_w)
    return float(history["derived_energy_kwh"])


def record_energy_usage(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    energy_kwh: float | None,
    settings: EnergyUsageSettings,
    retention_days: int = 45,
    time_zone: TimeZone = None,
    baseline_eligible: bool = True,
) -> EnergyUsageResult | None:
    """Fold a cumulative kWh sample into daily usage history."""
    if energy_kwh is None:
        return None

    window_days = max(int(settings.window_days), 1)
    threshold_ratio = max(float(settings.daily_spike_ratio), 0.0)
    today = _calendar_date(timestamp, time_zone).isoformat()
    days = _coerce_days(history.get("days"))
    _update_day_coverage(
        history,
        days,
        timestamp=timestamp,
        today=today,
        time_zone=time_zone,
    )
    prior_days = _prior_days(days, today, window_days)
    average_days = _prior_days(days, today, DEFAULT_USAGE_WINDOW_DAYS)

    last_energy = _float_or_none(history.get("last_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("last_sample_at"))
    initial_sample = last_energy is None or last_sample_at is None
    delta_kwh = 0.0 if initial_sample else max(float(energy_kwh) - last_energy, 0.0)

    if delta_kwh > 0.0 or not baseline_eligible:
        _add_daily_usage(
            days,
            today,
            delta_kwh,
            baseline_eligible=baseline_eligible,
        )

    history["last_energy_kwh"] = float(energy_kwh)
    history["last_sample_at"] = timestamp.isoformat()
    history["days"] = _prune_days(
        days,
        timestamp,
        retention_days,
        time_zone=time_zone,
    )

    today_usage = _round_kwh(_usage_for_date(days, today))
    average_kwh_per_day = (
        _round_kwh(sum(day["usage_kwh"] for day in average_days) / len(average_days))
        if average_days
        else None
    )
    baseline_total = _round_kwh(sum(day["usage_kwh"] for day in prior_days))
    baseline_day_count = len(prior_days)
    threshold_kwh = _round_kwh(baseline_total * threshold_ratio)
    daily_usage_share = (
        round(today_usage / baseline_total, 4) if baseline_total > 0.0 else 0.0
    )
    has_observed_positive_delta = any(
        float(day["usage_kwh"]) > 0.0 for day in days
    )
    if initial_sample:
        tracking_status = "waiting_for_delta"
        status_reason = "first_cumulative_sample"
    elif delta_kwh <= 0.0 and not has_observed_positive_delta:
        tracking_status = "waiting_for_delta"
        status_reason = "no_positive_delta_observed"
    elif baseline_day_count < window_days:
        tracking_status = "learning"
        status_reason = "building_energy_window"
    elif delta_kwh <= 0.0:
        tracking_status = "tracking"
        status_reason = "no_delta_today"
    else:
        tracking_status = "tracking"
        status_reason = "observed_energy_delta"

    result = EnergyUsageResult(
        circuit_id=circuit_id,
        date=today,
        daily_usage_kwh=today_usage,
        average_kwh_per_day=average_kwh_per_day,
        baseline_total_kwh=baseline_total,
        baseline_day_count=baseline_day_count,
        window_days=window_days,
        threshold_ratio=threshold_ratio,
        threshold_kwh=threshold_kwh,
        daily_usage_share=daily_usage_share,
        tracking_status=tracking_status,
        status_reason=status_reason,
    )
    if (
        baseline_day_count < window_days
        or baseline_total <= 0.0
        or threshold_kwh <= 0.0
        or today_usage <= threshold_kwh
    ):
        return result

    spike = EnergyUsageSpike(
        circuit_id=circuit_id,
        date=today,
        daily_usage_kwh=today_usage,
        baseline_total_kwh=baseline_total,
        baseline_day_count=baseline_day_count,
        window_days=window_days,
        threshold_ratio=threshold_ratio,
        threshold_kwh=threshold_kwh,
        daily_usage_share=daily_usage_share,
        features={
            "daily_usage_kwh": today_usage,
            "baseline_total_kwh": baseline_total,
            "baseline_window_days": float(window_days),
            "baseline_day_count": float(baseline_day_count),
            "threshold_kwh": threshold_kwh,
            "threshold_ratio": threshold_ratio,
            "daily_usage_share": daily_usage_share,
        },
    )
    return replace(
        result,
        tracking_status="over_threshold",
        status_reason="daily_usage_above_threshold",
        spike=spike,
    )


def _coerce_days(raw_days: Any) -> list[dict[str, float | str | bool]]:
    days: list[dict[str, float | str | bool]] = []
    if not isinstance(raw_days, list):
        return days
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        date = raw_day.get("date")
        usage = _float_or_none(raw_day.get("usage_kwh"))
        if not isinstance(date, str) or usage is None:
            continue
        day: dict[str, float | str | bool] = {
            "date": date,
            "usage_kwh": _round_kwh(max(usage, 0.0)),
        }
        if isinstance(raw_day.get("complete"), bool):
            day["complete"] = raw_day["complete"]
        if isinstance(raw_day.get("baseline_eligible"), bool):
            day["baseline_eligible"] = raw_day["baseline_eligible"]
        days.append(day)
    return days


def _prior_days(
    days: list[dict[str, float | str | bool]],
    today: str,
    window_days: int,
) -> list[dict[str, float]]:
    prior = [
        {"date": str(day["date"]), "usage_kwh": float(day["usage_kwh"])}
        for day in days
        if (
            str(day["date"]) < today
            and day.get("complete") is True
            and day.get("baseline_eligible") is not False
        )
    ]
    prior.sort(key=lambda day: day["date"])
    return prior[-window_days:]


def _add_daily_usage(
    days: list[dict[str, float | str | bool]],
    date: str,
    delta_kwh: float,
    *,
    baseline_eligible: bool,
) -> None:
    for day in days:
        if day["date"] == date:
            day["usage_kwh"] = _round_kwh(float(day["usage_kwh"]) + delta_kwh)
            if not baseline_eligible:
                day["baseline_eligible"] = False
            return
    day: dict[str, float | str | bool] = {
        "date": date,
        "usage_kwh": _round_kwh(delta_kwh),
    }
    if not baseline_eligible:
        day["baseline_eligible"] = False
    days.append(day)


def _usage_for_date(
    days: list[dict[str, float | str | bool]],
    date: str,
) -> float:
    return sum(float(day["usage_kwh"]) for day in days if day["date"] == date)


def _prune_days(
    days: list[dict[str, float | str | bool]],
    timestamp: datetime,
    retention_days: int,
    *,
    time_zone: TimeZone = None,
) -> list[dict[str, float | str | bool]]:
    cutoff = (
        _calendar_date(timestamp, time_zone) - timedelta(days=max(retention_days, 1))
    ).isoformat()
    return sorted(
        (day for day in days if str(day["date"]) >= cutoff),
        key=lambda day: str(day["date"]),
    )


def _calendar_date(timestamp: datetime, time_zone: TimeZone) -> date:
    if time_zone is None or timestamp.tzinfo is None:
        return timestamp.date()
    return local_date(timestamp, time_zone)


def _update_day_coverage(
    history: dict[str, Any],
    days: list[dict[str, float | str | bool]],
    *,
    timestamp: datetime,
    today: str,
    time_zone: TimeZone,
) -> None:
    """Mark a day complete only when samples bracket both local midnights."""
    calendar_timestamp = _calendar_datetime(timestamp, time_zone)
    coverage_date = str(history.get("coverage_date") or "")
    first_sample = _datetime_or_none(history.get("coverage_first_sample_at"))
    last_sample = _datetime_or_none(history.get("coverage_last_sample_at"))
    if coverage_date and coverage_date < today and first_sample and last_sample:
        first_calendar = _calendar_datetime(first_sample, time_zone)
        last_calendar = _calendar_datetime(last_sample, time_zone)
        next_date = last_calendar.date() + timedelta(days=1)
        bracketed = (
            coverage_date == last_calendar.date().isoformat()
            and first_calendar.date() == last_calendar.date()
            and next_date == calendar_timestamp.date()
            and _seconds_after_midnight(first_calendar) <= 15 * 60
            and _seconds_after_midnight(last_calendar) >= 23 * 3600 + 45 * 60
            and _seconds_after_midnight(calendar_timestamp) <= 15 * 60
            and 0.0 <= (timestamp - last_sample).total_seconds() <= 30 * 60
        )
        if bracketed:
            for day in days:
                if day.get("date") == coverage_date:
                    day["complete"] = True
                    break

    if coverage_date != today:
        history["coverage_date"] = today
        history["coverage_first_sample_at"] = timestamp.isoformat()
    history["coverage_last_sample_at"] = timestamp.isoformat()


def _calendar_datetime(timestamp: datetime, time_zone: TimeZone) -> datetime:
    if time_zone is None or timestamp.tzinfo is None:
        return timestamp
    return as_ha_local(timestamp, time_zone)


def _seconds_after_midnight(timestamp: datetime) -> int:
    return timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_kwh(value: float) -> float:
    return round(float(value), 3)
