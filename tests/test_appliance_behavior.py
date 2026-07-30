from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def _baseline(feature: str, median: float, low: float, high: float) -> BaselineStats:
    return BaselineStats(
        feature=feature,
        sample_count=14,
        median=median,
        mad=0.1,
        p10=low,
        p90=high,
        confidence=0.9,
    )


def _config(
    circuit_id: str,
    profile: ApplianceProfile,
    *,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id=circuit_id,
        name=circuit_id.replace("_", " ").title(),
        appliance_profile=profile,
        mode=mode,
    )


def _coordinator(
    config: CircuitConfig,
    state: AnalyzerState,
    store_data: FeatureStoreData | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        circuit_configs=(config,),
        state=state,
        store_data=store_data or FeatureStoreData(),
        entry_id="entry-1",
    )


def _detail(config: CircuitConfig, state: AnalyzerState, store_data=None) -> dict:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload(
        [_coordinator(config, state, store_data)],
        circuit_id=config.circuit_id,
    )
    assert payload["status"] == "ok"
    return payload["detail"]


def test_open_day_energy_with_only_full_day_baseline_stays_learning() -> None:
    state = AnalyzerState()
    state.data_quality_checklist_by_circuit["fridge"] = {
        "required_sensors_present": True,
        "numeric_states_valid": True,
        "source_data_fresh": True,
    }
    state.daily_energy_usage_by_circuit["fridge"] = 0.5
    store_data = FeatureStoreData(
        baselines={
            "fridge:daily_energy_kwh": _baseline("daily_energy_kwh", 2.0, 1.8, 2.2)
        }
    )

    detail = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )

    comparison = detail["today_vs_normal"][0]
    assert comparison["metric_id"] == "daily_energy_kwh"
    assert comparison["label"] == "Energy so far"
    assert comparison["unit"] == "kWh"
    assert comparison["current_value"] == 0.5
    assert comparison["status"] == "learning"
    assert comparison["status"] not in {"higher", "lower"}
    assert comparison.get("comparison_mode") == "same_time_of_day"


def test_early_day_energy_uses_same_time_baseline_and_labels_projection() -> None:
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 0.5
    state.energy_usage_evidence_by_circuit["fridge"] = {
        "comparison_mode": "same_time_of_day",
        "as_of": "2026-07-13T08:00:00-04:00",
        "contextual_expected_range": [0.4, 0.7],
        "contextual_baseline_median_kwh": 0.55,
        "contextual_baseline_confidence": 0.88,
        "projection_value": 1.9,
        "projection_low": 1.7,
        "projection_high": 2.1,
        "projection_confidence": 0.58,
    }
    store_data = FeatureStoreData(
        baselines={
            "fridge:daily_energy_kwh": _baseline(
                "daily_energy_kwh",
                2.0,
                1.8,
                2.2,
            )
        }
    )

    comparison = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )["today_vs_normal"][0]

    assert comparison["label"] == "Energy so far"
    assert comparison.get("comparison_mode") == "same_time_of_day"
    assert comparison.get("as_of") == "2026-07-13T08:00:00-04:00"
    assert (comparison["normal_low"], comparison["normal_high"]) == (0.4, 0.7)
    assert (comparison["normal_low"], comparison["normal_high"]) != (1.8, 2.2)
    assert comparison["status"] == "normal"
    assert comparison.get("projection_value") == 1.9
    assert (comparison.get("projection_low"), comparison.get("projection_high")) == (
        1.7,
        2.1,
    )
    assert comparison.get("projection_confidence", 1.0) < comparison["confidence"]


def test_today_vs_normal_learning_and_missing_data_statuses() -> None:
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 1.9

    learning = _detail(_config("fridge", ApplianceProfile.REFRIGERATOR), state)
    assert learning["today_vs_normal"][0]["status"] == "learning"

    missing = _detail(
        _config("freezer", ApplianceProfile.FREEZER),
        AnalyzerState(),
        FeatureStoreData(
            baselines={
                "freezer:daily_energy_kwh": _baseline(
                    "daily_energy_kwh",
                    1.1,
                    0.9,
                    1.3,
                )
            }
        ),
    )
    assert missing["today_vs_normal"][0]["status"] == "missing_data"


