from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from .alert_feedback import mapping_datetime
from .local_time import TimeZone, local_date, local_month_key

DEFAULT_DEMAND_WINDOW_MINUTES = 15
MAX_DEMAND_WINDOW_MINUTES = 240
DEFAULT_PEAK_RANK_COUNT = 3
DEFAULT_PEAK_WARNING_RATIO = 0.9
MAX_MONTHLY_PEAK_WINDOWS_PER_MONTH = 24


@dataclass(frozen=True, slots=True)
class DemandSettings:
    """User-tunable rolling demand settings."""

    window_minutes: int = DEFAULT_DEMAND_WINDOW_MINUTES
    demand_limit_w: float | None = None
    peak_rank_count: int = DEFAULT_PEAK_RANK_COUNT
    peak_warning_ratio: float = DEFAULT_PEAK_WARNING_RATIO


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
class DemandPeakEvidence:
    """Evidence that rolling demand is near the month's highest windows."""

    circuit_id: str
    date: str
    current_demand_w: float
    monthly_peak_rank: int
    monthly_peak_cutoff_w: float
    monthly_peak_usage_percent: float
    peak_rank_count: int
    peak_warning_ratio: float
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
    window_baseline_eligible: bool = True
    demand_limit_w: float | None = None
    demand_limit_usage: float = 0.0
    limit_exceeded: DemandLimitEvidence | None = None
    monthly_peak_rank: int = 0
    monthly_peak_status: str = "unavailable"
    monthly_peak_cutoff_w: float = 0.0
    monthly_peak_usage_percent: float = 0.0
    monthly_peak_rank_count: int = DEFAULT_PEAK_RANK_COUNT
    monthly_peak_warning_ratio: float = DEFAULT_PEAK_WARNING_RATIO
    monthly_peak_warning: DemandPeakEvidence | None = None
    monthly_peak_recorded: bool = False


def record_demand_sample(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    real_power_w: float | None,
    settings: DemandSettings,
    retention_days: int = 45,
    time_zone: TimeZone = None,
    baseline_eligible: bool = True,
    transient_samples: list[dict[str, Any]] | None = None,
    maintenance: Any = None,
) -> DemandResult | None:
    """Fold a real-power sample into a rolling demand window."""
    if real_power_w is None:
        return None

    window_minutes = min(
        max(int(settings.window_minutes), 1),
        MAX_DEMAND_WINDOW_MINUTES,
    )
    window = timedelta(minutes=window_minutes)
    today = _calendar_date(timestamp, time_zone).isoformat()
    samples = _coerce_samples(
        transient_samples if transient_samples else history.get("samples")
    )
    current_sample: dict[str, float | str | bool] = {
        "timestamp": timestamp.isoformat(),
        "real_power_w": _round_w(max(float(real_power_w), 0.0)),
    }
    if not baseline_eligible:
        current_sample["baseline_eligible"] = False
    calculation_samples = [
        *samples,
        current_sample,
    ]
    calculation_samples = _prune_samples(calculation_samples, timestamp, window)
    window_baseline_eligible = (
        baseline_eligible
        and not _window_overlaps_maintenance(timestamp, window, maintenance)
        and all(
            sample.get("baseline_eligible") is not False
            for sample in calculation_samples
        )
    )
    if transient_samples is not None:
        transient_samples[:] = calculation_samples

    current_demand = _time_weighted_average(calculation_samples, timestamp, window)
    daily_peaks = _coerce_daily_peaks(history.get("daily_peaks"))
    calculation_daily_peaks = (
        daily_peaks if window_baseline_eligible else list(daily_peaks)
    )
    peak_demand = _record_daily_peak(
        calculation_daily_peaks,
        today,
        current_demand,
    )
    monthly_peak = _record_monthly_peak_window(
        history,
        circuit_id=circuit_id,
        timestamp=timestamp,
        current_demand_w=current_demand,
        window_minutes=window_minutes,
        peak_rank_count=settings.peak_rank_count,
        peak_warning_ratio=settings.peak_warning_ratio,
        retention_days=retention_days,
        time_zone=time_zone,
        baseline_eligible=window_baseline_eligible,
    )

    if window_baseline_eligible:
        history["samples"] = [dict(sample) for sample in calculation_samples]
        history["daily_peaks"] = _prune_daily_peaks(
            calculation_daily_peaks,
            timestamp,
            retention_days,
            time_zone=time_zone,
        )

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
        window_baseline_eligible=window_baseline_eligible,
        demand_limit_w=limit_w,
        demand_limit_usage=limit_usage,
        monthly_peak_rank=monthly_peak["rank"],
        monthly_peak_status=monthly_peak["status"],
        monthly_peak_cutoff_w=monthly_peak["cutoff_w"],
        monthly_peak_usage_percent=monthly_peak["usage_percent"],
        monthly_peak_rank_count=monthly_peak["rank_count"],
        monthly_peak_warning_ratio=monthly_peak["warning_ratio"],
        monthly_peak_warning=monthly_peak["warning"],
        monthly_peak_recorded=monthly_peak["recorded"],
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


