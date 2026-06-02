from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .const import DOMAIN

SERVICE_RELEARN_BASELINE = "relearn_baseline"
SERVICE_PAUSE_ALERTS = "pause_alerts"
SERVICE_ACKNOWLEDGE_ALERT = "acknowledge_alert"
SERVICE_EXPORT_DIAGNOSTICS = "export_diagnostics"
SERVICE_RUN_MAPPING_CHECKS = "run_mapping_checks"
SERVICE_LABEL_NILM_SIGNATURE = "label_nilm_signature"
SERVICE_IGNORE_NILM_SIGNATURE = "ignore_nilm_signature"

ATTR_CIRCUIT_ID = "circuit_id"
ATTR_DURATION = "duration"
ATTR_ALERT_ID = "alert_id"
ATTR_SIGNATURE_ID = "signature_id"
ATTR_LABEL = "label"

_SERVICES_KEY = "_services_setup"


class _FallbackSchema:
    def __init__(
        self,
        required: tuple[str, ...] = (),
        optional: tuple[str, ...] = (),
    ) -> None:
        self.required = required
        self.optional = optional

    def __call__(self, data: Mapping[str, Any] | None) -> dict[str, Any]:
        values = dict(data or {})
        missing = [field for field in self.required if field not in values]
        if missing:
            raise ValueError(f"Missing required field: {', '.join(missing)}")
        return values


def _schema(required: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> Callable:
    try:
        import voluptuous as vol
    except ModuleNotFoundError:
        return _FallbackSchema(required, optional)

    fields: dict[Any, Any] = {}
    for field in required:
        fields[vol.Required(field)] = str
    for field in optional:
        fields[vol.Optional(field)] = object
    return vol.Schema(fields, extra=vol.ALLOW_EXTRA)


CIRCUIT_SERVICE_SCHEMA = _schema(required=(ATTR_CIRCUIT_ID,))
NILM_LABEL_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID, ATTR_SIGNATURE_ID, ATTR_LABEL)
)
NILM_SIGNATURE_SERVICE_SCHEMA = _schema(required=(ATTR_CIRCUIT_ID, ATTR_SIGNATURE_ID))

_SERVICE_SCHEMAS: dict[str, Callable | None] = {
    SERVICE_RELEARN_BASELINE: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_PAUSE_ALERTS: _schema(required=(ATTR_CIRCUIT_ID,), optional=(ATTR_DURATION,)),
    SERVICE_ACKNOWLEDGE_ALERT: _schema(required=(ATTR_ALERT_ID,)),
    SERVICE_EXPORT_DIAGNOSTICS: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_RUN_MAPPING_CHECKS: None,
    SERVICE_LABEL_NILM_SIGNATURE: NILM_LABEL_SERVICE_SCHEMA,
    SERVICE_IGNORE_NILM_SIGNATURE: NILM_SIGNATURE_SERVICE_SCHEMA,
}


async def async_setup_services(hass: Any) -> None:
    """Register integration services when a HA-like service registry is present."""
    services = getattr(hass, "services", None)
    register = getattr(services, "async_register", None)
    if register is None:
        return
    if not hasattr(hass, "data"):
        hass.data = {}
    if hass.data.get(DOMAIN, {}).get(_SERVICES_KEY) is True:
        return

    for service, schema in _SERVICE_SCHEMAS.items():
        register(DOMAIN, service, _service_handler(hass, service), schema=schema)

    hass.data.setdefault(DOMAIN, {})[_SERVICES_KEY] = True


async def async_unload_services(hass: Any) -> None:
    """Remove registered integration services."""
    services = getattr(hass, "services", None)
    remove = getattr(services, "async_remove", None)
    if remove is None:
        return

    for service in _SERVICE_SCHEMAS:
        remove(DOMAIN, service)

    domain_data = getattr(hass, "data", {}).get(DOMAIN)
    if isinstance(domain_data, dict):
        domain_data.pop(_SERVICES_KEY, None)


def _service_handler(hass: Any, service: str) -> Callable[[Any], Any]:
    async def handler(call: Any) -> None:
        bus = getattr(hass, "bus", None)
        fire = getattr(bus, "async_fire", None)
        if fire is None:
            return
        fire(f"{DOMAIN}_{service}", dict(getattr(call, "data", {}) or {}))

    return handler
