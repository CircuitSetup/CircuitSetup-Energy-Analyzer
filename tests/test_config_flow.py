from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_CIRCUITS,
    CONF_DASHBOARD_LAYOUT,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_RETENTION_MODE,
    CONF_SELECTED_ENTITY_GROUPS,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.discovery import DiscoveredSensor
from custom_components.circuitsetup_energy_analyzer.mapping import DualPhaseSuggestion
from custom_components.circuitsetup_energy_analyzer.models import SensorRole

CONF_DEMO_SOURCE_BUNDLE_ENABLED = "demo_source_bundle_enabled"


def _assert_create_entry_result(
    result: dict[str, object],
    expected_data: dict[str, object],
) -> None:
    assert result["type"] == "create_entry"
    assert result["title"] == ""
    assert result["data"] == expected_data


def _assert_no_description_placeholders(result: dict[str, object]) -> None:
    assert result.get("description_placeholders") in (None, {})


def test_format_mapping_suggestions_shows_confirmation_text() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        format_mapping_suggestions,
    )

    left = DiscoveredSensor(
        "sensor.panel_ch1_power",
        "HVAC L1 Power",
        SensorRole.REAL_POWER,
        "meter-1",
        "W",
        "power",
        "esphome",
    )
    right = DiscoveredSensor(
        "sensor.panel_ch2_power",
        "HVAC L2 Power",
        SensorRole.REAL_POWER,
        "meter-1",
        "W",
        "power",
        "esphome",
    )

    text = format_mapping_suggestions(
        [DualPhaseSuggestion(left, right, 0.8, ("neighboring channels",))]
    )

    assert "HVAC L1 Power" in text
    assert "sensor.panel_ch1_power" in text
    assert "HVAC L2 Power" in text
    assert "sensor.panel_ch2_power" in text
    assert "80%" in text
    assert "neighboring channels" in text
    assert "confirm or manually override" in text
    assert "accept, edit, mark as mixed, or exclude" in text
    assert "required metric availability" in text
    assert "optional metric availability" in text


def test_format_mapping_suggestions_requires_manual_definition_when_empty() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        format_mapping_suggestions,
    )

    text = format_mapping_suggestions([])

    assert "Continue with source sensors" in text
    assert "manual definition" not in text


def _schema_keys(schema) -> set[str]:
    keys = set()
    for marker, validator in schema.schema.items():
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        keys.add(key)
        section_schema = _section_schema(validator)
        if section_schema is not None:
            keys.update(_schema_keys(section_schema))
    return keys


def _schema_default(schema, field_name: str):
    for marker, validator in schema.schema.items():
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        if key == field_name:
            default = getattr(marker, "default", None)
            return default() if callable(default) else default
        section_schema = _section_schema(validator)
        if section_schema is not None:
            try:
                return _schema_default(section_schema, field_name)
            except AssertionError:
                pass
    raise AssertionError(f"{field_name} missing from schema")


def _schema_validator(schema, field_name: str):
    for marker, validator in schema.schema.items():
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        if key == field_name:
            return validator
        section_schema = _section_schema(validator)
        if section_schema is not None:
            try:
                return _schema_validator(section_schema, field_name)
            except AssertionError:
                pass
    raise AssertionError(f"{field_name} missing from schema")


def _section_schema(validator):
    if hasattr(validator, "schema") and isinstance(validator.schema, dict):
        return validator
    nested = getattr(validator, "schema", None)
    return nested if hasattr(nested, "schema") else None


def _schema_section_keys(schema) -> set[str]:
    keys = set()
    for marker, validator in schema.schema.items():
        if _section_schema(validator) is not None:
            keys.add(getattr(marker, "schema", getattr(marker, "key", marker)))
    return keys


def _schema_top_level_keys(schema) -> list[str]:
    return [
        getattr(marker, "schema", getattr(marker, "key", marker))
        for marker in schema.schema
    ]


def test_validate_setup_input_preserves_setup_fields_without_manual_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    payload = {
        CONF_SOURCE_DEVICES: ["meter-device"],
        CONF_EXTRA_SOURCE_ENTITIES: ["sensor.fridge_power", "sensor.main_l1_power"],
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power", "sensor.main_l2_power"],
        CONF_SENSITIVITY: "sensitive",
        CONF_RETENTION_MODE: "diagnostic",
        "circuits": [{"circuit_id": "fridge"}],
        "known_load_circuits": ["fridge"],
    }

    validated = validate_setup_input(payload)

    assert validated[CONF_SOURCE_DEVICES] == payload[CONF_SOURCE_DEVICES]
    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == ["sensor.fridge_power"]
    assert validated[CONF_SOURCE_ENTITIES] == ["sensor.fridge_power"]
    assert validated[CONF_ENABLE_EXPERIMENTAL_NILM] is True
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == payload[CONF_MAINS_SOURCE_ENTITIES]
    assert validated[CONF_SENSITIVITY] == "sensitive"
    assert validated[CONF_RETENTION_MODE] == "diagnostic"
    assert "circuits" not in validated
    assert "known_load_circuits" not in validated




def test_validate_setup_input_parses_text_entity_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    validated = validate_setup_input(
        {
            CONF_SOURCE_DEVICES: "meter-1, meter-2",
            CONF_EXTRA_SOURCE_ENTITIES: "sensor.fridge_power\nsensor.hvac_power",
            CONF_MAINS_SOURCE_ENTITIES: "sensor.main_l1_power, sensor.main_l2_power",
        }
    )

    assert validated[CONF_SOURCE_DEVICES] == ["meter-1", "meter-2"]
    assert validated[CONF_SOURCE_ENTITIES] == [
        "sensor.fridge_power",
        "sensor.hvac_power",
    ]
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


@pytest.mark.asyncio
async def test_source_selection_expands_source_device_only_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    async def fake_discover_for_devices(hass, source_devices):
        assert hass == "hass"
        assert source_devices == ("meter-device",)
        return ["sensor.device_l1_power", "sensor.device_l2_power"]

    monkeypatch.setattr(
        config_flow,
        "async_discover_energy_source_entities_for_devices",
        fake_discover_for_devices,
    )

    selected = await config_flow._async_source_selection_with_device_entities(
        "hass",
        {CONF_SOURCE_DEVICES: ["meter-device"]},
    )

    assert selected[CONF_SOURCE_DEVICES] == ["meter-device"]
    assert selected[CONF_EXTRA_SOURCE_ENTITIES] == []
    assert selected[CONF_SOURCE_ENTITIES] == [
        "sensor.device_l1_power",
        "sensor.device_l2_power",
    ]


@pytest.mark.asyncio
async def test_source_selection_merges_source_devices_and_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    async def fake_discover_for_devices(_hass, source_devices):
        assert source_devices == ("meter-device",)
        return ["sensor.device_l1_power", "sensor.device_l2_power"]

    monkeypatch.setattr(
        config_flow,
        "async_discover_energy_source_entities_for_devices",
        fake_discover_for_devices,
    )

    selected = await config_flow._async_source_selection_with_device_entities(
        object(),
        {
            CONF_SOURCE_DEVICES: "meter-device",
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.extra_power",
                "sensor.device_l1_power",
            ],
        },
    )

    assert selected[CONF_SOURCE_DEVICES] == ["meter-device"]
    assert selected[CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.extra_power",
        "sensor.device_l1_power",
    ]
    assert selected[CONF_SOURCE_ENTITIES] == [
        "sensor.device_l1_power",
        "sensor.device_l2_power",
        "sensor.extra_power",
    ]


@pytest.mark.parametrize(
    "validator_name",
    ["validate_setup_input", "validate_options_input"],
)
def test_validate_input_preserves_device_expanded_sources(
    validator_name: str,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    validated = getattr(config_flow, validator_name)(
        {
            CONF_SOURCE_DEVICES: ["meter-device"],
            CONF_SOURCE_ENTITIES: [
                "sensor.device_l1_power",
                "sensor.device_l2_power",
            ],
        }
    )

    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == []
    assert validated[CONF_SOURCE_ENTITIES] == [
        "sensor.device_l1_power",
        "sensor.device_l2_power",
    ]


@pytest.mark.asyncio
async def test_user_flow_auto_routes_mains_sources_to_mains_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
                "sensor.refrigerator_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert flow._pending_config[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]
    assert flow._pending_config[CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power"
    ]
    assert flow._pending_config[CONF_SOURCE_ENTITIES] == ["sensor.refrigerator_power"]
    assert _schema_default(result["data_schema"], "circuit_name") == "Refrigerator"
    assert _schema_default(result["data_schema"], "included_sensors") == [
        "sensor.refrigerator_power"
    ]


@pytest.mark.asyncio
async def test_user_flow_mains_only_sources_skip_assignment_review() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "utility"
    assert flow._pending_final_config[CONF_EXTRA_SOURCE_ENTITIES] == []
    assert flow._pending_final_config[CONF_SOURCE_ENTITIES] == []
    assert flow._pending_final_config[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]
    assert flow._pending_final_config[CONF_CIRCUITS] == []
    assert flow._pending_final_config[CONF_CIRCUIT_ASSIGNMENTS] == ""


def test_validate_setup_input_adds_demo_source_bundle_when_enabled() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        assignment_groups_from_sources,
        validate_setup_input,
    )
    from custom_components.circuitsetup_energy_analyzer.demo import (
        DEMO_SOURCE_ENTITY_IDS,
    )

    validated = validate_setup_input({CONF_DEMO_SOURCE_BUNDLE_ENABLED: True})
    demo_mains_source_entity_ids = {
        entity_id
        for entity_id in DEMO_SOURCE_ENTITY_IDS
        if "_demo_mains_" in entity_id
    }
    demo_assignable_source_entity_ids = (
        set(DEMO_SOURCE_ENTITY_IDS) - demo_mains_source_entity_ids
    )

    assert validated[CONF_DEMO_SOURCE_BUNDLE_ENABLED] is True
    assert demo_assignable_source_entity_ids <= set(
        validated[CONF_EXTRA_SOURCE_ENTITIES]
    )
    assert demo_assignable_source_entity_ids <= set(validated[CONF_SOURCE_ENTITIES])
    assert demo_mains_source_entity_ids <= set(
        validated[CONF_MAINS_SOURCE_ENTITIES]
    )

    groups = assignment_groups_from_sources(validated[CONF_SOURCE_ENTITIES])
    car_charger = next(
        group
        for group in groups
        if group["group_id"] == "cs_energy_analyzer_demo_car_charger"
    )

    assert car_charger["name"] == "Car Charger"
    assert car_charger["appliance_profile"] == "ev_charger"
    assert car_charger["mode"] == "dual_phase"
    assert "sensor.cs_energy_analyzer_demo_car_charger_l1_active_power" in (
        car_charger["entity_ids"]
    )
    assert "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power" in (
        car_charger["entity_ids"]
    )
    sump_pump = next(
        group
        for group in groups
        if group["group_id"] == "cs_energy_analyzer_demo_sump_pump"
    )

    assert sump_pump["name"] == "Sump Pump"
    assert sump_pump["appliance_profile"] == "sump_pump"
    assert sump_pump["mode"] == "single_phase"
    assert "sensor.cs_energy_analyzer_demo_sump_pump_active_power" in (
        sump_pump["entity_ids"]
    )


def test_validate_setup_input_preserves_outdoor_temperature_entity() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    validated = validate_setup_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: " sensor.outdoor_temperature ",
        }
    )

    assert (
        validated[CONF_OUTDOOR_TEMPERATURE_ENTITY]
        == "sensor.outdoor_temperature"
    )


def test_validate_setup_input_preserves_water_context_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    validated = validate_setup_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.sump_pump_watts"],
            CONF_RAIN_SENSOR_ENTITY: " binary_sensor.rain ",
            CONF_RAIN_INTENSITY_ENTITY: " sensor.precipitation_rate ",
            CONF_WATER_FLOW_SENSOR_ENTITIES: [
                " binary_sensor.water_flow ",
                "binary_sensor.hot_water_flow",
            ],
        }
    )

    assert validated[CONF_RAIN_SENSOR_ENTITY] == "binary_sensor.rain"
    assert validated[CONF_RAIN_INTENSITY_ENTITY] == "sensor.precipitation_rate"
    assert validated[CONF_WATER_FLOW_SENSOR_ENTITIES] == [
        "binary_sensor.water_flow",
        "binary_sensor.hot_water_flow",
    ]


def test_validate_options_input_parses_source_entity_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_options_input,
    )

    validated = validate_options_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: "sensor.fridge_power\nsensor.fridge_current",
            CONF_MAINS_SOURCE_ENTITIES: "sensor.main_l1_power, sensor.main_l2_power",
        }
    )

    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.fridge_power",
        "sensor.fridge_current",
    ]
    assert validated[CONF_SOURCE_ENTITIES] == [
        "sensor.fridge_power",
        "sensor.fridge_current",
    ]
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


def test_validate_options_input_moves_mains_sources_out_of_assignable_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_options_input,
    )

    validated = validate_options_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.main_l1_power",
                "sensor.main_l2_power",
            ],
        }
    )

    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == ["sensor.fridge_power"]
    assert validated[CONF_SOURCE_ENTITIES] == ["sensor.fridge_power"]
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


@pytest.mark.parametrize(
    "mains_entities",
    [
        [
            "sensor.panel_mains_l1_active_power",
            "sensor.panel_mains_l2_active_power",
        ],
        [
            "sensor.whole_home_l1_power",
            "sensor.whole_home_l2_power",
        ],
        [
            "sensor.utility_l1_energy",
            "sensor.utility_l2_energy",
        ],
        [
            "sensor.circuitsetup_energy_analyzer_mains_l1_current",
            "sensor.circuitsetup_energy_analyzer_mains_l2_current",
        ],
    ],
)
def test_validate_options_input_moves_real_mains_patterns_from_sources(
    mains_entities: list[str],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_options_input,
    )

    validated = validate_options_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                *mains_entities,
                "sensor.kitchen_refrigerator_active_power",
                "sensor.main_bedroom_light_power",
            ],
        }
    )

    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.kitchen_refrigerator_active_power",
        "sensor.main_bedroom_light_power",
    ]
    assert validated[CONF_SOURCE_ENTITIES] == [
        "sensor.kitchen_refrigerator_active_power",
        "sensor.main_bedroom_light_power",
    ]
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == mains_entities


def test_validate_options_input_preserves_outdoor_temperature_entity() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_options_input,
    )

    validated = validate_options_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.weather_station_temperature",
        }
    )

    assert (
        validated[CONF_OUTDOOR_TEMPERATURE_ENTITY]
        == "sensor.weather_station_temperature"
    )


def test_validate_options_input_preserves_blank_optional_context_overrides() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_options_input,
    )

    validated = validate_options_input(
        {
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: " ",
            CONF_RAIN_SENSOR_ENTITY: "",
            CONF_RAIN_INTENSITY_ENTITY: None,
        }
    )

    assert validated[CONF_OUTDOOR_TEMPERATURE_ENTITY] == ""
    assert validated[CONF_RAIN_SENSOR_ENTITY] == ""
    assert validated[CONF_RAIN_INTENSITY_ENTITY] == ""


