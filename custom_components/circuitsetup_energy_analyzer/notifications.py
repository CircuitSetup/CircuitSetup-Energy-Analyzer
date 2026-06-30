from __future__ import annotations

from math import isfinite
from typing import Any

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import DOMAIN
from .ids import readable_component as _readable_component
from .ids import tuple_id as _tuple_id
from .models import AlertEvidence, CircuitConfig
from .safety import ELECTRICAL_SAFETY_NOTICE, feature_needs_electrical_safety_notice


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    notification_key = alert.features.get("notification_key")
    if isinstance(notification_key, str) and notification_key.strip():
        return _tuple_id(
            f"{DOMAIN}_alert",
            alert.circuit_id,
            feature,
            notification_key.strip(),
        )
    return _tuple_id(f"{DOMAIN}_alert", alert.circuit_id, feature)


def settings_recommendation_notification_id(entry_id: str) -> str:
    """Return the persistent-notification id for suggested settings."""
    return f"{DOMAIN}_settings_recommendations_{_readable_component(entry_id)}"


def alert_notification_message(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> str:
    """Return Markdown body text for an alert persistent notification."""
    from .alert_links import alert_evidence_path

    lines = []
    if config is not None and config.name:
        lines.extend([f"**{config.name}**", ""])
    lines.append(alert.message)
    lines.extend(_nilm_source_lines(alert))
    lines.extend(
        [
            "",
            "[Open evidence graph]"
            f"({alert_evidence_path(alert, dashboard_path=dashboard_path)})",
            "",
            f"- Observed value: {alert.observed_value}",
            f"- {_comparison_value_label(alert)}: {alert.baseline_value}",
            f"- Repeated observations: {alert.repeated_count}",
        ]
    )
    if feature_needs_electrical_safety_notice(alert.feature):
        lines.extend(
            (
                "",
                f"Safety notice: {ELECTRICAL_SAFETY_NOTICE}",
            )
        )
    return "\n".join(lines)


def _nilm_source_lines(alert: AlertEvidence) -> list[str]:
    if not _is_nilm_estimated_alert(alert):
        return []

    lines: list[str] = []
    if "Estimated from mains power by NILM." not in alert.message:
        lines.append("Estimated from mains power by NILM.")

    confidence = _nilm_confidence(alert)
    if confidence is not None and "Confidence:" not in alert.message:
        lines.append(f"Confidence: {round(confidence * 100)}%.")
    return lines


def _is_nilm_estimated_alert(alert: AlertEvidence) -> bool:
    source = str(alert.features.get("source") or "").strip().lower()
    source_type = str(alert.features.get("source_type") or "").strip().lower()
    if source == "nilm" or source_type == "nilm_estimate":
        return True
    assignment_id = str(alert.features.get("assignment_id") or "").strip()
    return bool(assignment_id and alert.features.get("estimated") is True)


def _nilm_confidence(alert: AlertEvidence) -> float | None:
    for key in ("confidence", "nilm_confidence", "assignment_confidence"):
        raw = alert.features.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        if value < 0:
            continue
        if value > 1.0:
            value /= 100.0
        return min(value, 1.0)
    return None


async def async_create_alert_notification(
    hass: Any,
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> None:
    """Create a persistent notification for important alert evidence if HA exists."""
    try:
        from homeassistant.components import persistent_notification
    except ModuleNotFoundError:
        return

    create = getattr(persistent_notification, "async_create", None)
    if create is None:
        return

    try:
        create(
            hass,
            alert_notification_message(
                alert,
                config=config,
                dashboard_path=dashboard_path,
            ),
            title="Energy Analyzer Alert",
            notification_id=notification_id_for_alert(alert),
        )
    except (AttributeError, TypeError):
        return


async def async_create_settings_recommendation_notification(
    hass: Any,
    entry_id: str,
    *,
    total_pending: int,
) -> None:
    """Create one persistent notification for pending suggested settings."""
    if total_pending <= 0:
        return
    try:
        from homeassistant.components import persistent_notification
    except ModuleNotFoundError:
        return

    create = getattr(persistent_notification, "async_create", None)
    if create is None:
        return

    try:
        create(
            hass,
            _settings_recommendation_message(total_pending),
            title="CircuitSetup Energy Analyzer suggested settings",
            notification_id=settings_recommendation_notification_id(entry_id),
        )
    except (AttributeError, TypeError):
        return


def _settings_recommendation_message(total_pending: int) -> str:
    if total_pending == 1:
        return (
            "There is 1 suggested Advanced Circuit Setting to review via "
            "CircuitSetup Energy Analyzer > Configure > Review Suggested Settings."
        )
    return (
        f"There are {total_pending} suggested Advanced Circuit Settings "
        "to review via CircuitSetup Energy Analyzer > "
        "Configure > Review Suggested Settings."
    )


def _comparison_value_label(alert: AlertEvidence) -> str:
    if alert.feature in {"demand_limit", "demand_monthly_peak"}:
        return "Comparison value"
    return "Baseline value"
