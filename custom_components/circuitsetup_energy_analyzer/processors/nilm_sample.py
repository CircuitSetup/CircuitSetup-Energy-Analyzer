"""NILM sample processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, MutableMapping, MutableSet
from dataclasses import replace
from datetime import timedelta
from typing import Any

from ..models import AlertEvidence, CircuitConfig, CircuitEvent
from ..nilm import (
    NilmEdge,
    NilmEdgeDetector,
    NilmSignature,
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
    nilm_session_to_dict,
    nilm_signature_fingerprint,
    pair_nilm_sessions_for_signatures,
    unmatched_load_percentage,
)
from ..normalize import NormalizedCircuitSample
from ..unknown_loads import build_unknown_load_inventory
from .base import FeatureResult, ProcessingContext, StateUpdate

type NilmEnabledPredicate = Callable[[CircuitConfig], bool]
type DemoNilmSeeder = Callable[[CircuitConfig, Any], None]
type MinDeltaProvider = Callable[[str], float]
type KnownLoadEventsProvider = Callable[
    [str, Iterable[CircuitEvent]],
    Iterable[CircuitEvent],
]
type TopologyObserver = Callable[
    [CircuitConfig, Any, ProcessingContext],
    list[AlertEvidence],
]


class NilmSampleProcessor:
    """Process mains NILM samples into signatures, unknown loads, and alerts."""

    name = "nilm_sample"

    def __init__(
        self,
        *,
        nilm_enabled: NilmEnabledPredicate,
        seed_demo_nilm_state: DemoNilmSeeder,
        min_delta_w_for_circuit: MinDeltaProvider,
        detectors: MutableMapping[str, NilmEdgeDetector],
        total_events_by_circuit: defaultdict[str, int],
        unmatched_edges_by_circuit: defaultdict[str, list[NilmEdge]],
        ignored_signatures: MutableSet[tuple[str, str]],
        known_load_events: KnownLoadEventsProvider,
        observe_topology: TopologyObserver,
        unmatched_edges_max_items: int = 512,
    ) -> None:
        self._nilm_enabled = nilm_enabled
        self._seed_demo_nilm_state = seed_demo_nilm_state
        self._min_delta_w_for_circuit = min_delta_w_for_circuit
        self.detectors = detectors
        self.total_events_by_circuit = total_events_by_circuit
        self.unmatched_edges_by_circuit = unmatched_edges_by_circuit
        self.ignored_signatures = ignored_signatures
        self._known_load_events = known_load_events
        self._observe_topology = observe_topology
        self._unmatched_edges_max_items = max(int(unmatched_edges_max_items), 0)

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
        *,
        events: Iterable[CircuitEvent],
    ) -> FeatureResult:
        """Process one normalized sample for NILM signatures and inventory."""
        circuit_id = circuit_config.circuit_id
        if not self._nilm_enabled(circuit_config):
            return FeatureResult()

        self._seed_demo_nilm_state(circuit_config, sample.timestamp)

        min_delta_w = self._min_delta_w_for_circuit(circuit_id)
        detector = self.detectors.setdefault(
            circuit_id,
            NilmEdgeDetector(
                min_delta_w=min_delta_w,
                confirmation_samples=2,
                confirmation_max_interval=timedelta(seconds=15),
            ),
        )
        detector.min_delta_w = min_delta_w
        edges = detector.process(sample)
        known_events = tuple(self._known_load_events(circuit_id, events))
        alerts: list[AlertEvidence] = []
        store_dirty = False
        existing_unmatched = list(self.unmatched_edges_by_circuit[circuit_id])
        candidate_edges = [*existing_unmatched, *edges]
        matched_edges = ()
        if candidate_edges and known_events:
            mask = mask_known_loads(candidate_edges, known_events)
            matched_edges = mask.matched_edges
            next_unmatched = list(mask.unmatched_edges)
        else:
            next_unmatched = candidate_edges

        next_unmatched = _newest_nilm_edges(
            next_unmatched,
            self._unmatched_edges_max_items,
        )
        if edges:
            self.total_events_by_circuit[circuit_id] += len(edges)
        self.unmatched_edges_by_circuit[circuit_id] = next_unmatched

        for match in matched_edges:
            alerts.extend(
                self._observe_topology(circuit_config, match, context),
            )

        if edges or next_unmatched != existing_unmatched:
            signatures = cluster_recurring_signatures(
                self.unmatched_edges_by_circuit[circuit_id],
            )
            payloads = self._nilm_signature_payloads(
                circuit_id,
                signatures,
                context,
            )
            if payloads != context.store_data.nilm_signatures.get(circuit_id, []):
                context.store_data.nilm_signatures[circuit_id] = payloads
                store_dirty = True
            inventory = build_unknown_load_inventory(
                circuit_id=circuit_id,
                signatures=signatures,
                edges=self.unmatched_edges_by_circuit[circuit_id],
                now=sample.timestamp,
                existing_state=(
                    context.store_data.nilm_unknown_loads_by_circuit.get(
                        circuit_id,
                        {},
                    )
                ),
            )
            if inventory != context.store_data.nilm_unknown_loads_by_circuit.get(
                circuit_id,
            ):
                context.store_data.nilm_unknown_loads_by_circuit[circuit_id] = (
                    inventory
                )
                store_dirty = True
            session_payloads = _nilm_session_history_payloads(
                circuit_id,
                self.unmatched_edges_by_circuit[circuit_id],
                payloads,
                context.store_data.nilm_appliance_assignments_by_circuit.get(
                    circuit_id,
                    [],
                ),
            )
            if session_payloads:
                existing_sessions = (
                    context.store_data.nilm_session_history_by_circuit.get(
                        circuit_id,
                        [],
                    )
                )
                next_sessions = _merge_nilm_session_history(
                    existing_sessions,
                    session_payloads,
                )
                if next_sessions != existing_sessions:
                    context.store_data.nilm_session_history_by_circuit[circuit_id] = (
                        next_sessions
                    )
                    store_dirty = True

        return FeatureResult(
            alerts=alerts,
            notifications=list(alerts),
            state_updates=nilm_state_updates(
                circuit_id,
                context,
                total_events_by_circuit=self.total_events_by_circuit,
                unmatched_edges_by_circuit=self.unmatched_edges_by_circuit,
            ),
            store_dirty=store_dirty,
        )

    def refresh_state(
        self,
        circuit_id: str,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return current NILM state updates without processing a new sample."""
        return FeatureResult(
            state_updates=nilm_state_updates(
                circuit_id,
                context,
                total_events_by_circuit=self.total_events_by_circuit,
                unmatched_edges_by_circuit=self.unmatched_edges_by_circuit,
            ),
        )

    def _nilm_signature_payloads(
        self,
        circuit_id: str,
        signatures: Iterable[NilmSignature],
        context: ProcessingContext,
    ) -> list[dict[str, Any]]:
        existing = {
            str(signature.get("signature_id")): dict(signature)
            for signature in context.store_data.nilm_signatures.get(circuit_id, [])
        }
        existing_by_fingerprint = {
            str(signature.get("feedback_fingerprint")): dict(signature)
            for signature in context.store_data.nilm_signatures.get(circuit_id, [])
            if signature.get("feedback_fingerprint")
        }
        signature_list = list(signatures)
        current_id_by_fingerprint = {
            nilm_signature_fingerprint(signature): signature.signature_id
            for signature in signature_list
        }
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signature in signature_list:
            feedback_fingerprint = nilm_signature_fingerprint(signature)
            current = existing.get(
                signature.signature_id,
                existing_by_fingerprint.get(feedback_fingerprint, {}),
            )
            metadata_current = (
                current if _nilm_signature_metadata_compatible(signature, current)
                else {}
            )
            user_label = metadata_current.get("user_label")
            classified_signature = replace(signature, user_label=user_label)
            ignored = bool(metadata_current.get("ignored")) or (
                (circuit_id, signature.signature_id) in self.ignored_signatures
                and bool(metadata_current)
            )
            payload = {
                "signature_id": signature.signature_id,
                "median_delta_w": signature.median_delta_w,
                "median_delta_var": signature.median_delta_var,
                "median_delta_va": signature.median_delta_va,
                "median_delta_pf": signature.median_delta_pf,
                "median_leg_a_delta_w": signature.median_leg_a_delta_w,
                "median_leg_b_delta_w": signature.median_leg_b_delta_w,
                "leg_balance_ratio": signature.leg_balance_ratio,
                "dominant_leg": signature.dominant_leg,
                "split_phase_type": signature.split_phase_type,
                "occurrence_count": signature.occurrence_count,
                "confidence": signature.confidence,
                "classification": classify_signature(classified_signature),
                "feedback_fingerprint": feedback_fingerprint,
            }
            if user_label:
                payload["user_label"] = user_label
            if ignored:
                payload["ignored"] = True
            for key in ("review_state", "expected", "merged_into"):
                if key in metadata_current:
                    payload[key] = metadata_current[key]
            target_fingerprint = metadata_current.get("merged_into_fingerprint")
            if target_fingerprint:
                payload["merged_into_fingerprint"] = target_fingerprint
                payload["merged_into"] = current_id_by_fingerprint.get(
                    str(target_fingerprint),
                    payload.get("merged_into"),
                )
            payloads.append(payload)
            seen.add(signature.signature_id)
            if metadata_current.get("signature_id"):
                seen.add(str(metadata_current["signature_id"]))

        for signature_id, signature in existing.items():
            if signature_id not in seen and (
                signature.get("user_label") or signature.get("ignored")
                or signature.get("expected") or signature.get("merged_into")
                or signature.get("review_state")
            ):
                payloads.append(signature)

        return payloads


