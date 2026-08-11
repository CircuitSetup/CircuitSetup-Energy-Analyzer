from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .nilm import (
    NilmEdge,
    NilmSignature,
    nilm_signature_fingerprint,
    nilm_signature_fingerprint_v1,
    nilm_signature_is_assignable,
    nilm_signature_is_off_direction,
)

MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.5
UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION = 3
MIN_SIGNATURE_PAIR_SCORE = 0.50
SIGNATURE_PAIR_AMBIGUITY_MARGIN = 0.08
EDGE_COMPONENT_AMBIGUITY_MARGIN = 0.08
LEGACY_IDENTITY_UNRESOLVED_KEY = "legacy_identity_unresolved"


@dataclass(frozen=True, slots=True)
class _UnknownLoadComponent:
    component_id: str
    component_fingerprint: str
    on_signature: NilmSignature
    off_signature: NilmSignature | None
    pair_status: str
    pair_score: float | None
    alternate_pair_count: int = 0


@dataclass(frozen=True, slots=True)
class _UnknownLoadAllocation:
    edges_by_component: Mapping[str, tuple[NilmEdge, ...]]
    matched_on_count_by_component: Mapping[str, int]
    matched_off_count_by_component: Mapping[str, int]
    ambiguous_edge_count_by_component: Mapping[str, int]
    ambiguous_component_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _NormalizedUnknownLoadSession:
    """Storage-safe session evidence normalized to UTC before windowing."""

    session_id: str
    signature_fingerprint: str
    start: datetime
    end: datetime
    is_open: bool
    on_edge_id: str
    identities: frozenset[str]


@dataclass(frozen=True, slots=True)
class _OwnedUnknownLoadSession:
    session: _NormalizedUnknownLoadSession
    component_id: str


@dataclass(frozen=True, slots=True)
class _SessionInventoryEvidence:
    sessions_by_component: Mapping[str, tuple[_OwnedUnknownLoadSession, ...]]
    excluded_count_by_component: Mapping[str, int]
    ambiguous_component_ids: frozenset[str]
    observation_started_at: datetime | None


def estimate_unknown_load(signature: NilmSignature) -> dict[str, Any]:
    """Return a conservative user-facing estimate for an unknown NILM signature."""

    typical_watts = _rounded_abs(signature.median_delta_w)
    typical_var = _rounded_abs(signature.median_delta_var)
    typical_va = _rounded_abs(signature.median_delta_va)
    typical_power_factor = _typical_power_factor(typical_watts, typical_va)
    voltage_class = _voltage_class(signature.split_phase_type)
    likely_type = _likely_type(
        signature,
        typical_watts=typical_watts,
        typical_var=typical_var,
        typical_va=typical_va,
        typical_power_factor=typical_power_factor,
        voltage_class=voltage_class,
    )

    return {
        "signature_id": signature.signature_id,
        "display_name": _display_name(likely_type, voltage_class),
        "likely_type": likely_type,
        "voltage_class": voltage_class,
        "split_phase_type": signature.split_phase_type,
        "dominant_leg": signature.dominant_leg,
        "typical_watts": typical_watts,
        "typical_var": typical_var,
        "typical_va": typical_va,
        "typical_power_factor": typical_power_factor,
        "confidence": signature.confidence,
        "occurrence_count": signature.occurrence_count,
        "evidence": _evidence(
            signature,
            likely_type=likely_type,
            voltage_class=voltage_class,
            typical_watts=typical_watts,
            typical_var=typical_var,
            typical_va=typical_va,
            typical_power_factor=typical_power_factor,
        ),
    }


