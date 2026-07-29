from datetime import date

from custom_components.circuitsetup_energy_analyzer.appliance_health import (
    ApplianceHealthDay,
    ApplianceHealthSession,
    evaluate_appliance_health,
)
from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile


def _day(
    index: int,
    *,
    energy: float,
    runtime_hours: float,
    completed_cycles: int = 4,
    start_count: int = 4,
    context: dict[str, str] | None = None,
) -> ApplianceHealthDay:
    return ApplianceHealthDay(
        date=date(2026, 7, index),
        energy_kwh=energy,
        runtime_seconds=runtime_hours * 3600.0,
        completed_cycles=completed_cycles,
        start_count=start_count,
        context=context or {"weather_mode": "cooling", "temperature_bin": "hot"},
    )


def _sessions(
    start_day: int,
    count: int,
    *,
    duration_seconds: float,
) -> tuple[ApplianceHealthSession, ...]:
    return tuple(
        ApplianceHealthSession(
            started_at=f"2026-07-{day:02d}T10:00:00+00:00",
            stopped_at=f"2026-07-{day:02d}T10:12:00+00:00",
            duration_seconds=duration_seconds,
            gap_after_seconds=3600.0,
        )
        for day in range(start_day, start_day + count)
    )


def test_sustained_energy_per_runtime_degradation_requires_three_days() -> None:
    reference = tuple(
        _day(index, energy=2.0, runtime_hours=2.0) for index in range(1, 15)
    )
    recent = tuple(
        _day(index, energy=3.0, runtime_hours=2.0) for index in range(15, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.HVAC,
        days=reference + recent,
        sessions=(),
    )

    assert result.status == "possible_degradation"
    assert result.confidence >= 0.6
    assert result.primary_finding is not None
    assert result.primary_finding.feature == "efficiency_degradation"
    assert result.primary_finding.metric == "energy_per_runtime_hour"
    assert result.primary_finding.reference_median == 1.0
    assert result.primary_finding.recent_median == 1.5
    assert result.primary_finding.change_ratio == 0.5
    assert result.primary_finding.context == {
        "temperature_bin": "hot",
        "weather_mode": "cooling",
    }


def test_two_degraded_days_remain_learning() -> None:
    days = tuple(
        _day(index, energy=2.0, runtime_hours=2.0) for index in range(1, 15)
    ) + tuple(
        _day(index, energy=3.0, runtime_hours=2.0) for index in range(15, 17)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.HVAC,
        days=days,
        sessions=(),
    )

    assert result.status == "learning"
    assert result.primary_finding is None


def test_change_below_twenty_five_percent_is_normal() -> None:
    days = tuple(
        _day(index, energy=2.0, runtime_hours=2.0) for index in range(1, 15)
    ) + tuple(
        _day(index, energy=2.4, runtime_hours=2.0) for index in range(15, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.HVAC,
        days=days,
        sessions=(),
    )

    assert result.status == "normal"
    assert result.primary_finding is None


def test_hvac_requires_comparable_weather_context() -> None:
    reference = tuple(
        _day(
            index,
            energy=2.0,
            runtime_hours=2.0,
            context={"weather_mode": "heating", "temperature_bin": "cold"},
        )
        for index in range(1, 15)
    )
    recent = tuple(
        _day(index, energy=3.0, runtime_hours=2.0) for index in range(15, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.HVAC,
        days=reference + recent,
        sessions=(),
    )

    assert result.status == "learning"
    assert result.reason == "insufficient_comparable_context"


def test_flow_aware_appliance_requires_comparable_water_context() -> None:
    reference = tuple(
        _day(
            index,
            energy=2.0,
            runtime_hours=2.0,
            context={"water_flow_state": "no_flow"},
        )
        for index in range(1, 15)
    )
    recent = tuple(
        _day(
            index,
            energy=3.0,
            runtime_hours=2.0,
            context={"water_flow_state": "active_flow"},
        )
        for index in range(15, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.WATER_HEATER,
        days=reference + recent,
        sessions=(),
    )

    assert result.status == "learning"
    assert result.reason == "insufficient_comparable_context"


def test_zero_denominators_do_not_create_efficiency_findings() -> None:
    days = tuple(
        _day(
            index,
            energy=2.0,
            runtime_hours=0.0,
            completed_cycles=0,
            start_count=0,
            context={},
        )
        for index in range(1, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.REFRIGERATOR,
        days=days,
        sessions=(),
    )

    assert result.status == "learning"
    assert result.primary_finding is None


def test_non_hvac_appliance_can_compare_without_weather_context() -> None:
    reference = tuple(
        _day(index, energy=2.0, runtime_hours=2.0, context={})
        for index in range(1, 15)
    )
    recent = tuple(
        _day(index, energy=3.0, runtime_hours=2.0, context={})
        for index in range(15, 18)
    )

    result = evaluate_appliance_health(
        ApplianceProfile.REFRIGERATOR,
        days=reference + recent,
        sessions=(),
    )

    assert result.status == "possible_degradation"
    assert result.primary_finding is not None


def test_three_repeated_short_sessions_create_health_finding() -> None:
    learned = _sessions(1, 9, duration_seconds=720.0)
    recent = _sessions(10, 3, duration_seconds=120.0)

    result = evaluate_appliance_health(
        ApplianceProfile.REFRIGERATOR,
        days=(),
        sessions=learned + recent,
    )

    assert result.status == "possible_degradation"
    assert result.primary_finding is not None
    assert result.primary_finding.feature == "repeated_short_cycle"
    assert result.primary_finding.reference_median == 720.0
    assert result.primary_finding.recent_median == 120.0


def test_two_recent_short_sessions_are_insufficient() -> None:
    result = evaluate_appliance_health(
        ApplianceProfile.REFRIGERATOR,
        days=(),
        sessions=_sessions(1, 9, duration_seconds=720.0)
        + _sessions(10, 2, duration_seconds=120.0),
    )

    assert result.status == "learning"
    assert result.primary_finding is None
