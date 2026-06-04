from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    BaselineStats,
    CircuitEvent,
    EventType,
    PowerFlowMode,
    RetentionMode,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


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
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

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
async def test_setup_entry_rolls_back_forwarding_failure() -> None:
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


@pytest.mark.asyncio
async def test_setup_entry_listens_to_synthetic_mains_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer import async_setup_entry

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            return True

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.mains_l1_power"],
        },
    )

    assert await async_setup_entry(hass, entry) is True

    coordinator = hass.data[DOMAIN]["entry-1"]
    assert coordinator.source_entities == ("sensor.mains_l1_power",)


@pytest.mark.asyncio
async def test_runtime_update_processes_states_and_notifies_mature_anomaly(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    now_holder = {"value": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def __init__(self) -> None:
            self._states = {
                "sensor.fridge_power": SimpleNamespace(
                    state="170",
                    attributes={"unit_of_measurement": "W"},
                    last_updated=now,
                )
            }

        def get(self, entity_id: str):
            state = self._states[entity_id]
            state.last_updated = now_holder["value"]
            return state

    hass = SimpleNamespace(states=FakeStates(), data={DOMAIN: {}})
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(hours=cycle_index + 1),
                circuit_id="fridge",
                event_type=EventType.START,
            )
            for cycle_index in range(20)
        ],
        baselines={
            "fridge:real_power": BaselineStats(
                feature="real_power",
                sample_count=20,
                median=100.0,
                mad=5.0,
                p10=90.0,
                p90=110.0,
                confidence=1.0,
            )
        }
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id="entry-1",
        entry_data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                            "unit": "W",
                        }
                    ],
                    "retention_mode": RetentionMode.STANDARD.value,
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now_holder["value"],
    )

    await coordinator.async_process_update()
    now_holder["value"] = now + timedelta(minutes=1)
    await coordinator.async_process_update()
    now_holder["value"] = now + timedelta(minutes=2)
    await coordinator.async_process_update()

    assert (
        coordinator.state.last_event_by_circuit["fridge"].event_type
        is EventType.START
    )
    assert coordinator.state.learning_by_circuit["fridge"] is False
    assert coordinator.state.anomaly_score_by_circuit["fridge"] > 0.5
    assert coordinator.state.active_alerts_by_circuit["fridge"]
    assert notifications
    assert notifications[0].message.startswith("Possible issue")


@pytest.mark.asyncio
async def test_runtime_refreshes_recent_activity_timeline_from_store() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    event = CircuitEvent(
        timestamp=now - timedelta(minutes=20),
        circuit_id="fridge",
        event_type=EventType.START,
        severity=Severity.INFO,
    )
    old_event = CircuitEvent(
        timestamp=now - timedelta(days=3),
        circuit_id="fridge",
        event_type=EventType.STOP,
        severity=Severity.INFO,
    )
    alert = AlertEvidence(
        timestamp=now - timedelta(minutes=5),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue: Fridge cycle duration changed.",
        feature="cycle_duration",
        observed_value=45.0,
        baseline_value=30.0,
        change_ratio=0.5,
        repeated_count=3,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store_data=FeatureStoreData(events=[old_event, event], alerts=[alert]),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert (
        coordinator.state.recent_activity_by_circuit["fridge"]
        == "Possible issue: cycle duration"
    )
    assert coordinator.state.recent_activity_count_by_circuit["fridge"] == 2
    assert coordinator.state.recent_activity_timeline_by_circuit["fridge"] == {
        "status": "activity",
        "window_hours": 24,
        "total_count": 2,
        "event_count": 1,
        "alert_count": 1,
        "latest_title": "Possible issue: cycle duration",
        "latest_timestamp": alert.timestamp.isoformat(),
        "items": [
            {
                "timestamp": alert.timestamp.isoformat(),
                "kind": "alert",
                "title": "Possible issue: cycle duration",
                "detail": "Possible issue: Fridge cycle duration changed.",
                "severity": "warning",
                "feature": "cycle_duration",
                "event_type": None,
                "observed_value": 45.0,
                "baseline_value": 30.0,
                "change_ratio": 0.5,
                "repeated_count": 3,
            },
            {
                "timestamp": event.timestamp.isoformat(),
                "kind": "event",
                "title": "Start",
                "detail": "Observed start event.",
                "severity": "info",
                "feature": None,
                "event_type": "start",
                "observed_value": None,
                "baseline_value": None,
                "change_ratio": None,
                "repeated_count": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_runtime_blocks_alerts_until_learning_window_or_cycles_mature(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="170",
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power",
                    20,
                    100.0,
                    5.0,
                    90.0,
                    110.0,
                    1.0,
                )
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications == []
    assert coordinator.state.active_alerts_by_circuit == {}
    assert coordinator.state.learning_by_circuit["fridge"] is True


@pytest.mark.asyncio
async def test_setup_entry_loads_feature_store_and_runtime_saves(monkeypatch) -> None:
    import custom_components.circuitsetup_energy_analyzer as integration

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    saved = []

    class FakeFeatureStore:
        def __init__(self, hass, entry_id) -> None:
            self.data = FeatureStoreData(
                baselines={
                    "fridge:real_power": BaselineStats(
                        "real_power",
                        20,
                        100.0,
                        5.0,
                        90.0,
                        110.0,
                        1.0,
                    )
                }
            )

        async def async_load(self):
            return self.data

        async def async_save(self) -> None:
            saved.append(self.data)

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="170",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            return True

    monkeypatch.setattr(integration, "FeatureStore", FakeFeatureStore)

    hass = SimpleNamespace(
        data={},
        states=FakeStates(),
        config_entries=FakeConfigEntries(),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                            "unit": "W",
                        }
                    ],
                }
            ],
        },
        options={},
    )

    assert await integration.async_setup_entry(hass, entry)
    coordinator = hass.data[DOMAIN]["entry-1"]
    coordinator._now_fn = lambda: now

    await coordinator.async_process_update()
    await coordinator.async_relearn_baseline("fridge")

    assert saved
    assert "fridge:real_power" not in saved[-1].baselines


@pytest.mark.asyncio
async def test_runtime_applies_retention_before_persisting_events() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    old_event = CircuitEvent(
        timestamp=now - timedelta(days=30),
        circuit_id="fridge",
        event_type=EventType.START,
    )
    recent_event = CircuitEvent(
        timestamp=now - timedelta(days=2),
        circuit_id="fridge",
        event_type=EventType.STOP,
    )
    store_data = FeatureStoreData(events=[old_event, recent_event])

    class FakeStore:
        def __init__(self) -> None:
            self.data = store_data
            self.saved_events: list[list[CircuitEvent]] = []

        async def async_save(self) -> None:
            self.saved_events.append(list(self.data.events))

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="170",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    fake_store = FakeStore()
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "retention_mode": RetentionMode.LIGHTWEIGHT.value,
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
        store=fake_store,
        store_data=store_data,
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert fake_store.saved_events
    assert old_event not in fake_store.saved_events[-1]
    assert recent_event in fake_store.saved_events[-1]


@pytest.mark.asyncio
async def test_runtime_entry_retention_applies_when_circuit_omits_retention() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    old_event = CircuitEvent(
        timestamp=now - timedelta(days=30),
        circuit_id="fridge",
        event_type=EventType.START,
    )
    store_data = FeatureStoreData(events=[old_event])

    class FakeStore:
        def __init__(self) -> None:
            self.data = store_data
            self.saved_events: list[list[CircuitEvent]] = []

        async def async_save(self) -> None:
            self.saved_events.append(list(self.data.events))

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="170",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    fake_store = FakeStore()
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_RETENTION_MODE: RetentionMode.LIGHTWEIGHT.value,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
        store=fake_store,
        store_data=store_data,
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert fake_store.saved_events
    assert old_event not in fake_store.saved_events[-1]


@pytest.mark.asyncio
async def test_runtime_skips_store_write_when_update_has_no_persisted_changes() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStore:
        def __init__(self) -> None:
            self.data = FeatureStoreData()
            self.save_count = 0

        async def async_save(self) -> None:
            self.save_count += 1

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="0",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    fake_store = FakeStore()
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
        store=fake_store,
        store_data=FeatureStoreData(
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power",
                    20,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    1.0,
                )
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()
    await coordinator.async_process_update()

    assert fake_store.save_count == 0


@pytest.mark.asyncio
async def test_runtime_dual_phase_aggregates_leg_power() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.hvac_l1_power": "400",
                "sensor.hvac_l2_power": "450",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": "sensor.hvac_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.hvac_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                }
            ]
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    event = coordinator.state.last_event_by_circuit["hvac"]
    assert event.features["startup_power_w"] == 850.0


@pytest.mark.asyncio
async def test_runtime_dual_phase_tracks_leg_imbalance_and_notifies(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.hvac_l1_power": "2400",
                "sensor.hvac_l2_power": "1200",
                "sensor.hvac_l1_current": "20",
                "sensor.hvac_l2_current": "10",
                "sensor.hvac_l1_voltage": "121",
                "sensor.hvac_l2_voltage": "119",
            }
            units = {
                "sensor.hvac_l1_power": "W",
                "sensor.hvac_l2_power": "W",
                "sensor.hvac_l1_current": "A",
                "sensor.hvac_l2_current": "A",
                "sensor.hvac_l1_voltage": "V",
                "sensor.hvac_l2_voltage": "V",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": units[entity_id]},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": "sensor.hvac_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.hvac_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": "sensor.hvac_l1_current",
                            "role": "current",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.hvac_l2_current",
                            "role": "current",
                            "leg": "b",
                        },
                        {
                            "entity_id": "sensor.hvac_l1_voltage",
                            "role": "voltage",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.hvac_l2_voltage",
                            "role": "voltage",
                            "leg": "b",
                        },
                    ],
                }
            ],
        },
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "dual_phase_leg_imbalance"
    assert alert.repeated_count == 3
    assert alert.observed_value == 0.667
    assert alert.baseline_value == 0.5
    assert "Possible issue: HVAC split-phase legs are imbalanced" in alert.message
    assert coordinator.state.leg_imbalance_percent_by_circuit["hvac"] == 66.7
    assert coordinator.state.leg_imbalance_status_by_circuit["hvac"] == "imbalanced"
    assert coordinator.state.leg_imbalance_evidence_by_circuit["hvac"] == {
        "status": "imbalanced",
        "leg_imbalance_ratio": 0.667,
        "leg_imbalance_percent": 66.7,
        "threshold_ratio": 0.5,
        "threshold_percent": 50.0,
        "minimum_total_power_w": 500.0,
        "left_real_power_w": 2400.0,
        "right_real_power_w": 1200.0,
        "left_current_a": 20.0,
        "right_current_a": 10.0,
        "left_voltage_v": 121.0,
        "right_voltage_v": 119.0,
        "voltage_difference_v": 2.0,
        "dominant_leg": "a",
    }


