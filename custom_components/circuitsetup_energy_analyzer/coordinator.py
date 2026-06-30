from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from inspect import isawaitable
from statistics import median
from typing import Any, Self

from . import notifications
from . import repairs as repairs  # noqa: F401 - compatibility for test monkeypatching
from .activity_alerts import ActivityAlertSettings
from .activity_timeline import (
    DEFAULT_TIMELINE_WINDOW_HOURS,
    build_recent_activity_timeline,
    timeline_payload,
)
from .aggregation import aggregate_dual_phase
from .alerting import (
    ConservativeAlertPolicy,
    Observation,
    alert_feedback_fingerprint,
    alert_feedback_fingerprint_for_observation,
)
from .balance import (
    DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
)
from .billing import (
    BillingCycleSettings,
)
from .capacity import (
    DEFAULT_CAPACITY_WARNING_RATIO,
    CapacitySettings,
)
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_DASHBOARD_LAYOUT,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_EXPECTS_WATER_FLOW,
    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_RAIN_RESPONSE_WINDOW_MINUTES,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DEFAULT_DASHBOARD_LAYOUT,
    DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
    DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
    DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
    DOMAIN,
)
from .cost import CostSettings
from .cycles import (
    MIN_CYCLE_BASELINE_CONFIDENCE,
    RUN_CYCLE_DURATION_FEATURE,
    cycle_baseline_feature_values,
    cycle_summary_payload,
    summarize_circuit_cycles,
)
from .dashboard import (
    DASHBOARD_URL_PATH,
    NILM_DASHBOARD_GRAPHS_CARD,
    dashboard_graph_module_resource,
    dashboard_includes_nilm_graph_card,
    normalize_dashboard_layout,
)
from .demand import (
    DemandSettings,
)
from .demo import (
    DEMO_HISTORY_SEED_VERSION as _DEMO_HISTORY_SEED_VERSION,
)
from .demo import (
    demo_baseline as _demo_baseline,
)
from .demo import (
    demo_circuit_key as _demo_circuit_key,
)
from .demo import (
    demo_nilm_workspace_seed as _demo_nilm_workspace_seed,
)
from .demo import (
    demo_prior_usage as _demo_prior_usage,
)
from .demo import (
    demo_today_usage as _demo_today_usage,
)
from .demo import (
    is_demo_config as _is_demo_config,
)
from .demo import (
    is_demo_source_entity_id as _is_demo_source_entity_id,
)
from .energy_dashboard import (
    evaluate_energy_dashboard_readiness,
    readiness_payload,
)
from .events import CircuitEventDetector
from .exporting import build_circuit_history_csv
from .goals import EnergyGoalSettings
from .load_shift import (
    FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
)
from .local_time import local_date, local_day_time
from .managers.dashboard_controller import DashboardController
from .managers.entity_profile_controller import EntityProfileController
from .managers.evidence_actions import EvidenceActionController
from .managers.nilm_controller import NilmController
from .managers.notification_controller import NotificationController
from .managers.settings_controller import SettingsController
from .managers.setup_health import SetupHealthAggregator
from .managers.source_updates import SourceUpdateManager
from .managers.state_reducer import StateReducer, apply_state_update
from .managers.store_persistence import StorePersistenceManager
from .metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    PowerFlowMode,
    RetentionMode,
    SensorRef,
    SensorRole,
)
from .nilm import (
    KnownLoadMatch,
    NilmEdge,
    NilmEdgeDetector,
)
from .nilm_virtual import nilm_virtual_appliance_alerts
from .normalize import NormalizedCircuitSample, SourceState, build_circuit_sample
from .operating_detection import (
    OPERATING_DETECTION_OVERRIDE_FIELDS,
    OPERATING_DETECTION_SOURCE,
    resolve_operating_detection_from_settings,
)
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
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
    ProcessingContext,
    RunCycleProcessor,
    SolarFlowProcessor,
    StandbyProcessor,
    UtilityComparisonProcessor,
    WaterContextAlertProcessor,
)
from .profiles import get_profile_definition
from .settings_advisor import (
    DEFAULT_RECOMMENDATION_TTL,
    AdvisorCircuitContext,
    AdvisorInputs,
    RecommendationDecision,
    RecommendationStatus,
    SettingRecommendation,
    build_settings_recommendations,
    recommendation_evidence_fingerprint,
    recommendation_id_for,
    recommendation_to_dict,
    recommendation_unique_key,
    should_suppress_recommendation,
)
from .solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from .standby import StandbySettings
from .storage import (
    RETENTION_WINDOWS,
    FeatureStoreData,
    prune_contextual_baseline_state,
)
from .usage import EnergyUsageSettings
from .utility_comparison import (
    DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
    DEFAULT_UTILITY_STATISTIC_PERIOD,
    UtilityComparisonSettings,
    select_latest_statistics_energy,
    select_statistics_energy_for_period,
)
from .ux import (
    alert_evidence_detail,
    alert_policy_name_for_sensitivity,
    canonicalize_sensitivity_config,
    data_quality_checklist,
    friendly_feature_name,
    health_summary,
    learning_progress,
    mutable_config_copy,
    normalize_sensitivity,
)
from .water_correlations import (
    FlowCorrelationInput,
    RainPumpCorrelationInput,
    evaluate_flow_correlation,
    evaluate_rain_pump_correlation,
)
from .weather_context import WeatherContextSample, evaluate_weather_context

_LOGGER = logging.getLogger(__name__)
_UTILITY_COMPARISON_SETUP_REPAIR_PROBLEM_BY_STATUS = {
    "unconfigured": "utility_comparison_source_mismatch",
    "missing_utility": "utility_comparison_missing_utility_source",
    "missing_measured": "utility_comparison_missing_measured_source",
}
_DEMO_SOURCE_UNIQUE_ID_PREFIX = "demo_source_exact_"

SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS = 0.5
WEATHER_CONTEXT_HISTORY_MAX_SAMPLES = 1008
WATER_CONTEXT_HISTORY_MAX_SAMPLES = 1008
ALERT_HISTORY_MAX_ITEMS = 500
ALERT_HISTORY_MAX_AGE = timedelta(days=180)
ALERT_FEEDBACK_MAX_ITEMS = 500
ALERT_FEEDBACK_MAX_AGE = timedelta(days=365)
ALERT_EXPECTED_FEEDBACK_TTL = timedelta(days=90)
ALERT_UNHELPFUL_FEEDBACK_TTL = timedelta(days=45)
ALERT_UNHELPFUL_EXTRA_REPEATED = 2
ALERT_UNHELPFUL_RECOMMENDATION_MIN_COUNT = 2
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
HVAC_WEATHER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)
PUMP_WATER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
    }
)
FLOW_WATER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.WASHER,
    }
)
try:
    from homeassistant.components.recorder import (
        get_instance as _ha_recorder_get_instance,
    )
    from homeassistant.components.recorder.statistics import (
        statistics_during_period as _ha_statistics_during_period,
    )
    from homeassistant.helpers.event import async_track_state_change_event
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
except ModuleNotFoundError:
    _ha_recorder_get_instance = None
    _ha_statistics_during_period = None
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


class _FeedbackAwareAlertPolicy:
    """Apply persisted alert feedback before delegating to the scoring policy."""

    def __init__(self: Self, coordinator: Any, policy: ConservativeAlertPolicy) -> None:
        self._coordinator = coordinator
        self._policy = policy

    @property
    def min_repeated(self: Self) -> int:
        return self._policy.min_repeated

    @property
    def min_total_score(self: Self) -> float:
        return self._policy.min_total_score

    @property
    def min_average_score(self: Self) -> float:
        return self._policy.min_average_score

    @property
    def min_baseline_confidence(self: Self) -> float:
        return self._policy.min_baseline_confidence

    def observe(self: Self, observation: Observation) -> AlertEvidence | None:
        min_repeated = self._coordinator._adjusted_min_repeated_for_observation(
            observation,
            self._policy.min_repeated,
        )
        alert = self._policy.observe(observation, min_repeated=min_repeated)
        if alert is None or min_repeated == self._policy.min_repeated:
            return alert
        return replace(alert, adjusted_min_repeated=min_repeated)


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
        circuit_id: max(_alert_anomaly_score(alert) for alert in circuit_alerts)
        for circuit_id, circuit_alerts in alerts_by_circuit.items()
    }

    for circuit_id in state.last_event_by_circuit:
        state.anomaly_score_by_circuit.setdefault(circuit_id, 0.0)

    return state


def _alert_anomaly_score(alert: AlertEvidence) -> float:
    if alert.change_ratio != 0.0:
        return abs(alert.change_ratio)

    if alert.baseline_value != 0.0:
        return abs((alert.observed_value - alert.baseline_value) / alert.baseline_value)

    return abs(alert.observed_value)


def _merged_entry_settings_map(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any],
    key: str,
) -> dict[str, dict[str, Any]]:
    settings: dict[str, dict[str, Any]] = {}
    for source in (entry_data.get(key, {}), options.get(key, {})):
        if not isinstance(source, Mapping):
            continue
        for circuit_id, value in source.items():
            if isinstance(value, Mapping):
                settings[str(circuit_id)] = dict(value)
    return settings


def _recommendation_materially_matches(
    existing: SettingRecommendation,
    candidate: SettingRecommendation,
) -> bool:
    return _recommendation_material_key(existing) == _recommendation_material_key(
        candidate,
    )


def _recommendation_material_key(
    recommendation: SettingRecommendation,
) -> tuple[Any, ...]:
    return (
        recommendation.recommendation_id,
        recommendation.unique_key,
        recommendation.circuit_id,
        recommendation.circuit_name,
        recommendation.setting_key,
        recommendation.setting_label,
        recommendation.current_value,
        recommendation.suggested_value,
        recommendation.unit,
        recommendation.feature,
        recommendation.group,
        round(recommendation.confidence, 3),
        recommendation.reason,
        tuple(sorted(dict(recommendation.apply_payload).items())),
        _material_evidence_key(recommendation.feature, recommendation.evidence),
        recommendation.advisor_version,
    )


def _material_evidence_key(
    feature: str,
    evidence: Mapping[str, Any],
) -> tuple[tuple[str, Any], ...]:
    ignored_keys: set[str] = set()
    if feature == "capacity_warning_ratio":
        ignored_keys.add("observed_samples")
    return tuple(
        sorted(
            (key, value)
            for key, value in dict(evidence).items()
            if key not in ignored_keys
        )
    )


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


