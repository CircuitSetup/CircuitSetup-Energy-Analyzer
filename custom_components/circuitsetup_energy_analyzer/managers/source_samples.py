from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ..aggregation import aggregate_dual_phase
from ..models import CircuitConfig, CircuitMode, PowerFlowMode, SensorRef, SensorRole
from ..normalize import (
    NormalizedCircuitSample,
    SourceState,
    build_circuit_sample,
    suppress_inactive_stale_current_issues,
)


class SourceSampleBuilder:
    """Read HA source states and build normalized circuit samples."""

    def __init__(self, hass: Any) -> None:
        self._hass = hass

    def sample_for_config(
        self,
        config: CircuitConfig,
        now: datetime,
        *,
        inactive_power_threshold_w: float | None = None,
    ) -> NormalizedCircuitSample:
        if config.mode is CircuitMode.MAINS_NILM:
            return self._aggregate_parallel_sample(
                config,
                now,
                inactive_power_threshold_w=inactive_power_threshold_w,
            )
        if config.mode is not CircuitMode.DUAL_PHASE:
            return build_circuit_sample(
                config,
                self.source_states_for(config, now),
                now,
                inactive_power_threshold_w=inactive_power_threshold_w,
            )

        left_sensors = tuple(
            sensor for sensor in config.sensors if normalized_leg(sensor.leg) == "a"
        )
        right_sensors = tuple(
            sensor for sensor in config.sensors if normalized_leg(sensor.leg) == "b"
        )
        if not left_sensors or not right_sensors:
            return build_circuit_sample(
                config,
                self.source_states_for(config, now),
                now,
                inactive_power_threshold_w=inactive_power_threshold_w,
            )

        left_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=left_sensors,
        )
        right_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=right_sensors,
        )
        left_sample = build_circuit_sample(
            left_config,
            self.source_states_for(left_config, now),
            now,
        )
        right_sample = build_circuit_sample(
            right_config,
            self.source_states_for(right_config, now),
            now,
        )
        aggregated = aggregate_dual_phase(config.circuit_id, left_sample, right_sample)
        raw_real_power = _sum_complete_sample_values(
            (left_sample, right_sample),
            "raw_real_power",
        )
        sample = NormalizedCircuitSample(
            timestamp=aggregated.timestamp,
            circuit_id=config.circuit_id,
            real_power=aggregated.combined_real_power,
            current=aggregated.combined_current,
            voltage=aggregated.average_voltage,
            reactive_power=aggregated.combined_reactive_power,
            apparent_power=aggregated.combined_apparent_power,
            power_factor=aggregated.average_power_factor,
            frequency=aggregated.frequency,
            energy=aggregated.energy,
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=aggregated.quality_issues,
            raw_real_power=raw_real_power,
            power_flow=config.power_flow,
            power_flow_direction=_power_flow_direction(
                raw_real_power,
                config.power_flow,
            ),
            leg_a_real_power=aggregated.leg_a.real_power,
            leg_b_real_power=aggregated.leg_b.real_power,
            leg_a_current=aggregated.leg_a.current,
            leg_b_current=aggregated.leg_b.current,
            leg_a_voltage=aggregated.leg_a.voltage,
            leg_b_voltage=aggregated.leg_b.voltage,
            leg_power_imbalance_ratio=aggregated.leg_power_imbalance_ratio,
            voltage_difference=aggregated.voltage_difference,
            source_updated_at_by_role=_merge_source_update_times(
                (left_sample, right_sample)
            ),
        )
        return suppress_inactive_stale_current_issues(
            config,
            sample,
            inactive_power_threshold_w,
        )

    def source_states_for(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, SourceState]:
        states: dict[str, SourceState] = {}
        hass_states = getattr(self._hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return states

        for sensor in config.sensors:
            raw_state = get_state(sensor.entity_id)
            if raw_state is None:
                continue
            attributes = getattr(raw_state, "attributes", {}) or {}
            last_updated = getattr(raw_state, "last_updated", now) or now
            states[sensor.entity_id] = SourceState(
                entity_id=sensor.entity_id,
                state=str(getattr(raw_state, "state", "")),
                unit=attributes.get("unit_of_measurement") or sensor.unit,
                last_updated=last_updated,
                device_class=attributes.get("device_class"),
                state_class=attributes.get("state_class"),
            )
        return states

    def _aggregate_parallel_sample(
        self,
        config: CircuitConfig,
        now: datetime,
        *,
        inactive_power_threshold_w: float | None = None,
    ) -> NormalizedCircuitSample:
        sensor_samples = [
            (
                sensor,
                build_circuit_sample(
                    replace(config, sensors=(sensor,)),
                    self.source_states_for(replace(config, sensors=(sensor,)), now),
                    now,
                ),
            )
            for sensor in config.sensors
        ]
        samples = [sample for _sensor, sample in sensor_samples]
        if not samples:
            return build_circuit_sample(config, {}, now)

        raw_real_power = _sum_parallel_sensor_values(
            sensor_samples,
            "raw_real_power",
            SensorRole.REAL_POWER,
        )
        leg_a_sample, leg_b_sample = _parallel_leg_samples(sensor_samples)
        sample = NormalizedCircuitSample(
            timestamp=max(sample.timestamp for sample in samples),
            circuit_id=config.circuit_id,
            real_power=_sum_parallel_sensor_values(
                sensor_samples,
                "real_power",
                SensorRole.REAL_POWER,
            ),
            current=_sum_parallel_sensor_values(
                sensor_samples,
                "current",
                SensorRole.CURRENT,
            ),
            voltage=_average_sample_values(samples, "voltage"),
            reactive_power=_sum_parallel_sensor_values(
                sensor_samples,
                "reactive_power",
                SensorRole.REACTIVE_POWER,
            ),
            apparent_power=_sum_parallel_sensor_values(
                sensor_samples,
                "apparent_power",
                SensorRole.APPARENT_POWER,
            ),
            power_factor=_average_sample_values(samples, "power_factor"),
            frequency=_average_sample_values(samples, "frequency"),
            energy=_sum_parallel_sensor_values(
                sensor_samples,
                "energy",
                SensorRole.ENERGY,
            ),
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=tuple(
                issue for sample in samples for issue in sample.quality_issues
            ),
            raw_real_power=raw_real_power,
            power_flow=config.power_flow,
            power_flow_direction=_power_flow_direction(
                raw_real_power,
                config.power_flow,
            ),
            leg_a_real_power=_sample_value_or_none(leg_a_sample, "real_power"),
            leg_b_real_power=_sample_value_or_none(leg_b_sample, "real_power"),
            leg_a_current=_sample_value_or_none(leg_a_sample, "current"),
            leg_b_current=_sample_value_or_none(leg_b_sample, "current"),
            leg_a_voltage=_average_leg_sensor_values(
                sensor_samples,
                "voltage",
                SensorRole.VOLTAGE,
                "a",
            ),
            leg_b_voltage=_average_leg_sensor_values(
                sensor_samples,
                "voltage",
                SensorRole.VOLTAGE,
                "b",
            ),
            source_updated_at_by_role=_merge_source_update_times(samples),
        )
        return suppress_inactive_stale_current_issues(
            config,
            sample,
            inactive_power_threshold_w,
        )


def _parallel_leg_samples(
    sensor_samples: list[tuple[SensorRef, NormalizedCircuitSample]],
) -> tuple[NormalizedCircuitSample | None, NormalizedCircuitSample | None]:
    leg_a = next(
        (
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, SensorRole.REAL_POWER)
            and normalized_leg(sensor.leg) == "a"
        ),
        None,
    )
    leg_b = next(
        (
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, SensorRole.REAL_POWER)
            and normalized_leg(sensor.leg) == "b"
        ),
        None,
    )
    if leg_a is not None or leg_b is not None:
        return leg_a, leg_b

    hinted_leg_a = next(
        (
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, SensorRole.REAL_POWER)
            and entity_id_leg_hint(sensor.entity_id) == "a"
        ),
        None,
    )
    hinted_leg_b = next(
        (
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, SensorRole.REAL_POWER)
            and entity_id_leg_hint(sensor.entity_id) == "b"
        ),
        None,
    )
    if hinted_leg_a is not None or hinted_leg_b is not None:
        return hinted_leg_a, hinted_leg_b
    return None, None


