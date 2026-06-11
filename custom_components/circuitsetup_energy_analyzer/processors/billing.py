"""Billing-cycle budget processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..billing import (
    BillingCycleBudgetEvidence,
    BillingCycleSettings,
    record_billing_cycle_usage,
)
from ..models import AlertEvidence, CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type BillingCycleSettingsProvider = Callable[
    [CircuitConfig | None, str],
    BillingCycleSettings,
]
type BillingAlertPolicyProvider = Callable[[str], _AlertPolicy]


class BillingCycleProcessor:
    """Track billing-cycle kWh usage and configured budget alerts."""

    name = "billing_cycle"

    def __init__(
        self,
        *,
        settings_for_config: BillingCycleSettingsProvider,
        alert_policy_for_circuit: BillingAlertPolicyProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record billing-cycle usage, update state, and return budget alerts."""
        circuit_id = circuit_config.circuit_id
        result = record_billing_cycle_usage(
            context.store_data.billing_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            energy_kwh=sample.energy,
            settings=self._settings_for_config(circuit_config, circuit_id),
        )
        if result is None:
            return FeatureResult()

        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("billing_cycle_usage_kwh_by_circuit", circuit_id),
                    result.cycle_usage_kwh,
                ),
                StateUpdate(
                    ("billing_cycle_forecast_kwh_by_circuit", circuit_id),
                    result.projected_cycle_kwh,
                ),
                StateUpdate(
                    ("billing_cycle_budget_usage_by_circuit", circuit_id),
                    result.budget_usage_percent,
                ),
                StateUpdate(
                    ("billing_cycle_status_by_circuit", circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("billing_cycle_evidence_by_circuit", circuit_id),
                    billing_cycle_evidence_payload(result),
                ),
            ],
            store_dirty=True,
        )
        if result.budget_exceeded is None:
            return feature_result

        evidence = result.budget_exceeded
        score = (
            evidence.projected_cycle_kwh / evidence.budget_kwh
            if evidence.budget_kwh > 0.0
            else 0.0
        )
        alert = self._alert_policy_for_circuit(circuit_id).observe(
            Observation(
                circuit_id=circuit_id,
                feature="billing_cycle_budget",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.projected_cycle_kwh,
                baseline_value=evidence.budget_kwh,
                message=billing_cycle_budget_message(circuit_config, evidence),
                features=evidence.features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result


def billing_cycle_budget_message(
    config: CircuitConfig,
    evidence: BillingCycleBudgetEvidence,
) -> str:
    """Build the user-facing billing-cycle budget alert message."""
    return (
        f"Possible issue: {config.name} is projected to use "
        f"{_format_kwh(evidence.projected_cycle_kwh)} kWh in the "
        f"{evidence.cycle_start} to {evidence.cycle_end} billing cycle, above "
        f"the configured {_format_kwh(evidence.budget_kwh)} kWh "
        f"billing-cycle budget."
    )


def billing_cycle_evidence_payload(result: Any) -> dict[str, Any]:
    """Build the analyzer state payload for billing-cycle tracking."""
    return {
        "cycle_start": result.cycle_start,
        "cycle_end": result.cycle_end,
        "cycle_start_day": result.cycle_start_day,
        "cycle_usage_kwh": result.cycle_usage_kwh,
        "projected_cycle_kwh": result.projected_cycle_kwh,
        "elapsed_days": result.elapsed_days,
        "cycle_days": result.cycle_days,
        "budget_kwh": result.budget_kwh,
        "budget_alert_ratio": result.budget_alert_ratio,
        "budget_usage_percent": result.budget_usage_percent,
        "projected_budget_usage_percent": result.projected_budget_usage_percent,
        "status": result.status,
    }


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
