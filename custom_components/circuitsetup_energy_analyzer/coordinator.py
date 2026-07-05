from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from . import notifications as notifications  # noqa: F401 - compatibility for tests
from . import repairs as repairs  # noqa: F401 - compatibility for test monkeypatching
from .activity_timeline import (
    DEFAULT_TIMELINE_WINDOW_HOURS,
)
from .alerting import alert_anomaly_score
from .config_parsing import (
    circuit_configs_from_entry_data as _circuit_configs_from_entry_data,
)
from .config_parsing import (
    retention_mode_from_sources as _retention_mode_from_sources,
)
from .const import (
    CONF_DASHBOARD_LAYOUT,
    DEFAULT_DASHBOARD_LAYOUT,
    DOMAIN,
)
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
from .managers.settings_controller import (
    SettingsController,
    material_recommendation_evidence_key,
)
from .managers.setup_health import SetupHealthAggregator
from .managers.source_samples import (
    SourceSampleBuilder,
)
from .managers.source_updates import SourceUpdateManager
from .managers.state_reducer import StateReducer, apply_state_update
from .managers.store_persistence import StorePersistenceManager
from .managers.utility_energy_sources import (
    UtilityEnergySourceManager,
    _ha_recorder_get_instance,
    _ha_statistics_during_period,
)
from .managers.ux_state import UxStateManager
from .models import (
    AlertEvidence,
    CircuitConfig,
    CircuitEvent,
    RetentionMode,
)
from .nilm import (
    NilmEdge,
    NilmEdgeDetector,
)
from .normalize import NormalizedCircuitSample, SourceState
from .processors import (
    ActivityAlertProcessor,
    BillingCycleProcessor,
    CapacityProcessor,
    CircuitEventProcessor,
    CostProcessor,
    DemandProcessor,
    EnergyGoalProcessor,
    EnergyUsageProcessor,
    FeatureResult,
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
from .storage import (
    RETENTION_WINDOWS,
    FeatureStoreData,
)
from .ux import (
    canonicalize_sensitivity_config,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS = 0.5
SOURCE_STATE_UPDATE_MAX_BATCH_SECONDS = 5.0
SETTINGS_RECOMMENDATION_SOURCE_REFRESH_INTERVAL = timedelta(minutes=5)
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
try:
    from homeassistant.helpers.event import async_track_state_change_event
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
except ModuleNotFoundError:
    async_track_state_change_event = None

    class DataUpdateCoordinator:
        """Small fallback so helper tests can import without Home Assistant."""

        def __init__(
            self,
            hass: Any,
            logger: logging.Logger | None = None,
            *,
            name: str | None = None,
            **_: Any,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.data: Any = None

        def async_set_updated_data(self, data: Any) -> None:
            self.data = data


@dataclass(slots=True)
class AnalyzerState:
    """Runtime state exposed by the energy analyzer coordinator."""

    last_event_by_circuit: dict[str, CircuitEvent] = field(default_factory=dict)
    active_alerts_by_circuit: dict[str, list[AlertEvidence]] = field(
        default_factory=dict
    )
    anomaly_score_by_circuit: dict[str, float] = field(default_factory=dict)
    learning_by_circuit: dict[str, bool] = field(default_factory=dict)
    data_quality_by_circuit: dict[str, str] = field(default_factory=dict)
    power_quality_score_by_circuit: dict[str, float] = field(default_factory=dict)
    power_quality_evidence_by_circuit: dict[str, str] = field(default_factory=dict)
    reactive_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    apparent_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    power_factor_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    nilm_signature_count_by_circuit: dict[str, int] = field(default_factory=dict)
    nilm_unmatched_load_percentage_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    nilm_topology_status_by_circuit: dict[str, str] = field(default_factory=dict)
    nilm_topology_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    health_status_by_circuit: dict[str, str] = field(default_factory=dict)
    health_summary_by_circuit: dict[str, str] = field(default_factory=dict)
    readiness_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    learning_progress_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    data_quality_checklist_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    energy_dashboard_status_by_circuit: dict[str, str] = field(default_factory=dict)
    energy_dashboard_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    alert_evidence_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    recent_activity_by_circuit: dict[str, str] = field(default_factory=dict)
    recent_activity_count_by_circuit: dict[str, int] = field(default_factory=dict)
    recent_activity_timeline_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    recent_observations_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
    circuit_mode_by_circuit: dict[str, str] = field(default_factory=dict)
    power_flow_by_circuit: dict[str, str] = field(default_factory=dict)
    maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    latest_real_power_w_by_circuit: dict[str, float] = field(default_factory=dict)
    operating_state_by_circuit: dict[str, str] = field(default_factory=dict)
    operating_state_snapshot_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    nilm_review_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    nilm_unknown_loads_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    weather_context_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    rain_pump_context_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    water_flow_context_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    water_context_history_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    daily_energy_usage_by_circuit: dict[str, float] = field(default_factory=dict)
    energy_usage_share_by_circuit: dict[str, float] = field(default_factory=dict)
    energy_usage_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    energy_goal_usage_by_circuit: dict[str, float] = field(default_factory=dict)
    energy_goal_status_by_circuit: dict[str, str] = field(default_factory=dict)
    energy_goal_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    run_cycle_count_by_circuit: dict[str, int] = field(default_factory=dict)
    run_cycle_runtime_seconds_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    run_cycle_duty_cycle_by_circuit: dict[str, float] = field(default_factory=dict)
    run_cycle_status_by_circuit: dict[str, str] = field(default_factory=dict)
    run_cycle_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    billing_cycle_usage_kwh_by_circuit: dict[str, float] = field(default_factory=dict)
    billing_cycle_forecast_kwh_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    billing_cycle_budget_usage_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    billing_cycle_status_by_circuit: dict[str, str] = field(default_factory=dict)
    billing_cycle_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    cost_current_rate_by_circuit: dict[str, float] = field(default_factory=dict)
    cost_cycle_by_circuit: dict[str, float] = field(default_factory=dict)
    cost_cycle_forecast_by_circuit: dict[str, float] = field(default_factory=dict)
    cost_status_by_circuit: dict[str, str] = field(default_factory=dict)
    cost_evidence_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_demand_w_by_circuit: dict[str, float] = field(default_factory=dict)
    peak_demand_w_by_circuit: dict[str, float] = field(default_factory=dict)
    demand_limit_usage_by_circuit: dict[str, float] = field(default_factory=dict)
    demand_peak_rank_by_circuit: dict[str, int] = field(default_factory=dict)
    demand_peak_status_by_circuit: dict[str, str] = field(default_factory=dict)
    demand_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    capacity_usage_by_circuit: dict[str, float] = field(default_factory=dict)
    capacity_status_by_circuit: dict[str, str] = field(default_factory=dict)
    capacity_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    leg_imbalance_percent_by_circuit: dict[str, float] = field(default_factory=dict)
    leg_imbalance_status_by_circuit: dict[str, str] = field(default_factory=dict)
    leg_imbalance_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    metric_consistency_score_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    metric_consistency_status_by_circuit: dict[str, str] = field(default_factory=dict)
    metric_consistency_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    balance_power_w_by_circuit: dict[str, float] = field(default_factory=dict)
    monitored_power_w_by_circuit: dict[str, float] = field(default_factory=dict)
    monitored_coverage_percent_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    balance_status_by_circuit: dict[str, str] = field(default_factory=dict)
    balance_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    solar_generation_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_site_consumption_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_grid_import_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_grid_export_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_self_consumption_percent_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    solar_powered_percent_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_surplus_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_load_shift_w_by_circuit: dict[str, float] = field(default_factory=dict)
    solar_flexible_load_power_w_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    solar_flexible_load_coverage_percent_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    solar_flow_status_by_circuit: dict[str, str] = field(default_factory=dict)
    solar_surplus_status_by_circuit: dict[str, str] = field(default_factory=dict)
    solar_load_shift_status_by_circuit: dict[str, str] = field(default_factory=dict)
    solar_flow_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    solar_load_shift_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    utility_comparison_difference_kwh_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    utility_comparison_difference_percent_by_circuit: dict[str, float] = field(
        default_factory=dict
    )
    utility_comparison_status_by_circuit: dict[str, str] = field(default_factory=dict)
    utility_comparison_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    always_on_power_w_by_circuit: dict[str, float] = field(default_factory=dict)
    standby_threshold_w_by_circuit: dict[str, float] = field(default_factory=dict)
    standby_status_by_circuit: dict[str, str] = field(default_factory=dict)
    always_on_limit_usage_by_circuit: dict[str, float] = field(default_factory=dict)
    standby_evidence_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    settings_recommendations_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    settings_recommendation_count_by_circuit: dict[str, int] = field(
        default_factory=dict
    )


def process_events_into_state(
    state: AnalyzerState,
    events: Iterable[CircuitEvent],
    alerts: Iterable[AlertEvidence],
) -> AnalyzerState:
    """Fold newly detected events and alerts into analyzer runtime state."""
    for event in events:
        previous = state.last_event_by_circuit.get(event.circuit_id)
        if previous is None or event.timestamp >= previous.timestamp:
            state.last_event_by_circuit[event.circuit_id] = event

    alerts_by_circuit: defaultdict[str, list[AlertEvidence]] = defaultdict(list)
    for alert in alerts:
        alerts_by_circuit[alert.circuit_id].append(alert)

    state.active_alerts_by_circuit = dict(alerts_by_circuit)
    state.anomaly_score_by_circuit = {
        circuit_id: max(alert_anomaly_score(alert) for alert in circuit_alerts)
        for circuit_id, circuit_alerts in alerts_by_circuit.items()
    }

    for circuit_id in state.last_event_by_circuit:
        state.anomaly_score_by_circuit.setdefault(circuit_id, 0.0)

    return state


def _apply_state_update(state: Any, path: tuple[str, ...], value: Any) -> None:
    """Apply a processor-requested update to AnalyzerState."""
    apply_state_update(state, path, value)


def _normalized_entity_ids(entity_ids: Iterable[str] | None) -> set[str]:
    if entity_ids is None:
        return set()
    return {
        entity_id
        for entity_id in (str(entity_id).strip() for entity_id in entity_ids)
        if entity_id
    }


def _source_circuit_ids_by_entity(
    circuit_configs: Iterable[CircuitConfig],
) -> dict[str, tuple[str, ...]]:
    circuit_ids_by_entity: defaultdict[str, list[str]] = defaultdict(list)
    for config in circuit_configs:
        for sensor in config.sensors:
            entity_id = str(sensor.entity_id).strip()
            if entity_id:
                circuit_ids_by_entity[entity_id].append(config.circuit_id)
    return {
        entity_id: tuple(circuit_ids)
        for entity_id, circuit_ids in circuit_ids_by_entity.items()
    }


class EnergyAnalyzerCoordinator(DataUpdateCoordinator):
    """Runtime coordinator for source sensor updates and analyzer state."""

    def __init__(
        self: Self,
        hass: Any,
        *,
        entry_id: str = "default",
        entry_data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        store: Any | None = None,
        store_data: FeatureStoreData | None = None,
        config_entry: Any | None = None,
        now_fn: Any | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry_id = entry_id
        self.entry_data = canonicalize_sensitivity_config(entry_data or {})
        self.options = canonicalize_sensitivity_config(options or {})
        self._config_entry = config_entry
        self._store = store
        self.store_data = store_data or FeatureStoreData()
        self.circuit_configs = _circuit_configs_from_entry_data(
            self.entry_data,
            self.options,
        )
        self._source_circuit_ids_by_entity = _source_circuit_ids_by_entity(
            self.circuit_configs
        )
        self._known_source_entity_ids = frozenset(self._source_circuit_ids_by_entity)
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
            statistics_during_period=_ha_statistics_during_period,
            recorder_get_instance=_ha_recorder_get_instance,
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
        self.pipeline.configure_processors(
            event_processor=self._event_processor,
            power_quality_processor=self._power_quality_processor,
            energy_usage_processor=self._energy_usage_processor,
            energy_goal_processor=self._energy_goal_processor,
            run_cycle_processor=self._run_cycle_processor,
            activity_alert_processor=self._activity_alert_processor,
            billing_cycle_processor=self._billing_cycle_processor,
            cost_processor=self._cost_processor,
            demand_processor=self._demand_processor,
            capacity_processor=self._capacity_processor,
            leg_imbalance_processor=self._leg_imbalance_processor,
            metric_consistency_processor=self._metric_consistency_processor,
            standby_processor=self._standby_processor,
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
        self.notification_controller = NotificationController(
            self,
            material_evidence_key=material_recommendation_evidence_key,
        )
        self.setup_health = SetupHealthAggregator(self)
        self.paused_circuits: set[str] = set()
        self.last_exported_diagnostics: dict[str, Any] = {}
        self.last_exported_history_csv: str = ""
        self.mapping_checks_run = 0
        self._last_settings_recommendation_source_refresh_at: datetime | None = None
        self.state = AnalyzerState()
        self.started = False
        self.source_updates = SourceUpdateManager(
            self,
            track_state_change_event=async_track_state_change_event,
            debounce_seconds=SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS,
            max_batch_seconds=SOURCE_STATE_UPDATE_MAX_BATCH_SECONDS,
        )
        self.ux_state = UxStateManager(self)
        self._hydrate_state_from_store()
        self.async_set_updated_data(self.state)

    async def async_start(self: Self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        await self.source_updates.async_start(source_entities)

    async def async_stop(self: Self) -> None:
        """Stop listening to source entity state changes."""
        await self.source_updates.async_stop()

    @property
    def _source_update_task(self: Self) -> Any | None:
        """Compatibility accessor for lifecycle wait helpers."""
        return self.source_updates.source_update_task

    @property
    def source_entities(self: Self) -> tuple[str, ...]:
        """Configured source entities currently watched by the coordinator."""
        return self.source_updates.source_entities

    @source_entities.setter
    def source_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.source_entities = tuple(value)

    @property
    def pending_source_update_entities(self: Self) -> tuple[str, ...]:
        """Source entities queued for the next debounced update."""
        return self.source_updates.pending_source_update_entities

    @pending_source_update_entities.setter
    def pending_source_update_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.pending_source_update_entities = tuple(value)

    @property
    def last_source_update_entities(self: Self) -> tuple[str, ...]:
        """Source entities included in the most recent debounced update."""
        return self.source_updates.last_source_update_entities

    @last_source_update_entities.setter
    def last_source_update_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.last_source_update_entities = tuple(value)

    def current_time(self: Self) -> datetime:
        """Return the coordinator's current runtime timestamp."""
        return self._now_fn()

    def _processing_configs_for_changed_entities(
        self: Self,
        changed_entities: Iterable[str] | None,
    ) -> tuple[CircuitConfig, ...]:
        """Return circuit configs that need expensive per-circuit processing."""
        changed = _normalized_entity_ids(changed_entities)
        if not changed:
            return tuple(self.circuit_configs)

        if not changed.issubset(self._known_source_entity_ids):
            return tuple(self.circuit_configs)

        selected_circuit_ids = {
            circuit_id
            for entity_id in changed
            for circuit_id in self._source_circuit_ids_by_entity.get(entity_id, ())
        }
        if not selected_circuit_ids:
            return tuple(self.circuit_configs)

        selected_configs = [
            config
            for config in self.circuit_configs
            if config.circuit_id in selected_circuit_ids
        ]
        if any(
            not self.nilm_controller.enabled_for_config(config)
            for config in selected_configs
        ):
            selected_circuit_ids.update(
                config.circuit_id
                for config in self.circuit_configs
                if self.nilm_controller.enabled_for_config(config)
            )

        return tuple(
            config
            for config in self.circuit_configs
            if config.circuit_id in selected_circuit_ids
        )

    def _settings_recommendation_refresh_due(
        self: Self,
        now: datetime,
        *,
        changed_entities: Iterable[str] | None,
        force: bool,
    ) -> bool:
        if changed_entities is None:
            return True
        if force or self._last_settings_recommendation_source_refresh_at is None:
            self._last_settings_recommendation_source_refresh_at = now
            return True
        if (
            now - self._last_settings_recommendation_source_refresh_at
            >= SETTINGS_RECOMMENDATION_SOURCE_REFRESH_INTERVAL
        ):
            self._last_settings_recommendation_source_refresh_at = now
            return True
        return False

    def refresh_energy_goal_state(
        self: Self,
        circuit_id: str,
        config: CircuitConfig,
        context: Any,
    ) -> FeatureResult:
        """Refresh daily energy-goal state through the configured processor."""
        return self._energy_goal_processor.refresh_state(circuit_id, config, context)

    async def async_process_update(
        self: Self,
        *,
        changed_entities: Iterable[str] | None = None,
    ) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        context = self.context_builder.build(now)
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []
        processing_configs = self._processing_configs_for_changed_entities(
            changed_entities
        )
        processing_circuit_ids = {
            config.circuit_id for config in processing_configs
        }
        self.state_reducer.prune_recent_observations(
            self.state,
            now,
            window_hours=DEFAULT_TIMELINE_WINDOW_HOURS,
        )

        for config in self.circuit_configs:
            sample = self._sample_for_config(config, now)
            samples.append((config, sample))
            self.state_reducer.refresh_config_metadata_state(self.state, config)
            self.state_reducer.refresh_latest_real_power_state(
                self.state,
                config,
                sample,
            )
            if config.circuit_id not in processing_circuit_ids:
                continue
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            new_events, new_alerts = await self.pipeline.async_process_circuit(
                config,
                sample,
                context,
            )
            events.extend(new_events)
            alerts.extend(new_alerts)

        for config, sample in samples:
            if config.circuit_id not in processing_circuit_ids:
                continue
            for nilm_alert in self.nilm_controller.process_sample(
                config,
                sample,
                events,
                context,
            ):
                nilm_alert = self.evidence_actions.alert_with_feedback(nilm_alert)
                if nilm_alert.feedback_status != "expected":
                    alerts.append(nilm_alert)
                self.store_data.alerts.append(nilm_alert)
                self._mark_store_dirty()
                await self._notify_alert(nilm_alert)
        alerts.extend(await self._notify_nilm_virtual_appliances(now))
        alerts.extend(await self.pipeline.async_process_cross_circuit(samples, context))

        process_events_into_state(self.state, events, alerts)
        for config, sample in samples:
            self._refresh_ux_state(config, sample, now, context)
            if config.circuit_id not in processing_circuit_ids:
                continue
            await self._sync_setup_health_repairs(config.circuit_id)
            water_context_alert = self.environment_context.observe_water_context(
                config,
                now,
            )
            if water_context_alert is not None:
                water_context_alert = self.evidence_actions.alert_with_feedback(
                    water_context_alert
                )
                if water_context_alert.feedback_status != "expected":
                    alerts.append(water_context_alert)
                self.store_data.alerts.append(water_context_alert)
                self._mark_store_dirty()
                await self._notify_alert(water_context_alert)
        if alerts:
            process_events_into_state(self.state, events, alerts)
        recommendation_refresh_due = self._settings_recommendation_refresh_due(
            now,
            changed_entities=changed_entities,
            force=bool(alerts),
        )
        if recommendation_refresh_due:
            if self._rebuild_setting_recommendations(now):
                self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now, force=False)
        if recommendation_refresh_due:
            await (
                self.notification_controller.async_notify_settings_recommendations_if_needed()
            )
        return self.state

    async def async_relearn_baseline(self: Self, circuit_id: str) -> None:
        """Clear learned baselines and alert state for one circuit."""
        self.store_persistence.reset_baseline_for_circuit(
            circuit_id,
            self._baseline_values,
        )
        self.state_reducer.reset_learning_state(self.state, circuit_id)
        self._clear_nilm_topology_state(circuit_id)
        now = self._now_fn()
        self.refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_pause_alerts(
        self: Self,
        circuit_id: str,
        duration: str | None = None,
    ) -> None:
        """Pause alert notifications for a circuit."""
        await self.evidence_actions.async_pause_alerts(circuit_id, duration)

    async def async_acknowledge_alert(self: Self, alert_id: str) -> bool:
        """Acknowledge an active alert evidence item."""
        return await self.evidence_actions.async_acknowledge_alert(alert_id)

    async def async_set_circuit_sensitivity(
        self: Self,
        circuit_id: str,
        preset: str,
    ) -> None:
        """Persist an alert sensitivity preset for one circuit."""
        await self.settings_controller.async_set_circuit_sensitivity(
            circuit_id,
            preset,
        )

    async def async_set_entity_detail_level(self: Self, detail_level: str) -> None:
        """Persist the entity detail level and reload desired entities."""
        await self.entity_profile_controller.async_set_entity_detail_level(
            detail_level,
        )

    async def async_replace_advanced_settings(
        self: Self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace store-backed advanced settings for one circuit."""
        await self.settings_controller.async_replace_advanced_settings(
            circuit_id,
            settings,
        )

    async def async_set_energy_usage_settings(
        self: Self,
        circuit_id: str,
        window_days: Any = None,
        daily_spike_ratio: Any = None,
    ) -> None:
        """Persist daily energy usage spike settings for one circuit."""
        await self.settings_controller.async_set_energy_usage_settings(
            circuit_id,
            window_days,
            daily_spike_ratio,
        )

    async def async_recalculate_setting_recommendations(
        self: Self,
        circuit_id: str | None = None,
    ) -> None:
        """Rebuild pending advanced-setting recommendations from retained data."""
        await self.settings_controller.async_recalculate_setting_recommendations(
            circuit_id,
        )

    def _rebuild_setting_recommendations(
        self: Self,
        now: datetime,
        *,
        circuit_id: str | None = None,
    ) -> bool:
        """Rebuild pending recommendations without saving or notifying."""
        return self.settings_controller.rebuild_setting_recommendations(
            now,
            circuit_id=circuit_id,
        )

    async def async_apply_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Apply one pending setting recommendation to advanced settings."""
        await self.settings_controller.async_apply_setting_recommendation(
            recommendation_id,
        )

    async def async_undo_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> bool:
        """Restore the value recorded before an applied recommendation."""
        return await self.settings_controller.async_undo_setting_recommendation(
            recommendation_id,
        )

    async def async_reset_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> bool:
        """Reset a recommendation-backed setting to its built-in default."""
        return await self.settings_controller.async_reset_setting_recommendation(
            recommendation_id,
        )

    async def async_deny_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Record a denial for one pending setting recommendation."""
        await self.settings_controller.async_deny_setting_recommendation(
            recommendation_id,
        )

    async def async_dismiss_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Record a dismissal for one pending setting recommendation."""
        await self.settings_controller.async_dismiss_setting_recommendation(
            recommendation_id,
        )

    def _refresh_settings_recommendation_state(self: Self, now: datetime) -> None:
        self.settings_controller.refresh_settings_recommendation_state(now)

    async def async_set_energy_goal_settings(
        self: Self,
        circuit_id: str,
        daily_goal_kwh: Any = None,
        goal_alert_ratio: Any = None,
    ) -> None:
        """Persist daily energy goal settings for one circuit."""
        await self.settings_controller.async_set_energy_goal_settings(
            circuit_id,
            daily_goal_kwh,
            goal_alert_ratio,
        )

    async def async_set_activity_alert_settings(
        self: Self,
        circuit_id: str,
        max_active_minutes: Any = None,
        max_idle_minutes: Any = None,
    ) -> None:
        """Persist user-configured activity alert settings for one circuit."""
        await self.settings_controller.async_set_activity_alert_settings(
            circuit_id,
            max_active_minutes,
            max_idle_minutes,
        )

    async def async_set_billing_cycle_settings(
        self: Self,
        circuit_id: str,
        cycle_start_day: Any = None,
        budget_kwh: Any = None,
        budget_alert_ratio: Any = None,
    ) -> None:
        """Persist billing-cycle usage forecast settings for one circuit."""
        await self.settings_controller.async_set_billing_cycle_settings(
            circuit_id,
            cycle_start_day,
            budget_kwh,
            budget_alert_ratio,
        )

    async def async_set_cost_settings(
        self: Self,
        circuit_id: str,
        cycle_start_day: Any = None,
        default_rate_per_kwh: Any = None,
        tou_rate_per_kwh: Any = None,
        tou_start: Any = None,
        tou_end: Any = None,
        tou_weekdays: Any = None,
        tou_name: Any = None,
    ) -> None:
        """Persist cost and Time-of-Use settings for one circuit."""
        await self.settings_controller.async_set_cost_settings(
            circuit_id,
            cycle_start_day,
            default_rate_per_kwh,
            tou_rate_per_kwh,
            tou_start,
            tou_end,
            tou_weekdays,
            tou_name,
        )

    async def async_set_demand_settings(
        self: Self,
        circuit_id: str,
        window_minutes: Any = None,
        demand_limit_w: Any = None,
    ) -> None:
        """Persist rolling demand settings for one circuit."""
        await self.settings_controller.async_set_demand_settings(
            circuit_id,
            window_minutes,
            demand_limit_w,
        )

    async def async_set_capacity_settings(
        self: Self,
        circuit_id: str,
        breaker_amps: Any = None,
        warning_ratio: Any = None,
    ) -> None:
        """Persist circuit capacity settings for one circuit."""
        await self.settings_controller.async_set_capacity_settings(
            circuit_id,
            breaker_amps,
            warning_ratio,
        )

    async def async_set_leg_imbalance_settings(
        self: Self,
        circuit_id: str,
        warning_ratio: Any = None,
        minimum_total_power_w: Any = None,
    ) -> None:
        """Persist dual-phase leg imbalance thresholds for one circuit."""
        await self.settings_controller.async_set_leg_imbalance_settings(
            circuit_id,
            warning_ratio,
            minimum_total_power_w,
        )

    async def async_set_metric_consistency_settings(
        self: Self,
        circuit_id: str,
        apparent_power_tolerance_percent: Any = None,
        power_factor_tolerance: Any = None,
        minimum_apparent_power_va: Any = None,
    ) -> None:
        """Persist W/VA/PF consistency thresholds for one circuit."""
        await self.settings_controller.async_set_metric_consistency_settings(
            circuit_id,
            apparent_power_tolerance_percent,
            power_factor_tolerance,
            minimum_apparent_power_va,
        )

    async def async_set_mains_balance_settings(
        self: Self,
        circuit_id: str,
        negative_tolerance_w: Any = None,
    ) -> None:
        """Persist mains-minus-monitored balance thresholds."""
        await self.settings_controller.async_set_mains_balance_settings(
            circuit_id,
            negative_tolerance_w,
        )

    async def async_set_solar_flow_settings(
        self: Self,
        circuit_id: str,
        export_tolerance_w: Any = None,
        solar_surplus_threshold_w: Any = None,
        high_solar_surplus_threshold_w: Any = None,
        flexible_load_running_threshold_w: Any = None,
    ) -> None:
        """Persist solar flow and flexible-load thresholds."""
        await self.settings_controller.async_set_solar_flow_settings(
            circuit_id,
            export_tolerance_w,
            solar_surplus_threshold_w,
            high_solar_surplus_threshold_w,
            flexible_load_running_threshold_w,
        )

    async def async_set_standby_settings(
        self: Self,
        circuit_id: str,
        window_hours: Any = None,
        standby_threshold_w: Any = None,
        always_on_alert_w: Any = None,
    ) -> None:
        """Persist Always On and standby settings for one circuit."""
        await self.settings_controller.async_set_standby_settings(
            circuit_id,
            window_hours,
            standby_threshold_w,
            always_on_alert_w,
        )

    async def async_set_utility_comparison_settings(
        self: Self,
        circuit_id: str,
        utility_energy_entity: Any = None,
        measured_energy_entities: Any = None,
        tolerance_percent: Any = None,
        utility_statistic_id: Any = None,
        utility_source_type: Any = None,
        utility_statistic_period: Any = None,
    ) -> None:
        """Persist utility-vs-measured kWh comparison settings."""
        await self.settings_controller.async_set_utility_comparison_settings(
            circuit_id,
            utility_energy_entity,
            measured_energy_entities,
            tolerance_percent,
            utility_statistic_id,
            utility_source_type,
            utility_statistic_period,
        )

    async def async_start_maintenance(
        self: Self,
        circuit_id: str,
        note: str = "",
        duration: str | None = None,
        relearn_on_end: bool = False,
    ) -> None:
        """Mark one circuit in maintenance and pause appliance notifications."""
        await self.evidence_actions.async_start_maintenance(
            circuit_id,
            note=note,
            duration=duration,
            relearn_on_end=relearn_on_end,
        )

    async def async_end_maintenance(
        self: Self,
        circuit_id: str,
        relearn: bool = False,
    ) -> None:
        """Clear maintenance state and optionally relearn the circuit baseline."""
        await self.evidence_actions.async_end_maintenance(circuit_id, relearn=relearn)

    async def async_mark_alert_expected(self: Self, alert_id: str) -> bool:
        """Mark an alert pattern as expected for future notifications."""
        return await self.evidence_actions.async_mark_alert_expected(alert_id)

    async def async_mark_alert_unhelpful(self: Self, alert_id: str) -> bool:
        """Mark an alert pattern as unhelpful for future notifications."""
        return await self.evidence_actions.async_mark_alert_unhelpful(alert_id)

    async def async_mark_nilm_appliance_correct(self: Self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as correct."""
        return await self.evidence_actions.async_mark_nilm_appliance_correct(alert_id)

    async def async_mark_nilm_appliance_wrong(self: Self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as the wrong appliance."""
        return await self.evidence_actions.async_mark_nilm_appliance_wrong(alert_id)

    async def async_export_diagnostics(self: Self, circuit_id: str) -> None:
        """Store a lightweight diagnostics export snapshot for a circuit."""
        await self.export_manager.async_export_diagnostics(circuit_id)

    async def async_export_history_csv(self: Self, circuit_id: str) -> None:
        """Store retained analyzer history for one circuit as CSV text."""
        await self.export_manager.async_export_history_csv(circuit_id)

    async def async_run_mapping_checks(self: Self) -> None:
        """Run lightweight source mapping checks."""
        await self.setup_health.async_run_mapping_checks()

    async def async_create_dashboard(self: Self) -> dict[str, Any]:
        """Create or update the recommended Home Assistant dashboard."""
        return await self.dashboard_controller.async_create_dashboard()

    async def async_remove_dashboard(self: Self) -> dict[str, Any]:
        """Remove the recommended Home Assistant dashboard."""
        return await self.dashboard_controller.async_remove_dashboard()

    async def async_set_dashboard_layout(self: Self, layout: str) -> None:
        """Persist the selected recommended-dashboard layout."""
        await self.dashboard_controller.async_set_dashboard_layout(layout)

    async def async_label_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        label: str,
    ) -> None:
        """Persist a user-confirmed label for a NILM signature."""
        await self.nilm_controller.async_label_nilm_signature(
            circuit_id,
            signature_id,
            label,
        )

    async def async_label_nilm_interval(
        self: Self,
        circuit_id: str,
        *,
        label: str,
        start: Any,
        end: Any,
        appliance_id: str | None = None,
        mains_entity_id: str | None = None,
        ground_truth_entity_id: str | None = None,
        validation_start: Any = None,
        validation_end: Any = None,
        interval_id: str | None = None,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Persist a user-labeled NILM graph interval."""
        return await self.nilm_controller.async_label_nilm_interval(
            circuit_id,
            label=label,
            start=start,
            end=end,
            appliance_id=appliance_id,
            mains_entity_id=mains_entity_id,
            ground_truth_entity_id=ground_truth_entity_id,
            validation_start=validation_start,
            validation_end=validation_end,
            interval_id=interval_id,
            source=source,
            confidence=confidence,
        )

    async def async_delete_nilm_label_interval(
        self: Self,
        circuit_id: str,
        interval_id: str,
    ) -> bool:
        """Delete a user-labeled NILM graph interval."""
        return await self.nilm_controller.async_delete_nilm_label_interval(
            circuit_id,
            interval_id,
        )

    async def async_assign_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM signature to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_signature(
            circuit_id,
            signature_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_assign_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        label: str,
        signature_fingerprint: str | None = None,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM session to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_session(
            circuit_id,
            session_id,
            label=label,
            signature_fingerprint=signature_fingerprint,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_assign_nilm_interval(
        self: Self,
        circuit_id: str,
        interval_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM label interval to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_interval(
            circuit_id,
            interval_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_validate_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session matched its appliance assignment."""
        return await self.nilm_controller.async_validate_nilm_session(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
        )

    async def async_reject_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session did not match its appliance assignment."""
        return await self.nilm_controller.async_reject_nilm_session(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
        )

    async def async_validate_nilm_assignment_history(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Confirm assigned NILM sessions that overlap ground-truth intervals."""
        return await self.nilm_controller.async_validate_nilm_assignment_history(
            circuit_id,
            assignment_id,
        )

    async def async_rename_nilm_appliance(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        """Rename a NILM appliance assignment without changing its stable ID."""
        return await self.nilm_controller.async_rename_nilm_appliance(
            circuit_id,
            assignment_id,
            label=label,
        )

    async def async_change_nilm_appliance_profile(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        appliance_profile: str,
    ) -> dict[str, Any]:
        """Change the appliance profile hint for a NILM assignment."""
        return await self.nilm_controller.async_change_nilm_appliance_profile(
            circuit_id,
            assignment_id,
            appliance_profile=appliance_profile,
        )

    async def async_merge_nilm_assignments(
        self: Self,
        circuit_id: str,
        source_assignment_id: str,
        target_assignment_id: str,
    ) -> dict[str, Any]:
        """Merge one NILM appliance assignment into another."""
        return await self.nilm_controller.async_merge_nilm_assignments(
            circuit_id,
            source_assignment_id,
            target_assignment_id,
        )

    async def async_publish_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Publish estimated HA entities for a NILM assignment."""
        return await self.nilm_controller.async_publish_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_unpublish_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Stop publishing estimated HA entities for a NILM assignment."""
        return await self.nilm_controller.async_unpublish_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_retire_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Retire a NILM assignment and stop publishing entities."""
        return await self.nilm_controller.async_retire_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_ignore_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an ignored NILM signature marker."""
        await self.nilm_controller.async_ignore_nilm_signature(
            circuit_id,
            signature_id,
        )

    async def async_mark_nilm_signature_expected(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an expected NILM signature review decision."""
        await self.nilm_controller.async_mark_nilm_signature_expected(
            circuit_id,
            signature_id,
        )

    async def async_merge_nilm_signatures(
        self: Self,
        circuit_id: str,
        source_signature_id: str,
        target_signature_id: str,
    ) -> None:
        """Persist that one NILM signature should be treated as another."""
        await self.nilm_controller.async_merge_nilm_signatures(
            circuit_id,
            source_signature_id,
            target_signature_id,
        )

    def has_circuit(self: Self, circuit_id: str) -> bool:
        """Return whether this coordinator owns a circuit id."""
        return any(config.circuit_id == circuit_id for config in self.circuit_configs)

    def _hydrate_state_from_store(self: Self) -> None:
        self.ux_state.hydrate_state_from_store()

    def refresh_all_ux_state(self: Self, now: datetime) -> None:
        self.ux_state.refresh_all(now)

    def refresh_ux_state_for_circuit(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        self.ux_state.refresh_for_circuit(circuit_id, now)

    def _refresh_ux_state(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample | None,
        now: datetime,
        context: Any | None = None,
    ) -> None:
        self.ux_state.refresh_config(config, sample, now, context)

    def _latest_alert_for_circuit(self: Self, circuit_id: str) -> AlertEvidence | None:
        return self.ux_state.latest_alert_for_circuit(circuit_id)

    def _sample_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> NormalizedCircuitSample:
        return self.source_samples.sample_for_config(config, now)

    async def _sync_data_quality_repairs(
        self: Self,
        circuit_id: str,
        sample_or_problem: NormalizedCircuitSample | str,
    ) -> None:
        await self.setup_health.async_sync_data_quality_repairs(
            circuit_id,
            sample_or_problem,
        )

    async def _sync_setup_health_repairs(self: Self, circuit_id: str) -> None:
        await self.setup_health.async_sync_setup_health_repairs(circuit_id)

    def _nilm_signature_payloads(
        self: Self,
        circuit_id: str,
        signatures: Iterable[Any],
    ) -> list[dict[str, Any]]:
        return self.nilm_controller.signature_payloads(circuit_id, signatures)

    def apply_nilm_alert_feedback(
        self: Self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        self.alert_policies.apply_nilm_alert_feedback(alert, action, now)

    def _mark_store_dirty(self: Self) -> None:
        self.store_persistence.mark_dirty()

    @property
    def _store_dirty(self: Self) -> bool:
        return self.store_persistence.dirty

    @_store_dirty.setter
    def _store_dirty(self: Self, value: bool) -> None:
        self.store_persistence.dirty = bool(value)

    @property
    def _active_repair_issues(self: Self) -> set[tuple[str, str]]:
        return self.setup_health.active_repair_issues

    async def async_apply_feature_result(
        self: Self,
        result: FeatureResult,
    ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
        """Apply processor output to coordinator-owned state and side effects."""
        applied = self.state_reducer.apply_feature_result(
            self.state,
            self.store_data,
            result,
            alert_feedback=self.evidence_actions.alert_with_feedback,
        )
        for alert in applied.notifications:
            await self._notify_alert(alert)
        if applied.store_dirty:
            self._mark_store_dirty()
        return applied.events, applied.active_alerts

    async def _async_save_store(
        self: Self,
        now: datetime,
        *,
        force: bool = True,
    ) -> None:
        await self.store_persistence.async_save_if_dirty(now, force=force)

    def _apply_retention(self: Self, now: datetime) -> None:
        self.store_persistence.apply_retention(now)

    def _retention_mode_for_circuit(self: Self, circuit_id: str) -> RetentionMode:
        for config in self.circuit_configs:
            if config.circuit_id == circuit_id:
                return config.retention_mode
        return self._entry_retention_mode

    def _source_states_for(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, SourceState]:
        return self.source_samples.source_states_for(config, now)

    def _registered_demo_source_entity_ids(self: Self) -> dict[str, str]:
        return self.source_samples.registered_demo_source_entity_ids()


    def _clear_nilm_topology_state(self: Self, circuit_id: str) -> None:
        self.processor_runtime.clear_nilm_topology_state(circuit_id)

    def _learning_mature(self: Self, config: CircuitConfig, now: datetime) -> bool:
        return self.processor_runtime.learning_mature(config, now)

    async def _notify_alert(self: Self, alert: AlertEvidence) -> None:
        await self.notification_controller.async_notify_alert(alert)

    async def _notify_nilm_virtual_appliances(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        return await self.notification_controller.async_notify_nilm_virtual_appliances(
            now
        )
