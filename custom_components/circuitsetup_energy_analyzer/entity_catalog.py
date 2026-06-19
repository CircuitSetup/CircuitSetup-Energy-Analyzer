from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .const import (
    CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS,
    CONF_SELECTED_ENTITY_GROUPS,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)

CORE_DUPLICATE_REMOVAL_PHASE = "core_duplicate_condensation"
ELECTRICAL_CYCLE_CONDENSATION_PHASE = "electrical_cycle_condensation"
BILLING_STANDBY_WEATHER_CONDENSATION_PHASE = (
    "billing_standby_weather_condensation"
)
MAINTENANCE_SWITCH_CONDENSATION_PHASE = "maintenance_switch_condensation"


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
    removal_phase: str | None = None


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
) -> bool:
    """Return whether the compact model should create a described entity."""
    del circuit, coordinator
    compatibility_keys = {str(item) for item in legacy_compatibility_keys}
    if rule.legacy:
        return rule_key(rule) in compatibility_keys or rule.key in compatibility_keys

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


def compact_sensor_rule_is_setup_managed(rule: EntityCreationRule) -> bool:
    """Return whether current compact phases manage this sensor's creation."""
    return compact_rule_is_setup_managed(rule)


def compact_rule_is_setup_managed(rule: EntityCreationRule) -> bool:
    """Return whether current compact phases manage this entity's creation."""
    del rule
    return True


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
    counts = {domain: 0 for domain in _COUNT_DOMAINS}
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
    removal_phase: str | None = None,
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
        removal_phase=removal_phase,
    )


_COUNT_DOMAINS = ("sensor", "binary_sensor", "button", "select", "number", "switch")
_SETUP_MANAGED_REMOVAL_PHASES = frozenset(
    {
        CORE_DUPLICATE_REMOVAL_PHASE,
        ELECTRICAL_CYCLE_CONDENSATION_PHASE,
        BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
        MAINTENANCE_SWITCH_CONDENSATION_PHASE,
    },
)
_SETUP_MANAGED_GRAPH_GROUPS = frozenset(
    {
        EntityGroup.BILLING_FORECASTS,
        EntityGroup.CYCLE_METRICS,
        EntityGroup.ELECTRICAL_SCORES,
        EntityGroup.POWER_QUALITY_DRIFT,
    },
)


def _legacy_sensor(
    key: str,
    replacement: str,
    group: EntityGroup,
    *,
    removal_phase: str | None = None,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.LEGACY,
        group,
        ENTITY_DETAIL_EXPERT,
        replacement=replacement,
        legacy=True,
        removal_phase=removal_phase,
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
        "button",
        "pause_alerts",
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
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _graph_sensor("billing_cycle_forecast", EntityGroup.BILLING_FORECASTS),
    _legacy_sensor(
        "billing_cycle_status",
        "sensor.<circuit>_billing_cycle_usage",
        EntityGroup.BILLING_COST,
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "cost_current_rate",
        "sensor.<circuit>_cost_cycle",
        EntityGroup.BILLING_COST,
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _graph_sensor("cost_cycle_forecast", EntityGroup.BILLING_FORECASTS),
    _legacy_sensor(
        "cost_status",
        "sensor.<circuit>_cost_cycle",
        EntityGroup.BILLING_COST,
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _graph_sensor("always_on_limit_usage", EntityGroup.STANDBY),
    _graph_sensor("monitored_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("balance_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("monitored_coverage", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("balance_status", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_generation_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_grid_import_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_grid_export_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_site_consumption_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_self_consumption", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_surplus_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_powered", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_flexible_load_power", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_flexible_load_coverage", EntityGroup.MAINS_SOLAR),
    _graph_sensor("solar_load_shift_power", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("solar_flow_status", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("solar_surplus_status", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("solar_load_shift_status", EntityGroup.MAINS_SOLAR),
    _graph_sensor("utility_comparison_difference", EntityGroup.MAINS_SOLAR),
    _diagnostic_sensor("utility_comparison_status", EntityGroup.MAINS_SOLAR),
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
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "readiness",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "learning_progress",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "data_quality_checklist",
        "sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "alert_evidence",
        "Evidence panel and sensor.<circuit>_health_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "last_event",
        "Evidence panel or sensor.<circuit>_activity_summary",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "recent_activity_count",
        "Evidence panel or optional recent activity timeline",
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        removal_phase=CORE_DUPLICATE_REMOVAL_PHASE,
    ),
    _legacy_sensor(
        "power_quality_evidence",
        "sensor.<circuit>_electrical_health",
        EntityGroup.POWER_QUALITY_DRIFT,
        removal_phase=ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "metric_consistency_status",
        "sensor.<circuit>_electrical_health",
        EntityGroup.ELECTRICAL_SCORES,
        removal_phase=ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "leg_imbalance_status",
        "sensor.<circuit>_electrical_health",
        EntityGroup.ELECTRICAL_SCORES,
        removal_phase=ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "run_cycle_status",
        "sensor.<circuit>_activity_summary",
        EntityGroup.CYCLE_METRICS,
        removal_phase=ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "standby_threshold",
        "Advanced Circuit Settings",
        EntityGroup.STANDBY,
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _legacy_sensor(
        "outdoor_temperature",
        "Configured outdoor temperature source entity",
        EntityGroup.WEATHER,
        removal_phase=BILLING_STANDBY_WEATHER_CONDENSATION_PHASE,
    ),
    _rule(
        "button",
        "start_maintenance",
        EntityExposure.LEGACY,
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        ENTITY_DETAIL_EXPERT,
        replacement="switch.<circuit>_maintenance",
        legacy=True,
        removal_phase=MAINTENANCE_SWITCH_CONDENSATION_PHASE,
    ),
    _rule(
        "button",
        "end_maintenance",
        EntityExposure.LEGACY,
        EntityGroup.DEVELOPER_DIAGNOSTICS,
        ENTITY_DETAIL_EXPERT,
        replacement="switch.<circuit>_maintenance",
        legacy=True,
        removal_phase=MAINTENANCE_SWITCH_CONDENSATION_PHASE,
    ),
)

COMPACT_ENTITY_RULES: Mapping[tuple[str, str], EntityCreationRule] = {
    (rule.domain, rule.key): rule for rule in _RULES
}
