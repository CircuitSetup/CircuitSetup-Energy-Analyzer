from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer"
PANEL_ASSET = INTEGRATION_DIR / "frontend" / "energy-analyzer-panel.js"


def _run_panel_node_script(body: str) -> None:
    script = f"""
const fs = require("fs");
const vm = require("vm");
class BrowserDate extends Date {{
  toDateString() {{
    return new Intl.DateTimeFormat("en-CA", {{
      timeZone: "UTC",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }}).format(this);
  }}
}}
const context = {{
  console,
  Date: BrowserDate,
  Intl,
  URL,
  URLSearchParams,
  requestAnimationFrame(callback) {{ callback(); }},
  Event: class {{}},
  CustomEvent: class {{}},
  HTMLElement: class {{
    attachShadow() {{
      this.shadowRoot = {{ innerHTML: "", querySelectorAll() {{ return []; }} }};
      return this.shadowRoot;
    }}
    scrollIntoView() {{}}
  }},
  customElements: {{
    get() {{ return undefined; }},
    define() {{}},
  }},
  history: {{
    pushState() {{}},
    replaceState() {{}},
  }},
  window: {{
    location: {{ origin: "http://example.local", pathname: "/panel", search: "" }},
    addEventListener() {{}},
    dispatchEvent() {{}},
    scrollTo() {{}},
  }},
}};
vm.createContext(context);
const source = fs.readFileSync({json.dumps(str(PANEL_ASSET))}, "utf8");
vm.runInContext(
  `${{source}}\\n`
  + "this.Panel = CircuitSetupEnergyAnalyzerPanel;\\n"
  + "this.DashboardGraphs = CircuitSetupEnergyAnalyzerDashboardGraphs;",
  context
);
{body}
"""
    subprocess.run(["node", "-e", script], check=True, cwd=ROOT)


def _translations() -> dict:
    return json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )


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
    strings = _translations()
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
    strings = _translations()
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
        "appliance evidence navigation"
        in dashboard["data_description"]["dashboard_layout"].lower()
    )
    assert (
        "diagnostics/evidence section"
        in dashboard["data_description"]["dashboard_layout"].lower()
    )
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
    strings = _translations()

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
    strings = _translations()
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
    strings = _translations()

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
    strings = _translations()

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


def test_runtime_english_translation_is_the_single_source() -> None:
    translations = _translations()

    assert not (INTEGRATION_DIR / "strings.json").exists()

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
        translated_step = translations[section]["step"][step]
        assert translated_step["title"]
        assert translated_step["description"]
        assert translated_step.get("data") or translated_step.get("sections")

    translated_init = translations["options"]["step"]["init"]
    assert translated_init["title"]
    assert translated_init["description"]
    assert translated_init["menu_options"]