@pytest.mark.asyncio
async def test_runtime_tracks_power_metric_consistency() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.pump_power": "480",
                "sensor.pump_apparent": "600",
                "sensor.pump_pf": "0.8",
                "sensor.pump_voltage": "120",
                "sensor.pump_current": "10",
            }
            units = {
                "sensor.pump_power": "W",
                "sensor.pump_apparent": "VA",
                "sensor.pump_pf": "",
                "sensor.pump_voltage": "V",
                "sensor.pump_current": "A",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": units[entity_id]},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "pump",
                    "name": "Well Pump",
                    "mode": "single_phase",
                    "appliance_profile": "well_pump",
                    "sensors": [
                        {"entity_id": "sensor.pump_power", "role": "real_power"},
                        {
                            "entity_id": "sensor.pump_apparent",
                            "role": "apparent_power",
                        },
                        {"entity_id": "sensor.pump_pf", "role": "power_factor"},
                        {"entity_id": "sensor.pump_voltage", "role": "voltage"},
                        {"entity_id": "sensor.pump_current", "role": "current"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.metric_consistency_score_by_circuit["pump"] == 50.0
    assert (
        coordinator.state.metric_consistency_status_by_circuit["pump"]
        == "apparent_power_mismatch"
    )
    assert coordinator.state.metric_consistency_evidence_by_circuit["pump"] == {
        "status": "apparent_power_mismatch",
        "mismatch_score_percent": 50.0,
        "expected_apparent_power_va": 1200.0,
        "reported_apparent_power_va": 600.0,
        "apparent_power_difference_percent": -50.0,
        "apparent_power_tolerance_percent": 15.0,
        "apparent_power_source": "voltage_current",
        "expected_power_factor": 0.8,
        "reported_power_factor": 0.8,
        "power_factor_difference": 0.0,
        "power_factor_tolerance": 0.15,
    }


@pytest.mark.asyncio
async def test_runtime_dual_phase_generation_preserves_export_direction() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.solar_l1_power": "-1600",
                "sensor.solar_l2_power": "-1500",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "name": "Solar inverter",
                    "mode": "dual_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {
                            "entity_id": "sensor.solar_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.solar_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                }
            ]
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    event = coordinator.state.last_event_by_circuit["solar"]
    assert event.features["startup_power_w"] == 3100.0
    assert event.features["raw_real_power_w"] == -3100.0
    assert event.features["power_flow_direction"] == "export"


@pytest.mark.asyncio
async def test_runtime_experimental_nilm_updates_signature_diagnostics() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"watts": 100.0, "var": 10.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state=str(holder["watts"] if "power" in entity_id else holder["var"]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                        {
                            "entity_id": "sensor.mains_reactive",
                            "role": "reactive_power",
                        },
                    ],
                }
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    for index, watts in enumerate((100, 420, 110, 430, 115, 425), start=1):
        holder["watts"] = float(watts)
        holder["var"] = 10.0 if watts < 200 else 150.0
        holder["time"] = now + timedelta(seconds=index * 30)
        await coordinator.async_process_update()

    assert coordinator.state.nilm_signature_count_by_circuit["mains"] == 1
    assert coordinator.state.nilm_unmatched_load_percentage_by_circuit["mains"] > 0
    classification = coordinator.store_data.nilm_signatures["mains"][0][
        "classification"
    ]
    assert classification.startswith("possible")


@pytest.mark.asyncio
async def test_nilm_signature_expected_and_merge_review_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "on-1",
                        "classification": "unknown recurring load",
                    },
                    {
                        "signature_id": "on-2",
                        "classification": "possible motor-like load",
                    },
                    {
                        "signature_id": "on-3",
                        "classification": "ignored load",
                        "ignored": True,
                    },
                ]
            }
        ),
    )

    await coordinator.async_mark_nilm_signature_expected("mains", "on-1")
    await coordinator.async_merge_nilm_signatures("mains", "on-2", "on-1")

    signatures = {
        signature["signature_id"]: signature
        for signature in coordinator.store_data.nilm_signatures["mains"]
    }
    assert signatures["on-1"]["review_state"] == "expected"
    assert signatures["on-1"]["expected"] is True
    assert signatures["on-2"]["review_state"] == "merged"
    assert signatures["on-2"]["merged_into"] == "on-1"
    assert coordinator.state.nilm_signature_count_by_circuit["mains"] == 1
    assert {
        signature["review_state"]
        for signature in coordinator.state.nilm_review_by_circuit["mains"]
    } == {"expected", "merged", "ignored"}


@pytest.mark.asyncio
async def test_runtime_data_quality_creates_repairs_issue(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues = []

    async def fake_issue(hass, circuit_id, problem, severity=Severity.WARNING) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_data_quality_issue",
        fake_issue,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.missing", "role": "real_power"}
                    ],
                }
            ]
        },
    )

    await coordinator.async_process_update()

    assert issues == [("fridge", "missing_required_sensor")]


@pytest.mark.asyncio
async def test_runtime_negative_load_power_creates_orientation_issue(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    issues = []

    async def fake_issue(hass, circuit_id, problem, severity=Severity.WARNING) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_data_quality_issue",
        fake_issue,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "-180",
                "sensor.fridge_current": "1.7",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={
                    "unit_of_measurement": (
                        "A" if "current" in entity_id else "W"
                    )
                },
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_current", "role": "current"},
                    ],
                }
            ]
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert issues == [("fridge", "unexpected_negative_real_power")]
    assert "negative_real_power_load" in coordinator.state.data_quality_by_circuit[
        "fridge"
    ]
    assert "fridge" not in coordinator.state.last_event_by_circuit
    assert "fridge:real_power" not in coordinator.store_data.baselines


@pytest.mark.asyncio
async def test_runtime_creates_mains_nilm_config_from_mains_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: ["sensor.mains_power"],
        },
    )

    assert len(coordinator.circuit_configs) == 1
    assert coordinator.circuit_configs[0].circuit_id == "mains"
    assert coordinator.circuit_configs[0].mode is CircuitMode.MAINS_NILM
    assert (
        coordinator.circuit_configs[0].appliance_profile
        is ApplianceProfile.MAINS_NILM
    )
    assert coordinator.circuit_configs[0].power_flow is PowerFlowMode.MAINS_NET


def test_runtime_creates_mixed_energy_circuits_from_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        CircuitMode,
        SensorRole,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
                "sensor.cs_energy_analyzer_demo_hvac_energy",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_mains_l1_energy",
                "sensor.cs_energy_analyzer_demo_mains_l2_energy",
            ],
        },
    )

    by_sensor = {
        config.sensors[0].entity_id: config for config in coordinator.circuit_configs
    }

    assert set(by_sensor) == {
        "sensor.cs_energy_analyzer_demo_refrigerator_energy",
        "sensor.cs_energy_analyzer_demo_hvac_energy",
    }
    fridge = by_sensor["sensor.cs_energy_analyzer_demo_refrigerator_energy"]
    assert fridge.circuit_id == "cs_energy_analyzer_demo_refrigerator"
    assert fridge.name == "Cs Energy Analyzer Demo Refrigerator"
    assert fridge.mode is CircuitMode.MIXED
    assert fridge.sensors[0].role is SensorRole.ENERGY


def test_runtime_infers_mains_source_entity_role_from_entity_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import SensorRole

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_mains_l1_energy",
                "sensor.cs_energy_analyzer_demo_mains_l2_power",
            ],
        },
    )

    mains = coordinator.circuit_configs[0]

    assert [sensor.role for sensor in mains.sensors] == [
        SensorRole.ENERGY,
        SensorRole.REAL_POWER,
    ]


def test_runtime_circuit_config_defaults_solar_inverter_to_generation() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "name": "Solar inverter",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "battery",
                    "name": "Battery",
                    "mode": "single_phase",
                    "appliance_profile": "mixed",
                    "power_flow": "bidirectional",
                    "sensors": [
                        {"entity_id": "sensor.battery_power", "role": "real_power"}
                    ],
                },
            ]
        },
    )

    by_id = {config.circuit_id: config for config in coordinator.circuit_configs}

    assert by_id["solar"].appliance_profile is ApplianceProfile.SOLAR_INVERTER
    assert by_id["solar"].power_flow is PowerFlowMode.GENERATION
    assert by_id["battery"].power_flow is PowerFlowMode.MAINS_NET


@pytest.mark.asyncio
async def test_runtime_synthetic_mains_sums_multiple_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": "125",
                "sensor.mains_l2_power": "175",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.mains_l1_power",
                "sensor.mains_l2_power",
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    event = coordinator.state.last_event_by_circuit["mains"]
    assert event.features["startup_power_w"] == 300.0


@pytest.mark.asyncio
async def test_runtime_synthetic_mains_keeps_split_phase_nilm_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 95.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.mains_l1_power",
                "sensor.mains_l2_power",
            ],
        },
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 95.0),
        (400.0, 395.0),
        (105.0, 100.0),
        (405.0, 400.0),
        (110.0, 105.0),
        (410.0, 405.0),
    ]
    for index, (l1_w, l2_w) in enumerate(readings, start=1):
        holder["l1"] = l1_w
        holder["l2"] = l2_w
        holder["time"] = now + timedelta(seconds=index * 30)
        await coordinator.async_process_update()

    signature = coordinator.store_data.nilm_signatures["mains"][0]
    assert signature["split_phase_type"] == "balanced_240v"
    assert signature["dominant_leg"] == "balanced"
    assert signature["median_leg_a_delta_w"] == 300.0
    assert signature["median_leg_b_delta_w"] == 300.0
    assert signature["classification"] == "possible 240 V resistive load"


@pytest.mark.asyncio
async def test_runtime_mains_requires_leg_hints_for_split_phase_nilm() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"first": 100.0, "second": 95.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.panel_import_power": holder["first"],
                "sensor.panel_aux_power": holder["second"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        options={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.panel_import_power",
                "sensor.panel_aux_power",
            ],
        },
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 95.0),
        (400.0, 395.0),
        (105.0, 100.0),
        (405.0, 400.0),
        (110.0, 105.0),
        (410.0, 405.0),
    ]
    for index, (first_w, second_w) in enumerate(readings, start=1):
        holder["first"] = first_w
        holder["second"] = second_w
        holder["time"] = now + timedelta(seconds=index * 30)
        await coordinator.async_process_update()

    signature = coordinator.store_data.nilm_signatures["mains"][0]
    assert signature["split_phase_type"] == "unknown"
    assert signature["median_leg_a_delta_w"] is None
    assert signature["median_leg_b_delta_w"] is None
    assert signature["classification"] == "possible resistive load"


