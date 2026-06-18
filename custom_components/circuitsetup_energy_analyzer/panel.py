from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .alert_links import _feature_for_alert as _canonical_feature_for_alert
from .const import DOMAIN
from .models import AlertEvidence, CircuitConfig
from .notifications import notification_id_for_alert
from .recommendation_guidance import (
    is_hidden_recommendation_evidence_key,
    recommendation_evidence_preview,
    recommendation_setting_default_value,
    recommendation_setting_expected_effect,
)
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
    SERVICE_MERGE_NILM_SIGNATURES,
    SERVICE_PAUSE_ALERTS,
    SERVICE_RELEARN_BASELINE,
    SERVICE_RESET_SETTING_RECOMMENDATION,
    SERVICE_START_MAINTENANCE,
    SERVICE_UNDO_SETTING_RECOMMENDATION,
)
from .ux import alert_evidence_detail, friendly_feature_name

PANEL_URL_PATH = "circuitsetup-energy-analyzer-evidence"
MAX_NILM_PANEL_SIGNATURES = 5
MAX_NILM_MERGE_TARGET_OPTIONS = 5
NILM_SIGNATURE_PANEL_FIELDS = (
    ATTR_SIGNATURE_ID,
    "display_name",
    "user_label",
    "likely_type",
    "typical_watts",
    "confidence",
    "first_seen",
    "last_seen",
    "voltage_class",
    "running_state",
    "current_runtime_minutes",
    "estimated_energy_today_kwh",
    "review_state",
    "expected",
    "ignored",
    "merged_into",
)
PANEL_ELEMENT_NAME = "circuitsetup-energy-analyzer-panel"
STATIC_URL_PATH = "/circuitsetup_energy_analyzer_static"
PANEL_MODULE_NAME = "energy-analyzer-panel.js"
PANEL_MODULE_VERSION = "20260615-action-time-polish"
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
            feature=request.query.get("feature"),
            include_all_nilm=_truthy_query(request.query.get("include_all_nilm")),
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
        await _maybe_await(remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False))


def alert_evidence_payload(
    coordinators: Iterable[Any],
    *,
    alert_id: str | None = None,
    circuit_id: str | None = None,
    feature: str | None = None,
    include_all_nilm: bool = False,
) -> dict[str, Any]:
    """Return the dynamic panel payload for an alert or circuit fallback."""
    requested_alert_id = alert_id or None
    requested_circuit_id = circuit_id or None
    requested_feature = str(feature or "").strip() or None
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
                        requested_feature=requested_feature,
                        include_all_nilm=include_all_nilm,
                    )

    fallback_circuit: tuple[Any, CircuitConfig] | None = None
    if requested_circuit_id:
        for coordinator in coordinators:
            if alert := _latest_alert_for_circuit(
                coordinator,
                requested_circuit_id,
                feature=requested_feature,
            ):
                return _payload_for_alert(
                    "latest_for_circuit",
                    coordinator,
                    alert,
                    requested_alert_id=requested_alert_id,
                    requested_circuit_id=requested_circuit_id,
                    requested_feature=requested_feature,
                    include_all_nilm=include_all_nilm,
                )
            if detail := _state_alert_detail(
                coordinator,
                requested_circuit_id,
                feature=requested_feature,
            ):
                config = _config_for_circuit(coordinator, requested_circuit_id)
                return _with_requested_feature(
                    {
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
                            include_all_nilm=include_all_nilm,
                        ),
                    },
                    requested_feature,
                )
            config = _config_for_circuit(coordinator, requested_circuit_id)
            if config is not None and fallback_circuit is None:
                fallback_circuit = (coordinator, config)

    if requested_circuit_id and fallback_circuit is not None:
        coordinator, config = fallback_circuit
        return _with_requested_feature(
            {
                "status": "circuit_found_no_evidence",
                "requested_alert_id": requested_alert_id,
                "requested_circuit_id": requested_circuit_id,
                "alert": None,
                "circuit": _circuit_payload(config),
                "actions": _actions_for_context(
                    coordinator,
                    config=config,
                    alert_id=None,
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
                    include_all_nilm=include_all_nilm,
                ),
                "message": "No current alert evidence is available for this circuit.",
                "next_step": (
                    "Use the available circuit actions below, open Advanced "
                    "Circuit Settings, or review the summary sensors for the "
                    "latest state."
                ),
            },
            requested_feature,
        )

    return _with_requested_feature(
        {
            "status": "not_found",
            "requested_alert_id": requested_alert_id,
            "requested_circuit_id": requested_circuit_id,
            "alert": None,
            "circuit": None,
            "actions": {},
            "message": (
                "The requested alert or circuit evidence is no longer available."
            ),
            "next_step": (
                "Open a newer notification or review the appliance summary sensors."
            ),
        },
        requested_feature,
    )


