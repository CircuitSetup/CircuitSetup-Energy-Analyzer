from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .discovery import (
    sensor_metadata_is_unsupported,
    sensor_metadata_role_conflict,
    sensor_role_from_metadata,
)
from .models import CircuitConfig, CircuitSample, PowerFlowMode, SensorRole

STALE_AFTER = timedelta(minutes=10)
FUTURE_TIMESTAMP_TOLERANCE = timedelta(seconds=30)
UNAVAILABLE_STATES = {"unknown", "unavailable", ""}
NEGATIVE_LOAD_TOLERANCE_W = 5.0

_UNIT_SCALE_BY_ROLE = {
    SensorRole.REAL_POWER: {"kw": 1_000.0, "mw": 0.001, "Mw": 1_000_000.0},
    SensorRole.REACTIVE_POWER: {
        "kvar": 1_000.0,
        "mvar": 0.001,
        "Mvar": 1_000_000.0,
    },
    SensorRole.APPARENT_POWER: {
        "kva": 1_000.0,
        "mva": 0.001,
        "Mva": 1_000_000.0,
    },
    SensorRole.CURRENT: {"ka": 1_000.0, "ma": 0.001, "Ma": 1_000_000.0},
    SensorRole.PEAK_CURRENT: {"ka": 1_000.0, "ma": 0.001, "Ma": 1_000_000.0},
    SensorRole.VOLTAGE: {"kv": 1_000.0, "mv": 0.001, "Mv": 1_000_000.0},
}


def normalize_sensor_value(
    value: float,
    role: SensorRole,
    unit: str | None,
) -> float:
    """Normalize a sensor value to the base unit used for its role."""
    if role is SensorRole.ENERGY:
        return _normalize_energy_kwh(value, unit)
    if unit is None:
        return value
    normalized_unit = unit.strip()
    normalized_unit = (
        normalized_unit[:1].replace("K", "k") + normalized_unit[1:].lower()
    )
    return value * _UNIT_SCALE_BY_ROLE.get(role, {}).get(normalized_unit, 1.0)


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
    source_updated_at_by_role: tuple[tuple[SensorRole, datetime], ...] = ()

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
    *,
    inactive_power_threshold_w: float | None = None,
) -> NormalizedCircuitSample:
    values: dict[SensorRole, float | None] = {}
    source_by_role: dict[SensorRole, str] = {}
    source_updated_at_by_role: dict[SensorRole, datetime] = {}
    quality_issues: list[str] = []
    source_entity_ids = tuple(sensor.entity_id for sensor in config.sensors)

    for sensor in config.sensors:
        source = states.get(sensor.entity_id)
        source_unit = source.unit if source is not None and source.unit else sensor.unit
        metadata_unsupported = sensor_metadata_is_unsupported(
            device_class=source.device_class if source is not None else None,
            unit=source_unit,
        )
        if sensor_metadata_role_conflict(
            device_class=source.device_class if source is not None else None,
            unit=source_unit,
        ):
            quality_issues.append(
                f"{sensor.entity_id} metadata role conflict: "
                f"device_class={source.device_class} unit={source_unit}"
            )
            continue
        metadata_role = sensor_role_from_metadata(
            device_class=source.device_class if source is not None else None,
            unit=source_unit,
        )
        effective_role = metadata_role or sensor.role
        if source is None:
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} missing")
            continue

        if metadata_unsupported:
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} unsupported_metadata")
            continue

        if metadata_role is not None and metadata_role is not sensor.role:
            quality_issues.append(
                f"{sensor.entity_id} configured {sensor.role.value} conflicts with "
                f"metadata {metadata_role.value}"
            )

        timestamp_issue = _timestamp_issue(now, source.last_updated)
        if timestamp_issue is not None:
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} {timestamp_issue}")
            continue

        source_last_updated = source.last_updated.astimezone(UTC)
        now_utc = now.astimezone(UTC)
        is_stale = now_utc - source_last_updated > STALE_AFTER
        if is_stale:
            quality_issues.append(f"{sensor.entity_id} stale")

        state = source.state.strip()
        if state.lower() in UNAVAILABLE_STATES:
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} unavailable")
            continue
        if is_stale:
            values.setdefault(effective_role, None)
            continue

        try:
            value = float(state)
        except ValueError:
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} non_numeric")
            continue
        if not math.isfinite(value):
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} non_finite")
            continue

        value = normalize_sensor_value(value, effective_role, source_unit)
        if not math.isfinite(value):
            values.setdefault(effective_role, None)
            quality_issues.append(f"{sensor.entity_id} non_finite")
            continue

        values[effective_role] = value
        source_by_role[effective_role] = sensor.entity_id
        source_updated_at_by_role[effective_role] = source_last_updated

    raw_real_power = values.get(SensorRole.REAL_POWER)
    real_power, power_flow_direction = _normalize_real_power(
        raw_real_power,
        config.power_flow,
    )
    if _negative_load_power_issue(raw_real_power, config.power_flow):
        entity_id = source_by_role.get(SensorRole.REAL_POWER, "real_power")
        quality_issues.append(f"{entity_id} negative_real_power_load")

    sample = NormalizedCircuitSample(
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
        source_updated_at_by_role=tuple(source_updated_at_by_role.items()),
    )
    return suppress_inactive_stale_current_issues(
        config,
        sample,
        inactive_power_threshold_w,
    )


def suppress_inactive_stale_current_issues(
    config: CircuitConfig,
    sample: NormalizedCircuitSample,
    inactive_power_threshold_w: float | None,
) -> NormalizedCircuitSample:
    if (
        inactive_power_threshold_w is None
        or sample.raw_real_power is None
        or abs(sample.raw_real_power) > inactive_power_threshold_w
    ):
        return sample
    stale_current_issues = {
        f"{sensor.entity_id} stale"
        for sensor in config.sensors
        if sensor.role is SensorRole.CURRENT
    }
    return replace(
        sample,
        quality_issues=tuple(
            issue
            for issue in sample.quality_issues
            if issue not in stale_current_issues
        ),
    )


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
