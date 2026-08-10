"""Pure, deterministic evidence extraction for manually selected NILM intervals."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from statistics import median


@dataclass(frozen=True)
class NilmEvidenceThresholds:
    """Bounded tuning values shared by normalization and extraction."""

    minimum_context_seconds: float = 10.0
    maximum_context_seconds: float = 60.0
    context_interval_fraction: float = 0.2
    minimum_transition_w: float = 50.0
    maximum_source_skew_seconds: float = 15.0
    minimum_freshness_seconds: float = 15.0
    maximum_freshness_seconds: float = 300.0
    freshness_cadence_multiplier: float = 3.0
    complete_energy_coverage: float = 0.95
    numerical_noise_w: float = 2.0
    minimum_boundary_coverage: float = 0.75
    maximum_boundary_spread_w: float = 100.0
    maximum_boundary_gap_seconds: float = 60.0


DEFAULT_THRESHOLDS = NilmEvidenceThresholds()
MAX_REFERENCE_DURATION_SECONDS = 86_400.0


class ReferenceActivityState(StrEnum):
    """The only states a reference-history row may contribute."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NilmReferenceExtractionSettings:
    on_threshold: float | None
    off_threshold: float | None
    on_dwell_seconds: float = 0.0
    off_dwell_seconds: float = 0.0
    minimum_interval_seconds: float = 0.0
    merge_gap_seconds: float = 0.0
    maximum_unknown_gap_seconds: float = 0.0
    maximum_power_gap_seconds: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.on_dwell_seconds,
            self.off_dwell_seconds,
            self.minimum_interval_seconds,
            self.merge_gap_seconds,
            self.maximum_unknown_gap_seconds,
        )
        if any(
            not isfinite(value) or not 0 <= value <= MAX_REFERENCE_DURATION_SECONDS
            for value in values
        ):
            raise ValueError("reference durations must be finite and bounded")
        if (self.on_threshold is None) != (self.off_threshold is None):
            raise ValueError("reference thresholds must be configured together")
        if self.on_threshold is not None and (
            not isfinite(self.on_threshold)
            or self.on_threshold < 0
            or not isfinite(self.off_threshold)  # type: ignore[arg-type]
            or self.off_threshold < 0  # type: ignore[operator]
            or self.off_threshold > self.on_threshold  # type: ignore[operator]
        ):
            raise ValueError("reference thresholds must be non-negative and ordered")
        if self.maximum_power_gap_seconds is not None and (
            not isfinite(self.maximum_power_gap_seconds)
            or not 0 <= self.maximum_power_gap_seconds <= MAX_REFERENCE_DURATION_SECONDS
        ):
            raise ValueError("maximum power gap must be finite and non-negative")


@dataclass(frozen=True)
class NilmReferenceSample:
    timestamp: datetime
    value: object
    state: ReferenceActivityState
    numeric_value: float | None


@dataclass(frozen=True)
class NilmReferenceInterval:
    start: datetime
    end: datetime
    start_boundary_uncertainty_seconds: float | None
    end_boundary_uncertainty_seconds: float | None
    left_censored: bool
    right_censored: bool
    state_coverage: float
    unknown_duration_seconds: float
    merged_gap_count: int
    evidence_confidence: float
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class NilmReferenceDiagnostics:
    discarded_minimum_duration: int = 0
    bridged_unknown_gap_count: int = 0
    merged_inactive_gap_count: int = 0
    candidate_interval_count: int = 0
    imported_interval_count: int = 0
    low_coverage_interval_count: int = 0

    @property
    def discarded_short_interval_count(self) -> int:
        return self.discarded_minimum_duration

    @property
    def merged_short_gap_count(self) -> int:
        return self.merged_inactive_gap_count


@dataclass(frozen=True)
class NilmReferenceExtractionResult:
    intervals: tuple[NilmReferenceInterval, ...]
    diagnostics: NilmReferenceDiagnostics


