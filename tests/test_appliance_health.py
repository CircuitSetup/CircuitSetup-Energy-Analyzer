from datetime import UTC, date, datetime, timedelta
from time import perf_counter

from custom_components.circuitsetup_energy_analyzer.appliance_health import (
    ApplianceHealthDay,
    ApplianceHealthSession,
    build_appliance_health_days,
    build_appliance_health_sessions,
    evaluate_appliance_health,
)
from custom_components.circuitsetup_energy_analyzer.contextual_baseline import (
    ContextKey,
    ContextualBaselineSample,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitEvent,
    EventType,
)


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
    assert result.primary_finding.last_evidence_at == "2026-07-17"
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
    assert result.primary_finding.last_evidence_at == (
        "2026-07-12T10:12:00+00:00"
    )


def test_two_recent_short_sessions_are_insufficient() -> None:
    result = evaluate_appliance_health(
        ApplianceProfile.REFRIGERATOR,
        days=(),
        sessions=_sessions(1, 9, duration_seconds=720.0)
        + _sessions(10, 2, duration_seconds=120.0),
    )

    assert result.status == "learning"
    assert result.primary_finding is None


def test_health_day_builder_joins_complete_energy_and_cycle_days() -> None:
    days = [
        {
            "date": "2026-07-01",
            "usage_kwh": 2.4,
            "complete": True,
            "baseline_eligible": True,
        },
        {
            "date": "2026-07-02",
            "usage_kwh": 9.9,
            "complete": True,
            "baseline_eligible": False,
        },
    ]
    events = (
        CircuitEvent(
            datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
            "fridge",
            EventType.START,
        ),
        CircuitEvent(
            datetime(2026, 7, 1, 10, 15, tzinfo=UTC),
            "fridge",
            EventType.STOP,
        ),
    )

    result = build_appliance_health_days(
        circuit_id="fridge",
        energy_days=days,
        events=events,
        contextual_samples=(),
        merge_gap_seconds=60.0,
        time_zone="UTC",
    )

    assert [item.date.isoformat() for item in result] == ["2026-07-01"]
    assert result[0].energy_kwh == 2.4
    assert result[0].runtime_seconds == 900.0
    assert result[0].completed_cycles == 1
    assert result[0].start_count == 1


def test_health_day_builder_excludes_incomplete_and_maintenance_event_days() -> None:
    days = [
        {
            "date": "2026-07-01",
            "usage_kwh": 2.4,
            "complete": False,
        },
        {
            "date": "2026-07-02",
            "usage_kwh": 2.5,
            "complete": True,
        },
    ]
    events = (
        CircuitEvent(
            datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
            "fridge",
            EventType.START,
            features={"baseline_eligible": False},
        ),
        CircuitEvent(
            datetime(2026, 7, 2, 10, 15, tzinfo=UTC),
            "fridge",
            EventType.STOP,
            features={"baseline_eligible": False},
        ),
    )

    result = build_appliance_health_days(
        circuit_id="fridge",
        energy_days=days,
        events=events,
        contextual_samples=(),
        merge_gap_seconds=60.0,
        time_zone="UTC",
    )

    assert result == ()


def test_health_day_builder_retains_agreed_environment_context() -> None:
    timestamp = datetime(2026, 7, 1, 23, 0, tzinfo=UTC)
    context = ContextKey.from_mapping(
        {
            "season": "summer",
            "weather_mode": "cooling",
            "temperature_bin": "hot",
            "water_flow_state": "active_flow",
        }
    )
    samples = tuple(
        ContextualBaselineSample(
            timestamp=timestamp,
            circuit_id="water_heater",
            feature=feature,
            value=1.0,
            context=context,
        )
        for feature in ("daily_energy_kwh", "runtime_today_seconds")
    )

    result = build_appliance_health_days(
        circuit_id="water_heater",
        energy_days=(
            {
                "date": "2026-07-01",
                "usage_kwh": 2.4,
                "complete": True,
            },
        ),
        events=(),
        contextual_samples=samples,
        merge_gap_seconds=60.0,
        time_zone="UTC",
    )

    assert result[0].context == {
        "season": "summer",
        "temperature_bin": "hot",
        "water_flow_state": "active_flow",
        "weather_mode": "cooling",
    }


