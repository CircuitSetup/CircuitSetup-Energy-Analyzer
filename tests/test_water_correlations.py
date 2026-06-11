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
