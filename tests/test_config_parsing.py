from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_NILM_DETECTION_ENABLED,
    CONF_NILM_DETECTION_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitMode,
    SensorRef,
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


@pytest.mark.parametrize(
    ("metadata", "expected_role"),
    (
        ({"unit": "var"}, SensorRole.REACTIVE_POWER),
        ({"device_class": "apparent_power"}, SensorRole.APPARENT_POWER),
        ({"device_class": "power", "unit": "kW"}, SensorRole.REAL_POWER),
    ),
)
def test_config_parser_uses_unambiguous_metadata_over_saved_role(
    metadata: dict[str, str],
    expected_role: SensorRole,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data({
        CONF_CIRCUITS: [{
            "circuit_id": "meter",
            "name": "Meter",
            "sensors": [{
                "entity_id": "sensor.meter_channel",
                "role": SensorRole.REAL_POWER.value,
                **metadata,
            }],
        }],
    })

    assert configs[0].sensors[0].role is expected_role


def test_config_parser_omits_conflicting_sensor_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data({
        CONF_CIRCUITS: [{
            "circuit_id": "meter",
            "name": "Meter",
            "sensors": [{
                "entity_id": "sensor.meter_channel",
                "role": SensorRole.REAL_POWER.value,
                "device_class": "power",
                "unit": "A",
            }],
        }],
    })

    assert configs[0].sensors == ()


def test_config_parser_clamps_demand_window_to_supported_maximum() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "ev",
                    "name": "EV Charger",
                    "demand_window_minutes": 300,
                    "sensors": [
                        {"entity_id": "sensor.ev_power", "role": "real_power"}
                    ],
                }
            ]
        }
    )

    assert configs[0].demand_window_minutes == 240


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


def test_config_parser_groups_terminal_phase_aliases() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power_a",
                "sensor.panel_power_b",
                "sensor.panel_voltage_a",
                "sensor.panel_voltage_b",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["panel"]
    assert [(sensor.role, sensor.leg) for sensor in configs[0].sensors] == [
        (SensorRole.REAL_POWER, "a"),
        (SensorRole.REAL_POWER, "b"),
        (SensorRole.VOLTAGE, "a"),
        (SensorRole.VOLTAGE, "b"),
    ]


def test_source_alias_ids_are_input_order_invariant() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        source_circuit_ids_from_entity_ids,
    )

    entity_ids = [
        "sensor.pump_power",
        "sensor.pump_power_max",
        "sensor.pump_power_max_2",
    ]

    assert source_circuit_ids_from_entity_ids(
        entity_ids
    ) == source_circuit_ids_from_entity_ids(reversed(entity_ids))


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


def test_config_parser_groups_complementary_qualified_measurements() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    entity_ids = [
        "sensor.panel_power",
        "sensor.panel_current",
        "sensor.panel_voltage",
        "sensor.panel_power_max",
        "sensor.panel_current_max",
        "sensor.panel_voltage_max",
        "sensor.panel_kw_max",
        "sensor.panel_amps_max",
    ]
    configs = circuit_configs_from_entry_data({CONF_SOURCE_ENTITIES: entity_ids})
    reversed_configs = circuit_configs_from_entry_data(
        {CONF_SOURCE_ENTITIES: list(reversed(entity_ids))}
    )

    assert [config.circuit_id for config in configs] == [
        "panel",
        "panel_max",
        "panel_max_2",
    ]
    assert {sensor.role for sensor in configs[0].sensors} == {
        SensorRole.REAL_POWER,
        SensorRole.CURRENT,
        SensorRole.VOLTAGE,
    }
    assert {sensor.role for sensor in configs[1].sensors} == {
        SensorRole.REAL_POWER,
        SensorRole.CURRENT,
        SensorRole.VOLTAGE,
    }
    assert {sensor.role for sensor in configs[2].sensors} == {
        SensorRole.REAL_POWER,
        SensorRole.CURRENT,
    }
    assert {
        sensor.entity_id: config.circuit_id
        for config in reversed_configs
        for sensor in config.sensors
    } == {
        sensor.entity_id: config.circuit_id
        for config in configs
        for sensor in config.sensors
    }


