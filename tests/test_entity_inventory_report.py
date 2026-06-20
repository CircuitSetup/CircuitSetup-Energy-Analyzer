from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.const import (
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from scripts.entity_inventory import (
    REPRESENTATIVE_SCENARIO_IDS,
    build_inventory_report,
)
from scripts.report_compact_entity_inventory import _build_after_report


def test_inventory_report_covers_representative_before_count_scenarios() -> None:
    report = build_inventory_report()
    scenario_ids = {scenario["scenario_id"] for scenario in report["scenarios"]}

    assert set(REPRESENTATIVE_SCENARIO_IDS) <= scenario_ids
    assert {
        "refrigerator",
        "washer",
        "dryer_dual_phase",
        "hvac",
        "water_heater",
        "ev_charger",
        "sump_pump_with_rain",
        "water_pump_with_flow",
        "solar_inverter",
        "mains_nilm",
        "mixed_circuit",
    } <= scenario_ids


def test_inventory_report_pins_current_entity_count_baseline() -> None:
    report = build_inventory_report()
    by_scenario = {
        scenario["scenario_id"]: scenario for scenario in report["scenarios"]
    }

    refrigerator = by_scenario["refrigerator"]["detail_levels"][ENTITY_DETAIL_SIMPLE]
    hvac = by_scenario["hvac"]["detail_levels"][ENTITY_DETAIL_SIMPLE]
    washer = by_scenario["washer"]["detail_levels"][ENTITY_DETAIL_SIMPLE]

    assert refrigerator["created"]["total"] == 55
    assert refrigerator["created"]["sensor"] == 45
    assert refrigerator["created"]["button"] == 4
    assert "sensor.refrigerator_sensitivity" in refrigerator["created"]["entity_ids"]
    assert (
        "select.refrigerator_alert_sensitivity"
        in refrigerator["created"]["entity_ids"]
    )

    assert hvac["created"]["total"] == 67
    assert "sensor.hvac_outdoor_temperature" in hvac["created"]["entity_ids"]

    assert washer["created"]["total"] == 58
    assert "binary_sensor.washer_water_flow_mismatch" in washer["created"]["entity_ids"]


def test_inventory_variants_keep_optional_settings_separate() -> None:
    report = build_inventory_report()
    washer = next(
        scenario
        for scenario in report["scenarios"]
        if scenario["scenario_id"] == "washer"
    )

    full = washer["variants"]["full_electrical_sources"]["detail_levels"][
        ENTITY_DETAIL_SIMPLE
    ]
    optional = washer["variants"]["all_applicable_optional_settings"][
        "detail_levels"
    ][ENTITY_DETAIL_SIMPLE]
    full_ids = set(full["created"]["entity_ids"])
    optional_ids = set(optional["created"]["entity_ids"])

    assert optional["created"]["total"] > full["created"]["total"]
    assert "sensor.washer_billing_cycle_usage" not in full_ids
    assert "sensor.washer_cost_cycle" not in full_ids
    assert "sensor.washer_water_flow_correlation" not in full_ids
    assert "binary_sensor.washer_water_flow_mismatch" not in full_ids
    assert {
        "sensor.washer_billing_cycle_usage",
        "sensor.washer_cost_cycle",
        "sensor.washer_water_flow_correlation",
        "binary_sensor.washer_water_flow_mismatch",
    } <= optional_ids


def test_inventory_report_distinguishes_created_enabled_disabled_and_hidden() -> None:
    report = build_inventory_report()
    refrigerator = next(
        scenario
        for scenario in report["scenarios"]
        if scenario["scenario_id"] == "refrigerator"
    )

    simple = refrigerator["detail_levels"][ENTITY_DETAIL_SIMPLE]
    standard = refrigerator["detail_levels"][ENTITY_DETAIL_STANDARD]
    expert = refrigerator["detail_levels"][ENTITY_DETAIL_EXPERT]

    assert (
        simple["created"]["total"]
        == standard["created"]["total"]
        == expert["created"]["total"]
    )
    assert (
        simple["enabled"]["total"]
        < standard["enabled"]["total"]
        < expert["enabled"]["total"]
    )
    assert (
        simple["disabled"]["total"]
        > standard["disabled"]["total"]
        > expert["disabled"]["total"]
    )
    assert "sensor.refrigerator_recent_activity" in simple["hidden"]["entity_ids"]
    assert "binary_sensor.refrigerator_learning" in simple["hidden"]["entity_ids"]


def test_compact_inventory_report_keeps_count_bounds_and_switch_replacement() -> None:
    report = _build_after_report()
    refrigerator = next(
        scenario
        for scenario in report["scenarios"]
        if scenario["scenario_id"] == "refrigerator"
    )
    simple_keys = set(refrigerator["detail_levels"]["simple"]["created"]["keys"])

    assert "switch:maintenance" in simple_keys
    assert "button:pause_alerts" not in simple_keys
    assert max(
        scenario["detail_levels"]["simple"]["created"]["total"]
        for scenario in report["scenarios"]
    ) == 10
    assert max(
        scenario["detail_levels"]["standard"]["created"]["total"]
        for scenario in report["scenarios"]
    ) == 17
    assert all(
        scenario["detail_levels"]["expert_all_groups"]["created"]["total"] <= 50
        for scenario in report["scenarios"]
    )
