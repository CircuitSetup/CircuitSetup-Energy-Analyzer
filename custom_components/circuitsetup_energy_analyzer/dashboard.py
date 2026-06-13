from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .button import CIRCUIT_BUTTON_DESCRIPTIONS, button_description_applies
from .const import (
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUTS,
    DEFAULT_DASHBOARD_LAYOUT,
    DOMAIN,
)
from .number import CIRCUIT_NUMBER_DESCRIPTIONS, number_description_applies

DASHBOARD_TITLE = "CircuitSetup Energy Analyzer"
DASHBOARD_URL_PATH = "circuitsetup-energy-analyzer"
DASHBOARD_ICON = "mdi:home-lightning-bolt-outline"
EVIDENCE_PANEL_PATH = "/circuitsetup-energy-analyzer-evidence"

CORE_ENTITY_SPECS = (
    ("sensor", "health_summary", "Health Summary"),
    ("sensor", "activity_summary", "Activity Summary"),
    ("sensor", "electrical_health", "Electrical Health"),
    ("sensor", "energy_summary", "Energy Summary"),
    ("sensor", "daily_energy_usage", "Daily Energy Usage"),
    ("binary_sensor", "running", "Running"),
)
STANDARD_ENTITY_SPECS = (
    ("sensor", "energy_usage_status", "Energy Usage Status"),
    ("sensor", "energy_goal_status", "Energy Goal Status"),
    ("sensor", "run_cycle_status", "Run Cycle Status"),
    ("sensor", "weather_context", "Weather Context"),
    ("sensor", "rain_pump_correlation", "Rain Pump Correlation"),
    ("sensor", "water_flow_correlation", "Water Flow Correlation"),
    ("sensor", "demand_status", "Demand Status"),
    ("sensor", "capacity_status", "Capacity Status"),
    ("sensor", "leg_imbalance_status", "Leg Imbalance Status"),
    ("sensor", "metric_consistency_status", "Metric Consistency Status"),
    ("sensor", "balance_status", "Balance Status"),
    ("sensor", "solar_flow_status", "Solar Flow Status"),
    ("sensor", "utility_comparison_status", "Utility Comparison Status"),
    ("sensor", "standby_status", "Standby Status"),
    ("sensor", "nilm_unknown_loads", "NILM Unknown Loads"),
)
EXPERT_ENTITY_SPECS = (
    ("sensor", "alert_evidence", "Alert Evidence"),
    ("sensor", "power_quality_evidence", "Power Quality Evidence"),
    ("sensor", "energy_dashboard_status", "Energy Dashboard Status"),
    ("sensor", "data_quality_checklist", "Data Quality Checklist"),
    ("sensor", "readiness", "Readiness"),
    ("sensor", "learning_progress", "Learning Progress"),
    ("sensor", "recent_activity", "Recent Activity"),
    ("sensor", "settings_suggestions", "Settings Suggestions"),
)
GLOBAL_CONTROL_SPECS = (
    ("select", "dashboard_layout", "Dashboard Layout"),
    ("select", "entity_detail_level", "Entity Detail Level"),
    ("button", "run_mapping_checks", "Run Mapping Checks"),
    ("button", "recalculate_suggestions", "Recalculate Suggestions"),
    ("button", "create_dashboard", "Create Or Update Dashboard"),
)
CIRCUIT_CONTROL_SPECS = (
    ("select", "alert_sensitivity", "Alert Sensitivity"),
    ("number", "daily_energy_goal", "Daily Energy Goal"),
    ("button", "relearn_baseline", "Relearn Baseline"),
    ("button", "start_maintenance", "Start Maintenance"),
    ("button", "end_maintenance", "End Maintenance"),
    ("button", "pause_alerts", "Pause Alerts"),
)


def normalize_dashboard_layout(value: Any) -> str:
    """Return a supported recommended-dashboard layout."""
    normalized = str(value or "").strip().lower()
    if normalized in DASHBOARD_LAYOUTS:
        return normalized
    return DEFAULT_DASHBOARD_LAYOUT


