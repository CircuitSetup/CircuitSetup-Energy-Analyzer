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
    CONTEXT_GRAPH_CARD,
    DASHBOARD_CUSTOM_CARD_TYPES,
    DASHBOARD_URL_PATH,
    DATE_RANGE_CARD,
    ENERGY_COST_CARD,
    HOUSE_FLOW_CARD,
    HVAC_ASSOCIATIONS_CARD,
    NILM_DASHBOARD_GRAPHS_CARD,
    SUMMARY_CARD,
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
        "sensor.fridge_health": _registry_entry(
            "sensor.fridge_health",
            "entry-1_fridge_health_summary",
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
        "sensor.mains_health": _registry_entry(
            "sensor.mains_health",
            "entry-1_mains_health_summary",
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
        "custom:circuitsetup-energy-analyzer-energy-cost",
    } <= cards_by_view["overview"]
    assert {CONTEXT_GRAPH_CARD} <= cards_by_view["energy-costs"]
    assert (
        "custom:circuitsetup-energy-analyzer-energy-cost"
        not in cards_by_view["energy-costs"]
    )
    assert {
        "custom:circuitsetup-energy-analyzer-house-flow",
        SUMMARY_CARD,
    } <= cards_by_view["insights"]
    assert "history-graph" not in cards_by_view["insights"]


def test_dashboard_adds_shared_date_control_and_orders_home_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.dashboard"
        "._sections_footer_supported",
        lambda: True,
    )
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )

    assert all(
        view["footer"]["card"]["type"]
        == "custom:circuitsetup-energy-analyzer-date-range"
        for view in _dashboard_views(dashboard)
    )
    assert all(
        view["footer"]["card"]["api_path"]
        == "circuitsetup_energy_analyzer/appliance_insights"
        for view in _dashboard_views(dashboard)
    )
    home = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    assert [card["type"] for card in home["sections"][0]["cards"][:4]] == [
        CONTEXT_GRAPH_CARD,
        "custom:circuitsetup-energy-analyzer-house-flow",
        "custom:circuitsetup-energy-analyzer-appliance-grid",
        "custom:circuitsetup-energy-analyzer-energy-cost",
    ]
    assert home["sections"][0]["cards"][0]["title"] == "All appliance power"


def test_dashboard_keeps_date_control_on_older_home_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.dashboard"
        "._sections_footer_supported",
        lambda: False,
    )
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
    )

    for view in _dashboard_views(dashboard):
        assert "footer" not in view
        (date_card,) = view["sections"][-1]["cards"]
        assert date_card["type"] == DATE_RANGE_CARD
        assert date_card["api_path"] == (
            "circuitsetup_energy_analyzer/appliance_insights"
        )
        assert date_card["grid_options"] == {"columns": "full"}


def test_appliance_power_graph_groups_dual_phase_entities() -> None:
    dryer = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.dryer_l1_power", SensorRole.REAL_POWER),
            SensorRef("sensor.dryer_l2_power", SensorRole.REAL_POWER),
        ),
    )
    dashboard = build_recommended_dashboard(
        (dryer, *_circuits()),
        DASHBOARD_LAYOUT_STANDARD,
    )
    home = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    graph = _card_with_title(home, "All appliance power")
    dryer_rows = [
        row
        for row in graph["entities"]
        if row["entity"].startswith("sensor.dryer_")
    ]

    assert [row["series_id"] for row in dryer_rows] == [
        "circuit:dryer",
        "circuit:dryer",
    ]
    assert {row["name"] for row in dryer_rows} == {"Dryer"}