def test_partial_period_metrics_with_full_day_baselines_stay_learning() -> None:
    state = AnalyzerState()
    state.run_cycle_runtime_seconds_by_circuit["hvac"] = 25_200.0
    state.run_cycle_count_by_circuit["hvac"] = 12
    state.peak_demand_w_by_circuit["hvac"] = 5200.0
    store_data = FeatureStoreData(
        baselines={
            "hvac:runtime_today_seconds": _baseline(
                "runtime_today_seconds", 18_000.0, 14_400.0, 21_600.0
            ),
            "hvac:run_count_today": _baseline(
                "run_count_today", 6.0, 4.0, 8.0
            ),
            "hvac:demand_peak_w": _baseline(
                "demand_peak_w", 4600.0, 4200.0, 5000.0
            ),
        }
    )

    comparisons = {
        item["metric_id"]: item
        for item in _detail(_config("hvac", ApplianceProfile.HVAC), state, store_data)[
            "today_vs_normal"
        ]
    }

    assert {
        metric_id: comparisons[metric_id]["status"]
        for metric_id in (
            "runtime_today_seconds",
            "run_count_today",
            "demand_peak_w",
        )
    } == {
        "runtime_today_seconds": "learning",
        "run_count_today": "learning",
        "demand_peak_w": "learning",
    }


def test_contextual_energy_comparison_uses_existing_evidence_range() -> None:
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["hvac"] = 8.5
    state.energy_usage_evidence_by_circuit["hvac"] = {
        "contextual_expected_range": [7.0, 10.0],
        "contextual_baseline_median_kwh": 8.0,
        "contextual_baseline_confidence": 0.83,
    }

    detail = _detail(_config("hvac", ApplianceProfile.HVAC), state)

    comparison = detail["today_vs_normal"][0]
    assert comparison["status"] == "normal"
    assert comparison["source"] == "contextual_baseline"
    assert comparison["normal_low"] == 7.0
    assert comparison["normal_high"] == 10.0


def test_today_vs_normal_uses_accumulated_cost_without_flat_rate_baseline() -> None:
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 2.4
    state.cost_current_rate_by_circuit["fridge"] = 0.25
    state.cost_today_by_circuit["fridge"] = 0.6
    state.cost_evidence_by_circuit["fridge"] = {"cost_today_status": "actual"}
    store_data = FeatureStoreData(
        baselines={
            "fridge:daily_energy_kwh": _baseline("daily_energy_kwh", 2.0, 1.8, 2.2)
        }
    )

    detail = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )
    comparisons = {item["metric_id"]: item for item in detail["today_vs_normal"]}

    assert detail["cost_today"] == 0.6
    cost = comparisons["cost_today"]
    assert cost["label"] == "Cost so far"
    assert cost["unit"] == "currency"
    assert cost["current_value"] == 0.6
    assert cost["normal_low"] is None
    assert cost["normal_high"] is None
    assert cost["normal_median"] is None
    assert cost["status"] == "learning"
    assert cost["confidence"] is None
    assert cost["source"] == "current_state"
    assert cost.get("comparison_mode") == "same_time_of_day"


def test_running_power_uses_running_baseline() -> None:
    state = AnalyzerState()
    state.latest_real_power_w_by_circuit["fridge"] = 104.0
    state.run_cycle_status_by_circuit["fridge"] = "running"
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": _baseline("real_power", 100.0, 90.0, 110.0),
            "fridge:standby_power_w": _baseline(
                "standby_power_w",
                5.0,
                3.0,
                8.0,
            ),
        }
    )

    detail = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )
    power = {item["metric_id"]: item for item in detail["today_vs_normal"]}[
        "current_power_w"
    ]

    assert power.get("comparison_mode") == "running_state"
    assert (power["normal_low"], power["normal_high"]) == (90.0, 110.0)
    assert power["status"] == "normal"


def test_idle_power_uses_standby_baseline() -> None:
    state = AnalyzerState()
    state.latest_real_power_w_by_circuit["fridge"] = 5.0
    state.run_cycle_status_by_circuit["fridge"] = "idle"
    state.standby_status_by_circuit["fridge"] = "standby"
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": _baseline("real_power", 100.0, 90.0, 110.0),
            "fridge:standby_power_w": _baseline(
                "standby_power_w",
                5.0,
                3.0,
                8.0,
            ),
        }
    )

    detail = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )
    power = {item["metric_id"]: item for item in detail["today_vs_normal"]}[
        "current_power_w"
    ]

    assert power.get("comparison_mode") == "current_state"
    assert (power["normal_low"], power["normal_high"]) == (3.0, 8.0)
    assert power["status"] == "normal"


