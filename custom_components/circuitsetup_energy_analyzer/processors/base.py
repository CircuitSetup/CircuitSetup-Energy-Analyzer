"""Base contracts for analyzer feature processors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from ..alerting import Observation
from ..models import AlertEvidence, CircuitConfig, CircuitEvent
from ..normalize import NormalizedCircuitSample

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..coordinator import AnalyzerState
    from ..storage import FeatureStoreData
else:
    HomeAssistant = Any
    AnalyzerState = Any
    FeatureStoreData = Any


@dataclass(frozen=True, slots=True)
class StateUpdate:
    """State path update requested by a feature processor."""

    path: tuple[str, ...]
    value: Any


@dataclass(frozen=True, slots=True)
class ProcessingContext:
    """Runtime dependencies shared with feature processors."""

    now: datetime
    hass: HomeAssistant
    state: AnalyzerState
    store_data: FeatureStoreData
    options: Mapping[str, Any]
    entry_data: Mapping[str, Any]
    known_load_circuit_ids: frozenset[str]
    sensitivity: str


@dataclass(slots=True)
class FeatureResult:
    """Processor output applied by the coordinator."""

    events: list[CircuitEvent] = field(default_factory=list)
    alerts: list[AlertEvidence] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    state_updates: list[StateUpdate] = field(default_factory=list)
    repairs: list[Any] = field(default_factory=list)
    notifications: list[AlertEvidence] = field(default_factory=list)
    store_dirty: bool = False


class FeatureProcessor(Protocol):
    """Feature processor contract."""

    name: str

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Process a circuit sample and return coordinator-applied results."""

