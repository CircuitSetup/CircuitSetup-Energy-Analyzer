from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any

from .appliance_metadata import appliance_icon_for_profile
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
)
from .demo import (
    DEMO_SOURCE_ROLE_METADATA as _DEMO_SOURCE_ROLE_METADATA,
)
from .demo import (
    demo_circuit_id_from_entity_id as _demo_circuit_id_from_entity_id,
)
from .demo import (
    demo_source_value as _demo_source_value,
)
from .demo import (
    is_demo_source_entity_id as _is_demo_source_entity_id,
)
from .entities.energy import (
    daily_energy_usage_value,
    energy_goal_status_value,
    energy_goal_usage_value,
    energy_usage_share_value,
    energy_usage_status_value,
)
from .entities.nilm import (
    nilm_signature_count_value,
    nilm_topology_status_value,
    nilm_unknown_loads_attributes,
    nilm_unknown_loads_value,
    nilm_unmatched_load_percentage_value,
)
from .entities.settings_suggestions import (
    settings_suggestions_attributes,
    settings_suggestions_value,
)
from .entities.setup_health import (
    setup_health_attributes as _entity_setup_health_attributes,
)
from .entities.setup_health import (
    setup_health_value as _entity_setup_health_value,
)
from .entity import (
    CircuitAnalyzerEntity,
    CoordinatorEntity,
    EntityCategory,
    EntityTier,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    enable_summary_registry_entries,
    entity_detail_level_for_coordinator,
    entity_enabled_default_for_tier,
    hide_entity_registry_entries,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
    sync_entity_registry_categories,
    sync_entity_registry_visibility,
)
from .models import ApplianceProfile, CircuitMode, PowerFlowMode, SensorRef, SensorRole
from .safety import with_electrical_safety_notice
from .ux import friendly_feature_name, friendly_sensitivity_label

try:
    from homeassistant.components.sensor import SensorEntity, SensorStateClass
    from homeassistant.const import (
        PERCENTAGE,
        UnitOfEnergy,
        UnitOfPower,
        UnitOfTemperature,
    )
except ModuleNotFoundError:
    PERCENTAGE = "%"

    class UnitOfEnergy:
        """Fallback energy unit constants."""

        KILO_WATT_HOUR = "kWh"

    class UnitOfPower:
        """Fallback power unit constants."""

        WATT = "W"

    class UnitOfTemperature:
        """Fallback temperature unit constants."""

        FAHRENHEIT = "°F"
        CELSIUS = "°C"

    class SensorEntity:
        """Fallback sensor base for tests without Home Assistant."""

        @property
        def state(self) -> Any:
            return getattr(self, "native_value", None)

    class SensorStateClass:
        """Fallback sensor state class constants."""

        MEASUREMENT = "measurement"


SETUP_HEALTH_ENTITY_NAME = "CircuitSetup Energy Analyzer Setup Health"
SETUP_HEALTH_ENTITY_KEY = "setup_health"
SETUP_HEALTH_SUGGESTED_OBJECT_ID = "circuitsetup_energy_analyzer_setup_health"
SETUP_HEALTH_OPEN_PATH = "/config/integrations/integration/circuitsetup_energy_analyzer"


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


def health_summary_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return health detail that would otherwise require noisy status entities."""
    summary = health_summary_value(state, circuit_id)
    readiness = readiness_value(state, circuit_id)
    data_quality_problem = data_quality_checklist_value(state, circuit_id) == "problem"
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    maintenance_active = (
        isinstance(maintenance, Mapping) and maintenance.get("active") is True
    )
    active_alert_count = _active_alert_count(state, circuit_id)
    return {
        "raw_status": _health_summary_raw_status(summary, readiness),
        "status_label": summary,
        "status_explanation": _health_summary_explanation(summary, readiness),
        "learning_progress": learning_progress_value(state, circuit_id),
        "readiness": readiness,
        "data_quality_problem": data_quality_problem,
        "maintenance_active": maintenance_active,
        "active_alert_count": active_alert_count,
        "next_step": _health_summary_next_step(
            readiness,
            data_quality_problem=data_quality_problem,
            maintenance_active=maintenance_active,
            active_alert_count=active_alert_count,
        ),
    }


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
        if evidence.get("feature_name"):
            return str(evidence["feature_name"])
        if evidence.get("feature"):
            return friendly_feature_name(evidence.get("feature"))
        return ""

    alerts = getattr(state, "active_alerts_by_circuit", {}).get(circuit_id, [])
    if alerts:
        feature = getattr(alerts[-1], "feature", "")
        return friendly_feature_name(feature) if feature else ""
    return ""


def recent_activity_value(state: Any, circuit_id: str) -> str:
    """Return the latest recent activity title for a circuit."""
    return str(
        getattr(state, "recent_activity_by_circuit", {}).get(
            circuit_id,
            "No recent activity",
        )
    )


def recent_activity_count_value(state: Any, circuit_id: str) -> int:
    """Return the number of retained activity items in the recent window."""
    return int(
        getattr(state, "recent_activity_count_by_circuit", {}).get(circuit_id, 0)
    )


def sensitivity_value(state: Any, circuit_id: str) -> str:
    """Return the active sensitivity preset for a circuit."""
    return friendly_sensitivity_label(
        getattr(state, "sensitivity_by_circuit", {}).get(circuit_id, "balanced")
    )


def circuit_mode_value(state: Any, circuit_id: str) -> str:
    """Return the configured circuit mode label for a circuit."""
    return str(
        getattr(state, "circuit_mode_by_circuit", {}).get(circuit_id, "Unknown")
    )


def power_flow_value(state: Any, circuit_id: str) -> str:
    """Return the configured power-flow label for a circuit."""
    return str(
        getattr(state, "power_flow_by_circuit", {}).get(circuit_id, "Unknown")
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


_WEATHER_CONTEXT_STATUS_LABELS = {
    "no_temperature_source": "No Temperature Source",
    "learning": "Learning",
    "weather_correlated": "Weather Correlated",
    "above_weather_adjusted_range": "Above Weather-Adjusted Range",
}
_WATER_CONTEXT_STATUS_LABELS = {
    "unconfigured": "Unconfigured",
    "learning": "Learning",
    "normal": "Normal",
    "rain_explained": "Rain Explained",
    "compressor_explained": "Compressor Explained",
    "weather_explained": "Weather Explained",
    "possible_excess_pump_activity": "Possible Excess Pump Activity",
    "possible_missing_pump_activity": "Possible Missing Pump Activity",
    "possible_flow_without_load": "Possible Flow Without Load",
    "possible_load_without_flow": "Possible Load Without Flow",
    "possible_sensor_problem": "Possible Sensor Problem",
    "sensor_unavailable": "Sensor Unavailable",
}


def weather_context_value(state: Any, circuit_id: str) -> str:
    """Return a friendly weather-context status for an HVAC circuit."""
    evidence = getattr(state, "weather_context_by_circuit", {}).get(circuit_id)
    status = _weather_context_status(evidence)
    return _WEATHER_CONTEXT_STATUS_LABELS.get(status, friendly_feature_name(status))


def weather_context_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return weather-context evidence attributes for an HVAC circuit."""
    evidence = getattr(state, "weather_context_by_circuit", {}).get(circuit_id)
    if isinstance(evidence, Mapping):
        return dict(evidence)
    if is_dataclass(evidence) and not isinstance(evidence, type):
        return asdict(evidence)
    return {}


def outdoor_temperature_value(state: Any, circuit_id: str) -> float | None:
    """Return the graphable outdoor temperature for an HVAC circuit."""
    evidence = getattr(state, "weather_context_by_circuit", {}).get(circuit_id)
    if not isinstance(evidence, Mapping):
        return None
    value = _numeric_value(evidence.get("current_outdoor_temperature"))
    return None if value is None else round(value, 3)


def outdoor_temperature_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return outdoor temperature conversion evidence."""
    evidence = getattr(state, "weather_context_by_circuit", {}).get(circuit_id)
    if not isinstance(evidence, Mapping):
        return {}
    attributes: dict[str, Any] = {
        "temperature_unit": _outdoor_temperature_unit_from_evidence(evidence),
    }
    temperature_f = _numeric_value(evidence.get("temperature_f"))
    if temperature_f is not None:
        attributes["temperature_f"] = round(temperature_f, 3)
    if evidence.get("temperature_source_entity"):
        attributes["temperature_source_entity"] = str(
            evidence["temperature_source_entity"],
        )
    if evidence.get("temperature_source_unit"):
        attributes["temperature_source_unit"] = str(evidence["temperature_source_unit"])
    return attributes


def rain_pump_correlation_value(state: Any, circuit_id: str) -> str:
    """Return a friendly rain/pump correlation status."""
    evidence = getattr(state, "rain_pump_context_by_circuit", {}).get(circuit_id)
    status = _water_context_status(evidence)
    return _WATER_CONTEXT_STATUS_LABELS.get(status, friendly_feature_name(status))


def rain_pump_correlation_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return rain/pump evidence attributes."""
    evidence = getattr(state, "rain_pump_context_by_circuit", {}).get(circuit_id)
    return dict(evidence) if isinstance(evidence, Mapping) else {}


def water_flow_correlation_value(state: Any, circuit_id: str) -> str:
    """Return a friendly water-flow correlation status."""
    evidence = getattr(state, "water_flow_context_by_circuit", {}).get(circuit_id)
    status = _water_context_status(evidence)
    return _WATER_CONTEXT_STATUS_LABELS.get(status, friendly_feature_name(status))


