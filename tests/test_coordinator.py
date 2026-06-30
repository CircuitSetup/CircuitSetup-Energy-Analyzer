import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_ENTITY_MODEL_VERSION,
    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_MODEL_LEGACY,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    AnalyzerState,
    _apply_state_update,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    PowerFlowMode,
    RetentionMode,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_apply_state_update_rejects_unknown_root_path() -> None:
    state = AnalyzerState()

    with pytest.raises(ValueError, match="unknown root"):
        _apply_state_update(state, ("surprise_by_circuit", "fridge"), 1.0)

    assert not hasattr(state, "surprise_by_circuit")


def test_apply_state_update_rejects_non_dict_intermediate_path() -> None:
    state = AnalyzerState()
    state.learning_by_circuit["fridge"] = True

    with pytest.raises(TypeError, match="not a mapping"):
        _apply_state_update(
            state,
            ("learning_by_circuit", "fridge", "nested"),
            False,
        )

    assert state.learning_by_circuit == {"fridge": True}


def test_apply_state_update_names_bad_intermediate_segment() -> None:
    state = AnalyzerState()
    state.learning_by_circuit["fridge"] = True

    with pytest.raises(TypeError, match="fridge"):
        _apply_state_update(
            state,
            ("learning_by_circuit", "fridge", "nested", "leaf"),
            False,
        )


def test_apply_state_update_rejects_root_replacement() -> None:
    state = AnalyzerState()

    with pytest.raises(ValueError, match="destination key"):
        _apply_state_update(state, ("learning_by_circuit",), {"fridge": True})

    assert state.learning_by_circuit == {}


def test_apply_state_update_allows_known_state_dictionary_root() -> None:
    state = AnalyzerState()

    _apply_state_update(state, ("learning_by_circuit", "fridge"), True)

    assert state.learning_by_circuit == {"fridge": True}


def _settings_recommendation(advisor: Any, **overrides: Any) -> Any:
    values = {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "unique_key": "hvac:daily_spike_ratio",
        "circuit_id": "hvac",
        "circuit_name": "HVAC",
        "setting_key": "daily_spike_ratio",
        "setting_label": "Daily Spike Ratio",
        "current_value": 0.25,
        "suggested_value": 0.3,
        "unit": "ratio",
        "feature": "energy_usage_spikes",
        "group": "Energy Usage",
        "confidence": 0.78,
        "reason": "Observed 7 complete days of energy usage.",
        "evidence": {"observed_days": 7, "p95_daily_kwh": 9.8},
        "apply_payload": {"daily_spike_ratio": 0.3},
        "status": advisor.RecommendationStatus.PENDING,
        "created_at": datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return advisor.SettingRecommendation(**values)


def _hass_with_states(
    states: dict[str, Any],
    *,
    now: datetime,
) -> SimpleNamespace:
    class FakeStates:
        def get(self, entity_id: str) -> Any:
            value = states.get(entity_id)
            if value is None:
                return None
            if isinstance(value, tuple):
                state, changed_minutes = value
                return SimpleNamespace(
                    state=str(state),
                    attributes={},
                    last_changed=now - timedelta(minutes=changed_minutes),
                    last_updated=now,
                )
            return SimpleNamespace(
                state=str(value),
                attributes={},
                last_changed=now,
                last_updated=now,
            )

    return SimpleNamespace(states=FakeStates(), config=SimpleNamespace())


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


def test_processing_context_uses_home_assistant_time_zone() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(time_zone="America/New_York"),
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={},
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )

    context = coordinator._build_processing_context(now)

    assert context.time_zone == "America/New_York"


def test_coordinator_refreshes_rain_pump_context_from_rain_and_hvac() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        _hass_with_states(
            {
                "binary_sensor.rain": "on",
                "sensor.precipitation_rate": "0.35",
            },
            now=now,
        ),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "sump_pump",
                    "name": "Sump Pump",
                    "appliance_profile": "sump_pump",
                    "mode": "single_phase",
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC Compressor",
                    "appliance_profile": "hvac_compressor",
                    "mode": "dual_phase",
                },
            ],
            CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain",
            CONF_RAIN_INTENSITY_ENTITY: "sensor.precipitation_rate",
            CONF_ADVANCED_SETTINGS: {
                "sump_pump": {
                    CONF_RAIN_PUMP_CORRELATION_ENABLED: True,
                    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT: 25.0,
                }
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "pump_runtime_minutes": 6.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 27 * 60
    coordinator.state.run_cycle_runtime_seconds_by_circuit["hvac"] = 32 * 60
    coordinator.state.run_cycle_duty_cycle_by_circuit["hvac"] = 55.0

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.rain_pump_context_by_circuit["sump_pump"]
    assert evidence["status"] == "weather_explained"
    assert evidence["expected_runtime_minutes"] == pytest.approx(26.8)
    assert evidence["hvac_compressor_runtime_minutes"] == 32.0


def test_coordinator_normalizes_rain_intensity_units_to_mm_per_hour() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str) -> Any:
            values = {
                "binary_sensor.rain": ("on", {}),
                "sensor.precipitation_rate": (
                    "0.02",
                    {"unit_of_measurement": "in/h"},
                ),
            }
            value = values.get(entity_id)
            if value is None:
                return None
            state, attributes = value
            return SimpleNamespace(
                state=state,
                attributes=attributes,
                last_changed=now,
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), config=SimpleNamespace()),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "sump_pump",
                    "name": "Sump Pump",
                    "appliance_profile": "sump_pump",
                    "mode": "single_phase",
                }
            ],
            CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain",
            CONF_RAIN_INTENSITY_ENTITY: "sensor.precipitation_rate",
            CONF_ADVANCED_SETTINGS: {
                "sump_pump": {CONF_RAIN_PUMP_CORRELATION_ENABLED: True}
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "pump_runtime_minutes": 6.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 18 * 60

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.rain_pump_context_by_circuit["sump_pump"]
    assert evidence["rain_intensity_per_hour"] == 0.02
    assert evidence["rain_intensity_unit"] == "in/h"
    assert evidence["rain_intensity_mm_per_hour"] == pytest.approx(0.508)
    assert evidence["rain_intensity_bin"] == "heavy"
    assert evidence["baseline_context"] == "heavy_rain, heavy"
    assert evidence["rain_context_issues"] == []


def test_coordinator_marks_positive_rain_intensity_with_missing_unit_unknown() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str) -> Any:
            if entity_id != "sensor.precipitation_rate":
                return None
            return SimpleNamespace(
                state="0.35",
                attributes={},
                last_changed=now,
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), config=SimpleNamespace()),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "sump_pump",
                    "name": "Sump Pump",
                    "appliance_profile": "sump_pump",
                    "mode": "single_phase",
                }
            ],
            CONF_RAIN_INTENSITY_ENTITY: "sensor.precipitation_rate",
            CONF_ADVANCED_SETTINGS: {
                "sump_pump": {CONF_RAIN_PUMP_CORRELATION_ENABLED: True}
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "pump_runtime_minutes": 6.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 7 * 60

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.rain_pump_context_by_circuit["sump_pump"]
    assert evidence["rain_sensor_active"] is None
    assert evidence["rain_intensity_per_hour"] == 0.35
    assert evidence["rain_intensity_unit"] is None
    assert evidence["rain_intensity_mm_per_hour"] is None
    assert evidence["rain_intensity_bin"] == "unknown"
    assert evidence["baseline_context"] == "unknown"
    assert evidence["baseline_fallback_level"] == "unknown_rain_context"
    assert evidence["rain_context_issues"] == ["rain_intensity_unit_missing"]


def test_coordinator_refreshes_water_flow_context_for_flow_without_load() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        _hass_with_states({"binary_sensor.water_flow": ("on", 14)}, now=now),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                }
            ],
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"],
            CONF_ADVANCED_SETTINGS: {
                "washer": {
                    CONF_WATER_FLOW_CORRELATION_ENABLED: True,
                    CONF_LINKED_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"],
                    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES: 5,
                }
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "washer": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "flow_status": "normal",
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.water_flow_context_by_circuit["washer"]
    assert evidence["status"] == "possible_flow_without_load"
    assert evidence["mismatch_minutes"] == 14.0
    assert evidence["flow_sensor_entities"] == ["binary_sensor.water_flow"]


def test_coordinator_treats_positive_numeric_flow_sensor_as_active() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        _hass_with_states({"sensor.water_flow_rate": ("1.25", 9)}, now=now),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                }
            ],
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
            CONF_ADVANCED_SETTINGS: {
                "washer": {
                    CONF_WATER_FLOW_CORRELATION_ENABLED: True,
                    CONF_LINKED_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
                    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES: 5,
                }
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "washer": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "flow_status": "normal",
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.water_flow_context_by_circuit["washer"]
    assert evidence["status"] == "possible_flow_without_load"
    assert evidence["flow_active_minutes"] == 9.0
    assert evidence["mismatch_minutes"] == 9.0
    assert evidence["flow_sensor_entities"] == ["sensor.water_flow_rate"]


def test_coordinator_treats_zero_numeric_flow_sensor_as_inactive() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        _hass_with_states({"sensor.water_flow_rate": ("0", 9)}, now=now),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                }
            ],
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
            CONF_ADVANCED_SETTINGS: {
                "washer": {
                    CONF_WATER_FLOW_CORRELATION_ENABLED: True,
                    CONF_LINKED_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
                    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES: 5,
                }
            },
        },
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "washer": [
                    {
                        "timestamp": (
                            now - timedelta(days=index + 1)
                        ).isoformat(),
                        "flow_status": "normal",
                    }
                    for index in range(12)
                ]
            }
        ),
        now_fn=lambda: now,
    )

    coordinator._refresh_water_context_state(coordinator.circuit_configs[0], now)

    evidence = coordinator.state.water_flow_context_by_circuit["washer"]
    assert evidence["flow_active_minutes"] == 0.0
    assert evidence["status"] == "normal"


def test_coordinator_exposes_source_update_manager() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.managers.source_updates import (
        SourceUpdateManager,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert isinstance(coordinator.source_updates, SourceUpdateManager)
    assert coordinator.source_entities == ()


def test_coordinator_exposes_store_persistence_manager() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        store_persistence,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert isinstance(
        coordinator.store_persistence,
        store_persistence.StorePersistenceManager,
    )
    assert coordinator._store_dirty is False


def test_coordinator_exposes_notification_controller() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        notification_controller,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert isinstance(
        coordinator.notification_controller,
        notification_controller.NotificationController,
    )
    assert coordinator._notified_alert_ids == set()


def test_coordinator_exposes_setup_health_aggregator() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        setup_health,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert isinstance(
        coordinator.setup_health,
        setup_health.SetupHealthAggregator,
    )
    assert coordinator._active_repair_issues == set()


def test_coordinator_exposes_nilm_controller() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        nilm_controller,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert isinstance(
        coordinator.nilm_controller,
        nilm_controller.NilmController,
    )


def test_nilm_controller_exposes_assignment_edit_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert callable(coordinator.nilm_controller.async_rename_nilm_appliance)
    assert callable(coordinator.nilm_controller.async_change_nilm_appliance_profile)
    assert callable(coordinator.nilm_controller.async_merge_nilm_assignments)


def test_nilm_controller_exposes_label_and_assignment_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert callable(coordinator.nilm_controller.async_label_nilm_signature)
    assert callable(coordinator.nilm_controller.async_label_nilm_interval)
    assert callable(coordinator.nilm_controller.async_delete_nilm_label_interval)
    assert callable(coordinator.nilm_controller.async_assign_nilm_signature)
    assert callable(coordinator.nilm_controller.async_assign_nilm_session)
    assert callable(coordinator.nilm_controller.async_assign_nilm_interval)


def test_nilm_controller_exposes_session_validation_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert callable(coordinator.nilm_controller.async_validate_nilm_session)
    assert callable(coordinator.nilm_controller.async_reject_nilm_session)
    assert callable(coordinator.nilm_controller.assignment_for_session)


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
async def test_coordinator_coalesces_rapid_source_state_changes(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    callbacks = []
    process_calls = 0

    def fake_track_state_change_event(hass, entity_ids, callback):
        callbacks.append(callback)
        return lambda: None

    async def fake_process_update(self):
        nonlocal process_calls
        process_calls += 1
        return self.state

    monkeypatch.setattr(
        coordinator_module,
        "async_track_state_change_event",
        fake_track_state_change_event,
    )
    monkeypatch.setattr(
        coordinator_module,
        "SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        coordinator_module.EnergyAnalyzerCoordinator,
        "async_process_update",
        fake_process_update,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())
    await coordinator.async_start(["sensor.fridge_power"])

    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_power"}))
    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_current"}))
    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_var"}))
    for _ in range(20):
        if process_calls:
            break
        await asyncio.sleep(0.01)

    assert process_calls == 1
    assert coordinator.pending_source_update_entities == ()
    assert coordinator.last_source_update_entities == (
        "sensor.fridge_current",
        "sensor.fridge_power",
        "sensor.fridge_var",
    )


@pytest.mark.asyncio
async def test_coordinator_reschedules_source_update_added_during_processing(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    callbacks = []
    process_calls = 0
    first_update_started = asyncio.Event()
    release_first_update = asyncio.Event()

    def fake_track_state_change_event(hass, entity_ids, callback):
        callbacks.append(callback)
        return lambda: None

    async def fake_process_update(self):
        nonlocal process_calls
        process_calls += 1
        if process_calls == 1:
            first_update_started.set()
            await release_first_update.wait()
        return self.state

    monkeypatch.setattr(
        coordinator_module,
        "async_track_state_change_event",
        fake_track_state_change_event,
    )
    monkeypatch.setattr(
        coordinator_module,
        "SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        coordinator_module.EnergyAnalyzerCoordinator,
        "async_process_update",
        fake_process_update,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())
    await coordinator.async_start(["sensor.fridge_power"])

    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_power"}))
    await asyncio.wait_for(first_update_started.wait(), timeout=1)

    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_current"}))
    assert coordinator.pending_source_update_entities == ("sensor.fridge_current",)

    release_first_update.set()
    await asyncio.sleep(0.05)

    assert process_calls == 2
    assert coordinator.pending_source_update_entities == ()
    assert coordinator.last_source_update_entities == ("sensor.fridge_current",)


@pytest.mark.asyncio
async def test_coordinator_stop_cancels_pending_source_state_update(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    callbacks = []
    process_calls = 0

    def fake_track_state_change_event(hass, entity_ids, callback):
        callbacks.append(callback)
        return lambda: None

    async def fake_process_update(self):
        nonlocal process_calls
        process_calls += 1
        return self.state

    monkeypatch.setattr(
        coordinator_module,
        "async_track_state_change_event",
        fake_track_state_change_event,
    )
    monkeypatch.setattr(
        coordinator_module,
        "SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS",
        5.0,
    )
    monkeypatch.setattr(
        coordinator_module.EnergyAnalyzerCoordinator,
        "async_process_update",
        fake_process_update,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(SimpleNamespace())
    await coordinator.async_start(["sensor.fridge_power"])
    await callbacks[0](SimpleNamespace(data={"entity_id": "sensor.fridge_power"}))

    await coordinator.async_stop()
    await asyncio.sleep(0)

    assert process_calls == 0
    assert coordinator.pending_source_update_entities == ()
    assert coordinator.last_source_update_entities == ()


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
async def test_migrate_entry_canonicalizes_legacy_sensitivity_values() -> None:
    from custom_components.circuitsetup_energy_analyzer import async_migrate_entry

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.updates = []

        def async_update_entry(self, entry, **kwargs) -> None:
            self.updates.append((entry, kwargs))
            entry.data = MappingProxyType(kwargs.get("data", entry.data))
            entry.options = MappingProxyType(kwargs.get("options", entry.options))

    hass = SimpleNamespace(config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        data=MappingProxyType(
            {
                CONF_SENSITIVITY: "low",
                CONF_ADVANCED_SETTINGS: MappingProxyType(
                    {"freezer": MappingProxyType({"preset": "standard"})}
                ),
            }
        ),
        options=MappingProxyType(
            {
                CONF_SENSITIVITY: "high",
                CONF_ADVANCED_SETTINGS: MappingProxyType(
                    {"dryer": MappingProxyType({"preset": "high"})}
                ),
            }
        ),
    )

    assert await async_migrate_entry(hass, entry) is True

    assert hass.config_entries.updates == [
        (
            entry,
            {
                "data": {
                    CONF_SENSITIVITY: "quiet",
                    CONF_ADVANCED_SETTINGS: {"freezer": {"preset": "balanced"}},
                },
                "options": {
                    CONF_SENSITIVITY: "sensitive",
                    CONF_ADVANCED_SETTINGS: {"dryer": {"preset": "sensitive"}},
                    CONF_ENTITY_MODEL_VERSION: ENTITY_MODEL_LEGACY,
                },
            },
        )
    ]
    assert entry.data[CONF_SENSITIVITY] == "quiet"
    assert entry.options[CONF_SENSITIVITY] == "sensitive"


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
async def test_setup_entry_listens_to_outdoor_temperature_entity() -> None:
    from custom_components.circuitsetup_energy_analyzer import async_setup_entry

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            return True

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_SOURCE_ENTITIES: ["sensor.hvac_power"],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
        },
    )

    assert await async_setup_entry(hass, entry) is True

    coordinator = hass.data[DOMAIN]["entry-1"]
    assert coordinator.source_entities == (
        "sensor.hvac_power",
        "sensor.outdoor_temperature",
    )


def test_coordinator_imports_configured_utility_and_advanced_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                },
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [],
                },
            ],
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "mains": {
                    "utility_energy_entity": "sensor.opower_current_bill_usage",
                    "utility_statistic_id": "opower:utility_elec_consumption",
                    "utility_source_type": "statistics",
                    "utility_statistic_period": "day",
                    "measured_energy_entities": ["sensor.panel_import_energy"],
                    "tolerance_percent": 8.5,
                },
            },
            CONF_ADVANCED_SETTINGS: {
                "refrigerator": {
                    "preset": "high",
                    "operating_on_threshold_w": 30.0,
                    "operating_off_threshold_w": 12.0,
                    "operating_on_dwell_seconds": 14.0,
                    "operating_off_dwell_seconds": 50.0,
                    "operating_merge_gap_seconds": 95.0,
                    "window_days": 14,
                    "daily_spike_ratio": 0.35,
                    "daily_goal_kwh": 2.5,
                    "goal_alert_ratio": 0.9,
                    "max_active_minutes": 120,
                    "max_idle_minutes": 480,
                    "cycle_start_day": 15,
                    "budget_kwh": 90.0,
                    "budget_alert_ratio": 0.85,
                    "min_elapsed_days": 5,
                    "default_rate_per_kwh": 0.18,
                    "tou_rate_per_kwh": 0.42,
                    "tou_start": "16:00",
                    "tou_end": "21:00",
                    "tou_weekdays": "0,1,2,3,4",
                    "tou_name": "Peak",
                    "window_minutes": 30,
                    "demand_limit_w": 1200.0,
                    "breaker_amps": 20.0,
                    "warning_ratio": 0.8,
                    "window_hours": 72,
                    "standby_threshold_w": 6.0,
                    "always_on_alert_w": 12.0,
                    "min_samples": 36,
                    "leg_imbalance_warning_ratio": 0.4,
                    "leg_imbalance_min_total_power_w": 800.0,
                    "apparent_power_tolerance_percent": 12.0,
                    "power_factor_tolerance": 0.08,
                    "minimum_apparent_power_va": 120.0,
                    "balance_negative_tolerance_w": 250.0,
                    "solar_export_tolerance_w": 150.0,
                    "solar_surplus_threshold_w": 750.0,
                    "high_solar_surplus_threshold_w": 2000.0,
                    "flexible_load_running_threshold_w": 175.0,
                },
            },
        },
    )

    assert coordinator.store_data.utility_comparison_settings_by_circuit["mains"] == {
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_type": "statistics",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 8.5,
    }
    assert coordinator.store_data.sensitivity_by_circuit["refrigerator"] == "sensitive"
    assert coordinator.store_data.operating_detection_settings_by_circuit[
        "refrigerator"
    ] == {
        "operating_on_threshold_w": 30.0,
        "operating_off_threshold_w": 12.0,
        "operating_on_dwell_seconds": 14.0,
        "operating_off_dwell_seconds": 50.0,
        "operating_merge_gap_seconds": 95.0,
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit[
        "refrigerator"
    ] == {
        "window_days": 14,
        "daily_spike_ratio": 0.35,
    }
    assert coordinator.store_data.energy_goal_settings_by_circuit["refrigerator"] == {
        "daily_goal_kwh": 2.5,
        "goal_alert_ratio": 0.9,
    }
    assert coordinator.store_data.activity_alert_settings_by_circuit[
        "refrigerator"
    ] == {
        "max_active_minutes": 120,
        "max_idle_minutes": 480,
    }
    assert coordinator.store_data.billing_settings_by_circuit["refrigerator"] == {
        "cycle_start_day": 15,
        "budget_kwh": 90.0,
        "budget_alert_ratio": 0.85,
        "min_elapsed_days": 5,
    }
    assert coordinator.store_data.cost_settings_by_circuit["refrigerator"] == {
        "cycle_start_day": 15,
        "default_rate_per_kwh": 0.18,
        "tou_rate_per_kwh": 0.42,
        "tou_start": "16:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,1,2,3,4",
        "tou_name": "Peak",
    }
    assert coordinator.store_data.demand_settings_by_circuit["refrigerator"] == {
        "window_minutes": 30,
        "demand_limit_w": 1200.0,
    }
    assert coordinator.store_data.capacity_settings_by_circuit["refrigerator"] == {
        "breaker_amps": 20.0,
        "warning_ratio": 0.8,
    }
    assert coordinator.store_data.standby_settings_by_circuit["refrigerator"] == {
        "window_hours": 72,
        "standby_threshold_w": 6.0,
        "always_on_alert_w": 12.0,
        "min_samples": 36,
    }
    assert coordinator.store_data.leg_imbalance_settings_by_circuit[
        "refrigerator"
    ] == {
        "warning_ratio": 0.4,
        "minimum_total_power_w": 800.0,
    }
    assert coordinator.store_data.metric_consistency_settings_by_circuit[
        "refrigerator"
    ] == {
        "apparent_power_tolerance_percent": 12.0,
        "power_factor_tolerance": 0.08,
        "minimum_apparent_power_va": 120.0,
    }
    assert coordinator.store_data.balance_settings_by_circuit["refrigerator"] == {
        "negative_tolerance_w": 250.0,
    }
    assert coordinator.store_data.solar_flow_settings_by_circuit["refrigerator"] == {
        "export_tolerance_w": 150.0,
        "solar_surplus_threshold_w": 750.0,
        "high_solar_surplus_threshold_w": 2000.0,
        "flexible_load_running_threshold_w": 175.0,
    }


def test_coordinator_replaces_store_advanced_settings_after_section_reset() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
        options={
            CONF_ADVANCED_SETTINGS: {
                "refrigerator": {
                    "preset": "balanced",
                    "standby_threshold_w": 7.0,
                }
            },
        },
        store_data=FeatureStoreData(
            sensitivity_by_circuit={
                "refrigerator": "sensitive",
                "freezer": "quiet",
            },
            operating_detection_settings_by_circuit={
                "refrigerator": {"operating_off_threshold_w": 10.0},
                "freezer": {"operating_off_threshold_w": 8.0},
            },
            energy_usage_settings_by_circuit={
                "refrigerator": {"daily_spike_ratio": 0.35},
                "freezer": {"daily_spike_ratio": 0.4},
            },
            standby_settings_by_circuit={
                "refrigerator": {"standby_threshold_w": 6.0},
                "freezer": {"standby_threshold_w": 5.0},
            },
        ),
    )

    assert coordinator.store_data.sensitivity_by_circuit == {
        "refrigerator": "balanced",
        "freezer": "quiet",
    }
    assert coordinator.store_data.operating_detection_settings_by_circuit == {
        "freezer": {"operating_off_threshold_w": 8.0},
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit == {
        "freezer": {"daily_spike_ratio": 0.4},
    }
    assert coordinator.store_data.standby_settings_by_circuit == {
        "refrigerator": {"standby_threshold_w": 7.0},
        "freezer": {"standby_threshold_w": 5.0},
    }


def test_coordinator_clears_store_advanced_settings_after_full_reset() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "refrigerator",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
        options={CONF_ADVANCED_SETTINGS: {"refrigerator": {}}},
        store_data=FeatureStoreData(
            sensitivity_by_circuit={
                "refrigerator": "sensitive",
                "freezer": "quiet",
            },
            operating_detection_settings_by_circuit={
                "refrigerator": {"operating_off_threshold_w": 10.0},
            },
            energy_usage_settings_by_circuit={
                "refrigerator": {"daily_spike_ratio": 0.35},
                "freezer": {"daily_spike_ratio": 0.4},
            },
            energy_goal_settings_by_circuit={
                "refrigerator": {"daily_goal_kwh": 2.5},
            },
            activity_alert_settings_by_circuit={
                "refrigerator": {"max_active_minutes": 120},
            },
            billing_settings_by_circuit={
                "refrigerator": {"budget_kwh": 90.0},
            },
            cost_settings_by_circuit={
                "refrigerator": {"default_rate_per_kwh": 0.18},
            },
            demand_settings_by_circuit={
                "refrigerator": {"demand_limit_w": 1200.0},
            },
            capacity_settings_by_circuit={
                "refrigerator": {"warning_ratio": 0.8},
            },
            standby_settings_by_circuit={
                "refrigerator": {"standby_threshold_w": 6.0},
            },
            leg_imbalance_settings_by_circuit={
                "refrigerator": {"warning_ratio": 0.4},
            },
            metric_consistency_settings_by_circuit={
                "refrigerator": {"power_factor_tolerance": 0.08},
            },
            balance_settings_by_circuit={
                "refrigerator": {"negative_tolerance_w": 250.0},
            },
            solar_flow_settings_by_circuit={
                "refrigerator": {"solar_surplus_threshold_w": 750.0},
            },
        ),
    )

    assert coordinator.store_data.sensitivity_by_circuit == {"freezer": "quiet"}
    assert coordinator.store_data.energy_usage_settings_by_circuit == {
        "freezer": {"daily_spike_ratio": 0.4},
    }
    assert (
        "refrigerator"
        not in coordinator.store_data.operating_detection_settings_by_circuit
    )
    assert "refrigerator" not in coordinator.store_data.energy_goal_settings_by_circuit
    assert (
        "refrigerator"
        not in coordinator.store_data.activity_alert_settings_by_circuit
    )
    assert "refrigerator" not in coordinator.store_data.billing_settings_by_circuit
    assert "refrigerator" not in coordinator.store_data.cost_settings_by_circuit
    assert "refrigerator" not in coordinator.store_data.demand_settings_by_circuit
    assert "refrigerator" not in coordinator.store_data.capacity_settings_by_circuit
    assert "refrigerator" not in coordinator.store_data.standby_settings_by_circuit
    assert (
        "refrigerator"
        not in coordinator.store_data.leg_imbalance_settings_by_circuit
    )
    assert (
        "refrigerator"
        not in coordinator.store_data.metric_consistency_settings_by_circuit
    )
    assert "refrigerator" not in coordinator.store_data.balance_settings_by_circuit
    assert "refrigerator" not in coordinator.store_data.solar_flow_settings_by_circuit


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
    notification_kwargs: list[dict[str, object]] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        notifications.append(alert)
        notification_kwargs.append(kwargs)

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

    assert "fridge" not in coordinator.state.last_event_by_circuit
    assert coordinator.state.operating_state_by_circuit["fridge"] == "running"
    assert coordinator.state.learning_by_circuit["fridge"] is False
    assert coordinator.state.anomaly_score_by_circuit["fridge"] > 0.5
    assert coordinator.state.active_alerts_by_circuit["fridge"]
    assert notifications
    assert notifications[0].message.startswith("Possible issue")
    assert notification_kwargs[0].get("config").circuit_id == "fridge"


