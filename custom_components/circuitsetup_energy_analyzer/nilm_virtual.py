from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import DOMAIN
from .models import AlertEvidence, SensorRole, Severity
from .nilm import NilmEdge, NilmSession, pair_nilm_sessions

NILM_FINISHED_CONFIDENCE_THRESHOLD = 0.8
NILM_UNUSUAL_CONFIDENCE_THRESHOLD = 0.8
NILM_UNUSUAL_MIN_REPEATED = 2
NILM_VALIDATED_MODEL_STATES = frozenset({"published", "validated"})


@dataclass(frozen=True, slots=True)
class NilmVirtualApplianceState:
    """Panel/entity state for one estimated NILM appliance assignment."""

    appliance_id: str
    assignment_id: str
    display_name: str
    is_running: bool
    estimated_power_w: float
    estimated_energy_kwh_today: float
    confidence: float
    last_seen: datetime | None
    active_signature_id: str | None
    active_session_id: str | None
    latest_session_id: str | None
    model_status: str
    mains_circuit_id: str
    mains_source: str | None = None
    appliance_profile: str | None = None
    last_validation: str | None = None


def published_nilm_virtual_appliance_states(
    coordinator: Any,
) -> tuple[NilmVirtualApplianceState, ...]:
    """Return published, non-retired NILM virtual appliances."""
    return nilm_virtual_appliance_states(coordinator, published_only=True)


def nilm_virtual_appliance_states(
    coordinator: Any,
    *,
    published_only: bool = False,
) -> tuple[NilmVirtualApplianceState, ...]:
    """Return estimated NILM appliance states from persisted assignments."""
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return ()

    states: list[NilmVirtualApplianceState] = []
    for circuit_id, assignments in assignments_by_circuit.items():
        circuit_id_text = str(circuit_id or "").strip()
        edges = _nilm_edges_for_circuit(coordinator, circuit_id_text)
        signatures_by_id = _nilm_signatures_by_id(coordinator, circuit_id_text)
        for assignment in _iter_items(assignments):
            if not isinstance(assignment, Mapping):
                continue
            if published_only and not _published_assignment(assignment):
                continue
            state = _nilm_virtual_appliance_state(
                coordinator,
                circuit_id_text,
                assignment,
                edges,
                signatures_by_id,
            )
            if state is not None:
                states.append(state)
    return tuple(states)


def nilm_virtual_unique_id(
    entry_id: str,
    state: NilmVirtualApplianceState,
    key: str,
) -> str:
    """Return a stable unique id for one estimated NILM entity."""
    return f"{entry_id}_nilm_{state.assignment_id}_{key}"


def nilm_virtual_device_info(
    entry_id: str,
    state: NilmVirtualApplianceState,
) -> dict[str, Any]:
    """Return device registry metadata for an estimated NILM appliance."""
    return {
        "identifiers": {(DOMAIN, f"{entry_id}_nilm_{state.assignment_id}")},
        "name": state.display_name,
        "manufacturer": "CircuitSetup",
        "model": "NILM Estimated Appliance",
        "via_device": (DOMAIN, f"{entry_id}_{state.mains_circuit_id}"),
    }


def nilm_virtual_appliance_alerts(
    coordinator: Any,
    *,
    now: datetime,
) -> tuple[AlertEvidence, ...]:
    """Return eligible estimated-appliance notification alerts."""
    alerts: list[AlertEvidence] = []
    for state in published_nilm_virtual_appliance_states(coordinator):
        assignment = _assignment_for_state(coordinator, state)
        for alert in (
            nilm_virtual_finished_alert(state, now=now),
            nilm_virtual_unusual_runtime_alert(state, assignment, now=now),
            nilm_virtual_unusual_energy_alert(state, assignment, now=now),
        ):
            if alert is not None:
                alerts.append(alert)
    return tuple(alerts)


def nilm_virtual_finished_alert(
    state: Any,
    *,
    now: datetime,
) -> AlertEvidence | None:
    """Return a finished-running notification for a confident NILM appliance."""
    confidence = _clamped_float(getattr(state, "confidence", None), upper=1.0)
    session_id = str(getattr(state, "latest_session_id", "") or "").strip()
    model_status = str(getattr(state, "model_status", "") or "").strip()
    if (
        getattr(state, "is_running", False)
        or confidence < NILM_FINISHED_CONFIDENCE_THRESHOLD
        or model_status not in NILM_VALIDATED_MODEL_STATES
        or not session_id
    ):
        return None
    assignment_id = str(getattr(state, "assignment_id", "") or "").strip()
    if not assignment_id:
        return None
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.INFO,
        message=_nilm_alert_message(
            state,
            "appears finished",
            confidence=confidence,
        ),
        feature="nilm_appliance_finished",
        observed_value=_clamped_float(
            getattr(state, "estimated_energy_kwh_today", None),
        ),
        baseline_value=NILM_FINISHED_CONFIDENCE_THRESHOLD,
        repeated_count=1,
        last_seen=getattr(state, "last_seen", None),
        features=_nilm_alert_features(
            state,
            "finished",
            f"{assignment_id}:{session_id}",
        ),
    )


