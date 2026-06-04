from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from . import notifications, repairs
from .activity_alerts import ActivityAlertSettings, evaluate_activity_alert
from .activity_timeline import (
    build_recent_activity_timeline,
    timeline_payload,
)
from .aggregation import aggregate_dual_phase
from .alerting import ConservativeAlertPolicy, Observation
from .balance import BalanceInput, calculate_balance
from .baseline import build_baseline
from .billing import (
    BillingCycleBudgetEvidence,
    BillingCycleSettings,
    record_billing_cycle_usage,
)
from .capacity import (
    DEFAULT_CAPACITY_WARNING_RATIO,
    CapacitySettings,
    evaluate_circuit_capacity,
)
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .cost import CostSettings, record_cost_sample
from .cycles import (
    MIN_CYCLE_BASELINE_CONFIDENCE,
    cycle_baseline_feature_values,
    cycle_summary_payload,
    select_cycle_anomaly_evidence,
    summarize_circuit_cycles,
)
from .demand import (
    DemandLimitEvidence,
    DemandPeakEvidence,
    DemandSettings,
    record_demand_sample,
)
from .energy_dashboard import (
    evaluate_energy_dashboard_readiness,
    readiness_payload,
)
from .events import CircuitEventDetector
from .exporting import build_circuit_history_csv
from .goals import (
    EnergyGoalEvidence,
    EnergyGoalSettings,
    evaluate_daily_energy_goal,
)
from .load_shift import FlexibleLoadInput, evaluate_solar_load_shift
from .metric_consistency import (
    MetricConsistencyResult,
    evaluate_metric_consistency,
)
from .models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
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
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
    unmatched_load_percentage,
)
from .normalize import NormalizedCircuitSample, SourceState, build_circuit_sample
from .phase_balance import (
    LegImbalanceResult,
    evaluate_dual_phase_leg_imbalance,
)
from .power_quality import (
    PowerQualityEvidence,
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)
from .profiles import get_profile_definition
from .solar_flow import SolarFlowInput, calculate_solar_flow
from .standby import StandbyLimitEvidence, StandbySettings, record_standby_sample
from .storage import RETENTION_WINDOWS, FeatureStoreData
from .usage import EnergyUsageSettings, EnergyUsageSpike, record_energy_usage
from .utility_comparison import (
    DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
    DEFAULT_UTILITY_STATISTIC_PERIOD,
    UtilityComparisonSettings,
    compare_utility_energy,
    select_latest_statistics_energy,
    select_statistics_energy_for_period,
)
from .ux import (
    alert_evidence_detail,
    alert_policy_name_for_sensitivity,
    data_quality_checklist,
    health_summary,
    learning_progress,
    normalize_sensitivity,
)

_LOGGER = logging.getLogger(__name__)

FLEXIBLE_SOLAR_LOAD_PROFILES = frozenset(
    {
        ApplianceProfile.EV_CHARGER,
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.POOL_PUMP,
        ApplianceProfile.WATER_HEATER,
    }
)
MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE = 0.5

