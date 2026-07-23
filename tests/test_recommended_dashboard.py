from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.dashboard import (
    DASHBOARD_CUSTOM_CARD_TYPES,
    DASHBOARD_URL_PATH,
    NILM_DASHBOARD_GRAPHS_CARD,
    build_recommended_dashboard,
    dashboard_graph_module_resource,
    dashboard_preflight_summary,
)
from custom_components.circuitsetup_energy_analyzer.managers import (
    dashboard_controller as dashboard_storage,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


def _without_panel_text(value):
    if isinstance(value, dict):
        return {
            key: _without_panel_text(child)
            for key, child in value.items()
            if key != "text"
        }
    if isinstance(value, list):
        return [_without_panel_text(child) for child in value]
    return value


def _circuits() -> tuple[CircuitConfig, ...]:
    return (
        CircuitConfig(
            circuit_id="fridge",
            name="Refrigerator",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
            ),
        ),
        CircuitConfig(
            circuit_id="mains",
            name="Mains NILM",
            appliance_profile=ApplianceProfile.MAINS_NILM,
            mode=CircuitMode.MAINS_NILM,
            sensors=(),
        ),
    )


def _example_circuits() -> tuple[CircuitConfig, ...]:
    return (
        CircuitConfig(
            circuit_id="fridge",
            name="Refrigerator",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
            ),
        ),
        CircuitConfig(
            circuit_id="hvac",
            name="HVAC",
            appliance_profile=ApplianceProfile.HVAC,
            mode=CircuitMode.DUAL_PHASE,
            sensors=(
                SensorRef("sensor.hvac_power", SensorRole.REAL_POWER),
                SensorRef("sensor.hvac_energy", SensorRole.ENERGY),
            ),
        ),
        CircuitConfig(
            circuit_id="mains",
            name="Mains NILM",
            appliance_profile=ApplianceProfile.MAINS_NILM,
            mode=CircuitMode.MAINS_NILM,
            sensors=(),
        ),
    )


def _circuit_dicts() -> list[dict[str, object]]:
    return _circuit_config_dicts(_circuits())


def _example_circuit_dicts() -> list[dict[str, object]]:
    return _circuit_config_dicts(_example_circuits())


def _circuit_config_dicts(
    circuits: tuple[CircuitConfig, ...],
) -> list[dict[str, object]]:
    return [
        {
            **asdict(circuit),
            "appliance_profile": circuit.appliance_profile.value,
            "mode": circuit.mode.value,
        }
        for circuit in circuits
    ]


def _entity_refs(config: dict[str, object]) -> set[str]:
    refs: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, str):
            if value.startswith(
                ("sensor.", "binary_sensor.", "button.", "select.", "number.")
            ):
                refs.add(value)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return refs


def _dashboard_sections(config: dict[str, object]) -> list[dict[str, object]]:
    views = config.get("views")
    if not isinstance(views, list):
        return []
    sections: list[dict[str, object]] = []
    for view in views:
        if not isinstance(view, dict):
            continue
        view_sections = view.get("sections")
        if isinstance(view_sections, list):
            sections.extend(
                section for section in view_sections if isinstance(section, dict)
            )
    return sections


def _dashboard_views(config: dict[str, object]) -> list[dict[str, object]]:
    views = config.get("views")
    if not isinstance(views, list):
        return []
    return [view for view in views if isinstance(view, dict)]


def _entity_ref_counts_by_view(
    config: dict[str, object],
) -> dict[str, dict[str, int]]:
    counts_by_view: dict[str, dict[str, int]] = {}
    for view in _dashboard_views(config):
        counts: dict[str, int] = {}

        def walk(value: object, target_counts: dict[str, int]) -> None:
            if isinstance(value, str):
                if value.startswith(
                    ("sensor.", "binary_sensor.", "button.", "select.", "number.")
                ):
                    target_counts[value] = target_counts.get(value, 0) + 1
            elif isinstance(value, dict):
                for nested in value.values():
                    walk(nested, target_counts)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested, target_counts)

        walk(view, counts)
        counts_by_view[str(view.get("path") or "")] = counts
    return counts_by_view


def _card_of_type(config: dict[str, object], card_type: str) -> dict[str, object]:
    return next(
        card for card in _dashboard_cards(config) if card.get("type") == card_type
    )


def _dashboard_section(config: dict[str, object], title: str) -> dict[str, object]:
    return next(
        section
        for section in _dashboard_sections(config)
        if section.get("title") == title
    )


def _dashboard_cards(node: object) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            cards.append(node)
        for value in node.values():
            cards.extend(_dashboard_cards(value))
    elif isinstance(node, list):
        for item in node:
            cards.extend(_dashboard_cards(item))
    return cards


def _card_with_title(node: object, title: str) -> dict[str, object]:
    return next(card for card in _dashboard_cards(node) if card.get("title") == title)


def _entity_ref_count(config: dict[str, object], entity_id: str) -> int:
    count = 0

    def walk(value: object) -> None:
        nonlocal count
        if value == entity_id:
            count += 1
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return count


def _markdown_contents(config: dict[str, object]) -> list[str]:
    contents: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "markdown" and isinstance(
                value.get("content"),
                str,
            ):
                contents.append(value["content"])
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return contents


def _registry_entry(
    entity_id: str,
    unique_id: str,
    *,
    disabled_by: str | None = None,
    circuit_id: str | None = None,
    entity_key: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        config_entry_id="entry-1",
        platform="circuitsetup_energy_analyzer",
        disabled_by=disabled_by,
        circuit_id=circuit_id,
        entity_key=entity_key,
    )


def _nilm_power_registry_entry(
    entity_id: str = "sensor.pool_pump_estimated_power",
    *,
    entry_id: str = "entry-1",
    assignment_id: str = "pool_pump",
    original_name: str = "Pool Pump Estimated Power",
    disabled_by: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=f"{entry_id}_nilm_{assignment_id}_estimated_power",
        config_entry_id=entry_id,
        platform="circuitsetup_energy_analyzer",
        disabled_by=disabled_by,
        original_name=original_name,
        name=None,
    )


def _summary_only_registry_entries() -> dict[str, SimpleNamespace]:
    return {
        "sensor.fridge_activity": _registry_entry(
            "sensor.fridge_activity",
            "entry-1_fridge_activity_summary",
        ),
        "sensor.fridge_electrical": _registry_entry(
            "sensor.fridge_electrical",
            "entry-1_fridge_electrical_health",
        ),
        "sensor.fridge_energy": _registry_entry(
            "sensor.fridge_energy",
            "entry-1_fridge_energy_summary",
        ),
        "sensor.fridge_daily": _registry_entry(
            "sensor.fridge_daily",
            "entry-1_fridge_daily_energy_usage",
        ),
        "sensor.mains_activity": _registry_entry(
            "sensor.mains_activity",
            "entry-1_mains_activity_summary",
        ),
        "sensor.mains_electrical": _registry_entry(
            "sensor.mains_electrical",
            "entry-1_mains_electrical_health",
        ),
        "sensor.mains_energy": _registry_entry(
            "sensor.mains_energy",
            "entry-1_mains_energy_summary",
        ),
        "sensor.mains_daily": _registry_entry(
            "sensor.mains_daily",
            "entry-1_mains_daily_energy_usage",
        ),
        "sensor.mains_unknown_inventory": _registry_entry(
            "sensor.mains_unknown_inventory",
            "entry-1_mains_nilm_unknown_loads",
        ),
        "sensor.mains_signatures": _registry_entry(
            "sensor.mains_signatures",
            "entry-1_mains_nilm_signature_count",
        ),
    }


