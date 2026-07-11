"""Shared global tariff-setting accessors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GLOBAL_COST_SETTINGS_KEY = "__global__"


def global_cost_settings(coordinator: Any) -> Mapping[str, Any]:
    """Return the analyzer-wide tariff settings."""
    store_data = getattr(coordinator, "store_data", None)
    settings_by_circuit = getattr(store_data, "cost_settings_by_circuit", {})
    if not isinstance(settings_by_circuit, Mapping):
        return {}
    settings = settings_by_circuit.get(GLOBAL_COST_SETTINGS_KEY, {})
    return settings if isinstance(settings, Mapping) else {}


def configured_electricity_rate(cost_settings_by_circuit: Any) -> float:
    """Return the persisted analyzer-wide fallback electricity rate."""
    if not isinstance(cost_settings_by_circuit, Mapping):
        return 0.0
    settings = cost_settings_by_circuit.get(GLOBAL_COST_SETTINGS_KEY, {})
    if not isinstance(settings, Mapping):
        return 0.0
    return _positive_rate(settings.get("default_rate_per_kwh"))


def _positive_rate(value: Any) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 0.0
    return rate if rate > 0.0 else 0.0
