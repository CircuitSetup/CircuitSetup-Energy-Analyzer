from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    CircuitSample,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def _sample(seconds: int, watts: float) -> CircuitSample:
    return CircuitSample(
        timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
        + timedelta(seconds=seconds),
        circuit_id="fridge",
        real_power=watts,
        current=1.0,
        voltage=120.0,
        reactive_power=0.0,
        apparent_power=abs(watts),
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )


def test_feature_result_defaults_are_independent() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    first = FeatureResult()
    second = FeatureResult()

    first.events.append(
        CircuitEvent(
            timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    first.state_updates.append(
        StateUpdate(
            path=("health_summary_by_circuit", "fridge"),
            value="Running",
        )
    )

    assert len(first.events) == 1
    assert len(first.state_updates) == 1
    assert second.events == []
    assert second.state_updates == []


def test_processing_context_keeps_runtime_dependencies() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    hass = SimpleNamespace(data={DOMAIN: {}})
    state = AnalyzerState()
    store_data = FeatureStoreData()

    context = ProcessingContext(
        now=now,
        hass=hass,
        state=state,
        store_data=store_data,
        options={"sensitivity": "standard"},
        entry_data={"source_entities": ["sensor.fridge_power"]},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )

    assert context.now is now
    assert context.hass is hass
    assert context.state is state
    assert context.store_data is store_data
    assert context.known_load_circuit_ids == frozenset({"fridge"})


@pytest.mark.asyncio
async def test_coordinator_applies_feature_result() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    event = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue detected.",
        feature="processor_test",
    )
    notifications: list[AlertEvidence] = []
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={DOMAIN: {}}),
        entry_data={},
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )

    async def fake_notify(alert_to_notify: AlertEvidence) -> None:
        notifications.append(alert_to_notify)

    coordinator._notify_alert = fake_notify

    applied_events, applied_alerts = await coordinator._apply_feature_result(
        FeatureResult(
            events=[event],
            alerts=[alert],
            notifications=[alert],
            state_updates=[
                StateUpdate(
                    path=("health_summary_by_circuit", "fridge"),
                    value="Running",
                )
            ],
            store_dirty=True,
        )
    )

    assert applied_events == [event]
    assert applied_alerts == [alert]
    assert coordinator.store_data.events == [event]
    assert coordinator.store_data.alerts == [alert]
    assert coordinator.state.health_summary_by_circuit["fridge"] == "Running"
    assert notifications == [alert]
    assert coordinator._store_dirty is True


def test_event_processor_returns_events() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    first = processor.process(_sample(0, 5.0), config, context)
    second = processor.process(_sample(10, 210.0), config, context)

    assert first.events == []
    assert [event.event_type for event in second.events] == [EventType.START]
    assert second.store_dirty is True
