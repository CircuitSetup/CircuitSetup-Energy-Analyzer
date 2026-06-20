from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .const import (
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_ENTITY_MODEL_VERSION,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    DOMAIN,
    ENTITY_MODEL_COMPACT,
)
from .entity_catalog import (
    compact_migration_preview_for_hass,
    legacy_compatibility_keys_for_coordinator,
    legacy_entity_registry_entries_for_hass,
    selected_entity_groups_for_coordinator,
)

try:
    from homeassistant.helpers import device_registry as dr
except ModuleNotFoundError as err:
    if err.name != "homeassistant":
        raise
    dr = None


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    entry_id = getattr(entry, "entry_id", "default")
    diagnostics = {
        "entry": {
            "entry_id": entry_id,
            "title": getattr(entry, "title", ""),
            "data_keys": sorted(getattr(entry, "data", {})),
            "option_keys": sorted(getattr(entry, "options", {})),
        },
        "devices": _devices_for_entry(hass, entry_id),
        "entity_model": _entity_model_summary(hass, entry),
        "runtime_loaded": entry_id in getattr(hass, "data", {}).get(DOMAIN, {}),
    }
    runtime = _runtime_summary(hass, entry_id)
    if runtime is not None:
        diagnostics["runtime"] = runtime
    return diagnostics


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


def _runtime_summary(hass: Any, entry_id: str) -> dict[str, Any] | None:
    coordinator = getattr(hass, "data", {}).get(DOMAIN, {}).get(entry_id)
    store_data = getattr(coordinator, "store_data", None)
    if store_data is None:
        return None

    return {
        "events": _count_by_circuit(getattr(store_data, "events", [])),
        "baselines": _baseline_summary(getattr(store_data, "baselines", {})),
        "alerts": _count_by_circuit(getattr(store_data, "alerts", [])),
        "nilm_signatures": {
            str(circuit_id): len(signatures)
            for circuit_id, signatures in getattr(
                store_data,
                "nilm_signatures",
                {},
            ).items()
        },
        "last_exported_diagnostics": dict(
            getattr(coordinator, "last_exported_diagnostics", {}) or {}
        ),
    }


def _entity_model_summary(hass: Any, entry: Any) -> dict[str, Any]:
    entry_id = getattr(entry, "entry_id", "default")
    data = getattr(entry, "data", {}) or {}
    options = getattr(entry, "options", {}) or {}
    coordinator = getattr(hass, "data", {}).get(DOMAIN, {}).get(entry_id)
    metadata_source = coordinator
    if metadata_source is None:
        metadata_source = type(
            "_EntityModelDiagnosticSource",
            (),
            {"options": options, "entry_data": data},
        )()
    preview = compact_migration_preview_for_hass(hass, entry_id=entry_id)
    return {
        "version": _entry_value(
            data,
            options,
            CONF_ENTITY_MODEL_VERSION,
            ENTITY_MODEL_COMPACT,
        ),
        "detail_level": _entry_value(
            data,
            options,
            CONF_ENTITY_DETAIL_LEVEL,
            DEFAULT_ENTITY_DETAIL_LEVEL,
        ),
        "selected_groups": sorted(
            group.value for group in selected_entity_groups_for_coordinator(
                metadata_source
            )
        ),
        "desired_entity_count": int(preview.get("after_count", 0) or 0),
        "legacy_entity_count": len(
            legacy_entity_registry_entries_for_hass(hass, entry_id=entry_id)
        ),
        "legacy_compatibility_key_count": len(
            legacy_compatibility_keys_for_coordinator(metadata_source)
        ),
    }


def _entry_value(
    data: dict[str, Any],
    options: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    return options.get(key, data.get(key, default))


def _count_by_circuit(items: list[Any]) -> dict[str, Any]:
    counts = Counter(str(getattr(item, "circuit_id", "")) for item in items)
    counts.pop("", None)
    return {"count": len(items), "by_circuit": dict(sorted(counts.items()))}


def _baseline_summary(baselines: dict[str, Any]) -> dict[str, Any]:
    features_by_circuit: defaultdict[str, list[str]] = defaultdict(list)
    for key, baseline in baselines.items():
        circuit_id, _separator, feature_from_key = str(key).partition(":")
        feature = str(getattr(baseline, "feature", None) or feature_from_key)
        features_by_circuit[circuit_id].append(feature)

    return {
        "count": len(baselines),
        "features": {
            circuit_id: sorted(features)
            for circuit_id, features in sorted(features_by_circuit.items())
        },
    }
