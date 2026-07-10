"""Config-entry option persistence and reload helpers."""

from __future__ import annotations

from collections.abc import Mapping
from inspect import isawaitable
from typing import Any

from ..const import DATA_RELOAD_COUNT, DOMAIN
from ..ux import mutable_config_copy


class ConfigEntryController:
    """Own Home Assistant config-entry option persistence and reload calls."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_persist_options(self) -> None:
        """Persist the coordinator's active options to the config entry."""
        coordinator = self._coordinator
        entry = getattr(coordinator, "_config_entry", None)
        if entry is None:
            return
        update_entry = self._config_entry_method("async_update_entry")
        if update_entry is None:
            return

        options = mutable_config_copy(getattr(coordinator, "options", {}) or {})
        result = update_entry(entry, options=options)
        if isawaitable(result):
            await result
        coordinator.options = mutable_config_copy(options)

    async def async_update_options(self, updates: Mapping[str, Any]) -> None:
        """Merge updates into config-entry options and persist them."""
        coordinator = self._coordinator
        entry = getattr(coordinator, "_config_entry", None)
        base_options = (
            mutable_config_copy(getattr(entry, "options", {}) or {})
            if entry is not None
            else mutable_config_copy(getattr(coordinator, "options", {}) or {})
        )
        if not isinstance(base_options, dict):
            base_options = {}
        base_options.update(mutable_config_copy(dict(updates)))
        coordinator.options = mutable_config_copy(base_options)
        await self.async_persist_options()

    async def async_reload(self) -> None:
        """Reload the active config entry when Home Assistant supports it."""
        coordinator = self._coordinator
        if getattr(coordinator, "_config_entry", None) is None:
            return
        reload_entry = self._config_entry_method("async_reload")
        if reload_entry is None:
            return

        hass = coordinator.hass
        domain_data = hass.data.setdefault(DOMAIN, {})
        domain_data[DATA_RELOAD_COUNT] = domain_data.get(DATA_RELOAD_COUNT, 0) + 1
        try:
            result = reload_entry(coordinator.entry_id)
            if isawaitable(result):
                await result
        finally:
            remaining = domain_data.get(DATA_RELOAD_COUNT, 1) - 1
            if remaining > 0:
                domain_data[DATA_RELOAD_COUNT] = remaining
            else:
                domain_data.pop(DATA_RELOAD_COUNT, None)
                if not any(
                    not str(key).startswith("_") for key in domain_data
                ):
                    from ..panel import async_unload_panel
                    from ..services import async_unload_services

                    await async_unload_panel(hass)
                    await async_unload_services(hass)

    def _config_entry_method(self, method_name: str) -> Any | None:
        config_entries = getattr(self._coordinator.hass, "config_entries", None)
        method = getattr(config_entries, method_name, None)
        return method if callable(method) else None
