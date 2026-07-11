"""Global Time-of-Use boundary controls."""

from __future__ import annotations

from datetime import time as time_of_day
from typing import Any

from .const import DOMAIN
from .entity import (
    async_call_or_raise,
    device_identifiers_for_entities,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)
from .tariff import global_cost_settings

try:
    from homeassistant.components.time import TimeEntity
except ModuleNotFoundError:

    class TimeEntity:
        """Fallback time base for tests without Home Assistant."""


_TOU_TIME_DETAILS = {
    "tou_start": ("Time-Of-Use Start", "mdi:clock-start"),
    "tou_end": ("Time-Of-Use End", "mdi:clock-end"),
}


class GlobalTimeOfUseTime(TimeEntity):
    """Time entity for one analyzer-wide Time-of-Use boundary."""

    _attr_has_entity_name = False
    _attr_entity_category = None

    def __init__(self, coordinator: Any, *, entry_id: str, field: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._field = field
        name_suffix, self._attr_icon = _TOU_TIME_DETAILS[field]
        self._attr_name = f"CircuitSetup Energy Analyzer {name_suffix}"
        self._attr_unique_id = f"{entry_id}_{field}"
        self._attr_suggested_object_id = f"circuitsetup_energy_analyzer_{field}"

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
    def native_value(self) -> time_of_day | None:
        """Return the configured Time-of-Use boundary."""
        value = global_cost_settings(self.coordinator).get(self._field)
        try:
            return time_of_day.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

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
        """Return whether this boundary can be changed."""
        return callable(getattr(self.coordinator, "async_set_global_tou_time", None))

    async def async_set_value(self, value: time_of_day) -> None:
        """Persist the global Time-of-Use boundary."""
        await async_call_or_raise(
            self.coordinator,
            "async_set_global_tou_time",
            f"set {self._field}",
            self._field,
            value,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up global Time-of-Use boundary controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities = [
        GlobalTimeOfUseTime(coordinator, entry_id=entry_id, field=field)
        for field in _TOU_TIME_DETAILS
    ]
    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="time",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)