def test_config_parser_groups_singleton_complementary_qualifiers() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_power_max",
                "sensor.panel_current_max",
                "sensor.panel_voltage_max",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == ["panel", "panel_max"]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.panel_power"
    ]
    assert {sensor.role for sensor in configs[1].sensors} == {
        SensorRole.REAL_POWER,
        SensorRole.CURRENT,
        SensorRole.VOLTAGE,
    }


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


def test_config_parser_reserves_existing_ids_for_duplicate_aliases() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_SOURCE_ENTITIES: [
                "sensor.pump_power",
                "sensor.pump_kw",
                "sensor.pump_kw_power",
            ]
        }
    )

    assert [config.circuit_id for config in configs] == [
        "pump",
        "pump_kw_2",
        "pump_kw",
    ]
    assert all(len(config.sensors) == 1 for config in configs)


def test_config_parser_uses_saved_sensors_for_alias_collisions() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "pump",
                    "name": "Pump",
                    "sensors": [
                        {"entity_id": "sensor.pump_power", "role": "real_power"}
                    ],
                }
            ],
            CONF_SOURCE_ENTITIES: ["sensor.pump_kw", "sensor.pump_kva"],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "pump": ["sensor.pump_power", "sensor.pump_kva"],
        "pump_kw": ["sensor.pump_kw"],
    }


def test_config_parser_moves_saved_qualified_sensor_before_base_merge() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_voltage_max",
                            "role": "voltage",
                        }
                    ],
                }
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_voltage_max",
                "sensor.panel_voltage",
            ],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_voltage"],
        "panel_max": ["sensor.panel_voltage_max"],
    }


def test_config_parser_reuses_saved_variants_for_later_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [
                        {"entity_id": "sensor.panel_power", "role": "real_power"},
                        {"entity_id": "sensor.panel_voltage", "role": "voltage"},
                    ],
                },
                {
                    "circuit_id": "panel_max",
                    "name": "Panel Max",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_power_max",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.panel_voltage_max",
                            "role": "voltage",
                        },
                    ],
                },
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_voltage",
                "sensor.panel_power_max",
                "sensor.panel_voltage_max",
                "sensor.panel_current_max",
                "sensor.panel_kw_max",
            ],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_power", "sensor.panel_voltage"],
        "panel_max": [
            "sensor.panel_power_max",
            "sensor.panel_voltage_max",
            "sensor.panel_current_max",
        ],
        "panel_max_2": ["sensor.panel_kw_max"],
    }


def test_config_parser_removes_saved_sensor_promoted_to_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [
                        {"entity_id": "sensor.panel_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "panel_max",
                    "name": "Panel Max",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_voltage_max",
                            "role": "voltage",
                        }
                    ],
                }
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_voltage_max",
                "sensor.panel_current_max",
            ],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_voltage_max"],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_power"],
        "panel_max": ["sensor.panel_current_max"],
        "mains": ["sensor.panel_voltage_max"],
    }


def test_config_parser_removes_emptied_saved_variant() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [
                        {"entity_id": "sensor.panel_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "panel_max",
                    "name": "Panel Max",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_voltage_max",
                            "role": "voltage",
                        }
                    ],
                },
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_voltage_max",
            ],
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.panel_voltage_max"],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_power"],
        "mains": ["sensor.panel_voltage_max"],
    }


def test_config_parser_reindexes_saved_variant_after_collision_clears() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [
                        {"entity_id": "sensor.panel_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "panel_max_2",
                    "name": "Panel Max 2",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_voltage_max",
                            "role": "voltage",
                        }
                    ],
                },
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_power",
                "sensor.panel_voltage_max",
                "sensor.panel_current_max",
            ],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_power"],
        "panel_max": [
            "sensor.panel_voltage_max",
            "sensor.panel_current_max",
        ],
    }


