from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS, DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)


def _coordinator() -> EnergyAnalyzerCoordinator:
    return EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_current", "role": "current"},
                    ],
                }
            ],
            DOMAIN: {},
        },
    )


def test_setup_health_aggregator_builds_setup_repair_data() -> None:
    coordinator = _coordinator()

    assert coordinator.setup_health.repair_data(
        "fridge",
        "missing_energy_source",
    ) == {
        "circuit_name": "Refrigerator",
        "reason": "Daily Energy Usage needs a cumulative energy source.",
        "recommended_action": "Add a cumulative kWh sensor to Refrigerator",
        "source_entities": ["sensor.fridge_power", "sensor.fridge_current"],
    }


def test_setup_health_aggregator_builds_data_quality_repair_data() -> None:
    coordinator = _coordinator()

    assert coordinator.setup_health.data_quality_repair_data(
        "fridge",
        "unexpected_negative_real_power",
        ["sensor.fridge_power", "sensor.fridge_power"],
    ) == {
        "circuit_name": "Refrigerator",
        "reason": "A load circuit is reporting sustained negative real power.",
        "recommended_action": (
            "Check CT direction or power-flow mode for Refrigerator"
        ),
        "source_entities": ["sensor.fridge_power"],
    }
