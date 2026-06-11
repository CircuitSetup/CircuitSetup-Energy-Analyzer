"""Power metric consistency processor."""

from __future__ import annotations

from typing import Any

from ..metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
    MetricConsistencyResult,
    evaluate_metric_consistency,
)
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate


class MetricConsistencyProcessor:
    """Track consistency between W, VA, V, A, and power factor."""

    name = "metric_consistency"

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return state updates for the sample's power metric consistency."""
        settings = context.store_data.metric_consistency_settings_by_circuit.get(
            circuit_config.circuit_id,
            {},
        )
        result = evaluate_metric_consistency(
            real_power_w=getattr(sample, "real_power", None),
            apparent_power_va=getattr(sample, "apparent_power", None),
            power_factor=getattr(sample, "power_factor", None),
            voltage_v=getattr(sample, "voltage", None),
            current_a=getattr(sample, "current", None),
            leg_a_voltage_v=getattr(sample, "leg_a_voltage", None),
            leg_a_current_a=getattr(sample, "leg_a_current", None),
            leg_b_voltage_v=getattr(sample, "leg_b_voltage", None),
            leg_b_current_a=getattr(sample, "leg_b_current", None),
            apparent_power_tolerance_percent=_positive_float_value(
                settings.get("apparent_power_tolerance_percent"),
                default=DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
            ),
            power_factor_tolerance=_positive_float_value(
                settings.get("power_factor_tolerance"),
                default=DEFAULT_POWER_FACTOR_TOLERANCE,
            ),
            minimum_apparent_power_va=_nonnegative_float_value(
                settings.get("minimum_apparent_power_va"),
                default=DEFAULT_MIN_APPARENT_POWER_VA,
            ),
        )
        circuit_id = circuit_config.circuit_id
        return FeatureResult(
            state_updates=[
                StateUpdate(
                    ("metric_consistency_score_by_circuit", circuit_id),
                    result.mismatch_score_percent,
                ),
                StateUpdate(
                    ("metric_consistency_status_by_circuit", circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("metric_consistency_evidence_by_circuit", circuit_id),
                    metric_consistency_evidence_payload(result),
                ),
            ],
        )


def metric_consistency_evidence_payload(
    result: MetricConsistencyResult,
) -> dict[str, Any]:
    """Build the analyzer state payload for power metric consistency."""
    return {
        "status": result.status,
        "mismatch_score_percent": result.mismatch_score_percent,
        "expected_apparent_power_va": result.expected_apparent_power_va,
        "reported_apparent_power_va": result.reported_apparent_power_va,
        "apparent_power_difference_percent": (
            result.apparent_power_difference_percent
        ),
        "apparent_power_tolerance_percent": (
            result.apparent_power_tolerance_percent
        ),
        "apparent_power_source": result.apparent_power_source,
        "expected_power_factor": result.expected_power_factor,
        "reported_power_factor": result.reported_power_factor,
        "power_factor_difference": result.power_factor_difference,
        "power_factor_tolerance": result.power_factor_tolerance,
    }


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
