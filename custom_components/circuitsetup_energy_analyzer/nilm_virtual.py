from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .appliance_metadata import existing_area_names_for_hass, suggested_area_for_profile
from .const import DOMAIN
from .discovery import (
    sensor_metadata_is_unsupported,
    sensor_metadata_role_conflict,
    sensor_role_from_metadata,
)
from .models import AlertEvidence, SensorRole, Severity
from .nilm import (
    NilmEdge,
    NilmSession,
    build_nilm_appliance_alert_payload,
    build_nilm_appliance_identity,
    evaluate_nilm_validation_readiness,
    nilm_session_to_dict,
    nilm_signature_is_assignable,
    pair_nilm_sessions_for_signatures,
    resolve_nilm_signature_fingerprint,
    summarize_nilm_assignment_sessions,
)

NILM_FINISHED_CONFIDENCE_THRESHOLD = 0.8
NILM_UNUSUAL_CONFIDENCE_THRESHOLD = 0.8
NILM_UNUSUAL_MIN_REPEATED = 2
NILM_VALIDATED_MODEL_STATES = frozenset({"published", "validated"})
NILM_REVIEW_MODEL_STATES = frozenset({"conflict", "low_confidence", "needs_validation"})


@dataclass(frozen=True, slots=True)
class NilmVirtualApplianceState:
    """Panel/entity state for one estimated NILM appliance assignment."""

    appliance_id: str
    assignment_id: str
    display_name: str
    is_running: bool | None
    estimated_power_w: float | None
    estimated_energy_kwh_today: float
    confidence: float
    last_seen: datetime | None
    active_signature_id: str | None
    active_session_id: str | None
    latest_session_id: str | None
    model_status: str
    mains_circuit_id: str
    mains_source: str | None = None
    entry_id: str = ""
    appliance_profile: str | None = None
    last_validation: str | None = None
    appliance_key: str = ""
    sessions: tuple[dict[str, Any], ...] = ()
    runtime_today_seconds: float = 0.0
    run_count_today: int = 0
    current_session_duration_seconds: float | None = None
    current_session_id: str | None = None
    last_matched_session_id: str | None = None
    latest_signature_id: str | None = None
    validation_readiness: dict[str, Any] | None = None
    confirmed_session_ids: frozenset[str] = frozenset()
    rejected_session_ids: frozenset[str] = frozenset()
    adjusted_session_ids: frozenset[str] = frozenset()
    reference_time: datetime | None = None
    time_zone: str = "UTC"
    reference_available: bool = False
    reference_state_entity_id: str | None = None
    reference_power_entity_id: str | None = None
    reference_measured_power_w: float | None = None
    reference_source_entity_id: str | None = None
    reference_fallback_to_nilm: bool = True


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
        assignment_list = [
            assignment
            for assignment in _iter_items(assignments)
            if isinstance(assignment, Mapping)
        ]
        derived_sessions = _nilm_assignment_sessions(
            circuit_id_text,
            [
                assignment
                for assignment in assignment_list
                if (
                    _published_assignment(assignment)
                    if published_only
                    else _matching_assignment(assignment)
                )
            ],
            edges,
            signatures_by_id,
        )
        for assignment in assignment_list:
            if published_only and not _published_assignment(assignment):
                continue
            state = _nilm_virtual_appliance_state(
                coordinator,
                circuit_id_text,
                assignment,
                edges,
                derived_sessions,
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
    hass: Any | None = None,
) -> dict[str, Any]:
    """Return device registry metadata for an estimated NILM appliance."""
    device_info = {
        "identifiers": {(DOMAIN, f"{entry_id}_nilm_{state.assignment_id}")},
        "name": state.display_name,
        "manufacturer": "CircuitSetup",
        "model": "NILM Estimated Appliance",
    }
    via_device = (DOMAIN, f"{entry_id}_{state.mains_circuit_id}")
    if hass is None or _device_identifier_exists(hass, via_device):
        device_info["via_device"] = via_device
    suggested_area = suggested_area_for_profile(
        state.appliance_profile,
        existing_area_names_for_hass(hass),
    )
    if suggested_area:
        device_info["suggested_area"] = suggested_area
    return device_info


