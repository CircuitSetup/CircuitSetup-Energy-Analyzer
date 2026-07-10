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
    translation_path = (
        INTEGRATION_DIR / "translations" / "en.json"
    )
    panel_text_statement = (
        "const __panelText = JSON.parse("
        f"fs.readFileSync({json.dumps(str(translation_path))}, \"utf8\")"
        ").config_panel.panel;\n"
    )
    panel_class_statement = json.dumps(
        "this.Panel = class TestPanel extends CircuitSetupEnergyAnalyzerPanel "
        "{ constructor() { super(); this.panel = { config: "
        "{ text: __panelText } }; } };\n"
    )
    dashboard_class_statement = json.dumps(
        "this.DashboardGraphs = class TestDashboardGraphs extends "
        "CircuitSetupEnergyAnalyzerDashboardGraphs "
        "{ constructor() { super(); this.setConfig({ text: __panelText }); } "
        "setConfig(config) { super.setConfig(Object.assign("
        "{ text: __panelText }, config || {})); } };"
    )
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
  fs,
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
  + {json.dumps(panel_text_statement)}
  + {panel_class_statement}
  + {dashboard_class_statement},
  context
);
{body}
"""
    subprocess.run(["node", "-e", script], check=True, cwd=ROOT)


def _translations() -> dict:
    return json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )


def _iter_translation_strings(value, path: tuple[str, ...] = ()):
    if isinstance(value, str):
        yield path, value
        return
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_translation_strings(child, (*path, key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_translation_strings(child, (*path, str(index)))


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
        "Diagnostics and Evidence",
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
            not in appliance_overview
        )
    assert "Open Refrigerator Evidence" not in appliance_overview
    assert "Analyzer evidence links" in yaml.safe_dump(
        _dashboard_section(dashboard, "Diagnostics and Evidence")
    )

    energy_tracking = yaml.safe_dump(_dashboard_section(dashboard, "Energy Tracking"))
    assert "Appliance activity" not in energy_tracking
    assert "Electrical health rollups" not in energy_tracking


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
        "Diagnostics and Evidence",
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
    assert "Electrical health rollups" not in energy_section
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
    assert PANEL_ASSET.exists()
    asset = PANEL_ASSET.read_text(encoding="utf-8")
    translated_text = json.dumps(_translations()["config_panel"]["panel"])

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
        "_panelText(\"headers.appliance_detail\")",
        "_panelText(\"appliance_detail.today_vs_normal\")",
        "_renderApplianceTimeline",
        "detail.recent_timeline",
        "_panelText(\"appliance_detail.behavior_expectations\")",
        "_panelText(\"common.source\")",
        "_panelText(\"common.confidence\")",
        "NILM_WORKSPACE_CALL_API_PATH",
        "nilm_workspace",
        "NILM_WORKSPACE_QUERY_PARAM",
        "routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM)",
        "_loadNilmWorkspace",
        "_routeRequestsNilmWorkspace",
        "this._routeRequestsNilmWorkspace() ? this._renderNilmWorkspaceBody()",
        "_renderNilmWorkspace",
        "_renderNilmWorkspaceBody",
        "_panelText(\"headers.nilm_workspace\")",
        "_renderNilmWorkspaceLanes(workspace)",
        "_renderNilmReviewLayout(workspace)",
        "_nilmLaneItems",
        "_nilmSelectedReviewItem",
        "_nilmReviewItems",
        "_panelText(\"nilm_workspace.review_lanes\")",
        "_panelText(\"nilm_workspace.known_load_overlays\")",
        "_panelText(\"nilm_workspace.solar_net_overlays\")",
        "data-nilm-overlay-toggle",
        "_toggleNilmOverlaySeries",
        "_visibleNilmWorkspaceSeries",
        "_panelText(\"nilm_workspace.estimated_appliances_title\")",
        "data-nilm-appliance-detail-path",
        "_nilmApplianceDetailButton",
        "estimated_daily_energy",
        "model_status",
        "_renderNilmValidation",
        "ground_truth_entity_id",
        "ground_truth_options",
        "<select data-nilm-label-interval-input=\"ground_truth_entity_id\"",
        "_panelText(\"nilm_workspace.sessions_title\")",
        "_panelText(\"nilm_workspace.manual_labels\")",
        "_panelText(\"nilm_workspace.edges_title\")",
        "data-nilm-signature-fingerprint",
        "_focusNilmSignatureOnGraph",
        "_focusNilmGraphWindowForSignature",
        "_nilmSignatureFingerprint",
        "data-nilm-graph-zoom",
        "data-nilm-graph-pan",
        "data-nilm-workspace-graph",
        "data-nilm-graph-window",
        "_zoomNilmGraph",
        "_panNilmGraph",
        "_nilmWorkspaceGraphWindow",
        "_renderNilmLabelIntervalEditor",
        "_renderNilmSavedLabelIntervals",
        "_renderNilmAssignmentActions",
        "_callNilmWorkspaceItemAction",
        "_callNilmLabelIntervalAction",
        "data-nilm-label-interval-action",
        'data-nilm-label-interval-action="adjust"',
        "interval_id",
        "data-nilm-session-action",
        "data-nilm-assignment-action",
        "data-nilm-assignment-merge-target",
        "profile_options",
        "<select id=\"nilm_assignment_profile_",
        'collectionKey === "sessions"',
        "`#nilm_session_label_${index}`",
        "data-nilm-existing-assignment",
        'actionKey === "assign" ? '
        "this._nilmExistingAssignmentSelection(`signature_${index}`) : null",
        "_renderNilmExistingAssignmentField",
        "_saveNilmAssignmentChanges",
        "nilm_interval_energy_preview",
        "_nilmLabelIntervalEnergyPreview",
        "datetime-local",
        "MAX_CHART_POINTS_PER_SERIES",
        "_boundedChartPoints",
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
        "_panelText(\"chart.alert_evidence_label\")",
        "_panelTextFormat(\"chart.graph_times\"",
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
        "_snapNilmChartTimeToEdge",
        "NILM_EDGE_SNAP_MS",
        "nilm_sessions",
        "nilm-session-band",
        "nilm-session-label",
        "data-nilm-session-label",
        "data-nilm-session-start",
        "data-nilm-session-confidence",
        "_nilmSessionGraphLabel",
        "_selectNilmSessionInterval",
        "_startNilmChartSelection",
        "_chartEventTime",
        "pointerdown",
        "<svg",
        "feature_name",
        "_friendlyFeature",
        "alert.safety_notice",
        "recommendation.actions.preview",
        "nilm-label-field",
        "_renderNilmLabelField",
        "_renderNilmSignatureReview",
        "_renderNilmDecisionFlow",
        "_applyNilmDecision",
        "data-nilm-apply-decision",
        "_nilmLabelDrafts",
        "_rememberNilmLabelDraft",
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
        "_friendlyEntityName",
        "friendly_name",
        "item.name",
        "_overlayEntitySummary",
        "@media (max-width: 800px)",
        "@media (prefers-reduced-motion: reduce)",
        'role="tablist"',
        'role="tab"',
        "aria-selected",
        "aria-pressed",
        'aria-live="polite"',
        "<ha-icon",
        "min-height: 44px",
        "overflow-x: auto",
        "flex: 0 0 auto",
        "data-loading-skeleton",
        "data-nilm-lane-empty",
    ):
        assert expected in asset

    for text in (
        "Appliance Detail",
        "NILM Workspace",
        "Respond to this alert",
        "Known Load Overlays",
        "Manual Labels",
        "Identify this load",
        "Sessions, assignments, validation, and technical details",
        "Save Assignment",
        "Alert evidence chart",
        "Matched alert",
        "Expected effect:",
        "Action unavailable",
        "Home Assistant service calls are not available",
    ):
        assert text in translated_text
        assert text not in asset
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
    assert "border-radius: 12px" not in asset
    assert "border-radius: 16px" not in asset
    assert "border-radius: 999px" not in asset
    assert all(
        int(radius) <= 8
        for radius in re.findall(r"border-radius:\s*(\d+)px", asset)
    )


def test_appliance_detail_renders_cost_values_as_currency() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._applianceDetail = {
  status: "ok",
  detail: {
    activity_state: "Running",
    current_power_w: 820,
    source_type: "direct_meter",
    confidence: null,
    health_state: "Ready",
    electrical_state: "Normal",
    energy_state: "Normal",
    model_status: null,
    daily_energy_kwh: 2.4,
    runtime_today_seconds: 7200,
    run_count_today: 3,
    cost_today: 0.6,
    recent_timeline: { items: [] },
    today_vs_normal: [{
      metric_id: "cost_today",
      label: "Cost today",
      unit: "$",
      current_value: 0.6,
      normal_low: 0.45,
      normal_high: 0.55,
      normal_median: 0.5,
      status: "higher",
      confidence: 0.9,
      source: "baseline_cost_estimate"
    }],
    expectations: [],
    what_to_check_first: [],
    active_alerts: []
  },
  actions: {}
};
const html = panel._renderApplianceDetailBody();
for (const expected of [
  "Cost Today",
  "$0.60",
  "Cost today",
  "Normal $0.45 - $0.55",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
if (html.includes("0.6 $")) {
  throw new Error(`cost comparison used suffix currency: ${html}`);
}
"""
    )


def test_panel_module_version_tracks_recent_timeline_frontend_change() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        PANEL_MODULE_VERSION,
    )

    assert "timeline" in PANEL_MODULE_VERSION
    assert "nilm-lanes" in PANEL_MODULE_VERSION
    assert "dashboard-nilm-lanes" in PANEL_MODULE_VERSION
    assert "nilm-review-card" in PANEL_MODULE_VERSION
    assert "candidate-facts" in PANEL_MODULE_VERSION
    assert "session-validation-card" in PANEL_MODULE_VERSION
    assert "interval-running-prompt" in PANEL_MODULE_VERSION
    assert "low-confidence-nilm" in PANEL_MODULE_VERSION
    assert "nilm-ha-device-workflow" in PANEL_MODULE_VERSION
    assert "cost-currency" in PANEL_MODULE_VERSION
    assert "available-nilm-actions" in PANEL_MODULE_VERSION
    assert "visual-hierarchy" in PANEL_MODULE_VERSION
    assert "visual-hierarchy-review" in PANEL_MODULE_VERSION
    assert "scoped-retries" in PANEL_MODULE_VERSION


def test_nilm_workspace_places_graph_before_review_and_diagnostics() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    graph = asset.index("_renderNilmGraph(workspace, graphWindow, graphSessions)")
    lanes = asset.index("_renderNilmWorkspaceLanes(workspace)")
    review = asset.index("_renderNilmReviewLayout(workspace)")
    secondary = asset.index("_renderNilmSecondaryCollections(workspace)")

    assert graph < lanes < review < secondary
    assert "_renderNilmReviewQueue" not in asset


