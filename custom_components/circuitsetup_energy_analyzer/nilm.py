from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from itertools import combinations
from math import isfinite
from statistics import median, multimode
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import CircuitEvent, CircuitSample, EventType


def build_nilm_assignment_model(
    assignment: Mapping[str, Any],
    sessions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one assignment's transition model from reviewed complete sessions."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    confirmed = {
        str(value or "").strip()
        for value in assignment.get("confirmed_session_ids", ())
        if str(value or "").strip()
    }
    rejected = {
        str(value or "").strip()
        for value in assignment.get("rejected_session_ids", ())
        if str(value or "").strip()
    }
    eligible = []
    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        owner = str(session.get("assignment_id") or "").strip()
        on_delta, off_delta = _session_transition_values(session)
        if (
            session_id in confirmed
            and session_id not in rejected
            and (not owner or owner == assignment_id)
            and session.get("end") is not None
            and session.get("ambiguous") is not True
            and on_delta is not None
            and on_delta > 0
            and off_delta is not None
            and off_delta < 0
        ):
            eligible.append((session, on_delta, off_delta))
    eligible.sort(
        key=lambda item: str(item[0].get("end") or item[0].get("start") or ""),
        reverse=True,
    )
    eligible = eligible[:32]
    on_values = [item[1] for item in eligible]
    off_values = [item[2] for item in eligible]
    confidences = [
        value
        if (value := _model_number(session.get("confidence"))) is not None
        else 0.0
        for session, _, _ in eligible
    ]
    normalized = normalize_nilm_assignment_model(assignment)
    model: dict[str, Any] = {
        "role": normalized["role"],
        "power_states_w": [],
        "transition_prototypes": [],
        "model_confidence": 0.0,
        "model_revision": normalized["model_revision"],
    }
    if not on_values or not off_values:
        return model
    on_median = median(on_values)
    off_median = median(off_values)
    active_state = round(max(on_median, abs(off_median)), 3)
    model["power_states_w"] = [0.0, active_state]
    model["transition_prototypes"] = [
        _transition_prototype("on", 0.0, active_state, on_median, on_values),
        _transition_prototype("off", active_state, 0.0, off_median, off_values),
    ]
    model["model_confidence"] = round(
        min(max(median(confidences) if confidences else 0.0, 0.0), 1.0)
        * min(len(eligible) / 3, 1),
        3,
    )
    previous = {
        "power_states_w": normalized["power_states_w"],
        "transition_prototypes": normalized["transition_prototypes"],
    }
    current = {
        "power_states_w": model["power_states_w"],
        "transition_prototypes": model["transition_prototypes"],
    }
    if current != previous:
        model["model_revision"] += 1
    return model


