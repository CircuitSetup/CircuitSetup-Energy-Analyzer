from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any

from .baseline import score_deviation
from .local_time import TimeZone, local_date, local_day_end, local_day_start
from .models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
)

RUN_CYCLE_DURATION_FEATURE = "run_cycle_duration_s"
RUN_CYCLE_DUTY_CYCLE_FEATURE = "run_cycle_daily_duty_cycle_percent"
RUN_CYCLE_START_COUNT_FEATURE = "run_cycle_daily_start_count"
MIN_CYCLE_BASELINE_CONFIDENCE = 0.6


@dataclass(frozen=True, slots=True)
class CircuitCycleSummary:
    """Today-scoped operating-cycle evidence for one circuit."""

    circuit_id: str
    date: str
    status: str
    start_count: int
    completed_cycle_count: int
    runtime_seconds: float
    average_cycle_seconds: float
    active_cycle_seconds: float
    duty_cycle_percent: float
    day_elapsed_seconds: float
    first_start: datetime | None = None
    last_start: datetime | None = None
    last_stop: datetime | None = None
    day_start: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunSession:
    """Normalized run session built from confirmed transitions."""

    started_at: datetime
    stopped_at: datetime | None
    duration_seconds: float
    merged_transition_count: int
    start_event_id: str | None = None
    stop_event_id: str | None = None
    start_known: bool = True


@dataclass(frozen=True, slots=True)
class CycleAnomalyEvidence:
    """Selected run-cycle behavior evidence for one circuit."""

    feature: str
    message: str
    observed_value: float
    baseline_value: float
    score: float
    baseline_confidence: float
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


def summarize_circuit_cycles(
    events: Iterable[CircuitEvent],
    *,
    circuit_id: str,
    now: datetime,
    merge_gap_seconds: float = 0.0,
    time_zone: TimeZone = None,
) -> CircuitCycleSummary:
    """Summarize today's appliance run cycles from retained start/stop events."""
    day_start = _day_start_for_datetime(now, time_zone)
    sessions = build_normalized_run_sessions(
        events,
        circuit_id=circuit_id,
        merge_gap_seconds=merge_gap_seconds,
        now=now,
    )

    start_count = 0
    completed_cycle_count = 0
    runtime_seconds = 0.0
    completed_runtime_seconds = 0.0
    active_cycle_seconds = 0.0
    first_start: datetime | None = None
    last_start: datetime | None = None
    last_stop: datetime | None = None

    for session in sessions:
        if session.started_at > now:
            continue
        if session.started_at >= day_start:
            start_count += 1
            first_start = first_start or session.started_at
            last_start = session.started_at

        session_runtime = _session_runtime_within_day(
            session,
            day_start=day_start,
            now=now,
        )
        runtime_seconds += session_runtime

        if session.stopped_at is None:
            active_cycle_seconds += session_runtime
            continue
        if session.stopped_at >= day_start:
            last_stop = session.stopped_at
            completed_cycle_count += 1
            completed_runtime_seconds += session_runtime

    day_elapsed_seconds = max((now - day_start).total_seconds(), 0.0)
    average_cycle_seconds = (
        completed_runtime_seconds / completed_cycle_count
        if completed_cycle_count > 0
        else 0.0
    )
    duty_cycle_percent = (
        (runtime_seconds / day_elapsed_seconds) * 100.0
        if day_elapsed_seconds > 0.0
        else 0.0
    )
    if active_cycle_seconds > 0.0:
        status = "running"
    elif start_count > 0 or completed_cycle_count > 0:
        status = "idle"
    else:
        status = "no_activity"

    return CircuitCycleSummary(
        circuit_id=circuit_id,
        date=_calendar_date(now, time_zone).isoformat(),
        status=status,
        start_count=start_count,
        completed_cycle_count=completed_cycle_count,
        runtime_seconds=_round_seconds(runtime_seconds),
        average_cycle_seconds=_round_seconds(average_cycle_seconds),
        active_cycle_seconds=_round_seconds(active_cycle_seconds),
        duty_cycle_percent=round(duty_cycle_percent, 1),
        day_elapsed_seconds=_round_seconds(day_elapsed_seconds),
        first_start=first_start,
        last_start=last_start,
        last_stop=last_stop,
        day_start=day_start,
    )


