from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.circuitsetup_energy_analyzer.expected_schedule import (
    evaluate_expected_schedule,
    refresh_expected_schedule_contexts,
    schedule_settings_from_dict,
    schedule_window_state,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
    EventType,
)

TIME_ZONE = ZoneInfo("America/New_York")


def _settings(**overrides: object):
    raw = {
        "enabled": True,
        "windows": [
            {
                "start": "08:00",
                "end": "10:00",
                "weekdays": [0, 1, 2, 3, 4],
            }
        ],
        "minimum_duration_minutes": 30,
    }
    raw.update(overrides)
    return schedule_settings_from_dict(raw, appliance_key="circuit:pool_pump")


def test_running_within_local_schedule_is_expected() -> None:
    now = datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE)

    context = evaluate_expected_schedule(
        _settings(),
        now=now,
        is_running=True,
        source_available=True,
    )

    assert context.status == "running_in_expected_window"
    assert context.alert_ready is False
    assert context.expected_window_active is True


def test_running_outside_schedule_is_a_watch_until_repeated() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE)

    first = evaluate_expected_schedule(
        _settings(),
        now=now,
        is_running=True,
        source_available=True,
        outside_window_count=1,
    )
    repeated = evaluate_expected_schedule(
        _settings(),
        now=now,
        is_running=True,
        source_available=True,
        outside_window_count=3,
    )

    assert first.status == "running_outside_expected_window"
    assert first.alert_ready is False
    assert repeated.alert_ready is True


def test_one_missed_window_learns_but_repeated_misses_are_actionable() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE)

    first = evaluate_expected_schedule(
        _settings(),
        now=now,
        is_running=False,
        source_available=True,
        completed_window_missed=True,
        missed_window_count=1,
    )
    repeated = evaluate_expected_schedule(
        _settings(),
        now=now,
        is_running=False,
        source_available=True,
        completed_window_missed=True,
        missed_window_count=3,
    )

    assert first.status == "learning"
    assert first.alert_ready is False
    assert repeated.status == "did_not_run_in_expected_window"
    assert repeated.alert_ready is True


def test_schedule_entity_unavailable_suppresses_context() -> None:
    context = evaluate_expected_schedule(
        _settings(schedule_entity_id="schedule.pool_pump", windows=[]),
        now=datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
        is_running=True,
        source_available=True,
        schedule_state="unavailable",
    )

    assert context.status == "schedule_not_active"
    assert context.suppressed_reason == "schedule_unavailable"
    assert context.alert_ready is False


def test_maintenance_suppresses_schedule_findings() -> None:
    context = evaluate_expected_schedule(
        _settings(),
        now=datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE),
        is_running=True,
        source_available=True,
        maintenance_active=True,
        outside_window_count=5,
    )

    assert context.status == "schedule_not_active"
    assert context.suppressed_reason == "maintenance_active"
    assert context.alert_ready is False


def test_local_window_handles_dst_spring_forward_boundary() -> None:
    settings = schedule_settings_from_dict(
        {
            "enabled": True,
            "windows": [
                {
                    "start": "01:30",
                    "end": "03:30",
                    "weekdays": [6],
                }
            ],
        },
        appliance_key="circuit:pool_pump",
    )

    state = schedule_window_state(
        settings,
        datetime(2026, 3, 8, 3, 15, tzinfo=TIME_ZONE),
    )

    assert state.active is True
    assert state.current_start is not None
    assert state.current_end is not None
    assert state.current_end.astimezone(ZoneInfo("UTC")) > (
        state.current_start.astimezone(ZoneInfo("UTC"))
    )


def test_nonexistent_dst_window_is_skipped_instead_of_false_missed() -> None:
    settings = schedule_settings_from_dict(
        {
            "enabled": True,
            "windows": [
                {
                    "start": "02:30",
                    "end": "03:30",
                    "weekdays": [6],
                }
            ],
        },
        appliance_key="circuit:pool_pump",
    )

    state = schedule_window_state(
        settings,
        datetime(2026, 3, 8, 3, 15, tzinfo=TIME_ZONE),
    )

    assert state.active is False
    assert not str(state.completed_window_id or "").startswith("2026-03-08")


def test_cross_midnight_window_uses_the_start_day_weekday() -> None:
    settings = schedule_settings_from_dict(
        {
            "enabled": True,
            "windows": [
                {
                    "start": "22:00",
                    "end": "02:00",
                    "weekdays": [0],
                }
            ],
        },
        appliance_key="circuit:ev_charger",
    )

    state = schedule_window_state(
        settings,
        datetime(2026, 7, 14, 1, 0, tzinfo=TIME_ZONE),
    )

    assert state.active is True
    assert state.current_start is not None
    assert state.current_start.weekday() == 0


