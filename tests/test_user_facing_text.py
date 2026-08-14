# ruff: noqa: E501 - Embedded JavaScript follows its own readable line width.

from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer"
FRONTEND_DIR = INTEGRATION_DIR / "frontend"
PANEL_ASSET = FRONTEND_DIR / "energy-analyzer-panel.js"
PANEL_MAIN_ASSET = FRONTEND_DIR / "energy-analyzer-panel-main.js"
DASHBOARD_GRAPHS_ASSET = FRONTEND_DIR / "energy-analyzer-dashboard-graphs.js"
PANEL_SHELL_ASSET = FRONTEND_DIR / "energy-analyzer-panel-shell.js"
APPLIANCE_VIEWS_ASSET = FRONTEND_DIR / "energy-analyzer-appliance-views.js"
NILM_WORKSPACE_ASSET = FRONTEND_DIR / "energy-analyzer-nilm-workspace.js"
EVIDENCE_VIEWS_ASSET = FRONTEND_DIR / "energy-analyzer-evidence-views.js"
PANEL_METHOD_ASSETS = (
    PANEL_SHELL_ASSET,
    APPLIANCE_VIEWS_ASSET,
    NILM_WORKSPACE_ASSET,
    EVIDENCE_VIEWS_ASSET,
)
FRONTEND_ASSETS = (
    PANEL_MAIN_ASSET,
    *PANEL_METHOD_ASSETS,
    DASHBOARD_GRAPHS_ASSET,
    PANEL_ASSET,
)
PANEL_RUNTIME_ASSETS = (
    PANEL_MAIN_ASSET,
    *PANEL_METHOD_ASSETS,
    DASHBOARD_GRAPHS_ASSET,
)


def _frontend_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND_ASSETS)


def test_frontend_inherits_home_assistant_typography() -> None:
    panel_shell = PANEL_SHELL_ASSET.read_text(encoding="utf-8")
    dashboard = DASHBOARD_GRAPHS_ASSET.read_text(encoding="utf-8")
    combined = f"{panel_shell}\n{dashboard}"

    assert "font-family: Roboto, Noto, sans-serif" not in combined
    assert "font-family: var(--paper-font-body1_-_font-family" not in combined
    assert ":host {" in panel_shell
    assert "font-family: inherit;" in panel_shell
    assert "font-family: inherit;" in dashboard


def test_home_summary_metrics_fit_the_number_rendered() -> None:
    dashboard = DASHBOARD_GRAPHS_ASSET.read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(auto-fit, minmax(128px, 1fr))" in dashboard
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" not in dashboard


def test_panel_uses_content_header_and_home_assistant_card_tokens() -> None:
    asset = PANEL_SHELL_ASSET.read_text(encoding="utf-8")

    assert '<header class="page-header">' in asset
    assert 'class="panel page-header"' not in asset
    assert "var(--ha-card-border-radius" in asset
    assert "var(--ha-card-box-shadow" in asset


def _run_panel_node_script(body: str) -> None:
    translation_path = INTEGRATION_DIR / "translations" / "en.json"
    panel_text_statement = (
        "const __panelText = JSON.parse("
        f'fs.readFileSync({json.dumps(str(translation_path))}, "utf8")'
        ").config_panel.panel;\n"
    )
    panel_class_statement = json.dumps(
        "const __registered = registerEnergyAnalyzerPanel(registerDashboardGraphs, "
        "[PanelShellMethods, createApplianceViewMethods(PANEL_METHOD_DEPENDENCIES), "
        "createNilmWorkspaceMethods(PANEL_METHOD_DEPENDENCIES), "
        "createEvidenceViewMethods(PANEL_METHOD_DEPENDENCIES)]); "
        "this.Panel = class TestPanel extends "
        "__registered.CircuitSetupEnergyAnalyzerPanel "
        "{ constructor() { super(); this.panel = { config: "
        "{ text: __panelText } }; } };\n"
    )
    dashboard_class_statement = json.dumps(
        "this.DashboardGraphs = class TestDashboardGraphs extends "
        "__registered.CircuitSetupEnergyAnalyzerDashboardGraphs "
        "{ constructor() { super(); this.setConfig({ text: __panelText }); } "
        "setConfig(config) { super.setConfig(Object.assign("
        "{ text: __panelText }, config || {})); } };"
    )
    script = f"""
const fs = require("fs");
const vm = require("vm");
const assert = require("node:assert/strict");
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
const source = {json.dumps([str(path) for path in PANEL_RUNTIME_ASSETS])}
  .map((path) => fs.readFileSync(path, "utf8")
    .replace(/^import .*;$/gm, "")
    .replace(/^export /gm, ""))
  .join("\\n");
vm.runInContext(
  `${{source}}\\n`
  + {json.dumps(panel_text_statement)}
  + {panel_class_statement}
  + {dashboard_class_statement},
  context
);
function makePanel(state = {{}}) {{
  return Object.assign(new context.Panel(), state);
}}
function makeWorkspace({{ lanes = {{}}, lane_counts = {{}}, ...overrides }} = {{}}) {{
  const labels = {{
    needs_review: "Needs Review",
    assigned: "Assigned",
    published: "Published",
    hidden: "Removed",
  }};
  const baseLanes = Object.fromEntries(Object.entries(labels).map(([key, label]) => [
    key, {{ label, signature_ids: [], assignment_ids: [], interval_ids: [] }},
  ]));
  const baseCounts = Object.fromEntries(
    Object.keys(baseLanes).map((key) => [key, 0]),
  );
  return {{
    status: "ok",
    circuit: {{}},
    history: {{}},
    actions: {{}},
    validation: {{}},
    signatures: [],
    assignments: [],
    sessions: [],
    edges: [],
    label_intervals: [],
    virtual_appliances: [],
    known_load_overlays: [],
    solar_overlays: [],
    ...overrides,
    lanes: {{ ...baseLanes, ...lanes }},
    lane_counts: {{ ...baseCounts, ...lane_counts }},
  }};
}}
function makeAction(service, data = {{}}) {{
  return {{ domain: "circuitsetup_energy_analyzer", service, data }};
}}
{body}
"""
    subprocess.run(["node", "-e", script], check=True, cwd=ROOT)


def _translations() -> dict:
    return json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8")
    )


def test_hvac_associations_card_text_has_required_labels_and_placeholders() -> None:
    live_cards = _translations()["config_panel"]["dashboard"]["live_cards"]
    expected = {
        "hvac_associations_title",
        "heating",
        "cooling",
        "learned_baseline",
        "efficiency_percent",
        "recent_response",
        "learning",
        "tracking",
        "needs_attention",
        "stable",
        "faster",
        "slower",
        "supporting_blower",
        "mapped_temperature",
        "minutes_per_degree",
        "not_available",
        "retry",
        "load_error",
        "open_detail",
        "no_hvac_associations",
    }

    assert expected <= live_cards.keys()
    assert all(live_cards[key] for key in expected)
    assert re.findall(r"{(.*?)}", live_cards["mapped_temperature"]) == ["name"]
    assert re.findall(r"{(.*?)}", live_cards["minutes_per_degree"]) == [
        "value",
        "unit",
    ]
    assert re.findall(r"{(.*?)}", live_cards["no_hvac_associations"]) == []


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
    "mains_source_entities": "Mains Source Entities",
    "outdoor_temperature_entity": "Outdoor Temperature or Weather Entity",
    "rain_sensor_entity": "Rain or Weather Entity",
    "rain_intensity_entity": "Rain Intensity Sensor",
    "water_flow_sensor_entities": "Water Flow Sensors",
    "thermostat_entities": "Thermostats",
    "thermostat_temperature_sensor_entities": "Indoor Temperature Sensors",
    "sensitivity": "Alert Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_OPTIONS_LABELS = {
    "source_devices": "Source Devices",
    "extra_source_entities": "Extra Source Entities",
    "demo_source_bundle_enabled": "Load Bundled Demo Sources",
    "outdoor_temperature_entity": "Outdoor Temperature or Weather Entity",
    "rain_sensor_entity": "Rain or Weather Entity",
    "rain_intensity_entity": "Rain Intensity Sensor",
    "water_flow_sensor_entities": "Water Flow Sensors",
    "thermostat_entities": "Thermostats",
    "thermostat_temperature_sensor_entities": "Indoor Temperature Sensors",
    "sensitivity": "Alert Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_MAINS_LABELS = {
    "mains_source_entities": "Mains Source Entities",
    "nilm_detection_enabled": "Enable NILM Detection",
    "nilm_detection_sensitivity": "NILM Detection Sensitivity",
    "known_load_circuits": "Known Load Circuits",
}

EXPECTED_UTILITY_LABELS = {
    "enable_utility_comparison": "Enable Utility Comparison",
    "circuit_id": "Circuit",
    "utility_energy_entity": "Utility Energy Entity",
    "utility_cost_entity": "Utility Cost Entity",
    "utility_statistic_id": "Recorder Statistic ID (advanced)",
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
    "operating_on_threshold_w": "Turn-On Power (W)",
    "operating_on_dwell_seconds": "Turn-On Confirmation Time (seconds)",
    "operating_off_threshold_w": "Turn-Off Power (W)",
    "operating_off_dwell_seconds": "Turn-Off Confirmation Time (seconds)",
    "operating_merge_gap_seconds": "Merge Short Interruptions (seconds)",
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
    "reset_hvac_efficiency_settings_to_defaults": (
        "Reset HVAC Efficiency Settings To Defaults"
    ),
    "linked_thermostat_entities": "Linked Thermostats",
    "hvac_efficiency_change_threshold_pct": "Slower Response Alert Percent",
    "blower_represents_gas_heat": "Blower Represents Gas-Furnace Operation",
    "reset_dual_phase_settings_to_defaults": "Reset Dual-Phase Settings To Defaults",
    "leg_imbalance_warning_ratio": "Leg Imbalance Warning Ratio",
    "leg_imbalance_min_total_power_w": "Leg Imbalance Minimum Total Power W",
    "reset_power_quality_settings_to_defaults": "Reset Power Quality To Defaults",
    "mains_voltage_sag_ratio": "Mains Voltage Sag Ratio",
    "mains_voltage_swell_ratio": "Mains Voltage Spike Ratio",
    "mains_frequency_drop_hz": "Mains Frequency Drop Hz",
    "mains_frequency_spike_hz": "Mains Frequency Spike Hz",
    "mains_voltage_imbalance_ratio": "Mains Voltage Difference Ratio",
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
    "hvac_efficiency_settings": "Weather-Normalized HVAC Response",
    "dual_phase_settings": "Dual-Phase Leg Imbalance",
    "power_quality_settings": "Power Quality",
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
    "direct_circuit_id": "Direct Circuit ID",
    "duration": "Duration",
    "entry_id": "Entry ID",
    "entity_id": "Analyzer Entity",
    "goal_alert_ratio": "Goal Alert Ratio",
    "ground_truth_entity_id": "Reference Entity",
    "helper_circuit_id": "Helper circuit ID",
    "label": "Label",
    "keep_assignment_for_masking": "Keep Assignment For Masking",
    "keep_published_estimate": "Keep Published Estimate",
    "interval_id": "Interval ID",
    "intervals": "Intervals",
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
    "relationship": "Relationship",
    "reference_power_entity_id": "Reference Power Entity",
    "reference_state_entity_id": "Reference State Entity",
    "reference_threshold_w": "Reference Threshold W",
    "reference_on_threshold": "Reference ON Threshold",
    "reference_off_threshold": "Reference OFF Threshold",
    "reference_on_dwell_seconds": "Reference ON Dwell Seconds",
    "reference_off_dwell_seconds": "Reference OFF Dwell Seconds",
    "reference_minimum_interval_seconds": "Reference Minimum Interval Seconds",
    "reference_merge_gap_seconds": "Reference Merge Gap Seconds",
    "reference_maximum_unknown_gap_seconds": "Reference Maximum Unknown Gap Seconds",
    "reference_maximum_power_gap_seconds": "Reference Maximum Power Gap Seconds",
    "relearn": "Relearn",
    "relearn_on_end": "Relearn On End",
    "removed_interval_ids": "Removed interval IDs",
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
    "utility_cost_entity": "Utility Cost Entity",
    "utility_source_type": "Utility Source Type",
    "utility_statistic_id": "Recorder Statistic ID (advanced)",
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
    for days in ("18 days", "45 days", "180 days"):
        assert days in descriptions["retention_mode"]
    assert (
        "saves these source settings"
        in strings["config"]["step"]["user"]["description"].lower()
    )


def test_options_flow_labels_are_human_readable_and_described() -> None:
    strings = _translations()
    init_step = strings["options"]["step"]["init"]
    data = strings["options"]["step"]["sources"]["data"]
    descriptions = strings["options"]["step"]["sources"]["data_description"]

    assert list(init_step["menu_options"]) == [
        "sources",
        "refresh_sources",
        "mains",
        "assign",
        "utility",
        "dashboard",
        "entity_detail",
        "recommendations",
        "advanced",
    ]
    assert init_step["menu_options"] == {
        "sources": "🔌 Edit Source Selection",
        "refresh_sources": "🔄 Refresh Source Sensors",
        "mains": "⚡ Edit Mains Sensors & Known Loads",
        "assign": "🏷️ Appliance Circuit Assignments",
        "utility": "📊 Utility / Opower Comparison",
        "dashboard": "📋 Create Or Update Dashboard",
        "entity_detail": "👁️ Entity Detail Level",
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
    for days in ("18 days", "45 days", "180 days"):
        assert days in descriptions["retention_mode"]
    assert (
        "saves these source settings"
        in strings["options"]["step"]["sources"]["description"].lower()
    )
    refresh_sources = strings["options"]["step"]["refresh_sources"]
    assert refresh_sources["title"] == "Refresh Source Sensors"
    assert "added or renamed" in refresh_sources["description"].lower()
    assert "manual extra sources" in refresh_sources["description"].lower()
    assert "review its appliance assignment" in refresh_sources["description"].lower()
    assert "reload" in refresh_sources["description"].lower()
    assert refresh_sources["submit"] == "Refresh Source Sensors"
    assert (
        "existing settings were not changed"
        in strings["options"]["error"]["no_source_device_entities"].lower()
    )
    refresh_mains = strings["options"]["step"]["refresh_mains"]
    assert refresh_mains["title"] == "Review Refreshed Mains Sensors"
    assert "current replacements" in refresh_mains["description"].lower()
    assert refresh_mains["data"]["mains_source_entities"] == ("Mains Source Entities")
    entity_detail = strings["options"]["step"]["entity_detail"]
    assert entity_detail["data"]["entity_detail_level"] == "Entity Detail Level"
    assert entity_detail["data"]["selected_entity_groups"] == "Expert Entity Groups"
    assert "apply_entity_detail_profile" not in entity_detail["data"]
    assert "create" in entity_detail["description"].lower()
    assert "reloads" in entity_detail["description"].lower()
    assert "simple" in entity_detail["data_description"]["entity_detail_level"].lower()
    assert "creates" in entity_detail["data_description"]["entity_detail_level"].lower()
    assert (
        "expert" in entity_detail["data_description"]["selected_entity_groups"].lower()
    )
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
    assert (
        "reloads"
        in dashboard["data_description"]["apply_entity_detail_profile"].lower()
    )
    assert (
        "instead of creating or updating"
        in dashboard["data_description"]["remove_dashboard"].lower()
    )
    assert (
        "dashboard_layout_requires_higher_entity_detail" in strings["options"]["error"]
    )


def test_mains_and_utility_flow_labels_are_human_readable_and_described() -> None:
    strings = _translations()

    for section in ("config", "options"):
        utility_data = strings[section]["step"]["utility"]["data"]
        utility_descriptions = strings[section]["step"]["utility"]["data_description"]
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
    assert "optional" in mains_descriptions["mains_source_entities"].lower()
    assert "whole-home" in mains_descriptions["mains_source_entities"].lower()
    assert "edge detection" in mains_descriptions["nilm_detection_enabled"].lower()
    assert "power transition" in mains_descriptions[
        "nilm_detection_sensitivity"
    ].lower()
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
    assert section_descriptions.keys() == (EXPECTED_ADVANCED_SETTINGS_LABELS.keys())
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
    billing_fields = settings_step["sections"]["billing_cost_settings"]["data"]
    assert (
        not {
            "default_rate_per_kwh",
            "tou_rate_per_kwh",
            "tou_start",
            "tou_end",
            "tou_weekdays",
            "tou_name",
        }
        & billing_fields.keys()
    )


def test_assignment_flow_labels_are_human_readable_and_described() -> None:
    strings = _translations()

    for section in ("config", "options"):
        data = strings[section]["step"]["assign"]["data"]
        descriptions = strings[section]["step"]["assign"]["data_description"]
        assert data == {
            "include_circuit": "Analyze this appliance",
            "remove_from_analysis": "Remove From Analysis",
            "included_sensors": "Included Sensors",
            "circuit_name": "Circuit Name",
            "appliance_profile": "Appliance Type",
            "circuit_composition": "Circuit Composition",
            "nilm_detection_enabled": "Enable NILM Detection",
            "nilm_detection_sensitivity": "NILM Detection Sensitivity",
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
        assert (
            "several loads with no primary" in descriptions["appliance_profile"].lower()
        )
        assert (
            "primary appliance plus other loads"
            in descriptions["circuit_composition"].lower()
        )
        assert "edge detection" in descriptions["nilm_detection_enabled"].lower()
        assert (
            "power transition"
            in descriptions["nilm_detection_sensitivity"].lower()
        )
        assert "diagnostic history" in descriptions["circuit_retention_mode"].lower()
        for days in ("18 days", "45 days", "180 days"):
            assert days in descriptions["circuit_retention_mode"]
        assert strings[section]["step"]["assign"]["title"] == (
            "Appliance Circuit Assignments"
        )


def test_assignment_picker_text_is_human_readable() -> None:
    strings = _translations()

    data = strings["options"]["step"]["select_assignment"]["data"]
    descriptions = strings["options"]["step"]["select_assignment"]["data_description"]

    assert data == {
        "selected_assignment": "Assignment",
        "remove_assignments": "Remove Appliances",
    }
    assert descriptions == {
        "selected_assignment": (
            "Choose the existing appliance or circuit assignment to edit."
        ),
        "remove_assignments": (
            "Select one or more appliances to remove together instead of editing one."
        ),
    }
    assert (
        "x of"
        not in strings["options"]["step"]["select_assignment"]["description"].lower()
    )
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
        ("options", "refresh_sources"),
        ("options", "refresh_mains"),
        ("options", "mains"),
        ("options", "nilm"),
        ("options", "utility"),
        ("options", "entity_detail"),
        ("options", "select_assignment"),
        ("options", "select_advanced_circuit"),
        ("options", "advanced_settings"),
        ("options", "assign"),
    ):
        translated_step = translations[section]["step"][step]
        assert translated_step["title"]
        assert translated_step["description"]
        assert (
            translated_step.get("data")
            or translated_step.get("sections")
            or step == "refresh_sources"
        )

    translated_init = translations["options"]["step"]["init"]
    assert translated_init["title"]
    assert translated_init["description"]
    assert translated_init["menu_options"]


def test_daily_energy_sensor_uses_today_label() -> None:
    label = _translations()["entity"]["sensor"]["daily_energy_usage"]["name"]

    assert label == "Energy usage today"
    assert label != "Daily energy usage"


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


def test_pause_alert_action_renders_its_icon() -> None:
    _run_panel_node_script(
        """
const panel = makePanel({
  _payload: {
    actions: {
      pause_alerts: {
        label: "Pause Alerts",
        icon: "mdi:bell-pause-outline",
      },
    },
  },
});
const html = panel._actionButton("pause_alerts", "Pause Alerts");
assert.match(html, /<ha-icon icon="mdi:bell-pause-outline"><\\/ha-icon>/);
"""
    )


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


def test_readme_explains_environmental_sensor_learning_and_scope() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    for phrase in (
        "HVAC, HVAC compressor, HVAC blower, Mini-Split, and electric heat",
        "three distinct prior local dates",
        "ten dry, compressor-free context samples",
        "does not create a rain-specific missing-pump alert",
        "Global flow sources are shared",
        "linked source stays scoped to that appliance",
        "marked Unconfigured instead of creating a flow mismatch alert",
    ):
        assert phrase in readme_text


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


def test_dashboard_example_prioritizes_summary_cards_over_sensor_lists() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    cards = _dashboard_cards(dashboard)
    card_types = [card.get("type") for card in cards]

    assert card_types.count("entities") == 0
    assert "button" in card_types
    assert "history-graph" not in card_types
    assert {
        "custom:circuitsetup-energy-analyzer-house-flow",
        "custom:circuitsetup-energy-analyzer-appliance-grid",
        "custom:circuitsetup-energy-analyzer-energy-cost",
        "custom:circuitsetup-energy-analyzer-context-graph",
        "custom:circuitsetup-energy-analyzer-summary",
    } <= set(card_types)
    assert "gauge" not in card_types
    assert "glance" not in card_types
    assert "statistics-graph" not in card_types


def test_dashboard_example_keeps_energy_history_on_home() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    home = next(view for view in dashboard["views"] if view["path"] == "overview")
    home_cards = _dashboard_cards(home)
    energy_cards = [
        card
        for card in home_cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-energy-cost"
    ]
    home_summary = next(
        card
        for card in home_cards
        if card.get("type") == "custom:circuitsetup-energy-analyzer-house-flow"
    )

    assert len(energy_cards) == 1
    assert energy_cards[0]["api_path"].endswith("/appliance_insights")
    assert energy_cards[0]["primary_mains"] == {
        "circuit_id": "mains",
        "name": "Mains",
        "power_entities": ["sensor.mains_power"],
        "daily_energy_usage_entity": "sensor.mains_daily_energy_usage",
        "cost_today_entity": "sensor.mains_cost_today",
    }
    assert {appliance["circuit_id"] for appliance in energy_cards[0]["appliances"]} == {
        "refrigerator",
        "hvac",
        "washer",
    }
    assert home_summary["primary_mains"]["average_kwh_per_day_entity"].endswith(
        "_average_kwh_per_day"
    )
    assert home_summary["primary_mains"]["average_cost_per_day_entity"].endswith(
        "_average_cost_per_day"
    )


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
        "sensor.mains_balance_power",
        "sensor.mains_monitored_coverage",
        "sensor.mains_monitored_power",
        "sensor.mains_nilm_signature_count",
        "sensor.mains_nilm_unknown_loads",
        "sensor.mains_solar_flow_status",
        "sensor.mains_solar_surplus_power",
        "sensor.mains_utility_comparison_status",
        "sensor.mains_billing_cycle_usage",
        "sensor.mains_cost_cycle",
        "sensor.mains_cost_cycle_forecast",
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
    assert [view.get("path") for view in _dashboard_views(dashboard)] == [
        "overview",
        "energy-costs",
        "insights",
    ]
    assert "sensor.hvac_activity_summary" in dashboard_text
    assert "sensor.refrigerator_activity_summary" in dashboard_text
    assert "sensor.hvac_daily_energy_usage" in dashboard_text
    assert "sensor.refrigerator_cost_today" in dashboard_text
    assert "sensor.mains_cost_cycle" in dashboard_text
    assert "binary_sensor.hvac_running" not in dashboard_text
    assert "sensor.refrigerator_electrical_health" not in dashboard_text


def test_dashboard_example_removes_static_alert_evidence_view() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    dashboard = yaml.safe_load(dashboard_text)
    views = _dashboard_views(dashboard)
    refs = set(_dashboard_entity_refs(dashboard_text))

    assert [view.get("path") for view in views] == [
        "overview",
        "energy-costs",
        "insights",
    ]
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
        "sensor.mains_balance_status",
        "sensor.mains_demand_peak_status",
        "sensor.mains_readiness",
        "sensor.mains_nilm_discovered_signatures",
        "sensor.mains_nilm_unmatched_load_percentage",
        "sensor.mains_nilm_topology_status",
        "binary_sensor.mains_maintenance",
    }

    assert stale_entities.isdisjoint(set(_dashboard_entity_refs(dashboard_text)))
    assert "sensor.mains_monitored_power" in dashboard_text
    assert "sensor.mains_balance_power" in dashboard_text
    assert "sensor.mains_monitored_coverage" in dashboard_text
    assert "sensor.mains_nilm_unknown_loads" in dashboard_text
    assert "Review NILM Assignments" in dashboard_text
    assert (
        "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains"
        in dashboard_text
    )


def test_dashboard_example_explains_known_load_share_as_primary_mains_gauge() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    mains_view = next(
        view for view in _dashboard_views(dashboard) if view.get("path") == "insights"
    )
    flow_cards = [
        card
        for card in _dashboard_cards(mains_view)
        if card.get("type") == "custom:circuitsetup-energy-analyzer-house-flow"
    ]

    assert len(flow_cards) == 1
    assert flow_cards[0]["mode"] == "mains"
    assert flow_cards[0]["primary_mains"]["monitored_power_entity"] == (
        "sensor.mains_monitored_power"
    )
    assert flow_cards[0]["primary_mains"]["balance_power_entity"] == (
        "sensor.mains_balance_power"
    )
    assert flow_cards[0]["primary_mains"]["monitored_coverage_entity"] == (
        "sensor.mains_monitored_coverage"
    )


def test_dashboard_example_places_detail_panels_under_related_sections() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    dashboard = yaml.safe_load(dashboard_text)

    assert [view.get("title") for view in _dashboard_views(dashboard)] == [
        "Home",
        "Energy & Costs",
        "Insights",
    ]
    assert "title: Billing Cycle" in dashboard_text
    assert dashboard_text.count("Review NILM Assignments") == 1
    assert "title: Alert Evidence" not in dashboard_text


def test_dashboard_example_graphs_hvac_energy_with_outdoor_temperature() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    graphs = next(
        view
        for view in _dashboard_views(dashboard)
        if view.get("path") == "energy-costs"
    )
    graph_cards = [
        card
        for card in _dashboard_cards(graphs)
        if card.get("type") == "custom:circuitsetup-energy-analyzer-context-graph"
        and card.get("title") == "HVAC activity and outdoor temperature"
    ]

    assert graph_cards
    assert graph_cards[0]["grid_options"]["columns"] == 24
    assert graph_cards[0]["default_hours"] == 24
    assert graph_cards[0]["periods"] == [24, 168, 720]
    assert graph_cards[0]["entities"] == [
        {"entity": "sensor.hvac_power", "name": "HVAC power", "axis": "left"},
        {
            "entity": "sensor.outdoor_temperature",
            "name": "Outdoor temperature",
            "axis": "right",
        },
    ]


def test_dashboard_example_covers_configurable_analyzer_surfaces() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    refs = set(_dashboard_entity_refs(dashboard_text))

    expected_entities = {
        "sensor.refrigerator_activity_summary",
        "sensor.refrigerator_health_summary",
        "sensor.refrigerator_daily_energy_usage",
        "sensor.refrigerator_cost_today",
        "sensor.hvac_activity_summary",
        "sensor.hvac_health_summary",
        "sensor.hvac_daily_energy_usage",
        "sensor.hvac_cost_today",
        "sensor.outdoor_temperature",
        "sensor.mains_daily_energy_usage",
        "sensor.mains_cost_today",
        "sensor.mains_balance_power",
        "sensor.mains_monitored_coverage",
        "sensor.mains_monitored_power",
        "sensor.mains_nilm_unknown_loads",
        "sensor.mains_nilm_signature_count",
        "sensor.mains_solar_flow_status",
        "sensor.mains_solar_surplus_power",
        "sensor.mains_utility_comparison_status",
    }
    assert expected_entities <= refs
    assert "sensor.hvac_outdoor_temperature" not in refs
    assert "binary_sensor.hvac_running" not in refs
    assert "sensor.refrigerator_electrical_health" not in refs
    assert "circuitsetup_energy_analyzer.export_history_csv" not in dashboard_text


def test_dashboard_example_keeps_safety_notice_near_alert_philosophy() -> None:
    readme_text = (ROOT / "README.md").read_text()
    normalized_text = " ".join(readme_text.split())

    assert "Capacity diagnostics are operational evidence only" in normalized_text
    assert "do not verify breaker, wire, plug, appliance, or code suitability" in (
        normalized_text
    )


def test_dashboard_example_wraps_optional_feature_cards_conditionally() -> None:
    dashboard = yaml.safe_load((ROOT / "docs" / "dashboard-example.yaml").read_text())
    refs = set(
        _dashboard_entity_refs((ROOT / "docs" / "dashboard-example.yaml").read_text())
    )
    optional_entities = {
        "sensor.outdoor_temperature",
        "sensor.mains_solar_flow_status",
        "sensor.mains_solar_surplus_power",
        "sensor.mains_utility_comparison_status",
    }

    assert optional_entities <= refs
    leaf_cards = [
        card
        for card in _dashboard_cards(dashboard)
        if card.get("type") not in {"sections", "grid"}
    ]
    for entity in optional_entities:
        owners = [card for card in leaf_cards if entity in yaml.safe_dump(card)]
        assert 1 <= len(owners) <= 2
        assert all(
            owner.get("type", "").startswith("custom:circuitsetup-energy-analyzer-")
            or owner.get("type") == "history-graph"
            for owner in owners
        )


def test_readme_describes_summary_first_diagnostic_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Summary-First Diagnostics" in readme
    assert "Health Summary" in readme
    assert "Activity Summary" in readme
    assert "Energy Summary" in readme
    assert "advanced detail" in readme.lower()
    assert "power-quality, metric-consistency, and leg-balance evidence" in readme
    assert "Expert creates only the diagnostic or graph groups you select" in readme
    assert "Expert Entity Groups" in readme


def test_readme_explains_running_observation_and_alert_distinction() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "Activity Summary is the current operating state; use its state or "
        "`is_running` attribute for automations."
    ) in readme
    assert "Observation recorded means the analyzer noticed something unusual" in readme
    assert (
        "Possible issue means repeated evidence crossed the alert threshold." in readme
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
    assert "default: CircuitSetup Energy Analyzer alert" in blueprint_text
    assert "{{ alert_entity_name }} reports: {{ alert_state }}." in blueprint_text
    assert "reports a possible issue" not in blueprint_text
    assert "alert_entities:" in blueprint_text
    assert "alert_actions:" in blueprint_text
    assert "evidence_path" in blueprint_text
    assert "Open evidence graph" in blueprint_text
    assert "clickAction" in blueprint_text
    assert "url:" in blueprint_text


def test_readme_describes_blueprint_summary_sensor_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "The blueprint uses the selected summary sensor's explanation and "
        "circuit-specific `evidence_path` when available." in readme
    )


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


def test_alert_blueprint_uses_summary_sensor_explanations() -> None:
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
    evidence_template = Template(blueprint["variables"]["alert_evidence"])

    def render(attributes: dict[str, str]) -> str:
        return evidence_template.render(
            trigger={
                "to_state": {
                    "state": "Possible issue",
                    "attributes": attributes,
                }
            }
        ).strip()

    assert (
        render(
            {
                "friendly_name": "Washer Health Summary",
                "status_explanation": "Reported electrical measurements disagree.",
            }
        )
        == "Reported electrical measurements disagree."
    )
    assert (
        render(
            {
                "friendly_name": "Washer Energy Summary",
                "summary_explanation": "Energy use is above the configured threshold.",
            }
        )
        == "Energy use is above the configured threshold."
    )


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
        option["value"] for option in alert_input["selector"]["select"]["options"]
    }

    assert "possible_issue" in defaults
    assert {
        "possible_imbalance",
        "possible_metric_mismatch",
        "possible_power_quality_change",
        "high_usage",
        "watch",
        "mixed_observation",
        "nilm_review",
    } <= options

    alert_state_template = Template(blueprint["variables"]["alert_state"])
    normalized_state_template = Template(
        blueprint["variables"]["alert_state_normalized"]
    )
    condition_template = Template(blueprint["variables"]["alert_is_actionable"])

    def condition_matches(
        state: str,
        selected_states: list[str],
        *,
        power_quality_alert_confirmed: bool = False,
        learning: bool | None = False,
        alert_confirmed: bool | None = True,
        maintenance_active: bool = False,
        electrical_summary: str | None = None,
    ) -> bool:
        attributes = {
            "power_quality_alert_confirmed": power_quality_alert_confirmed,
            "maintenance_active": maintenance_active,
        }
        if learning is not None:
            attributes["learning"] = learning
        if alert_confirmed is not None:
            attributes["alert_confirmed"] = alert_confirmed
        if electrical_summary is not None:
            attributes["electrical_summary"] = electrical_summary
        trigger = {
            "to_state": {
                "state": state,
                "attributes": attributes,
            }
        }
        alert_state = alert_state_template.render(trigger=trigger).strip()
        alert_state_normalized = normalized_state_template.render(
            alert_state=alert_state
        ).strip()
        rendered = condition_template.render(
            trigger=trigger,
            alert_state_normalized=alert_state_normalized,
            alert_states=selected_states,
        )
        return rendered.strip() == "True"

    assert not condition_matches("Possible issue", defaults, learning=None)
    assert not condition_matches("Possible issue", defaults, learning=True)
    assert not condition_matches(
        "Possible issue",
        defaults,
        alert_confirmed=None,
    )
    assert not condition_matches(
        "Possible issue",
        defaults,
        alert_confirmed=False,
    )
    assert condition_matches("Possible issue", defaults, learning=False)
    assert not condition_matches(
        "Possible issue",
        defaults,
        maintenance_active=True,
    )
    assert condition_matches("Possible issue: Cycle Duration", defaults)
    assert condition_matches("High Usage", defaults)
    assert condition_matches("Watch", defaults)
    assert not condition_matches("Possible Power Quality Change", defaults)
    assert condition_matches(
        "Possible Power Quality Change",
        defaults,
        power_quality_alert_confirmed=True,
    )
    assert condition_matches(
        "Ready",
        defaults,
        electrical_summary="Possible Power Quality Change",
        power_quality_alert_confirmed=True,
    )
    assert not condition_matches("Needs data", defaults)