def test_nilm_signature_payloads_do_not_reuse_label_for_changed_topology() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmSignature

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "on-1",
                        "median_delta_w": 600.0,
                        "median_delta_var": 20.0,
                        "split_phase_type": "single_leg_a",
                        "user_label": "Kitchen circuit",
                        "expected": True,
                    }
                ]
            }
        ),
    )

    payloads = coordinator._nilm_signature_payloads(
        "mains",
        [
            NilmSignature(
                signature_id="on-1",
                median_delta_w=600.0,
                median_delta_var=20.0,
                median_delta_va=600.0,
                median_delta_pf=0.0,
                occurrence_count=3,
                confidence=0.6,
                median_leg_a_delta_w=300.0,
                median_leg_b_delta_w=300.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            )
        ],
    )

    assert "user_label" not in payloads[0]
    assert "expected" not in payloads[0]
    assert payloads[0]["classification"] == "possible 240 V resistive load"


@pytest.mark.asyncio
async def test_runtime_known_load_option_controls_nilm_masking() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def __init__(self, watts: float) -> None:
            self.watts = watts

        def get(self, entity_id: str):
            value = self.watts if "mains" in entity_id else max(self.watts - 100, 0)
            return SimpleNamespace(
                state=str(value),
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    async def unmatched_percentage_for(known_load_circuits: list[str]) -> float:
        states = FakeStates(100)
        coordinator = EnergyAnalyzerCoordinator(
            SimpleNamespace(states=states, data={}),
            entry_data={
                CONF_ENABLE_EXPERIMENTAL_NILM: True,
                CONF_KNOWN_LOAD_CIRCUITS: known_load_circuits,
                CONF_CIRCUITS: [
                    {
                        "circuit_id": "mains",
                        "name": "Mains",
                        "mode": "mains_nilm",
                        "appliance_profile": "mains_nilm",
                        "sensors": [
                            {
                                "entity_id": "sensor.mains_power",
                                "role": "real_power",
                            }
                        ],
                    },
                    {
                        "circuit_id": "fridge",
                        "name": "Fridge",
                        "mode": "single_phase",
                        "appliance_profile": "refrigerator",
                        "sensors": [
                            {
                                "entity_id": "sensor.fridge_power",
                                "role": "real_power",
                            }
                        ],
                    },
                ],
            },
            options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
            now_fn=lambda: now,
        )
        await coordinator.async_process_update()
        states.watts = 420
        await coordinator.async_process_update()
        return coordinator.state.nilm_unmatched_load_percentage_by_circuit["mains"]

    assert await unmatched_percentage_for(["fridge"]) == 0.0
    assert await unmatched_percentage_for(["hvac"]) == 100.0


@pytest.mark.asyncio
async def test_runtime_records_known_load_split_phase_topology_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    await coordinator.async_process_update()
    holder.update({"l1": 400.0, "fridge": 300.0, "time": now + timedelta(seconds=30)})
    await coordinator.async_process_update()

    assert coordinator.state.nilm_topology_status_by_circuit["fridge"] == "consistent"
    assert coordinator.state.nilm_topology_evidence_by_circuit["fridge"] == {
        "status": "consistent",
        "matched_mains_circuit_id": "mains",
        "event_type": "start",
        "configured_mode": "single_phase",
        "configured_leg": None,
        "expected_split_phase_types": ["single_leg_a", "single_leg_b"],
        "expected_dominant_legs": ["a", "b"],
        "observed_split_phase_type": "single_leg_a",
        "observed_dominant_leg": "a",
        "observed_leg": "a",
        "suggested_leg": "a",
        "observed_leg_a_delta_w": 300.0,
        "observed_leg_b_delta_w": 0.0,
        "observed_leg_balance_ratio": 2.0,
        "matched_delta_w": 300.0,
        "known_event_power_w": 300.0,
        "match_confidence": 1.0,
    }


@pytest.mark.asyncio
async def test_runtime_detects_known_load_configured_leg_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 100.0, 0.0),
        (400.0, 100.0, 300.0),
        (100.0, 100.0, 0.0),
        (410.0, 100.0, 310.0),
        (100.0, 100.0, 0.0),
        (420.0, 100.0, 320.0),
    ]
    for index, (l1_w, l2_w, fridge_w) in enumerate(readings):
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=index * 30),
            }
        )
        await coordinator.async_process_update()

    assert coordinator.state.nilm_topology_status_by_circuit["fridge"] == (
        "leg_mismatch"
    )
    evidence = coordinator.state.nilm_topology_evidence_by_circuit["fridge"]
    assert evidence["configured_leg"] == "b"
    assert evidence["observed_leg"] == "a"
    assert evidence["suggested_leg"] == "a"

    leg_alerts = [
        alert for alert in notifications if alert.feature == "nilm_leg_mismatch"
    ]
    assert leg_alerts
    assert "configured on leg b" in leg_alerts[0].message
    assert "mains NILM repeatedly matched it on leg a" in leg_alerts[0].message


@pytest.mark.asyncio
async def test_runtime_does_not_suggest_leg_from_mixed_topology_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    await coordinator.async_process_update()
    holder.update(
        {
            "l1": 175.0,
            "l2": 150.0,
            "fridge": 125.0,
            "time": now + timedelta(seconds=30),
        }
    )
    await coordinator.async_process_update()

    evidence = coordinator.state.nilm_topology_evidence_by_circuit["fridge"]
    assert evidence["status"] == "topology_mismatch"
    assert evidence["observed_split_phase_type"] == "imbalanced_240v_or_mixed"
    assert evidence["observed_dominant_leg"] == "a"
    assert evidence["observed_leg"] is None
    assert evidence["suggested_leg"] is None


@pytest.mark.asyncio
async def test_runtime_infers_configured_leg_from_single_phase_entity_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_l2_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": ["sensor.fridge_l2_power"],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 100.0, 0.0),
        (400.0, 100.0, 300.0),
        (100.0, 100.0, 0.0),
        (410.0, 100.0, 310.0),
        (100.0, 100.0, 0.0),
        (420.0, 100.0, 320.0),
    ]
    for index, (l1_w, l2_w, fridge_w) in enumerate(readings):
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=index * 30),
            }
        )
        await coordinator.async_process_update()

    evidence = coordinator.state.nilm_topology_evidence_by_circuit["fridge"]
    assert evidence["configured_leg"] == "b"
    assert evidence["observed_leg"] == "a"
    assert coordinator.state.nilm_topology_status_by_circuit["fridge"] == (
        "leg_mismatch"
    )


@pytest.mark.asyncio
async def test_runtime_alerts_on_repeated_known_load_topology_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 100.0, 0.0),
        (400.0, 400.0, 600.0),
        (100.0, 100.0, 0.0),
        (410.0, 410.0, 620.0),
        (100.0, 100.0, 0.0),
        (420.0, 420.0, 640.0),
    ]
    for index, (l1_w, l2_w, fridge_w) in enumerate(readings):
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=index * 30),
            }
        )
        await coordinator.async_process_update()

    topology_alerts = [
        alert for alert in notifications if alert.feature == "nilm_topology_mismatch"
    ]
    assert topology_alerts
    alert = topology_alerts[0]
    assert alert.feature == "nilm_topology_mismatch"
    assert alert.circuit_id == "fridge"
    assert alert.repeated_count == 3
    assert "configured as single phase" in alert.message
    assert "balanced_240v" in alert.message
    assert coordinator.state.nilm_topology_status_by_circuit["fridge"] == (
        "topology_mismatch"
    )


@pytest.mark.asyncio
async def test_runtime_ignores_low_confidence_known_load_topology_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"l1": 100.0, "l2": 100.0, "fridge": 0.0, "time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": holder["l1"],
                "sensor.mains_l2_power": holder["l2"],
                "sensor.fridge_power": holder["fridge"],
            }
            return SimpleNamespace(
                state=str(values[entity_id]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_l1_power", "role": "real_power"},
                        {"entity_id": "sensor.mains_l2_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                },
            ],
        },
        options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
        now_fn=lambda: holder["time"],
    )

    readings = [
        (100.0, 100.0, 0.0),
        (400.0, 400.0, 480.0),
        (100.0, 100.0, 0.0),
        (410.0, 410.0, 496.0),
        (100.0, 100.0, 0.0),
        (420.0, 420.0, 512.0),
    ]
    for index, (l1_w, l2_w, fridge_w) in enumerate(readings):
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=index * 30),
            }
        )
        await coordinator.async_process_update()

    assert coordinator.state.nilm_topology_status_by_circuit["fridge"] == (
        "low_confidence_match"
    )
    topology_alerts = [
        alert for alert in notifications if alert.feature == "nilm_topology_mismatch"
    ]
    assert topology_alerts == []


@pytest.mark.asyncio
async def test_relearn_clears_nilm_topology_state_and_policy() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Topology mismatch",
        feature="nilm_topology_mismatch",
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        store_data=FeatureStoreData(alerts=[alert]),
        now_fn=lambda: now,
    )
    coordinator.state.nilm_topology_status_by_circuit["fridge"] = "topology_mismatch"
    coordinator.state.nilm_topology_evidence_by_circuit["fridge"] = {
        "status": "topology_mismatch"
    }
    coordinator._nilm_topology_alert_policy_for_circuit("fridge").observe(
        coordinator_module.Observation(
            circuit_id="fridge",
            feature="nilm_topology_mismatch",
            score=1.0,
            baseline_confidence=1.0,
            observed_at=now,
        )
    )

    await coordinator.async_relearn_baseline("fridge")

    assert "fridge" not in coordinator.state.nilm_topology_status_by_circuit
    assert "fridge" not in coordinator.state.nilm_topology_evidence_by_circuit
    assert coordinator._nilm_topology_alert_policies == {}


