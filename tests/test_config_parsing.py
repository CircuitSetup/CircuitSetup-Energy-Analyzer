from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
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