def normalize_reference_samples(
    rows: Iterable[tuple[datetime, object]],
) -> tuple[NilmReferenceSample, ...]:
    """Sort rows and retain the final duplicate timestamp without guessing state."""
    latest: dict[datetime, tuple[int, NilmReferenceSample]] = {}
    for index, (timestamp, value) in enumerate(rows):
        state, numeric = _reference_value(value)
        latest[timestamp] = (
            index,
            NilmReferenceSample(timestamp, value, state, numeric),
        )
    return tuple(
        item[1]
        for item in sorted(
            latest.values(), key=lambda item: (item[1].timestamp, item[0])
        )
    )


def extract_reference_intervals(
    rows: Iterable[tuple[datetime, object]],
    *,
    start: datetime,
    end: datetime,
    settings: NilmReferenceExtractionSettings,
) -> NilmReferenceExtractionResult:
    """Extract bounded, dwell-confirmed active intervals from reference history."""
    if end <= start:
        raise ValueError("end must be after start")
    samples = tuple(
        sample
        for sample in normalize_reference_samples(rows)
        if start <= sample.timestamp <= end
    )
    if not samples:
        return NilmReferenceExtractionResult((), NilmReferenceDiagnostics())
    active = False
    candidate: ReferenceActivityState | None = None
    candidate_at: datetime | None = None
    interval_start: datetime | None = None
    left_censored = False
    unknown_at: datetime | None = None
    unknown_total = 0.0
    bridged = 0
    raw: list[tuple[datetime, datetime, bool, bool, float, int, set[str]]] = []
    previous: NilmReferenceSample | None = None
    for sample in samples:
        prior = previous
        previous = sample
        state = _resolved_reference_state(sample, active, settings)
        if state is ReferenceActivityState.UNKNOWN:
            unknown_at = unknown_at or sample.timestamp
            if (
                active
                and (sample.timestamp - unknown_at).total_seconds()
                > settings.maximum_unknown_gap_seconds
            ):
                raw.append(
                    (
                        interval_start or start,
                        unknown_at,
                        left_censored,
                        False,
                        unknown_total,
                        0,
                        {"unknown_gap_split"},
                    )
                )
                active, interval_start, candidate, candidate_at = (
                    False,
                    None,
                    None,
                    None,
                )
            continue
        if unknown_at is not None:
            gap = (sample.timestamp - unknown_at).total_seconds()
            if active and gap <= settings.maximum_unknown_gap_seconds:
                unknown_total += gap
                bridged += 1
            elif active:
                raw.append(
                    (
                        interval_start or start,
                        unknown_at,
                        left_censored,
                        False,
                        unknown_total,
                        0,
                        {"unknown_gap_split"},
                    )
                )
                active, interval_start, candidate, candidate_at = (
                    False,
                    None,
                    None,
                    None,
                )
            unknown_at = None
        if state is (
            ReferenceActivityState.ACTIVE if active else ReferenceActivityState.INACTIVE
        ):
            candidate, candidate_at = None, None
            continue
        dwell = (
            settings.on_dwell_seconds
            if state is ReferenceActivityState.ACTIVE
            else settings.off_dwell_seconds
        )
        if candidate is not state:
            candidate = state
            candidate_at, _ = _interpolated_transition_boundary(
                prior, sample, state, settings
            )
            if sample.timestamp == start and state is ReferenceActivityState.ACTIVE:
                active, interval_start, left_censored = True, start, True
            continue
        assert candidate_at is not None
        if (sample.timestamp - candidate_at).total_seconds() < dwell:
            continue
        if state is ReferenceActivityState.ACTIVE:
            active, interval_start, left_censored = True, candidate_at, False
        elif active:
            raw.append(
                (
                    interval_start or start,
                    candidate_at,
                    left_censored,
                    False,
                    unknown_total,
                    0,
                    set(),
                )
            )
            active, interval_start, unknown_total = False, None, 0.0
        candidate, candidate_at = None, None
    if active:
        raw.append(
            (
                interval_start or start,
                end,
                left_censored,
                True,
                unknown_total,
                0,
                {"right_censored"},
            )
        )
    merged: list[tuple[datetime, datetime, bool, bool, float, int, set[str]]] = []
    merged_count = 0
    for item in raw:
        if (
            merged
            and (item[0] - merged[-1][1]).total_seconds() <= settings.merge_gap_seconds
        ):
            previous = merged.pop()
            merged_count += 1
            merged.append(
                (
                    previous[0],
                    item[1],
                    previous[2],
                    item[3],
                    previous[4] + item[4],
                    previous[5] + item[5] + 1,
                    previous[6] | item[6] | {"inactive_gap_merged"},
                )
            )
        else:
            merged.append(item)
    intervals: list[NilmReferenceInterval] = []
    discarded = 0
    for interval_start, interval_end, left, right, unknown, gap_count, flags in merged:
        interval_duration = (interval_end - interval_start).total_seconds()
        if interval_duration < settings.minimum_interval_seconds:
            discarded += 1
            continue
        coverage = max(0.0, min(1.0, 1 - unknown / interval_duration))
        confidence = coverage * (0.85 if left or right else 1.0) * (0.9**gap_count)
        intervals.append(
            NilmReferenceInterval(
                interval_start,
                interval_end,
                _boundary_uncertainty(
                    samples, interval_start, settings.on_threshold, settings
                ),
                _boundary_uncertainty(
                    samples, interval_end, settings.off_threshold, settings
                ),
                left,
                right,
                coverage,
                unknown,
                gap_count,
                max(0.0, min(1.0, confidence)),
                tuple(sorted(flags)),
            )
        )
    return NilmReferenceExtractionResult(
        tuple(intervals),
        NilmReferenceDiagnostics(
            discarded_minimum_duration=discarded,
            bridged_unknown_gap_count=bridged,
            merged_inactive_gap_count=merged_count,
            candidate_interval_count=len(merged),
            imported_interval_count=len(intervals),
            low_coverage_interval_count=sum(
                interval.state_coverage < 1.0 for interval in intervals
            ),
        ),
    )


