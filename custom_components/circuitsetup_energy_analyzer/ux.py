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
from .localized_text import translation_text
from .models import (
    AlertEvidence,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitSample,
    EventType,
    SensorRole,
)
from .notifications import (
    ALERT_VALUE_METADATA,
    notification_id_for_alert,
)
from .notifications import (
    format_alert_value as _format_alert_value,
)
from .profiles import get_profile_definition
from .safety import feature_needs_electrical_safety_notice


def _ux_text(*keys: str, **values: Any) -> str:
    text = translation_text("ux", *keys)
    return text.format(**values) if values else text


SENSITIVITY_VALUES = frozenset({"quiet", "balanced", "sensitive"})
POLICY_NAME_BY_SENSITIVITY = {
    "quiet": "low",
    "balanced": "standard",
    "sensitive": "high",
}
SENSITIVITY_LABELS = {
    key: _ux_text("sensitivity_labels", key)
    for key in ("quiet", "balanced", "sensitive")
}
POWER_QUALITY_RELATIONSHIP_METRICS = (
    "reactive_to_real_ratio",
    "reactive_power",
    "power_factor_deficit",
    "power_factor",
    "apparent_to_real_ratio",
    "apparent_power",
)
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
    key: _ux_text("feature_tokens", key)
    for key in ("hvac", "kwh", "nilm", "pf", "s", "va", "var")
}


def normalize_sensitivity(value: Any) -> str:
    """Return a supported sensitivity preset."""
    normalized = str(value).strip().lower()
    return normalized if normalized in SENSITIVITY_VALUES else "balanced"


def alert_policy_name_for_sensitivity(value: Any) -> str:
    """Return the existing alert policy name for a friendly sensitivity value."""
    return POLICY_NAME_BY_SENSITIVITY[normalize_sensitivity(value)]


def friendly_sensitivity_label(value: Any) -> str:
    """Return the user-facing label for a sensitivity value."""
    return SENSITIVITY_LABELS[normalize_sensitivity(value)]


