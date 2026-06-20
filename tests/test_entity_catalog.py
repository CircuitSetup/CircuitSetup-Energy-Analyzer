from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_SELECTED_ENTITY_GROUPS,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
    CORE_DUPLICATE_REMOVAL_PHASE,
    ELECTRICAL_CYCLE_CONDENSATION_PHASE,
    LEGACY_ENTITY_REPLACEMENTS,
    MAINTENANCE_SWITCH_CONDENSATION_PHASE,
    EntityCreationRule,
    EntityExposure,
    EntityGroup,
    compact_creation_rule_for_entity,
    compact_creation_rules_by_key,
    compact_entity_count_preview,
    compact_migration_preview_for_registry,
    compact_rule_is_setup_managed,
    compact_sensor_rule_is_setup_managed,
    desired_compact_entity_rules,
    legacy_compatibility_keys_for_registry_entries,
    legacy_entity_registry_entries,
    selected_entity_groups_for_coordinator,
    should_create_entity,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
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


def test_legacy_registry_entries_drive_compatibility_and_preview() -> None:
    entries = [
        SimpleNamespace(
            entity_id="sensor.fridge_sensitivity",
            unique_id="entry-1_fridge_sensitivity",
            config_entry_id="entry-1",
            platform=DOMAIN,
            disabled_by=None,
            hidden_by=None,
        ),
        SimpleNamespace(
            entity_id="select.fridge_alert_sensitivity",
            unique_id="entry-1_fridge_alert_sensitivity",
            config_entry_id="entry-1",
            platform=DOMAIN,
            disabled_by=None,
            hidden_by=None,
        ),
        SimpleNamespace(
            entity_id="sensor.fridge_readiness",
            unique_id="entry-1_fridge_readiness",
            config_entry_id="entry-1",
            platform=DOMAIN,
            disabled_by="integration",
            hidden_by=None,
        ),
        SimpleNamespace(
            entity_id="button.fridge_start_maintenance",
            unique_id="entry-1_fridge_start_maintenance",
            config_entry_id="entry-1",
            platform=DOMAIN,
            disabled_by=None,
            hidden_by="user",
        ),
        SimpleNamespace(
            entity_id="sensor.fridge_power_quality_score",
            unique_id="entry-1_fridge_power_quality_score",
            config_entry_id="entry-1",
            platform=DOMAIN,
            disabled_by=None,
            hidden_by=None,
        ),
        SimpleNamespace(
            entity_id="sensor.other_sensitivity",
            unique_id="other_fridge_sensitivity",
            config_entry_id="other",
            platform=DOMAIN,
            disabled_by=None,
            hidden_by=None,
        ),
    ]

    legacy_entries = legacy_entity_registry_entries(entries, entry_id="entry-1")

    assert [(entry.domain, entry.key) for entry in legacy_entries] == [
        ("button", "start_maintenance"),
        ("sensor", "readiness"),
        ("sensor", "sensitivity"),
    ]
    assert LEGACY_ENTITY_REPLACEMENTS["sensitivity"] == "select:alert_sensitivity"
    assert legacy_compatibility_keys_for_registry_entries(
        entries,
        entry_id="entry-1",
    ) == {
        "button:start_maintenance",
        "sensor:sensitivity",
    }

    preview = compact_migration_preview_for_registry(entries, entry_id="entry-1")

    assert preview["before_count"] == 5
    assert preview["remove_count"] == 3
    assert preview["after_count"] == 3
    assert preview["customized_count"] == 1
    assert {
        item["entity_id"]: item["replacement"]
        for item in preview["will_remove"]
    } == {
        "button.fridge_start_maintenance": "switch:maintenance",
        "sensor.fridge_readiness": "sensor:health_summary#readiness",
        "sensor.fridge_sensitivity": "select:alert_sensitivity",
    }
    assert "select.fridge_alert_sensitivity" in preview["will_remain"]


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


def test_pause_alerts_button_is_expert_developer_diagnostic_opt_in() -> None:
    rule = compact_creation_rule_for_entity("button", "pause_alerts")

    assert rule.group is EntityGroup.DEVELOPER_DIAGNOSTICS
    assert not should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert not should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_STANDARD,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert not should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert should_create_entity(
        rule=rule,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.DEVELOPER_DIAGNOSTICS},
        legacy_compatibility_keys=(),
    )


def test_should_create_entity_checks_feature_source_applicability() -> None:
    rule = compact_creation_rule_for_entity("number", "daily_energy_goal")
    power_only = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    with_energy = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
        ),
    )

    assert not should_create_entity(
        rule=rule,
        circuit=power_only,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )
    assert should_create_entity(
        rule=rule,
        circuit=with_energy,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
        legacy_compatibility_keys=(),
    )


def test_solar_flexible_load_detail_uses_evidence_without_new_entities() -> None:
    rules = compact_creation_rules_by_key()
    legacy_mains_solar_keys = {
        "solar_site_consumption_power",
        "solar_grid_import_power",
        "solar_grid_export_power",
        "solar_self_consumption",
        "solar_powered",
        "solar_flexible_load_power",
        "solar_flexible_load_coverage",
        "solar_load_shift_power",
        "solar_load_shift_status",
        "utility_comparison_difference",
    }

    assert all(rules[("sensor", key)].legacy for key in legacy_mains_solar_keys)
    assert not should_create_entity(
        rule=rules[("sensor", "solar_flexible_load_power")],
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.MAINS_SOLAR},
        legacy_compatibility_keys=(),
    )


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
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "leg_imbalance")],
    )
    assert compact_sensor_rule_is_setup_managed(
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
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "billing_cycle_usage")],
    )
    assert compact_sensor_rule_is_setup_managed(
        rules[("sensor", "cost_cycle")],
    )


def test_maintenance_button_rules_are_marked_for_phase_five_creation() -> None:
    rules = compact_creation_rules_by_key()

    phase_five_button_keys = {
        key
        for (domain, key), rule in rules.items()
        if domain == "button"
        and rule.removal_phase == MAINTENANCE_SWITCH_CONDENSATION_PHASE
    }

    assert phase_five_button_keys == {
        "start_maintenance",
        "end_maintenance",
    }
    assert compact_rule_is_setup_managed(rules[("button", "start_maintenance")])
    assert compact_rule_is_setup_managed(rules[("button", "end_maintenance")])
    assert compact_rule_is_setup_managed(rules[("button", "relearn_baseline")])


def test_phase_six_manages_creation_for_every_catalog_rule() -> None:
    rules = compact_creation_rules_by_key()

    unmanaged = {
        (domain, key)
        for (domain, key), rule in rules.items()
        if not compact_rule_is_setup_managed(rule)
    }

    assert unmanaged == set()


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
        *(
            ("switch", description.key)
            for description in switch.CIRCUIT_SWITCH_DESCRIPTIONS
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
