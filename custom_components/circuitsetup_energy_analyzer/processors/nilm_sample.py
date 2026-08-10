"""NILM sample processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, MutableMapping, MutableSet
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from ..models import AlertEvidence, CircuitConfig, CircuitEvent
from ..nilm import (
    KnownLoadTopology,
    NilmAssignmentModel,
    NilmComponentStatus,
    NilmEdge,
    NilmEdgeDetector,
    NilmReconciliationResult,
    NilmScoreBreakdown,
    NilmSignature,
    NilmTransitionPrototype,
    _nilm_signature_edge_score,
    attribute_known_loads,
    build_nilm_validation_profile,
    classify_signature,
    cluster_recurring_signatures,
    conservation_tolerance_w,
    discover_nilm_helper_candidates,
    duration_state_score_for_transition,
    nilm_helper_candidate_to_dict,
    nilm_session_to_dict,
    nilm_signature_fingerprint,
    nilm_signature_fingerprint_v1,
    nilm_signature_is_assignable,
    nilm_signature_is_off_direction,
    nilm_transition_tolerance_w,
    normalize_nilm_assignment_model,
    pair_nilm_sessions_for_signatures,
    reconcile_nilm_edge,
    resolve_nilm_signature_fingerprint,
    unmatched_load_percentage,
)
from ..normalize import NormalizedCircuitSample
from ..unknown_loads import (
    build_unknown_load_inventory,
    migrate_unknown_load_inventory,
    unknown_load_inventory_needs_rebuild,
)
from .base import FeatureResult, ProcessingContext, StateUpdate

type NilmEnabledPredicate = Callable[[CircuitConfig], bool]
type DemoNilmSeeder = Callable[[CircuitConfig, Any], None]
type MinDeltaProvider = Callable[[str], float]
type KnownLoadEventsProvider = Callable[
    [str, Iterable[CircuitEvent]],
    Iterable[CircuitEvent],
]
type HelperCandidateEventsProvider = KnownLoadEventsProvider
type KnownLoadTopologyProvider = Callable[[str], KnownLoadTopology | None]
type TopologyObserver = Callable[
    [CircuitConfig, Any, ProcessingContext],
    list[AlertEvidence],
]


@dataclass(frozen=True, slots=True)
class _RuntimeAssignmentModel(NilmAssignmentModel):
    """Runtime model with stable prediction provenance."""

    model_schema_version: int = 0
    model_revision: int = 0
    model_fingerprint: str = ""


_NILM_RUNTIME_STATE_PATH_LIMIT = 12
_NILM_RUNTIME_PREDICTION_LIMIT = 12


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
        known_load_topology: KnownLoadTopologyProvider | None = None,
        helper_candidate_events: HelperCandidateEventsProvider | None = None,
        unmatched_edges_max_items: int = 512,
        session_history_max_items: int = 2000,
    ) -> None:
        self._nilm_enabled = nilm_enabled
        self._seed_demo_nilm_state = seed_demo_nilm_state
        self._min_delta_w_for_circuit = min_delta_w_for_circuit
        self.detectors = detectors
        self.total_events_by_circuit = total_events_by_circuit
        self.unmatched_edges_by_circuit = unmatched_edges_by_circuit
        self.ignored_signatures = ignored_signatures
        self._known_load_events = known_load_events
        self._known_load_topology = known_load_topology or (lambda _circuit_id: None)
        self._pending_known_load_events: dict[str, tuple[CircuitEvent, ...]] = {}
        self._helper_candidate_events = helper_candidate_events or (
            lambda _id, _events: ()
        )
        self._helper_events_by_source: dict[str, list[CircuitEvent]] = defaultdict(list)
        self._helper_links_dirty = False
        self._observe_topology = observe_topology
        self._unmatched_edges_max_items = max(int(unmatched_edges_max_items), 0)
        self._session_history_max_items = max(int(session_history_max_items), 0)
        self._helper_events_max_items = min(self._unmatched_edges_max_items, 512)
        self._hydrated_unmatched_edge_circuits: set[str] = set()

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
        cutoff = sample.timestamp - timedelta(days=7)
        retained = [event for event in helper_events if event.timestamp >= cutoff]
        self._helper_events_by_source[circuit_id] = (
            retained[-self._helper_events_max_items :]
            if self._helper_events_max_items
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
        assignments = tuple(
            item
            for item in context.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id, ()
            )
            if isinstance(item, Mapping)
        )
        signature_specs = tuple(
            item
            for item in context.store_data.nilm_signatures.get(circuit_id, ())
            if isinstance(item, Mapping)
        )
        hidden_assignment_ids = {
            str(item.get("assignment_id") or "").strip()
            for item in assignments
            if str(item.get("lifecycle_state") or "").strip() in {"ignored", "retired"}
            or (
                item.get("conversion_state") == "direct_meter"
                and item.get("keep_assignment_for_masking") is False
            )
        }
        stored_unmatched_edges = context.store_data.nilm_unmatched_edges_by_circuit
        persisted_edge_payloads = stored_unmatched_edges.get(circuit_id)
        has_persisted_edges = isinstance(persisted_edge_payloads, list)
        if circuit_id not in self._hydrated_unmatched_edge_circuits:
            if has_persisted_edges:
                self.unmatched_edges_by_circuit[circuit_id] = _nilm_edges_from_storage(
                    persisted_edge_payloads,
                    max_items=self._unmatched_edges_max_items,
                )
            self._hydrated_unmatched_edge_circuits.add(circuit_id)
        existing_unmatched = list(self.unmatched_edges_by_circuit[circuit_id])
        recovered_edges = (
            []
            if has_persisted_edges
            else _recover_unassigned_session_edges(
                context.store_data.nilm_session_history_by_circuit.get(circuit_id, ()),
                since=sample.timestamp - timedelta(days=7),
                excluded_assignment_ids=hidden_assignment_ids,
            )
        )
        candidate_edges = [*existing_unmatched, *recovered_edges, *edges]
        matched_edges = ()
        rejected_topology_candidates = ()
        defer_known_events = detector.has_pending_transition and not edges
        if candidate_edges and known_events and not defer_known_events:
            topology_by_circuit = {
                event.circuit_id: topology
                for event in known_events
                if (topology := self._known_load_topology(event.circuit_id)) is not None
            }
            mask = attribute_known_loads(
                candidate_edges,
                known_events,
                residual_min_delta_w=self._min_delta_w_for_circuit(circuit_id),
                topology_by_circuit=topology_by_circuit,
            )
            matched_edges = mask.matched_edges
            rejected_topology_candidates = mask.rejected_topology_candidates
            next_unmatched = list(mask.unmatched_edges)
        else:
            next_unmatched = candidate_edges
        if defer_known_events and known_events:
            self._pending_known_load_events[circuit_id] = known_events

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
            _restore_unique_component_state(
                sample.real_power, standby_w, detector.noise_spread_w,
                assignments, runtime, sample.timestamp, signature_specs
            )
            matches_by_edge_id: dict[int, list[Any]] = defaultdict(list)
            for match in matched_edges:
                matches_by_edge_id[id(match.edge)].append(match)
            new_unmasked: list[NilmEdge] = []
            for edge in edges:
                edge_matches = matches_by_edge_id.get(id(edge), [])
                match = edge_matches.pop(0) if edge_matches else None
                if match is None:
                    new_unmasked.append(edge)
                elif match.residual_edge is not None:
                    new_unmasked.append(match.residual_edge)
            previous_reconciliation = (
                context.state.nilm_reconciliation_by_circuit.get(circuit_id)
            )
            pending_confirmation = detector.has_pending_transition and not edges
            source_power_w = (
                _pending_reconciliation_source(
                    previous_reconciliation, sample.timestamp
                )
                if pending_confirmation
                else sample.real_power
            )
            available_helper_ids = set(
                context.state.latest_real_power_w_by_circuit
            )
            direct_helper_powers = {
                helper_id: (
                    runtime.get(str(item.get("assignment_id") or ""), {}).get(
                        "estimated_power_w"
                    )
                    if pending_confirmation
                    else context.state.latest_real_power_w_by_circuit.get(helper_id)
                )
                for item in assignments
                if (helper_id := _direct_helper_id(item)) is not None
            }
            if not pending_confirmation or source_power_w is not None:
                edge_timestamp = (
                    max(edge.timestamp for edge in new_unmasked)
                    if new_unmasked
                    else sample.timestamp
                )
                reconciliation_previous = (
                    _reconciliation_at_or_before(
                        previous_reconciliation, edge_timestamp
                    )
                    if new_unmasked
                    else previous_reconciliation
                )
                runtime, reconciliation, completed_sessions, accepted = (
                    reconcile_component_runtime(
                    source_power_w=source_power_w,
                    timestamp=edge_timestamp,
                    assignments=assignments,
                    runtime=runtime,
                    edges=new_unmasked,
                    standby_w=standby_w,
                    noise_spread_w=detector.noise_spread_w,
                    previous_reconciliation=reconciliation_previous,
                    helper_events=self._helper_events_by_source[circuit_id],
                    available_helper_ids=available_helper_ids,
                    direct_helper_powers=direct_helper_powers,
                    signature_specs=signature_specs,
                    )
                )
                if (
                    edge_timestamp < sample.timestamp
                    and reconciliation.get("energy_allocation_allowed")
                    and reconciliation.get("consistent")
                ):
                    runtime, reconciliation, followup_completed, _ = (
                        reconcile_component_runtime(
                            source_power_w=sample.real_power,
                            timestamp=sample.timestamp,
                            assignments=assignments,
                            runtime=runtime,
                            edges=(),
                            standby_w=standby_w,
                            noise_spread_w=detector.noise_spread_w,
                            previous_reconciliation=reconciliation,
                            helper_events=self._helper_events_by_source[circuit_id],
                            available_helper_ids=available_helper_ids,
                            direct_helper_powers=direct_helper_powers,
                            signature_specs=signature_specs,
                        )
                    )
                    completed_sessions.extend(followup_completed)
            else:
                accepted = ()
            accepted_ids = {id(accepted_edge) for accepted_edge in accepted}
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
                history.sort(
                    key=lambda item: str(
                        item.get("end") or item.get("start") or ""
                    )
                    if isinstance(item, Mapping)
                    else "",
                    reverse=True,
                )
                del history[self._session_history_max_items :]
                store_dirty = True

        next_unmatched = _newest_nilm_edges(
            next_unmatched,
            self._unmatched_edges_max_items,
        )
        if edges:
            self.total_events_by_circuit[circuit_id] += len(edges)
        self.unmatched_edges_by_circuit[circuit_id] = next_unmatched
        persisted_next_unmatched = [
            payload
            for edge in next_unmatched
            if (payload := _nilm_edge_to_storage(edge)) is not None
        ]
        if persisted_next_unmatched != persisted_edge_payloads:
            stored_unmatched_edges[circuit_id] = persisted_next_unmatched
            store_dirty = True

        for match in matched_edges:
            alerts.extend(
                self._observe_topology(circuit_config, match, context),
            )
        for match in rejected_topology_candidates:
            alerts.extend(
                self._observe_topology(circuit_config, match, context),
            )

        evidence_changed = bool(
            edges or next_unmatched != existing_unmatched or helper_events_changed
        )
        signatures: list[NilmSignature] = []
        payloads = list(signature_specs)
        if next_unmatched or evidence_changed:
            signatures = cluster_recurring_signatures(
                self.unmatched_edges_by_circuit[circuit_id],
            )
            payloads = self._nilm_signature_payloads(circuit_id, signatures, context)
            if self._helper_links_dirty:
                store_dirty = True
                self._helper_links_dirty = False
            if payloads != context.store_data.nilm_signatures.get(circuit_id, []):
                context.store_data.nilm_signatures[circuit_id] = payloads
                store_dirty = True
        session_history_changed = self.refresh_session_history(
            circuit_id, context.store_data
        )
        if session_history_changed:
            store_dirty = True

        existing_inventory = (
            context.store_data.nilm_unknown_loads_by_circuit.get(circuit_id, {})
        )
        inventory_stale = unknown_load_inventory_needs_rebuild(existing_inventory)
        sessions = context.store_data.nilm_session_history_by_circuit.get(
            circuit_id, ()
        )
        current_inventory = existing_inventory
        if next_unmatched or sessions or evidence_changed or inventory_stale:
            if signatures:
                inventory = build_unknown_load_inventory(
                    circuit_id=circuit_id,
                    signatures=signatures,
                    edges=self.unmatched_edges_by_circuit[circuit_id],
                    sessions=sessions,
                    now=sample.timestamp,
                    time_zone=context.time_zone or "UTC",
                    session_history_max_items=self._session_history_max_items,
                    existing_state=existing_inventory,
                )
            else:
                inventory = migrate_unknown_load_inventory(
                    circuit_id=circuit_id,
                    existing_state=existing_inventory,
                    signature_payloads=payloads,
                    sessions=sessions,
                    now=sample.timestamp,
                    time_zone=context.time_zone or "UTC",
                    session_history_max_items=self._session_history_max_items,
                )
            current_inventory = inventory
            inventory_evidence_changed = (
                evidence_changed or session_history_changed or inventory_stale
            )
            if inventory_evidence_changed and inventory != (
                context.store_data.nilm_unknown_loads_by_circuit.get(circuit_id)
            ):
                context.store_data.nilm_unknown_loads_by_circuit[circuit_id] = (
                    inventory
                )
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
                    unknown_load_inventory=current_inventory,
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
        next_sessions = next_sessions[: self._session_history_max_items]
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
        existing = [
            dict(signature)
            for signature in context.store_data.nilm_signatures.get(circuit_id, [])
            if isinstance(signature, Mapping)
        ]
        signature_list = list(signatures)
        current_records = _nilm_signature_records(signature_list)
        existing_by_v2 = _nilm_signature_multimap(
            existing,
            key="feedback_fingerprint",
            revision=2,
        )
        existing_by_legacy = _nilm_signature_legacy_multimap(existing)
        current_by_legacy = _nilm_signature_legacy_multimap(current_records)
        current_id_by_fingerprint = {
            str(record["feedback_fingerprint"]): str(record["signature_id"])
            for record in current_records
        }
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        ambiguous_existing_ids: set[str] = set()
        for signature, current_record in zip(
            signature_list,
            current_records,
            strict=True,
        ):
            feedback_fingerprint = str(current_record["feedback_fingerprint"])
            legacy_feedback_fingerprint = str(
                current_record["legacy_feedback_fingerprint"]
            )
            current, migration_status = _nilm_signature_metadata_source(
                signature,
                feedback_fingerprint=feedback_fingerprint,
                legacy_feedback_fingerprint=legacy_feedback_fingerprint,
                existing_by_v2=existing_by_v2,
                existing_by_legacy=existing_by_legacy,
                current_by_legacy=current_by_legacy,
            )
            if migration_status == "ambiguous_split":
                ambiguous_existing_ids.update(
                    str(item.get("signature_id") or "")
                    for item in existing_by_legacy.get(legacy_feedback_fingerprint, ())
                )
            metadata_current = current or {}
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
                "unique_day_count": signature.unique_day_count,
                "observation_span_seconds": signature.observation_span_seconds,
                "dispersion_w": signature.dispersion_w,
                "dispersion_var": signature.dispersion_var,
                "dispersion_va": signature.dispersion_va,
                "dispersion_pf": signature.dispersion_pf,
                "normalized_cluster_radius": signature.normalized_cluster_radius,
                "feature_coverage": signature.feature_coverage,
                "topology_consistency": signature.topology_consistency,
                "paired_occurrence_count": signature.paired_occurrence_count,
                "on_off_support": signature.on_off_support,
                "evidence_strength": signature.evidence_strength,
                "model_fit": signature.model_fit,
                "intrinsic_confidence": signature.intrinsic_confidence,
                "validated_precision": signature.validated_precision,
                "confidence": signature.confidence,
                "confidence_kind": signature.confidence_kind,
                "classification": classify_signature(classified_signature),
                "feedback_fingerprint": feedback_fingerprint,
                "legacy_feedback_fingerprint": legacy_feedback_fingerprint,
                "fingerprint_revision": 2,
            }
            matching_edges = [
                edge
                for edge in self.unmatched_edges_by_circuit[circuit_id]
                if _nilm_signature_edge_score(edge, payload) is not None
            ]
            signature_edges = [
                edge for edge in matching_edges
                if edge.timestamp >= context.now - timedelta(minutes=10)
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
                    and _nilm_assignment_owns_signature(
                        item,
                        feedback_fingerprint,
                        current_records,
                    )
                ),
                None,
            )
            legacy_owner = None
            if assignment is not None and _ensure_nilm_assignment_fingerprint(
                assignment,
                feedback_fingerprint,
            ):
                self._helper_links_dirty = True
            if assignment is None:
                legacy_owner = _confirmed_placeholder_owner(
                    payload,
                    matching_edges,
                    context.store_data.nilm_appliance_assignments_by_circuit.get(
                        circuit_id, []
                    ),
                    context.store_data.nilm_session_history_by_circuit.get(
                        circuit_id, []
                    ),
                )
                if legacy_owner is not None:
                    fingerprints = [
                        str(value or "").strip()
                        for value in _list_items(
                            legacy_owner.get("signature_fingerprints")
                        )
                        if str(value or "").strip().casefold() != "unassigned"
                    ]
                    legacy_owner["signature_fingerprints"] = list(
                        dict.fromkeys((*fingerprints, feedback_fingerprint))
                    )
                    legacy_owner["updated_at"] = context.now.isoformat()
                    assignment = legacy_owner
                    self._helper_links_dirty = True
            if assignment is not None and _record_assignment_model_drift(
                assignment, feedback_fingerprint, signature_edges
            ):
                self._helper_links_dirty = True
            if assignment is not None:
                _enrich_nilm_payload_confidence(payload, assignment)
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
            for key in ("expected", "review_state", "merged_into"):
                if key in metadata_current:
                    payload[key] = metadata_current[key]
            if legacy_owner is not None:
                payload["review_state"] = "assigned"
                payload["assignment_id"] = legacy_owner["assignment_id"]
            elif migration_status:
                payload["migration_status"] = migration_status
                payload["review_state"] = "needs_review"
                payload["split_into_fingerprints"] = sorted(
                    str(item["feedback_fingerprint"])
                    for item in current_by_legacy.get(
                        legacy_feedback_fingerprint,
                        (),
                    )
                )
            target_fingerprint = metadata_current.get("merged_into_fingerprint")
            if target_fingerprint:
                payload["merged_into_fingerprint"] = target_fingerprint
                resolved_target = resolve_nilm_signature_fingerprint(
                    str(target_fingerprint),
                    current_records,
                )
                payload["merged_into"] = current_id_by_fingerprint.get(
                    resolved_target or str(target_fingerprint),
                    payload.get("merged_into"),
                )
            payloads.append(payload)
            seen.add(signature.signature_id)
            if metadata_current.get("signature_id"):
                seen.add(str(metadata_current["signature_id"]))

        for signature in existing:
            signature_id = str(signature.get("signature_id") or "")
            if signature_id in ambiguous_existing_ids:
                signature = {
                    **signature,
                    "migration_status": "ambiguous_split",
                    "review_state": "needs_review",
                    "split_into_fingerprints": sorted(
                        str(item["feedback_fingerprint"])
                        for item in current_by_legacy.get(
                            str(signature.get("legacy_feedback_fingerprint")
                            or signature.get("feedback_fingerprint")
                            or ""),
                            (),
                        )
                    ),
                }
            if signature_id not in seen and (
                signature.get("user_label") or signature.get("ignored")
                or signature.get("merged_into")
                or signature.get("review_state")
            ):
                payload = dict(signature)
                payloads.append(payload)

        return payloads


def _nilm_signature_records(
    signatures: Iterable[NilmSignature],
) -> list[dict[str, Any]]:
    """Build the small identity records used for safe fingerprint migration."""
    return [
        {
            "signature_id": signature.signature_id,
            "feedback_fingerprint": nilm_signature_fingerprint(signature),
            "legacy_feedback_fingerprint": nilm_signature_fingerprint_v1(signature),
            "fingerprint_revision": 2,
            "median_delta_w": signature.median_delta_w,
            "median_delta_var": signature.median_delta_var,
            "median_delta_va": signature.median_delta_va,
            "median_delta_pf": signature.median_delta_pf,
            "median_leg_a_delta_w": signature.median_leg_a_delta_w,
            "median_leg_b_delta_w": signature.median_leg_b_delta_w,
            "leg_balance_ratio": signature.leg_balance_ratio,
            "dominant_leg": signature.dominant_leg,
            "split_phase_type": signature.split_phase_type,
        }
        for signature in signatures
    ]


def _nilm_signature_multimap(
    signatures: Iterable[Mapping[str, Any]],
    *,
    key: str,
    revision: int | None = None,
) -> defaultdict[str, list[dict[str, Any]]]:
    """Index identities without silently selecting one collided persisted row."""
    indexed: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for signature in signatures:
        value = str(signature.get(key) or "").strip()
        if not value:
            continue
        if revision is not None and _nilm_fingerprint_revision(value) != revision:
            continue
        indexed[value].append(dict(signature))
    return indexed


def _nilm_signature_legacy_multimap(
    signatures: Iterable[Mapping[str, Any]],
) -> defaultdict[str, list[dict[str, Any]]]:
    """Index every persisted v1 alias, including unversioned legacy primaries."""
    indexed: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for signature in signatures:
        values = [
            str(signature.get("legacy_feedback_fingerprint") or "").strip(),
        ]
        fingerprint = str(signature.get("feedback_fingerprint") or "").strip()
        if fingerprint and _nilm_fingerprint_revision(fingerprint) != 2:
            values.append(fingerprint)
        for value in dict.fromkeys(values):
            if value:
                indexed[value].append(dict(signature))
    return indexed


def _nilm_fingerprint_revision(value: str) -> int | None:
    first = str(value or "").split("|", 1)[0]
    if not first.startswith("revision="):
        return None
    try:
        return int(first.split("=", 1)[1])
    except ValueError:
        return None


def _nilm_signature_metadata_source(
    signature: NilmSignature,
    *,
    feedback_fingerprint: str,
    legacy_feedback_fingerprint: str,
    existing_by_v2: Mapping[str, list[dict[str, Any]]],
    existing_by_legacy: Mapping[str, list[dict[str, Any]]],
    current_by_legacy: Mapping[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Select metadata only when the old durable identity resolves uniquely."""
    exact = existing_by_v2.get(feedback_fingerprint, ())
    if len(exact) == 1:
        return exact[0], None
    legacy = existing_by_legacy.get(legacy_feedback_fingerprint, ())
    children = current_by_legacy.get(legacy_feedback_fingerprint, ())
    if len(legacy) == 1 and len(children) == 1:
        candidate = legacy[0]
        if _nilm_signature_metadata_compatible(signature, candidate):
            return candidate, None
    if legacy and len(children) > 1:
        return None, "ambiguous_split"
    return None, None


