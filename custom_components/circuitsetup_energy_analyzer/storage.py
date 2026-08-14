from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any, Self

from .const import STORAGE_KEY, STORAGE_VERSION
from .contextual_baseline import (
    contextual_sample_from_dict,
)
from .models import (
    AlertEvidence,
    BaselineStats,
    CircuitEvent,
    EventType,
    RetentionMode,
    Severity,
)
from .nilm_confidence import migrate_nilm_confidence_semantics
from .settings_advisor import (
    RecommendationDecision,
    SettingRecommendation,
    decision_from_dict,
    decision_to_dict,
    recommendation_from_dict,
    recommendation_to_dict,
)
from .unknown_loads import (
    NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
    _sanitize_nilm_session_history_ingress,
)
from .ux import normalize_nilm_detection_sensitivity, normalize_sensitivity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store
else:
    HomeAssistant = Any
    Store = Any

_LOGGER = logging.getLogger(__name__)


RETENTION_WINDOWS: dict[RetentionMode, timedelta] = {
    RetentionMode.LIGHTWEIGHT: timedelta(days=18),
    RetentionMode.STANDARD: timedelta(days=45),
    RetentionMode.DIAGNOSTIC: timedelta(days=180),
}
CONTEXTUAL_SAMPLE_CAPS: dict[RetentionMode, int] = {
    RetentionMode.LIGHTWEIGHT: 500,
    RetentionMode.STANDARD: 2000,
    RetentionMode.DIAGNOSTIC: 10000,
}
CONTEXTUAL_BUCKET_CAPS: dict[RetentionMode, int] = {
    RetentionMode.LIGHTWEIGHT: 64,
    RetentionMode.STANDARD: 128,
    RetentionMode.DIAGNOSTIC: 512,
}


