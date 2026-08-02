from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_SOURCE_ENTITIES,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitMode,
    SensorRole,
)


def test_config_parser_groups_source_entities_for_runtime_configs() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    entry_data = {
        CONF_CIRCUITS: [],
        CONF_SOURCE_ENTITIES: [
            "sensor.kitchen_fridge_power",
            "sensor.kitchen_fridge_current",
        ],
    }

    configs = circuit_configs_from_entry_data(entry_data)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data=entry_data,
    )

    assert configs == coordinator.circuit_configs
    assert configs[0].circuit_id == "kitchen_fridge"
    assert configs[0].appliance_profile is ApplianceProfile.REFRIGERATOR
    assert configs[0].mode is CircuitMode.SINGLE_PHASE
    assert [sensor.role for sensor in configs[0].sensors] == [
        SensorRole.REAL_POWER,
        SensorRole.CURRENT,
    ]


def test_config_parser_preserves_metric_like_circuit_basename() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {CONF_SOURCE_ENTITIES: ["sensor.solar_kw_power"]}
    )

    assert configs[0].circuit_id == "solar_kw"


def test_config_parser_preserves_numbered_channel_basename() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.hvac_1_power",
                "sensor.hvac_2_power",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["hvac_1", "hvac_2"]


def test_config_parser_preserves_metric_free_numbered_channels() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.channel_1",
                "sensor.channel_2",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["channel_1", "channel_2"]


def test_config_parser_keeps_directional_energy_counters_separate() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.grid_energy_import",
                "sensor.grid_energy_export",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["grid_import", "grid_export"]
    assert [config.sensors[0].role for config in configs] == [
        SensorRole.ENERGY,
        SensorRole.ENERGY,
    ]


def test_config_parser_keeps_directional_power_sensors_separate() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.grid_power_import",
                "sensor.grid_power_export",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["grid_import", "grid_export"]


def test_config_parser_separates_duplicate_qualified_measurements() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_voltage",
                "sensor.panel_voltage_max",
                "sensor.fridge_energy",
                "sensor.fridge_energy_today",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == [
        "panel",
        "panel_max",
        "fridge",
        "fridge_today",
    ]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.panel_power",
        "sensor.panel_voltage",
    ]


def test_config_parser_separates_duplicate_metric_aliases() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.pump_power",
                "sensor.pump_kw",
                "sensor.pump_kva",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["pump", "pump_kw"]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.pump_power",
        "sensor.pump_kva",
    ]


