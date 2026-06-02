from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import DOMAIN

try:
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
except ModuleNotFoundError:

    class EntityCategory:
        """Fallback entity category constants for tests without Home Assistant."""

        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity:
        """Small CoordinatorEntity fallback for helper tests."""

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator


@dataclass(frozen=True, slots=True)
class CircuitInfo:
    """Normalized configured circuit identity used by platform entities."""

    circuit_id: str
    name: str


def circuit_info_from_config(circuit: Any) -> CircuitInfo | None:
    """Return circuit id/name from a dataclass-like or mapping config object."""
    if isinstance(circuit, dict):
        circuit_id = circuit.get("circuit_id") or circuit.get("id")
        name = circuit.get("name") or circuit_id
    else:
        circuit_id = getattr(circuit, "circuit_id", None)
        name = getattr(circuit, "name", None) or circuit_id

    if not circuit_id:
        return None

    return CircuitInfo(circuit_id=str(circuit_id), name=str(name))


class CircuitAnalyzerEntity(CoordinatorEntity):
    """Base entity for diagnostics associated with one configured circuit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: CircuitInfo,
        key: str,
        name_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._circuit_id = circuit.circuit_id
        self._circuit_name = circuit.name
        self._attr_name = f"{circuit.name} {name_suffix}"
        self._attr_unique_id = f"{entry_id}_{circuit.circuit_id}_{key}"

    @property
    def circuit_id(self) -> str:
        """Configured circuit identifier."""
        return self._circuit_id

    @property
    def circuit_name(self) -> str:
        """Configured circuit display name."""
        return self._circuit_name

    @property
    def name(self) -> str:
        """Entity display name for fallback tests."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Unique id for fallback tests."""
        return self._attr_unique_id

    @property
    def device_info(self) -> dict[str, Any]:
        """Group diagnostic entities by analyzed circuit in Home Assistant."""
        return {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._circuit_id}")},
            "name": self._circuit_name,
            "manufacturer": "CircuitSetup",
        }

    @property
    def coordinator_state(self) -> Any:
        """Current coordinator state, tolerating staged test coordinators."""
        return getattr(self.coordinator, "data", None)