def _replace_if_present(
    target: dict[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> None:
    values = {key: source[key] for key in keys if key in source}
    if values:
        target[circuit_id] = values


def _replace_if_present_as(
    target: dict[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    key_map: Mapping[str, str],
) -> None:
    values = {
        output_key: source[input_key]
        for input_key, output_key in key_map.items()
        if input_key in source
    }
    if values:
        target[circuit_id] = values


def _remove_setting_key(
    target: dict[str, dict[str, Any]],
    circuit_id: str,
    setting_key: str,
) -> None:
    current = target.get(circuit_id)
    if not isinstance(current, dict) or setting_key not in current:
        return
    updated = dict(current)
    updated.pop(setting_key, None)
    if updated:
        target[circuit_id] = updated
    else:
        target.pop(circuit_id, None)


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
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._entry_retention_mode = _retention_mode_from_sources(
            self.entry_data,
            self.options,
        )
        self._known_load_circuit_ids = frozenset(
            _string_list_from_sources(
                self.entry_data,
                self.options,
                CONF_KNOWN_LOAD_CIRCUITS,
            )
        )
        self._sensitivity = normalize_sensitivity(
            self.options.get(
                CONF_SENSITIVITY,
                self.entry_data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        )
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
        self.dashboard_controller = DashboardController(self)
        self.entity_profile_controller = EntityProfileController(self)
        self.evidence_actions = EvidenceActionController(self)
        self.nilm_controller = NilmController(self)
        self.settings_controller = SettingsController(self)
        self.state_reducer = StateReducer()
        self._apply_config_entry_settings()
        self._detectors = {
            config.circuit_id: CircuitEventDetector()
            for config in self.circuit_configs
        }
        self._baseline_values: defaultdict[str, list[float]] = defaultdict(list)
        self._event_processor = CircuitEventProcessor(self._detectors)
        self._power_quality_processor = PowerQualityProcessor(
            alert_policy_for_circuit=self._alert_policy_for_circuit,
            learning_mature=self._learning_mature,
            seed_demo_event_history=self._seed_demo_event_history,
            seed_demo_power_quality_baselines=self._seed_demo_power_quality_baselines,
            baseline_values=self._baseline_values,
        )
        self._energy_usage_processor = EnergyUsageProcessor(
            settings_for_config=self._energy_usage_settings_for_config,
            retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
                self._retention_mode_for_circuit(circuit_id)
            ].days,
            alert_policy_for_circuit=self._usage_alert_policy_for_circuit,
            seed_demo_history=self._seed_demo_energy_usage_history,
        )
        self._energy_goal_processor = EnergyGoalProcessor(
            settings_for_config=self._energy_goal_settings_for_config,
            alert_policy_for_circuit=self._goal_alert_policy_for_circuit,
        )
        self._run_cycle_processor = RunCycleProcessor(
            alert_policy_for_circuit=self._cycle_alert_policy_for_circuit,
            learning_mature=self._learning_mature,
        )
        self._activity_alert_processor = ActivityAlertProcessor(
            settings_for_config=self._activity_alert_settings_for_config,
            alert_policy_for_circuit=self._activity_alert_policy_for_circuit,
        )
        self._billing_cycle_processor = BillingCycleProcessor(
            settings_for_config=self._billing_cycle_settings_for_config,
            alert_policy_for_circuit=self._billing_alert_policy_for_circuit,
        )
        self._cost_processor = CostProcessor(
            settings_for_config=self._cost_settings_for_config,
        )
        self._demand_processor = DemandProcessor(
            settings_for_config=self._demand_settings_for_config,
            alert_policy_for_circuit=self._demand_alert_policy_for_circuit,
            retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
                self._retention_mode_for_circuit(circuit_id)
            ].days,
        )
        self._capacity_processor = CapacityProcessor(
            settings_for_config=self._capacity_settings_for_config,
            alert_policy_for_circuit=self._capacity_alert_policy_for_circuit,
            retention_days_for_circuit=lambda circuit_id: RETENTION_WINDOWS[
                self._retention_mode_for_circuit(circuit_id)
            ].days,
            source_states_for=self._source_states_for,
        )
        self._leg_imbalance_processor = LegImbalanceProcessor(
            alert_policy_for_circuit=self._leg_imbalance_alert_policy_for_circuit,
        )
        self._metric_consistency_processor = MetricConsistencyProcessor()
        self._standby_processor = StandbyProcessor(
            settings_for_config=self._standby_settings_for_config,
            alert_policy_for_circuit=self._standby_alert_policy_for_circuit,
            seed_demo_history=lambda config, sample, context, settings: (
                self._seed_demo_standby_history(config, sample, context.now, settings)
            ),
        )
        self._utility_comparison_processor = UtilityComparisonProcessor(
            settings_for_circuit=self._utility_comparison_settings_for_circuit,
            alert_policy_for_circuit=self._utility_comparison_alert_policy_for_circuit,
            energy_kwh_for_entity=self._energy_kwh_for_entity,
            energy_kwh_sum_for_entities=self._energy_kwh_sum_for_entities,
            statistics_kwh_for_id=(
                lambda statistic_id, now, period: self._statistics_kwh_for_id(
                    statistic_id,
                    now,
                    period=period,
                )
            ),
            statistics_kwh_sum_for_entities=(
                lambda entity_ids, now, period, start_time, end_time: (
                    self._statistics_kwh_sum_for_entities(
                        entity_ids,
                        now,
                        period=period,
                        start_time=start_time,
                        end_time=end_time,
                    )
                )
            ),
            load_energy_entity_ids_for_sum=self._load_energy_entity_ids_for_sum,
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
        self._nilm_topology_processor = NilmTopologyProcessor(
            known_config_for_circuit=self._config_for_circuit,
            alert_policy_for_circuit=self._nilm_topology_alert_policy_for_circuit,
        )
        self._nilm_detectors: dict[str, NilmEdgeDetector] = {}
        self._nilm_unmatched_edges: defaultdict[str, list[NilmEdge]] = defaultdict(list)
        self._nilm_total_events_by_circuit: defaultdict[str, int] = defaultdict(int)
        self.ignored_nilm_signatures: set[tuple[str, str]] = set()
        self._nilm_sample_processor = NilmSampleProcessor(
            nilm_enabled=self._nilm_enabled,
            seed_demo_nilm_state=self._seed_demo_nilm_state,
            min_delta_w_for_circuit=(
                lambda circuit_id: _nilm_min_delta_w(
                    self._sensitivity_for_circuit(circuit_id),
                )
            ),
            detectors=self._nilm_detectors,
            total_events_by_circuit=self._nilm_total_events_by_circuit,
            unmatched_edges_by_circuit=self._nilm_unmatched_edges,
            ignored_signatures=self.ignored_nilm_signatures,
            known_load_events=self._known_load_events,
            observe_topology=(
                lambda config, match, _context: [
                    alert
                    for alert in [
                        self._observe_nilm_known_load_topology(config, match)
                    ]
                    if alert is not None
                ]
            ),
        )
        self._water_context_alert_processor = WaterContextAlertProcessor(
            alert_policy_for_circuit=self._water_context_alert_policy_for_circuit,
        )
        self._alert_policy = _alert_policy_for_sensitivity(self._sensitivity)
        self._alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._usage_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._goal_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._billing_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._demand_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._capacity_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._leg_imbalance_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._standby_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._utility_comparison_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._nilm_topology_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._cycle_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._activity_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._water_context_alert_policies: dict[
            tuple[str, str, str],
            ConservativeAlertPolicy,
        ] = {}
        self.store_persistence = StorePersistenceManager(self)
        self.notification_controller = NotificationController(
            self,
            compact_settings_recommendation_episode_key=(
                _compact_settings_recommendation_episode_key
            ),
            material_evidence_key=_material_evidence_key,
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
        self._hydrate_state_from_store()
        self.async_set_updated_data(self.state)

    async def async_start(self: Self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        await self.source_updates.async_start(source_entities)

    async def async_stop(self: Self) -> None:
        """Stop listening to source entity state changes."""
        await self.source_updates.async_stop()

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

    @property
    def _source_update_task(self: Self) -> asyncio.Task[Any] | None:
        return self.source_updates.source_update_task

    def _apply_config_entry_settings(self: Self) -> None:
        """Apply setup/options settings to store-backed runtime setting maps."""
        for circuit_id, settings in _merged_entry_settings_map(
            self.entry_data,
            self.options,
            CONF_UTILITY_COMPARISON_SETTINGS,
        ).items():
            if settings:
                self.store_data.utility_comparison_settings_by_circuit[circuit_id] = (
                    settings
                )
            else:
                self.store_data.utility_comparison_settings_by_circuit.pop(
                    circuit_id,
                    None,
                )

        for circuit_id, settings in _merged_entry_settings_map(
            self.entry_data,
            self.options,
            CONF_ADVANCED_SETTINGS,
        ).items():
            self._replace_advanced_settings(circuit_id, settings)

    def _replace_advanced_settings(
        self: Self,
        circuit_id: str,
        settings: dict[str, Any],
    ) -> None:
        self._clear_advanced_settings(circuit_id)
        self._apply_advanced_settings(circuit_id, settings)

    def _clear_advanced_settings(self: Self, circuit_id: str) -> None:
        self.store_data.sensitivity_by_circuit.pop(circuit_id, None)
        self.store_data.energy_usage_settings_by_circuit.pop(circuit_id, None)
        self.store_data.energy_goal_settings_by_circuit.pop(circuit_id, None)
        self.store_data.activity_alert_settings_by_circuit.pop(circuit_id, None)
        self.store_data.billing_settings_by_circuit.pop(circuit_id, None)
        self.store_data.cost_settings_by_circuit.pop(circuit_id, None)
        self.store_data.demand_settings_by_circuit.pop(circuit_id, None)
        self.store_data.capacity_settings_by_circuit.pop(circuit_id, None)
        self.store_data.standby_settings_by_circuit.pop(circuit_id, None)
        self.store_data.leg_imbalance_settings_by_circuit.pop(circuit_id, None)
        self.store_data.metric_consistency_settings_by_circuit.pop(circuit_id, None)
        self.store_data.balance_settings_by_circuit.pop(circuit_id, None)
        self.store_data.solar_flow_settings_by_circuit.pop(circuit_id, None)
        self.store_data.operating_detection_settings_by_circuit.pop(circuit_id, None)

    def _apply_advanced_settings(
        self: Self,
        circuit_id: str,
        settings: dict[str, Any],
    ) -> None:
        if not settings:
            return

        sensitivity = settings.get("preset")
        if sensitivity:
            self.store_data.sensitivity_by_circuit[circuit_id] = (
                normalize_sensitivity(str(sensitivity))
            )

        _replace_if_present(
            self.store_data.energy_usage_settings_by_circuit,
            circuit_id,
            settings,
            ("window_days", "daily_spike_ratio"),
        )
        _replace_if_present(
            self.store_data.energy_goal_settings_by_circuit,
            circuit_id,
            settings,
            ("daily_goal_kwh", "goal_alert_ratio"),
        )
        _replace_if_present(
            self.store_data.activity_alert_settings_by_circuit,
            circuit_id,
            settings,
            ("max_active_minutes", "max_idle_minutes"),
        )
        _replace_if_present(
            self.store_data.billing_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "budget_kwh",
                "budget_alert_ratio",
                "min_elapsed_days",
            ),
        )
        _replace_if_present(
            self.store_data.cost_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "default_rate_per_kwh",
                "tou_rate_per_kwh",
                "tou_start",
                "tou_end",
                "tou_weekdays",
                "tou_name",
            ),
        )
        _replace_if_present(
            self.store_data.demand_settings_by_circuit,
            circuit_id,
            settings,
            ("window_minutes", "demand_limit_w"),
        )
        _replace_if_present(
            self.store_data.capacity_settings_by_circuit,
            circuit_id,
            settings,
            ("breaker_amps", "warning_ratio"),
        )
        _replace_if_present(
            self.store_data.standby_settings_by_circuit,
            circuit_id,
            settings,
            (
                "window_hours",
                "standby_threshold_w",
                "always_on_alert_w",
                "min_samples",
            ),
        )
        _replace_if_present_as(
            self.store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            settings,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            },
        )
        _replace_if_present(
            self.store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            settings,
            (
                "apparent_power_tolerance_percent",
                "power_factor_tolerance",
                "minimum_apparent_power_va",
            ),
        )
        _replace_if_present_as(
            self.store_data.balance_settings_by_circuit,
            circuit_id,
            settings,
            {"balance_negative_tolerance_w": "negative_tolerance_w"},
        )
        _replace_if_present_as(
            self.store_data.solar_flow_settings_by_circuit,
            circuit_id,
            settings,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
                "solar_surplus_threshold_w": "solar_surplus_threshold_w",
                "high_solar_surplus_threshold_w": (
                    "high_solar_surplus_threshold_w"
                ),
                "flexible_load_running_threshold_w": (
                    "flexible_load_running_threshold_w"
                ),
            },
        )
        _replace_if_present(
            self.store_data.operating_detection_settings_by_circuit,
            circuit_id,
            settings,
            (*OPERATING_DETECTION_OVERRIDE_FIELDS, OPERATING_DETECTION_SOURCE),
        )

    async def _async_handle_source_state_change(self: Self, event: Any) -> None:
        """Handle Home Assistant source state changes."""
        await self.source_updates.async_handle_source_state_change(event)

    async def _async_process_debounced_source_update(self: Self) -> None:
        """Process one analyzer update for a burst of source state changes."""
        await self.source_updates.async_process_debounced_source_update()

    def _cancel_pending_source_update(self: Self) -> None:
        """Cancel queued source-state processing during restart/unload."""
        self.source_updates.cancel_pending_source_update()

    def _build_processing_context(self: Self, now: datetime) -> ProcessingContext:
        """Build immutable runtime context for feature processors."""
        return ProcessingContext(
            now=now,
            hass=self.hass,
            state=self.state,
            store_data=self.store_data,
            options=self.options,
            entry_data=self.entry_data,
            known_load_circuit_ids=self._known_load_circuit_ids,
            sensitivity=self._sensitivity,
            time_zone=self._ha_time_zone(),
        )

    def _ha_time_zone(self: Self) -> str | None:
        """Return Home Assistant's configured timezone name when available."""
        value = getattr(getattr(self.hass, "config", None), "time_zone", None)
        return str(value) if value else None

    async def async_process_update(self: Self) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        context = self._build_processing_context(now)
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []
        self._prune_recent_observations(now)

        for config in self.circuit_configs:
            sample = self._sample_for_config(config, now)
            samples.append((config, sample))
            self._refresh_config_metadata_state(config)
            self._refresh_latest_real_power_state(config, sample)
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            event_result = self._event_processor.process(sample, config, context)
            new_events, _ = await self._apply_feature_result(
                event_result,
            )
            events.extend(new_events)

            power_quality_result = self._power_quality_processor.process(
                sample,
                config,
                context,
            )
            if power_quality_result.clear_power_quality_state is not None:
                self._clear_power_quality_state(
                    power_quality_result.clear_power_quality_state
                )
            _, power_quality_alerts = await self._apply_feature_result(
                power_quality_result
            )
            alerts.extend(power_quality_alerts)

            usage_result = self._energy_usage_processor.process(sample, config, context)
            _, usage_alerts = await self._apply_feature_result(usage_result)
            alerts.extend(usage_alerts)

            goal_result = self._energy_goal_processor.process(sample, config, context)
            _, goal_alerts = await self._apply_feature_result(goal_result)
            alerts.extend(goal_alerts)

            cycle_result = self._run_cycle_processor.process(sample, config, context)
            _, cycle_alerts = await self._apply_feature_result(cycle_result)
            alerts.extend(cycle_alerts)

            activity_result = self._activity_alert_processor.process(
                sample,
                config,
                context,
            )
            _, activity_alerts = await self._apply_feature_result(activity_result)
            alerts.extend(activity_alerts)

            billing_result = self._billing_cycle_processor.process(
                sample,
                config,
                context,
            )
            _, billing_alerts = await self._apply_feature_result(billing_result)
            alerts.extend(billing_alerts)

            cost_result = self._cost_processor.process(sample, config, context)
            await self._apply_feature_result(cost_result)

            demand_result = self._demand_processor.process(sample, config, context)
            _, demand_alerts = await self._apply_feature_result(demand_result)
            alerts.extend(demand_alerts)

            capacity_result = self._capacity_processor.process(sample, config, context)
            _, capacity_alerts = await self._apply_feature_result(capacity_result)
            alerts.extend(capacity_alerts)

            leg_imbalance_result = self._leg_imbalance_processor.process(
                sample,
                config,
                context,
            )
            _, leg_imbalance_alerts = await self._apply_feature_result(
                leg_imbalance_result
            )
            alerts.extend(leg_imbalance_alerts)

            metric_consistency_result = self._metric_consistency_processor.process(
                sample,
                config,
                context,
            )
            await self._apply_feature_result(metric_consistency_result)

            if (
                config.power_flow is PowerFlowMode.GENERATION
                or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
            ):
                self._clear_standby_state(config.circuit_id)
            else:
                standby_result = self._standby_processor.process(
                    sample,
                    config,
                    context,
                )
                _, standby_alerts = await self._apply_feature_result(standby_result)
                alerts.extend(standby_alerts)

        for config, sample in samples:
            for nilm_alert in self._process_nilm_sample(config, sample, events):
                nilm_alert = self._alert_with_feedback(nilm_alert)
                if nilm_alert.feedback_status != "expected":
                    alerts.append(nilm_alert)
                self.store_data.alerts.append(nilm_alert)
                self._mark_store_dirty()
                await self._notify_alert(nilm_alert)
        alerts.extend(await self._notify_nilm_virtual_appliances(now))
        self._refresh_balance_state(samples, now)
        self._refresh_solar_flow_state(samples, now)
        alerts.extend(await self._observe_utility_comparisons(now))

        process_events_into_state(self.state, events, alerts)
        for config, sample in samples:
            self._refresh_ux_state(config, sample, now)
            await self._sync_setup_health_repairs(config.circuit_id)
            water_context_alert = self._observe_water_context(config, now)
            if water_context_alert is not None:
                water_context_alert = self._alert_with_feedback(water_context_alert)
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
        await self._notify_settings_recommendations_if_needed()
        return self.state

    def _refresh_config_metadata_state(self: Self, config: CircuitConfig) -> None:
        """Expose configured circuit classification metadata as diagnostic state."""
        self.state.circuit_mode_by_circuit[config.circuit_id] = (
            _friendly_circuit_mode(config.mode)
        )
        self.state.power_flow_by_circuit[config.circuit_id] = (
            _friendly_power_flow(config.power_flow)
        )

    def _refresh_latest_real_power_state(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample,
    ) -> None:
        """Store the latest normalized watts for lightweight state entities."""
        power_w = getattr(sample, "real_power", None)
        if power_w is None:
            self.state.latest_real_power_w_by_circuit.pop(config.circuit_id, None)
            return
        self.state.latest_real_power_w_by_circuit[config.circuit_id] = float(power_w)

    async def async_relearn_baseline(self: Self, circuit_id: str) -> None:
        """Clear learned baselines and alert state for one circuit."""
        prefix = f"{circuit_id}:"
        self.store_data.baselines = {
            key: value
            for key, value in self.store_data.baselines.items()
            if not key.startswith(prefix)
        }
        for key in list(self._baseline_values):
            if key.startswith(prefix):
                self._baseline_values.pop(key, None)
        self.store_data.alerts = [
            alert for alert in self.store_data.alerts if alert.circuit_id != circuit_id
        ]
        self._mark_store_dirty()
        self.state.active_alerts_by_circuit.pop(circuit_id, None)
        self.state.anomaly_score_by_circuit[circuit_id] = 0.0
        self.state.learning_by_circuit[circuit_id] = True
        self._clear_power_quality_state(circuit_id)
        self._clear_nilm_topology_state(circuit_id)
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
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
        self.store_data.sensitivity_by_circuit[circuit_id] = normalize_sensitivity(
            preset
        )
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

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
        advanced_by_circuit = self.options.setdefault(CONF_ADVANCED_SETTINGS, {})
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            self.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        updated_settings = dict(settings)
        advanced_by_circuit[circuit_id] = updated_settings
        self._replace_advanced_settings(circuit_id, updated_settings)
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_energy_usage_settings(
        self: Self,
        circuit_id: str,
        window_days: Any = None,
        daily_spike_ratio: Any = None,
    ) -> None:
        """Persist daily energy usage spike settings for one circuit."""
        config = self._config_for_circuit(circuit_id)
        current = self._energy_usage_settings_for_config(config, circuit_id)
        settings = {
            "window_days": _positive_int_value(
                window_days,
                default=current.window_days,
            ),
            "daily_spike_ratio": _positive_float_value(
                daily_spike_ratio,
                default=current.daily_spike_ratio,
            ),
        }
        self.store_data.energy_usage_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

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
        target_configs = [
            config
            for config in self.circuit_configs
            if circuit_id is None or config.circuit_id == circuit_id
        ]
        changed = False

        for config in target_configs:
            advisor_inputs = self._advisor_inputs_for_config(config, now)
            recommendations = build_settings_recommendations(advisor_inputs)
            recommendations.extend(
                self._unhelpful_alert_setting_recommendations(
                    config,
                    now,
                    existing_recommendation_ids={
                        recommendation.recommendation_id
                        for recommendation in recommendations
                    },
                ),
            )
            recommendation_ids = {
                recommendation.recommendation_id
                for recommendation in recommendations
            }
            for stored_id, stored in list(
                self.store_data.settings_recommendations.items(),
            ):
                if (
                    stored.circuit_id == config.circuit_id
                    and stored.status is RecommendationStatus.PENDING
                    and stored_id not in recommendation_ids
                ):
                    self.store_data.settings_recommendations[stored_id] = replace(
                        stored,
                        status=RecommendationStatus.STALE,
                    )
                    changed = True

            for recommendation in recommendations:
                stored = self.store_data.settings_recommendations.get(
                    recommendation.recommendation_id,
                )
                if (
                    stored is not None
                    and stored.status is RecommendationStatus.PENDING
                    and stored.expires_at > now
                    and _recommendation_materially_matches(stored, recommendation)
                ):
                    continue
                if stored != recommendation:
                    self.store_data.settings_recommendations[
                        recommendation.recommendation_id
                    ] = recommendation
                    changed = True

        self._refresh_settings_recommendation_state(now)
        return changed

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

    def _set_recommendation_setting_value(
        self: Self,
        circuit_id: str,
        setting_key: str,
        value: Any,
    ) -> None:
        advanced_by_circuit = self.options.setdefault(CONF_ADVANCED_SETTINGS, {})
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            self.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        current_settings = advanced_by_circuit.get(circuit_id, {})
        updated_settings = (
            dict(current_settings) if isinstance(current_settings, Mapping) else {}
        )
        self._clear_advanced_setting_value(circuit_id, setting_key)
        if value is None:
            updated_settings.pop(setting_key, None)
        else:
            updated_settings[setting_key] = value
            self._apply_advanced_settings(circuit_id, {setting_key: value})
        if updated_settings:
            advanced_by_circuit[circuit_id] = updated_settings
        else:
            advanced_by_circuit.pop(circuit_id, None)

    def _clear_advanced_setting_value(
        self: Self,
        circuit_id: str,
        setting_key: str,
    ) -> None:
        if setting_key == "preset":
            self.store_data.sensitivity_by_circuit.pop(circuit_id, None)
            return
        _remove_setting_key(
            self.store_data.energy_usage_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.energy_goal_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.activity_alert_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.billing_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.cost_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.demand_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.capacity_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.standby_settings_by_circuit,
            circuit_id,
            "min_samples" if setting_key == "standby_min_samples" else setting_key,
        )
        _remove_setting_key(
            self.store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            self.store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            self.store_data.balance_settings_by_circuit,
            circuit_id,
            {
                "balance_negative_tolerance_w": "negative_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            self.store_data.solar_flow_settings_by_circuit,
            circuit_id,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            self.store_data.operating_detection_settings_by_circuit,
            circuit_id,
            setting_key,
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

    async def _async_persist_config_entry_options(self: Self) -> None:
        if self._config_entry is None:
            return
        config_entries = getattr(self.hass, "config_entries", None)
        update_entry = getattr(config_entries, "async_update_entry", None)
        if update_entry is None:
            return

        options = mutable_config_copy(self.options)
        result = update_entry(self._config_entry, options=options)
        if isawaitable(result):
            await result
        self.options = mutable_config_copy(options)

    async def _async_reload_config_entry(self: Self) -> None:
        if self._config_entry is None:
            return
        config_entries = getattr(self.hass, "config_entries", None)
        reload_entry = getattr(config_entries, "async_reload", None)
        if reload_entry is None:
            return

        result = reload_entry(self.entry_id)
        if isawaitable(result):
            await result

    async def _async_record_setting_recommendation_decision(
        self: Self,
        recommendation_id: str,
        status: RecommendationStatus,
    ) -> None:
        recommendation = self.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.PENDING
        ):
            return

        now = self._now_fn()
        self.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=status,
        )
        self.store_data.settings_recommendation_decisions[
            recommendation.unique_key
        ] = RecommendationDecision(
            unique_key=recommendation.unique_key,
            status=status,
            decided_at=now,
            denied_value=recommendation.suggested_value,
            evidence_fingerprint=recommendation_evidence_fingerprint(
                recommendation,
            ),
        )
        self._mark_store_dirty()
        self._refresh_settings_recommendation_state(now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    def _advisor_inputs_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AdvisorInputs:
        return AdvisorInputs(
            now=now,
            context=AdvisorCircuitContext(
                circuit_id=config.circuit_id,
                circuit_name=config.name,
                appliance_profile=config.appliance_profile.value,
                circuit_mode=config.mode.value,
                power_flow=config.power_flow.value,
                advanced_settings=self._advanced_settings_for_circuit(
                    config.circuit_id,
                ),
            ),
            feature_history=self._advisor_feature_history_for_circuit(config, now),
            decisions=self.store_data.settings_recommendation_decisions,
        )

    def _unhelpful_alert_setting_recommendations(
        self: Self,
        config: CircuitConfig,
        now: datetime,
        *,
        existing_recommendation_ids: set[str],
    ) -> list[SettingRecommendation]:
        recommendation_id = recommendation_id_for(
            config.circuit_id,
            "daily_spike_ratio",
        )
        if recommendation_id in existing_recommendation_ids:
            return []

        feedback = self._repeated_unhelpful_daily_spike_feedback(config, now)
        if feedback is None:
            return []

        current_value = _positive_float_value(
            self._advanced_settings_for_circuit(config.circuit_id).get(
                "daily_spike_ratio",
            ),
            default=config.daily_energy_spike_ratio,
        )
        change_ratio = _absolute_float_value(feedback.get("change_ratio"))
        suggested_value = round(
            min(1.0, max(current_value + 0.05, change_ratio + 0.10)),
            1,
        )
        if suggested_value <= current_value:
            return []

        unique_key = recommendation_unique_key(config.circuit_id, "daily_spike_ratio")
        evidence = {
            "source": "unhelpful_alert_feedback",
            "feedback_fingerprint": str(feedback.get("fingerprint") or ""),
            "unhelpful_feedback_count": _positive_int_value(
                feedback.get("evidence_count"),
                default=1,
            ),
            "change_ratio": round(change_ratio, 3),
            "observed_value": _optional_float_value(feedback.get("observed_value")),
            "baseline_value": _optional_float_value(feedback.get("baseline_value")),
            "suggested_daily_spike_ratio": suggested_value,
        }
        recommendation = SettingRecommendation(
            recommendation_id=recommendation_id,
            unique_key=unique_key,
            circuit_id=config.circuit_id,
            circuit_name=config.name,
            setting_key="daily_spike_ratio",
            setting_label="Daily Spike Ratio",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="ratio",
            feature="energy_usage_spikes",
            group="Energy Usage",
            confidence=0.72,
            reason=(
                "This daily energy spike pattern was repeatedly marked not "
                "helpful. Increase the daily spike ratio to make future "
                "matching alerts more conservative."
            ),
            evidence=evidence,
            apply_payload={"daily_spike_ratio": suggested_value},
            status=RecommendationStatus.PENDING,
            created_at=now,
            expires_at=now + DEFAULT_RECOMMENDATION_TTL,
        )
        if should_suppress_recommendation(
            self.store_data.settings_recommendation_decisions.get(unique_key),
            now=now,
            suggested_value=recommendation.suggested_value,
            evidence_fingerprint=recommendation_evidence_fingerprint(recommendation),
        ):
            return []
        return [recommendation]

    def _repeated_unhelpful_daily_spike_feedback(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> Mapping[str, Any] | None:
        matches: list[Mapping[str, Any]] = []
        for feedback in self.store_data.alert_feedback.values():
            if not isinstance(feedback, Mapping):
                continue
            if _alert_feedback_status(feedback) != "unhelpful":
                continue
            if _alert_feedback_is_expired(feedback, now):
                continue
            if str(feedback.get("circuit_id") or "") != config.circuit_id:
                continue
            if str(feedback.get("feature") or "") != "daily_energy_usage_spike":
                continue
            if (
                _positive_int_value(feedback.get("evidence_count"), default=1)
                < ALERT_UNHELPFUL_RECOMMENDATION_MIN_COUNT
            ):
                continue
            matches.append(feedback)
        if not matches:
            return None
        return max(
            matches,
            key=lambda feedback: (
                _positive_int_value(feedback.get("evidence_count"), default=1),
                (
                    _mapping_datetime(feedback.get("last_seen")).timestamp()
                    if _mapping_datetime(feedback.get("last_seen")) is not None
                    else 0.0
                ),
            ),
        )

    def _advanced_settings_for_circuit(self: Self, circuit_id: str) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        for source in (
            self.entry_data.get(CONF_ADVANCED_SETTINGS, {}),
            self.options.get(CONF_ADVANCED_SETTINGS, {}),
        ):
            if not isinstance(source, Mapping):
                continue
            raw_settings = source.get(circuit_id, {})
            if isinstance(raw_settings, Mapping):
                settings.update(dict(raw_settings))

        settings.update(
            self.store_data.energy_usage_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(
            self.store_data.activity_alert_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(self.store_data.demand_settings_by_circuit.get(circuit_id, {}))
        settings.update(
            self.store_data.capacity_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(self.store_data.standby_settings_by_circuit.get(circuit_id, {}))
        settings.update(
            self.store_data.metric_consistency_settings_by_circuit.get(
                circuit_id,
                {},
            ),
        )

        leg_imbalance = self.store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "warning_ratio" in leg_imbalance:
            settings["leg_imbalance_warning_ratio"] = leg_imbalance["warning_ratio"]
        if "minimum_total_power_w" in leg_imbalance:
            settings["leg_imbalance_min_total_power_w"] = leg_imbalance[
                "minimum_total_power_w"
            ]

        balance = self.store_data.balance_settings_by_circuit.get(circuit_id, {})
        if "negative_tolerance_w" in balance:
            settings["balance_negative_tolerance_w"] = balance[
                "negative_tolerance_w"
            ]

        solar_flow = self.store_data.solar_flow_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "export_tolerance_w" in solar_flow:
            settings["solar_export_tolerance_w"] = solar_flow["export_tolerance_w"]
        for key in (
            "solar_surplus_threshold_w",
            "high_solar_surplus_threshold_w",
            "flexible_load_running_threshold_w",
        ):
            if key in solar_flow:
                settings[key] = solar_flow[key]

        settings.update(
            self.store_data.operating_detection_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )

        return settings

    def _advisor_feature_history_for_circuit(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, Any]:
        circuit_id = config.circuit_id
        feature_history: dict[str, Any] = {
            "energy_usage_days": [],
            "cycles": [],
            "operating_idle_samples": [],
            "operating_start_samples": [],
            "standby_samples_w": [],
            "current_samples": [],
            "leg_imbalance_ratios": [],
            "dual_phase_total_power_w": [],
            "apparent_power_residual_percent": [],
            "power_factor_residual": [],
            "apparent_power_samples_va": [],
            "negative_balance_w": [],
            "solar_export_w": [],
        }

        usage_history = self.store_data.energy_usage_by_circuit.get(circuit_id, {})
        usage_days = usage_history.get("days")
        if isinstance(usage_days, list):
            feature_history["energy_usage_days"] = list(usage_days)

        merge_gap_seconds = resolve_operating_detection_from_settings(
            config,
            getattr(
                self.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_id, {}),
        ).profile.merge_gap_seconds
        cycle_values = cycle_baseline_feature_values(
            self.store_data.events,
            circuit_id=circuit_id,
            now=now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=self._ha_time_zone(),
        )
        feature_history["cycles"] = [
            {"duration_minutes": duration_seconds / 60.0}
            for duration_seconds in _numeric_items(
                cycle_values.get(RUN_CYCLE_DURATION_FEATURE, []),
            )
        ]

        standby_history = self.store_data.standby_by_circuit.get(circuit_id, {})
        standby_samples = standby_history.get("samples")
        if isinstance(standby_samples, list):
            feature_history["operating_idle_samples"] = [
                dict(sample)
                for sample in standby_samples
                if isinstance(sample, Mapping)
            ]
        feature_history["standby_samples_w"] = _numeric_items(
            standby_samples,
            keys=("real_power_w",),
        )

        feature_history["operating_start_samples"] = [
            {
                "timestamp": event.timestamp.isoformat(),
                "power_w": float(event.features["startup_power_w"]),
            }
            for event in self.store_data.events
            if (
                event.circuit_id == circuit_id
                and event.event_type is EventType.START
                and "startup_power_w" in event.features
            )
        ]

        demand_history = self.store_data.demand_by_circuit.get(circuit_id, {})
        feature_history["current_samples"] = _numeric_items(
            demand_history.get("capacity_current_samples"),
            keys=("current_amps", "current_a", "amps"),
        )
        feature_history["current_samples"].extend(
            _numeric_items(
                demand_history.get("samples"),
                keys=("current_a", "current_amps", "amps"),
            )
        )

        leg_evidence = self.state.leg_imbalance_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["leg_imbalance_ratios"] = _numeric_items(
            [leg_evidence],
            keys=("leg_imbalance_ratio",),
        )
        total_power = _sum_optional_values(
            leg_evidence.get("left_real_power_w"),
            leg_evidence.get("right_real_power_w"),
        )
        if total_power is not None:
            feature_history["dual_phase_total_power_w"] = [total_power]

        metric_evidence = self.state.metric_consistency_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["apparent_power_residual_percent"] = _numeric_items(
            [metric_evidence],
            keys=("apparent_power_difference_percent",),
        )
        feature_history["power_factor_residual"] = _numeric_items(
            [metric_evidence],
            keys=("power_factor_difference",),
        )
        feature_history["apparent_power_samples_va"] = _numeric_items(
            [metric_evidence],
            keys=("reported_apparent_power_va",),
        )

        balance_evidence = self.state.balance_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["negative_balance_w"] = _numeric_items(
            [balance_evidence],
            keys=("balance_power_w",),
        )

        solar_evidence = self.state.solar_flow_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["solar_export_w"] = _numeric_items(
            [solar_evidence],
            keys=("grid_export_w", "solar_grid_export_w"),
        )

        return feature_history

    def _refresh_settings_recommendation_state(self: Self, now: datetime) -> None:
        by_circuit: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        pending_count_by_circuit: defaultdict[str, int] = defaultdict(int)
        for recommendation in sorted(
            self._visible_settings_recommendations(now),
            key=lambda item: (
                item.circuit_name,
                item.status is not RecommendationStatus.PENDING,
                item.group,
                item.setting_label,
                item.recommendation_id,
            ),
        ):
            by_circuit[recommendation.circuit_id].append(
                recommendation_to_dict(recommendation),
            )
            if recommendation.status is RecommendationStatus.PENDING:
                pending_count_by_circuit[recommendation.circuit_id] += 1
        self.state.settings_recommendations_by_circuit = dict(by_circuit)
        self.state.settings_recommendation_count_by_circuit = {
            circuit_id: count
            for circuit_id, count in pending_count_by_circuit.items()
            if count > 0
        }
        if not pending_count_by_circuit:
            self._set_settings_recommendation_notification_episode_key(())

    def _visible_settings_recommendations(
        self: Self,
        now: datetime,
    ) -> list[SettingRecommendation]:
        return [
            recommendation
            for recommendation in self.store_data.settings_recommendations.values()
            if recommendation.status
            in {RecommendationStatus.PENDING, RecommendationStatus.APPLIED}
            and recommendation.expires_at > now
        ]

    def _pending_settings_recommendations(
        self: Self,
        now: datetime,
    ) -> list[SettingRecommendation]:
        return [
            recommendation
            for recommendation in self.store_data.settings_recommendations.values()
            if recommendation.status is RecommendationStatus.PENDING
            and recommendation.expires_at > now
        ]

    async def _notify_settings_recommendations_if_needed(self: Self) -> None:
        await (
            self.notification_controller.async_notify_settings_recommendations_if_needed()
        )

    def _settings_recommendation_episode_key(
        self: Self,
    ) -> tuple[tuple[str, ...], ...]:
        return self.notification_controller.settings_recommendation_episode_key()

    def _set_settings_recommendation_notification_episode_key(
        self: Self,
        episode_key: tuple[tuple[str, ...], ...],
    ) -> None:
        self.notification_controller.set_settings_recommendation_notification_episode_key(
            episode_key
        )

    async def async_set_energy_goal_settings(
        self: Self,
        circuit_id: str,
        daily_goal_kwh: Any = None,
        goal_alert_ratio: Any = None,
    ) -> None:
        """Persist daily energy goal settings for one circuit."""
        config = self._config_for_circuit(circuit_id)
        current = self._energy_goal_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "goal_alert_ratio": _positive_float_value(
                goal_alert_ratio,
                default=current.goal_alert_ratio,
            ),
        }
        if daily_goal_kwh is None:
            if current.daily_goal_kwh is not None:
                settings["daily_goal_kwh"] = current.daily_goal_kwh
        else:
            goal_kwh = _optional_positive_float_value(
                daily_goal_kwh,
                default=None,
            )
            settings["daily_goal_kwh"] = goal_kwh if goal_kwh is not None else 0.0
        self.store_data.energy_goal_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        goal_result = self._energy_goal_processor.refresh_state(
            circuit_id,
            config,
            self._build_processing_context(now),
        )
        await self._apply_feature_result(goal_result)
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_activity_alert_settings(
        self: Self,
        circuit_id: str,
        max_active_minutes: Any = None,
        max_idle_minutes: Any = None,
    ) -> None:
        """Persist user-configured activity alert settings for one circuit."""
        current = self._activity_alert_settings_for_config(None, circuit_id)
        max_minutes = _optional_positive_float_value(
            max_active_minutes,
            default=current.max_active_minutes,
        )
        max_idle = _optional_positive_float_value(
            max_idle_minutes,
            default=current.max_idle_minutes,
        )
        settings: dict[str, Any] = {}
        if max_minutes is not None:
            settings["max_active_minutes"] = max_minutes
        if max_idle is not None:
            settings["max_idle_minutes"] = max_idle
        self.store_data.activity_alert_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_billing_cycle_settings(
        self: Self,
        circuit_id: str,
        cycle_start_day: Any = None,
        budget_kwh: Any = None,
        budget_alert_ratio: Any = None,
    ) -> None:
        """Persist billing-cycle usage forecast settings for one circuit."""
        config = self._config_for_circuit(circuit_id)
        current = self._billing_cycle_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
            "budget_alert_ratio": _positive_float_value(
                budget_alert_ratio,
                default=current.budget_alert_ratio,
            ),
        }
        budget = _optional_positive_float_value(
            budget_kwh,
            default=current.budget_kwh,
        )
        if budget is not None:
            settings["budget_kwh"] = budget
        self.store_data.billing_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

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
        config = self._config_for_circuit(circuit_id)
        current = self._cost_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
        }
        default_rate = _optional_positive_float_value(
            default_rate_per_kwh,
            default=current.default_rate_per_kwh,
        )
        tou_rate = _optional_positive_float_value(
            tou_rate_per_kwh,
            default=current.tou_rate_per_kwh,
        )
        if default_rate is not None:
            settings["default_rate_per_kwh"] = default_rate
        if tou_rate is not None:
            settings["tou_rate_per_kwh"] = tou_rate
        settings["tou_start"] = str(tou_start or current.tou_start or "")
        settings["tou_end"] = str(tou_end or current.tou_end or "")
        weekdays = _weekday_csv_value(
            tou_weekdays,
            default=current.tou_weekdays,
        )
        if weekdays:
            settings["tou_weekdays"] = weekdays
        settings["tou_name"] = str(tou_name or current.tou_name or "Peak")
        self.store_data.cost_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_demand_settings(
        self: Self,
        circuit_id: str,
        window_minutes: Any = None,
        demand_limit_w: Any = None,
    ) -> None:
        """Persist rolling demand settings for one circuit."""
        config = self._config_for_circuit(circuit_id)
        current = self._demand_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_minutes": _positive_int_value(
                window_minutes,
                default=current.window_minutes,
            ),
        }
        limit_w = _optional_positive_float_value(
            demand_limit_w,
            default=current.demand_limit_w,
        )
        if limit_w is not None:
            settings["demand_limit_w"] = limit_w
        self.store_data.demand_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_capacity_settings(
        self: Self,
        circuit_id: str,
        breaker_amps: Any = None,
        warning_ratio: Any = None,
    ) -> None:
        """Persist circuit capacity settings for one circuit."""
        current = self._capacity_settings_for_config(circuit_id)
        settings: dict[str, Any] = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=current.warning_ratio,
            ),
        }
        capacity_amps = _optional_positive_float_value(
            breaker_amps,
            default=current.breaker_amps,
        )
        if capacity_amps is not None:
            settings["breaker_amps"] = capacity_amps
        self.store_data.capacity_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_leg_imbalance_settings(
        self: Self,
        circuit_id: str,
        warning_ratio: Any = None,
        minimum_total_power_w: Any = None,
    ) -> None:
        """Persist dual-phase leg imbalance thresholds for one circuit."""
        current = self.store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=_positive_float_value(
                    current.get("warning_ratio"),
                    default=DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
                ),
            ),
            "minimum_total_power_w": _nonnegative_float_value(
                minimum_total_power_w,
                default=_nonnegative_float_value(
                    current.get("minimum_total_power_w"),
                    default=DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                ),
            ),
        }
        self.store_data.leg_imbalance_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_metric_consistency_settings(
        self: Self,
        circuit_id: str,
        apparent_power_tolerance_percent: Any = None,
        power_factor_tolerance: Any = None,
        minimum_apparent_power_va: Any = None,
    ) -> None:
        """Persist W/VA/PF consistency thresholds for one circuit."""
        current = self.store_data.metric_consistency_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "apparent_power_tolerance_percent": _positive_float_value(
                apparent_power_tolerance_percent,
                default=_positive_float_value(
                    current.get("apparent_power_tolerance_percent"),
                    default=DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
                ),
            ),
            "power_factor_tolerance": _positive_float_value(
                power_factor_tolerance,
                default=_positive_float_value(
                    current.get("power_factor_tolerance"),
                    default=DEFAULT_POWER_FACTOR_TOLERANCE,
                ),
            ),
            "minimum_apparent_power_va": _nonnegative_float_value(
                minimum_apparent_power_va,
                default=_nonnegative_float_value(
                    current.get("minimum_apparent_power_va"),
                    default=DEFAULT_MIN_APPARENT_POWER_VA,
                ),
            ),
        }
        self.store_data.metric_consistency_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_mains_balance_settings(
        self: Self,
        circuit_id: str,
        negative_tolerance_w: Any = None,
    ) -> None:
        """Persist mains-minus-monitored balance thresholds."""
        current = self.store_data.balance_settings_by_circuit.get(circuit_id, {})
        settings = {
            "negative_tolerance_w": _nonnegative_float_value(
                negative_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("negative_tolerance_w"),
                    default=DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                ),
            ),
        }
        self.store_data.balance_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_solar_flow_settings(
        self: Self,
        circuit_id: str,
        export_tolerance_w: Any = None,
        solar_surplus_threshold_w: Any = None,
        high_solar_surplus_threshold_w: Any = None,
        flexible_load_running_threshold_w: Any = None,
    ) -> None:
        """Persist solar flow and flexible-load thresholds."""
        current = self.store_data.solar_flow_settings_by_circuit.get(circuit_id, {})
        settings = {
            "export_tolerance_w": _nonnegative_float_value(
                export_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("export_tolerance_w"),
                    default=EXPORT_TOLERANCE_W,
                ),
            ),
            "solar_surplus_threshold_w": _nonnegative_float_value(
                solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("solar_surplus_threshold_w"),
                    default=SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "high_solar_surplus_threshold_w": _nonnegative_float_value(
                high_solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("high_solar_surplus_threshold_w"),
                    default=HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "flexible_load_running_threshold_w": _nonnegative_float_value(
                flexible_load_running_threshold_w,
                default=_nonnegative_float_value(
                    current.get("flexible_load_running_threshold_w"),
                    default=FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                ),
            ),
        }
        self.store_data.solar_flow_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_set_standby_settings(
        self: Self,
        circuit_id: str,
        window_hours: Any = None,
        standby_threshold_w: Any = None,
        always_on_alert_w: Any = None,
    ) -> None:
        """Persist Always On and standby settings for one circuit."""
        config = self._config_for_circuit(circuit_id)
        current = self._standby_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_hours": _positive_int_value(
                window_hours,
                default=current.window_hours,
            ),
            "standby_threshold_w": _positive_float_value(
                standby_threshold_w,
                default=current.standby_threshold_w,
            ),
        }
        alert_w = _optional_positive_float_value(
            always_on_alert_w,
            default=current.always_on_alert_w,
        )
        if alert_w is not None:
            settings["always_on_alert_w"] = alert_w
        self.store_data.standby_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

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
        current = self._utility_comparison_settings_for_circuit(circuit_id)
        utility_entity = (
            current.utility_energy_entity
            if utility_energy_entity is None
            else str(utility_energy_entity).strip()
        )
        utility_statistic = (
            current.utility_statistic_id
            if utility_statistic_id is None
            else str(utility_statistic_id).strip()
        )
        source_type = (
            current.utility_source_type
            if utility_source_type is None
            else str(utility_source_type).strip()
        )
        statistic_period = (
            current.utility_statistic_period
            if utility_statistic_period is None
            else str(utility_statistic_period).strip()
        )
        measured_entities = _entity_id_tuple_value(
            measured_energy_entities,
            default=current.measured_energy_entities,
        )
        settings: dict[str, Any] = {
            "tolerance_percent": _nonnegative_float_value(
                tolerance_percent,
                default=current.tolerance_percent,
            ),
        }
        if utility_entity:
            settings["utility_energy_entity"] = utility_entity
        if utility_statistic:
            settings["utility_statistic_id"] = utility_statistic
        if source_type:
            settings["utility_source_type"] = source_type
        if statistic_period:
            settings["utility_statistic_period"] = statistic_period
        if measured_entities:
            settings["measured_energy_entities"] = list(measured_entities)
        self.store_data.utility_comparison_settings_by_circuit[circuit_id] = settings
        self._mark_store_dirty()
        now = self._now_fn()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

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
        self.last_exported_diagnostics = {
            "circuit_id": circuit_id,
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

    async def _async_create_or_update_lovelace_dashboard(
        self: Self,
        payload: Mapping[str, Any],
    ) -> tuple[str, str | None]:
        lovelace_data = _lovelace_data_from_hass(self.hass)
        collection = _lovelace_dashboard_item_value(
            lovelace_data,
            "dashboards_collection",
        )
        if collection is None and _lovelace_dashboards(lovelace_data) is not None:
            collection = await _async_load_lovelace_dashboards_collection(
                self.hass,
                lovelace_data,
            )
        if collection is None:
            return "unavailable", "lovelace_dashboard_collection_unavailable"

        items_method = getattr(collection, "async_items", None)
        create_method = getattr(collection, "async_create_item", None)
        update_method = getattr(collection, "async_update_item", None)
        if not callable(items_method) or not callable(create_method):
            return "unavailable", "lovelace_dashboard_collection_unavailable"

        items = await _async_lovelace_method_result(items_method())
        dashboard_config = _lovelace_dashboard_config(payload)
        storage_payload = _lovelace_dashboard_storage_payload(payload)
        existing = next(
            (
                item
                for item in items
                if _lovelace_dashboard_matches(item, payload)
            ),
            None,
        )
        if existing is not None:
            if not callable(update_method):
                return "unavailable", "dashboard_update_unavailable"
            item_id = _lovelace_dashboard_item_id(existing, payload)
            allowed_update_keys = {
                "icon",
                "require_admin",
                "show_in_sidebar",
                "title",
            }
            update_payload = {
                key: value
                for key, value in storage_payload.items()
                if key in allowed_update_keys
            }
            updated_item = await _async_lovelace_method_result(
                update_method(item_id, update_payload)
            )
            item = {
                **_lovelace_dashboard_item_mapping(existing),
                **(dict(updated_item) if isinstance(updated_item, Mapping) else {}),
                **update_payload,
            }
            if not await _async_save_lovelace_dashboard_config(
                self.hass,
                lovelace_data,
                item,
                dashboard_config,
                update=True,
            ):
                return "unavailable", "dashboard_config_save_unavailable"
            return "updated", None

        created_item = await _async_lovelace_method_result(
            create_method(dict(storage_payload))
        )
        item = created_item if isinstance(created_item, Mapping) else storage_payload
        if not await _async_save_lovelace_dashboard_config(
            self.hass,
            lovelace_data,
            item,
            dashboard_config,
            update=False,
        ):
            return "unavailable", "dashboard_config_save_unavailable"
        return "created", None

    async def _async_remove_lovelace_dashboard(self: Self) -> tuple[str, str | None]:
        lovelace_data = _lovelace_data_from_hass(self.hass)
        collection = _lovelace_dashboard_item_value(
            lovelace_data,
            "dashboards_collection",
        )
        if collection is None and _lovelace_dashboards(lovelace_data) is not None:
            collection = await _async_load_lovelace_dashboards_collection(
                self.hass,
                lovelace_data,
            )

        payload = {"url_path": DASHBOARD_URL_PATH}
        if collection is not None:
            items_method = getattr(collection, "async_items", None)
            delete_method = getattr(collection, "async_delete_item", None)
            if not callable(items_method) or not callable(delete_method):
                return "unavailable", "lovelace_dashboard_delete_unavailable"

            items = await _async_lovelace_method_result(items_method())
            existing = next(
                (
                    item
                    for item in items
                    if _lovelace_dashboard_matches(item, payload)
                ),
                None,
            )
            if existing is None:
                if await _async_delete_lovelace_dashboard_config(
                    self.hass,
                    lovelace_data,
                    DASHBOARD_URL_PATH,
                ):
                    return "deleted", None
                return "missing", None

            item_id = _lovelace_dashboard_item_id(existing, payload)
            if not item_id:
                return "unavailable", "lovelace_dashboard_delete_unavailable"
            await _async_lovelace_method_result(delete_method(item_id))
            await _async_delete_lovelace_dashboard_config(
                self.hass,
                lovelace_data,
                DASHBOARD_URL_PATH,
            )
            return "deleted", None

        if await _async_delete_lovelace_dashboard_config(
            self.hass,
            lovelace_data,
            DASHBOARD_URL_PATH,
        ):
            return "deleted", None
        return "missing", None

    async def async_label_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        label: str,
    ) -> None:
        """Persist a user-confirmed label for a NILM signature."""
        signatures = self.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["user_label"] = label
                self._mark_store_dirty()
                self._refresh_nilm_state(circuit_id)
                self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
                self.async_set_updated_data(self.state)
                await self._async_save_store(self._now_fn())
                return
        signatures.append({"signature_id": signature_id, "user_label": label})
        self._mark_store_dirty()
        self._refresh_nilm_state(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

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
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        start_dt = _nilm_label_interval_datetime(start, "start")
        end_dt = _nilm_label_interval_datetime(end, "end")
        if end_dt <= start_dt:
            raise ValueError("NILM label interval end must be after start.")

        now_dt = self._now_fn()
        now = now_dt.isoformat()
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        interval_id_text = str(interval_id or "").strip() or _nilm_label_interval_id(
            circuit_id,
            start_iso,
            end_iso,
            label_text,
        )
        intervals = self.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        existing = next(
            (
                interval
                for interval in intervals
                if interval.get("interval_id") == interval_id_text
            ),
            None,
        )
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        payload: dict[str, Any] = {
            "interval_id": interval_id_text,
            "mains_circuit_id": circuit_id,
            "appliance_id": str(appliance_id or label_text).strip(),
            "label": label_text,
            "start": start_iso,
            "end": end_iso,
            "source": str(source or "manual").strip() or "manual",
            "confidence": max(min(confidence_value, 1.0), 0.0),
            "mains_entity_id": str(mains_entity_id or "").strip(),
            "created_at": str(existing.get("created_at") if existing else now),
            "updated_at": now,
        }
        ground_truth_text = str(ground_truth_entity_id or "").strip()
        if ground_truth_text:
            payload["ground_truth_entity_id"] = ground_truth_text
        if validation_start is not None and validation_end is not None:
            validation_start_dt = _nilm_label_interval_datetime(
                validation_start,
                "validation_start",
            )
            validation_end_dt = _nilm_label_interval_datetime(
                validation_end,
                "validation_end",
            )
            if validation_end_dt <= validation_start_dt:
                raise ValueError("NILM validation end must be after start.")
            payload["validation_start"] = validation_start_dt.isoformat()
            payload["validation_end"] = validation_end_dt.isoformat()

        if existing is None:
            intervals.append(payload)
        else:
            existing.clear()
            existing.update(payload)
        del intervals[:-NILM_LABEL_INTERVAL_MAX_ITEMS_PER_CIRCUIT]

        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now_dt)
        return dict(payload)

    async def async_delete_nilm_label_interval(
        self: Self,
        circuit_id: str,
        interval_id: str,
    ) -> bool:
        """Delete a user-labeled NILM graph interval."""
        interval_id_text = str(interval_id or "").strip()
        if not interval_id_text:
            raise ValueError("Missing interval_id.")
        intervals = self.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        remaining = [
            interval
            for interval in intervals
            if interval.get("interval_id") != interval_id_text
        ]
        if len(remaining) == len(intervals):
            return False
        self.store_data.nilm_label_intervals_by_circuit[circuit_id] = remaining
        now_dt = self._now_fn()
        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now_dt)
        return True

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
        signature = self._nilm_signature_for_review(circuit_id, signature_id)
        fingerprint = _nilm_signature_fingerprint_value(signature, signature_id)
        assignment = self._upsert_nilm_assignment(
            circuit_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            signature_fingerprint=fingerprint,
            lifecycle_state="assigned",
            confidence=signature.get("confidence", 1.0),
        )
        signature["assignment_id"] = assignment["assignment_id"]
        signature["review_state"] = "assigned"
        signature["user_label"] = assignment["display_name"]
        signature.pop("ignored", None)
        self.ignored_nilm_signatures.discard((circuit_id, signature_id))
        self._remove_nilm_signature_from_other_assignments(
            circuit_id,
            fingerprint,
            assignment["assignment_id"],
        )
        self._mark_store_dirty()
        self._refresh_nilm_state(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())
        return dict(assignment)

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
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            raise ValueError("Missing session_id.")
        assignment = self._upsert_nilm_assignment(
            circuit_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            signature_fingerprint=signature_fingerprint,
            session_id=session_id_text,
            lifecycle_state="assigned",
        )
        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())
        return dict(assignment)

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
        interval_id_text = str(interval_id or "").strip()
        intervals = self.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        interval = next(
            (
                item
                for item in intervals
                if item.get("interval_id") == interval_id_text
            ),
            None,
        )
        if interval is None:
            raise ValueError(f"Unknown interval_id '{interval_id_text}'.")
        assignment = self._upsert_nilm_assignment(
            circuit_id,
            label=label or str(interval.get("label") or ""),
            appliance_id=appliance_id or str(interval.get("appliance_id") or ""),
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            label_interval_id=interval_id_text,
            lifecycle_state="assigned",
            confidence=interval.get("confidence", 1.0),
        )
        interval["assignment_id"] = assignment["assignment_id"]
        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())
        return dict(assignment)

    async def async_validate_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session matched its appliance assignment."""
        return await self._async_record_nilm_session_validation(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
            correct=True,
        )

    async def async_reject_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session did not match its appliance assignment."""
        return await self._async_record_nilm_session_validation(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
            correct=False,
        )

    async def async_validate_nilm_assignment_history(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Confirm assigned NILM sessions that overlap ground-truth intervals."""
        assignment = self._nilm_assignment_for_id(circuit_id, assignment_id)
        intervals = [
            interval
            for interval in self.store_data.nilm_label_intervals_by_circuit.get(
                circuit_id,
                (),
            )
            if isinstance(interval, Mapping)
            and str(interval.get("ground_truth_entity_id") or "").strip()
            and _nilm_assignment_interval_matches(interval, assignment)
        ]
        if not intervals:
            raise ValueError(
                "No matching ground-truth NILM label intervals were found for "
                "this assignment."
            )

        assignment_id_text = str(assignment.get("assignment_id") or "").strip()
        assignment_session_ids = set(_clean_string_list(assignment.get("session_ids")))
        matched_session_ids: list[str] = []
        conflicting_session_ids: list[str] = []
        matched_interval_ids: set[int] = set()
        power_errors: list[float] = []
        energy_errors: list[float] = []
        for session in self.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        ):
            if not isinstance(session, Mapping):
                continue
            session_id = str(session.get("session_id") or "").strip()
            if not session_id:
                continue
            session_assignment_id = str(session.get("assignment_id") or "").strip()
            if (
                session_assignment_id != assignment_id_text
                and session_id not in assignment_session_ids
            ):
                continue
            if not session.get("end"):
                continue
            overlapping_intervals = [
                interval
                for interval in intervals
                if _nilm_overlap_seconds(interval, session) > 0
            ]
            if overlapping_intervals:
                _append_unique(matched_session_ids, session_id)
                session_power = _float_or_none(session.get("median_power_w"))
                session_energy = _float_or_none(session.get("estimated_energy_kwh"))
                for interval in overlapping_intervals:
                    matched_interval_ids.add(id(interval))
                    interval_power = _float_or_none(interval.get("median_power_w"))
                    interval_energy = _float_or_none(
                        interval.get("estimated_energy_kwh"),
                    )
                    if session_power is not None and interval_power is not None:
                        power_errors.append(abs(session_power - interval_power))
                    if session_energy is not None and interval_energy is not None:
                        energy_errors.append(abs(session_energy - interval_energy))
            elif any(
                _nilm_validation_coverage_overlap_seconds(interval, session) > 0
                for interval in intervals
            ):
                _append_unique(conflicting_session_ids, session_id)

        confirmed = _clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = _clean_string_list(assignment.get("rejected_session_ids"))
        newly_confirmed = [
            session_id
            for session_id in matched_session_ids
            if session_id not in confirmed
        ]
        newly_rejected = [
            session_id
            for session_id in conflicting_session_ids
            if session_id not in rejected
        ]
        if not newly_confirmed and not newly_rejected:
            raise ValueError(
                "No matching ground-truth NILM sessions were found for this "
                "assignment."
            )

        for session_id in newly_confirmed:
            _append_unique(confirmed, session_id)
            _append_unique(assignment.setdefault("session_ids", []), session_id)
        rejected = [
            session_id for session_id in rejected if session_id not in newly_confirmed
        ]
        for session_id in newly_rejected:
            _append_unique(rejected, session_id)
        confirmed = [
            session_id for session_id in confirmed if session_id not in newly_rejected
        ]

        now_dt = self._now_fn()
        now = now_dt.isoformat()
        current_confidence = _nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        confidence = min(
            1.0,
            round(current_confidence + (0.05 * len(newly_confirmed)), 3),
        )
        if newly_rejected:
            confidence = max(0.0, round(confidence - (0.15 * len(newly_rejected)), 3))
        assignment["confidence"] = confidence
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            _clean_string_list(assignment.get("adjusted_session_ids")),
        )
        ground_truth_interval_count = len(intervals)
        matched_ground_truth_count = len(matched_interval_ids)
        missed_ground_truth_count = max(
            ground_truth_interval_count - matched_ground_truth_count,
            0,
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["ground_truth_interval_count"] = ground_truth_interval_count
        assignment["matched_ground_truth_count"] = matched_ground_truth_count
        assignment["missed_ground_truth_count"] = missed_ground_truth_count
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["false_negative_rate"] = (
            round(missed_ground_truth_count / ground_truth_interval_count, 3)
            if ground_truth_interval_count
            else 0.0
        )
        assignment["median_power_error"] = (
            round(median(power_errors), 3) if power_errors else None
        )
        assignment["energy_estimate_error"] = (
            round(median(energy_errors), 3) if energy_errors else None
        )
        validation_starts: list[datetime] = []
        validation_ends: list[datetime] = []
        for interval in intervals:
            validation_start = _datetime_or_none(
                interval.get("validation_start") or interval.get("start"),
            )
            validation_end = _datetime_or_none(
                interval.get("validation_end") or interval.get("end"),
            )
            if validation_start is not None:
                validation_starts.append(validation_start)
            if validation_end is not None:
                validation_ends.append(validation_end)
        if validation_starts and validation_ends:
            assignment["validation_window_start"] = min(validation_starts).isoformat()
            assignment["validation_window_end"] = max(validation_ends).isoformat()
        if newly_rejected and assignment.get("lifecycle_state") != "retired":
            assignment["lifecycle_state"] = "conflict"
        elif assignment.get("lifecycle_state") not in {"published", "retired"}:
            assignment["lifecycle_state"] = "validated"
        assignment["last_validation"] = (
            "direct_meter_conflict" if newly_rejected else "history"
        )
        assignment["last_validated_at"] = now
        if newly_rejected:
            assignment["last_rejected_at"] = now
        assignment["updated_at"] = now
        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now_dt)
        return dict(assignment)

    async def async_rename_nilm_appliance(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        """Rename a NILM appliance assignment without changing its stable ID."""
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        assignment = self._nilm_assignment_for_id(circuit_id, assignment_id)
        assignment["display_name"] = label_text
        assignment["updated_at"] = self._now_fn().isoformat()
        await self._async_save_nilm_assignment_change()
        return dict(assignment)

    async def async_change_nilm_appliance_profile(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        appliance_profile: str,
    ) -> dict[str, Any]:
        """Change the appliance profile hint for a NILM assignment."""
        profile_text = str(appliance_profile or "").strip()
        if not profile_text:
            raise ValueError("Missing appliance_profile.")
        assignment = self._nilm_assignment_for_id(circuit_id, assignment_id)
        assignment["appliance_profile"] = profile_text
        assignment["updated_at"] = self._now_fn().isoformat()
        await self._async_save_nilm_assignment_change()
        return dict(assignment)

    async def async_merge_nilm_assignments(
        self: Self,
        circuit_id: str,
        source_assignment_id: str,
        target_assignment_id: str,
    ) -> dict[str, Any]:
        """Merge one NILM appliance assignment into another."""
        source_id = str(source_assignment_id or "").strip()
        target_id = str(target_assignment_id or "").strip()
        if not source_id or not target_id:
            raise ValueError("Missing source_assignment_id or target_assignment_id.")
        if source_id == target_id:
            raise ValueError(
                "source_assignment_id and target_assignment_id must be different."
            )
        source = self._nilm_assignment_for_id(circuit_id, source_id)
        target = self._nilm_assignment_for_id(circuit_id, target_id)
        for key in (
            "signature_fingerprints",
            "session_ids",
            "label_interval_ids",
            "confirmed_session_ids",
            "rejected_session_ids",
        ):
            values = target.setdefault(key, [])
            for value in _clean_string_list(source.get(key)):
                _append_unique(values, value)
        target["confirmed_sessions"] = len(
            _clean_string_list(target.get("confirmed_session_ids"))
        )
        target["rejected_sessions"] = len(
            _clean_string_list(target.get("rejected_session_ids"))
        )
        target["confidence"] = max(
            _nonnegative_float_value(target.get("confidence"), default=0.0),
            _nonnegative_float_value(source.get("confidence"), default=0.0),
        )
        target["publish_entities"] = bool(
            target.get("publish_entities") or source.get("publish_entities")
        )
        target["created_device"] = bool(
            target.get("created_device") or source.get("created_device")
        )
        if source.get("lifecycle_state") == "published":
            target["lifecycle_state"] = "published"
        target["updated_at"] = self._now_fn().isoformat()

        assignments = self.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            [],
        )
        self.store_data.nilm_appliance_assignments_by_circuit[circuit_id] = [
            assignment
            for assignment in assignments
            if assignment.get("assignment_id") != source_id
        ]
        for signature in self.store_data.nilm_signatures.get(circuit_id, []):
            if signature.get("assignment_id") == source_id:
                signature["assignment_id"] = target_id
        for interval in self.store_data.nilm_label_intervals_by_circuit.get(
            circuit_id,
            [],
        ):
            if interval.get("assignment_id") == source_id:
                interval["assignment_id"] = target_id
        await self._async_save_nilm_assignment_change()
        return dict(target)

    async def _async_record_nilm_session_validation(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None,
        correct: bool,
    ) -> dict[str, Any]:
        session_id_text = str(session_id or "").strip()
        assignment = self._nilm_assignment_for_session(
            circuit_id,
            session_id_text,
            assignment_id=assignment_id,
        )
        _append_unique(assignment.setdefault("session_ids", []), session_id_text)
        confirmed = _clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = _clean_string_list(assignment.get("rejected_session_ids"))
        current_confidence = _nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        now_dt = self._now_fn()
        now = now_dt.isoformat()
        if correct:
            already_confirmed = session_id_text in confirmed
            _append_unique(confirmed, session_id_text)
            rejected = [value for value in rejected if value != session_id_text]
            if not already_confirmed:
                assignment["confidence"] = min(
                    1.0,
                    round(current_confidence + 0.05, 3),
                )
            if assignment.get("lifecycle_state") not in {"published", "retired"}:
                assignment["lifecycle_state"] = "validated"
            assignment["last_validation"] = "correct"
            assignment["last_validated_at"] = now
        else:
            already_rejected = session_id_text in rejected
            _append_unique(rejected, session_id_text)
            confirmed = [value for value in confirmed if value != session_id_text]
            if not already_rejected:
                assignment["confidence"] = max(
                    0.0,
                    round(current_confidence - 0.15, 3),
                )
            if assignment.get("lifecycle_state") != "retired":
                assignment["lifecycle_state"] = "needs_validation"
            assignment["last_validation"] = "wrong_appliance"
            assignment["last_rejected_at"] = now
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            _clean_string_list(assignment.get("adjusted_session_ids")),
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["false_negative_rate"] = _nonnegative_float_value(
            assignment.get("false_negative_rate"),
            default=0.0,
        )
        assignment["median_power_error"] = _round_optional_number(
            assignment.get("median_power_error"),
        )
        assignment["energy_estimate_error"] = _round_optional_number(
            assignment.get("energy_estimate_error"),
        )
        assignment["updated_at"] = now
        self._mark_store_dirty()
        self.async_set_updated_data(self.state)
        await self._async_save_store(now_dt)
        return dict(assignment)

    def _upsert_nilm_assignment(
        self: Self,
        circuit_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
        signature_fingerprint: Any = None,
        session_id: str | None = None,
        label_interval_id: str | None = None,
        lifecycle_state: str = "assigned",
        confidence: Any = 1.0,
    ) -> dict[str, Any]:
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        appliance_id_text = (
            str(appliance_id or "").strip()
            or _nilm_assignment_appliance_id(label_text)
        )
        assignments = (
            self.store_data.nilm_appliance_assignments_by_circuit.setdefault(
                circuit_id,
                [],
            )
        )
        assignment_id_text = str(assignment_id or "").strip()
        assignment = next(
            (
                item
                for item in assignments
                if (
                    (
                        assignment_id_text
                        and item.get("assignment_id") == assignment_id_text
                    )
                    or (
                        not assignment_id_text
                        and item.get("appliance_id") == appliance_id_text
                    )
                )
            ),
            None,
        )
        now = self._now_fn().isoformat()
        if assignment is None:
            assignment = {
                "assignment_id": assignment_id_text
                or _nilm_assignment_id(circuit_id, appliance_id_text),
                "appliance_id": appliance_id_text,
                "display_name": label_text,
                "appliance_profile": str(appliance_profile or "").strip() or None,
                "mains_circuit_id": circuit_id,
                "signature_fingerprints": [],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": lifecycle_state,
                "confidence": 0.0,
                "created_at": now,
                "updated_at": now,
                "created_device": False,
                "publish_entities": False,
            }
            assignments.append(assignment)
        else:
            assignments[:] = [item for item in assignments if item is not assignment]
            assignments.append(assignment)
            assignment["display_name"] = label_text
            if appliance_profile:
                assignment["appliance_profile"] = str(appliance_profile).strip()
            assignment["lifecycle_state"] = lifecycle_state
            assignment["updated_at"] = now

        _append_unique(
            assignment.setdefault("signature_fingerprints", []),
            signature_fingerprint,
        )
        _append_unique(assignment.setdefault("session_ids", []), session_id)
        _append_unique(
            assignment.setdefault("label_interval_ids", []),
            label_interval_id,
        )
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        assignment["confidence"] = max(
            float(assignment.get("confidence") or 0.0),
            max(min(confidence_value, 1.0), 0.0),
        )
        del assignments[:-NILM_ASSIGNMENT_MAX_ITEMS_PER_CIRCUIT]
        return assignment

    def _nilm_assignment_for_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            raise ValueError("Missing session_id.")
        assignment_id_text = str(assignment_id or "").strip()
        if assignment_id_text:
            assignment = self._nilm_assignment_for_id(circuit_id, assignment_id_text)
            _append_unique(assignment.setdefault("session_ids", []), session_id_text)
            return assignment
        assignments = self.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            [],
        )
        for assignment in assignments:
            if session_id_text in assignment.get("session_ids", ()):
                return assignment
        raise ValueError(
            f"Assign NILM session '{session_id_text}' to an appliance before "
            "validating it."
        )

    def _remove_nilm_signature_from_other_assignments(
        self: Self,
        circuit_id: str,
        signature_fingerprint: str,
        assignment_id: str,
    ) -> None:
        if not signature_fingerprint:
            return
        for assignment in self.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            (),
        ):
            if assignment.get("assignment_id") == assignment_id:
                continue
            fingerprints = assignment.get("signature_fingerprints")
            if not isinstance(fingerprints, list):
                continue
            assignment["signature_fingerprints"] = [
                value for value in fingerprints if value != signature_fingerprint
            ]

    def _nilm_assignment_for_signature(
        self: Self,
        circuit_id: str,
        signature_fingerprint: str,
    ) -> dict[str, Any] | None:
        assignments = self.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            [],
        )
        return next(
            (
                assignment
                for assignment in assignments
                if signature_fingerprint
                in assignment.get("signature_fingerprints", ())
            ),
            None,
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

    def _nilm_assignment_for_id(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        return self.nilm_controller.assignment_for_id(circuit_id, assignment_id)

    async def _async_save_nilm_assignment_change(self: Self) -> None:
        await self.nilm_controller.async_save_assignment_change()

    async def async_ignore_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an ignored NILM signature marker."""
        self.ignored_nilm_signatures.add((circuit_id, signature_id))
        signatures = self.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["ignored"] = True
                assignment = self._upsert_nilm_assignment(
                    circuit_id,
                    label=_nilm_signature_assignment_label(signature, signature_id),
                    signature_fingerprint=_nilm_signature_fingerprint_value(
                        signature,
                        signature_id,
                    ),
                    lifecycle_state="ignored",
                    confidence=signature.get("confidence", 1.0),
                )
                signature["assignment_id"] = assignment["assignment_id"]
                self._mark_store_dirty()
                self._refresh_nilm_state(circuit_id)
                self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
                self.async_set_updated_data(self.state)
                await self._async_save_store(self._now_fn())
                return
        signature = {"signature_id": signature_id, "ignored": True}
        assignment = self._upsert_nilm_assignment(
            circuit_id,
            label=signature_id,
            signature_fingerprint=signature_id,
            lifecycle_state="ignored",
        )
        signature["assignment_id"] = assignment["assignment_id"]
        signatures.append(signature)
        self._mark_store_dirty()
        self._refresh_nilm_state(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

    async def async_mark_nilm_signature_expected(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an expected NILM signature review decision."""
        signature = self._nilm_signature_for_review(circuit_id, signature_id)
        signature["expected"] = True
        signature["review_state"] = "expected"
        assignment = self._upsert_nilm_assignment(
            circuit_id,
            label=_nilm_signature_assignment_label(signature, signature_id),
            signature_fingerprint=_nilm_signature_fingerprint_value(
                signature,
                signature_id,
            ),
            lifecycle_state="expected",
            confidence=signature.get("confidence", 1.0),
        )
        signature["assignment_id"] = assignment["assignment_id"]
        self._mark_store_dirty()
        self._refresh_nilm_state(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

    async def async_merge_nilm_signatures(
        self: Self,
        circuit_id: str,
        source_signature_id: str,
        target_signature_id: str,
    ) -> None:
        """Persist that one NILM signature should be treated as another."""
        target = self._nilm_signature_for_review(circuit_id, target_signature_id)
        source = self._nilm_signature_for_review(circuit_id, source_signature_id)
        source["review_state"] = "merged"
        source["merged_into"] = target_signature_id
        if target.get("feedback_fingerprint"):
            source["merged_into_fingerprint"] = target["feedback_fingerprint"]
        target_fingerprint = _nilm_signature_fingerprint_value(
            target,
            target_signature_id,
        )
        source_fingerprint = _nilm_signature_fingerprint_value(
            source,
            source_signature_id,
        )
        assignment = self._nilm_assignment_for_signature(
            circuit_id,
            target_fingerprint,
        ) or self._nilm_assignment_for_signature(circuit_id, source_fingerprint)
        if assignment is not None:
            _append_unique(
                assignment.setdefault("signature_fingerprints", []),
                source_fingerprint,
            )
            assignment["updated_at"] = self._now_fn().isoformat()
            source["assignment_id"] = assignment["assignment_id"]
            target["assignment_id"] = assignment["assignment_id"]
            self._remove_nilm_signature_from_other_assignments(
                circuit_id,
                source_fingerprint,
                assignment["assignment_id"],
            )
        self._mark_store_dirty()
        self._refresh_nilm_state(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

    def has_circuit(self: Self, circuit_id: str) -> bool:
        """Return whether this coordinator owns a circuit id."""
        return any(config.circuit_id == circuit_id for config in self.circuit_configs)

    def _hydrate_state_from_store(self: Self) -> None:
        for circuit_id, maintenance in self.store_data.maintenance_by_circuit.items():
            if maintenance.get("active") is True:
                self.paused_circuits.add(circuit_id)
        for circuit_id, signatures in self.store_data.nilm_signatures.items():
            for signature in signatures:
                if signature.get("ignored") is True:
                    self.ignored_nilm_signatures.add(
                        (circuit_id, str(signature.get("signature_id", "")))
                    )
            self._refresh_nilm_state(circuit_id)
        self.state.weather_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in (
                self.store_data.weather_context_by_circuit.items()
            )
        }
        self.state.rain_pump_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in (
                self.store_data.rain_pump_context_by_circuit.items()
            )
        }
        self.state.water_flow_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in (
                self.store_data.water_flow_context_by_circuit.items()
            )
        }
        self.state.water_context_history_by_circuit = {
            circuit_id: [dict(sample) for sample in samples]
            for circuit_id, samples in (
                self.store_data.water_context_history_by_circuit.items()
            )
        }
        self._refresh_all_ux_state(self._now_fn())
        self._refresh_settings_recommendation_state(self._now_fn())

    def _refresh_all_ux_state(self: Self, now: datetime) -> None:
        for config in self.circuit_configs:
            self._refresh_ux_state(config, None, now)

    def _refresh_ux_state_for_circuit(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        config = self._config_for_circuit(circuit_id)
        if config is not None:
            self._refresh_ux_state(config, None, now)

    def _refresh_ux_state(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample | None,
        now: datetime,
    ) -> None:
        circuit_id = config.circuit_id
        checklist = data_quality_checklist(config, sample)
        if (
            sample is None
            and circuit_id in self.state.data_quality_checklist_by_circuit
        ):
            checklist = dict(self.state.data_quality_checklist_by_circuit[circuit_id])
        self.state.data_quality_checklist_by_circuit[circuit_id] = checklist
        dashboard_readiness = evaluate_energy_dashboard_readiness(
            config,
            self._source_states_for(config, now),
        )
        self.state.energy_dashboard_status_by_circuit[circuit_id] = (
            dashboard_readiness.status
        )
        self.state.energy_dashboard_evidence_by_circuit[circuit_id] = (
            readiness_payload(dashboard_readiness)
        )

        learning = self.state.learning_by_circuit.get(circuit_id, True)
        suppression_reason = self._suppression_reason(circuit_id, learning)
        progress = learning_progress(
            config,
            events=self.store_data.events,
            baselines=self.store_data.baselines,
            baseline_buffer_counts={
                key: len(values) for key, values in self._baseline_values.items()
            },
            now=now,
            learning=learning,
            suppression_reason=suppression_reason,
        )
        self.state.learning_progress_by_circuit[circuit_id] = progress
        merge_gap_seconds = resolve_operating_detection_from_settings(
            config,
            getattr(
                self.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_id, {}),
        ).profile.merge_gap_seconds
        cycle_summary = summarize_circuit_cycles(
            self.store_data.events,
            circuit_id=circuit_id,
            now=now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=self._ha_time_zone(),
        )
        self.state.run_cycle_count_by_circuit[circuit_id] = (
            cycle_summary.start_count
        )
        self.state.run_cycle_runtime_seconds_by_circuit[circuit_id] = (
            cycle_summary.runtime_seconds
        )
        self.state.run_cycle_duty_cycle_by_circuit[circuit_id] = (
            cycle_summary.duty_cycle_percent
        )
        self.state.run_cycle_status_by_circuit[circuit_id] = cycle_summary.status
        self.state.run_cycle_evidence_by_circuit[circuit_id] = cycle_summary_payload(
            cycle_summary
        )
        self._refresh_weather_context_state(config, now)
        self._refresh_water_context_state(config, now)

        maintenance = dict(self.store_data.maintenance_by_circuit.get(circuit_id, {}))
        maintenance.setdefault("active", circuit_id in self.paused_circuits)
        self.state.maintenance_by_circuit[circuit_id] = maintenance
        self.state.sensitivity_by_circuit[circuit_id] = self._sensitivity_for_circuit(
            circuit_id
        )
        self._refresh_alert_evidence_state(circuit_id)
        self._refresh_recent_activity_state(circuit_id, now)
        self._refresh_nilm_state(circuit_id)

        status, summary = health_summary(
            data_quality_problem=bool(
                self.state.data_quality_by_circuit.get(circuit_id)
            ),
            paused=bool(maintenance.get("active"))
            or circuit_id in self.paused_circuits,
            active_alerts=bool(self.state.active_alerts_by_circuit.get(circuit_id)),
            observations=bool(
                self.state.recent_observations_by_circuit.get(circuit_id)
            ),
            nilm_review_count=len(
                self.state.nilm_review_by_circuit.get(circuit_id, [])
            ),
            mixed=(
                config.mode is CircuitMode.MIXED
                or config.appliance_profile is ApplianceProfile.MIXED
            ),
            learning=learning,
        )
        self.state.health_status_by_circuit[circuit_id] = status
        self.state.health_summary_by_circuit[circuit_id] = summary
        self.state.readiness_by_circuit[circuit_id] = {
            **progress,
            "required_metric_coverage": checklist["required_metric_coverage"],
            "optional_metric_coverage": checklist["optional_metric_coverage"],
            "health_status": status,
            "health_summary": summary,
        }

    def _suppression_reason(self: Self, circuit_id: str, learning: bool) -> str | None:
        if self.state.data_quality_by_circuit.get(circuit_id):
            return "data_quality"
        if circuit_id in self.paused_circuits:
            return "paused"
        if learning:
            return "learning"
        return None

    def _refresh_alert_evidence_state(self: Self, circuit_id: str) -> None:
        alert = self._latest_alert_for_circuit(circuit_id)
        if alert is None:
            self.state.alert_evidence_by_circuit.pop(circuit_id, None)
            return
        self.state.alert_evidence_by_circuit[circuit_id] = alert_evidence_detail(
            alert,
            config=self._config_for_circuit(circuit_id),
        )

    def _refresh_recent_activity_state(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        timeline = build_recent_activity_timeline(
            circuit_id=circuit_id,
            events=self.store_data.events,
            alerts=self.store_data.alerts,
            observations=self.state.recent_observations_by_circuit.get(
                circuit_id,
                [],
            ),
            now=now,
        )
        self.state.recent_activity_by_circuit[circuit_id] = timeline.latest_title
        self.state.recent_activity_count_by_circuit[circuit_id] = (
            timeline.total_count
        )
        self.state.recent_activity_timeline_by_circuit[circuit_id] = (
            timeline_payload(timeline)
        )

    def _refresh_weather_context_state(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        circuit_id = config.circuit_id
        if config.appliance_profile not in HVAC_WEATHER_CONTEXT_PROFILES:
            self._clear_weather_context_state(circuit_id)
            return

        outdoor_entity = self._outdoor_temperature_entity()
        if not outdoor_entity:
            self._clear_weather_context_state(circuit_id)
            return

        outdoor_temperature_reading = self._temperature_reading_for_entity(
            outdoor_entity,
        )
        outdoor_temperature = (
            outdoor_temperature_reading["temperature_f"]
            if outdoor_temperature_reading is not None
            else None
        )
        runtime_minutes = (
            self.state.run_cycle_runtime_seconds_by_circuit.get(circuit_id, 0.0)
            / 60.0
        )
        duty_cycle_percent = self.state.run_cycle_duty_cycle_by_circuit.get(
            circuit_id,
            0.0,
        )
        self._seed_demo_weather_context_history(
            config,
            now,
            outdoor_temperature=outdoor_temperature,
        )
        history = self._weather_context_history_samples(circuit_id, now)
        evidence = evaluate_weather_context(
            outdoor_temperature=outdoor_temperature,
            current_runtime_minutes=runtime_minutes,
            current_duty_cycle_percent=duty_cycle_percent,
            history=history,
            mode=_weather_context_mode(config),
            display_temperature=(
                outdoor_temperature_reading["display_temperature"]
                if outdoor_temperature_reading is not None
                else None
            ),
            display_temperature_unit=(
                outdoor_temperature_reading["display_unit"]
                if outdoor_temperature_reading is not None
                else "°F"
            ),
            observed_at=now,
            time_zone=self._ha_time_zone(),
        )
        if outdoor_temperature_reading is not None:
            evidence["temperature_source_entity"] = outdoor_entity
            evidence["temperature_source_unit"] = outdoor_temperature_reading[
                "source_unit"
            ]
        if self.store_data.weather_context_by_circuit.get(circuit_id) != evidence:
            self.store_data.weather_context_by_circuit[circuit_id] = evidence
            self._mark_store_dirty()
        self.state.weather_context_by_circuit[circuit_id] = dict(evidence)
        if outdoor_temperature is not None:
            changed = self._append_weather_context_history(
                circuit_id,
                now,
                temperature=outdoor_temperature,
                runtime_minutes=runtime_minutes,
                duty_cycle_percent=duty_cycle_percent,
            )
            if changed:
                self._mark_store_dirty()

    def _refresh_water_context_state(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        circuit_id = config.circuit_id
        advanced_settings = self._advanced_settings_for_circuit(circuit_id)
        profile = config.appliance_profile
        changed = False

        if profile in PUMP_WATER_CONTEXT_PROFILES and bool(
            advanced_settings.get(
                CONF_RAIN_PUMP_CORRELATION_ENABLED,
                DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
            )
        ):
            rain_evidence = self._rain_pump_context_evidence(
                config,
                advanced_settings,
                now,
            )
            if self.store_data.rain_pump_context_by_circuit.get(circuit_id) != (
                rain_evidence
            ):
                self.store_data.rain_pump_context_by_circuit[circuit_id] = (
                    rain_evidence
                )
                changed = True
            self.state.rain_pump_context_by_circuit[circuit_id] = dict(
                rain_evidence
            )
        else:
            changed = self._clear_rain_pump_context_state(circuit_id) or changed

        if profile in FLOW_WATER_CONTEXT_PROFILES and bool(
            advanced_settings.get(
                CONF_WATER_FLOW_CORRELATION_ENABLED,
                DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
            )
        ):
            flow_evidence = self._water_flow_context_evidence(
                config,
                advanced_settings,
                now,
            )
            if self.store_data.water_flow_context_by_circuit.get(circuit_id) != (
                flow_evidence
            ):
                self.store_data.water_flow_context_by_circuit[circuit_id] = (
                    flow_evidence
                )
                changed = True
            self.state.water_flow_context_by_circuit[circuit_id] = dict(
                flow_evidence
            )
        else:
            changed = self._clear_water_flow_context_state(circuit_id) or changed

        if profile in PUMP_WATER_CONTEXT_PROFILES | FLOW_WATER_CONTEXT_PROFILES:
            if self._append_water_context_history(circuit_id, now):
                changed = True
        else:
            changed = self._clear_water_context_history(circuit_id) or changed

        if changed:
            self._mark_store_dirty()

    def _observe_water_context(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        result = self._water_context_alert_processor.process(
            config,
            self._build_processing_context(now),
        )
        return result.alerts[0] if result.alerts else None

    def _rain_pump_context_evidence(
        self: Self,
        config: CircuitConfig,
        advanced_settings: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        rain_entity = self._configured_context_entity(CONF_RAIN_SENSOR_ENTITY)
        rain_intensity_entity = self._configured_context_entity(
            CONF_RAIN_INTENSITY_ENTITY
        )
        rain_active = self._binary_entity_active(rain_entity)
        rain_intensity = self._numeric_entity_value(rain_intensity_entity)
        rain_intensity_unit = self._entity_unit_of_measurement(rain_intensity_entity)
        compressor_context = self._hvac_compressor_context()
        runtime_minutes = self._runtime_minutes_for_circuit(config.circuit_id)
        baseline = self._dry_weather_pump_baseline(config.circuit_id, now)
        evidence = evaluate_rain_pump_correlation(
            RainPumpCorrelationInput(
                circuit_id=config.circuit_id,
                appliance_profile=config.appliance_profile.value,
                pump_runtime_minutes=runtime_minutes,
                dry_baseline_minutes=baseline["dry_baseline_minutes"],
                comparable_window_count=baseline["comparable_window_count"],
                rain_active=rain_active,
                rain_intensity_per_hour=rain_intensity,
                rain_intensity_unit=rain_intensity_unit,
                compressor_runtime_minutes=compressor_context["runtime_minutes"],
                compressor_duty_cycle_percent=compressor_context[
                    "duty_cycle_percent"
                ],
                sensitivity_delta_threshold_pct=float(
                    advanced_settings.get(
                        CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                        DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                    )
                ),
            )
        )
        evidence["rain_sensor_entity"] = rain_entity
        evidence["rain_sensor_active"] = rain_active
        evidence["rain_intensity_entity"] = rain_intensity_entity
        evidence["rain_intensity_per_hour"] = rain_intensity
        evidence["rain_intensity_unit"] = rain_intensity_unit
        evidence["rain_response_window_minutes"] = int(
            advanced_settings.get(
                CONF_RAIN_RESPONSE_WINDOW_MINUTES,
                DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
            )
        )
        evidence["hvac_compressor_runtime_minutes"] = compressor_context[
            "runtime_minutes"
        ]
        evidence["hvac_compressor_duty_cycle_percent"] = compressor_context[
            "duty_cycle_percent"
        ]
        evidence["hvac_compressor_circuits"] = compressor_context["circuit_ids"]
        return evidence

    def _water_flow_context_evidence(
        self: Self,
        config: CircuitConfig,
        advanced_settings: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        flow_entities = self._flow_entities_for_circuit(advanced_settings)
        threshold_minutes = int(
            advanced_settings.get(
                CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
                DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
            )
        )
        flow_active_minutes = self._max_flow_active_minutes(flow_entities, now)
        appliance_runtime_minutes = self._runtime_minutes_for_circuit(
            config.circuit_id
        )
        recent_related_runtime_minutes = (
            self._recent_flow_context_minutes(
                flow_entities,
                now,
                threshold_minutes,
            )
            if appliance_runtime_minutes > 0
            else 0.0
        )
        history_count = len(
            self.store_data.water_context_history_by_circuit.get(
                config.circuit_id,
                [],
            )
        )
        evidence = evaluate_flow_correlation(
            FlowCorrelationInput(
                circuit_id=config.circuit_id,
                appliance_profile=config.appliance_profile.value,
                flow_active_minutes=flow_active_minutes,
                appliance_runtime_minutes=appliance_runtime_minutes,
                recent_related_runtime_minutes=recent_related_runtime_minutes,
                mapped_appliance_count=self._mapped_water_appliance_count(
                    flow_entities
                ),
                threshold_minutes=threshold_minutes,
                expects_water_flow=bool(
                    advanced_settings.get(CONF_EXPECTS_WATER_FLOW, True)
                ),
                comparable_window_count=history_count,
            )
        )
        evidence["flow_sensor_entities"] = list(flow_entities)
        evidence["flow_sensor_active"] = any(
            self._binary_entity_active(entity_id) is True for entity_id in flow_entities
        )
        evidence["flow_mismatch_threshold_minutes"] = threshold_minutes
        return evidence

    def _clear_rain_pump_context_state(self: Self, circuit_id: str) -> bool:
        removed = False
        if self.state.rain_pump_context_by_circuit.pop(circuit_id, None) is not None:
            removed = True
        if (
            self.store_data.rain_pump_context_by_circuit.pop(circuit_id, None)
            is not None
        ):
            removed = True
        return removed

    def _clear_water_flow_context_state(self: Self, circuit_id: str) -> bool:
        removed = False
        if self.state.water_flow_context_by_circuit.pop(circuit_id, None) is not None:
            removed = True
        if (
            self.store_data.water_flow_context_by_circuit.pop(circuit_id, None)
            is not None
        ):
            removed = True
        return removed

    def _clear_water_context_history(self: Self, circuit_id: str) -> bool:
        removed = False
        if (
            self.state.water_context_history_by_circuit.pop(circuit_id, None)
            is not None
        ):
            removed = True
        if (
            self.store_data.water_context_history_by_circuit.pop(circuit_id, None)
            is not None
        ):
            removed = True
        return removed

    def _configured_context_entity(self: Self, key: str) -> str:
        for source in (self.options, self.entry_data):
            entity_id = str(source.get(key, "") or "").strip()
            if entity_id:
                return entity_id
        return ""

    def _configured_context_entities(self: Self, key: str) -> tuple[str, ...]:
        return tuple(_string_list_from_sources(self.entry_data, self.options, key))

    def _flow_entities_for_circuit(
        self: Self,
        advanced_settings: Mapping[str, Any],
    ) -> tuple[str, ...]:
        linked = advanced_settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES, [])
        entities = [
            entity_id
            for entity_id in _strings_from_any(linked)
            if entity_id
        ]
        if not entities:
            entities.extend(
                self._configured_context_entities(CONF_WATER_FLOW_SENSOR_ENTITIES)
            )
        return tuple(dict.fromkeys(entities))

    def _binary_entity_active(self: Self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        raw_state = self._raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip().lower()
        if state in {"on", "true", "1", "wet", "rain", "raining", "detected"}:
            return True
        if state in {"off", "false", "0", "dry", "clear", "none"}:
            return False
        return None

    def _numeric_entity_value(self: Self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        raw_state = self._raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip()
        return _float_or_none(state)

    def _entity_unit_of_measurement(self: Self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        raw_state = self._raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        attributes = getattr(raw_state, "attributes", {})
        if not isinstance(attributes, Mapping):
            return None
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        return unit or None

    def _max_flow_active_minutes(
        self: Self,
        entity_ids: Iterable[str],
        now: datetime,
    ) -> float:
        durations = [
            self._flow_entity_active_minutes(entity_id, now)
            for entity_id in entity_ids
        ]
        return round(max(durations, default=0.0), 3)

    def _flow_entity_active(self: Self, entity_id: str | None) -> bool | None:
        active = self._binary_entity_active(entity_id)
        if active is not None:
            return active
        value = self._numeric_entity_value(entity_id)
        if value is None:
            return None
        return value > 0.0

    def _flow_entity_active_minutes(
        self: Self,
        entity_id: str,
        now: datetime,
    ) -> float:
        if self._flow_entity_active(entity_id) is not True:
            return 0.0
        raw_state = self._raw_state_for_entity(entity_id)
        changed_at = _datetime_or_none(getattr(raw_state, "last_changed", None))
        if changed_at is None:
            return 0.0
        return max(0.0, (now - changed_at).total_seconds() / 60.0)

    def _recent_flow_context_minutes(
        self: Self,
        entity_ids: Iterable[str],
        now: datetime,
        threshold_minutes: int,
    ) -> float:
        recent_minutes = 0.0
        lookback = timedelta(minutes=max(threshold_minutes, 1) * 3)
        for entity_id in entity_ids:
            raw_state = self._raw_state_for_entity(entity_id)
            if raw_state is None:
                continue
            changed_at = _datetime_or_none(getattr(raw_state, "last_changed", None))
            if changed_at is not None and now - changed_at <= lookback:
                recent_minutes = max(recent_minutes, threshold_minutes)
        return recent_minutes

    def _runtime_minutes_for_circuit(self: Self, circuit_id: str) -> float:
        return round(
            self.state.run_cycle_runtime_seconds_by_circuit.get(circuit_id, 0.0)
            / 60.0,
            3,
        )

    def _hvac_compressor_context(self: Self) -> dict[str, Any]:
        circuit_ids: list[str] = []
        runtime_minutes = 0.0
        duty_cycle_percent = 0.0
        for config in self.circuit_configs:
            if config.appliance_profile not in {
                ApplianceProfile.HVAC,
                ApplianceProfile.HVAC_COMPRESSOR,
            }:
                continue
            circuit_ids.append(config.circuit_id)
            runtime_minutes += self._runtime_minutes_for_circuit(config.circuit_id)
            duty_cycle_percent = max(
                duty_cycle_percent,
                self.state.run_cycle_duty_cycle_by_circuit.get(
                    config.circuit_id,
                    0.0,
                ),
            )
        return {
            "circuit_ids": circuit_ids,
            "runtime_minutes": round(runtime_minutes, 3),
            "duty_cycle_percent": round(duty_cycle_percent, 3),
        }

    def _dry_weather_pump_baseline(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        dry_samples: list[float] = []
        for sample in self.store_data.water_context_history_by_circuit.get(
            circuit_id,
            [],
        ):
            if not isinstance(sample, Mapping):
                continue
            sample_time = _datetime_or_none(sample.get("timestamp"))
            if sample_time is not None and _ha_local_date(
                sample_time,
                self._ha_time_zone(),
            ) >= _ha_local_date(now, self._ha_time_zone()):
                continue
            if not _water_context_history_sample_is_dry(sample):
                continue
            if _float_or_none(sample.get("compressor_runtime_minutes")) not in (
                None,
                0.0,
            ):
                continue
            runtime = _float_or_none(sample.get("pump_runtime_minutes"))
            if runtime is not None:
                dry_samples.append(runtime)
        return {
            "dry_baseline_minutes": (
                round(float(median(dry_samples)), 3) if dry_samples else None
            ),
            "comparable_window_count": len(dry_samples),
        }

    def _mapped_water_appliance_count(self: Self, flow_entities: Iterable[str]) -> int:
        if not tuple(flow_entities):
            return 0
        count = 0
        for config in self.circuit_configs:
            if config.appliance_profile in FLOW_WATER_CONTEXT_PROFILES:
                count += 1
        return count

    def _append_water_context_history(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> bool:
        rain_evidence = self.state.rain_pump_context_by_circuit.get(circuit_id, {})
        flow_evidence = self.state.water_flow_context_by_circuit.get(circuit_id, {})
        if not rain_evidence and not flow_evidence:
            return False
        sample = {
            "timestamp": now.isoformat(),
            "rain_status": rain_evidence.get("status"),
            "flow_status": flow_evidence.get("status"),
            "pump_runtime_minutes": rain_evidence.get("pump_runtime_minutes"),
            "flow_active_minutes": flow_evidence.get("flow_active_minutes"),
            "mismatch_minutes": flow_evidence.get("mismatch_minutes"),
            "rain_active": rain_evidence.get("rain_sensor_active"),
            "compressor_runtime_minutes": rain_evidence.get(
                "hvac_compressor_runtime_minutes"
            ),
        }
        for key in (
            "rain_state",
            "rain_intensity_mm_per_hour",
            "rain_intensity_bin",
            "rain_context_issues",
        ):
            if key in rain_evidence:
                sample[key] = rain_evidence[key]
        history = self.store_data.water_context_history_by_circuit.setdefault(
            circuit_id,
            [],
        )
        for index in range(len(history) - 1, -1, -1):
            existing_time = _datetime_or_none(history[index].get("timestamp"))
            if existing_time is not None and _ha_local_date(
                existing_time,
                self._ha_time_zone(),
            ) == _ha_local_date(now, self._ha_time_zone()):
                if history[index] == sample:
                    return False
                history[index] = sample
                self.state.water_context_history_by_circuit[circuit_id] = [
                    dict(item) for item in history
                ]
                return True

        history.append(sample)
        del history[:-WATER_CONTEXT_HISTORY_MAX_SAMPLES]
        self.state.water_context_history_by_circuit[circuit_id] = [
            dict(item) for item in history
        ]
        return True

    def _clear_weather_context_state(self: Self, circuit_id: str) -> None:
        removed = False
        if self.state.weather_context_by_circuit.pop(circuit_id, None) is not None:
            removed = True
        if self.store_data.weather_context_by_circuit.pop(circuit_id, None) is not None:
            removed = True
        if (
            self.store_data.weather_context_history_by_circuit.pop(circuit_id, None)
            is not None
        ):
            removed = True
        if removed:
            self._mark_store_dirty()

    def _outdoor_temperature_entity(self: Self) -> str:
        for source in (self.options, self.entry_data):
            entity_id = str(source.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, "")).strip()
            if entity_id:
                return entity_id
        return ""

    def _temperature_reading_for_entity(
        self: Self,
        entity_id: str,
    ) -> dict[str, float | str] | None:
        raw_state = self._raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip()
        if state.lower() in {"unknown", "unavailable", ""}:
            return None
        value = _float_or_none(state)
        if value is None:
            return None
        attributes = getattr(raw_state, "attributes", {}) or {}
        source_unit = self._temperature_source_unit(
            str(attributes.get("unit_of_measurement") or "").strip(),
        )
        temperature_f = _temperature_to_fahrenheit(value, source_unit)
        display_unit = self._temperature_display_unit(source_unit)
        display_temperature = _temperature_from_fahrenheit(
            temperature_f,
            display_unit,
        )
        return {
            "temperature_f": round(temperature_f, 3),
            "display_temperature": round(display_temperature, 3),
            "display_unit": display_unit,
            "source_unit": source_unit,
        }

    def _temperature_source_unit(self: Self, raw_unit: str) -> str:
        unit = _normalized_temperature_unit(raw_unit)
        if unit:
            return unit
        return self._ha_temperature_unit()

    def _temperature_display_unit(self: Self, source_unit: str) -> str:
        if source_unit in {"°F", "°C"}:
            return source_unit
        return self._ha_temperature_unit()

    def _ha_temperature_unit(self: Self) -> str:
        config = getattr(self.hass, "config", None)
        units = getattr(config, "units", None)
        raw_unit = getattr(units, "temperature_unit", None)
        unit = _normalized_temperature_unit(str(raw_unit or ""))
        return unit or "°F"

    def _raw_state_for_entity(self: Self, entity_id: str) -> Any | None:
        hass_states = getattr(self.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return None
        return get_state(entity_id)

    def _weather_context_history_samples(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> list[WeatherContextSample]:
        samples: list[WeatherContextSample] = []
        raw_samples = self.store_data.weather_context_history_by_circuit.get(
            circuit_id,
            [],
        )
        for raw_sample in raw_samples:
            if not isinstance(raw_sample, Mapping):
                continue
            sample_time = _datetime_or_none(raw_sample.get("timestamp"))
            if sample_time is None or _ha_local_date(
                sample_time,
                self._ha_time_zone(),
            ) >= _ha_local_date(now, self._ha_time_zone()):
                continue
            temperature = _float_or_none(raw_sample.get("temperature"))
            runtime = _float_or_none(raw_sample.get("runtime_minutes"))
            duty = _float_or_none(raw_sample.get("duty_cycle_percent"))
            if temperature is None or runtime is None or duty is None:
                continue
            samples.append(
                WeatherContextSample(
                    temperature=temperature,
                    runtime_minutes=runtime,
                    duty_cycle_percent=duty,
                    timestamp=sample_time,
                    energy_kwh=_float_or_none(raw_sample.get("energy_kwh")),
                    start_count=(
                        int(start_count)
                        if (start_count := _float_or_none(
                            raw_sample.get("start_count"),
                        ))
                        is not None
                        else None
                    ),
                )
            )
        return samples

    def _append_weather_context_history(
        self: Self,
        circuit_id: str,
        now: datetime,
        *,
        temperature: float,
        runtime_minutes: float,
        duty_cycle_percent: float,
    ) -> bool:
        sample = {
            "timestamp": now.isoformat(),
            "temperature": round(float(temperature), 3),
            "runtime_minutes": round(float(runtime_minutes), 3),
            "duty_cycle_percent": round(float(duty_cycle_percent), 3),
            "start_count": self.state.run_cycle_count_by_circuit.get(circuit_id, 0),
        }
        history = self.store_data.weather_context_history_by_circuit.setdefault(
            circuit_id,
            [],
        )
        for index in range(len(history) - 1, -1, -1):
            existing_time = _datetime_or_none(history[index].get("timestamp"))
            if existing_time is not None and _ha_local_date(
                existing_time,
                self._ha_time_zone(),
            ) == _ha_local_date(now, self._ha_time_zone()):
                if history[index] == sample:
                    return False
                history[index] = sample
                return True

        history.append(sample)
        del history[:-WEATHER_CONTEXT_HISTORY_MAX_SAMPLES]
        return True

    def _latest_alert_for_circuit(self: Self, circuit_id: str) -> AlertEvidence | None:
        alerts = list(self.state.active_alerts_by_circuit.get(circuit_id, []))
        if not alerts:
            alerts = [
                alert
                for alert in self.store_data.alerts
                if alert.circuit_id == circuit_id
            ]
        if not alerts:
            return None
        return max(alerts, key=lambda alert: alert.timestamp)

    def _config_for_circuit(self: Self, circuit_id: str) -> CircuitConfig | None:
        for config in self.circuit_configs:
            if config.circuit_id == circuit_id:
                return config
        return None

    def _sample_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> NormalizedCircuitSample:
        if config.mode is CircuitMode.MAINS_NILM:
            return self._aggregate_parallel_sample(config, now)
        if config.mode is not CircuitMode.DUAL_PHASE:
            return build_circuit_sample(
                config,
                self._source_states_for(config, now),
                now,
            )

        left_sensors = tuple(
            sensor for sensor in config.sensors if _normalized_leg(sensor.leg) == "a"
        )
        right_sensors = tuple(
            sensor for sensor in config.sensors if _normalized_leg(sensor.leg) == "b"
        )
        if not left_sensors or not right_sensors:
            return build_circuit_sample(
                config,
                self._source_states_for(config, now),
                now,
            )

        left_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=left_sensors,
        )
        right_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=right_sensors,
        )
        left_sample = build_circuit_sample(
            left_config,
            self._source_states_for(left_config, now),
            now,
        )
        right_sample = build_circuit_sample(
            right_config,
            self._source_states_for(right_config, now),
            now,
        )
        aggregated = aggregate_dual_phase(config.circuit_id, left_sample, right_sample)
        raw_real_power = _sum_complete_sample_values(
            (left_sample, right_sample),
            "raw_real_power",
        )
        return NormalizedCircuitSample(
            timestamp=aggregated.timestamp,
            circuit_id=config.circuit_id,
            real_power=aggregated.combined_real_power,
            current=aggregated.combined_current,
            voltage=aggregated.average_voltage,
            reactive_power=aggregated.combined_reactive_power,
            apparent_power=aggregated.combined_apparent_power,
            power_factor=aggregated.average_power_factor,
            frequency=aggregated.frequency,
            energy=aggregated.energy,
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=aggregated.quality_issues,
            raw_real_power=raw_real_power,
            power_flow=config.power_flow,
            power_flow_direction=_power_flow_direction(
                raw_real_power,
                config.power_flow,
            ),
            leg_a_real_power=aggregated.leg_a.real_power,
            leg_b_real_power=aggregated.leg_b.real_power,
            leg_a_current=aggregated.leg_a.current,
            leg_b_current=aggregated.leg_b.current,
            leg_a_voltage=aggregated.leg_a.voltage,
            leg_b_voltage=aggregated.leg_b.voltage,
            leg_power_imbalance_ratio=aggregated.leg_power_imbalance_ratio,
            voltage_difference=aggregated.voltage_difference,
        )

    def _aggregate_parallel_sample(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> NormalizedCircuitSample:
        sensor_samples = [
            (
                sensor,
                build_circuit_sample(
                    replace(config, sensors=(sensor,)),
                    self._source_states_for(replace(config, sensors=(sensor,)), now),
                    now,
                ),
            )
            for sensor in config.sensors
        ]
        samples = [sample for _sensor, sample in sensor_samples]
        if not samples:
            return build_circuit_sample(config, {}, now)

        raw_real_power = _sum_parallel_sensor_values(
            sensor_samples,
            "raw_real_power",
            SensorRole.REAL_POWER,
        )
        leg_a_sample, leg_b_sample = _parallel_leg_samples(sensor_samples)
        return NormalizedCircuitSample(
            timestamp=max(sample.timestamp for sample in samples),
            circuit_id=config.circuit_id,
            real_power=_sum_parallel_sensor_values(
                sensor_samples,
                "real_power",
                SensorRole.REAL_POWER,
            ),
            current=_sum_parallel_sensor_values(
                sensor_samples,
                "current",
                SensorRole.CURRENT,
            ),
            voltage=_average_sample_values(samples, "voltage"),
            reactive_power=_sum_parallel_sensor_values(
                sensor_samples,
                "reactive_power",
                SensorRole.REACTIVE_POWER,
            ),
            apparent_power=_sum_parallel_sensor_values(
                sensor_samples,
                "apparent_power",
                SensorRole.APPARENT_POWER,
            ),
            power_factor=_average_sample_values(samples, "power_factor"),
            frequency=_average_sample_values(samples, "frequency"),
            energy=_sum_parallel_sensor_values(
                sensor_samples,
                "energy",
                SensorRole.ENERGY,
            ),
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=tuple(
                issue
                for sample in samples
                for issue in getattr(sample, "quality_issues", ())
            ),
            raw_real_power=raw_real_power,
            power_flow=config.power_flow,
            power_flow_direction=_power_flow_direction(
                raw_real_power,
                config.power_flow,
            ),
            leg_a_real_power=_sample_value_or_none(leg_a_sample, "real_power"),
            leg_b_real_power=_sample_value_or_none(leg_b_sample, "real_power"),
            leg_a_current=_sample_value_or_none(leg_a_sample, "current"),
            leg_b_current=_sample_value_or_none(leg_b_sample, "current"),
            leg_a_voltage=_sample_value_or_none(leg_a_sample, "voltage"),
            leg_b_voltage=_sample_value_or_none(leg_b_sample, "voltage"),
        )

    async def _sync_data_quality_repairs(
        self: Self,
        circuit_id: str,
        sample_or_problem: NormalizedCircuitSample | str,
    ) -> None:
        await self.setup_health.async_sync_data_quality_repairs(
            circuit_id,
            sample_or_problem,
        )

    def _data_quality_repair_data(
        self: Self,
        circuit_id: str,
        problem: str,
        source_entities: Iterable[str],
    ) -> dict[str, Any]:
        config = self._config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        return {
            "circuit_name": str(circuit_name),
            "reason": self._data_quality_repair_reason(problem),
            "recommended_action": self._data_quality_repair_action(
                circuit_name,
                problem,
            ),
            "source_entities": list(dict.fromkeys(source_entities)),
        }

    def _data_quality_repair_reason(self: Self, problem: str) -> str:
        reasons = {
            "missing_required_sensor": (
                "A configured circuit is missing a required source sensor."
            ),
            "missing_source_entities": (
                "The integration has no configured source sensors."
            ),
            "stale_source_sensor": (
                "One or more selected source sensors have not updated recently."
            ),
            "unexpected_negative_real_power": (
                "A load circuit is reporting sustained negative real power."
            ),
        }
        return reasons.get(problem, "A configured circuit has source-data issues.")

    def _data_quality_repair_action(
        self: Self,
        circuit_name: str,
        problem: str,
    ) -> str:
        actions = {
            "missing_required_sensor": f"Review source sensors for {circuit_name}",
            "missing_source_entities": (
                f"Add at least one source sensor for {circuit_name}"
            ),
            "stale_source_sensor": (
                f"Fix stale source sensor data for {circuit_name}"
            ),
            "unexpected_negative_real_power": (
                f"Check CT direction or power-flow mode for {circuit_name}"
            ),
        }
        return actions.get(problem, f"Review source data for {circuit_name}")

    def _data_quality_repair_source_entities(self: Self, circuit_id: str) -> list[str]:
        config = self._config_for_circuit(circuit_id)
        if config is None:
            return []
        return [
            sensor.entity_id
            for sensor in getattr(config, "sensors", ())
            if isinstance(getattr(sensor, "entity_id", None), str)
            and sensor.entity_id
        ]

    async def _sync_setup_health_repairs(self: Self, circuit_id: str) -> None:
        await self.setup_health.async_sync_setup_health_repairs(circuit_id)

    def _setup_health_repair_data(
        self: Self,
        circuit_id: str,
        problem: str,
    ) -> dict[str, str]:
        config = self._config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        recommended_actions = {
            "missing_energy_source": (
                f"Add a cumulative kWh sensor to {circuit_name}"
            ),
            "missing_source_entities": (
                f"Add at least one source sensor to {circuit_name}"
            ),
            "missing_mains_source": "Add a mains or whole-home source",
            "missing_electrical_metrics": (
                f"Add matching electrical metrics for {circuit_name}"
            ),
            "check_ct_direction": (
                f"Check CT direction or power-flow mode for {circuit_name}"
            ),
            "dual_phase_missing_leg": (
                f"Review leg A and leg B source sensors for {circuit_name}"
            ),
            "missing_rain_context_source": f"Add a rain sensor for {circuit_name}",
            "missing_water_flow_source": (
                f"Add a water-flow sensor for {circuit_name}"
            ),
            "utility_comparison_source_mismatch": (
                f"Review utility comparison source settings for {circuit_name}"
            ),
            "utility_comparison_missing_utility_source": (
                f"Add utility comparison source for {circuit_name}"
            ),
            "utility_comparison_missing_measured_source": (
                f"Add measured kWh source for {circuit_name}"
            ),
        }
        return {
            "circuit_name": str(circuit_name),
            "reason": self._setup_health_repair_reason(circuit_id, problem),
            "recommended_action": recommended_actions.get(
                problem,
                f"Review setup for {circuit_name}",
            ),
            "source_entities": self._setup_health_repair_source_entities(
                circuit_id,
                problem,
            ),
        }

    def _setup_health_repair_reason(self: Self, circuit_id: str, problem: str) -> str:
        config = self._config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        reasons = {
            "missing_energy_source": (
                "Daily Energy Usage needs a cumulative energy source."
            ),
            "missing_source_entities": (
                "No source sensors are configured for this circuit."
            ),
            "missing_mains_source": (
                "Mains balance, NILM, or solar-flow checks need a mains source."
            ),
            "missing_electrical_metrics": (
                "Power Metric Consistency needs matching supporting sensors."
            ),
            "check_ct_direction": (
                "Signed power evidence suggests export, reversed CT orientation, "
                "or a mapping mismatch."
            ),
            "dual_phase_missing_leg": (
                "One side of this dual-phase circuit is missing real-power data."
            ),
            "missing_rain_context_source": (
                "Rain-pump context is enabled, but no rain source is configured."
            ),
            "missing_water_flow_source": (
                "Water-flow context is enabled, but no flow source is configured."
            ),
            "utility_comparison_source_mismatch": (
                "Utility comparison sources or recorder periods cannot be compared."
            ),
            "utility_comparison_missing_utility_source": (
                "Utility comparison is enabled, but utility kWh has no data."
            ),
            "utility_comparison_missing_measured_source": (
                "Utility comparison is enabled, but measured kWh has no data."
            ),
        }
        return reasons.get(problem, f"Review setup for {circuit_name}.")

    def _setup_health_has_missing_source_entities(self: Self, circuit_id: str) -> bool:
        config = self._config_for_circuit(circuit_id)
        if config is not None and not self._setup_health_source_entities(circuit_id):
            return True
        return (
            str(self.state.data_quality_by_circuit.get(circuit_id, ""))
            == "missing_source_entities"
        )

    def _setup_health_source_entities(self: Self, circuit_id: str) -> list[str]:
        config = self._config_for_circuit(circuit_id)
        if config is None:
            return []
        return [
            sensor.entity_id
            for sensor in getattr(config, "sensors", ())
            if isinstance(getattr(sensor, "entity_id", None), str)
            and sensor.entity_id
        ]

    def _setup_health_repair_source_entities(
        self: Self,
        circuit_id: str,
        problem: str,
    ) -> list[str]:
        source_entities = self._setup_health_source_entities(circuit_id)
        if problem == "dual_phase_missing_leg":
            return source_entities
        if problem in {
            "missing_energy_source",
            "missing_electrical_metrics",
            "check_ct_direction",
        }:
            return source_entities
        return []

    def _setup_health_has_missing_mains_status(self: Self, circuit_id: str) -> bool:
        for field_name in (
            "balance_status_by_circuit",
            "solar_flow_status_by_circuit",
            "solar_surplus_status_by_circuit",
        ):
            if getattr(self.state, field_name, {}).get(circuit_id) == "missing_mains":
                return True
        return False

    def _setup_health_has_ct_direction_status(self: Self, circuit_id: str) -> bool:
        for field_name in (
            "balance_status_by_circuit",
            "solar_flow_status_by_circuit",
            "solar_surplus_status_by_circuit",
        ):
            if getattr(self.state, field_name, {}).get(circuit_id) in {
                "inconsistent_export",
                "negative_balance",
            }:
                return True
        return False

    def _setup_health_has_missing_rain_context_source(
        self: Self,
        circuit_id: str,
    ) -> bool:
        config = self._config_for_circuit(circuit_id)
        if (
            config is None
            or config.appliance_profile not in PUMP_WATER_CONTEXT_PROFILES
        ):
            return False
        advanced_settings = self._advanced_settings_for_circuit(circuit_id)
        if not bool(
            advanced_settings.get(
                CONF_RAIN_PUMP_CORRELATION_ENABLED,
                DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
            )
        ):
            return False
        return not self._has_rain_context_source_configured()

    def _setup_health_has_missing_water_flow_source(
        self: Self,
        circuit_id: str,
    ) -> bool:
        config = self._config_for_circuit(circuit_id)
        if (
            config is None
            or config.appliance_profile not in FLOW_WATER_CONTEXT_PROFILES
        ):
            return False
        advanced_settings = self._advanced_settings_for_circuit(circuit_id)
        if not bool(
            advanced_settings.get(
                CONF_WATER_FLOW_CORRELATION_ENABLED,
                DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
            )
        ):
            return False
        if not bool(advanced_settings.get(CONF_EXPECTS_WATER_FLOW, True)):
            return False
        return not self._flow_entities_for_circuit(advanced_settings)

    def _setup_health_has_utility_comparison_setup_status(
        self: Self,
        circuit_id: str,
    ) -> bool:
        return (
            self._setup_health_utility_comparison_repair_problem(circuit_id)
            is not None
        )

    def _setup_health_utility_comparison_repair_problem(
        self: Self,
        circuit_id: str,
    ) -> str | None:
        status = self.state.utility_comparison_status_by_circuit.get(circuit_id)
        return _UTILITY_COMPARISON_SETUP_REPAIR_PROBLEM_BY_STATUS.get(str(status))

    def _has_rain_context_source_configured(self: Self) -> bool:
        return bool(
            self._configured_context_entity(CONF_RAIN_SENSOR_ENTITY)
            or self._configured_context_entity(CONF_RAIN_INTENSITY_ENTITY)
        )

    def _has_mains_source_configured(self: Self) -> bool:
        return bool(
            _string_list_from_sources(
                self.entry_data,
                self.options,
                CONF_MAINS_SOURCE_ENTITIES,
            )
        )

    def _process_nilm_sample(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample,
        events: Iterable[CircuitEvent],
    ) -> list[AlertEvidence]:
        result = self._nilm_sample_processor.process(
            sample,
            config,
            self._build_processing_context(sample.timestamp),
            events=events,
        )
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)
        if result.store_dirty:
            self._mark_store_dirty()
        return list(result.alerts)

    def _known_load_events(
        self: Self,
        nilm_circuit_id: str,
        events: Iterable[CircuitEvent],
    ) -> Iterable[CircuitEvent]:
        for event in events:
            if event.circuit_id == nilm_circuit_id:
                continue
            if (
                self._known_load_circuit_ids
                and event.circuit_id not in self._known_load_circuit_ids
            ):
                continue
            yield event

    def _observe_nilm_known_load_topology(
        self: Self,
        mains_config: CircuitConfig,
        match: KnownLoadMatch,
    ) -> AlertEvidence | None:
        result = self._nilm_topology_processor.process(
            mains_config,
            match,
            self._build_processing_context(match.edge.timestamp),
        )
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)
        return result.alerts[0] if result.alerts else None

    def _nilm_enabled(self: Self, config: CircuitConfig) -> bool:
        enabled = bool(
            self.options.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                self.entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
            )
        )
        return enabled and (
            config.mode is CircuitMode.MAINS_NILM
            or config.appliance_profile is ApplianceProfile.MAINS_NILM
        )

    def _nilm_signature_payloads(
        self: Self,
        circuit_id: str,
        signatures: Iterable[Any],
    ) -> list[dict[str, Any]]:
        return self._nilm_sample_processor._nilm_signature_payloads(
            circuit_id,
            signatures,
            self._build_processing_context(self._now_fn()),
        )

    def _refresh_nilm_state(self: Self, circuit_id: str) -> None:
        result = self._nilm_sample_processor.refresh_state(
            circuit_id,
            self._build_processing_context(self._now_fn()),
        )
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)

    def _seed_demo_event_history(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        if not _is_demo_config(config):
            return

        profile = get_profile_definition(config.appliance_profile)
        minimum_starts = max(profile.minimum_cycles, 8)
        circuit_events = [
            event
            for event in self.store_data.events
            if event.circuit_id == config.circuit_id
        ]
        start_count = sum(
            1 for event in circuit_events if event.event_type is EventType.START
        )
        oldest = min((event.timestamp for event in circuit_events), default=None)
        mature_by_count = start_count >= minimum_starts
        mature_by_age = oldest is not None and now - oldest >= timedelta(
            days=profile.minimum_learning_days,
        )
        if mature_by_count and mature_by_age:
            return

        self.store_data.events = [
            event
            for event in self.store_data.events
            if not (
                event.circuit_id == config.circuit_id
                and event.features.get("demo_seed_version")
                == _DEMO_HISTORY_SEED_VERSION
            )
        ]
        base = now - timedelta(days=max(profile.minimum_learning_days, 7), hours=1)
        seeded: list[CircuitEvent] = []
        for index in range(minimum_starts):
            start = base + timedelta(hours=index * 4)
            stop = start + timedelta(minutes=45)
            seeded.append(
                CircuitEvent(
                    timestamp=start,
                    circuit_id=config.circuit_id,
                    event_type=EventType.START,
                    features={
                        "demo_seed_version": _DEMO_HISTORY_SEED_VERSION,
                        "cycle_index": index,
                    },
                )
            )
            seeded.append(
                CircuitEvent(
                    timestamp=stop,
                    circuit_id=config.circuit_id,
                    event_type=EventType.STOP,
                    features={
                        "demo_seed_version": _DEMO_HISTORY_SEED_VERSION,
                        "cycle_index": index,
                    },
                )
            )
        self.store_data.events.extend(seeded)
        self._mark_store_dirty()

    def _seed_demo_power_quality_baselines(
        self: Self,
        config: CircuitConfig,
        features: Mapping[str, float],
    ) -> None:
        if not _is_demo_config(config):
            return

        changed = False
        for feature, value in features.items():
            key = _baseline_key(config.circuit_id, feature)
            if key in self.store_data.baselines:
                continue
            self.store_data.baselines[key] = _demo_baseline(feature, value)
            changed = True
        if changed:
            self._mark_store_dirty()

    def _seed_demo_energy_usage_history(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
        settings: EnergyUsageSettings,
    ) -> None:
        if not _is_demo_config(config) or sample.energy is None:
            return

        energy_kwh = _float_or_none(sample.energy)
        if energy_kwh is None or energy_kwh <= 0.0:
            return

        window_days = max(int(settings.window_days), 1)
        today_date = _ha_local_date(now, self._ha_time_zone())
        today = today_date.isoformat()
        history = self.store_data.energy_usage_by_circuit.setdefault(
            config.circuit_id,
            {},
        )
        days = history.get("days")
        prior_day_count = (
            sum(
                1
                for day in days
                if isinstance(day, Mapping) and str(day.get("date", "")) < today
            )
            if isinstance(days, list)
            else 0
        )
        if prior_day_count >= window_days and _float_or_none(
            history.get("last_energy_kwh"),
        ) is not None:
            return

        circuit_key = _demo_circuit_key(config)
        prior_usage = _demo_prior_usage(circuit_key, window_days)
        today_usage = _demo_today_usage(circuit_key, energy_kwh)
        start_date = today_date - timedelta(days=window_days)
        history["days"] = [
            {
                "date": (start_date + timedelta(days=index)).isoformat(),
                "usage_kwh": round(float(usage), 3),
            }
            for index, usage in enumerate(prior_usage)
        ]
        history["last_energy_kwh"] = round(max(energy_kwh - today_usage, 0.0), 3)
        history["last_sample_at"] = (now - timedelta(minutes=5)).isoformat()
        history["_demo_seed_version"] = _DEMO_HISTORY_SEED_VERSION
        history["_demo_seed_date"] = today
        self._mark_store_dirty()

    def _seed_demo_weather_context_history(
        self: Self,
        config: CircuitConfig,
        now: datetime,
        *,
        outdoor_temperature: float | None,
    ) -> None:
        if (
            not _is_demo_config(config)
            or config.appliance_profile not in HVAC_WEATHER_CONTEXT_PROFILES
            or outdoor_temperature is None
        ):
            return

        raw_history = self.store_data.weather_context_history_by_circuit.setdefault(
            config.circuit_id,
            [],
        )
        comparable_count = 0
        for sample in raw_history:
            if not isinstance(sample, Mapping):
                continue
            sample_time = _datetime_or_none(sample.get("timestamp"))
            sample_temp = _float_or_none(sample.get("temperature"))
            if (
                sample_time is not None
                and _ha_local_date(sample_time, self._ha_time_zone())
                < _ha_local_date(now, self._ha_time_zone())
                and sample_temp is not None
                and abs(sample_temp - outdoor_temperature) <= 3.0
            ):
                comparable_count += 1
        if comparable_count >= 3:
            return

        current_date = _ha_local_date(now, self._ha_time_zone())
        self.store_data.weather_context_history_by_circuit[config.circuit_id] = [
            {
                "timestamp": local_day_time(
                    current_date - timedelta(days=7 - index),
                    time(12, 0),
                    self._ha_time_zone(),
                ).isoformat(),
                "temperature": round(float(outdoor_temperature) + offset, 3),
                "runtime_minutes": runtime,
                "duty_cycle_percent": duty,
                "energy_kwh": round(runtime * 0.055, 3),
                "start_count": 3 + (index % 2),
                "_demo_seed_version": _DEMO_HISTORY_SEED_VERSION,
            }
            for index, (offset, runtime, duty) in enumerate(
                (
                    (-2.0, 78.0, 12.5),
                    (-1.0, 84.0, 13.8),
                    (0.0, 92.0, 15.0),
                    (1.0, 97.0, 15.7),
                    (2.0, 104.0, 16.9),
                )
            )
        ]
        self._mark_store_dirty()

    def _seed_demo_standby_history(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
        settings: StandbySettings,
    ) -> None:
        if not _is_demo_config(config):
            return

        power_w = _demand_power_w(sample)
        if power_w is None:
            return

        min_samples = max(int(settings.min_samples), 1)
        history = self.store_data.standby_by_circuit.setdefault(
            config.circuit_id,
            {},
        )
        samples = history.get("samples")
        cutoff = now - timedelta(hours=max(int(settings.window_hours), 1))
        existing_count = (
            sum(
                1
                for raw_sample in samples
                if isinstance(raw_sample, Mapping)
                and (
                    sample_time := _datetime_or_none(raw_sample.get("timestamp"))
                )
                is not None
                and sample_time >= cutoff
            )
            if isinstance(samples, list)
            else 0
        )
        if existing_count >= min_samples:
            return

        window_hours = max(int(settings.window_hours), 1)
        sample_spacing_minutes = max(
            int((window_hours * 60) / max(min_samples + 1, 2)),
            5,
        )
        low_power_w = max(float(settings.standby_threshold_w) + 4.0, power_w * 0.04)
        seeded: list[dict[str, Any]] = []
        for index in range(max(min_samples - 1, 0)):
            timestamp = now - timedelta(
                minutes=sample_spacing_minutes * (min_samples - index),
            )
            seeded.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "real_power_w": round(
                        low_power_w + ((index % 4) * 1.5),
                        3,
                    ),
                    "_demo_seed_version": _DEMO_HISTORY_SEED_VERSION,
                }
            )
        history["samples"] = seeded
        self._mark_store_dirty()

    def _seed_demo_nilm_state(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        if not _is_demo_config(config):
            return

        seed = _demo_nilm_workspace_seed(now, circuit_id=config.circuit_id)

        if not self.store_data.nilm_signatures.get(config.circuit_id):
            self.store_data.nilm_signatures[config.circuit_id] = _demo_seed_list(
                seed.get("signatures"),
            )
            self._mark_store_dirty()

        if not self.store_data.nilm_unknown_loads_by_circuit.get(config.circuit_id):
            unknown_loads = seed.get("unknown_loads")
            if isinstance(unknown_loads, Mapping):
                self.store_data.nilm_unknown_loads_by_circuit[config.circuit_id] = (
                    dict(unknown_loads)
                )
            self._mark_store_dirty()

        if not self.store_data.nilm_session_history_by_circuit.get(config.circuit_id):
            self.store_data.nilm_session_history_by_circuit[config.circuit_id] = (
                _demo_seed_list(seed.get("sessions"))
            )
            self._mark_store_dirty()

        if not self.store_data.nilm_label_intervals_by_circuit.get(config.circuit_id):
            self.store_data.nilm_label_intervals_by_circuit[config.circuit_id] = (
                _demo_seed_list(seed.get("label_intervals"))
            )
            self._mark_store_dirty()

        if not self.store_data.nilm_appliance_assignments_by_circuit.get(
            config.circuit_id
        ):
            self.store_data.nilm_appliance_assignments_by_circuit[config.circuit_id] = (
                _demo_seed_list(seed.get("assignments"))
            )
            self._mark_store_dirty()

        self._nilm_total_events_by_circuit[config.circuit_id] = max(
            self._nilm_total_events_by_circuit[config.circuit_id],
            int(seed.get("total_events") or 0),
        )
        if not self._nilm_unmatched_edges[config.circuit_id]:
            self._nilm_unmatched_edges[config.circuit_id] = _demo_nilm_edges(
                seed.get("edges"),
            )
        self._nilm_unmatched_edges[config.circuit_id] = self._nilm_unmatched_edges[
            config.circuit_id
        ][:8]

    def _refresh_balance_state(
        self: Self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
        now: datetime,
    ) -> None:
        result = self._mains_balance_processor.process(
            samples,
            self._build_processing_context(now),
        )
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)

    def _refresh_solar_flow_state(
        self: Self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
        now: datetime,
    ) -> None:
        result = self._solar_flow_processor.process(
            samples,
            self._build_processing_context(now),
        )
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)

    async def _observe_utility_comparisons(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        alerts: list[AlertEvidence] = []
        context = self._build_processing_context(now)
        for circuit_id in self.store_data.utility_comparison_settings_by_circuit:
            config = self._config_for_circuit(circuit_id)
            if config is None:
                continue
            result = await self._utility_comparison_processor.process(config, context)
            _, new_alerts = await self._apply_feature_result(result)
            await self._sync_setup_health_repairs(circuit_id)
            alerts.extend(new_alerts)
        return alerts

    def _energy_kwh_sum_for_entities(
        self: Self,
        entity_ids: Iterable[str],
        now: datetime,
    ) -> tuple[float | None, tuple[str, ...]]:
        values: list[float] = []
        valid_entity_ids: list[str] = []
        for entity_id in entity_ids:
            value = self._energy_kwh_for_entity(entity_id, now)
            if value is None:
                continue
            values.append(value)
            valid_entity_ids.append(entity_id)
        if not values:
            return None, ()
        return round(sum(values), 3), tuple(valid_entity_ids)

    def _energy_kwh_for_entity(
        self: Self,
        entity_id: str,
        now: datetime,
    ) -> float | None:
        del now
        if not entity_id:
            return None
        hass_states = getattr(self.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return None
        raw_state = get_state(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip()
        if state.lower() in {"unknown", "unavailable", ""}:
            return None
        try:
            value = float(state)
        except ValueError:
            return None
        attributes = getattr(raw_state, "attributes", {}) or {}
        unit = attributes.get("unit_of_measurement")
        return _energy_value_kwh(value, unit)

    async def _statistics_kwh_for_id(
        self: Self,
        statistic_id: str,
        now: datetime,
        *,
        period: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Any:
        if not statistic_id:
            return select_latest_statistics_energy("", {}, now)
        statistics = await self._recorder_statistics_during_period(
            statistic_ids={statistic_id},
            start_time=start_time
            or _statistics_lookback_start(now, _utility_statistic_period_value(period)),
            end_time=end_time or now,
            period=period,
        )
        return select_latest_statistics_energy(statistic_id, statistics, now)

    async def _statistics_kwh_sum_for_entities(
        self: Self,
        entity_ids: Iterable[str],
        now: datetime,
        *,
        period: str,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[float | None, tuple[str, ...]]:
        ids = tuple(entity_id for entity_id in entity_ids if entity_id)
        if not ids:
            return None, ()
        statistics = await self._recorder_statistics_during_period(
            statistic_ids=set(ids),
            start_time=start_time,
            end_time=end_time,
            period=period,
        )
        values: list[float] = []
        valid_entity_ids: list[str] = []
        for entity_id in ids:
            reading = select_statistics_energy_for_period(
                entity_id,
                statistics,
                now,
                period_start=start_time,
                period_end=end_time,
            )
            if reading.energy_kwh is None:
                continue
            values.append(reading.energy_kwh)
            valid_entity_ids.append(entity_id)
        if not values:
            return None, ()
        return round(sum(values), 3), tuple(valid_entity_ids)

    async def _recorder_statistics_during_period(
        self: Self,
        *,
        statistic_ids: set[str],
        start_time: datetime,
        end_time: datetime | None,
        period: str,
    ) -> dict[str, list[dict[str, Any]]]:
        if _ha_statistics_during_period is None or not statistic_ids:
            return {}

        normalized_period = _utility_statistic_period_value(period)

        try:
            return await _async_recorder_executor_job(
                self.hass,
                _ha_statistics_during_period,
                self.hass,
                start_time,
                end_time,
                statistic_ids,
                normalized_period,
                {"energy": "kWh"},
                {"change", "sum", "state"},
            )
        except Exception as err:
            _LOGGER.debug(
                "Recorder statistics unavailable for %s: %s",
                sorted(statistic_ids),
                err,
            )
            return {}

    def _load_energy_entity_ids_for_sum(self: Self, circuit_id: str) -> tuple[str, ...]:
        entity_ids: list[str] = []
        for config in self.circuit_configs:
            if config.circuit_id == circuit_id:
                continue
            if (
                config.mode is CircuitMode.MAINS_NILM
                or config.appliance_profile is ApplianceProfile.MAINS_NILM
            ):
                continue
            if (
                config.power_flow is PowerFlowMode.GENERATION
                or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
            ):
                continue
            entity_ids.extend(
                sensor.entity_id
                for sensor in config.sensors
                if sensor.role is SensorRole.ENERGY
            )
        return tuple(entity_ids)

    def _sensitivity_for_circuit(self: Self, circuit_id: str) -> str:
        return normalize_sensitivity(
            self.store_data.sensitivity_by_circuit.get(circuit_id, self._sensitivity)
        )

    def _feedback_aware_alert_policy(
        self: Self,
        policy: ConservativeAlertPolicy,
    ) -> _FeedbackAwareAlertPolicy:
        return _FeedbackAwareAlertPolicy(self, policy)

    def _adjusted_min_repeated_for_observation(
        self: Self,
        observation: Observation,
        base_min_repeated: int,
    ) -> int:
        _fingerprint, feedback = self._alert_feedback_for_observation(observation)
        if _alert_feedback_status(feedback) != "unhelpful":
            return base_min_repeated
        return base_min_repeated + ALERT_UNHELPFUL_EXTRA_REPEATED

    def _alert_feedback_for_observation(
        self: Self,
        observation: Observation,
    ) -> tuple[str | None, Mapping[str, Any]]:
        candidates = (
            alert_feedback_fingerprint_for_observation(
                observation,
                config=self._config_for_circuit(observation.circuit_id),
            ),
            alert_feedback_fingerprint_for_observation(observation),
            _legacy_alert_feedback_key_for_observation(observation),
        )
        for fingerprint in candidates:
            feedback = self.store_data.alert_feedback.get(fingerprint)
            if not isinstance(feedback, Mapping):
                continue
            if _alert_feedback_is_expired(feedback, self._now_fn()):
                continue
            return fingerprint, feedback
        return None, {}

    def _alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._alert_policies.get(key)
        if policy is None:
            policy = _alert_policy_for_sensitivity(policy_name)
            self._alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _usage_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._usage_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=0.8,
            )
            self._usage_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _goal_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._goal_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._goal_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _billing_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._billing_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._billing_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _demand_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._demand_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._demand_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _capacity_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._capacity_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._capacity_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _leg_imbalance_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._leg_imbalance_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._leg_imbalance_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _standby_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._standby_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._standby_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _utility_comparison_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._utility_comparison_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._utility_comparison_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _nilm_topology_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._nilm_topology_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._nilm_topology_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _cycle_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._cycle_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=min_repeated * 1.5,
                min_average_score=1.5,
                min_baseline_confidence=MIN_CYCLE_BASELINE_CONFIDENCE,
            )
            self._cycle_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _activity_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._activity_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=1.0,
            )
            self._activity_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    def _water_context_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
        feature: str,
    ) -> _FeedbackAwareAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, feature, policy_name)
        policy = self._water_context_alert_policies.get(key)
        if policy is None:
            min_repeated = 4 if policy_name == "low" else 3
            policy = ConservativeAlertPolicy(
                min_repeated=min_repeated,
                min_total_score=float(min_repeated),
                min_average_score=1.0,
                min_baseline_confidence=0.7,
            )
            self._water_context_alert_policies[key] = policy
        return self._feedback_aware_alert_policy(policy)

    async def _store_alert_feedback(self: Self, alert_id: str, action: str) -> bool:
        alert = self._alert_for_id(alert_id)
        if alert is None:
            return False
        now = self._now_fn()
        fingerprint = _alert_feedback_key(
            alert,
            config=self._config_for_circuit(alert.circuit_id),
        )
        existing = self.store_data.alert_feedback.get(fingerprint, {})
        evidence_count = (
            _positive_int_value(existing.get("evidence_count"), default=0) + 1
        )
        expires_at = _alert_feedback_expires_at(action, now)
        self.store_data.alert_feedback[fingerprint] = {
            "fingerprint": fingerprint,
            "status": action,
            "action": action,
            "source_alert_id": alert_id,
            "alert_id": alert_id,
            "decided_at": now.isoformat(),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "last_seen": now.isoformat(),
            "circuit_id": alert.circuit_id,
            "feature": _alert_feature(alert),
            "change_ratio": alert.change_ratio,
            "observed_value": alert.observed_value,
            "baseline_value": alert.baseline_value,
            "evidence_count": evidence_count,
        }
        self._apply_nilm_alert_feedback(alert, action, now)
        self._retire_alert_id(alert_id)
        self._mark_store_dirty()
        self._refresh_all_ux_state(now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)
        return True

    def _apply_nilm_alert_feedback(
        self: Self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        if alert.features.get("source") != "nilm":
            return
        assignment_id = str(alert.features.get("assignment_id") or "").strip()
        if not assignment_id:
            return
        try:
            assignment = self._nilm_assignment_for_id(alert.circuit_id, assignment_id)
        except ValueError:
            return
        current_confidence = _nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        session_id = ""
        if _alert_feature(alert) == "nilm_appliance_finished":
            notification_key = str(alert.features.get("notification_key") or "").strip()
            notification_key_parts = notification_key.split(":", 1)
            if len(notification_key_parts) == 2:
                session_id = notification_key_parts[1].strip()
        confirmed = _clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = _clean_string_list(assignment.get("rejected_session_ids"))
        if action == "correct":
            assignment["confidence"] = min(1.0, round(current_confidence + 0.05, 3))
            assignment["last_validation"] = "correct"
            if session_id:
                _append_unique(confirmed, session_id)
                rejected = [value for value in rejected if value != session_id]
        elif action == "wrong_appliance":
            assignment["confidence"] = max(0.0, round(current_confidence - 0.15, 3))
            assignment["last_validation"] = "wrong_appliance"
            assignment["lifecycle_state"] = "needs_validation"
            if session_id:
                _append_unique(rejected, session_id)
                confirmed = [value for value in confirmed if value != session_id]
        else:
            return
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            _clean_string_list(assignment.get("adjusted_session_ids")),
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["updated_at"] = now.isoformat()

    def _retire_alert_id(self: Self, alert_id: str) -> None:
        """Remove an alert from stored and active evidence after user action."""
        self.store_data.alerts = [
            alert
            for alert in self.store_data.alerts
            if notifications.notification_id_for_alert(alert) != alert_id
        ]
        self.state.active_alerts_by_circuit = {
            circuit_id: [
                alert
                for alert in alerts
                if notifications.notification_id_for_alert(alert) != alert_id
            ]
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
        }
        self.state.active_alerts_by_circuit = {
            circuit_id: alerts
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
            if alerts
        }
        self.state.anomaly_score_by_circuit = {
            circuit_id: max(_alert_anomaly_score(alert) for alert in alerts)
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
        }
        self._mark_store_dirty()

    def _alert_for_id(self: Self, alert_id: str) -> AlertEvidence | None:
        alerts = list(self.store_data.alerts)
        for active_alerts in self.state.active_alerts_by_circuit.values():
            alerts.extend(active_alerts)
        for alert in alerts:
            if notifications.notification_id_for_alert(alert) == alert_id:
                return alert
        return None

    def _has_suppressed_alert_feedback(self: Self, alert: AlertEvidence) -> bool:
        _fingerprint, feedback = self._alert_feedback_for(alert)
        return _alert_feedback_status(feedback) == "expected"

    def _alert_feedback_for(
        self: Self,
        alert: AlertEvidence,
    ) -> tuple[str | None, Mapping[str, Any]]:
        candidates = (
            _alert_feedback_key(
                alert,
                config=self._config_for_circuit(alert.circuit_id),
            ),
            _alert_feedback_key(alert),
            _legacy_alert_feedback_key(alert),
        )
        for fingerprint in candidates:
            feedback = self.store_data.alert_feedback.get(fingerprint)
            if not isinstance(feedback, Mapping):
                continue
            if _alert_feedback_is_expired(feedback, self._now_fn()):
                continue
            return fingerprint, feedback
        return None, {}

    def _alert_with_feedback(self: Self, alert: AlertEvidence) -> AlertEvidence:
        fingerprint, feedback = self._alert_feedback_for(alert)
        status = _alert_feedback_status(feedback)
        if fingerprint is None or status is None:
            return alert
        return replace(
            alert,
            feedback_status=status,
            feedback_effect=_alert_feedback_effect(status),
            feedback_expires_at=_mapping_datetime(feedback.get("expires_at")),
            matching_feedback_fingerprint=fingerprint,
        )

    def _nilm_signature_for_review(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> dict[str, Any]:
        signatures = self.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                return signature
        signature = {"signature_id": signature_id, "review_state": "new"}
        signatures.append(signature)
        return signature

    def _mark_store_dirty(self: Self) -> None:
        self.store_persistence.mark_dirty()

    @property
    def _store_dirty(self: Self) -> bool:
        return self.store_persistence.dirty

    @_store_dirty.setter
    def _store_dirty(self: Self, value: bool) -> None:
        self.store_persistence.dirty = bool(value)

    @property
    def _notified_alert_ids(self: Self) -> set[str]:
        return self.notification_controller.notified_alert_ids

    @property
    def _settings_recommendation_notification_episode_key(
        self: Self,
    ) -> tuple[tuple[str, ...], ...]:
        return (
            self.notification_controller.settings_recommendation_notification_episode_key
        )

    @property
    def _active_repair_issues(self: Self) -> set[tuple[str, str]]:
        return self.setup_health.active_repair_issues

    async def _apply_feature_result(
        self: Self,
        result: FeatureResult,
    ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
        """Apply processor output to coordinator-owned state and side effects."""
        stored_alerts = [self._alert_with_feedback(alert) for alert in result.alerts]
        active_alerts = [
            alert
            for alert in stored_alerts
            if alert.feedback_status != "expected"
        ]
        if result.events:
            self.store_data.events.extend(result.events)
        if stored_alerts:
            self.store_data.alerts.extend(stored_alerts)
        for observation in result.observations:
            self._record_recent_observation(observation)
        for update in result.state_updates:
            self.state_reducer.apply_update(self.state, update.path, update.value)
        for alert in result.notifications:
            await self._notify_alert(self._alert_with_feedback(alert))
        if result.store_dirty or result.events or stored_alerts:
            self._mark_store_dirty()
        return list(result.events), active_alerts

    async def _async_save_store(self: Self, now: datetime) -> None:
        await self.store_persistence.async_save_if_dirty(now)

    def _apply_retention(self: Self, now: datetime) -> None:
        retained_events = [
            event for event in self.store_data.events if self._keep_event(event, now)
        ]
        if len(retained_events) != len(self.store_data.events):
            self.store_data.events = retained_events
        self._prune_energy_usage(now)
        self._prune_demand(now)
        self._prune_standby(now)
        self._prune_weather_context(now)
        self._prune_water_context(now)
        self._prune_contextual_baseline_state(now)
        self._prune_alert_history(now)
        self._prune_nilm_history(now)
        self._prune_alert_feedback(now)
        self._prune_recommendation_history(now)

    def _observation_payload(self: Self, observation: Any) -> dict[str, Any]:
        payload = {
            "timestamp": observation.observed_at.isoformat(),
            "circuit_id": observation.circuit_id,
            "feature": observation.feature,
            "feature_name": friendly_feature_name(observation.feature),
            "message": observation.message,
            "score": observation.score,
            "baseline_confidence": observation.baseline_confidence,
            "observed_value": observation.observed_value,
            "baseline_value": observation.baseline_value,
        }
        if getattr(observation, "observation_key", None) is not None:
            payload["observation_key"] = observation.observation_key
        return payload

    def _record_recent_observation(self: Self, observation: Any) -> None:
        payload = self._observation_payload(observation)
        observations = self.state.recent_observations_by_circuit.setdefault(
            observation.circuit_id,
            [],
        )
        observation_key = payload.get("observation_key")
        if observation_key is not None:
            for index, existing in enumerate(observations):
                if existing.get("observation_key") == observation_key:
                    observations[index] = payload
                    return
        observations.append(payload)

    def _prune_recent_observations(self: Self, now: datetime) -> None:
        cutoff = now - timedelta(hours=DEFAULT_TIMELINE_WINDOW_HOURS)
        retained: dict[str, list[dict[str, Any]]] = {}
        for (
            circuit_id,
            observations,
        ) in self.state.recent_observations_by_circuit.items():
            kept = [
                observation
                for observation in observations
                if _observation_within_cutoff(observation, cutoff)
            ]
            if kept:
                retained[circuit_id] = kept
        self.state.recent_observations_by_circuit = retained

    def _keep_event(self: Self, event: CircuitEvent, now: datetime) -> bool:
        retention_mode = self._retention_mode_for_circuit(event.circuit_id)
        return event.timestamp >= now - RETENTION_WINDOWS[retention_mode]

    def _prune_energy_usage(self: Self, now: datetime) -> None:
        for circuit_id, history in self.store_data.energy_usage_by_circuit.items():
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff = (
                _ha_local_date(now, self._ha_time_zone())
                - RETENTION_WINDOWS[retention_mode]
            ).isoformat()
            days = history.get("days", [])
            if not isinstance(days, list):
                continue
            history["days"] = [
                day
                for day in days
                if isinstance(day, dict) and str(day.get("date", "")) >= cutoff
            ]

    def _prune_demand(self: Self, now: datetime) -> None:
        for circuit_id, history in self.store_data.demand_by_circuit.items():
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff_datetime = now - RETENTION_WINDOWS[retention_mode]
            cutoff = (
                _ha_local_date(now, self._ha_time_zone())
                - RETENTION_WINDOWS[retention_mode]
            ).isoformat()
            capacity_samples = history.get("capacity_current_samples")
            if isinstance(capacity_samples, list):
                history["capacity_current_samples"] = [
                    sample
                    for sample in capacity_samples
                    if _sample_timestamp_is_at_or_after(sample, cutoff_datetime)
                ]
            daily_peaks = history.get("daily_peaks", [])
            if isinstance(daily_peaks, list):
                history["daily_peaks"] = [
                    peak
                    for peak in daily_peaks
                    if isinstance(peak, dict)
                    and str(peak.get("date", "")) >= cutoff
                ]

    def _prune_standby(self: Self, now: datetime) -> None:
        for circuit_id, history in self.store_data.standby_by_circuit.items():
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff = now - RETENTION_WINDOWS[retention_mode]
            samples = history.get("samples", [])
            if isinstance(samples, list):
                history["samples"] = [
                    sample
                    for sample in samples
                    if _sample_timestamp_is_at_or_after(sample, cutoff)
                ]

    def _prune_weather_context(self: Self, now: datetime) -> None:
        for circuit_id, history in (
            self.store_data.weather_context_history_by_circuit.items()
        ):
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff = now - RETENTION_WINDOWS[retention_mode]
            self.store_data.weather_context_history_by_circuit[circuit_id] = [
                sample
                for sample in history
                if _sample_timestamp_is_at_or_after(sample, cutoff)
            ][-WEATHER_CONTEXT_HISTORY_MAX_SAMPLES:]

    def _prune_water_context(self: Self, now: datetime) -> None:
        for circuit_id, history in (
            self.store_data.water_context_history_by_circuit.items()
        ):
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff = now - RETENTION_WINDOWS[retention_mode]
            self.store_data.water_context_history_by_circuit[circuit_id] = [
                sample
                for sample in history
                if _sample_timestamp_is_at_or_after(sample, cutoff)
            ][-WATER_CONTEXT_HISTORY_MAX_SAMPLES:]

    def _prune_contextual_baseline_state(self: Self, now: datetime) -> None:
        pruned_samples: dict[str, list[dict[str, Any]]] = {}
        pruned_stats: dict[str, dict[str, Any]] = {}
        circuit_ids = set(self.store_data.contextual_baseline_samples_by_circuit) | set(
            self.store_data.contextual_baselines_by_circuit
        )
        for circuit_id in circuit_ids:
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            samples = self.store_data.contextual_baseline_samples_by_circuit.get(
                circuit_id,
                [],
            )
            stats = self.store_data.contextual_baselines_by_circuit.get(
                circuit_id,
                {},
            )
            samples_by_circuit, stats_by_circuit = prune_contextual_baseline_state(
                {circuit_id: samples},
                {circuit_id: stats},
                retention_mode,
                now,
            )
            if samples_by_circuit.get(circuit_id):
                pruned_samples[circuit_id] = samples_by_circuit[circuit_id]
            if stats_by_circuit.get(circuit_id):
                pruned_stats[circuit_id] = stats_by_circuit[circuit_id]
        self.store_data.contextual_baseline_samples_by_circuit = pruned_samples
        self.store_data.contextual_baselines_by_circuit = pruned_stats

    def _prune_alert_history(self: Self, now: datetime) -> None:
        cutoff = now - ALERT_HISTORY_MAX_AGE
        self.store_data.alerts = sorted(
            (alert for alert in self.store_data.alerts if alert.timestamp >= cutoff),
            key=lambda alert: alert.timestamp,
            reverse=True,
        )[:ALERT_HISTORY_MAX_ITEMS]

    def _prune_nilm_history(self: Self, now: datetime) -> None:
        for circuit_id, signatures in self.store_data.nilm_signatures.items():
            self.store_data.nilm_signatures[circuit_id] = _newest_mapping_items(
                signatures,
                NILM_SIGNATURES_MAX_ITEMS_PER_CIRCUIT,
            )
        for inventory in self.store_data.nilm_unknown_loads_by_circuit.values():
            unknown_loads = inventory.get("unknown_loads")
            if isinstance(unknown_loads, list):
                inventory["unknown_loads"] = _newest_mapping_items(
                    unknown_loads,
                    NILM_UNKNOWN_LOADS_MAX_ITEMS_PER_CIRCUIT,
                )
        cutoff = now - NILM_SESSION_HISTORY_MAX_AGE
        for circuit_id, sessions in list(
            self.store_data.nilm_session_history_by_circuit.items()
        ):
            retained = [
                dict(session)
                for session in sessions
                if isinstance(session, Mapping)
                and _mapping_time(
                    session,
                    "end",
                    "start",
                    "updated_at",
                    "created_at",
                    "timestamp",
                )
                >= cutoff
            ]
            self.store_data.nilm_session_history_by_circuit[circuit_id] = sorted(
                retained,
                key=lambda session: _mapping_time(
                    session,
                    "end",
                    "start",
                    "updated_at",
                    "created_at",
                    "timestamp",
                ),
                reverse=True,
            )[:NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT]

    def _prune_alert_feedback(self: Self, now: datetime) -> None:
        cutoff = now - ALERT_FEEDBACK_MAX_AGE
        retained = {
            key: value
            for key, value in self.store_data.alert_feedback.items()
            if not _alert_feedback_is_expired(value, now)
            and _mapping_time(value, "created_at", "timestamp") >= cutoff
        }
        self.store_data.alert_feedback = dict(
            sorted(
                retained.items(),
                key=lambda item: _mapping_time(item[1], "created_at", "timestamp"),
                reverse=True,
            )[:ALERT_FEEDBACK_MAX_ITEMS]
        )

    def _prune_recommendation_history(self: Self, now: datetime) -> None:
        cutoff = now - RECOMMENDATION_HISTORY_MAX_AGE
        recommendations = {
            recommendation_id: recommendation
            for recommendation_id, recommendation in (
                self.store_data.settings_recommendations.items()
            )
            if recommendation.status is RecommendationStatus.PENDING
            or recommendation.created_at >= cutoff
        }
        self.store_data.settings_recommendations = dict(
            sorted(
                recommendations.items(),
                key=lambda item: _recommendation_sort_key(item[1]),
                reverse=True,
            )[:RECOMMENDATION_HISTORY_MAX_ITEMS]
        )

        decision_cutoff = now - RECOMMENDATION_DECISIONS_MAX_AGE
        decisions = {
            unique_key: decision
            for unique_key, decision in (
                self.store_data.settings_recommendation_decisions.items()
            )
            if decision.decided_at >= decision_cutoff
        }
        self.store_data.settings_recommendation_decisions = dict(
            sorted(
                decisions.items(),
                key=lambda item: item[1].decided_at,
                reverse=True,
            )[:RECOMMENDATION_DECISIONS_MAX_ITEMS]
        )
        self.store_data.settings_recommendation_notification_episode_key = (
            _compact_settings_recommendation_episode_key(
                self.store_data.settings_recommendation_notification_episode_key
            )
        )

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
        states: dict[str, SourceState] = {}
        hass_states = getattr(self.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return states

        registered_demo_entity_ids = self._registered_demo_source_entity_ids()
        for sensor in config.sensors:
            raw_state = get_state(sensor.entity_id)
            if raw_state is None and _is_demo_source_entity_id(sensor.entity_id):
                registered_entity_id = registered_demo_entity_ids.get(
                    sensor.entity_id
                )
                if (
                    registered_entity_id is not None
                    and registered_entity_id != sensor.entity_id
                ):
                    raw_state = get_state(registered_entity_id)
            if raw_state is None:
                continue
            attributes = getattr(raw_state, "attributes", {}) or {}
            last_updated = getattr(raw_state, "last_updated", now) or now
            if _is_demo_source_entity_id(sensor.entity_id):
                last_updated = now
            states[sensor.entity_id] = SourceState(
                entity_id=sensor.entity_id,
                state=str(getattr(raw_state, "state", "")),
                unit=attributes.get("unit_of_measurement") or sensor.unit,
                last_updated=last_updated,
                device_class=attributes.get("device_class"),
                state_class=attributes.get("state_class"),
            )
        return states

    def _registered_demo_source_entity_ids(self: Self) -> dict[str, str]:
        if self.hass is None:
            return {}
        registry = None
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
        except (ImportError, AttributeError, TypeError):
            registry = getattr(self.hass, "entity_registry", None)
        if registry is None:
            return {}
        entries = getattr(registry, "entities", {})
        values = entries.values() if hasattr(entries, "values") else entries
        registered: dict[str, str] = {}
        unique_id_prefix = f"{self.entry_id}_{_DEMO_SOURCE_UNIQUE_ID_PREFIX}"
        for registry_entry in values:
            unique_id = str(getattr(registry_entry, "unique_id", ""))
            if not unique_id.startswith(unique_id_prefix):
                continue
            if (
                getattr(registry_entry, "config_entry_id", self.entry_id)
                != self.entry_id
            ):
                continue
            if getattr(registry_entry, "platform", DOMAIN) != DOMAIN:
                continue
            canonical_entity_id = f"sensor.{unique_id.removeprefix(unique_id_prefix)}"
            registered[canonical_entity_id] = str(
                getattr(registry_entry, "entity_id", canonical_entity_id)
            )
        return registered


    def _activity_alert_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> ActivityAlertSettings:
        del config
        overrides = self.store_data.activity_alert_settings_by_circuit.get(
            circuit_id,
            {},
        )
        return ActivityAlertSettings(
            max_active_minutes=_optional_positive_float_value(
                overrides.get("max_active_minutes"),
                default=None,
            ),
            max_idle_minutes=_optional_positive_float_value(
                overrides.get("max_idle_minutes"),
                default=None,
            ),
        )

    def _energy_usage_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyUsageSettings:
        overrides = self.store_data.energy_usage_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_window_days = (
            config.energy_usage_window_days if config is not None else 7
        )
        default_spike_ratio = (
            config.daily_energy_spike_ratio if config is not None else 0.25
        )
        return EnergyUsageSettings(
            window_days=_positive_int_value(
                overrides.get("window_days"),
                default=default_window_days,
            ),
            daily_spike_ratio=_positive_float_value(
                overrides.get("daily_spike_ratio"),
                default=default_spike_ratio,
            ),
        )

    def _energy_goal_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyGoalSettings:
        overrides = self.store_data.energy_goal_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_goal_kwh = (
            config.daily_energy_goal_kwh if config is not None else None
        )
        default_alert_ratio = (
            config.energy_goal_alert_ratio if config is not None else 1.0
        )
        if "daily_goal_kwh" in overrides:
            goal_kwh = _optional_positive_float_value(
                overrides.get("daily_goal_kwh"),
                default=None,
            )
        else:
            goal_kwh = default_goal_kwh
        return EnergyGoalSettings(
            daily_goal_kwh=goal_kwh,
            goal_alert_ratio=_positive_float_value(
                overrides.get("goal_alert_ratio"),
                default=default_alert_ratio,
            ),
        )

    def _billing_cycle_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> BillingCycleSettings:
        overrides = self.store_data.billing_settings_by_circuit.get(circuit_id, {})
        default_start_day = (
            config.billing_cycle_start_day if config is not None else 1
        )
        default_budget_kwh = (
            config.billing_cycle_budget_kwh if config is not None else None
        )
        default_alert_ratio = (
            config.billing_cycle_budget_alert_ratio if config is not None else 1.0
        )
        default_min_elapsed_days = (
            config.billing_cycle_min_elapsed_days if config is not None else 3
        )
        return BillingCycleSettings(
            cycle_start_day=_positive_int_value(
                overrides.get("cycle_start_day"),
                default=default_start_day,
            ),
            budget_kwh=_optional_positive_float_value(
                overrides.get("budget_kwh"),
                default=default_budget_kwh,
            ),
            budget_alert_ratio=_positive_float_value(
                overrides.get("budget_alert_ratio"),
                default=default_alert_ratio,
            ),
            min_elapsed_days=_positive_int_value(
                overrides.get("min_elapsed_days"),
                default=default_min_elapsed_days,
            ),
        )

    def _cost_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> CostSettings:
        overrides = self.store_data.cost_settings_by_circuit.get(circuit_id, {})
        default_start_day = config.cost_cycle_start_day if config is not None else 1
        default_rate = config.default_rate_per_kwh if config is not None else None
        default_tou_rate = config.tou_rate_per_kwh if config is not None else None
        default_tou_start = config.tou_start if config is not None else None
        default_tou_end = config.tou_end if config is not None else None
        default_tou_weekdays = config.tou_weekdays if config is not None else ()
        default_tou_name = config.tou_name if config is not None else "Peak"
        return CostSettings(
            cycle_start_day=_positive_int_value(
                overrides.get("cycle_start_day"),
                default=default_start_day,
            ),
            default_rate_per_kwh=_optional_positive_float_value(
                overrides.get("default_rate_per_kwh"),
                default=default_rate,
            ),
            tou_rate_per_kwh=_optional_positive_float_value(
                overrides.get("tou_rate_per_kwh"),
                default=default_tou_rate,
            ),
            tou_start=str(overrides.get("tou_start") or default_tou_start or ""),
            tou_end=str(overrides.get("tou_end") or default_tou_end or ""),
            tou_weekdays=_weekday_tuple_value(
                overrides.get("tou_weekdays"),
                default=default_tou_weekdays,
            ),
            tou_name=str(overrides.get("tou_name") or default_tou_name or "Peak"),
        )

    def _demand_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> DemandSettings:
        overrides = self.store_data.demand_settings_by_circuit.get(circuit_id, {})
        default_window_minutes = (
            config.demand_window_minutes if config is not None else 15
        )
        default_limit_w = config.demand_limit_w if config is not None else None
        return DemandSettings(
            window_minutes=_positive_int_value(
                overrides.get("window_minutes"),
                default=default_window_minutes,
            ),
            demand_limit_w=_optional_positive_float_value(
                overrides.get("demand_limit_w"),
                default=default_limit_w,
            ),
        )

    def _capacity_settings_for_config(self: Self, circuit_id: str) -> CapacitySettings:
        overrides = self.store_data.capacity_settings_by_circuit.get(circuit_id, {})
        return CapacitySettings(
            breaker_amps=_optional_positive_float_value(
                overrides.get("breaker_amps"),
                default=None,
            ),
            warning_ratio=_positive_float_value(
                overrides.get("warning_ratio"),
                default=DEFAULT_CAPACITY_WARNING_RATIO,
            ),
        )

    def _standby_settings_for_config(
        self: Self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> StandbySettings:
        overrides = self.store_data.standby_settings_by_circuit.get(circuit_id, {})
        default_window_hours = (
            config.standby_window_hours if config is not None else 48
        )
        default_threshold_w = config.standby_threshold_w if config is not None else 8.0
        default_alert_w = config.always_on_alert_w if config is not None else None
        default_min_samples = config.standby_min_samples if config is not None else 24
        return StandbySettings(
            window_hours=_positive_int_value(
                overrides.get("window_hours"),
                default=default_window_hours,
            ),
            standby_threshold_w=_positive_float_value(
                overrides.get("standby_threshold_w"),
                default=default_threshold_w,
            ),
            always_on_alert_w=_optional_positive_float_value(
                overrides.get("always_on_alert_w"),
                default=default_alert_w,
            ),
            min_samples=_positive_int_value(
                overrides.get("min_samples"),
                default=default_min_samples,
            ),
        )

    def _utility_comparison_settings_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> UtilityComparisonSettings:
        overrides = self.store_data.utility_comparison_settings_by_circuit.get(
            circuit_id,
            {},
        )
        return UtilityComparisonSettings(
            utility_energy_entity=str(overrides.get("utility_energy_entity") or ""),
            utility_statistic_id=str(overrides.get("utility_statistic_id") or ""),
            utility_source_type=str(overrides.get("utility_source_type") or "auto"),
            utility_statistic_period=_utility_statistic_period_value(
                overrides.get("utility_statistic_period")
            ),
            measured_energy_entities=_entity_id_tuple_value(
                overrides.get("measured_energy_entities"),
                default=(),
            ),
            tolerance_percent=_nonnegative_float_value(
                overrides.get("tolerance_percent"),
                default=DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
            ),
        )

    def _clear_power_quality_state(self: Self, circuit_id: str) -> None:
        self.state.power_quality_score_by_circuit.pop(circuit_id, None)
        self.state.power_quality_evidence_by_circuit.pop(circuit_id, None)
        self.state.reactive_power_drift_by_circuit.pop(circuit_id, None)
        self.state.apparent_power_drift_by_circuit.pop(circuit_id, None)
        self.state.power_factor_drift_by_circuit.pop(circuit_id, None)

    def _clear_nilm_topology_state(self: Self, circuit_id: str) -> None:
        self.state.nilm_topology_status_by_circuit.pop(circuit_id, None)
        self.state.nilm_topology_evidence_by_circuit.pop(circuit_id, None)
        for key in list(self._nilm_topology_alert_policies):
            if key[0] == circuit_id:
                self._nilm_topology_alert_policies.pop(key, None)

    def _clear_standby_state(self: Self, circuit_id: str) -> None:
        self.state.always_on_power_w_by_circuit.pop(circuit_id, None)
        self.state.standby_threshold_w_by_circuit.pop(circuit_id, None)
        self.state.standby_status_by_circuit.pop(circuit_id, None)
        self.state.always_on_limit_usage_by_circuit.pop(circuit_id, None)
        self.state.standby_evidence_by_circuit.pop(circuit_id, None)

    def _learning_mature(self: Self, config: CircuitConfig, now: datetime) -> bool:
        profile = get_profile_definition(config.appliance_profile)
        circuit_events = [
            event
            for event in self.store_data.events
            if event.circuit_id == config.circuit_id
        ]
        cycle_count = sum(
            1 for event in circuit_events if event.event_type is EventType.START
        )
        if profile.minimum_cycles > 0 and cycle_count >= profile.minimum_cycles:
            return True

        if not circuit_events:
            return False

        first_seen = min(event.timestamp for event in circuit_events)
        return now - first_seen >= timedelta(days=profile.minimum_learning_days)

    async def _notify_alert(self: Self, alert: AlertEvidence) -> None:
        await self.notification_controller.async_notify_alert(alert)

    async def _notify_nilm_virtual_appliances(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        active_alerts: list[AlertEvidence] = []
        for alert in nilm_virtual_appliance_alerts(self, now=now):
            alert = self._alert_with_feedback(alert)
            alert_id = notifications.notification_id_for_alert(alert)
            if alert.feedback_status != "expected":
                active_alerts.append(alert)
            if alert_id in self._notified_alert_ids:
                continue
            self.store_data.alerts.append(alert)
            self._mark_store_dirty()
            await self._notify_alert(alert)
        return active_alerts


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


def _sum_optional_values(*raw_values: Any) -> float | None:
    values = _numeric_items(raw_values)
    if not values:
        return None
    return sum(abs(value) for value in values)


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_amps(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _utility_statistic_period_value(value: Any) -> str:
    normalized = str(value or DEFAULT_UTILITY_STATISTIC_PERIOD).strip().lower()
    if normalized not in {"hour", "day", "month"}:
        return DEFAULT_UTILITY_STATISTIC_PERIOD
    return normalized


def _statistics_lookback_start(now: datetime, period: str) -> datetime:
    if period == "hour":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=400)
    return now - timedelta(days=45)


def _demo_seed_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _demo_nilm_edges(value: Any) -> list[NilmEdge]:
    edges: list[NilmEdge] = []
    for raw_edge in _demo_seed_list(value):
        timestamp = _datetime_or_none(raw_edge.pop("timestamp", None))
        if timestamp is None:
            continue
        try:
            edges.append(NilmEdge(timestamp=timestamp, **raw_edge))
        except TypeError:
            continue
    return edges


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


def _observation_within_cutoff(
    observation: Mapping[str, Any],
    cutoff: datetime,
) -> bool:
    observed_at = _datetime_or_none(observation.get("timestamp"))
    return observed_at is not None and observed_at >= cutoff


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


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _alert_feedback_key(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
) -> str:
    return alert_feedback_fingerprint(alert, config=config)


def _legacy_alert_feedback_key(alert: AlertEvidence) -> str:
    return f"{alert.circuit_id}:{_alert_feature(alert)}"


def _legacy_alert_feedback_key_for_observation(observation: Observation) -> str:
    return f"{observation.circuit_id}:{observation.feature or 'alert'}"


def _alert_feedback_status(feedback: Mapping[str, Any]) -> str | None:
    status = feedback.get("status") or feedback.get("action")
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    return normalized or None


def _alert_feedback_effect(status: str) -> str:
    if status == "expected":
        return "Notifications suppressed for this expected pattern"
    if status == "unhelpful":
        return "Future matching alerts require stronger repeated evidence"
    return "Feedback recorded for this alert pattern"


def _alert_feedback_expires_at(action: str, now: datetime) -> datetime | None:
    if action == "expected":
        return now + ALERT_EXPECTED_FEEDBACK_TTL
    if action == "unhelpful":
        return now + ALERT_UNHELPFUL_FEEDBACK_TTL
    return None


def _alert_feedback_is_expired(
    feedback: Mapping[str, Any],
    now: datetime,
) -> bool:
    expires_at = _mapping_datetime(feedback.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at <= _datetime_with_matching_timezone(now, expires_at)


def _mapping_datetime(value: Any) -> datetime | None:
    return _datetime_or_none(value)


def _datetime_with_matching_timezone(now: datetime, target: datetime) -> datetime:
    if target.tzinfo is None and now.tzinfo is not None:
        return now.replace(tzinfo=None)
    if target.tzinfo is not None and now.tzinfo is None:
        return now.replace(tzinfo=target.tzinfo)
    return now


def _normalized_temperature_unit(unit: str) -> str:
    normalized = str(unit or "").strip().lower()
    if normalized in {"°f", "f", "fahrenheit"}:
        return "°F"
    if normalized in {"°c", "c", "celsius"}:
        return "°C"
    if normalized in {"k", "kelvin"}:
        return "K"
    return ""


def _temperature_to_fahrenheit(value: float, unit: str) -> float:
    if unit == "°C":
        return (value * 9.0 / 5.0) + 32.0
    if unit == "K":
        return ((value - 273.15) * 9.0 / 5.0) + 32.0
    return value


def _temperature_from_fahrenheit(value: float, unit: str) -> float:
    if unit == "°C":
        return (value - 32.0) * 5.0 / 9.0
    return value


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


def _parallel_leg_samples(
    sensor_samples: Iterable[tuple[SensorRef, NormalizedCircuitSample]],
) -> tuple[NormalizedCircuitSample | None, NormalizedCircuitSample | None]:
    items = list(sensor_samples)
    leg_a = next(
        (
            sample
            for sensor, sample in items
            if sensor.role is SensorRole.REAL_POWER
            and _normalized_leg(sensor.leg) == "a"
        ),
        None,
    )
    leg_b = next(
        (
            sample
            for sensor, sample in items
            if sensor.role is SensorRole.REAL_POWER
            and _normalized_leg(sensor.leg) == "b"
        ),
        None,
    )
    if leg_a is not None or leg_b is not None:
        return leg_a, leg_b

    hinted_leg_a = next(
        (
            sample
            for sensor, sample in items
            if sensor.role is SensorRole.REAL_POWER
            and _entity_id_leg_hint(sensor.entity_id) == "a"
        ),
        None,
    )
    hinted_leg_b = next(
        (
            sample
            for sensor, sample in items
            if sensor.role is SensorRole.REAL_POWER
            and _entity_id_leg_hint(sensor.entity_id) == "b"
        ),
        None,
    )
    if hinted_leg_a is not None or hinted_leg_b is not None:
        return hinted_leg_a, hinted_leg_b
    return None, None


def _entity_id_leg_hint(entity_id: str) -> str | None:
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in str(entity_id).lower()
    )
    padded = f"_{normalized}_"
    if any(
        pattern in padded
        for pattern in (
            "_l1_",
            "_leg1_",
            "_leg_1_",
            "_line1_",
            "_line_1_",
            "_phase1_",
            "_phase_1_",
            "_leg_a_",
            "_line_a_",
            "_phase_a_",
        )
    ):
        return "a"
    if any(
        pattern in padded
        for pattern in (
            "_l2_",
            "_leg2_",
            "_leg_2_",
            "_line2_",
            "_line_2_",
            "_phase2_",
            "_phase_2_",
            "_leg_b_",
            "_line_b_",
            "_phase_b_",
        )
    ):
        return "b"
    return None


def _sample_value_or_none(
    sample: NormalizedCircuitSample | None,
    attribute: str,
) -> float | None:
    if sample is None:
        return None
    value = getattr(sample, attribute, None)
    if value is None:
        return None
    return float(value)


def _sum_complete_sample_values(
    samples: Iterable[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    total = 0.0
    has_values = False
    for sample in samples:
        value = getattr(sample, attribute, None)
        if value is None:
            return None
        total += float(value)
        has_values = True
    if not has_values:
        return None
    return total


def _sum_parallel_sensor_values(
    sensor_samples: Iterable[tuple[SensorRef, NormalizedCircuitSample]],
    attribute: str,
    role: SensorRole,
) -> float | None:
    return _sum_complete_sample_values(
        [
            sample
            for sensor, sample in sensor_samples
            if sensor.role is role
        ],
        attribute,
    )


def _average_sample_values(
    samples: Iterable[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    values = [
        value
        for sample in samples
        if (value := getattr(sample, attribute, None)) is not None
    ]
    if not values:
        return None
    return float(sum(values) / len(values))


def _demand_power_w(sample: Any) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    if power_flow is PowerFlowMode.MAINS_NET:
        return max(float(power), 0.0)
    return max(float(power), 0.0)


def _power_flow_direction(
    raw_real_power: float | None,
    power_flow: PowerFlowMode,
) -> str | None:
    if raw_real_power is None:
        return None
    if power_flow is PowerFlowMode.LOAD:
        return "unexpected_export" if raw_real_power < 0 else "load"
    if power_flow is PowerFlowMode.GENERATION:
        return "export" if raw_real_power < 0 else "import"
    if raw_real_power > 0:
        return "import"
    if raw_real_power < 0:
        return "export"
    return "balanced"


def _normalized_leg(leg: str | None) -> str | None:
    if leg is None:
        return None
    value = leg.strip().lower()
    if value in {"a", "left", "l1", "line1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "line2", "2"}:
        return "b"
    return None


def _string_list_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    key: str,
) -> list[str]:
    options = options or {}
    raw = options[key] if key in options else entry_data.get(key, [])
    if isinstance(raw, str):
        return [raw] if raw else []
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def _strings_from_any(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


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


def _alert_policy_for_sensitivity(sensitivity: str) -> ConservativeAlertPolicy:
    policy_name = alert_policy_name_for_sensitivity(sensitivity)
    if policy_name == "high":
        return ConservativeAlertPolicy(
            min_repeated=3,
            min_total_score=2.4,
            min_average_score=1.2,
        )
    if policy_name == "low":
        return ConservativeAlertPolicy(
            min_repeated=4,
            min_total_score=6.0,
            min_average_score=1.8,
        )
    return ConservativeAlertPolicy()


def _nilm_min_delta_w(sensitivity: str) -> float:
    policy_name = alert_policy_name_for_sensitivity(sensitivity)
    if policy_name == "high":
        return 75.0
    if policy_name == "low":
        return 150.0
    return 100.0


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


def _friendly_circuit_mode(mode: CircuitMode) -> str:
    return {
        CircuitMode.SINGLE_PHASE: "Single Phase",
        CircuitMode.DUAL_PHASE: "Dual Phase",
        CircuitMode.MIXED: "Mixed",
        CircuitMode.MAINS_NILM: "Mains NILM",
    }.get(mode, "Unknown")


def _friendly_power_flow(power_flow: PowerFlowMode) -> str:
    return {
        PowerFlowMode.LOAD: "Load",
        PowerFlowMode.GENERATION: "Generation / Solar Export",
        PowerFlowMode.MAINS_NET: "Mains Net / Import-Export",
    }.get(power_flow, "Unknown")


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


def _optional_float_value(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _absolute_float_value(value: Any) -> float:
    parsed = _optional_float_value(value)
    return abs(parsed) if parsed is not None else 0.0


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


def _energy_value_kwh(value: float, unit: Any) -> float:
    normalized = str(unit or "kWh").strip().lower()
    if normalized == "wh":
        return round(value / 1000.0, 3)
    if normalized == "mwh":
        return round(value * 1000.0, 3)
    return round(value, 3)


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


async def _async_recorder_executor_job(hass: Any, target: Any, *args: Any) -> Any:
    if _ha_recorder_get_instance is not None:
        try:
            recorder = _ha_recorder_get_instance(hass)
        except Exception:
            recorder = None
        add_recorder_job = getattr(recorder, "async_add_executor_job", None)
        if callable(add_recorder_job):
            return await add_recorder_job(target, *args)

    raise RuntimeError("recorder executor is not available")


def _lovelace_dashboard_matches(item: Any, payload: Mapping[str, Any]) -> bool:
    target = _normalize_lovelace_path(payload.get("url_path"))
    if not target:
        return False
    return any(
        _normalize_lovelace_path(_lovelace_dashboard_item_value(item, key)) == target
        for key in ("url_path", "id")
    )


def _lovelace_data_from_hass(hass: Any) -> Any:
    hass_data = getattr(hass, "data", {})
    if isinstance(hass_data, Mapping):
        return hass_data.get("lovelace", {})
    return getattr(hass_data, "lovelace", {})


async def _async_load_lovelace_dashboards_collection(
    hass: Any,
    lovelace_data: Any,
) -> Any | None:
    del lovelace_data
    try:
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard
    except ImportError:
        return None

    collection = lovelace_dashboard.DashboardsCollection(hass)
    async_load = getattr(collection, "async_load", None)
    if callable(async_load):
        await _async_lovelace_method_result(async_load())
    return collection


def _lovelace_dashboards(lovelace_data: Any) -> MutableMapping[Any, Any] | None:
    dashboards = _lovelace_dashboard_item_value(lovelace_data, "dashboards")
    return dashboards if isinstance(dashboards, MutableMapping) else None


def _lovelace_dashboard_storage_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "config"}


def _lovelace_dashboard_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config")
    return dict(config) if isinstance(config, Mapping) else {}


async def _async_save_lovelace_dashboard_config(
    hass: Any,
    lovelace_data: Any,
    item: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    update: bool,
) -> bool:
    dashboards = _lovelace_dashboards(lovelace_data)
    if dashboards is None:
        return False

    url_path = _normalize_lovelace_path(
        _lovelace_dashboard_item_value(item, "url_path")
    )
    if not url_path:
        return False

    dashboard_store = dashboards.get(url_path)
    if dashboard_store is None:
        dashboard_store = _new_lovelace_storage(hass, item)
        if dashboard_store is None:
            return False
        dashboards[url_path] = dashboard_store

    if hasattr(dashboard_store, "config"):
        dashboard_store.config = dict(item)

    save = getattr(dashboard_store, "async_save", None)
    if not callable(save):
        return False
    save_config = dict(config)
    if not await _async_ensure_lovelace_dashboard_graph_resource(
        lovelace_data,
        save_config,
    ):
        save_config = _lovelace_config_without_card_type(
            save_config,
            NILM_DASHBOARD_GRAPHS_CARD,
        )
    await _async_lovelace_method_result(save(save_config))
    _register_lovelace_dashboard_panel(hass, item, update=update)
    return True


async def _async_ensure_lovelace_dashboard_graph_resource(
    lovelace_data: Any,
    config: Mapping[str, Any],
) -> bool:
    if not dashboard_includes_nilm_graph_card(config):
        return True

    resources = _lovelace_dashboard_item_value(lovelace_data, "resources")
    if resources is None:
        return False

    async_load = getattr(resources, "async_load", None)
    if callable(async_load) and not getattr(resources, "loaded", True):
        await _async_lovelace_method_result(async_load())
        if hasattr(resources, "loaded"):
            resources.loaded = True

    items_method = getattr(resources, "async_items", None)
    if not callable(items_method):
        return False

    resource = dashboard_graph_module_resource()
    items = await _async_lovelace_method_result(items_method())
    existing = next(
        (
            item
            for item in items
            if _lovelace_resource_matches_static_url(item, resource)
        ),
        None,
    )
    resource_payload = _lovelace_resource_update_payload(resource)
    if existing is None:
        create_method = getattr(resources, "async_create_item", None)
        if not callable(create_method):
            return False
        await _async_lovelace_method_result(create_method(resource_payload))
        return True

    if _lovelace_resource_has_current_values(existing, resource):
        return True

    update_method = getattr(resources, "async_update_item", None)
    item_id = _lovelace_dashboard_item_value(existing, "id")
    if callable(update_method) and item_id:
        await _async_lovelace_method_result(
            update_method(str(item_id), resource_payload)
        )
        return True
    return False


def _lovelace_config_without_card_type(
    config: Mapping[str, Any],
    card_type: str,
) -> dict[str, Any]:
    remove = object()

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            if value.get("type") == card_type:
                return remove
            cleaned: dict[str, Any] = {}
            for key, nested in value.items():
                cleaned_value = clean(nested)
                if cleaned_value is not remove:
                    cleaned[key] = cleaned_value
            return cleaned
        if isinstance(value, list):
            return [
                cleaned_value
                for item in value
                if (cleaned_value := clean(item)) is not remove
            ]
        return value

    cleaned_config = clean(config)
    return cleaned_config if isinstance(cleaned_config, dict) else dict(config)


def _lovelace_resource_update_payload(
    resource: Mapping[str, str],
) -> dict[str, str]:
    return {
        "res_type": resource["type"],
        "url": resource["url"],
    }


def _lovelace_resource_matches_static_url(
    item: Any,
    resource: Mapping[str, str],
) -> bool:
    return _lovelace_resource_static_url(
        _lovelace_dashboard_item_value(item, "url")
    ) == _lovelace_resource_static_url(resource.get("url"))


def _lovelace_resource_has_current_values(
    item: Any,
    resource: Mapping[str, str],
) -> bool:
    item_type = (
        _lovelace_dashboard_item_value(item, "type")
        or _lovelace_dashboard_item_value(item, "res_type")
    )
    return (
        str(item_type or "") == resource["type"]
        and str(_lovelace_dashboard_item_value(item, "url") or "") == resource["url"]
    )


def _lovelace_resource_static_url(value: Any) -> str:
    return str(value or "").strip().split("?", 1)[0]


async def _async_delete_lovelace_dashboard_config(
    hass: Any,
    lovelace_data: Any,
    url_path: str,
) -> bool:
    dashboards = _lovelace_dashboards(lovelace_data)
    if dashboards is None:
        return False

    dashboard_store = dashboards.get(url_path)
    if dashboard_store is None:
        return False

    dashboard_mode = getattr(dashboard_store, "mode", None)
    if callable(dashboard_mode):
        dashboard_mode = dashboard_mode()
    if str(dashboard_mode or "").strip().lower() != "storage":
        return False

    dashboard_store = dashboards.pop(url_path, None)
    if dashboard_store is None:
        return False

    try:
        from homeassistant.components import frontend
    except ImportError:
        frontend = None

    remove_panel = getattr(frontend, "async_remove_panel", None)
    if callable(remove_panel):
        remove_panel(hass, url_path)

    delete = getattr(dashboard_store, "async_delete", None)
    if callable(delete):
        await _async_lovelace_method_result(delete())
    return True


async def _async_lovelace_method_result(result: Any) -> Any:
    if isawaitable(result):
        return await result
    return result


def _new_lovelace_storage(hass: Any, item: Mapping[str, Any]) -> Any | None:
    try:
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard
    except ImportError:
        return None
    return lovelace_dashboard.LovelaceStorage(hass, dict(item))


def _register_lovelace_dashboard_panel(
    hass: Any,
    item: Mapping[str, Any],
    *,
    update: bool,
) -> None:
    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace.const import (
            CONF_ICON,
            CONF_REQUIRE_ADMIN,
            CONF_SHOW_IN_SIDEBAR,
            CONF_TITLE,
            CONF_URL_PATH,
            DEFAULT_ICON,
            MODE_STORAGE,
        )
        from homeassistant.components.lovelace.const import (
            DOMAIN as LOVELACE_DOMAIN,
        )
    except ImportError:
        return

    try:
        panel_kwargs = {
            "frontend_url_path": item.get(CONF_URL_PATH),
            "require_admin": item[CONF_REQUIRE_ADMIN],
            "show_in_sidebar": item[CONF_SHOW_IN_SIDEBAR],
            "sidebar_title": item[CONF_TITLE],
            "sidebar_icon": item.get(CONF_ICON, DEFAULT_ICON),
            "config": {"mode": MODE_STORAGE},
            "update": update,
        }
        try:
            frontend.async_register_built_in_panel(
                hass,
                LOVELACE_DOMAIN,
                **panel_kwargs,
            )
        except TypeError as err:
            if "show_in_sidebar" not in str(err):
                raise
            panel_kwargs.pop("show_in_sidebar", None)
            frontend.async_register_built_in_panel(
                hass,
                LOVELACE_DOMAIN,
                **panel_kwargs,
            )
    except (AttributeError, KeyError, ValueError):
        return


def _lovelace_dashboard_item_id(
    item: Any,
    payload: Mapping[str, Any],
) -> str:
    return str(
        _lovelace_dashboard_item_value(item, "id")
        or _lovelace_dashboard_item_value(item, "url_path")
        or payload.get("url_path")
        or ""
    )


def _lovelace_dashboard_item_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return {
        key: value
        for key in ("id", "url_path", "mode", "title", "icon", "show_in_sidebar")
        if (value := getattr(item, key, None)) is not None
    }


def _lovelace_dashboard_item_value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _normalize_lovelace_path(value: Any) -> str:
    return str(value or "").strip().removeprefix("/")


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
