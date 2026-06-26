from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer"


EXPECTED_FLOW_LABELS = {
    "source_devices": "Source Devices",
    "extra_source_entities": "Extra Source Entities",
    "demo_source_bundle_enabled": "Load Bundled Demo Sources",
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "outdoor_temperature_entity": "Outdoor Temperature Entity",
    "rain_sensor_entity": "Rain Sensor",
    "rain_intensity_entity": "Rain Intensity Sensor",
    "water_flow_sensor_entities": "Water Flow Sensors",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_OPTIONS_LABELS = {
    "source_devices": "Source Devices",
    "extra_source_entities": "Extra Source Entities",
    "demo_source_bundle_enabled": "Load Bundled Demo Sources",
    "outdoor_temperature_entity": "Outdoor Temperature Entity",
    "rain_sensor_entity": "Rain Sensor",
    "rain_intensity_entity": "Rain Intensity Sensor",
    "water_flow_sensor_entities": "Water Flow Sensors",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_MAINS_LABELS = {
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "known_load_circuits": "Known Load Circuits",
}

EXPECTED_UTILITY_LABELS = {
    "enable_utility_comparison": "Enable Utility Comparison",
    "circuit_id": "Circuit",
    "utility_energy_entity": "Utility Energy Entity",
    "utility_statistic_id": "Utility Statistic ID",
    "utility_source_type": "Utility Source Type",
    "utility_statistic_period": "Utility Statistic Period",
    "measured_energy_entities": "Measured Energy Entities",
    "tolerance_percent": "Tolerance Percent",
}

EXPECTED_ADVANCED_CIRCUIT_LABELS = {
    "circuit_id": "Circuit",
}

EXPECTED_ADVANCED_TOP_LEVEL_LABELS = {
    "reset_advanced_settings_to_defaults": (
        "Reset All Advanced Circuit Settings to Default"
    ),
}

EXPECTED_ADVANCED_SETTINGS_LABELS = {
    "preset": "Sensitivity",
    "reset_operating_detection_settings_to_defaults": (
        "Reset Operating Detection To Defaults"
    ),
    "operating_on_threshold_w": "Turn-On Power",
    "operating_on_dwell_seconds": "Turn-On Confirmation Time",
    "operating_off_threshold_w": "Turn-Off Power",
    "operating_off_dwell_seconds": "Turn-Off Confirmation Time",
    "operating_merge_gap_seconds": "Merge Short Interruptions",
    "reset_energy_settings_to_defaults": "Reset Energy Settings To Defaults",
    "window_days": "Energy Window Days",
    "daily_spike_ratio": "Daily Spike Ratio",
    "daily_goal_kwh": "Daily Goal kWh",
    "goal_alert_ratio": "Goal Alert Ratio",
    "reset_activity_settings_to_defaults": "Reset Activity Settings To Defaults",
    "max_active_minutes": "Max Active Minutes",
    "max_idle_minutes": "Max Idle Minutes",
    "reset_billing_cost_settings_to_defaults": "Reset Billing Settings To Defaults",
    "cycle_start_day": "Cycle Start Day",
    "budget_kwh": "Budget kWh",
    "budget_alert_ratio": "Budget Alert Ratio",
    "billing_min_elapsed_days": "Billing Minimum Elapsed Days",
    "default_rate_per_kwh": "Default Rate Per kWh",
    "tou_rate_per_kwh": "TOU Rate Per kWh",
    "tou_start": "TOU Start",
    "tou_end": "TOU End",
    "tou_weekdays": "TOU Weekdays",
    "tou_name": "TOU Name",
    "reset_demand_capacity_settings_to_defaults": (
        "Reset Demand And Capacity To Defaults"
    ),
    "window_minutes": "Demand Window Minutes",
    "demand_limit_w": "Demand Limit W",
    "breaker_amps": "Breaker Amps",
    "warning_ratio": "Capacity Warning Ratio",
    "reset_standby_settings_to_defaults": "Reset Standby Settings To Defaults",
    "window_hours": "Standby Window Hours",
    "standby_threshold_w": "Standby Threshold W",
    "always_on_alert_w": "Always On Alert W",
    "standby_min_samples": "Standby Minimum Samples",
    "reset_water_context_settings_to_defaults": "Reset Water Context To Defaults",
    "rain_pump_correlation_enabled": "Rain and Pump Correlation",
    "rain_response_window_minutes": "Rain Response Window Minutes",
    "rain_activity_delta_threshold_pct": "Rain Activity Threshold Percent",
    "water_flow_correlation_enabled": "Water Flow Correlation",
    "linked_flow_sensor_entities": "Linked Flow Sensors",
    "expects_water_flow": "Expects Water Flow",
    "flow_mismatch_threshold_minutes": "Flow Mismatch Threshold Minutes",
    "reset_dual_phase_settings_to_defaults": "Reset Dual-Phase Settings To Defaults",
    "leg_imbalance_warning_ratio": "Leg Imbalance Warning Ratio",
    "leg_imbalance_min_total_power_w": "Leg Imbalance Minimum Total Power W",
    "reset_power_quality_settings_to_defaults": "Reset Power Quality To Defaults",
    "apparent_power_tolerance_percent": "Apparent Power Tolerance Percent",
    "power_factor_tolerance": "Power Factor Tolerance",
    "minimum_apparent_power_va": "Minimum Apparent Power VA",
    "reset_mains_balance_settings_to_defaults": "Reset Mains Balance To Defaults",
    "balance_negative_tolerance_w": "Balance Negative Tolerance W",
    "reset_solar_flow_settings_to_defaults": "Reset Solar Flow To Defaults",
    "solar_export_tolerance_w": "Solar Export Tolerance W",
    "solar_surplus_threshold_w": "Solar Surplus Threshold W",
    "high_solar_surplus_threshold_w": "High Solar Surplus Threshold W",
    "flexible_load_running_threshold_w": "Flexible Load Running Threshold W",
}

EXPECTED_ADVANCED_SECTION_LABELS = {
    "analysis_settings": "Sensitivity",
    "operating_detection_settings": "Operating Detection",
    "energy_settings": "Energy Usage And Goals",
    "activity_settings": "Run And Activity Alerts",
    "billing_cost_settings": "Billing And Cost",
    "demand_capacity_settings": "Demand And Capacity",
    "standby_settings": "Always On And Standby",
    "water_context_settings": "Water Context",
    "dual_phase_settings": "Dual-Phase Leg Imbalance",
    "power_quality_settings": "Power Metric Consistency",
    "mains_balance_settings": "Mains Balance",
    "solar_flow_settings": "Solar Flow",
}

EXPECTED_SERVICE_FIELD_NAMES = {
    "alert_id": "Alert ID",
    "always_on_alert_w": "Always On Alert W",
    "budget_alert_ratio": "Budget Alert Ratio",
    "budget_kwh": "Budget kWh",
    "breaker_amps": "Breaker Amps",
    "circuit_id": "Circuit ID",
    "cycle_start_day": "Cycle Start Day",
    "daily_goal_kwh": "Daily Goal kWh",
    "daily_spike_ratio": "Daily Spike Ratio",
    "default_rate_per_kwh": "Default Rate Per kWh",
    "demand_limit_w": "Demand Limit W",
    "duration": "Duration",
    "entry_id": "Entry ID",
    "entity_id": "Analyzer Entity",
    "goal_alert_ratio": "Goal Alert Ratio",
    "ground_truth_entity_id": "Ground Truth Entity",
    "label": "Label",
    "interval_id": "Interval ID",
    "assignment_id": "Assignment ID",
    "appliance_id": "Appliance ID",
    "appliance_profile": "Appliance Profile",
    "apparent_power_tolerance_percent": "Apparent Power Tolerance Percent",
    "end": "End",
    "export_tolerance_w": "Export Tolerance W",
    "flexible_load_running_threshold_w": "Flexible Load Running Threshold W",
    "high_solar_surplus_threshold_w": "High Solar Surplus Threshold W",
    "minimum_apparent_power_va": "Minimum Apparent Power VA",
    "minimum_total_power_w": "Minimum Total Power W",
    "max_active_minutes": "Max Active Minutes",
    "max_idle_minutes": "Max Idle Minutes",
    "mains_entity_id": "Mains Entity",
    "measured_energy_entities": "Measured Energy Entities",
    "negative_tolerance_w": "Negative Tolerance W",
    "note": "Note",
    "power_factor_tolerance": "Power Factor Tolerance",
    "preset": "Preset",
    "recommendation_id": "Recommendation ID",
    "relearn": "Relearn",
    "relearn_on_end": "Relearn On End",
    "signature_id": "Signature ID",
    "source_assignment_id": "Source Assignment ID",
    "source_signature_id": "Source Signature ID",
    "solar_surplus_threshold_w": "Solar Surplus Threshold W",
    "session_id": "Session ID",
    "signature_fingerprint": "Signature Fingerprint",
    "start": "Start",
    "standby_threshold_w": "Standby Threshold W",
    "target_signature_id": "Target Signature ID",
    "target_assignment_id": "Target Assignment ID",
    "threshold_w": "Threshold W",
    "tou_end": "TOU End",
    "tou_name": "TOU Name",
    "tou_rate_per_kwh": "TOU Rate Per kWh",
    "tou_start": "TOU Start",
    "tou_weekdays": "TOU Weekdays",
    "tolerance_percent": "Tolerance Percent",
    "utility_energy_entity": "Utility Energy Entity",
    "utility_source_type": "Utility Source Type",
    "utility_statistic_id": "Utility Statistic ID",
    "utility_statistic_period": "Utility Statistic Period",
    "warning_ratio": "Warning Ratio",
    "window_days": "Window Days",
    "window_hours": "Window Hours",
    "window_minutes": "Window Minutes",
}


def test_config_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    data = strings["config"]["step"]["user"]["data"]
    descriptions = strings["config"]["step"]["user"]["data_description"]

    assert data == EXPECTED_FLOW_LABELS
    assert descriptions.keys() == EXPECTED_FLOW_LABELS.keys()
    assert all("_" not in label for label in data.values())
    assert all(description.endswith(".") for description in descriptions.values())
    assert all(20 <= len(description) <= 260 for description in descriptions.values())
    assert "esphome" in descriptions["source_devices"].lower()
    assert "power, voltage, current" in descriptions["extra_source_entities"].lower()
    assert "power factor" in descriptions["extra_source_entities"].lower()
    assert "optional" in descriptions["mains_source_entities"].lower()
    assert "fewer alerts" in descriptions["sensitivity"].lower()
    assert "balanced is the default" in descriptions["sensitivity"].lower()
    assert "more responsive" in descriptions["sensitivity"].lower()
    assert "storage" in descriptions["retention_mode"].lower()
    assert "diagnostic evidence" in descriptions["retention_mode"].lower()
    assert "binary" in descriptions["water_flow_sensor_entities"].lower()
    assert "numeric" in descriptions["water_flow_sensor_entities"].lower()
    assert "greater than 0" in descriptions["water_flow_sensor_entities"].lower()
    for days in ("14 days", "45 days", "180 days"):
        assert days in descriptions["retention_mode"]
    assert "saves these source settings" in strings["config"]["step"]["user"][
        "description"
    ].lower()


def test_options_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    init_step = strings["options"]["step"]["init"]
    data = strings["options"]["step"]["sources"]["data"]
    descriptions = strings["options"]["step"]["sources"]["data_description"]

    assert list(init_step["menu_options"]) == [
        "sources",
        "mains",
        "assign",
        "utility",
        "dashboard",
        "entity_detail",
        "compact_migration",
        "recommendations",
        "advanced",
    ]
    assert init_step["menu_options"] == {
        "sources": "🔌 Edit Source Selection",
        "mains": "⚡ Edit Mains Sensors & NILM Setting",
        "assign": "🏷️ Appliance Circuit Assignments",
        "utility": "📊 Utility / Opower Comparison",
        "dashboard": "📋 Create Or Update Dashboard",
        "entity_detail": "👁️ Entity Detail Level",
        "compact_migration": "🧹 Migrate To Compact Entity Model",
        "recommendations": "💡 Review Suggested Settings",
        "advanced": "🛠️ Advanced Circuit Settings",
    }
    assert all("_" not in label for label in init_step["menu_options"].values())
    assert "choose" in init_step["description"].lower()
    assert "source_devices" not in init_step
    assert "extra_source_entities" not in init_step
    assert data == EXPECTED_OPTIONS_LABELS
    assert descriptions.keys() == EXPECTED_OPTIONS_LABELS.keys()
    assert all("_" not in label for label in data.values())
    assert all(description.endswith(".") for description in descriptions.values())
    assert all(20 <= len(description) <= 260 for description in descriptions.values())
    assert "fewer alerts" in descriptions["sensitivity"].lower()
    assert "balanced is the default" in descriptions["sensitivity"].lower()
    assert "more responsive" in descriptions["sensitivity"].lower()
    assert "storage" in descriptions["retention_mode"].lower()
    assert "diagnostic evidence" in descriptions["retention_mode"].lower()
    assert "binary" in descriptions["water_flow_sensor_entities"].lower()
    assert "numeric" in descriptions["water_flow_sensor_entities"].lower()
    assert "greater than 0" in descriptions["water_flow_sensor_entities"].lower()
    for days in ("14 days", "45 days", "180 days"):
        assert days in descriptions["retention_mode"]
    assert "saves these source settings" in strings["options"]["step"]["sources"][
        "description"
    ].lower()
    entity_detail = strings["options"]["step"]["entity_detail"]
    assert entity_detail["data"]["entity_detail_level"] == "Entity Detail Level"
    assert entity_detail["data"]["selected_entity_groups"] == "Expert Entity Groups"
    assert "apply_entity_detail_profile" not in entity_detail["data"]
    assert "create" in entity_detail["description"].lower()
    assert "reloads" in entity_detail["description"].lower()
    assert "simple" in entity_detail["data_description"]["entity_detail_level"].lower()
    assert "creates" in entity_detail["data_description"]["entity_detail_level"].lower()
    assert (
        "expert"
        in entity_detail["data_description"]["selected_entity_groups"].lower()
    )
    compact_migration = strings["options"]["step"]["compact_migration"]
    assert (
        compact_migration["data"]["confirm_compact_migration"]
        == "Remove Legacy Entities"
    )
    assert "{will_remove}" in compact_migration["description"]
    assert "{will_remain}" in compact_migration["description"]
    assert "{before_count}" in compact_migration["description"]
    assert "{after_count}" in compact_migration["description"]
    assert "customized" in compact_migration["description"].lower()
    dashboard = strings["options"]["step"]["dashboard"]
    assert dashboard["data"]["dashboard_layout"] == "Dashboard Layout"
    assert (
        dashboard["data"]["apply_entity_detail_profile"]
        == "Match Entity Detail Level To Layout"
    )
    assert dashboard["data"]["remove_dashboard"] == "Remove Existing Dashboard"
    assert "summary" in dashboard["data_description"]["dashboard_layout"].lower()
    assert (
        "save a matching entity detail level"
        in dashboard["data_description"]["apply_entity_detail_profile"].lower()
    )
    assert "reloads" in dashboard["data_description"][
        "apply_entity_detail_profile"
    ].lower()
    assert (
        "instead of creating or updating"
        in dashboard["data_description"]["remove_dashboard"].lower()
    )
    assert (
        "dashboard_layout_requires_higher_entity_detail"
        in strings["options"]["error"]
    )


def test_mains_and_utility_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))

    for section in ("config", "options"):
        utility_data = strings[section]["step"]["utility"]["data"]
        utility_descriptions = strings[section]["step"]["utility"][
            "data_description"
        ]
        assert utility_data == EXPECTED_UTILITY_LABELS
        assert utility_descriptions.keys() == EXPECTED_UTILITY_LABELS.keys()
        assert all("_" not in label for label in utility_data.values())
        assert all(
            description.endswith(".") for description in utility_descriptions.values()
        )
        assert "opower" in strings[section]["step"]["utility"]["description"].lower()
        assert "optional" in strings[section]["step"]["utility"]["description"].lower()
        assert "sum" in utility_descriptions["measured_energy_entities"].lower()

    mains_data = strings["options"]["step"]["mains"]["data"]
    mains_descriptions = strings["options"]["step"]["mains"]["data_description"]
    assert mains_data == EXPECTED_MAINS_LABELS
    assert mains_descriptions.keys() == EXPECTED_MAINS_LABELS.keys()
    assert "experimental" in mains_descriptions["enable_experimental_nilm"].lower()
    assert "optional" in mains_descriptions["mains_source_entities"].lower()
    assert "mains nilm" in mains_descriptions["mains_source_entities"].lower()
    assert "known loads" in mains_descriptions["known_load_circuits"].lower()


