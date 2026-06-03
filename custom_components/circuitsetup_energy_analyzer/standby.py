from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

DEFAULT_STANDBY_WINDOW_HOURS = 48
DEFAULT_STANDBY_THRESHOLD_W = 8.0


@dataclass(frozen=True, slots=True)
class StandbySettings:
    """User-tunable Always On and standby settings."""

    window_hours: int = DEFAULT_STANDBY_WINDOW_HOURS
    standby_threshold_w: float = DEFAULT_STANDBY_THRESHOLD_W
    always_on_alert_w: float | None = None
    min_samples: int = 24


@dataclass(frozen=True, slots=True)
class StandbyLimitEvidence:
    """Evidence that Always On load is above a configured limit."""

    circuit_id: str
    always_on_power_w: float
    always_on_alert_w: float
    always_on_limit_usage: float
    current_power_w: float
    sample_count: int
    window_hours: int
    features: dict[str, float]


@dataclass(frozen=True, slots=True)
class StandbyResult:
    """Latest Always On and standby state for a circuit."""

    circuit_id: str
    always_on_power_w: float
    current_power_w: float
    standby_threshold_w: float
    sample_count: int
    window_hours: int
    status: str
    always_on_alert_w: float | None = None
    always_on_limit_usage: float = 0.0
    features: dict[str, float] | None = None
    limit_exceeded: StandbyLimitEvidence | None = None


def record_standby_sample(
    history: dict[str, Any],
    *,
    circuit_id: str,
    timestamp: datetime,
    real_power_w: float | None,
    settings: StandbySettings,
) -> StandbyResult | None:
    """Fold a real-power sample into an Always On / standby estimate."""
    if real_power_w is None:
        return None

    window_hours = max(int(settings.window_hours), 1)
    samples = _coerce_samples(history.get("samples"))
    samples.append(
        {
            "timestamp": timestamp.isoformat(),
            "real_power_w": _round_w(max(float(real_power_w), 0.0)),
        }
    )
    samples = _prune_samples(samples, timestamp, timedelta(hours=window_hours))
    history["samples"] = samples

    current_power = _round_w(max(float(real_power_w), 0.0))
    standby_threshold = max(float(settings.standby_threshold_w), 0.0)
    sample_count = len(samples)
    min_samples = max(int(settings.min_samples), 1)

    if sample_count < min_samples:
        return _result(
            circuit_id=circuit_id,
            always_on_power_w=0.0,
            current_power_w=current_power,
            standby_threshold_w=standby_threshold,
            sample_count=sample_count,
            window_hours=window_hours,
            status="learning",
            always_on_alert_w=_positive_float_or_none(settings.always_on_alert_w),
        )

    always_on = _low_watermark(
        [float(sample["real_power_w"]) for sample in samples]
    )
    status = _status(current_power, standby_threshold)
    alert_w = _positive_float_or_none(settings.always_on_alert_w)
    limit_usage = (
        round((always_on / alert_w) * 100, 1)
        if alert_w is not None and alert_w > 0.0
        else 0.0
    )
    result = _result(
        circuit_id=circuit_id,
        always_on_power_w=always_on,
        current_power_w=current_power,
        standby_threshold_w=standby_threshold,
        sample_count=sample_count,
        window_hours=window_hours,
        status=status,
        always_on_alert_w=alert_w,
        always_on_limit_usage=limit_usage,
    )
    if alert_w is None or always_on <= alert_w:
        return result

    evidence = StandbyLimitEvidence(
        circuit_id=circuit_id,
        always_on_power_w=always_on,
        always_on_alert_w=alert_w,
        always_on_limit_usage=limit_usage,
        current_power_w=current_power,
        sample_count=sample_count,
        window_hours=window_hours,
        features={
            "always_on_power_w": always_on,
            "always_on_alert_w": alert_w,
            "always_on_limit_usage": limit_usage,
            "current_power_w": current_power,
            "sample_count": float(sample_count),
            "window_hours": float(window_hours),
        },
    )
    return replace(result, limit_exceeded=evidence)


def _result(
    *,
    circuit_id: str,
    always_on_power_w: float,
    current_power_w: float,
    standby_threshold_w: float,
    sample_count: int,
    window_hours: int,
    status: str,
    always_on_alert_w: float | None = None,
    always_on_limit_usage: float = 0.0,
) -> StandbyResult:
    features = {
        "always_on_power_w": always_on_power_w,
        "current_power_w": current_power_w,
        "standby_threshold_w": standby_threshold_w,
        "sample_count": float(sample_count),
        "window_hours": float(window_hours),
    }
    return StandbyResult(
        circuit_id=circuit_id,
        always_on_power_w=always_on_power_w,
        current_power_w=current_power_w,
        standby_threshold_w=standby_threshold_w,
        sample_count=sample_count,
        window_hours=window_hours,
        status=status,
        always_on_alert_w=always_on_alert_w,
        always_on_limit_usage=always_on_limit_usage,
        features=features,
    )


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


def _low_watermark(values: list[float]) -> float:
    if not values:
        return 0.0
    return _round_w(min(values))


def _status(current_power_w: float, standby_threshold_w: float) -> str:
    if current_power_w <= 0.0:
        return "off"
    if current_power_w <= standby_threshold_w:
        return "standby"
    return "on"


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
