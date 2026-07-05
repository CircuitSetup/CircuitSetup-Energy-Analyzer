from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .const import (
    CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS,
    CONF_SELECTED_ENTITY_GROUPS,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)

LEGACY_ENTITY_REPLACEMENTS: Mapping[str, str] = {
    "sensitivity": "select:alert_sensitivity",
    "readiness": "sensor:health_summary#readiness",
    "learning_progress": "sensor:health_summary#learning_progress",
    "data_quality_checklist": "sensor:health_summary / setup_health / repairs",
    "alert_evidence": "evidence_panel",
    "last_event": "evidence_panel / recent_activity",
    "recent_activity_count": "recent_activity#count",
    "power_quality_evidence": "sensor:electrical_health / evidence_panel",
    "reactive_power_drift": "expert_group:power_quality_drift",
    "apparent_power_drift": "expert_group:power_quality_drift",
    "power_factor_drift": "expert_group:power_quality_drift",
    "metric_consistency_status": "sensor:electrical_health",
    "leg_imbalance_status": "sensor:electrical_health",
    "run_cycle_status": "sensor:activity_summary / binary_sensor:running",
    "billing_cycle_forecast": "billing_cycle_usage#forecast_kwh",
    "billing_cycle_budget_usage": "billing_cycle_usage#budget_usage_percent",
    "billing_cycle_status": "billing_cycle_usage#status",
    "cost_current_rate": "cost_cycle#current_rate_per_kwh",
    "cost_cycle_forecast": "cost_cycle#forecast_cost",
    "cost_status": "cost_cycle#status",
    "standby_threshold": "Advanced Circuit Settings / standby_status attribute",
    "outdoor_temperature": "configured source entity / weather_context attribute",
    "solar_site_consumption_power": "sensor:solar_flow_status / evidence_panel",
    "solar_grid_import_power": "sensor:solar_flow_status / evidence_panel",
    "solar_grid_export_power": "sensor:solar_flow_status / evidence_panel",
    "solar_self_consumption": "sensor:solar_flow_status / evidence_panel",
    "solar_powered": "sensor:solar_flow_status / evidence_panel",
    "solar_flexible_load_power": "sensor:solar_load_shift_evidence",
    "solar_flexible_load_coverage": "sensor:solar_load_shift_evidence",
    "solar_load_shift_power": "sensor:solar_surplus_power / evidence_panel",
    "solar_load_shift_status": "sensor:solar_surplus_status / evidence_panel",
    "utility_comparison_difference": "sensor:utility_comparison_status",
    "start_maintenance": "switch:maintenance",
    "end_maintenance": "switch:maintenance",
}


class EntityExposure(StrEnum):
    """Compact entity-model exposure class."""

    CORE = "core"
    FEATURE = "feature"
    GRAPH = "graph"
    DIAGNOSTIC = "diagnostic"
    LEGACY = "legacy"


class EntityGroup(StrEnum):
    """Compact entity-model opt-in group."""

    CORE = "core"
    CYCLE_METRICS = "cycle_metrics"
    ELECTRICAL_SCORES = "electrical_scores"
    POWER_QUALITY_DRIFT = "power_quality_drift"
    ENERGY_DETAIL = "energy_detail"
    BILLING_COST = "billing_cost"
    BILLING_FORECASTS = "billing_forecasts"
    DEMAND_CAPACITY = "demand_capacity"
    STANDBY = "standby"
    WEATHER = "weather"
    WATER = "water"
    MAINS_SOLAR = "mains_solar"
    NILM = "nilm"
    DEVELOPER_DIAGNOSTICS = "developer_diagnostics"


@dataclass(frozen=True, slots=True)
class EntityCreationRule:
    """Declarative compact-model creation policy for one entity key."""

    key: str
    domain: str
    exposure: EntityExposure
    group: EntityGroup
    minimum_detail_level: str
    create_in_simple: bool = False
    create_in_standard: bool = False
    create_in_expert: bool = False
    replacement: str | None = None
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class LegacyEntityRegistryEntry:
    """Registry row covered by the compact-model compatibility migration."""

    entity_id: str
    unique_id: str
    circuit_id: str
    domain: str
    key: str
    replacement: str
    disabled_by: str | None
    hidden_by: str | None
    customized: bool
    cleanup_safe: bool


