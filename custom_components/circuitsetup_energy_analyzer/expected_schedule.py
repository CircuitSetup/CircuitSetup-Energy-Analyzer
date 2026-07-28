"""Conservative expected operating-window context for scheduled appliances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .cycles import build_normalized_run_sessions
from .models import AlertEvidence, EventType, Severity
from .ux import data_quality_checklist

DEFAULT_REQUIRED_REPEATS = 3
DEFAULT_MINIMUM_DURATION_MINUTES = 15


@dataclass(frozen=True, slots=True)
class ExpectedWindow:
    start: time
    end: time
    weekdays: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
            "weekdays": list(self.weekdays),
        }


@dataclass(frozen=True, slots=True)
class ExpectedScheduleSettings:
    appliance_key: str
    enabled: bool
    schedule_entity_id: str | None
    windows: tuple[ExpectedWindow, ...]
    minimum_duration_minutes: int
    required_repeats: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "appliance_key": self.appliance_key,
            "enabled": self.enabled,
            "schedule_entity_id": self.schedule_entity_id,
            "windows": [window.as_dict() for window in self.windows],
            "minimum_duration_minutes": self.minimum_duration_minutes,
            "required_repeats": self.required_repeats,
        }


@dataclass(frozen=True, slots=True)
class ScheduleWindowState:
    active: bool
    current_start: datetime | None
    current_end: datetime | None
    completed_start: datetime | None
    completed_end: datetime | None
    completed_window_id: str | None


@dataclass(frozen=True, slots=True)
class ExpectedScheduleContext:
    appliance_key: str
    status: str
    message: str
    expected_window_active: bool
    alert_ready: bool
    repeat_count: int
    suppressed_reason: str | None = None
    evidence_confidence: str = "low"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _ScheduleTarget:
    circuit_id: str
    source_type: str
    assignment_id: str | None = None
    confidence: float | None = None
    model_ready: bool = True
    rejected_session_ids: frozenset[str] = frozenset()


def schedule_settings_from_dict(
    raw: Mapping[str, Any] | None,
    *,
    appliance_key: str,
) -> ExpectedScheduleSettings:
    """Return bounded schedule settings from user-controlled storage data."""
    values = raw if isinstance(raw, Mapping) else {}
    schedule_entity_id = str(values.get("schedule_entity_id") or "").strip() or None
    if schedule_entity_id and not schedule_entity_id.startswith("schedule."):
        schedule_entity_id = None
    windows: list[ExpectedWindow] = []
    raw_windows = values.get("windows", ())
    for item in raw_windows if isinstance(raw_windows, list | tuple) else ():
        if not isinstance(item, Mapping):
            continue
        start = _time_or_none(item.get("start"))
        end = _time_or_none(item.get("end"))
        weekdays = _weekdays(item.get("weekdays"))
        if start is None or end is None or not weekdays:
            continue
        windows.append(ExpectedWindow(start, end, weekdays))
        if len(windows) >= 14:
            break
    return ExpectedScheduleSettings(
        appliance_key=str(appliance_key),
        enabled=values.get("enabled") is True,
        schedule_entity_id=schedule_entity_id,
        windows=tuple(windows),
        minimum_duration_minutes=_bounded_int(
            values.get("minimum_duration_minutes"),
            default=DEFAULT_MINIMUM_DURATION_MINUTES,
            minimum=1,
            maximum=1440,
        ),
        required_repeats=_bounded_int(
            values.get("required_repeats"),
            default=DEFAULT_REQUIRED_REPEATS,
            minimum=2,
            maximum=7,
        ),
    )


def schedule_window_state(
    settings: ExpectedScheduleSettings,
    now: datetime,
) -> ScheduleWindowState:
    """Resolve active and most recently completed local windows."""
    if now.tzinfo is None:
        msg = "expected schedule evaluation requires a timezone-aware datetime"
        raise ValueError(msg)
    local_now = now.astimezone(now.tzinfo)
    intervals = _local_window_intervals(settings, local_now)
    now_utc = local_now.astimezone(UTC)
    active = [
        interval
        for interval in intervals
        if interval[0].astimezone(UTC) <= now_utc < interval[1].astimezone(UTC)
    ]
    completed = [
        interval for interval in intervals if interval[1].astimezone(UTC) <= now_utc
    ]
    current = max(active, key=lambda interval: interval[0]) if active else None
    prior = max(completed, key=lambda interval: interval[1]) if completed else None
    return ScheduleWindowState(
        active=current is not None,
        current_start=current[0] if current else None,
        current_end=current[1] if current else None,
        completed_start=prior[0] if prior else None,
        completed_end=prior[1] if prior else None,
        completed_window_id=(
            f"{prior[0].isoformat()}|{prior[1].isoformat()}" if prior else None
        ),
    )


def evaluate_expected_schedule(
    settings: ExpectedScheduleSettings,
    *,
    now: datetime,
    is_running: bool,
    source_available: bool,
    schedule_state: str | None = None,
    maintenance_active: bool = False,
    completed_window_missed: bool = False,
    missed_window_count: int = 0,
    outside_window_count: int = 0,
) -> ExpectedScheduleContext:
    """Describe schedule context without promoting one observation to a fault."""
    if not settings.enabled or not (
        settings.schedule_entity_id or settings.windows
    ):
        return _suppressed(settings, "schedule_not_configured")
    if maintenance_active:
        return _suppressed(settings, "maintenance_active")
    if not source_available:
        return _suppressed(settings, "source_unavailable")

    if settings.schedule_entity_id:
        normalized_state = str(schedule_state or "unknown").lower()
        if normalized_state in {"unknown", "unavailable", "none", ""}:
            return _suppressed(settings, "schedule_unavailable")
        expected_active = normalized_state == "on"
    else:
        expected_active = schedule_window_state(settings, now).active

    if is_running and expected_active:
        return ExpectedScheduleContext(
            appliance_key=settings.appliance_key,
            status="running_in_expected_window",
            message="Running during the expected schedule.",
            expected_window_active=True,
            alert_ready=False,
            repeat_count=0,
            evidence_confidence="high",
        )
    if is_running:
        count = max(int(outside_window_count), 1)
        return ExpectedScheduleContext(
            appliance_key=settings.appliance_key,
            status="running_outside_expected_window",
            message=(
                "Running outside the expected schedule."
                if count >= settings.required_repeats
                else "Running outside the expected schedule; watching for repetition."
            ),
            expected_window_active=False,
            alert_ready=count >= settings.required_repeats,
            repeat_count=count,
            evidence_confidence=(
                "high" if count >= settings.required_repeats else "medium"
            ),
        )
    if completed_window_missed:
        count = max(int(missed_window_count), 1)
        if count >= settings.required_repeats:
            return ExpectedScheduleContext(
                appliance_key=settings.appliance_key,
                status="did_not_run_in_expected_window",
                message=(
                    f"Did not meet the expected runtime for {count} schedule windows."
                ),
                expected_window_active=False,
                alert_ready=True,
                repeat_count=count,
                evidence_confidence="high",
            )
        return ExpectedScheduleContext(
            appliance_key=settings.appliance_key,
            status="learning",
            message="Expected window was missed once; waiting for repeated evidence.",
            expected_window_active=False,
            alert_ready=False,
            repeat_count=count,
            evidence_confidence="low",
        )
    if expected_active:
        return ExpectedScheduleContext(
            appliance_key=settings.appliance_key,
            status="learning",
            message="Expected schedule is active; waiting for the appliance to run.",
            expected_window_active=True,
            alert_ready=False,
            repeat_count=0,
            evidence_confidence="low",
        )
    return ExpectedScheduleContext(
        appliance_key=settings.appliance_key,
        status="schedule_not_active",
        message="The expected schedule is not active now.",
        expected_window_active=False,
        alert_ready=False,
        repeat_count=0,
        evidence_confidence="low",
    )


def refresh_expected_schedule_contexts(
    coordinator: Any,
    now: datetime,
) -> list[AlertEvidence]:
    """Refresh direct-appliance schedule context and return newly promoted alerts."""
    store_data = getattr(coordinator, "store_data", None)
    state = getattr(coordinator, "state", None)
    raw_settings = getattr(store_data, "appliance_schedule_settings", {})
    if not isinstance(raw_settings, Mapping):
        raw_settings = {}
    raw_evidence = getattr(store_data, "appliance_schedule_evidence", None)
    if not isinstance(raw_evidence, dict):
        raw_evidence = {}
        store_data.appliance_schedule_evidence = raw_evidence
    time_zone = _coordinator_time_zone(coordinator)
    local_now = now.astimezone(time_zone)
    contexts: dict[str, dict[str, Any]] = {}
    alerts: list[AlertEvidence] = []
    changed = False

    for appliance_key, raw in raw_settings.items():
        key = str(appliance_key or "").strip()
        settings = schedule_settings_from_dict(raw, appliance_key=key)
        target = _schedule_target(store_data, key)
        circuit_id = target.circuit_id if target else None
        is_running = _target_is_running(state, store_data, target, local_now)
        source_available = _target_source_available(
            coordinator,
            state,
            target,
            local_now,
        )
        maintenance_active = _maintenance_active(store_data, state, circuit_id)
        schedule_state, schedule_state_object = _schedule_entity_state(
            coordinator,
            settings.schedule_entity_id,
        )
        if (
            not settings.enabled
            or target is None
            or maintenance_active
            or not source_available
            or (
                settings.schedule_entity_id
                and schedule_state in {None, "unknown", "unavailable"}
            )
        ):
            if settings.schedule_entity_id:
                evidence = raw_evidence.get(key)
                if isinstance(evidence, dict):
                    before = repr(evidence)
                    evidence.pop("active_window_start", None)
                    if repr(evidence) != before:
                        changed = True
            context = evaluate_expected_schedule(
                settings,
                now=local_now,
                is_running=is_running,
                source_available=source_available and circuit_id is not None,
                schedule_state=schedule_state,
                maintenance_active=maintenance_active,
            )
            contexts[key] = context.as_dict()
            continue

        before = repr(raw_evidence.get(key))
        evidence = raw_evidence.setdefault(key, {})
        if not isinstance(evidence, dict):
            evidence = {}
            raw_evidence[key] = evidence
        completed_windows = _completed_windows(
            settings,
            local_now,
            schedule_state,
            schedule_state_object,
            evidence,
        )
        completed_id = completed_windows[-1][2] if completed_windows else None
        missed_window_ids = _string_list(evidence.get("missed_window_ids"))
        evaluated_window_ids = _string_list(evidence.get("evaluated_window_ids"))
        last_evaluated_end = _datetime_or_none(
            evidence.get("last_evaluated_window_end")
        )
        if last_evaluated_end is None:
            initial_cutoff = local_now - timedelta(days=1)
            completed_windows = [
                item for item in completed_windows if item[1] >= initial_cutoff
            ]
        else:
            completed_windows = [
                item for item in completed_windows if item[1] > last_evaluated_end
            ]
        for completed_start, completed_end, window_id in completed_windows:
            if window_id in evaluated_window_ids:
                continue
            runtime_seconds = _runtime_within_window(
                store_data,
                target,
                completed_start,
                completed_end,
            )
            if runtime_seconds < settings.minimum_duration_minutes * 60:
                missed_window_ids.append(window_id)
                del missed_window_ids[:-14]
            else:
                missed_window_ids = []
            evaluated_window_ids.append(window_id)
            del evaluated_window_ids[:-14]
        if completed_windows:
            evidence["last_evaluated_window_end"] = completed_windows[-1][
                1
            ].isoformat()
        evidence["missed_window_ids"] = missed_window_ids
        evidence["evaluated_window_ids"] = evaluated_window_ids

        outside_session_ids = _string_list(evidence.get("outside_session_ids"))
        current_session_id = _target_current_session_id(
            store_data,
            target,
            local_now,
        )
        expected_active = (
            schedule_state == "on"
            if settings.schedule_entity_id
            else schedule_window_state(settings, local_now).active
        )
        if (
            is_running
            and not expected_active
            and current_session_id
            and current_session_id not in outside_session_ids
        ):
            outside_session_ids.append(current_session_id)
            del outside_session_ids[:-14]
        elif is_running and expected_active and current_session_id:
            outside_session_ids = []
        evidence["outside_session_ids"] = outside_session_ids

        completed_window_missed = bool(
            completed_id and completed_id in missed_window_ids
        )
        context = evaluate_expected_schedule(
            settings,
            now=local_now,
            is_running=is_running,
            source_available=True,
            schedule_state=schedule_state,
            completed_window_missed=completed_window_missed,
            missed_window_count=len(missed_window_ids),
            outside_window_count=len(outside_session_ids),
        )
        contexts[key] = context.as_dict()
        alert_evidence_id = (
            current_session_id
            if context.status == "running_outside_expected_window"
            else completed_id
        )
        if (
            context.alert_ready
            and alert_evidence_id
            and evidence.get("last_alert_evidence_id") != alert_evidence_id
        ):
            evidence["last_alert_evidence_id"] = alert_evidence_id
            alerts.append(
                _schedule_alert(
                    context,
                    target=target,
                    timestamp=now,
                    evidence_id=alert_evidence_id,
                    required_repeats=settings.required_repeats,
                )
            )
        if repr(evidence) != before:
            changed = True

    state.expected_schedule_by_appliance = contexts
    if changed:
        _mark_store_dirty(coordinator)
    return alerts


def _suppressed(
    settings: ExpectedScheduleSettings,
    reason: str,
) -> ExpectedScheduleContext:
    return ExpectedScheduleContext(
        appliance_key=settings.appliance_key,
        status="schedule_not_active",
        message={
            "maintenance_active": "Schedule findings are paused during maintenance.",
            "source_unavailable": (
                "Schedule context is paused until source data returns."
            ),
            "schedule_unavailable": (
                "The Home Assistant Schedule entity is unavailable."
            ),
        }.get(reason, "No expected operating schedule is configured."),
        expected_window_active=False,
        alert_ready=False,
        repeat_count=0,
        suppressed_reason=reason,
        evidence_confidence="low",
    )


def _coordinator_time_zone(coordinator: Any) -> ZoneInfo:
    configured = str(
        getattr(getattr(coordinator.hass, "config", None), "time_zone", "UTC")
        or "UTC"
    )
    try:
        return ZoneInfo(configured)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def _schedule_target(store_data: Any, appliance_key: str) -> _ScheduleTarget | None:
    prefix, separator, circuit_id = appliance_key.partition(":")
    if separator and prefix == "circuit" and circuit_id:
        return _ScheduleTarget(circuit_id=circuit_id, source_type="direct_meter")
    if not separator or prefix != "nilm" or not circuit_id:
        return None
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return None
    for mains_circuit_id, assignments in assignments_by_circuit.items():
        for assignment in assignments if isinstance(assignments, list) else ():
            if not isinstance(assignment, Mapping):
                continue
            assignment_id = str(assignment.get("assignment_id") or "")
            key = str(assignment.get("appliance_key") or f"nilm:{assignment_id}")
            if key != appliance_key:
                continue
            rejected = assignment.get("rejected_session_ids")
            if assignment.get("conversion_state") == "direct_meter":
                direct_circuit_id = str(
                    assignment.get("direct_circuit_id") or ""
                ).strip()
                if direct_circuit_id:
                    return _ScheduleTarget(
                        circuit_id=direct_circuit_id,
                        source_type="direct_meter",
                        assignment_id=assignment_id,
                    )
            lifecycle = str(assignment.get("lifecycle_state") or "")
            return _ScheduleTarget(
                circuit_id=str(mains_circuit_id),
                source_type="nilm_estimate",
                assignment_id=assignment_id,
                confidence=_float_or_none(assignment.get("confidence")),
                model_ready=lifecycle in {"confirmed", "published", "validated"},
                rejected_session_ids=frozenset(
                    str(value).strip()
                    for value in rejected
                    if str(value).strip()
                ) if isinstance(rejected, list | tuple | set) else frozenset(),
            )
    return None


def _target_is_running(
    state: Any,
    store_data: Any,
    target: _ScheduleTarget | None,
    now: datetime,
) -> bool:
    if target is None:
        return False
    if target.source_type == "nilm_estimate":
        return _nilm_current_session(store_data, target, now) is not None
    values = getattr(state, "operating_state_by_circuit", {})
    return bool(
        isinstance(values, Mapping)
        and values.get(target.circuit_id) == "running"
    )


def _target_source_available(
    coordinator: Any,
    state: Any,
    target: _ScheduleTarget | None,
    now: datetime,
) -> bool:
    if target is None:
        return False
    values = getattr(state, "data_quality_checklist_by_circuit", {})
    checklist = (
        values.get(target.circuit_id, {}) if isinstance(values, Mapping) else {}
    )
    live_checklist = _live_source_checklist(coordinator, target, now)
    if live_checklist is not None:
        checklist = live_checklist
    source_ready = bool(
        isinstance(checklist, Mapping)
        and checklist
        and checklist.get("required_sensors_present") is not False
        and checklist.get("source_data_fresh") is not False
        and checklist.get("numeric_states_valid") is not False
    )
    if target.source_type != "nilm_estimate":
        return source_ready
    return (
        source_ready
        and target.model_ready
        and (target.confidence or 0.0) >= 0.8
    )


def _live_source_checklist(
    coordinator: Any,
    target: _ScheduleTarget,
    now: datetime,
) -> Mapping[str, Any] | None:
    configs = getattr(coordinator, "circuit_configs", ())
    config = next(
        (
            item
            for item in configs
            if getattr(item, "circuit_id", None) == target.circuit_id
        ),
        None,
    )
    sample_for_config = getattr(coordinator, "_sample_for_config", None)
    if not callable(sample_for_config):
        source_samples = getattr(coordinator, "source_samples", None)
        sample_for_config = getattr(source_samples, "sample_for_config", None)
    if config is None or not callable(sample_for_config):
        return None
    return data_quality_checklist(config, sample_for_config(config, now))


def _maintenance_active(store_data: Any, state: Any, circuit_id: str | None) -> bool:
    if not circuit_id:
        return False
    for owner in (store_data, state):
        values = getattr(owner, "maintenance_by_circuit", {})
        item = values.get(circuit_id, {}) if isinstance(values, Mapping) else {}
        if isinstance(item, Mapping) and item.get("active") is True:
            return True
    return False


def _schedule_entity_state(
    coordinator: Any,
    entity_id: str | None,
) -> tuple[str | None, Any | None]:
    if not entity_id:
        return None, None
    states = getattr(coordinator.hass, "states", None)
    get_state = getattr(states, "get", None)
    state = get_state(entity_id) if callable(get_state) else None
    return (str(getattr(state, "state", "unavailable")).lower(), state)


def _completed_windows(
    settings: ExpectedScheduleSettings,
    now: datetime,
    schedule_state: str | None,
    schedule_state_object: Any,
    evidence: dict[str, Any],
) -> list[tuple[datetime, datetime, str]]:
    if not settings.schedule_entity_id:
        now_utc = now.astimezone(UTC)
        return [
            (started, ended, f"{started.isoformat()}|{ended.isoformat()}")
            for started, ended in _local_window_intervals(settings, now)
            if ended.astimezone(UTC) <= now_utc
        ]
    if schedule_state == "on":
        started = getattr(schedule_state_object, "last_changed", None)
        if not isinstance(started, datetime):
            started = now
        evidence.setdefault("active_window_start", started.isoformat())
        return []
    started = _datetime_or_none(evidence.pop("active_window_start", None))
    if started is None:
        return []
    ended = getattr(schedule_state_object, "last_changed", None)
    if not isinstance(ended, datetime) or ended <= started:
        ended = now
    return [(started, ended, f"{started.isoformat()}|{ended.isoformat()}")]


def _runtime_within_window(
    store_data: Any,
    target: _ScheduleTarget,
    start: datetime,
    end: datetime,
) -> float:
    if target.source_type == "nilm_estimate":
        return _nilm_runtime_within_window(store_data, target, start, end)
    events = getattr(store_data, "events", ())
    sessions = build_normalized_run_sessions(
        events if isinstance(events, list | tuple) else (),
        circuit_id=target.circuit_id,
        merge_gap_seconds=0.0,
        now=end,
    )
    total = 0.0
    for session in sessions:
        session_end = session.stopped_at or end
        overlap_start = max(session.started_at, start)
        overlap_end = min(session_end, end)
        if overlap_end > overlap_start:
            total += (
                overlap_end.astimezone(UTC) - overlap_start.astimezone(UTC)
            ).total_seconds()
    return total


def _target_current_session_id(
    store_data: Any,
    target: _ScheduleTarget,
    now: datetime,
) -> str | None:
    if target.source_type == "nilm_estimate":
        session = _nilm_current_session(store_data, target, now)
        return str(session.get("session_id") or "") or None if session else None
    events = getattr(store_data, "events", ())
    event_values = events if isinstance(events, list | tuple) else ()
    circuit_events = sorted(
        (
            event
            for event in event_values
            if getattr(event, "circuit_id", None) == target.circuit_id
            and getattr(event, "timestamp", now) <= now
            and getattr(event, "event_type", None) in {EventType.START, EventType.STOP}
        ),
        key=lambda event: event.timestamp,
    )
    if not circuit_events or circuit_events[-1].event_type is not EventType.START:
        return None
    return circuit_events[-1].timestamp.isoformat()


def _schedule_alert(
    context: ExpectedScheduleContext,
    *,
    target: _ScheduleTarget,
    timestamp: datetime,
    evidence_id: str,
    required_repeats: int,
) -> AlertEvidence:
    missed = context.status == "did_not_run_in_expected_window"
    feature = (
        "expected_schedule_missed"
        if missed
        else "running_outside_expected_schedule"
    )
    source_features = {
        "source_type": target.source_type,
        "assignment_id": target.assignment_id,
        "confidence": target.confidence,
    }
    return AlertEvidence(
        timestamp=timestamp,
        circuit_id=target.circuit_id,
        severity=Severity.WARNING,
        message=context.message,
        feature=feature,
        observed_value=float(context.repeat_count),
        baseline_value=float(required_repeats),
        repeated_count=context.repeat_count,
        features={
            **context.as_dict(),
            "appliance_key": context.appliance_key,
            "notification_type": "unusual_runtime",
            "notification_key": evidence_id,
            **{
                key: value
                for key, value in source_features.items()
                if value is not None
            },
        },
    )


def _nilm_sessions(store_data: Any, target: _ScheduleTarget) -> list[Mapping[str, Any]]:
    history = getattr(store_data, "nilm_session_history_by_circuit", {})
    sessions = (
        history.get(target.circuit_id, ()) if isinstance(history, Mapping) else ()
    )
    session_values = sessions if isinstance(sessions, list | tuple) else ()
    return [
        session
        for session in session_values
        if isinstance(session, Mapping)
        and str(session.get("assignment_id") or "") == target.assignment_id
        and str(session.get("session_id") or "").strip()
        not in target.rejected_session_ids
    ]


def _nilm_current_session(
    store_data: Any,
    target: _ScheduleTarget,
    now: datetime,
) -> Mapping[str, Any] | None:
    candidates = [
        session
        for session in _nilm_sessions(store_data, target)
        if not session.get("end")
        and (started := _datetime_or_none(session.get("start"))) is not None
        and started <= now
    ]
    return max(
        candidates,
        key=lambda session: _datetime_or_none(session.get("start")) or now,
    ) if candidates else None


def _nilm_runtime_within_window(
    store_data: Any,
    target: _ScheduleTarget,
    start: datetime,
    end: datetime,
) -> float:
    total = 0.0
    for session in _nilm_sessions(store_data, target):
        session_start = _datetime_or_none(session.get("start"))
        session_end = _datetime_or_none(session.get("end")) or end
        if session_start is None:
            continue
        overlap_start = max(session_start, start)
        overlap_end = min(session_end, end)
        if overlap_end > overlap_start:
            total += (
                overlap_end.astimezone(UTC) - overlap_start.astimezone(UTC)
            ).total_seconds()
    return total


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)][-14:]


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mark_store_dirty(coordinator: Any) -> None:
    persistence = getattr(coordinator, "store_persistence", None)
    mark_dirty = getattr(persistence, "mark_dirty", None)
    if callable(mark_dirty):
        mark_dirty()


def _local_window_intervals(
    settings: ExpectedScheduleSettings,
    reference: datetime,
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for offset in range(-8, 2):
        start_day = reference.date() + timedelta(days=offset)
        for window in settings.windows:
            if start_day.weekday() not in window.weekdays:
                continue
            interval = _window_interval(start_day, window, reference)
            if interval is not None:
                intervals.append(interval)
    return sorted(intervals, key=lambda item: item[1].astimezone(UTC))


def _window_interval(
    start_day: date,
    window: ExpectedWindow,
    reference: datetime,
) -> tuple[datetime, datetime] | None:
    end_day = start_day + timedelta(days=1) if window.end <= window.start else start_day
    started = _normalized_wall_datetime(
        start_day,
        window.start,
        reference,
        end_boundary=False,
    )
    ended = _normalized_wall_datetime(
        end_day,
        window.end,
        reference,
        end_boundary=True,
    )
    if ended.astimezone(UTC) <= started.astimezone(UTC):
        return None
    return started, ended


def _normalized_wall_datetime(
    day: date,
    clock: time,
    reference: datetime,
    *,
    end_boundary: bool,
) -> datetime:
    zone = reference.tzinfo
    candidate = datetime.combine(
        day,
        clock,
        tzinfo=zone,
    ).replace(fold=1 if end_boundary else 0)
    round_trip = candidate.astimezone(UTC).astimezone(zone)
    if round_trip.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        return round_trip
    return candidate


def _time_or_none(value: Any) -> time | None:
    try:
        parsed = time.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None, second=0, microsecond=0)


def _weekdays(value: Any) -> tuple[int, ...]:
    days: set[int] = set()
    for item in value if isinstance(value, list | tuple) else ():
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            days.add(day)
    return tuple(sorted(days))


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)