@pytest.mark.parametrize(
    ("layout", "expected_paths"),
    [
        (
            DASHBOARD_LAYOUT_SIMPLE,
            ["overview", "energy-costs"],
        ),
        (
            DASHBOARD_LAYOUT_STANDARD,
            [
                "overview",
                "energy-costs",
                "insights",
            ],
        ),
        (
            DASHBOARD_LAYOUT_EXPERT,
            [
                "overview",
                "energy-costs",
                "insights",
            ],
        ),
    ],
)
def test_dashboard_uses_focused_conditional_views(
    layout: str,
    expected_paths: list[str],
) -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        layout,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )

    assert [view["path"] for view in _dashboard_views(dashboard)] == expected_paths
    assert all(view.get("sections") for view in _dashboard_views(dashboard))


def test_dashboard_groups_related_cards_into_three_views() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )

    cards_by_view = {
        view["path"]: {
            card["type"]
            for card in _dashboard_cards(view)
            if isinstance(card.get("type"), str)
        }
        for view in _dashboard_views(dashboard)
    }
    assert {
        "custom:circuitsetup-energy-analyzer-house-flow",
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    } <= cards_by_view["overview"]
    assert "custom:circuitsetup-energy-analyzer-energy-cost" in (
        cards_by_view["energy-costs"]
    )
    assert {
        "custom:circuitsetup-energy-analyzer-house-flow",
        "custom:circuitsetup-energy-analyzer-dashboard-graphs",
        "history-graph",
        "markdown",
    } <= cards_by_view["insights"]


def test_home_card_receives_every_appliance_for_live_sorting() -> None:
    appliances = tuple(
        CircuitConfig(
            circuit_id=f"appliance_{index}",
            name=f"Appliance {index}",
            appliance_profile=ApplianceProfile.MIXED,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef(
                    f"sensor.appliance_{index}_power",
                    SensorRole.REAL_POWER,
                ),
                SensorRef(
                    f"sensor.appliance_{index}_energy",
                    SensorRole.ENERGY,
                ),
            ),
        )
        for index in range(12)
    )
    dashboard = build_recommended_dashboard(
        (*appliances, _circuits()[1]),
        DASHBOARD_LAYOUT_STANDARD,
    )

    home = _dashboard_views(dashboard)[0]
    home_card = _card_of_type(
        home,
        "custom:circuitsetup-energy-analyzer-house-flow",
    )
    assert len(home_card["appliances"]) == 12
    assert all(
        appliance["circuit_id"] != "mains" for appliance in home_card["appliances"]
    )


def test_dashboard_separates_daily_and_billing_cost_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    energy_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    energy_card = _card_of_type(
        energy_view,
        "custom:circuitsetup-energy-analyzer-energy-cost",
    )

    assert {
        appliance["cost_today_entity"]
        for appliance in energy_card["appliances"]
    } == {"sensor.fridge_cost_today", "sensor.hvac_cost_today"}
    assert {
        appliance["average_cost_entity"]
        for appliance in energy_card["appliances"]
    } == {
        "sensor.fridge_average_cost_per_day",
        "sensor.hvac_average_cost_per_day",
    }
    assert {
        appliance["average_kwh_entity"]
        for appliance in energy_card["appliances"]
    } == {
        "sensor.fridge_average_kwh_per_day",
        "sensor.hvac_average_kwh_per_day",
    }
    billing_card = _card_with_title(energy_view, "Billing Cycle")
    billing_entities = {
        row["entity"] for row in billing_card["entities"] if isinstance(row, dict)
    }
    assert "sensor.mains_cost_cycle" in billing_entities
    assert "sensor.mains_cost_cycle_forecast" in billing_entities
    assert all("cost_today" not in entity_id for entity_id in billing_entities)


def test_appliance_timeline_uses_binary_running_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    appliance_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    appliance_card = _card_of_type(
        appliance_view,
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    )

    assert {
        appliance["running_entity"]
        for appliance in appliance_card["appliances"]
    } == {"binary_sensor.fridge_running", "binary_sensor.hvac_running"}
    assert all(
        "activity_summary" not in str(appliance)
        for appliance in appliance_card["appliances"]
    )


def test_insights_include_every_hvac_circuit() -> None:
    second_hvac = CircuitConfig(
        circuit_id="heat_pump",
        name="Heat pump",
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.heat_pump_power", SensorRole.REAL_POWER),),
    )
    dashboard = build_recommended_dashboard(
        (*_example_circuits(), second_hvac),
        DASHBOARD_LAYOUT_STANDARD,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    refs = _entity_refs(insights)

    assert "binary_sensor.hvac_running" in refs
    assert "binary_sensor.heat_pump_running" in refs
    assert "sensor.outdoor_temperature" in refs


def test_mains_view_identifies_primary_and_additional_mains_channels() -> None:
    second_mains = CircuitConfig(
        circuit_id="garage_mains",
        name="Garage subpanel",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.garage_mains_power", SensorRole.REAL_POWER),
        ),
    )
    dashboard = build_recommended_dashboard(
        (*_example_circuits(), second_mains),
        DASHBOARD_LAYOUT_STANDARD,
    )
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    flow_card = _card_of_type(
        mains_view,
        "custom:circuitsetup-energy-analyzer-house-flow",
    )

    assert flow_card["primary_mains"]["circuit_id"] == "mains"
    assert flow_card["secondary_mains"] == [
        {
            "circuit_id": "garage_mains",
            "name": "Garage subpanel",
            "power_entities": ["sensor.garage_mains_power"],
        }
    ]


@pytest.mark.parametrize("appliance_count", [0, 1, 10, 25])
def test_dashboard_omits_empty_views_and_cards(appliance_count: int) -> None:
    appliances = tuple(
        CircuitConfig(
            circuit_id=f"load_{index}",
            name=f"Load {index}",
            appliance_profile=ApplianceProfile.MIXED,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef(f"sensor.load_{index}_power", SensorRole.REAL_POWER),
            ),
        )
        for index in range(appliance_count)
    )
    dashboard = build_recommended_dashboard(
        appliances,
        DASHBOARD_LAYOUT_STANDARD,
    )

    for view in _dashboard_views(dashboard):
        assert view["sections"]
        for section in view["sections"]:
            assert section["cards"]
            assert all(card for card in section["cards"])


