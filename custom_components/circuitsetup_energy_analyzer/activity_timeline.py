from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .models import AlertEvidence, CircuitEvent

DEFAULT_TIMELINE_WINDOW_HOURS = 24
DEFAULT_TIMELINE_MAX_ITEMS = 8


@dataclass(frozen=True, slots=True)
class RecentActivityTimeline:
    """Compact per-circuit timeline built from retained events and alerts."""

    status: str
    window_hours: int
    total_count: int
    event_count: int
    alert_count: int
    latest_title: str
    latest_timestamp: str | None
    items: list[dict[str, Any]] = field(default_factory=list)


def build_recent_activity_timeline(
    *,
    circuit_id: str,
    events: Iterable[CircuitEvent],
    alerts: Iterable[AlertEvidence],
    now: datetime,
    window_hours: int = DEFAULT_TIMELINE_WINDOW_HOURS,
    max_items: int = DEFAULT_TIMELINE_MAX_ITEMS,
) -> RecentActivityTimeline:
    """Return a recent circuit activity summary from retained analyzer evidence."""

    window_hours = max(int(window_hours), 1)
    max_items = max(int(max_items), 1)
    cutoff = now - timedelta(hours=window_hours)
    event_items = [
        _event_item(event)
        for event in events
        if event.circuit_id == circuit_id and event.timestamp >= cutoff
    ]
    alert_items = [
        _alert_item(alert)
        for alert in alerts
        if alert.circuit_id == circuit_id and alert.timestamp >= cutoff
    ]
    all_items = sorted(
        [*event_items, *alert_items],
        key=lambda item: str(item["timestamp"]),
        reverse=True,
    )
    visible_items = all_items[:max_items]
    if not all_items:
        return RecentActivityTimeline(
            status="quiet",
            window_hours=window_hours,
            total_count=0,
            event_count=0,
            alert_count=0,
            latest_title="No recent activity",
            latest_timestamp=None,
            items=[],
        )

    latest = all_items[0]
    return RecentActivityTimeline(
        status="activity",
        window_hours=window_hours,
        total_count=len(all_items),
        event_count=len(event_items),
        alert_count=len(alert_items),
        latest_title=str(latest["title"]),
        latest_timestamp=str(latest["timestamp"]),
        items=visible_items,
    )


def timeline_payload(summary: RecentActivityTimeline) -> dict[str, Any]:
    """Return a JSON-safe payload for Home Assistant sensor attributes."""

    return {
        "status": summary.status,
        "window_hours": summary.window_hours,
        "total_count": summary.total_count,
        "event_count": summary.event_count,
        "alert_count": summary.alert_count,
        "latest_title": summary.latest_title,
        "latest_timestamp": summary.latest_timestamp,
        "items": list(summary.items),
    }


def _event_item(event: CircuitEvent) -> dict[str, Any]:
    event_type = event.event_type.value
    return {
        "timestamp": event.timestamp.isoformat(),
        "kind": "event",
        "title": event_type.replace("_", " ").title(),
        "detail": f"Observed {event_type.replace('_', ' ')} event.",
        "severity": event.severity.value,
        "feature": None,
        "event_type": event_type,
        "observed_value": None,
        "baseline_value": None,
        "change_ratio": None,
        "repeated_count": None,
    }


def _alert_item(alert: AlertEvidence) -> dict[str, Any]:
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    return {
        "timestamp": alert.timestamp.isoformat(),
        "kind": "alert",
        "title": f"Possible issue: {feature.replace('_', ' ')}",
        "detail": alert.message,
        "severity": alert.severity.value,
        "feature": alert.feature or None,
        "event_type": alert.event_type.value if alert.event_type else None,
        "observed_value": alert.observed_value,
        "baseline_value": alert.baseline_value,
        "change_ratio": alert.change_ratio,
        "repeated_count": alert.repeated_count,
    }