_DETAIL_ORDER = {
    ENTITY_DETAIL_SIMPLE: 0,
    ENTITY_DETAIL_STANDARD: 1,
    ENTITY_DETAIL_EXPERT: 2,
}


def should_create_entity(
    *,
    rule: EntityCreationRule,
    circuit: Any,
    coordinator: Any,
    detail_level: str,
    selected_groups: Collection[str | EntityGroup],
    legacy_compatibility_keys: Collection[str],
    applicability_already_checked: bool = False,
) -> bool:
    """Return whether the compact model should create a described entity."""
    if (
        not applicability_already_checked
        and not _rule_applies_to_circuit(rule, circuit, coordinator)
    ):
        return False

    compatibility_keys = {str(item) for item in legacy_compatibility_keys}
    if rule_key(rule) in compatibility_keys or rule.key in compatibility_keys:
        return True
    circuit_id = _circuit_id(circuit)
    if (
        circuit_id
        and f"{rule.domain}:{circuit_id}:{rule.key}" in compatibility_keys
    ):
        return True
    if rule.legacy:
        return False

    normalized_detail = _normalize_detail_level(detail_level)
    if _DETAIL_ORDER[normalized_detail] < _DETAIL_ORDER[
        _normalize_detail_level(rule.minimum_detail_level)
    ]:
        return False

    if normalized_detail == ENTITY_DETAIL_SIMPLE:
        return rule.create_in_simple
    if normalized_detail == ENTITY_DETAIL_STANDARD:
        return rule.create_in_standard

    if rule.create_in_expert:
        return True
    return rule.group in _normalize_groups(selected_groups)


def _rule_applies_to_circuit(
    rule: EntityCreationRule,
    circuit: Any,
    coordinator: Any,
) -> bool:
    """Return whether the rule's platform-level applicability allows creation."""
    if circuit is None:
        return True

    if rule.domain == "sensor":
        from . import sensor as sensor_platform

        description = _description_by_key(
            sensor_platform.SENSOR_DESCRIPTIONS,
            rule.key,
        )
        configured_circuits = getattr(coordinator, "circuit_configs", None)
        return description is None or sensor_platform.sensor_description_applies(
            description,
            circuit,
            coordinator,
            configured_circuits,
        )
    if rule.domain == "binary_sensor":
        from . import binary_sensor as binary_sensor_platform

        description = _description_by_key(
            binary_sensor_platform.BINARY_SENSOR_DESCRIPTIONS,
            rule.key,
        )
        return (
            description is None
            or binary_sensor_platform.binary_sensor_description_applies(
                description,
                circuit,
                coordinator,
            )
        )
    if rule.domain == "button":
        from . import button as button_platform

        description = _description_by_key(
            button_platform.CIRCUIT_BUTTON_DESCRIPTIONS,
            rule.key,
        )
        return description is None or button_platform.button_description_applies(
            description,
            circuit,
            coordinator,
        )
    if rule.domain == "select":
        from . import select as select_platform

        description = _description_by_key(
            select_platform.CIRCUIT_SELECT_DESCRIPTIONS,
            rule.key,
        )
        return description is None or select_platform.select_description_applies(
            description,
            circuit,
            coordinator,
        )
    if rule.domain == "number":
        from . import number as number_platform

        description = _description_by_key(
            number_platform.CIRCUIT_NUMBER_DESCRIPTIONS,
            rule.key,
        )
        return description is None or number_platform.number_description_applies(
            description,
            circuit,
            coordinator,
        )
    if rule.domain == "switch":
        from . import switch as switch_platform

        description = _description_by_key(
            switch_platform.CIRCUIT_SWITCH_DESCRIPTIONS,
            rule.key,
        )
        return description is None or switch_platform.switch_description_applies(
            description,
            circuit,
            coordinator,
        )
    return True


def _description_by_key(descriptions: Collection[Any], key: str) -> Any | None:
    return next(
        (
            description
            for description in descriptions
            if getattr(description, "key", None) == key
        ),
        None,
    )


