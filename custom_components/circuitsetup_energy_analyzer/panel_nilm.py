"""NILM panel payload builders and bounded workspace contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

from .const import DOMAIN
from .models import ApplianceProfile, CircuitConfig, CircuitMode, SensorRole
from .nilm import (
    NilmEdge,
    NilmSession,
    nilm_session_to_dict,
    pair_nilm_sessions_for_signatures,
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
from .services import (
    ATTR_APPLIANCE_PROFILE,
    ATTR_ASSIGNMENT_ID,
    ATTR_CIRCUIT_ID,
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_GROUND_TRUTH_ENTITY_ID,
    ATTR_INTERVAL_ID,
    ATTR_LABEL,
    ATTR_MAINS_ENTITY_ID,
    ATTR_SESSION_ID,
    ATTR_SIGNATURE_FINGERPRINT,
    ATTR_SIGNATURE_ID,
    ATTR_SOURCE_ASSIGNMENT_ID,
    ATTR_START,
    ATTR_TARGET_ASSIGNMENT_ID,
    SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
    SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
    SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
    SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
    SERVICE_CONVERT_NILM_APPLIANCE_TO_DIRECT_METER,
    SERVICE_DELETE_NILM_LABEL_INTERVAL,
    SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
    SERVICE_IGNORE_NILM_SIGNATURE,
    SERVICE_LABEL_NILM_INTERVAL,
    SERVICE_LABEL_NILM_SIGNATURE,
    SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
    SERVICE_MERGE_NILM_ASSIGNMENTS,
    SERVICE_MERGE_NILM_SIGNATURES,
    SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_REJECT_NILM_SESSION,
    SERVICE_RENAME_NILM_APPLIANCE,
    SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
    SERVICE_VALIDATE_NILM_SESSION,
)
from .ux import friendly_feature_name

MAX_NILM_PANEL_SIGNATURES = 5
MAX_NILM_MERGE_TARGET_OPTIONS = 5
NILM_SIGNATURE_PANEL_FIELDS = (
    ATTR_SIGNATURE_ID,
    "display_name",
    "user_label",
    "likely_type",
    "typical_watts",
    "typical_duration_seconds",
    "seen_count",
    "confidence",
    "first_seen",
    "last_seen",
    "voltage_class",
    "dominant_leg",
    "known_load_overlap",
    "running_state",
    "current_runtime_minutes",
    "estimated_energy_today_kwh",
    "review_state",
    "expected",
    "ignored",
    "merged_into",
    "fingerprint",
    "feedback_fingerprint",
    "signature_fingerprint",
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
    """Return bounded NILM workspace data for one mains NILM circuit."""

    target = _nilm_workspace_target(
        tuple(coordinators),
        circuit_id,
        entry_id=entry_id,
    )
    if target is None:
        return {
            "status": "not_found",
            "requested_circuit_id": circuit_id or None,
            "message": _panel_text("nilm_workspace", "no_mains_circuit"),
        }

    coordinator, config = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    edges = _nilm_edges_for_circuit(coordinator, config.circuit_id)
    recent_edges = sorted(edges, key=lambda edge: edge.timestamp)[
        -MAX_NILM_WORKSPACE_EDGES:
    ]
    signatures = _nilm_workspace_signatures(coordinator, config.circuit_id)
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
    assignment_options = _nilm_assignment_options(assignments)
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
    virtual_appliances = _nilm_virtual_appliances_for_assignments(
        assignments,
        sessions,
        edges,
    )
    validation = _nilm_validation_payload(
        all_label_intervals,
        all_sessions,
        assignments,
    )
    lanes = _nilm_workspace_lanes(signatures, assignments, label_intervals)
    return {
        "status": "ok",
        "circuit": _circuit_payload(config),
        "history": _nilm_workspace_history_payload(
            config,
            known_load_overlays,
            solar_overlays,
            hours=hours,
            entry_id=selected_entry_id,
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
                for item_key in ("assignment_ids", "signature_ids", "interval_ids")
            )
            for key, value in lanes.items()
        },
        "selection_guidance": _nilm_selection_guidance(),
        "actions": {
            "label_interval": _nilm_label_interval_action(config),
        },
        "edges": [_nilm_edge_payload(edge) for edge in recent_edges],
        "edge_count": len(edges),
        "sessions": sessions,
        "session_count": len(all_sessions),
    }


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
    return {
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
    return {
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
        "mark_expected": {
            "domain": DOMAIN,
            "service": SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
            "data": dict(data),
        },
        "merge": merge_action,
    }


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
    if "typical_watts" in signature:
        payload["typical_power_w"] = signature["typical_watts"]
    payload["why_grouped"] = _nilm_signature_explanation(signature)
    review_state = _nilm_review_state(signature)
    if review_state:
        payload["review_state"] = review_state
    return payload


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
    if signature.get("expected"):
        return "expected"
    if signature.get("merged_into"):
        return "merged"
    if str(signature.get("user_label") or "").strip():
        return "labeled"
    return None


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
) -> tuple[Any, Any] | None:
    requested_circuit_id = str(circuit_id or "").strip()
    requested_entry_id = str(entry_id or "").strip()
    sensor_fallback: tuple[Any, Any] | None = None
    for coordinator in coordinators:
        if (
            requested_entry_id
            and str(getattr(coordinator, "entry_id", "") or "") != requested_entry_id
        ):
            continue
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            config_circuit_id = str(getattr(config, "circuit_id", "") or "").strip()
            if not config_circuit_id:
                continue
            if requested_circuit_id and config_circuit_id != requested_circuit_id:
                continue
            if _is_explicit_nilm_config(config):
                return coordinator, config
            if sensor_fallback is None and _is_sensor_backed_mains_config(config):
                sensor_fallback = (coordinator, config)
    return sensor_fallback


def _is_explicit_nilm_config(config: Any) -> bool:
    mode = getattr(config, "mode", None)
    appliance_profile = getattr(config, "appliance_profile", None)
    return (
        mode is CircuitMode.MAINS_NILM
        or appliance_profile is ApplianceProfile.MAINS_NILM
        or str(mode) == CircuitMode.MAINS_NILM.value
        or str(appliance_profile) == ApplianceProfile.MAINS_NILM.value
    )


def _is_sensor_backed_mains_config(config: Any) -> bool:
    return (
        str(getattr(config, "circuit_id", "") or "").strip() == "mains"
        or getattr(config, "mode", None) is CircuitMode.MIXED
        or getattr(config, "appliance_profile", None) is ApplianceProfile.MIXED
    ) and bool(_sensor_entity_ids(config))


def _nilm_workspace_signatures(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    return [
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
            ),
        }
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


def _nilm_label_interval_action(config: CircuitConfig) -> dict[str, Any]:
    data = {ATTR_CIRCUIT_ID: config.circuit_id}
    entity_ids = _sensor_entity_ids(config)
    if entity_ids:
        data[ATTR_MAINS_ENTITY_ID] = entity_ids[0]
    return {
        "domain": DOMAIN,
        "service": SERVICE_LABEL_NILM_INTERVAL,
        "data": data,
        "requires": [ATTR_START, ATTR_END, ATTR_LABEL, ATTR_APPLIANCE_PROFILE],
        "profile_options": _nilm_appliance_profile_options(),
    }


def _nilm_sensor_label_interval_action(
    config: CircuitConfig,
    known_load_overlays: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    action = _nilm_label_interval_action(config)
    action["service"] = SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS
    action["requires"] = [
        ATTR_START,
        ATTR_END,
        ATTR_LABEL,
        ATTR_GROUND_TRUTH_ENTITY_ID,
    ]
    ground_truth_options = []
    seen_circuits: set[str] = set()
    for overlay in known_load_overlays:
        label = str(overlay.get("name") or overlay.get("circuit_id") or "").strip()
        circuit_id = str(overlay.get("circuit_id") or "").strip()
        entity_text = next(
            (
                str(entity_id or "").strip()
                for entity_id in _iter_items(overlay.get("entity_ids"))
                if str(entity_id or "").strip()
            ),
            "",
        )
        key = circuit_id or entity_text
        if not key or key in seen_circuits or not entity_text:
            continue
        seen_circuits.add(key)
        ground_truth_options.append(
            {"value": entity_text, "label": label or entity_text},
        )
    if ground_truth_options:
        action["ground_truth_options"] = ground_truth_options
    return action


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
    direct_circuit_options = _nilm_direct_circuit_options(
        coordinator,
        circuit_id,
    )
    return [
        _nilm_assignment_payload(
            circuit_id,
            item,
            assignments,
            label_intervals=label_intervals,
            direct_circuit_options=direct_circuit_options,
        )
        for item in assignments
    ]


def _nilm_assignment_options(
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if (
            not assignment_id
            or str(assignment.get("lifecycle_state") or "").lower() == "retired"
        ):
            continue
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment_id,
        ).strip()
        options.append({"value": assignment_id, "label": label})
    return options


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


def _nilm_assignment_payload(
    circuit_id: str,
    assignment: Mapping[str, Any],
    assignments: Iterable[Mapping[str, Any]] = (),
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
    direct_circuit_options: Iterable[Mapping[str, str]] = (),
) -> dict[str, Any]:
    payload = {str(key): value for key, value in assignment.items() if key != "actions"}
    assignment_id = str(payload.get(ATTR_ASSIGNMENT_ID) or "").strip()
    if not assignment_id:
        return payload

    payload["appliance_detail_path"] = _nilm_appliance_detail_panel_path(assignment_id)
    state = str(payload.get("lifecycle_state") or "").strip().lower()
    action_data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_ASSIGNMENT_ID: assignment_id}
    actions: dict[str, dict[str, Any]] = {}
    if state != "retired":
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
        direct_options = [dict(option) for option in direct_circuit_options]
        if direct_options and payload.get("conversion_state") != "direct_meter":
            actions["convert_to_direct_meter"] = {
                "domain": DOMAIN,
                "service": SERVICE_CONVERT_NILM_APPLIANCE_TO_DIRECT_METER,
                "data": dict(action_data),
                "requires": ["direct_circuit_id"],
                "target_options": direct_options,
            }
        if _nilm_assignment_has_ground_truth_intervals(payload, label_intervals):
            actions["validate_history"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
                "data": dict(action_data),
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
        elif (
            state not in {"expected", "ignored"}
            and payload.get("conversion_state") != "direct_meter"
        ):
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
    if actions:
        payload["actions"] = actions
    return payload


def _nilm_direct_circuit_options(
    coordinator: Any,
    mains_circuit_id: str,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if not isinstance(config, CircuitConfig):
            continue
        if (
            config.circuit_id == mains_circuit_id
            or config.mode
            in {
                CircuitMode.MAINS_NILM,
                CircuitMode.MIXED,
            }
            or config.appliance_profile
            in {
                ApplianceProfile.MAINS_NILM,
                ApplianceProfile.MIXED,
                ApplianceProfile.SOLAR_INVERTER,
            }
        ):
            continue
        options.append({"value": config.circuit_id, "label": config.name})
    return options


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
) -> list[dict[str, Any]]:
    reference_date = _nilm_workspace_reference_date(edges, sessions)
    virtual_appliances = []
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        if not assignment_id:
            continue
        assignment_session_ids = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("session_ids"))
            if str(value or "").strip()
        }
        assignment_sessions = [
            session
            for session in sessions
            if session.get("assignment_id") == assignment_id
            or str(session.get("session_id") or "").strip() in assignment_session_ids
        ]
        open_session = _latest_nilm_session(
            session for session in assignment_sessions if not session.get("end")
        )
        latest_session = open_session or _latest_nilm_session(assignment_sessions)
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
                "is_running": open_session is not None,
                "estimated_power_w": (
                    _round_float(open_session.get("median_power_w"))
                    if open_session
                    else 0.0
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
                    str(open_session.get("signature_fingerprint") or "")
                    if open_session
                    else None
                ),
                "active_session_id": (
                    str(open_session.get("session_id") or "") if open_session else None
                ),
                "model_status": str(assignment.get("lifecycle_state") or "candidate"),
                "source_type": "nilm_estimate",
                "source_label": _panel_text("source_labels", "nilm_estimate"),
                "estimated": True,
                "mains_circuit_id": str(assignment.get("mains_circuit_id") or ""),
                "appliance_detail_api_path": (
                    f"{APPLIANCE_DETAIL_API_PATH}?"
                    f"{urlencode({ATTR_ASSIGNMENT_ID: assignment_id})}"
                ),
                "appliance_detail_path": _nilm_appliance_detail_panel_path(
                    assignment_id
                ),
            }
        )
    return virtual_appliances


def _nilm_appliance_detail_panel_path(assignment_id: str) -> str:
    return (
        f"/{PANEL_URL_PATH}?"
        f"{urlencode({ATTR_ASSIGNMENT_ID: assignment_id, 'appliance_detail': '1'})}"
    )


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
) -> dict[str, dict[str, Any]]:
    lanes = {
        "needs_review": _nilm_lane("Needs Review"),
        "assigned": _nilm_lane("Assigned"),
        "published": _nilm_lane("Published"),
        "ignored_expected": _nilm_lane("Ignored / Expected"),
    }
    assigned_signature_ids = _nilm_assigned_signature_ids(assignments)
    for signature in signatures:
        signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
        if not signature_id:
            continue
        if _nilm_signature_hidden(signature):
            lanes["ignored_expected"]["signature_ids"].append(signature_id)
        elif _nilm_signature_identifiers(signature).isdisjoint(
            assigned_signature_ids,
        ):
            lanes["needs_review"]["signature_ids"].append(signature_id)

    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        state = str(assignment.get("lifecycle_state") or "").strip().lower()
        confidence = _clamped_float(assignment.get("confidence"), default=0.0)
        if _nilm_assignment_hidden(assignment):
            lane = "ignored_expected"
        elif assignment.get("publish_entities") is True or state == "published":
            lane = "published"
        elif (
            state
            in {
                "needs_validation",
                "conflict",
                "low_confidence",
                "validated",
                "ready_to_publish",
            }
            or confidence < 0.8
        ):
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
    return lanes


def _nilm_lane(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "assignment_ids": [],
        "signature_ids": [],
        "interval_ids": [],
    }


def _nilm_assignment_hidden(assignment: Mapping[str, Any]) -> bool:
    return str(assignment.get("lifecycle_state") or "").strip().lower() in {
        "ignored",
        "expected",
        "retired",
    }


def _nilm_signature_hidden(signature: Mapping[str, Any]) -> bool:
    state = str(signature.get("review_state") or "").strip().lower()
    return bool(
        signature.get("ignored")
        or signature.get("expected")
        or state in {"ignored", "expected", "merged"}
    )


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
    _target_coordinator, config = target
    query = urlencode({"circuit_id": config.circuit_id})
    return {
        "workspace_api_path": f"{NILM_WORKSPACE_API_PATH}?{query}",
        "workspace_call_api_path": f"{DOMAIN}/nilm_workspace?{query}",
    }


def _nilm_known_load_overlays(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    circuit_registry = getattr(coordinator, "circuit_registry", None)
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
    entry_id: str | None = None,
) -> dict[str, Any]:
    requested_hours = _bounded_float(
        hours,
        default=DEFAULT_NILM_WORKSPACE_HISTORY_HOURS,
        upper=MAX_NILM_WORKSPACE_HISTORY_HOURS,
    )
    end = datetime.now(UTC)
    start = end - timedelta(hours=requested_hours)
    entities = _nilm_workspace_history_entities(
        config,
        known_load_overlays,
        solar_overlays,
    )
    history_query_values = {
        "circuit_id": config.circuit_id,
        "hours": str(requested_hours),
    }
    if entry_id:
        history_query_values[ATTR_ENTRY_ID] = entry_id
    history_query = urlencode(history_query_values)
    recorder_query = urlencode(
        {
            "filter_entity_id": ",".join(entities),
            "end_time": end.isoformat(),
            "minimal_response": "1",
            "no_attributes": "1",
        }
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "hours": requested_hours,
        "max_hours": MAX_NILM_WORKSPACE_HISTORY_HOURS,
        "entities": entities,
        "entity_count": len(entities),
        "max_entities": MAX_NILM_WORKSPACE_HISTORY_ENTITIES,
        "api_path": f"{DOMAIN}/nilm_workspace_history?{history_query}",
        "fetch_path": f"{NILM_WORKSPACE_HISTORY_API_PATH}?{history_query}",
        "recorder_api_path": (
            f"history/period/{quote(start.isoformat(), safe='')}?{recorder_query}"
        ),
        "max_points_per_entity": MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY,
    }


def _nilm_workspace_history_entities(
    config: CircuitConfig,
    _known_load_overlays: list[dict[str, Any]],
    _solar_overlays: list[dict[str, Any]],
) -> list[str]:
    sensors = tuple(getattr(config, "sensors", ()) or ())
    real_power_ids = _unique_strings(
        sensor.entity_id
        for sensor in sensors
        if getattr(sensor, "role", None) == SensorRole.REAL_POWER
        and getattr(sensor, "entity_id", None)
    )
    if real_power_ids or any(getattr(sensor, "role", None) for sensor in sensors):
        return real_power_ids[:MAX_NILM_WORKSPACE_HISTORY_ENTITIES]
    return _sensor_entity_ids(config)[:MAX_NILM_WORKSPACE_HISTORY_ENTITIES]


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
        fingerprints = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("signature_fingerprints"))
            if str(value or "").strip()
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
            and not _nilm_signature_hidden(signature)
            and fingerprint not in hidden_fingerprints
            and fingerprint not in seen_fingerprints
            and key not in seen
        ):
            specs.append(key)
            seen.add(key)
    if specs or signatures or assignments:
        return specs
    return [(_nilm_workspace_signature_fingerprint(signatures), None)]


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
        for field in ("signature_fingerprints", "session_ids"):
            for value in _iter_items(assignment.get(field)):
                key = str(value or "").strip()
                if key:
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
    if session_id and circuit_id:
        data = {
            ATTR_CIRCUIT_ID: circuit_id,
            ATTR_SESSION_ID: session_id,
        }
        signature_fingerprint = str(payload.get("signature_fingerprint") or "").strip()
        if signature_fingerprint:
            data[ATTR_SIGNATURE_FINGERPRINT] = signature_fingerprint
        payload["actions"] = {
            "assign": {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
                "data": data,
                "requires": [ATTR_LABEL],
            }
        }
        assignment_id = str(payload.get("assignment_id") or "").strip()
        if assignment_id and (
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
            payload["actions"]["validate"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_SESSION,
                "data": dict(action_data),
            }
            payload["actions"]["reject"] = {
                "domain": DOMAIN,
                "service": SERVICE_REJECT_NILM_SESSION,
                "data": dict(action_data),
            }
    return payload


def _nilm_workspace_signature_fingerprint(signatures: list[dict[str, Any]]) -> str:
    for signature in signatures:
        signature_id = _nilm_signature_session_fingerprint(signature)
        if signature_id:
            return signature_id
    return "unassigned"


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