def test_dashboard_preflight_reports_views_and_visual_capabilities() -> None:
    preflight = dashboard_preflight_summary(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )

    assert preflight["views"] == [
        "Home",
        "Energy & Costs",
        "Insights",
    ]
    assert preflight["capabilities"] == {
        "house_flow": True,
        "appliance_grid": True,
        "energy_cost": True,
        "running_timeline": True,
        "mains_nilm": True,
        "weather": True,
        "water": False,
    }
    assert preflight["costs"] in {"recorded", "estimated", "unavailable"}


def test_generated_dashboard_uses_dashboard_example_sections() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert [view["path"] for view in _dashboard_views(dashboard)] == [
        "overview",
        "energy-costs",
        "insights",
    ]
    assert dashboard["views"][0]["type"] == "sections"
    assert dashboard["views"][0]["title"] == "Home"
    assert dashboard["views"][0]["path"] == "overview"
    assert dashboard["views"][0]["max_columns"] == 4
    assert dashboard["views"][0]["dense_section_placement"] is True


def test_generated_dashboard_matches_glance_columns_to_visible_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert not [
        card
        for card in _dashboard_cards(dashboard)
        if card.get("type") == "glance"
    ]


@pytest.mark.parametrize(
    ("layout", "circuits"),
    (
        (DASHBOARD_LAYOUT_SIMPLE, _example_circuits()),
        (DASHBOARD_LAYOUT_STANDARD, _circuits()),
        (DASHBOARD_LAYOUT_EXPERT, _example_circuits()[:1]),
        (DASHBOARD_LAYOUT_EXPERT, _example_circuits()[:2]),
        (DASHBOARD_LAYOUT_EXPERT, _example_circuits()),
    ),
)
def test_generated_dashboard_balances_last_four_column_row(
    layout: str,
    circuits: tuple[CircuitConfig, ...],
) -> None:
    dashboard = build_recommended_dashboard(
        circuits,
        layout,
    )
    used_columns = 0
    for section in _dashboard_sections(dashboard):
        span = int(section.get("column_span", 1))
        if used_columns + span > 4:
            assert used_columns == 4
            used_columns = 0
        used_columns += span
        if used_columns == 4:
            used_columns = 0

    assert used_columns == 0


def test_generated_dashboard_omits_duplicate_appliance_summary_cards() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert "Behavior Watchlist" not in {
        section.get("title") for section in _dashboard_sections(dashboard)
    }
    assert {
        "Usage watchlist",
        "Electrical watchlist",
        "Appliance activity",
        "Electrical health rollups",
    }.isdisjoint(
        {
            str(card.get("title") or card.get("name") or "")
            for card in _dashboard_cards(dashboard)
        }
    )


def test_dashboard_visual_story_sections_use_existing_summary_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    refs = _entity_refs(dashboard)

    assert {view["path"] for view in _dashboard_views(dashboard)} >= {
        "overview",
        "energy-costs",
        "insights",
    }
    assert "sensor.fridge_daily_energy_usage" in refs
    assert "sensor.fridge_cost_today" in refs
    assert "sensor.fridge_average_cost_per_day" in refs
    assert "sensor.fridge_health_summary" in refs
    assert "binary_sensor.fridge_running" in refs
    assert "sensor.mains_nilm_unknown_loads" in refs
    assert "sensor.mains_cost_cycle" in refs
    assert "sensor.mains_cost_cycle_forecast" in refs
    assert "sensor.fridge_activity_summary" not in refs
    assert "select.fridge_alert_sensitivity" not in refs
    assert "button.fridge_relearn_baseline" not in refs

    energy_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    assert _card_with_title(energy_view, "Billing Cycle")["entities"] == [
        {
            "entity": "sensor.mains_billing_cycle_usage",
            "name": "Mains NILM Billing cycle usage",
        },
        {"entity": "sensor.mains_cost_cycle", "name": "Mains NILM Cost so far"},
        {
            "entity": "sensor.mains_cost_cycle_forecast",
            "name": "Mains NILM Projected cost",
        },
    ]


def test_dashboard_setup_health_tile_opens_guided_panel_view() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        entry_id="entry-1",
    )
    home = _card_of_type(
        dashboard,
        "custom:circuitsetup-energy-analyzer-house-flow",
    )

    assert home["setup_health_entity"] == (
        "sensor.circuitsetup_energy_analyzer_setup_health"
    )
    assert home["setup_health_path"] == (
        "/circuitsetup-energy-analyzer-evidence?setup_health=1&entry_id=entry-1"
    )


def test_dashboard_long_form_cards_use_readable_section_widths() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert all(
        section["column_span"] == 4 for section in _dashboard_sections(dashboard)
    )
    assert all(
        card["grid_options"]["columns"] == 12
        for section in _dashboard_sections(dashboard)
        for card in section["cards"]
    )
    assert _card_of_type(
        dashboard,
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    )


def test_dashboard_balancing_accounts_for_wide_appliance_status_section() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert {
        section.get("column_span", 1)
        for section in _dashboard_sections(dashboard)
    } == {4}