def test_validate_setup_input_requires_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input({CONF_SOURCE_DEVICES: [], CONF_EXTRA_SOURCE_ENTITIES: []})

    assert error.value.error_key == "no_source_entities"


def test_validate_setup_input_rejects_source_entity_mapping() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input(
            {
                CONF_EXTRA_SOURCE_ENTITIES: {"sensor.fridge_power": True},
            }
        )

    assert error.value.error_key == "invalid_source_entities"


@pytest.mark.asyncio
async def test_fallback_user_flow_returns_no_source_entities_form_error() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()
    result = await flow.async_step_user(
        {CONF_SOURCE_DEVICES: [], CONF_EXTRA_SOURCE_ENTITIES: []}
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "no_source_entities"


@pytest.mark.asyncio
async def test_options_flow_init_offers_assignment_and_source_editing() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(
        SimpleNamespace(
            data={},
            options={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
        )
    )

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    assert result["step_id"] == "init"
    assert result["menu_options"] == [
        "sources",
        "mains",
        "assign",
        "utility",
        "dashboard",
        "entity_detail",
        "recommendations",
        "advanced",
    ]
    _assert_no_description_placeholders(result)


@pytest.mark.asyncio
async def test_options_recommendations_step_shows_friendly_pending_suggestions(
    monkeypatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "hvac": [
                    {
                        "recommendation_id": "hvac:daily_spike_ratio:v1",
                        "circuit_id": "hvac",
                        "circuit_name": "Downstairs HVAC",
                        "setting_key": "daily_spike_ratio",
                        "setting_label": "Daily Spike Ratio",
                        "current_value": 0.5,
                        "suggested_value": 0.3,
                        "confidence": 0.82,
                        "reason": "Recent daily usage has been stable.",
                        "evidence": {
                            "observed_daily_spike_ratio": 0.28,
                            "source_entities": ["sensor.hvac_power"],
                        },
                    }
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations()

    assert result["type"] == "form"
    assert result["step_id"] == "recommendations"
    assert {
        "setting_suggestion_ids",
        "recommendation_action",
    } <= _schema_keys(result["data_schema"])
    recommendation_options = _schema_validator(
        result["data_schema"],
        "setting_suggestion_ids",
    )["select"]["options"]
    assert recommendation_options == [
        {
            "value": "hvac:daily_spike_ratio:v1",
            "label": (
                "Downstairs HVAC - Daily Spike Ratio: "
                "0.5 -> 0.3 (82% confidence)"
            ),
        }
    ]
    assert _schema_validator(result["data_schema"], "setting_suggestion_ids")[
        "select"
    ]["multiple"]
    assert _schema_validator(result["data_schema"], "setting_suggestion_ids")[
        "select"
    ]["mode"] == "list"
    action_options = _schema_validator(
        result["data_schema"],
        "recommendation_action",
    )["select"]["options"]
    assert action_options == [
        {"value": "apply", "label": "Apply Suggestion"},
        {"value": "dismiss", "label": "Dismiss For Now"},
    ]
    summary = result["description_placeholders"]["recommendations"]
    assert summary.startswith("Settings Suggestions:")
    assert "Downstairs HVAC" in summary
    assert "Daily Spike Ratio" in summary
    assert "0.5 -> 0.3" in summary
    assert "Current value: 0.5" in summary
    assert "Default value: 0.25" in summary
    assert "Suggested value: 0.3" in summary
    assert (
        "Expected effect: Tune this setting toward the observed history without "
        "requiring manual threshold math."
    ) in summary
    assert "Recent daily usage has been stable." in summary
    assert "Observed Daily Spike Ratio: 0.28" in summary
    assert "source_entities" not in summary
    assert coordinator.async_recalculate_setting_recommendations.calls == [(None,)]


@pytest.mark.asyncio
async def test_options_recommendations_step_guides_capacity_suggestions() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "ev_charger": [
                    {
                        "recommendation_id": "ev_charger:warning_ratio:v1",
                        "circuit_id": "ev_charger",
                        "circuit_name": "EV Charger",
                        "setting_key": "warning_ratio",
                        "setting_label": "Capacity Warning Ratio",
                        "current_value": 0.9,
                        "suggested_value": 0.75,
                        "confidence": 0.76,
                        "reason": "Observed sustained high-current samples.",
                        "evidence": {
                            "observed_samples": 8,
                            "p95_current_amps": 36.4,
                        },
                    }
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations()

    summary = result["description_placeholders"]["recommendations"]
    assert "EV Charger - Capacity Warning Ratio: 0.9 -> 0.75" in summary
    assert "Default value: 0.8" in summary
    assert "Expected effect: Warn earlier when usage approaches capacity" in summary
    assert "Observed Samples: 8" in summary
    assert "P95 Current Amps: 36.4" in summary


@pytest.mark.asyncio
async def test_recommendations_step_guides_standby_advanced_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "washer": [
                    {
                        "recommendation_id": "washer:window_hours:v1",
                        "circuit_id": "washer",
                        "circuit_name": "Washer",
                        "setting_key": "window_hours",
                        "setting_label": "Window Hours",
                        "current_value": 48,
                        "suggested_value": 72,
                        "unit": "h",
                        "confidence": 0.72,
                        "reason": (
                            "Observed enough standby history to extend the window."
                        ),
                        "evidence": {"observed_standby_samples": 96},
                    },
                    {
                        "recommendation_id": "washer:always_on_alert_w:v1",
                        "circuit_id": "washer",
                        "circuit_name": "Washer",
                        "setting_key": "always_on_alert_w",
                        "setting_label": "Always On Alert W",
                        "current_value": 0.0,
                        "suggested_value": 35.0,
                        "unit": "W",
                        "confidence": 0.69,
                        "reason": "Observed elevated always-on draw.",
                        "evidence": {"p95_always_on_w": 42.5},
                    },
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations()

    summary = result["description_placeholders"]["recommendations"]
    assert "Washer - Window Hours: 48 h -> 72 h" in summary
    assert "Default value: 48" in summary
    assert "Expected effect: Use enough standby history" in summary
    assert "Observed Standby Samples: 96" in summary
    assert "Washer - Always On Alert W: 0 W -> 35 W" in summary
    assert "Expected effect: Surface unusually high Always On draw" in summary
    assert "P95 Always On W: 42.5" in summary


@pytest.mark.asyncio
async def test_options_recommendations_step_guides_solar_flow_suggestions() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "mains": [
                    {
                        "recommendation_id": (
                            "mains:high_solar_surplus_threshold_w:v1"
                        ),
                        "circuit_id": "mains",
                        "circuit_name": "Mains",
                        "setting_key": "high_solar_surplus_threshold_w",
                        "setting_label": "High Solar Surplus Threshold W",
                        "current_value": 1500.0,
                        "suggested_value": 2600.0,
                        "unit": "W",
                        "confidence": 0.74,
                        "reason": (
                            "High solar surplus should represent the upper end of "
                            "observed export events."
                        ),
                        "evidence": {
                            "observed_export_samples": 7,
                            "p95_export_w": 2600.0,
                            "source_entities": ["sensor.mains_power"],
                        },
                    }
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations()

    summary = result["description_placeholders"]["recommendations"]
    assert "Mains - High Solar Surplus Threshold W: 1500 W -> 2600 W" in summary
    assert "Default value: 1500" in summary
    assert "Expected effect: Reserve high solar surplus guidance" in summary
    assert "Observed Export Samples: 7" in summary
    assert "P95 Export W: 2600" in summary
    assert "source_entities" not in summary


@pytest.mark.asyncio
async def test_recommendations_step_guides_solar_flow_advanced_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "mains": [
                    {
                        "recommendation_id": "mains:solar_export_tolerance_w:v1",
                        "circuit_id": "mains",
                        "circuit_name": "Mains",
                        "setting_key": "solar_export_tolerance_w",
                        "setting_label": "Solar Export Tolerance W",
                        "current_value": 100.0,
                        "suggested_value": 250.0,
                        "unit": "W",
                        "confidence": 0.68,
                        "reason": (
                            "Observed inverter and mains readings differ at export."
                        ),
                        "evidence": {"p95_export_residual_w": 220.0},
                    },
                    {
                        "recommendation_id": (
                            "mains:flexible_load_running_threshold_w:v1"
                        ),
                        "circuit_id": "mains",
                        "circuit_name": "Mains",
                        "setting_key": "flexible_load_running_threshold_w",
                        "setting_label": "Flexible Load Running Threshold W",
                        "current_value": 100.0,
                        "suggested_value": 175.0,
                        "unit": "W",
                        "confidence": 0.7,
                        "reason": "Observed low idle draw on flexible loads.",
                        "evidence": {"observed_flexible_loads": 3},
                    },
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations()

    summary = result["description_placeholders"]["recommendations"]
    assert "Mains - Solar Export Tolerance W: 100 W -> 250 W" in summary
    assert "Default value: 100" in summary
    assert "Expected effect: Keep normal CT and inverter timing drift" in summary
    assert "P95 Export Residual W: 220" in summary
    assert "Mains - Flexible Load Running Threshold W: 100 W -> 175 W" in summary
    assert "Expected effect: Classify flexible loads as running only after" in summary
    assert "Observed Flexible Loads: 3" in summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "method_name"),
    [
        ("apply", "async_apply_setting_recommendation"),
        ("deny", "async_deny_setting_recommendation"),
        ("dismiss", "async_dismiss_setting_recommendation"),
    ],
)
async def test_options_recommendations_step_dispatches_batch_actions(
    action: str,
    method_name: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    recommendation = {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "circuit_id": "hvac",
        "circuit_name": "Downstairs HVAC",
        "setting_label": "Daily Spike Ratio",
        "current_value": 0.5,
        "suggested_value": 0.3,
    }
    second_recommendation = {
        "recommendation_id": "hvac:warning_ratio:v1",
        "circuit_id": "hvac",
        "circuit_name": "Downstairs HVAC",
        "setting_label": "Warning Ratio",
        "current_value": 0.9,
        "suggested_value": 0.75,
    }
    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "hvac": [recommendation, second_recommendation]
            }
        ),
        options={
            CONF_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_ADVANCED_SETTINGS: {"hvac": {"daily_spike_ratio": 0.3}},
        },
        async_recalculate_setting_recommendations=_async_recorder(),
        async_apply_setting_recommendation=_async_recorder(),
        async_deny_setting_recommendation=_async_recorder(),
        async_dismiss_setting_recommendation=_async_recorder(),
    )
    entry = SimpleNamespace(
        data={},
        options={CONF_SOURCE_ENTITIES: ["sensor.old_power"]},
        entry_id="entry-1",
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations(
        {
            "setting_suggestion_ids": [
                "hvac:daily_spike_ratio:v1",
                "hvac:warning_ratio:v1",
            ],
            "recommendation_action": action,
        }
    )

    _assert_create_entry_result(
        result,
        coordinator.options if action == "apply" else entry.options,
    )
    assert getattr(coordinator, method_name).calls == [
        ("hvac:daily_spike_ratio:v1",),
        ("hvac:warning_ratio:v1",),
    ]


@pytest.mark.asyncio
async def test_options_recommendations_step_handles_missing_or_empty_suggestions(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {}})

    missing = await flow.async_step_recommendations()

    assert missing["type"] == "form"
    assert missing["step_id"] == "recommendations"
    assert _schema_keys(missing["data_schema"]) == set()
    assert missing["errors"]["base"] == "recommendations_not_loaded"
    assert "not loaded yet" in missing["description_placeholders"]["recommendations"]

    coordinator = SimpleNamespace(
        state=SimpleNamespace(settings_recommendations_by_circuit={}),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    empty = await flow.async_step_recommendations()

    assert empty["type"] == "form"
    assert empty["step_id"] == "recommendations"
    assert _schema_keys(empty["data_schema"]) == set()
    assert empty["errors"] == {}
    assert "no pending suggestions" in empty["description_placeholders"][
        "recommendations"
    ].lower()


@pytest.mark.asyncio
async def test_options_recommendations_step_rejects_unknown_selection() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN

    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            settings_recommendations_by_circuit={
                "hvac": [
                    {
                        "recommendation_id": "hvac:daily_spike_ratio:v1",
                        "circuit_name": "Downstairs HVAC",
                        "setting_label": "Daily Spike Ratio",
                        "current_value": 0.5,
                        "suggested_value": 0.3,
                    }
                ]
            }
        ),
        async_recalculate_setting_recommendations=_async_recorder(),
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(
        SimpleNamespace(data={}, options={}, entry_id="entry-1")
    )
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_recommendations(
        {"setting_suggestion_ids": ["unknown"], "recommendation_action": "apply"}
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_recommendation"


def _async_recorder():
    async def record(*args):
        record.calls.append(args)

    record.calls = []
    return record


@pytest.mark.asyncio
async def test_options_sources_step_shows_source_selection_form() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(
        SimpleNamespace(
            data={},
            options={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
        )
    )

    result = await flow.async_step_sources()

    assert result["type"] == "form"
    assert result["step_id"] == "sources"
    assert CONF_SOURCE_DEVICES in _schema_keys(result["data_schema"])
    assert CONF_EXTRA_SOURCE_ENTITIES in _schema_keys(result["data_schema"])
    assert CONF_OUTDOOR_TEMPERATURE_ENTITY in _schema_keys(result["data_schema"])


def test_demo_source_bundle_toggle_defaults_off_for_new_setup() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    entry = SimpleNamespace(data={}, options={})

    assert CONF_DEMO_SOURCE_BUNDLE_ENABLED in _schema_keys(config_flow.DATA_SCHEMA)
    assert (
        _schema_default(config_flow.DATA_SCHEMA, CONF_DEMO_SOURCE_BUNDLE_ENABLED)
        is False
    )
    assert (
        _schema_default(
            config_flow._options_schema(entry),
            CONF_DEMO_SOURCE_BUNDLE_ENABLED,
        )
        is False
    )


def test_options_schema_checks_demo_source_bundle_when_demo_sources_exist() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    entry = SimpleNamespace(
        data={},
        options={
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
        },
    )

    assert (
        _schema_default(
            config_flow._options_schema(entry),
            CONF_DEMO_SOURCE_BUNDLE_ENABLED,
        )
        is True
    )


def test_setup_schema_exposes_outdoor_temperature_entity() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    assert CONF_OUTDOOR_TEMPERATURE_ENTITY in _schema_keys(config_flow.DATA_SCHEMA)


def test_setup_schema_exposes_water_context_sources() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    keys = _schema_keys(config_flow.DATA_SCHEMA)

    assert CONF_RAIN_SENSOR_ENTITY in keys
    assert CONF_RAIN_INTENSITY_ENTITY in keys
    assert CONF_WATER_FLOW_SENSOR_ENTITIES in keys


def test_water_flow_selector_allows_binary_and_numeric_sensor_entities() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    config = config_flow._water_flow_entity_selector_config(multiple=True)

    assert config == {
        "entity": {
            "multiple": True,
            "filter": [
                {"domain": "binary_sensor"},
                {"domain": "sensor"},
            ],
        }
    }


def test_optional_context_entity_selectors_do_not_default_to_blank_entity_ids() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    entry = SimpleNamespace(data={}, options={})
    options_schema = config_flow._options_schema(entry)

    for schema in (config_flow.DATA_SCHEMA, options_schema):
        assert _schema_default(schema, CONF_OUTDOOR_TEMPERATURE_ENTITY) is vol.UNDEFINED
        assert _schema_default(schema, CONF_RAIN_SENSOR_ENTITY) is vol.UNDEFINED
        assert _schema_default(schema, CONF_RAIN_INTENSITY_ENTITY) is vol.UNDEFINED


@pytest.mark.asyncio
async def test_options_mains_step_updates_mains_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_energy"],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.old_mains_energy"],
        },
        options={},
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_mains(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: False,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.new_mains_l1_energy"],
            CONF_KNOWN_LOAD_CIRCUITS: [],
        }
    )

    _assert_create_entry_result(
        result,
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: False,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.new_mains_l1_energy"],
            CONF_KNOWN_LOAD_CIRCUITS: [],
        },
    )


@pytest.mark.asyncio
async def test_options_mains_step_combines_mains_and_nilm_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: False,
            CONF_KNOWN_LOAD_CIRCUITS: ["fridge"],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.old_mains_power"],
            CONF_CIRCUITS: [
                {"circuit_id": "fridge", "name": "Fridge"},
                {"circuit_id": "hvac", "name": "HVAC"},
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    menu = await flow.async_step_init()

    assert menu["type"] == "menu"
    assert "mains" in menu["menu_options"]
    assert "nilm" not in menu["menu_options"]

    form = await flow.async_step_mains()

    assert form["type"] == "form"
    assert form["step_id"] == "mains"
    assert _schema_keys(form["data_schema"]) == {
        CONF_ENABLE_EXPERIMENTAL_NILM,
        CONF_MAINS_SOURCE_ENTITIES,
        CONF_KNOWN_LOAD_CIRCUITS,
    }
    assert (
        _schema_default(form["data_schema"], CONF_ENABLE_EXPERIMENTAL_NILM) is False
    )
    assert _schema_default(form["data_schema"], CONF_MAINS_SOURCE_ENTITIES) == [
        "sensor.old_mains_power"
    ]
    assert _schema_default(form["data_schema"], CONF_KNOWN_LOAD_CIRCUITS) == [
        "fridge"
    ]

    result = await flow.async_step_mains(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_mains_l1_power"],
            CONF_KNOWN_LOAD_CIRCUITS: ["hvac"],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ENABLE_EXPERIMENTAL_NILM] is True
    assert result["data"][CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.panel_mains_l1_power"
    ]
    assert result["data"][CONF_KNOWN_LOAD_CIRCUITS] == ["hvac"]


@pytest.mark.asyncio
async def test_options_entity_detail_step_saves_profile_without_registry_apply(
    monkeypatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    calls: list[tuple[object, object, str]] = []

    def fake_apply(hass, entry, detail_level):
        calls.append((hass, entry, detail_level))
        return {"total": 3, "will_disable": 1}

    monkeypatch.setattr(
        config_flow,
        "_apply_entity_detail_profile_to_existing_entities",
        fake_apply,
    )
    hass = SimpleNamespace()
    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = hass

    result = await flow.async_step_entity_detail(
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            "apply_entity_detail_profile": True,
        }
    )

    _assert_create_entry_result(
        result,
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: [],
        },
    )
    assert calls == []


@pytest.mark.asyncio
async def test_options_entity_detail_step_saves_expert_entity_groups() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_entity_detail(
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: [
                "cycle_metrics",
                "power_quality_drift",
            ],
        }
    )

    _assert_create_entry_result(
        result,
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: [
                "cycle_metrics",
                "power_quality_drift",
            ],
        },
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
        },
        entry_id="entry-1",
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_entity_detail(
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
            CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
        }
    )

    _assert_create_entry_result(
        result,
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
            CONF_SELECTED_ENTITY_GROUPS: [],
        },
    )


