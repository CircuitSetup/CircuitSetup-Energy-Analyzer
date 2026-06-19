from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONF_CIRCUITS = "circuits"
CONF_SOURCE_ENTITIES = "source_entities"
DOMAIN = "circuitsetup_energy_analyzer"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.asyncio
async def test_config_entry_setup_reload_unload_lifecycle(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise a real Home Assistant config-entry lifecycle."""

    import custom_components

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(__file__).parents[1] / "custom_components")],
    )
    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.fridge_energy",
        "120.5",
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="lifecycle-entry",
        title="Lifecycle Gate",
        data={
            CONF_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.fridge_energy",
            ],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.fridge_energy",
                            "role": "energy",
                        },
                    ],
                }
            ],
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is True
    assert coordinator.source_entities == (
        "sensor.fridge_power",
        "sensor.fridge_energy",
    )

    assert await hass.config_entries.async_reload(entry.entry_id) is True
    await hass.async_block_till_done()

    reloaded_coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is False
    assert reloaded_coordinator is not coordinator
    assert reloaded_coordinator.started is True
    assert reloaded_coordinator.source_entities == coordinator.source_entities

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert reloaded_coordinator.started is False
    assert entry.entry_id not in hass.data[DOMAIN]
