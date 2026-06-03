from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

DEFAULT_DEMAND_WINDOW_MINUTES = 15


@dataclass(frozen=True, slots=True)
class DemandSettings:
    """User-tunable rolling demand settings."""

    window_minutes: int = DEFAULT_DEMAND_WINDOW_MINUTES
    demand_limit_w: float | None = None


@dataclass(frozen=True, slots=True)
class DemandLimitEvidence:
    """Evidence that rolling demand exceeded a configured limit."""

    circuit_id: str
    date: str
    current_demand_w: float
    peak_demand_w: float
    demand_limit_w: float
    demand_limit_usage: float
    window_minutes: int
    features: dict[str, float]


@dataclass(frozen=True, slots=True)
class DemandResult:
    """Latest rolling demand state for a circuit."""

    circuit_id: str
    date: str
    current_demand_w: float
    peak_demand_w: float
    window_minutes: int
    demand_limit_w: float | None = None
    demand_limit_usage: float = 0.0
    limit_exceeded: DemandLimitEvidence | None = None


def record_demand_sample(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    real_power_w: float | None,
    settings: DemandSettings,
    retention_days: int = 45,
) -> DemandResult | None:
    """Fold a real-power sample into a rolling demand window."""
    if real_power_w is None:
        return None

    window_minutes = max(int(settings.window_minutes), 1)
    window = timedelta(minutes=window_minutes)
    today = timestamp.date().isoformat()
    samples = _coerce_samples(history.get("samples"))
    samples.append(
        {
            "timestamp": timestamp.isoformat(),
            "real_power_w": _round_w(max(float(real_power_w), 0.0)),
        }
    )
    samples = _prune_samples(samples, timestamp, window)

    current_demand = _time_weighted_average(samples, timestamp, window)
    daily_peaks = _coerce_daily_peaks(history.get("daily_peaks"))
    peak_demand = _record_daily_peak(daily_peaks, today, current_demand)

    history["samples"] = samples
    history["daily_peaks"] = _prune_daily_peaks(daily_peaks, timestamp, retention_days)

    limit_w = _positive_float_or_none(settings.demand_limit_w)
    limit_usage = (
        round((current_demand / limit_w) * 100, 1)
        if limit_w is not None and limit_w > 0.0
        else 0.0
    )
    result = DemandResult(
        circuit_id=circuit_id,
        date=today,
        current_demand_w=current_demand,
        peak_demand_w=peak_demand,
        window_minutes=window_minutes,
        demand_limit_w=limit_w,
        demand_limit_usage=limit_usage,
    )
    if limit_w is None or current_demand <= limit_w:
        return result

    evidence = DemandLimitEvidence(
        circuit_id=circuit_id,
        date=today,
        current_demand_w=current_demand,
        peak_demand_w=peak_demand,
        demand_limit_w=limit_w,
        demand_limit_usage=limit_usage,
        window_minutes=window_minutes,
        features={
            "current_demand_w": current_demand,
            "peak_demand_w": peak_demand,
            "demand_limit_w": limit_w,
            "demand_limit_usage": limit_usage,
            "demand_window_minutes": float(window_minutes),
        },
    )
    return replace(result, limit_exceeded=evidence)


def _coerce_samples(raw_samples: Any) -> list[dict[str, float | str]]:
    samples: list[dict[str, float | str]] = []
    if not isinstance(raw_samples, list):
        return samples
    for raw_sample in raw_samples:
        if not isinstance(raw_sample, dict):
            continue
        timestamp = raw_sample.get("timestamp")
        power = _float_or_none(raw_sample.get("real_power_w"))
        if not isinstance(timestamp, str) or power is None:
            continue
        if _datetime_or_none(timestamp) is None:
            continue
        samples.append(
            {
                "timestamp": timestamp,
                "real_power_w": _round_w(max(power, 0.0)),
            }
        )
    return sorted(samples, key=lambda sample: str(sample["timestamp"]))


def _coerce_daily_peaks(raw_peaks: Any) -> list[dict[str, float | str]]:
    peaks: list[dict[str, float | str]] = []
    if not isinstance(raw_peaks, list):
        return peaks
    for raw_peak in raw_peaks:
        if not isinstance(raw_peak, dict):
            continue
        date = raw_peak.get("date")
        peak = _float_or_none(raw_peak.get("peak_demand_w"))
        if not isinstance(date, str) or peak is None:
            continue
        peaks.append({"date": date, "peak_demand_w": _round_w(max(peak, 0.0))})
    return sorted(peaks, key=lambda peak: str(peak["date"]))


def _prune_samples(
    samples: list[dict[str, float | str]],
    timestamp: datetime,
    window: timedelta,
) -> list[dict[str, float | str]]:
    cutoff = timestamp - window
    return [
        sample
        for sample in samples
        if (sample_time := _datetime_or_none(sample["timestamp"])) is not None
        and sample_time >= cutoff
    ]


def _time_weighted_average(
    samples: list[dict[str, float | str]],
    timestamp: datetime,
    window: timedelta,
) -> float:
    if not samples:
        return 0.0
    if len(samples) == 1:
        return _round_w(float(samples[0]["real_power_w"]))

    cutoff = timestamp - window
    weighted_watt_seconds = 0.0
    represented_seconds = 0.0
    for index, sample in enumerate(samples):
        sample_time = _datetime_or_none(sample["timestamp"])
        if sample_time is None:
            continue
        next_time = timestamp
        if index + 1 < len(samples):
            next_sample_time = _datetime_or_none(samples[index + 1]["timestamp"])
            if next_sample_time is not None:
                next_time = min(next_sample_time, timestamp)
        interval_start = max(sample_time, cutoff)
        interval_seconds = max((next_time - interval_start).total_seconds(), 0.0)
        if interval_seconds <= 0.0:
            continue
        weighted_watt_seconds += float(sample["real_power_w"]) * interval_seconds
        represented_seconds += interval_seconds

    if represented_seconds <= 0.0:
        return _round_w(float(samples[-1]["real_power_w"]))
    return _round_w(weighted_watt_seconds / represented_seconds)


def _record_daily_peak(
    daily_peaks: list[dict[str, float | str]],
    date: str,
    current_demand_w: float,
) -> float:
    for peak in daily_peaks:
        if peak["date"] == date:
            peak["peak_demand_w"] = max(float(peak["peak_demand_w"]), current_demand_w)
            return _round_w(float(peak["peak_demand_w"]))
    daily_peaks.append({"date": date, "peak_demand_w": current_demand_w})
    daily_peaks.sort(key=lambda peak: str(peak["date"]))
    return current_demand_w


def _prune_daily_peaks(
    daily_peaks: list[dict[str, float | str]],
    timestamp: datetime,
    retention_days: int,
) -> list[dict[str, float | str]]:
    cutoff = (timestamp.date() - timedelta(days=max(retention_days, 1))).isoformat()
    return [
        peak
        for peak in daily_peaks
        if isinstance(peak.get("date"), str) and str(peak["date"]) >= cutoff
    ]


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


def _round_w(value: float) -> float:
    return round(float(value), 1)