@pytest.mark.asyncio
async def test_runtime_sensitivity_option_changes_alert_thresholds(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="110",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    async def alert_count_for_sensitivity(sensitivity: str) -> int:
        notifications: list[AlertEvidence] = []

        async def fake_notification(hass, alert) -> None:
            notifications.append(alert)

        monkeypatch.setattr(
            coordinator_module.notifications,
            "async_create_alert_notification",
            fake_notification,
        )
        coordinator = coordinator_module.EnergyAnalyzerCoordinator(
            SimpleNamespace(states=FakeStates(), data={}),
            entry_data={
                CONF_CIRCUITS: [
                    {
                        "circuit_id": "fridge",
                        "name": "Fridge",
                        "mode": "single_phase",
                        "appliance_profile": "refrigerator",
                        "sensors": [
                            {
                                "entity_id": "sensor.fridge_power",
                                "role": "real_power",
                            }
                        ],
                    }
                ],
            },
            options={CONF_SENSITIVITY: sensitivity},
            store_data=FeatureStoreData(
                events=[
                    CircuitEvent(
                        timestamp=now - timedelta(hours=index + 1),
                        circuit_id="fridge",
                        event_type=EventType.START,
                    )
                    for index in range(20)
                ],
                baselines={
                    "fridge:real_power": BaselineStats(
                        "real_power",
                        20,
                        100.0,
                        5.0,
                        90.0,
                        110.0,
                        1.0,
                    )
                },
            ),
            now_fn=lambda: now,
        )
        for _ in range(3):
            await coordinator.async_process_update()
        return len(notifications)

    assert await alert_count_for_sensitivity("standard") == 0
    assert await alert_count_for_sensitivity("high") == 1


@pytest.mark.asyncio
async def test_runtime_real_power_fallback_alerts_while_optional_metrics_learn(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "110",
                "sensor.fridge_var": "20",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                    ],
                }
            ],
        },
        options={CONF_SENSITIVITY: "high"},
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power", 20, 100.0, 5.0, 90.0, 110.0, 1.0
                )
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "real_power"
    assert coordinator.state.learning_by_circuit["fridge"] is True
    assert coordinator._baseline_values["fridge:reactive_power"] == [20.0, 20.0, 20.0]
    assert "fridge:reactive_power" not in coordinator.store_data.baselines


@pytest.mark.asyncio
async def test_relearn_baseline_clears_power_quality_runtime_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power", 20, 100.0, 5.0, 90.0, 110.0, 1.0
                )
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.power_quality_score_by_circuit["fridge"] = 4.5
    coordinator.state.power_quality_evidence_by_circuit["fridge"] = (
        "Possible issue"
    )
    coordinator.state.reactive_power_drift_by_circuit["fridge"] = 1.5
    coordinator.state.apparent_power_drift_by_circuit["fridge"] = 1.2
    coordinator.state.power_factor_drift_by_circuit["fridge"] = 0.8

    await coordinator.async_relearn_baseline("fridge")

    assert "fridge" not in coordinator.state.power_quality_score_by_circuit
    assert "fridge" not in coordinator.state.power_quality_evidence_by_circuit
    assert "fridge" not in coordinator.state.reactive_power_drift_by_circuit
    assert "fridge" not in coordinator.state.apparent_power_drift_by_circuit
    assert "fridge" not in coordinator.state.power_factor_drift_by_circuit


@pytest.mark.asyncio
async def test_runtime_no_feature_sample_clears_power_quality_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="unknown",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )
    coordinator.state.learning_by_circuit["fridge"] = False
    coordinator.state.power_quality_score_by_circuit["fridge"] = 4.5
    coordinator.state.power_quality_evidence_by_circuit["fridge"] = (
        "Possible issue"
    )
    coordinator.state.reactive_power_drift_by_circuit["fridge"] = 1.5
    coordinator.state.apparent_power_drift_by_circuit["fridge"] = 1.2
    coordinator.state.power_factor_drift_by_circuit["fridge"] = 0.8

    await coordinator.async_process_update()

    assert coordinator.state.learning_by_circuit["fridge"] is True
    assert "fridge" not in coordinator.state.power_quality_score_by_circuit
    assert "fridge" not in coordinator.state.power_quality_evidence_by_circuit
    assert "fridge" not in coordinator.state.reactive_power_drift_by_circuit
    assert "fridge" not in coordinator.state.apparent_power_drift_by_circuit
    assert "fridge" not in coordinator.state.power_factor_drift_by_circuit


@pytest.mark.asyncio
async def test_runtime_real_power_fallback_preserves_policy_window(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now, "power": 108.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state=str(holder["power"]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                }
            ],
        },
        options={CONF_SENSITIVITY: "high"},
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power", 20, 100.0, 5.0, 90.0, 110.0, 1.0
                )
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset, power in enumerate((108.0, 110.0, 110.0)):
        holder["time"] = now + timedelta(minutes=offset)
        holder["power"] = power
        await coordinator.async_process_update()

    assert notifications
    assert notifications[0].feature == "real_power"


@pytest.mark.asyncio
async def test_runtime_reactive_drift_uses_ratio_when_raw_baseline_is_zero() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "100",
                "sensor.fridge_var": "20",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power", 20, 100.0, 5.0, 90.0, 110.0, 1.0
                ),
                "fridge:reactive_power": BaselineStats(
                    "reactive_power", 20, 0.0, 1.0, 0.0, 0.0, 1.0
                ),
                "fridge:reactive_to_real_ratio": BaselineStats(
                    "reactive_to_real_ratio", 20, 0.05, 0.01, 0.04, 0.06, 1.0
                ),
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.reactive_power_drift_by_circuit["fridge"] > 2.0


@pytest.mark.asyncio
async def test_export_diagnostics_includes_power_quality_runtime_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())
    coordinator.state.power_quality_score_by_circuit["fridge"] = 3.5
    coordinator.state.power_quality_evidence_by_circuit["fridge"] = (
        "Possible issue"
    )
    coordinator.state.reactive_power_drift_by_circuit["fridge"] = 1.5
    coordinator.state.apparent_power_drift_by_circuit["fridge"] = 1.2
    coordinator.state.power_factor_drift_by_circuit["fridge"] = 0.8

    await coordinator.async_export_diagnostics("fridge")

    assert coordinator.last_exported_diagnostics["power_quality_score"] == 3.5
    assert (
        coordinator.last_exported_diagnostics["power_quality_evidence"]
        == "Possible issue"
    )
    assert coordinator.last_exported_diagnostics["reactive_power_drift"] == 1.5
    assert coordinator.last_exported_diagnostics["apparent_power_drift"] == 1.2
    assert coordinator.last_exported_diagnostics["power_factor_drift"] == 0.8


@pytest.mark.asyncio
async def test_export_history_csv_stores_retained_history_snapshot() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "fridge": {"days": [{"date": "2026-06-01", "usage_kwh": 8.5}]}
            },
            demand_by_circuit={
                "fridge": {
                    "daily_peaks": [
                        {"date": "2026-06-01", "peak_demand_w": 3200.0}
                    ]
                }
            },
        ),
    )

    await coordinator.async_export_history_csv("fridge")

    assert coordinator.last_exported_history_csv.startswith(
        "circuit_id,timestamp,period_start,period_end,metric,value,unit,source"
    )
    assert "daily_energy_usage" in coordinator.last_exported_history_csv
    assert "peak_demand" in coordinator.last_exported_history_csv


@pytest.mark.asyncio
async def test_runtime_populates_readiness_health_and_checklist_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "120",
                "sensor.fridge_var": "35",
                "sensor.fridge_pf": "0.91",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {
                            "entity_id": "sensor.fridge_var",
                            "role": "reactive_power",
                        },
                        {"entity_id": "sensor.fridge_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(days=1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power",
                    18,
                    100.0,
                    5.0,
                    90.0,
                    110.0,
                    0.8,
                )
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.health_status_by_circuit["fridge"] == "learning"
    assert coordinator.state.health_summary_by_circuit["fridge"] == "Learning"
    readiness = coordinator.state.readiness_by_circuit["fridge"]
    assert readiness["baseline_age_days"] == 1.0
    assert readiness["cycle_count"] == 2
    assert readiness["baseline_confidence"] == 0.8
    assert readiness["required_metric_coverage"] == 1.0
    assert readiness["optional_metric_coverage"] == 1.0
    assert readiness["alert_ready"] is False
    assert readiness["suppression_reason"] == "learning"
    assert (
        coordinator.state.data_quality_checklist_by_circuit["fridge"][
            "required_sensors_present"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_maintenance_mode_pauses_notifications_but_not_data_quality_repairs(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues: list[tuple[str, str]] = []

    async def fake_issue(hass, circuit_id, problem, severity=Severity.WARNING) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_data_quality_issue",
        fake_issue,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.missing", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )

    await coordinator.async_start_maintenance("fridge", note="Changed filter")
    await coordinator.async_process_update()

    assert coordinator.store_data.maintenance_by_circuit["fridge"]["active"] is True
    assert coordinator.store_data.maintenance_by_circuit["fridge"]["note"] == (
        "Changed filter"
    )
    assert "fridge" in coordinator.paused_circuits
    assert coordinator.state.maintenance_by_circuit["fridge"]["active"] is True
    assert issues == [("fridge", "missing_required_sensor")]


def test_per_circuit_sensitivity_override_controls_alert_policy() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        options={CONF_SENSITIVITY: "standard"},
        store_data=FeatureStoreData(
            sensitivity_by_circuit={"fridge": "sensitive", "hvac": "quiet"}
        ),
    )

    assert coordinator._sensitivity_for_circuit("unknown") == "balanced"
    assert coordinator._alert_policy_for_circuit("fridge").min_repeated == 3
    assert coordinator._alert_policy_for_circuit("hvac").min_repeated == 4


@pytest.mark.asyncio
async def test_expected_alert_feedback_suppresses_repeated_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        store_data=FeatureStoreData(
            alert_feedback={"fridge:reactive_power": {"action": "expected"}}
        ),
    )
    expected_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Expected compressor behavior",
        feature="reactive_power",
    )
    other_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 1, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Different behavior",
        feature="power_factor",
    )

    await coordinator._notify_alert(expected_alert)
    await coordinator._notify_alert(other_alert)

    assert notifications == [other_alert]


@pytest.mark.asyncio
async def test_alert_feedback_methods_store_circuit_feature_key() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="reactive_power",
        observed_value=42.0,
        baseline_value=20.0,
        change_ratio=1.1,
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        store_data=FeatureStoreData(alerts=[alert]),
        now_fn=lambda: datetime(2026, 6, 2, 12, 5, tzinfo=UTC),
    )

    await coordinator.async_mark_alert_expected(notification_id_for_alert(alert))

    assert coordinator.store_data.alert_feedback["fridge:reactive_power"][
        "action"
    ] == "expected"
    assert coordinator.store_data.alert_feedback["fridge:reactive_power"][
        "alert_id"
    ] == notification_id_for_alert(alert)

    await coordinator.async_mark_alert_unhelpful(notification_id_for_alert(alert))

    assert coordinator.store_data.alert_feedback["fridge:reactive_power"][
        "action"
    ] == "unhelpful"


