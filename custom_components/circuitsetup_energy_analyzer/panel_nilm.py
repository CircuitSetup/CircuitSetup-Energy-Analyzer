"""NILM panel payload builders and bounded workspace contracts."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from secrets import token_bytes
from statistics import fmean, median
from types import SimpleNamespace
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
    evaluate_nilm_validation_readiness,
    nilm_display_name,
    nilm_session_to_dict,
    nilm_signature_is_assignable,
    pair_nilm_sessions_for_signatures,
    resolve_nilm_signature_fingerprint,
)
from .nilm_interval_evidence import NilmReferenceExtractionSettings
from .nilm_load_identification import MIN_CONFIDENCE, MIN_OCCURRENCES
from .nilm_validation import (
    match_nilm_validation_intervals,
    nilm_validation_interval_id,
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
    NILM_WORKSPACE_COLLECTION_API_PATH,
    NILM_WORKSPACE_HISTORY_API_PATH,
    PANEL_URL_PATH,
)
from .processors.nilm_sample import (
    ensure_nilm_tracked_collection,
    nilm_tracked_collection_revision,
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
    "evidence_strength",
    "model_fit",
    "validated_precision",
    "confidence_kind",
    "confidence_semantics_version",
    "first_seen",
    "last_seen",
    "voltage_class",
    "dominant_leg",
    "known_load_overlap",
    "running_state",
    "current_runtime_minutes",
    "runtime_today_minutes",
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
    "energy_source",
    "power_coverage",
    "covered_duration_seconds",
    "longest_trace_gap_seconds",
    "trace_point_cap_truncated",
    "session_history_truncated",
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
MAX_NILM_WORKSPACE_KNOWN_LOAD_ATTRIBUTIONS = 20
MAX_NILM_AMBIGUITY_AUDIT_GROUP_PREVIEW = 3
DEFAULT_NILM_WORKSPACE_COLLECTION_LIMIT = 20
MAX_NILM_WORKSPACE_COLLECTION_LIMIT = 50
MAX_NILM_AMBIGUITY_CANDIDATE_EXPLANATIONS = 3
_NILM_AMBIGUITY_CURSOR_VERSION = "v1"
_NILM_AMBIGUITY_CURSOR_SECRET = token_bytes(32)
_NILM_AMBIGUITY_COLLECTION_VIEWS = frozenset({"occurrences", "groups"})
_NILM_AMBIGUITY_CANDIDATE_KINDS = frozenset(
    {"assignment", "signature", "stop_boundary"}
)
_NILM_AMBIGUITY_REASON_CODES = frozenset(
    {
        "assignment_candidate_conflict",
        "signature_candidate_conflict",
        "stop_boundary_conflict",
    }
)
_NILM_WORKSPACE_GENERIC_COLLECTIONS = frozenset(
    {
        "sessions",
        "label_intervals",
        "assignments",
        "signatures",
        "known_load_attributions",
    }
)
_NILM_WORKSPACE_ITEM_KINDS = frozenset(
    {
        "session",
        "ambiguous_session",
        "label_interval",
        "assignment",
        "signature",
        "known_load_attribution",
    }
)
_NILM_WORKSPACE_ITEM_SOURCES = {
    "session": ("sessions", "session_id"),
    "ambiguous_session": ("ambiguous_sessions", "session_id"),
    "label_interval": ("label_intervals", ATTR_INTERVAL_ID),
    "assignment": ("assignments", ATTR_ASSIGNMENT_ID),
    "signature": ("signatures", ATTR_SIGNATURE_ID),
    "known_load_attribution": ("known_load_attributions", "attribution_id"),
}
_NILM_ESTIMATE_QUALITY_WINDOWS = (
    ("today", "runtime_today_minutes", "estimated_energy_today_kwh"),
    ("7_days", "runtime_7_days_minutes", "estimated_energy_7_days_kwh"),
    ("30_days", "runtime_30_days_minutes", "estimated_energy_30_days_kwh"),
)


def _nilm_workspace_snapshot_value(value: Any) -> Any:
    """Detach tracked runtime values into plain immutable-worker inputs."""

    if isinstance(value, Mapping):
        return {
            key: _nilm_workspace_snapshot_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_nilm_workspace_snapshot_value(item) for item in value]
    return deepcopy(value)


def _nilm_workspace_read_snapshot(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None,
    entry_id: str | None,
) -> tuple[Any, ...]:
    """Capture bounded detached inputs for an executor-backed workspace read."""

    target = _nilm_workspace_target(tuple(coordinators), circuit_id, entry_id=entry_id)
    if target is None:
        return ()
    coordinator, config, _sources = target
    selected_circuit_id = config.circuit_id
    store = getattr(coordinator, "store_data", None)

    def circuit_mapping(name: str) -> dict[str, Any]:
        value = getattr(store, name, {})
        if not isinstance(value, Mapping):
            return {}
        return {
            selected_circuit_id: _nilm_workspace_snapshot_value(
                value.get(selected_circuit_id, [])
            )
        }

    assignments_by_circuit = getattr(
        store, "nilm_appliance_assignments_by_circuit", {}
    )
    configured_circuit_ids = {
        str(getattr(item, "circuit_id", "") or "")
        for item in getattr(coordinator, "circuit_configs", ()) or ()
        if str(getattr(item, "circuit_id", "") or "")
    }
    snapshot_assignments = (
        {
            key: _nilm_workspace_snapshot_value(value)
            for key, value in assignments_by_circuit.items()
            if key in configured_circuit_ids
        }
        if isinstance(assignments_by_circuit, Mapping)
        else {}
    )
    assignment_rows = (
        assignments_by_circuit.get(selected_circuit_id, ())
        if isinstance(assignments_by_circuit, Mapping)
        else ()
    )
    reference_ids = {
        str(item.get(field) or "").strip()
        for item in _iter_items(assignment_rows)
        if isinstance(item, Mapping)
        for field in ("reference_state_entity_id", "reference_power_entity_id")
        if str(item.get(field) or "").strip()
    }
    live_states = getattr(getattr(coordinator, "hass", None), "states", None)
    get_state = getattr(live_states, "get", None)
    state_rows: dict[str, Any] = {}
    if callable(get_state):
        for entity_id in reference_ids:
            if (row := get_state(entity_id)) is not None:
                state_rows[entity_id] = deepcopy(row)
    snapshot_states = SimpleNamespace(
        get=lambda entity_id, rows=state_rows: rows.get(entity_id)
    )
    snapshot_store = SimpleNamespace(
        nilm_signatures=circuit_mapping("nilm_signatures"),
        nilm_session_history_by_circuit=circuit_mapping(
            "nilm_session_history_by_circuit"
        ),
        nilm_label_intervals_by_circuit=circuit_mapping(
            "nilm_label_intervals_by_circuit"
        ),
        nilm_appliance_assignments_by_circuit=snapshot_assignments,
        nilm_known_load_attributions_by_circuit=circuit_mapping(
            "nilm_known_load_attributions_by_circuit"
        ),
    )
    inventory = getattr(
        getattr(coordinator, "state", None), "nilm_unknown_loads_by_circuit", {}
    )
    snapshot_state = SimpleNamespace(
        nilm_unknown_loads_by_circuit={
            selected_circuit_id: _nilm_workspace_snapshot_value(
                inventory.get(selected_circuit_id, {})
            )
        }
        if isinstance(inventory, Mapping)
        else {}
    )
    return (
        SimpleNamespace(
            entry_id=str(getattr(coordinator, "entry_id", "") or ""),
            circuit_configs=deepcopy(
                tuple(getattr(coordinator, "circuit_configs", ()) or ())
            ),
            store_data=snapshot_store,
            state=snapshot_state,
            _nilm_unmatched_edges={
                selected_circuit_id: _nilm_workspace_snapshot_value(
                    getattr(coordinator, "_nilm_unmatched_edges", {}).get(
                        selected_circuit_id, ()
                    )
                )
            },
            hass=SimpleNamespace(states=snapshot_states),
            _nilm_reference_options_snapshot=deepcopy(
                _nilm_reference_options(coordinator)
            ),
        ),
    )


def _nilm_workspace_prepare_revision_sources(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None,
    entry_id: str | None,
) -> None:
    """Install Task 2 exact mutation tracking on every retained read source."""

    target = _nilm_workspace_target(tuple(coordinators), circuit_id, entry_id=entry_id)
    if target is None:
        return
    coordinator, config, _sources = target
    selected_circuit_id = config.circuit_id
    store = getattr(coordinator, "store_data", None)
    for name in (
        "nilm_signatures",
        "nilm_session_history_by_circuit",
        "nilm_label_intervals_by_circuit",
        "nilm_known_load_attributions_by_circuit",
    ):
        ensure_nilm_tracked_collection(getattr(store, name, None), selected_circuit_id)
    assignments = getattr(store, "nilm_appliance_assignments_by_circuit", None)
    for item in getattr(coordinator, "circuit_configs", ()) or ():
        configured_id = str(getattr(item, "circuit_id", "") or "")
        if configured_id:
            ensure_nilm_tracked_collection(assignments, configured_id)
    inventory = getattr(
        getattr(coordinator, "state", None), "nilm_unknown_loads_by_circuit", None
    )
    selected_inventory = (
        inventory.get(selected_circuit_id) if isinstance(inventory, Mapping) else None
    )
    if isinstance(selected_inventory, Mapping):
        ensure_nilm_tracked_collection(selected_inventory, "unknown_loads")
    ensure_nilm_tracked_collection(
        getattr(coordinator, "_nilm_unmatched_edges", None), selected_circuit_id
    )


def _nilm_workspace_read_identity(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None,
    entry_id: str | None,
) -> tuple[Any, ...]:
    """Return an O(1) identity token for selected live NILM read inputs."""

    target = _nilm_workspace_target(tuple(coordinators), circuit_id, entry_id=entry_id)
    if target is None:
        return ("not_found",)
    coordinator, config, _sources = target
    selected_circuit_id = config.circuit_id
    store = getattr(coordinator, "store_data", None)

    def marker(value: Any) -> tuple[int, int, int | None]:
        if isinstance(value, Mapping):
            selected = value.get(selected_circuit_id)
        else:
            selected = None
        return (
            id(value),
            id(selected),
            nilm_tracked_collection_revision(selected),
        )

    assignments = getattr(store, "nilm_appliance_assignments_by_circuit", None)
    configured_ids = tuple(
        str(getattr(item, "circuit_id", "") or "")
        for item in getattr(coordinator, "circuit_configs", ()) or ()
        if str(getattr(item, "circuit_id", "") or "")
    )
    assignment_markers = tuple(
        (
            configured_id,
            id(rows),
            nilm_tracked_collection_revision(rows),
        )
        for configured_id in configured_ids
        for rows in (
            assignments.get(configured_id)
            if isinstance(assignments, Mapping)
            else None,
        )
    )
    selected_assignments = (
        assignments.get(selected_circuit_id, ())
        if isinstance(assignments, Mapping)
        else ()
    )
    live_states = getattr(getattr(coordinator, "hass", None), "states", None)
    get_state = getattr(live_states, "get", None)
    reference_state_markers = tuple(
        (
            entity_id,
            id(row),
            getattr(row, "state", None),
            getattr(row, "last_updated", None),
        )
        for item in _iter_items(selected_assignments)
        if isinstance(item, Mapping)
        for field in ("reference_state_entity_id", "reference_power_entity_id")
        if (entity_id := str(item.get(field) or "").strip())
        for row in (get_state(entity_id) if callable(get_state) else None,)
    )
    state = getattr(coordinator, "state", None)
    inventory = getattr(state, "nilm_unknown_loads_by_circuit", None)
    selected_inventory = (
        inventory.get(selected_circuit_id) if isinstance(inventory, Mapping) else None
    )
    unknown_loads = (
        selected_inventory.get("unknown_loads")
        if isinstance(selected_inventory, Mapping)
        else None
    )
    return (
        id(coordinator),
        id(getattr(coordinator, "data", None)),
        id(getattr(coordinator, "circuit_configs", None)),
        marker(getattr(store, "nilm_signatures", None)),
        marker(getattr(store, "nilm_session_history_by_circuit", None)),
        marker(getattr(store, "nilm_label_intervals_by_circuit", None)),
        marker(getattr(store, "nilm_appliance_assignments_by_circuit", None)),
        marker(getattr(store, "nilm_known_load_attributions_by_circuit", None)),
        marker(getattr(state, "nilm_unknown_loads_by_circuit", None)),
        marker(getattr(coordinator, "_nilm_unmatched_edges", None)),
        assignment_markers,
        (
            id(selected_inventory),
            id(unknown_loads),
            nilm_tracked_collection_revision(unknown_loads),
        ),
        reference_state_markers,
    )


async def _async_nilm_workspace_read(
    hass: Any,
    coordinators: Iterable[Any],
    builder: Any,
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Retry executor reads until their event-loop source identity is current."""

    live_coordinators = tuple(coordinators)
    identity_kwargs = {
        "circuit_id": kwargs.get("circuit_id"),
        "entry_id": kwargs.get("entry_id"),
    }
    while True:
        _nilm_workspace_prepare_revision_sources(
            live_coordinators, **identity_kwargs
        )
        identity = _nilm_workspace_read_identity(
            live_coordinators, **identity_kwargs
        )
        snapshot = _nilm_workspace_read_snapshot(
            live_coordinators, **identity_kwargs
        )
        if identity != _nilm_workspace_read_identity(
            live_coordinators, **identity_kwargs
        ):
            continue
        payload = await hass.async_add_executor_job(
            partial(builder, snapshot, **kwargs)
        )
        if identity == _nilm_workspace_read_identity(
            live_coordinators, **identity_kwargs
        ):
            return payload


