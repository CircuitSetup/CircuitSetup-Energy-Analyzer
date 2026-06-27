from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .appliance_metadata import existing_area_names_for_hass, suggested_area_for_profile
from .const import (
    CONF_CIRCUITS,
    CONF_ENTITY_DETAIL_LEVEL,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from .models import ApplianceProfile, SensorRole

try:
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
except ModuleNotFoundError:

    class HomeAssistantError(Exception):
        """Fallback Home Assistant error for tests without Home Assistant."""

    class EntityCategory:
        """Fallback entity category constants for tests without Home Assistant."""

        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity:
        """Small CoordinatorEntity fallback for helper tests."""

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator


class EntityTier(StrEnum):
    """Default Home Assistant entity exposure tier."""

    SUMMARY = "summary"
    FEATURE = "feature"
    DIAGNOSTIC = "diagnostic"


ENTITY_DETAIL_LEVELS = (
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
    ENTITY_DETAIL_EXPERT,
)


def normalize_entity_detail_level(value: Any) -> str:
    """Return a supported entity detail level."""
    normalized = str(value or "").strip().lower()
    if normalized in ENTITY_DETAIL_LEVELS:
        return normalized
    return DEFAULT_ENTITY_DETAIL_LEVEL


def entity_detail_level_for_coordinator(coordinator: Any) -> str:
    """Return the active entity detail level from coordinator options/data."""
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        if isinstance(container, Mapping) and container.get(CONF_ENTITY_DETAIL_LEVEL):
            return normalize_entity_detail_level(container[CONF_ENTITY_DETAIL_LEVEL])
    return DEFAULT_ENTITY_DETAIL_LEVEL


def entity_enabled_default_for_tier(
    tier: EntityTier,
    detail_level: Any = DEFAULT_ENTITY_DETAIL_LEVEL,
) -> bool:
    """Return whether a tier should be enabled by default for a detail level."""
    level = normalize_entity_detail_level(detail_level)
    if tier is EntityTier.SUMMARY:
        return True
    if tier is EntityTier.FEATURE:
        return level in {ENTITY_DETAIL_STANDARD, ENTITY_DETAIL_EXPERT}
    return level == ENTITY_DETAIL_EXPERT


async def async_call_or_raise(
    target: Any,
    method_name: str,
    action_label: str,
    *args: Any,
) -> None:
    """Call a coordinator action or raise the shared Home Assistant error."""
    method = getattr(target, method_name, None)
    if not callable(method):
        raise HomeAssistantError(
            f"Cannot {action_label.strip().lower()} right now because the "
            "analyzer action is unavailable."
        )
    result = method(*args)
    if inspect.isawaitable(result):
        await result


def desired_disabled_by_for_entity_tier(
    tier: EntityTier,
    detail_level: Any = DEFAULT_ENTITY_DETAIL_LEVEL,
) -> str | None:
    """Return registry disabled_by state desired for an entity tier."""
    if entity_enabled_default_for_tier(tier, detail_level):
        return None
    return "integration"


def entity_profile_registry_plan(
    entries: Iterable[Any],
    *,
    entry_id: str,
    entity_domain: str,
    tier_by_unique_id_suffix: Mapping[str, EntityTier],
    detail_level: Any,
) -> dict[str, Any]:
    """Preview registry enable/disable changes for applying a detail profile."""
    actions = _entity_profile_registry_actions(
        entries,
        entry_id=entry_id,
        entity_domain=entity_domain,
        tier_by_unique_id_suffix=tier_by_unique_id_suffix,
        detail_level=detail_level,
    )
    return {
        "profile": normalize_entity_detail_level(detail_level),
        "will_enable": sum(1 for action in actions if action["action"] == "enable"),
        "will_disable": sum(1 for action in actions if action["action"] == "disable"),
        "unchanged": sum(1 for action in actions if action["action"] == "unchanged"),
        "left_user_disabled": sum(
            1 for action in actions if action["action"] == "left_user_disabled"
        ),
        "total": len(actions),
        "actions": actions,
    }


def apply_entity_profile_to_registry(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    tier_by_unique_id_suffix: Mapping[str, EntityTier],
    detail_level: Any,
) -> dict[str, Any]:
    """Apply an entity detail profile to existing integration entities."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return {
            "profile": normalize_entity_detail_level(detail_level),
            "will_enable": 0,
            "will_disable": 0,
            "unchanged": 0,
            "left_user_disabled": 0,
            "total": 0,
            "actions": [],
        }

    registry = er.async_get(hass)
    update_entity = getattr(registry, "async_update_entity", None)
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    plan = entity_profile_registry_plan(
        values,
        entry_id=entry_id,
        entity_domain=entity_domain,
        tier_by_unique_id_suffix=tier_by_unique_id_suffix,
        detail_level=detail_level,
    )
    if not callable(update_entity):
        return plan

    integration_disabler = _integration_registry_disabler(er)
    for action in plan["actions"]:
        entity_id = action["entity_id"]
        if action["action"] == "disable":
            update_entity(entity_id, disabled_by=integration_disabler)
        elif action["action"] == "enable":
            update_entity(entity_id, disabled_by=None)
    return plan


def enable_summary_registry_entries(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    tier_by_unique_id_suffix: Mapping[str, EntityTier],
) -> dict[str, Any]:
    """Re-enable integration-disabled summary entities after tier promotions."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return {
            "enabled": 0,
            "left_user_disabled": 0,
            "unchanged": 0,
            "ignored": 0,
            "actions": [],
        }

    registry = er.async_get(hass)
    update_entity = getattr(registry, "async_update_entity", None)
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    actions = _summary_registry_actions(
        values,
        entry_id=entry_id,
        entity_domain=entity_domain,
        tier_by_unique_id_suffix=tier_by_unique_id_suffix,
    )
    if callable(update_entity):
        for action in actions:
            if action["action"] == "enable":
                update_entity(action["entity_id"], disabled_by=None)

    return {
        "enabled": sum(1 for action in actions if action["action"] == "enable"),
        "left_user_disabled": sum(
            1 for action in actions if action["action"] == "left_user_disabled"
        ),
        "unchanged": sum(1 for action in actions if action["action"] == "unchanged"),
        "ignored": sum(1 for action in actions if action["action"] == "ignore"),
        "actions": actions,
    }


