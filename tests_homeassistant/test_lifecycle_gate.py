from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONF_CIRCUITS = "circuits"
CONF_ADVANCED_SETTINGS = "advanced_settings"
CONF_ENABLE_EXPERIMENTAL_NILM = "enable_experimental_nilm"
CONF_MAINS_SOURCE_ENTITIES = "mains_source_entities"
CONF_OUTDOOR_TEMPERATURE_ENTITY = "outdoor_temperature_entity"
CONF_RAIN_INTENSITY_ENTITY = "rain_intensity_entity"
CONF_RAIN_SENSOR_ENTITY = "rain_sensor_entity"
CONF_SOURCE_ENTITIES = "source_entities"
CONF_WATER_FLOW_SENSOR_ENTITIES = "water_flow_sensor_entities"
DOMAIN = "circuitsetup_energy_analyzer"
PANEL_SETUP_KEY = "_panel_setup"
PANEL_REGISTERED_VALUE = "registered"
PANEL_SKIPPED_VALUE = "skipped_existing_panel"
PANEL_READY_VALUES = {PANEL_REGISTERED_VALUE, PANEL_SKIPPED_VALUE}
SERVICE_RELEARN_BASELINE = "relearn_baseline"
EXPECTED_PLATFORM_DOMAINS = frozenset(
    {
        "button",
        "number",
        "select",
        "sensor",
        "switch",
        "text",
        "time",
    }
)
EXPECTED_SOURCE_WORKFLOW_PLATFORM_DOMAINS = frozenset(
    {
        "button",
        "number",
        "select",
        "sensor",
        "switch",
        "text",
        "time",
    }
)
EXPECTED_MAINS_WORKFLOW_PLATFORM_DOMAINS = frozenset(
    {
        "button",
        "number",
        "select",
        "sensor",
        "switch",
        "text",
        "time",
    }
)
LIFECYCLE_LOG_BLOCKLIST = (
    "traceback",
    "duplicate entity",
    "duplicate service",
    "duplicate listener",
    "duplicate panel",
    "blocking i/o",
    "coroutine was never awaited",
    "was never awaited",
    "coroutine-not-awaited",
    "unhandled homeassistanterror",
    "translation failure",
    "invalid dashboard entity",
)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.asyncio
async def test_feature_store_migrates_previous_major_version(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homeassistant.helpers.storage import Store

    _point_custom_components_at_worktree(monkeypatch)
    from custom_components.circuitsetup_energy_analyzer.const import (
        STORAGE_KEY,
        STORAGE_VERSION,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import (
        FeatureStore,
        FeatureStoreData,
    )

    entry_id = "unsupported-store-version"
    key = f"{STORAGE_KEY}.{entry_id}"
    previous_data = {"sensitivity_by_circuit": {"fridge": "quiet"}}
    await Store(hass, STORAGE_VERSION - 1, key).async_save(previous_data)

    loaded = await FeatureStore(hass, entry_id).async_load()

    assert loaded == FeatureStoreData(sensitivity_by_circuit={"fridge": "quiet"})
    assert loaded.hvac_response_history_by_stream == {}
    assert loaded.hvac_baseline_era_by_stream == {}
    assert await Store(hass, STORAGE_VERSION, key).async_load() == previous_data


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_reload_unload_lifecycle(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise a real Home Assistant config-entry lifecycle."""

    caplog.set_level(logging.WARNING)

    _point_custom_components_at_worktree(monkeypatch)
    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.fridge_energy",
        "120.5",
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="lifecycle-entry",
        title="Lifecycle Gate",
        data={
            CONF_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.fridge_energy",
            ],
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
                        },
                        {
                            "entity_id": "sensor.fridge_energy",
                            "role": "energy",
                        },
                    ],
                }
            ],
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is True
    assert coordinator.source_entities == (
        "sensor.fridge_power",
        "sensor.fridge_energy",
    )
    assert hass.services.has_service(DOMAIN, SERVICE_RELEARN_BASELINE)
    assert hass.data[DOMAIN][PANEL_SETUP_KEY] in PANEL_READY_VALUES
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_PLATFORM_DOMAINS
    )

    assert await hass.config_entries.async_reload(entry.entry_id) is True
    await hass.async_block_till_done()

    reloaded_coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is False
    assert reloaded_coordinator is not coordinator
    assert reloaded_coordinator.started is True
    assert reloaded_coordinator.source_entities == coordinator.source_entities
    assert hass.services.has_service(DOMAIN, SERVICE_RELEARN_BASELINE)
    assert hass.data[DOMAIN][PANEL_SETUP_KEY] in PANEL_READY_VALUES
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_PLATFORM_DOMAINS
    )

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert reloaded_coordinator.started is False
    assert entry.entry_id not in hass.data[DOMAIN]
    assert not hass.services.has_service(DOMAIN, SERVICE_RELEARN_BASELINE)
    assert PANEL_SETUP_KEY not in hass.data.get(DOMAIN, {})

    remove_result = await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert remove_result.get("require_restart") is False
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_supports_multi_workflow_sources(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise richer real-setup workflows from one config entry."""

    caplog.set_level(logging.WARNING)

    _point_custom_components_at_worktree(monkeypatch)
    _set_source_state(hass, "sensor.fridge_power", "84", "W", "power")
    _set_source_state(hass, "sensor.fridge_energy", "120.5", "kWh", "energy")
    _set_source_state(hass, "sensor.dryer_l1_power", "1300", "W", "power")
    _set_source_state(hass, "sensor.dryer_l2_power", "1280", "W", "power")
    _set_source_state(hass, "sensor.dryer_energy", "42.0", "kWh", "energy")
    _set_source_state(hass, "sensor.hvac_power", "640", "W", "power")
    _set_source_state(hass, "sensor.mixed_power", "210", "W", "power")
    _set_source_state(hass, "sensor.panel_mains_l1_active_power", "2200", "W")
    _set_source_state(hass, "sensor.panel_mains_l2_active_power", "2100", "W")
    _set_source_state(hass, "sensor.solar_power", "-1400", "W", "power")
    _set_source_state(hass, "sensor.solar_energy", "980.0", "kWh", "energy")
    _set_source_state(hass, "sensor.outdoor_temperature", "72", "F")
    _set_source_state(hass, "sensor.rain_intensity", "0.2", "in/h")
    _set_source_state(hass, "binary_sensor.rain", "on")
    _set_source_state(hass, "binary_sensor.water_flow", "on")

    source_entities = [
        "sensor.fridge_power",
        "sensor.fridge_energy",
        "sensor.dryer_l1_power",
        "sensor.dryer_l2_power",
        "sensor.dryer_energy",
        "sensor.hvac_power",
        "sensor.mixed_power",
        "sensor.panel_mains_l1_active_power",
        "sensor.panel_mains_l2_active_power",
        "sensor.solar_power",
        "sensor.solar_energy",
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="workflow-entry",
        title="Workflow Gate",
        data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_SOURCE_ENTITIES: source_entities,
            CONF_MAINS_SOURCE_ENTITIES: [
                "sensor.panel_mains_l1_active_power",
                "sensor.panel_mains_l2_active_power",
            ],
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain",
            CONF_RAIN_INTENSITY_ENTITY: "sensor.rain_intensity",
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "dryer",
                    "name": "Laundry Dryer",
                    "mode": "dual_phase",
                    "appliance_profile": "dryer",
                    "sensors": [
                        {
                            "entity_id": "sensor.dryer_l1_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.dryer_l2_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                        {"entity_id": "sensor.dryer_energy", "role": "energy"},
                    ],
                },
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "mode": "single_phase",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "mixed_load",
                    "name": "Mixed Load",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {"entity_id": "sensor.mixed_power", "role": "real_power"},
                    ],
                },
                {
                    "circuit_id": "mains",
                    "name": "Mains NILM",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "power_flow": "mains_net",
                    "sensors": [
                        {
                            "entity_id": "sensor.panel_mains_l1_active_power",
                            "role": "real_power",
                            "leg": "a",
                        },
                        {
                            "entity_id": "sensor.panel_mains_l2_active_power",
                            "role": "real_power",
                            "leg": "b",
                        },
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "mode": "single_phase",
                    "appliance_profile": "solar_inverter",
                    "power_flow": "generation",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"},
                        {"entity_id": "sensor.solar_energy", "role": "energy"},
                    ],
                },
            ],
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    configs = {config.circuit_id: config for config in coordinator.circuit_configs}
    assert set(configs) == {
        "dryer",
        "fridge",
        "hvac",
        "mains",
        "mixed_load",
        "solar",
    }
    assert configs["dryer"].mode.value == "dual_phase"
    assert configs["mixed_load"].mode.value == "mixed"
    assert configs["mains"].mode.value == "mains_nilm"
    assert configs["solar"].power_flow.value == "generation"
    assert set(coordinator.source_entities) == {
        *source_entities,
        "sensor.outdoor_temperature",
        "binary_sensor.rain",
        "sensor.rain_intensity",
        "binary_sensor.water_flow",
    }
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_PLATFORM_DOMAINS
    )
    _assert_appliance_workflow_payloads(hass, coordinator, entry.entry_id)
    await _assert_appliance_workflow_panel_views(hass, entry.entry_id, monkeypatch)

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


