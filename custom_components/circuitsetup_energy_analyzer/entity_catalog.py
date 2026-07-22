from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .const import (
    CONF_SELECTED_ENTITY_GROUPS,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)


class EntityExposure(StrEnum):
    """Compact entity-model exposure class."""

    CORE = "core"
    FEATURE = "feature"
    GRAPH = "graph"
    DIAGNOSTIC = "diagnostic"


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
    applicability_already_checked: bool = False,
) -> bool:
    """Return whether the compact model should create a described entity."""
    if (
        not applicability_already_checked
        and not _rule_applies_to_circuit(rule, circuit, coordinator)
    ):
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


def compact_creation_rule_for_entity(domain: str, key: str) -> EntityCreationRule:
    """Return compact-model creation metadata for a current entity key."""
    return COMPACT_ENTITY_RULES[(domain, key)]


def compact_creation_rules_by_key() -> Mapping[tuple[str, str], EntityCreationRule]:
    """Return all known compact-model creation rules."""
    return COMPACT_ENTITY_RULES


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
) -> tuple[Any, ...]:
    """Return compact-model descriptions that should be created for setup."""
    from .entity import entity_detail_level_for_coordinator

    detail_level = entity_detail_level_for_coordinator(coordinator)
    selected_groups = selected_entity_groups_for_coordinator(coordinator)
    compact_descriptions: list[Any] = []
    for description in descriptions:
        key = str(getattr(description, "key", "")).strip()
        if not key:
            continue
        rule = COMPACT_ENTITY_RULES.get((domain, key))
        if rule is None:
            continue
        if should_create_entity(
            rule=rule,
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
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
        )
    )


def compact_entity_count_preview(
    *,
    current_entities: Collection[tuple[str, str]],
    circuit: Any,
    coordinator: Any,
    detail_level: str,
    selected_groups: Collection[str | EntityGroup],
) -> dict[str, int]:
    """Return desired compact entity counts by Home Assistant domain."""
    counts = dict.fromkeys(_COUNT_DOMAINS, 0)
    rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=circuit,
        coordinator=coordinator,
        detail_level=detail_level,
        selected_groups=selected_groups,
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
    )


_COUNT_DOMAINS = ("sensor", "binary_sensor", "button", "select", "number", "switch")


def _graph_sensor(
    key: str,
    group: EntityGroup,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.GRAPH,
        group,
        ENTITY_DETAIL_EXPERT,
    )


def _diagnostic_sensor(
    key: str,
    group: EntityGroup = EntityGroup.DEVELOPER_DIAGNOSTICS,
) -> EntityCreationRule:
    return _rule(
        "sensor",
        key,
        EntityExposure.DIAGNOSTIC,
        group,
        ENTITY_DETAIL_EXPERT,
    )


def _diagnostic_binary(
    key: str,
    group: EntityGroup = EntityGroup.DEVELOPER_DIAGNOSTICS,
) -> EntityCreationRule:
    return _rule(
        "binary_sensor",
        key,
        EntityExposure.DIAGNOSTIC,
        group,
        ENTITY_DETAIL_EXPERT,
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
        "sensor",
        "cost_today",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "average_cost_per_day",
        EntityExposure.CORE,
        EntityGroup.CORE,
        ENTITY_DETAIL_SIMPLE,
        simple=True,
        standard=True,
        expert=True,
    ),
    _rule(
        "sensor",
        "average_kwh_per_day",
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
    _diagnostic_binary("maintenance"),
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
    _graph_sensor("billing_cycle_forecast", EntityGroup.BILLING_FORECASTS),
    _graph_sensor("cost_cycle_forecast", EntityGroup.BILLING_FORECASTS),
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
)

COMPACT_ENTITY_RULES: Mapping[tuple[str, str], EntityCreationRule] = {
    (rule.domain, rule.key): rule for rule in _RULES
}