def test_advanced_settings_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    picker_step = strings["options"]["step"]["select_advanced_circuit"]
    settings_step = strings["options"]["step"]["advanced_settings"]
    section_data = {}
    section_descriptions = {}
    section_labels = {}
    for key, value in settings_step["sections"].items():
        section_labels[key] = value["name"]
        section_data.update(value["data"])
        section_descriptions.update(value["data_description"])

    assert picker_step["data"] == EXPECTED_ADVANCED_CIRCUIT_LABELS
    assert picker_step["data_description"].keys() == (
        EXPECTED_ADVANCED_CIRCUIT_LABELS.keys()
    )
    assert settings_step["data"] == {
        "reset_advanced_settings_to_defaults": (
            "Reset All Advanced Circuit Settings to Default"
        )
    }
    assert settings_step["data_description"] == {
        "reset_advanced_settings_to_defaults": (
            "Turn this on when saving to remove all custom advanced settings "
            "for this circuit."
        )
    }
    assert section_labels == EXPECTED_ADVANCED_SECTION_LABELS
    assert section_data == EXPECTED_ADVANCED_SETTINGS_LABELS
    assert section_descriptions.keys() == (
        EXPECTED_ADVANCED_SETTINGS_LABELS.keys()
    )
    assert settings_step["data"] == EXPECTED_ADVANCED_TOP_LEVEL_LABELS
    assert all("_" not in label for label in section_data.values())
    assert "selected_appliance" not in settings_step["description"]
    assert settings_step["description"].startswith("**{circuit_name}**")
    assert "service" not in settings_step["description"].lower()
    assert "appliance type" in settings_step["description"].lower()
    assert "operating detection source" in settings_step["description"].lower()
    assert "circuit mode" not in settings_step["description"].lower()
    assert "power flow" not in settings_step["description"].lower()
    assert " - " not in settings_step["description"]
    assert "only the sections that apply" in settings_step["description"].lower()
    assert "billing" in settings_step["description"].lower()
    assert "standby" in settings_step["description"].lower()
    billing_descriptions = settings_step["sections"]["billing_cost_settings"][
        "data_description"
    ]
    assert "time picker" in billing_descriptions["tou_start"].lower()
    assert "time picker" in billing_descriptions["tou_end"].lower()
    assert "choose" in billing_descriptions["tou_weekdays"].lower()
    assert "comma-separated" not in billing_descriptions["tou_weekdays"].lower()


