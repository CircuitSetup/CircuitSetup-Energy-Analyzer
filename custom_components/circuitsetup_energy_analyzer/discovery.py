from __future__ import annotations

import re
from collections.abc import Iterable
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
_UNSUPPORTED_REACTIVE_ENERGY_DEVICE_CLASSES = {"reactive_energy"}
_UNSUPPORTED_REACTIVE_ENERGY_UNITS = {"varh", "kvarh", "mvarh"}
_DEVICE_CLASS_ROLES = {
    "apparent_power": SensorRole.APPARENT_POWER,
    "current": SensorRole.CURRENT,
    "energy": SensorRole.ENERGY,
    "frequency": SensorRole.FREQUENCY,
    "power": SensorRole.REAL_POWER,
    "power_factor": SensorRole.POWER_FACTOR,
    "reactive_power": SensorRole.REACTIVE_POWER,
    "voltage": SensorRole.VOLTAGE,
}
_UNIT_ROLES = {
    "a": SensorRole.CURRENT,
    "ka": SensorRole.CURRENT,
    "ma": SensorRole.CURRENT,
    "hz": SensorRole.FREQUENCY,
    "va": SensorRole.APPARENT_POWER,
    "kva": SensorRole.APPARENT_POWER,
    "mva": SensorRole.APPARENT_POWER,
    "var": SensorRole.REACTIVE_POWER,
    "kvar": SensorRole.REACTIVE_POWER,
    "mvar": SensorRole.REACTIVE_POWER,
    "v": SensorRole.VOLTAGE,
    "kv": SensorRole.VOLTAGE,
    "mv": SensorRole.VOLTAGE,
    "w": SensorRole.REAL_POWER,
    "kw": SensorRole.REAL_POWER,
    "mw": SensorRole.REAL_POWER,
    "wh": SensorRole.ENERGY,
    "kwh": SensorRole.ENERGY,
    "mwh": SensorRole.ENERGY,
}
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
_UTILITY_TEXT_KEYWORDS = (
    "opower",
    "utility",
    "electric usage",
    "electric consumption",
    "monthly electric",
    "current bill",
    "billing",
    "bill usage",
    "bill energy",
    "elec",
)
_UTILITY_STATISTIC_KEYWORDS = (
    "opower",
    "utility",
    "electric",
    "elec",
    "bill",
)
_NON_ENERGY_BILLING_KEYWORDS = (
    "cost",
    "price",
    "rate",
    "charge",
    "currency",
    "dollar",
    "usd",
)


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


def infer_sensor_role(
    entity_id: str,
    friendly_name: str | None,
    *,
    device_class: str | None = None,
    unit: str | None = None,
) -> SensorRole | None:
    """Infer the analysis role from common energy meter sensor names."""
    text = _normalize_text(entity_id, friendly_name)
    normalized_device_class = str(device_class or "").strip().lower()
    normalized_unit = str(unit or "").strip().lower()

    if (
        normalized_device_class in _UNSUPPORTED_REACTIVE_ENERGY_DEVICE_CLASSES
        or normalized_unit in _UNSUPPORTED_REACTIVE_ENERGY_UNITS
    ):
        return None
    if role := _DEVICE_CLASS_ROLES.get(normalized_device_class):
        return role
    if role := _UNIT_ROLES.get(normalized_unit):
        return role
    if "reactive power" in text:
        return SensorRole.REACTIVE_POWER
    if "apparent power" in text:
        return SensorRole.APPARENT_POWER
    if "power factor" in text:
        return SensorRole.POWER_FACTOR
    if re.search(r"\b(?:active|real)\s+power\b|\bwatts?\b", text):
        return SensorRole.REAL_POWER
    if re.search(r"\bpeak\s+(?:current|amps?|a)\b", text):
        return SensorRole.PEAK_CURRENT
    if "reactive energy" in text or re.search(r"\b(?:kvarh|varh)\b", text):
        return None
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


def friendly_source_name(value: str) -> str:
    """Return the channel/metric name after an ESPHome MAC suffix."""
    object_id = str(value).split(".")[-1]
    matches = tuple(re.finditer(r"(?:^|_)[0-9a-f]{6}(?:_|$)", object_id.lower()))
    if matches:
        object_id = object_id[matches[-1].end() :]
    words = object_id.replace("_", " ").split()
    return " ".join("AC" if word.lower() == "ac" else word.title() for word in words)


def is_energy_source_sensor(sensor: DiscoveredSensor) -> bool:
    """Return true when a sensor looks useful for energy analysis."""
    if sensor.device_class in _DEVICE_CLASSES:
        return True
    if sensor.role is not None:
        return True
    unit = (sensor.unit or "").strip().lower()
    return unit in _ENERGY_SOURCE_UNITS


def _sensor_role_known_unsupported(sensor: DiscoveredSensor) -> bool:
    device_class = str(sensor.device_class or "").strip().lower()
    unit = str(sensor.unit or "").strip().lower()
    return (
        device_class in _UNSUPPORTED_REACTIVE_ENERGY_DEVICE_CLASSES
        or unit in _UNSUPPORTED_REACTIVE_ENERGY_UNITS
    )


