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
    DASHBOARD_URL_PATH,
    NILM_DASHBOARD_GRAPHS_CARD,
    build_recommended_dashboard,
    dashboard_graph_module_resource,
    dashboard_preflight_summary,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


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
        if isinstance(value, dict):
            entity_id = value.get("entity")
            if isinstance(entity_id, str):
                refs.add(entity_id)
            entities = value.get("entities")
            if isinstance(entities, list):
                for item in entities:
                    if isinstance(item, str):
                        refs.add(item)
                    else:
                        walk(item)
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
        if isinstance(value, dict):
            if value.get("entity") == entity_id:
                count += 1
            entities = value.get("entities")
            if isinstance(entities, list):
                for item in entities:
                    if item == entity_id:
                        count += 1
                    else:
                        walk(item)
            for key, nested in value.items():
                if key == "entities":
                    continue
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


def test_generated_dashboard_uses_dashboard_example_sections() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert [section.get("title") for section in _dashboard_sections(dashboard)] == [
        "Household Overview",
        "Today's Energy",
        "Behavior Watchlist",
        "Appliance Status",
        "Mains, Solar, and NILM",
        "Energy Tracking",
        "Appliance Run Timeline",
        "NILM Review",
        "HVAC Weather Context",
    ]
    assert dashboard["views"][0]["type"] == "sections"
    assert dashboard["views"][0]["title"] == "Overview"
    assert dashboard["views"][0]["path"] == "overview"
    assert dashboard["views"][0]["max_columns"] == 4
    assert dashboard["views"][0]["dense_section_placement"] is True


def test_dashboard_visual_story_sections_use_existing_summary_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    refs = _entity_refs(dashboard)

    assert _dashboard_section(dashboard, "Household Overview")
    assert _dashboard_section(dashboard, "Today's Energy")
    assert _dashboard_section(dashboard, "Behavior Watchlist")
    assert _dashboard_section(dashboard, "Appliance Run Timeline")
    assert _dashboard_section(dashboard, "NILM Review")
    assert "sensor.fridge_daily_energy_usage" in refs
    assert "sensor.fridge_energy_summary" in refs
    assert "sensor.fridge_activity_summary" in refs
    assert "sensor.mains_nilm_unknown_loads" in refs
    assert "select.fridge_alert_sensitivity" not in refs
    assert "button.fridge_relearn_baseline" not in refs


def test_dashboard_nilm_review_section_only_appears_when_mains_nilm_exists() -> None:
    dashboard = build_recommended_dashboard(
        (_config for _config in _example_circuits() if _config.circuit_id != "mains"),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert "NILM Review" not in {
        section.get("title") for section in _dashboard_sections(dashboard)
    }


def test_dashboard_preflight_summarizes_included_and_skipped_sections() -> None:
    preflight = dashboard_preflight_summary(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )

    assert preflight["layout"] == DASHBOARD_LAYOUT_STANDARD
    assert preflight["will_include"] == [
        "Household Overview",
        "Today's Energy",
        "Behavior Watchlist",
        "Appliance Status",
        "Mains, Solar, and NILM",
        "Energy Tracking",
        "Appliance Run Timeline",
        "NILM Review",
        "HVAC Weather Context",
    ]
    assert "Diagnostics and Evidence" in preflight["will_skip"]
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
    appliance_status = _dashboard_section(dashboard, "Appliance Status")
    refrigerator = _card_with_title(appliance_status, "Refrigerator")

    assert refrigerator["type"] == "entities"
    assert refrigerator["entities"] == [
        {"entity": "sensor.fridge_activity_summary", "name": "Activity"},
        {"entity": "sensor.fridge_electrical_health", "name": "Electrical Health"},
        {"entity": "sensor.fridge_energy_summary", "name": "Energy Summary"},
        {"entity": "sensor.fridge_daily_energy_usage", "name": "Daily Energy Usage"},
    ]
    appliance_text = str(appliance_status)
    assert "sensor.fridge_health_summary" not in appliance_text
    assert "binary_sensor.fridge_running" not in appliance_text
    assert "sensor.fridge_energy_usage_status" not in appliance_text
    assert "sensor.fridge_alert_evidence" not in appliance_text


def test_generated_dashboard_omits_dropdown_and_switch_controls() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_EXPERT,
    )
    refs = _entity_refs(dashboard)

    assert not {
        entity_id
        for entity_id in refs
        if entity_id.startswith(("select.", "switch."))
    }
    assert "Dashboard Controls" not in str(dashboard)
    assert "Controls" not in str(dashboard)


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
    mains_section = _dashboard_section(dashboard, "Mains, Solar, and NILM")

    review_card = next(
        card
        for card in _dashboard_cards(mains_section)
        if card.get("name") == "Open NILM Graph & Review"
    )

    assert review_card["type"] == "button"
    assert review_card["tap_action"] == {
        "action": "navigate",
        "navigation_path": (
            "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        ),
    }


def test_dashboard_hides_nilm_graph_cards_without_defined_appliances() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_STANDARD,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )

    cards = _dashboard_cards(_dashboard_section(dashboard, "Mains, Solar, and NILM"))

    assert not [
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    ]
    assert not [card for card in cards if card.get("title") == "NILM mains power"]
    assert "resources" not in dashboard