@pytest.mark.asyncio
async def test_runtime_tracks_latest_real_power_for_running_binary_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.washer_power"
            return SimpleNamespace(
                state="35",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "mode": "single_phase",
                    "appliance_profile": "washer",
                    "sensors": [
                        {
                            "entity_id": "sensor.washer_power",
                            "role": "real_power",
                            "unit": "W",
                        }
                    ],
                    "retention_mode": RetentionMode.STANDARD.value,
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.latest_real_power_w_by_circuit == {"washer": 35.0}


@pytest.mark.asyncio
async def test_runtime_tracks_config_metadata_for_dashboard_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.solar_power"
            return SimpleNamespace(
                state="-1200",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "name": "Solar Inverter",
                    "mode": "dual_phase",
                    "appliance_profile": "solar_inverter",
                    "power_flow": "generation",
                    "sensors": [
                        {
                            "entity_id": "sensor.solar_power",
                            "role": "real_power",
                            "unit": "W",
                        }
                    ],
                    "retention_mode": RetentionMode.STANDARD.value,
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.circuit_mode_by_circuit == {
        "solar": "Dual Phase",
    }
    assert coordinator.state.power_flow_by_circuit == {
        "solar": "Generation / Solar Export",
    }


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
        == "Possible issue: Cycle Duration"
    )
    assert coordinator.state.recent_activity_count_by_circuit["fridge"] == 2
    assert coordinator.state.recent_activity_timeline_by_circuit["fridge"] == {
        "status": "activity",
        "window_hours": 24,
        "total_count": 2,
        "event_count": 1,
        "alert_count": 1,
        "observation_count": 0,
        "latest_title": "Possible issue: Cycle Duration",
        "latest_timestamp": alert.timestamp.isoformat(),
        "items": [
            {
                "timestamp": alert.timestamp.isoformat(),
                "kind": "alert",
                "title": "Possible issue: Cycle Duration",
                "detail": "Possible issue: Fridge cycle duration changed.",
                "severity": "warning",
                "feature": "cycle_duration",
                "feature_name": "Cycle Duration",
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
async def test_runtime_retains_recent_observations_across_refreshes() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.alerting import Observation
    from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    now_holder = {"value": datetime(2026, 6, 18, 12, 0, tzinfo=UTC)}

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_power"
            return SimpleNamespace(
                state="5",
                attributes={"unit_of_measurement": "W"},
                last_updated=now_holder["value"],
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
                            "unit": "W",
                        }
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(),
        now_fn=lambda: now_holder["value"],
    )
    observation = Observation(
        circuit_id="fridge",
        feature="cycle_duration",
        score=1.8,
        baseline_confidence=0.9,
        observed_at=now_holder["value"],
        observed_value=45.0,
        baseline_value=30.0,
        message="Fridge ran longer than usual.",
    )

    await coordinator._apply_feature_result(
        FeatureResult(observations=[observation]),
    )
    now_holder["value"] = now_holder["value"] + timedelta(minutes=1)
    await coordinator.async_process_update()

    assert (
        coordinator.state.health_summary_by_circuit["fridge"]
        == "Observation recorded"
    )
    assert coordinator.state.recent_activity_timeline_by_circuit["fridge"] == {
        "status": "activity",
        "window_hours": 24,
        "total_count": 1,
        "event_count": 0,
        "alert_count": 0,
        "observation_count": 1,
        "latest_title": "Observation: Cycle Duration",
        "latest_timestamp": observation.observed_at.isoformat(),
        "items": [
            {
                "timestamp": observation.observed_at.isoformat(),
                "kind": "observation",
                "title": "Observation: Cycle Duration",
                "detail": "Fridge ran longer than usual.",
                "severity": "info",
                "feature": "cycle_duration",
                "feature_name": "Cycle Duration",
                "event_type": None,
                "observed_value": 45.0,
                "baseline_value": 30.0,
                "change_ratio": None,
                "repeated_count": None,
            }
        ],
    }


def test_refresh_alert_evidence_state_includes_graph_metadata_from_config() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 30, tzinfo=UTC)
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="reactive_to_real_ratio",
        observed_value=0.42,
        baseline_value=0.24,
        change_ratio=0.75,
        first_seen=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
        last_seen=now,
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
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.fridge_reactive_power",
                            "role": "reactive_power",
                        },
                        {
                            "entity_id": "sensor.fridge_power_factor",
                            "role": "power_factor",
                        },
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(alerts=[alert]),
        now_fn=lambda: now,
    )

    coordinator._refresh_alert_evidence_state("fridge")

    detail = coordinator.state.alert_evidence_by_circuit["fridge"]
    assert detail["graph_entities"] == [
        "sensor.fridge_reactive_power",
        "sensor.fridge_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["source_entities"] == [
        "sensor.fridge_power",
        "sensor.fridge_reactive_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["graph_window_start"] == "2026-06-02T08:00:00+00:00"
    assert detail["graph_window_end"] == "2026-06-02T14:30:00+00:00"


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

    async def fake_notification(hass, alert, **kwargs) -> None:
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


def test_runtime_retention_prunes_contextual_baseline_samples() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    old_sample = {
        "timestamp": (now - timedelta(days=30)).isoformat(),
        "feature": "daily_energy_kwh",
        "value": 7.5,
        "context": {"season": "spring"},
        "source": "test",
    }
    recent_sample = {
        "timestamp": (now - timedelta(days=2)).isoformat(),
        "feature": "daily_energy_kwh",
        "value": 8.5,
        "context": {"season": "summer"},
        "source": "test",
    }
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "single_phase",
                    "appliance_profile": "hvac",
                    "retention_mode": RetentionMode.LIGHTWEIGHT.value,
                    "sensors": [],
                }
            ],
        },
        store_data=FeatureStoreData(
            contextual_baseline_samples_by_circuit={
                "hvac": [old_sample, recent_sample]
            }
        ),
        now_fn=lambda: now,
    )

    coordinator._apply_retention(now)

    assert coordinator.store_data.contextual_baseline_samples_by_circuit == {
        "hvac": [recent_sample]
    }


def test_runtime_retention_prunes_daily_rows_by_ha_local_date() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 15, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "retention_mode": RetentionMode.LIGHTWEIGHT.value,
                    "sensors": [],
                }
            ],
        },
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "fridge": {
                    "days": [
                        {"date": "2026-05-30", "usage_kwh": 6.0},
                        {"date": "2026-05-31", "usage_kwh": 7.0},
                    ],
                }
            },
            demand_by_circuit={
                "fridge": {
                    "daily_peaks": [
                        {"date": "2026-05-30", "peak_demand_w": 1000.0},
                        {"date": "2026-05-31", "peak_demand_w": 1200.0},
                    ],
                }
            },
        ),
        now_fn=lambda: now,
    )

    coordinator._apply_retention(now)

    assert coordinator.store_data.energy_usage_by_circuit["fridge"]["days"] == [
        {"date": "2026-05-31", "usage_kwh": 7.0}
    ]
    assert coordinator.store_data.demand_by_circuit["fridge"]["daily_peaks"] == [
        {"date": "2026-05-31", "peak_demand_w": 1200.0}
    ]


def test_runtime_caps_growing_persisted_alert_and_feedback_structures() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        ALERT_FEEDBACK_MAX_ITEMS,
        ALERT_HISTORY_MAX_ITEMS,
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    alerts = [
        AlertEvidence(
            timestamp=now - timedelta(hours=index),
            circuit_id="fridge",
            severity=Severity.WARNING,
            message=f"Possible issue {index}",
            feature="real_power",
        )
        for index in range(ALERT_HISTORY_MAX_ITEMS + 25)
    ]
    feedback = {
        f"fridge:real_power:{index}": {
            "action": "expected",
            "created_at": (now - timedelta(hours=index)).isoformat(),
        }
        for index in range(ALERT_FEEDBACK_MAX_ITEMS + 25)
    }
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        store_data=FeatureStoreData(alerts=alerts, alert_feedback=feedback),
        now_fn=lambda: now,
    )

    coordinator._apply_retention(now)

    assert len(coordinator.store_data.alerts) == ALERT_HISTORY_MAX_ITEMS
    assert coordinator.store_data.alerts[0].message == "Possible issue 0"
    assert len(coordinator.store_data.alert_feedback) == ALERT_FEEDBACK_MAX_ITEMS
    assert "fridge:real_power:0" in coordinator.store_data.alert_feedback
    assert (
        f"fridge:real_power:{ALERT_FEEDBACK_MAX_ITEMS + 24}"
        not in coordinator.store_data.alert_feedback
    )


@pytest.mark.asyncio
async def test_expected_alert_feedback_suppresses_matching_future_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
    )

    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    previous_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_spike",
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
    )
    repeated_alert = AlertEvidence(
        timestamp=now + timedelta(days=1),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue again",
        feature="daily_energy_spike",
        observed_value=2.64,
        baseline_value=2.0,
        change_ratio=0.32,
    )
    fingerprint = alert_feedback_fingerprint(previous_alert)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            alert_feedback={
                fingerprint: {
                    "fingerprint": fingerprint,
                    "status": "expected",
                    "action": "expected",
                    "decided_at": now.isoformat(),
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=90)).isoformat(),
                    "circuit_id": "fridge",
                    "feature": "daily_energy_spike",
                }
            }
        ),
        now_fn=lambda: now + timedelta(days=1),
    )

    _, active_alerts = await coordinator._apply_feature_result(
        FeatureResult(alerts=[repeated_alert], notifications=[repeated_alert])
    )

    assert notifications == []
    assert active_alerts == []
    assert len(coordinator.store_data.alerts) == 1
    stored_alert = coordinator.store_data.alerts[0]
    assert stored_alert.feedback_status == "expected"
    assert stored_alert.matching_feedback_fingerprint == fingerprint
    assert stored_alert.feedback_effect == (
        "Notifications suppressed for this expected pattern"
    )


@pytest.mark.asyncio
async def test_expected_alert_feedback_does_not_suppress_unrelated_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
    )

    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    expected_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_spike",
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
    )
    unrelated_alert = AlertEvidence(
        timestamp=now + timedelta(days=1),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="standby_power",
        observed_value=40.0,
        baseline_value=10.0,
        change_ratio=3.0,
    )
    fingerprint = alert_feedback_fingerprint(expected_alert)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            alert_feedback={
                fingerprint: {
                    "fingerprint": fingerprint,
                    "status": "expected",
                    "action": "expected",
                    "decided_at": now.isoformat(),
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=90)).isoformat(),
                    "circuit_id": "fridge",
                    "feature": "daily_energy_spike",
                }
            }
        ),
        now_fn=lambda: now + timedelta(days=1),
    )

    _, active_alerts = await coordinator._apply_feature_result(
        FeatureResult(alerts=[unrelated_alert], notifications=[unrelated_alert])
    )

    assert active_alerts == [unrelated_alert]
    assert notifications == [unrelated_alert]
    assert coordinator.store_data.alerts == [unrelated_alert]


def test_unhelpful_feedback_raises_future_alert_requirement() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        Observation,
        alert_feedback_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    prior_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_usage_spike",
        observed_value=2.6,
        baseline_value=2.0,
        change_ratio=0.3,
    )
    fingerprint = alert_feedback_fingerprint(prior_alert)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            alert_feedback={
                fingerprint: {
                    "fingerprint": fingerprint,
                    "status": "unhelpful",
                    "action": "unhelpful",
                    "decided_at": now.isoformat(),
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=45)).isoformat(),
                    "circuit_id": "fridge",
                    "feature": "daily_energy_usage_spike",
                }
            }
        ),
        now_fn=lambda: now + timedelta(days=1),
    )
    policy = coordinator._usage_alert_policy_for_circuit("fridge")

    for index in range(4):
        assert (
            policy.observe(
                Observation(
                    circuit_id="fridge",
                    feature="daily_energy_usage_spike",
                    score=1.6,
                    baseline_confidence=1.0,
                    observed_at=now + timedelta(hours=index),
                    observed_value=2.61,
                    baseline_value=2.0,
                )
            )
            is None
        )

    alert = policy.observe(
        Observation(
            circuit_id="fridge",
            feature="daily_energy_usage_spike",
            score=1.6,
            baseline_confidence=1.0,
            observed_at=now + timedelta(hours=4),
            observed_value=2.62,
            baseline_value=2.0,
        )
    )

    assert alert is not None
    assert alert.repeated_count == 5
    assert alert.adjusted_min_repeated == 5


def test_runtime_caps_nilm_inventory_and_recommendation_history() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        settings_advisor as advisor,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        NILM_SESSION_HISTORY_MAX_AGE,
        NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
        NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT,
        NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT,
        RECOMMENDATION_DECISIONS_MAX_ITEMS,
        RECOMMENDATION_HISTORY_MAX_ITEMS,
        RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION,
        RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS,
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    signatures = [
        {
            "signature_id": f"sig-{index}",
            "last_seen": (now - timedelta(minutes=index)).isoformat(),
        }
        for index in range(NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT + 10)
    ]
    unknown_loads = [
        {
            "signature_id": f"unknown-{index}",
            "last_seen": (now - timedelta(minutes=index)).isoformat(),
        }
        for index in range(NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT + 10)
    ]
    session_history = [
        {
            "session_id": f"session-{index}",
            "start": (now - timedelta(minutes=index)).isoformat(),
            "end": (now - timedelta(minutes=index - 1)).isoformat(),
        }
        for index in range(NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT + 10)
    ]
    session_history.append(
        {
            "session_id": "old-session",
            "start": (
                now - NILM_SESSION_HISTORY_MAX_AGE - timedelta(days=1)
            ).isoformat(),
            "end": (now - NILM_SESSION_HISTORY_MAX_AGE).isoformat(),
        }
    )
    recommendations = {
        f"rec-{index}": _settings_recommendation(
            advisor,
            recommendation_id=f"rec-{index}",
            unique_key=f"hvac:setting:{index}",
            created_at=now - timedelta(hours=index),
            expires_at=now + timedelta(days=30),
        )
        for index in range(RECOMMENDATION_HISTORY_MAX_ITEMS + 10)
    }
    decisions = {
        f"hvac:setting:{index}": advisor.RecommendationDecision(
            unique_key=f"hvac:setting:{index}",
            status=advisor.RecommendationStatus.DENIED,
            decided_at=now - timedelta(hours=index),
            denied_value=index,
        )
        for index in range(RECOMMENDATION_DECISIONS_MAX_ITEMS + 10)
    }
    episodes = tuple(
        (f"rec-{index}", "hvac")
        for index in range(RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS + 10)
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        store_data=FeatureStoreData(
            nilm_signatures={"mains": signatures},
            nilm_unknown_loads_by_circuit={
                "mains": {"unknown_loads": unknown_loads}
            },
            nilm_session_history_by_circuit={"mains": session_history},
            settings_recommendations=recommendations,
            settings_recommendation_decisions=decisions,
            settings_recommendation_notification_episode_key=episodes,
        ),
        now_fn=lambda: now,
    )

    coordinator._apply_retention(now)

    assert (
        len(coordinator.store_data.nilm_signatures["mains"])
        == NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT
    )
    assert coordinator.store_data.nilm_signatures["mains"][0]["signature_id"] == (
        "sig-0"
    )
    assert len(
        coordinator.store_data.nilm_unknown_loads_by_circuit["mains"]["unknown_loads"]
    ) == NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT
    assert (
        len(coordinator.store_data.nilm_session_history_by_circuit["mains"])
        == NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT
    )
    assert coordinator.store_data.nilm_session_history_by_circuit["mains"][0][
        "session_id"
    ] == "session-0"
    assert all(
        session["session_id"] != "old-session"
        for session in coordinator.store_data.nilm_session_history_by_circuit["mains"]
    )
    assert (
        len(coordinator.store_data.settings_recommendations)
        == RECOMMENDATION_HISTORY_MAX_ITEMS
    )
    assert "rec-0" in coordinator.store_data.settings_recommendations
    assert (
        len(coordinator.store_data.settings_recommendation_decisions)
        == RECOMMENDATION_DECISIONS_MAX_ITEMS
    )
    assert "hvac:setting:0" in coordinator.store_data.settings_recommendation_decisions
    episode_key = (
        coordinator.store_data.settings_recommendation_notification_episode_key
    )
    assert len(episode_key) <= RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS
    assert episode_key[0] == (
        "version",
        RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION,
    )
    assert episode_key[1] == ("pending_count", "110")
    assert episode_key[2][0] == "fingerprint"


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
    holder = {"l1": 0.0, "l2": 0.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.hvac_l1_power": str(holder["l1"]),
                "sensor.hvac_l2_power": str(holder["l2"]),
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
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
        now_fn=lambda: holder["time"],
    )

    await coordinator.async_process_update()
    holder.update({"l1": 400.0, "l2": 450.0, "time": now + timedelta(seconds=30)})
    await coordinator.async_process_update()
    holder["time"] = now + timedelta(seconds=60)
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
    holder = {"l1": 0.0, "l2": 0.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.solar_l1_power": str(holder["l1"]),
                "sensor.solar_l2_power": str(holder["l2"]),
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
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
        now_fn=lambda: holder["time"],
    )

    await coordinator.async_process_update()
    holder.update({"l1": -1600.0, "l2": -1500.0, "time": now + timedelta(seconds=30)})
    await coordinator.async_process_update()
    holder["time"] = now + timedelta(seconds=60)
    await coordinator.async_process_update()

    event = coordinator.state.last_event_by_circuit["solar"]
    assert event.features["startup_power_w"] == 3100.0
    assert event.features["raw_real_power_w"] == -3100.0
    assert event.features["power_flow_direction"] == "export"