def test_config_parser_infers_missing_roles_and_ignores_harmonics() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "appliance_profile": "mains_nilm",
                    "mode": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.energy_meter_mains_l1_harmonic"},
                        {"entity_id": "sensor.mains_harmonic_active_power"},
                        {"entity_id": "sensor.mains_harmonic_kvar"},
                        {"entity_id": "sensor.mains_harmonic_kva"},
                        {"entity_id": "sensor.mains_harmonic_distortion"},
                        {"entity_id": "sensor.mains_total_harmonic_distortion"},
                        {"entity_id": "sensor.mains_harmonic_current"},
                        {"entity_id": "sensor.mains_harmonic_voltage"},
                        {"entity_id": "sensor.mains_harmonic_frequency"},
                        {"entity_id": "sensor.mains_harmonic_power_factor"},
                        {"entity_id": "sensor.mains_harmonic_energy"},
                        {"entity_id": "sensor.mains_harmonic_peak_current"},
                        {"entity_id": "sensor.mains_harmonic_current_a"},
                        {"entity_id": "sensor.mains_harmonic_distortion_a"},
                        {"entity_id": "sensor.mains_harmonic_3_active_power"},
                        {"entity_id": "sensor.energy_meter_mains_l1_watts"},
                        {"entity_id": "sensor.energy_meter_frequency_1"},
                        {"entity_id": "sensor.energy_meter_voltage_1"},
                        {"entity_id": "sensor.energy_meter_house_total_power"},
                        {"entity_id": "sensor.reactive_energy_monitor_power"},
                        {"entity_id": "sensor.varh_meter_active_power"},
                        {"entity_id": "sensor.reactive_energy_monitor_current"},
                        {"entity_id": "sensor.varh_meter_voltage"},
                        {"entity_id": "sensor.reactive_energy_monitor_kwh"},
                        {"entity_id": "sensor.varh_meter_wh"},
                        {"entity_id": "sensor.harmonic_filter_power"},
                        {"entity_id": "sensor.high_voltage_panel_active_power"},
                        {"entity_id": "sensor.current_pump_active_power"},
                        {"entity_id": "sensor.current_pump"},
                        {"entity_id": "sensor.current_pump_watt"},
                        {"entity_id": "sensor.current_pump_kw"},
                        {"entity_id": "sensor.voltage_panel_mw"},
                        {"entity_id": "sensor.high_voltage_panel_active_power_1"},
                        {"entity_id": "sensor.current_pump_kva"},
                        {"entity_id": "sensor.voltage_panel_kvar"},
                        {"entity_id": "sensor.voltage_panel_ka"},
                        {"entity_id": "sensor.current_pump_kv"},
                        {"entity_id": "sensor.panel_current_l1_2"},
                        {"entity_id": "sensor.panel_voltage_leg_a_2"},
                        {"entity_id": "sensor.current_pump_kvarh"},
                        {"entity_id": "sensor.current_pump_kvarh_import"},
                        {"entity_id": "sensor.current_pump_varh_total"},
                        {"entity_id": "sensor.mains_reactive_energy"},
                        {"entity_id": "sensor.mains_reactive_energy_import"},
                    ],
                }
            ]
        }
    )

    assert [(sensor.entity_id, sensor.role) for sensor in configs[0].sensors] == [
        ("sensor.energy_meter_mains_l1_watts", SensorRole.REAL_POWER),
        ("sensor.energy_meter_frequency_1", SensorRole.FREQUENCY),
        ("sensor.energy_meter_voltage_1", SensorRole.VOLTAGE),
        ("sensor.energy_meter_house_total_power", SensorRole.REAL_POWER),
        ("sensor.reactive_energy_monitor_power", SensorRole.REAL_POWER),
        ("sensor.varh_meter_active_power", SensorRole.REAL_POWER),
        ("sensor.reactive_energy_monitor_current", SensorRole.CURRENT),
        ("sensor.varh_meter_voltage", SensorRole.VOLTAGE),
        ("sensor.reactive_energy_monitor_kwh", SensorRole.ENERGY),
        ("sensor.varh_meter_wh", SensorRole.ENERGY),
        ("sensor.harmonic_filter_power", SensorRole.REAL_POWER),
        ("sensor.high_voltage_panel_active_power", SensorRole.REAL_POWER),
        ("sensor.current_pump_active_power", SensorRole.REAL_POWER),
        ("sensor.current_pump", SensorRole.REAL_POWER),
        ("sensor.current_pump_watt", SensorRole.REAL_POWER),
        ("sensor.current_pump_kw", SensorRole.REAL_POWER),
        ("sensor.voltage_panel_mw", SensorRole.REAL_POWER),
        ("sensor.high_voltage_panel_active_power_1", SensorRole.REAL_POWER),
        ("sensor.current_pump_kva", SensorRole.APPARENT_POWER),
        ("sensor.voltage_panel_kvar", SensorRole.REACTIVE_POWER),
        ("sensor.voltage_panel_ka", SensorRole.CURRENT),
        ("sensor.current_pump_kv", SensorRole.VOLTAGE),
        ("sensor.panel_current_l1_2", SensorRole.CURRENT),
        ("sensor.panel_voltage_leg_a_2", SensorRole.VOLTAGE),
    ]


def test_config_parser_groups_peak_current_under_mac_suffixed_channel() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.circuitsetup_energy_meter_24x_a4e634_car_charger_watts",
                "sensor.circuitsetup_energy_meter_24x_a4e634_car_charger_peak_a",
            ]
        }
    )

    assert len(configs) == 1
    assert configs[0].name == "Car Charger"
    assert [sensor.role for sensor in configs[0].sensors] == [
        SensorRole.REAL_POWER,
        SensorRole.PEAK_CURRENT,
    ]


def test_config_parser_does_not_create_orphan_configs_for_unassigned_sources() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Refrigerator",
                    "appliance_profile": "refrigerator",
                    "mode": "single_phase",
                    "sensors": ["sensor.refrigerator_power"],
                }
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.refrigerator_kvarh",
                "sensor.car_charger_l1_harmonic_power",
                "sensor.house_total_power",
                "sensor.new_unassigned_power",
            ],
        }
    )

    assert [config.circuit_id for config in configs] == ["refrigerator"]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.refrigerator_power"
    ]


def test_config_parser_excludes_harmonic_and_total_automatic_configs() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.refrigerator_power",
                "sensor.car_charger_l1_harmonic_power",
                "sensor.house_total_power",
                "sensor.refrigerator_reactive_energy",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["refrigerator"]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.refrigerator_power"
    ]


