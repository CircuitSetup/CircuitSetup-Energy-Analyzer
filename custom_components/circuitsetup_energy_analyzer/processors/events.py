"""Circuit event processor."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from datetime import timedelta
from typing import Any

from ..alert_feedback import mapping_datetime
from ..events import CircuitEventDetector
from ..models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
)
from ..normalize import NormalizedCircuitSample
from ..operating_detection import (
    operating_snapshot_to_dict,
    resolve_operating_detection_from_settings,
)
from .base import FeatureResult, ProcessingContext, StateUpdate


class CircuitEventProcessor:
    """Detect circuit events from normalized samples."""

    name = "events"

    def __init__(
        self,
        detectors: MutableMapping[str, CircuitEventDetector] | None = None,
    ) -> None:
        self.detectors = detectors if detectors is not None else {}
        self._resolved_by_circuit: dict[str, tuple[Any, ...]] = {}

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return newly detected events for a circuit sample."""
        if (
            circuit_config.mode is CircuitMode.MIXED
            or circuit_config.appliance_profile is ApplianceProfile.MIXED
        ):
            return FeatureResult()
        overrides = getattr(
            context.store_data,
            "operating_detection_settings_by_circuit",
            {},
        )
        resolved = resolve_operating_detection_from_settings(
            circuit_config,
            (
                overrides.get(circuit_config.circuit_id, {})
                if isinstance(overrides, dict)
                else {}
            ),
        )
        key = (
            resolved.profile.on_threshold_w,
            resolved.profile.off_threshold_w,
            resolved.profile.on_dwell_seconds,
            resolved.profile.off_dwell_seconds,
            resolved.profile.merge_gap_seconds,
            resolved.profile.max_sample_gap_seconds,
            resolved.profile.emit_initial_transition,
            resolved.source.value,
            resolved.appliance_profile.value,
            resolved.circuit_mode.value,
        )
        detector = self.detectors.get(circuit_config.circuit_id)
        if (
            detector is None
            or self._resolved_by_circuit.get(circuit_config.circuit_id) != key
        ):
            detector = CircuitEventDetector(
                on_threshold_w=resolved.profile.on_threshold_w,
                off_threshold_w=resolved.profile.off_threshold_w,
                on_dwell_seconds=resolved.profile.on_dwell_seconds,
                off_dwell_seconds=resolved.profile.off_dwell_seconds,
                merge_gap_seconds=resolved.profile.merge_gap_seconds,
                max_sample_gap_seconds=resolved.profile.max_sample_gap_seconds,
                emit_initial_transition=resolved.profile.emit_initial_transition,
                threshold_source=resolved.source,
                appliance_profile=resolved.appliance_profile,
                circuit_mode=resolved.circuit_mode,
            )
            self.detectors[circuit_config.circuit_id] = detector
            self._resolved_by_circuit[circuit_config.circuit_id] = key
        maintenance = context.store_data.maintenance_by_circuit.get(
            circuit_config.circuit_id,
            {},
        )
        events = [
            replace(
                event,
                features={
                    **event.features,
                    "baseline_eligible": _baseline_eligible(event, maintenance),
                },
            )
            for event in detector.process(sample)
        ]
        snapshot = detector.last_snapshot
        state_updates: list[StateUpdate] = []
        if snapshot is not None:
            state_updates.extend(
                (
                    StateUpdate(
                        path=("operating_state_by_circuit", circuit_config.circuit_id),
                        value=snapshot.state.value,
                    ),
                    StateUpdate(
                        path=(
                            "operating_state_snapshot_by_circuit",
                            circuit_config.circuit_id,
                        ),
                        value=operating_snapshot_to_dict(snapshot),
                    ),
                )
            )
        return FeatureResult(
            events=events,
            state_updates=state_updates,
            store_dirty=bool(events),
        )


def _baseline_eligible(event: CircuitEvent, maintenance: Any) -> bool:
    if not isinstance(maintenance, Mapping):
        return True
    if maintenance.get("active") is True:
        return False
    if event.event_type is not EventType.STOP:
        return True

    started_at = mapping_datetime(maintenance.get("started_at"))
    ended_at = mapping_datetime(maintenance.get("ended_at"))
    if started_at is None or ended_at is None:
        return True

    event_end = event.timestamp
    if started_at.tzinfo is None:
        event_end = event_end.replace(tzinfo=None)
    elif event_end.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
        ended_at = ended_at.replace(tzinfo=None)
    event_start = event_end - timedelta(
        seconds=float(event.features.get("run_duration_s", 0.0))
    )
    return not (event_start < ended_at and event_end > started_at)