def normalize_nilm_assignment_model(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional persisted assignment model fields conservatively."""
    role = assignment.get("role")
    states = assignment.get("power_states_w")
    confidence = _model_number(assignment.get("model_confidence"))
    valid_states = (
        [_model_number(value) for value in states]
        if isinstance(states, list)
        else []
    )
    prototypes = []
    stored_prototypes = assignment.get("transition_prototypes")
    for item in stored_prototypes if isinstance(stored_prototypes, list) else ():
        if not isinstance(item, Mapping) or item.get("direction") not in {"on", "off"}:
            continue
        values = [
            _model_number(item.get(key))
            for key in ("from_state_w", "to_state_w", "delta_w", "spread_w")
        ]
        if any(value is None for value in values):
            continue
        prototypes.append({
            "direction": item["direction"], "from_state_w": values[0],
            "to_state_w": values[1], "delta_w": values[2],
            "spread_w": max(values[3], 0.0),
            "sample_count": _model_nonnegative_int(item.get("sample_count")),
        })
    return {
        "role": role.strip() if isinstance(role, str) and role.strip() else "component",
        "power_states_w": (
            valid_states if all(value is not None for value in valid_states) else []
        ),
        "transition_prototypes": prototypes,
        "model_confidence": min(max(confidence or 0.0, 0.0), 1.0),
        "model_revision": _model_nonnegative_int(assignment.get("model_revision")),
    }


def nilm_assignment_model_is_compound_eligible(
    assignment: Mapping[str, Any],
) -> bool:
    """Return whether both directions are learned and confidence is sufficient."""
    prototypes = assignment.get("transition_prototypes")
    if not isinstance(prototypes, list):
        return False
    learned = {
        str(item.get("direction") or "")
        for item in prototypes
        if isinstance(item, Mapping)
        and _model_nonnegative_int(item.get("sample_count")) >= 3
    }
    confidence = _model_number(assignment.get("model_confidence"))
    return learned == {"on", "off"} and confidence is not None and confidence >= 0.70


def _transition_prototype(
    direction: str,
    from_state_w: float,
    to_state_w: float,
    delta_w: float,
    values: list[float],
) -> dict[str, Any]:
    center = median(values)
    return {
        "direction": direction,
        "from_state_w": round(from_state_w, 3),
        "to_state_w": round(to_state_w, 3),
        "delta_w": round(delta_w, 3),
        "spread_w": round(median(abs(value - center) for value in values), 3),
        "sample_count": len(values),
    }


def _model_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _model_nonnegative_int(value: Any) -> int:
    number = _model_number(value)
    return int(number) if number is not None and number >= 0 else 0


def _session_transition_values(
    session: Mapping[str, Any],
) -> tuple[float | None, float | None]:
    legacy = _model_number(session.get("median_power_w"))
    return (
        _model_number(session.get("on_delta_w")) if "on_delta_w" in session else legacy,
        _model_number(session.get("off_delta_w"))
        if "off_delta_w" in session
        else -abs(legacy) if legacy is not None else None,
    )


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
            (session_end.astimezone(UTC) - start.astimezone(UTC)).total_seconds(),
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
                (now.astimezone(UTC) - open_start.astimezone(UTC)).total_seconds(),
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
    stored_false_positive_rate = _nilm_number(assignment.get("false_positive_rate"))
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


class NilmComponentStatus(StrEnum):
    """Runtime state confidence for one reconciled component."""

    UNKNOWN = "unknown"
    OFF = "off"
    ON = "on"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class NilmTransitionPrototype:
    """Learned transition between two assignment power states."""

    assignment_id: str
    direction: str
    from_state_w: float
    to_state_w: float
    delta_w: float
    spread_w: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class NilmAssignmentModel:
    """Bounded transition model for one NILM assignment."""

    assignment_id: str
    power_states_w: tuple[float, ...]
    transition_prototypes: tuple[NilmTransitionPrototype, ...]
    model_confidence: float
    lifecycle_state: str
    last_observed: datetime | None


@dataclass(frozen=True, slots=True)
class NilmReconciliationResult:
    """Pure result of matching one source edge to assignment transitions."""

    accepted: bool
    transitions: tuple[NilmTransitionPrototype, ...]
    residual_w: float
    tolerance_w: float
    compound: bool
    consistent: bool
    energy_allocation_allowed: bool
    reason: str


def nilm_transition_tolerance_w(prototype: NilmTransitionPrototype) -> float:
    """Return the learned real-power tolerance for a transition."""
    return max(15.0, 3.0 * prototype.spread_w, 0.20 * abs(prototype.delta_w))


def conservation_tolerance_w(source_power_w: float, noise_spread_w: float) -> float:
    """Return the permitted source/component conservation error."""
    return max(25.0, 3.0 * noise_spread_w, 0.10 * abs(source_power_w))


def score_nilm_transition(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
    *,
    helper_score: float | None,
    duration_state_score: float | None,
    validation_score: float | None,
    optional_electrical_fit: float | None = None,
) -> float:
    """Score a transition, omitting and renormalizing unavailable evidence."""
    tolerance = nilm_transition_tolerance_w(prototype)
    real_fit = max(0.0, 1.0 - abs(edge.delta_w - prototype.delta_w) / tolerance)
    electrical_fit = real_fit
    if optional_electrical_fit is not None and isfinite(optional_electrical_fit):
        electrical_fit = 0.70 * real_fit + 0.30 * _nilm_unit(optional_electrical_fit)
    terms = [(0.55, electrical_fit)]
    terms.extend(
        (weight, _nilm_unit(value))
        for weight, value in (
            (0.25, helper_score),
            (0.10, duration_state_score),
            (0.10, validation_score),
        )
        if value is not None and isfinite(value)
    )
    return sum(weight * value for weight, value in terms) / sum(
        weight for weight, _ in terms
    )


def reconcile_nilm_edge(
    edge: NilmEdge,
    models: Iterable[NilmAssignmentModel],
    current_states_w: Mapping[str, float | None],
    helper_scores: Mapping[str, float | None],
    duration_state_scores: Mapping[str, float | None],
    validation_scores: Mapping[str, float | None],
    *,
    helper_conflict: bool = False,
) -> NilmReconciliationResult:
    """Match one edge to at most two legal assignment transitions."""
    models = tuple(models)
    legal = [
        (model, prototype)
        for model in models
        for prototype in model.transition_prototypes
        if _nilm_transition_legal(model, prototype, current_states_w)
    ]
    if helper_conflict:
        return _nilm_reconciliation(edge, (), reason="helper_conflict")

    singles = sorted(
        [
            (
                _nilm_candidate_score(
                    edge,
                    prototype,
                    helper_scores,
                    duration_state_scores,
                    validation_scores,
                ),
                prototype,
            )
            for _, prototype in legal
            if abs(edge.delta_w - prototype.delta_w)
            <= nilm_transition_tolerance_w(prototype)
        ],
        key=lambda item: item[0],
        reverse=True,
    )
    if singles and singles[0][0] >= 0.70:
        if len(singles) == 1 or singles[0][0] - singles[1][0] >= 0.15:
            return _nilm_reconciliation(edge, (singles[0][1],), reason="single")
        single_reason = "ambiguous"
    else:
        single_reason = "below_threshold"

    recent_ids = {
        model.assignment_id
        for model in sorted(
            (
                model
                for model in models
                if model.lifecycle_state.strip().lower() != "retired"
            ),
            key=lambda item: (
                -_nilm_aware(item.last_observed).timestamp()
                if item.last_observed is not None
                else float("inf"),
                item.assignment_id,
            ),
        )[:20]
    }
    per_assignment: dict[str, NilmTransitionPrototype] = {}
    for model, prototype in legal:
        if (
            model.assignment_id in recent_ids
            and model.lifecycle_state.strip().lower() != "retired"
            and prototype.sample_count >= 3
            and model.model_confidence >= 0.70
        ):
            previous = per_assignment.get(model.assignment_id)
            if previous is None or _nilm_transition_choice_key(
                edge, prototype
            ) < _nilm_transition_choice_key(edge, previous):
                per_assignment[model.assignment_id] = prototype
    best_single_residual = min(
        (abs(edge.delta_w - prototype.delta_w) for _, prototype in legal),
        default=abs(edge.delta_w),
    )
    pairs: list[tuple[float, tuple[NilmTransitionPrototype, ...]]] = []
    ordered_transitions = tuple(
        per_assignment[assignment_id] for assignment_id in sorted(per_assignment)
    )
    for first, second in combinations(ordered_transitions, 2):
        combined = _nilm_combined_transition(first, second)
        residual = abs(edge.delta_w - combined.delta_w)
        if residual > nilm_transition_tolerance_w(combined):
            continue
        improvement = (
            1.0
            if best_single_residual == 0.0 and residual == 0.0
            else (best_single_residual - residual) / best_single_residual
            if best_single_residual
            else 0.0
        )
        score = _nilm_candidate_score(
            edge,
            combined,
            {
                combined.assignment_id: _nilm_mean_available(
                    helper_scores, first, second
                )
            },
            {
                combined.assignment_id: _nilm_mean_available(
                    duration_state_scores, first, second
                )
            },
            {
                combined.assignment_id: _nilm_mean_available(
                    validation_scores, first, second
                )
            },
        )
        if score >= 0.75 and improvement >= 0.30:
            pairs.append((score, (first, second)))
    pairs.sort(reverse=True, key=lambda item: item[0])
    if pairs and (len(pairs) == 1 or pairs[0][0] - pairs[1][0] >= 0.15):
        return _nilm_reconciliation(edge, pairs[0][1], reason="compound")
    if len(per_assignment) > 2 and _nilm_multi_transition_matches(
        edge, ordered_transitions
    ):
        return _nilm_reconciliation(edge, (), reason="compound_unknown")
    return _nilm_reconciliation(
        edge,
        (),
        reason="ambiguous" if pairs or single_reason == "ambiguous" else single_reason,
    )


def _nilm_unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _nilm_transition_legal(
    model: NilmAssignmentModel,
    prototype: NilmTransitionPrototype,
    current_states_w: Mapping[str, float | None],
) -> bool:
    lifecycle = model.lifecycle_state.strip().lower()
    if lifecycle in {"hidden", "ignored", "expected", "rejected", "converted"}:
        return False
    current = current_states_w.get(model.assignment_id)
    if current is None or not isfinite(current):
        return False
    if lifecycle == "retired" and not (prototype.direction == "off" and current):
        return False
    if prototype.direction != ("on" if prototype.delta_w > 0 else "off"):
        return False
    if not all(
        any(abs(state - expected) <= 1e-6 for state in model.power_states_w)
        for expected in (prototype.from_state_w, prototype.to_state_w)
    ):
        return False
    return abs(current - prototype.from_state_w) <= 1e-6


def _nilm_transition_choice_key(
    edge: NilmEdge, prototype: NilmTransitionPrototype
) -> tuple[float, str, float, float, float, float, int]:
    return (
        abs(edge.delta_w - prototype.delta_w),
        prototype.direction,
        prototype.from_state_w,
        prototype.to_state_w,
        prototype.delta_w,
        prototype.spread_w,
        prototype.sample_count,
    )


def _nilm_candidate_score(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
    helpers: Mapping[str, float | None],
    durations: Mapping[str, float | None],
    validations: Mapping[str, float | None],
) -> float:
    return score_nilm_transition(
        edge,
        prototype,
        helper_score=helpers.get(prototype.assignment_id),
        duration_state_score=durations.get(prototype.assignment_id),
        validation_score=validations.get(prototype.assignment_id),
    )


def _nilm_combined_transition(
    first: NilmTransitionPrototype, second: NilmTransitionPrototype
) -> NilmTransitionPrototype:
    return NilmTransitionPrototype(
        assignment_id=f"{first.assignment_id}+{second.assignment_id}",
        direction="on" if first.delta_w + second.delta_w > 0 else "off",
        from_state_w=first.from_state_w + second.from_state_w,
        to_state_w=first.to_state_w + second.to_state_w,
        delta_w=first.delta_w + second.delta_w,
        spread_w=first.spread_w + second.spread_w,
        sample_count=min(first.sample_count, second.sample_count),
    )


def _nilm_mean_available(
    scores: Mapping[str, float | None],
    first: NilmTransitionPrototype,
    second: NilmTransitionPrototype,
) -> float | None:
    values = [
        value
        for assignment_id in (first.assignment_id, second.assignment_id)
        if (value := scores.get(assignment_id)) is not None and isfinite(value)
    ]
    return sum(values) / len(values) if values else None


def _nilm_multi_transition_matches(
    edge: NilmEdge, transitions: Iterable[NilmTransitionPrototype]
) -> bool:
    transitions = tuple(transitions)
    return any(
        abs(edge.delta_w - sum(item.delta_w for item in group))
        <= max(15.0, 0.20 * abs(edge.delta_w))
        for group in combinations(transitions, 3)
    )


def _nilm_reconciliation(
    edge: NilmEdge,
    transitions: tuple[NilmTransitionPrototype, ...],
    *,
    reason: str,
) -> NilmReconciliationResult:
    residual = edge.delta_w - sum(item.delta_w for item in transitions)
    tolerance = (
        nilm_transition_tolerance_w(
            transitions[0]
            if len(transitions) == 1
            else _nilm_combined_transition(*transitions)
        )
        if transitions
        else conservation_tolerance_w(edge.delta_w, 0.0)
    )
    accepted = bool(transitions)
    consistent = abs(residual) <= tolerance
    if accepted and not consistent:
        reason = "conservation_conflict"
        accepted = False
    return NilmReconciliationResult(
        accepted=accepted,
        transitions=transitions if accepted else (),
        residual_w=residual,
        tolerance_w=tolerance,
        compound=len(transitions) == 2 and accepted,
        consistent=consistent,
        energy_allocation_allowed=accepted and consistent,
        reason=reason,
    )


class NilmHelperRelationship(StrEnum):
    """How a circuit's events may support a NILM load."""

    CORROBORATES = "corroborates"
    DIRECT_COMPONENT = "direct_component"


@dataclass(frozen=True, slots=True)
class NilmHelperCandidate:
    """Bounded evidence that a circuit tracks NILM transitions."""

    helper_circuit_id: str
    matched_on_count: int
    matched_off_count: int
    unmatched_source_count: int
    unmatched_helper_count: int
    source_event_count: int
    helper_event_count: int
    source_coverage: float
    start_coverage: float
    stop_coverage: float
    helper_precision: float
    start_lag_seconds: float | None
    stop_lag_seconds: float | None
    start_lag_mad_seconds: float | None
    stop_lag_mad_seconds: float | None
    confidence: float
    last_observed: datetime | None


def score_nilm_helper_candidate(
    source_coverage: float,
    helper_precision: float,
    lag_mad_seconds: float,
) -> float:
    """Score helper evidence from coverage, precision, and timing stability."""
    stability = 1.0 - min(max(float(lag_mad_seconds), 0.0) / 120.0, 1.0)
    return (0.45 * source_coverage) + (0.35 * helper_precision) + (0.20 * stability)


def discover_nilm_helper_candidates(
    source_edges: Iterable[NilmEdge],
    helper_events_by_circuit: Mapping[str, Iterable[CircuitEvent]],
    *,
    max_lag: timedelta = timedelta(minutes=10),
) -> tuple[NilmHelperCandidate, ...]:
    """Return the eight strongest same-direction circuit-event matches."""
    source_edges = tuple(source_edges)
    source_by_type = {
        EventType.START: tuple(edge for edge in source_edges if edge.direction == "on"),
        EventType.STOP: tuple(edge for edge in source_edges if edge.direction == "off"),
    }
    source_event_count = sum(len(edges) for edges in source_by_type.values())
    candidates: list[NilmHelperCandidate] = []
    for circuit_id, iterable in helper_events_by_circuit.items():
        helper_events = tuple(
            event
            for event in iterable
            if event.event_type in {EventType.START, EventType.STOP}
        )
        matched_by_type = {
            event_type: _pair_nilm_helper_events(
                source_by_type[event_type],
                tuple(
                    event for event in helper_events if event.event_type == event_type
                ),
                max_lag=max_lag,
            )
            for event_type in (EventType.START, EventType.STOP)
        }
        matched_on = matched_by_type[EventType.START]
        matched_off = matched_by_type[EventType.STOP]
        matched_count = len(matched_on) + len(matched_off)
        helper_event_count = len(helper_events)
        start_lags = [lag for _, _, lag in matched_on]
        stop_lags = [lag for _, _, lag in matched_off]
        start_lag = _median_or_none(start_lags)
        stop_lag = _median_or_none(stop_lags)
        start_mad = _lag_mad(start_lags, start_lag)
        stop_mad = _lag_mad(stop_lags, stop_lag)
        source_coverage = (
            matched_count / source_event_count if source_event_count else 0.0
        )
        helper_precision = (
            matched_count / helper_event_count if helper_event_count else 0.0
        )
        sufficient_matches = len(matched_on) >= 3 and len(matched_off) >= 3
        lag_mad = _median_or_none(
            value for value in (start_mad, stop_mad) if value is not None
        )
        confidence = (
            score_nilm_helper_candidate(
                source_coverage, helper_precision, lag_mad or 0.0
            )
            if sufficient_matches
            else 0.0
        )
        observed = [
            timestamp
            for edge, event, _ in (*matched_on, *matched_off)
            for timestamp in (edge.timestamp, event.timestamp)
        ]
        candidates.append(
            NilmHelperCandidate(
                helper_circuit_id=str(circuit_id),
                matched_on_count=len(matched_on),
                matched_off_count=len(matched_off),
                unmatched_source_count=source_event_count - matched_count,
                unmatched_helper_count=helper_event_count - matched_count,
                source_event_count=source_event_count,
                helper_event_count=helper_event_count,
                source_coverage=source_coverage,
                start_coverage=(
                    len(matched_on) / len(source_by_type[EventType.START])
                    if source_by_type[EventType.START]
                    else 0.0
                ),
                stop_coverage=(
                    len(matched_off) / len(source_by_type[EventType.STOP])
                    if source_by_type[EventType.STOP]
                    else 0.0
                ),
                helper_precision=helper_precision,
                start_lag_seconds=start_lag,
                stop_lag_seconds=stop_lag,
                start_lag_mad_seconds=start_mad,
                stop_lag_mad_seconds=stop_mad,
                confidence=confidence,
                last_observed=max(observed) if observed else None,
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.confidence,
                -(
                    candidate.last_observed or datetime.min.replace(tzinfo=UTC)
                ).timestamp(),
                candidate.helper_circuit_id,
            ),
        )[:8]
    )


