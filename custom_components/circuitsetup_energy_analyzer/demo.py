from __future__ import annotations

from .models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    SensorRole,
)

DEMO_SOURCE_ENTITY_PREFIX = "sensor.cs_energy_analyzer_demo_"
DEMO_HISTORY_SEED_VERSION = 1

DEMO_SOURCE_METRICS = (
    "energy",
    "active_power",
    "current",
    "power_factor",
    "reactive_power",
    "apparent_power",
)
DEMO_SOURCE_ENTITY_IDS = tuple(
    f"sensor.cs_energy_analyzer_demo_{leg}_{metric}"
    for leg in ("mains_l1", "mains_l2")
    for metric in (*DEMO_SOURCE_METRICS, "voltage")
) + tuple(
    f"sensor.cs_energy_analyzer_demo_{circuit}_{metric}"
    for circuit in ("refrigerator", "washer", "pool_pump")
    for metric in DEMO_SOURCE_METRICS
) + tuple(
    f"sensor.cs_energy_analyzer_demo_{circuit}_{leg}_{metric}"
    for circuit in ("hvac", "water_heater", "dryer", "car_charger")
    for leg in ("l1", "l2")
    for metric in DEMO_SOURCE_METRICS
)

DEMO_SOURCE_VALUES: dict[str, dict[SensorRole, float]] = {
    "mains_l1": {
        SensorRole.ENERGY: 868.4,
        SensorRole.REAL_POWER: 1850.0,
        SensorRole.CURRENT: 15.4,
        SensorRole.POWER_FACTOR: 0.96,
        SensorRole.REACTIVE_POWER: 520.0,
        SensorRole.APPARENT_POWER: 1927.0,
        SensorRole.VOLTAGE: 119.6,
        SensorRole.FREQUENCY: 60.0,
    },
    "mains_l2": {
        SensorRole.ENERGY: 852.7,
        SensorRole.REAL_POWER: 1680.0,
        SensorRole.CURRENT: 14.1,
        SensorRole.POWER_FACTOR: 0.95,
        SensorRole.REACTIVE_POWER: 470.0,
        SensorRole.APPARENT_POWER: 1768.0,
        SensorRole.VOLTAGE: 120.3,
        SensorRole.FREQUENCY: 60.0,
    },
    "refrigerator": {
        SensorRole.ENERGY: 52.6,
        SensorRole.REAL_POWER: 285.0,
        SensorRole.CURRENT: 2.8,
        SensorRole.POWER_FACTOR: 0.58,
        SensorRole.REACTIVE_POWER: 400.0,
        SensorRole.APPARENT_POWER: 492.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "hvac_l1": {
        SensorRole.ENERGY: 188.4,
        SensorRole.REAL_POWER: 3300.0,
        SensorRole.CURRENT: 28.0,
        SensorRole.POWER_FACTOR: 0.72,
        SensorRole.REACTIVE_POWER: 3100.0,
        SensorRole.APPARENT_POWER: 4580.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "hvac_l2": {
        SensorRole.ENERGY: 171.9,
        SensorRole.REAL_POWER: 900.0,
        SensorRole.CURRENT: 7.4,
        SensorRole.POWER_FACTOR: 0.95,
        SensorRole.REACTIVE_POWER: 300.0,
        SensorRole.APPARENT_POWER: 947.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "water_heater_l1": {
        SensorRole.ENERGY: 84.3,
        SensorRole.REAL_POWER: 2050.0,
        SensorRole.CURRENT: 17.2,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 210.0,
        SensorRole.APPARENT_POWER: 2071.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "water_heater_l2": {
        SensorRole.ENERGY: 84.1,
        SensorRole.REAL_POWER: 2050.0,
        SensorRole.CURRENT: 17.1,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 205.0,
        SensorRole.APPARENT_POWER: 2071.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "washer": {
        SensorRole.ENERGY: 14.2,
        SensorRole.REAL_POWER: 420.0,
        SensorRole.CURRENT: 4.2,
        SensorRole.POWER_FACTOR: 0.83,
        SensorRole.REACTIVE_POWER: 280.0,
        SensorRole.APPARENT_POWER: 506.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "dryer_l1": {
        SensorRole.ENERGY: 63.7,
        SensorRole.REAL_POWER: 2600.0,
        SensorRole.CURRENT: 21.8,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 260.0,
        SensorRole.APPARENT_POWER: 2626.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "dryer_l2": {
        SensorRole.ENERGY: 63.1,
        SensorRole.REAL_POWER: 2550.0,
        SensorRole.CURRENT: 21.2,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 250.0,
        SensorRole.APPARENT_POWER: 2576.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "car_charger_l1": {
        SensorRole.ENERGY: 151.4,
        SensorRole.REAL_POWER: 4600.0,
        SensorRole.CURRENT: 38.5,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 460.0,
        SensorRole.APPARENT_POWER: 4646.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "car_charger_l2": {
        SensorRole.ENERGY: 150.8,
        SensorRole.REAL_POWER: 4550.0,
        SensorRole.CURRENT: 37.9,
        SensorRole.POWER_FACTOR: 0.99,
        SensorRole.REACTIVE_POWER: 450.0,
        SensorRole.APPARENT_POWER: 4596.0,
        SensorRole.FREQUENCY: 60.0,
    },
    "pool_pump": {
        SensorRole.ENERGY: 77.6,
        SensorRole.REAL_POWER: 950.0,
        SensorRole.CURRENT: 10.1,
        SensorRole.POWER_FACTOR: 0.86,
        SensorRole.REACTIVE_POWER: 580.0,
        SensorRole.APPARENT_POWER: 1105.0,
        SensorRole.FREQUENCY: 60.0,
    },
}

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

DEMO_PRIOR_DAILY_USAGE_KWH: dict[str, tuple[float, ...]] = {
    "refrigerator": (1.1, 1.2, 1.3, 1.1, 1.4, 1.2, 1.3),
    "hvac": (24.0, 28.5, 31.2, 27.8, 33.1, 29.4, 30.6),
    "water_heater": (5.8, 6.1, 5.9, 6.4, 6.0, 6.2, 5.7),
    "washer": (0.7, 0.9, 0.6, 1.1, 0.8, 1.0, 0.7),
    "dryer": (2.7, 3.2, 2.9, 3.5, 3.0, 3.4, 2.8),
    "pool_pump": (4.2, 4.4, 4.1, 4.5, 4.3, 4.6, 4.2),
    "car_charger": (9.6, 12.4, 10.1, 14.8, 8.5, 13.2, 11.1),
    "mains_nilm": (46.0, 51.2, 49.8, 54.4, 52.1, 48.7, 50.3),
    "mains": (46.0, 51.2, 49.8, 54.4, 52.1, 48.7, 50.3),
}
DEMO_TODAY_USAGE_KWH: dict[str, float] = {
    "refrigerator": 2.6,
    "hvac": 62.0,
    "water_heater": 10.8,
    "washer": 1.8,
    "dryer": 6.7,
    "pool_pump": 7.4,
    "car_charger": 26.0,
    "mains_nilm": 78.0,
    "mains": 78.0,
}


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