def test_dashboard_omits_empty_appliance_status_for_mains_only() -> None:
    mains = next(
        circuit
        for circuit in _example_circuits()
        if circuit.appliance_profile == ApplianceProfile.MAINS_NILM
    )

    dashboard = build_recommended_dashboard(
        (mains,),
        DASHBOARD_LAYOUT_STANDARD,
    )
    preflight = dashboard_preflight_summary(
        (mains,),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert not [
        card
        for card in _dashboard_cards(dashboard)
        if card.get("type")
        == "custom:circuitsetup-energy-analyzer-appliance-grid"
    ]
    assert preflight["will_include"] == ["Home", "Energy & Costs", "Insights"]


def test_dashboard_nilm_review_section_only_appears_when_mains_nilm_exists() -> None:
    dashboard = build_recommended_dashboard(
        (_config for _config in _example_circuits() if _config.circuit_id != "mains"),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert "mains-nilm" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }


def test_dashboard_preflight_summarizes_included_and_skipped_sections() -> None:
    preflight = dashboard_preflight_summary(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert preflight["layout"] == DASHBOARD_LAYOUT_STANDARD
    assert preflight["will_include"] == [
        "Home",
        "Energy & Costs",
        "Insights",
    ]
    assert preflight["nilm_enabled"] is True
    assert preflight["estimated_appliance_count"] == 0


def test_dashboard_preflight_reports_missing_and_disabled_entities() -> None:
    hass = SimpleNamespace(
        entity_registry=SimpleNamespace(
            entities={
                "sensor.fridge_activity": _registry_entry(
                    "sensor.fridge_activity",
                    "entry-1_fridge_activity_summary",
                ),
                "sensor.fridge_electrical": _registry_entry(
                    "sensor.fridge_electrical",
                    "entry-1_fridge_electrical_health",
                    disabled_by="integration",
                ),
            }
        )
    )

    preflight = dashboard_preflight_summary(
        (next(iter(_example_circuits())),),
        DASHBOARD_LAYOUT_STANDARD,
        hass=hass,
        entry_id="entry-1",
    )

    assert "Refrigerator: Electrical Health" in preflight["disabled_entities"]
    assert "Refrigerator: Energy Summary" in preflight["missing_source_data"]
    assert "Refrigerator: Daily Energy Usage" in preflight["missing_source_data"]


def test_appliance_status_cards_match_dashboard_example_summary_fields() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    appliance_card = _card_of_type(
        dashboard,
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    )
    refrigerator = next(
        appliance
        for appliance in appliance_card["appliances"]
        if appliance["circuit_id"] == "fridge"
    )

    assert refrigerator["health_entity"] == "sensor.fridge_health_summary"
    assert refrigerator["running_entity"] == "binary_sensor.fridge_running"
    assert refrigerator["energy_today_entity"] == (
        "sensor.fridge_daily_energy_usage"
    )
    appliance_text = str(appliance_card)
    assert "sensor.fridge_activity_summary" not in appliance_text
    assert "sensor.fridge_electrical_health" not in appliance_text
    assert "sensor.fridge_energy_usage_status" not in appliance_text
    assert "sensor.fridge_alert_evidence" not in appliance_text


def test_dashboard_omits_appliance_detail_buttons_in_favor_of_evidence_links() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
    )
    buttons = [
        card for card in _dashboard_cards(dashboard) if card.get("type") == "button"
    ]

    assert not [card for card in buttons if "Detail" in str(card.get("name", ""))]
    assert "appliance_detail=1" in str(dashboard)
    assert "Analyzer evidence links" in str(dashboard)
    assert "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge" in str(dashboard)
    assert "Open Refrigerator Evidence" not in str(dashboard)


def test_generated_dashboard_omits_dropdown_and_switch_controls() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
    )
    refs = _entity_refs(dashboard)
    dashboard_without_panel_text = _without_panel_text(dashboard)

    assert not {
        entity_id for entity_id in refs if entity_id.startswith(("select.", "switch."))
    }
    assert "Dashboard Controls" not in str(dashboard_without_panel_text)
    assert "Controls" not in str(dashboard_without_panel_text)


def test_dashboard_uses_nilm_signature_count_key_for_signature_card() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.mains_signatures": _registry_entry(
                        "sensor.mains_signatures",
                        "entry-1_mains_nilm_signature_count",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert "sensor.mains_signatures" in refs
    assert "sensor.mains_nilm_discovered_signatures" not in refs


def test_standard_dashboard_links_mains_nilm_graph_review() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )

    review_card = next(
        card
        for card in _dashboard_cards(mains_view)
        if card.get("name") == "Review NILM Assignments"
    )

    assert review_card["type"] == "button"
    assert review_card["tap_action"] == {
        "action": "navigate",
        "navigation_path": (
            "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        ),
    }


def test_dashboard_adds_nilm_graph_card_without_defined_appliances() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )

    cards = _dashboard_cards(
        next(
            view
            for view in _dashboard_views(dashboard)
            if view["path"] == "insights"
        )
    )

    assert [
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    ]
    assert "resources" not in dashboard


def test_expert_dashboard_adds_nilm_review_card_without_defined_appliances() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_EXPERT,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    cards = _dashboard_cards(mains_view)

    custom_graph = next(
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    )

    custom_graph_without_text = dict(custom_graph)
    text = custom_graph_without_text.pop("text")
    assert text["headers"]["nilm_workspace"] == "NILM Workspace"
    assert custom_graph_without_text == {
        "type": "custom:circuitsetup-energy-analyzer-dashboard-graphs",
        "title": "NILM mains power",
        "entry_id": "entry-1",
        "circuit_id": "mains",
        "detail_path": (
            "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        ),
        "appliance_power_entities": [],
        "grid_options": {"columns": 12},
    }
    assert not [
        card for card in cards if card.get("title") == "Defined NILM appliance power"
    ]
    assert "resources" not in dashboard


def test_standard_dashboard_adds_nilm_graph_card_for_defined_appliances() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.pool_pump_estimated_power": _nilm_power_registry_entry()
                }
            )
        ),
        entry_id="entry-1",
    )
    cards = _dashboard_cards(
        next(
            view
            for view in _dashboard_views(dashboard)
            if view["path"] == "insights"
        )
    )

    custom_graph = next(
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    )
    assert custom_graph["appliance_power_entities"] == [
        "sensor.pool_pump_estimated_power"
    ]
    assert "resources" not in dashboard


def test_expert_dashboard_adds_nilm_graph_cards_for_defined_appliances() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_EXPERT,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.pool_pump_estimated_power": _nilm_power_registry_entry()
                }
            )
        ),
        entry_id="entry-1",
    )
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    cards = _dashboard_cards(mains_view)

    custom_graph = next(
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    )
    custom_graph_without_text = dict(custom_graph)
    text = custom_graph_without_text.pop("text")
    assert text["dashboard_graphs"]["title"] == "NILM mains power"
    assert custom_graph_without_text == {
        "type": "custom:circuitsetup-energy-analyzer-dashboard-graphs",
        "title": "NILM mains power",
        "entry_id": "entry-1",
        "circuit_id": "mains",
        "detail_path": (
            "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        ),
        "appliance_power_entities": ["sensor.pool_pump_estimated_power"],
        "grid_options": {"columns": 12},
    }
    assert not [
        card for card in cards if card.get("title") == "Defined NILM appliance power"
    ]
    assert "resources" not in dashboard


def test_standard_dashboard_uses_detail_navigation_without_control_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    appliance_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    refs = _entity_refs(appliance_view)

    assert "Open Refrigerator Detail" not in str(appliance_view)
    assert "appliance_detail=1" in str(appliance_view)
    assert "sensor.fridge_alert_evidence" not in refs
    assert not {
        entity_id
        for entity_id in refs
        if entity_id.startswith(("button.", "select.", "switch."))
    }
    assert "Controls" not in str(appliance_view)


def test_dashboard_adds_hvac_weather_section_for_hvac_compressor() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="compressor",
                name="A/C Compressor",
                appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
                mode=CircuitMode.DUAL_PHASE,
                sensors=(
                    SensorRef("sensor.compressor_power", SensorRole.REAL_POWER),
                    SensorRef("sensor.compressor_energy", SensorRole.ENERGY),
                ),
            ),
        ),
        DASHBOARD_LAYOUT_STANDARD,
        outdoor_temperature_entity="sensor.backyard_temperature",
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    refs = _entity_refs(insights)
    dashboard_refs = _entity_refs(dashboard)

    assert "binary_sensor.compressor_running" in dashboard_refs
    assert "sensor.compressor_weather_context" in refs
    assert "sensor.backyard_temperature" in refs
    assert "sensor.compressor_outdoor_temperature" not in refs
    assert "sensor.compressor_run_cycle_runtime" not in refs
    assert "sensor.compressor_run_cycle_duty_cycle" not in refs