@pytest.mark.asyncio
async def test_options_entity_detail_step_reloads_entity_set_changes() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.updates: list[tuple[object, dict[str, object]]] = []
            self.reloads: list[str] = []

        def async_update_entry(self, entry, **kwargs) -> None:
            self.updates.append((entry, kwargs))
            entry.options = dict(kwargs["options"])

        async def async_reload(self, entry_id: str) -> bool:
            self.reloads.append(entry_id)
            return True

    entry = SimpleNamespace(data={}, options={}, entry_id="entry-1")
    config_entries = FakeConfigEntries()
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(config_entries=config_entries)

    result = await flow.async_step_entity_detail(
        {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
        }
    )

    expected_options = {
        CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
        CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
    }
    _assert_create_entry_result(result, expected_options)
    assert config_entries.updates == [(entry, {"options": expected_options})]
    assert config_entries.reloads == ["entry-1"]
    assert entry.options == expected_options






def test_utility_schema_omits_blank_optional_entity_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import config_flow

    included_entities: list[str] = []

    def capture_energy_entities(entity_ids: Iterable[str]) -> type[str]:
        included_entities.extend(entity_ids)
        return str

    monkeypatch.setattr(
        config_flow,
        "_single_energy_kwh_entity_selector",
        capture_energy_entities,
    )

    schema = config_flow._utility_schema(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [],
                }
            ]
        }
    )

    assert _schema_default(schema, "utility_energy_entity") is vol.UNDEFINED
    assert _schema_default(schema, "utility_cost_entity") is vol.UNDEFINED
    assert included_entities == []


@pytest.mark.asyncio
async def test_options_utility_step_saves_opower_comparison_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(
        SimpleNamespace(
            data={
                CONF_CIRCUITS: [
                    {
                        "circuit_id": "mains",
                        "name": "Mains NILM",
                        "mode": "mains_nilm",
                        "appliance_profile": "mains_nilm",
                        "sensors": [],
                    }
                ],
            },
            options={},
        )
    )

    result = await flow.async_step_utility(
        {
            "enable_utility_comparison": True,
            "circuit_id": "mains",
            "utility_energy_entity": "sensor.opower_current_bill_usage",
            "utility_cost_entity": "sensor.opower_current_bill_cost",
            "utility_statistic_id": "opower:utility_elec_consumption",
            "utility_source_type": "statistics",
            "utility_statistic_period": "day",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 8.5,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_UTILITY_COMPARISON_SETTINGS] == {
        "mains": {
            "utility_energy_entity": "sensor.opower_current_bill_usage",
            "utility_cost_entity": "sensor.opower_current_bill_cost",
            "utility_statistic_id": "opower:utility_elec_consumption",
            "utility_source_type": "statistics",
            "utility_statistic_period": "day",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 8.5,
        }
    }


@pytest.mark.asyncio
async def test_options_utility_step_can_clear_existing_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(
        SimpleNamespace(
            data={CONF_UTILITY_COMPARISON_SETTINGS: {"mains": {}}},
            options={
                CONF_UTILITY_COMPARISON_SETTINGS: {
                    "mains": {
                        "utility_energy_entity": "sensor.old_utility_usage",
                        "tolerance_percent": 10.0,
                    }
                }
            },
        )
    )

    result = await flow.async_step_utility(
        {"enable_utility_comparison": False, "circuit_id": "mains"}
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_UTILITY_COMPARISON_SETTINGS] == {"mains": {}}


@pytest.mark.asyncio
async def test_options_advanced_step_saves_existing_setting_families() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Kitchen Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ]
        },
        options={},
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_advanced()

    assert result["type"] == "form"
    assert result["step_id"] == "select_advanced_circuit"

    result = await flow.async_step_select_advanced_circuit(
        {"circuit_id": "refrigerator"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "advanced_settings"

    result = await flow.async_step_advanced_settings(
        {
            "preset": "sensitive",
            "window_days": 14,
            "daily_spike_ratio": 0.35,
            "daily_goal_kwh": 2.5,
            "goal_alert_ratio": 0.9,
            "max_active_minutes": 120,
            "max_idle_minutes": 480,
            "cycle_start_day": 15,
            "budget_kwh": 90.0,
            "budget_alert_ratio": 0.85,
            "billing_min_elapsed_days": 5,
            "window_minutes": 30,
            "demand_limit_w": 1200.0,
            "breaker_amps": 20.0,
            "warning_ratio": 0.8,
            "window_hours": 72,
            "standby_threshold_w": 6.0,
            "always_on_alert_w": 12.0,
            "standby_min_samples": 36,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ADVANCED_SETTINGS]["refrigerator"] == {
        "preset": "sensitive",
        "window_days": 14,
        "daily_spike_ratio": 0.35,
        "daily_goal_kwh": 2.5,
        "goal_alert_ratio": 0.9,
        "max_active_minutes": 120,
        "max_idle_minutes": 480,
        "cycle_start_day": 15,
        "budget_kwh": 90.0,
        "budget_alert_ratio": 0.85,
        "min_elapsed_days": 5,
        "window_minutes": 30,
        "demand_limit_w": 1200.0,
        "breaker_amps": 20.0,
        "warning_ratio": 0.8,
        "window_hours": 72,
        "standby_threshold_w": 6.0,
        "always_on_alert_w": 12.0,
        "min_samples": 36,
    }


@pytest.mark.asyncio
async def test_options_advanced_step_saves_operating_detection_overrides() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Kitchen Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ]
        },
        options={},
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_select_advanced_circuit(
        {"circuit_id": "refrigerator"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "advanced_settings"

    result = await flow.async_step_advanced_settings(
        {
            "operating_detection_settings": {
                "operating_on_threshold_w": 25.0,
                "operating_off_threshold_w": 12.0,
                "operating_on_dwell_seconds": 10.0,
                "operating_off_dwell_seconds": 45.0,
                "operating_merge_gap_seconds": 90.0,
            }
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ADVANCED_SETTINGS]["refrigerator"] == {
        "preset": "balanced",
        "operating_off_threshold_w": 12.0,
    }


@pytest.mark.asyncio
async def test_options_advanced_step_resets_circuit_to_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Kitchen Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [],
                },
            ]
        },
        options={
            CONF_ADVANCED_SETTINGS: {
                "refrigerator": {
                    "preset": "sensitive",
                    "daily_spike_ratio": 0.35,
                    "standby_threshold_w": 6.0,
                },
                "hvac": {
                    "preset": "quiet",
                    "breaker_amps": 40.0,
                },
            }
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    await flow.async_step_select_advanced_circuit({"circuit_id": "refrigerator"})
    result = await flow.async_step_advanced_settings(
        {"analysis_settings": {"reset_advanced_settings_to_defaults": True}}
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ADVANCED_SETTINGS] == {
        "refrigerator": {},
        "hvac": {
            "preset": "quiet",
            "breaker_amps": 40.0,
        }
    }


@pytest.mark.asyncio
async def test_options_flow_rejects_bogus_retention_mode() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))
    result = await flow.async_step_sources({CONF_RETENTION_MODE: "forever"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_retention_mode"


@pytest.mark.asyncio
async def test_options_flow_rejects_malformed_mains_source_entities() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))
    result = await flow.async_step_sources(
        {CONF_MAINS_SOURCE_ENTITIES: {"sensor.main_l1_power": True}}
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_mains_source_entities"


@pytest.mark.asyncio
async def test_options_flow_preserves_valid_options() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    user_input = {
        CONF_SOURCE_DEVICES: ["meter-device"],
        CONF_EXTRA_SOURCE_ENTITIES: ["sensor.fridge_power", "sensor.fridge_current"],
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power", "sensor.main_l2_power"],
        CONF_SENSITIVITY: "sensitive",
        CONF_RETENTION_MODE: "diagnostic",
    }
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_sources(user_input)

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.fridge_power",
        "sensor.fridge_current",
    ]
    assert result["data"][CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]
    assert result["data"][CONF_SENSITIVITY] == "sensitive"


@pytest.mark.asyncio
async def test_options_sources_step_auto_routes_new_mains_sources() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_SOURCE_ENTITIES: ["sensor.refrigerator_power"],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power"],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.main_l2_power",
            ],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_ENABLE_EXPERIMENTAL_NILM] is True
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power"
    ]
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power",
    ]
    assert result["data"][CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


@pytest.mark.asyncio
async def test_options_flow_adds_complete_demo_bundle_from_toggle() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )
    from custom_components.circuitsetup_energy_analyzer.demo import (
        DEMO_SOURCE_ENTITY_IDS,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_DEMO_SOURCE_BUNDLE_ENABLED: True,
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DEMO_SOURCE_BUNDLE_ENABLED] is True
    demo_mains_source_entity_ids = {
        entity_id
        for entity_id in DEMO_SOURCE_ENTITY_IDS
        if "_demo_mains_" in entity_id
    }
    demo_assignable_source_entity_ids = (
        set(DEMO_SOURCE_ENTITY_IDS) - demo_mains_source_entity_ids
    )
    assert demo_assignable_source_entity_ids <= set(
        result["data"][CONF_EXTRA_SOURCE_ENTITIES]
    )
    assert demo_assignable_source_entity_ids <= set(
        result["data"][CONF_SOURCE_ENTITIES]
    )
    assert demo_mains_source_entity_ids <= set(
        result["data"][CONF_MAINS_SOURCE_ENTITIES]
    )


@pytest.mark.asyncio
async def test_options_flow_removes_demo_bundle_and_demo_assignments() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    real_circuit = {
        "circuit_id": "kitchen_refrigerator",
        "name": "Kitchen Refrigerator",
        "appliance_profile": "refrigerator",
        "mode": "single_phase",
        "sensors": [
            {
                "entity_id": "sensor.kitchen_refrigerator_active_power",
                "role": "real_power",
            }
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_DEMO_SOURCE_BUNDLE_ENABLED: True,
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.kitchen_refrigerator_active_power",
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.kitchen_refrigerator_active_power",
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.real_mains_power",
                "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
            ],
            CONF_CIRCUITS: [
                real_circuit,
                {
                    "circuit_id": "cs_energy_analyzer_demo_washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_washer_active_power"
                            ),
                            "role": "real_power",
                        }
                    ],
                },
            ],
            CONF_KNOWN_LOAD_CIRCUITS: [
                "kitchen_refrigerator",
                "cs_energy_analyzer_demo_washer",
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_DEMO_SOURCE_BUNDLE_ENABLED: False,
            CONF_SOURCE_DEVICES: [],
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.kitchen_refrigerator_active_power"],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.real_mains_power"],
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DEMO_SOURCE_BUNDLE_ENABLED] is False
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.kitchen_refrigerator_active_power"
    ]
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.kitchen_refrigerator_active_power"
    ]
    assert result["data"][CONF_MAINS_SOURCE_ENTITIES] == ["sensor.real_mains_power"]
    assert result["data"][CONF_CIRCUITS] == [real_circuit]
    assert result["data"][CONF_KNOWN_LOAD_CIRCUITS] == ["kitchen_refrigerator"]
    assert "cs_energy_analyzer_demo_washer" not in result["data"][
        CONF_CIRCUIT_ASSIGNMENTS
    ]


