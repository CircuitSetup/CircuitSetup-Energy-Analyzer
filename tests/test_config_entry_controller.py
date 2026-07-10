from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    DATA_RELOAD_COUNT,
    DOMAIN,
)
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
        self.hass = SimpleNamespace(data={}, config_entries=_FakeConfigEntries())
        self.hass.data[DOMAIN] = {self.entry_id: self}


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


@pytest.mark.asyncio
async def test_config_entry_controller_counts_concurrent_reloads() -> None:
    coordinator = _ConfigEntryCoordinator()
    both_started = asyncio.Event()
    release = asyncio.Event()
    seen_counts: list[int] = []

    async def _reload(entry_id: str) -> bool:
        assert entry_id == coordinator.entry_id
        seen_counts.append(coordinator.hass.data[DOMAIN][DATA_RELOAD_COUNT])
        if len(seen_counts) == 2:
            both_started.set()
        await release.wait()
        return True

    coordinator.hass.config_entries.async_reload = _reload
    controller = config_entry_controller.ConfigEntryController(coordinator)
    tasks = [asyncio.create_task(controller.async_reload()) for _ in range(2)]

    await both_started.wait()
    assert seen_counts == [1, 2]
    release.set()
    await asyncio.gather(*tasks)

    assert DATA_RELOAD_COUNT not in coordinator.hass.data[DOMAIN]


@pytest.mark.parametrize("failure", [False, RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_config_entry_controller_reload_failure_cleans_preserved_panel(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool | type[BaseException],
) -> None:
    coordinator = _ConfigEntryCoordinator()
    cleaned: list[tuple[str, object]] = []

    async def _reload(entry_id: str) -> bool:
        domain_data = coordinator.hass.data[DOMAIN]
        assert domain_data[DATA_RELOAD_COUNT] == 1
        domain_data.pop(entry_id)
        if failure is not False:
            raise failure("reload failed")
        return False

    async def _cleanup_panel(hass: object) -> None:
        cleaned.append(("panel", hass))

    async def _cleanup_services(hass: object) -> None:
        cleaned.append(("services", hass))

    coordinator.hass.config_entries.async_reload = _reload
    from custom_components.circuitsetup_energy_analyzer import panel, services

    monkeypatch.setattr(panel, "async_unload_panel", _cleanup_panel)
    monkeypatch.setattr(services, "async_unload_services", _cleanup_services)
    controller = config_entry_controller.ConfigEntryController(coordinator)

    if failure is not False:
        with pytest.raises(failure, match="reload failed"):
            await controller.async_reload()
    else:
        await controller.async_reload()

    assert cleaned == [
        ("panel", coordinator.hass),
        ("services", coordinator.hass),
    ]
    assert DATA_RELOAD_COUNT not in coordinator.hass.data[DOMAIN]
