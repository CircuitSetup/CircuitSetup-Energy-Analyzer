from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    SensorRole,
)

DEMO_SOURCE_ENTITY_PREFIX = "sensor.cs_energy_analyzer_demo_"
DEMO_HISTORY_SEED_VERSION = 1
DEMO_SOURCE_DATA_PATH = Path(__file__).with_name("demo_sources.json")
DEMO_NILM_WORKSPACE_DATA_PATH = Path(__file__).with_name(
    "demo_nilm_workspace.json",
)

_DEMO_SOURCE_ENTITY_SENSOR_ROLES = (
    SensorRole.ENERGY,
    SensorRole.REAL_POWER,
    SensorRole.CURRENT,
    SensorRole.POWER_FACTOR,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.VOLTAGE,
)
_DEMO_SOURCE_ENTITY_ROLE_SUFFIXES = {
    SensorRole.REAL_POWER: "active_power",
}


@lru_cache(maxsize=1)
def _demo_source_data() -> dict[str, Any]:
    return json.loads(DEMO_SOURCE_DATA_PATH.read_text(encoding="utf-8"))


def _demo_source_values() -> dict[str, dict[SensorRole, float]]:
    values: dict[str, dict[SensorRole, float]] = {}
    raw_values = _demo_source_data().get("source_values", {})
    if not isinstance(raw_values, Mapping):
        return values
    for circuit_id, raw_circuit_values in raw_values.items():
        if not isinstance(raw_circuit_values, Mapping):
            continue
        circuit_values: dict[SensorRole, float] = {}
        for role_value, raw_value in raw_circuit_values.items():
            try:
                role = SensorRole(str(role_value))
                circuit_values[role] = float(raw_value)
            except (TypeError, ValueError):
                continue
        if circuit_values:
            values[str(circuit_id)] = circuit_values
    return values


def _demo_source_entity_ids(
    source_values: Mapping[str, Mapping[SensorRole, float]],
) -> tuple[str, ...]:
    return tuple(
        f"{DEMO_SOURCE_ENTITY_PREFIX}{circuit_id}_"
        f"{_DEMO_SOURCE_ENTITY_ROLE_SUFFIXES.get(role, role.value)}"
        for circuit_id, circuit_values in source_values.items()
        for role in circuit_values
        if role in _DEMO_SOURCE_ENTITY_SENSOR_ROLES
    )


def _demo_tuple_mapping(key: str) -> dict[str, tuple[float, ...]]:
    values: dict[str, tuple[float, ...]] = {}
    raw_values = _demo_source_data().get(key, {})
    if not isinstance(raw_values, Mapping):
        return values
    for circuit_id, raw_series in raw_values.items():
        if not isinstance(raw_series, list):
            continue
        values[str(circuit_id)] = tuple(float(value) for value in raw_series)
    return values


def _demo_float_mapping(key: str) -> dict[str, float]:
    raw_values = _demo_source_data().get(key, {})
    if not isinstance(raw_values, Mapping):
        return {}
    return {
        str(circuit_id): float(value)
        for circuit_id, value in raw_values.items()
    }


DEMO_SOURCE_VALUES = _demo_source_values()
DEMO_SOURCE_ENTITY_IDS = _demo_source_entity_ids(DEMO_SOURCE_VALUES)

DEMO_SOURCE_ROLE_METADATA: dict[SensorRole, dict[str, str]] = {
    SensorRole.ENERGY: {
        "device_class": "energy",
        "state_class": "total_increasing",
        "unit": "kWh",
        "icon": "mdi:counter",
    },
    SensorRole.REAL_POWER: {
        "device_class": "power",
        "state_class": "measurement",
        "unit": "W",
        "icon": "mdi:flash",
    },
    SensorRole.CURRENT: {
        "device_class": "current",
        "state_class": "measurement",
        "unit": "A",
        "icon": "mdi:current-ac",
    },
    SensorRole.POWER_FACTOR: {
        "device_class": "power_factor",
        "state_class": "measurement",
        "unit": "",
        "icon": "mdi:cosine-wave",
    },
    SensorRole.REACTIVE_POWER: {
        "device_class": "reactive_power",
        "state_class": "measurement",
        "unit": "var",
        "icon": "mdi:flash-triangle-outline",
    },
    SensorRole.APPARENT_POWER: {
        "device_class": "apparent_power",
        "state_class": "measurement",
        "unit": "VA",
        "icon": "mdi:flash-outline",
    },
    SensorRole.VOLTAGE: {
        "device_class": "voltage",
        "state_class": "measurement",
        "unit": "V",
        "icon": "mdi:sine-wave",
    },
    SensorRole.FREQUENCY: {
        "device_class": "frequency",
        "state_class": "measurement",
        "unit": "Hz",
        "icon": "mdi:sine-wave",
    },
}

