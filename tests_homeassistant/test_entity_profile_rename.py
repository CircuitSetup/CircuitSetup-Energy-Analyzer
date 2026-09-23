"""Entity registry rows survive a temporary detail reduction."""

from typing import Any

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_SELECTED_ENTITY_GROUPS,
    CONF_SOURCE_ENTITIES,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
)
from tests_homeassistant.test_lifecycle_gate import _point_custom_components_at_worktree


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_expert_entity_rename_survives_simple_and_back(
    hass: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_custom_components_at_worktree(monkeypatch)
    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="audit-profile-entry",
        title="Audit Profile",
        data={
            CONF_SOURCE_ENTITIES: ["sensor.fridge_power"],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ],
        },
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: ["electrical_scores"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    uid = "audit-profile-entry_fridge_power_quality_score"
    original_id = registry.async_get_entity_id("sensor", DOMAIN, uid)
    assert original_id is not None
    registry.async_update_entity(
        original_id, new_entity_id="sensor.my_fridge_quality", name="My Quality"
    )

    hass.config_entries.async_update_entry(
        entry, options={CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_SIMPLE}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, uid)
        == "sensor.my_fridge_quality"
    )

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: ["electrical_scores"],
        },
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored_id = registry.async_get_entity_id("sensor", DOMAIN, uid)
    assert restored_id is not None
    restored = registry.async_get(restored_id)
    assert restored_id == "sensor.my_fridge_quality"
    assert restored.name == "My Quality"

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_CIRCUITS: [], CONF_SOURCE_ENTITIES: []},
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_CIRCUITS] == []
    assert hass.data[DOMAIN][entry.entry_id].circuit_configs == ()
    assert registry.async_get_entity_id("sensor", DOMAIN, uid) is None
