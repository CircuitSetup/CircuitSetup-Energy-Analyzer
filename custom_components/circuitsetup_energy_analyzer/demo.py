from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import lru_cache
from math import sqrt
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
DEMO_SIMULATION_INTERVAL_SECONDS = 10
DEMO_SIMULATION_WINDOW_DAYS = 14
DEMO_SOURCE_DATA_PATH = Path(__file__).with_name("demo_sources.json")
DEMO_NILM_WORKSPACE_DATA_PATH = Path(__file__).with_name(
    "demo_nilm_workspace.json",
)
_DEMO_SIMULATION_TICKS_PER_DAY = (
    24 * 60 * 60 // DEMO_SIMULATION_INTERVAL_SECONDS
)
_DEMO_SPLIT_LEG_SUFFIXES = ("_l1", "_l2")

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


def demo_simulated_source_value(
    circuit_id: str,
    role: SensorRole,
    tick: int,
) -> float | None:
    """Return the demo source value for a compressed 10-second scenario tick."""
    base = demo_source_value(circuit_id, role)
    if base is None:
        return None
    tick = max(int(tick), 0)
    if tick == 0:
        return float(base)
    if role is SensorRole.ENERGY:
        return round(_demo_simulated_energy(circuit_id, tick, base), 3)
    if role is SensorRole.REAL_POWER:
        return round(_demo_simulated_real_power(circuit_id, tick, base), 3)
    if role is SensorRole.CURRENT:
        return round(_demo_simulated_current(circuit_id, tick, base), 3)
    if role is SensorRole.POWER_FACTOR:
        return round(_demo_simulated_power_factor(circuit_id, tick, base), 3)
    if role is SensorRole.APPARENT_POWER:
        return round(_demo_simulated_apparent_power(circuit_id, tick), 3)
    if role is SensorRole.REACTIVE_POWER:
        apparent = _demo_simulated_apparent_power(circuit_id, tick)
        real = _demo_simulated_real_power(
            circuit_id,
            tick,
            demo_source_value(circuit_id, SensorRole.REAL_POWER) or 0.0,
        )
        return round(sqrt(max((apparent * apparent) - (real * real), 0.0)), 3)
    if role is SensorRole.VOLTAGE:
        return round(_demo_simulated_voltage(circuit_id, tick, base), 3)
    return float(base)


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


def _demo_simulated_energy(circuit_id: str, tick: int, base: float) -> float:
    key = _demo_scenario_key(circuit_id)
    daily_usage = DEMO_PRIOR_DAILY_USAGE_KWH.get(
        key,
        DEMO_PRIOR_DAILY_USAGE_KWH["refrigerator"],
    )
    if circuit_id.endswith(_DEMO_SPLIT_LEG_SUFFIXES):
        daily_usage = tuple(value * 0.5 for value in daily_usage)
    day, day_tick = divmod(tick, _DEMO_SIMULATION_TICKS_PER_DAY)
    cycles, day_index = divmod(day, DEMO_SIMULATION_WINDOW_DAYS)
    window_usage = tuple(
        float(daily_usage[index % len(daily_usage)])
        for index in range(DEMO_SIMULATION_WINDOW_DAYS)
    )
    return (
        float(base)
        + cycles * sum(window_usage)
        + sum(window_usage[:day_index])
        + window_usage[day_index] * day_tick / _DEMO_SIMULATION_TICKS_PER_DAY
    )