@pytest.mark.asyncio
async def test_export_diagnostics_includes_ux_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())
    coordinator.state.health_status_by_circuit["fridge"] = "possible_issue"
    coordinator.state.health_summary_by_circuit["fridge"] = "Possible issue"
    coordinator.state.readiness_by_circuit["fridge"] = {"alert_ready": True}
    coordinator.state.learning_progress_by_circuit["fridge"] = {"cycle_count": 3}
    coordinator.state.data_quality_checklist_by_circuit["fridge"] = {
        "required_sensors_present": True
    }
    coordinator.state.alert_evidence_by_circuit["fridge"] = {
        "feature": "reactive_power"
    }
    coordinator.state.sensitivity_by_circuit["fridge"] = "quiet"
    coordinator.state.maintenance_by_circuit["fridge"] = {"active": True}
    coordinator.state.nilm_review_by_circuit["fridge"] = [
        {"signature_id": "on-1", "review_state": "new"}
    ]
    coordinator.state.energy_goal_usage_by_circuit["fridge"] = 102.5
    coordinator.state.energy_goal_status_by_circuit["fridge"] = "over_goal"
    coordinator.state.energy_goal_evidence_by_circuit["fridge"] = {
        "status": "over_goal",
        "daily_goal_kwh": 12.0,
    }
    coordinator.state.run_cycle_count_by_circuit["fridge"] = 4
    coordinator.state.run_cycle_runtime_seconds_by_circuit["fridge"] = 3600.0
    coordinator.state.run_cycle_duty_cycle_by_circuit["fridge"] = 12.5
    coordinator.state.run_cycle_status_by_circuit["fridge"] = "idle"
    coordinator.state.run_cycle_evidence_by_circuit["fridge"] = {
        "status": "idle",
        "start_count": 4,
    }

    await coordinator.async_export_diagnostics("fridge")

    assert coordinator.last_exported_diagnostics["health_status"] == "possible_issue"
    assert coordinator.last_exported_diagnostics["health_summary"] == "Possible issue"
    assert coordinator.last_exported_diagnostics["readiness"] == {
        "alert_ready": True
    }
    assert coordinator.last_exported_diagnostics["learning_progress"] == {
        "cycle_count": 3
    }
    assert coordinator.last_exported_diagnostics["data_quality_checklist"] == {
        "required_sensors_present": True
    }
    assert coordinator.last_exported_diagnostics["alert_evidence"] == {
        "feature": "reactive_power"
    }
    assert coordinator.last_exported_diagnostics["sensitivity"] == "quiet"
    assert coordinator.last_exported_diagnostics["maintenance"] == {"active": True}
    assert coordinator.last_exported_diagnostics["nilm_review"] == [
        {"signature_id": "on-1", "review_state": "new"}
    ]
    assert coordinator.last_exported_diagnostics["energy_goal_usage_percent"] == 102.5
    assert coordinator.last_exported_diagnostics["energy_goal_status"] == "over_goal"
    assert coordinator.last_exported_diagnostics["energy_goal_evidence"] == {
        "status": "over_goal",
        "daily_goal_kwh": 12.0,
    }
    assert coordinator.last_exported_diagnostics["run_cycle_count"] == 4
    assert coordinator.last_exported_diagnostics["run_cycle_runtime_seconds"] == 3600.0
    assert coordinator.last_exported_diagnostics["run_cycle_duty_cycle_percent"] == 12.5
    assert coordinator.last_exported_diagnostics["run_cycle_status"] == "idle"
    assert coordinator.last_exported_diagnostics["run_cycle_evidence"] == {
        "status": "idle",
        "start_count": 4,
    }


@pytest.mark.asyncio
async def test_runtime_learns_power_quality_baselines_for_optional_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "500",
                "sensor.fridge_var": "80",
                "sensor.fridge_va": "506",
                "sensor.fridge_pf": "0.98",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                        {"entity_id": "sensor.fridge_va", "role": "apparent_power"},
                        {"entity_id": "sensor.fridge_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        now_fn=lambda: holder["time"],
    )

    for offset in range(15):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert "fridge:real_power" in coordinator.store_data.baselines
    assert "fridge:reactive_power" in coordinator.store_data.baselines
    assert "fridge:apparent_power" in coordinator.store_data.baselines
    assert "fridge:power_factor" in coordinator.store_data.baselines
    assert "fridge:reactive_to_real_ratio" in coordinator.store_data.baselines
    assert "fridge:apparent_to_real_ratio" in coordinator.store_data.baselines
    assert coordinator.state.learning_by_circuit["fridge"] is True


@pytest.mark.asyncio
async def test_runtime_notifies_power_quality_relationship_change_after_maturity(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "510",
                "sensor.fridge_var": "220",
                "sensor.fridge_va": "560",
                "sensor.fridge_pf": "0.91",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                        {"entity_id": "sensor.fridge_va", "role": "apparent_power"},
                        {"entity_id": "sensor.fridge_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power", 20, 500.0, 20.0, 470.0, 530.0, 1.0
                ),
                "fridge:reactive_power": BaselineStats(
                    "reactive_power", 20, 80.0, 10.0, 65.0, 95.0, 1.0
                ),
                "fridge:apparent_power": BaselineStats(
                    "apparent_power", 20, 506.0, 12.0, 490.0, 520.0, 1.0
                ),
                "fridge:power_factor": BaselineStats(
                    "power_factor", 20, 0.98, 0.01, 0.96, 0.99, 1.0
                ),
                "fridge:reactive_to_real_ratio": BaselineStats(
                    "reactive_to_real_ratio", 20, 0.16, 0.02, 0.12, 0.20, 1.0
                ),
                "fridge:apparent_to_real_ratio": BaselineStats(
                    "apparent_to_real_ratio", 20, 1.01, 0.01, 1.0, 1.02, 1.0
                ),
                "fridge:power_factor_deficit": BaselineStats(
                    "power_factor_deficit", 20, 0.02, 0.01, 0.01, 0.04, 1.0
                ),
                "fridge:apparent_power_residual": BaselineStats(
                    "apparent_power_residual", 20, 0.0, 1.0, -1.0, 1.0, 1.0
                ),
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "reactive_shift_under_stable_real_power"
    assert "reactive power" in alert.message
    assert "real power stayed" in alert.message
    assert alert.features["relationship_rms"] > 2.0
    assert coordinator.state.power_quality_score_by_circuit["fridge"] > 2.0
    assert coordinator.state.power_quality_evidence_by_circuit["fridge"]


@pytest.mark.asyncio
async def test_runtime_mixed_circuit_tracks_power_quality_without_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mixed_power": "510",
                "sensor.mixed_var": "220",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mixed",
                    "name": "Kitchen Mixed",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {"entity_id": "sensor.mixed_power", "role": "real_power"},
                        {"entity_id": "sensor.mixed_var", "role": "reactive_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="mixed",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "mixed:real_power": BaselineStats(
                    "real_power", 20, 500.0, 20.0, 470.0, 530.0, 1.0
                ),
                "mixed:reactive_power": BaselineStats(
                    "reactive_power", 20, 80.0, 10.0, 65.0, 95.0, 1.0
                ),
                "mixed:reactive_to_real_ratio": BaselineStats(
                    "reactive_to_real_ratio", 20, 0.16, 0.02, 0.12, 0.20, 1.0
                ),
            },
        ),
        now_fn=lambda: now,
    )

    for _ in range(3):
        await coordinator.async_process_update()

    assert notifications == []
    assert coordinator.state.power_quality_score_by_circuit["mixed"] > 0.0
    assert coordinator.state.power_quality_evidence_by_circuit["mixed"] == ""


