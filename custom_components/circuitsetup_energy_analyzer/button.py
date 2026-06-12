from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)

try:
    from homeassistant.components.button import ButtonEntity
except ModuleNotFoundError:

    class ButtonEntity:
        """Fallback button base for tests without Home Assistant."""


@dataclass(frozen=True, slots=True)
class CircuitButtonDescription:
    key: str
    name_suffix: str
    method_name: str
    args_fn: Callable[[str], tuple[Any, ...]]
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


@dataclass(frozen=True, slots=True)
class GlobalButtonDescription:
    key: str
    name: str
    method_name: str
    args: tuple[Any, ...]
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


CIRCUIT_BUTTON_DESCRIPTIONS: tuple[CircuitButtonDescription, ...] = (
    CircuitButtonDescription(
        key="relearn_baseline",
        name_suffix="Relearn Baseline",
        method_name="async_relearn_baseline",
        args_fn=lambda circuit_id: (circuit_id,),
        icon="mdi:school-outline",
    ),
    CircuitButtonDescription(
        key="start_maintenance",
        name_suffix="Start Maintenance",
        method_name="async_start_maintenance",
        args_fn=lambda circuit_id: (circuit_id, "", None, False),
        icon="mdi:wrench-clock",
    ),
    CircuitButtonDescription(
        key="end_maintenance",
        name_suffix="End Maintenance",
        method_name="async_end_maintenance",
        args_fn=lambda circuit_id: (circuit_id, False),
        icon="mdi:wrench-check-outline",
    ),
    CircuitButtonDescription(
        key="pause_alerts",
        name_suffix="Pause Alerts",
        method_name="async_pause_alerts",
        args_fn=lambda circuit_id: (circuit_id, None),
        icon="mdi:bell-pause-outline",
    ),
)

GLOBAL_BUTTON_DESCRIPTIONS: tuple[GlobalButtonDescription, ...] = (
    GlobalButtonDescription(
        key="run_mapping_checks",
        name="CircuitSetup Energy Analyzer Run Mapping Checks",
        method_name="async_run_mapping_checks",
        args=(),
        icon="mdi:map-check-outline",
    ),
    GlobalButtonDescription(
        key="recalculate_suggestions",
        name="CircuitSetup Energy Analyzer Recalculate Suggestions",
        method_name="async_recalculate_setting_recommendations",
        args=(None,),
        icon="mdi:tune-variant",
    ),
    GlobalButtonDescription(
        key="create_dashboard",
        name="CircuitSetup Energy Analyzer Create Dashboard",
        method_name="async_create_dashboard",
        args=(),
        icon="mdi:view-dashboard-plus-outline",
    ),
)


class CircuitAnalyzerButton(CircuitAnalyzerEntity, ButtonEntity):
    """Button entity exposing a daily circuit action."""

    _attr_entity_category = None

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: CircuitButtonDescription,
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
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    async def async_press(self) -> None:
        """Run the circuit action."""
        await _call_if_present(
            self.coordinator,
            self.entity_description.method_name,
            *self.entity_description.args_fn(self.circuit_id),
        )


class GlobalAnalyzerButton(ButtonEntity):
    """Button entity exposing an integration-wide action."""

    _attr_has_entity_name = False
    _attr_entity_category = None

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        description: GlobalButtonDescription,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._entry_id = entry_id
        self._attr_name = description.name
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_suggested_object_id = (
            f"circuitsetup_energy_analyzer_{description.key}"
        )
        self._attr_icon = description.icon

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

    async def async_press(self) -> None:
        """Run the integration-wide action."""
        await _call_if_present(
            self.coordinator,
            self.entity_description.method_name,
            *self.entity_description.args,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up action button entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[ButtonEntity] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitAnalyzerButton(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in CIRCUIT_BUTTON_DESCRIPTIONS
        )

    entities.extend(
        GlobalAnalyzerButton(
            coordinator,
            entry_id=entry_id,
            description=description,
        )
        for description in GLOBAL_BUTTON_DESCRIPTIONS
    )

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="button",
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
