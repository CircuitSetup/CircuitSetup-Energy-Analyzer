from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    EntityCategory,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    hide_entity_registry_entries,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)
from .models import ApplianceProfile, SensorRole

try:
    from homeassistant.components.binary_sensor import BinarySensorEntity
except ModuleNotFoundError:

    class BinarySensorEntity:
        """Fallback binary sensor base for tests without Home Assistant."""


LAUNDRY_RUNNING_POWER_THRESHOLDS_W = {
    ApplianceProfile.WASHER: 20.0,
    ApplianceProfile.DRYER: 100.0,
}


def is_learning(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return whether a circuit is still in its learning period."""
    return bool(getattr(state, "learning_by_circuit", {}).get(circuit_id, True))


def has_data_quality_problem(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return true when a circuit has a non-empty data quality issue."""
    issue = getattr(state, "data_quality_by_circuit", {}).get(circuit_id, "")
    return bool(issue)


def is_maintenance_active(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return whether a circuit is currently marked as in maintenance."""
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    if not isinstance(maintenance, dict):
        return False
    return maintenance.get("active") is True


def is_laundry_appliance_running(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | str | None = None,
) -> bool:
    """Return whether a washer or dryer appears active from latest watts."""
    profile = _appliance_profile(appliance_profile)
    threshold = LAUNDRY_RUNNING_POWER_THRESHOLDS_W.get(profile)
    if threshold is None:
        return False

    power_by_circuit = getattr(state, "latest_real_power_w_by_circuit", {})
    if not isinstance(power_by_circuit, dict):
        return False
    power_w = power_by_circuit.get(circuit_id)
    if power_w is None:
        return False
    try:
        return float(power_w) >= threshold
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class DiagnosticBinarySensorDescription:
    """Description for one diagnostic binary sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str, ApplianceProfile | None], bool]
    device_class: str | None = None
    entity_category: Any | None = EntityCategory.DIAGNOSTIC
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    entity_picture: str | None = None
    force_update: bool = False
    has_entity_name: bool = False
    icon: str | None = None
    name: str | None = None
    translation_key: str | None = None
    translation_placeholders: dict[str, str] | None = None
    unit_of_measurement: str | None = None


BINARY_SENSOR_ICONS = {
    "learning": "mdi:school-outline",
    "data_quality_problem": "mdi:database-alert-outline",
    "maintenance": "mdi:wrench-clock",
    "running": "mdi:power-cycle",
}


BINARY_SENSOR_DESCRIPTIONS: tuple[DiagnosticBinarySensorDescription, ...] = (
    DiagnosticBinarySensorDescription(
        key="learning",
        name_suffix="Learning",
        value_fn=is_learning,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="data_quality_problem",
        name_suffix="Data Quality Problem",
        value_fn=has_data_quality_problem,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="maintenance",
        name_suffix="Maintenance",
        value_fn=is_maintenance_active,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="running",
        name_suffix="Running",
        value_fn=is_laundry_appliance_running,
        device_class="running",
        entity_category=None,
    ),
)


class CircuitAnalyzerBinarySensor(CircuitAnalyzerEntity, BinarySensorEntity):
    """Binary sensor exposing one diagnostic flag for an analyzed circuit."""

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: DiagnosticBinarySensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._appliance_profile = _appliance_profile(
            getattr(circuit, "appliance_profile", None)
        )
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self._attr_icon = description.icon or BINARY_SENSOR_ICONS.get(description.key)

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def is_on(self) -> bool:
        """Return the latest diagnostic flag."""
        if self.coordinator_state is None:
            return self.entity_description.value_fn(
                None,
                self.circuit_id,
                self._appliance_profile,
            )
        return self.entity_description.value_fn(
            self.coordinator_state,
            self.circuit_id,
            self._appliance_profile,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up diagnostic binary sensor entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[CircuitAnalyzerBinarySensor] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitAnalyzerBinarySensor(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in BINARY_SENSOR_DESCRIPTIONS
            if binary_sensor_description_applies(description, circuit)
        )

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="binary_sensor",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    hide_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="binary_sensor",
        hidden_unique_id_suffixes={
            description.key
            for description in BINARY_SENSOR_DESCRIPTIONS
            if description.entity_registry_visible_default is False
        },
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)


def binary_sensor_description_applies(
    description: DiagnosticBinarySensorDescription,
    circuit: Any,
) -> bool:
    """Return whether a binary sensor is useful for this circuit."""
    if description.key != "running":
        return True
    return (
        _appliance_profile(getattr(circuit, "appliance_profile", None))
        in LAUNDRY_RUNNING_POWER_THRESHOLDS_W
        and _has_real_power_sensor(circuit)
    )


def _has_real_power_sensor(circuit: Any) -> bool:
    """Return true when the configured circuit has active-power data."""
    return any(
        _sensor_role(sensor) is SensorRole.REAL_POWER
        for sensor in getattr(circuit, "sensors", ()) or ()
    )


def _sensor_role(sensor: Any) -> SensorRole | None:
    """Return a normalized sensor role from dict or dataclass sensor refs."""
    if isinstance(sensor, dict):
        role = sensor.get("role")
    else:
        role = getattr(sensor, "role", None)
    if isinstance(role, SensorRole):
        return role
    if role is None:
        return None
    try:
        return SensorRole(str(role))
    except ValueError:
        return None


def _appliance_profile(value: Any) -> ApplianceProfile | None:
    """Return a normalized appliance profile value."""
    if isinstance(value, ApplianceProfile):
        return value
    if value is None:
        return None
    try:
        return ApplianceProfile(str(value))
    except ValueError:
        return None