def _nilm_assignment_owns_signature(
    assignment: Mapping[str, Any],
    feedback_fingerprint: str,
    current_records: Iterable[Mapping[str, Any]],
) -> bool:
    for value in _list_items(assignment.get("signature_fingerprints")):
        fingerprint = str(value or "").strip()
        if fingerprint == feedback_fingerprint:
            return True
        if (
            fingerprint
            and resolve_nilm_signature_fingerprint(fingerprint, current_records)
            == feedback_fingerprint
        ):
            return True
    return False


def _ensure_nilm_assignment_fingerprint(
    assignment: dict[str, Any],
    feedback_fingerprint: str,
) -> bool:
    """Persist the uniquely resolved v2 ownership alias beside its legacy key."""
    fingerprints = [
        str(value or "").strip()
        for value in _list_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    ]
    if feedback_fingerprint in fingerprints:
        return False
    assignment["signature_fingerprints"] = list(
        dict.fromkeys((*fingerprints, feedback_fingerprint))
    )
    return True


def _enrich_nilm_payload_confidence(
    payload: dict[str, Any],
    assignment: Mapping[str, Any],
) -> None:
    """Blend history precision only after enough evaluable predictions exist."""
    evaluated = _nonnegative_int(assignment.get("validation_evaluable_session_count"))
    precision = _finite_float(assignment.get("validation_precision"))
    if evaluated < 3 or precision is None or not 0.0 <= precision <= 1.0:
        return
    intrinsic = _finite_float(payload.get("intrinsic_confidence")) or 0.0
    confidence = (0.9 * intrinsic) + (0.1 * precision)
    if _nonnegative_int(payload.get("unique_day_count")) <= 1:
        confidence = min(confidence, 0.65)
    if (_finite_float(payload.get("on_off_support")) or 0.0) <= 0.0:
        confidence = min(confidence, 0.75)
    payload["validated_precision"] = round(precision, 3)
    payload["confidence"] = round(min(max(confidence, 0.0), 0.95), 3)


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
    available_helper_ids: set[str] | frozenset[str] = frozenset(),
    direct_helper_powers: Mapping[str, Any] | None = None,
    signature_specs: Iterable[Mapping[str, Any]] = (),
) -> tuple[
    dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[NilmEdge]
]:
    """Apply bounded assignment transitions and enforce source conservation."""
    assignments = tuple(assignments)
    edges = tuple(edges)
    signature_specs = tuple(signature_specs)
    models = tuple(
        model
        for item in assignments
        if not _direct_helper_id(item)
        if (
            model := _runtime_assignment_model(item, signature_specs)
        ).transition_prototypes
    )
    validation_profiles = _runtime_validation_profiles(assignments, models)
    validation_scores = {
        assignment_id: profile["runtime_score"]
        for assignment_id, profile in validation_profiles.items()
    }
    assignments_by_id = {
        str(item.get("assignment_id") or ""): item for item in assignments
    }
    next_runtime = {key: dict(value) for key, value in runtime.items()}
    for payload in next_runtime.values():
        _runtime_provenance_defaults(payload)
    before_sample = {key: dict(value) for key, value in next_runtime.items()}
    accepted: list[NilmEdge] = []
    completed: list[dict[str, Any]] = []
    session_closes: list[
        tuple[str, NilmTransitionPrototype, NilmEdge, dict[str, Any]]
    ] = []
    conflict: str | None = None
    ambiguous_event_increment = 0
    evidence_diagnostics: defaultdict[str, int] = defaultdict(int)
    unavailable_reasons: defaultdict[str, int] = defaultdict(int)

    if source_power_w is None or not isfinite(source_power_w):
        _suspend_runtime(next_runtime)
        return next_runtime, _runtime_reconciliation(
            None, standby_w, next_runtime, noise_spread_w,
            "source_unavailable", timestamp, previous_reconciliation,
            total_event_increment=len(edges),
        ), completed, accepted

    direct_closes, direct_unavailable = _apply_direct_component_sample(
        assignments, next_runtime, direct_helper_powers or {}, timestamp
    )
    if direct_unavailable:
        conflict = "direct_helper_unavailable"

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
        helper_scores = _confirmed_helper_scores(
            assignments, helper_events, edge, available_helper_ids
        )
        duration_scores = _runtime_duration_state_scores(
            assignments, models, next_runtime, edge, current
        )
        candidates = _runtime_candidate_transitions(models, current, edge)
        candidate_assignment_ids = {
            prototype.assignment_id for prototype in candidates
        }
        helper_conflict = _confirmed_helper_conflict(
            assignments,
            helper_events,
            edge,
            available_helper_ids,
            models,
            current,
        )
        duration_available = any(
            _runtime_transition_score(duration_scores, prototype) is not None
            for prototype in candidates
        )
        validation_available = any(
            validation_scores.get(assignment_id) is not None
            for assignment_id in candidate_assignment_ids
        )
        evidence_diagnostics["duration_channel_available_count"] += int(
            duration_available
        )
        evidence_diagnostics["validation_channel_available_count"] += int(
            validation_available
        )
        if candidates and not duration_available:
            unavailable_reasons["duration_unavailable"] += 1
        for reason in {
            _runtime_validation_unavailable_reason(
                assignments_by_id[assignment_id],
                validation_profiles[assignment_id],
            )
            for assignment_id in candidate_assignment_ids
            if validation_scores.get(assignment_id) is None
        }:
            unavailable_reasons[reason] += 1
        result = reconcile_nilm_edge(
            edge,
            models,
            current,
            helper_scores,
            duration_scores,
            validation_scores,
            helper_conflict=helper_conflict,
        )
        if not result.accepted:
            if result.reason == "ambiguous":
                ambiguous_event_increment += 1
                evidence_diagnostics[
                    "ambiguous_with_secondary_evidence_count"
                    if duration_available or validation_available or helper_scores
                    else "ambiguous_without_secondary_evidence_count"
                ] += 1
            if result.reason == "helper_conflict":
                conflict = result.reason
            continue
        if duration_available:
            without_duration = reconcile_nilm_edge(
                edge, models, current, helper_scores, {}, validation_scores,
                helper_conflict=helper_conflict,
            )
            evidence_diagnostics["duration_rank_impact_count"] += int(
                without_duration.accepted_prototype_ids
                != result.accepted_prototype_ids
            )
        if validation_available:
            without_validation = reconcile_nilm_edge(
                edge, models, current, helper_scores, duration_scores, {},
                helper_conflict=helper_conflict,
            )
            evidence_diagnostics["validation_rank_impact_count"] += int(
                without_validation.accepted_prototype_ids
                != result.accepted_prototype_ids
            )
        pending_sessions: list[tuple[str, NilmTransitionPrototype, NilmEdge]] = []
        pending_predictions: list[
            tuple[str, dict[str, Any], bool]
        ] = []
        for transition in result.transitions:
            payload = next_runtime[transition.assignment_id]
            is_stop = _runtime_transition_is_stop(transition)
            is_start = _runtime_transition_is_start(payload, transition)
            matched_helper_evidence = _matched_corroborating_links(
                assignments,
                transition.assignment_id,
                helper_events,
                edge,
                available_helper_ids,
            )
            if not is_stop:
                payload.update({
                    "status": NilmComponentStatus.ON,
                    "state_power_w": transition.to_state_w,
                    "current_state_id": _runtime_transition_state_id(transition),
                    "current_state_power_w": transition.to_state_w,
                    "state_since": edge.timestamp.isoformat(),
                    "estimated_power_w": transition.to_state_w,
                    "confidence": _model_confidence(models, transition.assignment_id),
                    "consistent": True,
                    "last_observed": edge.timestamp.isoformat(),
                })
                if is_start:
                    payload.update({
                        "session_id": (
                            f"{transition.assignment_id}|"
                            f"{edge.timestamp.isoformat()}"
                        ),
                        "session_start": edge.timestamp.isoformat(),
                        "energy_kwh": 0.0,
                        "on_delta_w": transition.delta_w,
                        "on_delta_var": edge.delta_var,
                        "helper_evidence": matched_helper_evidence,
                        "state_path": [],
                        "accepted_predictions": [],
                        "start_prediction": None,
                    })
            else:
                existing_helper_ids = {
                    item.get("helper_circuit_id")
                    for item in _list_items(payload.get("helper_evidence"))
                    if isinstance(item, Mapping)
                }
                payload["helper_evidence"] = [
                    *_list_items(payload.get("helper_evidence")),
                    *(
                        item
                        for item in matched_helper_evidence
                        if item.get("helper_circuit_id") not in existing_helper_ids
                    ),
                ]
                if payload.get("session_id") and payload.get("session_start"):
                    pending_sessions.append(
                        (transition.assignment_id, transition, edge)
                    )
                payload.update({
                    "status": NilmComponentStatus.OFF,
                    "state_power_w": transition.to_state_w,
                    "current_state_id": _runtime_transition_state_id(transition),
                    "current_state_power_w": transition.to_state_w,
                    "state_since": edge.timestamp.isoformat(),
                    "last_stop": edge.timestamp.isoformat(),
                    "estimated_power_w": 0.0,
                })
            pending_predictions.append((
                transition.assignment_id,
                _runtime_prediction_summary(result, transition, models, edge),
                is_start,
            ))
        _scale_runtime_estimates(
            assignments,
            next_runtime,
            source_power_w=source_power_w,
            standby_w=standby_w,
            tolerance_w=conservation_tolerance_w(source_power_w, noise_spread_w),
        )
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
        for assignment_id, prediction, is_start in pending_predictions:
            _record_runtime_prediction(
                next_runtime[assignment_id], prediction, is_start=is_start
            )
        session_closes.extend(
            (
                assignment_id,
                transition,
                close_edge,
                _runtime_session_snapshot(next_runtime[assignment_id]),
            )
            for assignment_id, transition, close_edge in pending_sessions
        )

    tolerance = conservation_tolerance_w(source_power_w, noise_spread_w)
    _scale_runtime_estimates(
        assignments,
        next_runtime,
        source_power_w=source_power_w,
        standby_w=standby_w,
        tolerance_w=tolerance,
    )
    if _runtime_allocated_power(next_runtime) > source_power_w - standby_w + tolerance:
        _suspend_runtime(next_runtime)
        conflict = "over_allocation"
    increments, source_interval, standby_interval, energy_tolerance = (
        _runtime_energy_increments(
        before_sample, timestamp, previous_reconciliation
        )
    )
    previous_source_energy = _finite_float(
        (previous_reconciliation or {}).get("source_energy_kwh")
    ) or 0.0
    previous_component_energy = _finite_float(
        (previous_reconciliation or {}).get("component_energy_kwh")
    ) or 0.0
    component_interval = sum(increments.values())
    if conflict is None and (
        component_interval
        > source_interval - standby_interval + energy_tolerance
        or previous_component_energy + component_interval
        > previous_source_energy + source_interval + energy_tolerance
    ):
        changed_assignments = {
            assignment_id
            for assignment_id, payload in next_runtime.items()
            if payload != before_sample.get(assignment_id)
        }
        next_runtime = before_sample
        _suspend_runtime(next_runtime)
        for assignment_id in changed_assignments:
            next_runtime[assignment_id]["status"] = NilmComponentStatus.UNCERTAIN
        conflict = "energy_over_allocation"
        accepted.clear()
        session_closes.clear()
        completed.clear()
    elif conflict is None:
        for assignment_id, increment in increments.items():
            closing_snapshot = next((
                snapshot
                for close_id, _, _, snapshot in session_closes
                if close_id == assignment_id
                and snapshot.get("session_id")
                == before_sample.get(assignment_id, {}).get("session_id")
            ), None)
            target = closing_snapshot or next_runtime[assignment_id]
            target["energy_kwh"] = (
                _finite_float(target.get("energy_kwh")) or 0.0
            ) + increment
        session_closes.extend(
            (
                assignment_id,
                transition,
                NilmEdge(timestamp, transition.delta_w, 0.0, 0.0, 0.0, "off"),
                _runtime_session_snapshot(next_runtime[assignment_id]),
            )
            for assignment_id, transition in direct_closes
        )
        completed.extend(
            _completed_runtime_session(
                assignment_id,
                session_runtime,
                transition,
                close_edge,
                assignments,
            )
            for assignment_id, transition, close_edge, session_runtime
            in session_closes
        )
        for assignment_id, _, _, session_runtime in session_closes:
            if next_runtime[assignment_id].get("session_id") != session_runtime.get(
                "session_id"
            ):
                continue
            next_runtime[assignment_id].update({
                "session_id": None,
                "session_start": None,
                "energy_kwh": 0.0,
                "helper_evidence": [],
                "state_path": [],
                "accepted_predictions": [],
                "start_prediction": None,
            })
    consistent = conflict is None
    for payload in next_runtime.values():
        payload["consistent"] = consistent
        payload["last_observed"] = timestamp.isoformat()
    return next_runtime, _runtime_reconciliation(
        source_power_w, standby_w, next_runtime, noise_spread_w,
        conflict, timestamp, previous_reconciliation,
        source_interval if conflict is None else 0.0,
        standby_interval if conflict is None else 0.0,
        component_interval if conflict is None else 0.0,
        len(edges),
        ambiguous_event_increment,
        {
            **evidence_diagnostics,
            "evidence_unavailable_reason_counts": dict(unavailable_reasons),
        },
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
        payload = runtime.setdefault(assignment_id, {
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
        _runtime_provenance_defaults(payload)
    return runtime


def _runtime_provenance_defaults(payload: dict[str, Any]) -> None:
    """Hydrate additive runtime fields without invalidating legacy payloads."""
    status = payload.get("status")
    state_id = (
        "off"
        if status == NilmComponentStatus.OFF
        else "running"
        if status == NilmComponentStatus.ON
        else None
    )
    payload.setdefault("current_state_id", state_id)
    payload.setdefault("current_state_power_w", payload.get("state_power_w"))
    payload.setdefault(
        "state_since",
        payload.get("session_start") if status == NilmComponentStatus.ON else None,
    )
    payload.setdefault("last_stop", None)
    payload["state_path"] = [
        dict(item)
        for item in _list_items(payload.get("state_path"))
        if isinstance(item, Mapping)
    ][-_NILM_RUNTIME_STATE_PATH_LIMIT:]
    payload["accepted_predictions"] = [
        dict(item)
        for item in _list_items(payload.get("accepted_predictions"))
        if isinstance(item, Mapping)
    ][-_NILM_RUNTIME_PREDICTION_LIMIT:]
    if not isinstance(payload.get("start_prediction"), Mapping):
        payload["start_prediction"] = None


def _runtime_session_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = dict(payload)
    for name in ("state_path", "accepted_predictions", "helper_evidence"):
        snapshot[name] = [
            dict(item) if isinstance(item, Mapping) else item
            for item in _list_items(payload.get(name))
        ]
    if isinstance(payload.get("start_prediction"), Mapping):
        snapshot["start_prediction"] = dict(payload["start_prediction"])
    return snapshot


def _runtime_transition_is_stop(transition: NilmTransitionPrototype) -> bool:
    kind = transition.transition_kind.strip().lower()
    return (
        kind == "stop"
        or transition.to_state_id == "off"
        or (
            transition.direction == "off"
            and isfinite(transition.to_state_w)
            and abs(transition.to_state_w) <= 1e-6
        )
    )


def _runtime_transition_is_start(
    runtime: Mapping[str, Any], transition: NilmTransitionPrototype
) -> bool:
    kind = transition.transition_kind.strip().lower()
    return (
        kind == "start"
        or transition.from_state_id == "off"
        or (
            not runtime.get("session_id")
            and isfinite(transition.from_state_w)
            and abs(transition.from_state_w) <= 1e-6
        )
    )


def _runtime_transition_state_id(transition: NilmTransitionPrototype) -> str:
    if transition.to_state_id:
        return transition.to_state_id
    return "off" if _runtime_transition_is_stop(transition) else "running"


def _runtime_prediction_summary(
    result: NilmReconciliationResult,
    transition: NilmTransitionPrototype,
    models: Iterable[NilmAssignmentModel],
    edge: NilmEdge,
) -> dict[str, Any]:
    model = next(
        item for item in models if item.assignment_id == transition.assignment_id
    )
    breakdown = _runtime_prediction_breakdown(result, transition)
    unavailable = [
        name
        for name, value in (
            ("helper", breakdown.helper_score),
            ("duration", breakdown.duration_state_score),
            ("validation", breakdown.validation_score),
        )
        if value is None
    ]
    return {
        "prediction_timestamp": edge.timestamp.isoformat(),
        "model_schema_version": getattr(model, "model_schema_version", 0),
        "model_revision": getattr(model, "model_revision", 0),
        "model_fingerprint": getattr(model, "model_fingerprint", ""),
        "prototype_id": transition.prototype_id or transition.assignment_id,
        "transition_kind": transition.transition_kind or transition.direction,
        "candidate_score": breakdown.total,
        "winner_margin": result.score_margin,
        "channel_breakdown": {
            "electrical": breakdown.electrical_fit,
            "helper": breakdown.helper_score,
            "duration": breakdown.duration_state_score,
            "validation": breakdown.validation_score,
        },
        "unavailable_channels": unavailable,
        "state_id": _runtime_transition_state_id(transition),
        "state_power_w": transition.to_state_w,
    }


def _runtime_prediction_breakdown(
    result: NilmReconciliationResult,
    transition: NilmTransitionPrototype,
) -> NilmScoreBreakdown:
    prototype_id = transition.prototype_id or transition.assignment_id
    candidates = (
        result.component_breakdowns if result.compound else result.score_breakdowns
    )
    return next(
        item
        for item in candidates
        if item.assignment_id == transition.assignment_id
        and item.prototype_id == prototype_id
    )


def _record_runtime_prediction(
    runtime: dict[str, Any],
    prediction: Mapping[str, Any],
    *,
    is_start: bool,
) -> None:
    summary = dict(prediction)
    runtime["state_path"] = [
        *_list_items(runtime.get("state_path")),
        {
            "timestamp": summary["prediction_timestamp"],
            "state_id": summary["state_id"],
            "state_power_w": summary["state_power_w"],
            "prototype_id": summary["prototype_id"],
            "model_revision": summary["model_revision"],
        },
    ][-_NILM_RUNTIME_STATE_PATH_LIMIT:]
    runtime["accepted_predictions"] = [
        *_list_items(runtime.get("accepted_predictions")),
        summary,
    ][-_NILM_RUNTIME_PREDICTION_LIMIT:]
    if is_start:
        runtime["start_prediction"] = summary
    runtime["last_prediction"] = summary


def _restore_unique_component_state(
    source_power_w: Any,
    standby_w: float,
    noise_spread_w: float,
    assignments: Iterable[Mapping[str, Any]],
    runtime: dict[str, dict[str, Any]],
    timestamp: datetime,
    signature_specs: Iterable[Mapping[str, Any]] = (),
) -> None:
    source = _finite_float(source_power_w)
    if source is None:
        return
    models = tuple(sorted(
        (
            model
            for item in assignments
            if _direct_helper_id(item) is None
            if (
                model := _runtime_assignment_model(item, signature_specs)
            ).lifecycle_state
            in {"assigned", "validated", "published"}
            and model.model_confidence >= 0.70
            and len(model.power_states_w) >= 2
            and any(state > 0.0 for state in model.power_states_w)
            and model.transition_prototypes
        ),
        key=lambda model: (
            -model.last_observed.timestamp()
            if model.last_observed is not None
            else float("inf"),
            model.assignment_id,
        ),
    )[:20])
    compound_eligible = {
        model.assignment_id
        for model in models
        if {
            prototype.direction
            for prototype in model.transition_prototypes
            if prototype.sample_count >= 3
        }
        == {"on", "off"}
    }
    unknown = [
        model for model in models
        if runtime[model.assignment_id]["status"] == NilmComponentStatus.UNKNOWN
    ]
    if not unknown:
        return
    known = _runtime_allocated_power(runtime)
    tolerance = conservation_tolerance_w(source, noise_spread_w)
    target = source - standby_w - known
    ordered = tuple(sorted(unknown, key=lambda model: model.assignment_id))
    powers = tuple(max(model.power_states_w, default=0.0) for model in ordered)
    remaining = [0.0] * (len(powers) + 1)
    for index in range(len(powers) - 1, -1, -1):
        remaining[index] = remaining[index + 1] + powers[index]
    fits: list[tuple[float, tuple[str, ...]]] = []

    def search(index: int, total: float, active_ids: tuple[str, ...]) -> None:
        if len(fits) > 1 and fits[0][0] == fits[1][0] == 0.0:
            return
        if total > target + tolerance or total + remaining[index] < target - tolerance:
            return
        if index == len(ordered):
            if len(active_ids) > 1 and not set(active_ids) <= compound_eligible:
                return
            residual = abs(target - total)
            if residual <= tolerance:
                fits.append((residual, active_ids))
                fits.sort(key=lambda item: (item[0], len(item[1]), item[1]))
                del fits[2:]
            return
        search(index + 1, total, active_ids)
        search(
            index + 1,
            total + powers[index],
            (*active_ids, ordered[index].assignment_id),
        )

    search(0, 0.0, ())
    uniqueness_margin = max(5.0, tolerance * 0.25)
    if not fits or (
        len(fits) > 1 and fits[1][0] - fits[0][0] <= uniqueness_margin
    ):
        return
    active = set(fits[0][1])
    for model in unknown:
        power = (
            max(model.power_states_w, default=0.0)
            if model.assignment_id in active else 0.0
        )
        runtime[model.assignment_id].update({
            "status": NilmComponentStatus.ON if power else NilmComponentStatus.OFF,
            "state_power_w": power,
            "current_state_id": "running" if power else "off",
            "current_state_power_w": power,
            "state_since": timestamp.isoformat(),
            "estimated_power_w": power,
            "confidence": model.model_confidence,
            "consistent": True,
            "session_id": (
                f"{model.assignment_id}|{timestamp.isoformat()}" if power else None
            ),
            "session_start": timestamp.isoformat() if power else None,
        })


def _scale_runtime_estimates(
    assignments: Iterable[Mapping[str, Any]],
    runtime: Mapping[str, dict[str, Any]],
    *,
    source_power_w: float,
    standby_w: float,
    tolerance_w: float,
) -> None:
    direct_ids = {
        str(assignment.get("assignment_id") or "")
        for assignment in assignments
        if _direct_helper_id(assignment) is not None
    }
    for assignment_id, payload in runtime.items():
        if (
            assignment_id not in direct_ids
            and payload.get("status") == NilmComponentStatus.ON
        ):
            payload["estimated_power_w"] = payload.get("state_power_w")
    fixed_power = sum(
        _finite_float(payload.get("estimated_power_w")) or 0.0
        for assignment_id, payload in runtime.items()
        if assignment_id in direct_ids
        and payload.get("status") == NilmComponentStatus.ON
    )
    estimated_ids = [
        assignment_id
        for assignment_id, payload in runtime.items()
        if assignment_id not in direct_ids
        and payload.get("status") == NilmComponentStatus.ON
        and (_finite_float(payload.get("estimated_power_w")) or 0.0) > 0.0
    ]
    estimated_total = sum(
        _finite_float(runtime[assignment_id].get("estimated_power_w")) or 0.0
        for assignment_id in estimated_ids
    )
    available = max(source_power_w - standby_w - fixed_power, 0.0)
    if (
        not estimated_ids
        or estimated_total <= 0.0
        or abs(estimated_total - available) > tolerance_w
    ):
        return
    scale = available / estimated_total
    for assignment_id in estimated_ids:
        runtime[assignment_id]["estimated_power_w"] = (
            (_finite_float(runtime[assignment_id].get("estimated_power_w")) or 0.0)
            * scale
        )


def _direct_helper_id(assignment: Mapping[str, Any]) -> str | None:
    return next((
        str(link.get("helper_circuit_id") or "").strip()
        for link in _list_items(assignment.get("helper_links"))
        if isinstance(link, Mapping)
        and link.get("status") == "confirmed"
        and link.get("relationship") == "direct_component"
        and str(link.get("helper_circuit_id") or "").strip()
    ), None)


def _direct_helper_ids(assignments: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        helper_id
        for assignment in assignments
        if (helper_id := _direct_helper_id(assignment)) is not None
    }


def _apply_direct_component_sample(
    assignments: Iterable[Mapping[str, Any]],
    runtime: dict[str, dict[str, Any]],
    helper_powers: Mapping[str, Any],
    timestamp: datetime,
) -> tuple[list[tuple[str, NilmTransitionPrototype]], bool]:
    closes: list[tuple[str, NilmTransitionPrototype]] = []
    unavailable = False
    for assignment in assignments:
        helper_id = _direct_helper_id(assignment)
        if helper_id is None:
            continue
        power = _finite_float(helper_powers.get(helper_id))
        if power is None:
            payload = runtime[str(assignment.get("assignment_id") or "")]
            if payload.get("status") == NilmComponentStatus.ON:
                payload["status"] = NilmComponentStatus.UNCERTAIN
            payload["consistent"] = False
            unavailable = True
            continue
        assignment_id = str(assignment.get("assignment_id") or "")
        payload = runtime[assignment_id]
        was_on = payload.get("status") == NilmComponentStatus.ON
        previous_power = _finite_float(payload.get("estimated_power_w")) or 0.0
        has_open_session = bool(
            payload.get("session_id") and payload.get("session_start")
        )
        is_on = power > 0.0
        link = next(
            link for link in _list_items(assignment.get("helper_links"))
            if isinstance(link, Mapping)
            and str(link.get("helper_circuit_id") or "") == helper_id
            and link.get("relationship") == "direct_component"
        )
        if is_on and not has_open_session:
            payload.update({
                "session_id": f"{assignment_id}|{timestamp.isoformat()}",
                "session_start": timestamp.isoformat(),
                "energy_kwh": 0.0,
                "on_delta_w": power - previous_power,
                "start_prediction": None,
                "last_prediction": None,
                "accepted_predictions": [],
                "state_path": [],
            })
        elif has_open_session and not is_on:
            closes.append((assignment_id, NilmTransitionPrototype(
                assignment_id=assignment_id,
                direction="off",
                from_state_w=previous_power,
                to_state_w=0.0,
                delta_w=-previous_power,
                spread_w=0.0,
                sample_count=1,
            )))
        payload.update({
            "status": (
                NilmComponentStatus.ON
                if is_on
                else NilmComponentStatus.OFF
            ),
            "state_power_w": power,
            "current_state_id": "running" if is_on else "off",
            "current_state_power_w": power,
            "estimated_power_w": power,
            "confidence": _finite_float(link.get("confidence")) or 0.0,
        })
        if was_on != is_on:
            payload["state_since"] = timestamp.isoformat()
        if was_on and not is_on:
            payload["last_stop"] = timestamp.isoformat()
    return closes, unavailable


def _runtime_assignment_model(
    assignment: Mapping[str, Any],
    signature_specs: Iterable[Mapping[str, Any]] = (),
) -> NilmAssignmentModel:
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    normalized = normalize_nilm_assignment_model(assignment)
    if not normalized["transition_prototypes"]:
        signatures = tuple(signature_specs)
        by_key = _nilm_signatures_by_key(signatures)
        provisional = []
        legacy_provisional = []
        for fingerprint in _list_items(assignment.get("signature_fingerprints")):
            resolved = resolve_nilm_signature_fingerprint(str(fingerprint), signatures)
            signature = by_key.get(resolved or "")
            signed_watts = _finite_float(
                signature.get("median_delta_w") if signature else None
            )
            if signature is None or signed_watts is None or signed_watts == 0:
                continue
            if signed_watts < 0 and not _list_items(
                assignment.get("confirmed_session_ids")
            ):
                continue
            watts = abs(signed_watts)
            reactive = _finite_float(signature.get("median_delta_var"))
            if signed_watts < 0 and reactive is not None:
                reactive = -reactive
            sample_count = _nonnegative_int(signature.get("occurrence_count"))
            confidence = _clamped_confidence(signature.get("confidence"))
            if signed_watts < 0:
                confidence = max(
                    confidence,
                    _clamped_confidence(assignment.get("confidence")),
                )
            target = legacy_provisional if signed_watts < 0 else provisional
            target.append((watts, reactive, sample_count, confidence))
        if not provisional:
            provisional = legacy_provisional
        if provisional:
            states = sorted({0.0, *(watts for watts, *_ in provisional)})
            prototypes = [
                {
                    "direction": direction,
                    "from_state_w": 0.0 if direction == "on" else watts,
                    "to_state_w": watts if direction == "on" else 0.0,
                    "delta_w": watts if direction == "on" else -watts,
                    "spread_w": 0.0,
                    "sample_count": sample_count,
                    **(
                        {"delta_var": reactive if direction == "on" else -reactive}
                        if reactive is not None
                        else {}
                    ),
                }
                for watts, reactive, sample_count, _confidence in provisional
                for direction in ("on", "off")
            ]
            normalized = {
                **normalized,
                "power_states_w": states,
                "transition_prototypes": prototypes,
                "model_confidence": max(item[3] for item in provisional),
            }
    fingerprints = [
        str(value or "").strip()
        for value in _list_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    ]
    component_eligible = not fingerprints or any(
        map(nilm_signature_is_assignable, fingerprints)
    ) or (
        bool(_list_items(assignment.get("confirmed_session_ids")))
        and any(map(nilm_signature_is_off_direction, fingerprints))
    )
    prototypes = tuple(
        NilmTransitionPrototype(
            assignment_id=assignment_id,
            direction=item["direction"],
            from_state_w=item["from_state_w"],
            to_state_w=item["to_state_w"],
            delta_w=item["delta_w"],
            spread_w=item["spread_w"],
            sample_count=item["sample_count"],
            delta_var=item.get("delta_var"),
            spread_var=item.get("spread_var"),
            prototype_id=item.get("id", ""),
            transition_kind=_runtime_transition_kind(assignment, item),
            from_state_id=item.get("from_state_id", ""),
            to_state_id=item.get("to_state_id", ""),
        )
        for item in normalized["transition_prototypes"]
        if component_eligible
        if item["direction"] == ("on" if item["delta_w"] > 0 else "off")
    )
    return _RuntimeAssignmentModel(
        assignment_id=assignment_id,
        power_states_w=tuple(normalized["power_states_w"]),
        transition_prototypes=prototypes,
        model_confidence=normalized["model_confidence"],
        lifecycle_state=str(assignment.get("lifecycle_state") or ""),
        last_observed=_runtime_datetime(assignment.get("updated_at")),
        model_schema_version=_nonnegative_int(normalized["model_schema_version"]),
        model_revision=_nonnegative_int(normalized["model_revision"]),
        model_fingerprint=str(normalized["model_fingerprint"] or ""),
    )


def _runtime_transition_kind(
    assignment: Mapping[str, Any], normalized: Mapping[str, Any]
) -> str:
    return next(
        (
            str(item.get("kind") or "")
            for item in _list_items(assignment.get("transition_prototypes"))
            if isinstance(item, Mapping)
            and item.get("direction") == normalized.get("direction")
            and _finite_float(item.get("delta_w")) == normalized.get("delta_w")
            and _finite_float(item.get("from_state_w"))
            == normalized.get("from_state_w")
            and _finite_float(item.get("to_state_w")) == normalized.get("to_state_w")
        ),
        "",
    )


def _runtime_duration_state_scores(
    assignments: Iterable[Mapping[str, Any]],
    models: Iterable[NilmAssignmentModel],
    runtime: Mapping[str, Mapping[str, Any]],
    edge: NilmEdge,
    current_states_w: Mapping[str, float | None],
) -> dict[str, float | None]:
    """Build prototype-specific duration scores for one observed edge."""
    assignments_by_id = {
        str(item.get("assignment_id") or ""): item for item in assignments
    }
    candidates = _runtime_legal_transitions(models, current_states_w)
    prototype_counts: defaultdict[str, int] = defaultdict(int)
    for prototype in candidates:
        prototype_counts[prototype.prototype_id] += 1
    assignment_ids = set(assignments_by_id)
    scores: dict[str, float | None] = {}
    for prototype in candidates:
        prototype_id = prototype.prototype_id
        key = (
            prototype_id
            if prototype_id
            and prototype_counts[prototype_id] == 1
            and prototype_id not in assignment_ids
            else prototype.assignment_id
        )
        component_runtime = runtime.get(prototype.assignment_id, {})
        scores[key] = duration_state_score_for_transition(
            prototype,
            assignments_by_id[prototype.assignment_id],
            {
                **component_runtime,
                "session_started_at": component_runtime.get("session_start"),
            },
            edge.timestamp,
        )
    return scores


def _runtime_candidate_transitions(
    models: Iterable[NilmAssignmentModel],
    current_states_w: Mapping[str, float | None],
    edge: NilmEdge,
) -> tuple[NilmTransitionPrototype, ...]:
    return tuple(
        prototype
        for prototype in _runtime_legal_transitions(models, current_states_w)
        if abs(edge.delta_w - prototype.delta_w)
        <= nilm_transition_tolerance_w(prototype)
    )


def _runtime_legal_transitions(
    models: Iterable[NilmAssignmentModel],
    current_states_w: Mapping[str, float | None],
) -> tuple[NilmTransitionPrototype, ...]:
    return tuple(
        prototype
        for model in models
        for prototype in model.transition_prototypes
        if model.lifecycle_state.strip().lower()
        not in {"hidden", "ignored", "rejected", "converted"}
        if not (
            model.lifecycle_state.strip().lower() == "retired"
            and not (
                prototype.direction == "off"
                and current_states_w.get(model.assignment_id)
            )
        )
        if (current := current_states_w.get(model.assignment_id)) is not None
        if isfinite(current)
        if prototype.direction == ("on" if prototype.delta_w > 0 else "off")
        if all(
            any(abs(state - expected) <= 1e-6 for state in model.power_states_w)
            for expected in (prototype.from_state_w, prototype.to_state_w)
        )
        if abs(current - prototype.from_state_w) <= 1e-6
    )


def _runtime_transition_score(
    scores: Mapping[str, float | None], prototype: NilmTransitionPrototype
) -> float | None:
    if prototype.prototype_id and prototype.prototype_id in scores:
        return scores[prototype.prototype_id]
    return scores.get(prototype.assignment_id)


def _runtime_validation_profiles(
    assignments: Iterable[Mapping[str, Any]],
    models: Iterable[NilmAssignmentModel],
) -> dict[str, dict[str, Any]]:
    """Build assignment validation profiles once for one runtime update."""
    model_ids = {model.assignment_id for model in models}
    return {
        assignment_id: build_nilm_validation_profile(assignment)
        for assignment in assignments
        if (assignment_id := str(assignment.get("assignment_id") or ""))
        in model_ids
    }


def _runtime_validation_unavailable_reason(
    assignment: Mapping[str, Any], profile: Mapping[str, Any]
) -> str:
    method = str(assignment.get("validation_method") or "").strip().lower()
    if method and method != "one_to_one_iou":
        return "legacy_validation_method"
    records = [
        item
        for item in _list_items(assignment.get("validation_outcomes"))
        if isinstance(item, Mapping)
    ]
    if not _nonnegative_int(profile.get("sample_count")) and any(
        _runtime_validation_record_revision_mismatch(assignment, record)
        for record in records
    ):
        return "validation_revision_mismatch"
    return "insufficient_validation_support"


def _runtime_validation_record_revision_mismatch(
    assignment: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    expected_revision = _nonnegative_int(assignment.get("model_revision"))
    recorded_revision = _finite_float(
        record.get("model_revision", record.get("prediction_model_revision"))
    )
    expected_fingerprint = str(assignment.get("model_fingerprint") or "").strip()
    recorded_fingerprint = str(
        record.get("model_fingerprint")
        or record.get("prediction_model_fingerprint")
        or ""
    ).strip()
    return (
        recorded_revision is not None
        and expected_revision > 0
        and recorded_revision != expected_revision
    ) or bool(
        recorded_fingerprint
        and expected_fingerprint
        and recorded_fingerprint != expected_fingerprint
    )


def _confirmed_helper_scores(
    assignments: Iterable[Mapping[str, Any]],
    events: Iterable[CircuitEvent],
    edge: NilmEdge,
    available_helper_ids: set[str] | frozenset[str],
) -> dict[str, float | None]:
    events = tuple(events)
    scores: dict[str, float | None] = {}
    expected = "start" if edge.direction == "on" else "stop"
    for assignment in assignments:
        evidence: list[tuple[float, float]] = []
        for link in _list_items(assignment.get("helper_links")):
            link_evidence = _confirmed_helper_link_evidence(
                link, events, edge, available_helper_ids, expected
            )
            if link_evidence is None:
                continue
            _, confidence, matched = link_evidence
            evidence.append((confidence, confidence if matched else 0.0))
        if evidence:
            scores[str(assignment.get("assignment_id") or "")] = round(
                sum(weight * score for weight, score in evidence)
                / sum(weight for weight, _ in evidence)
                if sum(weight for weight, _ in evidence)
                else 0.0,
                6,
            )
    return scores


def _confirmed_helper_conflict(
    assignments: Iterable[Mapping[str, Any]],
    events: Iterable[CircuitEvent],
    edge: NilmEdge,
    available_helper_ids: set[str] | frozenset[str],
    models: Iterable[NilmAssignmentModel],
    current_states_w: Mapping[str, float | None],
) -> bool:
    events = tuple(events)
    eligible = {
        model.assignment_id
        for model in models
        if reconcile_nilm_edge(
            edge,
            (model,),
            current_states_w,
            {model.assignment_id: 1.0},
            {},
            {},
        ).accepted
    }
    helper_assignments: dict[str, set[str]] = {}
    expected = "start" if edge.direction == "on" else "stop"
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "")
        if assignment_id not in eligible:
            continue
        for link in _list_items(assignment.get("helper_links")):
            evidence = _confirmed_helper_link_evidence(
                link, events, edge, available_helper_ids, expected
            )
            if evidence is None:
                continue
            helper_id, confidence, matched = evidence
            if matched and confidence >= 0.75:
                helper_assignments.setdefault(helper_id, set()).add(assignment_id)
    return any(
        len(assignment_ids) > 1
        for assignment_ids in helper_assignments.values()
    )


def _confirmed_helper_link_evidence(
    link: Any,
    events: Iterable[CircuitEvent],
    edge: NilmEdge,
    available_helper_ids: set[str] | frozenset[str],
    expected: str,
) -> tuple[str, float, bool] | None:
    if (
        not isinstance(link, Mapping)
        or link.get("status") != "confirmed"
        or link.get("relationship") != "corroborates"
    ):
        return None
    helper_id = str(link.get("helper_circuit_id") or "")
    if helper_id not in available_helper_ids:
        return None
    confidence = _finite_float(link.get("confidence"))
    lag = _finite_float(link.get(
        "start_lag_seconds" if edge.direction == "on" else "stop_lag_seconds"
    ))
    mad = _finite_float(link.get(
        "start_lag_mad_seconds"
        if edge.direction == "on"
        else "stop_lag_mad_seconds"
    ))
    if confidence is None or lag is None or mad is None:
        return None
    matched = any(
        event.circuit_id == helper_id
        and event.event_type.value == expected
        and abs((event.timestamp - edge.timestamp).total_seconds() - lag)
        <= max(120.0, 3.0 * mad)
        for event in events
    )
    return helper_id, confidence, matched


def _matched_corroborating_links(
    assignments: Iterable[Mapping[str, Any]],
    assignment_id: str,
    events: Iterable[CircuitEvent],
    edge: NilmEdge,
    available_helper_ids: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    assignment = next(
        item for item in assignments if item.get("assignment_id") == assignment_id
    )
    expected = "start" if edge.direction == "on" else "stop"
    return [
        dict(link)
        for link in _list_items(assignment.get("helper_links"))
        if isinstance(link, Mapping)
        and (
            evidence := _confirmed_helper_link_evidence(
                link, events, edge, available_helper_ids, expected
            )
        )
        is not None
        and evidence[2]
    ]


def _runtime_energy_increments(
    runtime: Mapping[str, Mapping[str, Any]],
    timestamp: datetime,
    reconciliation: Mapping[str, Any] | None,
) -> tuple[dict[str, float], float, float, float]:
    if not reconciliation or not reconciliation.get("energy_allocation_allowed"):
        return {}, 0.0, 0.0, 0.0
    increments: dict[str, float] = {}
    observed = _runtime_datetime(reconciliation.get("last_observed"))
    interval_seconds = (
        max((timestamp - observed).total_seconds(), 0.0) if observed else 0.0
    )
    for assignment_id, payload in runtime.items():
        observed = _runtime_datetime(payload.get("last_observed"))
        power = _finite_float(payload.get("estimated_power_w"))
        if (
            observed is None
            or power is None
            or payload.get("status") != NilmComponentStatus.ON
        ):
            continue
        seconds = max((timestamp - observed).total_seconds(), 0.0)
        increments[assignment_id] = power * seconds / 3_600_000.0
    source_power = _finite_float(reconciliation.get("source_power_w")) or 0.0
    standby_power = _finite_float(reconciliation.get("standby_w")) or 0.0
    tolerance_w = _finite_float(reconciliation.get("tolerance_w")) or 0.0
    return (
        increments,
        max(source_power, 0.0) * interval_seconds / 3_600_000.0,
        max(standby_power, 0.0) * interval_seconds / 3_600_000.0,
        tolerance_w * interval_seconds / 3_600_000.0,
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
    predictions = [
        dict(item)
        for item in _list_items(runtime.get("accepted_predictions"))
        if isinstance(item, Mapping)
    ][-_NILM_RUNTIME_PREDICTION_LIMIT:]
    state_path = [
        dict(item)
        for item in _list_items(runtime.get("state_path"))
        if isinstance(item, Mapping)
    ][-_NILM_RUNTIME_STATE_PATH_LIMIT:]
    start_prediction = (
        dict(runtime["start_prediction"])
        if isinstance(runtime.get("start_prediction"), Mapping)
        else None
    )
    stop_prediction = predictions[-1] if predictions else None
    return {
        "session_id": runtime.get("session_id"),
        "assignment_id": assignment_id,
        "start": runtime.get("session_start"),
        "end": edge.timestamp.isoformat(),
        "on_delta_w": runtime.get("on_delta_w"),
        "off_delta_w": transition.delta_w,
        "on_delta_var": runtime.get("on_delta_var"),
        "off_delta_var": edge.delta_var,
        "energy_kwh": _finite_float(runtime.get("energy_kwh")) or 0.0,
        "confidence": min(
            _finite_float(runtime.get("confidence")) or 0.0,
            _finite_float(assignment.get("model_confidence")) or 0.0,
        ),
        "helper_evidence": [
            *(
                dict(link)
                for link in _list_items(assignment.get("helper_links"))
                if isinstance(link, Mapping)
                and link.get("status") == "confirmed"
                and link.get("relationship") == "direct_component"
            ),
            *(
                dict(link)
                for link in _list_items(runtime.get("helper_evidence"))
                if isinstance(link, Mapping)
            ),
        ],
        "start_prototype_id": (
            start_prediction.get("prototype_id") if start_prediction else None
        ),
        "stop_prototype_id": (
            stop_prediction.get("prototype_id") if stop_prediction else None
        ),
        "start_model_revision": (
            start_prediction.get("model_revision") if start_prediction else None
        ),
        "stop_model_revision": (
            stop_prediction.get("model_revision") if stop_prediction else None
        ),
        "start_model_schema_version": (
            start_prediction.get("model_schema_version")
            if start_prediction
            else None
        ),
        "stop_model_schema_version": (
            stop_prediction.get("model_schema_version") if stop_prediction else None
        ),
        "start_model_fingerprint": (
            start_prediction.get("model_fingerprint") if start_prediction else None
        ),
        "stop_model_fingerprint": (
            stop_prediction.get("model_fingerprint") if stop_prediction else None
        ),
        "accepted_predictions": predictions,
        "state_path": state_path,
        "consistent": True,
    }


def _runtime_reconciliation(
    source_power_w: float | None,
    standby_w: float,
    runtime: Mapping[str, Mapping[str, Any]],
    noise_spread_w: float,
    conflict: str | None,
    timestamp: datetime,
    previous: Mapping[str, Any] | None = None,
    source_interval_energy_kwh: float = 0.0,
    standby_interval_energy_kwh: float = 0.0,
    component_interval_energy_kwh: float = 0.0,
    total_event_increment: int = 0,
    ambiguous_event_increment: int = 0,
    evidence_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    allocated = _runtime_allocated_power(runtime)
    residual = (
        source_power_w - standby_w - allocated
        if source_power_w is not None
        else 0.0
    )
    consistent = source_power_w is not None and conflict is None
    conservation_conflicts = {"over_allocation", "energy_over_allocation"}
    previous_conflict = (previous or {}).get("conflict")
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
        "total_event_count": _nonnegative_int(
            (previous or {}).get("total_event_count")
        )
        + total_event_increment,
        "ambiguous_event_count": _nonnegative_int(
            (previous or {}).get("ambiguous_event_count")
        )
        + ambiguous_event_increment,
        "conservation_violations": _nonnegative_int(
            (previous or {}).get("conservation_violations")
        )
        + int(
            conflict in conservation_conflicts
            and previous_conflict not in conservation_conflicts
        ),
        "source_energy_kwh": (
            (_finite_float((previous or {}).get("source_energy_kwh")) or 0.0)
            + source_interval_energy_kwh
        ),
        "component_energy_kwh": (
            (_finite_float((previous or {}).get("component_energy_kwh")) or 0.0)
            + component_interval_energy_kwh
        ),
        "standby_energy_kwh": (
            (_finite_float((previous or {}).get("standby_energy_kwh")) or 0.0)
            + standby_interval_energy_kwh
        ),
        "residual_energy_kwh": (
            (_finite_float((previous or {}).get("residual_energy_kwh")) or 0.0)
            + max(
                source_interval_energy_kwh
                - standby_interval_energy_kwh
                - component_interval_energy_kwh,
                0.0,
            )
        ),
    }
    diagnostics = evidence_diagnostics or {}
    for name in (
        "duration_channel_available_count",
        "validation_channel_available_count",
        "duration_rank_impact_count",
        "validation_rank_impact_count",
        "ambiguous_with_secondary_evidence_count",
        "ambiguous_without_secondary_evidence_count",
    ):
        payload[name] = _nonnegative_int((previous or {}).get(name)) + (
            _nonnegative_int(diagnostics.get(name))
        )
    prior_reasons = (
        (previous or {}).get("evidence_unavailable_reason_counts")
        if isinstance(
            (previous or {}).get("evidence_unavailable_reason_counts"), Mapping
        )
        else {}
    )
    current_reasons = (
        diagnostics.get("evidence_unavailable_reason_counts")
        if isinstance(diagnostics.get("evidence_unavailable_reason_counts"), Mapping)
        else {}
    )
    reason_names = sorted({*prior_reasons, *current_reasons})[:8]
    payload["evidence_unavailable_reason_counts"] = {
        str(name): _nonnegative_int(prior_reasons.get(name))
        + _nonnegative_int(current_reasons.get(name))
        for name in reason_names
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


def _pending_reconciliation_source(
    previous: Any, pending_timestamp: datetime
) -> float | None:
    if not isinstance(previous, Mapping):
        return None
    source = _finite_float(previous.get("source_power_w"))
    observed = _runtime_datetime(previous.get("last_observed"))
    return (
        source
        if source is not None and observed is not None and observed <= pending_timestamp
        else None
    )


def _reconciliation_at_or_before(
    previous: Any, timestamp: datetime
) -> Mapping[str, Any] | None:
    if not isinstance(previous, Mapping):
        return None
    valid = _pending_reconciliation_source(previous, timestamp)
    return previous if valid is not None else None


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
    unknown_load_inventory: Mapping[str, Any] | None = None,
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
            dict(
                unknown_load_inventory
                if unknown_load_inventory is not None
                else context.store_data.nilm_unknown_loads_by_circuit.get(
                    circuit_id, {}
                )
            ),
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


def _nilm_edge_to_storage(edge: NilmEdge) -> dict[str, Any] | None:
    """Serialize full unmatched-edge evidence for durable NILM recovery."""
    if not isinstance(edge.timestamp, datetime):
        return None
    delta_w = _finite_float(edge.delta_w)
    direction = str(edge.direction or "").strip().casefold()
    if delta_w is None or delta_w == 0.0 or direction not in {"on", "off"}:
        return None
    timestamp = edge.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    payload = {
        "timestamp": timestamp.isoformat(),
        "delta_w": delta_w,
        "delta_var": _finite_float(edge.delta_var),
        "delta_va": _finite_float(edge.delta_va),
        "delta_pf": _finite_float(edge.delta_pf),
        "direction": direction,
        "leg_a_delta_w": _finite_float(edge.leg_a_delta_w),
        "leg_b_delta_w": _finite_float(edge.leg_b_delta_w),
        "leg_balance_ratio": _finite_float(edge.leg_balance_ratio),
        "dominant_leg": str(edge.dominant_leg or "unknown"),
        "split_phase_type": str(edge.split_phase_type or "unknown"),
    }
    if edge.origin != "aggregate":
        payload["origin"] = edge.origin
    if edge.parent_edge_id:
        payload["parent_edge_id"] = edge.parent_edge_id
    if edge.explained_known_circuit_ids:
        payload["explained_known_circuit_ids"] = list(edge.explained_known_circuit_ids)
    return payload


def _nilm_edges_from_storage(
    values: Iterable[Any],
    *,
    max_items: int,
) -> list[NilmEdge]:
    """Restore valid raw unmatched-edge evidence from the feature store."""
    edges: list[NilmEdge] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        timestamp = _runtime_datetime(value.get("timestamp"))
        delta_w = _finite_float(value.get("delta_w"))
        direction = str(value.get("direction") or "").strip().casefold()
        if (
            timestamp is None
            or delta_w is None
            or delta_w == 0.0
            or direction not in {"on", "off"}
        ):
            continue
        edges.append(
            NilmEdge(
                timestamp=timestamp,
                delta_w=delta_w,
                delta_var=_finite_float(value.get("delta_var")),
                delta_va=_finite_float(value.get("delta_va")),
                delta_pf=_finite_float(value.get("delta_pf")),
                direction=direction,
                leg_a_delta_w=_finite_float(value.get("leg_a_delta_w")),
                leg_b_delta_w=_finite_float(value.get("leg_b_delta_w")),
                leg_balance_ratio=_finite_float(value.get("leg_balance_ratio")),
                dominant_leg=str(value.get("dominant_leg") or "unknown"),
                split_phase_type=str(value.get("split_phase_type") or "unknown"),
                origin=str(value.get("origin") or "aggregate"),
                parent_edge_id=(
                    str(value["parent_edge_id"])
                    if value.get("parent_edge_id")
                    else None
                ),
                explained_known_circuit_ids=tuple(
                    str(circuit_id)
                    for circuit_id in value.get("explained_known_circuit_ids", ())
                    if str(circuit_id)
                ),
            )
        )
    return _newest_nilm_edges(dict.fromkeys(edges), max_items)


def _confirmed_placeholder_owner(
    signature: Mapping[str, Any],
    edges: Iterable[NilmEdge],
    assignments: Iterable[Any],
    sessions: Iterable[Any],
) -> dict[str, Any] | None:
    """Find one legacy placeholder assignment confirmed for this ON cluster."""
    fingerprint = str(signature.get("feedback_fingerprint") or "").strip()
    if (
        not nilm_signature_is_assignable(fingerprint)
        or _nonnegative_int(signature.get("occurrence_count")) < 3
    ):
        return None
    starts = {
        edge.timestamp
        for edge in edges
        if edge.direction == "on"
        and _nilm_signature_edge_score(edge, signature) is not None
    }
    if len(starts) < 2:
        return None
    matching_sessions = [
        session
        for session in sessions
        if isinstance(session, Mapping)
        and str(session.get("signature_fingerprint") or "").strip().casefold()
        == "unassigned"
        and _runtime_datetime(session.get("start")) in starts
    ]
    owners: list[dict[str, Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        assignment_fingerprints = [
            str(value or "").strip()
            for value in _list_items(assignment.get("signature_fingerprints"))
        ]
        if (
            not assignment_id
            or "unassigned"
            not in {value.casefold() for value in assignment_fingerprints}
            or any(map(nilm_signature_is_assignable, assignment_fingerprints))
            or str(assignment.get("lifecycle_state") or "").strip().casefold()
            in {"hidden", "ignored", "retired", "rejected", "converted"}
        ):
            continue
        confirmed = {
            str(value or "").strip()
            for value in _list_items(assignment.get("confirmed_session_ids"))
            if str(value or "").strip()
        }
        matches = sum(
            1
            for session in matching_sessions
            if str(session.get("session_id") or "").strip() in confirmed
            and str(session.get("assignment_id") or "").strip()
            in {"", assignment_id}
        )
        if matches >= 2:
            owners.append(assignment)
    return owners[0] if len(owners) == 1 else None


def _recover_unassigned_session_edges(
    sessions: Iterable[Any],
    *,
    since: datetime,
    excluded_assignment_ids: set[str] | frozenset[str] = frozenset(),
) -> list[NilmEdge]:
    """Recover placeholder-owned ON transitions for normal recurring clustering."""
    recovered: list[NilmEdge] = []
    for session in sessions:
        if (
            not isinstance(session, Mapping)
            or str(session.get("signature_fingerprint") or "").strip().casefold()
            != "unassigned"
            or str(session.get("assignment_id") or "").strip()
            in excluded_assignment_ids
        ):
            continue
        timestamp = _runtime_datetime(session.get("start"))
        delta_w = _finite_float(session.get("on_delta_w"))
        if timestamp is None or timestamp < since or delta_w is None or delta_w <= 0.0:
            continue
        recovered.append(
            NilmEdge(
                timestamp=timestamp,
                delta_w=delta_w,
                delta_var=_finite_float(session.get("on_delta_var")),
                direction="on",
                origin="recovered_session",
            )
        )
    return recovered


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
    signatures = list(signatures)
    specs: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    seen_fingerprints: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            continue
        fingerprints = [
            str(value or "").strip()
            for value in _list_items(assignment.get("signature_fingerprints"))
            if nilm_signature_is_assignable(value)
        ]
        hidden = str(assignment.get("lifecycle_state") or "").strip() in {
            "ignored",
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
            resolved = resolve_nilm_signature_fingerprint(fingerprint, signatures)
            if resolved is None:
                continue
            key = (resolved, assignment_id)
            if key not in seen:
                specs.append(key)
                seen.add(key)
                seen_fingerprints.add(resolved)
    for signature in signatures:
        fingerprint = _nilm_signature_session_fingerprint(signature)
        key = (fingerprint, None)
        if not nilm_signature_is_assignable(fingerprint):
            continue
        if signature.get("ignored") or signature.get("review_state") == "ignored":
            seen_fingerprints.add(fingerprint)
            continue
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
