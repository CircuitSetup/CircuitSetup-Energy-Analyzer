from __future__ import annotations

from datetime import datetime
from typing import Any

from ..cycles import cycle_summary_payload, summarize_circuit_cycles
from ..energy_dashboard import evaluate_energy_dashboard_readiness, readiness_payload
from ..models import AlertEvidence, ApplianceProfile, CircuitConfig, CircuitMode
from ..normalize import NormalizedCircuitSample
from ..operating_detection import resolve_operating_detection_from_settings
from ..ux import data_quality_checklist, health_summary, learning_progress


class UxStateManager:
    """Hydrate and refresh user-facing runtime UX state."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def hydrate_state_from_store(self) -> None:
        coordinator = self._coordinator
        maintenance_by_circuit = coordinator.store_data.maintenance_by_circuit
        for circuit_id, maintenance in maintenance_by_circuit.items():
            if maintenance.get("active") is True:
                coordinator.paused_circuits.add(circuit_id)
        coordinator.nilm_controller.hydrate_state_from_store()
        coordinator.state_reducer.hydrate_context_state_from_store(
            coordinator.state,
            coordinator.store_data,
        )
        self.refresh_all(coordinator.current_time())
        coordinator._refresh_settings_recommendation_state(coordinator.current_time())

    def refresh_all(self, now: datetime) -> None:
        for config in self._coordinator.circuit_configs:
            self.refresh_config(config, None, now)

    def refresh_for_circuit(self, circuit_id: str, now: datetime) -> None:
        config = self._coordinator.circuit_registry.config_for_circuit(circuit_id)
        if config is not None:
            self.refresh_config(config, None, now)

    def refresh_config(
        self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample | None,
        now: datetime,
        context: Any | None = None,
    ) -> None:
        coordinator = self._coordinator
        circuit_id = config.circuit_id
        checklist = data_quality_checklist(config, sample)
        if (
            sample is None
            and circuit_id in coordinator.state.data_quality_checklist_by_circuit
        ):
            checklist = dict(
                coordinator.state.data_quality_checklist_by_circuit[circuit_id]
            )
        coordinator.state.data_quality_checklist_by_circuit[circuit_id] = checklist

        dashboard_readiness = evaluate_energy_dashboard_readiness(
            config,
            coordinator._source_states_for(config, now),
        )
        coordinator.state.energy_dashboard_status_by_circuit[circuit_id] = (
            dashboard_readiness.status
        )
        coordinator.state.energy_dashboard_evidence_by_circuit[circuit_id] = (
            readiness_payload(dashboard_readiness)
        )

        learning = coordinator.state.learning_by_circuit.get(circuit_id, True)
        suppression_reason = self.suppression_reason(circuit_id, learning)
        progress = learning_progress(
            config,
            events=coordinator.store_data.events,
            baselines=coordinator.store_data.baselines,
            baseline_buffer_counts={
                key: len(values) for key, values in coordinator._baseline_values.items()
            },
            now=now,
            learning=learning,
            suppression_reason=suppression_reason,
        )
        coordinator.state.learning_progress_by_circuit[circuit_id] = progress

        merge_gap_seconds = resolve_operating_detection_from_settings(
            config,
            getattr(
                coordinator.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_id, {}),
        ).profile.merge_gap_seconds
        cycle_summary = summarize_circuit_cycles(
            coordinator.store_data.events,
            circuit_id=circuit_id,
            now=now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=coordinator.context_builder.time_zone(),
        )
        coordinator.state.run_cycle_count_by_circuit[circuit_id] = (
            cycle_summary.start_count
        )
        coordinator.state.run_cycle_runtime_seconds_by_circuit[circuit_id] = (
            cycle_summary.runtime_seconds
        )
        coordinator.state.run_cycle_duty_cycle_by_circuit[circuit_id] = (
            cycle_summary.duty_cycle_percent
        )
        coordinator.state.run_cycle_status_by_circuit[circuit_id] = cycle_summary.status
        coordinator.state.run_cycle_evidence_by_circuit[circuit_id] = (
            cycle_summary_payload(cycle_summary)
        )

        coordinator.environment_context.refresh_weather_context_state(config, now)
        coordinator.environment_context.refresh_water_context_state(config, now)

        maintenance = dict(
            coordinator.store_data.maintenance_by_circuit.get(circuit_id, {})
        )
        maintenance.setdefault("active", circuit_id in coordinator.paused_circuits)
        coordinator.state.maintenance_by_circuit[circuit_id] = maintenance
        coordinator.state.sensitivity_by_circuit[circuit_id] = (
            coordinator.settings_controller.sensitivity_for_circuit(circuit_id)
        )
        coordinator.state_reducer.refresh_alert_evidence_state(
            coordinator.state,
            circuit_id,
            self.latest_alert_for_circuit(circuit_id),
            config=coordinator.circuit_registry.config_for_circuit(circuit_id),
        )
        coordinator.state_reducer.refresh_recent_activity_state(
            coordinator.state,
            coordinator.store_data,
            circuit_id,
            now,
        )
        coordinator.nilm_controller.refresh_state(circuit_id, context)

        status, summary = health_summary(
            data_quality_problem=bool(
                coordinator.state.data_quality_by_circuit.get(circuit_id)
            ),
            paused=bool(maintenance.get("active"))
            or circuit_id in coordinator.paused_circuits,
            active_alerts=bool(
                coordinator.state.active_alerts_by_circuit.get(circuit_id)
            ),
            observations=bool(
                coordinator.state.recent_observations_by_circuit.get(circuit_id)
            ),
            nilm_review_count=len(
                coordinator.state.nilm_review_by_circuit.get(circuit_id, [])
            ),
            mixed=(
                config.mode is CircuitMode.MIXED
                or config.appliance_profile is ApplianceProfile.MIXED
            ),
            learning=learning,
        )
        coordinator.state.health_status_by_circuit[circuit_id] = status
        coordinator.state.health_summary_by_circuit[circuit_id] = summary
        coordinator.state.readiness_by_circuit[circuit_id] = {
            **progress,
            "required_metric_coverage": checklist["required_metric_coverage"],
            "optional_metric_coverage": checklist["optional_metric_coverage"],
            "health_status": status,
            "health_summary": summary,
        }

    def suppression_reason(self, circuit_id: str, learning: bool) -> str | None:
        coordinator = self._coordinator
        if coordinator.state.data_quality_by_circuit.get(circuit_id):
            return "data_quality"
        if circuit_id in coordinator.paused_circuits:
            return "paused"
        if learning:
            return "learning"
        return None

    def latest_alert_for_circuit(self, circuit_id: str) -> AlertEvidence | None:
        coordinator = self._coordinator
        alerts = list(coordinator.state.active_alerts_by_circuit.get(circuit_id, []))
        if not alerts:
            alerts = [
                alert
                for alert in coordinator.store_data.alerts
                if alert.circuit_id == circuit_id
            ]
        if not alerts:
            return None
        return max(alerts, key=lambda alert: alert.timestamp)
