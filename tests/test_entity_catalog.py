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
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
    EntityCreationRule,
    EntityExposure,
    EntityGroup,
    compact_creation_rule_for_entity,
    compact_creation_rules_by_key,
    compact_descriptions_for_setup,
    compact_entity_count_preview,
    desired_compact_entity_rules,
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
    )
    assert not should_create_entity(
        rule=feature,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
    )
    assert should_create_entity(
        rule=feature,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_STANDARD,
        selected_groups=(),
    )
    assert not should_create_entity(
        rule=graph,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups=(),
    )
    assert should_create_entity(
        rule=graph,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.CYCLE_METRICS},
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
        )










def test_pause_alerts_button_is_not_a_current_compact_entity() -> None:
    assert ("button", "pause_alerts") not in compact_creation_rules_by_key()


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
    )
    assert should_create_entity(
        rule=rule,
        circuit=with_energy,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
    )






def test_compact_descriptions_for_setup_filters_entity_descriptions() -> None:
    descriptions = (
        SimpleNamespace(key="health_summary"),
        SimpleNamespace(key="billing_cycle_forecast"),
        SimpleNamespace(key="sensitivity"),
    )
    coordinator = SimpleNamespace(options={}, entry_data={})

    filtered = compact_descriptions_for_setup(
        "sensor",
        descriptions,
        None,
        coordinator,
    )

    assert [description.key for description in filtered] == ["health_summary"]


def test_compact_creation_catalog_rules_have_entity_descriptions() -> None:
    description_keys = {
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

    missing = set(compact_creation_rules_by_key()) - description_keys

    assert missing == set()


def test_desired_compact_rules_preview_uses_current_applicability() -> None:
    current_entities = {
        ("sensor", "health_summary"),
        ("sensor", "activity_summary"),
        ("sensor", "billing_cycle_usage"),
        ("sensor", "run_cycle_runtime"),
        ("binary_sensor", "running"),
        ("select", "alert_sensitivity"),
    }

    simple_rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_SIMPLE,
        selected_groups=(),
    )
    expert_rules = desired_compact_entity_rules(
        current_entities=current_entities,
        circuit=None,
        coordinator=None,
        detail_level=ENTITY_DETAIL_EXPERT,
        selected_groups={EntityGroup.CYCLE_METRICS},
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
    ) == {
        "sensor": 2,
        "binary_sensor": 1,
        "button": 0,
        "select": 1,
        "number": 0,
        "switch": 0,
        "total": 4,
    }