def test_mains_parallel_sample_treats_partial_power_as_unavailable() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    stale = now - timedelta(hours=1)

    class FakeStates:
        def get(self, entity_id: str):
            if entity_id == "sensor.mains_l1_power":
                return SimpleNamespace(
                    state="1200",
                    attributes={"unit_of_measurement": "W"},
                    last_updated=now,
                )
            if entity_id == "sensor.mains_l2_power":
                return SimpleNamespace(
                    state="1300",
                    attributes={"unit_of_measurement": "W"},
                    last_updated=stale,
                )
            return None

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Main Service",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {
                            "entity_id": "sensor.mains_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.mains_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                }
            ]
        },
        now_fn=lambda: now,
    )

    sample = coordinator._sample_for_config(coordinator.circuit_configs[0], now)

    assert sample.real_power is None
    assert sample.raw_real_power is None
    assert sample.power_flow_direction is None
    assert "sensor.mains_l2_power stale" in sample.quality_issues


@pytest.mark.asyncio
async def test_runtime_experimental_nilm_updates_signature_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
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
    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        AsyncMock(),
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
    inventory = coordinator.state.nilm_unknown_loads_by_circuit["mains"]
    assert inventory["unknown_load_count"] == 1
    assert inventory["unknown_loads"][0]["signature_id"] == (
        coordinator.store_data.nilm_signatures["mains"][0]["signature_id"]
    )
    assert "estimated_energy_today_kwh" in inventory["unknown_loads"][0]
    sessions = coordinator.store_data.nilm_session_history_by_circuit["mains"]
    assert sessions
    assert sessions[0]["mains_circuit_id"] == "mains"
    assert sessions[0]["session_id"]
    assert sessions[0]["signature_fingerprint"] == (
        coordinator.store_data.nilm_signatures["mains"][0]["feedback_fingerprint"]
    )
    assert any(session["end"] is not None for session in sessions)


@pytest.mark.asyncio
async def test_runtime_hvac_weather_context_uses_outdoor_temperature() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 18, 0, tzinfo=UTC)
    start = CircuitEvent(
        timestamp=now - timedelta(hours=4),
        circuit_id="hvac",
        event_type=EventType.START,
    )
    stop = CircuitEvent(
        timestamp=now - timedelta(hours=1),
        circuit_id="hvac",
        event_type=EventType.STOP,
    )

    class FakeStates:
        def get(self, entity_id: str):
            state = "91" if entity_id == "sensor.outdoor_temperature" else "3200"
            unit = "°F" if entity_id == "sensor.outdoor_temperature" else "W"
            return SimpleNamespace(
                state=state,
                attributes={"unit_of_measurement": unit},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": "sensor.hvac_power",
                            "role": "real_power",
                            "leg": "a",
                        }
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[start, stop],
            weather_context_history_by_circuit={
                "hvac": [
                    {
                        "timestamp": (now - timedelta(days=3)).isoformat(),
                        "temperature": 90.0,
                        "runtime_minutes": 170.0,
                        "duty_cycle_percent": 44.0,
                    },
                    {
                        "timestamp": (now - timedelta(days=2)).isoformat(),
                        "temperature": 92.0,
                        "runtime_minutes": 190.0,
                        "duty_cycle_percent": 48.0,
                    },
                    {
                        "timestamp": (now - timedelta(days=1)).isoformat(),
                        "temperature": 89.0,
                        "runtime_minutes": 160.0,
                        "duty_cycle_percent": 42.0,
                    },
                ]
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    evidence = coordinator.state.weather_context_by_circuit["hvac"]
    assert evidence["status"] == "weather_correlated"
    assert evidence["current_outdoor_temperature"] == 91.0
    assert evidence["observed_runtime_minutes"] == 180.0
    assert coordinator.store_data.weather_context_by_circuit["hvac"] == evidence


@pytest.mark.asyncio
async def test_runtime_hvac_weather_context_preserves_celsius_display_unit() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 18, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            state = "25" if entity_id == "sensor.outdoor_temperature" else "3200"
            unit = "°C" if entity_id == "sensor.outdoor_temperature" else "W"
            return SimpleNamespace(
                state=state,
                attributes={"unit_of_measurement": unit},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": "sensor.hvac_power",
                            "role": "real_power",
                            "leg": "a",
                        }
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=4),
                    circuit_id="hvac",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=now - timedelta(hours=1),
                    circuit_id="hvac",
                    event_type=EventType.STOP,
                ),
            ],
            weather_context_history_by_circuit={
                "hvac": [
                    {
                        "timestamp": (now - timedelta(days=3)).isoformat(),
                        "temperature": 76.0,
                        "runtime_minutes": 170.0,
                        "duty_cycle_percent": 44.0,
                    },
                    {
                        "timestamp": (now - timedelta(days=2)).isoformat(),
                        "temperature": 78.0,
                        "runtime_minutes": 190.0,
                        "duty_cycle_percent": 48.0,
                    },
                    {
                        "timestamp": (now - timedelta(days=1)).isoformat(),
                        "temperature": 77.0,
                        "runtime_minutes": 160.0,
                        "duty_cycle_percent": 42.0,
                    },
                ]
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    evidence = coordinator.state.weather_context_by_circuit["hvac"]
    assert evidence["status"] == "weather_correlated"
    assert evidence["temperature_f"] == 77.0
    assert evidence["current_outdoor_temperature"] == 25.0
    assert evidence["temperature_unit"] == "°C"
    assert "25 °C" in evidence["explanation"]


@pytest.mark.asyncio
async def test_runtime_hvac_weather_context_does_not_learn_from_same_day_updates() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    base = datetime(2026, 6, 2, 18, 0, tzinfo=UTC)
    holder = {"now": base}

    class FakeStates:
        def get(self, entity_id: str):
            state = "91" if entity_id == "sensor.outdoor_temperature" else "3200"
            unit = "°F" if entity_id == "sensor.outdoor_temperature" else "W"
            return SimpleNamespace(
                state=state,
                attributes={"unit_of_measurement": unit},
                last_updated=holder["now"],
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": "sensor.hvac_power",
                            "role": "real_power",
                            "leg": "a",
                        }
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=base - timedelta(hours=4),
                    circuit_id="hvac",
                    event_type=EventType.START,
                )
            ],
        ),
        now_fn=lambda: holder["now"],
    )

    for minutes in (0, 5, 10, 15):
        holder["now"] = base + timedelta(minutes=minutes)
        await coordinator.async_process_update()

    evidence = coordinator.state.weather_context_by_circuit["hvac"]
    assert evidence["status"] == "learning"
    assert len(coordinator.store_data.weather_context_history_by_circuit["hvac"]) == 1


def test_weather_context_history_excludes_same_ha_local_day_samples() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(
            weather_context_history_by_circuit={
                "hvac": [
                    {
                        "timestamp": "2026-05-31T23:30:00+00:00",
                        "temperature": 91.0,
                        "runtime_minutes": 120.0,
                        "duty_cycle_percent": 30.0,
                    }
                ]
            }
        ),
        now_fn=lambda: now,
    )

    assert coordinator._weather_context_history_samples("hvac", now) == []


def test_dry_weather_pump_baseline_excludes_same_ha_local_day_samples() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": "2026-05-31T23:30:00+00:00",
                        "pump_runtime_minutes": 14.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    }
                ]
            }
        ),
        now_fn=lambda: now,
    )

    baseline = coordinator._dry_weather_pump_baseline("sump_pump", now)

    assert baseline["dry_baseline_minutes"] is None
    assert baseline["comparable_window_count"] == 0


def test_dry_weather_pump_baseline_excludes_intensity_derived_rain_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": "2026-06-07T12:00:00+00:00",
                        "pump_runtime_minutes": 6.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    },
                    {
                        "timestamp": "2026-06-08T12:00:00+00:00",
                        "pump_runtime_minutes": 8.0,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    },
                    {
                        "timestamp": "2026-06-09T12:00:00+00:00",
                        "pump_runtime_minutes": 60.0,
                        "rain_active": None,
                        "rain_state": "raining",
                        "rain_intensity_mm_per_hour": 0.35,
                        "rain_context_issues": [],
                        "compressor_runtime_minutes": 0.0,
                    },
                    {
                        "timestamp": "2026-06-06T12:00:00+00:00",
                        "pump_runtime_minutes": 50.0,
                        "rain_active": False,
                        "rain_state": "dry",
                        "rain_intensity_mm_per_hour": 0.35,
                        "rain_context_issues": [],
                        "compressor_runtime_minutes": 0.0,
                    },
                    {
                        "timestamp": "2026-06-05T12:00:00+00:00",
                        "pump_runtime_minutes": 40.0,
                        "rain_active": False,
                        "rain_state": "dry",
                        "rain_intensity_mm_per_hour": None,
                        "rain_context_issues": ["rain_activity_conflict"],
                        "compressor_runtime_minutes": 0.0,
                    },
                ]
            }
        ),
        now_fn=lambda: now,
    )

    baseline = coordinator._dry_weather_pump_baseline("sump_pump", now)

    assert baseline["dry_baseline_minutes"] == 7.0
    assert baseline["comparable_window_count"] == 2


def test_append_water_context_history_preserves_derived_rain_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )
    coordinator.state.rain_pump_context_by_circuit["sump_pump"] = {
        "status": "rain_explained",
        "pump_runtime_minutes": 18.0,
        "rain_sensor_active": None,
        "rain_state": "raining",
        "rain_intensity_mm_per_hour": 0.35,
        "rain_intensity_bin": "moderate",
        "rain_context_issues": [],
        "hvac_compressor_runtime_minutes": 0.0,
    }

    changed = coordinator._append_water_context_history("sump_pump", now)

    assert changed is True
    assert coordinator.store_data.water_context_history_by_circuit["sump_pump"] == [
        {
            "timestamp": "2026-06-10T12:00:00+00:00",
            "rain_status": "rain_explained",
            "flow_status": None,
            "pump_runtime_minutes": 18.0,
            "flow_active_minutes": None,
            "mismatch_minutes": None,
            "rain_active": None,
            "compressor_runtime_minutes": 0.0,
            "rain_state": "raining",
            "rain_intensity_mm_per_hour": 0.35,
            "rain_intensity_bin": "moderate",
            "rain_context_issues": [],
        }
    ]


def test_append_water_context_history_replaces_same_ha_local_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(
            water_context_history_by_circuit={
                "sump_pump": [
                    {
                        "timestamp": "2026-05-31T23:30:00+00:00",
                        "rain_status": "normal",
                        "flow_status": None,
                        "pump_runtime_minutes": 8.0,
                        "flow_active_minutes": None,
                        "mismatch_minutes": None,
                        "rain_active": False,
                        "compressor_runtime_minutes": 0.0,
                    }
                ]
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.rain_pump_context_by_circuit["sump_pump"] = {
        "status": "weather_explained",
        "pump_runtime_minutes": 14.0,
        "rain_sensor_active": False,
        "hvac_compressor_runtime_minutes": 0.0,
    }

    changed = coordinator._append_water_context_history("sump_pump", now)

    assert changed is True
    assert coordinator.store_data.water_context_history_by_circuit["sump_pump"] == [
        {
            "timestamp": "2026-06-01T03:30:00+00:00",
            "rain_status": "weather_explained",
            "flow_status": None,
            "pump_runtime_minutes": 14.0,
            "flow_active_minutes": None,
            "mismatch_minutes": None,
            "rain_active": False,
            "compressor_runtime_minutes": 0.0,
        }
    ]


def test_append_weather_context_history_replaces_same_ha_local_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(
            weather_context_history_by_circuit={
                "hvac": [
                    {
                        "timestamp": "2026-05-31T23:30:00+00:00",
                        "temperature": 88.0,
                        "runtime_minutes": 90.0,
                        "duty_cycle_percent": 20.0,
                        "start_count": 1,
                    }
                ]
            }
        ),
        now_fn=lambda: now,
    )
    coordinator.state.run_cycle_count_by_circuit["hvac"] = 2

    changed = coordinator._append_weather_context_history(
        "hvac",
        now,
        temperature=91.0,
        runtime_minutes=120.0,
        duty_cycle_percent=30.0,
    )

    assert changed is True
    assert coordinator.store_data.weather_context_history_by_circuit["hvac"] == [
        {
            "timestamp": "2026-06-01T03:30:00+00:00",
            "temperature": 91.0,
            "runtime_minutes": 120.0,
            "duty_cycle_percent": 30.0,
            "start_count": 2,
        }
    ]


def test_demo_energy_usage_history_uses_ha_local_seed_dates() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.usage import (
        EnergyUsageSettings,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )
    config = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_refrigerator",
        name="Demo Refrigerator",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                entity_id="sensor.cs_energy_analyzer_demo_refrigerator_energy",
                role=SensorRole.ENERGY,
            ),
        ),
    )

    coordinator._seed_demo_energy_usage_history(
        config,
        SimpleNamespace(energy=52.6),
        now,
        EnergyUsageSettings(window_days=7),
    )

    history = coordinator.store_data.energy_usage_by_circuit[config.circuit_id]
    assert history["_demo_seed_date"] == "2026-05-31"
    assert [day["date"] for day in history["days"]] == [
        "2026-05-24",
        "2026-05-25",
        "2026-05-26",
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
        "2026-05-30",
    ]


def test_demo_weather_context_history_uses_ha_local_prior_days() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )
    config = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_hvac",
        name="Demo HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef(
                entity_id="sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
                role=SensorRole.REAL_POWER,
            ),
        ),
    )

    coordinator._seed_demo_weather_context_history(
        config,
        now,
        outdoor_temperature=86.0,
    )

    history = coordinator.store_data.weather_context_history_by_circuit[
        config.circuit_id
    ]
    assert [item["timestamp"] for item in history] == [
        "2026-05-24T16:00:00+00:00",
        "2026-05-25T16:00:00+00:00",
        "2026-05-26T16:00:00+00:00",
        "2026-05-27T16:00:00+00:00",
        "2026-05-28T16:00:00+00:00",
    ]


@pytest.mark.asyncio
async def test_runtime_weather_context_clears_persisted_state_when_not_applicable() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 18, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            return SimpleNamespace(
                state="80",
                attributes={"unit_of_measurement": "°F"},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "Former HVAC",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            weather_context_by_circuit={"hvac": {"status": "weather_correlated"}},
            weather_context_history_by_circuit={
                "hvac": [
                    {
                        "timestamp": (now - timedelta(days=1)).isoformat(),
                        "temperature": 80.0,
                        "runtime_minutes": 20.0,
                        "duty_cycle_percent": 5.0,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert "hvac" not in coordinator.state.weather_context_by_circuit
    assert "hvac" not in coordinator.store_data.weather_context_by_circuit
    assert "hvac" not in coordinator.store_data.weather_context_history_by_circuit


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
    await coordinator.async_ignore_nilm_signature("mains", "on-3")

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
    assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ]
    assert {assignment["lifecycle_state"] for assignment in assignments} >= {
        "expected",
        "ignored",
    }


@pytest.mark.asyncio
async def test_nilm_label_interval_create_update_and_delete() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = {"value": datetime(2026, 6, 2, 13, 0, tzinfo=UTC)}
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(),
        now_fn=lambda: now["value"],
    )

    created = await coordinator.async_label_nilm_interval(
        "mains",
        label="Dishwasher",
        start="2026-06-02T12:00:00+00:00",
        end="2026-06-02T12:45:00+00:00",
        appliance_id="dishwasher",
        mains_entity_id="sensor.mains_power",
        ground_truth_entity_id="sensor.dishwasher_power",
    )
    now["value"] = datetime(2026, 6, 2, 13, 5, tzinfo=UTC)
    updated = await coordinator.async_label_nilm_interval(
        "mains",
        interval_id=created["interval_id"],
        label="Dishwasher wash cycle",
        start="2026-06-02T12:05:00+00:00",
        end="2026-06-02T12:50:00+00:00",
        appliance_id="dishwasher",
        mains_entity_id="sensor.mains_power",
    )
    now["value"] = datetime(2026, 6, 2, 13, 10, tzinfo=UTC)
    deleted = await coordinator.async_delete_nilm_label_interval(
        "mains",
        created["interval_id"],
    )

    assert created["interval_id"] == updated["interval_id"]
    assert updated["label"] == "Dishwasher wash cycle"
    assert updated["start"] == "2026-06-02T12:05:00+00:00"
    assert updated["end"] == "2026-06-02T12:50:00+00:00"
    assert updated["created_at"] == "2026-06-02T13:00:00+00:00"
    assert updated["updated_at"] == "2026-06-02T13:05:00+00:00"
    assert deleted is True
    assert coordinator.store_data.nilm_label_intervals_by_circuit["mains"] == []


@pytest.mark.asyncio
async def test_nilm_label_intervals_are_bounded_per_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT,
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(),
        now_fn=lambda: datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
    )

    base = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    for index in range(NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT + 1):
        start = base + timedelta(minutes=index * 2)
        end = start + timedelta(minutes=1)
        await coordinator.async_label_nilm_interval(
            "mains",
            label=f"Load {index}",
            start=start.isoformat(),
            end=end.isoformat(),
        )

    intervals = coordinator.store_data.nilm_label_intervals_by_circuit["mains"]
    assert len(intervals) == NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT
    assert intervals[0]["label"] == "Load 1"
    assert intervals[-1]["label"] == "Load 500"


@pytest.mark.asyncio
async def test_nilm_appliance_assignment_registry_assigns_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = {"value": datetime(2026, 6, 2, 13, 0, tzinfo=UTC)}
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "signature_1",
                        "feedback_fingerprint": "fingerprint_1",
                    }
                ]
            },
            nilm_label_intervals_by_circuit={
                "mains": [
                    {
                        "interval_id": "label-1",
                        "label": "Dishwasher",
                        "start": "2026-06-02T12:00:00+00:00",
                        "end": "2026-06-02T12:45:00+00:00",
                    }
                ]
            },
        ),
        now_fn=lambda: now["value"],
    )

    signature_assignment = await coordinator.async_assign_nilm_signature(
        "mains",
        "signature_1",
        label="Dishwasher",
        appliance_id="dishwasher",
        appliance_profile="dishwasher",
    )
    now["value"] = datetime(2026, 6, 2, 13, 5, tzinfo=UTC)
    session_assignment = await coordinator.async_assign_nilm_session(
        "mains",
        "session_1",
        label="Dishwasher",
        signature_fingerprint="fingerprint_1",
        appliance_id="dishwasher",
    )
    now["value"] = datetime(2026, 6, 2, 13, 10, tzinfo=UTC)
    interval_assignment = await coordinator.async_assign_nilm_interval(
        "mains",
        "label-1",
        label="Dishwasher",
        appliance_id="dishwasher",
    )

    assert signature_assignment["assignment_id"] == session_assignment[
        "assignment_id"
    ]
    assert interval_assignment["assignment_id"] == signature_assignment[
        "assignment_id"
    ]
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ][0]
    assert assignment["display_name"] == "Dishwasher"
    assert assignment["lifecycle_state"] == "assigned"
    assert assignment["signature_fingerprints"] == ["fingerprint_1"]
    assert assignment["session_ids"] == ["session_1"]
    assert assignment["label_interval_ids"] == ["label-1"]
    assert assignment["created_device"] is False
    assert assignment["publish_entities"] is False
    signature = coordinator.store_data.nilm_signatures["mains"][0]
    assert signature["assignment_id"] == assignment["assignment_id"]
    assert signature["review_state"] == "assigned"
    assert coordinator.store_data.nilm_label_intervals_by_circuit["mains"][0][
        "assignment_id"
    ] == assignment["assignment_id"]