def _reference_value(value: object) -> tuple[ReferenceActivityState, float | None]:
    if isinstance(value, bool):
        return (
            ReferenceActivityState.ACTIVE if value else ReferenceActivityState.INACTIVE
        ), None
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    ):
        return ReferenceActivityState.UNKNOWN, float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"on", "true", "active"}:
            return ReferenceActivityState.ACTIVE, None
        if text in {"off", "false", "inactive"}:
            return ReferenceActivityState.INACTIVE, None
    return ReferenceActivityState.UNKNOWN, None


def _resolved_reference_state(
    sample: NilmReferenceSample, active: bool, settings: NilmReferenceExtractionSettings
) -> ReferenceActivityState:
    if sample.numeric_value is None:
        return sample.state
    if settings.on_threshold is None:
        return ReferenceActivityState.UNKNOWN
    if sample.numeric_value >= settings.on_threshold:
        return ReferenceActivityState.ACTIVE
    if sample.numeric_value <= settings.off_threshold:  # type: ignore[operator]
        return ReferenceActivityState.INACTIVE
    return ReferenceActivityState.ACTIVE if active else ReferenceActivityState.INACTIVE


def _interpolated_transition_boundary(
    previous: NilmReferenceSample | None,
    current: NilmReferenceSample,
    state: ReferenceActivityState,
    settings: NilmReferenceExtractionSettings,
) -> tuple[datetime, float | None]:
    """Return a threshold crossing only when adjacent numeric data supports it."""
    threshold = (
        settings.on_threshold
        if state is ReferenceActivityState.ACTIVE
        else settings.off_threshold
    )
    if (
        previous is None
        or threshold is None
        or previous.numeric_value is None
        or current.numeric_value is None
    ):
        return current.timestamp, None
    span = (current.timestamp - previous.timestamp).total_seconds()
    maximum_span = settings.maximum_power_gap_seconds
    if maximum_span is None:
        maximum_span = max(60.0, settings.maximum_unknown_gap_seconds)
    low, high = sorted((previous.numeric_value, current.numeric_value))
    if span <= 0 or span > maximum_span or not low <= threshold <= high or low == high:
        return current.timestamp, min(max(span, 0.0), maximum_span) / 2
    from datetime import timedelta

    fraction = (threshold - previous.numeric_value) / (
        current.numeric_value - previous.numeric_value
    )
    return previous.timestamp + timedelta(seconds=span * fraction), span / 2


