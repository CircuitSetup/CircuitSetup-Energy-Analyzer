from __future__ import annotations

import builtins
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_ENTITY_MODEL_VERSION,
    CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS,
    CONF_SELECTED_ENTITY_GROUPS,
    DOMAIN,
    ENTITY_MODEL_COMPACT,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    BaselineStats,
    CircuitEvent,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


@pytest.mark.asyncio
async def test_diagnostics_redacts_config_values_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    hass = SimpleNamespace(data={DOMAIN: {}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={
            "source_entities": ["sensor.secret_panel_power"],
            "api_token": "super-secret",
        },
        options={
            "mains_source_entities": ["sensor.secret_mains_power"],
            "sensitivity": "high",
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"] == {
        "entry_id": "entry-1",
        "title": "Panel Analyzer",
        "data_keys": ["api_token", "source_entities"],
        "option_keys": ["mains_source_entities", "sensitivity"],
    }
    assert diagnostics["devices"] == []
    assert diagnostics["runtime_loaded"] is False
    assert "super-secret" not in repr(diagnostics)
    assert "sensor.secret_panel_power" not in repr(diagnostics)
    assert "sensor.secret_mains_power" not in repr(diagnostics)


@pytest.mark.asyncio
async def test_diagnostics_reports_runtime_loaded_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    hass = SimpleNamespace(data={DOMAIN: {"entry-1": object()}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={},
        options={},
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["runtime_loaded"] is True


@pytest.mark.asyncio
async def test_diagnostics_includes_redacted_runtime_summaries_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    coordinator = SimpleNamespace(
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
            ],
            baselines={
                "fridge:real_power": BaselineStats(
                    "real_power",
                    20,
                    100.0,
                    5.0,
                    90.0,
                    110.0,
                    1.0,
                )
            },
            alerts=[
                AlertEvidence(
                    timestamp=datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
                    circuit_id="fridge",
                    severity=Severity.WARNING,
                    message="Possible issue: real power changed",
                    feature="real_power",
                )
            ],
            nilm_signatures={"mains": [{"signature_id": "on-1"}]},
        ),
        last_exported_diagnostics={
            "circuit_id": "fridge",
            "anomaly_score": 0.42,
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={"source_entities": ["sensor.secret_panel_power"]},
        options={},
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["runtime"] == {
        "events": {"count": 1, "by_circuit": {"fridge": 1}},
        "baselines": {"count": 1, "features": {"fridge": ["real_power"]}},
        "alerts": {"count": 1, "by_circuit": {"fridge": 1}},
        "nilm_signatures": {"mains": 1},
        "last_exported_diagnostics": {
            "circuit_id": "fridge",
            "anomaly_score": 0.42,
        },
    }
    assert "sensor.secret_panel_power" not in repr(diagnostics)


@pytest.mark.asyncio
async def test_diagnostics_includes_entity_model_metadata_without_entity_ids() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    registry = SimpleNamespace(
        entities={
            "sensor.fridge_sensitivity": SimpleNamespace(
                entity_id="sensor.fridge_sensitivity",
                unique_id="entry-1_fridge_sensitivity",
                config_entry_id="entry-1",
                platform=DOMAIN,
                disabled_by=None,
                hidden_by=None,
            ),
            "sensor.fridge_health_summary": SimpleNamespace(
                entity_id="sensor.fridge_health_summary",
                unique_id="entry-1_fridge_health_summary",
                config_entry_id="entry-1",
                platform=DOMAIN,
                disabled_by=None,
                hidden_by=None,
            ),
        }
    )
    coordinator = SimpleNamespace(
        options={
            CONF_ENTITY_DETAIL_LEVEL: "expert",
            CONF_ENTITY_MODEL_VERSION: ENTITY_MODEL_COMPACT,
            CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
            CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS: ["sensor:sensitivity"],
        },
        entry_data={},
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=registry,
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={},
        options=coordinator.options,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entity_model"] == {
        "version": ENTITY_MODEL_COMPACT,
        "detail_level": "expert",
        "selected_groups": ["cycle_metrics"],
        "desired_entity_count": 1,
        "legacy_entity_count": 1,
        "legacy_compatibility_key_count": 1,
    }
    assert "sensor.fridge_sensitivity" not in repr(diagnostics["entity_model"])
    assert "entry-1_fridge_sensitivity" not in repr(diagnostics["entity_model"])


def test_diagnostics_reraises_nested_homeassistant_import_failures(
    monkeypatch,
) -> None:
    original_import = builtins.__import__
    sys.modules.pop("custom_components.circuitsetup_energy_analyzer.diagnostics", None)

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "homeassistant.helpers" and "device_registry" in fromlist:
            raise ModuleNotFoundError(
                "No module named 'voluptuous'",
                name="voluptuous",
            )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError) as err:
        importlib.import_module("custom_components.circuitsetup_energy_analyzer.diagnostics")

    assert err.value.name == "voluptuous"


def test_strings_include_service_repair_problem_keys() -> None:
    strings = json.loads(
        Path("custom_components/circuitsetup_energy_analyzer/strings.json").read_text(
            encoding="utf-8"
        )
    )

    assert "missing_source_entities" in strings["issues"]
    assert "missing_energy_source" in strings["issues"]
    assert "missing_mains_source" in strings["issues"]
    assert "missing_electrical_metrics" in strings["issues"]
    assert "check_ct_direction" in strings["issues"]
    assert "dual_phase_missing_leg" in strings["issues"]
    assert "missing_rain_context_source" in strings["issues"]
    assert "missing_water_flow_source" in strings["issues"]
    assert "utility_comparison_source_mismatch" in strings["issues"]