def test_health_day_builder_drops_conflicting_environment_context() -> None:
    timestamp = datetime(2026, 7, 1, 23, 0, tzinfo=UTC)
    samples = (
        ContextualBaselineSample(
            timestamp=timestamp,
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=2.0,
            context=ContextKey.from_mapping(
                {"weather_mode": "cooling", "temperature_bin": "hot"}
            ),
        ),
        ContextualBaselineSample(
            timestamp=timestamp,
            circuit_id="hvac",
            feature="runtime_today_seconds",
            value=7200.0,
            context=ContextKey.from_mapping(
                {"weather_mode": "heating", "temperature_bin": "cold"}
            ),
        ),
    )

    result = build_appliance_health_days(
        circuit_id="hvac",
        energy_days=(
            {
                "date": "2026-07-01",
                "usage_kwh": 2.4,
                "complete": True,
            },
        ),
        events=(),
        contextual_samples=samples,
        merge_gap_seconds=60.0,
        time_zone="UTC",
    )

    assert result[0].context == {}


def test_health_session_builder_reuses_merge_gap_and_excludes_maintenance() -> None:
    start = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    events = (
        CircuitEvent(start, "fridge", EventType.START),
        CircuitEvent(start + timedelta(minutes=5), "fridge", EventType.STOP),
        CircuitEvent(start + timedelta(minutes=6), "fridge", EventType.START),
        CircuitEvent(start + timedelta(minutes=11), "fridge", EventType.STOP),
        CircuitEvent(
            start + timedelta(days=1),
            "fridge",
            EventType.START,
            features={"baseline_eligible": False},
        ),
        CircuitEvent(
            start + timedelta(days=1, minutes=5),
            "fridge",
            EventType.STOP,
            features={"baseline_eligible": False},
        ),
    )

    result = build_appliance_health_sessions(
        circuit_id="fridge",
        events=events,
        merge_gap_seconds=60.0,
        time_zone="UTC",
        now=start + timedelta(days=2),
    )

    assert len(result) == 1
    assert result[0].duration_seconds == 600.0
    assert result[0].gap_after_seconds is None


def test_health_builders_fall_back_to_utc_for_unknown_time_zone() -> None:
    result = build_appliance_health_days(
        circuit_id="fridge",
        energy_days=(
            {
                "date": "2026-07-01",
                "usage_kwh": 2.4,
                "complete": True,
            },
        ),
        events=(),
        contextual_samples=(),
        merge_gap_seconds=60.0,
        time_zone="Not/A_Real_Zone",
    )

    assert result[0].date == date(2026, 7, 1)


def test_health_evaluation_stays_bounded_at_standard_retention() -> None:
    first_day = date(2026, 6, 1)
    days = tuple(
        ApplianceHealthDay(
            date=first_day + timedelta(days=index),
            energy_kwh=2.0 if index < 42 else 3.0,
            runtime_seconds=7200.0,
            completed_cycles=4,
            start_count=4,
            context={
                "season": "summer",
                "weather_mode": "cooling",
                "temperature_bin": "hot",
            },
        )
        for index in range(45)
    )
    first_session = datetime(2026, 6, 1, tzinfo=UTC)
    sessions = tuple(
        ApplianceHealthSession(
            started_at=(first_session + timedelta(minutes=index * 15)).isoformat(),
            stopped_at=(
                first_session + timedelta(minutes=index * 15 + 12)
            ).isoformat(),
            duration_seconds=720.0 if index < 1997 else 120.0,
            gap_after_seconds=180.0,
        )
        for index in range(2000)
    )

    started = perf_counter()
    for _ in range(100):
        evaluate_appliance_health(
            ApplianceProfile.HVAC,
            days=days,
            sessions=sessions,
        )

    assert perf_counter() - started < 1.0
