from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import Observation
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
    StateReducer,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    CircuitMode,
    EventType,
    PowerFlowMode,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    FeatureResult,
    StateUpdate,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_state_reducer_applies_known_mapping_path() -> None:
    state = AnalyzerState()
    reducer = StateReducer()

    reducer.apply_update(state, ("learning_by_circuit", "fridge"), True)

    assert state.learning_by_circuit == {"fridge": True}


def test_state_reducer_rejects_unknown_roots_and_intermediate_creation() -> None:
    state = AnalyzerState()
    reducer = StateReducer()

    with pytest.raises(ValueError, match="unknown root"):
        reducer.apply_update(state, ("unknown_by_circuit", "fridge"), True)

    with pytest.raises(ValueError, match="cannot create intermediate key"):
        reducer.apply_update(
            state,
            ("readiness_by_circuit", "fridge", "health_status"),
            "ok",
        )


def test_state_reducer_applies_state_update_batches() -> None:
    state = AnalyzerState()
    reducer = StateReducer()

    reducer.apply_updates(
        state,
        [
            StateUpdate(("learning_by_circuit", "fridge"), True),
            StateUpdate(("health_summary_by_circuit", "fridge"), "Running"),
        ],
    )

    assert state.learning_by_circuit == {"fridge": True}
    assert state.health_summary_by_circuit == {"fridge": "Running"}


def test_state_reducer_revises_hvac_association_on_processor_update() -> None:
    state = AnalyzerState()
    reducer = StateReducer()
    streams = {"heat_pump|climate.home|heating": {"status": "learning"}}

    reducer.apply_update(
        state,
        ("hvac_efficiency_by_circuit", "heat_pump"),
        {"status": "tracking", "current_streams": {"episode": 1}, "streams": streams},
    )
    reducer.apply_update(
        state,
        ("hvac_efficiency_by_circuit", "heat_pump"),
        {"status": "tracking", "current_streams": {"episode": 2}, "streams": streams},
    )

    assert state.hvac_association_revision_by_circuit == {"heat_pump": 1}

    reducer.apply_update(
        state,
        ("hvac_efficiency_by_circuit", "heat_pump"),
        {
            "status": "ready",
            "current_streams": {},
            "streams": {
                "heat_pump|climate.home|heating": {"status": "ready"}
            },
        },
    )

    assert state.hvac_association_revision_by_circuit == {"heat_pump": 2}


def test_state_reducer_applies_feature_result_payload() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    state = AnalyzerState()
    store_data = FeatureStoreData()
    reducer = StateReducer()
    event = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue.",
        feature="processor_test",
    )
    preserved_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Existing issue.",
        feature="preserved_test",
    )
    observation = Observation(
        circuit_id="fridge",
        feature="cycle_duration",
        score=1.8,
        baseline_confidence=0.9,
        observed_at=now,
        observed_value=45.0,
        baseline_value=30.0,
        message="Fridge ran longer than usual.",
    )
    applied = reducer.apply_feature_result(
        state,
        store_data,
        FeatureResult(
            events=[event],
            alerts=[alert],
            preserved_alerts=[preserved_alert],
            notifications=[alert],
            observations=[observation],
            state_updates=[
                StateUpdate(("health_summary_by_circuit", "fridge"), "Running")
            ],
            store_dirty=True,
        ),
        alert_feedback=lambda value: value,
    )

    assert applied.events == [event]
    assert applied.active_alerts == [alert, preserved_alert]
    assert applied.notifications == [alert]
    assert applied.store_dirty is True
    assert store_data.events == [event]
    assert store_data.alerts == [alert]
    assert state.recent_observations_by_circuit["fridge"] == [
        {
            "timestamp": now.isoformat(),
            "circuit_id": "fridge",
            "feature": "cycle_duration",
            "feature_name": "Cycle Duration",
            "message": "Fridge ran longer than usual.",
            "score": 1.8,
            "baseline_confidence": 0.9,
            "observed_value": 45.0,
            "baseline_value": 30.0,
        }
    ]
    assert state.health_summary_by_circuit == {"fridge": "Running"}


