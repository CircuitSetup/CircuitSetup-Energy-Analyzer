"""Dual-phase leg imbalance processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..models import AlertEvidence, CircuitConfig, CircuitMode
from ..normalize import NormalizedCircuitSample
from ..phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    LegImbalanceResult,
    evaluate_dual_phase_leg_imbalance,
)
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type LegImbalanceAlertPolicyProvider = Callable[[str], _AlertPolicy]


class LegImbalanceProcessor:
    """Track split-phase leg imbalance and emit configured alerts."""

    name = "leg_imbalance"

    def __init__(
        self,
        *,
        alert_policy_for_circuit: LegImbalanceAlertPolicyProvider,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record leg imbalance state and return repeated imbalance alerts."""
        result = _evaluate_leg_imbalance(sample, circuit_config, context)
        circuit_id = circuit_config.circuit_id
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("leg_imbalance_percent_by_circuit", circuit_id),
                    result.imbalance_percent,
                ),
                StateUpdate(
                    ("leg_imbalance_status_by_circuit", circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("leg_imbalance_evidence_by_circuit", circuit_id),
                    leg_imbalance_evidence_payload(result),
                ),
            ],
        )
        if result.status == "imbalanced":
            alert = self._leg_imbalance_alert(circuit_config, context, result)
            if alert is not None:
                feature_result.alerts.append(alert)
                feature_result.notifications.append(alert)
        return feature_result

    def _leg_imbalance_alert(
        self,
        config: CircuitConfig,
        context: ProcessingContext,
        result: LegImbalanceResult,
    ) -> AlertEvidence | None:
        score = (
            result.imbalance_ratio / result.threshold_ratio
            if result.threshold_ratio > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(config.circuit_id).observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="dual_phase_leg_imbalance",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=result.imbalance_ratio,
                baseline_value=result.threshold_ratio,
                message=leg_imbalance_message(config, result),
                features=result.features,
            )
        )


def leg_imbalance_message(
    config: CircuitConfig,
    result: LegImbalanceResult,
) -> str:
    """Build the user-facing dual-phase leg imbalance alert message."""
    return (
        f"Possible issue: {config.name} split-phase legs are imbalanced: "
        f"leg A is {_format_w(result.left_real_power_w or 0.0)} W and "
        f"leg B is {_format_w(result.right_real_power_w or 0.0)} W "
        f"({_format_percent(result.imbalance_percent)}% imbalance), above "
        f"the configured {_format_percent(result.threshold_percent)}% "
        "threshold. Review CT pairing, phase mapping, or appliance leg behavior."
    )


def leg_imbalance_evidence_payload(
    result: LegImbalanceResult,
) -> dict[str, Any]:
    """Build the analyzer state payload for split-phase leg balance."""
    return {
        "status": result.status,
        "leg_imbalance_ratio": result.imbalance_ratio,
        "leg_imbalance_percent": result.imbalance_percent,
        "threshold_ratio": result.threshold_ratio,
        "threshold_percent": result.threshold_percent,
        "minimum_total_power_w": result.minimum_total_power_w,
        "left_real_power_w": result.left_real_power_w,
        "right_real_power_w": result.right_real_power_w,
        "left_current_a": result.left_current_a,
        "right_current_a": result.right_current_a,
        "left_voltage_v": result.left_voltage_v,
        "right_voltage_v": result.right_voltage_v,
        "voltage_difference_v": result.voltage_difference_v,
        "dominant_leg": result.dominant_leg,
    }


def _evaluate_leg_imbalance(
    sample: NormalizedCircuitSample,
    config: CircuitConfig,
    context: ProcessingContext,
) -> LegImbalanceResult:
    if config.mode is not CircuitMode.DUAL_PHASE:
        return LegImbalanceResult(status="not_dual_phase")

    settings = context.store_data.leg_imbalance_settings_by_circuit.get(
        config.circuit_id,
        {},
    )
    return evaluate_dual_phase_leg_imbalance(
        left_real_power_w=getattr(sample, "leg_a_real_power", None),
        right_real_power_w=getattr(sample, "leg_b_real_power", None),
        left_current_a=getattr(sample, "leg_a_current", None),
        right_current_a=getattr(sample, "leg_b_current", None),
        left_voltage_v=getattr(sample, "leg_a_voltage", None),
        right_voltage_v=getattr(sample, "leg_b_voltage", None),
        threshold_ratio=_positive_float_value(
            settings.get("warning_ratio"),
            default=DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
        ),
        minimum_total_power_w=_nonnegative_float_value(
            settings.get("minimum_total_power_w"),
            default=DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
        ),
    )


def _positive_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