def nilm_virtual_unusual_runtime_alert(
    state: Any,
    assignment: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> AlertEvidence | None:
    """Return an unusual-runtime notification after repeated confident evidence."""
    if assignment is None or not getattr(state, "is_running", False):
        return None
    if not _nilm_unusual_alert_allowed(state):
        return None
    started_at = getattr(state, "last_seen", None)
    if not isinstance(started_at, datetime):
        return None
    baseline_minutes = _optional_positive_float(
        assignment.get("expected_runtime_minutes"),
    )
    observed_minutes = max(0.0, (now - started_at).total_seconds() / 60.0)
    repeated_count = _positive_int(assignment.get("unusual_runtime_repeated_count"))
    if (
        baseline_minutes is None
        or observed_minutes <= baseline_minutes
        or repeated_count < NILM_UNUSUAL_MIN_REPEATED
    ):
        return None
    assignment_id = str(getattr(state, "assignment_id", "") or "").strip()
    session_id = (
        str(getattr(state, "active_session_id", "") or "").strip()
        or str(getattr(state, "latest_session_id", "") or "").strip()
        or "current"
    )
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.WARNING,
        message=_nilm_alert_message(
            state,
            "appears to be running longer than usual",
            confidence=_clamped_float(getattr(state, "confidence", None), upper=1.0),
        ),
        feature="nilm_appliance_unusual_runtime",
        observed_value=round(observed_minutes, 3),
        baseline_value=round(baseline_minutes, 3),
        change_ratio=_change_ratio(observed_minutes, baseline_minutes),
        repeated_count=repeated_count,
        first_seen=started_at,
        last_seen=now,
        features=_nilm_alert_features(
            state,
            "unusual_runtime",
            f"{assignment_id}:runtime:{session_id}",
        ),
    )


def nilm_virtual_unusual_energy_alert(
    state: Any,
    assignment: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> AlertEvidence | None:
    """Return an unusual-energy notification after repeated confident evidence."""
    if assignment is None or not _nilm_unusual_alert_allowed(state):
        return None
    baseline_kwh = _optional_positive_float(assignment.get("expected_daily_energy_kwh"))
    observed_kwh = _clamped_float(getattr(state, "estimated_energy_kwh_today", None))
    repeated_count = _positive_int(assignment.get("unusual_energy_repeated_count"))
    if (
        baseline_kwh is None
        or observed_kwh <= baseline_kwh
        or repeated_count < NILM_UNUSUAL_MIN_REPEATED
    ):
        return None
    assignment_id = str(getattr(state, "assignment_id", "") or "").strip()
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.WARNING,
        message=_nilm_alert_message(
            state,
            "appears to be using more energy than usual today",
            confidence=_clamped_float(getattr(state, "confidence", None), upper=1.0),
        ),
        feature="nilm_appliance_unusual_energy",
        observed_value=round(observed_kwh, 3),
        baseline_value=round(baseline_kwh, 3),
        change_ratio=_change_ratio(observed_kwh, baseline_kwh),
        repeated_count=repeated_count,
        last_seen=getattr(state, "last_seen", None),
        features=_nilm_alert_features(
            state,
            "unusual_energy",
            f"{assignment_id}:energy:{now.date().isoformat()}",
        ),
    )


def nilm_virtual_attributes(state: NilmVirtualApplianceState) -> dict[str, Any]:
    """Return common attributes for estimated NILM entities."""
    return {
        "estimated": True,
        "source": "nilm",
        "assignment_id": state.assignment_id,
        "mains_source": state.mains_source,
        "confidence": state.confidence,
        "model_status": state.model_status,
        "last_validation": state.last_validation,
    }