def test_dashboard_omits_hvac_outdoor_temperature_mirror_without_source_entity() -> (
    None
):
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="compressor",
                name="A/C Compressor",
                appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
                mode=CircuitMode.DUAL_PHASE,
                sensors=(
                    SensorRef("sensor.compressor_power", SensorRole.REAL_POWER),
                    SensorRef("sensor.compressor_energy", SensorRole.ENERGY),
                ),
            ),
        ),
        DASHBOARD_LAYOUT_STANDARD,
    )
    refs = _entity_refs(dashboard)

    assert "sensor.compressor_weather_context" not in refs
    assert "sensor.compressor_outdoor_temperature" not in refs
    assert "insights" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }


def test_dashboard_layout_uses_example_summary_and_shared_tracking_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_SIMPLE)
    refs = _entity_refs(dashboard)

    assert dashboard["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard["views"][0]["path"] == "overview"
    assert {
        "sensor.fridge_health_summary",
        "sensor.fridge_daily_energy_usage",
        "sensor.fridge_cost_today",
        "binary_sensor.fridge_running",
    } <= refs
    assert "mains-nilm" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }
    assert "sensor.fridge_activity_summary" not in refs
    assert "sensor.fridge_metric_consistency_status" not in refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_standard_dashboard_layout_keeps_appliance_cards_compact() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)
    refs = _entity_refs(dashboard)

    assert "sensor.fridge_health_summary" in refs
    assert "binary_sensor.fridge_running" in refs
    assert "sensor.mains_nilm_unknown_loads" in refs
    assert "sensor.fridge_metric_consistency_status" not in refs
    assert "sensor.fridge_energy_usage_status" not in refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_simple_dashboard_layout_omits_feature_level_mains_gap_notes() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(entities=_summary_only_registry_entries())
        ),
        entry_id="entry-1",
    )
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "Mains rollups note" not in markdown
    assert "Mains load match note" not in markdown
    assert "Unknown load signals note" not in markdown


def test_standard_dashboard_layout_omits_missing_mains_gap_notes() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    markdown = "\n".join(_markdown_contents(mains_view))

    assert "Mains rollups note" not in markdown
    assert "Mains load match note" not in markdown
    assert "Unknown load signals note" not in markdown
    assert "Missing entities:" not in markdown
    assert "how much of current mains power is explained" not in markdown


def test_expert_dashboard_layout_adds_evidence_links_without_duplication() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_EXPERT)
    refs = _entity_refs(dashboard)
    markdown = str(dashboard)

    assert "sensor.fridge_health_summary" in refs
    assert "binary_sensor.fridge_running" in refs
    assert "sensor.fridge_alert_evidence" not in refs
    assert "sensor.fridge_power_quality_evidence" not in refs
    assert "sensor.fridge_energy_dashboard_status" not in refs
    assert "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge" in markdown
    assert (
        "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        in markdown
    )


