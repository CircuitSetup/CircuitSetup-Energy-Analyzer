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
