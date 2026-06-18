"""Activity alert processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..activity_alerts import ActivityAlertSettings, evaluate_activity_alert
from ..alerting import Observation
from ..cycles import summarize_circuit_cycles
from ..models import AlertEvidence, CircuitConfig
from ..normalize import NormalizedCircuitSample
from ..operating_detection import resolve_operating_detection
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
        merge_gap_seconds = resolve_operating_detection(
            circuit_config,
            overrides=getattr(
                context.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_config.circuit_id, {}),
        ).profile.merge_gap_seconds
        summary = summarize_circuit_cycles(
            context.store_data.events,
            circuit_id=circuit_config.circuit_id,
            now=context.now,
            merge_gap_seconds=merge_gap_seconds,
        )
        evidence = evaluate_activity_alert(
            circuit_id=circuit_config.circuit_id,
            circuit_name=circuit_config.name,
            summary=summary,
            settings=self._settings_for_config(
                circuit_config,
                circuit_config.circuit_id,
            ),
        )
        if evidence is None:
            return FeatureResult()

        alert = self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )
        if alert is None:
            return FeatureResult()
        return FeatureResult(alerts=[alert], notifications=[alert])
