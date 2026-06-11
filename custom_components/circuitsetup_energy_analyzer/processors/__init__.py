"""Feature processors for CircuitSetup Energy Analyzer."""

from .activity import ActivityAlertProcessor
from .base import FeatureProcessor, FeatureResult, ProcessingContext, StateUpdate
from .billing import BillingCycleProcessor
from .capacity import CapacityProcessor
from .cost import CostProcessor
from .cycles import RunCycleProcessor
from .demand import DemandProcessor
from .energy_goal import EnergyGoalProcessor
from .energy_usage import EnergyUsageProcessor
from .events import CircuitEventProcessor
from .leg_imbalance import LegImbalanceProcessor
from .mains_balance import MainsBalanceProcessor
from .metric_consistency import MetricConsistencyProcessor
from .power_quality import PowerQualityProcessor
from .standby import StandbyProcessor
from .utility_comparison import UtilityComparisonProcessor

__all__ = [
    "ActivityAlertProcessor",
    "BillingCycleProcessor",
    "CapacityProcessor",
    "CircuitEventProcessor",
    "CostProcessor",
    "DemandProcessor",
    "EnergyGoalProcessor",
    "EnergyUsageProcessor",
    "FeatureProcessor",
    "FeatureResult",
    "LegImbalanceProcessor",
    "MainsBalanceProcessor",
    "MetricConsistencyProcessor",
    "ProcessingContext",
    "PowerQualityProcessor",
    "RunCycleProcessor",
    "StandbyProcessor",
    "StateUpdate",
    "UtilityComparisonProcessor",
]