def _boundary_uncertainty(
    samples: Sequence[NilmReferenceSample],
    boundary: datetime,
    threshold: float | None,
    settings: NilmReferenceExtractionSettings,
) -> float | None:
    if threshold is None:
        return None
    for previous, current in zip(samples, samples[1:], strict=False):
        candidate, uncertainty = _interpolated_transition_boundary(
            previous,
            current,
            (
                ReferenceActivityState.ACTIVE
                if current.numeric_value is not None
                and current.numeric_value >= threshold
                else ReferenceActivityState.INACTIVE
            ),
            settings,
        )
        if candidate == boundary:
            return uncertainty
    return None


@dataclass(frozen=True)
class NilmPowerSample:
    timestamp: datetime
    value_w: float | None
    source_entity_id: str
    quality: str = "valid"
    unit: str = "W"


@dataclass(frozen=True)
class NilmAggregatePoint:
    timestamp: datetime
    power_w: float | None
    source_count: int
    fresh_source_count: int
    source_skew_seconds: float | None
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class NilmIntervalEvidence:
    start: datetime
    end: datetime
    start_transition_w: float | None
    stop_transition_w: float | None
    net_plateau_power_w: float | None
    average_power_w: float | None
    measured_energy_kwh: float | None
    partial_energy_kwh: float | None
    start_boundary_uncertainty_seconds: float | None
    end_boundary_uncertainty_seconds: float | None
    source_coverage: float
    power_coverage: float
    maximum_source_skew_seconds: float | None
    longest_power_gap_seconds: float | None
    start_transition_eligible: bool
    stop_transition_eligible: bool
    plateau_eligible: bool
    energy_complete: bool
    evidence_confidence: float
    power_confidence: float
    interior_transition_count: int
    largest_interior_transition_w: float | None
    quality_flags: tuple[str, ...]


def normalize_power_samples(
    samples: Iterable[NilmPowerSample],
) -> tuple[NilmPowerSample, ...]:
    """Normalize units, retain missing boundaries, and keep the last duplicate."""
    latest: dict[tuple[str, datetime], tuple[int, NilmPowerSample]] = {}
    for index, sample in enumerate(samples):
        unit = sample.unit.strip().lower()
        factor = {
            "w": 1.0,
            "watt": 1.0,
            "watts": 1.0,
            "kw": 1000.0,
            "kilowatt": 1000.0,
        }.get(unit)
        value = sample.value_w
        quality = sample.quality
        if factor is None:
            value, quality = None, "invalid"
        elif value is not None:
            value *= factor
            if not isfinite(value):
                value, quality = None, "invalid"
        latest[(sample.source_entity_id, sample.timestamp)] = (
            index,
            NilmPowerSample(
                sample.timestamp, value, sample.source_entity_id, quality, "W"
            ),
        )
    return tuple(
        item[1]
        for item in sorted(
            latest.values(),
            key=lambda item: (item[1].timestamp, item[1].source_entity_id, item[0]),
        )
    )


