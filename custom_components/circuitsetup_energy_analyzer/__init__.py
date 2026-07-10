from __future__ import annotations

from typing import Any

from . import repairs
from .const import (
    CONF_ENTITY_MODEL_VERSION,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_SOURCE_ENTITIES,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DATA_RELOAD_COUNT,
    DOMAIN,
    ENTITY_MODEL_LEGACY,
    PLATFORMS,
)
from .coordinator import EnergyAnalyzerCoordinator
from .entity_catalog import legacy_entity_registry_entries_for_hass
from .panel import async_setup_panel, async_unload_panel
from .services import async_setup_services, async_unload_services
from .storage import FeatureStore, FeatureStoreData
from .ux import canonicalize_sensitivity_config

type CircuitSetupEnergyAnalyzerConfigEntry = Any

_SERVICES_SETUP_KEY = "_services_setup"
_DEMO_SOURCE_ENTITY_PREFIX = "sensor.cs_energy_analyzer_demo_"
_DEMO_SOURCE_UNIQUE_ID_PREFIX = "demo_source_exact_"


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
        if getattr(hass, "config", None) is not None:
            await repairs.async_sync_compact_entity_model_issue(
                hass,
                entry_id,
                legacy_count=len(
                    legacy_entity_registry_entries_for_hass(hass, entry_id=entry_id)
                ),
            )
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
    if (
        CONF_ENTITY_MODEL_VERSION not in data
        and CONF_ENTITY_MODEL_VERSION not in options
    ):
        options[CONF_ENTITY_MODEL_VERSION] = ENTITY_MODEL_LEGACY
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
    domain_data = hass.data.get(DOMAIN, {})
    entry_id = getattr(entry, "entry_id", "default")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = domain_data.pop(entry_id, None)
        if coordinator is not None:
            await coordinator.async_stop()
        if not _has_config_entries(domain_data) and not domain_data.get(
            DATA_RELOAD_COUNT, 0
        ):
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
    entity_ids.extend(
        sensor.entity_id
        for config in getattr(coordinator, "circuit_configs", ())
        for sensor in getattr(config, "sensors", ())
    )
    return tuple(
        dict.fromkeys(
            _resolve_registered_demo_source_entity_ids(
                entity_ids,
                entry_id=getattr(entry, "entry_id", "default"),
                coordinator=coordinator,
            )
        )
    )


def _resolve_registered_demo_source_entity_ids(
    entity_ids: list[str],
    *,
    entry_id: str,
    coordinator: EnergyAnalyzerCoordinator,
) -> list[str]:
    registered_entity_ids = _registered_demo_source_entity_ids(
        getattr(coordinator, "hass", None),
        entry_id=entry_id,
    )
    if not registered_entity_ids:
        return entity_ids
    return [
        registered_entity_ids.get(entity_id, entity_id)
        if _is_demo_source_entity_id(entity_id)
        else entity_id
        for entity_id in entity_ids
    ]


def _registered_demo_source_entity_ids(
    hass: Any,
    *,
    entry_id: str,
) -> dict[str, str]:
    if hass is None:
        return {}
    registry = None
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
    except (ImportError, AttributeError, TypeError):
        registry = getattr(hass, "entity_registry", None)
    if registry is None:
        return {}
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    registered: dict[str, str] = {}
    unique_id_prefix = f"{entry_id}_{_DEMO_SOURCE_UNIQUE_ID_PREFIX}"
    for registry_entry in values:
        unique_id = str(getattr(registry_entry, "unique_id", ""))
        if not unique_id.startswith(unique_id_prefix):
            continue
        if getattr(registry_entry, "config_entry_id", entry_id) != entry_id:
            continue
        if getattr(registry_entry, "platform", DOMAIN) != DOMAIN:
            continue
        canonical_entity_id = (
            f"sensor.{unique_id.removeprefix(unique_id_prefix)}"
        )
        registered[canonical_entity_id] = str(
            getattr(registry_entry, "entity_id", canonical_entity_id)
        )
    return registered


def _is_demo_source_entity_id(entity_id: str) -> bool:
    return str(entity_id).startswith(_DEMO_SOURCE_ENTITY_PREFIX)


async def _async_load_feature_store(
    hass: Any,
    entry_id: str,
) -> tuple[Any | None, FeatureStoreData]:
    try:
        store = FeatureStore(hass, entry_id)
    except ModuleNotFoundError:
        return None, FeatureStoreData()
    except AttributeError:
        if getattr(hass, "config", None) is None:
            return None, FeatureStoreData()
        raise
    return store, await store.async_load()
