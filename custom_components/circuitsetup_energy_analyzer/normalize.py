from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import CircuitConfig, CircuitSample, PowerFlowMode, SensorRole

STALE_AFTER = timedelta(minutes=10)
UNAVAILABLE_STATES = {"unknown", "unavailable", ""}
NEGATIVE_LOAD_TOLERANCE_W = 5.0

_POWER_ROLES = {
    SensorRole.REAL_POWER,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
}


@dataclass(frozen=True, slots=True)
class SourceState:
    entity_id: str
    state: str
    unit: str | None
    last_updated: datetime
    device_class: str | None = None
    state_class: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedCircuitSample(CircuitSample):
    source_entity_ids: tuple[str, ...] = ()
    quality_issues: tuple[str, ...] = ()
    raw_real_power: float | None = None
    power_flow: PowerFlowMode = PowerFlowMode.LOAD
    power_flow_direction: str | None = None
    leg_a_real_power: float | None = None
    leg_b_real_power: float | None = None
    leg_a_current: float | None = None
    leg_b_current: float | None = None
    leg_a_voltage: float | None = None
    leg_b_voltage: float | None = None
    leg_power_imbalance_ratio: float | None = None
    voltage_difference: float | None = None

    @property
    def real_power_w(self) -> float | None:
        return self.real_power

    @property
    def raw_real_power_w(self) -> float | None:
        return self.raw_real_power

    @property
    def reactive_power_var(self) -> float | None:
        return self.reactive_power

    @property
    def apparent_power_va(self) -> float | None:
        return self.apparent_power

    @property
    def frequency_hz(self) -> float | None:
        return self.frequency


def build_circuit_sample(
    config: CircuitConfig,
    states: dict[str, SourceState],
    now: datetime,
) -> NormalizedCircuitSample:
    values: dict[SensorRole, float | None] = {}
    source_by_role: dict[SensorRole, str] = {}
    quality_issues: list[str] = []
    source_entity_ids = tuple(sensor.entity_id for sensor in config.sensors)

    for sensor in config.sensors:
        source = states.get(sensor.entity_id)
        if source is None:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} missing")
            continue

        if now - source.last_updated > STALE_AFTER:
            quality_issues.append(f"{sensor.entity_id} stale")

        state = source.state.strip()
        if state.lower() in UNAVAILABLE_STATES:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} unavailable")
            continue

        try:
            value = float(state)
        except ValueError:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} non_numeric")
            continue

        if sensor.role in _POWER_ROLES and _is_kw(source.unit):
            value *= 1000
        elif sensor.role is SensorRole.ENERGY:
            value = _normalize_energy_kwh(value, source.unit)

        values[sensor.role] = value
        source_by_role[sensor.role] = sensor.entity_id

    raw_real_power = values.get(SensorRole.REAL_POWER)
    real_power, power_flow_direction = _normalize_real_power(
        raw_real_power,
        config.power_flow,
    )
    if _negative_load_power_issue(raw_real_power, config.power_flow):
        entity_id = source_by_role.get(SensorRole.REAL_POWER, "real_power")
        quality_issues.append(f"{entity_id} negative_real_power_load")

    return NormalizedCircuitSample(
        timestamp=now,
        circuit_id=config.circuit_id,
        real_power=real_power,
        current=values.get(SensorRole.CURRENT),
        voltage=values.get(SensorRole.VOLTAGE),
        reactive_power=values.get(SensorRole.REACTIVE_POWER),
        apparent_power=values.get(SensorRole.APPARENT_POWER),
        power_factor=values.get(SensorRole.POWER_FACTOR),
        frequency=values.get(SensorRole.FREQUENCY),
        energy=values.get(SensorRole.ENERGY),
        source_entity_ids=source_entity_ids,
        quality_issues=tuple(quality_issues),
        raw_real_power=raw_real_power,
        power_flow=config.power_flow,
        power_flow_direction=power_flow_direction,
    )


def _is_kw(unit: str | None) -> bool:
    return unit is not None and unit.strip().lower() == "kw"


def _normalize_energy_kwh(value: float, unit: str | None) -> float:
    if unit is None:
        return value
    normalized = unit.strip().lower()
    if normalized == "wh":
        return value / 1000
    if normalized == "mwh":
        return value * 1000
    return value


def _negative_load_power_issue(
    real_power: float | None,
    power_flow: PowerFlowMode,
) -> bool:
    return (
        power_flow is PowerFlowMode.LOAD
        and real_power is not None
        and real_power < -NEGATIVE_LOAD_TOLERANCE_W
    )


def _normalize_real_power(
    real_power: float | None,
    power_flow: PowerFlowMode,
) -> tuple[float | None, str | None]:
    if real_power is None:
        return None, None

    if power_flow is PowerFlowMode.LOAD:
        if real_power < -NEGATIVE_LOAD_TOLERANCE_W:
            return None, "unexpected_export"
        return max(real_power, 0.0), "load"

    if power_flow is PowerFlowMode.GENERATION:
        if real_power < 0:
            return abs(real_power), "export"
        return 0.0, "import"

    if real_power > 0:
        return real_power, "import"
    if real_power < 0:
        return real_power, "export"
    return 0.0, "balanced"
