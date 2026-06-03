from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
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
