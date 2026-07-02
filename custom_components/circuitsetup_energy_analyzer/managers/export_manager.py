from __future__ import annotations

from typing import Any

from ..appliance_detail import appliance_detail_for_circuit
from ..exporting import build_circuit_history_csv


class ExportManager:
    """Build user-triggered diagnostics and history exports."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_export_diagnostics(self, circuit_id: str) -> None:
        """Store a lightweight diagnostics export snapshot for a circuit."""
        coordinator = self._coordinator
        state = coordinator.state
        appliance_detail = appliance_detail_for_circuit(coordinator, circuit_id)
        coordinator.last_exported_diagnostics = {
            "circuit_id": circuit_id,
            "appliance_detail": (
                appliance_detail.as_dict() if appliance_detail is not None else None
            ),
            "anomaly_score": state.anomaly_score_by_circuit.get(circuit_id, 0.0),
            "data_quality": state.data_quality_by_circuit.get(circuit_id),
            "learning": state.learning_by_circuit.get(circuit_id, True),
            "power_quality_score": state.power_quality_score_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "power_quality_evidence": state.power_quality_evidence_by_circuit.get(
                circuit_id,
                "",
            ),
            "reactive_power_drift": state.reactive_power_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "apparent_power_drift": state.apparent_power_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "power_factor_drift": state.power_factor_drift_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "health_status": state.health_status_by_circuit.get(circuit_id),
            "health_summary": state.health_summary_by_circuit.get(circuit_id),
            "readiness": state.readiness_by_circuit.get(circuit_id, {}),
            "learning_progress": state.learning_progress_by_circuit.get(
                circuit_id,
                {},
            ),
            "data_quality_checklist": state.data_quality_checklist_by_circuit.get(
                circuit_id,
                {},
            ),
            "alert_evidence": state.alert_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "sensitivity": state.sensitivity_by_circuit.get(circuit_id),
            "maintenance": state.maintenance_by_circuit.get(circuit_id, {}),
            "nilm_review": state.nilm_review_by_circuit.get(circuit_id, []),
            "daily_energy_usage_kwh": state.daily_energy_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "energy_usage_share_percent": state.energy_usage_share_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "energy_usage_evidence": state.energy_usage_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "energy_goal_usage_percent": (
                state.energy_goal_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "energy_goal_status": state.energy_goal_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "energy_goal_evidence": state.energy_goal_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "run_cycle_count": state.run_cycle_count_by_circuit.get(
                circuit_id,
                0,
            ),
            "run_cycle_runtime_seconds": (
                state.run_cycle_runtime_seconds_by_circuit.get(circuit_id, 0.0)
            ),
            "run_cycle_duty_cycle_percent": (
                state.run_cycle_duty_cycle_by_circuit.get(circuit_id, 0.0)
            ),
            "run_cycle_status": state.run_cycle_status_by_circuit.get(
                circuit_id,
                "no_activity",
            ),
            "run_cycle_evidence": state.run_cycle_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "billing_cycle_usage_kwh": (
                state.billing_cycle_usage_kwh_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_forecast_kwh": (
                state.billing_cycle_forecast_kwh_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_budget_usage_percent": (
                state.billing_cycle_budget_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "billing_cycle_status": state.billing_cycle_status_by_circuit.get(
                circuit_id,
                "no_budget",
            ),
            "billing_cycle_evidence": (
                state.billing_cycle_evidence_by_circuit.get(circuit_id, {})
            ),
            "cost_current_rate_per_kwh": state.cost_current_rate_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "cost_cycle": state.cost_cycle_by_circuit.get(circuit_id, 0.0),
            "cost_cycle_forecast": state.cost_cycle_forecast_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "cost_status": state.cost_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "cost_evidence": state.cost_evidence_by_circuit.get(circuit_id, {}),
            "current_demand_w": state.current_demand_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "peak_demand_w": state.peak_demand_w_by_circuit.get(circuit_id, 0.0),
            "demand_limit_usage_percent": (
                state.demand_limit_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "demand_evidence": state.demand_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "capacity_usage_percent": state.capacity_usage_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "capacity_status": state.capacity_status_by_circuit.get(
                circuit_id,
                "unconfigured",
            ),
            "capacity_evidence": state.capacity_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
            "utility_comparison_difference_kwh": (
                state.utility_comparison_difference_kwh_by_circuit.get(
                    circuit_id,
                    0.0,
                )
            ),
            "utility_comparison_difference_percent": (
                state.utility_comparison_difference_percent_by_circuit.get(
                    circuit_id,
                    0.0,
                )
            ),
            "utility_comparison_status": (
                state.utility_comparison_status_by_circuit.get(
                    circuit_id,
                    "unconfigured",
                )
            ),
            "utility_comparison_evidence": (
                state.utility_comparison_evidence_by_circuit.get(
                    circuit_id,
                    {},
                )
            ),
            "always_on_power_w": state.always_on_power_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "standby_threshold_w": state.standby_threshold_w_by_circuit.get(
                circuit_id,
                0.0,
            ),
            "standby_status": state.standby_status_by_circuit.get(
                circuit_id,
                "learning",
            ),
            "always_on_limit_usage_percent": (
                state.always_on_limit_usage_by_circuit.get(circuit_id, 0.0)
            ),
            "standby_evidence": state.standby_evidence_by_circuit.get(
                circuit_id,
                {},
            ),
        }
        coordinator.async_set_updated_data(state)

    async def async_export_history_csv(self, circuit_id: str) -> None:
        """Store retained analyzer history for one circuit as CSV text."""
        coordinator = self._coordinator
        coordinator.last_exported_history_csv = build_circuit_history_csv(
            coordinator.store_data,
            circuit_id,
        )
        coordinator.async_set_updated_data(coordinator.state)