def test_home_cards_order_graphs_before_appliances_and_configured_voltage(
) -> None:
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_watts", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_active_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_voltage", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_frequency", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_power_harmonic", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_l1_current", SensorRole.CURRENT),
            SensorRef("sensor.mains_l2_current", SensorRole.CURRENT),
        ),
    )
    states = {
        "sensor.mains_active_power": SimpleNamespace(
            state="0",
            attributes={"friendly_name": "Mains Active Power"},
        ),
        "sensor.mains_voltage": SimpleNamespace(
            state="0",
            attributes={"friendly_name": "Mains Voltage Power"},
        ),
    }
    dashboard = build_recommended_dashboard(
        (_circuits()[0], mains),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
        mains_voltage_entities=(
            "sensor.mains_l2_voltage",
            " sensor.mains_l1_voltage ",
            "sensor.mains_l1_voltage",
        ),
    )
    home = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    cards = home["sections"][0]["cards"]

    assert [card.get("title") for card in cards[:6]] == [
        "Mains total power and amps",
        "All appliance power",
        "Home energy summary",
        "Appliances",
        "Line voltage",
        "Energy and costs",
    ]
    voltage = _card_with_title(home, "Line voltage")
    assert voltage["type"] == "grid"
    assert [gauge["entity"] for gauge in voltage["cards"]] == [
        "sensor.mains_l1_voltage",
        "sensor.mains_l2_voltage",
    ]
    graph = cards[0]
    assert graph["entities"] == [
        {
            "entity": "sensor.mains_watts",
            "name": "Mains total power",
            "series_id": "mains:power",
            "axis": "left",
        },
        {
            "entity": "sensor.mains_active_power",
            "name": "Mains total power",
            "series_id": "mains:power",
            "axis": "left",
        },
        {
            "entity": "sensor.mains_power",
            "name": "Mains total power",
            "series_id": "mains:power",
            "axis": "left",
        },
        {
            "entity": "sensor.mains_l1_current",
            "name": "Total Amps",
            "series_id": "mains:current",
            "axis": "right",
        },
        {
            "entity": "sensor.mains_l2_current",
            "name": "Total Amps",
            "series_id": "mains:current",
            "axis": "right",
        },
    ]
    summary = cards[2]
    assert summary["primary_mains"]["power_entities"] == [
        "sensor.mains_watts",
        "sensor.mains_active_power",
        "sensor.mains_power",
        "sensor.mains_voltage",
        "sensor.mains_frequency",
        "sensor.mains_power_harmonic",
    ]
    assert summary["primary_mains"]["current_entities"] == [
        "sensor.mains_l1_current",
        "sensor.mains_l2_current",
    ]
    assert [card["grid_options"]["columns"] for card in cards[:6]] == [
        24,
        24,
        24,
        24,
        24,
        24,
    ]


def test_home_voltage_card_uses_native_gauges_with_adaptive_ranges() -> None:
    states = {
        "sensor.mains_l1_voltage": SimpleNamespace(state="118"),
        "sensor.mains_l2_voltage": SimpleNamespace(state="230"),
    }
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
        mains_voltage_entities=(
            "sensor.mains_l1_voltage",
            "sensor.mains_l2_voltage",
        ),
    )
    home = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )

    card = _card_with_title(home, "Line voltage")
    assert card["type"] == "grid"
    assert card["columns"] == 2
    assert card["square"] is False
    assert card["cards"] == [
        {
            "type": "gauge",
            "entity": "sensor.mains_l1_voltage",
            "needle": True,
            "min": 90,
            "max": 145,
        },
        {
            "type": "gauge",
            "entity": "sensor.mains_l2_voltage",
            "needle": True,
            "min": 180,
            "max": 280,
        },
    ]


def test_home_omits_voltage_card_without_configured_voltage_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)
    home = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )

    assert not any(
        card.get("title") == "Line voltage" for card in home["sections"][0]["cards"]
    )


