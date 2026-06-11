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
    detail = {
        "alert_id": notification_id_for_alert(alert),
        "circuit_id": alert.circuit_id,
        "feature": feature,
        "feature_name": friendly_feature_name(feature),
        "severity": alert.severity.value,
        "message": alert.message,
        "baseline_value": alert.baseline_value,
        "observed_value": alert.observed_value,
        "change_ratio": alert.change_ratio,
        "percent_change": round(alert.change_ratio * 100.0, 3),
        "repeated_count": alert.repeated_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "time_window": (
            f"{first_seen} to {last_seen}" if first_seen and last_seen else None
        ),
        "contributing_metrics": {
            str(key): value for key, value in sorted(alert.features.items())
        },
        "evidence_path": alert_evidence_path(alert, dashboard_path=dashboard_path),
        "graph_entities": list(alert_graph_entities(alert, config)),
        "source_entities": list(alert_source_entities(config)),
        "graph_window_start": graph_window_start.isoformat(),
        "graph_window_end": graph_window_end.isoformat(),
    }
    if feature_needs_electrical_safety_notice(feature):
        detail["safety_notice"] = ELECTRICAL_SAFETY_NOTICE
    return detail


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

    return {
        "required_sensors_present": required_present,
        "optional_sensors_present": optional_present,
        "numeric_states_valid": not _has_issue_containing(
            quality_issues,
            "non_numeric",
        ),
        "source_data_fresh": not _has_issue_containing(quality_issues, "stale"),
        "quality_issues": quality_issues,
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
