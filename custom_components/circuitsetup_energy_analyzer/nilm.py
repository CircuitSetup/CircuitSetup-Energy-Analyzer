from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from statistics import median, multimode
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import CircuitEvent, CircuitSample, EventType


@dataclass(frozen=True, slots=True)
class NilmApplianceIdentity:
    """Stable logical identity for one NILM appliance assignment."""

    appliance_key: str
    assignment_id: str
    appliance_id: str
    display_name: str
    mains_circuit_id: str
    mains_source_entity_id: str | None
    appliance_profile: str


def build_nilm_appliance_identity(
    assignment: Mapping[str, Any],
    *,
    mains_source_entity_id: str | None = None,
) -> NilmApplianceIdentity:
    """Build an appliance identity without conflating it with its mains source."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if not assignment_id:
        raise ValueError("Missing assignment_id.")
    appliance_id = str(assignment.get("appliance_id") or assignment_id).strip()
    return NilmApplianceIdentity(
        appliance_key=f"nilm:{assignment_id}",
        assignment_id=assignment_id,
        appliance_id=appliance_id,
        display_name=str(
            assignment.get("display_name") or appliance_id or assignment_id
        ).strip(),
        mains_circuit_id=str(assignment.get("mains_circuit_id") or "").strip(),
        mains_source_entity_id=(
            str(mains_source_entity_id).strip() if mains_source_entity_id else None
        ),
        appliance_profile=str(
            assignment.get("appliance_profile") or "nilm_virtual"
        ).strip(),
    )


def nilm_appliance_detail_path(identity: NilmApplianceIdentity) -> str:
    """Return the appliance-scoped detail route for a NILM identity."""
    return "/circuitsetup-energy-analyzer-evidence?" + urlencode(
        {
            "circuit_id": identity.mains_circuit_id,
            "assignment_id": identity.assignment_id,
            "nilm_workspace": "1",
            "appliance_detail": "1",
        }
    )


def build_nilm_appliance_alert_payload(
    identity: NilmApplianceIdentity,
    *,
    session_id: str | None = None,
    signature_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Return explicit appliance target, mains source, and evidence context."""
    return {
        "primary_target": identity.appliance_key,
        "source_context": {
            "mains_circuit_id": identity.mains_circuit_id,
            "mains_source_entity_id": identity.mains_source_entity_id,
        },
        "evidence_context": {
            "assignment_id": identity.assignment_id,
            "session_id": session_id,
            "signature_fingerprint": signature_fingerprint,
        },
        "appliance_detail_path": nilm_appliance_detail_path(identity),
    }


