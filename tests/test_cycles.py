from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
)


def test_cycle_summary_counts_today_completed_and_active_cycles() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=now - timedelta(days=1),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=0),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=20),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=11, minute=30),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=11, minute=45),
            circuit_id="well_pump",
            event_type=EventType.START,
        ),
    ]

    summary = summarize_circuit_cycles(events, circuit_id="fridge", now=now)

    assert summary.date == "2026-06-03"
    assert summary.status == "running"
    assert summary.start_count == 2
    assert summary.completed_cycle_count == 1
    assert summary.runtime_seconds == 3000.0
    assert summary.average_cycle_seconds == 1200.0
    assert summary.active_cycle_seconds == 1800.0
    assert summary.duty_cycle_percent == 6.9
    assert summary.first_start == now.replace(hour=1, minute=0)
    assert summary.last_start == now.replace(hour=11, minute=30)
    assert summary.last_stop == now.replace(hour=1, minute=20)


def test_cycle_summary_includes_cycle_running_across_midnight() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=datetime(2026, 6, 2, 23, 50, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=datetime(2026, 6, 3, 0, 10, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
    ]

    summary = summarize_circuit_cycles(events, circuit_id="fridge", now=now)

    assert summary.status == "idle"
    assert summary.start_count == 0
    assert summary.completed_cycle_count == 1
    assert summary.runtime_seconds == 600.0
    assert summary.average_cycle_seconds == 600.0
    assert summary.duty_cycle_percent == 1.4


def test_cycle_summary_uses_ha_local_day_boundary() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=datetime(2026, 5, 31, 23, 30, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
    ]

    summary = summarize_circuit_cycles(
        events,
        circuit_id="fridge",
        now=now,
        time_zone="America/New_York",
    )

    assert summary.date == "2026-05-31"
    assert summary.start_count == 1
    assert summary.completed_cycle_count == 1
    assert summary.runtime_seconds == 1800.0
    assert summary.average_cycle_seconds == 1800.0
    assert summary.day_elapsed_seconds == 84600.0
    assert summary.duty_cycle_percent == 2.1


def test_cycle_summary_uses_absolute_elapsed_time_on_spring_forward_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    summary = summarize_circuit_cycles(
        [],
        circuit_id="hvac",
        now=datetime(2026, 3, 9, 3, 30, tzinfo=UTC),
        time_zone="America/New_York",
    )

    assert summary.date == "2026-03-08"
    assert summary.day_elapsed_seconds == 81000.0


def test_cycle_summary_uses_absolute_elapsed_time_on_fall_back_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    summary = summarize_circuit_cycles(
        [],
        circuit_id="hvac",
        now=datetime(2026, 11, 2, 4, 30, tzinfo=UTC),
        time_zone="America/New_York",
    )

    assert summary.date == "2026-11-01"
    assert summary.day_elapsed_seconds == 88200.0


def test_cycle_baselines_use_ha_local_prior_dates() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        cycle_baseline_feature_values,
    )

    now = datetime(2026, 6, 2, 3, 30, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=datetime(2026, 6, 1, 23, 30, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=datetime(2026, 6, 2, 0, 0, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
    ]

    values = cycle_baseline_feature_values(
        events,
        circuit_id="fridge",
        now=now,
        time_zone="America/New_York",
    )

    assert values["run_cycle_daily_start_count"] == []
    assert values["run_cycle_daily_duty_cycle_percent"] == []


def test_cycle_summary_reports_no_activity_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    summary = summarize_circuit_cycles(
        [],
        circuit_id="fridge",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
    )

    assert summary.status == "no_activity"
    assert summary.start_count == 0
    assert summary.completed_cycle_count == 0
    assert summary.runtime_seconds == 0.0
    assert summary.average_cycle_seconds == 0.0
    assert summary.active_cycle_seconds == 0.0
    assert summary.duty_cycle_percent == 0.0


def test_build_normalized_run_sessions_merges_short_gap() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        build_normalized_run_sessions,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=0),
            circuit_id="washer",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=10),
            circuit_id="washer",
            event_type=EventType.STOP,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=11),
            circuit_id="washer",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=20),
            circuit_id="washer",
            event_type=EventType.STOP,
        ),
    ]

    sessions = build_normalized_run_sessions(
        events,
        circuit_id="washer",
        merge_gap_seconds=90.0,
        now=now,
    )

    assert len(sessions) == 1
    assert sessions[0].started_at == now.replace(hour=1, minute=0)
    assert sessions[0].stopped_at == now.replace(hour=1, minute=20)
    assert sessions[0].duration_seconds == 1140.0
    assert sessions[0].merged_transition_count == 4