def test_home_mains_graph_uses_friendly_names_for_opaque_power_sources() -> None:
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_channel_a", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_channel_b", SensorRole.REAL_POWER),
            SensorRef("sensor.main_panel_channel_1", SensorRole.REAL_POWER),
            SensorRef("sensor.main_panel_channel_2", SensorRole.REAL_POWER),
            SensorRef("sensor.main_panel_channel_3", SensorRole.REAL_POWER),
            SensorRef(
                "sensor.high_voltage_panel_active_power",
                SensorRole.REAL_POWER,
            ),
        ),
    )
    states = {
        "sensor.mains_channel_a": SimpleNamespace(
            state="0",
            attributes={"friendly_name": "Mains Supply Watts"},
        ),
        "sensor.mains_channel_b": SimpleNamespace(
            state="0",
            attributes={
                "friendly_name": "Mains Voltage Power",
                "unit_of_measurement": "W",
            },
        ),
        "sensor.main_panel_channel_1": SimpleNamespace(
            state="0",
            attributes={"unit_of_measurement": "W"},
        ),
        "sensor.main_panel_channel_2": SimpleNamespace(
            state="0",
            attributes={"unit_of_measurement": "kW"},
        ),
        "sensor.main_panel_channel_3": SimpleNamespace(
            state="0",
            attributes={
                "device_class": "power",
                "unit_of_measurement": "MW",
            },
        ),
        "sensor.high_voltage_panel_active_power": SimpleNamespace(
            state="0",
            attributes={
                "device_class": "power",
                "unit_of_measurement": "W",
            },
        ),
    }
    dashboard = build_recommended_dashboard(
        (mains,),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
    )
    home = _dashboard_views(dashboard)[0]
    graph = _card_with_title(home, "Mains total power and amps")
    summary = _card_with_title(home, "Home energy summary")

    assert [row["entity"] for row in graph["entities"]] == [
        "sensor.mains_channel_a",
        "sensor.main_panel_channel_1",
        "sensor.main_panel_channel_2",
        "sensor.high_voltage_panel_active_power",
    ]
    assert summary["primary_mains"]["power_entities"] == [
        "sensor.mains_channel_a",
        "sensor.mains_channel_b",
        "sensor.main_panel_channel_1",
        "sensor.main_panel_channel_2",
        "sensor.main_panel_channel_3",
        "sensor.high_voltage_panel_active_power",
    ]


def test_home_mains_graph_uses_amps_axis_when_power_is_unavailable() -> None:
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_current", SensorRole.CURRENT),),
    )
    dashboard = build_recommended_dashboard((mains,), DASHBOARD_LAYOUT_STANDARD)
    graph = _dashboard_views(dashboard)[0]["sections"][0]["cards"][0]

    assert graph["title"] == "Mains total power and amps"
    assert graph["y_axis_label"] == "A"
    assert graph["entities"][0]["axis"] == "left"


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
    home_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    energy_card = _card_of_type(
        home_view,
        "custom:circuitsetup-energy-analyzer-energy-cost",
    )
    home_summary = _card_of_type(
        home_view,
        "custom:circuitsetup-energy-analyzer-house-flow",
    )
    assert energy_card in home_view["sections"][0]["cards"]
    assert "energy-costs" in {
        view["path"] for view in _dashboard_views(dashboard)
    }
    assert energy_card["grid_options"]["columns"] == 24
    assert energy_card["primary_mains"]["daily_energy_usage_entity"] == (
        "sensor.mains_daily_energy_usage"
    )
    assert energy_card["primary_mains"]["cost_today_entity"] == (
        "sensor.mains_cost_today"
    )
    assert {
        appliance["circuit_id"] for appliance in energy_card["appliances"]
    } == {"fridge", "hvac"}
    assert home_summary["primary_mains"]["daily_energy_usage_entity"] == (
        "sensor.mains_daily_energy_usage"
    )
    assert home_summary["primary_mains"]["cost_today_entity"] == (
        "sensor.mains_cost_today"
    )
    assert home_summary["primary_mains"]["average_kwh_per_day_entity"] == (
        "sensor.mains_average_kwh_per_day"
    )
    assert home_summary["primary_mains"]["average_cost_per_day_entity"] == (
        "sensor.mains_average_cost_per_day"
    )
    insights_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    billing_card = _card_with_title(insights_view, "Billing Cycle")
    assert insights_view["sections"][0]["cards"][-1] == billing_card
    assert billing_card["type"] == SUMMARY_CARD
    billing_entities = {
        row["entity"] for row in billing_card["entities"] if isinstance(row, dict)
    }
    assert "sensor.mains_cost_cycle" in billing_entities
    assert "sensor.mains_cost_cycle_forecast" in billing_entities
    assert all("cost_today" not in entity_id for entity_id in billing_entities)