def entity_id_leg_hint(entity_id: str) -> str | None:
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in str(entity_id).lower()
    )
    padded = f"_{normalized}_"
    if any(
        pattern in padded
        for pattern in (
            "_l1_",
            "_leg1_",
            "_leg_1_",
            "_line1_",
            "_line_1_",
            "_phase1_",
            "_phase_1_",
            "_ct1_",
            "_leg_a_",
            "_line_a_",
            "_phase_a_",
        )
    ):
        return "a"
    if any(
        pattern in padded
        for pattern in (
            "_l2_",
            "_leg2_",
            "_leg_2_",
            "_line2_",
            "_line_2_",
            "_phase2_",
            "_phase_2_",
            "_ct2_",
            "_leg_b_",
            "_line_b_",
            "_phase_b_",
        )
    ):
        return "b"
    return None


def _sample_value_or_none(
    sample: NormalizedCircuitSample | None,
    attribute: str,
) -> float | None:
    if sample is None:
        return None
    value = getattr(sample, attribute, None)
    if value is None:
        return None
    return float(value)


def _merge_source_update_times(
    samples: list[NormalizedCircuitSample] | tuple[NormalizedCircuitSample, ...],
) -> tuple[tuple[SensorRole, datetime], ...]:
    latest: dict[SensorRole, datetime] = {}
    for sample in samples:
        for role, timestamp in sample.source_updated_at_by_role:
            latest[role] = min(latest.get(role, timestamp), timestamp)
    return tuple(latest.items())