def _demo_simulated_real_power(circuit_id: str, tick: int, base: float) -> float:
    key = _demo_scenario_key(circuit_id)
    day, day_tick = _demo_day_and_tick(tick)
    multiplier = 0.05
    if key == "mains":
        multiplier = 0.75
        if _in_demo_window(day_tick, 7.0, 180) or _in_demo_window(
            day_tick,
            17.0,
            240,
        ):
            multiplier = 1.25
        if day % 5 == 2 and _in_demo_window(day_tick, 13.0, 120):
            multiplier = 1.6
    elif key in {"refrigerator", "freezer"}:
        multiplier = 1.05 if (day_tick // (45 * 60 // 10)) % 2 == 0 else 0.12
        if day % 4 == 1 and _in_demo_window(day_tick, 14.0, 180):
            multiplier = 1.7
    elif key == "hvac":
        multiplier = 1.15 if _in_demo_window(day_tick, 12.0, 360) else 0.15
        if _in_demo_window(day_tick, 18.0, 240):
            multiplier = 0.9
        if day % 5 == 2 and _in_demo_window(day_tick, 13.0, 120):
            multiplier = 1.8 if circuit_id.endswith("_l1") else 0.35
    elif key == "water_heater":
        if _in_demo_window(day_tick, 6.0, 90) or _in_demo_window(day_tick, 19.0, 60):
            multiplier = 1.2
    elif key == "washer":
        if day % 2 == 0 and _in_demo_window(day_tick, 9.0, 80):
            multiplier = 1.2
        if day % 7 == 3 and _in_demo_window(day_tick, 9.0, 210):
            multiplier = 1.4
    elif key == "dryer":
        if day % 2 == 0 and _in_demo_window(day_tick, 10.5, 70):
            multiplier = 1.1
        if day % 7 == 3 and _in_demo_window(day_tick, 11.0, 140):
            multiplier = 1.3
    elif key == "car_charger":
        if _in_demo_window(day_tick, 1.0, 180):
            multiplier = 1.0
        if day % 3 == 0 and _in_demo_window(day_tick, 22.0, 240):
            multiplier = 1.4
    elif key == "pool_pump":
        multiplier = 1.0 if _in_demo_window(day_tick, 10.0, 360) else 0.08
        if day % 4 == 1 and _in_demo_window(day_tick, 10.0, 540):
            multiplier = 1.25
    elif key == "sump_pump":
        multiplier = 0.02
        if day in {2, 5, 9} and _demo_burst(day_tick, every_minutes=50, on_minutes=4):
            multiplier = 1.5
        elif _demo_burst(day_tick, every_minutes=180, on_minutes=2):
            multiplier = 0.6
    elif key == "microwave":
        if day % 2 == 0 and _in_demo_window(day_tick, 18.0, 10):
            multiplier = 1.0
    elif key == "oven":
        if day % 3 == 0 and _in_demo_window(day_tick, 17.5, 90):
            multiplier = 1.0
    wobble = 1.0 + ((tick % 6) - 2.5) * 0.01
    return max(float(base) * multiplier * wobble, 0.0)


def _demo_simulated_current(circuit_id: str, tick: int, base: float) -> float:
    base_power = demo_source_value(circuit_id, SensorRole.REAL_POWER) or 0.0
    if base_power <= 0.0:
        return float(base)
    return (
        float(base)
        * _demo_simulated_real_power(circuit_id, tick, base_power)
        / base_power
    )


def _demo_simulated_power_factor(circuit_id: str, tick: int, base: float) -> float:
    key = _demo_scenario_key(circuit_id)
    day, day_tick = _demo_day_and_tick(tick)
    if (
        key in {"hvac", "pool_pump", "sump_pump", "refrigerator", "freezer"}
        and day % 5 == 2
        and _in_demo_window(day_tick, 13.0, 120)
    ):
        return max(float(base) - 0.25, 0.42)
    return float(base)


def _demo_simulated_apparent_power(circuit_id: str, tick: int) -> float:
    real = _demo_simulated_real_power(
        circuit_id,
        tick,
        demo_source_value(circuit_id, SensorRole.REAL_POWER) or 0.0,
    )
    key = _demo_scenario_key(circuit_id)
    day, day_tick = _demo_day_and_tick(tick)
    if key == "microwave" and day % 7 == 4 and _in_demo_window(day_tick, 18.0, 10):
        return real * 0.65
    power_factor = _demo_simulated_power_factor(
        circuit_id,
        tick,
        demo_source_value(circuit_id, SensorRole.POWER_FACTOR) or 0.95,
    )
    return real / max(power_factor, 0.1)


def _demo_simulated_voltage(circuit_id: str, tick: int, base: float) -> float:
    key = _demo_scenario_key(circuit_id)
    day, day_tick = _demo_day_and_tick(tick)
    if key in {"hvac", "pool_pump", "sump_pump"} and _demo_burst(
        day_tick,
        every_minutes=45,
        on_minutes=1,
    ):
        return float(base) - 5.0
    return float(base) + ((day % 3) - 1) * 0.4


def _demo_scenario_key(circuit_id: str) -> str:
    key = demo_circuit_key_from_id(circuit_id)
    for suffix in _DEMO_SPLIT_LEG_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _demo_day_and_tick(tick: int) -> tuple[int, int]:
    day, day_tick = divmod(tick, _DEMO_SIMULATION_TICKS_PER_DAY)
    return day % DEMO_SIMULATION_WINDOW_DAYS, day_tick


def _in_demo_window(day_tick: int, start_hour: float, minutes: int) -> bool:
    start = int(start_hour * 60 * 60 / DEMO_SIMULATION_INTERVAL_SECONDS)
    duration = int(minutes * 60 / DEMO_SIMULATION_INTERVAL_SECONDS)
    return start <= day_tick < start + duration


def _demo_burst(day_tick: int, *, every_minutes: int, on_minutes: int) -> bool:
    cycle_ticks = every_minutes * 60 // DEMO_SIMULATION_INTERVAL_SECONDS
    on_ticks = on_minutes * 60 // DEMO_SIMULATION_INTERVAL_SECONDS
    return cycle_ticks > 0 and day_tick % cycle_ticks < on_ticks


def demo_nilm_workspace_seed(
    now: datetime,
    *,
    circuit_id: str = "mains_nilm",
) -> dict[str, Any]:
    """Return the bundled NILM demo workspace scenario for a point in time."""
    return _resolve_demo_seed_values(
        DEMO_NILM_WORKSPACE_SEED_TEMPLATE,
        now,
        circuit_id,
    )


@lru_cache(maxsize=1)
def _demo_nilm_workspace_seed_template() -> dict[str, Any]:
    return json.loads(DEMO_NILM_WORKSPACE_DATA_PATH.read_text(encoding="utf-8"))


DEMO_NILM_WORKSPACE_SEED_TEMPLATE = _demo_nilm_workspace_seed_template()


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