def aggregate_power_samples(
    samples: Iterable[NilmPowerSample],
    *,
    source_entity_ids: Sequence[str] | None = None,
    thresholds: NilmEvidenceThresholds = DEFAULT_THRESHOLDS,
) -> tuple[NilmAggregatePoint, ...]:
    """Sum synchronized fresh legs; missing/stale legs are explicit gaps, never zero."""
    normalized = normalize_power_samples(samples)
    sources = tuple(
        source_entity_ids or tuple(sorted({s.source_entity_id for s in normalized}))
    )
    by_source = {
        source: tuple(s for s in normalized if s.source_entity_id == source)
        for source in sources
    }
    cadences = {source: _cadence(series) for source, series in by_source.items()}
    timestamps = sorted({sample.timestamp for sample in normalized})
    points: list[NilmAggregatePoint] = []
    for timestamp in timestamps:
        contributing: list[NilmPowerSample] = []
        flags: set[str] = set()
        for source in sources:
            sample = _latest_at_or_before(by_source[source], timestamp)
            if sample is None or sample.value_w is None or sample.quality != "valid":
                flags.add("missing_source")
                continue
            age = (timestamp - sample.timestamp).total_seconds()
            cadence = cadences[source]
            freshness = _freshness_seconds(cadence, thresholds)
            if age > freshness:
                flags.add("stale_source")
                continue
            contributing.append(sample)
        skew = _skew(contributing)
        if skew is not None and skew > thresholds.maximum_source_skew_seconds:
            flags.add("source_skew_exceeded")
        complete = len(contributing) == len(sources) and not flags
        points.append(
            NilmAggregatePoint(
                timestamp,
                sum(s.value_w for s in contributing) if complete else None,
                len(sources),
                len(contributing),
                skew,
                tuple(sorted(flags)),
            )
        )
    return tuple(points)


def context_window_seconds(
    start: datetime,
    end: datetime,
    thresholds: NilmEvidenceThresholds = DEFAULT_THRESHOLDS,
    observed_cadence_seconds: float | None = None,
) -> float:
    """Return a bounded side window that leaves at least 20% interior context."""
    duration = max(0.0, (end - start).total_seconds())
    requested = max(
        thresholds.minimum_context_seconds,
        duration * thresholds.context_interval_fraction,
        (observed_cadence_seconds or 0.0) * 2,
    )
    return min(thresholds.maximum_context_seconds, requested, duration / 4)