def water_flow_correlation_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return water-flow evidence attributes."""
    evidence = getattr(state, "water_flow_context_by_circuit", {}).get(circuit_id)
    return dict(evidence) if isinstance(evidence, Mapping) else {}


def water_flow_mismatch_minutes_value(state: Any, circuit_id: str) -> float:
    """Return current flow/appliance mismatch duration in minutes."""
    evidence = getattr(state, "water_flow_context_by_circuit", {}).get(
        circuit_id,
        {},
    )
    if not isinstance(evidence, Mapping):
        return 0.0
    return float(evidence.get("mismatch_minutes", 0.0) or 0.0)


def _outdoor_temperature_unit_from_evidence(evidence: Mapping[str, Any]) -> str:
    unit = str(
        evidence.get("temperature_unit")
        or evidence.get("current_outdoor_temperature_unit")
        or "",
    ).strip()
    lowered = unit.lower()
    if lowered in {"°c", "c", "celsius"}:
        return UnitOfTemperature.CELSIUS
    if lowered in {"°f", "f", "fahrenheit"}:
        return UnitOfTemperature.FAHRENHEIT
    return unit or UnitOfTemperature.FAHRENHEIT


def _weather_context_status(evidence: Any) -> str:
    if isinstance(evidence, Mapping):
        return str(evidence.get("status") or "no_temperature_source")
    status = getattr(evidence, "status", None)
    if status:
        return str(status)
    if isinstance(evidence, str):
        return evidence
    return "no_temperature_source"


def _water_context_status(evidence: Any) -> str:
    if isinstance(evidence, Mapping):
        return str(evidence.get("status") or "unconfigured")
    status = getattr(evidence, "status", None)
    if status:
        return str(status)
    if isinstance(evidence, str):
        return evidence
    return "unconfigured"


def _numeric_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def demand_peak_rank_value(state: Any, circuit_id: str) -> int:
    """Return the current rolling demand rank for this month's peak windows."""
    return int(getattr(state, "demand_peak_rank_by_circuit", {}).get(circuit_id, 0))


