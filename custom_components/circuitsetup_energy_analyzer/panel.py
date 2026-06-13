from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .const import DOMAIN
from .models import AlertEvidence, CircuitConfig
from .notifications import notification_id_for_alert
from .services import (
    ATTR_ALERT_ID,
    ATTR_CIRCUIT_ID,
    ATTR_ENTRY_ID,
    ATTR_RECOMMENDATION_ID,
    ATTR_SIGNATURE_ID,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_APPLY_SETTING_RECOMMENDATION,
    SERVICE_DENY_SETTING_RECOMMENDATION,
    SERVICE_DISMISS_SETTING_RECOMMENDATION,
    SERVICE_END_MAINTENANCE,
    SERVICE_IGNORE_NILM_SIGNATURE,
    SERVICE_LABEL_NILM_SIGNATURE,
    SERVICE_MARK_ALERT_EXPECTED,
    SERVICE_MARK_ALERT_UNHELPFUL,
    SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
    SERVICE_PAUSE_ALERTS,
    SERVICE_RELEARN_BASELINE,
    SERVICE_START_MAINTENANCE,
)
from .ux import alert_evidence_detail

PANEL_URL_PATH = "circuitsetup-energy-analyzer-evidence"
PANEL_ELEMENT_NAME = "circuitsetup-energy-analyzer-panel"
STATIC_URL_PATH = "/circuitsetup_energy_analyzer_static"
PANEL_MODULE_NAME = "energy-analyzer-panel.js"
PANEL_MODULE_VERSION = "20260612-action-availability"
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
    await _async_remove_existing_panel(hass)
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
        await _maybe_await(
            remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        )


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
                    "actions": _actions_for_context(
                        coordinator,
                        config=config,
                        alert_id=detail.get("alert_id"),
                        circuit_id=requested_circuit_id,
                    ),
                    "setting_recommendations": (
                        _setting_recommendations_for_circuit(
                            coordinator,
                            requested_circuit_id,
                        )
                    ),
                    "nilm": _nilm_payload_for_circuit(
                        coordinator,
                        requested_circuit_id,
                    ),
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
        "actions": _actions_for_context(
            coordinator,
            config=config,
            alert_id=detail["alert_id"],
            circuit_id=alert.circuit_id,
        ),
        "setting_recommendations": _setting_recommendations_for_circuit(
            coordinator,
            alert.circuit_id,
        ),
        "nilm": _nilm_payload_for_circuit(coordinator, alert.circuit_id),
    }


def _actions_for_context(
    coordinator: Any,
    *,
    config: CircuitConfig | None,
    alert_id: Any,
    circuit_id: str | None,
) -> dict[str, dict[str, Any]]:
    actions: dict[str, dict[str, Any]] = {}
    if isinstance(alert_id, str) and alert_id:
        alert_data = {ATTR_ALERT_ID: alert_id}
        actions.update(
            {
                "acknowledge": {
                    "domain": DOMAIN,
                    "service": SERVICE_ACKNOWLEDGE_ALERT,
                    "data": alert_data,
                },
                "mark_expected": {
                    "domain": DOMAIN,
                    "service": SERVICE_MARK_ALERT_EXPECTED,
                    "data": alert_data,
                },
                "mark_unhelpful": {
                    "domain": DOMAIN,
                    "service": SERVICE_MARK_ALERT_UNHELPFUL,
                    "data": alert_data,
                },
            }
        )

    if circuit_id:
        circuit_data = {ATTR_CIRCUIT_ID: circuit_id}
        if _maintenance_active(coordinator, circuit_id):
            maintenance_action = {
                "end_maintenance": {
                    "domain": DOMAIN,
                    "service": SERVICE_END_MAINTENANCE,
                    "data": circuit_data,
                }
            }
        else:
            maintenance_action = {
                "start_maintenance": {
                    "domain": DOMAIN,
                    "service": SERVICE_START_MAINTENANCE,
                    "data": circuit_data,
                }
            }
        actions.update(
            {
                "pause_alerts": _pause_alerts_action(
                    coordinator,
                    circuit_id,
                    alert_id=alert_id,
                    data=circuit_data,
                ),
                "relearn_baseline": {
                    "domain": DOMAIN,
                    "service": SERVICE_RELEARN_BASELINE,
                    "data": circuit_data,
                },
                "open_advanced_circuit_settings": {
                    "type": "navigate",
                    "path": _advanced_circuit_settings_path(config),
                },
            }
        )
        actions.update(maintenance_action)

    recommendations = _setting_recommendations_for_circuit(
        coordinator,
        circuit_id,
    )
    recommendation_id = _first_recommendation_id(recommendations)
    if recommendation_id:
        recommendation_data: dict[str, Any] = {
            ATTR_RECOMMENDATION_ID: recommendation_id
        }
        entry_id = getattr(coordinator, "entry_id", None)
        if isinstance(entry_id, str) and entry_id:
            recommendation_data[ATTR_ENTRY_ID] = entry_id
        actions["apply_setting_recommendation"] = {
            "domain": DOMAIN,
            "service": SERVICE_APPLY_SETTING_RECOMMENDATION,
            "data": recommendation_data,
        }
        actions["deny_setting_recommendation"] = {
            "domain": DOMAIN,
            "service": SERVICE_DENY_SETTING_RECOMMENDATION,
            "data": recommendation_data,
        }
        actions["dismiss_setting_recommendation"] = {
            "domain": DOMAIN,
            "service": SERVICE_DISMISS_SETTING_RECOMMENDATION,
            "data": recommendation_data,
        }

    return actions


