from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import DOMAIN
from .models import AlertEvidence, CircuitConfig


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    return _tuple_id(f"{DOMAIN}_alert", alert.circuit_id, feature)


def alert_notification_message(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> str:
    """Return Markdown body text for an alert persistent notification."""
    from .alert_links import alert_evidence_path, alert_graph_entities

    lines = [
        alert.message,
        "",
        "[Open evidence graph]"
        f"({alert_evidence_path(alert, dashboard_path=dashboard_path)})",
        "",
        f"- Observed value: {alert.observed_value}",
        f"- Baseline value: {alert.baseline_value}",
        f"- Repeated observations: {alert.repeated_count}",
    ]
    graph_entities = alert_graph_entities(alert, config)
    if graph_entities:
        lines.extend(
            [
                "",
                "Graph entities:",
                *(f"- `{entity_id}`" for entity_id in graph_entities),
            ]
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
        title="CircuitSetup Energy Analyzer alert",
        notification_id=notification_id_for_alert(alert),
    )


def _tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(_readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def _readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"