def _assert_appliance_workflow_payloads(
    hass: Any,
    coordinator: Any,
    entry_id: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.dashboard import (
        build_recommended_dashboard,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
        setup_health_payload,
    )
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    appliance = appliance_detail_payload([coordinator], circuit_id="fridge")
    assert appliance["status"] == "ok"
    assert appliance["detail"]["source_type"] == "direct_meter"
    assert appliance["detail"]["evidence_path"].endswith("circuit_id=fridge")
    assert "open_evidence" not in appliance["actions"]
    assert appliance["actions"]["relearn_baseline"]["data"] == {
        "circuit_id": "fridge"
    }

    setup_health = setup_health_payload([coordinator], entry_id=entry_id)
    assert setup_health["status"] == "ok"
    assert setup_health["checklist_total_count"] == len(setup_health["checklist"])
    assert setup_health["checklist_total_count"] > 0

    nilm_workspace = nilm_workspace_payload([coordinator], circuit_id="mains")
    assert nilm_workspace["status"] == "ok"
    assert nilm_workspace["circuit"]["circuit_id"] == "mains"
    assert set(nilm_workspace["lanes"]) == {
        "needs_review",
        "assigned",
        "published",
        "hidden",
    }
    label_action_data = nilm_workspace["actions"]["label_interval"]["data"]
    assert label_action_data["circuit_id"] == "mains"
    assert label_action_data["mains_entity_id"].startswith("sensor.")

    dashboard = build_recommended_dashboard(
        coordinator.circuit_configs,
        "standard",
        hass=hass,
        entry_id=entry_id,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )
    views = {
        view.get("path"): view
        for view in dashboard.get("views", [])
        if isinstance(view, dict)
    }
    assert set(views) == {
        "overview",
        "energy-costs",
        "insights",
    }
    card_types = {
        card.get("type")
        for view in views.values()
        for section in view.get("sections", [])
        for card in section.get("cards", [])
        if isinstance(card, dict)
    }
    assert {
        "custom:circuitsetup-energy-analyzer-house-flow",
        "custom:circuitsetup-energy-analyzer-appliance-grid",
        "custom:circuitsetup-energy-analyzer-energy-cost",
    } <= card_types
    assert "custom:circuitsetup-energy-analyzer-dashboard-graphs" not in card_types


async def _assert_appliance_workflow_panel_views(
    hass: Any,
    entry_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the panel API views used by the browser workflow."""

    from custom_components.circuitsetup_energy_analyzer import panel

    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    appliance = await panel.ApplianceDetailView().get(
        SimpleNamespace(app={panel.KEY_HASS: hass}, query={"circuit_id": "fridge"})
    )
    assert appliance["status"] == "ok"
    assert appliance["detail"]["source_type"] == "direct_meter"
    assert "open_evidence" not in appliance["actions"]
    assert appliance["actions"]["relearn_baseline"]["data"] == {
        "circuit_id": "fridge"
    }

    stale_assignment = await panel.ApplianceDetailView().get(
        SimpleNamespace(
            app={panel.KEY_HASS: hass},
            query={"assignment_id": "missing-assignment"},
        )
    )
    assert stale_assignment["status"] == "not_found"
    assert stale_assignment["next_step"] == (
        "Open the NILM workspace to review current appliance assignments."
    )

    setup_health = await panel.SetupHealthView().get(
        SimpleNamespace(app={panel.KEY_HASS: hass}, query={"entry_id": entry_id})
    )
    assert setup_health["status"] == "ok"
    assert setup_health["checklist_total_count"] == len(setup_health["checklist"])
    assert setup_health["checklist_total_count"] > 0

    nilm_workspace = await panel.NilmWorkspaceView().get(
        SimpleNamespace(app={panel.KEY_HASS: hass}, query={"circuit_id": "mains"})
    )
    assert nilm_workspace["status"] == "ok"
    assert nilm_workspace["circuit"]["circuit_id"] == "mains"
    assert set(nilm_workspace["lanes"]) == {
        "needs_review",
        "assigned",
        "published",
        "hidden",
    }
    label_action_data = nilm_workspace["actions"]["label_interval"]["data"]
    assert label_action_data["circuit_id"] == "mains"
    assert label_action_data["mains_entity_id"].startswith("sensor.")


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_supports_extra_entity_only_source_output(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise setup data produced by an extra-entity-only source selection."""

    caplog.set_level(logging.WARNING)

    _point_custom_components_at_worktree(monkeypatch)
    _set_source_state(hass, "sensor.extra_refrigerator_power", "92", "W", "power")
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="extra-entity-entry",
        title="Extra Entity Gate",
        data={CONF_SOURCE_ENTITIES: ["sensor.extra_refrigerator_power"]},
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert [config.circuit_id for config in coordinator.circuit_configs] == [
        "extra_refrigerator",
    ]
    config = coordinator.circuit_configs[0]
    assert config.mode.value == "single_phase"
    assert config.appliance_profile.value == "refrigerator"
    assert coordinator.source_entities == ("sensor.extra_refrigerator_power",)
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_SOURCE_WORKFLOW_PLATFORM_DOMAINS
    )

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_supports_rain_intensity_only_source(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise setup when rain context comes only from an intensity source."""

    caplog.set_level(logging.WARNING)

    _point_custom_components_at_worktree(monkeypatch)
    _set_source_state(hass, "sensor.sump_pump_power", "15", "W", "power")
    _set_source_state(hass, "sensor.rain_intensity", "0.3", "in/h")
    _set_source_state(hass, "binary_sensor.water_flow", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="rain-intensity-entry",
        title="Rain Intensity Gate",
        data={
            CONF_SOURCE_ENTITIES: ["sensor.sump_pump_power"],
            CONF_RAIN_INTENSITY_ENTITY: "sensor.rain_intensity",
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"],
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert [config.circuit_id for config in coordinator.circuit_configs] == [
        "sump_pump",
    ]
    assert coordinator.circuit_configs[0].appliance_profile.value == "sump_pump"
    assert coordinator.source_entities == (
        "sensor.sump_pump_power",
        "sensor.rain_intensity",
        "binary_sensor.water_flow",
    )
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_SOURCE_WORKFLOW_PLATFORM_DOMAINS
    )

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_builds_mains_nilm_from_mains_sources(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise auto mains/NILM setup without a hand-written mains circuit."""

    caplog.set_level(logging.WARNING)

    _point_custom_components_at_worktree(monkeypatch)
    mains_entities = [
        "sensor.panel_mains_l1_active_power",
        "sensor.panel_mains_l2_active_power",
    ]
    _set_source_state(hass, mains_entities[0], "2200", "W", "power")
    _set_source_state(hass, mains_entities[1], "2100", "W", "power")
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="auto-mains-entry",
        title="Auto Mains Gate",
        data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: mains_entities,
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert [config.circuit_id for config in coordinator.circuit_configs] == ["mains"]
    config = coordinator.circuit_configs[0]
    assert config.mode.value == "mains_nilm"
    assert config.appliance_profile.value == "mains_nilm"
    assert config.power_flow.value == "mains_net"
    assert coordinator.source_entities == tuple(mains_entities)
    assert (
        _registered_platform_domains(hass, entry.entry_id)
        == EXPECTED_MAINS_WORKFLOW_PLATFORM_DOMAINS
    )

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_setup_registers_published_nilm_device(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore published NILM assignments as real HA entities and a device."""

    from homeassistant.helpers import device_registry as dr

    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStore

    _point_custom_components_at_worktree(monkeypatch)
    entry_id = "published-nilm-entry"
    mains_entities = ["sensor.published_mains_l1", "sensor.published_mains_l2"]
    for entity_id in mains_entities:
        _set_source_state(hass, entity_id, "1800", "W", "power")
    session_anchor = datetime.now(UTC).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    ) - timedelta(days=4)
    published_sessions = [
        (f"published-session-{index}", session_anchor + timedelta(days=index))
        for index in range(1, 4)
    ]
    published_session_ids = [session_id for session_id, _start in published_sessions]

    store = FeatureStore(hass, entry_id)
    store.data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-washer",
                "appliance_id": "washer",
                "display_name": "Washer",
                "appliance_profile": "washer",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["washer-signature"],
                "session_ids": list(published_session_ids),
                "confirmed_session_ids": list(published_session_ids),
                "rejected_session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "published",
                "confidence": 0.9,
                "feedback_evidence_score": 0.9,
                "model_fit": 0.9,
                "validation_evaluable_session_count": 3,
                "validation_precision": 1.0,
                "false_positive_rate": 0.0,
                "created_device": True,
                "publish_entities": True,
            }
        ]
    }
    store.data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": session_id,
                "assignment_id": "assignment-washer",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=20)).isoformat(),
                "ambiguous": False,
                "energy_source": "residual_trace_measured",
                "known_source_coverage_min": 1.0,
                "known_source_coverage_time_weighted": 1.0,
                "stale_subtraction_prevented_count": 0,
                "partial_residual_point_count": 0,
                "negative_residual_point_count": 0,
            }
            for session_id, start in published_sessions
        ]
    }
    await store.async_save()

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        title="Published NILM Gate",
        data={
            CONF_ENABLE_EXPERIMENTAL_NILM: True,
            CONF_MAINS_SOURCE_ENTITIES: mains_entities,
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    registry_entry = next(
        item
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
        if item.unique_id
        == f"{entry_id}_nilm_assignment-washer_estimated_power"
    )
    assert registry_entry.config_entry_id == entry_id
    state = hass.states.get(registry_entry.entity_id)
    assert state is not None
    assert state.state == "unavailable"
    device_registry = dr.async_get(hass)
    device_identifier = (DOMAIN, f"{entry_id}_nilm_assignment-washer")
    assert any(
        device_identifier in item.identifiers
        for item in dr.async_entries_for_config_entry(device_registry, entry_id)
    )

    coordinator = hass.data[DOMAIN][entry_id]
    expected_unique_ids = {
        f"{entry_id}_nilm_assignment-washer_{key}"
        for key in (
            "health_summary",
            "activity_summary",
            "energy_summary",
            "estimated_power",
            "estimated_daily_energy",
            "estimated_running",
        )
    }
    assignment_entries = {
        item.unique_id: item
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
        if item.unique_id.startswith(f"{entry_id}_nilm_assignment-washer_")
    }
    assert set(assignment_entries) == expected_unique_ids
    entity_registry.async_remove(
        assignment_entries[
            f"{entry_id}_nilm_assignment-washer_health_summary"
        ].entity_id
    )
    assert (
        coordinator.nilm_controller._assignment_entities_present(
            "assignment-washer",
            expected=True,
        )
        is False
    )

    unpublished = await coordinator.async_unpublish_nilm_appliance_assignment(
        "mains",
        "assignment-washer",
    )
    await hass.async_block_till_done()
    assert unpublished["lifecycle_state"] == "validated"
    assert hass.states.get(registry_entry.entity_id) is None
    assert not any(
        item.unique_id.startswith(f"{entry_id}_nilm_assignment-washer_")
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
    )
    assert not any(
        device_identifier in item.identifiers
        for item in dr.async_entries_for_config_entry(device_registry, entry_id)
    )

    reloaded_coordinator = hass.data[DOMAIN][entry_id]
    published = await reloaded_coordinator.async_publish_nilm_appliance_assignment(
        "mains",
        "assignment-washer",
    )
    await hass.async_block_till_done()
    assert published["lifecycle_state"] == "published"
    assert any(
        item.unique_id
        == f"{entry_id}_nilm_assignment-washer_estimated_power"
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
    )
    assert any(
        device_identifier in item.identifiers
        for item in dr.async_entries_for_config_entry(device_registry, entry_id)
    )


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_config_entry_runtime_source_changes_update_analyzer_state(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise source updates through the real Home Assistant listener path."""

    caplog.set_level(logging.WARNING)

    from custom_components.circuitsetup_energy_analyzer import coordinator as coord

    monkeypatch.setattr(coord, "SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS", 0.0)
    monkeypatch.setattr(
        coord,
        "SOURCE_ANALYSIS_INTERVAL_SECONDS",
        0.0,
        raising=False,
    )
    _point_custom_components_at_worktree(monkeypatch)
    _set_source_state(hass, "sensor.fridge_power", "0", "W", "power")
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="runtime-listener-entry",
        title="Runtime Listener Gate",
        data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
            CONF_ADVANCED_SETTINGS: {
                "fridge": {
                    "operating_on_threshold_w": 25.0,
                    "operating_off_threshold_w": 10.0,
                    "operating_on_dwell_seconds": 0.0,
                    "operating_off_dwell_seconds": 0.0,
                }
            },
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
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    now = {"value": datetime.now(UTC) + timedelta(seconds=1)}
    coordinator._now_fn = lambda: now["value"]

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "5",
        "W",
        "power",
        expected_operating_state="off",
    )

    assert coordinator.state.latest_real_power_w_by_circuit["fridge"] == 5.0
    assert coordinator.state.operating_state_by_circuit["fridge"] == "off"
    now["value"] += timedelta(seconds=1)

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "84",
        "W",
        "power",
        expected_operating_state="pending_on",
    )

    assert coordinator.state.latest_real_power_w_by_circuit["fridge"] == 84.0
    assert coordinator.state.operating_state_by_circuit["fridge"] == "pending_on"
    now["value"] += timedelta(seconds=1)

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "85",
        "W",
        "power",
        expected_operating_state="running",
    )

    assert coordinator.state.latest_real_power_w_by_circuit["fridge"] == 85.0
    assert coordinator.state.operating_state_by_circuit["fridge"] == "running"
    now["value"] += timedelta(seconds=1)

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "NaN",
        "W",
        "power",
        expected_operating_state="running",
    )

    assert "fridge" not in coordinator.state.latest_real_power_w_by_circuit
    assert coordinator.state.operating_state_by_circuit["fridge"] == "running"
    now["value"] += timedelta(seconds=1)

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "0",
        "W",
        "power",
        expected_operating_state="pending_off",
    )

    assert coordinator.state.latest_real_power_w_by_circuit["fridge"] == 0.0
    assert coordinator.state.operating_state_by_circuit["fridge"] == "pending_off"
    now["value"] += timedelta(seconds=1)

    await _set_source_state_and_wait(
        hass,
        coordinator,
        "sensor.fridge_power",
        "1",
        "W",
        "power",
        expected_operating_state="off",
    )

    assert coordinator.state.latest_real_power_w_by_circuit["fridge"] == 1.0
    assert coordinator.state.operating_state_by_circuit["fridge"] == "off"

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


