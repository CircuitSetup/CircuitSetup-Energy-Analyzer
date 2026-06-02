from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN


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