def derive_manual_interval_evidence(
    samples: Iterable[NilmPowerSample],
    *,
    start: datetime,
    end: datetime,
    source_entity_ids: Sequence[str] | None = None,
    thresholds: NilmEvidenceThresholds = DEFAULT_THRESHOLDS,
) -> NilmIntervalEvidence:
    """Extract independent boundary, plateau, and coverage evidence for an interval."""
    if end <= start:
        raise ValueError("end must be after start")
    normalized = normalize_power_samples(samples)
    points = aggregate_power_samples(
        normalized, source_entity_ids=source_entity_ids, thresholds=thresholds
    )
    observed_cadence = _cadence(normalized)
    window = context_window_seconds(start, end, thresholds, observed_cadence)
    pre = _points_between(points, _offset(start, -window), start, end_inclusive=False)
    early = _points_between(points, start, _offset(start, window))
    late = _points_between(points, _offset(end, -window), end, end_inclusive=False)
    post = tuple(
        point for point in points if end < point.timestamp <= _offset(end, window)
    )
    pre_power, early_power, late_power, post_power = (
        _robust_power(group) for group in (pre, early, late, post)
    )
    sources = tuple(
        source_entity_ids
        or tuple(sorted({sample.source_entity_id for sample in normalized}))
    )
    by_source = {
        source: tuple(
            sample for sample in normalized if sample.source_entity_id == source
        )
        for source in sources
    }
    start_delta, start_reliable = _boundary_delta(
        by_source,
        _offset(start, -window),
        start,
        start,
        _offset(start, window),
        thresholds,
        after_start_inclusive=True,
    )
    stop_delta, stop_reliable = _boundary_delta(
        by_source,
        _offset(end, -window),
        end,
        end,
        _offset(end, window),
        thresholds,
        after_start_inclusive=False,
    )
    flags: set[str] = set()
    start_ok = start_reliable and _eligible_start(start_delta, thresholds)
    stop_ok = stop_reliable and _eligible_stop(stop_delta, thresholds)
    if not start_ok:
        flags.add("start_transition_ineligible")
    if not stop_ok:
        flags.add("stop_transition_ineligible")
    interior = _points_between(points, _offset(start, window), _offset(end, -window))
    net_points = _net_points(
        _points_between(points, start, end), start, end, pre_power, post_power
    )
    interior_net_points = _net_points(interior, start, end, pre_power, post_power)
    changes = _material_changes_net(
        net_points,
        thresholds.minimum_transition_w,
        start=_offset(start, window),
        end=_offset(end, -window),
    )
    if changes:
        flags.add("interior_transition_present")
    if len(changes) > 1:
        flags.add("multiple_load_changes")
    baseline = _baseline(pre_power, post_power)
    if baseline is None:
        flags.add("baseline_unavailable")
    elif pre_power is None or post_power is None:
        flags.add("one_sided_baseline")
    partial_energy, coverage, longest_gap, average = _integrate(
        net_points,
        start,
        end,
        maximum_span_seconds=_freshness_seconds(observed_cadence, thresholds),
    )
    net_values = [power for _, power in net_points if power is not None]
    if any(power < -thresholds.numerical_noise_w for power in net_values):
        flags.add("material_negative_net_power")
    if coverage < thresholds.complete_energy_coverage:
        flags.add("incomplete_power_coverage")
    interior_values = [power for _, power in interior_net_points if power is not None]
    plateau = (
        median(interior_values) if interior_values and baseline is not None else None
    )
    plateau_ok = (
        plateau is not None
        and coverage > 0
        and "material_negative_net_power" not in flags
    )
    complete = (
        baseline is not None
        and coverage >= thresholds.complete_energy_coverage
        and "material_negative_net_power" not in flags
    )
    measured = partial_energy if complete else None
    aggregate_valid = [
        point
        for point in _points_between(points, start, end)
        if point.power_w is not None
    ]
    source_coverage = (
        len(aggregate_valid) / len(_points_between(points, start, end))
        if _points_between(points, start, end)
        else 0.0
    )
    skews = [p.source_skew_seconds for p in points if p.source_skew_seconds is not None]
    confidence = max(
        0.0,
        min(
            1.0,
            coverage
            * source_coverage
            * max(0.4, 1.0 - 0.15 * len(changes))
            * (0.8 if baseline is None else 1.0),
        ),
    )
    return NilmIntervalEvidence(
        start,
        end,
        start_delta,
        stop_delta,
        plateau,
        average,
        measured,
        partial_energy,
        window if pre and early else None,
        window if late and post else None,
        source_coverage,
        coverage,
        max(skews) if skews else None,
        longest_gap,
        start_ok,
        stop_ok,
        plateau_ok,
        complete,
        confidence,
        coverage,
        len(changes),
        max((abs(change) for change in changes), default=None),
        tuple(sorted(flags)),
    )


def _cadence(series: Sequence[NilmPowerSample]) -> float:
    deltas = [
        (b.timestamp - a.timestamp).total_seconds()
        for a, b in zip(series, series[1:], strict=False)
        if b.timestamp > a.timestamp
    ]
    return median(deltas) if deltas else 0.0


def _freshness_seconds(
    cadence_seconds: float, thresholds: NilmEvidenceThresholds
) -> float:
    return min(
        thresholds.maximum_freshness_seconds,
        max(
            thresholds.minimum_freshness_seconds,
            cadence_seconds * thresholds.freshness_cadence_multiplier,
        ),
    )


def _latest_at_or_before(
    series: Sequence[NilmPowerSample], timestamp: datetime
) -> NilmPowerSample | None:
    return next(
        (sample for sample in reversed(series) if sample.timestamp <= timestamp), None
    )