@pytest.mark.asyncio
async def test_options_flow_removing_demo_bundle_preserves_data_circuits() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    real_circuit = {
        "circuit_id": "kitchen_refrigerator",
        "name": "Kitchen Refrigerator",
        "appliance_profile": "refrigerator",
        "mode": "single_phase",
        "sensors": [
            {
                "entity_id": "sensor.kitchen_refrigerator_active_power",
                "role": "real_power",
            }
        ],
    }
    entry = SimpleNamespace(
        data={
            CONF_DEMO_SOURCE_BUNDLE_ENABLED: True,
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.kitchen_refrigerator_active_power",
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.kitchen_refrigerator_active_power",
                "sensor.cs_energy_analyzer_demo_washer_active_power",
            ],
            CONF_CIRCUITS: [
                real_circuit,
                {
                    "circuit_id": "cs_energy_analyzer_demo_washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_washer_active_power"
                            ),
                            "role": "real_power",
                        }
                    ],
                },
            ],
            CONF_KNOWN_LOAD_CIRCUITS: [
                "kitchen_refrigerator",
                "cs_energy_analyzer_demo_washer",
            ],
        },
        options={},
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_DEMO_SOURCE_BUNDLE_ENABLED: False,
            CONF_SOURCE_DEVICES: [],
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.kitchen_refrigerator_active_power"],
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [real_circuit]
    assert result["data"][CONF_KNOWN_LOAD_CIRCUITS] == ["kitchen_refrigerator"]
    assert "kitchen_refrigerator" in result["data"][CONF_CIRCUIT_ASSIGNMENTS]
    assert "cs_energy_analyzer_demo_washer" not in result["data"][
        CONF_CIRCUIT_ASSIGNMENTS
    ]


@pytest.mark.asyncio
async def test_options_flow_creates_recommended_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> None:
            self.calls.append(("async_create_dashboard", ()))

    coordinator = Coordinator()
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    form = await flow.async_step_dashboard()
    result = await flow.async_step_dashboard(
        {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT}
    )

    assert form["type"] == "form"
    assert _schema_default(form["data_schema"], CONF_DASHBOARD_LAYOUT) == (
        DASHBOARD_LAYOUT_STANDARD
    )
    assert _schema_validator(form["data_schema"], CONF_DASHBOARD_LAYOUT) == {
        "select": {
            "options": [
                {"value": "simple", "label": "Simple"},
                {"value": "standard", "label": "Standard"},
                {"value": "expert", "label": "Expert"},
            ]
        }
    }
    assert _schema_default(form["data_schema"], "remove_dashboard") is False
    assert _schema_default(form["data_schema"], "apply_entity_detail_profile") is False
    assert result["type"] == "create_entry"
    assert result["data"][CONF_DASHBOARD_LAYOUT] == DASHBOARD_LAYOUT_EXPERT
    assert coordinator.calls == [
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_EXPERT,)),
        ("async_create_dashboard", ()),
    ]


@pytest.mark.asyncio
async def test_options_flow_reports_dashboard_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> dict[str, str]:
            self.calls.append(("async_create_dashboard", ()))
            return {
                "action": "unavailable",
                "reason": "lovelace_dashboard_collection_unavailable",
            }

    coordinator = Coordinator()
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_dashboard(
        {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "dashboard"
    assert result["errors"] == {"base": "dashboard_creation_unavailable"}
    assert _schema_default(result["data_schema"], CONF_DASHBOARD_LAYOUT) == (
        DASHBOARD_LAYOUT_EXPERT
    )
    assert coordinator.calls == [
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_EXPERT,)),
        ("async_create_dashboard", ()),
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_STANDARD,)),
    ]


@pytest.mark.asyncio
async def test_options_flow_dashboard_warns_when_layout_exceeds_entity_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> None:
            self.calls.append(("async_create_dashboard", ()))

    coordinator = Coordinator()
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_SIMPLE,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_dashboard(
        {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "dashboard"
    assert result["errors"] == {
        "base": "dashboard_layout_requires_higher_entity_detail"
    }
    assert _schema_default(result["data_schema"], CONF_DASHBOARD_LAYOUT) == (
        DASHBOARD_LAYOUT_EXPERT
    )
    assert (
        _schema_default(result["data_schema"], "apply_entity_detail_profile")
        is False
    )
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_options_flow_dashboard_matches_detail_without_registry_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    calls: list[tuple[object, object, str]] = []

    def fake_apply(hass, entry, detail_level):
        calls.append((hass, entry, detail_level))
        return {"total": 8, "will_enable": 5}

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> None:
            self.calls.append(("async_create_dashboard", ()))

    monkeypatch.setattr(
        config_flow,
        "_apply_entity_detail_profile_to_existing_entities",
        fake_apply,
    )
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    coordinator = Coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_SIMPLE,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = hass

    result = await flow.async_step_dashboard(
        {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT,
            "apply_entity_detail_profile": True,
        }
    )

    _assert_create_entry_result(
        result,
        {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
        },
    )
    assert calls == []
    assert coordinator.calls == [
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_EXPERT,)),
        ("async_create_dashboard", ()),
    ]


@pytest.mark.asyncio
async def test_options_flow_dashboard_allows_expert_layout_with_standard_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> None:
            self.calls.append(("async_create_dashboard", ()))

    coordinator = Coordinator()
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_dashboard(
        {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT}
    )

    _assert_create_entry_result(
        result,
        {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
        },
    )
    assert coordinator.calls == [
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_EXPERT,)),
        ("async_create_dashboard", ()),
    ]


@pytest.mark.asyncio
async def test_options_flow_dashboard_create_failure_does_not_apply_registry_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    calls: list[tuple[object, object, str]] = []

    def fake_apply(hass, entry, detail_level):
        calls.append((hass, entry, detail_level))
        return {"total": 8, "will_enable": 5}

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> dict[str, str]:
            self.calls.append(("async_create_dashboard", ()))
            return {
                "action": "unavailable",
                "reason": "lovelace_dashboard_collection_unavailable",
            }

    monkeypatch.setattr(
        config_flow,
        "_apply_entity_detail_profile_to_existing_entities",
        fake_apply,
    )
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    coordinator = Coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_SIMPLE,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_SIMPLE,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = hass

    result = await flow.async_step_dashboard(
        {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            "apply_entity_detail_profile": True,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "dashboard"
    assert result["errors"] == {"base": "dashboard_creation_unavailable"}
    assert calls == []
    assert coordinator.calls == [
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_STANDARD,)),
        ("async_create_dashboard", ()),
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_SIMPLE,)),
    ]


@pytest.mark.asyncio
async def test_options_flow_removes_recommended_dashboard_without_changing_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        async def async_set_dashboard_layout(self, layout: str) -> None:
            self.calls.append(("async_set_dashboard_layout", (layout,)))

        async def async_create_dashboard(self) -> None:
            self.calls.append(("async_create_dashboard", ()))

        async def async_remove_dashboard(self) -> None:
            self.calls.append(("async_remove_dashboard", ()))

    coordinator = Coordinator()
    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_STANDARD,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    result = await flow.async_step_dashboard(
        {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT,
            "remove_dashboard": True,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DASHBOARD_LAYOUT] == DASHBOARD_LAYOUT_STANDARD
    assert coordinator.calls == [("async_remove_dashboard", ())]


@pytest.mark.asyncio
async def test_options_sources_step_preserves_existing_mains_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
                "sensor.fridge_power",
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
                "sensor.fridge_power",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.main_l1_power",
                "sensor.main_l2_power",
                "sensor.fridge_power",
                "sensor.laundry_washer_active_power",
            ],
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_SENSITIVITY: "balanced",
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


@pytest.mark.asyncio
async def test_options_sources_step_merges_new_sensor_into_existing_appliance() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    existing_circuit = {
        "circuit_id": "car_charger",
        "name": "Car Charger",
        "appliance_profile": "ev_charger",
        "mode": "dual_phase",
        "power_flow": "load",
        "retention_mode": "diagnostic",
        "daily_energy_goal_kwh": 12.5,
        "sensors": [
            {
                "entity_id": "sensor.car_charger_l1_active_power",
                "role": "real_power",
                "leg": "a",
            },
            {
                "entity_id": "sensor.car_charger_l2_active_power",
                "role": "real_power",
                "leg": "b",
            },
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
            ],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
            ],
            CONF_CIRCUITS: [existing_circuit],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
                "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            ],
            CONF_RETENTION_MODE: "diagnostic",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [
        {
            **existing_circuit,
            "sensors": [
                *existing_circuit["sensors"],
                {
                    "entity_id": (
                        "sensor.circuitsetup_energy_analyzer_car_charger_l1_current"
                    ),
                    "role": "current",
                    "leg": "a",
                },
            ],
        }
    ]
    assignment_lines = [
        line
        for line in result["data"][CONF_CIRCUIT_ASSIGNMENTS].splitlines()
        if line and not line.startswith("#")
    ]
    assert len(assignment_lines) == 1
    assert assignment_lines[0].startswith("Car Charger | ev_charger | dual_phase |")


@pytest.mark.asyncio
async def test_options_sources_step_preserves_string_sensors_when_merging() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    existing_circuit = {
        "circuit_id": "car_charger",
        "name": "Car Charger",
        "appliance_profile": "ev_charger",
        "mode": "dual_phase",
        "sensors": [
            "sensor.car_charger_l1_active_power",
            "sensor.car_charger_l2_active_power",
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            ],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            ],
            CONF_CIRCUITS: [existing_circuit],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            ],
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [
        {
            **existing_circuit,
            "sensors": [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
                {
                    "entity_id": (
                        "sensor.circuitsetup_energy_analyzer_car_charger_l1_current"
                    ),
                    "role": "current",
                    "leg": "a",
                },
            ],
        }
    ]


@pytest.mark.asyncio
async def test_options_assignment_updates_dual_phase_mode_from_available_legs() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    existing_circuit = {
        "circuit_id": "car_charger",
        "name": "Car Charger",
        "appliance_profile": "ev_charger",
        "mode": "single_phase",
        "sensors": [
            {
                "entity_id": "sensor.car_charger_l1_active_power",
                "role": "real_power",
                "leg": "a",
            },
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
            ],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
            ],
            CONF_CIRCUITS: [existing_circuit],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    await flow.async_step_assign()
    await flow.async_step_select_assignment({"selected_assignment": "car_charger"})
    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
            ],
            "circuit_name": "Car Charger",
            "appliance_profile": "ev_charger",
            "circuit_retention_mode": "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS][0]["mode"] == "dual_phase"


@pytest.mark.asyncio
async def test_options_assignment_review_preserves_outdoor_temperature_entity() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()

    assert result["type"] == "form"
    assert flow._pending_config[CONF_OUTDOOR_TEMPERATURE_ENTITY] == (
        "sensor.outdoor_temperature"
    )


@pytest.mark.asyncio
async def test_options_assignment_review_saves_optional_rain_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.sump_pump_power"],
            CONF_SOURCE_ENTITIES: ["sensor.sump_pump_power"],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_sources(
        {
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.sump_pump_power"],
            CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain",
            CONF_RAIN_INTENSITY_ENTITY: "sensor.precipitation_rate",
            CONF_SENSITIVITY: "balanced",
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_RAIN_SENSOR_ENTITY] == "binary_sensor.rain"
    assert result["data"][CONF_RAIN_INTENSITY_ENTITY] == "sensor.precipitation_rate"


@pytest.mark.asyncio
async def test_user_flow_builds_assignment_step_from_source_selection() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.garage_vehicle_charging_l1_active_power",
                "sensor.garage_vehicle_charging_l2_active_power",
                "sensor.garage_vehicle_charging_l1_current",
                "sensor.garage_vehicle_charging_l2_current",
            ],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_mains_l1_voltage"],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_keys(result["data_schema"]) == {
        "include_circuit",
        "included_sensors",
        "circuit_name",
        "appliance_profile",
        "circuit_retention_mode",
    }
    assert _schema_default(result["data_schema"], "circuit_name") == (
        "Garage Vehicle Charging"
    )
    assert _schema_default(result["data_schema"], "appliance_profile") == "ev_charger"
    assert _schema_default(result["data_schema"], "circuit_retention_mode") == (
        "standard"
    )
    assert _schema_default(result["data_schema"], "include_circuit") is True
    assert result["description_placeholders"] == {
        "circuit_name": "Garage Vehicle Charging",
        "appliance_profile": "ev_charger",
        "circuit_mode": "dual_phase",
        "power_flow": "load",
    }


@pytest.mark.asyncio
async def test_user_flow_rejects_claimed_source_in_later_group() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    sources = ["sensor.refrigerator_power", "sensor.microwave_power"]
    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user({CONF_EXTRA_SOURCE_ENTITIES: sources})
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Kitchen Appliances",
            "appliance_profile": "mixed",
            "included_sensors": sources,
        }
    )

    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Microwave",
            "appliance_profile": "microwave",
            "included_sensors": ["sensor.microwave_power"],
        }
    )

    assert result["step_id"] == "assign"
    assert result["errors"] == {"base": "invalid_circuit_assignments"}

    result = await flow.async_step_assign({"include_circuit": False})
    assert result["step_id"] == "utility"
    circuits = flow._pending_final_config[CONF_CIRCUITS]
    assert len(circuits) == 1
    assert [sensor["entity_id"] for sensor in circuits[0]["sensors"]] == sources


@pytest.mark.parametrize("leg_token", ["leg", "line", "phase"])
@pytest.mark.asyncio
async def test_user_flow_detects_numeric_leg_suffixes_as_dual_phase(
    leg_token: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    source_entities = [
        f"sensor.dryer_{leg_token}_1_power",
        f"sensor.dryer_{leg_token}_2_power",
    ]
    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user({CONF_EXTRA_SOURCE_ENTITIES: source_entities})

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Dryer"
    assert _schema_default(result["data_schema"], "appliance_profile") == "dryer"
    assert result["description_placeholders"]["circuit_mode"] == "dual_phase"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Dryer",
            "appliance_profile": "dryer",
            "included_sensors": source_entities,
        }
    )

    assert result["type"] == "form"
    circuit = flow._pending_final_config[CONF_CIRCUITS][0]
    assert circuit["mode"] == "dual_phase"
    assert [sensor["leg"] for sensor in circuit["sensors"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_user_flow_downgrades_normally_dual_phase_appliance_with_one_leg() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.garage_vehicle_charging_l1_active_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "appliance_profile") == "ev_charger"
    assert result["description_placeholders"]["circuit_mode"] == "single_phase"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Garage Vehicle Charging",
            "appliance_profile": "ev_charger",
            "included_sensors": ["sensor.garage_vehicle_charging_l1_active_power"],
        }
    )

    assert result["type"] == "form"
    assert flow._pending_final_config[CONF_CIRCUITS][0]["mode"] == "single_phase"