def test_nilm_workspace_summary_shows_review_progress_before_graph() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderNilmWorkspaceSummary({
  lanes: {
    needs_review: {
      label: "Needs Review", signature_ids: ["sig-1"], assignment_ids: [],
    },
    assigned: {
      label: "Assigned", signature_ids: [], assignment_ids: ["assignment-1"],
    },
  },
  lane_counts: { needs_review: 1, assigned: 1 },
});
if (!html.includes("Review lanes") || !html.includes("Needs Review")
    || !html.includes("1 item")) {
  throw new Error(`missing workspace review progress: ${html}`);
}
"""
    )


def test_panel_command_targets_and_focus_styles_are_explicit() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")
    command_rule = re.search(r"button, a\.button\s*\{(?P<body>.*?)\}", asset, re.DOTALL)

    assert command_rule is not None
    assert "min-height: 44px" in command_rule.group("body")
    for selector in (
        "button:focus-visible",
        "a.button:focus-visible",
        ".decision-tile:has(input:focus-visible)",
        ".nilm-decision-option:has(input:focus-visible)",
        ".nilm-lane:focus-visible",
        ".nilm-review-card:focus-visible",
        '.nilm-review-card[aria-pressed="true"]:focus-visible',
    ):
        assert selector in asset
    assert "outline: none" in asset
    assert "0 0 0 2px var(--card-background-color" in asset
    assert "0 0 0 5px var(--primary-color" in asset


def test_nilm_workspace_renders_review_lanes_from_payload() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [],
  label_intervals: [],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  edges: [],
  validation: {},
  lanes: {
    needs_review: {
      label: "Needs Review",
      signature_ids: ["sig-new"],
      assignment_ids: []
    },
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-1"]
    },
    needs_validation: {
      label: "Needs Validation",
      signature_ids: [],
      assignment_ids: ["assignment-2"]
    },
    ready_to_publish: {
      label: "Ready to Publish",
      signature_ids: [],
      assignment_ids: ["assignment-3", "assignment-4"]
    },
    published: {
      label: "Published",
      signature_ids: [],
      assignment_ids: ["assignment-5"]
    },
    ignored_expected: {
      label: "Ignored / Expected",
      signature_ids: ["sig-ignored"],
      assignment_ids: []
    }
  },
  lane_counts: {
    needs_review: 1,
    assigned: 1,
    needs_validation: 1,
    ready_to_publish: 2,
    published: 1,
    ignored_expected: 1
  }
};
const html = panel._renderNilmWorkspaceBody();
for (const expected of [
  "Review lanes",
  "Needs Review",
  "Needs Validation",
  "Ready to Publish",
  "Published",
  "Ignored / Expected",
  'role="tablist"',
  'role="tab"',
  'data-nilm-lane="needs_review"',
  'aria-selected="true"',
  '<strong>2</strong>'
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_nilm_lane_items_preserve_indexes_and_render_one_selected_inspector() -> None:
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
      typical_power_w: 720,
      typical_duration_seconds: 1500,
      seen_count: 4,
      voltage_class: "120v",
      dominant_leg: "a",
      known_load_overlap: "No known-load overlap",
      why_grouped: "Grouped by similar NILM on/off edges around 720 W.",
      last_seen: "2026-06-06T08:00:00+00:00",
      actions: {
        label: {},
        assign: {},
        ignore: {},
        mark_expected: {},
        merge: { target_options: [] }
      }
    },
    { signature_id: "sig-reviewed", user_label: "Dryer", review_state: "confirmed" },
    {
      signature_id: "sig-2",
      display_label: "Unknown load 2",
      confidence: 0.65,
      typical_power_w: 1440,
      actions: { ignore: {} }
    }
  ],
  assignments: [
    { assignment_id: "assignment-reviewed", display_name: "Washer" },
    {
      assignment_id: "assignment-2",
      display_name: "Heat Pump",
      estimated_power_w: 2400,
      actions: { publish: {} }
    }
  ],
  lanes: {
    needs_review: {
      label: "Needs Review",
      signature_ids: ["sig-1", "sig-2"],
      assignment_ids: []
    },
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-2"]
    },
    published: {
      label: "Published",
      signature_ids: [],
      assignment_ids: []
    }
  }
};
const items = panel._nilmLaneItems(panel._nilmWorkspace, "needs_review");
if (items.length !== 2 || items[0].index !== 0 || items[1].index !== 2) {
  throw new Error(`wrong lane items: ${JSON.stringify(items)}`);
}
panel._nilmSelectedReviewKey = panel._nilmReviewKey(items[1]);
const html = panel._renderNilmReviewLayout(panel._nilmWorkspace);
if (!html.includes('aria-pressed="true"') || !html.includes("Unknown load 2")) {
  throw new Error(`selection not reflected: ${html}`);
}
if (!html.includes('data-nilm-apply-decision="2"')) {
  throw new Error(`signature lost original index: ${html}`);
}
if ((html.match(/data-nilm-review-inspector/g) || []).length !== 1) {
  throw new Error(`expected one inspector: ${html}`);
}
const selectedCard = html.indexOf('data-nilm-review-item="signature:sig-2"');
const inspector = html.indexOf(
  '<div class="nilm-review-inspector" data-nilm-review-inspector'
);
const beforeInspector = html.slice(selectedCard, inspector).trimEnd();
if (selectedCard < 0 || inspector < 0 || !beforeInspector.endsWith("</button>")) {
  throw new Error(`inspector did not follow the selected card: ${html}`);
}

panel._nilmActiveLane = "assigned";
panel._nilmSelectedReviewKey = "";
const assignmentHtml = panel._renderNilmReviewLayout(panel._nilmWorkspace);
if (!assignmentHtml.includes('data-nilm-assignment-index="1"')) {
  throw new Error(`assignment lost original index: ${assignmentHtml}`);
}

panel._nilmActiveLane = "published";
const emptyHtml = panel._renderNilmReviewLayout(panel._nilmWorkspace);
if (!emptyHtml.includes("data-nilm-lane-empty")) {
  throw new Error(`empty lane did not explain its state: ${emptyHtml}`);
}
"""
    )


def test_nilm_explicit_empty_needs_review_lane_is_authoritative() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  signatures: [
    {
      signature_id: "sig-assigned",
      display_label: "Assigned load",
      review_state: "new"
    },
    {
      signature_id: "sig-merged",
      display_label: "Merged load",
      review_state: "merged"
    }
  ],
  assignments: [
    {
      assignment_id: "assignment-1",
      display_name: "Assigned appliance",
      signature_id: "sig-assigned"
    }
  ],
  lanes: {
    needs_review: {
      label: "Needs Review",
      signature_ids: [],
      assignment_ids: []
    },
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-1"]
    },
    ignored_expected: {
      label: "Ignored / Expected",
      signature_ids: ["sig-merged"],
      assignment_ids: []
    }
  },
  lane_counts: { needs_review: 0 }
};

const items = panel._nilmLaneItems(panel._nilmWorkspace, "needs_review");
if (items.length !== 0) {
  throw new Error(`explicit empty lane was repopulated: ${JSON.stringify(items)}`);
}

const lanesHtml = panel._renderNilmWorkspaceLanes(panel._nilmWorkspace);
const tabStart = lanesHtml.indexOf('data-nilm-lane="needs_review"');
const tabEnd = lanesHtml.indexOf("</button>", tabStart);
const needsReviewTab = lanesHtml.slice(tabStart, tabEnd);
if (!needsReviewTab.includes("<strong>0</strong>")) {
  throw new Error(`needs review count disagreed with payload: ${lanesHtml}`);
}

const html = panel._renderNilmReviewLayout(panel._nilmWorkspace);
if ((html.match(/data-nilm-lane-empty/g) || []).length !== 1) {
  throw new Error(`expected one stable empty status: ${html}`);
}
for (const expected of [
  'id="nilm_review_lane_panel"',
  'role="tabpanel"',
  'aria-labelledby="nilm_lane_needs_review"'
]) {
  if (!html.includes(expected)) {
    throw new Error(`empty lane lost tabpanel ${expected}: ${html}`);
  }
}
if (html.includes("data-nilm-review-inspector")) {
  throw new Error(`empty lane rendered an inspector: ${html}`);
}
"""
    )


def test_nilm_lane_tabs_change_selection_without_fetching() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
let rendered = 0;
let fetched = 0;
panel._render = () => { rendered += 1; };
panel._loadEvidence = () => { fetched += 1; };
panel._nilmSelectedReviewKey = "signature:sig-1";
panel._nilmFocusedSignature = "fingerprint-1";

panel._activateNilmLane("assigned");

if (panel._nilmActiveLane !== "assigned") {
  throw new Error(`lane did not change: ${panel._nilmActiveLane}`);
}
if (panel._nilmSelectedReviewKey || panel._nilmFocusedSignature) {
  throw new Error("lane change did not clear stale selection state");
}
if (rendered !== 1 || fetched !== 0) {
  throw new Error(`lane change rerender/fetch mismatch: ${rendered}/${fetched}`);
}
"""
    )


def test_nilm_review_power_percent_scales_and_clamps() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const reviewItems = [
  { kind: "signature", item: { typical_power_w: 250 }, index: 0 },
  { kind: "assignment", item: { estimated_power_w: 1000 }, index: 0 }
];
const cases = [
  [reviewItems[0], 25],
  [{ kind: "signature", item: { median_power_w: 2000 }, index: 1 }, 100],
  [{ kind: "signature", item: { typical_power_w: -50 }, index: 2 }, 0],
  [{ kind: "signature", item: {}, index: 3 }, 0]
];
for (const [item, expected] of cases) {
  const actual = panel._nilmPowerPercent(item, reviewItems);
  if (actual !== expected) {
    throw new Error(`power percent ${actual} did not equal ${expected}`);
  }
}

const cardItem = {
  kind: "signature",
  item: {
    signature_id: "sig-1",
    display_label: "Load",
    typical_power_w: 250,
    confidence: 1.4
  },
  index: 0
};
const html = panel._renderNilmReviewCard(cardItem, reviewItems, false);
for (const expected of [
  '--power-percent:25%',
  '<span>100%</span>',
  '<progress max="100" value="100"'
]) {
  if (!html.includes(expected)) {
    throw new Error(`review card missed ${expected}: ${html}`);
  }
}
"""
    )


def test_nilm_lane_count_badge_respects_radius_limit() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")
    start = asset.index(".nilm-lane strong {")
    end = asset.index("\n        }", start)
    rule = asset[start:end]

    assert "border-radius: 8px" in rule
    assert "999px" not in rule


def test_nilm_workspace_graph_controls_use_accessible_icons() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderNilmGraphControls({
  start: 0,
  end: 3600000,
  min: 0,
  max: 7200000
});
for (const icon of [
  'icon="mdi:magnify-plus-outline"',
  'icon="mdi:magnify-minus-outline"',
  'icon="mdi:chevron-left"',
  'icon="mdi:chevron-right"'
]) {
  if (!html.includes(icon)) {
    throw new Error(`missing graph control ${icon}: ${html}`);
  }
}
for (const name of ["Zoom In", "Zoom Out", "Pan Earlier", "Pan Later"]) {
  for (const attribute of ["title", "aria-label"]) {
    const expected = `${attribute}="${name}"`;
    if (!html.includes(expected)) {
      throw new Error(`missing graph control name ${expected}: ${html}`);
    }
  }
}
"""
    )


def test_nilm_interval_editor_is_progressively_disclosed() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [],
  label_intervals: [],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  edges: [],
  validation: {},
  actions: {},
  lanes: {
    needs_review: { label: "Needs Review", signature_ids: [], assignment_ids: [] },
  },
};
const initialHtml = panel._renderNilmWorkspaceBody();
if (!initialHtml.includes('data-nilm-open-interval-editor')) {
  throw new Error(`missing explicit Label interval control: ${initialHtml}`);
}
if (initialHtml.includes('class="nilm-interval-form"')) {
  throw new Error(`interval form was not progressively disclosed: ${initialHtml}`);
}
panel._render = () => {};
panel._selectNilmEdgeTime({
  dataset: {
    nilmEdgeTime: "2026-06-24T18:12:00Z",
    nilmEdgeDirection: "on",
  },
});
const selectedHtml = panel._renderNilmWorkspaceBody();
if (
  !panel._nilmIntervalEditorOpen
  || !selectedHtml.includes('class="nilm-interval-form"')
) {
  throw new Error(`edge selection did not reveal interval editor: ${selectedHtml}`);
}
const graph = selectedHtml.indexOf('class="workspace-section nilm-graph-section"');
const editor = selectedHtml.indexOf(
  'class="workspace-section nilm-interval-editor-section"'
);
const lanes = selectedHtml.indexOf('role="tablist"');
if (!(graph >= 0 && graph < editor && editor < lanes)) {
  throw new Error(`interval editor is not directly below graph: ${selectedHtml}`);
}
const secondary = panel._renderNilmSecondaryCollections(panel._nilmWorkspace);
if (
  !secondary.includes('data-nilm-secondary-details')
  || !secondary.includes('<details')
) {
  throw new Error(`secondary collections lost their disclosure: ${selectedHtml}`);
}
if (secondary.includes('class="nilm-interval-form"')) {
  throw new Error(
    `secondary disclosure still owns the active interval editor: ${secondary}`
  );
}
"""
    )


def test_nilm_secondary_collections_use_one_disclosure() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderNilmSecondaryCollections({
  label_intervals: [],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  edges: [],
  validation: {},
  actions: {},
});
if ((html.match(/<details/g) || []).length !== 1) {
  throw new Error(`expected one secondary disclosure: ${html}`);
}
for (const expected of [
  "Sessions, assignments, validation, and technical details",
  "Manual Labels",
  "Estimated Appliances",
  "Appliance Assignments",
  "Validation",
  "NILM Sessions",
  "NILM Edges",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing secondary collection ${expected}: ${html}`);
  }
}
if (html.includes('data-nilm-decision')) {
  throw new Error(`secondary disclosure duplicated signature decisions: ${html}`);
}
"""
    )


