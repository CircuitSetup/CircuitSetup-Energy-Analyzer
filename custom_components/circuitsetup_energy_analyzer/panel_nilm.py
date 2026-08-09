"""NILM panel payload builders and bounded workspace contracts."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from statistics import fmean, median
from typing import Any
from urllib.parse import quote, urlencode

from .const import DOMAIN
from .discovery import sensor_metadata_role_conflict, sensor_role_from_metadata
from .entity import _entity_registry_for_hass
from .managers.nilm_controller import (
    configured_primary_assignment_id,
    nilm_assignment_is_active,
    nilm_assignment_publication_reason,
)
from .managers.source_samples import normalized_leg
from .models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    NilmSourceKind,
    SensorRole,
)
from .nilm import (
    NilmEdge,
    NilmSession,
    nilm_display_name,
    nilm_session_to_dict,
    nilm_signature_is_assignable,
    pair_nilm_sessions_for_signatures,
    resolve_nilm_signature_fingerprint,
)
from .nilm_virtual import (
    nilm_live_runtime,
    nilm_model_status,
    nilm_reference_runtime,
    nilm_runtime_available,
)
from .panel_common import (
    _circuit_payload,
    _datetime_from_iso,
    _iter_items,
    _panel_text,
)
from .panel_contracts import (
    APPLIANCE_DETAIL_API_PATH,
    NILM_WORKSPACE_API_PATH,
    NILM_WORKSPACE_HISTORY_API_PATH,
    PANEL_URL_PATH,
)
from .profiles import nilm_source_kind
from .services import (
    ATTR_APPLIANCE_PROFILE,
    ATTR_ASSIGNMENT_ID,
    ATTR_CIRCUIT_ID,
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_GROUND_TRUTH_ENTITY_ID,
    ATTR_HELPER_CIRCUIT_ID,
    ATTR_INTERVAL_ID,
    ATTR_INTERVALS,
    ATTR_LABEL,
    ATTR_MAINS_ENTITY_ID,
    ATTR_PRESET,
    ATTR_REFERENCE_POWER_ENTITY_ID,
    ATTR_RELATIONSHIP,
    ATTR_SESSION_ID,
    ATTR_SIGNATURE_FINGERPRINT,
    ATTR_SIGNATURE_ID,
    ATTR_SOURCE_ASSIGNMENT_ID,
    ATTR_START,
    ATTR_TARGET_ASSIGNMENT_ID,
    ATTR_THRESHOLD_W,
    SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
    SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
    SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
    SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
    SERVICE_CONFIRM_NILM_CONFIGURED_PRIMARY,
    SERVICE_DELETE_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_DELETE_NILM_LABEL_INTERVAL,
    SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
    SERVICE_IGNORE_NILM_SIGNATURE,
    SERVICE_LABEL_NILM_SIGNATURE,
    SERVICE_MERGE_NILM_ASSIGNMENTS,
    SERVICE_MERGE_NILM_SIGNATURES,
    SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_REJECT_NILM_SESSION,
    SERVICE_REMOVE_NILM_HELPER_LINK,
    SERVICE_REMOVE_NILM_REFERENCE_LINK,
    SERVICE_RENAME_NILM_APPLIANCE,
    SERVICE_RESTORE_NILM_ITEM,
    SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_SAVE_NILM_INTERVAL_CHANGES,
    SERVICE_SET_CIRCUIT_SENSITIVITY,
    SERVICE_SET_NILM_HELPER_LINK,
    SERVICE_SET_NILM_REFERENCE_LINK,
    SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
    SERVICE_VALIDATE_NILM_SESSION,
)
from .unknown_loads import MIN_CONFIDENCE, MIN_OCCURRENCES
from .ux import friendly_feature_name

MAX_NILM_PANEL_SIGNATURES = 5
MAX_NILM_MERGE_TARGET_OPTIONS = 5
NILM_SIGNATURE_PANEL_FIELDS = (
    ATTR_SIGNATURE_ID,
    "display_name",
    "user_label",
    "likely_type",
    "classification",
    "typical_watts",
    "typical_var",
    "typical_va",
    "typical_power_factor",
    "median_delta_w",
    "median_delta_var",
    "median_delta_va",
    "median_delta_pf",
    "typical_duration_seconds",
    "seen_count",
    "occurrence_count",
    "confidence",
    "first_seen",
    "last_seen",
    "voltage_class",
    "dominant_leg",
    "known_load_overlap",
    "running_state",
    "current_runtime_minutes",
    "estimated_energy_today_kwh",
    "runtime_7_days_minutes",
    "runtime_30_days_minutes",
    "estimated_energy_7_days_kwh",
    "estimated_energy_30_days_kwh",
    "runtime_windows",
    "estimate_status",
    "estimate_status_by_window",
    "observation_started_at",
    "runtime_window_definition",
    "energy_estimate_confidence",
    "review_state",
    "ignored",
    "merged_into",
    "fingerprint",
    "feedback_fingerprint",
    "signature_fingerprint",
    "helper_candidates",
    "direction",
    "component_id",
    "matched_assignment_id",
    "session_ids",
    "latest_session",
    "electrical_class",
    "electrical_class_confidence",
)
DEFAULT_NILM_WORKSPACE_HISTORY_HOURS = 6.0
MAX_NILM_WORKSPACE_HISTORY_HOURS = 24.0
MAX_NILM_WORKSPACE_HISTORY_ENTITIES = 8
MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY = 2160
MAX_NILM_WORKSPACE_KNOWN_LOADS = 8
MAX_NILM_WORKSPACE_EDGES = 40
MAX_NILM_WORKSPACE_SESSIONS = 20
MAX_NILM_WORKSPACE_LABEL_INTERVALS = 40


def nilm_workspace_payload(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None = None,
    hours: Any = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return bounded NILM workspace data for one Load Separation source."""

    target = _nilm_workspace_target(
        tuple(coordinators),
        circuit_id,
        entry_id=entry_id,
    )
    if target is None:
        return {
            "status": "not_found",
            "requested_circuit_id": circuit_id or None,
            "message": _panel_text("nilm_workspace", "no_source"),
        }

    coordinator, config, sources = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    edges = _nilm_edges_for_circuit(coordinator, config.circuit_id)
    recent_edges = sorted(edges, key=lambda edge: edge.timestamp)[
        -MAX_NILM_WORKSPACE_EDGES:
    ]
    signatures = _nilm_workspace_signatures(
        coordinator,
        config.circuit_id,
        config=config,
    )
    known_load_overlays = _nilm_known_load_overlays(
        coordinator,
        config.circuit_id,
    )
    solar_overlays = _nilm_solar_overlays(coordinator, config.circuit_id)
    all_label_intervals = _nilm_label_intervals_for_circuit(
        coordinator,
        config.circuit_id,
        limit=None,
    )
    label_intervals = all_label_intervals[:MAX_NILM_WORKSPACE_LABEL_INTERVALS]
    assignments = _nilm_assignments_for_circuit(
        coordinator,
        config.circuit_id,
        label_intervals=all_label_intervals,
    )
    _add_nilm_helper_evidence(
        assignments,
        signatures,
        config.circuit_id,
        coordinator=coordinator,
        config=config,
    )
    _add_nilm_reference_evidence(
        assignments,
        config.circuit_id,
        coordinator=coordinator,
    )
    assignment_options = _nilm_assignment_options(assignments, config=config)
    session_display_labels = _nilm_session_display_labels(signatures, assignments)
    reviewed_session_ids = _nilm_reviewed_session_ids_by_assignment(assignments)
    stored_sessions = _nilm_session_history_for_circuit(
        coordinator,
        config.circuit_id,
        reviewed_session_ids=reviewed_session_ids,
    )
    all_generated_sessions = _nilm_workspace_sessions(
        edges,
        config.circuit_id,
        signatures=signatures,
        assignments=assignments,
        reviewed_session_ids=reviewed_session_ids,
        limit=None,
    )
    all_sessions = _nilm_workspace_visible_sessions(
        _merge_nilm_session_payloads(all_generated_sessions, stored_sessions),
        signatures,
        assignments,
    )
    all_sessions = _add_nilm_session_display_labels(
        all_sessions,
        session_display_labels,
    )
    _add_nilm_component_occurrences(signatures, all_sessions)
    sessions = _add_nilm_session_display_labels(
        _nilm_workspace_visible_sessions(
            _merge_nilm_session_payloads(
                _nilm_workspace_sessions(
                    recent_edges,
                    config.circuit_id,
                    signatures=signatures,
                    assignments=assignments,
                    reviewed_session_ids=reviewed_session_ids,
                ),
                stored_sessions,
            ),
            signatures,
            assignments,
        ),
        session_display_labels,
    )[:MAX_NILM_WORKSPACE_SESSIONS]
    _add_nilm_assignment_options(signatures, assignment_options)
    _add_nilm_assignment_options(label_intervals, assignment_options)
    _add_nilm_assignment_options(sessions, assignment_options)
    _add_nilm_session_signature_reviews(sessions, signatures)
    virtual_appliances = _nilm_virtual_appliances_for_assignments(
        assignments,
        sessions,
        edges,
        coordinator=coordinator,
    )
    validation = _nilm_validation_payload(
        all_label_intervals,
        all_sessions,
        assignments,
    )
    lanes = _nilm_workspace_lanes(signatures, assignments, label_intervals, sessions)
    configured_primary = _nilm_configured_primary_payload(
        config,
        signatures,
        assignments,
        label_intervals=all_label_intervals,
        sessions=all_sessions,
    )
    payload = {
        "status": "ok",
        "circuit": _circuit_payload(config),
        "reconciliation": _nilm_reconciliation_payload(coordinator, config.circuit_id),
        "source": _nilm_workspace_source(coordinator, config, include_path=False),
        "sensitivity": _nilm_workspace_sensitivity(
            coordinator, config.circuit_id, all_label_intervals
        ),
        "sources": sources,
        "history": _nilm_workspace_history_payload(
            config,
            known_load_overlays,
            solar_overlays,
            hours=hours,
            entry_id=selected_entry_id,
            hass=getattr(coordinator, "hass", None),
        ),
        "known_load_overlays": known_load_overlays,
        "solar_overlays": solar_overlays,
        "signatures": signatures,
        "signature_count": len(signatures),
        "label_intervals": label_intervals,
        "label_interval_count": len(label_intervals),
        "assignments": assignments,
        "assignment_count": len(assignments),
        "virtual_appliances": virtual_appliances,
        "virtual_appliance_count": len(virtual_appliances),
        "validation": validation,
        "lanes": lanes,
        "lane_counts": {
            key: sum(
                len(value[item_key])
                for item_key in (
                    "assignment_ids",
                    "signature_ids",
                    "interval_ids",
                    "session_ids",
                )
            )
            for key, value in lanes.items()
        },
        "selection_guidance": _nilm_selection_guidance(),
        "actions": {
            "label_interval": _nilm_label_interval_action(
                config, assignment_options
            ),
        },
        "edges": [_nilm_edge_payload(edge) for edge in recent_edges],
        "edge_count": len(edges),
        "sessions": sessions,
        "session_count": len(all_sessions),
    }
    if configured_primary is not None:
        payload["configured_primary"] = configured_primary
    return _scope_nilm_actions(payload, selected_entry_id)


