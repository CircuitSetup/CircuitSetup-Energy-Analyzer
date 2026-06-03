from custom_components.circuitsetup_energy_analyzer.metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_POWER_FACTOR_TOLERANCE,
    evaluate_metric_consistency,
)


def test_metric_consistency_accepts_matching_va_and_power_factor() -> None:
    result = evaluate_metric_consistency(
        real_power_w=960.0,
        apparent_power_va=1200.0,
        power_factor=0.8,
        voltage_v=120.0,
        current_a=10.0,
    )

    assert result.status == "consistent"
    assert result.mismatch_score_percent == 0.0
    assert result.expected_apparent_power_va == 1200.0
    assert result.expected_power_factor == 0.8
    assert result.features == {
        "mismatch_score_percent": 0.0,
        "expected_apparent_power_va": 1200.0,
        "reported_apparent_power_va": 1200.0,
        "apparent_power_difference_percent": 0.0,
        "expected_power_factor": 0.8,
        "reported_power_factor": 0.8,
        "power_factor_difference": 0.0,
    }


def test_metric_consistency_flags_apparent_power_mismatch() -> None:
    result = evaluate_metric_consistency(
        real_power_w=480.0,
        apparent_power_va=600.0,
        power_factor=0.8,
        voltage_v=120.0,
        current_a=10.0,
    )

    assert result.status == "apparent_power_mismatch"
    assert result.mismatch_score_percent == 50.0
    assert result.expected_apparent_power_va == 1200.0
    assert result.reported_apparent_power_va == 600.0
    assert result.apparent_power_difference_percent == -50.0
    assert result.apparent_power_tolerance_percent == (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
    )


def test_metric_consistency_flags_power_factor_mismatch() -> None:
    result = evaluate_metric_consistency(
        real_power_w=600.0,
        apparent_power_va=1200.0,
        power_factor=0.9,
        voltage_v=120.0,
        current_a=10.0,
    )

    assert result.status == "power_factor_mismatch"
    assert result.mismatch_score_percent == 40.0
    assert result.expected_power_factor == 0.5
    assert result.reported_power_factor == 0.9
    assert result.power_factor_difference == 0.4
    assert result.power_factor_tolerance == DEFAULT_POWER_FACTOR_TOLERANCE


def test_metric_consistency_sums_dual_phase_leg_va_when_available() -> None:
    result = evaluate_metric_consistency(
        real_power_w=1800.0,
        apparent_power_va=2400.0,
        power_factor=0.75,
        voltage_v=120.0,
        current_a=20.0,
        leg_a_voltage_v=121.0,
        leg_a_current_a=10.0,
        leg_b_voltage_v=119.0,
        leg_b_current_a=10.0,
    )

    assert result.status == "consistent"
    assert result.apparent_power_source == "leg_voltage_current"
    assert result.expected_apparent_power_va == 2400.0


def test_metric_consistency_reports_missing_or_idle_inputs() -> None:
    missing = evaluate_metric_consistency(
        real_power_w=100.0,
        apparent_power_va=None,
        power_factor=None,
        voltage_v=None,
        current_a=None,
    )
    idle = evaluate_metric_consistency(
        real_power_w=2.0,
        apparent_power_va=2.0,
        power_factor=1.0,
        voltage_v=120.0,
        current_a=0.01,
    )

    assert missing.status == "missing_metrics"
    assert idle.status == "idle"
