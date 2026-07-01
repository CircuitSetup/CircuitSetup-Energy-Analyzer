from __future__ import annotations

from datetime import UTC, datetime

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
    recorded_observations: list[Observation] = []

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
        record_observation=recorded_observations.append,
    )

    assert applied.events == [event]
    assert applied.active_alerts == [alert]
    assert applied.notifications == [alert]
    assert applied.store_dirty is True
    assert store_data.events == [event]
    assert store_data.alerts == [alert]
    assert recorded_observations == [observation]
    assert state.health_summary_by_circuit == {"fridge": "Running"}
