from custom_components.circuitsetup_energy_analyzer.goals import (
    DEFAULT_GOAL_ALERT_RATIO,
    EnergyGoalSettings,
    evaluate_daily_energy_goal,
)


def test_evaluate_daily_energy_goal_tracks_usage_under_goal() -> None:
    result = evaluate_daily_energy_goal(
        circuit_id="fridge",
        date="2026-06-03",
        daily_usage_kwh=9.5,
        settings=EnergyGoalSettings(daily_goal_kwh=12.0),
    )

    assert DEFAULT_GOAL_ALERT_RATIO == 1.0
    assert result.daily_goal_kwh == 12.0
    assert result.goal_usage_percent == 79.2
    assert result.alert_threshold_kwh == 12.0
    assert result.status == "tracking"
    assert result.goal_exceeded is None


def test_evaluate_daily_energy_goal_flags_over_goal_usage() -> None:
    result = evaluate_daily_energy_goal(
        circuit_id="fridge",
        date="2026-06-03",
        daily_usage_kwh=13.2,
        settings=EnergyGoalSettings(daily_goal_kwh=12.0),
    )

    assert result.status == "over_goal"
    assert result.goal_exceeded is not None
    assert result.goal_exceeded.features == {
        "daily_usage_kwh": 13.2,
        "daily_goal_kwh": 12.0,
        "goal_usage_percent": 110.0,
        "alert_threshold_kwh": 12.0,
        "goal_alert_ratio": 1.0,
    }


def test_evaluate_daily_energy_goal_can_warn_before_goal() -> None:
    result = evaluate_daily_energy_goal(
        circuit_id="fridge",
        date="2026-06-03",
        daily_usage_kwh=11.0,
        settings=EnergyGoalSettings(daily_goal_kwh=12.0, goal_alert_ratio=0.9),
    )

    assert result.status == "near_goal"
    assert result.alert_threshold_kwh == 10.8
    assert result.goal_exceeded is not None


def test_evaluate_daily_energy_goal_is_unconfigured_without_goal() -> None:
    result = evaluate_daily_energy_goal(
        circuit_id="fridge",
        date="2026-06-03",
        daily_usage_kwh=13.2,
        settings=EnergyGoalSettings(),
    )

    assert result.daily_goal_kwh is None
    assert result.goal_usage_percent == 0.0
    assert result.status == "unconfigured"
    assert result.goal_exceeded is None