@pytest.mark.parametrize(
    ("circuit_name", "profile", "source_entities", "expected_mode"),
    [
        (
            "Well Pump",
            "water_pump",
            [
                "sensor.well_pump_l1_active_power",
                "sensor.well_pump_l2_active_power",
            ],
            "dual_phase",
        ),
        (
            "Sump Pump",
            "sump_pump",
            [
                "sensor.sump_pump_l1_active_power",
                "sensor.sump_pump_l2_active_power",
            ],
            "dual_phase",
        ),
        (
            "Pool Pump",
            "pool_pump",
            [
                "sensor.pool_pump_l1_active_power",
                "sensor.pool_pump_l2_active_power",
            ],
            "dual_phase",
        ),
        (
            "Well Pump",
            "water_pump",
            [
                "sensor.well_pump_l1_active_power",
            ],
            "single_phase",
        ),
        (
            "Water Pump",
            "water_pump",
            [
                "sensor.water_pump_l1_active_power",
            ],
            "single_phase",
        ),
        (
            "Water Pump",
            "water_pump",
            [
                "sensor.water_pump_l1_active_power",
                "sensor.water_pump_l2_active_power",
            ],
            "dual_phase",
        ),
        (
            "Booster Pump",
            "water_pump",
            [
                "sensor.booster_pump_l1_active_power",
            ],
            "single_phase",
        ),
        (
            "Electric Heat",
            "electric_heat",
            [
                "sensor.garage_electric_heat_l1_active_power",
                "sensor.garage_electric_heat_l2_active_power",
            ],
            "dual_phase",
        ),
        (
            "Electric Heat",
            "electric_heat",
            [
                "sensor.garage_electric_heat_l1_active_power",
            ],
            "single_phase",
        ),
    ],
)
@pytest.mark.asyncio
async def test_user_flow_treats_two_leg_pumps_as_dual_phase(
    circuit_name: str,
    profile: str,
    source_entities: list[str],
    expected_mode: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {CONF_EXTRA_SOURCE_ENTITIES: source_entities}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "appliance_profile") == profile
    assert result["description_placeholders"]["circuit_mode"] == expected_mode

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": circuit_name,
            "appliance_profile": profile,
            "included_sensors": source_entities,
        }
    )

    circuit = flow._pending_final_config[CONF_CIRCUITS][0]
    assert result["type"] == "form"
    assert circuit["mode"] == expected_mode
    if expected_mode == "dual_phase":
        assert [sensor["leg"] for sensor in circuit["sensors"]] == ["a", "b"]


@pytest.mark.parametrize(
    ("circuit_id", "expected_name", "expected_profile", "expected_mode", "suffixes"),
    [
        (
            "car_charger",
            "Car Charger",
            "ev_charger",
            "dual_phase",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "hvac",
            "Hvac",
            "hvac",
            "dual_phase",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "dryer",
            "Dryer",
            "dryer",
            "dual_phase",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "water_heater",
            "Water Heater",
            "water_heater",
            "dual_phase",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "refrigerator",
            "Refrigerator",
            "refrigerator",
            "single_phase",
            ("power_l1", "current_l1"),
        ),
    ],
)
@pytest.mark.asyncio
async def test_user_flow_groups_appliance_sources_with_metric_before_leg(
    circuit_id: str,
    expected_name: str,
    expected_profile: str,
    expected_mode: str,
    suffixes: tuple[str, ...],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    source_entities = [f"sensor.{circuit_id}_{suffix}" for suffix in suffixes]
    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: source_entities,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == expected_name
    assert _schema_default(result["data_schema"], "appliance_profile") == (
        expected_profile
    )
    assert _schema_default(result["data_schema"], "included_sensors") == source_entities
    assert result["description_placeholders"] == {
        "circuit_name": expected_name,
        "appliance_profile": expected_profile,
        "circuit_mode": expected_mode,
        "power_flow": "load",
    }

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": expected_name,
            "appliance_profile": expected_profile,
            "included_sensors": source_entities,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "utility"
    circuit = flow._pending_final_config[CONF_CIRCUITS][0]
    assert circuit["circuit_id"] == circuit_id
    assert [sensor["entity_id"] for sensor in circuit["sensors"]] == source_entities


def test_assignment_groups_from_sources_returns_empty_for_mains_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        assignment_groups_from_sources,
    )

    assert (
        assignment_groups_from_sources(
            ["sensor.main_l1_power", "sensor.main_l2_power"],
            mains_source_entities=["sensor.main_l1_power", "sensor.main_l2_power"],
        )
        == []
    )


def test_automatic_assignments_route_meter_metrics_and_use_channel_names(
    monkeypatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)
    sources = [
        "sensor.circuitsetup_energy_meter_24x_a4e634_voltage",
        "sensor.circuitsetup_energy_meter_24x_a4e634_frequency",
        "sensor.circuitsetup_energy_meter_24x_a4e634_car_charger_peak_a",
        "sensor.circuitsetup_energy_meter_24x_a4e634_car_charger_harmonic_power",
        "sensor.circuitsetup_energy_meter_24x_a4e634_pressure_pump_watts",
        "sensor.circuitsetup_energy_meter_24x_a4e634_ac_watts",
    ]

    validated = config_flow.validate_setup_input(
        {CONF_EXTRA_SOURCE_ENTITIES: sources, CONF_RETENTION_MODE: "standard"}
    )
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == sources[:2]

    groups = config_flow.assignment_groups_from_sources(
        validated[CONF_SOURCE_ENTITIES],
        mains_source_entities=validated[CONF_MAINS_SOURCE_ENTITIES],
    )

    assert [group["name"] for group in groups] == [
        "Car Charger",
        "Pressure Pump",
        "AC",
    ]
    assert [group["appliance_profile"] for group in groups] == [
        "ev_charger",
        "water_pump",
        "hvac_compressor",
    ]
    assert groups[0]["entity_ids"] == (sources[2],)
    assert config_flow._assignment_sensor_options(groups[0]["entity_ids"]) == [
        {
            "value": sources[2],
            "label": f"Car Charger Peak A ({sources[2]})",
        }
    ]

    circuit = config_flow._circuit_from_assignment_group(
        groups[0],
        {
            "include_circuit": True,
            "included_sensors": [sources[2]],
            "circuit_name": "Car Charger",
            "appliance_profile": "ev_charger",
        },
    )
    assert circuit is not None
    assert circuit["sensors"][0]["role"] == "peak_current"


def test_automatic_assignments_exclude_total_titles_but_keep_saved() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        assignment_groups_from_sources,
    )

    source = "sensor.circuitsetup_energy_meter_24x_a4e634_channel_1_power"
    source_names = {source: "CircuitSetup Energy Meter House Total"}

    assert assignment_groups_from_sources([source], source_names=source_names) == []

    saved = {
        "circuit_id": "house_total",
        "name": "House Total",
        "appliance_profile": "mixed",
        "mode": "mixed",
        "sensors": [{"entity_id": source, "role": "real_power"}],
    }
    groups = assignment_groups_from_sources(
        [source],
        source_names=source_names,
        existing_circuits=[saved],
    )

    assert len(groups) == 1
    assert groups[0]["circuit_id"] == "house_total"


def test_empty_assignment_sensor_list_does_not_offer_placeholder_value() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _assignment_schema,
        _strict_string_list,
    )

    schema = _assignment_schema(
        {
            "name": "Circuit",
            "appliance_profile": "mixed",
            "entity_ids": (),
        }
    )

    assert "included_sensors" not in _schema_keys(schema)
    assert (
        _strict_string_list(
            ["__no_items_available__"],
            invalid_error_key="invalid_circuit_assignments",
        )
        == []
    )


def test_unassigned_filtered_sources_remain_available_for_later_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _final_config_without_assignment_review,
    )

    source = "sensor.car_charger_l1_harmonic_power"
    final_config = _final_config_without_assignment_review(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [source],
            CONF_SOURCE_ENTITIES: [source],
        }
    )

    assert final_config[CONF_EXTRA_SOURCE_ENTITIES] == [source]
    assert final_config[CONF_SOURCE_ENTITIES] == []


def test_assignment_text_builds_circuits_and_excludes_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        build_config_from_assignment_input,
    )

    pending = {
        CONF_SOURCE_ENTITIES: [
            "sensor.hvac_l1_power",
            "sensor.hvac_l2_power",
            "sensor.hvac_l1_current",
            "sensor.hvac_l2_current",
            "sensor.basement_lights_power",
        ],
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power"],
        CONF_SOURCE_DEVICES: ["meter-device"],
        CONF_EXTRA_SOURCE_ENTITIES: [],
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_SENSITIVITY: "balanced",
        CONF_RETENTION_MODE: "standard",
    }

    config = build_config_from_assignment_input(
        pending,
        {
            CONF_CIRCUIT_ASSIGNMENTS: "\n".join(
                [
                    (
                        "A/C Compressor | hvac_compressor | dual_phase | "
                        "sensor.hvac_l1_power, sensor.hvac_l2_power, "
                        "sensor.hvac_l1_current, sensor.hvac_l2_current"
                    ),
                    "Basement Lights | exclude | mixed | sensor.basement_lights_power",
                ]
            )
        },
    )

    assert config[CONF_SOURCE_DEVICES] == ["meter-device"]
    assert config[CONF_SOURCE_ENTITIES] == [
        "sensor.hvac_l1_power",
        "sensor.hvac_l2_power",
        "sensor.hvac_l1_current",
        "sensor.hvac_l2_current",
    ]
    assert config["circuits"] == [
        {
            "circuit_id": "a_c_compressor",
            "name": "A/C Compressor",
            "appliance_profile": "hvac_compressor",
            "mode": "dual_phase",
            "sensors": [
                {
                    "entity_id": "sensor.hvac_l1_power",
                    "role": "real_power",
                    "leg": "a",
                },
                {
                    "entity_id": "sensor.hvac_l2_power",
                    "role": "real_power",
                    "leg": "b",
                },
                {
                    "entity_id": "sensor.hvac_l1_current",
                    "role": "current",
                    "leg": "a",
                },
                {
                    "entity_id": "sensor.hvac_l2_current",
                    "role": "current",
                    "leg": "b",
                },
            ],
        }
    ]


@pytest.mark.asyncio
async def test_assignment_step_creates_entry_with_user_circuit_assignments() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.air_handler_active_power",
                "sensor.air_handler_current",
                "sensor.sump_pump_active_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Air Handler"
    assert _schema_default(result["data_schema"], "appliance_profile") == "hvac_blower"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "HVAC Blower",
            "appliance_profile": "hvac_blower",
            "circuit_retention_mode": "diagnostic",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Sump Pump"
    assert _schema_default(result["data_schema"], "appliance_profile") == "sump_pump"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Sump Pump",
            "appliance_profile": "sump_pump",
            "circuit_retention_mode": "standard",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.air_handler_active_power",
        "sensor.air_handler_current",
        "sensor.sump_pump_active_power",
    ]
    assert result["data"]["circuits"] == [
        {
            "circuit_id": "hvac_blower",
            "name": "HVAC Blower",
            "appliance_profile": "hvac_blower",
            "mode": "single_phase",
            "power_flow": "load",
            "retention_mode": "diagnostic",
            "sensors": [
                {
                    "entity_id": "sensor.air_handler_active_power",
                    "role": "real_power",
                    "leg": None,
                },
                {
                    "entity_id": "sensor.air_handler_current",
                    "role": "current",
                    "leg": None,
                },
            ],
        },
        {
            "circuit_id": "sump_pump",
            "name": "Sump Pump",
            "appliance_profile": "sump_pump",
            "mode": "single_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {
                    "entity_id": "sensor.sump_pump_active_power",
                    "role": "real_power",
                    "leg": None,
                }
            ],
        },
    ]


@pytest.mark.asyncio
async def test_assignment_step_allows_manual_override_before_saving() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.garage_ac_compressor_l1_active_power",
                "sensor.garage_ac_compressor_l2_active_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert _schema_default(result["data_schema"], "appliance_profile") == (
        "hvac_compressor"
    )
    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Garage HVAC System",
            "appliance_profile": "hvac",
            "circuit_retention_mode": "standard",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
    assert result["data"]["circuits"][0]["name"] == "Garage HVAC System"
    assert result["data"]["circuits"][0]["appliance_profile"] == "hvac"
    assert result["data"]["circuits"][0]["mode"] == "dual_phase"
    assert result["data"]["circuits"][0]["power_flow"] == "load"
    assert result["data"]["circuits"][0]["retention_mode"] == "standard"


@pytest.mark.asyncio
async def test_setup_utility_step_saves_opower_comparison_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.panel_import_energy",
                "sensor.refrigerator_energy",
            ],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_import_energy"],
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": ["sensor.refrigerator_energy"],
            "circuit_name": "Refrigerator",
            "appliance_profile": "refrigerator",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility(
        {
            "enable_utility_comparison": True,
            "circuit_id": "mains",
            "utility_energy_entity": "sensor.typical_monthly_electric_usage",
            "utility_source_type": "entity",
            "utility_statistic_period": "day",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 12.0,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_UTILITY_COMPARISON_SETTINGS] == {
        "mains": {
            "utility_energy_entity": "sensor.typical_monthly_electric_usage",
            "utility_source_type": "entity",
            "utility_statistic_period": "day",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 12.0,
        }
    }


@pytest.mark.asyncio
async def test_setup_nilm_step_saves_known_load_circuits_with_selector() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_active_power",
                "sensor.hvac_l1_active_power",
                "sensor.hvac_l2_active_power",
            ],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_mains_active_power"],
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": ["sensor.refrigerator_active_power"],
            "circuit_name": "Refrigerator",
            "appliance_profile": "refrigerator",
            "circuit_retention_mode": "standard",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": [
                "sensor.hvac_l1_active_power",
                "sensor.hvac_l2_active_power",
            ],
            "circuit_name": "HVAC",
            "appliance_profile": "hvac",
            "circuit_retention_mode": "diagnostic",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "nilm"
    assert _schema_keys(result["data_schema"]) == {CONF_KNOWN_LOAD_CIRCUITS}

    result = await flow.async_step_nilm(
        {CONF_KNOWN_LOAD_CIRCUITS: ["refrigerator", "hvac"]}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_KNOWN_LOAD_CIRCUITS] == ["refrigerator", "hvac"]


@pytest.mark.asyncio
async def test_options_nilm_step_updates_known_load_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_KNOWN_LOAD_CIRCUITS: ["fridge"],
            CONF_CIRCUITS: [
                {"circuit_id": "fridge", "name": "Fridge"},
                {"circuit_id": "hvac", "name": "HVAC"},
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                },
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    assert "mains" in result["menu_options"]
    assert "nilm" not in result["menu_options"]

    result = await flow.async_step_mains()

    assert result["type"] == "form"
    assert result["step_id"] == "mains"
    assert _schema_default(result["data_schema"], CONF_KNOWN_LOAD_CIRCUITS) == [
        "fridge"
    ]

    result = await flow.async_step_mains(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: [],
            CONF_KNOWN_LOAD_CIRCUITS: ["hvac"],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_KNOWN_LOAD_CIRCUITS] == ["hvac"]


@pytest.mark.asyncio
async def test_options_assignment_step_prefills_saved_classification() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.air_handler_active_power",
                "sensor.air_handler_current",
            ],
            "circuits": [
                {
                    "circuit_id": "hvac_blower",
                    "name": "HVAC Blower",
                    "appliance_profile": "hvac_blower",
                    "mode": "single_phase",
                    "sensors": [
                        {
                            "entity_id": "sensor.air_handler_active_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.air_handler_current",
                            "role": "current",
                        },
                    ],
                }
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["type"] == "form"
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "hvac_blower"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC Blower"
    assert _schema_default(result["data_schema"], "appliance_profile") == "hvac_blower"


@pytest.mark.asyncio
async def test_options_assignment_step_starts_from_saved_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.air_handler_active_power",
                "sensor.air_handler_current",
            ],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac_blower",
                    "name": "HVAC Blower",
                    "appliance_profile": "hvac_blower",
                    "mode": "single_phase",
                    "sensors": [
                        {
                            "entity_id": "sensor.air_handler_active_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.air_handler_current",
                            "role": "current",
                        },
                    ],
                }
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()

    assert result["type"] == "form"
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "hvac_blower"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC Blower"
    assert _schema_default(result["data_schema"], "appliance_profile") == "hvac_blower"


