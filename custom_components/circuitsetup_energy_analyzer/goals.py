from __future__ import annotations

from dataclasses import dataclass, replace

DEFAULT_GOAL_ALERT_RATIO = 1.0


@dataclass(frozen=True, slots=True)
class EnergyGoalSettings:
    """User-tunable daily energy goal settings."""

    daily_goal_kwh: float | None = None
    goal_alert_ratio: float = DEFAULT_GOAL_ALERT_RATIO


@dataclass(frozen=True, slots=True)
class EnergyGoalEvidence:
    """Evidence that daily usage has reached a configured goal threshold."""

    circuit_id: str
    date: str
    daily_usage_kwh: float
    daily_goal_kwh: float
    goal_usage_percent: float
    alert_threshold_kwh: float
    goal_alert_ratio: float
    status: str
    features: dict[str, float]


@dataclass(frozen=True, slots=True)
class EnergyGoalResult:
    """Latest daily energy-goal state for a circuit."""

    circuit_id: str
    date: str
    daily_usage_kwh: float
    daily_goal_kwh: float | None
    goal_usage_percent: float
    alert_threshold_kwh: float
    goal_alert_ratio: float
    status: str = "unconfigured"
    goal_exceeded: EnergyGoalEvidence | None = None


def evaluate_daily_energy_goal(
    *,
    circuit_id: str,
    date: str,
    daily_usage_kwh: float,
    settings: EnergyGoalSettings,
) -> EnergyGoalResult:
    """Compare today's kWh usage with a configured daily goal."""
    usage_kwh = _round_kwh(max(float(daily_usage_kwh), 0.0))
    goal_kwh = _positive_float_or_none(settings.daily_goal_kwh)
    alert_ratio = max(float(settings.goal_alert_ratio), 0.0)

    result = EnergyGoalResult(
        circuit_id=circuit_id,
        date=date,
        daily_usage_kwh=usage_kwh,
        daily_goal_kwh=goal_kwh,
        goal_usage_percent=0.0,
        alert_threshold_kwh=0.0,
        goal_alert_ratio=alert_ratio,
    )
    if goal_kwh is None:
        return result

    goal_usage = round((usage_kwh / goal_kwh) * 100, 1)
    alert_threshold = _round_kwh(goal_kwh * alert_ratio)
    status = _goal_status(usage_kwh, goal_kwh, alert_threshold)
    result = replace(
        result,
        goal_usage_percent=goal_usage,
        alert_threshold_kwh=alert_threshold,
        status=status,
    )
    if status not in {"near_goal", "over_goal"}:
        return result

    evidence = EnergyGoalEvidence(
        circuit_id=circuit_id,
        date=date,
        daily_usage_kwh=usage_kwh,
        daily_goal_kwh=goal_kwh,
        goal_usage_percent=goal_usage,
        alert_threshold_kwh=alert_threshold,
        goal_alert_ratio=alert_ratio,
        status=status,
        features={
            "daily_usage_kwh": usage_kwh,
            "daily_goal_kwh": goal_kwh,
            "goal_usage_percent": goal_usage,
            "alert_threshold_kwh": alert_threshold,
            "goal_alert_ratio": alert_ratio,
        },
    )
    return replace(result, goal_exceeded=evidence)


def _goal_status(
    daily_usage_kwh: float,
    daily_goal_kwh: float,
    alert_threshold_kwh: float,
) -> str:
    if daily_usage_kwh >= daily_goal_kwh:
        return "over_goal"
    if alert_threshold_kwh > 0.0 and daily_usage_kwh >= alert_threshold_kwh:
        return "near_goal"
    return "tracking"


def _positive_float_or_none(value: float | None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _round_kwh(value: float) -> float:
    return round(float(value), 3)
