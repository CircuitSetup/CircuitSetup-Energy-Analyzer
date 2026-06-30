from __future__ import annotations

import pytest

from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
    StateReducer,
)


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