def _nilm_virtual_appliance_state(
    coordinator: Any,
    circuit_id: str,
    assignment: Mapping[str, Any],
    edges: list[NilmEdge],
    signatures_by_id: Mapping[str, Mapping[str, Any]],
) -> NilmVirtualApplianceState | None:
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if not assignment_id:
        return None
    sessions = _nilm_assignment_sessions(
        circuit_id,
        assignment,
        edges,
        signatures_by_id,
    )
    open_session = _latest_nilm_session(
        session for session in sessions if session.end is None
    )
    latest_session = open_session or _latest_nilm_session(sessions)
    reference_date = _nilm_reference_date(edges, sessions)
    return NilmVirtualApplianceState(
        appliance_id=str(assignment.get("appliance_id") or assignment_id),
        assignment_id=assignment_id,
        display_name=str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment_id
        ),
        is_running=open_session is not None,
        estimated_power_w=(
            round(float(open_session.median_power_w), 3) if open_session else 0.0
        ),
        estimated_energy_kwh_today=_nilm_daily_energy(sessions, reference_date),
        confidence=_clamped_float(assignment.get("confidence"), upper=1.0),
        last_seen=_nilm_session_seen(latest_session),
        active_signature_id=(
            open_session.signature_fingerprint if open_session else None
        ),
        active_session_id=open_session.session_id if open_session else None,
        latest_session_id=latest_session.session_id if latest_session else None,
        model_status=str(assignment.get("lifecycle_state") or "candidate"),
        mains_circuit_id=circuit_id,
        mains_source=_mains_source_entity_id(coordinator, circuit_id),
        appliance_profile=(
            str(assignment.get("appliance_profile"))
            if assignment.get("appliance_profile")
            else None
        ),
        last_validation=(
            str(assignment.get("last_validation"))
            if assignment.get("last_validation")
            else None
        ),
    )


def _published_assignment(assignment: Mapping[str, Any]) -> bool:
    return (
        assignment.get("publish_entities") is True
        and str(assignment.get("lifecycle_state") or "") != "retired"
    )


def _assignment_for_state(
    coordinator: Any,
    state: Any,
) -> Mapping[str, Any] | None:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return None
    circuit_id = str(getattr(state, "mains_circuit_id", "") or "")
    assignment_id = str(getattr(state, "assignment_id", "") or "")
    for assignment in _iter_items(assignments_by_circuit.get(circuit_id)):
        if (
            isinstance(assignment, Mapping)
            and str(assignment.get("assignment_id") or "") == assignment_id
        ):
            return assignment
    return None


def _nilm_unusual_alert_allowed(state: Any) -> bool:
    confidence = _clamped_float(getattr(state, "confidence", None), upper=1.0)
    model_status = str(getattr(state, "model_status", "") or "").strip()
    return (
        confidence >= NILM_UNUSUAL_CONFIDENCE_THRESHOLD
        and model_status in NILM_VALIDATED_MODEL_STATES
    )


def _nilm_alert_message(
    state: Any,
    phrase: str,
    *,
    confidence: float,
) -> str:
    return (
        f"{getattr(state, 'display_name', 'NILM appliance')} {phrase}. "
        "Estimated from mains power by NILM. "
        f"Confidence: {round(confidence * 100)}%."
    )


def _nilm_alert_features(
    state: Any,
    notification_type: str,
    notification_key: str,
) -> dict[str, Any]:
    return {
        "source": "nilm",
        "estimated": True,
        "assignment_id": str(getattr(state, "assignment_id", "") or ""),
        "appliance_id": str(getattr(state, "appliance_id", "") or ""),
        "notification_type": notification_type,
        "notification_key": notification_key,
    }


def _nilm_assignment_sessions(
    circuit_id: str,
    assignment: Mapping[str, Any],
    edges: list[NilmEdge],
    signatures_by_id: Mapping[str, Mapping[str, Any]],
) -> list[NilmSession]:
    sessions: list[NilmSession] = []
    assignment_id = str(assignment.get("assignment_id") or "").strip() or None
    for value in _iter_items(assignment.get("signature_fingerprints")):
        fingerprint = str(value or "").strip()
        if not fingerprint:
            continue
        signature_edges = _nilm_edges_matching_signature(
            edges,
            signatures_by_id.get(fingerprint),
        )
        sessions.extend(
            pair_nilm_sessions(
                signature_edges,
                mains_circuit_id=circuit_id,
                signature_fingerprint=fingerprint,
                assignment_id=assignment_id,
            )
        )
    return sessions