def test_nilm_full_workspace_has_one_owner() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmActiveLane = "assigned";
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [],
  label_intervals: [],
  virtual_appliances: [],
  assignments: [{
    assignment_id: "assignment-1",
    appliance_id: "dishwasher",
    display_name: "Dishwasher",
    appliance_profile: "dishwasher",
    lifecycle_state: "assigned",
    confidence: 0.8,
    appliance_detail_path: "/detail/dishwasher",
    actions: {
      rename: {},
      change_profile: {
        profile_options: [{ value: "dishwasher", label: "Dishwasher" }],
      },
      merge: {
        target_options: [{ value: "assignment-2", label: "Washer" }],
      },
      validate_history: {},
      publish: {},
      unpublish: {},
      retire: {},
    },
  }],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: Array.from({ length: 6 }, (_, index) => ({
    session_id: `session-${index + 1}`,
    assignment_id: "assignment-1",
    display_name: `Dishwasher ${index + 1}`,
    start: `2026-06-24T${String(10 + index).padStart(2, "0")}:00:00Z`,
    end: `2026-06-24T${String(10 + index).padStart(2, "0")}:30:00Z`,
    actions: { assign: {}, validate: {}, reject: {} },
  })),
  edges: [],
  validation: {},
  actions: {},
  lanes: {
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-1"],
    },
  },
};
const html = panel._renderNilmWorkspaceBody();
const unique = [
  'id="nilm_assignment_label_0"',
  'id="nilm_assignment_profile_0"',
  'id="nilm_assignment_merge_target_0"',
  'data-nilm-assignment-index="0" data-nilm-assignment-action="save"',
  'data-nilm-assignment-index="0" data-nilm-assignment-action="validate_history"',
  'data-nilm-assignment-index="0" data-nilm-assignment-action="publish"',
  'data-nilm-assignment-index="0" data-nilm-assignment-action="unpublish"',
  'data-nilm-assignment-index="0" data-nilm-assignment-action="retire"',
];
for (const marker of unique) {
  const count = html.split(marker).length - 1;
  if (count !== 1) {
    throw new Error(`expected one owner for ${marker}, got ${count}: ${html}`);
  }
}
for (let index = 0; index < 6; index += 1) {
  for (const marker of [
    `id="nilm_session_label_${index}"`,
    `data-nilm-session-index="${index}" data-nilm-session-action="assign"`,
    `data-nilm-session-index="${index}" data-nilm-session-action="validate"`,
    `data-nilm-session-index="${index}" data-nilm-session-action="reject"`,
  ]) {
    const count = html.split(marker).length - 1;
    if (count !== 1) {
      throw new Error(
        `expected one owner for session ${index}: ${marker}, got ${count}`
      );
    }
  }
}
const secondary = panel._renderNilmSecondaryCollections(panel._nilmWorkspace);
for (const interactive of [
  'id="nilm_assignment_label_0"',
  'id="nilm_assignment_profile_0"',
  'id="nilm_assignment_merge_target_0"',
  'data-nilm-assignment-action',
  'data-nilm-appliance-detail-path',
]) {
  if (secondary.includes(interactive)) {
    throw new Error(`secondary assignment was not read-only: ${interactive}`);
  }
}
if (!secondary.includes("Dishwasher") || !secondary.includes("Confidence 80%")) {
  throw new Error(`secondary assignment summary disappeared: ${secondary}`);
}
"""
    )


def test_nilm_signature_review_hides_unavailable_decisions() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  signatures: [
    {
      signature_id: "sig-ignore-only",
      display_label: "Unknown load",
      actions: {
        ignore: {
          domain: "circuitsetup_energy_analyzer",
          service: "ignore_nilm_signature",
          data: { circuit_id: "mains", signature_id: "sig-ignore-only" }
        }
      }
    }
  ]
};
const html = panel._renderNilmDecisionFlow(panel._nilmWorkspace.signatures[0], 0);
for (const expected of [
  'name="nilm_decision_0"',
  'value="ignore"',
  'data-nilm-apply-decision="0"'
]) {
  if (!html.includes(expected)) {
    throw new Error(`expected available decision ${expected}: ${html}`);
  }
}
for (const unexpected of [
  'value="identify"',
  'value="mark_expected"',
  'value="merge"',
]) {
  if (html.includes(unexpected)) {
    throw new Error(`rendered unavailable decision ${unexpected}: ${html}`);
  }
}
"""
    )


def test_nilm_decision_flow_renders_one_apply_without_direct_action_wall() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const signature = {
  signature_id: "sig-1",
  actions: {
    label: {},
    assign: {},
    ignore: {},
    mark_expected: {},
    merge: { target_options: [{ value: "sig-2", label: "Load 2" }] }
  }
};
panel._nilmWorkspace = { status: "ok", signatures: [signature] };
const html = panel._renderNilmDecisionFlow(signature, 0);
for (const expected of [
  'name="nilm_decision_0"',
  'value="identify"',
  'value="mark_expected"',
  'value="ignore"',
  'value="merge"',
  'data-nilm-apply-decision="0"'
]) {
  if (!html.includes(expected)) throw new Error(`missing ${expected}: ${html}`);
}
if ((html.match(/data-nilm-apply-decision/g) || []).length !== 1) {
  throw new Error(`expected one NILM Apply action: ${html}`);
}
for (const oldAction of [
  'data-nilm-action="label"',
  'data-nilm-action="assign"',
  'data-nilm-action="ignore"',
  'data-nilm-action="mark_expected"',
  'data-nilm-action="merge"'
]) {
  if (html.includes(oldAction)) {
    throw new Error(`duplicate direct action ${oldAction}: ${html}`);
  }
}
const key = panel._nilmDecisionDraftKey(signature);
panel._nilmLabelDrafts.set(panel._nilmLabelDraftKey(signature), "Washer");
panel._nilmDecisionDrafts.set(key, {
  decision: "identify",
  identifyMode: "assign",
  assignmentId: "assignment-washer",
  mergeTarget: "sig-2",
});
signature.actions.assign.assignment_options = [
  { value: "assignment-washer", label: "Washer" },
];
const identifyHtml = panel._renderNilmDecisionFlow(signature, 0);
for (const expected of [
  'value="assign" selected',
  'value="label"',
  'value="assignment-washer" selected',
  'value="Washer"',
]) {
  if (!identifyHtml.includes(expected)) {
    throw new Error(`identify lost ${expected}: ${identifyHtml}`);
  }
}
panel._nilmDecisionDrafts.set(
  key,
  Object.assign({}, panel._nilmDecisionDraft(signature), { decision: "merge" })
);
const mergeHtml = panel._renderNilmDecisionFlow(signature, 0);
if (!mergeHtml.includes('data-selected="sig-2"')) {
  throw new Error(`merge target draft was discarded: ${mergeHtml}`);
}
"""
    )


def test_nilm_identify_modes_rerender_only_their_relevant_fields() -> None:
    _run_panel_node_script(
        """
const listeners = {};
let rerenders = 0;
const signature = {
  signature_id: "sig-1",
  display_label: "Unknown load",
  actions: {
    label: { service: "label_nilm_signature" },
    assign: {
      service: "assign_nilm_signature",
      assignment_options: [{ value: "assignment-1", label: "Dishwasher" }],
    },
  },
};
const panel = new context.Panel();
const key = panel._nilmDecisionDraftKey(signature);
const identifyMode = {
  value: "label",
  dataset: { nilmDecisionKey: key },
  addEventListener(type, callback) { listeners[type] = callback; },
};
panel._loading = false;
panel._payload = { status: "not_found", actions: {} };
panel._nilmWorkspace = { status: "ok", signatures: [signature] };
panel._nilmDecisionDrafts.set(key, { decision: "identify", identifyMode: "assign" });
panel.shadowRoot = {
  innerHTML: "",
  querySelector() { return null; },
  querySelectorAll(selector) {
    return selector === "[data-nilm-identify-mode]" ? [identifyMode] : [];
  },
};
panel._render();
if (typeof listeners.change !== "function") {
  throw new Error("identify mode change listener was not registered");
}
panel._render = () => { rerenders += 1; };

listeners.change();
const labelHtml = panel._renderNilmDecisionFlow(signature, 0);
for (const semantic of [
  '<fieldset class="decision-group nilm-decision-group"',
  "<legend>",
]) {
  if (!labelHtml.includes(semantic)) {
    throw new Error(`decision choices lack ${semantic}: ${labelHtml}`);
  }
}
if (labelHtml.includes('data-nilm-existing-assignment="signature_0"')) {
  throw new Error(`Label only exposed an ignored assignment selector: ${labelHtml}`);
}
if (!labelHtml.includes('id="nilm_label_0"') || rerenders !== 1) {
  throw new Error(`Label only did not rerender its field: ${labelHtml}`);
}

identifyMode.value = "assign";
listeners.change();
const assignHtml = panel._renderNilmDecisionFlow(signature, 0);
if (!assignHtml.includes('data-nilm-existing-assignment="signature_0"')) {
  throw new Error(`Assign mode did not expose assignment selector: ${assignHtml}`);
}
if (!assignHtml.includes('id="nilm_label_0"') || rerenders !== 2) {
  throw new Error(`Assign mode did not rerender its fields: ${assignHtml}`);
}
"""
    )


def test_nilm_decision_identify_assigns_without_scrolling_to_top() -> None:
    _run_panel_node_script(
        """