def _payload_for_alert(
    status: str,
    coordinator: Any,
    alert: AlertEvidence,
    *,
    requested_alert_id: str | None,
    requested_circuit_id: str | None,
    requested_feature: str | None,
    include_all_nilm: bool,
) -> dict[str, Any]:
    config = _config_for_circuit(coordinator, alert.circuit_id)
    detail = alert_evidence_detail(alert, config=config)
    return _with_requested_feature(
        {
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
            "nilm": _nilm_payload_for_circuit(
                coordinator,
                alert.circuit_id,
                include_all_nilm=include_all_nilm,
            ),
        },
        requested_feature,
    )


def _with_requested_feature(
    payload: dict[str, Any],
    requested_feature: str | None,
) -> dict[str, Any]:
    if requested_feature:
        payload["requested_feature"] = requested_feature
    return payload


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
                "open_advanced_circuit_settings": (
                    _advanced_circuit_settings_action(coordinator, config)
                ),
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


def _advanced_circuit_settings_action(
    coordinator: Any,
    config: CircuitConfig | None,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "type": "navigate",
        "path": _advanced_circuit_settings_path(coordinator, config),
    }
    entry_id = _coordinator_entry_id(coordinator)
    if entry_id:
        action[ATTR_ENTRY_ID] = entry_id
    if config is not None:
        action[ATTR_CIRCUIT_ID] = config.circuit_id
        action["options_step"] = "advanced_settings"
    return action


def _advanced_circuit_settings_path(
    coordinator: Any,
    config: CircuitConfig | None,
) -> str:
    path = "/config/integrations/integration/circuitsetup_energy_analyzer"
    params: dict[str, str] = {}
    entry_id = _coordinator_entry_id(coordinator)
    if entry_id:
        params["config_entry"] = entry_id
    if config is not None:
        params[ATTR_CIRCUIT_ID] = config.circuit_id
        params["options_step"] = "advanced_settings"
    if not params:
        return path
    return f"{path}#{urlencode(params)}"


def _coordinator_entry_id(coordinator: Any) -> str | None:
    entry_id = getattr(coordinator, "entry_id", None)
    if isinstance(entry_id, str) and entry_id:
        return entry_id
    return None


def _setting_recommendations_for_circuit(
    coordinator: Any,
    circuit_id: str | None,
) -> list[dict[str, Any]]:
    if not circuit_id:
        return []
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {})
    recommendations = (
        by_circuit.get(circuit_id, ())
        if isinstance(
            by_circuit,
            dict,
        )
        else ()
    )
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
            "circuit_id",
            "setting_key",
            "setting_label",
            "feature",
            "current_value",
            "suggested_value",
            "unit",
            "reason",
            "evidence",
            "confidence",
        ):
            value = getattr(item, key, None)
            if value is not None:
                payload[key] = value

    recommendation_id = payload.get(ATTR_RECOMMENDATION_ID)
    payload["display_label"] = _recommendation_display_label(payload)
    _add_recommendation_guidance(payload)
    if isinstance(recommendation_id, str) and recommendation_id:
        payload["actions"] = _recommendation_actions(
            coordinator,
            recommendation_id,
            status=str(payload.get("status") or "pending"),
        )
        evidence_path = _recommendation_evidence_path(payload, recommendation_id)
        if evidence_path:
            payload["evidence_path"] = evidence_path
            payload["actions"]["preview"] = {"path": evidence_path}
    return payload


