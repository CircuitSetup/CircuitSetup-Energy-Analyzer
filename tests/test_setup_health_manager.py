from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS, DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.managers.setup_health import (
    data_quality_problem,
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


@pytest.mark.parametrize(
    ("issue", "problem"),
    [
        ("", "missing_required_sensor"),
        ("sensor.x missing", "missing_required_sensor"),
        ("sensor.x unavailable", "invalid_source_sensor"),
        ("sensor.x non_numeric", "invalid_source_sensor"),
        ("sensor.x non_finite", "invalid_source_sensor"),
        ("sensor.x naive_timestamp", "invalid_source_timestamp"),
        ("sensor.x future_timestamp", "invalid_source_timestamp"),
        ("sensor.x stale", "stale_source_sensor"),
        ("sensor.x negative_real_power_load", "unexpected_negative_real_power"),
    ],
)
def test_data_quality_problem_preserves_failure_kind(
    issue: str,
    problem: str,
) -> None:
    assert data_quality_problem(issue) == problem


@pytest.mark.asyncio
async def test_setup_health_creates_each_simultaneous_data_quality_repair(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import repairs

    created: dict[str, list[str]] = {}

    async def fake_create(
        hass,
        circuit_id,
        problem,
        *,
        source_entities=(),
        **kwargs,
    ) -> None:
        del hass, circuit_id, kwargs
        created[problem] = list(source_entities)

    monkeypatch.setattr(
        repairs,
        "existing_circuit_problem_issues",
        lambda hass, circuit_id, problems: set(),
    )
    monkeypatch.setattr(repairs, "async_create_data_quality_issue", fake_create)
    sample = SimpleNamespace(
        quality_issues=(
            "sensor.fridge_power unavailable",
            "sensor.fridge_current stale",
            "sensor.fridge_voltage future_timestamp",
        ),
        source_entity_ids=(
            "sensor.fridge_power",
            "sensor.fridge_current",
            "sensor.fridge_voltage",
        ),
    )
    coordinator = _coordinator()
    coordinator.state.learning_by_circuit["fridge"] = False

    await coordinator.setup_health.async_sync_data_quality_repairs("fridge", sample)

    assert created == {
        "invalid_source_sensor": ["sensor.fridge_power"],
        "stale_source_sensor": ["sensor.fridge_current"],
        "invalid_source_timestamp": ["sensor.fridge_voltage"],
    }

    created.clear()
    coordinator.setup_health.active_repair_issues.clear()
    coordinator.state.learning_by_circuit["fridge"] = True

    await coordinator.setup_health.async_sync_data_quality_repairs("fridge", sample)

    assert created == {
        "invalid_source_sensor": ["sensor.fridge_power"],
        "invalid_source_timestamp": ["sensor.fridge_voltage"],
    }


@pytest.mark.asyncio
async def test_setup_health_aggregator_runs_mapping_checks(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import repairs

    async def fake_create(*args, **kwargs) -> None:
        del args, kwargs

    monkeypatch.setattr(
        repairs,
        "existing_circuit_problem_issues",
        lambda hass, circuit_id, problems: set(),
    )
    monkeypatch.setattr(
        repairs,
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
