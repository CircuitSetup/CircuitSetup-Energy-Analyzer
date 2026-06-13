from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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


def nilm_topology_status_value(state: Any, circuit_id: str) -> str:
    """Return whether mains NILM topology matches the configured circuit mode."""
    return str(
        getattr(state, "nilm_topology_status_by_circuit", {}).get(
            circuit_id,
            "no_match",
        )
    )


def nilm_unknown_loads_value(state: Any, circuit_id: str) -> int:
    """Return the count of reviewable unknown NILM loads for a circuit."""
    inventory = getattr(state, "nilm_unknown_loads_by_circuit", {}).get(
        circuit_id,
        {},
    )
    if isinstance(inventory, Mapping):
        return int(inventory.get("unknown_load_count", 0))
    return 0


def nilm_unknown_loads_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return consolidated unknown NILM load inventory attributes."""
    inventory = getattr(state, "nilm_unknown_loads_by_circuit", {}).get(
        circuit_id,
        {},
    )
    return dict(inventory) if isinstance(inventory, Mapping) else {}