def test_hvac_associations_card_is_on_energy_costs_only() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    cards_by_view = {
        str(view["path"]): {
            str(card["type"])
            for card in _dashboard_cards(view)
            if isinstance(card.get("type"), str)
        }
        for view in _dashboard_views(dashboard)
    }

    assert HVAC_ASSOCIATIONS_CARD in cards_by_view["energy-costs"]
    assert HVAC_ASSOCIATIONS_CARD not in cards_by_view["overview"]
    assert HVAC_ASSOCIATIONS_CARD not in cards_by_view.get("insights", set())
    card = _card_of_type(
        next(
            view
            for view in _dashboard_views(dashboard)
            if view["path"] == "energy-costs"
        ),
        HVAC_ASSOCIATIONS_CARD,
    )
    assert card["title"] == "HVAC & Thermostats"
    assert card["entry_id"] is None
    assert card["api_path"] == "circuitsetup_energy_analyzer/hvac_associations"
    assert card["labels"]["hvac_associations_title"] == "HVAC & Thermostats"


def test_hvac_associations_card_is_omitted_without_hvac() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)

    assert HVAC_ASSOCIATIONS_CARD not in {
        str(card["type"])
        for card in _dashboard_cards(dashboard)
        if isinstance(card.get("type"), str)
    }


def test_hvac_associations_card_uses_resolved_health_sensors_for_revisions() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.renamed_hvac_health": _registry_entry(
                        "sensor.renamed_hvac_health",
                        "entry-1_hvac_health_summary",
                    )
                }
            )
        ),
        entry_id="entry-1",
    )

    card = _card_of_type(
        next(
            view
            for view in _dashboard_views(dashboard)
            if view["path"] == "energy-costs"
        ),
        HVAC_ASSOCIATIONS_CARD,
    )

    assert card["revision_entities"] == ["sensor.renamed_hvac_health"]


def test_heat_pump_dashboard_keeps_hvac_cards_and_weather_graphs() -> None:
    heat_pump = CircuitConfig(
        circuit_id="heat_pump",
        name="Heat Pump",
        appliance_profile=ApplianceProfile.HEAT_PUMP,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(SensorRef("sensor.heat_pump_power", SensorRole.REAL_POWER),),
    )
    dashboard = build_recommended_dashboard(
        (heat_pump,),
        DASHBOARD_LAYOUT_STANDARD,
        outdoor_temperature_entity="sensor.outdoor_temperature",
    )
    cards_by_view = {
        str(view["path"]): {
            str(card["type"])
            for card in _dashboard_cards(view)
            if isinstance(card.get("type"), str)
        }
        for view in _dashboard_views(dashboard)
    }

    assert "energy-costs" in cards_by_view
    assert HVAC_ASSOCIATIONS_CARD in cards_by_view["energy-costs"]
    assert CONTEXT_GRAPH_CARD in cards_by_view["energy-costs"]


def test_hvac_associations_card_is_shown_in_simple_layout() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(), DASHBOARD_LAYOUT_SIMPLE
    )
    cards_by_view = {
        str(view["path"]): {
            str(card["type"])
            for card in _dashboard_cards(view)
            if isinstance(card.get("type"), str)
        }
        for view in _dashboard_views(dashboard)
    }

    assert HVAC_ASSOCIATIONS_CARD in cards_by_view["energy-costs"]
    assert "insights" not in cards_by_view