def test_assignment_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))

    for section in ("config", "options"):
        data = strings[section]["step"]["assign"]["data"]
        descriptions = strings[section]["step"]["assign"]["data_description"]
        assert data == {
            "include_circuit": "Include Circuit",
            "remove_from_analysis": "Remove From Analysis",
            "included_sensors": "Included Sensors",
            "circuit_name": "Circuit Name",
            "appliance_profile": "Appliance Type",
            "circuit_retention_mode": "Circuit Retention",
        }
        assert descriptions.keys() == data.keys()
        assert all("_" not in label for label in data.values())
        assert all(description.endswith(".") for description in descriptions.values())
        assert "appliance" in descriptions["appliance_profile"].lower()
        assert "selected sensors" in descriptions["include_circuit"].lower()
        assert "source sensors stay" in descriptions["remove_from_analysis"].lower()
        assert "home assistant" in descriptions["remove_from_analysis"].lower()
        assert "unchecked" in descriptions["included_sensors"].lower()
        assert "diagnostic history" in descriptions["circuit_retention_mode"].lower()
        for days in ("14 days", "45 days", "180 days"):
            assert days in descriptions["circuit_retention_mode"]
        assert strings[section]["step"]["assign"]["title"] == (
            "Appliance Circuit Assignments"
        )


def test_assignment_picker_text_is_human_readable() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))

    data = strings["options"]["step"]["select_assignment"]["data"]
    descriptions = strings["options"]["step"]["select_assignment"]["data_description"]

    assert data == {"selected_assignment": "Assignment"}
    assert descriptions == {
        "selected_assignment": (
            "Choose the existing appliance or circuit assignment to edit."
        )
    }
    assert "x of" not in strings["options"]["step"]["select_assignment"][
        "description"
    ].lower()
    assert strings["options"]["step"]["select_assignment"]["title"] == (
        "Appliance Circuit Assignments"
    )


def test_runtime_english_translations_include_setup_and_options_text() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )

    for section, step in (
        ("config", "user"),
            ("config", "utility"),
            ("config", "assign"),
            ("config", "nilm"),
            ("options", "sources"),
            ("options", "mains"),
            ("options", "nilm"),
            ("options", "utility"),
            ("options", "entity_detail"),
            ("options", "compact_migration"),
        ("options", "select_assignment"),
        ("options", "select_advanced_circuit"),
        ("options", "advanced_settings"),
        ("options", "assign"),
    ):
        strings_step = strings[section]["step"][step]
        translated_step = translations[section]["step"][step]
        assert translated_step["data"] == strings_step["data"]
        assert translated_step["data_description"] == strings_step["data_description"]
        assert translated_step["title"] == strings_step["title"]
        assert translated_step["description"] == strings_step["description"]
        if "sections" in strings_step:
            assert translated_step["sections"] == strings_step["sections"]

    strings_init = strings["options"]["step"]["init"]
    translated_init = translations["options"]["step"]["init"]
    assert translated_init["title"] == strings_init["title"]
    assert translated_init["description"] == strings_init["description"]
    assert translated_init["menu_options"] == strings_init["menu_options"]


def test_config_flow_descriptions_do_not_show_non_actionable_mapping_suggestions() -> (
    None
):
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )

    for payload in (strings, translations):
        descriptions = (
            payload["config"]["step"]["user"]["description"],
            payload["config"]["step"]["utility"]["description"],
            payload["options"]["step"]["init"]["description"],
            payload["options"]["step"]["sources"]["description"],
            payload["options"]["step"]["mains"]["description"],
            payload["options"]["step"]["utility"]["description"],
        )
        for description in descriptions:
            assert "{mapping_suggestions}" not in description
            assert "dual-phase channel pairs" not in description.lower()


def test_service_fields_have_human_readable_names_and_descriptions() -> None:
    services = yaml.safe_load((INTEGRATION_DIR / "services.yaml").read_text())

    for service in services.values():
        for field_name, field in service.get("fields", {}).items():
            assert field["name"] == EXPECTED_SERVICE_FIELD_NAMES[field_name]
            assert "_" not in field["name"]
            assert field["description"].endswith(".")
            assert 20 <= len(field["description"]) <= 160


def test_services_are_labeled_as_advanced_script_paths() -> None:
    services = yaml.safe_load((INTEGRATION_DIR / "services.yaml").read_text())

    for service_name, service in services.items():
        description = service["description"]
        assert description.startswith("Advanced/script action:"), service_name
        assert "normal user path" in description.lower(), service_name


def test_maintenance_switch_label_describes_mode_not_power_control() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )

    for payload in (strings, translations):
        label = payload["entity"]["switch"]["maintenance"]["name"]
        assert label == "Maintenance mode"


def test_readme_documents_normal_user_action_paths() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_text = " ".join(readme_text.split())

    assert "## Normal User Paths" in readme_text
    for phrase in (
        "Circuit action -> button/select/number entity",
        "Alert action -> evidence panel button",
        "NILM signature action -> NILM/evidence panel button",
        "Recommendation action -> Suggested Settings UI button",
        "Setup/data-quality fix -> Repairs flow",
    ):
        assert phrase in normalized_text


def test_sensitivity_vocabulary_is_quiet_balanced_sensitive() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )

    combined = "\n".join(
        [
            readme_text,
            json.dumps(strings, sort_keys=True),
            json.dumps(translations, sort_keys=True),
        ]
    )
    assert "Quiet" in combined
    assert "Balanced" in combined
    assert "Sensitive" in combined
    assert "Low is quieter" not in combined
    assert "Standard is balanced" not in combined
    assert "High is more responsive" not in combined
    assert "`standard`, `high`, `low`" not in readme_text


def test_cost_rate_selectors_allow_any_decimal_precision() -> None:
    services = yaml.safe_load((INTEGRATION_DIR / "services.yaml").read_text())
    fields = services["set_cost_settings"]["fields"]

    assert fields["default_rate_per_kwh"]["selector"]["number"]["step"] == "any"
    assert fields["tou_rate_per_kwh"]["selector"]["number"]["step"] == "any"