def test_dashboard_uses_entity_registry_ids_for_renamed_entities() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_health": _registry_entry(
                        "sensor.kitchen_fridge_health",
                        "entry-1_fridge_health_summary",
                    ),
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_fridge_activity_summary",
                    ),
                    "sensor.kitchen_fridge_electrical": _registry_entry(
                        "sensor.kitchen_fridge_electrical",
                        "entry-1_fridge_electrical_health",
                    ),
                    "sensor.kitchen_fridge_energy": _registry_entry(
                        "sensor.kitchen_fridge_energy",
                        "entry-1_fridge_energy_summary",
                    ),
                    "sensor.kitchen_fridge_daily_kwh": _registry_entry(
                        "sensor.kitchen_fridge_daily_kwh",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                    "binary_sensor.kitchen_fridge_running_now": _registry_entry(
                        "binary_sensor.kitchen_fridge_running_now",
                        "entry-1_fridge_running",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.kitchen_fridge_health",
        "sensor.kitchen_fridge_daily_kwh",
        "binary_sensor.kitchen_fridge_running_now",
    } <= refs
    assert "sensor.fridge_health_summary" not in refs
    assert "sensor.fridge_activity_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs


def test_dashboard_uses_registry_metadata_when_unique_id_scheme_changes() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.renamed_activity": _registry_entry(
                        "sensor.renamed_activity",
                        "future-scheme-2",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                    "sensor.renamed_daily": _registry_entry(
                        "sensor.renamed_daily",
                        "future-scheme-3",
                        circuit_id="fridge",
                        entity_key="daily_energy_usage",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.renamed_activity",
        "sensor.renamed_daily",
    } <= refs
    assert "sensor.fridge_health_summary" not in refs
    assert "sensor.fridge_activity_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs


def test_dashboard_omits_ambiguous_metadata_matches_without_guessing() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.first_activity": _registry_entry(
                        "sensor.first_activity",
                        "future-scheme-1",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                    "sensor.second_activity": _registry_entry(
                        "sensor.second_activity",
                        "future-scheme-2",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    assert "sensor.first_activity" not in refs
    assert "sensor.second_activity" not in refs
    assert "sensor.fridge_health_summary" not in refs


def test_dashboard_does_not_suffix_match_nested_circuit_unique_ids() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="fridge",
                name="Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
            CircuitConfig(
                circuit_id="kitchen_fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
        ),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_kitchen_fridge_health_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    appliance_card = _card_of_type(
        dashboard,
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    )
    kitchen_fridge = next(
        appliance
        for appliance in appliance_card["appliances"]
        if appliance["circuit_id"] == "kitchen_fridge"
    )
    fridge = next(
        appliance
        for appliance in appliance_card["appliances"]
        if appliance["circuit_id"] == "fridge"
    )

    assert kitchen_fridge["health_entity"] == "sensor.kitchen_fridge_activity"
    assert "health_entity" not in fridge


def test_dashboard_omits_missing_and_disabled_entities() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_energy": _registry_entry(
                        "sensor.kitchen_fridge_energy",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_fridge_health_summary",
                        disabled_by="integration",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    assert "sensor.kitchen_fridge_energy" in refs
    assert "sensor.kitchen_fridge_activity" not in refs


def test_dashboard_does_not_guess_ids_when_registry_is_available_but_empty() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs


def test_dashboard_uses_registry_ids_and_ignores_controls() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.fridge_activity": _registry_entry(
                        "sensor.fridge_activity",
                        "entry-1_fridge_health_summary",
                    ),
                    "sensor.fridge_electrical": _registry_entry(
                        "sensor.fridge_electrical",
                        "entry-1_fridge_cost_today",
                    ),
                    "sensor.fridge_energy": _registry_entry(
                        "sensor.fridge_energy",
                        "entry-1_fridge_average_kwh_per_day",
                    ),
                    "sensor.fridge_daily": _registry_entry(
                        "sensor.fridge_daily",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                    "select.fridge_sensitivity": _registry_entry(
                        "select.fridge_sensitivity",
                        "entry-1_fridge_alert_sensitivity",
                    ),
                    "number.fridge_kwh_goal": _registry_entry(
                        "number.fridge_kwh_goal",
                        "entry-1_fridge_daily_energy_goal",
                    ),
                    "button.fridge_relearn": _registry_entry(
                        "button.fridge_relearn",
                        "entry-1_fridge_relearn_baseline",
                    ),
                    "button.fridge_start_maintenance": _registry_entry(
                        "button.fridge_start_maintenance",
                        "entry-1_fridge_start_maintenance",
                    ),
                    "button.fridge_end_maintenance": _registry_entry(
                        "button.fridge_end_maintenance",
                        "entry-1_fridge_end_maintenance",
                    ),
                    "button.fridge_pause_alerts": _registry_entry(
                        "button.fridge_pause_alerts",
                        "entry-1_fridge_pause_alerts",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.fridge_activity",
        "sensor.fridge_electrical",
        "sensor.fridge_energy",
        "sensor.fridge_daily",
    } <= refs
    assert not {
        entity_id
        for entity_id in refs
        if entity_id.startswith(("select.", "switch.", "number.", "button."))
    }


def test_dashboard_omits_control_entities_for_mains_only_dashboard() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="mains",
                name="Mains NILM",
                appliance_profile=ApplianceProfile.MAINS_NILM,
                mode=CircuitMode.MAINS_NILM,
                sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
            ),
        ),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "select.mains_sensitivity": _registry_entry(
                        "select.mains_sensitivity",
                        "entry-1_mains_alert_sensitivity",
                    ),
                    "number.mains_kwh_goal": _registry_entry(
                        "number.mains_kwh_goal",
                        "entry-1_mains_daily_energy_goal",
                    ),
                    "button.mains_relearn": _registry_entry(
                        "button.mains_relearn",
                        "entry-1_mains_relearn_baseline",
                    ),
                    "button.mains_start_maintenance": _registry_entry(
                        "button.mains_start_maintenance",
                        "entry-1_mains_start_maintenance",
                    ),
                    "button.mains_pause_alerts": _registry_entry(
                        "button.mains_pause_alerts",
                        "entry-1_mains_pause_alerts",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert "select.mains_sensitivity" not in refs
    assert "number.mains_kwh_goal" not in refs
    assert "button.mains_relearn" not in refs
    assert "button.mains_start_maintenance" not in refs
    assert "button.mains_pause_alerts" not in refs


def test_dashboard_omits_disabled_and_unavailable_summaries() -> None:
    class FakeStates:
        def get(self, entity_id: str) -> SimpleNamespace | None:
            if entity_id == "sensor.fridge_daily":
                return SimpleNamespace(state="unavailable")
            if entity_id == "sensor.fridge_electrical":
                return SimpleNamespace(state="unknown")
            return SimpleNamespace(state="idle")

    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.fridge_activity": _registry_entry(
                        "sensor.fridge_activity",
                        "entry-1_fridge_health_summary",
                        disabled_by="integration",
                    ),
                    "sensor.fridge_electrical": _registry_entry(
                        "sensor.fridge_electrical",
                        "entry-1_fridge_cost_today",
                    ),
                    "sensor.fridge_energy": _registry_entry(
                        "sensor.fridge_energy",
                        "entry-1_fridge_average_kwh_per_day",
                    ),
                    "sensor.fridge_daily": _registry_entry(
                        "sensor.fridge_daily",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                }
            ),
            states=FakeStates(),
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert "sensor.fridge_activity" not in refs
    assert "sensor.fridge_electrical" not in refs
    assert "sensor.fridge_daily" not in refs
    assert "sensor.fridge_energy" in refs


class _FakeDashboardsCollection:
    def __init__(self, existing: bool) -> None:
        self._existing = existing
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.deleted: list[str] = []
        self.dashboard_stores: dict[str, _FakeLovelaceStorage] | None = None

    async def async_items(self) -> list[dict[str, object]]:
        if not self._existing:
            return []
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        item = {"id": DASHBOARD_URL_PATH, **data}
        if self.dashboard_stores is not None:
            self.dashboard_stores[DASHBOARD_URL_PATH] = _FakeLovelaceStorage(item)
        return item

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        return {"id": item_id, **data}

    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)
        if self.dashboard_stores is not None:
            dashboard_store = self.dashboard_stores.pop(DASHBOARD_URL_PATH, None)
            if dashboard_store is not None:
                await dashboard_store.async_delete()


class _FakeLovelaceStorage:
    def __init__(
        self,
        config: dict[str, object],
        *,
        mode: str = "storage",
        delete_error: Exception | None = None,
    ) -> None:
        self.config = config
        self.mode = mode
        self.delete_error = delete_error
        self.saved: list[dict[str, object]] = []
        self.deleted = False

    async def async_save(self, config: dict[str, object]) -> None:
        self.saved.append(config)

    async def async_delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class _FakeLovelaceResources:
    def __init__(
        self,
        items: list[dict[str, object]] | None = None,
        *,
        loaded: bool = False,
    ) -> None:
        self.items = list(items or [])
        self.loaded = loaded
        self.load_count = 0
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def async_load(self) -> None:
        self.load_count += 1
        self.loaded = True

    def async_items(self) -> list[dict[str, object]]:
        return list(self.items)

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        item = {
            "id": f"resource-{len(self.items) + 1}",
            "type": data.get("res_type"),
            "url": data.get("url"),
        }
        self.items.append(item)
        return item

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        item = {
            "id": item_id,
            "type": data.get("res_type"),
            "url": data.get("url"),
        }
        for index, existing in enumerate(self.items):
            if existing.get("id") == item_id:
                self.items[index] = item
                break
        return item


class _FakeReadOnlyLovelaceResources:
    loaded = True

    def __init__(self, items: list[dict[str, object]] | None = None) -> None:
        self.items = list(items or [])

    def async_items(self) -> list[dict[str, object]]:
        return list(self.items)


class _FakeAttributeDashboardsCollection:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def async_items(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="lovelace-circuitsetup-energy-analyzer",
                url_path=DASHBOARD_URL_PATH,
            )
        ]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        return {"id": DASHBOARD_URL_PATH, **data}

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        return {"id": item_id, **data}


class _FakeSyncItemsDashboardsCollection(_FakeDashboardsCollection):
    def async_items(self) -> list[dict[str, object]]:  # type: ignore[override]
        if not self._existing:
            return []
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]


class _FakeDetachedDashboardsCollection(_FakeDashboardsCollection):
    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)