def _point_custom_components_at_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(__file__).parents[1] / "custom_components")],
    )


def _set_source_state(
    hass: Any,
    entity_id: str,
    state: str,
    unit: str | None = None,
    device_class: str | None = None,
) -> None:
    attributes = {}
    if unit is not None:
        attributes["unit_of_measurement"] = unit
    if device_class is not None:
        attributes["device_class"] = device_class
    hass.states.async_set(entity_id, state, attributes)


async def _set_source_state_and_wait(
    hass: Any,
    coordinator: Any,
    entity_id: str,
    state: str,
    unit: str | None = None,
    device_class: str | None = None,
    *,
    expected_operating_state: str | None = None,
    circuit_id: str = "fridge",
) -> None:
    coordinator.last_source_update_entities = ()
    _set_source_state(hass, entity_id, state, unit, device_class)
    await _wait_for_runtime_update(
        hass,
        coordinator,
        (entity_id,),
        circuit_id=circuit_id,
        expected_operating_state=expected_operating_state,
    )


async def _wait_for_runtime_update(
    hass: Any,
    coordinator: Any,
    changed_entities: tuple[str, ...],
    *,
    circuit_id: str = "fridge",
    expected_operating_state: str | None = None,
) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        await hass.async_block_till_done()
        await asyncio.sleep(0.01)
        await hass.async_block_till_done()
        if coordinator.last_source_update_entities == changed_entities:
            task = coordinator.source_updates.source_update_task
            state_ready = (
                expected_operating_state is None
                or coordinator.state.operating_state_by_circuit.get(circuit_id)
                == expected_operating_state
            )
            if state_ready and (task is None or task.done()):
                return
    assert coordinator.last_source_update_entities == changed_entities
    if expected_operating_state is not None:
        assert (
            coordinator.state.operating_state_by_circuit.get(circuit_id)
            == expected_operating_state
        )


def _registered_platform_domains(hass: Any, entry_id: str) -> set[str]:
    registry = er.async_get(hass)
    return {
        entity_entry.domain
        for entity_entry in er.async_entries_for_config_entry(registry, entry_id)
        if entity_entry.platform == DOMAIN
    }


def _unexpected_lifecycle_log_messages(
    records: list[logging.LogRecord],
) -> list[str]:
    messages: list[str] = []
    for record in records:
        message = record.getMessage()
        if (
            record.levelno >= logging.ERROR
            or record.exc_info is not None
            or _contains_lifecycle_hazard(message)
        ):
            messages.append(message)
    return messages


def _unexpected_lifecycle_warning_messages(warnings: Any) -> list[str]:
    messages: list[str] = []
    for warning in warnings:
        message = str(warning.message)
        if _contains_lifecycle_hazard(message):
            messages.append(message)
    return messages


def _contains_lifecycle_hazard(message: str) -> bool:
    normalized = _normalize_lifecycle_hazard_text(message)
    return any(
        _normalize_lifecycle_hazard_text(fragment) in normalized
        for fragment in LIFECYCLE_LOG_BLOCKLIST
    )


def _normalize_lifecycle_hazard_text(message: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", message.lower()).split())
