from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .cycles import build_normalized_run_sessions
from .models import AlertEvidence
from .notifications import notification_id_for_alert

MAX_TIMELINE_SESSIONS = 40


@dataclass(frozen=True, slots=True)
class ApplianceTimelineSession:
    """Shared direct/NILM appliance session payload."""

    session_id: str
    appliance_key: str
    start: datetime
    end: datetime | None
    duration_seconds: float | None
    source_type: str
    confidence: float | None
    status: str
    alert_ids: tuple[str, ...]
    maintenance: bool
    estimated_energy_kwh: float | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat() if self.end else None
        return payload


def direct_appliance_timeline(
    coordinator: Any,
    circuit_id: str,
) -> tuple[ApplianceTimelineSession, ...]:
    """Build bounded direct sessions from retained start/stop transitions."""
    store_data = getattr(coordinator, "store_data", None)
    events = getattr(store_data, "events", ()) or ()
    alerts = tuple(getattr(store_data, "alerts", ()) or ())
    now = _coordinator_now(coordinator)
    sessions = build_normalized_run_sessions(
        events,
        circuit_id=circuit_id,
        merge_gap_seconds=60.0,
        now=now,
    )
    maintenance = _maintenance_window(store_data, circuit_id)
    result = [
        ApplianceTimelineSession(
            session_id=f"direct:{circuit_id}:{session.started_at.isoformat()}",
            appliance_key=f"circuit:{circuit_id}",
            start=session.started_at,
            end=session.stopped_at,
            duration_seconds=session.duration_seconds,
            source_type="direct_meter",
            confidence=None,
            status=(
                "anomalous"
                if _session_alert_ids(
                    alerts,
                    circuit_id=circuit_id,
                    start=session.started_at,
                    end=session.stopped_at or now,
                )
                else "running"
                if session.stopped_at is None
                else "completed"
            ),
            alert_ids=_session_alert_ids(
                alerts,
                circuit_id=circuit_id,
                start=session.started_at,
                end=session.stopped_at or now,
            ),
            maintenance=_window_overlaps(
                session.started_at,
                session.stopped_at or now,
                maintenance,
            ),
            estimated_energy_kwh=None,
        )
        for session in sessions[-MAX_TIMELINE_SESSIONS:]
    ]
    return tuple(result)


def nilm_appliance_timeline(
    state: Any,
    alerts: Iterable[AlertEvidence] = (),
    *,
    maintenance: Mapping[str, Any] | None = None,
) -> tuple[ApplianceTimelineSession, ...]:
    """Build bounded assignment-specific estimated sessions."""
    now = getattr(state, "reference_time", None) or datetime.now(UTC)
    rejected = set(getattr(state, "rejected_session_ids", ()) or ())
    confirmed = set(getattr(state, "confirmed_session_ids", ()) or ())
    adjusted = set(getattr(state, "adjusted_session_ids", ()) or ())
    appliance_key = str(getattr(state, "appliance_key", "") or "") or (
        f"nilm:{getattr(state, 'assignment_id', '')}"
    )
    maintenance_window = _maintenance_window_from_payload(maintenance or {})
    result: list[ApplianceTimelineSession] = []
    for payload in tuple(getattr(state, "sessions", ()) or ())[
        -MAX_TIMELINE_SESSIONS:
    ]:
        if not isinstance(payload, Mapping):
            continue
        start = _datetime_or_none(payload.get("start"))
        if start is None:
            continue
        end = _datetime_or_none(payload.get("end"))
        session_id = str(payload.get("session_id") or "").strip()
        alert_ids = _nilm_session_alert_ids(alerts, session_id)
        status = (
            "rejected"
            if session_id in rejected
            else "adjusted"
            if session_id in adjusted
            else "confirmed"
            if session_id in confirmed
            else "anomalous"
            if alert_ids
            else "running"
            if end is None
            else "estimated"
        )
        result.append(
            ApplianceTimelineSession(
                session_id=session_id,
                appliance_key=appliance_key,
                start=start,
                end=end,
                duration_seconds=(
                    _number_or_none(payload.get("duration_seconds"))
                    if end is not None
                    else max(
                        (now.astimezone(UTC) - start.astimezone(UTC)).total_seconds(),
                        0.0,
                    )
                ),
                source_type="nilm_estimate",
                confidence=_number_or_none(payload.get("confidence")),
                status=status,
                alert_ids=alert_ids,
                maintenance=bool(payload.get("maintenance"))
                or _window_overlaps(
                    start,
                    end or now,
                    maintenance_window,
                ),
                estimated_energy_kwh=_number_or_none(
                    payload.get("estimated_energy_kwh")
                ),
            )
        )
    return tuple(result)


def _session_alert_ids(
    alerts: Iterable[AlertEvidence],
    *,
    circuit_id: str,
    start: datetime,
    end: datetime,
) -> tuple[str, ...]:
    return tuple(
        notification_id_for_alert(alert)
        for alert in alerts
        if isinstance(alert, AlertEvidence)
        and alert.circuit_id == circuit_id
        and start <= alert.timestamp <= end
    )


def _nilm_session_alert_ids(
    alerts: Iterable[AlertEvidence],
    session_id: str,
) -> tuple[str, ...]:
    return tuple(
        notification_id_for_alert(alert)
        for alert in alerts
        if isinstance(alert, AlertEvidence)
        and str(alert.features.get("session_id") or "") == session_id
    )


def _maintenance_window(
    store_data: Any,
    circuit_id: str,
) -> tuple[datetime, datetime | None] | None:
    values = getattr(store_data, "maintenance_by_circuit", {})
    payload = values.get(circuit_id, {}) if isinstance(values, Mapping) else {}
    return _maintenance_window_from_payload(payload)


def _maintenance_window_from_payload(
    payload: Mapping[str, Any],
) -> tuple[datetime, datetime | None] | None:
    start = _datetime_or_none(payload.get("started_at"))
    if start is None:
        return None
    return start, _datetime_or_none(
        payload.get("ended_at") or payload.get("expires_at")
    )


def _window_overlaps(
    start: datetime,
    end: datetime,
    window: tuple[datetime, datetime | None] | None,
) -> bool:
    if window is None:
        return False
    window_start, window_end = window
    return start <= (window_end or end) and end >= window_start


def _coordinator_now(coordinator: Any) -> datetime:
    current_time = getattr(coordinator, "current_time", None)
    value = current_time() if callable(current_time) else datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
