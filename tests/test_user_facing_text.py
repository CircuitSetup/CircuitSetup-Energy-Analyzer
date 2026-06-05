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
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_OPTIONS_LABELS = {
    "source_devices": "Source Devices",
    "extra_source_entities": "Extra Source Entities",
    "enable_experimental_nilm": "Enable Experimental NILM",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_MAINS_LABELS = {
    "mains_source_entities": "Mains Source Entities",
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

EXPECTED_ADVANCED_SETTINGS_LABELS = {
    "preset": "Sensitivity",
    "window_days": "Energy Window Days",
    "daily_spike_ratio": "Daily Spike Ratio",
    "daily_goal_kwh": "Daily Goal kWh",
    "goal_alert_ratio": "Goal Alert Ratio",
    "max_active_minutes": "Max Active Minutes",
    "max_idle_minutes": "Max Idle Minutes",
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
    "window_minutes": "Demand Window Minutes",
    "demand_limit_w": "Demand Limit W",
    "breaker_amps": "Breaker Amps",
    "warning_ratio": "Capacity Warning Ratio",
    "window_hours": "Standby Window Hours",
    "standby_threshold_w": "Standby Threshold W",
    "always_on_alert_w": "Always On Alert W",
    "standby_min_samples": "Standby Minimum Samples",
    "leg_imbalance_warning_ratio": "Leg Imbalance Warning Ratio",
    "leg_imbalance_min_total_power_w": "Leg Imbalance Minimum Total Power W",
    "apparent_power_tolerance_percent": "Apparent Power Tolerance Percent",
    "power_factor_tolerance": "Power Factor Tolerance",
    "minimum_apparent_power_va": "Minimum Apparent Power VA",
    "balance_negative_tolerance_w": "Balance Negative Tolerance W",
    "solar_export_tolerance_w": "Solar Export Tolerance W",
    "solar_surplus_threshold_w": "Solar Surplus Threshold W",
    "high_solar_surplus_threshold_w": "High Solar Surplus Threshold W",
    "flexible_load_running_threshold_w": "Flexible Load Running Threshold W",
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
    "goal_alert_ratio": "Goal Alert Ratio",
    "label": "Label",
    "apparent_power_tolerance_percent": "Apparent Power Tolerance Percent",
    "export_tolerance_w": "Export Tolerance W",
    "flexible_load_running_threshold_w": "Flexible Load Running Threshold W",
    "high_solar_surplus_threshold_w": "High Solar Surplus Threshold W",
    "minimum_apparent_power_va": "Minimum Apparent Power VA",
    "minimum_total_power_w": "Minimum Total Power W",
    "max_active_minutes": "Max Active Minutes",
    "max_idle_minutes": "Max Idle Minutes",
    "measured_energy_entities": "Measured Energy Entities",
    "negative_tolerance_w": "Negative Tolerance W",
    "note": "Note",
    "power_factor_tolerance": "Power Factor Tolerance",
    "preset": "Preset",
    "relearn": "Relearn",
    "relearn_on_end": "Relearn On End",
    "signature_id": "Signature ID",
    "source_signature_id": "Source Signature ID",
    "solar_surplus_threshold_w": "Solar Surplus Threshold W",
    "standby_threshold_w": "Standby Threshold W",
    "target_signature_id": "Target Signature ID",
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
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
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
    assert "quieter" in descriptions["sensitivity"].lower()
    assert "more responsive" in descriptions["sensitivity"].lower()
    assert "storage" in descriptions["retention_mode"].lower()
    assert "diagnostic evidence" in descriptions["retention_mode"].lower()
    assert "review circuit assignments" in strings["config"]["step"]["user"][
        "description"
    ].lower()


def test_options_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    init_step = strings["options"]["step"]["init"]
    data = strings["options"]["step"]["sources"]["data"]
    descriptions = strings["options"]["step"]["sources"]["data_description"]

    assert init_step["menu_options"] == {
        "assign": "Review Circuit Assignments",
        "sources": "Edit Source Selection",
        "mains": "Edit Mains Sensors",
        "nilm": "Experimental NILM Settings",
        "utility": "Utility / Opower Comparison",
        "advanced": "Advanced Circuit Settings",
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
    assert "quieter" in descriptions["sensitivity"].lower()
    assert "more responsive" in descriptions["sensitivity"].lower()
    assert "storage" in descriptions["retention_mode"].lower()
    assert "diagnostic evidence" in descriptions["retention_mode"].lower()
    assert "review circuit assignments" in strings["options"]["step"]["sources"][
        "description"
    ].lower()


def test_mains_and_utility_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())

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
    assert "optional" in mains_descriptions["mains_source_entities"].lower()
    assert "mains nilm" in mains_descriptions["mains_source_entities"].lower()


def test_advanced_settings_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    picker_step = strings["options"]["step"]["select_advanced_circuit"]
    settings_step = strings["options"]["step"]["advanced_settings"]

    assert picker_step["data"] == EXPECTED_ADVANCED_CIRCUIT_LABELS
    assert picker_step["data_description"].keys() == (
        EXPECTED_ADVANCED_CIRCUIT_LABELS.keys()
    )
    assert settings_step["data"] == EXPECTED_ADVANCED_SETTINGS_LABELS
    assert settings_step["data_description"].keys() == (
        EXPECTED_ADVANCED_SETTINGS_LABELS.keys()
    )
    assert all("_" not in label for label in settings_step["data"].values())
    assert "service" not in settings_step["description"].lower()
    assert "billing" in settings_step["description"].lower()
    assert "standby" in settings_step["description"].lower()


def test_assignment_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())

    for section in ("config", "options"):
        data = strings[section]["step"]["assign"]["data"]
        descriptions = strings[section]["step"]["assign"]["data_description"]
        assert data == {
            "include_circuit": "Include Circuit",
            "included_sensors": "Included Sensors",
            "circuit_name": "Circuit Name",
            "appliance_profile": "Appliance Type",
            "circuit_mode": "Circuit Mode",
            "power_flow": "Power Flow",
            "circuit_retention_mode": "Circuit Retention",
        }
        assert descriptions.keys() == data.keys()
        assert all("_" not in label for label in data.values())
        assert all(description.endswith(".") for description in descriptions.values())
        assert "appliance" in descriptions["appliance_profile"].lower()
        assert "selected sensors" in descriptions["include_circuit"].lower()
        assert "unchecked" in descriptions["included_sensors"].lower()
        assert "mains nilm" in descriptions["circuit_mode"].lower()
        assert "only" in descriptions["circuit_mode"].lower()
        assert "mains" in descriptions["circuit_mode"].lower()
        assert "solar" in descriptions["power_flow"].lower()
        assert "diagnostic history" in descriptions["circuit_retention_mode"].lower()


def test_assignment_picker_text_is_human_readable() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())

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


def test_runtime_english_translations_include_setup_and_options_text() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text()
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

    strings_init = strings["options"]["step"]["init"]
    translated_init = translations["options"]["step"]["init"]
    assert translated_init["title"] == strings_init["title"]
    assert translated_init["description"] == strings_init["description"]
    assert translated_init["menu_options"] == strings_init["menu_options"]


def test_config_flow_descriptions_do_not_show_non_actionable_mapping_suggestions() -> (
    None
):
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text()
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
    assert "glance" in card_types
    assert "history-graph" in card_types
    assert "gauge" in card_types
    assert any(card.get("title") == "At a glance" for card in cards)


def test_dashboard_example_is_appliance_first_and_explains_energy_tracking() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text(
        encoding="utf-8"
    )
    dashboard = yaml.safe_load(dashboard_text)
    section_titles = {
        section.get("title")
        for section in dashboard.get("sections", [])
        if isinstance(section, dict)
    }

    assert {
        "Needs attention",
        "Appliance overview",
        "Energy tracking",
        "Power quality detail",
        "Mains, solar, and NILM",
    } <= section_titles
    assert "Waiting For Energy Change" in dashboard_text
    assert "sensor.hvac_energy_usage_status" in dashboard_text
    assert "sensor.hvac_daily_energy_usage" in dashboard_text
    assert "sensor.hvac_health_summary" in dashboard_text
    assert "sensor.hvac_alert_evidence" in dashboard_text
    assert "sensor.water_heater_energy_usage_status" in dashboard_text
    assert "sensor.mains_nilm_learning_progress" in dashboard_text
    assert "sensor.mains_nilm_anomaly_score" in dashboard_text

    needs_attention = yaml.safe_dump(
        next(
            section
            for section in dashboard["sections"]
            if section.get("title") == "Needs attention"
        )
    )
    assert "possible issue" in needs_attention
    assert "Repairs" in needs_attention

    appliance_overview = yaml.safe_dump(
        next(
            section
            for section in dashboard["sections"]
            if section.get("title") == "Appliance overview"
        )
    )
    for appliance in (
        "Refrigerator",
        "HVAC",
        "Water heater",
        "Pool pump",
        "Washer",
        "Dryer",
    ):
        assert appliance in appliance_overview

    power_quality_detail = yaml.safe_dump(
        next(
            section
            for section in dashboard["sections"]
            if section.get("title") == "Power quality detail"
        )
    )
    assert "sensor.hvac_power_quality_score" in power_quality_detail
    assert "sensor.refrigerator_standby_status" in power_quality_detail


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
    assert "sensor.mains_nilm_health_summary" in dashboard_text
    assert "sensor.mains_nilm_nilm_discovered_signatures" in dashboard_text
    assert "binary_sensor.mains_nilm_maintenance" in dashboard_text


def test_dashboard_example_covers_configurable_analyzer_surfaces() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    refs = set(_dashboard_entity_refs(dashboard_text))

    expected_entities = {
        "sensor.refrigerator_circuit_mode",
        "sensor.refrigerator_power_flow",
        "sensor.refrigerator_energy_usage_status",
        "sensor.refrigerator_energy_goal_status",
        "sensor.hvac_run_cycle_status",
        "sensor.refrigerator_recent_activity",
        "sensor.refrigerator_billing_cycle_status",
        "sensor.refrigerator_cost_status",
        "sensor.hvac_demand_peak_status",
        "sensor.hvac_capacity_status",
        "sensor.hvac_leg_imbalance_status",
        "sensor.hvac_metric_consistency_status",
        "sensor.mains_nilm_balance_status",
        "sensor.mains_nilm_solar_flow_status",
        "sensor.refrigerator_standby_status",
        "sensor.mains_nilm_nilm_topology_status",
    }
    assert expected_entities <= refs
    assert "circuitsetup_energy_analyzer.export_history_csv" in dashboard_text
    assert "Alert philosophy" in dashboard_text
    assert "Notifications and repairs" in dashboard_text


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


def test_readme_includes_status_glossary_for_machine_values() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Status Glossary" in readme_text
    for raw_status in (
        "missing_metrics",
        "not_dual_phase",
        "missing_mains",
        "inconsistent_export",
        "no_match",
        "projected_over_budget",
        "active_solar_supported",
    ):
        assert raw_status in readme_text
    assert "Missing Metrics" in readme_text
    assert "raw_status" in readme_text
    assert "status_explanation" in readme_text


def test_readme_explains_core_dashboard_sensors_and_zero_kwh() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Core Appliance Status Sensors" in readme_text
    assert "Daily Energy Usage can show 0 kWh for two different reasons" in readme_text
    assert "Waiting For Energy Change" in readme_text
    assert "true zero usage" in readme_text
    assert "not observed a cumulative kWh increase" in readme_text


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
        "docs/images/readme/mains-sensors.png",
        "docs/images/readme/advanced-settings.png",
        "docs/images/readme/circuit-modes.png",
        "docs/images/readme/power-flow.png",
        "docs/images/readme/energy-usage-spikes.png",
        "docs/images/readme/daily-energy-goals.png",
        "docs/images/readme/run-cycle-diagnostics.png",
        "docs/images/readme/recent-activity-timeline.png",
        "docs/images/readme/billing-cycle-forecasts.png",
        "docs/images/readme/cost-time-of-use.png",
        "docs/images/readme/history-csv-export.png",
        "docs/images/readme/peak-demand-tracking.png",
        "docs/images/readme/circuit-capacity-tracking.png",
        "docs/images/readme/dual-phase-leg-imbalance.png",
        "docs/images/readme/power-metric-consistency.png",
        "docs/images/readme/mains-balance.png",
        "docs/images/readme/solar-flow-diagnostics.png",
        "docs/images/readme/utility-comparison.png",
        "docs/images/readme/always-on-standby.png",
        "docs/images/readme/experimental-nilm.png",
        "docs/images/readme/alert-philosophy.png",
        "docs/images/readme/notifications-repairs.png",
        "docs/images/readme/demo-dashboard.png",
    }

    assert expected <= set(refs)
    for ref in sorted(set(refs)):
        path = ROOT / ref
        assert path.exists(), f"{ref} is referenced by README but missing"
        width, height = _png_dimensions(path)
        assert width >= 500, f"{ref} is too narrow to show readable UI"
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


def _dashboard_entity_refs(dashboard_text: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(r"entity:\s*([a-z_]+\.[A-Za-z0-9_]+)", dashboard_text)
    ]


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])
