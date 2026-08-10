"""Deterministic one-to-one temporal matching for NILM validation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class NilmValidationPolicy:
    """Conservative temporal gates for history-based NILM validation."""

    min_iou: float = 0.50
    min_ground_truth_coverage: float = 0.70
    min_prediction_coverage: float = 0.50
    min_boundary_tolerance_seconds: float = 60.0
    max_boundary_tolerance_seconds: float = 900.0
    min_validation_window_coverage: float = 0.50


@dataclass(frozen=True, slots=True)
class NilmTemporalMatch:
    """One selected temporal prediction-to-ground-truth match."""

    session_id: str
    interval_id: str
    score: float
    iou: float
    overlap_seconds: float
    ground_truth_coverage: float
    prediction_coverage: float
    start_error_seconds: float
    end_error_seconds: float
    duration_error_seconds: float


@dataclass(frozen=True, slots=True)
class NilmValidationMatchResult:
    """The deterministic result of matching a validation history."""

    matches: tuple[NilmTemporalMatch, ...]
    false_positive_session_ids: tuple[str, ...]
    false_negative_interval_ids: tuple[str, ...]
    unevaluated_session_ids: tuple[str, ...]
    skipped_session_ids: tuple[str, ...]
    skipped_interval_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _NormalizedInterval:
    """Validated immutable temporal source data used only by the matcher."""

    stable_id: str
    start: datetime
    end: datetime
    power_w: float | None
    energy_kwh: float | None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def sort_key(self) -> tuple[datetime, datetime, str]:
        return self.start, self.end, self.stable_id


@dataclass(frozen=True, slots=True)
class _MatchingPlan:
    """Aggregate DP state with an order-independent deterministic rank."""

    matches: tuple[NilmTemporalMatch, ...] = ()
    total_score: float = 0.0
    total_iou: float = 0.0
    total_boundary_error: float = 0.0

    def with_match(self, match: NilmTemporalMatch) -> _MatchingPlan:
        return _MatchingPlan(
            matches=(match, *self.matches),
            total_score=self.total_score + match.score,
            total_iou=self.total_iou + match.iou,
            total_boundary_error=(
                self.total_boundary_error
                + match.start_error_seconds
                + match.end_error_seconds
            ),
        )

    @property
    def rank(self) -> tuple[float, int, float, float, tuple[tuple[str, str], ...]]:
        """Return the lexicographically comparable inverse preference tuple."""
        return (
            -round(self.total_score, 9),
            -len(self.matches),
            -round(self.total_iou, 9),
            round(self.total_boundary_error, 9),
            tuple((match.session_id, match.interval_id) for match in self.matches),
        )


def match_nilm_validation_intervals(
    sessions: Iterable[Mapping[str, Any]],
    intervals: Iterable[Mapping[str, Any]],
    *,
    circuit_id: str,
    policy: NilmValidationPolicy | None = None,
) -> NilmValidationMatchResult:
    """Match completed NILM sessions to ground truth without temporal bridging.

    Inputs are copied into immutable normalized values before matching.  Invalid
    or open sessions and invalid intervals are surfaced as skipped IDs; valid
    predictions outside sufficiently covered validation windows are unevaluated.
    """
    resolved_policy = policy or NilmValidationPolicy()
    normalized_sessions, skipped_session_ids = _normalize_sessions(sessions)
    normalized_intervals, skipped_interval_ids = _normalize_intervals(
        intervals,
        circuit_id=circuit_id,
    )
    coverage_windows = _merge_coverage_windows(normalized_intervals)
    plan = _maximum_score_non_crossing_matches(
        normalized_sessions,
        normalized_intervals,
        policy=resolved_policy,
    )
    selected_session_ids = {match.session_id for match in plan.matches}
    selected_interval_ids = {match.interval_id for match in plan.matches}

    false_positive_ids: list[str] = []
    unevaluated_ids: list[str] = []
    for session in normalized_sessions:
        if session.stable_id in selected_session_ids:
            continue
        coverage = _coverage_fraction(session, coverage_windows)
        if coverage >= resolved_policy.min_validation_window_coverage:
            false_positive_ids.append(session.stable_id)
        else:
            unevaluated_ids.append(session.stable_id)

    return NilmValidationMatchResult(
        matches=plan.matches,
        false_positive_session_ids=tuple(false_positive_ids),
        false_negative_interval_ids=tuple(
            interval.stable_id
            for interval in normalized_intervals
            if interval.stable_id not in selected_interval_ids
        ),
        unevaluated_session_ids=tuple(unevaluated_ids),
        skipped_session_ids=tuple(sorted(set(skipped_session_ids))),
        skipped_interval_ids=tuple(sorted(set(skipped_interval_ids))),
    )


def nilm_validation_interval_id(
    interval: Mapping[str, Any],
    *,
    circuit_id: str,
) -> str | None:
    """Return a durable ground-truth ID, including the legacy fallback."""
    interval_id = str(interval.get("interval_id") or "").strip()
    if interval_id:
        return interval_id
    entity_id = str(interval.get("ground_truth_entity_id") or "").strip()
    start = _parse_datetime(interval.get("start"))
    end = _parse_datetime(interval.get("end"))
    if not entity_id or start is None or end is None:
        return None
    return _legacy_interval_id(circuit_id, entity_id, start, end)


def _normalize_sessions(
    sessions: Iterable[Mapping[str, Any]],
) -> tuple[tuple[_NormalizedInterval, ...], tuple[str, ...]]:
    normalized: list[_NormalizedInterval] = []
    skipped_ids: list[str] = []
    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            continue
        if _session_is_open(session):
            skipped_ids.append(session_id)
            continue
        start = _parse_datetime(session.get("start"))
        end = _parse_datetime(session.get("end"))
        if start is None or end is None or end <= start:
            skipped_ids.append(session_id)
            continue
        normalized.append(
            _NormalizedInterval(
                stable_id=session_id,
                start=start,
                end=end,
                power_w=_optional_float(session.get("median_power_w")),
                energy_kwh=_optional_float(session.get("estimated_energy_kwh")),
            )
        )
    return _deduplicate_intervals(normalized), tuple(skipped_ids)


def _normalize_intervals(
    intervals: Iterable[Mapping[str, Any]],
    *,
    circuit_id: str,
) -> tuple[tuple[_NormalizedInterval, ...], tuple[str, ...]]:
    normalized: list[_NormalizedInterval] = []
    skipped_ids: list[str] = []
    for interval in intervals:
        source_id = str(interval.get("interval_id") or "").strip()
        entity_id = str(interval.get("ground_truth_entity_id") or "").strip()
        start = _parse_datetime(interval.get("start"))
        end = _parse_datetime(interval.get("end"))
        stable_id = source_id or _invalid_interval_id(
            circuit_id,
            entity_id,
            interval.get("start"),
            interval.get("end"),
        )
        if not entity_id or start is None or end is None or end <= start:
            skipped_ids.append(stable_id)
            continue
        stable_id = source_id or _legacy_interval_id(circuit_id, entity_id, start, end)
        coverage_start, coverage_end = _normalized_coverage(interval, start, end)
        normalized.append(
            _NormalizedInterval(
                stable_id=stable_id,
                start=start,
                end=end,
                power_w=_optional_float(interval.get("median_power_w")),
                energy_kwh=_optional_float(
                    interval.get(
                        "measured_energy_kwh",
                        interval.get("estimated_energy_kwh"),
                    )
                ),
                coverage_start=coverage_start,
                coverage_end=coverage_end,
            )
        )
    return _deduplicate_intervals(normalized), tuple(skipped_ids)


def _session_is_open(session: Mapping[str, Any]) -> bool:
    return bool(
        session.get("open") is True
        or session.get("is_open") is True
        or str(session.get("status") or "").strip().casefold() == "open"
        or not session.get("end")
    )


def _normalized_coverage(
    interval: Mapping[str, Any],
    start: datetime,
    end: datetime,
) -> tuple[datetime, datetime]:
    coverage_start = _parse_datetime(interval.get("validation_start")) or start
    coverage_end = _parse_datetime(interval.get("validation_end")) or end
    if coverage_end <= coverage_start:
        return start, end
    return coverage_start, coverage_end


def _deduplicate_intervals(
    intervals: Iterable[_NormalizedInterval],
) -> tuple[_NormalizedInterval, ...]:
    deduplicated: dict[str, _NormalizedInterval] = {}
    for interval in sorted(intervals, key=lambda value: value.sort_key):
        deduplicated.setdefault(interval.stable_id, interval)
    return tuple(sorted(deduplicated.values(), key=lambda value: value.sort_key))


def _maximum_score_non_crossing_matches(
    sessions: tuple[_NormalizedInterval, ...],
    intervals: tuple[_NormalizedInterval, ...],
    *,
    policy: NilmValidationPolicy,
) -> _MatchingPlan:
    rows = len(sessions)
    columns = len(intervals)
    states = [
        [_MatchingPlan() for _ in range(columns + 1)] for _ in range(rows + 1)
    ]
    for session_index in range(rows - 1, -1, -1):
        for interval_index in range(columns - 1, -1, -1):
            candidates = [
                states[session_index + 1][interval_index],
                states[session_index][interval_index + 1],
            ]
            match = _temporal_match(
                sessions[session_index],
                intervals[interval_index],
                policy=policy,
            )
            if match is not None:
                candidates.append(
                    states[session_index + 1][interval_index + 1].with_match(match)
                )
            states[session_index][interval_index] = min(
                candidates,
                key=lambda candidate: candidate.rank,
            )
    return states[0][0]


def _temporal_match(
    session: _NormalizedInterval,
    interval: _NormalizedInterval,
    *,
    policy: NilmValidationPolicy,
) -> NilmTemporalMatch | None:
    overlap_seconds = _overlap_seconds(
        session.start,
        session.end,
        interval.start,
        interval.end,
    )
    if overlap_seconds <= 0:
        return None
    session_duration = session.duration_seconds
    interval_duration = interval.duration_seconds
    union_seconds = (
        max(session.end, interval.end) - min(session.start, interval.start)
    ).total_seconds()
    iou = overlap_seconds / union_seconds
    ground_truth_coverage = overlap_seconds / interval_duration
    prediction_coverage = overlap_seconds / session_duration
    start_error = abs((session.start - interval.start).total_seconds())
    end_error = abs((session.end - interval.end).total_seconds())
    duration_error = abs(session_duration - interval_duration)
    tolerance = min(
        policy.max_boundary_tolerance_seconds,
        max(policy.min_boundary_tolerance_seconds, interval_duration * 0.5),
    )
    if (
        iou < policy.min_iou
        or ground_truth_coverage < policy.min_ground_truth_coverage
        or prediction_coverage < policy.min_prediction_coverage
        or start_error > tolerance
        or end_error > tolerance
    ):
        return None
    start_score = max(0.0, 1.0 - (start_error / tolerance))
    end_score = max(0.0, 1.0 - (end_error / tolerance))
    score = (0.70 * iou) + (0.30 * ((start_score + end_score) / 2.0))
    return NilmTemporalMatch(
        session_id=session.stable_id,
        interval_id=interval.stable_id,
        score=score,
        iou=iou,
        overlap_seconds=overlap_seconds,
        ground_truth_coverage=ground_truth_coverage,
        prediction_coverage=prediction_coverage,
        start_error_seconds=start_error,
        end_error_seconds=end_error,
        duration_error_seconds=duration_error,
    )


def _merge_coverage_windows(
    intervals: Iterable[_NormalizedInterval],
) -> tuple[tuple[datetime, datetime], ...]:
    windows = sorted(
        (
            (interval.coverage_start, interval.coverage_end)
            for interval in intervals
            if interval.coverage_start is not None and interval.coverage_end is not None
        ),
        key=lambda window: window[0],
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in windows:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _coverage_fraction(
    session: _NormalizedInterval,
    coverage_windows: Iterable[tuple[datetime, datetime]],
) -> float:
    covered_seconds = sum(
        _overlap_seconds(session.start, session.end, start, end)
        for start, end in coverage_windows
    )
    return covered_seconds / session.duration_seconds


def _overlap_seconds(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> float:
    overlap_end = min(first_end, second_end)
    overlap_start = max(first_start, second_start)
    return max(0.0, (overlap_end - overlap_start).total_seconds())


def _legacy_interval_id(
    circuit_id: str,
    entity_id: str,
    start: datetime,
    end: datetime,
) -> str:
    seed = "|".join((circuit_id, entity_id, start.isoformat(), end.isoformat()))
    return f"legacy:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _invalid_interval_id(
    circuit_id: str,
    entity_id: str,
    start: Any,
    end: Any,
) -> str:
    seed = "|".join((circuit_id, entity_id, str(start or ""), str(end or "")))
    return f"invalid:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
