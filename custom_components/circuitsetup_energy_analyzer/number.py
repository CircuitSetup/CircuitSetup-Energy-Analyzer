from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import CONF_ADVANCED_SETTINGS, DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    async_call_or_raise,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
)
from .entity_catalog import compact_descriptions_for_setup
from .models import SensorRole
from .tariff import configured_electricity_rate, global_cost_settings

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
    device_class: Any | None = None
    entity_category: Any | None = None
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    force_update: bool = False
    has_entity_name: bool = False
    translation_key: str | None = None
    translation_placeholders: Mapping[str, str] | None = None
    unit_of_measurement: str | None = None
    max_value: None = None
    min_value: None = None
    mode: Any | None = None
    step: None = None


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
        await async_call_or_raise(
            self.coordinator,
            "async_set_energy_goal_settings",
            self.entity_description.name_suffix,
            self.circuit_id,
            float(value),
            None,
        )


class GlobalElectricityRateNumber(NumberEntity):
    """Number entity for the analyzer-wide electricity rate."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_icon = "mdi:currency-usd"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "$/kWh"

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = "CircuitSetup Energy Analyzer Fallback Electricity Rate"
        self._attr_unique_id = f"{entry_id}_electricity_rate"
        self._attr_suggested_object_id = (
            "circuitsetup_energy_analyzer_electricity_rate"
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
    def native_value(self) -> float:
        """Return the shared electricity rate, using zero when unconfigured."""
        store_data = getattr(self.coordinator, "store_data", None)
        return configured_electricity_rate(
            getattr(store_data, "cost_settings_by_circuit", {}),
        )

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the currency-per-energy unit."""
        return self._attr_native_unit_of_measurement

    @property
    def device_info(self) -> dict[str, Any]:
        """Group the shared rate under the integration device."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "CircuitSetup Energy Analyzer",
            "manufacturer": "CircuitSetup",
        }

    @property
    def available(self) -> bool:
        """Return whether the shared rate can currently be changed."""
        return callable(getattr(self.coordinator, "async_set_global_cost_rate", None))

    async def async_set_native_value(self, value: float) -> None:
        """Persist an analyzer-wide electricity rate."""
        await async_call_or_raise(
            self.coordinator,
            "async_set_global_cost_rate",
            "set electricity rate",
            float(value),
        )


class GlobalTimeOfUseRateNumber(GlobalElectricityRateNumber):
    """Number entity for the analyzer-wide Time-of-Use rate."""

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        super().__init__(coordinator, entry_id=entry_id)
        self._attr_name = "CircuitSetup Energy Analyzer Time-Of-Use Rate"
        self._attr_unique_id = f"{entry_id}_tou_rate"
        self._attr_suggested_object_id = "circuitsetup_energy_analyzer_tou_rate"

    @property
    def native_value(self) -> float:
        """Return the globally configured Time-of-Use rate."""
        try:
            value = global_cost_settings(self.coordinator).get(
                "tou_rate_per_kwh",
                0.0,
            )
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def available(self) -> bool:
        """Return whether the global Time-of-Use rate can be changed."""
        return callable(getattr(self.coordinator, "async_set_global_tou_rate", None))

    async def async_set_native_value(self, value: float) -> None:
        """Persist the global Time-of-Use rate."""
        await async_call_or_raise(
            self.coordinator,
            "async_set_global_tou_rate",
            "set Time-of-Use rate",
            float(value),
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up number entities for daily circuit controls."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[NumberEntity] = []
    circuit_device_identifiers: set[tuple[str, str]] = set()

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        circuit_device_identifiers.add((DOMAIN, f"{entry_id}_{circuit.circuit_id}"))
        descriptions = tuple(
            description
            for description in CIRCUIT_NUMBER_DESCRIPTIONS
            if number_description_applies(description, raw_circuit, coordinator)
        )
        descriptions = compact_descriptions_for_setup(
            "number",
            descriptions,
            raw_circuit,
            coordinator,
            hass=hass,
            entry_id=entry_id,
        )
        entities.extend(
            CircuitDailyEnergyGoalNumber(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in descriptions
        )

    entities.extend(
        (
            GlobalElectricityRateNumber(coordinator, entry_id=entry_id),
            GlobalTimeOfUseRateNumber(coordinator, entry_id=entry_id),
        )
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
        desired_identifiers=(
            device_identifiers_for_entities(entities) | circuit_device_identifiers
        ),
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
    advanced_settings = _advanced_settings_for_circuit_id(coordinator, circuit_id)
    if advanced_settings.get("daily_goal_kwh") is not None:
        try:
            return float(advanced_settings["daily_goal_kwh"])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def number_description_applies(
    description: CircuitNumberDescription,
    circuit: Any,
    coordinator: Any | None = None,
) -> bool:
    """Return whether a number control is useful for this circuit."""
    if description.key != "daily_energy_goal":
        return True
    if _has_energy_sensor(circuit):
        return True
    circuit_id = _circuit_id(circuit)
    state = getattr(coordinator, "data", None)
    if circuit_id in getattr(state, "daily_energy_usage_by_circuit", {}):
        return True
    evidence = getattr(state, "energy_usage_evidence_by_circuit", {}).get(circuit_id)
    return isinstance(evidence, Mapping) and bool(evidence)


def _has_energy_sensor(circuit: Any) -> bool:
    return any(
        _sensor_role(sensor) is SensorRole.ENERGY
        and _sensor_unit_is_cumulative_energy(sensor)
        for sensor in _circuit_sensors(circuit)
    )


def _sensor_unit_is_cumulative_energy(sensor: Any) -> bool:
    unit = _sensor_value(sensor, "unit")
    if unit is None:
        return True
    normalized = str(unit).strip().lower().replace(" ", "")
    return normalized in {"kwh", "wh", "mwh"}


def _sensor_role(sensor: Any) -> SensorRole | None:
    role = _sensor_value(sensor, "role")
    if isinstance(role, SensorRole):
        return role
    try:
        return SensorRole(str(role))
    except (TypeError, ValueError):
        return None


def _sensor_value(sensor: Any, key: str) -> Any:
    if isinstance(sensor, Mapping):
        return sensor.get(key)
    return getattr(sensor, key, None)


def _advanced_settings_for_circuit_id(
    coordinator: Any | None,
    circuit_id: str,
) -> Mapping[str, Any]:
    if coordinator is None:
        return {}
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        settings_by_circuit = (
            container.get(CONF_ADVANCED_SETTINGS)
            if isinstance(container, Mapping)
            else None
        )
        if not isinstance(settings_by_circuit, Mapping):
            continue
        settings = settings_by_circuit.get(circuit_id, {})
        if isinstance(settings, Mapping):
            return settings
    return {}


def _circuit_id(circuit: Any) -> str:
    return str(_circuit_value(circuit, "circuit_id", "") or "")


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
