from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import (
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUTS,
    DEFAULT_DASHBOARD_LAYOUT,
    DOMAIN,
)

DASHBOARD_TITLE = "CircuitSetup Energy Analyzer"
DASHBOARD_URL_PATH = "circuitsetup-energy-analyzer"
DASHBOARD_ICON = "mdi:home-lightning-bolt-outline"
NILM_DASHBOARD_GRAPHS_CARD = "custom:circuitsetup-energy-analyzer-dashboard-graphs"
NILM_ESTIMATED_POWER_KEY = "estimated_power"

APPLIANCE_STATUS_ENTITY_SPECS = (
    ("sensor", "activity_summary", "Activity"),
    ("sensor", "electrical_health", "Electrical Health"),
    ("sensor", "energy_summary", "Energy Summary"),
    ("sensor", "daily_energy_usage", "Daily Energy Usage"),
)
MAINS_ROLLUP_ENTITY_SPECS = (
    ("sensor", "activity_summary", "Activity"),
    ("sensor", "electrical_health", "Electrical"),
    ("sensor", "energy_summary", "Energy"),
)
MAINS_LOAD_MATCH_ENTITY_SPECS = (
    ("sensor", "monitored_power", "Known Appliance Load"),
    ("sensor", "balance_power", "Unassigned Mains Load"),
    ("sensor", "monitored_coverage", "Known Load Share"),
)
UNKNOWN_LOAD_SIGNAL_ENTITY_SPECS = (
    ("sensor", "nilm_unknown_loads", "Inventory"),
    ("sensor", "nilm_signature_count", "Signatures"),
    ("sensor", "monitored_coverage", "Known Load Share"),
)
SOLAR_FLOW_ENTITY_SPECS = (
    ("sensor", "solar_flow_status", "Solar Flow"),
    ("sensor", "solar_surplus_power", "Solar Surplus"),
)
UTILITY_COMPARISON_ENTITY_SPECS = (
    ("sensor", "utility_comparison_difference", "Utility Difference"),
    ("sensor", "utility_comparison_status", "Utility Status"),
)
HVAC_WEATHER_ENTITY_SPECS = (
    ("sensor", "daily_energy_usage", "Daily Energy Usage"),
)
WATER_FLOW_PROFILES = {
    "sump_pump",
    "washer",
    "water_heater",
    "water_pump",
    "well_pump",
}
HVAC_WEATHER_PROFILES = {
    "hvac",
    "hvac_compressor",
    "hvac_blower",
    "electric_heat",
}


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
    outdoor_temperature_entity: str | None = None,
) -> dict[str, Any]:
    """Build a recommended Lovelace dashboard config for analyzer circuits."""
    normalized_layout = normalize_dashboard_layout(layout)
    include_feature_cards = _layout_includes_feature_cards(normalized_layout)
    include_expert_links = normalized_layout == DASHBOARD_LAYOUT_EXPERT
    circuit_list = [
        circuit
        for circuit in circuits
        if _circuit_id(circuit)
    ]
    registry_lookup = _registry_entity_lookup(hass, entry_id)
    appliance_circuits = [
        circuit for circuit in circuit_list if not _is_mains_circuit(circuit)
    ]
    mains_circuits = [circuit for circuit in circuit_list if _is_mains_circuit(circuit)]
    hvac_circuits = [
        circuit for circuit in appliance_circuits if _is_hvac_circuit(circuit)
    ]

    sections = [
        _household_overview_section(
            appliance_circuits,
            mains_circuits=mains_circuits,
            include_feature_cards=include_feature_cards,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ),
        _todays_energy_section(
            appliance_circuits,
            mains_circuits=mains_circuits,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ),
        _behavior_watchlist_section(
            appliance_circuits,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ),
        _appliance_status_section(
            appliance_circuits,
            include_evidence_links=include_feature_cards,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
    ]
    if mains_circuits:
        sections.append(
            _mains_section(
                mains_circuits[0],
                include_feature_cards=include_feature_cards,
                include_dashboard_graph_cards=include_expert_links,
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
        )
    sections.append(
        _energy_tracking_section(
            appliance_circuits,
            mains_circuits=mains_circuits,
            include_feature_cards=include_feature_cards,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
    )
    sections.append(
        _appliance_run_timeline_section(
            appliance_circuits,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
    )
    if include_feature_cards and mains_circuits:
        sections.append(
            _nilm_review_section(
                mains_circuits[0],
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
        )
    if include_feature_cards and hvac_circuits:
        sections.append(
            _hvac_weather_section(
                hvac_circuits[0],
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
                outdoor_temperature_entity=outdoor_temperature_entity,
            )
        )
    if include_expert_links:
        sections.append(_expert_evidence_section(circuit_list))

    dashboard = {
        "title": DASHBOARD_TITLE,
        "views": [
            {
                "title": "Overview",
                "path": "overview",
                "icon": DASHBOARD_ICON,
                "type": "sections",
                "max_columns": 4,
                "dense_section_placement": True,
                "sections": sections,
            }
        ],
    }
    return dashboard


def dashboard_preflight_summary(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None = None,
    entry_id: str | None = None,
    outdoor_temperature_entity: str | None = None,
) -> dict[str, Any]:
    """Return the sections and data classes the generated dashboard will use."""
    normalized_layout = normalize_dashboard_layout(layout)
    include_feature_cards = _layout_includes_feature_cards(normalized_layout)
    include_expert_links = normalized_layout == DASHBOARD_LAYOUT_EXPERT
    circuit_list = [
        circuit
        for circuit in circuits
        if _circuit_id(circuit)
    ]
    appliance_circuits = [
        circuit for circuit in circuit_list if not _is_mains_circuit(circuit)
    ]
    mains_circuits = [circuit for circuit in circuit_list if _is_mains_circuit(circuit)]
    hvac_circuits = [
        circuit for circuit in appliance_circuits if _is_hvac_circuit(circuit)
    ]
    will_include = _dashboard_section_titles(
        appliance_circuits=appliance_circuits,
        mains_circuits=mains_circuits,
        hvac_circuits=hvac_circuits,
        include_feature_cards=include_feature_cards,
        include_expert_links=include_expert_links,
    )
    all_sections = [
        "Household Overview",
        "Today's Energy",
        "Behavior Watchlist",
        "Appliance Status",
        "Mains, Solar, and NILM",
        "Energy Tracking",
        "Appliance Run Timeline",
        "NILM Review",
        "HVAC Weather Context",
        "Diagnostics and Evidence",
    ]
    registry_lookup = _registry_entity_lookup(hass, entry_id)
    missing_source_data, disabled_entities = _dashboard_preflight_entity_gaps(
        appliance_circuits,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    return {
        "layout": normalized_layout,
        "will_include": will_include,
        "will_skip": [
            section for section in all_sections if section not in will_include
        ],
        "missing_source_data": missing_source_data,
        "disabled_entities": disabled_entities,
        "nilm_enabled": bool(mains_circuits),
        "nilm_sections_enabled": include_feature_cards and bool(mains_circuits),
        "estimated_appliance_count": len(
            _published_nilm_power_rows(registry_lookup, entry_id)
        ),
        "outdoor_temperature_entity": outdoor_temperature_entity or None,
    }


def _dashboard_preflight_entity_gaps(
    appliance_circuits: Sequence[Any],
    *,
    registry_lookup: Mapping[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> tuple[list[str], list[str]]:
    if registry_lookup is None or not entry_id:
        return [], []

    missing: list[str] = []
    disabled: list[str] = []
    for circuit in appliance_circuits:
        circuit_id = _circuit_id(circuit)
        circuit_name = _circuit_name(circuit)
        for entity_domain, entity_key, label in APPLIANCE_STATUS_ENTITY_SPECS:
            entry, resolution_issue = _registry_entry_for_spec(
                registry_lookup,
                entry_id=entry_id,
                circuit_id=circuit_id,
                entity_domain=entity_domain,
                entity_key=entity_key,
            )
            preflight_label = f"{circuit_name}: {label}"
            if resolution_issue == "ambiguous" or entry is None:
                missing.append(preflight_label)
                continue
            if _entry_value(entry, "disabled_by"):
                disabled.append(preflight_label)
                continue
            entity_id = str(_entry_value(entry, "entity_id") or "").strip()
            if (
                not entity_id
                or not entity_id.startswith(f"{entity_domain}.")
                or _entity_is_unavailable(hass, entity_id)
            ):
                missing.append(preflight_label)
    return list(_dedupe(missing)), list(_dedupe(disabled))


def dashboard_storage_payload(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None = None,
    entry_id: str | None = None,
    outdoor_temperature_entity: str | None = None,
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
            outdoor_temperature_entity=outdoor_temperature_entity,
        ),
    }


def _dashboard_section_titles(
    *,
    appliance_circuits: Sequence[Any],
    mains_circuits: Sequence[Any],
    hvac_circuits: Sequence[Any],
    include_feature_cards: bool,
    include_expert_links: bool,
) -> list[str]:
    titles = [
        "Household Overview",
        "Today's Energy",
        "Behavior Watchlist",
        "Appliance Status",
    ]
    if mains_circuits:
        titles.append("Mains, Solar, and NILM")
    titles.extend(["Energy Tracking", "Appliance Run Timeline"])
    if include_feature_cards and mains_circuits:
        titles.append("NILM Review")
    if include_feature_cards and hvac_circuits:
        titles.append("HVAC Weather Context")
    if include_expert_links:
        titles.append("Diagnostics and Evidence")
    return titles


def _household_overview_section(
    appliance_circuits: Iterable[Any],
    *,
    mains_circuits: Iterable[Any],
    include_feature_cards: bool,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    appliance_list = list(appliance_circuits)
    mains_list = list(mains_circuits)
    cards: list[dict[str, Any]] = []
    setup_health = _resolved_setup_health_entity_id(
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if setup_health:
        cards.append(
            {
                "type": "tile",
                "entity": setup_health,
                "name": "Setup Health",
                "vertical": False,
            }
        )

    if mains_list:
        overview_rows, _ = _resolved_entity_rows(
            _circuit_id(mains_list[0]),
            (
                ("sensor", "monitored_power", "Total Monitored Power"),
                ("sensor", "monitored_coverage", "Known Load Coverage"),
            ),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if include_feature_cards:
            unknown_loads = _resolved_entity_id(
                _circuit_id(mains_list[0]),
                ("sensor", "nilm_unknown_loads", "NILM Review Count"),
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
            if unknown_loads:
                overview_rows.append(
                    {"entity": unknown_loads, "name": "NILM Review Count"}
                )
        if overview_rows:
            cards.append(_entities_card("Household energy overview", overview_rows))

    activity_rows = _resolved_rows_for_circuits(
        appliance_list[:5],
        ("sensor", "activity_summary", "Activity"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if activity_rows:
        cards.append(
            {
                "type": "glance",
                "title": "Top appliances right now",
                "columns": min(len(activity_rows), 5),
                "entities": activity_rows,
            }
        )
    if not cards:
        cards.append(_markdown_card("Household overview appears after setup."))
    return {"type": "grid", "title": "Household Overview", "cards": cards}


def _todays_energy_section(
    appliance_circuits: Iterable[Any],
    *,
    mains_circuits: Iterable[Any],
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    circuits = [*list(appliance_circuits), *list(mains_circuits)]
    daily_rows = _resolved_rows_for_circuits(
        circuits,
        ("sensor", "daily_energy_usage", "Daily Energy Usage"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if daily_rows:
        cards.append(
            {
                "type": "glance",
                "title": "Top energy users today",
                "columns": min(len(daily_rows), 5),
                "entities": daily_rows[:5],
            }
        )
        cards.append(
            _statistics_graph_card(
                "Today's appliance energy",
                [row["entity"] for row in daily_rows],
            )
        )
    else:
        cards.append(_markdown_card("Today's energy appears after kWh sources report."))
    return {"type": "grid", "title": "Today's Energy", "cards": cards}


def _behavior_watchlist_section(
    appliance_circuits: Iterable[Any],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    circuits = list(appliance_circuits)
    energy_rows = _resolved_rows_for_circuits(
        circuits,
        ("sensor", "energy_summary", "Energy Summary"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    electrical_rows = _resolved_rows_for_circuits(
        circuits,
        ("sensor", "electrical_health", "Electrical Health"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if energy_rows:
        cards.append(_entities_card("Usage watchlist", energy_rows))
    if electrical_rows:
        cards.append(_entities_card("Electrical watchlist", electrical_rows))
    for circuit in circuits[:3]:
        circuit_id = _circuit_id(circuit)
        if not circuit_id:
            continue
        cards.append(
            {
                "type": "button",
                "name": f"Open {_circuit_name(circuit)} Evidence",
                "icon": "mdi:clipboard-search-outline",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": (
                        f"{DEFAULT_ALERT_EVIDENCE_PATH}?circuit_id={circuit_id}"
                    ),
                },
            }
        )
    if not cards:
        cards.append(_markdown_card("Behavior watchlist appears after entities load."))
    return {"type": "grid", "title": "Behavior Watchlist", "cards": cards}


def _appliance_status_section(
    circuits: Iterable[Any],
    *,
    include_evidence_links: bool,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    cards: list[dict[str, Any]] = [
        _markdown_card(
            "These cards keep each appliance to Activity, Electrical Health, "
            "Energy Summary, and Daily Energy Usage. Daily Energy Usage may show "
            "Waiting For Energy Change until a cumulative kWh source increases."
        )
    ]
    for circuit in circuits:
        circuit_id = _circuit_id(circuit)
        if not circuit_id:
            continue
        name = _circuit_name(circuit)
        rows, notes = _resolved_entity_rows(
            circuit_id,
            APPLIANCE_STATUS_ENTITY_SPECS,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if notes:
            cards.append(_markdown_card(_circuit_note(name, notes)))
        if rows:
            cards.append(_entities_card(name, rows))
            if include_evidence_links:
                cards.append(
                    {
                        "type": "button",
                        "name": f"Open {name} Evidence",
                        "icon": "mdi:chart-line",
                        "tap_action": {
                            "action": "navigate",
                            "navigation_path": (
                                f"{DEFAULT_ALERT_EVIDENCE_PATH}?"
                                f"circuit_id={circuit_id}"
                            ),
                        },
                    }
                )

    return {
        "type": "grid",
        "title": "Appliance Status",
        "cards": cards,
    }


def _mains_section(
    circuit: Any,
    *,
    include_feature_cards: bool,
    include_dashboard_graph_cards: bool,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    circuit_id = _circuit_id(circuit)
    cards: list[dict[str, Any]] = []

    rollup_rows, _ = _resolved_entity_rows(
        circuit_id,
        MAINS_ROLLUP_ENTITY_SPECS,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if rollup_rows:
        cards.append(
            {
                "type": "glance",
                "title": "Mains rollups",
                "columns": 3,
                "entities": rollup_rows,
            }
        )

    if include_feature_cards:
        coverage_entity = _resolved_entity_id(
            circuit_id,
            ("sensor", "monitored_coverage", "Known Load Share"),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if coverage_entity:
            cards.append(
                {
                    "type": "gauge",
                    "entity": coverage_entity,
                    "name": "Known Load Share",
                    "min": 0,
                    "max": 100,
                    "severity": {"red": 0, "yellow": 40, "green": 70},
                }
            )
            cards.append(
                _markdown_card(
                    "Known Load Share is how much of current mains power is explained "
                    "by the circuits you selected. Low values usually mean normal "
                    "unmonitored loads, not necessarily a problem."
                )
            )

        load_rows, _ = _resolved_entity_rows(
            circuit_id,
            MAINS_LOAD_MATCH_ENTITY_SPECS,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if load_rows:
            cards.append(_entities_card("Mains Load Match", load_rows))

        unknown_inventory = _resolved_entity_id(
            circuit_id,
            ("sensor", "nilm_unknown_loads", "Unknown Load Inventory"),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if unknown_inventory:
            cards.append(
                {
                    "type": "tile",
                    "entity": unknown_inventory,
                    "name": "Unknown Load Inventory",
                    "vertical": False,
                }
            )

        unknown_rows, _ = _resolved_entity_rows(
            circuit_id,
            UNKNOWN_LOAD_SIGNAL_ENTITY_SPECS,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if unknown_rows:
            cards.append(
                {
                    "type": "glance",
                    "title": "Unknown load signals",
                    "columns": 3,
                    "entities": unknown_rows,
                }
            )

        cards.append(
            {
                "type": "button",
                "name": "Open NILM Graph & Review",
                "icon": "mdi:chart-line",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": (
                        f"{DEFAULT_ALERT_EVIDENCE_PATH}?"
                        f"nilm_workspace=1&circuit_id={circuit_id}"
                    ),
                },
            }
        )

        if include_dashboard_graph_cards:
            appliance_power_rows = _published_nilm_power_rows(
                registry_lookup,
                entry_id,
            )
            if nilm_graph_card := _nilm_dashboard_graphs_card(
                circuit_id=circuit_id,
                entry_id=entry_id,
                appliance_power_rows=appliance_power_rows,
            ):
                cards.append(nilm_graph_card)

            if appliance_power_graph := _defined_nilm_appliance_power_graph(
                appliance_power_rows
            ):
                cards.append(appliance_power_graph)

        if solar_card := _conditional_entities_card(
            circuit_id,
            SOLAR_FLOW_ENTITY_SPECS,
            "Solar flow",
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ):
            cards.append(solar_card)
        if utility_card := _conditional_entities_card(
            circuit_id,
            UTILITY_COMPARISON_ENTITY_SPECS,
            "Utility comparison",
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ):
            cards.append(utility_card)

    daily_energy = _resolved_entity_id(
        circuit_id,
        ("sensor", "daily_energy_usage", "Daily Energy Usage"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if daily_energy:
        cards.append(_statistics_graph_card("Mains daily energy", [daily_energy]))

    return {
        "type": "grid",
        "title": "Mains, Solar, and NILM",
        "cards": cards,
    }


def _energy_tracking_section(
    circuits: Iterable[Any],
    *,
    mains_circuits: Iterable[Any],
    include_feature_cards: bool,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    appliance_circuits = list(circuits)
    mains_list = list(mains_circuits)
    daily_entities = _resolved_entities_for_circuits(
        appliance_circuits,
        ("sensor", "daily_energy_usage", "Daily Energy Usage"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    activity_entities = _resolved_entities_for_circuits(
        appliance_circuits,
        ("sensor", "activity_summary", "Activity Summary"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    electrical_rows = _resolved_rows_for_circuits(
        [*appliance_circuits, *mains_list],
        ("sensor", "electrical_health", "Electrical Health"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )

    cards: list[dict[str, Any]] = []
    if daily_entities:
        cards.append(_statistics_graph_card("Daily energy trend", daily_entities))
    if activity_entities:
        cards.append(
            {
                "type": "history-graph",
                "title": "Appliance activity",
                "hours_to_show": 48,
                "entities": [
                    {"entity": entity_id} for entity_id in activity_entities
                ],
            }
        )
    if electrical_rows:
        cards.append(
            {
                "type": "glance",
                "title": "Electrical health rollups",
                "columns": 4,
                "entities": electrical_rows,
            }
        )
    if include_feature_cards and (
        water_flow_card := _water_flow_context_card(
            appliance_circuits,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
    ):
        cards.append(water_flow_card)

    if not cards:
        cards.append(
            _markdown_card(
                "Energy tracking cards appear after analyzer summary entities are "
                "created and available."
            )
        )

    return {
        "type": "grid",
        "title": "Energy Tracking",
        "cards": cards,
    }


def _appliance_run_timeline_section(
    circuits: Iterable[Any],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    activity_entities = _resolved_entities_for_circuits(
        circuits,
        ("sensor", "activity_summary", "Activity Summary"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if activity_entities:
        cards.append(
            {
                "type": "history-graph",
                "title": "Appliance run timeline",
                "hours_to_show": 24,
                "entities": [{"entity": entity_id} for entity_id in activity_entities],
            }
        )
    else:
        cards.append(_markdown_card("Run timeline appears after activity summaries."))
    return {"type": "grid", "title": "Appliance Run Timeline", "cards": cards}


def _nilm_review_section(
    circuit: Any,
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    circuit_id = _circuit_id(circuit)
    rows, _notes = _resolved_entity_rows(
        circuit_id,
        UNKNOWN_LOAD_SIGNAL_ENTITY_SPECS,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if rows:
        cards.append(
            {
                "type": "glance",
                "title": "NILM review",
                "columns": min(len(rows), 3),
                "entities": rows,
            }
        )
    cards.append(
        {
            "type": "button",
            "name": "Review NILM Assignments",
            "icon": "mdi:playlist-check",
            "tap_action": {
                "action": "navigate",
                "navigation_path": (
                    f"{DEFAULT_ALERT_EVIDENCE_PATH}?"
                    f"nilm_workspace=1&circuit_id={circuit_id}"
                ),
            },
        }
    )
    return {"type": "grid", "title": "NILM Review", "cards": cards}


def _hvac_weather_section(
    circuit: Any,
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
    outdoor_temperature_entity: str | None,
) -> dict[str, Any]:
    circuit_id = _circuit_id(circuit)
    weather_rows, weather_notes = _resolved_entity_rows(
        circuit_id,
        HVAC_WEATHER_ENTITY_SPECS,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    weather_context = _resolved_entity_id(
        circuit_id,
        ("sensor", "weather_context", "Outdoor Weather Context"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if weather_notes:
        cards.append(_markdown_card(_note_content("HVAC weather note", weather_notes)))
    temperature_row = _source_entity_row(
        outdoor_temperature_entity,
        "Outdoor Temperature",
        include_name=True,
    )
    if temperature_row is not None:
        weather_rows.append(temperature_row)
    if weather_rows:
        weather_entities = [row["entity"] for row in weather_rows]
        cards.append(
            _conditional_card(
                weather_entities,
                {
                    "type": "statistics-graph",
                    "title": "HVAC daily energy and outdoor temperature",
                    "days_to_show": 7,
                    "period": "day",
                    "stat_types": ["max"],
                    "entities": weather_rows,
                },
            )
        )
    if weather_context:
        cards.append(
            _conditional_card(
                [weather_context],
                {
                    "type": "tile",
                    "entity": weather_context,
                    "name": "Outdoor Weather Context",
                    "vertical": False,
                },
            )
        )
    cards.append(
        _markdown_card(
            "Notifications and repairs: appliance alerts use persistent "
            "notifications with observed evidence. Repairs are reserved for "
            "setup, configuration, missing sensors, stale data, or other "
            "data-quality problems. Demand and capacity findings are "
            "operational evidence from energy measurements, not electrical "
            "safety verification, code compliance, or breaker sizing advice."
        )
    )

    return {
        "type": "grid",
        "title": "HVAC Weather Context",
        "cards": cards,
    }


def _expert_evidence_section(circuits: Iterable[Any]) -> dict[str, Any]:
    return {
        "type": "grid",
        "title": "Diagnostics and Evidence",
        "cards": [
            _markdown_card(
                _expert_evidence_markdown(circuits)
            )
        ],
    }


def _conditional_entities_card(
    circuit_id: str,
    specs: Iterable[tuple[str, str, str]],
    title: str,
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    rows, _notes = _resolved_entity_rows(
        circuit_id,
        specs,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if not rows:
        return None
    return _conditional_card(
        [row["entity"] for row in rows],
        _entities_card(title, rows),
    )


def _water_flow_context_card(
    circuits: Iterable[Any],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    rows = _resolved_rows_for_circuits(
        [
            circuit
            for circuit in circuits
            if _circuit_profile(circuit) in WATER_FLOW_PROFILES
        ],
        ("sensor", "water_flow_correlation", "Water Flow Correlation"),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if not rows:
        return None
    return _conditional_card(
        [row["entity"] for row in rows],
        {
            "type": "glance",
            "title": "Water flow context",
            "columns": 2,
            "entities": rows,
        },
    )


def _statistics_graph_card(title: str, entity_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "type": "statistics-graph",
        "title": title,
        "days_to_show": 7,
        "period": "day",
        "stat_types": ["max"],
        "entities": [{"entity": entity_id} for entity_id in _dedupe(entity_ids)],
    }


def _defined_nilm_appliance_power_graph(
    appliance_power_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any] | None:
    if not appliance_power_rows:
        return None
    return {
        "type": "history-graph",
        "title": "Defined NILM appliance power",
        "hours_to_show": 24,
        "entities": list(appliance_power_rows),
    }


def _nilm_dashboard_graphs_card(
    *,
    circuit_id: str,
    entry_id: str | None,
    appliance_power_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any] | None:
    if not appliance_power_rows:
        return None
    return {
        "type": NILM_DASHBOARD_GRAPHS_CARD,
        "title": "NILM mains power",
        "entry_id": entry_id,
        "circuit_id": circuit_id,
        "detail_path": (
            f"{DEFAULT_ALERT_EVIDENCE_PATH}?nilm_workspace=1"
            f"&circuit_id={quote(circuit_id, safe='')}"
        ),
        "appliance_power_entities": [
            row["entity"] for row in appliance_power_rows if row.get("entity")
        ],
    }


def _conditional_card(
    entity_ids: Iterable[str],
    card: dict[str, Any],
) -> dict[str, Any]:
    conditions: list[dict[str, str]] = []
    for entity_id in _dedupe(entity_ids):
        conditions.extend(
            (
                {"entity": entity_id, "state_not": "unavailable"},
                {"entity": entity_id, "state_not": "unknown"},
            )
        )
    return {
        "type": "conditional",
        "conditions": conditions,
        "card": card,
    }


def _entities_card(title: str, rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    return {
        "type": "entities",
        "title": title,
        "show_header_toggle": False,
        "entities": list(_dedupe_entity_rows(rows)),
    }


def _resolved_entities_for_circuits(
    circuits: Iterable[Any],
    spec: tuple[str, str, str],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> list[str]:
    entity_ids: list[str] = []
    for circuit in circuits:
        entity_id = _resolved_entity_id(
            _circuit_id(circuit),
            spec,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if entity_id:
            entity_ids.append(entity_id)
    return list(_dedupe(entity_ids))


def _resolved_rows_for_circuits(
    circuits: Iterable[Any],
    spec: tuple[str, str, str],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for circuit in circuits:
        entity_id = _resolved_entity_id(
            _circuit_id(circuit),
            spec,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if entity_id:
            rows.append({"entity": entity_id, "name": _circuit_name(circuit)})
    return list(_dedupe_entity_rows(rows))


def _resolved_entity_id(
    circuit_id: str,
    spec: tuple[str, str, str],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> str | None:
    rows, _notes = _resolved_entity_rows(
        circuit_id,
        (spec,),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
        include_names=False,
    )
    if not rows:
        return None
    return rows[0]["entity"]


def _published_nilm_power_rows(
    registry_lookup: Mapping[str, Any] | None,
    entry_id: str | None,
) -> list[dict[str, str]]:
    if not registry_lookup or not entry_id:
        return []

    prefix = f"{entry_id}_nilm_"
    suffix = f"_{NILM_ESTIMATED_POWER_KEY}"
    rows: list[dict[str, str]] = []
    for entry in registry_lookup.values():
        unique_id = str(_entry_value(entry, "unique_id") or "").strip()
        if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
            continue
        if _entry_value(entry, "disabled_by"):
            continue
        entity_id = str(_entry_value(entry, "entity_id") or "").strip()
        if not entity_id.startswith("sensor."):
            continue
        assignment_id = unique_id[len(prefix) : -len(suffix)]
        rows.append(
            {
                "entity": entity_id,
                "name": _nilm_power_graph_label(entry, assignment_id),
            }
        )

    return list(_dedupe_entity_rows(sorted(rows, key=lambda row: row["entity"])))


def _resolved_setup_health_entity_id(
    *,
    registry_lookup: Mapping[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> str | None:
    if not entry_id or registry_lookup is None:
        return "sensor.circuitsetup_energy_analyzer_setup_health"

    entry = registry_lookup.get(f"{entry_id}_setup_health")
    if entry is None:
        matches = [
            value
            for value in registry_lookup.values()
            if _entry_value(value, "entity_key", "key") == "setup_health"
            or str(_entry_value(value, "unique_id") or "").endswith("_setup_health")
        ]
        entry = matches[0] if len(matches) == 1 else None
    if entry is None or _entry_value(entry, "disabled_by"):
        return None
    entity_id = str(_entry_value(entry, "entity_id") or "").strip()
    if not entity_id.startswith("sensor.") or _entity_is_unavailable(hass, entity_id):
        return None
    return entity_id


def _nilm_power_graph_label(entry: Any, assignment_id: str) -> str:
    raw_label = (
        _entry_value(entry, "name")
        or _entry_value(entry, "original_name")
        or assignment_id
    )
    label = str(raw_label or "").replace("_", " ").replace("-", " ").strip()
    suffix = " estimated power"
    if label.lower().endswith(suffix):
        label = label[: -len(suffix)].strip()
    return label or assignment_id.replace("_", " ").title()


def _resolved_entity_rows(
    circuit_id: str,
    specs: Iterable[tuple[str, str, str]],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
    include_names: bool = True,
) -> tuple[list[dict[str, str]], list[str]]:
    if not entry_id or registry_lookup is None:
        return [
            _entity_row(
                _guessed_entity_id(circuit_id, entity_domain, entity_key),
                label,
                include_name=include_names,
            )
            for entity_domain, entity_key, label in specs
        ], []

    rows: list[dict[str, str]] = []
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
        if not entity_id or not entity_id.startswith(f"{entity_domain}."):
            missing_labels.append(label)
            continue
        if _entity_is_unavailable(hass, entity_id):
            unavailable_labels.append(label)
            continue
        rows.append(_entity_row(entity_id, label, include_name=include_names))

    notes: list[str] = []
    if disabled_labels:
        notes.append(_dashboard_gap_note("disabled", disabled_labels))
    if missing_labels:
        notes.append(_dashboard_gap_note("missing", missing_labels))
    if unavailable_labels:
        notes.append(_dashboard_gap_note("unavailable", unavailable_labels))
    if ambiguous_labels:
        notes.append(_dashboard_gap_note("ambiguous", ambiguous_labels))
    return list(_dedupe_entity_rows(rows)), notes


def _entity_row(
    entity_id: str,
    name: str,
    *,
    include_name: bool,
) -> dict[str, str]:
    row = {"entity": entity_id}
    if include_name:
        row["name"] = name
    return row


def _source_entity_row(
    entity_id: Any,
    name: str,
    *,
    include_name: bool,
) -> dict[str, str] | None:
    normalized = str(entity_id or "").strip()
    if "." not in normalized:
        return None
    return _entity_row(normalized, name, include_name=include_name)


def _dedupe_entity_rows(
    rows: Iterable[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        entity_id = row.get("entity", "")
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        result.append(row)
    return tuple(result)


def _circuit_id(circuit: Any) -> str:
    return str(_circuit_value(circuit, "circuit_id") or "").strip()


def _circuit_name(circuit: Any) -> str:
    circuit_id = _circuit_id(circuit)
    return str(_circuit_value(circuit, "name") or circuit_id).strip() or circuit_id


def _circuit_profile(circuit: Any) -> str:
    return _normalized_value(_circuit_value(circuit, "appliance_profile"))


def _circuit_mode(circuit: Any) -> str:
    return _normalized_value(_circuit_value(circuit, "mode"))


def _is_mains_circuit(circuit: Any) -> bool:
    return "mains_nilm" in {
        _circuit_profile(circuit),
        _circuit_mode(circuit),
        _circuit_id(circuit),
    }


def _is_hvac_circuit(circuit: Any) -> bool:
    return _circuit_profile(circuit) in HVAC_WEATHER_PROFILES


def _layout_includes_feature_cards(layout: str) -> bool:
    return layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}


def _normalized_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _circuit_value(circuit: Any, key: str) -> Any:
    if isinstance(circuit, Mapping):
        return circuit.get(key)
    return getattr(circuit, key, None)


def _registry_entity_lookup(
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any] | None:
    if hass is None or not entry_id:
        return None
    registry = getattr(hass, "entity_registry", None)
    if registry is None:
        try:
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            registry = None
        else:
            try:
                registry = er.async_get(hass)
            except (AttributeError, TypeError):
                registry = None
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


def _dashboard_contains_card_type(cards: object, card_type: str) -> bool:
    if isinstance(cards, Mapping):
        if cards.get("type") == card_type:
            return True
        return any(
            _dashboard_contains_card_type(value, card_type)
            for value in cards.values()
        )
    if isinstance(cards, list):
        return any(_dashboard_contains_card_type(value, card_type) for value in cards)
    return False


def dashboard_includes_nilm_graph_card(config: object) -> bool:
    """Return whether a dashboard config uses the custom NILM graph card."""
    return _dashboard_contains_card_type(config, NILM_DASHBOARD_GRAPHS_CARD)


def dashboard_graph_module_resource() -> dict[str, str]:
    """Return the Lovelace module resource for the custom dashboard graph card."""
    from .panel import PANEL_MODULE_NAME, PANEL_MODULE_VERSION, STATIC_URL_PATH

    return {
        "type": "module",
        "url": f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v={PANEL_MODULE_VERSION}",
    }


def _guessed_entity_id(circuit_id: str, entity_domain: str, entity_key: str) -> str:
    return f"{entity_domain}.{circuit_id}_{entity_key}"


def _markdown_card(content: str) -> dict[str, str]:
    return {"type": "markdown", "content": content}


def _expert_evidence_markdown(circuits: Iterable[Any]) -> str:
    lines = [
        "**Analyzer evidence links**",
        (
            "Open these views when you want alert evidence, analyzer actions, "
            "and troubleshooting context without adding more diagnostic rows "
            "to every appliance card."
        ),
    ]
    for circuit in circuits:
        circuit_id = _circuit_id(circuit)
        if not circuit_id:
            continue
        lines.append(
            f"- [{_circuit_name(circuit)} evidence]"
            f"({DEFAULT_ALERT_EVIDENCE_PATH}?circuit_id={circuit_id})"
        )
    return "\n".join(lines)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
