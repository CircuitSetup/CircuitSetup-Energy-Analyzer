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
    "enable_experimental_nilm": "Enable Experimental NILM",
    "mains_source_entities": "Mains Source Entities",
    "sensitivity": "Sensitivity",
    "retention_mode": "Retention Mode",
}

EXPECTED_SERVICE_FIELD_NAMES = {
    "alert_id": "Alert ID",
    "circuit_id": "Circuit ID",
    "daily_spike_ratio": "Daily Spike Ratio",
    "duration": "Duration",
    "label": "Label",
    "note": "Note",
    "preset": "Preset",
    "relearn": "Relearn",
    "relearn_on_end": "Relearn On End",
    "signature_id": "Signature ID",
    "source_signature_id": "Source Signature ID",
    "target_signature_id": "Target Signature ID",
    "window_days": "Window Days",
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


def test_service_fields_have_human_readable_names_and_descriptions() -> None:
    services = yaml.safe_load((INTEGRATION_DIR / "services.yaml").read_text())

    for service in services.values():
        for field_name, field in service.get("fields", {}).items():
            assert field["name"] == EXPECTED_SERVICE_FIELD_NAMES[field_name]
            assert "_" not in field["name"]
            assert field["description"].endswith(".")
            assert 20 <= len(field["description"]) <= 160
