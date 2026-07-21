from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
)
from custom_components.circuitsetup_energy_analyzer.context_sources import (
    flow_entities_for_settings,
    has_mains_source_configured,
    has_rain_context_source_configured,
    string_list_from_sources,
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
