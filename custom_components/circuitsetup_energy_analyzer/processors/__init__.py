"""Feature processors for CircuitSetup Energy Analyzer."""

from .activity import ActivityAlertProcessor
from .base import FeatureProcessor, FeatureResult, ProcessingContext, StateUpdate
from .billing import BillingCycleProcessor
from .cycles import RunCycleProcessor
from .energy_goal import EnergyGoalProcessor
from .energy_usage import EnergyUsageProcessor
from .events import CircuitEventProcessor

__all__ = [
    "ActivityAlertProcessor",
    "BillingCycleProcessor",
    "CircuitEventProcessor",
    "EnergyGoalProcessor",
    "EnergyUsageProcessor",
    "FeatureProcessor",
    "FeatureResult",
    "ProcessingContext",
    "RunCycleProcessor",
    "StateUpdate",
]
