from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_DASHBOARD_LAYOUT,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
    DEFAULT_DASHBOARD_LAYOUT,
    DOMAIN,
)
from .dashboard import normalize_dashboard_layout
from .entity import (
    ENTITY_DETAIL_LEVELS,
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
    legacy_compatibility_keys_for_setup,
    selected_entity_groups_for_coordinator,
    should_create_entity,
)
from .sensor import sensitivity_value
from .ux import friendly_sensitivity_label

try:
    from homeassistant.components.select import SelectEntity
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:

    class SelectEntity:
        """Fallback select base for tests without Home Assistant."""

    class HomeAssistantError(Exception):
        """Fallback Home Assistant error for tests without Home Assistant."""


SENSITIVITY_OPTIONS = ["Quiet", "Balanced", "Sensitive"]
DASHBOARD_LAYOUT_OPTIONS = ["Simple", "Standard", "Expert"]
DASHBOARD_LAYOUT_LABELS = {
    DASHBOARD_LAYOUT_SIMPLE: "Simple",
    DASHBOARD_LAYOUT_STANDARD: "Standard",
    DASHBOARD_LAYOUT_EXPERT: "Expert",
}
SENSITIVITY_SELECT_ALIASES = {
    "low": "quiet",
    "quiet": "quiet",
    "standard": "balanced",
    "balanced": "balanced",
    "high": "sensitive",
    "sensitive": "sensitive",
}
DASHBOARD_LAYOUT_SELECT_ALIASES = {
    DASHBOARD_LAYOUT_SIMPLE: DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD: DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUT_EXPERT: DASHBOARD_LAYOUT_EXPERT,
    "simple": DASHBOARD_LAYOUT_SIMPLE,
    "standard": DASHBOARD_LAYOUT_STANDARD,
    "expert": DASHBOARD_LAYOUT_EXPERT,
}


