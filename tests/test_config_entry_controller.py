from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.managers import (
    config_entry_controller,
)


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.updated: list[tuple[object, dict[str, Any]]] = []
        self.reloaded: list[str] = []

    async def async_update_entry(
        self,
        entry: object,
        *,
        options: dict[str, Any],
    ) -> None:
        self.updated.append((entry, options))

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


class _ConfigEntryCoordinator:
    def __init__(self) -> None:
        self.entry_id = "entry-1"
        self.options = {"advanced_settings": {"fridge": {"daily_spike_ratio": 0.25}}}
        self._config_entry = SimpleNamespace(
            options={"existing_option": True, "dashboard_layout": "standard"}
        )
        self.hass = SimpleNamespace(config_entries=_FakeConfigEntries())


@pytest.mark.asyncio
async def test_config_entry_controller_persists_options_copy() -> None:
    coordinator = _ConfigEntryCoordinator()
    controller = config_entry_controller.ConfigEntryController(coordinator)

    await controller.async_persist_options()

    assert coordinator.hass.config_entries.updated == [
        (
            coordinator._config_entry,
            {
                "advanced_settings": {
                    "fridge": {"daily_spike_ratio": 0.25},
                },
            },
        )
    ]
    persisted_options = coordinator.hass.config_entries.updated[0][1]
    assert persisted_options is not coordinator.options
    assert persisted_options["advanced_settings"] is not coordinator.options[
        "advanced_settings"
    ]


@pytest.mark.asyncio
async def test_config_entry_controller_updates_options_from_entry_options() -> None:
    coordinator = _ConfigEntryCoordinator()
    controller = config_entry_controller.ConfigEntryController(coordinator)

    await controller.async_update_options({"dashboard_layout": "expert"})

    assert coordinator.hass.config_entries.updated == [
        (
            coordinator._config_entry,
            {"existing_option": True, "dashboard_layout": "expert"},
        )
    ]
    assert coordinator.options == {
        "existing_option": True,
        "dashboard_layout": "expert",
    }


@pytest.mark.asyncio
async def test_config_entry_controller_reloads_config_entry() -> None:
    coordinator = _ConfigEntryCoordinator()
    controller = config_entry_controller.ConfigEntryController(coordinator)

    await controller.async_reload()

    assert coordinator.hass.config_entries.reloaded == ["entry-1"]