def test_unknown_operating_state_does_not_use_standby_baseline() -> None:
    store_data = FeatureStoreData(
        baselines={
            "fridge:standby_power_w": _baseline(
                "standby_power_w",
                5.0,
                3.0,
                8.0,
            )
        }
    )

    for operating_state in ("unknown", "learning"):
        state = AnalyzerState()
        state.latest_real_power_w_by_circuit["fridge"] = 5.0
        state.run_cycle_status_by_circuit["fridge"] = operating_state

        power = {
            item["metric_id"]: item
            for item in _detail(
                _config("fridge", ApplianceProfile.REFRIGERATOR),
                state,
                store_data,
            )["today_vs_normal"]
        }["current_power_w"]

        assert power["status"] == "learning"
        assert power["normal_low"] is None
        assert power["normal_high"] is None


def test_mixed_circuit_suppresses_appliance_running_power_comparison() -> None:
    state = AnalyzerState()
    state.latest_real_power_w_by_circuit["kitchen"] = 104.0
    state.run_cycle_status_by_circuit["kitchen"] = "running"
    store_data = FeatureStoreData(
        baselines={
            "kitchen:real_power": _baseline("real_power", 100.0, 90.0, 110.0)
        }
    )

    detail = _detail(
        _config("kitchen", ApplianceProfile.MIXED, mode=CircuitMode.MIXED),
        state,
        store_data,
    )

    metric_ids = {item["metric_id"] for item in detail["today_vs_normal"]}
    assert "current_power_w" not in metric_ids


def test_today_vs_normal_includes_demand_capacity_and_solar_metrics() -> None:
    state = AnalyzerState()
    state.current_demand_w_by_circuit["ev"] = 3100.0
    state.peak_demand_w_by_circuit["ev"] = 5200.0
    state.capacity_usage_by_circuit["ev"] = 86.0
    state.capacity_status_by_circuit["ev"] = "over_limit"
    state.solar_flexible_load_coverage_percent_by_circuit["ev"] = 74.0
    store_data = FeatureStoreData(
        baselines={
            "ev:demand_peak_w": _baseline("demand_peak_w", 4800.0, 4200.0, 5000.0),
            "ev:capacity_usage_percent": _baseline(
                "capacity_usage_percent",
                70.0,
                50.0,
                80.0,
            ),
            "ev:solar_covered_share_percent": _baseline(
                "solar_covered_share_percent",
                65.0,
                40.0,
                90.0,
            ),
        }
    )

    detail = _detail(_config("ev", ApplianceProfile.EV_CHARGER), state, store_data)
    comparisons = {item["metric_id"]: item for item in detail["today_vs_normal"]}

    assert comparisons["current_demand_w"]["label"] == "Current demand"
    assert comparisons["current_demand_w"]["unit"] == "W"
    assert comparisons["current_demand_w"]["current_value"] == 3100.0
    assert comparisons["current_demand_w"].get("comparison_mode") == "current_state"
    assert comparisons["demand_peak_w"]["label"] == "Demand peak so far"
    assert comparisons["demand_peak_w"]["current_value"] == 5200.0
    assert comparisons["demand_peak_w"]["status"] == "learning"
    assert comparisons["demand_peak_w"]["full_period_normal_low"] == 4200.0
    assert comparisons["demand_peak_w"]["full_period_normal_high"] == 5000.0
    assert (
        comparisons["demand_peak_w"].get("comparison_mode")
        == "same_time_of_day"
    )
    assert comparisons["capacity_usage_percent"]["label"] == "Capacity usage"
    assert comparisons["capacity_usage_percent"]["current_value"] == 86.0
    assert comparisons["capacity_usage_percent"]["status"] == "higher"
    assert (
        comparisons["capacity_usage_percent"].get("comparison_mode")
        == "current_state"
    )
    assert comparisons["current_demand_w"]["current_value"] != comparisons[
        "demand_peak_w"
    ]["current_value"]
    assert comparisons["capacity_usage_percent"]["unit"] == "%"
    assert comparisons["solar_covered_share_percent"]["label"] == "Solar-covered share"
    assert comparisons["solar_covered_share_percent"]["current_value"] == 74.0
    assert comparisons["solar_covered_share_percent"]["status"] == "normal"


def test_capacity_and_demand_comparisons_expose_configured_limits() -> None:
    state = AnalyzerState()
    state.peak_demand_w_by_circuit["ev"] = 4200.0
    state.demand_evidence_by_circuit["ev"] = {"demand_limit_w": 5000.0}
    state.capacity_usage_by_circuit["ev"] = 86.0
    state.capacity_status_by_circuit["ev"] = "over_limit"
    state.capacity_evidence_by_circuit["ev"] = {"warning_ratio": 0.8}

    comparisons = {
        item["metric_id"]: item
        for item in _detail(_config("ev", ApplianceProfile.EV_CHARGER), state)[
            "today_vs_normal"
        ]
    }

    capacity = comparisons["capacity_usage_percent"]
    assert capacity["configured_warning_value"] == 80.0
    assert capacity["configured_limit_value"] == 100.0
    assert capacity["limit_unit"] == "%"
    demand = comparisons["demand_peak_w"]
    assert demand["configured_limit_value"] == 5000.0
    assert demand["limit_unit"] == "W"


