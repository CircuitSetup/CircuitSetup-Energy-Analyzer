from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from types import MappingProxyType
from typing import Any

from .cycles import CircuitCycleSummary


@dataclass(frozen=True, slots=True)
class ActivityAlertSettings:
    """User-configured activity notification settings for one circuit."""

    max_active_minutes: float | None = None
    max_idle_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class ActivityAlertEvidence:
    """Evidence for a user-configured activity alert."""

    feature: str
    message: str
    observed_value: float
    baseline_value: float
    score: float
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


def evaluate_activity_alert(
    *,
    circuit_id: str,
    circuit_name: str,
    summary: CircuitCycleSummary,
    settings: ActivityAlertSettings,
) -> ActivityAlertEvidence | None:
    """Return evidence when a configured activity alert is active."""
    max_active_minutes = _positive_float_or_none(settings.max_active_minutes)
    active_minutes = round(summary.active_cycle_seconds / 60.0, 3)
    if (
        max_active_minutes is not None
        and not _is_mains_circuit(circuit_id)
        and summary.status == "running"
        and active_minutes > max_active_minutes
    ):
        return ActivityAlertEvidence(
            feature="activity_left_on",
            message=(
                f"Activity alert: {circuit_name} has been active for "
                f"{_format_minutes(active_minutes)}, above the configured "
                f"{_format_minutes(max_active_minutes)} limit."
            ),
            observed_value=active_minutes,
            baseline_value=max_active_minutes,
            score=active_minutes / max_active_minutes,
            features={
                "active_minutes": active_minutes,
                "max_active_minutes": max_active_minutes,
                "active_cycle_seconds": summary.active_cycle_seconds,
                "last_start": (
                    summary.last_start.isoformat() if summary.last_start else None
                ),
            },
        )

    max_idle_minutes = _positive_float_or_none(settings.max_idle_minutes)
    idle_seconds = _idle_seconds(summary)
    if (
        max_idle_minutes is None
        or idle_seconds is None
        or idle_seconds <= max_idle_minutes * 60.0
    ):
        return None

    idle_minutes = round(idle_seconds / 60.0, 3)
    return ActivityAlertEvidence(
        feature="activity_inactive_too_long",
        message=(
            f"Activity alert: {circuit_name} has shown no activity for "
            f"{_format_minutes(idle_minutes)}, above the configured "
            f"{_format_minutes(max_idle_minutes)} limit."
        ),
        observed_value=idle_minutes,
        baseline_value=max_idle_minutes,
        score=idle_minutes / max_idle_minutes,
        features={
            "idle_minutes": idle_minutes,
            "max_idle_minutes": max_idle_minutes,
            "idle_seconds": round(idle_seconds, 3),
            "last_start": (
                summary.last_start.isoformat() if summary.last_start else None
            ),
            "last_stop": summary.last_stop.isoformat() if summary.last_stop else None,
            "status": summary.status,
        },
    )


def _idle_seconds(summary: CircuitCycleSummary) -> float | None:
    if summary.status == "running":
        return None
    if summary.status == "no_activity":
        return max(float(summary.day_elapsed_seconds), 0.0)
    if summary.status != "idle" or summary.last_stop is None:
        return None

    day_start = _day_start(summary, summary.last_stop)
    seconds_since_stop = summary.day_elapsed_seconds - max(
        (summary.last_stop - day_start).total_seconds(),
        0.0,
    )
    return max(seconds_since_stop, 0.0)


def _is_mains_circuit(circuit_id: str) -> bool:
    return circuit_id.strip().casefold() == "mains"


def _day_start(summary: CircuitCycleSummary, reference: datetime) -> datetime:
    if summary.day_start is not None:
        return summary.day_start
    try:
        summary_date = datetime.fromisoformat(summary.date).date()
    except ValueError:
        summary_date = reference.date()
    return datetime.combine(summary_date, time.min, tzinfo=reference.tzinfo)


def _positive_float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0.0:
        return None
    return number


def _format_minutes(value: float) -> str:
    if value < 60.0:
        return f"{value:.1f}".rstrip("0").rstrip(".") + " minutes"
    hours = value / 60.0
    return f"{hours:.1f}".rstrip("0").rstrip(".") + " hours"