def rule_key(rule: EntityCreationRule) -> str:
    """Return the stable compatibility key for a rule."""
    return f"{rule.domain}:{rule.key}"


def compact_creation_rule_for_entity(domain: str, key: str) -> EntityCreationRule:
    """Return compact-model creation metadata for a current entity key."""
    return COMPACT_ENTITY_RULES[(domain, key)]


def compact_creation_rules_by_key() -> Mapping[tuple[str, str], EntityCreationRule]:
    """Return all known compact-model creation rules."""
    return COMPACT_ENTITY_RULES


def legacy_compatibility_keys_for_coordinator(coordinator: Any) -> set[str]:
    """Return legacy entity keys explicitly preserved for this config entry."""
    keys: set[str] = set()
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        if not isinstance(container, Mapping):
            continue
        raw_value = container.get(CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS)
        keys.update(_normalize_legacy_compatibility_keys(raw_value))
    return keys


def legacy_compatibility_keys_for_setup(
    hass: Any,
    *,
    entry_id: str,
    coordinator: Any,
) -> set[str]:
    """Return explicit and registry-discovered compatibility keys for setup."""
    keys = legacy_compatibility_keys_for_coordinator(coordinator)
    keys.update(
        legacy_compatibility_keys_for_registry_entries(
            _registry_entries_for_hass(hass),
            entry_id=entry_id,
        )
    )
    return keys


def legacy_compatibility_keys_for_registry_entries(
    entries: Collection[Any],
    *,
    entry_id: str,
) -> set[str]:
    """Return compatibility keys for existing legacy rows not safe to remove."""
    return {
        f"{entry.domain}:{entry.circuit_id}:{entry.key}"
        for entry in legacy_entity_registry_entries(entries, entry_id=entry_id)
        if not entry.cleanup_safe
    }


def legacy_entity_registry_entries(
    entries: Collection[Any],
    *,
    entry_id: str,
) -> tuple[LegacyEntityRegistryEntry, ...]:
    """Classify registry rows covered by compact-model migration metadata."""
    legacy_entries: list[LegacyEntityRegistryEntry] = []
    for entry in entries:
        legacy_entry = _legacy_entity_registry_entry(entry, entry_id=entry_id)
        if legacy_entry is not None:
            legacy_entries.append(legacy_entry)
    return tuple(sorted(legacy_entries, key=lambda item: item.entity_id))


def legacy_entity_registry_entries_for_hass(
    hass: Any,
    *,
    entry_id: str,
) -> tuple[LegacyEntityRegistryEntry, ...]:
    """Return compact-model legacy rows from Home Assistant's entity registry."""
    return legacy_entity_registry_entries(
        _registry_entries_for_hass(hass),
        entry_id=entry_id,
    )


