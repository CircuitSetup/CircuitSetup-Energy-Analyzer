from __future__ import annotations

import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .const import DOMAIN
from .models import AlertEvidence, CircuitConfig
from .notifications import notification_id_for_alert
from .services import (
    ATTR_ALERT_ID,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_MARK_ALERT_EXPECTED,
    SERVICE_MARK_ALERT_UNHELPFUL,
)
from .ux import alert_evidence_detail

PANEL_URL_PATH = "circuitsetup-energy-analyzer-evidence"
PANEL_ELEMENT_NAME = "circuitsetup-energy-analyzer-panel"
STATIC_URL_PATH = "/circuitsetup_energy_analyzer_static"
PANEL_MODULE_NAME = "energy-analyzer-panel.js"
PANEL_MODULE_VERSION = "20260606-native-chart"
EVIDENCE_API_PATH = f"/api/{DOMAIN}/alert_evidence"

_PANEL_SETUP_KEY = "_panel_setup"
_PANEL_SKIPPED_VALUE = "skipped_existing_panel"
_PANEL_REGISTERED_VALUE = "registered"
_FRONTEND_DIR = Path(__file__).parent / "frontend"

try:
    from aiohttp import web
    from homeassistant.components.http import KEY_HASS, HomeAssistantView
except ModuleNotFoundError:
    KEY_HASS = "hass"

    class HomeAssistantView:  # type: ignore[no-redef]
        """Fallback base class for unit tests without Home Assistant installed."""

    class _FallbackWeb:
        @staticmethod
        def json_response(data: dict[str, Any]) -> dict[str, Any]:
            return data

    web = _FallbackWeb()  # type: ignore[assignment]


class AlertEvidenceView(HomeAssistantView):
    """Authenticated API endpoint used by the dynamic alert evidence panel."""

    url = EVIDENCE_API_PATH
    name = f"api:{DOMAIN}:alert_evidence"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return alert evidence selected by query parameters."""
        hass = request.app[KEY_HASS]
        payload = alert_evidence_payload(
            _loaded_coordinators(hass),
            alert_id=request.query.get("alert_id"),
            circuit_id=request.query.get("circuit_id"),
        )
        return web.json_response(payload)


async def async_setup_panel(hass: Any) -> bool:
    """Register the dynamic alert evidence frontend once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_PANEL_SETUP_KEY) in {
        _PANEL_REGISTERED_VALUE,
        _PANEL_SKIPPED_VALUE,
    }:
        return True

    await _async_register_static_paths(hass)
    _register_view(hass)
    registered = await _async_register_panel(hass)
    domain_data[_PANEL_SETUP_KEY] = (
        _PANEL_REGISTERED_VALUE if registered else _PANEL_SKIPPED_VALUE
    )
    return True


