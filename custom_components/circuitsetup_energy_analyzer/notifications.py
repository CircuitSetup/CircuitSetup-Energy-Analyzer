from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from .const import DOMAIN
from .models import AlertEvidence


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    return _tuple_id(f"{DOMAIN}_alert", alert.circuit_id, feature)


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


def _tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(_readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def _readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"