def _coordinator(
    *,
    events: list[CircuitEvent] | None = None,
    maintenance: bool = False,
    source_fresh: bool = True,
) -> SimpleNamespace:
    store_data = SimpleNamespace(
        appliance_schedule_settings={
            "circuit:pool_pump": _settings().as_dict(),
        },
        appliance_schedule_evidence={},
        maintenance_by_circuit=(
            {"pool_pump": {"active": True}} if maintenance else {}
        ),
        events=events or [],
    )
    return SimpleNamespace(
        hass=SimpleNamespace(
            config=SimpleNamespace(time_zone="America/New_York"),
            states=SimpleNamespace(get=lambda entity_id: None),
        ),
        state=SimpleNamespace(
            operating_state_by_circuit={"pool_pump": "off"},
            data_quality_checklist_by_circuit={
                "pool_pump": {
                    "required_sensors_present": True,
                    "source_data_fresh": source_fresh,
                    "numeric_states_valid": True,
                }
            },
            expected_schedule_by_appliance={},
        ),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )


def test_completed_window_with_minimum_runtime_is_not_missed() -> None:
    events = [
        CircuitEvent(
            timestamp=datetime(2026, 7, 13, 8, 10, tzinfo=TIME_ZONE),
            circuit_id="pool_pump",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=datetime(2026, 7, 13, 8, 45, tzinfo=TIME_ZONE),
            circuit_id="pool_pump",
            event_type=EventType.STOP,
        ),
    ]
    coordinator = _coordinator(events=events)

    alerts = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE),
    )

    context = coordinator.state.expected_schedule_by_appliance["circuit:pool_pump"]
    assert alerts == []
    assert context["status"] == "schedule_not_active"
    assert coordinator.store_data.appliance_schedule_evidence[
        "circuit:pool_pump"
    ]["missed_window_ids"] == []


def test_three_distinct_missed_windows_create_one_alert() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings["circuit:pool_pump"] = (
        _settings(
            windows=[
                {"start": "08:00", "end": "10:00", "weekdays": [0]},
            ]
        ).as_dict()
    )

    first = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE),
    )
    second = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 20, 12, 0, tzinfo=TIME_ZONE),
    )
    third = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 27, 12, 0, tzinfo=TIME_ZONE),
    )
    repeated = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 27, 12, 5, tzinfo=TIME_ZONE),
    )

    context = coordinator.state.expected_schedule_by_appliance["circuit:pool_pump"]
    assert first == []
    assert second == []
    assert len(third) == 1
    assert third[0].feature == "expected_schedule_missed"
    assert third[0].repeated_count == 3
    assert repeated == []
    assert context["status"] == "did_not_run_in_expected_window"


def test_maintenance_and_stale_source_do_not_record_missed_windows() -> None:
    maintenance = _coordinator(maintenance=True)
    stale = _coordinator(source_fresh=False)
    now = datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE)

    maintenance_alerts = refresh_expected_schedule_contexts(maintenance, now)
    stale_alerts = refresh_expected_schedule_contexts(stale, now)

    assert maintenance_alerts == []
    assert stale_alerts == []
    assert maintenance.store_data.appliance_schedule_evidence == {}
    assert stale.store_data.appliance_schedule_evidence == {}
    assert maintenance.state.expected_schedule_by_appliance[
        "circuit:pool_pump"
    ]["suppressed_reason"] == "maintenance_active"
    assert stale.state.expected_schedule_by_appliance["circuit:pool_pump"][
        "suppressed_reason"
    ] == "source_unavailable"


def test_schedule_entity_state_is_preferred_over_local_windows() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings["circuit:pool_pump"] = (
        _settings(
            schedule_entity_id="schedule.pool_pump",
            windows=[],
        ).as_dict()
    )
    coordinator.state.operating_state_by_circuit["pool_pump"] = "running"
    coordinator.hass.states.get = lambda entity_id: SimpleNamespace(
        state="on",
        last_changed=datetime(2026, 7, 13, 8, 0, tzinfo=TIME_ZONE),
    )

    alerts = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )

    assert alerts == []
    assert coordinator.state.expected_schedule_by_appliance[
        "circuit:pool_pump"
    ]["status"] == "running_in_expected_window"


def test_three_distinct_outside_sessions_create_one_watch_alert() -> None:
    coordinator = _coordinator()
    coordinator.state.operating_state_by_circuit["pool_pump"] = "running"
    alerts = []
    for day in (13, 20, 27):
        start = datetime(2026, 7, day, 12, 0, tzinfo=TIME_ZONE)
        if coordinator.store_data.events:
            coordinator.store_data.events.append(
                CircuitEvent(
                    timestamp=start.replace(hour=11),
                    circuit_id="pool_pump",
                    event_type=EventType.STOP,
                )
            )
        coordinator.store_data.events.append(
            CircuitEvent(
                timestamp=start,
                circuit_id="pool_pump",
                event_type=EventType.START,
            )
        )
        alerts.extend(
            refresh_expected_schedule_contexts(
                coordinator,
                start.replace(minute=5),
            )
        )

    assert len(alerts) == 1
    assert alerts[0].feature == "running_outside_expected_schedule"
    assert alerts[0].repeated_count == 3