def test_standard_dashboard_hides_nilm_graph_cards_for_defined_appliances() -> None:
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
    cards = _dashboard_cards(_dashboard_section(dashboard, "Mains, Solar, and NILM"))

    assert not [
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    ]
    assert not [
        card for card in cards if card.get("title") == "Defined NILM appliance power"
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
    mains_section = _dashboard_section(dashboard, "Mains, Solar, and NILM")
    cards = _dashboard_cards(mains_section)

    custom_graph = next(
        card
        for card in cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-dashboard-graphs"
    )
    appliance_graph = _card_with_title(mains_section, "Defined NILM appliance power")

    assert custom_graph == {
        "type": "custom:circuitsetup-energy-analyzer-dashboard-graphs",
        "title": "NILM mains power",
        "entry_id": "entry-1",
        "circuit_id": "mains",
        "detail_path": (
            "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        ),
        "appliance_power_entities": ["sensor.pool_pump_estimated_power"],
    }
    assert appliance_graph == {
        "type": "history-graph",
        "title": "Defined NILM appliance power",
        "hours_to_show": 24,
        "entities": [
            {"entity": "sensor.pool_pump_estimated_power", "name": "Pool Pump"}
        ],
    }
    assert "resources" not in dashboard


def test_standard_dashboard_links_appliance_evidence_without_control_entities() -> None:
    dashboard = build_recommended_dashboard(
        _example_circuits(),
        DASHBOARD_LAYOUT_STANDARD,
    )
    appliance_status = _dashboard_section(dashboard, "Appliance Status")

    evidence_card = next(
        card
        for card in _dashboard_cards(appliance_status)
        if card.get("name") == "Open Refrigerator Evidence"
    )
    refs = _entity_refs(appliance_status)

    assert evidence_card["type"] == "button"
    assert evidence_card["tap_action"] == {
        "action": "navigate",
        "navigation_path": (
            "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge"
        ),
    }
    assert "sensor.fridge_alert_evidence" not in refs
    assert not {
        entity_id
        for entity_id in refs
        if entity_id.startswith(("button.", "select.", "switch."))
    }
    assert "Controls" not in str(appliance_status)


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
    hvac_section = _dashboard_section(dashboard, "HVAC Weather Context")
    refs = _entity_refs(hvac_section)
    dashboard_refs = _entity_refs(dashboard)

    assert "sensor.compressor_activity_summary" in dashboard_refs
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

    assert "sensor.compressor_weather_context" in refs
    assert "sensor.compressor_outdoor_temperature" not in refs


def test_dashboard_layout_uses_example_summary_and_shared_tracking_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_SIMPLE)
    refs = _entity_refs(dashboard)

    assert dashboard["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard["views"][0]["path"] == "overview"
    assert {
        "sensor.fridge_activity_summary",
        "sensor.fridge_electrical_health",
        "sensor.fridge_energy_summary",
        "sensor.fridge_daily_energy_usage",
    } <= refs
    assert "sensor.mains_nilm_unknown_loads" not in refs
    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs
    assert "sensor.fridge_metric_consistency_status" not in refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_standard_dashboard_layout_keeps_appliance_cards_compact() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)
    refs = _entity_refs(dashboard)

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
    mains_section = _dashboard_section(dashboard, "Mains, Solar, and NILM")
    markdown = "\n".join(_markdown_contents(mains_section))

    assert "Mains rollups note" not in markdown
    assert "Mains load match note" not in markdown
    assert "Unknown load signals note" not in markdown
    assert "Missing entities:" not in markdown
    assert "how much of current mains power is explained" not in markdown


def test_expert_dashboard_layout_adds_evidence_links_without_duplication() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_EXPERT)
    refs = _entity_refs(dashboard)
    markdown = str(dashboard)

    assert "sensor.fridge_activity_summary" in refs
    assert "sensor.fridge_alert_evidence" not in refs
    assert "sensor.fridge_power_quality_evidence" not in refs
    assert "sensor.fridge_energy_dashboard_status" not in refs
    assert (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge" in markdown
    )
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
        "sensor.kitchen_fridge_activity",
        "sensor.kitchen_fridge_electrical",
        "sensor.kitchen_fridge_energy",
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
                            entity_key="activity_summary",
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