def nilm_helper_candidate_to_dict(candidate: NilmHelperCandidate) -> dict[str, Any]:
    """Return compact helper evidence with an explicit suggestion gate."""
    return {
        field: getattr(candidate, field) for field in candidate.__dataclass_fields__
    } | {
        "last_observed": (
            candidate.last_observed.isoformat() if candidate.last_observed else None
        ),
        "suggested": (
            candidate.matched_on_count >= 3
            and candidate.matched_off_count >= 3
            and candidate.confidence >= 0.75
        ),
    }


def _pair_nilm_helper_events(
    edges: tuple[NilmEdge, ...],
    events: tuple[CircuitEvent, ...],
    *,
    max_lag: timedelta,
) -> tuple[tuple[NilmEdge, CircuitEvent, float], ...]:
    candidates = sorted(
        (
            (
                abs((event.timestamp - edge.timestamp).total_seconds()),
                edge_index,
                event_index,
            )
            for edge_index, edge in enumerate(edges)
            for event_index, event in enumerate(events)
            if abs(event.timestamp - edge.timestamp) <= max_lag
        ),
    )
    used_edges: set[int] = set()
    used_events: set[int] = set()
    matches: list[tuple[NilmEdge, CircuitEvent, float]] = []
    for _, edge_index, event_index in candidates:
        if edge_index in used_edges or event_index in used_events:
            continue
        edge, event = edges[edge_index], events[event_index]
        matches.append(
            (edge, event, (event.timestamp - edge.timestamp).total_seconds())
        )
        used_edges.add(edge_index)
        used_events.add(event_index)
    return tuple(matches)


