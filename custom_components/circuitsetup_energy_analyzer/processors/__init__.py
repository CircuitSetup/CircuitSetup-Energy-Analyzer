"""Feature processors for CircuitSetup Energy Analyzer."""

from .activity import ActivityAlertProcessor
from .appliance_health import ApplianceHealthProcessor
from .base import FeatureResult, ProcessingContext, StateUpdate
from .billing import BillingCycleProcessor
from .capacity import CapacityProcessor
from .cost import CostProcessor
from .cycles import RunCycleProcessor
from .demand import DemandProcessor
from .energy_goal import EnergyGoalProcessor
from .energy_usage import EnergyUsageProcessor
from .events import CircuitEventProcessor
from .hvac_efficiency import HvacEfficiencyProcessor
from .leg_imbalance import LegImbalanceProcessor
from .mains_balance import MainsBalanceProcessor
from .mains_power_quality import MainsPowerQualityProcessor
from .metric_consistency import MetricConsistencyProcessor
from .nilm_sample import NilmSampleProcessor
from .nilm_topology import NilmTopologyProcessor
from .power_quality import PowerQualityProcessor
from .solar_flow import SolarFlowProcessor
from .standby import StandbyProcessor
from .utility_comparison import UtilityComparisonProcessor
from .water_context import WaterContextAlertProcessor

__all__ = [
    "ActivityAlertProcessor",
    "ApplianceHealthProcessor",
    "BillingCycleProcessor",
    "CapacityProcessor",
    "CircuitEventProcessor",
    "CostProcessor",
    "DemandProcessor",
    "EnergyGoalProcessor",
    "EnergyUsageProcessor",
    "FeatureResult",
    "HvacEfficiencyProcessor",
    "LegImbalanceProcessor",
    "MainsBalanceProcessor",
    "MainsPowerQualityProcessor",
    "MetricConsistencyProcessor",
    "NilmSampleProcessor",
    "NilmTopologyProcessor",
    "PowerQualityProcessor",
    "ProcessingContext",
    "RunCycleProcessor",
    "SolarFlowProcessor",
    "StandbyProcessor",
    "StateUpdate",
    "UtilityComparisonProcessor",
    "WaterContextAlertProcessor",
]