def _nilm_signatures_by_id(
    coordinator: Any,
    circuit_id: str,
) -> dict[str, Mapping[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    signatures_by_circuit = getattr(store_data, "nilm_signatures", {})
    if not isinstance(signatures_by_circuit, Mapping):
        return {}
    signatures: dict[str, Mapping[str, Any]] = {}
    for signature in _iter_items(signatures_by_circuit.get(circuit_id, ())):
        if not isinstance(signature, Mapping):
            continue
        for key in ("signature_id", "feedback_fingerprint"):
            value = str(signature.get(key) or "").strip()
            if value:
                signatures[value] = signature
    return signatures


def _nilm_edges_matching_signature(
    edges: list[NilmEdge],
    signature: Mapping[str, Any] | None,
) -> list[NilmEdge]:
    if signature is None:
        return edges
    watts = _signature_watts(signature)
    split_phase_type = str(signature.get("split_phase_type") or "").strip()
    return [
        edge
        for edge in edges
        if _nilm_edge_matches_watts(edge, watts)
        and _nilm_edge_matches_split_phase(edge, split_phase_type)
    ]


def _signature_watts(signature: Mapping[str, Any]) -> float | None:
    for key in ("median_delta_w", "typical_watts"):
        value = signature.get(key)
        if isinstance(value, (int, float)) and abs(float(value)) > 0:
            return abs(float(value))
    return None


def _nilm_edge_matches_watts(edge: NilmEdge, watts: float | None) -> bool:
    if watts is None:
        return True
    tolerance = max(watts * 0.25, 50.0)
    return abs(abs(float(edge.delta_w)) - watts) <= tolerance


def _nilm_edge_matches_split_phase(edge: NilmEdge, split_phase_type: str) -> bool:
    if split_phase_type in {"", "unknown", "mixed"}:
        return True
    edge_type = str(edge.split_phase_type or "").strip()
    if edge_type in {"", "unknown", "mixed"}:
        return True
    if split_phase_type == edge_type:
        return True
    return split_phase_type == "single_leg" and edge_type.startswith("single_leg")


def _nilm_edges_for_circuit(coordinator: Any, circuit_id: str) -> list[NilmEdge]:
    edges_by_circuit = getattr(coordinator, "_nilm_unmatched_edges", {})
    if not isinstance(edges_by_circuit, Mapping):
        return []
    return [
        edge
        for edge in _iter_items(edges_by_circuit.get(circuit_id, ()))
        if isinstance(edge, NilmEdge)
    ]


def _latest_nilm_session(
    sessions: Iterable[NilmSession],
) -> NilmSession | None:
    latest: NilmSession | None = None
    latest_seen: datetime | None = None
    for session in sessions:
        seen = _nilm_session_seen(session)
        if seen is None:
            continue
        if latest_seen is None or seen > latest_seen:
            latest = session
            latest_seen = seen
    return latest


def _nilm_session_seen(session: NilmSession | None) -> datetime | None:
    if session is None:
        return None
    return session.end or session.start


def _nilm_reference_date(
    edges: list[NilmEdge],
    sessions: list[NilmSession],
) -> Any:
    latest_edge = max((edge.timestamp for edge in edges), default=None)
    if latest_edge is not None:
        return latest_edge.date()
    latest_session = _latest_nilm_session(sessions)
    seen = _nilm_session_seen(latest_session)
    return seen.date() if seen else None


def _nilm_daily_energy(
    sessions: list[NilmSession],
    reference_date: Any,
) -> float:
    if reference_date is None:
        return 0.0
    return round(
        sum(
            session.estimated_energy_kwh
            for session in sessions
            if session.start.date() == reference_date
        ),
        3,
    )


def _mains_source_entity_id(coordinator: Any, circuit_id: str) -> str | None:
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if str(getattr(config, "circuit_id", "")) != circuit_id:
            continue
        for sensor in getattr(config, "sensors", ()) or ():
            role = getattr(sensor, "role", None)
            try:
                sensor_role = role if isinstance(role, SensorRole) else SensorRole(role)
            except (TypeError, ValueError):
                continue
            if sensor_role is SensorRole.REAL_POWER:
                return str(getattr(sensor, "entity_id", "") or "") or None
    return None


def _clamped_float(value: Any, *, upper: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if upper is not None:
        return min(number, upper)
    return number


def _optional_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _change_ratio(observed_value: float, baseline_value: float) -> float:
    if baseline_value == 0:
        return 0.0
    return round((observed_value - baseline_value) / baseline_value, 3)


def _iter_items(value: Any) -> Iterable[Any]:
    if isinstance(value, (str, bytes)) or value is None:
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()
