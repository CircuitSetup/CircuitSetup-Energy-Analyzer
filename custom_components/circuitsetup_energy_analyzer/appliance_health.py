"""Pure predictive appliance-health evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from types import MappingProxyType

from .baseline import build_baseline
from .models import ApplianceProfile

REFERENCE_DAY_COUNT = 14
RECENT_DAY_COUNT = 3
REFERENCE_SESSION_COUNT = 9
RECENT_SESSION_COUNT = 3
DEGRADATION_CHANGE_RATIO = 0.25

_WEATHER_AWARE_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.HVAC_BLOWER,
    ApplianceProfile.MINI_SPLIT,
    ApplianceProfile.ELECTRIC_HEAT,
}
_FLOW_AWARE_PROFILES = {
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.WASHER,
    ApplianceProfile.DISHWASHER,
}
_WEATHER_CONTEXT_KEYS = ("season", "weather_mode", "temperature_bin")
_DAY_METRICS = (
    "energy_per_runtime_hour",
    "energy_per_completed_cycle",
    "average_cycle_duration",
    "starts_per_runtime_hour",
)


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

    for metric in _DAY_METRICS:
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
            all(value > reference_median for value in recent_values)
            and change_ratio >= DEGRADATION_CHANGE_RATIO
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