def _nilm_workspace_sensitivity(
    coordinator: Any,
    circuit_id: str,
    label_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = getattr(coordinator, "settings_controller", None)
    if settings is None:
        current = "balanced"
        threshold = 100.0
    else:
        current = settings.sensitivity_for_circuit(circuit_id)
        threshold = settings.nilm_min_delta_w(circuit_id)
    recommendation = _nilm_sensitivity_recommendation(
        current, threshold, label_intervals
    )
    action = {
        "domain": DOMAIN,
        "service": SERVICE_SET_CIRCUIT_SENSITIVITY,
        "data": {ATTR_CIRCUIT_ID: circuit_id},
    }
    if recommendation is not None:
        action["data"][ATTR_PRESET] = recommendation
    return {
        "current": current,
        "effective_minimum_edge_w": threshold,
        "recommendation": recommendation,
        "action": action,
    }


def _nilm_sensitivity_recommendation(
    current: str,
    threshold_w: float,
    intervals: list[dict[str, Any]],
) -> str | None:
    next_setting = {"quiet": "balanced", "balanced": "sensitive"}.get(current)
    if next_setting is None:
        return None
    grouped: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
    for interval in intervals:
        assignment = str(interval.get("assignment_id") or "").strip()
        label = str(interval.get("label") or "").strip().casefold()
        value = interval.get("observed_transition_w")
        if not assignment or not label or not isinstance(value, (int, float)):
            continue
        value = abs(float(value))
        if not math.isfinite(value):
            continue
        observed_at = _datetime_from_iso(
            interval.get("start") or interval.get("created_at")
        )
        if observed_at is None:
            continue
        grouped.setdefault((assignment, label), []).append((observed_at, value))
    for observations in grouped.values():
        recent = [value for _, value in sorted(observations)[-3:]]
        if len(recent) < 3:
            continue
        typical = median(recent)
        if 0.0 < typical < threshold_w and all(
            abs(value - typical) <= typical * 0.2 for value in recent
        ):
            return next_setting
    return None


def _nilm_payload_for_circuit(
    coordinator: Any,
    circuit_id: str | None,
    *,
    include_all_nilm: bool = False,
) -> dict[str, Any]:
    if not circuit_id:
        return {
            "signatures": [],
            "signature_count": 0,
            "signatures_has_more": False,
            "signatures_omitted_count": 0,
        }
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    preview_signatures = (
        signatures if include_all_nilm else signatures[:MAX_NILM_PANEL_SIGNATURES]
    )
    workspace_paths = _nilm_workspace_paths(coordinator, circuit_id)
    payload = {
        "signatures": [
            {
                **_nilm_signature_payload(signature),
                "display_label": _nilm_signature_label(
                    signature,
                    str(signature[ATTR_SIGNATURE_ID]),
                ),
                "actions": _nilm_actions_for_signature(
                    circuit_id,
                    str(signature[ATTR_SIGNATURE_ID]),
                    signatures,
                    include_all_nilm=include_all_nilm,
                    restorable=_nilm_signature_restorable(signature),
                ),
            }
            for signature in preview_signatures
            if signature.get(ATTR_SIGNATURE_ID)
        ],
        "signature_count": len(signatures),
        "signatures_has_more": len(signatures) > len(preview_signatures),
        "signatures_omitted_count": max(
            len(signatures) - len(preview_signatures),
            0,
        ),
        **workspace_paths,
    }
    return _scope_nilm_actions(
        payload,
        str(getattr(coordinator, "entry_id", "") or ""),
    )


def _scope_nilm_actions(payload: Any, entry_id: str) -> Any:
    """Add the selected entry to nested NILM service actions."""
    if not entry_id:
        return payload
    if isinstance(payload, dict):
        if (
            payload.get("domain") == DOMAIN
            and isinstance(payload.get("service"), str)
            and isinstance(payload.get("data"), dict)
        ):
            payload["data"].setdefault(ATTR_ENTRY_ID, entry_id)
        for value in payload.values():
            _scope_nilm_actions(value, entry_id)
    elif isinstance(payload, list):
        for value in payload:
            _scope_nilm_actions(value, entry_id)
    return payload


def _nilm_signatures_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    signatures_by_circuit = getattr(store_data, "nilm_signatures", {})
    stored_signatures = (
        [
            dict(item)
            for item in _iter_items(signatures_by_circuit.get(circuit_id, ()))
            if isinstance(item, dict)
        ]
        if isinstance(signatures_by_circuit, dict)
        else []
    )
    stored_by_id = {
        str(signature[ATTR_SIGNATURE_ID]): signature
        for signature in stored_signatures
        if signature.get(ATTR_SIGNATURE_ID)
    }

    state = getattr(coordinator, "state", None)
    inventory_by_circuit = getattr(state, "nilm_unknown_loads_by_circuit", {})
    inventory = (
        inventory_by_circuit.get(circuit_id)
        if isinstance(inventory_by_circuit, dict)
        else None
    )
    if isinstance(inventory, dict):
        unknown_loads = [
            dict(item)
            for item in _iter_items(inventory.get("unknown_loads", ()))
            if isinstance(item, dict)
        ]
        if unknown_loads:
            signatures: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for signature in unknown_loads:
                signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
                if signature_id:
                    seen_ids.add(signature_id)
                stored = stored_by_id.get(signature_id)
                signatures.append(
                    {**signature, **stored} if stored is not None else signature
                )
            signatures.extend(
                signature
                for signature in stored_signatures
                if str(signature.get(ATTR_SIGNATURE_ID) or "").strip() not in seen_ids
            )
            return signatures

    return stored_signatures


def _nilm_actions_for_signature(
    circuit_id: str,
    signature_id: str,
    signatures: list[dict[str, Any]],
    *,
    include_all_nilm: bool = False,
    restorable: bool = False,
) -> dict[str, dict[str, Any]]:
    data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_SIGNATURE_ID: signature_id}
    merge_target_options = _nilm_merge_target_options(signatures, signature_id)
    merge_target_preview = (
        merge_target_options
        if include_all_nilm
        else merge_target_options[:MAX_NILM_MERGE_TARGET_OPTIONS]
    )
    merge_action: dict[str, Any] = {
        "domain": DOMAIN,
        "service": SERVICE_MERGE_NILM_SIGNATURES,
        "data": {ATTR_CIRCUIT_ID: circuit_id, "source_signature_id": signature_id},
        "requires": ["target_signature_id"],
        "target_options": merge_target_preview,
        "target_option_count": len(merge_target_options),
        "target_options_has_more": len(merge_target_options)
        > len(merge_target_preview),
        "target_options_omitted_count": max(
            len(merge_target_options) - len(merge_target_preview),
            0,
        ),
    }
    if not merge_target_preview:
        merge_action.update(
            {
                "enabled": False,
                "unavailable_reason": "no_merge_target",
                "unavailable_label": _panel_text(
                    "nilm_workspace",
                    "no_merge_target_action",
                ),
            }
        )
    actions = {
        "label": {
            "domain": DOMAIN,
            "service": SERVICE_LABEL_NILM_SIGNATURE,
            "data": dict(data),
            "requires": [ATTR_LABEL],
        },
        "assign": {
            "domain": DOMAIN,
            "service": SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
            "data": dict(data),
            "requires": [ATTR_LABEL],
        },
        "ignore": {
            "domain": DOMAIN,
            "service": SERVICE_IGNORE_NILM_SIGNATURE,
            "data": dict(data),
        },
        "merge": merge_action,
    }
    if restorable:
        actions["restore"] = {
            "domain": DOMAIN,
            "service": SERVICE_RESTORE_NILM_ITEM,
            "data": dict(data),
        }
    return actions


