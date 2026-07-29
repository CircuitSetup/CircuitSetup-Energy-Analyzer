"""Pure predictive appliance-health evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from statistics import median
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .baseline import build_baseline
from .contextual_baseline import ContextualBaselineSample
from .cycles import build_normalized_run_sessions
from .local_time import TimeZone, local_date, local_day_end, local_day_time
from .models import ApplianceProfile, CircuitEvent

REFERENCE_DAY_COUNT = 14
RECENT_DAY_COUNT = 3
REFERENCE_SESSION_COUNT = 9
RECENT_SESSION_COUNT = 3
DEGRADATION_CHANGE_RATIO = 0.25

_WEATHER_AWARE_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.HEAT_PUMP,
    ApplianceProfile.HVAC_BLOWER,
    ApplianceProfile.MINI_SPLIT,
    ApplianceProfile.ELECTRIC_HEAT,
}
_FLOW_AWARE_PROFILES = {
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.WASHER,
    ApplianceProfile.DISHWASHER,
}
_WEATHER_CONTEXT_KEYS = ("season", "weather_mode", "temperature_bin")
_SUMP_CONTEXT_KEYS = (
    "season",
    "rain_state",
    "rain_intensity_bin",
    "temperature_bin",
    "outdoor_humidity_bin",
)
_DAY_METRIC_DIRECTIONS = {
    "energy_per_runtime_hour": 1.0,
    "energy_per_completed_cycle": 1.0,
    "average_cycle_duration": 1.0,
    "starts_per_runtime_hour": 1.0,
}


@dataclass(frozen=True, slots=True)
class ApplianceHealthDay:
    """One complete retained day eligible for health comparison."""

    date: date
    energy_kwh: float | None
    runtime_seconds: float
    completed_cycles: int
    start_count: int
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True, slots=True)
class ApplianceHealthSession:
    """One normalized completed appliance run session."""

    started_at: str
    stopped_at: str
    duration_seconds: float
    gap_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ApplianceHealthFinding:
    """One sustained health change supported by retained evidence."""

    feature: str
    metric: str
    reference_median: float
    recent_median: float
    change_ratio: float
    reference_count: int
    recent_count: int
    confidence: float
    last_evidence_at: str
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True, slots=True)
class ApplianceHealthEvaluation:
    """Health status and strongest retained findings for one appliance."""

    status: str
    reason: str
    confidence: float
    findings: tuple[ApplianceHealthFinding, ...] = ()

    @property
    def primary_finding(self) -> ApplianceHealthFinding | None:
        return self.findings[0] if self.findings else None


def evaluate_appliance_health(
    appliance_profile: ApplianceProfile,
    *,
    days: Sequence[ApplianceHealthDay],
    sessions: Sequence[ApplianceHealthSession],
) -> ApplianceHealthEvaluation:
    """Evaluate sustained degradation and repeated abnormal short cycles."""
    findings: list[ApplianceHealthFinding] = []
    evaluated = False
    context_blocked = False
    ordered_days = sorted(days, key=lambda item: item.date)

    for metric, adverse_direction in _DAY_METRIC_DIRECTIONS.items():
        metric_days = [
            (day, value)
            for day in ordered_days
            if (value := _day_metric_value(day, metric)) is not None
        ]
        if len(metric_days) < RECENT_DAY_COUNT:
            continue

        recent = metric_days[-RECENT_DAY_COUNT:]
        context = _comparison_context(
            appliance_profile,
            [item[0] for item in recent],
        )
        if context is None:
            context_blocked = True
            continue

        reference = [
            item
            for item in metric_days[:-RECENT_DAY_COUNT]
            if _matches_context(item[0], context)
        ][-REFERENCE_DAY_COUNT:]
        if len(reference) < REFERENCE_DAY_COUNT:
            context_blocked = context_blocked or bool(context)
            continue

        evaluated = True
        reference_median = float(median(item[1] for item in reference))
        recent_values = [item[1] for item in recent]
        if reference_median <= 0.0:
            continue
        recent_median = float(median(recent_values))
        change_ratio = (recent_median - reference_median) / reference_median
        if (
            all(
                (value - reference_median) * adverse_direction > 0.0
                for value in recent_values
            )
            and change_ratio * adverse_direction >= DEGRADATION_CHANGE_RATIO
        ):
            findings.append(
                ApplianceHealthFinding(
                    feature="efficiency_degradation",
                    metric=metric,
                    reference_median=reference_median,
                    recent_median=recent_median,
                    change_ratio=change_ratio,
                    reference_count=len(reference),
                    recent_count=len(recent),
                    confidence=_confidence(
                        len(reference),
                        len(recent),
                        reference_required=REFERENCE_DAY_COUNT,
                        recent_required=RECENT_DAY_COUNT,
                    ),
                    last_evidence_at=recent[-1][0].date.isoformat(),
                    context=context,
                )
            )

    session_finding, sessions_evaluated = _evaluate_short_sessions(sessions)
    evaluated = evaluated or sessions_evaluated
    if session_finding is not None:
        findings.append(session_finding)

    findings.sort(
        key=lambda item: abs(item.change_ratio) * item.confidence,
        reverse=True,
    )
    if findings:
        return ApplianceHealthEvaluation(
            status="possible_degradation",
            reason="sustained_change",
            confidence=max(item.confidence for item in findings),
            findings=tuple(findings),
        )
    if evaluated:
        return ApplianceHealthEvaluation(
            status="normal",
            reason="within_comparable_range",
            confidence=1.0,
        )
    return ApplianceHealthEvaluation(
        status="learning",
        reason=(
            "insufficient_comparable_context"
            if context_blocked
            else "insufficient_history"
        ),
        confidence=0.0,
    )


def build_appliance_health_days(
    *,
    circuit_id: str,
    energy_days: Iterable[Mapping[str, Any]],
    events: Iterable[CircuitEvent],
    contextual_samples: Iterable[ContextualBaselineSample],
    merge_gap_seconds: float,
    time_zone: TimeZone,
) -> tuple[ApplianceHealthDay, ...]:
    """Join complete energy days with retained cycle and context evidence."""
    resolved_time_zone = _resolved_time_zone(time_zone)
    circuit_events = tuple(
        event for event in events if event.circuit_id == circuit_id
    )
    ineligible_dates = _ineligible_event_dates(circuit_events, resolved_time_zone)
    context_by_date = _context_by_date(
        circuit_id,
        contextual_samples,
        resolved_time_zone,
    )
    eligible_days: list[tuple[date, float]] = []
    for raw_day in energy_days:
        day = _health_day_date(raw_day)
        energy = _nonnegative_float_or_none(raw_day.get("usage_kwh"))
        if (
            day is None
            or raw_day.get("complete") is not True
            or raw_day.get("baseline_eligible") is False
            or day in ineligible_dates
            or energy is None
        ):
            continue
        eligible_days.append((day, energy))
    if not eligible_days:
        return ()

    target_dates = {day for day, _energy in eligible_days}
    runtime_by_date = dict.fromkeys(target_dates, 0.0)
    starts_by_date = dict.fromkeys(target_dates, 0)
    completions_by_date = dict.fromkeys(target_dates, 0)
    now = local_day_end(max(target_dates), resolved_time_zone)
    sessions = build_normalized_run_sessions(
        circuit_events,
        circuit_id=circuit_id,
        merge_gap_seconds=merge_gap_seconds,
        now=now,
    )
    for session in sessions:
        started_on = local_date(session.started_at, resolved_time_zone)
        if started_on in starts_by_date:
            starts_by_date[started_on] += 1
        if session.stopped_at is not None:
            stopped_on = local_date(session.stopped_at, resolved_time_zone)
            if stopped_on in completions_by_date:
                completions_by_date[stopped_on] += 1
        for interval_start, interval_stop in session.active_intervals:
            interval_end = interval_stop or now
            interval_day = local_date(interval_start, resolved_time_zone)
            final_day = local_date(interval_end, resolved_time_zone)
            while interval_day <= final_day:
                if interval_day in runtime_by_date:
                    day_start = local_day_time(
                        interval_day,
                        time.min,
                        resolved_time_zone,
                    )
                    next_day_start = local_day_time(
                        interval_day + timedelta(days=1),
                        time.min,
                        resolved_time_zone,
                    )
                    runtime_by_date[interval_day] += _elapsed_seconds(
                        max(interval_start, day_start),
                        min(interval_end, next_day_start),
                    )
                interval_day += timedelta(days=1)

    return tuple(
        ApplianceHealthDay(
            date=day,
            energy_kwh=energy,
            runtime_seconds=round(runtime_by_date[day], 3),
            completed_cycles=completions_by_date[day],
            start_count=starts_by_date[day],
            context=context_by_date.get(day, {}),
        )
        for day, energy in sorted(eligible_days)
    )


def build_appliance_health_sessions(
    *,
    circuit_id: str,
    events: Iterable[CircuitEvent],
    merge_gap_seconds: float,
    time_zone: TimeZone,
    now: datetime,
) -> tuple[ApplianceHealthSession, ...]:
    """Convert existing normalized completed runs into health sessions."""
    resolved_time_zone = _resolved_time_zone(time_zone)
    circuit_events = tuple(
        event for event in events if event.circuit_id == circuit_id
    )
    ineligible_dates = _ineligible_event_dates(circuit_events, resolved_time_zone)
    completed = [
        session
        for session in build_normalized_run_sessions(
            circuit_events,
            circuit_id=circuit_id,
            merge_gap_seconds=merge_gap_seconds,
            now=now,
        )
        if session.stopped_at is not None
        and local_date(session.started_at, resolved_time_zone) not in ineligible_dates
        and local_date(session.stopped_at, resolved_time_zone) not in ineligible_dates
    ]
    return tuple(
        ApplianceHealthSession(
            started_at=session.started_at.isoformat(),
            stopped_at=session.stopped_at.isoformat(),
            duration_seconds=session.duration_seconds,
            gap_after_seconds=(
                _elapsed_seconds(session.stopped_at, completed[index + 1].started_at)
                if index + 1 < len(completed)
                else None
            ),
        )
        for index, session in enumerate(completed)
        if session.stopped_at is not None
    )


def _day_metric_value(day: ApplianceHealthDay, metric: str) -> float | None:
    energy = day.energy_kwh
    runtime_hours = day.runtime_seconds / 3600.0
    if metric == "energy_per_runtime_hour":
        return (
            energy / runtime_hours
            if energy is not None and runtime_hours > 0
            else None
        )
    if metric == "energy_per_completed_cycle":
        return (
            energy / day.completed_cycles
            if energy is not None and day.completed_cycles > 0
            else None
        )
    if metric == "average_cycle_duration":
        return (
            day.runtime_seconds / day.completed_cycles
            if day.completed_cycles > 0
            else None
        )
    if metric == "starts_per_runtime_hour":
        return day.start_count / runtime_hours if runtime_hours > 0 else None
    raise ValueError(f"unsupported appliance health metric: {metric}")


def _comparison_context(
    profile: ApplianceProfile,
    recent_days: Sequence[ApplianceHealthDay],
) -> dict[str, str] | None:
    context: dict[str, str] = {}
    if profile in _WEATHER_AWARE_PROFILES:
        weather = _shared_context(recent_days, _WEATHER_CONTEXT_KEYS)
        if weather is None or not weather:
            return None
        context.update(weather)

    if profile is ApplianceProfile.SUMP_PUMP:
        sump_context = _shared_context(recent_days, _SUMP_CONTEXT_KEYS)
        if sump_context is None or not sump_context:
            return None
        context.update(sump_context)

    if profile in _FLOW_AWARE_PROFILES and any(
        day.context.get("water_flow_state") for day in recent_days
    ):
        flow = _shared_context(recent_days, ("water_flow_state",))
        if flow is None or not flow:
            return None
        context.update(flow)
    return context


def _shared_context(
    days: Sequence[ApplianceHealthDay],
    keys: Sequence[str],
) -> dict[str, str] | None:
    shared: dict[str, str] = {}
    for key in keys:
        values = [day.context.get(key) for day in days]
        if not any(values):
            continue
        if any(value is None for value in values) or len(set(values)) != 1:
            return None
        shared[key] = str(values[0])
    return shared


def _matches_context(
    day: ApplianceHealthDay,
    context: Mapping[str, str],
) -> bool:
    return all(day.context.get(key) == value for key, value in context.items())


def _evaluate_short_sessions(
    sessions: Sequence[ApplianceHealthSession],
) -> tuple[ApplianceHealthFinding | None, bool]:
    if len(sessions) < REFERENCE_SESSION_COUNT + RECENT_SESSION_COUNT:
        return None, False

    learned = sessions[:-RECENT_SESSION_COUNT]
    recent = sessions[-RECENT_SESSION_COUNT:]
    if len(learned) < REFERENCE_SESSION_COUNT:
        return None, False

    baseline = build_baseline(
        "appliance_health_session_duration",
        [session.duration_seconds for session in learned],
    )
    recent_values = [session.duration_seconds for session in recent]
    threshold = max(baseline.p10 * 0.5, 1.0)
    if not all(value < threshold for value in recent_values):
        return None, True

    recent_median = float(median(recent_values))
    change_ratio = (
        (recent_median - baseline.median) / baseline.median
        if baseline.median > 0.0
        else 0.0
    )
    return (
        ApplianceHealthFinding(
            feature="repeated_short_cycle",
            metric="session_duration_seconds",
            reference_median=baseline.median,
            recent_median=recent_median,
            change_ratio=change_ratio,
            reference_count=len(learned),
            recent_count=len(recent),
            confidence=_confidence(
                len(learned),
                len(recent),
                reference_required=REFERENCE_SESSION_COUNT,
                recent_required=RECENT_SESSION_COUNT,
            ),
            last_evidence_at=recent[-1].stopped_at,
        ),
        True,
    )


def _confidence(
    reference_count: int,
    recent_count: int,
    *,
    reference_required: int,
    recent_required: int,
) -> float:
    return min(1.0, reference_count / reference_required) * min(
        1.0,
        recent_count / recent_required,
    )


def _resolved_time_zone(time_zone: TimeZone) -> TimeZone:
    if not isinstance(time_zone, str):
        return time_zone
    try:
        return ZoneInfo(time_zone.strip()) if time_zone.strip() else UTC
    except ZoneInfoNotFoundError:
        return UTC


def _ineligible_event_dates(
    events: Iterable[CircuitEvent],
    time_zone: TimeZone,
) -> set[date]:
    return {
        local_date(event.timestamp, time_zone)
        for event in events
        if event.features.get("baseline_eligible") is False
    }


def _context_by_date(
    circuit_id: str,
    samples: Iterable[ContextualBaselineSample],
    time_zone: TimeZone,
) -> dict[date, dict[str, str]]:
    relevant_keys = tuple(
        dict.fromkeys(
            (*_WEATHER_CONTEXT_KEYS, *_SUMP_CONTEXT_KEYS, "water_flow_state")
        )
    )
    grouped: dict[date, dict[str, set[tuple[tuple[str, str], ...]]]] = {}
    for sample in samples:
        if (
            sample.circuit_id != circuit_id
            or sample.feature not in {"daily_energy_kwh", "runtime_today_seconds"}
        ):
            continue
        context = sample.context.as_dict()
        normalized = tuple(
            (key, context[key])
            for key in relevant_keys
            if context.get(key)
        )
        grouped.setdefault(local_date(sample.timestamp, time_zone), {}).setdefault(
            sample.feature,
            set(),
        ).add(normalized)

    result: dict[date, dict[str, str]] = {}
    for day, features in grouped.items():
        energy = features.get("daily_energy_kwh", set())
        runtime = features.get("runtime_today_seconds", set())
        if len(energy) != 1 or len(runtime) != 1:
            result[day] = {}
            continue
        energy_context = dict(next(iter(energy)))
        runtime_context = dict(next(iter(runtime)))
        shared: dict[str, str] = {}
        conflict = False
        for key in relevant_keys:
            energy_value = energy_context.get(key)
            runtime_value = runtime_context.get(key)
            if energy_value is not None and runtime_value is not None:
                if energy_value != runtime_value:
                    conflict = True
                    break
                shared[key] = energy_value
        result[day] = {} if conflict else shared
    return result


def _health_day_date(raw_day: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(raw_day.get("date", "")))
    except ValueError:
        return None


def _nonnegative_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) and parsed >= 0.0 else None


def _elapsed_seconds(start: datetime, end: datetime) -> float:
    if start.tzinfo is not None and end.tzinfo is not None:
        return max((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds(), 0.0)
    return max((end - start).total_seconds(), 0.0)