def _skew(samples: Sequence[NilmPowerSample]) -> float | None:
    if not samples:
        return None
    return (
        max(s.timestamp for s in samples) - min(s.timestamp for s in samples)
    ).total_seconds()


def _offset(value: datetime, seconds: float) -> datetime:
    from datetime import timedelta

    return value + timedelta(seconds=seconds)


def _points_between(
    points: Sequence[NilmAggregatePoint],
    start: datetime,
    end: datetime,
    *,
    end_inclusive: bool = True,
) -> tuple[NilmAggregatePoint, ...]:
    return tuple(
        p
        for p in points
        if start <= p.timestamp <= end
        if end_inclusive or p.timestamp < end
    )


def _robust_power(points: Sequence[NilmAggregatePoint]) -> float | None:
    values = [point.power_w for point in points if point.power_w is not None]
    return median(values) if values else None


def _difference(after: float | None, before: float | None) -> float | None:
    return None if after is None or before is None else after - before


@dataclass(frozen=True)
class _WindowStats:
    power_w: float | None
    spread_w: float | None
    coverage: float
    representative_timestamp: datetime | None
    last_timestamp: datetime | None
    first_timestamp: datetime | None


def _boundary_delta(
    by_source: dict[str, Sequence[NilmPowerSample]],
    before_start: datetime,
    boundary: datetime,
    after_start: datetime,
    after_end: datetime,
    thresholds: NilmEvidenceThresholds,
    *,
    after_start_inclusive: bool,
) -> tuple[float | None, bool]:
    deltas: list[float] = []
    before_times: list[datetime] = []
    after_times: list[datetime] = []
    for series in by_source.values():
        before = _window_stats(series, before_start, boundary, end_inclusive=False)
        after = _window_stats(
            series,
            after_start,
            after_end,
            start_inclusive=after_start_inclusive,
        )
        if not _reliable_boundary_windows(before, after, thresholds):
            return None, False
        assert before.power_w is not None and after.power_w is not None
        assert before.last_timestamp is not None and after.first_timestamp is not None
        assert before.representative_timestamp is not None
        assert after.representative_timestamp is not None
        deltas.append(after.power_w - before.power_w)
        before_times.append(before.representative_timestamp)
        after_times.append(after.representative_timestamp)
        if (
            after.first_timestamp - before.last_timestamp
        ).total_seconds() > thresholds.maximum_boundary_gap_seconds:
            return None, False
    compatible = (
        _timestamp_spread(before_times) <= thresholds.maximum_source_skew_seconds
    )
    compatible &= (
        _timestamp_spread(after_times) <= thresholds.maximum_source_skew_seconds
    )
    return (sum(deltas), compatible) if compatible else (None, False)