def _nilm_merge_target_options(
    signatures: Iterable[dict[str, Any]],
    source_signature_id: str,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for signature in signatures:
        signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
        if not signature_id or signature_id == source_signature_id:
            continue
        options.append(
            {
                "value": signature_id,
                "label": _nilm_signature_label(signature, signature_id),
            }
        )
    return options


def _nilm_signature_payload(signature: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        key: signature[key] for key in NILM_SIGNATURE_PANEL_FIELDS if key in signature
    }
    payload["source_type"] = "nilm_estimate"
    payload["source_label"] = _panel_text("source_labels", "nilm_estimate")
    payload["direction"] = _nilm_signature_direction(signature)
    if "typical_watts" in signature:
        payload["typical_power_w"] = signature["typical_watts"]
    payload["why_grouped"] = _nilm_signature_explanation(signature)
    review_state = _nilm_review_state(signature)
    if review_state:
        payload["review_state"] = review_state
    return payload


def _add_nilm_component_occurrences(
    signatures: list[dict[str, Any]],
    sessions: Iterable[Mapping[str, Any]],
) -> None:
    candidates = [
        signature
        for signature in signatures
        if _nilm_signature_direction(signature) == "on"
    ]
    by_key = {
        key: signature
        for signature in candidates
        for key in _nilm_signature_lookup_keys(signature)
    }
    matched: dict[str, list[Mapping[str, Any]]] = {
        str(signature.get(ATTR_SIGNATURE_ID)): [] for signature in candidates
    }
    for session in sessions:
        if not session.get("end") or session.get("ambiguous"):
            continue
        fingerprint = str(session.get("signature_fingerprint") or "").strip()
        signature = by_key.get(fingerprint)
        if signature is None:
            compatible = [
                item
                for item in candidates
                if _nilm_session_signature_compatible(session, item)
            ]
            signature = compatible[0] if len(compatible) == 1 else None
        if signature is not None:
            matched[str(signature.get(ATTR_SIGNATURE_ID))].append(session)
    for signature in candidates:
        occurrences = matched[str(signature.get(ATTR_SIGNATURE_ID))]
        if not occurrences:
            continue
        occurrences.sort(
            key=lambda item: str(item.get("end") or item.get("start") or "")
        )
        latest = occurrences[-1]
        session_ids = [
            str(item.get("session_id"))
            for item in occurrences
            if item.get("session_id")
        ]
        durations = [
            float(item["duration_seconds"])
            for item in occurrences
            if isinstance(item.get("duration_seconds"), int | float)
        ]
        assignment_ids = {
            str(item.get(ATTR_ASSIGNMENT_ID) or "").strip()
            for item in occurrences
            if str(item.get(ATTR_ASSIGNMENT_ID) or "").strip()
        }
        signature["session_ids"] = session_ids
        signature["latest_session"] = {
            key: latest[key]
            for key in (
                "session_id",
                "start",
                "end",
                "duration_seconds",
                "median_power_w",
                "estimated_energy_kwh",
                "confidence",
                ATTR_ASSIGNMENT_ID,
            )
            if latest.get(key) is not None
        }
        if durations:
            signature["typical_duration_seconds"] = median(durations)
        if len(assignment_ids) == 1:
            assignment_id = next(iter(assignment_ids))
            signature["matched_assignment_id"] = assignment_id
            signature["component_id"] = assignment_id
        else:
            signature["component_id"] = _nilm_signature_session_fingerprint(signature)
        electrical_class = _nilm_signature_electrical_class(signature)
        if electrical_class != "unknown":
            signature["electrical_class"] = electrical_class
            signature["electrical_class_confidence"] = signature.get("confidence")


def _nilm_session_signature_compatible(
    session: Mapping[str, Any],
    signature: Mapping[str, Any],
) -> bool:
    observed_w = _clamped_float(session.get("on_delta_w"), default=0.0)
    expected_w = _clamped_float(
        signature.get("typical_watts") or signature.get("median_delta_w"),
        default=0.0,
    )
    if (
        not observed_w
        or not expected_w
        or abs(abs(observed_w) - abs(expected_w)) > max(50.0, abs(expected_w) * 0.25)
    ):
        return False
    observed_var = session.get("on_delta_var")
    expected_var = signature.get("typical_var") or signature.get("median_delta_var")
    return not (
        isinstance(observed_var, int | float)
        and isinstance(expected_var, int | float)
        and abs(abs(float(observed_var)) - abs(float(expected_var)))
        > max(75.0, abs(float(expected_var)) * 0.5)
    )


def _nilm_signature_electrical_class(signature: Mapping[str, Any]) -> str:
    value = str(
        signature.get("likely_type") or signature.get("classification") or ""
    ).lower()
    if "motor" in value:
        return "motor"
    if "resistive" in value or "heating_element" in value:
        return "resistive"
    if "power_electronics" in value or "power-electronics" in value:
        return "power_electronics"
    return "unknown"


def _nilm_signature_direction(signature: Mapping[str, Any]) -> str:
    explicit = str(signature.get("direction") or "").strip().lower()
    if explicit in {"on", "off"}:
        return explicit
    for value in _nilm_signature_lookup_keys(signature):
        for token in value.split("|"):
            if token in {"direction=on", "direction=off"}:
                return token.removeprefix("direction=")
        prefix = value.split("-", 1)[0].lower()
        if prefix in {"on", "off"}:
            return prefix
    return "unknown"


def _nilm_signature_explanation(signature: Mapping[str, Any]) -> str:
    typical_watts = _clamped_float(signature.get("typical_watts"), default=0.0)
    if typical_watts > 0:
        power = _format_power_label(typical_watts)
        return f"Grouped by similar NILM on/off edges around {power}."
    return "Grouped by similar NILM on/off edges from mains power."


def _nilm_review_state(signature: Mapping[str, Any]) -> str | None:
    review_state = str(signature.get("review_state") or "").strip()
    if review_state:
        return review_state
    if signature.get("ignored"):
        return "ignored"
    if signature.get("merged_into"):
        return "merged"
    if str(signature.get("user_label") or "").strip():
        return "labeled"
    return None


def _nilm_signature_restorable(signature: Mapping[str, Any]) -> bool:
    return _nilm_review_state(signature) in {"ignored", "merged"}


def _nilm_topology_capability(
    config: CircuitConfig | None,
) -> tuple[str, str | None]:
    if config is None:
        return "not_applicable", None
    try:
        mode = CircuitMode(config.mode)
    except (TypeError, ValueError):
        mode = None
    if mode is CircuitMode.SINGLE_PHASE:
        return "not_applicable", None
    legs = {
        normalized_leg(sensor.leg)
        for sensor in config.sensors
        if _nilm_real_power_sensor_series(sensor) is not None and sensor.leg
    }
    leg_a = "a" in legs
    leg_b = "b" in legs
    if not leg_a and not leg_b:
        if mode is CircuitMode.DUAL_PHASE:
            return (
                "unavailable",
                "Both leg real-power sensors are required for topology evidence.",
            )
        return "not_applicable", None
    if leg_a and leg_b:
        return "available", None
    return (
        "unavailable",
        "Both leg real-power sensors are required for topology evidence.",
    )


def _apply_nilm_topology_capability(
    payload: dict[str, Any],
    topology: tuple[str, str | None],
) -> dict[str, Any]:
    applicability, requirement = topology
    payload["topology_applicability"] = applicability
    if applicability != "available":
        payload.pop("voltage_class", None)
        payload.pop("dominant_leg", None)
    else:
        for key in ("voltage_class", "dominant_leg"):
            if str(payload.get(key) or "").strip().lower() == "unknown":
                payload.pop(key, None)
    if requirement:
        payload["topology_requirement"] = requirement
    return payload


def _nilm_signature_label(signature: Mapping[str, Any], fallback: str) -> str:
    label = (
        str(signature.get("user_label") or "").strip()
        or str(signature.get("display_name") or "").strip()
        or str(signature.get("likely_type") or "").strip()
        or fallback
    )
    parts = [label]
    typical_watts = signature.get("typical_watts")
    if isinstance(typical_watts, (int, float)) and typical_watts > 0:
        parts.append(_format_power_label(float(typical_watts)))
    confidence = signature.get("confidence")
    if isinstance(confidence, (int, float)):
        parts.append(f"confidence {round(float(confidence) * 100):.0f}%")
    first_seen = _format_first_seen_label(signature.get("first_seen"))
    if first_seen:
        parts.append(f"first seen {first_seen}")
    return ", ".join(parts)


def _nilm_workspace_target(
    coordinators: Iterable[Any],
    circuit_id: str | None,
    *,
    entry_id: str | None = None,
) -> tuple[Any, Any, list[dict[str, str]]] | None:
    requested_circuit_id = str(circuit_id or "").strip()
    requested_entry_id = str(entry_id or "").strip()
    for coordinator in coordinators:
        if (
            requested_entry_id
            and str(getattr(coordinator, "entry_id", "") or "") != requested_entry_id
        ):
            continue
        source_configs = _nilm_workspace_source_configs(coordinator)
        sources = [source for _config, source in source_configs]
        candidates = [
            config
            for config, source in source_configs
            if not requested_circuit_id or source["circuit_id"] == requested_circuit_id
        ]
        if candidates:
            return coordinator, candidates[0], sources
        if requested_entry_id:
            return None
    return None


def _nilm_workspace_source_configs(
    coordinator: Any,
) -> list[tuple[Any, dict[str, str]]]:
    sources: dict[str, tuple[Any, dict[str, str]]] = {}
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        kind = nilm_source_kind(config)
        if kind is None:
            continue
        circuit_id = str(getattr(config, "circuit_id", "") or "")
        if circuit_id not in sources or kind.value == "mains":
            sources[circuit_id] = (config, _nilm_workspace_source(coordinator, config))
    return list(sources.values())


def _nilm_workspace_source(
    coordinator: Any, config: Any, *, include_path: bool = True
) -> dict[str, str]:
    entry_id = str(getattr(coordinator, "entry_id", "") or "")
    circuit_id = str(getattr(config, "circuit_id", "") or "")
    source = {
        "entry_id": entry_id,
        "circuit_id": circuit_id,
        "name": str(getattr(config, "name", "") or circuit_id),
        "source_kind": str(nilm_source_kind(config).value),
    }
    if include_path:
        source["path"] = _nilm_workspace_path(entry_id, circuit_id)
    return source


def _nilm_workspace_path(entry_id: str, circuit_id: str) -> str:
    query = urlencode(
        {"nilm_workspace": "1", "entry_id": entry_id, "circuit_id": circuit_id}
    )
    return f"/{PANEL_URL_PATH}?{query}"


def _nilm_workspace_signatures(
    coordinator: Any,
    circuit_id: str,
    *,
    config: CircuitConfig | None = None,
) -> list[dict[str, Any]]:
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    topology = _nilm_topology_capability(config)
    return [
        _apply_nilm_topology_capability(
            {
                **_nilm_signature_payload(signature),
                "display_label": _nilm_signature_label(
                    signature,
                    str(signature[ATTR_SIGNATURE_ID]),
                ),
                "actions": _nilm_actions_for_signature(
                    circuit_id,
                    str(signature[ATTR_SIGNATURE_ID]),
                    signatures,
                    include_all_nilm=True,
                    restorable=_nilm_signature_restorable(signature),
                ),
            },
            topology,
        )
        for signature in signatures
        if signature.get(ATTR_SIGNATURE_ID)
    ]


def _nilm_label_intervals_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    limit: int | None = MAX_NILM_WORKSPACE_LABEL_INTERVALS,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    intervals_by_circuit = getattr(store_data, "nilm_label_intervals_by_circuit", {})
    intervals = (
        [
            dict(item)
            for item in _iter_items(intervals_by_circuit.get(circuit_id, ()))
            if isinstance(item, dict)
        ]
        if isinstance(intervals_by_circuit, Mapping)
        else []
    )
    payloads = [
        _nilm_label_interval_payload(circuit_id, interval) for interval in intervals
    ]
    return payloads if limit is None else payloads[:limit]


def _nilm_label_interval_payload(
    circuit_id: str,
    interval: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {str(key): value for key, value in interval.items() if key != "actions"}
    interval_id = str(payload.get(ATTR_INTERVAL_ID) or "").strip()
    if interval_id:
        payload["actions"] = {
            "delete": {
                "domain": DOMAIN,
                "service": SERVICE_DELETE_NILM_LABEL_INTERVAL,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_INTERVAL_ID: interval_id,
                },
            },
            "assign": {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_INTERVAL_ID: interval_id,
                },
                "requires": [ATTR_LABEL],
            },
        }
    return payload


def _nilm_label_interval_action(
    config: CircuitConfig,
    assignment_options: list[dict[str, str]],
) -> dict[str, Any]:
    data = {ATTR_CIRCUIT_ID: config.circuit_id}
    entity_ids = _sensor_entity_ids(config)
    if entity_ids:
        data[ATTR_MAINS_ENTITY_ID] = entity_ids[0]
    return {
        "domain": DOMAIN,
        "service": SERVICE_SAVE_NILM_INTERVAL_CHANGES,
        "data": data,
        "requires": [ATTR_LABEL, ATTR_INTERVALS],
        "profile_options": _nilm_appliance_profile_options(),
        "assignment_options": assignment_options,
    }


def _nilm_assignments_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return []
    assignments = [
        item
        for item in _iter_items(assignments_by_circuit.get(circuit_id, ()))
        if isinstance(item, dict)
    ]
    configured_circuit_names = tuple(
        config.name
        for config in getattr(coordinator, "circuit_configs", ()) or ()
        if isinstance(config, CircuitConfig)
    )
    return [
        _nilm_assignment_payload(
            circuit_id,
            item,
            assignments,
            entry_id=str(getattr(coordinator, "entry_id", "") or ""),
            label_intervals=label_intervals,
            configured_circuit_names=configured_circuit_names,
        )
        for item in assignments
    ]


def _nilm_assignment_options(
    assignments: Iterable[Mapping[str, Any]],
    *,
    config: CircuitConfig | None = None,
) -> list[dict[str, str]]:
    options = (
        [
            {
                "value": configured_primary_assignment_id(config.circuit_id),
                "label": f"Configured primary: {config.name}",
            }
        ]
        if config is not None
        and nilm_source_kind(config) is NilmSourceKind.PRIMARY_MIXED
        else []
    )
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id or not nilm_assignment_is_active(assignment):
            continue
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment_id,
        ).strip()
        if any(option["value"] == assignment_id for option in options):
            continue
        options.append({"value": assignment_id, "label": label})
    return options


