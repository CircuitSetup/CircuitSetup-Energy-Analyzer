from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
)
from custom_components.circuitsetup_energy_analyzer.profiles import (
    get_profile_definition,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_coordinator_exposes_processor_runtime_learning_maturity() -> None:
    now = datetime(2026, 7, 2, 12, tzinfo=UTC)
    minimum_cycles = get_profile_definition("refrigerator").minimum_cycles
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(days=8, minutes=index),
                circuit_id="fridge",
                event_type=EventType.START,
            )
            for index in range(minimum_cycles)
        ]
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    assert coordinator.processor_runtime.__class__.__name__ == "ProcessorRuntimeManager"
    assert coordinator.processor_runtime.learning_mature(
        coordinator.circuit_configs[0],
        now,
    )

    store_data.learning_started_at_by_circuit["fridge"] = now.isoformat()
    assert not coordinator.processor_runtime.learning_mature(
        coordinator.circuit_configs[0],
        now,
    )
    coordinator.refresh_ux_state_for_circuit("fridge", now)
    progress = coordinator.state.learning_progress_by_circuit["fridge"]
    assert progress["baseline_age_days"] == 0.0
    assert progress["cycle_count"] == 0

    store_data.events.extend(
        CircuitEvent(
            timestamp=now,
            circuit_id="fridge",
            event_type=EventType.START,
        )
        for _index in range(minimum_cycles)
    )
    assert coordinator.processor_runtime.learning_mature(
        coordinator.circuit_configs[0],
        now,
    )


def test_power_transition_does_not_advance_lifecycle_learning() -> None:
    now = datetime(2026, 7, 2, 12, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(days=8),
                circuit_id="fridge",
                event_type=EventType.POWER_TRANSITION,
                features={"transition_delta_w": 400.0},
            )
        ]
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    assert not coordinator.processor_runtime.learning_mature(
        coordinator.circuit_configs[0],
        now,
    )


def test_mains_quality_learning_matures_from_learning_age_without_cycles() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    store_data = FeatureStoreData(
        learning_started_at_by_circuit={
            "mains": (now - timedelta(days=8)).isoformat(),
        },
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    assert not coordinator.processor_runtime.learning_mature(config, now)
    assert coordinator.processor_runtime.mains_power_quality_learning_mature(
        config,
        now,
    )

    store_data.learning_started_at_by_circuit["mains"] = (
        now - timedelta(days=1)
    ).isoformat()
    assert not coordinator.processor_runtime.mains_power_quality_learning_mature(
        config,
        now,
    )


def test_mains_quality_learning_ignores_retained_start_cycles() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    minimum_cycles = get_profile_definition(ApplianceProfile.MAINS_NILM).minimum_cycles
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=index),
                circuit_id="mains",
                event_type=EventType.START,
            )
            for index in range(minimum_cycles)
        ],
        learning_started_at_by_circuit={
            "mains": (now - timedelta(days=1)).isoformat(),
        },
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    assert coordinator.processor_runtime.learning_mature(config, now)
    assert not coordinator.processor_runtime.mains_power_quality_learning_mature(
        config,
        now,
    )


def test_mains_quality_learning_epoch_is_seeded_when_missing() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    store_data = FeatureStoreData()
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    assert store_data.learning_started_at_by_circuit["mains"] == now.isoformat()
    assert coordinator.store_persistence.dirty is True
    assert not coordinator.processor_runtime.mains_power_quality_learning_mature(
        coordinator.circuit_configs[0],
        now,
    )