def nilm_state_updates(
    circuit_id: str,
    context: ProcessingContext,
    *,
    total_events_by_circuit: defaultdict[str, int],
    unmatched_edges_by_circuit: defaultdict[str, list[NilmEdge]],
) -> list[StateUpdate]:
    """Build state updates for current NILM signatures and unknown loads."""
    signatures = context.store_data.nilm_signatures.get(circuit_id, [])
    active_count = sum(
        1
        for signature in signatures
        if not signature.get("ignored")
        and signature.get("review_state") != "merged"
    )
    return [
        StateUpdate(("nilm_signature_count_by_circuit", circuit_id), active_count),
        StateUpdate(
            ("nilm_unmatched_load_percentage_by_circuit", circuit_id),
            unmatched_load_percentage(
                total_events_by_circuit[circuit_id],
                len(unmatched_edges_by_circuit[circuit_id]),
            ),
        ),
        StateUpdate(
            ("nilm_review_by_circuit", circuit_id),
            [nilm_review_payload(signature) for signature in signatures],
        ),
        StateUpdate(
            ("nilm_unknown_loads_by_circuit", circuit_id),
            dict(context.store_data.nilm_unknown_loads_by_circuit.get(circuit_id, {})),
        ),
    ]


def nilm_review_payload(signature: dict[str, Any]) -> dict[str, Any]:
    """Build the user-facing NILM review payload for one signature."""
    payload = dict(signature)
    if payload.get("review_state"):
        return payload
    if payload.get("ignored"):
        payload["review_state"] = "ignored"
    elif payload.get("user_label"):
        payload["review_state"] = "labeled"
    else:
        payload["review_state"] = "new"
    return payload


