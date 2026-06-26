from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median, multimode

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
    leg_a_delta_w: float | None = None
    leg_b_delta_w: float | None = None
    leg_balance_ratio: float | None = None
    dominant_leg: str = "unknown"
    split_phase_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class KnownLoadMatch:
    """NILM edge attributed to an already-known circuit event."""

    edge: NilmEdge
    known_circuit_id: str
    confidence: float
    known_power_w: float = 0.0


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
    median_leg_a_delta_w: float | None = None
    median_leg_b_delta_w: float | None = None
    leg_balance_ratio: float | None = None
    dominant_leg: str = "unknown"
    split_phase_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class NilmSession:
    """Probable appliance run reconstructed from compatible NILM edges."""

    session_id: str
    mains_circuit_id: str
    signature_fingerprint: str
    on_edge_id: str
    off_edge_id: str | None
    start: datetime
    end: datetime | None
    duration_seconds: float | None
    median_power_w: float
    estimated_energy_kwh: float
    confidence: float
    overlap_count: int = 0
    ambiguous: bool = False
    alternate_match_count: int = 0
    known_load_masked: bool = False
    known_load_confidence: float | None = None
    assignment_id: str | None = None


def nilm_signature_fingerprint(signature: NilmSignature) -> str:
    """Return a stable review key for a recurring NILM signature shape."""
    return "|".join(
        (
            f"direction={_signature_direction(signature.signature_id)}",
            f"watts={_abs_value_bucket(signature.median_delta_w, 100.0)}",
            f"var={_abs_value_bucket(signature.median_delta_var, 100.0)}",
            f"va={_abs_value_bucket(signature.median_delta_va, 100.0)}",
            f"pf={_abs_value_bucket(signature.median_delta_pf, 0.05)}",
            f"split={signature.split_phase_type or 'unknown'}",
            f"leg={signature.dominant_leg or 'unknown'}",
            f"balance={_optional_ratio_bucket(signature.leg_balance_ratio)}",
        )
    )


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

        leg_a_delta = _optional_delta(
            getattr(sample, "leg_a_real_power", None),
            getattr(previous, "leg_a_real_power", None),
        )
        leg_b_delta = _optional_delta(
            getattr(sample, "leg_b_real_power", None),
            getattr(previous, "leg_b_real_power", None),
        )
        topology = _split_phase_topology(leg_a_delta, leg_b_delta)

        return [
            NilmEdge(
                timestamp=sample.timestamp,
                delta_w=delta_w,
                delta_var=_delta(sample.reactive_power, previous.reactive_power),
                delta_va=_delta(sample.apparent_power, previous.apparent_power),
                delta_pf=_delta(sample.power_factor, previous.power_factor),
                direction="on" if delta_w > 0 else "off",
                leg_a_delta_w=_round_optional(leg_a_delta),
                leg_b_delta_w=_round_optional(leg_b_delta),
                leg_balance_ratio=topology["leg_balance_ratio"],
                dominant_leg=topology["dominant_leg"],
                split_phase_type=topology["split_phase_type"],
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
                    KnownLoadMatch(edge, event.circuit_id, confidence, known_watts),
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
        median_leg_a = _median_optional(
            candidate.leg_a_delta_w for candidate in cluster
        )
        median_leg_b = _median_optional(
            candidate.leg_b_delta_w for candidate in cluster
        )
        split_phase_type = _dominant_text(
            candidate.split_phase_type for candidate in cluster
        )
        dominant_leg = _dominant_text(candidate.dominant_leg for candidate in cluster)
        leg_balance_ratio = _median_optional(
            candidate.leg_balance_ratio for candidate in cluster
        )
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
                median_leg_a_delta_w=median_leg_a,
                median_leg_b_delta_w=median_leg_b,
                leg_balance_ratio=leg_balance_ratio,
                dominant_leg=dominant_leg,
                split_phase_type=split_phase_type,
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

    if (
        abs_w >= 200
        and reactive_ratio <= 0.12
        and abs(signature.median_delta_pf) <= 0.08
    ):
        return _split_phase_label(signature, "resistive load")
    if abs_w >= 200 and reactive_ratio >= 0.3:
        return _split_phase_label(signature, "motor-like load")
    if abs_va >= 100 and reactive_ratio >= 0.75:
        return _split_phase_label(signature, "power-electronics load")
    return "unknown recurring load"


def pair_nilm_sessions(
    edges: Iterable[NilmEdge],
    *,
    mains_circuit_id: str,
    signature_fingerprint: str,
    assignment_id: str | None = None,
    known_load_masked: bool = False,
    known_load_confidence: float | None = None,
    min_duration: timedelta = timedelta(seconds=1),
    max_duration: timedelta = timedelta(hours=12),
    min_confidence: float = 0.5,
) -> list[NilmSession]:
    """Pair compatible unmatched on/off NILM edges into probable sessions."""

    ordered_edges = sorted(edges, key=lambda edge: edge.timestamp)
    on_edges = [edge for edge in ordered_edges if edge.direction == "on"]
    off_edges = [edge for edge in ordered_edges if edge.direction == "off"]
    used_off_indices: set[int] = set()
    sessions: list[NilmSession] = []

    for on_edge in on_edges:
        candidates: list[tuple[float, datetime, int, NilmEdge]] = []
        for off_index, off_edge in enumerate(off_edges):
            if off_index in used_off_indices:
                continue
            score = _nilm_session_pair_score(
                on_edge,
                off_edge,
                min_duration=min_duration,
                max_duration=max_duration,
            )
            if score is None:
                continue
            candidates.append((score, off_edge.timestamp, off_index, off_edge))

        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
        if not candidates:
            sessions.append(
                _open_nilm_session(
                    on_edge,
                    mains_circuit_id=mains_circuit_id,
                    signature_fingerprint=signature_fingerprint,
                    assignment_id=assignment_id,
                    known_load_masked=known_load_masked,
                    known_load_confidence=known_load_confidence,
                )
            )
            continue

        best_score, _timestamp, off_index, off_edge = candidates[0]
        close_alternates = sum(
            1 for score, *_rest in candidates[1:] if best_score - score <= 0.08
        )
        confidence = best_score * (0.85 ** close_alternates)
        if known_load_masked:
            confidence *= _nilm_known_load_penalty(known_load_confidence)
        if confidence <= min_confidence:
            sessions.append(
                _open_nilm_session(
                    on_edge,
                    mains_circuit_id=mains_circuit_id,
                    signature_fingerprint=signature_fingerprint,
                    assignment_id=assignment_id,
                    known_load_masked=known_load_masked,
                    known_load_confidence=known_load_confidence,
                )
            )
            continue

        used_off_indices.add(off_index)
        sessions.append(
            _closed_nilm_session(
                on_edge,
                off_edge,
                mains_circuit_id=mains_circuit_id,
                signature_fingerprint=signature_fingerprint,
                confidence=confidence,
                assignment_id=assignment_id,
                ambiguous=close_alternates > 0,
                alternate_match_count=close_alternates,
                known_load_masked=known_load_masked,
                known_load_confidence=known_load_confidence,
            )
        )

    return [_with_nilm_session_overlap(session, sessions) for session in sessions]


def unmatched_load_percentage(total_events: int, unmatched_events: int) -> float:
    """Return the share of events that remain unmatched."""

    if total_events <= 0:
        return 0.0
    return (unmatched_events / total_events) * 100.0


def _delta(current: float | None, previous: float | None) -> float:
    if current is None or previous is None:
        return 0.0
    return current - previous


def _signature_direction(signature_id: str) -> str:
    direction = str(signature_id).split("-", 1)[0].strip().lower()
    return direction if direction in {"on", "off"} else "unknown"


def _abs_value_bucket(value: float, step: float) -> str:
    bucket_start = (abs(float(value)) // step) * step
    bucket_end = bucket_start + step
    if step >= 1.0:
        return f"{bucket_start:.0f}-{bucket_end:.0f}"
    return f"{bucket_start:.2f}-{bucket_end:.2f}"


def _optional_ratio_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    return _abs_value_bucket(value, 0.25)


def _optional_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


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
    if not _split_phase_types_compatible(edge, reference):
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
        split_phase_type=_dominant_text(
            candidate.split_phase_type for candidate in cluster
        ),
        dominant_leg=_dominant_text(candidate.dominant_leg for candidate in cluster),
    )
    return _edge_similar(edge, reference) or any(
        _edge_similar(edge, candidate) for candidate in cluster
    )


def _within_ratio(value: float, reference: float, tolerance_ratio: float) -> bool:
    tolerance = max(abs(reference) * tolerance_ratio, 25.0)
    return abs(value - reference) <= tolerance


def _split_phase_topology(
    leg_a_delta_w: float | None,
    leg_b_delta_w: float | None,
) -> dict[str, float | str | None]:
    if leg_a_delta_w is None and leg_b_delta_w is None:
        return _topology("unknown", "unknown", None)
    if leg_a_delta_w is None or leg_b_delta_w is None:
        return _topology("missing_leg_data", "unknown", None)

    abs_a = abs(float(leg_a_delta_w))
    abs_b = abs(float(leg_b_delta_w))
    balance_ratio = _leg_balance_ratio(abs_a, abs_b)
    dominant_leg = _dominant_leg(abs_a, abs_b, balance_ratio)
    leg_threshold_w = 50.0
    single_leg_ratio = 0.25

    if abs_a < leg_threshold_w and abs_b < leg_threshold_w:
        return _topology("unknown", "unknown", balance_ratio)
    if leg_a_delta_w * leg_b_delta_w < 0:
        return _topology("imbalanced_240v_or_mixed", "mixed", balance_ratio)
    if (
        abs_a >= leg_threshold_w
        and abs_b <= leg_threshold_w
        and abs_b <= abs_a * single_leg_ratio
    ):
        return _topology("single_leg_a", "a", balance_ratio)
    if (
        abs_b >= leg_threshold_w
        and abs_a <= leg_threshold_w
        and abs_a <= abs_b * single_leg_ratio
    ):
        return _topology("single_leg_b", "b", balance_ratio)
    if balance_ratio is not None and balance_ratio <= 0.25:
        return _topology("balanced_240v", "balanced", balance_ratio)
    return _topology("imbalanced_240v_or_mixed", dominant_leg, balance_ratio)


def _topology(
    split_phase_type: str,
    dominant_leg: str,
    leg_balance_ratio: float | None,
) -> dict[str, float | str | None]:
    return {
        "split_phase_type": split_phase_type,
        "dominant_leg": dominant_leg,
        "leg_balance_ratio": leg_balance_ratio,
    }


def _leg_balance_ratio(abs_a: float, abs_b: float) -> float | None:
    average = (abs_a + abs_b) / 2.0
    if average <= 0.0:
        return None
    return round(abs(abs_a - abs_b) / average, 3)


def _dominant_leg(
    abs_a: float,
    abs_b: float,
    balance_ratio: float | None,
) -> str:
    if balance_ratio is not None and balance_ratio <= 0.25:
        return "balanced"
    if abs_a > abs_b:
        return "a"
    if abs_b > abs_a:
        return "b"
    return "balanced"


def _median_optional(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return round(float(median(usable)), 3)


def _dominant_text(values: Iterable[str]) -> str:
    usable = [value for value in values if value and value != "unknown"]
    if not usable:
        return "unknown"
    return sorted(multimode(usable))[0]


def _split_phase_types_compatible(edge: NilmEdge, reference: NilmEdge) -> bool:
    edge_type = edge.split_phase_type
    reference_type = reference.split_phase_type
    if _uncertain_split_phase_type(edge_type) or _uncertain_split_phase_type(
        reference_type
    ):
        return _uncertain_split_phase_type(edge_type) and _uncertain_split_phase_type(
            reference_type
        )
    return edge_type == reference_type


def _uncertain_split_phase_type(value: str) -> bool:
    return value in {"unknown", "missing_leg_data"}


def _split_phase_label(signature: NilmSignature, label: str) -> str:
    if signature.split_phase_type == "balanced_240v":
        return f"possible 240 V {label}"
    if signature.split_phase_type in {"single_leg_a", "single_leg_b"}:
        return f"possible 120 V {label}"
    return f"possible {label}"


def _open_nilm_session(
    on_edge: NilmEdge,
    *,
    mains_circuit_id: str,
    signature_fingerprint: str,
    assignment_id: str | None,
    known_load_masked: bool,
    known_load_confidence: float | None,
) -> NilmSession:
    on_edge_id = _nilm_edge_id(on_edge)
    confidence = 0.35
    if known_load_masked:
        confidence *= _nilm_known_load_penalty(known_load_confidence)
    return NilmSession(
        session_id=_nilm_session_id(
            mains_circuit_id,
            signature_fingerprint,
            on_edge_id,
            None,
        ),
        mains_circuit_id=mains_circuit_id,
        signature_fingerprint=signature_fingerprint,
        on_edge_id=on_edge_id,
        off_edge_id=None,
        start=on_edge.timestamp,
        end=None,
        duration_seconds=None,
        median_power_w=round(abs(float(on_edge.delta_w)), 3),
        estimated_energy_kwh=0.0,
        confidence=round(confidence, 3),
        known_load_masked=known_load_masked,
        known_load_confidence=_nilm_known_load_confidence(
            known_load_masked,
            known_load_confidence,
        ),
        assignment_id=assignment_id,
    )


def _closed_nilm_session(
    on_edge: NilmEdge,
    off_edge: NilmEdge,
    *,
    mains_circuit_id: str,
    signature_fingerprint: str,
    confidence: float,
    assignment_id: str | None,
    ambiguous: bool,
    alternate_match_count: int,
    known_load_masked: bool,
    known_load_confidence: float | None,
) -> NilmSession:
    on_edge_id = _nilm_edge_id(on_edge)
    off_edge_id = _nilm_edge_id(off_edge)
    duration_seconds = max(
        0.0,
        (off_edge.timestamp - on_edge.timestamp).total_seconds(),
    )
    median_power_w = round(
        (abs(float(on_edge.delta_w)) + abs(float(off_edge.delta_w))) / 2.0,
        3,
    )
    return NilmSession(
        session_id=_nilm_session_id(
            mains_circuit_id,
            signature_fingerprint,
            on_edge_id,
            off_edge_id,
        ),
        mains_circuit_id=mains_circuit_id,
        signature_fingerprint=signature_fingerprint,
        on_edge_id=on_edge_id,
        off_edge_id=off_edge_id,
        start=on_edge.timestamp,
        end=off_edge.timestamp,
        duration_seconds=duration_seconds,
        median_power_w=median_power_w,
        estimated_energy_kwh=round(
            (median_power_w * duration_seconds) / 3_600_000.0,
            3,
        ),
        confidence=round(_clamp(confidence), 3),
        ambiguous=ambiguous,
        alternate_match_count=alternate_match_count,
        known_load_masked=known_load_masked,
        known_load_confidence=_nilm_known_load_confidence(
            known_load_masked,
            known_load_confidence,
        ),
        assignment_id=assignment_id,
    )


def _nilm_session_pair_score(
    on_edge: NilmEdge,
    off_edge: NilmEdge,
    *,
    min_duration: timedelta,
    max_duration: timedelta,
) -> float | None:
    if on_edge.direction != "on" or off_edge.direction != "off":
        return None
    duration = off_edge.timestamp - on_edge.timestamp
    if duration < min_duration or duration > max_duration:
        return None
    if not _nilm_pair_topology_compatible(on_edge, off_edge):
        return None

    watt_score = _nilm_magnitude_score(
        off_edge.delta_w,
        on_edge.delta_w,
        tolerance_ratio=0.25,
        floor=50.0,
    )
    if watt_score is None:
        return None

    scores = [watt_score]
    for value, reference, tolerance_ratio, floor in (
        (off_edge.delta_var, on_edge.delta_var, 0.5, 75.0),
        (off_edge.delta_va, on_edge.delta_va, 0.35, 75.0),
        (off_edge.delta_pf, on_edge.delta_pf, 0.5, 0.1),
    ):
        score = _nilm_optional_magnitude_score(
            value,
            reference,
            tolerance_ratio=tolerance_ratio,
            floor=floor,
        )
        if score is not None:
            scores.append(score)

    return _clamp(sum(scores) / len(scores))


def _nilm_pair_topology_compatible(on_edge: NilmEdge, off_edge: NilmEdge) -> bool:
    if not _split_phase_types_compatible(on_edge, off_edge):
        return False
    on_leg = on_edge.dominant_leg
    off_leg = off_edge.dominant_leg
    return (
        on_leg in {"unknown", "mixed"}
        or off_leg in {"unknown", "mixed"}
        or on_leg == off_leg
    )


def _nilm_magnitude_score(
    value: float,
    reference: float,
    *,
    tolerance_ratio: float,
    floor: float,
) -> float | None:
    tolerance = max(abs(float(reference)) * tolerance_ratio, floor)
    distance = abs(abs(float(value)) - abs(float(reference)))
    if distance > tolerance:
        return None
    return _clamp(1.0 - (distance / tolerance))


def _nilm_optional_magnitude_score(
    value: float,
    reference: float,
    *,
    tolerance_ratio: float,
    floor: float,
) -> float | None:
    if abs(float(value)) < floor and abs(float(reference)) < floor:
        return None
    return _nilm_magnitude_score(
        value,
        reference,
        tolerance_ratio=tolerance_ratio,
        floor=floor,
    )


def _with_nilm_session_overlap(
    session: NilmSession,
    sessions: list[NilmSession],
) -> NilmSession:
    latest_seen = max(candidate.end or candidate.start for candidate in sessions)
    overlap_count = sum(
        1
        for other in sessions
        if other is not session
        and _nilm_sessions_overlap(session, other, latest_seen=latest_seen)
    )
    if overlap_count == 0:
        return session
    return replace(
        session,
        overlap_count=overlap_count,
        confidence=round(_clamp(session.confidence * (0.9 ** overlap_count)), 3),
    )


def _nilm_sessions_overlap(
    left: NilmSession,
    right: NilmSession,
    *,
    latest_seen: datetime,
) -> bool:
    left_end = left.end or latest_seen
    right_end = right.end or latest_seen
    return left.start < right_end and right.start < left_end


def _nilm_known_load_penalty(known_load_confidence: float | None) -> float:
    confidence = _nilm_known_load_confidence(True, known_load_confidence)
    if confidence is None:
        return 0.85
    return _clamp(1.0 - (0.3 * confidence))


def _nilm_known_load_confidence(
    known_load_masked: bool,
    known_load_confidence: float | None,
) -> float | None:
    if not known_load_masked or known_load_confidence is None:
        return None
    return round(_clamp(known_load_confidence), 3)


def _nilm_edge_id(edge: NilmEdge) -> str:
    return "|".join(
        (
            edge.direction,
            edge.timestamp.isoformat(),
            f"w={edge.delta_w:.3f}",
            f"var={edge.delta_var:.3f}",
            edge.split_phase_type,
            edge.dominant_leg,
        )
    )


def _nilm_session_id(
    mains_circuit_id: str,
    signature_fingerprint: str,
    on_edge_id: str,
    off_edge_id: str | None,
) -> str:
    return "|".join(
        (
            str(mains_circuit_id),
            str(signature_fingerprint),
            on_edge_id,
            off_edge_id or "open",
        )
    )


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)
