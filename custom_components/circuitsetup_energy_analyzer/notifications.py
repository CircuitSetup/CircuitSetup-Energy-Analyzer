from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .models import AlertEvidence


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    return f"{DOMAIN}_alert_{alert.circuit_id}_{feature}"


async def async_create_alert_notification(hass: Any, alert: AlertEvidence) -> None:
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
        alert.message,
        title="CircuitSetup Energy Analyzer alert",
        notification_id=notification_id_for_alert(alert),
    )