def test_dashboard_example_prioritizes_summary_cards_over_sensor_lists() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    cards = _dashboard_cards(dashboard)
    card_types = [card.get("type") for card in cards]

    assert card_types.count("entities") <= 10
    assert "button" in card_types
    assert "gauge" in card_types
    assert "glance" in card_types
    assert "history-graph" in card_types
    assert "statistics-graph" in card_types
    assert "tile" in card_types
    assert any(card.get("title") == "Appliance Status" for card in cards)
    statistics_cards = [
        card for card in cards if card.get("type") == "statistics-graph"
    ]
    assert statistics_cards
    assert all(card.get("days_to_show") == 7 for card in statistics_cards)
    assert all(card.get("period") == "day" for card in statistics_cards)


def test_dashboard_example_graphs_daily_energy_totals_with_max_stat() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    statistics_cards = [
        card
        for card in _dashboard_cards(dashboard)
        if card.get("type") == "statistics-graph"
        and any(
            str(
                entity.get("entity", "") if isinstance(entity, dict) else entity
            ).endswith("_daily_energy_usage")
            for entity in card.get("entities", [])
        )
    ]

    assert statistics_cards
    assert all(card.get("stat_types") == ["max"] for card in statistics_cards)


def test_dashboard_example_omits_hidden_default_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
    )

    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    refs = set(_dashboard_entity_refs(dashboard_text))
    intentional_feature_panel_refs = {
        "sensor.mains_nilm_balance_power",
        "sensor.mains_nilm_monitored_coverage",
        "sensor.mains_nilm_monitored_power",
        "sensor.mains_nilm_nilm_discovered_signatures",
        "sensor.mains_nilm_nilm_unknown_loads",
        "sensor.mains_nilm_solar_flow_status",
        "sensor.mains_nilm_solar_surplus_power",
        "sensor.mains_nilm_utility_comparison_difference",
        "sensor.mains_nilm_utility_comparison_status",
        "sensor.water_heater_water_flow_correlation",
        "sensor.washer_water_flow_correlation",
    }
    hidden_sensor_keys = {
        description.key
        for description in SENSOR_DESCRIPTIONS
        if description.entity_registry_visible_default is False
    }
    hidden_binary_sensor_keys = {
        description.key
        for description in BINARY_SENSOR_DESCRIPTIONS
        if description.entity_registry_visible_default is False
    }

    hidden_refs = sorted(
        ref
        for ref in refs
        if ref not in intentional_feature_panel_refs
        if (
            ref.startswith("sensor.")
            and any(ref.endswith(f"_{key}") for key in hidden_sensor_keys)
        )
        or (
            ref.startswith("binary_sensor.")
            and any(ref.endswith(f"_{key}") for key in hidden_binary_sensor_keys)
        )
    )

    assert hidden_refs == []


def test_dashboard_example_is_appliance_first_and_explains_energy_tracking() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text(
        encoding="utf-8"
    )
    dashboard = yaml.safe_load(dashboard_text)
    section_titles = {
        section.get("title")
        for section in _dashboard_sections(dashboard)
    }

    assert {
        "Appliance Status",
        "Mains, Solar, and NILM",
        "Energy Tracking",
        "HVAC Weather Context",
    } <= section_titles
    assert section_titles.isdisjoint(
        {
            "Needs attention",
            "Appliance overview",
            "Energy tracking",
            "Power quality detail",
            "Alert evidence",
            "NILM Unknown Loads",
            "Settings And Exports",
            "Power Quality Detail",
            "Alert Philosophy",
        }
    )
    assert [section.get("title") for section in _dashboard_sections(dashboard)][:2] == [
        "Appliance Status",
        "Mains, Solar, and NILM",
    ]
    assert "Waiting For Energy Change" in dashboard_text
    assert "sensor.hvac_activity_summary" in dashboard_text
    assert "sensor.hvac_electrical_health" in dashboard_text
    assert "sensor.hvac_energy_summary" in dashboard_text
    assert "sensor.washer_activity_summary" in dashboard_text
    assert "sensor.dryer_activity_summary" in dashboard_text
    assert "sensor.hvac_daily_energy_usage" in dashboard_text
    assert "sensor.water_heater_energy_summary" in dashboard_text
    assert "sensor.mains_nilm_activity_summary" in dashboard_text

    appliance_overview = yaml.safe_dump(
        _dashboard_section(dashboard, "Appliance Status")
    )
    for appliance in (
        "Refrigerator",
        "HVAC",
        "Water heater",
        "Pool pump",
        "Washer",
        "Dryer",
        "Car charger",
    ):
        assert appliance in appliance_overview
    for circuit in (
        "refrigerator",
        "hvac",
        "water_heater",
        "pool_pump",
        "washer",
        "dryer",
        "car_charger",
    ):
        assert f"sensor.{circuit}_activity_summary" in appliance_overview
        assert f"sensor.{circuit}_electrical_health" in appliance_overview
        assert f"sensor.{circuit}_energy_summary" in appliance_overview
        assert f"sensor.{circuit}_daily_energy_usage" in appliance_overview
        assert f"sensor.{circuit}_health_summary" not in appliance_overview

    energy_tracking = yaml.safe_dump(_dashboard_section(dashboard, "Energy Tracking"))
    assert "Electrical health rollups" in energy_tracking
    assert "sensor.hvac_electrical_health" in energy_tracking
    assert "sensor.mains_nilm_electrical_health" in energy_tracking


def test_dashboard_example_removes_static_alert_evidence_view() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    dashboard = yaml.safe_load(dashboard_text)
    views = _dashboard_views(dashboard)
    refs = set(_dashboard_entity_refs(dashboard_text))

    assert len(views) == 1
    assert views[0].get("path") == "overview"
    assert all(view.get("path") != "alert-evidence" for view in views)
    assert "title: Alert Evidence" not in dashboard_text
    assert "path: alert-evidence" not in dashboard_text
    assert "Open from notifications" not in dashboard_text
    assert refs.isdisjoint(
        {
        "sensor.hvac_alert_evidence",
        "sensor.hvac_leg_imbalance",
        "sensor.hvac_power_quality_score",
        "sensor.hvac_reactive_power_drift",
        "sensor.hvac_power_factor_drift",
        }
    )


def test_dashboard_example_uses_current_mains_nilm_entity_ids() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()

    stale_entities = {
        "sensor.mains_health_summary",
        "sensor.mains_learning_progress",
        "sensor.mains_anomaly_score",
        "sensor.mains_alert_evidence",
        "sensor.mains_recent_activity",
        "sensor.mains_balance_power",
        "sensor.mains_monitored_power",
        "sensor.mains_monitored_coverage",
        "sensor.mains_balance_status",
        "sensor.mains_demand_peak_status",
        "sensor.mains_readiness",
        "sensor.mains_nilm_discovered_signatures",
        "sensor.mains_nilm_unmatched_load_percentage",
        "sensor.mains_nilm_topology_status",
        "binary_sensor.mains_maintenance",
    }

    assert stale_entities.isdisjoint(set(_dashboard_entity_refs(dashboard_text)))
    assert "sensor.mains_nilm_activity_summary" in dashboard_text
    assert "sensor.mains_nilm_electrical_health" in dashboard_text
    assert "sensor.mains_nilm_nilm_unknown_loads" in dashboard_text
    assert "Open NILM Graph & Review" in dashboard_text
    assert "/circuitsetup-energy-analyzer-evidence?circuit_id=mains" in dashboard_text


def test_dashboard_example_explains_known_load_share_as_primary_mains_gauge() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    cards = _dashboard_cards(dashboard)
    mains_section = yaml.safe_dump(
        _dashboard_section(dashboard, "Mains, Solar, and NILM")
    )
    coverage_gauges = [
        card
        for card in cards
        if card.get("type") == "gauge"
        and card.get("entity") == "sensor.mains_nilm_monitored_coverage"
    ]
    load_match_cards = [
        card for card in cards if card.get("title") == "Mains Load Match"
    ]

    assert len(coverage_gauges) == 1
    assert coverage_gauges[0]["name"] == "Known Load Share"
    assert len(load_match_cards) == 1
    assert load_match_cards[0]["type"] == "entities"
    assert {
        row["entity"]: row["name"]
        for row in load_match_cards[0]["entities"]
    } == {
        "sensor.mains_nilm_monitored_power": "Known Appliance Load",
        "sensor.mains_nilm_balance_power": "Unassigned Mains Load",
        "sensor.mains_nilm_monitored_coverage": "Known Load Share",
    }
    assert "Mains Load Match" in mains_section
    assert "Known Load Share" in mains_section
    assert "how much of current mains power is explained" in mains_section
    assert "sensor.mains_nilm_nilm_unmatched_load_percentage" not in mains_section