def demand_peak_status_value(state: Any, circuit_id: str) -> str:
    """Return whether current demand is near this month's top windows."""
    return str(
        getattr(state, "demand_peak_status_by_circuit", {}).get(
            circuit_id,
            "unavailable",
        )
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


def solar_generation_power_value(state: Any, circuit_id: str) -> float:
    """Return instantaneous solar generation in watts."""
    return float(
        getattr(state, "solar_generation_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_site_consumption_power_value(state: Any, circuit_id: str) -> float:
    """Return instantaneous site consumption from solar plus signed grid power."""
    return float(
        getattr(state, "solar_site_consumption_w_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def solar_grid_import_power_value(state: Any, circuit_id: str) -> float:
    """Return instantaneous grid import power in watts."""
    return float(
        getattr(state, "solar_grid_import_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_grid_export_power_value(state: Any, circuit_id: str) -> float:
    """Return instantaneous grid export power in watts."""
    return float(
        getattr(state, "solar_grid_export_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_self_consumption_value(state: Any, circuit_id: str) -> float:
    """Return percent of generated solar consumed on site."""
    return float(
        getattr(state, "solar_self_consumption_percent_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def solar_powered_value(state: Any, circuit_id: str) -> float:
    """Return percent of current site load powered by solar."""
    return float(
        getattr(state, "solar_powered_percent_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_flow_status_value(state: Any, circuit_id: str) -> str:
    """Return the instantaneous solar-flow diagnostic status."""
    return str(
        getattr(state, "solar_flow_status_by_circuit", {}).get(
            circuit_id,
            "missing_mains",
        )
    )


def solar_surplus_power_value(state: Any, circuit_id: str) -> float:
    """Return instantaneous solar export available as surplus power."""
    return float(
        getattr(state, "solar_surplus_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_load_shift_power_value(state: Any, circuit_id: str) -> float:
    """Return surplus power available after the load-shift threshold is met."""
    return float(
        getattr(state, "solar_load_shift_w_by_circuit", {}).get(circuit_id, 0.0)
    )


def solar_flexible_load_power_value(state: Any, circuit_id: str) -> float:
    """Return current power used by configured flexible solar loads."""
    return float(
        getattr(state, "solar_flexible_load_power_w_by_circuit", {}).get(
            circuit_id,
            0.0,
        )
    )


def solar_flexible_load_coverage_value(state: Any, circuit_id: str) -> float:
    """Return percent of active flexible load estimated to be solar-covered."""
    return float(
        getattr(
            state,
            "solar_flexible_load_coverage_percent_by_circuit",
            {},
        ).get(circuit_id, 0.0)
    )


def solar_surplus_status_value(state: Any, circuit_id: str) -> str:
    """Return the solar surplus/load-shift diagnostic status."""
    return str(
        getattr(state, "solar_surplus_status_by_circuit", {}).get(
            circuit_id,
            "missing_mains",
        )
    )


def solar_load_shift_status_value(state: Any, circuit_id: str) -> str:
    """Return whether flexible loads are solar-covered or waiting for surplus."""
    return str(
        getattr(state, "solar_load_shift_status_by_circuit", {}).get(
            circuit_id,
            "not_applicable",
        )
    )


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


def activity_summary_value(state: Any, circuit_id: str) -> str:
    """Return a user-facing summary of what the circuit is doing."""
    run_status = run_cycle_status_value(state, circuit_id)
    standby_status = standby_status_value(state, circuit_id)
    if run_status == "running":
        return "Running"
    if run_status == "idle":
        return "Idle"
    if standby_status in {"on", "standby", "off"}:
        return _status_label(standby_status)
    return "No Activity"


def activity_summary_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return activity detail that would otherwise require several entities."""
    run_status = run_cycle_status_value(state, circuit_id)
    standby_status = standby_status_value(state, circuit_id)
    return {
        "run_cycle_status": run_status,
        "standby_status": standby_status,
        "run_cycle_count": run_cycle_count_value(state, circuit_id),
        "run_cycle_runtime_seconds": run_cycle_runtime_value(state, circuit_id),
        "duty_cycle_percent": run_cycle_duty_cycle_value(state, circuit_id),
        "summary_explanation": _activity_summary_explanation(
            run_status,
            standby_status,
        ),
    }


def electrical_health_value(state: Any, circuit_id: str) -> str:
    """Return a user-facing electrical-health rollup."""
    return _electrical_health_summary(state, circuit_id)[0]


def electrical_health_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return electrical-health detail from metric, phase, and PQ checks."""
    summary, explanation = _electrical_health_summary(state, circuit_id)
    metric_status = metric_consistency_status_value(state, circuit_id)
    leg_status = leg_imbalance_status_value(state, circuit_id)
    return {
        "summary": summary,
        "metric_consistency_status": metric_status,
        "metric_consistency_score": metric_consistency_score_value(state, circuit_id),
        "leg_imbalance_status": leg_status,
        "leg_imbalance_percent": leg_imbalance_value(state, circuit_id),
        "power_quality_score": power_quality_score_value(state, circuit_id),
        "power_quality_evidence": power_quality_evidence_value(state, circuit_id),
        "status_explanation": explanation,
        "metric_status_explanation": _status_explanation(metric_status),
        "leg_status_explanation": _status_explanation(leg_status),
        "what_to_check_first": _electrical_health_first_check(
            summary,
            metric_status,
            leg_status,
            power_quality_evidence_value(state, circuit_id),
        ),
    }


def energy_summary_value(state: Any, circuit_id: str) -> str:
    """Return a user-facing energy-use rollup."""
    return _energy_summary(state, circuit_id)[0]


def energy_summary_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    """Return energy, billing, goal, and cost detail in one place."""
    summary, explanation = _energy_summary(state, circuit_id)
    has_energy_evidence = _has_energy_usage_evidence(state, circuit_id)
    energy_usage_status = (
        energy_usage_status_value(state, circuit_id)
        if has_energy_evidence
        else "missing_energy_data"
    )
    goal_status = energy_goal_status_value(state, circuit_id)
    billing_status = billing_cycle_status_value(state, circuit_id)
    cost_status = cost_status_value(state, circuit_id)
    return {
        "summary": summary,
        "energy_data_available": has_energy_evidence,
        "energy_usage_status": energy_usage_status,
        "energy_goal_status": goal_status,
        "billing_cycle_status": billing_status,
        "cost_status": cost_status,
        "daily_energy_usage_kwh": daily_energy_usage_value(state, circuit_id),
        "energy_usage_share_percent": energy_usage_share_value(state, circuit_id),
        "billing_cycle_usage_kwh": billing_cycle_usage_value(state, circuit_id),
        "billing_cycle_forecast_kwh": billing_cycle_forecast_value(state, circuit_id),
        "cost_cycle": cost_cycle_value(state, circuit_id),
        "cost_cycle_forecast": cost_cycle_forecast_value(state, circuit_id),
        "summary_explanation": explanation,
        "energy_usage_explanation": _status_explanation(energy_usage_status),
        "billing_cycle_explanation": _status_explanation(billing_status),
    }


def _health_summary_raw_status(summary: str, readiness: str) -> str:
    if readiness and readiness != "ready":
        return readiness
    normalized = summary.strip().lower().replace(" ", "_")
    return normalized or "ready"


def _health_summary_explanation(summary: str, readiness: str) -> str:
    if summary == "Possible issue":
        return "One or more analyzer alerts are active for this circuit."
    if summary == "Needs data":
        return "The analyzer needs valid source sensor data before checks are reliable."
    if summary == "Learning":
        return "The analyzer is still building a baseline for this circuit."
    if summary == "Paused":
        return "Alerts are currently paused for this circuit."
    if readiness != "ready":
        return _status_explanation(readiness)
    return "No setup or health issue is currently active for this circuit."


def _health_summary_next_step(
    readiness: str,
    *,
    data_quality_problem: bool,
    maintenance_active: bool,
    active_alert_count: int,
) -> str:
    if data_quality_problem:
        return "Review source sensor data"
    if readiness == "learning":
        return "Let analyzer learn"
    if maintenance_active:
        return "End maintenance when work is complete"
    if active_alert_count:
        return "Review alert evidence"
    return "No action needed"


def _electrical_health_first_check(
    summary: str,
    metric_status: str,
    leg_status: str,
    power_quality_evidence: str,
) -> str:
    if leg_status == "imbalanced":
        return "Compare both legs of the dual-phase circuit and verify CT pairing."
    if metric_status in {
        "apparent_power_mismatch",
        "power_factor_mismatch",
        "metric_mismatch",
    }:
        return "Verify watts, amps, voltage, apparent power, and power factor sources."
    if power_quality_evidence:
        return (
            "Compare recent VAR, VA, watts, and power factor to the learned "
            "baseline."
        )
    if summary == "Needs Metrics":
        return (
            "Add matching electrical metrics such as watts, amps, voltage, VA, "
            "or PF."
        )
    return "No electrical check is needed right now."


def _active_alert_count(state: Any, circuit_id: str) -> int:
    alerts = getattr(state, "active_alerts_by_circuit", {}).get(circuit_id, ())
    if isinstance(alerts, int | float):
        return max(int(alerts), 0)
    if isinstance(alerts, Mapping):
        return len(alerts)
    try:
        return len(tuple(alerts))
    except TypeError:
        return 0


def _activity_summary_explanation(run_status: str, standby_status: str) -> str:
    if run_status == "running":
        return "The appliance is currently active."
    if run_status == "idle":
        return "The appliance has run-cycle data and is currently idle."
    if standby_status == "standby":
        return "The circuit is in the learned standby range."
    if standby_status == "on":
        return "The circuit is above the standby range."
    if standby_status == "off":
        return "The circuit is below the standby threshold."
    return "No recent activity has been observed."


def _electrical_health_summary(state: Any, circuit_id: str) -> tuple[str, str]:
    metric_status = metric_consistency_status_value(state, circuit_id)
    leg_status = leg_imbalance_status_value(state, circuit_id)
    power_quality_evidence = power_quality_evidence_value(state, circuit_id)

    if leg_status == "imbalanced":
        return (
            "Possible Imbalance",
            "A dual-phase load has a meaningful leg-to-leg imbalance.",
        )
    if metric_status in {
        "apparent_power_mismatch",
        "power_factor_mismatch",
        "metric_mismatch",
    }:
        return (
            "Possible Metric Mismatch",
            "Reported electrical measurements do not agree with each other.",
        )
    if power_quality_evidence:
        return (
            "Possible Power Quality Change",
            "Power-quality evidence has changed from the learned baseline.",
        )
    if metric_status == "missing_metrics":
        return (
            "Needs Metrics",
            "Electrical-health checks need matching watts, amps, voltage, VA, or PF.",
        )
    return "Normal", "No electrical-health issue is currently active."


def _energy_summary(state: Any, circuit_id: str) -> tuple[str, str]:
    if not _has_energy_usage_evidence(state, circuit_id):
        return (
            "Needs Energy Data",
            "No cumulative kWh evidence is available for this circuit.",
        )

    energy_usage_status = energy_usage_status_value(state, circuit_id)
    goal_status = energy_goal_status_value(state, circuit_id)
    billing_status = billing_cycle_status_value(state, circuit_id)
    cost_status = cost_status_value(state, circuit_id)

    if (
        energy_usage_status == "over_threshold"
        or goal_status == "over_goal"
        or billing_status in {"over_budget", "projected_over_budget"}
    ):
        return (
            "High Usage",
            "Energy use is above a configured threshold or budget.",
        )
    if goal_status == "near_goal" or cost_status == "tou_peak":
        return "Watch", "Energy or cost is near a configured warning threshold."
    if energy_usage_status == "waiting_for_delta":
        return (
            "Needs Energy Data",
            "A cumulative kWh source is present but has not increased yet.",
        )
    if energy_usage_status == "learning":
        return "Learning", "The analyzer is still learning normal energy use."
    return "Normal", "Energy use is within configured thresholds."


def _has_energy_usage_evidence(state: Any, circuit_id: str) -> bool:
    evidence = getattr(state, "energy_usage_evidence_by_circuit", {}).get(circuit_id)
    if isinstance(evidence, Mapping) and evidence:
        return True
    return circuit_id in getattr(state, "daily_energy_usage_by_circuit", {})


def _numeric_count(value: Any) -> float:
    if isinstance(value, int | float):
        return max(float(value), 0.0)
    return 0.0


RECENT_ACTIVITY_ATTRIBUTE_MAX_ITEMS = 5
RECENT_ACTIVITY_DETAIL_MAX_LENGTH = 65
RECENT_ACTIVITY_ATTRIBUTE_FIELDS = (
    "timestamp",
    "title",
    "detail",
    "kind",
    "severity",
    "feature",
    "feature_name",
    "event_type",
    "observed_value",
    "baseline_value",
    "change_ratio",
    "repeated_count",
)

LEARNING_PROGRESS_PENDING_SAMPLE_MAX_ITEMS = 5

SOLAR_LOAD_SHIFT_CANDIDATE_MAX_ITEMS = 5
SOLAR_LOAD_SHIFT_CANDIDATE_FIELDS = (
    "circuit_id",
    "name",
    "appliance_profile",
    "current_power_w",
    "state",
)


def _recent_activity_attributes(value: Mapping[str, Any]) -> dict[str, Any]:
    attributes = {key: item for key, item in value.items() if key != "items"}
    raw_items = value.get("items", ())
    if not isinstance(raw_items, Iterable) or isinstance(
        raw_items, str | bytes | Mapping
    ):
        item_list: list[Any] = []
    else:
        item_list = list(raw_items)

    preview_items = item_list[:RECENT_ACTIVITY_ATTRIBUTE_MAX_ITEMS]
    attributes["shown_count"] = len(preview_items)
    attributes["has_more"] = len(item_list) > len(preview_items)
    attributes["items"] = [
        _recent_activity_item_preview(item) for item in preview_items
    ]
    return attributes


def _recent_activity_item_preview(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    return {
        field: _recent_activity_attribute_value(field, item[field])
        for field in RECENT_ACTIVITY_ATTRIBUTE_FIELDS
        if field in item and item[field] is not None
    }


def _recent_activity_attribute_value(field: str, value: Any) -> Any:
    if field == "detail" and isinstance(value, str):
        return _bounded_attribute_string(value, RECENT_ACTIVITY_DETAIL_MAX_LENGTH)
    return value


def _learning_progress_attributes(value: Mapping[str, Any]) -> dict[str, Any]:
    attributes = {
        key: item for key, item in value.items() if key != "pending_feature_samples"
    }
    pending_samples = value.get("pending_feature_samples", {})
    if isinstance(pending_samples, Mapping):
        pending_items = list(pending_samples.items())
    else:
        pending_items = []

    preview_items = pending_items[:LEARNING_PROGRESS_PENDING_SAMPLE_MAX_ITEMS]
    attributes["pending_feature_sample_count"] = len(pending_items)
    attributes["pending_feature_samples_shown_count"] = len(preview_items)
    attributes["pending_feature_samples_has_more"] = len(pending_items) > len(
        preview_items
    )
    attributes["pending_feature_samples"] = dict(preview_items)
    return attributes


def _bounded_attribute_string(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    suffix = "..."
    if max_length <= len(suffix):
        return suffix[:max_length]
    return value[: max_length - len(suffix)] + suffix


def _solar_load_shift_attributes(value: Mapping[str, Any]) -> dict[str, Any]:
    attributes = {
        key: item for key, item in value.items() if key != "candidate_loads"
    }
    raw_loads = value.get("candidate_loads", ())
    if not isinstance(raw_loads, Iterable) or isinstance(
        raw_loads, str | bytes | Mapping
    ):
        candidate_loads: list[Any] = []
    else:
        candidate_loads = list(raw_loads)

    preview_loads = candidate_loads[:SOLAR_LOAD_SHIFT_CANDIDATE_MAX_ITEMS]
    attributes["candidate_load_count"] = len(candidate_loads)
    attributes["candidate_loads_shown_count"] = len(preview_loads)
    attributes["candidate_loads_has_more"] = len(candidate_loads) > len(
        preview_loads
    )
    attributes["candidate_loads"] = [
        _solar_load_shift_candidate_preview(load) for load in preview_loads
    ]
    return attributes


def _solar_load_shift_candidate_preview(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return {}
    return {
        field: candidate[field]
        for field in SOLAR_LOAD_SHIFT_CANDIDATE_FIELDS
        if field in candidate and candidate[field] is not None
    }


def _mapping_attributes(field_name: str) -> Callable[[Any, str], dict[str, Any] | None]:
    def attributes(state: Any, circuit_id: str) -> dict[str, Any] | None:
        value = getattr(state, field_name, {}).get(circuit_id)
        if isinstance(value, Mapping):
            attributes = dict(value)
            if field_name == "data_quality_checklist_by_circuit":
                attributes.pop("quality_issues_full", None)
            if field_name == "learning_progress_by_circuit":
                return _learning_progress_attributes(attributes)
            if field_name == "recent_activity_timeline_by_circuit":
                return _recent_activity_attributes(attributes)
            if field_name == "solar_load_shift_evidence_by_circuit":
                return _solar_load_shift_attributes(attributes)
            if field_name in {
                "demand_evidence_by_circuit",
                "capacity_evidence_by_circuit",
            }:
                return with_electrical_safety_notice(attributes)
            return attributes
        return None

    return attributes


def _sensitivity_attributes(state: Any, circuit_id: str) -> dict[str, Any]:
    return {"preset": sensitivity_value(state, circuit_id)}


_STATUS_LABEL_OVERRIDES: Mapping[str, str] = {
    "nilm_review": "NILM Review",
    "tou_peak": "TOU Peak",
    "waiting_for_delta": "Waiting For Energy Change",
}

_STATUS_EXPLANATIONS: Mapping[str, str] = {
    "active_grid_supported": (
        "A flexible load is running, but the current solar surplus does not cover it."
    ),
    "active_solar_supported": (
        "A flexible load is running and the current solar surplus appears to cover it."
    ),
    "apparent_power_mismatch": (
        "Reported apparent power does not match the relationship expected from "
        "voltage, current, and real power."
    ),
    "consistent": "The available measurements are internally consistent.",
    "exporting": "Signed mains power currently indicates export to the grid.",
    "high_surplus": (
        "Solar export is above the high-surplus threshold configured for load shifting."
    ),
    "idle": "The circuit is below the active-load threshold for this check.",
    "imbalanced": (
        "A dual-phase load has a repeated leg-to-leg difference above the configured "
        "warning threshold."
    ),
    "importing": "Signed mains power currently indicates import from the grid.",
    "inconsistent_export": (
        "Grid export is larger than measured generation; check CT orientation, solar "
        "mapping, batteries, or missing generation channels."
    ),
    "learning": "The analyzer is still collecting baseline evidence.",
    "leg_mismatch": (
        "Mains NILM evidence repeatedly points to a different split-phase leg than "
        "the circuit assignment."
    ),
    "metric_mismatch": (
        "One or more power relationships changed beyond the configured tolerance."
    ),
    "missing_current": (
        "This check needs a current sensor, or power and voltage sensors that can "
        "estimate current."
    ),
    "missing_energy_data": (
        "This summary needs a cumulative kWh sensor or retained energy evidence."
    ),
    "missing_generation": "Solar-flow checks need at least one generation circuit.",
    "missing_mains": "This check needs a mains, whole-home, or aggregate source.",
    "missing_measured": "Utility comparison needs a measured kWh source.",
    "missing_metrics": (
        "This check needs more matching voltage, current, real power, apparent power, "
        "or power factor sensors."
    ),
    "missing_utility": "Utility comparison needs a utility or Opower source.",
    "mismatch": (
        "The measured value differs from the comparison source beyond tolerance."
    ),
    "monthly_peak": (
        "The current rolling demand is the highest retained monthly window."
    ),
    "near_goal": "Daily energy usage is near the configured goal threshold.",
    "near_monthly_peak": (
        "The current rolling demand is near the highest retained monthly windows."
    ),
    "negative_balance": (
        "Monitored load power is higher than mains power beyond tolerance; check "
        "mapping, signs, solar, or CT orientation."
    ),
    "no_activity": "No recent run-cycle activity has been observed.",
    "no_budget": "No billing-cycle budget is configured for this circuit.",
    "no_generation": "No solar generation is currently being measured.",
    "no_match": "No matching NILM event has been observed yet.",
    "no_monitored_circuits": "Mains balance needs at least one monitored load circuit.",
    "no_surplus": "No solar export surplus is currently available.",
    "not_applicable": "This check does not apply to the current circuit configuration.",
    "not_dual_phase": "This check only applies to dual-phase circuits.",
    "off": "The latest power sample is below the configured standby threshold.",
    "on": "The latest power sample is above the standby range.",
    "over_budget": "Billing-cycle usage is over the configured budget.",
    "over_goal": "Daily energy usage is over the configured goal.",
    "over_limit": "The measured value is over the configured limit.",
    "over_threshold": "The measured value is over the configured threshold.",
    "paused": "Analysis is paused for this circuit.",
    "possible_issue": "Repeated evidence has crossed an alert threshold.",
    "power_factor_mismatch": (
        "Reported power factor does not match real power divided by apparent power."
    ),
    "power_ready": "Power metadata is ready for Home Assistant energy features.",
    "projected_over_budget": (
        "Current usage projects above the configured billing-cycle budget."
    ),
    "ready": "The analyzer has enough data for this check.",
    "running": "The circuit is currently above the active-load threshold.",
    "self_powered": "Solar generation is approximately covering current site load.",
    "standby": "The latest power sample is within the configured standby range.",
    "surplus_available": (
        "Solar export is above the surplus threshold configured for load shifting."
    ),
    "surplus_candidate": (
        "An idle flexible load could be a candidate while solar surplus is available."
    ),
    "topology_match": "Mains NILM evidence matches the configured circuit mode.",
    "topology_mismatch": (
        "Mains NILM evidence conflicts with the configured circuit mode."
    ),
    "tou_peak": "The current time is inside the configured time-of-use peak period.",
    "tracking": "The analyzer has enough inputs and is tracking this check.",
    "unavailable": "This check does not have enough retained data yet.",
    "unconfigured": "This optional check has not been configured for this circuit.",
    "waiting_for_surplus": "No idle flexible load currently has enough solar surplus.",
    "waiting_for_delta": (
        "A cumulative kWh source is present, but the analyzer has not observed it "
        "increase since tracking started."
    ),
}


def _is_status_sensor_key(key: str) -> bool:
    return key.endswith("_status")


def _status_label(raw_status: Any) -> str:
    status = str(raw_status or "")
    if status in _STATUS_LABEL_OVERRIDES:
        return _STATUS_LABEL_OVERRIDES[status]

    words = status.replace("-", "_").split("_")
    formatted_words = []
    for word in words:
        lower = word.lower()
        if lower in {"ct", "nilm", "pf", "tou", "va"}:
            formatted_words.append(lower.upper())
        elif lower == "kwh":
            formatted_words.append("kWh")
        else:
            formatted_words.append(lower.capitalize())
    return " ".join(formatted_words)


def _status_explanation(raw_status: Any) -> str:
    status = str(raw_status or "")
    return _STATUS_EXPLANATIONS.get(
        status,
        f"{_status_label(status)} status reported by the analyzer.",
    )


def _status_raw_value(
    description: DiagnosticSensorDescription,
    state: Any,
    circuit_id: str,
    attributes: Mapping[str, Any] | None = None,
) -> Any:
    if attributes is not None and attributes.get("status"):
        return attributes["status"]
    return description.value_fn(state, circuit_id)


@dataclass(frozen=True, slots=True)
class DiagnosticSensorDescription:
    """Description for one diagnostic sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str], Any]
    device_class: str | None = None
    entity_category: Any | None = EntityCategory.DIAGNOSTIC
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    entity_tier: EntityTier = EntityTier.DIAGNOSTIC
    entity_picture: str | None = None
    force_update: bool = False
    has_entity_name: bool = False
    icon: str | None = None
    last_reset: Any | None = None
    name: str | None = None
    native_unit_of_measurement: str | None = None
    options: list[str] | None = None
    state_class: str | None = None
    suggested_display_precision: int | None = None
    suggested_unit_of_measurement: str | None = None
    translation_key: str | None = None
    translation_placeholders: Mapping[str, str] | None = None
    unit_of_measurement: None = None
    attributes_fn: Callable[[Any, str], dict[str, Any] | None] | None = None


SENSOR_ICONS: Mapping[str, str] = {
    "anomaly_score": "mdi:alert-octagon-outline",
    "last_event": "mdi:timeline-clock-outline",
    "health_summary": "mdi:heart-pulse",
    "activity_summary": "mdi:run-fast",
    "electrical_health": "mdi:lightning-bolt-circle",
    "energy_summary": "mdi:home-lightning-bolt-outline",
    "readiness": "mdi:check-decagram-outline",
    "learning_progress": "mdi:school-outline",
    "data_quality_checklist": "mdi:database-alert-outline",
    "energy_dashboard_status": "mdi:view-dashboard-outline",
    "alert_evidence": "mdi:clipboard-alert-outline",
    "recent_activity": "mdi:timeline-text-outline",
    "recent_activity_count": "mdi:counter",
    "sensitivity": "mdi:tune-variant",
    "settings_suggestions": "mdi:tune-variant",
    "circuit_mode": "mdi:transmission-tower",
    "power_flow": "mdi:swap-horizontal",
    "power_quality_score": "mdi:sine-wave",
    "power_quality_evidence": "mdi:lightning-bolt-circle",
    "reactive_power_drift": "mdi:flash-triangle-outline",
    "apparent_power_drift": "mdi:alpha-v-circle-outline",
    "power_factor_drift": "mdi:cosine-wave",
    "nilm_signature_count": "mdi:graph-outline",
    "nilm_unknown_loads": "mdi:home-search-outline",
    "nilm_unmatched_load_percentage": "mdi:chart-scatter-plot",
    "nilm_topology_status": "mdi:source-branch",
    "weather_context": "mdi:thermometer-lines",
    "outdoor_temperature": "mdi:thermometer",
    "rain_pump_correlation": "mdi:weather-rainy",
    "water_flow_correlation": "mdi:water-sync",
    "water_flow_mismatch_minutes": "mdi:pipe-leak",
    "daily_energy_usage": "mdi:counter",
    "energy_usage_share": "mdi:chart-pie",
    "energy_usage_status": "mdi:lightning-bolt-outline",
    "energy_goal_usage": "mdi:target",
    "energy_goal_status": "mdi:flag-checkered",
    "run_cycle_count": "mdi:counter",
    "run_cycle_runtime": "mdi:timer-outline",
    "run_cycle_duty_cycle": "mdi:percent-outline",
    "run_cycle_status": "mdi:run",
    "current_demand": "mdi:gauge",
    "peak_demand": "mdi:chart-line-variant",
    "demand_limit_usage": "mdi:gauge-full",
    "demand_peak_rank": "mdi:podium",
    "demand_peak_status": "mdi:chart-timeline-variant",
    "demand_status": "mdi:transmission-tower",
    "capacity_usage": "mdi:fuse",
    "capacity_status": "mdi:fuse-alert",
    "leg_imbalance": "mdi:scale-balance",
    "leg_imbalance_status": "mdi:scale-unbalanced",
    "metric_consistency_score": "mdi:clipboard-check-outline",
    "metric_consistency_status": "mdi:clipboard-check-outline",
    "balance_power": "mdi:scale-balance",
    "monitored_power": "mdi:flash-outline",
    "monitored_coverage": "mdi:radar",
    "balance_status": "mdi:scale-balance",
    "solar_generation_power": "mdi:solar-power-variant",
    "solar_site_consumption_power": "mdi:home-lightning-bolt-outline",
    "solar_grid_import_power": "mdi:transmission-tower-import",
    "solar_grid_export_power": "mdi:transmission-tower-export",
    "solar_self_consumption": "mdi:home-percent-outline",
    "solar_powered": "mdi:solar-power",
    "solar_flow_status": "mdi:swap-horizontal-bold",
    "solar_surplus_power": "mdi:weather-sunny-alert",
    "solar_load_shift_power": "mdi:clock-fast",
    "solar_flexible_load_power": "mdi:power-plug-outline",
    "solar_flexible_load_coverage": "mdi:chart-donut",
    "solar_load_shift_status": "mdi:clock-check-outline",
    "solar_surplus_status": "mdi:weather-sunny",
    "utility_comparison_difference": "mdi:file-compare",
    "utility_comparison_status": "mdi:receipt-text-check-outline",
    "billing_cycle_usage": "mdi:calendar-counter",
    "billing_cycle_forecast": "mdi:calendar-clock",
    "billing_cycle_budget_usage": "mdi:cash-clock",
    "billing_cycle_status": "mdi:calendar-check",
    "cost_current_rate": "mdi:currency-usd",
    "cost_cycle": "mdi:cash-multiple",
    "cost_cycle_forecast": "mdi:chart-line",
    "cost_status": "mdi:cash-check",
    "always_on_power": "mdi:power-plug",
    "standby_threshold": "mdi:power-standby",
    "standby_status": "mdi:power-sleep",
    "always_on_limit_usage": "mdi:power-cycle",
}


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
        attributes_fn=health_summary_attributes,
    ),
    DiagnosticSensorDescription(
        key="activity_summary",
        name_suffix="Activity Summary",
        value_fn=activity_summary_value,
        attributes_fn=activity_summary_attributes,
    ),
    DiagnosticSensorDescription(
        key="electrical_health",
        name_suffix="Electrical Health",
        value_fn=electrical_health_value,
        attributes_fn=electrical_health_attributes,
    ),
    DiagnosticSensorDescription(
        key="energy_summary",
        name_suffix="Energy Summary",
        value_fn=energy_summary_value,
        attributes_fn=energy_summary_attributes,
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
        key="recent_activity",
        name_suffix="Recent Activity",
        value_fn=recent_activity_value,
        attributes_fn=_mapping_attributes("recent_activity_timeline_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="recent_activity_count",
        name_suffix="Recent Activity Count",
        value_fn=recent_activity_count_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("recent_activity_timeline_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="sensitivity",
        name_suffix="Sensitivity",
        value_fn=sensitivity_value,
        attributes_fn=_sensitivity_attributes,
    ),
    DiagnosticSensorDescription(
        key="settings_suggestions",
        name_suffix="Settings Suggestions",
        value_fn=settings_suggestions_value,
        attributes_fn=settings_suggestions_attributes,
    ),
    DiagnosticSensorDescription(
        key="circuit_mode",
        name_suffix="Circuit Mode",
        value_fn=circuit_mode_value,
    ),
    DiagnosticSensorDescription(
        key="power_flow",
        name_suffix="Power Flow",
        value_fn=power_flow_value,
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
        key="nilm_unknown_loads",
        name_suffix="NILM Unknown Loads",
        value_fn=nilm_unknown_loads_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=nilm_unknown_loads_attributes,
    ),
    DiagnosticSensorDescription(
        key="nilm_unmatched_load_percentage",
        name_suffix="NILM Unmatched Load Percentage",
        value_fn=nilm_unmatched_load_percentage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="nilm_topology_status",
        name_suffix="NILM Topology Status",
        value_fn=nilm_topology_status_value,
        attributes_fn=_mapping_attributes("nilm_topology_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="weather_context",
        name_suffix="Weather Context",
        value_fn=weather_context_value,
        attributes_fn=weather_context_attributes,
    ),
    DiagnosticSensorDescription(
        key="outdoor_temperature",
        name_suffix="Outdoor Temperature",
        value_fn=outdoor_temperature_value,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=outdoor_temperature_attributes,
    ),
    DiagnosticSensorDescription(
        key="rain_pump_correlation",
        name_suffix="Rain Pump Correlation",
        value_fn=rain_pump_correlation_value,
        attributes_fn=rain_pump_correlation_attributes,
    ),
    DiagnosticSensorDescription(
        key="water_flow_correlation",
        name_suffix="Water Flow Correlation",
        value_fn=water_flow_correlation_value,
        attributes_fn=water_flow_correlation_attributes,
    ),
    DiagnosticSensorDescription(
        key="water_flow_mismatch_minutes",
        name_suffix="Water Flow Mismatch Minutes",
        value_fn=water_flow_mismatch_minutes_value,
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=water_flow_correlation_attributes,
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
        key="demand_peak_rank",
        name_suffix="Demand Peak Rank",
        value_fn=demand_peak_rank_value,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("demand_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="demand_peak_status",
        name_suffix="Demand Peak Status",
        value_fn=demand_peak_status_value,
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
        key="solar_generation_power",
        name_suffix="Solar Generation Power",
        value_fn=solar_generation_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_site_consumption_power",
        name_suffix="Solar Site Consumption Power",
        value_fn=solar_site_consumption_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_grid_import_power",
        name_suffix="Solar Grid Import Power",
        value_fn=solar_grid_import_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_grid_export_power",
        name_suffix="Solar Grid Export Power",
        value_fn=solar_grid_export_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_self_consumption",
        name_suffix="Solar Self Consumption",
        value_fn=solar_self_consumption_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_powered",
        name_suffix="Solar Powered",
        value_fn=solar_powered_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_flow_status",
        name_suffix="Solar Flow Status",
        value_fn=solar_flow_status_value,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_surplus_power",
        name_suffix="Solar Surplus Power",
        value_fn=solar_surplus_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_load_shift_power",
        name_suffix="Solar Load Shift Power",
        value_fn=solar_load_shift_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_flexible_load_power",
        name_suffix="Solar Flexible Load Power",
        value_fn=solar_flexible_load_power_value,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_load_shift_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_flexible_load_coverage",
        name_suffix="Solar Flexible Load Coverage",
        value_fn=solar_flexible_load_coverage_value,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attributes_fn=_mapping_attributes("solar_load_shift_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_load_shift_status",
        name_suffix="Solar Load Shift Status",
        value_fn=solar_load_shift_status_value,
        attributes_fn=_mapping_attributes("solar_load_shift_evidence_by_circuit"),
    ),
    DiagnosticSensorDescription(
        key="solar_surplus_status",
        name_suffix="Solar Surplus Status",
        value_fn=solar_surplus_status_value,
        attributes_fn=_mapping_attributes("solar_flow_evidence_by_circuit"),
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

_SUMMARY_SENSOR_KEYS = {
    "health_summary",
    "activity_summary",
    "electrical_health",
    "energy_summary",
    "daily_energy_usage",
    "nilm_signature_count",
    "nilm_unknown_loads",
}
_VISIBLE_BY_DEFAULT_SENSOR_KEYS = {
    *_SUMMARY_SENSOR_KEYS,
    "weather_context",
    "outdoor_temperature",
    "rain_pump_correlation",
    "water_flow_correlation",
}
_NORMAL_ENTITY_SENSOR_KEYS = {
    "health_summary",
    "activity_summary",
    "electrical_health",
    "energy_summary",
    "settings_suggestions",
    "daily_energy_usage",
    "weather_context",
    "outdoor_temperature",
    "rain_pump_correlation",
    "water_flow_correlation",
    "water_flow_mismatch_minutes",
    "energy_usage_share",
    "energy_usage_status",
    "energy_goal_usage",
    "energy_goal_status",
    "run_cycle_count",
    "run_cycle_runtime",
    "run_cycle_duty_cycle",
    "current_demand",
    "peak_demand",
    "demand_limit_usage",
    "capacity_usage",
    "balance_power",
    "monitored_power",
    "monitored_coverage",
    "solar_generation_power",
    "solar_site_consumption_power",
    "solar_grid_import_power",
    "solar_grid_export_power",
    "solar_self_consumption",
    "solar_powered",
    "solar_flow_status",
    "solar_surplus_power",
    "solar_load_shift_power",
    "solar_flexible_load_power",
    "solar_flexible_load_coverage",
    "solar_load_shift_status",
    "solar_surplus_status",
    "utility_comparison_difference",
    "utility_comparison_status",
    "billing_cycle_usage",
    "billing_cycle_forecast",
    "billing_cycle_budget_usage",
    "billing_cycle_status",
    "cost_current_rate",
    "cost_cycle",
    "cost_cycle_forecast",
    "cost_status",
    "always_on_power",
    "standby_threshold",
    "standby_status",
    "always_on_limit_usage",
}


def _entity_tier_for_sensor_key(key: str) -> EntityTier:
    if key in _SUMMARY_SENSOR_KEYS:
        return EntityTier.SUMMARY
    if key in _NORMAL_ENTITY_SENSOR_KEYS:
        return EntityTier.FEATURE
    return EntityTier.DIAGNOSTIC


def _with_entity_defaults(
    description: DiagnosticSensorDescription,
) -> DiagnosticSensorDescription:
    tier = _entity_tier_for_sensor_key(description.key)
    return replace(
        description,
        entity_category=(
            None if tier is not EntityTier.DIAGNOSTIC else description.entity_category
        ),
        entity_registry_enabled_default=entity_enabled_default_for_tier(tier),
        entity_registry_visible_default=(
            description.key in _VISIBLE_BY_DEFAULT_SENSOR_KEYS
        ),
        entity_tier=tier,
    )


SENSOR_DESCRIPTIONS = tuple(
    _with_entity_defaults(description) for description in SENSOR_DESCRIPTIONS
)
SENSOR_ENTITY_TIER_BY_KEY: dict[str, EntityTier] = {
    description.key: description.entity_tier for description in SENSOR_DESCRIPTIONS
}


_CORE_SENSOR_KEYS = {
    "anomaly_score",
    "last_event",
    "health_summary",
    "activity_summary",
    "electrical_health",
    "energy_summary",
    "readiness",
    "learning_progress",
    "data_quality_checklist",
    "energy_dashboard_status",
    "alert_evidence",
    "recent_activity",
    "recent_activity_count",
    "sensitivity",
    "settings_suggestions",
    "circuit_mode",
    "power_flow",
}
_ENERGY_USAGE_SENSOR_KEYS = {
    "daily_energy_usage",
    "energy_usage_share",
    "energy_usage_status",
}
_ENERGY_GOAL_SENSOR_KEYS = {"energy_goal_usage", "energy_goal_status"}
_POWER_QUALITY_SENSOR_KEYS = {"power_quality_score", "power_quality_evidence"}
_RUN_CYCLE_SENSOR_KEYS = {
    "run_cycle_count",
    "run_cycle_runtime",
    "run_cycle_duty_cycle",
    "run_cycle_status",
}
_DEMAND_SENSOR_KEYS = {
    "current_demand",
    "peak_demand",
    "demand_limit_usage",
    "demand_peak_rank",
    "demand_peak_status",
    "demand_status",
}
_CAPACITY_SENSOR_KEYS = {"capacity_usage", "capacity_status"}
_SPLIT_PHASE_SENSOR_KEYS = {
    "leg_imbalance",
    "leg_imbalance_status",
}
_METRIC_CONSISTENCY_SENSOR_KEYS = {
    "metric_consistency_score",
    "metric_consistency_status",
}
_MAINS_NILM_SENSOR_KEYS = {
    "nilm_signature_count",
    "nilm_unknown_loads",
    "nilm_unmatched_load_percentage",
    "nilm_topology_status",
}
_BALANCE_SENSOR_KEYS = {
    "balance_power",
    "monitored_power",
    "monitored_coverage",
    "balance_status",
}
_SOLAR_FLOW_SENSOR_KEYS = {
    "solar_generation_power",
    "solar_site_consumption_power",
    "solar_grid_import_power",
    "solar_grid_export_power",
    "solar_self_consumption",
    "solar_powered",
    "solar_flow_status",
    "solar_surplus_power",
    "solar_load_shift_power",
    "solar_flexible_load_power",
    "solar_flexible_load_coverage",
    "solar_load_shift_status",
    "solar_surplus_status",
}
_UTILITY_COMPARISON_SENSOR_KEYS = {
    "utility_comparison_difference",
    "utility_comparison_status",
}
_BILLING_SENSOR_KEYS = {
    "billing_cycle_usage",
    "billing_cycle_forecast",
    "billing_cycle_budget_usage",
    "billing_cycle_status",
}
_COST_SENSOR_KEYS = {
    "cost_current_rate",
    "cost_cycle",
    "cost_cycle_forecast",
    "cost_status",
}
_STANDBY_SENSOR_KEYS = {
    "always_on_power",
    "standby_threshold",
    "standby_status",
    "always_on_limit_usage",
}
_WEATHER_CONTEXT_SENSOR_KEYS = {"weather_context", "outdoor_temperature"}
_RAIN_PUMP_CONTEXT_SENSOR_KEYS = {"rain_pump_correlation"}
_WATER_FLOW_CONTEXT_SENSOR_KEYS = {
    "water_flow_correlation",
    "water_flow_mismatch_minutes",
}
_WEATHER_CONTEXT_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.HVAC_BLOWER,
    ApplianceProfile.ELECTRIC_HEAT,
}
_RAIN_PUMP_CONTEXT_PROFILES = {
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
}
_WATER_FLOW_CONTEXT_PROFILES = {
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.WASHER,
}
_CYCLIC_APPLIANCE_PROFILES = {
    ApplianceProfile.REFRIGERATOR,
    ApplianceProfile.FREEZER,
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.HVAC_BLOWER,
    ApplianceProfile.ELECTRIC_HEAT,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.OVEN,
    ApplianceProfile.MICROWAVE,
    ApplianceProfile.WASHER,
    ApplianceProfile.DRYER,
    ApplianceProfile.POOL_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.MOTOR_LOAD,
    ApplianceProfile.RESISTIVE_LOAD,
}
_HIGH_POWER_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.ELECTRIC_HEAT,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.OVEN,
    ApplianceProfile.MICROWAVE,
    ApplianceProfile.DRYER,
    ApplianceProfile.POOL_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.EV_CHARGER,
    ApplianceProfile.SOLAR_INVERTER,
    ApplianceProfile.MAINS_NILM,
}
_POWER_QUALITY_ROLES = {
    SensorRole.REAL_POWER,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.CURRENT,
    SensorRole.VOLTAGE,
}
def sensor_description_applies(
    description: DiagnosticSensorDescription,
    circuit: Any,
    coordinator: Any,
    configured_circuits: Iterable[Any] | None = None,
) -> bool:
    """Return whether a diagnostic sensor is useful for this circuit."""
    key = description.key
    if key in _CORE_SENSOR_KEYS:
        return True

    roles = _sensor_roles(circuit)
    profile = _appliance_profile(circuit)
    mode = _circuit_mode(circuit)
    is_mains = mode is CircuitMode.MAINS_NILM or profile is ApplianceProfile.MAINS_NILM
    has_real_power = SensorRole.REAL_POWER in roles
    has_energy = SensorRole.ENERGY in roles
    has_current = SensorRole.CURRENT in roles
    has_voltage = SensorRole.VOLTAGE in roles

    if key in _ENERGY_USAGE_SENSOR_KEYS:
        return has_energy
    if key in _ENERGY_GOAL_SENSOR_KEYS:
        return has_energy and (
            _configured_positive(circuit, "daily_energy_goal_kwh")
            or _stored_settings(coordinator, "energy_goal_settings_by_circuit", circuit)
        )
    if key in _POWER_QUALITY_SENSOR_KEYS:
        return bool(roles & _POWER_QUALITY_ROLES)
    if key == "reactive_power_drift":
        return SensorRole.REACTIVE_POWER in roles
    if key == "apparent_power_drift":
        return SensorRole.APPARENT_POWER in roles
    if key == "power_factor_drift":
        return SensorRole.POWER_FACTOR in roles
    if key in _MAINS_NILM_SENSOR_KEYS:
        return is_mains
    if key in _RUN_CYCLE_SENSOR_KEYS:
        return (
            profile in _CYCLIC_APPLIANCE_PROFILES
            and not is_mains
            and (has_real_power or has_current)
        )
    if key in _DEMAND_SENSOR_KEYS:
        return has_real_power and (
            is_mains
            or mode is CircuitMode.DUAL_PHASE
            or profile in _HIGH_POWER_PROFILES
        )
    if key in _CAPACITY_SENSOR_KEYS:
        return (
            (has_current or (has_real_power and has_voltage))
            and _stored_settings(coordinator, "capacity_settings_by_circuit", circuit)
        )
    if key in _SPLIT_PHASE_SENSOR_KEYS:
        return mode is CircuitMode.DUAL_PHASE and (has_real_power or has_current)
    if key in _METRIC_CONSISTENCY_SENSOR_KEYS:
        has_consistency_context = (
            SensorRole.APPARENT_POWER in roles
            or SensorRole.POWER_FACTOR in roles
            or (has_voltage and has_current)
        )
        is_dedicated_appliance = (
            mode is not CircuitMode.MIXED
            and profile is not ApplianceProfile.MIXED
        )
        return has_real_power and has_consistency_context and (
            is_mains or is_dedicated_appliance
        )
    if key in _BALANCE_SENSOR_KEYS:
        return is_mains
    if key in _SOLAR_FLOW_SENSOR_KEYS:
        return is_mains and _has_solar_flow_sources(coordinator, configured_circuits)
    if key in _UTILITY_COMPARISON_SENSOR_KEYS:
        return _stored_settings(
            coordinator,
            "utility_comparison_settings_by_circuit",
            circuit,
        )
    if key in _BILLING_SENSOR_KEYS:
        return has_energy and (
            _configured_positive(circuit, "billing_cycle_budget_kwh")
            or _stored_settings(coordinator, "billing_settings_by_circuit", circuit)
        )
    if key in _COST_SENSOR_KEYS:
        return has_energy and (
            _configured_positive(circuit, "default_rate_per_kwh")
            or _configured_positive(circuit, "tou_rate_per_kwh")
            or _stored_settings(coordinator, "cost_settings_by_circuit", circuit)
        )
    if key in _STANDBY_SENSOR_KEYS:
        return (
            not is_mains
            and has_real_power
            and (
                profile in _CYCLIC_APPLIANCE_PROFILES
                or _stored_settings(coordinator, "standby_settings_by_circuit", circuit)
            )
        )
    if key in _WEATHER_CONTEXT_SENSOR_KEYS:
        return profile in _WEATHER_CONTEXT_PROFILES and _has_temperature_source(
            coordinator,
        )
    if key in _RAIN_PUMP_CONTEXT_SENSOR_KEYS:
        return profile in _RAIN_PUMP_CONTEXT_PROFILES and _has_rain_context_source(
            coordinator,
        )
    if key in _WATER_FLOW_CONTEXT_SENSOR_KEYS:
        return profile in _WATER_FLOW_CONTEXT_PROFILES and _has_water_flow_source(
            coordinator,
            circuit,
        )
    return False


def _applicable_sensor_descriptions(
    circuit: Any,
    coordinator: Any,
    configured_circuits: Iterable[Any] | None = None,
) -> tuple[DiagnosticSensorDescription, ...]:
    return tuple(
        description
        for description in SENSOR_DESCRIPTIONS
        if sensor_description_applies(
            description,
            circuit,
            coordinator,
            configured_circuits,
        )
    )


def _sensor_roles(circuit: Any) -> set[SensorRole]:
    sensors = circuit.get("sensors", ()) if isinstance(circuit, Mapping) else getattr(
        circuit,
        "sensors",
        (),
    )
    roles: set[SensorRole] = set()
    for sensor in sensors or ():
        role = sensor.get("role") if isinstance(sensor, Mapping) else getattr(
            sensor,
            "role",
            None,
        )
        try:
            roles.add(SensorRole(role))
        except (TypeError, ValueError):
            continue
    return roles


def _appliance_profile(circuit: Any) -> ApplianceProfile | None:
    raw_profile = (
        circuit.get("appliance_profile")
        if isinstance(circuit, Mapping)
        else getattr(circuit, "appliance_profile", None)
    )
    raw_profile = _appliance_profile_alias(str(raw_profile or ""))
    try:
        return ApplianceProfile(raw_profile)
    except (TypeError, ValueError):
        return None


def _appliance_profile_alias(raw_profile: str) -> str:
    normalized = raw_profile.strip().lower()
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
        "clothes_washer": ApplianceProfile.WASHER.value,
        "laundry_washer": ApplianceProfile.WASHER.value,
        "washing_machine": ApplianceProfile.WASHER.value,
        "clothes_dryer": ApplianceProfile.DRYER.value,
        "electric_dryer": ApplianceProfile.DRYER.value,
        "gas_dryer": ApplianceProfile.DRYER.value,
        "microwave_oven": ApplianceProfile.MICROWAVE.value,
        "kitchen_microwave": ApplianceProfile.MICROWAVE.value,
        "car_charger": ApplianceProfile.EV_CHARGER.value,
        "vehicle_charger": ApplianceProfile.EV_CHARGER.value,
        "vehicle_charging": ApplianceProfile.EV_CHARGER.value,
        "level2_charger": ApplianceProfile.EV_CHARGER.value,
        "level_2_charger": ApplianceProfile.EV_CHARGER.value,
        "wall_connector": ApplianceProfile.EV_CHARGER.value,
    }
    return aliases.get(normalized, normalized)


def _circuit_mode(circuit: Any) -> CircuitMode | None:
    raw_mode = circuit.get("mode") if isinstance(circuit, Mapping) else getattr(
        circuit,
        "mode",
        None,
    )
    try:
        return CircuitMode(raw_mode)
    except (TypeError, ValueError):
        return None


def _circuit_id(circuit: Any) -> str:
    if isinstance(circuit, Mapping):
        return str(circuit.get("circuit_id") or circuit.get("id") or "")
    return str(getattr(circuit, "circuit_id", "") or "")


def _configured_positive(circuit: Any, field_name: str) -> bool:
    value = circuit.get(field_name) if isinstance(circuit, Mapping) else getattr(
        circuit,
        field_name,
        None,
    )
    try:
        return float(value) > 0.0
    except (TypeError, ValueError):
        return False


def _stored_settings(coordinator: Any, field_name: str, circuit: Any) -> bool:
    store_data = getattr(coordinator, "store_data", None)
    settings_by_circuit = getattr(store_data, field_name, {}) if store_data else {}
    settings = settings_by_circuit.get(_circuit_id(circuit), {})
    if isinstance(settings, Mapping) and bool(settings):
        return True
    config_key = {
        "utility_comparison_settings_by_circuit": CONF_UTILITY_COMPARISON_SETTINGS,
    }.get(field_name)
    if config_key is None:
        return False
    settings_by_circuit = _coordinator_config_value(coordinator, config_key)
    if not isinstance(settings_by_circuit, Mapping):
        return False
    settings = settings_by_circuit.get(_circuit_id(circuit), {})
    return isinstance(settings, Mapping) and bool(settings)


def _has_temperature_source(coordinator: Any) -> bool:
    value = _coordinator_config_value(coordinator, CONF_OUTDOOR_TEMPERATURE_ENTITY)
    return value is not None and bool(str(value).strip())


def _has_rain_context_source(coordinator: Any) -> bool:
    return any(
        bool(str(_coordinator_config_value(coordinator, key) or "").strip())
        for key in (CONF_RAIN_SENSOR_ENTITY, CONF_RAIN_INTENSITY_ENTITY)
    )


def _has_water_flow_source(coordinator: Any, circuit: Any | None = None) -> bool:
    value = _coordinator_config_value(coordinator, CONF_WATER_FLOW_SENSOR_ENTITIES)
    if isinstance(value, str):
        if value.strip():
            return True
    if isinstance(value, (list, tuple, set)):
        if any(bool(str(item).strip()) for item in value):
            return True
    return circuit is not None and _has_linked_water_flow_source(coordinator, circuit)


def _has_linked_water_flow_source(coordinator: Any, circuit: Any) -> bool:
    settings = _advanced_settings_for_circuit(coordinator, circuit)
    value = settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(bool(str(item).strip()) for item in value)
    return False


def _advanced_settings_for_circuit(
    coordinator: Any,
    circuit: Any,
) -> Mapping[str, Any]:
    settings_by_circuit = _coordinator_config_value(coordinator, CONF_ADVANCED_SETTINGS)
    if not isinstance(settings_by_circuit, Mapping):
        return {}
    settings = settings_by_circuit.get(_circuit_id(circuit), {})
    return settings if isinstance(settings, Mapping) else {}


def _coordinator_config_value(coordinator: Any, key: str) -> Any:
    if key == CONF_UTILITY_COMPARISON_SETTINGS:
        merged: dict[str, Any] = {}
        for field_name in ("entry_data", "options"):
            container = getattr(coordinator, field_name, {})
            value = container.get(key) if isinstance(container, Mapping) else None
            if isinstance(value, Mapping):
                merged.update(value)
        if merged:
            return merged
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        if isinstance(container, Mapping) and container.get(key):
            return container[key]
    return None


def _has_solar_flow_sources(
    coordinator: Any,
    configured_circuits: Iterable[Any] | None = None,
) -> bool:
    circuits = tuple(configured_circuits or ()) or _configured_circuits(coordinator)
    for circuit in circuits:
        profile = _appliance_profile(circuit)
        power_flow = (
            circuit.get("power_flow")
            if isinstance(circuit, Mapping)
            else getattr(circuit, "power_flow", None)
        )
        if profile is ApplianceProfile.SOLAR_INVERTER:
            return True
        try:
            if PowerFlowMode(power_flow) is PowerFlowMode.GENERATION:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _configured_circuits(coordinator: Any) -> tuple[Any, ...]:
    circuits = tuple(getattr(coordinator, "circuit_configs", ()) or ())
    if circuits:
        return circuits
    for field_name in ("entry_data", "options"):
        container = getattr(coordinator, field_name, {})
        if isinstance(container, Mapping):
            configured = container.get(CONF_CIRCUITS)
            if isinstance(configured, (list, tuple)):
                return tuple(configured)
    return ()


setup_health_value = _entity_setup_health_value
setup_health_attributes = _entity_setup_health_attributes


class SetupHealthSensor(CoordinatorEntity, SensorEntity):
    """Top-level setup health and next-step sensor for the integration."""

    _attr_has_entity_name = False
    _attr_entity_category = None
    _attr_entity_registry_visible_default = True
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, coordinator: Any, *, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_name = SETUP_HEALTH_ENTITY_NAME
        self._attr_unique_id = f"{entry_id}_{SETUP_HEALTH_ENTITY_KEY}"
        self._attr_suggested_object_id = SETUP_HEALTH_SUGGESTED_OBJECT_ID

    @property
    def unique_id(self) -> str:
        """Return the stable unique ID for fallback tests."""
        return self._attr_unique_id

    @property
    def suggested_object_id(self) -> str:
        """Return the stable suggested object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def name(self) -> str:
        """Return the visible entity name."""
        return self._attr_name

    @property
    def icon(self) -> str | None:
        """Return the setup-health icon."""
        return self._attr_icon

    @property
    def native_value(self) -> str:
        """Return the current setup-health next step."""
        return setup_health_value(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return setup-health issue details."""
        return setup_health_attributes(self.coordinator)


class CircuitAnalyzerSensor(CircuitAnalyzerEntity, SensorEntity):
    """Sensor exposing one analyzed value for a configured circuit."""

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
        self._attr_entity_category = description.entity_category
        self._attr_entity_registry_enabled_default = (
            entity_enabled_default_for_tier(
                description.entity_tier,
                entity_detail_level_for_coordinator(coordinator),
            )
        )
        self._attr_entity_registry_visible_default = (
            description.entity_registry_visible_default
        )
        self._attr_icon = (
            appliance_icon_for_profile(circuit.appliance_profile)
            if description.key == "activity_summary"
            else None
        ) or description.icon or SENSOR_ICONS.get(description.key)
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the native unit, allowing temperature display units to vary."""
        if self.entity_description.key == "outdoor_temperature":
            attributes = outdoor_temperature_attributes(
                self.coordinator_state,
                self.circuit_id,
            )
            return str(
                attributes.get("temperature_unit")
                or UnitOfTemperature.FAHRENHEIT,
            )
        return self._attr_native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        """Return the latest diagnostic value."""
        if self.coordinator_state is None:
            value = self.entity_description.value_fn(None, self.circuit_id)
        else:
            value = self.entity_description.value_fn(
                self.coordinator_state,
                self.circuit_id,
            )
        if _is_status_sensor_key(self.entity_description.key):
            attributes_fn = self.entity_description.attributes_fn
            attributes = (
                attributes_fn(self.coordinator_state, self.circuit_id)
                if attributes_fn is not None
                else None
            )
            value = _status_raw_value(
                self.entity_description,
                self.coordinator_state,
                self.circuit_id,
                attributes,
            )
            return _status_label(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional diagnostics for sensors that expose detail."""
        attributes_fn = self.entity_description.attributes_fn
        attributes = (
            attributes_fn(self.coordinator_state, self.circuit_id)
            if attributes_fn is not None
            else None
        )
        if not _is_status_sensor_key(self.entity_description.key):
            return attributes

        raw_status = _status_raw_value(
            self.entity_description,
            self.coordinator_state,
            self.circuit_id,
            attributes,
        )
        status_attributes = dict(attributes or {})
        status_attributes["raw_status"] = str(raw_status)
        status_attributes["status_label"] = _status_label(raw_status)
        status_attributes["status_explanation"] = _status_explanation(raw_status)
        return status_attributes


class DemoSourceSensor(SensorEntity):
    """Synthetic source sensor used by the installed demo dashboard."""

    _attr_has_entity_name = False
    _attr_entity_registry_visible_default = False

    def __init__(self, *, entry_id: str, sensor: SensorRef) -> None:
        object_id = sensor.entity_id.removeprefix("sensor.")
        circuit_id = _demo_circuit_id_from_entity_id(sensor.entity_id)
        role = _coerce_sensor_role(sensor.role)
        metadata = _DEMO_SOURCE_ROLE_METADATA.get(role, {})

        self.entity_id = sensor.entity_id
        self._attr_name = _title_from_object_id(object_id)
        self._attr_unique_id = f"{entry_id}_demo_source_exact_{object_id}"
        self._attr_suggested_object_id = object_id
        self._attr_native_value = _demo_source_value(circuit_id, role)
        self._attr_device_class = metadata.get("device_class")
        self._attr_native_unit_of_measurement = metadata.get("unit") or None
        self._attr_state_class = metadata.get("state_class")
        self._attr_icon = metadata.get("icon")
        self._entry_id = entry_id

    @property
    def unique_id(self) -> str:
        """Unique ID for fallback tests."""
        return self._attr_unique_id

    @property
    def suggested_object_id(self) -> str:
        """Suggested Home Assistant object ID for fallback tests."""
        return self._attr_suggested_object_id

    @property
    def name(self) -> str:
        """Entity display name for fallback tests."""
        return self._attr_name

    @property
    def native_value(self) -> float | None:
        """Return the demo measurement value."""
        return self._attr_native_value

    @property
    def device_class(self) -> str | None:
        """Return the measurement device class."""
        return self._attr_device_class

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the measurement unit."""
        return self._attr_native_unit_of_measurement

    @property
    def state_class(self) -> str | None:
        """Return the recorder state class."""
        return self._attr_state_class

    @property
    def icon(self) -> str | None:
        """Return the demo source icon."""
        return self._attr_icon


def _demo_source_entities_for_circuits(
    entry_id: str,
    circuits: tuple[Any, ...],
) -> list[DemoSourceSensor]:
    entities: list[DemoSourceSensor] = []
    seen: set[str] = set()
    for circuit in circuits:
        sensors = (
            circuit.get("sensors", ())
            if isinstance(circuit, Mapping)
            else getattr(circuit, "sensors", ())
        )
        for sensor in sensors or ():
            sensor_ref = _sensor_ref_or_none(sensor)
            if sensor_ref is None:
                continue
            if sensor_ref.entity_id in seen:
                continue
            if not _is_demo_source_entity_id(sensor_ref.entity_id):
                continue
            entities.append(DemoSourceSensor(entry_id=entry_id, sensor=sensor_ref))
            seen.add(sensor_ref.entity_id)
    return entities


def _sensor_ref_or_none(sensor: Any) -> SensorRef | None:
    if isinstance(sensor, SensorRef):
        return sensor
    if isinstance(sensor, Mapping):
        entity_id = sensor.get("entity_id")
        role = sensor.get("role")
        leg = sensor.get("leg")
        unit = sensor.get("unit")
    else:
        entity_id = getattr(sensor, "entity_id", None)
        role = getattr(sensor, "role", None)
        leg = getattr(sensor, "leg", None)
        unit = getattr(sensor, "unit", None)
    if not isinstance(entity_id, str) or not entity_id:
        return None
    try:
        sensor_role = SensorRole(role)
    except (TypeError, ValueError):
        return None
    return SensorRef(entity_id, sensor_role, leg=leg, unit=unit)


def _coerce_sensor_role(role: Any) -> SensorRole:
    return role if isinstance(role, SensorRole) else SensorRole(role)


def _title_from_object_id(object_id: str) -> str:
    text = object_id.removeprefix("cs_energy_analyzer_demo_")
    return text.replace("_", " ").title()


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up diagnostic sensor entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    configured_circuits = tuple(circuits_for_entities(entry, coordinator))
    entities: list[SensorEntity] = [
        SetupHealthSensor(coordinator, entry_id=entry_id),
    ]

    for raw_circuit in configured_circuits:
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        descriptions = _applicable_sensor_descriptions(
            raw_circuit,
            coordinator,
            configured_circuits,
        )
        entities.extend(
            CircuitAnalyzerSensor(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in descriptions
        )

    entities.extend(
        _demo_source_entities_for_circuits(
            entry_id,
            configured_circuits,
        )
    )
    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    enable_summary_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        tier_by_unique_id_suffix=SENSOR_ENTITY_TIER_BY_KEY,
    )
    hidden_sensor_suffixes = {
        description.key
        for description in SENSOR_DESCRIPTIONS
        if description.entity_registry_visible_default is False
    }
    hidden_demo_source_suffixes = {
        unique_id.removeprefix(f"{entry_id}_")
        for unique_id in {
            str(getattr(entity, "unique_id", ""))
            for entity in entities
            if isinstance(entity, DemoSourceSensor)
        }
        if unique_id.startswith(f"{entry_id}_demo_source_")
    }
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)
    sync_entity_registry_visibility(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        hidden_unique_id_suffixes=hidden_sensor_suffixes,
        detail_level=entity_detail_level_for_coordinator(coordinator),
    )
    hide_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        hidden_unique_id_suffixes=hidden_demo_source_suffixes,
    )
    sync_entity_registry_categories(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        entity_category_by_unique_id_suffix={
            description.key: description.entity_category
            for description in SENSOR_DESCRIPTIONS
        },
    )
