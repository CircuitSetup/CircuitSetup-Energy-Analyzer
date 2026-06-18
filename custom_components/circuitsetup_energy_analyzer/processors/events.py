"""Circuit event processor."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from ..events import CircuitEventDetector
from ..models import CircuitConfig
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
        events = detector.process(sample)
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

