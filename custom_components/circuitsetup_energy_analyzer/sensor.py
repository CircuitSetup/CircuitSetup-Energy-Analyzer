from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import DOMAIN
from .entity import (
    CircuitAnalyzerEntity,
    circuit_info_from_config,
    circuits_for_entities,
)

try:
    from homeassistant.components.sensor import SensorEntity, SensorStateClass
    from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
except ModuleNotFoundError:
    PERCENTAGE = "%"

    class UnitOfEnergy:
        """Fallback energy unit constants."""

        KILO_WATT_HOUR = "kWh"

    class UnitOfPower:
        """Fallback power unit constants."""

        WATT = "W"

    class SensorEntity:
        """Fallback sensor base for tests without Home Assistant."""

        @property
        def state(self) -> Any:
            return getattr(self, "native_value", None)

    class SensorStateClass:
        """Fallback sensor state class constants."""

        MEASUREMENT = "measurement"


def anomaly_score_value(state: Any, circuit_id: str) -> float:
    """Return the current anomaly score for a circuit."""
    return float(getattr(state, "anomaly_score_by_circuit", {}).get(circuit_id, 0.0))


def last_event_value(state: Any, circuit_id: str) -> str | None:
    """Return the last event type value for a circuit."""
    event = getattr(state, "last_event_by_circuit", {}).get(circuit_id)
    if event is None:
        return None
    return event.event_type.value


def health_summary_value(state: Any, circuit_id: str) -> str:
    """Return a dashboard-friendly health summary for a circuit."""
    summary = getattr(state, "health_summary_by_circuit", {}).get(circuit_id)
    if summary:
        return str(summary)

    status = readiness_value(state, circuit_id)
    return {
        "learning": "Learning",
        "ready": "Ready",
        "needs_data": "Needs data",
        "paused": "Paused",
        "possible_issue": "Possible issue",
        "mixed_observation": "Mixed observation",
        "nilm_review": "NILM review",
    }.get(status, str(status).replace("_", " ").title())


def readiness_value(state: Any, circuit_id: str) -> str:
    """Return the readiness/health status for a circuit."""
    readiness = getattr(state, "readiness_by_circuit", {}).get(circuit_id, {})
    if isinstance(readiness, Mapping) and readiness.get("health_status"):
        return str(readiness["health_status"])

    status = getattr(state, "health_status_by_circuit", {}).get(circuit_id)
    if status:
        return str(status)

    if getattr(state, "learning_by_circuit", {}).get(circuit_id) is True:
        return "learning"
    return "ready"


def learning_progress_value(state: Any, circuit_id: str) -> float:
    """Return learning progress as a dashboard-friendly percentage."""
    progress = getattr(state, "learning_progress_by_circuit", {}).get(circuit_id, {})
    if not isinstance(progress, Mapping):
        return 0.0
    if progress.get("alert_ready") is True:
        return 100.0

    learned_count = _numeric_count(progress.get("learned_feature_count"))
    pending_samples = progress.get("pending_feature_samples", {})
    if isinstance(pending_samples, Mapping):
        pending_count = sum(_numeric_count(value) for value in pending_samples.values())
    else:
        pending_count = _numeric_count(pending_samples)

    total = learned_count + pending_count
    if total <= 0:
        return 0.0
    return round((learned_count / total) * 100.0, 1)


def data_quality_checklist_value(state: Any, circuit_id: str) -> str:
    """Return ok/problem based on data-quality checklist state."""
    checklist = getattr(state, "data_quality_checklist_by_circuit", {}).get(
        circuit_id,
        {},
    )
    if not isinstance(checklist, Mapping):
        return "problem"
    if checklist.get("quality_issues"):
        return "problem"
    if checklist.get("required_sensors_present") is not True:
        return "problem"
    for key in ("numeric_states_valid", "source_data_fresh"):
        if key in checklist and checklist[key] is not True:
            return "problem"
    return "ok"


