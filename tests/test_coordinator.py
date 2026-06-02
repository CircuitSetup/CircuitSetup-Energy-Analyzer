from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_SOURCE_ENTITIES,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)


def test_process_events_into_state_tracks_latest_event_per_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
        process_events_into_state,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    first = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 422.0},
    )
    later = CircuitEvent(
        timestamp=now + timedelta(minutes=8),
        circuit_id="fridge",
        event_type=EventType.STOP,
        severity=Severity.INFO,
        features={"run_duration_s": 480.0},
    )
    other = CircuitEvent(
        timestamp=now + timedelta(minutes=2),
        circuit_id="well_pump",
        event_type=EventType.VOLTAGE_SAG,
        severity=Severity.WARNING,
        features={"sag_ratio": 0.11},
    )

    state = process_events_into_state(AnalyzerState(), [later, first, other], [])

    assert state.last_event_by_circuit == {
        "fridge": later,
        "well_pump": other,
    }


def test_process_events_into_state_uses_strongest_absolute_alert_change_ratio() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
        process_events_into_state,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    weaker = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Cycle is longer than learned baseline",
        feature="cycle_duration_s",
        observed_value=420.0,
        baseline_value=360.0,
        change_ratio=0.1667,
    )
    stronger_negative = AlertEvidence(
        timestamp=now + timedelta(minutes=5),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Startup power dropped from learned baseline",
        feature="startup_power_w",
        observed_value=250.0,
        baseline_value=500.0,
        change_ratio=-0.5,
    )

    state = process_events_into_state(
        AnalyzerState(),
        [],
        [weaker, stronger_negative],
    )

    assert state.active_alerts_by_circuit == {
        "fridge": [weaker, stronger_negative],
    }
    assert state.anomaly_score_by_circuit == {"fridge": 0.5}


def test_process_events_into_state_replaces_active_alert_set() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
        process_events_into_state,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    old_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Old active alert",
        change_ratio=0.4,
    )
    last_event = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
    )
    state = AnalyzerState(
        last_event_by_circuit={"fridge": last_event},
        active_alerts_by_circuit={"fridge": [old_alert]},
        anomaly_score_by_circuit={"fridge": 0.4},
    )

    updated = process_events_into_state(state, [], [])

    assert updated.active_alerts_by_circuit == {}
    assert updated.anomaly_score_by_circuit == {"fridge": 0.0}


@pytest.mark.asyncio
async def test_coordinator_start_replaces_existing_subscription(monkeypatch) -> None:
    import custom_components.circuitsetup_energy_analyzer.coordinator as coordinator_module

    unsubscribed: list[str] = []

    def fake_track_state_change_event(hass, entity_ids, callback):
        unsubscribe_id = ",".join(entity_ids)

        def unsubscribe() -> None:
            unsubscribed.append(unsubscribe_id)

        return unsubscribe

    monkeypatch.setattr(
        coordinator_module,
        "async_track_state_change_event",
        fake_track_state_change_event,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    await coordinator.async_start(["sensor.fridge_power"])
    await coordinator.async_start(["sensor.well_pump_power"])

    assert unsubscribed == ["sensor.fridge_power"]
    assert coordinator.source_entities == ("sensor.well_pump_power",)
    await coordinator.async_stop()
    assert unsubscribed == ["sensor.fridge_power", "sensor.well_pump_power"]


@pytest.mark.asyncio
async def test_setup_entry_stores_and_unload_stops_coordinator_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.forwarded = []
            self.unloaded = []

        async def async_forward_entry_setups(self, entry, platforms) -> None:
            self.forwarded.append((entry, platforms))

        async def async_unload_platforms(self, entry, platforms) -> bool:
            self.unloaded.append((entry, platforms))
            return True

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
    )

    assert await async_setup_entry(hass, entry) is True

    coordinator = hass.data[DOMAIN]["entry-1"]
    assert isinstance(coordinator, EnergyAnalyzerCoordinator)
    assert coordinator.source_entities == ("sensor.fridge_power",)
    assert coordinator.started is True
    assert hass.config_entries.forwarded

    assert await async_unload_entry(hass, entry) is True

    assert coordinator.started is False
    assert hass.data[DOMAIN] == {}
    assert hass.config_entries.unloaded


@pytest.mark.asyncio
async def test_setup_entry_rolls_back_coordinator_when_platform_forwarding_fails() -> None:
    from custom_components.circuitsetup_energy_analyzer import async_setup_entry

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            raise RuntimeError("forward failed")

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
    )

    with pytest.raises(RuntimeError, match="forward failed"):
        await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN] == {}
