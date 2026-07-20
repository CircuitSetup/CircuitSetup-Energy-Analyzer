from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
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
                timestamp=now - timedelta(minutes=10 + index),
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
