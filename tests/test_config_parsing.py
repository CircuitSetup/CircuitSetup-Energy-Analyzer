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
                        {"entity_id": "sensor.energy_meter_mains_l1_watts"},
                        {"entity_id": "sensor.energy_meter_frequency_1"},
                        {"entity_id": "sensor.energy_meter_voltage_1"},
                        {"entity_id": "sensor.energy_meter_house_total_power"},
                        {"entity_id": "sensor.high_voltage_panel_active_power"},
                        {"entity_id": "sensor.current_pump_active_power"},
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
        ("sensor.high_voltage_panel_active_power", SensorRole.REAL_POWER),
        ("sensor.current_pump_active_power", SensorRole.REAL_POWER),
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
                "sensor.car_charger_l1_harmonic_power",
                "sensor.house_total_power",
                "sensor.new_unassigned_power",
            ],
        }
    )

    assert [config.circuit_id for config in configs] == ["refrigerator"]


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
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["refrigerator"]


def test_config_parser_creates_mains_config_without_experimental_nilm() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.mains_power",
                "sensor.mains_l1_harmonic_power",
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
