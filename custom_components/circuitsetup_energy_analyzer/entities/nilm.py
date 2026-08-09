from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

NILM_UNKNOWN_LOADS_ATTRIBUTE_MAX_ITEMS = 5
NILM_UNKNOWN_LOADS_ATTRIBUTE_FIELDS = (
    "signature_id",
    "display_name",
    "likely_type",
    "typical_watts",
    "confidence",
    "first_seen",
    "runtime_7_days_minutes",
    "runtime_30_days_minutes",
    "estimated_energy_7_days_kwh",
    "estimated_energy_30_days_kwh",
    "runtime_windows",
    "estimate_status",
)


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
    if not isinstance(inventory, Mapping) or not inventory:
        return {}

    unknown_loads = inventory.get("unknown_loads", ())
    unknown_load_items = (
        list(unknown_loads)
        if isinstance(unknown_loads, Iterable)
        and not isinstance(unknown_loads, (str, bytes))
        else []
    )
    shown_unknown_loads = [
        _unknown_load_attribute_preview(load)
        for load in unknown_load_items[:NILM_UNKNOWN_LOADS_ATTRIBUTE_MAX_ITEMS]
    ]
    return {
        "unknown_load_count": int(inventory.get("unknown_load_count", 0) or 0),
        "active_unknown_load_count": int(
            inventory.get("active_unknown_load_count", 0) or 0
        ),
        "shown_count": len(shown_unknown_loads),
        "has_more": len(unknown_load_items) > len(shown_unknown_loads),
        "unknown_loads": shown_unknown_loads,
    }


def _unknown_load_attribute_preview(load: Any) -> dict[str, Any]:
    if not isinstance(load, Mapping):
        return {}
    return {
        field: value
        for field in NILM_UNKNOWN_LOADS_ATTRIBUTE_FIELDS
        if (value := load.get(field)) is not None
    }