def canonicalize_sensitivity_config(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a mutable config copy using canonical sensitivity preset names."""
    copied = mutable_config_copy(value)
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


def mutable_config_copy(value: Any) -> Any:
    """Return a mutable plain-Python copy of nested config mappings."""
    if isinstance(value, Mapping):
        return {key: mutable_config_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mutable_config_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mutable_config_copy(item) for item in value)
    return value


CONF_SENSITIVITY_KEY = "sensitivity"
CONF_ADVANCED_SETTINGS_KEY = "advanced_settings"


def friendly_feature_name(value: Any) -> str:
    """Return a human-readable label for an internal alert feature key."""
    raw = str(value or "").strip()
    if not raw:
        return _ux_text("feature_fallback")
    words = []
    for token in raw.replace("-", "_").split("_"):
        token = token.strip()
        if not token:
            continue
        words.append(FEATURE_TOKEN_LABELS.get(token.lower(), token.title()))
    return " ".join(words) or _ux_text("feature_fallback")


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
    value_metric = _alert_value_metric(alert, feature)
    value_label, value_unit, value_format = ALERT_VALUE_METADATA.get(
        value_metric,
        (friendly_feature_name(value_metric), "", "number"),
    )
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
        "value_metric": value_metric,
        "value_label": value_label,
        "value_unit": value_unit,
        "value_format": value_format,
        "severity": alert.severity.value,
        "message": alert.message,
        "what_happened": _alert_what_happened(
            alert,
            value_label=value_label,
            value_unit=value_unit,
            value_format=value_format,
        ),
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
            _ux_text("time_window", first_seen=first_seen, last_seen=last_seen)
            if first_seen and last_seen
            else None
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
        detail["safety_notice"] = translation_text("safety", "electrical_notice")
    if alert.feedback_status is not None:
        detail["feedback_status"] = alert.feedback_status
    if alert.feedback_effect is not None:
        detail["feedback_effect"] = alert.feedback_effect
    if alert.feedback_expires_at is not None:
        detail["feedback_expires_at"] = alert.feedback_expires_at.isoformat()
    if alert.matching_feedback_fingerprint is not None:
        detail["matching_feedback_fingerprint"] = alert.matching_feedback_fingerprint
    if alert.adjusted_min_repeated is not None:
        detail["adjusted_min_repeated"] = alert.adjusted_min_repeated
    return detail


def _alert_value_metric(alert: AlertEvidence, feature: str) -> str:
    explicit = str(alert.value_metric).strip()
    return explicit or feature


def _alert_what_happened(
    alert: AlertEvidence,
    *,
    value_label: str,
    value_unit: str,
    value_format: str,
) -> str:
    return _ux_text(
        "what_happened",
        value_label=value_label,
        observed_value=_format_alert_value(
            alert.observed_value,
            value_unit,
            value_format,
        ),
        baseline_value=_format_alert_value(
            alert.baseline_value,
            value_unit,
            value_format,
        ),
    )


def _alert_why_it_matters(feature: str) -> str:
    lower = feature.lower()
    if "capacity" in lower or "demand" in lower:
        return _ux_text("why_it_matters", "capacity")
    if "reactive" in lower or "power_factor" in lower or lower.endswith("_pf"):
        return _ux_text("why_it_matters", "power_quality")
    if "energy" in lower or "kwh" in lower:
        return _ux_text("why_it_matters", "energy")
    if "cycle" in lower or "activity" in lower:
        return _ux_text("why_it_matters", "activity")
    return _ux_text("why_it_matters", "default")


def _alert_what_to_check_first(feature: str) -> str:
    lower = feature.lower()
    if "capacity" in lower or "demand" in lower:
        return _ux_text("what_to_check_first", "capacity")
    if "leg" in lower or "phase" in lower:
        return _ux_text("what_to_check_first", "phase")
    if "reactive" in lower or "power_factor" in lower or lower.endswith("_pf"):
        return _ux_text("what_to_check_first", "power_quality")
    if "energy" in lower or "kwh" in lower:
        return _ux_text("what_to_check_first", "energy")
    if "cycle" in lower or "activity" in lower:
        return _ux_text("what_to_check_first", "activity")
    return _ux_text("what_to_check_first", "default")


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
    required_present = roles_with_values >= REQUIRED_ROLES
    configured_optional = configured_roles & OPTIONAL_ROLES
    optional_present = (
        bool(configured_optional) and configured_optional <= roles_with_values
    )
    quality_issues = list(getattr(sample, "quality_issues", ())) if sample else []
    quality_issue_preview = quality_issues[:MAX_QUALITY_ISSUES]

    return {
        "required_sensors_present": required_present,
        "optional_sensors_present": optional_present,
        "numeric_states_valid": not _has_any_issue_containing(
            quality_issues,
            ("non_numeric", "non_finite"),
        ),
        "source_data_fresh": not _has_any_issue_containing(
            quality_issues,
            ("stale", "future_timestamp", "naive_timestamp"),
        ),
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
        "days_required": max(
            get_profile_definition(config.appliance_profile).minimum_learning_days,
            1,
        ),
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
        return "needs_data", _ux_text("health_summary", "needs_data")
    if paused:
        return "paused", _ux_text("health_summary", "paused")
    if active_alerts:
        return "possible_issue", _ux_text("health_summary", "possible_issue")
    if observations:
        return "observation", _ux_text("health_summary", "observation")
    if nilm_review_count > 0:
        return "nilm_review", _ux_text("health_summary", "nilm_review")
    if mixed:
        return "mixed_observation", _ux_text("health_summary", "mixed_observation")
    if learning:
        return "learning", _ux_text("health_summary", "learning")
    return "ready", _ux_text("health_summary", "ready")


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


def _has_any_issue_containing(
    quality_issues: Sequence[str],
    texts: Sequence[str],
) -> bool:
    return any(_has_issue_containing(quality_issues, text) for text in texts)


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
