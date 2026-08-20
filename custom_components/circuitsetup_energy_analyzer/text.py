"""Global Time-of-Use label control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity

from .const import DOMAIN
from .entity import (
    async_call_or_raise,
    device_identifiers_for_entities,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)
from .tariff import global_cost_settings


class GlobalTimeOfUseNameText(TextEntity):
    """Text entity for the analyzer-wide Time-of-Use label."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_icon = "mdi:tag-text-outline"
    _attr_native_max = 64

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = "CircuitSetup Energy Analyzer Time-Of-Use Name"
        self._attr_unique_id = f"{entry_id}_tou_name"
        self._attr_suggested_object_id = "circuitsetup_energy_analyzer_tou_name"

    @property
    def unique_id(self) -> str:
        """Return the stable unique ID for fallback tests."""
        return self._attr_unique_id

    @property
    def suggested_object_id(self) -> str:
        """Return the stable object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def name(self) -> str:
        """Return the visible entity name."""
        return self._attr_name

    @property
    def native_value(self) -> str:
        """Return the configured Time-of-Use label."""
        return str(global_cost_settings(self.coordinator).get("tou_name") or "Peak")

    @property
    def device_info(self) -> dict[str, Any]:
        """Group global tariff controls under the analyzer device."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "CircuitSetup Energy Analyzer",
            "manufacturer": "CircuitSetup",
        }

    @property
    def available(self) -> bool:
        """Return whether the Time-of-Use label can be changed."""
        return callable(getattr(self.coordinator, "async_set_global_tou_name", None))

    async def async_set_value(self, value: str) -> None:
        """Persist the global Time-of-Use label."""
        await async_call_or_raise(
            self.coordinator,
            "async_set_global_tou_name",
            "set Time-of-Use name",
            str(value),
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up the global Time-of-Use label control."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities = [GlobalTimeOfUseNameText(coordinator, entry_id=entry_id)]
    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="text",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)
