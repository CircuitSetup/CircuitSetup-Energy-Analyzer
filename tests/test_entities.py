from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    Severity,
)


def test_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        anomaly_score_value,
        last_event_value,
        nilm_signature_count_value,
        nilm_unmatched_load_percentage_value,
    )

    event = CircuitEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        event_type=EventType.START,
        severity=Severity.INFO,
        features={"startup_power_w": 512.0},
    )
    state = AnalyzerState(
        last_event_by_circuit={"fridge": event},
        anomaly_score_by_circuit={"fridge": 0.42},
        nilm_signature_count_by_circuit={"fridge": 3},
        nilm_unmatched_load_percentage_by_circuit={"fridge": 17.5},
    )

    assert anomaly_score_value(state, "fridge") == 0.42
    assert last_event_value(state, "fridge") == "start"
    assert nilm_signature_count_value(state, "fridge") == 3
    assert nilm_unmatched_load_percentage_value(state, "fridge") == 17.5

    assert anomaly_score_value(state, "unknown") == 0.0
    assert last_event_value(state, "unknown") is None
    assert nilm_signature_count_value(state, "unknown") == 0
    assert nilm_unmatched_load_percentage_value(state, "unknown") == 0.0


def test_binary_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        has_data_quality_problem,
        is_learning,
    )

    state = AnalyzerState(
        learning_by_circuit={"fridge": False},
        data_quality_by_circuit={
            "fridge": "",
            "well_pump": "missing current sample",
        },
    )

    assert is_learning(state, "fridge") is False
    assert is_learning(state, "unknown") is True
    assert has_data_quality_problem(state, "fridge") is False
    assert has_data_quality_problem(state, "well_pump") is True
    assert has_data_quality_problem(state, "unknown") is False


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    coordinator = SimpleNamespace(data=AnalyzerState())
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.name for entity in added_entities] == [
        "Kitchen Fridge Anomaly Score",
        "Kitchen Fridge Last Event",
        "Kitchen Fridge NILM Discovered Signatures",
        "Kitchen Fridge NILM Unmatched Load Percentage",
    ]
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_fridge_anomaly_score",
        "entry-1_fridge_last_event",
        "entry-1_fridge_nilm_signature_count",
        "entry-1_fridge_nilm_unmatched_load_percentage",
    ]


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    circuit = {
        "circuit_id": "well_pump",
        "name": "Well Pump",
    }
    coordinator = SimpleNamespace(data=AnalyzerState())
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.name for entity in added_entities] == [
        "Well Pump Learning",
        "Well Pump Data Quality Problem",
    ]
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_well_pump_learning",
        "entry-1_well_pump_data_quality_problem",
    ]
