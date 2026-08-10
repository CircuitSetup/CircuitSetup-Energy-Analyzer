from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from itertools import combinations
from math import isclose, isfinite, log
from statistics import median
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .metric_consistency import evaluate_metric_consistency
from .models import (
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    CircuitSample,
    EventType,
    SensorRole,
)
from .nilm_interval_evidence import DEFAULT_THRESHOLDS

_LEGACY_INTERVAL_CONFIDENCE_CAP = 0.25
_MAX_POSITIVE_EVIDENCE = 96
_MAX_EVIDENCE_PER_DAY = 4
_MAX_EVIDENCE_PER_SOURCE = 64
_LEGACY_STOP_WEIGHT = 0.35
_ESTIMATED_ENERGY_WEIGHT = 0.5
_EDGE_DERIVED_PLATEAU_WEIGHT = 0.35
_TRANSITION_ONLY_CONFIDENCE_CAP = 0.65
_SOURCE_TRUST = {"session": 1.0, "interval": 0.85, "legacy_interval": 0.45}
_CONFIDENCE_CAP = 0.95
_POWER_ENERGY_DISAGREEMENT_RATIO = 0.35
_NILM_MAX_SCORE_BREAKDOWNS = 5
_NILM_MAX_ACTIVE_STATES = 3
_NILM_STATE_SPLIT_MIN_EFFECTIVE_SUPPORT = 8.0
_NILM_STATE_MIN_EFFECTIVE_SUPPORT = 3.0
_NILM_STATE_MIN_DISTINCT_DAYS = 2
_NILM_STATE_MIN_DISPERSION_REDUCTION = 0.30
NILM_DURATION_MIN_EFFECTIVE_SUPPORT = 5.0
NILM_DURATION_MIN_DISTINCT_DAYS = 3
NILM_DURATION_MAX_CENTRAL_RATIO = 100.0
NILM_DURATION_MIN_LOG_TAPER = log(2.0)
NILM_VALIDATION_MIN_OUTCOMES = 5
NILM_VALIDATION_MIN_DISTINCT_DAYS = 3
NILM_VALIDATION_PRIOR_CORRECT = 2.0
NILM_VALIDATION_PRIOR_WRONG = 2.0
NILM_VALIDATION_MAX_REPLAY_WINDOW = timedelta(days=31)


@dataclass(frozen=True, slots=True)
class _NormalizedAssignmentEvidence:
    """One normalized, assignment-owned evidence record."""

    evidence_id: str
    source_type: str
    timestamp: datetime | None
    local_day: str
    positive: bool
    on_delta_w: float | None
    off_delta_w: float | None
    plateau_w: float | None
    plateau_source: str | None
    duration_s: float | None
    energy_kwh: float | None
    energy_source: str | None
    quality: float
    inferred_stop: bool = False
    issues: tuple[str, ...] = ()
    on_delta_var: float | None = None
    off_delta_var: float | None = None