(async () => {
const calls = [];
let scrolled = 0;
const panel = new context.Panel();
panel._render = () => {};
panel._scrollToTop = () => { scrolled += 1; };
panel._renderAndScrollToTop = () => { scrolled += 1; };
panel._loadEvidence = async () => {};
panel._hass = {
  callService: async (domain, service, data) => calls.push({ domain, service, data }),
};
panel.shadowRoot.querySelector = (selector) => {
  if (selector === "#nilm_label_0") return { value: "Dishwasher" };
  return null;
};
const signature = {
  signature_id: "sig-1",
  actions: {
    assign: {
      domain: "circuitsetup_energy_analyzer",
      service: "assign_nilm_signature",
      data: { circuit_id: "mains", signature_id: "sig-1" },
    },
    label: {
      domain: "circuitsetup_energy_analyzer",
      service: "label_nilm_signature",
      data: { circuit_id: "mains", signature_id: "sig-1" },
    },
  },
};
panel._nilmWorkspace = { status: "ok", signatures: [signature] };
const key = panel._nilmDecisionDraftKey(signature);
panel._nilmDecisionDrafts.set(key, {
  decision: "identify",
  identifyMode: "assign",
});

await panel._applyNilmDecision(0);

if (calls.length !== 1 || calls[0].service !== "assign_nilm_signature") {
  throw new Error(`identify did not assign: ${JSON.stringify(calls)}`);
}
if (calls[0].data.label !== "Dishwasher") {
  throw new Error(`identify lost its label: ${JSON.stringify(calls[0])}`);
}
if (scrolled !== 0) {
  throw new Error(`identify scrolled to the page top ${scrolled} times`);
}
if (panel._nilmDecisionDrafts.has(key)) {
  const remaining = JSON.stringify([...panel._nilmDecisionDrafts.entries()]);
  throw new Error(
    `successful decision draft was not cleared: ${remaining}`
  );
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_decision_failure_keeps_draft_and_feedback_in_inspector() -> None:
    _run_panel_node_script(
        """
(async () => {
let scrolled = 0;
let focused = 0;
const panel = new context.Panel();
panel._render = () => {};
panel._scrollToTop = () => { scrolled += 1; };
panel._renderAndScrollToTop = () => { scrolled += 1; };
panel._hass = {
  callService: async () => { throw new Error("service failed"); },
};
panel.shadowRoot.querySelector = (selector) => {
  if (selector === "#nilm_label_0") return { value: "Dishwasher" };
  if (selector.startsWith('[data-inline-feedback=')) {
    return { focus() { focused += 1; } };
  }
  return null;
};
const signature = {
  signature_id: "sig-1",
  actions: {
    label: {
      domain: "circuitsetup_energy_analyzer",
      service: "label_nilm_signature",
      data: { circuit_id: "mains", signature_id: "sig-1" },
    },
  },
};
panel._nilmWorkspace = { status: "ok", signatures: [signature] };
const key = panel._nilmDecisionDraftKey(signature);
const draft = { decision: "identify", identifyMode: "label" };
panel._nilmDecisionDrafts.set(key, draft);

await panel._applyNilmDecision(0);

if (panel._nilmDecisionDrafts.get(key) !== draft) {
  throw new Error("failed decision did not retain its draft");
}
if (panel._inlineFeedback.scope !== key || panel._inlineFeedback.kind !== "error") {
  throw new Error(
    `failure escaped inspector feedback: ${JSON.stringify(panel._inlineFeedback)}`
  );
}
if (scrolled !== 0) {
  throw new Error(`failed decision scrolled to the page top ${scrolled} times`);
}
if (focused !== 1) {
  throw new Error(`failed decision focused feedback ${focused} times`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_decision_success_advances_and_keeps_graph_context() -> None:
    _run_panel_node_script(
        """
(async () => {
const panel = new context.Panel();
panel._render = () => {};
panel.shadowRoot.querySelector = () => null;
panel._scrollToTop = () => { throw new Error("decision scrolled to top"); };
panel._hass = { callService: async () => {} };
panel._nilmActiveLane = "needs_review";
panel._nilmSelectedReviewKey = "signature:sig-1";
panel._nilmFocusedSignature = "fingerprint-1";
panel._nilmGraphWindow = { start: 1000, end: 2000, min: 0, max: 3000 };
const first = {
  signature_id: "sig-1",
  feedback_fingerprint: "fingerprint-1",
  actions: {
    ignore: {
      domain: "circuitsetup_energy_analyzer",
      service: "ignore_nilm_signature",
      data: { signature_id: "sig-1" },
    },
  },
};
const second = {
  signature_id: "sig-2",
  feedback_fingerprint: "fingerprint-2",
  actions: { ignore: {} },
};
panel._nilmWorkspace = {
  status: "ok",
  signatures: [first, second],
  assignments: [],
  lanes: {
    needs_review: { signature_ids: ["sig-1", "sig-2"], assignment_ids: [] },
  },
};
const firstKey = panel._nilmDecisionDraftKey(first);
const secondKey = panel._nilmDecisionDraftKey(second);
panel._nilmDecisionDrafts.set(firstKey, { decision: "ignore", identifyMode: "assign" });
panel._nilmDecisionDrafts.set(
  secondKey,
  { decision: "ignore", identifyMode: "assign" }
);
panel._loadNilmWorkspace = async () => {
  panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-2"];
};
let focused = "";
panel._focusNilmSignatureOnGraph = async (fingerprint, options) => {
  focused = fingerprint;
  if (options.scroll !== false || options.toggle !== false) {
    throw new Error(`wrong focus options: ${JSON.stringify(options)}`);
  }
  panel._nilmFocusedSignature = fingerprint;
};

await panel._applyNilmDecision(0);

if (panel._nilmActiveLane !== "needs_review") {
  throw new Error(`decision changed lane: ${panel._nilmActiveLane}`);
}
if (panel._nilmSelectedReviewKey !== "signature:sig-2") {
  throw new Error(`decision did not advance: ${panel._nilmSelectedReviewKey}`);
}
if (focused !== "fingerprint-2") {
  throw new Error(`decision lost graph context: ${focused}`);
}
if (
  panel._nilmDecisionDrafts.has(firstKey)
  || !panel._nilmDecisionDrafts.has(secondKey)
) {
  const keys = JSON.stringify([...panel._nilmDecisionDrafts.keys()]);
  throw new Error(`decision cleared unrelated drafts: ${keys}`);
}
if (
  panel._inlineFeedback.scope !== secondKey
  || panel._inlineFeedback.kind !== "success"
) {
  throw new Error(
    `success feedback was not focused locally: ${JSON.stringify(panel._inlineFeedback)}`
  );
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_signature_cards_carry_graph_focus_without_show_button() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const item = {
  kind: "signature",
  index: 0,
  item: {
    signature_id: "sig-1",
    feedback_fingerprint: "fingerprint-1",
    display_label: "Unknown load",
  },
};
const card = panel._renderNilmReviewCard(item, [item], true);
const inspector = panel._renderNilmSignatureReview(item.item, 0);
if (!card.includes('data-nilm-signature-fingerprint="fingerprint-1"')) {
  throw new Error(`signature card cannot focus graph sessions: ${card}`);
}
for (const duplicate of ["Show on Graph", "data-nilm-signature-focus"]) {
  if (inspector.includes(duplicate)) {
    throw new Error(`inspector kept separate graph action ${duplicate}: ${inspector}`);
  }
}
"""
    )


def test_nilm_review_card_shows_compact_occurrence_and_last_seen_context() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const reviewItem = {
  kind: "signature",
  index: 0,
  item: {
    signature_id: "sig-1",
    display_label: "Unknown load",
    typical_power_w: 1250,
    confidence: 0.82,
    seen_count: 7,
    last_seen: "2026-07-09T14:30:00Z",
  },
};
const html = panel._renderNilmReviewCard(reviewItem, [reviewItem], true);
for (const expected of ["Seen count: 7", "Last seen:", "2026-07-09"]) {
  if (!html.includes(expected)) {
    throw new Error(`review card omitted ${expected}: ${html}`);
  }
}
"""
    )


def test_nilm_failed_interval_save_preserves_open_editor_and_draft() -> None:
    _run_panel_node_script(
        """
(async () => {
const panel = new context.Panel();
panel._render = () => {};
panel.shadowRoot.querySelector = () => null;
let scrolls = 0;
panel._renderAndScrollToTop = () => { scrolls += 1; };
panel._scrollToTop = () => { scrolls += 1; };
panel._nilmIntervalEditorOpen = true;
panel._nilmLabelIntervalDraft = {
  start: "2026-06-24T18:12",
  end: "2026-06-24T19:03",
  label: "Dishwasher",
  appliance_id: "dishwasher",
  ground_truth_entity_id: "",
};
const draft = panel._nilmLabelIntervalDraft;
panel._nilmWorkspace = {
  actions: {
    label_interval: {
      domain: "circuitsetup_energy_analyzer",
      service: "label_nilm_interval",
      data: {},
    },
  },
  label_intervals: [],
};
panel._hass = {
  callService: async () => { throw new Error("save failed"); },
};

await panel._callNilmLabelIntervalAction(-1, "save");

if (!panel._nilmIntervalEditorOpen || panel._nilmLabelIntervalDraft !== draft) {
  throw new Error("failed interval save discarded the open draft");
}
if (scrolls !== 0) {
  throw new Error(`failed interval save scrolled ${scrolls} times`);
}
if (panel._inlineFeedback.scope !== "nilm-interval"
    || panel._inlineFeedback.kind !== "error"
    || panel._nilmIntervalFailedAction !== "save") {
  const state = JSON.stringify({
    feedback: panel._inlineFeedback,
    retry: panel._nilmIntervalFailedAction,
  });
  throw new Error(`failed interval save was not locally retryable: ${state}`);
}
const html = panel._renderNilmLabelIntervalEditor(panel._nilmWorkspace);
if (!html.includes('data-nilm-interval-retry="save"')
    || !html.includes("save failed")) {
  throw new Error(`interval editor hid retry feedback: ${html}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_interval_validation_stays_local_and_keeps_draft_context() -> None:
    _run_panel_node_script(
        """
(async () => {
let scrolls = 0;
const panel = new context.Panel();
panel._render = () => {};
panel.shadowRoot.querySelector = () => null;
panel._renderAndScrollToTop = () => { scrolls += 1; };
panel._scrollToTop = () => { scrolls += 1; };
panel._nilmIntervalEditorOpen = true;
panel._nilmLabelIntervalDraft = {
  start: "2026-06-24T18:12",
  end: "2026-06-24T19:03",
  label: "",
  appliance_id: "",
  ground_truth_entity_id: "",
};
const draft = panel._nilmLabelIntervalDraft;
panel._nilmWorkspace = {
  actions: {
    label_interval: {
      domain: "circuitsetup_energy_analyzer",
      service: "label_nilm_interval",
      data: {},
    },
  },
  label_intervals: [],
};

await panel._callNilmLabelIntervalAction(-1, "save");

if (scrolls !== 0 || panel._nilmLabelIntervalDraft !== draft
    || !panel._nilmIntervalEditorOpen) {
  throw new Error("interval validation lost graph/form context");
}
if (panel._inlineFeedback.scope !== "nilm-interval"
    || panel._inlineFeedback.kind !== "error") {
  const feedback = JSON.stringify(panel._inlineFeedback);
  throw new Error(`interval validation was not local: ${feedback}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_assignment_actions_use_ha_device_workflow_labels() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const publishHtml = panel._renderNilmAssignmentActions({
  assignment_id: "assignment-washer",
  display_name: "Washer",
  actions: { publish: {} }
}, 0);
const unpublishHtml = panel._renderNilmAssignmentActions({
  assignment_id: "assignment-washer",
  display_name: "Washer",
  actions: { unpublish: {} }
}, 0);
for (const expected of ["Create HA Device", "Remove HA Device"]) {
  const html = expected === "Create HA Device" ? publishHtml : unpublishHtml;
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
for (const stale of ["Publish Entities", "Disable Publishing"]) {
  if (publishHtml.includes(stale) || unpublishHtml.includes(stale)) {
    throw new Error(`stale label ${stale}`);
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
const signature = panel._nilmWorkspace.signatures[0];
const key = panel._nilmDecisionDraftKey(signature);
panel._nilmDecisionDrafts.set(key, { decision: "identify", identifyMode: "assign" });
const identifyHtml = panel._renderNilmWorkspaceBody();
if ((identifyHtml.match(/id="nilm_label_0"/g) || []).length !== 1) {
  throw new Error(`identify label was duplicated: ${identifyHtml}`);
}
if (identifyHtml.includes('id="nilm_merge_targets_0"')) {
  throw new Error(`identify rendered unrelated merge controls: ${identifyHtml}`);
}
panel._nilmDecisionDrafts.set(key, { decision: "merge", identifyMode: "assign" });
const mergeHtml = panel._renderNilmWorkspaceBody();
if ((mergeHtml.match(/id="nilm_merge_targets_0"/g) || []).length !== 1) {
  throw new Error(`merge target was duplicated: ${mergeHtml}`);
}
if (mergeHtml.includes('id="nilm_label_0"')) {
  throw new Error(`merge rendered unrelated identify controls: ${mergeHtml}`);
}
"""
    )


def test_nilm_workspace_renders_session_validation_cards() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [
    {
      signature_id: "sig-dishwasher",
      feedback_fingerprint: "dishwasher-fingerprint",
      actions: { ignore: {} }
    }
  ],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [
    {
      session_id: "session-dishwasher",
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
      display_label: "Dishwasher",
      assignment_id: "assignment-dishwasher",
      signature_fingerprint: "dishwasher-fingerprint",
      confidence: 0.82,
      median_power_w: 720,
      estimated_energy_kwh: 0.61,
      actions: {
        validate: {},
        reject: {}
      }
    }
  ],
  edges: [],
  validation: {}
};
const html = panel._renderNilmWorkspaceBody();
for (const expected of [
  "Session Validation",
  "Predicted Dishwasher",
  "2026-06-24",
  "51m",
  "Estimated by NILM",
  "Confidence 82%",
  "Correct",
  "Wrong appliance",
  "Adjust Interval",
  'data-nilm-session-action="validate"',
  'data-nilm-session-action="reject"',
  'data-nilm-session-interval-index="0"'
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
for (const duplicate of ["Ignore Similar", 'data-nilm-action="ignore"']) {
  if (html.includes(duplicate)) {
    throw new Error(`session validation duplicated ${duplicate}: ${html}`);
  }
}
"""
    )


def test_nilm_session_validation_actions_reload_workspace_in_place() -> None:
    _run_panel_node_script(
        """
(async () => {
const calls = [];
const loads = [];
let assigned = false;
const panel = new context.Panel();
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
context.window.location.assign = () => { assigned = true; };
panel._render = () => {};
panel._scrollToTop = () => {};
panel._hass = {
  callService: async (domain, service, data) => calls.push({ domain, service, data }),
};
panel._loadEvidence = async (options) => loads.push(options);
panel._nilmWorkspace = {
  sessions: [
    {
      display_name: "Dishwasher",
      actions: {
        validate: {
          domain: "circuitsetup_energy_analyzer",
          service: "validate_nilm_session",
          data: {
            circuit_id: "mains",
            session_id: "session-1",
            assignment_id: "assignment-dishwasher",
          },
        },
      },
    },
  ],
};

await panel._callNilmWorkspaceItemAction("sessions", 0, "validate");

if (assigned) {
  throw new Error("session validation should not force a browser reload");
}
if (calls.length !== 1 || calls[0].service !== "validate_nilm_session") {
  throw new Error(`expected validate service call, got ${JSON.stringify(calls)}`);
}
if (loads.length !== 1 || !loads[0].routeKey.includes("nilm_workspace=1")) {
  throw new Error(
    `expected in-place NILM reload, got ${JSON.stringify(loads)}`
  );
}
if (panel._lastActionMessage !== "Confirmed Dishwasher.") {
  throw new Error(`expected confirmation message, got ${panel._lastActionMessage}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_session_validation_buttons_call_services_or_update_interval() -> None:
    _run_panel_node_script(
        """
(async () => {
const calls = [];
const loads = [];
const panel = new context.Panel();
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
panel._render = () => {};
panel._scrollToTop = () => {};
panel._hass = {
  callService: async (domain, service, data) => calls.push({ domain, service, data }),
};
panel._loadEvidence = async (options) => loads.push(options);
panel._nilmWorkspace = {
  status: "ok",
  signatures: [
    {
      signature_id: "sig-dishwasher",
      feedback_fingerprint: "dishwasher-fingerprint",
      actions: {
        ignore: {
          domain: "circuitsetup_energy_analyzer",
          service: "ignore_nilm_signature",
          data: {
            circuit_id: "mains",
            signature_id: "sig-dishwasher",
          },
        },
      },
    },
  ],
  sessions: [
    {
      session_id: "session-dishwasher",
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
      display_name: "Dishwasher",
      assignment_id: "assignment-dishwasher",
      signature_fingerprint: "dishwasher-fingerprint",
      actions: {
        validate: {
          domain: "circuitsetup_energy_analyzer",
          service: "validate_nilm_session",
          data: {
            circuit_id: "mains",
            session_id: "session-dishwasher",
            assignment_id: "assignment-dishwasher",
          },
        },
        reject: {
          domain: "circuitsetup_energy_analyzer",
          service: "reject_nilm_session",
          data: {
            circuit_id: "mains",
            session_id: "session-dishwasher",
            assignment_id: "assignment-dishwasher",
          },
        },
      },
    },
  ],
};

await panel._callNilmWorkspaceItemAction("sessions", 0, "validate");
if (calls[calls.length - 1].service !== "validate_nilm_session") {
  throw new Error(`Correct did not call validate service: ${JSON.stringify(calls)}`);
}
if (loads.length !== 1) {
  throw new Error(`Correct did not reload NILM: ${JSON.stringify(loads)}`);
}
if (panel._lastActionMessage !== "Confirmed Dishwasher.") {
  throw new Error(`Correct used wrong label: ${panel._lastActionMessage}`);
}

await panel._callNilmWorkspaceItemAction("sessions", 0, "reject");
if (calls[calls.length - 1].service !== "reject_nilm_session") {
  throw new Error(`Wrong appliance missed reject: ${JSON.stringify(calls)}`);
}
if (loads.length !== 2) {
  throw new Error(`Wrong appliance did not reload NILM: ${JSON.stringify(loads)}`);
}
if (panel._lastActionMessage !== "Marked Dishwasher for review.") {
  throw new Error(`Wrong appliance used wrong label: ${panel._lastActionMessage}`);
}

panel._selectNilmSessionIntervalByIndex(0);
const expectedStart = panel._datetimeLocalFromMillis(
  Date.parse("2026-06-24T18:12:00Z")
);
const expectedEnd = panel._datetimeLocalFromMillis(
  Date.parse("2026-06-24T19:03:00Z")
);
if (
  panel._nilmLabelIntervalDraft.start !== expectedStart
  || panel._nilmLabelIntervalDraft.end !== expectedEnd
) {
  throw new Error(
    `Adjust Interval range: ${JSON.stringify(panel._nilmLabelIntervalDraft)}`
  );
}
if (!panel._nilmIntervalEditorOpen) {
  throw new Error("Adjust Interval did not open the editable interval form");
}

await panel._callNilmAction(0, "ignore");
if (calls[calls.length - 1].service !== "ignore_nilm_signature") {
  throw new Error(`Ignore Similar missed service: ${JSON.stringify(calls)}`);
}
if (panel._lastActionMessage !== "Ignored signature.") {
  throw new Error(`Ignore Similar message: ${panel._lastActionMessage}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_panel_action_message_clears_on_evidence_route_change() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const routes = [];
panel._loadedRouteKey = "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge";
panel._lastActionMessage = "Marked as not helpful.";
panel._loadEvidence = (options) => routes.push(options.routeKey);
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?circuit_id=hvac";

panel._loadEvidenceIfRouteChanged();

if (panel._lastActionMessage) {
  throw new Error(
    `expected route change to clear message, got ${panel._lastActionMessage}`
  );
}
if (routes[0] !== "/circuitsetup-energy-analyzer-evidence?circuit_id=hvac") {
  throw new Error(`expected new evidence route load, got ${JSON.stringify(routes)}`);
}
"""
    )


def test_circuit_fallback_does_not_render_historical_alert_heading() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._loading = false;
panel._payload = {
  status: "circuit_found_no_evidence",
  message: "No current alert evidence is available for this circuit.",
  next_step: "Use the available circuit actions below.",
  actions: {},
};
const html = panel._renderNotFound();
if (!html.includes("No current alert evidence")) {
  throw new Error(`expected circuit fallback heading: ${html}`);
}
if (html.includes("Historical alert not found")) {
  throw new Error(
    `circuit fallback should not look stale: ${html}`
  );
}
"""
    )


def test_alert_evidence_panel_reads_fallback_text_from_panel_config() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._panel = {
  config: {
    text: {
      fallbacks: {
        current_circuit_heading: "Translated current evidence heading",
        historical_message: "Translated stale message.",
        historical_next_step: "Translated stale next step.",
      },
      actions: {
        available_circuit_actions: "Translated circuit actions",
      },
    },
  },
};
panel._loading = false;
panel._payload = {
  status: "circuit_found_no_evidence",
  actions: {
    relearn_baseline: {
      service: "relearn_baseline",
      data: { circuit_id: "hvac" },
    },
  },
};
const html = panel._renderNotFound();
for (const expected of [
  "Translated current evidence heading",
  "Translated stale message.",
  "Translated stale next step.",
  "Translated circuit actions",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing translated panel config text ${expected}: ${html}`);
  }
}
"""
    )


def test_chart_points_include_hover_titles_with_label_and_value() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg(
  [
    {
      name: "Kitchen Fridge",
      points: [
        {
          time: Date.parse("2026-06-24T18:12:00Z"),
          value: 123.456,
        },
      ],
    },
  ],
  {
    graph_window_start: "2026-06-24T18:00:00Z",
    graph_window_end: "2026-06-24T19:00:00Z",
    y_axis_label: "W",
  },
);
if (!html.includes("<title>Kitchen Fridge: 123.46 W at ")) {
  throw new Error(`expected point hover title with label and value: ${html}`);
}
"""
    )


def test_nilm_workspace_hides_already_reviewed_session_validation_cards() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  status: "ok",
  history: {},
  signatures: [],
  virtual_appliances: [],
  assignments: [
    {
      assignment_id: "assignment-dishwasher",
      confirmed_session_ids: ["session-confirmed"],
      rejected_session_ids: ["session-rejected"]
    }
  ],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [
    {
      session_id: "session-confirmed",
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
      display_label: "Already Confirmed",
      assignment_id: "assignment-dishwasher",
      actions: { validate: {}, reject: {} }
    },
    {
      session_id: "session-rejected",
      start: "2026-06-24T20:12:00Z",
      end: "2026-06-24T21:03:00Z",
      display_label: "Already Rejected",
      assignment_id: "assignment-dishwasher",
      actions: { validate: {}, reject: {} }
    },
    {
      session_id: "session-pending",
      start: "2026-06-25T18:12:00Z",
      end: "2026-06-25T19:03:00Z",
      display_label: "Pending Dishwasher",
      assignment_id: "assignment-dishwasher",
      actions: { validate: {}, reject: {} }
    }
  ],
  edges: [],
  validation: {}
};
const html = panel._renderNilmWorkspaceBody();
for (const hidden of ["Already Confirmed", "Already Rejected"]) {
  if (html.includes(hidden)) {
    throw new Error(`reviewed session still visible: ${hidden}: ${html}`);
  }
}
if (!html.includes("Predicted Pending Dishwasher")) {
  throw new Error(`pending session missing: ${html}`);
}
"""
    )


def test_nilm_workspace_marks_low_confidence_estimated_sessions() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspaceHistorySeries = [[
  {
    entity_id: "sensor.mains_power",
    state: "200",
    last_changed: "2026-06-24T18:00:00Z"
  },
  {
    entity_id: "sensor.mains_power",
    state: "900",
    last_changed: "2026-06-24T19:10:00Z"
  }
]];
panel._nilmWorkspace = {
  status: "ok",
  history: {
    start: "2026-06-24T18:00:00Z",
    end: "2026-06-24T19:10:00Z"
  },
  signatures: [],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [
    {
      session_id: "session-low",
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
      display_label: "Dishwasher",
      assignment_id: "assignment-dishwasher",
      confidence: 0.7,
      median_power_w: 720,
      estimated_energy_kwh: 0.61,
      actions: { validate: {}, reject: {} }
    }
  ],
  edges: [],
  validation: {}
};
const html = panel._renderNilmWorkspaceBody();
for (const expected of [
  "Estimated by NILM",
  "Low confidence",
  "Confidence 70%",
  'data-nilm-session-confidence="0.70"',
  'data-nilm-low-confidence="true"'
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_nilm_session_validation_adjust_interval_loads_session_times() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
let rendered = false;
panel._render = () => { rendered = true; };
panel._nilmWorkspace = {
  sessions: [
    {
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
    }
  ]
};
panel._selectNilmSessionIntervalByIndex(0);
const expectedStart = panel._datetimeLocalFromMillis(
  Date.parse("2026-06-24T18:12:00Z")
);
const expectedEnd = panel._datetimeLocalFromMillis(
  Date.parse("2026-06-24T19:03:00Z")
);
if (panel._nilmLabelIntervalDraft.start !== expectedStart) {
  throw new Error(`wrong start ${panel._nilmLabelIntervalDraft.start}`);
}
if (panel._nilmLabelIntervalDraft.end !== expectedEnd) {
  throw new Error(`wrong end ${panel._nilmLabelIntervalDraft.end}`);
}
if (panel._lastActionMessage !== "Loaded NILM session interval.") {
  throw new Error(`wrong message ${panel._lastActionMessage}`);
}
if (!rendered) {
  throw new Error("adjust interval did not re-render");
}
if (!panel._nilmIntervalEditorOpen) {
  throw new Error("adjust interval did not open the interval editor");
}
"""
    )


def test_nilm_label_interval_form_asks_whether_appliance_was_running() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmLabelIntervalDraft = {
  start: "2026-06-24T18:12",
  end: "2026-06-24T19:03",
  label: "Dishwasher"
};
const html = panel._renderNilmLabelIntervalEditor({
  label_intervals: [],
  actions: {
    sensor_label_interval: {
      ground_truth_options: []
    }
  }
});
for (const expected of [
  "Was this appliance running here?",
  "Review the selected graph window",
  "Dishwasher",
  "Save Interval"
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
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
        'this._panelText("dashboard_graphs.latest_notification")',
        'this._panelText("dashboard_graphs.view_notification_detail")',
        'this._panelText("dashboard_graphs.title")',
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

const reviewOnly = new context.DashboardGraphs();
reviewOnly.setConfig({ appliance_power_entities: [] });
reviewOnly._loading = false;
reviewOnly._nilmWorkspaceLoading = false;
reviewOnly._nilmWorkspace = {
  status: "ok",
  assignment_count: 0,
  virtual_appliance_count: 0,
  assignments: [],
  virtual_appliances: [],
  history: {},
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  lanes: {
    needs_review: {
      label: "Needs Review",
      signature_ids: ["sig-new"],
      assignment_ids: []
    }
  },
  lane_counts: { needs_review: 1 }
};
reviewOnly._render();
if (!reviewOnly.shadowRoot.innerHTML.includes("Review lanes")) {
  throw new Error("dashboard graph card should show live NILM review lanes");
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
  lanes: {
    needs_review: {
      label: "Needs Review",
      signature_ids: ["sig-new"],
      assignment_ids: []
    },
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-1"]
    },
    needs_validation: {
      label: "Needs Validation",
      signature_ids: [],
      assignment_ids: ["assignment-2"]
    },
    ready_to_publish: {
      label: "Ready to Publish",
      signature_ids: [],
      assignment_ids: ["assignment-3", "assignment-4"]
    },
    published: {
      label: "Published",
      signature_ids: [],
      assignment_ids: ["assignment-5"]
    },
    ignored_expected: {
      label: "Ignored / Expected",
      signature_ids: ["sig-ignored"],
      assignment_ids: []
    }
  },
  lane_counts: {
    needs_review: 1,
    assigned: 1,
    needs_validation: 1,
    ready_to_publish: 2,
    published: 1,
    ignored_expected: 1
  },
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
  "Review lanes",
  "Ready to Publish",
  "2 items",
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
    assert (
        'this._panelText("recommendations.suggested_settings"), grouped.pending'
        in asset
    )
    assert (
        'this._panelText("recommendations.applied_suggested_settings"), '
        "grouped.applied"
        in asset
    )
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


def test_appliance_detail_runtime_formatter_preserves_unknown_values() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")
    formatter_start = asset.index("_formatDuration(value) {")
    formatter_end = asset.index("\n  _formatConfidence(value)", formatter_start)
    formatter = asset[formatter_start:formatter_end]

    null_guard = "value === null || value === undefined"
    coercion = "Number(value)"

    assert null_guard in formatter
    assert formatter.index(null_guard) < formatter.index(coercion)


def test_appliance_detail_percent_comparisons_format_without_extra_space() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const rendered = panel._formatComparisonValue({ unit: "%" }, 74);
if (rendered !== "74%") {
  throw new Error(`expected compact percent label, got ${rendered}`);
}
"""
    )


def test_setup_health_panel_route_is_wired_to_read_only_payload() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")
    setup_health_api_path = (
        'const SETUP_HEALTH_API_PATH = '
        '"/api/circuitsetup_energy_analyzer/setup_health";'
    )
    setup_health_call_api_path = (
        'const SETUP_HEALTH_CALL_API_PATH = '
        '"circuitsetup_energy_analyzer/setup_health";'
    )

    assert setup_health_api_path in asset
    assert setup_health_call_api_path in asset
    assert 'const SETUP_HEALTH_QUERY_PARAM = "setup_health";' in asset
    assert "_routeRequestsSetupHealth" in asset
    assert "_loadSetupHealth" in asset
    assert 'routeUrl.searchParams.get("entry_id")' in asset
    assert "SETUP_HEALTH_CALL_API_PATH}${query ? `?${query}` : \"\"}" in asset
    assert "_renderSetupHealthBody" in asset


def test_setup_health_panel_renders_next_step_only_in_checklist() -> None:
    body = """
const panel = new context.Panel();
const basePath = "/config/integrations/dashboard#config_entry=entry-hvac";
const escapedBasePath = "/config/integrations/dashboard#config_entry=entry-hvac";
const advancedHref = 'href="' + escapedBasePath
  + "&amp;circuit_id=hvac&amp;options_step=advanced_settings" + '"';
const entityDetailHref = 'href="' + escapedBasePath
  + "&amp;options_step=entity_detail" + '"';
panel._setupHealthLoading = false;
panel._setupHealthError = "";
panel._setupHealth = {
  status: "ok",
  text: __SETUP_HEALTH_TEXT__,
  state: "Configure breaker amps",
  next_step: "Configure breaker amps for HVAC",
  message: "Configure breaker amps for HVAC",
  open_path: `${basePath}&options_step=sources`,
  issue_count: 1,
  checklist_ready_count: 1,
  checklist_total_count: 3,
  checklist: [
    { item_id: "source_data_found", status: "ok" },
    {
      item_id: "entity_detail_level_selected",
      status: "needs_attention",
      title: "Entity detail level selected",
      why_it_matters: "Choose how much setup detail Home Assistant should create.",
      fix: "Choose entity detail level",
      open_path: `${basePath}&options_step=entity_detail`,
    },
  ],
  issues: [
    {
      issue: "missing_capacity_setting",
      severity: "warning",
      fix: "Configure breaker amps for HVAC",
      reason: "Capacity tracking needs the circuit breaker size.",
      affected_circuit_name: "HVAC",
      open_path: `${basePath}&circuit_id=hvac&options_step=advanced_settings`,
    },
  ],
};
const rendered = panel._renderSetupHealthContent();
for (const unexpected of [
  ">Status<",
  ">Next Step<",
  ">Checklist<",
  ">Issues<",
  "What To Check First",
  "This affects appliance analysis quality.",
  "source_data_found",
]) {
  if (rendered.includes(unexpected)) {
    throw new Error(`unexpected setup health duplicate or raw text: ${unexpected}`);
  }
}
const nextStepCount = (
  rendered.match(/Configure breaker amps for HVAC/g) || []
).length;
if (nextStepCount !== 1) {
  throw new Error(
    `expected one next-step rendering in checklist, got ${nextStepCount}`,
  );
}
for (const expected of [
  "Source data found",
  "Confirms Home Assistant is receiving live readings for each circuit.",
  "Entity detail level selected",
  "Capacity tracking needs the circuit breaker size.",
  "Open setting",
  advancedHref,
  entityDetailHref,
]) {
  if (!rendered.includes(expected)) {
    throw new Error(`missing setup health checklist content: ${expected}`);
  }
}
"""
    _run_panel_node_script(
        body.replace(
            "__SETUP_HEALTH_TEXT__",
            json.dumps(_translations()["config_panel"]["panel"]["setup_health"]),
        )
    )


def test_setup_health_user_text_lives_in_translations() -> None:
    translations = _translations()
    setup_health = translations["config_panel"]["panel"]["setup_health"]
    checklist = setup_health["checklist"]

    for item_id in (
        "source_data_found",
        "circuit_assignments_reviewed",
        "ct_direction_valid",
        "cumulative_kwh_sources_found",
        "appliance_profiles_selected",
        "entity_detail_level_selected",
        "dashboard_created",
        "notifications_enabled",
        "nilm_enabled",
        "learning_progress",
    ):
        assert checklist[item_id]["title"]
        assert checklist[item_id]["why_it_matters"]
        assert checklist[item_id]["fix"]

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            INTEGRATION_DIR / "entities" / "setup_health.py",
            INTEGRATION_DIR / "frontend" / "energy-analyzer-panel.js",
            INTEGRATION_DIR / "panel.py",
        )
    )
    translated_text = json.dumps(setup_health)
    for text in (
        "Confirms Home Assistant is receiving live readings for each circuit.",
        "Names, profiles, and sensor roles identify each circuit.",
        "Checks that power flow matches the selected circuit role.",
        "Energy totals power today-vs-normal and utility comparisons.",
        "Profiles choose the right runtime, standby, demand, and context checks.",
        "Controls which helper sensors and dashboard diagnostics HA creates.",
        "Provides setup health, appliance status, and evidence links in one view.",
        "Keeps alert notifications linked to the evidence that caused them.",
        "Optional mains NILM can discover unknown loads from aggregate sensors.",
        "Recent history is needed before comparisons and alerts become reliable.",
        "Open setting",
        "No setup checklist items are available yet.",
        "Setup Health is not available because the integration is not loaded.",
        "Reload the integration, then open Setup Health again.",
    ):
        assert text in translated_text
        assert text not in source_text


def test_alert_evidence_panel_text_lives_in_translations() -> None:
    translations = _translations()
    evidence = translations["config_panel"]["panel"]["evidence"]
    translated_text = json.dumps(evidence)

    for text in (
        "Loading alert evidence...",
        "No current alert evidence",
        "No current alert evidence is available for this circuit.",
        "Historical alert not found",
        "The alert from this notification is no longer available.",
        (
            "Open a newer notification or review the appliance summary sensors "
            "for current evidence."
        ),
        "Available Circuit Actions",
    ):
        assert text in translated_text


def test_config_panel_translations_do_not_have_edge_whitespace() -> None:
    translations = _translations()["config_panel"]
    for path, value in _iter_translation_strings(translations, ("config_panel",)):
        assert value == value.strip(), ".".join(path)


def test_dynamic_panel_static_text_lives_in_translations() -> None:
    translations = _translations()
    panel_text = translations["config_panel"]["panel"]
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            PANEL_ASSET,
            INTEGRATION_DIR / "panel.py",
        )
    )
    translated_text = json.dumps(panel_text)

    for text in (
        "Appliance Detail",
        "NILM Workspace",
        "Recommendation Evidence",
        "Respond to this alert",
        "Pause alerts for maintenance",
        "Tune this circuit",
        "Retry",
        "Action complete.",
        "Could not run {service}: {message}",
        (
            "Home Assistant service calls are not available in this panel "
            "session. Reload Home Assistant and try again."
        ),
        "Today vs Normal",
        "Behavior Expectations",
        "What To Check First",
        "Alerts and Evidence",
        "No actions are available for this appliance right now.",
        "NILM Signatures",
        "Estimated Appliances",
        "Appliance Assignments",
        "Manual Labels",
        "Session Validation",
        "Prediction Preview",
        "Known Load Overlays",
        "Solar/Net Overlays",
        "Show known-load overlays",
        "Show solar/net overlays",
        "Zoom In",
        "Zoom Out",
        "Pan Earlier",
        "Pan Later",
        "Graph times shown in {time_zone}.",
        "Matched alert",
        "Latest evidence for circuit",
        "Circuit actions available",
        "Direct meter",
        "Estimated by NILM",
        "Mixed circuit",
        "Unknown",
        "NILM mains power",
        "Loading NILM graphs...",
        "Latest related notification",
        "View notification detail",
    ):
        assert text in translated_text
        assert text not in source_text


def test_notification_and_dashboard_text_live_in_translations() -> None:
    translations = _translations()
    notification_text = translations["config_panel"]["notifications"]
    dashboard_text = translations["config_panel"]["dashboard"]

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            INTEGRATION_DIR / "notifications.py",
            INTEGRATION_DIR / "dashboard.py",
        )
    )
    translated_text = json.dumps(
        {
            "notifications": notification_text,
            "dashboard": dashboard_text,
        }
    )
    for text in (
        "Energy Analyzer Alert",
        "Open evidence",
        "Observed value",
        "Repeated observations",
        "CircuitSetup Energy Analyzer suggested settings",
        "Top appliances right now",
        "Today's Energy",
        "Appliance Status",
        "Known Load Share",
        "Open NILM Graph & Review",
        "Mains, Solar, and NILM",
        "Diagnostics and Evidence",
        "Missing entities",
        "Next step",
    ):
        assert text in translated_text
        assert text not in source_text


def test_dynamic_alert_evidence_panel_previews_recommendation_evidence() -> None:
    asset_path = (
        INTEGRATION_DIR
        / "frontend"
        / "energy-analyzer-panel.js"
    )

    asset = asset_path.read_text(encoding="utf-8")

    assert "_renderSelectedRecommendationEvidence()" in asset
    assert "selected_recommendation" in asset
    assert 'this._panelText("recommendations.recommendation_evidence")' in asset
    assert 'this._panelTextFormat("recommendations.previewing_evidence"' in asset


def test_dynamic_alert_evidence_panel_orders_recommendation_actions() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    preview = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"preview", this._panelText("actions.labels.preview_evidence"), true)'
    )
    apply = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"apply", this._panelText("actions.labels.apply"))'
    )
    dismiss = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"dismiss", this._panelText("actions.labels.dismiss"), true)'
    )
    undo = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"undo", this._panelText("actions.labels.undo"), true)'
    )
    reset = asset.index(
        'this._recommendationActionButton(recommendation, originalIndex, '
        '"reset", this._panelText("actions.labels.reset_default"), true)'
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
        'history.replaceState(history.state, "", routeKey)',
        "this._loadEvidence({ routeKey })",
        "_formatDateTime(value)",
        "${year}-${month}-${day} ${hour12}:${minute}${suffix}",
        "_chartSvg(series, alert)",
        "Date.parse(alert.graph_window_start)",
        "Date.parse(alert.graph_window_end)",
        "_alertActionMessage(actionKey)",
        'this._panelText("actions.groups.respond_title")',
        'this._panelText("actions.groups.pause_title")',
        'this._panelText("actions.groups.tune_title")',
        "messages.alert_acknowledged",
        "messages.marked_expected",
        "messages.marked_unhelpful",
        "messages.saved_label",
        "nilm_workspace.review_state",
    ):
        assert expected in asset
    assert "Retire" not in asset
    assert "Rename Appliance" not in asset
    assert "Change Type" not in asset
    assert "Merge Assignment" not in asset
    assert "Evidence Window" not in asset