def _newest_nilm_edges(edges: Iterable[NilmEdge], max_items: int) -> list[NilmEdge]:
    if max_items <= 0:
        return []
    return sorted(edges, key=lambda edge: edge.timestamp)[-max_items:]


def _nilm_session_history_payloads(
    circuit_id: str,
    edges: Iterable[NilmEdge],
    signatures: list[dict[str, Any]],
    assignments: Iterable[Any],
) -> list[dict[str, Any]]:
    edge_list = list(edges)
    if not edge_list:
        return []
    assignment_list = [
        assignment for assignment in assignments if isinstance(assignment, Mapping)
    ]
    signatures_by_key = _nilm_signatures_by_key(signatures)
    assignment_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignment_list
    }
    matcher_specs: list[dict[str, Any]] = []
    for signature_fingerprint, assignment_id in _nilm_session_specs(
        signatures,
        assignment_list,
    ):
        spec = dict(signatures_by_key.get(signature_fingerprint) or {})
        spec["signature_fingerprint"] = signature_fingerprint
        spec["assignment_id"] = assignment_id
        assignment = assignment_by_id.get(assignment_id or "", {})
        for key in ("min_duration_seconds", "max_duration_seconds"):
            if key in assignment:
                spec[key] = assignment[key]
        matcher_specs.append(spec)
    return [
        nilm_session_to_dict(session)
        for session in pair_nilm_sessions_for_signatures(
            edge_list,
            mains_circuit_id=circuit_id,
            signature_specs=matcher_specs,
        )
    ]


