from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_LINKED_THERMOSTAT_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
)


def string_list_from_sources(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    key: str,
) -> list[str]:
    options = options or {}
    raw = options[key] if key in options else entry_data.get(key, [])
    if isinstance(raw, str):
        return [raw] if raw else []
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def strings_from_any(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def configured_context_entity(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    key: str,
) -> str:
    options = options or {}
    raw = options[key] if key in options else entry_data.get(key, "")
    return str(raw or "").strip()


def configured_context_entities(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    key: str,
) -> tuple[str, ...]:
    return tuple(string_list_from_sources(entry_data, options, key))


def flow_entities_for_settings(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    advanced_settings: Mapping[str, Any],
) -> tuple[str, ...]:
    linked = advanced_settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES, [])
    entities = [entity_id for entity_id in strings_from_any(linked) if entity_id]
    if not entities:
        entities.extend(
            configured_context_entities(
                entry_data,
                options,
                CONF_WATER_FLOW_SENSOR_ENTITIES,
            )
        )
    return tuple(dict.fromkeys(entities))


def thermostat_entities_for_settings(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            configured_context_entities(
                entry_data,
                options,
                CONF_THERMOSTAT_ENTITIES,
            )
        )
    )


def thermostat_mappings_for_settings(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
    advanced_settings: Mapping[str, Any],
) -> dict[str, str | None]:
    linked = tuple(
        dict.fromkeys(
            strings_from_any(advanced_settings.get(CONF_LINKED_THERMOSTAT_ENTITIES))
        )
    )
    if not linked:
        configured = thermostat_entities_for_settings(entry_data, options)
        linked = configured if len(configured) == 1 else ()

    raw_map = advanced_settings.get(CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP, {})
    temperature_map = raw_map if isinstance(raw_map, Mapping) else {}
    return {
        entity_id: str(temperature_map.get(entity_id) or "").strip() or None
        for entity_id in linked
    }


def has_rain_context_source_configured(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
) -> bool:
    return bool(
        configured_context_entity(entry_data, options, CONF_RAIN_SENSOR_ENTITY)
        or configured_context_entity(entry_data, options, CONF_RAIN_INTENSITY_ENTITY)
    )


def has_mains_source_configured(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any] | None,
) -> bool:
    return bool(
        string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