@dataclass(slots=True)
class FeatureStoreData:
    """In-memory feature store payload."""

    events: list[CircuitEvent] = field(default_factory=list)
    baselines: dict[str, BaselineStats] = field(default_factory=dict)
    alerts: list[AlertEvidence] = field(default_factory=list)
    nilm_signatures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    nilm_unknown_loads_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    nilm_unmatched_edges_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    nilm_session_history_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    nilm_known_load_attributions_by_circuit: dict[str, list[dict[str, Any]]] = (
        field(default_factory=dict)
    )
    nilm_session_history_ingress_by_circuit: dict[
        str, dict[str, int | bool]
    ] = field(default_factory=dict, repr=False)
    nilm_label_intervals_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    nilm_appliance_assignments_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    weather_context_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    weather_context_history_by_circuit: dict[str, list[dict[str, Any]]] = field(
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
    hvac_response_history_by_stream: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    hvac_response_context_by_stream: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    hvac_correlation_history_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    hvac_baseline_era_by_stream: dict[str, str] = field(default_factory=dict)
    contextual_baseline_samples_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    contextual_baselines_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
    nilm_detection_sensitivity_by_circuit: dict[str, str] = field(
        default_factory=dict
    )
    maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    alert_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    energy_usage_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    energy_goal_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    activity_alert_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    energy_usage_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    billing_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    billing_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    cost_settings_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    cost_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    demand_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    demand_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    capacity_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    leg_imbalance_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    mains_power_quality_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    metric_consistency_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    balance_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    solar_flow_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    utility_comparison_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    standby_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    standby_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    operating_detection_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    settings_recommendations: dict[str, SettingRecommendation] = field(
        default_factory=dict
    )
    settings_recommendation_decisions: dict[str, RecommendationDecision] = field(
        default_factory=dict
    )
    settings_recommendation_notification_episode_key: tuple[
        tuple[str, ...],
        ...,
    ] = field(default_factory=tuple)
    appliance_notification_preferences: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    notification_delivery_state: dict[str, Any] = field(default_factory=dict)
    weekly_digest_settings: dict[str, Any] = field(default_factory=dict)
    appliance_schedule_settings: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    appliance_schedule_evidence: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    dashboard_status: dict[str, Any] = field(default_factory=dict)
    learning_started_at_by_circuit: dict[str, str] = field(default_factory=dict)


def event_to_dict(event: CircuitEvent) -> dict[str, Any]:
    """Serialize a circuit event for JSON storage."""
    return {
        "timestamp": event.timestamp.isoformat(),
        "circuit_id": event.circuit_id,
        "event_type": event.event_type.value,
        "severity": event.severity.value,
        "features": _features_to_dict(event.features),
    }


def event_from_dict(raw: dict[str, Any]) -> CircuitEvent:
    """Deserialize a circuit event from JSON storage."""
    return CircuitEvent(
        timestamp=datetime.fromisoformat(raw["timestamp"]),
        circuit_id=str(raw["circuit_id"]),
        event_type=EventType(raw["event_type"]),
        severity=Severity(raw.get("severity", Severity.INFO.value)),
        features=_features_to_dict(raw.get("features", {})),
    )


def baseline_to_dict(baseline: BaselineStats) -> dict[str, Any]:
    """Serialize baseline statistics for JSON storage."""
    return {
        "feature": baseline.feature,
        "sample_count": baseline.sample_count,
        "median": baseline.median,
        "mad": baseline.mad,
        "p10": baseline.p10,
        "p90": baseline.p90,
        "confidence": baseline.confidence,
    }


def baseline_from_dict(raw: dict[str, Any]) -> BaselineStats:
    """Deserialize baseline statistics from JSON storage."""
    return BaselineStats(
        feature=str(raw["feature"]),
        sample_count=int(raw["sample_count"]),
        median=float(raw["median"]),
        mad=float(raw["mad"]),
        p10=float(raw["p10"]),
        p90=float(raw["p90"]),
        confidence=float(raw["confidence"]),
    )


def alert_to_dict(alert: AlertEvidence) -> dict[str, Any]:
    """Serialize alert evidence for JSON storage."""
    payload = {
        "timestamp": alert.timestamp.isoformat(),
        "circuit_id": alert.circuit_id,
        "severity": alert.severity.value,
        "message": alert.message,
        "event_type": alert.event_type.value if alert.event_type else None,
        "features": _features_to_dict(alert.features),
        "feature": alert.feature,
        "value_metric": alert.value_metric,
        "observed_value": alert.observed_value,
        "baseline_value": alert.baseline_value,
        "change_ratio": alert.change_ratio,
        "repeated_count": alert.repeated_count,
        "first_seen": alert.first_seen.isoformat() if alert.first_seen else None,
        "last_seen": alert.last_seen.isoformat() if alert.last_seen else None,
    }
    if alert.feedback_status is not None:
        payload["feedback_status"] = alert.feedback_status
    if alert.feedback_effect is not None:
        payload["feedback_effect"] = alert.feedback_effect
    if alert.feedback_expires_at is not None:
        payload["feedback_expires_at"] = alert.feedback_expires_at.isoformat()
    if alert.matching_feedback_fingerprint is not None:
        payload["matching_feedback_fingerprint"] = (
            alert.matching_feedback_fingerprint
        )
    if alert.adjusted_min_repeated is not None:
        payload["adjusted_min_repeated"] = alert.adjusted_min_repeated
    return payload


def alert_from_dict(raw: dict[str, Any]) -> AlertEvidence:
    """Deserialize alert evidence from JSON storage."""
    event_type = raw.get("event_type")
    first_seen = raw.get("first_seen")
    last_seen = raw.get("last_seen")
    feedback_expires_at = raw.get("feedback_expires_at")
    return AlertEvidence(
        timestamp=datetime.fromisoformat(raw["timestamp"]),
        circuit_id=str(raw["circuit_id"]),
        severity=Severity(raw["severity"]),
        message=str(raw["message"]),
        event_type=EventType(event_type) if event_type else None,
        features=_features_to_dict(raw.get("features", {})),
        feature=str(raw.get("feature", "")),
        value_metric=str(raw.get("value_metric", "")),
        observed_value=float(raw.get("observed_value", 0.0)),
        baseline_value=float(raw.get("baseline_value", 0.0)),
        change_ratio=float(raw.get("change_ratio", 0.0)),
        repeated_count=int(raw.get("repeated_count", 1)),
        first_seen=datetime.fromisoformat(first_seen) if first_seen else None,
        last_seen=datetime.fromisoformat(last_seen) if last_seen else None,
        feedback_status=(
            str(raw["feedback_status"]) if raw.get("feedback_status") else None
        ),
        feedback_effect=(
            str(raw["feedback_effect"]) if raw.get("feedback_effect") else None
        ),
        feedback_expires_at=(
            datetime.fromisoformat(feedback_expires_at)
            if feedback_expires_at
            else None
        ),
        matching_feedback_fingerprint=(
            str(raw["matching_feedback_fingerprint"])
            if raw.get("matching_feedback_fingerprint")
            else None
        ),
        adjusted_min_repeated=(
            int(raw["adjusted_min_repeated"])
            if raw.get("adjusted_min_repeated") is not None
            else None
        ),
    )


def feature_store_data_to_dict(data: FeatureStoreData) -> dict[str, Any]:
    """Serialize the full feature store payload for Home Assistant storage."""
    return {
        "schema_version": STORAGE_VERSION,
        "events": [event_to_dict(event) for event in data.events],
        "baselines": {
            key: baseline_to_dict(baseline)
            for key, baseline in data.baselines.items()
        },
        "learning_started_at_by_circuit": {
            str(circuit_id): str(timestamp)
            for circuit_id, timestamp in data.learning_started_at_by_circuit.items()
        },
        "alerts": [alert_to_dict(alert) for alert in data.alerts],
        "nilm_signatures": {
            str(circuit_id): [dict(signature) for signature in signatures]
            for circuit_id, signatures in data.nilm_signatures.items()
        },
        "nilm_unknown_loads_by_circuit": _dict_of_dicts(
            data.nilm_unknown_loads_by_circuit
        ),
        "nilm_unmatched_edges_by_circuit": _dict_of_list_dicts_including_empty(
            data.nilm_unmatched_edges_by_circuit
        ),
        "nilm_session_history_by_circuit": _dict_of_list_dicts(
            data.nilm_session_history_by_circuit
        ),
        "nilm_known_load_attributions_by_circuit": _dict_of_list_dicts(
            data.nilm_known_load_attributions_by_circuit
        ),
        "nilm_label_intervals_by_circuit": _dict_of_list_dicts(
            data.nilm_label_intervals_by_circuit
        ),
        "nilm_appliance_assignments_by_circuit": _dict_of_list_dicts(
            data.nilm_appliance_assignments_by_circuit
        ),
        "weather_context_by_circuit": _dict_of_dicts(
            data.weather_context_by_circuit
        ),
        "weather_context_history_by_circuit": _dict_of_list_dicts(
            data.weather_context_history_by_circuit
        ),
        "rain_pump_context_by_circuit": _dict_of_dicts(
            data.rain_pump_context_by_circuit
        ),
        "water_flow_context_by_circuit": _dict_of_dicts(
            data.water_flow_context_by_circuit
        ),
        "water_context_history_by_circuit": _dict_of_list_dicts(
            data.water_context_history_by_circuit
        ),
        "hvac_response_history_by_stream": _dict_of_list_dicts(
            data.hvac_response_history_by_stream
        ),
        "hvac_response_context_by_stream": _dict_of_dicts(
            data.hvac_response_context_by_stream
        ),
        "hvac_correlation_history_by_circuit": _dict_of_list_dicts(
            data.hvac_correlation_history_by_circuit
        ),
        "hvac_baseline_era_by_stream": {
            str(stream_id): str(era)
            for stream_id, era in data.hvac_baseline_era_by_stream.items()
        },
        "contextual_baseline_samples_by_circuit": _dict_of_list_dicts(
            data.contextual_baseline_samples_by_circuit
        ),
        "contextual_baselines_by_circuit": _dict_of_dicts(
            data.contextual_baselines_by_circuit
        ),
        "sensitivity_by_circuit": {
            str(circuit_id): normalize_sensitivity(sensitivity)
            for circuit_id, sensitivity in data.sensitivity_by_circuit.items()
        },
        "nilm_detection_sensitivity_by_circuit": {
            str(circuit_id): normalize_nilm_detection_sensitivity(sensitivity)
            for circuit_id, sensitivity in (
                data.nilm_detection_sensitivity_by_circuit.items()
            )
        },
        "maintenance_by_circuit": _dict_of_dicts(data.maintenance_by_circuit),
        "alert_feedback": _dict_of_dicts(data.alert_feedback),
        "energy_usage_settings_by_circuit": _dict_of_dicts(
            data.energy_usage_settings_by_circuit
        ),
        "energy_goal_settings_by_circuit": _dict_of_dicts(
            data.energy_goal_settings_by_circuit
        ),
        "activity_alert_settings_by_circuit": _dict_of_dicts(
            data.activity_alert_settings_by_circuit
        ),
        "energy_usage_by_circuit": _dict_of_dicts(data.energy_usage_by_circuit),
        "billing_settings_by_circuit": _dict_of_dicts(
            data.billing_settings_by_circuit
        ),
        "billing_by_circuit": _dict_of_dicts(data.billing_by_circuit),
        "cost_settings_by_circuit": _dict_of_dicts(data.cost_settings_by_circuit),
        "cost_by_circuit": _dict_of_dicts(data.cost_by_circuit),
        "demand_settings_by_circuit": _dict_of_dicts(data.demand_settings_by_circuit),
        "demand_by_circuit": _dict_of_dicts(data.demand_by_circuit),
        "capacity_settings_by_circuit": _dict_of_dicts(
            data.capacity_settings_by_circuit
        ),
        "leg_imbalance_settings_by_circuit": _dict_of_dicts(
            data.leg_imbalance_settings_by_circuit
        ),
        "mains_power_quality_settings_by_circuit": _dict_of_dicts(
            data.mains_power_quality_settings_by_circuit
        ),
        "metric_consistency_settings_by_circuit": _dict_of_dicts(
            data.metric_consistency_settings_by_circuit
        ),
        "balance_settings_by_circuit": _dict_of_dicts(
            data.balance_settings_by_circuit
        ),
        "solar_flow_settings_by_circuit": _dict_of_dicts(
            data.solar_flow_settings_by_circuit
        ),
        "utility_comparison_settings_by_circuit": _dict_of_dicts(
            data.utility_comparison_settings_by_circuit
        ),
        "standby_settings_by_circuit": _dict_of_dicts(
            data.standby_settings_by_circuit
        ),
        "standby_by_circuit": _dict_of_dicts(data.standby_by_circuit),
        "operating_detection_settings_by_circuit": _dict_of_dicts(
            data.operating_detection_settings_by_circuit
        ),
        "settings_recommendations": {
            str(recommendation_id): recommendation_to_dict(recommendation)
            for recommendation_id, recommendation in (
                data.settings_recommendations.items()
            )
        },
        "settings_recommendation_decisions": {
            str(unique_key): decision_to_dict(decision)
            for unique_key, decision in (
                data.settings_recommendation_decisions.items()
            )
        },
        "settings_recommendation_notification_episode_key": [
            list(part)
            for part in data.settings_recommendation_notification_episode_key
        ],
        "appliance_notification_preferences": _dict_of_dicts(
            data.appliance_notification_preferences
        ),
        "notification_delivery_state": _json_mapping(
            data.notification_delivery_state
        ),
        "weekly_digest_settings": _json_mapping(
            data.weekly_digest_settings
        ),
        "appliance_schedule_settings": _dict_of_dicts(
            data.appliance_schedule_settings
        ),
        "appliance_schedule_evidence": _dict_of_dicts(
            data.appliance_schedule_evidence
        ),
        "dashboard_status": _dict_of_jsonable_values(data.dashboard_status),
    }


def feature_store_data_from_dict(raw: dict[str, Any] | None) -> FeatureStoreData:
    """Deserialize the full feature store payload from Home Assistant storage."""
    if raw is None:
        return FeatureStoreData()
    nilm_session_history, nilm_session_history_ingress = (
        _nilm_session_history_from_raw(
            raw.get("nilm_session_history_by_circuit", {})
        )
    )
    data = FeatureStoreData(
        events=_events_from_raw(raw.get("events", [])),
        baselines=_baselines_from_raw(raw.get("baselines", {})),
        learning_started_at_by_circuit={
            str(circuit_id): str(timestamp)
            for circuit_id, timestamp in _mapping_items(
                raw.get("learning_started_at_by_circuit", {})
            )
        },
        alerts=_alerts_from_raw(raw.get("alerts", [])),
        nilm_signatures=_dict_of_list_dicts(raw.get("nilm_signatures", {})),
        nilm_unknown_loads_by_circuit=_dict_of_dicts(
            raw.get("nilm_unknown_loads_by_circuit", {})
        ),
        nilm_unmatched_edges_by_circuit=_dict_of_list_dicts_including_empty(
            raw.get("nilm_unmatched_edges_by_circuit", {})
        ),
        nilm_session_history_by_circuit=nilm_session_history,
        nilm_session_history_ingress_by_circuit=nilm_session_history_ingress,
        nilm_known_load_attributions_by_circuit=(
            _nilm_known_load_attributions_from_raw(
                raw.get("nilm_known_load_attributions_by_circuit", {})
            )
        ),
        nilm_label_intervals_by_circuit=_dict_of_list_dicts(
            raw.get("nilm_label_intervals_by_circuit", {})
        ),
        nilm_appliance_assignments_by_circuit=_dict_of_list_dicts(
            raw.get("nilm_appliance_assignments_by_circuit", {})
        ),
        weather_context_by_circuit=_dict_of_dicts(
            raw.get("weather_context_by_circuit", {})
        ),
        weather_context_history_by_circuit=_dict_of_list_dicts(
            raw.get("weather_context_history_by_circuit", {})
        ),
        rain_pump_context_by_circuit=_dict_of_dicts(
            raw.get("rain_pump_context_by_circuit", {})
        ),
        water_flow_context_by_circuit=_dict_of_dicts(
            raw.get("water_flow_context_by_circuit", {})
        ),
        water_context_history_by_circuit=_dict_of_list_dicts(
            raw.get("water_context_history_by_circuit", {})
        ),
        hvac_response_history_by_stream=_dict_of_list_dicts(
            raw.get("hvac_response_history_by_stream", {})
        ),
        hvac_response_context_by_stream=_dict_of_dicts(
            raw.get("hvac_response_context_by_stream", {})
        ),
        hvac_correlation_history_by_circuit=_dict_of_list_dicts(
            raw.get("hvac_correlation_history_by_circuit", {})
        ),
        hvac_baseline_era_by_stream={
            str(stream_id): str(era)
            for stream_id, era in _mapping_items(
                raw.get("hvac_baseline_era_by_stream", {})
            )
            if str(stream_id) and str(era)
        },
        contextual_baseline_samples_by_circuit=(
            _contextual_samples_by_circuit(
                raw.get("contextual_baseline_samples_by_circuit", {})
            )
        ),
        contextual_baselines_by_circuit=_contextual_baselines_by_circuit(
            raw.get("contextual_baselines_by_circuit", {})
        ),
        sensitivity_by_circuit={
            str(circuit_id): normalize_sensitivity(sensitivity)
            for circuit_id, sensitivity in _mapping_items(
                raw.get("sensitivity_by_circuit", {})
            )
        },
        nilm_detection_sensitivity_by_circuit={
            str(circuit_id): normalize_nilm_detection_sensitivity(sensitivity)
            for circuit_id, sensitivity in _mapping_items(
                raw.get("nilm_detection_sensitivity_by_circuit", {})
            )
        },
        maintenance_by_circuit=_dict_of_dicts(
            raw.get("maintenance_by_circuit", {}),
        ),
        alert_feedback=_dict_of_dicts(raw.get("alert_feedback", {})),
        energy_usage_settings_by_circuit=_dict_of_dicts(
            raw.get("energy_usage_settings_by_circuit", {}),
        ),
        energy_goal_settings_by_circuit=_dict_of_dicts(
            raw.get("energy_goal_settings_by_circuit", {}),
        ),
        activity_alert_settings_by_circuit=_dict_of_dicts(
            raw.get("activity_alert_settings_by_circuit", {}),
        ),
        energy_usage_by_circuit=_dict_of_dicts(
            raw.get("energy_usage_by_circuit", {}),
        ),
        billing_settings_by_circuit=_dict_of_dicts(
            raw.get("billing_settings_by_circuit", {}),
        ),
        billing_by_circuit=_dict_of_dicts(raw.get("billing_by_circuit", {})),
        cost_settings_by_circuit=_dict_of_dicts(
            raw.get("cost_settings_by_circuit", {}),
        ),
        cost_by_circuit=_dict_of_dicts(raw.get("cost_by_circuit", {})),
        demand_settings_by_circuit=_dict_of_dicts(
            raw.get("demand_settings_by_circuit", {}),
        ),
        demand_by_circuit=_dict_of_dicts(raw.get("demand_by_circuit", {})),
        capacity_settings_by_circuit=_dict_of_dicts(
            raw.get("capacity_settings_by_circuit", {}),
        ),
        leg_imbalance_settings_by_circuit=_dict_of_dicts(
            raw.get("leg_imbalance_settings_by_circuit", {}),
        ),
        mains_power_quality_settings_by_circuit=_dict_of_dicts(
            raw.get("mains_power_quality_settings_by_circuit", {}),
        ),
        metric_consistency_settings_by_circuit=_dict_of_dicts(
            raw.get("metric_consistency_settings_by_circuit", {}),
        ),
        balance_settings_by_circuit=_dict_of_dicts(
            raw.get("balance_settings_by_circuit", {}),
        ),
        solar_flow_settings_by_circuit=_dict_of_dicts(
            raw.get("solar_flow_settings_by_circuit", {}),
        ),
        utility_comparison_settings_by_circuit=_dict_of_dicts(
            raw.get("utility_comparison_settings_by_circuit", {}),
        ),
        standby_settings_by_circuit=_dict_of_dicts(
            raw.get("standby_settings_by_circuit", {}),
        ),
        standby_by_circuit=_dict_of_dicts(raw.get("standby_by_circuit", {})),
        operating_detection_settings_by_circuit=_dict_of_dicts(
            raw.get("operating_detection_settings_by_circuit", {}),
        ),
        settings_recommendations=_recommendations_from_raw(
            raw.get("settings_recommendations", {})
        ),
        settings_recommendation_decisions=_recommendation_decisions_from_raw(
            raw.get("settings_recommendation_decisions", {})
        ),
        settings_recommendation_notification_episode_key=_episode_key_from_raw(
            raw.get("settings_recommendation_notification_episode_key", [])
        ),
        appliance_notification_preferences=_dict_of_dicts(
            raw.get("appliance_notification_preferences", {})
        ),
        notification_delivery_state=_json_mapping(
            raw.get("notification_delivery_state", {})
        ),
        weekly_digest_settings=_json_mapping(
            raw.get("weekly_digest_settings", {})
        ),
        appliance_schedule_settings=_dict_of_dicts(
            raw.get("appliance_schedule_settings", {})
        ),
        appliance_schedule_evidence=_dict_of_dicts(
            raw.get("appliance_schedule_evidence", {})
        ),
        dashboard_status=_dict_of_jsonable_values(raw.get("dashboard_status", {})),
    )
    migrate_nilm_confidence_semantics(
        data.nilm_appliance_assignments_by_circuit,
        data.nilm_signatures,
        data.nilm_session_history_by_circuit,
    )
    return data


def _copy_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_payload(item) for item in value]
    return value


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return _copy_payload(value)


