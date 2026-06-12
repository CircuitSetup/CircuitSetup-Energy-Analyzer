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
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)

try:
    from homeassistant.components.number import NumberEntity
    from homeassistant.const import UnitOfEnergy
except ModuleNotFoundError:

    class NumberEntity:
        """Fallback number base for tests without Home Assistant."""

    class UnitOfEnergy:
        """Fallback energy unit constants."""

        KILO_WATT_HOUR = "kWh"


@dataclass(frozen=True, slots=True)
class CircuitNumberDescription:
    key: str
    name_suffix: str
    icon: str
    native_min_value: float
    native_max_value: float
    native_step: float
    native_unit_of_measurement: str


CIRCUIT_NUMBER_DESCRIPTIONS: tuple[CircuitNumberDescription, ...] = (
    CircuitNumberDescription(
        key="daily_energy_goal",
        name_suffix="Daily Energy Goal",
        icon="mdi:target",
        native_min_value=0.0,
        native_max_value=100000.0,
        native_step=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
)


class CircuitDailyEnergyGoalNumber(CircuitAnalyzerEntity, NumberEntity):
    """Number entity for a circuit's daily kWh goal."""

    _attr_entity_category = None

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: CircuitNumberDescription,
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
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = (
            description.native_unit_of_measurement
        )
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
    def native_value(self) -> float:
        """Return the configured daily kWh goal, using 0 when unset."""
        return _daily_energy_goal_value(self.coordinator, self.circuit_id)

    @property
    def native_min_value(self) -> float:
        """Return the minimum supported goal."""
        return self._attr_native_min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum supported goal."""
        return self._attr_native_max_value

    @property
    def native_step(self) -> float:
        """Return the supported goal increment."""
        return self._attr_native_step

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the native energy unit."""
        return self._attr_native_unit_of_measurement

    async def async_set_native_value(self, value: float) -> None:
        """Persist the new daily kWh goal."""
        await _call_if_present(
            self.coordinator,
            "async_set_energy_goal_settings",
            self.circuit_id,
            float(value),
            None,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up number entities for daily circuit controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[NumberEntity] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitDailyEnergyGoalNumber(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in CIRCUIT_NUMBER_DESCRIPTIONS
        )

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="number",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)


def _daily_energy_goal_value(coordinator: Any, circuit_id: str) -> float:
    store_data = getattr(coordinator, "store_data", None)
    settings_by_circuit = getattr(store_data, "energy_goal_settings_by_circuit", {})
    if isinstance(settings_by_circuit, Mapping):
        settings = settings_by_circuit.get(circuit_id, {})
        if isinstance(settings, Mapping) and settings.get("daily_goal_kwh") is not None:
            try:
                return float(settings["daily_goal_kwh"])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


async def _call_if_present(target: Any, method_name: str, *args: Any) -> None:
    method = getattr(target, method_name, None)
    if method is None:
        return
    result = method(*args)
    if inspect.isawaitable(result):
        await result
