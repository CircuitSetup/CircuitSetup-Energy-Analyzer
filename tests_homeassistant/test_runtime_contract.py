from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.circuitsetup_energy_analyzer import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_DASHBOARD_LAYOUT,
    CONF_ENTITY_DETAIL_LEVEL,
    DASHBOARD_LAYOUT_EXPERT,
    DOMAIN,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def _circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
        ),
    )


def _mains_nilm_circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )


class _RuntimeCoordinator:
    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self.data = AnalyzerState(
            energy_dashboard_status_by_circuit={"fridge": "ready"},
            latest_real_power_w_by_circuit={"fridge": 84.0},
            sensitivity_by_circuit={"fridge": "balanced"},
        )
        self.circuit_configs = (_circuit(),)
        self.entry_data = {}
        self.options = {
            CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT,
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
        }
        self.dashboard_layout = DASHBOARD_LAYOUT_EXPERT
        self.store_data = SimpleNamespace(
            energy_goal_settings_by_circuit={
                "fridge": {"daily_goal_kwh": 4.5},
            },
        )


class _NilmRuntimeCoordinator:
    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self.data = AnalyzerState()
        self.circuit_configs = (_mains_nilm_circuit(),)
        self.entry_data = {}
        self.options = {
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
        }
        self.store_data = FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "mains_circuit_id": "mains",
                        "signature_fingerprints": ["signature_1"],
                        "publish_entities": True,
                        "created_device": True,
                        "lifecycle_state": "published",
                        "confidence": 0.91,
                    }
                ]
            },
        )
        self._nilm_unmatched_edges = {
            "mains": [
                NilmEdge(
                    timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
                    delta_w=820.0,
                    delta_var=120.0,
                    delta_va=830.0,
                    delta_pf=-0.05,
                    direction="on",
                )
            ]
        }


@pytest.mark.asyncio
async def test_platform_setup_uses_home_assistant_runtime_registries(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="runtime-entry",
        title="Runtime Contract",
        data={},
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = _RuntimeCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    entity_registry = er.async_get(hass)
    stale_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "runtime-entry_fridge_obsolete",
        suggested_object_id="fridge_obsolete",
        config_entry=entry,
    )
    device_registry = dr.async_get(hass)
    stale_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "runtime-entry_obsolete")},
        manufacturer="CircuitSetup",
        name="Old Circuit",
    )
    added_entities: list[Any] = []

    for platform in (sensor, binary_sensor, button, select, number, switch):
        await platform.async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "runtime-entry_setup_health",
        "runtime-entry_fridge_running",
        "runtime-entry_run_mapping_checks",
        "runtime-entry_dashboard_layout",
        "runtime-entry_entity_detail_level",
        "runtime-entry_fridge_daily_energy_goal",
        "runtime-entry_fridge_maintenance",
    } <= unique_ids
    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, stale_entity.unique_id)
        is None
    )
    updated_stale_device = device_registry.async_get_device(
        identifiers={(DOMAIN, "runtime-entry_obsolete")},
    )
    if updated_stale_device is not None:
        assert entry.entry_id not in updated_stale_device.config_entries
    assert stale_device.id


@pytest.mark.asyncio
async def test_platform_setup_restores_published_nilm_virtual_entities(
    hass: Any,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="runtime-entry",
        title="Runtime Contract",
        data={},
        options={},
    )
    entry.add_to_hass(hass)
    coordinator = _NilmRuntimeCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    added_entities: list[Any] = []

    await sensor.async_setup_entry(hass, entry, added_entities.extend)
    await binary_sensor.async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "runtime-entry_nilm_assignment-dishwasher_health_summary",
        "runtime-entry_nilm_assignment-dishwasher_activity_summary",
        "runtime-entry_nilm_assignment-dishwasher_energy_summary",
        "runtime-entry_nilm_assignment-dishwasher_estimated_power",
        "runtime-entry_nilm_assignment-dishwasher_estimated_daily_energy",
        "runtime-entry_nilm_assignment-dishwasher_estimated_running",
    } <= unique_ids
    estimated_power = next(
        entity
        for entity in added_entities
        if entity.unique_id
        == "runtime-entry_nilm_assignment-dishwasher_estimated_power"
    )
    assert estimated_power.extra_state_attributes["estimated"] is True
    assert estimated_power.device_info["model"] == "NILM Estimated Appliance"