class _FakeExistingDashboardWithoutUpdate:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def async_items(self) -> list[dict[str, object]]:
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        return {"id": DASHBOARD_URL_PATH, **data}


class _FakeStrictUpdateDashboardsCollection(_FakeDashboardsCollection):
    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        allowed_update_keys = {
            "icon",
            "require_admin",
            "show_in_sidebar",
            "title",
        }
        extra = set(data) - allowed_update_keys
        if extra:
            raise AssertionError(f"Unexpected dashboard update keys: {extra}")
        return await super().async_update_item(item_id, data)


@pytest.mark.asyncio
async def test_coordinator_creates_recommended_dashboard_with_selected_layout() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboards: dict[str, _FakeLovelaceStorage] = {}
    collection.dashboard_stores = dashboards
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": dashboards,
                "dashboards_collection": collection,
                "resources": _FakeLovelaceResources(),
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={
            "circuits": _example_circuit_dicts(),
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
        },
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    created = collection.created[0]
    assert created["url_path"] == DASHBOARD_URL_PATH
    assert created["mode"] == "storage"
    assert created["title"] == "CircuitSetup Energy Analyzer"
    assert "config" not in created
    saved_dashboard = str(dashboards[DASHBOARD_URL_PATH].saved[0])
    assert "'path': 'overview'" in saved_dashboard
    assert "circuitsetup-energy-analyzer-appliance-grid" in saved_dashboard
    assert "sensor.fridge_health_summary" in saved_dashboard
    assert "sensor.outdoor_temperature" in saved_dashboard
    assert "sensor.hvac_outdoor_temperature" not in saved_dashboard
    assert "sensor.fridge_metric_consistency_status" not in saved_dashboard
    assert coordinator.last_dashboard_create_request["action"] == "created"
    assert (
        coordinator.last_dashboard_create_request["layout"] == DASHBOARD_LAYOUT_STANDARD
    )


@pytest.mark.asyncio
async def test_lovelace_dashboard_save_registers_graph_card_resource() -> None:
    resource = dashboard_graph_module_resource()
    expected_resource = {"res_type": resource["type"], "url": resource["url"]}
    resources = _FakeLovelaceResources()
    dashboard_store = _FakeLovelaceStorage({"url_path": DASHBOARD_URL_PATH})
    lovelace_data = SimpleNamespace(
        dashboards={DASHBOARD_URL_PATH: dashboard_store},
        resources=resources,
    )
    config = {
        "views": [
            {
                "sections": [
                    {"cards": [{"type": NILM_DASHBOARD_GRAPHS_CARD}]},
                ],
            }
        ],
    }

    saved = await dashboard_storage._async_save_lovelace_dashboard_config(
        SimpleNamespace(),
        lovelace_data,
        {"url_path": DASHBOARD_URL_PATH},
        config,
        update=False,
    )

    assert saved is True
    assert resources.loaded is True
    assert resources.load_count == 1
    assert resources.created == [expected_resource]
    assert resources.updated == []
    assert dashboard_store.saved == [config]
    assert "resources" not in dashboard_store.saved[0]


@pytest.mark.asyncio
async def test_lovelace_dashboard_save_updates_graph_card_resource_version() -> None:
    resource = dashboard_graph_module_resource()
    static_url = resource["url"].split("?", 1)[0]
    old_resource = {
        "id": "dashboard-graph-module",
        "type": "module",
        "url": f"{static_url}?v=old",
    }
    resources = _FakeLovelaceResources([old_resource], loaded=True)
    dashboard_store = _FakeLovelaceStorage({"url_path": DASHBOARD_URL_PATH})
    lovelace_data = SimpleNamespace(
        dashboards={DASHBOARD_URL_PATH: dashboard_store},
        resources=resources,
    )
    config = {
        "views": [
            {
                "sections": [
                    {"cards": [{"type": NILM_DASHBOARD_GRAPHS_CARD}]},
                ],
            }
        ],
    }

    saved = await dashboard_storage._async_save_lovelace_dashboard_config(
        SimpleNamespace(),
        lovelace_data,
        {"url_path": DASHBOARD_URL_PATH},
        config,
        update=True,
    )

    assert saved is True
    assert resources.load_count == 0
    assert resources.created == []
    assert resources.updated == [
        (
            "dashboard-graph-module",
            {"res_type": resource["type"], "url": resource["url"]},
        )
    ]


@pytest.mark.asyncio
async def test_lovelace_dashboard_strips_custom_cards_without_writable_resource(
) -> None:
    resources = _FakeReadOnlyLovelaceResources()
    dashboard_store = _FakeLovelaceStorage({"url_path": DASHBOARD_URL_PATH})
    lovelace_data = SimpleNamespace(
        dashboards={DASHBOARD_URL_PATH: dashboard_store},
        resources=resources,
    )
    config = {
        "views": [
            {
                "sections": [
                    {
                        "cards": [
                            *[
                                {"type": card_type}
                                for card_type in DASHBOARD_CUSTOM_CARD_TYPES
                            ],
                            {"type": "history-graph", "title": "Native graph"},
                        ],
                    },
                ],
            }
        ],
    }

    saved = await dashboard_storage._async_save_lovelace_dashboard_config(
        SimpleNamespace(),
        lovelace_data,
        {"url_path": DASHBOARD_URL_PATH},
        config,
        update=True,
    )

    assert saved is True
    cards = _dashboard_cards(dashboard_store.saved[0])
    assert [card.get("type") for card in cards] == ["history-graph"]
    assert cards[0]["title"] == "Native graph"


@pytest.mark.asyncio
async def test_coordinator_updates_existing_recommended_dashboard() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=True)
    dashboard_store = _FakeLovelaceStorage(
        {"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}
    )
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": {DASHBOARD_URL_PATH: dashboard_store},
                "dashboards_collection": collection,
                "resources": _FakeLovelaceResources(),
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_EXPERT},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert len(collection.updated) == 1
    item_id, update = collection.updated[0]
    assert item_id == DASHBOARD_URL_PATH
    assert update["title"] == "CircuitSetup Energy Analyzer"
    assert "config" not in update
    saved_dashboard = str(dashboard_store.saved[0])
    assert "'path': 'energy-costs'" in saved_dashboard
    assert "sensor.fridge_health_summary" in saved_dashboard
    assert "sensor.fridge_alert_evidence" not in saved_dashboard
    assert coordinator.last_dashboard_create_request["action"] == "updated"


@pytest.mark.asyncio
async def test_coordinator_updates_existing_dashboard_with_valid_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeStrictUpdateDashboardsCollection(existing=True)
    dashboard_store = _FakeLovelaceStorage(
        {"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}
    )
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": {DASHBOARD_URL_PATH: dashboard_store},
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.updated) == 1
    _item_id, update = collection.updated[0]
    assert "mode" not in update
    assert "url_path" not in update