def test_today_vs_normal_skips_unconfigured_capacity_metric() -> None:
    state = AnalyzerState()
    state.capacity_usage_by_circuit["fridge"] = 0.0
    state.capacity_status_by_circuit["fridge"] = "unconfigured"

    detail = _detail(_config("fridge", ApplianceProfile.REFRIGERATOR), state)

    comparisons = {item["metric_id"]: item for item in detail["today_vs_normal"]}
    assert "capacity_usage_percent" not in comparisons


def test_demand_peak_comparison_uses_contextual_demand_evidence() -> None:
    state = AnalyzerState()
    state.peak_demand_w_by_circuit["ev"] = 5200.0
    state.demand_evidence_by_circuit["ev"] = {
        "contextual_expected_range_w": [4200.0, 5000.0],
        "contextual_baseline_median_w": 4600.0,
        "contextual_baseline_confidence": 0.77,
    }

    detail = _detail(_config("ev", ApplianceProfile.EV_CHARGER), state)
    comparisons = {item["metric_id"]: item for item in detail["today_vs_normal"]}

    demand = comparisons["demand_peak_w"]
    assert demand["status"] == "higher"
    assert demand["source"] == "contextual_baseline"
    assert demand["normal_low"] == 4200.0
    assert demand["normal_high"] == 5000.0
    assert demand["normal_median"] == 4600.0
    assert demand["confidence"] == 0.77


def test_unavailable_cost_is_not_presented_as_valid() -> None:
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 2.4
    state.cost_current_rate_by_circuit["fridge"] = 0.25
    state.cost_today_by_circuit["fridge"] = 0.6
    state.cost_evidence_by_circuit["fridge"] = {"cost_today_status": "unavailable"}
    store_data = FeatureStoreData(
        baselines={
            "fridge:daily_energy_kwh": _baseline("daily_energy_kwh", 2.0, 1.8, 2.2)
        }
    )

    detail = _detail(
        _config("fridge", ApplianceProfile.REFRIGERATOR),
        state,
        store_data,
    )

    assert detail["cost_today"] is None
    assert "cost_today" not in {
        item["metric_id"] for item in detail["today_vs_normal"]
    }


@pytest.mark.parametrize(
    "profile",
    (ApplianceProfile.HVAC, ApplianceProfile.MINI_SPLIT),
)
def test_weather_aware_long_runtime_uses_weather_context(
    profile: ApplianceProfile,
) -> None:
    circuit_id = profile.value
    config = _config(circuit_id, profile)
    store_data = FeatureStoreData(
        baselines={
            f"{circuit_id}:runtime_today_seconds": _baseline(
                "runtime_today_seconds",
                18_000.0,
                14_400.0,
                21_600.0,
            )
        }
    )
    hot = AnalyzerState()
    hot.run_cycle_runtime_seconds_by_circuit[circuit_id] = 25_200.0
    hot.run_cycle_evidence_by_circuit[circuit_id] = {
        "runtime_today_contextual_expected_range_seconds": [14_400.0, 21_600.0],
        "runtime_today_contextual_baseline_median_seconds": 18_000.0,
        "runtime_today_contextual_baseline_confidence": 0.9,
    }
    hot.weather_context_by_circuit[circuit_id] = {"status": "weather_correlated"}
    mild = AnalyzerState()
    mild.run_cycle_runtime_seconds_by_circuit[circuit_id] = 25_200.0
    mild.run_cycle_evidence_by_circuit[circuit_id] = dict(
        hot.run_cycle_evidence_by_circuit[circuit_id]
    )

    hot_expectation = _detail(config, hot, store_data)["expectations"][0]
    mild_expectation = _detail(config, mild, store_data)["expectations"][0]

    assert hot_expectation["status"] == "expected"
    assert "weather" in hot_expectation["observed"].lower()
    assert mild_expectation["status"] == "watch"


