from __future__ import annotations

from datetime import datetime
from typing import Any

from ..contextual_baseline import (
    build_context_for_sample,
    daily_energy_fallback_contexts,
    select_contextual_baseline,
    stored_contextual_samples,
)
from ..cycles import (
    RUN_CYCLE_RUNTIME_TODAY_FEATURE,
    RUN_CYCLE_START_COUNT_FEATURE,
    cycle_summary_payload,
    summarize_circuit_cycles,
)
from ..energy_dashboard import evaluate_energy_dashboard_readiness, readiness_payload
from ..local_time import as_ha_local, local_date
from ..models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
)
from ..normalize import NormalizedCircuitSample
from ..operating_detection import resolve_operating_detection_from_settings
from ..state import circuit_is_learning
from ..usage import _coerce_days, _usage_for_date
from ..ux import data_quality_checklist, health_summary, learning_progress


class UxStateManager:
    """Hydrate and refresh user-facing runtime UX state."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def hydrate_state_from_store(self) -> None:
        coordinator = self._coordinator
        now = coordinator.current_time()
        maintenance_by_circuit = coordinator.store_data.maintenance_by_circuit
        for circuit_id, maintenance in maintenance_by_circuit.items():
            if coordinator.evidence_actions.expire_maintenance_if_due(circuit_id, now):
                continue
            if maintenance.get("active") is True:
                coordinator.paused_circuits.add(circuit_id)
        coordinator.nilm_controller.hydrate_state_from_store()
        coordinator.state_reducer.hydrate_context_state_from_store(
            coordinator.state,
            coordinator.store_data,
        )
        today = local_date(now, coordinator.context_builder.time_zone()).isoformat()
        for config in coordinator.circuit_configs:
            history = coordinator.store_data.energy_usage_by_circuit.get(
                config.circuit_id,
                {},
            )
            coordinator.state.daily_energy_usage_by_circuit[config.circuit_id] = (
                _usage_for_date(_coerce_days(history.get("days")), today)
            )
        self.refresh_all(now)
        coordinator._refresh_settings_recommendation_state(now)

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
        coordinator.evidence_actions.expire_maintenance_if_due(circuit_id, now)
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

        learning = circuit_is_learning(coordinator.state, circuit_id)
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
        cycle_evidence = cycle_summary_payload(cycle_summary)
        cycle_evidence.update(
            _same_time_cycle_evidence(
                config=config,
                sample=sample,
                state=coordinator.state,
                store_data=coordinator.store_data,
                summary=cycle_summary,
                now=now,
                time_zone=coordinator.context_builder.time_zone(),
                contextual_samples_cache=(
                    context.contextual_samples_cache if context is not None else None
                ),
            )
        )
        coordinator.state.run_cycle_evidence_by_circuit[circuit_id] = cycle_evidence

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


def _same_time_cycle_evidence(
    *,
    config: CircuitConfig,
    sample: NormalizedCircuitSample | None,
    state: Any,
    store_data: Any,
    summary: Any,
    now: datetime,
    time_zone: str | None,
    contextual_samples_cache: Any | None = None,
) -> dict[str, Any]:
    context_sample = sample or NormalizedCircuitSample(
        timestamp=now,
        circuit_id=config.circuit_id,
    )
    current_date = local_date(now, time_zone)
    raw_samples = store_data.contextual_baseline_samples_by_circuit.get(
        config.circuit_id,
        [],
    )
    historical = [
        item
        for item in stored_contextual_samples(
            config.circuit_id,
            raw_samples,
            cache=contextual_samples_cache,
        )
        if local_date(item.timestamp, time_zone) < current_date
    ]
    evidence: dict[str, Any] = {
        "comparison_mode": "same_time_of_day",
        "as_of": as_ha_local(now, time_zone).isoformat(),
    }
    metrics = (
        (
            RUN_CYCLE_RUNTIME_TODAY_FEATURE,
            "runtime_today",
            float(summary.runtime_seconds),
            "runtime_today_contextual_expected_range_seconds",
            "runtime_today_contextual_baseline_median_seconds",
            "runtime_today_contextual_baseline_confidence",
        ),
        (
            RUN_CYCLE_START_COUNT_FEATURE,
            "run_count",
            float(summary.start_count),
            "run_count_contextual_expected_range",
            "run_count_contextual_baseline_median",
            "run_count_contextual_baseline_confidence",
        ),
    )
    for (
        feature,
        projection_prefix,
        current_value,
        range_key,
        median_key,
        confidence_key,
    ) in metrics:
        context_key = build_context_for_sample(
            circuit_config=config,
            sample=context_sample,
            state=state,
            store_data=store_data,
            now=now,
            feature=feature,
            time_zone=time_zone,
            calendar_timestamp=now,
        )
        selected = select_contextual_baseline(
            circuit_id=config.circuit_id,
            feature=feature,
            samples=historical,
            fallback_contexts=daily_energy_fallback_contexts(context_key),
        )
        if selected is None:
            continue
        evidence[range_key] = [round(selected.p10, 3), round(selected.p90, 3)]
        evidence[median_key] = round(selected.median, 3)
        evidence[confidence_key] = selected.confidence
        full_period = store_data.baselines.get(f"{config.circuit_id}:{feature}")
        if (
            isinstance(full_period, BaselineStats)
            and selected.median > 0.0
            and current_value >= 0.0
        ):
            ratio = current_value / selected.median
            evidence[f"{projection_prefix}_projection_value"] = round(
                full_period.median * ratio,
                3,
            )
            evidence[f"{projection_prefix}_projection_low"] = round(
                full_period.p10 * ratio,
                3,
            )
            evidence[f"{projection_prefix}_projection_high"] = round(
                full_period.p90 * ratio,
                3,
            )
            evidence[f"{projection_prefix}_projection_confidence"] = round(
                min(selected.confidence, full_period.confidence) * 0.66,
                3,
            )
    return evidence
