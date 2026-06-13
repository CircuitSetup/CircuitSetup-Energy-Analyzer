from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def daily_energy_usage_value(state: Any, circuit_id: str) -> float:
    """Return today's cumulative usage derived from the circuit energy sensor."""
    return float(
        getattr(state, "daily_energy_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_usage_share_value(state: Any, circuit_id: str) -> float:
    """Return today's usage as a percent of the learned energy window."""
    return float(
        getattr(state, "energy_usage_share_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_usage_status_value(state: Any, circuit_id: str) -> str:
    """Return the daily energy usage tracker status."""
    evidence = getattr(state, "energy_usage_evidence_by_circuit", {}).get(
        circuit_id,
        {},
    )
    if isinstance(evidence, Mapping):
        return str(evidence.get("status") or "learning")
    return "learning"


def energy_goal_usage_value(state: Any, circuit_id: str) -> float:
    """Return today's usage as a percent of the configured daily goal."""
    return float(
        getattr(state, "energy_goal_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_goal_status_value(state: Any, circuit_id: str) -> str:
    """Return the daily energy goal tracker status."""
    return str(
        getattr(state, "energy_goal_status_by_circuit", {}).get(
            circuit_id,
            "unconfigured",
        )
    )
