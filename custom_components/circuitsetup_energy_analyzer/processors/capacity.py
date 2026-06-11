"""Circuit capacity tracking processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol

from ..alerting import Observation
from ..capacity import CapacityResult, CapacitySettings, evaluate_circuit_capacity
from ..models import AlertEvidence, CircuitConfig, CircuitMode, SensorRole
from ..normalize import NormalizedCircuitSample, SourceState
from .base import FeatureResult, ProcessingContext, StateUpdate


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type CapacitySettingsProvider = Callable[[str], CapacitySettings]
type CapacityAlertPolicyProvider = Callable[[str], _AlertPolicy]
type RetentionDaysProvider = Callable[[str], int]
type SourceStatesProvider = Callable[
    [CircuitConfig, datetime],
    Mapping[str, SourceState],
]


class CapacityProcessor:
    """Track circuit current samples and configured breaker capacity alerts."""

    name = "capacity"

    def __init__(
        self,
        *,
        settings_for_config: CapacitySettingsProvider,
        alert_policy_for_circuit: CapacityAlertPolicyProvider,
        retention_days_for_circuit: RetentionDaysProvider,
        source_states_for: SourceStatesProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._retention_days_for_circuit = retention_days_for_circuit
        self._source_states_for = source_states_for

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record capacity state and return configured capacity alerts."""
        circuit_id = circuit_config.circuit_id
        current_amps = self._capacity_current_a(circuit_config, sample, context)
        result = evaluate_circuit_capacity(
            circuit_id=circuit_id,
            current_amps=current_amps,
            real_power_w=_capacity_power_w(sample),
            voltage_v=_capacity_voltage_v(circuit_config, sample),
            settings=self._settings_for_config(circuit_id),
        )
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("capacity_usage_by_circuit", circuit_id),
                    result.capacity_usage_percent,
                ),
                StateUpdate(
                    ("capacity_status_by_circuit", circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("capacity_evidence_by_circuit", circuit_id),
                    capacity_evidence_payload(result),
                ),
            ],
            store_dirty=_record_capacity_current_sample(
                context.store_data.demand_by_circuit,
                circuit_id=circuit_id,
                timestamp=context.now,
                current_amps=current_amps,
                retention_days=self._retention_days_for_circuit(circuit_id),
            ),
        )
        if result.status == "over_limit":
            alert = self._capacity_alert(circuit_config, context, result)
            if alert is not None:
                feature_result.alerts.append(alert)
                feature_result.notifications.append(alert)
        return feature_result

    def _capacity_current_a(
        self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample,
        context: ProcessingContext,
    ) -> float | None:
        if config.mode is CircuitMode.DUAL_PHASE:
            leg_currents = self._dual_phase_leg_currents(config, context.now)
            if leg_currents:
                return max(leg_currents)
        current = getattr(sample, "current", None)
        if current is None:
            return None
        if config.mode is CircuitMode.DUAL_PHASE and current > 0.0:
            return float(current) / 2.0
        return float(current)

    def _dual_phase_leg_currents(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> tuple[float, ...]:
        states = self._source_states_for(config, now)
        currents: list[float] = []
        for sensor in config.sensors:
            if sensor.role is not SensorRole.CURRENT:
                continue
            if _normalized_leg(sensor.leg) is None:
                continue
            source = states.get(sensor.entity_id)
            if source is None:
                continue
            try:
                value = float(source.state)
            except ValueError:
                continue
            if value > 0.0:
                currents.append(value)
        return tuple(currents)

    def _capacity_alert(
        self,
        config: CircuitConfig,
        context: ProcessingContext,
        result: CapacityResult,
    ) -> AlertEvidence | None:
        score = (
            result.current_amps / result.warning_threshold_amps
            if result.warning_threshold_amps > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(config.circuit_id).observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="circuit_capacity",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=result.current_amps,
                baseline_value=result.warning_threshold_amps,
                message=capacity_limit_message(config, result),
                features=result.features or {},
            )
        )


def capacity_limit_message(config: CircuitConfig, result: CapacityResult) -> str:
    """Build the user-facing circuit-capacity alert message."""
    return (
        f"Possible issue: {config.name} current is "
        f"{_format_amps(result.current_amps)} A, which is "
        f"{_format_percent(result.capacity_usage_percent)}% of the configured "
        f"{_format_amps(result.breaker_amps)} A circuit capacity. This is above "
        f"the configured {_format_percent(result.warning_ratio * 100)}% warning "
        f"level ({_format_amps(result.warning_threshold_amps)} A)."
    )


def capacity_evidence_payload(result: CapacityResult) -> dict[str, Any]:
    """Build the analyzer state payload for circuit-capacity tracking."""
    return {
        "status": result.status,
        "current_amps": result.current_amps,
        "breaker_amps": result.breaker_amps,
        "warning_threshold_amps": result.warning_threshold_amps,
        "capacity_usage_percent": result.capacity_usage_percent,
        "warning_ratio": result.warning_ratio,
        "current_source": result.current_source,
    }


def _record_capacity_current_sample(
    demand_by_circuit: dict[str, dict[str, Any]],
    *,
    circuit_id: str,
    timestamp: datetime,
    current_amps: float | None,
    retention_days: int,
) -> bool:
    if current_amps is None:
        return False
    try:
        parsed = abs(float(current_amps))
    except (TypeError, ValueError):
        return False

    history = demand_by_circuit.setdefault(circuit_id, {})
    cutoff = timestamp - timedelta(days=retention_days)
    samples = [
        sample
        for sample in _coerce_timestamped_dicts(history.get("capacity_current_samples"))
        if _sample_timestamp_is_at_or_after(sample, cutoff)
    ]
    samples.append(
        {
            "timestamp": timestamp.isoformat(),
            "current_amps": round(parsed, 2),
        }
    )
    history["capacity_current_samples"] = samples
    return True


def _capacity_power_w(sample: NormalizedCircuitSample) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    return abs(float(power))


def _capacity_voltage_v(
    config: CircuitConfig,
    sample: NormalizedCircuitSample,
) -> float | None:
    voltage = getattr(sample, "voltage", None)
    if voltage is None:
        return None
    multiplier = 2.0 if config.mode is CircuitMode.DUAL_PHASE else 1.0
    return abs(float(voltage)) * multiplier


def _coerce_timestamped_dicts(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    return [
        dict(item)
        for item in raw_items
        if isinstance(item, Mapping)
        and _datetime_or_none(item.get("timestamp")) is not None
    ]


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sample_timestamp_is_at_or_after(sample: Any, cutoff: datetime) -> bool:
    if not isinstance(sample, dict):
        return False
    sample_time = _datetime_or_none(sample.get("timestamp"))
    return sample_time is not None and sample_time >= cutoff


def _normalized_leg(leg: str | None) -> str | None:
    if leg is None:
        return None
    value = leg.strip().lower()
    if value in {"a", "left", "l1", "line1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "line2", "2"}:
        return "b"
    return None


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_amps(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