async def async_unload_panel(hass: Any) -> None:
    """Remove the panel registration when the last config entry unloads."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.pop(_PANEL_SETUP_KEY, None) != _PANEL_REGISTERED_VALUE:
        return

    frontend = _frontend_component(hass)
    remove_panel = getattr(frontend, "async_remove_panel", None)
    if remove_panel is not None:
        remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


def alert_evidence_payload(
    coordinators: Iterable[Any],
    *,
    alert_id: str | None = None,
    circuit_id: str | None = None,
) -> dict[str, Any]:
    """Return the dynamic panel payload for an alert or circuit fallback."""
    requested_alert_id = alert_id or None
    requested_circuit_id = circuit_id or None
    coordinators = tuple(coordinators)

    if requested_alert_id:
        for coordinator in coordinators:
            for alert in _coordinator_alerts(coordinator):
                if notification_id_for_alert(alert) == requested_alert_id:
                    return _payload_for_alert(
                        "matched_alert",
                        coordinator,
                        alert,
                        requested_alert_id=requested_alert_id,
                        requested_circuit_id=requested_circuit_id,
                    )

    if requested_circuit_id:
        for coordinator in coordinators:
            if alert := _latest_alert_for_circuit(coordinator, requested_circuit_id):
                return _payload_for_alert(
                    "latest_for_circuit",
                    coordinator,
                    alert,
                    requested_alert_id=requested_alert_id,
                    requested_circuit_id=requested_circuit_id,
                )
            if detail := _state_alert_detail(coordinator, requested_circuit_id):
                config = _config_for_circuit(coordinator, requested_circuit_id)
                return {
                    "status": "latest_for_circuit",
                    "requested_alert_id": requested_alert_id,
                    "requested_circuit_id": requested_circuit_id,
                    "alert": dict(detail),
                    "circuit": _circuit_payload(config),
                    "actions": _actions_for_alert_id(detail.get("alert_id")),
                }

    return {
        "status": "not_found",
        "requested_alert_id": requested_alert_id,
        "requested_circuit_id": requested_circuit_id,
        "alert": None,
        "circuit": None,
        "actions": {},
    }


def _payload_for_alert(
    status: str,
    coordinator: Any,
    alert: AlertEvidence,
    *,
    requested_alert_id: str | None,
    requested_circuit_id: str | None,
) -> dict[str, Any]:
    config = _config_for_circuit(coordinator, alert.circuit_id)
    detail = alert_evidence_detail(alert, config=config)
    return {
        "status": status,
        "requested_alert_id": requested_alert_id,
        "requested_circuit_id": requested_circuit_id,
        "alert": detail,
        "circuit": _circuit_payload(config),
        "actions": _actions_for_alert_id(detail["alert_id"]),
    }


def _actions_for_alert_id(alert_id: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(alert_id, str) or not alert_id:
        return {}
    data = {ATTR_ALERT_ID: alert_id}
    return {
        "acknowledge": {
            "domain": DOMAIN,
            "service": SERVICE_ACKNOWLEDGE_ALERT,
            "data": data,
        },
        "mark_expected": {
            "domain": DOMAIN,
            "service": SERVICE_MARK_ALERT_EXPECTED,
            "data": data,
        },
        "mark_unhelpful": {
            "domain": DOMAIN,
            "service": SERVICE_MARK_ALERT_UNHELPFUL,
            "data": data,
        },
    }


def _circuit_payload(config: CircuitConfig | None) -> dict[str, str] | None:
    if config is None:
        return None
    return {
        "circuit_id": config.circuit_id,
        "name": config.name,
        "appliance_profile": str(config.appliance_profile),
        "mode": str(config.mode),
    }


def _latest_alert_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> AlertEvidence | None:
    alerts = [
        alert
        for alert in _coordinator_alerts(coordinator)
        if alert.circuit_id == circuit_id
    ]
    if not alerts:
        return None
    return max(alerts, key=lambda alert: alert.last_seen or alert.timestamp)


def _state_alert_detail(coordinator: Any, circuit_id: str) -> dict[str, Any] | None:
    state = getattr(coordinator, "state", None)
    details = getattr(state, "alert_evidence_by_circuit", {}) or {}
    detail = details.get(circuit_id)
    return dict(detail) if isinstance(detail, dict) else None


def _coordinator_alerts(coordinator: Any) -> tuple[AlertEvidence, ...]:
    store_data = getattr(coordinator, "store_data", None)
    alerts = getattr(store_data, "alerts", ()) or ()
    return tuple(alert for alert in alerts if isinstance(alert, AlertEvidence))


def _config_for_circuit(coordinator: Any, circuit_id: str) -> CircuitConfig | None:
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if getattr(config, "circuit_id", None) == circuit_id:
            return config
    return None


def _loaded_coordinators(hass: Any) -> tuple[Any, ...]:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {}) or {}
    return tuple(
        value
        for key, value in domain_data.items()
        if key != _PANEL_SETUP_KEY and not str(key).startswith("_")
    )


async def _async_register_static_paths(hass: Any) -> None:
    http = getattr(hass, "http", None)
    register_static = getattr(http, "async_register_static_paths", None)
    if register_static is None:
        return
    await register_static([_static_path_config()])


def _static_path_config() -> Any:
    try:
        from homeassistant.components.http import StaticPathConfig
    except ModuleNotFoundError:
        return (STATIC_URL_PATH, str(_FRONTEND_DIR), True)
    return StaticPathConfig(STATIC_URL_PATH, str(_FRONTEND_DIR), True)


def _register_view(hass: Any) -> None:
    http = getattr(hass, "http", None)
    register_view = getattr(http, "register_view", None)
    if register_view is not None:
        register_view(AlertEvidenceView())


async def _async_register_panel(hass: Any) -> bool:
    frontend = _frontend_component(hass)
    panel_exists = getattr(frontend, "async_panel_exists", None)
    if panel_exists is not None and await _maybe_await(
        panel_exists(hass, PANEL_URL_PATH)
    ):
        return False

    panel_custom = _panel_custom_component(hass)
    register_panel = getattr(panel_custom, "async_register_panel", None)
    if register_panel is None:
        return False
    try:
        await register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_ELEMENT_NAME,
            sidebar_title="Energy Analyzer Evidence",
            sidebar_icon="mdi:chart-timeline-variant",
            module_url=(
                f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v={PANEL_MODULE_VERSION}"
            ),
            config={
                "api_path": EVIDENCE_API_PATH,
                "domain": DOMAIN,
            },
            embed_iframe=False,
            require_admin=False,
        )
    except ValueError:
        return False
    return True


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _panel_custom_component(hass: Any) -> Any:
    try:
        from homeassistant.components import panel_custom

        return panel_custom
    except ModuleNotFoundError:
        return getattr(getattr(hass, "components", None), "panel_custom", None)


def _frontend_component(hass: Any) -> Any:
    try:
        from homeassistant.components import frontend

        return frontend
    except ModuleNotFoundError:
        return getattr(getattr(hass, "components", None), "frontend", None)