def _nilm_configured_primary_payload(
    config: CircuitConfig,
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
    sessions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    if nilm_source_kind(config) is not NilmSourceKind.PRIMARY_MIXED:
        return None
    assignment_id = configured_primary_assignment_id(config.circuit_id)
    assignment = next(
        (item for item in assignments if item.get(ATTR_ASSIGNMENT_ID) == assignment_id),
        None,
    )
    current_binding = None
    current_signature = None
    current_identifiers: set[str] = set()
    if assignment is not None:
        for fingerprint in _iter_items(assignment.get("signature_fingerprints")):
            fingerprint_text = str(fingerprint or "").strip()
            if not fingerprint_text:
                continue
            if not nilm_signature_is_assignable(fingerprint_text):
                continue
            current_identifiers.add(fingerprint_text)
            signature = next(
                (
                    item
                    for item in signatures
                    if fingerprint_text in _nilm_signature_identifiers(item)
                ),
                None,
            )
            if (
                signature is not None
                and nilm_signature_is_assignable(
                    _nilm_signature_session_fingerprint(signature)
                )
                and current_binding is None
            ):
                current_signature = signature
                current_binding = {
                    ATTR_SIGNATURE_ID: signature[ATTR_SIGNATURE_ID],
                    "display_label": signature.get("display_label"),
                }
    if current_binding is None:
        signature = next(
            (
                item
                for item in signatures
                if str(item.get("assignment_id") or "").strip() == assignment_id
            ),
            None,
        )
        if signature is not None and nilm_signature_is_assignable(
            _nilm_signature_session_fingerprint(signature)
        ):
            current_signature = signature
            current_identifiers.update(_nilm_signature_identifiers(signature))
            current_binding = {
                ATTR_SIGNATURE_ID: signature[ATTR_SIGNATURE_ID],
                "display_label": signature.get("display_label"),
            }

    confirmed_interval_ids = {
        str(value or "").strip()
        for value in _iter_items((assignment or {}).get("label_interval_ids"))
        if str(value or "").strip()
    }
    confirmed_interval_count = sum(
        1
        for interval in label_intervals
        if isinstance(interval, Mapping)
        if str(interval.get(ATTR_ASSIGNMENT_ID) or "").strip() == assignment_id
        or str(interval.get(ATTR_INTERVAL_ID) or "").strip()
        in confirmed_interval_ids
    )
    signature_status: dict[str, Any] = {"status": "not_established"}
    attribution_count = 0
    if current_signature is not None:
        signature_identifiers = _nilm_signature_identifiers(current_signature)
        recurrence_count = int(
            _clamped_float(
                current_signature.get(
                    "occurrence_count",
                    current_signature.get("seen_count"),
                ),
                default=0.0,
            )
        )
        signature_status = {
            "status": "established",
            ATTR_SIGNATURE_ID: current_signature[ATTR_SIGNATURE_ID],
            "display_label": current_signature.get("display_label"),
            "recurrence_count": recurrence_count,
        }
        attribution_count = sum(
            1
            for session in sessions
            if isinstance(session, Mapping)
            if str(session.get(ATTR_ASSIGNMENT_ID) or "").strip() == assignment_id
            if str(session.get("signature_fingerprint") or "").strip()
            in signature_identifiers
        )

    competing = _nilm_assigned_signature_ids(
        item for item in assignments if item.get(ATTR_ASSIGNMENT_ID) != assignment_id
    )
    candidates = []
    for signature in signatures:
        identifiers = _nilm_signature_identifiers(signature)
        occurrences = int(
            _clamped_float(
                signature.get("occurrence_count", signature.get("seen_count")),
                default=0.0,
            )
        )
        confidence = _clamped_float(signature.get("confidence"), default=0.0)
        watts = abs(_clamped_float(signature.get("typical_watts"), default=0.0))
        if (
            not nilm_signature_is_assignable(
                _nilm_signature_session_fingerprint(signature)
            )
            or
            _nilm_review_state(signature) in {"ignored", "merged"}
            or identifiers & competing
            or identifiers & current_identifiers
            or occurrences < MIN_OCCURRENCES
            or confidence < MIN_CONFIDENCE
            or watts <= 0.0
        ):
            continue
        stable_id = str(signature.get(ATTR_SIGNATURE_ID) or "")
        candidates.append(
            (
                (-watts, -occurrences, -confidence, stable_id),
                signature,
                occurrences,
                confidence,
                watts,
            )
        )
    selected = min(
        candidates,
        default=None,
        key=lambda item: item[0],
    )
    if selected is not None and current_signature is not None:
        current_watts = abs(
            _clamped_float(current_signature.get("typical_watts"), default=0.0)
        )
        if selected[4] <= current_watts:
            selected = None
    suggestion = None
    if selected is not None:
        _rank, signature, occurrences, confidence, watts = selected
        suggestion = {
            ATTR_SIGNATURE_ID: signature[ATTR_SIGNATURE_ID],
            "display_label": signature.get("display_label"),
            "confidence": confidence,
            "evidence_summary": (
                f"{occurrences} recurring events around {watts:.0f} W "
                f"with {confidence:.0%} confidence."
            ),
            "action": {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
                "data": {
                    ATTR_CIRCUIT_ID: config.circuit_id,
                    ATTR_SIGNATURE_ID: signature[ATTR_SIGNATURE_ID],
                    ATTR_ASSIGNMENT_ID: assignment_id,
                    ATTR_LABEL: config.name,
                    ATTR_APPLIANCE_PROFILE: config.appliance_profile.value,
                },
            },
        }
    return {
        ATTR_ASSIGNMENT_ID: assignment_id,
        "display_name": config.name,
        ATTR_APPLIANCE_PROFILE: config.appliance_profile.value,
        "current_binding": current_binding,
        "evidence": {"confirmed_interval_count": confirmed_interval_count},
        "signature": signature_status,
        "attribution": {
            "status": "active" if current_binding is not None else "inactive",
            "matching_detection_count": attribution_count,
        },
        "suggestion": suggestion,
    }


def _add_nilm_helper_evidence(
    assignments: list[dict[str, Any]],
    signatures: list[dict[str, Any]],
    circuit_id: str,
    *,
    coordinator: Any,
    config: CircuitConfig,
) -> None:
    signatures_by_fingerprint = {
        str(signature.get(key) or "").strip(): signature
        for signature in signatures
        for key in ("fingerprint", "feedback_fingerprint", "signature_fingerprint")
        if signature.get(key)
    }
    helper_options_by_id = {
        option[ATTR_HELPER_CIRCUIT_ID]: option
        for option in _nilm_helper_options(coordinator, config)
    }
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        candidates = [
            dict(candidate)
            for fingerprint in assignment.get("signature_fingerprints", ())
            for candidate in signatures_by_fingerprint.get(str(fingerprint), {}).get(
                "helper_candidates", ()
            )
            if (
                isinstance(candidate, Mapping)
                and candidate.get("suggested") is True
                and candidate.get(ATTR_HELPER_CIRCUIT_ID) in helper_options_by_id
            )
        ]
        links = [
            dict(link)
            for link in assignment.get("helper_links", ())
            if isinstance(link, Mapping)
        ]
        for item in candidates:
            item["state"] = (
                "degraded"
                if item.get("degraded") or item.get("status") == "degraded"
                else "suggested"
                if item.get("suggested")
                else "available"
            )
            option = helper_options_by_id[item[ATTR_HELPER_CIRCUIT_ID]]
            item.setdefault("helper_name", option["helper_name"])
            item["actions"] = {
                "set": {
                    "domain": DOMAIN,
                    "service": SERVICE_SET_NILM_HELPER_LINK,
                    "data": {
                        ATTR_CIRCUIT_ID: circuit_id,
                        ATTR_ASSIGNMENT_ID: assignment_id,
                        ATTR_HELPER_CIRCUIT_ID: item[ATTR_HELPER_CIRCUIT_ID],
                        ATTR_RELATIONSHIP: "corroborates",
                    },
                }
            }
        for item in links:
            item["state"] = (
                "degraded"
                if item.get("degraded") or item.get("status") == "degraded"
                else "confirmed"
            )
            item["actions"] = {
                "remove": {
                    "domain": DOMAIN,
                    "service": SERVICE_REMOVE_NILM_HELPER_LINK,
                    "data": {
                        ATTR_CIRCUIT_ID: circuit_id,
                        ATTR_ASSIGNMENT_ID: assignment_id,
                        ATTR_HELPER_CIRCUIT_ID: item.get(ATTR_HELPER_CIRCUIT_ID),
                    },
                }
            }
        assignment["helper_candidates"] = candidates
        assignment["helper_links"] = links
        assignment["helper_options"] = [
            {
                **option,
                "actions": {
                    "set": {
                        "domain": DOMAIN,
                        "service": SERVICE_SET_NILM_HELPER_LINK,
                        "data": {
                            ATTR_CIRCUIT_ID: circuit_id,
                            ATTR_ASSIGNMENT_ID: assignment_id,
                            ATTR_HELPER_CIRCUIT_ID: option[ATTR_HELPER_CIRCUIT_ID],
                            ATTR_RELATIONSHIP: "corroborates",
                        },
                    }
                },
            }
            for option in helper_options_by_id.values()
        ]


def _nilm_helper_options(
    coordinator: Any,
    source_config: CircuitConfig,
) -> list[dict[str, Any]]:
    options = []
    for helper in getattr(coordinator, "circuit_configs", ()) or ():
        if (
            not isinstance(helper, CircuitConfig)
            or helper.circuit_id == source_config.circuit_id
            or not _nilm_real_power_series(helper)
        ):
            continue
        helper_assignments = getattr(
            getattr(coordinator, "store_data", None),
            "nilm_appliance_assignments_by_circuit",
            {},
        )
        if isinstance(helper_assignments, Mapping) and any(
            isinstance(item, Mapping) and item.get("conversion_state") == "direct_meter"
            for item in _iter_items(helper_assignments.get(helper.circuit_id, ()))
        ):
            continue
        options.append(
            {
                ATTR_HELPER_CIRCUIT_ID: helper.circuit_id,
                "helper_name": helper.name,
            }
        )
    return options


def _add_nilm_reference_evidence(
    assignments: list[dict[str, Any]],
    circuit_id: str,
    *,
    coordinator: Any,
) -> None:
    state_options, power_options = _nilm_reference_options(coordinator)
    power_device_ids = {
        item["device_id"]: item["entity_id"]
        for item in power_options
        if item.get("device_id")
    }
    state_device_ids = {
        item["entity_id"]: item.get("device_id") for item in state_options
    }
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        state_entity_id = str(
            assignment.get("reference_state_entity_id") or ""
        ).strip()
        power_entity_id = str(
            assignment.get("reference_power_entity_id") or ""
        ).strip()
        suggested_power_entity_id = power_device_ids.get(
            state_device_ids.get(state_entity_id)
        )
        action_data = {
            ATTR_CIRCUIT_ID: circuit_id,
            ATTR_ASSIGNMENT_ID: assignment_id,
        }
        actions: dict[str, Any] = {
            "set": {
                "domain": DOMAIN,
                "service": SERVICE_SET_NILM_REFERENCE_LINK,
                "data": dict(action_data),
                "requires": [
                    "reference_state_entity_id",
                    "reference_power_entity_id",
                    "reference_threshold_w",
                ],
            }
        }
        actions["import"] = {
            "domain": DOMAIN,
            "service": SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
            "data": {
                **action_data,
                ATTR_LABEL: str(
                    assignment.get("display_name")
                    or assignment.get("appliance_id")
                    or assignment_id
                ),
            },
            "requires": [
                ATTR_GROUND_TRUTH_ENTITY_ID,
                ATTR_REFERENCE_POWER_ENTITY_ID,
                ATTR_THRESHOLD_W,
                ATTR_START,
                ATTR_END,
            ],
        }
        if state_entity_id or power_entity_id:
            actions["remove"] = {
                "domain": DOMAIN,
                "service": SERVICE_REMOVE_NILM_REFERENCE_LINK,
                "data": dict(action_data),
            }
        runtime = nilm_reference_runtime(coordinator, assignment)
        assignment["reference"] = {
            "state_entity_id": state_entity_id or None,
            "power_entity_id": power_entity_id or None,
            "threshold_w": _clamped_float(
                assignment.get("reference_threshold_w"), default=0.0
            ),
            **runtime,
            "state_options": state_options,
            "power_options": power_options,
            "suggested_power_entity_id": suggested_power_entity_id,
            "actions": actions,
        }


def _nilm_reference_options(
    coordinator: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hass = getattr(coordinator, "hass", None)
    states = getattr(hass, "states", None)
    async_all = getattr(states, "async_all", None)
    if not callable(async_all):
        return [], []
    try:
        state_rows = tuple(async_all())
    except (AttributeError, TypeError):
        return [], []

    registry = _entity_registry_for_hass(hass)
    entries = getattr(registry, "entities", {})
    if hasattr(entries, "get"):
        registry_entry = entries.get
    else:
        by_id = {
            str(getattr(item, "entity_id", "") or ""): item
            for item in entries or ()
        }
        registry_entry = by_id.get

    state_options: list[dict[str, Any]] = []
    power_options: list[dict[str, Any]] = []
    for row in state_rows:
        entity_id = str(getattr(row, "entity_id", "") or "").strip()
        domain = entity_id.partition(".")[0]
        attributes = getattr(row, "attributes", {})
        if not isinstance(attributes, Mapping):
            attributes = {}
        name = str(attributes.get("friendly_name") or entity_id).strip()
        registry_row = registry_entry(entity_id)
        device_id = str(getattr(registry_row, "device_id", "") or "") or None
        if domain in {"switch", "binary_sensor", "input_boolean"}:
            state_options.append(
                {
                    "entity_id": entity_id,
                    "name": name,
                    "device_id": device_id,
                    "role": "state",
                    "unit": None,
                }
            )
            continue
        if domain != "sensor":
            continue
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        device_class = str(attributes.get("device_class") or "").strip()
        if sensor_metadata_role_conflict(device_class=device_class, unit=unit):
            continue
        if (
            sensor_role_from_metadata(device_class=device_class, unit=unit)
            is not SensorRole.REAL_POWER
        ):
            continue
        try:
            value = float(getattr(row, "state", None))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        power_options.append(
            {
                "entity_id": entity_id,
                "name": name,
                "device_id": device_id,
                "role": SensorRole.REAL_POWER.value,
                "unit": unit,
            }
        )

    def sort_key(item: Mapping[str, Any]) -> tuple[str, str]:
        return str(item["name"]).casefold(), str(item["entity_id"])

    state_options.sort(key=sort_key)
    power_options.sort(key=sort_key)
    return state_options[:512], power_options[:512]


def _add_nilm_assignment_options(
    items: Iterable[dict[str, Any]],
    assignment_options: list[dict[str, str]],
) -> None:
    if not assignment_options:
        return
    for item in items:
        actions = item.get("actions")
        assign = actions.get("assign") if isinstance(actions, dict) else None
        if isinstance(assign, dict):
            assign["assignment_options"] = list(assignment_options)


def _add_nilm_session_signature_reviews(
    sessions: Iterable[dict[str, Any]],
    signatures: Iterable[Mapping[str, Any]],
) -> None:
    """Expose the retained signature decision on safe, unassigned sessions."""
    by_identifier: dict[str, list[Mapping[str, Any]]] = {}
    for signature in signatures:
        if (
            _nilm_signature_hidden(signature)
            or not isinstance(signature.get("actions"), Mapping)
        ):
            continue
        for identifier in _nilm_signature_identifiers(signature):
            by_identifier.setdefault(identifier, []).append(signature)
    for session in sessions:
        session.pop("signature_review", None)
        fingerprint = str(session.get("signature_fingerprint") or "").strip()
        if (
            not session.get("end")
            or bool(session.get("ambiguous"))
            or bool(session.get("known_load_masked"))
            or str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
            or not nilm_signature_is_assignable(fingerprint)
        ):
            continue
        matches = by_identifier.get(fingerprint, [])
        if len(matches) != 1:
            continue
        signature = matches[0]
        session["signature_review"] = {
            ATTR_SIGNATURE_ID: signature[ATTR_SIGNATURE_ID],
            "display_label": signature.get("display_label"),
            "signature_fingerprint": fingerprint,
            "actions": deepcopy(signature["actions"]),
        }


def _nilm_assignment_payload(
    circuit_id: str,
    assignment: Mapping[str, Any],
    assignments: Iterable[Mapping[str, Any]] = (),
    *,
    entry_id: str = "",
    label_intervals: Iterable[Mapping[str, Any]] = (),
    configured_circuit_names: Iterable[str] = (),
) -> dict[str, Any]:
    assignments = tuple(assignments)
    payload = {
        str(key): value
        for key, value in assignment.items()
        if key not in {"actions", "typical_power_source"}
    }
    if payload.get("display_name"):
        payload["display_name"] = nilm_display_name(
            str(payload["display_name"]),
            configured_circuit_names,
        )
    assignment_id = str(payload.get(ATTR_ASSIGNMENT_ID) or "").strip()
    if not assignment_id:
        return payload
    interval_ids = {
        str(value or "").strip()
        for value in _iter_items(payload.get("label_interval_ids"))
        if str(value or "").strip()
    }
    transition_watts = []
    recorded_interval_watts = []
    for interval in label_intervals:
        if (
            str(interval.get(ATTR_ASSIGNMENT_ID) or "").strip() != assignment_id
            and str(interval.get(ATTR_INTERVAL_ID) or "").strip() not in interval_ids
        ):
            continue
        try:
            watts = float(interval.get("observed_transition_w"))
        except (TypeError, ValueError):
            watts = None
        if watts is not None and math.isfinite(watts) and watts >= 0:
            transition_watts.append(watts)
        try:
            watts = float(interval.get("median_power_w"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(watts) and watts >= 0:
            recorded_interval_watts.append(watts)
    try:
        existing_watts = float(payload.get("typical_power_w"))
    except (TypeError, ValueError):
        existing_watts = None
    if (
        (
            existing_watts is None
            or not math.isfinite(existing_watts)
            or existing_watts < 0
        )
        and transition_watts
    ):
        payload["typical_power_w"] = round(median(transition_watts), 3)
    elif (
        existing_watts is None
        or not math.isfinite(existing_watts)
        or existing_watts < 0
    ) and recorded_interval_watts:
        payload["typical_power_w"] = round(fmean(recorded_interval_watts), 3)
        payload["typical_power_source"] = "interval_average"

    payload["appliance_detail_path"] = _nilm_appliance_detail_panel_path(
        assignment_id, entry_id=entry_id
    )
    state = str(payload.get("lifecycle_state") or "").strip().lower()
    action_data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_ASSIGNMENT_ID: assignment_id}
    actions: dict[str, dict[str, Any]] = {}
    publication_reason = nilm_assignment_publication_reason(payload)
    payload["publication"] = {
        "available": publication_reason is None,
        **({"reason": publication_reason} if publication_reason else {}),
    }
    if state != "retired":
        manual_interval_id = next(
            (
                str(interval.get(ATTR_INTERVAL_ID) or "").strip()
                for interval in label_intervals
                if str(interval.get(ATTR_INTERVAL_ID) or "").strip() in interval_ids
                and str(interval.get(ATTR_ASSIGNMENT_ID) or "").strip()
                == assignment_id
                and str(interval.get("source") or "").strip().lower() == "manual"
            ),
            "",
        )
        if state == "needs_validation" and manual_interval_id:
            actions["accept"] = {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
                "data": {
                    **action_data,
                    ATTR_INTERVAL_ID: manual_interval_id,
                    ATTR_LABEL: str(
                        payload.get("display_name") or payload.get("appliance_id") or ""
                    ).strip(),
                },
            }
        actions["rename"] = {
            "domain": DOMAIN,
            "service": SERVICE_RENAME_NILM_APPLIANCE,
            "data": dict(action_data),
            "requires": [ATTR_LABEL],
        }
        actions["change_profile"] = {
            "domain": DOMAIN,
            "service": SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
            "data": dict(action_data),
            "requires": [ATTR_APPLIANCE_PROFILE],
        }
        actions["change_profile"]["profile_options"] = _nilm_appliance_profile_options(
            payload.get(ATTR_APPLIANCE_PROFILE)
        )
        if _nilm_assignment_has_ground_truth_intervals(payload, label_intervals):
            actions["validate_history"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
                "data": dict(action_data),
            }
        if (
            state == "needs_validation"
            and assignment_id == configured_primary_assignment_id(circuit_id)
        ):
            actions["confirm_primary"] = {
                "domain": DOMAIN,
                "service": SERVICE_CONFIRM_NILM_CONFIGURED_PRIMARY,
                "data": dict(action_data),
            }
        primary_id = configured_primary_assignment_id(circuit_id)
        if (
            assignment_id != primary_id
            and state
            in {"assigned", "needs_validation", "validated", "ready_to_publish"}
            and any(
                item.get(ATTR_ASSIGNMENT_ID) == primary_id for item in assignments
            )
            and any(
                nilm_signature_is_assignable(value)
                for value in _iter_items(payload.get("signature_fingerprints"))
            )
        ):
            actions["confirm_primary"] = {
                "domain": DOMAIN,
                "service": SERVICE_MERGE_NILM_ASSIGNMENTS,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_SOURCE_ASSIGNMENT_ID: assignment_id,
                    ATTR_TARGET_ASSIGNMENT_ID: primary_id,
                },
            }
        target_options = _nilm_assignment_target_options(assignment_id, assignments)
        if target_options:
            actions["merge"] = {
                "domain": DOMAIN,
                "service": SERVICE_MERGE_NILM_ASSIGNMENTS,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_SOURCE_ASSIGNMENT_ID: assignment_id,
                },
                "requires": [ATTR_TARGET_ASSIGNMENT_ID],
                "target_options": target_options,
            }
        if payload.get("publish_entities") is True or state == "published":
            actions["unpublish"] = {
                "domain": DOMAIN,
                "service": SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
                "data": dict(action_data),
            }
        elif publication_reason is None:
            actions["publish"] = {
                "domain": DOMAIN,
                "service": SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
                "data": dict(action_data),
            }
        actions["retire"] = {
            "domain": DOMAIN,
            "service": SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
            "data": dict(action_data),
        }
    if (
        state in {"ignored", "retired"}
        or payload.get("conversion_state") == "direct_meter"
    ):
        actions["restore"] = {
            "domain": DOMAIN,
            "service": SERVICE_RESTORE_NILM_ITEM,
            "data": dict(action_data),
        }
    if state == "retired":
        actions["delete_permanently"] = {
            "domain": DOMAIN,
            "service": SERVICE_DELETE_NILM_APPLIANCE_ASSIGNMENT,
            "data": dict(action_data),
        }
    if actions:
        payload["actions"] = actions
    return payload


def _nilm_assignment_has_ground_truth_intervals(
    assignment: Mapping[str, Any],
    label_intervals: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        isinstance(interval, Mapping)
        and str(interval.get("ground_truth_entity_id") or "").strip()
        and _nilm_validation_assignment_matches(interval, assignment)
        for interval in label_intervals
    )


def _nilm_assignment_target_options(
    assignment_id: str,
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for assignment in assignments:
        target_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not target_id or target_id == assignment_id:
            continue
        if str(assignment.get("lifecycle_state") or "").strip().lower() == "retired":
            continue
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or target_id
        ).strip()
        options.append({"value": target_id, "label": label})
    return options


def _nilm_virtual_appliances_for_assignments(
    assignments: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    edges: list[NilmEdge],
    *,
    coordinator: Any | None = None,
) -> list[dict[str, Any]]:
    reference_date = _nilm_workspace_reference_date(edges, sessions)
    entry_id = str(getattr(coordinator, "entry_id", "") or "")
    virtual_appliances = []
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        if not assignment_id or _nilm_assignment_hidden(assignment):
            continue
        assignment_session_ids = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("session_ids"))
            if str(value or "").strip()
        }
        rejected_session_ids = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("rejected_session_ids"))
            if str(value or "").strip()
        }
        assignment_sessions = [
            session
            for session in sessions
            if (
                session.get("assignment_id") == assignment_id
                or str(session.get("session_id") or "").strip()
                in assignment_session_ids
            )
            and str(session.get("session_id") or "").strip()
            not in rejected_session_ids
        ]
        open_session = _latest_nilm_session(
            session for session in assignment_sessions if not session.get("end")
        )
        latest_session = open_session or _latest_nilm_session(assignment_sessions)
        runtime, reconciliation = nilm_live_runtime(
            coordinator,
            str(assignment.get("mains_circuit_id") or ""),
            assignment_id,
        )
        live_available = nilm_runtime_available(runtime, reconciliation)
        reference = nilm_reference_runtime(coordinator, assignment)
        helper_status = (
            "degraded"
            if any(
                isinstance(link, Mapping) and link.get("status") == "degraded"
                for link in _iter_items(assignment.get("helper_links"))
            )
            else "healthy"
        )
        detail_query = {ATTR_ASSIGNMENT_ID: assignment_id}
        if entry_id:
            detail_query[ATTR_ENTRY_ID] = entry_id
        virtual_appliances.append(
            {
                "appliance_key": f"nilm:{assignment_id}",
                "appliance_id": str(assignment.get("appliance_id") or assignment_id),
                "assignment_id": assignment_id,
                "display_name": str(
                    assignment.get("display_name")
                    or assignment.get("appliance_id")
                    or assignment_id
                ),
                "is_running": (
                    reference["is_running"]
                    if reference["available"]
                    else runtime.get("status") == "on"
                    if live_available
                    else None
                ),
                "estimated_power_w": (
                    _round_float(runtime.get("estimated_power_w"))
                    if live_available
                    else None
                ),
                "estimated_energy_kwh_today": _nilm_daily_energy(
                    assignment_sessions,
                    reference_date,
                ),
                "confidence": _clamped_float(
                    assignment.get("confidence"),
                    default=0.0,
                    upper=1.0,
                ),
                "last_seen": _nilm_session_last_seen(latest_session),
                "active_signature_id": (
                    str(runtime.get("signature_fingerprint") or "")
                    if live_available
                    else None
                ),
                "active_session_id": (
                    str(runtime.get("session_id") or "") if live_available else None
                ),
                "model_status": nilm_model_status(assignment, reconciliation),
                "helper_status": helper_status,
                "source_type": "nilm_estimate",
                "source_label": _panel_text("source_labels", "nilm_estimate"),
                "estimated": True,
                "mains_circuit_id": str(assignment.get("mains_circuit_id") or ""),
                "appliance_detail_api_path": (
                    f"{APPLIANCE_DETAIL_API_PATH}?{urlencode(detail_query)}"
                ),
                "appliance_detail_path": _nilm_appliance_detail_panel_path(
                    assignment_id, entry_id=entry_id
                ),
            }
        )
    return virtual_appliances


