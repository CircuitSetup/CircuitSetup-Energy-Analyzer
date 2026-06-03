from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

DEFAULT_USAGE_WINDOW_DAYS = 7
DEFAULT_DAILY_USAGE_SPIKE_RATIO = 0.25


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
    baseline_total_kwh: float
    baseline_day_count: int
    window_days: int
    threshold_ratio: float
    threshold_kwh: float
    daily_usage_share: float
    spike: EnergyUsageSpike | None = None


def record_energy_usage(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    energy_kwh: float | None,
    settings: EnergyUsageSettings,
    retention_days: int = 45,
) -> EnergyUsageResult | None:
    """Fold a cumulative kWh sample into daily usage history."""
    if energy_kwh is None:
        return None

    window_days = max(int(settings.window_days), 1)
    threshold_ratio = max(float(settings.daily_spike_ratio), 0.0)
    today = timestamp.date().isoformat()
    days = _coerce_days(history.get("days"))
    prior_days = _prior_days(days, today, window_days)

    last_energy = _float_or_none(history.get("last_energy_kwh"))
    last_sample_at = _datetime_or_none(history.get("last_sample_at"))
    if last_energy is None or last_sample_at is None:
        delta_kwh = 0.0
    else:
        delta_kwh = max(float(energy_kwh) - last_energy, 0.0)

    if delta_kwh > 0.0:
        _add_daily_usage(days, today, delta_kwh)

    history["last_energy_kwh"] = float(energy_kwh)
    history["last_sample_at"] = timestamp.isoformat()
    history["days"] = _prune_days(days, timestamp, retention_days)

    today_usage = _round_kwh(_usage_for_date(days, today))
    baseline_total = _round_kwh(sum(day["usage_kwh"] for day in prior_days))
    baseline_day_count = len(prior_days)
    threshold_kwh = _round_kwh(baseline_total * threshold_ratio)
    daily_usage_share = (
        round(today_usage / baseline_total, 4) if baseline_total > 0.0 else 0.0
    )
    result = EnergyUsageResult(
        circuit_id=circuit_id,
        date=today,
        daily_usage_kwh=today_usage,
        baseline_total_kwh=baseline_total,
        baseline_day_count=baseline_day_count,
        window_days=window_days,
        threshold_ratio=threshold_ratio,
        threshold_kwh=threshold_kwh,
        daily_usage_share=daily_usage_share,
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
    return replace(result, spike=spike)


def _coerce_days(raw_days: Any) -> list[dict[str, float | str]]:
    days: list[dict[str, float | str]] = []
    if not isinstance(raw_days, list):
        return days
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        date = raw_day.get("date")
        usage = _float_or_none(raw_day.get("usage_kwh"))
        if not isinstance(date, str) or usage is None:
            continue
        days.append({"date": date, "usage_kwh": _round_kwh(max(usage, 0.0))})
    return days


def _prior_days(
    days: list[dict[str, float | str]],
    today: str,
    window_days: int,
) -> list[dict[str, float]]:
    prior = [
        {"date": str(day["date"]), "usage_kwh": float(day["usage_kwh"])}
        for day in days
        if str(day["date"]) < today
    ]
    prior.sort(key=lambda day: day["date"])
    return prior[-window_days:]


def _add_daily_usage(
    days: list[dict[str, float | str]],
    date: str,
    delta_kwh: float,
) -> None:
    for day in days:
        if day["date"] == date:
            day["usage_kwh"] = _round_kwh(float(day["usage_kwh"]) + delta_kwh)
            return
    days.append({"date": date, "usage_kwh": _round_kwh(delta_kwh)})


def _usage_for_date(days: list[dict[str, float | str]], date: str) -> float:
    return sum(float(day["usage_kwh"]) for day in days if day["date"] == date)


def _prune_days(
    days: list[dict[str, float | str]],
    timestamp: datetime,
    retention_days: int,
) -> list[dict[str, float | str]]:
    cutoff = (timestamp.date() - timedelta(days=max(retention_days, 1))).isoformat()
    return sorted(
        (day for day in days if str(day["date"]) >= cutoff),
        key=lambda day: str(day["date"]),
    )


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