@pytest.mark.asyncio
async def test_runtime_notifies_daily_energy_usage_spike(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    holder = {"time": now, "energy": 112.6}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_energy"
            return SimpleNamespace(
                state=str(holder["energy"]),
                attributes={"unit_of_measurement": "kWh"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "fridge": {
                    "last_energy_kwh": 100.0,
                    "last_sample_at": "2026-06-03T00:00:00+00:00",
                    "days": [
                        {"date": "2026-05-27", "usage_kwh": 6.0},
                        {"date": "2026-05-28", "usage_kwh": 7.0},
                        {"date": "2026-05-29", "usage_kwh": 8.0},
                        {"date": "2026-05-30", "usage_kwh": 7.0},
                        {"date": "2026-05-31", "usage_kwh": 6.0},
                        {"date": "2026-06-01", "usage_kwh": 8.0},
                        {"date": "2026-06-02", "usage_kwh": 8.0},
                    ],
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        holder["energy"] += 0.1
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "daily_energy_usage_spike"
    assert "used 12.9 kWh today" in alert.message
    assert "25%" in alert.message
    assert alert.observed_value == 12.9
    assert alert.baseline_value == 12.5
    assert alert.features["baseline_total_kwh"] == 50.0
    assert coordinator.state.daily_energy_usage_by_circuit["fridge"] == 12.9
    assert coordinator.state.energy_usage_share_by_circuit["fridge"] == 25.8


@pytest.mark.asyncio
async def test_runtime_persists_energy_usage_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store=FakeStore(),
    )

    await coordinator.async_set_energy_usage_settings(
        "fridge",
        window_days=14,
        daily_spike_ratio=0.2,
    )

    assert saved
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "window_days": 14,
        "daily_spike_ratio": 0.2,
    }


@pytest.mark.asyncio
async def test_runtime_notifies_daily_energy_goal_exceeded(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    holder = {"time": now, "energy": 112.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_energy"
            return SimpleNamespace(
                state=str(holder["energy"]),
                attributes={"unit_of_measurement": "kWh"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            energy_goal_settings_by_circuit={
                "fridge": {"daily_goal_kwh": 12.0, "goal_alert_ratio": 1.0}
            },
            energy_usage_by_circuit={
                "fridge": {
                    "last_energy_kwh": 100.0,
                    "last_sample_at": "2026-06-03T00:00:00+00:00",
                    "days": [],
                }
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        holder["energy"] += 0.1
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "daily_energy_goal"
    assert "daily goal" in alert.message
    assert alert.observed_value == 12.3
    assert alert.baseline_value == 12.0
    assert coordinator.state.energy_goal_usage_by_circuit["fridge"] == 102.5
    assert coordinator.state.energy_goal_status_by_circuit["fridge"] == "over_goal"
    assert coordinator.state.energy_goal_evidence_by_circuit["fridge"] == {
        "date": "2026-06-03",
        "daily_usage_kwh": 12.3,
        "daily_goal_kwh": 12.0,
        "goal_usage_percent": 102.5,
        "alert_threshold_kwh": 12.0,
        "goal_alert_ratio": 1.0,
        "status": "over_goal",
    }


@pytest.mark.asyncio
async def test_runtime_persists_energy_goal_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store=FakeStore(),
    )

    await coordinator.async_set_energy_goal_settings(
        "fridge",
        daily_goal_kwh=12.0,
        goal_alert_ratio=1.0,
    )

    assert saved
    assert coordinator.store_data.energy_goal_settings_by_circuit["fridge"] == {
        "daily_goal_kwh": 12.0,
        "goal_alert_ratio": 1.0,
    }


@pytest.mark.asyncio
async def test_runtime_notifies_configured_activity_left_on(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_power"
            return SimpleNamespace(
                state="0",
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(minutes=45),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
            ],
            activity_alert_settings_by_circuit={
                "fridge": {"max_active_minutes": 30.0}
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "activity_left_on"
    assert alert.repeated_count == 3
    assert alert.observed_value >= 45.0
    assert alert.baseline_value == 30.0
    assert "Kitchen Fridge has been active" in alert.message


@pytest.mark.asyncio
async def test_runtime_notifies_configured_activity_inactive_too_long(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_power"
            return SimpleNamespace(
                state="0",
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=5),
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=now - timedelta(hours=4),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ],
            activity_alert_settings_by_circuit={
                "fridge": {"max_idle_minutes": 180.0}
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "activity_inactive_too_long"
    assert alert.repeated_count == 3
    assert alert.observed_value >= 240.0
    assert alert.baseline_value == 180.0
    assert "Kitchen Fridge has shown no activity" in alert.message
    assert alert.features["max_idle_minutes"] == 180.0


@pytest.mark.asyncio
async def test_runtime_persists_activity_alert_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                }
            ],
        },
        store=FakeStore(),
    )

    await coordinator.async_set_activity_alert_settings(
        "fridge",
        max_active_minutes=45.0,
        max_idle_minutes=120.0,
    )

    assert coordinator.store_data.activity_alert_settings_by_circuit["fridge"] == {
        "max_active_minutes": 45.0,
        "max_idle_minutes": 120.0,
    }
    assert saved[-1].activity_alert_settings_by_circuit["fridge"] == {
        "max_active_minutes": 45.0,
        "max_idle_minutes": 120.0,
    }


@pytest.mark.asyncio
async def test_runtime_reports_energy_dashboard_readiness() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_energy"
            return SimpleNamespace(
                state="42",
                attributes={
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                },
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.energy_dashboard_status_by_circuit["fridge"] == "ready"
    assert coordinator.state.energy_dashboard_evidence_by_circuit["fridge"] == {
        "status": "ready",
        "ready_energy_entities": ["sensor.fridge_energy"],
        "ready_power_entities": [],
        "issues": [],
        "guidance": (
            "Add the ready energy entity to Home Assistant's Energy Dashboard "
            "as an individual device."
        ),
    }


@pytest.mark.asyncio
async def test_runtime_reports_run_cycle_diagnostics_from_retained_events() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=0),
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=20),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
                CircuitEvent(
                    timestamp=now.replace(hour=11, minute=30),
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
            ]
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.run_cycle_count_by_circuit["fridge"] == 2
    assert coordinator.state.run_cycle_runtime_seconds_by_circuit["fridge"] == 3000.0
    assert coordinator.state.run_cycle_duty_cycle_by_circuit["fridge"] == 6.9
    assert coordinator.state.run_cycle_status_by_circuit["fridge"] == "running"
    assert coordinator.state.run_cycle_evidence_by_circuit["fridge"] == {
        "date": "2026-06-03",
        "status": "running",
        "start_count": 2,
        "completed_cycle_count": 1,
        "runtime_seconds": 3000.0,
        "average_cycle_seconds": 1200.0,
        "active_cycle_seconds": 1800.0,
        "duty_cycle_percent": 6.9,
        "day_elapsed_seconds": 43200.0,
        "first_start": "2026-06-03T01:00:00+00:00",
        "last_start": "2026-06-03T11:30:00+00:00",
        "last_stop": "2026-06-03T01:20:00+00:00",
        "scope": "today",
        "evidence_source": "retained_start_stop_events",
    }


@pytest.mark.asyncio
async def test_runtime_notifies_repeated_long_run_cycle_after_maturity(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_power"
            return SimpleNamespace(
                state="0",
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    events: list[CircuitEvent] = []
    for day_offset in range(1, 21):
        start = now - timedelta(days=day_offset, hours=2)
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=start + timedelta(minutes=20),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(minutes=45),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(events=events),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "run_cycle_duration_s"
    assert alert.repeated_count == 3
    assert "Kitchen Fridge has been running" in alert.message
    assert alert.observed_value >= 2700.0
    assert alert.baseline_value == 1200.0
    assert alert.features["baseline_sample_count"] == 20.0
    assert coordinator.store_data.baselines["fridge:run_cycle_duration_s"].median == (
        1200.0
    )


@pytest.mark.asyncio
async def test_runtime_tracks_peak_demand_and_notifies_limit(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 15, tzinfo=UTC)
    holder = {"time": now, "power": 2600.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.ev_power"
            return SimpleNamespace(
                state=str(holder["power"]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "ev",
                    "name": "EV Charger",
                    "mode": "single_phase",
                    "appliance_profile": "ev_charger",
                    "demand_limit_w": 2000.0,
                    "sensors": [
                        {"entity_id": "sensor.ev_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            demand_by_circuit={
                "ev": {
                    "samples": [
                        {
                            "timestamp": "2026-06-03T12:00:00+00:00",
                            "real_power_w": 2200.0,
                        },
                        {
                            "timestamp": "2026-06-03T12:05:00+00:00",
                            "real_power_w": 2400.0,
                        },
                        {
                            "timestamp": "2026-06-03T12:10:00+00:00",
                            "real_power_w": 2600.0,
                        },
                    ],
                    "daily_peaks": [],
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "demand_limit"
    assert "EV Charger demand averaged 2516.7 W" in alert.message
    assert "configured 2000 W limit" in alert.message
    assert alert.observed_value == 2516.7
    assert alert.baseline_value == 2000.0
    assert coordinator.state.current_demand_w_by_circuit["ev"] == 2516.7
    assert coordinator.state.peak_demand_w_by_circuit["ev"] == 2516.7
    assert coordinator.state.demand_limit_usage_by_circuit["ev"] == 125.8


@pytest.mark.asyncio
async def test_runtime_tracks_monthly_peak_demand_rank_and_notifies(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 15, tzinfo=UTC)
    holder = {"time": now, "power": 3700.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.mains_power"
            return SimpleNamespace(
                state=str(holder["power"]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            demand_by_circuit={
                "mains": {
                    "samples": [],
                    "daily_peaks": [],
                    "monthly_peak_windows": [
                        {
                            "timestamp": "2026-06-01T18:15:00+00:00",
                            "demand_w": 5000.0,
                            "window_minutes": 15,
                        },
                        {
                            "timestamp": "2026-06-02T17:30:00+00:00",
                            "demand_w": 4500.0,
                            "window_minutes": 15,
                        },
                        {
                            "timestamp": "2026-06-03T07:45:00+00:00",
                            "demand_w": 4000.0,
                            "window_minutes": 15,
                        },
                    ],
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert coordinator.state.demand_peak_rank_by_circuit["mains"] == 4
    assert (
        coordinator.state.demand_peak_status_by_circuit["mains"]
        == "near_monthly_peak"
    )
    assert coordinator.state.demand_evidence_by_circuit["mains"] == {
        "date": "2026-06-03",
        "current_demand_w": 3700.0,
        "peak_demand_w": 3700.0,
        "demand_window_minutes": 15,
        "demand_limit_w": None,
        "demand_limit_usage_percent": 0.0,
        "status": "unconfigured",
        "monthly_peak_rank": 4,
        "monthly_peak_status": "near_monthly_peak",
        "monthly_peak_cutoff_w": 4000.0,
        "monthly_peak_usage_percent": 92.5,
        "monthly_peak_rank_count": 3,
        "monthly_peak_warning_ratio": 0.9,
    }
    assert notifications
    alert = notifications[0]
    assert alert.feature == "demand_monthly_peak"
    assert "Mains demand averaged 3700 W" in alert.message
    assert "near this month's top 3 demand windows" in alert.message
    assert alert.observed_value == 3700.0
    assert alert.baseline_value == 4000.0
    assert alert.features["monthly_peak_usage_percent"] == 92.5


@pytest.mark.asyncio
async def test_runtime_persists_demand_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [],
                }
            ],
        },
        store=FakeStore(),
    )

    await coordinator.async_set_demand_settings(
        "hvac",
        window_minutes=30,
        demand_limit_w=4500.0,
    )

    assert saved
    assert coordinator.store_data.demand_settings_by_circuit["hvac"] == {
        "window_minutes": 30,
        "demand_limit_w": 4500.0,
    }


@pytest.mark.asyncio
async def test_runtime_tracks_circuit_capacity_and_notifies_limit(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    holder = {"time": now, "current": 34.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.ev_current"
            return SimpleNamespace(
                state=str(holder["current"]),
                attributes={"unit_of_measurement": "A"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "ev",
                    "name": "EV Charger",
                    "mode": "single_phase",
                    "appliance_profile": "ev_charger",
                    "sensors": [
                        {"entity_id": "sensor.ev_current", "role": "current"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={
                "ev": {"breaker_amps": 40.0, "warning_ratio": 0.8}
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "circuit_capacity"
    assert alert.repeated_count == 3
    assert alert.observed_value == 34.0
    assert alert.baseline_value == 32.0
    assert "EV Charger current is 34 A" in alert.message
    assert coordinator.state.capacity_usage_by_circuit["ev"] == 85.0
    assert coordinator.state.capacity_status_by_circuit["ev"] == "over_limit"
    assert coordinator.state.capacity_evidence_by_circuit["ev"] == {
        "status": "over_limit",
        "current_amps": 34.0,
        "breaker_amps": 40.0,
        "warning_threshold_amps": 32.0,
        "capacity_usage_percent": 85.0,
        "warning_ratio": 0.8,
        "current_source": "current_sensor",
    }


@pytest.mark.asyncio
async def test_runtime_persists_capacity_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "ev",
                    "name": "EV Charger",
                    "mode": "single_phase",
                    "appliance_profile": "ev_charger",
                    "sensors": [],
                }
            ],
        },
        store=FakeStore(),
    )

    await coordinator.async_set_capacity_settings(
        "ev",
        breaker_amps=40.0,
        warning_ratio=0.8,
    )

    assert saved
    assert coordinator.store_data.capacity_settings_by_circuit["ev"] == {
        "breaker_amps": 40.0,
        "warning_ratio": 0.8,
    }


@pytest.mark.asyncio
async def test_runtime_calculates_mains_balance_from_monitored_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_power": "5000",
                "sensor.hvac_power": "2400",
                "sensor.fridge_power": "300",
                "sensor.solar_power": "-1500",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"},
                    ],
                },
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.balance_power_w_by_circuit["mains"] == 2300.0
    assert coordinator.state.monitored_power_w_by_circuit["mains"] == 2700.0
    assert coordinator.state.monitored_coverage_percent_by_circuit["mains"] == 54.0
    assert coordinator.state.balance_status_by_circuit["mains"] == "tracking"
    assert coordinator.state.balance_evidence_by_circuit["mains"] == {
        "mains_power_w": 5000.0,
        "monitored_power_w": 2700.0,
        "balance_power_w": 2300.0,
        "monitored_coverage_percent": 54.0,
        "monitored_circuit_count": 2.0,
        "status": "tracking",
    }


@pytest.mark.asyncio
async def test_runtime_calculates_solar_flow_from_mains_and_generation() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_power": "-500",
                "sensor.solar_power": "-2000",
                "sensor.pool_pump_power": "800",
                "sensor.water_heater_power": "0",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "pool",
                    "name": "Pool Pump",
                    "mode": "dual_phase",
                    "appliance_profile": "pool_pump",
                    "sensors": [
                        {
                            "entity_id": "sensor.pool_pump_power",
                            "role": "real_power",
                        },
                    ],
                },
                {
                    "circuit_id": "water_heater",
                    "name": "Water Heater",
                    "mode": "dual_phase",
                    "appliance_profile": "water_heater",
                    "sensors": [
                        {
                            "entity_id": "sensor.water_heater_power",
                            "role": "real_power",
                        },
                    ],
                },
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.solar_generation_w_by_circuit["mains"] == 2000.0
    assert coordinator.state.solar_site_consumption_w_by_circuit["mains"] == 1500.0
    assert coordinator.state.solar_grid_import_w_by_circuit["mains"] == 0.0
    assert coordinator.state.solar_grid_export_w_by_circuit["mains"] == 500.0
    assert coordinator.state.solar_self_consumption_percent_by_circuit["mains"] == 75.0
    assert coordinator.state.solar_powered_percent_by_circuit["mains"] == 100.0
    assert coordinator.state.solar_flow_status_by_circuit["mains"] == "exporting"
    assert coordinator.state.solar_surplus_w_by_circuit["mains"] == 500.0
    assert coordinator.state.solar_load_shift_w_by_circuit["mains"] == 500.0
    assert (
        coordinator.state.solar_surplus_status_by_circuit["mains"]
        == "surplus_available"
    )
    assert (
        coordinator.state.solar_flexible_load_power_w_by_circuit["mains"]
        == 800.0
    )
    assert (
        coordinator.state.solar_flexible_load_coverage_percent_by_circuit["mains"]
        == 100.0
    )
    assert (
        coordinator.state.solar_load_shift_status_by_circuit["mains"]
        == "active_solar_supported"
    )
    assert coordinator.state.solar_flow_evidence_by_circuit["mains"] == {
        "mains_net_power_w": -500.0,
        "solar_generation_w": 2000.0,
        "grid_import_w": 0.0,
        "grid_export_w": 500.0,
        "site_consumption_w": 1500.0,
        "solar_used_on_site_w": 1500.0,
        "self_consumption_percent": 75.0,
        "solar_powered_percent": 100.0,
        "solar_surplus_w": 500.0,
        "load_shift_available_w": 500.0,
        "solar_surplus_threshold_w": 500.0,
        "high_solar_surplus_threshold_w": 1500.0,
        "generation_circuit_count": 1.0,
        "status": "exporting",
        "solar_surplus_status": "surplus_available",
    }
    assert coordinator.state.solar_load_shift_evidence_by_circuit["mains"] == {
        "status": "active_solar_supported",
        "solar_surplus_status": "surplus_available",
        "active_flexible_load_power_w": 800.0,
        "solar_load_shift_available_w": 500.0,
        "grid_import_w": 0.0,
        "solar_coverage_percent": 100.0,
        "active_flexible_load_count": 1,
        "idle_flexible_load_count": 1,
        "unavailable_flexible_load_count": 0,
        "candidate_loads": [
            {
                "circuit_id": "pool",
                "name": "Pool Pump",
                "appliance_profile": "pool_pump",
                "current_power_w": 800.0,
                "state": "active",
            },
            {
                "circuit_id": "water_heater",
                "name": "Water Heater",
                "appliance_profile": "water_heater",
                "current_power_w": 0.0,
                "state": "idle",
            },
        ],
    }


@pytest.mark.asyncio
async def test_runtime_tracks_always_on_and_notifies_limit(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
    holder = {"time": now, "power": 46.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.office_power"
            return SimpleNamespace(
                state=str(holder["power"]),
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "office",
                    "name": "Office",
                    "mode": "single_phase",
                    "appliance_profile": "mixed",
                    "standby_threshold_w": 8.0,
                    "always_on_alert_w": 25.0,
                    "standby_min_samples": 6,
                    "sensors": [
                        {"entity_id": "sensor.office_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            standby_by_circuit={
                "office": {
                    "samples": [
                        {
                            "timestamp": f"2026-06-03T{hour:02d}:00:00+00:00",
                            "real_power_w": 45.0,
                        }
                        for hour in range(8)
                    ]
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "always_on_power"
    assert "Office Always On is 45 W" in alert.message
    assert "configured 25 W limit" in alert.message
    assert coordinator.state.always_on_power_w_by_circuit["office"] == 45.0
    assert coordinator.state.standby_status_by_circuit["office"] == "on"
    assert coordinator.state.always_on_limit_usage_by_circuit["office"] == 180.0


@pytest.mark.asyncio
async def test_runtime_persists_standby_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "office",
                    "name": "Office",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [],
                }
            ],
        },
        store=FakeStore(),
    )

    await coordinator.async_set_standby_settings(
        "office",
        window_hours=48,
        standby_threshold_w=10.0,
        always_on_alert_w=30.0,
    )

    assert saved
    assert coordinator.store_data.standby_settings_by_circuit["office"] == {
        "window_hours": 48,
        "standby_threshold_w": 10.0,
        "always_on_alert_w": 30.0,
    }


@pytest.mark.asyncio
async def test_runtime_compares_utility_to_configured_mains_energy_and_notifies(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_power": "1000",
                "sensor.opower_current_bill_usage": "120",
                "sensor.panel_import_energy": "135",
            }
            units = {
                "sensor.mains_power": "W",
                "sensor.opower_current_bill_usage": "kWh",
                "sensor.panel_import_energy": "kWh",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": units[entity_id]},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
            ],
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {
                    "utility_energy_entity": "sensor.opower_current_bill_usage",
                    "measured_energy_entities": ["sensor.panel_import_energy"],
                    "tolerance_percent": 10.0,
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "utility_energy_mismatch"
    assert alert.repeated_count == 3
    assert alert.observed_value == 135.0
    assert alert.baseline_value == 120.0
    assert alert.change_ratio == 0.125
    assert "Utility comparison mismatch" in alert.message
    assert "Mains measured 135 kWh" in alert.message
    assert coordinator.state.utility_comparison_status_by_circuit["mains"] == (
        "mismatch"
    )
    assert (
        coordinator.state.utility_comparison_difference_kwh_by_circuit["mains"]
        == 15.0
    )
    assert (
        coordinator.state.utility_comparison_difference_percent_by_circuit["mains"]
        == 12.5
    )
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"] == {
        "status": "mismatch",
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "",
        "utility_source_id": "sensor.opower_current_bill_usage",
        "utility_source_type": "entity",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "comparison_source": "explicit_entities",
        "measured_source_type": "entity_state",
        "period_start": None,
        "period_end": None,
        "utility_data_lag_hours": None,
        "utility_kwh": 120.0,
        "measured_kwh": 135.0,
        "difference_kwh": 15.0,
        "difference_percent": 12.5,
        "absolute_difference_percent": 12.5,
        "tolerance_percent": 10.0,
    }


@pytest.mark.asyncio
async def test_runtime_sums_circuit_energy_when_measured_entities_omitted() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_power": "1000",
                "sensor.opower_current_bill_usage": "50",
                "sensor.fridge_energy": "20",
                "sensor.hvac_energy": "42",
                "sensor.solar_energy": "100",
            }
            units = {
                "sensor.mains_power": "W",
                "sensor.opower_current_bill_usage": "kWh",
                "sensor.fridge_energy": "kWh",
                "sensor.hvac_energy": "kWh",
                "sensor.solar_energy": "kWh",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": units[entity_id]},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_energy", "role": "energy"},
                    ],
                },
            ],
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {
                    "utility_energy_entity": "sensor.opower_current_bill_usage",
                    "tolerance_percent": 10.0,
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.utility_comparison_status_by_circuit["mains"] == (
        "mismatch"
    )
    assert (
        coordinator.state.utility_comparison_difference_kwh_by_circuit["mains"]
        == 12.0
    )
    assert (
        coordinator.state.utility_comparison_difference_percent_by_circuit["mains"]
        == 24.0
    )
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"] == {
        "status": "mismatch",
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "",
        "utility_source_id": "sensor.opower_current_bill_usage",
        "utility_source_type": "entity",
        "utility_statistic_period": "day",
        "measured_energy_entities": [
            "sensor.fridge_energy",
            "sensor.hvac_energy",
        ],
        "comparison_source": "circuit_energy_sum",
        "measured_source_type": "entity_state",
        "period_start": None,
        "period_end": None,
        "utility_data_lag_hours": None,
        "utility_kwh": 50.0,
        "measured_kwh": 62.0,
        "difference_kwh": 12.0,
        "difference_percent": 24.0,
        "absolute_difference_percent": 24.0,
        "tolerance_percent": 10.0,
    }


@pytest.mark.asyncio
async def test_runtime_compares_opower_statistics_with_measured_mains_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    period_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)
    calls: list[dict[str, object]] = []

    def timestamp_ms(value: datetime) -> int:
        return int(value.timestamp() * 1000)

    def fake_statistics_during_period(
        hass: object,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str],
        types: set[str],
    ) -> dict[str, list[dict[str, float]]]:
        del hass
        calls.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "statistic_ids": statistic_ids,
                "period": period,
                "units": units,
                "types": types,
            }
        )
        if statistic_ids == {"opower:utility_elec_consumption"}:
            return {
                "opower:utility_elec_consumption": [
                    {
                        "start": timestamp_ms(
                            datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
                        ),
                        "end": timestamp_ms(period_start),
                        "change": 29.0,
                    },
                    {
                        "start": timestamp_ms(period_start),
                        "end": timestamp_ms(period_end),
                        "change": 30.0,
                    },
                ]
            }
        if statistic_ids == {"sensor.mains_import_energy"}:
            assert start_time == period_start
            assert end_time == period_end
            return {
                "sensor.mains_import_energy": [
                    {
                        "start": timestamp_ms(period_start),
                        "end": timestamp_ms(period_end),
                        "change": 36.0,
                    }
                ]
            }
        return {}

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        fake_statistics_during_period,
        raising=False,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.mains_power"
            return SimpleNamespace(
                state="1000",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
            ],
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {
                    "utility_statistic_id": "opower:utility_elec_consumption",
                    "utility_source_type": "statistics",
                    "measured_energy_entities": ["sensor.mains_import_energy"],
                    "tolerance_percent": 10.0,
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert calls[0]["statistic_ids"] == {"opower:utility_elec_consumption"}
    assert calls[0]["period"] == "day"
    assert calls[1]["statistic_ids"] == {"sensor.mains_import_energy"}
    assert coordinator.state.utility_comparison_status_by_circuit["mains"] == (
        "mismatch"
    )
    assert (
        coordinator.state.utility_comparison_difference_kwh_by_circuit["mains"]
        == 6.0
    )
    assert (
        coordinator.state.utility_comparison_difference_percent_by_circuit["mains"]
        == 20.0
    )
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"] == {
        "status": "mismatch",
        "utility_energy_entity": "",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_id": "opower:utility_elec_consumption",
        "utility_source_type": "statistics",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.mains_import_energy"],
        "comparison_source": "explicit_entities",
        "measured_source_type": "statistics",
        "period_start": "2026-06-02T00:00:00+00:00",
        "period_end": "2026-06-03T00:00:00+00:00",
        "utility_data_lag_hours": 48.0,
        "utility_kwh": 30.0,
        "measured_kwh": 36.0,
        "difference_kwh": 6.0,
        "difference_percent": 20.0,
        "absolute_difference_percent": 20.0,
        "tolerance_percent": 10.0,
    }


@pytest.mark.asyncio
async def test_runtime_compares_opower_statistics_with_configured_circuit_sum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    period_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)
    measured_statistic_ids: list[set[str]] = []

    def timestamp_ms(value: datetime) -> int:
        return int(value.timestamp() * 1000)

    def fake_statistics_during_period(
        hass: object,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str],
        types: set[str],
    ) -> dict[str, list[dict[str, float]]]:
        del hass, period, units, types
        if statistic_ids == {"opower:utility_elec_consumption"}:
            return {
                "opower:utility_elec_consumption": [
                    {
                        "start": timestamp_ms(period_start),
                        "end": timestamp_ms(period_end),
                        "change": 50.0,
                    }
                ]
            }
        measured_statistic_ids.append(statistic_ids)
        assert start_time == period_start
        assert end_time == period_end
        return {
            "sensor.fridge_energy": [
                {
                    "start": timestamp_ms(period_start),
                    "end": timestamp_ms(period_end),
                    "change": 20.0,
                }
            ],
            "sensor.hvac_energy": [
                {
                    "start": timestamp_ms(period_start),
                    "end": timestamp_ms(period_end),
                    "change": 32.0,
                }
            ],
        }

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        fake_statistics_during_period,
        raising=False,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_power": "1000",
                "sensor.fridge_energy": "20",
                "sensor.hvac_energy": "32",
                "sensor.solar_energy": "100",
            }
            units = {
                "sensor.mains_power": "W",
                "sensor.fridge_energy": "kWh",
                "sensor.hvac_energy": "kWh",
                "sensor.solar_energy": "kWh",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": units[entity_id]},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_energy", "role": "energy"},
                    ],
                },
            ],
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {
                    "utility_statistic_id": "opower:utility_elec_consumption",
                    "utility_source_type": "statistics",
                    "tolerance_percent": 10.0,
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert measured_statistic_ids == [{"sensor.fridge_energy", "sensor.hvac_energy"}]
    assert coordinator.state.utility_comparison_status_by_circuit["mains"] == (
        "tracking"
    )
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"][
        "measured_energy_entities"
    ] == ["sensor.fridge_energy", "sensor.hvac_energy"]
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"][
        "comparison_source"
    ] == "circuit_energy_sum"
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"][
        "measured_source_type"
    ] == "statistics"
    assert (
        coordinator.state.utility_comparison_difference_kwh_by_circuit["mains"]
        == 2.0
    )