def test_dashboard_example_places_detail_panels_under_related_sections() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    dashboard = yaml.safe_load(dashboard_text)

    section_titles = [
        section.get("title") for section in _dashboard_sections(dashboard)
    ]
    assert section_titles == [
        "Appliance Status",
        "Mains, Solar, and NILM",
        "Energy Tracking",
        "HVAC Weather Context",
    ]

    mains_section = yaml.safe_dump(
        _dashboard_section(dashboard, "Mains, Solar, and NILM")
    )
    energy_section = yaml.safe_dump(_dashboard_section(dashboard, "Energy Tracking"))
    weather_section = yaml.safe_dump(
        _dashboard_section(dashboard, "HVAC Weather Context")
    )

    assert "Unknown Load Inventory" in mains_section
    assert "Unknown load signals" in mains_section
    assert "Settings and exports" in energy_section
    assert "Electrical health rollups" in energy_section
    assert "Notifications and repairs" in weather_section
    assert "title: NILM Unknown Loads" not in dashboard_text
    assert "title: Settings And Exports" not in dashboard_text
    assert "title: Power Quality Detail" not in dashboard_text


def test_dashboard_example_graphs_hvac_energy_with_outdoor_temperature() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    hvac_section = _dashboard_section(dashboard, "HVAC Weather Context")
    hvac_cards = _dashboard_cards(hvac_section)
    graph_cards = [
        card
        for card in hvac_cards
        if card.get("type") == "statistics-graph"
        and card.get("title") == "HVAC daily energy and outdoor temperature"
    ]

    assert graph_cards
    assert graph_cards[0]["entities"] == [
        {"entity": "sensor.hvac_daily_energy_usage", "name": "Daily Energy Usage"},
        {"entity": "sensor.outdoor_temperature", "name": "Outdoor Temperature"},
    ]


def test_dashboard_example_covers_configurable_analyzer_surfaces() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    refs = set(_dashboard_entity_refs(dashboard_text))

    expected_entities = {
        "sensor.refrigerator_activity_summary",
        "sensor.refrigerator_electrical_health",
        "sensor.refrigerator_energy_summary",
        "sensor.refrigerator_daily_energy_usage",
        "sensor.hvac_activity_summary",
        "sensor.hvac_electrical_health",
        "sensor.hvac_energy_summary",
        "sensor.hvac_daily_energy_usage",
        "sensor.hvac_weather_context",
        "sensor.outdoor_temperature",
        "sensor.water_heater_activity_summary",
        "sensor.water_heater_electrical_health",
        "sensor.water_heater_energy_summary",
        "sensor.water_heater_daily_energy_usage",
        "sensor.pool_pump_activity_summary",
        "sensor.pool_pump_electrical_health",
        "sensor.pool_pump_energy_summary",
        "sensor.pool_pump_daily_energy_usage",
        "sensor.washer_activity_summary",
        "sensor.washer_electrical_health",
        "sensor.washer_energy_summary",
        "sensor.washer_daily_energy_usage",
        "sensor.dryer_activity_summary",
        "sensor.dryer_electrical_health",
        "sensor.dryer_energy_summary",
        "sensor.dryer_daily_energy_usage",
        "sensor.car_charger_activity_summary",
        "sensor.car_charger_electrical_health",
        "sensor.car_charger_energy_summary",
        "sensor.car_charger_daily_energy_usage",
        "sensor.mains_nilm_activity_summary",
        "sensor.mains_nilm_electrical_health",
        "sensor.mains_nilm_energy_summary",
        "sensor.mains_nilm_daily_energy_usage",
        "sensor.mains_nilm_balance_power",
        "sensor.mains_nilm_monitored_coverage",
        "sensor.mains_nilm_monitored_power",
        "sensor.mains_nilm_nilm_unknown_loads",
        "sensor.mains_nilm_nilm_discovered_signatures",
        "sensor.mains_nilm_solar_flow_status",
        "sensor.mains_nilm_solar_surplus_power",
        "sensor.mains_nilm_utility_comparison_difference",
        "sensor.mains_nilm_utility_comparison_status",
        "sensor.water_heater_water_flow_correlation",
        "sensor.washer_water_flow_correlation",
    }
    assert expected_entities <= refs
    assert "sensor.hvac_outdoor_temperature" not in refs
    assert "sensor.hvac_run_cycle_runtime" not in refs
    assert "sensor.hvac_run_cycle_duty_cycle" not in refs
    assert not any(ref.endswith("_health_summary") for ref in refs)
    assert not any(ref.startswith("binary_sensor.") for ref in refs)
    assert "circuitsetup_energy_analyzer.export_history_csv" in dashboard_text
    assert "Alert Philosophy" in dashboard_text
    assert "Notifications and repairs" in dashboard_text


def test_dashboard_example_keeps_safety_notice_near_alert_philosophy() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    normalized_text = " ".join(dashboard_text.split())

    assert "Demand and capacity findings are" in normalized_text
    assert "operational evidence from energy measurements" in normalized_text
    assert "not electrical safety verification" in normalized_text


def test_dashboard_example_wraps_optional_feature_cards_conditionally() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    refs = _dashboard_entity_refs_with_conditional_context(dashboard)
    optional_entities = {
        "sensor.hvac_weather_context",
        "sensor.outdoor_temperature",
        "sensor.mains_nilm_solar_flow_status",
        "sensor.mains_nilm_solar_surplus_power",
        "sensor.mains_nilm_utility_comparison_difference",
        "sensor.mains_nilm_utility_comparison_status",
    }

    assert optional_entities <= set(refs)
    assert all(refs[entity] for entity in optional_entities)


def test_readme_describes_summary_first_diagnostic_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Summary-First Diagnostics" in readme
    assert "Health Summary" in readme
    assert "Activity Summary" in readme
    assert "Electrical Health" in readme
    assert "Energy Summary" in readme
    assert "advanced detail" in readme.lower()
    assert "Power-quality evidence and metric/leg status" in readme
    assert "Expert creates only the diagnostic or graph groups you select" in readme
    assert "Expert Entity Groups" in readme


def test_readme_explains_running_observation_and_alert_distinction() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "Running is the current operating state used for automations." in readme
    )
    assert (
        "Observation recorded means the analyzer noticed something unusual" in readme
    )
    assert (
        "Possible issue means repeated evidence crossed the alert threshold."
        in readme
    )


def test_alert_blueprint_is_user_friendly_and_actionable() -> None:
    blueprint_path = (
        ROOT
        / "blueprints"
        / "automation"
        / "circuitsetup_energy_analyzer"
        / "energy_alert_notification.yaml"
    )
    blueprint_text = blueprint_path.read_text(encoding="utf-8")

    assert "CircuitSetup Energy Analyzer Alerts" in blueprint_text
    assert "persistent_notification.create" in blueprint_text
    assert "selector:" in blueprint_text
    assert "entity:" in blueprint_text
    assert "action:" in blueprint_text
    assert "possible issue" in blueprint_text.lower()
    assert "alert_entities:" in blueprint_text
    assert "alert_actions:" in blueprint_text
    assert "evidence_path" in blueprint_text
    assert "Open evidence graph" in blueprint_text
    assert "clickAction" in blueprint_text
    assert "url:" in blueprint_text


def test_alert_blueprint_evidence_path_renders_clean_url() -> None:
    from jinja2 import Template

    class BlueprintLoader(yaml.SafeLoader):
        pass

    BlueprintLoader.add_constructor(
        "!input",
        lambda loader, node: loader.construct_scalar(node),
    )
    blueprint_path = (
        ROOT
        / "blueprints"
        / "automation"
        / "circuitsetup_energy_analyzer"
        / "energy_alert_notification.yaml"
    )
    blueprint = yaml.load(blueprint_path.read_text(encoding="utf-8"), BlueprintLoader)
    evidence_template = Template(blueprint["variables"]["evidence_path"])

    configured_path = evidence_template.render(
        trigger={
            "to_state": {
                "attributes": {
                    "evidence_path": "/custom-dashboard/alert-evidence?alert_id=1"
                }
            }
        }
    )
    fallback_path = evidence_template.render(trigger={"to_state": None})

    assert configured_path == "/custom-dashboard/alert-evidence?alert_id=1"
    assert fallback_path == "/circuitsetup-energy-analyzer-evidence"