try:
    from homeassistant.components.recorder.statistics import (
        statistics_during_period as _ha_statistics_during_period,
    )
    from homeassistant.helpers.event import async_track_state_change_event
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
except ModuleNotFoundError:
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
    sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
    maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    nilm_review_by_circuit: dict[str, list[dict[str, Any]]] = field(
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


def _replace_if_present(
    target: dict[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> None:
    values = {key: source[key] for key in keys if key in source}
    if values:
        target[circuit_id] = values


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
        now_fn: Any | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry_id = entry_id
        self.entry_data = entry_data or {}
        self.options = options or {}
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
        self._sensitivity = str(
            self.options.get(
                CONF_SENSITIVITY,
                self.entry_data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        )
        self._apply_config_entry_settings()
        self._detectors = {
            config.circuit_id: CircuitEventDetector()
            for config in self.circuit_configs
        }
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
        self._baseline_values: defaultdict[str, list[float]] = defaultdict(list)
        self._notified_alert_ids: set[str] = set()
        self._active_repair_issues: set[tuple[str, str]] = set()
        self._nilm_detectors: dict[str, NilmEdgeDetector] = {}
        self._nilm_unmatched_edges: defaultdict[str, list[NilmEdge]] = defaultdict(list)
        self._nilm_total_events_by_circuit: defaultdict[str, int] = defaultdict(int)
        self._store_dirty = False
        self.paused_circuits: set[str] = set()
        self.ignored_nilm_signatures: set[tuple[str, str]] = set()
        self.last_exported_diagnostics: dict[str, Any] = {}
        self.last_exported_history_csv: str = ""
        self.mapping_checks_run = 0
        self.state = AnalyzerState()
        self.source_entities: tuple[str, ...] = ()
        self.started = False
        self._unsub_state_change: Any = None
        self._hydrate_state_from_store()
        self.async_set_updated_data(self.state)

    async def async_start(self: Self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None

        self.source_entities = tuple(source_entities)
        self.started = True

        if async_track_state_change_event is None or not self.source_entities:
            return

        self._unsub_state_change = async_track_state_change_event(
            self.hass,
            list(self.source_entities),
            self._async_handle_source_state_change,
        )

    async def async_stop(self: Self) -> None:
        """Stop listening to source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None
        self.started = False

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
            self._apply_advanced_settings(circuit_id, settings)

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

    async def _async_handle_source_state_change(self: Self, event: Any) -> None:
        """Handle Home Assistant source state changes."""
        await self.async_process_update()

    async def async_process_update(self: Self) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []

        for config in self.circuit_configs:
            sample = self._sample_for_config(config, now)
            samples.append((config, sample))
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            detector = self._detectors.setdefault(
                config.circuit_id,
                CircuitEventDetector(),
            )
            new_events = detector.process(sample)
            events.extend(new_events)
            if new_events:
                self.store_data.events.extend(new_events)
                self._mark_store_dirty()

            alert = self._observe_power_quality(config, sample, now)
            if alert is not None:
                alerts.append(alert)
                self.store_data.alerts.append(alert)
                self._mark_store_dirty()
                await self._notify_alert(alert)

            usage_alert = self._observe_energy_usage(config, sample, now)
            if usage_alert is not None:
                alerts.append(usage_alert)
                self.store_data.alerts.append(usage_alert)
                self._mark_store_dirty()
                await self._notify_alert(usage_alert)

            goal_alert = self._observe_energy_goal(config, now)
            if goal_alert is not None:
                alerts.append(goal_alert)
                self.store_data.alerts.append(goal_alert)
                self._mark_store_dirty()
                await self._notify_alert(goal_alert)

            cycle_alert = self._observe_run_cycle(config, now)
            if cycle_alert is not None:
                alerts.append(cycle_alert)
                self.store_data.alerts.append(cycle_alert)
                self._mark_store_dirty()
                await self._notify_alert(cycle_alert)

            activity_alert = self._observe_activity_alert(config, now)
            if activity_alert is not None:
                alerts.append(activity_alert)
                self.store_data.alerts.append(activity_alert)
                self._mark_store_dirty()
                await self._notify_alert(activity_alert)

            billing_alert = self._observe_billing_cycle(config, sample, now)
            if billing_alert is not None:
                alerts.append(billing_alert)
                self.store_data.alerts.append(billing_alert)
                self._mark_store_dirty()
                await self._notify_alert(billing_alert)

            self._observe_cost(config, sample, now)

            demand_alert = self._observe_demand(config, sample, now)
            if demand_alert is not None:
                alerts.append(demand_alert)
                self.store_data.alerts.append(demand_alert)
                self._mark_store_dirty()
                await self._notify_alert(demand_alert)

            capacity_alert = self._observe_capacity(config, sample, now)
            if capacity_alert is not None:
                alerts.append(capacity_alert)
                self.store_data.alerts.append(capacity_alert)
                self._mark_store_dirty()
                await self._notify_alert(capacity_alert)

            leg_imbalance_alert = self._observe_leg_imbalance(config, sample, now)
            if leg_imbalance_alert is not None:
                alerts.append(leg_imbalance_alert)
                self.store_data.alerts.append(leg_imbalance_alert)
                self._mark_store_dirty()
                await self._notify_alert(leg_imbalance_alert)

            self._observe_metric_consistency(config, sample)

            standby_alert = self._observe_standby(config, sample, now)
            if standby_alert is not None:
                alerts.append(standby_alert)
                self.store_data.alerts.append(standby_alert)
                self._mark_store_dirty()
                await self._notify_alert(standby_alert)

        for config, sample in samples:
            for nilm_alert in self._process_nilm_sample(config, sample, events):
                alerts.append(nilm_alert)
                self.store_data.alerts.append(nilm_alert)
                self._mark_store_dirty()
                await self._notify_alert(nilm_alert)
        self._refresh_balance_state(samples)
        self._refresh_solar_flow_state(samples)
        for utility_alert in await self._observe_utility_comparisons(now):
            alerts.append(utility_alert)
            self.store_data.alerts.append(utility_alert)
            self._mark_store_dirty()
            await self._notify_alert(utility_alert)

        process_events_into_state(self.state, events, alerts)
        for config, sample in samples:
            self._refresh_ux_state(config, sample, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)
        return self.state

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
        self.paused_circuits.add(circuit_id)
        self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)

    async def async_acknowledge_alert(self: Self, alert_id: str) -> None:
        """Acknowledge an active alert evidence item."""
        self.store_data.alerts = [
            alert
            for alert in self.store_data.alerts
            if notifications.notification_id_for_alert(alert) != alert_id
        ]
        self._mark_store_dirty()
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
            circuit_id: (
                max(_alert_anomaly_score(alert) for alert in alerts)
                if alerts
                else 0.0
            )
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
        }
        self._refresh_all_ux_state(self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

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
        self._refresh_energy_goal_state_for_circuit(circuit_id, now)
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
        now = self._now_fn()
        payload: dict[str, Any] = {
            "active": True,
            "note": str(note),
            "started_at": now.isoformat(),
            "relearn_on_end": bool(relearn_on_end),
        }
        if duration is not None:
            payload["duration"] = str(duration)
        self.store_data.maintenance_by_circuit[circuit_id] = payload
        self.paused_circuits.add(circuit_id)
        self._mark_store_dirty()
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_end_maintenance(
        self: Self,
        circuit_id: str,
        relearn: bool = False,
    ) -> None:
        """Clear maintenance state and optionally relearn the circuit baseline."""
        now = self._now_fn()
        current = dict(self.store_data.maintenance_by_circuit.get(circuit_id, {}))
        should_relearn = bool(relearn or current.get("relearn_on_end"))
        current.update({"active": False, "ended_at": now.isoformat()})
        self.store_data.maintenance_by_circuit[circuit_id] = current
        self.paused_circuits.discard(circuit_id)
        self._mark_store_dirty()
        if should_relearn:
            await self.async_relearn_baseline(circuit_id)
            return
        self._refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_mark_alert_expected(self: Self, alert_id: str) -> None:
        """Mark an alert pattern as expected for future notifications."""
        await self._store_alert_feedback(alert_id, "expected")

    async def async_mark_alert_unhelpful(self: Self, alert_id: str) -> None:
        """Mark an alert pattern as unhelpful for future notifications."""
        await self._store_alert_feedback(alert_id, "unhelpful")

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
                self._mark_store_dirty()
                self._refresh_nilm_state(circuit_id)
                self._refresh_ux_state_for_circuit(circuit_id, self._now_fn())
                self.async_set_updated_data(self.state)
                await self._async_save_store(self._now_fn())
                return
        signatures.append({"signature_id": signature_id, "ignored": True})
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
        self._nilm_signature_for_review(circuit_id, target_signature_id)
        source = self._nilm_signature_for_review(circuit_id, source_signature_id)
        source["review_state"] = "merged"
        source["merged_into"] = target_signature_id
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
        self._refresh_all_ux_state(self._now_fn())

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
        cycle_summary = summarize_circuit_cycles(
            self.store_data.events,
            circuit_id=circuit_id,
            now=now,
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
        self.state.alert_evidence_by_circuit[circuit_id] = alert_evidence_detail(alert)

    def _refresh_recent_activity_state(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        timeline = build_recent_activity_timeline(
            circuit_id=circuit_id,
            events=self.store_data.events,
            alerts=self.store_data.alerts,
            now=now,
        )
        self.state.recent_activity_by_circuit[circuit_id] = timeline.latest_title
        self.state.recent_activity_count_by_circuit[circuit_id] = (
            timeline.total_count
        )
        self.state.recent_activity_timeline_by_circuit[circuit_id] = (
            timeline_payload(timeline)
        )

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
        raw_real_power = _sum_sample_values(
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

        raw_real_power = _sum_sample_values(samples, "raw_real_power")
        leg_a_sample, leg_b_sample = _parallel_leg_samples(sensor_samples)
        return NormalizedCircuitSample(
            timestamp=max(sample.timestamp for sample in samples),
            circuit_id=config.circuit_id,
            real_power=_sum_sample_values(samples, "real_power"),
            current=_sum_sample_values(samples, "current"),
            voltage=_average_sample_values(samples, "voltage"),
            reactive_power=_sum_sample_values(samples, "reactive_power"),
            apparent_power=_sum_sample_values(samples, "apparent_power"),
            power_factor=_average_sample_values(samples, "power_factor"),
            frequency=_average_sample_values(samples, "frequency"),
            energy=_sum_sample_values(samples, "energy"),
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
        desired: set[tuple[str, str]] = set()
        if isinstance(sample_or_problem, str):
            self.state.data_quality_by_circuit[circuit_id] = sample_or_problem
            desired.add((circuit_id, sample_or_problem))
        elif sample_or_problem.quality_issues:
            issue = sample_or_problem.quality_issues[0]
            problem = _data_quality_problem(issue)
            self.state.data_quality_by_circuit[circuit_id] = issue
            desired.add((circuit_id, problem))
        else:
            self.state.data_quality_by_circuit.pop(circuit_id, None)

        current = {
            issue for issue in self._active_repair_issues if issue[0] == circuit_id
        }
        for issue in current - desired:
            await repairs.async_delete_data_quality_issue(self.hass, issue[0], issue[1])
            self._active_repair_issues.discard(issue)

        for issue in desired - self._active_repair_issues:
            await repairs.async_create_data_quality_issue(self.hass, issue[0], issue[1])
            self._active_repair_issues.add(issue)

    def _process_nilm_sample(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample,
        events: Iterable[CircuitEvent],
    ) -> list[AlertEvidence]:
        alerts: list[AlertEvidence] = []
        if not self._nilm_enabled(config):
            return alerts

        min_delta_w = _nilm_min_delta_w(
            self._sensitivity_for_circuit(config.circuit_id)
        )
        detector = self._nilm_detectors.setdefault(
            config.circuit_id,
            NilmEdgeDetector(min_delta_w=min_delta_w),
        )
        detector.min_delta_w = min_delta_w
        edges = detector.process(sample)
        if edges:
            known_events = self._known_load_events(config.circuit_id, events)
            mask = mask_known_loads(edges, known_events)
            for match in mask.matched_edges:
                alert = self._observe_nilm_known_load_topology(config, match)
                if alert is not None:
                    alerts.append(alert)
            self._nilm_total_events_by_circuit[config.circuit_id] += len(edges)
            self._nilm_unmatched_edges[config.circuit_id].extend(mask.unmatched_edges)

            signatures = cluster_recurring_signatures(
                self._nilm_unmatched_edges[config.circuit_id]
            )
            payloads = self._nilm_signature_payloads(config.circuit_id, signatures)
            if payloads != self.store_data.nilm_signatures.get(config.circuit_id, []):
                self.store_data.nilm_signatures[config.circuit_id] = payloads
                self._mark_store_dirty()

        self._refresh_nilm_state(config.circuit_id)
        return alerts

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
        known_config = self._config_for_circuit(match.known_circuit_id)
        if known_config is None:
            return None

        evidence = _nilm_topology_evidence_payload(
            mains_config=mains_config,
            known_config=known_config,
            match=match,
        )
        if not evidence:
            return None

        circuit_id = known_config.circuit_id
        if match.confidence < MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE:
            evidence["status"] = "low_confidence_match"
            evidence["minimum_match_confidence"] = (
                MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE
            )
        status = str(evidence["status"])
        self.state.nilm_topology_status_by_circuit[circuit_id] = status
        self.state.nilm_topology_evidence_by_circuit[circuit_id] = evidence
        if status not in {"topology_mismatch", "leg_mismatch"}:
            return None

        policy = self._nilm_topology_alert_policy_for_circuit(circuit_id)
        feature = _nilm_topology_alert_feature(status)
        return policy.observe(
            Observation(
                circuit_id=circuit_id,
                feature=feature,
                score=1.0,
                baseline_confidence=1.0,
                observed_at=match.edge.timestamp,
                observed_value=1.0,
                baseline_value=0.0,
                message=_nilm_topology_mismatch_message(known_config, evidence),
                features={
                    "match_confidence": float(evidence["match_confidence"]),
                    "matched_delta_w": float(evidence["matched_delta_w"]),
                    "known_event_power_w": float(evidence["known_event_power_w"]),
                    "observed_leg_balance_ratio": float(
                        evidence.get("observed_leg_balance_ratio") or 0.0
                    ),
                },
            )
        )

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
        existing = {
            str(signature.get("signature_id")): dict(signature)
            for signature in self.store_data.nilm_signatures.get(circuit_id, [])
        }
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signature in signatures:
            current = existing.get(signature.signature_id, {})
            metadata_current = (
                current
                if _nilm_signature_metadata_compatible(signature, current)
                else {}
            )
            user_label = metadata_current.get("user_label")
            classified_signature = replace(signature, user_label=user_label)
            ignored = bool(metadata_current.get("ignored")) or (
                circuit_id,
                signature.signature_id,
            ) in self.ignored_nilm_signatures and bool(metadata_current)
            payload = {
                "signature_id": signature.signature_id,
                "median_delta_w": signature.median_delta_w,
                "median_delta_var": signature.median_delta_var,
                "median_delta_va": signature.median_delta_va,
                "median_delta_pf": signature.median_delta_pf,
                "median_leg_a_delta_w": signature.median_leg_a_delta_w,
                "median_leg_b_delta_w": signature.median_leg_b_delta_w,
                "leg_balance_ratio": signature.leg_balance_ratio,
                "dominant_leg": signature.dominant_leg,
                "split_phase_type": signature.split_phase_type,
                "occurrence_count": signature.occurrence_count,
                "confidence": signature.confidence,
                "classification": classify_signature(classified_signature),
            }
            if user_label:
                payload["user_label"] = user_label
            if ignored:
                payload["ignored"] = True
            for key in ("review_state", "expected", "merged_into"):
                if key in metadata_current:
                    payload[key] = metadata_current[key]
            payloads.append(payload)
            seen.add(signature.signature_id)

        for signature_id, signature in existing.items():
            if signature_id not in seen and (
                signature.get("user_label") or signature.get("ignored")
                or signature.get("expected") or signature.get("merged_into")
                or signature.get("review_state")
            ):
                payloads.append(signature)

        return payloads

    def _refresh_nilm_state(self: Self, circuit_id: str) -> None:
        signatures = self.store_data.nilm_signatures.get(circuit_id, [])
        active_count = sum(
            1
            for signature in signatures
            if not signature.get("ignored")
            and signature.get("review_state") != "merged"
        )
        self.state.nilm_signature_count_by_circuit[circuit_id] = active_count
        self.state.nilm_unmatched_load_percentage_by_circuit[circuit_id] = (
            unmatched_load_percentage(
                self._nilm_total_events_by_circuit[circuit_id],
                len(self._nilm_unmatched_edges[circuit_id]),
            )
        )
        self.state.nilm_review_by_circuit[circuit_id] = [
            _nilm_review_payload(signature) for signature in signatures
        ]

    def _refresh_balance_state(
        self: Self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
    ) -> None:
        mains_items = [
            (config, sample)
            for config, sample in samples
            if config.mode is CircuitMode.MAINS_NILM
            or config.appliance_profile is ApplianceProfile.MAINS_NILM
        ]
        if not mains_items:
            return

        monitored = [
            BalanceInput(
                circuit_id=config.circuit_id,
                real_power_w=sample.real_power,
                generation=config.power_flow is PowerFlowMode.GENERATION
                or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER,
            )
            for config, sample in samples
            if config not in {item[0] for item in mains_items}
        ]
        for config, sample in mains_items:
            result = calculate_balance(
                mains=BalanceInput(
                    circuit_id=config.circuit_id,
                    real_power_w=sample.real_power,
                ),
                monitored=monitored,
            )
            circuit_id = config.circuit_id
            self.state.balance_power_w_by_circuit[circuit_id] = (
                result.balance_power_w
            )
            self.state.monitored_power_w_by_circuit[circuit_id] = (
                result.monitored_power_w
            )
            self.state.monitored_coverage_percent_by_circuit[circuit_id] = (
                result.monitored_coverage_percent
            )
            self.state.balance_status_by_circuit[circuit_id] = result.status
            self.state.balance_evidence_by_circuit[circuit_id] = {
                **result.features,
                "status": result.status,
            }

    def _refresh_solar_flow_state(
        self: Self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
    ) -> None:
        mains_items = [
            (config, sample)
            for config, sample in samples
            if config.mode is CircuitMode.MAINS_NILM
            or config.appliance_profile is ApplianceProfile.MAINS_NILM
        ]
        if not mains_items:
            return

        generation = [
            SolarFlowInput(
                circuit_id=config.circuit_id,
                real_power_w=sample.real_power,
            )
            for config, sample in samples
            if config.power_flow is PowerFlowMode.GENERATION
            or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
        ]
        flexible_loads = [
            FlexibleLoadInput(
                circuit_id=config.circuit_id,
                name=config.name,
                appliance_profile=config.appliance_profile.value,
                real_power_w=sample.real_power,
            )
            for config, sample in samples
            if _is_flexible_solar_load(config)
        ]
        for config, sample in mains_items:
            result = calculate_solar_flow(
                mains=SolarFlowInput(
                    circuit_id=config.circuit_id,
                    real_power_w=sample.real_power,
                ),
                generation=generation,
            )
            load_shift = evaluate_solar_load_shift(
                solar_load_shift_available_w=result.load_shift_available_w,
                solar_surplus_status=result.solar_surplus_status,
                grid_import_w=result.grid_import_w,
                flexible_loads=flexible_loads,
            )
            circuit_id = config.circuit_id
            self.state.solar_generation_w_by_circuit[circuit_id] = (
                result.solar_generation_w
            )
            self.state.solar_site_consumption_w_by_circuit[circuit_id] = (
                result.site_consumption_w
            )
            self.state.solar_grid_import_w_by_circuit[circuit_id] = (
                result.grid_import_w
            )
            self.state.solar_grid_export_w_by_circuit[circuit_id] = (
                result.grid_export_w
            )
            self.state.solar_self_consumption_percent_by_circuit[circuit_id] = (
                result.self_consumption_percent
            )
            self.state.solar_powered_percent_by_circuit[circuit_id] = (
                result.solar_powered_percent
            )
            self.state.solar_surplus_w_by_circuit[circuit_id] = (
                result.solar_surplus_w
            )
            self.state.solar_load_shift_w_by_circuit[circuit_id] = (
                result.load_shift_available_w
            )
            self.state.solar_flexible_load_power_w_by_circuit[circuit_id] = (
                load_shift.active_flexible_load_power_w
            )
            self.state.solar_flexible_load_coverage_percent_by_circuit[circuit_id] = (
                load_shift.solar_coverage_percent
            )
            self.state.solar_flow_status_by_circuit[circuit_id] = result.status
            self.state.solar_surplus_status_by_circuit[circuit_id] = (
                result.solar_surplus_status
            )
            self.state.solar_load_shift_status_by_circuit[circuit_id] = (
                load_shift.status
            )
            self.state.solar_flow_evidence_by_circuit[circuit_id] = {
                **result.features,
                "status": result.status,
                "solar_surplus_status": result.solar_surplus_status,
            }
            self.state.solar_load_shift_evidence_by_circuit[circuit_id] = (
                load_shift.features
            )

    async def _observe_utility_comparisons(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        alerts: list[AlertEvidence] = []
        for circuit_id in self.store_data.utility_comparison_settings_by_circuit:
            config = self._config_for_circuit(circuit_id)
            if config is None:
                continue
            alert = await self._observe_utility_comparison(config, now)
            if alert is not None:
                alerts.append(alert)
        return alerts

    async def _observe_utility_comparison(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        settings = self._utility_comparison_settings_for_circuit(config.circuit_id)
        utility_source_type = _utility_source_type_for_settings(settings)
        utility_period_start: datetime | None = None
        utility_period_end: datetime | None = None
        utility_data_lag_hours: float | None = None
        if utility_source_type == "statistics":
            utility_reading = await self._statistics_kwh_for_id(
                settings.utility_statistic_id,
                now,
                period=settings.utility_statistic_period,
            )
            utility_kwh = utility_reading.energy_kwh
            utility_period_start = utility_reading.period_start
            utility_period_end = utility_reading.period_end
            utility_data_lag_hours = utility_reading.data_lag_hours
        else:
            utility_kwh = self._energy_kwh_for_entity(
                settings.utility_energy_entity,
                now,
            )

        utility_period_available = (
            utility_period_start is not None and utility_period_end is not None
        )
        if settings.measured_energy_entities:
            comparison_source = "explicit_entities"
            if utility_source_type == "statistics" and not utility_period_available:
                measured_kwh = None
                measured_entity_ids = settings.measured_energy_entities
                measured_source_type = "statistics"
            elif utility_period_available:
                measured_kwh, measured_entity_ids = (
                    await self._statistics_kwh_sum_for_entities(
                        settings.measured_energy_entities,
                        now,
                        period=settings.utility_statistic_period,
                        start_time=utility_period_start,
                        end_time=utility_period_end,
                    )
                )
                measured_source_type = "statistics"
            else:
                measured_kwh, measured_entity_ids = self._energy_kwh_sum_for_entities(
                    settings.measured_energy_entities,
                    now,
                )
                measured_source_type = "entity_state"
        else:
            comparison_source = "circuit_energy_sum"
            fallback_entities = self._load_energy_entity_ids_for_sum(config.circuit_id)
            if utility_source_type == "statistics" and not utility_period_available:
                measured_kwh = None
                measured_entity_ids = fallback_entities
                measured_source_type = "statistics"
            elif utility_period_available:
                measured_kwh, measured_entity_ids = (
                    await self._statistics_kwh_sum_for_entities(
                        fallback_entities,
                        now,
                        period=settings.utility_statistic_period,
                        start_time=utility_period_start,
                        end_time=utility_period_end,
                    )
                )
                measured_source_type = "statistics"
            else:
                measured_kwh, measured_entity_ids = self._energy_kwh_sum_for_entities(
                    fallback_entities,
                    now,
                )
                measured_source_type = "entity_state"

        result = compare_utility_energy(
            settings=settings,
            utility_kwh=utility_kwh,
            measured_kwh=measured_kwh,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
            utility_source_type=utility_source_type,
            measured_source_type=measured_source_type,
            period_start=_datetime_iso_or_none(utility_period_start),
            period_end=_datetime_iso_or_none(utility_period_end),
            utility_data_lag_hours=utility_data_lag_hours,
        )
        self._update_utility_comparison_state(config.circuit_id, result)
        if result.status != "mismatch":
            return None

        score = (
            result.absolute_difference_percent / result.tolerance_percent
            if result.tolerance_percent > 0.0
            else result.absolute_difference_percent
        )
        policy = self._utility_comparison_alert_policy_for_circuit(config.circuit_id)
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="utility_energy_mismatch",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=result.measured_kwh or 0.0,
                baseline_value=result.utility_kwh or 0.0,
                message=_utility_comparison_message(config, result),
                features=result.features or {},
            )
        )

    def _update_utility_comparison_state(
        self: Self,
        circuit_id: str,
        result: Any,
    ) -> None:
        self.state.utility_comparison_difference_kwh_by_circuit[circuit_id] = (
            result.difference_kwh
        )
        self.state.utility_comparison_difference_percent_by_circuit[circuit_id] = (
            result.difference_percent
        )
        self.state.utility_comparison_status_by_circuit[circuit_id] = result.status
        self.state.utility_comparison_evidence_by_circuit[circuit_id] = (
            _utility_comparison_evidence_payload(result)
        )

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

        def _fetch() -> dict[str, list[dict[str, Any]]]:
            return _ha_statistics_during_period(
                self.hass,
                start_time,
                end_time,
                statistic_ids,
                normalized_period,
                {"energy": "kWh"},
                {"change", "sum", "state"},
            )

        add_executor_job = getattr(self.hass, "async_add_executor_job", None)
        try:
            if add_executor_job is None:
                return _fetch()
            return await add_executor_job(_fetch)
        except Exception as err:  # noqa: BLE001 - recorder availability varies by setup.
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

    def _capacity_current_a(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> float | None:
        if config.mode is CircuitMode.DUAL_PHASE:
            leg_currents = self._dual_phase_leg_currents(config, now)
            if leg_currents:
                return max(leg_currents)
        current = getattr(sample, "current", None)
        if current is None:
            return None
        if config.mode is CircuitMode.DUAL_PHASE and current > 0.0:
            return float(current) / 2.0
        return float(current)

    def _dual_phase_leg_currents(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> tuple[float, ...]:
        states = self._source_states_for(config, now)
        currents: list[float] = []
        for sensor in config.sensors:
            if sensor.role is not SensorRole.CURRENT:
                continue
            if _normalized_leg(sensor.leg) is None:
                continue
            source = states.get(sensor.entity_id)
            if source is None:
                continue
            try:
                value = float(source.state)
            except ValueError:
                continue
            if value > 0.0:
                currents.append(value)
        return tuple(currents)

    def _sensitivity_for_circuit(self: Self, circuit_id: str) -> str:
        return normalize_sensitivity(
            self.store_data.sensitivity_by_circuit.get(circuit_id, self._sensitivity)
        )

    def _alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        sensitivity = self._sensitivity_for_circuit(circuit_id)
        policy_name = alert_policy_name_for_sensitivity(sensitivity)
        key = (circuit_id, policy_name)
        policy = self._alert_policies.get(key)
        if policy is None:
            policy = _alert_policy_for_sensitivity(policy_name)
            self._alert_policies[key] = policy
        return policy

    def _usage_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _goal_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _billing_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _demand_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _capacity_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _leg_imbalance_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _standby_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _utility_comparison_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _nilm_topology_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _cycle_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    def _activity_alert_policy_for_circuit(
        self: Self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
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
        return policy

    async def _store_alert_feedback(self: Self, alert_id: str, action: str) -> None:
        alert = self._alert_for_id(alert_id)
        if alert is None:
            return
        self.store_data.alert_feedback[_alert_feedback_key(alert)] = {
            "action": action,
            "alert_id": alert_id,
            "created_at": self._now_fn().isoformat(),
            "circuit_id": alert.circuit_id,
            "feature": _alert_feature(alert),
            "change_ratio": alert.change_ratio,
            "observed_value": alert.observed_value,
            "baseline_value": alert.baseline_value,
        }
        self._mark_store_dirty()
        self._refresh_ux_state_for_circuit(alert.circuit_id, self._now_fn())
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

    def _alert_for_id(self: Self, alert_id: str) -> AlertEvidence | None:
        alerts = list(self.store_data.alerts)
        for active_alerts in self.state.active_alerts_by_circuit.values():
            alerts.extend(active_alerts)
        for alert in alerts:
            if notifications.notification_id_for_alert(alert) == alert_id:
                return alert
        return None

    def _has_suppressed_alert_feedback(self: Self, alert: AlertEvidence) -> bool:
        feedback = self.store_data.alert_feedback.get(_alert_feedback_key(alert), {})
        return feedback.get("action") in {"expected", "unhelpful"}

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
        self._store_dirty = True

    async def _async_save_store(self: Self, now: datetime) -> None:
        if self._store is None or not self._store_dirty:
            return
        self._apply_retention(now)
        self._store.data = self.store_data
        await self._store.async_save()
        self._store_dirty = False

    def _apply_retention(self: Self, now: datetime) -> None:
        retained_events = [
            event for event in self.store_data.events if self._keep_event(event, now)
        ]
        if len(retained_events) != len(self.store_data.events):
            self.store_data.events = retained_events
        self._prune_energy_usage(now)
        self._prune_demand(now)
        self._prune_standby(now)

    def _keep_event(self: Self, event: CircuitEvent, now: datetime) -> bool:
        retention_mode = self._retention_mode_for_circuit(event.circuit_id)
        return event.timestamp >= now - RETENTION_WINDOWS[retention_mode]

    def _prune_energy_usage(self: Self, now: datetime) -> None:
        for circuit_id, history in self.store_data.energy_usage_by_circuit.items():
            retention_mode = self._retention_mode_for_circuit(circuit_id)
            cutoff = (now.date() - RETENTION_WINDOWS[retention_mode]).isoformat()
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
            cutoff = (now.date() - RETENTION_WINDOWS[retention_mode]).isoformat()
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

        for sensor in config.sensors:
            raw_state = get_state(sensor.entity_id)
            if raw_state is None:
                continue
            attributes = getattr(raw_state, "attributes", {}) or {}
            states[sensor.entity_id] = SourceState(
                entity_id=sensor.entity_id,
                state=str(getattr(raw_state, "state", "")),
                unit=attributes.get("unit_of_measurement") or sensor.unit,
                last_updated=getattr(raw_state, "last_updated", now) or now,
                device_class=attributes.get("device_class"),
                state_class=attributes.get("state_class"),
            )
        return states

    def _observe_power_quality(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        policy = self._alert_policy_for_circuit(config.circuit_id)
        features = extract_power_quality_features(sample)
        if not features:
            self.state.learning_by_circuit[config.circuit_id] = True
            self._clear_power_quality_state(config.circuit_id)
            return None

        baselines: dict[str, Any] = {}
        learning_new_features = False
        for feature, value in features.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = self.store_data.baselines.get(key)
            if baseline is None:
                values = self._baseline_values[key]
                values.append(value)
                if len(values) >= 15:
                    baseline = build_baseline(feature, values)
                    self.store_data.baselines[key] = baseline
                    self._mark_store_dirty()
                learning_new_features = True
            if baseline is not None:
                baselines[feature] = baseline

        scores = score_power_quality_features(features, baselines)
        evidence = select_power_quality_evidence(
            config,
            scores,
            min_relationship_score=policy.min_average_score,
        )
        if (
            evidence is None
            and config.mode is not CircuitMode.MIXED
            and config.appliance_profile is not ApplianceProfile.MIXED
        ):
            evidence = self._real_power_fallback_evidence(scores, policy)
        self._update_power_quality_state(config.circuit_id, scores, evidence)

        mature = self._learning_mature(config, now)
        has_confident_scores = any(score.baseline_confidence >= 0.6 for score in scores)
        self.state.learning_by_circuit[config.circuit_id] = (
            learning_new_features or not mature or not has_confident_scores
        )
        if not mature or not has_confident_scores:
            return None
        if evidence is None:
            return None

        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )

    def _observe_energy_usage(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        settings = self._energy_usage_settings_for_config(
            config,
            config.circuit_id,
        )
        result = record_energy_usage(
            self.store_data.energy_usage_by_circuit.setdefault(
                config.circuit_id,
                {},
            ),
            circuit_id=config.circuit_id,
            timestamp=now,
            energy_kwh=sample.energy,
            settings=EnergyUsageSettings(
                window_days=settings.window_days,
                daily_spike_ratio=settings.daily_spike_ratio,
            ),
            retention_days=RETENTION_WINDOWS[
                self._retention_mode_for_circuit(config.circuit_id)
            ].days,
        )
        if result is None:
            return None

        self._mark_store_dirty()
        self.state.daily_energy_usage_by_circuit[config.circuit_id] = (
            result.daily_usage_kwh
        )
        self.state.energy_usage_share_by_circuit[config.circuit_id] = round(
            result.daily_usage_share * 100,
            1,
        )
        self.state.energy_usage_evidence_by_circuit[config.circuit_id] = (
            _energy_usage_evidence_payload(result)
        )

        if result.spike is None:
            return None

        spike = result.spike
        policy = self._usage_alert_policy_for_circuit(config.circuit_id)
        score = (
            spike.daily_usage_kwh / spike.threshold_kwh
            if spike.threshold_kwh > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="daily_energy_usage_spike",
                score=score,
                baseline_confidence=min(
                    spike.baseline_day_count / spike.window_days,
                    1.0,
                ),
                observed_at=now,
                observed_value=spike.daily_usage_kwh,
                baseline_value=spike.threshold_kwh,
                message=_energy_usage_spike_message(config, spike),
                features=spike.features,
            )
        )

    def _observe_energy_goal(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        usage_evidence = self.state.energy_usage_evidence_by_circuit.get(
            config.circuit_id,
            {},
        )
        if not isinstance(usage_evidence, dict):
            return None
        if usage_evidence.get("date") != now.date().isoformat():
            return None

        result = self._refresh_energy_goal_state_for_circuit(config.circuit_id, now)
        if result.goal_exceeded is None:
            return None

        evidence = result.goal_exceeded
        policy = self._goal_alert_policy_for_circuit(config.circuit_id)
        score = (
            evidence.daily_usage_kwh / evidence.alert_threshold_kwh
            if evidence.alert_threshold_kwh > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="daily_energy_goal",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=evidence.daily_usage_kwh,
                baseline_value=evidence.daily_goal_kwh,
                message=_energy_goal_message(config, evidence),
                features=evidence.features,
            )
        )

    def _refresh_energy_goal_state_for_circuit(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> Any:
        usage_evidence = self.state.energy_usage_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        date = (
            str(usage_evidence.get("date"))
            if isinstance(usage_evidence, dict) and usage_evidence.get("date")
            else now.date().isoformat()
        )
        result = evaluate_daily_energy_goal(
            circuit_id=circuit_id,
            date=date,
            daily_usage_kwh=self.state.daily_energy_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            settings=self._energy_goal_settings_for_config(
                self._config_for_circuit(circuit_id),
                circuit_id,
            ),
        )
        self.state.energy_goal_usage_by_circuit[circuit_id] = (
            result.goal_usage_percent
        )
        self.state.energy_goal_status_by_circuit[circuit_id] = result.status
        self.state.energy_goal_evidence_by_circuit[circuit_id] = (
            _energy_goal_evidence_payload(result)
        )
        return result

    def _observe_run_cycle(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        summary = summarize_circuit_cycles(
            self.store_data.events,
            circuit_id=config.circuit_id,
            now=now,
        )
        baselines = self._cycle_baselines_for_config(config, now)
        if not self._learning_mature(config, now):
            return None

        policy = self._cycle_alert_policy_for_circuit(config.circuit_id)
        evidence = select_cycle_anomaly_evidence(
            config,
            summary,
            baselines,
            min_score=policy.min_average_score,
        )
        if evidence is None:
            return None

        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )

    def _cycle_baselines_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, BaselineStats]:
        baselines: dict[str, BaselineStats] = {}
        values_by_feature = cycle_baseline_feature_values(
            self.store_data.events,
            circuit_id=config.circuit_id,
            now=now,
        )
        for feature, values in values_by_feature.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = self.store_data.baselines.get(key)
            if baseline is None and len(values) >= 9:
                baseline = build_baseline(feature, values)
                self.store_data.baselines[key] = baseline
                self._mark_store_dirty()
            if baseline is not None:
                baselines[feature] = baseline
        return baselines

    def _observe_activity_alert(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        summary = summarize_circuit_cycles(
            self.store_data.events,
            circuit_id=config.circuit_id,
            now=now,
        )
        evidence = evaluate_activity_alert(
            circuit_id=config.circuit_id,
            circuit_name=config.name,
            summary=summary,
            settings=self._activity_alert_settings_for_config(
                config,
                config.circuit_id,
            ),
        )
        if evidence is None:
            return None

        policy = self._activity_alert_policy_for_circuit(config.circuit_id)
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )

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

    def _observe_billing_cycle(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        settings = self._billing_cycle_settings_for_config(
            config,
            config.circuit_id,
        )
        result = record_billing_cycle_usage(
            self.store_data.billing_by_circuit.setdefault(config.circuit_id, {}),
            circuit_id=config.circuit_id,
            timestamp=now,
            energy_kwh=sample.energy,
            settings=settings,
        )
        if result is None:
            return None

        self._mark_store_dirty()
        self.state.billing_cycle_usage_kwh_by_circuit[config.circuit_id] = (
            result.cycle_usage_kwh
        )
        self.state.billing_cycle_forecast_kwh_by_circuit[config.circuit_id] = (
            result.projected_cycle_kwh
        )
        self.state.billing_cycle_budget_usage_by_circuit[config.circuit_id] = (
            result.budget_usage_percent
        )
        self.state.billing_cycle_status_by_circuit[config.circuit_id] = result.status
        self.state.billing_cycle_evidence_by_circuit[config.circuit_id] = (
            _billing_cycle_evidence_payload(result)
        )

        if result.budget_exceeded is None:
            return None

        evidence = result.budget_exceeded
        policy = self._billing_alert_policy_for_circuit(config.circuit_id)
        score = (
            evidence.projected_cycle_kwh / evidence.budget_kwh
            if evidence.budget_kwh > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="billing_cycle_budget",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=evidence.projected_cycle_kwh,
                baseline_value=evidence.budget_kwh,
                message=_billing_cycle_budget_message(config, evidence),
                features=evidence.features,
            )
        )

    def _observe_cost(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> None:
        settings = self._cost_settings_for_config(config, config.circuit_id)
        result = record_cost_sample(
            self.store_data.cost_by_circuit.setdefault(config.circuit_id, {}),
            circuit_id=config.circuit_id,
            timestamp=now,
            energy_kwh=sample.energy,
            settings=settings,
        )
        if result is None:
            return

        self._mark_store_dirty()
        self.state.cost_current_rate_by_circuit[config.circuit_id] = (
            result.current_rate_per_kwh
        )
        self.state.cost_cycle_by_circuit[config.circuit_id] = result.cycle_cost
        self.state.cost_cycle_forecast_by_circuit[config.circuit_id] = (
            result.projected_cycle_cost
        )
        self.state.cost_status_by_circuit[config.circuit_id] = result.status
        self.state.cost_evidence_by_circuit[config.circuit_id] = (
            _cost_evidence_payload(result)
        )

    def _observe_demand(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        power_w = _demand_power_w(sample)
        settings = self._demand_settings_for_config(config, config.circuit_id)
        result = record_demand_sample(
            self.store_data.demand_by_circuit.setdefault(config.circuit_id, {}),
            circuit_id=config.circuit_id,
            timestamp=now,
            real_power_w=power_w,
            settings=settings,
            retention_days=RETENTION_WINDOWS[
                self._retention_mode_for_circuit(config.circuit_id)
            ].days,
        )
        if result is None:
            return None

        if result.monthly_peak_recorded:
            self._mark_store_dirty()
        self.state.current_demand_w_by_circuit[config.circuit_id] = (
            result.current_demand_w
        )
        self.state.peak_demand_w_by_circuit[config.circuit_id] = result.peak_demand_w
        self.state.demand_limit_usage_by_circuit[config.circuit_id] = (
            result.demand_limit_usage
        )
        self.state.demand_peak_rank_by_circuit[config.circuit_id] = (
            result.monthly_peak_rank
        )
        self.state.demand_peak_status_by_circuit[config.circuit_id] = (
            result.monthly_peak_status
        )
        self.state.demand_evidence_by_circuit[config.circuit_id] = (
            _demand_evidence_payload(result)
        )

        if result.limit_exceeded is not None:
            self._mark_store_dirty()
            evidence = result.limit_exceeded
            policy = self._demand_alert_policy_for_circuit(config.circuit_id)
            score = (
                evidence.current_demand_w / evidence.demand_limit_w
                if evidence.demand_limit_w > 0.0
                else 0.0
            )
            return policy.observe(
                Observation(
                    circuit_id=config.circuit_id,
                    feature="demand_limit",
                    score=score,
                    baseline_confidence=1.0,
                    observed_at=now,
                    observed_value=evidence.current_demand_w,
                    baseline_value=evidence.demand_limit_w,
                    message=_demand_limit_message(config, evidence),
                    features=evidence.features,
                )
            )

        if result.monthly_peak_warning is not None:
            self._mark_store_dirty()
            evidence = result.monthly_peak_warning
            policy = self._demand_alert_policy_for_circuit(config.circuit_id)
            score = max(1.0, evidence.monthly_peak_usage_percent / 100.0)
            return policy.observe(
                Observation(
                    circuit_id=config.circuit_id,
                    feature="demand_monthly_peak",
                    score=score,
                    baseline_confidence=1.0,
                    observed_at=now,
                    observed_value=evidence.current_demand_w,
                    baseline_value=evidence.monthly_peak_cutoff_w,
                    message=_demand_monthly_peak_message(config, evidence),
                    features=evidence.features,
                )
            )

        return None

    def _observe_capacity(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        result = evaluate_circuit_capacity(
            circuit_id=config.circuit_id,
            current_amps=self._capacity_current_a(config, sample, now),
            real_power_w=_capacity_power_w(sample),
            voltage_v=_capacity_voltage_v(config, sample),
            settings=self._capacity_settings_for_config(config.circuit_id),
        )
        self.state.capacity_usage_by_circuit[config.circuit_id] = (
            result.capacity_usage_percent
        )
        self.state.capacity_status_by_circuit[config.circuit_id] = result.status
        self.state.capacity_evidence_by_circuit[config.circuit_id] = (
            _capacity_evidence_payload(result)
        )
        if result.status != "over_limit":
            return None

        policy = self._capacity_alert_policy_for_circuit(config.circuit_id)
        score = (
            result.current_amps / result.warning_threshold_amps
            if result.warning_threshold_amps > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="circuit_capacity",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=result.current_amps,
                baseline_value=result.warning_threshold_amps,
                message=_capacity_limit_message(config, result),
                features=result.features or {},
            )
        )

    def _observe_leg_imbalance(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        if config.mode is not CircuitMode.DUAL_PHASE:
            result = LegImbalanceResult(status="not_dual_phase")
        else:
            result = evaluate_dual_phase_leg_imbalance(
                left_real_power_w=getattr(sample, "leg_a_real_power", None),
                right_real_power_w=getattr(sample, "leg_b_real_power", None),
                left_current_a=getattr(sample, "leg_a_current", None),
                right_current_a=getattr(sample, "leg_b_current", None),
                left_voltage_v=getattr(sample, "leg_a_voltage", None),
                right_voltage_v=getattr(sample, "leg_b_voltage", None),
            )

        self.state.leg_imbalance_percent_by_circuit[config.circuit_id] = (
            result.imbalance_percent
        )
        self.state.leg_imbalance_status_by_circuit[config.circuit_id] = result.status
        self.state.leg_imbalance_evidence_by_circuit[config.circuit_id] = (
            _leg_imbalance_evidence_payload(result)
        )
        if result.status != "imbalanced":
            return None

        policy = self._leg_imbalance_alert_policy_for_circuit(config.circuit_id)
        score = (
            result.imbalance_ratio / result.threshold_ratio
            if result.threshold_ratio > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="dual_phase_leg_imbalance",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=result.imbalance_ratio,
                baseline_value=result.threshold_ratio,
                message=_leg_imbalance_message(config, result),
                features=result.features,
            )
        )

    def _observe_metric_consistency(
        self: Self,
        config: CircuitConfig,
        sample: Any,
    ) -> None:
        result = evaluate_metric_consistency(
            real_power_w=getattr(sample, "real_power", None),
            apparent_power_va=getattr(sample, "apparent_power", None),
            power_factor=getattr(sample, "power_factor", None),
            voltage_v=getattr(sample, "voltage", None),
            current_a=getattr(sample, "current", None),
            leg_a_voltage_v=getattr(sample, "leg_a_voltage", None),
            leg_a_current_a=getattr(sample, "leg_a_current", None),
            leg_b_voltage_v=getattr(sample, "leg_b_voltage", None),
            leg_b_current_a=getattr(sample, "leg_b_current", None),
        )
        self.state.metric_consistency_score_by_circuit[config.circuit_id] = (
            result.mismatch_score_percent
        )
        self.state.metric_consistency_status_by_circuit[config.circuit_id] = (
            result.status
        )
        self.state.metric_consistency_evidence_by_circuit[config.circuit_id] = (
            _metric_consistency_evidence_payload(result)
        )

    def _observe_standby(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        if (
            config.power_flow is PowerFlowMode.GENERATION
            or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
        ):
            self._clear_standby_state(config.circuit_id)
            return None

        power_w = _demand_power_w(sample)
        settings = self._standby_settings_for_config(config, config.circuit_id)
        result = record_standby_sample(
            self.store_data.standby_by_circuit.setdefault(config.circuit_id, {}),
            circuit_id=config.circuit_id,
            timestamp=now,
            real_power_w=power_w,
            settings=settings,
        )
        if result is None:
            return None

        self.state.always_on_power_w_by_circuit[config.circuit_id] = (
            result.always_on_power_w
        )
        self.state.standby_threshold_w_by_circuit[config.circuit_id] = (
            result.standby_threshold_w
        )
        self.state.standby_status_by_circuit[config.circuit_id] = result.status
        self.state.always_on_limit_usage_by_circuit[config.circuit_id] = (
            result.always_on_limit_usage
        )
        self.state.standby_evidence_by_circuit[config.circuit_id] = (
            _standby_evidence_payload(result)
        )

        if result.limit_exceeded is None:
            return None

        self._mark_store_dirty()
        evidence = result.limit_exceeded
        policy = self._standby_alert_policy_for_circuit(config.circuit_id)
        score = (
            evidence.always_on_power_w / evidence.always_on_alert_w
            if evidence.always_on_alert_w > 0.0
            else 0.0
        )
        return policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="always_on_power",
                score=score,
                baseline_confidence=1.0,
                observed_at=now,
                observed_value=evidence.always_on_power_w,
                baseline_value=evidence.always_on_alert_w,
                message=_standby_limit_message(config, evidence),
                features=evidence.features,
            )
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

    def _real_power_fallback_evidence(
        self: Self,
        scores: Iterable[Any],
        policy: ConservativeAlertPolicy,
    ) -> PowerQualityEvidence | None:
        for score in scores:
            if (
                score.feature == "real_power"
                and score.baseline_confidence
                >= policy.min_baseline_confidence
            ):
                return PowerQualityEvidence(
                    feature="real_power",
                    message="",
                    observed_value=score.observed_value,
                    baseline_value=score.baseline_value,
                    change_ratio=score.change_ratio,
                    score=score.score,
                    baseline_confidence=score.baseline_confidence,
                    features={"real_power": score.score},
                )
        return None

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

    def _update_power_quality_state(
        self: Self,
        circuit_id: str,
        scores: Iterable[Any],
        evidence: PowerQualityEvidence | None,
    ) -> None:
        def _drift(primary: str, fallback: str) -> float:
            candidates = [
                score
                for feature in (primary, fallback)
                if (score := by_feature.get(feature)) is not None
            ]
            if not candidates:
                return 0.0
            score = max(
                candidates,
                key=lambda candidate: (
                    abs(candidate.change_ratio),
                    candidate.score,
                ),
            )
            return abs(score.change_ratio)

        scores = list(scores)
        by_feature = {score.feature: score for score in scores}
        self.state.power_quality_score_by_circuit[circuit_id] = relationship_rms_score(
            scores
        )
        self.state.power_quality_evidence_by_circuit[circuit_id] = (
            evidence.message if evidence is not None else ""
        )
        self.state.reactive_power_drift_by_circuit[circuit_id] = _drift(
            "reactive_power",
            "reactive_to_real_ratio",
        )
        self.state.apparent_power_drift_by_circuit[circuit_id] = _drift(
            "apparent_power",
            "apparent_to_real_ratio",
        )
        self.state.power_factor_drift_by_circuit[circuit_id] = _drift(
            "power_factor",
            "power_factor_deficit",
        )

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
        if alert.circuit_id in self.paused_circuits:
            return
        if self._has_suppressed_alert_feedback(alert):
            return
        alert_id = notifications.notification_id_for_alert(alert)
        if alert_id in self._notified_alert_ids:
            return
        self._notified_alert_ids.add(alert_id)
        await notifications.async_create_alert_notification(self.hass, alert)


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _energy_usage_spike_message(
    config: CircuitConfig,
    spike: EnergyUsageSpike,
) -> str:
    share_percent = round(spike.daily_usage_share * 100, 1)
    threshold_percent = round(spike.threshold_ratio * 100)
    return (
        f"Possible issue: {config.name} used {_format_kwh(spike.daily_usage_kwh)} "
        f"kWh today, which is {share_percent}% of its last {spike.window_days} "
        f"days of usage ({_format_kwh(spike.baseline_total_kwh)} kWh). This is "
        f"above the configured {threshold_percent}% daily usage threshold."
    )


def _energy_usage_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "date": result.date,
        "daily_usage_kwh": result.daily_usage_kwh,
        "baseline_total_kwh": result.baseline_total_kwh,
        "baseline_window_days": result.window_days,
        "baseline_day_count": result.baseline_day_count,
        "threshold_ratio": result.threshold_ratio,
        "threshold_kwh": result.threshold_kwh,
        "daily_usage_share_percent": round(result.daily_usage_share * 100, 1),
        "status": (
            "over_threshold"
            if result.spike is not None
            else (
                "tracking"
                if result.baseline_day_count >= result.window_days
                else "learning"
            )
        ),
    }


def _energy_goal_message(
    config: CircuitConfig,
    evidence: EnergyGoalEvidence,
) -> str:
    return (
        f"Energy goal notice: {config.name} used "
        f"{_format_kwh(evidence.daily_usage_kwh)} kWh today, which is "
        f"{evidence.goal_usage_percent}% of its configured "
        f"{_format_kwh(evidence.daily_goal_kwh)} kWh daily goal."
    )


def _energy_goal_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "date": result.date,
        "daily_usage_kwh": result.daily_usage_kwh,
        "daily_goal_kwh": result.daily_goal_kwh,
        "goal_usage_percent": result.goal_usage_percent,
        "alert_threshold_kwh": result.alert_threshold_kwh,
        "goal_alert_ratio": result.goal_alert_ratio,
        "status": result.status,
    }


def _billing_cycle_budget_message(
    config: CircuitConfig,
    evidence: BillingCycleBudgetEvidence,
) -> str:
    return (
        f"Possible issue: {config.name} is projected to use "
        f"{_format_kwh(evidence.projected_cycle_kwh)} kWh in the "
        f"{evidence.cycle_start} to {evidence.cycle_end} billing cycle, above "
        f"the configured {_format_kwh(evidence.budget_kwh)} kWh "
        f"billing-cycle budget."
    )


def _billing_cycle_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "cycle_start": result.cycle_start,
        "cycle_end": result.cycle_end,
        "cycle_start_day": result.cycle_start_day,
        "cycle_usage_kwh": result.cycle_usage_kwh,
        "projected_cycle_kwh": result.projected_cycle_kwh,
        "elapsed_days": result.elapsed_days,
        "cycle_days": result.cycle_days,
        "budget_kwh": result.budget_kwh,
        "budget_alert_ratio": result.budget_alert_ratio,
        "budget_usage_percent": result.budget_usage_percent,
        "projected_budget_usage_percent": result.projected_budget_usage_percent,
        "status": result.status,
    }


def _cost_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "cycle_start": result.cycle_start,
        "cycle_end": result.cycle_end,
        "cycle_start_day": result.cycle_start_day,
        "current_rate_per_kwh": result.current_rate_per_kwh,
        "active_rate_name": result.active_rate_name,
        "delta_kwh": result.delta_kwh,
        "delta_cost": result.delta_cost,
        "cycle_cost": result.cycle_cost,
        "projected_cycle_cost": result.projected_cycle_cost,
        "elapsed_days": result.elapsed_days,
        "cycle_days": result.cycle_days,
        "status": result.status,
    }


def _demand_limit_message(
    config: CircuitConfig,
    evidence: DemandLimitEvidence,
) -> str:
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, above the configured "
        f"{_format_w(evidence.demand_limit_w)} W limit."
    )


def _demand_monthly_peak_message(
    config: CircuitConfig,
    evidence: DemandPeakEvidence,
) -> str:
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, near this month's top "
        f"{evidence.peak_rank_count} demand windows. It is "
        f"{_format_percent(evidence.monthly_peak_usage_percent)}% of the "
        f"{_format_w(evidence.monthly_peak_cutoff_w)} W cutoff."
    )


def _demand_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "date": result.date,
        "current_demand_w": result.current_demand_w,
        "peak_demand_w": result.peak_demand_w,
        "demand_window_minutes": result.window_minutes,
        "demand_limit_w": result.demand_limit_w,
        "demand_limit_usage_percent": result.demand_limit_usage,
        "status": (
            "over_limit"
            if result.limit_exceeded is not None
            else ("tracking" if result.demand_limit_w is not None else "unconfigured")
        ),
        "monthly_peak_rank": result.monthly_peak_rank,
        "monthly_peak_status": result.monthly_peak_status,
        "monthly_peak_cutoff_w": result.monthly_peak_cutoff_w,
        "monthly_peak_usage_percent": result.monthly_peak_usage_percent,
        "monthly_peak_rank_count": result.monthly_peak_rank_count,
        "monthly_peak_warning_ratio": result.monthly_peak_warning_ratio,
    }


def _capacity_limit_message(config: CircuitConfig, result: Any) -> str:
    return (
        f"Possible issue: {config.name} current is "
        f"{_format_amps(result.current_amps)} A, which is "
        f"{_format_percent(result.capacity_usage_percent)}% of the configured "
        f"{_format_amps(result.breaker_amps)} A circuit capacity. This is above "
        f"the configured {_format_percent(result.warning_ratio * 100)}% warning "
        f"level ({_format_amps(result.warning_threshold_amps)} A)."
    )


def _capacity_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "current_amps": result.current_amps,
        "breaker_amps": result.breaker_amps,
        "warning_threshold_amps": result.warning_threshold_amps,
        "capacity_usage_percent": result.capacity_usage_percent,
        "warning_ratio": result.warning_ratio,
        "current_source": result.current_source,
    }


def _leg_imbalance_message(
    config: CircuitConfig,
    result: LegImbalanceResult,
) -> str:
    return (
        f"Possible issue: {config.name} split-phase legs are imbalanced: "
        f"leg A is {_format_w(result.left_real_power_w or 0.0)} W and "
        f"leg B is {_format_w(result.right_real_power_w or 0.0)} W "
        f"({_format_percent(result.imbalance_percent)}% imbalance), above "
        f"the configured {_format_percent(result.threshold_percent)}% "
        "threshold. Review CT pairing, phase mapping, or appliance leg behavior."
    )


def _leg_imbalance_evidence_payload(
    result: LegImbalanceResult,
) -> dict[str, Any]:
    return {
        "status": result.status,
        "leg_imbalance_ratio": result.imbalance_ratio,
        "leg_imbalance_percent": result.imbalance_percent,
        "threshold_ratio": result.threshold_ratio,
        "threshold_percent": result.threshold_percent,
        "minimum_total_power_w": result.minimum_total_power_w,
        "left_real_power_w": result.left_real_power_w,
        "right_real_power_w": result.right_real_power_w,
        "left_current_a": result.left_current_a,
        "right_current_a": result.right_current_a,
        "left_voltage_v": result.left_voltage_v,
        "right_voltage_v": result.right_voltage_v,
        "voltage_difference_v": result.voltage_difference_v,
        "dominant_leg": result.dominant_leg,
    }


def _metric_consistency_evidence_payload(
    result: MetricConsistencyResult,
) -> dict[str, Any]:
    return {
        "status": result.status,
        "mismatch_score_percent": result.mismatch_score_percent,
        "expected_apparent_power_va": result.expected_apparent_power_va,
        "reported_apparent_power_va": result.reported_apparent_power_va,
        "apparent_power_difference_percent": (
            result.apparent_power_difference_percent
        ),
        "apparent_power_tolerance_percent": (
            result.apparent_power_tolerance_percent
        ),
        "apparent_power_source": result.apparent_power_source,
        "expected_power_factor": result.expected_power_factor,
        "reported_power_factor": result.reported_power_factor,
        "power_factor_difference": result.power_factor_difference,
        "power_factor_tolerance": result.power_factor_tolerance,
    }


def _standby_limit_message(
    config: CircuitConfig,
    evidence: StandbyLimitEvidence,
) -> str:
    return (
        f"Possible issue: {config.name} Always On is "
        f"{_format_w(evidence.always_on_power_w)} W over the last "
        f"{evidence.window_hours} hours, above the configured "
        f"{_format_w(evidence.always_on_alert_w)} W limit."
    )


def _standby_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "always_on_power_w": result.always_on_power_w,
        "current_power_w": result.current_power_w,
        "standby_threshold_w": result.standby_threshold_w,
        "sample_count": result.sample_count,
        "window_hours": result.window_hours,
        "always_on_alert_w": result.always_on_alert_w,
        "always_on_limit_usage_percent": result.always_on_limit_usage,
        "status": result.status,
    }


def _utility_comparison_message(config: CircuitConfig, result: Any) -> str:
    return (
        f"Utility comparison mismatch: {config.name} measured "
        f"{_format_kwh(result.measured_kwh or 0.0)} kWh while "
        f"{result.utility_source_id} reports "
        f"{_format_kwh(result.utility_kwh or 0.0)} kWh. Difference is "
        f"{_format_kwh(result.difference_kwh)} kWh "
        f"({_format_percent(result.absolute_difference_percent)}%), above the "
        f"{_format_percent(result.tolerance_percent)}% tolerance. Verify both "
        "sensors cover the same billing or current-bill period before treating "
        "this as a meter, CT, or utility-data problem."
    )


def _utility_comparison_evidence_payload(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "utility_energy_entity": result.utility_energy_entity,
        "utility_statistic_id": result.utility_statistic_id,
        "utility_source_id": result.utility_source_id,
        "utility_source_type": result.utility_source_type,
        "utility_statistic_period": result.utility_statistic_period,
        "measured_energy_entities": list(result.measured_entity_ids),
        "comparison_source": result.comparison_source,
        "measured_source_type": result.measured_source_type,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "utility_data_lag_hours": result.utility_data_lag_hours,
        "utility_kwh": result.utility_kwh,
        "measured_kwh": result.measured_kwh,
        "difference_kwh": result.difference_kwh,
        "difference_percent": result.difference_percent,
        "absolute_difference_percent": result.absolute_difference_percent,
        "tolerance_percent": result.tolerance_percent,
    }


def _is_flexible_solar_load(config: CircuitConfig) -> bool:
    return (
        config.power_flow is PowerFlowMode.LOAD
        and config.mode is not CircuitMode.MAINS_NILM
        and config.appliance_profile in FLEXIBLE_SOLAR_LOAD_PROFILES
    )


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_amps(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _datetime_iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _utility_source_type_for_settings(settings: UtilityComparisonSettings) -> str:
    raw = str(settings.utility_source_type or "auto").strip().lower()
    if raw == "statistic":
        raw = "statistics"
    if raw not in {"auto", "entity", "statistics"}:
        raw = "auto"
    if raw == "auto":
        return "statistics" if settings.utility_statistic_id.strip() else "entity"
    return raw


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


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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


def _alert_feedback_key(alert: AlertEvidence) -> str:
    return f"{alert.circuit_id}:{_alert_feature(alert)}"


def _nilm_review_payload(signature: dict[str, Any]) -> dict[str, Any]:
    payload = dict(signature)
    if payload.get("review_state"):
        return payload
    if payload.get("ignored"):
        payload["review_state"] = "ignored"
    elif payload.get("user_label"):
        payload["review_state"] = "labeled"
    else:
        payload["review_state"] = "new"
    return payload


def _nilm_topology_evidence_payload(
    *,
    mains_config: CircuitConfig,
    known_config: CircuitConfig,
    match: KnownLoadMatch,
) -> dict[str, Any]:
    expected_types = _expected_nilm_split_phase_types(known_config)
    observed_type = str(match.edge.split_phase_type or "unknown")
    configured_leg = _configured_single_phase_leg(known_config)
    observed_leg = _observed_single_phase_leg(observed_type, match.edge.dominant_leg)
    suggested_leg = (
        observed_leg if known_config.mode is CircuitMode.SINGLE_PHASE else None
    )
    if not expected_types:
        status = "not_evaluated"
    elif observed_type in {"unknown", "missing_leg_data"}:
        status = "unknown_topology"
    elif observed_type in expected_types:
        status = "consistent"
    else:
        status = "topology_mismatch"
    if (
        status == "consistent"
        and configured_leg is not None
        and observed_leg is not None
        and configured_leg != observed_leg
    ):
        status = "leg_mismatch"

    return {
        "status": status,
        "matched_mains_circuit_id": mains_config.circuit_id,
        "event_type": "start" if match.edge.direction == "on" else "stop",
        "configured_mode": known_config.mode.value,
        "configured_leg": configured_leg,
        "expected_split_phase_types": list(expected_types),
        "expected_dominant_legs": list(
            _expected_nilm_dominant_legs(known_config, configured_leg)
        ),
        "observed_split_phase_type": observed_type,
        "observed_dominant_leg": match.edge.dominant_leg,
        "observed_leg": observed_leg,
        "suggested_leg": suggested_leg,
        "observed_leg_a_delta_w": _round_optional_number(match.edge.leg_a_delta_w),
        "observed_leg_b_delta_w": _round_optional_number(match.edge.leg_b_delta_w),
        "observed_leg_balance_ratio": _round_optional_number(
            match.edge.leg_balance_ratio
        ),
        "matched_delta_w": _round_number(match.edge.delta_w),
        "known_event_power_w": _round_number(match.known_power_w),
        "match_confidence": _round_number(match.confidence),
    }


def _expected_nilm_split_phase_types(config: CircuitConfig) -> tuple[str, ...]:
    if config.mode is CircuitMode.SINGLE_PHASE:
        return ("single_leg_a", "single_leg_b")
    if config.mode is CircuitMode.DUAL_PHASE:
        return ("balanced_240v",)
    return ()


def _expected_nilm_dominant_legs(
    config: CircuitConfig,
    configured_leg: str | None,
) -> tuple[str, ...]:
    if config.mode is CircuitMode.SINGLE_PHASE:
        if configured_leg is not None:
            return (configured_leg,)
        return ("a", "b")
    if config.mode is CircuitMode.DUAL_PHASE:
        return ("balanced",)
    return ()


def _configured_single_phase_leg(config: CircuitConfig) -> str | None:
    if config.mode is not CircuitMode.SINGLE_PHASE:
        return None
    legs = {
        normalized
        for sensor in config.sensors
        if (normalized := _normalized_leg(sensor.leg)) is not None
    }
    if len(legs) == 1:
        return next(iter(legs))
    return None


def _observed_single_phase_leg(
    observed_type: str,
    dominant_leg: str,
) -> str | None:
    if observed_type == "single_leg_a":
        return "a"
    if observed_type == "single_leg_b":
        return "b"
    return None


def _nilm_topology_alert_feature(status: str) -> str:
    if status == "leg_mismatch":
        return "nilm_leg_mismatch"
    return "nilm_topology_mismatch"


def _nilm_topology_mismatch_message(
    config: CircuitConfig,
    evidence: dict[str, Any],
) -> str:
    if evidence.get("status") == "leg_mismatch":
        configured_leg = evidence.get("configured_leg", "unknown")
        observed_leg = evidence.get("observed_leg", "unknown")
        return (
            f"Possible issue: {config.name} is configured on leg "
            f"{configured_leg}, but mains NILM repeatedly matched it on leg "
            f"{observed_leg}. Verify circuit mapping, CT orientation, and "
            "whether another appliance changed at the same time before "
            "treating this as an appliance problem."
        )

    observed_type = evidence.get("observed_split_phase_type", "unknown")
    expected = ", ".join(evidence.get("expected_split_phase_types") or [])
    return (
        f"Possible issue: {config.name} is configured as "
        f"{_circuit_mode_phrase(config.mode)}, but mains NILM repeatedly matched "
        f"it as {observed_type}. Expected {expected or 'no topology check'} from "
        "the configured circuit mode. Verify circuit mapping, CT orientation, "
        "and whether another appliance changed at the same time before treating "
        "this as an appliance problem."
    )


def _circuit_mode_phrase(mode: CircuitMode) -> str:
    return str(mode.value).replace("_", " ")


def _nilm_signature_metadata_compatible(
    signature: Any,
    current: dict[str, Any],
) -> bool:
    if not current:
        return False

    current_type = str(current.get("split_phase_type") or "")
    signature_type = str(getattr(signature, "split_phase_type", "unknown") or "unknown")
    if current_type:
        if not _nilm_split_phase_metadata_compatible(current_type, signature_type):
            return False
    elif signature_type not in {"unknown", "missing_leg_data"}:
        return False

    checks = (
        ("median_delta_w", 0.2),
        ("median_delta_var", 0.35),
        ("median_delta_va", 0.35),
    )
    for key, tolerance_ratio in checks:
        current_value = _float_or_none(current.get(key))
        signature_value = _float_or_none(getattr(signature, key, None))
        if current_value is None or signature_value is None:
            continue
        tolerance = max(abs(signature_value) * tolerance_ratio, 25.0)
        if abs(current_value - signature_value) > tolerance:
            return False

    return True


def _nilm_split_phase_metadata_compatible(
    current_type: str,
    signature_type: str,
) -> bool:
    uncertain = {"unknown", "missing_leg_data"}
    if current_type in uncertain or signature_type in uncertain:
        return current_type in uncertain and signature_type in uncertain
    return current_type == signature_type


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


def _sum_sample_values(
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
    return float(sum(values))


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


def _capacity_power_w(sample: Any) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    return abs(float(power))


def _capacity_voltage_v(config: CircuitConfig, sample: Any) -> float | None:
    voltage = getattr(sample, "voltage", None)
    if voltage is None:
        return None
    multiplier = 2.0 if config.mode is CircuitMode.DUAL_PHASE else 1.0
    return abs(float(voltage)) * multiplier


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


def _data_quality_problem(issue: str) -> str:
    issue_text = issue.lower()
    if "negative_real_power_load" in issue_text:
        return "unexpected_negative_real_power"
    if "stale" in issue_text:
        return "stale_source_sensor"
    return "missing_required_sensor"


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
    for suffix in (
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
    ):
        if object_id.endswith(suffix):
            return _strip_trailing_leg_token(object_id[: -len(suffix)])
    return _strip_trailing_leg_token(object_id)


def _strip_trailing_leg_token(object_id: str) -> str:
    for suffix in (
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
    ):
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _entity_object_id(entity_id: str) -> str:
    return str(entity_id).split(".")[-1].strip().lower()


def _has_metric_suffix(object_id: str, metric_suffixes: Iterable[str]) -> bool:
    normalized = object_id.strip().lower()
    return any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in metric_suffixes
    )


def _friendly_name_from_circuit_id(circuit_id: str) -> str:
    return str(circuit_id).replace("_", " ").strip().title()


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
        (("_oven_", "_range_"), ApplianceProfile.OVEN, CircuitMode.DUAL_PHASE),
        (("_dryer_",), ApplianceProfile.DRYER, CircuitMode.DUAL_PHASE),
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
