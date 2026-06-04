from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / "circuitsetup_energy_analyzer"


EXPECTED_FLOW_LABELS = {
    "source_entities": "Source Entities",
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_OPTIONS_LABELS = {
    "source_entities": "Source Entities",
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
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
    "max_active_minutes": "Max Active Minutes",
    "max_idle_minutes": "Max Idle Minutes",
    "measured_energy_entities": "Measured Energy Entities",
    "note": "Note",
    "preset": "Preset",
    "relearn": "Relearn",
    "relearn_on_end": "Relearn On End",
    "signature_id": "Signature ID",
    "source_signature_id": "Source Signature ID",
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
    assert all(20 <= len(description) <= 160 for description in descriptions.values())
    assert "power, voltage, current" in descriptions["source_entities"].lower()
    assert "power factor" in descriptions["source_entities"].lower()
    assert "optional" in descriptions["mains_source_entities"].lower()


def test_options_flow_labels_are_human_readable_and_described() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    data = strings["options"]["step"]["init"]["data"]
    descriptions = strings["options"]["step"]["init"]["data_description"]

    assert data == EXPECTED_OPTIONS_LABELS
    assert descriptions.keys() == EXPECTED_OPTIONS_LABELS.keys()
    assert all("_" not in label for label in data.values())
    assert all(description.endswith(".") for description in descriptions.values())
    assert all(20 <= len(description) <= 160 for description in descriptions.values())
    assert "optional" in descriptions["mains_source_entities"].lower()


def test_runtime_english_translations_include_setup_and_options_text() -> None:
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    translations = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text()
    )

    for section, step in (("config", "user"), ("options", "init")):
        strings_step = strings[section]["step"][step]
        translated_step = translations[section]["step"][step]
        assert translated_step["data"] == strings_step["data"]
        assert translated_step["data_description"] == strings_step["data_description"]
        assert translated_step["title"] == strings_step["title"]
        assert translated_step["description"] == strings_step["description"]


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
