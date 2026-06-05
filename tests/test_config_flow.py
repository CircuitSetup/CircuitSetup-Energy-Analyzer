from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
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


def _schema_validator(schema, field_name: str):
    for marker, validator in schema.schema.items():
        key = getattr(marker, "schema", getattr(marker, "key", marker))
        if key == field_name:
            return validator
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
        "assign",
        "sources",
        "mains",
        "nilm",
        "utility",
        "advanced",
    ]
    assert result["description_placeholders"] == {}


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
        {CONF_MAINS_SOURCE_ENTITIES: ["sensor.new_mains_l1_energy"]}
    )

    assert result == {
        "type": "create_entry",
        "title": "",
        "data": {
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.new_mains_l1_energy"],
        },
    }


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
            "preset": "high",
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
            "default_rate_per_kwh": 0.18,
            "tou_rate_per_kwh": 0.42,
            "tou_start": "16:00",
            "tou_end": "21:00",
            "tou_weekdays": "0,1,2,3,4",
            "tou_name": "Peak",
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
        "preset": "high",
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
        "default_rate_per_kwh": 0.18,
        "tou_rate_per_kwh": 0.42,
        "tou_start": "16:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,1,2,3,4",
        "tou_name": "Peak",
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
        CONF_SENSITIVITY: "high",
        CONF_RETENTION_MODE: "diagnostic",
    }
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(SimpleNamespace(data={}, options={}))

    result = await flow.async_step_sources(user_input)

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert _schema_keys(result["data_schema"]) == {
        "include_circuit",
        "included_sensors",
        "circuit_name",
        "appliance_profile",
        "circuit_mode",
        "power_flow",
        "circuit_retention_mode",
    }
    assert result["description_placeholders"]["assignment_progress"] == "1 of 1"
    assert result["description_placeholders"]["current_sensors"] == (
        "sensor.fridge_power\nsensor.fridge_current"
    )


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
            CONF_SENSITIVITY: "standard",
            CONF_RETENTION_MODE: "standard",
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "assign"
    assert result["description_placeholders"]["assignment_progress"] == "1 of 2"
    assert result["description_placeholders"]["current_sensors"] == (
        "sensor.fridge_power"
    )
    assert flow._pending_config[CONF_MAINS_SOURCE_ENTITIES] == [
        "sensor.main_l1_power",
        "sensor.main_l2_power",
    ]


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
        "circuit_mode",
        "power_flow",
        "circuit_retention_mode",
    }
    assert _schema_default(result["data_schema"], "circuit_name") == (
        "Garage Vehicle Charging"
    )
    assert _schema_default(result["data_schema"], "appliance_profile") == "ev_charger"
    assert _schema_default(result["data_schema"], "circuit_mode") == "dual_phase"
    assert _schema_default(result["data_schema"], "power_flow") == "load"
    assert _schema_default(result["data_schema"], "circuit_retention_mode") == (
        "standard"
    )
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
            "power_flow": "load",
            "circuit_retention_mode": "diagnostic",
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
            "power_flow": "load",
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
    assert _schema_default(result["data_schema"], "circuit_mode") == "dual_phase"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Garage HVAC System",
            "appliance_profile": "hvac",
            "circuit_mode": "dual_phase",
            "power_flow": "load",
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
            "circuit_mode": "single_phase",
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
            "circuit_mode": "single_phase",
            "power_flow": "load",
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
            "circuit_mode": "dual_phase",
            "power_flow": "load",
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
    assert "nilm" in result["menu_options"]

    result = await flow.async_step_nilm()

    assert result["type"] == "form"
    assert result["step_id"] == "nilm"
    assert _schema_default(result["data_schema"], CONF_KNOWN_LOAD_CIRCUITS) == [
        "fridge"
    ]

    result = await flow.async_step_nilm({CONF_KNOWN_LOAD_CIRCUITS: ["hvac"]})

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

    result = await flow.async_step_sources(
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
    assert result["step_id"] == "assign"
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC Blower"
    assert _schema_default(result["data_schema"], "appliance_profile") == "hvac_blower"
    assert _schema_default(result["data_schema"], "circuit_mode") == "single_phase"


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
    assert _schema_keys(result["data_schema"]) == {"selected_assignment"}
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
            "circuit_mode": "dual_phase",
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
    assert _schema_default(result["data_schema"], "power_flow") == "generation"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Roof Solar",
            "appliance_profile": "solar_inverter",
            "circuit_mode": "single_phase",
            "power_flow": "generation",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "utility"

    result = await flow.async_step_utility({"enable_utility_comparison": False})

    assert result["type"] == "create_entry"
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
    assert _schema_default(result["data_schema"], "circuit_mode") == "single_phase"


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
        _advanced_settings_schema,
    )

    schema = _advanced_settings_schema({})

    assert _schema_default(schema, "daily_goal_kwh") == 0.0
    assert _schema_default(schema, "max_active_minutes") == 0
    assert _schema_default(schema, "max_idle_minutes") == 0
    assert _schema_default(schema, "budget_kwh") == 0.0
    assert _schema_default(schema, "default_rate_per_kwh") == 0.0
    assert _schema_default(schema, "tou_rate_per_kwh") == 0.0
    assert _schema_default(schema, "demand_limit_w") == 0.0
    assert _schema_default(schema, "breaker_amps") == 0.0
    assert _schema_default(schema, "always_on_alert_w") == 0.0
    assert _schema_default(schema, "billing_min_elapsed_days") == 3
    assert _schema_default(schema, "standby_min_samples") == 24


def test_advanced_settings_schema_exposes_power_quality_balance_and_solar_controls(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
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
        }
    )

    assert _schema_default(schema, "leg_imbalance_warning_ratio") == 0.4
    assert _schema_default(schema, "leg_imbalance_min_total_power_w") == 800.0
    assert _schema_default(schema, "apparent_power_tolerance_percent") == 12.0
    assert _schema_default(schema, "power_factor_tolerance") == 0.08
    assert _schema_default(schema, "minimum_apparent_power_va") == 120.0
    assert _schema_default(schema, "balance_negative_tolerance_w") == 250.0
    assert _schema_default(schema, "solar_export_tolerance_w") == 150.0
    assert _schema_default(schema, "solar_surplus_threshold_w") == 750.0
    assert _schema_default(schema, "high_solar_surplus_threshold_w") == 2000.0
    assert _schema_default(schema, "flexible_load_running_threshold_w") == 175.0


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
    assert _schema_default(result["data_schema"], "circuit_name") == "HVAC"

    result = await flow.async_step_assign(
        {
            "include_circuit": True,
            "circuit_name": "Upstairs HVAC",
            "appliance_profile": "hvac",
            "circuit_mode": "dual_phase",
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
            "circuit_mode": "single_phase",
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
                {"value": "standard", "label": "Standard"},
                {"value": "high", "label": "High"},
                {"value": "low", "label": "Low"},
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
                {"value": "standard", "label": "Standard"},
                {"value": "high", "label": "High"},
                {"value": "low", "label": "Low"},
            ]
        }
    }

    appliance_options = _schema_validator(
        assignment_schema,
        "appliance_profile",
    )["select"]["options"]
    assert {"value": "hvac", "label": "HVAC"} in appliance_options
    assert {"value": "hvac_compressor", "label": "HVAC Compressor"} in (
        appliance_options
    )
    assert {"value": "hvac_blower", "label": "HVAC Blower"} in appliance_options
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