def test_sump_pump_after_rain_is_expected_without_rain_is_watch() -> None:
    config = _config("sump_pump", ApplianceProfile.SUMP_PUMP)
    store_data = FeatureStoreData(
        baselines={
            "sump_pump:runtime_today_seconds": _baseline(
                "runtime_today_seconds",
                600.0,
                300.0,
                900.0,
            )
        }
    )
    after_rain = AnalyzerState()
    after_rain.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 1800.0
    after_rain.run_cycle_evidence_by_circuit["sump_pump"] = {
        "runtime_today_contextual_expected_range_seconds": [300.0, 900.0],
        "runtime_today_contextual_baseline_median_seconds": 600.0,
        "runtime_today_contextual_baseline_confidence": 0.9,
    }
    after_rain.rain_pump_context_by_circuit["sump_pump"] = {
        "status": "rain_explained"
    }
    dry = AnalyzerState()
    dry.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 1800.0
    dry.run_cycle_evidence_by_circuit["sump_pump"] = dict(
        after_rain.run_cycle_evidence_by_circuit["sump_pump"]
    )

    assert _detail(config, after_rain, store_data)["expectations"][0]["status"] == (
        "expected"
    )
    assert _detail(config, dry, store_data)["expectations"][0]["status"] == "watch"


def test_dryer_leg_imbalance_produces_first_check_guidance() -> None:
    state = AnalyzerState()
    state.leg_imbalance_status_by_circuit["dryer"] = "imbalanced"
    state.leg_imbalance_percent_by_circuit["dryer"] = 42.0

    expectation = _detail(
        _config("dryer", ApplianceProfile.DRYER, mode=CircuitMode.DUAL_PHASE),
        state,
    )["expectations"][0]

    assert expectation["status"] == "possible_issue"
    assert "dual-phase" in expectation["what_to_check_first"][0]


def test_profile_specific_expectations_cover_remaining_named_appliances() -> None:
    cases = {
        ApplianceProfile.DISHWASHER: "bounded wash and dry cycle",
        ApplianceProfile.THREE_D_PRINTER: "preheat and heater cycling",
        ApplianceProfile.MINI_SPLIT: "outdoor temperature",
        ApplianceProfile.WASHER: "bounded cycle",
        ApplianceProfile.DRYER: "high power",
        ApplianceProfile.WATER_HEATER: "water heating",
        ApplianceProfile.OVEN: "high heat",
        ApplianceProfile.MICROWAVE: "short high-power",
        ApplianceProfile.POOL_PUMP: "scheduled pump",
        ApplianceProfile.EV_CHARGER: "circuit capacity",
        ApplianceProfile.SOLAR_INVERTER: "daylight",
        ApplianceProfile.MIXED: "mixed circuit",
        ApplianceProfile.MAINS_NILM: "whole-home",
    }

    for profile, expected_text in cases.items():
        config = _config(profile.value, profile)
        expectation = _detail(config, AnalyzerState())["expectations"][0]

        assert expectation["status"] == "ok"
        assert expected_text in expectation["expected"].lower()
        assert expectation["title"] != "Behavior looks normal"


def test_normal_fallback_expectation_does_not_repeat_no_action_needed() -> None:
    expectation = _detail(
        _config("motor", ApplianceProfile.MOTOR_LOAD),
        AnalyzerState(),
    )["expectations"][0]

    assert expectation["title"] == "Behavior looks normal"
    assert expectation["what_to_check_first"] == []


def test_mini_split_expectation_explains_inverter_and_defrost_behavior() -> None:
    expectation = _detail(
        _config("mini_split", ApplianceProfile.MINI_SPLIT),
        AnalyzerState(),
    )["expectations"][0]

    assert "modulate" in expectation["expected"].lower()
    assert "defrost" in expectation["why_it_matters"].lower()


def test_maintenance_suppresses_issue_language() -> None:
    state = AnalyzerState()
    state.leg_imbalance_status_by_circuit["dryer"] = "imbalanced"
    state.maintenance_by_circuit["dryer"] = {"active": True}

    expectation = _detail(
        _config("dryer", ApplianceProfile.DRYER, mode=CircuitMode.DUAL_PHASE),
        state,
    )["expectations"][0]

    assert expectation["status"] == "expected"
    assert "maintenance" in expectation["title"].lower()


def test_low_confidence_nilm_expectation_prompts_validation() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    mains = _config(
        "mains",
        ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    coordinator = SimpleNamespace(
        circuit_configs=(mains,),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "display_name": "Dishwasher",
                        "confidence": 0.61,
                        "lifecycle_state": "needs_validation",
                        "publish_entities": True,
                    }
                ]
            }
        ),
        _nilm_unmatched_edges={},
        entry_id="entry-1",
    )

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )

    expectation = payload["detail"]["expectations"][0]
    assert expectation["status"] == "watch"
    assert expectation["source_type"] == "nilm_estimate"
    assert "Validate" in expectation["what_to_check_first"][0]