def test_config_parser_reuses_emptied_saved_base_for_later_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "panel",
                    "name": "Panel",
                    "sensors": [],
                }
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.panel_voltage",
                "sensor.panel_current_max",
            ],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "panel": ["sensor.panel_voltage"],
        "panel_max": ["sensor.panel_current_max"],
    }


def test_config_parser_does_not_rehome_manual_circuit_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "cold_storage",
                    "name": "Cold Storage",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.fridge_voltage",
            ],
        }
    )

    assert [config.circuit_id for config in configs] == ["cold_storage"]
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.fridge_power"
    ]


def test_config_parser_does_not_merge_alias_into_reserved_saved_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "pump",
                    "name": "Pump",
                    "sensors": [
                        {"entity_id": "sensor.pump_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "pump_kw",
                    "name": "Basement",
                    "sensors": [
                        {
                            "entity_id": "sensor.basement_power",
                            "role": "real_power",
                        }
                    ],
                },
            ],
            CONF_SOURCE_ENTITIES: [
                "sensor.pump_power",
                "sensor.pump_kw",
                "sensor.basement_power",
            ],
        }
    )

    assert {
        config.circuit_id: [sensor.entity_id for sensor in config.sensors]
        for config in configs
    } == {
        "pump": ["sensor.pump_power"],
        "pump_kw": ["sensor.basement_power"],
        "pump_kw_2": ["sensor.pump_kw"],
    }


def test_config_parser_merges_supported_mains_sources_and_drops_harmonics() -> None:
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
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_kw", "role": "real_power"},
                        {
                            "entity_id": "sensor.mains_reactive_energy",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.mains_harmonic_active_power",
                            "role": "real_power",
                        },
                    ],
                }
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.mains_power",
                "sensor.mains_kw",
                "sensor.mains_voltage",
                "sensor.mains_frequency",
                "sensor.mains_harmonic_active_power",
            ],
        }
    )

    assert [(sensor.entity_id, sensor.role) for sensor in configs[0].sensors] == [
        ("sensor.mains_power", SensorRole.REAL_POWER),
        ("sensor.mains_voltage", SensorRole.VOLTAGE),
        ("sensor.mains_frequency", SensorRole.FREQUENCY),
    ]


def test_config_parser_uses_runtime_metadata_for_generic_mains_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    entities = ["sensor.channel_1", "sensor.channel_2", "sensor.channel_3"]
    configs = circuit_configs_from_entry_data(
        {CONF_MAINS_SOURCE_ENTITIES: entities},
        mains_sensor_roles={
            entities[0]: SensorRole.REAL_POWER,
            entities[1]: SensorRole.VOLTAGE,
            entities[2]: None,
        },
    )

    assert [(sensor.entity_id, sensor.role) for sensor in configs[0].sensors] == [
        (entities[0], SensorRole.REAL_POWER),
        (entities[1], SensorRole.VOLTAGE),
    ]


def test_config_parser_keeps_saved_mains_role_when_metadata_is_inconclusive() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    entity_id = "sensor.channel_1"
    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "mode": "mains_nilm",
                    "sensors": [{"entity_id": entity_id, "role": "real_power"}],
                }
            ],
            CONF_MAINS_SOURCE_ENTITIES: [entity_id],
        },
        mains_sensor_roles={},
    )

    assert configs[0].sensors == (SensorRef(entity_id, SensorRole.REAL_POWER),)