def _entity_profile_registry_actions(
    entries: Iterable[Any],
    *,
    entry_id: str,
    entity_domain: str,
    tier_by_unique_id_suffix: Mapping[str, EntityTier],
    detail_level: Any,
) -> list[dict[str, Any]]:
    prefix = f"{entity_domain}."
    suffixes = sorted(tier_by_unique_id_suffix, key=len, reverse=True)
    actions: list[dict[str, Any]] = []
    for entry in entries:
        entity_id = str(getattr(entry, "entity_id", ""))
        unique_id = str(getattr(entry, "unique_id", ""))
        if (
            getattr(entry, "config_entry_id", None) != entry_id
            or getattr(entry, "platform", None) != DOMAIN
            or not entity_id.startswith(prefix)
        ):
            continue
        suffix = next(
            (
                candidate
                for candidate in suffixes
                if unique_id.endswith(f"_{candidate}")
            ),
            None,
        )
        if suffix is None:
            continue

        tier = tier_by_unique_id_suffix[suffix]
        desired_disabled_by = desired_disabled_by_for_entity_tier(
            tier,
            detail_level,
        )
        actual_disabled_by = _registry_disabled_by_name(
            getattr(entry, "disabled_by", None)
        )
        action = _registry_profile_action(actual_disabled_by, desired_disabled_by)
        actions.append(
            {
                "entity_id": entity_id,
                "unique_id": unique_id,
                "suffix": suffix,
                "tier": tier.value,
                "disabled_by": actual_disabled_by,
                "desired_disabled_by": desired_disabled_by,
                "action": action,
            }
        )
    return actions


def _summary_registry_actions(
    entries: Iterable[Any],
    *,
    entry_id: str,
    entity_domain: str,
    tier_by_unique_id_suffix: Mapping[str, EntityTier],
) -> list[dict[str, Any]]:
    prefix = f"{entity_domain}."
    suffixes = sorted(tier_by_unique_id_suffix, key=len, reverse=True)
    actions: list[dict[str, Any]] = []
    for entry in entries:
        entity_id = str(getattr(entry, "entity_id", ""))
        unique_id = str(getattr(entry, "unique_id", ""))
        if (
            getattr(entry, "config_entry_id", None) != entry_id
            or getattr(entry, "platform", None) != DOMAIN
            or not entity_id.startswith(prefix)
        ):
            continue
        suffix = next(
            (
                candidate
                for candidate in suffixes
                if unique_id.endswith(f"_{candidate}")
            ),
            None,
        )
        if suffix is None:
            continue

        tier = tier_by_unique_id_suffix[suffix]
        disabled_by = _registry_disabled_by_name(getattr(entry, "disabled_by", None))
        if tier is not EntityTier.SUMMARY:
            action = "ignore"
        elif disabled_by == "integration":
            action = "enable"
        elif disabled_by == "user":
            action = "left_user_disabled"
        else:
            action = "unchanged"
        actions.append(
            {
                "action": action,
                "entity_id": entity_id,
                "suffix": suffix,
            }
        )
    return actions


