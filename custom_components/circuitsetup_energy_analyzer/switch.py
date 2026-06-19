from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    entity_detail_level_for_coordinator,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
    supports_daily_circuit_controls,
)
from .entity_catalog import (
    compact_creation_rule_for_entity,
    legacy_compatibility_keys_for_coordinator,
    selected_entity_groups_for_coordinator,
    should_create_entity,
)

try:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:

    class SwitchEntity:
        """Fallback switch base for tests without Home Assistant."""

    class HomeAssistantError(Exception):
        """Fallback Home Assistant error for tests without Home Assistant."""


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
        name_suffix="Maintenance",
        icon="mdi:wrench-clock",
        has_entity_name=True,
        translation_key="maintenance",
    ),
)


class CircuitMaintenanceSwitch(CircuitAnalyzerEntity, SwitchEntity):
    """Switch entity exposing a circuit's maintenance state."""

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
        self._attr_name = None
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
        """Return whether maintenance is active for this circuit."""
        return _maintenance_active(self.coordinator_state, self.circuit_id)

    @property
    def available(self) -> bool:
        """Return whether both maintenance actions can currently run."""
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
        """Start maintenance for this circuit."""
        del kwargs
        if self.is_on:
            return
        await _call_or_raise(
            self.coordinator,
            "async_start_maintenance",
            self.entity_description.name_suffix,
            self.circuit_id,
            "",
            None,
            False,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """End maintenance for this circuit."""
        del kwargs
        if not self.is_on:
            return
        await _call_or_raise(
            self.coordinator,
            "async_end_maintenance",
            self.entity_description.name_suffix,
            self.circuit_id,
            False,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up switch entities for daily circuit controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[SwitchEntity] = []
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
        descriptions = _compact_switch_descriptions_for_setup(
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


def _compact_switch_descriptions_for_setup(
    descriptions: tuple[CircuitSwitchDescription, ...],
    circuit: Any,
    coordinator: Any,
) -> tuple[CircuitSwitchDescription, ...]:
    compatibility_keys = legacy_compatibility_keys_for_coordinator(coordinator)
    selected_groups = selected_entity_groups_for_coordinator(coordinator)
    detail_level = entity_detail_level_for_coordinator(coordinator)
    compact_descriptions: list[CircuitSwitchDescription] = []
    for description in descriptions:
        rule = compact_creation_rule_for_entity("switch", description.key)
        if not should_create_entity(
            rule=rule,
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
            legacy_compatibility_keys=compatibility_keys,
        ):
            continue
        compact_descriptions.append(description)
    return tuple(compact_descriptions)


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


def _maintenance_actions_available(coordinator: Any) -> bool:
    return callable(getattr(coordinator, "async_start_maintenance", None)) and callable(
        getattr(coordinator, "async_end_maintenance", None)
    )


async def _call_or_raise(
    target: Any,
    method_name: str,
    action_label: str,
    *args: Any,
) -> None:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise HomeAssistantError(
            f"Cannot {action_label.strip().lower()} right now because the "
            "analyzer action is unavailable."
        )
    result = method(*args)
    if inspect.isawaitable(result):
        await result