def _recommendation_display_label(payload: Mapping[str, Any]) -> str:
    for key in ("title", "summary", "setting_label"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    feature = str(payload.get("feature") or "").strip()
    if feature:
        return friendly_feature_name(feature)
    return "Suggested setting"


def _recommendation_actions(
    coordinator: Any,
    recommendation_id: str,
    *,
    status: str,
) -> dict[str, dict[str, Any]]:
    data: dict[str, Any] = {ATTR_RECOMMENDATION_ID: recommendation_id}
    entry_id = getattr(coordinator, "entry_id", None)
    if isinstance(entry_id, str) and entry_id:
        data[ATTR_ENTRY_ID] = entry_id
    is_pending = status == "pending"
    is_applied = status == "applied"
    return {
        "apply": {
            "domain": DOMAIN,
            "service": SERVICE_APPLY_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_pending,
            "unavailable_reason": "not_pending",
            "unavailable_label": "This recommendation is no longer pending.",
        },
        "deny": {
            "domain": DOMAIN,
            "service": SERVICE_DENY_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_pending,
            "unavailable_reason": "not_pending",
            "unavailable_label": "This recommendation is no longer pending.",
        },
        "dismiss": {
            "domain": DOMAIN,
            "service": SERVICE_DISMISS_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_pending,
            "unavailable_reason": "not_pending",
            "unavailable_label": "This recommendation is no longer pending.",
        },
        "undo": {
            "domain": DOMAIN,
            "service": SERVICE_UNDO_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_applied,
            "unavailable_reason": "not_applied",
            "unavailable_label": "Only applied recommendations can be undone.",
        },
        "reset": {
            "domain": DOMAIN,
            "service": SERVICE_RESET_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": True,
        },
    }


def _add_recommendation_guidance(payload: dict[str, Any]) -> None:
    setting_key = str(payload.get("setting_key") or "")
    default_value = recommendation_setting_default_value(setting_key)
    if default_value is not None:
        payload["default_value"] = default_value
    expected_effect = recommendation_setting_expected_effect(setting_key)
    if expected_effect:
        payload["expected_effect"] = expected_effect
    evidence = payload.pop("evidence", None)
    payload.update(_recommendation_evidence_metadata(evidence))
    evidence_preview = recommendation_evidence_preview(evidence)
    if evidence_preview:
        payload["evidence_preview"] = evidence_preview


def _recommendation_evidence_metadata(
    evidence: Any,
    *,
    limit: int = 4,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        return {}

    preview_key_count = 0
    for key, value in evidence.items():
        key_text = str(key)
        if is_hidden_recommendation_evidence_key(key_text):
            continue
        if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
            continue
        preview_key_count += 1
        if preview_key_count >= limit:
            break

    evidence_key_count = len(evidence)
    omitted_key_count = max(evidence_key_count - preview_key_count, 0)
    return {
        "evidence_key_count": evidence_key_count,
        "evidence_preview_key_count": preview_key_count,
        "evidence_omitted_key_count": omitted_key_count,
        "evidence_has_more": omitted_key_count > 0,
    }


def _recommendation_evidence_path(
    payload: Mapping[str, Any],
    recommendation_id: str,
) -> str:
    circuit_id = str(payload.get("circuit_id") or "").strip()
    if not circuit_id:
        return ""
    query = urlencode(
        {
            "circuit_id": circuit_id,
            ATTR_RECOMMENDATION_ID: recommendation_id,
        }
    )
    return f"/{PANEL_URL_PATH}?{query}"


def _first_recommendation_id(recommendations: list[dict[str, Any]]) -> str | None:
    for recommendation in recommendations:
        recommendation_id = recommendation.get(ATTR_RECOMMENDATION_ID)
        if isinstance(recommendation_id, str) and recommendation_id:
            return recommendation_id
    return None


def _nilm_payload_for_circuit(
    coordinator: Any,
    circuit_id: str | None,
    *,
    include_all_nilm: bool = False,
) -> dict[str, Any]:
    if not circuit_id:
        return {
            "signatures": [],
            "signature_count": 0,
            "signatures_has_more": False,
            "signatures_omitted_count": 0,
        }
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    preview_signatures = (
        signatures if include_all_nilm else signatures[:MAX_NILM_PANEL_SIGNATURES]
    )
    return {
        "signatures": [
            {
                **_nilm_signature_payload(signature),
                "display_label": _nilm_signature_label(
                    signature,
                    str(signature[ATTR_SIGNATURE_ID]),
                ),
                "actions": _nilm_actions_for_signature(
                    circuit_id,
                    str(signature[ATTR_SIGNATURE_ID]),
                    signatures,
                    include_all_nilm=include_all_nilm,
                ),
            }
            for signature in preview_signatures
            if signature.get(ATTR_SIGNATURE_ID)
        ],
        "signature_count": len(signatures),
        "signatures_has_more": len(signatures) > len(preview_signatures),
        "signatures_omitted_count": max(
            len(signatures) - len(preview_signatures),
            0,
        ),
    }


def _nilm_signatures_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    signatures_by_circuit = getattr(store_data, "nilm_signatures", {})
    stored_signatures = (
        [
            dict(item)
            for item in _iter_items(signatures_by_circuit.get(circuit_id, ()))
            if isinstance(item, dict)
        ]
        if isinstance(signatures_by_circuit, dict)
        else []
    )
    stored_by_id = {
        str(signature[ATTR_SIGNATURE_ID]): signature
        for signature in stored_signatures
        if signature.get(ATTR_SIGNATURE_ID)
    }

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
            signatures: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for signature in unknown_loads:
                signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
                if signature_id:
                    seen_ids.add(signature_id)
                stored = stored_by_id.get(signature_id)
                signatures.append(
                    {**signature, **stored} if stored is not None else signature
                )
            signatures.extend(
                signature
                for signature in stored_signatures
                if str(signature.get(ATTR_SIGNATURE_ID) or "").strip() not in seen_ids
            )
            return signatures

    return stored_signatures


def _nilm_actions_for_signature(
    circuit_id: str,
    signature_id: str,
    signatures: list[dict[str, Any]],
    *,
    include_all_nilm: bool = False,
) -> dict[str, dict[str, Any]]:
    data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_SIGNATURE_ID: signature_id}
    merge_target_options = _nilm_merge_target_options(signatures, signature_id)
    merge_target_preview = (
        merge_target_options
        if include_all_nilm
        else merge_target_options[:MAX_NILM_MERGE_TARGET_OPTIONS]
    )
    merge_action: dict[str, Any] = {
        "domain": DOMAIN,
        "service": SERVICE_MERGE_NILM_SIGNATURES,
        "data": {ATTR_CIRCUIT_ID: circuit_id, "source_signature_id": signature_id},
        "requires": ["target_signature_id"],
        "target_options": merge_target_preview,
        "target_option_count": len(merge_target_options),
        "target_options_has_more": len(merge_target_options)
        > len(merge_target_preview),
        "target_options_omitted_count": max(
            len(merge_target_options) - len(merge_target_preview),
            0,
        ),
    }
    if not merge_target_preview:
        merge_action.update(
            {
                "enabled": False,
                "unavailable_reason": "no_merge_target",
                "unavailable_label": (
                    "No other NILM signature is available to merge into yet."
                ),
            }
        )
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
        "merge": merge_action,
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


def _nilm_signature_payload(signature: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        key: signature[key] for key in NILM_SIGNATURE_PANEL_FIELDS if key in signature
    }
    review_state = _nilm_review_state(signature)
    if review_state:
        payload["review_state"] = review_state
    return payload


def _nilm_review_state(signature: Mapping[str, Any]) -> str | None:
    review_state = str(signature.get("review_state") or "").strip()
    if review_state:
        return review_state
    if signature.get("ignored"):
        return "ignored"
    if signature.get("expected"):
        return "expected"
    if signature.get("merged_into"):
        return "merged"
    if str(signature.get("user_label") or "").strip():
        return "labeled"
    return None


def _nilm_signature_label(signature: Mapping[str, Any], fallback: str) -> str:
    label = (
        str(signature.get("user_label") or "").strip()
        or str(signature.get("display_name") or "").strip()
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


def _truthy_query(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "all"}


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
    *,
    feature: str | None = None,
) -> AlertEvidence | None:
    alerts = [
        alert
        for alert in _coordinator_alerts(coordinator)
        if alert.circuit_id == circuit_id
        and _feature_matches(_canonical_feature_for_alert(alert), feature)
    ]
    if not alerts:
        return None
    return max(alerts, key=lambda alert: alert.last_seen or alert.timestamp)


def _state_alert_detail(
    coordinator: Any,
    circuit_id: str,
    *,
    feature: str | None = None,
) -> dict[str, Any] | None:
    state = getattr(coordinator, "state", None)
    details = getattr(state, "alert_evidence_by_circuit", {}) or {}
    detail = details.get(circuit_id)
    if not isinstance(detail, dict):
        return None
    if not _feature_matches(detail.get("feature"), feature):
        return None
    return dict(detail)


def _feature_matches(value: Any, requested_feature: str | None) -> bool:
    if not requested_feature:
        return True
    return str(value or "").strip() == requested_feature


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