def test_state_reducer_records_and_prunes_recent_observations() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    stale = now - timedelta(hours=13)
    state = AnalyzerState()
    store_data = FeatureStoreData()
    reducer = StateReducer()

    initial = Observation(
        circuit_id="fridge",
        feature="cycle_duration",
        score=1.2,
        baseline_confidence=0.7,
        observed_at=stale,
        observed_value=36.0,
        baseline_value=30.0,
        message="Older cycle duration note.",
        observation_key="fridge-cycle",
    )
    replacement = Observation(
        circuit_id="fridge",
        feature="cycle_duration",
        score=1.8,
        baseline_confidence=0.9,
        observed_at=now,
        observed_value=45.0,
        baseline_value=30.0,
        message="Fridge ran longer than usual.",
        observation_key="fridge-cycle",
    )
    stale_other = Observation(
        circuit_id="washer",
        feature="run_count",
        score=0.5,
        baseline_confidence=0.6,
        observed_at=stale,
        observed_value=3.0,
        baseline_value=1.0,
        message="Older washer note.",
    )

    reducer.apply_feature_result(
        state,
        store_data,
        FeatureResult(observations=[initial]),
        alert_feedback=lambda value: value,
    )
    reducer.apply_feature_result(
        state,
        store_data,
        FeatureResult(observations=[replacement, stale_other]),
        alert_feedback=lambda value: value,
    )

    fridge_payload = {
        "timestamp": now.isoformat(),
        "circuit_id": "fridge",
        "feature": "cycle_duration",
        "feature_name": "Cycle Duration",
        "message": "Fridge ran longer than usual.",
        "score": 1.8,
        "baseline_confidence": 0.9,
        "observed_value": 45.0,
        "baseline_value": 30.0,
        "observation_key": "fridge-cycle",
    }
    assert state.recent_observations_by_circuit["fridge"] == [fridge_payload]
    assert state.recent_observations_by_circuit["washer"] == [
        {
            "timestamp": stale.isoformat(),
            "circuit_id": "washer",
            "feature": "run_count",
            "feature_name": "Run Count",
            "message": "Older washer note.",
            "score": 0.5,
            "baseline_confidence": 0.6,
            "observed_value": 3.0,
            "baseline_value": 1.0,
        }
    ]

    reducer.prune_recent_observations(state, now, window_hours=12)

    assert state.recent_observations_by_circuit == {"fridge": [fridge_payload]}


def test_state_reducer_clears_processor_owned_state_groups() -> None:
    state = AnalyzerState()
    reducer = StateReducer()
    state.power_quality_score_by_circuit["fridge"] = 98.0
    state.power_quality_evidence_by_circuit["fridge"] = {"status": "ok"}
    state.reactive_power_drift_by_circuit["fridge"] = 0.1
    state.apparent_power_drift_by_circuit["fridge"] = 0.2
    state.power_factor_drift_by_circuit["fridge"] = 0.3
    state.standby_threshold_w_by_circuit["fridge"] = 12.0
    state.always_on_power_w_by_circuit["fridge"] = 8.0
    state.standby_status_by_circuit["fridge"] = "normal"
    state.always_on_limit_usage_by_circuit["fridge"] = 0.42
    state.standby_evidence_by_circuit["fridge"] = {"status": "normal"}

    assert reducer.clear_power_quality_state(state, "fridge") is True
    assert reducer.clear_standby_state(state, "fridge") is True
    assert reducer.clear_power_quality_state(state, "fridge") is False
    assert reducer.clear_standby_state(state, "fridge") is False
    assert state.power_quality_score_by_circuit == {}
    assert state.power_quality_evidence_by_circuit == {}
    assert state.reactive_power_drift_by_circuit == {}
    assert state.apparent_power_drift_by_circuit == {}
    assert state.power_factor_drift_by_circuit == {}
    assert state.standby_threshold_w_by_circuit == {}
    assert state.always_on_power_w_by_circuit == {}
    assert state.standby_status_by_circuit == {}
    assert state.always_on_limit_usage_by_circuit == {}
    assert state.standby_evidence_by_circuit == {}


