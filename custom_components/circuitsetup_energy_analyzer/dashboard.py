from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import (
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUTS,
    DEFAULT_DASHBOARD_LAYOUT,
    DOMAIN,
)
from .localized_text import translation_section, translation_text


def _dashboard_text(*keys: str) -> str:
    return translation_text("dashboard", *keys)


def _section_title(key: str) -> str:
    return _dashboard_text("sections", key)


DASHBOARD_TITLE = _dashboard_text("title")
DASHBOARD_URL_PATH = "circuitsetup-energy-analyzer"
DASHBOARD_ICON = "mdi:home-lightning-bolt-outline"
DASHBOARD_COLUMNS = 4
NILM_DASHBOARD_GRAPHS_CARD = "custom:circuitsetup-energy-analyzer-dashboard-graphs"
HOUSE_FLOW_CARD = "custom:circuitsetup-energy-analyzer-house-flow"
APPLIANCE_GRID_CARD = "custom:circuitsetup-energy-analyzer-appliance-grid"
ENERGY_COST_CARD = "custom:circuitsetup-energy-analyzer-energy-cost"
DASHBOARD_CUSTOM_CARD_TYPES = (
    HOUSE_FLOW_CARD,
    APPLIANCE_GRID_CARD,
    ENERGY_COST_CARD,
    NILM_DASHBOARD_GRAPHS_CARD,
)
NILM_ESTIMATED_POWER_KEY = "estimated_power"

_DASHBOARD_ENTITY_DOMAINS = {
    "activity_summary": "sensor",
    "average_cost_per_day": "sensor",
    "average_kwh_per_day": "sensor",
    "balance_power": "sensor",
    "billing_cycle_usage": "sensor",
    "cost_cycle": "sensor",
    "cost_cycle_forecast": "sensor",
    "cost_today": "sensor",
    "daily_energy_usage": "sensor",
    "electrical_health": "sensor",
    "energy_summary": "sensor",
    "health_summary": "sensor",
    "monitored_coverage": "sensor",
    "monitored_power": "sensor",
    "nilm_signature_count": "sensor",
    "nilm_unknown_loads": "sensor",
    "running": "binary_sensor",
    "solar_flow_status": "sensor",
    "solar_surplus_power": "sensor",
    "utility_comparison_status": "sensor",
    "water_flow_correlation": "sensor",
    "weather_context": "sensor",
}


@dataclass(frozen=True, slots=True)
class DashboardCircuit:
    """Registry-resolved circuit data used by every generated view."""

    circuit_id: str
    name: str
    profile: str
    area: str | None
    is_mains: bool
    is_hvac: bool
    detail_path: str
    power_entities: tuple[str, ...]
    entities: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DashboardContext:
    """One semantic model for the generated dashboard."""

    circuits: tuple[DashboardCircuit, ...]
    appliances: tuple[DashboardCircuit, ...]
    mains: tuple[DashboardCircuit, ...]
    hvac: tuple[DashboardCircuit, ...]
    primary_mains: DashboardCircuit | None
    setup_health_entity: str | None
    registry_lookup: Mapping[str, Any] | None
    entry_id: str | None
    outdoor_temperature_entity: str | None
    layout: str
    has_weather: bool
    has_water: bool

