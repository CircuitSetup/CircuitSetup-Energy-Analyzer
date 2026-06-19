from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
)
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_SELECTED_ENTITY_GROUPS,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
    CORE_DUPLICATE_REMOVAL_PHASE,
    ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    EntityCreationRule,
    EntityExposure,
    EntityGroup,
    compact_creation_rule_for_entity,
    compact_creation_rules_by_key,
    compact_entity_count_preview,
    compact_sensor_rule_is_setup_managed,
    desired_compact_entity_rules,
    selected_entity_groups_for_coordinator,
    should_create_entity,
)


def test_should_create_entity_respects_detail_levels_and_selected_groups() -> None:
    core = EntityCreationRule(
        key="health_summary",
        domain="sensor",
        exposure=EntityExposure.CORE,
        group=EntityGroup.CORE,
        minimum_detail_level=ENTITY_DETAIL_SIMPLE,
        create_in_simple=True,
        create_in_standard=True,
        create_in_expert=True,
    )
    feature = EntityCreationRule(
        key="billing_cycle_usage",
        domain="sensor",
        exposure=EntityExposure.FEATURE,
        group=EntityGroup.BILLING_COST,
        minimum_detail_level=ENTITY_DETAIL_STANDARD,
        create_in_standard=True,
        create_in_expert=True,
    )
    graph = EntityCreationRule(
        key="run_cycle_runtime",
        domain="sensor",
        exposure=EntityExposure.GRAPH,
        group=EntityGroup.CYCLE_METRICS,
        minimum_detail_level=ENTITY_DETAIL_EXPERT,
    )

    assert should_create_entity(
        rule=core,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert not should_create_entity(
        rule=feature,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert should_create_entity(
        rule=feature,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_STANDARD,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert not should_create_entity(
        rule=graph,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert should_create_entity(
        rule=graph,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.CYCLE_METRICS},
        legacy_compatibility_keys=(),
    )


def test_selected_entity_groups_options_override_entry_data() -> None:
    coordinator = SimpleNamespace(
        options={CONF_SELECTED_ENTITY_GROUPS: []},
        entry_data={CONF_SELECTED_ENTITY_GROUPS: [EntityGroup.CYCLE_METRICS.value]},
    )

    assert selected_entity_groups_for_coordinator(coordinator) == set()
    assert selected_entity_groups_for_coordinator(
        SimpleNamespace(
            options={},
            entry_data={
                CONF_SELECTED_ENTITY_GROUPS: [EntityGroup.POWER_QUALITY_DRIFT.value],
            },
        )
    ) == {EntityGroup.POWER_QUALITY_DRIFT}


def test_should_create_entity_defaults_invalid_detail_levels_to_simple() -> None:
    feature = EntityCreationRule(
        key="billing_cycle_usage",
        domain="sensor",
        exposure=EntityExposure.FEATURE,
        group=EntityGroup.BILLING_COST,
        minimum_detail_level=ENTITY_DETAIL_STANDARD,
        create_in_standard=True,
        create_in_expert=True,
    )

    for detail_level in (None, "", "bogus"):
        assert not should_create_entity(
            rule=feature,
            circuit=None,
            coordinator=None,
            detail_level=detail_level,
            selected_groups=(),
            legacy_compatibility_keys=(),
        )


def test_should_create_entity_preserves_legacy_compatibility_keys() -> None:
    rule = EntityCreationRule(
        key="sensitivity",
        domain="sensor",
        exposure=EntityExposure.LEGACY,
        group=EntityGroup.DEVELOPER_DIAGNOSTICS,
        minimum_detail_level=ENTITY_DETAIL_EXPERT,
        replacement="select.<circuit>_alert_sensitivity",
        legacy=True,
    )

    assert not should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.DEVELOPER_DIAGNOSTICS},
        legacy_compatibility_keys=(),
    )
    assert should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys={"sensor:sensitivity"},
    )


def test_compact_creation_rule_documents_requested_replacements() -> None:
    sensitivity = compact_creation_rule_for_entity("sensor", "sensitivity")
    run_cycle_status = compact_creation_rule_for_entity("sensor", "run_cycle_status")
    maintenance_start = compact_creation_rule_for_entity("button", "start_maintenance")

    assert sensitivity.legacy
    assert sensitivity.replacement == "select.<circuit>_alert_sensitivity"
    assert run_cycle_status.legacy
    assert run_cycle_status.group is EntityGroup.CYCLE_METRICS
    assert run_cycle_status.replacement == "sensor.<circuit>_activity_summary"
    assert maintenance_start.legacy
    assert maintenance_start.replacement == "switch.<circuit>_maintenance"