@dataclass(frozen=True, slots=True)
class CircuitSelectDescription:
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
    options: list[str] | None = None


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
        return friendly_sensitivity_label(
            sensitivity_value(self.coordinator_state, self.circuit_id)
        )

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def available(self) -> bool:
        """Return whether the sensitivity preset can currently be changed."""
        return self._coordinator_available() and _select_action_available(
            self.coordinator,
            "async_set_circuit_sensitivity",
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose why the select is unavailable when relevant."""
        if self.available:
            return None
        if not _select_action_available(
            self.coordinator,
            "async_set_circuit_sensitivity",
        ):
            return _action_unavailable_attributes()
        return None

    def _coordinator_available(self) -> bool:
        """Return the backing coordinator availability when HA exposes it."""
        try:
            return bool(super().available)
        except AttributeError:
            return getattr(self.coordinator, "last_update_success", True) is not False

    async def async_select_option(self, option: str) -> None:
        """Persist a new sensitivity preset."""
        preset = _select_option_value(
            option,
            aliases=SENSITIVITY_SELECT_ALIASES,
            action_label=self.entity_description.name_suffix,
            valid_options=SENSITIVITY_OPTIONS,
        )
        await _call_or_raise(
            self.coordinator,
            "async_set_circuit_sensitivity",
            self.entity_description.name_suffix,
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

    @property
    def available(self) -> bool:
        """Return whether the entity detail level can currently be changed."""
        return _select_action_available(
            self.coordinator,
            "async_set_entity_detail_level",
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose why the select is unavailable when relevant."""
        if self.available:
            return None
        return _action_unavailable_attributes()

    async def async_select_option(self, option: str) -> None:
        """Persist and apply a new entity detail profile."""
        detail_level = _select_option_value(
            option,
            aliases={level: level for level in ENTITY_DETAIL_LEVELS},
            action_label="entity detail level",
            valid_options=ENTITY_DETAIL_LEVELS,
        )
        await _call_or_raise(
            self.coordinator,
            "async_set_entity_detail_level",
            "entity detail level",
            detail_level,
        )


class DashboardLayoutSelect(SelectEntity):
    """Select entity for the recommended dashboard layout."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_options = DASHBOARD_LAYOUT_OPTIONS
    _attr_icon = "mdi:view-dashboard-edit-outline"

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = "CircuitSetup Energy Analyzer Dashboard Layout"
        self._attr_unique_id = f"{entry_id}_dashboard_layout"
        self._attr_suggested_object_id = "circuitsetup_energy_analyzer_dashboard_layout"

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
        """Return supported recommended-dashboard layouts."""
        return list(self._attr_options)

    @property
    def current_option(self) -> str:
        """Return the selected recommended-dashboard layout."""
        options = getattr(self.coordinator, "options", {}) or {}
        return DASHBOARD_LAYOUT_LABELS[
            normalize_dashboard_layout(
                getattr(
                    self.coordinator,
                    "dashboard_layout",
                    options.get(CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT),
                )
            )
        ]

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

    @property
    def available(self) -> bool:
        """Return whether the dashboard layout can currently be changed."""
        return _select_action_available(
            self.coordinator,
            "async_set_dashboard_layout",
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose why the select is unavailable when relevant."""
        if self.available:
            return None
        return _action_unavailable_attributes()

    async def async_select_option(self, option: str) -> None:
        """Persist a new recommended-dashboard layout."""
        layout = _select_option_value(
            option,
            aliases=DASHBOARD_LAYOUT_SELECT_ALIASES,
            action_label="dashboard layout",
            valid_options=DASHBOARD_LAYOUT_OPTIONS,
        )
        await _call_or_raise(
            self.coordinator,
            "async_set_dashboard_layout",
            "dashboard layout",
            layout,
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
        descriptions = tuple(
            description
            for description in CIRCUIT_SELECT_DESCRIPTIONS
            if select_description_applies(description, raw_circuit, coordinator)
        )
        descriptions = _compact_select_descriptions_for_setup(
            descriptions,
            raw_circuit,
            coordinator,
            hass=hass,
            entry_id=entry_id,
        )
        entities.extend(
            CircuitAlertSensitivitySelect(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in descriptions
        )

    entities.extend(
        (
            EntityDetailLevelSelect(coordinator, entry_id=entry_id),
            DashboardLayoutSelect(coordinator, entry_id=entry_id),
        )
    )

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


def _compact_select_descriptions_for_setup(
    descriptions: tuple[CircuitSelectDescription, ...],
    circuit: Any,
    coordinator: Any,
    *,
    hass: Any,
    entry_id: str,
) -> tuple[CircuitSelectDescription, ...]:
    compatibility_keys = legacy_compatibility_keys_for_setup(
        hass,
        entry_id=entry_id,
        coordinator=coordinator,
    )
    selected_groups = selected_entity_groups_for_coordinator(coordinator)
    detail_level = entity_detail_level_for_coordinator(coordinator)
    compact_descriptions: list[CircuitSelectDescription] = []
    for description in descriptions:
        rule = compact_creation_rule_for_entity("select", description.key)
        if not should_create_entity(
            rule=rule,
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
            legacy_compatibility_keys=compatibility_keys,
            applicability_already_checked=True,
        ):
            continue
        compact_descriptions.append(description)
    return tuple(compact_descriptions)


def select_description_applies(
    description: CircuitSelectDescription,
    circuit: Any,
    coordinator: Any | None = None,
) -> bool:
    """Return whether a select control is useful for this circuit."""
    del coordinator
    if description.key == "alert_sensitivity":
        return True
    return supports_daily_circuit_controls(circuit)


def _select_action_available(coordinator: Any, method_name: str) -> bool:
    return callable(getattr(coordinator, method_name, None))


def _action_unavailable_attributes() -> dict[str, str]:
    return {
        "availability_reason": "action_unavailable",
        "availability_label": "The analyzer action is unavailable.",
        "next_step": "Reload the integration or check the system log.",
    }


async def _call_or_raise(
    target: Any,
    method_name: str,
    action_label: str,
    *args: Any,
) -> None:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise HomeAssistantError(
            f"Cannot set {action_label.strip().lower()} right now because the "
            "analyzer action is unavailable."
        )
    result = method(*args)
    if inspect.isawaitable(result):
        await result


def _select_option_value(
    option: Any,
    *,
    aliases: Mapping[str, str],
    action_label: str,
    valid_options: list[str] | tuple[str, ...],
) -> str:
    normalized = str(option or "").strip().lower()
    if normalized in aliases:
        return aliases[normalized]
    choices = ", ".join(valid_options)
    raise HomeAssistantError(
        f"Cannot set {action_label.strip().lower()} to {option!r}. "
        f"Choose one of: {choices}."
    )
