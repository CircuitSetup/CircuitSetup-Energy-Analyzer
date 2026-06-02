from __future__ import annotations

from typing import Any

from .const import DOMAIN

try:
    from homeassistant.helpers import device_registry as dr
except ModuleNotFoundError:
    dr = None


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    entry_id = getattr(entry, "entry_id", "default")
    return {
        "entry": {
            "entry_id": entry_id,
            "title": getattr(entry, "title", ""),
            "data_keys": sorted(getattr(entry, "data", {})),
            "option_keys": sorted(getattr(entry, "options", {})),
        },
        "devices": _devices_for_entry(hass, entry_id),
        "runtime_loaded": entry_id in getattr(hass, "data", {}).get(DOMAIN, {}),
    }


def _devices_for_entry(hass: Any, entry_id: str) -> list[dict[str, Any]]:
    """Return device metadata for this entry when HA helpers are importable."""
    if dr is None:
        return []

    async_get = getattr(dr, "async_get", None)
    entries_for_config_entry = getattr(dr, "async_entries_for_config_entry", None)
    if async_get is None or entries_for_config_entry is None:
        return []

    device_registry = async_get(hass)
    devices = entries_for_config_entry(device_registry, entry_id)
    return [
        {
            "id": getattr(device, "id", None),
            "name": getattr(device, "name", None),
            "manufacturer": getattr(device, "manufacturer", None),
            "model": getattr(device, "model", None),
        }
        for device in devices
    ]