def _advanced_circuit_settings_path(config: CircuitConfig | None) -> str:
    if config is None:
        return "/config/integrations/integration/circuitsetup_energy_analyzer"
    return (
        "/config/integrations/integration/circuitsetup_energy_analyzer"
        f"?circuit_id={config.circuit_id}"
    )


def _setting_recommendations_for_circuit(
    coordinator: Any,
    circuit_id: str | None,
) -> list[dict[str, Any]]:
    if not circuit_id:
        return []
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {})
    recommendations = by_circuit.get(circuit_id, ()) if isinstance(
        by_circuit,
        dict,
    ) else ()
    return [
        _recommendation_payload(item, coordinator=coordinator)
        for item in _iter_items(recommendations)
    ]


def _recommendation_payload(item: Any, *, coordinator: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
        for key in (
            ATTR_RECOMMENDATION_ID,
            "title",
            "summary",
            "feature",
            "current_value",
            "suggested_value",
            "reason",
        ):
            value = getattr(item, key, None)
            if value is not None:
                payload[key] = value

    recommendation_id = payload.get(ATTR_RECOMMENDATION_ID)
    if isinstance(recommendation_id, str) and recommendation_id:
        payload["actions"] = _recommendation_actions(coordinator, recommendation_id)
    return payload


def _recommendation_actions(
    coordinator: Any,
    recommendation_id: str,
) -> dict[str, dict[str, Any]]:
    data: dict[str, Any] = {ATTR_RECOMMENDATION_ID: recommendation_id}
    entry_id = getattr(coordinator, "entry_id", None)
    if isinstance(entry_id, str) and entry_id:
        data[ATTR_ENTRY_ID] = entry_id
    return {
        "apply": {
            "domain": DOMAIN,
            "service": SERVICE_APPLY_SETTING_RECOMMENDATION,
            "data": dict(data),
        },
        "deny": {
            "domain": DOMAIN,
            "service": SERVICE_DENY_SETTING_RECOMMENDATION,
            "data": dict(data),
        },
        "dismiss": {
            "domain": DOMAIN,
            "service": SERVICE_DISMISS_SETTING_RECOMMENDATION,
            "data": dict(data),
        },
    }


def _first_recommendation_id(recommendations: list[dict[str, Any]]) -> str | None:
    for recommendation in recommendations:
        recommendation_id = recommendation.get(ATTR_RECOMMENDATION_ID)
        if isinstance(recommendation_id, str) and recommendation_id:
            return recommendation_id
    return None


def _nilm_payload_for_circuit(
    coordinator: Any,
    circuit_id: str | None,
) -> dict[str, Any]:
    if not circuit_id:
        return {"signatures": []}
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    return {
        "signatures": [
            {
                **signature,
                "actions": _nilm_actions_for_signature(
                    circuit_id,
                    str(signature[ATTR_SIGNATURE_ID]),
                    signatures,
                ),
            }
            for signature in signatures
            if signature.get(ATTR_SIGNATURE_ID)
        ]
    }


def _nilm_signatures_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    state = getattr(coordinator, "state", None)
    inventory_by_circuit = getattr(state, "nilm_unknown_loads_by_circuit", {})
    inventory = (
        inventory_by_circuit.get(circuit_id)
        if isinstance(inventory_by_circuit, dict)
        else None
    )
    if isinstance(inventory, dict):
        unknown_loads = [
            dict(item)
            for item in _iter_items(inventory.get("unknown_loads", ()))
            if isinstance(item, dict)
        ]
        if unknown_loads:
            return unknown_loads

    store_data = getattr(coordinator, "store_data", None)
    signatures_by_circuit = getattr(store_data, "nilm_signatures", {})
    if not isinstance(signatures_by_circuit, dict):
        return []
    return [
        dict(item)
        for item in _iter_items(signatures_by_circuit.get(circuit_id, ()))
        if isinstance(item, dict)
    ]


def _nilm_actions_for_signature(
    circuit_id: str,
    signature_id: str,
    signatures: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_SIGNATURE_ID: signature_id}
    return {
        "label": {
            "domain": DOMAIN,
            "service": SERVICE_LABEL_NILM_SIGNATURE,
            "data": dict(data),
            "requires": ["label"],
        },
        "ignore": {
            "domain": DOMAIN,
            "service": SERVICE_IGNORE_NILM_SIGNATURE,
            "data": dict(data),
        },
        "mark_expected": {
            "domain": DOMAIN,
            "service": SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
            "data": dict(data),
        },
        "merge": {
            "domain": DOMAIN,
            "service": "merge_nilm_signatures",
            "data": {ATTR_CIRCUIT_ID: circuit_id, "source_signature_id": signature_id},
            "requires": ["target_signature_id"],
            "target_options": _nilm_merge_target_options(signatures, signature_id),
        },
    }


def _nilm_merge_target_options(
    signatures: Iterable[dict[str, Any]],
    source_signature_id: str,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for signature in signatures:
        signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
        if not signature_id or signature_id == source_signature_id:
            continue
        options.append(
            {
                "value": signature_id,
                "label": _nilm_signature_label(signature, signature_id),
            }
        )
    return options


def _nilm_signature_label(signature: Mapping[str, Any], fallback: str) -> str:
    label = (
        str(signature.get("display_name") or "").strip()
        or str(signature.get("likely_type") or "").strip()
        or fallback
    )
    parts = [label]
    typical_watts = signature.get("typical_watts")
    if isinstance(typical_watts, (int, float)) and typical_watts > 0:
        parts.append(_format_power_label(float(typical_watts)))
    confidence = signature.get("confidence")
    if isinstance(confidence, (int, float)):
        parts.append(f"confidence {round(float(confidence) * 100):.0f}%")
    first_seen = _format_first_seen_label(signature.get("first_seen"))
    if first_seen:
        parts.append(f"first seen {first_seen}")
    return ", ".join(parts)


def _format_power_label(typical_watts: float) -> str:
    if typical_watts >= 1000:
        return f"{round(typical_watts / 1000, 1):.1f} kW"
    return f"{round(typical_watts):.0f} W"


def _format_first_seen_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.split("T", 1)[0]


def _pause_alerts_action(
    coordinator: Any,
    circuit_id: str,
    *,
    alert_id: Any,
    data: dict[str, str],
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "domain": DOMAIN,
        "service": SERVICE_PAUSE_ALERTS,
        "data": data,
    }
    reason = _pause_alerts_unavailable_reason(
        coordinator,
        circuit_id,
        alert_id=alert_id,
    )
    if reason is not None:
        action.update(
            {
                "enabled": False,
                "unavailable_reason": reason,
                "unavailable_label": _unavailable_action_label(reason),
            }
        )
    return action


def _pause_alerts_unavailable_reason(
    coordinator: Any,
    circuit_id: str,
    *,
    alert_id: Any,
) -> str | None:
    if _alerts_paused(coordinator, circuit_id):
        return "alerts_paused"
    if isinstance(alert_id, str) and alert_id:
        return None
    if _has_active_alert(coordinator, circuit_id):
        return None
    return "no_active_alert"


def _unavailable_action_label(reason: str) -> str:
    return {
        "alerts_paused": "Alerts are already paused for this circuit.",
        "no_active_alert": "No active alert is available to pause.",
    }.get(reason, reason.replace("_", " ").capitalize())


def _alerts_paused(coordinator: Any, circuit_id: str) -> bool:
    paused_circuits = getattr(coordinator, "paused_circuits", ())
    return circuit_id in paused_circuits or _maintenance_active(coordinator, circuit_id)


def _has_active_alert(coordinator: Any, circuit_id: str) -> bool:
    state = getattr(coordinator, "state", None)
    alerts_by_circuit = getattr(state, "active_alerts_by_circuit", {})
    if isinstance(alerts_by_circuit, Mapping) and _truthy_collection(
        alerts_by_circuit.get(circuit_id)
    ):
        return True
    return _latest_alert_for_circuit(coordinator, circuit_id) is not None


def _truthy_collection(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, Mapping):
        return bool(value)
    try:
        return len(value) > 0
    except TypeError:
        return bool(value)


def _maintenance_active(coordinator: Any, circuit_id: str) -> bool:
    state = getattr(coordinator, "state", None)
    maintenance_by_circuit = getattr(state, "maintenance_by_circuit", {})
    if not isinstance(maintenance_by_circuit, dict):
        return False
    maintenance = maintenance_by_circuit.get(circuit_id)
    return isinstance(maintenance, Mapping) and maintenance.get("active") is True


def _iter_items(value: Any) -> Iterable[Any]:
    if isinstance(value, (str, bytes)) or value is None:
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


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
    panel_custom = _panel_custom_component(hass)
    register_panel = getattr(panel_custom, "async_register_panel", None)
    if register_panel is None:
        return False
    try:
        await register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_ELEMENT_NAME,
            # Keep the evidence page available for notification links without
            # adding a standalone entry to the Home Assistant sidebar.
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


async def _async_remove_existing_panel(hass: Any) -> None:
    frontend = _frontend_component(hass)
    panel_exists = getattr(frontend, "async_panel_exists", None)
    remove_panel = getattr(frontend, "async_remove_panel", None)
    if panel_exists is None or remove_panel is None:
        return
    if not await _maybe_await(panel_exists(hass, PANEL_URL_PATH)):
        return
    await _maybe_await(remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False))


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
