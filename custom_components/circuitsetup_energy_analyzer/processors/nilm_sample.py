"""NILM sample processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, MutableMapping, MutableSet
from dataclasses import replace
from typing import Any

from ..models import AlertEvidence, CircuitConfig, CircuitEvent
from ..nilm import (
    NilmEdge,
    NilmEdgeDetector,
    NilmSignature,
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
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
            NilmEdgeDetector(min_delta_w=min_delta_w),
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
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signature in signatures:
            current = existing.get(signature.signature_id, {})
            metadata_current = (
                current if _nilm_signature_metadata_compatible(signature, current)
                else {}
            )
            user_label = metadata_current.get("user_label")
            classified_signature = replace(signature, user_label=user_label)
            ignored = bool(metadata_current.get("ignored")) or (
                circuit_id,
                signature.signature_id,
            ) in self.ignored_signatures and bool(metadata_current)
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
            }
            if user_label:
                payload["user_label"] = user_label
            if ignored:
                payload["ignored"] = True
            for key in ("review_state", "expected", "merged_into"):
                if key in metadata_current:
                    payload[key] = metadata_current[key]
            payloads.append(payload)
            seen.add(signature.signature_id)

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