def energy_dashboard_status_value(state: Any, circuit_id: str) -> str:
    """Return whether circuit sources are ready for HA Energy Dashboard."""
    return str(
        getattr(state, "energy_dashboard_status_by_circuit", {}).get(
            circuit_id,
            "needs_energy_source",
        )
    )


def alert_evidence_value(state: Any, circuit_id: str) -> str:
    """Return the feature named in the latest alert evidence."""
    evidence = getattr(state, "alert_evidence_by_circuit", {}).get(circuit_id, {})
    if isinstance(evidence, Mapping):
        return str(evidence.get("feature") or "")

    alerts = getattr(state, "active_alerts_by_circuit", {}).get(circuit_id, [])
    if alerts:
        return str(getattr(alerts[-1], "feature", "") or "")
    return ""


def sensitivity_value(state: Any, circuit_id: str) -> str:
    """Return the active sensitivity preset for a circuit."""
    return str(
        getattr(state, "sensitivity_by_circuit", {}).get(circuit_id, "balanced")
    )


def power_quality_score_value(state: Any, circuit_id: str) -> float:
    """Return the current power-quality relationship score for a circuit."""
    return float(
        getattr(state, "power_quality_score_by_circuit", {}).get(circuit_id, 0.0)
    )


def power_quality_evidence_value(state: Any, circuit_id: str) -> str:
    """Return the current power-quality evidence message for a circuit."""
    return str(
        getattr(state, "power_quality_evidence_by_circuit", {}).get(circuit_id, "")
    )


def reactive_power_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current reactive-power drift ratio for a circuit."""
    return float(
        getattr(state, "reactive_power_drift_by_circuit", {}).get(circuit_id, 0.0)
    )


def apparent_power_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current apparent-power drift ratio for a circuit."""
    return float(
        getattr(state, "apparent_power_drift_by_circuit", {}).get(circuit_id, 0.0)
    )