def test_alert_blueprint_matches_current_summary_alert_states() -> None:
    from jinja2 import Template

    class BlueprintLoader(yaml.SafeLoader):
        pass

    BlueprintLoader.add_constructor(
        "!input",
        lambda loader, node: loader.construct_scalar(node),
    )
    blueprint_path = (
        ROOT
        / "blueprints"
        / "automation"
        / "circuitsetup_energy_analyzer"
        / "energy_alert_notification.yaml"
    )
    blueprint = yaml.load(blueprint_path.read_text(encoding="utf-8"), BlueprintLoader)
    alert_input = blueprint["blueprint"]["input"]["alert_states"]
    defaults = alert_input["default"]
    options = {
        option["value"]
        for option in alert_input["selector"]["select"]["options"]
    }

    assert "possible_issue" in defaults
    assert {
        "possible_imbalance",
        "possible_metric_mismatch",
        "possible_power_quality_change",
        "high_usage",
        "watch",
        "needs_data",
        "needs_energy_data",
        "needs_metrics",
        "mixed_observation",
        "nilm_review",
    } <= options

    state_template = Template(blueprint["variables"]["alert_state_normalized"])
    condition_template = Template(blueprint["condition"][0]["value_template"])

    def condition_matches(state: str, selected_states: list[str]) -> bool:
        trigger = {"to_state": {"state": state}}
        alert_state_normalized = state_template.render(trigger=trigger).strip()
        rendered = condition_template.render(
            trigger=trigger,
            alert_state_normalized=alert_state_normalized,
            alert_states=selected_states,
        )
        return rendered.strip() == "True"

    assert condition_matches("Possible issue", defaults)
    assert condition_matches("Possible issue: Cycle Duration", defaults)
    assert condition_matches("High Usage", defaults)
    assert condition_matches("Watch", defaults)
    assert not condition_matches("Needs data", defaults)
    assert condition_matches("Needs data", ["needs_data"])
    assert condition_matches("Needs Metrics", ["needs_metrics"])


def test_dynamic_alert_evidence_panel_asset_is_user_facing() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    assert asset_path.exists()
    asset = asset_path.read_text(encoding="utf-8")

    for expected in (
        'customElements.get("circuitsetup-energy-analyzer-panel")',
        'customElements.define("circuitsetup-energy-analyzer-panel"',
        "URLSearchParams",
        "/api/circuitsetup_energy_analyzer/alert_evidence",
        "history/period",
        "/api/circuitsetup_energy_analyzer/nilm_workspace",
        "NILM_WORKSPACE_CALL_API_PATH",
        "_loadNilmWorkspace",
        "_renderNilmWorkspace",
        "NILM Workspace",
        "Known Load Overlays",
        "Estimated Appliances",
        "Appliance Assignments",
        "estimated_daily_energy",
        "model_status",
        "Validation",
        "False positives",
        "False negatives",
        "Median power error",
        "Energy error",
        "Prediction Preview",
        "Ground Truth Sensor",
        "ground_truth_entity_id",
        "_renderNilmValidation",
        "NILM Sessions",
        "Manual Labels",
        "NILM Signatures",
        "_renderNilmLabelIntervals",
        "_renderNilmAssignmentActions",
        "_callNilmWorkspaceItemAction",
        "_callNilmLabelIntervalAction",
        "data-nilm-label-interval-action",
        "data-nilm-session-action",
        "data-nilm-assignment-action",
        "data-nilm-assignment-merge-target",
        "Assign Appliance",
        "Publish Entities",
        "Disable Publishing",
        "Retire",
        "Rename Appliance",
        "Change Type",
        "Merge Assignment",
        "Confirm Appliance",
        "Wrong Appliance",
        "Save Interval",
        "Generate From Sensor",
        "Delete Label",
        "datetime-local",
        "Saved interval label:",
        "Deleted interval label.",
        "MAX_CHART_POINTS_PER_SERIES",
        "_boundedChartPoints",
        "Could not load NILM workspace history",
        'callService("circuitsetup_energy_analyzer"',
        "acknowledge_alert",
        "mark_alert_expected",
        "mark_alert_unhelpful",
        "pause_alerts",
        "start_maintenance",
        "relearn_baseline",
        "apply_setting_recommendation",
        "dismiss_setting_recommendation",
        "Alert evidence chart",
        "data-nilm-chart-select",
        "_startNilmChartSelection",
        "_chartEventTime",
        "pointerdown",
        "<svg",
        "No history samples",
        "Matched alert",
        "Latest evidence for circuit",
        "Circuit actions available",
        "Historical alert not found",
        "Observed",
        "Baseline",
        "feature_name",
        "_friendlyFeature",
        "Safety Notice",
        "alert.safety_notice",
        "Default:",
        "Expected effect:",
        "Evidence:",
        "Preview evidence",
        "recommendation.actions.preview",
        "nilm-label-field",
        "_renderNilmLabelField",
        "_renderNilmSignatureReview",
        "_nilmLabelDrafts",
        "_rememberNilmLabelDraft",
        "Enter a label for this NILM signature before saving.",
        "Save Label",
        "merge-target-chip",
        "_nilmMergeTargetChip",
        "_selectNilmMergeTarget",
        "data-nilm-merge-target",
        "signature.display_label",
        "recommendation.display_label",
        "unavailable_reason",
        "action-reason",
        "_actionDisabled",
        "_guardActionCall",
        "Action unavailable",
        "Home Assistant service calls are not available",
        "_friendlyEntityName",
        "friendly_name",
        "item.name",
    ):
        assert expected in asset
    assert '${this._metric("Feature", alert.feature)}' not in asset
    assert "iframe" not in asset
    assert "Graph entities" not in asset
    assert "Graphed Sources" not in asset
    assert "NILM Review" not in asset
    assert "_renderNilmActions" not in asset
    assert "_entityList" not in asset
    assert "window.prompt" not in asset
    assert "Label this NILM signature" not in asset
    assert "<select id=\"nilm_merge_target_" not in asset
    assert (
        'entities.map((entityId) => `<code>${this._escape(entityId)}</code>`)'
        not in asset
    )
    assert "Source Entities" not in asset
    assert "source-entity-chip" not in asset
    assert "data-source-entity" not in asset
    assert "data-nilm-workspace-action" not in asset
    assert "_openSourceEntity" not in asset
    assert "${this._escape(item.entity_id)}" not in asset
    assert "this._escape(signature.signature_id)}</strong>" not in asset
    assert "recommendation.recommendation_id || \"Recommendation\"" not in asset
    assert "deny_setting_recommendation" not in asset
    assert '_recommendationActionButton(recommendation, index, "deny"' not in asset


def test_dynamic_alert_evidence_panel_hides_unavailable_recommendation_actions() -> (
    None
):
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_shouldHideUnavailableRecommendationAction(actionKey, action)" in asset
    assert 'if (!action) {\n      return "";' in asset
    assert (
        "action.enabled === false"
        " && this._shouldHideUnavailableRecommendationAction(actionKey, action)"
    ) in asset


def test_dynamic_alert_evidence_panel_separates_applied_recommendations() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_recommendationsByStatus(recommendations)" in asset
    assert "_renderRecommendationSection(" in asset
    assert '"Suggested Settings", grouped.pending' in asset
    assert '"Applied Suggested Settings", grouped.applied' in asset
    assert 'status === "applied"' in asset
    assert "originalIndex" in asset


def test_dynamic_alert_evidence_panel_formats_setting_recommendation_rows() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_recommendationValueRows(recommendation)" in asset
    assert 'String((recommendation && recommendation.status) || "pending")' in asset
    assert (
        "const currentValue = applied && recommendation.suggested_value !== "
        "undefined ? recommendation.suggested_value : recommendation.current_value;"
    ) in asset
    assert (
        "const suggestedValue = applied ? undefined : recommendation.suggested_value;"
        in asset
    )
    assert '${this._escape(recommendation.feature || "Suggested setting")}' not in asset


def test_dynamic_alert_evidence_panel_previews_recommendation_evidence() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_renderSelectedRecommendationEvidence()" in asset
    assert "selected_recommendation" in asset
    assert "Recommendation Evidence" in asset
    assert "Previewing evidence for" in asset


def test_dynamic_alert_evidence_panel_scrolls_after_messages() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_renderAndScrollToTop()" in asset
    assert "_scrollToTop()" in asset
    assert "requestAnimationFrame" in asset
    assert "window.scrollTo({ top: 0" in asset


def test_dynamic_alert_evidence_panel_preserves_nilm_label_drafts() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "this._nilmLabelDrafts = new Map();" in asset
    assert (
        "input.addEventListener(\"input\", () => this._rememberNilmLabelDraft("
        in asset
    )
    assert "this._nilmLabelDraftKey(signature)" in asset
    assert "this._nilmLabelDrafts.get(draftKey)" in asset