def _sum_complete_sample_values(
    samples: tuple[NormalizedCircuitSample, ...] | list[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    total = 0.0
    has_values = False
    for sample in samples:
        value = getattr(sample, attribute, None)
        if value is None:
            return None
        total += float(value)
        has_values = True
    if not has_values:
        return None
    return total


def _sum_parallel_sensor_values(
    sensor_samples: list[tuple[SensorRef, NormalizedCircuitSample]],
    attribute: str,
    role: SensorRole,
) -> float | None:
    return _sum_complete_sample_values(
        [
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, role)
        ],
        attribute,
    )


def _average_sample_values(
    samples: list[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    values = [
        value
        for sample in samples
        if (value := getattr(sample, attribute, None)) is not None
    ]
    if not values:
        return None
    return float(sum(values) / len(values))


def _average_leg_sensor_values(
    sensor_samples: list[tuple[SensorRef, NormalizedCircuitSample]],
    attribute: str,
    role: SensorRole,
    leg: str,
) -> float | None:
    return _average_sample_values(
        [
            sample
            for sensor, sample in sensor_samples
            if _sensor_sample_has_role(sensor, sample, role)
            and (normalized_leg(sensor.leg) or entity_id_leg_hint(sensor.entity_id))
            == leg
        ],
        attribute,
    )


def _sensor_sample_has_role(
    sensor: SensorRef,
    sample: NormalizedCircuitSample,
    role: SensorRole,
) -> bool:
    source_roles = {
        source_role.value if isinstance(source_role, SensorRole) else str(source_role)
        for source_role, _timestamp in sample.source_updated_at_by_role
    }
    return role.value in source_roles if source_roles else sensor.role is role


def _power_flow_direction(
    raw_real_power: float | None,
    power_flow: PowerFlowMode,
) -> str | None:
    if raw_real_power is None:
        return None
    if power_flow is PowerFlowMode.LOAD:
        return "unexpected_export" if raw_real_power < 0 else "load"
    if power_flow is PowerFlowMode.GENERATION:
        return "export" if raw_real_power < 0 else "import"
    if power_flow is PowerFlowMode.MAINS_NET:
        if raw_real_power > 0:
            return "import"
        if raw_real_power < 0:
            return "export"
        return "balanced"
    return "load"


def normalized_leg(leg: str | None) -> str | None:
    value = str(leg or "").strip().lower()
    if value in {"a", "left", "l1", "leg1", "line1", "phase1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "leg2", "line2", "phase2", "2"}:
        return "b"
    return None
