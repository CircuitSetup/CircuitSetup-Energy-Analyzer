from __future__ import annotations

from typing import Any

from .const import (
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_SOURCE_ENTITIES,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import EnergyAnalyzerCoordinator
from .panel import async_setup_panel, async_unload_panel
from .services import async_setup_services, async_unload_services
from .storage import FeatureStore, FeatureStoreData
from .ux import canonicalize_sensitivity_config

type CircuitSetupEnergyAnalyzerConfigEntry = Any

_SERVICES_SETUP_KEY = "_services_setup"


def _has_config_entries(domain_data: dict[str, Any]) -> bool:
    return any(not str(key).startswith("_") for key in domain_data)


async def async_setup_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Set up CircuitSetup Energy Analyzer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry_id = getattr(entry, "entry_id", "default")
    store, store_data = await _async_load_feature_store(hass, entry_id)
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_id=entry_id,
        entry_data=getattr(entry, "data", {}),
        options=getattr(entry, "options", {}),
        store=store,
        store_data=store_data,
        config_entry=entry,
    )
    first_entry = not _has_config_entries(hass.data[DOMAIN])
    try:
        if first_entry:
            await async_setup_services(hass)
            await async_setup_panel(hass)
        await coordinator.async_start(_source_entities_for_entry(entry, coordinator))
        hass.data[DOMAIN][entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry_id, None)
        await coordinator.async_stop()
        if first_entry and not _has_config_entries(hass.data.get(DOMAIN, {})):
            await async_unload_panel(hass)
            await async_unload_services(hass)
        raise
    return True


async def async_migrate_entry(
    hass: Any,
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
) -> bool:
    """Migrate config-entry data while preserving existing keys."""
    data = canonicalize_sensitivity_config(getattr(entry, "data", {}) or {})
    options = canonicalize_sensitivity_config(getattr(entry, "options", {}) or {})
    if data != dict(getattr(entry, "data", {}) or {}) or options != dict(
        getattr(entry, "options", {}) or {}
    ):
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
        )
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
        if not _has_config_entries(hass.data.get(DOMAIN, {})):
            await async_unload_panel(hass)
            await async_unload_services(hass)
    return unload_ok


def _source_entities_for_entry(
    entry: CircuitSetupEnergyAnalyzerConfigEntry,
    coordinator: EnergyAnalyzerCoordinator,
) -> tuple[str, ...]:
    entry_data = getattr(entry, "data", {}) or {}
    entry_options = getattr(entry, "options", {}) or {}
    entity_ids = list(
        entry_options.get(
            CONF_SOURCE_ENTITIES,
            entry_data.get(CONF_SOURCE_ENTITIES, []),
        )
    )
    outdoor_temperature_entity = str(
        entry_options.get(
            CONF_OUTDOOR_TEMPERATURE_ENTITY,
            entry_data.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, ""),
        )
        or ""
    ).strip()
    if outdoor_temperature_entity:
        entity_ids.append(outdoor_temperature_entity)
    for key in (CONF_RAIN_SENSOR_ENTITY, CONF_RAIN_INTENSITY_ENTITY):
        entity_id = str(
            entry_options.get(key, entry_data.get(key, ""))
            or ""
        ).strip()
        if entity_id:
            entity_ids.append(entity_id)
    flow_entities = entry_options.get(
        CONF_WATER_FLOW_SENSOR_ENTITIES,
        entry_data.get(CONF_WATER_FLOW_SENSOR_ENTITIES, []),
    )
    if isinstance(flow_entities, str):
        if flow_entities:
            entity_ids.append(flow_entities)
    elif isinstance(flow_entities, (list, tuple, set)):
        entity_ids.extend(
            entity_id for entity_id in flow_entities if isinstance(entity_id, str)
        )
    for config in getattr(coordinator, "circuit_configs", ()):
        for sensor in getattr(config, "sensors", ()):
            entity_ids.append(sensor.entity_id)
    return tuple(dict.fromkeys(entity_ids))


async def _async_load_feature_store(
    hass: Any,
    entry_id: str,
) -> tuple[Any | None, FeatureStoreData]:
    try:
        store = FeatureStore(hass, entry_id)
    except ModuleNotFoundError:
        return None, FeatureStoreData()
    return store, await store.async_load()
