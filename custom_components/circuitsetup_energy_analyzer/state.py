"""Analyzer runtime state and event-reduction compatibility helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .alerting import alert_anomaly_score
from .managers.state_reducer import apply_state_update
from .models import AlertEvidence, CircuitEvent


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
    expected_schedule_by_appliance: dict[str, dict[str, Any]] = field(
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
    cost_today_by_circuit: dict[str, float | None] = field(default_factory=dict)
    cost_today_status_by_circuit: dict[str, str] = field(default_factory=dict)
    cost_cycle_by_circuit: dict[str, float] = field(default_factory=dict)
    cost_cycle_status_by_circuit: dict[str, str] = field(default_factory=dict)
    cost_cycle_forecast_by_circuit: dict[str, float] = field(default_factory=dict)
    cost_status_by_circuit: dict[str, str] = field(default_factory=dict)
    cost_evidence_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    utility_cost_rate_by_circuit: dict[str, float] = field(default_factory=dict)
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
