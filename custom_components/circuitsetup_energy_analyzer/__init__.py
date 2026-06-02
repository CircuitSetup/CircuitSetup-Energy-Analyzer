from __future__ import annotations

from typing import Any

from .const import CONF_SOURCE_ENTITIES, DOMAIN, PLATFORMS

type CircuitSetupEnergyAnalyzerConfigEntry = Any


async def async_setup_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    source_entities = getattr(entry, "data", {}).get(CONF_SOURCE_ENTITIES, [])
    hass.data[DOMAIN][getattr(entry, "entry_id", "default")] = {
        CONF_SOURCE_ENTITIES: source_entities
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Unload CircuitSetup Energy Analyzer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(getattr(entry, "entry_id", "default"), None)
    return unload_ok
