from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from .models import CircuitEvent, EventType


@dataclass(frozen=True, slots=True)
class CircuitCycleSummary:
    """Today-scoped operating-cycle evidence for one circuit."""

    circuit_id: str
    date: str
    status: str
    start_count: int
    completed_cycle_count: int
    runtime_seconds: float
    average_cycle_seconds: float
    active_cycle_seconds: float
    duty_cycle_percent: float
    day_elapsed_seconds: float
    first_start: datetime | None = None
    last_start: datetime | None = None
    last_stop: datetime | None = None


def summarize_circuit_cycles(
    events: Iterable[CircuitEvent],
    *,
    circuit_id: str,
    now: datetime,
) -> CircuitCycleSummary:
    """Summarize today's appliance run cycles from retained start/stop events."""
    day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    circuit_events = sorted(
        (
            event
            for event in events
            if event.circuit_id == circuit_id
            and event.timestamp <= now
            and event.event_type in {EventType.START, EventType.STOP}
        ),
        key=lambda event: event.timestamp,
    )

    active_start: datetime | None = None
    for event in circuit_events:
        if event.timestamp >= day_start:
            break
        if event.event_type is EventType.START:
            active_start = event.timestamp
        elif event.event_type is EventType.STOP:
            active_start = None

    start_count = 0
    completed_cycle_count = 0
    runtime_seconds = 0.0
    completed_runtime_seconds = 0.0
    active_cycle_seconds = 0.0
    first_start: datetime | None = None
    last_start: datetime | None = None
    last_stop: datetime | None = None

    for event in circuit_events:
        if event.timestamp < day_start:
            continue
        if event.event_type is EventType.START:
            start_count += 1
            first_start = first_start or event.timestamp
            last_start = event.timestamp
            active_start = event.timestamp
            continue

        last_stop = event.timestamp
        if active_start is None:
            continue
        cycle_start = max(active_start, day_start)
        duration = max((event.timestamp - cycle_start).total_seconds(), 0.0)
        runtime_seconds += duration
        completed_runtime_seconds += duration
        completed_cycle_count += 1
        active_start = None

    if active_start is not None:
        cycle_start = max(active_start, day_start)
        active_cycle_seconds = max((now - cycle_start).total_seconds(), 0.0)
        runtime_seconds += active_cycle_seconds

    day_elapsed_seconds = max((now - day_start).total_seconds(), 0.0)
    average_cycle_seconds = (
        completed_runtime_seconds / completed_cycle_count
        if completed_cycle_count > 0
        else 0.0
    )
    duty_cycle_percent = (
        (runtime_seconds / day_elapsed_seconds) * 100.0
        if day_elapsed_seconds > 0.0
        else 0.0
    )
    if active_cycle_seconds > 0.0:
        status = "running"
    elif start_count > 0 or completed_cycle_count > 0:
        status = "idle"
    else:
        status = "no_activity"

    return CircuitCycleSummary(
        circuit_id=circuit_id,
        date=now.date().isoformat(),
        status=status,
        start_count=start_count,
        completed_cycle_count=completed_cycle_count,
        runtime_seconds=_round_seconds(runtime_seconds),
        average_cycle_seconds=_round_seconds(average_cycle_seconds),
        active_cycle_seconds=_round_seconds(active_cycle_seconds),
        duty_cycle_percent=round(duty_cycle_percent, 1),
        day_elapsed_seconds=_round_seconds(day_elapsed_seconds),
        first_start=first_start,
        last_start=last_start,
        last_stop=last_stop,
    )


def cycle_summary_payload(summary: CircuitCycleSummary) -> dict[str, Any]:
    """Return JSON-safe diagnostic evidence for cycle summary sensors."""
    return {
        "date": summary.date,
        "status": summary.status,
        "start_count": summary.start_count,
        "completed_cycle_count": summary.completed_cycle_count,
        "runtime_seconds": summary.runtime_seconds,
        "average_cycle_seconds": summary.average_cycle_seconds,
        "active_cycle_seconds": summary.active_cycle_seconds,
        "duty_cycle_percent": summary.duty_cycle_percent,
        "day_elapsed_seconds": summary.day_elapsed_seconds,
        "first_start": _isoformat_or_none(summary.first_start),
        "last_start": _isoformat_or_none(summary.last_start),
        "last_stop": _isoformat_or_none(summary.last_stop),
        "scope": "today",
        "evidence_source": "retained_start_stop_events",
    }


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _round_seconds(value: float) -> float:
    return round(float(value), 3)
