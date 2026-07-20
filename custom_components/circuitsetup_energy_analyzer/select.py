from __future__ import annotations

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
    HomeAssistantError,
    async_call_or_raise,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    entity_detail_level_for_coordinator,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
    supports_daily_circuit_controls,
)
from .entity_catalog import compact_descriptions_for_setup
from .sensor import sensitivity_value
from .ux import friendly_sensitivity_label

try:
    from homeassistant.components.select import SelectEntity
except ModuleNotFoundError:

    class SelectEntity:
        """Fallback select base for tests without Home Assistant."""


SENSITIVITY_OPTIONS = ["Quiet", "Balanced", "Sensitive"]
DASHBOARD_LAYOUT_OPTIONS = ["Simple", "Standard", "Expert"]
DASHBOARD_LAYOUT_LABELS = {
    DASHBOARD_LAYOUT_SIMPLE: "Simple",
    DASHBOARD_LAYOUT_STANDARD: "Standard",
    DASHBOARD_LAYOUT_EXPERT: "Expert",
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
            action_label=self.entity_description.name_suffix,
            valid_options=SENSITIVITY_OPTIONS,
        )
        await async_call_or_raise(
            self.coordinator,
            "async_set_circuit_sensitivity",
            f"set {self.entity_description.name_suffix}",
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
            action_label="entity detail level",
            valid_options=ENTITY_DETAIL_LEVELS,
        )
        await async_call_or_raise(
            self.coordinator,
            "async_set_entity_detail_level",
            "set entity detail level",
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
            action_label="dashboard layout",
            valid_options=DASHBOARD_LAYOUT_OPTIONS,
        )
        await async_call_or_raise(
            self.coordinator,
            "async_set_dashboard_layout",
            "set dashboard layout",
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
        descriptions = compact_descriptions_for_setup(
            "select",
            descriptions,
            raw_circuit,
            coordinator,
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


def _select_option_value(
    option: Any,
    *,
    action_label: str,
    valid_options: list[str] | tuple[str, ...],
) -> str:
    normalized = str(option or "").strip().lower()
    if normalized in {value.lower() for value in valid_options}:
        return normalized
    choices = ", ".join(valid_options)
    raise HomeAssistantError(
        f"Cannot set {action_label.strip().lower()} to {option!r}. "
        f"Choose one of: {choices}."
    )
