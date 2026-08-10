"""Pure, deterministic evidence extraction for manually selected NILM intervals."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
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


DEFAULT_THRESHOLDS = NilmEvidenceThresholds()


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
            freshness = min(
                thresholds.maximum_freshness_seconds,
                max(
                    thresholds.minimum_freshness_seconds,
                    cadence * thresholds.freshness_cadence_multiplier,
                ),
            )
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
) -> float:
    """Return a bounded side window that leaves at least 20% interior context."""
    duration = max(0.0, (end - start).total_seconds())
    requested = max(
        thresholds.minimum_context_seconds,
        duration * thresholds.context_interval_fraction,
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
    points = aggregate_power_samples(
        samples, source_entity_ids=source_entity_ids, thresholds=thresholds
    )
    window = context_window_seconds(start, end, thresholds)
    pre = _points_between(points, _offset(start, -window), start, end_inclusive=False)
    early = _points_between(points, start, _offset(start, window))
    late = _points_between(points, _offset(end, -window), end, end_inclusive=False)
    post = tuple(
        point for point in points if end < point.timestamp <= _offset(end, window)
    )
    pre_power, early_power, late_power, post_power = (
        _robust_power(group) for group in (pre, early, late, post)
    )
    start_delta = _difference(early_power, pre_power)
    stop_delta = _difference(post_power, late_power)
    flags: set[str] = set()
    start_ok = _eligible(start_delta, pre, early, thresholds)
    stop_ok = _eligible(stop_delta, late, post, thresholds)
    if not start_ok:
        flags.add("start_transition_ineligible")
    if not stop_ok:
        flags.add("stop_transition_ineligible")
    interior = _points_between(points, _offset(start, window), _offset(end, -window))
    changes = _material_changes(interior, thresholds.minimum_transition_w)
    if changes:
        flags.add("interior_transition_present")
    if len(changes) > 1:
        flags.add("multiple_load_changes")
    baseline = _baseline(pre_power, post_power)
    if baseline is None:
        flags.add("baseline_unavailable")
    elif pre_power is None or post_power is None:
        flags.add("one_sided_baseline")
    net_points = _net_points(
        _points_between(points, start, end), start, end, pre_power, post_power
    )
    partial_energy, coverage, longest_gap, average = _integrate(net_points, start, end)
    net_values = [power for _, power in net_points if power is not None]
    if any(power < -thresholds.numerical_noise_w for power in net_values):
        flags.add("material_negative_net_power")
    if coverage < thresholds.complete_energy_coverage:
        flags.add("incomplete_power_coverage")
    plateau = median(net_values) if net_values and baseline is not None else None
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
            * (0.7 if changes else 1.0)
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
        tuple(sorted(flags)),
    )


def _cadence(series: Sequence[NilmPowerSample]) -> float:
    deltas = [
        (b.timestamp - a.timestamp).total_seconds()
        for a, b in zip(series, series[1:], strict=False)
        if b.timestamp > a.timestamp
    ]
    return median(deltas) if deltas else 0.0


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


def _eligible(
    delta: float | None,
    before: Sequence[NilmAggregatePoint],
    after: Sequence[NilmAggregatePoint],
    thresholds: NilmEvidenceThresholds,
) -> bool:
    return (
        delta is not None
        and abs(delta) >= thresholds.minimum_transition_w
        and all(p.power_w is not None for p in (*before, *after))
    )


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
    points: Sequence[tuple[datetime, float | None]], start: datetime, end: datetime
) -> tuple[float | None, float, float | None, float | None]:
    duration = (end - start).total_seconds()
    covered = 0.0
    energy_ws = 0.0
    longest_gap = 0.0
    gap_start: datetime | None = None
    for (left_time, left_power), (right_time, right_power) in zip(
        points, points[1:], strict=False
    ):
        seconds = (right_time - left_time).total_seconds()
        if left_power is not None and right_power is not None:
            covered += seconds
            energy_ws += (left_power + right_power) * seconds / 2
            gap_start = None
        else:
            gap_start = gap_start or left_time
            longest_gap = max(longest_gap, (right_time - gap_start).total_seconds())
    coverage = covered / duration if duration else 0.0
    average = energy_ws / covered if covered else None
    return (
        energy_ws / 3_600_000 if covered else None,
        coverage,
        longest_gap or None,
        average,
    )
