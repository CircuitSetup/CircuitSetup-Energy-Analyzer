from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import DOMAIN
from .models import AlertEvidence, CircuitConfig
from .safety import ELECTRICAL_SAFETY_NOTICE, feature_needs_electrical_safety_notice


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
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

    create(
        hass,
        alert_notification_message(alert, config=config, dashboard_path=dashboard_path),
        title="Energy Analyzer Alert",
        notification_id=notification_id_for_alert(alert),
    )


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

    create(
        hass,
        _settings_recommendation_message(total_pending),
        title="CircuitSetup Energy Analyzer suggested settings",
        notification_id=settings_recommendation_notification_id(entry_id),
    )


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


def _tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(_readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def _readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"
