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
    CONF_SELECTED_ENTITY_GROUPS,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
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
        "appliance_details": [],
        "last_exported_diagnostics": {
            "circuit_id": "fridge",
            "anomaly_score": 0.42,
        },
    }
    assert "sensor.secret_panel_power" not in repr(diagnostics)


@pytest.mark.asyncio
async def test_diagnostics_includes_appliance_detail_runtime_summaries() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    state = AnalyzerState(
        latest_real_power_w_by_circuit={"fridge": 84.0},
        daily_energy_usage_by_circuit={"fridge": 2.4},
        run_cycle_status_by_circuit={"fridge": "running"},
    )
    coordinator = SimpleNamespace(
        state=state,
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(
                    SensorRef("sensor.secret_fridge_power", SensorRole.REAL_POWER),
                    SensorRef("sensor.secret_fridge_energy", SensorRole.ENERGY),
                ),
            ),
            CircuitConfig(
                circuit_id="mains",
                name="Mains NILM",
                appliance_profile=ApplianceProfile.MAINS_NILM,
                mode=CircuitMode.MAINS_NILM,
                sensors=(
                    SensorRef("sensor.secret_mains_power", SensorRole.REAL_POWER),
                ),
            ),
        ),
        store_data=FeatureStoreData(
            baselines={
                "fridge:daily_energy_kwh": BaselineStats(
                    "daily_energy_kwh",
                    12,
                    1.8,
                    0.1,
                    1.5,
                    2.1,
                    0.86,
                )
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "appliance_id": "dishwasher",
                        "display_name": "Dishwasher",
                        "appliance_profile": "dishwasher",
                        "lifecycle_state": "published",
                        "confidence": 0.91,
                        "publish_entities": True,
                        "created_device": True,
                    }
                ]
            },
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    timestamp=datetime(2026, 6, 2, 18, 0, tzinfo=UTC),
                    delta_w=820.0,
                    delta_var=0.0,
                    delta_va=820.0,
                    delta_pf=0.0,
                    direction="on",
                )
            ]
        },
        last_exported_diagnostics={},
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={"source_entities": ["sensor.secret_panel_power"]},
        options={},
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    details = {
        detail["display_name"]: detail
        for detail in diagnostics["runtime"]["appliance_details"]
    }
    assert details["Kitchen Fridge"]["source_type"] == "direct_meter"
    assert details["Kitchen Fridge"]["daily_energy_kwh"] == 2.4
    assert details["Kitchen Fridge"]["today_vs_normal"][0]["status"] == "learning"
    assert details["Dishwasher"]["source_type"] == "nilm_estimate"
    assert details["Dishwasher"]["confidence"] == 0.91
    assert "sensor.secret" not in repr(diagnostics["runtime"]["appliance_details"])


@pytest.mark.asyncio
async def test_diagnostics_includes_entity_display_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    coordinator = SimpleNamespace(
        options={
            CONF_ENTITY_DETAIL_LEVEL: "expert",
            CONF_SELECTED_ENTITY_GROUPS: ["cycle_metrics"],
        },
        entry_data={},
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Panel Analyzer",
        data={},
        options=coordinator.options,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entity_model"] == {
        "detail_level": "expert",
        "selected_groups": ["cycle_metrics"],
    }


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
        Path(
            "custom_components/circuitsetup_energy_analyzer/translations/en.json"
        ).read_text(encoding="utf-8")
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
