from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    ENTITY_DETAIL_LEVELS,
    CircuitAnalyzerEntity,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    entity_detail_level_for_coordinator,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)
from .sensor import sensitivity_value
from .ux import normalize_sensitivity

try:
    from homeassistant.components.select import SelectEntity
except ModuleNotFoundError:

    class SelectEntity:
        """Fallback select base for tests without Home Assistant."""


SENSITIVITY_OPTIONS = ["quiet", "balanced", "sensitive"]


@dataclass(frozen=True, slots=True)
class CircuitSelectDescription:
    key: str
    name_suffix: str
    icon: str


CIRCUIT_SELECT_DESCRIPTIONS: tuple[CircuitSelectDescription, ...] = (
    CircuitSelectDescription(
        key="alert_sensitivity",
        name_suffix="Alert Sensitivity",
        icon="mdi:tune-variant",
    ),
)


class CircuitAlertSensitivitySelect(CircuitAnalyzerEntity, SelectEntity):
    """Select entity for a circuit's daily alert sensitivity."""

    _attr_entity_category = None
    _attr_options = SENSITIVITY_OPTIONS

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: CircuitSelectDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._attr_icon = description.icon
        self._attr_suggested_object_id = f"{self.circuit_id}_{description.key}"

    @property
    def suggested_object_id(self) -> str:
        """Return the stable object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def options(self) -> list[str]:
        """Return supported sensitivity presets."""
        return list(self._attr_options)

    @property
    def current_option(self) -> str:
        """Return the active sensitivity preset."""
        return normalize_sensitivity(
            sensitivity_value(self.coordinator_state, self.circuit_id)
        )

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    async def async_select_option(self, option: str) -> None:
        """Persist a new sensitivity preset."""
        preset = normalize_sensitivity(option)
        await _call_if_present(
            self.coordinator,
            "async_set_circuit_sensitivity",
            self.circuit_id,
            preset,
        )


class EntityDetailLevelSelect(SelectEntity):
    """Select entity for the integration's default entity detail level."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_options = list(ENTITY_DETAIL_LEVELS)
    _attr_icon = "mdi:format-list-bulleted-type"

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = "CircuitSetup Energy Analyzer Entity Detail Level"
        self._attr_unique_id = f"{entry_id}_entity_detail_level"
        self._attr_suggested_object_id = (
            "circuitsetup_energy_analyzer_entity_detail_level"
        )

    @property
    def name(self) -> str:
        """Return the visible entity name for fallback tests."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Return the stable unique ID for fallback tests."""
        return self._attr_unique_id

    @property
    def suggested_object_id(self) -> str:
        """Return the stable object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def options(self) -> list[str]:
        """Return supported entity detail profiles."""
        return list(self._attr_options)

    @property
    def current_option(self) -> str:
        """Return the active entity detail profile."""
        return entity_detail_level_for_coordinator(self.coordinator)

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def device_info(self) -> dict[str, Any]:
        """Group global controls under one integration device."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "CircuitSetup Energy Analyzer",
            "manufacturer": "CircuitSetup",
        }

    async def async_select_option(self, option: str) -> None:
        """Persist and apply a new entity detail profile."""
        if option not in ENTITY_DETAIL_LEVELS:
            return
        await _call_if_present(
            self.coordinator,
            "async_set_entity_detail_level",
            option,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up select entities for daily circuit and integration controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[SelectEntity] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitAlertSensitivitySelect(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in CIRCUIT_SELECT_DESCRIPTIONS
        )

    entities.append(EntityDetailLevelSelect(coordinator, entry_id=entry_id))

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="select",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)


async def _call_if_present(target: Any, method_name: str, *args: Any) -> None:
    method = getattr(target, method_name, None)
    if method is None:
        return
    result = method(*args)
    if inspect.isawaitable(result):
        await result
