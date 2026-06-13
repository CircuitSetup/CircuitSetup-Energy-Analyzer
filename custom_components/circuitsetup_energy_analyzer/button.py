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
from .models import ApplianceProfile, SensorRole

try:
    from homeassistant.components.button import ButtonEntity
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:

    class ButtonEntity:
        """Fallback button base for tests without Home Assistant."""

    class HomeAssistantError(Exception):
        """Fallback Home Assistant error for tests without Home Assistant."""


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

    @property
    def available(self) -> bool:
        """Return whether the action is currently usable."""
        return _button_availability_reason(
            self.entity_description.key,
            self.circuit_id,
            self.coordinator_state,
            self.coordinator,
        ) is None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose why a daily action is unavailable when relevant."""
        reason = _button_availability_reason(
            self.entity_description.key,
            self.circuit_id,
            self.coordinator_state,
            self.coordinator,
        )
        if reason is None:
            return None
        return _availability_attributes(reason)

    async def async_press(self) -> None:
        """Run the circuit action."""
        reason = _button_availability_reason(
            self.entity_description.key,
            self.circuit_id,
            self.coordinator_state,
            self.coordinator,
        )
        if reason is not None:
            raise HomeAssistantError(
                f"Cannot {self.entity_description.name_suffix.strip().lower()} "
                f"right now because {reason.replace('_', ' ')}: "
                f"{_availability_reason_label(reason)}"
            )
        await _call_or_raise(
            self.coordinator,
            self.entity_description.method_name,
            self.entity_description.name_suffix,
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
    def available(self) -> bool:
        """Return whether the global action can currently run."""
        return callable(
            getattr(self.coordinator, self.entity_description.method_name, None)
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Group global controls under one integration device."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "CircuitSetup Energy Analyzer",
            "manufacturer": "CircuitSetup",
        }

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose global action availability and dashboard action results."""
        attributes: dict[str, str] = {}
        if not self.available:
            attributes.update(_availability_attributes("action_unavailable"))
        if self.entity_description.key != "create_dashboard":
            return attributes or None
        request = getattr(self.coordinator, "last_dashboard_create_request", None)
        if not isinstance(request, Mapping):
            return attributes or None

        for source_key, attribute_key in (
            ("action", "last_dashboard_action"),
            ("reason", "last_dashboard_reason"),
            ("dashboard_path", "last_dashboard_path"),
            ("layout", "last_dashboard_layout"),
        ):
            value = str(request.get(source_key) or "").strip()
            if value:
                attributes[attribute_key] = value
        return attributes or None

    async def async_press(self) -> None:
        """Run the integration-wide action."""
        await _call_or_raise(
            self.coordinator,
            self.entity_description.method_name,
            self.entity_description.name,
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
            if button_description_applies(description, raw_circuit, coordinator)
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


def button_description_applies(
    description: CircuitButtonDescription,
    circuit: Any,
    coordinator: Any | None = None,
) -> bool:
    """Return whether a daily button is useful for this circuit."""
    del coordinator
    if description.key not in {
        "relearn_baseline",
        "start_maintenance",
        "end_maintenance",
        "pause_alerts",
    }:
        return True
    return _supports_daily_circuit_actions(circuit)


def _supports_daily_circuit_actions(circuit: Any) -> bool:
    profile = _appliance_profile(_circuit_value(circuit, "appliance_profile"))
    if profile in {
        ApplianceProfile.MAINS_NILM,
        ApplianceProfile.SOLAR_INVERTER,
        ApplianceProfile.MIXED,
    }:
        return False
    return _has_real_power_sensor(circuit)


def _button_availability_reason(
    button_key: str,
    circuit_id: str,
    state: Any,
    coordinator: Any,
) -> str | None:
    method_name = next(
        (
            description.method_name
            for description in CIRCUIT_BUTTON_DESCRIPTIONS
            if description.key == button_key
        ),
        None,
    )
    if method_name is not None and not callable(
        getattr(coordinator, method_name, None)
    ):
        return "action_unavailable"

    if button_key == "start_maintenance" and _maintenance_active(state, circuit_id):
        return "maintenance_active"
    if button_key == "end_maintenance" and not _maintenance_active(state, circuit_id):
        return "maintenance_inactive"
    if button_key == "pause_alerts":
        if _alerts_paused(state, coordinator, circuit_id):
            return "alerts_paused"
        if not _has_active_alert(state, circuit_id):
            return "no_active_alert"
    return None


def _availability_reason_label(reason: str) -> str:
    return {
        "action_unavailable": "The analyzer action is unavailable.",
        "maintenance_active": "Maintenance is already active for this circuit.",
        "maintenance_inactive": "Maintenance is not active for this circuit.",
        "alerts_paused": "Alerts are already paused for this circuit.",
        "no_active_alert": "No active alert is available to pause.",
    }.get(reason, reason.replace("_", " "))


def _availability_attributes(reason: str) -> dict[str, str]:
    return {
        "availability_reason": reason,
        "availability_label": _availability_reason_label(reason),
        "next_step": _availability_next_step(reason),
    }


def _availability_next_step(reason: str) -> str:
    return {
        "action_unavailable": "Reload the integration or check the system log.",
        "maintenance_active": "Use End Maintenance when work is complete.",
        "maintenance_inactive": "Use Start Maintenance before ending maintenance.",
        "alerts_paused": "End maintenance or wait for the alert pause to expire.",
        "no_active_alert": (
            "Review the circuit summary or evidence panel for current alerts."
        ),
    }.get(reason, "Review the circuit controls and try again.")


def _maintenance_active(state: Any, circuit_id: str) -> bool:
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    return isinstance(maintenance, Mapping) and maintenance.get("active") is True


def _alerts_paused(state: Any, coordinator: Any, circuit_id: str) -> bool:
    paused_circuits = getattr(coordinator, "paused_circuits", ())
    return circuit_id in paused_circuits or _maintenance_active(state, circuit_id)


def _has_active_alert(state: Any, circuit_id: str) -> bool:
    alerts_by_circuit = getattr(state, "active_alerts_by_circuit", {})
    if not isinstance(alerts_by_circuit, Mapping):
        return False
    alerts = alerts_by_circuit.get(circuit_id)
    if isinstance(alerts, int | float):
        return alerts > 0
    if isinstance(alerts, Mapping):
        return bool(alerts)
    try:
        return len(alerts) > 0
    except TypeError:
        return bool(alerts)


def _has_real_power_sensor(circuit: Any) -> bool:
    return any(
        _sensor_role(sensor) is SensorRole.REAL_POWER
        for sensor in _circuit_sensors(circuit)
    )


def _sensor_role(sensor: Any) -> SensorRole | None:
    role = (
        sensor.get("role")
        if isinstance(sensor, dict)
        else getattr(sensor, "role", None)
    )
    if isinstance(role, SensorRole):
        return role
    try:
        return SensorRole(str(role))
    except (TypeError, ValueError):
        return None


def _circuit_sensors(circuit: Any) -> tuple[Any, ...]:
    sensors = _circuit_value(circuit, "sensors", ())
    if isinstance(sensors, tuple):
        return sensors
    if isinstance(sensors, list):
        return tuple(sensors)
    return ()


def _circuit_value(circuit: Any, key: str, default: Any = None) -> Any:
    if isinstance(circuit, Mapping):
        return circuit.get(key, default)
    return getattr(circuit, key, default)


def _appliance_profile(value: Any) -> ApplianceProfile | None:
    if isinstance(value, ApplianceProfile):
        return value
    try:
        return ApplianceProfile(str(value))
    except (TypeError, ValueError):
        return None


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