def test_state_reducer_clears_context_state_and_store_groups() -> None:
    state = AnalyzerState()
    store_data = FeatureStoreData()
    reducer = StateReducer()
    state.weather_context_by_circuit["hvac"] = {"status": "normal"}
    store_data.weather_context_by_circuit["hvac"] = {"status": "normal"}
    store_data.weather_context_history_by_circuit["hvac"] = [{"sample": 1}]
    state.rain_pump_context_by_circuit["pump"] = {"status": "expected"}
    store_data.rain_pump_context_by_circuit["pump"] = {"status": "expected"}
    state.water_flow_context_by_circuit["pump"] = {"status": "normal"}
    store_data.water_flow_context_by_circuit["pump"] = {"status": "normal"}
    state.water_context_history_by_circuit["pump"] = [{"sample": 2}]
    store_data.water_context_history_by_circuit["pump"] = [{"sample": 2}]

    assert reducer.clear_weather_context_state(state, store_data, "hvac") is True
    assert reducer.clear_rain_pump_context_state(state, store_data, "pump") is True
    assert reducer.clear_water_flow_context_state(state, store_data, "pump") is True
    assert reducer.clear_water_context_history(state, store_data, "pump") is True
    assert reducer.clear_weather_context_state(state, store_data, "hvac") is False
    assert reducer.clear_rain_pump_context_state(state, store_data, "pump") is False
    assert reducer.clear_water_flow_context_state(state, store_data, "pump") is False
    assert reducer.clear_water_context_history(state, store_data, "pump") is False
    assert state.weather_context_by_circuit == {}
    assert store_data.weather_context_by_circuit == {}
    assert store_data.weather_context_history_by_circuit == {}
    assert state.rain_pump_context_by_circuit == {}
    assert store_data.rain_pump_context_by_circuit == {}
    assert state.water_flow_context_by_circuit == {}
    assert store_data.water_flow_context_by_circuit == {}
    assert state.water_context_history_by_circuit == {}
    assert store_data.water_context_history_by_circuit == {}


def test_state_reducer_refreshes_metadata_and_latest_power() -> None:
    state = AnalyzerState()
    reducer = StateReducer()
    config = SimpleNamespace(
        circuit_id="fridge",
        mode=CircuitMode.DUAL_PHASE,
        power_flow=PowerFlowMode.LOAD,
    )

    reducer.refresh_config_metadata_state(state, config)
    reducer.refresh_latest_real_power_state(
        state,
        config,
        SimpleNamespace(real_power=823.4),
    )

    assert state.circuit_mode_by_circuit == {"fridge": "Dual Phase"}
    assert state.power_flow_by_circuit == {"fridge": "Load"}
    assert state.latest_real_power_w_by_circuit == {"fridge": 823.4}

    reducer.refresh_latest_real_power_state(
        state,
        config,
        SimpleNamespace(real_power=None),
    )

    assert state.latest_real_power_w_by_circuit == {}


def test_state_reducer_resets_learning_state_for_relearn() -> None:
    state = AnalyzerState()
    reducer = StateReducer()
    state.active_alerts_by_circuit["fridge"] = [object()]
    state.anomaly_score_by_circuit["fridge"] = 4.2
    state.learning_by_circuit["fridge"] = False
    state.power_quality_score_by_circuit["fridge"] = 91.0
    state.power_factor_drift_by_circuit["fridge"] = 0.2
    state.appliance_health_status_by_circuit["fridge"] = "possible_degradation"
    state.appliance_health_evidence_by_circuit["fridge"] = {
        "feature": "efficiency_degradation"
    }
    state.hvac_current_episode_by_stream = {
        "fridge|climate.kitchen|cooling": {"complete": False},
        "washer|climate.laundry|cooling": {"complete": False},
    }
    state.hvac_efficiency_by_circuit["fridge"] = {"status": "ready"}
    state.hvac_thermostat_setup_issues_by_circuit["fridge"] = [
        {"issue": "missing"}
    ]

    reducer.reset_learning_state(state, "fridge")

    assert state.active_alerts_by_circuit == {}
    assert state.anomaly_score_by_circuit == {"fridge": 0.0}
    assert state.learning_by_circuit == {"fridge": True}
    assert state.power_quality_score_by_circuit == {}
    assert state.power_factor_drift_by_circuit == {}
    assert state.appliance_health_status_by_circuit == {}
    assert state.appliance_health_evidence_by_circuit == {}
    assert state.hvac_current_episode_by_stream == {
        "washer|climate.laundry|cooling": {"complete": False}
    }
    assert state.hvac_efficiency_by_circuit == {}
    assert state.hvac_association_revision_by_circuit == {"fridge": 1}
    assert state.hvac_thermostat_setup_issues_by_circuit == {}


