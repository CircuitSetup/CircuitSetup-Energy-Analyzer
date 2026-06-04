from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
)
from custom_components.circuitsetup_energy_analyzer.discovery import DiscoveredSensor
from custom_components.circuitsetup_energy_analyzer.mapping import DualPhaseSuggestion
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


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
    for marker in schema.schema:
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        keys.add(key)
    return keys


def _schema_default(schema, field_name: str):
    for marker in schema.schema:
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        if key != field_name:
            continue
        default = getattr(marker, "default", None)
        return default() if callable(default) else default
    raise AssertionError(f"{field_name} missing from schema")


def test_validate_setup_input_preserves_setup_fields_without_manual_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    payload = {
        CONF_SOURCE_DEVICES: ["meter-device"],
        CONF_EXTRA_SOURCE_ENTITIES: ["sensor.fridge_power", "sensor.main_l1_power"],
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power", "sensor.main_l2_power"],
        CONF_SENSITIVITY: "high",
        CONF_RETENTION_MODE: "diagnostic",
        "circuits": [{"circuit_id": "fridge"}],
        "known_load_circuits": ["fridge"],
    }

    validated = validate_setup_input(payload)

    assert validated[CONF_SOURCE_DEVICES] == payload[CONF_SOURCE_DEVICES]
    assert validated[CONF_EXTRA_SOURCE_ENTITIES] == payload[CONF_EXTRA_SOURCE_ENTITIES]
    assert validated[CONF_SOURCE_ENTITIES] == payload[CONF_EXTRA_SOURCE_ENTITIES]
    assert validated[CONF_ENABLE_EXPERIMENTAL_NILM] is True
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == payload[CONF_MAINS_SOURCE_ENTITIES]
    assert validated[CONF_SENSITIVITY] == "high"
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
async def test_options_flow_rejects_bogus_retention_mode() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))
    result = await flow.async_step_init({CONF_RETENTION_MODE: "forever"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_retention_mode"


@pytest.mark.asyncio
async def test_options_flow_rejects_malformed_mains_source_entities() -> None:
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))
    result = await flow.async_step_init(
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
        CONF_SENSITIVITY: "high",
        CONF_RETENTION_MODE: "diagnostic",
    }
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_init(user_input)

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_keys(result["data_schema"]) == {
        "include_circuit",
        "circuit_name",
        "appliance_profile",
        "circuit_mode",
    }
    assert result["description_placeholders"]["assignment_progress"] == "1 of 1"
    assert result["description_placeholders"]["current_sensors"] == (
        "sensor.fridge_power\nsensor.fridge_current"
    )


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
        "circuit_name",
        "appliance_profile",
        "circuit_mode",
    }
    assert _schema_default(result["data_schema"], "circuit_name") == (
        "Garage Vehicle Charging"
    )
    assert _schema_default(result["data_schema"], "appliance_profile") == "ev_charger"
    assert _schema_default(result["data_schema"], "circuit_mode") == "dual_phase"
    assert _schema_default(result["data_schema"], "include_circuit") is True
    assert result["description_placeholders"] == {
        "assignment_progress": "1 of 1",
        "circuit_name": "Garage Vehicle Charging",
        "appliance_profile": "ev_charger",
        "circuit_mode": "dual_phase",
        "current_sensors": "\n".join(
            [
                "sensor.garage_vehicle_charging_l1_active_power",
                "sensor.garage_vehicle_charging_l2_active_power",
                "sensor.garage_vehicle_charging_l1_current",
                "sensor.garage_vehicle_charging_l2_current",
            ]
        ),
    }


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
        CONF_SENSITIVITY: "standard",
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
            "circuit_mode": "single_phase",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert result["description_placeholders"]["assignment_progress"] == "2 of 2"
    assert _schema_default(result["data_schema"], "circuit_name") == "Sump Pump"
    assert _schema_default(result["data_schema"], "appliance_profile") == "sump_pump"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Sump Pump",
            "appliance_profile": "sump_pump",
            "circuit_mode": "single_phase",
        }
    )

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
    assert _schema_default(result["data_schema"], "circuit_mode") == "dual_phase"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Garage HVAC System",
            "appliance_profile": "hvac",
            "circuit_mode": "dual_phase",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"]["circuits"][0]["name"] == "Garage HVAC System"
    assert result["data"]["circuits"][0]["appliance_profile"] == "hvac"
    assert result["data"]["circuits"][0]["mode"] == "dual_phase"


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

    result = await flow.async_step_init(
        {
            CONF_EXTRA_SOURCE_ENTITIES: [
                "sensor.air_handler_active_power",
                "sensor.air_handler_current",
            ],
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC Blower"
    assert _schema_default(result["data_schema"], "appliance_profile") == "hvac_blower"
    assert _schema_default(result["data_schema"], "circuit_mode") == "single_phase"


@pytest.mark.asyncio
async def test_options_flow_does_not_emit_non_actionable_mapping_suggestions() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["description_placeholders"] == {}


def test_flow_schemas_serialize_for_home_assistant_frontend() -> None:
    import voluptuous_serialize

    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        DATA_SCHEMA,
        _options_schema,
    )

    assert voluptuous_serialize.convert(DATA_SCHEMA)
    assert voluptuous_serialize.convert(
        _options_schema(SimpleNamespace(data={}, options={}))
    )


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
        "sensor.cs_energy_analyzer_demo_car_charger_voltage"
        not in include_entities
    )


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


def test_config_flow_imports_and_strings_load_without_home_assistant() -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow

    manifest_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "circuitsetup_energy_analyzer"
        / "manifest.json"
    )
    strings_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "circuitsetup_energy_analyzer"
        / "strings.json"
    )

    assert config_flow.CircuitSetupEnergyAnalyzerConfigFlow.VERSION == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["integration_type"] == "hub"
    assert "recorder" in manifest["after_dependencies"]
    assert (
        manifest["documentation"]
        == "https://github.com/CircuitSetup/CircuitSetup-Energy-Analyzer"
    )
    assert (
        manifest["issue_tracker"]
        == "https://github.com/CircuitSetup/CircuitSetup-Energy-Analyzer/issues"
    )
    assert json.loads(strings_path.read_text(encoding="utf-8"))["title"] == (
        "CircuitSetup Energy Analyzer"
    )
