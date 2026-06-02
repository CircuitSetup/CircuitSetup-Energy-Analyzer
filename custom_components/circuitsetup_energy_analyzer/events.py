from __future__ import annotations

from datetime import datetime

from .models import CircuitEvent, CircuitSample, EventType


class CircuitEventDetector:
    """Detect operating events from a sequence of circuit samples."""

    def __init__(
        self,
        on_threshold_w: float = 80.0,
        off_threshold_w: float = 30.0,
        voltage_sag_ratio: float = 0.08,
    ) -> None:
        self._on_threshold_w = on_threshold_w
        self._off_threshold_w = off_threshold_w
        self._voltage_sag_ratio = voltage_sag_ratio
        self._is_on = False
        self._run_started_at: datetime | None = None
        self._nominal_voltage: float | None = None
        self._sag_emitted_for_run = False

    def process(self, sample: CircuitSample) -> list[CircuitEvent]:
        events: list[CircuitEvent] = []
        watts = sample.real_power

        if not self._is_on:
            if watts is not None and watts >= self._on_threshold_w:
                self._is_on = True
                self._run_started_at = sample.timestamp
                self._sag_emitted_for_run = False
                events.append(
                    CircuitEvent(
                        timestamp=sample.timestamp,
                        circuit_id=sample.circuit_id,
                        event_type=EventType.START,
                        features={"startup_power_w": watts},
                    )
                )
            elif sample.voltage is not None:
                self._nominal_voltage = sample.voltage
        elif watts is not None and watts <= self._off_threshold_w:
            features: dict[str, float] = {}
            if self._run_started_at is not None:
                features["run_duration_s"] = (
                    sample.timestamp - self._run_started_at
                ).total_seconds()

            events.append(
                CircuitEvent(
                    timestamp=sample.timestamp,
                    circuit_id=sample.circuit_id,
                    event_type=EventType.STOP,
                    features=features,
                )
            )
            self._is_on = False
            self._run_started_at = None
            self._sag_emitted_for_run = False
            if sample.voltage is not None:
                self._nominal_voltage = sample.voltage

        if self._is_on and not self._sag_emitted_for_run:
            sag_event = self._detect_voltage_sag(sample)
            if sag_event is not None:
                events.append(sag_event)
                self._sag_emitted_for_run = True

        return events

    def _detect_voltage_sag(self, sample: CircuitSample) -> CircuitEvent | None:
        if (
            self._nominal_voltage is None
            or sample.voltage is None
            or sample.real_power is None
            or self._nominal_voltage <= 0.0
        ):
            return None

        sag_ratio = (self._nominal_voltage - sample.voltage) / self._nominal_voltage
        if sag_ratio < self._voltage_sag_ratio:
            return None

        return CircuitEvent(
            timestamp=sample.timestamp,
            circuit_id=sample.circuit_id,
            event_type=EventType.VOLTAGE_SAG,
            features={
                "voltage": sample.voltage,
                "nominal_voltage": self._nominal_voltage,
                "sag_ratio": sag_ratio,
                "real_power_w": sample.real_power,
            },
        )