def test_alert_evidence_renders_visual_comparison_before_graph_and_details() -> (
    None
):
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._payload = { actions: {} };
const html = panel._renderAlertContent({
  circuit_id: "fridge",
  feature: "daily_energy",
  feature_name: "Daily Energy",
  observed_value: 6.2,
  baseline_value: 3.4,
  expected_value: 3.8,
  threshold: 5.0,
  percent_change: 82,
  repeated_count: 3,
  first_seen: "2026-07-08T10:00:00Z",
  last_seen: "2026-07-08T12:00:00Z",
  what_happened: "Energy increased above the learned range.",
  why_it_matters: "The refrigerator is using more energy than usual.",
  what_to_check_first: "Check the door seal.",
  graph_entities: []
}, { name: "Kitchen Refrigerator" });
const comparison = html.indexOf('data-evidence-comparison="visual"');
const graph = html.indexOf('data-evidence-graph');
const explanation = html.indexOf('data-evidence-explanation');
const technical = html.indexOf('data-evidence-technical');
if (!(comparison >= 0 && comparison < graph && graph < explanation
      && explanation < technical)) {
  throw new Error(`wrong evidence hierarchy: ${html}`);
}
for (const marker of ["observed", "expected", "threshold"]) {
  if (!html.includes(`data-comparison-marker="${marker}"`)) {
    throw new Error(`missing ${marker} marker: ${html}`);
  }
}
"""
    )


def test_alert_route_never_loads_or_renders_nilm_and_response_precedes_details() -> (
    None
):
    _run_panel_node_script(
        """