@pytest.mark.asyncio
async def test_nilm_appliance_assignments_are_bounded_per_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT,
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(),
        now_fn=lambda: datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
    )

    for index in range(NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT + 1):
        await coordinator.async_assign_nilm_session(
            "mains",
            f"session-{index}",
            label=f"Load {index}",
            appliance_id=f"load-{index}",
        )

    assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"]
    assert len(assignments) == NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT
    assert assignments[0]["display_name"] == "Load 1"
    assert assignments[-1]["display_name"] == "Load 64"


@pytest.mark.asyncio
async def test_nilm_session_validation_updates_assignment_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = {"value": datetime(2026, 6, 2, 14, 0, tzinfo=UTC)}
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["fingerprint_1"],
                        "session_ids": ["session_1"],
                        "label_interval_ids": [],
                        "lifecycle_state": "assigned",
                        "confidence": 0.8,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    }
                ]
            },
        ),
        now_fn=lambda: now["value"],
    )

    validated = await coordinator.async_validate_nilm_session("mains", "session_1")

    assert validated["confidence"] == pytest.approx(0.85)
    assert validated["lifecycle_state"] == "validated"
    assert validated["confirmed_session_ids"] == ["session_1"]
    assert validated["rejected_session_ids"] == []
    assert validated["confirmed_sessions"] == 1
    assert validated["rejected_sessions"] == 0
    assert validated["adjusted_sessions"] == 0
    assert validated["false_positive_rate"] == pytest.approx(0.0)
    assert validated["false_negative_rate"] == pytest.approx(0.0)
    assert validated["median_power_error"] is None
    assert validated["energy_estimate_error"] is None
    assert validated["last_validation"] == "correct"
    assert validated["last_validated_at"] == "2026-06-02T14:00:00+00:00"

    duplicate_validated = await coordinator.async_validate_nilm_session(
        "mains",
        "session_1",
    )

    assert duplicate_validated["confidence"] == pytest.approx(0.85)
    assert duplicate_validated["confirmed_sessions"] == 1

    now["value"] = datetime(2026, 6, 2, 14, 5, tzinfo=UTC)
    rejected = await coordinator.async_reject_nilm_session("mains", "session_1")

    assert rejected["confidence"] == pytest.approx(0.7)
    assert rejected["lifecycle_state"] == "needs_validation"
    assert rejected["confirmed_session_ids"] == []
    assert rejected["rejected_session_ids"] == ["session_1"]
    assert rejected["confirmed_sessions"] == 0
    assert rejected["rejected_sessions"] == 1
    assert rejected["adjusted_sessions"] == 0
    assert rejected["false_positive_rate"] == pytest.approx(1.0)
    assert rejected["false_negative_rate"] == pytest.approx(0.0)
    assert rejected["median_power_error"] is None
    assert rejected["energy_estimate_error"] is None
    assert rejected["last_validation"] == "wrong_appliance"
    assert rejected["last_rejected_at"] == "2026-06-02T14:05:00+00:00"

    duplicate_rejected = await coordinator.async_reject_nilm_session(
        "mains",
        "session_1",
    )

    assert duplicate_rejected["confidence"] == pytest.approx(0.7)
    assert duplicate_rejected["rejected_sessions"] == 1


@pytest.mark.asyncio
async def test_nilm_assignment_history_validation_confirms_matches() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 14, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={
                "mains": [
                    {
                        "interval_id": "label-dishwasher",
                        "mains_circuit_id": "mains",
                        "appliance_id": "dishwasher",
                        "label": "Dishwasher",
                        "start": "2026-06-02T12:10:00+00:00",
                        "end": "2026-06-02T12:40:00+00:00",
                        "source": "sensor",
                        "confidence": 1.0,
                        "mains_entity_id": "sensor.mains_power",
                        "ground_truth_entity_id": "sensor.dishwasher_power",
                        "median_power_w": 800.0,
                        "estimated_energy_kwh": 0.5,
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mains": [
                    {
                        "session_id": "session-match",
                        "assignment_id": "assignment-dishwasher",
                        "start": "2026-06-02T12:00:00+00:00",
                        "end": "2026-06-02T12:45:00+00:00",
                        "confidence": 0.78,
                        "median_power_w": 820.0,
                        "estimated_energy_kwh": 0.615,
                    },
                    {
                        "session_id": "session-later",
                        "assignment_id": "assignment-dishwasher",
                        "start": "2026-06-02T13:00:00+00:00",
                        "end": "2026-06-02T13:45:00+00:00",
                        "confidence": 0.76,
                    },
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": [],
                        "session_ids": ["session-match", "session-later"],
                        "label_interval_ids": ["label-dishwasher"],
                        "confirmed_session_ids": [],
                        "rejected_session_ids": ["session-match"],
                        "lifecycle_state": "assigned",
                        "confidence": 0.8,
                        "created_at": "2026-06-02T11:00:00+00:00",
                        "updated_at": "2026-06-02T11:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    validated = await coordinator.async_validate_nilm_assignment_history(
        "mains",
        "assignment-dishwasher",
    )

    assert validated["confirmed_session_ids"] == ["session-match"]
    assert validated["rejected_session_ids"] == []
    assert validated["confirmed_sessions"] == 1
    assert validated["rejected_sessions"] == 0
    assert validated["adjusted_sessions"] == 0
    assert validated["confidence"] == pytest.approx(0.85)
    assert validated["lifecycle_state"] == "validated"
    assert validated["last_validation"] == "history"
    assert validated["last_validated_at"] == "2026-06-02T14:00:00+00:00"
    assert validated["ground_truth_interval_count"] == 1
    assert validated["matched_ground_truth_count"] == 1
    assert validated["missed_ground_truth_count"] == 0
    assert validated["false_positive_rate"] == pytest.approx(0.0)
    assert validated["false_negative_rate"] == pytest.approx(0.0)
    assert validated["median_power_error"] == pytest.approx(20.0)
    assert validated["energy_estimate_error"] == pytest.approx(0.115)
    assert "session-later" not in validated["confirmed_session_ids"]


@pytest.mark.asyncio
async def test_nilm_assignment_history_validation_rejects_direct_meter_conflicts() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 15, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={
                "mains": [
                    {
                        "interval_id": "label-dishwasher",
                        "mains_circuit_id": "mains",
                        "appliance_id": "dishwasher",
                        "label": "Dishwasher",
                        "start": "2026-06-02T12:00:00+00:00",
                        "end": "2026-06-02T12:30:00+00:00",
                        "validation_start": "2026-06-02T12:00:00+00:00",
                        "validation_end": "2026-06-02T14:00:00+00:00",
                        "source": "sensor",
                        "confidence": 1.0,
                        "ground_truth_entity_id": "sensor.dishwasher_power",
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mains": [
                    {
                        "session_id": "session-false-positive",
                        "assignment_id": "assignment-dishwasher",
                        "start": "2026-06-02T13:00:00+00:00",
                        "end": "2026-06-02T13:30:00+00:00",
                        "confidence": 0.78,
                    }
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": [],
                        "session_ids": ["session-false-positive"],
                        "label_interval_ids": ["label-dishwasher"],
                        "confirmed_session_ids": [],
                        "rejected_session_ids": [],
                        "lifecycle_state": "validated",
                        "confidence": 0.8,
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    validated = await coordinator.async_validate_nilm_assignment_history(
        "mains",
        "assignment-dishwasher",
    )

    assert validated["confirmed_session_ids"] == []
    assert validated["rejected_session_ids"] == ["session-false-positive"]
    assert validated["confirmed_sessions"] == 0
    assert validated["rejected_sessions"] == 1
    assert validated["adjusted_sessions"] == 0
    assert validated["confidence"] == pytest.approx(0.65)
    assert validated["lifecycle_state"] == "conflict"
    assert validated["last_validation"] == "direct_meter_conflict"
    assert validated["last_rejected_at"] == "2026-06-02T15:00:00+00:00"
    assert validated["ground_truth_interval_count"] == 1
    assert validated["matched_ground_truth_count"] == 0
    assert validated["missed_ground_truth_count"] == 1
    assert validated["false_positive_rate"] == pytest.approx(1.0)
    assert validated["false_negative_rate"] == pytest.approx(1.0)
    assert validated["median_power_error"] is None
    assert validated["energy_estimate_error"] is None
    assert validated["validation_window_start"] == "2026-06-02T12:00:00+00:00"
    assert validated["validation_window_end"] == "2026-06-02T14:00:00+00:00"


@pytest.mark.asyncio
async def test_adjusted_nilm_label_interval_improves_history_matching() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = {"value": datetime(2026, 6, 2, 15, 0, tzinfo=UTC)}
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={
                "mains": [
                    {
                        "interval_id": "label-dishwasher",
                        "mains_circuit_id": "mains",
                        "appliance_id": "dishwasher",
                        "label": "Dishwasher",
                        "start": "2026-06-02T10:00:00+00:00",
                        "end": "2026-06-02T10:30:00+00:00",
                        "source": "manual",
                        "confidence": 1.0,
                        "ground_truth_entity_id": "sensor.dishwasher_power",
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mains": [
                    {
                        "session_id": "session-dishwasher",
                        "assignment_id": "assignment-dishwasher",
                        "start": "2026-06-02T12:00:00+00:00",
                        "end": "2026-06-02T12:45:00+00:00",
                        "confidence": 0.78,
                    }
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": [],
                        "session_ids": ["session-dishwasher"],
                        "label_interval_ids": ["label-dishwasher"],
                        "confirmed_session_ids": [],
                        "rejected_session_ids": [],
                        "lifecycle_state": "learning",
                        "confidence": 0.8,
                    }
                ]
            },
        ),
        now_fn=lambda: now["value"],
    )

    with pytest.raises(ValueError, match="No matching ground-truth NILM sessions"):
        await coordinator.async_validate_nilm_assignment_history(
            "mains",
            "assignment-dishwasher",
        )

    now["value"] = datetime(2026, 6, 2, 15, 5, tzinfo=UTC)
    await coordinator.async_label_nilm_interval(
        "mains",
        interval_id="label-dishwasher",
        label="Dishwasher",
        start="2026-06-02T12:05:00+00:00",
        end="2026-06-02T12:50:00+00:00",
        appliance_id="dishwasher",
        ground_truth_entity_id="sensor.dishwasher_power",
    )

    validated = await coordinator.async_validate_nilm_assignment_history(
        "mains",
        "assignment-dishwasher",
    )

    assert validated["confirmed_session_ids"] == ["session-dishwasher"]
    assert validated["matched_ground_truth_count"] == 1
    assert validated["missed_ground_truth_count"] == 0
    assert validated["false_negative_rate"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_nilm_assignment_rename_and_profile_update() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = {"value": datetime(2026, 6, 2, 15, 0, tzinfo=UTC)}
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["fingerprint_1"],
                        "session_ids": ["session_1"],
                        "label_interval_ids": [],
                        "lifecycle_state": "validated",
                        "confidence": 0.85,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now["value"],
    )

    renamed = await coordinator.async_rename_nilm_appliance(
        "mains",
        "assignment-dishwasher",
        label="Kitchen Dishwasher",
    )
    now["value"] = datetime(2026, 6, 2, 15, 5, tzinfo=UTC)
    updated = await coordinator.async_change_nilm_appliance_profile(
        "mains",
        "assignment-dishwasher",
        appliance_profile="dishwasher_heated_dry",
    )

    assert renamed["display_name"] == "Kitchen Dishwasher"
    assert renamed["appliance_id"] == "dishwasher"
    assert updated["display_name"] == "Kitchen Dishwasher"
    assert updated["appliance_profile"] == "dishwasher_heated_dry"
    assert updated["updated_at"] == "2026-06-02T15:05:00+00:00"


@pytest.mark.asyncio
async def test_nilm_assignment_merge_moves_references_to_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 16, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "source-sig",
                        "assignment_id": "assignment-source",
                    }
                ]
            },
            nilm_label_intervals_by_circuit={
                "mains": [
                    {
                        "interval_id": "label-source",
                        "assignment_id": "assignment-source",
                    }
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-source",
                        "appliance_id": "dishwasher_old",
                        "display_name": "Dishwasher old",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["source-fingerprint"],
                        "session_ids": ["source-session"],
                        "label_interval_ids": ["label-source"],
                        "confirmed_session_ids": ["source-session"],
                        "rejected_session_ids": [],
                        "lifecycle_state": "validated",
                        "confidence": 0.72,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    },
                    {
                        "assignment_id": "assignment-target",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["target-fingerprint"],
                        "session_ids": ["target-session"],
                        "label_interval_ids": [],
                        "confirmed_session_ids": [],
                        "rejected_session_ids": ["target-session"],
                        "lifecycle_state": "published",
                        "confidence": 0.9,
                        "created_at": "2026-06-02T13:00:00+00:00",
                        "updated_at": "2026-06-02T13:00:00+00:00",
                        "created_device": True,
                        "publish_entities": True,
                    },
                ]
            },
        ),
        now_fn=lambda: now,
    )

    merged = await coordinator.async_merge_nilm_assignments(
        "mains",
        "assignment-source",
        "assignment-target",
    )

    assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ]
    assert [assignment["assignment_id"] for assignment in assignments] == [
        "assignment-target"
    ]
    assert merged["signature_fingerprints"] == [
        "target-fingerprint",
        "source-fingerprint",
    ]
    assert merged["session_ids"] == ["target-session", "source-session"]
    assert merged["label_interval_ids"] == ["label-source"]
    assert merged["confirmed_session_ids"] == ["source-session"]
    assert merged["rejected_session_ids"] == ["target-session"]
    assert merged["confidence"] == 0.9
    assert merged["lifecycle_state"] == "published"
    assert merged["publish_entities"] is True
    assert merged["updated_at"] == "2026-06-02T16:00:00+00:00"
    assert coordinator.store_data.nilm_signatures["mains"][0]["assignment_id"] == (
        "assignment-target"
    )
    assert coordinator.store_data.nilm_label_intervals_by_circuit["mains"][0][
        "assignment_id"
    ] == "assignment-target"


@pytest.mark.asyncio
async def test_nilm_signature_assignment_clears_ignored_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "signature_1",
                        "feedback_fingerprint": "fingerprint_1",
                        "ignored": True,
                        "review_state": "ignored",
                    }
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-ignored",
                        "appliance_id": "ignored_load",
                        "display_name": "Ignored Load",
                        "appliance_profile": None,
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["fingerprint_1"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "ignored",
                        "confidence": 0.7,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    }
                ]
            },
        ),
    )
    coordinator.ignored_nilm_signatures.add(("mains", "signature_1"))

    assignment = await coordinator.async_assign_nilm_signature(
        "mains",
        "signature_1",
        label="Dishwasher",
        appliance_id="dishwasher",
    )

    signature = coordinator.store_data.nilm_signatures["mains"][0]
    assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ]
    assert "ignored" not in signature
    assert ("mains", "signature_1") not in coordinator.ignored_nilm_signatures
    assert assignment["lifecycle_state"] == "assigned"
    assert [
        item
        for item in assignments
        if "fingerprint_1" in item.get("signature_fingerprints", ())
    ] == [assignment]


@pytest.mark.asyncio
async def test_nilm_signature_merge_tracks_assignment_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "source",
                        "feedback_fingerprint": "source-fingerprint",
                    },
                    {
                        "signature_id": "target",
                        "feedback_fingerprint": "target-fingerprint",
                    },
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-source",
                        "appliance_id": "pool_pump",
                        "display_name": "Pool Pump",
                        "appliance_profile": "pool_pump",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["source-fingerprint"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "assigned",
                        "confidence": 1.0,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    },
                    {
                        "assignment_id": "assignment-target",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["target-fingerprint"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "assigned",
                        "confidence": 1.0,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    }
                ]
            },
        ),
    )

    await coordinator.async_merge_nilm_signatures("mains", "source", "target")

    signatures = {
        signature["signature_id"]: signature
        for signature in coordinator.store_data.nilm_signatures["mains"]
    }
    assignments = {
        assignment["assignment_id"]: assignment
        for assignment in coordinator.store_data.nilm_appliance_assignments_by_circuit[
            "mains"
        ]
    }
    source_assignment = assignments["assignment-source"]
    assignment = assignments["assignment-target"]
    assert signatures["source"]["assignment_id"] == "assignment-target"
    assert source_assignment["signature_fingerprints"] == []
    assert assignment["signature_fingerprints"] == [
        "target-fingerprint",
        "source-fingerprint",
    ]


@pytest.mark.asyncio
async def test_nilm_assignment_publish_unpublish_and_retire_lifecycle() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.reloaded: list[str] = []

        async def async_reload(self, entry_id: str) -> None:
            self.reloaded.append(entry_id)

    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_id=entry.entry_id,
        config_entry=entry,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["signature_1"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "validated",
                        "confidence": 0.92,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": False,
                        "publish_entities": False,
                    }
                ]
            },
        ),
        now_fn=lambda: datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
    )

    published = await coordinator.async_publish_nilm_appliance_assignment(
        "mains",
        "assignment-dishwasher",
    )

    assert published["publish_entities"] is True
    assert published["created_device"] is True
    assert published["lifecycle_state"] == "published"
    assert published["updated_at"] == "2026-06-02T14:00:00+00:00"
    assert hass.config_entries.reloaded == ["entry-1"]

    unpublished = await coordinator.async_unpublish_nilm_appliance_assignment(
        "mains",
        "assignment-dishwasher",
    )

    assert unpublished["publish_entities"] is False
    assert unpublished["created_device"] is True
    assert unpublished["lifecycle_state"] == "validated"
    assert hass.config_entries.reloaded == ["entry-1", "entry-1"]

    retired = await coordinator.async_retire_nilm_appliance_assignment(
        "mains",
        "assignment-dishwasher",
    )

    assert retired["publish_entities"] is False
    assert retired["lifecycle_state"] == "retired"
    assert hass.config_entries.reloaded == ["entry-1", "entry-1", "entry-1"]


def test_nilm_virtual_alert_builders_gate_confidence_and_repeated_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer import nilm_virtual

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    state = SimpleNamespace(
        assignment_id="assignment-dishwasher",
        display_name="Dishwasher",
        is_running=False,
        estimated_energy_kwh_today=0.45,
        confidence=0.82,
        last_seen=now - timedelta(minutes=5),
        active_session_id=None,
        latest_session_id="session-1",
        model_status="published",
        mains_circuit_id="mains",
    )

    finished_builder = getattr(nilm_virtual, "nilm_virtual_finished_alert", None)
    assert finished_builder is not None
    finished_alert = finished_builder(state, now=now)

    assert finished_alert is not None
    assert finished_alert.feature == "nilm_appliance_finished"
    assert finished_alert.circuit_id == "mains"
    assert "Estimated from mains power by NILM" in finished_alert.message
    assert "Confidence: 82%" in finished_alert.message
    assert finished_alert.features["source_type"] == "nilm_estimate"
    assert finished_alert.features["estimated"] is True
    assert finished_alert.features["confidence"] == pytest.approx(0.82)
    assert finished_alert.features["assignment_id"] == "assignment-dishwasher"
    assert finished_alert.features["notification_key"] == (
        "assignment-dishwasher:session-1"
    )

    low_confidence_state = SimpleNamespace(**{**state.__dict__, "confidence": 0.7})
    assert finished_builder(low_confidence_state, now=now) is None
    nan_confidence_state = SimpleNamespace(
        **{**state.__dict__, "confidence": float("nan")}
    )
    assert finished_builder(nan_confidence_state, now=now) is None
    pending_validation_state = SimpleNamespace(
        **{**state.__dict__, "model_status": "needs_validation"}
    )
    assert finished_builder(pending_validation_state, now=now) is None

    running_state = SimpleNamespace(
        **{
            **state.__dict__,
            "is_running": True,
            "confidence": 0.86,
            "last_seen": now - timedelta(minutes=45),
            "active_session_id": "session-open",
            "latest_session_id": "session-open",
            "estimated_energy_kwh_today": 1.2,
        }
    )
    runtime_builder = getattr(
        nilm_virtual,
        "nilm_virtual_unusual_runtime_alert",
        None,
    )
    energy_builder = getattr(nilm_virtual, "nilm_virtual_unusual_energy_alert", None)
    assert runtime_builder is not None
    assert energy_builder is not None

    assert (
        runtime_builder(
            running_state,
            {"expected_runtime_minutes": 30, "unusual_runtime_repeated_count": 1},
            now=now,
        )
        is None
    )
    runtime_alert = runtime_builder(
        running_state,
        {"expected_runtime_minutes": 30, "unusual_runtime_repeated_count": 2},
        now=now,
    )

    assert runtime_alert is not None
    assert runtime_alert.feature == "nilm_appliance_unusual_runtime"
    assert runtime_alert.repeated_count == 2
    assert "estimated" in runtime_alert.message.lower()
    assert runtime_alert.features["source_type"] == "nilm_estimate"
    assert runtime_alert.features["confidence"] == pytest.approx(0.86)

    unvalidated_state = SimpleNamespace(
        **{**running_state.__dict__, "model_status": "assigned"}
    )
    assert (
        runtime_builder(
            unvalidated_state,
            {"expected_runtime_minutes": 30, "unusual_runtime_repeated_count": 2},
            now=now,
        )
        is None
    )

    energy_alert = energy_builder(
        state,
        {"expected_daily_energy_kwh": 0.3, "unusual_energy_repeated_count": 2},
        now=now,
    )

    assert energy_alert is not None
    assert energy_alert.feature == "nilm_appliance_unusual_energy"
    assert energy_alert.repeated_count == 2
    assert "Estimated from mains power by NILM" in energy_alert.message
    assert energy_alert.features["source_type"] == "nilm_estimate"
    assert energy_alert.features["confidence"] == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_nilm_virtual_finished_notification_uses_existing_alert_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    sent_notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        sent_notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["signature_1"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "published",
                        "confidence": 0.91,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )
    coordinator._nilm_unmatched_edges["mains"] = [
        NilmEdge(
            timestamp=now - timedelta(minutes=45),
            delta_w=650.0,
            delta_var=20.0,
            delta_va=650.0,
            delta_pf=0.0,
            direction="on",
        ),
        NilmEdge(
            timestamp=now - timedelta(minutes=5),
            delta_w=-640.0,
            delta_var=-18.0,
            delta_va=-640.0,
            delta_pf=0.0,
            direction="off",
        ),
    ]

    notify_virtual = getattr(coordinator, "_notify_nilm_virtual_appliances", None)
    assert notify_virtual is not None
    active_alerts = await notify_virtual(now)

    assert sent_notifications
    assert active_alerts == sent_notifications
    assert sent_notifications[0].feature == "nilm_appliance_finished"
    assert "Estimated from mains power by NILM" in sent_notifications[0].message
    assert coordinator.store_data.alerts[-1] == sent_notifications[0]

    active_alerts = await notify_virtual(now)

    assert len(sent_notifications) == 1
    assert active_alerts
    assert active_alerts[0].feature == "nilm_appliance_finished"


