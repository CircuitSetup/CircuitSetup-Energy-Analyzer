from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.components import persistent_notification
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import Blueprint, BlueprintInputs
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict

from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.sensor import (
    energy_summary_attributes,
    energy_summary_value,
    health_summary_attributes,
    health_summary_value,
)


@pytest.mark.asyncio
async def test_notification_blueprint_runs_with_summary_sensor_attributes(
    hass: Any,
) -> None:
    """Load the shipped blueprint and exercise its state trigger in Home Assistant."""
    path = (
        Path(__file__).parents[1]
        / "blueprints"
        / "automation"
        / "circuitsetup_energy_analyzer"
        / "energy_alert_notification.yaml"
    )
    blueprint_data = load_yaml_dict(path)
    blueprint = Blueprint(
        blueprint_data,
        path=str(path),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    blueprint_inputs = blueprint_data["blueprint"]["input"]
    assert blueprint_inputs["persistent_notification"]["default"] is False
    selectable_values = {
        item["value"]
        for item in blueprint_inputs["alert_states"]["selector"]["select"]["options"]
    }
    assert "maintenance" not in selectable_values
    assert "stale" not in selectable_values
    assert "needs_data" not in selectable_values
    inputs = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": str(path),
                "input": {
                    "alert_entities": [
                        "sensor.washer_energy_summary",
                        "sensor.washer_health_summary",
                    ],
                    "for_duration": {"seconds": 0},
                    "alert_actions": [
                        {
                            "event": "energy_analyzer_blueprint_alert",
                            "event_data": {
                                "evidence": "{{ alert_evidence }}",
                                "path": "{{ evidence_path }}",
                                "state": "{{ alert_state }}",
                            },
                        }
                    ],
                },
            }
        },
    )
    inputs.validate()
    events = []
    notifications = []
    hass.bus.async_listen("energy_analyzer_blueprint_alert", events.append)
    assert await async_setup_component(hass, "persistent_notification", {})
    persistent_notification.async_register_callback(
        hass,
        lambda update_type, items: (
            notifications.extend(items.values())
            if update_type is not persistent_notification.UpdateType.REMOVED
            else None
        ),
    )

    assert await async_setup_component(
        hass,
        "automation",
        {"automation": [inputs.async_substitute()]},
    )
    await hass.async_block_till_done()
    hass.states.async_set("sensor.washer_energy_summary", "Normal")
    await hass.async_block_till_done()
    state = AnalyzerState(
        daily_energy_usage_by_circuit={"washer": 13.1},
        energy_usage_evidence_by_circuit={
            "washer": {"status": "over_threshold", "threshold_kwh": 12.5}
        },
        learning_by_circuit={"washer": True},
    )
    hass.states.async_set(
        "sensor.washer_energy_summary",
        energy_summary_value(state, "washer"),
        energy_summary_attributes(state, "washer"),
    )
    await hass.async_block_till_done()

    assert events == []
    assert notifications == []

    hass.states.async_set("sensor.washer_energy_summary", "Normal")
    await hass.async_block_till_done()
    state.learning_by_circuit["washer"] = False
    hass.states.async_set(
        "sensor.washer_energy_summary",
        energy_summary_value(state, "washer"),
        energy_summary_attributes(state, "washer"),
    )
    await hass.async_block_till_done()

    assert events == []
    assert notifications == []

    hass.states.async_set("sensor.washer_energy_summary", "Normal")
    await hass.async_block_till_done()
    state.active_alerts_by_circuit["washer"] = [
        SimpleNamespace(feature="daily_energy_usage_spike")
    ]
    state.maintenance_by_circuit["washer"] = {"active": True}
    hass.states.async_set(
        "sensor.washer_energy_summary",
        energy_summary_value(state, "washer"),
        energy_summary_attributes(state, "washer"),
    )
    await hass.async_block_till_done()

    assert events == []
    assert notifications == []

    hass.states.async_set("sensor.washer_energy_summary", "Normal")
    await hass.async_block_till_done()
    state.maintenance_by_circuit.clear()
    hass.states.async_set(
        "sensor.washer_energy_summary",
        energy_summary_value(state, "washer"),
        energy_summary_attributes(state, "washer"),
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "evidence": "Energy use is above a configured threshold or budget.",
        "path": "/circuitsetup-energy-analyzer-evidence?circuit_id=washer",
        "state": "High Usage",
    }
    assert notifications == []

    state.active_alerts_by_circuit.clear()
    hass.states.async_set(
        "sensor.washer_energy_summary",
        energy_summary_value(state, "washer"),
        energy_summary_attributes(state, "washer"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.washer_energy_summary").state == "High Usage"

    hass.states.async_set("sensor.washer_health_summary", "Ready")
    await hass.async_block_till_done()
    provisional_state = AnalyzerState(
        power_quality_evidence_by_circuit={
            "washer": "Possible issue: reactive power changed from baseline"
        },
        learning_by_circuit={"washer": False},
    )
    hass.states.async_set(
        "sensor.washer_health_summary",
        health_summary_value(provisional_state, "washer"),
        health_summary_attributes(provisional_state, "washer"),
    )
    await hass.async_block_till_done()
    assert len(events) == 1
    assert notifications == []

    hass.states.async_set("sensor.washer_health_summary", "Ready")
    await hass.async_block_till_done()
    confirmed_state = AnalyzerState(
        power_quality_evidence_by_circuit={
            "washer": "Possible issue: reactive power changed from baseline"
        },
        active_alerts_by_circuit={
            "washer": [
                SimpleNamespace(feature="reactive_shift_under_stable_real_power")
            ]
        },
        learning_by_circuit={"washer": False},
    )
    hass.states.async_set(
        "sensor.washer_health_summary",
        health_summary_value(confirmed_state, "washer"),
        health_summary_attributes(confirmed_state, "washer"),
    )
    await hass.async_block_till_done()

    assert len(events) == 2
    assert events[1].data == {
        "evidence": "Power-quality evidence has changed from the learned baseline.",
        "path": "/circuitsetup-energy-analyzer-evidence?circuit_id=washer",
        "state": "Possible Power Quality Change",
    }
    assert notifications == []
