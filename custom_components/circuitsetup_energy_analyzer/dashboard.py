from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import (
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUTS,
    DEFAULT_DASHBOARD_LAYOUT,
)

DASHBOARD_TITLE = "CircuitSetup Energy Analyzer"
DASHBOARD_URL_PATH = "circuitsetup-energy-analyzer"
DASHBOARD_ICON = "mdi:home-lightning-bolt-outline"
EVIDENCE_PANEL_PATH = "/circuitsetup-energy-analyzer-evidence"

CORE_SENSOR_SUFFIXES = (
    "health_summary",
    "activity_summary",
    "electrical_health",
    "energy_summary",
    "daily_energy_usage",
)
STANDARD_SENSOR_SUFFIXES = (
    "energy_usage_status",
    "energy_goal_status",
    "run_cycle_status",
    "weather_context",
    "rain_pump_correlation",
    "water_flow_correlation",
    "demand_status",
    "capacity_status",
    "leg_imbalance_status",
    "metric_consistency_status",
    "balance_status",
    "solar_flow_status",
    "utility_comparison_status",
    "standby_status",
    "nilm_unknown_loads",
)
EXPERT_SENSOR_SUFFIXES = (
    "alert_evidence",
    "power_quality_evidence",
    "energy_dashboard_status",
    "data_quality_checklist",
    "readiness",
    "learning_progress",
    "recent_activity",
    "settings_suggestions",
)


def normalize_dashboard_layout(value: Any) -> str:
    """Return a supported recommended-dashboard layout."""
    normalized = str(value or "").strip().lower()
    if normalized in DASHBOARD_LAYOUTS:
        return normalized
    return DEFAULT_DASHBOARD_LAYOUT


def build_recommended_dashboard(circuits: Iterable[Any], layout: Any) -> dict[str, Any]:
    """Build a recommended Lovelace dashboard config for analyzer circuits."""
    normalized_layout = normalize_dashboard_layout(layout)
    circuit_list = [
        circuit
        for circuit in circuits
        if str(getattr(circuit, "circuit_id", "")).strip()
    ]
    cards: list[dict[str, Any]] = [
        _markdown_card(
            "Use this dashboard as a starting point. It shows analyzer-created "
            "entities only; Home Assistant will hide cards whose entities do not exist."
        )
    ]
    for circuit in circuit_list:
        cards.append(_circuit_card(circuit, normalized_layout))
    if normalized_layout == DASHBOARD_LAYOUT_EXPERT:
        cards.append(
            _markdown_card(
                f"Open detailed alert evidence from notifications or visit "
                f"{EVIDENCE_PANEL_PATH}."
            )
        )

    return {
        "title": DASHBOARD_TITLE,
        "views": [
            {
                "title": DASHBOARD_TITLE,
                "path": DASHBOARD_URL_PATH,
                "icon": DASHBOARD_ICON,
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "title": _layout_title(normalized_layout),
                        "cards": cards,
                    }
                ],
            }
        ],
    }


def dashboard_storage_payload(circuits: Iterable[Any], layout: Any) -> dict[str, Any]:
    """Return the payload used to create/update a Home Assistant dashboard."""
    return {
        "url_path": DASHBOARD_URL_PATH,
        "mode": "storage",
        "title": DASHBOARD_TITLE,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin": False,
        "config": build_recommended_dashboard(circuits, layout),
    }


def _layout_title(layout: str) -> str:
    if layout == DASHBOARD_LAYOUT_EXPERT:
        return "Expert Energy Analyzer"
    if layout == DASHBOARD_LAYOUT_STANDARD:
        return "Standard Energy Analyzer"
    return "Simple Energy Analyzer"


def _circuit_card(circuit: Any, layout: str) -> dict[str, Any]:
    circuit_id = str(getattr(circuit, "circuit_id", "")).strip()
    name = str(getattr(circuit, "name", "") or circuit_id).strip() or circuit_id
    entities = [_sensor_entity(circuit_id, suffix) for suffix in CORE_SENSOR_SUFFIXES]
    entities.append(f"binary_sensor.{circuit_id}_running")
    if layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}:
        entities.extend(
            _sensor_entity(circuit_id, suffix)
            for suffix in STANDARD_SENSOR_SUFFIXES
        )
    if layout == DASHBOARD_LAYOUT_EXPERT:
        entities.extend(
            _sensor_entity(circuit_id, suffix) for suffix in EXPERT_SENSOR_SUFFIXES
        )

    return {
        "type": "entities",
        "title": name,
        "show_header_toggle": False,
        "entities": [{"entity": entity_id} for entity_id in _dedupe(entities)],
    }


def _sensor_entity(circuit_id: str, suffix: str) -> str:
    return f"sensor.{circuit_id}_{suffix}"


def _markdown_card(content: str) -> dict[str, str]:
    return {"type": "markdown", "content": content}


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