@pytest.mark.asyncio
async def test_nilm_virtual_low_confidence_notification_prompts_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    sent_notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        sent_notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "lifecycle_state": "needs_validation",
                        "confidence": 0.72,
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    notify_virtual = getattr(coordinator, "_notify_nilm_virtual_appliances", None)
    assert notify_virtual is not None
    active_alerts = await notify_virtual(now)

    assert sent_notifications
    assert active_alerts == sent_notifications
    assert sent_notifications[0].feature == "nilm_low_confidence_change"
    assert "needs validation" in sent_notifications[0].message
    assert "Estimated from mains power by NILM" in sent_notifications[0].message
    assert sent_notifications[0].features["notification_key"] == (
        "assignment-dishwasher:low_confidence"
    )

    active_alerts = await notify_virtual(now)

    assert len(sent_notifications) == 1
    assert active_alerts
    assert active_alerts[0].feature == "nilm_low_confidence_change"


@pytest.mark.asyncio
async def test_nilm_virtual_needs_validation_notification_uses_review_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    sent_notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        sent_notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "lifecycle_state": "needs_validation",
                        "confidence": 0.91,
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    active_alerts = await coordinator._notify_nilm_virtual_appliances(now)

    assert sent_notifications
    assert active_alerts == sent_notifications
    assert sent_notifications[0].feature == "nilm_assignment_needs_validation"
    assert sent_notifications[0].features["notification_key"] == (
        "assignment-dishwasher:needs_validation"
    )


@pytest.mark.asyncio
async def test_nilm_virtual_conflict_notification_uses_model_drift_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    sent_notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        sent_notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "lifecycle_state": "conflict",
                        "confidence": 0.91,
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )

    active_alerts = await coordinator._notify_nilm_virtual_appliances(now)

    assert sent_notifications
    assert active_alerts == sent_notifications
    assert sent_notifications[0].feature == "nilm_model_drift"
    assert sent_notifications[0].features["notification_key"] == (
        "assignment-dishwasher:model_drift"
    )


@pytest.mark.asyncio
async def test_nilm_notification_feedback_adjusts_assignment_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["signature_1"],
                        "session_ids": [],
                        "label_interval_ids": [],
                        "lifecycle_state": "published",
                        "confidence": 0.9,
                        "created_at": "2026-06-02T12:00:00+00:00",
                        "updated_at": "2026-06-02T12:00:00+00:00",
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="mains",
        severity=Severity.INFO,
        message=(
            "Dishwasher appears finished. Estimated from mains power by NILM. "
            "Confidence: 90%."
        ),
        feature="nilm_appliance_finished",
        features={
            "source": "nilm",
            "assignment_id": "assignment-dishwasher",
            "notification_key": "assignment-dishwasher:session-1",
        },
    )
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts.append(alert)

    mark_wrong = getattr(coordinator, "async_mark_nilm_appliance_wrong", None)
    mark_correct = getattr(coordinator, "async_mark_nilm_appliance_correct", None)
    assert mark_wrong is not None
    assert mark_correct is not None
    assert await mark_wrong(alert_id) is True

    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ][0]
    assert assignment["confidence"] == pytest.approx(0.75)
    assert assignment["lifecycle_state"] == "needs_validation"
    assert assignment["confirmed_session_ids"] == []
    assert assignment["rejected_session_ids"] == ["session-1"]
    assert assignment["confirmed_sessions"] == 0
    assert assignment["rejected_sessions"] == 1
    assert assignment["false_positive_rate"] == pytest.approx(1.0)

    coordinator.store_data.alerts.append(alert)
    assert await mark_correct(alert_id) is True

    assert assignment["confidence"] == pytest.approx(0.8)
    assert assignment["last_validation"] == "correct"
    assert assignment["confirmed_session_ids"] == ["session-1"]
    assert assignment["rejected_session_ids"] == []
    assert assignment["confirmed_sessions"] == 1
    assert assignment["rejected_sessions"] == 0
    assert assignment["false_positive_rate"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_nilm_non_session_notification_feedback_keeps_session_counts_empty() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "lifecycle_state": "published",
                        "confidence": 0.9,
                        "created_device": True,
                        "publish_entities": True,
                    }
                ]
            },
        ),
        now_fn=lambda: now,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="mains",
        severity=Severity.INFO,
        message="Dishwasher runtime looks unusual. Estimated from mains power by NILM.",
        feature="nilm_appliance_unusual_runtime",
        features={
            "source": "nilm",
            "assignment_id": "assignment-dishwasher",
            "notification_type": "runtime",
            "notification_key": "assignment-dishwasher:runtime:2026-06-02",
        },
    )
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts.append(alert)

    assert await coordinator.async_mark_nilm_appliance_wrong(alert_id) is True

    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ][0]
    assert assignment["confidence"] == pytest.approx(0.75)
    assert assignment["confirmed_session_ids"] == []
    assert assignment["rejected_session_ids"] == []
    assert assignment["confirmed_sessions"] == 0
    assert assignment["rejected_sessions"] == 0
    assert assignment["false_positive_rate"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_runtime_data_quality_creates_repairs_issue(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem, dict(kwargs.get("data") or {})))

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

    assert issues == [
        (
            "fridge",
            "missing_required_sensor",
            {
                "circuit_name": "Fridge",
                "reason": "A configured circuit is missing a required source sensor.",
                "recommended_action": "Review source sensors for Fridge",
                "source_entities": ["sensor.missing"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_runtime_negative_load_power_creates_orientation_issue(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    issues = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        source_entities=(),
        **kwargs,
    ) -> None:
        issues.append(
            (
                circuit_id,
                problem,
                tuple(source_entities),
                dict(kwargs.get("data") or {}),
            )
        )

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

    assert issues == [
        (
            "fridge",
            "unexpected_negative_real_power",
            ("sensor.fridge_power", "sensor.fridge_current"),
            {
                "circuit_name": "Fridge",
                "reason": "A load circuit is reporting sustained negative real power.",
                "recommended_action": (
                    "Check CT direction or power-flow mode for Fridge"
                ),
                "source_entities": [
                    "sensor.fridge_power",
                    "sensor.fridge_current",
                ],
            },
        )
    ]
    assert "negative_real_power_load" in coordinator.state.data_quality_by_circuit[
        "fridge"
    ]
    assert "fridge" not in coordinator.state.last_event_by_circuit
    assert "fridge:real_power" not in coordinator.store_data.baselines


@pytest.mark.asyncio
async def test_runtime_missing_energy_source_creates_setup_health_repair(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.fridge_power"
            return SimpleNamespace(
                state="180",
                attributes={
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "state_class": "measurement",
                },
                last_updated=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
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
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )

    await coordinator.async_process_update()

    assert ("fridge", "missing_energy_source") in issues


@pytest.mark.asyncio
async def test_setup_health_repair_includes_circuit_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    repairs_created: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        del hass, severity
        repairs_created.append((circuit_id, problem, dict(kwargs.get("data") or {})))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.state.energy_dashboard_status_by_circuit["fridge"] = (
        "needs_energy_source"
    )

    await coordinator._sync_setup_health_repairs("fridge")

    assert repairs_created == [
        (
            "fridge",
            "missing_energy_source",
            {
                "circuit_name": "Refrigerator",
                "reason": "Daily Energy Usage needs a cumulative energy source.",
                "recommended_action": (
                    "Add a cumulative kWh sensor to Refrigerator"
                ),
                "source_entities": ["sensor.fridge_power"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_process_update_missing_source_entities_creates_setup_health_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    repairs_created: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        del hass, severity
        repairs_created.append((circuit_id, problem, dict(kwargs.get("data") or {})))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "garage_freezer",
                    "name": "Garage Freezer",
                    "mode": "single_phase",
                    "appliance_profile": "freezer",
                    "sensors": [],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    await coordinator.async_process_update()

    assert repairs_created == [
        (
            "garage_freezer",
            "missing_source_entities",
            {
                "circuit_name": "Garage Freezer",
                "reason": "No source sensors are configured for this circuit.",
                "recommended_action": (
                    "Add at least one source sensor to Garage Freezer"
                ),
                "source_entities": [],
            },
        )
    ]


@pytest.mark.asyncio
async def test_runtime_missing_mains_source_creates_setup_health_repair(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.state.balance_status_by_circuit["mains"] = "missing_mains"
    coordinator.state.energy_dashboard_status_by_circuit["mains"] = "ready"

    await coordinator._sync_setup_health_repairs("mains")

    assert ("mains", "missing_mains_source") in issues


@pytest.mark.asyncio
async def test_runtime_missing_electrical_metrics_creates_setup_health_repair(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.state.metric_consistency_status_by_circuit["hvac"] = "missing_metrics"

    await coordinator._sync_setup_health_repairs("hvac")

    assert ("hvac", "missing_electrical_metrics") in issues


@pytest.mark.asyncio
async def test_runtime_ct_direction_setup_health_issue_creates_repair(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.state.solar_flow_status_by_circuit["solar"] = "inconsistent_export"

    await coordinator._sync_setup_health_repairs("solar")

    assert ("solar", "check_ct_direction") in issues


@pytest.mark.asyncio
async def test_runtime_dual_phase_missing_leg_power_creates_setup_health_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 18, 0, tzinfo=UTC)
    issues: list[tuple[str, str, dict[str, Any]]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem, dict(kwargs.get("data") or {})))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    class FakeStates:
        def get(self, entity_id: str):
            if entity_id == "sensor.hvac_l2_power":
                return None
            assert entity_id == "sensor.hvac_l1_power"
            return SimpleNamespace(
                state="2400",
                attributes={"unit_of_measurement": "W"},
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

    assert coordinator.state.leg_imbalance_status_by_circuit["hvac"] == (
        "missing_leg_power"
    )
    dual_phase_issue = next(
        data
        for circuit_id, problem, data in issues
        if circuit_id == "hvac" and problem == "dual_phase_missing_leg"
    )
    assert dual_phase_issue == {
        "circuit_name": "HVAC",
        "reason": "One side of this dual-phase circuit is missing real-power data.",
        "recommended_action": "Review leg A and leg B source sensors for HVAC",
        "source_entities": [
            "sensor.hvac_l1_power",
            "sensor.hvac_l2_power",
        ],
    }


@pytest.mark.asyncio
async def test_runtime_enabled_rain_context_without_source_creates_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.sump_power"
            return SimpleNamespace(
                state="650",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "sump_pump",
                    "name": "Sump Pump",
                    "mode": "single_phase",
                    "appliance_profile": "sump_pump",
                    "sensors": [
                        {"entity_id": "sensor.sump_power", "role": "real_power"}
                    ],
                }
            ],
            CONF_ADVANCED_SETTINGS: {
                "sump_pump": {CONF_RAIN_PUMP_CORRELATION_ENABLED: True}
            },
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert ("sump_pump", "missing_rain_context_source") in issues


@pytest.mark.asyncio
async def test_runtime_enabled_water_flow_context_without_source_creates_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.washer_power"
            return SimpleNamespace(
                state="700",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "mode": "single_phase",
                    "appliance_profile": "washer",
                    "sensors": [
                        {"entity_id": "sensor.washer_power", "role": "real_power"}
                    ],
                }
            ],
            CONF_ADVANCED_SETTINGS: {
                "washer": {CONF_WATER_FLOW_CORRELATION_ENABLED: True}
            },
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert ("washer", "missing_water_flow_source") in issues


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


@pytest.mark.asyncio
async def test_demo_source_entities_are_treated_as_current_for_data_quality() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    old_timestamp = now - timedelta(hours=2)
    circuit_id = "cs_energy_analyzer_demo_refrigerator"

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == (
                "sensor.cs_energy_analyzer_demo_refrigerator_active_power"
            )
            return SimpleNamespace(
                state="285",
                attributes={"unit_of_measurement": "W"},
                last_updated=old_timestamp,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={DOMAIN: {}}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": circuit_id,
                    "name": "Refrigerator",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_refrigerator_active_power"
                            ),
                            "role": "real_power",
                        },
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert circuit_id not in coordinator.state.data_quality_by_circuit
    checklist = coordinator.state.data_quality_checklist_by_circuit[circuit_id]
    assert checklist["source_data_fresh"] is True
    assert not any("stale" in issue for issue in checklist["quality_issues"])


def test_demo_source_states_use_registered_suffixed_entity_ids() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    canonical_entity_id = "sensor.cs_energy_analyzer_demo_refrigerator_energy"
    registered_entity_id = "sensor.cs_energy_analyzer_demo_refrigerator_energy_2"
    config = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_refrigerator",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef(canonical_entity_id, SensorRole.ENERGY),),
    )

    class FakeStates:
        def get(self, entity_id: str):
            if entity_id == canonical_entity_id:
                return None
            assert entity_id == registered_entity_id
            return SimpleNamespace(
                state="52.6",
                attributes={"unit_of_measurement": "kWh"},
                last_updated=now,
            )

    registry = SimpleNamespace(
        entities={
            registered_entity_id: SimpleNamespace(
                entity_id=registered_entity_id,
                unique_id=(
                    "entry-1_demo_source_exact_"
                    "cs_energy_analyzer_demo_refrigerator_energy"
                ),
                config_entry_id="entry-1",
                platform=DOMAIN,
            )
        }
    )
    hass = SimpleNamespace(
        states=FakeStates(),
        data={DOMAIN: {}},
        entity_registry=registry,
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_id="entry-1",
        entry_data={},
        now_fn=lambda: now,
    )

    states = coordinator._source_states_for(config, now)

    assert states[canonical_entity_id].state == "52.6"
    assert states[canonical_entity_id].entity_id == canonical_entity_id


@pytest.mark.asyncio
async def test_demo_appliance_history_is_seeded_after_learning() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    circuit_id = "cs_energy_analyzer_demo_hvac"
    states = {
        "sensor.cs_energy_analyzer_demo_hvac_l1_energy": ("188.4", "kWh"),
        "sensor.cs_energy_analyzer_demo_hvac_l2_energy": ("171.9", "kWh"),
        "sensor.cs_energy_analyzer_demo_hvac_l1_active_power": ("3300", "W"),
        "sensor.cs_energy_analyzer_demo_hvac_l2_active_power": ("900", "W"),
        "sensor.cs_energy_analyzer_demo_hvac_l1_current": ("28.0", "A"),
        "sensor.cs_energy_analyzer_demo_hvac_l2_current": ("7.4", "A"),
        "sensor.cs_energy_analyzer_demo_hvac_l1_power_factor": ("0.72", ""),
        "sensor.cs_energy_analyzer_demo_hvac_l2_power_factor": ("0.95", ""),
        "sensor.cs_energy_analyzer_demo_hvac_l1_reactive_power": ("3100", "var"),
        "sensor.cs_energy_analyzer_demo_hvac_l2_reactive_power": ("300", "var"),
        "sensor.cs_energy_analyzer_demo_hvac_l1_apparent_power": ("4580", "VA"),
        "sensor.cs_energy_analyzer_demo_hvac_l2_apparent_power": ("947", "VA"),
        "sensor.cs_energy_analyzer_demo_mains_l1_voltage": ("119.6", "V"),
        "sensor.cs_energy_analyzer_demo_mains_l2_voltage": ("120.3", "V"),
        "sensor.demo_outdoor_temperature": ("86", "°F"),
    }

    class FakeStates:
        def get(self, entity_id: str):
            value, unit = states[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={DOMAIN: {}}),
        entry_data={
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.demo_outdoor_temperature",
            CONF_CIRCUITS: [
                {
                    "circuit_id": circuit_id,
                    "name": "HVAC",
                    "mode": "dual_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_energy"
                            ),
                            "role": "energy",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_energy"
                            ),
                            "role": "energy",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power"
                            ),
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_active_power"
                            ),
                            "role": "real_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_current"
                            ),
                            "role": "current",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_current"
                            ),
                            "role": "current",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_power_factor"
                            ),
                            "role": "power_factor",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_power_factor"
                            ),
                            "role": "power_factor",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_reactive_power"
                            ),
                            "role": "reactive_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_reactive_power"
                            ),
                            "role": "reactive_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l1_apparent_power"
                            ),
                            "role": "apparent_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_hvac_l2_apparent_power"
                            ),
                            "role": "apparent_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_voltage"
                            ),
                            "role": "voltage",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_voltage"
                            ),
                            "role": "voltage",
                            "leg": "b",
                        },
                    ],
                },
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    usage = coordinator.state.energy_usage_evidence_by_circuit[circuit_id]
    assert usage["baseline_day_count"] >= 7
    assert usage["status"] != "learning"
    assert usage["status"] != "waiting_for_delta"
    assert coordinator.state.learning_by_circuit[circuit_id] is False
    assert coordinator.state.learning_progress_by_circuit[circuit_id][
        "learning"
    ] is False
    weather = coordinator.state.weather_context_by_circuit[circuit_id]
    assert weather["status"] != "learning"
    assert weather["status"] in {
        "weather_correlated",
        "above_weather_adjusted_range",
    }
    assert coordinator.state.standby_status_by_circuit[circuit_id] != "learning"


@pytest.mark.asyncio
async def test_demo_mains_nilm_history_is_seeded_after_learning() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import (
        nilm_workspace_payload,
    )

    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    circuit_id = "mains_nilm"
    states = {
        "sensor.cs_energy_analyzer_demo_mains_l1_energy": ("868.4", "kWh"),
        "sensor.cs_energy_analyzer_demo_mains_l2_energy": ("852.7", "kWh"),
        "sensor.cs_energy_analyzer_demo_mains_l1_active_power": ("1850", "W"),
        "sensor.cs_energy_analyzer_demo_mains_l2_active_power": ("1680", "W"),
        "sensor.cs_energy_analyzer_demo_mains_l1_current": ("15.4", "A"),
        "sensor.cs_energy_analyzer_demo_mains_l2_current": ("14.1", "A"),
        "sensor.cs_energy_analyzer_demo_mains_l1_power_factor": ("0.96", ""),
        "sensor.cs_energy_analyzer_demo_mains_l2_power_factor": ("0.95", ""),
        "sensor.cs_energy_analyzer_demo_mains_l1_reactive_power": ("520", "var"),
        "sensor.cs_energy_analyzer_demo_mains_l2_reactive_power": ("470", "var"),
        "sensor.cs_energy_analyzer_demo_mains_l1_apparent_power": ("1927", "VA"),
        "sensor.cs_energy_analyzer_demo_mains_l2_apparent_power": ("1768", "VA"),
        "sensor.cs_energy_analyzer_demo_mains_l1_voltage": ("119.6", "V"),
        "sensor.cs_energy_analyzer_demo_mains_l2_voltage": ("120.3", "V"),
    }

    class FakeStates:
        def get(self, entity_id: str):
            value, unit = states[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=now,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={DOMAIN: {}}),
        entry_data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_CIRCUITS: [
                {
                    "circuit_id": circuit_id,
                    "name": "Mains NILM",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_energy"
                            ),
                            "role": "energy",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_energy"
                            ),
                            "role": "energy",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_active_power"
                            ),
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_active_power"
                            ),
                            "role": "real_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_current"
                            ),
                            "role": "current",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_current"
                            ),
                            "role": "current",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_power_factor"
                            ),
                            "role": "power_factor",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_power_factor"
                            ),
                            "role": "power_factor",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_reactive_power"
                            ),
                            "role": "reactive_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_reactive_power"
                            ),
                            "role": "reactive_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_apparent_power"
                            ),
                            "role": "apparent_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_apparent_power"
                            ),
                            "role": "apparent_power",
                            "leg": "b",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l1_voltage"
                            ),
                            "role": "voltage",
                            "leg": "a",
                        },
                        {
                            "entity_id": (
                                "sensor.cs_energy_analyzer_demo_mains_l2_voltage"
                            ),
                            "role": "voltage",
                            "leg": "b",
                        },
                    ],
                },
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    usage = coordinator.state.energy_usage_evidence_by_circuit[circuit_id]
    assert usage["baseline_day_count"] >= 7
    assert usage["status"] != "learning"
    assert coordinator.state.learning_by_circuit[circuit_id] is False
    assert coordinator.state.nilm_signature_count_by_circuit[circuit_id] > 0
    unknown_loads = coordinator.state.nilm_unknown_loads_by_circuit[circuit_id]
    assert unknown_loads["unknown_load_count"] > 0
    assert unknown_loads["active_unknown_load_count"] > 0
    sessions = coordinator.store_data.nilm_session_history_by_circuit[circuit_id]
    assert any(session["end"] is not None for session in sessions)
    assert all(session["median_power_w"] > 0 for session in sessions)
    assert all(session["confidence"] > 0 for session in sessions)
    workspace = nilm_workspace_payload([coordinator], circuit_id=circuit_id)
    assert workspace["edge_count"] >= 4
    assert {edge["direction"] for edge in workspace["edges"]} == {"on", "off"}
    assert workspace["label_interval_count"] >= 1
    assert workspace["assignment_count"] >= 1
    assert workspace["virtual_appliance_count"] >= 1
    assert workspace["validation"]["metrics"]["ground_truth_interval_count"] >= 1
    assert workspace["validation"]["metrics"]["prediction_count"] >= 1
    assert workspace["session_count"] >= 2
    assert {session["session_id"] for session in workspace["sessions"]} >= {
        "demo_motor_load_l1_open",
        "demo_resistive_load_240v_session",
    }
    assert any(
        session.get("display_label") == "Demo Pool Pump"
        for session in workspace["sessions"]
    )