DEMO_PRIOR_DAILY_USAGE_KWH = _demo_tuple_mapping("prior_daily_usage_kwh")
DEMO_TODAY_USAGE_KWH = _demo_float_mapping("today_usage_kwh")


def is_demo_source_entity_id(entity_id: str) -> bool:
    """Return whether the entity belongs to the bundled demo dataset."""
    return str(entity_id).startswith(DEMO_SOURCE_ENTITY_PREFIX)


def is_demo_config(config: CircuitConfig) -> bool:
    """Return whether any configured source sensor comes from the demo dataset."""
    return any(is_demo_source_entity_id(sensor.entity_id) for sensor in config.sensors)


def demo_circuit_key(config: CircuitConfig) -> str:
    """Return the normalized demo key for seeded history templates."""
    if (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    ):
        return "mains_nilm"
    return demo_circuit_key_from_id(config.circuit_id)


def demo_circuit_key_from_id(circuit_id: str) -> str:
    """Return the normalized demo key from a circuit id."""
    return str(circuit_id).removeprefix("cs_energy_analyzer_demo_")


def demo_circuit_id_from_entity_id(entity_id: str) -> str:
    """Return the demo circuit id embedded in a demo source entity id."""
    object_id = entity_id.removeprefix(DEMO_SOURCE_ENTITY_PREFIX)
    suffixes = (
        "_reactive_power",
        "_apparent_power",
        "_power_factor",
        "_active_power",
        "_frequency",
        "_voltage",
        "_current",
        "_energy",
    )
    for suffix in suffixes:
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def demo_source_value(circuit_id: str, role: SensorRole) -> float | None:
    """Return a representative current value for a demo source sensor."""
    circuit_values = DEMO_SOURCE_VALUES.get(circuit_id, {})
    if role in circuit_values:
        return circuit_values[role]
    return DEMO_SOURCE_VALUES.get("pool_pump", {}).get(role)


def demo_prior_usage(circuit_key: str, window_days: int) -> tuple[float, ...]:
    """Return seeded daily kWh history for demo energy usage diagnostics."""
    template = DEMO_PRIOR_DAILY_USAGE_KWH.get(
        circuit_key,
        DEMO_PRIOR_DAILY_USAGE_KWH["refrigerator"],
    )
    return tuple(float(template[index % len(template)]) for index in range(window_days))


def demo_today_usage(circuit_key: str, energy_kwh: float) -> float:
    """Return seeded current-day kWh usage for demo spike diagnostics."""
    preferred = DEMO_TODAY_USAGE_KWH.get(circuit_key, max(energy_kwh * 0.15, 0.5))
    if energy_kwh <= preferred:
        return round(max(energy_kwh * 0.2, 0.001), 3)
    return round(float(preferred), 3)


def demo_baseline(feature: str, value: float) -> BaselineStats:
    """Return a compact baseline around a demo feature value."""
    spread_floor = 0.01 if "ratio" in feature or "factor" in feature else 5.0
    spread = max(abs(float(value)) * 0.05, spread_floor)
    return BaselineStats(
        feature=feature,
        sample_count=20,
        median=float(value),
        mad=spread,
        p10=float(value) - spread,
        p90=float(value) + spread,
        confidence=1.0,
    )


def demo_nilm_workspace_seed(
    now: datetime,
    *,
    circuit_id: str = "mains_nilm",
) -> dict[str, Any]:
    """Return the bundled NILM demo workspace scenario for a point in time."""
    return _resolve_demo_seed_values(
        _demo_nilm_workspace_seed_template(),
        now,
        circuit_id,
    )


@lru_cache(maxsize=1)
def _demo_nilm_workspace_seed_template() -> dict[str, Any]:
    return json.loads(DEMO_NILM_WORKSPACE_DATA_PATH.read_text(encoding="utf-8"))


def _resolve_demo_seed_values(value: Any, now: datetime, circuit_id: str) -> Any:
    if isinstance(value, dict):
        if set(value) == {"offset_seconds"}:
            return (
                now + timedelta(seconds=float(value["offset_seconds"]))
            ).isoformat()
        return {
            str(key): _resolve_demo_seed_values(item, now, circuit_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_demo_seed_values(item, now, circuit_id)
            for item in value
        ]
    if value == "$circuit_id":
        return circuit_id
    return value
