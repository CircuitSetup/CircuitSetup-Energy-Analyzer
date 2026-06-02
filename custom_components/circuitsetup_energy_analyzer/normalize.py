from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import CircuitConfig, CircuitSample, SensorRole


STALE_AFTER = timedelta(minutes=10)
UNAVAILABLE_STATES = {"unknown", "unavailable", ""}

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


@dataclass(frozen=True, slots=True)
class NormalizedCircuitSample(CircuitSample):
    source_entity_ids: tuple[str, ...] = ()
    quality_issues: tuple[str, ...] = ()

    @property
    def real_power_w(self) -> float | None:
        return self.real_power

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
) -> CircuitSample:
    values: dict[SensorRole, float | None] = {}
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

        values[sensor.role] = value

    return NormalizedCircuitSample(
        timestamp=now,
        circuit_id=config.circuit_id,
        real_power=values.get(SensorRole.REAL_POWER),
        current=values.get(SensorRole.CURRENT),
        voltage=values.get(SensorRole.VOLTAGE),
        reactive_power=values.get(SensorRole.REACTIVE_POWER),
        apparent_power=values.get(SensorRole.APPARENT_POWER),
        power_factor=values.get(SensorRole.POWER_FACTOR),
        frequency=values.get(SensorRole.FREQUENCY),
        source_entity_ids=source_entity_ids,
        quality_issues=tuple(quality_issues),
    )


def _is_kw(unit: str | None) -> bool:
    return unit is not None and unit.strip().lower() == "kw"