def _nilm_reconciliation_payload(
    coordinator: Any, circuit_id: str
) -> dict[str, Any] | None:
    _, reconciliation = nilm_live_runtime(coordinator, circuit_id, "")
    if not reconciliation:
        return None
    conflict = reconciliation.get("conflict")
    return {
        "residual_w": reconciliation.get("residual_w"),
        "residual_energy_kwh": reconciliation.get("residual_energy_kwh"),
        "tolerance_w": reconciliation.get("tolerance_w"),
        "state": (
            "conflict"
            if conflict
            else "consistent"
            if reconciliation.get("consistent")
            else "unavailable"
        ),
        "review_action": reconciliation.get("review_item"),
    }


def _nilm_appliance_detail_panel_path(assignment_id: str, *, entry_id: str = "") -> str:
    query = {ATTR_ASSIGNMENT_ID: assignment_id, "appliance_detail": "1"}
    if entry_id:
        query[ATTR_ENTRY_ID] = entry_id
    return f"/{PANEL_URL_PATH}?{urlencode(query)}"


def _nilm_appliance_profile_options(
    current_profile: Any = None,
) -> list[dict[str, str]]:
    values = (
        str(current_profile or "").strip(),
        *(
            item.value
            for item in ApplianceProfile
            if item is not ApplianceProfile.MAINS_NILM
        ),
    )
    return [
        {"value": profile, "label": friendly_feature_name(profile)}
        for index, profile in enumerate(values)
        if profile and profile not in values[:index]
    ]


