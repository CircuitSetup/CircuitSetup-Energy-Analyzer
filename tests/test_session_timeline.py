from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
)
from custom_components.circuitsetup_energy_analyzer.session_timeline import (
    direct_appliance_timeline,
    nilm_appliance_timeline,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

PANEL_JS = (
    Path(__file__).parents[1]
    / "custom_components"
    / "circuitsetup_energy_analyzer"
    / "frontend"
    / "energy-analyzer-panel-main.js"
)


def _event(at: datetime, event_type: EventType) -> CircuitEvent:
    return CircuitEvent(
        timestamp=at,
        circuit_id="washer",
        event_type=event_type,
    )


def _alert(
    at: datetime,
    *,
    circuit_id: str = "washer",
    session_id: str | None = None,
) -> AlertEvidence:
    return AlertEvidence(
        timestamp=at,
        circuit_id=circuit_id,
        severity=Severity.WARNING,
        message="Session needs attention.",
        feature="cycle_duration",
        features={"session_id": session_id} if session_id else {},
    )


def test_direct_timeline_uses_normalized_sessions_with_overlays() -> None:
    start = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
    alert = _alert(start + timedelta(minutes=12))
    store = FeatureStoreData(
        events=[
            _event(start, EventType.START),
            _event(start + timedelta(minutes=10), EventType.STOP),
            _event(start + timedelta(minutes=10, seconds=30), EventType.START),
            _event(start + timedelta(minutes=20), EventType.STOP),
        ],
        alerts=[alert],
        maintenance_by_circuit={
            "washer": {
                "active": False,
                "started_at": (start + timedelta(minutes=5)).isoformat(),
                "ended_at": (start + timedelta(minutes=15)).isoformat(),
            }
        },
    )

    timeline = direct_appliance_timeline(
        SimpleNamespace(
            store_data=store,
            current_time=lambda: start + timedelta(hours=1),
        ),
        "washer",
    )

    assert len(timeline) == 1
    session = timeline[0]
    assert session.appliance_key == "circuit:washer"
    assert session.source_type == "direct_meter"
    assert session.start == start
    assert session.end == start + timedelta(minutes=20)
    assert session.duration_seconds == 1170.0
    assert session.status == "anomalous"
    assert session.alert_ids == (notification_id_for_alert(alert),)
    assert session.maintenance is True


def test_direct_timeline_keeps_open_session_running() -> None:
    start = datetime(2026, 7, 13, 11, 30, tzinfo=UTC)
    store = FeatureStoreData(events=[_event(start, EventType.START)])

    (session,) = direct_appliance_timeline(
        SimpleNamespace(
            store_data=store,
            current_time=lambda: start + timedelta(minutes=30),
        ),
        "washer",
    )

    assert session.end is None
    assert session.duration_seconds == 1800.0
    assert session.status == "running"


def test_direct_timeline_duration_is_elapsed_time_across_dst() -> None:
    local = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 0, 30, tzinfo=local)
    end = datetime(2026, 11, 1, 2, 30, tzinfo=local)
    store = FeatureStoreData(
        events=[_event(start, EventType.START), _event(end, EventType.STOP)]
    )

    (session,) = direct_appliance_timeline(
        SimpleNamespace(store_data=store, current_time=lambda: end),
        "washer",
    )

    expected = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()
    assert session.duration_seconds == expected == 10800.0
    assert session.as_dict()["start"].endswith("-04:00")
    assert session.as_dict()["end"].endswith("-05:00")


def test_merged_direct_timeline_sums_elapsed_segments_across_dst() -> None:
    local = ZoneInfo("America/New_York")
    first_start = datetime(2026, 3, 8, 1, 30, tzinfo=local)
    first_end = datetime(2026, 3, 8, 3, 0, tzinfo=local)
    second_start = datetime(2026, 3, 8, 3, 0, 30, tzinfo=local)
    second_end = datetime(2026, 3, 8, 3, 30, tzinfo=local)
    store = FeatureStoreData(
        events=[
            _event(first_start, EventType.START),
            _event(first_end, EventType.STOP),
            _event(second_start, EventType.START),
            _event(second_end, EventType.STOP),
        ]
    )

    (session,) = direct_appliance_timeline(
        SimpleNamespace(store_data=store, current_time=lambda: second_end),
        "washer",
    )

    assert session.duration_seconds == 3570.0


