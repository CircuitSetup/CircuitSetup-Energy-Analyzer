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
