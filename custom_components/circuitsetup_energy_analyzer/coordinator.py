from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from . import notifications as notifications  # noqa: F401 - compatibility for tests
from . import repairs as repairs  # noqa: F401 - compatibility for test monkeypatching
from .activity_alerts import ActivityAlertSettings
from .activity_timeline import (
    DEFAULT_TIMELINE_WINDOW_HOURS,
)
from .alert_feedback import (
    alert_feedback_is_expired as _alert_feedback_is_expired,
)
from .alerting import alert_anomaly_score
from .appliance_detail import appliance_detail_for_circuit
from .billing import (
    BillingCycleSettings,
)
from .capacity import (
    CapacitySettings,
)
from .const import (
    CONF_CIRCUITS,
    CONF_DASHBOARD_LAYOUT,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SOURCE_ENTITIES,
    DEFAULT_DASHBOARD_LAYOUT,
    DEFAULT_RETENTION_MODE,
    DOMAIN,
)
from .context_sources import (
    string_list_from_sources as _string_list_from_sources,
)
from .cost import CostSettings
from .dashboard import normalize_dashboard_layout
from .demand import (
    DemandSettings,
)
from .events import CircuitEventDetector
from .exporting import build_circuit_history_csv
from .goals import EnergyGoalSettings
from .local_time import local_date
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
from .managers.source_samples import (
    entity_id_leg_hint as _entity_id_leg_hint,
)
from .managers.source_samples import (
    normalized_leg as _normalized_leg,
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
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    PowerFlowMode,
    RetentionMode,
    SensorRef,
    SensorRole,
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
from .settings_advisor import (
    RecommendationStatus,
    SettingRecommendation,
)
from .standby import StandbySettings
from .storage import (
    RETENTION_WINDOWS,
    FeatureStoreData,
    prune_contextual_baseline_state,
)
from .usage import EnergyUsageSettings
from .utility_comparison import (
    UtilityComparisonSettings,
)
from .ux import (
    canonicalize_sensitivity_config,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS = 0.5
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
RECOMMENDATION_HISTORY_MAX_ITEMS = 200
RECOMMENDATION_HISTORY_MAX_AGE = timedelta(days=180)
RECOMMENDATION_DECISIONS_MAX_ITEMS = 500
RECOMMENDATION_DECISIONS_MAX_AGE = timedelta(days=365)
RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS = 100
RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION = "sha256:v1"
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


def _compact_settings_recommendation_episode_key(
    episode_key: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Return a bounded duplicate-suppression key for pending recommendations."""
    if len(episode_key) <= RECOMMENDATION_NOTIFICATION_EPISODE_MAX_ITEMS:
        return episode_key
    fingerprint = hashlib.sha256(repr(episode_key).encode("utf-8")).hexdigest()
    return (
        ("version", RECOMMENDATION_NOTIFICATION_EPISODE_FINGERPRINT_VERSION),
        ("pending_count", str(len(episode_key))),
        ("fingerprint", fingerprint),
    )


def _apply_state_update(state: Any, path: tuple[str, ...], value: Any) -> None:
    """Apply a processor-requested update to AnalyzerState."""
    apply_state_update(state, path, value)


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
            clean_string_list=_clean_string_list,
            append_unique=_append_unique,
            nonnegative_float_value=_nonnegative_float_value,
            label_interval_datetime=_nilm_label_interval_datetime,
            label_interval_id=_nilm_label_interval_id,
            signature_fingerprint_value=_nilm_signature_fingerprint_value,
            signature_assignment_label=_nilm_signature_assignment_label,
            label_interval_max_items=NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT,
            round_optional_number=_round_optional_number,
            assignment_interval_matches=_nilm_assignment_interval_matches,
            overlap_seconds=_nilm_overlap_seconds,
            validation_coverage_overlap_seconds=(
                _nilm_validation_coverage_overlap_seconds
            ),
            float_or_none=_float_or_none,
            datetime_or_none=_datetime_or_none,
            assignment_appliance_id=_nilm_assignment_appliance_id,
            assignment_id=_nilm_assignment_id,
            assignment_max_items=NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT,
        )
        self.settings_controller = SettingsController(self)
        self.alert_policies = AlertPolicyManager(self)
        self.processor_runtime = ProcessorRuntimeManager(self)
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
                lambda config, match, _context: [
                    alert
                    for alert in [
                        self.nilm_controller.observe_known_load_topology(config, match)
                    ]
                    if alert is not None
                ]
            ),
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
            newest_mapping_items=_newest_mapping_items,
            mapping_time=_mapping_time,
            retention_mode_for_circuit=self._retention_mode_for_circuit,
            retention_window_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
                self._retention_mode_for_circuit(circuit_id)
            ],
            ha_local_date=_ha_local_date,
            ha_time_zone=self.context_builder.time_zone,
            sample_timestamp_is_at_or_after=_sample_timestamp_is_at_or_after,
            contextual_baseline_pruner=prune_contextual_baseline_state,
            weather_context_history_max_samples=WEATHER_CONTEXT_HISTORY_MAX_SAMPLES,
            water_context_history_max_samples=WATER_CONTEXT_HISTORY_MAX_SAMPLES,
            alert_history_max_age=ALERT_HISTORY_MAX_AGE,
            alert_history_max_items=ALERT_HISTORY_MAX_ITEMS,
            alert_feedback_is_expired=_alert_feedback_is_expired,
            alert_feedback_max_age=ALERT_FEEDBACK_MAX_AGE,
            alert_feedback_max_items=ALERT_FEEDBACK_MAX_ITEMS,
            nilm_signatures_max_items=NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT,
            nilm_unknown_loads_max_items=NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT,
            nilm_session_history_max_age=NILM_SESSION_HISTORY_MAX_AGE,
            nilm_session_history_max_items=NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
            recommendation_pending_status=RecommendationStatus.PENDING,
            recommendation_sort_key=_recommendation_sort_key,
            recommendation_history_max_age=RECOMMENDATION_HISTORY_MAX_AGE,
            recommendation_history_max_items=RECOMMENDATION_HISTORY_MAX_ITEMS,
            recommendation_decisions_max_age=RECOMMENDATION_DECISIONS_MAX_AGE,
            recommendation_decisions_max_items=RECOMMENDATION_DECISIONS_MAX_ITEMS,
            compact_settings_recommendation_episode_key=(
                _compact_settings_recommendation_episode_key
            ),
        )
        self.notification_controller = NotificationController(
            self,
            compact_settings_recommendation_episode_key=(
                _compact_settings_recommendation_episode_key
            ),
            material_evidence_key=material_recommendation_evidence_key,
        )
        self.setup_health = SetupHealthAggregator(self)
        self.paused_circuits: set[str] = set()
        self.last_exported_diagnostics: dict[str, Any] = {}
        self.last_exported_history_csv: str = ""
        self.mapping_checks_run = 0
        self.state = AnalyzerState()
        self.started = False
        self.source_updates = SourceUpdateManager(
            self,
            track_state_change_event=async_track_state_change_event,
            debounce_seconds=SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS,
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

    def refresh_energy_goal_state(
        self: Self,
        circuit_id: str,
        config: CircuitConfig,
        context: Any,
    ) -> FeatureResult:
        """Refresh daily energy-goal state through the configured processor."""
        return self._energy_goal_processor.refresh_state(circuit_id, config, context)

    async def async_process_update(self: Self) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        context = self.context_builder.build(now)
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []
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
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            new_events, new_alerts = await self.pipeline.async_process_circuit(
                config,
                sample,
                context,
            )
            events.extend(new_events)
            alerts.extend(new_alerts)

        for config, sample in samples:
            for nilm_alert in self.nilm_controller.process_sample(
                config,
                sample,
                events,
            ):
                nilm_alert = self.evidence_actions.alert_with_feedback(nilm_alert)
                if nilm_alert.feedback_status != "expected":
                    alerts.append(nilm_alert)
                self.store_data.alerts.append(nilm_alert)
                self._mark_store_dirty()
                await self._notify_alert(nilm_alert)
        alerts.extend(await self._notify_nilm_virtual_appliances(now))
        alerts.extend(await self.pipeline.async_process_cross_circuit(samples, now))

        process_events_into_state(self.state, events, alerts)
        for config, sample in samples:
            self._refresh_ux_state(config, sample, now)
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
        if self._rebuild_setting_recommendations(now):
            self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)
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
        appliance_detail = appliance_detail_for_circuit(self, circuit_id)
        self.last_exported_diagnostics = {
            "circuit_id": circuit_id,
            "appliance_detail": (
                appliance_detail.as_dict() if appliance_detail is not None else None
            ),
            "anomaly_score": self.state.anomaly_score_by_circuit.get(circuit_id, 0.0),
            "data_quality": self.state.data_quality_by_circuit.get(circuit_id),
            "learning": self.state.learning_by_circuit.get(circuit_id, True),
            "power_quality_score": self.state.power_quality_score_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "power_quality_evidence": self.state.power_quality_evidence_by_circuit.get(
                circuit_id,
                "",
            ),
            "reactive_power_drift": self.state.reactive_power_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "apparent_power_drift": self.state.apparent_power_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "power_factor_drift": self.state.power_factor_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "health_status": self.state.health_status_by_circuit.get(circuit_id),
            "health_summary": self.state.health_summary_by_circuit.get(circuit_id),
            "readiness": self.state.readiness_by_circuit.get(circuit_id, {}),
            "learning_progress": self.state.learning_progress_by_circuit.get(
                circuit_id,
                {},
            ),
            "data_quality_checklist": self.state.data_quality_checklist_by_circuit.get(
                circuit_id,
                {},
            ),
            "alert_evidence": self.state.alert_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "sensitivity": self.state.sensitivity_by_circuit.get(circuit_id),
            "maintenance": self.state.maintenance_by_circuit.get(circuit_id, {}),
            "nilm_review": self.state.nilm_review_by_circuit.get(circuit_id, []),
            "daily_energy_usage_kwh": self.state.daily_energy_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "energy_usage_share_percent": self.state.energy_usage_share_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "energy_usage_evidence": self.state.energy_usage_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "energy_goal_usage_percent": (
                self.state.energy_goal_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "energy_goal_status": self.state.energy_goal_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "energy_goal_evidence": self.state.energy_goal_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "run_cycle_count": self.state.run_cycle_count_by_circuit.get(
                circuit_id,
                0,
            ),
            "run_cycle_runtime_seconds": (
                self.state.run_cycle_runtime_seconds_by_circuit.get(circuit_id, 0.0)
            ),
            "run_cycle_duty_cycle_percent": (
                self.state.run_cycle_duty_cycle_by_circuit.get(circuit_id, 0.0)
            ),
            "run_cycle_status": self.state.run_cycle_status_by_circuit.get(
                circuit_id,
                "no_activity",
            ),
            "run_cycle_evidence": self.state.run_cycle_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "billing_cycle_usage_kwh": (
                self.state.billing_cycle_usage_kwh_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_forecast_kwh": (
                self.state.billing_cycle_forecast_kwh_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_budget_usage_percent": (
                self.state.billing_cycle_budget_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_status": self.state.billing_cycle_status_by_circuit.get(
                circuit_id,
                "no_budget",
            ),
            "billing_cycle_evidence": (
                self.state.billing_cycle_evidence_by_circuit.get(circuit_id, {})
            ),
            "cost_current_rate_per_kwh": self.state.cost_current_rate_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "cost_cycle": self.state.cost_cycle_by_circuit.get(circuit_id, 0.0),
            "cost_cycle_forecast": self.state.cost_cycle_forecast_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "cost_status": self.state.cost_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "cost_evidence": self.state.cost_evidence_by_circuit.get(circuit_id, {}),
            "current_demand_w": self.state.current_demand_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "peak_demand_w": self.state.peak_demand_w_by_circuit.get(circuit_id, 0.0),
            "demand_limit_usage_percent": (
                self.state.demand_limit_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "demand_evidence": self.state.demand_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "capacity_usage_percent": self.state.capacity_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "capacity_status": self.state.capacity_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "capacity_evidence": self.state.capacity_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "utility_comparison_difference_kwh": (
                self.state.utility_comparison_difference_kwh_by_circuit.get(
                    circuit_id,
                    0.0,
                )
            ),
            "utility_comparison_difference_percent": (
                self.state.utility_comparison_difference_percent_by_circuit.get(
                    circuit_id,
                    0.0,
                )
            ),
            "utility_comparison_status": (
                self.state.utility_comparison_status_by_circuit.get(
                    circuit_id,
                    "unconfigured",
                )
            ),
            "utility_comparison_evidence": (
                self.state.utility_comparison_evidence_by_circuit.get(
                    circuit_id,
                    {},
                )
            ),
            "always_on_power_w": self.state.always_on_power_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "standby_threshold_w": self.state.standby_threshold_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "standby_status": self.state.standby_status_by_circuit.get(
                circuit_id,
                "learning",
            ),
            "always_on_limit_usage_percent": (
                self.state.always_on_limit_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "standby_evidence": self.state.standby_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
        }
        self.async_set_updated_data(self.state)

    async def async_export_history_csv(self: Self, circuit_id: str) -> None:
        """Store retained analyzer history for one circuit as CSV text."""
        self.last_exported_history_csv = build_circuit_history_csv(
            self.store_data,
            circuit_id,
        )
        self.async_set_updated_data(self.state)

    async def async_run_mapping_checks(self: Self) -> None:
        """Run lightweight source mapping checks."""
        self.mapping_checks_run += 1
        for config in self.circuit_configs:
            if not config.sensors:
                self.state.data_quality_by_circuit[config.circuit_id] = (
                    "missing_required_sensor"
                )
                await self._sync_data_quality_repairs(
                    config.circuit_id,
                    "missing_required_sensor",
                )
            self._refresh_ux_state(config, None, self._now_fn())
        self.async_set_updated_data(self.state)

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
    ) -> None:
        self.ux_state.refresh_config(config, sample, now)

    def _suppression_reason(self: Self, circuit_id: str, learning: bool) -> str | None:
        return self.ux_state.suppression_reason(circuit_id, learning)

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

    async def _async_save_store(self: Self, now: datetime) -> None:
        await self.store_persistence.async_save_if_dirty(now)

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


    def _activity_alert_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> ActivityAlertSettings:
        return self.processor_runtime.activity_alert_settings_for_config(
            config,
            circuit_id,
        )

    def _energy_usage_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyUsageSettings:
        return self.processor_runtime.energy_usage_settings_for_config(
            config,
            circuit_id,
        )

    def _energy_goal_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyGoalSettings:
        return self.processor_runtime.energy_goal_settings_for_config(
            config,
            circuit_id,
        )

    def _billing_cycle_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> BillingCycleSettings:
        return self.processor_runtime.billing_cycle_settings_for_config(
            config,
            circuit_id,
        )

    def _cost_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> CostSettings:
        return self.processor_runtime.cost_settings_for_config(
            config,
            circuit_id,
        )

    def _demand_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> DemandSettings:
        return self.processor_runtime.demand_settings_for_config(
            config,
            circuit_id,
        )

    def _capacity_settings_for_config(self: Self, circuit_id: str) -> CapacitySettings:
        return self.processor_runtime.capacity_settings_for_config(circuit_id)

    def _standby_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> StandbySettings:
        return self.processor_runtime.standby_settings_for_config(
            config,
            circuit_id,
        )

    def _utility_comparison_settings_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> UtilityComparisonSettings:
        return self.processor_runtime.utility_comparison_settings_for_circuit(
            circuit_id
        )

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


def _numeric_items(
    raw_items: Any,
    *,
    keys: tuple[str, ...] = (),
) -> list[float]:
    if raw_items is None:
        return []
    try:
        items = list(raw_items)
    except TypeError:
        items = [raw_items]

    values: list[float] = []
    for item in items:
        if keys and isinstance(item, Mapping):
            for key in keys:
                if key in item:
                    _append_float(values, item.get(key))
                    break
            continue
        _append_float(values, item)
    return values


def _coerce_timestamped_dicts(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    return [
        dict(item)
        for item in raw_items
        if isinstance(item, Mapping)
        and _datetime_or_none(item.get("timestamp")) is not None
    ]


def _append_float(values: list[float], raw_value: Any) -> None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return
    values.append(value)


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_amps(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _ha_local_date(value: datetime, time_zone: str | None) -> Any:
    if time_zone is None or value.tzinfo is None:
        return value.date()
    return local_date(value, time_zone)


def _water_context_history_sample_is_dry(sample: Mapping[str, Any]) -> bool:
    raw_issues = sample.get("rain_context_issues")
    if isinstance(raw_issues, str) and raw_issues.strip():
        return False
    if isinstance(raw_issues, (list, tuple, set)) and raw_issues:
        return False
    intensity = _float_or_none(sample.get("rain_intensity_mm_per_hour"))
    if intensity is not None and intensity > 0.0:
        return False
    rain_state = str(sample.get("rain_state") or "").strip().lower()
    if rain_state:
        return rain_state == "dry"
    return sample.get("rain_active") is False


def _datetime_floor() -> datetime:
    return datetime.min.replace(tzinfo=UTC)


def _mapping_time(item: Any, *keys: str) -> datetime:
    if not isinstance(item, Mapping):
        return _datetime_floor()
    for key in keys or ("last_seen", "timestamp", "created_at", "first_seen"):
        parsed = _datetime_or_none(item.get(key))
        if parsed is not None:
            return parsed
    return _datetime_floor()


def _newest_mapping_items(items: Any, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    mapped_items = [dict(item) for item in items if isinstance(item, Mapping)]
    return sorted(mapped_items, key=_mapping_time, reverse=True)[:max_items]


def _recommendation_sort_key(
    recommendation: SettingRecommendation,
) -> tuple[bool, datetime]:
    return (
        recommendation.status is RecommendationStatus.PENDING,
        max(recommendation.created_at, recommendation.expires_at),
    )


def _sample_timestamp_is_at_or_after(sample: Any, cutoff: datetime) -> bool:
    if not isinstance(sample, dict):
        return False
    sample_time = _datetime_or_none(sample.get("timestamp"))
    return sample_time is not None and sample_time >= cutoff


def _weather_context_mode(config: CircuitConfig) -> str:
    if config.appliance_profile is ApplianceProfile.ELECTRIC_HEAT:
        return "heating"
    return "cooling"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_number(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return round(parsed, 3)


def _round_optional_number(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return round(parsed, 3)


def _retention_mode_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> RetentionMode:
    options = options or {}
    raw = options.get(
        CONF_RETENTION_MODE,
        entry_data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
    )
    try:
        return RetentionMode(str(raw))
    except ValueError:
        return RetentionMode.STANDARD


def _circuit_configs_from_entry_data(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[CircuitConfig, ...]:
    configs: list[CircuitConfig] = []
    options = options or {}
    default_retention_mode = _retention_mode_from_sources(entry_data, options)
    raw_circuits = (
        options[CONF_CIRCUITS]
        if CONF_CIRCUITS in options
        else entry_data.get(CONF_CIRCUITS, [])
    )
    for raw_circuit in raw_circuits:
        config = _circuit_config_from_raw(raw_circuit, default_retention_mode)
        if config is not None:
            configs.append(config)

    configs = _configs_with_merged_source_entity_refs(
        entry_data,
        options,
        configs,
    )
    configs.extend(
        _source_entity_configs_from_sources(
            entry_data,
            options,
            default_retention_mode,
            configs,
        )
    )

    if (
        _experimental_nilm_enabled(entry_data, options)
        and not any(config.mode is CircuitMode.MAINS_NILM for config in configs)
    ):
        mains_config = _mains_nilm_config_from_sources(entry_data, options)
        if mains_config is not None:
            configs.append(mains_config)
    return tuple(configs)


def _configs_with_merged_source_entity_refs(
    entry_data: dict[str, Any],
    options: dict[str, Any],
    existing_configs: Iterable[CircuitConfig],
) -> list[CircuitConfig]:
    configs = list(existing_configs)
    if not configs:
        return configs

    source_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_SOURCE_ENTITIES,
    )
    if not source_entities:
        return configs

    mains_entities = set(
        _string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
    config_index = _config_index_by_source_circuit_id(configs)
    existing_source_entities = {
        sensor.entity_id for config in configs for sensor in config.sensors
    }
    for entity_id in source_entities:
        if entity_id in mains_entities or entity_id in existing_source_entities:
            continue
        config_index_value = config_index.get(
            _source_circuit_id_from_entity_id(entity_id)
        )
        if config_index_value is None:
            continue
        config = configs[config_index_value]
        configs[config_index_value] = replace(
            config,
            sensors=(
                *config.sensors,
                SensorRef(
                    entity_id=entity_id,
                    role=_sensor_role_from_entity_id(entity_id),
                    leg=_entity_id_leg_hint(entity_id),
                ),
            ),
        )
        existing_source_entities.add(entity_id)
    return configs


def _config_index_by_source_circuit_id(
    configs: Iterable[CircuitConfig],
) -> dict[str, int]:
    config_index: dict[str, int] = {}
    for index, config in enumerate(configs):
        for value in (config.circuit_id, config.name):
            circuit_id = _canonical_source_circuit_id(value)
            if circuit_id:
                config_index.setdefault(circuit_id, index)
    return config_index


def _source_entity_configs_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    retention_mode: RetentionMode,
    existing_configs: Iterable[CircuitConfig],
) -> tuple[CircuitConfig, ...]:
    source_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_SOURCE_ENTITIES,
    )
    if not source_entities:
        return ()

    mains_entities = set(
        _string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
    shared_voltage_refs = _shared_voltage_refs(source_entities, mains_entities)
    existing_circuit_ids = {config.circuit_id for config in existing_configs}
    existing_source_entities = {
        sensor.entity_id
        for config in existing_configs
        for sensor in config.sensors
    }
    sensors_by_circuit_id: dict[str, list[SensorRef]] = {}
    for entity_id in source_entities:
        if entity_id in mains_entities or entity_id in existing_source_entities:
            continue
        circuit_id = _source_circuit_id_from_entity_id(entity_id)
        if not circuit_id or circuit_id in existing_circuit_ids:
            continue
        sensors_by_circuit_id.setdefault(circuit_id, []).append(
            SensorRef(
                entity_id=entity_id,
                role=_sensor_role_from_entity_id(entity_id),
                leg=_entity_id_leg_hint(entity_id),
            )
        )

    configs: list[CircuitConfig] = []
    for circuit_id, sensors in sensors_by_circuit_id.items():
        appliance_profile, mode = _appliance_profile_mode_from_circuit_id(circuit_id)
        sensors_with_voltage = _with_shared_voltage_context(
            tuple(sensors),
            mode,
            shared_voltage_refs,
        )
        configs.append(
            CircuitConfig(
                circuit_id=circuit_id,
                name=_friendly_name_from_circuit_id(circuit_id),
                appliance_profile=appliance_profile,
                mode=mode,
                sensors=sensors_with_voltage,
                retention_mode=retention_mode,
            )
        )
    return tuple(configs)


def _experimental_nilm_enabled(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> bool:
    options = options or {}
    return bool(
        options.get(
            CONF_ENABLE_EXPERIMENTAL_NILM,
            entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
        )
    )


def _mains_nilm_config_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> CircuitConfig | None:
    mains_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_MAINS_SOURCE_ENTITIES,
    )
    if not mains_entities:
        return None

    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=tuple(
            SensorRef(
                entity_id=entity_id,
                role=_sensor_role_from_entity_id(entity_id),
                leg=_entity_id_leg_hint(entity_id),
            )
            for entity_id in mains_entities
        ),
        retention_mode=_retention_mode_from_sources(entry_data, options),
        power_flow=PowerFlowMode.MAINS_NET,
    )


def _circuit_config_from_raw(
    raw_circuit: Any,
    default_retention_mode: RetentionMode = RetentionMode.STANDARD,
) -> CircuitConfig | None:
    if isinstance(raw_circuit, CircuitConfig):
        return raw_circuit
    if not isinstance(raw_circuit, dict):
        return None

    circuit_id = raw_circuit.get("circuit_id") or raw_circuit.get("id")
    if not circuit_id:
        return None

    try:
        appliance_profile = _appliance_profile_from_raw_value(
            raw_circuit.get("appliance_profile", ApplianceProfile.MIXED.value)
        )
        mode = CircuitMode(raw_circuit.get("mode", CircuitMode.MIXED.value))
        retention_mode = RetentionMode(
            raw_circuit.get("retention_mode", default_retention_mode.value)
        )
    except ValueError:
        return None

    return CircuitConfig(
        circuit_id=str(circuit_id),
        name=str(raw_circuit.get("name") or circuit_id),
        appliance_profile=appliance_profile,
        mode=mode,
        sensors=_sensor_refs_from_raw(raw_circuit),
        retention_mode=retention_mode,
        power_flow=_power_flow_mode_from_raw(raw_circuit, appliance_profile, mode),
        energy_usage_window_days=_positive_int_from_raw(
            raw_circuit,
            "energy_usage_window_days",
            "usage_window_days",
            default=7,
        ),
        daily_energy_spike_ratio=_positive_float_from_raw(
            raw_circuit,
            "daily_energy_spike_ratio",
            "usage_spike_ratio",
            default=0.25,
        ),
        daily_energy_goal_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "daily_energy_goal_kwh",
            "daily_goal_kwh",
        ),
        energy_goal_alert_ratio=_positive_float_from_raw(
            raw_circuit,
            "energy_goal_alert_ratio",
            "goal_alert_ratio",
            default=1.0,
        ),
        billing_cycle_start_day=_positive_int_from_raw(
            raw_circuit,
            "billing_cycle_start_day",
            "cycle_start_day",
            default=1,
        ),
        billing_cycle_budget_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "billing_cycle_budget_kwh",
            "budget_kwh",
        ),
        billing_cycle_budget_alert_ratio=_positive_float_from_raw(
            raw_circuit,
            "billing_cycle_budget_alert_ratio",
            "budget_alert_ratio",
            default=1.0,
        ),
        billing_cycle_min_elapsed_days=_positive_int_from_raw(
            raw_circuit,
            "billing_cycle_min_elapsed_days",
            default=3,
        ),
        cost_cycle_start_day=_positive_int_from_raw(
            raw_circuit,
            "cost_cycle_start_day",
            "cycle_start_day",
            default=1,
        ),
        default_rate_per_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "default_rate_per_kwh",
            "cost_default_rate_per_kwh",
        ),
        tou_rate_per_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "tou_rate_per_kwh",
            "cost_tou_rate_per_kwh",
        ),
        tou_start=_optional_string_from_raw(raw_circuit, "tou_start", "cost_tou_start"),
        tou_end=_optional_string_from_raw(raw_circuit, "tou_end", "cost_tou_end"),
        tou_weekdays=_weekday_tuple_value(raw_circuit.get("tou_weekdays")),
        tou_name=str(raw_circuit.get("tou_name") or "Peak"),
        demand_window_minutes=_positive_int_from_raw(
            raw_circuit,
            "demand_window_minutes",
            "demand_window",
            default=15,
        ),
        demand_limit_w=_optional_positive_float_from_raw(
            raw_circuit,
            "demand_limit_w",
            "demand_limit",
        ),
        standby_window_hours=_positive_int_from_raw(
            raw_circuit,
            "standby_window_hours",
            "standby_window",
            default=48,
        ),
        standby_threshold_w=_positive_float_from_raw(
            raw_circuit,
            "standby_threshold_w",
            "standby_threshold",
            default=8.0,
        ),
        always_on_alert_w=_optional_positive_float_from_raw(
            raw_circuit,
            "always_on_alert_w",
            "always_on_limit_w",
        ),
        standby_min_samples=_positive_int_from_raw(
            raw_circuit,
            "standby_min_samples",
            default=24,
        ),
    )


def _appliance_profile_from_raw_value(value: Any) -> ApplianceProfile:
    normalized = str(value or ApplianceProfile.MIXED.value).strip().lower()
    aliases = {
        "hvac_system": ApplianceProfile.HVAC.value,
        "ac": ApplianceProfile.HVAC_COMPRESSOR.value,
        "a_c": ApplianceProfile.HVAC_COMPRESSOR.value,
        "ac_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "a_c_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "air_conditioner": ApplianceProfile.HVAC_COMPRESSOR.value,
        "compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "heat_pump": ApplianceProfile.HVAC_COMPRESSOR.value,
        "air_handler": ApplianceProfile.HVAC_BLOWER.value,
        "hvac_air_handler": ApplianceProfile.HVAC_BLOWER.value,
        "blower": ApplianceProfile.HVAC_BLOWER.value,
        "aux_heat": ApplianceProfile.ELECTRIC_HEAT.value,
        "electric_aux_heat": ApplianceProfile.ELECTRIC_HEAT.value,
        "heat_strip": ApplianceProfile.ELECTRIC_HEAT.value,
        "well_pump": ApplianceProfile.WATER_PUMP.value,
        "booster_pump": ApplianceProfile.WATER_PUMP.value,
        "car_charger": ApplianceProfile.EV_CHARGER.value,
        "vehicle_charger": ApplianceProfile.EV_CHARGER.value,
        "vehicle_charging": ApplianceProfile.EV_CHARGER.value,
        "level2_charger": ApplianceProfile.EV_CHARGER.value,
        "level_2_charger": ApplianceProfile.EV_CHARGER.value,
        "wall_connector": ApplianceProfile.EV_CHARGER.value,
        "microwave_oven": ApplianceProfile.MICROWAVE.value,
        "kitchen_microwave": ApplianceProfile.MICROWAVE.value,
    }
    normalized = aliases.get(normalized, normalized)
    return ApplianceProfile(normalized)


def _power_flow_mode_from_raw(
    raw_circuit: dict[str, Any],
    appliance_profile: ApplianceProfile,
    mode: CircuitMode,
) -> PowerFlowMode:
    raw_power_flow = raw_circuit.get("power_flow")
    if raw_power_flow is not None:
        value = str(raw_power_flow).strip().lower()
        if value == "bidirectional":
            return PowerFlowMode.MAINS_NET
        try:
            return PowerFlowMode(value)
        except ValueError:
            return PowerFlowMode.LOAD
    if (
        appliance_profile is ApplianceProfile.MAINS_NILM
        or mode is CircuitMode.MAINS_NILM
    ):
        return PowerFlowMode.MAINS_NET
    if appliance_profile is ApplianceProfile.SOLAR_INVERTER:
        return PowerFlowMode.GENERATION
    return PowerFlowMode.LOAD


def _sensor_refs_from_raw(raw_circuit: dict[str, Any]) -> tuple[SensorRef, ...]:
    raw_sensors = raw_circuit.get("sensors")
    if raw_sensors is None:
        raw_sensors = raw_circuit.get("source_entities", [])

    refs: list[SensorRef] = []
    for raw_sensor in raw_sensors:
        ref = _sensor_ref_from_raw(raw_sensor)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _nilm_label_interval_datetime(value: Any, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as err:
        raise ValueError(f"Invalid NILM label interval {field_name}.") from err
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _nilm_label_interval_id(
    circuit_id: str,
    start: str,
    end: str,
    label: str,
) -> str:
    seed = f"{circuit_id}|{start}|{end}|{label}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"label-{digest}"


def _nilm_signature_fingerprint_value(
    signature: Mapping[str, Any],
    fallback: str,
) -> str:
    return str(
        signature.get("feedback_fingerprint")
        or signature.get("signature_fingerprint")
        or signature.get("signature_id")
        or fallback
    ).strip()


def _nilm_signature_assignment_label(
    signature: Mapping[str, Any],
    fallback: str,
) -> str:
    return (
        str(signature.get("user_label") or "").strip()
        or str(signature.get("display_name") or "").strip()
        or str(signature.get("likely_type") or "").strip()
        or fallback
    )


def _nilm_assignment_interval_matches(
    interval: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    interval_id = str(interval.get("interval_id") or "").strip()
    if interval_id and interval_id in _clean_string_list(
        assignment.get("label_interval_ids")
    ):
        return True
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if (
        assignment_id
        and str(interval.get("assignment_id") or "").strip() == assignment_id
    ):
        return True
    interval_appliance = str(
        interval.get("appliance_id") or interval.get("label") or ""
    ).strip().casefold()
    if not interval_appliance:
        return False
    return interval_appliance in {
        str(assignment.get("appliance_id") or "").strip().casefold(),
        str(assignment.get("display_name") or "").strip().casefold(),
    }


def _nilm_overlap_seconds(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    first_start = _datetime_or_none(first.get("start"))
    first_end = _datetime_or_none(first.get("end"))
    second_start = _datetime_or_none(second.get("start"))
    second_end = _datetime_or_none(second.get("end"))
    if not all((first_start, first_end, second_start, second_end)):
        return 0.0
    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def _nilm_validation_coverage_overlap_seconds(
    interval: Mapping[str, Any],
    session: Mapping[str, Any],
) -> float:
    validation_start = interval.get("validation_start")
    validation_end = interval.get("validation_end")
    if not validation_start or not validation_end:
        return 0.0
    return _nilm_overlap_seconds(
        {"start": validation_start, "end": validation_end},
        session,
    )


def _nilm_assignment_appliance_id(label: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() else "_"
        for character in str(label or "").strip()
    ).strip("_")
    return "_".join(part for part in slug.split("_") if part)[:64] or "nilm"


def _nilm_assignment_id(circuit_id: str, appliance_id: str) -> str:
    seed = f"{circuit_id}|{appliance_id}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"assignment-{digest}"


def _append_unique(values: Any, value: Any) -> None:
    text = str(value or "").strip()
    if not text or text in values:
        return
    values.append(text)


def _clean_string_list(values: Any) -> list[str]:
    if isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    cleaned: list[str] = []
    for value in iterator:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _positive_int_from_raw(
    raw: dict[str, Any],
    *keys: str,
    default: int,
) -> int:
    for key in keys:
        if key not in raw:
            continue
        try:
            value = int(raw[key])
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _positive_int_value(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float_from_raw(
    raw: dict[str, Any],
    *keys: str,
    default: float,
) -> float:
    for key in keys:
        if key not in raw:
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return default


def _optional_positive_float_from_raw(
    raw: dict[str, Any],
    *keys: str,
) -> float | None:
    for key in keys:
        if key not in raw:
            continue
        value = _optional_positive_float_value(raw[key], default=None)
        if value is not None:
            return value
    return None


def _optional_string_from_raw(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _positive_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


def _entity_id_tuple_value(
    value: Any,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    return tuple(str(item).strip() for item in raw_items if str(item).strip())


def _weekday_tuple_value(
    value: Any,
    *,
    default: tuple[int, ...] = (),
) -> tuple[int, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    weekdays: list[int] = []
    for item in raw_items:
        try:
            weekday = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= weekday <= 6 and weekday not in weekdays:
            weekdays.append(weekday)
    return tuple(weekdays) if weekdays else default


def _weekday_csv_value(value: Any, *, default: tuple[int, ...] = ()) -> str:
    return ",".join(str(day) for day in _weekday_tuple_value(value, default=default))


def _event_entity_id(event: Any) -> str:
    """Extract a Home Assistant state-change entity id from an event-like object."""
    data = getattr(event, "data", {})
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("entity_id") or "").strip()


def _optional_positive_float_value(
    value: Any,
    *,
    default: float | None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _sensor_ref_from_raw(raw_sensor: Any) -> SensorRef | None:
    if isinstance(raw_sensor, SensorRef):
        return raw_sensor
    if isinstance(raw_sensor, str):
        return SensorRef(
            entity_id=raw_sensor,
            role=_sensor_role_from_entity_id(raw_sensor),
            leg=_entity_id_leg_hint(raw_sensor),
        )
    if not isinstance(raw_sensor, dict):
        return None

    entity_id = raw_sensor.get("entity_id")
    if not entity_id:
        return None
    try:
        role = SensorRole(raw_sensor.get("role", SensorRole.REAL_POWER.value))
    except ValueError:
        return None
    return SensorRef(
        entity_id=str(entity_id),
        role=role,
        leg=raw_sensor.get("leg"),
        unit=raw_sensor.get("unit"),
    )


_SOURCE_METRIC_SUFFIXES = (
    "_reactive_power",
    "_apparent_power",
    "_power_factor",
    "_line_frequency",
    "_real_power",
    "_active_power",
    "_frequency",
    "_current",
    "_voltage",
    "_energy",
    "_watts",
    "_watt",
    "_amps",
    "_amp",
    "_power",
    "_kwh",
    "_mwh",
    "_wh",
    "_var",
    "_va",
    "_pf",
    "_hz",
)
_SOURCE_LEG_SUFFIXES = (
    "_leg_a",
    "_leg_b",
    "_line_a",
    "_line_b",
    "_phase_a",
    "_phase_b",
    "_leg_1",
    "_leg_2",
    "_line_1",
    "_line_2",
    "_phase_1",
    "_phase_2",
    "_leg1",
    "_leg2",
    "_line1",
    "_line2",
    "_phase1",
    "_phase2",
    "_l1",
    "_l2",
)
_ANALYZER_SOURCE_ENTITY_PREFIXES = (
    "circuitsetup_energy_analyzer_",
    "cs_energy_analyzer_",
)
_PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES = ("cs_energy_analyzer_demo_",)


def _sensor_role_from_entity_id(entity_id: str) -> SensorRole:
    object_id = _entity_object_id(entity_id)
    if _has_metric_suffix(object_id, ("power_factor", "pf")):
        return SensorRole.POWER_FACTOR
    if _has_metric_suffix(object_id, ("reactive_power", "reactive", "var")):
        return SensorRole.REACTIVE_POWER
    if _has_metric_suffix(object_id, ("apparent_power", "apparent", "va")):
        return SensorRole.APPARENT_POWER
    if _has_metric_suffix(object_id, ("frequency", "line_frequency", "hz")):
        return SensorRole.FREQUENCY
    if _has_metric_suffix(object_id, ("current", "amps", "amp", "a")):
        return SensorRole.CURRENT
    if _has_metric_suffix(object_id, ("voltage", "volts", "volt", "v")):
        return SensorRole.VOLTAGE
    if _has_metric_suffix(object_id, ("energy", "kwh", "wh", "mwh")):
        return SensorRole.ENERGY
    return SensorRole.REAL_POWER


def _shared_voltage_refs(
    source_entities: Iterable[str],
    mains_entities: set[str],
) -> tuple[SensorRef, ...]:
    refs: list[SensorRef] = []
    seen_legs: set[str] = set()
    for entity_id in dict.fromkeys([*source_entities, *mains_entities]):
        if _sensor_role_from_entity_id(entity_id) is not SensorRole.VOLTAGE:
            continue
        if entity_id not in mains_entities and not _looks_like_mains_voltage(entity_id):
            continue
        leg = _entity_id_leg_hint(entity_id)
        if leg is None or leg in seen_legs:
            continue
        refs.append(SensorRef(entity_id=entity_id, role=SensorRole.VOLTAGE, leg=leg))
        seen_legs.add(leg)
    return tuple(refs)


def _looks_like_mains_voltage(entity_id: str) -> bool:
    object_id = _entity_object_id(entity_id)
    return any(token in f"_{object_id}_" for token in ("_mains_", "_main_"))


def _with_shared_voltage_context(
    sensors: tuple[SensorRef, ...],
    mode: CircuitMode,
    shared_voltage_refs: tuple[SensorRef, ...],
) -> tuple[SensorRef, ...]:
    if not shared_voltage_refs or any(
        sensor.role is SensorRole.VOLTAGE for sensor in sensors
    ):
        return sensors
    if mode is CircuitMode.DUAL_PHASE:
        return _append_missing_voltage_legs(sensors, shared_voltage_refs, {"a", "b"})
    if mode is CircuitMode.SINGLE_PHASE:
        desired_leg = next(
            (
                leg
                for sensor in sensors
                if (leg := _normalized_leg(sensor.leg)) is not None
            ),
            "a",
        )
        return _append_missing_voltage_legs(sensors, shared_voltage_refs, {desired_leg})
    return sensors


def _append_missing_voltage_legs(
    sensors: tuple[SensorRef, ...],
    shared_voltage_refs: tuple[SensorRef, ...],
    desired_legs: set[str],
) -> tuple[SensorRef, ...]:
    present_legs = {
        leg
        for sensor in sensors
        if sensor.role is SensorRole.VOLTAGE
        and (leg := _normalized_leg(sensor.leg)) is not None
    }
    additions = tuple(
        ref
        for ref in shared_voltage_refs
        if (leg := _normalized_leg(ref.leg)) in desired_legs
        and leg not in present_legs
    )
    return (*sensors, *additions)


def _source_circuit_id_from_entity_id(entity_id: str) -> str:
    object_id = _entity_object_id(entity_id)
    return _canonical_source_circuit_id(
        _strip_trailing_source_detail_tokens(object_id)
    )


def _canonical_source_circuit_id(value: Any) -> str:
    circuit_id = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    for preserved_prefix in _PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(preserved_prefix):
            return circuit_id
    for prefix in _ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(prefix):
            return circuit_id.removeprefix(prefix) or circuit_id
    return circuit_id


def _strip_trailing_source_detail_tokens(object_id: str) -> str:
    stripped = object_id
    while True:
        for suffix in (*_SOURCE_METRIC_SUFFIXES, *_SOURCE_LEG_SUFFIXES):
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        else:
            return stripped or object_id


def _strip_trailing_leg_token(object_id: str) -> str:
    for suffix in _SOURCE_LEG_SUFFIXES:
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _entity_object_id(entity_id: str) -> str:
    return str(entity_id).split(".")[-1].strip().lower()


def _has_metric_suffix(object_id: str, metric_suffixes: Iterable[str]) -> bool:
    normalized = _strip_trailing_leg_token(object_id.strip().lower())
    return any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in metric_suffixes
    )


def _friendly_name_from_circuit_id(circuit_id: str) -> str:
    text = str(circuit_id).removeprefix("cs_energy_analyzer_demo_")
    return text.replace("_", " ").strip().title()


def _appliance_profile_mode_from_circuit_id(
    circuit_id: str,
) -> tuple[ApplianceProfile, CircuitMode]:
    normalized = f"_{str(circuit_id).strip().lower()}_"
    for tokens, profile, mode in (
        (
            ("_refrigerator_", "_fridge_"),
            ApplianceProfile.REFRIGERATOR,
            CircuitMode.SINGLE_PHASE,
        ),
        (("_freezer_",), ApplianceProfile.FREEZER, CircuitMode.SINGLE_PHASE),
        (
            (
                "_ac_compressor_",
                "_a_c_compressor_",
                "_compressor_",
                "_heat_pump_",
                "_air_conditioner_",
                "_ac_",
            ),
            ApplianceProfile.HVAC_COMPRESSOR,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_air_handler_", "_hvac_air_handler_", "_blower_"),
            ApplianceProfile.HVAC_BLOWER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_aux_heat_", "_electric_heat_", "_electric_aux_heat_", "_heat_strip_"),
            ApplianceProfile.ELECTRIC_HEAT,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_hvac_",),
            ApplianceProfile.HVAC,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_water_heater_", "_waterheater_"),
            ApplianceProfile.WATER_HEATER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_microwave_", "_microwave_oven_"),
            ApplianceProfile.MICROWAVE,
            CircuitMode.SINGLE_PHASE,
        ),
        (("_oven_", "_range_"), ApplianceProfile.OVEN, CircuitMode.DUAL_PHASE),
        (
            ("_washer_", "_clothes_washer_", "_laundry_washer_", "_washing_machine_"),
            ApplianceProfile.WASHER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_dryer_", "_clothes_dryer_", "_electric_dryer_", "_gas_dryer_"),
            ApplianceProfile.DRYER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_pool_pump_", "_poolpump_"),
            ApplianceProfile.POOL_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            (
                "_well_pump_",
                "_wellpump_",
                "_water_pump_",
                "_waterpump_",
                "_booster_pump_",
            ),
            ApplianceProfile.WATER_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_sump_pump_", "_sumppump_"),
            ApplianceProfile.SUMP_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            (
                "_ev_",
                "_evse_",
                "_charger_",
                "_ev_charging_",
                "_car_charger_",
                "_car_charging_",
                "_vehicle_charger_",
                "_vehicle_charging_",
                "_level2_charger_",
                "_level_2_charger_",
                "_wall_connector_",
            ),
            ApplianceProfile.EV_CHARGER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_solar_", "_inverter_", "_pv_"),
            ApplianceProfile.SOLAR_INVERTER,
            CircuitMode.SINGLE_PHASE,
        ),
    ):
        if any(token in normalized for token in tokens):
            return profile, mode
    return ApplianceProfile.MIXED, CircuitMode.MIXED
