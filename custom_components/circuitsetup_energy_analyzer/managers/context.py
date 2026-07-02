from __future__ import annotations

from datetime import datetime
from typing import Any

from ..processors import ProcessingContext


class ProcessingContextBuilder:
    """Build processor runtime context from coordinator state."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def time_zone(self) -> str | None:
        value = getattr(
            getattr(self._coordinator.hass, "config", None),
            "time_zone",
            None,
        )
        return str(value) if value else None

    def build(self, now: datetime) -> ProcessingContext:
        coordinator = self._coordinator
        return ProcessingContext(
            now=now,
            hass=coordinator.hass,
            state=coordinator.state,
            store_data=coordinator.store_data,
            options=coordinator.options,
            entry_data=coordinator.entry_data,
            known_load_circuit_ids=coordinator.circuit_registry.known_load_circuit_ids,
            sensitivity=coordinator.settings_controller.default_sensitivity,
            time_zone=self.time_zone(),
        )