def discovered_sensor_roles(
    hass: Any,
    entity_ids: Iterable[str] | None = None,
) -> dict[str, SensorRole | None]:
    """Return resolved roles for current Home Assistant sensor metadata."""
    if entity_ids is not None:
        selected = {str(entity_id) for entity_id in entity_ids if entity_id}
        registry_entries = _get_entity_registry_entries(hass)
        states = getattr(hass, "states", None)
        state_get = getattr(states, "get", None)
        roles: dict[str, SensorRole | None] = {}
        for entity_id in sorted(selected):
            state = state_get(entity_id) if callable(state_get) else None
            entry = registry_entries.get(entity_id)
            if state is None and entry is None:
                continue
            sensor = _build_discovered_sensor(
                entity_id,
                state,
                entry,
            )
            if sensor.role is not None or _sensor_role_known_unsupported(sensor):
                roles[entity_id] = sensor.role
        return roles
    return {
        sensor.entity_id: sensor.role
        for sensor in _build_discovered_sensors(hass)
        if sensor.role is not None or _sensor_role_known_unsupported(sensor)
    }


async def async_discover_energy_source_entities(hass: Any) -> list[str]:
    """Discover generic energy-like sensor entity IDs for setup selectors."""
    return [
        sensor.entity_id
        for sensor in _build_discovered_sensors(hass)
        if is_energy_source_sensor(sensor)
    ]


async def async_discover_energy_source_entities_for_devices(
    hass: Any,
    device_ids: list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    """Discover energy-like source entities that belong to selected devices."""
    selected_device_ids = {str(device_id) for device_id in device_ids if device_id}
    if not selected_device_ids:
        return []
    return [
        sensor.entity_id
        for sensor in _build_discovered_sensors(hass)
        if sensor.device_id in selected_device_ids and is_energy_source_sensor(sensor)
    ]


async def async_discover_utility_energy_entities(hass: Any) -> list[str]:
    """Discover utility or Opower energy entities suitable for bill comparison."""
    return [
        sensor.entity_id
        for sensor in sorted(
            _build_discovered_sensors(hass),
            key=lambda candidate: (
                _utility_sensor_score(candidate),
                candidate.entity_id,
            ),
            reverse=True,
        )
        if _utility_sensor_score(sensor) > 0
    ]


async def async_discover_utility_statistic_ids(hass: Any) -> list[str]:
    """Discover utility or Opower recorder statistic IDs when metadata is available."""
    statistic_ids = await _async_recorder_statistic_ids(hass)
    return sorted(
        statistic_id
        for statistic_id in statistic_ids
        if _looks_like_utility_statistic_id(statistic_id)
    )


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


def _utility_sensor_score(sensor: DiscoveredSensor) -> int:
    if not _is_energy_quantity_sensor(sensor):
        return 0
    text = _normalize_text(sensor.entity_id, sensor.name)
    if any(keyword in text for keyword in _NON_ENERGY_BILLING_KEYWORDS):
        return 0

    score = sum(1 for keyword in _UTILITY_TEXT_KEYWORDS if keyword in text)
    if "opower" in text:
        score += 4
    if "utility" in text:
        score += 3
    if "bill" in text or "billing" in text:
        score += 2
    return score


def _is_energy_quantity_sensor(sensor: DiscoveredSensor) -> bool:
    unit = (sensor.unit or "").strip().lower()
    return (
        sensor.role is SensorRole.ENERGY
        or sensor.device_class == "energy"
        or unit in {"wh", "kwh", "mwh"}
    )


async def _async_recorder_statistic_ids(hass: Any) -> list[str]:
    if hass is None:
        return []

    fake_statistic_ids = getattr(hass, "recorder_statistic_ids", None)
    if fake_statistic_ids is not None:
        return [str(statistic_id) for statistic_id in fake_statistic_ids]

    try:
        from homeassistant.components.recorder.statistics import (
            async_list_statistic_ids,
        )
    except (ImportError, ModuleNotFoundError):
        return []

    try:
        statistics = await async_list_statistic_ids(hass)
    except Exception:
        return []

    statistic_ids: list[str] = []
    for statistic in statistics or []:
        if isinstance(statistic, str):
            statistic_ids.append(statistic)
        elif isinstance(statistic, dict) and statistic.get("statistic_id"):
            statistic_ids.append(str(statistic["statistic_id"]))
    return statistic_ids


def _looks_like_utility_statistic_id(statistic_id: str) -> bool:
    text = statistic_id.lower()
    return any(keyword in text for keyword in _UTILITY_STATISTIC_KEYWORDS) and not any(
        keyword in text for keyword in _NON_ENERGY_BILLING_KEYWORDS
    )


def _normalize_text(entity_id: str, friendly_name: str | None) -> str:
    text = f"{entity_id} {friendly_name or ''}".lower()
    return re.sub(r"[^a-z0-9]+", " ", text)


def _get_entity_registry_entries(hass: Any) -> dict[str, Any]:
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return {}

    try:
        registry = er.async_get(hass)
    except (AttributeError, TypeError):
        registry = getattr(hass, "entity_registry", None)
    if registry is None:
        return {}
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
        role=infer_sensor_role(
            entity_id,
            name,
            device_class=device_class,
            unit=attributes.get("unit_of_measurement"),
        ),
        device_id=getattr(entry, "device_id", None) or attributes.get("device_id"),
        unit=attributes.get("unit_of_measurement"),
        device_class=device_class,
        integration_domain=(
            getattr(entry, "platform", None) or attributes.get("integration_domain")
        ),
    )