def _window_stats(
    series: Sequence[NilmPowerSample],
    start: datetime,
    end: datetime,
    *,
    start_inclusive: bool = True,
    end_inclusive: bool = True,
) -> _WindowStats:
    selected = [
        sample
        for sample in series
        if (sample.timestamp >= start if start_inclusive else sample.timestamp > start)
        and (sample.timestamp <= end if end_inclusive else sample.timestamp < end)
    ]
    usable = [
        sample
        for sample in selected
        if sample.value_w is not None and sample.quality == "valid"
    ]
    if not selected or not usable:
        return _WindowStats(None, None, 0.0, None, None, None)
    values = [sample.value_w for sample in usable if sample.value_w is not None]
    timestamps = sorted(sample.timestamp for sample in usable)
    return _WindowStats(
        median(values),
        max(values) - min(values),
        len(usable) / len(selected),
        timestamps[len(timestamps) // 2],
        max(timestamps),
        min(timestamps),
    )


def _reliable_boundary_windows(
    before: _WindowStats, after: _WindowStats, thresholds: NilmEvidenceThresholds
) -> bool:
    return (
        before.power_w is not None
        and after.power_w is not None
        and before.coverage >= thresholds.minimum_boundary_coverage
        and after.coverage >= thresholds.minimum_boundary_coverage
        and (before.spread_w or 0.0) <= thresholds.maximum_boundary_spread_w
        and (after.spread_w or 0.0) <= thresholds.maximum_boundary_spread_w
    )


def _eligible_start(delta: float | None, thresholds: NilmEvidenceThresholds) -> bool:
    return delta is not None and delta >= thresholds.minimum_transition_w


def _eligible_stop(delta: float | None, thresholds: NilmEvidenceThresholds) -> bool:
    return delta is not None and delta <= -thresholds.minimum_transition_w


def _timestamp_spread(timestamps: Sequence[datetime]) -> float:
    if not timestamps:
        return float("inf")
    return (max(timestamps) - min(timestamps)).total_seconds()


def _material_changes(
    points: Sequence[NilmAggregatePoint], threshold: float
) -> list[float]:
    return [
        b.power_w - a.power_w
        for a, b in zip(points, points[1:], strict=False)
        if a.power_w is not None
        and b.power_w is not None
        and abs(b.power_w - a.power_w) >= threshold
    ]


def _material_changes_net(
    points: Sequence[tuple[datetime, float | None]],
    threshold: float,
    *,
    start: datetime,
    end: datetime,
) -> list[float]:
    return [
        right_power - left_power
        for (left_time, left_power), (right_time, right_power) in zip(
            points, points[1:], strict=False
        )
        if left_power is not None
        and right_power is not None
        and start <= left_time <= end
        and start <= right_time <= end
        and abs(right_power - left_power) >= threshold
    ]


def _baseline(pre: float | None, post: float | None) -> tuple[float, float] | None:
    if pre is None and post is None:
        return None
    return (pre if pre is not None else post, post if post is not None else pre)  # type: ignore[arg-type]


def _net_points(
    points: Sequence[NilmAggregatePoint],
    start: datetime,
    end: datetime,
    pre: float | None,
    post: float | None,
) -> tuple[tuple[datetime, float | None], ...]:
    baseline = _baseline(pre, post)
    if baseline is None:
        return tuple((point.timestamp, None) for point in points)
    left, right = baseline
    duration = (end - start).total_seconds()
    return tuple(
        (
            point.timestamp,
            None
            if point.power_w is None
            else point.power_w
            - (
                left
                + (right - left) * (point.timestamp - start).total_seconds() / duration
            ),
        )
        for point in points
    )


def _integrate(
    points: Sequence[tuple[datetime, float | None]],
    start: datetime,
    end: datetime,
    *,
    maximum_span_seconds: float,
) -> tuple[float | None, float, float | None, float | None]:
    duration = (end - start).total_seconds()
    covered = 0.0
    energy_ws = 0.0
    longest_gap = 0.0
    if not points:
        return None, 0.0, duration or None, None
    covered_spans: list[tuple[datetime, datetime]] = []
    for (left_time, left_power), (right_time, right_power) in zip(
        points, points[1:], strict=False
    ):
        seconds = (right_time - left_time).total_seconds()
        if (
            left_power is not None
            and right_power is not None
            and seconds <= maximum_span_seconds
        ):
            covered += seconds
            energy_ws += (left_power + right_power) * seconds / 2
            covered_spans.append((left_time, right_time))
    if covered_spans:
        longest_gap = (covered_spans[0][0] - start).total_seconds()
        previous_end = covered_spans[0][1]
        for span_start, span_end in covered_spans[1:]:
            longest_gap = max(longest_gap, (span_start - previous_end).total_seconds())
            previous_end = max(previous_end, span_end)
        longest_gap = max(longest_gap, (end - previous_end).total_seconds())
    else:
        longest_gap = duration
    coverage = covered / duration if duration else 0.0
    average = energy_ws / covered if covered else None
    return (
        energy_ws / 3_600_000 if covered else None,
        coverage,
        longest_gap or None,
        average,
    )
