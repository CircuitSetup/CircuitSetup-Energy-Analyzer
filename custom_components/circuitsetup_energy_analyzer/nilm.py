from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable

from .models import CircuitEvent, CircuitSample, EventType


@dataclass(frozen=True, slots=True)
class NilmEdge:
    """Aggregate mains power transition candidate."""

    timestamp: datetime
    delta_w: float
    delta_var: float
    delta_va: float
    delta_pf: float
    direction: str


@dataclass(frozen=True, slots=True)
class KnownLoadMatch:
    """NILM edge attributed to an already-known circuit event."""

    edge: NilmEdge
    known_circuit_id: str
    confidence: float


@dataclass(frozen=True, slots=True)
class NilmMaskResult:
    """Known-load masking output."""

    matched_edges: tuple[KnownLoadMatch, ...]
    unmatched_edges: tuple[NilmEdge, ...]


@dataclass(frozen=True, slots=True)
class NilmSignature:
    """Recurring unmatched edge signature for user review."""

    signature_id: str
    median_delta_w: float
    median_delta_var: float
    median_delta_va: float
    median_delta_pf: float
    occurrence_count: int
    confidence: float
    user_label: str | None = None


class NilmEdgeDetector:
    """Detect significant mains real-power transitions."""

    def __init__(self, min_delta_w: float = 100.0) -> None:
        self.min_delta_w = min_delta_w
        self._previous: CircuitSample | None = None

    def process(self, sample: CircuitSample) -> list[NilmEdge]:
        if sample.real_power is None:
            self._previous = None
            return []

        if self._previous is None or self._previous.real_power is None:
            self._previous = sample
            return []

        previous = self._previous
        self._previous = sample

        delta_w = sample.real_power - previous.real_power
        if abs(delta_w) < self.min_delta_w:
            return []

        return [
            NilmEdge(
                timestamp=sample.timestamp,
                delta_w=delta_w,
                delta_var=_delta(sample.reactive_power, previous.reactive_power),
                delta_va=_delta(sample.apparent_power, previous.apparent_power),
                delta_pf=_delta(sample.power_factor, previous.power_factor),
                direction="on" if delta_w > 0 else "off",
            )
        ]

    def process_many(self, samples: Iterable[CircuitSample]) -> list[NilmEdge]:
        edges: list[NilmEdge] = []
        for sample in samples:
            edges.extend(self.process(sample))
        return edges


def mask_known_loads(
    aggregate_edges: Iterable[NilmEdge],
    known_events: Iterable[CircuitEvent],
    time_window: timedelta = timedelta(seconds=15),
    watt_tolerance_ratio: float = 0.25,
) -> NilmMaskResult:
    """Mask aggregate edges explained by known circuit start/stop events."""

    edges = list(aggregate_edges)
    events = list(known_events)
    candidates: list[tuple[int, int, KnownLoadMatch, float]] = []

    for edge_index, edge in enumerate(edges):
        for event_index, event in enumerate(events):
            if event.event_type not in {EventType.START, EventType.STOP}:
                continue
            if event.event_type is EventType.START and edge.direction != "on":
                continue
            if event.event_type is EventType.STOP and edge.direction != "off":
                continue
            time_distance = abs(edge.timestamp - event.timestamp)
            if time_distance > time_window:
                continue
            known_watts = _event_power_w(event)
            if known_watts is None or known_watts <= 0:
                continue

            ratio = abs(abs(edge.delta_w) - known_watts) / known_watts
            if ratio > watt_tolerance_ratio:
                continue

            confidence = max(0.0, 1.0 - (ratio / watt_tolerance_ratio))
            candidates.append(
                (
                    edge_index,
                    event_index,
                    KnownLoadMatch(edge, event.circuit_id, confidence),
                    time_distance.total_seconds(),
                )
            )

    matched_edge_indices: set[int] = set()
    matched_event_indices: set[int] = set()
    selected: list[tuple[int, KnownLoadMatch]] = []

    for edge_index, event_index, match, _time_distance in sorted(
        candidates,
        key=lambda candidate: (
            -candidate[2].confidence,
            candidate[3],
            candidate[0],
            candidate[1],
        ),
    ):
        if edge_index in matched_edge_indices or event_index in matched_event_indices:
            continue
        matched_edge_indices.add(edge_index)
        matched_event_indices.add(event_index)
        selected.append((edge_index, match))

    matched_edges = tuple(match for _index, match in sorted(selected))
    unmatched_edges = tuple(
        edge for index, edge in enumerate(edges) if index not in matched_edge_indices
    )

    return NilmMaskResult(matched_edges, unmatched_edges)


