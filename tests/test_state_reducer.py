from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import Observation
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
    StateReducer,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
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
    assert applied.active_alerts == [alert]
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