def cycle_baseline_feature_values(
    events: Iterable[CircuitEvent],
    *,
    circuit_id: str,
    now: datetime,
    merge_gap_seconds: float = 0.0,
    time_zone: TimeZone = None,
) -> dict[str, list[float]]:
    """Return prior cycle-feature samples suitable for robust baselines."""
    day_start = _day_start_for_datetime(now, time_zone)
    current_date = _calendar_date(now, time_zone)
    circuit_events = _circuit_cycle_events(events, circuit_id)
    prior_dates = sorted(
        {
            _calendar_date(event.timestamp, time_zone)
            for event in circuit_events
            if _calendar_date(event.timestamp, time_zone) < current_date
        }
    )
    daily_summaries = [
        summarize_circuit_cycles(
            circuit_events,
            circuit_id=circuit_id,
            now=_end_of_day(day, now, time_zone),
            merge_gap_seconds=merge_gap_seconds,
            time_zone=time_zone,
        )
        for day in prior_dates
    ]
    active_daily_summaries = [
        summary
        for summary in daily_summaries
        if summary.start_count > 0 or summary.completed_cycle_count > 0
    ]
    return {
        RUN_CYCLE_DURATION_FEATURE: _completed_cycle_durations(
            circuit_events,
            circuit_id=circuit_id,
            before=day_start,
            merge_gap_seconds=merge_gap_seconds,
        ),
        RUN_CYCLE_DUTY_CYCLE_FEATURE: [
            summary.duty_cycle_percent for summary in active_daily_summaries
        ],
        RUN_CYCLE_START_COUNT_FEATURE: [
            float(summary.start_count) for summary in active_daily_summaries
        ],
    }


def select_cycle_anomaly_evidence(
    config: CircuitConfig,
    summary: CircuitCycleSummary,
    baselines: dict[str, BaselineStats],
    *,
    min_score: float = 1.5,
) -> CycleAnomalyEvidence | None:
    """Select conservative appliance run-cycle anomaly evidence."""
    if (
        config.mode in {CircuitMode.MIXED, CircuitMode.MAINS_NILM}
        or config.appliance_profile
        in {
            ApplianceProfile.MIXED,
            ApplianceProfile.MAINS_NILM,
            ApplianceProfile.SOLAR_INVERTER,
        }
    ):
        return None

    candidates = [
        candidate
        for candidate in (
            _active_cycle_duration_evidence(config, summary, baselines),
            _daily_duty_cycle_evidence(config, summary, baselines),
            _daily_start_count_evidence(config, summary, baselines),
        )
        if candidate is not None
        and candidate.score >= min_score
        and candidate.baseline_confidence >= MIN_CYCLE_BASELINE_CONFIDENCE
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.score)


def cycle_summary_payload(summary: CircuitCycleSummary) -> dict[str, Any]:
    """Return JSON-safe diagnostic evidence for cycle summary sensors."""
    return {
        "date": summary.date,
        "status": summary.status,
        "start_count": summary.start_count,
        "completed_cycle_count": summary.completed_cycle_count,
        "runtime_seconds": summary.runtime_seconds,
        "average_cycle_seconds": summary.average_cycle_seconds,
        "active_cycle_seconds": summary.active_cycle_seconds,
        "duty_cycle_percent": summary.duty_cycle_percent,
        "day_elapsed_seconds": summary.day_elapsed_seconds,
        "first_start": _isoformat_or_none(summary.first_start),
        "last_start": _isoformat_or_none(summary.last_start),
        "last_stop": _isoformat_or_none(summary.last_stop),
        "scope": "today",
        "evidence_source": "retained_start_stop_events",
    }