def test_dashboard_notes_ambiguous_summary_metadata_matches_without_guessing() -> None:
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
                        entity_key="activity_summary",
                    ),
                    "sensor.second_activity": _registry_entry(
                        "sensor.second_activity",
                        "future-scheme-2",
                        circuit_id="fridge",
                        entity_key="activity_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.first_activity" not in refs
    assert "sensor.second_activity" not in refs
    assert "sensor.fridge_activity_summary" not in refs
    assert "Ambiguous entities: Activity" in markdown
    assert (
        "Next step: remove duplicate stale analyzer entities or reload the integration."
        in markdown
    )


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
                        "entry-1_kitchen_fridge_activity_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    appliance_status = _dashboard_section(dashboard, "Appliance Status")
    kitchen_fridge = _card_with_title(appliance_status, "Kitchen Fridge")
    markdown = "\n".join(_markdown_contents(dashboard))

    assert (
        _entity_ref_count(kitchen_fridge, "sensor.kitchen_fridge_activity")
        == 1
    )
    assert "Fridge dashboard note" in markdown
    assert "Missing entities: Activity" in markdown


def test_dashboard_adds_helpful_notes_for_missing_and_disabled_entities() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_energy": _registry_entry(
                        "sensor.kitchen_fridge_energy",
                        "entry-1_fridge_energy_summary",
                    ),
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_fridge_activity_summary",
                        disabled_by="integration",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.kitchen_fridge_energy" in refs
    assert "sensor.kitchen_fridge_activity" not in refs
    assert "Refrigerator dashboard note" in markdown
    assert "Disabled entities: Activity" in markdown
    assert "Next step: enable these entities from Home Assistant entity settings." in (
        markdown
    )
    assert "Missing entities: Electrical Health, Daily Energy Usage" in markdown
    assert (
        "Next step: reload the integration or review Entity Detail Level."
        in markdown
    )


def test_dashboard_does_not_guess_ids_when_registry_is_available_but_empty() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs
    assert "Refrigerator dashboard note" in markdown
    assert (
        "Missing entities: Activity, Electrical Health, Energy Summary, "
        "Daily Energy Usage"
    ) in markdown
    assert (
        "Next step: reload the integration or review Entity Detail Level."
        in markdown
    )


def test_dashboard_uses_registry_ids_and_ignores_controls() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
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


def test_dashboard_notes_missing_disabled_and_unavailable_summaries() -> None:
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
                        "entry-1_fridge_activity_summary",
                        disabled_by="integration",
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
                }
            ),
            states=FakeStates(),
        ),
        entry_id="entry-1",
    )
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "Refrigerator dashboard note" in markdown
    assert "Disabled entities: Activity" in markdown
    assert "Next step: enable these entities from Home Assistant entity settings." in (
        markdown
    )
    assert (
        "Unavailable entities: Electrical Health, Daily Energy Usage"
        in markdown
    )
    assert "Next step: open the entity details and follow its availability reason." in (
        markdown
    )


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
    assert "Appliance Status" in saved_dashboard
    assert "sensor.fridge_activity_summary" in saved_dashboard
    assert "sensor.outdoor_temperature" in saved_dashboard
    assert "sensor.hvac_outdoor_temperature" not in saved_dashboard
    assert "sensor.fridge_metric_consistency_status" not in saved_dashboard
    assert coordinator.last_dashboard_create_request["action"] == "created"
    assert (
        coordinator.last_dashboard_create_request["layout"]
        == DASHBOARD_LAYOUT_STANDARD
    )


@pytest.mark.asyncio
async def test_lovelace_dashboard_save_registers_graph_card_resource() -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module

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

    saved = await module._async_save_lovelace_dashboard_config(
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
    from custom_components.circuitsetup_energy_analyzer import coordinator as module

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

    saved = await module._async_save_lovelace_dashboard_config(
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
async def test_lovelace_dashboard_strips_graph_card_without_writable_resource() -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module

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
                            {"type": NILM_DASHBOARD_GRAPHS_CARD},
                            {"type": "history-graph", "title": "Native graph"},
                        ],
                    },
                ],
            }
        ],
    }

    saved = await module._async_save_lovelace_dashboard_config(
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
    assert "Energy Tracking" in saved_dashboard
    assert "sensor.fridge_activity_summary" in saved_dashboard
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
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
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
        module,
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
    assert "Appliance Status" in saved_dashboard
    assert "sensor.fridge_activity_summary" in saved_dashboard
    assert "sensor.fridge_metric_consistency_status" not in saved_dashboard
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_handles_sync_lovelace_dashboard_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
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
        module,
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
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
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
        module,
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
