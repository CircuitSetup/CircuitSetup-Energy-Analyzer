"""Predictive appliance-health processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from ..alerting import Observation
from ..appliance_health import (
    ApplianceHealthEvaluation,
    ApplianceHealthFinding,
    build_appliance_health_days,
    build_appliance_health_sessions,
    evaluate_appliance_health,
)
from ..contextual_baseline import stored_contextual_samples
from ..models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
)
from ..normalize import NormalizedCircuitSample
from ..state import circuit_is_learning
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

type HealthAlertPolicyProvider = Callable[[str], AlertPolicy]
type MergeGapProvider = Callable[[CircuitConfig], float]

_EXCLUDED_PROFILES = {
    ApplianceProfile.MAINS_NILM,
    ApplianceProfile.MIXED,
    ApplianceProfile.SOLAR_INVERTER,
}
_EXCLUDED_MODES = {CircuitMode.MAINS_NILM, CircuitMode.MIXED}
_METRIC_LABELS = {
    "energy_per_runtime_hour": "energy per runtime hour",
    "energy_per_completed_cycle": "energy per completed cycle",
    "average_cycle_duration": "average cycle duration",
    "starts_per_runtime_hour": "starts per runtime hour",
    "session_duration_seconds": "run duration",
}


class ApplianceHealthProcessor:
    """Convert retained appliance-health findings into the shared alert path."""

    name = "appliance_health"

    def __init__(
        self,
        *,
        alert_policy_for_circuit: HealthAlertPolicyProvider,
        short_cycle_alert_policy_for_circuit: HealthAlertPolicyProvider | None = None,
        merge_gap_seconds_for_config: MergeGapProvider,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._short_cycle_alert_policy_for_circuit = (
            short_cycle_alert_policy_for_circuit or alert_policy_for_circuit
        )
        self._merge_gap_seconds_for_config = merge_gap_seconds_for_config

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Evaluate bounded retained evidence without Home Assistant I/O."""
        del sample
        circuit_id = circuit_config.circuit_id
        if _not_applicable(circuit_config):
            return _status_result(circuit_id, "not_applicable", "unsupported_circuit")
        if circuit_is_learning(context.state, circuit_id):
            return _status_result(circuit_id, "learning", "shared_learning_active")

        merge_gap_seconds = self._merge_gap_seconds_for_config(circuit_config)
        energy_history = context.store_data.energy_usage_by_circuit.get(circuit_id, {})
        energy_days = (
            energy_history.get("days", ())
            if isinstance(energy_history, Mapping)
            else ()
        )
        raw_contextual_samples = (
            context.store_data.contextual_baseline_samples_by_circuit.get(
                circuit_id,
                (),
            )
        )
        contextual_samples = stored_contextual_samples(
            circuit_id,
            raw_contextual_samples,
            cache=context.contextual_samples_cache,
        )
        days = build_appliance_health_days(
            circuit_id=circuit_id,
            energy_days=energy_days,
            events=context.store_data.events,
            contextual_samples=contextual_samples,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
        )
        sessions = build_appliance_health_sessions(
            circuit_id=circuit_id,
            events=context.store_data.events,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
            now=context.now,
        )
        evaluation = evaluate_appliance_health(
            circuit_config.appliance_profile,
            days=days,
            sessions=sessions,
        )
        evidence = _evaluation_evidence(evaluation)
        result = FeatureResult(
            state_updates=_state_updates(
                circuit_id,
                evaluation.status,
                evidence,
            )
        )
        finding = evaluation.primary_finding
        if finding is None:
            return result

        observation = Observation(
            circuit_id=circuit_id,
            feature=finding.feature,
            score=max(abs(finding.change_ratio) / 0.20, 1.5),
            baseline_confidence=finding.confidence,
            observed_at=context.now,
            observed_value=finding.recent_median,
            baseline_value=finding.reference_median,
            message=_finding_message(finding),
            observation_key=(
                f"{finding.feature}:{evidence['last_eligible_date_or_session']}"
            ),
            value_metric=finding.metric,
            features=_finding_features(finding),
        )
        result.observations.append(observation)
        policy_provider = (
            self._short_cycle_alert_policy_for_circuit
            if finding.feature == "repeated_short_cycle"
            else self._alert_policy_for_circuit
        )
        alert = policy_provider(circuit_id).observe(observation)
        if alert is None:
            active_alert = _matching_active_health_alert(
                context.state,
                circuit_id,
                finding,
            )
            if active_alert is not None:
                result.alerts.append(active_alert)
            return result
        if finding.feature == "repeated_short_cycle":
            alert = replace(alert, repeated_count=finding.recent_count)
        result.alerts.append(alert)
        result.notifications.append(alert)
        return result