def build_nilm_assignment_model(
    assignment: Mapping[str, Any],
    sessions: Iterable[Mapping[str, Any]],
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a deterministic schema-v2 binary model and legacy projection."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    confirmed = _assignment_ids(assignment, "confirmed_session_ids")
    rejected = _assignment_ids(assignment, "rejected_session_ids")
    records = [
        record
        for session in sessions
        if (
            record := _normalize_session_evidence(
                session, assignment_id, confirmed, rejected
            )
        )
        is not None
    ]
    interval_ids = _assignment_ids(assignment, "label_interval_ids")
    records.extend(
        record
        for interval in label_intervals
        if (
            record := _normalize_interval_evidence(
                interval, assignment_id, interval_ids
            )
        )
        is not None
    )
    observed_modern_on = any(
        record.positive
        and record.source_type != "legacy_interval"
        and record.on_delta_w is not None
        for record in records
    )
    observed_modern_off = any(
        record.positive
        and record.source_type != "legacy_interval"
        and record.off_delta_w is not None
        for record in records
    )
    if observed_modern_on or observed_modern_off:
        records = [
            replace(
                record,
                on_delta_w=None if observed_modern_on else record.on_delta_w,
                off_delta_w=None if observed_modern_off else record.off_delta_w,
            )
            if record.source_type == "legacy_interval"
            else record
            for record in records
        ]
    positives = _select_positive_evidence(
        record for record in records if record.positive
    )
    negatives = [record for record in records if not record.positive]
    normalized = normalize_nilm_assignment_model(assignment)
    model = _empty_assignment_model(normalized)
    if not positives:
        model["evidence_summary"]["negative_count"] = len(negatives)
        if not negatives and not any(
            key in assignment
            for key in (
                "confirmed_session_ids",
                "rejected_session_ids",
                "label_interval_ids",
            )
        ):
            return model
        return _finalize_assignment_model(model, normalized)
    on = [record for record in positives if record.on_delta_w is not None]
    off = [record for record in positives if record.off_delta_w is not None]
    plateau = [record for record in positives if record.plateau_w is not None]
    weighted_plateau = _weighted_plateau_records(plateau)
    power_source = "plateau"
    if plateau:
        active_power = _weighted_median(
            [record.plateau_w for record in weighted_plateau], weighted_plateau
        )
        if not any(record.plateau_source == "trace" for record in plateau):
            power_source = "edge_derived_plateau"
    else:
        energy_power = [
            record
            for record in positives
            if record.energy_kwh is not None
            and record.duration_s
            and record.duration_s > 0
        ]
        if energy_power:
            active_power = _weighted_median(
                [
                    record.energy_kwh * 3_600_000 / record.duration_s
                    for record in energy_power
                ],
                energy_power,
            )
            power_source = "energy_mean"
        else:
            active_power = max(
                _weighted_median([record.on_delta_w for record in on], on)
                if on
                else 0.0,
                abs(_weighted_median([record.off_delta_w for record in off], off))
                if off
                else 0.0,
            )
            power_source = "transition_fallback"
    active_power = round(active_power, 3)
    learned_states = _learn_nilm_active_states(weighted_plateau)
    model_kind = "binary"
    if learned_states is not None and len(learned_states) > 1:
        model_kind = "multi_state"
    elif learned_states is None and plateau:
        model_kind = "variable_envelope"
    state_powers = learned_states or [active_power]
    model["model_kind"] = model_kind
    model["power_states_w"] = [0.0, *state_powers]
    model["states"] = [
        {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
        *[
            {
                "id": (f"active_{index}" if model_kind == "multi_state" else "running"),
                "kind": ("active" if model_kind == "multi_state" else "running"),
                "power_w": power,
                "spread_w": round(
                    _weighted_mad([record.plateau_w for record in members], members),
                    3,
                )
                if members
                else 0.0,
                "power_source": power_source,
            }
            for index, (power, members) in enumerate(
                _state_members(state_powers, weighted_plateau), 1
            )
        ],
    ]
    if model_kind == "variable_envelope":
        model["active_power_envelope_w"] = _profile(
            [record.plateau_w for record in weighted_plateau], weighted_plateau
        )
    for index, (power, members) in enumerate(
        _state_members(state_powers, weighted_plateau), 1
    ):
        state_id = f"active_{index}" if model_kind == "multi_state" else "running"
        member_ids = {record.evidence_id for record in members}
        state_on = [
            record
            for record in on
            if record.evidence_id in member_ids
            or (
                record.plateau_w is None
                and abs(record.on_delta_w - power) <= max(15.0, power * 0.20)
            )
        ]
        state_off = [
            record
            for record in off
            if record.evidence_id in member_ids
            or (
                record.plateau_w is None
                and abs(abs(record.off_delta_w) - power) <= max(15.0, power * 0.20)
            )
        ]
        if not plateau:
            state_on, state_off = on, off
        if state_on:
            model["transition_prototypes"].append(
                _rich_transition_prototype(
                    assignment_id,
                    "on",
                    0.0,
                    power,
                    state_on,
                    from_state_id="off",
                    to_state_id=state_id,
                )
            )
        if state_off:
            model["transition_prototypes"].append(
                _rich_transition_prototype(
                    assignment_id,
                    "off",
                    power,
                    0.0,
                    state_off,
                    from_state_id=state_id,
                    to_state_id="off",
                )
            )
    profile_records = [
        record for record in positives if record.duration_s and record.duration_s > 0
    ]
    model["run_profile"] = {
        "plateau_w": _profile(
            [record.plateau_w for record in weighted_plateau], weighted_plateau
        ),
        "duration_s": _duration_profile(profile_records),
        "energy_kwh": {},
    }
    energy_records = [
        record for record in profile_records if record.energy_kwh is not None
    ]
    model["run_profile"]["energy_kwh"] = _energy_profile(energy_records)
    model["run_profile"]["plateau_w"]["source_counts"] = _count_values(
        record.plateau_source for record in plateau
    )
    state_dwell_profiles = _build_nilm_state_dwell_profiles(
        sessions,
        positives,
        assignment_id,
        {state["id"] for state in model["states"] if state["id"] != "off"},
    )
    if state_dwell_profiles:
        model["state_dwell_profiles"] = state_dwell_profiles
    conflicts = _close_rejected_conflicts(negatives, on, off)
    issues = sorted({issue for record in positives for issue in record.issues})
    state_support = min(_weighted_support(weighted_plateau) / 3, 1.0)
    confidence = _evidence_confidence(
        positives, on, off, conflicts, state_support=state_support
    )
    model["evidence_confidence"] = confidence
    model["model_confidence"] = confidence
    model["evidence_summary"] = {
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "positive_distinct_days": _distinct_days(positives),
        "effective_support": round(_effective_support(positives), 3),
        "state_support": round(state_support, 3),
        "source_counts": _count_values(record.source_type for record in positives),
        "inferred_stop_count": sum(
            record.inferred_stop and record.off_delta_w is not None
            for record in positives
        ),
        "close_rejected_conflicts": conflicts,
        "quality_issues": issues,
    }
    return _finalize_assignment_model(model, normalized)


def _build_nilm_state_dwell_profiles(
    sessions: Iterable[Mapping[str, Any]],
    records: list[_NormalizedAssignmentEvidence],
    assignment_id: str,
    active_state_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Build bounded state-dwell profiles from completed, normalized sessions."""
    record_by_id = {
        record.evidence_id: record
        for record in records
        if record.source_type == "session"
    }
    dwell_records: defaultdict[str, list[_NormalizedAssignmentEvidence]] = defaultdict(
        list
    )
    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        record = record_by_id.get(session_id)
        if record is None or str(session.get("assignment_id") or "").strip() not in {
            "",
            assignment_id,
        }:
            continue
        if _nilm_datetime(session.get("end")) is None:
            continue
        path = session.get("state_path")
        dwell = session.get("state_dwell_seconds")
        if not isinstance(path, list) or not isinstance(dwell, Mapping):
            continue
        path_ids = {
            str(item.get("state_id") or "").strip()
            for item in path
            if isinstance(item, Mapping)
        }
        for raw_state_id, raw_seconds in dwell.items():
            state_id = str(raw_state_id or "").strip()
            seconds = _positive_number(raw_seconds)
            if (
                not state_id
                or state_id not in active_state_ids
                or state_id not in path_ids
                or seconds is None
            ):
                continue
            dwell_records[state_id].append(replace(record, duration_s=seconds))
    return {
        state_id: _duration_profile(state_records)
        for state_id, state_records in sorted(dwell_records.items())
        if state_records
    }


def _finalize_assignment_model(
    model: dict[str, Any], normalized: Mapping[str, Any]
) -> dict[str, Any]:
    model["model_fingerprint"] = _model_fingerprint(model)
    previous = {
        key: normalized.get(key)
        for key in ("power_states_w", "transition_prototypes", "model_fingerprint")
    }
    current = {key: model.get(key) for key in previous}
    previous["transition_prototypes"] = sorted(
        previous["transition_prototypes"],
        key=lambda item: (item["direction"], item.get("id", "")),
    )
    current["transition_prototypes"] = sorted(
        current["transition_prototypes"],
        key=lambda item: (item["direction"], item.get("id", "")),
    )
    if current != previous:
        model["model_revision"] += 1
    return model


def _assignment_ids(assignment: Mapping[str, Any], key: str) -> set[str]:
    return {
        str(value or "").strip()
        for value in assignment.get(key, ())
        if str(value or "").strip()
    }


def _normalize_session_evidence(
    session: Mapping[str, Any],
    assignment_id: str,
    confirmed: set[str],
    rejected: set[str],
) -> _NormalizedAssignmentEvidence | None:
    evidence_id = str(session.get("session_id") or "").strip()
    owner = str(session.get("assignment_id") or "").strip()
    if (
        not evidence_id
        or (owner and owner != assignment_id)
        or evidence_id not in confirmed | rejected
    ):
        return None
    on, off = _session_transition_values(session)
    on = on if on is not None and on > 0 else None
    off = off if off is not None and off < 0 else None
    plateau = _positive_number(session.get("median_power_w"))
    duration = _duration_seconds(session)
    measured_energy = _positive_number(session.get("measured_energy_kwh"))
    estimated_energy = (
        _positive_number(session.get("estimated_energy_kwh"))
        if measured_energy is None and on is not None and off is not None and duration
        else None
    )
    energy = measured_energy or estimated_energy
    energy_source = (
        "measured"
        if measured_energy is not None
        else "estimated"
        if estimated_energy is not None
        else None
    )
    if not any((on, off, plateau, energy)):
        return None
    record = _evidence_record(
        evidence_id,
        "session",
        session,
        evidence_id in confirmed and evidence_id not in rejected,
        on,
        off,
        plateau,
        "edge_derived" if plateau is not None else None,
        duration,
        energy,
        energy_source,
        _quality(session),
        False,
    )
    return replace(
        record,
        on_delta_var=_session_edge_metric(
            session, value_key="on_delta_var", edge_id_key="on_edge_id", metric="var"
        ),
        off_delta_var=_session_edge_metric(
            session, value_key="off_delta_var", edge_id_key="off_edge_id", metric="var"
        ),
    )


def _normalize_interval_evidence(
    interval: Mapping[str, Any], assignment_id: str, interval_ids: set[str]
) -> _NormalizedAssignmentEvidence | None:
    evidence_id = str(interval.get("interval_id") or "").strip()
    owner = str(interval.get("assignment_id") or "").strip()
    if (
        not evidence_id
        or evidence_id not in interval_ids
        or (owner and owner != assignment_id)
    ):
        return None
    if not _is_schema_2_interval(interval):
        edge = _positive_number(interval.get("observed_transition_w"))
        if edge is None:
            return None
        energy = _positive_number(interval.get("measured_energy_kwh"))
        return _evidence_record(
            evidence_id,
            "legacy_interval",
            interval,
            True,
            edge,
            -edge,
            None,
            None,
            _duration_seconds(interval),
            energy,
            "measured" if energy is not None else None,
            min(_quality(interval), _LEGACY_INTERVAL_CONFIDENCE_CAP),
            True,
        )
    on = (
        _positive_number(interval.get("start_transition_w"))
        if interval.get("start_transition_eligible") is True
        else None
    )
    raw_off = (
        _model_number(interval.get("stop_transition_w"))
        if interval.get("stop_transition_eligible") is True
        else None
    )
    off = raw_off if raw_off is not None and raw_off < 0 else None
    plateau = _schema_2_interval_plateau(interval)
    duration = _duration_seconds(interval)
    energy = _positive_number(interval.get("measured_energy_kwh"))
    if not any((on, off, plateau, energy)):
        return None
    issues: list[str] = []
    if plateau and energy and duration:
        mean_power = energy * 3_600_000 / duration
        if (
            abs(plateau - mean_power) / max(plateau, mean_power)
            > _POWER_ENERGY_DISAGREEMENT_RATIO
        ):
            issues.append("power_energy_disagreement")
    quality = _schema_2_interval_confidence(interval) * (0.5 if issues else 1.0)
    return _evidence_record(
        evidence_id,
        "interval",
        interval,
        True,
        on,
        off,
        plateau,
        "trace" if plateau is not None else None,
        duration,
        energy,
        "measured" if energy is not None else None,
        quality,
        False,
        tuple(issues),
    )


def _evidence_record(
    evidence_id: str,
    source_type: str,
    source: Mapping[str, Any],
    positive: bool,
    on: float | None,
    off: float | None,
    plateau: float | None,
    plateau_source: str | None,
    duration: float | None,
    energy: float | None,
    energy_source: str | None,
    quality: float,
    inferred_stop: bool,
    issues: tuple[str, ...] = (),
) -> _NormalizedAssignmentEvidence:
    timestamp = _nilm_datetime(source.get("end") or source.get("start"))
    return _NormalizedAssignmentEvidence(
        evidence_id,
        source_type,
        timestamp,
        timestamp.date().isoformat()
        if timestamp
        else str(source.get("end") or source.get("start") or evidence_id)[:10],
        positive,
        on,
        off,
        plateau,
        plateau_source,
        duration,
        energy,
        energy_source,
        quality,
        inferred_stop,
        issues,
    )


def _select_positive_evidence(
    records: Iterable[_NormalizedAssignmentEvidence],
) -> list[_NormalizedAssignmentEvidence]:
    ordered = sorted(records, key=_evidence_sort_key)
    representatives: list[_NormalizedAssignmentEvidence] = []
    seen_days: set[str] = set()
    source_counts: defaultdict[str, int] = defaultdict(int)
    for record in ordered:
        if record.local_day not in seen_days:
            if source_counts[record.source_type] >= _MAX_EVIDENCE_PER_SOURCE:
                continue
            representatives.append(record)
            seen_days.add(record.local_day)
            source_counts[record.source_type] += 1
    selected = representatives[:_MAX_POSITIVE_EVIDENCE]
    day_counts = defaultdict(int)
    source_counts = defaultdict(int)
    for record in selected:
        day_counts[record.local_day] += 1
        source_counts[record.source_type] += 1
    for record in ordered:
        if len(selected) >= _MAX_POSITIVE_EVIDENCE:
            break
        if (
            record in selected
            or day_counts[record.local_day] >= _MAX_EVIDENCE_PER_DAY
            or source_counts[record.source_type] >= _MAX_EVIDENCE_PER_SOURCE
        ):
            continue
        selected.append(record)
        day_counts[record.local_day] += 1
        source_counts[record.source_type] += 1
    return selected


def _evidence_sort_key(
    record: _NormalizedAssignmentEvidence,
) -> tuple[float, float, float, str]:
    return (
        -record.quality,
        -_SOURCE_TRUST[record.source_type],
        -(record.timestamp.timestamp() if record.timestamp else 0.0),
        record.evidence_id,
    )


def _weighted_median(
    values: list[float | None], records: list[_NormalizedAssignmentEvidence]
) -> float:
    pairs = sorted(
        (float(value), _evidence_weight(record))
        for value, record in zip(values, records, strict=False)
        if value is not None
    )
    target = sum(weight for _, weight in pairs) / 2
    total = 0.0
    for index, (value, weight) in enumerate(pairs):
        total += weight
        if total == target and index + 1 < len(pairs):
            return (value + pairs[index + 1][0]) / 2
        if total >= target:
            return value
    return pairs[-1][0]


def _weighted_mad(
    values: list[float | None], records: list[_NormalizedAssignmentEvidence]
) -> float:
    usable = [
        (float(value), record)
        for value, record in zip(values, records, strict=False)
        if value is not None
    ]
    if not usable:
        return 0.0
    center = _weighted_median(
        [value for value, _ in usable], [record for _, record in usable]
    )
    return _weighted_median(
        [abs(value - center) for value, _ in usable], [record for _, record in usable]
    )


def _profile(
    values: list[float | None],
    records: list[_NormalizedAssignmentEvidence],
    *,
    precision: int = 3,
) -> dict[str, Any]:
    usable = [
        (float(value), record)
        for value, record in zip(values, records, strict=False)
        if value is not None
    ]
    if not usable:
        return {
            "median": None,
            "mad": None,
            "p10": None,
            "p90": None,
            "sample_count": 0,
            "effective_support": 0.0,
            "distinct_days": 0,
        }
    vals, recs = zip(*usable, strict=False)
    return {
        "median": round(_weighted_median(list(vals), list(recs)), precision),
        "mad": round(_weighted_mad(list(vals), list(recs)), precision),
        "p10": round(_weighted_percentile(list(vals), list(recs), 0.1), precision),
        "p90": round(_weighted_percentile(list(vals), list(recs), 0.9), precision),
        "sample_count": len(recs),
        "effective_support": round(_effective_support(list(recs)), 3),
        "distinct_days": _distinct_days(recs),
    }


def _duration_profile(
    records: list[_NormalizedAssignmentEvidence],
) -> dict[str, Any]:
    profile = _profile([record.duration_s for record in records], records)
    log_values = [log(float(record.duration_s)) for record in records]
    profile.update(
        median_seconds=profile["median"],
        mad_seconds=profile["mad"],
        p10_seconds=profile["p10"],
        p90_seconds=profile["p90"],
        median_log_seconds=(
            round(_weighted_median(log_values, records), 3) if records else None
        ),
        mad_log_seconds=(
            round(_weighted_mad(log_values, records), 3) if records else None
        ),
    )
    return profile


def _energy_profile(
    records: list[_NormalizedAssignmentEvidence],
) -> dict[str, Any]:
    weighted_records = [
        replace(
            record,
            quality=record.quality
            * (
                _ESTIMATED_ENERGY_WEIGHT if record.energy_source == "estimated" else 1.0
            ),
        )
        for record in records
    ]
    profile = _profile(
        [record.energy_kwh for record in weighted_records],
        weighted_records,
        precision=6,
    )
    measured_count = sum(record.energy_source == "measured" for record in records)
    estimated_count = sum(record.energy_source == "estimated" for record in records)
    profile.update(
        sample_count=len(records),
        measured_count=measured_count,
        estimated_count=estimated_count,
        source=(
            "mixed"
            if measured_count and estimated_count
            else "measured"
            if measured_count
            else "estimated"
            if estimated_count
            else "unknown"
        ),
        weighted_median_kwh=profile["median"],
        weighted_mad_kwh=profile["mad"],
        weighted_p10_kwh=profile["p10"],
        weighted_p90_kwh=profile["p90"],
        median_kwh=profile["median"],
        mad_kwh=profile["mad"],
        p10_kwh=profile["p10"],
        p90_kwh=profile["p90"],
    )
    return profile


def _weighted_plateau_records(
    records: list[_NormalizedAssignmentEvidence],
) -> list[_NormalizedAssignmentEvidence]:
    return [
        replace(
            record,
            quality=record.quality
            * (
                _EDGE_DERIVED_PLATEAU_WEIGHT
                if record.plateau_source == "edge_derived"
                else 1.0
            ),
        )
        for record in records
    ]


def _learn_nilm_active_states(
    records: list[_NormalizedAssignmentEvidence],
) -> list[float] | None:
    """Learn up to three compact active plateaus, or an envelope when broad."""
    if not records:
        return []
    one_center = _weighted_median([record.plateau_w for record in records], records)
    if _effective_support(records) < _NILM_STATE_SPLIT_MIN_EFFECTIVE_SUPPORT:
        return [round(one_center, 3)]
    baseline = _weighted_absolute_deviation(records, one_center)
    best: tuple[float, list[list[_NormalizedAssignmentEvidence]]] | None = None
    ordered = sorted(
        records, key=lambda record: (record.plateau_w or 0.0, record.evidence_id)
    )
    for count in range(2, _NILM_MAX_ACTIVE_STATES + 1):
        for groups in _nilm_contiguous_groups(ordered, count):
            centers = [
                _weighted_median([item.plateau_w for item in group], group)
                for group in groups
            ]
            if not _nilm_state_groups_valid(groups, centers):
                continue
            deviation = sum(
                _weighted_absolute_deviation(group, center)
                for group, center in zip(groups, centers, strict=True)
            )
            if (
                baseline <= 0
                or (baseline - deviation) / baseline
                < _NILM_STATE_MIN_DISPERSION_REDUCTION
            ):
                continue
            key = (
                deviation,
                [[item.evidence_id for item in group] for group in groups],
            )
            if best is None or key < (
                best[0],
                [[item.evidence_id for item in group] for group in best[1]],
            ):
                best = (deviation, groups)
    if best is None:
        spread = _weighted_mad([record.plateau_w for record in records], records)
        return None if spread >= 20.0 and len(records) >= 2 else [round(one_center, 3)]
    return [
        round(_weighted_median([item.plateau_w for item in group], group), 3)
        for group in best[1]
    ]


def _nilm_contiguous_groups(
    records: list[_NormalizedAssignmentEvidence], count: int
) -> Iterable[list[list[_NormalizedAssignmentEvidence]]]:
    for cuts in combinations(range(1, len(records)), count - 1):
        boundaries = (0, *cuts, len(records))
        yield [
            records[boundaries[index] : boundaries[index + 1]] for index in range(count)
        ]


def _weighted_absolute_deviation(
    records: list[_NormalizedAssignmentEvidence], center: float
) -> float:
    return sum(
        _evidence_weight(record) * abs((record.plateau_w or 0.0) - center)
        for record in records
    )


def _nilm_state_groups_valid(
    groups: list[list[_NormalizedAssignmentEvidence]], centers: list[float]
) -> bool:
    if any(
        _effective_support(group) < _NILM_STATE_MIN_EFFECTIVE_SUPPORT
        or _distinct_days(group) < _NILM_STATE_MIN_DISTINCT_DAYS
        for group in groups
    ):
        return False
    for left, right, left_group, right_group in zip(
        centers, centers[1:], groups, groups[1:], strict=False
    ):
        left_spread = _weighted_mad([item.plateau_w for item in left_group], left_group)
        right_spread = _weighted_mad(
            [item.plateau_w for item in right_group], right_group
        )
        pooled = (left_spread + right_spread) / 2
        if right - left <= max(50.0, 3.0 * pooled, 0.15 * right):
            return False
    return True


def _state_members(
    state_powers: list[float], records: list[_NormalizedAssignmentEvidence]
) -> list[tuple[float, list[_NormalizedAssignmentEvidence]]]:
    members = [[] for _ in state_powers]
    for record in records:
        index = min(
            range(len(state_powers)),
            key=lambda item: (
                abs((record.plateau_w or 0.0) - state_powers[item]),
                item,
            ),
        )
        members[index].append(record)
    return list(zip(state_powers, members, strict=True))


def _count_values(values: Iterable[str | None]) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for value in values:
        if value:
            counts[value] += 1
    return dict(sorted(counts.items()))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _weighted_percentile(
    values: list[float],
    records: list[_NormalizedAssignmentEvidence],
    fraction: float,
) -> float:
    pairs = sorted(
        (float(value), _evidence_weight(record))
        for value, record in zip(values, records, strict=False)
    )
    target = sum(weight for _, weight in pairs) * fraction
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= target:
            return value
    return pairs[-1][0]


def _rich_transition_prototype(
    assignment_id: str,
    direction: str,
    start: float,
    end: float,
    records: list[_NormalizedAssignmentEvidence],
    *,
    from_state_id: str | None = None,
    to_state_id: str | None = None,
) -> dict[str, Any]:
    values = [
        record.on_delta_w if direction == "on" else record.off_delta_w
        for record in records
    ]
    center = _weighted_median(values, records)
    inferred = direction == "off" and all(record.inferred_stop for record in records)
    from_state_id = from_state_id or ("off" if direction == "on" else "running")
    to_state_id = to_state_id or ("running" if direction == "on" else "off")
    kind = _semantic_transition_kind(
        direction,
        from_state_id,
        to_state_id,
        start,
        end,
    )
    prototype = {
        "id": _canonical_prototype_id(assignment_id, kind, from_state_id, to_state_id),
        "kind": kind,
        "direction": direction,
        "from_state_id": from_state_id,
        "to_state_id": to_state_id,
        "from_state_w": round(start, 3),
        "to_state_w": round(end, 3),
        "delta_w": round(center, 3),
        "spread_w": round(_weighted_mad(values, records), 3),
        "sample_count": len(records),
        "effective_support": round(
            _weighted_support(records) * (_LEGACY_STOP_WEIGHT if inferred else 1.0), 3
        ),
        "distinct_days": _distinct_days(records),
        "evidence_kind": "inferred_legacy_stop" if inferred else "observed",
    }
    vars_ = [
        record.on_delta_var if direction == "on" else record.off_delta_var
        for record in records
    ]
    var_records = [
        record
        for value, record in zip(vars_, records, strict=False)
        if value is not None
    ]
    if var_records:
        var_values = [value for value in vars_ if value is not None]
        var_center = _weighted_median(var_values, var_records)
        prototype.update(
            delta_var=round(var_center, 3),
            spread_var=round(_weighted_mad(var_values, var_records), 3),
        )
    return prototype


def _semantic_transition_kind(
    direction: str,
    from_state_id: str,
    to_state_id: str,
    from_state_w: float,
    to_state_w: float,
) -> str:
    """Return lifecycle semantics while retaining electrical direction separately."""
    if from_state_id == "off" and to_state_id != "off":
        return "start"
    if from_state_id != "off" and to_state_id == "off":
        return "stop"
    if to_state_w > from_state_w:
        return "state_up"
    if to_state_w < from_state_w:
        return "state_down"
    return "state_up" if direction == "on" else "state_down"


def _canonical_prototype_id(
    assignment_id: str,
    kind: str,
    from_state_id: str,
    to_state_id: str,
) -> str:
    """Return an assignment-scoped transition identity when ownership is known."""
    return (
        f"{assignment_id}:{kind}:{from_state_id}->{to_state_id}"
        if assignment_id
        else f"{kind}:{from_state_id}->{to_state_id}"
    )


def _evidence_weight(record: _NormalizedAssignmentEvidence) -> float:
    return max(record.quality, 0.05) * _SOURCE_TRUST[record.source_type]


def _effective_support(
    records: Iterable[_NormalizedAssignmentEvidence], multiplier: float = 1.0
) -> float:
    weights = [_evidence_weight(record) * multiplier for record in records]
    return (
        sum(weights) ** 2 / sum(weight * weight for weight in weights)
        if weights
        else 0.0
    )


def _weighted_support(records: Iterable[_NormalizedAssignmentEvidence]) -> float:
    return sum(_evidence_weight(record) for record in records)


def _distinct_days(records: Iterable[_NormalizedAssignmentEvidence]) -> int:
    return len({record.local_day for record in records})


def _close_rejected_conflicts(
    negatives: list[_NormalizedAssignmentEvidence],
    on: list[_NormalizedAssignmentEvidence],
    off: list[_NormalizedAssignmentEvidence],
) -> int:
    centers = [record.on_delta_w for record in on] + [
        abs(record.off_delta_w) for record in off
    ]
    return sum(
        1
        for record in negatives
        if any(
            value is not None and abs(abs(value) - center) <= max(10.0, center * 0.15)
            for value in (record.on_delta_w, record.off_delta_w)
            for center in centers
            if center is not None
        )
    )


def _evidence_confidence(
    records: list[_NormalizedAssignmentEvidence],
    on: list[_NormalizedAssignmentEvidence],
    off: list[_NormalizedAssignmentEvidence],
    conflicts: int,
    *,
    state_support: float,
) -> float:
    support = min(_effective_support(records) / 8, 1.0)
    days = min(_distinct_days(records) / 6, 1.0)
    directional = (bool(on) + bool(off)) / 2
    spreads = [
        _weighted_mad([record.on_delta_w for record in on], on)
        / max(abs(_weighted_median([record.on_delta_w for record in on], on)), 1.0)
        if on
        else 0.0,
        _weighted_mad([record.off_delta_w for record in off], off)
        / max(abs(_weighted_median([record.off_delta_w for record in off], off)), 1.0)
        if off
        else 0.0,
        _weighted_mad(
            [record.plateau_w for record in records if record.plateau_w is not None],
            [record for record in records if record.plateau_w is not None],
        )
        / max(
            _weighted_median(
                [
                    record.plateau_w
                    for record in records
                    if record.plateau_w is not None
                ],
                [record for record in records if record.plateau_w is not None],
            ),
            1.0,
        )
        if any(record.plateau_w is not None for record in records)
        else 0.0,
    ]
    if off:
        off_values = [abs(record.off_delta_w) for record in off]
        spreads.append(
            (_percentile(off_values, 0.9) - _percentile(off_values, 0.1))
            / max(_weighted_median(off_values, off), 1.0)
        )
    dispersion = min(max(spreads), 1.0)
    inferred_only = bool(records) and all(record.inferred_stop for record in records)
    quality = sum(record.quality for record in records) / len(records)
    score = (
        (0.1 + 0.35 * support + 0.15 * days + 0.2 * directional + 0.2 * state_support)
        * quality
        * (1 - 0.5 * dispersion)
        * (1 - min(conflicts * 0.1, 0.4))
    )
    confidence_cap = (
        0.25
        if inferred_only
        else _CONFIDENCE_CAP
        if state_support > 0
        else _TRANSITION_ONLY_CONFIDENCE_CAP
    )
    return round(min(score, confidence_cap), 3)


def _empty_assignment_model(normalized: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_schema_version": 2,
        "model_kind": "binary",
        "role": normalized["role"],
        "power_states_w": [],
        "states": [],
        "transition_prototypes": [],
        "run_profile": {},
        "evidence_summary": {
            "positive_count": 0,
            "negative_count": 0,
            "positive_distinct_days": 0,
            "effective_support": 0.0,
            "state_support": 0.0,
            "source_counts": {},
            "inferred_stop_count": 0,
            "close_rejected_conflicts": 0,
            "quality_issues": [],
        },
        "evidence_confidence": 0.0,
        "model_confidence": 0.0,
        "model_revision": normalized["model_revision"],
        "model_fingerprint": "",
    }


def _model_fingerprint(model: Mapping[str, Any]) -> str:
    parts = repr(
        (
            model.get("power_states_w"),
            model.get("model_kind"),
            model.get("states"),
            sorted(
                (
                    item.get("direction"),
                    item.get("delta_w"),
                    item.get("spread_w"),
                    item.get("delta_var"),
                    item.get("spread_var"),
                    item.get("sample_count"),
                    item.get("effective_support"),
                    item.get("distinct_days"),
                )
                for item in model.get("transition_prototypes", [])
            ),
            model.get("run_profile"),
            model.get("evidence_summary"),
            model.get("model_confidence"),
            model.get("evidence_confidence"),
        )
    )
    return sha256(parts.encode()).hexdigest()[:16]


def _is_schema_2_interval(interval: Mapping[str, Any]) -> bool:
    """Return whether an interval uses backend-derived directional evidence."""
    version = _model_number(interval.get("evidence_schema_version"))
    return version is not None and version >= 2


def _positive_number(value: Any) -> float | None:
    number = _model_number(value)
    return number if number is not None and number > 0 else None


def _duration_seconds(source: Mapping[str, Any]) -> float | None:
    duration = _positive_number(source.get("duration_s"))
    if duration is not None:
        return duration
    start = _nilm_datetime(source.get("start"))
    end = _nilm_datetime(source.get("end"))
    return (end - start).total_seconds() if start and end and end > start else None


def _quality(source: Mapping[str, Any]) -> float:
    value = next(
        (
            _model_number(source.get(key))
            for key in ("evidence_confidence", "power_confidence", "confidence")
            if _model_number(source.get(key)) is not None
        ),
        0.0,
    )
    coverage = _model_number(source.get("power_coverage"))
    return min(
        max(
            value * (min(max(coverage, 0.0), 1.0) if coverage is not None else 1.0), 0.0
        ),
        1.0,
    )


def _schema_2_interval_confidence(interval: Mapping[str, Any]) -> float:
    """Bound backend evidence confidence by its actual power coverage."""
    confidence = next(
        (
            value
            for key in ("evidence_confidence", "power_confidence", "confidence")
            if (value := _model_number(interval.get(key))) is not None
        ),
        0.0,
    )
    coverage = _model_number(interval.get("power_coverage"))
    if coverage is not None:
        confidence *= min(max(coverage, 0.0), 1.0)
    return min(max(confidence, 0.0), 1.0)


def _schema_2_interval_plateau(interval: Mapping[str, Any]) -> float | None:
    """Return complete, eligible schema-2 active-state evidence if available."""
    coverage = _model_number(interval.get("power_coverage"))
    if (
        interval.get("plateau_eligible") is not True
        or coverage is None
        or coverage < DEFAULT_THRESHOLDS.complete_energy_coverage
    ):
        return None
    for key in ("median_power_w", "average_power_w"):
        if (value := _model_number(interval.get(key))) is not None and value > 0:
            return value
    return None


def normalize_nilm_assignment_model(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional persisted assignment model fields conservatively."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    role = assignment.get("role")
    states = assignment.get("power_states_w")
    confidence = _model_number(assignment.get("model_confidence"))
    valid_states = (
        [_model_number(value) for value in states] if isinstance(states, list) else []
    )
    prototypes: list[dict[str, Any]] = []
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
        direction = str(item["direction"])
        from_state_id = str(item.get("from_state_id") or "").strip() or (
            "off" if direction == "on" else "running"
        )
        to_state_id = str(item.get("to_state_id") or "").strip() or (
            "running" if direction == "on" else "off"
        )
        kind = _semantic_transition_kind(
            direction,
            from_state_id,
            to_state_id,
            values[0],
            values[1],
        )
        stored_id = str(item.get("id") or "").strip()
        canonical_id = _canonical_prototype_id(
            assignment_id,
            kind,
            from_state_id,
            to_state_id,
        )
        prototype_id = canonical_id if assignment_id else stored_id or canonical_id
        stored_aliases = item.get("legacy_ids")
        aliases: list[str] = []
        for value in (
            stored_id,
            *(stored_aliases if isinstance(stored_aliases, list | tuple) else ()),
        ):
            alias = str(value or "").strip()
            if alias and alias != prototype_id and alias not in aliases:
                aliases.append(alias)
        spread_var = _model_number(item.get("spread_var"))
        prototype: dict[str, Any] = {
            "id": prototype_id,
            "kind": kind,
            "direction": direction,
            "from_state_w": values[0],
            "to_state_w": values[1],
            "delta_w": values[2],
            "spread_w": max(values[3], 0.0),
            "sample_count": _model_nonnegative_int(item.get("sample_count")),
            "effective_support": max(
                _model_number(item.get("effective_support"))
                or _model_nonnegative_int(item.get("sample_count")),
                0.0,
            ),
            "distinct_days": _model_nonnegative_int(item.get("distinct_days")),
            "evidence_kind": str(item.get("evidence_kind") or "observed"),
            "from_state_id": from_state_id,
            "to_state_id": to_state_id,
        }
        if aliases:
            prototype["legacy_ids"] = aliases
        if (delta_var := _model_number(item.get("delta_var"))) is not None:
            prototype["delta_var"] = delta_var
        if spread_var is not None:
            prototype["spread_var"] = max(spread_var, 0.0)
        prototypes.append(prototype)
    state_values = (
        valid_states if all(value is not None for value in valid_states) else []
    )
    active = state_values[1] if len(state_values) > 1 else None
    states = (
        [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {
                "id": "running",
                "kind": "running",
                "power_w": active,
                "spread_w": 0.0,
                "power_source": "legacy",
            },
        ]
        if active is not None
        else []
    )
    if isinstance(assignment.get("states"), list):
        rich_states = []
        for item in assignment["states"]:
            state_id = (
                str(item.get("id") or "").strip() if isinstance(item, Mapping) else ""
            )
            if (
                not state_id
                or (state_id != "off" and not state_id.startswith("active_"))
                and state_id != "running"
            ):
                continue
            if (power := _model_number(item.get("power_w"))) is None:
                continue
            state = {
                "id": state_id,
                "kind": "off"
                if state_id == "off"
                else ("active" if state_id.startswith("active_") else "running"),
                "power_w": power,
                "spread_w": max(_model_number(item.get("spread_w")) or 0.0, 0.0),
            }
            if state_id != "off" and isinstance(item.get("power_source"), str):
                state["power_source"] = item["power_source"]
            rich_states.append(state)
        if rich_states and sum(item["id"] == "off" for item in rich_states) == 1:
            states = sorted(
                rich_states,
                key=lambda item: (item["id"] != "off", item["power_w"], item["id"]),
            )
            if not state_values:
                state_values = [item["power_w"] for item in states]
    prototypes.sort(key=lambda item: (item["direction"], item["delta_w"], item["id"]))
    normalized = {
        "model_schema_version": 2,
        "model_kind": str(assignment.get("model_kind") or "binary")
        if str(assignment.get("model_kind") or "binary")
        in {"binary", "multi_state", "variable_envelope"}
        else "binary",
        "role": role.strip() if isinstance(role, str) and role.strip() else "component",
        "power_states_w": state_values,
        "states": states,
        "transition_prototypes": prototypes,
        "model_confidence": min(max(confidence or 0.0, 0.0), 1.0),
        "evidence_confidence": min(
            max(
                _model_number(assignment.get("evidence_confidence"))
                or confidence
                or 0.0,
                0.0,
            ),
            1.0,
        ),
        "model_revision": _model_nonnegative_int(assignment.get("model_revision")),
        "model_fingerprint": str(assignment.get("model_fingerprint") or ""),
    }
    if isinstance(assignment.get("run_profile"), Mapping):
        normalized["run_profile"] = {
            name: _normalize_assignment_profile(profile)
            for name, profile in assignment["run_profile"].items()
            if isinstance(name, str) and isinstance(profile, Mapping)
        }
    if isinstance(assignment.get("evidence_summary"), Mapping):
        summary = assignment["evidence_summary"]
        normalized["evidence_summary"] = {
            "positive_count": _model_nonnegative_int(summary.get("positive_count")),
            **{
                key: number
                for key in (
                    "negative_count",
                    "positive_distinct_days",
                    "effective_support",
                    "state_support",
                    "close_rejected_conflicts",
                    "inferred_stop_count",
                )
                if (number := _model_number(summary.get(key))) is not None
            },
            "quality_issues": [
                item
                for item in summary.get("quality_issues", ())
                if isinstance(item, str)
            ],
        }
        if isinstance(summary.get("source_counts"), Mapping):
            normalized["evidence_summary"]["source_counts"] = {
                str(key): _model_nonnegative_int(value)
                for key, value in summary["source_counts"].items()
                if isinstance(key, str)
            }
    if not normalized["model_fingerprint"] and state_values:
        normalized["model_fingerprint"] = _model_fingerprint(normalized)
    return normalized


def _normalize_assignment_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        field: number
        for field, raw in profile.items()
        if (number := _model_number(raw)) is not None
    }
    if profile.get("source") in {"measured", "estimated", "mixed", "unknown"}:
        normalized["source"] = profile["source"]
    if isinstance(profile.get("source_counts"), Mapping):
        normalized["source_counts"] = {
            str(key): _model_nonnegative_int(value)
            for key, value in profile["source_counts"].items()
            if isinstance(key, str)
        }
    return normalized


def nilm_assignment_model_is_compound_eligible(
    assignment: Mapping[str, Any],
    prototype: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a candidate transition has sufficient compound evidence."""
    prototypes = assignment.get("transition_prototypes")
    if not isinstance(prototypes, list):
        return False
    candidates = [prototype] if prototype is not None else prototypes
    learned = any(
        isinstance(item, Mapping)
        and _model_nonnegative_int(item.get("sample_count")) >= 3
        and _model_number(item.get("effective_support", item.get("sample_count")))
        is not None
        and _model_number(item.get("effective_support", item.get("sample_count")))
        >= 3.0
        for item in candidates
    )
    confidence = _model_number(assignment.get("model_confidence"))
    summary = assignment.get("evidence_summary")
    state_support = (
        _model_number(summary.get("state_support"))
        if isinstance(summary, Mapping)
        else None
    )
    return (
        learned
        and confidence is not None
        and confidence >= 0.70
        and state_support is not None
        and state_support > 0
    )


def _transition_prototype(
    direction: str,
    from_state_w: float,
    to_state_w: float,
    delta_w: float,
    values: list[float],
    var_values: list[float],
) -> dict[str, Any]:
    center = median(values)
    prototype = {
        "direction": direction,
        "from_state_w": round(from_state_w, 3),
        "to_state_w": round(to_state_w, 3),
        "delta_w": round(delta_w, 3),
        "spread_w": round(median(abs(value - center) for value in values), 3),
        "sample_count": len(values),
    }
    if var_values:
        var_center = median(var_values)
        prototype.update(
            {
                "delta_var": round(var_center, 3),
                "spread_var": round(
                    median(abs(value - var_center) for value in var_values), 3
                ),
            }
        )
    return prototype


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
    on_delta = _session_edge_metric(
        session,
        value_key="on_delta_w",
        edge_id_key="on_edge_id",
        metric="w",
    )
    off_delta = _session_edge_metric(
        session,
        value_key="off_delta_w",
        edge_id_key="off_edge_id",
        metric="w",
    )
    return (
        on_delta if on_delta is not None else legacy,
        off_delta
        if off_delta is not None
        else (-abs(legacy) if legacy is not None else None),
    )


def _session_edge_metric(
    session: Mapping[str, Any],
    *,
    value_key: str,
    edge_id_key: str,
    metric: str,
) -> float | None:
    if (value := _model_number(session.get(value_key))) is not None:
        return value
    prefix = f"{metric}="
    for token in str(session.get(edge_id_key) or "").split("|"):
        if token.startswith(prefix):
            return _model_number(token.removeprefix(prefix))
    return None


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


def nilm_display_name(
    display_name: str,
    configured_circuit_names: Iterable[str] = (),
) -> str:
    """Disambiguate an estimated appliance from configured circuit names."""
    name = str(display_name or "").strip()
    configured = {
        str(value or "").strip().casefold()
        for value in configured_circuit_names
        if str(value or "").strip()
    }
    return f"{name} (estimated)" if name.casefold() in configured else name


def build_nilm_appliance_identity(
    assignment: Mapping[str, Any],
    *,
    mains_source_entity_id: str | None = None,
    configured_circuit_names: Iterable[str] = (),
) -> NilmApplianceIdentity:
    """Build an appliance identity without conflating it with its mains source."""
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if not assignment_id:
        raise ValueError("Missing assignment_id.")
    appliance_id = str(assignment.get("appliance_id") or assignment_id).strip()
    display_name = str(
        assignment.get("display_name") or appliance_id or assignment_id
    ).strip()
    return NilmApplianceIdentity(
        appliance_key=f"nilm:{assignment_id}",
        assignment_id=assignment_id,
        appliance_id=appliance_id,
        display_name=nilm_display_name(display_name, configured_circuit_names),
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
    delta_var: float | None = None
    delta_va: float | None = None
    delta_pf: float | None = None
    direction: str = "on"
    leg_a_delta_w: float | None = None
    leg_b_delta_w: float | None = None
    leg_balance_ratio: float | None = None
    dominant_leg: str = "unknown"
    split_phase_type: str = "unknown"
    origin: str = "aggregate"
    parent_edge_id: str | None = None
    explained_known_circuit_ids: tuple[str, ...] = ()


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
    delta_var: float | None = None
    spread_var: float | None = None
    prototype_id: str = ""
    transition_kind: str = ""
    from_state_id: str = ""
    to_state_id: str = ""
    prototype_aliases: tuple[str, ...] = ()


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
class NilmScoreBreakdown:
    """Immutable components of one renormalized transition score."""

    total: float
    electrical_fit: float
    helper_score: float | None
    duration_state_score: float | None
    validation_score: float | None
    available_weight: float
    prototype_id: str = ""
    assignment_id: str = ""

    @property
    def electrical_contribution(self) -> float:
        """Return the renormalized electrical contribution to ``total``."""
        return 0.55 * self.electrical_fit / self.available_weight

    @property
    def helper_contribution(self) -> float | None:
        """Return the optional renormalized helper contribution."""
        return (
            0.25 * self.helper_score / self.available_weight
            if self.helper_score is not None
            else None
        )

    @property
    def duration_contribution(self) -> float | None:
        """Return the optional renormalized duration contribution."""
        return (
            0.10 * self.duration_state_score / self.available_weight
            if self.duration_state_score is not None
            else None
        )

    @property
    def validation_contribution(self) -> float | None:
        """Return the optional renormalized validation contribution."""
        return (
            0.10 * self.validation_score / self.available_weight
            if self.validation_score is not None
            else None
        )


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
    accepted_score: float | None = None
    runner_up_score: float | None = None
    score_margin: float | None = None
    accepted_prototype_ids: tuple[str, ...] = ()
    score_breakdowns: tuple[NilmScoreBreakdown, ...] = ()
    component_breakdowns: tuple[NilmScoreBreakdown, ...] = ()
    unavailable_channels: tuple[str, ...] = ()


def nilm_transition_tolerance_w(prototype: NilmTransitionPrototype) -> float:
    """Return the learned real-power tolerance for a transition."""
    return max(15.0, 3.0 * prototype.spread_w, 0.20 * abs(prototype.delta_w))


def conservation_tolerance_w(source_power_w: float, noise_spread_w: float) -> float:
    """Return the permitted source/component conservation error."""
    return max(25.0, 3.0 * noise_spread_w, 0.10 * abs(source_power_w))


def duration_state_score_for_transition(
    prototype: NilmTransitionPrototype,
    assignment: Mapping[str, Any],
    runtime: Mapping[str, Any],
    timestamp: datetime,
) -> float | None:
    """Return soft run or supported active-state dwell evidence."""
    kind = prototype.transition_kind.strip().lower()
    if kind == "start":
        return None
    if kind in {"state_up", "state_down"}:
        if (
            not prototype.from_state_id
            or not prototype.to_state_id
            or prototype.from_state_id == "off"
            or prototype.to_state_id == "off"
            or prototype.from_state_id == prototype.to_state_id
            or not isfinite(prototype.from_state_w)
            or not isfinite(prototype.to_state_w)
            or (
                kind == "state_up"
                and not (
                    prototype.direction == "on"
                    and prototype.delta_w > 0
                    and prototype.to_state_w > prototype.from_state_w
                )
            )
            or (
                kind == "state_down"
                and not (
                    prototype.direction == "off"
                    and prototype.delta_w < 0
                    and prototype.to_state_w < prototype.from_state_w
                )
            )
        ):
            return None
        profiles = assignment.get("state_dwell_profiles")
        profile = (
            profiles.get(prototype.from_state_id)
            if isinstance(profiles, Mapping)
            else None
        )
        started_at = _nilm_datetime(runtime.get("state_since"))
    else:
        if kind and kind != "stop":
            return None
        if prototype.direction != "off" or prototype.delta_w >= 0:
            return None
        if (
            not isfinite(prototype.from_state_w)
            or prototype.from_state_w <= 0
            or not isfinite(prototype.to_state_w)
            or not isclose(prototype.to_state_w, 0.0, abs_tol=1e-6)
        ):
            return None
        if prototype.to_state_id and prototype.to_state_id != "off":
            return None
        if prototype.from_state_id == "off":
            return None
        run_profile = assignment.get("run_profile")
        profile = (
            run_profile.get("duration_s") if isinstance(run_profile, Mapping) else None
        )
        started_at = _nilm_runtime_started_at(runtime)
    if not isinstance(profile, Mapping) or started_at is None:
        return None
    support = _nilm_finite_number(profile.get("effective_support"))
    distinct_days = _nilm_finite_number(profile.get("distinct_days"))
    p10 = _nilm_positive_finite(profile.get("p10_seconds", profile.get("p10")))
    p90 = _nilm_positive_finite(profile.get("p90_seconds", profile.get("p90")))
    median_seconds = _nilm_positive_finite(
        profile.get("median_seconds", profile.get("median"))
    )
    if (
        support is None
        or support < NILM_DURATION_MIN_EFFECTIVE_SUPPORT
        or distinct_days is None
        or distinct_days < NILM_DURATION_MIN_DISTINCT_DAYS
        or p10 is None
        or p90 is None
        or median_seconds is None
        or not p10 <= median_seconds <= p90
        or p90 / p10 > NILM_DURATION_MAX_CENTRAL_RATIO
    ):
        return None

    observed_at = _nilm_datetime(timestamp)
    if observed_at is None:
        return None
    duration_seconds = (observed_at - started_at).total_seconds()
    if not isfinite(duration_seconds) or duration_seconds <= 0:
        return None
    if p10 <= duration_seconds <= p90:
        return 1.0

    median_log = _nilm_finite_number(profile.get("median_log_seconds"))
    mad_log = _nilm_finite_number(profile.get("mad_log_seconds"))
    center_log = median_log if median_log is not None else log(median_seconds)
    dispersion = max(mad_log or 0.0, 0.0)
    lower_log = log(p10)
    upper_log = log(p90)
    taper = max(
        3.0 * dispersion,
        center_log - lower_log,
        upper_log - center_log,
        NILM_DURATION_MIN_LOG_TAPER,
    )
    distance = (
        lower_log - log(duration_seconds)
        if duration_seconds < p10
        else log(duration_seconds) - upper_log
    )
    position = min(max(distance / taper, 0.0), 1.0)
    return _nilm_unit(1.0 - (3.0 * position**2 - 2.0 * position**3))


def build_nilm_validation_profile(
    assignment: Mapping[str, Any],
    *,
    session_outcomes: Iterable[Mapping[str, Any]] = (),
    held_out_replay: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a deterministic, revision-matched validation reliability profile."""
    trusted = [
        item
        for record in (*tuple(session_outcomes), *tuple(held_out_replay))
        if (
            item := _nilm_trusted_validation_outcome(
                assignment, record, allow_ground_truth=False
            )
        )
        is not None
    ]

    schema = _nilm_finite_number(assignment.get("validation_schema_version"))
    method = str(assignment.get("validation_method") or "").strip().lower()
    if schema is not None and schema >= 2 and method == "one_to_one_iou":
        stored = assignment.get("validation_outcomes")
        if isinstance(stored, list | tuple):
            trusted.extend(
                item
                for record in stored
                if isinstance(record, Mapping)
                and (
                    item := _nilm_trusted_validation_outcome(
                        assignment, record, allow_ground_truth=True
                    )
                )
                is not None
            )

    deduplicated = _nilm_deduplicate_validation_outcomes(trusted)

    correct_count = sum(outcome for _, _, outcome, _ in deduplicated)
    wrong_count = len(deduplicated) - correct_count
    days = {day for _, _, _, day in deduplicated if day is not None}
    reliability = (correct_count + NILM_VALIDATION_PRIOR_CORRECT) / (
        len(deduplicated) + NILM_VALIDATION_PRIOR_CORRECT + NILM_VALIDATION_PRIOR_WRONG
    )
    eligible = (
        len(deduplicated) >= NILM_VALIDATION_MIN_OUTCOMES
        and len(days) >= NILM_VALIDATION_MIN_DISTINCT_DAYS
    )
    source_counts = {
        source: sum(item_source == source for _, item_source, _, _ in deduplicated)
        for source in sorted({item_source for _, item_source, _, _ in deduplicated})
    }
    return {
        "sample_count": len(deduplicated),
        "effective_support": float(len(deduplicated)),
        "distinct_days": len(days),
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "reliability": reliability,
        "runtime_eligible": eligible,
        "runtime_score": reliability if eligible else None,
        "source_counts": source_counts,
    }


def _nilm_trusted_validation_outcome(
    assignment: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    allow_ground_truth: bool,
) -> tuple[str, str, bool, str | None] | None:
    source = _nilm_validation_source(record)
    if source is None or (source == "ground_truth" and not allow_ground_truth):
        return None
    outcome_id = str(
        record.get("outcome_id")
        or record.get("replay_id")
        or (record.get("session_id") if source != "held_out_replay" else "")
        or record.get("validation_outcome_id")
        or ""
    ).strip()
    if not outcome_id:
        return None
    outcome = str(record.get("outcome") or record.get("result") or "").strip().lower()
    if outcome not in {"correct", "wrong"}:
        return None
    if source == "held_out_replay" and not _nilm_valid_held_out_replay(
        assignment, record
    ):
        return None
    if not _nilm_validation_revision_matches(assignment, record):
        return None
    timestamp = _nilm_datetime(record.get("timestamp") or record.get("created_at"))
    day = timestamp.date().isoformat() if timestamp else None
    return outcome_id, source, outcome == "correct", day


def _nilm_valid_held_out_replay(
    assignment: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    """Return whether replay provenance names one bounded prediction window."""
    expected_revision = _model_nonnegative_int(assignment.get("model_revision"))
    recorded_revision = _nilm_finite_number(
        record.get("model_revision", record.get("prediction_model_revision"))
    )
    if (
        expected_revision <= 0
        or recorded_revision is None
        or recorded_revision <= 0
        or not recorded_revision.is_integer()
        or int(recorded_revision) != expected_revision
    ):
        return False
    window_id = str(
        record.get("test_window_id")
        or record.get("replay_window_id")
        or record.get("window_id")
        or ""
    ).strip()
    window_start = _nilm_datetime(
        record.get("test_window_start")
        or record.get("replay_window_start")
        or record.get("window_start")
    )
    window_end = _nilm_datetime(
        record.get("test_window_end")
        or record.get("replay_window_end")
        or record.get("window_end")
    )
    observed_at = _nilm_datetime(record.get("timestamp") or record.get("created_at"))
    return bool(
        window_id
        and window_start is not None
        and window_end is not None
        and observed_at is not None
        and window_start <= observed_at <= window_end
        and timedelta(0)
        < window_end - window_start
        <= NILM_VALIDATION_MAX_REPLAY_WINDOW
    )


def _nilm_validation_source(record: Mapping[str, Any]) -> str | None:
    source = (
        str(
            record.get("source")
            or record.get("validation_source")
            or record.get("outcome_source")
            or record.get("source_type")
            or ""
        )
        .strip()
        .lower()
    )
    if source in {"feedback", "explicit_feedback", "session_feedback", "user_feedback"}:
        return "feedback"
    if source in {"held_out_replay", "heldout_replay", "held-out-replay"}:
        return "held_out_replay"
    if source in {"ground_truth", "assignment_ground_truth"}:
        return "ground_truth"
    return None


def _nilm_deduplicate_validation_outcomes(
    records: Iterable[tuple[str, str, bool, str | None]],
) -> list[tuple[str, str, bool, str | None]]:
    by_id: dict[str, list[tuple[str, str, bool, str | None]]] = defaultdict(list)
    for record in records:
        by_id[record[0]].append(record)
    deduplicated: list[tuple[str, str, bool, str | None]] = []
    source_order = {"feedback": 0, "held_out_replay": 1, "ground_truth": 2}
    for outcome_id in sorted(by_id):
        duplicates = by_id[outcome_id]
        outcomes = {item[2] for item in duplicates}
        if len(outcomes) != 1:
            continue
        source = min(
            (item[1] for item in duplicates),
            key=lambda item: (source_order[item], item),
        )
        days = sorted(item[3] for item in duplicates if item[3] is not None)
        deduplicated.append(
            (outcome_id, source, outcomes.pop(), days[0] if days else None)
        )
    return deduplicated


def _nilm_validation_revision_matches(
    assignment: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    expected_revision = _model_nonnegative_int(assignment.get("model_revision"))
    recorded_revision = _nilm_finite_number(
        record.get("model_revision", record.get("prediction_model_revision"))
    )
    expected_fingerprint = str(assignment.get("model_fingerprint") or "").strip()
    recorded_fingerprint = str(
        record.get("model_fingerprint")
        or record.get("prediction_model_fingerprint")
        or ""
    ).strip()
    matches: list[bool] = []
    if recorded_revision is not None and expected_revision > 0:
        matches.append(recorded_revision == expected_revision)
    if recorded_fingerprint and expected_fingerprint:
        matches.append(recorded_fingerprint == expected_fingerprint)
    return bool(matches) and all(matches)


def _nilm_runtime_started_at(runtime: Mapping[str, Any]) -> datetime | None:
    for key in (
        "session_started_at",
        "current_session_started_at",
        "started_at",
        "start",
    ):
        if (value := _nilm_datetime(runtime.get(key))) is not None:
            return value
    current_session = runtime.get("current_session")
    return (
        _nilm_runtime_started_at(current_session)
        if isinstance(current_session, Mapping)
        else None
    )


def _nilm_finite_number(value: Any) -> float | None:
    number = _nilm_number(value)
    return number if number is not None and isfinite(number) else None


def _nilm_positive_finite(value: Any) -> float | None:
    number = _nilm_finite_number(value)
    return number if number is not None and number > 0 else None


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
    return score_nilm_transition_breakdown(
        edge,
        prototype,
        helper_score=helper_score,
        duration_state_score=duration_state_score,
        validation_score=validation_score,
        optional_electrical_fit=optional_electrical_fit,
    ).total


def score_nilm_transition_breakdown(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
    *,
    helper_score: float | None,
    duration_state_score: float | None,
    validation_score: float | None,
    optional_electrical_fit: float | None = None,
) -> NilmScoreBreakdown:
    """Return the immutable components of a transition score."""
    tolerance = nilm_transition_tolerance_w(prototype)
    real_fit = max(0.0, 1.0 - abs(edge.delta_w - prototype.delta_w) / tolerance)
    electrical_fit = real_fit
    if optional_electrical_fit is not None and isfinite(optional_electrical_fit):
        electrical_fit = 0.70 * real_fit + 0.30 * _nilm_unit(optional_electrical_fit)
    helper = _nilm_optional_unit(helper_score)
    duration = _nilm_optional_unit(duration_state_score)
    validation = _nilm_optional_unit(validation_score)
    terms = [(0.55, electrical_fit)] + [
        (weight, value)
        for weight, value in (
            (0.25, helper),
            (0.10, duration),
            (0.10, validation),
        )
        if value is not None
    ]
    available_weight = sum(weight for weight, _ in terms)
    return NilmScoreBreakdown(
        total=sum(weight * value for weight, value in terms) / available_weight,
        electrical_fit=electrical_fit,
        helper_score=helper,
        duration_state_score=duration,
        validation_score=validation,
        available_weight=available_weight,
        prototype_id=prototype.prototype_id or prototype.assignment_id,
        assignment_id=prototype.assignment_id,
    )


def reconcile_nilm_edge(
    edge: NilmEdge,
    models: Iterable[NilmAssignmentModel],
    current_states_w: Mapping[str, float | None],
    helper_scores: Mapping[str, float | None],
    duration_state_scores: Mapping[str, float | None],
    validation_scores: Mapping[str, float | None],
    *,
    current_state_ids: Mapping[str, str | None] | None = None,
    helper_conflict: bool = False,
) -> NilmReconciliationResult:
    """Match one edge to a bounded set of legal assignment transitions."""
    models = tuple(models)
    legal = [
        (model, prototype)
        for model in models
        for prototype in model.transition_prototypes
        if _nilm_transition_legal(model, prototype, current_states_w, current_state_ids)
    ]
    if helper_conflict:
        return _nilm_reconciliation(edge, (), reason="helper_conflict")

    singles = sorted(
        [
            (
                _nilm_candidate_breakdown(
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
        key=lambda item: (-item[0].total, _nilm_transition_choice_key(edge, item[1])),
    )
    if singles and singles[0][0].total >= 0.70:
        if len(singles) == 1 or singles[0][0].total - singles[1][0].total >= 0.15:
            return _nilm_reconciliation(
                edge,
                (singles[0][1],),
                reason="single",
                accepted_breakdown=singles[0][0],
                runner_up_score=singles[1][0].total if len(singles) > 1 else None,
                score_breakdowns=tuple(item[0] for item in singles),
            )
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
    compounds: list[
        tuple[
            NilmScoreBreakdown,
            tuple[NilmTransitionPrototype, ...],
            tuple[NilmScoreBreakdown, ...],
        ]
    ] = []
    ordered_transitions = tuple(
        per_assignment[assignment_id] for assignment_id in sorted(per_assignment)
    )
    # ponytail: four simultaneous transitions bound combinatorial work; already-active
    # components remain unlimited. Raise only if labelled replay needs larger groups.
    for size in range(2, min(4, len(ordered_transitions)) + 1):
        sized_compounds: list[
            tuple[
                NilmScoreBreakdown,
                tuple[NilmTransitionPrototype, ...],
                tuple[NilmScoreBreakdown, ...],
            ]
        ] = []
        for group in combinations(ordered_transitions, size):
            combined = _nilm_combined_transition(group)
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
            duration_score = _nilm_mean_available(
                duration_state_scores, group, prototype_level=True
            )
            validation_score = _nilm_mean_available(
                validation_scores, group, prototype_level=True
            )
            breakdown = score_nilm_transition_breakdown(
                edge,
                combined,
                helper_score=_nilm_mean_available(helper_scores, group),
                duration_state_score=duration_score,
                validation_score=validation_score,
                optional_electrical_fit=_nilm_reactive_fit(edge, combined),
            )
            if breakdown.total >= 0.75 and improvement >= 0.30:
                component_breakdowns = tuple(
                    _nilm_component_breakdown(
                        prototype,
                        helper_scores.get(prototype.assignment_id),
                        _nilm_score_lookup(duration_state_scores, prototype),
                        _nilm_score_lookup(validation_scores, prototype),
                    )
                    for prototype in group
                )
                sized_compounds.append((breakdown, group, component_breakdowns))
        if sized_compounds:
            compounds = sized_compounds
            break
    compounds.sort(
        key=lambda item: (
            -item[0].total,
            tuple(_nilm_prototype_score_id(prototype) for prototype in item[1]),
        )
    )
    if compounds and (
        len(compounds) == 1 or compounds[0][0].total - compounds[1][0].total >= 0.15
    ):
        return _nilm_reconciliation(
            edge,
            compounds[0][1],
            reason="compound",
            accepted_breakdown=compounds[0][0],
            runner_up_score=compounds[1][0].total if len(compounds) > 1 else None,
            score_breakdowns=tuple(item[0] for item in compounds),
            component_breakdowns=compounds[0][2],
        )
    return _nilm_reconciliation(
        edge,
        (),
        reason=(
            "ambiguous" if compounds or single_reason == "ambiguous" else single_reason
        ),
        score_breakdowns=tuple(item[0] for item in singles),
    )


def _nilm_unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _nilm_optional_unit(value: float | None) -> float | None:
    return _nilm_unit(value) if value is not None and isfinite(value) else None


def _nilm_transition_legal(
    model: NilmAssignmentModel,
    prototype: NilmTransitionPrototype,
    current_states_w: Mapping[str, float | None],
    current_state_ids: Mapping[str, str | None] | None = None,
) -> bool:
    lifecycle = model.lifecycle_state.strip().lower()
    if lifecycle in {"hidden", "ignored", "rejected", "converted"}:
        return False
    current = current_states_w.get(model.assignment_id)
    if current is None or not isfinite(current):
        return False
    if current_state_ids is not None:
        expected_id = prototype.from_state_id
        current_id = str(current_state_ids.get(model.assignment_id) or "").strip()
        if not expected_id or current_id != expected_id:
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
) -> tuple[float, str, float, float, float, float, int, str, str]:
    return (
        abs(edge.delta_w - prototype.delta_w),
        prototype.direction,
        prototype.from_state_w,
        prototype.to_state_w,
        prototype.delta_w,
        prototype.spread_w,
        prototype.sample_count,
        prototype.assignment_id,
        prototype.prototype_id,
    )


def _nilm_candidate_score(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
    helpers: Mapping[str, float | None],
    durations: Mapping[str, float | None],
    validations: Mapping[str, float | None],
) -> float:
    return _nilm_candidate_breakdown(
        edge, prototype, helpers, durations, validations
    ).total


def _nilm_candidate_breakdown(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
    helpers: Mapping[str, float | None],
    durations: Mapping[str, float | None],
    validations: Mapping[str, float | None],
) -> NilmScoreBreakdown:
    return score_nilm_transition_breakdown(
        edge,
        prototype,
        helper_score=helpers.get(prototype.assignment_id),
        duration_state_score=_nilm_score_lookup(durations, prototype),
        validation_score=_nilm_score_lookup(validations, prototype),
        optional_electrical_fit=_nilm_reactive_fit(edge, prototype),
    )


def _nilm_score_lookup(
    scores: Mapping[str, float | None], prototype: NilmTransitionPrototype
) -> float | None:
    if prototype.prototype_id and prototype.prototype_id in scores:
        return scores[prototype.prototype_id]
    for alias in prototype.prototype_aliases:
        if alias in scores:
            return scores[alias]
    return scores.get(prototype.assignment_id)


def _nilm_prototype_score_id(prototype: NilmTransitionPrototype) -> str:
    return prototype.prototype_id or prototype.assignment_id


def _nilm_component_breakdown(
    prototype: NilmTransitionPrototype,
    helper_score: float | None,
    duration_state_score: float | None,
    validation_score: float | None,
) -> NilmScoreBreakdown:
    component_edge = NilmEdge(
        timestamp=datetime.min.replace(tzinfo=UTC),
        delta_w=prototype.delta_w,
        delta_var=prototype.delta_var,
        direction=prototype.direction,
    )
    return score_nilm_transition_breakdown(
        component_edge,
        prototype,
        helper_score=helper_score,
        duration_state_score=duration_state_score,
        validation_score=validation_score,
        optional_electrical_fit=(1.0 if prototype.delta_var is not None else None),
    )


def _nilm_reactive_fit(
    edge: NilmEdge,
    prototype: NilmTransitionPrototype,
) -> float | None:
    if edge.delta_var is None or prototype.delta_var is None:
        return None
    tolerance = max(
        25.0,
        3.0 * (prototype.spread_var or 0.0),
        0.40 * abs(prototype.delta_var),
    )
    return max(0.0, 1.0 - abs(edge.delta_var - prototype.delta_var) / tolerance)


def _nilm_combined_transition(
    transitions: Iterable[NilmTransitionPrototype],
) -> NilmTransitionPrototype:
    transitions = tuple(transitions)
    return NilmTransitionPrototype(
        assignment_id="+".join(item.assignment_id for item in transitions),
        direction="on" if sum(item.delta_w for item in transitions) > 0 else "off",
        from_state_w=sum(item.from_state_w for item in transitions),
        to_state_w=sum(item.to_state_w for item in transitions),
        delta_w=sum(item.delta_w for item in transitions),
        spread_w=sum(item.spread_w for item in transitions),
        sample_count=min(item.sample_count for item in transitions),
        delta_var=(
            sum(item.delta_var for item in transitions if item.delta_var is not None)
            if all(item.delta_var is not None for item in transitions)
            else None
        ),
        spread_var=(
            sum(item.spread_var or 0.0 for item in transitions)
            if all(item.spread_var is not None for item in transitions)
            else None
        ),
    )


def _nilm_mean_available(
    scores: Mapping[str, float | None],
    transitions: Iterable[NilmTransitionPrototype],
    *,
    prototype_level: bool = False,
) -> float | None:
    values = [
        value
        for item in transitions
        if (
            value := (
                _nilm_score_lookup(scores, item)
                if prototype_level
                else scores.get(item.assignment_id)
            )
        )
        is not None
        and isfinite(value)
    ]
    return sum(values) / len(values) if values else None


def _nilm_reconciliation(
    edge: NilmEdge,
    transitions: tuple[NilmTransitionPrototype, ...],
    *,
    reason: str,
    accepted_breakdown: NilmScoreBreakdown | None = None,
    runner_up_score: float | None = None,
    score_breakdowns: tuple[NilmScoreBreakdown, ...] = (),
    component_breakdowns: tuple[NilmScoreBreakdown, ...] = (),
) -> NilmReconciliationResult:
    residual = edge.delta_w - sum(item.delta_w for item in transitions)
    tolerance = (
        nilm_transition_tolerance_w(
            transitions[0]
            if len(transitions) == 1
            else _nilm_combined_transition(transitions)
        )
        if transitions
        else conservation_tolerance_w(edge.delta_w, 0.0)
    )
    accepted = bool(transitions)
    consistent = abs(residual) <= tolerance
    if accepted and not consistent:
        reason = "conservation_conflict"
        accepted = False
        accepted_breakdown = None
        component_breakdowns = ()
    accepted_score = (
        accepted_breakdown.total if accepted_breakdown is not None else None
    )
    return NilmReconciliationResult(
        accepted=accepted,
        transitions=transitions if accepted else (),
        residual_w=residual,
        tolerance_w=tolerance,
        compound=len(transitions) > 1 and accepted,
        consistent=consistent,
        energy_allocation_allowed=accepted and consistent,
        reason=reason,
        accepted_score=accepted_score,
        runner_up_score=runner_up_score,
        score_margin=(
            accepted_score - runner_up_score
            if accepted_score is not None and runner_up_score is not None
            else None
        ),
        accepted_prototype_ids=(
            tuple(_nilm_prototype_score_id(item) for item in transitions)
            if accepted
            else ()
        ),
        score_breakdowns=score_breakdowns[:_NILM_MAX_SCORE_BREAKDOWNS],
        component_breakdowns=component_breakdowns[:4],
        unavailable_channels=(
            tuple(
                name
                for name, value in (
                    ("helper", accepted_breakdown.helper_score),
                    ("duration", accepted_breakdown.duration_state_score),
                    ("validation", accepted_breakdown.validation_score),
                )
                if value is None
            )
            if accepted_breakdown is not None
            else ()
        ),
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
class KnownLoadTopology:
    """Configured topology expected for one known-load circuit."""

    expected_split_phase_types: tuple[str, ...] = ()
    configured_leg: str | None = None


KNOWN_LOAD_MAGNITUDE_WEIGHT = 0.65
KNOWN_LOAD_TIME_WEIGHT = 0.20
KNOWN_LOAD_TOPOLOGY_WEIGHT = 0.15
KNOWN_LOAD_ASSIGNMENT_AMBIGUITY_MARGIN = 0.05
KNOWN_LOAD_EXACT_ASSIGNMENT_MAX_BITMASK_NODES = 12

if not isclose(
    KNOWN_LOAD_MAGNITUDE_WEIGHT + KNOWN_LOAD_TIME_WEIGHT + KNOWN_LOAD_TOPOLOGY_WEIGHT,
    1.0,
):
    raise RuntimeError("Known-load candidate weights must sum to 1.0.")


@dataclass(frozen=True, slots=True)
class KnownLoadCandidateScore:
    """Weighted evidence for one aggregate-edge/known-event candidate."""

    total: float
    magnitude: float
    time: float
    topology: float
    time_offset_seconds: float
    topology_status: str


@dataclass(frozen=True, slots=True)
class KnownEventPowerEstimate:
    """Power estimate derived from a known circuit transition event."""

    magnitude_w: float
    signed_delta_w: float | None
    source: str
    transition_spread_w: float | None = None
    transition_timestamp: datetime | None = None
    transition_timing_uncertainty_s: float | None = None


@dataclass(frozen=True, slots=True)
class KnownLoadMatch:
    """NILM edge attributed to an already-known circuit event."""

    edge: NilmEdge
    known_circuit_id: str
    confidence: float
    known_power_w: float = 0.0
    event_type: EventType | None = None
    event_timestamp: datetime | None = None
    power_source: str | None = None
    time_distance_seconds: float | None = None
    magnitude_ratio: float | None = None
    topology_compatible: bool | None = None
    topology_score: float | None = None
    explained_delta_w: float = 0.0
    residual_delta_w: float = 0.0
    residual_edge: NilmEdge | None = None
    selection_method: str = "greedy"
    time_offset_seconds: float | None = None
    magnitude_score: float | None = None
    time_score: float | None = None
    topology_status: str | None = None
    known_power_source: str | None = None
    known_transition_delta_w: float | None = None
    known_transition_spread_w: float | None = None
    transition_timing_uncertainty_s: float | None = None
    power_match_confidence: float | None = None
    selection_status: str | None = None


@dataclass(frozen=True, slots=True)
class NilmMaskResult:
    """Known-load masking output."""

    matched_edges: tuple[KnownLoadMatch, ...]
    unmatched_edges: tuple[NilmEdge, ...]
    residual_edges: tuple[NilmEdge, ...] = ()
    ambiguous_edge_count: int = 0
    rejected_topology_candidates: tuple[KnownLoadMatch, ...] = ()

    @property
    def topology_rejections(self) -> tuple[KnownLoadMatch, ...]:
        """Compatibility alias for bounded topology-rejection diagnostics."""
        return self.rejected_topology_candidates


def known_load_topology_for_config(config: CircuitConfig) -> KnownLoadTopology:
    """Return NILM topology expectations derived from circuit configuration."""
    if config.mode is CircuitMode.SINGLE_PHASE:
        expected_types = ("single_leg_a", "single_leg_b")
    elif config.mode is CircuitMode.DUAL_PHASE:
        expected_types = ("balanced_240v",)
    else:
        expected_types = ()
    configured_legs = {
        normalized
        for sensor in config.sensors
        if (normalized := _normalize_known_load_leg(sensor.leg)) is not None
    }
    configured_leg = (
        next(iter(configured_legs))
        if config.mode is CircuitMode.SINGLE_PHASE and len(configured_legs) == 1
        else None
    )
    return KnownLoadTopology(expected_types, configured_leg)


def evaluate_known_load_topology(
    edge: NilmEdge,
    topology: KnownLoadTopology,
) -> str:
    """Evaluate one observed NILM edge against a known-load topology."""
    if not topology.expected_split_phase_types:
        return "not_evaluated"
    observed_type = str(edge.split_phase_type or "unknown")
    if observed_type in {"unknown", "missing_leg_data"}:
        return "unknown_topology"
    if observed_type not in topology.expected_split_phase_types:
        return "topology_mismatch"
    observed_leg = observed_known_load_leg(edge)
    if (
        topology.configured_leg is not None
        and observed_leg is not None
        and topology.configured_leg != observed_leg
    ):
        return "leg_mismatch"
    return "consistent"


def observed_known_load_leg(edge: NilmEdge) -> str | None:
    """Return the single-phase leg encoded by an observed NILM edge."""
    if edge.split_phase_type == "single_leg_a":
        return "a"
    if edge.split_phase_type == "single_leg_b":
        return "b"
    return None


def expected_known_load_dominant_legs(
    topology: KnownLoadTopology,
) -> tuple[str, ...]:
    """Return dominant-leg evidence expected by one topology."""
    if topology.expected_split_phase_types == ("balanced_240v",):
        return ("balanced",)
    if set(topology.expected_split_phase_types) == {"single_leg_a", "single_leg_b"}:
        return (topology.configured_leg,) if topology.configured_leg else ("a", "b")
    return ()


def _normalize_known_load_leg(leg: str | None) -> str | None:
    if leg is None:
        return None
    value = leg.strip().lower()
    if value in {"a", "left", "l1", "line1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "line2", "2"}:
        return "b"
    return None


@dataclass(frozen=True, slots=True)
class NilmSignature:
    """Recurring unmatched edge signature for user review."""

    signature_id: str
    median_delta_w: float
    median_delta_var: float | None = None
    median_delta_va: float | None = None
    median_delta_pf: float | None = None
    occurrence_count: int = 0
    confidence: float = 0.0
    user_label: str | None = None
    median_leg_a_delta_w: float | None = None
    median_leg_b_delta_w: float | None = None
    leg_balance_ratio: float | None = None
    dominant_leg: str = "unknown"
    split_phase_type: str = "unknown"
    unique_day_count: int = 0
    observation_span_seconds: float = 0.0
    dispersion_w: float = 0.0
    dispersion_var: float | None = None
    dispersion_va: float | None = None
    dispersion_pf: float | None = None
    normalized_cluster_radius: float = 1.0
    feature_coverage: float = 0.0
    topology_consistency: float = 0.0
    paired_occurrence_count: int = 0
    on_off_support: float = 0.0
    evidence_strength: float = 0.0
    model_fit: float = 0.0
    intrinsic_confidence: float = 0.0
    validated_precision: float | None = None
    confidence_kind: str = "evidence"


@dataclass(frozen=True, slots=True)
class NilmClusteringPolicy:
    """Bounded, deterministic tolerances for recurring edge signatures."""

    min_occurrences: int = 3
    max_refinement_passes: int = 3
    watts_ratio: float = 0.20
    watts_floor: float = 25.0
    var_ratio: float = 0.25
    var_floor: float = 25.0
    va_ratio: float = 0.20
    va_floor: float = 40.0
    pf_ratio: float = 0.25
    pf_floor: float = 0.03
    leg_watts_ratio: float = 0.20
    leg_watts_floor: float = 25.0
    balance_ratio: float = 0.25
    balance_floor: float = 0.10
    max_centroid_distance: float = 1.0
    max_complete_link_distance: float = 1.0
    ambiguous_best_fit_margin: float = 0.15


@dataclass(frozen=True, slots=True)
class _NilmFeatureStats:
    """Robust numeric descriptor for one cluster feature."""

    count: int
    median: float | None
    mad: float | None
    minimum: float | None
    maximum: float | None
    coverage: float


@dataclass(slots=True)
class _NilmEdgeCluster:
    """Mutable working cluster retaining members for diagnostics and pairing."""

    members: list[NilmEdge]
    direction: str
    split_phase_type: str
    dominant_leg: str
    feature_stats: dict[str, _NilmFeatureStats]


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
    on_delta_var: float | None = None
    off_delta_var: float | None = None


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
        "on_delta_var": session.on_delta_var,
        "off_delta_var": session.off_delta_var,
    }


def nilm_signature_fingerprint_v1(signature: NilmSignature) -> str:
    """Return the pre-v2 review key retained only as a migration alias."""
    return "|".join(
        (
            f"direction={_signature_direction(signature.signature_id)}",
            f"watts={_abs_value_bucket(signature.median_delta_w, 100.0)}",
            f"var={_optional_value_bucket(signature.median_delta_var, 100.0)}",
            f"va={_optional_value_bucket(signature.median_delta_va, 100.0)}",
            f"pf={_optional_value_bucket(signature.median_delta_pf, 0.05)}",
            f"split={signature.split_phase_type or 'unknown'}",
            f"leg={signature.dominant_leg or 'unknown'}",
            f"balance={_optional_ratio_bucket(signature.leg_balance_ratio)}",
        )
    )


def nilm_signature_fingerprint(signature: NilmSignature) -> str:
    """Return the versioned durable review key for one signature shape."""
    return "|".join(
        (
            "revision=2",
            f"direction={_signature_direction(signature.signature_id)}",
            f"watts={_abs_value_bucket(signature.median_delta_w, 50.0)}",
            f"var={_optional_value_bucket_v2(signature.median_delta_var, 25.0)}",
            f"va={_optional_value_bucket_v2(signature.median_delta_va, 50.0)}",
            f"pf={_optional_value_bucket_v2(signature.median_delta_pf, 0.025)}",
            f"split={signature.split_phase_type or 'unknown'}",
            f"leg={signature.dominant_leg or 'unknown'}",
            f"leg_a={_optional_value_bucket_v2(signature.median_leg_a_delta_w, 50.0)}",
            f"leg_b={_optional_value_bucket_v2(signature.median_leg_b_delta_w, 50.0)}",
            f"balance={_optional_value_bucket_v2(signature.leg_balance_ratio, 0.10)}",
        )
    )


def nilm_signature_is_off_direction(value: Any) -> bool:
    """Return whether a signature direction or fingerprint is OFF-only."""
    text = str(value or "").strip().casefold()
    return (
        text == "off"
        or text.startswith(("off-", "direction=off|"))
        or "direction=off" in text.split("|")
    )


def nilm_signature_is_assignable(value: Any) -> bool:
    """Return whether a signature can own a detected appliance component."""
    text = str(value or "").strip()
    return (
        bool(text)
        and text.casefold() != "unassigned"
        and not nilm_signature_is_off_direction(text)
    )


def resolve_nilm_signature_fingerprint(
    saved_fingerprint: str,
    signatures: Iterable[Mapping[str, Any]],
) -> str | None:
    """Resolve v2 keys or a uniquely represented legacy review key."""
    saved = str(saved_fingerprint or "").strip()
    current_by_value: dict[str, Mapping[str, Any]] = {}
    legacy_aliases: dict[str, list[str]] = defaultdict(list)
    for signature in signatures:
        primary = str(
            signature.get("feedback_fingerprint")
            or signature.get("signature_fingerprint")
            or signature.get("signature_id")
            or ""
        ).strip()
        if not primary:
            continue
        current_by_value.setdefault(primary, signature)
        for alias in _nilm_signature_legacy_aliases(signature):
            legacy_aliases[alias].append(primary)
    saved_parts = _nilm_fingerprint_parts(saved)
    if saved in current_by_value and (
        "=" not in saved or saved_parts.get("revision") == "2"
    ):
        return saved
    aliases = tuple(dict.fromkeys(legacy_aliases.get(saved, ())))
    if len(aliases) == 1:
        return aliases[0]
    if not saved_parts.get("direction") or not saved_parts.get("watts"):
        return saved or None
    candidates = [
        value
        for value in current_by_value
        if (parts := _nilm_fingerprint_parts(value)).get("direction")
        == saved_parts["direction"]
        and _nilm_fingerprint_bucket_compatible(
            saved_parts.get("watts"),
            parts.get("watts"),
        )
        and _nilm_fingerprint_topology_compatible(saved_parts, parts)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) < 2:
        return None
    ranked = sorted(
        (
            sum(
                saved_parts.get(key) not in {None, "unknown"}
                and saved_parts.get(key) == parts.get(key)
                for key in ("var", "va", "pf", "split", "leg", "balance")
            ),
            value,
        )
        for value in candidates
        for parts in (_nilm_fingerprint_parts(value),)
    )
    return ranked[-1][1] if ranked[-1][0] > ranked[-2][0] else None


def _nilm_fingerprint_parts(value: str) -> dict[str, str]:
    return {
        key: item
        for token in str(value or "").split("|")
        if "=" in token
        for key, item in (token.split("=", 1),)
    }


def _nilm_signature_legacy_aliases(signature: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stored or reconstructable v1 aliases without broad matching."""
    aliases = [
        str(signature.get("legacy_feedback_fingerprint") or "").strip(),
    ]
    fingerprint = str(signature.get("feedback_fingerprint") or "").strip()
    if fingerprint and not _nilm_fingerprint_parts(fingerprint).get("revision"):
        aliases.append(fingerprint)
    try:
        aliases.append(
            nilm_signature_fingerprint_v1(
                NilmSignature(
                    signature_id=str(signature.get("signature_id") or ""),
                    median_delta_w=float(signature.get("median_delta_w") or 0.0),
                    median_delta_var=_nilm_number(signature.get("median_delta_var")),
                    median_delta_va=_nilm_number(signature.get("median_delta_va")),
                    median_delta_pf=_nilm_number(signature.get("median_delta_pf")),
                    median_leg_a_delta_w=_nilm_number(
                        signature.get("median_leg_a_delta_w")
                    ),
                    median_leg_b_delta_w=_nilm_number(
                        signature.get("median_leg_b_delta_w")
                    ),
                    leg_balance_ratio=_nilm_number(signature.get("leg_balance_ratio")),
                    dominant_leg=str(signature.get("dominant_leg") or "unknown"),
                    split_phase_type=str(
                        signature.get("split_phase_type") or "unknown"
                    ),
                )
            )
        )
    except (TypeError, ValueError):
        pass
    return tuple(alias for alias in dict.fromkeys(aliases) if alias)


def _nilm_fingerprint_bucket_compatible(
    saved: str | None,
    current: str | None,
) -> bool:
    if saved == current:
        return True
    if not saved or not current or "unknown" in {saved, current}:
        return False
    try:
        saved_start, saved_end = (float(value) for value in saved.split("-", 1))
        current_start, current_end = (float(value) for value in current.split("-", 1))
    except (TypeError, ValueError):
        return False
    return max(saved_start, current_start) < min(saved_end, current_end)


def _nilm_fingerprint_topology_compatible(
    saved: Mapping[str, str], current: Mapping[str, str]
) -> bool:
    return all(
        saved.get(key) in {None, "unknown"} or saved.get(key) == current.get(key)
        for key in ("split", "leg")
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
                    edge = self._edge_between(baseline, sample)
                    if edge is not None:
                        edge = replace(edge, timestamp=candidate.timestamp)
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
                    edge = self._edge_between(baseline, sample)
                    if edge is not None:
                        edge = replace(edge, timestamp=candidate.timestamp)
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
        previous_real_time = _source_updated_at(previous, SensorRole.REAL_POWER)
        sample_real_time = _source_updated_at(sample, SensorRole.REAL_POWER)
        previous_va, previous_pf = _nilm_electrical_features(
            previous,
            previous_real_time,
            self.confirmation_max_interval,
        )
        sample_va, sample_pf = _nilm_electrical_features(
            sample,
            sample_real_time,
            self.confirmation_max_interval,
        )
        previous_var_time = _source_updated_at(previous, SensorRole.REACTIVE_POWER)
        sample_var_time = _source_updated_at(sample, SensorRole.REACTIVE_POWER)

        return NilmEdge(
            timestamp=sample.timestamp,
            delta_w=delta_w,
            delta_var=_aligned_optional_delta(
                sample.reactive_power,
                previous.reactive_power,
                sample_var_time,
                previous_var_time,
                sample_real_time,
                previous_real_time,
                self.confirmation_max_interval,
            ),
            delta_va=_aligned_optional_delta(
                sample_va[0],
                previous_va[0],
                sample_va[1],
                previous_va[1],
                sample_real_time,
                previous_real_time,
                self.confirmation_max_interval,
            ),
            delta_pf=_aligned_optional_delta(
                sample_pf[0],
                previous_pf[0],
                sample_pf[1],
                previous_pf[1],
                sample_real_time,
                previous_real_time,
                self.confirmation_max_interval,
            ),
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


def _nilm_electrical_features(
    sample: CircuitSample,
    real_power_updated_at: datetime,
    max_interval: timedelta | None,
) -> tuple[tuple[float | None, datetime | None], tuple[float | None, datetime | None]]:
    consistency = evaluate_metric_consistency(
        real_power_w=getattr(sample, "real_power", None),
        apparent_power_va=getattr(sample, "apparent_power", None),
        power_factor=getattr(sample, "power_factor", None),
        voltage_v=getattr(sample, "voltage", None),
        current_a=getattr(sample, "current", None),
        leg_a_voltage_v=getattr(sample, "leg_a_voltage", None),
        leg_a_current_a=getattr(sample, "leg_a_current", None),
        leg_b_voltage_v=getattr(sample, "leg_b_voltage", None),
        leg_b_current_a=getattr(sample, "leg_b_current", None),
    )
    if consistency.status in {
        "metric_mismatch",
        "apparent_power_mismatch",
        "power_factor_mismatch",
    }:
        return (None, None), (None, None)

    apparent_power = consistency.reported_apparent_power_va
    apparent_power_role = SensorRole.APPARENT_POWER
    if apparent_power is None:
        apparent_power = consistency.expected_apparent_power_va
        apparent_power_role = SensorRole.VOLTAGE
    apparent_power_timestamp = (
        (
            _aligned_source_updated_at(
                sample,
                (SensorRole.VOLTAGE, SensorRole.CURRENT),
                real_power_updated_at,
                max_interval,
            )
            if apparent_power_role is SensorRole.VOLTAGE
            else _source_updated_at(sample, apparent_power_role)
        )
        if apparent_power is not None
        else None
    )

    power_factor = consistency.reported_power_factor
    power_factor_timestamp = (
        _source_updated_at(sample, SensorRole.POWER_FACTOR)
        if power_factor is not None
        else apparent_power_timestamp
    )
    if power_factor is None:
        power_factor = consistency.expected_power_factor
    return (
        (apparent_power, apparent_power_timestamp),
        (power_factor, power_factor_timestamp),
    )


def _source_updated_at(sample: CircuitSample, role: SensorRole) -> datetime:
    for source_role, timestamp in getattr(sample, "source_updated_at_by_role", ()):
        if source_role is role or str(source_role) == role.value:
            return timestamp
    return sample.timestamp


def _aligned_source_updated_at(
    sample: CircuitSample,
    roles: tuple[SensorRole, ...],
    real_power_updated_at: datetime,
    max_interval: timedelta | None,
) -> datetime | None:
    timestamps = tuple(_source_updated_at(sample, role) for role in roles)
    if max_interval is not None and any(
        abs(timestamp - real_power_updated_at) > max_interval
        for timestamp in timestamps
    ):
        return None
    return max(timestamps)


def _aligned_optional_delta(
    current: float | None,
    previous: float | None,
    current_updated_at: datetime | None,
    previous_updated_at: datetime | None,
    current_real_updated_at: datetime,
    previous_real_updated_at: datetime,
    max_interval: timedelta | None,
) -> float | None:
    if current is None or previous is None:
        return None
    if max_interval is not None:
        if current_updated_at is None or previous_updated_at is None:
            return None
        if (
            abs(current_updated_at - current_real_updated_at) > max_interval
            or abs(previous_updated_at - previous_real_updated_at) > max_interval
        ):
            return None
    return float(current) - float(previous)


@dataclass(frozen=True, slots=True)
class _KnownLoadCandidate:
    edge_index: int
    event_index: int
    match: KnownLoadMatch
    score: KnownLoadCandidateScore


@dataclass(frozen=True, slots=True)
class _KnownLoadAssignment:
    candidate_indices: tuple[int, ...] = ()
    total_score: float = 0.0
    total_offset_seconds: float = 0.0


def _known_load_topology_score(status: str) -> float:
    if status == "consistent":
        return 1.0
    if status in {"unknown_topology", "not_evaluated"}:
        return 0.5
    return 0.0


def _select_known_load_candidates(
    candidates: list[_KnownLoadCandidate],
) -> tuple[set[int], set[int]]:
    selected: set[int] = set()
    ambiguous_edges: set[int] = set()
    for component in _known_load_candidate_components(candidates):
        edge_nodes = {candidates[index].edge_index for index in component}
        event_nodes = {candidates[index].event_index for index in component}
        if min(len(edge_nodes), len(event_nodes)) > (
            KNOWN_LOAD_EXACT_ASSIGNMENT_MAX_BITMASK_NODES
        ):
            component_selected, component_ambiguous = _greedy_known_load_component(
                candidates, component
            )
            selected.update(component_selected)
            ambiguous_edges.update(component_ambiguous)
            continue

        assignments = _exact_known_load_component(candidates, component)
        if not assignments:
            continue
        best = assignments[0]
        second = assignments[1] if len(assignments) > 1 else None
        best_indices = set(best.candidate_indices)
        if (
            second is not None
            and best.candidate_indices != second.candidate_indices
            and best.total_score - second.total_score
            <= KNOWN_LOAD_ASSIGNMENT_AMBIGUITY_MARGIN
        ):
            second_indices = set(second.candidate_indices)
            selected.update(best_indices & second_indices)
            ambiguous_edges.update(
                candidates[index].edge_index for index in best_indices ^ second_indices
            )
        else:
            selected.update(best_indices)
    return selected, ambiguous_edges


def _known_load_candidate_components(
    candidates: list[_KnownLoadCandidate],
) -> tuple[tuple[int, ...], ...]:
    by_edge: dict[int, list[int]] = defaultdict(list)
    by_event: dict[int, list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        by_edge[candidate.edge_index].append(index)
        by_event[candidate.event_index].append(index)

    components: list[tuple[int, ...]] = []
    remaining = set(range(len(candidates)))
    while remaining:
        start = min(
            remaining,
            key=lambda index: _candidate_stable_key(candidates[index]),
        )
        pending = [start]
        component: set[int] = set()
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            candidate = candidates[index]
            pending.extend(by_edge[candidate.edge_index])
            pending.extend(by_event[candidate.event_index])
        remaining.difference_update(component)
        components.append(
            tuple(
                sorted(
                    component,
                    key=lambda index: _candidate_stable_key(candidates[index]),
                )
            )
        )
    return tuple(components)


def _exact_known_load_component(
    candidates: list[_KnownLoadCandidate],
    component: tuple[int, ...],
) -> tuple[_KnownLoadAssignment, ...]:
    edge_nodes = sorted({candidates[index].edge_index for index in component})
    event_nodes = sorted({candidates[index].event_index for index in component})
    bitmask_is_edge = len(edge_nodes) <= len(event_nodes)
    bit_nodes = edge_nodes if bitmask_is_edge else event_nodes
    other_nodes = event_nodes if bitmask_is_edge else edge_nodes
    bit_position = {node: position for position, node in enumerate(bit_nodes)}
    candidates_by_other: dict[int, list[int]] = defaultdict(list)
    for index in component:
        candidate = candidates[index]
        other_node = candidate.event_index if bitmask_is_edge else candidate.edge_index
        candidates_by_other[other_node].append(index)
    for values in candidates_by_other.values():
        values.sort(key=lambda index: _candidate_selection_key(candidates[index]))

    states: dict[int, tuple[_KnownLoadAssignment, ...]] = {0: (_KnownLoadAssignment(),)}
    for other_node in other_nodes:
        next_states: dict[int, list[_KnownLoadAssignment]] = defaultdict(list)
        for mask, assignments in states.items():
            for assignment in assignments:
                next_states[mask].append(assignment)
                for candidate_index in candidates_by_other.get(other_node, ()):
                    candidate = candidates[candidate_index]
                    bit_node = (
                        candidate.edge_index
                        if bitmask_is_edge
                        else candidate.event_index
                    )
                    bit = 1 << bit_position[bit_node]
                    if mask & bit:
                        continue
                    next_states[mask | bit].append(
                        _extend_known_load_assignment(
                            assignment,
                            candidate_index,
                            candidates,
                        )
                    )
        states = {
            mask: _best_known_load_assignments(values, candidates)
            for mask, values in next_states.items()
        }
    return _best_known_load_assignments(
        [assignment for values in states.values() for assignment in values],
        candidates,
    )


def _extend_known_load_assignment(
    assignment: _KnownLoadAssignment,
    candidate_index: int,
    candidates: list[_KnownLoadCandidate],
) -> _KnownLoadAssignment:
    indices = tuple(
        sorted(
            (*assignment.candidate_indices, candidate_index),
            key=lambda index: _candidate_stable_key(candidates[index]),
        )
    )
    candidate = candidates[candidate_index]
    return _KnownLoadAssignment(
        indices,
        assignment.total_score + candidate.score.total,
        assignment.total_offset_seconds + abs(candidate.score.time_offset_seconds),
    )


def _best_known_load_assignments(
    assignments: Iterable[_KnownLoadAssignment],
    candidates: list[_KnownLoadCandidate],
) -> tuple[_KnownLoadAssignment, ...]:
    unique = {assignment.candidate_indices: assignment for assignment in assignments}
    return tuple(
        sorted(
            unique.values(),
            key=lambda assignment: _known_load_assignment_sort_key(
                assignment, candidates
            ),
        )[:2]
    )


def _known_load_assignment_sort_key(
    assignment: _KnownLoadAssignment,
    candidates: list[_KnownLoadCandidate],
) -> tuple[float, int, float, tuple[tuple[int, int], ...]]:
    stable_pairs = tuple(
        _candidate_stable_key(candidates[index])
        for index in assignment.candidate_indices
    )
    return (
        -assignment.total_score,
        -len(assignment.candidate_indices),
        assignment.total_offset_seconds,
        stable_pairs,
    )


def _greedy_known_load_component(
    candidates: list[_KnownLoadCandidate],
    component: tuple[int, ...],
) -> tuple[set[int], set[int]]:
    by_edge: dict[int, list[int]] = defaultdict(list)
    by_event: dict[int, list[int]] = defaultdict(list)
    for index in component:
        by_edge[candidates[index].edge_index].append(index)
        by_event[candidates[index].event_index].append(index)

    ambiguous_edges: set[int] = set()
    ambiguous_events: set[int] = set()
    for values in by_edge.values():
        ranked = sorted(
            values,
            key=lambda index: _candidate_selection_key(candidates[index]),
        )
        if len(ranked) > 1 and (
            candidates[ranked[0]].score.total - candidates[ranked[1]].score.total
            <= KNOWN_LOAD_ASSIGNMENT_AMBIGUITY_MARGIN
        ):
            ambiguous_edges.add(candidates[ranked[0]].edge_index)
            ambiguous_events.update(
                candidates[index].event_index for index in ranked[:2]
            )
    for values in by_event.values():
        ranked = sorted(
            values,
            key=lambda index: _candidate_selection_key(candidates[index]),
        )
        if len(ranked) > 1 and (
            candidates[ranked[0]].score.total - candidates[ranked[1]].score.total
            <= KNOWN_LOAD_ASSIGNMENT_AMBIGUITY_MARGIN
        ):
            ambiguous_events.add(candidates[ranked[0]].event_index)
            ambiguous_edges.update(candidates[index].edge_index for index in ranked[:2])

    selected: set[int] = set()
    used_edges: set[int] = set()
    used_events: set[int] = set()
    for index in sorted(
        component,
        key=lambda candidate_index: _candidate_selection_key(
            candidates[candidate_index]
        ),
    ):
        candidate = candidates[index]
        if (
            candidate.edge_index in ambiguous_edges
            or candidate.event_index in ambiguous_events
            or candidate.edge_index in used_edges
            or candidate.event_index in used_events
        ):
            continue
        selected.add(index)
        used_edges.add(candidate.edge_index)
        used_events.add(candidate.event_index)
        candidates[index] = replace(
            candidate,
            match=replace(candidate.match, selection_method="greedy_fallback"),
        )
    return selected, ambiguous_edges


def _candidate_selection_key(
    candidate: _KnownLoadCandidate,
) -> tuple[float, float, int, int]:
    return (
        -candidate.score.total,
        abs(candidate.score.time_offset_seconds),
        candidate.edge_index,
        candidate.event_index,
    )


def _candidate_stable_key(candidate: _KnownLoadCandidate) -> tuple[int, int]:
    return candidate.edge_index, candidate.event_index


def attribute_known_loads(
    aggregate_edges: Iterable[NilmEdge],
    known_events: Iterable[CircuitEvent],
    time_window: timedelta = timedelta(seconds=15),
    watt_tolerance_ratio: float = 0.25,
    residual_min_delta_w: float = 100.0,
    topology_by_circuit: Mapping[str, KnownLoadTopology] | None = None,
) -> NilmMaskResult:
    """Attribute aggregate edges to known circuit events and retain residuals."""

    edges = list(aggregate_edges)
    events = list(known_events)
    candidates: list[_KnownLoadCandidate] = []
    rejected_topology_candidates: list[tuple[int, int, KnownLoadMatch]] = []
    time_window_seconds = max(time_window.total_seconds(), 0.0)
    magnitude_tolerance = max(float(watt_tolerance_ratio), 0.0)
    topology_by_circuit = topology_by_circuit or {}

    for edge_index, edge in enumerate(edges):
        if edge.origin != "aggregate":
            continue
        for event_index, event in enumerate(events):
            if event.event_type not in {
                EventType.START,
                EventType.STOP,
                EventType.POWER_TRANSITION,
            }:
                continue
            estimate = _event_power_estimate(event)
            if estimate is None:
                continue
            event_direction = (
                "on"
                if event.event_type is EventType.START
                or estimate.signed_delta_w is not None
                and estimate.signed_delta_w > 0.0
                else "off"
            )
            if edge.direction != event_direction:
                continue
            time_distance_seconds, time_offset_seconds = _known_event_time_distance(
                event, edge.timestamp
            )
            if time_distance_seconds > time_window_seconds:
                continue
            known_watts = estimate.magnitude_w
            power_source = estimate.source

            ratio = abs(abs(edge.delta_w) - known_watts) / known_watts
            if ratio > magnitude_tolerance:
                continue

            magnitude_score = (
                1.0
                if magnitude_tolerance == 0.0 and ratio == 0.0
                else max(0.0, 1.0 - (ratio / magnitude_tolerance))
                if magnitude_tolerance > 0.0
                else 0.0
            )
            time_score = (
                1.0
                if time_window_seconds == 0.0 and time_distance_seconds == 0.0
                else max(0.0, 1.0 - (time_distance_seconds / time_window_seconds))
                if time_window_seconds > 0.0
                else 0.0
            )
            topology_status = evaluate_known_load_topology(
                edge,
                topology_by_circuit.get(event.circuit_id, KnownLoadTopology()),
            )
            topology_score = _known_load_topology_score(topology_status)
            score = KnownLoadCandidateScore(
                total=(
                    KNOWN_LOAD_MAGNITUDE_WEIGHT * magnitude_score
                    + KNOWN_LOAD_TIME_WEIGHT * time_score
                    + KNOWN_LOAD_TOPOLOGY_WEIGHT * topology_score
                ),
                magnitude=magnitude_score,
                time=time_score,
                topology=topology_score,
                time_offset_seconds=time_offset_seconds,
                topology_status=topology_status,
            )
            signed_known_watts = (
                estimate.signed_delta_w
                if estimate.signed_delta_w is not None
                else known_watts
                if event.event_type is EventType.START
                else -known_watts
            )
            residual_delta_w = edge.delta_w - signed_known_watts
            if not isclose(
                edge.delta_w,
                signed_known_watts + residual_delta_w,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError("Known-load attribution must conserve real power.")
            eligible = topology_status not in {"topology_mismatch", "leg_mismatch"}
            residual_edge = (
                _known_load_residual_edge(
                    edge,
                    residual_delta_w,
                    event.circuit_id,
                    residual_min_delta_w=residual_min_delta_w,
                )
                if eligible
                else None
            )
            match = KnownLoadMatch(
                edge=edge,
                known_circuit_id=event.circuit_id,
                confidence=score.total,
                known_power_w=known_watts,
                event_type=event.event_type,
                event_timestamp=event.timestamp,
                power_source=power_source,
                time_distance_seconds=time_distance_seconds,
                magnitude_ratio=ratio,
                topology_compatible=(
                    True
                    if topology_status == "consistent"
                    else False
                    if not eligible
                    else None
                ),
                topology_score=score.topology,
                explained_delta_w=signed_known_watts,
                residual_delta_w=residual_delta_w,
                residual_edge=residual_edge,
                selection_method=(
                    "global_assignment" if eligible else "topology_rejected"
                ),
                time_offset_seconds=score.time_offset_seconds,
                magnitude_score=score.magnitude,
                time_score=score.time,
                topology_status=score.topology_status,
                known_power_source=estimate.source,
                known_transition_delta_w=estimate.signed_delta_w,
                known_transition_spread_w=estimate.transition_spread_w,
                transition_timing_uncertainty_s=(
                    estimate.transition_timing_uncertainty_s
                ),
                power_match_confidence=score.magnitude,
                selection_status=("candidate" if eligible else "rejected_topology"),
            )
            if eligible:
                candidates.append(
                    _KnownLoadCandidate(edge_index, event_index, match, score)
                )
            else:
                rejected_topology_candidates.append((edge_index, event_index, match))

    selected_candidate_indices, ambiguous_edge_indices = _select_known_load_candidates(
        candidates
    )
    selected_candidates = sorted(
        (candidates[index] for index in selected_candidate_indices),
        key=lambda candidate: (candidate.edge_index, candidate.event_index),
    )
    matched_edge_indices = {candidate.edge_index for candidate in selected_candidates}
    matched_edges = tuple(
        replace(candidate.match, selection_status="matched")
        for candidate in selected_candidates
    )
    accepted_unmatched_edges = tuple(
        edge for index, edge in enumerate(edges) if index not in matched_edge_indices
    )
    residual_edges = tuple(
        candidate.match.residual_edge
        for candidate in selected_candidates
        if candidate.match.residual_edge is not None
    )
    matched_event_indices = {candidate.event_index for candidate in selected_candidates}
    strongest_rejections_by_event: dict[int, tuple[int, int, KnownLoadMatch]] = {}
    for edge_index, event_index, match in rejected_topology_candidates:
        if edge_index in matched_edge_indices or event_index in matched_event_indices:
            continue
        existing = strongest_rejections_by_event.get(event_index)
        candidate_key = (
            -float(match.power_match_confidence or 0.0),
            float(match.time_distance_seconds or 0.0),
            edge_index,
            event_index,
        )
        if existing is None or candidate_key < (
            -float(existing[2].power_match_confidence or 0.0),
            float(existing[2].time_distance_seconds or 0.0),
            existing[0],
            existing[1],
        ):
            strongest_rejections_by_event[event_index] = (
                edge_index,
                event_index,
                match,
            )

    return NilmMaskResult(
        matched_edges,
        accepted_unmatched_edges + residual_edges,
        residual_edges,
        len(ambiguous_edge_indices),
        tuple(
            match
            for _edge_index, _event_index, match in sorted(
                strongest_rejections_by_event.values(),
                key=lambda item: (item[1], item[0]),
            )
        ),
    )


def mask_known_loads(
    aggregate_edges: Iterable[NilmEdge],
    known_events: Iterable[CircuitEvent],
    time_window: timedelta = timedelta(seconds=15),
    watt_tolerance_ratio: float = 0.25,
) -> NilmMaskResult:
    """Compatibility wrapper for direct known-load attribution."""

    return attribute_known_loads(
        aggregate_edges,
        known_events,
        time_window=time_window,
        watt_tolerance_ratio=watt_tolerance_ratio,
    )


def _known_load_residual_edge(
    edge: NilmEdge,
    residual_delta_w: float,
    known_circuit_id: str,
    *,
    residual_min_delta_w: float,
) -> NilmEdge | None:
    """Create a provenance-linked residual when it clears the configured floor."""

    threshold = (
        max(float(residual_min_delta_w), 0.0)
        if isfinite(float(residual_min_delta_w))
        else 100.0
    )
    if abs(residual_delta_w) < threshold:
        return None
    return NilmEdge(
        timestamp=edge.timestamp,
        delta_w=residual_delta_w,
        direction="on" if residual_delta_w > 0 else "off",
        origin="known_load_residual",
        parent_edge_id=_nilm_edge_id(edge),
        explained_known_circuit_ids=(known_circuit_id,),
    )


_CLUSTER_FEATURES: tuple[tuple[str, str, str, str], ...] = (
    ("delta_w", "delta_w", "watts_ratio", "watts_floor"),
    ("delta_var", "delta_var", "var_ratio", "var_floor"),
    ("delta_va", "delta_va", "va_ratio", "va_floor"),
    ("delta_pf", "delta_pf", "pf_ratio", "pf_floor"),
    ("leg_a", "leg_a_delta_w", "leg_watts_ratio", "leg_watts_floor"),
    ("leg_b", "leg_b_delta_w", "leg_watts_ratio", "leg_watts_floor"),
    ("balance", "leg_balance_ratio", "balance_ratio", "balance_floor"),
)
_MISSING_FEATURE_DISTANCE_PENALTY = 0.10


def cluster_recurring_signatures(edges: Iterable[NilmEdge]) -> list[NilmSignature]:
    """Cluster recurring edges without allowing transitive similarity bridges."""
    policy = NilmClusteringPolicy()
    clusters = _cluster_recurring_edges(
        edges,
        policy=policy,
        day_key=lambda value: value.astimezone(UTC).date(),
    )
    support = _cluster_on_off_support(clusters, policy=policy)
    signatures: list[NilmSignature] = []
    for cluster in clusters:
        if len(cluster.members) < policy.min_occurrences:
            continue
        signature = _signature_from_cluster(
            cluster,
            index=len(signatures) + 1,
            policy=policy,
            day_key=lambda value: value.astimezone(UTC).date(),
            paired_occurrence_count=support.get(id(cluster), (0, 0.0))[0],
            on_off_support=support.get(id(cluster), (0, 0.0))[1],
        )
        signatures.append(signature)
    return signatures


def _cluster_recurring_edges(
    edges: Iterable[NilmEdge],
    *,
    policy: NilmClusteringPolicy,
    day_key: Callable[[datetime], date],
) -> tuple[_NilmEdgeCluster, ...]:
    """Return deterministic, topology-partitioned clusters for recurring edges."""
    del day_key  # The core remains timezone-free; callers use it when emitting data.
    ordered_edges = tuple(sorted(edges, key=_nilm_cluster_edge_key))
    clusters = _assign_recurring_edges(ordered_edges, policy=policy)
    previous_membership = _cluster_membership_key(clusters)
    for _ in range(policy.max_refinement_passes):
        refined = _refine_recurring_clusters(
            clusters,
            ordered_edges=ordered_edges,
            policy=policy,
        )
        membership = _cluster_membership_key(refined)
        clusters = refined
        if membership == previous_membership:
            break
        previous_membership = membership
    return tuple(sorted(clusters, key=_nilm_cluster_sort_key))


def _assign_recurring_edges(
    edges: Iterable[NilmEdge],
    *,
    policy: NilmClusteringPolicy,
) -> list[_NilmEdgeCluster]:
    by_partition: dict[tuple[str, str, str], list[_NilmEdgeCluster]] = {}
    for edge in edges:
        partition = _nilm_cluster_partition(edge)
        candidates = by_partition.setdefault(partition, [])
        fits = [
            (distance, cluster)
            for cluster in candidates
            if (distance := _cluster_fit_distance(edge, cluster, policy=policy))
            is not None
        ]
        fits.sort(key=lambda item: (item[0], _nilm_cluster_sort_key(item[1])))
        if not fits or _missing_feature_best_fit_is_ambiguous(
            edge,
            fits,
            policy=policy,
        ):
            candidates.append(_new_nilm_edge_cluster(edge))
            continue
        selected = fits[0][1]
        selected.members.append(edge)
        selected.feature_stats = _cluster_feature_stats(selected.members)
    return [cluster for clusters in by_partition.values() for cluster in clusters]


def _refine_recurring_clusters(
    clusters: Iterable[_NilmEdgeCluster],
    *,
    ordered_edges: Iterable[NilmEdge],
    policy: NilmClusteringPolicy,
) -> list[_NilmEdgeCluster]:
    """Reassign each edge once against the current robust descriptors.

    This intentionally works from the complete-link-safe initial assignment,
    rather than restarting first-fit clustering.  Removing an edge before its
    decision means it is judged against the descriptors established by the
    other observations, then added back only when it is a unique admissible
    fit.  The caller bounds how often this pass runs.
    """
    working = [
        _NilmEdgeCluster(
            members=list(cluster.members),
            direction=cluster.direction,
            split_phase_type=cluster.split_phase_type,
            dominant_leg=cluster.dominant_leg,
            feature_stats=_cluster_feature_stats(cluster.members),
        )
        for cluster in clusters
    ]
    for edge in ordered_edges:
        _remove_edge_from_clusters(working, edge)
        partition = _nilm_cluster_partition(edge)
        candidates = [
            cluster
            for cluster in working
            if (
                cluster.direction,
                cluster.split_phase_type,
                cluster.dominant_leg,
            )
            == partition
        ]
        fits = [
            (distance, cluster)
            for cluster in candidates
            if (distance := _cluster_fit_distance(edge, cluster, policy=policy))
            is not None
        ]
        fits.sort(key=lambda item: (item[0], _nilm_cluster_sort_key(item[1])))
        if not fits or _missing_feature_best_fit_is_ambiguous(
            edge,
            fits,
            policy=policy,
        ):
            working.append(_new_nilm_edge_cluster(edge))
            continue
        selected = fits[0][1]
        selected.members.append(edge)
        selected.feature_stats = _cluster_feature_stats(selected.members)
    return working


def _remove_edge_from_clusters(
    clusters: list[_NilmEdgeCluster],
    edge: NilmEdge,
) -> None:
    """Remove one exact working member and refresh only its cluster."""
    for index, cluster in enumerate(clusters):
        for member_index, member in enumerate(cluster.members):
            if member is not edge:
                continue
            del cluster.members[member_index]
            if cluster.members:
                cluster.feature_stats = _cluster_feature_stats(cluster.members)
            else:
                del clusters[index]
            return
    raise ValueError("NILM clustering refinement lost an edge")


def _new_nilm_edge_cluster(edge: NilmEdge) -> _NilmEdgeCluster:
    return _NilmEdgeCluster(
        members=[edge],
        direction=edge.direction,
        split_phase_type=_nilm_cluster_split_phase_type(edge),
        dominant_leg=_nilm_cluster_dominant_leg(edge),
        feature_stats=_cluster_feature_stats((edge,)),
    )


def _nilm_cluster_partition(edge: NilmEdge) -> tuple[str, str, str]:
    split_phase_type = _nilm_cluster_split_phase_type(edge)
    dominant_leg = _nilm_cluster_dominant_leg(edge)
    return edge.direction, split_phase_type, dominant_leg


def _nilm_cluster_split_phase_type(edge: NilmEdge) -> str:
    value = str(edge.split_phase_type or "unknown").strip().casefold()
    return value or "unknown"


def _nilm_cluster_dominant_leg(edge: NilmEdge) -> str:
    split_phase_type = _nilm_cluster_split_phase_type(edge)
    if split_phase_type in {"unknown", "missing_leg_data"}:
        return split_phase_type
    return str(edge.dominant_leg or "unknown").strip().casefold() or "unknown"


def _cluster_fit_distance(
    edge: NilmEdge,
    cluster: _NilmEdgeCluster,
    *,
    policy: NilmClusteringPolicy,
) -> float | None:
    if _nilm_cluster_partition(edge) != (
        cluster.direction,
        cluster.split_phase_type,
        cluster.dominant_leg,
    ):
        return None
    distances: list[float] = []
    for name, attribute, ratio_name, floor_name in _CLUSTER_FEATURES:
        value = _nilm_cluster_feature_value(edge, attribute)
        stats = cluster.feature_stats[name]
        if value is None:
            if stats.median is not None:
                distances.append(_MISSING_FEATURE_DISTANCE_PENALTY)
            continue
        if stats.median is None:
            distances.append(_MISSING_FEATURE_DISTANCE_PENALTY)
            continue
        distance = _nilm_normalized_feature_distance(
            value,
            stats.median,
            ratio=getattr(policy, ratio_name),
            floor=getattr(policy, floor_name),
        )
        if distance > policy.max_centroid_distance:
            return None
        projected_minimum = min(stats.minimum, value)
        projected_maximum = max(stats.maximum, value)
        complete_link_distance = _nilm_normalized_feature_distance(
            projected_minimum,
            projected_maximum,
            ratio=getattr(policy, ratio_name),
            floor=getattr(policy, floor_name),
        )
        if complete_link_distance > policy.max_complete_link_distance:
            return None
        distances.append(distance)
    return sum(distances) / len(distances) if distances else None


def _missing_feature_best_fit_is_ambiguous(
    edge: NilmEdge,
    fits: list[tuple[float, _NilmEdgeCluster]],
    *,
    policy: NilmClusteringPolicy,
) -> bool:
    if len(fits) < 2 or fits[1][0] - fits[0][0] > policy.ambiguous_best_fit_margin:
        return False
    first = fits[0][1]
    second = fits[1][1]
    for name, attribute, ratio_name, floor_name in _CLUSTER_FEATURES[1:]:
        if _nilm_cluster_feature_value(edge, attribute) is not None:
            continue
        first_value = first.feature_stats[name].median
        second_value = second.feature_stats[name].median
        if first_value is None or second_value is None:
            continue
        if (
            _nilm_normalized_feature_distance(
                first_value,
                second_value,
                ratio=getattr(policy, ratio_name),
                floor=getattr(policy, floor_name),
            )
            > policy.max_centroid_distance
        ):
            return True
    return False


def _cluster_feature_stats(
    edges: Iterable[NilmEdge],
) -> dict[str, _NilmFeatureStats]:
    members = tuple(edges)
    total = len(members)
    stats: dict[str, _NilmFeatureStats] = {}
    for name, attribute, _ratio_name, _floor_name in _CLUSTER_FEATURES:
        values = sorted(
            value
            for edge in members
            if (value := _nilm_cluster_feature_value(edge, attribute)) is not None
        )
        if not values:
            stats[name] = _NilmFeatureStats(0, None, None, None, None, 0.0)
            continue
        center = float(median(values))
        stats[name] = _NilmFeatureStats(
            count=len(values),
            median=center,
            mad=float(median(abs(value - center) for value in values)),
            minimum=values[0],
            maximum=values[-1],
            coverage=len(values) / total if total else 0.0,
        )
    return stats


def _nilm_cluster_feature_value(edge: NilmEdge, attribute: str) -> float | None:
    value = _nilm_number(getattr(edge, attribute))
    return value if value is not None and isfinite(value) else None


def _nilm_normalized_feature_distance(
    first: float,
    second: float,
    *,
    ratio: float,
    floor: float,
) -> float:
    tolerance = max(floor, ratio * max(abs(first), abs(second)))
    return abs(first - second) / tolerance


def _nilm_cluster_edge_key(edge: NilmEdge) -> tuple[Any, ...]:
    return (
        *_nilm_cluster_partition(edge),
        abs(edge.delta_w),
        edge.delta_w,
        _optional_sort_key(edge.delta_var),
        _optional_sort_key(edge.delta_va),
        _optional_sort_key(edge.delta_pf),
        _optional_sort_key(edge.leg_a_delta_w),
        _optional_sort_key(edge.leg_b_delta_w),
        _optional_sort_key(edge.leg_balance_ratio),
        edge.timestamp,
        edge.origin,
        edge.parent_edge_id or "",
    )


def _nilm_cluster_sort_key(cluster: _NilmEdgeCluster) -> tuple[Any, ...]:
    return (
        cluster.direction,
        cluster.split_phase_type,
        cluster.dominant_leg,
        _optional_sort_key(cluster.feature_stats["delta_w"].median),
        _optional_sort_key(cluster.feature_stats["delta_var"].median),
        _optional_sort_key(cluster.feature_stats["delta_va"].median),
        _optional_sort_key(cluster.feature_stats["delta_pf"].median),
        _nilm_cluster_edge_key(min(cluster.members, key=_nilm_cluster_edge_key)),
    )


def _cluster_membership_key(
    clusters: Iterable[_NilmEdgeCluster],
) -> tuple[tuple[tuple[Any, ...], ...], ...]:
    return tuple(
        tuple(
            _nilm_cluster_edge_key(edge)
            for edge in sorted(cluster.members, key=_nilm_cluster_edge_key)
        )
        for cluster in sorted(clusters, key=_nilm_cluster_sort_key)
    )


def _cluster_on_off_support(
    clusters: tuple[_NilmEdgeCluster, ...],
    *,
    policy: NilmClusteringPolicy,
) -> dict[int, tuple[int, float]]:
    support: dict[int, tuple[int, float]] = {}
    used_edges: set[tuple[int, int]] = set()
    indexed = list(enumerate(clusters))
    for on_index, on_cluster in indexed:
        if on_cluster.direction != "on":
            continue
        candidates = [
            (distance, off_index, off_cluster)
            for off_index, off_cluster in indexed
            if off_cluster.direction == "off"
            if (distance := _opposite_cluster_distance(on_cluster, off_cluster, policy))
            is not None
        ]
        candidates.sort(key=lambda item: (item[0], _nilm_cluster_sort_key(item[2])))
        if not candidates or (
            len(candidates) > 1
            and candidates[1][0] - candidates[0][0] <= policy.ambiguous_best_fit_margin
        ):
            continue
        _distance, off_index, off_cluster = candidates[0]
        pairs = 0
        for member_index, on_edge in enumerate(
            sorted(on_cluster.members, key=_nilm_cluster_edge_key)
        ):
            if (on_index, member_index) in used_edges:
                continue
            available = [
                (candidate_index, off_edge)
                for candidate_index, off_edge in enumerate(
                    sorted(off_cluster.members, key=_nilm_cluster_edge_key)
                )
                if (off_index, candidate_index) not in used_edges
                if timedelta(seconds=30)
                <= off_edge.timestamp - on_edge.timestamp
                <= timedelta(hours=12)
            ]
            if not available:
                continue
            candidate_index, _off_edge = min(
                available,
                key=lambda item: (item[1].timestamp, _nilm_cluster_edge_key(item[1])),
            )
            used_edges.add((on_index, member_index))
            used_edges.add((off_index, candidate_index))
            pairs += 1
        if not pairs:
            continue
        on_support = (2.0 * pairs) / (
            len(on_cluster.members) + len(off_cluster.members)
        )
        support[id(on_cluster)] = (pairs, on_support)
        support[id(off_cluster)] = (pairs, on_support)
    return support


def _opposite_cluster_distance(
    on_cluster: _NilmEdgeCluster,
    off_cluster: _NilmEdgeCluster,
    policy: NilmClusteringPolicy,
) -> float | None:
    if (
        on_cluster.split_phase_type != off_cluster.split_phase_type
        or on_cluster.dominant_leg != off_cluster.dominant_leg
    ):
        return None
    distances: list[float] = []
    for name, _attribute, ratio_name, floor_name in _CLUSTER_FEATURES:
        on_value = on_cluster.feature_stats[name].median
        off_value = off_cluster.feature_stats[name].median
        if on_value is None or off_value is None:
            if on_value is not None or off_value is not None:
                distances.append(_MISSING_FEATURE_DISTANCE_PENALTY)
            continue
        distance = _nilm_normalized_feature_distance(
            abs(on_value),
            abs(off_value),
            ratio=getattr(policy, ratio_name),
            floor=getattr(policy, floor_name),
        )
        if distance > policy.max_centroid_distance:
            return None
        distances.append(distance)
    return sum(distances) / len(distances) if distances else None


def _signature_from_cluster(
    cluster: _NilmEdgeCluster,
    *,
    index: int,
    policy: NilmClusteringPolicy,
    day_key: Callable[[datetime], date],
    paired_occurrence_count: int,
    on_off_support: float,
) -> NilmSignature:
    stats = cluster.feature_stats
    members = tuple(cluster.members)
    day_count = len({day_key(edge.timestamp) for edge in members})
    span_seconds = (
        (
            max(edge.timestamp for edge in members)
            - min(edge.timestamp for edge in members)
        ).total_seconds()
        if len(members) > 1
        else 0.0
    )
    radii = [
        _nilm_normalized_feature_distance(
            feature.minimum,
            feature.maximum,
            ratio=getattr(policy, ratio_name),
            floor=getattr(policy, floor_name),
        )
        for name, _attribute, ratio_name, floor_name in _CLUSTER_FEATURES
        if (feature := stats[name]).minimum is not None and feature.maximum is not None
    ]
    radius = max(radii, default=0.0)
    feature_coverage = (
        sum(
            stats[name].coverage
            for name in (
                "delta_var",
                "delta_va",
                "delta_pf",
                "leg_a",
                "leg_b",
                "balance",
            )
        )
        + _cluster_topology_coverage(members)
    ) / 7.0
    topology_consistency = _cluster_topology_consistency(members)
    count_score = min(1.0, len(members) / 8.0)
    day_score = min(1.0, day_count / 4.0)
    span_score = min(1.0, span_seconds / timedelta(days=7).total_seconds())
    dispersion_score = max(0.0, 1.0 - radius)
    data_quality_score = (feature_coverage + topology_consistency) / 2.0
    evidence_strength = (0.5 * count_score) + (0.4 * day_score) + (0.1 * span_score)
    model_fit = (0.7 * dispersion_score) + (0.3 * data_quality_score)
    intrinsic_confidence = (
        (0.25 * count_score)
        + (0.20 * day_score)
        + (0.05 * span_score)
        + (0.25 * dispersion_score)
        + (0.10 * data_quality_score)
        + (0.15 * on_off_support)
    )
    if day_count <= 1:
        intrinsic_confidence = min(intrinsic_confidence, 0.65)
    if on_off_support <= 0.0:
        intrinsic_confidence = min(intrinsic_confidence, 0.75)
    intrinsic_confidence = min(intrinsic_confidence, 0.95)
    return NilmSignature(
        signature_id=f"{cluster.direction}-{index}",
        median_delta_w=round(stats["delta_w"].median or 0.0, 3),
        median_delta_var=_round_optional(stats["delta_var"].median),
        median_delta_va=_round_optional(stats["delta_va"].median),
        median_delta_pf=_round_optional(stats["delta_pf"].median),
        occurrence_count=len(members),
        confidence=round(min(intrinsic_confidence, 0.90), 3),
        median_leg_a_delta_w=_round_optional(stats["leg_a"].median),
        median_leg_b_delta_w=_round_optional(stats["leg_b"].median),
        leg_balance_ratio=_round_optional(stats["balance"].median),
        dominant_leg=cluster.dominant_leg,
        split_phase_type=cluster.split_phase_type,
        unique_day_count=day_count,
        observation_span_seconds=round(span_seconds, 3),
        dispersion_w=round(stats["delta_w"].mad or 0.0, 3),
        dispersion_var=_round_optional(stats["delta_var"].mad),
        dispersion_va=_round_optional(stats["delta_va"].mad),
        dispersion_pf=_round_optional(stats["delta_pf"].mad),
        normalized_cluster_radius=round(radius, 3),
        feature_coverage=round(feature_coverage, 3),
        topology_consistency=round(topology_consistency, 3),
        paired_occurrence_count=paired_occurrence_count,
        on_off_support=round(on_off_support, 3),
        evidence_strength=round(evidence_strength, 3),
        model_fit=round(model_fit, 3),
        intrinsic_confidence=round(intrinsic_confidence, 3),
        confidence_kind="evidence",
    )


def _cluster_topology_consistency(edges: Iterable[NilmEdge]) -> float:
    values = [
        (_nilm_cluster_split_phase_type(edge), _nilm_cluster_dominant_leg(edge))
        for edge in edges
    ]
    if not values:
        return 0.0
    return max(values.count(value) for value in set(values)) / len(values)


def _cluster_topology_coverage(edges: Iterable[NilmEdge]) -> float:
    values = tuple(edges)
    if not values:
        return 0.0
    return sum(
        _nilm_cluster_split_phase_type(edge) not in {"unknown", "missing_leg_data"}
        for edge in values
    ) / len(values)


def classify_signature(signature: NilmSignature) -> str:
    """Return a deliberately non-definitive label for a recurring signature."""

    if signature.user_label:
        return signature.user_label

    abs_w = abs(signature.median_delta_w)
    abs_var = (
        abs(signature.median_delta_var)
        if signature.median_delta_var is not None
        else None
    )
    abs_va = (
        abs(signature.median_delta_va)
        if signature.median_delta_va is not None
        else None
    )
    abs_pf = (
        abs(signature.median_delta_pf)
        if signature.median_delta_pf is not None
        else None
    )
    reactive_ratio = abs_var / max(abs_w, 1.0) if abs_var is not None else None

    if (
        abs_var is not None
        and abs_pf is not None
        and abs_pf <= 0.08
        and abs_w >= 200
        and reactive_ratio is not None
        and reactive_ratio <= 0.12
    ):
        return _split_phase_label(signature, "resistive load")
    if (
        abs_var is not None
        and abs_w >= 200
        and reactive_ratio is not None
        and reactive_ratio >= 0.3
    ):
        return _split_phase_label(signature, "motor-like load")
    if (
        abs_var is not None
        and abs_va is not None
        and abs_va >= 100
        and reactive_ratio is not None
        and reactive_ratio >= 0.75
    ):
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
        and not nilm_signature_is_off_direction(spec.get("direction"))
        and not nilm_signature_is_off_direction(_nilm_session_spec_fingerprint(spec))
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
        if expected is None or edge_value is None:
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


def _signature_direction(signature_id: str) -> str:
    direction = str(signature_id).split("-", 1)[0].strip().lower()
    return direction if direction in {"on", "off"} else "unknown"


def _abs_value_bucket(value: float, step: float) -> str:
    bucket_start = (abs(float(value)) // step) * step
    bucket_end = bucket_start + step
    if step >= 1.0:
        return f"{bucket_start:.0f}-{bucket_end:.0f}"
    return f"{bucket_start:.2f}-{bucket_end:.2f}"


def _optional_value_bucket(value: float | None, step: float) -> str:
    return "unknown" if value is None else _abs_value_bucket(value, step)


def _optional_value_bucket_v2(value: float | None, step: float) -> str:
    """Return a v2 bucket without losing 0.025 PF precision."""
    if value is None:
        return "unknown"
    bucket_start = (abs(float(value)) // step) * step
    bucket_end = bucket_start + step
    if step >= 1.0:
        return f"{bucket_start:.0f}-{bucket_end:.0f}"
    precision = 3 if step < 0.05 else 2
    return f"{bucket_start:.{precision}f}-{bucket_end:.{precision}f}"


def _optional_sort_key(value: float | None) -> tuple[int, float]:
    return (value is None, float(value or 0.0))


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
    estimate = _event_power_estimate(event)
    return estimate.magnitude_w if estimate is not None else None


def _event_power_estimate(event: CircuitEvent) -> KnownEventPowerEstimate | None:
    """Select the transition delta first, then retain legacy power precedence."""

    signed_delta_w = _finite_event_feature_number(event, "transition_delta_w")
    if event.event_type is EventType.POWER_TRANSITION:
        if signed_delta_w is None or signed_delta_w == 0.0:
            return None
        return KnownEventPowerEstimate(
            abs(signed_delta_w),
            signed_delta_w,
            "transition_delta_w",
            _optional_nonnegative_event_feature_number(event, "transition_spread_w"),
            _event_feature_datetime(event, "transition_timestamp"),
            _optional_nonnegative_event_feature_number(
                event, "transition_timing_uncertainty_s"
            ),
        )
    if signed_delta_w is not None and (
        event.event_type is EventType.START
        and signed_delta_w > 0.0
        or event.event_type is EventType.STOP
        and signed_delta_w < 0.0
    ):
        source = "transition_delta_w"
    else:
        legacy_power = _event_power_w_with_source(event)
        if legacy_power is None:
            return None
        magnitude_w, source = legacy_power
        signed_delta_w = None
        return KnownEventPowerEstimate(
            magnitude_w,
            signed_delta_w,
            source,
            _optional_nonnegative_event_feature_number(event, "transition_spread_w"),
            _event_feature_datetime(event, "transition_timestamp"),
            _optional_nonnegative_event_feature_number(
                event, "transition_timing_uncertainty_s"
            ),
        )

    return KnownEventPowerEstimate(
        abs(signed_delta_w),
        signed_delta_w,
        source,
        _optional_nonnegative_event_feature_number(event, "transition_spread_w"),
        _event_feature_datetime(event, "transition_timestamp"),
        _optional_nonnegative_event_feature_number(
            event, "transition_timing_uncertainty_s"
        ),
    )


def _finite_event_feature_number(event: CircuitEvent, key: str) -> float | None:
    try:
        value = float(event.features.get(key))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _optional_nonnegative_event_feature_number(
    event: CircuitEvent, key: str
) -> float | None:
    value = _finite_event_feature_number(event, key)
    return value if value is not None and value >= 0.0 else None


def _event_feature_datetime(event: CircuitEvent, key: str) -> datetime | None:
    value = event.features.get(key)
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _known_event_time_distance(
    event: CircuitEvent, edge_timestamp: datetime
) -> tuple[float, float]:
    """Return distance and signed offset using a valid transition interval."""

    window_start = _event_feature_datetime(event, "transition_window_start")
    window_end = _event_feature_datetime(event, "transition_window_end")
    if window_start is not None and window_end is not None:
        try:
            if window_end >= window_start:
                if window_start <= edge_timestamp <= window_end:
                    return 0.0, 0.0
                boundary = window_start if edge_timestamp < window_start else window_end
                time_offset_seconds = (boundary - edge_timestamp).total_seconds()
                return abs(time_offset_seconds), time_offset_seconds
        except TypeError:
            pass
    time_offset_seconds = (event.timestamp - edge_timestamp).total_seconds()
    return abs(time_offset_seconds), time_offset_seconds


def _event_power_w_with_source(event: CircuitEvent) -> tuple[float, str] | None:
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
            try:
                watts = abs(float(value))
            except (TypeError, ValueError):
                continue
            if isfinite(watts) and watts > 0:
                return watts, key
    return None


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
        on_delta_var=_round_optional(on_edge.delta_var),
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
        on_delta_var=_round_optional(on_edge.delta_var),
        off_delta_var=_round_optional(off_edge.delta_var),
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
        if value is None or reference is None:
            continue
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
    value: float | None,
    reference: float | None,
    *,
    tolerance_ratio: float,
    floor: float,
) -> float | None:
    if value is None or reference is None:
        return None
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
        and _nilm_sessions_compete(session, other)
        and _nilm_sessions_overlap(session, other, latest_seen=latest_seen)
    )
    if overlap_count == 0:
        return session
    return replace(
        session,
        overlap_count=overlap_count,
        confidence=round(_clamp(session.confidence * (0.9**overlap_count)), 3),
    )


def _nilm_sessions_compete(left: NilmSession, right: NilmSession) -> bool:
    if left.assignment_id and right.assignment_id:
        return left.assignment_id == right.assignment_id
    return left.signature_fingerprint == right.signature_fingerprint


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
    fields = (
        edge.direction,
        edge.timestamp.isoformat(),
        f"w={edge.delta_w:.3f}",
        f"var={_optional_number_text(edge.delta_var)}",
        edge.split_phase_type,
        edge.dominant_leg,
    )
    if edge.origin != "aggregate":
        fields += (
            f"origin={edge.origin}",
            f"parent={edge.parent_edge_id or 'none'}",
            "explained=" + ",".join(edge.explained_known_circuit_ids),
        )
    return "|".join(fields)


def _optional_number_text(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.3f}"


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