def test_appliance_timeline_uses_activity_summary_entities() -> None:
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
        appliance["activity_entity"]
        for appliance in appliance_card["appliances"]
    } == {"sensor.fridge_activity_summary", "sensor.hvac_activity_summary"}
    assert {
        appliance["icon"] for appliance in appliance_card["appliances"]
    } == {"mdi:fridge-outline", "mdi:hvac"}
    assert all(
        "running_entity" not in appliance
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
    graphs = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    graph = _card_with_title(graphs, "HVAC activity and outdoor temperature")
    refs = _entity_refs(graphs)

    assert graph["type"] == CONTEXT_GRAPH_CARD
    assert "default_hours" not in graph
    assert "periods" not in graph
    assert graph["entities"][-1]["axis"] == "right"
    assert "sensor.hvac_power" in refs
    assert "sensor.heat_pump_power" in refs
    assert "binary_sensor.hvac_running" not in refs
    assert "sensor.outdoor_temperature" in refs
    assert CONTEXT_GRAPH_CARD not in {
        card["type"] for card in insights["sections"][0]["cards"]
    }


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
        "insights",
    }
    assert "sensor.fridge_daily_energy_usage" in refs
    assert "sensor.fridge_cost_today" in refs
    assert "sensor.mains_average_cost_per_day" in refs
    assert "sensor.fridge_health_summary" in refs
    assert "sensor.fridge_activity_summary" in refs
    assert "sensor.mains_nilm_unknown_loads" in refs
    assert "sensor.mains_cost_cycle" in refs
    assert "sensor.mains_cost_cycle_forecast" in refs
    assert "select.fridge_alert_sensitivity" not in refs
    assert "button.fridge_relearn_baseline" not in refs

    insights_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    assert _card_with_title(insights_view, "Billing Cycle")["entities"] == [
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
    for view in _dashboard_views(dashboard):
        for section in view["sections"]:
            content_cards = section["cards"]
            if len(content_cards) == 1 and content_cards[0]["type"] == DATE_RANGE_CARD:
                assert content_cards[0]["grid_options"]["columns"] == "full"
                continue
            if view["path"] == "overview":
                assert {
                    card["grid_options"]["columns"] for card in content_cards
                } == {24}
                continue
            expected_columns = (
                24
                if view["path"] == "energy-costs"
                else 48 // min(4, len(content_cards))
            )
            assert {
                card["grid_options"]["columns"] for card in content_cards
            } == {expected_columns}
    assert _card_of_type(
        dashboard,
        "custom:circuitsetup-energy-analyzer-appliance-grid",
    )


def test_single_insight_card_uses_full_width() -> None:
    dashboard = build_recommended_dashboard(
        (_example_circuits()[1],),
        DASHBOARD_LAYOUT_STANDARD,
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )

    (card,) = insights["sections"][0]["cards"]
    assert card["grid_options"]["columns"] == 48


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
    assert preflight["will_include"] == ["Home", "Insights"]


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
                "sensor.fridge_health": _registry_entry(
                    "sensor.fridge_health",
                    "entry-1_fridge_health_summary",
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

    assert "Refrigerator: Health" in preflight["disabled_entities"]
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
    assert refrigerator["activity_entity"] == "sensor.fridge_activity_summary"
    assert refrigerator["energy_today_entity"] == (
        "sensor.fridge_daily_energy_usage"
    )
    appliance_text = str(appliance_card)
    assert "binary_sensor.fridge_running" not in appliance_text
    assert "sensor.fridge_electrical_health" not in appliance_text
    assert "sensor.fridge_energy_usage_status" not in appliance_text
    assert "sensor.fridge_alert_evidence" not in appliance_text


def test_dashboard_detail_links_open_appliance_detail_pages() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
    )
    buttons = [
        card for card in _dashboard_cards(dashboard) if card.get("type") == "button"
    ]

    assert not [card for card in buttons if "Detail" in str(card.get("name", ""))]
    assert "appliance_detail=1" in str(dashboard)
    assert "Detail links" in str(dashboard)
    assert (
        "/circuitsetup-energy-analyzer-evidence?"
        "circuit_id=fridge&amp;appliance_detail=1"
    ) not in str(dashboard)
    assert "circuit_id=fridge&appliance_detail=1" in str(dashboard)
    assert "circuit_id=mains&appliance_detail=1" not in str(dashboard)
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


def test_dashboard_omits_empty_nilm_graph_from_graph_tab() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )

    assert "energy-costs" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }
    assert "resources" not in dashboard


def test_expert_dashboard_keeps_nilm_review_without_empty_graph() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_EXPERT,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    insights_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    cards = _dashboard_cards(insights_view)

    assert "energy-costs" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }
    assert any(
        card.get("name") == "Review NILM Assignments"
        for card in cards
    )
    assert "resources" not in dashboard


def test_standard_dashboard_adds_date_driven_nilm_graph_for_defined_appliances(
) -> None:
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
            if view["path"] == "energy-costs"
        )
    )

    graph = next(
        card
        for card in cards
        if card.get("title") == "Defined NILM appliance power"
    )
    assert graph["type"] == CONTEXT_GRAPH_CARD
    assert graph["entities"] == [
        {
            "entity": "sensor.pool_pump_estimated_power",
            "name": "Pool Pump",
            "series_id": "nilm:sensor.pool_pump_estimated_power",
            "axis": "left",
        }
    ]
    assert "resources" not in dashboard


