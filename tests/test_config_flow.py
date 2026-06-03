from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
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

    assert "manual definition" in text


def test_validate_setup_input_preserves_nilm_and_circuit_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    payload = {
        CONF_SOURCE_ENTITIES: ["sensor.fridge_power", "sensor.main_l1_power"],
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power", "sensor.main_l2_power"],
        CONF_KNOWN_LOAD_CIRCUITS: ["fridge"],
        CONF_SENSITIVITY: "high",
        CONF_RETENTION_MODE: "diagnostic",
        CONF_CIRCUITS: [
            {
                "circuit_id": "fridge",
                "name": "Fridge",
                "mode": "mixed",
                "appliance_profile": "mixed",
                "source_entities": ["sensor.fridge_power"],
            },
            {
                "id": "mains",
                "name": "Mains NILM",
                "mode": "mains_nilm",
                "appliance_profile": "mains_nilm",
                "source_entities": [
                    "sensor.main_l1_power",
                    "sensor.main_l2_power",
                ],
            },
        ],
    }

    validated = validate_setup_input(payload)

    assert validated[CONF_SOURCE_ENTITIES] == payload[CONF_SOURCE_ENTITIES]
    assert validated[CONF_ENABLE_EXPERIMENTAL_NILM] is True
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == payload[CONF_MAINS_SOURCE_ENTITIES]
    assert validated[CONF_KNOWN_LOAD_CIRCUITS] == ["fridge"]
    assert validated[CONF_SENSITIVITY] == "high"
    assert validated[CONF_RETENTION_MODE] == "diagnostic"
    assert validated[CONF_CIRCUITS] == payload[CONF_CIRCUITS]


def test_validate_setup_input_parses_text_area_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        validate_setup_input,
    )

    validated = validate_setup_input(
        {
            CONF_SOURCE_ENTITIES: "sensor.fridge_power\nsensor.hvac_power",
            CONF_MAINS_SOURCE_ENTITIES: "sensor.main_l1_power, sensor.main_l2_power",
            CONF_KNOWN_LOAD_CIRCUITS: "fridge\nhvac",
            CONF_CIRCUITS: json.dumps(
                [
                    {
                        "circuit_id": "fridge",
                        "name": "Fridge",
                        "mode": "single_phase",
                    }
                ]
            ),
        }
    )

    assert validated[CONF_SOURCE_ENTITIES] == [
        "sensor.fridge_power",
        "sensor.hvac_power",
    ]
    assert validated[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]
    assert validated[CONF_KNOWN_LOAD_CIRCUITS] == ["fridge", "hvac"]
    assert validated[CONF_CIRCUITS] == [
        {"circuit_id": "fridge", "name": "Fridge", "mode": "single_phase"}
    ]


def test_validate_setup_input_rejects_invalid_circuit_json() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input(
            {
                CONF_SOURCE_ENTITIES: "sensor.fridge_power",
                CONF_CIRCUITS: "{not json",
            }
        )

    assert error.value.error_key == "invalid_circuits"


def test_validate_setup_input_requires_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input({CONF_SOURCE_ENTITIES: [], CONF_CIRCUITS: []})

    assert error.value.error_key == "no_source_entities"


def test_validate_setup_input_rejects_non_mapping_circuit_items() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input(
            {
                CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
                CONF_CIRCUITS: ["not-a-dict"],
            }
        )

    assert error.value.error_key == "invalid_circuits"


def test_validate_setup_input_rejects_source_entity_mapping() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        SetupValidationError,
        validate_setup_input,
    )

    with pytest.raises(SetupValidationError) as error:
        validate_setup_input(
            {
                CONF_SOURCE_ENTITIES: {"sensor.fridge_power": True},
                CONF_CIRCUITS: [],
            }
        )

    assert error.value.error_key == "invalid_source_entities"


@pytest.mark.asyncio
async def test_fallback_user_flow_returns_no_source_entities_form_error() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerConfigFlow,
    )

    flow = CircuitSetupEnergyAnalyzerConfigFlow()
    result = await flow.async_step_user({CONF_SOURCE_ENTITIES: [], CONF_CIRCUITS: []})

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
        CONF_ENABLE_EXPERIMENTAL_NILM: True,
        CONF_MAINS_SOURCE_ENTITIES: ["sensor.main_l1_power", "sensor.main_l2_power"],
        CONF_KNOWN_LOAD_CIRCUITS: ["fridge"],
        CONF_SENSITIVITY: "high",
        CONF_RETENTION_MODE: "diagnostic",
    }
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_init(user_input)

    assert result["type"] == "create_entry"
    assert result["data"] == user_input


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
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["integration_type"]
        == "hub"
    )
    assert json.loads(strings_path.read_text(encoding="utf-8"))["title"] == (
        "CircuitSetup Energy Analyzer"
    )