def _events_from_raw(values: Any) -> list[CircuitEvent]:
    events: list[CircuitEvent] = []
    for value in _list_items(values):
        if not isinstance(value, Mapping):
            continue
        try:
            events.append(event_from_dict(dict(value)))
        except (KeyError, TypeError, ValueError):
            continue
    return events


def _baselines_from_raw(values: Any) -> dict[str, BaselineStats]:
    baselines: dict[str, BaselineStats] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, Mapping):
            continue
        try:
            baselines[str(key)] = baseline_from_dict(dict(value))
        except (KeyError, TypeError, ValueError):
            continue
    return baselines


def _alerts_from_raw(values: Any) -> list[AlertEvidence]:
    alerts: list[AlertEvidence] = []
    for value in _list_items(values):
        if not isinstance(value, Mapping):
            continue
        try:
            alerts.append(alert_from_dict(dict(value)))
        except (KeyError, TypeError, ValueError):
            continue
    return alerts


def _recommendations_from_raw(values: Any) -> dict[str, SettingRecommendation]:
    recommendations: dict[str, SettingRecommendation] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, Mapping):
            continue
        try:
            recommendations[str(key)] = recommendation_from_dict(value)
        except (KeyError, TypeError, ValueError):
            continue
    return recommendations


def _recommendation_decisions_from_raw(
    values: Any,
) -> dict[str, RecommendationDecision]:
    decisions: dict[str, RecommendationDecision] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, Mapping):
            continue
        try:
            decisions[str(key)] = decision_from_dict(value)
        except (KeyError, TypeError, ValueError):
            continue
    return decisions


