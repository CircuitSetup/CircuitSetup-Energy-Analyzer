from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .const import CONF_CIRCUITS, DOMAIN

try:
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
except ModuleNotFoundError:

    class EntityCategory:
        """Fallback entity category constants for tests without Home Assistant."""

        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity:
        """Small CoordinatorEntity fallback for helper tests."""

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator


@dataclass(frozen=True, slots=True)
class CircuitInfo:
    """Normalized configured circuit identity used by platform entities."""

    circuit_id: str
    name: str


def circuit_info_from_config(circuit: Any) -> CircuitInfo | None:
    """Return circuit id/name from a dataclass-like or mapping config object."""
    if isinstance(circuit, dict):
        circuit_id = circuit.get("circuit_id") or circuit.get("id")
        name = circuit.get("name") or circuit_id
    else:
        circuit_id = getattr(circuit, "circuit_id", None)
        name = getattr(circuit, "name", None) or circuit_id

    if not circuit_id:
        return None

    return CircuitInfo(circuit_id=str(circuit_id), name=str(name))


def circuits_for_entities(entry: Any, coordinator: Any) -> tuple[Any, ...]:
    """Return runtime circuits when available, falling back to entry data."""
    runtime_circuits = tuple(getattr(coordinator, "circuit_configs", ()) or ())
    if runtime_circuits:
        return runtime_circuits
    return tuple(getattr(entry, "data", {}).get(CONF_CIRCUITS, []))


def stale_entity_registry_entity_ids(
    entries: Iterable[Any],
    *,
    entry_id: str,
    entity_domain: str,
    desired_unique_ids: set[str],
) -> list[str]:
    """Return stale integration entity IDs for one platform domain."""
    prefix = f"{entity_domain}."
    return [
        str(entry.entity_id)
        for entry in entries
        if getattr(entry, "config_entry_id", None) == entry_id
        and getattr(entry, "platform", None) == DOMAIN
        and str(getattr(entry, "entity_id", "")).startswith(prefix)
        and getattr(entry, "unique_id", None) not in desired_unique_ids
    ]


def prune_stale_entity_registry_entries(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    desired_unique_ids: set[str],
) -> None:
    """Remove stale entity registry rows for entities no longer created."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return

    registry = er.async_get(hass)
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    for entity_id in stale_entity_registry_entity_ids(
        values,
        entry_id=entry_id,
        entity_domain=entity_domain,
        desired_unique_ids=desired_unique_ids,
    ):
        registry.async_remove(entity_id)


def stale_device_registry_device_ids(
    entries: Iterable[Any],
    *,
    entry_id: str,
    desired_identifiers: set[tuple[str, str]],
) -> list[str]:
    """Return stale integration device IDs for one config entry."""
    identifier_prefix = f"{entry_id}_"
    stale_device_ids: list[str] = []
    for entry in entries:
        config_entries = set(getattr(entry, "config_entries", ()) or ())
        if entry_id not in config_entries:
            continue
        identifiers = {
            (str(identifier[0]), str(identifier[1]))
            for identifier in getattr(entry, "identifiers", ()) or ()
            if isinstance(identifier, (list, tuple)) and len(identifier) == 2
        }
        integration_identifiers = {
            identifier
            for identifier in identifiers
            if identifier[0] == DOMAIN and identifier[1].startswith(identifier_prefix)
        }
        if integration_identifiers and not (
            integration_identifiers & desired_identifiers
        ):
            device_id = getattr(entry, "id", None)
            if device_id:
                stale_device_ids.append(str(device_id))
    return stale_device_ids


def prune_stale_device_registry_entries(
    hass: Any,
    *,
    entry_id: str,
    desired_identifiers: set[tuple[str, str]],
) -> None:
    """Remove stale integration devices no longer used by platform entities."""
    try:
        from homeassistant.helpers import device_registry as dr
    except ImportError:
        return

    registry = dr.async_get(hass)
    devices = getattr(registry, "devices", {})
    values = devices.values() if hasattr(devices, "values") else devices
    update_device = getattr(registry, "async_update_device", None)
    if not callable(update_device):
        return

    for device_id in stale_device_registry_device_ids(
        values,
        entry_id=entry_id,
        desired_identifiers=desired_identifiers,
    ):
        update_device(device_id, remove_config_entry_id=entry_id)


def device_identifiers_for_entities(entities: Iterable[Any]) -> set[tuple[str, str]]:
    """Return Home Assistant device identifiers exposed by entity objects."""
    identifiers: set[tuple[str, str]] = set()
    for entity in entities:
        device_info = getattr(entity, "device_info", None)
        if not isinstance(device_info, dict):
            continue
        for identifier in device_info.get("identifiers", ()) or ():
            if isinstance(identifier, (list, tuple)) and len(identifier) == 2:
                identifiers.add((str(identifier[0]), str(identifier[1])))
    return identifiers


class CircuitAnalyzerEntity(CoordinatorEntity):
    """Base entity for diagnostics associated with one configured circuit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: CircuitInfo,
        key: str,
        name_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._circuit_id = circuit.circuit_id
        self._circuit_name = circuit.name
        self._attr_name = f"{circuit.name} {name_suffix}"
        self._attr_unique_id = f"{entry_id}_{circuit.circuit_id}_{key}"

    @property
    def circuit_id(self) -> str:
        """Configured circuit identifier."""
        return self._circuit_id

    @property
    def circuit_name(self) -> str:
        """Configured circuit display name."""
        return self._circuit_name

    @property
    def name(self) -> str:
        """Entity display name for fallback tests."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Unique id for fallback tests."""
        return self._attr_unique_id

    @property
    def device_info(self) -> dict[str, Any]:
        """Group diagnostic entities by analyzed circuit in Home Assistant."""
        return {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._circuit_id}")},
            "name": self._circuit_name,
            "manufacturer": "CircuitSetup",
        }

    @property
    def coordinator_state(self) -> Any:
        """Current coordinator state, tolerating staged test coordinators."""
        return getattr(self.coordinator, "data", None)