def build_normalized_run_sessions(
    events: Iterable[CircuitEvent],
    *,
    circuit_id: str,
    merge_gap_seconds: float,
    now: datetime,
) -> list[RunSession]:
    """Build normalized run sessions from retained start/stop transitions."""
    circuit_events = _circuit_cycle_events(events, circuit_id)
    raw_sessions: list[RunSession] = []
    active_start: datetime | None = None

    for event in circuit_events:
        if event.timestamp > now:
            break
        if event.event_type is EventType.START:
            active_start = event.timestamp
            continue
        if event.event_type is not EventType.STOP or active_start is None:
            continue
        duration = max((event.timestamp - active_start).total_seconds(), 0.0)
        raw_sessions.append(
            RunSession(
                started_at=active_start,
                stopped_at=event.timestamp,
                duration_seconds=_round_seconds(duration),
                merged_transition_count=2,
            )
        )
        active_start = None

    if active_start is not None:
        raw_sessions.append(
            RunSession(
                started_at=active_start,
                stopped_at=None,
                duration_seconds=_round_seconds(
                    max((now - active_start).total_seconds(), 0.0)
                ),
                merged_transition_count=1,
            )
        )

    if not raw_sessions:
        return []

    merged_sessions: list[RunSession] = [raw_sessions[0]]
    for session in raw_sessions[1:]:
        previous = merged_sessions[-1]
        if (
            previous.stopped_at is not None
            and session.started_at >= previous.stopped_at
            and (session.started_at - previous.stopped_at).total_seconds()
            <= merge_gap_seconds
        ):
            merged_sessions[-1] = RunSession(
                started_at=previous.started_at,
                stopped_at=session.stopped_at,
                duration_seconds=_round_seconds(
                    previous.duration_seconds + session.duration_seconds
                ),
                merged_transition_count=(
                    previous.merged_transition_count + session.merged_transition_count
                ),
                start_known=previous.start_known,
            )
            continue
        merged_sessions.append(session)
    return merged_sessions


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _active_cycle_duration_evidence(
    config: CircuitConfig,
    summary: CircuitCycleSummary,
    baselines: dict[str, BaselineStats],
) -> CycleAnomalyEvidence | None:
    baseline = baselines.get(RUN_CYCLE_DURATION_FEATURE)
    observed = summary.active_cycle_seconds
    if baseline is None or observed <= baseline.median or observed <= 0.0:
        return None
    score = score_deviation(observed, baseline)
    return CycleAnomalyEvidence(
        feature=RUN_CYCLE_DURATION_FEATURE,
        message=(
            f"Possible issue: {config.name} has been running for "
            f"{_format_seconds(observed)}, above its learned "
            f"{_format_seconds(baseline.median)} cycle-duration baseline. "
            "Evidence is retained start/stop timing only, not a diagnosis."
        ),
        observed_value=observed,
        baseline_value=baseline.median,
        score=score,
        baseline_confidence=baseline.confidence,
        features={
            "active_cycle_seconds": observed,
            "baseline_cycle_seconds": baseline.median,
            "baseline_p90_cycle_seconds": baseline.p90,
            "baseline_sample_count": float(baseline.sample_count),
            "baseline_confidence": baseline.confidence,
            "score": score,
        },
    )


def _daily_duty_cycle_evidence(
    config: CircuitConfig,
    summary: CircuitCycleSummary,
    baselines: dict[str, BaselineStats],
) -> CycleAnomalyEvidence | None:
    baseline = baselines.get(RUN_CYCLE_DUTY_CYCLE_FEATURE)
    observed = summary.duty_cycle_percent
    if baseline is None or observed <= baseline.median or observed <= 0.0:
        return None
    score = score_deviation(observed, baseline)
    return CycleAnomalyEvidence(
        feature=RUN_CYCLE_DUTY_CYCLE_FEATURE,
        message=(
            f"Possible issue: {config.name} has run for {observed}% of today, "
            f"above its learned {baseline.median}% daily duty-cycle baseline. "
            "Evidence is retained start/stop timing only, not a diagnosis."
        ),
        observed_value=observed,
        baseline_value=baseline.median,
        score=score,
        baseline_confidence=baseline.confidence,
        features={
            "duty_cycle_percent": observed,
            "baseline_duty_cycle_percent": baseline.median,
            "baseline_p90_duty_cycle_percent": baseline.p90,
            "baseline_sample_count": float(baseline.sample_count),
            "baseline_confidence": baseline.confidence,
            "score": score,
        },
    )


