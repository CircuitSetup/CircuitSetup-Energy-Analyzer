from custom_components.circuitsetup_energy_analyzer.water_correlations import (
    FlowCorrelationInput,
    RainPumpCorrelationInput,
    evaluate_flow_correlation,
    evaluate_rain_pump_correlation,
)


def test_rain_explains_elevated_sump_runtime() -> None:
    evidence = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=18.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=True,
            rain_intensity_per_hour=None,
            compressor_runtime_minutes=0.0,
            compressor_duty_cycle_percent=0.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )
    assert evidence["status"] == "rain_explained"
    assert evidence["expected_runtime_minutes"] > 6.0
    assert evidence["actual_minus_expected_minutes"] <= 0.0
    assert "rain" in evidence["contributing_factors"]
    assert evidence["baseline_context"] == "raining"
    assert evidence["baseline_fallback_level"] == "rain_adjusted_context"
    assert evidence["baseline_sample_count"] == 18
    assert evidence["contextual_status"] == "rain_explained"
    assert evidence["rain_adjusted_baseline_minutes"] == (
        evidence["expected_runtime_minutes"]
    )
    assert evidence["contextual_baseline_confidence"] == evidence["confidence"]


def test_rain_and_compressor_together_explain_higher_sump_runtime() -> None:
    evidence = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=27.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=True,
            rain_intensity_per_hour=0.35,
            compressor_runtime_minutes=32.0,
            compressor_duty_cycle_percent=55.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )
    assert evidence["status"] == "weather_explained"
    assert evidence["expected_runtime_minutes"] >= 27.0
    assert evidence["compressor_adjustment_minutes"] > 0.0


def test_positive_rain_intensity_explains_pump_runtime_without_binary_sensor() -> None:
    evidence = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=18.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=None,
            rain_intensity_per_hour=0.35,
            compressor_runtime_minutes=0.0,
            compressor_duty_cycle_percent=0.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )

    assert evidence["status"] == "rain_explained"
    assert "rain" in evidence["contributing_factors"]
    assert "rain_intensity" in evidence["contributing_factors"]
    assert evidence["baseline_context"] == "raining, moderate"
    assert evidence["baseline_fallback_level"] == "rain_adjusted_context"
    assert evidence["rain_context_issues"] == []


def test_conflicting_rain_sensor_and_intensity_records_context_issue() -> None:
    evidence = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=7.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=False,
            rain_intensity_per_hour=0.35,
            compressor_runtime_minutes=0.0,
            compressor_duty_cycle_percent=0.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )

    assert evidence["status"] == "normal"
    assert evidence["rain_adjustment_minutes"] == 0.0
    assert "rain" not in evidence["contributing_factors"]
    assert evidence["baseline_context"] == "ambiguous, moderate"
    assert evidence["baseline_fallback_level"] == "ambiguous_rain_context"
    assert evidence["rain_context_issues"] == ["rain_activity_conflict"]


def test_high_pump_runtime_after_adjustment_is_possible_issue() -> None:
    evidence = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=60.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=True,
            rain_intensity_per_hour=0.1,
            compressor_runtime_minutes=5.0,
            compressor_duty_cycle_percent=10.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )
    assert evidence["status"] == "possible_excess_pump_activity"
    assert evidence["actual_minus_expected_minutes"] > 0.0
    assert evidence["confidence"] >= 0.75
    assert evidence["baseline_context"] == "raining, moderate"
    assert evidence["baseline_fallback_level"] == "rain_adjusted_context"


def test_rain_pump_confidence_does_not_increase_for_problem_status() -> None:
    normal = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=6.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=False,
            rain_intensity_per_hour=None,
            compressor_runtime_minutes=0.0,
            compressor_duty_cycle_percent=0.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )
    possible_issue = evaluate_rain_pump_correlation(
        RainPumpCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="sump_pump",
            pump_runtime_minutes=60.0,
            dry_baseline_minutes=6.0,
            comparable_window_count=18,
            rain_active=False,
            rain_intensity_per_hour=None,
            compressor_runtime_minutes=0.0,
            compressor_duty_cycle_percent=0.0,
            sensitivity_delta_threshold_pct=25.0,
        )
    )

    assert normal["status"] == "normal"
    assert possible_issue["status"] == "possible_excess_pump_activity"
    assert possible_issue["confidence"] == normal["confidence"]