async def async_nilm_workspace_collection_payload(
    hass: Any,
    coordinators: Iterable[Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a collection payload from an event-loop-captured snapshot."""

    return await _async_nilm_workspace_read(
        hass, coordinators, nilm_workspace_collection_payload, kwargs
    )


async def async_nilm_workspace_item_payload(
    hass: Any,
    coordinators: Iterable[Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build an exact-item payload from an event-loop-captured snapshot."""

    return await _async_nilm_workspace_read(
        hass, coordinators, nilm_workspace_item_payload, kwargs
    )


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
    merged_sessions = _merge_nilm_session_payloads(
        all_generated_sessions,
        stored_sessions,
    )
    all_sessions = _nilm_workspace_visible_sessions(
        merged_sessions,
        signatures,
        assignments,
    )
    ambiguity_audit = _nilm_workspace_ambiguity_audit_summary(
        _nilm_workspace_ambiguous_sessions(
            merged_sessions,
            signatures,
            assignments,
        ),
        session_display_labels,
        circuit_id=config.circuit_id,
        entry_id=selected_entry_id,
    )
    all_sessions = _add_nilm_session_display_labels(
        all_sessions,
        session_display_labels,
    )
    _add_nilm_component_occurrences(signatures, all_sessions)
    _add_nilm_assignment_options(signatures, assignment_options)
    label_intervals, label_interval_meta = _nilm_workspace_collection_metadata(
        "label_intervals",
        all_label_intervals,
        limit=MAX_NILM_WORKSPACE_LABEL_INTERVALS,
        circuit_id=config.circuit_id,
        entry_id=selected_entry_id,
    )
    _add_nilm_assignment_options(label_intervals, assignment_options)
    _add_nilm_assignment_options(all_sessions, assignment_options)
    _add_nilm_session_signature_reviews(all_sessions, signatures)
    sessions, session_meta = _nilm_workspace_collection_metadata(
        "sessions",
        all_sessions,
        limit=MAX_NILM_WORKSPACE_SESSIONS,
        circuit_id=config.circuit_id,
        entry_id=selected_entry_id,
    )
    all_known_load_attributions = _nilm_known_load_attributions_for_circuit(
        coordinator,
        config.circuit_id,
    )
    known_load_attributions, attribution_meta = (
        _nilm_workspace_collection_metadata(
            "known_load_attributions",
            all_known_load_attributions,
            limit=MAX_NILM_WORKSPACE_KNOWN_LOAD_ATTRIBUTIONS,
            circuit_id=config.circuit_id,
            entry_id=selected_entry_id,
        )
    )
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
        "label_interval_count": len(all_label_intervals),
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
        "known_load_attributions": known_load_attributions,
        "collection_meta": {
            "sessions": session_meta,
            "label_intervals": label_interval_meta,
            "known_load_attributions": attribution_meta,
            "ambiguous_sessions": {
                "total_count": (
                    int(ambiguity_audit["total_count"])
                    if ambiguity_audit is not None
                    else 0
                ),
                "returned_count": 0,
                "truncated": ambiguity_audit is not None,
                "next_cursor": None,
            },
        },
    }
    if ambiguity_audit is not None:
        payload["ambiguity_audit"] = ambiguity_audit
    if configured_primary is not None:
        payload["configured_primary"] = configured_primary
    return _scope_nilm_actions(payload, selected_entry_id)


def nilm_workspace_collection_payload(
    coordinators: Iterable[Any],
    *,
    collection: str | None = None,
    circuit_id: str | None = None,
    entry_id: str | None = None,
    group_id: str | None = None,
    cursor: str | None = None,
    limit: Any = None,
    view: str | None = None,
) -> dict[str, Any]:
    """Return one explicitly whitelisted, read-only NILM audit collection."""

    if collection in _NILM_WORKSPACE_GENERIC_COLLECTIONS:
        return _nilm_workspace_generic_collection_payload(
            coordinators,
            collection=str(collection),
            circuit_id=circuit_id,
            entry_id=entry_id,
            cursor=cursor,
            limit=limit,
            group_id=group_id,
            view=view,
        )
    if collection != "ambiguous_sessions":
        return {
            "status": "invalid_collection",
            "items": [],
            "total_count": 0,
            "returned_count": 0,
            "truncated": False,
            "next_cursor": None,
        }
    target = _nilm_workspace_target(
        tuple(coordinators),
        circuit_id,
        entry_id=entry_id,
    )
    if target is None:
        return {
            "status": "not_found",
            "items": [],
            "total_count": 0,
            "returned_count": 0,
            "truncated": False,
            "next_cursor": None,
        }

    coordinator, config, _sources = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    signatures = _nilm_workspace_signatures(
        coordinator,
        config.circuit_id,
        config=config,
    )
    all_label_intervals = _nilm_label_intervals_for_circuit(
        coordinator,
        config.circuit_id,
        limit=None,
    )
    assignments = _nilm_assignments_for_circuit(
        coordinator,
        config.circuit_id,
        label_intervals=all_label_intervals,
    )
    reviewed_session_ids = _nilm_reviewed_session_ids_by_assignment(assignments)
    sessions = _nilm_workspace_ambiguous_sessions(
        _merge_nilm_session_payloads(
            _nilm_workspace_sessions(
                _nilm_edges_for_circuit(coordinator, config.circuit_id),
                config.circuit_id,
                signatures=signatures,
                assignments=assignments,
                reviewed_session_ids=reviewed_session_ids,
                limit=None,
            ),
            _nilm_session_history_for_circuit(
                coordinator,
                config.circuit_id,
                reviewed_session_ids=reviewed_session_ids,
            ),
        ),
        signatures,
        assignments,
    )
    session_labels = _nilm_session_display_labels(signatures, assignments)
    normalized_view = str(view or "occurrences").strip().lower()
    if normalized_view not in _NILM_AMBIGUITY_COLLECTION_VIEWS:
        return {
            "status": "invalid_view",
            "items": [],
            "groups": [],
            "total_count": 0,
            "returned_count": 0,
            "truncated": False,
            "next_cursor": None,
        }
    page_limit = _nilm_workspace_collection_limit(limit)
    if normalized_view == "groups":
        if group_id is not None:
            return {
                "status": "invalid_scope",
                "items": [],
                "groups": [],
                "total_count": 0,
                "returned_count": 0,
                "truncated": False,
                "next_cursor": None,
            }
        groups = _nilm_workspace_ambiguity_groups(
            sessions,
            session_labels,
            circuit_id=config.circuit_id,
        )
        total_count = len(groups)
        cursor_key = _nilm_ambiguity_group_collection_cursor_key(
            cursor,
            circuit_id=config.circuit_id,
            entry_id=selected_entry_id,
        )
        if cursor is not None and cursor_key is None:
            return {
                "status": "invalid_cursor",
                "items": [],
                "groups": [],
                "total_count": total_count,
                "returned_count": 0,
                "truncated": False,
                "next_cursor": None,
            }
        if cursor_key is not None:
            groups = [
                group
                for group in groups
                if _nilm_ambiguity_group_sort_key(group) > cursor_key
            ]
        page = groups[:page_limit]
        truncated = len(groups) > len(page)
        return {
            "status": "ok",
            "items": [],
            "groups": page,
            "total_count": total_count,
            "returned_count": len(page),
            "truncated": truncated,
            "next_cursor": (
                _nilm_ambiguity_group_collection_cursor(
                    page[-1],
                    circuit_id=config.circuit_id,
                    entry_id=selected_entry_id,
                )
                if truncated and page
                else None
            ),
        }
    normalized_group_id = _nilm_ambiguity_text(group_id)
    if group_id is not None and normalized_group_id is None:
        sessions = []
    elif normalized_group_id:
        sessions = [
            session
            for session in sessions
            if _nilm_session_ambiguity_group_id(session, config.circuit_id)
            == normalized_group_id
        ]
    ordered = sorted(sessions, key=_nilm_ambiguity_session_sort_key)
    total_count = len(ordered)
    cursor_key = _nilm_ambiguity_collection_cursor_key(
        cursor,
        circuit_id=config.circuit_id,
        entry_id=selected_entry_id,
        group_id=normalized_group_id,
    )
    if cursor is not None and cursor_key is None:
        return {
            "status": "invalid_cursor",
            "items": [],
            "total_count": len(ordered),
            "returned_count": 0,
            "truncated": False,
            "next_cursor": None,
        }
    if cursor_key is not None:
        ordered = [
            session
            for session in ordered
            if _nilm_ambiguity_session_sort_key(session) > cursor_key
        ]
    page = ordered[:page_limit]
    truncated = len(ordered) > len(page)
    return {
        "status": "ok",
        "items": [
            _nilm_ambiguity_audit_item(
                session,
                session_labels,
                circuit_id=config.circuit_id,
            )
            for session in page
        ],
        "total_count": total_count,
        "returned_count": len(page),
        "truncated": truncated,
        "next_cursor": (
            _nilm_ambiguity_collection_cursor(
                page[-1],
                circuit_id=config.circuit_id,
                entry_id=selected_entry_id,
                group_id=normalized_group_id,
            )
            if truncated and page
            else None
        ),
    }


def _nilm_workspace_generic_collection_payload(
    coordinators: Iterable[Any],
    *,
    collection: str,
    circuit_id: str | None,
    entry_id: str | None,
    cursor: str | None,
    limit: Any,
    group_id: str | None,
    view: str | None,
) -> dict[str, Any]:
    """Return one non-ambiguous bounded workspace collection page."""

    if group_id is not None or view is not None:
        return _nilm_workspace_collection_error("invalid_scope")
    page_limit = _nilm_workspace_generic_collection_limit(limit)
    if page_limit is None:
        return _nilm_workspace_collection_error("invalid_limit")
    target = _nilm_workspace_target(
        tuple(coordinators), circuit_id, entry_id=entry_id
    )
    if target is None:
        return _nilm_workspace_collection_error("not_found")
    coordinator, config, _sources = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    items = _NilmWorkspaceReadSource(coordinator, config).collection(collection)
    ordered = _nilm_workspace_ordered_collection(collection, items)
    total_count = len(ordered)
    cursor_key = _nilm_workspace_generic_collection_cursor_key(
        cursor,
        collection=collection,
        circuit_id=config.circuit_id,
        entry_id=selected_entry_id,
    )
    if cursor is not None and cursor_key is None:
        return _nilm_workspace_collection_error(
            "invalid_cursor", total_count=total_count
        )
    if cursor_key is not None:
        ordered = [
            item
            for item in ordered
            if _nilm_workspace_collection_sort_key(collection, item) > cursor_key
        ]
    page = ordered[:page_limit]
    truncated = len(ordered) > len(page)
    return _scope_nilm_actions(
        {
            "status": "ok",
            "collection": collection,
            "items": page,
            "total_count": total_count,
            "returned_count": len(page),
            "truncated": truncated,
            "next_cursor": (
                _nilm_workspace_generic_collection_cursor(
                    collection,
                    page[-1],
                    circuit_id=config.circuit_id,
                    entry_id=selected_entry_id,
                )
                if truncated and page
                else None
            ),
        },
        selected_entry_id,
    )


def _nilm_workspace_collection_error(
    status: str,
    *,
    total_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "items": [],
        "total_count": total_count,
        "returned_count": 0,
        "truncated": False,
        "next_cursor": None,
    }


def _nilm_workspace_generic_collection_limit(value: Any) -> int | None:
    if value is None:
        return DEFAULT_NILM_WORKSPACE_COLLECTION_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return min(parsed, MAX_NILM_WORKSPACE_COLLECTION_LIMIT)


class _NilmWorkspaceReadSource:
    """Request-local, lazily prepared NILM workspace read source."""

    def __init__(self, coordinator: Any, config: CircuitConfig) -> None:
        self.coordinator = coordinator
        self.config = config
        self.circuit_id = config.circuit_id
        self._collections: dict[str, list[dict[str, Any]]] = {}
        self._merged_sessions: list[dict[str, Any]] | None = None
        self._raw_signatures: list[dict[str, Any]] | None = None
        self._raw_intervals: list[dict[str, Any]] | None = None
        self._raw_assignments: list[dict[str, Any]] | None = None

    def collection(self, name: str) -> list[dict[str, Any]]:
        if name not in self._collections:
            self._collections[name] = self._build_collection(name)
        return self._collections[name]

    def item(self, kind: str, item_id: str) -> dict[str, Any] | None:
        collection, identity = _NILM_WORKSPACE_ITEM_SOURCES[kind]
        return next(
            (
                dict(item)
                for item in self.collection(collection)
                if str(item.get(identity) or "").strip() == item_id
            ),
            None,
        )

    def _build_collection(self, name: str) -> list[dict[str, Any]]:
        if name == "signatures":
            signatures = self._signatures()
            _add_nilm_assignment_options(signatures, self._assignment_options())
            return signatures
        if name == "label_intervals":
            intervals = self._intervals()
            _add_nilm_assignment_options(intervals, self._assignment_options())
            return intervals
        if name == "assignments":
            return self._assignments()
        if name in {"sessions", "ambiguous_sessions"}:
            signatures = self.collection("signatures")
            assignments = self.collection("assignments")
            merged = self._sessions()
            labels = _nilm_session_display_labels(signatures, assignments)
            if name == "ambiguous_sessions":
                return [
                    _nilm_ambiguity_audit_item(
                        session, labels, circuit_id=self.circuit_id
                    )
                    for session in _nilm_workspace_ambiguous_sessions(
                        merged, signatures, assignments
                    )
                ]
            sessions = _add_nilm_session_display_labels(
                _nilm_workspace_visible_sessions(merged, signatures, assignments),
                labels,
            )
            _add_nilm_assignment_options(sessions, self._assignment_options())
            _add_nilm_session_signature_reviews(sessions, signatures)
            return sessions
        if name == "known_load_attributions":
            return _nilm_known_load_attributions_for_circuit(
                self.coordinator, self.circuit_id
            )
        raise KeyError(name)

    def _assignment_options(self) -> list[dict[str, Any]]:
        return _nilm_assignment_options(self._assignments(), config=self.config)

    def _signatures(self) -> list[dict[str, Any]]:
        if self._raw_signatures is None:
            self._raw_signatures = _nilm_workspace_signatures(
                self.coordinator, self.circuit_id, config=self.config
            )
        return self._raw_signatures

    def _intervals(self) -> list[dict[str, Any]]:
        if self._raw_intervals is None:
            self._raw_intervals = _nilm_label_intervals_for_circuit(
                self.coordinator, self.circuit_id, limit=None
            )
        return self._raw_intervals

    def _assignments(self) -> list[dict[str, Any]]:
        if self._raw_assignments is None:
            self._raw_assignments = _nilm_assignments_for_circuit(
                self.coordinator,
                self.circuit_id,
                label_intervals=self._intervals(),
            )
            _add_nilm_helper_evidence(
                self._raw_assignments,
                self._signatures(),
                self.circuit_id,
                coordinator=self.coordinator,
                config=self.config,
            )
            _add_nilm_reference_evidence(
                self._raw_assignments,
                self.circuit_id,
                coordinator=self.coordinator,
            )
        return self._raw_assignments

    def _sessions(self) -> list[dict[str, Any]]:
        if self._merged_sessions is None:
            signatures = self.collection("signatures")
            assignments = self.collection("assignments")
            reviewed_ids = _nilm_reviewed_session_ids_by_assignment(assignments)
            self._merged_sessions = _merge_nilm_session_payloads(
                _nilm_workspace_sessions(
                    _nilm_edges_for_circuit(self.coordinator, self.circuit_id),
                    self.circuit_id,
                    signatures=signatures,
                    assignments=assignments,
                    reviewed_session_ids=reviewed_ids,
                    limit=None,
                ),
                _nilm_session_history_for_circuit(
                    self.coordinator,
                    self.circuit_id,
                    reviewed_session_ids=reviewed_ids,
                ),
            )
        return self._merged_sessions

    def retained_sessions(self) -> list[dict[str, Any]]:
        """Return persisted sessions without generating edge-derived sessions."""

        reviewed_ids = _nilm_reviewed_session_ids_by_assignment(self._assignments())
        return _nilm_session_history_for_circuit(
            self.coordinator,
            self.circuit_id,
            reviewed_session_ids=reviewed_ids,
        )


def _nilm_workspace_ordered_collection(
    collection: str,
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        (
            dict(item)
            for item in items
            if _nilm_workspace_collection_identity(collection, item)
        ),
        key=lambda item: _nilm_workspace_collection_sort_key(collection, item),
    )


def _nilm_workspace_collection_identity(
    collection: str,
    item: Mapping[str, Any],
) -> str:
    field = {
        "sessions": "session_id",
        "label_intervals": ATTR_INTERVAL_ID,
        "assignments": ATTR_ASSIGNMENT_ID,
        "signatures": ATTR_SIGNATURE_ID,
        "known_load_attributions": "attribution_id",
    }.get(collection, "")
    return str(item.get(field) or "").strip()


def _nilm_workspace_collection_timestamp(
    collection: str,
    item: Mapping[str, Any],
) -> datetime | None:
    fields = {
        "sessions": ("end", "start"),
        "label_intervals": ("end", "start", "updated_at", "created_at"),
        "assignments": ("updated_at", "created_at"),
        "signatures": ("last_seen", "first_seen"),
        "known_load_attributions": ("timestamp",),
    }.get(collection, ())
    return next(
        (
            timestamp
            for field in fields
            if (timestamp := _datetime_from_iso(item.get(field))) is not None
        ),
        None,
    )


def _nilm_workspace_collection_sort_key(
    collection: str,
    item: Mapping[str, Any],
) -> tuple[int, float, str]:
    timestamp = _nilm_workspace_collection_timestamp(collection, item)
    timestamp_key = -timestamp.timestamp() if timestamp is not None else float("inf")
    completion_key = (
        0
        if collection != "sessions" or _datetime_from_iso(item.get("end")) is not None
        else 1
    )
    return (
        completion_key,
        timestamp_key,
        _nilm_workspace_collection_identity(collection, item),
    )


def _nilm_workspace_generic_collection_cursor(
    collection: str,
    item: Mapping[str, Any],
    *,
    circuit_id: str,
    entry_id: str,
) -> str:
    timestamp = _nilm_workspace_collection_timestamp(collection, item)
    item_id = _nilm_workspace_collection_identity(collection, item)
    if not item_id:
        return ""
    return _nilm_ambiguity_cursor_token(
        [
            "collection",
            collection,
            str(circuit_id or ""),
            str(entry_id or ""),
            0
            if collection != "sessions"
            or _datetime_from_iso(item.get("end")) is not None
            else 1,
            timestamp.isoformat() if timestamp is not None else "",
            item_id,
        ]
    )


def _nilm_workspace_generic_collection_cursor_key(
    cursor: Any,
    *,
    collection: str,
    circuit_id: str,
    entry_id: str,
) -> tuple[int, float, str] | None:
    value = _nilm_ambiguity_cursor_value(cursor)
    if not isinstance(value, list) or len(value) != 7:
        return None
    (
        kind,
        cursor_collection,
        cursor_circuit_id,
        cursor_entry_id,
        completion,
        raw_time,
        item_id,
    ) = value
    if (
        kind != "collection"
        or cursor_collection != collection
        or cursor_circuit_id != str(circuit_id or "")
        or cursor_entry_id != str(entry_id or "")
        or completion not in {0, 1}
        or not isinstance(raw_time, str)
        or not (normalized_item_id := _nilm_ambiguity_text(item_id))
    ):
        return None
    timestamp = _datetime_from_iso(raw_time) if raw_time else None
    return (
        completion,
        -timestamp.timestamp() if timestamp is not None else float("inf"),
        normalized_item_id,
    )


def _nilm_workspace_collection_metadata(
    collection: str,
    items: Iterable[Mapping[str, Any]],
    *,
    limit: int,
    circuit_id: str,
    entry_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = _nilm_workspace_ordered_collection(collection, items)
    page = ordered[:limit]
    truncated = len(ordered) > len(page)
    return page, {
        "total_count": len(ordered),
        "returned_count": len(page),
        "truncated": truncated,
        "next_cursor": (
            _nilm_workspace_generic_collection_cursor(
                collection,
                page[-1],
                circuit_id=circuit_id,
                entry_id=entry_id,
            )
            if truncated and page
            else None
        ),
    }


def _nilm_known_load_attributions_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    records_by_circuit = getattr(
        store_data, "nilm_known_load_attributions_by_circuit", {}
    )
    if not isinstance(records_by_circuit, Mapping):
        return []
    display_names = {
        config.circuit_id: config.name
        for config in getattr(coordinator, "circuit_configs", ()) or ()
        if isinstance(config, CircuitConfig)
    }
    payloads = [
        payload
        for record in _iter_items(records_by_circuit.get(circuit_id, ()))
        if isinstance(record, Mapping)
        if (payload := _nilm_known_load_attribution_payload(record)) is not None
    ]
    for payload in payloads:
        payload["known_load_labels"] = [
            display_names.get(known_circuit_id, known_circuit_id)
            for known_circuit_id in payload["known_circuit_ids"]
        ]
    return _nilm_workspace_ordered_collection("known_load_attributions", payloads)


def _nilm_known_load_attribution_payload(
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    attribution_id = str(record.get("attribution_id") or "").strip()
    timestamp = _datetime_from_iso(record.get("timestamp"))
    aggregate_edge_id = str(record.get("aggregate_edge_id") or "").strip()
    aggregate_delta_w = _nilm_optional_finite_number(record.get("aggregate_delta_w"))
    explained_delta_w = _nilm_optional_finite_number(record.get("explained_delta_w"))
    residual_delta_w = _nilm_optional_finite_number(record.get("residual_delta_w"))
    if (
        not attribution_id
        or timestamp is None
        or not aggregate_edge_id
        or aggregate_delta_w is None
        or explained_delta_w is None
        or residual_delta_w is None
        or not math.isclose(
            aggregate_delta_w,
            explained_delta_w + residual_delta_w,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
    ):
        return None
    known_circuit_ids = _unique_strings(
        _iter_items(record.get("known_circuit_ids"))
    )[:8]
    rejected = [
        {
            "known_circuit_id": str(item.get("known_circuit_id") or "").strip(),
            "topology_status": str(item.get("topology_status") or "").strip(),
            "selection_status": str(item.get("selection_status") or "").strip(),
        }
        for item in _iter_items(record.get("rejected_candidate_summaries"))
        if isinstance(item, Mapping)
        and str(item.get("known_circuit_id") or "").strip()
    ][:4]
    return {
        "attribution_id": attribution_id,
        "timestamp": timestamp.isoformat(),
        "aggregate_edge_id": aggregate_edge_id,
        "aggregate_delta_w": aggregate_delta_w,
        "explained_delta_w": explained_delta_w,
        "residual_delta_w": residual_delta_w,
        "known_circuit_ids": known_circuit_ids,
        "selection_method": str(record.get("selection_method") or "unattributed"),
        "compound": bool(record.get("compound")),
        "magnitude_score": _nilm_optional_finite_number(
            record.get("magnitude_score")
        ),
        "time_score": _nilm_optional_finite_number(record.get("time_score")),
        "topology_score": _nilm_optional_finite_number(
            record.get("topology_score")
        ),
        "total_score": _nilm_optional_finite_number(record.get("total_score")),
        "time_offsets_s": [
            value
            for item in _iter_items(record.get("time_offsets_s"))
            if (value := _nilm_optional_finite_number(item)) is not None
        ][:8],
        "topology_statuses": _unique_strings(
            _iter_items(record.get("topology_statuses"))
        )[:8],
        "residual_edge_id": (
            str(record.get("residual_edge_id") or "").strip() or None
        ),
        "ambiguity_status": str(record.get("ambiguity_status") or "unmatched"),
        "rejected_candidate_summaries": rejected,
        "provenance_version": _nilm_nonnegative_count(
            record.get("provenance_version")
        )
        or 1,
    }


def nilm_workspace_item_payload(
    coordinators: Iterable[Any],
    *,
    kind: str | None = None,
    item_id: str | None = None,
    circuit_id: str | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Resolve one safe, exact NILM workspace item without loading a page."""

    normalized_kind = str(kind or "").strip().lower()
    normalized_id = _nilm_ambiguity_text(item_id)
    if normalized_kind not in _NILM_WORKSPACE_ITEM_KINDS or normalized_id is None:
        return _nilm_workspace_item_error("invalid_kind", normalized_kind or None)
    target = _nilm_workspace_target(
        tuple(coordinators), circuit_id, entry_id=entry_id
    )
    if target is None:
        return _nilm_workspace_item_error("not_found", normalized_kind)
    coordinator, config, _sources = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    source = _NilmWorkspaceReadSource(coordinator, config)
    item = source.item(normalized_kind, normalized_id)
    if item is None:
        return _nilm_workspace_item_error("not_found", normalized_kind)
    if normalized_kind == "ambiguous_session":
        # Exact deep links are read-only audit navigation.  The regular
        # ambiguity audit may expose a deliberate manual-interval action,
        # but a link must never open an editor or advertise that action.
        item["safe_actions"] = ["open_on_graph"]
    if normalized_kind == "session" and _datetime_from_iso(item.get("end")) is None:
        return _nilm_workspace_item_error("not_found", normalized_kind)
    status = (
        "retired"
        if normalized_kind == "assignment"
        and str(item.get("lifecycle_state") or "").strip().lower() == "retired"
        else "ok"
    )
    payload = {
        "status": status,
        "kind": normalized_kind,
        "item": item,
        "focus": _nilm_workspace_item_focus(
            item,
            normalized_kind,
            config,
            collections=source,
        ),
        "safe_actions": _nilm_workspace_item_safe_actions(item, normalized_kind),
    }
    return _scope_nilm_actions(payload, selected_entry_id)


def _nilm_workspace_item_error(
    status: str,
    kind: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "kind": kind,
        "item": None,
        "focus": None,
        "safe_actions": [],
    }


def _nilm_workspace_item_safe_actions(
    item: Mapping[str, Any],
    kind: str,
) -> list[str]:
    if kind == "ambiguous_session":
        return ["open_on_graph"]
    if kind == "known_load_attribution":
        return ["open_on_graph"]
    actions = item.get("actions")
    return sorted(actions) if isinstance(actions, Mapping) else []


def _nilm_workspace_item_focus(
    item: Mapping[str, Any],
    kind: str,
    config: CircuitConfig,
    *,
    collections: Any = None,
) -> dict[str, Any]:
    start = _datetime_from_iso(item.get("start"))
    end = _datetime_from_iso(item.get("end"))
    if kind == "known_load_attribution":
        timestamp = _datetime_from_iso(item.get("timestamp"))
        if timestamp is not None:
            start = timestamp - timedelta(seconds=30)
            end = timestamp + timedelta(seconds=30)
    elif kind == "signature":
        start = _datetime_from_iso(item.get("first_seen"))
        end = _datetime_from_iso(item.get("last_seen"))
    if kind in {"assignment", "signature"} and (
        start is None or end is None or end <= start
    ):
        related = _nilm_workspace_item_related_interval(item, kind, collections)
        if related is not None:
            start = _datetime_from_iso(related.get("start"))
            end = _datetime_from_iso(related.get("end"))
    if end is None:
        end = start
    return {
        "start": start.isoformat() if start is not None else None,
        "end": end.isoformat() if end is not None else None,
        "entity_ids": _sensor_entity_ids(config),
    }


def _nilm_workspace_item_related_interval(
    item: Mapping[str, Any],
    kind: str,
    collections: Mapping[str, Iterable[Mapping[str, Any]]] | None,
) -> Mapping[str, Any] | None:
    """Find the newest retained session/label interval for an exact item."""

    if isinstance(collections, Mapping):
        get_collection = collections.get
    elif isinstance(collections, _NilmWorkspaceReadSource):
        get_collection = collections.collection
    else:
        return None
    session_source = (
        collections.retained_sessions()
        if kind == "signature"
        and isinstance(collections, _NilmWorkspaceReadSource)
        else get_collection("sessions")
    )
    sessions = [
        candidate
        for candidate in _iter_items(session_source)
        if isinstance(candidate, Mapping)
        and _datetime_from_iso(candidate.get("start")) is not None
        and _datetime_from_iso(candidate.get("end")) is not None
    ]
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    if kind == "assignment":
        assignment_id = str(item.get(ATTR_ASSIGNMENT_ID) or "").strip()
        fingerprints = {
            str(value or "").strip()
            for value in _iter_items(item.get("signature_fingerprints"))
            if str(value or "").strip()
        }
        candidates = [
            ("sessions", candidate)
            for candidate in sessions
            if str(candidate.get(ATTR_ASSIGNMENT_ID) or "").strip()
            == assignment_id
            or str(candidate.get("signature_fingerprint") or "").strip()
            in fingerprints
        ]
        if not candidates and assignment_id:
            candidates = [
                ("label_intervals", candidate)
                for candidate in _iter_items(get_collection("label_intervals"))
                if isinstance(candidate, Mapping)
                and str(candidate.get(ATTR_ASSIGNMENT_ID) or "").strip()
                == assignment_id
                and _datetime_from_iso(candidate.get("start")) is not None
                and _datetime_from_iso(candidate.get("end")) is not None
            ]
    elif kind == "signature":
        identifiers = _nilm_signature_identifiers(item)
        candidates = [
            ("sessions", candidate)
            for candidate in sessions
            if any(
                str(candidate.get(field) or "").strip() in identifiers
                for field in ("signature_fingerprint", ATTR_SIGNATURE_ID)
            )
        ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: _nilm_workspace_collection_sort_key(*candidate),
    )[1]


def _nilm_workspace_collection_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NILM_WORKSPACE_COLLECTION_LIMIT
    if parsed <= 0:
        return DEFAULT_NILM_WORKSPACE_COLLECTION_LIMIT
    return min(parsed, MAX_NILM_WORKSPACE_COLLECTION_LIMIT)


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
    payload["estimate_quality"] = _nilm_estimate_quality_rows(payload)
    return payload


def _nilm_estimate_quality_rows(
    signature: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Expose per-window estimate evidence without inferring missing values."""

    windows = signature.get("runtime_windows")
    statuses = signature.get("estimate_status_by_window")
    window_payloads = windows if isinstance(windows, Mapping) else {}
    status_payloads = statuses if isinstance(statuses, Mapping) else {}
    observation_started_at = signature.get("observation_started_at")
    energy_source = signature.get("energy_source")
    source_quality = signature.get("energy_estimate_confidence")
    rows: list[dict[str, Any]] = []
    for window, runtime_key, energy_key in _NILM_ESTIMATE_QUALITY_WINDOWS:
        details = window_payloads.get(window)
        details = details if isinstance(details, Mapping) else {}
        status = str(
            status_payloads.get(window)
            or details.get("estimate_status")
            or signature.get("estimate_status")
            or "legacy_unverified"
        ).strip().lower()
        if status not in {
            "complete",
            "partial_history",
            "ambiguous",
            "legacy_unverified",
        }:
            status = "legacy_unverified"
        rows.append(
            {
                "window": window,
                "status": status,
                "runtime_minutes": _nilm_optional_finite_number(
                    signature.get(runtime_key)
                ),
                "energy_kwh": _nilm_optional_finite_number(signature.get(energy_key)),
                "observation_started_at": observation_started_at,
                "requested_start": details.get("requested_start"),
                "requested_end": details.get("requested_end"),
                "coverage_start": details.get("coverage_start"),
                "coverage_end": details.get("coverage_end"),
                "coverage_days": _nilm_optional_finite_number(
                    details.get("coverage_days")
                ),
                "nominal_days": _nilm_optional_finite_number(
                    details.get("nominal_days")
                ),
                "included_session_count": _nilm_nonnegative_count(
                    details.get("included_session_count")
                ),
                "excluded_session_count": _nilm_nonnegative_count(
                    details.get("excluded_session_count")
                ),
                "energy_source": str(energy_source).strip() if energy_source else None,
                "energy_quality": _nilm_optional_finite_number(source_quality),
                "power_coverage": _nilm_optional_finite_number(
                    signature.get("power_coverage")
                ),
                "longest_trace_gap_seconds": _nilm_optional_finite_number(
                    signature.get("longest_trace_gap_seconds")
                ),
                "retention_truncated": bool(
                    signature.get("session_history_truncated")
                    or signature.get("trace_point_cap_truncated")
                ),
            }
        )
    return rows


def _nilm_optional_finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nilm_nonnegative_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


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
            signature["electrical_class_confidence"] = signature.get(
                "evidence_strength",
                signature.get("confidence"),
            )


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
    evidence_strength = signature.get("evidence_strength")
    if isinstance(evidence_strength, (int, float)):
        parts.append(
            f"evidence strength {round(float(evidence_strength) * 100):.0f}%"
        )
    elif isinstance(signature.get("confidence"), (int, float)):
        parts.append(
            "legacy confidence (mixed semantics) "
            f"{round(float(signature['confidence']) * 100):.0f}%"
        )
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
    histories = getattr(store_data, "nilm_session_history_by_circuit", {})
    sessions = histories.get(circuit_id, ()) if isinstance(histories, Mapping) else ()
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
            sessions=sessions,
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
                f"with {confidence:.0%} evidence strength."
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
                    "reference_on_threshold",
                    "reference_off_threshold",
                    "reference_on_dwell_seconds",
                    "reference_off_dwell_seconds",
                    "reference_minimum_interval_seconds",
                    "reference_merge_gap_seconds",
                    "reference_maximum_unknown_gap_seconds",
                    "reference_maximum_power_gap_seconds",
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
        reference_settings = _nilm_reference_settings_payload(assignment)
        assignment["reference"] = {
            "state_entity_id": state_entity_id or None,
            "power_entity_id": power_entity_id or None,
            **reference_settings,
            **({"import_summary": summary} if (
                summary := _nilm_reference_import_summary(
                    assignment.get("reference_import_summary")
                )
            ) is not None else {}),
            **runtime,
            "state_options": state_options,
            "power_options": power_options,
            "suggested_power_entity_id": suggested_power_entity_id,
            "actions": actions,
        }


def _nilm_reference_options(
    coordinator: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshot = getattr(coordinator, "_nilm_reference_options_snapshot", None)
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        return snapshot
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
    sessions: Iterable[Mapping[str, Any]] = (),
    configured_circuit_names: Iterable[str] = (),
) -> dict[str, Any]:
    assignments = tuple(assignments)
    sessions = tuple(sessions)
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
    publication_readiness = evaluate_nilm_validation_readiness(
        payload,
        sessions,
        min_confirmed_sessions=3,
        min_distinct_days=3,
        max_false_positive_rate=0.2,
        min_confidence=0.8,
    )["publication_readiness"]
    payload["publication_readiness"] = publication_readiness
    publication_reason = nilm_assignment_publication_reason(
        payload,
        sessions=sessions,
        publication_readiness=publication_readiness,
    )
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
            and bool(session.get("end"))
            and not str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
            and not bool(session.get("ambiguous"))
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
    evaluable_prediction_ids: set[str] = set()
    unevaluated_prediction_ids: set[str] = set()
    matched_sessions_by_interval_id: dict[str, dict[str, Any]] = {}
    matches_by_interval_id = {}
    for assignment_id, assignment in assignment_by_id.items():
        assignment_intervals = [
            interval
            for interval in ground_truth_intervals
            if _nilm_validation_assignment_matches(interval, assignment)
        ]
        if not assignment_intervals:
            continue
        assignment_sessions = [
            session
            for session in predictions
            if str(session.get("assignment_id") or "").strip() == assignment_id
        ]
        circuit_id = next(
            (
                str(interval.get("mains_circuit_id") or "").strip()
                for interval in assignment_intervals
                if str(interval.get("mains_circuit_id") or "").strip()
            ),
            "panel",
        )
        result = match_nilm_validation_intervals(
            assignment_sessions,
            assignment_intervals,
            circuit_id=circuit_id,
        )
        evaluable_prediction_ids.update(
            match.session_id for match in result.matches
        )
        evaluable_prediction_ids.update(result.false_positive_session_ids)
        unevaluated_prediction_ids.update(result.unevaluated_session_ids)
        sessions_by_id = {
            str(session.get("session_id") or "").strip(): session
            for session in assignment_sessions
            if str(session.get("session_id") or "").strip()
        }
        for match in result.matches:
            session = sessions_by_id.get(match.session_id)
            if session is None:
                continue
            matched_prediction_ids.add(match.session_id)
            matched_sessions_by_interval_id[match.interval_id] = session
            matches_by_interval_id[match.interval_id] = match
    preview = []
    for interval in ground_truth_intervals:
        circuit_id = str(interval.get("mains_circuit_id") or "").strip() or "panel"
        interval_id = nilm_validation_interval_id(
            interval,
            circuit_id=circuit_id,
        )
        match = matches_by_interval_id.get(interval_id)
        session = matched_sessions_by_interval_id.get(interval_id)
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
                "overlap_seconds": match.overlap_seconds if match else 0.0,
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
            "evaluable_prediction_count": len(evaluable_prediction_ids),
            "unevaluated_prediction_count": len(unevaluated_prediction_ids),
            "matched_ground_truth_count": matched_ground_truth_count,
            "matched_prediction_count": matched_prediction_count,
            "missed_ground_truth_count": (
                ground_truth_count - matched_ground_truth_count
            ),
            "precision": _nilm_validation_ratio(
                matched_prediction_count,
                len(evaluable_prediction_ids),
            ),
            "recall": _nilm_validation_ratio(
                matched_ground_truth_count,
                ground_truth_count,
            ),
        },
        "prediction_preview": preview,
    }


def _nilm_validation_assignment_matches(
    interval: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    if "assignment_id" in interval:
        return str(interval.get("assignment_id") or "").strip() == str(
            assignment.get("assignment_id") or ""
        ).strip()
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


def _nilm_workspace_session_page(
    sessions: Iterable[Mapping[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return completed sessions first, newest first within each state."""

    def sort_key(session: Mapping[str, Any]) -> tuple[bool, float]:
        seen = _nilm_session_seen_datetime(session)
        return bool(session.get("end")), seen.timestamp() if seen else float("-inf")

    ordered = sorted(
        (dict(session) for session in sessions),
        key=sort_key,
        reverse=True,
    )
    return ordered[: max(int(limit), 0)]


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


def _nilm_reference_settings_payload(
    assignment: Mapping[str, Any],
) -> dict[str, float | None]:
    """Return only normalized persisted reference settings for the panel."""

    def number(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed >= 0 else None

    legacy = number(assignment.get("reference_threshold_w"))
    on_threshold = number(assignment.get("reference_on_threshold"))
    off_threshold = number(assignment.get("reference_off_threshold"))
    if on_threshold is None and off_threshold is None:
        on_threshold = off_threshold = legacy
    settings_values = {
        "on_threshold": on_threshold,
        "off_threshold": off_threshold,
        "on_dwell_seconds": number(
            assignment.get("reference_on_dwell_seconds")
        )
        or 0.0,
        "off_dwell_seconds": number(
            assignment.get("reference_off_dwell_seconds")
        )
        or 0.0,
        "minimum_interval_seconds": number(
            assignment.get("reference_minimum_interval_seconds")
        )
        or 0.0,
        "merge_gap_seconds": number(
            assignment.get("reference_merge_gap_seconds")
        )
        or 0.0,
        "maximum_unknown_gap_seconds": number(
            assignment.get("reference_maximum_unknown_gap_seconds")
        )
        or 0.0,
        "maximum_power_gap_seconds": number(
            assignment.get("reference_maximum_power_gap_seconds")
        ),
    }
    try:
        settings = NilmReferenceExtractionSettings(**settings_values)
    except ValueError:
        settings = NilmReferenceExtractionSettings(
            on_threshold=legacy,
            off_threshold=legacy,
        )
    return {
        "threshold_w": legacy if legacy is not None else (settings.on_threshold or 0.0),
        "on_threshold": settings.on_threshold,
        "off_threshold": settings.off_threshold,
        "on_dwell_seconds": settings.on_dwell_seconds,
        "off_dwell_seconds": settings.off_dwell_seconds,
        "minimum_interval_seconds": settings.minimum_interval_seconds,
        "merge_gap_seconds": settings.merge_gap_seconds,
        "maximum_unknown_gap_seconds": settings.maximum_unknown_gap_seconds,
        "maximum_power_gap_seconds": settings.maximum_power_gap_seconds,
    }


def _nilm_reference_import_summary(value: Any) -> dict[str, Any] | None:
    """Return a bounded, display-only summary for the latest reference import."""
    if not isinstance(value, Mapping):
        return None
    count_keys = (
        "candidate_interval_count",
        "imported_interval_count",
        "discarded_minimum_duration_count",
        "bridged_unknown_gap_count",
        "merged_inactive_gap_count",
        "low_coverage_interval_count",
    )
    summary: dict[str, Any] = {}
    for key in count_keys:
        count = value.get(key, 0)
        summary[key] = (
            min(count, 10_000)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0
            else 0
        )
    warnings = value.get("warnings")
    if isinstance(warnings, list):
        summary["warnings"] = [
            warning.strip()[:128]
            for warning in warnings
            if isinstance(warning, str) and warning.strip()
        ][:16]
    else:
        summary["warnings"] = []
    return summary


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
    hidden_assignment_ids, hidden_fingerprints = _nilm_workspace_session_filters(
        signatures,
        assignments,
    )
    return [
        dict(session)
        for session in sessions
        if not bool(session.get("ambiguous"))
        and _nilm_workspace_session_is_visible(
            session,
            hidden_assignment_ids,
            hidden_fingerprints,
        )
    ]


def _nilm_workspace_ambiguous_sessions(
    sessions: Iterable[Mapping[str, Any]],
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return completed, visible ambiguous evidence for the read-only audit."""

    hidden_assignment_ids, hidden_fingerprints = _nilm_workspace_session_filters(
        signatures,
        assignments,
    )
    eligible: list[dict[str, Any]] = []
    for session in sessions:
        if (
            not bool(session.get("ambiguous"))
            or not _nilm_workspace_session_is_visible(
                session,
                hidden_assignment_ids,
                hidden_fingerprints,
            )
        ):
            continue
        start = _datetime_from_iso(session.get("start"))
        end = _datetime_from_iso(session.get("end"))
        if start is None or end is None or end <= start:
            continue
        eligible.append(dict(session))
    return eligible


def _nilm_workspace_session_filters(
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> tuple[set[str], set[str]]:
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
    return hidden_assignment_ids, hidden_fingerprints


def _nilm_workspace_session_is_visible(
    session: Mapping[str, Any],
    hidden_assignment_ids: set[str],
    hidden_fingerprints: set[str],
) -> bool:
    return (
        str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
        not in hidden_assignment_ids
        and str(session.get("signature_fingerprint") or "").strip()
        not in hidden_fingerprints
    )


def _nilm_ambiguity_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= 256 else None


def _nilm_ambiguity_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        return None
    return round(score, 3)


def _nilm_session_ambiguity_candidates(
    session: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Normalize the retained top-three pairing explanations for presentation."""

    raw_candidates = session.get("ambiguity_candidates")
    if not isinstance(raw_candidates, (list, tuple)):
        return []
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_candidate in raw_candidates[:MAX_NILM_AMBIGUITY_CANDIDATE_EXPLANATIONS]:
        if not isinstance(raw_candidate, Mapping):
            continue
        candidate_id = _nilm_ambiguity_text(raw_candidate.get("candidate_id"))
        candidate_kind = _nilm_ambiguity_text(raw_candidate.get("candidate_kind"))
        reason_code = _nilm_ambiguity_text(raw_candidate.get("reason_code"))
        if (
            candidate_id is None
            or candidate_id in seen_ids
            or candidate_kind not in _NILM_AMBIGUITY_CANDIDATE_KINDS
            or reason_code not in _NILM_AMBIGUITY_REASON_CODES
        ):
            continue
        candidate: dict[str, Any] = {
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "signature_fingerprint": _nilm_ambiguity_text(
                raw_candidate.get("signature_fingerprint")
            ),
            "assignment_id": _nilm_ambiguity_text(
                raw_candidate.get("assignment_id")
            ),
            "edge_id": _nilm_ambiguity_text(raw_candidate.get("edge_id")),
            "total_score": _nilm_ambiguity_score(raw_candidate.get("total_score")),
            "score_margin_from_best": _nilm_ambiguity_score(
                raw_candidate.get("score_margin_from_best")
            ),
            "reason_code": reason_code,
        }
        candidates.append(candidate)
        seen_ids.add(candidate_id)
    return sorted(
        candidates,
        key=lambda candidate: (
            -(
                candidate["total_score"]
                if candidate["total_score"] is not None
                else -1.0
            ),
            candidate["candidate_id"],
        ),
    )


def _nilm_session_ambiguity_detail(
    session: Mapping[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]], list[str]]:
    """Return the supported category and stable identity inputs for one row."""

    candidates = _nilm_session_ambiguity_candidates(session)
    reason_codes = sorted(
        {candidate["reason_code"] for candidate in candidates}
    )
    if "assignment_candidate_conflict" in reason_codes:
        category = "assignment_candidate_conflict"
    elif "signature_candidate_conflict" in reason_codes:
        category = "signature_candidate_conflict"
    elif "stop_boundary_conflict" in reason_codes:
        category = "stop_boundary_conflict"
    else:
        category = "other"
    identifiers = {
        f"signature:{value}"
        for value in (
            _nilm_ambiguity_text(session.get("signature_fingerprint")),
            *(
                candidate.get("signature_fingerprint") for candidate in candidates
            ),
        )
        if value
    }
    identifiers.update(
        f"assignment:{candidate['assignment_id']}"
        for candidate in candidates
        if candidate.get("assignment_id")
    )
    return category, reason_codes, candidates, sorted(identifiers)


def _nilm_ambiguity_group_id(
    circuit_id: str,
    category: str,
    identifiers: Iterable[str],
    reason_codes: Iterable[str],
) -> str:
    identity = json.dumps(
        {
            "circuit_id": circuit_id,
            "category": category,
            "identifiers": sorted(set(identifiers)),
            "reason_codes": sorted(set(reason_codes)),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"amb-group-{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _nilm_ambiguity_candidate_labels(
    candidates: Iterable[Mapping[str, Any]],
    labels: Mapping[str, str],
) -> list[str]:
    return _unique_strings(
        labels[key]
        for candidate in candidates
        for key in (
            str(candidate.get("assignment_id") or "").strip(),
            str(candidate.get("signature_fingerprint") or "").strip(),
        )
        if key in labels and str(labels[key] or "").strip()
    )[:MAX_NILM_AMBIGUITY_CANDIDATE_EXPLANATIONS]


def _nilm_ambiguity_group_sort_key(
    group: Mapping[str, Any],
) -> tuple[int, float, str]:
    """Return the deterministic newest group order used by audit cursors."""

    count = group.get("occurrence_count")
    occurrence_count = (
        int(count)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0
        else 0
    )
    latest_at = group.get("latest_at")
    latest = (
        latest_at
        if isinstance(latest_at, datetime)
        else _datetime_from_iso(latest_at)
    )
    group_id = str(group.get("group_id") or "").strip()
    return (
        -occurrence_count,
        -(latest.timestamp() if latest is not None else float("-inf")),
        group_id,
    )


def _nilm_workspace_ambiguity_groups(
    sessions: Iterable[Mapping[str, Any]],
    labels: Mapping[str, str],
    *,
    circuit_id: str,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for session in sessions:
        category, reason_codes, candidates, identifiers = (
            _nilm_session_ambiguity_detail(session)
        )
        group_id = _nilm_ambiguity_group_id(
            circuit_id,
            category,
            identifiers,
            reason_codes,
        )
        latest_at = _datetime_from_iso(session.get("end"))
        if latest_at is None:
            continue
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "category": category,
                "reason_codes": reason_codes,
                "candidate_labels": set(),
                "occurrence_count": 0,
                "latest_at": latest_at,
            },
        )
        group["occurrence_count"] += 1
        group["latest_at"] = max(group["latest_at"], latest_at)
        group["candidate_labels"].update(
            _nilm_ambiguity_candidate_labels(candidates, labels)
        )
    ordered = sorted(groups.values(), key=_nilm_ambiguity_group_sort_key)
    return [
        {
            "group_id": group["group_id"],
            "category": group["category"],
            "reason_codes": group["reason_codes"],
            "candidate_labels": sorted(group["candidate_labels"])[
                :MAX_NILM_AMBIGUITY_CANDIDATE_EXPLANATIONS
            ],
            "occurrence_count": group["occurrence_count"],
            "latest_at": group["latest_at"].isoformat(),
        }
        for group in ordered
    ]


def _nilm_ambiguity_audit_fetch_path(circuit_id: str, entry_id: str) -> str:
    query = {"collection": "ambiguous_sessions", "circuit_id": circuit_id}
    if entry_id:
        query[ATTR_ENTRY_ID] = entry_id
    return f"{NILM_WORKSPACE_COLLECTION_API_PATH}?{urlencode(query)}"


def _nilm_workspace_ambiguity_audit_summary(
    sessions: Iterable[Mapping[str, Any]],
    labels: Mapping[str, str],
    *,
    circuit_id: str,
    entry_id: str,
) -> dict[str, Any] | None:
    sessions = tuple(sessions)
    if not sessions:
        return None
    groups = _nilm_workspace_ambiguity_groups(
        sessions,
        labels,
        circuit_id=circuit_id,
    )
    return {
        "total_count": len(sessions),
        "requires_action": False,
        "collapsed_by_default": True,
        "group_count": len(groups),
        "group_preview": groups[:MAX_NILM_AMBIGUITY_AUDIT_GROUP_PREVIEW],
        "group_preview_truncated": len(groups)
        > MAX_NILM_AMBIGUITY_AUDIT_GROUP_PREVIEW,
        "fetch_path": _nilm_ambiguity_audit_fetch_path(circuit_id, entry_id),
    }


def _nilm_session_ambiguity_group_id(
    session: Mapping[str, Any],
    circuit_id: str,
) -> str:
    category, reason_codes, _candidates, identifiers = _nilm_session_ambiguity_detail(
        session
    )
    return _nilm_ambiguity_group_id(
        circuit_id,
        category,
        identifiers,
        reason_codes,
    )


def _nilm_ambiguity_session_sort_key(
    session: Mapping[str, Any],
) -> tuple[float, str]:
    end = _datetime_from_iso(session.get("end"))
    session_id = str(session.get("session_id") or "").strip()
    return (
        -(end.timestamp() if end is not None else float("-inf")),
        session_id,
    )


def _nilm_ambiguity_cursor_token(value: list[Any]) -> str:
    """Return a signed opaque token for one bounded ambiguity-audit page."""

    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac_new(
            _NILM_AMBIGUITY_CURSOR_SECRET,
            payload.encode("ascii"),
            sha256,
        ).digest()
    ).decode("ascii").rstrip("=")
    return f"{_NILM_AMBIGUITY_CURSOR_VERSION}.{payload}.{signature}"


def _nilm_ambiguity_cursor_value(cursor: Any) -> list[Any] | None:
    """Read a valid signed ambiguity-audit cursor without trusting its data."""

    if not isinstance(cursor, str) or not cursor or len(cursor) > 1024:
        return None
    try:
        version, payload, signature = cursor.split(".")
        if version != _NILM_AMBIGUITY_CURSOR_VERSION:
            return None
        expected_signature = base64.urlsafe_b64encode(
            hmac_new(
                _NILM_AMBIGUITY_CURSOR_SECRET,
                payload.encode("ascii"),
                sha256,
            ).digest()
        ).decode("ascii").rstrip("=")
        if not compare_digest(signature, expected_signature):
            return None
        padding = "=" * (-len(payload) % 4)
        decoded = base64.b64decode(
            payload + padding,
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(decoded.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def _nilm_ambiguity_collection_cursor(
    session: Mapping[str, Any],
    *,
    circuit_id: str,
    entry_id: str,
    group_id: str | None,
) -> str:
    """Return a signed, scope-bound occurrence cursor."""

    end = _datetime_from_iso(session.get("end"))
    session_id = str(session.get("session_id") or "").strip()
    if end is None or not session_id:
        return ""
    return _nilm_ambiguity_cursor_token(
        [
            "occurrences",
            str(circuit_id or ""),
            str(entry_id or ""),
            str(group_id or ""),
            end.isoformat(),
            session_id,
        ]
    )


def _nilm_ambiguity_collection_cursor_key(
    cursor: Any,
    *,
    circuit_id: str,
    entry_id: str,
    group_id: str | None,
) -> tuple[float, str] | None:
    value = _nilm_ambiguity_cursor_value(cursor)
    if not isinstance(value, list) or len(value) != 6:
        return None
    view = value[0]
    cursor_circuit_id = _nilm_ambiguity_text(value[1])
    cursor_entry_id = str(value[2] or "") if isinstance(value[2], str) else None
    cursor_group_id = str(value[3] or "") if isinstance(value[3], str) else None
    if (
        view != "occurrences"
        or cursor_circuit_id != str(circuit_id or "")
        or cursor_entry_id != str(entry_id or "")
        or cursor_group_id != str(group_id or "")
    ):
        return None
    end = _datetime_from_iso(value[4])
    session_id = _nilm_ambiguity_text(value[5])
    if end is None or session_id is None:
        return None
    return -end.timestamp(), session_id


def _nilm_ambiguity_group_collection_cursor(
    group: Mapping[str, Any],
    *,
    circuit_id: str,
    entry_id: str,
) -> str:
    """Return a signed, scope-bound group-summary cursor."""

    occurrence_count = group.get("occurrence_count")
    latest_at = _datetime_from_iso(group.get("latest_at"))
    group_id = _nilm_ambiguity_text(group.get("group_id"))
    if (
        not isinstance(occurrence_count, int)
        or isinstance(occurrence_count, bool)
        or occurrence_count < 0
        or latest_at is None
        or group_id is None
    ):
        return ""
    return _nilm_ambiguity_cursor_token(
        [
            "groups",
            str(circuit_id or ""),
            str(entry_id or ""),
            occurrence_count,
            latest_at.isoformat(),
            group_id,
        ]
    )


def _nilm_ambiguity_group_collection_cursor_key(
    cursor: Any,
    *,
    circuit_id: str,
    entry_id: str,
) -> tuple[int, float, str] | None:
    value = _nilm_ambiguity_cursor_value(cursor)
    if not isinstance(value, list) or len(value) != 6:
        return None
    view = value[0]
    cursor_circuit_id = _nilm_ambiguity_text(value[1])
    cursor_entry_id = str(value[2] or "") if isinstance(value[2], str) else None
    occurrence_count = value[3]
    latest_at = _datetime_from_iso(value[4])
    group_id = _nilm_ambiguity_text(value[5])
    if (
        view != "groups"
        or cursor_circuit_id != str(circuit_id or "")
        or cursor_entry_id != str(entry_id or "")
        or not isinstance(occurrence_count, int)
        or isinstance(occurrence_count, bool)
        or occurrence_count < 0
        or latest_at is None
        or group_id is None
    ):
        return None
    return -occurrence_count, -latest_at.timestamp(), group_id


def _nilm_ambiguity_audit_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1_000_000_000:
        return None
    return round(number, 6)


def _nilm_ambiguity_audit_item(
    session: Mapping[str, Any],
    labels: Mapping[str, str],
    *,
    circuit_id: str,
) -> dict[str, Any]:
    category, reason_codes, candidates, _identifiers = (
        _nilm_session_ambiguity_detail(session)
    )
    explanations: list[dict[str, Any]] = []
    for candidate in candidates[:MAX_NILM_AMBIGUITY_CANDIDATE_EXPLANATIONS]:
        explanation = dict(candidate)
        for key in (
            str(candidate.get("assignment_id") or "").strip(),
            str(candidate.get("signature_fingerprint") or "").strip(),
        ):
            if key in labels and str(labels[key] or "").strip():
                explanation["display_label"] = labels[key]
                break
        explanations.append(explanation)
    start = _datetime_from_iso(session.get("start"))
    end = _datetime_from_iso(session.get("end"))
    return {
        "session_id": str(session.get("session_id") or "").strip(),
        "group_id": _nilm_session_ambiguity_group_id(session, circuit_id),
        "start": start.isoformat() if start is not None else None,
        "end": end.isoformat() if end is not None else None,
        "on_edge_id": _nilm_ambiguity_text(session.get("on_edge_id")),
        "off_edge_id": _nilm_ambiguity_text(session.get("off_edge_id")),
        "duration_seconds": _nilm_ambiguity_audit_number(
            session.get("duration_seconds")
        ),
        "median_power_w": _nilm_ambiguity_audit_number(
            session.get("median_power_w")
        ),
        "estimated_energy_kwh": _nilm_ambiguity_audit_number(
            session.get("estimated_energy_kwh")
        ),
        "ambiguous": True,
        "ambiguity_category": category,
        "ambiguity_reason_codes": reason_codes,
        "candidate_explanations": explanations,
        "safe_actions": ["open_on_graph", "create_manual_interval"],
    }


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
        if (
            nilm_signature_is_assignable(signature_fingerprint)
            and not assignment_id
            and not bool(payload.get("ambiguous"))
            and bool(payload.get("end"))
        ):
            data[ATTR_SIGNATURE_FINGERPRINT] = signature_fingerprint
            actions["assign"] = {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
                "data": data,
                "requires": [ATTR_LABEL],
            }
        if (
            payload.get("end")
            and assignment_id
            and not bool(payload.get("ambiguous"))
            and (
                reviewed_session_ids is None
                or (
                    assignment_id in reviewed_session_ids
                    and all(
                        session_id not in ids
                        for ids in reviewed_session_ids.values()
                    )
                )
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