def test_config_parser_keeps_supported_metrics_on_reactive_energy_devices() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "sensors": [
                        {"entity_id": "sensor.varh_meter_active_energy"},
                        {"entity_id": "sensor.reactive_energy_monitor_w"},
                        {"entity_id": "sensor.varh_meter_v"},
                        {"entity_id": "sensor.varh_meter_volts"},
                        {"entity_id": "sensor.varh_meter_a"},
                        {"entity_id": "sensor.varh_meter_apparent"},
                        {"entity_id": "sensor.varh_meter_reactive"},
                        {"entity_id": "sensor.mains_reactive_energy"},
                        {"entity_id": "sensor.mains_kvarh"},
                    ],
                }
            ]
        }
    )

    assert [(sensor.entity_id, sensor.role) for sensor in configs[0].sensors] == [
        ("sensor.varh_meter_active_energy", SensorRole.ENERGY),
        ("sensor.reactive_energy_monitor_w", SensorRole.REAL_POWER),
        ("sensor.varh_meter_v", SensorRole.VOLTAGE),
        ("sensor.varh_meter_volts", SensorRole.VOLTAGE),
        ("sensor.varh_meter_a", SensorRole.CURRENT),
        ("sensor.varh_meter_apparent", SensorRole.APPARENT_POWER),
        ("sensor.varh_meter_reactive", SensorRole.REACTIVE_POWER),
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
        ("sensor.voltage_panel_mw", SensorRole.REAL_POWER),
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
    assert configs[0].nilm_detection_enabled is False
    assert [sensor.entity_id for sensor in configs[0].sensors] == [
        "sensor.mains_power"
    ]


def test_config_parser_backfills_legacy_nilm_enablement() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "legacy_mains",
                    "name": "Legacy Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": ["sensor.mains_power"],
                },
                {
                    "circuit_id": "explicit_mains",
                    "name": "Explicit Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    CONF_NILM_DETECTION_ENABLED: False,
                    CONF_NILM_DETECTION_SENSITIVITY: "sensitive",
                    "sensors": ["sensor.other_mains_power"],
                },
            ],
        }
    )

    assert configs[0].nilm_detection_enabled is True
    assert configs[0].nilm_detection_sensitivity == "balanced"
    assert configs[1].nilm_detection_enabled is False
    assert configs[1].nilm_detection_sensitivity == "sensitive"


def test_config_parser_requires_explicit_mixed_nilm_enablement() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "legacy_mains",
                    "name": "Legacy Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": ["sensor.mains_power"],
                },
                {
                    "circuit_id": "network_rack",
                    "name": "Network Rack",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": ["sensor.network_rack_power"],
                },
                {
                    "circuit_id": "hvac_blower",
                    "name": "HVAC Blower",
                    "mode": "mixed",
                    "appliance_profile": "hvac_blower",
                    "sensors": ["sensor.hvac_blower_power"],
                },
                {
                    "circuit_id": "enabled_mixed",
                    "name": "Enabled Mixed",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    CONF_NILM_DETECTION_ENABLED: True,
                    "sensors": ["sensor.enabled_mixed_power"],
                },
            ],
        }
    )

    enabled_by_id = {
        config.circuit_id: config.nilm_detection_enabled for config in configs
    }
    assert enabled_by_id == {
        "legacy_mains": True,
        "network_rack": False,
        "hvac_blower": False,
        "enabled_mixed": True,
    }


def test_config_parser_preserves_legacy_untyped_mains_nilm_enablement() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Legacy Mains",
                    "sensors": ["sensor.mains_power"],
                },
                {
                    "circuit_id": "network_rack",
                    "name": "Network Rack",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": ["sensor.network_rack_power"],
                },
            ],
        }
    )

    enabled_by_id = {
        config.circuit_id: config.nilm_detection_enabled for config in configs
    }
    assert enabled_by_id == {
        "mains": True,
        "network_rack": False,
    }


def test_config_parser_backfills_legacy_synthetic_mains_nilm_enablement() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_parsing import (
        circuit_configs_from_entry_data,
    )

    configs = circuit_configs_from_entry_data(
        {
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.mains_power"],
        }
    )

    assert configs[0].circuit_id == "mains"
    assert configs[0].nilm_detection_enabled is True


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