def _registry_profile_action(
    actual_disabled_by: str | None,
    desired_disabled_by: str | None,
) -> str:
    if desired_disabled_by is None:
        if actual_disabled_by is None:
            return "unchanged"
        if actual_disabled_by == "integration":
            return "enable"
        return "left_user_disabled"
    if actual_disabled_by is None:
        return "disable"
    if actual_disabled_by == desired_disabled_by:
        return "unchanged"
    return "left_user_disabled"


def _registry_disabled_by_name(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if raw_value is None:
        return None
    return str(raw_value).split(".")[-1].lower()


def _integration_registry_disabler(registry_module: Any) -> Any:
    disabler = getattr(registry_module, "RegistryEntryDisabler", None)
    return getattr(disabler, "INTEGRATION", "integration")


@dataclass(frozen=True, slots=True)
class CircuitInfo:
    """Normalized configured circuit identity used by platform entities."""

    circuit_id: str
    name: str
    appliance_profile: str | None = None
    sensors: tuple[Any, ...] = ()


def circuit_info_from_config(circuit: Any) -> CircuitInfo | None:
    """Return circuit id/name from a dataclass-like or mapping config object."""
    if isinstance(circuit, dict):
        circuit_id = circuit.get("circuit_id") or circuit.get("id")
        name = circuit.get("name") or circuit_id
        appliance_profile = circuit.get("appliance_profile")
        sensors = circuit.get("sensors") or ()
    else:
        circuit_id = getattr(circuit, "circuit_id", None)
        name = getattr(circuit, "name", None) or circuit_id
        appliance_profile = getattr(circuit, "appliance_profile", None)
        sensors = getattr(circuit, "sensors", ()) or ()

    if not circuit_id:
        return None

    return CircuitInfo(
        circuit_id=str(circuit_id),
        name=str(name),
        appliance_profile=str(appliance_profile) if appliance_profile else None,
        sensors=tuple(sensors),
    )


def circuits_for_entities(entry: Any, coordinator: Any) -> tuple[Any, ...]:
    """Return runtime circuits when available, falling back to entry data."""
    runtime_circuits = tuple(getattr(coordinator, "circuit_configs", ()) or ())
    if runtime_circuits:
        return runtime_circuits
    return tuple(getattr(entry, "data", {}).get(CONF_CIRCUITS, []))


def supports_daily_circuit_controls(circuit: Any) -> bool:
    """Return whether daily controls are useful for this circuit."""
    profile = _appliance_profile(_circuit_value(circuit, "appliance_profile"))
    if profile in {
        ApplianceProfile.MAINS_NILM,
        ApplianceProfile.SOLAR_INVERTER,
        ApplianceProfile.MIXED,
    }:
        return False
    return _has_real_power_sensor(circuit)


def _has_real_power_sensor(circuit: Any) -> bool:
    return any(
        _sensor_role(sensor) is SensorRole.REAL_POWER
        for sensor in _circuit_sensors(circuit)
    )


def _sensor_role(sensor: Any) -> SensorRole | None:
    role = (
        sensor.get("role")
        if isinstance(sensor, Mapping)
        else getattr(sensor, "role", None)
    )
    if isinstance(role, SensorRole):
        return role
    try:
        return SensorRole(str(role))
    except (TypeError, ValueError):
        return None


def _circuit_sensors(circuit: Any) -> tuple[Any, ...]:
    sensors = _circuit_value(circuit, "sensors", ())
    if isinstance(sensors, tuple):
        return sensors
    if isinstance(sensors, list):
        return tuple(sensors)
    return ()


def _circuit_value(circuit: Any, key: str, default: Any = None) -> Any:
    if isinstance(circuit, Mapping):
        return circuit.get(key, default)
    return getattr(circuit, key, default)


def _appliance_profile(value: Any) -> ApplianceProfile | None:
    if isinstance(value, ApplianceProfile):
        return value
    try:
        return ApplianceProfile(str(value))
    except (TypeError, ValueError):
        return None


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


def hide_entity_registry_entries(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    hidden_unique_id_suffixes: set[str],
) -> None:
    """Mark existing detail entities hidden when defaults become less noisy."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return

    registry = er.async_get(hass)
    update_entity = getattr(registry, "async_update_entity", None)
    if not callable(update_entity):
        return

    hider = getattr(er, "RegistryEntryHider", None)
    hidden_by = getattr(hider, "INTEGRATION", "integration")
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    prefix = f"{entity_domain}."
    for entry in values:
        entity_id = str(getattr(entry, "entity_id", ""))
        unique_id = str(getattr(entry, "unique_id", ""))
        if (
            getattr(entry, "config_entry_id", None) != entry_id
            or getattr(entry, "platform", None) != DOMAIN
            or not entity_id.startswith(prefix)
            or getattr(entry, "hidden_by", None) is not None
            or not any(
                unique_id.endswith(f"_{suffix}")
                for suffix in hidden_unique_id_suffixes
            )
        ):
            continue
        update_entity(entity_id, hidden_by=hidden_by)


def sync_entity_registry_visibility(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    hidden_unique_id_suffixes: set[str],
    detail_level: Any,
) -> None:
    """Hide noisy detail rows normally, but reveal integration-hidden rows in Expert."""
    if normalize_entity_detail_level(detail_level) != ENTITY_DETAIL_EXPERT:
        hide_entity_registry_entries(
            hass,
            entry_id=entry_id,
            entity_domain=entity_domain,
            hidden_unique_id_suffixes=hidden_unique_id_suffixes,
        )
        return

    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return

    registry = er.async_get(hass)
    update_entity = getattr(registry, "async_update_entity", None)
    if not callable(update_entity):
        return

    hider = getattr(er, "RegistryEntryHider", None)
    integration_hidden_by = _registry_disabled_by_name(
        getattr(hider, "INTEGRATION", "integration")
    )
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    prefix = f"{entity_domain}."
    for entry in values:
        entity_id = str(getattr(entry, "entity_id", ""))
        unique_id = str(getattr(entry, "unique_id", ""))
        hidden_by = _registry_disabled_by_name(getattr(entry, "hidden_by", None))
        if (
            getattr(entry, "config_entry_id", None) != entry_id
            or getattr(entry, "platform", None) != DOMAIN
            or not entity_id.startswith(prefix)
            or hidden_by != integration_hidden_by
            or not any(
                unique_id.endswith(f"_{suffix}")
                for suffix in hidden_unique_id_suffixes
            )
        ):
            continue
        update_entity(entity_id, hidden_by=None)


def sync_entity_registry_categories(
    hass: Any,
    *,
    entry_id: str,
    entity_domain: str,
    entity_category_by_unique_id_suffix: dict[str, Any | None],
) -> None:
    """Update existing entity registry rows to current platform categories."""
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return

    registry = er.async_get(hass)
    update_entity = getattr(registry, "async_update_entity", None)
    if not callable(update_entity):
        return

    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    prefix = f"{entity_domain}."
    for entry in values:
        entity_id = str(getattr(entry, "entity_id", ""))
        unique_id = str(getattr(entry, "unique_id", ""))
        if (
            getattr(entry, "config_entry_id", None) != entry_id
            or getattr(entry, "platform", None) != DOMAIN
            or not entity_id.startswith(prefix)
        ):
            continue
        for suffix, entity_category in entity_category_by_unique_id_suffix.items():
            if not unique_id.endswith(f"_{suffix}"):
                continue
            if getattr(entry, "entity_category", None) != entity_category:
                update_entity(entity_id, entity_category=entity_category)
            break


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
        self._appliance_profile = circuit.appliance_profile
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
        device_info: dict[str, Any] = {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._circuit_id}")},
            "name": self._circuit_name,
            "manufacturer": "CircuitSetup",
        }
        suggested_area = suggested_area_for_profile(
            self._appliance_profile,
            existing_area_names_for_hass(getattr(self.coordinator, "hass", None)),
        )
        if suggested_area:
            device_info["suggested_area"] = suggested_area
        return device_info

    @property
    def coordinator_state(self) -> Any:
        """Current coordinator state, tolerating staged test coordinators."""
        return getattr(self.coordinator, "data", None)