def test_runtime_infers_appliance_profiles_from_named_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
        SensorRole,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_refrigerator_energy",
                "sensor.cs_energy_analyzer_demo_hvac_l1_energy",
                "sensor.cs_energy_analyzer_demo_hvac_l2_energy",
                "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
                "sensor.cs_energy_analyzer_demo_hvac_l2_active_power",
                "sensor.cs_energy_analyzer_demo_hvac_l1_current",
                "sensor.cs_energy_analyzer_demo_hvac_l2_current",
                "sensor.cs_energy_analyzer_demo_water_heater_l1_energy",
                "sensor.cs_energy_analyzer_demo_water_heater_l2_energy",
                "sensor.cs_energy_analyzer_demo_water_heater_l1_active_power",
                "sensor.cs_energy_analyzer_demo_water_heater_l2_active_power",
                "sensor.cs_energy_analyzer_demo_water_heater_l1_current",
                "sensor.cs_energy_analyzer_demo_water_heater_l2_current",
                "sensor.cs_energy_analyzer_demo_washer_energy",
                "sensor.cs_energy_analyzer_demo_washer_active_power",
                "sensor.cs_energy_analyzer_demo_washer_current",
                "sensor.cs_energy_analyzer_demo_washer_power_factor",
                "sensor.cs_energy_analyzer_demo_washer_reactive_power",
                "sensor.cs_energy_analyzer_demo_washer_apparent_power",
                "sensor.cs_energy_analyzer_demo_dryer_l1_energy",
                "sensor.cs_energy_analyzer_demo_dryer_l2_energy",
                "sensor.cs_energy_analyzer_demo_dryer_l1_active_power",
                "sensor.cs_energy_analyzer_demo_dryer_l2_active_power",
                "sensor.cs_energy_analyzer_demo_dryer_l1_current",
                "sensor.cs_energy_analyzer_demo_dryer_l2_current",
                "sensor.cs_energy_analyzer_demo_dryer_l1_power_factor",
                "sensor.cs_energy_analyzer_demo_dryer_l2_power_factor",
                "sensor.cs_energy_analyzer_demo_dryer_l1_reactive_power",
                "sensor.cs_energy_analyzer_demo_dryer_l2_reactive_power",
                "sensor.cs_energy_analyzer_demo_dryer_l1_apparent_power",
                "sensor.cs_energy_analyzer_demo_dryer_l2_apparent_power",
                "sensor.cs_energy_analyzer_demo_pool_pump_energy",
                "sensor.cs_energy_analyzer_demo_basement_lights_energy",
                "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
                "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.cs_energy_analyzer_demo_mains_l1_energy",
                "sensor.cs_energy_analyzer_demo_mains_l2_energy",
                "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
                "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
            ],
        },
    )

    by_circuit = {config.circuit_id: config for config in coordinator.circuit_configs}

    assert set(by_circuit) == {
        "cs_energy_analyzer_demo_refrigerator",
        "cs_energy_analyzer_demo_hvac",
        "cs_energy_analyzer_demo_water_heater",
        "cs_energy_analyzer_demo_washer",
        "cs_energy_analyzer_demo_dryer",
        "cs_energy_analyzer_demo_pool_pump",
        "cs_energy_analyzer_demo_basement_lights",
    }
    fridge = by_circuit["cs_energy_analyzer_demo_refrigerator"]
    assert fridge.circuit_id == "cs_energy_analyzer_demo_refrigerator"
    assert fridge.name == "Refrigerator"
    assert fridge.appliance_profile is ApplianceProfile.REFRIGERATOR
    assert fridge.mode is CircuitMode.SINGLE_PHASE
    assert fridge.sensors[0].role is SensorRole.ENERGY
    assert any(
        sensor.entity_id == "sensor.cs_energy_analyzer_demo_mains_l1_voltage"
        and sensor.role is SensorRole.VOLTAGE
        for sensor in fridge.sensors
    )

    hvac = by_circuit["cs_energy_analyzer_demo_hvac"]
    assert hvac.appliance_profile is ApplianceProfile.HVAC
    assert hvac.mode is CircuitMode.DUAL_PHASE
    assert {
        (sensor.entity_id, sensor.role, sensor.leg) for sensor in hvac.sensors
    } >= {
        (
            "sensor.cs_energy_analyzer_demo_hvac_l1_active_power",
            SensorRole.REAL_POWER,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_hvac_l2_active_power",
            SensorRole.REAL_POWER,
            "b",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
            SensorRole.VOLTAGE,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
            SensorRole.VOLTAGE,
            "b",
        ),
    }
    assert not any(
        sensor.entity_id == "sensor.cs_energy_analyzer_demo_hvac_voltage"
        for sensor in hvac.sensors
    )

    water_heater = by_circuit["cs_energy_analyzer_demo_water_heater"]
    assert water_heater.appliance_profile is ApplianceProfile.WATER_HEATER
    assert water_heater.mode is CircuitMode.DUAL_PHASE
    assert {
        (sensor.entity_id, sensor.role, sensor.leg)
        for sensor in water_heater.sensors
    } >= {
        (
            "sensor.cs_energy_analyzer_demo_water_heater_l1_active_power",
            SensorRole.REAL_POWER,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_water_heater_l2_active_power",
            SensorRole.REAL_POWER,
            "b",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
            SensorRole.VOLTAGE,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
            SensorRole.VOLTAGE,
            "b",
        ),
    }
    assert not any(
        sensor.entity_id == "sensor.cs_energy_analyzer_demo_water_heater_voltage"
        for sensor in water_heater.sensors
    )

    washer = by_circuit["cs_energy_analyzer_demo_washer"]
    assert washer.name == "Washer"
    assert washer.appliance_profile is ApplianceProfile.WASHER
    assert washer.mode is CircuitMode.SINGLE_PHASE
    assert {
        (sensor.entity_id, sensor.role, sensor.leg) for sensor in washer.sensors
    } >= {
        (
            "sensor.cs_energy_analyzer_demo_washer_active_power",
            SensorRole.REAL_POWER,
            None,
        ),
        (
            "sensor.cs_energy_analyzer_demo_washer_current",
            SensorRole.CURRENT,
            None,
        ),
        (
            "sensor.cs_energy_analyzer_demo_washer_power_factor",
            SensorRole.POWER_FACTOR,
            None,
        ),
        (
            "sensor.cs_energy_analyzer_demo_washer_reactive_power",
            SensorRole.REACTIVE_POWER,
            None,
        ),
        (
            "sensor.cs_energy_analyzer_demo_washer_apparent_power",
            SensorRole.APPARENT_POWER,
            None,
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
            SensorRole.VOLTAGE,
            "a",
        ),
    }

    dryer = by_circuit["cs_energy_analyzer_demo_dryer"]
    assert dryer.name == "Dryer"
    assert dryer.appliance_profile is ApplianceProfile.DRYER
    assert dryer.mode is CircuitMode.DUAL_PHASE
    assert {
        (sensor.entity_id, sensor.role, sensor.leg) for sensor in dryer.sensors
    } >= {
        (
            "sensor.cs_energy_analyzer_demo_dryer_l1_active_power",
            SensorRole.REAL_POWER,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_dryer_l2_active_power",
            SensorRole.REAL_POWER,
            "b",
        ),
        (
            "sensor.cs_energy_analyzer_demo_dryer_l1_current",
            SensorRole.CURRENT,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_dryer_l2_current",
            SensorRole.CURRENT,
            "b",
        ),
        (
            "sensor.cs_energy_analyzer_demo_dryer_l1_reactive_power",
            SensorRole.REACTIVE_POWER,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_dryer_l2_apparent_power",
            SensorRole.APPARENT_POWER,
            "b",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
            SensorRole.VOLTAGE,
            "a",
        ),
        (
            "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
            SensorRole.VOLTAGE,
            "b",
        ),
    }

    pool_pump = by_circuit["cs_energy_analyzer_demo_pool_pump"]
    assert pool_pump.appliance_profile is ApplianceProfile.POOL_PUMP
    assert pool_pump.mode is CircuitMode.SINGLE_PHASE

    lights = by_circuit["cs_energy_analyzer_demo_basement_lights"]
    assert lights.appliance_profile is ApplianceProfile.MIXED
    assert lights.mode is CircuitMode.MIXED


def test_runtime_merges_new_prefixed_source_sensor_into_existing_config() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import SensorRole

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                "sensor.car_charger_l1_active_power",
                "sensor.car_charger_l2_active_power",
                "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            ],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "car_charger",
                    "name": "Car Charger",
                    "appliance_profile": "ev_charger",
                    "mode": "dual_phase",
                    "sensors": [
                        {
                            "entity_id": "sensor.car_charger_l1_active_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.car_charger_l2_active_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                }
            ],
        },
    )

    assert [config.circuit_id for config in coordinator.circuit_configs] == [
        "car_charger"
    ]
    assert {
        (sensor.entity_id, sensor.role, sensor.leg)
        for sensor in coordinator.circuit_configs[0].sensors
    } == {
        (
            "sensor.car_charger_l1_active_power",
            SensorRole.REAL_POWER,
            "a",
        ),
        (
            "sensor.car_charger_l2_active_power",
            SensorRole.REAL_POWER,
            "b",
        ),
        (
            "sensor.circuitsetup_energy_analyzer_car_charger_l1_current",
            SensorRole.CURRENT,
            "a",
        ),
    }


def test_runtime_infers_vehicle_charging_sources_as_dual_phase_ev_charger() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
        SensorRole,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                "sensor.garage_vehicle_charging_l1_active_power",
                "sensor.garage_vehicle_charging_l2_active_power",
                "sensor.garage_vehicle_charging_l1_current",
                "sensor.garage_vehicle_charging_l2_current",
                "sensor.garage_vehicle_charging_l1_power_factor",
                "sensor.garage_vehicle_charging_l2_power_factor",
                "sensor.panel_mains_l1_voltage",
                "sensor.panel_mains_l2_voltage",
            ],
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.panel_mains_l1_voltage",
                "sensor.panel_mains_l2_voltage",
            ],
        },
    )

    config = coordinator.circuit_configs[0]

    assert config.circuit_id == "garage_vehicle_charging"
    assert config.name == "Garage Vehicle Charging"
    assert config.appliance_profile is ApplianceProfile.EV_CHARGER
    assert config.mode is CircuitMode.DUAL_PHASE
    assert {
        (sensor.entity_id, sensor.role, sensor.leg) for sensor in config.sensors
    } >= {
        (
            "sensor.garage_vehicle_charging_l1_active_power",
            SensorRole.REAL_POWER,
            "a",
        ),
        (
            "sensor.garage_vehicle_charging_l2_active_power",
            SensorRole.REAL_POWER,
            "b",
        ),
        ("sensor.panel_mains_l1_voltage", SensorRole.VOLTAGE, "a"),
        ("sensor.panel_mains_l2_voltage", SensorRole.VOLTAGE, "b"),
    }


@pytest.mark.parametrize(
    ("circuit_id", "expected_name", "expected_profile", "expected_mode", "suffixes"),
    [
        (
            "car_charger",
            "Car Charger",
            "EV_CHARGER",
            "DUAL_PHASE",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "hvac",
            "Hvac",
            "HVAC",
            "DUAL_PHASE",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "dryer",
            "Dryer",
            "DRYER",
            "DUAL_PHASE",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "water_heater",
            "Water Heater",
            "WATER_HEATER",
            "DUAL_PHASE",
            ("power_l1", "current_l1", "power_l2", "current_l2"),
        ),
        (
            "refrigerator",
            "Refrigerator",
            "REFRIGERATOR",
            "SINGLE_PHASE",
            ("power_l1", "current_l1"),
        ),
    ],
)
def test_runtime_groups_appliance_sources_with_metric_before_leg(
    circuit_id: str,
    expected_name: str,
    expected_profile: str,
    expected_mode: str,
    suffixes: tuple[str, ...],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
        SensorRole,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                f"sensor.{circuit_id}_{suffix}" for suffix in suffixes
            ],
        },
    )

    assert [config.circuit_id for config in coordinator.circuit_configs] == [circuit_id]
    config = coordinator.circuit_configs[0]
    assert config.name == expected_name
    assert config.appliance_profile is getattr(ApplianceProfile, expected_profile)
    assert config.mode is getattr(CircuitMode, expected_mode)
    assert {
        (sensor.entity_id, sensor.role, sensor.leg) for sensor in config.sensors
    } == {
        (
            f"sensor.{circuit_id}_{suffix}",
            (
                SensorRole.CURRENT
                if suffix.startswith("current")
                else SensorRole.REAL_POWER
            ),
            "b" if suffix.endswith("l2") else "a",
        )
        for suffix in suffixes
    }


def test_runtime_infers_recommended_v1_appliance_taxonomy_from_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_SOURCE_ENTITIES: [
                "sensor.garage_ac_compressor_l1_active_power",
                "sensor.garage_ac_compressor_l2_active_power",
                "sensor.air_handler_active_power",
                "sensor.air_handler_current",
                "sensor.aux_heat_l1_active_power",
                "sensor.aux_heat_l2_active_power",
                "sensor.well_pump_active_power",
                "sensor.pool_pump_active_power",
                "sensor.sump_pump_active_power",
                "sensor.kitchen_microwave_active_power",
            ],
        },
    )

    by_circuit = {config.circuit_id: config for config in coordinator.circuit_configs}

    assert by_circuit["garage_ac_compressor"].appliance_profile is (
        ApplianceProfile.HVAC_COMPRESSOR
    )
    assert by_circuit["garage_ac_compressor"].mode is CircuitMode.DUAL_PHASE
    assert by_circuit["air_handler"].appliance_profile is ApplianceProfile.HVAC_BLOWER
    assert by_circuit["air_handler"].mode is CircuitMode.SINGLE_PHASE
    assert by_circuit["aux_heat"].appliance_profile is ApplianceProfile.ELECTRIC_HEAT
    assert by_circuit["aux_heat"].mode is CircuitMode.DUAL_PHASE
    assert by_circuit["well_pump"].appliance_profile is ApplianceProfile.WATER_PUMP
    assert by_circuit["pool_pump"].appliance_profile is ApplianceProfile.POOL_PUMP
    assert by_circuit["sump_pump"].appliance_profile is ApplianceProfile.SUMP_PUMP
    assert by_circuit["kitchen_microwave"].appliance_profile is (
        ApplianceProfile.MICROWAVE
    )
    assert by_circuit["kitchen_microwave"].mode is CircuitMode.SINGLE_PHASE


def test_runtime_accepts_car_charger_as_manual_appliance_profile_alias() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "garage_charger",
                    "name": "Garage Car Charger",
                    "mode": "dual_phase",
                    "appliance_profile": "car_charger",
                    "sensors": [
                        {
                            "entity_id": "sensor.garage_charger_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.garage_charger_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                }
            ],
        },
    )

    config = coordinator.circuit_configs[0]

    assert config.appliance_profile is ApplianceProfile.EV_CHARGER
    assert config.mode is CircuitMode.DUAL_PHASE


def test_runtime_accepts_microwave_oven_as_manual_appliance_profile_alias() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "kitchen_microwave",
                    "name": "Kitchen Microwave",
                    "mode": "single_phase",
                    "appliance_profile": "microwave_oven",
                    "sensors": [
                        {
                            "entity_id": "sensor.kitchen_microwave_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
    )

    config = coordinator.circuit_configs[0]

    assert config.appliance_profile is ApplianceProfile.MICROWAVE


def test_runtime_uses_circuits_saved_from_options_flow_assignments() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitMode,
        SensorRole,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "old_mixed",
                    "name": "Old Mixed",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {
                            "entity_id": "sensor.old_mixed_power",
                            "role": "real_power",
                        }
                    ],
                }
            ],
        },
        options={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "air_handler",
                    "name": "Air Handler",
                    "mode": "single_phase",
                    "appliance_profile": "hvac_blower",
                    "sensors": [
                        {
                            "entity_id": "sensor.air_handler_active_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.air_handler_current",
                            "role": "current",
                        },
                    ],
                }
            ],
        },
    )

    assert len(coordinator.circuit_configs) == 1
    config = coordinator.circuit_configs[0]
    assert config.circuit_id == "air_handler"
    assert config.appliance_profile is ApplianceProfile.HVAC_BLOWER
    assert config.mode is CircuitMode.SINGLE_PHASE
    assert {
        (sensor.entity_id, sensor.role) for sensor in config.sensors
    } == {
        ("sensor.air_handler_active_power", SensorRole.REAL_POWER),
        ("sensor.air_handler_current", SensorRole.CURRENT),
    }


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
    holder = {"l1": 0.0, "l2": 0.0, "time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mains_l1_power": str(holder["l1"]),
                "sensor.mains_l2_power": str(holder["l2"]),
            }
            return SimpleNamespace(
                state=values[entity_id],
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

    await coordinator.async_process_update()
    holder.update({"l1": 125.0, "l2": 175.0, "time": now + timedelta(seconds=30)})
    await coordinator.async_process_update()
    holder["time"] = now + timedelta(seconds=60)
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


def test_nilm_signature_payloads_reuse_review_by_stable_fingerprint() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmSignature,
        nilm_signature_fingerprint,
    )

    saved_signature = NilmSignature(
        signature_id="on-1",
        median_delta_w=612.0,
        median_delta_var=142.0,
        median_delta_va=628.0,
        median_delta_pf=-0.03,
        occurrence_count=3,
        confidence=0.7,
        median_leg_a_delta_w=610.0,
        median_leg_b_delta_w=15.0,
        leg_balance_ratio=0.95,
        dominant_leg="a",
        split_phase_type="single_leg_a",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "on-1",
                        "feedback_fingerprint": nilm_signature_fingerprint(
                            saved_signature
                        ),
                        "median_delta_w": saved_signature.median_delta_w,
                        "median_delta_var": saved_signature.median_delta_var,
                        "median_delta_va": saved_signature.median_delta_va,
                        "median_delta_pf": saved_signature.median_delta_pf,
                        "split_phase_type": saved_signature.split_phase_type,
                        "dominant_leg": saved_signature.dominant_leg,
                        "user_label": "Guest room heater",
                        "expected": True,
                        "review_state": "expected",
                    }
                ]
            }
        ),
    )

    payloads = coordinator._nilm_signature_payloads(
        "mains",
        [
            NilmSignature(
                signature_id="on-2",
                median_delta_w=625.0,
                median_delta_var=151.0,
                median_delta_va=638.0,
                median_delta_pf=-0.02,
                occurrence_count=6,
                confidence=0.9,
                median_leg_a_delta_w=625.0,
                median_leg_b_delta_w=18.0,
                leg_balance_ratio=0.94,
                dominant_leg="a",
                split_phase_type="single_leg_a",
            )
        ],
    )

    assert payloads[0]["signature_id"] == "on-2"
    assert payloads[0]["user_label"] == "Guest room heater"
    assert payloads[0]["expected"] is True
    assert payloads[0]["review_state"] == "expected"


def test_nilm_signature_payloads_remap_merge_target_by_stable_fingerprint() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmSignature,
        nilm_signature_fingerprint,
    )

    source = NilmSignature("on-1", 600.0, 140.0, 620.0, -0.02, 3, 0.7)
    target = NilmSignature(
        "on-2",
        1800.0,
        80.0,
        1810.0,
        0.0,
        4,
        0.8,
        dominant_leg="balanced",
        split_phase_type="balanced_240v",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": source.signature_id,
                        "feedback_fingerprint": nilm_signature_fingerprint(source),
                        "median_delta_w": source.median_delta_w,
                        "median_delta_var": source.median_delta_var,
                        "median_delta_va": source.median_delta_va,
                        "split_phase_type": source.split_phase_type,
                        "review_state": "merged",
                        "merged_into": target.signature_id,
                        "merged_into_fingerprint": nilm_signature_fingerprint(target),
                    },
                    {
                        "signature_id": target.signature_id,
                        "feedback_fingerprint": nilm_signature_fingerprint(target),
                        "median_delta_w": target.median_delta_w,
                        "median_delta_var": target.median_delta_var,
                        "median_delta_va": target.median_delta_va,
                        "split_phase_type": target.split_phase_type,
                        "review_state": "expected",
                    },
                ]
            }
        ),
    )

    payloads = coordinator._nilm_signature_payloads(
        "mains",
        [
            NilmSignature("on-4", 610.0, 145.0, 630.0, -0.02, 6, 0.9),
            NilmSignature(
                "on-5",
                1815.0,
                85.0,
                1822.0,
                0.0,
                5,
                0.9,
                dominant_leg="balanced",
                split_phase_type="balanced_240v",
            ),
        ],
    )

    by_id = {payload["signature_id"]: payload for payload in payloads}
    assert by_id["on-4"]["review_state"] == "merged"
    assert by_id["on-4"]["merged_into"] == "on-5"
    assert by_id["on-5"]["review_state"] == "expected"


