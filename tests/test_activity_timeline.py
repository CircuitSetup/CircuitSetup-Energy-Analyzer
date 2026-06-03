from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.activity_timeline import (
    build_recent_activity_timeline,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)


def test_recent_activity_timeline_merges_events_and_alerts_newest_first() -> None:
    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    start = CircuitEvent(
        timestamp=now - timedelta(minutes=30),
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 480.0},
    )
    old = CircuitEvent(
        timestamp=now - timedelta(days=2),
        circuit_id="fridge",
        event_type=EventType.STOP,
    )
    other = CircuitEvent(
        timestamp=now - timedelta(minutes=15),
        circuit_id="hvac",
        event_type=EventType.START,
    )
    alert = AlertEvidence(
        timestamp=now - timedelta(minutes=5),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue: Fridge run duration changed.",
        feature="cycle_duration",
        observed_value=45.0,
        baseline_value=30.0,
        change_ratio=0.5,
        repeated_count=3,
    )

    summary = build_recent_activity_timeline(
        circuit_id="fridge",
        events=[old, start, other],
        alerts=[alert],
        now=now,
        window_hours=24,
    )

    assert summary.status == "activity"
    assert summary.latest_title == "Possible issue: cycle duration"
    assert summary.latest_timestamp == alert.timestamp.isoformat()
    assert summary.event_count == 1
    assert summary.alert_count == 1
    assert summary.total_count == 2
    assert summary.items == [
        {
            "timestamp": alert.timestamp.isoformat(),
            "kind": "alert",
            "title": "Possible issue: cycle duration",
            "detail": "Possible issue: Fridge run duration changed.",
            "severity": "warning",
            "feature": "cycle_duration",
            "event_type": None,
            "observed_value": 45.0,
            "baseline_value": 30.0,
            "change_ratio": 0.5,
            "repeated_count": 3,
        },
        {
            "timestamp": start.timestamp.isoformat(),
            "kind": "event",
            "title": "Start",
            "detail": "Observed start event.",
            "severity": "info",
            "feature": None,
            "event_type": "start",
            "observed_value": None,
            "baseline_value": None,
            "change_ratio": None,
            "repeated_count": None,
        },
    ]


def test_recent_activity_timeline_limits_items_and_reports_quiet() -> None:
    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=now - timedelta(minutes=index),
            circuit_id="pump",
            event_type=EventType.START,
        )
        for index in range(6)
    ]

    limited = build_recent_activity_timeline(
        circuit_id="pump",
        events=events,
        alerts=[],
        now=now,
        window_hours=24,
        max_items=3,
    )
    quiet = build_recent_activity_timeline(
        circuit_id="pump",
        events=[],
        alerts=[],
        now=now,
    )

    assert limited.total_count == 6
    assert len(limited.items) == 3
    assert quiet.status == "quiet"
    assert quiet.latest_title == "No recent activity"
    assert quiet.items == []
