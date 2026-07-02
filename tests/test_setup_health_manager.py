from __future__ import annotations

from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_setup_health_aggregator_runs_mapping_checks(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    async def fake_create(*args, **kwargs) -> None:
        del args, kwargs

    monkeypatch.setattr(
        coordinator_module.repairs,
        "existing_circuit_problem_issues",
        lambda hass, circuit_id, problems: set(),
    )
    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_data_quality_issue",
        fake_create,
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
    )

    await coordinator.setup_health.async_run_mapping_checks()

    assert coordinator.mapping_checks_run == 1
    assert (
        coordinator.state.data_quality_by_circuit["fridge"]
        == "missing_required_sensor"
    )
