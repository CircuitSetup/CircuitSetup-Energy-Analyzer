from __future__ import annotations

from typing import Any

from .const import CONF_SOURCE_ENTITIES, DOMAIN, PLATFORMS
from .coordinator import EnergyAnalyzerCoordinator

type CircuitSetupEnergyAnalyzerConfigEntry = Any


async def async_setup_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry_id = getattr(entry, "entry_id", "default")
    source_entities = getattr(entry, "data", {}).get(CONF_SOURCE_ENTITIES, [])
    coordinator = EnergyAnalyzerCoordinator(hass)
    await coordinator.async_start(source_entities)
    hass.data[DOMAIN][entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry_id, None)
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Unload CircuitSetup Energy Analyzer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(
            getattr(entry, "entry_id", "default"), None
        )
        if coordinator is not None:
            await coordinator.async_stop()
    return unload_ok
