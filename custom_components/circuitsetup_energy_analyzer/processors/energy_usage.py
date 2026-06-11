"""Daily energy usage processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..models import AlertEvidence, CircuitConfig
from ..normalize import NormalizedCircuitSample
from ..usage import EnergyUsageSettings, EnergyUsageSpike, record_energy_usage
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type EnergyUsageSettingsProvider = Callable[
    [CircuitConfig | None, str],
    EnergyUsageSettings,
]
type RetentionDaysProvider = Callable[[str], int]
type UsageAlertPolicyProvider = Callable[[str], _AlertPolicy]
type DemoEnergyUsageSeeder = Callable[
    [CircuitConfig, NormalizedCircuitSample, Any, EnergyUsageSettings],
    None,
]


class EnergyUsageProcessor:
    """Track daily kWh usage and produce spike alerts for one circuit."""

    name = "energy_usage"

    def __init__(
        self,
        *,
        settings_for_config: EnergyUsageSettingsProvider,
        retention_days_for_circuit: RetentionDaysProvider,
        alert_policy_for_circuit: UsageAlertPolicyProvider,
        seed_demo_history: DemoEnergyUsageSeeder | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._retention_days_for_circuit = retention_days_for_circuit
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._seed_demo_history = seed_demo_history

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record daily usage, update analyzer state, and return spike alerts."""
        circuit_id = circuit_config.circuit_id
        settings = self._settings_for_config(circuit_config, circuit_id)
        if self._seed_demo_history is not None:
            self._seed_demo_history(circuit_config, sample, context.now, settings)

        result = record_energy_usage(
            context.store_data.energy_usage_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            energy_kwh=sample.energy,
            settings=EnergyUsageSettings(
                window_days=settings.window_days,
                daily_spike_ratio=settings.daily_spike_ratio,
            ),
            retention_days=self._retention_days_for_circuit(circuit_id),
        )
        if result is None:
            return FeatureResult()

        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("daily_energy_usage_by_circuit", circuit_id),
                    result.daily_usage_kwh,
                ),
                StateUpdate(
                    ("energy_usage_share_by_circuit", circuit_id),
                    round(result.daily_usage_share * 100, 1),
                ),
                StateUpdate(
                    ("energy_usage_evidence_by_circuit", circuit_id),
                    energy_usage_evidence_payload(result),
                ),
            ],
            store_dirty=True,
        )

        if result.spike is None:
            return feature_result

        spike = result.spike
        score = (
            spike.daily_usage_kwh / spike.threshold_kwh
            if spike.threshold_kwh > 0.0
            else 0.0
        )
        alert = self._alert_policy_for_circuit(circuit_id).observe(
            Observation(
                circuit_id=circuit_id,
                feature="daily_energy_usage_spike",
                score=score,
                baseline_confidence=min(
                    spike.baseline_day_count / spike.window_days,
                    1.0,
                ),
                observed_at=context.now,
                observed_value=spike.daily_usage_kwh,
                baseline_value=spike.threshold_kwh,
                message=energy_usage_spike_message(circuit_config, spike),
                features=spike.features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result


def energy_usage_spike_message(
    config: CircuitConfig,
    spike: EnergyUsageSpike,
) -> str:
    """Build the user-facing daily usage spike message."""
    share_percent = round(spike.daily_usage_share * 100, 1)
    threshold_percent = round(spike.threshold_ratio * 100)
    return (
        f"Possible issue: {config.name} used {_format_kwh(spike.daily_usage_kwh)} "
        f"kWh today, which is {share_percent}% of its last {spike.window_days} "
        f"days of usage ({_format_kwh(spike.baseline_total_kwh)} kWh). This is "
        f"above the configured {threshold_percent}% daily usage threshold."
    )


def energy_usage_evidence_payload(result: Any) -> dict[str, Any]:
    """Build the analyzer state payload for daily usage tracking."""
    status = "over_threshold" if result.spike is not None else result.tracking_status
    return {
        "date": result.date,
        "daily_usage_kwh": result.daily_usage_kwh,
        "baseline_total_kwh": result.baseline_total_kwh,
        "baseline_window_days": result.window_days,
        "baseline_day_count": result.baseline_day_count,
        "threshold_ratio": result.threshold_ratio,
        "threshold_kwh": result.threshold_kwh,
        "daily_usage_share_percent": round(result.daily_usage_share * 100, 1),
        "status": status,
        "raw_status": status,
        "status_label": _status_label_for_evidence(status),
        "status_explanation": _status_explanation_for_evidence(status),
        "status_reason": result.status_reason,
        "suggested_next_check": _energy_usage_next_check(status),
    }


def _status_label_for_evidence(status: str) -> str:
    overrides = {"waiting_for_delta": "Waiting For Energy Change"}
    if status in overrides:
        return overrides[status]
    return " ".join(part.capitalize() for part in status.split("_"))


def _status_explanation_for_evidence(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "A cumulative kWh source is present, but the analyzer has not "
            "observed it increase since tracking started."
        )
    if status == "learning":
        return "The analyzer is still collecting the rolling daily kWh baseline."
    if status == "tracking":
        return "The analyzer is tracking daily usage from cumulative kWh changes."
    if status == "over_threshold":
        return "Today usage is above the configured rolling-window threshold."
    return f"{_status_label_for_evidence(status)} status reported by the analyzer."


def _energy_usage_next_check(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "Let the analyzer see the energy sensor increase, or confirm the "
            "circuit has a cumulative kWh source."
        )
    if status == "learning":
        return "Let the analyzer retain enough full days for the rolling baseline."
    if status == "tracking":
        return "No action is needed unless the usage looks wrong for the appliance."
    if status == "over_threshold":
        return "Review recent appliance runtime and confirm the mapped kWh source."
    return "Review the sensor attributes for the observed evidence."


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