def test_validated_nilm_session_uses_the_same_schedule_context() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings = {
        "nilm:assignment-pool-pump": _settings().as_dict()
    }
    coordinator.store_data.appliance_schedule_settings[
        "nilm:assignment-pool-pump"
    ]["appliance_key"] = "nilm:assignment-pool-pump"
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-pool-pump",
                "appliance_key": "nilm:assignment-pool-pump",
                "lifecycle_state": "validated",
                "confidence": 0.91,
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": "session-running",
                "assignment_id": "assignment-pool-pump",
                "start": "2026-07-13T08:15:00-04:00",
                "end": None,
                "confidence": 0.92,
            }
        ]
    }
    coordinator.state.data_quality_checklist_by_circuit["mains"] = {
        "required_sensors_present": True,
        "source_data_fresh": True,
        "numeric_states_valid": True,
    }

    alerts = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )

    assert alerts == []
    assert coordinator.state.expected_schedule_by_appliance[
        "nilm:assignment-pool-pump"
    ]["status"] == "running_in_expected_window"


def test_converted_nilm_identity_uses_its_direct_meter_runtime() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings = {
        "nilm:assignment-pool-pump": {
            **_settings().as_dict(),
            "appliance_key": "nilm:assignment-pool-pump",
        }
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-pool-pump",
                "appliance_key": "nilm:assignment-pool-pump",
                "conversion_state": "direct_meter",
                "direct_circuit_id": "pool_pump",
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {}
    coordinator.state.operating_state_by_circuit["pool_pump"] = "running"

    alerts = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )

    assert alerts == []
    assert coordinator.state.expected_schedule_by_appliance[
        "nilm:assignment-pool-pump"
    ]["status"] == "running_in_expected_window"


def test_low_confidence_nilm_schedule_does_not_record_findings() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings = {
        "nilm:assignment-pool-pump": {
            **_settings().as_dict(),
            "appliance_key": "nilm:assignment-pool-pump",
        }
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-pool-pump",
                "appliance_key": "nilm:assignment-pool-pump",
                "lifecycle_state": "validated",
                "confidence": 0.62,
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {"mains": []}
    coordinator.state.data_quality_checklist_by_circuit["mains"] = {
        "required_sensors_present": True,
        "source_data_fresh": True,
        "numeric_states_valid": True,
    }

    refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 12, 0, tzinfo=TIME_ZONE),
    )

    assert coordinator.store_data.appliance_schedule_evidence == {}
    assert coordinator.state.expected_schedule_by_appliance[
        "nilm:assignment-pool-pump"
    ]["suppressed_reason"] == "source_unavailable"


def test_expected_in_window_session_resets_old_outside_evidence() -> None:
    start = datetime(2026, 7, 13, 8, 15, tzinfo=TIME_ZONE)
    coordinator = _coordinator(
        events=[
            CircuitEvent(
                timestamp=start,
                circuit_id="pool_pump",
                event_type=EventType.START,
            )
        ]
    )
    coordinator.state.operating_state_by_circuit["pool_pump"] = "running"
    coordinator.store_data.appliance_schedule_evidence = {
        "circuit:pool_pump": {
            "outside_session_ids": ["outside-1", "outside-2", "outside-3"],
        }
    }

    alerts = refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )

    assert alerts == []
    assert coordinator.store_data.appliance_schedule_evidence[
        "circuit:pool_pump"
    ]["outside_session_ids"] == []


def test_delayed_refresh_evaluates_every_completed_local_window() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings["circuit:pool_pump"] = (
        _settings(
            windows=[
                {"start": "08:00", "end": "08:01", "weekdays": [0]},
                {"start": "08:02", "end": "08:03", "weekdays": [0]},
            ],
            minimum_duration_minutes=1,
        ).as_dict()
    )

    refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 8, 5, tzinfo=TIME_ZONE),
    )

    evidence = coordinator.store_data.appliance_schedule_evidence[
        "circuit:pool_pump"
    ]
    assert len(evidence["evaluated_window_ids"]) == 2
    assert len(evidence["missed_window_ids"]) == 2


def test_schedule_entity_unavailable_span_is_not_counted_after_recovery() -> None:
    coordinator = _coordinator()
    coordinator.store_data.appliance_schedule_settings["circuit:pool_pump"] = (
        _settings(
            schedule_entity_id="schedule.pool_pump",
            windows=[],
        ).as_dict()
    )
    schedule_state = {
        "value": "on",
        "last_changed": datetime(2026, 7, 13, 8, 0, tzinfo=TIME_ZONE),
    }
    coordinator.hass.states.get = lambda entity_id: SimpleNamespace(
        state=schedule_state["value"],
        last_changed=schedule_state["last_changed"],
    )

    refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 8, 15, tzinfo=TIME_ZONE),
    )
    schedule_state.update(
        value="unavailable",
        last_changed=datetime(2026, 7, 13, 8, 30, tzinfo=TIME_ZONE),
    )
    refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 8, 30, tzinfo=TIME_ZONE),
    )
    schedule_state.update(
        value="off",
        last_changed=datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )
    refresh_expected_schedule_contexts(
        coordinator,
        datetime(2026, 7, 13, 9, 0, tzinfo=TIME_ZONE),
    )

    evidence = coordinator.store_data.appliance_schedule_evidence[
        "circuit:pool_pump"
    ]
    assert evidence.get("missed_window_ids", []) == []