@pytest.mark.asyncio
async def test_options_assignment_review_selects_one_saved_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
        assignment_picker_options,
    )

    circuits = [
        {
            "circuit_id": "upstairs_hvac",
            "name": "Upstairs HVAC",
            "appliance_profile": "hvac",
            "mode": "dual_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": "sensor.upstairs_hvac_l1_power", "role": "real_power"},
                {"entity_id": "sensor.upstairs_hvac_l2_power", "role": "real_power"},
            ],
        },
        {
            "circuit_id": "downstairs_hvac",
            "name": "Downstairs HVAC",
            "appliance_profile": "hvac",
            "mode": "dual_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": "sensor.downstairs_hvac_l1_power", "role": "real_power"},
                {"entity_id": "sensor.downstairs_hvac_l2_power", "role": "real_power"},
            ],
        },
    ]
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.upstairs_hvac_l1_power",
                "sensor.upstairs_hvac_l2_power",
                "sensor.downstairs_hvac_l1_power",
                "sensor.downstairs_hvac_l2_power",
            ],
            CONF_CIRCUITS: circuits,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()

    assert result["type"] == "form"
    assert result["step_id"] == "select_assignment"
    assert _schema_keys(result["data_schema"]) == {
        "selected_assignment",
        "remove_assignments",
    }
    assert assignment_picker_options(circuits) == [
        {
            "value": "upstairs_hvac",
            "label": "Upstairs HVAC - Dual Phase - 2 sensors",
        },
        {
            "value": "downstairs_hvac",
            "label": "Downstairs HVAC - Dual Phase - 2 sensors",
        },
    ]

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "downstairs_hvac"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Downstairs HVAC"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": [
                "sensor.downstairs_hvac_l1_power",
                "sensor.downstairs_hvac_l2_power",
            ],
            "circuit_name": "Downstairs Heat Pump",
            "appliance_profile": "hvac",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [
        circuits[0],
        {
            "circuit_id": "downstairs_hvac",
            "name": "Downstairs Heat Pump",
            "appliance_profile": "hvac",
            "mode": "dual_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {
                    "entity_id": "sensor.downstairs_hvac_l1_power",
                    "role": "real_power",
                    "leg": "a",
                },
                {
                    "entity_id": "sensor.downstairs_hvac_l2_power",
                    "role": "real_power",
                    "leg": "b",
                },
            ],
        },
    ]


@pytest.mark.asyncio
async def test_options_assignment_review_can_remove_selected_appliance() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    circuits = [
        {
            "circuit_id": "refrigerator",
            "name": "Kitchen Refrigerator",
            "appliance_profile": "refrigerator",
            "mode": "single_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": "sensor.refrigerator_power", "role": "real_power"},
            ],
        },
        {
            "circuit_id": "microwave",
            "name": "Microwave",
            "appliance_profile": "microwave",
            "mode": "single_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": "sensor.microwave_power", "role": "real_power"},
            ],
        },
    ]
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.microwave_power",
            ],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.microwave_power",
            ],
            CONF_CIRCUITS: circuits,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "microwave"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert "remove_from_analysis" in _schema_keys(result["data_schema"])

    result = await flow.async_step_assign({"remove_from_analysis": True})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [circuits[0]]
    assert result["data"][CONF_SOURCE_ENTITIES] == ["sensor.refrigerator_power"]
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power",
        "sensor.microwave_power",
    ]


@pytest.mark.asyncio
async def test_options_assignment_review_keeps_removed_extra_sources_inactive() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    refrigerator = {
        "circuit_id": "refrigerator",
        "name": "Kitchen Refrigerator",
        "appliance_profile": "refrigerator",
        "mode": "single_phase",
        "power_flow": "load",
        "retention_mode": "standard",
        "sensors": [
            {"entity_id": "sensor.refrigerator_power", "role": "real_power"},
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: ["sensor.refrigerator_power"],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.microwave_power",
            ],
            CONF_CIRCUITS: [refrigerator],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "refrigerator"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": ["sensor.refrigerator_power"],
            "circuit_name": "Kitchen Refrigerator",
            "appliance_profile": "refrigerator",
        }
    )

    assert result["type"] == "create_entry"
    assert len(result["data"][CONF_CIRCUITS]) == 1
    assert result["data"][CONF_CIRCUITS][0]["circuit_id"] == "refrigerator"
    assert result["data"][CONF_SOURCE_ENTITIES] == ["sensor.refrigerator_power"]
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power",
        "sensor.microwave_power",
    ]


@pytest.mark.asyncio
async def test_options_assignment_review_can_reassign_inactive_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    refrigerator = {
        "circuit_id": "refrigerator",
        "name": "Kitchen Refrigerator",
        "appliance_profile": "refrigerator",
        "mode": "single_phase",
        "power_flow": "load",
        "retention_mode": "standard",
        "sensors": [
            {"entity_id": "sensor.refrigerator_power", "role": "real_power"},
        ],
    }
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: ["sensor.refrigerator_power"],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.microwave_power",
            ],
            CONF_CIRCUITS: [refrigerator],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "refrigerator"}
    )
    assert result["step_id"] == "assign"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "included_sensors": [
                "sensor.refrigerator_power",
                "sensor.microwave_power",
            ],
            "circuit_name": "Kitchen Appliances",
            "appliance_profile": "mixed",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.refrigerator_power",
        "sensor.microwave_power",
    ]
    assert [
        sensor["entity_id"]
        for sensor in result["data"][CONF_CIRCUITS][0]["sensors"]
    ] == ["sensor.refrigerator_power", "sensor.microwave_power"]


@pytest.mark.asyncio
async def test_options_assignment_review_can_bulk_remove_appliances() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    circuits = [
        {
            "circuit_id": circuit_id,
            "name": circuit_id.title(),
            "appliance_profile": "mixed",
            "mode": "mixed",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": f"sensor.{circuit_id}_power", "role": "real_power"}
            ],
        }
        for circuit_id in ("first", "second", "third")
    ]
    source_entities = [
        "sensor.first_power",
        "sensor.second_power",
        "sensor.third_power",
    ]
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: source_entities,
            CONF_EXTRA_SOURCE_ENTITIES: source_entities,
            CONF_CIRCUITS: circuits,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert _schema_keys(result["data_schema"]) == {
        "selected_assignment",
        "remove_assignments",
    }

    result = await flow.async_step_select_assignment(
        {
            "selected_assignment": "third",
            "remove_assignments": ["first", "second"],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == [circuits[2]]
    assert result["data"][CONF_SOURCE_ENTITIES] == ["sensor.third_power"]
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == source_entities


@pytest.mark.asyncio
async def test_options_assignment_review_can_remove_auto_inferred_appliance() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    source_entities = [
        "sensor.dryer_power_l1",
        "sensor.dryer_current_l1",
        "sensor.dryer_power_l2",
        "sensor.dryer_current_l2",
    ]
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: source_entities,
            CONF_EXTRA_SOURCE_ENTITIES: source_entities,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment({"selected_assignment": "dryer"})
    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Dryer"
    assert "remove_from_analysis" in _schema_keys(result["data_schema"])

    result = await flow.async_step_assign({"remove_from_analysis": True})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == []
    assert result["data"][CONF_SOURCE_ENTITIES] == []
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == source_entities


@pytest.mark.asyncio
async def test_options_assignment_review_can_remove_last_appliance() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    circuits = [
        {
            "circuit_id": "microwave",
            "name": "Microwave",
            "appliance_profile": "microwave",
            "mode": "single_phase",
            "power_flow": "load",
            "retention_mode": "standard",
            "sensors": [
                {"entity_id": "sensor.microwave_power", "role": "real_power"},
            ],
        },
    ]
    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: ["sensor.microwave_power"],
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.microwave_power"],
            CONF_CIRCUITS: circuits,
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "microwave"}
    )
    assert "remove_from_analysis" in _schema_keys(result["data_schema"])

    result = await flow.async_step_assign({"remove_from_analysis": True})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS] == []
    assert result["data"][CONF_SOURCE_ENTITIES] == []
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == ["sensor.microwave_power"]


def test_circuit_mode_options_use_human_labels() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        circuit_mode_options,
    )

    assert circuit_mode_options() == [
        {"value": "single_phase", "label": "Single Phase"},
        {"value": "dual_phase", "label": "Dual Phase"},
        {"value": "mixed", "label": "Mixed"},
        {"value": "mains_nilm", "label": "Mains NILM"},
    ]


def test_power_flow_options_use_human_labels() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        power_flow_options,
    )

    assert power_flow_options() == [
        {"value": "load", "label": "Load"},
        {"value": "generation", "label": "Generation / Solar Export"},
        {"value": "mains_net", "label": "Mains Net / Import-Export"},
    ]


@pytest.mark.asyncio
async def test_assignment_step_exposes_power_flow_for_solar_and_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.roof_solar_inverter_active_power",
            ],
        }
    )

    assert result["type"] == "form"
    assert _schema_default(result["data_schema"], "appliance_profile") == (
        "solar_inverter"
    )
    assert result["description_placeholders"]["circuit_mode"] == "dual_phase"
    assert "power_flow" not in _schema_keys(result["data_schema"])

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Roof Solar",
            "appliance_profile": "solar_inverter",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS][0]["mode"] == "dual_phase"
    assert result["data"][CONF_CIRCUITS][0]["power_flow"] == "generation"


@pytest.mark.asyncio
async def test_assignment_step_auto_suggests_washer_profile() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.laundry_washer_active_power",
                "sensor.laundry_washer_current",
                "sensor.laundry_washer_power_factor",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "appliance_profile") == "washer"
    assert "circuit_mode" not in _schema_keys(result["data_schema"])


@pytest.mark.asyncio
async def test_assignment_step_auto_suggests_microwave_profile() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.kitchen_microwave_active_power",
                "sensor.kitchen_microwave_current",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "appliance_profile") == "microwave"
    assert "circuit_mode" not in _schema_keys(result["data_schema"])


@pytest.mark.parametrize(
    ("entity_id", "expected_profile"),
    [
        ("sensor.channel_1_active_power", "refrigerator"),
        ("sensor.garage_freezer_active_power", "freezer"),
    ],
)
@pytest.mark.asyncio
async def test_assignment_step_uses_friendly_name_only_as_profile_fallback(
    entity_id: str,
    expected_profile: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()
    flow.hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                attributes={"friendly_name": "Kitchen Refrigerator Power"}
            )
        )
    )

    result = await flow.async_step_user({CONF_EXTRA_SOURCE_ENTITIES: [entity_id]})

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "appliance_profile") == (
        expected_profile
    )


@pytest.mark.asyncio
async def test_assignment_step_uses_clean_demo_circuit_names() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_washer_active_power",
                "sensor.cs_energy_analyzer_demo_washer_current",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "Washer"
    assert result["description_placeholders"]["circuit_name"] == "Washer"


def test_advanced_settings_schema_renders_optional_zero_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema(
        {},
        {
            "circuit_id": "refrigerator",
            "name": "Kitchen Refrigerator",
            "appliance_profile": ApplianceProfile.REFRIGERATOR.value,
            "mode": CircuitMode.SINGLE_PHASE.value,
            "power_flow": "load",
        },
    )

    assert "selected_appliance" not in _schema_keys(schema)
    assert _schema_default(schema, "operating_on_threshold_w") == 25.0
    assert _schema_default(schema, "operating_off_threshold_w") == 10.0
    assert _schema_default(schema, "operating_on_dwell_seconds") == 10.0
    assert _schema_default(schema, "operating_off_dwell_seconds") == 45.0
    assert _schema_default(schema, "operating_merge_gap_seconds") == 90.0
    assert _schema_default(schema, "daily_goal_kwh") == 0.0
    assert _schema_default(schema, "max_active_minutes") == 0
    assert _schema_default(schema, "max_idle_minutes") == 0
    assert _schema_default(schema, "budget_kwh") == 0.0
    assert "default_rate_per_kwh" not in _schema_keys(schema)
    assert "tou_rate_per_kwh" not in _schema_keys(schema)
    assert "tou_start" not in _schema_keys(schema)
    assert "tou_end" not in _schema_keys(schema)
    assert "tou_weekdays" not in _schema_keys(schema)
    assert "tou_name" not in _schema_keys(schema)
    assert _schema_default(schema, "demand_limit_w") == 0.0
    assert _schema_default(schema, "breaker_amps") == 0.0
    assert _schema_default(schema, "always_on_alert_w") == 0.0
    assert _schema_default(schema, "billing_min_elapsed_days") == 3
    assert _schema_default(schema, "standby_min_samples") == 24
    assert _schema_section_keys(schema) == {
        "analysis_settings",
        "operating_detection_settings",
        "energy_settings",
        "activity_settings",
        "billing_cost_settings",
        "demand_capacity_settings",
        "standby_settings",
        "power_quality_settings",
    }
    assert "leg_imbalance_warning_ratio" not in _schema_keys(schema)
    assert "balance_negative_tolerance_w" not in _schema_keys(schema)
    assert "solar_export_tolerance_w" not in _schema_keys(schema)


