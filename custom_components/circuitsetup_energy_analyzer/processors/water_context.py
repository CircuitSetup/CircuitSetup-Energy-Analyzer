"""Water-context alert processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..alerting import Observation
from ..models import CircuitConfig
from ..profiles import supports_direct_appliance_analysis
from .base import AlertPolicy, FeatureResult, ProcessingContext

ALERT_STATUSES = frozenset(
    {
        "possible_excess_pump_activity",
        "possible_missing_pump_activity",
        "possible_flow_without_load",
        "possible_load_without_flow",
        "possible_sensor_problem",
    },
)


type WaterContextAlertPolicyProvider = Callable[[str, str], AlertPolicy]


class WaterContextAlertProcessor:
    """Observe rain-pump and flow-context evidence for actionable alerts."""

    name = "water_context"

    def __init__(
        self,
        *,
        alert_policy_for_circuit: WaterContextAlertPolicyProvider,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return the first actionable water-context alert for a circuit."""
        if not supports_direct_appliance_analysis(circuit_config):
            return FeatureResult()
        circuit_id = circuit_config.circuit_id
        for feature, evidence in (
            (
                "rain_pump_correlation",
                context.state.rain_pump_context_by_circuit.get(circuit_id, {}),
            ),
            (
                "water_flow_correlation",
                context.state.water_flow_context_by_circuit.get(circuit_id, {}),
            ),
        ):
            if not isinstance(evidence, Mapping):
                continue
            status = str(evidence.get("status") or "")
            if status not in ALERT_STATUSES:
                continue
            policy = self._alert_policy_for_circuit(circuit_id, feature)
            observed_value = water_context_observed_value(evidence)
            baseline_value = water_context_baseline_value(evidence)
            confidence = _float_or_none(evidence.get("confidence")) or 0.0
            score = max(
                1.0,
                abs(observed_value - baseline_value) / max(baseline_value, 1.0),
            )
            alert = policy.observe(
                Observation(
                    circuit_id=circuit_id,
                    feature=feature,
                    score=score,
                    baseline_confidence=confidence,
                    observed_at=context.now,
                    observed_value=observed_value,
                    baseline_value=baseline_value,
                    message=water_context_alert_message(
                        circuit_config.name,
                        evidence,
                    ),
                    features=water_context_alert_features(evidence),
                )
            )
            if alert is not None:
                return FeatureResult(alerts=[alert], notifications=[alert])
        return FeatureResult()


def water_context_observed_value(evidence: Mapping[str, Any]) -> float:
    """Return the most relevant observed water-context value."""
    for key in ("mismatch_minutes", "pump_runtime_minutes", "flow_active_minutes"):
        value = _float_or_none(evidence.get(key))
        if value is not None:
            return value
    return 0.0


def water_context_baseline_value(evidence: Mapping[str, Any]) -> float:
    """Return the most relevant baseline water-context value."""
    for key in ("expected_runtime_minutes", "dry_baseline_minutes"):
        value = _float_or_none(evidence.get(key))
        if value is not None:
            return value
    threshold = _float_or_none(evidence.get("flow_mismatch_threshold_minutes"))
    return threshold if threshold is not None else 0.0


def water_context_alert_features(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build numeric alert features from water-context evidence."""
    features: dict[str, Any] = {}
    for key in (
        "mismatch_minutes",
        "pump_runtime_minutes",
        "expected_runtime_minutes",
        "flow_active_minutes",
        "confidence",
        "baseline_sample_count",
        "contextual_baseline_confidence",
    ):
        value = _float_or_none(evidence.get(key))
        if value is not None:
            features[key] = value
    for key in (
        "baseline_context",
        "baseline_fallback_level",
        "contextual_status",
    ):
        value = evidence.get(key)
        if isinstance(value, str) and value:
            features[key] = value
    return features


def water_context_alert_message(
    circuit_name: str,
    evidence: Mapping[str, Any],
) -> str:
    """Build the user-facing water-context alert message."""
    summary = str(evidence.get("friendly_summary") or "").strip()
    status = str(evidence.get("status") or "possible_issue")
    status_label = status.replace("_", " ").title()
    if summary:
        return f"Possible issue: {circuit_name} water context changed. {summary}"
    return f"Possible issue: {circuit_name} water context changed: {status_label}."


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
