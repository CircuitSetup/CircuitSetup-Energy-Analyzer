"""Construct coordinator managers, processors, state, and listener runtime."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .config_parsing import (
    retention_mode_from_sources as _retention_mode_from_sources,
)
from .const import CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT
from .dashboard import normalize_dashboard_layout
from .events import CircuitEventDetector
from .managers.alert_policies import AlertPolicyManager
from .managers.circuit_registry import CircuitRegistry
from .managers.config_entry_controller import ConfigEntryController
from .managers.context import ProcessingContextBuilder
from .managers.dashboard_controller import DashboardController
from .managers.demo_data import DemoDataSeeder
from .managers.entity_profile_controller import EntityProfileController
from .managers.environmental_context import (
    WATER_CONTEXT_HISTORY_MAX_SAMPLES,
    WEATHER_CONTEXT_HISTORY_MAX_SAMPLES,
    EnvironmentalContextManager,
)
from .managers.evidence_actions import EvidenceActionController
from .managers.export_manager import ExportManager
from .managers.nilm_controller import NilmController
from .managers.notification_controller import NotificationController
from .managers.processing_pipeline import ProcessingPipeline
from .managers.processor_runtime import ProcessorRuntimeManager
from .managers.settings_controller import SettingsController
from .managers.setup_health import SetupHealthAggregator
from .managers.source_samples import SourceSampleBuilder
from .managers.source_updates import SourceUpdateManager
from .managers.state_reducer import StateReducer
from .managers.store_persistence import StorePersistenceManager
from .managers.utility_energy_sources import UtilityEnergySourceManager
from .managers.ux_state import UxStateManager
from .nilm import NilmEdge, NilmEdgeDetector
from .operating_detection import resolve_operating_detection_from_settings
from .processors import (
    ActivityAlertProcessor,
    ApplianceHealthProcessor,
    BillingCycleProcessor,
    CapacityProcessor,
    CircuitEventProcessor,
    CostProcessor,
    DemandProcessor,
    EnergyGoalProcessor,
    EnergyUsageProcessor,
    HvacEfficiencyProcessor,
    LegImbalanceProcessor,
    MainsBalanceProcessor,
    MetricConsistencyProcessor,
    NilmSampleProcessor,
    NilmTopologyProcessor,
    PowerQualityProcessor,
    RunCycleProcessor,
    SolarFlowProcessor,
    StandbyProcessor,
    UtilityComparisonProcessor,
    WaterContextAlertProcessor,
)
from .state import AnalyzerState
from .storage import RETENTION_WINDOWS
from .utility_comparison import effective_electricity_rate

ALERT_HISTORY_MAX_ITEMS = 500
ALERT_HISTORY_MAX_AGE = timedelta(days=180)
ALERT_FEEDBACK_MAX_ITEMS = 500
ALERT_FEEDBACK_MAX_AGE = timedelta(days=365)
NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT = 64
NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT = 32
NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT = 64
NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT = 500
NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT = 2000
NILM_SESSION_HISTORY_MAX_AGE = timedelta(days=45)
NILM_UNMATCHED_EDGES_MAX_ITEMS_PER_CIRCUIT = 512
RECOMMENDATION_HISTORY_MAX_ITEMS = 200
RECOMMENDATION_HISTORY_MAX_AGE = timedelta(days=180)
RECOMMENDATION_DECISIONS_MAX_ITEMS = 500
RECOMMENDATION_DECISIONS_MAX_AGE = timedelta(days=365)


def initialize_runtime(
    coordinator: Any,
    *,
    hass: Any,
    entry_id: str,
    now_fn: Any | None,
    statistics_during_period: Any,
    recorder_get_instance: Any,
    track_state_change_event: Any,
    debounce_seconds: float,
    max_batch_seconds: float,
) -> None:
    """Attach the established manager and processor runtime to a coordinator."""
    self = coordinator
    self.circuit_registry = CircuitRegistry(self)
    self._now_fn = now_fn or (lambda: datetime.now(UTC))
    self._entry_retention_mode = _retention_mode_from_sources(
        self.entry_data,
        self.options,
    )
    self.source_samples = SourceSampleBuilder(hass, entry_id=entry_id)
    self.dashboard_layout = normalize_dashboard_layout(
        self.options.get(
            CONF_DASHBOARD_LAYOUT,
            self.entry_data.get(CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT),
        )
    )
    self.last_dashboard_create_request: dict[str, Any] | None = None
    self.last_dashboard_remove_request: dict[str, Any] | None = None
    self.dashboard_status: dict[str, Any] | None = (
        dict(self.store_data.dashboard_status)
        if self.store_data.dashboard_status
        else None
    )
    self.config_entry_controller = ConfigEntryController(self)
    self.dashboard_controller = DashboardController(self)
    self.entity_profile_controller = EntityProfileController(self)
    self.evidence_actions = EvidenceActionController(self)
    self.nilm_controller = NilmController(
        self,
        label_interval_max_items=NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT,
        assignment_max_items=NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT,
    )
    self.settings_controller = SettingsController(self)
    self.alert_policies = AlertPolicyManager(self)
    self.processor_runtime = ProcessorRuntimeManager(self)
    self.export_manager = ExportManager(self)
    self.context_builder = ProcessingContextBuilder(self)
    self.demo_data = DemoDataSeeder(self)
    self.pipeline = ProcessingPipeline(self)
    self.state_reducer = StateReducer()
    self.utility_energy_sources = UtilityEnergySourceManager(
        self,
        statistics_during_period=statistics_during_period,
        recorder_get_instance=recorder_get_instance,
    )
    self.environment_context = EnvironmentalContextManager(self)
    self.settings_controller.apply_config_entry_settings()
    self._detectors = {
        config.circuit_id: CircuitEventDetector()
        for config in self.circuit_configs
    }
    self._baseline_values: defaultdict[str, list[float]] = defaultdict(list)
    self._event_processor = CircuitEventProcessor(self._detectors)
    self._power_quality_processor = PowerQualityProcessor(
        alert_policy_for_circuit=self.alert_policies.alert_policy_for_circuit,
        learning_mature=self.processor_runtime.learning_mature,
        seed_demo_event_history=self.demo_data.seed_event_history,
        seed_demo_power_quality_baselines=(
            self.demo_data.seed_power_quality_baselines
        ),
        baseline_values=self._baseline_values,
    )
    self._energy_usage_processor = EnergyUsageProcessor(
        settings_for_config=(
            self.processor_runtime.energy_usage_settings_for_config
        ),
        retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
            self._retention_mode_for_circuit(circuit_id)
        ].days,
        alert_policy_for_circuit=self.alert_policies.usage_alert_policy_for_circuit,
        seed_demo_history=self.demo_data.seed_energy_usage_history,
    )
    self._energy_goal_processor = EnergyGoalProcessor(
        settings_for_config=self.processor_runtime.energy_goal_settings_for_config,
        alert_policy_for_circuit=self.alert_policies.goal_alert_policy_for_circuit,
    )
    self._run_cycle_processor = RunCycleProcessor(
        alert_policy_for_circuit=self.alert_policies.cycle_alert_policy_for_circuit,
        learning_mature=self.processor_runtime.learning_mature,
    )
    self._appliance_health_processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=self.alert_policies.cycle_alert_policy_for_circuit,
        short_cycle_alert_policy_for_circuit=(
            self.alert_policies.appliance_health_short_cycle_alert_policy_for_circuit
        ),
        merge_gap_seconds_for_config=lambda config: (
            resolve_operating_detection_from_settings(
                config,
                self.store_data.operating_detection_settings_by_circuit.get(
                    config.circuit_id,
                    {},
                ),
            ).profile.merge_gap_seconds
        ),
    )
    self._activity_alert_processor = ActivityAlertProcessor(
        settings_for_config=(
            self.processor_runtime.activity_alert_settings_for_config
        ),
        alert_policy_for_circuit=(
            self.alert_policies.activity_alert_policy_for_circuit
        ),
    )
    self._billing_cycle_processor = BillingCycleProcessor(
        settings_for_config=(
            self.processor_runtime.billing_cycle_settings_for_config
        ),
        alert_policy_for_circuit=(
            self.alert_policies.billing_alert_policy_for_circuit
        ),
    )
    self._cost_processor = CostProcessor(
        settings_for_config=self.processor_runtime.cost_settings_for_config,
        utility_rate_for_circuit=lambda _circuit_id: (
            effective_electricity_rate(
                self.state.utility_cost_rate_by_circuit,
            )
            or None
        ),
    )
    self._demand_processor = DemandProcessor(
        settings_for_config=self.processor_runtime.demand_settings_for_config,
        alert_policy_for_circuit=self.alert_policies.demand_alert_policy_for_circuit,
        retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
            self._retention_mode_for_circuit(circuit_id)
        ].days,
    )
    self._capacity_processor = CapacityProcessor(
        settings_for_config=self.processor_runtime.capacity_settings_for_config,
        alert_policy_for_circuit=(
            self.alert_policies.capacity_alert_policy_for_circuit
        ),
        retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
            self._retention_mode_for_circuit(circuit_id)
        ].days,
        source_states_for=self._source_states_for,
    )
    self._leg_imbalance_processor = LegImbalanceProcessor(
        alert_policy_for_circuit=(
            self.alert_policies.leg_imbalance_alert_policy_for_circuit
        ),
    )
    self._metric_consistency_processor = MetricConsistencyProcessor()
    self._standby_processor = StandbyProcessor(
        settings_for_config=self.processor_runtime.standby_settings_for_config,
        alert_policy_for_circuit=(
            self.alert_policies.standby_alert_policy_for_circuit
        ),
        seed_demo_history=self.demo_data.seed_standby_history,
    )
    self._utility_comparison_processor = UtilityComparisonProcessor(
        settings_for_circuit=(
            self.processor_runtime.utility_comparison_settings_for_circuit
        ),
        alert_policy_for_circuit=(
            self.alert_policies.utility_comparison_alert_policy_for_circuit
        ),
        energy_kwh_for_entity=self.utility_energy_sources.energy_kwh_for_entity,
        energy_kwh_sum_for_entities=(
            self.utility_energy_sources.energy_kwh_sum_for_entities
        ),
        statistics_kwh_for_id=self.utility_energy_sources.statistics_kwh_for_id,
        statistics_kwh_sum_for_entities=(
            self.utility_energy_sources.statistics_kwh_sum_for_entities
        ),
        load_energy_entity_ids_for_sum=(
            self.utility_energy_sources.load_energy_entity_ids_for_sum
        ),
        numeric_value_for_entity=self.context_builder.numeric_entity_value,
    )
    self._mains_balance_processor = MainsBalanceProcessor(
        settings_for_circuit=lambda circuit_id: (
            self.store_data.balance_settings_by_circuit.get(circuit_id, {})
        ),
    )
    self._solar_flow_processor = SolarFlowProcessor(
        settings_for_circuit=lambda circuit_id: (
            self.store_data.solar_flow_settings_by_circuit.get(circuit_id, {})
        ),
    )
    self._hvac_efficiency_processor = HvacEfficiencyProcessor()
    self.pipeline.configure_processors(
        event_processor=self._event_processor,
        power_quality_processor=self._power_quality_processor,
        energy_usage_processor=self._energy_usage_processor,
        energy_goal_processor=self._energy_goal_processor,
        run_cycle_processor=self._run_cycle_processor,
        appliance_health_processor=self._appliance_health_processor,
        activity_alert_processor=self._activity_alert_processor,
        billing_cycle_processor=self._billing_cycle_processor,
        cost_processor=self._cost_processor,
        demand_processor=self._demand_processor,
        capacity_processor=self._capacity_processor,
        leg_imbalance_processor=self._leg_imbalance_processor,
        metric_consistency_processor=self._metric_consistency_processor,
        standby_processor=self._standby_processor,
        hvac_efficiency_processor=self._hvac_efficiency_processor,
        mains_balance_processor=self._mains_balance_processor,
        solar_flow_processor=self._solar_flow_processor,
        utility_comparison_processor=self._utility_comparison_processor,
        clear_power_quality_state=lambda circuit_id: (
            self.state_reducer.clear_power_quality_state(self.state, circuit_id)
        ),
        clear_standby_state=lambda circuit_id: (
            self.state_reducer.clear_standby_state(self.state, circuit_id)
        ),
        sync_setup_health_repairs=self._sync_setup_health_repairs,
    )
    self._nilm_topology_processor = NilmTopologyProcessor(
        known_config_for_circuit=self.circuit_registry.config_for_circuit,
        alert_policy_for_circuit=(
            self.alert_policies.nilm_topology_alert_policy_for_circuit
        ),
    )
    self._nilm_detectors: dict[str, NilmEdgeDetector] = {}
    self._nilm_unmatched_edges: defaultdict[str, list[NilmEdge]] = defaultdict(list)
    self._nilm_total_events_by_circuit: defaultdict[str, int] = defaultdict(int)
    self.ignored_nilm_signatures: set[tuple[str, str]] = set()
    self._nilm_sample_processor = NilmSampleProcessor(
        nilm_enabled=self.nilm_controller.enabled_for_config,
        seed_demo_nilm_state=self.nilm_controller.seed_demo_state,
        min_delta_w_for_circuit=self.settings_controller.nilm_min_delta_w,
        detectors=self._nilm_detectors,
        total_events_by_circuit=self._nilm_total_events_by_circuit,
        unmatched_edges_by_circuit=self._nilm_unmatched_edges,
        ignored_signatures=self.ignored_nilm_signatures,
        known_load_events=self.nilm_controller.known_load_events,
        observe_topology=(
            lambda config, match, context: [
                alert
                for alert in [
                    self.nilm_controller.observe_known_load_topology(
                        config,
                        match,
                        context,
                    )
                ]
                if alert is not None
            ]
        ),
        unmatched_edges_max_items=NILM_UNMATCHED_EDGES_MAX_ITEMS_PER_CIRCUIT,
    )
    self.nilm_controller.configure_processors(
        sample_processor=self._nilm_sample_processor,
        topology_processor=self._nilm_topology_processor,
        total_events_by_circuit=self._nilm_total_events_by_circuit,
        unmatched_edges_by_circuit=self._nilm_unmatched_edges,
    )
    self._water_context_alert_processor = WaterContextAlertProcessor(
        alert_policy_for_circuit=(
            self.alert_policies.water_context_alert_policy_for_circuit
        ),
    )
    self.store_persistence = StorePersistenceManager(
        self,
        retention_mode_for_circuit=self._retention_mode_for_circuit,
        ha_time_zone=self.context_builder.time_zone,
        weather_context_history_max_samples=WEATHER_CONTEXT_HISTORY_MAX_SAMPLES,
        water_context_history_max_samples=WATER_CONTEXT_HISTORY_MAX_SAMPLES,
        alert_history_max_age=ALERT_HISTORY_MAX_AGE,
        alert_history_max_items=ALERT_HISTORY_MAX_ITEMS,
        alert_feedback_max_age=ALERT_FEEDBACK_MAX_AGE,
        alert_feedback_max_items=ALERT_FEEDBACK_MAX_ITEMS,
        nilm_signatures_max_items=NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT,
        nilm_unknown_loads_max_items=NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT,
        nilm_session_history_max_age=NILM_SESSION_HISTORY_MAX_AGE,
        nilm_session_history_max_items=NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
        recommendation_history_max_age=RECOMMENDATION_HISTORY_MAX_AGE,
        recommendation_history_max_items=RECOMMENDATION_HISTORY_MAX_ITEMS,
        recommendation_decisions_max_age=RECOMMENDATION_DECISIONS_MAX_AGE,
        recommendation_decisions_max_items=RECOMMENDATION_DECISIONS_MAX_ITEMS,
    )
    self.notification_controller = NotificationController(self)
    self.setup_health = SetupHealthAggregator(self)
    self.paused_circuits: set[str] = set()
    self.last_exported_diagnostics: dict[str, Any] = {}
    self.last_exported_history_csv: str = ""
    self.mapping_checks_run = 0
    self._last_settings_recommendation_source_refresh_at: datetime | None = None
    self._unsub_expected_schedule_interval: Any | None = None
    self._unsub_maintenance_expiry: Any | None = None
    self.state = AnalyzerState()
    self.started = False
    self.source_updates = SourceUpdateManager(
        self,
        track_state_change_event=track_state_change_event,
        debounce_seconds=debounce_seconds,
        max_batch_seconds=max_batch_seconds,
    )
    self.ux_state = UxStateManager(self)
