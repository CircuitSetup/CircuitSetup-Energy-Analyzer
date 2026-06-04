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
)

try:
    from homeassistant.components.binary_sensor import BinarySensorEntity
except ModuleNotFoundError:

    class BinarySensorEntity:
        """Fallback binary sensor base for tests without Home Assistant."""


def is_learning(state: Any, circuit_id: str) -> bool:
    """Return whether a circuit is still in its learning period."""
    return bool(getattr(state, "learning_by_circuit", {}).get(circuit_id, True))


def has_data_quality_problem(state: Any, circuit_id: str) -> bool:
    """Return true when a circuit has a non-empty data quality issue."""
    issue = getattr(state, "data_quality_by_circuit", {}).get(circuit_id, "")
    return bool(issue)


def is_maintenance_active(state: Any, circuit_id: str) -> bool:
    """Return whether a circuit is currently marked as in maintenance."""
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    if not isinstance(maintenance, dict):
        return False
    return maintenance.get("active") is True


@dataclass(frozen=True, slots=True)
class DiagnosticBinarySensorDescription:
    """Description for one diagnostic binary sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str], bool]
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


BINARY_SENSOR_DESCRIPTIONS: tuple[DiagnosticBinarySensorDescription, ...] = (
    DiagnosticBinarySensorDescription(
        key="learning",
        name_suffix="Learning",
        value_fn=is_learning,
    ),
    DiagnosticBinarySensorDescription(
        key="data_quality_problem",
        name_suffix="Data Quality Problem",
        value_fn=has_data_quality_problem,
    ),
    DiagnosticBinarySensorDescription(
        key="maintenance",
        name_suffix="Maintenance",
        value_fn=is_maintenance_active,
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

    @property
    def is_on(self) -> bool:
        """Return the latest diagnostic flag."""
        if self.coordinator_state is None:
            return self.entity_description.value_fn(None, self.circuit_id)
        return self.entity_description.value_fn(
            self.coordinator_state,
            self.circuit_id,
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
        )

    async_add_entities(entities)
