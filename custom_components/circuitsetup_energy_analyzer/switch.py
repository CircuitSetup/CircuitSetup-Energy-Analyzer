from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    async_call_or_raise,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
    supports_daily_circuit_controls,
)
from .entity_catalog import compact_descriptions_for_setup
from .tariff import global_cost_settings

try:
    from homeassistant.components.switch import SwitchEntity
except ModuleNotFoundError:

    class SwitchEntity:
        """Fallback switch base for tests without Home Assistant."""


@dataclass(frozen=True, slots=True)
class CircuitSwitchDescription:
    key: str
    name_suffix: str
    icon: str
    device_class: Any | None = None
    entity_category: Any | None = None
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    force_update: bool = False
    has_entity_name: bool = False
    translation_key: str | None = None
    translation_placeholders: Mapping[str, str] | None = None
    unit_of_measurement: str | None = None


CIRCUIT_SWITCH_DESCRIPTIONS: tuple[CircuitSwitchDescription, ...] = (
    CircuitSwitchDescription(
        key="maintenance",
        name_suffix="Pause alerts",
        icon="mdi:bell-pause-outline",
        has_entity_name=True,
        translation_key="maintenance",
    ),
)

_TOU_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class CircuitMaintenanceSwitch(CircuitAnalyzerEntity, SwitchEntity):
    """Switch entity exposing whether circuit alerts are paused."""

    _attr_entity_category = None

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: CircuitSwitchDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._attr_name = description.name_suffix
        self._attr_has_entity_name = description.has_entity_name
        self._attr_icon = description.icon
        self._attr_suggested_object_id = f"{self.circuit_id}_{description.key}"
        self._attr_translation_key = description.translation_key

    @property
    def suggested_object_id(self) -> str:
        """Return the stable object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def is_on(self) -> bool:
        """Return whether alerts are paused for this circuit."""
        return _alerts_paused(self.coordinator_state, self.coordinator, self.circuit_id)

    @property
    def available(self) -> bool:
        """Return whether both pause and resume actions can currently run."""
        return _maintenance_actions_available(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose bounded maintenance metadata for this circuit."""
        details = _maintenance_details(self.coordinator_state, self.circuit_id)
        attributes = {
            key: details[key]
            for key in ("started_at", "expires_at", "note", "relearn_on_end")
            if key in details
        }
        return attributes or None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pause alerts for this circuit."""
        del kwargs
        if self.is_on:
            return
        await async_call_or_raise(
            self.coordinator,
            "async_start_maintenance",
            self.entity_description.name_suffix,
            self.circuit_id,
            "",
            None,
            False,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Resume alerts for this circuit."""
        del kwargs
        if not self.is_on:
            return
        await async_call_or_raise(
            self.coordinator,
            "async_end_maintenance",
            self.entity_description.name_suffix,
            self.circuit_id,
            False,
        )


class GlobalTimeOfUseWeekdaySwitch(SwitchEntity):
    """Switch entity for one analyzer-wide Time-of-Use weekday."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator: Any, *, entry_id: str, weekday: int) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._weekday = weekday
        self._attr_name = (
            f"CircuitSetup Energy Analyzer Time-Of-Use {_TOU_WEEKDAY_NAMES[weekday]}"
        )
        self._attr_unique_id = f"{entry_id}_tou_weekday_{weekday}"
        self._attr_suggested_object_id = (
            f"circuitsetup_energy_analyzer_tou_{_TOU_WEEKDAY_NAMES[weekday].lower()}"
        )

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
    def is_on(self) -> bool:
        """Return whether this weekday uses the Time-of-Use rate."""
        weekdays = str(global_cost_settings(self.coordinator).get("tou_weekdays") or "")
        return str(self._weekday) in {value.strip() for value in weekdays.split(",")}

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
        """Return whether this weekday can be changed."""
        return callable(getattr(self.coordinator, "async_set_global_tou_weekday", None))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable this Time-of-Use weekday."""
        del kwargs
        if not self.is_on:
            await async_call_or_raise(
                self.coordinator,
                "async_set_global_tou_weekday",
                "enable Time-of-Use weekday",
                self._weekday,
                True,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable this Time-of-Use weekday."""
        del kwargs
        if self.is_on:
            await async_call_or_raise(
                self.coordinator,
                "async_set_global_tou_weekday",
                "disable Time-of-Use weekday",
                self._weekday,
                False,
            )

async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up switch entities for daily circuit controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[SwitchEntity] = [
        GlobalTimeOfUseWeekdaySwitch(
            coordinator,
            entry_id=entry_id,
            weekday=weekday,
        )
        for weekday in range(7)
    ]
    circuit_device_identifiers: set[tuple[str, str]] = set()

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        circuit_device_identifiers.add((DOMAIN, f"{entry_id}_{circuit.circuit_id}"))
        descriptions = tuple(
            description
            for description in CIRCUIT_SWITCH_DESCRIPTIONS
            if switch_description_applies(description, raw_circuit, coordinator)
        )
        descriptions = compact_descriptions_for_setup(
            "switch",
            descriptions,
            raw_circuit,
            coordinator,
        )
        entities.extend(
            CircuitMaintenanceSwitch(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in descriptions
        )

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="switch",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=(
            device_identifiers_for_entities(entities) | circuit_device_identifiers
        ),
    )
    async_add_entities(entities)


def switch_description_applies(
    description: CircuitSwitchDescription,
    circuit: Any,
    coordinator: Any | None = None,
) -> bool:
    """Return whether a switch control is useful for this circuit."""
    del coordinator
    if description.key != "maintenance":
        return True
    return supports_daily_circuit_controls(circuit)


def _maintenance_details(state: Any, circuit_id: str) -> Mapping[str, Any]:
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    if not isinstance(maintenance, Mapping):
        return {}
    return maintenance


def _maintenance_active(state: Any, circuit_id: str) -> bool:
    return _maintenance_details(state, circuit_id).get("active") is True


def _alerts_paused(state: Any, coordinator: Any, circuit_id: str) -> bool:
    paused_circuits = getattr(coordinator, "paused_circuits", ()) or ()
    return circuit_id in paused_circuits or _maintenance_active(state, circuit_id)


def _maintenance_actions_available(coordinator: Any) -> bool:
    return callable(getattr(coordinator, "async_start_maintenance", None)) and callable(
        getattr(coordinator, "async_end_maintenance", None)
    )
