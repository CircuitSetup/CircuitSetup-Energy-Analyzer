from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    circuit_info_from_config,
    circuits_for_entities,
)

try:
    from homeassistant.components.sensor import SensorEntity, SensorStateClass
    from homeassistant.const import PERCENTAGE
except ModuleNotFoundError:
    PERCENTAGE = "%"

    class SensorEntity:
        """Fallback sensor base for tests without Home Assistant."""

        @property
        def state(self) -> Any:
            return getattr(self, "native_value", None)

    class SensorStateClass:
        """Fallback sensor state class constants."""

        MEASUREMENT = "measurement"


def anomaly_score_value(state: Any, circuit_id: str) -> float:
    """Return the current anomaly score for a circuit."""
    return float(getattr(state, "anomaly_score_by_circuit", {}).get(circuit_id, 0.0))


def last_event_value(state: Any, circuit_id: str) -> str | None:
    """Return the last event type value for a circuit."""
    event = getattr(state, "last_event_by_circuit", {}).get(circuit_id)
    if event is None:
        return None
    return event.event_type.value


def nilm_signature_count_value(state: Any, circuit_id: str) -> int:
    """Return the number of discovered NILM signatures for a circuit."""
    return int(
        getattr(state, "nilm_signature_count_by_circuit", {}).get(circuit_id, 0)
    )


def nilm_unmatched_load_percentage_value(state: Any, circuit_id: str) -> float:
    """Return the NILM unmatched load percentage for a circuit."""
    return float(
        getattr(state, "nilm_unmatched_load_percentage_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


@dataclass(frozen=True, slots=True)
class DiagnosticSensorDescription:
    """Description for one diagnostic sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str], Any]
    native_unit_of_measurement: str | None = None
    state_class: str | None = None


SENSOR_DESCRIPTIONS: tuple[DiagnosticSensorDescription, ...] = (
    DiagnosticSensorDescription(
        key="anomaly_score",
        name_suffix="Anomaly Score",
        value_fn=anomaly_score_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="last_event",
        name_suffix="Last Event",
        value_fn=last_event_value,
    ),
    DiagnosticSensorDescription(
        key="nilm_signature_count",
        name_suffix="NILM Discovered Signatures",
        value_fn=nilm_signature_count_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="nilm_unmatched_load_percentage",
        name_suffix="NILM Unmatched Load Percentage",
        value_fn=nilm_unmatched_load_percentage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


class CircuitAnalyzerSensor(CircuitAnalyzerEntity, SensorEntity):
    """Sensor exposing one diagnostic value for an analyzed circuit."""

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: DiagnosticSensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class

    @property
    def native_value(self) -> Any:
        """Return the latest diagnostic value."""
        if self.coordinator_state is None:
            return self.entity_description.value_fn(None, self.circuit_id)
        return self.entity_description.value_fn(
            self.coordinator_state,
            self.circuit_id,
        )


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up diagnostic sensor entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[CircuitAnalyzerSensor] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitAnalyzerSensor(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in SENSOR_DESCRIPTIONS
        )

    async_add_entities(entities)