def build_recommended_dashboard(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Build a recommended Lovelace dashboard config for analyzer circuits."""
    normalized_layout = normalize_dashboard_layout(layout)
    circuit_list = [
        circuit
        for circuit in circuits
        if str(getattr(circuit, "circuit_id", "")).strip()
    ]
    registry_lookup = _registry_entity_lookup(hass, entry_id)
    cards: list[dict[str, Any]] = [
        _markdown_card(
            "Use this dashboard as a starting point. It shows analyzer-created "
            "entities only. If analyzer entities are missing or disabled, the "
            "dashboard will show a note with the next thing to check."
        )
    ]
    if global_controls_card := _global_controls_card(
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    ):
        cards.append(global_controls_card)
    for circuit in circuit_list:
        cards.append(
            _circuit_card(
                circuit,
                normalized_layout,
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
        )
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


def dashboard_storage_payload(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return the payload used to create/update a Home Assistant dashboard."""
    return {
        "url_path": DASHBOARD_URL_PATH,
        "mode": "storage",
        "title": DASHBOARD_TITLE,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin": False,
        "config": build_recommended_dashboard(
            circuits,
            layout,
            hass=hass,
            entry_id=entry_id,
        ),
    }


def _layout_title(layout: str) -> str:
    if layout == DASHBOARD_LAYOUT_EXPERT:
        return "Expert Energy Analyzer"
    if layout == DASHBOARD_LAYOUT_STANDARD:
        return "Standard Energy Analyzer"
    return "Simple Energy Analyzer"


def _circuit_card(
    circuit: Any,
    layout: str,
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    circuit_id = str(getattr(circuit, "circuit_id", "")).strip()
    name = str(getattr(circuit, "name", "") or circuit_id).strip() or circuit_id
    specs = list(CORE_ENTITY_SPECS)
    if layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}:
        specs.extend(STANDARD_ENTITY_SPECS)
    if layout == DASHBOARD_LAYOUT_EXPERT:
        specs.extend(EXPERT_ENTITY_SPECS)

    entities, notes = _resolved_entity_ids(
        circuit_id,
        specs,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if notes:
        cards.append(_markdown_card(_circuit_note(name, notes)))
    if entities:
        cards.append(
            {
                "type": "entities",
                "title": name,
                "show_header_toggle": False,
                "entities": [{"entity": entity_id} for entity_id in _dedupe(entities)],
            }
        )
    if control_card := _circuit_controls_card(
        circuit,
        name,
        circuit_id,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    ):
        cards.append(control_card)
    if len(cards) == 1:
        return cards[0]
    return {
        "type": "vertical-stack",
        "title": name,
        "cards": cards,
    }


def _resolved_entity_ids(
    circuit_id: str,
    specs: Iterable[tuple[str, str, str]],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> tuple[list[str], list[str]]:
    if not entry_id or registry_lookup is None:
        return [
            _guessed_entity_id(circuit_id, entity_domain, entity_key)
            for entity_domain, entity_key, _label in specs
        ], []

    entity_ids: list[str] = []
    missing_labels: list[str] = []
    disabled_labels: list[str] = []
    unavailable_labels: list[str] = []
    ambiguous_labels: list[str] = []
    for entity_domain, entity_key, label in specs:
        entry, resolution_issue = _registry_entry_for_spec(
            registry_lookup,
            entry_id=entry_id,
            circuit_id=circuit_id,
            entity_domain=entity_domain,
            entity_key=entity_key,
        )
        if resolution_issue == "ambiguous":
            ambiguous_labels.append(label)
            continue
        if entry is None:
            missing_labels.append(label)
            continue
        if getattr(entry, "disabled_by", None):
            disabled_labels.append(label)
            continue
        entity_id = str(getattr(entry, "entity_id", "")).strip()
        if not entity_id:
            missing_labels.append(label)
            continue
        if not entity_id.startswith(f"{entity_domain}."):
            missing_labels.append(label)
            continue
        if _entity_is_unavailable(hass, entity_id):
            unavailable_labels.append(label)
            continue
        entity_ids.append(entity_id)

    notes: list[str] = []
    if disabled_labels:
        notes.append(_dashboard_gap_note("disabled", disabled_labels))
    if missing_labels:
        notes.append(_dashboard_gap_note("missing", missing_labels))
    if unavailable_labels:
        notes.append(_dashboard_gap_note("unavailable", unavailable_labels))
    if ambiguous_labels:
        notes.append(_dashboard_gap_note("ambiguous", ambiguous_labels))
    return entity_ids, notes


def _global_controls_card(
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    entities, notes = _resolved_global_entity_ids(
        GLOBAL_CONTROL_SPECS,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    return _control_card(
        "Dashboard Controls",
        note_title="Dashboard controls note",
        entities=entities,
        notes=notes,
    )


def _circuit_controls_card(
    circuit: Any,
    name: str,
    circuit_id: str,
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    specs = _applicable_circuit_control_specs(circuit)
    if not specs:
        return None
    entities, notes = _resolved_entity_ids(
        circuit_id,
        specs,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    return _control_card(
        f"{name} Controls",
        note_title=f"{name} controls note",
        entities=entities,
        notes=notes,
    )


_CIRCUIT_BUTTON_DESCRIPTION_BY_KEY = {
    description.key: description for description in CIRCUIT_BUTTON_DESCRIPTIONS
}
_CIRCUIT_NUMBER_DESCRIPTION_BY_KEY = {
    description.key: description for description in CIRCUIT_NUMBER_DESCRIPTIONS
}


def _applicable_circuit_control_specs(
    circuit: Any,
) -> tuple[tuple[str, str, str], ...]:
    specs: list[tuple[str, str, str]] = []
    for entity_domain, entity_key, label in CIRCUIT_CONTROL_SPECS:
        if entity_domain == "button":
            description = _CIRCUIT_BUTTON_DESCRIPTION_BY_KEY.get(entity_key)
            if description is not None and not button_description_applies(
                description,
                circuit,
            ):
                continue
        if entity_domain == "number":
            description = _CIRCUIT_NUMBER_DESCRIPTION_BY_KEY.get(entity_key)
            if description is not None and not number_description_applies(
                description,
                circuit,
            ):
                continue
        specs.append((entity_domain, entity_key, label))
    return tuple(specs)


def _control_card(
    title: str,
    *,
    note_title: str,
    entities: Iterable[str],
    notes: Iterable[str],
) -> dict[str, Any] | None:
    cards: list[dict[str, Any]] = []
    note_list = [note for note in notes if note]
    entity_list = list(_dedupe(entities))
    if note_list:
        cards.append(_markdown_card(_note_content(note_title, note_list)))
    if entity_list:
        cards.append(
            {
                "type": "entities",
                "title": title,
                "show_header_toggle": False,
                "entities": [{"entity": entity_id} for entity_id in entity_list],
            }
        )
    if not cards:
        return None
    if len(cards) == 1:
        return cards[0]
    return {"type": "vertical-stack", "title": title, "cards": cards}


def _resolved_global_entity_ids(
    specs: Iterable[tuple[str, str, str]],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> tuple[list[str], list[str]]:
    if not entry_id or registry_lookup is None:
        return [], []

    entity_ids: list[str] = []
    missing_labels: list[str] = []
    disabled_labels: list[str] = []
    unavailable_labels: list[str] = []
    ambiguous_labels: list[str] = []
    for entity_domain, entity_key, label in specs:
        entry, resolution_issue = _registry_entry_for_global_spec(
            registry_lookup,
            entry_id=entry_id,
            entity_domain=entity_domain,
            entity_key=entity_key,
        )
        if resolution_issue == "ambiguous":
            ambiguous_labels.append(label)
            continue
        if entry is None:
            missing_labels.append(label)
            continue
        if getattr(entry, "disabled_by", None):
            disabled_labels.append(label)
            continue
        entity_id = str(getattr(entry, "entity_id", "")).strip()
        if not entity_id or not entity_id.startswith(f"{entity_domain}."):
            missing_labels.append(label)
            continue
        if _entity_is_unavailable(hass, entity_id):
            unavailable_labels.append(label)
            continue
        entity_ids.append(entity_id)

    notes: list[str] = []
    if disabled_labels:
        notes.append(_dashboard_gap_note("disabled", disabled_labels))
    if missing_labels:
        notes.append(_dashboard_gap_note("missing", missing_labels))
    if unavailable_labels:
        notes.append(_dashboard_gap_note("unavailable", unavailable_labels))
    if ambiguous_labels:
        notes.append(_dashboard_gap_note("ambiguous", ambiguous_labels))
    return entity_ids, notes


def _registry_entity_lookup(
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    if hass is None or not entry_id:
        return None
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        registry = getattr(hass, "entity_registry", None)
    else:
        registry = er.async_get(hass)
    if registry is None:
        return None

    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    return {
        unique_id: entry
        for entry in values
        if getattr(entry, "config_entry_id", None) == entry_id
        and getattr(entry, "platform", None) == DOMAIN
        and (unique_id := str(getattr(entry, "unique_id", "")).strip())
    }


def _entity_is_unavailable(hass: Any | None, entity_id: str) -> bool:
    states = getattr(hass, "states", None)
    if states is None:
        return False
    get_state = getattr(states, "get", None)
    if not callable(get_state):
        return False
    state = get_state(entity_id)
    state_value = str(getattr(state, "state", "")).strip().lower()
    return state_value in {"unknown", "unavailable"}


def _circuit_note(name: str, notes: Iterable[str]) -> str:
    return _note_content(f"{name} dashboard note", notes)


def _note_content(title: str, notes: Iterable[str]) -> str:
    lines = [f"**{title}**"]
    lines.extend(note for note in notes if note)
    return "\n".join(lines)


def _dashboard_gap_note(reason: str, labels: Iterable[str]) -> str:
    label_text = ", ".join(labels)
    if reason == "ambiguous":
        return (
            f"Ambiguous entities: {label_text}\n"
            "Next step: remove duplicate stale analyzer entities or reload "
            "the integration."
        )
    if reason == "disabled":
        return (
            f"Disabled entities: {label_text}\n"
            "Next step: enable these entities from Home Assistant entity settings."
        )
    if reason == "unavailable":
        return (
            f"Unavailable entities: {label_text}\n"
            "Next step: open the entity details and follow its availability reason."
        )
    return (
        f"Missing entities: {label_text}\n"
        "Next step: reload the integration or review Entity Detail Level."
    )


def _expected_unique_id(entry_id: str, circuit_id: str, entity_key: str) -> str:
    return f"{entry_id}_{circuit_id}_{entity_key}"


def _expected_global_unique_id(entry_id: str, entity_key: str) -> str:
    return f"{entry_id}_{entity_key}"


def _registry_entry_for_spec(
    registry_lookup: Mapping[str, Any],
    *,
    entry_id: str,
    circuit_id: str,
    entity_domain: str,
    entity_key: str,
) -> tuple[Any | None, str | None]:
    exact = registry_lookup.get(_expected_unique_id(entry_id, circuit_id, entity_key))
    if exact is not None:
        return exact, None

    candidates = [
        entry
        for entry in registry_lookup.values()
        if _entry_entity_domain(entry) == entity_domain
        and _entry_matches_circuit_key(entry, entry_id, circuit_id, entity_key)
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, None


def _registry_entry_for_global_spec(
    registry_lookup: Mapping[str, Any],
    *,
    entry_id: str,
    entity_domain: str,
    entity_key: str,
) -> tuple[Any | None, str | None]:
    exact = registry_lookup.get(_expected_global_unique_id(entry_id, entity_key))
    if exact is not None:
        return exact, None

    candidates = [
        entry
        for entry in registry_lookup.values()
        if _entry_entity_domain(entry) == entity_domain
        and _entry_matches_global_key(entry, entity_key)
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, None


def _entry_matches_circuit_key(
    entry: Any,
    entry_id: str,
    circuit_id: str,
    entity_key: str,
) -> bool:
    entry_circuit = _entry_value(entry, "circuit_id", "circuit")
    entry_key = _entry_value(
        entry,
        "entity_key",
        "description_key",
        "translation_key",
        "key",
    )
    if entry_circuit == circuit_id and entry_key == entity_key:
        return True

    unique_id = str(_entry_value(entry, "unique_id") or "").strip()
    return unique_id == _expected_unique_id(entry_id, circuit_id, entity_key)


def _entry_matches_global_key(entry: Any, entity_key: str) -> bool:
    entry_key = _entry_value(
        entry,
        "entity_key",
        "description_key",
        "translation_key",
        "key",
    )
    if entry_key == entity_key and not _entry_value(entry, "circuit_id", "circuit"):
        return True

    unique_id = str(_entry_value(entry, "unique_id") or "").strip()
    return unique_id.endswith(f"_{entity_key}")


def _entry_entity_domain(entry: Any) -> str:
    entity_id = str(_entry_value(entry, "entity_id") or "").strip()
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _entry_value(entry: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(entry, Mapping) and key in entry:
            return entry[key]
        value = getattr(entry, key, None)
        if value is not None:
            return value
    return None


def _guessed_entity_id(circuit_id: str, entity_domain: str, entity_key: str) -> str:
    return f"{entity_domain}.{circuit_id}_{entity_key}"


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