def _episode_key_from_raw(values: Any) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(str(item) for item in value)
        for value in _list_items(values)
        if isinstance(value, list | tuple)
    )


def _mapping_items(values: Any) -> Iterable[tuple[Any, Any]]:
    if not isinstance(values, Mapping):
        return ()
    return values.items()


def _list_items(values: Any) -> Iterable[Any]:
    return values if isinstance(values, list) else ()


def prune_events(
    data: FeatureStoreData,
    retention_mode: RetentionMode,
    now: datetime,
    *,
    contextual_sample_cap_per_circuit: int | None = None,
    contextual_bucket_cap_per_feature: int | None = None,
) -> FeatureStoreData:
    """Return a new payload with events pruned according to retention mode."""
    cutoff = now - RETENTION_WINDOWS[retention_mode]
    contextual_samples, contextual_stats = prune_contextual_baseline_state(
        data.contextual_baseline_samples_by_circuit,
        data.contextual_baselines_by_circuit,
        retention_mode,
        now,
        contextual_sample_cap_per_circuit=contextual_sample_cap_per_circuit,
        contextual_bucket_cap_per_feature=contextual_bucket_cap_per_feature,
    )
    return FeatureStoreData(
        events=[event for event in data.events if event.timestamp >= cutoff],
        baselines=data.baselines,
        learning_started_at_by_circuit=data.learning_started_at_by_circuit,
        alerts=data.alerts,
        nilm_signatures=data.nilm_signatures,
        nilm_unknown_loads_by_circuit=data.nilm_unknown_loads_by_circuit,
        nilm_unmatched_edges_by_circuit=data.nilm_unmatched_edges_by_circuit,
        nilm_session_history_by_circuit=data.nilm_session_history_by_circuit,
        nilm_known_load_attributions_by_circuit=(
            data.nilm_known_load_attributions_by_circuit
        ),
        nilm_label_intervals_by_circuit=data.nilm_label_intervals_by_circuit,
        nilm_appliance_assignments_by_circuit=(
            data.nilm_appliance_assignments_by_circuit
        ),
        weather_context_by_circuit=data.weather_context_by_circuit,
        weather_context_history_by_circuit=data.weather_context_history_by_circuit,
        rain_pump_context_by_circuit=data.rain_pump_context_by_circuit,
        water_flow_context_by_circuit=data.water_flow_context_by_circuit,
        water_context_history_by_circuit=data.water_context_history_by_circuit,
        hvac_response_history_by_stream=data.hvac_response_history_by_stream,
        hvac_response_context_by_stream=data.hvac_response_context_by_stream,
        hvac_correlation_history_by_circuit=(
            data.hvac_correlation_history_by_circuit
        ),
        hvac_baseline_era_by_stream=data.hvac_baseline_era_by_stream,
        contextual_baseline_samples_by_circuit=contextual_samples,
        contextual_baselines_by_circuit=contextual_stats,
        sensitivity_by_circuit=data.sensitivity_by_circuit,
        nilm_detection_sensitivity_by_circuit=(
            data.nilm_detection_sensitivity_by_circuit
        ),
        maintenance_by_circuit=data.maintenance_by_circuit,
        alert_feedback=data.alert_feedback,
        energy_usage_settings_by_circuit=data.energy_usage_settings_by_circuit,
        energy_goal_settings_by_circuit=data.energy_goal_settings_by_circuit,
        activity_alert_settings_by_circuit=(
            data.activity_alert_settings_by_circuit
        ),
        energy_usage_by_circuit=data.energy_usage_by_circuit,
        billing_settings_by_circuit=data.billing_settings_by_circuit,
        billing_by_circuit=data.billing_by_circuit,
        cost_settings_by_circuit=data.cost_settings_by_circuit,
        cost_by_circuit=data.cost_by_circuit,
        demand_settings_by_circuit=data.demand_settings_by_circuit,
        demand_by_circuit=data.demand_by_circuit,
        capacity_settings_by_circuit=data.capacity_settings_by_circuit,
        leg_imbalance_settings_by_circuit=data.leg_imbalance_settings_by_circuit,
        mains_power_quality_settings_by_circuit=(
            data.mains_power_quality_settings_by_circuit
        ),
        metric_consistency_settings_by_circuit=(
            data.metric_consistency_settings_by_circuit
        ),
        balance_settings_by_circuit=data.balance_settings_by_circuit,
        solar_flow_settings_by_circuit=data.solar_flow_settings_by_circuit,
        utility_comparison_settings_by_circuit=(
            data.utility_comparison_settings_by_circuit
        ),
        standby_settings_by_circuit=data.standby_settings_by_circuit,
        standby_by_circuit=data.standby_by_circuit,
        operating_detection_settings_by_circuit=(
            data.operating_detection_settings_by_circuit
        ),
        settings_recommendations=data.settings_recommendations,
        settings_recommendation_decisions=data.settings_recommendation_decisions,
        settings_recommendation_notification_episode_key=(
            data.settings_recommendation_notification_episode_key
        ),
        appliance_notification_preferences=data.appliance_notification_preferences,
        notification_delivery_state=data.notification_delivery_state,
        weekly_digest_settings=data.weekly_digest_settings,
        appliance_schedule_settings=data.appliance_schedule_settings,
        appliance_schedule_evidence=data.appliance_schedule_evidence,
        dashboard_status=data.dashboard_status,
    )