def test_state_reducer_refreshes_alert_evidence_and_recent_activity() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    state = AnalyzerState()
    store_data = FeatureStoreData()
    reducer = StateReducer()
    event = CircuitEvent(
        timestamp=now - timedelta(minutes=5),
        circuit_id="fridge",
        event_type=EventType.START,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Fridge energy is higher than normal.",
        feature="energy_usage",
        observed_value=2.8,
        baseline_value=2.0,
    )
    store_data.events.append(event)
    store_data.alerts.append(alert)

    reducer.refresh_alert_evidence_state(state, "fridge", alert, config=None)
    reducer.refresh_recent_activity_state(state, store_data, "fridge", now)

    assert state.alert_evidence_by_circuit["fridge"]["message"] == (
        "Fridge energy is higher than normal."
    )
    assert state.recent_activity_by_circuit["fridge"] == (
        "Possible issue: Energy Usage"
    )
    assert state.recent_activity_count_by_circuit == {"fridge": 2}
    assert state.recent_activity_timeline_by_circuit["fridge"]["total_count"] == 2

    reducer.refresh_alert_evidence_state(state, "fridge", None, config=None)

    assert state.alert_evidence_by_circuit == {}


def test_state_reducer_clears_only_direct_appliance_state() -> None:
    state = AnalyzerState()
    state.run_cycle_status_by_circuit = {"fridge": "running", "washer": "idle"}
    state.daily_energy_usage_by_circuit = {"fridge": 2.0}
    state.hvac_current_episode_by_stream = {
        "fridge|climate.kitchen|cooling": {"active": True},
        "washer|climate.laundry|cooling": {"active": True},
    }

    reducer = StateReducer()
    assert reducer.clear_direct_appliance_state(state, "fridge")
    assert not reducer.clear_direct_appliance_state(state, "fridge")
    assert state.run_cycle_status_by_circuit == {"washer": "idle"}
    assert state.daily_energy_usage_by_circuit == {"fridge": 2.0}
    assert set(state.hvac_current_episode_by_stream) == {
        "washer|climate.laundry|cooling"
    }


def test_state_reducer_hydrates_context_state_from_store() -> None:
    state = AnalyzerState()
    store_data = FeatureStoreData()
    store_data.weather_context_by_circuit["hvac"] = {"status": "normal"}
    store_data.rain_pump_context_by_circuit["sump"] = {"status": "rain_explained"}
    store_data.water_flow_context_by_circuit["pump"] = {"status": "normal"}
    store_data.water_context_history_by_circuit["pump"] = [{"sample": 1}]

    StateReducer().hydrate_context_state_from_store(state, store_data)

    assert state.weather_context_by_circuit == {"hvac": {"status": "normal"}}
    assert state.rain_pump_context_by_circuit == {
        "sump": {"status": "rain_explained"}
    }
    assert state.water_flow_context_by_circuit == {"pump": {"status": "normal"}}
    assert state.water_context_history_by_circuit == {"pump": [{"sample": 1}]}
    assert state.weather_context_by_circuit["hvac"] is not (
        store_data.weather_context_by_circuit["hvac"]
    )
    assert state.water_context_history_by_circuit["pump"][0] is not (
        store_data.water_context_history_by_circuit["pump"][0]
    )