(async () => {
const requests = [];
const panel = new context.Panel();
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?alert_id=alert-1";
panel._render = () => {};
panel._requestJson = async (apiPath, fetchPath) => {
  requests.push({ apiPath, fetchPath });
  if (apiPath.startsWith("circuitsetup_energy_analyzer/nilm_workspace")) {
    return { status: "ok", signatures: [], history: {} };
  }
  return {
    status: "matched_alert",
    circuit: { circuit_id: "mains", name: "Whole Home" },
    alert: {
      alert_id: "alert-1",
      circuit_id: "mains",
      feature: "daily_energy",
      feature_name: "Daily Energy",
      observed_value: 18.2,
      expected_value: 12.0,
      threshold: 16.0,
      repeated_count: 2,
      graph_entities: [],
      what_happened: "Energy increased.",
      why_it_matters: "The change is worth reviewing.",
      what_to_check_first: "Check recent loads.",
    },
    nilm: {
      workspace_call_api_path:
        "circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains",
      workspace_api_path:
        "/api/circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains",
    },
    actions: { acknowledge: { service: "acknowledge_alert", data: {} } },
  };
};

await panel._loadEvidence({ routeKey: panel._routeKey() });

if (
  requests.length !== 1
  || !requests[0].apiPath.startsWith("circuitsetup_energy_analyzer/alert_evidence")
) {
  const calls = JSON.stringify(requests);
  throw new Error(`alert route loaded another destination: ${calls}`);
}
if (panel._nilmWorkspace !== null) {
  const workspace = JSON.stringify(panel._nilmWorkspace);
  throw new Error(`alert route retained NILM workspace: ${workspace}`);
}
panel._nilmWorkspace = { status: "ok", signatures: [], history: {} };
const html = panel._renderAlertContent(panel._payload.alert, panel._payload.circuit);
for (const forbidden of ["NILM Workspace", "workspace-summary", "nilm-review-layout"]) {
  if (html.includes(forbidden)) {
    throw new Error(`alert evidence embedded NILM content ${forbidden}: ${html}`);
  }
}
const explanation = html.indexOf("data-evidence-explanation");
const response = html.indexOf('class="evidence-section response-section"');
const technical = html.indexOf("data-evidence-technical");
if (!(explanation >= 0 && explanation < response && response < technical)) {
  throw new Error(`response hierarchy is wrong: ${html}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_history_error_stays_in_graph_and_retries_only_history() -> None:
    _run_panel_node_script(
        """
(async () => {
let retryHistory = 0;
let reloadEvidence = 0;
const listeners = {};
const retry = {
  addEventListener(type, callback) { listeners[type] = callback; },
};
const panel = new context.Panel();
panel._loading = false;
panel._historyError = "Could not load history samples.";
panel._payload = {
  status: "matched_alert",
  circuit: { circuit_id: "mains", name: "Whole Home" },
  alert: {
    alert_id: "alert-1",
    circuit_id: "mains",
    feature: "daily_energy",
    observed_value: 18.2,
    expected_value: 12.0,
    repeated_count: 2,
    graph_entities: ["sensor.mains_power"],
  },
  actions: {},
};
const draft = { decision: "identify", identifyMode: "label" };
panel._nilmDecisionDrafts.set("draft", draft);
panel._loadHistory = async () => { retryHistory += 1; };
panel._loadEvidence = async () => { reloadEvidence += 1; };
panel.shadowRoot = {
  innerHTML: "",
  querySelectorAll() { return []; },
  querySelector(selector) {
    return selector === "[data-retry-alert-history]" ? retry : null;
  },
};

panel._render();
if (!panel.shadowRoot.innerHTML.includes("data-alert-history-error")
    || !panel.shadowRoot.innerHTML.includes("data-evidence-graph")) {
  throw new Error(
    `alert history failure left the graph region: ${panel.shadowRoot.innerHTML}`
  );
}
if (typeof listeners.click !== "function") {
  throw new Error("alert history retry listener was not registered");
}
await listeners.click();
if (retryHistory !== 1 || reloadEvidence !== 0) {
  throw new Error(
    `history retry reloaded the wrong operation: ${retryHistory}/${reloadEvidence}`
  );
}
if (panel._nilmDecisionDrafts.get("draft") !== draft) {
  throw new Error("alert history retry discarded unrelated draft context");
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_load_errors_have_workspace_and_graph_scoped_retries() -> None:
    _run_panel_node_script(
        """
(async () => {
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?nilm_workspace=1&circuit_id=mains";

const workspaceListeners = {};
const workspaceRetry = {
  addEventListener(type, callback) { workspaceListeners[type] = callback; },
};
const workspacePanel = new context.Panel();
workspacePanel._loading = false;
workspacePanel._payload = { status: "circuit_found_no_evidence", actions: {} };
workspacePanel._nilmWorkspaceError = "Could not load NILM workspace.";
const decisionDraft = { decision: "ignore" };
workspacePanel._nilmDecisionDrafts.set("draft", decisionDraft);
let workspaceLoads = 0;
let historyLoads = 0;
workspacePanel._loadNilmWorkspace = async () => { workspaceLoads += 1; };
workspacePanel._loadNilmWorkspaceHistory = async () => { historyLoads += 1; };
workspacePanel.shadowRoot = {
  innerHTML: "",
  querySelectorAll() { return []; },
  querySelector(selector) {
    return selector === "[data-retry-nilm-workspace]" ? workspaceRetry : null;
  },
};
workspacePanel._render();
if (!workspacePanel.shadowRoot.innerHTML.includes("data-nilm-workspace-error")) {
  throw new Error(
    `full NILM failure has no workspace retry: ${workspacePanel.shadowRoot.innerHTML}`
  );
}
if (typeof workspaceListeners.click !== "function") {
  throw new Error("workspace retry listener was not registered");
}
await workspaceListeners.click();
if (workspaceLoads !== 1 || historyLoads !== 0
    || workspacePanel._nilmDecisionDrafts.get("draft") !== decisionDraft) {
  throw new Error("workspace retry did not preserve its operation scope");
}

const historyListeners = {};
const historyRetry = {
  addEventListener(type, callback) { historyListeners[type] = callback; },
};
const historyPanel = new context.Panel();
historyPanel._loading = false;
historyPanel._payload = { status: "circuit_found_no_evidence", actions: {} };
historyPanel._nilmWorkspace = {
  status: "ok",
  history: { api_path: "history/period/2026-07-09" },
  signatures: [],
  label_intervals: [],
  virtual_appliances: [],
  assignments: [],
  known_load_overlays: [],
  solar_overlays: [],
  sessions: [],
  edges: [],
  validation: {},
  actions: {},
  lanes: {},
};
historyPanel._nilmWorkspaceHistoryError = "Could not load NILM history.";
const labelDraft = { start: "2026-07-09T10:00", label: "Dryer" };
historyPanel._nilmLabelIntervalDraft = labelDraft;
workspaceLoads = 0;
historyLoads = 0;
historyPanel._loadNilmWorkspace = async () => { workspaceLoads += 1; };
historyPanel._loadNilmWorkspaceHistory = async () => { historyLoads += 1; };
historyPanel.shadowRoot = {
  innerHTML: "",
  querySelectorAll() { return []; },
  querySelector(selector) {
    return selector === "[data-retry-nilm-history]" ? historyRetry : null;
  },
};
historyPanel._render();
const html = historyPanel.shadowRoot.innerHTML;
if (!html.includes("data-nilm-history-error")
    || !html.includes('class="workspace-section nilm-graph-section"')
    || html.includes("No graph history is available yet.")) {
  throw new Error(`NILM history failure was rendered as empty data: ${html}`);
}
if (typeof historyListeners.click !== "function") {
  throw new Error("NILM history retry listener was not registered");
}
await historyListeners.click();
if (historyLoads !== 1 || workspaceLoads !== 0
    || historyPanel._nilmLabelIntervalDraft !== labelDraft) {
  throw new Error("NILM history retry did not preserve graph draft context");
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_failed_nilm_workspace_refresh_does_not_leave_stale_content_visible() -> (
    None
):
    _run_panel_node_script(
        """
(async () => {
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
const panel = new context.Panel();
panel._render = () => {};
panel._payload = { circuit: { circuit_id: "mains" } };
panel._nilmWorkspace = { status: "ok", signatures: [{ signature_id: "stale" }] };
panel._loadedRouteKey = panel._routeKey();
panel._evidenceRequestId = 1;
panel._requestJson = async () => { throw new Error("refresh failed"); };

await panel._loadNilmWorkspace(1, panel._loadedRouteKey);

if (
  panel._nilmWorkspace !== null
  || !panel._nilmWorkspaceError.includes("refresh failed")
) {
  throw new Error(`failed refresh left stale workspace: ${JSON.stringify({
    workspace: panel._nilmWorkspace,
    error: panel._nilmWorkspaceError,
  })}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_evidence_header_shows_latest_evidence_timestamp() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._loading = false;
panel._payload = {
  status: "latest_for_circuit",
  circuit: { circuit_id: "fridge", name: "Kitchen Refrigerator" },
  alert: {
    circuit_id: "fridge",
    feature: "daily_energy",
    message: "Energy increased.",
    observed_value: 6.2,
    expected_value: 3.8,
    repeated_count: 3,
    last_seen: "2026-07-09T12:00:00Z",
  },
  actions: {},
};
panel.shadowRoot = {
  innerHTML: "",
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
panel._render();
const start = panel.shadowRoot.innerHTML.indexOf('<section class="panel page-header">');
const end = panel.shadowRoot.innerHTML.indexOf("</section>", start);
const header = panel.shadowRoot.innerHTML.slice(start, end);
if (!header.includes("Last Seen") || !header.includes("2026-07-09")) {
  throw new Error(`latest timestamp missing from evidence header: ${header}`);
}
"""
    )


def test_alert_evidence_comparison_falls_back_for_incomplete_metrics() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderAlertComparison({ observed_value: 620 });
if (!html.includes('data-evidence-comparison="fallback"')) {
  throw new Error(`missing comparison fallback: ${html}`);
}
if (html.includes('role="img"')) {
  throw new Error(`incomplete comparison rendered a misleading scale: ${html}`);
}
"""
    )


def test_alert_evidence_informational_metrics_are_scoped_and_unframed() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    scoped_start = asset.index("        .evidence-meta .metric,")
    scoped_style = asset[scoped_start : asset.index("}", scoped_start)]
    for selector in (
        ".evidence-meta .metric",
        '[data-evidence-comparison] .metric',
        '[data-evidence-technical] .metric',
    ):
        assert selector in scoped_style
    for declaration in (
        "background: transparent;",
        "border: 0;",
        "border-radius: 0;",
        "padding: 0;",
    ):
        assert declaration in scoped_style

    global_start = asset.index("        .metric {")
    global_style = asset[global_start : asset.index("}", global_start)]
    assert "border: 1px solid" in global_style
    assert "background: var(--secondary-background-color" in global_style


def test_alert_evidence_technical_details_has_minimum_touch_target() -> None:
    asset = PANEL_ASSET.read_text(encoding="utf-8")

    summary_start = asset.index(
        "        [data-evidence-technical] > summary {"
    )
    summary_style = asset[summary_start : asset.index("}", summary_start)]
    for declaration in (
        "box-sizing: border-box;",
        "line-height: 20px;",
        "min-height: 44px;",
        "padding: 12px 0;",
    ):
        assert declaration in summary_style


def test_alert_evidence_comparison_accessible_name_includes_threshold() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const withThreshold = panel._renderAlertComparison({
  observed_value: 6.2,
  expected_value: 3.8,
  threshold: 5,
});
if (!withThreshold.includes(
  'aria-label="Observed 6.2; expected 3.8; threshold 5."'
)) {
  throw new Error(`threshold missing from accessible name: ${withThreshold}`);
}

const withoutThreshold = panel._renderAlertComparison({
  observed_value: 6.2,
  expected_value: 3.8,
});
if (!withoutThreshold.includes(
  'aria-label="Observed 6.2; expected 3.8."'
)) {
  throw new Error(`two-value accessible name changed: ${withoutThreshold}`);
}
if (withoutThreshold.includes("threshold")) {
  throw new Error(`missing threshold still announced: ${withoutThreshold}`);
}
"""
    )


def test_alert_evidence_comparison_marker_positions_are_finite_and_bounded() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const cases = [
  panel._alertComparisonScale({
    observed_value: 6.2,
    expected_value: 3.8,
    threshold: 5,
  }),
  panel._alertComparisonScale({
    observed_value: 5,
    expected_value: 5,
    threshold: 5,
  }),
];
for (const scale of cases) {
  if (!scale || scale.markers.length !== 3) {
    throw new Error(`missing comparison markers: ${JSON.stringify(scale)}`);
  }
  for (const marker of scale.markers) {
    if (!Number.isFinite(marker.position)
        || marker.position < 0 || marker.position > 100) {
      throw new Error(`invalid ${marker.key} position: ${marker.position}`);
    }
  }
}
if (!cases[1].markers.every((marker) => marker.position === 50)) {
  throw new Error(`equal values were not centered: ${JSON.stringify(cases[1])}`);
}
"""
    )


def test_alert_feedback_uses_one_semantic_decision_flow() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._payload = {
  actions: { acknowledge: {}, mark_expected: {}, mark_unhelpful: {} },
};
panel._inlineFeedback = {
  scope: "alert-response",
  kind: "success",
  message: "Saved",
};
const html = panel._renderAlertResponse();
for (const expected of [
  '<fieldset class="decision-group"',
  'name="alert_decision"',
  'value="acknowledge"',
  'value="mark_expected"',
  'value="mark_unhelpful"',
  'id="apply_alert_decision"',
  'aria-live="polite"'
]) {
  if (!html.includes(expected)) throw new Error(`missing ${expected}: ${html}`);
}
if ((html.match(/id="apply_alert_decision"/g) || []).length !== 1) {
  throw new Error(`expected one Apply action: ${html}`);
}
if ((html.match(/aria-live="polite"/g) || []).length !== 1) {
  throw new Error(`expected one live region owner: ${html}`);
}
for (const oldButton of [
  'id="acknowledge"',
  'id="mark_expected"',
  'id="mark_unhelpful"',
]) {
  if (html.includes(oldButton)) {
    throw new Error(`duplicate direct action ${oldButton}: ${html}`);
  }
}
"""
    )


def test_alert_decision_radio_enables_apply_and_feedback_receives_focus() -> None:
    _run_panel_node_script(
        """
const listeners = {};
const applyButton = {
  disabled: true,
  addEventListener() {},
};
const radio = {
  value: "mark_expected",
  addEventListener(type, callback) { listeners[type] = callback; },
};
let focused = 0;
const feedback = { focus() { focused += 1; } };
const panel = new context.Panel();
panel._loading = false;
panel._payload = { status: "not_found", actions: {} };
panel.shadowRoot = {
  innerHTML: "",
  querySelectorAll(selector) {
    return selector === "[data-alert-decision]" ? [radio] : [];
  },
  querySelector(selector) {
    if (selector === "#apply_alert_decision") return applyButton;
    if (selector === '[data-inline-feedback="alert-response"]') return feedback;
    return null;
  },
};
panel._render();
if (typeof listeners.change !== "function") {
  throw new Error("alert decision change listener was not registered");
}
listeners.change();
if (panel._alertDecision !== "mark_expected" || applyButton.disabled) {
  throw new Error("radio change did not enable Apply");
}
panel._render = () => {};
panel._setInlineFeedback("alert-response", "success", "Saved");
if (focused !== 1) throw new Error(`feedback focus count was ${focused}`);
"""
    )


def test_alert_decision_success_stays_local_after_refresh() -> None:
    _run_panel_node_script(
        """
(async () => {
const calls = [];
const loads = [];
let scrolls = 0;
const panel = new context.Panel();
context.window.location.search = "?alert_id=alert-1";
panel._render = () => {};
panel._scrollToTop = () => { scrolls += 1; };
panel.shadowRoot.querySelector = () => null;
panel._hass = {
  callService: async (domain, service, data) => calls.push({ domain, service, data }),
};
panel._payload = {
  alert: { alert_id: "alert-1", circuit_id: "fridge", feature: "daily_energy" },
  actions: {
    mark_expected: {
      service: "mark_alert_expected",
      data: { alert_id: "alert-1" },
    },
  },
};
panel._loadEvidence = async (options) => {
  loads.push(options);
  panel._payload = { status: "historical_alert_not_found", actions: {} };
  panel._loading = false;
};
panel._alertDecision = "mark_expected";

await panel._applyAlertDecision();

if (calls.length !== 1 || calls[0].service !== "mark_alert_expected") {
  throw new Error(`unexpected service calls: ${JSON.stringify(calls)}`);
}
if (loads.length !== 1 || /alert_id=/.test(loads[0].routeKey)
    || !/circuit_id=fridge/.test(loads[0].routeKey)
    || !/feature=daily_energy/.test(loads[0].routeKey)) {
  throw new Error(`response refresh route changed: ${JSON.stringify(loads)}`);
}
if (scrolls !== 0) throw new Error(`response action scrolled ${scrolls} times`);
if (panel._inlineFeedback.scope !== "alert-response"
    || panel._inlineFeedback.kind !== "success"
    || panel._inlineFeedback.message !== "Marked as expected behavior.") {
  throw new Error(`missing local success: ${JSON.stringify(panel._inlineFeedback)}`);
}
const fallback = panel._renderNotFound();
if (!fallback.includes("Marked as expected behavior.")
    || !fallback.includes('data-inline-feedback="alert-response"')) {
  throw new Error(`refresh hid acknowledgement feedback: ${fallback}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_acknowledgement_survives_real_alert_id_refresh() -> None:
    _run_panel_node_script(
        """
(async () => {
const calls = [];
const requests = [];
const replacedPaths = [];
let focused = 0;
let scrolls = 0;
const panel = new context.Panel();
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?alert_id=alert-1";
context.history.replaceState = (_state, _title, path) => {
  replacedPaths.push(path);
  const route = new URL(path, context.window.location.origin);
  context.window.location.pathname = route.pathname;
  context.window.location.search = route.search;
  panel._loadEvidenceIfRouteChanged();
};
panel._render = () => {};
panel._scrollToTop = () => { scrolls += 1; };
panel.shadowRoot.querySelector = () => ({
  focus: () => { focused += 1; },
});
panel._hass = {
  callService: async (domain, service, data) => {
    calls.push({ domain, service, data });
  },
};
panel._payload = {
  alert: {
    alert_id: "alert-1",
    circuit_id: "fridge",
    feature: "daily_energy",
  },
  actions: {
    acknowledge: {
      service: "acknowledge_alert",
      data: { alert_id: "alert-1" },
    },
  },
};
panel._loadedRouteKey = panel._routeKey();
panel._loading = false;
panel._requestJson = async (apiPath, fetchPath) => {
  requests.push({ apiPath, fetchPath });
  return {
    status: "circuit_found_no_evidence",
    circuit: { circuit_id: "fridge", name: "Kitchen Refrigerator" },
    actions: {},
  };
};
panel._alertDecision = "acknowledge";

await panel._applyAlertDecision();

if (calls.length !== 1 || calls[0].service !== "acknowledge_alert") {
  throw new Error(`unexpected service calls: ${JSON.stringify(calls)}`);
}
if (requests.length !== 1
    || /alert_id=/.test(requests[0].apiPath)
    || !/circuit_id=fridge/.test(requests[0].apiPath)
    || !/feature=daily_energy/.test(requests[0].apiPath)) {
  throw new Error(`unexpected refresh request: ${JSON.stringify(requests)}`);
}
if (replacedPaths.length !== 1
    || /alert_id=/.test(replacedPaths[0])
    || panel._routeKey() !== panel._loadedRouteKey) {
  throw new Error(
    `refresh route is not reload-safe: ${JSON.stringify(replacedPaths)}`
  );
}
if (panel._loading || panel._payload.alert
    || panel._payload.status !== "circuit_found_no_evidence") {
  throw new Error(`fallback payload was discarded: ${panel._loading}`);
}
if (scrolls !== 0) throw new Error(`acknowledgement scrolled ${scrolls} times`);
if (focused !== 1) throw new Error(`feedback focus count was ${focused}`);
if (panel._inlineFeedback.message !== "Alert acknowledged.") {
  const feedback = JSON.stringify(panel._inlineFeedback);
  throw new Error(`missing acknowledgement feedback: ${feedback}`);
}
const fallback = panel._renderNotFound();
if (!fallback.includes("Alert acknowledged.")) {
  throw new Error(`fallback hid acknowledgement: ${fallback}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_decision_service_failure_stays_local() -> None:
    _run_panel_node_script(
        """
(async () => {
let loads = 0;
let scrolls = 0;
let focused = 0;
const panel = new context.Panel();
panel._render = () => {};
panel._scrollToTop = () => { scrolls += 1; };
panel.shadowRoot.querySelector = (selector) => (
  selector === '[data-inline-feedback="alert-response"]'
    ? { focus() { focused += 1; } }
    : null
);
panel._hass = {
  callService: async () => { throw new Error("service offline"); },
};
panel._payload = {
  actions: {
    mark_unhelpful: { service: "mark_alert_unhelpful", data: {} },
  },
};
panel._loadEvidence = async () => { loads += 1; };
panel._alertDecision = "mark_unhelpful";

await panel._applyAlertDecision();

if (loads !== 0) throw new Error("failed response unexpectedly refreshed");
if (scrolls !== 0) throw new Error(`failed response scrolled ${scrolls} times`);
if (panel._error) throw new Error(`response failure leaked globally: ${panel._error}`);
if (panel._alertDecision !== "mark_unhelpful") {
  throw new Error(`failed response cleared selection: ${panel._alertDecision}`);
}
if (panel._inlineFeedback.scope !== "alert-response"
    || panel._inlineFeedback.kind !== "error"
    || !panel._inlineFeedback.message.includes("service offline")) {
  throw new Error(`missing local failure: ${JSON.stringify(panel._inlineFeedback)}`);
}
if (focused !== 1) throw new Error(`failed response focused feedback ${focused} times`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_decision_guard_failure_stays_local() -> None:
    _run_panel_node_script(
        """
(async () => {
let calls = 0;
let scrolls = 0;
const panel = new context.Panel();
panel._render = () => {};
panel._scrollToTop = () => { scrolls += 1; };
panel.shadowRoot.querySelector = () => null;
panel._hass = { callService: async () => { calls += 1; } };
panel._payload = {
  actions: {
    mark_expected: {
      service: "mark_alert_expected",
      enabled: false,
      unavailable_label: "Expected feedback is temporarily unavailable.",
    },
  },
};
panel._alertDecision = "mark_expected";

await panel._applyAlertDecision();

if (calls !== 0) throw new Error("guarded response called a service");
if (scrolls !== 0) throw new Error(`guarded response scrolled ${scrolls} times`);
if (panel._error) throw new Error(`guard failure leaked globally: ${panel._error}`);
if (panel._inlineFeedback.scope !== "alert-response"
    || panel._inlineFeedback.kind !== "error"
    || panel._inlineFeedback.message
      !== "Expected feedback is temporarily unavailable.") {
  const feedback = JSON.stringify(panel._inlineFeedback);
  throw new Error(`missing local guard failure: ${feedback}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_decision_requires_a_choice_locally() -> None:
    _run_panel_node_script(
        """
(async () => {
let scrolls = 0;
const panel = new context.Panel();
panel._render = () => {};
panel._scrollToTop = () => { scrolls += 1; };
panel.shadowRoot.querySelector = () => null;

await panel._applyAlertDecision();

if (scrolls !== 0) throw new Error(`decision validation scrolled ${scrolls} times`);
if (panel._inlineFeedback.scope !== "alert-response"
    || panel._inlineFeedback.kind !== "error"
    || panel._inlineFeedback.message !== "Choose a response before applying.") {
  throw new Error(`missing local validation: ${JSON.stringify(panel._inlineFeedback)}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_alert_secondary_actions_and_recommendations_use_disclosures() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._payload = {
  actions: {
    acknowledge: {},
    pause_alerts: {},
    open_appliance_detail: {},
    relearn_baseline: {},
    open_advanced_circuit_settings: {},
  },
  setting_recommendations: [{
    display_label: "Daily threshold",
    status: "pending",
    actions: { apply: {} },
  }],
};
const html = panel._renderAlertContent({
  circuit_id: "fridge",
  feature: "daily_energy",
  graph_entities: [],
}, { name: "Kitchen Refrigerator" });
const response = html.indexOf('id="apply_alert_decision"');
const pause = html.indexOf('data-alert-disclosure="pause"');
const tune = html.indexOf('data-alert-disclosure="tune"');
const recommendations = html.indexOf('data-alert-disclosure="recommendations"');
if (!(response >= 0 && response < pause && pause < tune
      && tune < recommendations)) {
  throw new Error(`wrong response disclosure order: ${html}`);
}
for (const name of ["pause", "tune", "recommendations"]) {
  if (!new RegExp(`<details[^>]+data-alert-disclosure="${name}"`).test(html)) {
    throw new Error(`missing ${name} details disclosure: ${html}`);
  }
}
for (const action of [
  'id="pause_alerts"',
  'id="open_appliance_detail"',
  'id="relearn_baseline"',
  'id="open_advanced_circuit_settings"',
]) {
  if (!html.includes(action)) throw new Error(`missing ${action}: ${html}`);
}
"""
    )


def test_alert_response_and_secondary_disclosures_are_unframed() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._payload = {
  actions: {
    acknowledge: {},
    pause_alerts: {},
    relearn_baseline: {},
  },
};
const html = panel._renderAlertContent({
  circuit_id: "fridge",
  feature: "daily_energy",
  graph_entities: [],
}, { name: "Kitchen Refrigerator" });
const wrappers = [
  html.match(/<section class="([^"]*response-section[^"]*)">/),
  html.match(
    /<details class="([^"]*)" data-alert-disclosure="pause">/
  ),
  html.match(
    /<details class="([^"]*)" data-alert-disclosure="tune">/
  ),
];
for (const wrapper of wrappers) {
  if (!wrapper) throw new Error(`missing alert action wrapper: ${html}`);
  if (wrapper[1].split(/\\s+/).includes("panel")) {
    throw new Error(`alert action wrapper is still framed: ${wrapper[0]}`);
  }
}
if (!html.includes('class="decision-tile"')) {
  throw new Error(`decision choices lost their bordered tile: ${html}`);
}
"""
    )


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


def test_readme_documents_assignment_defaults() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "choose the appliance type, circuit mode, power-flow mode" not in readme_text
    )
    for expected in (
        "choose the appliance type and source sensors",
        "The integration derives circuit mode and power-flow mode",
        "| Profile | Default phase/topology | Default power flow |",
        "| `refrigerator` | Single phase | Load |",
        "| `hvac` | Dual phase when both legs are selected; "
        "otherwise single phase | Load |",
        "| `solar_inverter` | Dual phase | Generation |",
        "| `mains_nilm` | Mains NILM | Mains/net |",
        "| `mixed` | Mixed | Load |",
    ):
        assert expected in readme_text


def test_readme_explains_notification_evidence_workflow() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_text = " ".join(readme_text.split())

    assert "**Open evidence**" in readme_text
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
    assert "Persistent notifications include one final Markdown link" in normalized_text
    assert "link directly to **Configure > Review Suggested Settings**" in readme_text
    assert "visual comparison" in normalized_text
    assert "graph-first evidence" in normalized_text
    assert "focused inspector" in normalized_text
    assert "single **Apply**" in normalized_text
    assert (
        "Alert evidence panel showing observed and expected metrics with "
        "investigation context"
    ) in readme_text
    assert "source graph and investigation context" not in readme_text


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
    assert "Appliance Run Timeline" in readme_text
    assert "NILM Review" in readme_text
    assert "Diagnostics and Evidence" in readme_text
    assert "NILM review lanes" in readme_text
    assert (
        "Needs Review, Assigned, Needs Validation, Ready to Publish, "
        "Published, and Ignored / Expected"
    ) in readme_text
    assert "instead of service-control cards" in readme_text
    assert "expert evidence links and NILM buttons" in readme_text
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
        "The workspace groups work into lanes",
        "Needs Review, Assigned, Needs Validation, Ready to Publish, "
        "Published, and Ignored / Expected",
        "dynamic dashboard NILM card can show the same lane counts "
        "when it is available",
        "appliance-profile choices",
        "Published NILM appliances are marked as estimated",
        "Remove HA Device",
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
        "docs/images/readme/alert-evidence.png",
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
