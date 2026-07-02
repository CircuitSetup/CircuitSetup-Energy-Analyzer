"""Circuit lookup helpers for coordinator-owned circuit configs."""

from __future__ import annotations

from typing import Any

from ..const import CONF_KNOWN_LOAD_CIRCUITS
from ..context_sources import string_list_from_sources


class CircuitRegistry:
    """Own read-only lookup of configured circuits by circuit ID."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def config_for_circuit(self, circuit_id: str) -> Any | None:
        """Return the configured circuit matching a stable circuit ID."""
        for config in self._coordinator.circuit_configs:
            if config.circuit_id == circuit_id:
                return config
        return None

    @property
    def known_load_circuit_ids(self) -> frozenset[str]:
        """Return configured known-load circuit IDs for mains NILM masking."""
        return frozenset(
            string_list_from_sources(
                self._coordinator.entry_data,
                self._coordinator.options,
                CONF_KNOWN_LOAD_CIRCUITS,
            )
        )
