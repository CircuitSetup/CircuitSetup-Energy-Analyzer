"""Demand tracking processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..demand import (
    DemandLimitEvidence,
    DemandPeakEvidence,
    DemandSettings,
    record_demand_sample,
)
from ..models import AlertEvidence, CircuitConfig, PowerFlowMode
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type DemandSettingsProvider = Callable[[CircuitConfig | None, str], DemandSettings]
type DemandAlertPolicyProvider = Callable[[str], _AlertPolicy]
type RetentionDaysProvider = Callable[[str], int]


class DemandProcessor:
    """Track rolling demand and demand alerts for one circuit."""

    name = "demand"

    def __init__(
        self,
        *,
        settings_for_config: DemandSettingsProvider,
        alert_policy_for_circuit: DemandAlertPolicyProvider,
        retention_days_for_circuit: RetentionDaysProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._retention_days_for_circuit = retention_days_for_circuit

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record demand state and return configured demand alerts."""
        circuit_id = circuit_config.circuit_id
        result = record_demand_sample(
            context.store_data.demand_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            real_power_w=_demand_power_w(sample),
            settings=self._settings_for_config(circuit_config, circuit_id),
            retention_days=self._retention_days_for_circuit(circuit_id),
        )
        if result is None:
            return FeatureResult()

        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("current_demand_w_by_circuit", circuit_id),
                    result.current_demand_w,
                ),
                StateUpdate(
                    ("peak_demand_w_by_circuit", circuit_id),
                    result.peak_demand_w,
                ),
                StateUpdate(
                    ("demand_limit_usage_by_circuit", circuit_id),
                    result.demand_limit_usage,
                ),
                StateUpdate(
                    ("demand_peak_rank_by_circuit", circuit_id),
                    result.monthly_peak_rank,
                ),
                StateUpdate(
                    ("demand_peak_status_by_circuit", circuit_id),
                    result.monthly_peak_status,
                ),
                StateUpdate(
                    ("demand_evidence_by_circuit", circuit_id),
                    demand_evidence_payload(result),
                ),
            ],
            store_dirty=result.monthly_peak_recorded,
        )

        alert = None
        if result.limit_exceeded is not None:
            alert = self._demand_limit_alert(
                circuit_config,
                context,
                result.limit_exceeded,
            )
        elif result.monthly_peak_warning is not None:
            alert = self._demand_monthly_peak_alert(
                circuit_config,
                context,
                result.monthly_peak_warning,
            )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result

    def _demand_limit_alert(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
        evidence: DemandLimitEvidence,
    ) -> AlertEvidence | None:
        score = (
            evidence.current_demand_w / evidence.demand_limit_w
            if evidence.demand_limit_w > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature="demand_limit",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.current_demand_w,
                baseline_value=evidence.demand_limit_w,
                message=demand_limit_message(circuit_config, evidence),
                features=evidence.features,
            )
        )

    def _demand_monthly_peak_alert(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
        evidence: DemandPeakEvidence,
    ) -> AlertEvidence | None:
        score = max(1.0, evidence.monthly_peak_usage_percent / 100.0)
        return self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature="demand_monthly_peak",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.current_demand_w,
                baseline_value=evidence.monthly_peak_cutoff_w,
                message=demand_monthly_peak_message(circuit_config, evidence),
                features=evidence.features,
            )
        )


def demand_limit_message(
    config: CircuitConfig,
    evidence: DemandLimitEvidence,
) -> str:
    """Build the user-facing demand-limit alert message."""
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, above the configured "
        f"{_format_w(evidence.demand_limit_w)} W limit."
    )


def demand_monthly_peak_message(
    config: CircuitConfig,
    evidence: DemandPeakEvidence,
) -> str:
    """Build the user-facing monthly peak demand alert message."""
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, near this month's top "
        f"{evidence.peak_rank_count} demand windows. It is "
        f"{_format_percent(evidence.monthly_peak_usage_percent)}% of the "
        f"{_format_w(evidence.monthly_peak_cutoff_w)} W cutoff."
    )


def demand_evidence_payload(result: Any) -> dict[str, Any]:
    """Build the analyzer state payload for rolling demand tracking."""
    return {
        "date": result.date,
        "current_demand_w": result.current_demand_w,
        "peak_demand_w": result.peak_demand_w,
        "demand_window_minutes": result.window_minutes,
        "demand_limit_w": result.demand_limit_w,
        "demand_limit_usage_percent": result.demand_limit_usage,
        "status": (
            "over_limit"
            if result.limit_exceeded is not None
            else ("tracking" if result.demand_limit_w is not None else "unconfigured")
        ),
        "monthly_peak_rank": result.monthly_peak_rank,
        "monthly_peak_status": result.monthly_peak_status,
        "monthly_peak_cutoff_w": result.monthly_peak_cutoff_w,
        "monthly_peak_usage_percent": result.monthly_peak_usage_percent,
        "monthly_peak_rank_count": result.monthly_peak_rank_count,
        "monthly_peak_warning_ratio": result.monthly_peak_warning_ratio,
    }


def _demand_power_w(sample: NormalizedCircuitSample) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    return max(float(power), 0.0)


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