def test_config_flow_descriptions_do_not_show_non_actionable_mapping_suggestions() -> (
    None
):
    translations = _translations()

    descriptions = (
        translations["config"]["step"]["user"]["description"],
        translations["config"]["step"]["utility"]["description"],
        translations["options"]["step"]["init"]["description"],
        translations["options"]["step"]["sources"]["description"],
        translations["options"]["step"]["mains"]["description"],
        translations["options"]["step"]["utility"]["description"],
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


def test_alert_pause_switch_label_matches_pause_resume_alert_language() -> None:
    translations = _translations()

    label = translations["entity"]["switch"]["maintenance"]["name"]
    assert label == "Pause alerts"

    binary_label = translations["entity"]["binary_sensor"]["maintenance"]["name"]
    assert binary_label == "Alerts paused"


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
    translations = _translations()

    combined = "\n".join(
        [
            readme_text,
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
        assert (
            f"/circuitsetup-energy-analyzer-evidence?circuit_id={circuit}"
            in appliance_overview
        )
    for name in (
        "Open Refrigerator Evidence",
        "Open HVAC Evidence",
        "Open Water heater Evidence",
        "Open Pool pump Evidence",
        "Open Washer Evidence",
        "Open Dryer Evidence",
        "Open Car charger Evidence",
    ):
        assert name in appliance_overview

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
    assert (
        "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        in dashboard_text
    )


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
        "/api/circuitsetup_energy_analyzer/appliance_detail",
        "APPLIANCE_DETAIL_CALL_API_PATH",
        "APPLIANCE_DETAIL_QUERY_PARAM",
        "routeUrl.searchParams.get(APPLIANCE_DETAIL_QUERY_PARAM)",
        "_loadApplianceDetail",
        "_routeRequestsApplianceDetail",
        "this._routeRequestsApplianceDetail() ? this._renderApplianceDetailBody()",
        "_renderApplianceDetail",
        "_renderApplianceDetailBody",
        "Appliance Detail",
        "Today vs Normal",
        "Behavior Expectations",
        "Source",
        "Confidence",
        "NILM_WORKSPACE_CALL_API_PATH",
        "nilm_workspace",
        "NILM_WORKSPACE_QUERY_PARAM",
        "routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM)",
        "_loadNilmWorkspace",
        "_routeRequestsNilmWorkspace",
        "this._routeRequestsNilmWorkspace() ? this._renderNilmWorkspaceBody()",
        "_renderNilmWorkspace",
        "_renderNilmWorkspaceBody",
        "NILM Workspace",
        "_renderNilmReviewQueue(workspace)",
        "_nilmReviewItems",
        "Needs review",
        "Next to review",
        "signatures need labels or decisions.",
        "Review mains load changes, labels, and assignments used by NILM.",
        "Known Load Overlays",
        "Known loads mark configured circuits so NILM can separate expected usage.",
        "Solar/Net Overlays",
        "Solar and net-flow overlays help explain import/export changes on mains.",
        "Show known-load overlays",
        "Show solar/net overlays",
        "data-nilm-overlay-toggle",
        "_toggleNilmOverlaySeries",
        "_visibleNilmWorkspaceSeries",
        "Estimated Appliances",
        "Estimated appliances are NILM's current best grouped load guesses.",
        "Appliance Assignments",
        "Assignments save a signature as a named appliance for future review.",
        "Open Appliance Detail",
        "data-nilm-appliance-detail-path",
        "_nilmApplianceDetailButton",
        "estimated_daily_energy",
        "model_status",
        "Validation",
        "False positives",
        "False negatives",
        "Median power error",
        "Energy error",
        "Prediction Preview",
        "Preview compares saved labels with NILM's predicted sessions.",
        "Ground Truth Sensor",
        "ground_truth_entity_id",
        "ground_truth_options",
        "<select data-nilm-label-interval-input=\"ground_truth_entity_id\"",
        "No ground-truth sensors are available from known-load circuits.",
        "_renderNilmValidation",
        "NILM Sessions",
        "Sessions pair on/off edges into likely appliance runs.",
        "Manual Labels",
        "Manual labels teach NILM which appliance was running during a time range.",
        "NILM Signatures",
        "Signatures group similar sessions that may be the same appliance.",
        "NILM Edges",
        "Edges are detected power changes before they are paired into sessions.",
        "Show on Graph",
        "data-nilm-signature-focus",
        "_focusNilmSignatureOnGraph",
        "_focusNilmGraphWindowForSignature",
        "_nilmSignatureFingerprint",
        "Zoom In",
        "Zoom Out",
        "Pan Earlier",
        "Pan Later",
        "data-nilm-graph-zoom",
        "data-nilm-graph-pan",
        "data-nilm-workspace-graph",
        "data-nilm-graph-window",
        "Showing NILM graph window",
        "_zoomNilmGraph",
        "_panNilmGraph",
        "_nilmWorkspaceGraphWindow",
        "_renderNilmLabelIntervals",
        "_renderNilmAssignmentActions",
        "_callNilmWorkspaceItemAction",
        "_callNilmLabelIntervalAction",
        "data-nilm-label-interval-action",
        'data-nilm-label-interval-action="adjust"',
        "Adjust Label",
        "interval_id",
        "data-nilm-session-action",
        "data-nilm-assignment-action",
        "data-nilm-assignment-merge-target",
        "profile_options",
        "<select id=\"nilm_assignment_profile_",
        "<option value=\"\">Do not merge</option>",
        'collectionKey === "sessions"',
        "`#nilm_session_label_${index}`",
        "Existing appliance",
        "data-nilm-existing-assignment",
        'actionKey === "assign" ? '
        "this._nilmExistingAssignmentSelection(`signature_${index}`) : null",
        "_renderNilmExistingAssignmentField",
        "Assign Appliance",
        "Publish Entities",
        "Disable Publishing",
        "Remove Assignment",
        "Save Assignment",
        "_saveNilmAssignmentChanges",
        "No assignment changes to save.",
        "Confirm Appliance",
        "Wrong Appliance",
        "Save Interval",
        "Generate From Sensor",
        "Estimated energy",
        "nilm_interval_energy_preview",
        "_nilmLabelIntervalEnergyPreview",
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
        "relearn_baseline",
        "open_appliance_detail",
        'this._listen("#open_appliance_detail", () => '
        'this._callAction("open_appliance_detail"))',
        "apply_setting_recommendation",
        "dismiss_setting_recommendation",
        "Alert evidence chart",
        "Graph times shown in",
        "_timeZone",
        "_chartTimeTicks",
        "_chartDateKey",
        "_formatAxisTime",
        "time-grid",
        'text-anchor="${tick.anchor}"',
        "data-nilm-chart-select",
        "nilm_edges",
        "nilm-edge-marker",
        "data-nilm-edge-times",
        "data-nilm-edge-time",
        "data-nilm-edge-direction",
        "_selectNilmEdgeTime",
        "Loaded NILM edge time.",
        "_snapNilmChartTimeToEdge",
        "NILM_EDGE_SNAP_MS",
        "nilm_sessions",
        "nilm-session-band",
        "nilm-session-label",
        "data-nilm-session-label",
        "data-nilm-session-start",
        "data-nilm-session-confidence",
        "confidence ${Math.round(confidenceValue * 100)}%",
        "_nilmSessionGraphLabel",
        "_selectNilmSessionInterval",
        "Loaded NILM session interval.",
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
        "_overlayEntitySummary",
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
    assert 'placeholder="sensor.dishwasher_power"' not in asset
    assert "<select id=\"nilm_merge_target_" not in asset
    assert (
        "querySelector(`#nilm_assignment_label_${index}`)\n"
        "        || this.shadowRoot.querySelector(`#nilm_session_label_${index}`)"
        not in asset
    )
    assert (
        'entities.map((entityId) => `<code>${this._escape(entityId)}</code>`)'
        not in asset
    )
    assert "Source Entities" not in asset
    assert "source-entity-chip" not in asset
    assert "data-source-entity" not in asset
    assert '(item.entity_ids || []).join(", ")' not in asset
    assert "data-nilm-workspace-action" not in asset
    assert "_openSourceEntity" not in asset
    assert "${this._escape(item.entity_id)}" not in asset
    assert "this._escape(signature.signature_id)}</strong>" not in asset
    assert "recommendation.recommendation_id || \"Recommendation\"" not in asset
    assert "deny_setting_recommendation" not in asset
    assert '_recommendationActionButton(recommendation, index, "deny"' not in asset


def test_nilm_workspace_places_review_actions_before_diagnostics() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    review = asset.index("_renderNilmReviewQueue(workspace)")
    signatures = asset.index('_renderNilmWorkspaceList("NILM Signatures"')
    overlays = asset.index("_renderNilmOverlayToggles(workspace)")
    graph_controls = asset.index("_renderNilmGraphControls(graphWindow)")
    prediction = asset.index("_renderNilmValidation(workspace.validation)")
    edges = asset.index('_renderNilmWorkspaceList("NILM Edges"')

    assert review < signatures < overlays < graph_controls < prediction < edges
    assert "Needs review" in asset
    assert "Next to review" in asset


def test_nilm_workspace_review_queue_shows_next_review_item_actions() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  signatures: [
    {
      signature_id: "sig-1",
      display_label: "Unknown load 1",
      confidence: 0.42,
      actions: {
        label: {},
        assign: {},
        ignore: {},
        mark_expected: {},
        merge: { target_options: [] }
      }
    },
    {
      signature_id: "sig-2",
      user_label: "Dryer",
      review_state: "confirmed",
      actions: { label: {} }
    }
  ]
};
const html = panel._renderNilmReviewQueue(panel._nilmWorkspace);
for (const expected of [
  "Needs review",
  "1 signature needs labels or decisions.",
  "Next to review",
  "Unknown load 1",
  "Save Label",
  "Assign Appliance",
  "Ignore",
  "Mark Expected"
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_nilm_workspace_does_not_duplicate_review_item_control_ids() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [
    {
      signature_id: "sig-1",
      display_label: "Unknown load 1",
      confidence: 0.42,
      actions: {
        label: {},
        assign: {},
        ignore: {},
        mark_expected: {},
        merge: {
          target_options: [{ value: "sig-2", label: "Unknown load 2" }]
        }
      }
    },
    {
      signature_id: "sig-2",
      display_label: "Unknown load 2",
      user_label: "Dryer",
      review_state: "confirmed",
      actions: { label: {} }
    }
  ],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  edges: [],
  validation: {}
};
const html = panel._renderNilmWorkspaceBody();
for (const id of ['id="nilm_label_0"', 'id="nilm_merge_targets_0"']) {
  const count = (html.match(new RegExp(id, "g")) || []).length;
  if (count !== 1) {
    throw new Error(`${id} rendered ${count} times: ${html}`);
  }
}
"""
    )


def test_dashboard_graphs_custom_card_asset_is_registered() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    for expected in (
        'customElements.get("circuitsetup-energy-analyzer-dashboard-graphs")',
        'customElements.define("circuitsetup-energy-analyzer-dashboard-graphs"',
        "CircuitSetupEnergyAnalyzerDashboardGraphs",
        "Latest related notification",
        "View notification detail",
        "NILM mains power",
        "data-dashboard-alert-detail",
    ):
        assert expected in asset


def test_dashboard_graphs_card_hides_without_appliance_and_renders_graphs() -> None:
    _run_panel_node_script(
        r"""
const hidden = new context.DashboardGraphs();
hidden.setConfig({ appliance_power_entities: [] });
hidden._loading = false;
hidden._nilmWorkspaceLoading = false;
hidden._nilmWorkspace = {
  status: "ok",
  assignment_count: 0,
  virtual_appliance_count: 0,
  assignments: [],
  virtual_appliances: [],
};
hidden._render();
if (hidden.shadowRoot.innerHTML !== "") {
  throw new Error("dashboard graph card should hide when no NILM appliance is defined");
}

const card = new context.DashboardGraphs();
card.setConfig({
  title: "NILM mains power",
  circuit_id: "mains",
  detail_path: "/circuitsetup-energy-analyzer-evidence"
    + "?nilm_workspace=1&circuit_id=mains",
  appliance_power_entities: ["sensor.pool_pump_estimated_power"],
});
card._hass = {
  config: { time_zone: "UTC" },
  states: {
    "sensor.pool_pump_estimated_power": {
      attributes: { friendly_name: "Pool Pump Estimated Power" },
    },
    "sensor.mains_power": { attributes: { friendly_name: "Mains Power" } },
  },
};
card._loading = false;
card._historyLoading = false;
card._nilmWorkspaceLoading = false;
card._payload = {
  alert: {
    what_happened: "Pool pump used more power than expected.",
    evidence_path: "/circuitsetup-energy-analyzer-evidence"
      + "?alert_id=alert-1&circuit_id=mains",
    graph_window_start: "2026-06-29T12:00:00Z",
    graph_window_end: "2026-06-29T12:10:00Z",
    graph_entities: ["sensor.mains_power"],
  },
};
card._historySeries = [[
  {
    entity_id: "sensor.mains_power",
    state: "120",
    last_changed: "2026-06-29T12:00:00Z",
  },
  {
    entity_id: "sensor.mains_power",
    state: "180",
    last_changed: "2026-06-29T12:10:00Z",
  },
]];
card._nilmWorkspace = {
  status: "ok",
  assignment_count: 1,
  virtual_appliance_count: 1,
  assignments: [{ assignment_id: "pool_pump" }],
  virtual_appliances: [{ appliance_id: "pool_pump" }],
  history: { start: "2026-06-29T12:00:00Z", end: "2026-06-29T12:10:00Z" },
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [{
    start: "2026-06-29T12:01:00Z",
    end: "2026-06-29T12:09:00Z",
    display_label: "Pool Pump",
    confidence: 0.91,
  }],
};
card._nilmWorkspaceHistorySeries = [[
  {
    entity_id: "sensor.mains_power",
    state: "120",
    last_changed: "2026-06-29T12:00:00Z",
  },
  {
    entity_id: "sensor.mains_power",
    state: "180",
    last_changed: "2026-06-29T12:10:00Z",
  },
]];
card._render();
const html = card.shadowRoot.innerHTML;
for (const expected of [
  "Latest related notification",
  "Pool pump used more power than expected.",
  "data-dashboard-alert-detail",
  "View notification detail",
  "NILM mains power",
  "Pool Pump",
  "axis-label",
  ">W<",
]) {
  if (!html.includes(expected)) {
    throw new Error(`dashboard graph card missing ${expected}`);
  }
}
"""
    )


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


def test_dynamic_alert_evidence_panel_uses_internal_component_renderers() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    for expected in (
        "class CircuitSetupPanelComponent",
        "class CircuitSetupEvidenceSummary",
        "class CircuitSetupNilmWorkspace",
        "class CircuitSetupRecommendationCards",
        "this._evidenceSummary = new CircuitSetupEvidenceSummary(this);",
        "this._nilmWorkspaceComponent = new CircuitSetupNilmWorkspace(this);",
        "this._recommendationCards = new CircuitSetupRecommendationCards(this);",
        "return this._evidenceSummary.renderAlert(alert, circuit);",
        "return this._nilmWorkspaceComponent.render();",
        "return this._recommendationCards.renderSection(",
    ):
        assert expected in asset


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


def test_dynamic_alert_evidence_panel_orders_recommendation_actions() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    preview = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"preview", "Preview evidence", true)'
    )
    apply = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"apply", "Apply")'
    )
    dismiss = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"dismiss", "Dismiss", true)'
    )
    undo = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"undo", "Undo", true)'
    )
    reset = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"reset", "Reset default", true)'
    )

    assert preview < apply < dismiss < undo < reset


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
        "_alertActionMessage(actionKey)",
        (
            '_renderActionGroup("Respond to this alert", "Review the graph, '
            'then choose how the analyzer should treat this alert."'
        ),
        (
            '_renderActionGroup("Pause alerts for maintenance", "Use this '
            "when the appliance is being serviced or intentionally behaving "
            'differently."'
        ),
        (
            '_renderActionGroup("Tune this circuit", "Use these when the '
            'appliance summary looks wrong or the learned baseline is stale."'
        ),
        "Alert acknowledged.",
        "Marked as expected behavior.",
        "Marked as not helpful.",
        "Saved label:",
        "Review state:",
    ):
        assert expected in asset
    assert "Retire" not in asset
    assert "Rename Appliance" not in asset
    assert "Change Type" not in asset
    assert "Merge Assignment" not in asset
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
    assert "new Intl.DateTimeFormat(undefined, {" in asset
    assert "timeZone: this._timeZone()," in asset
    assert "this._hass.config.time_zone" in asset


def test_chart_time_ticks_include_date_for_displayed_timezone_boundary() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "America/New_York" } };
const ticks = panel._chartTimeTicks(
  Date.parse("2026-06-02T03:30:00Z"),
  Date.parse("2026-06-02T04:30:00Z"),
  () => 0
);
if (!ticks.some((tick) => /Jun|6\\//.test(tick.label))) {
  const labels = ticks.map((tick) => tick.label).join(" | ");
  throw new Error(
    `expected a displayed date in HA timezone labels: ${labels}`
  );
}
"""
    )


def test_show_on_graph_focuses_matching_nilm_session_window() -> None:
    _run_panel_node_script(
        """
(async () => {
const requests = [];
const historyPath = "circuitsetup_energy_analyzer/nilm_workspace_history"
  + "?circuit_id=mains&hours=1";
const panel = new context.Panel();
panel._render = () => {};
panel._requestJson = async (apiPath, fetchPath) => {
  requests.push({ apiPath, fetchPath });
  return [[{
    entity_id: "sensor.mains_power",
    state: "350",
    last_changed: "2026-06-06T02:05:00Z",
  }]];
};
panel._nilmWorkspace = {
  status: "ok",
  history: {
    start: "2026-06-06T03:00:00Z",
    end: "2026-06-06T04:00:00Z",
    max_hours: 24,
    api_path: historyPath,
    fetch_path: `/api/${historyPath}`,
  },
  sessions: [
    {
      signature_fingerprint: "signature-1",
      start: "2026-06-06T02:00:00Z",
      end: "2026-06-06T02:30:00Z",
    },
  ],
};
await panel._focusNilmSignatureOnGraph("signature-1");
const sessionStart = Date.parse("2026-06-06T02:00:00Z");
const sessionEnd = Date.parse("2026-06-06T02:30:00Z");
if (!panel._nilmGraphWindow) {
  throw new Error("expected Show on Graph to set a graph window");
}
const missesSession = panel._nilmGraphWindow.start > sessionStart
  || panel._nilmGraphWindow.end < sessionEnd;
if (missesSession) {
  const graphWindow = JSON.stringify(panel._nilmGraphWindow);
  throw new Error(`expected graph window to include session: ${graphWindow}`);
}
if (!requests[0] || !/hours=3/.test(requests[0].apiPath)) {
  const requestsJson = JSON.stringify(requests);
  throw new Error(`expected Show on Graph to reload history: ${requestsJson}`);
}
if (!panel._nilmWorkspaceHistorySeries.length) {
  throw new Error("expected Show on Graph to store focused history rows");
}
if (!/graph sessions/.test(panel._lastActionMessage || "")) {
  const message = panel._lastActionMessage;
  throw new Error(`expected visible Show on Graph message, got ${message}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_show_on_graph_toggle_off_restores_full_nilm_window() -> None:
    _run_panel_node_script(
        """
(async () => {
const historyPath = "circuitsetup_energy_analyzer/nilm_workspace_history"
  + "?circuit_id=mains&hours=4";
const panel = new context.Panel();
panel._render = () => {};
panel._requestJson = async () => [];
panel._nilmWorkspace = {
  status: "ok",
  history: {
    start: "2026-06-06T00:00:00Z",
    end: "2026-06-06T04:00:00Z",
    max_hours: 24,
    api_path: historyPath,
    fetch_path: `/api/${historyPath}`,
  },
  sessions: [
    {
      signature_fingerprint: "signature-1",
      start: "2026-06-06T02:00:00Z",
      end: "2026-06-06T02:30:00Z",
    },
  ],
};
await panel._focusNilmSignatureOnGraph("signature-1");
await panel._focusNilmSignatureOnGraph("signature-1");
const graphWindow = panel._nilmWorkspaceGraphWindow(panel._nilmWorkspace);
if (panel._nilmFocusedSignature) {
  throw new Error("expected repeated Show on Graph click to clear focus");
}
if (graphWindow.start !== Date.parse(panel._nilmWorkspace.history.start)
  || graphWindow.end !== Date.parse(panel._nilmWorkspace.history.end)) {
  const graphWindowJson = JSON.stringify(graphWindow);
  throw new Error(`expected full graph window after clear: ${graphWindowJson}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_save_assignment_calls_changed_assignment_services() -> None:
    _run_panel_node_script(
        """
(async () => {
  const calls = [];
  const panel = new context.Panel();
  panel._render = () => {};
  panel._scrollToTop = () => {};
  panel._loadEvidence = async () => {};
  panel._actionRefreshRouteKey = () => "/test";
  panel._hass = {
    callService: async (domain, service, data) => calls.push({
      domain,
      service,
      data,
    }),
  };
  panel.shadowRoot.querySelector = (selector) => {
    if (selector === "#nilm_assignment_label_0") {
      return { value: "Dishwasher Prime" };
    }
    if (selector === "#nilm_assignment_profile_0") {
      return { value: "dishwasher" };
    }
    if (selector === "#nilm_assignment_merge_target_0") {
      return { value: "assignment-target" };
    }
    return null;
  };
  panel._nilmWorkspace = {
    assignments: [{
      assignment_id: "assignment-source",
      display_name: "Dishwasher",
      appliance_profile: "mixed",
      actions: {
        rename: {
          domain: "circuitsetup_energy_analyzer",
          service: "rename_nilm_appliance",
          data: { circuit_id: "mains", assignment_id: "assignment-source" },
        },
        change_profile: {
          domain: "circuitsetup_energy_analyzer",
          service: "change_nilm_appliance_profile",
          data: { circuit_id: "mains", assignment_id: "assignment-source" },
        },
        merge: {
          domain: "circuitsetup_energy_analyzer",
          service: "merge_nilm_assignments",
          data: {
            circuit_id: "mains",
            source_assignment_id: "assignment-source",
          },
        },
      },
    }],
  };
  await panel._saveNilmAssignmentChanges(0);
  const services = calls.map((call) => call.service).join(",");
  const expected = [
    "rename_nilm_appliance",
    "change_nilm_appliance_profile",
    "merge_nilm_assignments",
  ].join(",");
  if (services !== expected) {
    throw new Error(`unexpected services: ${services}`);
  }
  if (calls[0].data.label !== "Dishwasher Prime") {
    throw new Error("rename call did not include edited label");
  }
  if (calls[1].data.appliance_profile !== "dishwasher") {
    throw new Error("profile call did not include edited appliance type");
  }
  if (calls[2].data.target_assignment_id !== "assignment-target") {
    throw new Error("merge call did not include selected target");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
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
    translations = _translations()
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
    assert "visual appliance story" in readme_text
    assert "Household Overview" in readme_text
    assert "Today's Energy" in readme_text
    assert "Behavior Watchlist" in readme_text
    assert "Appliance Run Timeline" in readme_text
    assert "NILM Review" in readme_text
    assert "instead of service-control cards" in readme_text
    assert "navigation-only evidence buttons" in readme_text
    assert "Missing, disabled, or unavailable entities" in readme_text
    assert "Create Or Update Dashboard" in readme_text
    assert "Match Entity Detail Level To Layout" in readme_text
    assert "Remove Existing Dashboard" in readme_text
    assert "dashboard action still runs from Configure" in readme_text
    assert "**Standard**: Simple plus feature-level mains" in readme_text
    assert "appliance evidence navigation" in readme_text
    assert "**Expert**: Standard plus the diagnostics/evidence section" in (
        readme_text
    )
    assert "does not add diagnostic/detail entity cards automatically" in readme_text
    assert "graph/detail cards for the Expert groups you selected" not in readme_text
    assert "button.circuitsetup_energy_analyzer_create_dashboard" not in readme_text
    assert "adds small action cards" not in readme_text


def test_readme_documents_compact_entity_model_and_migration() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Compact entity model" in readme_text
    assert "Migrate To Compact Entity Model" in readme_text
    assert "docs/entity-model.md" in readme_text
    assert "docs/entity-model-migration.md" not in readme_text
    assert "`switch.<circuit>_maintenance`" in readme_text
    assert "`button.<circuit>_start_maintenance`" not in readme_text
    assert "`button.<circuit>_end_maintenance`" not in readme_text
    assert "`button.<circuit>_pause_alerts`" not in readme_text
    assert "`sensor.<circuit>_sensitivity`" not in readme_text
    assert "`sensor.<circuit>_standby_threshold`" not in readme_text
    assert "Legacy replacement" in readme_text
    assert "sensor.<circuit>_health_summary" in readme_text
    assert "configured outdoor temperature source entity" in readme_text


def test_entity_model_docs_keep_counts_without_inventory_scripts() -> None:
    entity_model = (ROOT / "docs" / "entity-model.md").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme_text.lower().split())

    assert not (ROOT / "scripts" / "report_entity_inventory.py").exists()
    assert not (ROOT / "scripts" / "entity_inventory.py").exists()
    assert "python scripts/report_entity_inventory.py" not in entity_model
    assert "generated development artifacts" not in normalized_readme
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
        "Adjust Label",
        "Validate History",
        "false-positive and false-negative rates",
        "known-load sensors as selectable ground-truth sources",
        "appliance-profile choices",
        "Published NILM appliances are marked as estimated",
        "Disable Publishing",
        "NILM estimates are inferred from aggregate power and are not safety evidence",
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