def _coerce_samples(raw_samples: Any) -> list[dict[str, float | str | bool]]:
    samples: list[dict[str, float | str | bool]] = []
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
        sample: dict[str, float | str | bool] = {
            "timestamp": timestamp,
            "real_power_w": _round_w(max(power, 0.0)),
        }
        if raw_sample.get("baseline_eligible") is False:
            sample["baseline_eligible"] = False
        samples.append(sample)
    return sorted(samples, key=lambda sample: str(sample["timestamp"]))


def _window_overlaps_maintenance(
    timestamp: datetime,
    window: timedelta,
    maintenance: Any,
) -> bool:
    if not isinstance(maintenance, Mapping):
        return False
    maintenance_start = mapping_datetime(maintenance.get("started_at"))
    maintenance_end = mapping_datetime(maintenance.get("ended_at"))
    if maintenance_start is None or maintenance_end is None:
        return False

    window_start = timestamp - window
    window_end = timestamp
    if any(
        value.tzinfo is None
        for value in (window_start, window_end, maintenance_start, maintenance_end)
    ):
        window_start = window_start.replace(tzinfo=None)
        window_end = window_end.replace(tzinfo=None)
        maintenance_start = maintenance_start.replace(tzinfo=None)
        maintenance_end = maintenance_end.replace(tzinfo=None)
    return window_start < maintenance_end and window_end > maintenance_start


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


def _coerce_monthly_peak_windows(
    raw_windows: Any,
) -> list[dict[str, float | int | str]]:
    windows: list[dict[str, float | int | str]] = []
    if not isinstance(raw_windows, list):
        return windows
    for raw_window in raw_windows:
        if not isinstance(raw_window, dict):
            continue
        timestamp = raw_window.get("timestamp")
        demand_w = _float_or_none(raw_window.get("demand_w"))
        window_minutes = int(_float_or_none(raw_window.get("window_minutes")) or 0)
        if (
            not isinstance(timestamp, str)
            or demand_w is None
            or window_minutes <= 0
            or _datetime_or_none(timestamp) is None
        ):
            continue
        windows.append(
            {
                "timestamp": timestamp,
                "demand_w": _round_w(max(demand_w, 0.0)),
                "window_minutes": window_minutes,
            }
        )
    return sorted(
        windows,
        key=lambda window: (
            _month_key(str(window["timestamp"])),
            -float(window["demand_w"]),
            str(window["timestamp"]),
        ),
    )


