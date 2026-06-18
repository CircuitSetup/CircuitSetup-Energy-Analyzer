from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .alert_links import (
    DEFAULT_ALERT_EVIDENCE_PATH,
    alert_evidence_path,
    alert_graph_entities,
    alert_graph_window,
    alert_source_entities,
)
from .models import (
    AlertEvidence,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitSample,
    EventType,
    SensorRole,
)
from .notifications import notification_id_for_alert
from .safety import ELECTRICAL_SAFETY_NOTICE, feature_needs_electrical_safety_notice

FRIENDLY_SENSITIVITY_ALIASES = {
    "low": "quiet",
    "quiet": "quiet",
    "standard": "balanced",
    "balanced": "balanced",
    "high": "sensitive",
    "sensitive": "sensitive",
}
POLICY_SENSITIVITY_ALIASES = {
    "quiet": "low",
    "balanced": "standard",
    "sensitive": "high",
}
SENSITIVITY_LABELS = {
    "quiet": "Quiet",
    "balanced": "Balanced",
    "sensitive": "Sensitive",
}
MAX_CONTRIBUTING_METRICS = 5
MAX_ALERT_SOURCE_ENTITIES = 5
MAX_QUALITY_ISSUES = 5
REQUIRED_ROLES = {SensorRole.REAL_POWER}
OPTIONAL_ROLES = {
    SensorRole.VOLTAGE,
    SensorRole.CURRENT,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.FREQUENCY,
}
ROLE_SAMPLE_FIELDS = {
    SensorRole.VOLTAGE: "voltage",
    SensorRole.CURRENT: "current",
    SensorRole.REAL_POWER: "real_power",
    SensorRole.REACTIVE_POWER: "reactive_power",
    SensorRole.APPARENT_POWER: "apparent_power",
    SensorRole.POWER_FACTOR: "power_factor",
    SensorRole.FREQUENCY: "frequency",
    SensorRole.ENERGY: "energy",
}
FEATURE_TOKEN_LABELS = {
    "hvac": "HVAC",
    "kwh": "kWh",
    "nilm": "NILM",
    "pf": "PF",
    "s": "Seconds",
    "va": "VA",
    "var": "VAR",
}


def normalize_sensitivity(value: Any) -> str:
    """Return the friendly sensitivity preset for a user or legacy value."""
    return FRIENDLY_SENSITIVITY_ALIASES.get(str(value).strip().lower(), "balanced")


def alert_policy_name_for_sensitivity(value: Any) -> str:
    """Return the existing alert policy name for a friendly sensitivity value."""
    return POLICY_SENSITIVITY_ALIASES[normalize_sensitivity(value)]


def friendly_sensitivity_label(value: Any) -> str:
    """Return the user-facing label for a friendly or legacy sensitivity value."""
    return SENSITIVITY_LABELS[normalize_sensitivity(value)]