def _not_applicable(config: CircuitConfig) -> bool:
    return (
        config.mode in _EXCLUDED_MODES
        or config.appliance_profile in _EXCLUDED_PROFILES
        or config.power_flow is not PowerFlowMode.LOAD
    )


def _status_result(circuit_id: str, status: str, reason: str) -> FeatureResult:
    evidence = {"status": status, "reason": reason}
    return FeatureResult(
        state_updates=_state_updates(circuit_id, status, evidence),
    )


def _state_updates(
    circuit_id: str,
    status: str,
    evidence: Mapping[str, Any],
) -> list[StateUpdate]:
    return [
        StateUpdate(("appliance_health_status_by_circuit", circuit_id), status),
        StateUpdate(
            ("appliance_health_evidence_by_circuit", circuit_id),
            dict(evidence),
        ),
    ]


def _evaluation_evidence(
    evaluation: ApplianceHealthEvaluation,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": evaluation.status,
        "reason": evaluation.reason,
        "confidence": round(evaluation.confidence, 3),
    }
    finding = evaluation.primary_finding
    if finding is None:
        return evidence

    evidence.update(
        {
            "feature": finding.feature,
            "metric": finding.metric,
            "reference_median": finding.reference_median,
            "recent_median": finding.recent_median,
            "change_ratio": finding.change_ratio,
            "change_percent": round(finding.change_ratio * 100.0, 1),
            "reference_count": finding.reference_count,
            "recent_count": finding.recent_count,
            "context": dict(finding.context),
            "last_eligible_date_or_session": finding.last_evidence_at,
        }
    )
    return evidence


def _finding_features(finding: ApplianceHealthFinding) -> dict[str, Any]:
    count_scope = (
        "day" if finding.feature == "efficiency_degradation" else "session"
    )
    return {
        "notification_type": "appliance_health_issue",
        "metric": finding.metric,
        "reference_value": finding.reference_median,
        "recent_value": finding.recent_median,
        "change_percent": round(finding.change_ratio * 100.0, 1),
        "confidence": round(finding.confidence, 3),
        "health_evidence_key": finding.last_evidence_at,
        f"reference_{count_scope}_count": finding.reference_count,
        f"recent_{count_scope}_count": finding.recent_count,
        **dict(finding.context),
    }


def _matching_active_health_alert(
    state: Any,
    circuit_id: str,
    finding: ApplianceHealthFinding,
) -> AlertEvidence | None:
    for alert in getattr(state, "active_alerts_by_circuit", {}).get(circuit_id, ()):
        if (
            alert.feature == finding.feature
            and alert.features.get("health_evidence_key") == finding.last_evidence_at
        ):
            return alert
    return None


def _finding_message(finding: ApplianceHealthFinding) -> str:
    percent = round(abs(finding.change_ratio) * 100.0)
    direction = "above" if finding.change_ratio >= 0.0 else "below"
    recent_scope = (
        "days" if finding.feature == "efficiency_degradation" else "sessions"
    )
    return (
        f"Possible issue: {_METRIC_LABELS[finding.metric]} has remained "
        f"{percent}% {direction} this appliance's comparable learned range "
        f"across {finding.recent_count} recent {recent_scope}. Check operating "
        "conditions and service needs; this is an inspection prompt, not a "
        "component diagnosis or safety control."
    )