def _record_monthly_peak_window(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    current_demand_w: float,
    window_minutes: int,
    peak_rank_count: int,
    peak_warning_ratio: float,
    retention_days: int,
    time_zone: TimeZone = None,
    baseline_eligible: bool = True,
) -> dict[str, Any]:
    rank_count = max(int(peak_rank_count), 1)
    warning_ratio = min(max(float(peak_warning_ratio), 0.0), 1.0)
    windows = _coerce_monthly_peak_windows(history.get("monthly_peak_windows"))
    month = _month_key_for_datetime(timestamp, time_zone)
    monthly_before = [
        window
        for window in windows
        if _month_key(str(window["timestamp"]), time_zone) == month
    ]
    monthly_demands = sorted(
        (float(window["demand_w"]) for window in monthly_before),
        reverse=True,
    )
    cutoff_w = (
        monthly_demands[rank_count - 1]
        if len(monthly_demands) >= rank_count
        else (monthly_demands[-1] if monthly_demands else current_demand_w)
    )
    rank = 1 + sum(1 for demand_w in monthly_demands if demand_w > current_demand_w)
    usage_percent = (
        round((current_demand_w / cutoff_w) * 100, 1) if cutoff_w > 0.0 else 0.0
    )
    has_monthly_baseline = len(monthly_demands) >= rank_count and cutoff_w > 0.0
    status = "below_monthly_peak"
    if rank <= rank_count:
        status = "monthly_peak"
    elif has_monthly_baseline and usage_percent >= round(warning_ratio * 100, 1):
        status = "near_monthly_peak"

    warning = None
    if has_monthly_baseline and status in {"monthly_peak", "near_monthly_peak"}:
        warning = DemandPeakEvidence(
            circuit_id=circuit_id,
            date=_calendar_date(timestamp, time_zone).isoformat(),
            current_demand_w=current_demand_w,
            monthly_peak_rank=rank,
            monthly_peak_cutoff_w=cutoff_w,
            monthly_peak_usage_percent=usage_percent,
            peak_rank_count=rank_count,
            peak_warning_ratio=warning_ratio,
            window_minutes=window_minutes,
            features={
                "current_demand_w": current_demand_w,
                "monthly_peak_rank": float(rank),
                "monthly_peak_cutoff_w": cutoff_w,
                "monthly_peak_usage_percent": usage_percent,
                "peak_rank_count": float(rank_count),
                "peak_warning_ratio": warning_ratio,
                "demand_window_minutes": float(window_minutes),
            },
        )

    before_windows = list(windows)
    if baseline_eligible and current_demand_w > 0.0:
        windows.append(
            {
                "timestamp": timestamp.isoformat(),
                "demand_w": current_demand_w,
                "window_minutes": window_minutes,
            }
        )
    pruned_windows = _prune_monthly_peak_windows(
        windows,
        timestamp=timestamp,
        retention_days=retention_days,
        time_zone=time_zone,
    )
    recorded = pruned_windows != before_windows
    if baseline_eligible and (recorded or "monthly_peak_windows" in history):
        history["monthly_peak_windows"] = pruned_windows
    return {
        "rank": rank,
        "status": status,
        "cutoff_w": cutoff_w,
        "usage_percent": usage_percent,
        "rank_count": rank_count,
        "warning_ratio": warning_ratio,
        "warning": warning,
        "recorded": recorded,
    }


def _prune_samples(
    samples: list[dict[str, float | str | bool]],
    timestamp: datetime,
    window: timedelta,
) -> list[dict[str, float | str | bool]]:
    cutoff = timestamp - window
    return [
        sample
        for sample in samples
        if (sample_time := _datetime_or_none(sample["timestamp"])) is not None
        and sample_time >= cutoff
    ]


def _time_weighted_average(
    samples: list[dict[str, float | str | bool]],
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
    *,
    time_zone: TimeZone = None,
) -> list[dict[str, float | str]]:
    cutoff = (
        _calendar_date(timestamp, time_zone) - timedelta(days=max(retention_days, 1))
    ).isoformat()
    return [
        peak
        for peak in daily_peaks
        if isinstance(peak.get("date"), str) and str(peak["date"]) >= cutoff
    ]


def _prune_monthly_peak_windows(
    windows: list[dict[str, float | int | str]],
    *,
    timestamp: datetime,
    retention_days: int,
    time_zone: TimeZone = None,
) -> list[dict[str, float | int | str]]:
    cutoff = timestamp - timedelta(days=max(retention_days, 1))
    retained = [
        window
        for window in windows
        if (window_time := _datetime_or_none(window["timestamp"])) is not None
        and window_time >= cutoff
    ]
    by_month: dict[str, list[dict[str, float | int | str]]] = {}
    for window in retained:
        by_month.setdefault(
            _month_key(str(window["timestamp"]), time_zone),
            [],
        ).append(window)

    top_windows: list[dict[str, float | int | str]] = []
    for month in sorted(by_month):
        month_windows = sorted(
            by_month[month],
            key=lambda window: (
                -float(window["demand_w"]),
                str(window["timestamp"]),
            ),
        )
        top_windows.extend(month_windows[:MAX_MONTHLY_PEAK_WINDOWS_PER_MONTH])
    return [
        {
            "timestamp": str(window["timestamp"]),
            "demand_w": _round_w(float(window["demand_w"])),
            "window_minutes": int(window["window_minutes"]),
        }
        for window in top_windows
    ]


def _month_key(timestamp: str, time_zone: TimeZone = None) -> str:
    parsed = _datetime_or_none(timestamp)
    if parsed is None:
        return ""
    return _month_key_for_datetime(parsed, time_zone)


def _month_key_for_datetime(timestamp: datetime, time_zone: TimeZone) -> str:
    if time_zone is None or timestamp.tzinfo is None:
        return timestamp.strftime("%Y-%m")
    return local_month_key(timestamp, time_zone)


def _calendar_date(timestamp: datetime, time_zone: TimeZone) -> date:
    if time_zone is None or timestamp.tzinfo is None:
        return timestamp.date()
    return local_date(timestamp, time_zone)


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