def _nilm_signatures_by_key(
    signatures: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    values: dict[str, Mapping[str, Any]] = {}
    for signature in signatures:
        for key in ("signature_id", "feedback_fingerprint", "signature_fingerprint"):
            value = str(signature.get(key) or "").strip()
            if value:
                values[value] = signature
    return values


def _nilm_session_specs(
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Any],
) -> list[tuple[str, str | None]]:
    specs: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    seen_fingerprints: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            continue
        fingerprints = [
            str(value or "").strip()
            for value in _list_items(assignment.get("signature_fingerprints"))
            if str(value or "").strip()
        ]
        hidden = str(assignment.get("lifecycle_state") or "").strip() in {
            "ignored",
            "expected",
            "retired",
        } or (
            assignment.get("conversion_state") == "direct_meter"
            and assignment.get("keep_assignment_for_masking") is False
        )
        if hidden:
            seen_fingerprints.update(fingerprints)
            continue
        assignment_id = str(assignment.get("assignment_id") or "").strip() or None
        for fingerprint in fingerprints:
            key = (fingerprint, assignment_id)
            if key not in seen:
                specs.append(key)
                seen.add(key)
                seen_fingerprints.add(fingerprint)
    for signature in signatures:
        fingerprint = _nilm_signature_session_fingerprint(signature)
        key = (fingerprint, None)
        if fingerprint and fingerprint not in seen_fingerprints and key not in seen:
            specs.append(key)
            seen.add(key)
    return specs


def _nilm_signature_session_fingerprint(signature: Mapping[str, Any]) -> str:
    return str(
        signature.get("feedback_fingerprint")
        or signature.get("signature_fingerprint")
        or signature.get("signature_id")
        or ""
    ).strip()


def _merge_nilm_session_history(
    existing: Iterable[Any],
    updates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for session in existing:
        if isinstance(session, Mapping):
            session_id = str(session.get("session_id") or "").strip()
            if session_id:
                merged[session_id] = dict(session)
    for update in updates:
        session_id = str(update.get("session_id") or "").strip()
        if not session_id:
            continue
        if update.get("off_edge_id"):
            _remove_replaced_nilm_sessions(
                merged,
                signature_fingerprint=str(
                    update.get("signature_fingerprint") or ""
                ).strip(),
                off_edge_id=str(update.get("off_edge_id") or "").strip(),
                on_edge_id=str(update.get("on_edge_id") or "").strip(),
                assignment_id=str(update.get("assignment_id") or "").strip(),
                any_signature=bool(update.get("ambiguous")),
            )
        merged[session_id] = dict(update)
    return sorted(
        merged.values(),
        key=lambda session: str(session.get("end") or session.get("start") or ""),
        reverse=True,
    )


def _remove_replaced_nilm_sessions(
    sessions: dict[str, dict[str, Any]],
    *,
    signature_fingerprint: str,
    on_edge_id: str,
    off_edge_id: str,
    assignment_id: str = "",
    any_signature: bool = False,
) -> None:
    if not on_edge_id:
        return
    for session_id, session in list(sessions.items()):
        existing_off_edge_id = str(session.get("off_edge_id") or "").strip()
        if (
            str(session.get("on_edge_id") or "").strip() == on_edge_id
            and (
                (off_edge_id and existing_off_edge_id == off_edge_id)
                or (
                    not existing_off_edge_id
                    and (
                        any_signature
                        or str(session.get("signature_fingerprint") or "").strip()
                        == signature_fingerprint
                        or (
                            assignment_id
                            and str(session.get("assignment_id") or "").strip()
                            == assignment_id
                        )
                    )
                )
            )
        ):
            sessions.pop(session_id, None)


def _optional_float(*values: Any) -> float | None:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _list_items(values: Any) -> Iterable[Any]:
    return values if isinstance(values, list) else ()


def _nilm_signature_metadata_compatible(
    signature: NilmSignature,
    current: dict[str, Any],
) -> bool:
    if not current:
        return False

    current_type = str(current.get("split_phase_type") or "")
    signature_type = str(signature.split_phase_type or "unknown")
    if current_type:
        if not _nilm_split_phase_metadata_compatible(current_type, signature_type):
            return False
    elif signature_type not in {"unknown", "missing_leg_data"}:
        return False

    checks = (
        ("median_delta_w", 0.2),
        ("median_delta_var", 0.35),
        ("median_delta_va", 0.35),
    )
    for key, tolerance_ratio in checks:
        current_value = _float_or_none(current.get(key))
        signature_value = _float_or_none(getattr(signature, key, None))
        if current_value is None or signature_value is None:
            continue
        tolerance = max(abs(signature_value) * tolerance_ratio, 25.0)
        if abs(current_value - signature_value) > tolerance:
            return False

    return True


def _nilm_split_phase_metadata_compatible(
    current_type: str,
    signature_type: str,
) -> bool:
    uncertain = {"unknown", "missing_leg_data"}
    if current_type in uncertain or signature_type in uncertain:
        return current_type in uncertain and signature_type in uncertain
    return current_type == signature_type


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
