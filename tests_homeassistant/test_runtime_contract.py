from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.circuitsetup_energy_analyzer import (
    binary_sensor,
    sensor,
)
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_SELECTED_ENTITY_GROUPS,
    CONF_SOURCE_ENTITIES,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
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
from tests_homeassistant.test_lifecycle_gate import (
    _point_custom_components_at_worktree,
    _uses_hierarchical_entity_ids,
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


def _mains_nilm_circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_platform_setup_uses_home_assistant_runtime_registries(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    hass.states.async_set(
        "sensor.laundry_power",
        "42",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="runtime-entry",
        title="Runtime Contract",
        data={
            CONF_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.fridge_energy",
                "sensor.laundry_power",
            ],
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
                    "circuit_id": "laundry_east",
                    "name": "Café, Laundry {East}",
                    "mode": "single_phase",
                    "appliance_profile": "motor_load",
                    "sensors": [
                        {
                            "entity_id": "sensor.laundry_power",
                            "role": "real_power",
                        },
                    ],
                },
            ],
        },
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: ["developer_diagnostics"],
        },
    )
    entry.add_to_hass(hass)

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

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, stale_entity.unique_id)
        is None
    )
    assert not any(
        (DOMAIN, "runtime-entry_obsolete") in item.identifiers
        for item in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    )
    assert stale_device.id

    expected_entities = {
        "sensor": (
            "runtime-entry_fridge_activity_summary",
            "sensor.kitchen_fridge_activity_summary",
            "Activity summary",
            None,
            True,
            False,
        ),
        "binary_sensor": (
            "runtime-entry_fridge_learning",
            "binary_sensor.kitchen_fridge_learning",
            "Learning",
            EntityCategory.DIAGNOSTIC,
            True,
            True,
        ),
        "button": (
            "runtime-entry_fridge_relearn_baseline",
            "button.fridge_relearn_baseline",
            "Relearn baseline",
            None,
            True,
            False,
        ),
        "switch": (
            "runtime-entry_fridge_maintenance",
            "switch.kitchen_fridge_fridge_maintenance",
            "Pause alerts",
            None,
            True,
            False,
        ),
        "select": (
            "runtime-entry_fridge_alert_sensitivity",
            "select.fridge_alert_sensitivity",
            "Alert sensitivity",
            None,
            True,
            False,
        ),
        "number": (
            "runtime-entry_fridge_daily_energy_goal",
            "number.fridge_daily_energy_goal",
            "Daily energy goal",
            None,
            True,
            False,
        ),
    }
    uses_hierarchical_entity_ids = _uses_hierarchical_entity_ids()
    registry_entries: dict[str, Any] = {}
    for domain, (
        unique_id,
        entity_id,
        expected_name,
        expected_category,
        enabled_by_default,
        hidden_by_default,
    ) in expected_entities.items():
        registered_entity_id = entity_registry.async_get_entity_id(
            domain,
            DOMAIN,
            unique_id,
        )
        assert registered_entity_id is not None
        if not uses_hierarchical_entity_ids:
            assert registered_entity_id == entity_id
        registry_entry = entity_registry.async_get(registered_entity_id)
        assert registry_entry is not None
        registry_entries[domain] = registry_entry
        assert registry_entry.unique_id == unique_id
        assert registry_entry.original_name == expected_name
        assert registry_entry.has_entity_name is True
        assert registry_entry.translation_key is not None
        assert registry_entry.entity_category == expected_category
        assert (registry_entry.disabled_by is None) is enabled_by_default
        assert (registry_entry.hidden_by is not None) is hidden_by_default
        state = hass.states.get(registered_entity_id)
        assert state is not None
        assert state.attributes["friendly_name"] == f"Kitchen Fridge {expected_name}"

    fridge_device = next(
        device
        for device in dr.async_entries_for_config_entry(
            device_registry,
            entry.entry_id,
        )
        if (DOMAIN, "runtime-entry_fridge") in device.identifiers
    )
    assert fridge_device.name == "Kitchen Fridge"
    assert fridge_device.manufacturer == "CircuitSetup"
    assert all(
        registry_entry.device_id == fridge_device.id
        for registry_entry in registry_entries.values()
    )
    if not uses_hierarchical_entity_ids:
        assert entity_registry.async_get_entity_id(
            "sensor",
            DOMAIN,
            "runtime-entry_fridge_daily_energy_usage",
        ) == "sensor.kitchen_fridge_energy_usage_today"
        assert entity_registry.async_get_entity_id(
            "binary_sensor",
            DOMAIN,
            "runtime-entry_fridge_maintenance",
        ) == "binary_sensor.kitchen_fridge_alerts_paused"

    special_entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        "runtime-entry_laundry_east_activity_summary",
    )
    assert special_entity_id is not None
    if not uses_hierarchical_entity_ids:
        assert special_entity_id == "sensor.cafe_laundry_east_activity_summary"
    special_entry = entity_registry.async_get(special_entity_id)
    assert special_entry is not None
    assert special_entry.original_name == "Activity summary"
    assert special_entry.has_entity_name is True
    assert special_entry.translation_key is not None
    special_device = next(
        device
        for device in dr.async_entries_for_config_entry(
            device_registry,
            entry.entry_id,
        )
        if (DOMAIN, "runtime-entry_laundry_east") in device.identifiers
    )
    assert special_device.name == "Café, Laundry {East}"
    assert special_entry.device_id == special_device.id
    special_state = hass.states.get(special_entity_id)
    assert special_state is not None
    assert special_state.attributes["friendly_name"] == (
        "Café, Laundry {East} Activity summary"
    )

    customized_entity_id = "sensor.favorite_fridge_activity"
    entity_registry.async_update_entity(
        registry_entries["sensor"].entity_id,
        new_entity_id=customized_entity_id,
        name="Pinned Fridge Activity",
    )
    assert await hass.config_entries.async_reload(entry.entry_id) is True
    await hass.async_block_till_done()

    reloaded_entry = entity_registry.async_get(customized_entity_id)
    assert reloaded_entry is not None
    assert reloaded_entry.unique_id == "runtime-entry_fridge_activity_summary"
    assert reloaded_entry.name == "Pinned Fridge Activity"
    assert hass.states.get(customized_entity_id).attributes["friendly_name"] == (
        "Pinned Fridge Activity"
    )


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
    assert "via_device" not in estimated_power.device_info
    assert estimated_power.device_class is None
    assert estimated_power.options is None
    assert estimated_power.last_reset is None
    assert estimated_power.suggested_display_precision is None
    assert estimated_power.suggested_unit_of_measurement is None
