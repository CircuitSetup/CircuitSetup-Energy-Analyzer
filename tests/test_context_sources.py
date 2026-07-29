from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_LINKED_THERMOSTAT_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
)
from custom_components.circuitsetup_energy_analyzer.context_sources import (
    flow_entities_for_settings,
    has_mains_source_configured,
    has_rain_context_source_configured,
    string_list_from_sources,
    thermostat_entities_for_settings,
    thermostat_mappings_for_settings,
)


def test_string_list_from_sources_prefers_options() -> None:
    assert string_list_from_sources(
        {CONF_MAINS_SOURCE_ENTITIES: ["sensor.entry_mains"]},
        {CONF_MAINS_SOURCE_ENTITIES: ["sensor.option_mains"]},
        CONF_MAINS_SOURCE_ENTITIES,
    ) == ["sensor.option_mains"]


def test_context_source_presence_helpers() -> None:
    assert has_mains_source_configured(
        {CONF_MAINS_SOURCE_ENTITIES: ["sensor.mains_power"]},
        {},
    )
    assert has_rain_context_source_configured(
        {},
        {CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain"},
    )
    assert not has_rain_context_source_configured(
        {CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain"},
        {CONF_RAIN_SENSOR_ENTITY: ""},
    )


def test_flow_entities_prefer_linked_settings_then_global_sources() -> None:
    entry_data = {CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.global_flow"]}

    assert flow_entities_for_settings(
        entry_data,
        {},
        {CONF_LINKED_FLOW_SENSOR_ENTITIES: ["binary_sensor.linked_flow"]},
    ) == ("binary_sensor.linked_flow",)

    assert flow_entities_for_settings(entry_data, {}, {}) == (
        "binary_sensor.global_flow",
    )


def test_thermostat_entities_prefer_options_and_remove_duplicates() -> None:
    assert thermostat_entities_for_settings(
        {CONF_THERMOSTAT_ENTITIES: ["climate.entry"]},
        {
            CONF_THERMOSTAT_ENTITIES: [
                "climate.downstairs",
                "climate.downstairs",
                "climate.upstairs",
            ]
        },
    ) == ("climate.downstairs", "climate.upstairs")


def test_thermostat_mappings_use_links_and_per_thermostat_temperature() -> None:
    entry_data = {
        CONF_THERMOSTAT_ENTITIES: ["climate.downstairs", "climate.upstairs"]
    }

    assert thermostat_mappings_for_settings(
        entry_data,
        {},
        {
            CONF_LINKED_THERMOSTAT_ENTITIES: ["climate.downstairs"],
            CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP: {
                "climate.downstairs": "sensor.downstairs_temperature",
                "climate.unlinked": "sensor.unlinked_temperature",
            },
        },
    ) == {"climate.downstairs": "sensor.downstairs_temperature"}


def test_thermostat_mappings_default_only_when_one_thermostat_is_configured() -> None:
    assert thermostat_mappings_for_settings(
        {CONF_THERMOSTAT_ENTITIES: ["climate.only"]},
        {},
        {},
    ) == {"climate.only": None}

    assert (
        thermostat_mappings_for_settings(
            {
                CONF_THERMOSTAT_ENTITIES: [
                    "climate.downstairs",
                    "climate.upstairs",
                ]
            },
            {},
            {},
        )
        == {}
    )