def test_expert_dashboard_adds_date_driven_nilm_graph_for_defined_appliances() -> None:
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
    graph_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    cards = _dashboard_cards(graph_view)

    graph = next(
        card
        for card in cards
        if card.get("title") == "Defined NILM appliance power"
    )
    assert graph == {
        "type": CONTEXT_GRAPH_CARD,
        "title": "Defined NILM appliance power",
        "y_axis_label": "W",
        "entities": [
            {
                "entity": "sensor.pool_pump_estimated_power",
                "name": "Pool Pump",
                "series_id": "nilm:sensor.pool_pump_estimated_power",
                "axis": "left",
            }
        ],
        "labels": graph["labels"],
        "grid_options": {"columns": 24},
    }
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
    graphs = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    graph_refs = _entity_refs(graphs)
    insight_refs = _entity_refs(insights)

    assert "binary_sensor.compressor_running" not in graph_refs
    assert "sensor.backyard_temperature" in graph_refs
    assert "sensor.compressor_weather_context" in insight_refs
    assert _card_with_title(insights, "HVAC weather context")["type"] == SUMMARY_CARD
    assert "sensor.compressor_outdoor_temperature" not in graph_refs
    assert "sensor.compressor_run_cycle_runtime" not in graph_refs
    assert "sensor.compressor_run_cycle_duty_cycle" not in graph_refs


def test_dashboard_adds_hvac_weather_section_for_mini_split() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="mini_split",
                name="Mini-Split",
                appliance_profile=ApplianceProfile.MINI_SPLIT,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(
                    SensorRef("sensor.mini_split_power", SensorRole.REAL_POWER),
                ),
            ),
        ),
        DASHBOARD_LAYOUT_STANDARD,
        outdoor_temperature_entity="sensor.backyard_temperature",
    )
    graphs = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    insights = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )

    assert "sensor.backyard_temperature" in _entity_refs(graphs)
    assert "sensor.mini_split_weather_context" in _entity_refs(insights)
    assert _card_with_title(insights, "HVAC weather context")["type"] == SUMMARY_CARD


def test_hvac_graph_omits_apparent_and_reactive_power_sources() -> None:
    circuits = (
        CircuitConfig(
            circuit_id="compressor",
            name="A/C Compressor",
            appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
            mode=CircuitMode.DUAL_PHASE,
            sensors=(
                SensorRef("sensor.compressor_w", SensorRole.REAL_POWER),
                SensorRef("sensor.compressor_va", SensorRole.REAL_POWER),
                SensorRef("sensor.compressor_var", SensorRole.REAL_POWER),
            ),
        ),
    )
    states = {
        "sensor.compressor_w": SimpleNamespace(
            state="2500",
            attributes={"unit_of_measurement": "W"},
        ),
        "sensor.compressor_va": SimpleNamespace(
            state="2600",
            attributes={"unit_of_measurement": "VA"},
        ),
        "sensor.compressor_var": SimpleNamespace(
            state="400",
            attributes={"unit_of_measurement": "var"},
        ),
    }
    dashboard = build_recommended_dashboard(
        circuits,
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
        outdoor_temperature_entity="sensor.backyard_temperature",
    )
    graphs = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    history_graph = _card_with_title(
        graphs,
        "HVAC activity and outdoor temperature",
    )
    graph_cards = graphs["sections"][0]["cards"]
    refs = _entity_refs(history_graph)

    assert history_graph["type"] == CONTEXT_GRAPH_CARD
    assert {card["type"] for card in graph_cards} == {
        HVAC_ASSOCIATIONS_CARD,
        CONTEXT_GRAPH_CARD,
    }
    assert "sensor.compressor_w" in refs
    assert "sensor.compressor_va" not in refs
    assert "sensor.compressor_var" not in refs