def _nilm_workspace_lanes(
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    label_intervals: Iterable[Mapping[str, Any]] = (),
    sessions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    sessions = tuple(sessions)
    lanes = {
        "needs_review": _nilm_lane("Needs Review"),
        "assigned": _nilm_lane("Assigned"),
        "published": _nilm_lane("Published"),
        "hidden": _nilm_lane("Removed"),
    }
    assigned_signature_ids = _nilm_assigned_signature_ids(assignments)
    reviewed_session_fingerprints = {
        str(session.get(ATTR_SIGNATURE_FINGERPRINT) or "").strip()
        for session in sessions
        if str(session.get(ATTR_SESSION_ID) or "").strip()
        and not str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
        and isinstance(session.get("actions"), Mapping)
        and isinstance(session["actions"].get("assign"), Mapping)
    }
    for signature in signatures:
        signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
        if not signature_id:
            continue
        complete_component = _nilm_signature_direction(signature) == "on" and bool(
            signature.get("session_ids")
        )
        if _nilm_signature_hidden(signature) and complete_component:
            lanes["hidden"]["signature_ids"].append(signature_id)
        elif (
            complete_component
            and _nilm_signature_session_fingerprint(signature)
            not in reviewed_session_fingerprints
            and not str(signature.get("matched_assignment_id") or "").strip()
            and _nilm_signature_identifiers(signature).isdisjoint(
                assigned_signature_ids,
            )
        ):
            lanes["needs_review"]["signature_ids"].append(signature_id)

    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        state = str(assignment.get("lifecycle_state") or "").strip().lower()
        confidence = _clamped_float(assignment.get("confidence"), default=0.0)
        if _nilm_assignment_hidden(assignment):
            lane = "hidden"
        elif assignment.get("publish_entities") is True or state == "published":
            lane = "published"
        elif state in {
                "needs_validation",
                "conflict",
                "low_confidence",
                "validated",
                "ready_to_publish",
            } or confidence < 0.8:
            lane = "needs_review"
        else:
            lane = "assigned"
        lanes[lane]["assignment_ids"].append(assignment_id)
    assigned_interval_ids = {
        str(value or "").strip()
        for assignment in assignments
        for value in _iter_items(assignment.get("label_interval_ids"))
        if str(value or "").strip()
    }
    for interval in label_intervals:
        interval_id = str(interval.get(ATTR_INTERVAL_ID) or "").strip()
        if (
            interval_id
            and interval_id not in assigned_interval_ids
            and not str(interval.get(ATTR_ASSIGNMENT_ID) or "").strip()
        ):
            lanes["needs_review"]["interval_ids"].append(interval_id)
    for session in sessions:
        session_id = str(session.get(ATTR_SESSION_ID) or "").strip()
        actions = session.get("actions")
        if (
            session_id
            and not str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
            and isinstance(actions, Mapping)
            and isinstance(actions.get("assign"), Mapping)
        ):
            lanes["needs_review"]["session_ids"].append(session_id)
    return lanes


def _nilm_lane(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "assignment_ids": [],
        "signature_ids": [],
        "interval_ids": [],
        "session_ids": [],
    }


def _nilm_assignment_hidden(assignment: Mapping[str, Any]) -> bool:
    return str(assignment.get("lifecycle_state") or "").strip().lower() in {
        "ignored",
        "retired",
    }


def _nilm_signature_hidden(signature: Mapping[str, Any]) -> bool:
    state = str(signature.get("review_state") or "").strip().lower()
    return bool(signature.get("ignored") or state in {"ignored", "merged"})


def _nilm_assigned_signature_ids(
    assignments: Iterable[Mapping[str, Any]],
) -> set[str]:
    signature_ids: set[str] = set()
    for assignment in assignments:
        for key in ("signature_fingerprints", "signature_ids"):
            signature_ids.update(
                str(value or "").strip()
                for value in _iter_items(assignment.get(key))
                if str(value or "").strip()
            )
        for key in ("feedback_fingerprint", "signature_fingerprint", "fingerprint"):
            value = str(assignment.get(key) or "").strip()
            if value:
                signature_ids.add(value)
    return signature_ids


def _nilm_signature_identifiers(signature: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for key in (
        ATTR_SIGNATURE_ID,
        "signature_id",
        "fingerprint",
        "feedback_fingerprint",
        "signature_fingerprint",
    ):
        value = str(signature.get(key) or "").strip()
        if value:
            identifiers.add(value)
    for key in ("signature_fingerprints", "signature_ids"):
        identifiers.update(
            str(value or "").strip()
            for value in _iter_items(signature.get(key))
            if str(value or "").strip()
        )
    return identifiers


def _nilm_selection_guidance() -> dict[str, Any]:
    return {
        "snap_to_edges": True,
        "show_likely_paired_off_edge": True,
        "preview_interval_kwh": True,
        "show_known_load_overlap": True,
    }


def _nilm_validation_payload(
    label_intervals: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    ground_truth_intervals = [
        interval
        for interval in label_intervals
        if str(interval.get("ground_truth_entity_id") or "").strip()
    ]
    predictions = [
        session
        for session in sessions
        if session.get("end") and str(session.get("assignment_id") or "").strip()
    ]
    assignment_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignments
        if str(assignment.get("assignment_id") or "").strip()
    }
    matched_prediction_ids: set[str] = set()
    preview = []
    for interval in ground_truth_intervals:
        session, overlap = _nilm_validation_best_match(
            interval,
            predictions,
            assignment_by_id,
            matched_prediction_ids,
        )
        if session is not None:
            matched_prediction_ids.add(str(session.get("session_id") or ""))
        measured_power_w = _optional_round_float(interval.get("median_power_w"))
        measured_energy_kwh = _optional_round_float(
            interval.get("measured_energy_kwh"), digits=6
        )
        estimated_power_w = (
            _optional_round_float(session.get("median_power_w")) if session else None
        )
        estimated_energy_kwh = (
            _optional_round_float(session.get("estimated_energy_kwh"), digits=6)
            if session
            else None
        )
        preview.append(
            {
                "interval_id": interval.get("interval_id"),
                "label": interval.get("label") or interval.get("appliance_id"),
                "ground_truth_entity_id": interval.get("ground_truth_entity_id"),
                "source": interval.get("source") or "manual",
                "prediction_status": "matched" if session is not None else "missed",
                "matched_assignment_id": (
                    str(session.get("assignment_id") or "") if session else None
                ),
                "matched_session_id": (
                    str(session.get("session_id") or "") if session else None
                ),
                "overlap_seconds": overlap,
                "prediction_confidence": session.get("confidence") if session else None,
                "measured_power_w": measured_power_w,
                "estimated_power_w": estimated_power_w,
                "power_error_w": (
                    round(abs(estimated_power_w - measured_power_w), 3)
                    if measured_power_w is not None and estimated_power_w is not None
                    else None
                ),
                "measured_energy_kwh": measured_energy_kwh,
                "estimated_energy_kwh": estimated_energy_kwh,
                "energy_error_kwh": (
                    round(abs(estimated_energy_kwh - measured_energy_kwh), 6)
                    if measured_energy_kwh is not None
                    and estimated_energy_kwh is not None
                    else None
                ),
            }
        )

    matched_ground_truth_count = sum(
        1 for item in preview if item["prediction_status"] == "matched"
    )
    matched_prediction_count = len({value for value in matched_prediction_ids if value})
    prediction_count = len(predictions)
    ground_truth_count = len(ground_truth_intervals)
    return {
        "metrics": {
            "ground_truth_interval_count": ground_truth_count,
            "prediction_count": prediction_count,
            "matched_ground_truth_count": matched_ground_truth_count,
            "matched_prediction_count": matched_prediction_count,
            "missed_ground_truth_count": (
                ground_truth_count - matched_ground_truth_count
            ),
            "precision": _nilm_validation_ratio(
                matched_prediction_count,
                prediction_count,
            ),
            "recall": _nilm_validation_ratio(
                matched_ground_truth_count,
                ground_truth_count,
            ),
        },
        "prediction_preview": preview,
    }


def _nilm_validation_best_match(
    interval: Mapping[str, Any],
    sessions: list[dict[str, Any]],
    assignment_by_id: Mapping[str, Mapping[str, Any]],
    matched_prediction_ids: set[str],
) -> tuple[dict[str, Any] | None, float]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for session in sessions:
        session_id = str(session.get("session_id") or "")
        if session_id and session_id in matched_prediction_ids:
            continue
        assignment = assignment_by_id.get(str(session.get("assignment_id") or ""))
        if assignment is None or not _nilm_validation_assignment_matches(
            interval,
            assignment,
        ):
            continue
        overlap = _nilm_validation_overlap_seconds(interval, session)
        if overlap > 0:
            candidates.append((overlap, session))
    if not candidates:
        return None, 0.0
    candidates.sort(key=lambda item: item[0], reverse=True)
    overlap, session = candidates[0]
    return session, overlap


def _nilm_validation_assignment_matches(
    interval: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    interval_id = str(interval.get("interval_id") or "").strip()
    if interval_id and interval_id in {
        str(value or "").strip()
        for value in _iter_items(assignment.get("label_interval_ids"))
    }:
        return True
    interval_appliance = (
        str(interval.get("appliance_id") or interval.get("label") or "")
        .strip()
        .casefold()
    )
    if not interval_appliance:
        return False
    return interval_appliance in {
        str(assignment.get("appliance_id") or "").strip().casefold(),
        str(assignment.get("display_name") or "").strip().casefold(),
    }


def _nilm_validation_overlap_seconds(
    interval: Mapping[str, Any],
    session: Mapping[str, Any],
) -> float:
    interval_start = _datetime_from_iso(interval.get("start"))
    interval_end = _datetime_from_iso(interval.get("end"))
    session_start = _datetime_from_iso(session.get("start"))
    session_end = _datetime_from_iso(session.get("end"))
    if not all((interval_start, interval_end, session_start, session_end)):
        return 0.0
    overlap_start = max(interval_start, session_start)
    overlap_end = min(interval_end, session_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def _nilm_validation_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _latest_nilm_session(
    sessions: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    latest: Mapping[str, Any] | None = None
    latest_seen: datetime | None = None
    for session in sessions:
        seen = _nilm_session_seen_datetime(session)
        if seen is None:
            continue
        if latest_seen is None or seen > latest_seen:
            latest = session
            latest_seen = seen
    return latest


def _nilm_session_seen_datetime(session: Mapping[str, Any]) -> datetime | None:
    return _datetime_from_iso(session.get("end")) or _datetime_from_iso(
        session.get("start")
    )


def _nilm_session_last_seen(session: Mapping[str, Any] | None) -> str | None:
    if session is None:
        return None
    seen = _nilm_session_seen_datetime(session)
    return seen.isoformat() if seen else None


def _nilm_workspace_reference_date(
    edges: list[NilmEdge],
    sessions: list[dict[str, Any]],
) -> Any:
    latest_edge = max((edge.timestamp for edge in edges), default=None)
    if latest_edge is not None:
        return latest_edge.date()
    latest_session = _latest_nilm_session(sessions)
    seen = _nilm_session_seen_datetime(latest_session) if latest_session else None
    return seen.date() if seen else None


def _nilm_daily_energy(
    sessions: list[dict[str, Any]],
    reference_date: Any,
) -> float:
    if reference_date is None:
        return 0.0
    return round(
        sum(
            _clamped_float(session.get("estimated_energy_kwh"), default=0.0)
            for session in sessions
            if (
                (start := _datetime_from_iso(session.get("start"))) is not None
                and start.date() == reference_date
            )
        ),
        3,
    )


def _round_float(value: Any) -> float:
    return round(_clamped_float(value, default=0.0), 3)


def _optional_round_float(value: Any, *, digits: int = 3) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) and number >= 0 else None


def _clamped_float(value: Any, *, default: float, upper: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    if upper is not None:
        return min(number, upper)
    return number


def _nilm_workspace_paths(coordinator: Any, circuit_id: str) -> dict[str, str]:
    target = _nilm_workspace_target((coordinator,), circuit_id)
    if target is None:
        return {}
    _target_coordinator, config, _sources = target
    entry_id = str(getattr(coordinator, "entry_id", "") or "")
    query = urlencode({"entry_id": entry_id, "circuit_id": config.circuit_id})
    return {
        "workspace_api_path": f"{NILM_WORKSPACE_API_PATH}?{query}",
        "workspace_call_api_path": f"{DOMAIN}/nilm_workspace?{query}",
    }


def _nilm_known_load_overlays(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    circuit_registry = getattr(coordinator, "circuit_registry", None)
    source_config = (
        circuit_registry.config_for_circuit(circuit_id)
        if circuit_registry is not None
        else None
    )
    if (
        source_config is None
        or nilm_source_kind(source_config) is not NilmSourceKind.MAINS
    ):
        return []
    known_load_ids = {
        str(value)
        for value in _iter_items(
            getattr(circuit_registry, "known_load_circuit_ids", ())
        )
    }
    overlays: list[dict[str, Any]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if not isinstance(config, CircuitConfig) or config.circuit_id == circuit_id:
            continue
        if known_load_ids and config.circuit_id not in known_load_ids:
            continue
        entity_ids = _sensor_entity_ids(config)
        if not entity_ids:
            continue
        overlays.append(
            {
                "circuit_id": config.circuit_id,
                "name": config.name,
                "entity_ids": entity_ids,
            }
        )
        if len(overlays) >= MAX_NILM_WORKSPACE_KNOWN_LOADS:
            break
    return overlays


def _nilm_solar_overlays(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    source_config = next(
        (
            config
            for config in getattr(coordinator, "circuit_configs", ()) or ()
            if isinstance(config, CircuitConfig) and config.circuit_id == circuit_id
        ),
        None,
    )
    if (
        source_config is None
        or nilm_source_kind(source_config) is not NilmSourceKind.MAINS
    ):
        return []
    overlays: list[dict[str, Any]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if (
            not isinstance(config, CircuitConfig)
            or config.circuit_id == circuit_id
            or str(config.appliance_profile) != ApplianceProfile.SOLAR_INVERTER.value
        ):
            continue
        entity_ids = _sensor_entity_ids(config)
        if entity_ids:
            overlays.append(
                {
                    "circuit_id": config.circuit_id,
                    "name": config.name,
                    "entity_ids": entity_ids,
                }
            )
        if len(overlays) >= MAX_NILM_WORKSPACE_KNOWN_LOADS:
            break
    return overlays


def _nilm_workspace_history_payload(
    config: CircuitConfig,
    known_load_overlays: list[dict[str, Any]],
    solar_overlays: list[dict[str, Any]],
    *,
    hours: Any,
    start: Any = None,
    end: Any = None,
    entry_id: str | None = None,
    helper_configs: Iterable[CircuitConfig] = (),
    hass: Any = None,
) -> dict[str, Any]:
    requested_hours, start_at, end_at, targeted = _nilm_workspace_history_window(
        hours,
        start=start,
        end=end,
    )
    source_series = _nilm_real_power_series(config, hass=hass)
    entity_series = _nilm_workspace_history_series(
        config,
        known_load_overlays,
        solar_overlays,
        helper_configs,
        hass=hass,
    )
    entities = [item["entity_id"] for item in entity_series]
    history_query_values = {
        "circuit_id": config.circuit_id,
        "hours": str(requested_hours),
    }
    if entry_id:
        history_query_values[ATTR_ENTRY_ID] = entry_id
    if targeted:
        history_query_values["start"] = start_at.isoformat()
        history_query_values["end"] = end_at.isoformat()
    history_query = urlencode(history_query_values)
    recorder_query = urlencode(
        {
            "filter_entity_id": ",".join(entities),
            "end_time": end_at.isoformat(),
            "minimal_response": "1",
            "no_attributes": "1",
        }
    )
    payload = {
        "start": start_at.isoformat(),
        "end": end_at.isoformat(),
        "hours": requested_hours,
        "max_hours": MAX_NILM_WORKSPACE_HISTORY_HOURS,
        "entities": entities,
        "source_entities": [item["entity_id"] for item in source_series],
        "entity_series": entity_series,
        "entity_count": len(entities),
        "max_entities": MAX_NILM_WORKSPACE_HISTORY_ENTITIES,
        "api_path": f"{DOMAIN}/nilm_workspace_history?{history_query}",
        "fetch_path": f"{NILM_WORKSPACE_HISTORY_API_PATH}?{history_query}",
        "recorder_api_path": (
            f"history/period/{quote(start_at.isoformat(), safe='')}?{recorder_query}"
        ),
        "max_points_per_entity": MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY,
    }
    if not source_series:
        payload["missing_real_power_reason"] = (
            "Configure a real-power sensor measured in W, kW, mW, or MW."
        )
    return payload


def _nilm_workspace_history_window(
    hours: Any,
    *,
    start: Any = None,
    end: Any = None,
) -> tuple[float, datetime, datetime, bool]:
    """Return an aware, capped target window or the bounded hours fallback."""

    try:
        start_at = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError
        start_at = start_at.astimezone(UTC)
        end_at = end_at.astimezone(UTC)
        if end_at <= start_at:
            raise ValueError
        maximum_window = timedelta(hours=MAX_NILM_WORKSPACE_HISTORY_HOURS)
        if end_at - start_at > maximum_window:
            start_at = end_at - maximum_window
        requested_hours = (end_at - start_at).total_seconds() / 3600
    except (TypeError, ValueError, OverflowError):
        requested_hours = _bounded_float(
            hours,
            default=DEFAULT_NILM_WORKSPACE_HISTORY_HOURS,
            upper=MAX_NILM_WORKSPACE_HISTORY_HOURS,
        )
        end_at = datetime.now(UTC)
        return requested_hours, end_at - timedelta(hours=requested_hours), end_at, False

    return requested_hours, start_at, end_at, True


def _nilm_workspace_history_entities(
    config: CircuitConfig,
    _known_load_overlays: list[dict[str, Any]],
    _solar_overlays: list[dict[str, Any]],
    helper_configs: Iterable[CircuitConfig] = (),
) -> list[str]:
    return [
        item["entity_id"]
        for item in _nilm_workspace_history_series(
            config,
            _known_load_overlays,
            _solar_overlays,
            helper_configs,
        )
    ]


def _nilm_workspace_history_series(
    config: CircuitConfig,
    _known_load_overlays: list[dict[str, Any]],
    _solar_overlays: list[dict[str, Any]],
    helper_configs: Iterable[CircuitConfig] = (),
    *,
    hass: Any = None,
) -> list[dict[str, str]]:
    source_series = _nilm_real_power_series(config, hass=hass)
    if config.mode != CircuitMode.MAINS_NILM:
        source_series = source_series[:1]
    if not source_series:
        return []
    helper_series = [
        series
        for helper in helper_configs
        for series in _nilm_real_power_series(helper, hass=hass)[:1]
    ]
    unique = {}
    for series in (*source_series, *helper_series):
        unique.setdefault(series["entity_id"], series)
    return list(unique.values())[:5]


def _nilm_real_power_series(
    config: CircuitConfig,
    *,
    hass: Any = None,
) -> list[dict[str, str]]:
    series = []
    for sensor in getattr(config, "sensors", ()) or ():
        item = _nilm_real_power_sensor_series(sensor, hass=hass)
        if item is not None and item["entity_id"] not in {
            existing["entity_id"] for existing in series
        }:
            series.append(item)
    return series


def _nilm_real_power_sensor_series(
    sensor: Any,
    *,
    hass: Any = None,
) -> dict[str, str] | None:
    entity_id = str(getattr(sensor, "entity_id", "") or "").strip()
    if not entity_id:
        return None
    unit = str(getattr(sensor, "unit", "") or "").strip()
    metadata_role = sensor_role_from_metadata(unit=unit)
    configured_role = getattr(sensor, "role", None)
    effective_role = metadata_role or configured_role
    if effective_role != SensorRole.REAL_POWER:
        return None
    if unit and unit.lower() not in {"w", "kw", "mw"}:
        return None
    series = {
        "entity_id": entity_id,
        "effective_role": SensorRole.REAL_POWER.value,
        "source_unit": unit or "W",
    }
    if hass is not None:
        metadata = _nilm_history_live_real_power_metadata(hass, entity_id)
        if metadata is None:
            return None
        series.update(metadata)
    return series


def _nilm_history_live_real_power_metadata(
    hass: Any,
    entity_id: str,
) -> dict[str, str] | None:
    states = getattr(hass, "states", None)
    state_get = getattr(states, "get", None)
    state = state_get(entity_id) if callable(state_get) else None
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, Mapping):
        return {"effective_role": SensorRole.REAL_POWER.value}
    device_class = attributes.get("device_class")
    unit = str(attributes.get("unit_of_measurement") or "").strip()
    if sensor_metadata_role_conflict(device_class=device_class, unit=unit):
        return None
    role = sensor_role_from_metadata(device_class=device_class, unit=unit)
    if role not in {None, SensorRole.REAL_POWER} or (
        unit and unit.lower() not in {"w", "kw", "mw"}
    ):
        return None
    metadata = {"effective_role": SensorRole.REAL_POWER.value}
    if unit:
        metadata["source_unit"] = unit
    return metadata


def _sensor_entity_ids(config: Any) -> list[str]:
    return _unique_strings(
        sensor.entity_id
        for sensor in getattr(config, "sensors", ()) or ()
        if getattr(sensor, "entity_id", None)
    )


def _nilm_edges_for_circuit(coordinator: Any, circuit_id: str) -> list[NilmEdge]:
    edges_by_circuit = getattr(coordinator, "_nilm_unmatched_edges", {})
    if not isinstance(edges_by_circuit, Mapping):
        return []
    return [
        edge
        for edge in _iter_items(edges_by_circuit.get(circuit_id, ()))
        if isinstance(edge, NilmEdge)
    ]


def _nilm_edge_payload(edge: NilmEdge) -> dict[str, Any]:
    return {
        "timestamp": edge.timestamp.isoformat(),
        "direction": edge.direction,
        "delta_w": edge.delta_w,
        "delta_var": edge.delta_var,
        "delta_va": edge.delta_va,
        "delta_pf": edge.delta_pf,
        "dominant_leg": edge.dominant_leg,
        "split_phase_type": edge.split_phase_type,
    }


def _nilm_workspace_sessions(
    edges: list[NilmEdge],
    circuit_id: str,
    *,
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
    limit: int | None = MAX_NILM_WORKSPACE_SESSIONS,
) -> list[dict[str, Any]]:
    signature_by_id = {
        key: signature
        for signature in signatures
        for key in _nilm_signature_lookup_keys(signature)
    }
    assignment_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignments
    }
    matcher_specs: list[dict[str, Any]] = []
    for signature_fingerprint, assignment_id in _nilm_workspace_session_specs(
        signatures,
        assignments,
    ):
        spec = dict(signature_by_id.get(signature_fingerprint) or {})
        spec["signature_fingerprint"] = signature_fingerprint
        spec["assignment_id"] = assignment_id
        assignment = assignment_by_id.get(assignment_id or "", {})
        for key in ("min_duration_seconds", "max_duration_seconds"):
            if key in assignment:
                spec[key] = assignment[key]
        matcher_specs.append(spec)
    first_on_w = next(
        (
            abs(float(edge.delta_w))
            for edge in sorted(edges, key=lambda item: item.timestamp)
            if edge.direction == "on" and abs(float(edge.delta_w)) > 0.0
        ),
        None,
    )
    if first_on_w is not None:
        for spec in matcher_specs:
            if not any(
                spec.get(key) is not None for key in ("typical_watts", "median_delta_w")
            ):
                spec["typical_watts"] = first_on_w
        if not matcher_specs:
            matcher_specs.append(
                {
                    "signature_fingerprint": "unassigned",
                    "typical_watts": first_on_w,
                }
            )
    sessions = pair_nilm_sessions_for_signatures(
        edges,
        signature_specs=matcher_specs,
        mains_circuit_id=circuit_id,
    )
    payloads = [
        _nilm_session_payload(
            session,
            reviewed_session_ids=reviewed_session_ids,
        )
        for session in sessions
    ]
    return payloads if limit is None else payloads[:limit]


def _nilm_workspace_session_specs(
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> list[tuple[str, str | None]]:
    specs: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    seen_fingerprints: set[str] = set()
    hidden_fingerprints: set[str] = set()
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip() or None
        saved_fingerprints = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("signature_fingerprints"))
            if str(value or "").strip()
        }
        fingerprints = {
            resolved
            for value in saved_fingerprints
            if nilm_signature_is_assignable(value)
            if (resolved := resolve_nilm_signature_fingerprint(value, signatures))
        }
        if _nilm_assignment_hidden(assignment):
            hidden_fingerprints.update(fingerprints)
            continue
        for fingerprint in fingerprints:
            key = (fingerprint, assignment_id)
            if fingerprint and key not in seen:
                specs.append(key)
                seen.add(key)
                seen_fingerprints.add(fingerprint)
    for signature in signatures:
        fingerprint = _nilm_signature_session_fingerprint(signature)
        key = (fingerprint, None)
        if (
            fingerprint
            and nilm_signature_is_assignable(fingerprint)
            and not _nilm_signature_hidden(signature)
            and fingerprint not in hidden_fingerprints
            and fingerprint not in seen_fingerprints
            and key not in seen
        ):
            specs.append(key)
            seen.add(key)
    return specs


def _nilm_workspace_visible_sessions(
    sessions: Iterable[Mapping[str, Any]],
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    hidden_assignment_ids = {
        str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        for assignment in assignments
        if _nilm_assignment_hidden(assignment)
        if str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
    }
    hidden_fingerprints = {
        str(value or "").strip()
        for assignment in assignments
        if _nilm_assignment_hidden(assignment)
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    }
    visible_assignment_fingerprints = {
        str(value or "").strip()
        for assignment in assignments
        if not _nilm_assignment_hidden(assignment)
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    }
    hidden_fingerprints.update(
        fingerprint
        for signature in signatures
        if _nilm_signature_hidden(signature)
        if (fingerprint := _nilm_signature_session_fingerprint(signature))
        if str(signature.get("review_state") or "").strip().lower() != "merged"
        or fingerprint not in visible_assignment_fingerprints
    )
    return [
        dict(session)
        for session in sessions
        if str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
        not in hidden_assignment_ids
        and str(session.get("signature_fingerprint") or "").strip()
        not in hidden_fingerprints
    ]


def _nilm_signature_lookup_keys(signature: Mapping[str, Any]) -> list[str]:
    return [
        value
        for value in (
            str(signature.get(ATTR_SIGNATURE_ID) or "").strip(),
            str(signature.get("feedback_fingerprint") or "").strip(),
            str(signature.get("signature_fingerprint") or "").strip(),
        )
        if value
    ]


def _nilm_signature_session_fingerprint(signature: Mapping[str, Any]) -> str:
    return str(
        signature.get("feedback_fingerprint")
        or signature.get("signature_fingerprint")
        or signature.get(ATTR_SIGNATURE_ID)
        or ""
    ).strip()


def _nilm_session_history_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    sessions_by_circuit = getattr(store_data, "nilm_session_history_by_circuit", {})
    if not isinstance(sessions_by_circuit, Mapping):
        return []
    return [
        _nilm_session_payload_with_actions(
            dict(session),
            reviewed_session_ids=reviewed_session_ids,
        )
        for session in _iter_items(sessions_by_circuit.get(circuit_id))
        if isinstance(session, Mapping)
    ]


def _nilm_reviewed_session_ids_by_assignment(
    assignments: Iterable[Mapping[str, Any]],
) -> dict[str, set[str]]:
    reviewed: dict[str, set[str]] = {}
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        reviewed_ids = reviewed.setdefault(assignment_id, set())
        for key in ("confirmed_session_ids", "rejected_session_ids"):
            for value in _iter_items(assignment.get(key)):
                session_id = str(value or "").strip()
                if session_id:
                    reviewed_ids.add(session_id)
    return reviewed


def _nilm_session_display_labels(
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for signature in signatures:
        label = str(
            signature.get("display_label")
            or signature.get("display_name")
            or signature.get("likely_type")
            or signature.get(ATTR_SIGNATURE_ID)
            or ""
        ).strip()
        if not label:
            continue
        for key in _nilm_signature_lookup_keys(signature):
            labels.setdefault(key, label)
    for assignment in assignments:
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment.get(ATTR_ASSIGNMENT_ID)
            or ""
        ).strip()
        if not label:
            continue
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if assignment_id:
            labels[assignment_id] = label
        for value in _iter_items(assignment.get("session_ids")):
            key = str(value or "").strip()
            if key:
                labels[key] = label
        fingerprints = [
            str(value or "").strip()
            for value in _iter_items(assignment.get("signature_fingerprints"))
            if str(value or "").strip()
        ]
        if fingerprints and not any(map(nilm_signature_is_assignable, fingerprints)):
            continue
        for key in fingerprints:
            labels[key] = label
    return labels


def _add_nilm_session_display_labels(
    sessions: Iterable[Mapping[str, Any]],
    labels: Mapping[str, str],
) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for session in sessions:
        payload = dict(session)
        label = str(payload.get("display_label") or "").strip()
        for field in ("assignment_id", "signature_fingerprint", "session_id"):
            key = str(payload.get(field) or "").strip()
            if not label and key:
                label = labels.get(key, "")
        if label:
            payload["display_label"] = label
        labeled.append(payload)
    return labeled


def _merge_nilm_session_payloads(
    primary: Iterable[Mapping[str, Any]],
    fallback: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in (*list(primary), *list(fallback)):
        session_id = str(session.get("session_id") or "").strip()
        if not session_id or session_id in seen:
            continue
        merged.append(dict(session))
        seen.add(session_id)
    return merged


def _nilm_session_payload(
    session: NilmSession,
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    return _nilm_session_payload_with_actions(
        nilm_session_to_dict(session),
        reviewed_session_ids=reviewed_session_ids,
    )


def _nilm_session_payload_with_actions(
    payload: dict[str, Any],
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    circuit_id = str(payload.get("mains_circuit_id") or "").strip()
    signature_fingerprint = str(payload.get("signature_fingerprint") or "").strip()
    if signature_fingerprint and not nilm_signature_is_assignable(
        signature_fingerprint
    ):
        payload.pop(ATTR_ASSIGNMENT_ID, None)
    payload.pop("actions", None)
    if session_id and circuit_id:
        data = {
            ATTR_CIRCUIT_ID: circuit_id,
            ATTR_SESSION_ID: session_id,
        }
        assignment_id = str(payload.get(ATTR_ASSIGNMENT_ID) or "").strip()
        actions: dict[str, Any] = {}
        if nilm_signature_is_assignable(signature_fingerprint) and not assignment_id:
            data[ATTR_SIGNATURE_FINGERPRINT] = signature_fingerprint
            actions["assign"] = {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
                "data": data,
                "requires": [ATTR_LABEL],
            }
        if payload.get("end") and assignment_id and (
            reviewed_session_ids is None
            or (
                assignment_id in reviewed_session_ids
                and all(session_id not in ids for ids in reviewed_session_ids.values())
            )
        ):
            action_data = {
                ATTR_CIRCUIT_ID: circuit_id,
                ATTR_SESSION_ID: session_id,
                ATTR_ASSIGNMENT_ID: assignment_id,
            }
            actions["validate"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_SESSION,
                "data": dict(action_data),
            }
            actions["reject"] = {
                "domain": DOMAIN,
                "service": SERVICE_REJECT_NILM_SESSION,
                "data": dict(action_data),
            }
        if actions:
            payload["actions"] = actions
    return payload


def _bounded_float(
    value: Any,
    *,
    default: float,
    upper: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, upper)


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _format_power_label(typical_watts: float) -> str:
    if typical_watts >= 1000:
        return f"{round(typical_watts / 1000, 1):.1f} kW"
    return f"{round(typical_watts):.0f} W"


def _format_first_seen_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.split("T", 1)[0]