def _daily_start_count_evidence(
    config: CircuitConfig,
    summary: CircuitCycleSummary,
    baselines: dict[str, BaselineStats],
) -> CycleAnomalyEvidence | None:
    baseline = baselines.get(RUN_CYCLE_START_COUNT_FEATURE)
    observed = float(summary.start_count)
    if baseline is None or observed <= baseline.median or observed <= 0.0:
        return None
    score = score_deviation(observed, baseline)
    return CycleAnomalyEvidence(
        feature=RUN_CYCLE_START_COUNT_FEATURE,
        message=(
            f"Possible issue: {config.name} has started {summary.start_count} "
            f"times today, above its learned {baseline.median:g} starts-per-day "
            "baseline. Evidence is retained start/stop timing only, not a "
            "diagnosis."
        ),
        observed_value=observed,
        baseline_value=baseline.median,
        score=score,
        baseline_confidence=baseline.confidence,
        features={
            "start_count": observed,
            "baseline_start_count": baseline.median,
            "baseline_p90_start_count": baseline.p90,
            "baseline_sample_count": float(baseline.sample_count),
            "baseline_confidence": baseline.confidence,
            "score": score,
        },
    )


def _completed_cycle_durations(
    events: Iterable[CircuitEvent],
    *,
    circuit_id: str,
    before: datetime,
    merge_gap_seconds: float = 0.0,
) -> list[float]:
    return [
        session.duration_seconds
        for session in build_normalized_run_sessions(
            events,
            circuit_id=circuit_id,
            merge_gap_seconds=merge_gap_seconds,
            now=before,
        )
        if session.stopped_at is not None and session.stopped_at < before
    ]


def _circuit_cycle_events(
    events: Iterable[CircuitEvent],
    circuit_id: str,
) -> list[CircuitEvent]:
    return sorted(
        (
            event
            for event in events
            if event.circuit_id == circuit_id
            and event.event_type in {EventType.START, EventType.STOP}
        ),
        key=lambda event: event.timestamp,
    )


def _end_of_day(day: date, now: datetime, time_zone: TimeZone = None) -> datetime:
    if time_zone is not None:
        return local_day_end(day, time_zone)
    return datetime.combine(day, time.max, tzinfo=now.tzinfo)


def _day_start_for_datetime(now: datetime, time_zone: TimeZone) -> datetime:
    if time_zone is None or now.tzinfo is None:
        return datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    return local_day_start(now, time_zone)


def _calendar_date(timestamp: datetime, time_zone: TimeZone) -> date:
    if time_zone is None or timestamp.tzinfo is None:
        return timestamp.date()
    return local_date(timestamp, time_zone)


def _session_runtime_within_day(
    session: RunSession,
    *,
    day_start: datetime,
    now: datetime,
) -> float:
    if session.stopped_at is None:
        if session.started_at >= day_start:
            return session.duration_seconds
        return _round_seconds(max((now - day_start).total_seconds(), 0.0))

    if session.stopped_at <= day_start:
        return 0.0
    if session.started_at >= day_start:
        return session.duration_seconds
    return _round_seconds(max((session.stopped_at - day_start).total_seconds(), 0.0))


def _format_seconds(value: float) -> str:
    seconds = round(value)
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f}".rstrip("0").rstrip(".") + " min"
    hours = minutes / 60.0
    return f"{hours:.1f}".rstrip("0").rstrip(".") + " h"


def _round_seconds(value: float) -> float:
    return round(float(value), 3)