@pytest.mark.asyncio
async def test_coordinator_updates_attribute_shaped_existing_dashboard() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeAttributeDashboardsCollection()
    dashboard_store = _FakeLovelaceStorage(
        {
            "id": "lovelace-circuitsetup-energy-analyzer",
            "url_path": DASHBOARD_URL_PATH,
        }
    )
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": {DASHBOARD_URL_PATH: dashboard_store},
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert len(collection.updated) == 1
    item_id, update = collection.updated[0]
    assert item_id == "lovelace-circuitsetup-energy-analyzer"
    assert update["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard_store.saved
    assert coordinator.last_dashboard_create_request["action"] == "updated"


@pytest.mark.asyncio
async def test_coordinator_reads_attribute_shaped_lovelace_data() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboards: dict[str, _FakeLovelaceStorage] = {}
    collection.dashboard_stores = dashboards
    hass = SimpleNamespace(
        data={
            "lovelace": SimpleNamespace(
                dashboards=dashboards,
                dashboards_collection=collection,
            )
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    assert dashboards[DASHBOARD_URL_PATH].saved
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_creates_dashboard_from_current_lovelace_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    lovelace_data = SimpleNamespace(
        dashboards={},
        resources=_FakeLovelaceResources(),
        yaml_dashboards={},
    )
    collection.dashboard_stores = lovelace_data.dashboards

    async def load_collection(hass: object, data: object) -> object:
        assert data is lovelace_data
        return collection

    monkeypatch.setattr(
        dashboard_storage,
        "_async_load_lovelace_dashboards_collection",
        load_collection,
        raising=False,
    )
    hass = SimpleNamespace(data={"lovelace": lovelace_data})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    created = collection.created[0]
    assert created["url_path"] == DASHBOARD_URL_PATH
    assert created["mode"] == "storage"
    assert "config" not in created
    stored_dashboard = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    assert stored_dashboard.saved
    saved_dashboard = str(stored_dashboard.saved[0])
    assert "'path': 'overview'" in saved_dashboard
    assert "circuitsetup-energy-analyzer-appliance-grid" in saved_dashboard
    assert "sensor.fridge_health_summary" in saved_dashboard
    assert "sensor.fridge_metric_consistency_status" not in saved_dashboard
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_handles_sync_lovelace_dashboard_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeSyncItemsDashboardsCollection(existing=False)
    lovelace_data = SimpleNamespace(
        dashboards={},
        resources=object(),
        yaml_dashboards={},
    )
    collection.dashboard_stores = lovelace_data.dashboards

    async def load_collection(hass: object, data: object) -> object:
        assert data is lovelace_data
        return collection

    monkeypatch.setattr(
        dashboard_storage,
        "_async_load_lovelace_dashboards_collection",
        load_collection,
        raising=False,
    )
    hass = SimpleNamespace(data={"lovelace": lovelace_data})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    assert lovelace_data.dashboards[DASHBOARD_URL_PATH].saved
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_skips_duplicate_dashboard_when_update_unavailable() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeExistingDashboardWithoutUpdate()
    hass = SimpleNamespace(data={"lovelace": {"dashboards_collection": collection}})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert coordinator.last_dashboard_create_request["action"] == "unavailable"
    assert (
        coordinator.last_dashboard_create_request["reason"]
        == "dashboard_update_unavailable"
    )


@pytest.mark.asyncio
async def test_coordinator_removes_existing_recommended_dashboard() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=True)
    dashboard_store = _FakeLovelaceStorage(
        {"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}
    )
    dashboards = {DASHBOARD_URL_PATH: dashboard_store}
    collection.dashboard_stores = dashboards
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": dashboards,
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_remove_dashboard()

    assert collection.deleted == [DASHBOARD_URL_PATH]
    assert DASHBOARD_URL_PATH not in dashboards
    assert dashboard_store.deleted is True
    assert coordinator.last_dashboard_remove_request == {
        "entry_id": coordinator.entry_id,
        "dashboard_path": f"/{DASHBOARD_URL_PATH}",
        "title": "CircuitSetup Energy Analyzer",
        "action": "deleted",
    }


@pytest.mark.asyncio
async def test_coordinator_reports_missing_dashboard_on_remove() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    hass = SimpleNamespace(
        data={"lovelace": {"dashboards": {}, "dashboards_collection": collection}}
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_remove_dashboard()

    assert collection.deleted == []
    assert coordinator.last_dashboard_remove_request["action"] == "missing"


@pytest.mark.asyncio
async def test_coordinator_removes_orphaned_recommended_dashboard_config() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboard_store = _FakeLovelaceStorage({"config": {"views": []}})
    dashboards = {DASHBOARD_URL_PATH: dashboard_store}
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": dashboards,
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_remove_dashboard()

    assert collection.deleted == []
    assert DASHBOARD_URL_PATH not in dashboards
    assert dashboard_store.deleted is True
    assert coordinator.last_dashboard_remove_request["action"] == "deleted"


@pytest.mark.asyncio
async def test_coordinator_does_not_remove_yaml_dashboard_as_orphan() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboard_store = _FakeLovelaceStorage(
        {"config": {"views": []}},
        mode="yaml",
        delete_error=RuntimeError("YAML dashboards should not be deleted"),
    )
    dashboards = {DASHBOARD_URL_PATH: dashboard_store}
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": dashboards,
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_remove_dashboard()

    assert collection.deleted == []
    assert dashboards[DASHBOARD_URL_PATH] is dashboard_store
    assert dashboard_store.deleted is False
    assert coordinator.last_dashboard_remove_request["action"] == "missing"


@pytest.mark.asyncio
async def test_coordinator_removes_live_dashboard_after_loading_fresh_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDetachedDashboardsCollection(existing=True)
    dashboard_store = _FakeLovelaceStorage(
        {"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}
    )
    lovelace_data = SimpleNamespace(
        dashboards={DASHBOARD_URL_PATH: dashboard_store},
        resources=object(),
        yaml_dashboards={},
    )

    async def load_collection(hass: object, data: object) -> object:
        assert data is lovelace_data
        return collection

    monkeypatch.setattr(
        dashboard_storage,
        "_async_load_lovelace_dashboards_collection",
        load_collection,
        raising=False,
    )
    hass = SimpleNamespace(data={"lovelace": lovelace_data})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_remove_dashboard()

    assert collection.deleted == [DASHBOARD_URL_PATH]
    assert DASHBOARD_URL_PATH not in lovelace_data.dashboards
    assert dashboard_store.deleted is True
    assert coordinator.last_dashboard_remove_request["action"] == "deleted"


@pytest.mark.asyncio
async def test_coordinator_records_reason_when_lovelace_collection_is_missing() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert coordinator.last_dashboard_create_request["action"] == "unavailable"
    assert (
        coordinator.last_dashboard_create_request["reason"]
        == "lovelace_dashboard_collection_unavailable"
    )
