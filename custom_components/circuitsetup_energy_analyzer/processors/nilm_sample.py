"""NILM sample processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, MutableMapping, MutableSet
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import combinations
from math import isfinite
from typing import Any

from ..models import AlertEvidence, CircuitConfig, CircuitEvent
from ..nilm import (
    NilmAssignmentModel,
    NilmComponentStatus,
    NilmEdge,
    NilmEdgeDetector,
    NilmSignature,
    NilmTransitionPrototype,
    _nilm_signature_edge_score,
    classify_signature,
    cluster_recurring_signatures,
    conservation_tolerance_w,
    discover_nilm_helper_candidates,
    mask_known_loads,
    nilm_helper_candidate_to_dict,
    nilm_session_to_dict,
    nilm_signature_fingerprint,
    pair_nilm_sessions_for_signatures,
    reconcile_nilm_edge,
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
type HelperCandidateEventsProvider = KnownLoadEventsProvider
type TopologyObserver = Callable[
    [CircuitConfig, Any, ProcessingContext],
    list[AlertEvidence],
]


class NilmSampleProcessor:
    """Process NILM source samples into signatures, unknown loads, and alerts."""

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
        helper_candidate_events: HelperCandidateEventsProvider | None = None,
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
        self._pending_known_load_events: dict[str, tuple[CircuitEvent, ...]] = {}
        self._helper_candidate_events = helper_candidate_events or (
            lambda _id, _events: ()
        )
        self._helper_events_by_source: dict[str, list[CircuitEvent]] = defaultdict(list)
        self._helper_links_dirty = False
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
        helper_events = self._helper_events_by_source[circuit_id]
        previous_helper_event_keys = tuple(map(_helper_event_key, helper_events))
        helper_events.extend(self._helper_candidate_events(circuit_id, events))
        helper_events = list(
            {_helper_event_key(event): event for event in helper_events}.values()
        )
        cutoff = sample.timestamp - timedelta(minutes=10)
        retained = [event for event in helper_events if event.timestamp >= cutoff]
        self._helper_events_by_source[circuit_id] = (
            retained[-self._unmatched_edges_max_items :]
            if self._unmatched_edges_max_items
            else []
        )
        helper_events_changed = previous_helper_event_keys != tuple(
            map(_helper_event_key, self._helper_events_by_source[circuit_id])
        )
        current_known_events = tuple(self._known_load_events(circuit_id, events))
        pending_known_events = self._pending_known_load_events.pop(circuit_id, ())
        known_events = (*pending_known_events, *current_known_events)
        alerts: list[AlertEvidence] = []
        store_dirty = False
        existing_unmatched = list(self.unmatched_edges_by_circuit[circuit_id])
        candidate_edges = [*existing_unmatched, *edges]
        matched_edges = ()
        defer_known_events = detector.has_pending_transition and not edges
        if candidate_edges and known_events and not defer_known_events:
            mask = mask_known_loads(candidate_edges, known_events)
            matched_edges = mask.matched_edges
            next_unmatched = list(mask.unmatched_edges)
        else:
            next_unmatched = candidate_edges
        if defer_known_events and known_events:
            self._pending_known_load_events[circuit_id] = known_events

        assignments = tuple(
            item
            for item in context.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id, ()
            )
            if isinstance(item, Mapping)
        )
        runtime = _initial_component_runtime(
            assignments,
            context.state.nilm_component_runtime_by_circuit.get(circuit_id, {}),
            sample.timestamp,
        )
        reconciliation = None
        completed_sessions: list[dict[str, Any]] = []
        if runtime:
            standby_w = _finite_float(
                context.state.always_on_power_w_by_circuit.get(circuit_id)
            ) or 0.0
            _apply_direct_helpers(assignments, runtime, context.state)
            _restore_unique_component_state(
                sample.real_power, standby_w, detector.noise_spread_w,
                assignments, runtime
            )
            masked_ids = {id(match.edge) for match in matched_edges}
            new_unmasked = [edge for edge in edges if id(edge) not in masked_ids]
            runtime, reconciliation, completed_sessions, accepted = (
                reconcile_component_runtime(
                    source_power_w=sample.real_power,
                    timestamp=sample.timestamp,
                    assignments=assignments,
                    runtime=runtime,
                    edges=new_unmasked,
                    standby_w=standby_w,
                    noise_spread_w=detector.noise_spread_w,
                    previous_reconciliation=(
                        context.state.nilm_reconciliation_by_circuit.get(circuit_id)
                    ),
                    helper_events=self._helper_events_by_source[circuit_id],
                )
            )
            accepted_ids = {id(edge) for edge in accepted}
            next_unmatched = [
                edge for edge in next_unmatched if id(edge) not in accepted_ids
            ]
            if completed_sessions:
                history = (
                    context.store_data.nilm_session_history_by_circuit.setdefault(
                        circuit_id, []
                    )
                )
                history.extend(completed_sessions)
                del history[:-512]
                store_dirty = True

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

        if edges or next_unmatched != existing_unmatched or helper_events_changed:
            signatures = cluster_recurring_signatures(
                self.unmatched_edges_by_circuit[circuit_id],
            )
            payloads = self._nilm_signature_payloads(
                circuit_id,
                signatures,
                context,
            )
            if self._helper_links_dirty:
                store_dirty = True
                self._helper_links_dirty = False
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
            if self.refresh_session_history(circuit_id, context.store_data):
                store_dirty = True

        return FeatureResult(
            alerts=alerts,
            notifications=list(alerts),
            state_updates=[
                *nilm_state_updates(
                    circuit_id,
                    context,
                    total_events_by_circuit=self.total_events_by_circuit,
                    unmatched_edges_by_circuit=self.unmatched_edges_by_circuit,
                ),
                *(
                    [
                        StateUpdate(
                            ("nilm_component_runtime_by_circuit", circuit_id),
                            runtime,
                        ),
                        StateUpdate(
                            ("nilm_reconciliation_by_circuit", circuit_id),
                            reconciliation,
                        ),
                    ]
                    if reconciliation is not None
                    else []
                ),
            ],
            store_dirty=store_dirty,
        )

    def refresh_session_history(self, circuit_id: str, store_data: Any) -> bool:
        """Recompute persisted sessions from current edges and assignments."""
        assignments = store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            [],
        )
        existing_sessions = store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            [],
        )
        next_sessions = _reconcile_nilm_session_duration_bounds(
            circuit_id,
            existing_sessions,
            assignments,
        )
        session_payloads = _nilm_session_history_payloads(
            circuit_id,
            self.unmatched_edges_by_circuit[circuit_id],
            store_data.nilm_signatures.get(circuit_id, []),
            assignments,
        )
        if session_payloads:
            next_sessions = _merge_nilm_session_history(
                next_sessions,
                session_payloads,
                assignments=assignments,
            )
        if next_sessions == existing_sessions:
            return False
        store_data.nilm_session_history_by_circuit[circuit_id] = next_sessions
        return True

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
            signature_edges = [
                edge
                for edge in self.unmatched_edges_by_circuit[circuit_id]
                if edge.timestamp >= context.now - timedelta(minutes=10)
                and _nilm_signature_edge_score(edge, payload) is not None
            ]
            assignment = next(
                (
                    item
                    for item in (
                        context.store_data.nilm_appliance_assignments_by_circuit.get(
                            circuit_id, []
                        )
                    )
                    if isinstance(item, dict)
                    and feedback_fingerprint
                    in {
                        str(value or "").strip()
                        for value in _list_items(
                            item.get("signature_fingerprints")
                        )
                    }
                ),
                None,
            )
            if assignment is not None and _record_assignment_model_drift(
                assignment, feedback_fingerprint, signature_edges
            ):
                self._helper_links_dirty = True
            observations = self._helper_events_by_source.get(circuit_id, [])
            if observations:
                by_circuit: defaultdict[str, list[CircuitEvent]] = defaultdict(list)
                for event in observations:
                    by_circuit[event.circuit_id].append(event)
                payload["helper_candidates"] = [
                    nilm_helper_candidate_to_dict(candidate)
                    for candidate in discover_nilm_helper_candidates(
                        signature_edges, by_circuit
                    )
                ]
                self._helper_links_dirty |= _refresh_confirmed_helper_links(
                    context.store_data.nilm_appliance_assignments_by_circuit.get(
                        circuit_id, []
                    ),
                    feedback_fingerprint,
                    payload["helper_candidates"],
                )
            elif "helper_candidates" in metadata_current:
                payload["helper_candidates"] = metadata_current["helper_candidates"]
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


def reconcile_component_runtime(
    *,
    source_power_w: float | None,
    timestamp: datetime,
    assignments: Iterable[Mapping[str, Any]],
    runtime: Mapping[str, Mapping[str, Any]],
    edges: Iterable[NilmEdge],
    standby_w: float,
    noise_spread_w: float,
    previous_reconciliation: Mapping[str, Any] | None = None,
    helper_events: Iterable[CircuitEvent] = (),
) -> tuple[
    dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[NilmEdge]
]:
    """Apply bounded assignment transitions and enforce source conservation."""
    assignments = tuple(assignments)
    models = tuple(_runtime_assignment_model(item) for item in assignments)
    next_runtime = {key: dict(value) for key, value in runtime.items()}
    _integrate_runtime_energy(next_runtime, timestamp, previous_reconciliation)
    accepted: list[NilmEdge] = []
    completed: list[dict[str, Any]] = []
    conflict: str | None = None

    if source_power_w is None or not isfinite(source_power_w):
        _suspend_runtime(next_runtime)
        return next_runtime, _runtime_reconciliation(
            None, standby_w, next_runtime, noise_spread_w,
            "source_unavailable", timestamp
        ), completed, accepted

    for edge in edges:
        before = {key: dict(value) for key, value in next_runtime.items()}
        current = {
            key: _finite_float(value.get("state_power_w"))
            if value.get("status") in {
                NilmComponentStatus.ON, NilmComponentStatus.OFF
            }
            else None
            for key, value in next_runtime.items()
        }
        result = reconcile_nilm_edge(
            edge,
            models,
            current,
            _confirmed_helper_scores(assignments, helper_events, edge),
            {},
            {},
        )
        if not result.accepted:
            if result.reason == "helper_conflict":
                conflict = result.reason
            continue
        pending_sessions: list[dict[str, Any]] = []
        for transition in result.transitions:
            payload = next_runtime[transition.assignment_id]
            if transition.direction == "on":
                payload.update({
                    "status": NilmComponentStatus.ON,
                    "state_power_w": transition.to_state_w,
                    "estimated_power_w": transition.to_state_w,
                    "session_id": (
                        f"{transition.assignment_id}|{edge.timestamp.isoformat()}"
                    ),
                    "session_start": edge.timestamp.isoformat(),
                    "confidence": _model_confidence(models, transition.assignment_id),
                    "consistent": True,
                    "last_observed": edge.timestamp.isoformat(),
                    "energy_kwh": 0.0,
                    "on_delta_w": transition.delta_w,
                })
            else:
                if payload.get("session_id") and payload.get("session_start"):
                    pending_sessions.append(_completed_runtime_session(
                        transition.assignment_id,
                        payload,
                        transition,
                        edge,
                        assignments,
                    ))
                payload.update({
                    "status": NilmComponentStatus.OFF,
                    "state_power_w": transition.to_state_w,
                    "estimated_power_w": 0.0,
                    "session_id": None,
                    "session_start": None,
                    "energy_kwh": 0.0,
                })
        tolerance = conservation_tolerance_w(source_power_w, noise_spread_w)
        if (
            _runtime_allocated_power(next_runtime)
            > source_power_w - standby_w + tolerance
        ):
            next_runtime = before
            _suspend_runtime(next_runtime)
            conflict = "over_allocation"
            continue
        accepted.append(edge)
        completed.extend(pending_sessions)

    tolerance = conservation_tolerance_w(source_power_w, noise_spread_w)
    if _runtime_allocated_power(next_runtime) > source_power_w - standby_w + tolerance:
        _suspend_runtime(next_runtime)
        conflict = "over_allocation"
    consistent = conflict is None
    for payload in next_runtime.values():
        payload["consistent"] = consistent
        payload["last_observed"] = timestamp.isoformat()
    return next_runtime, _runtime_reconciliation(
        source_power_w, standby_w, next_runtime, noise_spread_w,
        conflict, timestamp
    ), completed, accepted


def _initial_component_runtime(
    assignments: Iterable[Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    timestamp: datetime,
) -> dict[str, dict[str, Any]]:
    runtime = {key: dict(value) for key, value in current.items()}
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        if not assignment_id:
            continue
        runtime.setdefault(assignment_id, {
            "status": NilmComponentStatus.UNKNOWN,
            "state_power_w": None,
            "estimated_power_w": None,
            "session_id": None,
            "session_start": None,
            "confidence": 0.0,
            "consistent": False,
            "last_observed": timestamp.isoformat(),
            "energy_kwh": 0.0,
        })
    return runtime


def _restore_unique_component_state(
    source_power_w: Any,
    standby_w: float,
    noise_spread_w: float,
    assignments: Iterable[Mapping[str, Any]],
    runtime: dict[str, dict[str, Any]],
) -> None:
    source = _finite_float(source_power_w)
    if source is None:
        return
    models = tuple(_runtime_assignment_model(item) for item in assignments)
    unknown = [
        model for model in models
        if runtime[model.assignment_id]["status"] == NilmComponentStatus.UNKNOWN
    ]
    if not unknown:
        return
    known = _runtime_allocated_power(runtime)
    tolerance = conservation_tolerance_w(source, noise_spread_w)
    fits: list[tuple[str, ...]] = []
    for count in range(min(2, len(unknown)) + 1):
        for group in combinations(unknown, count):
            allocated = known + sum(
                max(model.power_states_w, default=0.0) for model in group
            )
            if abs(source - standby_w - allocated) <= tolerance:
                fits.append(tuple(model.assignment_id for model in group))
    if len(fits) != 1:
        return
    active = set(fits[0])
    for model in unknown:
        power = (
            max(model.power_states_w, default=0.0)
            if model.assignment_id in active else 0.0
        )
        runtime[model.assignment_id].update({
            "status": NilmComponentStatus.ON if power else NilmComponentStatus.OFF,
            "state_power_w": power,
            "estimated_power_w": power,
            "confidence": model.model_confidence,
            "consistent": True,
        })


def _apply_direct_helpers(
    assignments: Iterable[Mapping[str, Any]],
    runtime: dict[str, dict[str, Any]],
    state: Any,
) -> None:
    for assignment in assignments:
        direct = next((
            link for link in _list_items(assignment.get("helper_links"))
            if isinstance(link, Mapping)
            and link.get("status") == "confirmed"
            and link.get("relationship") == "direct_component"
        ), None)
        if direct is None:
            continue
        power = _finite_float(state.latest_real_power_w_by_circuit.get(
            str(direct.get("helper_circuit_id") or "")
        ))
        if power is None:
            continue
        runtime[str(assignment.get("assignment_id"))].update({
            "status": (
                NilmComponentStatus.ON
                if power > 0.0
                else NilmComponentStatus.OFF
            ),
            "state_power_w": power,
            "estimated_power_w": power,
            "confidence": _finite_float(direct.get("confidence")) or 0.0,
        })


def _runtime_assignment_model(assignment: Mapping[str, Any]) -> NilmAssignmentModel:
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    prototypes = tuple(
        NilmTransitionPrototype(
            assignment_id=assignment_id,
            direction=str(item.get("direction") or ""),
            from_state_w=float(item.get("from_state_w") or 0.0),
            to_state_w=float(item.get("to_state_w") or 0.0),
            delta_w=float(item.get("delta_w") or 0.0),
            spread_w=float(item.get("spread_w") or 0.0),
            sample_count=int(item.get("sample_count") or 0),
        )
        for item in _list_items(assignment.get("transition_prototypes"))
        if isinstance(item, Mapping)
    )
    return NilmAssignmentModel(
        assignment_id=assignment_id,
        power_states_w=tuple(
            float(value)
            for value in _list_items(assignment.get("power_states_w"))
            if _finite_float(value) is not None
        ),
        transition_prototypes=prototypes,
        model_confidence=_finite_float(assignment.get("model_confidence")) or 0.0,
        lifecycle_state=str(assignment.get("lifecycle_state") or ""),
        last_observed=_runtime_datetime(assignment.get("updated_at")),
    )


def _confirmed_helper_scores(
    assignments: Iterable[Mapping[str, Any]],
    events: Iterable[CircuitEvent],
    edge: NilmEdge,
) -> dict[str, float | None]:
    events = tuple(events)
    scores: dict[str, float | None] = {}
    expected = "start" if edge.direction == "on" else "stop"
    for assignment in assignments:
        matched = [
            _finite_float(link.get("confidence")) or 0.0
            for link in _list_items(assignment.get("helper_links"))
            if isinstance(link, Mapping)
            and link.get("status") == "confirmed"
            and any(
                event.circuit_id == str(link.get("helper_circuit_id") or "")
                and event.event_type.value == expected
                and abs(event.timestamp - edge.timestamp) <= timedelta(minutes=10)
                for event in events
            )
        ]
        if matched:
            scores[str(assignment.get("assignment_id") or "")] = (
                sum(matched) / len(matched)
            )
    return scores


def _integrate_runtime_energy(
    runtime: dict[str, dict[str, Any]],
    timestamp: datetime,
    reconciliation: Mapping[str, Any] | None,
) -> None:
    if not reconciliation or not reconciliation.get("energy_allocation_allowed"):
        return
    for payload in runtime.values():
        observed = _runtime_datetime(payload.get("last_observed"))
        power = _finite_float(payload.get("estimated_power_w"))
        if (
            observed is None
            or power is None
            or payload.get("status") != NilmComponentStatus.ON
        ):
            continue
        seconds = max((timestamp - observed).total_seconds(), 0.0)
        payload["energy_kwh"] = (
            (_finite_float(payload.get("energy_kwh")) or 0.0)
            + power * seconds / 3_600_000.0
        )


def _completed_runtime_session(
    assignment_id: str,
    runtime: Mapping[str, Any],
    transition: NilmTransitionPrototype,
    edge: NilmEdge,
    assignments: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    assignment = next(
        item for item in assignments if item.get("assignment_id") == assignment_id
    )
    return {
        "session_id": runtime.get("session_id"),
        "assignment_id": assignment_id,
        "start": runtime.get("session_start"),
        "end": edge.timestamp.isoformat(),
        "on_delta_w": runtime.get("on_delta_w"),
        "off_delta_w": transition.delta_w,
        "energy_kwh": _finite_float(runtime.get("energy_kwh")) or 0.0,
        "confidence": min(
            _finite_float(runtime.get("confidence")) or 0.0,
            _finite_float(assignment.get("model_confidence")) or 0.0,
        ),
        "helper_evidence": [
            dict(link)
            for link in _list_items(assignment.get("helper_links"))
            if isinstance(link, Mapping) and link.get("status") == "confirmed"
        ],
        "consistent": True,
    }


def _runtime_reconciliation(
    source_power_w: float | None,
    standby_w: float,
    runtime: Mapping[str, Mapping[str, Any]],
    noise_spread_w: float,
    conflict: str | None,
    timestamp: datetime,
) -> dict[str, Any]:
    allocated = _runtime_allocated_power(runtime)
    residual = (
        source_power_w - standby_w - allocated
        if source_power_w is not None
        else 0.0
    )
    consistent = source_power_w is not None and conflict is None
    payload = {
        "source_power_w": source_power_w,
        "standby_w": standby_w,
        "allocated_power_w": allocated,
        "residual_w": residual,
        "tolerance_w": conservation_tolerance_w(
            source_power_w or 0.0, noise_spread_w
        ),
        "consistent": consistent,
        "energy_allocation_allowed": consistent,
        "conflict": conflict,
        "last_observed": timestamp.isoformat(),
    }
    if conflict:
        payload["review_item"] = {
            "type": "model_conflict",
            "reason": conflict,
            "timestamp": timestamp.isoformat(),
        }
    return payload


def _runtime_allocated_power(runtime: Mapping[str, Mapping[str, Any]]) -> float:
    return sum(
        _finite_float(payload.get("estimated_power_w")) or 0.0
        for payload in runtime.values()
        if payload.get("status") == NilmComponentStatus.ON
    )


def _suspend_runtime(runtime: Mapping[str, dict[str, Any]]) -> None:
    for payload in runtime.values():
        if payload.get("status") == NilmComponentStatus.ON:
            payload["status"] = NilmComponentStatus.UNCERTAIN
        payload["consistent"] = False


def _model_confidence(
    models: Iterable[NilmAssignmentModel], assignment_id: str
) -> float:
    return next(
        model.model_confidence for model in models
        if model.assignment_id == assignment_id
    )


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _runtime_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _record_assignment_model_drift(
    assignment: dict[str, Any], fingerprint: str, edges: Iterable[NilmEdge]
) -> bool:
    """Retain repeated reviewed-signature drift without changing its model."""
    prototypes = {
        str(item.get("direction") or ""): item
        for item in _list_items(assignment.get("transition_prototypes"))
        if isinstance(item, Mapping)
    }
    stored = assignment.get("model_drift_edges_by_fingerprint")
    by_fingerprint = {
        str(key): list(_list_items(value))[-3:]
        for key, value in stored.items()
    } if isinstance(stored, Mapping) else {}
    fingerprint = str(fingerprint or "").strip()
    seen = by_fingerprint.get(
        fingerprint, list(_list_items(assignment.get("model_drift_edge_ids")))[-3:]
    )
    changed = False
    for edge in edges:
        prototype = prototypes.get(edge.direction)
        if prototype is None:
            continue
        delta = _optional_float(prototype.get("delta_w"))
        spread = _optional_float(prototype.get("spread_w")) or 0.0
        if delta is None:
            continue
        tolerance = max(15.0, 3 * spread, abs(delta) * 0.2)
        edge_id = f"{edge.timestamp.isoformat()}|{round(edge.delta_w, 3)}"
        if abs(edge.delta_w - delta) <= tolerance or edge_id in seen:
            continue
        seen.append(edge_id)
        changed = True
    if not changed:
        return False
    by_fingerprint[fingerprint] = seen[-3:]
    retained_fingerprints = {
        str(value or "").strip()
        for value in _list_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    }
    assignment["model_drift_edges_by_fingerprint"] = {
        key: value
        for key, value in by_fingerprint.items()
        if not retained_fingerprints or key in retained_fingerprints
    }
    assignment.pop("model_drift_edge_ids", None)
    if len(by_fingerprint[fingerprint]) >= 3:
        assignment["model_status"] = "needs_review"
    return True


def _helper_event_key(event: CircuitEvent) -> tuple[Any, ...]:
    """Return stable identity for retry-safe helper observation retention."""
    return (
        event.timestamp,
        event.circuit_id,
        event.event_type,
        repr(event.severity),
        repr(sorted(event.features.items())),
    )


def _refresh_confirmed_helper_links(
    assignments: Iterable[Any],
    feedback_fingerprint: str,
    candidates: Iterable[Mapping[str, Any]],
) -> bool:
    """Refresh statistics on confirmed links without changing relationships."""
    candidates_by_id = {
        str(candidate.get("helper_circuit_id") or ""): candidate
        for candidate in candidates
    }
    changed = False
    for assignment in assignments:
        if not isinstance(assignment, Mapping) or feedback_fingerprint not in {
            str(value or "")
            for value in _list_items(assignment.get("signature_fingerprints"))
        }:
            continue
        for link in _list_items(assignment.get("helper_links")):
            if not isinstance(link, dict) or link.get("status") not in {
                "confirmed",
                "degraded",
            }:
                continue
            candidate = candidates_by_id.get(str(link.get("helper_circuit_id") or ""))
            if candidate is None:
                continue
            previous = dict(link)
            link.setdefault(
                "confirmed_matched_on_count",
                _nonnegative_int(link.get("matched_on_count")),
            )
            link.setdefault(
                "confirmed_matched_off_count",
                _nonnegative_int(link.get("matched_off_count")),
            )
            relationship = link.get("relationship")
            status = link.get("status")
            link.update(candidate)
            link["relationship"] = relationship
            link["status"] = status
            for key in (
                "matched_on_count",
                "matched_off_count",
                "unmatched_source_count",
                "unmatched_helper_count",
                "source_event_count",
                "helper_event_count",
                "confirmed_matched_on_count",
                "confirmed_matched_off_count",
            ):
                link[key] = _nonnegative_int(link.get(key))
            link["confidence"] = confidence = _clamped_confidence(
                link.get("confidence")
            )
            new_on = link["matched_on_count"] - link["confirmed_matched_on_count"]
            new_off = link["matched_off_count"] - link["confirmed_matched_off_count"]
            if new_on >= 3 and new_off >= 3 and confidence < 0.75:
                link["status"] = "degraded"
            changed |= link != previous
    return changed


def _nonnegative_int(value: Any) -> int:
    parsed = _optional_float(value)
    return int(parsed) if parsed is not None and isfinite(parsed) and parsed > 0 else 0


def _clamped_confidence(value: Any) -> float:
    parsed = _optional_float(value)
    if parsed is None or not isfinite(parsed):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


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
    *,
    assignments: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    assignments_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignments
        if isinstance(assignment, Mapping)
    }
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
        payload = dict(update)
        on_edge_id = str(update.get("on_edge_id") or "").strip()
        existing_session = merged.get(session_id)
        if existing_session is None and on_edge_id:
            existing_session = next(
                (
                    session
                    for session in merged.values()
                    if str(session.get("on_edge_id") or "").strip() == on_edge_id
                ),
                None,
            )
        if existing_session is not None and payload.get("end") is None:
            preserved_close = existing_session.get("_duration_bound_close")
            if isinstance(preserved_close, Mapping):
                payload["_duration_bound_close"] = dict(preserved_close)
                assignment_id = str(
                    payload.get("assignment_id")
                    or existing_session.get("assignment_id")
                    or ""
                ).strip()
                _replace_nilm_assignment_rejection(
                    assignments_by_id.get(assignment_id),
                    old_session_id=str(
                        existing_session.get("session_id") or ""
                    ).strip(),
                    new_session_id=session_id,
                )
        _remove_replaced_nilm_sessions(
            merged,
            on_edge_id=on_edge_id,
        )
        merged[session_id] = payload
    return sorted(
        merged.values(),
        key=lambda session: str(session.get("end") or session.get("start") or ""),
        reverse=True,
    )


def _reconcile_nilm_session_duration_bounds(
    circuit_id: str,
    sessions: Iterable[Any],
    assignments: Iterable[Any],
) -> list[dict[str, Any]]:
    assignments_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignments
        if isinstance(assignment, Mapping)
    }
    reconciled: list[dict[str, Any]] = []
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        payload = dict(session)
        assignment = assignments_by_id.get(
            str(payload.get("assignment_id") or "").strip()
        )
        stored_close = payload.get("_duration_bound_close")
        close_payload = stored_close if isinstance(stored_close, Mapping) else None
        duration = _optional_float(
            close_payload.get("duration_seconds")
            if close_payload is not None
            else payload.get("duration_seconds")
        )
        minimum = _optional_float(
            assignment.get("min_duration_seconds") if assignment else None
        )
        maximum = _optional_float(
            assignment.get("max_duration_seconds") if assignment else None
        )
        outside_bounds = duration is not None and (
            (minimum is not None and duration < minimum)
            or (maximum is not None and duration > maximum)
        )
        fingerprint = str(payload.get("signature_fingerprint") or "").strip()
        on_edge_id = str(payload.get("on_edge_id") or "").strip()
        confidence = _optional_float(payload.get("confidence"))
        if (
            payload.get("end") is not None
            and outside_bounds
            and fingerprint
            and on_edge_id
        ):
            closed_session_id = str(payload.get("session_id") or "").strip()
            open_session_id = "|".join(
                (circuit_id, fingerprint, on_edge_id, "open")
            )
            payload["_duration_bound_close"] = {
                key: payload.get(key)
                for key in (
                    "session_id",
                    "off_edge_id",
                    "end",
                    "duration_seconds",
                    "estimated_energy_kwh",
                    "confidence",
                    "ambiguous",
                    "alternate_match_count",
                )
            }
            _replace_nilm_assignment_rejection(
                assignment,
                old_session_id=closed_session_id,
                new_session_id=open_session_id,
            )
            payload.update(
                {
                    "session_id": open_session_id,
                    "off_edge_id": None,
                    "end": None,
                    "duration_seconds": None,
                    "estimated_energy_kwh": 0.0,
                    "confidence": min(
                        max(confidence if confidence is not None else 0.35, 0.0),
                        0.35,
                    ),
                    "ambiguous": False,
                    "alternate_match_count": 0,
                }
            )
        elif payload.get("end") is None and close_payload and not outside_bounds:
            _replace_nilm_assignment_rejection(
                assignment,
                old_session_id=str(payload.get("session_id") or "").strip(),
                new_session_id=str(
                    close_payload.get("session_id") or ""
                ).strip(),
            )
            payload.update(close_payload)
            payload.pop("_duration_bound_close", None)
        reconciled.append(payload)
    return sorted(
        reconciled,
        key=lambda session: str(session.get("end") or session.get("start") or ""),
        reverse=True,
    )


def _remove_replaced_nilm_sessions(
    sessions: dict[str, dict[str, Any]],
    *,
    on_edge_id: str,
) -> None:
    if not on_edge_id:
        return
    for session_id, session in list(sessions.items()):
        if str(session.get("on_edge_id") or "").strip() == on_edge_id:
            sessions.pop(session_id, None)


def _replace_nilm_assignment_rejection(
    assignment: Mapping[str, Any] | None,
    *,
    old_session_id: str,
    new_session_id: str,
) -> None:
    if (
        not isinstance(assignment, MutableMapping)
        or not old_session_id
        or not new_session_id
    ):
        return
    rejected = [
        str(value or "").strip()
        for value in _list_items(assignment.get("rejected_session_ids"))
        if str(value or "").strip()
    ]
    if old_session_id not in rejected:
        return
    assignment["rejected_session_ids"] = list(
        dict.fromkeys(
            new_session_id if session_id == old_session_id else session_id
            for session_id in rejected
        )
    )


def _optional_float(*values: Any) -> float | None:
    for value in values:
        try:
            return float(value)
        except (OverflowError, TypeError, ValueError):
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