@pytest.mark.asyncio
async def test_runtime_known_load_option_controls_nilm_masking() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def __init__(self, watts: float, timestamp: datetime) -> None:
            self.watts = watts
            self.time = timestamp

        def get(self, entity_id: str):
            value = self.watts if "mains" in entity_id else max(self.watts - 100, 0)
            return SimpleNamespace(
                state=str(value),
                attributes={"unit_of_measurement": "W"},
                last_updated=self.time,
            )

    async def unmatched_percentage_for(known_load_circuits: list[str]) -> float:
        states = FakeStates(100, now)
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
            now_fn=lambda: states.time,
        )
        await coordinator.async_process_update()
        states.time = now + timedelta(seconds=30)
        states.watts = 420
        await coordinator.async_process_update()
        states.time = now + timedelta(seconds=60)
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
    holder["time"] = now + timedelta(seconds=60)
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        (0, 100.0, 100.0, 0.0),
        (30, 400.0, 100.0, 300.0),
        (60, 400.0, 100.0, 300.0),
        (120, 100.0, 100.0, 0.0),
        (180, 100.0, 100.0, 0.0),
        (240, 410.0, 100.0, 310.0),
        (270, 410.0, 100.0, 310.0),
        (330, 100.0, 100.0, 0.0),
        (390, 100.0, 100.0, 0.0),
        (450, 420.0, 100.0, 320.0),
        (480, 420.0, 100.0, 320.0),
    ]
    for seconds, l1_w, l2_w, fridge_w in readings:
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=seconds),
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
    holder["time"] = now + timedelta(seconds=60)
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        (0, 100.0, 100.0, 0.0),
        (30, 400.0, 100.0, 300.0),
        (60, 400.0, 100.0, 300.0),
        (120, 100.0, 100.0, 0.0),
        (180, 100.0, 100.0, 0.0),
        (240, 410.0, 100.0, 310.0),
        (270, 410.0, 100.0, 310.0),
        (330, 100.0, 100.0, 0.0),
        (390, 100.0, 100.0, 0.0),
        (450, 420.0, 100.0, 320.0),
        (480, 420.0, 100.0, 320.0),
    ]
    for seconds, l1_w, l2_w, fridge_w in readings:
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=seconds),
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        (0, 100.0, 100.0, 0.0),
        (30, 400.0, 400.0, 600.0),
        (60, 400.0, 400.0, 600.0),
        (120, 100.0, 100.0, 0.0),
        (180, 100.0, 100.0, 0.0),
        (240, 410.0, 410.0, 620.0),
        (270, 410.0, 410.0, 620.0),
        (330, 100.0, 100.0, 0.0),
        (390, 100.0, 100.0, 0.0),
        (450, 420.0, 420.0, 640.0),
        (480, 420.0, 420.0, 640.0),
    ]
    for seconds, l1_w, l2_w, fridge_w in readings:
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=seconds),
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        (0, 100.0, 100.0, 0.0),
        (30, 400.0, 400.0, 480.0),
        (60, 400.0, 400.0, 480.0),
        (120, 100.0, 100.0, 0.0),
        (180, 100.0, 100.0, 0.0),
        (240, 410.0, 410.0, 496.0),
        (270, 410.0, 410.0, 496.0),
        (330, 100.0, 100.0, 0.0),
        (390, 100.0, 100.0, 0.0),
        (450, 420.0, 420.0, 512.0),
        (480, 420.0, 420.0, 512.0),
    ]
    for seconds, l1_w, l2_w, fridge_w in readings:
        holder.update(
            {
                "l1": l1_w,
                "l2": l2_w,
                "fridge": fridge_w,
                "time": now + timedelta(seconds=seconds),
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
    from custom_components.circuitsetup_energy_analyzer.alerting import Observation

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
        Observation(
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

        async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        holder["time"] = now + timedelta(days=offset)
        daily_events = []
        for day_offset in range(1, 11):
            start = holder["time"] - timedelta(days=day_offset, hours=2)
            daily_events.extend(
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
        daily_events.append(
            CircuitEvent(
                timestamp=holder["time"] - timedelta(minutes=45),
                circuit_id="fridge",
                event_type=EventType.START,
            )
        )
        coordinator.store_data.events = daily_events
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
    assert readiness["cycle_count"] == 1
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

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
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


def test_coordinator_canonicalizes_legacy_sensitivity_config_copies() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        entry_data={
            CONF_SENSITIVITY: "low",
            "advanced_settings": {
                "freezer": {"preset": "standard"},
            },
        },
        options={
            CONF_SENSITIVITY: "high",
            "advanced_settings": {
                "dryer": {"preset": "high"},
            },
        },
    )

    assert coordinator.entry_data[CONF_SENSITIVITY] == "quiet"
    assert coordinator.entry_data["advanced_settings"]["freezer"]["preset"] == (
        "balanced"
    )
    assert coordinator.options[CONF_SENSITIVITY] == "sensitive"
    assert coordinator.options["advanced_settings"]["dryer"]["preset"] == "sensitive"


@pytest.mark.asyncio
async def test_expected_alert_feedback_suppresses_repeated_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
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
async def test_contextual_alert_feedback_only_suppresses_matching_context(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )
    hot_context = {
        "comparison_basis": "contextual",
        "baseline_context": "season=summer|temperature_bin=very_hot",
        "baseline_fallback_level": "exact",
    }
    mild_context = {
        "comparison_basis": "contextual",
        "baseline_context": "season=summer|temperature_bin=mild",
        "baseline_fallback_level": "exact",
    }
    expected_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Expected hot day use",
        feature="daily_energy_spike",
        features=hot_context,
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        store_data=FeatureStoreData(alerts=[expected_alert]),
        now_fn=lambda: datetime(2026, 6, 2, 12, 5, tzinfo=UTC),
    )

    assert (
        await coordinator.async_mark_alert_expected(
            notification_id_for_alert(expected_alert)
        )
        is True
    )
    assert (
        coordinator.store_data.alert_feedback[
            alert_feedback_fingerprint(expected_alert)
        ]["action"]
        == "expected"
    )

    repeated_hot_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Expected hot day use again",
        feature="daily_energy_spike",
        features=hot_context,
    )
    mild_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Mild day use needs attention",
        feature="daily_energy_spike",
        features=mild_context,
    )

    await coordinator._notify_alert(repeated_hot_alert)
    await coordinator._notify_alert(mild_alert)

    assert notifications == [mild_alert]


@pytest.mark.asyncio
async def test_alert_feedback_methods_store_fingerprint_key() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
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

    assert (
        await coordinator.async_mark_alert_expected(notification_id_for_alert(alert))
        is True
    )

    fingerprint = alert_feedback_fingerprint(alert)
    feedback = coordinator.store_data.alert_feedback[fingerprint]
    assert feedback["fingerprint"] == fingerprint
    assert feedback["status"] == "expected"
    assert feedback["action"] == "expected"
    assert feedback["alert_id"] == notification_id_for_alert(alert)
    assert feedback["source_alert_id"] == notification_id_for_alert(alert)
    assert feedback["circuit_id"] == "fridge"
    assert feedback["feature"] == "reactive_power"
    assert feedback["evidence_count"] == 1
    assert feedback["expires_at"] == "2026-08-31T12:05:00+00:00"

    unhelpful_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 1, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="power_factor",
        observed_value=0.62,
        baseline_value=0.95,
        change_ratio=-0.35,
    )
    coordinator.store_data.alerts.append(unhelpful_alert)

    assert (
        await coordinator.async_mark_alert_unhelpful(
            notification_id_for_alert(unhelpful_alert)
        )
        is True
    )

    unhelpful_fingerprint = alert_feedback_fingerprint(unhelpful_alert)
    assert coordinator.store_data.alert_feedback[unhelpful_fingerprint][
        "action"
    ] == "unhelpful"
    assert coordinator.store_data.alert_feedback[unhelpful_fingerprint][
        "expires_at"
    ] == "2026-07-17T12:05:00+00:00"


@pytest.mark.parametrize(
    ("method_name", "feedback_action"),
    [
        ("async_mark_alert_expected", "expected"),
        ("async_mark_alert_unhelpful", "unhelpful"),
    ],
)
@pytest.mark.asyncio
async def test_alert_feedback_methods_store_feedback_and_retire_visible_alert(
    method_name: str,
    feedback_action: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
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
    coordinator.state.active_alerts_by_circuit = {"fridge": [alert]}
    coordinator.state.anomaly_score_by_circuit = {"fridge": 1.1}

    alert_id = notification_id_for_alert(alert)
    result = await getattr(coordinator, method_name)(alert_id)

    assert result is True
    fingerprint = alert_feedback_fingerprint(alert)
    assert coordinator.store_data.alert_feedback[fingerprint]["action"] == (
        feedback_action
    )
    assert coordinator.store_data.alert_feedback[fingerprint]["alert_id"] == alert_id
    assert [
        notification_id_for_alert(stored_alert)
        for stored_alert in coordinator.store_data.alerts
    ] == []
    assert coordinator.state.active_alerts_by_circuit.get("fridge", []) == []


@pytest.mark.asyncio
async def test_alert_feedback_methods_report_stale_alert_ids() -> None:
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
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(),
        store_data=FeatureStoreData(alerts=[alert]),
    )

    assert await coordinator.async_mark_alert_expected("missing-alert") is False
    assert await coordinator.async_mark_alert_unhelpful("missing-alert") is False
    assert await coordinator.async_acknowledge_alert("missing-alert") is False

    alert_id = notification_id_for_alert(alert)
    assert await coordinator.async_mark_alert_expected(alert_id) is True
    assert await coordinator.async_acknowledge_alert(alert_id) is False


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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
async def test_runtime_detects_motor_power_quality_shift_from_watts_amps_pf_and_var(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.pool_pump_energy": "348.7",
                "sensor.pool_pump_power": "950",
                "sensor.pool_pump_current": "8.5",
                "sensor.pool_pump_var": "580",
                "sensor.pool_pump_pf": "0.86",
            }
            units = {
                "sensor.pool_pump_energy": "kWh",
                "sensor.pool_pump_power": "W",
                "sensor.pool_pump_current": "A",
                "sensor.pool_pump_var": "var",
                "sensor.pool_pump_pf": "",
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
                    "circuit_id": "pool_pump",
                    "name": "Pool Pump",
                    "mode": "single_phase",
                    "appliance_profile": "pool_pump",
                    "sensors": [
                        {"entity_id": "sensor.pool_pump_energy", "role": "energy"},
                        {"entity_id": "sensor.pool_pump_power", "role": "real_power"},
                        {"entity_id": "sensor.pool_pump_current", "role": "current"},
                        {
                            "entity_id": "sensor.pool_pump_var",
                            "role": "reactive_power",
                        },
                        {"entity_id": "sensor.pool_pump_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="pool_pump",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "pool_pump:real_power": BaselineStats(
                    "real_power", 20, 940.0, 30.0, 890.0, 980.0, 1.0
                ),
                "pool_pump:reactive_power": BaselineStats(
                    "reactive_power", 20, 220.0, 25.0, 180.0, 260.0, 1.0
                ),
                "pool_pump:power_factor": BaselineStats(
                    "power_factor", 20, 0.97, 0.02, 0.94, 0.99, 1.0
                ),
                "pool_pump:reactive_to_real_ratio": BaselineStats(
                    "reactive_to_real_ratio", 20, 0.23, 0.03, 0.18, 0.28, 1.0
                ),
                "pool_pump:power_factor_deficit": BaselineStats(
                    "power_factor_deficit", 20, 0.03, 0.01, 0.01, 0.06, 1.0
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
    assert "reactive power changed" in alert.message
    assert alert.features["real_power"] < 1.0
    assert alert.features["reactive_power"] > 1.5
    assert alert.features["reactive_to_real_ratio"] > 1.5
    assert alert.features["power_factor"] > 1.5
    assert alert.features["power_factor_deficit"] > 1.5
    assert coordinator.state.power_quality_score_by_circuit["pool_pump"] > 1.5
    assert coordinator.state.power_quality_evidence_by_circuit["pool_pump"]
    assert coordinator.state.reactive_power_drift_by_circuit["pool_pump"] > 1.0
    assert coordinator.state.power_factor_drift_by_circuit["pool_pump"] > 0.1
    assert coordinator.state.apparent_power_drift_by_circuit["pool_pump"] == 0.0
    assert (
        coordinator.state.metric_consistency_status_by_circuit["pool_pump"]
        == "missing_metrics"
    )


@pytest.mark.asyncio
async def test_runtime_mixed_circuit_tracks_power_quality_without_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
async def test_runtime_marks_energy_usage_waiting_for_delta() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.hvac_energy"
            return SimpleNamespace(
                state="108.4",
                attributes={"unit_of_measurement": "kWh"},
                last_updated=now,
            )

    hass = SimpleNamespace(states=FakeStates(), data={DOMAIN: {}})
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id="entry-1",
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_energy", "role": "energy"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    evidence = coordinator.state.energy_usage_evidence_by_circuit["hvac"]
    assert evidence["status"] == "waiting_for_delta"
    assert evidence["status_label"] == "Waiting For Energy Change"
    assert evidence["status_reason"] == "first_cumulative_sample"
    assert "cumulative kWh" in evidence["status_explanation"]
    assert evidence["suggested_next_check"] == (
        "Let the analyzer see the energy sensor increase, or confirm the circuit "
        "has a cumulative kWh source."
    )


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
async def test_coordinator_builds_settings_recommendation_after_maturity() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.25},
            },
        },
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "hvac": {
                    "days": [
                        {"usage_kwh": 5.8},
                        {"usage_kwh": 6.1},
                        {"usage_kwh": 7.4},
                        {"usage_kwh": 6.7},
                        {"usage_kwh": 8.9},
                        {"usage_kwh": 9.8},
                        {"usage_kwh": 7.9},
                    ],
                }
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_recalculate_setting_recommendations()

    recommendation = coordinator.state.settings_recommendations_by_circuit["hvac"][0]
    assert recommendation["setting_key"] == "daily_spike_ratio"
    assert recommendation["setting_label"] == "Daily Spike Ratio"
    assert recommendation["suggested_value"] == 0.3
    assert coordinator.state.settings_recommendation_count_by_circuit["hvac"] == 1


@pytest.mark.asyncio
async def test_coordinator_builds_operating_detection_recommendations_after_maturity(
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    base = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
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
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=base + timedelta(days=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                    features={"startup_power_w": value},
                )
                for index, value in enumerate((84.5, 88.0, 90.0, 92.0, 96.0, 101.0))
            ],
            standby_by_circuit={
                "fridge": {
                    "samples": [
                        {
                            "timestamp": (
                                base + timedelta(hours=index * 16)
                            ).isoformat(),
                            "real_power_w": value,
                        }
                        for index, value in enumerate(
                            (
                                4.2,
                                4.8,
                                5.1,
                                5.4,
                                5.8,
                                6.0,
                                6.2,
                                6.4,
                                6.5,
                                6.7,
                                6.8,
                                6.9,
                                7.0,
                                7.2,
                            )
                        )
                    ]
                }
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_recalculate_setting_recommendations()

    recommendations = coordinator.state.settings_recommendations_by_circuit["fridge"]
    setting_keys = {recommendation["setting_key"] for recommendation in recommendations}
    assert {
        "operating_on_threshold_w",
        "operating_off_threshold_w",
    }.issubset(setting_keys)
    by_key = {
        recommendation["setting_key"]: recommendation
        for recommendation in recommendations
    }
    assert by_key["operating_on_threshold_w"]["suggested_value"] == 45.0
    assert by_key["operating_off_threshold_w"]["suggested_value"] == 15.0


@pytest.mark.asyncio
async def test_repeated_unhelpful_alert_suggests_safe_daily_spike_setting() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    prior_alert = AlertEvidence(
        timestamp=now - timedelta(days=1),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Daily usage spike",
        feature="daily_energy_usage_spike",
        observed_value=3.0,
        baseline_value=2.0,
        change_ratio=0.5,
    )
    fingerprint = alert_feedback_fingerprint(prior_alert)
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "fridge": {"daily_spike_ratio": 0.25},
            },
        },
        store_data=FeatureStoreData(
            alert_feedback={
                fingerprint: {
                    "fingerprint": fingerprint,
                    "status": "unhelpful",
                    "action": "unhelpful",
                    "decided_at": (now - timedelta(days=1)).isoformat(),
                    "created_at": (now - timedelta(days=2)).isoformat(),
                    "expires_at": (now + timedelta(days=30)).isoformat(),
                    "last_seen": (now - timedelta(days=1)).isoformat(),
                    "circuit_id": "fridge",
                    "feature": "daily_energy_usage_spike",
                    "change_ratio": 0.5,
                    "observed_value": 3.0,
                    "baseline_value": 2.0,
                    "evidence_count": 2,
                },
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_recalculate_setting_recommendations("fridge")

    recommendation = coordinator.state.settings_recommendations_by_circuit["fridge"][0]
    assert recommendation["setting_key"] == "daily_spike_ratio"
    assert recommendation["suggested_value"] == 0.6
    assert recommendation["current_value"] == 0.25
    assert recommendation["evidence"]["source"] == "unhelpful_alert_feedback"
    assert recommendation["evidence"]["unhelpful_feedback_count"] == 2
    assert coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"][
        "daily_spike_ratio"
    ] == 0.25


@pytest.mark.asyncio
async def test_apply_setting_recommendation_updates_advanced_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(settings_advisor)
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.25},
            },
        },
        store_data=FeatureStoreData(
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
    )

    await coordinator.async_apply_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"]["daily_spike_ratio"]
        == 0.3
    )
    assert (
        coordinator.store_data.energy_usage_settings_by_circuit["hvac"][
            "daily_spike_ratio"
        ]
        == 0.3
    )
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is settings_advisor.RecommendationStatus.APPLIED
    )
    recommendations = coordinator.state.settings_recommendations_by_circuit["hvac"]
    assert recommendations[0]["recommendation_id"] == recommendation.recommendation_id
    assert recommendations[0]["status"] == "applied"
    assert (
        coordinator.state.settings_recommendation_count_by_circuit.get("hvac", 0)
        == 0
    )


@pytest.mark.asyncio
async def test_apply_operating_detection_recommendation_preserves_learned_source(
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(
        settings_advisor,
        recommendation_id="fridge:operating_on_threshold_w:v1",
        unique_key="fridge:operating_on_threshold_w",
        circuit_id="fridge",
        circuit_name="Kitchen Fridge",
        setting_key="operating_on_threshold_w",
        setting_label="Turn-On Power",
        current_value=25.0,
        suggested_value=45.0,
        unit="W",
        feature="operating_detection_thresholds",
        group="Operating Detection",
        apply_payload={"operating_on_threshold_w": 45.0},
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
        store_data=FeatureStoreData(
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
    )

    await coordinator.async_apply_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"][
            "operating_on_threshold_w"
        ]
        == 45.0
    )
    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"][
            "operating_detection_source"
        ]
        == "learned_recommendation"
    )
    assert (
        coordinator.store_data.operating_detection_settings_by_circuit["fridge"][
            "operating_detection_source"
        ]
        == "learned_recommendation"
    )


@pytest.mark.asyncio
async def test_undo_setting_recommendation_restores_previous_value() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(
        settings_advisor,
        status=settings_advisor.RecommendationStatus.APPLIED,
    )
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.3},
            },
        },
        store_data=FeatureStoreData(
            energy_usage_settings_by_circuit={"hvac": {"daily_spike_ratio": 0.3}},
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
    )

    await coordinator.async_undo_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"]["daily_spike_ratio"]
        == 0.25
    )
    assert (
        coordinator.store_data.energy_usage_settings_by_circuit["hvac"][
            "daily_spike_ratio"
        ]
        == 0.25
    )
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is settings_advisor.RecommendationStatus.PENDING
    )


@pytest.mark.asyncio
async def test_reset_setting_recommendation_restores_builtin_default() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(
        settings_advisor,
        current_value=0.35,
        suggested_value=0.5,
        apply_payload={"daily_spike_ratio": 0.5},
    )
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.35},
            },
        },
        store_data=FeatureStoreData(
            energy_usage_settings_by_circuit={"hvac": {"daily_spike_ratio": 0.35}},
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
    )

    await coordinator.async_reset_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"]["daily_spike_ratio"]
        == 0.25
    )
    assert (
        coordinator.store_data.energy_usage_settings_by_circuit["hvac"][
            "daily_spike_ratio"
        ]
        == 0.25
    )
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is settings_advisor.RecommendationStatus.STALE
    )


@pytest.mark.asyncio
async def test_deny_setting_recommendation_records_decision() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(settings_advisor)
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
        store_data=FeatureStoreData(
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
        now_fn=lambda: datetime(2026, 6, 3, 9, 30, tzinfo=UTC),
    )

    await coordinator.async_deny_setting_recommendation(
        recommendation.recommendation_id,
    )

    decision = coordinator.store_data.settings_recommendation_decisions[
        recommendation.unique_key
    ]
    assert decision.status is settings_advisor.RecommendationStatus.DENIED
    assert decision.denied_value == recommendation.suggested_value
    assert decision.evidence_fingerprint == (
        settings_advisor.recommendation_evidence_fingerprint(recommendation)
    )
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is settings_advisor.RecommendationStatus.DENIED
    )