def _median_or_none(values: Iterable[float]) -> float | None:
    values = tuple(values)
    return float(median(values)) if values else None


def _lag_mad(values: Iterable[float], center: float | None) -> float | None:
    values = tuple(values)
    if not values or center is None:
        return None
    return float(median(abs(value - center) for value in values))


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
    on_delta_w: float | None = None
    off_delta_w: float | None = None


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
        "on_delta_w": session.on_delta_w,
        "off_delta_w": session.off_delta_w,
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
        self._stable_changes_w: deque[float] = deque(maxlen=64)

    @property
    def has_pending_transition(self) -> bool:
        """Return whether a transition still needs confirmation."""
        return self._pending is not None

    @property
    def noise_spread_w(self) -> float:
        """Return the MAD of the last 64 changes that were below threshold."""
        if not self._stable_changes_w:
            return 0.0
        center = median(self._stable_changes_w)
        return float(median(abs(value - center) for value in self._stable_changes_w))

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
        change_w = float(sample.real_power) - float(previous.real_power)
        if abs(change_w) < self.min_delta_w:
            self._stable_changes_w.append(change_w)

        if self.confirmation_samples > 1:
            return self._process_confirmed(previous, sample)

        edge = self._edge_between(previous, sample)
        return [edge] if edge is not None else []

    def _process_confirmed(
        self,
        previous: CircuitSample,
        sample: CircuitSample,
    ) -> list[NilmEdge]:
        pending = self._pending
        if (
            self.confirmation_max_interval is not None
            and sample.timestamp - previous.timestamp > self.confirmation_max_interval
        ):
            self._pending = None
            if pending is not None:
                baseline, candidate, _count = pending
                if self._same_level(sample, candidate, baseline):
                    edge = self._edge_between(baseline, candidate)
                    return [edge] if edge is not None else []
                if self._same_level(sample, baseline, baseline):
                    return []
            edge = self._edge_between(previous, sample)
            return [edge] if edge is not None else []
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
        tolerance = transition * self.confirmation_tolerance_ratio
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
        and (
            _nilm_session_spec_assignment_id(spec)
            or (
                str(spec.get("direction") or "").lower() != "off"
                and (
                    _nilm_number(spec.get("median_delta_w")) is None
                    or float(spec["median_delta_w"]) >= 0
                )
            )
        )
    ]
    if not specs:
        return []

    ordered_edges = sorted(edges, key=lambda edge: edge.timestamp)
    on_edges = [edge for edge in ordered_edges if edge.direction == "on"]
    off_edges = [edge for edge in ordered_edges if edge.direction == "off"]
    candidates: list[_NilmSessionCandidate] = []
    for on_index, on_edge in enumerate(on_edges):
        for off_index, off_edge in enumerate(off_edges):
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
    preferred_candidates: dict[tuple[int, int], _NilmSessionCandidate] = {}
    by_pair: dict[tuple[int, int], list[_NilmSessionCandidate]] = {}
    for candidate in candidates:
        by_pair.setdefault((candidate.on_index, candidate.off_index), []).append(
            candidate
        )
    for pair, pair_candidates in by_pair.items():
        ranked = sorted(pair_candidates, key=lambda item: -item.score)
        assigned: dict[str, _NilmSessionCandidate] = {}
        for candidate in ranked:
            if (
                candidate.assignment_id
                and ranked[0].score - candidate.score <= ambiguity_margin
            ):
                assigned.setdefault(candidate.assignment_id, candidate)
        if len(assigned) == 1 and ranked[0].assignment_id:
            preferred_candidates[pair] = next(iter(assigned.values()))
            continue
        if len(assigned) > 1:
            ambiguous_pairs.add(pair)
            preferred_candidates[pair] = ranked[0]
            continue
        if (
            len(ranked) > 1
            and ranked[0].signature_fingerprint != ranked[1].signature_fingerprint
            and ranked[0].score - ranked[1].score <= ambiguity_margin
        ):
            ambiguous_pairs.add(pair)
        preferred_candidates.setdefault(pair, ranked[0])

    used_on_indices: set[int] = set()
    used_off_indices: set[int] = set()
    force_open_on_indices: set[int] = set()
    sessions: list[NilmSession] = []
    eligible_candidates = list(preferred_candidates.values())
    # ponytail: greedy global assignment is intentionally bounded; replace it with
    # maximum-weight matching only if labelled replay data shows a measurable gap.
    for candidate in sorted(
        eligible_candidates,
        key=lambda item: (
            -item.score,
            item.off_edge.timestamp,
            item.on_edge.timestamp,
            item.signature_fingerprint,
        ),
    ):
        if candidate.on_index in force_open_on_indices:
            continue
        if (
            candidate.on_index in used_on_indices
            or candidate.off_index in used_off_indices
        ):
            continue
        close_alternates = [
            alternate
            for alternate in eligible_candidates
            if alternate.on_index == candidate.on_index
            and alternate.off_index != candidate.off_index
            and alternate.off_index not in used_off_indices
            and candidate.score - alternate.score <= ambiguity_margin
        ]
        alternate_off_indices = {alternate.off_index for alternate in close_alternates}
        pair = (candidate.on_index, candidate.off_index)
        pair_ambiguous = pair in ambiguous_pairs
        alternate_match_count = len(alternate_off_indices) + (
            len(by_pair[pair]) - 1 if pair_ambiguous else 0
        )
        assignment_ids = {None if pair_ambiguous else candidate.assignment_id}
        assignment_ids.update(
            None
            if (alternate.on_index, alternate.off_index) in ambiguous_pairs
            else alternate.assignment_id
            for alternate in close_alternates
        )
        assignment_id = next(iter(assignment_ids)) if len(assignment_ids) == 1 else None
        confidence = candidate.score * (0.85 ** len(alternate_off_indices))
        if confidence <= min_confidence:
            force_open_on_indices.add(candidate.on_index)
            continue
        used_on_indices.add(candidate.on_index)
        used_off_indices.add(candidate.off_index)
        sessions.append(
            _closed_nilm_session(
                candidate.on_edge,
                candidate.off_edge,
                mains_circuit_id=mains_circuit_id,
                signature_fingerprint=candidate.signature_fingerprint,
                confidence=confidence,
                assignment_id=assignment_id,
                ambiguous=pair_ambiguous or bool(alternate_off_indices),
                alternate_match_count=alternate_match_count,
                known_load_masked=False,
                known_load_confidence=None,
            )
        )

    for on_index, on_edge in enumerate(on_edges):
        if on_index in used_on_indices:
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
        assigned_specs: dict[str, tuple[float, Mapping[str, Any]]] = {}
        for match in ranked_specs:
            assignment_id = _nilm_session_spec_assignment_id(match[1])
            if assignment_id and ranked_specs[0][0] - match[0] <= ambiguity_margin:
                assigned_specs.setdefault(assignment_id, match)
        if len(assigned_specs) == 1 and _nilm_session_spec_assignment_id(
            ranked_specs[0][1]
        ):
            ranked_specs = [next(iter(assigned_specs.values()))]
        if (
            len(ranked_specs) > 1
            and ranked_specs[0][0] - ranked_specs[1][0] <= ambiguity_margin
        ):
            sessions.append(
                _open_nilm_session(
                    on_edge,
                    mains_circuit_id=mains_circuit_id,
                    signature_fingerprint=_nilm_session_spec_fingerprint(
                        ranked_specs[0][1]
                    ),
                    assignment_id=None,
                    known_load_masked=False,
                    known_load_confidence=None,
                    ambiguous=True,
                    alternate_match_count=sum(
                        1
                        for score, _spec in ranked_specs[1:]
                        if ranked_specs[0][0] - score <= ambiguity_margin
                    ),
                )
            )
            continue
        spec = ranked_specs[0][1]
        assignment_id = _nilm_session_spec_assignment_id(spec)
        fingerprint = _nilm_session_spec_fingerprint(spec)
        candidate_eligible_off = any(
            candidate.on_index == on_index
            and candidate.off_index not in used_off_indices
            and (
                candidate.assignment_id == assignment_id
                if assignment_id
                else candidate.signature_fingerprint == fingerprint
            )
            for candidate in candidates
        )
        spec_min_duration = _nilm_session_spec_duration(
            spec,
            "min_duration_seconds",
            min_duration,
        )
        too_early_off = any(
            off_index not in used_off_indices
            and _nilm_session_pair_score(
                on_edge,
                off_edge,
                min_duration=timedelta(seconds=1),
                max_duration=spec_min_duration,
            )
            is not None
            and _nilm_signature_pair_score(on_edge, off_edge, spec) is not None
            for off_index, off_edge in enumerate(off_edges)
        )
        if on_index not in force_open_on_indices and (
            candidate_eligible_off or too_early_off
        ):
            continue
        sessions.append(
            _open_nilm_session(
                on_edge,
                mains_circuit_id=mains_circuit_id,
                signature_fingerprint=fingerprint,
                assignment_id=assignment_id,
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
    ambiguous: bool = False,
    alternate_match_count: int = 0,
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
        ambiguous=ambiguous,
        alternate_match_count=alternate_match_count,
        known_load_masked=known_load_masked,
        known_load_confidence=_nilm_known_load_confidence(
            known_load_masked,
            known_load_confidence,
        ),
        assignment_id=assignment_id,
        on_delta_w=round(float(on_edge.delta_w), 3),
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
        on_delta_w=round(float(on_edge.delta_w), 3),
        off_delta_w=round(float(off_edge.delta_w), 3),
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
        confidence=round(_clamp(session.confidence * (0.9**overlap_count)), 3),
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
