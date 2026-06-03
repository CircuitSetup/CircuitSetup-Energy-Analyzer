from custom_components.circuitsetup_energy_analyzer.phase_balance import (
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    evaluate_dual_phase_leg_imbalance,
)


def test_dual_phase_leg_imbalance_flags_high_real_power_difference() -> None:
    result = evaluate_dual_phase_leg_imbalance(
        left_real_power_w=2400.0,
        right_real_power_w=1200.0,
        left_current_a=20.0,
        right_current_a=10.0,
        left_voltage_v=121.0,
        right_voltage_v=119.0,
    )

    assert result.status == "imbalanced"
    assert round(result.imbalance_percent, 1) == 66.7
    assert result.threshold_ratio == DEFAULT_LEG_IMBALANCE_WARNING_RATIO
    assert result.dominant_leg == "a"
    assert result.voltage_difference_v == 2.0
    assert result.features == {
        "leg_imbalance_ratio": result.imbalance_ratio,
        "leg_imbalance_percent": result.imbalance_percent,
        "left_real_power_w": 2400.0,
        "right_real_power_w": 1200.0,
        "threshold_ratio": DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
        "threshold_percent": 50.0,
    }


def test_dual_phase_leg_imbalance_tracks_when_within_threshold() -> None:
    result = evaluate_dual_phase_leg_imbalance(
        left_real_power_w=2400.0,
        right_real_power_w=1800.0,
        left_current_a=20.0,
        right_current_a=15.0,
    )

    assert result.status == "tracking"
    assert round(result.imbalance_percent, 1) == 28.6
    assert result.dominant_leg == "a"


def test_dual_phase_leg_imbalance_requires_both_leg_power_values() -> None:
    result = evaluate_dual_phase_leg_imbalance(
        left_real_power_w=2400.0,
        right_real_power_w=None,
    )

    assert result.status == "missing_leg_power"
    assert result.imbalance_ratio == 0.0
    assert result.dominant_leg == "unknown"


def test_dual_phase_leg_imbalance_ignores_idle_or_control_power() -> None:
    result = evaluate_dual_phase_leg_imbalance(
        left_real_power_w=35.0,
        right_real_power_w=0.0,
    )

    assert result.status == "idle"
    assert result.imbalance_ratio == 0.0
    assert result.dominant_leg == "unknown"