def test_dynamic_alert_evidence_panel_reloads_when_notification_url_changes() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    for expected in (
        "circuitsetup-energy-analyzer-route-change",
        "window.addEventListener",
        "history.pushState",
        "history.replaceState",
        "popstate",
        "_routeKey",
        "_loadedRouteKey",
        "_evidenceRequestId",
    ):
        assert expected in asset


def test_dynamic_alert_evidence_panel_action_and_time_contracts() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    for expected in (
        "_actionRefreshRouteKey(actionKey)",
        'routeUrl.searchParams.delete("alert_id")',
        'this._loadEvidence({ routeKey: this._actionRefreshRouteKey(actionKey) })',
        "_formatDateTime(value)",
        "${year}-${month}-${day} ${hour12}:${minute}${suffix}",
        "_chartSvg(series, alert)",
        "Date.parse(alert.graph_window_start)",
        "Date.parse(alert.graph_window_end)",
        "Action complete",
        "Saved label:",
        "Review state:",
    ):
        assert expected in asset
    assert "Evidence Window" not in asset


def test_dynamic_alert_evidence_panel_formats_iso_offsets_as_local_time() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "new Date(value)" in asset
    assert "raw.match(/^(\\d{4})-(\\d{2})-(\\d{2})T" not in asset
    assert "const year = String(date.getFullYear());" in asset
    assert (
        "return this._formatDateParts(year, month, day, date.getHours(), minute);"
        in asset
    )