def test_flow_without_any_water_load_is_possible_leak_candidate() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="washer",
            appliance_profile="washer",
            flow_active_minutes=14.0,
            appliance_runtime_minutes=0.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=3,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
        )
    )
    assert evidence["status"] == "possible_flow_without_load"
    assert evidence["mismatch_minutes"] == 14.0
    assert evidence["friendly_summary"] == (
        "Water flow has been active for 14 minutes with no mapped water "
        "appliance activity."
    )
    assert evidence["baseline_context"] == "active_flow"
    assert evidence["baseline_fallback_level"] == "water_flow_context"
    assert evidence["baseline_sample_count"] == 12
    assert evidence["contextual_status"] == "possible_flow_without_load"
    assert evidence["contextual_baseline_confidence"] == evidence["confidence"]


def test_flow_confidence_does_not_increase_for_problem_status() -> None:
    normal = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="washer",
            appliance_profile="washer",
            flow_active_minutes=0.0,
            appliance_runtime_minutes=0.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=3,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
        )
    )
    possible_issue = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="washer",
            appliance_profile="washer",
            flow_active_minutes=14.0,
            appliance_runtime_minutes=0.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=3,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
        )
    )

    assert normal["status"] == "normal"
    assert possible_issue["status"] == "possible_flow_without_load"
    assert possible_issue["confidence"] == normal["confidence"]


def test_flow_correlation_is_unconfigured_when_appliance_does_not_expect_flow() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="sump_pump",
            appliance_profile="water_pump",
            flow_active_minutes=0.0,
            appliance_runtime_minutes=12.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=1,
            threshold_minutes=5,
            expects_water_flow=False,
            comparable_window_count=12,
        )
    )

    assert evidence["status"] == "unconfigured"
    assert evidence["confidence"] == 0.3


def test_flow_correlation_is_unconfigured_without_a_configured_sensor() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="well_pump",
            appliance_profile="well_pump",
            flow_active_minutes=0.0,
            appliance_runtime_minutes=12.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=0,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
            flow_source_configured=False,
        )
    )

    assert evidence["status"] == "unconfigured"


def test_shared_flow_is_explained_by_another_mapped_load() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="washer",
            appliance_profile="washer",
            flow_active_minutes=8.0,
            appliance_runtime_minutes=0.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=2,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
            mapped_appliance_runtime_minutes=8.0,
        )
    )

    assert evidence["status"] == "normal"
    assert evidence["mismatch_minutes"] == 0.0


def test_appliance_runtime_without_any_mapped_flow_sensor_is_sensor_problem() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="well_pump",
            appliance_profile="well_pump",
            flow_active_minutes=0.0,
            appliance_runtime_minutes=12.0,
            recent_related_runtime_minutes=0.0,
            mapped_appliance_count=0,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
        )
    )

    assert evidence["status"] == "possible_sensor_problem"
    assert evidence["mismatch_minutes"] == 12.0


def test_water_heater_uses_recent_flow_instead_of_exact_overlap() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="water_heater",
            appliance_profile="water_heater",
            flow_active_minutes=0.0,
            appliance_runtime_minutes=22.0,
            recent_related_runtime_minutes=8.0,
            mapped_appliance_count=2,
            threshold_minutes=5,
            expects_water_flow=True,
            comparable_window_count=12,
        )
    )
    assert evidence["status"] == "normal"
    assert evidence["recent_flow_explains_activity"] is True
    assert evidence["baseline_context"] == "recent_flow"
    assert evidence["baseline_fallback_level"] == "water_flow_context"
