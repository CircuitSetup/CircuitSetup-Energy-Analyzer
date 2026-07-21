from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .models import CircuitConfig, CircuitSample, PowerFlowMode, SensorRole

STALE_AFTER = timedelta(minutes=10)
FUTURE_TIMESTAMP_TOLERANCE = timedelta(seconds=30)
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
    def apparent_power_va(self) -> float | None:
        return self.apparent_power


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

        timestamp_issue = _timestamp_issue(now, source.last_updated)
        if timestamp_issue is not None:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} {timestamp_issue}")
            continue

        source_last_updated = source.last_updated.astimezone(UTC)
        now_utc = now.astimezone(UTC)
        is_stale = now_utc - source_last_updated > STALE_AFTER
        if is_stale:
            quality_issues.append(f"{sensor.entity_id} stale")

        state = source.state.strip()
        if state.lower() in UNAVAILABLE_STATES:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} unavailable")
            continue
        if is_stale:
            values[sensor.role] = None
            continue

        try:
            value = float(state)
        except ValueError:
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} non_numeric")
            continue
        if not math.isfinite(value):
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} non_finite")
            continue

        if sensor.role in _POWER_ROLES and _is_kw(source.unit):
            value *= 1000
        elif sensor.role is SensorRole.ENERGY:
            value = _normalize_energy_kwh(value, source.unit)
        if not math.isfinite(value):
            values[sensor.role] = None
            quality_issues.append(f"{sensor.entity_id} non_finite")
            continue

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


def _timestamp_issue(now: datetime, source_last_updated: datetime) -> str | None:
    if _is_naive(now) or _is_naive(source_last_updated):
        return "naive_timestamp"
    future_skew = source_last_updated.astimezone(UTC) - now.astimezone(UTC)
    if future_skew > FUTURE_TIMESTAMP_TOLERANCE:
        return "future_timestamp"
    return None


def _is_naive(value: datetime) -> bool:
    return value.tzinfo is None or value.tzinfo.utcoffset(value) is None


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
        and real_power <= -NEGATIVE_LOAD_TOLERANCE_W
    )


def _normalize_real_power(
    real_power: float | None,
    power_flow: PowerFlowMode,
) -> tuple[float | None, str | None]:
    if real_power is None:
        return None, None

    if power_flow is PowerFlowMode.LOAD:
        if real_power <= -NEGATIVE_LOAD_TOLERANCE_W:
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