@pytest.mark.asyncio
async def test_advanced_settings_form_shows_operating_detection_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "appliance_profile": "refrigerator",
                    "mode": "single_phase",
                    "power_flow": "load",
                    "sensors": [],
                }
            ]
        },
        options={
            CONF_ADVANCED_SETTINGS: {
                "fridge": {
                    "operating_on_threshold_w": 30.0,
                    "operating_off_threshold_w": 12.0,
                }
            }
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow._advanced_circuit_id = "fridge"

    result = await flow.async_step_advanced_settings()

    assert result["description_placeholders"]["operating_detection_source"] == (
        "User override"
    )


@pytest.mark.asyncio
async def test_advanced_settings_form_shows_learned_operating_detection_source(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "appliance_profile": "refrigerator",
                    "mode": "single_phase",
                    "power_flow": "load",
                    "sensors": [],
                }
            ]
        },
        options={
            CONF_ADVANCED_SETTINGS: {
                "fridge": {
                    "operating_on_threshold_w": 30.0,
                    "operating_off_threshold_w": 12.0,
                    "operating_detection_source": "learned_recommendation",
                }
            }
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow._advanced_circuit_id = "fridge"

    result = await flow.async_step_advanced_settings()

    assert result["description_placeholders"]["operating_detection_source"] == (
        "Suggested from learned behavior"
    )


def test_advanced_settings_schema_exposes_section_reset_controls() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schemas = [
        _advanced_settings_schema(
            {},
            {
                "circuit_id": "refrigerator",
                "name": "Kitchen Refrigerator",
                "appliance_profile": ApplianceProfile.REFRIGERATOR.value,
                "mode": CircuitMode.SINGLE_PHASE.value,
                "power_flow": "load",
            },
        ),
        _advanced_settings_schema(
            {},
            {
                "circuit_id": "well_pump",
                "name": "Well Pump",
                "appliance_profile": ApplianceProfile.WELL_PUMP.value,
                "mode": CircuitMode.DUAL_PHASE.value,
                "power_flow": "load",
            },
        ),
        _advanced_settings_schema(
            {},
            {
                "circuit_id": "mains",
                "name": "Mains",
                "appliance_profile": ApplianceProfile.MAINS_NILM.value,
                "mode": CircuitMode.MAINS_NILM.value,
                "power_flow": "mains_net",
            },
        ),
    ]

    reset_fields = (
        "reset_operating_detection_settings_to_defaults",
        "reset_energy_settings_to_defaults",
        "reset_activity_settings_to_defaults",
        "reset_billing_cost_settings_to_defaults",
        "reset_demand_capacity_settings_to_defaults",
        "reset_standby_settings_to_defaults",
        "reset_water_context_settings_to_defaults",
        "reset_dual_phase_settings_to_defaults",
        "reset_power_quality_settings_to_defaults",
        "reset_mains_balance_settings_to_defaults",
        "reset_solar_flow_settings_to_defaults",
    )
    defaults = {}
    for schema in schemas:
        for field_name in reset_fields:
            try:
                defaults[field_name] = _schema_default(schema, field_name)
            except AssertionError:
                continue

    assert set(defaults) == set(reset_fields)
    assert all(default is False for default in defaults.values())
    for schema in schemas:
        assert _schema_top_level_keys(schema)[0] == (
            "reset_advanced_settings_to_defaults"
        )
        assert _schema_default(schema, "reset_advanced_settings_to_defaults") is False
        assert "reset_analysis_settings_to_defaults" not in _schema_keys(schema)


def test_advanced_settings_schema_excludes_global_tou_controls() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    schema = config_flow._advanced_settings_schema(
        {"tou_start": "16:00", "tou_end": "21:00", "tou_weekdays": "0,2,4"},
        {
            "circuit_id": "mains",
            "name": "Mains",
            "appliance_profile": config_flow.ApplianceProfile.MAINS_NILM.value,
            "mode": config_flow.CircuitMode.MAINS_NILM.value,
            "power_flow": "mains_net",
        },
    )

    assert not {
        "default_rate_per_kwh",
        "tou_rate_per_kwh",
        "tou_start",
        "tou_end",
        "tou_weekdays",
        "tou_name",
    } & _schema_keys(schema)


def test_advanced_settings_schema_shows_water_context_for_water_appliances() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema(
        {
            "linked_flow_sensor_entities": ["binary_sensor.water_flow"],
            "flow_mismatch_threshold_minutes": 8,
        },
        {
            "circuit_id": "sump_pump",
            "name": "Sump Pump",
            "appliance_profile": ApplianceProfile.SUMP_PUMP.value,
            "mode": CircuitMode.SINGLE_PHASE.value,
            "power_flow": "load",
        },
    )

    assert "water_context_settings" in _schema_section_keys(schema)
    assert _schema_default(schema, "rain_response_window_minutes") == 120
    assert _schema_default(schema, "rain_activity_delta_threshold_pct") == 25.0
    assert "water_flow_correlation_enabled" not in _schema_keys(schema)

    washer_schema = _advanced_settings_schema(
        {"linked_flow_sensor_entities": ["binary_sensor.water_flow"]},
        {
            "circuit_id": "washer",
            "name": "Washer",
            "appliance_profile": ApplianceProfile.WASHER.value,
            "mode": CircuitMode.SINGLE_PHASE.value,
            "power_flow": "load",
        },
    )

    assert "water_context_settings" in _schema_section_keys(washer_schema)
    assert _schema_default(washer_schema, "expects_water_flow") is True
    assert _schema_default(washer_schema, "linked_flow_sensor_entities") == [
        "binary_sensor.water_flow"
    ]


def test_advanced_settings_schema_exposes_power_quality_balance_and_solar_controls(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema(
        {
            "leg_imbalance_warning_ratio": 0.4,
            "leg_imbalance_min_total_power_w": 800.0,
            "apparent_power_tolerance_percent": 12.0,
            "power_factor_tolerance": 0.08,
            "minimum_apparent_power_va": 120.0,
            "balance_negative_tolerance_w": 250.0,
            "solar_export_tolerance_w": 150.0,
            "solar_surplus_threshold_w": 750.0,
            "high_solar_surplus_threshold_w": 2000.0,
            "flexible_load_running_threshold_w": 175.0,
        },
        {
            "circuit_id": "mains",
            "name": "Mains NILM",
            "appliance_profile": ApplianceProfile.MAINS_NILM.value,
            "mode": CircuitMode.MAINS_NILM.value,
            "power_flow": "mains_net",
        },
    )

    assert "dual_phase_settings" not in _schema_section_keys(schema)
    assert _schema_default(schema, "apparent_power_tolerance_percent") == 12.0
    assert _schema_default(schema, "power_factor_tolerance") == 0.08
    assert _schema_default(schema, "minimum_apparent_power_va") == 120.0
    assert _schema_default(schema, "balance_negative_tolerance_w") == 250.0
    assert _schema_default(schema, "solar_export_tolerance_w") == 150.0
    assert _schema_default(schema, "solar_surplus_threshold_w") == 750.0
    assert _schema_default(schema, "high_solar_surplus_threshold_w") == 2000.0
    assert _schema_default(schema, "flexible_load_running_threshold_w") == 175.0


def test_advanced_settings_schema_shows_dual_phase_controls_only_for_dual_phase(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema(
        {
            "leg_imbalance_warning_ratio": 0.4,
            "leg_imbalance_min_total_power_w": 800.0,
        },
        {
            "circuit_id": "hvac",
            "name": "Downstairs HVAC",
            "appliance_profile": ApplianceProfile.HVAC.value,
            "mode": CircuitMode.DUAL_PHASE.value,
            "power_flow": "load",
        },
    )

    assert "dual_phase_settings" in _schema_section_keys(schema)
    assert _schema_default(schema, "leg_imbalance_warning_ratio") == 0.4
    assert _schema_default(schema, "leg_imbalance_min_total_power_w") == 800.0
    assert "mains_balance_settings" not in _schema_section_keys(schema)
    assert "solar_flow_settings" not in _schema_section_keys(schema)


def test_advanced_settings_schema_hides_appliance_controls_for_mixed_circuits(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema(
        {},
        {
            "circuit_id": "kitchen_plugs",
            "name": "Kitchen Plugs",
            "appliance_profile": ApplianceProfile.MIXED.value,
            "mode": CircuitMode.MIXED.value,
            "power_flow": "load",
        },
    )

    assert _schema_section_keys(schema) == {
        "analysis_settings",
        "operating_detection_settings",
        "energy_settings",
        "billing_cost_settings",
        "demand_capacity_settings",
        "power_quality_settings",
    }
    assert _schema_default(schema, "operating_on_threshold_w") == 80.0
    assert "max_active_minutes" not in _schema_keys(schema)
    assert "standby_threshold_w" not in _schema_keys(schema)


def test_advanced_settings_from_sectioned_input_saves_flat_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _advanced_settings_from_input,
    )

    settings = _advanced_settings_from_input(
        {
            "analysis_settings": {"preset": "sensitive"},
            "energy_settings": {
                "window_days": 14,
                "daily_spike_ratio": 0.35,
                "daily_goal_kwh": 2.5,
                "goal_alert_ratio": 0.9,
            },
            "activity_settings": {
                "max_active_minutes": 120,
                "max_idle_minutes": 480,
            },
            "billing_cost_settings": {
                "cycle_start_day": 15,
                "budget_kwh": 90.0,
                "budget_alert_ratio": 0.85,
                "billing_min_elapsed_days": 5,
            },
            "demand_capacity_settings": {
                "window_minutes": 30,
                "demand_limit_w": 1200.0,
                "breaker_amps": 20.0,
                "warning_ratio": 0.8,
            },
            "standby_settings": {
                "window_hours": 72,
                "standby_threshold_w": 6.0,
                "always_on_alert_w": 12.0,
                "standby_min_samples": 36,
            },
        }
    )

    assert settings == {
        "preset": "sensitive",
        "window_days": 14,
        "daily_spike_ratio": 0.35,
        "daily_goal_kwh": 2.5,
        "goal_alert_ratio": 0.9,
        "max_active_minutes": 120,
        "max_idle_minutes": 480,
        "cycle_start_day": 15,
        "budget_kwh": 90.0,
        "budget_alert_ratio": 0.85,
        "min_elapsed_days": 5,
        "window_minutes": 30,
        "demand_limit_w": 1200.0,
        "breaker_amps": 20.0,
        "warning_ratio": 0.8,
        "window_hours": 72,
        "standby_threshold_w": 6.0,
        "always_on_alert_w": 12.0,
        "min_samples": 36,
    }


def test_advanced_settings_from_input_resets_selected_sections_to_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _advanced_settings_from_input,
    )

    settings = _advanced_settings_from_input(
        {
            "analysis_settings": {
                "preset": "sensitive",
            },
            "operating_detection_settings": {
                "operating_on_threshold_w": 30.0,
                "operating_off_threshold_w": 12.0,
                "reset_operating_detection_settings_to_defaults": True,
            },
            "energy_settings": {
                "window_days": 14,
                "daily_spike_ratio": 0.35,
                "daily_goal_kwh": 2.5,
                "goal_alert_ratio": 0.9,
                "reset_energy_settings_to_defaults": True,
            },
            "billing_cost_settings": {
                "cycle_start_day": 15,
                "budget_kwh": 90.0,
                "budget_alert_ratio": 0.85,
                "billing_min_elapsed_days": 5,
            },
            "standby_settings": {
                "window_hours": 72,
                "standby_threshold_w": 6.0,
                "always_on_alert_w": 12.0,
                "standby_min_samples": 36,
                "reset_standby_settings_to_defaults": True,
            },
        }
    )

    assert settings == {
        "preset": "sensitive",
        "cycle_start_day": 15,
        "budget_kwh": 90.0,
        "budget_alert_ratio": 0.85,
        "min_elapsed_days": 5,
    }


def test_advanced_settings_from_input_only_persists_non_default_operating_overrides(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        _advanced_settings_from_input,
    )

    settings = _advanced_settings_from_input(
        {
            "analysis_settings": {"preset": "balanced"},
            "operating_detection_settings": {
                "operating_on_threshold_w": 25.0,
                "operating_off_threshold_w": 12.0,
                "operating_on_dwell_seconds": 10.0,
                "operating_off_dwell_seconds": 45.0,
                "operating_merge_gap_seconds": 90.0,
            },
        },
        context={
            "circuit_id": "refrigerator",
            "name": "Kitchen Refrigerator",
            "appliance_profile": ApplianceProfile.REFRIGERATOR.value,
            "mode": CircuitMode.SINGLE_PHASE.value,
            "power_flow": "load",
        },
    )

    assert settings == {
        "preset": "balanced",
        "operating_off_threshold_w": 12.0,
    }


def test_advanced_settings_from_input_rejects_invalid_operating_overrides() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        ApplianceProfile,
        CircuitMode,
        SetupValidationError,
        _advanced_settings_from_input,
    )

    with pytest.raises(SetupValidationError, match="invalid_advanced_settings") as err:
        _advanced_settings_from_input(
            {
                "operating_detection_settings": {
                    "operating_on_threshold_w": 10.0,
                    "operating_off_threshold_w": 12.0,
                }
            },
            context={
                "circuit_id": "refrigerator",
                "name": "Kitchen Refrigerator",
                "appliance_profile": ApplianceProfile.REFRIGERATOR.value,
                "mode": CircuitMode.SINGLE_PHASE.value,
                "power_flow": "load",
            },
        )

    assert err.value.error_key == "invalid_advanced_settings"


def test_advanced_settings_from_input_resets_all_settings_to_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _advanced_settings_from_input,
    )

    settings = _advanced_settings_from_input(
        {
            "analysis_settings": {
                "reset_advanced_settings_to_defaults": True,
                "preset": "sensitive",
            },
            "energy_settings": {
                "daily_spike_ratio": 0.35,
            },
            "standby_settings": {
                "standby_threshold_w": 6.0,
            },
        }
    )

    assert settings == {}


def test_advanced_settings_from_input_resets_remaining_feature_sections() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _advanced_settings_from_input,
    )

    settings = _advanced_settings_from_input(
        {
            "analysis_settings": {
                "preset": "sensitive",
            },
            "water_context_settings": {
                "rain_pump_correlation_enabled": True,
                "rain_response_window_minutes": 180,
                "rain_activity_delta_threshold_pct": 40.0,
                "water_flow_correlation_enabled": True,
                "linked_flow_sensor_entities": ["binary_sensor.water_flow"],
                "expects_water_flow": True,
                "flow_mismatch_threshold_minutes": 9,
                "reset_water_context_settings_to_defaults": True,
            },
            "dual_phase_settings": {
                "leg_imbalance_warning_ratio": 0.4,
                "leg_imbalance_min_total_power_w": 800.0,
                "reset_dual_phase_settings_to_defaults": True,
            },
            "power_quality_settings": {
                "apparent_power_tolerance_percent": 12.0,
                "power_factor_tolerance": 0.08,
                "minimum_apparent_power_va": 120.0,
            },
            "mains_balance_settings": {
                "balance_negative_tolerance_w": 250.0,
                "reset_mains_balance_settings_to_defaults": True,
            },
            "solar_flow_settings": {
                "solar_export_tolerance_w": 150.0,
                "solar_surplus_threshold_w": 750.0,
                "high_solar_surplus_threshold_w": 2000.0,
                "flexible_load_running_threshold_w": 175.0,
                "reset_solar_flow_settings_to_defaults": True,
            },
        }
    )

    assert settings == {
        "preset": "sensitive",
        "apparent_power_tolerance_percent": 12.0,
        "power_factor_tolerance": 0.08,
        "minimum_apparent_power_va": 120.0,
    }
@pytest.mark.asyncio
async def test_options_assignment_edit_preserves_existing_circuit_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
                "sensor.cs_energy_analyzer_demo_hvac_l2_active_power",
            ],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "cs_energy_analyzer_demo_hvac",
                    "name": "HVAC",
                    "appliance_profile": "hvac",
                    "mode": "dual_phase",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power"
                            ),
                            "role": "real_power",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_active_power"
                            ),
                            "role": "real_power",
                        },
                    ],
                }
            ],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_assign()

    assert result["type"] == "form"
    assert result["step_id"] == "select_assignment"

    result = await flow.async_step_select_assignment(
        {"selected_assignment": "cs_energy_analyzer_demo_hvac"}
    )

    assert result["type"] == "form"
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Upstairs HVAC",
            "appliance_profile": "hvac",
            "included_sensors": [
                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
                "sensor.cs_energy_analyzer_demo_hvac_l2_active_power",
            ],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CIRCUITS][0]["circuit_id"] == (
        "cs_energy_analyzer_demo_hvac"
    )
    assert result["data"][CONF_CIRCUITS][0]["name"] == "Upstairs HVAC"


