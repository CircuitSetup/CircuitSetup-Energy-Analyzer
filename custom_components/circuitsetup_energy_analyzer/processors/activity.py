"""Activity alert processor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from ..activity_alerts import ActivityAlertSettings, evaluate_activity_alert
from ..alerting import Observation
from ..cycles import summarize_circuit_cycles
from ..models import AlertEvidence, ApplianceProfile, CircuitConfig, CircuitMode
from ..normalize import NormalizedCircuitSample
from ..operating_detection import (
    operating_state_is_running,
    resolve_operating_detection_from_settings,
)
from .base import FeatureResult, ProcessingContext


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type ActivityAlertSettingsProvider = Callable[
    [CircuitConfig | None, str],
    ActivityAlertSettings,
]
type ActivityAlertPolicyProvider = Callable[[str], _AlertPolicy]


class ActivityAlertProcessor:
    """Evaluate user-configured activity alerts for one circuit."""

    name = "activity_alert"

    def __init__(
        self,
        *,
        settings_for_config: ActivityAlertSettingsProvider,
        alert_policy_for_circuit: ActivityAlertPolicyProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return configured activity alerts for the current cycle summary."""
        merge_gap_seconds = resolve_operating_detection_from_settings(
            circuit_config,
            getattr(
                context.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_config.circuit_id, {}),
        ).profile.merge_gap_seconds
        if _operating_state_is_unavailable(context, circuit_config.circuit_id):
            return FeatureResult()
        summary = summarize_circuit_cycles(
            context.store_data.events,
            circuit_id=circuit_config.circuit_id,
            now=context.now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
        )
        evidence = evaluate_activity_alert(
            circuit_id=circuit_config.circuit_id,
            circuit_name=circuit_config.name,
            summary=summary,
            settings=self._settings_for_config(
                circuit_config,
                circuit_config.circuit_id,
            ),
            suppress_active_duration_alert=_is_mains_nilm(circuit_config),
        )
        if evidence is None:
            return FeatureResult()

        observation = Observation(
            circuit_id=circuit_config.circuit_id,
            feature=evidence.feature,
            score=evidence.score,
            baseline_confidence=1.0,
            observed_at=context.now,
            observed_value=evidence.observed_value,
            baseline_value=evidence.baseline_value,
            message=evidence.message,
            observation_key=_observation_key(evidence.feature, summary),
            features=evidence.features,
        )
        policy_observation = replace(observation, observation_key=None)
        alert = self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            policy_observation
        )
        if alert is None:
            return FeatureResult(observations=[observation])
        return FeatureResult(
            observations=[observation],
            alerts=[alert],
            notifications=[alert],
        )


def _observation_key(feature: str, summary: Any) -> str:
    if feature == "activity_left_on" and summary.last_start is not None:
        return f"{feature}:{summary.last_start.isoformat()}"
    if summary.last_stop is not None:
        return f"{feature}:{summary.last_stop.isoformat()}"
    return f"{feature}:{summary.date}"


def _operating_state_is_unavailable(
    context: ProcessingContext,
    circuit_id: str,
) -> bool:
    snapshots = getattr(context.state, "operating_state_snapshot_by_circuit", {}) or {}
    if not isinstance(snapshots, dict):
        return False
    snapshot = snapshots.get(circuit_id)
    return snapshot is not None and operating_state_is_running(snapshot) is None


def _is_mains_nilm(config: CircuitConfig) -> bool:
    return (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    )