def prune_contextual_baseline_state(
    samples_by_circuit: dict[str, list[dict[str, Any]]],
    baselines_by_circuit: dict[str, dict[str, Any]],
    retention_mode: RetentionMode,
    now: datetime,
    *,
    contextual_sample_cap_per_circuit: int | None = None,
    contextual_bucket_cap_per_feature: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Prune contextual samples and cap retained stats buckets."""
    cutoff = now - RETENTION_WINDOWS[retention_mode]
    sample_cap = (
        CONTEXTUAL_SAMPLE_CAPS[retention_mode]
        if contextual_sample_cap_per_circuit is None
        else max(int(contextual_sample_cap_per_circuit), 0)
    )
    bucket_cap = (
        CONTEXTUAL_BUCKET_CAPS[retention_mode]
        if contextual_bucket_cap_per_feature is None
        else max(int(contextual_bucket_cap_per_feature), 0)
    )
    return (
        _prune_contextual_samples(samples_by_circuit, cutoff, sample_cap),
        _prune_contextual_baselines(baselines_by_circuit, bucket_cap),
    )


class FeatureStore:
    """Home Assistant Store wrapper for analyzer feature data."""

    def __init__(self: Self, hass: HomeAssistant, entry_id: str) -> None:
        from homeassistant.helpers.storage import Store as HAStore

        class _CurrentOnlyStore(HAStore):
            async def _async_migrate_func(
                self,
                old_major_version: int,
                old_minor_version: int,
                old_data: dict[str, Any],
            ) -> dict[str, Any]:
                if old_major_version == STORAGE_VERSION - 1:
                    _LOGGER.info(
                        "Migrating %s storage schema %s.%s to schema %s",
                        self.key,
                        old_major_version,
                        old_minor_version,
                        STORAGE_VERSION,
                    )
                    return old_data
                _LOGGER.warning(
                    "Discarding unsupported %s storage schema %s.%s; "
                    "starting with schema %s",
                    self.key,
                    old_major_version,
                    old_minor_version,
                    STORAGE_VERSION,
                )
                return {}

        self._hass = hass
        self._store: Store[dict[str, Any]] = _CurrentOnlyStore(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry_id}",
        )
        self.data = FeatureStoreData()

    async def async_load(self: Self) -> FeatureStoreData:
        """Load stored data and return the in-memory payload."""
        self.data = feature_store_data_from_dict(await self._store.async_load())
        return self.data

    async def async_save(self: Self) -> None:
        """Persist the current payload without serializing on the event loop."""
        data = await self._hass.async_add_executor_job(
            feature_store_data_to_dict,
            self.data,
        )
        await self._store.async_save(data)


def _features_to_dict(features: Any) -> dict[str, Any]:
    return {
        str(key): _json_safe_feature_value(value)
        for key, value in dict(features).items()
    }


def _json_safe_feature_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _dict_of_dicts(values: Any) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    for key, value in _mapping_items(values):
        if isinstance(value, Mapping):
            sanitized[str(key)] = dict(value)
    return sanitized


def _dict_of_jsonable_values(values: Any) -> dict[str, Any]:
    return {
        str(key): _json_safe_feature_value(value)
        for key, value in _mapping_items(values)
    }


def _dict_of_list_dicts(values: Any) -> dict[str, list[dict[str, Any]]]:
    sanitized: dict[str, list[dict[str, Any]]] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, list):
            continue
        items = [dict(item) for item in value if isinstance(item, Mapping)]
        if items:
            sanitized[str(key)] = items
    return sanitized


def _nilm_session_history_from_raw(
    values: Any,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, int | bool]],
]:
    """Bound NILM history before generic storage materialization."""

    histories: dict[str, list[dict[str, Any]]] = {}
    ingress_by_circuit: dict[str, dict[str, int | bool]] = {}
    for key, value in _mapping_items(values):
        rows, ingress = _sanitize_nilm_session_history_ingress(
            value,
            max_source_rows=NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
        )
        circuit_id = str(key)
        if rows:
            histories[circuit_id] = rows
        if ingress["was_truncated"] or not ingress["identity_aliases_complete"]:
            ingress_by_circuit[circuit_id] = ingress
    return histories, ingress_by_circuit


def _nilm_known_load_attributions_from_raw(
    values: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Materialize a bounded, deterministic known-load attribution ledger."""

    attributions: dict[str, list[dict[str, Any]]] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, list):
            continue
        rows: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            attribution_id = str(item.get("attribution_id", "")).strip()
            timestamp = str(item.get("timestamp", "")).strip()
            if not attribution_id or not timestamp:
                continue
            row = dict(item)
            row["attribution_id"] = attribution_id
            row["timestamp"] = timestamp
            rejected = item.get("rejected_candidate_summaries", ())
            row["rejected_candidate_summaries"] = [
                dict(candidate)
                for candidate in rejected
                if isinstance(candidate, Mapping)
            ][:4] if isinstance(rejected, list | tuple) else []
            rows.append(row)
        if rows:
            attributions[str(key)] = sorted(
                rows,
                key=lambda row: (
                    str(row["timestamp"]),
                    str(row["attribution_id"]),
                ),
                reverse=True,
            )[:NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT]
    return attributions