def canonicalize_sensitivity_config(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a mutable config copy using canonical sensitivity preset names."""
    copied = _mutable_config_copy(value)
    if CONF_SENSITIVITY_KEY in copied:
        copied[CONF_SENSITIVITY_KEY] = normalize_sensitivity(
            copied[CONF_SENSITIVITY_KEY]
        )

    advanced_settings = copied.get(CONF_ADVANCED_SETTINGS_KEY)
    if isinstance(advanced_settings, Mapping):
        for settings in advanced_settings.values():
            if isinstance(settings, dict) and "preset" in settings:
                settings["preset"] = normalize_sensitivity(settings["preset"])

    return copied


CONF_SENSITIVITY_KEY = "sensitivity"
CONF_ADVANCED_SETTINGS_KEY = "advanced_settings"


def _mutable_config_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_config_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mutable_config_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mutable_config_copy(item) for item in value)
    return value


def friendly_feature_name(value: Any) -> str:
    """Return a human-readable label for an internal alert feature key."""
    raw = str(value or "").strip()
    if not raw:
        return "Alert"
    words = []
    for token in raw.replace("-", "_").split("_"):
        token = token.strip()
        if not token:
            continue
        words.append(FEATURE_TOKEN_LABELS.get(token.lower(), token.title()))
    return " ".join(words) or "Alert"


def alert_evidence_detail(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Return JSON-safe detail suitable for dashboard attributes."""
    first_seen = _isoformat_or_none(alert.first_seen)
    last_seen = _isoformat_or_none(alert.last_seen)
    graph_window_start, graph_window_end = alert_graph_window(alert)
    feature = _alert_feature(alert)
    contributing_metrics = _bounded_contributing_metrics(
        alert.features,
        primary_key=feature,
    )
    source_entities = _bounded_source_entities(config)
    detail = {
        "alert_id": notification_id_for_alert(alert),
        "circuit_id": alert.circuit_id,
        "feature": feature,
        "feature_name": friendly_feature_name(feature),
        "severity": alert.severity.value,
        "message": alert.message,
        "what_happened": _alert_what_happened(alert, feature),
        "why_it_matters": _alert_why_it_matters(feature),
        "what_to_check_first": _alert_what_to_check_first(feature),
        "baseline_value": alert.baseline_value,
        "expected_value": alert.baseline_value,
        "observed_value": alert.observed_value,
        "threshold": _alert_threshold(alert.features),
        "sample_count": _alert_sample_count(alert.features),
        "change_ratio": alert.change_ratio,
        "percent_change": round(alert.change_ratio * 100.0, 3),
        "repeated_count": alert.repeated_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "time_window": (
            f"{first_seen} to {last_seen}" if first_seen and last_seen else None
        ),
        "contributing_metrics": contributing_metrics["metrics"],
        "contributing_metrics_count": contributing_metrics["count"],
        "contributing_metrics_has_more": contributing_metrics["has_more"],
        "contributing_metrics_omitted_count": contributing_metrics["omitted_count"],
        "evidence_path": alert_evidence_path(alert, dashboard_path=dashboard_path),
        "graph_entities": list(alert_graph_entities(alert, config)),
        "source_entities": source_entities["entities"],
        "source_entities_count": source_entities["count"],
        "source_entities_has_more": source_entities["has_more"],
        "source_entities_omitted_count": source_entities["omitted_count"],
        "graph_window_start": graph_window_start.isoformat(),
        "graph_window_end": graph_window_end.isoformat(),
    }
    if feature_needs_electrical_safety_notice(feature):
        detail["safety_notice"] = ELECTRICAL_SAFETY_NOTICE
    return detail


def _alert_what_happened(alert: AlertEvidence, feature: str) -> str:
    feature_name = friendly_feature_name(feature)
    return (
        f"{feature_name} changed from the learned or configured expectation. "
        f"Observed {alert.observed_value} compared with {alert.baseline_value}."
    )


def _alert_why_it_matters(feature: str) -> str:
    lower = feature.lower()
    if "capacity" in lower or "demand" in lower:
        return (
            "Demand and capacity evidence can show unusual operating load, but "
            "it is not an electrical safety verification."
        )
    if "reactive" in lower or "power_factor" in lower or lower.endswith("_pf"):
        return (
            "Changes in VAR, VA, or power factor can indicate that the load is "
            "operating differently than its learned pattern."
        )
    if "energy" in lower or "kwh" in lower:
        return (
            "Energy-use changes can identify appliances that are running longer "
            "or using more energy than their recent baseline."
        )
    if "cycle" in lower or "activity" in lower:
        return (
            "Run-cycle changes can show equipment that is running longer, "
            "short-cycling, or not running when expected."
        )
    return (
        "Repeated analyzer evidence means this circuit is no longer matching "
        "its recent learned or configured behavior."
    )


def _alert_what_to_check_first(feature: str) -> str:
    lower = feature.lower()
    if "capacity" in lower or "demand" in lower:
        return "Review the appliance load and configured breaker/capacity settings."
    if "leg" in lower or "phase" in lower:
        return "Verify both CTs, leg assignment, and dual-phase circuit mapping."
    if "reactive" in lower or "power_factor" in lower or lower.endswith("_pf"):
        return "Compare watts, VAR, VA, current, voltage, and power factor readings."
    if "energy" in lower or "kwh" in lower:
        return "Check the cumulative kWh sensor and recent appliance runtime."
    if "cycle" in lower or "activity" in lower:
        return "Review recent run cycles and whether the appliance is expected to run."
    return "Review the source sensors and recent activity for this circuit."


def _alert_threshold(features: Mapping[str, Any]) -> Any:
    for key in (
        "threshold",
        "threshold_w",
        "threshold_kwh",
        "limit",
        "limit_w",
        "warning_ratio",
        "tolerance_percent",
    ):
        if key in features:
            return features[key]
    return None


def _alert_sample_count(features: Mapping[str, Any]) -> Any:
    for key in ("sample_count", "samples", "window_sample_count", "cycle_count"):
        if key in features:
            return features[key]
    return None


def _bounded_contributing_metrics(
    features: Mapping[str, Any],
    *,
    primary_key: str | None = None,
) -> dict[str, Any]:
    items = [(str(key), value) for key, value in sorted(features.items())]
    preview_items: list[tuple[str, Any]] = []
    if primary_key is not None:
        for key, value in items:
            if key == primary_key:
                preview_items.append((key, value))
                break
    for key, value in items:
        if key == primary_key:
            continue
        if len(preview_items) >= MAX_CONTRIBUTING_METRICS:
            break
        preview_items.append((key, value))
    count = len(items)
    preview_count = len(preview_items)
    return {
        "metrics": dict(preview_items),
        "count": count,
        "has_more": count > preview_count,
        "omitted_count": max(count - preview_count, 0),
    }


def _bounded_source_entities(config: CircuitConfig | None) -> dict[str, Any]:
    source_entities = list(alert_source_entities(config))
    preview_entities = source_entities[:MAX_ALERT_SOURCE_ENTITIES]
    count = len(source_entities)
    preview_count = len(preview_entities)
    return {
        "entities": preview_entities,
        "count": count,
        "has_more": count > preview_count,
        "omitted_count": max(count - preview_count, 0),
    }


def data_quality_checklist(
    config: CircuitConfig,
    sample: CircuitSample | None,
) -> dict[str, Any]:
    """Summarize source sensor and sample coverage for one circuit."""
    configured_roles = {sensor.role for sensor in config.sensors}
    roles_with_values = _roles_with_sample_values(sample)
    required_present = REQUIRED_ROLES <= roles_with_values
    configured_optional = configured_roles & OPTIONAL_ROLES
    optional_present = (
        bool(configured_optional) and configured_optional <= roles_with_values
    )
    quality_issues = list(getattr(sample, "quality_issues", ())) if sample else []
    quality_issue_preview = quality_issues[:MAX_QUALITY_ISSUES]

    return {
        "required_sensors_present": required_present,
        "optional_sensors_present": optional_present,
        "numeric_states_valid": not _has_issue_containing(
            quality_issues,
            "non_numeric",
        ),
        "source_data_fresh": not _has_issue_containing(quality_issues, "stale"),
        "quality_issues": quality_issue_preview,
        "quality_issue_count": len(quality_issues),
        "quality_issues_has_more": len(quality_issues) > len(quality_issue_preview),
        "quality_issues_omitted_count": max(
            len(quality_issues) - len(quality_issue_preview),
            0,
        ),
        "quality_issues_full": quality_issues,
        "metric_roles_present": sorted(role.value for role in roles_with_values),
        "required_metric_coverage": _coverage(REQUIRED_ROLES, roles_with_values),
        "optional_metric_coverage": _coverage(configured_optional, roles_with_values),
        "missing_required_metric_roles": sorted(
            role.value for role in REQUIRED_ROLES - roles_with_values
        ),
        "missing_optional_metric_roles": sorted(
            role.value for role in configured_optional - roles_with_values
        ),
    }


def learning_progress(
    config: CircuitConfig,
    *,
    events: Sequence[CircuitEvent],
    baselines: Mapping[str, BaselineStats],
    baseline_buffer_counts: Mapping[str, int],
    now: datetime,
    learning: bool,
    suppression_reason: str | None,
) -> dict[str, Any]:
    """Summarize baseline learning progress for one circuit."""
    circuit_events = [
        event for event in events if event.circuit_id == config.circuit_id
    ]
    circuit_baselines = _values_for_circuit(config.circuit_id, baselines)
    pending_samples = _pending_samples_for_circuit(
        config.circuit_id,
        baseline_buffer_counts,
    )
    confidences = [baseline.confidence for baseline in circuit_baselines]

    return {
        "baseline_age_days": _baseline_age_days(circuit_events, now),
        "cycle_count": sum(
            1 for event in circuit_events if event.event_type is EventType.START
        ),
        "baseline_confidence": min(confidences) if confidences else 0.0,
        "learned_feature_count": len(circuit_baselines),
        "learning": learning,
        "alert_ready": not learning and suppression_reason is None,
        "suppression_reason": suppression_reason,
        "pending_feature_samples": pending_samples,
    }


def health_summary(
    *,
    data_quality_problem: bool = False,
    paused: bool = False,
    active_alerts: bool = False,
    observations: bool = False,
    nilm_review_count: int = 0,
    mixed: bool = False,
    learning: bool = False,
) -> tuple[str, str]:
    """Return the highest-priority dashboard health state."""
    if data_quality_problem:
        return "needs_data", "Needs data"
    if paused:
        return "paused", "Paused"
    if active_alerts:
        return "possible_issue", "Possible issue"
    if observations:
        return "observation", "Observation recorded"
    if nilm_review_count > 0:
        return "nilm_review", "NILM review"
    if mixed:
        return "mixed_observation", "Mixed observation"
    if learning:
        return "learning", "Learning"
    return "ready", "Ready"


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _roles_with_sample_values(sample: CircuitSample | None) -> set[SensorRole]:
    if sample is None:
        return set()
    return {
        role
        for role, field_name in ROLE_SAMPLE_FIELDS.items()
        if getattr(sample, field_name, None) is not None
    }


def _has_issue_containing(quality_issues: Sequence[str], text: str) -> bool:
    return any(text in issue for issue in quality_issues)


def _coverage(expected_roles: set[SensorRole], present_roles: set[SensorRole]) -> float:
    if not expected_roles:
        return 1.0
    return round(len(expected_roles & present_roles) / len(expected_roles), 3)


def _values_for_circuit(
    circuit_id: str,
    values: Mapping[str, BaselineStats],
) -> list[BaselineStats]:
    prefix = f"{circuit_id}:"
    return [value for key, value in values.items() if str(key).startswith(prefix)]


def _pending_samples_for_circuit(
    circuit_id: str,
    baseline_buffer_counts: Mapping[str, int],
) -> dict[str, int]:
    prefix = f"{circuit_id}:"
    return {
        str(key)[len(prefix) :]: int(value)
        for key, value in baseline_buffer_counts.items()
        if str(key).startswith(prefix)
    }


def _baseline_age_days(events: Sequence[CircuitEvent], now: datetime) -> float:
    if not events:
        return 0.0
    oldest = min(event.timestamp for event in events)
    return round((now - oldest).total_seconds() / 86400.0, 3)