def _device_identifier_exists(hass: Any, identifier: tuple[str, str]) -> bool:
    try:
        from homeassistant.helpers import device_registry as dr

        registry = dr.async_get(hass)
    except (AttributeError, ImportError, KeyError, TypeError):
        return True
    return registry.async_get_device(identifiers={identifier}) is not None


def nilm_virtual_appliance_alerts(
    coordinator: Any,
    *,
    now: datetime,
) -> tuple[AlertEvidence, ...]:
    """Return eligible estimated-appliance notification alerts."""
    alerts: list[AlertEvidence] = []
    for state in published_nilm_virtual_appliance_states(coordinator):
        assignment = _assignment_for_state(coordinator, state)
        alerts.extend(
            alert
            for alert in (
                nilm_virtual_low_confidence_alert(state, now=now),
                nilm_virtual_finished_alert(state, now=now),
                nilm_virtual_unusual_runtime_alert(state, assignment, now=now),
                nilm_virtual_unusual_energy_alert(state, assignment, now=now),
            )
            if alert is not None
        )
    return tuple(alerts)


def nilm_virtual_low_confidence_alert(
    state: Any,
    *,
    now: datetime,
) -> AlertEvidence | None:
    """Return a validation prompt when a published NILM appliance is uncertain."""
    confidence = _clamped_float(getattr(state, "confidence", None), upper=1.0)
    model_status = str(getattr(state, "model_status", "") or "").strip()
    low_confidence = confidence < NILM_FINISHED_CONFIDENCE_THRESHOLD
    needs_validation = model_status in NILM_REVIEW_MODEL_STATES
    if not (low_confidence or needs_validation):
        return None
    assignment_id = str(getattr(state, "assignment_id", "") or "").strip()
    if not assignment_id:
        return None
    if model_status == "conflict":
        notification_type = "model_drift"
        feature = "nilm_model_drift"
    elif low_confidence:
        notification_type = "low_confidence"
        feature = "nilm_low_confidence_change"
    else:
        notification_type = "needs_validation"
        feature = "nilm_assignment_needs_validation"
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.WARNING,
        message=_nilm_alert_message(
            state,
            "needs validation",
            confidence=confidence,
        ),
        feature=feature,
        value_metric="nilm_appliance_confidence",
        observed_value=confidence,
        baseline_value=NILM_FINISHED_CONFIDENCE_THRESHOLD,
        repeated_count=1,
        last_seen=getattr(state, "last_seen", None),
        features=_nilm_alert_features(
            state,
            notification_type,
            f"{assignment_id}:{notification_type}",
            confidence=confidence,
        ),
    )


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
        message=_nilm_finished_message(state, confidence=confidence),
        feature="nilm_appliance_finished",
        value_metric="nilm_appliance_confidence",
        observed_value=confidence,
        baseline_value=NILM_FINISHED_CONFIDENCE_THRESHOLD,
        repeated_count=1,
        last_seen=getattr(state, "last_seen", None),
        features=_nilm_alert_features(
            state,
            "finished",
            f"{assignment_id}:{session_id}",
            confidence=confidence,
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
    duration_seconds = _optional_positive_float(
        getattr(state, "current_session_duration_seconds", None)
    )
    if duration_seconds is None:
        return None
    baseline_minutes = _optional_positive_float(
        assignment.get("expected_runtime_minutes"),
    )
    observed_minutes = duration_seconds / 60.0
    started_at = now - timedelta(seconds=duration_seconds)
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
    confidence = _clamped_float(getattr(state, "confidence", None), upper=1.0)
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.WARNING,
        message=_nilm_alert_message(
            state,
            "appears to be running longer than usual",
            confidence=confidence,
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
            confidence=confidence,
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
    confidence = _clamped_float(getattr(state, "confidence", None), upper=1.0)
    return AlertEvidence(
        timestamp=now,
        circuit_id=str(getattr(state, "mains_circuit_id", "") or ""),
        severity=Severity.WARNING,
        message=_nilm_alert_message(
            state,
            "appears to be using more energy than usual today",
            confidence=confidence,
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
            confidence=confidence,
        ),
    )


def nilm_virtual_attributes(state: NilmVirtualApplianceState) -> dict[str, Any]:
    """Return common attributes for estimated NILM entities."""
    return {
        "estimated": True,
        "source": "nilm",
        "source_type": "nilm_estimate",
        "appliance_key": state.appliance_key,
        "assignment_id": state.assignment_id,
        "appliance_id": state.appliance_id,
        "appliance_profile": state.appliance_profile,
        "mains_circuit_id": state.mains_circuit_id,
        "mains_source": state.mains_source,
        "confidence": state.confidence,
        "model_status": state.model_status,
        "last_validation": state.last_validation,
        "reference_available": state.reference_available,
        "reference_state_entity_id": state.reference_state_entity_id,
        "reference_power_entity_id": state.reference_power_entity_id,
        "reference_measured_power_w": state.reference_measured_power_w,
        "reference_source_entity_id": state.reference_source_entity_id,
        "reference_fallback_to_nilm": state.reference_fallback_to_nilm,
    }


def _nilm_virtual_appliance_state(
    coordinator: Any,
    circuit_id: str,
    assignment: Mapping[str, Any],
    edges: list[NilmEdge],
    circuit_sessions: Iterable[NilmSession],
) -> NilmVirtualApplianceState | None:
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    fingerprints = [
        str(value or "").strip()
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    ]
    component_eligible = not fingerprints or any(
        map(nilm_signature_is_assignable, fingerprints)
    )
    if not assignment_id:
        return None
    derived_sessions = [
        session
        for session in circuit_sessions
        if session.assignment_id == assignment_id and not session.ambiguous
    ] if component_eligible else []
    session_payloads = _merged_assignment_session_payloads(
        coordinator,
        circuit_id,
        assignment,
        derived_sessions,
    )
    now = _nilm_now(coordinator, edges, derived_sessions, session_payloads)
    time_zone = _nilm_time_zone(coordinator)
    session_summary = summarize_nilm_assignment_sessions(
        assignment,
        [session for session in session_payloads if session.get("end")],
        now=now,
        time_zone=time_zone,
    )
    identity = build_nilm_appliance_identity(
        assignment,
        mains_source_entity_id=_mains_source_entity_id(coordinator, circuit_id),
        configured_circuit_names=(
            getattr(config, "name", "")
            for config in getattr(coordinator, "circuit_configs", ()) or ()
        ),
    )
    runtime, reconciliation = nilm_live_runtime(coordinator, circuit_id, assignment_id)
    live_available = component_eligible and nilm_runtime_available(
        runtime, reconciliation
    )
    reference = nilm_reference_runtime(coordinator, assignment)
    is_running = (
        reference["is_running"]
        if reference["available"]
        else runtime.get("status") == "on"
        if live_available
        else None
    )
    live_power = (
        round(_clamped_float(runtime.get("estimated_power_w")), 3)
        if live_available
        else None
    )
    rejected_session_ids = {
        str(value or "").strip()
        for value in _iter_items(assignment.get("rejected_session_ids"))
        if str(value or "").strip()
    }
    latest_session = _latest_session_payload(
        [
            session
            for session in session_summary["sessions"]
            if str(session.get("session_id") or "").strip() not in rejected_session_ids
        ]
    )
    return NilmVirtualApplianceState(
        appliance_id=identity.appliance_id,
        assignment_id=assignment_id,
        display_name=identity.display_name,
        is_running=is_running,
        estimated_power_w=live_power,
        estimated_energy_kwh_today=round(
            session_summary["estimated_energy_today_kwh"]
            + (_clamped_float(runtime.get("energy_kwh")) if live_available else 0.0),
            6,
        ),
        confidence=_clamped_float(assignment.get("confidence"), upper=1.0),
        last_seen=_session_payload_seen(latest_session),
        active_signature_id=(
            str(runtime.get("signature_fingerprint") or "") or None
            if live_available
            else None
        ),
        active_session_id=(
            str(runtime.get("session_id") or "") or None if live_available else None
        ),
        latest_session_id=(
            str(latest_session.get("session_id") or "") or None
            if latest_session
            else None
        ),
        model_status=nilm_model_status(assignment, reconciliation),
        mains_circuit_id=identity.mains_circuit_id or circuit_id,
        mains_source=identity.mains_source_entity_id,
        entry_id=str(getattr(coordinator, "entry_id", "") or ""),
        appliance_profile=identity.appliance_profile,
        last_validation=(
            str(assignment.get("last_validation"))
            if assignment.get("last_validation")
            else None
        ),
        appliance_key=identity.appliance_key,
        sessions=tuple(session_summary["sessions"]),
        runtime_today_seconds=session_summary["runtime_today_seconds"],
        run_count_today=session_summary["run_count_today"],
        current_session_duration_seconds=(
            _runtime_duration_seconds(runtime, now) if is_running else None
        ),
        current_session_id=(
            str(runtime.get("session_id") or "") or None if live_available else None
        ),
        last_matched_session_id=session_summary["last_matched_session_id"],
        latest_signature_id=(
            str(latest_session.get("signature_fingerprint") or "") or None
            if latest_session
            else None
        ),
        validation_readiness=evaluate_nilm_validation_readiness(
            assignment,
            session_summary["sessions"],
            min_confirmed_sessions=3,
            min_distinct_days=3,
            max_false_positive_rate=0.2,
            min_confidence=NILM_FINISHED_CONFIDENCE_THRESHOLD,
            time_zone=time_zone,
        ),
        confirmed_session_ids=frozenset(
            str(value or "").strip()
            for value in _iter_items(assignment.get("confirmed_session_ids"))
            if str(value or "").strip()
        ),
        rejected_session_ids=frozenset(rejected_session_ids),
        adjusted_session_ids=frozenset(
            str(value or "").strip()
            for value in _iter_items(assignment.get("adjusted_session_ids"))
            if str(value or "").strip()
        ),
        reference_time=now,
        time_zone=time_zone,
        reference_available=bool(reference["available"]),
        reference_state_entity_id=(
            str(assignment.get("reference_state_entity_id") or "") or None
        ),
        reference_power_entity_id=(
            str(assignment.get("reference_power_entity_id") or "") or None
        ),
        reference_measured_power_w=reference["measured_power_w"],
        reference_source_entity_id=reference["source_entity_id"],
        reference_fallback_to_nilm=bool(reference["fallback_to_nilm"]),
    )


def nilm_reference_runtime(
    coordinator: Any,
    assignment: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve authoritative reference state without replacing NILM power."""
    fallback = {
        "available": False,
        "is_running": None,
        "measured_power_w": None,
        "source_entity_id": None,
        "fallback_to_nilm": True,
        "state_mode": "unavailable",
    }
    if str(assignment.get("lifecycle_state") or "").strip().lower() == "retired":
        return fallback
    state_entity_id = str(
        assignment.get("reference_state_entity_id") or ""
    ).strip()
    power_entity_id = str(
        assignment.get("reference_power_entity_id") or ""
    ).strip()
    if not state_entity_id and not power_entity_id:
        return fallback
    states = getattr(getattr(coordinator, "hass", None), "states", None)
    get_state = getattr(states, "get", None)
    if not callable(get_state):
        return fallback

    measured_power_w = _nilm_reference_power_w(
        get_state(power_entity_id) if power_entity_id else None,
        power_entity_id,
    )
    if state_entity_id:
        row = get_state(state_entity_id)
        state = str(getattr(row, "state", "") or "").strip().lower()
        if state_entity_id.partition(".")[0] in {
            "switch",
            "binary_sensor",
            "input_boolean",
        } and state in {"on", "off"}:
            return {
                "available": True,
                "is_running": state == "on",
                "measured_power_w": measured_power_w,
                "source_entity_id": state_entity_id,
                "fallback_to_nilm": False,
                "state_mode": "binary_state",
            }
        return {**fallback, "measured_power_w": measured_power_w}
    if measured_power_w is None:
        return fallback
    threshold_w = _optional_nonnegative_float(
        assignment.get("reference_on_threshold")
    )
    if threshold_w is None:
        threshold_w = _optional_nonnegative_float(
            assignment.get("reference_threshold_w")
        )
    return {
        "available": True,
        "is_running": measured_power_w > (threshold_w or 0.0),
        "measured_power_w": measured_power_w,
        "source_entity_id": power_entity_id,
        "fallback_to_nilm": False,
        # This is only a current-value display; historical interval extraction
        # remains responsible for hysteresis and dwell handling.
        "state_mode": "stateless_numeric",
    }


def _nilm_reference_power_w(state: Any, entity_id: str) -> float | None:
    if state is None or entity_id.partition(".")[0] != "sensor":
        return None
    attributes = getattr(state, "attributes", {})
    if not isinstance(attributes, Mapping):
        return None
    unit = str(attributes.get("unit_of_measurement") or "").strip()
    device_class = str(attributes.get("device_class") or "").strip()
    if sensor_metadata_role_conflict(device_class=device_class, unit=unit):
        return None
    if (
        sensor_role_from_metadata(device_class=device_class, unit=unit)
        is not SensorRole.REAL_POWER
    ):
        return None
    try:
        value = float(getattr(state, "state", None))
    except (TypeError, ValueError):
        return None
    if not isfinite(value):
        return None
    factor = {"W": 1.0, "kW": 1_000.0, "mW": 0.001, "MW": 1_000_000.0}.get(
        unit
    )
    if factor is None:
        return None
    return round(max(value * factor, 0.0), 3)


def nilm_live_runtime(
    coordinator: Any, circuit_id: str, assignment_id: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    state = getattr(coordinator, "data", None) or getattr(coordinator, "state", None)
    runtime_by_circuit = getattr(state, "nilm_component_runtime_by_circuit", {})
    reconciliation_by_circuit = getattr(state, "nilm_reconciliation_by_circuit", {})
    circuit_runtime = _mapping_item(runtime_by_circuit, circuit_id)
    return _mapping_item(circuit_runtime, assignment_id), _mapping_item(
        reconciliation_by_circuit, circuit_id
    )


def nilm_model_status(
    assignment: Mapping[str, Any], reconciliation: Mapping[str, Any]
) -> str:
    lifecycle_state = str(assignment.get("lifecycle_state") or "candidate")
    if lifecycle_state == "conflict" or reconciliation.get("conflict"):
        return "conflict"
    if any(
        isinstance(link, Mapping) and link.get("status") == "degraded"
        for link in _iter_items(assignment.get("helper_links"))
    ):
        return "degraded"
    return lifecycle_state


def nilm_runtime_available(
    runtime: Mapping[str, Any], reconciliation: Mapping[str, Any]
) -> bool:
    """Return whether current component state is safe to expose live."""
    return bool(
        runtime
        and runtime.get("consistent") is True
        and reconciliation
        and reconciliation.get("consistent") is True
        and not reconciliation.get("conflict")
        and runtime.get("status") in {"on", "off"}
        and _optional_nonnegative_float(runtime.get("estimated_power_w")) is not None
        and (
            "energy_kwh" not in runtime
            or _optional_nonnegative_float(runtime.get("energy_kwh")) is not None
        )
        and (runtime.get("status") == "off" or _runtime_start(runtime) is not None)
    )


def _mapping_item(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    item = value.get(key)
    return item if isinstance(item, Mapping) else {}


def _runtime_start(runtime: Mapping[str, Any]) -> datetime | None:
    try:
        started = datetime.fromisoformat(str(runtime.get("session_start")))
    except (TypeError, ValueError):
        return None
    return started if started.tzinfo is not None else None


def _runtime_duration_seconds(
    runtime: Mapping[str, Any], now: datetime
) -> float | None:
    started = _runtime_start(runtime)
    return max((now - started).total_seconds(), 0.0) if started else None


def _merged_assignment_session_payloads(
    coordinator: Any,
    circuit_id: str,
    assignment: Mapping[str, Any],
    derived_sessions: Iterable[NilmSession],
) -> list[dict[str, Any]]:
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    fingerprints = [
        str(value or "").strip()
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    ]
    component_eligible = not fingerprints or any(
        map(nilm_signature_is_assignable, fingerprints)
    )
    session_ids = {
        str(value or "").strip()
        for value in _iter_items(assignment.get("session_ids"))
        if str(value or "").strip()
    }
    confirmed_session_ids = {
        str(value or "").strip()
        for value in _iter_items(assignment.get("confirmed_session_ids"))
        if str(value or "").strip()
    }
    rejected_session_ids = {
        str(value or "").strip()
        for value in _iter_items(assignment.get("rejected_session_ids"))
        if str(value or "").strip()
    }
    store_data = getattr(coordinator, "store_data", None)
    histories = getattr(store_data, "nilm_session_history_by_circuit", {})
    stored = histories.get(circuit_id, ()) if isinstance(histories, Mapping) else ()
    merged: dict[str, dict[str, Any]] = {}
    for session in _iter_items(stored):
        if not isinstance(session, Mapping) or bool(session.get("ambiguous")):
            continue
        session_fingerprint = str(
            session.get("signature_fingerprint") or ""
        ).strip()
        session_id = str(session.get("session_id") or "").strip()
        owner = str(session.get("assignment_id") or "").strip()
        if not session_id:
            continue
        explicitly_linked = session_id in session_ids
        confirmed_linked = session_id in confirmed_session_ids
        rejected_linked = session_id in rejected_session_ids
        if not component_eligible and (
            (not confirmed_linked and not rejected_linked) or not session.get("end")
        ):
            continue
        if owner and owner != assignment_id:
            continue
        if not owner and not explicitly_linked:
            continue
        if (
            session_fingerprint
            and not nilm_signature_is_assignable(session_fingerprint)
            and not confirmed_linked
            and not rejected_linked
        ):
            continue
        merged[session_id] = dict(session)
    owned_starts = {str(session.get("start") or "") for session in merged.values()}
    for session in derived_sessions:
        if session.ambiguous:
            continue
        if session.start.isoformat() not in owned_starts:
            merged.setdefault(session.session_id, nilm_session_to_dict(session))
    return sorted(
        merged.values(),
        key=lambda session: str(session.get("start") or ""),
    )


def _latest_session_payload(
    sessions: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    return max(
        sessions,
        key=lambda session: (
            _session_payload_seen(session) or datetime.min.replace(tzinfo=UTC)
        ),
        default=None,
    )


def _session_payload_seen(session: Mapping[str, Any] | None) -> datetime | None:
    if session is None:
        return None
    for value in (session.get("end"), session.get("start")):
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _nilm_now(
    coordinator: Any,
    edges: Iterable[NilmEdge],
    sessions: Iterable[NilmSession],
    payloads: Iterable[Mapping[str, Any]],
) -> datetime:
    current_time = getattr(coordinator, "current_time", None)
    if callable(current_time):
        value = current_time()
        if isinstance(value, datetime):
            return value
    values = [edge.timestamp for edge in edges]
    values.extend(
        seen
        for session in sessions
        if (seen := _nilm_session_seen(session)) is not None
    )
    values.extend(
        seen
        for payload in payloads
        if (seen := _session_payload_seen(payload)) is not None
    )
    return max(values, default=datetime.now().astimezone())


def _nilm_time_zone(coordinator: Any) -> str:
    hass = getattr(coordinator, "hass", None)
    config = getattr(hass, "config", None)
    return str(getattr(config, "time_zone", "UTC") or "UTC")


def _published_assignment(assignment: Mapping[str, Any]) -> bool:
    return assignment.get("publish_entities") is True and _matching_assignment(
        assignment
    )


def _matching_assignment(assignment: Mapping[str, Any]) -> bool:
    return str(assignment.get("lifecycle_state") or "") not in {
        "ignored",
        "retired",
    }


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
        "Estimated from aggregate circuit power by NILM. "
        f"Confidence: {round(confidence * 100)}%."
    )


def _nilm_finished_message(state: Any, *, confidence: float) -> str:
    """Describe the completed estimated on/off run in a user-facing alert."""
    return (
        f"{getattr(state, 'display_name', 'NILM appliance')}: "
        "a detected estimated run ended. NILM matched a completed on/off run "
        "from aggregate circuit power. "
        f"Confidence: {round(confidence * 100)}%."
    )


def _nilm_alert_features(
    state: Any,
    notification_type: str,
    notification_key: str,
    *,
    confidence: float,
) -> dict[str, Any]:
    assignment_id = str(getattr(state, "assignment_id", "") or "")
    appliance_key = (
        str(getattr(state, "appliance_key", "") or "") or f"nilm:{assignment_id}"
    )
    mains_circuit_id = str(getattr(state, "mains_circuit_id", "") or "")
    entry_id = str(getattr(state, "entry_id", "") or "")
    session_id = str(
        getattr(state, "active_session_id", "")
        or getattr(state, "latest_session_id", "")
        or ""
    )
    signature_fingerprint = str(
        getattr(state, "active_signature_id", "")
        or getattr(state, "latest_signature_id", "")
        or ""
    )
    identity = build_nilm_appliance_identity(
        {
            "assignment_id": assignment_id,
            "appliance_id": str(getattr(state, "appliance_id", "") or ""),
            "display_name": str(getattr(state, "display_name", "") or ""),
            "mains_circuit_id": mains_circuit_id,
            "appliance_profile": str(
                getattr(state, "appliance_profile", "") or "nilm_virtual"
            ),
        },
        mains_source_entity_id=getattr(state, "mains_source", None),
    )
    routing = build_nilm_appliance_alert_payload(
        identity,
        session_id=session_id or None,
        signature_fingerprint=signature_fingerprint or None,
    )
    return {
        "source": "nilm",
        "source_type": "nilm_estimate",
        "estimated": True,
        "confidence": confidence,
        "primary_target": appliance_key,
        "appliance_key": appliance_key,
        "assignment_id": assignment_id,
        "appliance_id": str(getattr(state, "appliance_id", "") or ""),
        "display_name": str(getattr(state, "display_name", "") or ""),
        "mains_circuit_id": mains_circuit_id,
        **({"entry_id": entry_id} if entry_id else {}),
        "mains_source_entity_id": getattr(state, "mains_source", None),
        "session_id": session_id or None,
        "signature_fingerprint": signature_fingerprint or None,
        **routing,
        "notification_type": notification_type,
        "notification_key": notification_key,
    }


def _nilm_assignment_sessions(
    circuit_id: str,
    assignments: Iterable[Mapping[str, Any]],
    edges: list[NilmEdge],
    signatures_by_id: Mapping[str, Mapping[str, Any]],
) -> list[NilmSession]:
    specs: list[dict[str, Any]] = []
    unique_signatures = {
        id(value): value for value in signatures_by_id.values()
    }
    signatures = list(unique_signatures.values())
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip() or None
        for value in _iter_items(assignment.get("signature_fingerprints")):
            fingerprint = str(value or "").strip()
            if not fingerprint:
                continue
            resolved = resolve_nilm_signature_fingerprint(fingerprint, signatures)
            signature = signatures_by_id.get(resolved or fingerprint)
            if not signature:
                continue
            spec = dict(signature)
            spec["signature_fingerprint"] = resolved or fingerprint
            spec["assignment_id"] = assignment_id
            for key in ("min_duration_seconds", "max_duration_seconds"):
                if key in assignment:
                    spec[key] = assignment[key]
            specs.append(spec)
    return pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id=circuit_id,
        signature_specs=specs,
    )


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


def _nilm_edges_for_circuit(coordinator: Any, circuit_id: str) -> list[NilmEdge]:
    edges_by_circuit = getattr(coordinator, "_nilm_unmatched_edges", {})
    if not isinstance(edges_by_circuit, Mapping):
        return []
    return [
        edge
        for edge in _iter_items(edges_by_circuit.get(circuit_id, ()))
        if isinstance(edge, NilmEdge)
    ]


def _nilm_session_seen(session: NilmSession | None) -> datetime | None:
    if session is None:
        return None
    return session.end or session.start


def _mains_source_entity_id(coordinator: Any, circuit_id: str) -> str | None:
    states = getattr(getattr(coordinator, "hass", None), "states", None)
    get_state = getattr(states, "get", None)
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if str(getattr(config, "circuit_id", "")) != circuit_id:
            continue
        for sensor in getattr(config, "sensors", ()) or ():
            role = getattr(sensor, "role", None)
            try:
                sensor_role = role if isinstance(role, SensorRole) else SensorRole(role)
            except (TypeError, ValueError):
                continue
            entity_id = str(getattr(sensor, "entity_id", "") or "")
            source = get_state(entity_id) if callable(get_state) and entity_id else None
            attributes = getattr(source, "attributes", None)
            attributes = attributes if isinstance(attributes, Mapping) else {}
            device_class = attributes.get("device_class")
            unit = attributes.get("unit_of_measurement")
            if sensor_metadata_is_unsupported(
                device_class=device_class, unit=unit
            ) or sensor_metadata_role_conflict(device_class=device_class, unit=unit):
                continue
            effective_role = (
                sensor_role_from_metadata(
                    device_class=device_class,
                    unit=unit,
                )
                or sensor_role
            )
            if effective_role is SensorRole.REAL_POWER:
                return entity_id or None
    return None


def _clamped_float(value: Any, *, upper: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(number):
        return 0.0
    if number < 0:
        return 0.0
    if upper is not None:
        return min(number, upper)
    return number


def _optional_nonnegative_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0 else None


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