def _dict_of_list_dicts_including_empty(
    values: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Sanitize list payloads while preserving a stored empty-list marker."""
    sanitized: dict[str, list[dict[str, Any]]] = {}
    for key, value in _mapping_items(values):
        if not isinstance(value, list):
            continue
        sanitized[str(key)] = [
            dict(item) for item in value if isinstance(item, Mapping)
        ]
    return sanitized


def _contextual_samples_by_circuit(values: Any) -> dict[str, list[dict[str, Any]]]:
    sanitized: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(values, Mapping):
        return sanitized
    for circuit_id, raw_samples in values.items():
        samples: list[dict[str, Any]] = []
        if not isinstance(raw_samples, list):
            continue
        for raw_sample in raw_samples:
            if not isinstance(raw_sample, Mapping):
                continue
            sample = contextual_sample_from_dict(str(circuit_id), raw_sample)
            if sample is None:
                continue
            payload = dict(raw_sample)
            payload["feature"] = sample.feature
            payload["value"] = sample.value
            payload["context"] = sample.context.as_dict()
            payload["timestamp"] = sample.timestamp.isoformat()
            samples.append(payload)
        if samples:
            sanitized[str(circuit_id)] = samples
    return sanitized


def _contextual_baselines_by_circuit(values: Any) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    if not isinstance(values, Mapping):
        return sanitized
    for circuit_id, raw_stats_by_key in values.items():
        if not isinstance(raw_stats_by_key, Mapping):
            continue
        stats_by_key: dict[str, Any] = {}
        for key, raw_stats in raw_stats_by_key.items():
            if not isinstance(raw_stats, Mapping):
                continue
            context = raw_stats.get("context", {})
            if not isinstance(context, Mapping):
                continue
            try:
                stats_by_key[str(key)] = {
                    "feature": str(raw_stats["feature"]),
                    "context_fingerprint": str(raw_stats["context_fingerprint"]),
                    "context": {str(k): str(v) for k, v in context.items()},
                    "sample_count": _contextual_stats_sample_count_value(
                        raw_stats["sample_count"]
                    ),
                    "median": float(raw_stats["median"]),
                    "mad": float(raw_stats["mad"]),
                    "p10": float(raw_stats["p10"]),
                    "p90": float(raw_stats["p90"]),
                    "confidence": float(raw_stats["confidence"]),
                    "fallback_level": str(
                        raw_stats.get("fallback_level", "exact_context")
                    ),
                    "first_seen": raw_stats.get("first_seen"),
                    "last_seen": raw_stats.get("last_seen"),
                }
            except (KeyError, TypeError, ValueError):
                continue
        if stats_by_key:
            sanitized[str(circuit_id)] = stats_by_key
    return sanitized


def _prune_contextual_samples(
    samples_by_circuit: dict[str, list[dict[str, Any]]],
    cutoff: datetime,
    cap_per_circuit: int,
) -> dict[str, list[dict[str, Any]]]:
    pruned: dict[str, list[dict[str, Any]]] = {}
    for circuit_id, raw_samples in samples_by_circuit.items():
        retained: list[dict[str, Any]] = []
        for raw_sample in raw_samples:
            sample = contextual_sample_from_dict(circuit_id, raw_sample)
            if sample is None or sample.timestamp < cutoff:
                continue
            retained.append(dict(raw_sample))
        retained.sort(key=lambda item: str(item.get("timestamp", "")))
        if cap_per_circuit:
            retained = retained[-cap_per_circuit:]
        if retained:
            pruned[circuit_id] = retained
    return pruned


def _prune_contextual_baselines(
    baselines_by_circuit: dict[str, dict[str, Any]],
    cap_per_feature: int,
) -> dict[str, dict[str, Any]]:
    if cap_per_feature <= 0:
        return {}

    changed = False
    pruned: dict[str, dict[str, Any]] = {}
    for circuit_id, stats_by_key in baselines_by_circuit.items():
        grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for key, stats in stats_by_key.items():
            if not isinstance(stats, Mapping):
                changed = True
                continue
            feature = str(stats.get("feature") or str(key).split("|", 1)[0])
            grouped.setdefault(feature, []).append((str(key), dict(stats)))

        retained: dict[str, dict[str, Any]] = {}
        for feature_stats in grouped.values():
            ranked = sorted(
                feature_stats,
                key=lambda item: (
                    _contextual_stats_sample_count(item[1]),
                    _contextual_stats_last_seen(item[1]),
                ),
                reverse=True,
            )
            if len(ranked) > cap_per_feature:
                changed = True
            retained.update(dict(ranked[:cap_per_feature]))

        if retained:
            pruned[str(circuit_id)] = retained
        if len(retained) != len(stats_by_key):
            changed = True

    return pruned if changed else baselines_by_circuit


def _contextual_stats_sample_count(stats: Mapping[str, Any]) -> float:
    try:
        return float(
            max(
                _contextual_stats_sample_count_value(stats.get("sample_count", 0)),
                0,
            )
        )
    except (TypeError, ValueError):
        return 0.0


def _contextual_stats_sample_count_value(value: Any) -> int | float:
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("contextual sample count must be finite")
    if parsed < 0.0:
        parsed = 0.0
    return int(parsed) if parsed.is_integer() else parsed


def _contextual_stats_last_seen(stats: Mapping[str, Any]) -> datetime:
    value = stats.get("last_seen") or stats.get("first_seen")
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min