def build_unknown_load_inventory(
    *,
    circuit_id: str,
    signatures: Iterable[NilmSignature],
    edges: Iterable[NilmEdge],
    sessions: Iterable[Mapping[str, Any]] = (),
    now: datetime,
    time_zone: str = "UTC",
    session_history_max_items: int | None = None,
    existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consolidated inventory of recurring unknown NILM loads."""

    signature_list = list(signatures)
    edge_list = sorted(
        (_edge_with_utc_timestamp(edge) for edge in edges),
        key=lambda edge: edge.timestamp,
    )
    components = _unknown_load_components(signature_list)
    allocation = _allocate_unknown_edges(components, edge_list)
    now_utc = _as_utc_datetime(now)
    session_list = tuple(sessions)
    session_evidence = _session_inventory_evidence(
        session_list,
        components=components,
        now=now_utc,
        existing_state=existing_state or {},
    )
    windows = _runtime_windows(now_utc, time_zone)
    loads = [
        (
            _unknown_component_session_payload(
                component,
                allocation,
                session_evidence,
                windows=windows,
                now=now_utc,
                existing_state=existing_state or {},
                session_history_max_items=session_history_max_items,
            )
            if session_list
            else _unknown_component_payload(
                component,
                allocation,
                now=now_utc,
                existing_state=existing_state or {},
            )
        )
        for component in components
    ]
    loads.sort(key=lambda load: str(load["component_id"]))
    active_count = sum(1 for load in loads if load["running_state"] == "probably_on")
    ambiguous_count = sum(
        1 for load in loads if load["separation_status"] == "ambiguous"
    )

    inventory = {
        "circuit_id": circuit_id,
        "schema_version": UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION,
        "unknown_load_count": len(loads),
        "active_unknown_load_count": active_count,
        "ambiguous_unknown_load_count": ambiguous_count,
        "simultaneous_unknown_event_count": _simultaneous_unknown_event_count(
            edge_list
        ),
        "unknown_estimated_energy_today_kwh": _sum_loads(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_estimated_energy_7_days_kwh": _sum_loads(
            loads,
            "estimated_energy_7_days_kwh",
        ),
        "unknown_estimated_energy_30_days_kwh": _sum_loads(
            loads,
            "estimated_energy_30_days_kwh",
        ),
        "largest_unknown_load": _largest_load(loads, "typical_watts"),
        "highest_unknown_energy_load": _largest_load(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_loads": loads,
    }
    if session_list:
        inventory.update(
            {
                "observation_started_at": _observation_started_at(
                    session_evidence.observation_started_at,
                    existing_state or {},
                ),
                "runtime_window_definition": _runtime_window_definition(),
                "estimate_status": _worst_estimate_status(
                    load.get("estimate_status", "complete") for load in loads
                ),
            }
        )
    else:
        observed = _edge_observation_started_at(loads)
        for load in loads:
            _add_edge_window_metadata(load, windows, observed, existing_state or {})
        inventory.update(
            {
                "observation_started_at": _observation_started_at(
                    observed, existing_state or {}
                ),
                "runtime_window_definition": _runtime_window_definition(),
                "estimate_status": _worst_estimate_status(
                    load.get("estimate_status", "partial_history") for load in loads
                ),
            }
        )
    return inventory


def unknown_load_inventory_needs_rebuild(
    existing_state: Mapping[str, Any] | None,
) -> bool:
    """Return whether a persisted inventory predates component ownership."""

    if not isinstance(existing_state, Mapping):
        return True
    try:
        schema_version = int(existing_state.get("schema_version", 0))
    except (TypeError, ValueError):
        return True
    if schema_version < UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION:
        return True
    loads = existing_state.get("unknown_loads")
    if not isinstance(loads, list):
        return True
    if not isinstance(existing_state.get("runtime_window_definition"), Mapping):
        return True
    if str(existing_state.get("estimate_status") or "") not in {
        "complete",
        "partial_history",
        "legacy_unverified",
        "ambiguous",
    }:
        return True

    component_ids: set[str] = set()
    for load in loads:
        if not isinstance(load, Mapping):
            return True
        if str(load.get("estimate_status") or "") not in {
            "complete",
            "partial_history",
            "legacy_unverified",
            "ambiguous",
        }:
            return True
        windows = load.get("runtime_windows")
        if not isinstance(windows, Mapping) or not all(
            isinstance(windows.get(name), Mapping)
            and {
                "coverage_start",
                "coverage_end",
                "coverage_days",
                "estimate_status",
                "included_session_count",
                "excluded_session_count",
            }
            <= windows[name].keys()
            for name in ("today", "7_days", "30_days")
        ):
            return True
        if load.get(LEGACY_IDENTITY_UNRESOLVED_KEY) is True:
            continue
        if _stored_signature_direction(load) == "off":
            return True
        component_id = str(load.get("component_id") or "").strip()
        if not component_id or component_id in component_ids:
            return True
        component_ids.add(component_id)
        if not all(
            str(load.get(key) or "").strip()
            for key in (
                "component_fingerprint",
                "on_signature_id",
                "on_signature_fingerprint",
            )
        ):
            return True
    return False


def migrate_unknown_load_inventory(
    *,
    circuit_id: str,
    existing_state: Mapping[str, Any],
    signature_payloads: Iterable[Mapping[str, Any]],
    sessions: Iterable[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    time_zone: str = "UTC",
    session_history_max_items: int | None = None,
) -> dict[str, Any]:
    """Upgrade a stale inventory without discarding rows that lack edge evidence."""

    signatures = [
        signature
        for payload in signature_payloads
        if (signature := _signature_from_payload(payload)) is not None
    ]
    components = _unknown_load_components(signatures)
    session_list = tuple(sessions) if sessions is not None else ()
    if session_list and now is not None:
        rebuilt = build_unknown_load_inventory(
            circuit_id=circuit_id,
            signatures=signatures,
            edges=(),
            sessions=session_list,
            now=now,
            time_zone=time_zone,
            session_history_max_items=session_history_max_items,
            existing_state=existing_state,
        )
        existing_loads = [
            dict(load)
            for load in existing_state.get("unknown_loads", ())
            if isinstance(load, Mapping)
        ]
        covered_indexes = {
            index
            for component in components
            for index, load in enumerate(existing_loads)
            if _load_identifies_component(load, component)
            or _legacy_load_matches_on_signature(load, component.on_signature)
            or (
                component.off_signature is not None
                and _load_is_off_duplicate(load, component.off_signature)
            )
        }
        retained = [
            _migrated_unclassified_row(load)
            for index, load in enumerate(existing_loads)
            if index not in covered_indexes
        ]
        if retained:
            legacy = _legacy_unverified_inventory(
                circuit_id, retained, existing_state
            )
            loads = [*rebuilt["unknown_loads"], *legacy["unknown_loads"]]
            loads.sort(
                key=lambda load: (
                    str(load.get("component_id") or load.get("signature_id") or ""),
                    str(load.get("signature_id") or ""),
                )
            )
            rebuilt.update(_inventory_aggregate(circuit_id, loads))
            rebuilt["estimate_status"] = _worst_estimate_status(
                str(load.get("estimate_status") or "legacy_unverified")
                for load in loads
            )
            legacy_observed = legacy.get("observation_started_at")
            if legacy_observed:
                rebuilt["observation_started_at"] = _observation_started_at(
                    _as_utc_datetime(legacy_observed), rebuilt
                )
        elif not rebuilt["unknown_loads"]:
            rebuilt["estimate_status"] = "partial_history"
        return rebuilt
    existing_loads = [
        dict(load)
        for load in existing_state.get("unknown_loads", ())
        if isinstance(load, Mapping)
    ]
    retained: list[dict[str, Any]] = []
    used_indexes: set[int] = set()

    for component in components:
        candidates = [
            index
            for index, load in enumerate(existing_loads)
            if _load_identifies_component(load, component)
        ]
        if not candidates:
            candidates = [
                index
                for index, load in enumerate(existing_loads)
                if _legacy_load_matches_on_signature(load, component.on_signature)
            ]
        if len(candidates) != 1:
            continue
        index = candidates[0]
        if index in used_indexes:
            continue
        used_indexes.add(index)
        retained.append(_migrated_component_row(existing_loads[index], component))

        if component.off_signature is not None:
            used_indexes.update(
                index
                for index, load in enumerate(existing_loads)
                if index not in used_indexes
                and _load_is_off_duplicate(load, component.off_signature)
            )

    retained_component_ids = {
        str(load.get("component_id") or "").strip() for load in retained
    }
    for index, load in enumerate(existing_loads):
        if index in used_indexes:
            continue
        component_id = str(load.get("component_id") or "").strip()
        if component_id and component_id in retained_component_ids:
            continue
        retained.append(_migrated_unclassified_row(load))
        if component_id:
            retained_component_ids.add(component_id)

    retained.sort(
        key=lambda load: (
            str(load.get("component_id") or load.get("signature_id") or ""),
            str(load.get("signature_id") or ""),
        )
    )
    return _legacy_unverified_inventory(circuit_id, retained, existing_state)


def _inventory_aggregate(
    circuit_id: str,
    loads: list[dict[str, Any]],
) -> dict[str, Any]:
    active_count = sum(
        1
        for load in loads
        if load.get("running_state") == "probably_on"
        and load.get("separation_status") != "ambiguous"
    )
    ambiguous_count = sum(
        1 for load in loads if load.get("separation_status") == "ambiguous"
    )
    return {
        "circuit_id": circuit_id,
        "schema_version": UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION,
        "unknown_load_count": len(loads),
        "active_unknown_load_count": active_count,
        "ambiguous_unknown_load_count": ambiguous_count,
        "simultaneous_unknown_event_count": 0,
        "unknown_estimated_energy_today_kwh": _sum_loads(
            loads, "estimated_energy_today_kwh"
        ),
        "unknown_estimated_energy_7_days_kwh": _sum_loads(
            loads, "estimated_energy_7_days_kwh"
        ),
        "unknown_estimated_energy_30_days_kwh": _sum_loads(
            loads, "estimated_energy_30_days_kwh"
        ),
        "largest_unknown_load": _largest_load(loads, "typical_watts"),
        "highest_unknown_energy_load": _largest_load(
            loads, "estimated_energy_today_kwh"
        ),
        "unknown_loads": loads,
    }


def _legacy_unverified_inventory(
    circuit_id: str,
    loads: list[dict[str, Any]],
    existing_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve prior values when history was not retained for recomputation."""

    observation_started = _observation_started_at(
        _edge_observation_started_at(loads), existing_state
    )
    for load in loads:
        status = "legacy_unverified"
        load["estimate_status"] = status
        load["estimate_status_by_window"] = {
            name: status for name in ("today", "7_days", "30_days")
        }
        load["observation_started_at"] = observation_started
        load["runtime_window_definition"] = _runtime_window_definition()
        load["runtime_windows"] = {
            name: {
                "coverage_start": None,
                "coverage_end": None,
                "coverage_days": 0.0,
                "nominal_days": days,
                "estimate_status": status,
                "included_session_count": 0,
                "excluded_session_count": 0,
            }
            for name, days in (("today", 0.0), ("7_days", 7.0), ("30_days", 30.0))
        }
    inventory = _inventory_aggregate(circuit_id, loads)
    inventory.update(
        {
            "observation_started_at": observation_started,
            "runtime_window_definition": _runtime_window_definition(),
            "estimate_status": "legacy_unverified",
        }
    )
    return inventory


def _signature_from_payload(payload: Mapping[str, Any]) -> NilmSignature | None:
    signature_id = str(payload.get("signature_id") or "").strip()
    try:
        watts = float(payload.get("median_delta_w"))
    except (TypeError, ValueError):
        return None
    if not signature_id:
        return None
    return NilmSignature(
        signature_id=signature_id,
        median_delta_w=watts,
        median_delta_var=_optional_float(payload.get("median_delta_var")),
        median_delta_va=_optional_float(payload.get("median_delta_va")),
        median_delta_pf=_optional_float(payload.get("median_delta_pf")),
        occurrence_count=_nonnegative_int(payload.get("occurrence_count")),
        confidence=_finite_or_zero(payload.get("confidence")),
        dominant_leg=str(payload.get("dominant_leg") or "unknown"),
        split_phase_type=str(payload.get("split_phase_type") or "unknown"),
        median_leg_a_delta_w=_optional_float(payload.get("median_leg_a_delta_w")),
        median_leg_b_delta_w=_optional_float(payload.get("median_leg_b_delta_w")),
        leg_balance_ratio=_optional_float(payload.get("leg_balance_ratio")),
    )


def _load_identifies_component(
    load: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> bool:
    return any(
        str(load.get(key) or "").strip() == value
        for key, value in (
            ("component_id", component.component_id),
            ("signature_id", component.on_signature.signature_id),
            ("on_signature_id", component.on_signature.signature_id),
            ("component_fingerprint", component.component_fingerprint),
            ("on_signature_fingerprint", component.component_fingerprint),
            ("signature_fingerprint", component.component_fingerprint),
            ("fingerprint", component.component_fingerprint),
        )
    )


def _load_is_off_duplicate(
    load: Mapping[str, Any],
    off_signature: NilmSignature,
) -> bool:
    return str(load.get("signature_id") or "").strip() == off_signature.signature_id


def _migrated_component_row(
    load: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> dict[str, Any]:
    migrated = dict(load)
    migrated.pop(LEGACY_IDENTITY_UNRESOLVED_KEY, None)
    migrated.update(
        {
            "signature_id": component.on_signature.signature_id,
            "component_id": component.component_id,
            "component_fingerprint": component.component_fingerprint,
            "on_signature_id": component.on_signature.signature_id,
            "on_signature_fingerprint": nilm_signature_fingerprint(
                component.on_signature
            ),
            "off_signature_id": (
                component.off_signature.signature_id
                if component.off_signature is not None
                else None
            ),
            "off_signature_fingerprint": (
                nilm_signature_fingerprint(component.off_signature)
                if component.off_signature is not None
                else None
            ),
            "signature_pair_status": component.pair_status,
            "signature_pair_score": (
                round(component.pair_score, 3)
                if component.pair_score is not None
                else None
            ),
            "alternate_signature_pair_count": component.alternate_pair_count,
            "matched_on_edge_count": int(load.get("matched_on_edge_count") or 0),
            "matched_off_edge_count": int(load.get("matched_off_edge_count") or 0),
            "ambiguous_edge_count": int(load.get("ambiguous_edge_count") or 0),
        }
    )
    return migrated


def _migrated_unclassified_row(load: Mapping[str, Any]) -> dict[str, Any]:
    """Mark an opaque legacy row as retained so migration does not repeat."""

    migrated = dict(load)
    migrated[LEGACY_IDENTITY_UNRESOLVED_KEY] = True
    return migrated


def _stored_signature_direction(value: Mapping[str, Any]) -> str:
    signature_id = str(value.get("signature_id") or "").strip()
    try:
        watts = float(value.get("median_delta_w"))
    except (TypeError, ValueError):
        return "off" if nilm_signature_is_off_direction(signature_id) else "unknown"
    return _unknown_signature_direction(
        NilmSignature(signature_id=signature_id, median_delta_w=watts)
    )


def _optional_float(value: Any) -> float | None:
    try:
        number = None if value is None else float(value)
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _finite_or_zero(value: Any) -> float:
    number = _optional_float(value)
    return number if number is not None else 0.0


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _unknown_signature_direction(signature: NilmSignature) -> str:
    """Classify a raw signature without trusting malformed identifier metadata."""

    watts = float(signature.median_delta_w)
    signature_id = signature.signature_id
    fingerprint = nilm_signature_fingerprint(signature)
    is_off_identifier = nilm_signature_is_off_direction(
        signature_id
    ) or nilm_signature_is_off_direction(fingerprint)
    if watts < 0.0:
        return "off"
    if watts > 0.0 and is_off_identifier:
        return "invalid"
    if watts > 0.0 and nilm_signature_is_assignable(signature_id):
        return "on"
    return "unknown"


def _unknown_load_components(
    signatures: Iterable[NilmSignature],
) -> tuple[_UnknownLoadComponent, ...]:
    on_signatures = sorted(
        (
            signature
            for signature in signatures
            if _unknown_signature_direction(signature) == "on"
        ),
        key=lambda signature: signature.signature_id,
    )
    off_signatures = sorted(
        (
            signature
            for signature in signatures
            if _unknown_signature_direction(signature) == "off"
        ),
        key=lambda signature: signature.signature_id,
    )
    candidates = [
        (on_signature, off_signature, score)
        for on_signature in on_signatures
        for off_signature in off_signatures
        if (score := _signature_pair_score(on_signature, off_signature))
        is not None
        and score >= MIN_SIGNATURE_PAIR_SCORE
    ]
    candidates.sort(
        key=lambda candidate: (
            -candidate[2],
            candidate[0].signature_id,
            candidate[1].signature_id,
        )
    )

    ambiguous_counts = _pair_ambiguity_counts(candidates)
    ambiguous_on_ids = set(ambiguous_counts)
    paired_by_on: dict[str, tuple[NilmSignature, float]] = {}
    used_off_ids: set[str] = set()
    for on_signature, off_signature, score in candidates:
        if (
            on_signature.signature_id in ambiguous_on_ids
            or on_signature.signature_id in paired_by_on
            or off_signature.signature_id in used_off_ids
        ):
            continue
        paired_by_on[on_signature.signature_id] = (off_signature, score)
        used_off_ids.add(off_signature.signature_id)

    return tuple(
        _UnknownLoadComponent(
            component_id=on_signature.signature_id,
            component_fingerprint=nilm_signature_fingerprint(on_signature),
            on_signature=on_signature,
            off_signature=(
                paired_by_on[on_signature.signature_id][0]
                if on_signature.signature_id in paired_by_on
                else None
            ),
            pair_status=(
                "ambiguous"
                if on_signature.signature_id in ambiguous_on_ids
                else "paired"
                if on_signature.signature_id in paired_by_on
                else "on_only"
            ),
            pair_score=(
                paired_by_on[on_signature.signature_id][1]
                if on_signature.signature_id in paired_by_on
                else None
            ),
            alternate_pair_count=ambiguous_counts.get(on_signature.signature_id, 0),
        )
        for on_signature in on_signatures
    )


def _pair_ambiguity_counts(
    candidates: list[tuple[NilmSignature, NilmSignature, float]],
) -> dict[str, int]:
    by_on: dict[str, list[tuple[NilmSignature, NilmSignature, float]]] = {}
    by_off: dict[str, list[tuple[NilmSignature, NilmSignature, float]]] = {}
    for candidate in candidates:
        by_on.setdefault(candidate[0].signature_id, []).append(candidate)
        by_off.setdefault(candidate[1].signature_id, []).append(candidate)

    counts: dict[str, int] = {}
    for group in (*by_on.values(), *by_off.values()):
        if len(group) < 2:
            continue
        best_score = max(candidate[2] for candidate in group)
        close = [
            candidate
            for candidate in group
            if best_score - candidate[2] <= SIGNATURE_PAIR_AMBIGUITY_MARGIN
        ]
        if len(close) < 2:
            continue
        for on_signature, _off_signature, _score in close:
            counts[on_signature.signature_id] = max(
                counts.get(on_signature.signature_id, 0),
                len(close) - 1,
            )
    return counts


def _signature_pair_score(
    on_signature: NilmSignature,
    off_signature: NilmSignature,
) -> float | None:
    if (
        _unknown_signature_direction(on_signature) != "on"
        or _unknown_signature_direction(off_signature) != "off"
    ):
        return None
    return _signature_electrical_score(on_signature, off_signature)


def _allocate_unknown_edges(
    components: Iterable[_UnknownLoadComponent],
    edges: Iterable[NilmEdge],
) -> _UnknownLoadAllocation:
    component_list = tuple(components)
    allocated: dict[str, list[NilmEdge]] = {
        component.component_id: [] for component in component_list
    }
    matched_on_counts = {component.component_id: 0 for component in component_list}
    matched_off_counts = {component.component_id: 0 for component in component_list}
    ambiguous_counts = {component.component_id: 0 for component in component_list}
    ambiguous_ids = {
        component.component_id
        for component in component_list
        if component.pair_status == "ambiguous"
    }
    edge_list = list(edges)
    simultaneous_timestamps = _simultaneous_timestamps(edge_list)

    for _index, edge in sorted(
        enumerate(edge_list),
        key=lambda item: (item[1].timestamp, item[0]),
    ):
        if edge.timestamp in simultaneous_timestamps:
            simultaneous_candidates = [
                component
                for component in component_list
                if component.component_id not in ambiguous_ids
                and _component_simultaneous_match(component, edge)
            ]
            for component in simultaneous_candidates:
                ambiguous_counts[component.component_id] += 1
                ambiguous_ids.add(component.component_id)
            continue
        candidates = [
            (component, score)
            for component in component_list
            if component.component_id not in ambiguous_ids
            and (score := _component_edge_score(component, edge)) is not None
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda candidate: (-candidate[1], candidate[0].component_id)
        )

        winner, winner_score = candidates[0]
        close = [
            component
            for component, score in candidates
            if winner_score - score <= EDGE_COMPONENT_AMBIGUITY_MARGIN
        ]
        if len(close) > 1:
            for component in close:
                ambiguous_counts[component.component_id] += 1
                ambiguous_ids.add(component.component_id)
            continue

        allocated[winner.component_id].append(edge)
        if edge.direction == "on":
            matched_on_counts[winner.component_id] += 1
        else:
            matched_off_counts[winner.component_id] += 1

    return _UnknownLoadAllocation(
        edges_by_component={
            component_id: tuple(component_edges)
            for component_id, component_edges in allocated.items()
        },
        matched_on_count_by_component=matched_on_counts,
        matched_off_count_by_component=matched_off_counts,
        ambiguous_edge_count_by_component=ambiguous_counts,
        ambiguous_component_ids=frozenset(ambiguous_ids),
    )


def _component_edge_score(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> float | None:
    prototype = _component_edge_prototype(component, edge)
    return _signature_edge_score(prototype, edge) if prototype is not None else None


def _component_simultaneous_match(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> bool:
    prototype = _component_edge_prototype(component, edge)
    if prototype is None:
        return False
    topology_matches = (
        prototype.split_phase_type == "unknown"
        or edge.split_phase_type == "unknown"
        or prototype.split_phase_type == edge.split_phase_type
    )
    return topology_matches and _within_tolerance(
        abs(edge.delta_w),
        abs(float(prototype.median_delta_w)),
        0.2,
        50.0,
    )


def _component_edge_prototype(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> NilmSignature | None:
    direction = str(edge.direction or "").casefold()
    if direction == "on" and edge.delta_w > 0.0:
        return component.on_signature
    if direction != "off" or edge.delta_w >= 0.0:
        return None
    if component.off_signature is not None:
        return component.off_signature
    return component.on_signature if component.pair_status == "on_only" else None


def _signature_edge_score(signature: NilmSignature, edge: NilmEdge) -> float | None:
    reference = NilmSignature(
        signature_id=signature.signature_id,
        median_delta_w=edge.delta_w,
        median_delta_var=edge.delta_var,
        median_delta_va=edge.delta_va,
        median_delta_pf=edge.delta_pf,
        dominant_leg=edge.dominant_leg,
        split_phase_type=edge.split_phase_type,
    )
    return _signature_electrical_score(signature, reference)


def _signature_electrical_score(
    left: NilmSignature,
    right: NilmSignature,
) -> float | None:
    left_watts = abs(float(left.median_delta_w))
    right_watts = abs(float(right.median_delta_w))
    if not _within_tolerance(right_watts, left_watts, 0.2, 50.0):
        return None
    scores = [_tolerance_score(right_watts, left_watts, 0.2, 50.0)]
    for left_value, right_value, ratio, floor in (
        (left.median_delta_var, right.median_delta_var, 0.35, 75.0),
    ):
        if left_value is None or right_value is None:
            continue
        if not _within_tolerance(abs(right_value), abs(left_value), ratio, floor):
            return None
        scores.append(
            _tolerance_score(abs(right_value), abs(left_value), ratio, floor)
        )
    for left_value, right_value, ratio, floor in (
        (left.median_delta_va, right.median_delta_va, 0.35, 75.0),
        (left.median_delta_pf, right.median_delta_pf, 0.5, 0.10),
    ):
        if left_value is None or right_value is None:
            continue
        if _within_tolerance(abs(right_value), abs(left_value), ratio, floor):
            scores.append(
                _tolerance_score(abs(right_value), abs(left_value), ratio, floor)
            )
    for left_value, right_value in (
        (left.split_phase_type, right.split_phase_type),
        (left.dominant_leg, right.dominant_leg),
    ):
        if left_value == "unknown" or right_value == "unknown":
            continue
        if left_value != right_value:
            return None
        scores.append(1.0)
    return round(sum(scores) / len(scores), 6)


def _tolerance_score(
    value: float,
    reference: float,
    ratio: float,
    floor: float,
) -> float:
    tolerance = max(abs(reference) * ratio, floor)
    return max(0.0, 1.0 - (abs(value - reference) / tolerance))


def _as_utc_datetime(value: datetime | str | Any) -> datetime:
    """Parse storage timestamps, treating legacy naive values as UTC."""

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("timestamp is not a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _edge_with_utc_timestamp(edge: NilmEdge) -> NilmEdge:
    """Apply the legacy UTC convention before edge timestamps reach runtime math."""

    timestamp = _as_utc_datetime(edge.timestamp)
    return replace(edge, timestamp=timestamp) if timestamp != edge.timestamp else edge


def _runtime_windows(
    now: datetime,
    time_zone: str,
) -> dict[str, tuple[datetime, datetime, float]]:
    """Build local-midnight and elapsed-time windows in UTC."""

    try:
        local_zone = ZoneInfo(time_zone)
    except (TypeError, ZoneInfoNotFoundError):
        local_zone = UTC
    local_now = now.astimezone(local_zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_midnight.astimezone(UTC)
    return {
        "today": (today_start, now, (now - today_start).total_seconds() / 86_400),
        "7_days": (now - timedelta(hours=168), now, 7.0),
        "30_days": (now - timedelta(hours=720), now, 30.0),
    }


def _runtime_window_definition() -> dict[str, str]:
    return {
        "today": "configured_local_midnight_to_now",
        "7_days": "trailing_168_elapsed_hours_to_now",
        "30_days": "trailing_720_elapsed_hours_to_now",
    }


def _normalize_unknown_load_sessions(
    sessions: Iterable[Mapping[str, Any]], now: datetime
) -> tuple[tuple[_NormalizedUnknownLoadSession, ...], int]:
    """Validate persisted sessions without allowing malformed storage to raise."""

    normalized: list[_NormalizedUnknownLoadSession] = []
    excluded = 0
    for raw in sessions:
        if not isinstance(raw, Mapping):
            excluded += 1
            continue
        try:
            session_id = str(raw.get("session_id") or "").strip()
            fingerprint = str(raw.get("signature_fingerprint") or "").strip()
            if not session_id or not fingerprint:
                raise ValueError("missing session identity")
            if bool(raw.get("ambiguous")) or bool(raw.get("known_load_masked")):
                raise ValueError("excluded session evidence")
            start = _as_utc_datetime(raw.get("start"))
            end_value = raw.get("end")
            is_open = end_value is None
            end = now if is_open else _as_utc_datetime(end_value)
            if start > now or end < start or not all(
                isfinite(value)
                for value in ((end - start).total_seconds(),)
            ):
                raise ValueError("invalid session interval")
            identities = frozenset(
                value
                for value in (
                    str(raw.get("component_id") or "").strip(),
                    str(raw.get("component_fingerprint") or "").strip(),
                    str(raw.get("signature_id") or "").strip(),
                    fingerprint,
                    str(raw.get("on_signature_id") or "").strip(),
                    str(raw.get("on_signature_fingerprint") or "").strip(),
                )
                if value
            )
            normalized.append(
                _NormalizedUnknownLoadSession(
                    session_id=session_id,
                    signature_fingerprint=fingerprint,
                    start=start,
                    end=end,
                    is_open=is_open,
                    on_edge_id=str(raw.get("on_edge_id") or "").strip(),
                    identities=identities,
                )
            )
        except (TypeError, ValueError, OverflowError):
            excluded += 1
    return tuple(normalized), excluded


def _session_owner_candidates(
    session: _NormalizedUnknownLoadSession,
    components: Iterable[_UnknownLoadComponent],
    existing_state: Mapping[str, Any],
) -> tuple[str, ...]:
    """Resolve only explicit component/signature identities; never by watts."""

    candidates: list[str] = []
    for component in components:
        identities = {
            component.component_id,
            component.component_fingerprint,
            component.on_signature.signature_id,
            nilm_signature_fingerprint(component.on_signature),
            nilm_signature_fingerprint_v1(component.on_signature),
        }
        if session.identities & identities:
            candidates.append(component.component_id)
            continue
        loads = existing_state.get("unknown_loads")
        if not isinstance(loads, list):
            continue
        for load in loads:
            if not isinstance(load, Mapping) or not _load_identifies_component(
                load, component
            ):
                continue
            legacy_identities = {
                str(load.get(key) or "").strip()
                for key in (
                    "component_id",
                    "component_fingerprint",
                    "signature_id",
                    "on_signature_id",
                    "on_signature_fingerprint",
                    "signature_fingerprint",
                    "fingerprint",
                )
            }
            if session.identities & (legacy_identities - {""}):
                candidates.append(component.component_id)
                break
    return tuple(sorted(set(candidates)))


def _deduplicate_owned_sessions(
    sessions: Iterable[_OwnedUnknownLoadSession],
) -> tuple[tuple[_OwnedUnknownLoadSession, ...], set[str]]:
    """Apply stable session/on-edge/interval deduplication conservatively."""

    retained = list(sessions)
    excluded_components: set[str] = set()
    for key_fn in (
        lambda item: ("session", item.session.session_id),
        lambda item: ("on_edge", item.session.on_edge_id)
        if item.session.on_edge_id
        else (
            "interval",
            item.component_id,
            item.session.start,
            item.session.end,
        ),
        lambda item: (
            "interval", item.component_id, item.session.start, item.session.end
        ),
    ):
        grouped: dict[tuple[Any, ...], list[_OwnedUnknownLoadSession]] = {}
        for item in retained:
            grouped.setdefault(key_fn(item), []).append(item)
        next_retained: list[_OwnedUnknownLoadSession] = []
        for group in grouped.values():
            if len(group) == 1:
                next_retained.extend(group)
                continue
            components = {item.component_id for item in group}
            closed = [item for item in group if not item.session.is_open]
            if len(components) != 1 or (
                len(closed) > 1
                and len({(item.session.start, item.session.end) for item in closed}) > 1
            ):
                excluded_components.update(components)
                continue
            next_retained.append(closed[0] if closed else group[0])
        retained = next_retained
    return tuple(retained), excluded_components


def _session_inventory_evidence(
    sessions: Iterable[Mapping[str, Any]],
    *,
    components: Iterable[_UnknownLoadComponent],
    now: datetime,
    existing_state: Mapping[str, Any],
) -> _SessionInventoryEvidence:
    component_list = tuple(components)
    normalized, invalid_count = _normalize_unknown_load_sessions(sessions, now)
    owned: list[_OwnedUnknownLoadSession] = []
    excluded = {component.component_id: invalid_count for component in component_list}
    ambiguous_ids: set[str] = set()
    for session in normalized:
        candidates = _session_owner_candidates(session, component_list, existing_state)
        if len(candidates) != 1:
            targets = candidates or tuple(
                component.component_id for component in component_list
            )
            for component_id in targets:
                excluded[component_id] += 1
                if len(candidates) > 1:
                    ambiguous_ids.add(component_id)
            continue
        owned.append(_OwnedUnknownLoadSession(session, candidates[0]))
    retained, dedup_excluded = _deduplicate_owned_sessions(owned)
    for component_id in dedup_excluded:
        excluded[component_id] += 1
        ambiguous_ids.add(component_id)
    return _SessionInventoryEvidence(
        sessions_by_component={
            component.component_id: tuple(
                item for item in retained if item.component_id == component.component_id
            )
            for component in component_list
        },
        excluded_count_by_component=excluded,
        ambiguous_component_ids=frozenset(ambiguous_ids),
        observation_started_at=min((item.start for item in normalized), default=None),
    )


def _clip_session_seconds(
    session: _OwnedUnknownLoadSession, start: datetime, end: datetime
) -> float:
    clipped_start = max(session.session.start, start)
    clipped_end = min(session.session.end, end)
    return max(0.0, (clipped_end - clipped_start).total_seconds())


def _union_session_seconds(
    sessions: Iterable[_OwnedUnknownLoadSession],
    start: datetime,
    end: datetime,
) -> float:
    """Return clipped runtime without counting overlapping intervals twice."""

    intervals = sorted(
        (
            max(item.session.start, start),
            min(item.session.end, end),
        )
        for item in sessions
        if min(item.session.end, end) > max(item.session.start, start)
    )
    if not intervals:
        return 0.0
    total = 0.0
    current_start, current_end = intervals[0]
    for interval_start, interval_end in intervals[1:]:
        if interval_start <= current_end:
            current_end = max(current_end, interval_end)
            continue
        total += (current_end - current_start).total_seconds()
        current_start, current_end = interval_start, interval_end
    return total + (current_end - current_start).total_seconds()


def _estimate_status(
    *,
    ambiguous: bool,
    excluded_count: int,
    observation_started_at: datetime | None,
    window_start: datetime,
    session_history_max_items: int | None,
) -> str:
    if ambiguous:
        return "ambiguous"
    if (
        excluded_count
        or observation_started_at is None
        or observation_started_at > window_start
        or session_history_max_items is not None
    ):
        return "partial_history"
    return "complete"


def _worst_estimate_status(statuses: Iterable[str]) -> str:
    severity = {
        "complete": 0,
        "partial_history": 1,
        "legacy_unverified": 2,
        "ambiguous": 3,
    }
    return max(statuses, key=lambda status: severity.get(status, 3), default="complete")


def _observation_started_at(
    observed: datetime | None, existing_state: Mapping[str, Any]
) -> str | None:
    values = [observed] if observed is not None else []
    try:
        existing = existing_state.get("observation_started_at")
        if existing:
            values.append(_as_utc_datetime(existing))
    except (TypeError, ValueError, OverflowError):
        pass
    return min(values).isoformat() if values else None


def _edge_observation_started_at(loads: Iterable[Mapping[str, Any]]) -> datetime | None:
    observed: list[datetime] = []
    for load in loads:
        try:
            value = load.get("first_seen")
            if value:
                observed.append(_as_utc_datetime(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return min(observed, default=None)


def _add_edge_window_metadata(
    load: dict[str, Any],
    windows: Mapping[str, tuple[datetime, datetime, float]],
    observed: datetime | None,
    existing_state: Mapping[str, Any],
) -> None:
    """Keep edge-only callers schema-compatible without claiming retained history."""

    ambiguous = load.get("separation_status") == "ambiguous"
    status = "ambiguous" if ambiguous else "partial_history"
    included = int(load.get("matched_on_edge_count") or 0)
    load["runtime_windows"] = {
        name: {
            "coverage_start": max(start, observed).isoformat()
            if observed is not None
            else start.isoformat(),
            "coverage_end": end.isoformat(),
            "coverage_days": round(
                max(0.0, (end - max(start, observed)).total_seconds() / 86_400)
                if observed is not None
                else 0.0,
                3,
            ),
            "nominal_days": round(nominal_days, 3),
            "estimate_status": status,
            "included_session_count": included,
            "excluded_session_count": 0,
        }
        for name, (start, end, nominal_days) in windows.items()
    }
    load["estimate_status_by_window"] = {
        name: status for name in windows
    }
    load["estimate_status"] = status
    load["observation_started_at"] = _observation_started_at(observed, existing_state)
    load["runtime_window_definition"] = _runtime_window_definition()


def _unknown_component_session_payload(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
    evidence: _SessionInventoryEvidence,
    *,
    windows: Mapping[str, tuple[datetime, datetime, float]],
    now: datetime,
    existing_state: Mapping[str, Any],
    session_history_max_items: int | None,
) -> dict[str, Any]:
    """Assemble one component payload from reconstructed persisted runs."""

    payload = _unknown_component_payload(
        component, allocation, now=now, existing_state=existing_state
    )
    existing_load = _existing_component_state(existing_state, component)
    for key in ("user_label", "labels"):
        if key in existing_load:
            payload[key] = existing_load[key]
    sessions = evidence.sessions_by_component[component.component_id]
    ambiguous = (
        payload["separation_status"] == "ambiguous"
        or component.component_id in evidence.ambiguous_component_ids
    )
    open_sessions = [item for item in sessions if item.session.is_open]
    if ambiguous or len(open_sessions) > 1:
        payload["running_state"] = "unknown"
        payload["current_runtime_minutes"] = 0.0
        ambiguous = True
    elif open_sessions:
        payload["running_state"] = "probably_on"
        payload["current_runtime_minutes"] = round(
            (now - open_sessions[0].session.start).total_seconds() / 60.0, 3
        )
        payload["last_start"] = open_sessions[0].session.start.isoformat()
        payload["last_stop"] = None
    else:
        payload["running_state"] = "probably_off"
        payload["current_runtime_minutes"] = 0.0

    estimate_statuses: dict[str, str] = {}
    runtime_windows: dict[str, dict[str, Any]] = {}
    for name, (start, end, nominal_days) in windows.items():
        seconds = (
            0.0 if ambiguous else _union_session_seconds(sessions, start, end)
        )
        runtime_minutes = round(seconds / 60.0, 3)
        status = _estimate_status(
            ambiguous=ambiguous,
            excluded_count=evidence.excluded_count_by_component[component.component_id],
            observation_started_at=evidence.observation_started_at,
            window_start=start,
            session_history_max_items=session_history_max_items,
        )
        estimate_statuses[name] = status
        runtime_windows[name] = {
            "coverage_start": max(start, evidence.observation_started_at)
            .isoformat()
            if evidence.observation_started_at is not None
            else start.isoformat(),
            "coverage_end": end.isoformat(),
            "coverage_days": round(
                max(
                    0.0,
                    (
                        end - max(start, evidence.observation_started_at)
                    ).total_seconds()
                    / 86_400,
                )
                if evidence.observation_started_at is not None
                else 0.0,
                3,
            ),
            "nominal_days": round(nominal_days, 3),
            "estimate_status": status,
            "included_session_count": sum(
                1 for item in sessions if _clip_session_seconds(item, start, end) > 0.0
            )
            if not ambiguous
            else 0,
            "excluded_session_count": evidence.excluded_count_by_component[
                component.component_id
            ],
        }
        suffix = {"today": "today", "7_days": "7_days", "30_days": "30_days"}[name]
        payload[f"runtime_{suffix}_minutes"] = runtime_minutes
        payload[f"estimated_energy_{suffix}_kwh"] = _estimated_kwh(
            float(payload["typical_watts"]), runtime_minutes
        )
    payload["runtime_windows"] = runtime_windows
    payload["estimate_status_by_window"] = estimate_statuses
    payload["estimate_status"] = _worst_estimate_status(estimate_statuses.values())
    payload["observation_started_at"] = _observation_started_at(
        evidence.observation_started_at, existing_state
    )
    payload["runtime_window_definition"] = _runtime_window_definition()
    payload["separation_status"] = "ambiguous" if ambiguous else "separable"
    payload["energy_estimate_confidence"] = (
        0.0 if ambiguous else float(payload["confidence"])
    )
    return payload


def _unknown_component_payload(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
    *,
    now: datetime,
    existing_state: Mapping[str, Any],
) -> dict[str, Any]:
    estimate = estimate_unknown_load(component.on_signature)
    matching_edges = list(allocation.edges_by_component[component.component_id])
    first_seen = min((edge.timestamp for edge in matching_edges), default=None)
    last_seen = max((edge.timestamp for edge in matching_edges), default=None)
    runtime_minutes, running_state, last_start, last_stop = _runtime_state(
        matching_edges,
        now,
    )
    ambiguous = (
        component.pair_status == "ambiguous"
        or component.component_id in allocation.ambiguous_component_ids
    )
    if ambiguous:
        runtime_minutes = 0.0
        running_state = "unknown"

    energy_today = _estimated_kwh(estimate["typical_watts"], runtime_minutes)
    existing_load = _existing_component_state(existing_state, component)
    review_state = str(existing_load.get("review_state") or "new")
    if review_state == "merged":
        review_state = "merged"
    evidence = list(estimate["evidence"])
    evidence.append(_component_evidence(component, allocation))

    return {
        **estimate,
        "component_id": component.component_id,
        "component_fingerprint": component.component_fingerprint,
        "on_signature_id": component.on_signature.signature_id,
        "on_signature_fingerprint": nilm_signature_fingerprint(
            component.on_signature
        ),
        "off_signature_id": (
            component.off_signature.signature_id
            if component.off_signature is not None
            else None
        ),
        "off_signature_fingerprint": (
            nilm_signature_fingerprint(component.off_signature)
            if component.off_signature is not None
            else None
        ),
        "signature_pair_status": component.pair_status,
        "signature_pair_score": (
            round(component.pair_score, 3)
            if component.pair_score is not None
            else None
        ),
        "alternate_signature_pair_count": component.alternate_pair_count,
        "matched_on_edge_count": allocation.matched_on_count_by_component[
            component.component_id
        ],
        "matched_off_edge_count": allocation.matched_off_count_by_component[
            component.component_id
        ],
        "ambiguous_edge_count": allocation.ambiguous_edge_count_by_component[
            component.component_id
        ],
        "evidence": evidence,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "review_state": review_state,
        "separation_status": "ambiguous" if ambiguous else "separable",
        "running_state": running_state,
        "last_start": last_start.isoformat() if last_start else None,
        "last_stop": last_stop.isoformat() if last_stop else None,
        "current_runtime_minutes": runtime_minutes
        if running_state == "probably_on"
        else 0.0,
        "runtime_today_minutes": runtime_minutes,
        "runtime_7_days_minutes": runtime_minutes,
        "runtime_30_days_minutes": runtime_minutes,
        "estimated_energy_today_kwh": energy_today,
        "estimated_energy_7_days_kwh": energy_today,
        "estimated_energy_30_days_kwh": energy_today,
        "energy_estimate_confidence": 0.0
        if ambiguous
        else float(estimate["confidence"]),
    }


def _component_evidence(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
) -> str:
    if component.pair_status == "paired" and component.off_signature is not None:
        return (
            "Paired "
            f"{allocation.matched_on_count_by_component[component.component_id]} ON "
            "events with "
            f"{allocation.matched_off_count_by_component[component.component_id]} OFF "
            f"events using {component.on_signature.signature_id} and "
            f"{component.off_signature.signature_id}."
        )
    if component.pair_status == "ambiguous":
        return (
            "Multiple component/signature matches were too close to separate "
            "conservatively."
        )
    return (
        "No separate recurring OFF signature is established; compatible negative "
        "edges use the ON-magnitude fallback."
    )


def _runtime_state(
    edges: list[NilmEdge],
    now: datetime,
) -> tuple[float, str, datetime | None, datetime | None]:
    running = False
    last_start: datetime | None = None
    last_stop: datetime | None = None
    runtime_minutes = 0.0

    for edge in edges:
        if edge.direction == "on" and not running:
            running = True
            last_start = edge.timestamp
            continue
        if edge.direction == "off" and running and last_start is not None:
            runtime_minutes += max(
                0.0,
                (edge.timestamp - last_start).total_seconds() / 60.0,
            )
            running = False
            last_stop = edge.timestamp

    if running and last_start is not None:
        runtime_minutes += max(0.0, (now - last_start).total_seconds() / 60.0)

    return (
        round(runtime_minutes, 3),
        "probably_on" if running else "probably_off",
        last_start,
        last_stop,
    )


def _ambiguous_signature_ids(
    signatures: list[NilmSignature],
    edges: list[NilmEdge],
) -> set[str]:
    simultaneous_timestamps = _simultaneous_timestamps(edges)
    if not simultaneous_timestamps:
        return set()

    ambiguous_ids: set[str] = set()
    for signature in signatures:
        if any(
            edge.timestamp in simultaneous_timestamps
            and _watts_topology_match(signature, edge)
            for edge in edges
        ):
            ambiguous_ids.add(signature.signature_id)
    return ambiguous_ids


def _watts_topology_match(signature: NilmSignature, edge: NilmEdge) -> bool:
    target_watts = abs(float(signature.median_delta_w))
    topology_match = (
        signature.split_phase_type == "unknown"
        or edge.split_phase_type == "unknown"
        or signature.split_phase_type == edge.split_phase_type
    )
    return (
        _within_tolerance(abs(edge.delta_w), target_watts, 0.2, 50.0)
        and topology_match
    )


def _simultaneous_timestamps(edges: list[NilmEdge]) -> set[datetime]:
    counts: dict[datetime, int] = {}
    for edge in edges:
        counts[edge.timestamp] = counts.get(edge.timestamp, 0) + 1
    return {timestamp for timestamp, count in counts.items() if count > 1}


def _simultaneous_unknown_event_count(edges: list[NilmEdge]) -> int:
    simultaneous = _simultaneous_timestamps(edges)
    return sum(1 for edge in edges if edge.timestamp in simultaneous)


def _estimated_kwh(watts: float, runtime_minutes: float) -> float:
    return round((float(watts) * float(runtime_minutes)) / 60000.0, 3)


def _sum_loads(loads: list[dict[str, Any]], key: str) -> float:
    return round(sum(_load_number(load, key) for load in loads), 3)


def _largest_load(loads: list[dict[str, Any]], key: str) -> str | None:
    identified_loads = [
        load for load in loads if str(load.get("signature_id") or "").strip()
    ]
    if not identified_loads:
        return None
    return str(
        max(identified_loads, key=lambda load: _load_number(load, key))["signature_id"]
    )


def _load_number(load: Mapping[str, Any], key: str) -> float:
    return _optional_float(load.get(key)) or 0.0


def _existing_component_state(
    existing_state: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> Mapping[str, Any]:
    loads = existing_state.get("unknown_loads") if existing_state else None
    if not isinstance(loads, list):
        return {}
    mappings = [load for load in loads if isinstance(load, Mapping)]
    for load in mappings:
        if load.get("component_id") == component.component_id:
            return load
    for load in mappings:
        if load.get("signature_id") in {
            component.component_id,
            component.on_signature.signature_id,
        } or load.get("on_signature_id") == component.on_signature.signature_id:
            return load
    for load in mappings:
        if (
            load.get("component_fingerprint") == component.component_fingerprint
            or load.get("on_signature_fingerprint")
            == component.component_fingerprint
        ):
            return load
    legacy_matches = [
        load
        for load in mappings
        if _legacy_load_matches_on_signature(load, component.on_signature)
    ]
    if len(legacy_matches) == 1:
        return legacy_matches[0]

    if component.pair_status == "paired" and component.off_signature is not None:
        paired_off_matches = [
            load
            for load in mappings
            if load.get("signature_id") == component.off_signature.signature_id
        ]
        if len(paired_off_matches) == 1:
            return paired_off_matches[0]
    return {}


def _legacy_load_matches_on_signature(
    load: Mapping[str, Any],
    signature: NilmSignature,
) -> bool:
    try:
        typical_watts = float(load.get("typical_watts"))
    except (TypeError, ValueError):
        return False
    if not _within_tolerance(
        typical_watts,
        abs(float(signature.median_delta_w)),
        0.2,
        50.0,
    ):
        return False
    stored_topology = str(load.get("split_phase_type") or "unknown")
    return (
        stored_topology == "unknown"
        or signature.split_phase_type == "unknown"
        or stored_topology == signature.split_phase_type
    )


def _existing_load_state(
    existing_state: Mapping[str, Any],
    signature_id: str,
) -> Mapping[str, Any]:
    """Return legacy state for callers outside component inventory construction."""

    loads = existing_state.get("unknown_loads") if existing_state else None
    if not isinstance(loads, list):
        return {}
    for load in loads:
        if isinstance(load, Mapping) and load.get("signature_id") == signature_id:
            return load
    return {}


def _within_tolerance(
    value: float,
    reference: float,
    ratio: float,
    floor: float,
) -> bool:
    return abs(value - reference) <= max(abs(reference) * ratio, floor)


def _likely_type(
    signature: NilmSignature,
    *,
    typical_watts: float,
    typical_var: float | None,
    typical_va: float | None,
    typical_power_factor: float | None,
    voltage_class: str,
) -> str:
    if not _has_enough_evidence(signature):
        return "unknown"

    if typical_var is None or typical_va is None or typical_power_factor is None:
        return "unknown"
    reactive_ratio = typical_var / max(typical_watts, 1.0)
    if (
        voltage_class == "240 V"
        and signature.split_phase_type == "balanced_240v"
        and typical_watts >= 1000.0
        and reactive_ratio <= 0.12
        and typical_power_factor >= 0.95
    ):
        return "heating_element_candidate"

    if (
        voltage_class == "120 V"
        and signature.split_phase_type in {"single_leg_a", "single_leg_b"}
        and typical_watts >= 150.0
        and reactive_ratio >= 0.25
        and typical_power_factor <= 0.9
    ):
        return "motor"

    if typical_va >= 100.0 and typical_var >= 75.0 and reactive_ratio >= 0.75:
        return "power_electronics"

    return "unknown"


def _has_enough_evidence(signature: NilmSignature) -> bool:
    return (
        signature.occurrence_count >= MIN_OCCURRENCES
        and signature.confidence >= MIN_CONFIDENCE
    )


def _voltage_class(split_phase_type: str) -> str:
    if split_phase_type == "balanced_240v":
        return "240 V"
    if split_phase_type in {"single_leg_a", "single_leg_b"}:
        return "120 V"
    if split_phase_type == "imbalanced_240v_or_mixed":
        return "mixed"
    return "unknown"


def _display_name(likely_type: str, voltage_class: str) -> str:
    if likely_type == "heating_element_candidate":
        return "Estimated 240 V heating element candidate"
    if likely_type == "motor":
        voltage = "120 V" if voltage_class == "120 V" else "unknown-voltage"
        return f"Estimated possible {voltage} motor-like unknown load"
    if likely_type == "power_electronics":
        return "Estimated possible power-electronics unknown load"
    return "Estimated unknown load"


def _evidence(
    signature: NilmSignature,
    *,
    likely_type: str,
    voltage_class: str,
    typical_watts: float,
    typical_var: float | None,
    typical_va: float | None,
    typical_power_factor: float | None,
) -> list[str]:
    evidence = [
        (
            f"Estimated from {signature.occurrence_count} recurring unmatched events "
            f"with confidence {signature.confidence:.2f}."
        ),
        (
            "Split-phase evidence suggests "
            f"{_voltage_label(voltage_class)} topology "
            f"({signature.split_phase_type}, dominant leg {signature.dominant_leg})."
        ),
        (
            f"Typical median change is {typical_watts:.1f} W, "
            f"{_optional_metric_text(typical_var, 1)} VAR, "
            f"{_optional_metric_text(typical_va, 1)} VA, "
            f"estimated PF {_optional_metric_text(typical_power_factor, 3)}."
        ),
    ]

    if not _has_enough_evidence(signature):
        evidence.append(
            "Limited recurring evidence; keep this as unknown until more samples "
            "are observed."
        )
    elif likely_type == "heating_element_candidate":
        evidence.append(
            "Possible heating element candidate: balanced 240 V, high W, "
            "low VAR, and PF near unity."
        )
    elif likely_type == "motor":
        evidence.append(
            "Possible motor-like pattern: single-leg 120 V, meaningful "
            "reactive power, and lower estimated PF."
        )
    elif likely_type == "power_electronics":
        evidence.append(
            "Possible power-electronics pattern: VA and VAR are high versus "
            "real power without the single-leg motor pattern."
        )
    else:
        evidence.append("No conservative helper pattern matched; keep this as unknown.")

    return evidence


def _voltage_label(voltage_class: str) -> str:
    if voltage_class == "120 V":
        return "possible 120 V"
    if voltage_class == "240 V":
        return "possible 240 V"
    if voltage_class == "mixed":
        return "mixed"
    return "unknown-voltage"


def _typical_power_factor(
    typical_watts: float,
    typical_va: float | None,
) -> float | None:
    if typical_va is None or typical_va <= 0.0:
        return None
    return round(min(typical_watts / typical_va, 1.0), 3)


def _rounded_abs(value: float | None) -> float | None:
    if value is None:
        return None
    return round(abs(float(value)), 3)


def _optional_abs(value: float | None) -> float | None:
    return None if value is None else abs(float(value))


def _optional_metric_text(value: float | None, decimals: int) -> str:
    return "unavailable" if value is None else f"{value:.{decimals}f}"