@pytest.mark.asyncio
async def test_runtime_handles_unavailable_recorder_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)

    def broken_statistics_during_period(*args, **kwargs):
        raise RuntimeError("recorder is not available")

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        broken_statistics_during_period,
        raising=False,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.mains_power"
            return SimpleNamespace(
                state="1000",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"},
                    ],
                },
            ],
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {
                    "utility_statistic_id": "opower:utility_elec_consumption",
                    "utility_source_type": "statistics",
                    "measured_energy_entities": ["sensor.mains_import_energy"],
                    "tolerance_percent": 10.0,
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.utility_comparison_status_by_circuit["mains"] == (
        "missing_utility"
    )
    assert coordinator.state.utility_comparison_evidence_by_circuit["mains"][
        "utility_source_type"
    ] == "statistics"


@pytest.mark.asyncio
async def test_runtime_persists_utility_comparison_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store=FakeStore(),
    )

    await coordinator.async_set_utility_comparison_settings(
        "mains",
        utility_energy_entity="sensor.opower_current_bill_usage",
        utility_statistic_id="opower:utility_elec_consumption",
        utility_source_type="auto",
        utility_statistic_period="day",
        measured_energy_entities=["sensor.panel_import_energy"],
        tolerance_percent=8.5,
    )

    assert saved
    assert coordinator.store_data.utility_comparison_settings_by_circuit["mains"] == {
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_type": "auto",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 8.5,
    }