def compact_migration_preview_for_registry(
    entries: Collection[Any],
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Return a compact-model migration preview for registry-backed options UI."""
    matching_entries = tuple(_matching_registry_entries(entries, entry_id=entry_id))
    legacy_entries = legacy_entity_registry_entries(entries, entry_id=entry_id)
    legacy_entity_ids = {entry.entity_id for entry in legacy_entries}
    new_maintenance_switches = _new_maintenance_switch_unique_ids(
        matching_entries,
        legacy_entries,
        entry_id=entry_id,
    )
    will_remove = [
        {
            "entity_id": entry.entity_id,
            "unique_id": entry.unique_id,
            "domain": entry.domain,
            "key": entry.key,
            "replacement": entry.replacement,
            "customized": entry.customized,
            "disabled_by": entry.disabled_by,
            "hidden_by": entry.hidden_by,
        }
        for entry in legacy_entries
    ]
    will_remain = [
        str(getattr(entry, "entity_id", ""))
        for entry in matching_entries
        if str(getattr(entry, "entity_id", "")) not in legacy_entity_ids
    ]
    return {
        "before_count": len(matching_entries),
        "remove_count": len(will_remove),
        "after_count": max(
            len(matching_entries) - len(will_remove) + len(new_maintenance_switches),
            0,
        ),
        "customized_count": sum(1 for entry in legacy_entries if entry.customized),
        "will_remove": will_remove,
        "will_remain": sorted(will_remain),
        "new_maintenance_switches": new_maintenance_switches,
    }


def compact_migration_preview_for_hass(
    hass: Any,
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Return a compact-model migration preview from the live entity registry."""
    return compact_migration_preview_for_registry(
        _registry_entries_for_hass(hass),
        entry_id=entry_id,
    )


def remove_legacy_entity_registry_entries(
    hass: Any,
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Remove legacy registry rows after explicit compact-model confirmation."""
    registry = _entity_registry_for_hass(hass)
    if registry is None:
        return compact_migration_preview_for_registry((), entry_id=entry_id)
    entries = getattr(registry, "entities", {})
    values = tuple(entries.values() if hasattr(entries, "values") else entries)
    preview = compact_migration_preview_for_registry(values, entry_id=entry_id)
    remove = getattr(registry, "async_remove", None)
    if callable(remove):
        for item in preview["will_remove"]:
            remove(item["entity_id"])
    return preview


def selected_entity_groups_for_coordinator(coordinator: Any) -> set[EntityGroup]:
    """Return compact expert groups selected for this config entry."""
    options = getattr(coordinator, "options", {})
    if isinstance(options, Mapping) and CONF_SELECTED_ENTITY_GROUPS in options:
        return _normalize_groups_from_value(options.get(CONF_SELECTED_ENTITY_GROUPS))

    entry_data = getattr(coordinator, "entry_data", {})
    if isinstance(entry_data, Mapping):
        return _normalize_groups_from_value(
            entry_data.get(CONF_SELECTED_ENTITY_GROUPS)
        )
    return set()


def compact_descriptions_for_setup(
    domain: str,
    descriptions: Collection[Any],
    circuit: Any,
    coordinator: Any,
    *,
    hass: Any,
    entry_id: str,
) -> tuple[Any, ...]:
    """Return compact-model descriptions that should be created for setup."""
    from .entity import entity_detail_level_for_coordinator

    compatibility_keys = legacy_compatibility_keys_for_setup(
        hass,
        entry_id=entry_id,
        coordinator=coordinator,
    )
    detail_level = entity_detail_level_for_coordinator(coordinator)
    selected_groups = selected_entity_groups_for_coordinator(coordinator)
    compact_descriptions: list[Any] = []
    for description in descriptions:
        key = str(getattr(description, "key", "")).strip()
        if not key:
            continue
        if should_create_entity(
            rule=compact_creation_rule_for_entity(domain, key),
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
            legacy_compatibility_keys=compatibility_keys,
            applicability_already_checked=True,
        ):
            compact_descriptions.append(description)
    return tuple(compact_descriptions)


def desired_compact_entity_rules(
    *,
    current_entities: Collection[tuple[str, str]],
    circuit: Any,
    coordinator: Any,
    detail_level: str,
    selected_groups: Collection[str | EntityGroup],
    legacy_compatibility_keys: Collection[str],
) -> tuple[EntityCreationRule, ...]:
    """Return compact rules for currently applicable entity keys."""
    rules = (
        compact_creation_rule_for_entity(domain, key)
        for domain, key in sorted(current_entities)
    )
    return tuple(
        rule
        for rule in rules
        if should_create_entity(
            rule=rule,
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
            legacy_compatibility_keys=legacy_compatibility_keys,
        )
    )


def compact_entity_count_preview(
    *,
    current_entities: Collection[tuple[str, str]],
    circuit: Any,
    coordinator: Any,
    detail_level: str,
    selected_groups: Collection[str | EntityGroup],
    legacy_compatibility_keys: Collection[str],
) -> dict[str, int]:
    """Return desired compact entity counts by Home Assistant domain."""
    counts = dict.fromkeys(_COUNT_DOMAINS, 0)
    rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=circuit,
        coordinator=coordinator,
        detail_level=detail_level,
        selected_groups=selected_groups,
        legacy_compatibility_keys=legacy_compatibility_keys,
    )
    for rule in rules:
        counts[rule.domain] = counts.get(rule.domain, 0) + 1
    counts["total"] = sum(counts.values())
    return counts


def _normalize_detail_level(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _DETAIL_ORDER:
        return normalized
    return DEFAULT_ENTITY_DETAIL_LEVEL


def _normalize_groups(groups: Collection[str | EntityGroup]) -> set[EntityGroup]:
    normalized: set[EntityGroup] = set()
    for group in groups:
        if isinstance(group, EntityGroup):
            normalized.add(group)
            continue
        try:
            normalized.add(EntityGroup(str(group)))
        except ValueError:
            continue
    return normalized


def _normalize_legacy_compatibility_keys(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value} if value.strip() else set()
    if isinstance(value, Collection):
        return {str(item) for item in value if str(item).strip()}
    return set()


def _normalize_groups_from_value(value: Any) -> set[EntityGroup]:
    if value is None:
        return set()
    if isinstance(value, EntityGroup):
        return {value}
    if isinstance(value, str):
        return _normalize_groups((value,))
    if isinstance(value, Collection):
        return _normalize_groups(value)
    return set()


def _entity_registry_for_hass(hass: Any) -> Any | None:
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return getattr(hass, "entity_registry", None)
    try:
        return er.async_get(hass)
    except (AttributeError, TypeError):
        return getattr(hass, "entity_registry", None)


def _registry_entries_for_hass(hass: Any) -> tuple[Any, ...]:
    registry = _entity_registry_for_hass(hass)
    if registry is None:
        return ()
    entries = getattr(registry, "entities", {})
    values = entries.values() if hasattr(entries, "values") else entries
    return tuple(values)


def _matching_registry_entries(
    entries: Collection[Any],
    *,
    entry_id: str,
) -> tuple[Any, ...]:
    return tuple(
        entry
        for entry in entries
        if getattr(entry, "config_entry_id", None) == entry_id
        and getattr(entry, "platform", None) == DOMAIN
        and str(getattr(entry, "entity_id", "")).partition(".")[0] in _COUNT_DOMAINS
    )


def _legacy_entity_registry_entry(
    entry: Any,
    *,
    entry_id: str,
) -> LegacyEntityRegistryEntry | None:
    if (
        getattr(entry, "config_entry_id", None) != entry_id
        or getattr(entry, "platform", None) != DOMAIN
    ):
        return None
    entity_id = str(getattr(entry, "entity_id", ""))
    domain = entity_id.partition(".")[0]
    if domain not in _COUNT_DOMAINS:
        return None
    unique_id = str(getattr(entry, "unique_id", ""))
    if not unique_id.startswith(f"{entry_id}_"):
        return None
    key = _legacy_key_from_unique_id(unique_id, domain=domain)
    if key is None:
        return None
    circuit_id = _legacy_circuit_id_from_unique_id(
        unique_id,
        entry_id=entry_id,
        key=key,
    )
    if not circuit_id:
        return None
    disabled_by = _registry_marker_name(getattr(entry, "disabled_by", None))
    hidden_by = _registry_marker_name(getattr(entry, "hidden_by", None))
    customized = _registry_entry_has_user_customization(
        entry,
        disabled_by=disabled_by,
        hidden_by=hidden_by,
    )
    cleanup_safe = (
        not customized
        and (disabled_by == "integration" or hidden_by == "integration")
    )
    return LegacyEntityRegistryEntry(
        entity_id=entity_id,
        unique_id=unique_id,
        circuit_id=circuit_id,
        domain=domain,
        key=key,
        replacement=LEGACY_ENTITY_REPLACEMENTS[key],
        disabled_by=disabled_by,
        hidden_by=hidden_by,
        customized=customized,
        cleanup_safe=cleanup_safe,
    )


def _legacy_key_from_unique_id(unique_id: str, *, domain: str) -> str | None:
    legacy_rules = (
        rule
        for rule in COMPACT_ENTITY_RULES.values()
        if rule.key in LEGACY_ENTITY_REPLACEMENTS and rule.domain == domain
    )
    for rule in sorted(legacy_rules, key=lambda item: len(item.key), reverse=True):
        if unique_id.endswith(f"_{rule.key}"):
            return rule.key
    return None


def _legacy_circuit_id_from_unique_id(
    unique_id: str,
    *,
    entry_id: str,
    key: str,
) -> str:
    return unique_id.removeprefix(f"{entry_id}_").removesuffix(f"_{key}")


def _circuit_id(circuit: Any) -> str:
    if circuit is None:
        return ""
    if isinstance(circuit, Mapping):
        return str(circuit.get("circuit_id") or circuit.get("id") or "")
    return str(getattr(circuit, "circuit_id", "") or "")


def _registry_entry_has_user_customization(
    entry: Any,
    *,
    disabled_by: str | None,
    hidden_by: str | None,
) -> bool:
    if disabled_by == "user" or hidden_by == "user":
        return True
    for attribute in ("name", "name_by_user", "icon", "area_id"):
        if getattr(entry, attribute, None):
            return True
    return False


def _registry_marker_name(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", None)
    raw_name = getattr(value, "name", None)
    text = str(raw_value or raw_name or value).split(".")[-1].strip().lower()
    return text or None


def _new_maintenance_switch_unique_ids(
    entries: Collection[Any],
    legacy_entries: Collection[LegacyEntityRegistryEntry],
    *,
    entry_id: str,
) -> list[str]:
    current_unique_ids = {str(getattr(entry, "unique_id", "")) for entry in entries}
    missing: set[str] = set()
    for entry in legacy_entries:
        if entry.key not in {"start_maintenance", "end_maintenance"}:
            continue
        circuit_id = entry.unique_id.removeprefix(f"{entry_id}_").removesuffix(
            f"_{entry.key}"
        )
        switch_unique_id = f"{entry_id}_{circuit_id}_maintenance"
        if switch_unique_id not in current_unique_ids:
            missing.add(switch_unique_id)
    return sorted(missing)


def _rule(
    domain: str,
    key: str,
    exposure: EntityExposure,
    group: EntityGroup,
    minimum_detail_level: str,
    *,
    simple: bool = False,
    standard: bool = False,
    expert: bool = False,
    replacement: str | None = None,
    legacy: bool = False,
) -> EntityCreationRule:
    return EntityCreationRule(
        key=key,
        domain=domain,
        exposure=exposure,
        group=group,
        minimum_detail_level=minimum_detail_level,
        create_in_simple=simple,
        create_in_standard=standard,
        create_in_expert=expert,
        replacement=replacement,
        legacy=legacy,
    )


_COUNT_DOMAINS = ("sensor", "binary_sensor", "button", "select", "number", "switch")


def _legacy_sensor(
    key: str,
    replacement: str,
    group: EntityGroup,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.LEGACY,
        group,
        ENTITY_DETAIL_EXPERT,
        replacement=replacement,
        legacy=True,
    )


def _graph_sensor(
    key: str,
    group: EntityGroup,
    *,
    replacement: str | None = None,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.GRAPH,
        group,
        ENTITY_DETAIL_EXPERT,
        replacement=replacement,
    )


def _diagnostic_sensor(
    key: str,
    group: EntityGroup = EntityGroup.DEVELOPER_DIAGNOSTICS,
    *,
    replacement: str | None = None,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.DIAGNOSTIC,
        group,
        ENTITY_DETAIL_EXPERT,
        replacement=replacement,
    )


def _diagnostic_binary(
    key: str,
    group: EntityGroup = EntityGroup.DEVELOPER_DIAGNOSTICS,
    *,
    replacement: str | None = None,
) -> EntityCreationRule:
    return _rule(
        "binary_sensor",
        key,
        EntityExposure.DIAGNOSTIC,
        group,
        ENTITY_DETAIL_EXPERT,
        replacement=replacement,
    )


_RULES: tuple[EntityCreationRule, ...] = (
    _rule(
        "sensor",
        "health_summary",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "activity_summary",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "electrical_health",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "energy_summary",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "daily_energy_usage",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "binary_sensor",
        "running",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "select",
        "alert_sensitivity",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "button",
        "relearn_baseline",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "number",
        "daily_energy_goal",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "switch",
        "maintenance",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "weather_context",
        EntityExposure.FEATURE,
        EntityGroup.WEATHER,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "water_flow_correlation",
        EntityExposure.FEATURE,
        EntityGroup.WATER,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "binary_sensor",
        "water_flow_mismatch",
        EntityExposure.FEATURE,
        EntityGroup.WATER,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "rain_pump_correlation",
        EntityExposure.FEATURE,
        EntityGroup.WATER,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "billing_cycle_usage",
        EntityExposure.FEATURE,
        EntityGroup.BILLING_COST,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "cost_cycle",
        EntityExposure.FEATURE,
        EntityGroup.BILLING_COST,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "capacity_usage",
        EntityExposure.FEATURE,
        EntityGroup.DEMAND_CAPACITY,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "leg_imbalance",
        EntityExposure.FEATURE,
        EntityGroup.ELECTRICAL_SCORES,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "always_on_power",
        EntityExposure.FEATURE,
        EntityGroup.STANDBY,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "standby_status",
        EntityExposure.FEATURE,
        EntityGroup.STANDBY,
        ENTITY_DETAIL_STANDARD,
        standard=True,
        expert=True,
    ),
    _diagnostic_binary("learning"),
    _diagnostic_binary("data_quality_problem"),
    _diagnostic_binary(
        "maintenance",
        replacement="switch.<circuit>_maintenance",
    ),
    _diagnostic_sensor("settings_suggestions"),
    _diagnostic_sensor("anomaly_score"),
    _diagnostic_sensor("circuit_mode"),
    _diagnostic_sensor("power_flow"),
    _graph_sensor("energy_usage_share", EntityGroup.ENERGY_DETAIL),
    _graph_sensor("energy_goal_usage", EntityGroup.ENERGY_DETAIL),
    _diagnostic_sensor("energy_goal_status", EntityGroup.ENERGY_DETAIL),
    _diagnostic_sensor("energy_usage_status", EntityGroup.ENERGY_DETAIL),
    _diagnostic_sensor("energy_dashboard_status", EntityGroup.ENERGY_DETAIL),
    _graph_sensor("current_demand", EntityGroup.DEMAND_CAPACITY),
    _graph_sensor("peak_demand", EntityGroup.DEMAND_CAPACITY),
    _graph_sensor("demand_limit_usage", EntityGroup.DEMAND_CAPACITY),
    _graph_sensor("demand_peak_rank", EntityGroup.DEMAND_CAPACITY),
    _diagnostic_sensor("demand_status", EntityGroup.DEMAND_CAPACITY),
    _diagnostic_sensor("demand_peak_status", EntityGroup.DEMAND_CAPACITY),
    _diagnostic_sensor("capacity_status", EntityGroup.DEMAND_CAPACITY),
    _legacy_sensor(
        "billing_cycle_budget_usage",
        "sensor.<circuit>_billing_cycle_usage",
        EntityGroup.BILLING_COST,
    ),
    _graph_sensor("billing_cycle_forecast", EntityGroup.BILLING_FORECASTS),
    _legacy_sensor(
        "billing_cycle_status",
        "sensor.<circuit>_billing_cycle_usage",
        EntityGroup.BILLING_COST,
    ),
    _legacy_sensor(
        "cost_current_rate",
        "sensor.<circuit>_cost_cycle",
        EntityGroup.BILLING_COST,
    ),
    _graph_sensor("cost_cycle_forecast", EntityGroup.BILLING_FORECASTS),
    _legacy_sensor(
        "cost_status",
        "sensor.<circuit>_cost_cycle",
        EntityGroup.BILLING_COST,
    ),
    _graph_sensor("always_on_limit_usage", EntityGroup.STANDBY),
    _graph_sensor("monitored_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("balance_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("monitored_coverage", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("balance_status", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_generation_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_surplus_power", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("solar_flow_status", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("solar_surplus_status", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("utility_comparison_status", EntityGroup.MAINS_SOLAR),
    _legacy_sensor(
        "solar_site_consumption_power",
        "sensor.<circuit>_solar_flow_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_grid_import_power",
        "sensor.<circuit>_solar_flow_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_grid_export_power",
        "sensor.<circuit>_solar_flow_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_self_consumption",
        "sensor.<circuit>_solar_flow_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_powered",
        "sensor.<circuit>_solar_flow_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_flexible_load_power",
        "solar load-shift evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_flexible_load_coverage",
        "solar load-shift evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_load_shift_power",
        "sensor.<circuit>_solar_surplus_power and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "solar_load_shift_status",
        "sensor.<circuit>_solar_surplus_status and evidence panel",
        EntityGroup.MAINS_SOLAR,
    ),
    _legacy_sensor(
        "utility_comparison_difference",
        "sensor.<circuit>_utility_comparison_status",
        EntityGroup.MAINS_SOLAR,
    ),
    _graph_sensor("nilm_signature_count", EntityGroup.NILM),
    _graph_sensor("nilm_unknown_loads", EntityGroup.NILM),
    _graph_sensor("nilm_unmatched_load_percentage", EntityGroup.NILM),
    _diagnostic_sensor("nilm_topology_status", EntityGroup.NILM),
    _graph_sensor("water_flow_mismatch_minutes", EntityGroup.WATER),
    _diagnostic_sensor("recent_activity"),
    _rule(
        "sensor",
        "run_cycle_count",
        EntityExposure.GRAPH,
        EntityGroup.CYCLE_METRICS,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "run_cycle_runtime",
        EntityExposure.GRAPH,
        EntityGroup.CYCLE_METRICS,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "run_cycle_duty_cycle",
        EntityExposure.GRAPH,
        EntityGroup.CYCLE_METRICS,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "power_quality_score",
        EntityExposure.GRAPH,
        EntityGroup.ELECTRICAL_SCORES,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "metric_consistency_score",
        EntityExposure.GRAPH,
        EntityGroup.ELECTRICAL_SCORES,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "reactive_power_drift",
        EntityExposure.GRAPH,
        EntityGroup.POWER_QUALITY_DRIFT,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "apparent_power_drift",
        EntityExposure.GRAPH,
        EntityGroup.POWER_QUALITY_DRIFT,
        ENTITY_DETAIL_EXPERT,
    ),
    _rule(
        "sensor",
        "power_factor_drift",
        EntityExposure.GRAPH,
        EntityGroup.POWER_QUALITY_DRIFT,
        ENTITY_DETAIL_EXPERT,
    ),
    _legacy_sensor(
        "sensitivity",
        "select.<circuit>_alert_sensitivity",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "readiness",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "learning_progress",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "data_quality_checklist",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "alert_evidence",
        "Evidence panel and sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "last_event",
        "Evidence panel or sensor.<circuit>_activity_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "recent_activity_count",
        "Evidence panel or optional recent activity timeline",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
    ),
    _legacy_sensor(
        "power_quality_evidence",
        "sensor.<circuit>_electrical_health",
        EntityGroup.POWER_QUALITY_DRIFT,
    ),
    _legacy_sensor(
        "metric_consistency_status",
        "sensor.<circuit>_electrical_health",
        EntityGroup.ELECTRICAL_SCORES,
    ),
    _legacy_sensor(
        "leg_imbalance_status",
        "sensor.<circuit>_electrical_health",
        EntityGroup.ELECTRICAL_SCORES,
    ),
    _legacy_sensor(
        "run_cycle_status",
        "sensor.<circuit>_activity_summary",
        EntityGroup.CYCLE_METRICS,
    ),
    _legacy_sensor(
        "standby_threshold",
        "Advanced Circuit Settings",
        EntityGroup.STANDBY,
    ),
    _legacy_sensor(
        "outdoor_temperature",
        "Configured outdoor temperature source entity",
        EntityGroup.WEATHER,
    ),
    _rule(
        "button",
        "start_maintenance",
        EntityExposure.LEGACY,
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        ENTITY_DETAIL_EXPERT,
        replacement="switch.<circuit>_maintenance",
        legacy=True,
    ),
    _rule(
        "button",
        "end_maintenance",
        EntityExposure.LEGACY,
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        ENTITY_DETAIL_EXPERT,
        replacement="switch.<circuit>_maintenance",
        legacy=True,
    ),
)

COMPACT_ENTITY_RULES: Mapping[tuple[str, str], EntityCreationRule] = {
    (rule.domain, rule.key): rule for rule in _RULES
}