def test_daily_action_services_document_entity_targets() -> None:
    services = yaml.safe_load(
        (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for service_name in (
        "relearn_baseline",
        "pause_alerts",
        "start_maintenance",
        "end_maintenance",
        "set_circuit_sensitivity",
        "set_energy_goal_settings",
    ):
        fields = services[service_name]["fields"]
        assert fields["circuit_id"]["required"] is False
        assert fields["entity_id"]["required"] is False
        assert "analyzer entity" in fields["entity_id"]["description"]
        assert fields["entity_id"]["selector"] == {
            "entity": {
                "domain": [
                    "sensor",
                    "binary_sensor",
                    "button",
                    "select",
                    "number",
                    "switch",
                ]
            }
        }


def test_advanced_circuit_services_document_entity_targets() -> None:
    services = yaml.safe_load(
        (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for service_name in (
        "export_diagnostics",
        "export_history_csv",
        "set_energy_usage_settings",
        "set_energy_goal_settings",
        "set_activity_alert_settings",
        "set_billing_cycle_settings",
        "set_cost_settings",
        "set_demand_settings",
        "set_capacity_settings",
        "set_leg_imbalance_settings",
        "set_metric_consistency_settings",
        "set_mains_balance_settings",
        "set_solar_flow_settings",
        "set_standby_settings",
        "set_utility_comparison_settings",
        "recalculate_setting_recommendations",
    ):
        fields = services[service_name]["fields"]
        assert fields["circuit_id"]["required"] is False
        assert fields["entity_id"]["required"] is False
        assert "analyzer entity" in fields["entity_id"]["description"]


def test_nilm_signature_services_document_entity_targets() -> None:
    services = yaml.safe_load(
        (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for service_name in (
        "label_nilm_signature",
        "ignore_nilm_signature",
        "mark_nilm_signature_expected",
        "merge_nilm_signatures",
        "label_nilm_interval",
        "delete_nilm_label_interval",
        "generate_nilm_sensor_label_intervals",
        "assign_signature_to_appliance",
        "assign_session_to_appliance",
        "assign_interval_to_appliance",
        "validate_nilm_session",
        "reject_nilm_session",
        "validate_nilm_assignment_history",
        "rename_nilm_appliance",
        "change_nilm_appliance_profile",
        "merge_nilm_assignments",
        "publish_nilm_appliance_assignment",
        "unpublish_nilm_appliance_assignment",
        "retire_nilm_appliance_assignment",
    ):
        fields = services[service_name]["fields"]
        assert fields["circuit_id"]["required"] is False
        assert fields["entity_id"]["required"] is False
        assert "analyzer entity" in fields["entity_id"]["description"]


def test_alert_feedback_services_document_entity_targets() -> None:
    services = yaml.safe_load(
        (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for service_name in (
        "acknowledge_alert",
        "mark_alert_expected",
        "mark_alert_unhelpful",
    ):
        fields = services[service_name]["fields"]
        assert fields["alert_id"]["required"] is False
        assert fields["entity_id"]["required"] is False
        assert "exactly one active alert" in fields["alert_id"]["description"]
        assert "exactly one active alert" in fields["entity_id"]["description"]


def test_recommendation_action_services_document_entity_targets() -> None:
    services = yaml.safe_load(
        (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for service_name in (
        "apply_setting_recommendation",
        "deny_setting_recommendation",
        "dismiss_setting_recommendation",
        "undo_setting_recommendation",
        "reset_setting_recommendation",
    ):
        fields = services[service_name]["fields"]
        assert fields["recommendation_id"]["required"] is False
        assert fields["entity_id"]["required"] is False
        assert "analyzer entity" in fields["entity_id"]["description"]
        assert "exactly one pending recommendation" in fields[
            "entity_id"
        ]["description"]


def test_readme_includes_status_glossary_for_machine_values() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Status Glossary" in readme_text
    for raw_status in (
        "missing_metrics",
        "not_dual_phase",
        "missing_mains",
        "inconsistent_export",
        "waiting_for_delta",
        "no_match",
        "projected_over_budget",
        "active_solar_supported",
    ):
        assert raw_status in readme_text
    assert "Missing Metrics" in readme_text
    assert "raw_status" in readme_text
    assert "status_explanation" in readme_text


def test_readme_describes_appliance_drilldown_pattern() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Appliance Drilldown Pattern" in readme_text
    for phrase in (
        "Appliance status card",
        "Appliance automations",
        "Energy tracking",
        "Electrical review",
        "Setup and data quality",
        "advanced diagnostic entities",
    ):
        assert phrase in readme_text


def test_setup_health_repairs_descriptions_include_circuit_next_step() -> None:
    translations = json.loads(
        (
            INTEGRATION_DIR / "translations" / "en.json"
        ).read_text(encoding="utf-8")
    )
    issues = translations["issues"]

    for key in (
        "missing_energy_source",
        "missing_mains_source",
        "missing_electrical_metrics",
        "check_ct_direction",
        "dual_phase_missing_leg",
        "missing_rain_context_source",
        "missing_water_flow_source",
        "utility_comparison_source_mismatch",
        "utility_comparison_missing_utility_source",
        "utility_comparison_missing_measured_source",
    ):
        description = issues[key]["description"]
        assert "{circuit_name}" in description
        assert "{recommended_action}" in description
        assert "{reason}" in description


def test_readme_includes_practical_usage_guide() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_text = " ".join(readme_text.split())

    assert "## Using The Integration" in readme_text
    for phrase in (
        "First-time setup checklist",
        "Classify circuits deliberately",
        "Use it day to day",
        "Configure the optional features you actually need",
        "Practical examples",
        "When an alert appears",
        "Common setup states",
    ):
        assert phrase in readme_text
    for phrase in (
        "Washer or dryer running automation",
        "Refrigerator monitoring",
        "HVAC or 240 V appliance review",
        "EV charger or high-current circuit",
        "Utility or Opower comparison",
    ):
        assert phrase in readme_text
    for phrase in (
        "do not need to enable every diagnostic entity",
        "let the analyzer learn for at least 7 days",
        "Appliance Circuit Assignments",
        "Advanced Circuit Settings",
        "Settings > Devices & services",
        "only shows settings that apply",
        "Running binary sensor",
        "status_explanation",
    ):
        assert phrase in normalized_text
    assert "Most options are set from Home Assistant Developer Tools > Actions" not in (
        readme_text
    )


def test_readme_explains_notification_evidence_graph_links() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_text = " ".join(readme_text.split())

    assert "Open evidence graph" in readme_text
    assert "Alert Evidence" in readme_text
    assert "evidence_path" in readme_text
    assert "graph_entities" in readme_text
    assert "dynamic Alert Evidence panel" in readme_text
    assert "Companion App" in readme_text
    assert "clickAction" in readme_text
    assert "/circuitsetup-energy-analyzer-evidence" in readme_text
    assert "appliance, mains, nilm, weather-context, and energy-overview cards" in (
        normalized_text.lower()
    )
    assert "dynamically selects graph entities" in normalized_text
    assert "docs/dashboard-example.yaml" in readme_text
    assert "Persistent notifications include a Markdown link" in normalized_text


def test_readme_explains_core_dashboard_sensors_and_zero_kwh() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Core Appliance Status Sensors" in readme_text
    assert "Daily Energy Usage can show 0 kWh for two different reasons" in readme_text
    assert "Waiting For Energy Change" in readme_text
    assert "waiting_for_delta" in readme_text
    assert "true zero usage" in readme_text
    assert "not observed a cumulative kWh increase" in readme_text


def test_readme_explains_generated_dashboard_controls() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "generated dashboard uses Home Assistant's current entity registry IDs" in (
        readme_text
    )
    assert "renamed analyzer entities are respected" in readme_text
    assert "matches the included example dashboard structure" in readme_text
    assert "does not add dropdown, switch, number, or button control cards" in (
        readme_text
    )
    assert "keeps each appliance card to four summary rows" in readme_text
    assert "Missing, disabled, or unavailable entities" in readme_text
    assert "Create Or Update Dashboard" in readme_text
    assert "Match Entity Detail Level To Layout" in readme_text
    assert "Remove Existing Dashboard" in readme_text
    assert "dashboard action still runs from Configure" in readme_text
    assert "**Expert**: Standard plus analyzer evidence links" in readme_text
    assert "does not add diagnostic/detail entity cards automatically" in readme_text
    assert "graph/detail cards for the Expert groups you selected" not in readme_text
    assert "button.circuitsetup_energy_analyzer_create_dashboard" not in readme_text
    assert "adds small action cards" not in readme_text


def test_readme_documents_compact_entity_model_and_migration() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Compact entity model" in readme_text
    assert "Migrate To Compact Entity Model" in readme_text
    assert "docs/entity-model.md" in readme_text
    assert "docs/entity-model-migration.md" in readme_text
    assert "`switch.<circuit>_maintenance`" in readme_text
    assert "`button.<circuit>_start_maintenance`" not in readme_text
    assert "`button.<circuit>_end_maintenance`" not in readme_text
    assert "`button.<circuit>_pause_alerts`" not in readme_text
    assert "`sensor.<circuit>_sensitivity`" not in readme_text
    assert "`sensor.<circuit>_standby_threshold`" not in readme_text
    assert "Legacy replacement" in readme_text
    assert "sensor.<circuit>_health_summary" in readme_text
    assert "configured outdoor temperature source entity" in readme_text


def test_entity_model_docs_document_local_count_report_generation() -> None:
    entity_model = (ROOT / "docs" / "entity-model.md").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme_text.lower().split())

    assert "python scripts/report_entity_inventory.py" in entity_model
    assert "generated development artifacts are not checked in" in normalized_readme
    assert "Simple creates 10 or fewer" in entity_model
    assert "`switch.<circuit>_maintenance`" in entity_model


def test_readme_sensor_reference_is_table_with_friendly_names_first() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |"
        in readme_text
    )
    for row in (
        "| Health Summary | `sensor.<circuit>_health_summary` |",
        "| Setup Health / Next Step | "
        "`sensor.circuitsetup_energy_analyzer_setup_health` |",
        "| Energy | `sensor.<appliance>_energy` |",
        "| Active Power | `sensor.<appliance>_active_power` "
        "or `sensor.<appliance>_watts` |",
        "| Running | `binary_sensor.<circuit>_running` |",
    ):
        assert row in readme_text
    assert "- Energy (`sensor.<appliance>_energy`)" not in readme_text
    assert "- Health Summary:" not in readme_text
    assert "Known Load Share" in readme_text
    assert "`sensor.<circuit>_nilm_discovered_signatures`" in readme_text
    assert "`sensor.<circuit>_nilm_signature_count`" not in readme_text
    assert "Expert Energy Detail group" in readme_text
    assert "Expert Demand and Capacity group" in readme_text
    assert "Expert Mains and Solar Detail group" in readme_text
    assert "Expert NILM Detail group" in readme_text
    assert "Expert Developer Diagnostics group" in readme_text
    assert "how much of current mains power is explained" in readme_text
    assert "Expert group" in readme_text
    assert "Core/default visible" in readme_text
    assert "Standard feature entity" in readme_text
    assert "Advanced diagnostic, hidden by default." not in readme_text


def test_readme_describes_current_nilm_workspace_flow() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    for expected in (
        "NILM workspace can also pair compatible on/off edges into likely sessions",
        "Open NILM Graph & Review",
        "Mains, Solar, and NILM",
        "label signatures, save graph intervals, merge duplicate signatures",
        "assign a signature/session/interval to an appliance",
        "Published NILM appliances are marked as estimated",
        "`assign_session_to_appliance`",
        "`publish_nilm_appliance_assignment`",
    ):
        assert expected in readme_text


def test_readme_describes_bounded_settings_suggestion_attributes() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "Attributes show a bounded preview of up to five suggestions with IDs, "
        "setting labels, current values, and suggested values"
    ) in readme_text
    old_attribute_text = (
        "Attributes include recommendation IDs, suggested values, and evidence"
    )
    assert old_attribute_text not in readme_text


def test_readme_explains_compatible_meter_support_and_links_product() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "CircuitSetup-first, not CircuitSetup-only" in readme_text
    assert "other compatible meters" in readme_text
    assert (
        "power, current, voltage, energy, frequency, reactive power, "
        "apparent power, or power factor"
        in readme_text
    )
    assert (
        "https://circuitsetup.us/index.php/product/expandable-6-channel-esp32-energy-meter/"
        in readme_text
    )


def test_readme_screenshot_references_exist_and_are_cropped() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    refs = re.findall(
        r"!\[[^\]]+\]\((docs/images/readme/[^)]+\.png)\)",
        readme_text,
    )

    expected = {
        "docs/images/readme/integration-overview.png",
        "docs/images/readme/options-menu.png",
        "docs/images/readme/assignment-editor.png",
        "docs/images/readme/advanced-settings.png",
        "docs/images/readme/notifications-panel.png",
        "docs/images/readme/notifications-repairs.png",
        "docs/images/readme/demo-dashboard.png",
    }

    assert expected <= set(refs)
    assert "### Screenshots" not in readme_text
    focused_native_refs = {
        "docs/images/readme/notifications-panel.png",
    }
    for ref in sorted(set(refs)):
        path = ROOT / ref
        assert path.exists(), f"{ref} is referenced by README but missing"
        width, height = _png_dimensions(path)
        min_width = 350 if ref in focused_native_refs else 500
        assert width >= min_width, f"{ref} is too narrow to show readable UI"
        if ref in focused_native_refs:
            assert width <= 520, f"{ref} should stay at native card/panel scale"
        assert height >= 250, f"{ref} is too short to show readable UI"
        assert not (
            width >= 1800 and height >= 1000
        ), f"{ref} looks like a full-screen capture rather than a cropped UI panel"


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


def _dashboard_views(dashboard: object) -> list[dict[str, object]]:
    if not isinstance(dashboard, dict):
        return []
    views = dashboard.get("views")
    if isinstance(views, list):
        return [view for view in views if isinstance(view, dict)]
    return [dashboard]


def _dashboard_sections(dashboard: object) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    for view in _dashboard_views(dashboard):
        view_sections = view.get("sections", [])
        if isinstance(view_sections, list):
            sections.extend(
                section for section in view_sections if isinstance(section, dict)
            )
    return sections


def _dashboard_section(dashboard: object, title: str) -> dict[str, object]:
    return next(
        section
        for section in _dashboard_sections(dashboard)
        if section.get("title") == title
    )


def _dashboard_entity_refs(dashboard_text: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(r"entity:\s*([a-z_]+\.[A-Za-z0-9_]+)", dashboard_text)
    ]


def _dashboard_entity_refs_with_conditional_context(
    node: object,
    *,
    conditional: bool = False,
) -> dict[str, bool]:
    refs: dict[str, bool] = {}
    if isinstance(node, dict):
        current_conditional = conditional or node.get("type") == "conditional"
        entity = node.get("entity")
        if isinstance(entity, str):
            refs[entity] = refs.get(entity, False) or current_conditional
        for value in node.values():
            refs.update(
                _dashboard_entity_refs_with_conditional_context(
                    value,
                    conditional=current_conditional,
                )
            )
    elif isinstance(node, list):
        for item in node:
            refs.update(
                _dashboard_entity_refs_with_conditional_context(
                    item,
                    conditional=conditional,
                )
            )
    return refs


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])