@pytest.mark.asyncio
async def test_dismiss_setting_recommendation_records_decision() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    recommendation = _settings_recommendation(settings_advisor)
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
        store_data=FeatureStoreData(
            settings_recommendations={
                recommendation.recommendation_id: recommendation,
            },
        ),
        now_fn=lambda: datetime(2026, 6, 3, 9, 30, tzinfo=UTC),
    )

    await coordinator.async_dismiss_setting_recommendation(
        recommendation.recommendation_id,
    )

    decision = coordinator.store_data.settings_recommendation_decisions[
        recommendation.unique_key
    ]
    assert decision.status is settings_advisor.RecommendationStatus.DISMISSED
    assert decision.denied_value == recommendation.suggested_value
    assert decision.evidence_fingerprint == (
        settings_advisor.recommendation_evidence_fingerprint(recommendation)
    )
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is settings_advisor.RecommendationStatus.DISMISSED
    )


def test_settings_recommendation_notification_id_is_entry_scoped() -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    assert notifications.settings_recommendation_notification_id("entry-1") == (
        f"{DOMAIN}_settings_recommendations_entry_1"
    )


@pytest.mark.asyncio
async def test_process_update_builds_settings_recommendation_after_maturity() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.25},
            },
        },
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "hvac": {
                    "days": [
                        {"usage_kwh": 5.8},
                        {"usage_kwh": 6.1},
                        {"usage_kwh": 7.4},
                        {"usage_kwh": 6.7},
                        {"usage_kwh": 8.9},
                        {"usage_kwh": 9.8},
                        {"usage_kwh": 7.9},
                    ],
                }
            },
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    recommendation = coordinator.state.settings_recommendations_by_circuit["hvac"][0]
    assert recommendation["setting_key"] == "daily_spike_ratio"
    assert recommendation["suggested_value"] == 0.3
    assert coordinator.state.settings_recommendation_count_by_circuit["hvac"] == 1


@pytest.mark.asyncio
async def test_process_update_preserves_recommendation_episode_on_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    saved: list[FeatureStoreData] = []
    notifications: list[dict[str, Any]] = []

    class FakeStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved.append(self.data)

    async def fake_notification(hass, entry_id, *, total_pending):
        notifications.append(
            {
                "entry_id": entry_id,
                "total_pending": total_pending,
            }
        )

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_settings_recommendation_notification",
        fake_notification,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    now_holder = {"value": now}
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "hvac": {
                "days": [
                    {"date": "2026-05-26", "usage_kwh": 5.8},
                    {"date": "2026-05-27", "usage_kwh": 6.1},
                    {"date": "2026-05-28", "usage_kwh": 7.4},
                    {"date": "2026-05-29", "usage_kwh": 6.7},
                    {"date": "2026-05-30", "usage_kwh": 8.9},
                    {"date": "2026-05-31", "usage_kwh": 9.8},
                    {"date": "2026-06-01", "usage_kwh": 7.9},
                ],
            }
        },
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_id="entry-1",
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.25},
            },
        },
        store=FakeStore(),
        store_data=store_data,
        now_fn=lambda: now_holder["value"],
    )

    await coordinator.async_process_update()
    first = store_data.settings_recommendations["hvac:daily_spike_ratio:v1"]
    first_created_at = first.created_at
    first_expires_at = first.expires_at
    assert store_data.settings_recommendation_notification_episode_key

    now_holder["value"] = now + timedelta(minutes=5)
    await coordinator.async_process_update()

    repeated = store_data.settings_recommendations["hvac:daily_spike_ratio:v1"]
    assert repeated.created_at == first_created_at
    assert repeated.expires_at == first_expires_at
    saved_after_repeat = len(saved)
    assert notifications == [{"entry_id": "entry-1", "total_pending": 1}]

    reloaded = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_id="entry-1",
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
        options={
            CONF_ADVANCED_SETTINGS: {
                "hvac": {"daily_spike_ratio": 0.25},
            },
        },
        store=FakeStore(),
        store_data=store_data,
        now_fn=lambda: now_holder["value"],
    )
    now_holder["value"] = now + timedelta(minutes=10)
    await reloaded.async_process_update()

    assert len(saved) == saved_after_repeat
    assert notifications == [{"entry_id": "entry-1", "total_pending": 1}]


@pytest.mark.asyncio
async def test_settings_recommendation_episode_survives_retention_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import (
        settings_advisor as advisor,
    )

    notifications: list[dict[str, Any]] = []

    class FakeStore:
        def __init__(self, data: FeatureStoreData) -> None:
            self.data = data

        async def async_save(self) -> None:
            return None

    async def fake_notification(hass, entry_id, *, total_pending):
        notifications.append(
            {
                "entry_id": entry_id,
                "total_pending": total_pending,
            }
        )

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_settings_recommendation_notification",
        fake_notification,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        settings_recommendations={
            f"rec-{index}": _settings_recommendation(
                advisor,
                recommendation_id=f"rec-{index}",
                unique_key=f"hvac:setting:{index}",
                setting_key=f"setting_{index}",
                created_at=now - timedelta(minutes=index),
                expires_at=now + timedelta(days=30),
            )
            for index in range(
                coordinator_module.RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS + 10
            )
        },
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_id="entry-1",
        store=FakeStore(store_data),
        store_data=store_data,
        now_fn=lambda: now,
    )
    coordinator._refresh_settings_recommendation_state(now)
    await coordinator._notify_settings_recommendations_if_needed()
    coordinator._apply_retention(now)

    reloaded = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_id="entry-1",
        store=FakeStore(store_data),
        store_data=store_data,
        now_fn=lambda: now,
    )
    reloaded._refresh_settings_recommendation_state(now)
    await reloaded._notify_settings_recommendations_if_needed()

    assert notifications == [{"entry_id": "entry-1", "total_pending": 110}]


@pytest.mark.asyncio
async def test_set_entity_detail_level_persists_options_and_reloads_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import entity as entity_module

    apply_calls: list[tuple[str, str]] = []

    def fake_apply(*_args, entity_domain: str, detail_level: str, **_kwargs):
        apply_calls.append((entity_domain, detail_level))
        return {}

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.updated_options: list[dict[str, Any]] = []
            self.reloaded: list[str] = []

        def async_update_entry(self, entry, *, options):
            self.updated_options.append(options)
            entry.options = MappingProxyType(options)
            return True

        async def async_reload(self, entry_id: str) -> None:
            self.reloaded.append(entry_id)

    monkeypatch.setattr(
        entity_module,
        "apply_entity_profile_to_registry",
        fake_apply,
    )

    entry = SimpleNamespace(entry_id="entry-1", data={}, options=MappingProxyType({}))
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: None),
        data={},
        config_entries=FakeConfigEntries(),
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id=entry.entry_id,
        entry_data=entry.data,
        options=entry.options,
        config_entry=entry,
    )

    await coordinator.async_set_entity_detail_level(ENTITY_DETAIL_EXPERT)

    assert hass.config_entries.updated_options == [
        {CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT}
    ]
    assert coordinator.options[CONF_ENTITY_DETAIL_LEVEL] == ENTITY_DETAIL_EXPERT
    assert hass.config_entries.reloaded == ["entry-1"]
    assert apply_calls == []


@pytest.mark.asyncio
async def test_apply_setting_recommendation_persists_config_entry_options() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )
    from custom_components.circuitsetup_energy_analyzer import settings_advisor

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.updated_options: list[dict[str, Any]] = []

        def async_update_entry(self, entry, *, options):
            self.updated_options.append(options)
            entry.options = MappingProxyType(options)
            return True

    recommendation = _settings_recommendation(settings_advisor)
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
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
        options=MappingProxyType(
            {
                CONF_ADVANCED_SETTINGS: MappingProxyType(
                    {
                        "hvac": MappingProxyType(
                            {"daily_spike_ratio": 0.25},
                        )
                    },
                )
            },
        ),
    )
    store_data = FeatureStoreData(
        settings_recommendations={
            recommendation.recommendation_id: recommendation,
        },
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: None),
        data={},
        config_entries=FakeConfigEntries(),
    )
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id=entry.entry_id,
        entry_data=entry.data,
        options=entry.options,
        store_data=store_data,
        config_entry=entry,
    )

    await coordinator.async_apply_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert (
        hass.config_entries.updated_options[-1][CONF_ADVANCED_SETTINGS]["hvac"][
            "daily_spike_ratio"
        ]
        == 0.3
    )
    assert (
        coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"]["daily_spike_ratio"]
        == 0.3
    )

    reloaded = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id=entry.entry_id,
        entry_data=entry.data,
        options=entry.options,
        store_data=store_data,
        config_entry=entry,
    )

    assert (
        reloaded.store_data.energy_usage_settings_by_circuit["hvac"][
            "daily_spike_ratio"
        ]
        == 0.3
    )


@pytest.mark.asyncio
async def test_process_update_recommends_capacity_from_current_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    notifications: list[dict[str, Any]] = []

    async def fake_notification(hass, entry_id, *, total_pending):
        notifications.append(
            {
                "entry_id": entry_id,
                "total_pending": total_pending,
            }
        )

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_settings_recommendation_notification",
        fake_notification,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    now_holder = {"value": now}

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.ev_current"
            return SimpleNamespace(
                state="31",
                attributes={"unit_of_measurement": "A"},
                last_updated=now_holder["value"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_id="entry-1",
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "ev",
                    "name": "EV Charger",
                    "mode": "single_phase",
                    "appliance_profile": "ev_charger",
                    "sensors": [
                        {
                            "entity_id": "sensor.ev_current",
                            "role": "current",
                            "unit": "A",
                        }
                    ],
                }
            ],
        },
        options={
            CONF_ADVANCED_SETTINGS: {
                "ev": {"warning_ratio": 0.9},
            },
        },
        now_fn=lambda: now_holder["value"],
    )

    for index in range(6):
        now_holder["value"] = now + timedelta(minutes=index)
        await coordinator.async_process_update()

    assert "ev" not in coordinator.state.settings_recommendations_by_circuit
    assert notifications == []

    now_holder["value"] = now + timedelta(minutes=6)
    await coordinator.async_process_update()

    recommendation = coordinator.state.settings_recommendations_by_circuit["ev"][0]
    assert recommendation["setting_key"] == "warning_ratio"
    assert recommendation["suggested_value"] == 0.75
    assert coordinator.state.settings_recommendation_count_by_circuit["ev"] == 1
    stored = coordinator.store_data.settings_recommendations["ev:warning_ratio:v1"]
    first_created_at = stored.created_at
    first_expires_at = stored.expires_at
    assert notifications == [{"entry_id": "entry-1", "total_pending": 1}]

    now_holder["value"] = now + timedelta(minutes=7)
    await coordinator.async_process_update()

    repeated = coordinator.store_data.settings_recommendations["ev:warning_ratio:v1"]
    assert repeated.created_at == first_created_at
    assert repeated.expires_at == first_expires_at
    assert notifications == [{"entry_id": "entry-1", "total_pending": 1}]


@pytest.mark.asyncio
async def test_settings_recommendation_notification_creates_persistent_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    calls: list[dict[str, Any]] = []

    def fake_create(hass, message, *, title, notification_id):
        calls.append(
            {
                "hass": hass,
                "message": message,
                "title": title,
                "notification_id": notification_id,
            }
        )

    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    persistent_notification = ModuleType(
        "homeassistant.components.persistent_notification",
    )
    persistent_notification.async_create = fake_create
    components.persistent_notification = persistent_notification
    homeassistant.components = components
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        persistent_notification,
    )

    await notifications.async_create_settings_recommendation_notification(
        SimpleNamespace(),
        "entry-1",
        total_pending=2,
    )

    assert calls == [
        {
            "hass": SimpleNamespace(),
            "message": (
                "There are 2 suggested Advanced Circuit Settings to review via "
                "CircuitSetup Energy Analyzer > Configure > Review Suggested "
                "Settings."
            ),
            "title": "CircuitSetup Energy Analyzer suggested settings",
            "notification_id": f"{DOMAIN}_settings_recommendations_entry_1",
        }
    ]


@pytest.mark.asyncio
async def test_runtime_notifies_daily_energy_goal_exceeded(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    holder = {"time": now, "energy": 112.0}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        holder["time"] = now + timedelta(days=offset)
        coordinator.store_data.events = [
            CircuitEvent(
                timestamp=holder["time"] - timedelta(minutes=45),
                circuit_id="fridge",
                event_type=EventType.START,
            )
        ]
        await coordinator.async_process_update()

    assert notifications
    alert = next(item for item in notifications if item.feature == "activity_left_on")
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        holder["time"] = now + timedelta(days=offset)
        coordinator.store_data.events = [
            CircuitEvent(
                timestamp=holder["time"] - timedelta(hours=5),
                circuit_id="fridge",
                event_type=EventType.START,
            ),
            CircuitEvent(
                timestamp=holder["time"] - timedelta(hours=4),
                circuit_id="fridge",
                event_type=EventType.STOP,
            ),
        ]
        await coordinator.async_process_update()

    assert notifications
    alert = next(
        item for item in notifications if item.feature == "activity_inactive_too_long"
    )
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
        "ready_energy_entity_count": 1,
        "ready_energy_entities_has_more": False,
        "ready_energy_entities_omitted_count": 0,
        "ready_power_entities": [],
        "ready_power_entity_count": 0,
        "ready_power_entities_has_more": False,
        "ready_power_entities_omitted_count": 0,
        "issues": [],
        "issue_count": 0,
        "issues_has_more": False,
        "issues_omitted_count": 0,
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
async def test_runtime_merges_short_gap_cycles_for_activity_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.washer_power"
            return SimpleNamespace(
                state="0",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "mode": "single_phase",
                    "appliance_profile": "washer",
                    "sensors": [
                        {"entity_id": "sensor.washer_power", "role": "real_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=0),
                    circuit_id="washer",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=10),
                    circuit_id="washer",
                    event_type=EventType.STOP,
                ),
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=11),
                    circuit_id="washer",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=now.replace(hour=1, minute=20),
                    circuit_id="washer",
                    event_type=EventType.STOP,
                ),
            ]
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    assert coordinator.state.run_cycle_count_by_circuit["washer"] == 1
    assert coordinator.state.run_cycle_runtime_seconds_by_circuit["washer"] == 1140.0
    assert coordinator.state.run_cycle_status_by_circuit["washer"] == "idle"


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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
        holder["time"] = now + timedelta(days=offset)
        daily_events: list[CircuitEvent] = []
        for day_offset in range(1, 21):
            start = holder["time"] - timedelta(days=day_offset, hours=2)
            daily_events.extend(
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
        daily_events.append(
            CircuitEvent(
                timestamp=holder["time"] - timedelta(minutes=45),
                circuit_id="fridge",
                event_type=EventType.START,
            )
        )
        coordinator.store_data.events = daily_events
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
    assert "within 92.5% of this month's #3 demand window cutoff" in alert.message
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
async def test_runtime_clears_standby_state_for_generation_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.solar_power"
            return SimpleNamespace(
                state="-500",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "power_flow": "generation",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )
    coordinator.state.always_on_power_w_by_circuit["solar"] = 25.0
    coordinator.state.standby_threshold_w_by_circuit["solar"] = 8.0
    coordinator.state.standby_status_by_circuit["solar"] = "standby"
    coordinator.state.always_on_limit_usage_by_circuit["solar"] = 120.0
    coordinator.state.standby_evidence_by_circuit["solar"] = {"status": "standby"}

    await coordinator.async_process_update()

    assert "solar" not in coordinator.state.always_on_power_w_by_circuit
    assert "solar" not in coordinator.state.standby_threshold_w_by_circuit
    assert "solar" not in coordinator.state.standby_status_by_circuit
    assert "solar" not in coordinator.state.always_on_limit_usage_by_circuit
    assert "solar" not in coordinator.state.standby_evidence_by_circuit


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

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    class FakeRecorder:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    monkeypatch.setattr(
        coordinator_module,
        "_ha_recorder_get_instance",
        lambda hass: FakeRecorder(),
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

    class FakeRecorder:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    monkeypatch.setattr(
        coordinator_module,
        "_ha_recorder_get_instance",
        lambda hass: FakeRecorder(),
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
async def test_recorder_statistics_use_recorder_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    recorder_jobs: list[tuple[object, tuple[object, ...]]] = []

    def fake_statistics_during_period(
        hass: object,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str],
        types: set[str],
    ) -> dict[str, list[dict[str, float]]]:
        del hass, start_time, end_time, statistic_ids, period, units, types
        return {"sensor.energy": [{"sum": 12.3}]}

    class FakeRecorder:
        async def async_add_executor_job(self, target, *args):
            recorder_jobs.append((target, args))
            return target(*args)

    def fake_get_instance(hass: object) -> FakeRecorder:
        del hass
        return FakeRecorder()

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        fake_statistics_during_period,
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module,
        "_ha_recorder_get_instance",
        fake_get_instance,
        raising=False,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_data={CONF_CIRCUITS: []},
        now_fn=lambda: now,
    )

    statistics = await coordinator._recorder_statistics_during_period(
        statistic_ids={"sensor.energy"},
        start_time=now - timedelta(days=1),
        end_time=now,
        period="day",
    )

    assert recorder_jobs
    target, args = recorder_jobs[0]
    assert target is fake_statistics_during_period
    assert args == (
        coordinator.hass,
        now - timedelta(days=1),
        now,
        {"sensor.energy"},
        "day",
        {"energy": "kWh"},
        {"change", "sum", "state"},
    )
    assert statistics == {"sensor.energy": [{"sum": 12.3}]}


@pytest.mark.asyncio
async def test_recorder_statistics_skip_generic_executor_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    generic_jobs: list[object] = []
    statistics_calls = 0

    def fake_statistics_during_period(*args, **kwargs):
        nonlocal statistics_calls
        del args, kwargs
        statistics_calls += 1
        return {"sensor.energy": [{"sum": 12.3}]}

    async def async_add_executor_job(target, *args):
        generic_jobs.append(target)
        return target(*args)

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        fake_statistics_during_period,
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module,
        "_ha_recorder_get_instance",
        lambda hass: None,
        raising=False,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}, async_add_executor_job=async_add_executor_job),
        entry_data={CONF_CIRCUITS: []},
        now_fn=lambda: now,
    )

    statistics = await coordinator._recorder_statistics_during_period(
        statistic_ids={"sensor.energy"},
        start_time=now - timedelta(days=1),
        end_time=now,
        period="day",
    )

    assert statistics == {}
    assert generic_jobs == []
    assert statistics_calls == 0


@pytest.mark.asyncio
async def test_runtime_utility_comparison_setup_issue_creates_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    issues: list[tuple[str, str]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        issues.append((circuit_id, problem))

    def broken_statistics_during_period(*args, **kwargs):
        raise RuntimeError("recorder is not available")

    monkeypatch.setattr(
        coordinator_module,
        "_ha_statistics_during_period",
        broken_statistics_during_period,
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
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

    assert ("mains", "utility_comparison_missing_utility_source") in issues


@pytest.mark.asyncio
async def test_runtime_utility_comparison_missing_measured_creates_specific_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    created: list[tuple[str, str, dict[str, str]]] = []

    async def fake_issue(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        created.append((circuit_id, problem, kwargs["data"]))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_issue,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
    )
    coordinator.state.utility_comparison_status_by_circuit["mains"] = (
        "missing_measured"
    )
    coordinator.store_data.utility_comparison_settings_by_circuit["mains"] = {
        "utility_energy_entity": "sensor.utility_kwh",
    }

    await coordinator._sync_setup_health_repairs("mains")

    assert created == [
        (
            "mains",
            "utility_comparison_missing_measured_source",
            {
                "circuit_name": "Mains",
                "reason": (
                    "Utility comparison is enabled, but measured kWh has no data."
                ),
                "recommended_action": "Add measured kWh source for Mains",
                "source_entities": [],
            },
        )
    ]


@pytest.mark.asyncio
async def test_runtime_specific_utility_comparison_repair_deletes_legacy_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    created: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    async def fake_create(
        hass,
        circuit_id,
        problem,
        severity=Severity.WARNING,
        **kwargs,
    ) -> None:
        created.append((circuit_id, problem))

    async def fake_delete(hass, circuit_id, problem) -> None:
        deleted.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_create_circuit_issue",
        fake_create,
    )
    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_delete_circuit_issue",
        fake_delete,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
    )
    coordinator.state.utility_comparison_status_by_circuit["mains"] = (
        "missing_measured"
    )

    await coordinator._sync_setup_health_repairs("mains")
    await coordinator._sync_setup_health_repairs("mains")

    assert deleted == [("mains", "utility_comparison_source_mismatch")]
    assert created == [("mains", "utility_comparison_missing_measured_source")]


@pytest.mark.asyncio
async def test_runtime_utility_comparison_setup_repair_clears_when_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    deleted: list[tuple[str, str]] = []

    async def fake_delete(hass, circuit_id, problem) -> None:
        deleted.append((circuit_id, problem))

    monkeypatch.setattr(
        coordinator_module.repairs,
        "async_delete_circuit_issue",
        fake_delete,
    )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"}
                    ],
                }
            ]
        },
        now_fn=lambda: datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
    )
    coordinator._active_repair_issues.update(
        {
            ("mains", "utility_comparison_source_mismatch"),
            ("mains", "utility_comparison_missing_utility_source"),
            ("mains", "utility_comparison_missing_measured_source"),
        }
    )
    coordinator.state.utility_comparison_status_by_circuit["mains"] = "tracking"

    await coordinator._sync_setup_health_repairs("mains")

    assert deleted == [
        ("mains", "utility_comparison_missing_measured_source"),
        ("mains", "utility_comparison_missing_utility_source"),
        ("mains", "utility_comparison_source_mismatch"),
    ]


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

    async def fake_notification(hass, alert, **kwargs) -> None:
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

    async def fake_notification(hass, alert, **kwargs) -> None:
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