def test_standby_settings_default_to_two_day_low_watermark_window() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "office",
                    "name": "Office",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [],
                }
            ],
        },
    )

    settings = coordinator._standby_settings_for_config(
        coordinator.circuit_configs[0],
        "office",
    )

    assert settings.window_hours == 48


@pytest.mark.asyncio
async def test_runtime_tracks_billing_cycle_and_notifies_budget(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    holder = {"time": now, "energy": 200.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_energy"
            return SimpleNamespace(
                state=str(holder["energy"]),
                attributes={"unit_of_measurement": "kWh"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "billing_cycle_start_day": 1,
                    "billing_cycle_budget_kwh": 250.0,
                    "billing_cycle_budget_alert_ratio": 1.0,
                    "billing_cycle_min_elapsed_days": 3,
                    "sensors": [
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            billing_by_circuit={
                "fridge": {
                    "cycle_start": "2026-06-01",
                    "cycle_end": "2026-07-01",
                    "cycle_usage_kwh": 90.0,
                    "last_energy_kwh": 190.0,
                    "last_sample_at": "2026-06-10T00:00:00+00:00",
                }
            }
        ),
        now_fn=lambda: holder["time"],
    )

    for hour in (18, 19, 20):
        holder["time"] = datetime(2026, 6, 10, hour, 0, tzinfo=UTC)
        await coordinator.async_process_update()

    assert len(notifications) == 1
    alert = notifications[0]
    assert alert.feature == "billing_cycle_budget"
    assert "Fridge is projected to use 300 kWh" in alert.message
    assert "configured 250 kWh billing-cycle budget" in alert.message
    assert coordinator.state.billing_cycle_usage_kwh_by_circuit["fridge"] == 100.0
    assert coordinator.state.billing_cycle_forecast_kwh_by_circuit["fridge"] == 300.0
    assert coordinator.state.billing_cycle_budget_usage_by_circuit["fridge"] == 40.0
    assert (
        coordinator.state.billing_cycle_status_by_circuit["fridge"]
        == "projected_over_budget"
    )


@pytest.mark.asyncio
async def test_runtime_persists_billing_cycle_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store=FakeStore(),
    )

    await coordinator.async_set_billing_cycle_settings(
        "fridge",
        cycle_start_day=15,
        budget_kwh=300.0,
        budget_alert_ratio=0.9,
    )

    assert saved
    assert coordinator.store_data.billing_settings_by_circuit["fridge"] == {
        "cycle_start_day": 15,
        "budget_kwh": 300.0,
        "budget_alert_ratio": 0.9,
    }


@pytest.mark.asyncio
async def test_runtime_tracks_time_of_use_cost() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 8, 18, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.hvac_energy"
            return SimpleNamespace(
                state="104",
                attributes={"unit_of_measurement": "kWh"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "cost_cycle_start_day": 1,
                    "default_rate_per_kwh": 0.10,
                    "tou_rate_per_kwh": 0.30,
                    "tou_start": "17:00",
                    "tou_end": "21:00",
                    "tou_weekdays": "0,1,2,3,4",
                    "tou_name": "Peak",
                    "sensors": [
                        {"entity_id": "sensor.hvac_energy", "role": "energy"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            cost_by_circuit={
                "hvac": {
                    "cycle_start": "2026-06-01",
                    "cycle_end": "2026-07-01",
                    "cycle_cost": 5.0,
                    "last_energy_kwh": 100.0,
                    "last_sample_at": "2026-06-08T16:30:00+00:00",
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.cost_current_rate_by_circuit["hvac"] == 0.30
    assert coordinator.state.cost_cycle_by_circuit["hvac"] == 6.2
    assert coordinator.state.cost_cycle_forecast_by_circuit["hvac"] == 23.25
    assert coordinator.state.cost_status_by_circuit["hvac"] == "tou_peak"
    assert coordinator.state.cost_evidence_by_circuit["hvac"]["active_rate_name"] == (
        "Peak"
    )


@pytest.mark.asyncio
async def test_runtime_persists_cost_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
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
        store=FakeStore(),
    )

    await coordinator.async_set_cost_settings(
        "fridge",
        cycle_start_day=1,
        default_rate_per_kwh=0.20,
        tou_rate_per_kwh=0.30,
        tou_start="17:00",
        tou_end="21:00",
        tou_weekdays="0,1,2,3,4",
        tou_name="Peak",
    )

    assert saved
    assert coordinator.store_data.cost_settings_by_circuit["fridge"] == {
        "cycle_start_day": 1,
        "default_rate_per_kwh": 0.20,
        "tou_rate_per_kwh": 0.30,
        "tou_start": "17:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,1,2,3,4",
        "tou_name": "Peak",
    }


@pytest.mark.asyncio
async def test_runtime_mixed_circuit_suppresses_real_power_fallback_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mixed_power": "170",
                "sensor.mixed_var": "90",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mixed",
                    "name": "Kitchen Mixed",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {"entity_id": "sensor.mixed_power", "role": "real_power"},
                        {"entity_id": "sensor.mixed_var", "role": "reactive_power"},
                    ],
                }
            ],
        },
        options={CONF_SENSITIVITY: "high"},
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="mixed",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "mixed:real_power": BaselineStats(
                    "real_power", 20, 100.0, 5.0, 90.0, 110.0, 1.0
                ),
                "mixed:reactive_power": BaselineStats(
                    "reactive_power", 20, 80.0, 10.0, 65.0, 95.0, 1.0
                ),
            },
        ),
        now_fn=lambda: now,
    )

    for _ in range(3):
        await coordinator.async_process_update()

    assert notifications == []
    assert coordinator.state.active_alerts_by_circuit.get("mixed", []) == []
    assert coordinator.state.power_quality_score_by_circuit["mixed"] > 0.0
    assert coordinator.state.power_quality_evidence_by_circuit["mixed"] == ""
