"""Always On and standby tracking processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..models import (
    AlertEvidence,
    CircuitConfig,
    PowerFlowMode,
)
from ..normalize import NormalizedCircuitSample
from ..standby import (
    StandbyLimitEvidence,
    StandbyResult,
    StandbySettings,
    record_standby_sample,
)
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type StandbySettingsProvider = Callable[[CircuitConfig | None, str], StandbySettings]
type StandbyAlertPolicyProvider = Callable[[str], _AlertPolicy]
type DemoStandbySeeder = Callable[
    [CircuitConfig, NormalizedCircuitSample, ProcessingContext, StandbySettings],
    None,
]


class StandbyProcessor:
    """Track Always On / standby state and configured Always On alerts."""

    name = "standby"

    def __init__(
        self,
        *,
        settings_for_config: StandbySettingsProvider,
        alert_policy_for_circuit: StandbyAlertPolicyProvider,
        seed_demo_history: DemoStandbySeeder | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._seed_demo_history = seed_demo_history

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record standby state and return configured Always On alerts."""
        power_w = _standby_power_w(sample)
        settings = self._settings_for_config(circuit_config, circuit_config.circuit_id)
        if self._seed_demo_history is not None:
            self._seed_demo_history(circuit_config, sample, context, settings)
        result = record_standby_sample(
            context.store_data.standby_by_circuit.setdefault(
                circuit_config.circuit_id,
                {},
            ),
            circuit_id=circuit_config.circuit_id,
            timestamp=context.now,
            real_power_w=power_w,
            settings=settings,
        )
        if result is None:
            return FeatureResult()

        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("always_on_power_w_by_circuit", circuit_config.circuit_id),
                    result.always_on_power_w,
                ),
                StateUpdate(
                    ("standby_threshold_w_by_circuit", circuit_config.circuit_id),
                    result.standby_threshold_w,
                ),
                StateUpdate(
                    ("standby_status_by_circuit", circuit_config.circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("always_on_limit_usage_by_circuit", circuit_config.circuit_id),
                    result.always_on_limit_usage,
                ),
                StateUpdate(
                    ("standby_evidence_by_circuit", circuit_config.circuit_id),
                    standby_evidence_payload(result),
                ),
            ],
            store_dirty=result.limit_exceeded is not None,
        )
        if result.limit_exceeded is not None:
            alert = self._standby_limit_alert(
                circuit_config,
                context,
                result.limit_exceeded,
            )
            if alert is not None:
                feature_result.alerts.append(alert)
                feature_result.notifications.append(alert)
        return feature_result

    def _standby_limit_alert(
        self,
        config: CircuitConfig,
        context: ProcessingContext,
        evidence: StandbyLimitEvidence,
    ) -> AlertEvidence | None:
        score = (
            evidence.always_on_power_w / evidence.always_on_alert_w
            if evidence.always_on_alert_w > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(config.circuit_id).observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="always_on_power",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.always_on_power_w,
                baseline_value=evidence.always_on_alert_w,
                message=standby_limit_message(config, evidence),
                features=evidence.features,
            )
        )


def standby_limit_message(
    config: CircuitConfig,
    evidence: StandbyLimitEvidence,
) -> str:
    """Build the user-facing Always On alert message."""
    return (
        f"Possible issue: {config.name} Always On is "
        f"{_format_w(evidence.always_on_power_w)} W over the last "
        f"{evidence.window_hours} hours, above the configured "
        f"{_format_w(evidence.always_on_alert_w)} W limit."
    )


def standby_evidence_payload(result: StandbyResult) -> dict[str, Any]:
    """Build the analyzer state payload for standby tracking."""
    return {
        "always_on_power_w": result.always_on_power_w,
        "current_power_w": result.current_power_w,
        "standby_threshold_w": result.standby_threshold_w,
        "sample_count": result.sample_count,
        "window_hours": result.window_hours,
        "always_on_alert_w": result.always_on_alert_w,
        "always_on_limit_usage_percent": result.always_on_limit_usage,
        "status": result.status,
    }


def _standby_power_w(sample: NormalizedCircuitSample) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    return max(float(power), 0.0)


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