def test_core_duplicate_rules_are_marked_for_phase_two_removal() -> None:
    rules = compact_creation_rules_by_key()

    core_duplicate_sensor_keys = {
        key
        for (domain, key), rule in rules.items()
        if domain == "sensor" and rule.removal_phase == CORE_DUPLICATE_REMOVAL_PHASE
    }

    assert core_duplicate_sensor_keys == {
        "sensitivity",
        "readiness",
        "learning_progress",
        "data_quality_checklist",
        "alert_evidence",
        "last_event",
        "recent_activity_count",
    }
    assert rules[("sensor", "recent_activity")].removal_phase is None
    assert rules[("sensor", "always_on_power")].removal_phase is None
    assert rules[("sensor", "weather_context")].removal_phase is None


def test_electrical_cycle_rules_are_marked_for_phase_three_creation() -> None:
    rules = compact_creation_rules_by_key()

    phase_three_legacy_sensor_keys = {
        key
        for (domain, key), rule in rules.items()
        if domain == "sensor"
        and rule.removal_phase == ELECTRICAL_CYCLE_CONDENSATION_PHASE
    }

    assert phase_three_legacy_sensor_keys == {
        "power_quality_evidence",
        "metric_consistency_status",
        "leg_imbalance_status",
        "run_cycle_status",
    }
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "run_cycle_count")],
    )
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "reactive_power_drift")],
    )
    assert not compact_sensor_rule_is_setup_managed(
        rules[("sensor", "leg_imbalance")],
    )
    assert not compact_sensor_rule_is_setup_managed(
        rules[("sensor", "always_on_power")],
    )


def test_billing_standby_weather_rules_are_marked_for_phase_four_creation() -> None:
    rules = compact_creation_rules_by_key()

    phase_four_sensor_keys = {
        key
        for (domain, key), rule in rules.items()
        if domain == "sensor"
        and rule.removal_phase == "billing_standby_weather_condensation"
    }

    assert phase_four_sensor_keys == {
        "billing_cycle_budget_usage",
        "billing_cycle_status",
        "cost_current_rate",
        "cost_status",
        "standby_threshold",
        "outdoor_temperature",
    }
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "billing_cycle_forecast")],
    )
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "cost_cycle_forecast")],
    )
    assert not compact_sensor_rule_is_setup_managed(
        rules[("sensor", "billing_cycle_usage")],
    )
    assert not compact_sensor_rule_is_setup_managed(
        rules[("sensor", "cost_cycle")],
    )


def test_compact_creation_catalog_covers_every_current_entity_description() -> None:
    current_description_keys = {
        *(
            ("sensor", description.key)
            for description in sensor.SENSOR_DESCRIPTIONS
        ),
        *(
            ("binary_sensor", description.key)
            for description in binary_sensor.BINARY_SENSOR_DESCRIPTIONS
        ),
        *(
            ("button", description.key)
            for description in button.CIRCUIT_BUTTON_DESCRIPTIONS
        ),
        *(
            ("select", description.key)
            for description in select.CIRCUIT_SELECT_DESCRIPTIONS
        ),
        *(
            ("number", description.key)
            for description in number.CIRCUIT_NUMBER_DESCRIPTIONS
        ),
    }

    missing = current_description_keys - set(compact_creation_rules_by_key())

    assert missing == set()


def test_desired_compact_rules_preview_uses_current_applicability() -> None:
    current_entities = {
        ("sensor", "health_summary"),
        ("sensor", "activity_summary"),
        ("sensor", "billing_cycle_usage"),
        ("sensor", "run_cycle_runtime"),
        ("sensor", "sensitivity"),
        ("binary_sensor", "running"),
        ("select", "alert_sensitivity"),
    }

    simple_rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    expert_rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.CYCLE_METRICS},
        legacy_compatibility_keys={"sensor:sensitivity"},
    )

    assert {(rule.domain, rule.key) for rule in simple_rules} == {
        ("sensor", "health_summary"),
        ("sensor", "activity_summary"),
        ("binary_sensor", "running"),
        ("select", "alert_sensitivity"),
    }
    assert {(rule.domain, rule.key) for rule in expert_rules} == current_entities
    assert compact_entity_count_preview(
        current_entities=current_entities,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    ) == {
        "sensor": 2,
        "binary_sensor": 1,
        "button": 0,
        "select": 1,
        "number": 0,
        "switch": 0,
        "total": 4,
    }
