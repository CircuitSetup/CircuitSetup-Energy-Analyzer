from __future__ import annotations

from types import SimpleNamespace

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


def test_today_vs_normal_classifies_daily_energy_from_baseline() -> None:
    state = AnalyzerState()
    state.data_quality_checklist_by_circuit["fridge"] = {
        "required_sensors_present": True,
        "numeric_states_valid": True,
        "source_data_fresh": True,
    }
    state.daily_energy_usage_by_circuit["fridge"] = 2.4
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
    assert comparison == {
        "metric_id": "daily_energy_kwh",
        "label": "Energy today",
        "unit": "kWh",
        "current_value": 2.4,
        "normal_low": 1.8,
        "normal_high": 2.2,
        "normal_median": 2.0,
        "status": "higher",
        "confidence": 0.9,
        "source": "baseline",
    }
    assert detail["expectations"][0]["status"] == "watch"
    assert "above normal" in detail["expectations"][0]["observed"]


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


def test_hvac_long_runtime_is_expected_on_hot_weather_and_watch_on_mild_day() -> None:
    config = _config("hvac", ApplianceProfile.HVAC)
    store_data = FeatureStoreData(
        baselines={
            "hvac:runtime_today_seconds": _baseline(
                "runtime_today_seconds",
                18_000.0,
                14_400.0,
                21_600.0,
            )
        }
    )
    hot = AnalyzerState()
    hot.run_cycle_runtime_seconds_by_circuit["hvac"] = 25_200.0
    hot.weather_context_by_circuit["hvac"] = {"status": "weather_correlated"}
    mild = AnalyzerState()
    mild.run_cycle_runtime_seconds_by_circuit["hvac"] = 25_200.0

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
    after_rain.rain_pump_context_by_circuit["sump_pump"] = {
        "status": "rain_explained"
    }
    dry = AnalyzerState()
    dry.run_cycle_runtime_seconds_by_circuit["sump_pump"] = 1800.0

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