APPLIANCE_STATUS_ENTITY_SPECS = (
    ("sensor", "activity_summary", _dashboard_text("entity_labels", "activity")),
    (
        "sensor",
        "electrical_health",
        _dashboard_text("entity_labels", "electrical_health"),
    ),
    ("sensor", "energy_summary", _dashboard_text("entity_labels", "energy_summary")),
    (
        "sensor",
        "daily_energy_usage",
        _dashboard_text("entity_labels", "daily_energy_usage"),
    ),
)
MAINS_ROLLUP_ENTITY_SPECS = (
    ("sensor", "activity_summary", _dashboard_text("entity_labels", "activity")),
    ("sensor", "electrical_health", _dashboard_text("entity_labels", "electrical")),
    ("sensor", "energy_summary", _dashboard_text("entity_labels", "energy")),
)
MAINS_LOAD_MATCH_ENTITY_SPECS = (
    (
        "sensor",
        "monitored_power",
        _dashboard_text("entity_labels", "known_appliance_load"),
    ),
    (
        "sensor",
        "balance_power",
        _dashboard_text("entity_labels", "unassigned_mains_load"),
    ),
    (
        "sensor",
        "monitored_coverage",
        _dashboard_text("entity_labels", "known_load_share"),
    ),
)
UNKNOWN_LOAD_SIGNAL_ENTITY_SPECS = (
    ("sensor", "nilm_unknown_loads", _dashboard_text("entity_labels", "inventory")),
    ("sensor", "nilm_signature_count", _dashboard_text("entity_labels", "signatures")),
    (
        "sensor",
        "monitored_coverage",
        _dashboard_text("entity_labels", "known_load_share"),
    ),
)
SOLAR_FLOW_ENTITY_SPECS = (
    ("sensor", "solar_flow_status", _dashboard_text("entity_labels", "solar_flow")),
    (
        "sensor",
        "solar_surplus_power",
        _dashboard_text("entity_labels", "solar_surplus"),
    ),
)
UTILITY_COMPARISON_ENTITY_SPECS = (
    (
        "sensor",
        "utility_comparison_status",
        _dashboard_text("entity_labels", "utility_status"),
    ),
)
HVAC_WEATHER_ENTITY_SPECS = (
    (
        "sensor",
        "daily_energy_usage",
        _dashboard_text("entity_labels", "daily_energy_usage"),
    ),
)
TODAYS_COST_ENTITY_SPECS = (
    ("sensor", "cost_cycle", _dashboard_text("entity_labels", "cost_so_far")),
    (
        "sensor",
        "cost_cycle_forecast",
        _dashboard_text("entity_labels", "projected_cost"),
    ),
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
    context = _dashboard_context(
        circuits,
        layout,
        hass=hass,
        entry_id=entry_id,
        outdoor_temperature_entity=outdoor_temperature_entity,
    )
    home_view = _build_home_view(context)
    if context.appliances:
        home_view["sections"][0]["cards"].extend(
            _build_appliances_view(context)["sections"][0]["cards"]
        )
    contextual_cards: list[dict[str, Any]] = []
    if (
        context.layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}
        and (context.has_weather or context.has_water)
    ):
        contextual_cards = _build_insights_view(context)["sections"][0]["cards"]
    contextual_graphs = [
        card for card in contextual_cards if card.get("type") == "history-graph"
    ]
    contextual_insights = [
        card for card in contextual_cards if card.get("type") != "history-graph"
    ]
    views = [home_view]
    if context.appliances or context.primary_mains is not None:
        views.append(
            _build_energy_costs_view(
                context,
                contextual_graphs=contextual_graphs,
            )
        )
    insight_cards: list[dict[str, Any]] = []
    if (
        context.layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}
        and context.mains
    ):
        insight_cards.extend(
            _build_mains_nilm_view(context)["sections"][0]["cards"]
        )
    insight_cards.extend(contextual_insights)
    if context.layout == DASHBOARD_LAYOUT_EXPERT and context.circuits:
        insight_cards.extend(
            _build_diagnostics_view(context)["sections"][0]["cards"]
        )
    if context.layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}:
        billing_rows = _billing_cycle_rows(context)
        if billing_rows:
            insight_cards.append(
                _entities_card(
                    _dashboard_text("cards", "billing_cycle"),
                    billing_rows,
                )
            )
    if insight_cards:
        views.append(
            _dashboard_view(
                title=_dashboard_text("views", "insights"),
                path="insights",
                icon="mdi:lightbulb-on-outline",
                cards=insight_cards,
            )
        )
    for view in views:
        cards = view["sections"][0]["cards"]
        card_columns = (
            6
            if view["path"] == "energy-costs"
            else 12
            // min(
                DASHBOARD_COLUMNS,
                max(1, len(cards)),
            )
        )
        for card in cards:
            card["grid_options"]["columns"] = card_columns
    return {
        "title": DASHBOARD_TITLE,
        "views": views,
    }


