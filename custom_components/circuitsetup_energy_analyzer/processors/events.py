"""Circuit event processor."""

from __future__ import annotations

from collections.abc import MutableMapping

from ..events import CircuitEventDetector
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext


class CircuitEventProcessor:
    """Detect circuit events from normalized samples."""

    name = "events"

    def __init__(
        self,
        detectors: MutableMapping[str, CircuitEventDetector] | None = None,
    ) -> None:
        self.detectors = detectors if detectors is not None else {}

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return newly detected events for a circuit sample."""
        detector = self.detectors.setdefault(
            circuit_config.circuit_id,
            CircuitEventDetector(),
        )
        events = detector.process(sample)
        return FeatureResult(events=events, store_dirty=bool(events))