def test_dynamic_alert_evidence_panel_asset_is_user_facing() -> None:
    assert PANEL_ASSET.exists()
    asset = _frontend_source()
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
        '_panelText("headers.appliance_detail")',
        '_panelText("appliance_detail.today_vs_normal")',
        "data-appliance-daily-cost",
        "payload.daily_totals",
        "average_cost_per_day",
        "average_kwh_per_day",
        "detail.recent_timeline",
        "_renderApplianceTimeline",
        '_panelText("appliance_detail.behavior_expectations")',
        "data-appliance-behavior-health",
        "NILM_WORKSPACE_CALL_API_PATH",
        "nilm_workspace",
        "NILM_WORKSPACE_QUERY_PARAM",
        "routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM)",
        "_loadNilmWorkspace",
        "_routeRequestsNilmWorkspace",
        "this._routeRequestsNilmWorkspace() ? this._renderNilmWorkspaceBody()",
        "_renderNilmWorkspace",
        "_renderNilmWorkspaceBody",
        "data-nilm-source-picker",
        "nilm_workspace.source_picker_label",
        '_panelText("headers.nilm_workspace")',
        "_renderNilmWorkspaceLanes(workspace)",
        "_renderNilmReviewLayout(workspace)",
        "_nilmLaneItems",
        "_nilmSelectedReviewItem",
        '_panelText("nilm_workspace.review_lanes")',
        '_panelText("nilm_workspace.known_load_overlays")',
        '_panelText("nilm_workspace.solar_net_overlays")',
        "_visibleNilmWorkspaceSeries",
        '_panelText("nilm_workspace.estimated_appliances_title")',
        "data-nilm-appliance-detail-path",
        "_nilmApplianceDetailButton",
        "estimated_daily_energy",
        "model_status",
        "_renderNilmValidation",
        "ground_truth_entity_id",
        '_panelText("nilm_workspace.sessions_title")',
        '_panelText("nilm_workspace.edges_title")',
        "data-nilm-signature-fingerprint",
        "_focusNilmSignatureOnGraph",
        "_focusNilmGraphWindowForSignature",
        "_nilmSignatureFingerprint",
        "data-nilm-graph-zoom",
        "data-nilm-graph-pan",
        "data-nilm-workspace-graph",
        "data-${prefix}-window",
        "_zoomNilmGraph",
        "_panNilmGraph",
        "_nilmWorkspaceGraphWindow",
        "_renderNilmLabelIntervalEditor",
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
        '<select id="nilm_assignment_profile_',
        'collectionKey === "sessions"',
        "`#nilm_session_label_${index}`",
        "data-nilm-existing-assignment",
        'actionKey === "assign" ? '
        "this._nilmExistingAssignmentSelection(sourceKey) : null",
        "_renderNilmExistingAssignmentField",
        "_saveNilmAssignmentChanges",
        "data-nilm-interval-evidence",
        "_requestNilmIntervalEvidence",
        "datetime-local",
        "MAX_CHART_POINTS_PER_SERIES",
        "_boundedChartPoints",
        'callService("circuitsetup_energy_analyzer"',
        "acknowledge_alert",
        "mark_alert_expected",
        "mark_alert_confirmed",
        "mark_alert_unhelpful",
        "pause_alerts",
        "relearn_baseline",
        "open_appliance_detail",
        'this._listen("#open_appliance_detail", () => '
        'this._callAction("open_appliance_detail"))',
        "apply_setting_recommendation",
        "dismiss_setting_recommendation",
        '_panelTextFormat("chart.accessible_summary"',
        '_panelTextFormat("chart.graph_times"',
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
        "Load Separation",
        "Respond to this alert",
        "Known Load Overlays",
        "Label appliance interval",
        "Identify this load",
        "Sessions, validation, and technical details",
        "Appliance Type",
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
    assert '<select id="nilm_merge_target_' not in asset
    assert (
        "querySelector(`#nilm_assignment_label_${index}`)\n"
        "        || this.shadowRoot.querySelector(`#nilm_session_label_${index}`)"
        not in asset
    )
    assert (
        "entities.map((entityId) => `<code>${this._escape(entityId)}</code>`)"
        not in asset
    )
    assert "Source Entities" not in asset
    assert "source-entity-chip" not in asset
    assert "data-source-entity" not in asset
    assert '(item.entity_ids || []).join(", ")' not in asset
    assert "data-nilm-workspace-action" not in asset
    assert "_openSourceEntity" not in asset
    assert "_renderSessionTimeline" not in asset
    assert "_renderApplianceActions" not in asset
    assert "_callApplianceDetailAction" not in asset
    assert "_renderApplianceNotificationPreferences" not in asset
    assert "_saveApplianceNotificationPreferences" not in asset
    assert "_renderExpectedSchedule" not in asset
    assert "_saveExpectedSchedule" not in asset
    assert "data-appliance-detail-action" not in asset
    assert "data-appliance-notifications" not in asset
    assert "data-expected-schedule" not in asset
    assert "${this._escape(item.entity_id)}" not in asset
    assert "this._escape(signature.signature_id)}</strong>" not in asset
    assert 'recommendation.recommendation_id || "Recommendation"' not in asset
    assert "deny_setting_recommendation" not in asset
    assert '_recommendationActionButton(recommendation, index, "deny"' not in asset
    assert "border-radius: 12px" not in asset
    assert "border-radius: 16px" not in asset
    assert "border-radius: 999px" not in asset
    assert all(
        int(radius) <= 8 for radius in re.findall(r"border-radius:\s*(\d+)px", asset)
    )


