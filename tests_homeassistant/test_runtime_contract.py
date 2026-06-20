from __future__ import annotations

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