@pytest.mark.parametrize(
    ("profile", "circuit_id", "name"),
    [
        (ApplianceProfile.WASHER, "washer", "Washer"),
        (ApplianceProfile.DISHWASHER, "dishwasher", "Dishwasher"),
    ],
)
def test_water_context_is_a_separate_dual_axis_graph(
    profile: ApplianceProfile,
    circuit_id: str,
    name: str,
) -> None:
    appliance = CircuitConfig(
        circuit_id=circuit_id,
        name=name,
        appliance_profile=profile,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef(f"sensor.{circuit_id}_power", SensorRole.REAL_POWER),),
    )
    registry = {
        f"sensor.{circuit_id}_water_context": _registry_entry(
            f"sensor.{circuit_id}_water_context",
            f"entry-1_{circuit_id}_water_flow_correlation",
        )
    }
    dashboard = build_recommended_dashboard(
        (appliance,),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(entities=registry),
            states=SimpleNamespace(get=lambda _entity_id: None),
        ),
        entry_id="entry-1",
    )
    energy_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "energy-costs"
    )
    home_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "overview"
    )
    energy_card = _card_of_type(
        home_view,
        "custom:circuitsetup-energy-analyzer-energy-cost",
    )
    water_card = _card_with_title(energy_view, "Water flow context")

    assert energy_view["sections"][0]["cards"] == [water_card]
    assert "water_contexts" not in energy_card
    assert water_card["type"] == CONTEXT_GRAPH_CARD
    assert "default_hours" not in water_card
    assert "periods" not in water_card
    assert "y_axis_label" not in water_card
    assert water_card["water_contexts"] == [
        {
            "name": name,
            "series_id": f"circuit:{circuit_id}",
            "correlation_entity": f"sensor.{circuit_id}_water_context",
            "power_entities": [f"sensor.{circuit_id}_power"],
        }
    ]


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
    insights_view = next(
        view for view in _dashboard_views(dashboard) if view["path"] == "insights"
    )
    assert _card_with_title(insights_view, "Billing Cycle")


def test_dashboard_layout_uses_example_summary_and_shared_tracking_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_SIMPLE)
    refs = _entity_refs(dashboard)

    assert dashboard["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard["views"][0]["path"] == "overview"
    assert {
        "sensor.fridge_health_summary",
        "sensor.fridge_activity_summary",
        "sensor.fridge_daily_energy_usage",
        "sensor.fridge_cost_today",
    } <= refs
    assert "mains-nilm" not in {
        view["path"] for view in _dashboard_views(dashboard)
    }
    assert "sensor.fridge_metric_consistency_status" not in refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_standard_dashboard_layout_keeps_appliance_cards_compact() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)
    refs = _entity_refs(dashboard)

    assert "sensor.fridge_health_summary" in refs
    assert "sensor.fridge_activity_summary" in refs
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
    assert "sensor.fridge_activity_summary" in refs
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
                    "sensor.kitchen_fridge_energy": _registry_entry(
                        "sensor.kitchen_fridge_energy",
                        "entry-1_fridge_energy_summary",
                    ),
                    "sensor.kitchen_fridge_daily_kwh": _registry_entry(
                        "sensor.kitchen_fridge_daily_kwh",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.kitchen_fridge_health",
        "sensor.kitchen_fridge_activity",
        "sensor.kitchen_fridge_daily_kwh",
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
        "sensor.fridge_daily",
    } <= refs
    assert "sensor.fridge_energy" not in refs
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


def test_dashboard_omits_disabled_and_unused_summaries() -> None:
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
    assert "sensor.fridge_electrical" in refs
    assert "sensor.fridge_daily" in refs
    assert "sensor.fridge_energy" not in refs


def test_dashboard_keeps_unavailable_today_entities_for_live_totals() -> None:
    class FakeStates:
        def get(self, entity_id: str) -> SimpleNamespace:
            return SimpleNamespace(state="unavailable")

    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.fridge_daily": _registry_entry(
                        "sensor.fridge_daily",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                    "sensor.fridge_cost": _registry_entry(
                        "sensor.fridge_cost",
                        "entry-1_fridge_cost_today",
                    ),
                }
            ),
            states=FakeStates(),
        ),
        entry_id="entry-1",
    )
    home_card = _card_of_type(dashboard, HOUSE_FLOW_CARD)
    energy_card = _card_of_type(dashboard, ENERGY_COST_CARD)

    for card in (home_card, energy_card):
        fridge = next(
            appliance
            for appliance in card["appliances"]
            if appliance["circuit_id"] == "fridge"
        )
        assert fridge["energy_today_entity"] == "sensor.fridge_daily"
        assert fridge["cost_today_entity"] == "sensor.fridge_cost"


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
    assert "custom:circuitsetup-energy-analyzer-energy-cost" in saved_dashboard
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