def test_direct_timeline_orders_repeated_fall_back_hour_by_instant() -> None:
    local = ZoneInfo("America/New_York")
    first_start = datetime(2026, 11, 1, 1, 40, tzinfo=local, fold=0)
    first_end = datetime(2026, 11, 1, 1, 55, tzinfo=local, fold=0)
    second_start = datetime(2026, 11, 1, 1, 5, tzinfo=local, fold=1)
    second_end = datetime(2026, 11, 1, 1, 20, tzinfo=local, fold=1)
    store = FeatureStoreData(
        events=[
            _event(first_start, EventType.START),
            _event(first_end, EventType.STOP),
            _event(second_start, EventType.START),
            _event(second_end, EventType.STOP),
        ]
    )

    timeline = direct_appliance_timeline(
        SimpleNamespace(store_data=store, current_time=lambda: second_end),
        "washer",
    )

    assert len(timeline) == 2
    assert [session.duration_seconds for session in timeline] == [900.0, 900.0]
    assert [session.start.fold for session in timeline] == [0, 1]


def test_nilm_timeline_preserves_estimate_validation_and_alert_marker() -> None:
    start = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
    session_id = "session-dishwasher"
    alert = _alert(
        start + timedelta(minutes=20),
        circuit_id="mains",
        session_id=session_id,
    )
    state = SimpleNamespace(
        assignment_id="assignment-dishwasher",
        appliance_key="nilm:assignment-dishwasher",
        mains_circuit_id="mains",
        reference_time=start + timedelta(hours=2),
        sessions=(
            {
                "session_id": session_id,
                "assignment_id": "assignment-dishwasher",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=45)).isoformat(),
                "duration_seconds": 2700.0,
                "confidence": 0.91,
                "estimated_energy_kwh": 0.62,
                "maintenance": True,
            },
        ),
        confirmed_session_ids=frozenset({session_id}),
        rejected_session_ids=frozenset(),
        adjusted_session_ids=frozenset(),
    )

    (session,) = nilm_appliance_timeline(state, alerts=(alert,))

    assert session.appliance_key == "nilm:assignment-dishwasher"
    assert session.source_type == "nilm_estimate"
    assert session.duration_seconds == 2700.0
    assert session.confidence == 0.91
    assert session.estimated_energy_kwh == 0.62
    assert session.status == "confirmed"
    assert session.alert_ids == (notification_id_for_alert(alert),)
    assert session.maintenance is True


def test_nilm_open_session_duration_is_dst_safe() -> None:
    local = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 0, 30, tzinfo=local)
    now = datetime(2026, 11, 1, 2, 30, tzinfo=local)
    state = SimpleNamespace(
        assignment_id="assignment-dishwasher",
        appliance_key="nilm:assignment-dishwasher",
        mains_circuit_id="mains",
        reference_time=now,
        sessions=(
            {
                "session_id": "session-open",
                "start": start.isoformat(),
                "end": None,
                "duration_seconds": None,
                "confidence": 0.8,
            },
        ),
        confirmed_session_ids=frozenset(),
        rejected_session_ids=frozenset(),
        adjusted_session_ids=frozenset(),
    )

    (session,) = nilm_appliance_timeline(state)

    assert session.end is None
    assert session.duration_seconds == 10800.0
    assert session.status == "running"


def test_nilm_timeline_payload_is_bounded_to_newest_sessions() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    sessions = tuple(
        {
            "session_id": f"session-{index}",
            "start": (start + timedelta(hours=index)).isoformat(),
            "end": (start + timedelta(hours=index, minutes=5)).isoformat(),
            "duration_seconds": 300.0,
        }
        for index in range(55)
    )
    state = SimpleNamespace(
        assignment_id="assignment-dishwasher",
        appliance_key="nilm:assignment-dishwasher",
        mains_circuit_id="mains",
        reference_time=start + timedelta(days=3),
        sessions=sessions,
        confirmed_session_ids=frozenset(),
        rejected_session_ids=frozenset(),
        adjusted_session_ids=frozenset(),
    )

    timeline = nilm_appliance_timeline(state)

    assert len(timeline) == 40
    assert timeline[0].session_id == "session-15"
    assert timeline[-1].session_id == "session-54"


def test_session_strip_has_timezone_and_accessibility_fallbacks() -> None:
    source = PANEL_JS.read_text(encoding="utf-8")

    assert "_timelineClockParts(start)" in source
    assert "timeZone: this._timeZone()" in source
    assert "crossesDay" in source
    assert 'session.end ? "" : "running"' in source
    assert 'appliance_detail.maintenance_session' in source
    assert 'role="img" aria-label=' in source