def test_cycle_summary_uses_normalized_sessions_for_count_and_runtime() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=0),
            circuit_id="washer",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=10),
            circuit_id="washer",
            event_type=EventType.STOP,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=11),
            circuit_id="washer",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now.replace(hour=1, minute=20),
            circuit_id="washer",
            event_type=EventType.STOP,
        ),
    ]

    summary = summarize_circuit_cycles(
        events,
        circuit_id="washer",
        now=now,
        merge_gap_seconds=90.0,
    )

    assert summary.status == "idle"
    assert summary.start_count == 1
    assert summary.completed_cycle_count == 1
    assert summary.runtime_seconds == 1140.0
    assert summary.average_cycle_seconds == 1140.0


def test_cycle_baselines_use_prior_completed_cycles_and_daily_activity() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        cycle_baseline_feature_values,
    )

    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    events: list[CircuitEvent] = []
    for day_offset in range(1, 16):
        start = now - timedelta(days=day_offset, hours=2)
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=start + timedelta(minutes=20),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )

    values = cycle_baseline_feature_values(events, circuit_id="fridge", now=now)

    assert values["run_cycle_duration_s"] == [1200.0] * 15
    assert values["run_cycle_daily_start_count"] == [1.0] * 15
    assert values["run_cycle_daily_duty_cycle_percent"] == [1.4] * 15


def test_cycle_baselines_exclude_maintenance_events() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        cycle_baseline_feature_values,
    )

    now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    events = []
    for day in range(1, 4):
        start = datetime(2026, 6, day, 1, 0, tzinfo=UTC)
        features = {"baseline_eligible": day != 2}
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                    features=features,
                ),
                CircuitEvent(
                    timestamp=start + timedelta(minutes=20),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                    features=features,
                ),
            ]
        )

    values = cycle_baseline_feature_values(events, circuit_id="fridge", now=now)

    assert values["run_cycle_duration_s"] == [1200.0, 1200.0]
    assert values["run_cycle_daily_start_count"] == [1.0, 1.0]
    assert values["run_cycle_daily_duty_cycle_percent"] == [1.4, 1.4]


def test_cycle_baselines_exclude_cross_day_maintenance_sessions() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        cycle_baseline_feature_values,
    )

    events = [
        CircuitEvent(
            timestamp=datetime(2026, 6, 1, 23, 50, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
            features={"baseline_eligible": False},
        ),
        CircuitEvent(
            timestamp=datetime(2026, 6, 2, 0, 20, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.STOP,
            features={"baseline_eligible": True},
        ),
    ]

    values = cycle_baseline_feature_values(
        events,
        circuit_id="fridge",
        now=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
    )

    assert all(not samples for samples in values.values())


def test_cycle_evidence_flags_active_run_longer_than_learned_cycles() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        CircuitCycleSummary,
        select_cycle_anomaly_evidence,
    )

    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-06-16",
        status="running",
        start_count=1,
        completed_cycle_count=0,
        runtime_seconds=2400.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=2400.0,
        duty_cycle_percent=6.7,
        day_elapsed_seconds=36000.0,
    )

    evidence = select_cycle_anomaly_evidence(
        config,
        summary,
        {
            "run_cycle_duration_s": BaselineStats(
                "run_cycle_duration_s",
                20,
                1200.0,
                60.0,
                1100.0,
                1300.0,
                1.0,
            )
        },
        min_score=1.5,
    )

    assert evidence is not None
    assert evidence.feature == "run_cycle_duration_s"
    assert evidence.observed_value == 2400.0
    assert evidence.baseline_value == 1200.0
    assert "Kitchen Fridge has been running" in evidence.message
    assert "not a diagnosis" in evidence.message
    assert evidence.features == {
        "active_cycle_seconds": 2400.0,
        "baseline_cycle_seconds": 1200.0,
        "baseline_p90_cycle_seconds": 1300.0,
        "baseline_sample_count": 20.0,
        "baseline_confidence": 1.0,
        "score": evidence.score,
    }


def test_cycle_evidence_suppresses_mixed_circuit_appliance_alerts() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        CircuitCycleSummary,
        select_cycle_anomaly_evidence,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Kitchen Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
    )
    summary = CircuitCycleSummary(
        circuit_id="mixed",
        date="2026-06-16",
        status="running",
        start_count=12,
        completed_cycle_count=0,
        runtime_seconds=2400.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=2400.0,
        duty_cycle_percent=6.7,
        day_elapsed_seconds=36000.0,
    )

    assert (
        select_cycle_anomaly_evidence(
            config,
            summary,
            {
                "run_cycle_duration_s": BaselineStats(
                    "run_cycle_duration_s",
                    20,
                    1200.0,
                    60.0,
                    1100.0,
                    1300.0,
                    1.0,
                )
            },
        )
        is None
    )