def summarize_nilm_assignment_sessions(
    assignment: Mapping[str, Any],
    sessions: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Summarize only the sessions owned by one NILM assignment."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    assigned_session_ids = {
        str(value).strip()
        for value in _nilm_list(assignment.get("session_ids"))
        if str(value).strip()
    }
    rejected_session_ids = {
        str(value).strip()
        for value in _nilm_list(assignment.get("rejected_session_ids"))
        if str(value).strip()
    }
    owned_sessions = [
        dict(session)
        for session in sessions
        if _nilm_session_owned_by_assignment(
            session,
            assignment_id=assignment_id,
            assigned_session_ids=assigned_session_ids,
        )
    ]
    zone = _nilm_zone(time_zone)
    local_today = _nilm_aware(now).astimezone(zone).date()
    day_start = datetime.combine(local_today, time.min, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    runtime_today = 0.0
    energy_today = 0.0
    run_count_today = 0
    open_session: Mapping[str, Any] | None = None
    latest_session: Mapping[str, Any] | None = None
    latest_seen: datetime | None = None
    for session in owned_sessions:
        if str(session.get("session_id") or "").strip() in rejected_session_ids:
            continue
        start = _nilm_datetime(session.get("start"))
        if start is None:
            continue
        end = _nilm_datetime(session.get("end"))
        if end is not None and (latest_seen is None or end > latest_seen):
            latest_seen = end
            latest_session = session
        if end is None:
            current_open_start = (
                _nilm_datetime(open_session.get("start"))
                if open_session is not None
                else None
            )
            if current_open_start is None or start > current_open_start:
                open_session = session
        session_end = end or now
        overlap_start = max(start, day_start)
        overlap_end = min(session_end, day_end)
        if overlap_end <= overlap_start:
            continue
        if start.astimezone(zone).date() == local_today:
            run_count_today += 1
        overlap_duration = max(
            0.0,
            (
                overlap_end.astimezone(UTC) - overlap_start.astimezone(UTC)
            ).total_seconds(),
        )
        runtime_today += overlap_duration
        total_duration = max(
            0.0,
            (
                session_end.astimezone(UTC) - start.astimezone(UTC)
            ).total_seconds(),
        )
        session_energy = max(
            _nilm_number(session.get("estimated_energy_kwh")) or 0.0,
            0.0,
        )
        if end is None and session_energy == 0.0:
            session_energy = (
                max(_nilm_number(session.get("median_power_w")) or 0.0, 0.0)
                * total_duration
                / 3_600_000.0
            )
        if total_duration > 0:
            energy_today += session_energy * (overlap_duration / total_duration)
    current_duration = None
    if open_session is not None:
        open_start = _nilm_datetime(open_session.get("start"))
        if open_start is not None:
            current_duration = max(
                0.0,
                (
                    now.astimezone(UTC) - open_start.astimezone(UTC)
                ).total_seconds(),
            )
    return {
        "sessions": owned_sessions,
        "runtime_today_seconds": round(runtime_today, 3),
        "run_count_today": run_count_today,
        "estimated_energy_today_kwh": round(energy_today, 3),
        "current_session_duration_seconds": (
            round(current_duration, 3) if current_duration is not None else None
        ),
        "current_session_id": (
            str(open_session.get("session_id") or "") or None
            if open_session is not None
            else None
        ),
        "last_matched_session_id": (
            str(latest_session.get("session_id") or "") or None
            if latest_session is not None
            else None
        ),
    }


def evaluate_nilm_validation_readiness(
    assignment: Mapping[str, Any],
    sessions: Iterable[Mapping[str, Any]],
    *,
    min_confirmed_sessions: int = 5,
    min_distinct_days: int = 3,
    max_false_positive_rate: float = 0.2,
    min_confidence: float = 0.75,
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Gate NILM comparisons until all validation thresholds are met."""
    confirmed_ids = {
        str(value).strip()
        for value in _nilm_list(assignment.get("confirmed_session_ids"))
        if str(value).strip()
    }
    rejected_ids = {
        str(value).strip()
        for value in _nilm_list(assignment.get("rejected_session_ids"))
        if str(value).strip()
    }
    zone = _nilm_zone(time_zone)
    confirmed_days = {
        start.astimezone(zone).date()
        for session in sessions
        if str(session.get("session_id") or "").strip() in confirmed_ids
        and (start := _nilm_datetime(session.get("start"))) is not None
    }
    validation_total = len(confirmed_ids) + len(rejected_ids)
    stored_false_positive_rate = _nilm_number(
        assignment.get("false_positive_rate")
    )
    false_positive_rate = (
        stored_false_positive_rate
        if stored_false_positive_rate is not None
        else len(rejected_ids) / validation_total
        if validation_total
        else 0.0
    )
    confidence = _nilm_number(assignment.get("confidence")) or 0.0
    ready = (
        len(confirmed_ids) >= max(min_confirmed_sessions, 0)
        and len(confirmed_days) >= max(min_distinct_days, 0)
        and false_positive_rate <= max_false_positive_rate
        and confidence >= min_confidence
    )
    return {
        "ready": ready,
        "today_vs_normal_enabled": ready,
        "status": "ready" if ready else "needs_validation",
        "confirmed_sessions": len(confirmed_ids),
        "distinct_confirmed_days": len(confirmed_days),
        "false_positive_rate": round(false_positive_rate, 3),
        "confidence": round(confidence, 3),
    }


def plan_nilm_direct_meter_conversion(
    identity: NilmApplianceIdentity,
    assignment: Mapping[str, Any],
    *,
    direct_circuit_id: str,
    keep_assignment_for_masking: bool = True,
) -> dict[str, Any]:
    """Build a lossless conversion plan while disabling duplicate estimates."""
    direct_id = str(direct_circuit_id or "").strip()
    if not direct_id:
        raise ValueError("Missing direct_circuit_id.")
    return {
        "appliance_key": identity.appliance_key,
        "assignment_id": identity.assignment_id,
        "direct_circuit_id": direct_id,
        "display_name": identity.display_name,
        "appliance_profile": identity.appliance_profile,
        "confirmed_session_ids": list(
            _nilm_list(assignment.get("confirmed_session_ids"))
        ),
        "rejected_session_ids": list(
            _nilm_list(assignment.get("rejected_session_ids"))
        ),
        "adjusted_session_ids": list(
            _nilm_list(assignment.get("adjusted_session_ids"))
        ),
        "publish_estimated_entities": False,
        "keep_assignment_for_masking": bool(keep_assignment_for_masking),
    }


def _nilm_session_owned_by_assignment(
    session: Mapping[str, Any],
    *,
    assignment_id: str,
    assigned_session_ids: set[str],
) -> bool:
    session_id = str(session.get("session_id") or "").strip()
    owner = str(session.get("assignment_id") or "").strip()
    if owner:
        return owner == assignment_id
    return bool(session_id and session_id in assigned_session_ids)


def _nilm_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _nilm_aware(value)
    try:
        return _nilm_aware(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def _nilm_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo("UTC"))


def _nilm_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or "UTC"))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _nilm_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nilm_list(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, list | tuple | set) else ()


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


def nilm_session_to_dict(session: NilmSession) -> dict[str, Any]:
    """Return compact, storage-safe NILM session metadata."""
    return {
        "session_id": session.session_id,
        "mains_circuit_id": session.mains_circuit_id,
        "signature_fingerprint": session.signature_fingerprint,
        "on_edge_id": session.on_edge_id,
        "off_edge_id": session.off_edge_id,
        "start": session.start.isoformat(),
        "end": session.end.isoformat() if session.end is not None else None,
        "duration_seconds": session.duration_seconds,
        "median_power_w": session.median_power_w,
        "estimated_energy_kwh": session.estimated_energy_kwh,
        "confidence": session.confidence,
        "overlap_count": session.overlap_count,
        "ambiguous": session.ambiguous,
        "alternate_match_count": session.alternate_match_count,
        "known_load_masked": session.known_load_masked,
        "known_load_confidence": session.known_load_confidence,
        "assignment_id": session.assignment_id,
    }


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

    def __init__(
        self,
        min_delta_w: float = 100.0,
        *,
        confirmation_samples: int = 1,
        confirmation_tolerance_ratio: float = 0.15,
        confirmation_max_interval: timedelta | None = None,
    ) -> None:
        self.min_delta_w = min_delta_w
        self.confirmation_samples = max(int(confirmation_samples), 1)
        self.confirmation_tolerance_ratio = max(
            float(confirmation_tolerance_ratio),
            0.0,
        )
        self.confirmation_max_interval = confirmation_max_interval
        self._previous: CircuitSample | None = None
        self._pending: tuple[CircuitSample, CircuitSample, int] | None = None

    def process(self, sample: CircuitSample) -> list[NilmEdge]:
        if sample.real_power is None:
            self._previous = None
            self._pending = None
            return []

        if self._previous is None or self._previous.real_power is None:
            self._previous = sample
            return []

        previous = self._previous
        self._previous = sample

        if self.confirmation_samples > 1:
            return self._process_confirmed(previous, sample)

        edge = self._edge_between(previous, sample)
        return [edge] if edge is not None else []

    def _process_confirmed(
        self,
        previous: CircuitSample,
        sample: CircuitSample,
    ) -> list[NilmEdge]:
        if (
            self.confirmation_max_interval is not None
            and sample.timestamp - previous.timestamp > self.confirmation_max_interval
        ):
            self._pending = None
            edge = self._edge_between(previous, sample)
            return [edge] if edge is not None else []
        pending = self._pending
        if pending is not None:
            baseline, candidate, count = pending
            if self._same_level(sample, candidate, baseline):
                count += 1
                if count >= self.confirmation_samples:
                    self._pending = None
                    edge = self._edge_between(baseline, candidate)
                    return [edge] if edge is not None else []
                self._pending = (baseline, candidate, count)
                return []
            if self._same_level(sample, baseline, baseline):
                self._pending = None
                return []
            previous = baseline

        if (
            abs(float(sample.real_power) - float(previous.real_power))
            >= self.min_delta_w
        ):
            self._pending = (previous, sample, 1)
        else:
            self._pending = None
        return []

    def _same_level(
        self,
        sample: CircuitSample,
        reference: CircuitSample,
        baseline: CircuitSample,
    ) -> bool:
        transition = abs(float(reference.real_power) - float(baseline.real_power))
        tolerance = max(
            self.min_delta_w * 0.5,
            transition * self.confirmation_tolerance_ratio,
        )
        return abs(float(sample.real_power) - float(reference.real_power)) <= tolerance

    def _edge_between(
        self,
        previous: CircuitSample,
        sample: CircuitSample,
    ) -> NilmEdge | None:
        delta_w = float(sample.real_power) - float(previous.real_power)
        if abs(delta_w) < self.min_delta_w:
            return None

        leg_a_delta = _optional_delta(
            getattr(sample, "leg_a_real_power", None),
            getattr(previous, "leg_a_real_power", None),
        )
        leg_b_delta = _optional_delta(
            getattr(sample, "leg_b_real_power", None),
            getattr(previous, "leg_b_real_power", None),
        )
        topology = _split_phase_topology(leg_a_delta, leg_b_delta)

        return NilmEdge(
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

    for on_position, on_edge in enumerate(on_edges):
        next_on = next(
            (
                later_on.timestamp
                for later_on in on_edges[on_position + 1 :]
                if _nilm_magnitude_score(
                    later_on.delta_w,
                    on_edge.delta_w,
                    tolerance_ratio=0.25,
                    floor=50.0,
                )
                is not None
            ),
            None,
        )
        candidates: list[tuple[float, datetime, int, NilmEdge]] = []
        for off_index, off_edge in enumerate(off_edges):
            if off_index in used_off_indices:
                continue
            if next_on is not None and off_edge.timestamp > next_on:
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


@dataclass(frozen=True, slots=True)
class _NilmSessionCandidate:
    on_index: int
    off_index: int
    on_edge: NilmEdge
    off_edge: NilmEdge
    signature_fingerprint: str
    assignment_id: str | None
    score: float


def pair_nilm_sessions_for_signatures(
    edges: Iterable[NilmEdge],
    *,
    mains_circuit_id: str,
    signature_specs: Iterable[Mapping[str, Any]],
    min_duration: timedelta = timedelta(seconds=30),
    max_duration: timedelta = timedelta(hours=12),
    min_confidence: float = 0.5,
    ambiguity_margin: float = 0.08,
) -> list[NilmSession]:
    """Pair NILM sessions once across all competing signatures."""

    specs = [
        spec
        for spec in signature_specs
        if _nilm_session_spec_fingerprint(spec)
        and str(spec.get("direction") or "").lower() != "off"
        and (
            _nilm_number(spec.get("median_delta_w")) is None
            or float(spec["median_delta_w"]) >= 0
        )
    ]
    if not specs:
        return []

    ordered_edges = sorted(edges, key=lambda edge: edge.timestamp)
    on_edges = [edge for edge in ordered_edges if edge.direction == "on"]
    off_edges = [edge for edge in ordered_edges if edge.direction == "off"]
    candidates: list[_NilmSessionCandidate] = []
    for on_index, on_edge in enumerate(on_edges):
        next_on = next(
            (
                later_on.timestamp
                for later_on in on_edges[on_index + 1 :]
                if _nilm_magnitude_score(
                    later_on.delta_w,
                    on_edge.delta_w,
                    tolerance_ratio=0.25,
                    floor=50.0,
                )
                is not None
            ),
            None,
        )
        for off_index, off_edge in enumerate(off_edges):
            if next_on is not None and off_edge.timestamp > next_on:
                continue
            for spec in specs:
                spec_min_duration = _nilm_session_spec_duration(
                    spec,
                    "min_duration_seconds",
                    min_duration,
                )
                spec_max_duration = _nilm_session_spec_duration(
                    spec,
                    "max_duration_seconds",
                    max_duration,
                )
                pair_score = _nilm_session_pair_score(
                    on_edge,
                    off_edge,
                    min_duration=spec_min_duration,
                    max_duration=spec_max_duration,
                )
                signature_score = _nilm_signature_pair_score(on_edge, off_edge, spec)
                if pair_score is None or signature_score is None:
                    continue
                score = _clamp((pair_score + (2.0 * signature_score)) / 3.0)
                if score <= min_confidence:
                    continue
                candidates.append(
                    _NilmSessionCandidate(
                        on_index=on_index,
                        off_index=off_index,
                        on_edge=on_edge,
                        off_edge=off_edge,
                        signature_fingerprint=_nilm_session_spec_fingerprint(spec),
                        assignment_id=_nilm_session_spec_assignment_id(spec),
                        score=score,
                    )
                )

    ambiguous_pairs: set[tuple[int, int]] = set()
    by_pair: dict[tuple[int, int], list[_NilmSessionCandidate]] = {}
    for candidate in candidates:
        by_pair.setdefault((candidate.on_index, candidate.off_index), []).append(
            candidate
        )
    for pair, pair_candidates in by_pair.items():
        ranked = sorted(pair_candidates, key=lambda item: -item.score)
        if (
            len(ranked) > 1
            and ranked[0].signature_fingerprint != ranked[1].signature_fingerprint
            and ranked[0].score - ranked[1].score <= ambiguity_margin
        ):
            ambiguous_pairs.add(pair)

    used_on_indices: set[int] = set()
    used_off_indices: set[int] = set()
    sessions: list[NilmSession] = []
    # ponytail: greedy global assignment is intentionally bounded; replace it with
    # maximum-weight matching only if labelled replay data shows a measurable gap.
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -item.score,
            item.off_edge.timestamp,
            item.on_edge.timestamp,
            item.signature_fingerprint,
        ),
    ):
        if (candidate.on_index, candidate.off_index) in ambiguous_pairs:
            continue
        if (
            candidate.on_index in used_on_indices
            or candidate.off_index in used_off_indices
        ):
            continue
        used_on_indices.add(candidate.on_index)
        used_off_indices.add(candidate.off_index)
        sessions.append(
            _closed_nilm_session(
                candidate.on_edge,
                candidate.off_edge,
                mains_circuit_id=mains_circuit_id,
                signature_fingerprint=candidate.signature_fingerprint,
                confidence=candidate.score,
                assignment_id=candidate.assignment_id,
                ambiguous=False,
                alternate_match_count=0,
                known_load_masked=False,
                known_load_confidence=None,
            )
        )

    for on_index, on_edge in enumerate(on_edges):
        if on_index in used_on_indices or _nilm_on_edge_has_compatible_off(
            on_edge,
            off_edges,
            max_duration=max_duration,
        ):
            continue
        ranked_specs = sorted(
            (
                (score, spec)
                for spec in specs
                if (score := _nilm_signature_edge_score(on_edge, spec)) is not None
                and score > min_confidence
            ),
            key=lambda item: (
                -item[0],
                _nilm_session_spec_fingerprint(item[1]),
            ),
        )
        if not ranked_specs:
            continue
        if (
            len(ranked_specs) > 1
            and ranked_specs[0][0] - ranked_specs[1][0] <= ambiguity_margin
        ):
            continue
        spec = ranked_specs[0][1]
        sessions.append(
            _open_nilm_session(
                on_edge,
                mains_circuit_id=mains_circuit_id,
                signature_fingerprint=_nilm_session_spec_fingerprint(spec),
                assignment_id=_nilm_session_spec_assignment_id(spec),
                known_load_masked=False,
                known_load_confidence=None,
            )
        )

    ordered_sessions = sorted(sessions, key=lambda session: session.start)
    return [
        _with_nilm_session_overlap(session, ordered_sessions)
        for session in ordered_sessions
    ]


def _nilm_session_spec_fingerprint(spec: Mapping[str, Any]) -> str:
    return str(
        spec.get("signature_fingerprint")
        or spec.get("feedback_fingerprint")
        or spec.get("signature_id")
        or ""
    ).strip()


def _nilm_session_spec_assignment_id(spec: Mapping[str, Any]) -> str | None:
    return str(spec.get("assignment_id") or "").strip() or None


def _nilm_session_spec_duration(
    spec: Mapping[str, Any],
    key: str,
    default: timedelta,
) -> timedelta:
    seconds = _nilm_number(spec.get(key))
    if seconds is None or seconds <= 0:
        return default
    return timedelta(seconds=seconds)


def _nilm_signature_pair_score(
    on_edge: NilmEdge,
    off_edge: NilmEdge,
    spec: Mapping[str, Any],
) -> float | None:
    on_score = _nilm_signature_edge_score(on_edge, spec)
    off_score = _nilm_signature_edge_score(off_edge, spec)
    if on_score is None or off_score is None:
        return None
    return (on_score + off_score) / 2.0


def _nilm_signature_edge_score(
    edge: NilmEdge,
    spec: Mapping[str, Any],
) -> float | None:
    scores: list[float] = []
    expected_watts = _nilm_number(
        spec.get("typical_watts")
        if spec.get("typical_watts") is not None
        else spec.get("median_delta_w")
    )
    if expected_watts is not None and abs(expected_watts) > 0:
        score = _nilm_magnitude_score(
            edge.delta_w,
            expected_watts,
            tolerance_ratio=0.25,
            floor=50.0,
        )
        if score is None:
            return None
        scores.append(score)

    for field, edge_value, tolerance_ratio, floor in (
        ("median_delta_var", edge.delta_var, 0.5, 75.0),
        ("median_delta_va", edge.delta_va, 0.35, 75.0),
        ("median_delta_pf", edge.delta_pf, 0.5, 0.1),
    ):
        expected = _nilm_number(spec.get(field))
        if expected is None:
            continue
        score = _nilm_optional_magnitude_score(
            edge_value,
            expected,
            tolerance_ratio=tolerance_ratio,
            floor=floor,
        )
        if score is None and (
            abs(float(edge_value)) >= floor or abs(expected) >= floor
        ):
            return None
        if score is not None:
            scores.append(score)

    expected_type = str(spec.get("split_phase_type") or "").strip()
    if expected_type not in {"", "unknown", "mixed", "missing_leg_data"}:
        edge_type = str(edge.split_phase_type or "").strip()
        if edge_type not in {"", "unknown", "mixed", "missing_leg_data"}:
            if expected_type != edge_type:
                return None
            scores.append(1.0)

    expected_leg = str(spec.get("dominant_leg") or "").strip()
    if expected_leg not in {"", "unknown", "mixed"}:
        edge_leg = str(edge.dominant_leg or "").strip()
        if edge_leg not in {"", "unknown", "mixed"}:
            if expected_leg != edge_leg:
                return None
            scores.append(1.0)

    return sum(scores) / len(scores) if scores else 1.0


def _nilm_on_edge_has_compatible_off(
    on_edge: NilmEdge,
    off_edges: Iterable[NilmEdge],
    *,
    max_duration: timedelta,
) -> bool:
    return any(
        _nilm_session_pair_score(
            on_edge,
            off_edge,
            min_duration=timedelta(seconds=1),
            max_duration=max_duration,
        )
        is not None
        for off_edge in off_edges
    )


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
        if score is None and (
            abs(float(value)) >= floor or abs(float(reference)) >= floor
        ):
            return None
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
