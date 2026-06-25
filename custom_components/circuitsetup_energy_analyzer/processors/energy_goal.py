"""Daily energy goal processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..alerting import Observation
from ..goals import (
    EnergyGoalEvidence,
    EnergyGoalSettings,
    evaluate_daily_energy_goal,
)
from ..local_time import local_date
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

type EnergyGoalSettingsProvider = Callable[
    [CircuitConfig | None, str],
    EnergyGoalSettings,
]
type GoalAlertPolicyProvider = Callable[[str], AlertPolicy]


class EnergyGoalProcessor:
    """Evaluate daily kWh goals for one circuit."""

    name = "energy_goal"

    def __init__(
        self,
        *,
        settings_for_config: EnergyGoalSettingsProvider,
        alert_policy_for_circuit: GoalAlertPolicyProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Update goal state and return an alert when today's goal is exceeded."""
        usage_evidence = context.state.energy_usage_evidence_by_circuit.get(
            circuit_config.circuit_id,
            {},
        )
        if not isinstance(usage_evidence, dict):
            return FeatureResult()
        if usage_evidence.get("date") != _context_date(context):
            return FeatureResult()
        return self.refresh_state(
            circuit_config.circuit_id,
            circuit_config,
            context,
            include_alert=True,
        )

    def refresh_state(
        self,
        circuit_id: str,
        circuit_config: CircuitConfig | None,
        context: ProcessingContext,
        *,
        include_alert: bool = False,
    ) -> FeatureResult:
        """Return state updates for the latest daily energy goal status."""
        usage_evidence = context.state.energy_usage_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        date = (
            str(usage_evidence.get("date"))
            if isinstance(usage_evidence, dict) and usage_evidence.get("date")
            else _context_date(context)
        )
        result = evaluate_daily_energy_goal(
            circuit_id=circuit_id,
            date=date,
            daily_usage_kwh=context.state.daily_energy_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            settings=self._settings_for_config(circuit_config, circuit_id),
        )
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("energy_goal_usage_by_circuit", circuit_id),
                    result.goal_usage_percent,
                ),
                StateUpdate(
                    ("energy_goal_status_by_circuit", circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("energy_goal_evidence_by_circuit", circuit_id),
                    energy_goal_evidence_payload(result),
                ),
            ],
        )
        if not include_alert or result.goal_exceeded is None:
            return feature_result

        evidence = result.goal_exceeded
        score = (
            evidence.daily_usage_kwh / evidence.alert_threshold_kwh
            if evidence.alert_threshold_kwh > 0.0
            else 0.0
        )
        alert = self._alert_policy_for_circuit(circuit_id).observe(
            Observation(
                circuit_id=circuit_id,
                feature="daily_energy_goal",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.daily_usage_kwh,
                baseline_value=evidence.daily_goal_kwh,
                message=energy_goal_message(circuit_config, evidence),
                features=evidence.features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result


def energy_goal_message(
    config: CircuitConfig | None,
    evidence: EnergyGoalEvidence,
) -> str:
    """Build the user-facing daily energy goal message."""
    name = config.name if config is not None else evidence.circuit_id
    return (
        f"Energy goal notice: {name} used "
        f"{_format_kwh(evidence.daily_usage_kwh)} kWh today, which is "
        f"{evidence.goal_usage_percent}% of its configured "
        f"{_format_kwh(evidence.daily_goal_kwh)} kWh daily goal."
    )


def energy_goal_evidence_payload(result: Any) -> dict[str, Any]:
    """Build the analyzer state payload for daily energy goals."""
    return {
        "date": result.date,
        "daily_usage_kwh": result.daily_usage_kwh,
        "daily_goal_kwh": result.daily_goal_kwh,
        "goal_usage_percent": result.goal_usage_percent,
        "alert_threshold_kwh": result.alert_threshold_kwh,
        "goal_alert_ratio": result.goal_alert_ratio,
        "status": result.status,
    }


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _context_date(context: ProcessingContext) -> str:
    if context.time_zone is None or context.now.tzinfo is None:
        return context.now.date().isoformat()
    return local_date(context.now, context.time_zone).isoformat()
