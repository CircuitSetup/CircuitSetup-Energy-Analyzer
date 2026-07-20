from __future__ import annotations

import pytest

from custom_components.circuitsetup_energy_analyzer import (
    config_flow,
    entity_catalog,
    panel,
    repairs,
    storage,
)
from custom_components.circuitsetup_energy_analyzer import (
    coordinator as coordinator_module,
)
from custom_components.circuitsetup_energy_analyzer.config_parsing import (
    circuit_configs_from_entry_data,
)
from custom_components.circuitsetup_energy_analyzer.ux import normalize_sensitivity


@pytest.mark.parametrize(
    ("module", "name"),
    (
        (
            config_flow.CircuitSetupEnergyAnalyzerOptionsFlow,
            "async_step_compact_migration",
        ),
        (coordinator_module.EnergyAnalyzerCoordinator, "_source_update_task"),
        (entity_catalog, "compact_migration_preview_for_hass"),
        (panel, "nilm_workspace_payload"),
        (repairs, "async_sync_compact_entity_model_issue"),
        (storage, "migrate_v1_to_v2"),
    ),
)
def test_backward_compatibility_apis_are_removed(
    module: object,
    name: str,
) -> None:
    assert not hasattr(module, name)


def test_legacy_sensitivity_names_are_not_normalized() -> None:
    assert normalize_sensitivity("low") == "balanced"
    assert normalize_sensitivity("standard") == "balanced"
    assert normalize_sensitivity("high") == "balanced"


def test_legacy_circuit_setting_names_are_ignored() -> None:
    config = circuit_configs_from_entry_data(
        {
            "circuits": [
                {
                    "circuit_id": "dryer",
                    "usage_window_days": 30,
                    "power_flow": "bidirectional",
                    "source_entities": ["sensor.dryer_power"],
                }
            ]
        }
    )[0]

    assert config.energy_usage_window_days == 7
    assert config.power_flow.value == "load"
    assert config.sensors == ()