def test_appliance_detail_uses_home_assistant_currency_without_hardcoded_dollars() -> (
    None
):
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { currency: "EUR" } };
panel._applianceDetail = {
  status: "ok",
  detail: {
    activity_state: "Running",
    current_power_w: 820,
    source_type: "direct_meter",
    source_quality: { status: "fresh", label: "Fresh" },
    learning_readiness: { status: "ready", label: "Ready" },
    confidence: null,
    health_state: "Ready",
    energy_state: "Normal",
    model_status: null,
    daily_energy_kwh: 2.4,
    runtime_today_seconds: 7200,
    run_count_today: 3,
    cost_today: 0.6,
    average_cost_per_day: 0.5,
    average_kwh_per_day: 2.1,
    recent_timeline: { items: [] },
    today_vs_normal: [{
      metric_id: "cost_today",
      label: "Cost today",
      unit: "currency",
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
  daily_totals: [
    { date: "2026-07-10", energy_kwh: 2, cost: 0.5 },
    { date: "2026-07-11", energy_kwh: 2.2, cost: 0.55 },
  ],
  actions: {}
};
const html = panel._renderApplianceDetailBody();
for (const expected of [
  'data-appliance-daily-cost',
  "kWh Today",
  "Average kWh per Day",
  "Cost Today",
  "Average Cost per Day",
  "€0.60",
  "Cost today",
  "Normal",
  "€0.45 - €0.55",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
if (html.includes("$")) {
  throw new Error(`cost display hardcoded dollars: ${html}`);
}
assert.equal((html.match(/>Cost Today</g) || []).length, 1);
assert.equal((html.match(/class="chart"/g) || []).length, 1);
assert.equal((html.match(/class="panel summary appliance-detail-facts"/g) || []).length, 0);
assert.ok(html.includes("data-appliance-now"));
const dailyMetricOrder = [
  ">kWh Today<",
  ">Average kWh per Day<",
  ">Cost Today<",
  ">Average Cost per Day<",
].map((label) => html.indexOf(label));
assert.ok(dailyMetricOrder.every((index) => index >= 0));
assert.deepEqual(dailyMetricOrder, [...dailyMetricOrder].sort((left, right) => left - right));
for (const removed of [
  ">Source<",
  ">Mains Source<",
  ">Data Quality<",
  ">Model<",
  ">Energy Today<",
]) {
  assert.ok(!html.includes(removed), `unexpected appliance fact ${removed}: ${html}`);
}
assert.ok(html.includes('data-chart-right-axis="€"'));
assert.ok(html.includes('>€0.55</text>'));
assert.equal((html.match(/stroke-dasharray="6 4"/g) || []).length, 1);
assert.ok(!html.includes("What To Check First"));
"""
    )


def test_appliance_daily_cost_chart_omits_absent_costs_and_keeps_home_assistant_dates() -> (
    None
):
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { currency: "USD", time_zone: "America/New_York" } };
const noRateHtml = panel._renderApplianceDailyCost({ daily_totals: [
  { date: "2026-01-01", energy_kwh: 2.0, cost: null },
  { date: "2026-01-02", energy_kwh: 2.1, cost: undefined },
  { date: "2026-01-03", energy_kwh: 2.2, cost: Number.NaN },
] }, {});
assert.equal((noRateHtml.match(/class="chart"/g) || []).length, 1);
assert.ok(!noRateHtml.includes("data-chart-right-axis"));
assert.ok(!noRateHtml.includes('stroke-dasharray="6 4"'));

const browserParse = context.Date.parse;
context.Date.parse = (value) => browserParse(String(value).endsWith("T12:00:00") ? `${value}+09:00` : value);
const timezoneHtml = panel._renderApplianceDailyCost({ daily_totals: [
  { date: "2026-01-01", energy_kwh: 2.0, cost: null },
] }, {});
const time = Number(timezoneHtml.match(/data-chart-time="(\\d+)"/)[1]);
const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
}).formatToParts(new Date(time)).map((part) => [part.type, part.value]));
assert.equal(`${parts.year}-${parts.month}-${parts.day}`, "2026-01-01");
"""
    )


def test_appliance_detail_labels_projected_energy_ranges_and_status() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderApplianceComparisons([{
  metric_id: "daily_energy_kwh",
  label: "Energy so far",
  unit: "kWh",
  current_value: 0.5,
  normal_low: 0.4,
  normal_high: 0.7,
  normal_median: 0.55,
  comparison_mode: "same_time_of_day",
  status: "normal",
  confidence: 0.88,
  source: "contextual_baseline",
  projection_value: 1.9,
  projection_low: 1.7,
  projection_high: 2.1,
  projection_confidence: 0.58,
  full_period_normal_low: 1.4,
  full_period_normal_high: 1.8,
  full_period_normal_median: 1.6
}]);
for (const expected of [
  "Energy so far",
  "Projected",
  "1.9 kWh",
  "Projected range 1.7 kWh - 2.1 kWh",
  "Completed-day normal range 1.4 kWh - 1.8 kWh",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
assert.equal((html.match(/>Projected</g) || []).length, 1);
assert.ok(!html.includes("Projection confidence"));
assert.ok(!html.includes("Projected status"));
"""
    )


def test_appliance_detail_comparison_formats_runtime_as_duration() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderApplianceComparisons([{
  metric_id: "runtime_today_seconds",
  label: "Runtime so far",
  unit: "s",
  current_value: 10349.897,
  normal_low: 2610.09,
  normal_high: 12518.361,
  status: "normal",
  projection_value: 17801.167,
  projection_low: 9164.483,
  projection_high: 22217.996,
  full_period_normal_low: 8530.127,
  full_period_normal_high: 20680.089,
}]);
for (const expected of ["2h 52m 30s", "43m 30s - 3h 28m 38s", "4h 56m 41s"]) {
  assert.ok(html.includes(expected), `missing ${expected}: ${html}`);
}
assert.ok(html.includes('icon="mdi:timer-outline"'));
for (const raw of ["10349.897 s", "2610.09 s", "12518.361 s", "17801.167 s"]) {
  assert.ok(!html.includes(raw), `raw seconds remain: ${html}`);
}
"""
    )


def test_appliance_detail_shows_full_period_normals_and_limits_without_projection() -> (
    None
):
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderApplianceComparisons([{
  metric_id: "demand_peak_w",
  label: "Demand peak so far",
  unit: "W",
  current_value: 4200,
  normal_low: null,
  normal_high: null,
  normal_median: null,
  comparison_mode: "same_time_of_day",
  status: "learning",
  full_period_normal_low: 3500,
  full_period_normal_high: 4800,
  configured_limit_value: 5000,
  limit_unit: "W"
}, {
  metric_id: "capacity_usage_percent",
  label: "Capacity usage",
  unit: "%",
  current_value: 86,
  status: "higher",
  configured_warning_value: 80,
  configured_limit_value: 100,
  limit_unit: "%"
}]);
for (const expected of [
  "Completed-day normal range 3,500 W - 4,800 W",
  "Configured limit 5,000 W",
  "Configured warning 80%",
  "Configured limit 100%",
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_appliance_detail_explains_missing_cost_friendly() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const value = panel._formatCost(null);
if (value !== "Cost unavailable") {
  throw new Error(`expected friendly missing-cost text, got: ${value}`);
}
"""
    )


def test_weekly_digest_save_rejects_unsaved_api_results() -> None:
    _run_panel_node_script(
        r"""
(async () => {
  async function assertRejected(panel, response, save, current) {
    const original = current();
    panel._loadedRouteKey = "/panel";
    panel._render = () => {};
    panel._postJson = async () => response;
    await save();
    assert.equal(current(), original);
    assert.match(panel._lastActionMessage, /not_found/);
  }

  const weekly = new context.Panel();
  weekly._setupHealth = { weekly_digest_settings: { enabled: false } };
  weekly.shadowRoot = { querySelector: () => ({ querySelector: (field) => ({
    "[data-weekly-digest-enabled]": { checked: true },
    "[data-weekly-digest-delivery]": { value: "panel_only" },
    "[data-weekly-digest-notify-service]": { value: "" },
  })[field] }) };
  await assertRejected(weekly, { status: "not_found", weekly_digest_settings: { enabled: true } },
    () => weekly._saveWeeklyDigestSettings(), () => weekly._setupHealth.weekly_digest_settings);

})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_weekly_digest_panel_renders_observed_alerts() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderWeeklyDigest({
  week_start: "2026-07-20",
  week_end: "2026-07-26",
  observed_alerts: [{ display_name: "Dishwasher", energy_kwh: 0 }],
}, { enabled: true, delivery: "panel_only" });
assert.match(html, /Alerts observed this week/);
assert.match(html, /Dishwasher/);
"""
    )


def test_unavailable_setting_preview_hides_incomplete_impact_claims() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
const html = panel._renderSettingImpactPreview({ impact_preview: {
  available: false,
  observations_evaluated: 23,
  history_start: "2026-07-01T12:00:00Z",
  history_end: "2026-07-13T12:00:00Z",
  current_alert_count: 37,
  candidate_alert_count: 41,
  current_state_change_count: null,
  candidate_state_change_count: null,
  examples_removed: ["old example"],
  examples_added: ["new example"],
  limitations: ["A reliable preview is unavailable because retained history contains only alerts selected by the current setting."],
} });
assert.equal(html, "");
"""
    )


def test_appliance_detail_uses_icons_grids_and_omits_cumbersome_controls() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._applianceDetail = {
  status: "ok",
  detail: {
    activity_state: "Running",
    current_power_w: 820,
    source_type: "direct_meter",
    source_quality: { status: "fresh", label: "Fresh" },
    learning_readiness: { status: "ready", label: "Ready" },
    confidence: 0.87,
    health_state: "Ready",
    energy_state: "Normal",
    model_status: "Measured",
    daily_energy_kwh: 2.4,
    runtime_today_seconds: 7200,
    run_count_today: 3,
    cost_today: 0.6,
    recent_timeline: { items: [{ timestamp: "2026-07-11T12:00:00Z", title: "Started", detail: "Compressor started." }] },
    today_vs_normal: [{ metric_id: "current_power_w", label: "Current power", unit: "W", current_value: 820, normal_low: 300, normal_high: 600, status: "higher", confidence: 0.8, source: "baseline" }],
    expectations: [],
    what_to_check_first: [],
    active_alerts: [{ message: "Power is above normal.", severity: "warning" }]
  },
  notification_preferences: {
    finished_running: true,
    delivery_mode: "immediate",
    minimum_confidence: 0.5,
    cooldown_minutes: 60
  },
  expected_schedule: {
    settings: { enabled: true, windows: [{ start: "08:00", end: "10:00", weekdays: [0] }] }
  },
  actions: {
    open_evidence: { type: "navigate", path: "/evidence" },
    mark_expected: { domain: "test", service: "expected" },
    mark_unhelpful: { domain: "test", service: "unhelpful" },
    relearn_baseline: { domain: "test", service: "relearn" }
  }
};
const html = panel._renderApplianceDetailBody();
for (const expected of [
  'icon="mdi:play-circle-outline"',
  'icon="mdi:flash-outline"',
  'icon="mdi:heart-pulse"',
  'icon="mdi:chart-line"',
  'icon="mdi:clock-outline"',
  'icon="mdi:calendar-today"',
  'icon="mdi:cash"',
  'class="appliance-timeline"',
  'data-appliance-comparison-table',
]) {
  if (!html.includes(expected)) throw new Error(`missing ${expected}: ${html}`);
}
for (const removed of [
  "Session Timeline",
  "session-strip",
  "data-session-id",
  "Appliance Notifications",
  "data-appliance-notifications",
  "Expected Schedule",
  "data-expected-schedule",
  "<h2>Actions</h2>",
  "data-appliance-detail-action",
  "appliance-alert-actions",
  "appliance-general-actions",
  "Relearn Baseline",
]) {
  if (html.includes(removed)) throw new Error(`unexpected appliance-detail control ${removed}: ${html}`);
}
"""
    )


def test_appliance_detail_renders_predictive_health_evidence() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const learning = panel._renderApplianceBehaviorHealth({
  expectations: [],
  appliance_health: {
    status: "learning",
    reason: "insufficient_history",
    confidence: 0,
  },
});
assert.ok(learning.includes('data-appliance-behavior-health'));
assert.ok(learning.includes("Predictive Health"));
assert.ok(learning.includes("Learning"));
assert.ok(learning.includes("More completed appliance history is needed"));

const withoutHealth = panel._renderApplianceBehaviorHealth({
  expectations: [],
  appliance_health: null,
  recent_timeline: { items: [] },
});
assert.ok(withoutHealth.includes("Predictive Health"));
assert.ok(!withoutHealth.includes("<strong>Learning</strong>"));

const possibleIssue = panel._renderApplianceBehaviorHealth({
  expectations: [],
  appliance_health: {
    status: "possible_degradation",
    reason: "sustained_change",
    confidence: 0.91,
    feature: "efficiency_degradation",
    metric: "energy_per_runtime_hour",
    change_percent: 30,
    reference_count: 14,
    recent_count: 3,
    context: { season: "summer", weather_mode: "cooling" },
    last_eligible_date_or_session: "2026-07-27",
  },
  recent_timeline: { items: [] },
});
for (const expected of [
  "Possible degradation",
  "Sustained efficiency change",
  "30%",
  "14 reference days",
  "3 recent days",
  "season: summer",
  "weather mode: cooling",
  "2026-07-27",
]) {
  assert.ok(possibleIssue.includes(expected), `missing ${expected}: ${possibleIssue}`);
}
"""
    )


def test_appliance_detail_renders_hvac_thermostat_efficiency() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { unit_system: { temperature: "°F" } } };
const ready = panel._renderHvacEfficiency({
  status: "ready",
  summary_score: 110,
  trend: "slower",
  threshold_pct: 25,
  learning: {
    reference_count: 50,
    recent_count: 5,
    required_reference: 50,
    required_recent: 5,
  },
  heating: [{
    thermostat_entity_id: "climate.upstairs",
    thermostat_name: "Upstairs",
    status: "ready",
    score: 110,
    trend: "faster",
    change_percent: -9.1,
    baseline_runtime_minutes: 55,
    recent_runtime_minutes: 50,
    reference_count: 50,
    recent_count: 5,
    outdoor_temperature_f: 28,
    season: "winter",
    weather_mode: "heating",
    attribution: "gas_furnace_proxy",
    supporting_blower_ids: [],
  }],
  cooling: [{
    thermostat_entity_id: "climate.downstairs",
    thermostat_name: "Downstairs",
    status: "ready",
    score: 80,
    trend: "slower",
    change_percent: 25,
    baseline_runtime_minutes: 50,
    recent_runtime_minutes: 62.5,
    reference_count: 50,
    recent_count: 5,
    outdoor_temperature_f: 95,
    season: "summer",
    weather_mode: "cooling",
    attribution: "direct",
    supporting_blower_ids: ["blower"],
  }],
});
for (const expected of [
  'data-hvac-efficiency',
  "Weather-Normalized HVAC Response",
  "110 / 100",
  'style="--hvac-score:27.5%"',
  "100 is the learned weather-normalized baseline",
  "Slower-runtime alert threshold: 25%",
  "Heating",
  "Cooling",
  "Upstairs",
  "Downstairs",
  "50 min",
  "62.5 min",
  "50 of 50 reference core days",
  "5 of 5 recent core days",
  "Outdoor temperature",
  "95°F",
  "Season",
  "summer",
  "Weather context",
  "cooling",
  "Gas-furnace blower proxy",
  "Cooling blower supports air handling",
  'icon="mdi:thermostat"',
  'icon="mdi:weather-sunny"',
  'icon="mdi:calendar-season"',
  'icon="mdi:cloud-outline"',
  'icon="mdi:account-check-outline"',
  'icon="mdi:counter"',
]) {
  assert.ok(ready.includes(expected), `missing ${expected}: ${ready}`);
}

const learning = panel._renderHvacEfficiency({
  status: "learning",
  summary_score: null,
  trend: null,
  threshold_pct: 25,
  heating: [],
  cooling: [],
  learning: {
    reference_count: 0,
    recent_count: 0,
    required_reference: 50,
    required_recent: 5,
  },
});
assert.ok(learning.includes("Learning"));
assert.ok(learning.includes("requires outdoor temperature"));
assert.ok(!learning.toLowerCase().includes("fault"));
assert.ok(learning.includes("hvac-efficiency-layout"));
assert.ok(learning.includes('data-hvac-learning="true"'));
assert.ok(learning.includes('icon="mdi:database-clock-outline"'));
assert.ok(learning.includes('icon="mdi:history"'));
"""
    )


def test_appliance_detail_hides_empty_guidance_and_uses_split_overview() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._applianceDetail = {
  status: "ok",
  detail: {
    activity_state: "Idle",
    current_power_w: 2,
    source_type: "direct_meter",
    source_quality: { status: "fresh", label: "Fresh" },
    learning_readiness: { status: "learning", label: "Learning", days_complete: 3, days_required: 7 },
    confidence: null,
    health_state: "Ready",
    energy_state: "Normal",
    model_status: null,
    daily_energy_kwh: 0.2,
    runtime_today_seconds: 0,
    run_count_today: 0,
    cost_today: null,
    recent_timeline: { items: [] },
    today_vs_normal: [],
    energy_change_explanation: null,
    expectations: [],
    what_to_check_first: [],
    next_step: "Review alert evidence",
    active_alerts: [{ message: "No linked evidence", severity: "watch" }],
  },
};
const html = panel._renderApplianceDetailBody();
assert.ok(html.includes("data-appliance-now"));
assert.ok(html.includes("Appliance Activity History"));
assert.ok(!html.includes("Why Energy Changed"));
assert.ok(!html.includes("What To Check First"));
assert.ok(html.includes("3 days of learning out of 7 days complete"));
assert.equal(
  panel._applianceDetailHeaderMessage(panel._applianceDetail.detail, panel._applianceDetail),
  "Appliance behavior summary.",
);
"""
    )


def test_appliance_timeline_deduplicates_items_shown_in_the_same_minute() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
const html = panel._renderApplianceTimeline({ items: [
  { timestamp: "2026-07-11T12:00:05Z", title: "Started", detail: "Compressor started." },
  { timestamp: "2026-07-11T12:00:41Z", title: "Started", detail: "Compressor started." },
  { timestamp: "2026-07-11T12:05:00Z", title: "Stopped", detail: "Compressor stopped." },
] });
assert.equal((html.match(/Compressor started\./g) || []).length, 1);
assert.equal((html.match(/Compressor stopped\./g) || []).length, 1);
"""
    )


def test_appliance_comparisons_show_today_and_normal_without_source() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
const html = panel._renderApplianceComparisons([{
  metric_id: "current_power_w",
  label: "Current power",
  unit: "W",
  current_value: 820,
  normal_low: 300,
  normal_high: 600,
  status: "higher",
  source: "contextual_baseline",
}], { days_complete: 7, days_required: 7 });
for (const expected of ["Today", "Normal", "820 W", "300 W - 600 W"]) {
  assert.ok(html.includes(expected), `missing ${expected}: ${html}`);
}
assert.ok(!html.includes("Source Contextual Baseline"));
"""
    )


def test_appliance_history_zoom_uses_supported_viewport_ladder() -> None:
    _run_panel_node_script(
        r"""
(async () => {
  const panel = new context.Panel();
  const requested = [];
  panel._applianceDetail = { history: { period_hours: [24, 168, 720] } };
  panel._loadApplianceDetailHistory = async (hours) => { requested.push(hours); panel._applianceDetailHistoryHours = hours; };
  panel._applianceDetailHistoryHours = 168;
  panel._applianceDetailHistoryBounds = { min: 0, max: 168 * 60 * 60 * 1000 };
  panel._render = () => {};
  await panel._zoomApplianceHistoryGraph(0.5);
  assert.equal(panel._applianceDetailHistoryGraphWindow().end - panel._applianceDetailHistoryGraphWindow().start, 24 * 60 * 60 * 1000);
  panel._panApplianceHistoryGraph(-0.5);
  assert.ok(panel._applianceDetailHistoryGraphWindow().start < 72 * 60 * 60 * 1000);
  await panel._zoomApplianceHistoryGraph(2);
  assert.equal(panel._applianceDetailHistoryGraphWindow().end - panel._applianceDetailHistoryGraphWindow().start, 168 * 60 * 60 * 1000);
  panel._applianceDetailHistoryHours = 24;
  panel._applianceDetailHistoryBounds = { min: 0, max: 24 * 60 * 60 * 1000 };
  panel._applianceDetailHistoryWindow = null;
  await panel._zoomApplianceHistoryGraph(2);
  assert.deepEqual(requested, [168]);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_alert_technical_details_keep_metric_boxes() -> None:
    asset = _frontend_source()

    assert "[data-evidence-technical] .metric" not in asset


def test_appliance_detail_renders_history_before_the_summary() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._applianceDetail = {
  status: "ok",
  history: {
    entities: [
      "sensor.fridge_power",
      "sensor.fridge_power_factor",
      "sensor.fridge_current",
      "sensor.fridge_energy",
    ],
    entity_series: [
      { entity_id: "sensor.fridge_power", unit: "W" },
      { entity_id: "sensor.fridge_va", unit: "VA" },
      { entity_id: "sensor.fridge_var", unit: "VAR" },
      { entity_id: "sensor.fridge_power_factor", unit: "PF" },
      { entity_id: "sensor.fridge_current", unit: "A" },
      { entity_id: "sensor.fridge_energy", unit: "kWh" },
    ],
    default_hours: 168,
    period_hours: [24, 168, 720],
  },
  detail: {
    activity_state: "Running",
    current_power_w: 128,
    source_type: "direct_meter",
    confidence: null,
    health_state: "Ready",
    energy_state: "Normal",
    model_status: null,
    daily_energy_kwh: 1.8,
    runtime_today_seconds: 7200,
    run_count_today: 3,
    cost_today: 0.6,
    recent_timeline: { items: [] },
    today_vs_normal: [],
    expectations: [],
    what_to_check_first: [],
    active_alerts: []
  },
  actions: {}
};
panel._applianceDetailHistorySeries = [[
  { entity_id: "sensor.fridge_power", state: "128", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_power", state: "84", last_changed: "2026-07-10T13:00:00Z" },
], [
  { entity_id: "sensor.fridge_va", state: "132", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_va", state: "90", last_changed: "2026-07-10T13:00:00Z" },
], [
  { entity_id: "sensor.fridge_var", state: "14", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_var", state: "11", last_changed: "2026-07-10T13:00:00Z" },
], [
  { entity_id: "sensor.fridge_power_factor", state: "0.92", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_power_factor", state: "0.88", last_changed: "2026-07-10T13:00:00Z" },
], [
  { entity_id: "sensor.fridge_current", state: "1.4", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_current", state: "1.1", last_changed: "2026-07-10T13:00:00Z" },
], [
  { entity_id: "sensor.fridge_energy", state: "1.2", last_changed: "2026-07-10T12:00:00Z" },
  { entity_id: "sensor.fridge_energy", state: "1.4", last_changed: "2026-07-10T13:00:00Z" },
]];
panel._applianceDetailHistoryBounds = {
  min: Date.parse("2026-07-10T00:00:00Z"),
  max: Date.parse("2026-07-11T00:00:00Z"),
};
const html = panel._renderApplianceDetailBody();
const graph = html.indexOf('class="chart"');
const summary = html.indexOf("data-appliance-behavior-health");
if (graph < 0 || graph > summary) {
  throw new Error(`expected appliance history graph before summaries: ${html}`);
}
for (const expected of [
  ">Graphs<",
  'data-appliance-history-period',
  'data-appliance-history-graph-zoom="0.5"',
  'data-appliance-history-graph-pan="-0.5"',
  'aria-label="Zoom In"',
  'aria-label="Pan Earlier"',
  'data-chart-point="1"',
  'data-chart-tooltip',
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
assert.ok(!html.includes(">VA<"));
assert.ok(!html.includes(">VAR<"));
if ((html.match(/class="chart"/g) || []).length !== 3) {
  throw new Error(`expected combined power and amps plus power factor and energy charts: ${html}`);
}
const axisLabels = [...html.matchAll(/class="axis-label"[^>]*>([^<]+)<\\/text>/g)]
  .map((match) => match[1]);
assert.deepEqual(axisLabels, ["W", "A", "PF", "kWh"]);
"""
    )


def test_appliance_detail_history_requests_the_selected_period() -> None:
    _run_panel_node_script(
        r"""
(async () => {
  const requests = [];
  const panel = new context.Panel();
  context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
  context.window.location.search = "?appliance_detail=1&circuit_id=fridge";
  panel._loadedRouteKey = "/circuitsetup-energy-analyzer-evidence?appliance_detail=1&circuit_id=fridge";
  panel._applianceDetail = {
    history: {
      entities: ["sensor.fridge_power", "sensor.fridge_energy"],
      default_hours: 168,
      period_hours: [24, 168, 720],
    },
  };
  panel._render = () => {};
  panel._requestJson = async (apiPath, fetchPath) => {
    requests.push({ apiPath, fetchPath });
    return [[{ entity_id: "sensor.fridge_power", state: "128", last_changed: "2026-07-10T12:00:00Z" }]];
  };
  await panel._loadApplianceDetailHistory(24);
  assert.equal(requests.length, 1);
  assert.match(requests[0].apiPath, /^history\/period\//);
  assert.match(requests[0].apiPath, /filter_entity_id=sensor.fridge_power%2Csensor.fridge_energy/);
  assert.equal(panel._applianceDetailHistoryHours, 24);
  assert.equal(panel._applianceDetailHistorySeries.length, 1);
  assert.equal(panel._applianceDetailChartSeries.length, 1);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_suggested_settings_route_renders_the_notification_review() -> None:
    _run_panel_node_script(
        """
context.window.location.search = "?review_suggested_settings=1&entry_id=entry-1";
const panel = new context.Panel();
panel._payload = {
  status: "settings_recommendations",
  setting_recommendations: [{
    display_label: "Raise daily spike threshold",
    status: "pending",
    actions: { apply: {} },
  }],
};
if (!panel._routeRequestsSuggestedSettings()) {
  throw new Error("expected notification review route to be recognized");
}
const html = panel._renderSuggestedSettingsBody();
for (const expected of ["Suggested Settings", "Raise daily spike threshold"]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_scoped_load_error_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_alert_history_error_stays_in_graph_and_retries_only_history";
    {
      let historyLoads = 0;
      let evidenceLoads = 0;
      const listeners = {};
      const panel = makePanel({
        _loading: false,
        _historyError: "Could not load history samples.",
        _payload: {
          status: "matched_alert",
          circuit: { circuit_id: "mains", name: "Whole Home" },
          alert: {
            graph_entities: ["sensor.mains_power"],
          },
          actions: {},
        },
      });
      const draft = { decision: "identify", identifyMode: "label" };
      panel._nilmDecisionDrafts.set("draft", draft);
      panel._loadHistory = async () => { historyLoads += 1; };
      panel._loadEvidence = async () => { evidenceLoads += 1; };
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll() { return []; },
        querySelector(selector) {
          return selector === "[data-retry-alert-history]" ? {
            addEventListener(type, callback) { listeners[type] = callback; },
          } : null;
        },
      };
      panel._render();
      assert.ok(panel.shadowRoot.innerHTML.includes("data-alert-history-error"));
      assert.ok(panel.shadowRoot.innerHTML.includes("data-evidence-graph"));
      assert.equal(typeof listeners.click, "function");
      await listeners.click();
      assert.deepEqual([historyLoads, evidenceLoads], [1, 0]);
      assert.equal(panel._nilmDecisionDrafts.get("draft"), draft);
    }

    name = "test_nilm_load_errors_have_workspace_and_graph_scoped_retries";
    context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
    context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
    {
      let workspaceLoads = 0;
      let historyLoads = 0;
      const listeners = {};
      const draft = { decision: "ignore" };
      const panel = makePanel({
        _loading: false,
        _payload: { status: "circuit_found_no_evidence" },
        _nilmWorkspaceError: "Could not load NILM workspace.",
      });
      panel._nilmDecisionDrafts.set("draft", draft);
      panel._loadNilmWorkspace = async () => { workspaceLoads += 1; };
      panel._loadNilmWorkspaceHistory = async () => { historyLoads += 1; };
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll() { return []; },
        querySelector(selector) {
          return selector === "[data-retry-nilm-workspace]" ? {
            addEventListener(type, callback) { listeners[type] = callback; },
          } : null;
        },
      };
      panel._render();
      assert.ok(panel.shadowRoot.innerHTML.includes("data-nilm-workspace-error"));
      assert.equal(typeof listeners.click, "function");
      await listeners.click();
      assert.deepEqual([workspaceLoads, historyLoads], [1, 0]);
      assert.equal(panel._nilmDecisionDrafts.get("draft"), draft);
    }
    {
      let workspaceLoads = 0;
      let historyLoads = 0;
      const listeners = {};
      const draft = { start: "2026-07-09T10:00", label: "Dryer" };
      const panel = makePanel({
        _loading: false,
        _payload: { status: "circuit_found_no_evidence" },
        _nilmWorkspace: makeWorkspace({ history: { api_path: "history/period/2026-07-09" } }),
        _nilmWorkspaceHistoryError: "Could not load NILM history.",
        _nilmLabelIntervalDraft: draft,
      });
      panel._loadNilmWorkspace = async () => { workspaceLoads += 1; };
      panel._loadNilmWorkspaceHistory = async () => { historyLoads += 1; };
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll() { return []; },
        querySelector(selector) {
          return selector === "[data-retry-nilm-history]" ? {
            addEventListener(type, callback) { listeners[type] = callback; },
          } : null;
        },
      };
      panel._render();
      const html = panel.shadowRoot.innerHTML;
      assert.ok(html.includes("data-nilm-history-error"));
      assert.ok(html.includes("nilm-graph-section"));
      assert.ok(!html.includes("No graph history is available yet."));
      assert.equal(typeof listeners.click, "function");
      await listeners.click();
      assert.deepEqual([historyLoads, workspaceLoads], [1, 0]);
      assert.equal(panel._nilmLabelIntervalDraft, draft);
    }

    name = "test_failed_nilm_workspace_refresh_does_not_leave_stale_content_visible";
    {
      const panel = makePanel({
        _payload: { circuit: { circuit_id: "mains" } },
        _nilmWorkspace: makeWorkspace({ signatures: [{ signature_id: "stale" }] }),
        _evidenceRequestId: 1,
      });
      panel._render = () => {};
      panel._loadedRouteKey = panel._routeKey();
      panel._requestJson = async () => { throw new Error("refresh failed"); };
      await panel._loadNilmWorkspace(1, panel._loadedRouteKey);
      assert.equal(panel._nilmWorkspace, null);
      assert.match(panel._nilmWorkspaceError, /refresh failed/);
    }

    name = "test_route_replacement_settles_transient_panel_state";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains-a";
      const panel = makePanel({
        _evidenceRequestId: 7,
        _busyAction: "nilm_label_interval_save",
        _historyLoading: true,
        _nilmActiveLane: "published",
        _nilmSelectedReviewKey: "assignment:a",
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      context.window.location.search = "?circuit_id=mains-b";
      panel._requestJson = async () => ({
        status: "circuit_found_no_evidence",
        circuit: { circuit_id: "mains-b" },
        actions: {},
      });
      await panel._loadEvidence({ routeKey: panel._routeKey() });
      assert.equal(panel._busyAction, "");
      assert.ok(!panel._historyLoading);
      assert.equal(panel._nilmActiveLane, "needs_review");
      assert.equal(panel._nilmSelectedReviewKey, "");
      assert.ok(!panel._renderChart({}).includes("data-loading-skeleton"));
    }

    name = "test_same_route_workspace_refresh_preserves_nilm_lane_selection";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const panel = makePanel({
        _nilmActiveLane: "assigned",
        _nilmSelectedReviewKey: "assignment:one",
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel._requestJson = async (apiPath) => apiPath.includes("nilm_workspace") ?
        makeWorkspace() : {
          status: "circuit_found_no_evidence",
          circuit: { circuit_id: "mains" },
          nilm: {
            workspace_call_api_path: "circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains",
          },
          actions: {},
        };
      await panel._loadEvidence({ routeKey: panel._routeKey() });
      assert.equal(panel._nilmActiveLane, "assigned");
      assert.equal(panel._nilmSelectedReviewKey, "assignment:one");
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_alert_decision_render_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_alert_feedback_uses_one_semantic_decision_flow";
    {
      const panel = makePanel({
        _payload: { actions: { acknowledge: {}, mark_expected: {}, mark_confirmed: {}, mark_unhelpful: {} } },
        _inlineFeedback: { scope: "alert-response", kind: "success", message: "Saved" },
      });
      const html = panel._renderAlertResponse();
      for (const expected of [
        '<fieldset class="decision-group"',
        'name="alert_decision"',
        'value="acknowledge"',
        'value="mark_expected"',
        'value="mark_confirmed"',
        'value="mark_unhelpful"',
        'id="apply_alert_decision"',
        'aria-live="polite"',
      ]) assert.ok(html.includes(expected), expected);
      assert.equal((html.match(/id="apply_alert_decision"/g) || []).length, 1);
      assert.equal((html.match(/aria-live="polite"/g) || []).length, 1);
      for (const duplicate of ["acknowledge", "mark_expected", "mark_confirmed", "mark_unhelpful"]) {
        assert.ok(!html.includes(`id="${duplicate}"`));
      }
    }
    name = "test_nilm_finished_alert_uses_completion_decisions_and_overrides_workspace_route";
    {
      const panel = makePanel({
        _payload: {
          actions: {
            acknowledge: {},
            mark_nilm_appliance_correct: {},
            mark_nilm_appliance_wrong: {},
          },
        },
      });
      const html = panel._renderAlertResponse();
      for (const expected of [
        'value="acknowledge"',
        'value="mark_nilm_appliance_correct"',
        'value="mark_nilm_appliance_wrong"',
      ]) assert.ok(html.includes(expected), expected);
      assert.ok(!html.includes('value="mark_expected"'));
      context.window.location.search = "?alert_id=alert-1&nilm_workspace=1&appliance_detail=1";
      assert.equal(panel._routeRequestsApplianceDetail(), false);
      assert.equal(panel._routeRequestsNilmWorkspace(), false);
    }
    name = "test_alert_decision_radio_enables_apply_and_feedback_receives_focus";
    {
      const listeners = {};
      const apply = { disabled: true, addEventListener() {} };
      const radio = {
        value: "mark_expected",
        addEventListener(type, callback) { listeners[type] = callback; },
      };
      let focused = 0;
      const panel = makePanel({ _loading: false, _payload: { status: "not_found", actions: {} } });
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll(selector) { return selector === "[data-alert-decision]" ? [radio] : []; },
        querySelector(selector) {
          if (selector === "#apply_alert_decision") return apply;
          if (selector === '[data-inline-feedback="alert-response"]') {
            return { focus() { focused += 1; } };
          }
          return null;
        },
      };
      panel._render();
      assert.equal(typeof listeners.change, "function");
      listeners.change();
      assert.equal(panel._alertDecision, "mark_expected");
      assert.ok(!apply.disabled);
      panel._render = () => {};
      panel._setInlineFeedback("alert-response", "success", "Saved");
      assert.equal(focused, 1);
    }
    name = "test_alert_decision_requires_a_choice_locally";
    {
      let scrolls = 0;
      const panel = makePanel();
      panel._render = () => {};
      panel._scrollToTop = () => { scrolls += 1; };
      panel.shadowRoot.querySelector = () => null;
      await panel._applyAlertDecision();
      assert.equal(scrolls, 0);
      assert.equal(panel._inlineFeedback.scope, "alert-response");
      assert.equal(panel._inlineFeedback.kind, "error");
      assert.equal(panel._inlineFeedback.message, "Choose a response before applying.");
    }
    name = "test_alert_secondary_actions_and_recommendations_use_disclosures";
    {
      const panel = makePanel({
        _payload: {
          actions: {
            acknowledge: {},
            pause_alerts: {},
            open_appliance_detail: {},
            relearn_baseline: {},
            open_advanced_circuit_settings: {},
          },
          setting_recommendations: [{ display_label: "Daily threshold", status: "pending", actions: { apply: {} } }],
        },
      });
      const html = panel._renderAlertContent(
        { circuit_id: "fridge", feature: "daily_energy", graph_entities: [] },
        { name: "Kitchen Refrigerator" },
      );
      const order = [
        html.indexOf('id="apply_alert_decision"'),
        html.indexOf('data-alert-disclosure="pause"'),
        html.indexOf('data-alert-disclosure="tune"'),
        html.indexOf('data-alert-disclosure="recommendations"'),
      ];
      assert.ok(order.every((position) => position >= 0));
      assert.ok(order.every((position, index) => !index || order[index - 1] < position));
      for (const name of ["pause", "tune", "recommendations"]) {
        assert.match(html, new RegExp(`<details[^>]+data-alert-disclosure="${name}"`));
      }
      for (const action of [
        "pause_alerts",
        "open_appliance_detail",
        "relearn_baseline",
        "open_advanced_circuit_settings",
      ]) assert.ok(html.includes(`id="${action}"`));
    }
    name = "test_alert_response_and_secondary_disclosures_are_unframed";
    {
      const panel = makePanel({
        _payload: { actions: { acknowledge: {}, pause_alerts: {}, relearn_baseline: {} } },
      });
      const html = panel._renderAlertContent(
        { circuit_id: "fridge", feature: "daily_energy", graph_entities: [] },
        { name: "Kitchen Refrigerator" },
      );
      const wrappers = [
        html.match(/<section class="([^"]*response-section[^"]*)">/),
        html.match(/<details class="([^"]*)" data-alert-disclosure="pause">/),
        html.match(/<details class="([^"]*)" data-alert-disclosure="tune">/),
      ];
      for (const wrapper of wrappers) {
        assert.ok(wrapper);
        assert.ok(!wrapper[1].split(/\\s+/).includes("panel"), wrapper[0]);
      }
      assert.ok(html.includes('class="decision-tile"'));
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_alert_decision_action_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_alert_decision_success_stays_local_after_refresh";
    {
      const calls = [];
      const loads = [];
      let scrolls = 0;
      context.window.location.search = "?alert_id=alert-1";
      const panel = makePanel({
        _payload: {
          alert: { alert_id: "alert-1", circuit_id: "fridge", feature: "daily_energy" },
          actions: {
            mark_expected: makeAction("mark_alert_expected", { alert_id: "alert-1" }),
          },
        },
        _alertDecision: "mark_expected",
      });
      context.history.replaceState = (_state, _title, path) => {
        const route = new URL(path, context.window.location.origin);
        context.window.location.pathname = route.pathname;
        context.window.location.search = route.search;
      };
      panel._render = () => {};
      panel._scrollToTop = () => { scrolls += 1; };
      panel.shadowRoot.querySelector = () => null;
      panel._hass = {
        callService: async (_domain, service) => calls.push(service),
      };
      panel._loadEvidence = async (options) => {
        loads.push(options);
        panel._payload = { status: "historical_alert_not_found", actions: {} };
        panel._loading = false;
      };
      await panel._applyAlertDecision();
      assert.deepEqual(
        [calls.length, calls[0], loads.length, scrolls,
          panel._inlineFeedback.scope, panel._inlineFeedback.kind,
          panel._inlineFeedback.message],
        [1, "mark_alert_expected", 1, 0, "alert-response", "success",
          "Marked as expected behavior."],
      );
      assert.doesNotMatch(loads[0].routeKey, /alert_id=/);
      assert.match(loads[0].routeKey, /circuit_id=fridge/);
      assert.match(loads[0].routeKey, /feature=daily_energy/);
      const fallback = panel._renderNotFound();
      assert.ok(fallback.includes("Marked as expected behavior."));
      assert.ok(fallback.includes('data-inline-feedback="alert-response"'));
    }
    name = "test_alert_acknowledgement_survives_real_alert_id_refresh";
    {
      const calls = [];
      const requests = [];
      const replaced = [];
      let focused = 0;
      let scrolls = 0;
      context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
      context.window.location.search = "?alert_id=alert-1";
      const panel = makePanel({
        _loading: false,
        _historyLoading: true,
        _payload: {
          alert: { alert_id: "alert-1", circuit_id: "fridge", feature: "daily_energy" },
          actions: {
            acknowledge: makeAction("acknowledge_alert", { alert_id: "alert-1" }),
          },
        },
        _alertDecision: "acknowledge",
      });
      panel._loadedRouteKey = panel._routeKey();
      context.history.replaceState = (_state, _title, path) => {
        replaced.push(path);
        const route = new URL(path, context.window.location.origin);
        context.window.location.pathname = route.pathname;
        context.window.location.search = route.search;
        panel._loadEvidenceIfRouteChanged();
      };
      panel._render = () => {};
      panel._scrollToTop = () => { scrolls += 1; };
      panel.shadowRoot.querySelector = () => ({ focus() { focused += 1; } });
      panel._hass = {
        callService: async (_domain, service) => calls.push(service),
      };
      panel._requestJson = async (apiPath, fetchPath) => {
        requests.push({ apiPath, fetchPath });
        return {
          status: "circuit_found_no_evidence",
          circuit: { circuit_id: "fridge", name: "Kitchen Refrigerator" },
          actions: {},
        };
      };
      await panel._applyAlertDecision();
      assert.deepEqual(
        [calls.length, calls[0], requests.length, replaced.length,
          panel._routeKey(), panel._loadedRouteKey, panel._loading,
          panel._payload.status, panel._payload.alert, panel._historyLoading,
          scrolls, focused, panel._inlineFeedback.message],
        [1, "acknowledge_alert", 1, 1, panel._loadedRouteKey,
          panel._loadedRouteKey, false, "circuit_found_no_evidence", undefined,
          false, 0, 1, "Alert acknowledged."],
      );
      assert.doesNotMatch(requests[0].apiPath, /alert_id=/);
      assert.match(requests[0].apiPath, /circuit_id=fridge/);
      assert.match(requests[0].apiPath, /feature=daily_energy/);
      assert.doesNotMatch(replaced[0], /alert_id=/);
      assert.ok(panel._renderNotFound().includes("Alert acknowledged."));
    }
    for (const row of [
      {
        name: "test_alert_decision_service_failure_stays_local",
        decision: "mark_unhelpful",
        action: makeAction("mark_alert_unhelpful"),
        callService: async () => { throw new Error("service offline"); },
        expectedCalls: 1,
        expectedMessage: "service offline",
      },
      {
        name: "test_alert_decision_guard_failure_stays_local",
        decision: "mark_expected",
        action: {
          service: "mark_alert_expected",
          enabled: false,
          unavailable_label: "Expected feedback is temporarily unavailable.",
        },
        callService: async () => {},
        expectedCalls: 0,
        expectedMessage: "Expected feedback is temporarily unavailable.",
      },
    ]) {
      name = row.name;
      let calls = 0;
      let loads = 0;
      let scrolls = 0;
      let focused = 0;
      const panel = makePanel({
        _payload: { actions: { [row.decision]: row.action } },
        _alertDecision: row.decision,
      });
      panel._render = () => {};
      panel._scrollToTop = () => { scrolls += 1; };
      panel._loadEvidence = async () => { loads += 1; };
      panel.shadowRoot.querySelector = () => ({ focus() { focused += 1; } });
      panel._hass = { callService: async () => { calls += 1; return row.callService(); } };
      await panel._applyAlertDecision();
      assert.deepEqual(
        [calls, loads, scrolls, panel._error, panel._alertDecision,
          panel._inlineFeedback.scope, panel._inlineFeedback.kind, focused],
        [row.expectedCalls, 0, 0, "", row.decision, "alert-response", "error", 1],
      );
      assert.ok(panel._inlineFeedback.message.includes(row.expectedMessage));
    }
    name = "test_shared_panel_action_completions_ignore_replacement_routes";
    context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
    for (const kind of ["alert", "recommendation"]) {
      for (const outcome of ["resolve", "reject"]) {
        context.window.location.search = "?circuit_id=a";
        let settle;
        let renders = 0;
        let scrolls = 0;
        let replaces = 0;
        let requests = 0;
        const panel = makePanel({ _evidenceRequestId: 3 });
        panel._loadedRouteKey = panel._routeKey();
        panel._render = () => { renders += 1; };
        panel._scrollToTop = () => { scrolls += 1; };
        panel.shadowRoot.querySelector = () => null;
        context.history.replaceState = () => { replaces += 1; };
        panel._hass = {
          callService: () => new Promise((resolve, reject) => { settle = { resolve, reject }; }),
        };
        const action = makeAction(`${kind}_service`);
        let operation;
        if (kind === "alert") {
          panel._payload = {
            alert: { alert_id: "alert-a", circuit_id: "a", feature: "daily_energy" },
            actions: { mark_expected: action },
          };
          operation = panel._callAction("mark_expected", { feedbackScope: "alert-response" });
        } else {
          panel._payload = {
            circuit: { circuit_id: "a" },
            actions: {},
            setting_recommendations: [{ actions: { apply: action } }],
          };
          operation = panel._callRecommendationAction(0, "apply");
        }
        await Promise.resolve();
        context.window.location.search = "?circuit_id=b";
        const payloadB = { status: "circuit_found_no_evidence",
          circuit: { circuit_id: "b" }, actions: {} };
        panel._requestJson = async () => { requests += 1; return payloadB; };
        await panel._loadEvidence({ routeKey: panel._routeKey() });
        const rendersAtB = renders;
        if (outcome === "resolve") settle.resolve();
        else settle.reject(new Error("late failure"));
        await operation;
        assert.deepEqual(
          [panel._payload, requests, renders, scrolls, replaces,
            panel._lastActionMessage, panel._error, panel._inlineFeedback.message],
          [payloadB, 1, rendersAtB, 0, 0, "", "", ""],
        );
      }
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_focused_nilm_history_request_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
    context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
    const history = { start: "2026-06-06T00:00:00Z",
      end: "2026-06-06T08:00:00Z", max_hours: 24,
      api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=8",
      fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=8",
    };
    name = "test_focused_nilm_history_failure_retries_exact_window_and_keeps_drafts";
    {
      const listeners = {};
      const requests = [];
      const stale = [[{ state: "100" }]];
      const fresh = [[{ state: "350" }]];
      const panel = makePanel({
        _loading: false,
        _evidenceRequestId: 1,
        _payload: { status: "circuit_found_no_evidence" },
        _nilmWorkspace: makeWorkspace({
          history: {
            ...history,
            start: "2026-06-06T03:00:00Z", end: "2026-06-06T04:00:00Z",
            api_path: history.api_path.replace("hours=8", "hours=1"),
            fetch_path: history.fetch_path.replace("hours=8", "hours=1"),
          },
        }),
        _nilmWorkspaceHistorySeries: stale,
        _nilmWorkspaceError: "unrelated workspace warning",
        _nilmFocusedSignature: "signature-1",
        _nilmGraphWindow: { start: 1, end: 2, min: 0, max: 3 },
        _nilmIntervalEditorOpen: true,
        _nilmLabelIntervalDraft: { start: "2026-06-06T02:00",
          end: "2026-06-06T02:30", label: "Dryer" },
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._nilmDecisionDrafts.set("signature-1", { decision: "identify", identifyMode: "label" });
      const graphWindow = panel._nilmGraphWindow;
      const intervalDraft = panel._nilmLabelIntervalDraft;
      const decisionDrafts = panel._nilmDecisionDrafts;
      panel._requestJson = async (apiPath, fetchPath) => {
        requests.push({ apiPath, fetchPath });
        if (requests.length === 1) throw new Error("focused history failed");
        return fresh;
      };
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll() { return []; },
        querySelector(selector) {
          if (selector === "[data-retry-nilm-history]" &&
              this.innerHTML.includes("data-retry-nilm-history")) {
            return { addEventListener(type, callback) { listeners[type] = callback; } };
          }
          return null;
        },
      };
      const window = { start: Date.parse("2026-06-06T01:30:00Z"),
        end: Date.parse("2026-06-06T02:45:00Z") };
      await panel._loadNilmWorkspaceHistoryForWindow(window);
      assert.deepEqual(panel._nilmWorkspaceHistorySeries, stale);
      assert.match(panel._nilmWorkspaceHistoryError, /focused history failed/);
      assert.ok(panel.shadowRoot.innerHTML.includes("data-nilm-history-error"));
      assert.equal(typeof listeners.click, "function");
      const failed = panel._nilmWorkspaceHistoryFailedRequest;
      assert.deepEqual(
        [failed.hours, failed.window.start, failed.window.end],
        [2, window.start, window.end],
      );
      await listeners.click();
      assert.equal(requests.length, 2);
      assert.deepEqual(
        [requests[0].apiPath, requests[0].fetchPath],
        [requests[1].apiPath, requests[1].fetchPath],
      );
      assert.match(requests[1].apiPath, /hours=2/);
      assert.deepEqual(
        [panel._nilmWorkspaceHistorySeries, panel._nilmWorkspaceHistoryError,
          panel._nilmWorkspaceHistoryFailedRequest, panel._nilmWorkspaceError,
          panel._nilmFocusedSignature, panel._nilmGraphWindow,
          panel._nilmLabelIntervalDraft, panel._nilmDecisionDrafts,
          panel._nilmIntervalEditorOpen],
        [fresh, "", null, "unrelated workspace warning", "signature-1",
          graphWindow, intervalDraft, decisionDrafts, true],
      );
    }
    name = "test_focused_nilm_history_keeps_latest_signature_when_requests_finish_out_of_order";
    {
      const pending = [];
      let renders = 0;
      const panel = makePanel({
        _evidenceRequestId: 4,
        _nilmWorkspace: makeWorkspace({
          history,
          sessions: [
            { signature_fingerprint: "signature-a", start: "2026-06-06T01:00:00Z",
              end: "2026-06-06T01:30:00Z" },
            { signature_fingerprint: "signature-b", start: "2026-06-06T06:00:00Z",
              end: "2026-06-06T06:30:00Z" },
          ],
        }),
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => { renders += 1; };
      panel._requestJson = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
      const seriesA = [[{ state: "100" }]];
      const seriesB = [[{ state: "600" }]];
      const focusA = panel._focusNilmSignatureOnGraph("signature-a", { scroll: false, toggle: false });
      const focusB = panel._focusNilmSignatureOnGraph("signature-b", { scroll: false, toggle: false });
      assert.equal(pending.length, 2);
      assert.ok(panel._nilmWorkspaceHistoryLoading);
      pending[1].resolve(seriesB);
      await focusB;
      const windowB = panel._nilmGraphWindow;
      const startB = panel._nilmWorkspace.history.start;
      const rendersAfterB = renders;
      assert.deepEqual(
        [panel._nilmWorkspaceHistorySeries, panel._nilmFocusedSignature,
          panel._nilmWorkspaceHistoryLoading],
        [seriesB, "signature-b", false],
      );
      assert.ok(windowB);
      pending[0].resolve(seriesA);
      await focusA;
      assert.deepEqual(
        [panel._nilmWorkspaceHistorySeries, panel._nilmFocusedSignature,
          panel._nilmGraphWindow, panel._nilmWorkspace.history.start,
          panel._nilmWorkspaceHistoryLoading, renders],
        [seriesB, "signature-b", windowB, startB, false, rendersAfterB],
      );
    }
    name = "test_focused_nilm_history_cannot_mutate_after_navigation";
    {
      let resolveFocused;
      let renders = 0;
      const panel = makePanel({
        _evidenceRequestId: 2,
        _payload: { circuit: { circuit_id: "mains" }, actions: {} },
        _nilmWorkspace: makeWorkspace({
          history,
          sessions: [{ signature_fingerprint: "signature-a",
            start: "2026-06-06T01:00:00Z", end: "2026-06-06T01:30:00Z" }],
        }),
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => { renders += 1; };
      panel._requestJson = (apiPath) => apiPath.includes("nilm_workspace_history") ?
        new Promise((resolve) => { resolveFocused = resolve; }) :
        Promise.resolve({ status: "no_evidence", actions: {} });
      const focus = panel._focusNilmSignatureOnGraph(
        "signature-a",
        { scroll: false, toggle: false },
      );
      context.window.location.search = "?circuit_id=kitchen";
      const nextRoute = panel._routeKey();
      await panel._loadEvidence({ routeKey: nextRoute });
      const rendersAfterNavigation = renders;
      resolveFocused([[{ state: "100" }]]);
      await focus;
      assert.deepEqual(
        [panel._loadedRouteKey, panel._nilmWorkspace,
          panel._nilmWorkspaceHistorySeries.length, panel._nilmWorkspaceHistoryError,
          panel._nilmWorkspaceHistoryFailedRequest, panel._nilmWorkspaceHistoryLoading,
          panel._nilmFocusedSignature, panel._nilmGraphWindow,
          panel._lastActionMessage, renders],
        [nextRoute, null, 0, "", null, false, "", null, "", rendersAfterNavigation],
      );
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_nilm_workspace_places_graph_before_review_and_diagnostics() -> None:
    asset = _frontend_source()

    graph = asset.index("_renderNilmGraph(workspace, graphWindow, graphBands)")
    lanes = asset.index("_renderNilmWorkspaceLanes(workspace)")
    review = asset.index("_renderNilmReviewLayout(workspace)")
    secondary = asset.index("_renderNilmSecondaryCollections(workspace)")

    assert graph < lanes < review < secondary
    assert "_renderNilmReviewQueue" not in asset


def test_nilm_graph_uses_dense_watt_series_and_disables_selection_tooltips() -> None:
    _run_panel_node_script(
        """
(() => {
  const panel = makePanel({
    _hass: { states: {
      "sensor.mains_power": { attributes: { unit_of_measurement: "KW" } },
      "sensor.mixed_power": { attributes: { unit_of_measurement: "Kw" } },
      "sensor.milli_power": { attributes: { unit_of_measurement: "mW" } },
      "sensor.mega_power": { attributes: { unit_of_measurement: "MW" } },
    } },
  });
  const start = Date.parse("2026-07-31T12:00:00Z");
  const history = [Array.from({ length: 2160 }, (_item, index) => ({
    entity_id: "sensor.mains_power",
    state: String(index / 1000),
    last_changed: new Date(start + index * 10000).toISOString(),
  })), [{
    entity_id: "sensor.milli_power",
    state: "1000",
    last_changed: new Date(start).toISOString(),
  }], [{
    entity_id: "sensor.mega_power",
    state: "0.001",
    last_changed: new Date(start).toISOString(),
  }], [{
    entity_id: "sensor.mixed_power",
    state: "0.18",
    last_changed: new Date(start).toISOString(),
  }]];
  panel._nilmWorkspaceHistorySeries = history;
  const nilmSeries = panel._visibleNilmWorkspaceSeries(makeWorkspace(), null);
  assert.equal(nilmSeries[0].points.length, 2160);
  assert.equal(nilmSeries[0].unit, "W");
  assert.equal(nilmSeries[0].points[1000].value, 1000);
  assert.equal(nilmSeries[1].points[0].value, 1);
  assert.equal(nilmSeries[2].points[0].value, 1000);
  assert.equal(nilmSeries[3].points[0].value, 180);
  assert.equal(panel._chartSeries(history)[0].points.length, 240);

  panel._nilmIntervalEditorOpen = true;
  panel._nilmWorkspaceHistoryLoading = false;
  panel._nilmWorkspaceHistoryError = "";
  const graph = panel._renderNilmGraph(
    makeWorkspace({ known_load_overlays: [{ entity_ids: ["sensor.pump_power"] }] }),
    { start, end: start + 2159 * 10000 },
    [],
  );
  assert.ok(graph.includes('class="axis-label"'));
  assert.ok(graph.includes(">W</text>"));
  assert.ok(graph.includes('data-nilm-chart-select="1"'));
  assert.ok(!graph.includes("data-nilm-overlay-toggle"));

  const listeners = [];
  const tooltip = {
    hidden: "false",
    setAttribute(name, value) { if (name === "aria-hidden") this.hidden = value; },
  };
  const point = { addEventListener() {} };
  const svg = {
    dataset: { nilmChartSelect: "1" },
    addEventListener(type) { listeners.push(type); },
    querySelectorAll() { return [point]; },
    querySelector() { return {}; },
    closest() { return { querySelector() { return tooltip; } }; },
  };
  panel.shadowRoot = {
    querySelectorAll(selector) { return selector === "svg.chart" ? [svg] : []; },
  };
  panel._attachChartInspectors();
  assert.equal(tooltip.hidden, "true");
  assert.ok(!listeners.includes("pointermove"));
})();
"""
    )


def test_nilm_lane_rendering_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    assert.equal(typeof context.Panel.prototype._nilmReviewItems, "undefined");

    name = "test_nilm_workspace_summary_is_compact_and_lanes_have_one_inventory";
    {
      const panel = makePanel();
      const workspace = makeWorkspace({
        circuit: { circuit_id: "mains", name: "Whole Home Main" },
        lane_counts: { needs_review: 5, assigned: 1, published: 2, hidden: 0 },
      });
      workspace.lanes.needs_review.signature_ids = ["sig-1", "sig-2"];
      workspace.lanes.assigned.assignment_ids = ["assignment-1"];
      const summary = panel._renderNilmWorkspaceSummary(workspace);
      for (const expected of [
        "Whole Home Main",
        "data-nilm-review-progress",
        'value="3"',
        'max="8"',
      ]) {
        assert.ok(summary.includes(expected));
      }
      assert.equal((summary.match(/<progress/g) || []).length, 1);
      for (const duplicate of [
        'class="metric"',
        "data-nilm-lane=",
        "Assigned",
        "Needs Validation",
        "Ready to Publish",
        "Published",
        "Removed",
      ]) {
        assert.ok(!summary.includes(duplicate));
      }
      name = "test_nilm_workspace_renders_review_lanes_from_payload";
      const lanes = panel._renderNilmWorkspaceLanes(workspace);
      assert.equal((lanes.match(/data-nilm-lane=/g) || []).length, 4);
      for (const expected of [
        'role="tablist"', 'role="tab"', 'data-nilm-lane="needs_review"',
        "Needs Review", "Published", "Removed", "<strong>5</strong>",
      ]) assert.ok(lanes.includes(expected), expected);
      assert.doesNotMatch(
        context.Panel.prototype._renderNilmWorkspaceLanes.toString(),
        /summaryOnly/,
      );
      Object.assign(panel, {
        _loading: false,
        _nilmWorkspaceLoading: false,
        _nilmWorkspace: workspace,
      });
      const body = panel._renderNilmWorkspaceContent();
      assert.ok(body.includes('class="nilm-workspace"'));
      assert.ok(!body.includes('<section class="panel"><section class="workspace-section workspace-summary"'));
      assert.ok(
        body.indexOf("nilm-graph-section") <
          body.indexOf('class="nilm-lanes"'),
      );
    }

    name = "test_nilm_lane_items_preserve_indexes_and_render_one_selected_inspector";
    {
      const panel = makePanel();
      panel._nilmWorkspace = makeWorkspace({
        signatures: [
          {
            signature_id: "sig-1",
            display_label: "Unknown load 1",
          },
          { signature_id: "sig-reviewed" },
          {
            signature_id: "sig-2",
            display_label: "Unknown load 2",
            actions: { ignore: {} },
          },
        ],
        assignments: [
          { assignment_id: "assignment-reviewed" },
          {
            assignment_id: "assignment-2",
            display_name: "Heat Pump",
            actions: { publish: {} },
          },
        ],
      });
      panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-1", "sig-2"];
      panel._nilmWorkspace.lanes.assigned.assignment_ids = ["assignment-2"];
      const items = panel._nilmLaneItems(panel._nilmWorkspace, "needs_review");
      assert.equal(JSON.stringify(items.map((item) => item.index)), "[0,2]");
      panel._nilmSelectedReviewKey = panel._nilmReviewKey(items[1]);
      const html = panel._renderNilmReviewLayout(panel._nilmWorkspace);
      for (const expected of [
        'aria-pressed="true"',
        "Unknown load 2",
        'data-nilm-apply-decision="signature_2"',
      ]) {
        assert.ok(html.includes(expected));
      }
      assert.equal((html.match(/data-nilm-review-inspector/g) || []).length, 1);
      const selectedCard = html.indexOf('data-nilm-review-item="signature:sig-2"');
      const inspector = html.indexOf('<div class="nilm-review-inspector');
      assert.ok(selectedCard >= 0 && inspector > selectedCard);
      assert.ok(html.slice(selectedCard, inspector).includes("</button>"));
      assert.ok(html.indexOf('class="nilm-review-list') < inspector);
      panel._nilmActiveLane = "assigned";
      panel._nilmSelectedReviewKey = "";
      assert.ok(
        panel._renderNilmReviewLayout(panel._nilmWorkspace)
          .includes('data-nilm-assignment-index="1"'),
      );
      panel._nilmActiveLane = "published";
      assert.ok(panel._renderNilmReviewLayout(panel._nilmWorkspace).includes("data-nilm-lane-empty"));
    }

    name = "test_nilm_explicit_empty_needs_review_lane_is_authoritative";
    {
      const panel = makePanel();
      panel._nilmWorkspace = makeWorkspace({
        signatures: [
          { signature_id: "sig-assigned", review_state: "new" },
        ],
      });
      assert.equal(panel._nilmLaneItems(panel._nilmWorkspace, "needs_review").length, 0);
      const tabs = panel._renderNilmWorkspaceLanes(panel._nilmWorkspace);
      const tab = tabs.slice(
        tabs.indexOf('data-nilm-lane="needs_review"'),
        tabs.indexOf("</button>", tabs.indexOf('data-nilm-lane="needs_review"')),
      );
      assert.ok(tab.includes("<strong>0</strong>"));
      const html = panel._renderNilmReviewLayout(panel._nilmWorkspace);
      assert.equal((html.match(/data-nilm-lane-empty/g) || []).length, 1);
      for (const expected of [
        'id="nilm_review_lane_panel"',
        'role="tabpanel"',
        'aria-labelledby="nilm_lane_needs_review"',
      ]) {
        assert.ok(html.includes(expected));
      }
      assert.ok(!html.includes("data-nilm-review-inspector"));
    }

    name = "test_nilm_lane_tabs_change_selection_without_fetching";
    {
      let rendered = 0;
      let fetched = 0;
      const panel = makePanel({
        _nilmSelectedReviewKey: "signature:sig-1",
        _nilmFocusedSignature: "fingerprint-1",
      });
      panel._render = () => { rendered += 1; };
      panel._loadEvidence = () => { fetched += 1; };
      panel._activateNilmLane("assigned");
      assert.equal(panel._nilmActiveLane, "assigned");
      assert.equal(panel._nilmSelectedReviewKey, "");
      assert.equal(panel._nilmFocusedSignature, "");
      assert.deepEqual([rendered, fetched], [1, 0]);
    }

    name = "test_nilm_review_power_percent_scales_and_clamps";
    {
      const panel = makePanel();
      const items = [
        { kind: "signature", item: { typical_power_w: 250 }, index: 0 },
        { kind: "assignment", item: { estimated_power_w: 1000 }, index: 0 },
      ];
      for (const [item, expected] of [
        [items[0], 25],
        [{ kind: "signature", item: { median_power_w: 2000 }, index: 1 }, 100],
        [{ kind: "signature", item: { typical_power_w: -50 }, index: 2 }, 0],
        [{ kind: "signature", item: {}, index: 3 }, 0],
      ]) {
        assert.equal(panel._nilmPowerPercent(item, items), expected);
      }
      const html = panel._renderNilmReviewCard({
        kind: "signature",
        item: {
          signature_id: "sig-1",
          display_label: "Load",
          typical_power_w: 250,
          evidence_strength: 1.4,
        },
        index: 0,
      }, items, false);
      for (const expected of ["--power-percent:25%", "Evidence strength: 100%", '<progress max="100" value="100"']) {
        assert.ok(html.includes(expected));
      }
    }

    name = "test_nilm_workspace_graph_controls_use_accessible_icons";
    {
      const html = makePanel()._renderNilmGraphControls({ start: 0, end: 3600000, min: 0, max: 7200000 });
      for (const [icon, name] of [
        ["mdi:magnify-plus-outline", "Zoom In"],
        ["mdi:magnify-minus-outline", "Zoom Out"],
        ["mdi:chevron-left", "Pan Earlier"],
        ["mdi:chevron-right", "Pan Later"],
      ]) {
        assert.ok(html.includes(`icon="${icon}"`));
        assert.ok(html.includes(`title="${name}"`));
        assert.ok(html.includes(`aria-label="${name}"`));
      }
    }

    name = "test_nilm_signature_cards_carry_graph_focus_without_show_button";
    {
      const panel = makePanel();
      const item = { kind: "signature", index: 0, item: {
        signature_id: "sig-1", feedback_fingerprint: "fingerprint-1",
        display_label: "Unknown load",
      } };
      assert.ok(
        panel._renderNilmReviewCard(item, [item], true)
          .includes('data-nilm-signature-fingerprint="fingerprint-1"'),
      );
      const inspector = panel._renderNilmSignatureReview(item.item, "signature_0", 0);
      assert.ok(!inspector.includes("Show on Graph"));
      assert.ok(!inspector.includes("data-nilm-signature-focus"));
    }

    name = "test_nilm_review_card_shows_compact_occurrence_and_last_seen_context";
    {
      const panel = makePanel();
      const item = { kind: "signature", index: 0, item: {
        signature_id: "sig-1", display_label: "Unknown load",
        typical_power_w: 1250, evidence_strength: 0.82, seen_count: 7,
        last_seen: "2026-07-09T14:30:00Z",
      } };
      const html = panel._renderNilmReviewCard(item, [item], true);
      for (const expected of ["Seen count: 7", "Last seen:", "2026-07-09"]) {
        assert.ok(html.includes(expected));
      }
    }

    name = "test_nilm_state_rerenders_restore_deep_keyboard_focus";
    context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
    context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
    for (const item of [
      {
        selector: "[data-nilm-decision]", event: "change",
        dataset: { nilmDecision: "", nilmDecisionKey: "fingerprint-1" },
        value: "identify",
      },
      {
        selector: "[data-nilm-identify-mode]", event: "change",
        dataset: { nilmIdentifyMode: "", nilmDecisionKey: "fingerprint-1" },
        value: "label",
      },
      {
        selector: "[data-nilm-lane]", event: "click",
        dataset: { nilmLane: "assigned" },
      },
      {
        selector: "[data-nilm-review-item]", event: "click", loadsGraph: true,
        dataset: {
          nilmReviewItem: "signature:sig-1",
          nilmSignatureFingerprint: "fingerprint-1",
        },
      },
    ]) {
      const panel = makePanel({
        _payload: { status: "circuit_found_no_evidence",
          circuit: { circuit_id: "mains" } },
        _nilmWorkspace: null,
      });
      let current;
      const shadow = {
        activeElement: null,
        _html: "",
        set innerHTML(value) {
          this._html = value;
          this.activeElement = null;
          current = {
            dataset: { ...item.dataset },
            value: item.value,
            listeners: {},
            addEventListener(type, callback) { this.listeners[type] = callback; },
            focus() { shadow.activeElement = this; },
          };
        },
        get innerHTML() { return this._html; },
        querySelector() { return null; },
        querySelectorAll(selector) { return selector === item.selector ? [current] : []; },
      };
      panel.shadowRoot = shadow;
      if (item.loadsGraph) {
        panel._nilmWorkspace = makeWorkspace({
          signatures: [{
            signature_id: "sig-1",
            feedback_fingerprint: "fingerprint-1",
          }],
        });
        panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-1"];
        panel._focusNilmSignatureOnGraph = async () => {
          panel._render();
          await Promise.resolve();
          panel._render();
          return true;
        };
      }
      panel._render();
      const before = current;
      shadow.activeElement = before;
      assert.equal(typeof before.listeners[item.event], "function");
      before.listeners[item.event]({ preventDefault() {}, stopPropagation() {} });
      await Promise.resolve();
      await Promise.resolve();
      assert.ok(shadow.activeElement && shadow.activeElement !== before);
      assert.deepEqual(shadow.activeElement.dataset, item.dataset);
      if (item.value) {
        assert.equal(shadow.activeElement.value, item.value);
      }
    }

    name = "test_nilm_lane_tabs_use_roving_focus_and_keyboard_activation";
    {
      const panel = makePanel({
        _nilmActiveLane: "needs_review",
        _payload: {
          status: "circuit_found_no_evidence",
          circuit: { circuit_id: "mains" },
        },
      });
      const html = panel._renderNilmWorkspaceLanes(makeWorkspace());
      assert.equal((html.match(/tabindex="0"/g) || []).length, 1);
      assert.equal((html.match(/tabindex="-1"/g) || []).length, 3);
      const laneKeys = ["needs_review", "assigned", "published", "hidden"];
      let buttons = [];
      const shadow = {
        activeElement: null,
        _html: "",
        set innerHTML(value) {
          this._html = value;
          this.activeElement = null;
          buttons = laneKeys.map((key) => ({
            dataset: { nilmLane: key },
            listeners: {},
            addEventListener(type, callback) { this.listeners[type] = callback; },
            focus() { shadow.activeElement = this; },
          }));
        },
        get innerHTML() { return this._html; },
        querySelector() { return null; },
        querySelectorAll(selector) { return selector === "[data-nilm-lane]" ? buttons : []; },
      };
      panel.shadowRoot = shadow;
      panel._render();
      let active = buttons[0];
      shadow.activeElement = active;
      for (const [key, expectedLane] of [
        ["ArrowRight", "assigned"],
        ["End", "hidden"],
        ["Home", "needs_review"],
        ["ArrowLeft", "hidden"],
      ]) {
        let prevented = 0;
        active.listeners.keydown({ key, preventDefault() { prevented += 1; } });
        active = shadow.activeElement;
        assert.equal(prevented, 1, key);
        assert.equal(panel._nilmActiveLane, expectedLane, key);
        assert.equal(active.dataset.nilmLane, expectedLane, key);
      }
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_panel_command_targets_and_focus_styles_are_explicit() -> None:
    asset = _frontend_source()
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


def test_nilm_workspace_disclosure_and_ownership_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_nilm_interval_editor_is_progressively_disclosed";
    {
      const panel = makePanel({ _nilmWorkspace: makeWorkspace() });
      const initial = panel._renderNilmWorkspaceBody();
      assert.ok(initial.includes("data-nilm-open-interval-editor"));
      assert.ok(!initial.includes('class="nilm-interval-form"'));
      panel._render = () => {};
      panel._selectNilmEdgeTime({
        dataset: {
          nilmEdgeTime: "2026-06-24T18:12:00Z",
          nilmEdgeDirection: "on",
        },
      });
      const selected = panel._renderNilmWorkspaceBody();
      assert.ok(panel._nilmIntervalEditorOpen);
      assert.ok(selected.includes('class="nilm-interval-form"'));
      const graph = selected.indexOf("nilm-graph-section");
      const editor = selected.indexOf("nilm-interval-editor-section");
      const lanes = selected.indexOf('role="tablist"');
      assert.ok(graph >= 0 && graph < editor && editor < lanes);
      const secondary = panel._renderNilmSecondaryCollections(panel._nilmWorkspace);
      assert.ok(secondary.includes("data-nilm-secondary-collections"));
      assert.ok(secondary.includes("<section"));
      assert.ok(!secondary.includes('class="nilm-interval-form"'));
    }

    name = "test_nilm_saved_interval_focus_and_edit_are_separate";
    {
      const interval = {
        interval_id: "interval-1",
        assignment_id: "assignment-1",
        display_label: "Dishwasher",
        start: "2026-06-24T18:10:00Z",
        end: "2026-06-24T18:30:00Z",
      };
      const panel = makePanel({
        _nilmWorkspace: makeWorkspace({
          history: {
            api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains",
            start: "2026-06-24T18:00:00Z",
            end: "2026-06-24T19:00:00Z",
          },
          assignments: [{
            assignment_id: "assignment-1",
            display_name: "Dishwasher",
            appliance_id: "dishwasher",
            appliance_profile: "dishwasher",
          }],
          label_intervals: [interval],
        }),
      });
      panel._nilmWorkspaceHistorySeries = [[
        { entity_id: "sensor.mains_power", state: "100", effective_role: "real_power",
          source_unit: "W", last_changed: "2026-06-24T18:00:00Z" },
        { entity_id: "sensor.mains_power", state: "900", effective_role: "real_power",
          source_unit: "W", last_changed: "2026-06-24T19:00:00Z" },
      ]];
      panel._render = () => {};
      panel.shadowRoot = {
        querySelector() { return null; },
        querySelectorAll() { return []; },
      };
      panel._loadNilmWorkspaceHistoryForWindow = async () => true;

      await panel._callNilmLabelIntervalAction(0, "adjust");

      assert.equal(panel._nilmIntervalEditorOpen, false);
      assert.equal(panel._nilmFocusedInterval.start, Date.parse(interval.start));
      assert.equal(panel._nilmFocusedInterval.end, Date.parse(interval.end));
      panel._visibleNilmWorkspaceSeries = () => [{
        entity_id: "sensor.mains_power",
        name: "Mains power",
        unit: "W",
        points: [
          { time: Date.parse(interval.start), value: 100 },
          { time: Date.parse(interval.end), value: 900 },
        ],
      }];
      const selected = panel._renderNilmWorkspaceBody();
      assert.ok(selected.includes("data-nilm-edit-focused-interval"));
      assert.ok(selected.includes("Edit appliance interval"));
      assert.ok(!selected.includes("data-nilm-open-interval-editor"));

      assert.equal(panel._editNilmFocusedInterval(), true);
      assert.equal(panel._nilmIntervalEditorOpen, true);

      const emptyGraph = makePanel({ _nilmWorkspace: makeWorkspace() })
        ._renderNilmWorkspaceBody();
      assert.ok(emptyGraph.includes("data-nilm-open-interval-editor"));
      assert.ok(emptyGraph.includes("Label appliance interval"));
      assert.ok(!emptyGraph.includes("data-nilm-edit-focused-interval"));
    }

    name = "test_nilm_secondary_collections_are_always_visible";
    {
      const panel = makePanel();
      const html = panel._renderNilmSecondaryCollections(makeWorkspace({ sessions: [
        { session_id: "assigned", assignment_id: "assignment-1",
          start: "OWNED_SESSION", actions: { assign: {} } },
        { session_id: "unassigned", start: "RAW_SESSION",
          actions: { assign: {} } },
      ] }));
      assert.equal((html.match(/<details/g) || []).length, 0);
      for (const expected of [
        "Sessions, validation, and technical details",
        "Estimated Appliances",
        "NILM Sessions",
        "NILM Edges",
        "Validation",
      ]) {
        assert.ok(html.includes(expected));
      }
      assert.ok(!html.includes("Manual Labels"));
      assert.ok(!html.includes("data-nilm-decision"));
      assert.ok(html.includes("OWNED_SESSION"));
      assert.ok(html.includes("RAW_SESSION"));
      assert.ok(html.includes('data-nilm-session-index="1" data-nilm-session-action="assign"'));
      assert.ok(!html.includes('data-nilm-session-index="0" data-nilm-session-action="assign"'));
    }

    name = "test_nilm_full_workspace_has_one_owner";
    {
      const assignment = {
        assignment_id: "assignment-1",
        display_name: "Dishwasher",
        appliance_profile: "dishwasher",
        confidence_kind: "feedback_evidence",
        feedback_evidence_score: 0.8,
        appliance_detail_path: "/detail/dishwasher",
        actions: {
          rename: {},
          change_profile: { profile_options: [{ value: "dishwasher", label: "Dishwasher" }] },
          merge: { target_options: [{ value: "assignment-2", label: "Washer" }] },
          validate_history: {},
          publish: {},
          unpublish: {},
          retire: {},
        },
      };
      const sessions = Array.from({ length: 6 }, (_, index) => ({
        session_id: `session-${index + 1}`,
        assignment_id: "assignment-1",
        start: "2026-06-24T18:12:00Z",
        end: "2026-06-24T19:03:00Z",
        actions: { assign: {}, validate: {}, reject: {} },
      }));
      const workspace = makeWorkspace({
        assignments: [assignment],
        sessions,
      });
      workspace.lanes.assigned.assignment_ids = ["assignment-1"];
      const panel = makePanel({ _nilmActiveLane: "assigned", _nilmWorkspace: workspace });
      const html = panel._renderNilmWorkspaceBody();
      for (const marker of [
        'id="nilm_assignment_label_0"',
        'id="nilm_assignment_profile_0"',
        'id="nilm_assignment_merge_target_0"',
      ]) {
        assert.equal(html.split(marker).length - 1, 1);
      }
      for (const action of ["save", "merge", "validate_history", "publish", "unpublish", "retire"]) {
        const marker = `data-nilm-assignment-index="0" data-nilm-assignment-action="${action}"`;
        assert.equal(html.split(marker).length - 1, 1);
      }
      for (let index = 0; index < sessions.length; index += 1) {
        const input = `id="nilm_session_label_${index}"`;
        assert.equal(html.split(input).length - 1, 0);
        for (const action of ["validate", "reject"]) {
          const marker = `data-nilm-session-index="${index}" data-nilm-session-action="${action}"`;
          assert.equal(html.split(marker).length - 1, 1);
        }
        const assign = `data-nilm-session-index="${index}" data-nilm-session-action="assign"`;
        assert.equal(html.split(assign).length - 1, 0);
      }
      const secondary = panel._renderNilmSecondaryCollections(workspace);
      for (const duplicate of [
        'id="nilm_assignment_label_0"',
        'id="nilm_assignment_profile_0"',
        'id="nilm_assignment_merge_target_0"',
        "data-nilm-assignment-action",
        "data-nilm-appliance-detail-path",
        "Appliance Assignments",
        "Feedback evidence score: 80%",
      ]) {
        assert.ok(!secondary.includes(duplicate));
      }
      assert.ok(html.includes("Dishwasher"));
      assert.ok(html.includes("Feedback evidence score: 80%"));
    }

    const validationSession = {
      session_id: "session-dishwasher",
      start: "2026-06-24T18:12:00Z",
      end: "2026-06-24T19:03:00Z",
      display_label: "Dishwasher",
      assignment_id: "assignment-dishwasher",
      signature_fingerprint: "dishwasher-fingerprint",
      pairing_confidence: 0.82,
      median_power_w: 720,
      estimated_energy_kwh: 0.61,
      actions: { validate: {}, reject: {} },
    };
    name = "test_nilm_workspace_renders_session_validation_cards";
    {
      const panel = makePanel({ _nilmWorkspace: makeWorkspace({
        signatures: [{ signature_id: "sig-dishwasher",
          feedback_fingerprint: "dishwasher-fingerprint", actions: { ignore: {} } }],
        sessions: [validationSession],
      }) });
      const html = panel._renderNilmWorkspaceBody();
      for (const expected of [
        "Session Validation", "Predicted Dishwasher", "2026-06-24", "51m",
        "Estimated by NILM", "Pairing confidence: 82%", "Correct", "Wrong appliance",
        "Adjust Interval", 'data-nilm-session-action="validate"',
        'data-nilm-session-action="reject"', 'data-nilm-session-interval-index="0"',
      ]) assert.ok(html.includes(expected), expected);
      for (const duplicate of ["Ignore Similar", 'data-nilm-action="ignore"']) {
        assert.ok(!html.includes(duplicate), duplicate);
      }
    }

    name = "test_nilm_workspace_hides_already_reviewed_session_validation_cards";
    {
      const workspace = makeWorkspace({
        assignments: [{ assignment_id: "assignment-dishwasher",
          confirmed_session_ids: ["session-confirmed"],
          rejected_session_ids: ["session-rejected"] }],
        sessions: [
          { ...validationSession, session_id: "session-confirmed", display_label: "Already Confirmed" },
          { ...validationSession, session_id: "session-rejected", display_label: "Already Rejected" },
          { ...validationSession, session_id: "session-pending", display_label: "Pending Dishwasher" },
        ],
      });
      const html = makePanel({ _nilmWorkspace: workspace })._renderNilmWorkspaceBody();
      for (const hidden of ["Already Confirmed", "Already Rejected"]) {
        assert.ok(!html.includes(hidden), hidden);
      }
      assert.ok(html.includes("Predicted Pending Dishwasher"));
    }

    name = "test_nilm_workspace_marks_low_confidence_estimated_sessions";
    {
      const panel = makePanel({
        _nilmFocusedSignature: "dishwasher-fingerprint",
        _nilmFocusedOccurrenceIndex: 0,
        _nilmWorkspace: makeWorkspace({
          history: { start: "2026-06-24T18:00:00Z", end: "2026-06-24T19:10:00Z" },
          sessions: [{ ...validationSession, pairing_confidence: 0.7 }],
        }),
      });
      panel._nilmWorkspaceHistorySeries = [[
        { entity_id: "sensor.mains_power", state: "200",
          effective_role: "real_power", source_unit: "W",
          last_changed: "2026-06-24T18:00:00Z" },
        { entity_id: "sensor.mains_power", state: "900",
          effective_role: "real_power", source_unit: "W",
          last_changed: "2026-06-24T19:10:00Z" },
      ]];
      const html = panel._renderNilmWorkspaceBody();
      for (const expected of [
        "Estimated by NILM", "Low pairing confidence", "Pairing confidence: 70%",
        'data-nilm-session-confidence="0.70"', 'data-nilm-low-confidence="true"',
      ]) assert.ok(html.includes(expected), expected);
    }

    name = "test_nilm_review_card_labels_interval_average_power";
    {
      const panel = makePanel();
      const averageHtml = panel._renderNilmReviewCard({
        kind: "assignment",
        item: { assignment_id: "assignment-hvac", display_name: "HVAC", typical_power_w: 400, typical_power_source: "interval_average" },
        index: 0,
      }, [], false);
      assert.ok(averageHtml.includes("Average power: 400 W"));

      const normalHtml = panel._renderNilmReviewCard({
        kind: "assignment",
        item: { assignment_id: "assignment-pump", display_name: "Pump", typical_power_w: 400 },
        index: 1,
      }, [], false);
      assert.ok(normalHtml.includes("400 W"));
      assert.ok(!normalHtml.includes("Average power"));
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_nilm_workspace_collection_formatting_and_publication_disclosures() -> None:
    _run_panel_node_script(
        r'''
const edge = {
  timestamp: "2026-08-12T12:00:00Z",
  direction: "on",
  delta_w: 123.4567,
  split_phase_type: "unknown",
  dominant_leg: "L1",
};
const sessions = [
  {
    session_id: "open-session",
    display_label: "Washer",
    start: "2026-08-12T12:00:00Z",
    end: null,
    pairing_confidence: 0.82,
    median_power_w: 123.456,
    estimated_energy_kwh: 0.9,
    actions: { assign: makeAction("assign_session_to_appliance") },
  },
  {
    session_id: "closed-session",
    display_label: "Dryer",
    start: "2026-08-12T13:00:00Z",
    end: "2026-08-12T13:30:00Z",
    pairing_confidence: 0.72,
    median_power_w: 321.987,
    estimated_energy_kwh: 0.16,
    actions: { assign: makeAction("assign_session_to_appliance") },
  },
];
const workspace = makeWorkspace({
  source: { source_kind: "mains" },
  sessions,
  edges: [edge],
  ambiguity_audit: {
    total_count: 1,
    fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace/collections?collection=ambiguous_sessions&circuit_id=mains",
    group_preview: [],
  },
  known_load_attributions: [{
    timestamp: "2026-08-12T12:00:00Z",
    aggregate_delta_w: 1,
    explained_delta_w: 1,
    residual_delta_w: 0,
    known_circuit_ids: [],
    known_load_labels: [],
    selection_method: "unattributed",
  }],
});
const panel = makePanel({ _nilmWorkspace: workspace });
const secondary = panel._renderNilmSecondaryCollections(workspace);
const openStart = secondary.indexOf("Predicted Washer");
const closedStart = secondary.indexOf("Predicted Dryer");
const openBlock = secondary.slice(openStart, closedStart);
assert.ok(openStart >= 0 && closedStart > openStart);
assert.match(secondary, /data-nilm-session-range><span>[^<]+<\/span><span>[^<]+<\/span>/);
assert.ok(openBlock.includes("Pairing confidence"));
assert.ok(openBlock.includes("123.456 W"));
assert.ok(!openBlock.includes("kWh"));
assert.ok(secondary.includes("Pairing confidence: 72%"));
assert.match(secondary, /<strong>On: 123\.46 W<\/strong>\s*<span>/);
assert.ok(secondary.includes("Dominant leg: L1"));
assert.ok(!secondary.includes("unknown"));
const singlePhase = panel._renderNilmSecondaryCollections({
  ...workspace,
  source: { source_kind: "single_phase" },
});
assert.ok(!singlePhase.includes("Dominant leg"));

const assignment = {
  assignment_id: "dryer",
  display_name: "Dryer",
  median_power_error: 1.234,
  energy_estimate_error: 0.16,
  helper_options: [{ helper_circuit_id: "washer", helper_name: "Washer" }],
  helper_links: [],
  publication: { available: false, reason: "internal detail" },
  publication_readiness: {
    status: "needs_review",
    reasons: ["internal reason"],
    gates: { validated_sessions: "pending" },
  },
};
const inspector = panel._renderNilmReviewInspector({ kind: "assignment", index: 0, item: assignment });
assert.ok(inspector.indexOf("Median power error") < inspector.indexOf("Energy error"));
assert.match(inspector, /Median power error[\s\S]*<\/p>\s*<p[^>]*>Energy error/);
assert.ok(inspector.includes("Publication readiness"));
assert.ok(inspector.includes("<details open>"));
assert.ok(inspector.includes("Publication readiness gates"));
assert.ok(!inspector.includes("Reason:"));
assert.ok(!inspector.includes("internal detail"));
assert.ok(inspector.includes("A helper circuit is a separately metered load"));
assert.ok(inspector.includes("Choose a helper circuit"));
assert.ok(!inspector.includes("Choose another helper circuit"));
assert.ok(secondary.includes("Uncertain events"));
assert.ok(secondary.includes("Review uncertain events"));
assert.ok(secondary.includes('class="nilm-evidence-summary"'));
assert.ok(secondary.includes("Evidence quality and attribution"));
assert.ok(secondary.indexOf("data-nilm-ambiguity-audit") > secondary.indexOf("data-nilm-secondary-collections"));
assert.ok(secondary.indexOf("data-nilm-evidence-section") > secondary.indexOf("data-nilm-secondary-collections"));
''',
    )


def test_nilm_helper_prompt_distinguishes_unassigned_and_assigned_helpers() -> None:
    _run_panel_node_script(
        r'''
const workspace = makeWorkspace();
const panel = makePanel({ _nilmWorkspace: workspace });
const helperOptions = [{ helper_circuit_id: "washer", helper_name: "Washer" }];
const unassigned = panel._renderNilmHelperEvidence({
  assignment_id: "dryer-unassigned",
  helper_options: helperOptions,
  helper_links: [],
  helper_candidates: [],
}, 0);
const assigned = panel._renderNilmHelperEvidence({
  assignment_id: "dryer-assigned",
  helper_options: helperOptions,
  helper_links: [{ helper_circuit_id: "washer", helper_name: "Washer" }],
  helper_candidates: [],
}, 1);

assert.ok(unassigned.includes("Choose a helper circuit"));
assert.ok(!unassigned.includes("Choose another helper circuit"));
assert.ok(assigned.includes("Choose another helper circuit"));
''',
    )


def test_open_nilm_session_matches_validation_confidence_format() -> None:
    _run_panel_node_script(
        r'''
const workspace = makeWorkspace({
  sessions: [{
    session_id: "open-session",
    display_label: "Washer",
    start: "2026-08-12T12:00:00Z",
    end: null,
    pairing_confidence: 0.4,
    median_power_w: 123.45,
    estimated_energy_kwh: 0.9,
  }],
});
const panel = makePanel({ _nilmWorkspace: workspace });
const html = panel._renderNilmSecondaryCollections(workspace);
const sessionsStart = html.indexOf("NILM Sessions");
const edgesStart = html.indexOf("NILM Edges", sessionsStart);
const sessions = html.slice(sessionsStart, edgesStart);

assert.ok(sessions.includes("In progress. Pairing confidence 40%"));
assert.ok(!sessions.includes("Low pairing confidence"));
''',
    )


def test_nilm_evidence_quality_pagination_and_deep_links_are_bounded() -> None:
    _run_panel_node_script(
        r'''
(async () => {
  const quality = [{
    window: "today",
    status: "complete",
    runtime_minutes: 0,
    energy_kwh: 0,
    included_session_count: 0,
    excluded_session_count: 0,
    energy_source: "measured",
    power_coverage: 0,
    requested_start: "2026-08-12T00:00:00Z",
    requested_end: "2026-08-12T12:00:00Z",
    coverage_start: "2026-08-12T04:00:00Z",
    coverage_end: "2026-08-12T12:00:00Z",
    coverage_days: 0.333,
    longest_trace_gap_seconds: 0,
    retention_truncated: false,
  }];
  const attribution = {
    attribution_id: "attribution-1",
    timestamp: "2026-08-12T12:00:00Z",
    aggregate_delta_w: 1204,
    explained_delta_w: 1006,
    residual_delta_w: 198,
    known_circuit_ids: ["dryer"],
    known_load_labels: ["Clothes dryer"],
    selection_method: "global_assignment",
    compound: false,
    time_offsets_s: [1.8],
    topology_statuses: ["consistent"],
    rejected_candidate_summaries: [{
      known_circuit_id: "pool_pump",
      topology_status: "rejected",
      selection_status: "rejected",
    }],
  };
  const workspace = makeWorkspace({
    circuit: { circuit_id: "mains" },
    signatures: [{ signature_id: "signature-1", display_label: "Dryer", estimate_quality: quality }],
    known_load_attributions: [attribution],
    sessions: [{
      session_id: "new-session",
      start: "2026-08-12T12:00:00Z",
      end: "2026-08-12T12:05:00Z",
    }],
    collection_meta: {
      sessions: { total_count: 2, returned_count: 1, truncated: true, next_cursor: "cursor-1" },
    },
  });
  const panel = makePanel({ _nilmWorkspace: workspace });
  const evidence = panel._renderNilmEvidenceDetails(workspace);
  assert.ok(evidence.includes('data-nilm-evidence-details'));
  assert.ok(evidence.includes("Today"));
  assert.ok(evidence.includes("Complete"));
  assert.ok(evidence.includes("0 kWh"));
  assert.ok(evidence.includes("0%"));
  assert.ok(evidence.includes("Aggregate change"));
  assert.ok(evidence.includes("+1,204 W"));
  assert.ok(evidence.includes("Clothes dryer"));
  assert.ok(evidence.includes("Residual retained"));
  assert.ok(evidence.includes("Rejected candidate"));
  assert.ok(evidence.includes("Global assignment"));
  assert.ok(evidence.includes("Consistent"));
  assert.ok(evidence.includes("Topology rejected"));
  assert.ok(evidence.includes("Requested range"));
  assert.ok(evidence.includes("Actual retained coverage range"));
  const intervalEvidence = panel._renderNilmIntervalEvidence({
    average_power_w: 0,
    source_coverage: 0.92,
    power_coverage: 0,
    start_transition_eligible: true,
    stop_transition_eligible: false,
    interior_transition_count: 2,
    quality_flags: ["start_uncertain"],
  });
  assert.ok(intervalEvidence.includes("Average power: 0 W"));
  assert.ok(intervalEvidence.includes("Source coverage: 92%"));
  assert.ok(intervalEvidence.includes("Power coverage: 0%"));
  assert.ok(intervalEvidence.includes("Start transition uncertain"));
  assert.ok(intervalEvidence.includes("Boundary quality: Stop transition uncertain"));
  assert.ok(intervalEvidence.includes("Interior transitions: 2"));

  context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
  panel._evidenceRequestId = 3;
  panel._loadedRouteKey = "/panel?nilm_workspace=1&circuit_id=mains";
  panel._render = () => {};
  const calls = [];
  panel._requestJson = async (apiPath, fetchPath) => {
    calls.push({ apiPath, fetchPath });
    return {
      status: "ok",
      items: [{
        session_id: "older-session",
        start: "2026-08-12T10:00:00Z",
        end: "2026-08-12T10:05:00Z",
      }],
      total_count: 2,
      returned_count: 1,
      truncated: false,
      next_cursor: null,
    };
  };
  await panel._loadMoreNilmSessions();
  assert.equal(
    panel._nilmWorkspace.sessions.map((item) => item.session_id).join(","),
    "new-session,older-session",
  );
  assert.ok(calls[0].fetchPath.includes("collection=sessions"));
  assert.ok(calls[0].fetchPath.includes("cursor=cursor-1"));

  const deepLinkWorkspace = makeWorkspace({
    circuit: { circuit_id: "mains" },
    sessions: workspace.sessions.slice(0, 1),
  });
  context.window.location.search = "?nilm_workspace=1&circuit_id=mains&session_id=older-session";
  const deepLinkPanel = makePanel({
    _nilmWorkspace: deepLinkWorkspace,
    _evidenceRequestId: 4,
    _loadedRouteKey: "/panel?nilm_workspace=1&circuit_id=mains&session_id=older-session",
  });
  deepLinkPanel._render = () => {};
  let focused = null;
  deepLinkPanel._focusNilmReviewItem = async (item) => {
    focused = item;
    return true;
  };
  deepLinkPanel._requestJson = async (apiPath, fetchPath) => {
    calls.push({ apiPath, fetchPath });
    return {
      status: "ok",
      kind: "session",
      item: {
        session_id: "older-session",
        start: "2026-08-12T10:00:00Z",
        end: "2026-08-12T10:05:00Z",
      },
      focus: { start: "2026-08-12T10:00:00Z", end: "2026-08-12T10:05:00Z" },
      safe_actions: [],
    };
  };
  assert.equal(await deepLinkPanel._focusNilmRouteTarget(
    deepLinkWorkspace,
    deepLinkPanel._loadedRouteKey,
  ), true);
  assert.equal(focused.item.session_id, "older-session");
  assert.equal(deepLinkWorkspace.sessions.length, 1);
  assert.ok(calls.at(-1).fetchPath.includes("nilm_workspace/item"));

  context.window.location.search = "?nilm_workspace=1&circuit_id=mains&ambiguous_session_id=ambiguous-1";
  const ambiguousPanel = makePanel({
    _nilmWorkspace: makeWorkspace({
      circuit: { circuit_id: "mains" },
      ambiguity_audit: {
        total_count: 1,
        fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace/collections?collection=ambiguous_sessions&circuit_id=mains",
        group_preview: [],
      },
    }),
    _nilmActiveLane: "needs_review",
    _evidenceRequestId: 5,
    _loadedRouteKey: "/panel?nilm_workspace=1&circuit_id=mains&ambiguous_session_id=ambiguous-1",
  });
  ambiguousPanel._render = () => {};
  let ambiguityFocused = null;
  ambiguousPanel._focusNilmAmbiguityOccurrence = async (item) => {
    ambiguityFocused = item;
    return true;
  };
  ambiguousPanel._requestJson = async () => ({
    status: "ok",
    kind: "ambiguous_session",
    item: {
      session_id: "ambiguous-1",
      group_id: "ambiguous-group-1",
      start: "2026-08-12T09:00:00Z",
      end: "2026-08-12T09:05:00Z",
      safe_actions: ["open_on_graph", "create_manual_interval"],
    },
    focus: { start: "2026-08-12T09:00:00Z", end: "2026-08-12T09:05:00Z" },
    safe_actions: ["open_on_graph"],
  });
  assert.equal(await ambiguousPanel._focusNilmRouteTarget(
    ambiguousPanel._nilmWorkspace,
    ambiguousPanel._loadedRouteKey,
  ), true);
  assert.equal(ambiguityFocused.session_id, "ambiguous-1");
  assert.equal(ambiguousPanel._nilmActiveLane, "needs_review");
  assert.equal(ambiguousPanel._nilmWorkspace.sessions.length, 0);
  const auditHtml = ambiguousPanel._renderNilmAmbiguityAudit(ambiguousPanel._nilmWorkspace);
  assert.ok(auditHtml.includes('data-nilm-ambiguity-occurrence="ambiguous-1"'));
  assert.ok(auditHtml.includes("data-nilm-ambiguity-open-graph"));
  assert.ok(!auditHtml.includes("data-nilm-ambiguity-create-interval"));
})();
'''
    )


def test_nilm_lane_count_badge_respects_radius_limit() -> None:
    asset = _frontend_source()
    start = asset.index(".nilm-lane strong {")
    end = asset.index("\n        }", start)
    rule = asset[start:end]

    assert "border-radius: 8px" in rule
    assert "999px" not in rule


def test_nilm_decision_render_contracts() -> None:
    _run_panel_node_script(
        """
(() => {
  let name = "";
  try {
    name = "test_nilm_signature_review_hides_unavailable_decisions";
    {
      const panel = makePanel();
      const signature = {
        signature_id: "sig-ignore-only",
        actions: {
          ignore: makeAction("ignore_nilm_signature", {
            circuit_id: "mains",
            signature_id: "sig-ignore-only",
          }),
        },
      };
      panel._nilmWorkspace = makeWorkspace({ signatures: [signature] });
      const html = panel._renderNilmDecisionFlow(signature, "signature_0");
      for (const expected of [
        'name="nilm_decision_signature_0"',
        'value="ignore"',
        'data-nilm-apply-decision="signature_0"',
      ]) {
        assert.ok(html.includes(expected));
      }
      for (const unavailable of [
        'value="identify"',
        'value="mark_expected"',
        'value="merge"',
      ]) {
        assert.ok(!html.includes(unavailable));
      }
    }

    name = "test_nilm_decision_flow_renders_one_apply_without_direct_action_wall";
    {
      const panel = makePanel();
      const signature = {
        signature_id: "sig-1",
        actions: {
          label: {},
          assign: {
            assignment_options: [{ value: "assignment-washer", label: "Washer" }],
          },
          ignore: {},
          merge: {
            target_options: [{ value: "sig-2", label: "Load 2" }],
          },
        },
      };
      panel._nilmWorkspace = makeWorkspace({ signatures: [signature] });
      let html = panel._renderNilmDecisionFlow(signature, "signature_0");
      for (const expected of [
        'name="nilm_decision_signature_0"',
        'value="identify"',
        'value="ignore"',
        'value="merge"',
        'data-nilm-apply-decision="signature_0"',
      ]) {
        assert.ok(html.includes(expected));
      }
      assert.equal((html.match(/data-nilm-apply-decision/g) || []).length, 1);
      for (const action of ["label", "assign", "ignore", "merge"]) {
        assert.ok(!html.includes(`data-nilm-action="${action}"`));
      }
      const key = panel._nilmDecisionDraftKey(signature);
      panel._nilmLabelDrafts.set(panel._nilmLabelDraftKey(signature), "Washer");
      panel._nilmDecisionDrafts.set(key, {
        decision: "identify",
        identifyMode: "assign",
        assignmentId: "assignment-washer",
        mergeTarget: "sig-2",
      });
      html = panel._renderNilmDecisionFlow(signature, "signature_0");
      for (const expected of [
        'value="assign" selected',
        'value="label"',
        'value="assignment-washer" selected',
        'value="Washer"',
      ]) {
        assert.ok(html.includes(expected));
      }
      name = "test_nilm_workspace_does_not_duplicate_review_item_control_ids";
      assert.equal((html.match(/id="nilm_label_signature_0"/g) || []).length, 1);
      assert.ok(!html.includes('id="nilm_merge_targets_signature_0"'));
      panel._nilmDecisionDrafts.set(key, {
        ...panel._nilmDecisionDraft(signature),
        decision: "merge",
      });
      const mergeHtml = panel._renderNilmDecisionFlow(signature, "signature_0");
      assert.ok(mergeHtml.includes('data-selected="sig-2"'));
      assert.equal((mergeHtml.match(/id="nilm_merge_targets_signature_0"/g) || []).length, 1);
      assert.ok(!mergeHtml.includes('id="nilm_label_signature_0"'));
    }

    name = "test_nilm_identify_modes_rerender_only_their_relevant_fields";
    for (const mode of ["label", "assign"]) {
      const listeners = {};
      let rerenders = 0;
      const signature = {
        signature_id: "sig-1",
        actions: {
          label: makeAction("label_nilm_signature"),
          assign: Object.assign(makeAction("assign_nilm_signature"), {
            assignment_options: [{ value: "assignment-1", label: "Dishwasher" }],
          }),
        },
      };
      const panel = makePanel({
        _loading: false,
        _payload: { status: "not_found" },
        _nilmWorkspace: makeWorkspace({ signatures: [signature] }),
      });
      const key = panel._nilmDecisionDraftKey(signature);
      panel._nilmDecisionDrafts.set(key, {
        decision: "identify",
        identifyMode: mode === "label" ? "assign" : "label",
      });
      const select = {
        value: mode,
        dataset: { nilmDecisionKey: key },
        addEventListener(type, callback) { listeners[type] = callback; },
      };
      panel.shadowRoot = {
        innerHTML: "",
        querySelector() { return null; },
        querySelectorAll(selector) {
          return selector === "[data-nilm-identify-mode]" ? [select] : [];
        },
      };
      panel._render();
      assert.equal(typeof listeners.change, "function");
      panel._render = () => { rerenders += 1; };
      listeners.change();
      const html = panel._renderNilmDecisionFlow(signature, "signature_0");
      assert.ok(html.includes('<fieldset class="decision-group nilm-decision-group"'));
      assert.ok(html.includes("<legend>"));
      assert.ok(html.includes('id="nilm_label_signature_0"'));
      assert.equal(
        html.includes('data-nilm-existing-assignment="signature_0"'),
        mode === "assign",
      );
      assert.equal(rerenders, 1);
    }

    name = "test_nilm_assignment_actions_use_ha_device_workflow_labels";
    {
      const panel = makePanel();
      for (const [action, expected, stale] of [
        ["publish", "Create HA Device", "Publish Entities"],
        ["unpublish", "Remove HA Device", "Disable Publishing"],
      ]) {
        const html = panel._renderNilmAssignmentActions({ assignment_id: "assignment-washer",
          display_name: "Washer", actions: { [action]: {} } }, 0);
        assert.ok(html.includes(expected));
        assert.ok(!html.includes(stale));
      }
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
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


def test_chart_points_render_home_assistant_style_tooltip_markup() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg(
  [
    {
      name: "Kitchen Fridge",
      unit: "kWh",
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
for (const expected of [
  'data-chart-frame',
  'data-chart-point="1"',
  'data-chart-name="Kitchen Fridge"',
  'data-chart-value="123.46"',
  'data-chart-unit="W"',
  'data-chart-tooltip',
  'data-chart-crosshair',
  'stroke-width="2"',
  'class="legend-marker"',
  'icon="mdi:check-circle"',
]) {
  assert.ok(html.includes(expected), `missing ${expected}: ${html}`);
}
assert.ok(!html.includes("data-chart-readout"), "fixed chart readout must be removed");
assert.ok(!html.includes("<title>Kitchen Fridge"), "point tooltips must not be rendered");
assert.ok(!html.includes("data-chart-right-axis"), "default charts must keep a single axis");
"""
    )


def test_chart_supports_opt_in_dual_axes_with_series_units() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg(
  [
    { name: "kWh per Day", unit: "kWh", points: [{ time: Date.parse("2026-06-24T18:12:00Z"), value: 2.5 }] },
    { name: "Cost per Day", unit: "EUR", axis: "right", points: [{ time: Date.parse("2026-06-24T18:12:00Z"), value: 0.6 }] },
  ],
  { y_axis_label: "kWh", right_y_axis_label: "EUR" },
);
for (const expected of [
  'data-chart-right-axis="EUR"',
  'data-chart-unit="kWh"',
  'data-chart-unit="EUR"',
  'stroke-dasharray="6 4"',
  '>kWh<',
  '>EUR<',
]) {
  assert.ok(html.includes(expected), `missing ${expected}: ${html}`);
}
assert.match(html, /Values range from 2[.]5 kWh to 2[.]5 kWh.*Right axis ranges from 0[.]6 EUR to 0[.]6 EUR/);
"""
    )


def test_dual_axis_series_scale_to_their_own_min_and_max() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg(
  [
    { name: "Energy", unit: "kWh", points: [
      { time: Date.parse("2026-06-24T18:00:00Z"), value: 1.9 },
      { time: Date.parse("2026-06-24T19:00:00Z"), value: 2.3 },
    ] },
    { name: "Cost", unit: "USD", axis: "right", points: [
      { time: Date.parse("2026-06-24T18:00:00Z"), value: 0.34 },
      { time: Date.parse("2026-06-24T19:00:00Z"), value: 0.41 },
    ] },
  ],
  { y_axis_label: "kWh", right_y_axis_label: "USD" },
);
const pointY = (name, value) => Number(
  Array.from(html.matchAll(/<circle[^>]+>/g)).find((circle) => (
    circle[0].includes(`data-chart-name="${name}"`)
      && circle[0].includes(`data-chart-value="${value}"`)
  ))[0].match(/cy="([^"]+)"/)[1],
);
assert.equal(pointY("Energy", "2.3"), 18);
assert.equal(pointY("Energy", "1.9"), 278);
assert.equal(pointY("Cost", "0.41"), 18);
assert.equal(pointY("Cost", "0.34"), 278);
"""
    )


def test_bar_series_start_at_zero_on_both_axes() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const start = Date.parse("2026-06-24T18:00:00Z");
const end = Date.parse("2026-06-24T19:00:00Z");
const html = panel._chartSvg(
  [
    { name: "Energy", kind: "bar", unit: "kWh", points: [
      { time: start, value: 5 },
      { time: end, value: 10 },
    ] },
    { name: "Cost", kind: "bar", unit: "USD", axis: "right", points: [
      { time: start, value: 0.5 },
      { time: end, value: 1 },
    ] },
  ],
  { y_axis_label: "kWh", right_y_axis_label: "USD" },
);
const barHeight = (name, value) => Number(
  Array.from(html.matchAll(/<rect[^>]+data-energy-bar="1"[^>]+>/g)).find((bar) => (
    bar[0].includes(`data-chart-name="${name}"`)
      && bar[0].includes(`data-chart-value="${value}"`)
  ))[0].match(/height="([^"]+)"/)[1],
);
assert.equal(barHeight("Energy", "5"), 130);
assert.equal(barHeight("Energy", "10"), 260);
assert.equal(barHeight("Cost", "0.5"), 130);
assert.equal(barHeight("Cost", "1"), 260);
"""
    )


def test_dual_axis_preserves_tiny_positive_ranges() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const start = Date.parse("2026-06-24T18:00:00Z");
const end = Date.parse("2026-06-24T19:00:00Z");
const html = panel._chartSvg(
  [
    { name: "Energy", unit: "kWh", points: [{ time: start, value: 0 }, { time: end, value: 1e-17 }] },
    { name: "Cost", unit: "USD", axis: "right", points: [{ time: start, value: 0 }, { time: end, value: 1e-18 }] },
  ],
  { y_axis_label: "kWh", right_y_axis_label: "USD" },
);
const pointY = (name, time) => Number(
  Array.from(html.matchAll(/<circle[^>]+>/g)).find((circle) => (
    circle[0].includes(`data-chart-name="${name}"`)
      && circle[0].includes(`data-chart-time="${time}"`)
  ))[0].match(/cy="([^"]+)"/)[1],
);
assert.equal(pointY("Energy", end), 18);
assert.equal(pointY("Cost", end), 18);
"""
    )


def test_default_chart_keeps_legacy_minimum_range() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg([{ name: "Cost", points: [
  { time: Date.parse("2026-06-24T18:00:00Z"), value: 0.34 },
  { time: Date.parse("2026-06-24T19:00:00Z"), value: 0.41 },
] }], { y_axis_label: "USD" });
const maxPoint = Array.from(html.matchAll(/<circle[^>]+>/g)).find((circle) => circle[0].includes('data-chart-value="0.41"'))[0];
assert.equal(maxPoint.match(/cy="([^"]+)"/)[1], "259.8");
assert.ok(!html.includes("data-chart-right-axis"));
"""
    )


def test_chart_keeps_data_in_svg_without_visible_fallback() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const html = panel._chartSvg(
  [
    { name: "Kitchen Fridge", points: [
      { time: Date.parse("2026-06-24T18:10:00Z"), value: 123.456 },
      { time: Date.parse("2026-06-24T18:20:00Z"), value: 98.5 },
    ] },
    { name: "Basement Freezer", points: [
      { time: Date.parse("2026-06-24T18:30:00Z"), value: 45.25 },
    ] },
  ],
  {
    graph_window_start: "2026-06-24T18:00:00Z",
    graph_window_end: "2026-06-24T19:00:00Z",
    y_axis_label: "W",
    nilm_select_interval: true,
    nilm_sessions: [
      { session_id: "session-in", display_label: "Dishwasher", start: "2026-06-24T18:05:00Z", end: "2026-06-24T18:25:00Z", pairing_confidence: 0.82, selected: true },
      { session_id: "session-out", display_label: "Out of window", start: "2026-06-24T20:00:00Z", end: "2026-06-24T20:30:00Z", pairing_confidence: 0.9 },
    ],
    nilm_edges: [
      { timestamp: "2026-06-24T18:15:00Z", direction: "rising" },
      { timestamp: "2026-06-24T20:15:00Z", direction: "falling_outside" },
    ],
  },
);
const svg = html.match(/<svg[\s\S]*?<\/svg>/)[0];
assert.ok(!html.includes("chart-data-summary"), "chart data summary should not be visible");
assert.ok(!html.includes("chart-data-fallback"), "chart data disclosure should not be rendered");
assert.ok(!html.includes("<summary>View chart data</summary>"), "chart data summary label should not be visible");
assert.match(svg, /aria-label="Alert evidence chart with 2 series and 3 points\. Values range from 45\.25 W to 123\.46 W/);
for (const attribute of ['data-nilm-chart-select="1"', 'data-nilm-selected="true"', 'data-nilm-edge-direction="rising"']) {
  assert.ok(svg.includes(attribute), `SVG lost interactive attribute: ${attribute}`);
}
assert.ok(!svg.includes('data-nilm-edge-direction="falling_outside"'));
"""
    )


def test_nilm_graph_uses_appliance_names_without_raw_session_metadata() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._hass = { config: { time_zone: "UTC" } };
const rawSessionId = "hvac_2_direction_off_watts_0_100_var_0_100_va_0_100_pf_0_10";
assert.equal(
  panel._nilmSessionGraphLabel({ session_id: rawSessionId }),
  "Unknown load",
);
const html = panel._chartSvg(
  [{ name: "HVAC 2", points: [
    { time: Date.parse("2026-08-04T08:00:00Z"), value: 20 },
    { time: Date.parse("2026-08-04T09:00:00Z"), value: 102 },
  ] }],
  {
    graph_window_start: "2026-08-04T08:00:00Z",
    graph_window_end: "2026-08-04T09:00:00Z",
    y_axis_label: "W",
    nilm_sessions: [{
      session_id: rawSessionId,
      display_label: "Condensate Pump 2",
      start: "2026-08-04T08:10:00Z",
      end: "2026-08-04T08:30:00Z",
      selected: true,
    }],
  },
);
assert.ok(html.includes('data-nilm-session-label="Condensate Pump 2"'));
assert.ok(!html.includes(rawSessionId));
"""
    )


def test_dashboard_graphs_custom_card_asset_is_registered() -> None:
    asset = _frontend_source()

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
  circuit: { circuit_id: "mains", name: "Whole Home Main" },
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
if (!reviewOnly.shadowRoot.innerHTML.includes("Whole Home Main")
    || !reviewOnly.shadowRoot.innerHTML.includes("data-nilm-review-progress")
    || reviewOnly.shadowRoot.innerHTML.includes("Review lanes")) {
  throw new Error("dashboard graph card should show compact live NILM review progress");
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
    effective_role: "real_power",
    source_unit: "W",
    last_changed: "2026-06-29T12:00:00Z",
  },
  {
    entity_id: "sensor.mains_power",
    state: "180",
    effective_role: "real_power",
    source_unit: "W",
    last_changed: "2026-06-29T12:10:00Z",
  },
]];
card._nilmWorkspace = {
  status: "ok",
  circuit: { circuit_id: "mains", name: "Whole Home Main" },
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
      assignment_ids: ["assignment-2", "assignment-3", "assignment-4"]
    },
    assigned: {
      label: "Assigned",
      signature_ids: [],
      assignment_ids: ["assignment-1"]
    },
    published: {
      label: "Published",
      signature_ids: [],
      assignment_ids: ["assignment-5"]
    },
    expected: {
      label: "Expected",
      signature_ids: [],
      assignment_ids: []
    },
    hidden: {
      label: "Removed",
      signature_ids: ["sig-ignored"],
      assignment_ids: []
    }
  },
  lane_counts: {
    needs_review: 4,
    assigned: 1,
    published: 1,
    expected: 0,
    hidden: 1
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
    effective_role: "real_power",
    source_unit: "W",
    last_changed: "2026-06-29T12:00:00Z",
  },
  {
    entity_id: "sensor.mains_power",
    state: "180",
    effective_role: "real_power",
    source_unit: "W",
    last_changed: "2026-06-29T12:10:00Z",
  },
]];
card._render();
const html = card.shadowRoot.innerHTML;
const detailLinkIndex = html.indexOf('data-dashboard-alert-detail');
if (html.includes('chart-data-fallback') || html.includes('chart-data-summary')) {
  throw new Error("dashboard graph card should not render a chart data disclosure");
}
if (detailLinkIndex < 0) {
  throw new Error("dashboard graph card should keep the detail link");
}
for (const expected of [
  "Latest related notification",
  "Pool pump used more power than expected.",
  "data-dashboard-alert-detail",
  "View notification detail",
  "NILM mains power",
  "Whole Home Main",
  "Review progress",
  "3 of 7 reviewed",
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
    asset = _frontend_source()

    assert "_shouldHideUnavailableRecommendationAction(actionKey, action)" in asset
    assert 'if (!action) {\n      return "";' in asset
    assert (
        "action.enabled === false"
        " && this._shouldHideUnavailableRecommendationAction(actionKey, action)"
    ) in asset


def test_dynamic_alert_evidence_panel_separates_applied_recommendations() -> None:
    asset = _frontend_source()

    assert "_recommendationsByStatus(recommendations)" in asset
    assert "_renderRecommendationSection(" in asset
    assert (
        'this._panelText("recommendations.suggested_settings"), grouped.pending'
        in asset
    )
    assert (
        'this._panelText("recommendations.applied_suggested_settings"), '
        "grouped.applied" in asset
    )
    assert 'status === "applied"' in asset
    assert "originalIndex" in asset


def test_dynamic_alert_evidence_panel_uses_internal_component_renderers() -> None:
    asset = _frontend_source()

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
    asset = _frontend_source()

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
    asset = _frontend_source()
    formatter_start = asset.index("_formatDuration(value) {")
    formatter_end = asset.index("\n  _formatConfidence(value)", formatter_start)
    formatter = asset[formatter_start:formatter_end]

    null_guard = "value === null || value === undefined"
    coercion = "Number(value)"

    assert null_guard in formatter
    assert formatter.index(null_guard) < formatter.index(coercion)

    _run_panel_node_script(
        """
const panel = new context.Panel();
assert.equal(panel._formatDuration(0), "0s");
assert.equal(panel._formatDuration(61), "1m 1s");
assert.equal(panel._formatDuration(3661), "1h 1m 1s");
assert.equal(panel._formatDuration(null), "Unknown");
"""
    )


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
    asset = _frontend_source()
    setup_health_api_path = (
        "const SETUP_HEALTH_API_PATH = "
        '"/api/circuitsetup_energy_analyzer/setup_health";'
    )
    setup_health_call_api_path = (
        "const SETUP_HEALTH_CALL_API_PATH = "
        '"circuitsetup_energy_analyzer/setup_health";'
    )

    assert setup_health_api_path in asset
    assert setup_health_call_api_path in asset
    assert 'const SETUP_HEALTH_QUERY_PARAM = "setup_health";' in asset
    assert "_routeRequestsSetupHealth" in asset
    assert "_loadSetupHealth" in asset
    assert 'routeUrl.searchParams.get("entry_id")' in asset
    assert 'SETUP_HEALTH_CALL_API_PATH}${query ? `?${query}` : ""}' in asset
    assert "_renderSetupHealthBody" in asset


def test_appliance_insights_panel_route_and_api_contract() -> None:
    asset = _frontend_source()

    for expected in (
        "const APPLIANCE_INSIGHTS_API_PATH = "
        '"/api/circuitsetup_energy_analyzer/appliance_insights";',
        "const APPLIANCE_INSIGHTS_CALL_API_PATH = "
        '"circuitsetup_energy_analyzer/appliance_insights";',
        'const APPLIANCE_INSIGHTS_QUERY_PARAM = "appliance_insights";',
        'routeUrl.searchParams.get(APPLIANCE_INSIGHTS_QUERY_PARAM) === "1"',
        "_routeRequestsApplianceInsights",
        "_loadApplianceInsights",
        "_renderApplianceInsightsBody",
    ):
        assert expected in asset


def test_appliance_insights_panel_exposes_filter_and_sort_controls() -> None:
    asset = _frontend_source()

    for expected in (
        "data-appliance-insights-filter",
        'this._panelText("appliance_insights.filters.running")',
        'this._panelText("appliance_insights.filters.needs_attention")',
        'this._panelText("appliance_insights.filters.nilm_estimated")',
        'this._panelText("appliance_insights.filters.learning")',
        'this._panelText("appliance_insights.filters.data_problem")',
        "data-appliance-insights-sort",
        'this._panelText("appliance_insights.sorts.highest_energy")',
        'this._panelText("appliance_insights.sorts.largest_change")',
    ):
        assert expected in asset


def test_appliance_insights_panel_has_stable_source_and_detail_deep_link_hooks() -> (
    None
):
    asset = _frontend_source()

    for expected in (
        "data-appliance-insights-detail-path",
        "data-appliance-insights-source-path",
        'querySelectorAll("[data-appliance-insights-detail-path]")',
        'querySelectorAll("[data-appliance-insights-source-path]")',
    ):
        assert expected in asset


def test_setup_health_panel_renders_next_step_only_in_checklist() -> None:
    body = """
const panel = new context.Panel();
const integrationPath = "/config/integrations/integration/circuitsetup_energy_analyzer";
const integrationHref = 'href="' + integrationPath + '"';
panel._setupHealthLoading = false;
panel._setupHealthError = "";
panel._setupHealth = {
  status: "ok",
  text: __SETUP_HEALTH_TEXT__,
  state: "Configure breaker amps",
  next_step: "Configure breaker amps for HVAC",
  message: "Configure breaker amps for HVAC",
  open_path: integrationPath,
  issue_count: 1,
  checklist_ready_count: 2,
  checklist_total_count: 4,
  checklist: [
    { item_id: "source_data_found", status: "needs_attention" },
    {
      item_id: "notifications_enabled",
      status: "ok",
    },
    { item_id: "nilm_enabled", status: "optional" },
    {
      item_id: "learning_progress",
      status: "learning",
      title: "Learning progress",
      why_it_matters: "Learning is still in progress.",
      fix: "Keep collecting data",
    },
  ],
  issues: [
    {
      issue: "missing_capacity_setting",
      severity: "warning",
      fix: "Configure breaker amps for HVAC",
      reason: "Capacity tracking needs the circuit breaker size.",
      affected_circuit_name: "HVAC",
      open_path: integrationPath,
    },
  ],
};
const rendered = panel._renderSetupHealthContent();
const waitingSource = panel._renderSetupHealthChecklistItem({
  item_id: "source_data_found",
  status: "learning",
});
if (!waitingSource.includes("Waiting to verify source data")) {
  throw new Error(`missing waiting source title: ${waitingSource}`);
}
for (const unexpected of [
  ">Status<",
  ">Next Step<",
  ">Checklist<",
  ">Issues<",
  "What To Check First",
  "This affects appliance analysis quality.",
  "source_data_found",
  ">Learning<",
  "Circuit: HVAC",
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
  'icon="mdi:check-circle"',
  'icon="mdi:alert-circle"',
  'icon="mdi:minus-circle-outline"',
  'icon="mdi:progress-clock"',
  'aria-label="Complete"',
  'aria-label="Needs attention"',
  'aria-label="Optional"',
  'aria-label="Learning"',
]) {
  if (!rendered.includes(expected)) {
    throw new Error(`missing checklist status icon: ${expected}`);
  }
}
if (rendered.includes("<span>Needs attention</span>")) {
  throw new Error(`raw checklist status remains: ${rendered}`);
}
for (const expected of [
  "Source data needs attention",
  "Confirms Home Assistant is receiving live readings for each circuit.",
  "Notifications enabled",
  "NILM enabled",
  "Capacity tracking needs the circuit breaker size.",
  "Open integration options",
  integrationHref,
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

    assert (
        "{circuit_name}"
        in translations["issues"]["unexpected_negative_real_power"]["description"]
    )

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            INTEGRATION_DIR / "entities" / "setup_health.py",
            *FRONTEND_ASSETS,
            INTEGRATION_DIR / "panel.py",
        )
    )
    translated_text = json.dumps(setup_health)
    for text in (
        "Confirms Home Assistant is receiving live readings for each circuit.",
        "Names, profiles, and sensor roles identify each circuit.",
        "Checks that power flow matches the selected circuit role.",
        (
            "Energy totals use a configured kWh source or are derived "
            "automatically from power."
        ),
        "Profiles choose the right runtime, standby, demand, and context checks.",
        "Controls which helper sensors and dashboard diagnostics HA creates.",
        "Provides setup health, appliance status, and evidence links in one view.",
        "Keeps alert notifications linked to the evidence that caused them.",
        "Optional mains NILM can discover unknown loads from aggregate sensors.",
        "Recent history is needed before comparisons and alerts become reliable.",
        "Open integration options",
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
            *FRONTEND_ASSETS,
            INTEGRATION_DIR / "panel.py",
        )
    )
    translated_text = json.dumps(panel_text)

    for text in (
        "Appliance Detail",
        "Load Separation",
        "Review Evidence",
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
        "NILM Signatures",
        "Estimated Appliances",
        "Label appliance interval",
        "Session Validation",
        "Prediction Preview",
        "Power: measured {measured}, estimated {estimated}, error {error}",
        "Energy: measured {measured}, estimated {estimated}, error {error}",
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


def test_backend_ux_notification_and_advisor_text_live_in_translations() -> None:
    translations = _translations()["config_panel"]
    translated_text = json.dumps(
        {
            "ux": translations["ux"],
            "notifications": translations["notifications"],
            "settings_advisor": translations["settings_advisor"],
        }
    )
    source_text = "\n".join(
        (INTEGRATION_DIR / filename).read_text(encoding="utf-8")
        for filename in ("ux.py", "notifications.py", "settings_advisor.py")
    )

    for text in (
        "Quiet",
        "Demand and capacity evidence can show unusual operating load, but it is not an electrical safety verification.",
        "Needs data",
        "Reactive-to-real power ratio",
        "This is a repeated change from the learned electrical pattern, not an electrical safety diagnosis.",
        "Weekly Appliance Digest",
        "Daily Appliance Summary",
        "Standby Power Threshold",
        "Energy Usage",
        "Observed sustained EV charger current samples; lower the warning ratio without inferring breaker size.",
        "High solar surplus should represent the upper end of observed export events.",
    ):
        assert text in translated_text
        assert text not in source_text


def test_dynamic_alert_evidence_panel_previews_recommendation_evidence() -> None:
    asset = _frontend_source()

    assert "_renderSelectedRecommendationEvidence()" in asset
    assert "selected_recommendation" in asset
    assert 'this._panelText("recommendations.recommendation_evidence")' in asset
    assert 'this._panelTextFormat("recommendations.previewing_evidence"' in asset


def test_recommendation_evidence_is_an_exclusive_actionable_view() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._loading = false;
panel._error = "";
panel._listen = () => {};
panel.shadowRoot.querySelector = () => null;
panel._payload = {
  status: "ok",
  alert: {
    circuit_id: "washer",
    message: "ALERT ISSUE SENTINEL",
    feature: "daily_energy",
    graph_entities: ["sensor.washer_power"],
    graph_window_start: "2026-07-11T10:00:00Z",
    graph_window_end: "2026-07-11T12:00:00Z",
    y_axis_label: "W",
  },
  circuit: { name: "Washer" },
  selected_recommendation: {
    recommendation_id: "washer:daily:v1",
    display_label: "Daily threshold",
    current_value: 10,
    default_value: 12,
    suggested_value: 14,
    unit: "W",
    expected_effect: "Reduce nuisance alerts.",
    evidence_preview: "Observed Days: 8; Daily P95: 13.8",
    actions: {
      apply: { enabled: true },
      dismiss: { enabled: true },
      reset: { enabled: true },
    },
  },
  setting_recommendations: [{ recommendation_id: "washer:daily:v1" }],
};
panel._historySeries = [[
  { entity_id: "sensor.washer_power", state: "10", last_changed: "2026-07-11T10:00:00Z" },
  { entity_id: "sensor.washer_power", state: "14", last_changed: "2026-07-11T12:00:00Z" },
]];
panel._render();
const html = panel.shadowRoot.innerHTML;
for (const expected of [
  "Review Evidence",
  "Reviewing evidence for Daily threshold.",
  'data-recommendation-action="apply"',
  'data-recommendation-action="dismiss"',
  'data-recommendation-action="reset"',
  "Reduce nuisance alerts.",
  "Observed Days",
  "Daily P95",
  'class="chart"',
  ">10 W<",
  ">12 W<",
  ">14 W<",
]) {
  assert.ok(html.includes(expected), `missing ${expected}`);
}
assert.ok(
  html.indexOf('class="recommendation-values"') < html.indexOf('class="chart"')
    && html.indexOf('class="chart"') < html.indexOf('data-recommendation-action="apply"'),
  "recommendation data and graph must precede actions",
);
assert.equal((html.match(/Review Evidence/g) || []).length, 1);
assert.equal((html.match(/Reviewing evidence for/g) || []).length, 1);
for (const unexpected of ["Recommendation Evidence", "Previewing evidence", "ALERT ISSUE SENTINEL", "Respond to this alert", "What To Check First"]) {
  assert.ok(!html.includes(unexpected), `unexpected alert content: ${unexpected}`);
}
"""
    )


def test_suggested_setting_uses_two_columns_and_inline_historical_impact() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
const html = panel._renderRecommendationSectionContent("Suggested Settings", [{
  originalIndex: 0,
  recommendation: {
    display_label: "Daily threshold",
    current_value: 10,
    default_value: 12,
    suggested_value: 14,
    unit: "W",
    expected_effect: "Reduce low-value alerts.",
    evidence_preview: "Observed Days: 8; Daily P95: 13.8",
    impact_preview: {
      available: true,
      observations_evaluated: 23,
      history_start: "2026-07-01T12:00:00Z",
      history_end: "2026-07-13T12:00:00Z",
      current_alert_count: 4,
      candidate_alert_count: 2,
      current_state_change_count: null,
      candidate_state_change_count: null,
      examples_removed: [],
      examples_added: [],
      limitations: [],
    },
    actions: {},
  },
}]);
for (const expected of [
  'class="recommendation-layout"',
  'class="recommendation-values"',
  'class="recommendation-evidence-line"',
  "Observed Days: 8",
  "Daily P95: 13.8",
  "Historical impact:",
  ">10 W<",
  ">12 W<",
  ">14 W<",
]) {
  assert.ok(html.includes(expected), `missing ${expected}`);
}
assert.ok(!html.includes("<details"), "historical impact must not be a disclosure");
assert.equal((html.match(/recommendation-value/g) || []).length, 4);
"""
    )


def test_panel_waits_for_authenticated_hass_before_loading() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel.isConnected = true;
let loads = 0;
panel._loadEvidence = () => { loads += 1; };
panel.connectedCallback();
assert.equal(loads, 0);
panel.hass = { callApi: async () => ({}) };
assert.equal(loads, 1);
"""
    )


def test_panel_recovers_hass_assigned_before_custom_element_upgrade() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel.isConnected = true;
const authenticatedHass = { callApi: async () => ({}) };
Object.defineProperty(panel, "hass", {
  configurable: true,
  enumerable: true,
  value: authenticatedHass,
  writable: true,
});
let loads = 0;
panel._loadEvidence = () => { loads += 1; };
panel.connectedCallback();
assert.equal(panel._hass, authenticatedHass);
assert.equal(loads, 1);
assert.equal(Object.prototype.hasOwnProperty.call(panel, "hass"), false);
"""
    )


def test_panel_options_actions_use_supported_integration_page() -> None:
    _run_panel_node_script(
        r"""
(async () => {
  const calls = [];
  const panel = new context.Panel();
  panel._hass = {
    callApi: async (method, path, data) => {
      calls.push({ method, path, data });
      return {};
    },
  };
  let destination = "";
  panel._navigate = (path) => { destination = path; };
  await panel._openOptionsFlow({
    entry_id: "entry-1",
    circuit_id: "fridge",
    options_step: "advanced_settings",
    path: "/config/integrations/integration/circuitsetup_energy_analyzer",
  });
  assert.equal(JSON.stringify(calls), "[]");
  assert.equal(destination, "/config/integrations/integration/circuitsetup_energy_analyzer");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_relearn_baseline_requires_confirmation() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._pendingConfirmationAction = "relearn_baseline";
const html = panel._renderActionConfirmation();
for (const expected of [
  "<ha-dialog",
  "Relearn Baseline",
  "restart learning",
  "<ha-dialog-footer>",
  '<ha-button slot="secondaryAction" id="cancel_action_confirmation" appearance="plain">',
  '<ha-button slot="primaryAction" id="confirm_action" variant="brand" appearance="filled">',
]) {
  if (!html.includes(expected)) {
    throw new Error(`missing ${expected}: ${html}`);
  }
}
"""
    )


def test_no_evidence_fallback_renders_mixed_circuit_action() -> None:
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
panel._loading = false;
panel._payload = {
  status: "circuit_found_no_evidence",
  actions: {
    mark_circuit_mixed: {
      domain: "circuitsetup_energy_analyzer",
      service: "mark_circuit_mixed",
      data: { circuit_id: "fridge" },
    },
  },
};
const html = panel._renderNotFound();
assert.match(html, /id="mark_circuit_mixed"/);
assert.match(html, />This circuit powers other loads</);
"""
    )


def test_mark_circuit_mixed_requires_confirmation_and_reports_result() -> None:
    _run_panel_node_script(
        r"""
(async () => {
  const calls = [];
  const panel = new context.Panel();
  panel._payload = { actions: { mark_circuit_mixed: {
    domain: "circuitsetup_energy_analyzer",
    service: "mark_circuit_mixed",
    data: { circuit_id: "fridge" },
  } } };
  panel._hass = { callService: async (...args) => { calls.push(args); } };
  panel._render = () => {};
  panel._scrollToTop = () => {};
  panel._loadEvidence = async () => {};
  panel._loadedRouteKey = panel._routeKey();

  const evidence = panel._renderActionDisclosure("tune", "Tune", "Tune it", [
    panel._actionButton("mark_circuit_mixed", panel._panelText("actions.labels.mark_circuit_mixed"), true),
  ]);
  assert.match(evidence, /This circuit powers other loads/);

  panel._requestActionConfirmation("mark_circuit_mixed");
  assert.equal(calls.length, 0);
  const confirmation = panel._renderActionConfirmation();
  for (const expected of ["keep aggregate history", "stop direct-appliance classifications and alerts", "reload the integration"]) {
    assert.ok(confirmation.includes(expected), confirmation);
  }
  assert.ok(!confirmation.includes("detected another load"), confirmation);
  panel._cancelActionConfirmation();
  assert.equal(calls.length, 0);

  panel._requestActionConfirmation("mark_circuit_mixed");
  await panel._confirmPendingAction();
  assert.deepEqual(calls, [["circuitsetup_energy_analyzer", "mark_circuit_mixed", { circuit_id: "fridge" }]]);
  assert.equal(panel._lastActionMessage, "Circuit marked as mixed.");

  panel._hass.callService = async () => { throw new Error("service failed"); };
  panel._renderAndScrollToTop = () => {};
  panel._requestActionConfirmation("mark_circuit_mixed");
  await panel._confirmPendingAction();
  assert.match(panel._error, /service failed/);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    )


def test_dynamic_alert_evidence_panel_orders_recommendation_actions() -> None:
    asset = _frontend_source()

    preview = asset.index(
        "this._recommendationActionButton(recommendation, originalIndex, "
        '"preview", this._panelText("actions.labels.preview_evidence"), true)'
    )
    apply = asset.index(
        "this._recommendationActionButton(recommendation, originalIndex, "
        '"apply", this._panelText("actions.labels.apply"))'
    )
    dismiss = asset.index(
        "this._recommendationActionButton(recommendation, originalIndex, "
        '"dismiss", this._panelText("actions.labels.dismiss"), true)'
    )
    undo = asset.index(
        "this._recommendationActionButton(recommendation, originalIndex, "
        '"undo", this._panelText("actions.labels.undo"), true)'
    )
    reset = asset.index(
        "this._recommendationActionButton(recommendation, originalIndex, "
        '"reset", this._panelText("actions.labels.reset_default"), true)'
    )

    assert preview < apply < dismiss < undo < reset


def test_dynamic_alert_evidence_panel_scrolls_after_messages() -> None:
    asset = _frontend_source()

    assert "_renderAndScrollToTop()" in asset
    assert "_scrollToTop()" in asset
    assert "requestAnimationFrame" in asset
    assert "window.scrollTo({ top: 0" in asset


def test_dynamic_alert_evidence_panel_preserves_nilm_label_drafts() -> None:
    asset = _frontend_source()

    assert "this._nilmLabelDrafts = new Map();" in asset
    assert (
        'input.addEventListener("input", () => this._rememberNilmLabelDraft(' in asset
    )
    assert "this._nilmLabelDraftKey(signature)" in asset
    assert "this._nilmLabelDrafts.get(draftKey)" in asset


def test_dynamic_alert_evidence_panel_reloads_when_notification_url_changes() -> None:
    asset = _frontend_source()

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
    asset = _frontend_source()

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


def test_nilm_decision_action_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_nilm_decision_identify_assigns_without_scrolling_to_top";
    {
      const calls = [];
      let scrolled = 0;
      const panel = makePanel();
      panel._render = () => {};
      panel._scrollToTop = () => { scrolled += 1; };
      panel._renderAndScrollToTop = () => { scrolled += 1; };
      panel._loadEvidence = async () => {};
      panel._hass = {
        callService: async (domain, service, data) => calls.push({ domain, service, data }),
      };
      panel.shadowRoot.querySelector = (selector) =>
        selector === "#nilm_label_signature_0" ? { value: "Dishwasher" } : null;
      const signature = {
        signature_id: "sig-1",
        actions: {
          assign: makeAction("assign_nilm_signature"),
        },
      };
      panel._nilmWorkspace = makeWorkspace({
        signatures: [signature],
      });
      panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-1"];
      const key = panel._nilmDecisionDraftKey(signature);
      panel._nilmDecisionDrafts.set(key, { decision: "identify", identifyMode: "assign" });
      await panel._applyNilmDecision("signature_0");
      assert.deepEqual(
        [calls.length, calls[0].service, calls[0].data.label, scrolled,
          panel._nilmDecisionDrafts.has(key)],
        [1, "assign_nilm_signature", "Dishwasher", 0, false],
      );
    }

    name = "test_nilm_decision_failure_keeps_draft_and_feedback_in_inspector";
    {
      let scrolled = 0;
      let focused = 0;
      const panel = makePanel();
      panel._render = () => {};
      panel._scrollToTop = () => { scrolled += 1; };
      panel._renderAndScrollToTop = () => { scrolled += 1; };
      panel._hass = { callService: async () => { throw new Error("service failed"); } };
      panel.shadowRoot.querySelector = (selector) => {
        if (selector === "#nilm_label_signature_0") return { value: "Dishwasher" };
        if (selector.startsWith("[data-inline-feedback=")) {
          return { focus() { focused += 1; } };
        }
        return null;
      };
      const signature = {
        signature_id: "sig-1",
        actions: {
          label: makeAction("label_nilm_signature"),
        },
      };
      panel._nilmWorkspace = makeWorkspace({ signatures: [signature] });
      const key = panel._nilmDecisionDraftKey(signature);
      const draft = { decision: "identify", identifyMode: "label" };
      panel._nilmDecisionDrafts.set(key, draft);
      await panel._applyNilmDecision("signature_0");
      assert.deepEqual(
        [panel._nilmDecisionDrafts.get(key), panel._inlineFeedback.scope,
          panel._inlineFeedback.kind, scrolled, focused],
        [draft, "signature_0", "error", 0, 1],
      );
    }

    name = "test_nilm_decision_success_advances_and_keeps_graph_context";
    {
      const panel = makePanel({
        _nilmActiveLane: "needs_review",
        _nilmSelectedReviewKey: "signature:sig-1",
        _nilmFocusedSignature: "fingerprint-1",
        _nilmGraphWindow: { start: 1000, end: 2000, min: 0, max: 3000 },
      });
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      panel._scrollToTop = () => { throw new Error("decision scrolled to top"); };
      panel._hass = { callService: async () => {} };
      const first = {
        signature_id: "sig-1",
        feedback_fingerprint: "fingerprint-1",
        actions: { ignore: makeAction("ignore_nilm_signature") },
      };
      const second = {
        signature_id: "sig-2",
        feedback_fingerprint: "fingerprint-2",
        actions: { ignore: {} },
      };
      panel._nilmWorkspace = makeWorkspace({
        signatures: [first, second],
      });
      panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-1", "sig-2"];
      const firstKey = panel._nilmDecisionDraftKey(first);
      const secondKey = panel._nilmDecisionDraftKey(second);
      panel._nilmDecisionDrafts.set(firstKey, { decision: "ignore", identifyMode: "assign" });
      panel._nilmDecisionDrafts.set(secondKey, { decision: "ignore", identifyMode: "assign" });
      panel._refreshNilmWorkspaceData = async () => {
        panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-2"];
        return true;
      };
      let focused = "";
      panel._focusNilmSignatureOnGraph = async (fingerprint, options) => {
        focused = fingerprint;
        assert.ok(!options.scroll);
        assert.ok(!options.toggle);
        panel._nilmFocusedSignature = fingerprint;
      };
      await panel._applyNilmDecision("signature_0");
      assert.deepEqual(
        [panel._nilmActiveLane, panel._nilmSelectedReviewKey, focused,
          panel._nilmDecisionDrafts.has(firstKey), panel._nilmDecisionDrafts.has(secondKey),
          panel._inlineFeedback.scope, panel._inlineFeedback.kind],
        ["needs_review", "signature:sig-2", "fingerprint-2", false, true,
          "nilm-review", "success"],
      );
    }

    name = "test_nilm_action_completion_cannot_mutate_a_replacement_route";
    {
      context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains-a";
      let finishService;
      let workspaceLoads = 0;
      let graphFocus = 0;
      const panel = makePanel({ _evidenceRequestId: 4 });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      panel._hass = {
        callService: () => new Promise((resolve) => { finishService = resolve; }),
      };
      const signature = {
        signature_id: "sig-a",
        feedback_fingerprint: "fingerprint-a",
        actions: {
          ignore: makeAction("ignore_nilm_signature"),
        },
      };
      panel._nilmWorkspace = makeWorkspace({
        signatures: [signature],
      });
      panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-a"];
      panel._nilmSelectedReviewKey = "signature:sig-a";
      panel._refreshNilmWorkspaceData = async () => { workspaceLoads += 1; return true; };
      panel._focusNilmSignatureOnGraph = async () => { graphFocus += 1; };
      const operation = panel._callNilmAction(signature, "signature_0", "ignore");
      await Promise.resolve();
      assert.ok(panel._busyAction);
      context.window.location.search = "?circuit_id=mains-b";
      panel._requestJson = async () => ({
        status: "circuit_found_no_evidence",
        circuit: { circuit_id: "mains-b", name: "Mains B" },
        actions: {},
      });
      await panel._loadEvidence({ routeKey: panel._routeKey() });
      finishService();
      await operation;
      assert.deepEqual(
        [workspaceLoads, graphFocus, panel._busyAction, panel._lastActionMessage,
          panel._inlineFeedback.message, panel._payload.circuit.circuit_id],
        [0, 0, "", "", "", "mains-b"],
      );
    }

    name = "test_nilm_label_success_is_announced_when_signature_remains_in_lane";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const panel = makePanel({ _evidenceRequestId: 2 });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel._hass = { callService: async () => {} };
      panel.shadowRoot.querySelector = (selector) =>
        selector === "#nilm_label_signature_0" ? { value: "Dishwasher" } : null;
      const signature = {
        signature_id: "sig-1",
        feedback_fingerprint: "fingerprint-1",
        actions: {
          label: makeAction("label_nilm_signature"),
        },
      };
      panel._nilmWorkspace = makeWorkspace({
        signatures: [signature],
      });
      panel._nilmWorkspace.lanes.needs_review.signature_ids = ["sig-1"];
      panel._refreshNilmWorkspaceData = async () => {
        signature.user_label = "Dishwasher";
        return true;
      };
      await panel._callNilmAction(signature, "signature_0", "label");
      const html = panel._renderNilmReviewLayout(panel._nilmWorkspace);
      for (const expected of [
        'data-inline-feedback="nilm-review"',
        'tabindex="-1"',
        'role="status"',
        "Saved label: Dishwasher.",
        'data-nilm-review-item="signature:sig-1"',
      ]) {
        assert.ok(html.includes(expected));
      }
    }

    name = "test_nilm_assignment_and_session_completions_ignore_replacement_routes";
    const itemCases = [
      { kind: "publish", collection: "assignments", action: "publish", lane: "published",
        message: "Created an estimated HA appliance device." },
      { kind: "save", lane: "assigned", message: "Saved assignment changes." },
      { kind: "session", collection: "sessions", action: "validate",
        lane: "needs_review", message: "Confirmed Dishwasher." },
      { kind: "session-reject", collection: "sessions", action: "reject",
        lane: "needs_review", message: "Marked Dishwasher for review." },
    ];
    for (const row of itemCases) {
      const { kind } = row;
      for (const outcome of ["resolve", "reject"]) {
        context.window.location.search = "?nilm_workspace=1&circuit_id=a";
        let settle;
        let assigns = 0;
        let refreshes = 0;
        let renders = 0;
        let scrolls = 0;
        let requests = 0;
        const panel = makePanel({
          _evidenceRequestId: 5,
          _payload: { circuit: { circuit_id: "a" }, actions: {} },
        });
        panel._loadedRouteKey = panel._routeKey();
        panel._render = () => { renders += 1; };
        panel._scrollToTop = () => { scrolls += 1; };
        context.window.location.assign = () => { assigns += 1; };
        const action = makeAction(`${kind}_service`);
        const assignment = { assignment_id: "assignment-1", display_name: "Dishwasher",
          appliance_profile: "washer",
          actions: kind === "save" ? { rename: action } : { publish: action } };
        const session = { session_id: "session-1", assignment_id: "assignment-1",
          actions: { [row.action]: action } };
        panel._nilmWorkspace = makeWorkspace({
          assignments: [assignment],
          sessions: [session],
        });
        panel._nilmWorkspace.lanes.assigned.assignment_ids = ["assignment-1"];
        panel.shadowRoot.querySelector = (selector) =>
          selector === "#nilm_assignment_label_0" ? { value: "Dishwasher Updated" } : null;
        panel._hass = {
          callService: () => new Promise((resolve, reject) => { settle = { resolve, reject }; }),
        };
        panel._refreshNilmWorkspaceData = async () => { refreshes += 1; return true; };
        const operation = kind === "save" ? panel._saveNilmAssignmentChanges(0) :
          panel._callNilmWorkspaceItemAction(row.collection, 0, row.action);
        await Promise.resolve();
        context.window.location.search = "?circuit_id=b";
        const payloadB = { status: "circuit_found_no_evidence",
          circuit: { circuit_id: "b" }, actions: {} };
        panel._requestJson = async () => { requests += 1; return payloadB; };
        await panel._loadEvidence({ routeKey: panel._routeKey() });
        const rendersAtB = renders;
        if (outcome === "resolve") settle.resolve();
        else settle.reject(new Error("late failure"));
        await operation;
        assert.deepEqual(
          [panel._payload, requests, refreshes, assigns, renders, scrolls,
            panel._lastActionMessage, panel._error],
          [payloadB, 1, 0, 0, rendersAtB, 0, "", ""],
        );
      }
    }

    for (const row of itemCases) {
      const { kind } = row;
      name = kind === "session"
        ? "test_nilm_session_validation_actions_reload_workspace_in_place"
        : kind === "session-reject"
          ? "test_nilm_session_validation_buttons_call_services_or_update_interval"
          : "test_nilm_assignment_and_session_success_preserves_the_lane_inspector";
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      let assigns = 0;
      let refreshes = 0;
      let feedbackFocus = 0;
      let restoredScroll = null;
      const panel = makePanel({
        _evidenceRequestId: 8,
        _payload: {
          circuit: { circuit_id: "mains" },
          actions: {},
        },
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel._scrollToTop = () => { throw new Error(`${kind} scrolled to top`); };
      context.window.scrollY = 420;
      context.window.scrollTo = (options) => { restoredScroll = options.top; };
      context.window.location.assign = () => { assigns += 1; };
      const action = makeAction(`${kind}_service`);
      const assignment = { assignment_id: "assignment-1", display_name: "Dishwasher",
        appliance_profile: "washer",
        actions: kind === "save" ? { rename: action } : { publish: action } };
      const session = { session_id: "session-1", assignment_id: "assignment-1",
        display_name: "Dishwasher",
        actions: { [row.action]: action } };
      panel._nilmWorkspace = makeWorkspace({
        assignments: [assignment],
        sessions: [session],
      });
      panel._nilmWorkspace.lanes.assigned.assignment_ids = ["assignment-1"];
      panel._nilmActiveLane = "assigned";
      panel._nilmSelectedReviewKey = "assignment:assignment-1";
      panel.shadowRoot.querySelector = (selector) => {
        if (selector === "#nilm_assignment_label_0") return { value: "Dishwasher Updated" };
        if (selector === '[data-inline-feedback="assignment:assignment-1"]') {
          return { focus() { feedbackFocus += 1; } };
        }
        return null;
      };
      panel._hass = { callService: async () => {} };
      panel._refreshNilmWorkspaceData = async () => {
        refreshes += 1;
        for (const lane of Object.values(panel._nilmWorkspace.lanes)) {
          lane.assignment_ids = [];
        }
        panel._nilmWorkspace.lanes[row.lane].assignment_ids = ["assignment-1"];
        if (kind === "save") assignment.display_name = "Dishwasher Updated";
        return true;
      };
      if (kind === "save") await panel._saveNilmAssignmentChanges(0);
      else await panel._callNilmWorkspaceItemAction(row.collection, 0, row.action);
      assert.deepEqual(
        [refreshes, assigns, panel._nilmActiveLane, panel._nilmSelectedReviewKey,
          panel._inlineFeedback.scope, panel._inlineFeedback.kind,
          panel._inlineFeedback.message, feedbackFocus, restoredScroll],
        [1, 0, row.lane, "assignment:assignment-1",
          "assignment:assignment-1", "success", row.message, 1, 420],
      );
      const inspector = panel._renderNilmReviewLayout(panel._nilmWorkspace);
      assert.match(inspector, /data-nilm-review-inspector/);
      assert.match(inspector, /data-nilm-assignment-index="0"/);
    }

    name = "test_partial_assignment_save_failure_refreshes_successful_change";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      let calls = 0;
      let refreshes = 0;
      const assignment = { assignment_id: "a", display_name: "Old",
        appliance_profile: "washer", actions: {
          rename: makeAction("rename"), change_profile: makeAction("profile"),
        } };
      const panel = makePanel({ _nilmWorkspace: { assignments: [assignment] } });
      panel._render = () => {};
      panel.shadowRoot.querySelector = (selector) => selector.includes("label")
        ? { value: "New" } : { value: "dryer" };
      panel._hass = { callService: async () => {
        calls += 1;
        if (calls === 2) throw new Error("profile failed");
      } };
      panel._refreshNilmWorkspaceData = async () => { refreshes += 1; return true; };
      const profileKey = `${panel._nilmAssignmentDraftKey(assignment)}:appliance_profile`;
      panel._nilmAssignmentDrafts.set(profileKey, "dryer");
      await panel._saveNilmAssignmentChanges(0);
      assert.deepEqual(
        [calls, refreshes, panel._busyAction, panel._error,
          panel._nilmAssignmentDrafts.has(profileKey)],
        [2, 1, "", "Could not save assignment changes: profile failed", true],
      );
    }

    const sessionAssign = makeAction("assign_session", { session_id: "session-new" });
    sessionAssign.requires = ["label"];
    const newSession = { session_id: "session-new", display_name: "Dryer",
      actions: { assign: sessionAssign } };
    const oldAssignment = { assignment_id: "assignment-old", display_name: "Old" };
    const source = { assignment_id: "assignment-source", display_name: "Dryer",
      actions: { merge: { ...makeAction("merge_assignments"),
        requires: ["target_assignment_id"] } } };
    const mergeTarget = { assignment_id: "assignment-target", display_name: "Laundry",
      actions: { publish: {} } };
    for (const row of [
      {
        name: "test_new_session_assignment_selects_refreshed_assignment_inspector",
        kind: "session", lane: "assigned", id: "assignment-new",
        sessions: [newSession], assignments: [],
        results: [{ assignment_id: "assignment-new", display_name: "Dryer",
          session_ids: ["session-new"], actions: { publish: {} } },
        ],
      },
      {
        name: "test_save_with_merge_selects_surviving_target_inspector",
        kind: "merge", lane: "published", id: "assignment-target",
        sessions: [], assignments: [source, mergeTarget], results: [mergeTarget],
      },
      {
        name: "test_existing_session_reassignment_selects_explicit_target",
        kind: "reassign", lane: "published", id: "assignment-target",
        sessions: [{ session_id: "session-move", assignment_id: "assignment-old",
          display_name: "Dryer", actions: { assign: sessionAssign } }],
        assignments: [oldAssignment, mergeTarget], results: [oldAssignment, mergeTarget],
      },
    ]) {
      name = row.name;
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const calls = [];
      let focused = 0;
      const refreshedSessions = row.kind === "merge" ? row.sessions : row.sessions.map(
        (session) => ({ ...session, assignment_id: row.id }),
      );
      const refreshedAssignments = row.kind === "merge" ? row.results : row.results.map(
        (assignment) => assignment.assignment_id === row.id
          ? { ...assignment, session_ids: Array.from(new Set([
            ...(assignment.session_ids || []), refreshedSessions[0].session_id,
          ])) }
          : assignment,
      );
      const refreshed = makeWorkspace({
        assignments: refreshedAssignments,
        sessions: refreshedSessions,
      });
      refreshed.lanes[row.lane].assignment_ids = [row.id];
      if (row.kind === "reassign") refreshed.lanes.assigned.assignment_ids = ["assignment-old"];
      const panel = makePanel({
        _nilmWorkspace: makeWorkspace({
          assignments: row.assignments,
          sessions: row.sessions,
        }),
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel._hass = { callService: async (_domain, _service, data) => calls.push(data) };
      panel.shadowRoot.querySelector = (selector) => {
        if (selector === "#nilm_session_label_0") return { value: "Dryer" };
        if (selector === "#nilm_assignment_merge_target_0") {
          return { value: "assignment-target" };
        }
        if (selector === `[data-inline-feedback="assignment:${row.id}"]`) {
          return { focus() { focused += 1; } };
        }
        return null;
      };
      panel._refreshNilmWorkspaceData = async () => {
        panel._nilmWorkspace = refreshed;
        return true;
      };
      if (row.kind === "reassign") {
        panel._nilmExistingAssignmentSelection = () => (
          { label: "Laundry", assignment_id: row.id }
        );
      }
      if (row.kind !== "merge") {
        await panel._callNilmWorkspaceItemAction("sessions", 0, "assign");
      } else {
        await panel._callNilmWorkspaceItemAction("assignments", 0, "merge");
      }
      assert.equal(
        calls[0][row.kind === "merge" ? "target_assignment_id" : "assignment_id"],
        row.kind === "session" ? undefined : row.id,
      );
      assert.deepEqual(
        [panel._nilmActiveLane, panel._nilmSelectedReviewKey,
          panel._inlineFeedback.scope, panel._inlineFeedback.kind, focused],
        [row.lane, `assignment:${row.id}`, `assignment:${row.id}`, "success", 1],
      );
      const inspector = panel._renderNilmReviewLayout(panel._nilmWorkspace);
      assert.equal((inspector.match(/data-nilm-review-inspector/g) || []).length, 1);
      assert.match(
        inspector,
        new RegExp(`data-nilm-assignment-index="${row.kind === "reassign" ? 1 : 0}"`),
      );
    }

    for (const newerFails of [false, true]) {
      name = "test_workspace_mutations_converge_after_service_reordering_or_failure";
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const services = [];
      const requests = [];
      let focused = 0;
      const assignments = ["older", "newer"].map((suffix) => ({
        assignment_id: `assignment-${suffix}`,
        display_name: suffix,
        actions: { publish: makeAction(`publish_${suffix}`) },
      }));
      const panel = makePanel({ _nilmWorkspace: makeWorkspace({ assignments }) });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel.shadowRoot.querySelector = (selector) =>
        selector === '[data-inline-feedback="assignment:assignment-newer"]' ?
          { focus() { focused += 1; } } : null;
      panel._hass = { callService: () => new Promise((resolve, reject) => {
        services.push({ resolve, reject });
      }) };
      panel._requestJson = () => new Promise((resolve) => requests.push(resolve));
      const older = panel._callNilmWorkspaceItemAction("assignments", 0, "publish");
      const newer = panel._callNilmWorkspaceItemAction("assignments", 1, "publish");
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(services.length, 2);
      const converged = makeWorkspace({ assignments });
      converged.lanes.published.assignment_ids = assignments.map(
        (assignment) => assignment.assignment_id,
      );
      if (newerFails) {
        services[0].resolve();
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(requests.length, 1);
        services[1].reject(new Error("newer failed"));
        await newer;
        requests[0](converged);
        await older;
        assert.equal(panel._nilmWorkspace, converged);
        assert.match(panel._error, /newer failed/);
      } else {
        services[1].resolve();
        await new Promise((resolve) => setImmediate(resolve));
        const newerWorkspace = makeWorkspace({ assignments: [assignments[1]] });
        newerWorkspace.lanes.published.assignment_ids = ["assignment-newer"];
        requests[0](newerWorkspace);
        services[0].resolve();
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(requests.length, 2);
        const feedback = panel._inlineFeedback;
        requests[1](converged);
        await Promise.all([older, newer]);
        name = "test_overlapping_workspace_refreshes_keep_newest_assignment_state";
        assert.deepEqual(
          [panel._nilmWorkspace, panel._nilmActiveLane, panel._nilmSelectedReviewKey,
            panel._inlineFeedback, focused],
          [converged, "published", "assignment:assignment-newer", feedback, 1],
        );
      }
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_alert_evidence_informational_metrics_are_scoped_and_unframed() -> None:
    asset = _frontend_source()

    scoped_start = asset.index("        .evidence-meta .metric,")
    scoped_style = asset[scoped_start : asset.index("}", scoped_start)]
    for selector in (
        ".evidence-meta .metric",
        "[data-evidence-comparison] .metric",
    ):
        assert selector in scoped_style
    assert "[data-evidence-technical] .metric" not in scoped_style
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


def test_evidence_visual_blocks_use_white_card_surfaces() -> None:
    asset = _frontend_source()
    surface_rule = re.search(
        r"\.legend\s*\{(?P<body>.*?)\}",
        asset,
        re.DOTALL,
    )

    assert surface_rule is not None
    assert "background: var(--card-background-color, #fff);" in surface_rule.group(
        "body"
    )
    assert "padding: 16px 0 0;" in surface_rule.group("body")
    assert "border:" not in surface_rule.group("body")
    assert "box-shadow:" not in surface_rule.group("body")


def test_nilm_multi_interval_labeling_contracts() -> None:
    _run_panel_node_script(
        """
(() => {
  const panel = makePanel({
    _nilmIntervalEditorOpen: true,
    _nilmActiveIntervalIndex: 1,
    _nilmLabelIntervalDraft: {
      label: "Dishwasher",
      appliance_id: "dishwasher",
      appliance_profile: "dishwasher",
      intervals: [
        { start: "2026-07-10T08:00", end: "2026-07-10T08:30" },
        { start: "2026-07-10T09:00", end: "2026-07-10T09:45" },
      ],
    },
  });
  const workspace = makeWorkspace({ actions: { label_interval: {
    ...makeAction("label_nilm_interval"),
    profile_options: [{ value: "dishwasher", label: "Dishwasher" }],
  } } });
  const html = panel._renderNilmLabelIntervalEditor(workspace);
  assert.ok(html.includes("Label appliance interval"));
  assert.ok(html.includes("data-nilm-interval-guidance"));
  for (const guidance of [
    "Select one complete run of one appliance.",
    "Start just before its power rises.",
    "End just after its power falls.",
    "Avoid intervals where another appliance also turns on or off.",
    "One clean run is enough.",
  ]) {
    assert.ok(html.includes(guidance), guidance);
  }
  assert.ok(html.includes('data-nilm-interval-row="0"'));
  assert.ok(html.includes('data-nilm-interval-row="1"'));
  assert.ok(html.includes('data-nilm-active="true"'));
  assert.ok(html.indexOf("Appliance Type") < html.indexOf('data-nilm-interval-row="0"'));
  assert.ok(!html.includes("Ground Truth Sensor"));
  assert.ok(!html.includes("Generate From Sensor"));

  panel._nilmLabelIntervalDraft.intervals[0].interval_id = "saved-1";
  const bands = panel._nilmGraphBands(makeWorkspace({
    assignments: [{ assignment_id: "retired", lifecycle_state: "retired",
      label_interval_ids: ["retired-1"] }],
    label_intervals: [
      { interval_id: "saved-1", start: "2026-07-10T08:00Z", end: "2026-07-10T08:30Z" },
      { interval_id: "retired-1", start: "2026-07-10T10:00Z", end: "2026-07-10T10:30Z" },
    ],
  }), []);
  assert.equal(bands.filter((item) => item.interval_id === "saved-1").length, 1);
  assert.equal(bands.filter((item) => item.interval_id === "retired-1").length, 0);
  assert.ok(bands.some((item) => item.band_kind === "draft" && item.selected));

  const makeChart = () => {
    const listeners = new Map();
    const removed = [];
    const chart = {
      dataset: {
        chartLeft: "54", chartRight: "876", chartTop: "18", chartBottom: "278",
        chartStart: "0", chartEnd: "1000",
      },
      ownerDocument: { createElementNS() {
        return {
          attributes: {},
          setAttribute(name, value) { this.attributes[name] = String(value); },
          remove() { this.removed = true; },
        };
      } },
      getAttribute: () => "0 0 900 320",
      getBoundingClientRect: () => ({ left: 0, width: 900 }),
      appendChild(element) { this.band = element; },
      addEventListener(type, callback) { listeners.set(type, callback); },
      removeEventListener(type, callback) { removed.push([type, callback]); },
    };
    return { chart, listeners, removed };
  };
  let renders = 0;
  panel._render = () => { renders += 1; };
  panel._scheduleNilmIntervalEvidence = () => {};

  const forward = makeChart();
  panel._startNilmChartSelection(
    { target: { dataset: {} }, clientX: 300, pointerId: 1 },
    forward.chart,
  );
  const stalePointerUp = forward.listeners.get("pointerup");
  forward.listeners.get("pointermove")({ clientX: 500, pointerId: 1 });
  assert.equal(forward.chart.band.attributes["data-nilm-provisional-band"], "true");
  assert.ok(Number(forward.chart.band.attributes.width) > 1);
  assert.equal(renders, 0);
  assert.equal(panel._nilmLabelIntervalDraft.intervals.length, 2);

  forward.listeners.get("pointerleave")({ clientX: 950, pointerId: 1 });
  assert.equal(panel._nilmLabelIntervalDraft.intervals.length, 3);
  assert.equal(panel._nilmActiveIntervalIndex, 2);
  assert.equal(panel._nilmLabelIntervalDraft.intervals[2].end_millis, 1000);
  assert.equal(renders, 1);
  assert.equal(forward.chart.band.removed, true);
  assert.ok(forward.removed.some(([type]) => type === "pointermove"));

  stalePointerUp({ clientX: 700, pointerId: 1 });
  assert.equal(panel._nilmLabelIntervalDraft.intervals.length, 3);
  assert.equal(panel._updateNilmDraftBoundary(2, "start", 400), true);
  assert.equal(panel._nilmLabelIntervalDraft.intervals[2].start_millis, 400);

  const zeroWidth = makeChart();
  panel._startNilmChartSelection(
    { target: { dataset: {} }, clientX: 400, pointerId: 2 },
    zeroWidth.chart,
  );
  zeroWidth.listeners.get("pointercancel")({ pointerId: 2 });
  assert.equal(panel._nilmLabelIntervalDraft.intervals.length, 3);
  assert.equal(zeroWidth.chart.band.removed, true);

  const reverse = makeChart();
  panel._startNilmChartSelection(
    { target: { dataset: {} }, clientX: 700, pointerId: 3 },
    reverse.chart,
  );
  reverse.listeners.get("pointermove")({ clientX: 300, pointerId: 3 });
  reverse.listeners.get("pointerup")({ clientX: 300, pointerId: 3 });
  const reversedInterval = panel._nilmLabelIntervalDraft.intervals[3];
  assert.ok(reversedInterval.start_millis < reversedInterval.end_millis);
})();
"""
    )


def test_nilm_reference_sensor_controls_and_import_order() -> None:
    _run_panel_node_script(
        """
(async () => {
  const reference = {
    state_entity_id: "switch.pump",
    power_entity_id: null,
    threshold_w: 25,
    on_threshold: 25,
    off_threshold: 20,
    on_dwell_seconds: 3,
    off_dwell_seconds: 4,
    minimum_interval_seconds: 30,
    merge_gap_seconds: 5,
    maximum_unknown_gap_seconds: 60,
    maximum_power_gap_seconds: 120,
    import_summary: {
      candidate_interval_count: 5,
      imported_interval_count: 3,
      discarded_minimum_duration_count: 1,
      bridged_unknown_gap_count: 2,
      merged_inactive_gap_count: 1,
      low_coverage_interval_count: 1,
      warnings: ["coverage_below_target", "<unsafe warning>"],
    },
    suggested_power_entity_id: "sensor.pump_power",
    state_options: [
      { entity_id: "switch.pump", name: "Pump switch", device_id: "device-1" },
    ],
    power_options: [
      { entity_id: "sensor.pump_power", name: "Pump power", unit: "W", device_id: "device-1" },
      { entity_id: "sensor.other_power", name: "Other power", unit: "W", device_id: "device-2" },
    ],
    actions: {
      set: makeAction("set_nilm_reference_link", { circuit_id: "mixed", assignment_id: "pump" }),
      import: makeAction("generate_nilm_sensor_label_intervals", { circuit_id: "mixed", assignment_id: "pump", label: "Pump" }),
      remove: makeAction("remove_nilm_reference_link", { circuit_id: "mixed", assignment_id: "pump" }),
    },
  };
  const item = { assignment_id: "pump", display_name: "Pump", reference };
  const calls = [];
  const panel = makePanel({
    _nilmWorkspace: makeWorkspace({ assignments: [item] }),
    _nilmReferenceDrafts: new Map(),
    _nilmSelectedReviewKey: "assignment:pump",
    _nilmGraphWindow: { start: Date.parse("2026-08-01T00:00:00Z"), end: Date.parse("2026-08-02T00:00:00Z") },
    _hass: { async callService(domain, service, data) { calls.push({ domain, service, data }); } },
  });
  panel._render = () => {};
  panel._refreshNilmWorkspaceData = async () => true;
  panel._nilmWorkspaceActionContext = () => ({
    requestId: 1, routeKey: "route", isCurrent: () => true, isRouteCurrent: () => true,
  });
  panel._restoreNilmIntervalScroll = () => {};

  let html = panel._renderNilmReferenceSensors(item, 0);
  assert.ok(html.includes("Reference sensors"));
  assert.ok(!html.includes('value="sensor.pump_power" selected'));
  assert.ok(html.includes("<ha-entity-picker"));
  assert.ok(html.includes('data-nilm-reference-input="stateEntityId"'));
  assert.ok(html.includes('data-nilm-reference-input="powerEntityId"'));
  assert.ok(!html.includes("<option"));
  assert.ok(!html.includes('data-nilm-reference-input="onThreshold"'));
  assert.ok(html.includes('data-nilm-reference-input="onDwellSeconds"'));
  assert.ok(html.includes("UNKNOWN is neither OFF nor ON"));
  assert.ok(html.includes("Hysteresis uses different ON and OFF thresholds"));
  assert.ok(html.includes("prevent guessing across longer missing history"));
  assert.ok(html.includes('data-nilm-reference-import-summary'));
  assert.ok(html.includes("Last import: 3 of 5 intervals imported."));
  assert.ok(html.includes('data-nilm-reference-low-coverage'));
  assert.ok(html.includes("&lt;unsafe warning&gt;"));

  panel._nilmReferenceDrafts.set("pump", {
    stateEntityId: "",
    powerEntityId: "sensor.other_power",
    thresholdW: "12", onThreshold: "12", offThreshold: "10",
    onDwellSeconds: "", offDwellSeconds: "", minimumIntervalSeconds: "",
    mergeGapSeconds: "", maximumUncertainGapSeconds: "", maximumPowerGapSeconds: "",
    start: "2026-08-01T00:00",
    end: "2026-08-02T00:00",
    open: true,
    error: "",
  });
  html = panel._renderNilmReferenceSensors(item, 0);
  assert.ok(!html.includes('value="sensor.other_power" selected'));
  assert.ok(html.includes('data-nilm-reference-input="onThreshold"'));
  assert.ok(html.includes('data-nilm-reference-input="offThreshold"'));
  assert.ok(html.includes("<details open"));

  panel._nilmReferenceDrafts.set("pump", {
    stateEntityId: "switch.pump",
    powerEntityId: "sensor.pump_power",
    thresholdW: "25", onThreshold: "25", offThreshold: "20",
    onDwellSeconds: "3", offDwellSeconds: "4", minimumIntervalSeconds: "30",
    mergeGapSeconds: "5", maximumUncertainGapSeconds: "60", maximumPowerGapSeconds: "120",
    start: "2026-08-01T00:00",
    end: "2026-08-02T00:00",
    open: true,
    error: "",
  });
  await panel._callNilmReferenceAction(0, "link_import");
  assert.deepEqual(calls.map((call) => call.service), [
    "set_nilm_reference_link",
    "generate_nilm_sensor_label_intervals",
  ]);
  assert.equal(calls[0].data.reference_state_entity_id, "switch.pump");
  assert.equal(calls[0].data.reference_on_dwell_seconds, 3);
  assert.equal(calls[0].data.reference_maximum_unknown_gap_seconds, 60);
  assert.equal(calls[0].data.reference_maximum_power_gap_seconds, 120);
  assert.ok(!("reference_threshold_w" in calls[0].data));
  assert.ok(!("reference_on_threshold" in calls[0].data));
  assert.equal(calls[1].data.ground_truth_entity_id, "switch.pump");
  assert.equal(calls[1].data.reference_power_entity_id, "sensor.pump_power");
  assert.ok(!("threshold_w" in calls[1].data));
  assert.equal(panel._nilmReferenceDrafts.get("pump").open, true);

  panel._nilmReferenceDrafts.set("pump", {
    stateEntityId: "", powerEntityId: "sensor.pump_power",
    thresholdW: "25", onThreshold: "25", offThreshold: "20",
    onDwellSeconds: "", offDwellSeconds: "", minimumIntervalSeconds: "",
    mergeGapSeconds: "", maximumUncertainGapSeconds: "", maximumPowerGapSeconds: "",
    start: "2026-08-01T00:00", end: "2026-08-02T00:00", open: true, error: "",
  });
  await panel._callNilmReferenceAction(0, "link_import");
  assert.equal(calls.at(-2).data.reference_on_threshold, 25);
  assert.equal(calls.at(-2).data.reference_off_threshold, 20);
  assert.equal(calls.at(-2).data.reference_threshold_w, 25);
  assert.equal(calls.at(-1).data.threshold_w, 25);

  panel._nilmReferenceDrafts.set("pump", {
    stateEntityId: "", powerEntityId: "sensor.pump_power",
    thresholdW: "25", onThreshold: "10", offThreshold: "20",
    onDwellSeconds: "", offDwellSeconds: "", minimumIntervalSeconds: "",
    mergeGapSeconds: "", maximumUncertainGapSeconds: "", maximumPowerGapSeconds: "",
    start: "2026-08-01T00:00", end: "2026-08-02T00:00", open: true, error: "",
  });
  const callCount = calls.length;
  await panel._callNilmReferenceAction(0, "link_import");
  assert.equal(calls.length, callCount);
  assert.match(panel._nilmReferenceDrafts.get("pump").error, /OFF threshold/);

  const failed = makePanel({
    _nilmWorkspace: makeWorkspace({ assignments: [item] }),
    _nilmReferenceDrafts: new Map([["pump", {
      stateEntityId: "switch.pump", powerEntityId: "sensor.pump_power",
      thresholdW: "25", start: "2026-08-01T00:00", end: "2026-08-02T00:00",
      open: true, error: "",
    }]]),
    _hass: { async callService() { throw new Error("recorder failed"); } },
  });
  failed._render = () => {};
  failed._nilmWorkspaceActionContext = panel._nilmWorkspaceActionContext;
  await failed._callNilmReferenceAction(0, "link_import");
  assert.equal(failed._nilmReferenceDrafts.get("pump").open, true);
  assert.match(failed._nilmReferenceDrafts.get("pump").error, /recorder failed/);
})();
"""
    )


def test_nilm_interval_editor_can_cancel_and_remove_intervals() -> None:
    _run_panel_node_script(
        """
const panel = makePanel({
  _nilmIntervalEditorOpen: true,
  _nilmLabelIntervalDraft: {
    label: "Condensate Pump 2",
    appliance_profile: "pump",
    intervals: [{ start: "2026-08-04T08:00", end: "2026-08-04T08:10" }],
  },
});
panel._render = () => {};
let html = panel._renderNilmLabelIntervalEditor(makeWorkspace({
  actions: { label_interval: { profile_options: [] } },
}));
assert.ok(html.includes('data-nilm-cancel-interval-editor'));
assert.ok(html.includes(">Cancel<"));
assert.ok(html.includes('data-nilm-remove-interval="0"'));
assert.ok(html.includes(">Remove Interval<"));

panel._removeNilmDraftInterval(0);
assert.equal(
  JSON.stringify(panel._nilmLabelIntervalDraft.intervals),
  JSON.stringify([{ start: "", end: "", interval_id: "" }]),
);
panel._cancelNilmIntervalEditor();
assert.equal(panel._nilmIntervalEditorOpen, false);
assert.deepEqual(panel._nilmLabelIntervalDraft, panel._emptyNilmLabelIntervalDraft());

html = panel._renderNilmReviewInspector({
  kind: "interval",
  index: 2,
  item: {
    interval_id: "saved-interval",
    start: "2026-08-04T08:00:00Z",
    end: "2026-08-04T08:10:00Z",
    actions: { delete: makeAction("delete_nilm_label_interval") },
  },
});
assert.ok(!html.includes('data-nilm-label-interval-action="delete"'));
assert.ok(html.includes("Show on graph"));
"""
    )


def test_nilm_review_editor_stages_changes_until_one_save() -> None:
    _run_panel_node_script(
        """
(async () => {
const saved = {
  interval_id: "saved-interval",
  assignment_id: "assignment-washer",
  label: "Washer",
  start: "2026-08-04T08:00:00Z",
  end: "2026-08-04T08:10:00Z",
  actions: { delete: makeAction("delete_nilm_label_interval") },
};
const session = {
  session_id: "session-review",
  display_label: "Uncertain Washer",
  pairing_confidence: 0.67,
  ambiguous: true,
  median_power_w: 440,
  actions: { assign: makeAction("assign_session_to_appliance", { requires: ["label"] }) },
};
const active = {
  assignment_id: "assignment-washer",
  display_name: "Washer",
  lifecycle_state: "needs_validation",
  actions: { accept: makeAction("assign_interval_to_appliance") },
};
const removed = {
  assignment_id: "assignment-retired",
  display_name: "Old Washer",
  lifecycle_state: "retired",
  actions: { delete_permanently: makeAction("delete_nilm_appliance_assignment") },
};
const workspace = makeWorkspace({
  actions: { label_interval: {
    ...makeAction("save_nilm_interval_changes"),
    assignment_options: [{ value: "assignment-washer", label: "Washer" }],
  } },
  label_intervals: [saved],
  sessions: [session],
  assignments: [active, removed],
});
workspace.lanes.needs_review.session_ids = ["session-review"];
workspace.lanes.needs_review.assignment_ids = ["assignment-washer"];
workspace.lanes.hidden.assignment_ids = ["assignment-retired"];
const calls = [];
const panel = makePanel({
  _nilmWorkspace: workspace,
  _nilmIntervalEditorOpen: false,
  _nilmLabelIntervalDraft: {
    label: "Washer", appliance_id: "washer", appliance_profile: "washer",
    assignment_id: "assignment-washer", intervals: [{ ...saved }],
  },
});
panel._render = () => {};
panel._restoreNilmIntervalScroll = () => {};
panel._refreshNilmWorkspaceData = async () => true;
panel._hass = { callService: async (domain, service, data) => calls.push({ domain, service, data }) };
panel.shadowRoot.querySelector = (selector) => selector === "#nilm_session_label_0"
  ? { value: "Washer" }
  : selector === '[data-nilm-existing-assignment="label_interval"]'
    ? { value: "assignment-washer", selectedOptions: [{ textContent: "Washer" }] }
  : null;

const reviewItems = panel._nilmLaneItems(workspace);
assert.equal(reviewItems.map((item) => item.kind).join(","), "assignment,session");
const sessionItem = reviewItems.find((item) => item.kind === "session");
assert.equal(panel._nilmReviewKey(sessionItem), "session:session-review");
const sessionHtml = panel._renderNilmReviewInspector(sessionItem);
assert.ok(sessionHtml.includes("Pairing confidence: 67%"), sessionHtml);
assert.ok(sessionHtml.includes("Ambiguous"), sessionHtml);
assert.ok(sessionHtml.includes('data-nilm-session-action="assign"'), sessionHtml);
await panel._callNilmWorkspaceItemAction("sessions", 0, "assign");
assert.equal(calls[0].service, "assign_session_to_appliance");

const assignmentEditor = panel._renderNilmLabelIntervalEditor(workspace);
assert.ok(assignmentEditor.includes('data-nilm-existing-assignment="label_interval"'));
panel._rememberNilmLabelIntervalDraft({ dataset: { nilmExistingAssignment: "label_interval" } });
assert.equal(panel._nilmLabelIntervalDraft.assignment_id, "assignment-washer");
assert.equal(panel._nilmLabelIntervalDraft.label, "Washer");

const activeHtml = panel._renderNilmAssignmentActions(active, 0);
const removedHtml = panel._renderNilmAssignmentActions(removed, 1);
assert.ok(activeHtml.includes('data-nilm-assignment-action="accept"'));
assert.ok(!activeHtml.includes("delete_permanently"));
assert.ok(removedHtml.includes('data-nilm-assignment-action="delete_permanently"'));

panel._openNilmIntervalEditor();
panel._removeNilmDraftInterval(0);
assert.equal(calls.length, 1, "staging a saved removal must not call a service");
assert.equal(JSON.stringify(panel._nilmRemovedIntervalIds), '["saved-interval"]');
assert.equal(panel._nilmIntervalDraftItems().length, 0);
panel._cancelNilmIntervalEditor();
assert.equal(calls.length, 1, "Cancel must not call a service");
assert.equal(JSON.stringify(panel._nilmRemovedIntervalIds), "[]");
assert.equal(panel._nilmIntervalDraftItems()[0].interval_id, "saved-interval");

panel._openNilmIntervalEditor();
panel._removeNilmDraftInterval(0);
const editorHtml = panel._renderNilmLabelIntervalEditor(workspace);
assert.ok(editorHtml.includes(">Save Changes<"), editorHtml);
assert.ok(editorHtml.includes("Select one complete run of one appliance"), editorHtml);
assert.ok(editorHtml.includes("Add more clean runs to improve"), editorHtml);
await panel._callNilmLabelIntervalAction(-1, "save");
assert.equal(calls.length, 2);
assert.equal(calls[1].service, "save_nilm_interval_changes");
assert.equal(JSON.stringify(calls[1].data.intervals), "[]");
assert.equal(JSON.stringify(calls[1].data.removed_interval_ids), '["saved-interval"]');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_existing_interval_edit_updates_preview_and_saves_same_interval() -> None:
    _run_panel_node_script(
        """
(async () => {
const interval = {
  interval_id: "saved-interval",
  label: "Condensate Pump 2",
  appliance_id: "condensate_pump_2",
  start: "2026-08-04T08:00:00Z",
  end: "2026-08-04T08:10:00Z",
};
const workspace = makeWorkspace({
  history: {
    api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains",
    start: "2026-08-04T08:00:00Z",
    end: "2026-08-04T08:10:00Z",
  },
  label_intervals: [interval],
  actions: { label_interval: makeAction("label_nilm_interval") },
});
const calls = [];
let renders = 0;
const panel = makePanel({ _nilmWorkspace: workspace });
panel._nilmWorkspaceHistorySeries = [[
  { entity_id: "sensor.hvac_2_power", state: "100", effective_role: "real_power",
    source_unit: "W", last_changed: "2026-08-04T08:01:00Z" },
  { entity_id: "sensor.hvac_2_power", state: "184", effective_role: "real_power",
    source_unit: "W", last_changed: "2026-08-04T08:02:00Z" },
  { entity_id: "sensor.hvac_2_power", state: "184", effective_role: "real_power",
    source_unit: "W", last_changed: "2026-08-04T08:09:00Z" },
  { entity_id: "sensor.hvac_2_power", state: "100", effective_role: "real_power",
    source_unit: "W", last_changed: "2026-08-04T08:10:00Z" },
]];
panel._render = () => { renders += 1; };
panel._refreshNilmWorkspaceData = async () => true;
panel._restoreNilmIntervalScroll = () => {};
panel.shadowRoot.querySelector = () => null;
panel._loadNilmWorkspaceHistoryForWindow = async () => true;
panel._hass = { callService: async (domain, service, data) => {
  calls.push({ domain, service, data });
} };

await panel._callNilmLabelIntervalAction(0, "adjust");
assert.equal(panel._nilmIntervalEditorOpen, false);
assert.equal(panel._editNilmFocusedInterval(), true);
assert.equal(panel._nilmLabelIntervalDraft.intervals[0].interval_id, "saved-interval");
renders = 0;
const changedStartIso = "2026-08-04T08:02:00.000Z";
const changedStart = panel._datetimeLocalFromMillis(Date.parse(changedStartIso));
panel._rememberNilmLabelIntervalDraft({
  dataset: { nilmLabelIntervalInput: "start", nilmIntervalIndex: "0" },
  value: changedStart,
});
assert.equal(renders, 2, "boundary edits render both the draft and cleared backend evidence");
const bands = panel._nilmGraphBands(workspace, []);
assert.equal(bands.length, 1);
assert.equal(bands[0].band_kind, "draft");
assert.equal(bands[0].start, changedStartIso);
const previewHtml = panel._renderNilmLabelIntervalEditor(workspace);
assert.ok(!previewHtml.includes("Estimated load"), previewHtml);

await panel._callNilmLabelIntervalAction(-1, "save");
assert.equal(calls.length, 1, JSON.stringify(panel._inlineFeedback));
assert.equal(calls[0].data.interval_id, "saved-interval");
assert.equal(calls[0].data.start, changedStartIso);
assert.ok(!("observed_transition_w" in calls[0].data));
assert.ok(!("appliance_profile" in calls[0].data));
assert.equal(panel._nilmIntervalEditorOpen, false);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_interval_evidence_preview_is_backend_authoritative() -> None:
    workspace_source = NILM_WORKSPACE_ASSET.read_text(encoding="utf-8")

    assert "NILM_INTERVAL_EVIDENCE_API_PATH" in workspace_source
    assert "_requestNilmIntervalEvidence" in workspace_source
    assert "data-nilm-interval-evidence" in workspace_source
    assert "saved.observed_transition_w" not in workspace_source
    assert "_nilmLabelIntervalPowerPreview" not in workspace_source


def test_nilm_assigned_interval_is_visible_and_persistently_removable() -> None:
    _run_panel_node_script(
        """
(async () => {
const interval = {
  interval_id: "saved-interval",
  assignment_id: "assignment-pump",
  label: "Condensate Pump 2",
  start: "2026-08-04T08:00:00Z",
  end: "2026-08-04T08:10:00Z",
  actions: { delete: makeAction("delete_nilm_label_interval") },
};
const assignment = {
  assignment_id: "assignment-pump",
  display_name: "Condensate Pump 2",
  lifecycle_state: "assigned",
  label_interval_ids: ["saved-interval"],
  actions: {},
};
const workspace = makeWorkspace({
  history: {
    api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains",
    start: "2026-08-04T08:00:00Z",
    end: "2026-08-04T08:10:00Z",
  },
  assignments: [assignment],
  label_intervals: [interval],
});
const calls = [];
const panel = makePanel({ _nilmWorkspace: workspace });
panel._render = () => {};
panel._restoreNilmIntervalScroll = () => {};
panel.shadowRoot.querySelector = () => null;
panel._loadNilmWorkspaceHistoryForWindow = async () => true;
panel._hass = { callService: async (domain, service, data) => {
  calls.push({ domain, service, data });
} };

let html = panel._renderNilmReviewInspector({
  kind: "assignment",
  index: 0,
  item: assignment,
});
assert.ok(html.includes("Labeled interval"), html);
assert.ok(html.includes('data-nilm-label-interval-action="adjust"'), html);
assert.ok(!html.includes('data-nilm-label-interval-action="delete"'), html);

await panel._callNilmLabelIntervalAction(0, "adjust");
assert.equal(panel._nilmIntervalEditorOpen, false);
assert.equal(panel._editNilmFocusedInterval(), true);
html = panel._renderNilmLabelIntervalEditor(workspace);
assert.ok(!html.includes('data-nilm-label-interval-action="delete"'), html);
assert.ok(html.includes('data-nilm-remove-interval="0"'), html);

panel._removeNilmDraftInterval(0);
assert.equal(calls.length, 0);
assert.equal(JSON.stringify(panel._nilmRemovedIntervalIds), '["saved-interval"]');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_interval_evidence_preview_uses_explicit_target_and_ignores_stale_results() -> None:
    _run_panel_node_script(
        """
const workspace = makeWorkspace({
  circuit: { circuit_id: "mains" },
  label_intervals: [{
    start: "2026-08-04T08:00:00Z",
    end: "2026-08-04T08:10:00Z",
  }],
});
(async () => {
const panel = makePanel({
  _nilmWorkspace: workspace,
  _nilmActiveIntervalIndex: 0,
  _nilmLabelIntervalDraft: { intervals: workspace.label_intervals },
  _loadedRouteKey: "/panel?entry_id=entry-1&circuit_id=wrong-circuit",
});
const path = panel._nilmIntervalEvidenceRequest();
assert.ok(path.includes("entry_id=entry-1"), path);
assert.ok(path.includes("circuit_id=mains"), path);
assert.equal(new URL(path, "http://example.local").searchParams.get("start"), "2026-08-04T08:00:00.000Z");
let rendered = 0;
panel._render = () => { rendered += 1; };
const requestedPaths = [];
panel._requestJson = async (requestPath) => {
  requestedPaths.push(requestPath);
  return { interval_evidence: {
  start_transition_w: 500, stop_transition_w: -490, average_power_w: 480,
  median_power_w: 475, partial_energy_kwh: 0.12, source_coverage: 0.9,
  power_coverage: 0.8, quality_flags: ["power_gap"],
  } };
};
const timers = new Map();
let nextTimer = 0;
context.setTimeout = (callback) => { const id = ++nextTimer; timers.set(id, callback); return id; };
context.clearTimeout = (id) => timers.delete(id);
panel._nilmIntervalEvidence = { start_transition_w: 1 };
panel._scheduleNilmIntervalEvidence();
panel._nilmLabelIntervalDraft.intervals[0].end = "2026-08-04T08:12:00Z";
panel._scheduleNilmIntervalEvidence();
assert.equal(panel._nilmIntervalEvidence, null, "new bounds must immediately clear stale evidence");
assert.equal(rendered, 2, "each valid boundary edit renders its cleared preview");
assert.equal(timers.size, 1, "rapid boundary edits retain only the final debounce timer");
for (const callback of timers.values()) callback();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(requestedPaths.length, 1, "only the final bounds request may be fetched");
const finalQuery = new URL(requestedPaths[0], "http://example.local").searchParams;
assert.equal(finalQuery.get("entry_id"), "entry-1");
assert.equal(finalQuery.get("circuit_id"), "mains");
assert.equal(finalQuery.get("start"), "2026-08-04T08:00:00.000Z");
assert.equal(finalQuery.get("end"), "2026-08-04T08:12:00.000Z");
panel._nilmIntervalEvidenceToken = 2;
panel._nilmIntervalEvidence = null;
await panel._requestNilmIntervalEvidence(path, 1);
assert.equal(panel._nilmIntervalEvidence, null, "stale response must not update evidence");
await panel._requestNilmIntervalEvidence(path, 2);
assert.equal(panel._nilmIntervalEvidence.start_transition_w, 500);
assert.equal(rendered, 4);
const html = panel._renderNilmIntervalEvidence(panel._nilmIntervalEvidence);
for (const text of ["Start transition: 500 W", "Stop transition: -490 W", "Average power: 480 W", "Median power: 475 W", "Estimated energy: 0.12 kWh", "Source coverage: 90%", "Power coverage: 80%", "A long gap appears in the power evidence"]) {
  assert.ok(html.includes(text), html);
}
})().catch((error) => { console.error(error); process.exit(1); });
"""
    )


def test_nilm_interval_editor_loads_one_backend_evidence_preview() -> None:
    _run_panel_node_script(
        """
(async () => {
const interval = {
  interval_id: "saved-interval",
  assignment_id: "assignment-pump",
  start: "2026-08-04T08:00:00Z",
  end: "2026-08-04T08:10:00Z",
};
const workspace = makeWorkspace({
  circuit: { circuit_id: "mains" },
  label_intervals: [interval],
  assignments: [{ assignment_id: "assignment-pump", display_name: "Pump" }],
});
const panel = makePanel({
  _nilmWorkspace: workspace,
  _nilmFocusedInterval: {
    start: Date.parse(interval.start), end: Date.parse(interval.end),
  },
  _loadedRouteKey: "/panel?entry_id=entry-1&circuit_id=mains",
});
let rendered = 0;
panel._render = () => { rendered += 1; };
const timers = new Map();
let nextTimer = 0;
context.setTimeout = (callback) => { const id = ++nextTimer; timers.set(id, callback); return id; };
context.clearTimeout = (id) => timers.delete(id);
const requests = [];
panel._requestJson = async (path) => {
  requests.push(path);
  return { interval_evidence: { average_power_w: 480 } };
};
panel._nilmIntervalEvidence = { average_power_w: 1 };
assert.equal(panel._editNilmFocusedInterval(), true);
assert.equal(panel._nilmIntervalEvidence, null, "loading clears stale evidence");
assert.equal(timers.size, 1, "loading schedules exactly one preview");
for (const callback of timers.values()) callback();
await new Promise((resolve) => setImmediate(resolve));
assert.equal(requests.length, 1, "loading fetches exactly one preview");
assert.equal(panel._nilmIntervalEvidence.average_power_w, 480);
assert.ok(rendered >= 2, "loading renders the draft and preview state");
})().catch((error) => { console.error(error); process.exit(1); });
"""
    )


def test_nilm_interval_action_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    const baseIntervalDraft = { label: "Dishwasher", appliance_id: "dishwasher",
      appliance_profile: "dishwasher", assignment_id: "",
      intervals: [{ start: "2026-06-24T18:12", end: "2026-06-24T19:03",
        interval_id: "" }] };
    const workspacePath = "circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains";

    name = "test_nilm_session_validation_adjust_interval_loads_session_times";
    {
      const start = "2026-06-24T18:12:00Z";
      const end = "2026-06-24T19:03:00Z";
      let renders = 0;
      let requests = 0;
      const panel = makePanel({
        _evidenceRequestId: 1,
        _nilmWorkspace: makeWorkspace({
          history: {
            start: "2026-06-24T17:00:00Z", end: "2026-06-24T20:00:00Z",
            max_hours: 24,
            api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=3",
            fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=3",
          },
          sessions: [{ start, end }],
        }),
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => { renders += 1; };
      panel.shadowRoot.querySelector = () => null;
      panel._requestJson = async () => { requests += 1; return []; };
      await panel._selectNilmSessionIntervalByIndex(0);
      assert.deepEqual(
        [panel._nilmLabelIntervalDraft.intervals[0].start,
          panel._nilmLabelIntervalDraft.intervals[0].end,
          panel._nilmIntervalEditorOpen, panel._lastActionMessage],
        [panel._datetimeLocalFromMillis(Date.parse(start)),
          panel._datetimeLocalFromMillis(Date.parse(end)), true,
          "Loaded NILM session interval."],
      );
      assert.equal(requests, 1);
      assert.ok(renders > 0);
    }

    name = "test_nilm_label_interval_form_guides_graph_selection";
    {
      const panel = makePanel({ _nilmLabelIntervalDraft: { ...baseIntervalDraft } });
      const html = panel._renderNilmLabelIntervalEditor({ label_intervals: [],
        actions: { label_interval: { profile_options: [
          { value: "dishwasher", label: "Dishwasher" },
        ] } } });
      for (const expected of [
        "Label appliance interval", "Select one complete run of one appliance",
        "Start just before its power rises",
        "Avoid intervals where another appliance also turns on or off",
        "Appliance Type", "Dishwasher", "Save Changes",
      ]) assert.ok(html.includes(expected), expected);
      assert.ok(!html.includes('data-nilm-label-interval-input="observed_transition_w"'));
    }

    name = "test_nilm_failed_interval_save_preserves_open_editor_and_draft";
    {
      let scrolls = 0;
      const panel = makePanel({
        _nilmIntervalEditorOpen: true,
        _nilmLabelIntervalDraft: { ...baseIntervalDraft },
        _nilmWorkspace: makeWorkspace({
          actions: { label_interval: makeAction("label_nilm_interval") },
        }),
      });
      const draft = panel._nilmLabelIntervalDraft;
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      panel._renderAndScrollToTop = () => { scrolls += 1; };
      panel._scrollToTop = () => { scrolls += 1; };
      panel._hass = { callService: async () => { throw new Error("save failed"); } };
      await panel._callNilmLabelIntervalAction(-1, "save");
      assert.ok(panel._nilmIntervalEditorOpen);
      assert.equal(panel._nilmLabelIntervalDraft, draft);
      assert.equal(scrolls, 0);
      assert.equal(panel._inlineFeedback.scope, "nilm-interval");
      assert.equal(panel._inlineFeedback.kind, "error");
      assert.equal(panel._nilmIntervalFailedAction, "save");
      const html = panel._renderNilmIntervalFeedback();
      assert.ok(html.includes('data-nilm-interval-retry="save"'));
      assert.ok(html.includes("save failed"));
    }

    name = "test_nilm_interval_validation_stays_local_and_keeps_draft_context";
    {
      let scrolls = 0;
      const panel = makePanel({
        _nilmIntervalEditorOpen: true,
        _nilmLabelIntervalDraft: { ...baseIntervalDraft, label: "", appliance_id: "" },
        _nilmWorkspace: makeWorkspace({
          actions: { label_interval: makeAction("label_nilm_interval") },
        }),
      });
      const draft = panel._nilmLabelIntervalDraft;
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      panel._renderAndScrollToTop = () => { scrolls += 1; };
      panel._scrollToTop = () => { scrolls += 1; };
      await panel._callNilmLabelIntervalAction(-1, "save");
      assert.equal(scrolls, 0);
      assert.equal(panel._nilmLabelIntervalDraft, draft);
      assert.ok(panel._nilmIntervalEditorOpen);
      assert.equal(panel._inlineFeedback.scope, "nilm-interval");
      assert.equal(panel._inlineFeedback.kind, "error");
    }

    name = "test_nilm_interval_success_refreshes_workspace_and_keeps_local_context";
    context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
    context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
    for (const { actionKey, clearsEditor } of [
      { actionKey: "save", clearsEditor: true },
      { actionKey: "delete", clearsEditor: false },
    ]) {
      let scrolls = 0;
      let evidenceLoads = 0;
      let workspaceLoads = 0;
      let focuses = 0;
      let focusOptions;
      context.window.scrollY = 640;
      context.window.scrollTo = (options) => {
        context.window.scrollY = typeof options === "number" ? options : options.top;
      };
      const panel = makePanel({
        _evidenceRequestId: 7,
        _payload: {
          circuit: { circuit_id: "mains" },
          nilm: {
            workspace_call_api_path: workspacePath,
            workspace_api_path: `/api/${workspacePath}`,
          },
        },
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {
        if (panel._inlineFeedback.kind === "success") context.window.scrollY = 502;
      };
      panel._scrollToTop = () => { scrolls += 1; };
      panel._renderAndScrollToTop = () => { scrolls += 1; };
      panel._loadEvidence = async () => { evidenceLoads += 1; };
      panel.shadowRoot = {
        querySelector(selector) {
          if (selector === '[data-inline-feedback="nilm-interval"]') {
            return { focus(options) { focuses += 1; focusOptions = options; } };
          }
          return null;
        },
        querySelectorAll() { return []; },
      };
      const interval = { interval_id: "interval-1", label: "Dishwasher",
        actions: { assign: makeAction("assign_interval_to_appliance"),
          delete: makeAction("delete_nilm_label_interval") } };
      const workspace = makeWorkspace({
        circuit: panel._payload.circuit,
        actions: {
          label_interval: makeAction("label_nilm_interval"),
        },
        label_intervals: [interval],
      });
      const refreshed = makeWorkspace({
        ...workspace,
        assignments: actionKey === "save" ? [{ assignment_id: "assignment-saved",
          appliance_id: "dishwasher", lifecycle_state: "needs_validation" }] : [],
        label_intervals: actionKey === "delete" ? [] : [interval],
      });
      const graphSeries = [["graph"]];
      const graphWindow = { start: 10, end: 20, min: 0, max: 30 };
      Object.assign(panel, {
        _nilmWorkspace: workspace,
        _nilmWorkspaceHistorySeries: graphSeries,
        _nilmGraphWindow: graphWindow,
        _nilmFocusedSignature: "signature-2",
        _nilmActiveLane: "assigned",
        _nilmSelectedReviewKey: "assignment:assignment-2",
        _nilmIntervalEditorOpen: true,
        _nilmLabelIntervalDraft: { ...baseIntervalDraft },
      });
      panel._nilmDecisionDrafts.set("unrelated-decision", { decision: "ignore" });
      panel._nilmAssignmentDrafts.set("unrelated-assignment", "Heat pump");
      const editorDraft = panel._nilmLabelIntervalDraft;
      const decisionDrafts = panel._nilmDecisionDrafts;
      const assignmentDrafts = panel._nilmAssignmentDrafts;
      panel._hass = { callService: async () => {} };
      panel._requestJson = async (apiPath) => {
        workspaceLoads += 1;
        assert.ok(apiPath.includes("nilm_workspace"));
        return refreshed;
      };
      const index = actionKey === "save" ? -1 : 0;
      await panel._callNilmLabelIntervalAction(index, actionKey);
      assert.deepEqual([evidenceLoads, scrolls, workspaceLoads], [0, 0, 1]);
      const expectedLane = actionKey === "save" ? "needs_review" : "assigned";
      const expectedReviewKey = actionKey === "save"
        ? "assignment:assignment-saved"
        : "assignment:assignment-2";
      assert.deepEqual(
        [context.window.scrollY, panel._nilmWorkspace, panel._nilmWorkspaceHistorySeries,
          panel._nilmGraphWindow, panel._nilmFocusedSignature, panel._nilmActiveLane,
          panel._nilmSelectedReviewKey, panel._nilmDecisionDrafts, panel._nilmAssignmentDrafts,
          panel._inlineFeedback.scope, panel._inlineFeedback.kind],
        [640, refreshed, graphSeries, graphWindow, "signature-2", expectedLane,
          expectedReviewKey, decisionDrafts, assignmentDrafts, "nilm-interval", "success"],
      );
      assert.ok(panel._inlineFeedback.message);
      assert.equal(focuses, 1);
      assert.ok(focusOptions.preventScroll);
      if (clearsEditor) {
        assert.ok(!panel._nilmIntervalEditorOpen);
        assert.notEqual(panel._nilmLabelIntervalDraft, editorDraft);
        assert.equal(panel._nilmLabelIntervalDraft.label, "");
        assert.equal(panel._nilmLabelIntervalDraft.intervals.length, 1);
      } else {
        assert.ok(panel._nilmIntervalEditorOpen);
        assert.equal(panel._nilmLabelIntervalDraft, editorDraft);
      }
    }

    name = "test_interval_refresh_invalidates_pending_focus_without_stuck_graph";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const priorSeries = [["prior"]];
      const staleSeries = [["stale"]];
      const graphWindow = { start: 10, end: 20, min: 0, max: 30 };
      const interval = { interval_id: "interval-1", label: "Dishwasher",
        actions: { delete: makeAction("delete_nilm_label_interval") } };
      const workspace = makeWorkspace({
        circuit: { circuit_id: "mains" },
        history: { start: "2026-07-09T17:00:00Z",
          end: "2026-07-09T20:00:00Z", max_hours: 24,
          api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=3",
          fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=3",
        },
        label_intervals: [interval],
      });
      const refreshed = makeWorkspace({ ...workspace, label_intervals: [] });
      const panel = makePanel({
        _evidenceRequestId: 9,
        _payload: {
          circuit: workspace.circuit,
          nilm: {
            workspace_call_api_path: workspacePath,
            workspace_api_path: `/api/${workspacePath}`,
          },
        },
        _nilmWorkspace: workspace,
        _nilmWorkspaceHistorySeries: priorSeries,
        _nilmGraphWindow: graphWindow,
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      let resolveFocused;
      let requestCount = 0;
      panel._requestJson = (apiPath) => {
        requestCount += 1;
        if (apiPath.includes("nilm_workspace_history")) {
          return new Promise((resolve) => { resolveFocused = resolve; });
        }
        return Promise.resolve(refreshed);
      };
      let serviceCalls = 0;
      panel._hass = { callService: async () => { serviceCalls += 1; } };
      const focused = panel._loadNilmWorkspaceHistoryForWindow({
        start: Date.parse("2026-07-09T18:30:00Z"),
        end: Date.parse("2026-07-09T19:30:00Z"),
      });
      assert.deepEqual(
        [panel._nilmWorkspaceHistoryLoading, panel._nilmWorkspaceHistorySeries],
        [true, priorSeries],
      );
      await panel._callNilmLabelIntervalAction(0, "delete");
      assert.deepEqual(
        [serviceCalls, requestCount, panel._nilmWorkspaceHistoryLoading,
          panel._nilmWorkspaceHistorySeries, panel._nilmGraphWindow,
          panel._inlineFeedback.kind],
        [1, 2, false, priorSeries, graphWindow, "success"],
      );
      resolveFocused(staleSeries);
      await focused;
      assert.deepEqual(
        [panel._nilmWorkspaceHistoryLoading, panel._nilmWorkspaceHistorySeries,
          panel._nilmGraphWindow, panel._nilmWorkspaceHistoryError,
          panel._nilmWorkspaceHistoryFailedRequest, panel._inlineFeedback.kind],
        [false, priorSeries, graphWindow, "", null, "success"],
      );
    }

    name = "test_interval_refresh_failure_retries_only_workspace_request";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const circuit = { circuit_id: "mains" };
      const workspace = makeWorkspace({
        circuit,
        actions: { label_interval: makeAction("label_nilm_interval") },
      });
      const refreshed = makeWorkspace({
        ...workspace,
        label_intervals: [{ interval_id: "saved", label: "Dishwasher" }],
      });
      const graphSeries = [[{
        entity_id: "sensor.mains_power",
        state: "420",
        last_changed: "2026-07-09T18:00:00Z",
      }]];
      const graphWindow = { start: 10, end: 20, min: 0, max: 30 };
      const panel = makePanel({
        _evidenceRequestId: 11,
        _loading: false,
        _payload: {
          status: "circuit_found_no_evidence",
          circuit,
          actions: {},
          nilm: {
            workspace_call_api_path: workspacePath,
            workspace_api_path: `/api/${workspacePath}`,
          },
        },
        _nilmWorkspace: workspace,
        _nilmWorkspaceHistorySeries: graphSeries,
        _nilmGraphWindow: graphWindow,
        _nilmActiveLane: "assigned",
        _nilmSelectedReviewKey: "assignment:assignment-1",
        _nilmIntervalEditorOpen: true,
        _nilmLabelIntervalDraft: { label: "Dishwasher",
          appliance_id: "dishwasher", appliance_profile: "dishwasher",
          intervals: [{ start: "2026-07-09T18:00",
            end: "2026-07-09T18:30", interval_id: "" }] },
      });
      panel._loadedRouteKey = panel._routeKey();
      panel._nilmDecisionDrafts.set("unrelated", { decision: "ignore" });
      const decisionDrafts = panel._nilmDecisionDrafts;
      let serviceCalls = 0;
      let workspaceRequests = 0;
      panel._hass = { callService: async () => { serviceCalls += 1; } };
      panel._requestJson = async () => {
        workspaceRequests += 1;
        if (workspaceRequests === 1) throw new Error("refresh unavailable");
        return refreshed;
      };
      const listeners = {};
      const retry = {
        addEventListener(type, callback) { listeners[type] = callback; },
      };
      panel.shadowRoot = {
        innerHTML: "",
        querySelectorAll() { return []; },
        querySelector(selector) {
          if (selector === "[data-nilm-interval-refresh-retry]" &&
              this.innerHTML.includes("data-nilm-interval-refresh-retry")) return retry;
          if (selector === '[data-inline-feedback="nilm-interval"]') return { focus() {} };
          return null;
        },
      };
      await panel._callNilmLabelIntervalAction(-1, "save");
      assert.deepEqual([serviceCalls, workspaceRequests], [1, 1]);
      assert.equal(panel._inlineFeedback.scope, "nilm-interval");
      assert.equal(panel._inlineFeedback.kind, "error");
      assert.match(panel._inlineFeedback.message, /completed/i);
      assert.match(panel._inlineFeedback.message, /refresh/i);
      assert.ok(panel._nilmIntervalRefreshSuccessMessage);
      assert.equal(typeof listeners.click, "function");
      assert.ok(!panel.shadowRoot.innerHTML.includes('data-nilm-interval-retry="save"'));
      assert.ok(!panel._nilmIntervalEditorOpen);
      assert.equal(panel._nilmLabelIntervalDraft.label, "");
      await listeners.click();
      assert.deepEqual([serviceCalls, workspaceRequests], [1, 2]);
      assert.deepEqual(
        [panel._nilmWorkspace, panel._inlineFeedback.kind, panel._nilmIntervalRefreshSuccessMessage,
          panel._nilmWorkspaceHistorySeries, panel._nilmGraphWindow, panel._nilmActiveLane,
          panel._nilmSelectedReviewKey, panel._nilmDecisionDrafts],
        [refreshed, "success", "", graphSeries, graphWindow, "assigned",
          "assignment:assignment-1", decisionDrafts],
      );
      assert.match(panel._inlineFeedback.message, /Saved interval label: Dishwasher/i);
    }

    for (const kind of ["interval", "signature"]) {
      name = kind === "interval"
        ? "test_interval_mutation_coalesces_with_assignment_refresh"
        : "test_signature_mutation_coalesces_with_assignment_refresh";
      context.window.location.search = "?nilm_workspace=1&circuit_id=mains";
      const requests = [];
      const assignment = { assignment_id: "assignment-1", display_name: "Dryer",
        actions: { publish: makeAction("publish_assignment") } };
      const interval = { interval_id: "interval-1", label: "Dryer",
        actions: { delete: makeAction("delete_interval") } };
      const signature = { signature_id: "signature-1",
        actions: { ignore: makeAction("ignore_signature") } };
      const workspace = makeWorkspace({ assignments: [assignment],
        label_intervals: [interval], signatures: [signature] });
      workspace.lanes.needs_review.signature_ids = ["signature-1"];
      const panel = makePanel({
        _nilmWorkspace: workspace,
      });
      panel._render = () => {};
      panel.shadowRoot.querySelector = () => null;
      panel._hass = { callService: async () => {} };
      panel._requestJson = () => new Promise((resolve) => requests.push(resolve));
      const publish = panel._callNilmWorkspaceItemAction("assignments", 0, "publish");
      const mutation = kind === "interval"
        ? panel._callNilmLabelIntervalAction(0, "delete")
        : panel._callNilmAction(signature, "signature_0", "ignore");
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(requests.length, 1);
      requests[0](makeWorkspace({ assignments: [assignment] }));
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(requests.length, 2);
      const converged = makeWorkspace({ assignments: [assignment] });
      converged.lanes.published.assignment_ids = ["assignment-1"];
      requests[1](converged);
      await Promise.all([publish, mutation]);
      assert.deepEqual(
        [panel._nilmWorkspace, panel._inlineFeedback.scope,
          panel._inlineFeedback.kind, panel._busyAction],
        [converged, kind === "interval" ? "nilm-interval" : "nilm-review", "success", ""],
      );
    }

    name = "test_interval_stale_failure_and_retry_preserve_replacement_route";
    {
      context.window.location.search = "?nilm_workspace=1&circuit_id=a";
      let rejectService;
      let renders = 0;
      const interval = { interval_id: "interval-a", label: "Dryer",
        actions: { delete: makeAction("delete_interval") } };
      const panel = makePanel({
        _nilmWorkspace: makeWorkspace({ label_intervals: [interval] }),
      });
      panel._render = () => { renders += 1; };
      panel.shadowRoot.querySelector = () => null;
      panel._hass = { callService: () => new Promise((_resolve, reject) => {
        rejectService = reject;
      }) };
      const operation = panel._callNilmLabelIntervalAction(0, "delete");
      await Promise.resolve();
      context.window.location.search = "?circuit_id=b";
      const payloadB = { status: "circuit_found_no_evidence",
        circuit: { circuit_id: "b" }, actions: {} };
      panel._requestJson = async () => payloadB;
      await panel._loadEvidence({ routeKey: panel._routeKey() });
      panel._busyAction = "route_b_busy";
      panel._inlineFeedback = { scope: "route-b", kind: "success", message: "Route B" };
      const rendersAtB = renders;
      rejectService(new Error("late interval failure"));
      await operation;
      assert.deepEqual(
        [panel._payload, panel._busyAction, panel._inlineFeedback,
          panel._error, renders],
        [payloadB, "route_b_busy",
          { scope: "route-b", kind: "success", message: "Route B" }, "", rendersAtB],
      );

      context.window.location.search = "?nilm_workspace=1&circuit_id=a";
      let resolveRetry;
      let requestCount = 0;
      const retryPanel = makePanel({
        _nilmIntervalRefreshSuccessMessage: "Saved interval",
      });
      retryPanel._render = () => {};
      retryPanel.shadowRoot.querySelector = () => null;
      retryPanel._requestJson = async () => {
        requestCount += 1;
        if (requestCount === 1) return new Promise((resolve) => { resolveRetry = resolve; });
        return payloadB;
      };
      const retry = retryPanel._retryNilmIntervalWorkspaceRefresh();
      await new Promise((resolve) => setImmediate(resolve));
      context.window.location.search = "?circuit_id=b";
      await retryPanel._loadEvidence({ routeKey: retryPanel._routeKey() });
      retryPanel._busyAction = "route_b_busy";
      retryPanel._inlineFeedback = { scope: "route-b", kind: "success", message: "Route B" };
      resolveRetry(makeWorkspace());
      await retry;
      assert.deepEqual(
        [retryPanel._payload, retryPanel._busyAction, retryPanel._inlineFeedback],
        [payloadB, "route_b_busy",
          { scope: "route-b", kind: "success", message: "Route B" }],
      );
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_alert_evidence_technical_details_has_minimum_touch_target() -> None:
    asset = _frontend_source()

    summary_start = asset.index("        [data-evidence-technical] > summary {")
    summary_style = asset[summary_start : asset.index("}", summary_start)]
    for declaration in (
        "box-sizing: border-box;",
        "line-height: 20px;",
        "min-height: 44px;",
        "padding: 12px 0;",
    ):
        assert declaration in summary_style


def test_non_nilm_panel_routes_use_the_shared_surface_contract() -> None:
    evidence_views = EVIDENCE_VIEWS_ASSET.read_text(encoding="utf-8")
    appliance_views = APPLIANCE_VIEWS_ASSET.read_text(encoding="utf-8")
    panel_shell = PANEL_SHELL_ASSET.read_text(encoding="utf-8")

    assert "data-evidence-comparison" in evidence_views
    assert "recommendation-layout" in evidence_views
    assert "appliance-insights-table" in appliance_views
    assert "setup-health-status" in appliance_views
    assert '<header class="page-header">' in panel_shell
    assert 'class="panel page-header"' not in panel_shell
    assert "font-family:" not in evidence_views
    assert "font-family:" not in appliance_views


def test_alert_and_nilm_sections_share_home_assistant_card_surfaces() -> None:
    asset = _frontend_source()
    surface_rule = re.search(
        r"\.section-surface\s*\{(?P<body>.*?)\}",
        asset,
        re.DOTALL,
    )

    assert surface_rule is not None
    for declaration in (
        "background: var(--ha-card-background, var(--card-background-color));",
        "border: var(--ha-card-border-width, 1px) solid",
        "var(--ha-card-border-color, var(--divider-color));",
        "border-radius: var(--ha-card-border-radius, 12px);",
        "box-shadow: var(--ha-card-box-shadow);",
    ):
        assert declaration in surface_rule.group("body")
    assert ".section-surface {\n          padding: 16px;" in asset
    for marker in (
        'class="evidence-section evidence-meta summary section-surface"',
        'class="evidence-section comparison section-surface"',
        'class="section-surface" data-evidence-graph',
        'class="evidence-section response-section section-surface"',
        'class="evidence-section disclosure section-surface" data-evidence-technical',
        'class="workspace-summary section-surface"',
        'class="workspace-section nilm-graph-section section-surface"',
        'class="workspace-section nilm-interval-editor-section section-surface"',
        'class="nilm-review-list section-surface"',
        'class="nilm-review-inspector section-surface"',
        'class="workspace-section section-surface" data-nilm-secondary-collections',
    ):
        assert marker in asset
    assert (
        'class="evidence-section evidence-investigation section-surface"' not in asset
    )
    assert 'class="nilm-review-layout section-surface"' not in asset


def test_alert_evidence_render_contracts() -> None:
    _run_panel_node_script(
        """
(async () => {
  let name = "";
  try {
    name = "test_alert_evidence_renders_visual_comparison_before_graph_and_details";
    {
      const panel = makePanel({ _payload: { actions: {} } });
      const html = panel._renderAlertContent({
        circuit_id: "fridge",
        feature: "daily_energy",
        feature_name: "Daily Energy",
        observed_value: 6.2,
        expected_value: 3.8,
        threshold: 5,
        what_happened: "Energy increased above the learned range.",
        why_it_matters: "The refrigerator is using more energy than usual.",
        what_to_check_first: "Check the door seal.",
        graph_entities: [],
      }, { name: "Kitchen Refrigerator" });
      const positions = [
        html.indexOf('data-evidence-comparison="visual"'),
        html.indexOf("data-evidence-graph"),
        html.indexOf("data-evidence-explanation"),
        html.indexOf("data-evidence-technical"),
      ];
      assert.ok(positions.every((position) => position >= 0));
      assert.ok(positions.every((position, index) => !index || positions[index - 1] < position));
      for (const marker of ["observed", "expected", "threshold"]) {
        assert.ok(html.includes(`data-comparison-marker="${marker}"`));
      }
    }

    name = "test_alert_route_never_loads_or_renders_nilm_and_response_precedes_details";
    {
      const requests = [];
      context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
      context.window.location.search = "?alert_id=alert-1";
      const panel = makePanel();
      panel._render = () => {};
      panel._requestJson = async (apiPath, fetchPath) => {
        requests.push({ apiPath, fetchPath });
        return {
          status: "matched_alert",
          circuit: { circuit_id: "mains", name: "Whole Home" },
          alert: {
            alert_id: "alert-1",
            circuit_id: "mains",
            feature: "daily_energy",
            feature_name: "Daily Energy",
            observed_value: 18.2,
            expected_value: 12,
            threshold: 16,
            repeated_count: 2,
            graph_entities: [],
            what_happened: "Energy increased.",
            why_it_matters: "The change is worth reviewing.",
            what_to_check_first: "Check recent loads.",
          },
          nilm: {
            workspace_call_api_path: "circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains",
            workspace_api_path: "/api/circuitsetup_energy_analyzer/nilm_workspace?circuit_id=mains",
          },
          actions: { acknowledge: makeAction("acknowledge_alert") },
        };
      };
      await panel._loadEvidence({ routeKey: panel._routeKey() });
      assert.equal(requests.length, 1);
      assert.match(requests[0].apiPath, /^circuitsetup_energy_analyzer\\/alert_evidence/);
      assert.equal(panel._nilmWorkspace, null);
      panel._nilmWorkspace = makeWorkspace();
      const html = panel._renderAlertContent(panel._payload.alert, panel._payload.circuit);
      for (const forbidden of ["NILM Workspace", "workspace-summary", "nilm-review-layout"]) {
        assert.ok(!html.includes(forbidden), forbidden);
      }
      const explanation = html.indexOf("data-evidence-explanation");
      const response = html.indexOf("response-section");
      const technical = html.indexOf("data-evidence-technical");
      assert.ok(explanation >= 0 && explanation < response && response < technical);
    }

    name = "test_alert_evidence_header_shows_latest_evidence_timestamp";
    {
      const panel = makePanel({
        _loading: false,
        _payload: {
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
        },
      });
      panel.shadowRoot = {
        innerHTML: "",
        querySelector() { return null; },
        querySelectorAll() { return []; },
      };
      panel._render();
      const start = panel.shadowRoot.innerHTML.indexOf('<header class="page-header">');
      const header = panel.shadowRoot.innerHTML.slice(
        start,
        panel.shadowRoot.innerHTML.indexOf("</header>", start),
      );
      assert.ok(header.includes("Last Seen"));
      assert.ok(header.includes("2026-07-09"));
    }

    name = "test_alert_evidence_comparison_falls_back_for_incomplete_metrics";
    {
      const html = makePanel()._renderAlertComparison({ observed_value: 620 });
      assert.ok(html.includes('data-evidence-comparison="fallback"'));
      assert.ok(!html.includes('role="img"'));
    }

    name = "test_alert_evidence_labels_and_formats_metric_values";
    {
      const panel = makePanel({ _payload: { actions: {} } });
      const ratioAlert = {
        circuit_id: "oven",
        feature: "resistive_load_became_reactive",
        value_label: "Reactive-to-real power ratio",
        value_unit: "%",
        value_format: "percentage",
        observed_value: 0.14248837235748318,
        baseline_value: 0.10285714285714286,
        expected_value: 0.10285714285714286,
        graph_entities: [],
      };
      const comparison = panel._renderAlertComparison(ratioAlert);
      for (const expected of [
        '<p class="comparison-metric">Reactive-to-real power ratio</p>',
        "<span>Observed</span>",
        "14.249%",
        "<span>Expected</span>",
        "10.286%",
      ]) assert.ok(comparison.includes(expected), expected);

      const content = panel._renderAlertContent(ratioAlert, { name: "Oven" });
      assert.ok(content.includes("Baseline Reactive-to-real power ratio"));
      assert.ok(content.includes("10.286%"));

      for (const [alert, value, expected] of [
        [{ value_format: "decimal", value_unit: "" }, 0.9874, "0.987"],
        [{ value_format: "number", value_unit: "W" }, 120, "120 W"],
        [{ value_format: "number", value_unit: "VAR" }, 42, "42 VAR"],
        [{ value_format: "number", value_unit: "VA" }, 128, "128 VA"],
        [{ value_label: "Real power", value_format: "number", value_unit: "" }, 120, "120"],
        [{ value_label: "Runtime today", value_format: "number", value_unit: "" }, 42, "42"],
      ]) assert.equal(panel._formatAlertMetricValue(alert, value), expected);
    }

    name = "test_alert_evidence_comparison_accessible_name_includes_threshold";
    {
      const panel = makePanel();
      const rows = [
        {
          alert: { observed_value: 6.2, expected_value: 3.8, threshold: 5 },
          label: 'aria-label="Observed 6.2; expected 3.8; threshold 5; change +63.16%."',
          hasThreshold: true,
        },
        {
          alert: { observed_value: 6.2, expected_value: 3.8 },
          label: 'aria-label="Observed 6.2; expected 3.8; change +63.16%."',
          hasThreshold: false,
        },
      ];
      for (const row of rows) {
        const html = panel._renderAlertComparison(row.alert);
        assert.ok(html.includes(row.label));
        assert.equal(html.includes("threshold"), row.hasThreshold);
      }
    }

    name = "test_alert_evidence_comparison_marker_positions_are_finite_and_bounded";
    {
      const panel = makePanel();
      const scales = [
        panel._alertComparisonScale({ observed_value: 6.2, expected_value: 3.8, threshold: 5 }),
        panel._alertComparisonScale({ observed_value: 5, expected_value: 5, threshold: 5 }),
      ];
      for (const scale of scales) {
        assert.equal(scale.markers.length, 3);
        for (const marker of scale.markers) {
          assert.ok(Number.isFinite(marker.position));
          assert.ok(marker.position >= 0 && marker.position <= 100);
        }
      }
      assert.ok(scales[1].markers.every((marker) => marker.position === 50));
    }

    name = "test_alert_comparison_shows_and_announces_percent_change";
    {
      const panel = makePanel();
      const increased = panel._renderAlertComparison({
        observed_value: 150,
        expected_value: 100,
        threshold: 125,
      });
      for (const expected of [
        'data-comparison-change="50"',
        "Change",
        "+50%",
        "change +50%",
      ]) {
        assert.ok(increased.includes(expected));
      }
      for (const alert of [
        { observed_value: 10, expected_value: 0 },
        { observed_value: "not-a-number", expected_value: 5 },
      ]) {
        const fallback = panel._renderAlertComparison(alert);
        assert.ok(fallback.includes('data-comparison-change="unavailable"'));
        assert.ok(fallback.includes("Change"));
        assert.ok(fallback.includes("Unavailable"));
        assert.doesNotMatch(fallback, /NaN%|Infinity%/);
      }
    }
  } catch (error) {
    console.error(name, error);
    throw error;
  }
})();
"""
    )


def test_dynamic_alert_evidence_panel_formats_iso_offsets_as_local_time() -> None:
    asset = _frontend_source()

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
if (!requests[0] || !/hours=1/.test(requests[0].apiPath)) {
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


def test_nilm_graph_focuses_one_occurrence_and_navigates_previous_next() -> None:
    _run_panel_node_script(
        """
(async () => {
const panel = new context.Panel();
panel._render = () => {};
panel._requestJson = async () => [];
panel._nilmWorkspace = {
  status: "ok",
  history: {
    start: "2026-08-04T00:00:00Z", end: "2026-08-04T04:00:00Z",
    max_hours: 24,
    api_path: "circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=4",
    fetch_path: "/api/circuitsetup_energy_analyzer/nilm_workspace_history?circuit_id=mains&hours=4",
  },
  sessions: [
    { session_id: "older", signature_fingerprint: "blower",
      start: "2026-08-04T01:00:00Z", end: "2026-08-04T01:05:00Z",
      duration_seconds: 300, on_delta_w: 319, off_delta_w: -319 },
    { session_id: "newer", signature_fingerprint: "blower",
      start: "2026-08-04T03:00:00Z", end: "2026-08-04T03:10:00Z",
      duration_seconds: 600, on_delta_w: 319, off_delta_w: -319 },
    { session_id: "other", signature_fingerprint: "pump",
      start: "2026-08-04T02:00:00Z", end: "2026-08-04T02:02:00Z" },
  ],
  edges: [],
};
await panel._focusNilmSignatureOnGraph("blower", { scroll: false, toggle: false });
assert.equal(panel._nilmFocusedOccurrence().session_id, "newer");
let evidence = panel._nilmFocusedGraphEvidence(panel._nilmWorkspace);
assert.equal(evidence.sessions.length, 1);
assert.equal(evidence.sessions[0].selected, true);
assert.equal(
  JSON.stringify(evidence.edges.map((edge) => [edge.direction, edge.timestamp])),
  JSON.stringify([["on", "2026-08-04T03:00:00Z"], ["off", "2026-08-04T03:10:00Z"]]),
);
let html = panel._renderNilmOccurrenceControls();
assert.ok(html.includes("data-nilm-occurrence-step=\\\"-1\\\""));
assert.ok(html.includes("data-nilm-occurrence-step=\\\"1\\\" disabled"));
assert.match(html, /10m|10 min|10 minutes/);

await panel._stepNilmOccurrence(-1);
assert.equal(panel._nilmFocusedOccurrence().session_id, "older");
evidence = panel._nilmFocusedGraphEvidence(panel._nilmWorkspace);
assert.equal(evidence.sessions[0].session_id, "older");
html = panel._renderNilmOccurrenceControls();
assert.ok(html.includes("data-nilm-occurrence-step=\\\"-1\\\" disabled"));
assert.ok(html.includes("data-nilm-occurrence-step=\\\"1\\\""));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


def test_nilm_graph_has_no_detection_annotations_until_selected() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  sessions: [{ session_id: "raw", start: "2026-08-04T01:00:00Z",
    end: "2026-08-04T01:05:00Z" }],
  edges: [{ timestamp: "2026-08-04T01:00:00Z", direction: "on", delta_w: 300 }],
};
const evidence = panel._nilmFocusedGraphEvidence(panel._nilmWorkspace);
assert.equal(evidence.sessions.length, 0);
assert.equal(evidence.edges.length, 0);
"""
    )


def test_nilm_assignment_review_card_focuses_its_component_signature() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderNilmReviewCard({
  kind: "assignment",
  item: {
    assignment_id: "assignment-pump",
    display_name: "Pump",
    signature_fingerprints: ["component-fingerprint"],
  },
  index: 0,
}, [], false);
assert.match(html, /data-nilm-signature-fingerprint="component-fingerprint"/);
"""
    )


def test_nilm_assignment_review_card_focuses_a_signature_with_an_occurrence() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
panel._nilmWorkspace = {
  sessions: [{
    signature_fingerprint: "current-component",
    start: "2026-08-04T01:00:00Z",
    end: "2026-08-04T01:05:00Z",
  }],
};
const html = panel._renderNilmReviewCard({
  kind: "assignment",
  item: {
    assignment_id: "assignment-pump",
    display_name: "Pump",
    signature_fingerprints: ["stale-component", "current-component"],
  },
  index: 0,
}, [], false);
assert.match(html, /data-nilm-signature-fingerprint="current-component"/);
"""
    )


def test_nilm_configured_primary_assignment_renders_confirmation_action() -> None:
    _run_panel_node_script(
        """
const panel = new context.Panel();
const html = panel._renderNilmAssignmentActions({
  assignment_id: "hvac_1-configured-primary",
  actions: {
    confirm_primary: {
      domain: "circuitsetup_energy_analyzer",
      service: "confirm_nilm_configured_primary",
      data: { circuit_id: "hvac_1", assignment_id: "hvac_1-configured-primary" },
    },
  },
}, 0);
assert.match(html, /data-nilm-assignment-action="confirm_primary"/);
assert.match(html, /Confirm primary appliance/);
"""
    )


def test_nilm_appliance_detail_omits_self_link_and_circuit_recommendations() -> None:
    _run_panel_node_script(
        """
context.window.location.pathname = "/circuitsetup-energy-analyzer-evidence";
context.window.location.search = "?circuit_id=hvac_2&alert_id=alert-1&assignment_id=pump&appliance_detail=1";
const panel = new context.Panel();
const currentPath = `${context.window.location.pathname}${context.window.location.search}`;
let html = panel._renderApplianceAlerts([{
  message: "Pump finished",
  evidence_path: currentPath,
}]);
assert.ok(!html.includes("Open Evidence"));
html = panel._renderApplianceAlerts([{
  message: "Other evidence",
  evidence_path: "/circuitsetup-energy-analyzer-evidence?alert_id=alert-2",
}]);
assert.ok(html.includes("Open Evidence"));

panel._renderApplianceDetail = () => "<section>Assignment detail</section>";
panel._payload = { setting_recommendations: [{
  status: "applied",
  display_label: "HVAC 2 circuit setting",
}]} ;
panel._applianceDetail = { requested_assignment_id: "pump" };
html = panel._renderApplianceDetailBody();
assert.ok(!html.includes("Applied Suggested Settings"));
assert.ok(!html.includes("HVAC 2 circuit setting"));
panel._applianceDetail = { requested_assignment_id: null };
assert.ok(panel._renderApplianceDetailBody().includes("Applied Suggested Settings"));
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
  const item = panel._nilmWorkspace.assignments[0];
  panel._nilmAssignmentDrafts.clear();
  const clean = panel._renderNilmAssignmentActions(item, 0);
  if (!clean.includes(">Save</button>") || !clean.includes("disabled")
      || !clean.includes('data-nilm-assignment-action="merge"')) {
    throw new Error("clean assignment actions did not keep Save neutral and Merge separate");
  }
  panel._nilmAssignmentDrafts.set("assignment-source:label", "Dishwasher Prime");
  const dirty = panel._renderNilmAssignmentActions(item, 0);
  const save = dirty.match(/<button[^>]+data-nilm-assignment-action="save"[^>]*>/)[0];
  if (save.includes("secondary") || save.includes("disabled")) {
    throw new Error("changed assignment did not activate the primary Save action");
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
        "mark_alert_confirmed",
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
        assert (
            "exactly one pending recommendation" in fields["entity_id"]["description"]
        )


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


def test_readme_describes_native_dashboard_and_detail_ui() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (
        "Home Assistant's stock header and icon tabs",
        "Home energy summary on the left and Appliances on the right",
        "Line voltage",
        "floating date",
        "VA and VAR are omitted from Appliance Detail graphs",
    ):
        assert text in readme_text

    assert "House power flow is shown" not in readme_text
    assert "a restore icon resets an individual graph" not in readme_text


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


def test_stale_source_repair_description_names_the_source_entity() -> None:
    description = _translations()["issues"]["stale_source_sensor"]["description"]

    assert "{source_entities}" in description


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
        "Activity Summary state or its `is_running` attribute",
        "status_explanation",
    ):
        assert phrase in normalized_text
    assert "Most options are set from Home Assistant Developer Tools > Actions" not in (
        readme_text
    )


def test_readme_documents_assignment_defaults() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "choose the appliance type, circuit mode, power-flow mode" not in readme_text
    for expected in (
        "integration suggests an appliance type",
        "Home Assistant friendly name as a",
        "fallback. You confirm the appliance type and source sensors",
        "derives circuit mode and power-flow mode",
        "| Profile | Default phase/topology | Default power flow |",
        "| `refrigerator` | Single phase | Load |",
        "| `dishwasher` | Single phase | Load |",
        "| `3d_printer` | Single phase | Load |",
        "| `hvac` | Dual phase when both legs are selected; "
        "otherwise single phase | Load |",
        "| `mini_split` | Dual phase when both legs are selected; "
        "otherwise single phase | Load |",
        "| `solar_inverter` | Dual phase | Generation |",
        "| `mains_nilm` | Mains NILM | Mains/net |",
        "| `mixed` | Mixed | Load |",
    ):
        assert expected in readme_text
    normalized_readme = " ".join(readme_text.split())
    assert (
        "Water-flow correlation applies to `water_pump`, `well_pump`, "
        "`water_heater`, `washer`, and `dishwasher` circuits" in normalized_readme
    )
    assert (
        "Automatic source parsing treats explicit `gas_dryer` names as single "
        "phase and explicit `electric_dryer` names as dual phase." in normalized_readme
    )
    assert (
        "This context applies only to HVAC, HVAC compressor, HVAC blower, "
        "Mini-Split, and electric heat profiles." in normalized_readme
    )
    assert (
        "Mini-Split inverter operation can remain at low power; tune the "
        "default `100 W` on and `40 W` off thresholds in Advanced Circuit "
        "Settings when equipment or metering differs." in normalized_readme
    )


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
    assert (
        "link directly to **Review Suggested Settings** in the evidence panel"
        in readme_text
    )
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
    assert "Energy Usage Today" in readme_text
    assert "Daily Energy Usage" not in readme_text
    assert "sensor.<circuit>_daily_energy_usage" in readme_text
    assert "Average kWh per Day" in readme_text
    assert "Average Cost per Day" in readme_text
    assert "effective main-analyzer rate" in readme_text
    assert "configured default/base rate" in readme_text
    assert "last known valid Opower-derived rate" in readme_text
    assert "whole-day cost estimates stay unavailable" in readme_text
    assert "up to seven completed days" in readme_text
    assert "up to 30 completed days" in readme_text
    assert "Energy Usage Today can show 0 kWh for two different reasons" in readme_text
    assert "Waiting For Energy Change" in readme_text
    assert "waiting_for_delta" in readme_text
    assert "true zero usage" in readme_text
    assert "automatic watt-to-kWh helper" in readme_text


def test_readme_explains_generated_dashboard_controls() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "generated dashboard uses Home Assistant's current entity registry IDs" in (
        readme_text
    )
    assert "renamed analyzer entities are respected" in readme_text
    assert "Home, Energy & Costs, and Insights" in readme_text
    assert "Expert-only diagnostics" in readme_text
    assert "live-sorts appliance tiles" in readme_text
    assert "built from each appliance's Activity Summary history" in readme_text
    assert "keeps graphs half-width on the left" in readme_text
    assert "HVAC overlays outdoor temperature on a second axis" in readme_text
    assert "Water flow context overlays correlated appliance power" in readme_text
    assert (
        "daily averages on a second line without percentage comparisons" in readme_text
    )
    assert "shared Home Assistant-style date range control" in readme_text
    assert (
        "combining both phases of a dual-phase appliance into one line" in readme_text
    )
    assert "previous, next, now, compare, and CSV download actions" in readme_text
    assert "without repeating a separate Active Now list" in readme_text
    assert "segmented Running intervals against the selected range" in readme_text
    assert "no visible chart-level zoom, pan, or reset controls" in readme_text
    assert "Detail links open appliance detail pages directly" in readme_text
    assert "Billing Cycle card lives on the final Insights tab" in readme_text
    assert "recorded, estimated, or unavailable cost status" in readme_text
    assert "first configured mains circuit is the primary whole-house source" in (
        readme_text
    )
    assert "require no third-party Lovelace dependency" in readme_text
    assert "Create Or Update Dashboard" in readme_text
    assert "Match Entity Detail Level To Layout" in readme_text
    assert "Remove Existing Dashboard" in readme_text
    assert "dashboard action still runs from Configure" in readme_text
    assert "**Standard**: Simple plus one Insights view" in readme_text
    assert "**Expert**: Standard plus diagnostic navigation" in readme_text
    assert "button.circuitsetup_energy_analyzer_create_dashboard" not in readme_text
    assert "adds small action cards" not in readme_text


def test_readme_documents_current_compact_entity_model() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Compact entity model" in readme_text
    assert "docs/entity-model.md" in readme_text
    assert "`switch.<circuit>_maintenance`" in readme_text
    assert "`button.<circuit>_start_maintenance`" not in readme_text
    assert "`button.<circuit>_end_maintenance`" not in readme_text
    assert "`button.<circuit>_pause_alerts`" not in readme_text
    assert "`sensor.<circuit>_sensitivity`" not in readme_text
    assert "`sensor.<circuit>_standby_threshold`" not in readme_text
    assert "sensor.<circuit>_health_summary" in readme_text


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
        "| Activity Summary | `sensor.<circuit>_activity_summary` |",
    ):
        assert row in readme_text
    assert "`binary_sensor.<circuit>_running`" not in readme_text
    assert "`sensor.<circuit>_electrical_health`" not in readme_text
    assert "- Energy (`sensor.<appliance>_energy`)" not in readme_text
    assert "- Health Summary:" not in readme_text
    assert "Known Load Share" in readme_text
    assert "`sensor.<circuit>_nilm_signature_count`" in readme_text
    assert "`sensor.<circuit>_nilm_discovered_signatures`" not in readme_text
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


def test_nilm_helper_review_text_and_controls_are_user_facing() -> None:
    translations = json.loads(
        Path(
            "custom_components/circuitsetup_energy_analyzer/translations/en.json"
        ).read_text(encoding="utf-8")
    )["config_panel"]["panel"]["nilm_workspace"]

    assert translations["helper_matched_starts"] == (
        "Matched {matched} of {total} {name} starts"
    )
    assert translations["helper_start_delay"] == (
        "Typical start delay {seconds} seconds"
    )
    assert translations["helper_relationship_corroborates"] == (
        "Runs with this load (evidence only)"
    )
    assert translations["helper_relationship_direct_component"] == (
        "Directly measures this load (included in source)"
    )

    script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/"
        "energy-analyzer-nilm-workspace.js"
    ).read_text(encoding="utf-8")
    assert 'aria-pressed="${selected}"' in script
    assert "data-nilm-helper-circuit-id=" in script
    assert 'searchParams.append("helper_circuit_id"' in script
    assert "evidence.actions && evidence.actions.set" in script
    assert "evidence.actions && evidence.actions.remove" in script
    assert "set_nilm_helper_link" not in script
    assert "remove_nilm_helper_link" not in script


def test_readme_describes_current_nilm_workspace_flow() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    for expected in (
        "review recurring loads, assign or identify them",
        "validate completed sessions or link reference sensors, and publish only "
        "when the estimate is trustworthy",
        "The graph shows measured source power; separated appliance power and "
        "energy are estimates. Open sessions are provisional, and uncertain or "
        "unexplained power remains unassigned.",
        "Pure mixed and primary appliance plus mixed loads sources do not "
        "process known loads.",
        "Known-load masking is applied only to mains sources, as are Known Load Overlays.",
        "they do not become component owners or subtraction meters.",
        "Editing either time or dragging or keyboard-moving a graph boundary "
        "updates the same unsaved interval; Save is the only action that persists it.",
        "Adjust Interval loads the saved interval into the graph.",
        "focuses its newest trustworthy completed session, then falls back to "
        "its newest saved labeled interval.",
        "An explicitly linked state sensor may still be authoritative for on/off "
        "state; measured power remains validation evidence.",
    ):
        assert expected in readme_text

    for expected in (
        "NILM workspace can also pair compatible on/off edges",
        "Review NILM Assignments",
        "Mains & NILM",
        "drag across the graph to select one or more appliance intervals",
        "Label appliance interval",
        "highlights the active graph selection and matching time fields",
        "sends the saved evidence directly to Needs Review",
        "false-positive and false-negative rates",
        "The workspace groups work into five lanes",
        "Needs Review, Assigned, Published, Expected, and Removed",
        "dynamic dashboard NILM card can show the same lane counts "
        "when it is available",
        "Published NILM appliances are marked as estimated",
        "Remove HA Device",
        "NILM estimates are inferred from aggregate power and are not safety evidence",
        "`assign_session_to_appliance`",
        "`publish_nilm_appliance_assignment`",
    ):
        assert expected in readme_text


def test_nilm_workspace_source_picker_renders_and_navigates_only_for_multiple_sources() -> (
    None
):
    _run_panel_node_script(
        r"""
const panel = new context.Panel();
const summary = (sources) => panel._renderNilmWorkspaceSummary({
  circuit: { circuit_id: "mains", name: "Mains" },
  sources,
  lanes: {},
  lane_counts: {},
});
if (summary([]).includes("data-nilm-source-picker")
    || summary([{ circuit_id: "mains", name: "Mains", path: "/nilm?entry_id=one&circuit_id=mains" }]).includes("data-nilm-source-picker")) {
  throw new Error("zero and one source must not render a picker");
}
const path = "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&entry_id=entry-2&circuit_id=mixed";
const html = summary([
  { circuit_id: "mains", name: "Mains", path: "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&entry_id=entry-1&circuit_id=mains" },
  { circuit_id: "mixed", name: "Mixed", path },
]);
if (!html.includes("data-nilm-source-picker") || !html.includes(`value="${path.replaceAll("&", "&amp;")}"`)) {
  throw new Error("multiple sources must render backend paths in the picker");
}
let changed;
const select = { value: path, addEventListener(_event, callback) { changed = callback; } };
let navigated = "";
panel._navigate = (value) => { navigated = value; };
panel.shadowRoot = {
  innerHTML: "",
  querySelectorAll(selector) { return selector === "[data-nilm-source-picker]" ? [select] : []; },
  querySelector() { return null; },
};
panel._attachChartInspectors = () => {};
panel._listen = () => {};
panel._renderNilmWorkspaceBody = () => "";
panel._routeRequestsNilmWorkspace = () => false;
panel._renderEvidenceBody = () => "";
panel._renderActionConfirmation = () => "";
panel._render();
changed();
if (navigated !== path) throw new Error(`picker did not navigate to backend path: ${navigated}`);
"""
    )


def test_evidence_views_render_and_navigate_load_separation_action() -> None:
    _run_panel_node_script(
        r"""
const path = "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&entry_id=entry-1&circuit_id=mixed";
const panel = makePanel({
  _payload: { actions: { open_load_separation: { type: "navigate", path } } },
});
const alertHtml = panel._renderAlertContent(
  { circuit_id: "mixed", feature: "daily_energy", graph_entities: [] },
  { name: "Mixed Loads" },
);
const fallbackHtml = panel._renderFallbackActionsContent();
for (const html of [alertHtml, fallbackHtml]) {
  if (!html.includes('id="open_load_separation"')) {
    throw new Error("Load Separation action missing from an evidence action list");
  }
}
let navigated = "";
panel._navigate = (value) => { navigated = value; };
let click;
const button = { addEventListener(_event, callback) { click = callback; } };
panel.shadowRoot = {
  innerHTML: "",
  querySelector(selector) { return selector === "#open_load_separation" ? button : null; },
  querySelectorAll() { return []; },
};
panel._attachChartInspectors = () => {};
panel._renderEvidenceBody = () => "";
panel._renderActionConfirmation = () => "";
panel._render();
click();
if (navigated !== path) throw new Error(`Load Separation action did not navigate: ${navigated}`);
"""
    )


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
        "apparent power, or power factor" in readme_text
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
        assert not (width >= 1800 and height >= 1000), (
            f"{ref} looks like a full-screen capture rather than a cropped UI panel"
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


def _dashboard_views(dashboard: object) -> list[dict[str, object]]:
    if not isinstance(dashboard, dict):
        return []
    views = dashboard.get("views")
    if isinstance(views, list):
        return [view for view in views if isinstance(view, dict)]
    return [dashboard]


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
