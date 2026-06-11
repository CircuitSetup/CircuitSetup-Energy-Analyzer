"""Feature processors for CircuitSetup Energy Analyzer."""

from .base import FeatureProcessor, FeatureResult, ProcessingContext, StateUpdate
from .cycles import RunCycleProcessor
from .energy_goal import EnergyGoalProcessor
from .energy_usage import EnergyUsageProcessor
from .events import CircuitEventProcessor

__all__ = [
    "CircuitEventProcessor",
    "EnergyGoalProcessor",
    "EnergyUsageProcessor",
    "FeatureProcessor",
    "FeatureResult",
    "ProcessingContext",
    "RunCycleProcessor",
    "StateUpdate",
]
