from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import SensorRole

ENERGY_SOURCE_DEVICE_CLASSES = (
    "apparent_power",
    "current",
    "energy",
    "frequency",
    "power",
    "power_factor",
    "reactive_energy",
    "reactive_power",
    "voltage",
)
_DEVICE_CLASSES = set(ENERGY_SOURCE_DEVICE_CLASSES)
_ENERGY_SOURCE_UNITS = {
    "a",
    "hz",
    "ka",
    "kva",
    "kvar",
    "kvarh",
    "kv",
    "kw",
    "kwh",
    "ma",
    "mva",
    "mvar",
    "mv",
    "mw",
    "mwh",
    "v",
    "va",
    "var",
    "varh",
    "w",
    "wh",
}


@dataclass(frozen=True, slots=True)
class DiscoveredSensor:
    """Candidate Home Assistant source sensor."""

    entity_id: str
    name: str
    role: SensorRole | None
    device_id: str | None
    unit: str | None
    device_class: str | None
    integration_domain: str | None


def infer_sensor_role(entity_id: str, friendly_name: str | None) -> SensorRole | None:
    """Infer the analysis role from common energy meter sensor names."""
    text = _normalize_text(entity_id, friendly_name)

    if "reactive power" in text:
        return SensorRole.REACTIVE_POWER
    if "apparent power" in text:
        return SensorRole.APPARENT_POWER
    if "power factor" in text:
        return SensorRole.POWER_FACTOR
    if "voltage" in text:
        return SensorRole.VOLTAGE
    if "current" in text or re.search(r"\bamps?\b", text):
        return SensorRole.CURRENT
    if "frequency" in text:
        return SensorRole.FREQUENCY
    if "power" in text or re.search(r"\bwatts?\b", text):
        return SensorRole.REAL_POWER
    if re.search(r"\b(?:kwh|wh)\b", text) or re.search(
        r"\benergy\b(?!\s+meter\b)",
        text,
    ):
        return SensorRole.ENERGY
    return None


def score_circuitsetup_candidate(sensor: DiscoveredSensor) -> int:
    """Score likely CircuitSetup energy meter sensors higher."""
    score = 0
    text = f"{sensor.entity_id} {sensor.name}".lower()

    if sensor.integration_domain == "esphome":
        score += 2
    if "circuitsetup" in text:
        score += 2
    if "energy" in text or "meter" in text:
        score += 1
    if sensor.role is not None:
        score += 1
    if sensor.device_class in _DEVICE_CLASSES:
        score += 1

    return score


def is_energy_source_sensor(sensor: DiscoveredSensor) -> bool:
    """Return true when a sensor looks useful for energy analysis."""
    if sensor.device_class in _DEVICE_CLASSES:
        return True
    if sensor.role is not None:
        return True
    unit = (sensor.unit or "").strip().lower()
    return unit in _ENERGY_SOURCE_UNITS


async def async_discover_sensors(hass: Any) -> list[DiscoveredSensor]:
    """Discover candidate sensor entities from HA registry and current states."""
    return [
        sensor
        for sensor in _build_discovered_sensors(hass)
        if score_circuitsetup_candidate(sensor) >= 3
    ]


async def async_discover_energy_source_entities(hass: Any) -> list[str]:
    """Discover generic energy-like sensor entity IDs for setup selectors."""
    return [
        sensor.entity_id
        for sensor in _build_discovered_sensors(hass)
        if is_energy_source_sensor(sensor)
    ]


def _build_discovered_sensors(hass: Any) -> list[DiscoveredSensor]:
    if hass is None:
        return []

    registry_entries = _get_entity_registry_entries(hass)
    state_entity_ids = _get_state_sensor_entity_ids(hass)
    entity_ids = sorted(set(registry_entries) | set(state_entity_ids))

    sensors = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id) if getattr(hass, "states", None) else None
        entry = registry_entries.get(entity_id)
        sensor = _build_discovered_sensor(entity_id, state, entry)
        sensors.append(sensor)

    return sensors


def _normalize_text(entity_id: str, friendly_name: str | None) -> str:
    text = f"{entity_id} {friendly_name or ''}".lower()
    return re.sub(r"[^a-z0-9]+", " ", text)


def _get_entity_registry_entries(hass: Any) -> dict[str, Any]:
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return {}

    registry = er.async_get(hass)
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    return {
        entry.entity_id: entry
        for entry in values
        if getattr(entry, "entity_id", "").startswith("sensor.")
    }


def _get_state_sensor_entity_ids(hass: Any) -> set[str]:
    states = getattr(hass, "states", None)
    if states is None:
        return set()
    if hasattr(states, "async_entity_ids"):
        return set(states.async_entity_ids("sensor"))
    if hasattr(states, "async_all"):
        return {state.entity_id for state in states.async_all("sensor")}
    return set()


def _build_discovered_sensor(
    entity_id: str,
    state: Any,
    entry: Any,
) -> DiscoveredSensor:
    attributes = getattr(state, "attributes", {}) or {}
    name = (
        attributes.get("friendly_name")
        or getattr(entry, "name", None)
        or getattr(entry, "original_name", None)
        or entity_id
    )
    device_class = attributes.get("device_class") or getattr(
        entry,
        "device_class",
        None,
    )

    return DiscoveredSensor(
        entity_id=entity_id,
        name=name,
        role=infer_sensor_role(entity_id, name),
        device_id=getattr(entry, "device_id", None),
        unit=attributes.get("unit_of_measurement"),
        device_class=device_class,
        integration_domain=(
            getattr(entry, "platform", None) or attributes.get("integration_domain")
        ),
    )