@pytest.mark.asyncio
async def test_assignment_step_allows_sensor_level_inclusion() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()

    result = await flow.async_step_user(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.refrigerator_active_power",
                "sensor.refrigerator_current",
                "sensor.refrigerator_power_factor",
            ],
        }
    )

    assert result["type"] == "form"
    assert "included_sensors" in _schema_keys(result["data_schema"])
    assert _schema_default(result["data_schema"], "included_sensors") == [
        "sensor.refrigerator_active_power",
        "sensor.refrigerator_current",
        "sensor.refrigerator_power_factor",
    ]

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Refrigerator",
            "appliance_profile": "refrigerator",
            "included_sensors": [
                "sensor.refrigerator_active_power",
                "sensor.refrigerator_power_factor",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.refrigerator_active_power",
        "sensor.refrigerator_power_factor",
    ]
    assert [
        sensor["entity_id"] for sensor in result["data"][CONF_CIRCUITS][0]["sensors"]
    ] == [
        "sensor.refrigerator_active_power",
        "sensor.refrigerator_power_factor",
    ]


@pytest.mark.asyncio
async def test_options_flow_does_not_emit_non_actionable_mapping_suggestions() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    _assert_no_description_placeholders(result)


def test_flow_schemas_serialize_for_home_assistant_frontend() -> None:
    import voluptuous_serialize

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        DATA_SCHEMA,
        _advanced_settings_schema,
        _entity_detail_schema,
        _options_schema,
        _time_selector,
    )

    def serialize_ha_selector(schema):
        serializer = getattr(schema, "serialize", None)
        if callable(serializer):
            return serializer()
        return voluptuous_serialize.UNSUPPORTED

    assert voluptuous_serialize.convert(
        DATA_SCHEMA,
        custom_serializer=serialize_ha_selector,
    )
    assert voluptuous_serialize.convert(
        _options_schema(SimpleNamespace(data={}, options={})),
        custom_serializer=serialize_ha_selector,
    )
    assert voluptuous_serialize.convert(
        _entity_detail_schema(SimpleNamespace(data={}, options={})),
        custom_serializer=serialize_ha_selector,
    )
    assert _time_selector().serialize() == {"selector": {"time": {}}}

    try:
        from homeassistant.helpers import config_validation as cv
    except ModuleNotFoundError:
        return

    assert voluptuous_serialize.convert(
        _advanced_settings_schema({}),
        custom_serializer=cv.custom_serializer,
    )


def test_select_options_use_friendly_labels_for_home_assistant(monkeypatch) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)

    setup_schema = config_flow._setup_schema()
    assignment_schema = config_flow._assignment_schema(
        {
            "entity_ids": ("sensor.fridge_active_power",),
            "appliance_profile": "refrigerator",
            "mode": "single_phase",
        }
    )
    advanced_schema = config_flow._advanced_settings_schema({})

    assert _schema_validator(setup_schema, CONF_SENSITIVITY) == {
        "select": {
            "options": [
                {"value": "quiet", "label": "Quiet"},
                {"value": "balanced", "label": "Balanced"},
                {"value": "sensitive", "label": "Sensitive"},
            ]
        }
    }
    retention_options = [
        {"value": "standard", "label": "Standard"},
        {"value": "lightweight", "label": "Lightweight"},
        {"value": "diagnostic", "label": "Diagnostic"},
    ]
    assert _schema_validator(setup_schema, CONF_RETENTION_MODE) == {
        "select": {"options": retention_options}
    }
    assert _schema_validator(
        assignment_schema,
        "circuit_retention_mode",
    ) == {"select": {"options": retention_options}}
    assert _schema_validator(advanced_schema, "preset") == {
        "select": {
            "options": [
                {"value": "quiet", "label": "Quiet"},
                {"value": "balanced", "label": "Balanced"},
                {"value": "sensitive", "label": "Sensitive"},
            ]
        }
    }
    entity_detail_schema = config_flow._entity_detail_schema(
        SimpleNamespace(data={}, options={})
    )
    assert _schema_validator(entity_detail_schema, CONF_ENTITY_DETAIL_LEVEL) == {
        "select": {
            "options": [
                {"value": ENTITY_DETAIL_SIMPLE, "label": "Simple"},
                {"value": ENTITY_DETAIL_STANDARD, "label": "Standard"},
                {"value": ENTITY_DETAIL_EXPERT, "label": "Expert"},
            ]
        }
    }
    group_options = _schema_validator(
        entity_detail_schema,
        CONF_SELECTED_ENTITY_GROUPS,
    )["select"]["options"]
    assert {"value": "cycle_metrics", "label": "Cycle Metrics"} in group_options
    assert {
        "value": "power_quality_drift",
        "label": "Power Quality Drift",
    } in group_options
    assert (
        _schema_default(entity_detail_schema, CONF_ENTITY_DETAIL_LEVEL)
        == DEFAULT_ENTITY_DETAIL_LEVEL
    )

    appliance_options = _schema_validator(
        assignment_schema,
        "appliance_profile",
    )["select"]["options"]
    assert {"value": "hvac", "label": "HVAC"} in appliance_options
    assert {"value": "hvac_compressor", "label": "HVAC Compressor"} in (
        appliance_options
    )
    assert {"value": "hvac_blower", "label": "HVAC Blower"} in appliance_options
    assert {"value": "microwave", "label": "Microwave"} in appliance_options
    assert {"value": "washer", "label": "Washer"} in appliance_options
    assert {"value": "dryer", "label": "Dryer"} in appliance_options
    assert {"value": "ev_charger", "label": "EV Charger"} in appliance_options
    assert all("_" not in option["label"] for option in appliance_options)


def test_setup_schema_filters_energy_sources_and_removes_manual_fields() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    selector_config = config_flow._energy_entity_selector_config()

    assert selector_config == {
        "entity": {
            "multiple": True,
            "filter": [
                {
                    "domain": "sensor",
                    "device_class": sorted(
                        {
                            "apparent_power",
                            "current",
                            "energy",
                            "frequency",
                            "power",
                            "power_factor",
                            "reactive_energy",
                            "reactive_power",
                            "voltage",
                        }
                    ),
                }
            ],
        }
    }
    assert config_flow._energy_entity_selector_config(
        ["sensor.panel_power", "sensor.panel_voltage"]
    ) == {
        "entity": {
            "multiple": True,
            "filter": [
                {
                    "domain": "sensor",
                    "device_class": sorted(
                        {
                            "apparent_power",
                            "current",
                            "energy",
                            "frequency",
                            "power",
                            "power_factor",
                            "reactive_energy",
                            "reactive_power",
                            "voltage",
                        }
                    ),
                }
            ],
            "include_entities": ["sensor.panel_power", "sensor.panel_voltage"],
        }
    }
    assert config_flow._source_device_selector_config() == {
        "device": {
            "multiple": True,
            "filter": [{"integration": "esphome"}],
            "entity": [
                {
                    "domain": "sensor",
                    "device_class": sorted(
                        {
                            "apparent_power",
                            "current",
                            "energy",
                            "frequency",
                            "power",
                            "power_factor",
                            "reactive_energy",
                            "reactive_power",
                            "voltage",
                        }
                    ),
                }
            ],
        }
    }
    assert "circuits" not in _schema_keys(config_flow.DATA_SCHEMA)
    assert CONF_SOURCE_DEVICES in _schema_keys(config_flow.DATA_SCHEMA)
    assert CONF_EXTRA_SOURCE_ENTITIES in _schema_keys(config_flow.DATA_SCHEMA)
    assert CONF_SOURCE_ENTITIES not in _schema_keys(config_flow.DATA_SCHEMA)
    assert CONF_EXTRA_SOURCE_ENTITIES in _schema_keys(
        config_flow._options_schema(SimpleNamespace(data={}, options={}))
    )
    assert CONF_SOURCE_ENTITIES not in _schema_keys(
        config_flow._options_schema(SimpleNamespace(data={}, options={}))
    )
    assert "known_load_circuits" not in _schema_keys(config_flow.DATA_SCHEMA)
    assert "known_load_circuits" not in _schema_keys(
        config_flow._options_schema(SimpleNamespace(data={}, options={}))
    )


def test_options_schema_allows_demo_dual_phase_entities_before_they_exist() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        _energy_entity_selector_config,
        _selectable_source_entity_ids,
    )

    include_entities = _energy_entity_selector_config(
        _selectable_source_entity_ids(None)
    )["entity"]["include_entities"]

    assert "sensor.cs_energy_analyzer_demo_hvac_l1_active_power" in include_entities
    assert "sensor.cs_energy_analyzer_demo_hvac_l2_active_power" in include_entities
    assert (
        "sensor.cs_energy_analyzer_demo_water_heater_l1_active_power"
        in include_entities
    )
    assert "sensor.cs_energy_analyzer_demo_hvac_voltage" not in include_entities
    assert "sensor.cs_energy_analyzer_demo_mains_l1_voltage" in include_entities
    assert "sensor.cs_energy_analyzer_demo_mains_l2_voltage" in include_entities
    assert (
        "sensor.cs_energy_analyzer_demo_car_charger_l1_active_power"
        in include_entities
    )
    assert (
        "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power"
        in include_entities
    )
    assert (
        "sensor.cs_energy_analyzer_demo_hvac_l1_apparent_power"
        in include_entities
    )
    assert "sensor.cs_energy_analyzer_demo_washer_active_power" in include_entities
    assert "sensor.cs_energy_analyzer_demo_dryer_l1_active_power" in include_entities
    assert "sensor.cs_energy_analyzer_demo_dryer_l2_active_power" in include_entities
    assert (
        "sensor.cs_energy_analyzer_demo_car_charger_voltage"
        not in include_entities
    )
def test_options_schema_uses_discovered_suffixed_demo_entity_ids(
    monkeypatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    monkeypatch.setattr(config_flow, "ha_selector", lambda config: config)

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
            ],
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_mains_l1_energy",
            ],
        },
    )
    discovered_entities = [
        "sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
        "sensor.cs_energy_analyzer_demo_hvac_l1_active_power_2",
        "sensor.cs_energy_analyzer_demo_mains_l1_energy",
    ]

    source_schema = config_flow._options_schema(entry, discovered_entities)
    mains_schema = config_flow._mains_schema(entry, discovered_entities)

    assert _schema_default(source_schema, CONF_EXTRA_SOURCE_ENTITIES) == [
        "sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
        "sensor.cs_energy_analyzer_demo_hvac_l1_active_power_2",
    ]
    assert _schema_default(mains_schema, CONF_MAINS_SOURCE_ENTITIES) == [
        "sensor.cs_energy_analyzer_demo_mains_l1_energy"
    ]


def test_options_source_entities_override_setup_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        _source_entities_for_entry,
    )

    entry = SimpleNamespace(
        data={CONF_SOURCE_ENTITIES: ["sensor.setup_energy"]},
        options={CONF_SOURCE_ENTITIES: ["sensor.option_power"]},
    )
    coordinator = SimpleNamespace(circuit_configs=())

    assert _source_entities_for_entry(entry, coordinator) == ("sensor.option_power",)


def test_source_entities_for_entry_listens_to_mains_voltage_without_nilm() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        _source_entities_for_entry,
    )

    entry = SimpleNamespace(
        data={
            CONF_SOURCE_ENTITIES: ["sensor.pump_power"],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.setup_voltage"],
        },
        options={CONF_MAINS_SOURCE_ENTITIES: ["sensor.option_voltage"]},
    )
    coordinator = SimpleNamespace(circuit_configs=())

    assert _source_entities_for_entry(entry, coordinator) == (
        "sensor.pump_power",
        "sensor.option_voltage",
    )


def test_source_entities_for_entry_includes_linked_flow_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        _source_entities_for_entry,
    )

    entry = SimpleNamespace(
        data={
            CONF_ADVANCED_SETTINGS: {
                "washer": {
                    CONF_LINKED_FLOW_SENSOR_ENTITIES: [
                        "binary_sensor.washer_flow"
                    ]
                }
            }
        },
        options={},
    )
    coordinator = SimpleNamespace(circuit_configs=())

    assert _source_entities_for_entry(entry, coordinator) == (
        "binary_sensor.washer_flow",
    )


def test_source_entities_for_entry_uses_registered_demo_entity_ids() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        _source_entities_for_entry,
    )

    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
            ],
        },
    )
    registry = SimpleNamespace(
        entities={
            "sensor.cs_energy_analyzer_demo_refrigerator_energy_2": SimpleNamespace(
                entity_id="sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
                unique_id=(
                    "entry-1_demo_source_exact_"
                    "cs_energy_analyzer_demo_refrigerator_energy"
                ),
                config_entry_id="entry-1",
                platform=DOMAIN,
            ),
            "sensor.cs_energy_analyzer_demo_hvac_l1_active_power": SimpleNamespace(
                entity_id="sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
                unique_id=(
                    "entry-1_demo_source_exact_"
                    "cs_energy_analyzer_demo_hvac_l1_active_power"
                ),
                config_entry_id="entry-1",
                platform=DOMAIN,
            ),
        }
    )
    coordinator = SimpleNamespace(
        circuit_configs=(),
        hass=SimpleNamespace(entity_registry=registry),
    )

    assert _source_entities_for_entry(entry, coordinator) == (
        "sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
        "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
    )


def test_source_entities_for_entry_falls_back_when_ha_registry_get_fails(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import (
        _source_entities_for_entry,
    )

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")

    def async_get(_hass):
        raise TypeError("unhashable type")

    entity_registry_module.async_get = async_get
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    entry = SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
            ],
        },
    )
    registry = SimpleNamespace(
        entities={
            "sensor.cs_energy_analyzer_demo_refrigerator_energy_2": SimpleNamespace(
                entity_id="sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
                unique_id=(
                    "entry-1_demo_source_exact_"
                    "cs_energy_analyzer_demo_refrigerator_energy"
                ),
                config_entry_id="entry-1",
                platform=DOMAIN,
            ),
        }
    )
    coordinator = SimpleNamespace(
        circuit_configs=(),
        hass=SimpleNamespace(entity_registry=registry),
    )

    assert _source_entities_for_entry(entry, coordinator) == (
        "sensor.cs_energy_analyzer_demo_refrigerator_energy_2",
    )


def test_config_flow_imports_and_strings_load_without_home_assistant() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    manifest_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "circuitsetup_energy_analyzer"
        / "manifest.json"
    )
    translations_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "circuitsetup_energy_analyzer"
        / "translations"
        / "en.json"
    )

    assert config_flow.CircuitSetupEnergyAnalyzerConfigFlow.VERSION == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["integration_type"] == "hub"
    assert "recorder" in manifest["after_dependencies"]
    assert "esphome" not in manifest["after_dependencies"]
    assert {"frontend", "http", "panel_custom"} <= set(manifest["dependencies"])
    assert (
        manifest["documentation"]
        == "https://github.com/CircuitSetup/CircuitSetup-Energy-Analyzer"
    )
    assert (
        manifest["issue_tracker"]
        == "https://github.com/CircuitSetup/CircuitSetup-Energy-Analyzer/issues"
    )
    assert json.loads(translations_path.read_text(encoding="utf-8"))["title"] == (
        "CircuitSetup Energy Analyzer"
    )