def cluster_recurring_signatures(edges: Iterable[NilmEdge]) -> list[NilmSignature]:
    """Cluster similar recurring edges into conservative NILM signatures."""

    sorted_edges = sorted(
        edges,
        key=lambda edge: (
            edge.direction,
            abs(edge.delta_w),
            edge.delta_w,
            edge.delta_var,
            edge.delta_va,
            edge.delta_pf,
            edge.timestamp,
        ),
    )

    clusters: list[list[NilmEdge]] = []
    for edge in sorted_edges:
        for cluster in clusters:
            if _edge_similar_to_cluster(edge, cluster):
                cluster.append(edge)
                break
        else:
            clusters.append([edge])

    signatures: list[NilmSignature] = []
    for index, cluster in enumerate(clusters, start=1):
        if len(cluster) < 3:
            continue

        median_w = float(median(candidate.delta_w for candidate in cluster))
        median_var = float(median(candidate.delta_var for candidate in cluster))
        median_va = float(median(candidate.delta_va for candidate in cluster))
        median_pf = float(median(candidate.delta_pf for candidate in cluster))
        confidence = min(0.95, 0.6 + ((len(cluster) - 3) * 0.1))
        direction = cluster[0].direction
        signatures.append(
            NilmSignature(
                signature_id=f"{direction}-{index}",
                median_delta_w=median_w,
                median_delta_var=median_var,
                median_delta_va=median_va,
                median_delta_pf=median_pf,
                occurrence_count=len(cluster),
                confidence=confidence,
            )
        )

    return signatures


def classify_signature(signature: NilmSignature) -> str:
    """Return a deliberately non-definitive label for a recurring signature."""

    if signature.user_label:
        return signature.user_label

    abs_w = abs(signature.median_delta_w)
    abs_var = abs(signature.median_delta_var)
    abs_va = abs(signature.median_delta_va)
    reactive_ratio = abs_var / max(abs_w, 1.0)

    if abs_w >= 200 and reactive_ratio <= 0.12 and abs(signature.median_delta_pf) <= 0.08:
        return "possible resistive load"
    if abs_w >= 200 and reactive_ratio >= 0.3:
        return "possible motor-like load"
    if abs_va >= 100 and reactive_ratio >= 0.75:
        return "possible power-electronics load"
    return "unknown recurring load"


def unmatched_load_percentage(total_events: int, unmatched_events: int) -> float:
    """Return the share of events that remain unmatched."""

    if total_events <= 0:
        return 0.0
    return (unmatched_events / total_events) * 100.0


def _delta(current: float | None, previous: float | None) -> float:
    if current is None or previous is None:
        return 0.0
    return current - previous


def _event_power_w(event: CircuitEvent) -> float | None:
    preferred_keys = (
        "startup_power_w",
        "real_power_w",
        "stop_power_w",
        "power_w",
        "startup_power",
        "real_power",
        "stop_power",
        "power",
        "delta_w",
        "steady_power_w",
    )
    for key in preferred_keys:
        value = event.features.get(key)
        if value is not None:
            return abs(float(value))
    return None


def _edge_similar(edge: NilmEdge, reference: NilmEdge) -> bool:
    if edge.direction != reference.direction:
        return False
    return _within_ratio(edge.delta_w, reference.delta_w, 0.2) and _within_ratio(
        edge.delta_var, reference.delta_var, 0.35
    )


def _edge_similar_to_cluster(edge: NilmEdge, cluster: list[NilmEdge]) -> bool:
    reference = NilmEdge(
        timestamp=cluster[0].timestamp,
        delta_w=float(median(candidate.delta_w for candidate in cluster)),
        delta_var=float(median(candidate.delta_var for candidate in cluster)),
        delta_va=float(median(candidate.delta_va for candidate in cluster)),
        delta_pf=float(median(candidate.delta_pf for candidate in cluster)),
        direction=cluster[0].direction,
    )
    return _edge_similar(edge, reference) or any(
        _edge_similar(edge, candidate) for candidate in cluster
    )


def _within_ratio(value: float, reference: float, tolerance_ratio: float) -> bool:
    tolerance = max(abs(reference) * tolerance_ratio, 25.0)
    return abs(value - reference) <= tolerance