def _dashboard_context(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None,
    entry_id: str | None,
    outdoor_temperature_entity: str | None,
) -> DashboardContext:
    registry_lookup = _registry_entity_lookup(hass, entry_id)
    resolved = tuple(
        _dashboard_circuit(
            circuit,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        for circuit in circuits
        if _circuit_id(circuit)
    )
    appliances = tuple(circuit for circuit in resolved if not circuit.is_mains)
    mains = tuple(circuit for circuit in resolved if circuit.is_mains)
    hvac = tuple(circuit for circuit in appliances if circuit.is_hvac)
    outdoor_entity = str(outdoor_temperature_entity or "").strip() or None
    has_registry = registry_lookup is not None
    has_weather = bool(outdoor_entity) or (
        has_registry
        and any(circuit.entities.get("weather_context") for circuit in hvac)
    )
    water_profiles = {_normalized_value(profile) for profile in WATER_FLOW_PROFILES}
    has_water = any(
        circuit.profile in water_profiles
        and (
            circuit.entities.get("water_flow_correlation")
            if has_registry
            else False
        )
        for circuit in appliances
    )
    return DashboardContext(
        circuits=resolved,
        appliances=appliances,
        mains=mains,
        hvac=hvac,
        primary_mains=mains[0] if mains else None,
        setup_health_entity=_resolved_setup_health_entity_id(
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ),
        registry_lookup=registry_lookup,
        entry_id=entry_id,
        outdoor_temperature_entity=outdoor_entity,
        layout=normalize_dashboard_layout(layout),
        has_weather=has_weather,
        has_water=has_water,
    )


def _dashboard_circuit(
    circuit: Any,
    *,
    registry_lookup: Mapping[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> DashboardCircuit:
    circuit_id = _circuit_id(circuit)
    entities = {}
    for entity_key, entity_domain in _DASHBOARD_ENTITY_DOMAINS.items():
        entity_id = _resolved_entity_id(
            circuit_id,
            (entity_domain, entity_key, entity_key),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if entity_id:
            entities[entity_key] = entity_id
    return DashboardCircuit(
        circuit_id=circuit_id,
        name=_circuit_name(circuit),
        profile=_circuit_profile(circuit),
        area=str(_circuit_value(circuit, "area") or "").strip() or None,
        is_mains=_is_mains_circuit(circuit),
        is_hvac=_is_hvac_circuit(circuit),
        detail_path=(
            f"{DEFAULT_ALERT_EVIDENCE_PATH}?"
            f"{urlencode({'circuit_id': circuit_id, 'appliance_detail': '1'})}"
        ),
        power_entities=_source_entities_for_role(
            circuit,
            "real_power",
            hass=hass,
        ),
        entities=entities,
    )


def _source_entities_for_role(
    circuit: Any,
    role: str,
    *,
    hass: Any | None,
) -> tuple[str, ...]:
    sensors = _circuit_value(circuit, "sensors") or ()
    entity_ids = []
    for sensor in sensors:
        sensor_role = _entry_value(sensor, "role")
        if _normalized_value(sensor_role) != role:
            continue
        entity_id = str(_entry_value(sensor, "entity_id") or "").strip()
        if entity_id and not _entity_is_apparent_or_reactive_power(hass, entity_id):
            entity_ids.append(entity_id)
    return _dedupe(entity_ids)


def _build_home_view(context: DashboardContext) -> dict[str, Any]:
    card = {
        "type": HOUSE_FLOW_CARD,
        "title": _dashboard_text("cards", "home_summary"),
        "entry_id": context.entry_id,
        "api_path": f"{DOMAIN}/appliance_insights",
        "setup_health_entity": context.setup_health_entity,
        "setup_health_path": _setup_health_panel_path(context.entry_id),
        "primary_mains": _dashboard_circuit_payload(
            context.primary_mains,
            (
                "daily_energy_usage",
                "cost_today",
                "monitored_power",
                "balance_power",
                "monitored_coverage",
                "nilm_unknown_loads",
                "solar_flow_status",
                "solar_surplus_power",
            ),
        ),
        "appliances": [
            _appliance_card_payload(circuit) for circuit in context.appliances
        ],
        "labels": dict(translation_section("dashboard", "live_cards")),
    }
    return _dashboard_view(
        title=_dashboard_text("views", "home"),
        path="overview",
        icon=DASHBOARD_ICON,
        cards=[card],
    )


def _build_appliances_view(context: DashboardContext) -> dict[str, Any]:
    return _dashboard_view(
        title=_dashboard_text("views", "appliances"),
        path="appliances",
        icon="mdi:devices",
        cards=[
            {
                "type": APPLIANCE_GRID_CARD,
                "title": _dashboard_text("cards", "appliances"),
                "appliances": [
                    _appliance_card_payload(circuit)
                    for circuit in context.appliances
                ],
                "labels": dict(translation_section("dashboard", "live_cards")),
            }
        ],
    )


def _build_energy_costs_view(
    context: DashboardContext,
    *,
    contextual_graphs: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    cards = list(contextual_graphs[:1])
    cards.append(
        {
            "type": ENERGY_COST_CARD,
            "title": _dashboard_text("cards", "energy_and_costs"),
            "entry_id": context.entry_id,
            "api_path": f"{DOMAIN}/appliance_insights",
            "text": dict(translation_section("panel")),
            "primary_mains": _dashboard_circuit_payload(
                context.primary_mains,
                (
                    "daily_energy_usage",
                    "cost_today",
                    "average_kwh_per_day",
                    "average_cost_per_day",
                ),
            ),
            "appliances": [
                _energy_cost_payload(circuit) for circuit in context.appliances
            ],
            "labels": dict(translation_section("dashboard", "live_cards")),
        }
    )
    cards.extend(contextual_graphs[1:])
    appliance_power_rows = _published_nilm_power_rows(
        context.registry_lookup,
        context.entry_id,
    )
    if context.primary_mains is not None and appliance_power_rows:
        cards.append(
            _nilm_dashboard_graphs_card(
                circuit_id=context.primary_mains.circuit_id,
                entry_id=context.entry_id,
                appliance_power_rows=appliance_power_rows,
            )
        )
    return _dashboard_view(
        title=_dashboard_text("views", "energy_costs"),
        path="energy-costs",
        icon="mdi:chart-bar",
        cards=cards,
    )


def _build_mains_nilm_view(context: DashboardContext) -> dict[str, Any]:
    primary = context.primary_mains
    if primary is None:
        raise ValueError("Mains view requires a primary mains circuit")
    cards: list[dict[str, Any]] = [
        {
            "type": HOUSE_FLOW_CARD,
            "mode": "mains",
            "title": _dashboard_text("cards", "mains_and_nilm"),
            "primary_mains": _dashboard_circuit_payload(
                primary,
                (
                    "monitored_power",
                    "balance_power",
                    "monitored_coverage",
                    "nilm_unknown_loads",
                    "nilm_signature_count",
                    "solar_flow_status",
                    "solar_surplus_power",
                    "utility_comparison_status",
                ),
            ),
            "secondary_mains": [
                {
                    "circuit_id": circuit.circuit_id,
                    "name": circuit.name,
                    "power_entities": list(circuit.power_entities),
                }
                for circuit in context.mains[1:]
            ],
            "labels": dict(translation_section("dashboard", "live_cards")),
        }
    ]
    cards.append(
        {
            "type": "button",
            "name": _dashboard_text("cards", "review_nilm_assignments"),
            "icon": "mdi:playlist-check",
            "tap_action": {
                "action": "navigate",
                "navigation_path": (
                    f"{DEFAULT_ALERT_EVIDENCE_PATH}?nilm_workspace=1&"
                    f"circuit_id={quote(primary.circuit_id, safe='')}"
                ),
            },
        }
    )
    return _dashboard_view(
        title=_dashboard_text("views", "mains_nilm"),
        path="mains-nilm",
        icon="mdi:transmission-tower",
        cards=cards,
    )


def _build_insights_view(context: DashboardContext) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    history_rows: list[dict[str, str]] = []
    if context.outdoor_temperature_entity:
        history_rows.append(
            {
                "entity": context.outdoor_temperature_entity,
                "name": _dashboard_text("entity_labels", "outdoor_temperature"),
            }
        )
    weather_rows: list[dict[str, str]] = []
    for circuit in context.hvac:
        for entity_id in circuit.power_entities:
            history_rows.append(
                {"entity": entity_id, "name": f"{circuit.name} power"}
            )
        for key, suffix in (
            ("running", "running"),
            ("daily_energy_usage", "energy today"),
        ):
            if entity_id := circuit.entities.get(key):
                history_rows.append(
                    {"entity": entity_id, "name": f"{circuit.name} {suffix}"}
                )
        if entity_id := circuit.entities.get("weather_context"):
            weather_rows.append({"entity": entity_id, "name": circuit.name})
    if history_rows:
        cards.append(
            {
                "type": "history-graph",
                "title": _dashboard_text("cards", "hvac_weather_correlation"),
                "hours_to_show": 168,
                "entities": list(_dedupe_entity_rows(history_rows)),
            }
        )
    if weather_rows:
        cards.append(
            _entities_card(
                _dashboard_text("cards", "hvac_weather_status"),
                weather_rows,
            )
        )
    water_rows = [
        {"entity": entity_id, "name": circuit.name}
        for circuit in context.appliances
        if (entity_id := circuit.entities.get("water_flow_correlation"))
        and circuit.profile in WATER_FLOW_PROFILES
    ]
    if water_rows:
        cards.append(
            {
                "type": "history-graph",
                "title": _dashboard_text("cards", "water_flow_context"),
                "hours_to_show": 168,
                "entities": water_rows,
            }
        )
    return _dashboard_view(
        title=_dashboard_text("views", "insights"),
        path="insights",
        icon="mdi:lightbulb-on-outline",
        cards=cards,
    )


def _build_diagnostics_view(context: DashboardContext) -> dict[str, Any]:
    return _dashboard_view(
        title=_dashboard_text("views", "diagnostics"),
        path="diagnostics",
        icon="mdi:tools",
        cards=[
            _markdown_card(
                _expert_evidence_markdown(
                    [
                        {
                            "circuit_id": circuit.circuit_id,
                            "name": circuit.name,
                        }
                        for circuit in context.circuits
                    ]
                )
            )
        ],
    )


def _dashboard_view(
    *,
    title: str,
    path: str,
    icon: str,
    cards: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "title": title,
        "path": path,
        "icon": icon,
        "type": "sections",
        "max_columns": DASHBOARD_COLUMNS,
        "dense_section_placement": True,
        "sections": [
            {
                "type": "grid",
                "column_span": DASHBOARD_COLUMNS,
                "cards": [
                    {
                        **card,
                        "grid_options": {
                            **card.get("grid_options", {}),
                            "columns": 12,
                        },
                    }
                    for card in cards
                ],
            }
        ],
    }


def _appliance_card_payload(circuit: DashboardCircuit) -> dict[str, Any]:
    return {
        "circuit_id": circuit.circuit_id,
        "name": circuit.name,
        "profile": circuit.profile,
        "area": circuit.area,
        "detail_path": circuit.detail_path,
        "power_entities": list(circuit.power_entities),
        **_named_entities(
            circuit,
            {
                "running": "running_entity",
                "daily_energy_usage": "energy_today_entity",
                "cost_today": "cost_today_entity",
                "health_summary": "health_entity",
            },
        ),
    }


def _energy_cost_payload(circuit: DashboardCircuit) -> dict[str, Any]:
    return {
        "circuit_id": circuit.circuit_id,
        "name": circuit.name,
        **_named_entities(
            circuit,
            {
                "daily_energy_usage": "energy_today_entity",
                "cost_today": "cost_today_entity",
                "average_kwh_per_day": "average_kwh_entity",
                "average_cost_per_day": "average_cost_entity",
            },
        ),
    }


def _dashboard_circuit_payload(
    circuit: DashboardCircuit | None,
    keys: Sequence[str],
) -> dict[str, Any] | None:
    if circuit is None:
        return None
    return {
        "circuit_id": circuit.circuit_id,
        "name": circuit.name,
        "power_entities": list(circuit.power_entities),
        **_named_entities(circuit, {key: f"{key}_entity" for key in keys}),
    }


def _named_entities(
    circuit: DashboardCircuit,
    names: Mapping[str, str],
) -> dict[str, str]:
    return {
        output_name: entity_id
        for entity_key, output_name in names.items()
        if (entity_id := circuit.entities.get(entity_key))
    }


def _billing_cycle_rows(context: DashboardContext) -> list[dict[str, str]]:
    circuits = (
        (context.primary_mains,)
        if context.primary_mains is not None
        else context.appliances
    )
    rows = []
    for circuit in circuits:
        if circuit is None:
            continue
        for key, label in (
            ("billing_cycle_usage", _dashboard_text("entity_labels", "billing_usage")),
            ("cost_cycle", _dashboard_text("entity_labels", "cost_so_far")),
            ("cost_cycle_forecast", _dashboard_text("entity_labels", "projected_cost")),
        ):
            if entity_id := circuit.entities.get(key):
                rows.append(
                    {
                        "entity": entity_id,
                        "name": f"{circuit.name} {label}",
                    }
                )
    return rows


def _dashboard_cost_status(
    hass: Any | None,
    entry_id: str | None,
    context: DashboardContext,
) -> str:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {}) if hass is not None else {}
    coordinator = (
        domain_data.get(entry_id)
        if entry_id and isinstance(domain_data, Mapping)
        else None
    )
    state = getattr(coordinator, "state", None)
    statuses = getattr(state, "cost_today_status_by_circuit", {}) or {}
    estimates = getattr(state, "estimated_cost_today_by_circuit", {}) or {}
    circuit_ids = {circuit.circuit_id for circuit in context.circuits}
    if any(statuses.get(circuit_id) == "actual" for circuit_id in circuit_ids):
        return "recorded"
    if any(estimates.get(circuit_id) is not None for circuit_id in circuit_ids):
        return "estimated"
    return "unavailable"


def dashboard_preflight_summary(
    circuits: Iterable[Any],
    layout: Any,
    *,
    hass: Any | None = None,
    entry_id: str | None = None,
    outdoor_temperature_entity: str | None = None,
) -> dict[str, Any]:
    """Return the views and data capabilities the generated dashboard will use."""
    circuit_list = tuple(circuits)
    context = _dashboard_context(
        circuit_list,
        layout,
        hass=hass,
        entry_id=entry_id,
        outdoor_temperature_entity=outdoor_temperature_entity,
    )
    dashboard = build_recommended_dashboard(
        circuit_list,
        layout,
        hass=hass,
        entry_id=entry_id,
        outdoor_temperature_entity=outdoor_temperature_entity,
    )
    views = [str(view.get("title") or "") for view in dashboard["views"]]
    paths = [str(view.get("path") or "") for view in dashboard["views"]]
    valid_circuits = [circuit for circuit in circuit_list if _circuit_id(circuit)]
    appliance_circuits = [
        circuit for circuit in valid_circuits if not _is_mains_circuit(circuit)
    ]
    all_views = [
        _dashboard_text("views", "home"),
        _dashboard_text("views", "energy_costs"),
        _dashboard_text("views", "insights"),
    ]
    registry_lookup = _registry_entity_lookup(hass, entry_id)
    missing_source_data, disabled_entities = _dashboard_preflight_entity_gaps(
        appliance_circuits,
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    return {
        "layout": context.layout,
        "views": views,
        "view_paths": paths,
        "capabilities": {
            "house_flow": True,
            "appliance_grid": bool(context.appliances),
            "energy_cost": bool(context.appliances or context.primary_mains),
            "running_timeline": any(
                circuit.entities.get("running") for circuit in context.appliances
            ),
            "mains_nilm": bool(context.mains),
            "weather": context.has_weather,
            "water": context.has_water,
        },
        "costs": _dashboard_cost_status(hass, entry_id, context),
        "missing_power_inputs": [
            circuit.name for circuit in context.circuits if not circuit.power_entities
        ],
        "missing_energy_inputs": [
            circuit.name
            for circuit in context.circuits
            if "daily_energy_usage" not in circuit.entities
        ],
        "missing_cost_inputs": [
            circuit.name
            for circuit in context.circuits
            if "cost_today" not in circuit.entities
        ],
        "missing_weather_inputs": bool(context.hvac) and not context.has_weather,
        "missing_nilm_inputs": not context.mains,
        "will_include": views,
        "will_skip": [view for view in all_views if view and view not in views],
        "missing_source_data": missing_source_data,
        "disabled_entities": disabled_entities,
        "nilm_enabled": bool(context.mains),
        "nilm_sections_enabled": (
            context.layout in {DASHBOARD_LAYOUT_STANDARD, DASHBOARD_LAYOUT_EXPERT}
            and bool(context.mains)
        ),
        "estimated_appliance_count": len(
            _published_nilm_power_rows(registry_lookup, entry_id)
        ),
        "outdoor_temperature_entity": context.outdoor_temperature_entity,
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
        _section_title("household_overview"),
        _section_title("todays_energy"),
        _section_title("energy_tracking"),
        _section_title("appliance_run_timeline"),
    ]
    if appliance_circuits:
        titles.append(_section_title("appliance_status"))
    if mains_circuits:
        titles.append(_section_title("mains_solar_nilm"))
    if include_feature_cards and mains_circuits:
        titles.append(_section_title("nilm_review"))
    if include_feature_cards and hvac_circuits:
        titles.append(_section_title("hvac_weather_context"))
    if include_expert_links:
        titles.append(_section_title("diagnostics_and_evidence"))
    return titles


def _balance_last_section_row(sections: Sequence[dict[str, Any]]) -> None:
    row: list[dict[str, Any]] = []
    used_columns = 0
    for section in sections:
        span = _section_column_span(section)
        if row and used_columns + span > DASHBOARD_COLUMNS:
            row = []
            used_columns = 0
        row.append(section)
        used_columns += span
        if used_columns == DASHBOARD_COLUMNS:
            row = []
            used_columns = 0

    if not row:
        return

    spans = [_section_column_span(section) for section in row]
    center = (len(row) - 1) / 2
    for _ in range(DASHBOARD_COLUMNS - used_columns):
        index = min(
            range(len(row)),
            key=lambda candidate: (
                spans[candidate],
                abs(candidate - center),
                candidate,
            ),
        )
        spans[index] += 1

    for section, span in zip(row, spans, strict=True):
        section["column_span"] = span


def _section_column_span(section: Mapping[str, Any]) -> int:
    try:
        span = int(section.get("column_span", 1))
    except (TypeError, ValueError):
        span = 1
    return max(1, min(DASHBOARD_COLUMNS, span))


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
                "name": _dashboard_text("cards", "setup_health"),
                "vertical": False,
                "grid_options": {"columns": "full", "rows": 1},
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": _setup_health_panel_path(entry_id),
                },
            }
        )

    if mains_list:
        overview_rows, _ = _resolved_entity_rows(
            _circuit_id(mains_list[0]),
            (
                (
                    "sensor",
                    "monitored_power",
                    _dashboard_text("entity_labels", "total_monitored_power"),
                ),
                (
                    "sensor",
                    "monitored_coverage",
                    _dashboard_text("entity_labels", "known_load_coverage"),
                ),
            ),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if include_feature_cards:
            unknown_loads = _resolved_entity_id(
                _circuit_id(mains_list[0]),
                (
                    "sensor",
                    "nilm_unknown_loads",
                    _dashboard_text("entity_labels", "nilm_review_count"),
                ),
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
            if unknown_loads:
                overview_rows.append(
                    {
                        "entity": unknown_loads,
                        "name": _dashboard_text("entity_labels", "nilm_review_count"),
                    }
                )
        if overview_rows:
            cards.append(
                _entities_card(
                    _dashboard_text("cards", "household_energy_overview"),
                    overview_rows,
                )
            )

    activity_rows = _resolved_rows_for_circuits(
        appliance_list[:5],
        ("sensor", "activity_summary", _dashboard_text("entity_labels", "activity")),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if activity_rows:
        cards.append(
            {
                "type": "glance",
                "title": _dashboard_text("cards", "top_appliances_right_now"),
                "columns": _glance_columns(activity_rows),
                "entities": activity_rows,
            }
        )
    if not cards:
        cards.append(
            _markdown_card(_dashboard_text("notes", "household_overview_after_setup"))
        )
    return {
        "type": "grid",
        "title": _section_title("household_overview"),
        "cards": cards,
    }


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
        (
            "sensor",
            "daily_energy_usage",
            _dashboard_text("entity_labels", "daily_energy_usage"),
        ),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if daily_rows:
        cards.append(
            _statistics_graph_card(
                _dashboard_text("cards", "todays_appliance_energy"),
                [row["entity"] for row in daily_rows],
            )
        )
        cards.append(
            {
                "type": "glance",
                "title": _dashboard_text("cards", "top_energy_users_today"),
                "columns": _glance_columns(daily_rows[:5]),
                "entities": daily_rows[:5],
            }
        )
        cost_rows: list[dict[str, str]] = []
        for circuit in circuits:
            rows, _notes = _resolved_entity_rows(
                _circuit_id(circuit),
                TODAYS_COST_ENTITY_SPECS,
                registry_lookup=registry_lookup,
                hass=hass,
                entry_id=entry_id,
            )
            cost_rows.extend(
                {
                    **row,
                    "name": f"{_circuit_name(circuit)} {row.get('name', '')}",
                }
                for row in rows
            )
        if cost_rows:
            cards.append(
                _entities_card(_dashboard_text("cards", "cost_estimate"), cost_rows)
            )
    else:
        cards.append(
            _markdown_card(_dashboard_text("notes", "todays_energy_after_sources"))
        )
    return {"type": "grid", "title": _section_title("todays_energy"), "cards": cards}


def _appliance_status_section(
    circuits: Iterable[Any],
    *,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
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

    return {
        "type": "grid",
        "title": _section_title("appliance_status"),
        "column_span": 2,
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
                "title": _dashboard_text("cards", "mains_rollups"),
                "columns": _glance_columns(rollup_rows),
                "entities": rollup_rows,
            }
        )

    if include_feature_cards:
        coverage_entity = _resolved_entity_id(
            circuit_id,
            (
                "sensor",
                "monitored_coverage",
                _dashboard_text("entity_labels", "known_load_share"),
            ),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if coverage_entity:
            cards.append(
                {
                    "type": "gauge",
                    "entity": coverage_entity,
                    "name": _dashboard_text("entity_labels", "known_load_share"),
                    "min": 0,
                    "max": 100,
                    "severity": {"red": 0, "yellow": 40, "green": 70},
                }
            )
            cards.append(_markdown_card(_dashboard_text("notes", "known_load_share")))

        load_rows, _ = _resolved_entity_rows(
            circuit_id,
            MAINS_LOAD_MATCH_ENTITY_SPECS,
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if load_rows:
            cards.append(
                _entities_card(_dashboard_text("cards", "mains_load_match"), load_rows)
            )

        unknown_inventory = _resolved_entity_id(
            circuit_id,
            (
                "sensor",
                "nilm_unknown_loads",
                _dashboard_text("entity_labels", "unknown_load_inventory"),
            ),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        )
        if unknown_inventory:
            cards.append(
                {
                    "type": "tile",
                    "entity": unknown_inventory,
                    "name": _dashboard_text("entity_labels", "unknown_load_inventory"),
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
                    "title": _dashboard_text("cards", "unknown_load_signals"),
                    "columns": _glance_columns(unknown_rows),
                    "entities": unknown_rows,
                }
            )

        cards.append(
            {
                "type": "button",
                "name": _dashboard_text("cards", "open_nilm_graph_review"),
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
            _dashboard_text("cards", "solar_flow"),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ):
            cards.append(solar_card)
        if utility_card := _conditional_entities_card(
            circuit_id,
            UTILITY_COMPARISON_ENTITY_SPECS,
            _dashboard_text("cards", "utility_comparison"),
            registry_lookup=registry_lookup,
            hass=hass,
            entry_id=entry_id,
        ):
            cards.append(utility_card)

    daily_energy = _resolved_entity_id(
        circuit_id,
        (
            "sensor",
            "daily_energy_usage",
            _dashboard_text("entity_labels", "daily_energy_usage"),
        ),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    if daily_energy:
        cards.append(
            _statistics_graph_card(
                _dashboard_text("cards", "mains_daily_energy"),
                [daily_energy],
            )
        )

    return {
        "type": "grid",
        "title": _section_title("mains_solar_nilm"),
        "cards": cards,
    }


def _energy_tracking_section(
    circuits: Iterable[Any],
    *,
    include_feature_cards: bool,
    registry_lookup: dict[str, Any] | None,
    hass: Any | None,
    entry_id: str | None,
) -> dict[str, Any]:
    appliance_circuits = list(circuits)
    daily_entities = _resolved_entities_for_circuits(
        appliance_circuits,
        (
            "sensor",
            "daily_energy_usage",
            _dashboard_text("entity_labels", "daily_energy_usage"),
        ),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if daily_entities:
        cards.append(
            _statistics_graph_card(
                _dashboard_text("cards", "daily_energy_trend"),
                daily_entities,
            )
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
            _markdown_card(_dashboard_text("notes", "energy_tracking_after_entities"))
        )

    return {
        "type": "grid",
        "title": _section_title("energy_tracking"),
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
        (
            "sensor",
            "activity_summary",
            _dashboard_text("entity_labels", "activity_summary"),
        ),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if activity_entities:
        cards.append(
            {
                "type": "history-graph",
                "title": _dashboard_text("cards", "appliance_run_timeline"),
                "hours_to_show": 24,
                "entities": [{"entity": entity_id} for entity_id in activity_entities],
            }
        )
    else:
        cards.append(
            _markdown_card(_dashboard_text("notes", "run_timeline_after_activity"))
        )
    return {
        "type": "grid",
        "title": _section_title("appliance_run_timeline"),
        "cards": cards,
    }


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
                "title": _dashboard_text("cards", "nilm_review"),
                "columns": _glance_columns(rows),
                "entities": rows,
            }
        )
    cards.append(
        {
            "type": "button",
            "name": _dashboard_text("cards", "review_nilm_assignments"),
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
    return {"type": "grid", "title": _section_title("nilm_review"), "cards": cards}


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
        (
            "sensor",
            "weather_context",
            _dashboard_text("entity_labels", "outdoor_weather_context"),
        ),
        registry_lookup=registry_lookup,
        hass=hass,
        entry_id=entry_id,
    )
    cards: list[dict[str, Any]] = []
    if weather_notes:
        cards.append(
            _markdown_card(
                _note_content(
                    _dashboard_text("notes", "hvac_weather_note"),
                    weather_notes,
                )
            )
        )
    temperature_row = _source_entity_row(
        outdoor_temperature_entity,
        _dashboard_text("entity_labels", "outdoor_temperature"),
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
                    "title": _dashboard_text("cards", "hvac_energy_temperature"),
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
                    "name": _dashboard_text("entity_labels", "outdoor_weather_context"),
                    "vertical": False,
                },
            )
        )
    cards.append(_markdown_card(_dashboard_text("notes", "notifications_and_repairs")))

    return {
        "type": "grid",
        "title": _section_title("hvac_weather_context"),
        "cards": cards,
    }


def _expert_evidence_section(circuits: Iterable[Any]) -> dict[str, Any]:
    return {
        "type": "grid",
        "title": _section_title("diagnostics_and_evidence"),
        "cards": [_markdown_card(_expert_evidence_markdown(circuits))],
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
        (
            "sensor",
            "water_flow_correlation",
            _dashboard_text("entity_labels", "water_flow_correlation"),
        ),
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
            "title": _dashboard_text("cards", "water_flow_context"),
            "columns": _glance_columns(rows),
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
        "title": _dashboard_text("cards", "defined_nilm_appliance_power"),
        "hours_to_show": 24,
        "entities": list(appliance_power_rows),
    }


def _nilm_dashboard_graphs_card(
    *,
    circuit_id: str,
    entry_id: str | None,
    appliance_power_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any] | None:
    return {
        "type": NILM_DASHBOARD_GRAPHS_CARD,
        "title": _dashboard_text("cards", "nilm_mains_power"),
        "text": dict(translation_section("panel")),
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
        "grid_options": {"columns": "full", "rows": "auto"},
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


def _setup_health_panel_path(entry_id: str | None) -> str:
    params = {"setup_health": "1"}
    if entry_id:
        params["entry_id"] = entry_id
    return f"{DEFAULT_ALERT_EVIDENCE_PATH}?{urlencode(params)}"


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


def _entity_is_apparent_or_reactive_power(
    hass: Any | None,
    entity_id: str,
) -> bool:
    states = getattr(hass, "states", None)
    get_state = getattr(states, "get", None)
    if not callable(get_state):
        return False
    state = get_state(entity_id)
    attributes = getattr(state, "attributes", {}) or {}
    unit = str(attributes.get("unit_of_measurement", "")).strip().lower()
    device_class = str(attributes.get("device_class", "")).strip().lower()
    return (
        unit.endswith("va")
        or unit.endswith("var")
        or device_class in {"apparent_power", "reactive_power"}
    )


def _circuit_note(name: str, notes: Iterable[str]) -> str:
    return _note_content(
        _dashboard_text("notes", "circuit_dashboard_note").format(name=name),
        notes,
    )


def _note_content(title: str, notes: Iterable[str]) -> str:
    lines = [f"**{title}**"]
    lines.extend(note for note in notes if note)
    return "\n".join(lines)


def _dashboard_gap_note(reason: str, labels: Iterable[str]) -> str:
    label_text = ", ".join(labels)
    if reason == "ambiguous":
        template = _dashboard_text("gap_notes", "ambiguous")
        return template.format(labels=label_text)
    if reason == "disabled":
        template = _dashboard_text("gap_notes", "disabled")
        return template.format(labels=label_text)
    if reason == "unavailable":
        template = _dashboard_text("gap_notes", "unavailable")
        return template.format(labels=label_text)
    template = _dashboard_text("gap_notes", "missing")
    return template.format(labels=label_text)


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
            _dashboard_contains_card_type(value, card_type) for value in cards.values()
        )
    if isinstance(cards, list):
        return any(_dashboard_contains_card_type(value, card_type) for value in cards)
    return False


def dashboard_includes_nilm_graph_card(config: object) -> bool:
    """Return whether a dashboard config needs the first-party card module."""
    return any(
        _dashboard_contains_card_type(config, card_type)
        for card_type in DASHBOARD_CUSTOM_CARD_TYPES
    )


def dashboard_graph_module_resource() -> dict[str, str]:
    """Return the Lovelace module resource for the custom dashboard graph card."""
    from .panel import PANEL_MODULE_NAME, PANEL_MODULE_VERSION, STATIC_URL_PATH

    return {
        "type": "module",
        "url": f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v={PANEL_MODULE_VERSION}",
    }


def _guessed_entity_id(circuit_id: str, entity_domain: str, entity_key: str) -> str:
    return f"{entity_domain}.{circuit_id}_{entity_key}"


def _glance_columns(rows: Sequence[Any]) -> int:
    return max(1, min(2, len(rows)))


def _markdown_card(content: str) -> dict[str, Any]:
    return {
        "type": "markdown",
        "content": content,
        "grid_options": {"columns": "full", "rows": "auto"},
    }


def _expert_evidence_markdown(circuits: Iterable[Any]) -> str:
    lines = [
        f"**{_dashboard_text('expert', 'heading')}**",
        _dashboard_text("expert", "description"),
    ]
    for circuit in circuits:
        circuit_id = _circuit_id(circuit)
        if not circuit_id:
            continue
        link_label = _dashboard_text("expert", "link_label").format(
            name=_circuit_name(circuit)
        )
        lines.append(
            f"- [{link_label}]({DEFAULT_ALERT_EVIDENCE_PATH}?circuit_id={circuit_id})"
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