def test_config_parser_creates_mains_config_without_experimental_nilm() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.mains_power",
                "sensor.mains_l1_harmonic_power",
                "sensor.mains_harmonic_distortion_2",
            ]
        }
    )

    assert len(configs) == 1
    assert configs[0].circuit_id == "mains"
    assert configs[0].mode is CircuitMode.MAINS_NILM
    assert configs[0].appliance_profile is ApplianceProfile.MAINS_NILM
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.mains_power"
    ]


def test_config_parser_treats_solar_inverter_sources_as_dual_phase() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {CONF_SOURCE_ENTITIES: ["sensor.roof_solar_inverter_active_power"]}
    )

    assert configs[0].appliance_profile is ApplianceProfile.SOLAR_INVERTER
    assert configs[0].mode is CircuitMode.DUAL_PHASE


def test_config_parser_coerces_raw_solar_inverter_to_dual_phase() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "appliance_profile": "solar_inverter",
                    "mode": "single_phase",
                    "sensors": ["sensor.roof_solar_inverter_active_power"],
                }
            ]
        }
    )

    assert configs[0].mode is CircuitMode.DUAL_PHASE


@pytest.mark.parametrize(
    ("entity_id", "expected_profile"),
    [
        ("sensor.kitchen_dishwasher_active_power", ApplianceProfile.DISHWASHER),
        ("sensor.kitchen_dish_washer_active_power", ApplianceProfile.DISHWASHER),
        (
            "sensor.workshop_3d_printer_active_power",
            ApplianceProfile.THREE_D_PRINTER,
        ),
        (
            "sensor.workshop_3dprinter_active_power",
            ApplianceProfile.THREE_D_PRINTER,
        ),
        (
            "sensor.workshop_3_d_printer_active_power",
            ApplianceProfile.THREE_D_PRINTER,
        ),
    ],
)
def test_config_parser_infers_new_appliance_profiles(
    entity_id: str,
    expected_profile: ApplianceProfile,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    config = circuit_configs_from_entry_data({CONF_SOURCE_ENTITIES: [entity_id]})[0]

    assert config.appliance_profile is expected_profile
    assert config.mode is CircuitMode.SINGLE_PHASE


@pytest.mark.parametrize(
    "entity_id",
    [
        "sensor.bedroom_mini_split_active_power",
        "sensor.bedroom_minisplit_active_power",
        "sensor.office_ductless_heat_pump_active_power",
        "sensor.office_ductless_ac_active_power",
    ],
)
def test_config_parser_infers_mini_split_profile(entity_id: str) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    config = circuit_configs_from_entry_data({CONF_SOURCE_ENTITIES: [entity_id]})[0]

    assert config.appliance_profile is ApplianceProfile.MINI_SPLIT
    assert config.mode is CircuitMode.DUAL_PHASE


def test_config_parser_infers_central_heat_pump_profile() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    config = circuit_configs_from_entry_data(
        {CONF_SOURCE_ENTITIES: ["sensor.downstairs_heat_pump_active_power"]}
    )[0]

    assert config.appliance_profile is ApplianceProfile.HEAT_PUMP
    assert config.mode is CircuitMode.DUAL_PHASE


def test_config_parser_accepts_both_mini_split_modes() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    for mode in (CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE):
        config = circuit_configs_from_entry_data(
            {
                CONF_CIRCUITS: [
                    {
                        "circuit_id": f"mini_split_{mode.value}",
                        "name": "Mini-Split",
                        "appliance_profile": "mini_split",
                        "mode": mode.value,
                        "sensors": ["sensor.mini_split_active_power"],
                    }
                ]
            }
        )[0]
        assert config.appliance_profile is ApplianceProfile.MINI_SPLIT
        assert config.mode is mode


@pytest.mark.parametrize(
    ("entity_id", "expected_mode"),
    [
        ("sensor.laundry_gas_dryer_active_power", CircuitMode.SINGLE_PHASE),
        ("sensor.laundry_electric_dryer_active_power", CircuitMode.DUAL_PHASE),
    ],
)
def test_config_parser_distinguishes_dryer_topology(
    entity_id: str,
    expected_mode: CircuitMode,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    config = circuit_configs_from_entry_data({CONF_SOURCE_ENTITIES: [entity_id]})[0]

    assert config.appliance_profile is ApplianceProfile.DRYER
    assert config.mode is expected_mode