def power_factor_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current power-factor drift ratio for a circuit."""
    return float(
        getattr(state, "power_factor_drift_by_circuit", {}).get(circuit_id, 0.0)
    )


def nilm_signature_count_value(state: Any, circuit_id: str) -> int:
    """Return the number of discovered NILM signatures for a circuit."""
    return int(
        getattr(state, "nilm_signature_count_by_circuit", {}).get(circuit_id, 0)
    )


def nilm_unmatched_load_percentage_value(state: Any, circuit_id: str) -> float:
    """Return the NILM unmatched load percentage for a circuit."""
    return float(
        getattr(state, "nilm_unmatched_load_percentage_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def daily_energy_usage_value(state: Any, circuit_id: str) -> float:
    """Return today's cumulative usage derived from the circuit energy sensor."""
    return float(
        getattr(state, "daily_energy_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_usage_share_value(state: Any, circuit_id: str) -> float:
    """Return today's usage as a percent of the learned energy window."""
    return float(
        getattr(state, "energy_usage_share_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_usage_status_value(state: Any, circuit_id: str) -> str:
    """Return the daily energy usage tracker status."""
    evidence = getattr(state, "energy_usage_evidence_by_circuit", {}).get(
        circuit_id,
        {},
    )
    if isinstance(evidence, Mapping):
        return str(evidence.get("status") or "learning")
    return "learning"


def energy_goal_usage_value(state: Any, circuit_id: str) -> float:
    """Return today's usage as a percent of the configured daily goal."""
    return float(
        getattr(state, "energy_goal_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def energy_goal_status_value(state: Any, circuit_id: str) -> str:
    """Return the daily energy goal tracker status."""
    return str(
        getattr(state, "energy_goal_status_by_circuit", {}).get(
            circuit_id,
            "unconfigured",
        )
    )


def run_cycle_count_value(state: Any, circuit_id: str) -> int:
    """Return today's appliance start count from retained event evidence."""
    return int(getattr(state, "run_cycle_count_by_circuit", {}).get(circuit_id, 0))


def run_cycle_runtime_value(state: Any, circuit_id: str) -> float:
    """Return today's appliance runtime in seconds."""
    return float(
        getattr(state, "run_cycle_runtime_seconds_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def run_cycle_duty_cycle_value(state: Any, circuit_id: str) -> float:
    """Return today's appliance duty cycle as a percentage."""
    return float(
        getattr(state, "run_cycle_duty_cycle_by_circuit", {}).get(circuit_id, 0.0)
    )


def run_cycle_status_value(state: Any, circuit_id: str) -> str:
    """Return today's appliance run-cycle status."""
    return str(
        getattr(state, "run_cycle_status_by_circuit", {}).get(
            circuit_id,
            "no_activity",
        )
    )


def current_demand_value(state: Any, circuit_id: str) -> float:
    """Return the current rolling demand average in watts."""
    return float(
        getattr(state, "current_demand_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def peak_demand_value(state: Any, circuit_id: str) -> float:
    """Return the highest rolling demand observed today."""
    return float(getattr(state, "peak_demand_w_by_circuit", {}).get(circuit_id, 0.0))


def demand_limit_usage_value(state: Any, circuit_id: str) -> float:
    """Return current demand as a percent of the configured demand limit."""
    return float(
        getattr(state, "demand_limit_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def demand_status_value(state: Any, circuit_id: str) -> str:
    """Return the rolling demand tracker status."""
    evidence = getattr(state, "demand_evidence_by_circuit", {}).get(circuit_id, {})
    if isinstance(evidence, Mapping):
        return str(evidence.get("status") or "unconfigured")
    return "unconfigured"


def capacity_usage_value(state: Any, circuit_id: str) -> float:
    """Return current circuit load as a percent of configured capacity."""
    return float(getattr(state, "capacity_usage_by_circuit", {}).get(circuit_id, 0.0))


def capacity_status_value(state: Any, circuit_id: str) -> str:
    """Return the circuit capacity tracker status."""
    return str(
        getattr(state, "capacity_status_by_circuit", {}).get(
            circuit_id,
            "unconfigured",
        )
    )


def leg_imbalance_value(state: Any, circuit_id: str) -> float:
    """Return split-phase leg imbalance as a percentage."""
    return float(
        getattr(state, "leg_imbalance_percent_by_circuit", {}).get(circuit_id, 0.0)
    )


def leg_imbalance_status_value(state: Any, circuit_id: str) -> str:
    """Return the split-phase leg imbalance tracker status."""
    return str(
        getattr(state, "leg_imbalance_status_by_circuit", {}).get(
            circuit_id,
            "not_dual_phase",
        )
    )


def metric_consistency_score_value(state: Any, circuit_id: str) -> float:
    """Return the largest W/VA/PF consistency mismatch percentage."""
    return float(
        getattr(state, "metric_consistency_score_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def metric_consistency_status_value(state: Any, circuit_id: str) -> str:
    """Return the W/VA/PF metric consistency status."""
    return str(
        getattr(state, "metric_consistency_status_by_circuit", {}).get(
            circuit_id,
            "missing_metrics",
        )
    )


def balance_power_value(state: Any, circuit_id: str) -> float:
    """Return unmonitored mains balance power in watts."""
    return float(
        getattr(state, "balance_power_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def monitored_power_value(state: Any, circuit_id: str) -> float:
    """Return summed monitored circuit power for a mains balance."""
    return float(
        getattr(state, "monitored_power_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def monitored_coverage_value(state: Any, circuit_id: str) -> float:
    """Return percent of mains power covered by monitored circuits."""
    return float(
        getattr(state, "monitored_coverage_percent_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def balance_status_value(state: Any, circuit_id: str) -> str:
    """Return the mains balance tracker status."""
    status = getattr(state, "balance_status_by_circuit", {}).get(circuit_id)
    return str(status or "missing_mains")


def utility_comparison_difference_value(state: Any, circuit_id: str) -> float:
    """Return measured-vs-utility kWh difference as a percentage."""
    return float(
        getattr(state, "utility_comparison_difference_percent_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def utility_comparison_status_value(state: Any, circuit_id: str) -> str:
    """Return the utility comparison tracker status."""
    return str(
        getattr(state, "utility_comparison_status_by_circuit", {}).get(
            circuit_id,
            "unconfigured",
        )
    )


def billing_cycle_usage_value(state: Any, circuit_id: str) -> float:
    """Return current billing-cycle usage in kWh."""
    return float(
        getattr(state, "billing_cycle_usage_kwh_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def billing_cycle_forecast_value(state: Any, circuit_id: str) -> float:
    """Return projected end-of-cycle usage in kWh."""
    return float(
        getattr(state, "billing_cycle_forecast_kwh_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def billing_cycle_budget_usage_value(state: Any, circuit_id: str) -> float:
    """Return current billing-cycle usage as a percent of the configured budget."""
    return float(
        getattr(state, "billing_cycle_budget_usage_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def billing_cycle_status_value(state: Any, circuit_id: str) -> str:
    """Return the billing-cycle tracker status."""
    return str(
        getattr(state, "billing_cycle_status_by_circuit", {}).get(
            circuit_id,
            "no_budget",
        )
    )


def cost_current_rate_value(state: Any, circuit_id: str) -> float:
    """Return the active cost rate for a circuit."""
    return float(
        getattr(state, "cost_current_rate_by_circuit", {}).get(circuit_id, 0.0)
    )


def cost_cycle_value(state: Any, circuit_id: str) -> float:
    """Return current billing-cycle cost estimate."""
    return float(getattr(state, "cost_cycle_by_circuit", {}).get(circuit_id, 0.0))


def cost_cycle_forecast_value(state: Any, circuit_id: str) -> float:
    """Return projected end-of-cycle cost estimate."""
    return float(
        getattr(state, "cost_cycle_forecast_by_circuit", {}).get(circuit_id, 0.0)
    )


def cost_status_value(state: Any, circuit_id: str) -> str:
    """Return the cost tracker status."""
    return str(
        getattr(state, "cost_status_by_circuit", {}).get(
            circuit_id,
            "unconfigured",
        )
    )


def always_on_power_value(state: Any, circuit_id: str) -> float:
    """Return estimated Always On power for a circuit."""
    return float(
        getattr(state, "always_on_power_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def standby_threshold_value(state: Any, circuit_id: str) -> float:
    """Return the configured standby threshold in watts."""
    return float(
        getattr(state, "standby_threshold_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def standby_status_value(state: Any, circuit_id: str) -> str:
    """Return the current standby tracker status."""
    return str(
        getattr(state, "standby_status_by_circuit", {}).get(circuit_id, "learning")
    )


def always_on_limit_usage_value(state: Any, circuit_id: str) -> float:
    """Return estimated Always On power as a percent of the configured limit."""
    return float(
        getattr(state, "always_on_limit_usage_by_circuit", {}).get(circuit_id, 0.0)
    )


def _numeric_count(value: Any) -> float:
    if isinstance(value, int | float):
        return max(float(value), 0.0)
    return 0.0


def _mapping_attributes(field_name: str) -> Callable[[Any, str], dict[str, Any] | None]:
    def attributes(state: Any, circuit_id: str) -> dict[str, Any] | None:
        value = getattr(state, field_name, {}).get(circuit_id)
        if isinstance(value, Mapping):
            return dict(value)
        return None

    return attributes


def _sensitivity_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    return {"preset": sensitivity_value(state, circuit_id)}


@dataclass(frozen=True, slots=True)
class DiagnosticSensorDescription:
    """Description for one diagnostic sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str], Any]
    native_unit_of_measurement: str | None = None
    state_class: str | None = None
    attributes_fn: Callable[[Any, str], dict[str, Any] | None] | None = None


SENSOR_DESCRIPTIONS: tuple[DiagnosticSensorDescription, ...] = (
    DiagnosticSensorDescription(
        key="anomaly_score",
        name_suffix="Anomaly Score",
        value_fn=anomaly_score_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="last_event",
        name_suffix="Last Event",
        value_fn=last_event_value,
    ),
    DiagnosticSensorDescription(
        key="health_summary",
        name_suffix="Health Summary",
        value_fn=health_summary_value,
    ),
    DiagnosticSensorDescription(
        key="readiness",
        name_suffix="Readiness",
        value_fn=readiness_value,
        attributes_fn=_mapping_attributes("readiness_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="learning_progress",
        name_suffix="Learning Progress",
        value_fn=learning_progress_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("learning_progress_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="data_quality_checklist",
        name_suffix="Data Quality Checklist",
        value_fn=data_quality_checklist_value,
        attributes_fn=_mapping_attributes("data_quality_checklist_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="energy_dashboard_status",
        name_suffix="Energy Dashboard Status",
        value_fn=energy_dashboard_status_value,
        attributes_fn=_mapping_attributes("energy_dashboard_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="alert_evidence",
        name_suffix="Alert Evidence",
        value_fn=alert_evidence_value,
        attributes_fn=_mapping_attributes("alert_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="sensitivity",
        name_suffix="Sensitivity",
        value_fn=sensitivity_value,
        attributes_fn=_sensitivity_attributes,
    ),
    DiagnosticSensorDescription(
        key="power_quality_score",
        name_suffix="Power Quality Score",
        value_fn=power_quality_score_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="power_quality_evidence",
        name_suffix="Power Quality Evidence",
        value_fn=power_quality_evidence_value,
    ),
    DiagnosticSensorDescription(
        key="reactive_power_drift",
        name_suffix="Reactive Power Drift",
        value_fn=reactive_power_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="apparent_power_drift",
        name_suffix="Apparent Power Drift",
        value_fn=apparent_power_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="power_factor_drift",
        name_suffix="Power Factor Drift",
        value_fn=power_factor_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="nilm_signature_count",
        name_suffix="NILM Discovered Signatures",
        value_fn=nilm_signature_count_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="nilm_unmatched_load_percentage",
        name_suffix="NILM Unmatched Load Percentage",
        value_fn=nilm_unmatched_load_percentage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="daily_energy_usage",
        name_suffix="Daily Energy Usage",
        value_fn=daily_energy_usage_value,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("energy_usage_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="energy_usage_share",
        name_suffix="Energy Usage Share",
        value_fn=energy_usage_share_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("energy_usage_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="energy_usage_status",
        name_suffix="Energy Usage Status",
        value_fn=energy_usage_status_value,
        attributes_fn=_mapping_attributes("energy_usage_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="energy_goal_usage",
        name_suffix="Energy Goal Usage",
        value_fn=energy_goal_usage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("energy_goal_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="energy_goal_status",
        name_suffix="Energy Goal Status",
        value_fn=energy_goal_status_value,
        attributes_fn=_mapping_attributes("energy_goal_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="run_cycle_count",
        name_suffix="Run Cycle Count",
        value_fn=run_cycle_count_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("run_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="run_cycle_runtime",
        name_suffix="Run Cycle Runtime",
        value_fn=run_cycle_runtime_value,
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("run_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="run_cycle_duty_cycle",
        name_suffix="Run Cycle Duty Cycle",
        value_fn=run_cycle_duty_cycle_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("run_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="run_cycle_status",
        name_suffix="Run Cycle Status",
        value_fn=run_cycle_status_value,
        attributes_fn=_mapping_attributes("run_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="current_demand",
        name_suffix="Current Demand",
        value_fn=current_demand_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("demand_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="peak_demand",
        name_suffix="Peak Demand",
        value_fn=peak_demand_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("demand_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="demand_limit_usage",
        name_suffix="Demand Limit Usage",
        value_fn=demand_limit_usage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("demand_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="demand_status",
        name_suffix="Demand Status",
        value_fn=demand_status_value,
        attributes_fn=_mapping_attributes("demand_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="capacity_usage",
        name_suffix="Circuit Capacity Usage",
        value_fn=capacity_usage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("capacity_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="capacity_status",
        name_suffix="Circuit Capacity Status",
        value_fn=capacity_status_value,
        attributes_fn=_mapping_attributes("capacity_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="leg_imbalance",
        name_suffix="Leg Imbalance",
        value_fn=leg_imbalance_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("leg_imbalance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="leg_imbalance_status",
        name_suffix="Leg Imbalance Status",
        value_fn=leg_imbalance_status_value,
        attributes_fn=_mapping_attributes("leg_imbalance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="metric_consistency_score",
        name_suffix="Metric Consistency Score",
        value_fn=metric_consistency_score_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("metric_consistency_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="metric_consistency_status",
        name_suffix="Metric Consistency Status",
        value_fn=metric_consistency_status_value,
        attributes_fn=_mapping_attributes("metric_consistency_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="balance_power",
        name_suffix="Balance Power",
        value_fn=balance_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("balance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="monitored_power",
        name_suffix="Monitored Power",
        value_fn=monitored_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("balance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="monitored_coverage",
        name_suffix="Monitored Coverage",
        value_fn=monitored_coverage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("balance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="balance_status",
        name_suffix="Balance Status",
        value_fn=balance_status_value,
        attributes_fn=_mapping_attributes("balance_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="utility_comparison_difference",
        name_suffix="Utility Comparison Difference",
        value_fn=utility_comparison_difference_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("utility_comparison_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="utility_comparison_status",
        name_suffix="Utility Comparison Status",
        value_fn=utility_comparison_status_value,
        attributes_fn=_mapping_attributes("utility_comparison_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="billing_cycle_usage",
        name_suffix="Billing Cycle Usage",
        value_fn=billing_cycle_usage_value,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("billing_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="billing_cycle_forecast",
        name_suffix="Billing Cycle Forecast",
        value_fn=billing_cycle_forecast_value,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("billing_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="billing_cycle_budget_usage",
        name_suffix="Billing Cycle Budget Usage",
        value_fn=billing_cycle_budget_usage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("billing_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="billing_cycle_status",
        name_suffix="Billing Cycle Status",
        value_fn=billing_cycle_status_value,
        attributes_fn=_mapping_attributes("billing_cycle_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="cost_current_rate",
        name_suffix="Cost Current Rate",
        value_fn=cost_current_rate_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("cost_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="cost_cycle",
        name_suffix="Cost Cycle",
        value_fn=cost_cycle_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("cost_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="cost_cycle_forecast",
        name_suffix="Cost Cycle Forecast",
        value_fn=cost_cycle_forecast_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("cost_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="cost_status",
        name_suffix="Cost Status",
        value_fn=cost_status_value,
        attributes_fn=_mapping_attributes("cost_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="always_on_power",
        name_suffix="Always On Power",
        value_fn=always_on_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("standby_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="standby_threshold",
        name_suffix="Standby Threshold",
        value_fn=standby_threshold_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("standby_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="standby_status",
        name_suffix="Standby Status",
        value_fn=standby_status_value,
        attributes_fn=_mapping_attributes("standby_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="always_on_limit_usage",
        name_suffix="Always On Limit Usage",
        value_fn=always_on_limit_usage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("standby_evidence_by_circuit"),
    ),
)


class CircuitAnalyzerSensor(CircuitAnalyzerEntity, SensorEntity):
    """Sensor exposing one diagnostic value for an analyzed circuit."""

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: DiagnosticSensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class

    @property
    def native_value(self) -> Any:
        """Return the latest diagnostic value."""
        if self.coordinator_state is None:
            return self.entity_description.value_fn(None, self.circuit_id)
        return self.entity_description.value_fn(
            self.coordinator_state,
            self.circuit_id,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional diagnostics for sensors that expose detail."""
        attributes_fn = self.entity_description.attributes_fn
        if attributes_fn is None:
            return None
        return attributes_fn(self.coordinator_state, self.circuit_id)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up diagnostic sensor entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[CircuitAnalyzerSensor] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        entities.extend(
            CircuitAnalyzerSensor(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in SENSOR_DESCRIPTIONS
        )

    async_add_entities(entities)
