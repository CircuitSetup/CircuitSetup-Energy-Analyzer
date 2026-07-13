from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from .alert_links import _feature_for_alert as _canonical_feature_for_alert
from .appliance_detail import (
    ApplianceDetail,
    appliance_detail_for_assignment,
    appliance_detail_for_circuit,
)
from .appliance_insights import (
    appliance_insights_for_coordinators,
    energy_change_explanation,
)
from .appliance_notifications import preferences_from_dict
from .attention import attention_items_for_coordinators
from .const import DOMAIN
from .entities.setup_health import (
    setup_health_attributes,
    setup_health_panel_text,
    setup_health_value,
)
from .expected_schedule import schedule_settings_from_dict
from .localized_text import translation_section, translation_text
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRole,
)
from .nilm import NilmEdge, NilmSession, nilm_session_to_dict, pair_nilm_sessions
from .notifications import notification_id_for_alert
from .recommendation_guidance import (
    is_hidden_recommendation_evidence_key,
    recommendation_evidence_preview,
    recommendation_setting_control_text,
    recommendation_setting_default_value,
    recommendation_setting_expected_effect,
)
from .services import (
    ATTR_ALERT_ID,
    ATTR_APPLIANCE_PROFILE,
    ATTR_ASSIGNMENT_ID,
    ATTR_CIRCUIT_ID,
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_GROUND_TRUTH_ENTITY_ID,
    ATTR_INTERVAL_ID,
    ATTR_LABEL,
    ATTR_MAINS_ENTITY_ID,
    ATTR_RECOMMENDATION_ID,
    ATTR_SESSION_ID,
    ATTR_SIGNATURE_FINGERPRINT,
    ATTR_SIGNATURE_ID,
    ATTR_SOURCE_ASSIGNMENT_ID,
    ATTR_START,
    ATTR_TARGET_ASSIGNMENT_ID,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_APPLY_SETTING_RECOMMENDATION,
    SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
    SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
    SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
    SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
    SERVICE_CONVERT_NILM_APPLIANCE_TO_DIRECT_METER,
    SERVICE_DELETE_NILM_LABEL_INTERVAL,
    SERVICE_DISMISS_SETTING_RECOMMENDATION,
    SERVICE_END_MAINTENANCE,
    SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
    SERVICE_IGNORE_NILM_SIGNATURE,
    SERVICE_LABEL_NILM_INTERVAL,
    SERVICE_LABEL_NILM_SIGNATURE,
    SERVICE_MARK_ALERT_EXPECTED,
    SERVICE_MARK_ALERT_UNHELPFUL,
    SERVICE_MARK_NILM_APPLIANCE_CORRECT,
    SERVICE_MARK_NILM_APPLIANCE_WRONG,
    SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
    SERVICE_MERGE_NILM_ASSIGNMENTS,
    SERVICE_MERGE_NILM_SIGNATURES,
    SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_REJECT_NILM_SESSION,
    SERVICE_RELEARN_BASELINE,
    SERVICE_RENAME_NILM_APPLIANCE,
    SERVICE_RESET_SETTING_RECOMMENDATION,
    SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_START_MAINTENANCE,
    SERVICE_UNDO_SETTING_RECOMMENDATION,
    SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
    SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
    SERVICE_VALIDATE_NILM_SESSION,
)
from .settings_preview import (
    build_setting_impact_preview,
    setting_preview_observations,
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
    "typical_duration_seconds",
    "seen_count",
    "confidence",
    "first_seen",
    "last_seen",
    "voltage_class",
    "dominant_leg",
    "known_load_overlap",
    "running_state",
    "current_runtime_minutes",
    "estimated_energy_today_kwh",
    "review_state",
    "expected",
    "ignored",
    "merged_into",
    "fingerprint",
    "feedback_fingerprint",
    "signature_fingerprint",
)
PANEL_ELEMENT_NAME = "circuitsetup-energy-analyzer-panel"
STATIC_URL_PATH = "/circuitsetup_energy_analyzer_static"
PANEL_MODULE_NAME = "energy-analyzer-panel.js"
PANEL_MODULE_VERSION = "20260713-8"
EVIDENCE_API_PATH = f"/api/{DOMAIN}/alert_evidence"
APPLIANCE_DETAIL_API_PATH = f"/api/{DOMAIN}/appliance_detail"
APPLIANCE_INSIGHTS_API_PATH = f"/api/{DOMAIN}/appliance_insights"
SETUP_HEALTH_API_PATH = f"/api/{DOMAIN}/setup_health"
NILM_WORKSPACE_API_PATH = f"/api/{DOMAIN}/nilm_workspace"
NILM_WORKSPACE_HISTORY_API_PATH = f"/api/{DOMAIN}/nilm_workspace_history"
DEFAULT_NILM_WORKSPACE_HISTORY_HOURS = 6.0
MAX_NILM_WORKSPACE_HISTORY_HOURS = 24.0
MAX_NILM_WORKSPACE_HISTORY_ENTITIES = 8
MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY = 240
MAX_NILM_WORKSPACE_KNOWN_LOADS = 8
MAX_NILM_WORKSPACE_EDGES = 40
MAX_NILM_WORKSPACE_SESSIONS = 20
MAX_NILM_WORKSPACE_LABEL_INTERVALS = 40
DEFAULT_APPLIANCE_DETAIL_HISTORY_HOURS = 168
APPLIANCE_DETAIL_HISTORY_PERIOD_HOURS = (24, 168, 720)
_HISTORY_UNIT_BY_ROLE = {
    SensorRole.VOLTAGE: "V",
    SensorRole.CURRENT: "A",
    SensorRole.REAL_POWER: "W",
    SensorRole.REACTIVE_POWER: "var",
    SensorRole.APPARENT_POWER: "VA",
    SensorRole.POWER_FACTOR: "PF",
    SensorRole.FREQUENCY: "Hz",
    SensorRole.ENERGY: "kWh",
}

_PANEL_SETUP_KEY = "_panel_setup"
_PANEL_SKIPPED_VALUE = "skipped_existing_panel"
_PANEL_REGISTERED_VALUE = "registered"
_FRONTEND_DIR = Path(__file__).parent / "frontend"


def _panel_text(*keys: str) -> str:
    return translation_text("panel", *keys)

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
            recommendation_id=request.query.get(ATTR_RECOMMENDATION_ID),
            entry_id=request.query.get(ATTR_ENTRY_ID),
            review_suggested_settings=_truthy_query(
                request.query.get("review_suggested_settings")
            ),
            include_all_nilm=_truthy_query(request.query.get("include_all_nilm")),
        )
        return web.json_response(payload)


class ApplianceDetailView(HomeAssistantView):
    """Authenticated appliance-centered detail endpoint."""

    url = APPLIANCE_DETAIL_API_PATH
    name = f"api:{DOMAIN}:appliance_detail"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return appliance detail selected by circuit or NILM assignment."""
        hass = request.app[KEY_HASS]
        payload = appliance_detail_payload(
            _loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            assignment_id=request.query.get(ATTR_ASSIGNMENT_ID),
            entry_id=request.query.get(ATTR_ENTRY_ID),
        )
        return web.json_response(payload)

    async def post(self, request: Any) -> Any:
        """Persist appliance notification or expected-schedule settings."""
        hass = request.app[KEY_HASS]
        payload = await request.json()
        if isinstance(payload, Mapping) and "expected_schedule" in payload:
            result = await async_set_appliance_expected_schedule(
                _loaded_coordinators(hass),
                circuit_id=request.query.get("circuit_id"),
                assignment_id=request.query.get(ATTR_ASSIGNMENT_ID),
                values=payload.get("expected_schedule"),
                entry_id=request.query.get(ATTR_ENTRY_ID),
            )
        else:
            result = await async_set_appliance_notification_preferences(
                _loaded_coordinators(hass),
                circuit_id=request.query.get("circuit_id"),
                assignment_id=request.query.get(ATTR_ASSIGNMENT_ID),
                values=payload,
                entry_id=request.query.get(ATTR_ENTRY_ID),
            )
        return web.json_response(result)


class ApplianceInsightsView(HomeAssistantView):
    """Authenticated integration-level appliance index endpoint."""

    url = APPLIANCE_INSIGHTS_API_PATH
    name = f"api:{DOMAIN}:appliance_insights"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return bounded direct and NILM appliance insights."""
        hass = request.app[KEY_HASS]
        return web.json_response(
            appliance_insights_payload(_loaded_coordinators(hass))
        )


class SetupHealthView(HomeAssistantView):
    """Authenticated read-only Setup Health endpoint."""

    url = SETUP_HEALTH_API_PATH
    name = f"api:{DOMAIN}:setup_health"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return the current integration setup checklist."""
        hass = request.app[KEY_HASS]
        payload = setup_health_payload(
            _loaded_coordinators(hass),
            entry_id=request.query.get(ATTR_ENTRY_ID),
        )
        return web.json_response(payload)

    async def post(self, request: Any) -> Any:
        """Persist weekly digest opt-in and delivery settings."""
        hass = request.app[KEY_HASS]
        result = await async_set_weekly_digest_settings(
            _loaded_coordinators(hass),
            entry_id=request.query.get(ATTR_ENTRY_ID),
            values=await request.json(),
        )
        return web.json_response(result)


class NilmWorkspaceView(HomeAssistantView):
    """Authenticated read-only NILM workspace payload."""

    url = NILM_WORKSPACE_API_PATH
    name = f"api:{DOMAIN}:nilm_workspace"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return bounded NILM workspace data selected by query parameters."""
        hass = request.app[KEY_HASS]
        payload = nilm_workspace_payload(
            _loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            hours=request.query.get("hours"),
            entry_id=request.query.get(ATTR_ENTRY_ID),
        )
        return web.json_response(payload)


class NilmWorkspaceHistoryView(HomeAssistantView):
    """Authenticated bounded history endpoint for the NILM workspace."""

    url = NILM_WORKSPACE_HISTORY_API_PATH
    name = f"api:{DOMAIN}:nilm_workspace_history"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return capped recorder history for NILM workspace charting."""
        hass = request.app[KEY_HASS]
        payload = await nilm_workspace_history_payload(
            hass,
            _loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            hours=request.query.get("hours"),
            entry_id=request.query.get(ATTR_ENTRY_ID),
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
        await _async_call_component_helper(
            remove_panel,
            hass,
            PANEL_URL_PATH,
            warn_if_unknown=False,
        )


def alert_evidence_payload(
    coordinators: Iterable[Any],
    *,
    alert_id: str | None = None,
    circuit_id: str | None = None,
    feature: str | None = None,
    recommendation_id: str | None = None,
    entry_id: str | None = None,
    review_suggested_settings: bool = False,
    include_all_nilm: bool = False,
) -> dict[str, Any]:
    """Return the dynamic panel payload for an alert or circuit fallback."""
    requested_alert_id = alert_id or None
    requested_circuit_id = circuit_id or None
    requested_feature = str(feature or "").strip() or None
    requested_recommendation_id = str(recommendation_id or "").strip() or None
    requested_entry_id = str(entry_id or "").strip() or None
    coordinators = tuple(coordinators)
    text = alert_evidence_panel_text()

    if review_suggested_settings:
        coordinator = _setup_health_coordinator(coordinators, requested_entry_id)
        recommendations = (
            _pending_setting_recommendations(coordinator)
            if coordinator is not None
            else []
        )
        return {
            "status": "settings_recommendations",
            "requested_entry_id": requested_entry_id,
            "alert": None,
            "circuit": None,
            "actions": {},
            "setting_recommendations": recommendations,
            "text": text,
        }

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
                        requested_recommendation_id=requested_recommendation_id,
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
                    requested_recommendation_id=requested_recommendation_id,
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
                        "text": text,
                    },
                    requested_feature,
                    requested_recommendation_id=requested_recommendation_id,
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
                "message": _panel_text(
                    "evidence",
                    "fallbacks",
                    "current_circuit_message",
                ),
                "next_step": _panel_text(
                    "evidence",
                    "fallbacks",
                    "current_circuit_next_step",
                ),
                "text": text,
            },
            requested_feature,
            requested_recommendation_id=requested_recommendation_id,
        )

    return _with_requested_feature(
        {
            "status": "not_found",
            "requested_alert_id": requested_alert_id,
            "requested_circuit_id": requested_circuit_id,
            "alert": None,
            "circuit": None,
            "actions": {},
            "message": _panel_text("evidence", "fallbacks", "not_found_message"),
            "next_step": _panel_text("evidence", "fallbacks", "not_found_next_step"),
            "text": text,
        },
        requested_feature,
        requested_recommendation_id=requested_recommendation_id,
    )


def alert_evidence_panel_text() -> dict[str, Any]:
    """Return English panel text from Home Assistant translations."""
    return dict(translation_section("panel"))


def appliance_detail_payload(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None = None,
    assignment_id: str | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return one appliance-centered detail payload."""
    requested_circuit_id = str(circuit_id or "").strip() or None
    requested_assignment_id = str(assignment_id or "").strip() or None
    requested_entry_id = str(entry_id or "").strip() or None
    coordinators = tuple(coordinators)
    if requested_entry_id:
        coordinators = tuple(
            coordinator
            for coordinator in coordinators
            if str(getattr(coordinator, "entry_id", "")) == requested_entry_id
        )

    if requested_assignment_id:
        for coordinator in coordinators:
            detail = appliance_detail_for_assignment(
                coordinator,
                requested_assignment_id,
            )
            if detail is not None:
                return _appliance_detail_payload(
                    coordinator,
                    detail,
                    requested_circuit_id=requested_circuit_id,
                    requested_assignment_id=requested_assignment_id,
                    requested_entry_id=requested_entry_id,
                )
        return {
            "status": "not_found",
            "requested_circuit_id": requested_circuit_id,
            "requested_assignment_id": requested_assignment_id,
            **(
                {"requested_entry_id": requested_entry_id}
                if requested_entry_id
                else {}
            ),
            "detail": None,
            "actions": {},
            "message": _panel_text(
                "appliance_detail",
                "assignment_not_found_message",
            ),
            "next_step": _panel_text(
                "appliance_detail",
                "assignment_not_found_next_step",
            ),
        }

    if requested_circuit_id:
        for coordinator in coordinators:
            detail = appliance_detail_for_circuit(coordinator, requested_circuit_id)
            if detail is not None:
                return _appliance_detail_payload(
                    coordinator,
                    detail,
                    requested_circuit_id=requested_circuit_id,
                    requested_assignment_id=requested_assignment_id,
                    requested_entry_id=requested_entry_id,
                )

    return {
        "status": "not_found",
        "requested_circuit_id": requested_circuit_id,
        "requested_assignment_id": requested_assignment_id,
        **(
            {"requested_entry_id": requested_entry_id}
            if requested_entry_id
            else {}
        ),
        "detail": None,
        "actions": {},
        "message": _panel_text("appliance_detail", "fallback_message"),
        "next_step": _panel_text("appliance_detail", "fallback_next_step"),
    }


def appliance_insights_payload(
    coordinators: Iterable[Any],
) -> dict[str, Any]:
    """Return the integration-level appliance index payload."""
    items = appliance_insights_for_coordinators(coordinators)
    return {
        "status": "ok",
        "count": len(items),
        "items": [item.as_dict() for item in items],
    }


def setup_health_payload(
    coordinators: Iterable[Any],
    *,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return bounded Setup Health data for the panel."""
    requested_entry_id = str(entry_id or "").strip() or None
    coordinator = _setup_health_coordinator(coordinators, requested_entry_id)
    text = setup_health_panel_text()
    if coordinator is None:
        unavailable = text.get("unavailable", {})
        return {
            "status": "not_found",
            "requested_entry_id": requested_entry_id,
            "state": str(unavailable.get("state") or ""),
            "attributes": {},
            "checklist": [],
            "issues": [],
            "message": str(unavailable.get("message") or ""),
            "next_step": str(unavailable.get("next_step") or ""),
            "open_path": None,
            "checklist_ready_count": 0,
            "checklist_total_count": 0,
            "needs_attention": [],
            "text": text,
        }

    attributes = setup_health_attributes(coordinator)
    checklist = list(attributes.get("checklist") or [])
    issues = list(attributes.get("issues") or [])
    state = setup_health_value(coordinator)
    needs_attention = [
        item.as_dict() for item in attention_items_for_coordinators((coordinator,))
    ]
    raw_digest_settings = getattr(
        coordinator.store_data,
        "weekly_digest_settings",
        {},
    )
    digest_settings = (
        dict(raw_digest_settings) if isinstance(raw_digest_settings, Mapping) else {}
    )
    return {
        "status": "ok",
        "requested_entry_id": requested_entry_id,
        "state": state,
        "attributes": attributes,
        "checklist": checklist,
        "issues": issues,
        "message": attributes.get("issue_summary") or state,
        "next_step": (
            attributes.get("next_step") or attributes.get("recommended_action")
        ),
        "open_path": attributes.get("open_path"),
        "ready": attributes.get("ready"),
        "issue_count": attributes.get("issue_count"),
        "warning_count": attributes.get("warning_count"),
        "checklist_ready_count": attributes.get("checklist_ready_count"),
        "checklist_total_count": attributes.get("checklist_total_count"),
        "needs_attention": needs_attention,
        "weekly_digest": digest_settings.get("latest_report"),
        "weekly_digest_settings": {
            "enabled": digest_settings.get("enabled") is True,
            "delivery": str(digest_settings.get("delivery") or "panel_only"),
            "notify_service": str(digest_settings.get("notify_service") or ""),
        },
        "text": text,
    }


async def async_set_appliance_notification_preferences(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None,
    assignment_id: str | None,
    values: Any,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Save validated preferences using the backend-derived appliance key."""
    if entry_id:
        coordinators = (
            coordinator
            for coordinator in coordinators
            if str(getattr(coordinator, "entry_id", "")) == str(entry_id)
        )
    for coordinator in coordinators:
        detail = (
            appliance_detail_for_assignment(coordinator, str(assignment_id))
            if assignment_id
            else appliance_detail_for_circuit(coordinator, str(circuit_id))
        )
        if detail is None:
            continue
        appliance_key = detail.appliance_key or f"circuit:{detail.circuit_id}"
        preferences = preferences_from_dict(
            values if isinstance(values, Mapping) else {},
            appliance_key=appliance_key,
        )
        coordinator.store_data.appliance_notification_preferences[appliance_key] = (
            preferences.as_dict()
        )
        persistence = getattr(coordinator, "store_persistence", None)
        mark_dirty = getattr(persistence, "mark_dirty", None)
        if callable(mark_dirty):
            mark_dirty()
        save = getattr(persistence, "async_save_if_dirty", None)
        if callable(save):
            clock = getattr(coordinator, "current_time", None)
            now = clock() if callable(clock) else datetime.now(UTC)
            await save(now)
        return {"status": "saved", "notification_preferences": preferences.as_dict()}
    return {"status": "not_found", "notification_preferences": None}


async def async_set_weekly_digest_settings(
    coordinators: Iterable[Any],
    *,
    entry_id: str | None,
    values: Any,
) -> dict[str, Any]:
    coordinator = _setup_health_coordinator(coordinators, entry_id)
    if coordinator is None:
        return {"status": "not_found", "weekly_digest_settings": None}
    raw = values if isinstance(values, Mapping) else {}
    delivery = str(raw.get("delivery") or "panel_only")
    if delivery not in {
        "panel_only",
        "persistent_notification",
        "mobile_notification",
    }:
        delivery = "panel_only"
    settings = {
        "enabled": raw.get("enabled") is True,
        "delivery": delivery,
        "notify_service": (
            str(raw.get("notify_service") or "").strip()
            if delivery == "mobile_notification"
            else ""
        ),
    }
    existing = getattr(coordinator.store_data, "weekly_digest_settings", {})
    if isinstance(existing, Mapping) and existing.get("latest_report"):
        settings["latest_report"] = existing["latest_report"]
    coordinator.store_data.weekly_digest_settings = settings
    persistence = getattr(coordinator, "store_persistence", None)
    mark_dirty = getattr(persistence, "mark_dirty", None)
    if callable(mark_dirty):
        mark_dirty()
    save = getattr(persistence, "async_save_if_dirty", None)
    if callable(save):
        clock = getattr(coordinator, "current_time", None)
        await save(clock() if callable(clock) else datetime.now(UTC))
    return {"status": "saved", "weekly_digest_settings": settings}


async def async_set_appliance_expected_schedule(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None,
    assignment_id: str | None,
    values: Any,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Save bounded expected-schedule settings for a backend-resolved appliance."""
    if entry_id:
        coordinators = (
            coordinator
            for coordinator in coordinators
            if str(getattr(coordinator, "entry_id", "")) == str(entry_id)
        )
    for coordinator in coordinators:
        detail = (
            appliance_detail_for_assignment(coordinator, str(assignment_id))
            if assignment_id
            else appliance_detail_for_circuit(coordinator, str(circuit_id))
        )
        if detail is None:
            continue
        appliance_key = detail.appliance_key or f"circuit:{detail.circuit_id}"
        settings = schedule_settings_from_dict(
            values if isinstance(values, Mapping) else {},
            appliance_key=appliance_key,
        )
        stored = settings.as_dict()
        existing = coordinator.store_data.appliance_schedule_settings.get(
            appliance_key
        )
        coordinator.store_data.appliance_schedule_settings[appliance_key] = stored
        if existing != stored:
            coordinator.store_data.appliance_schedule_evidence.pop(
                appliance_key,
                None,
            )
        persistence = getattr(coordinator, "store_persistence", None)
        mark_dirty = getattr(persistence, "mark_dirty", None)
        if callable(mark_dirty):
            mark_dirty()
        save = getattr(persistence, "async_save_if_dirty", None)
        if callable(save):
            clock = getattr(coordinator, "current_time", None)
            await save(clock() if callable(clock) else datetime.now(UTC))
        if getattr(coordinator, "started", False):
            restart = getattr(coordinator, "async_start", None)
            if callable(restart):
                await restart(getattr(coordinator, "source_entities", ()))
        return {"status": "saved", "expected_schedule_settings": stored}
    return {"status": "not_found", "expected_schedule_settings": None}


def _setup_health_coordinator(
    coordinators: Iterable[Any],
    entry_id: str | None,
) -> Any | None:
    first = None
    for coordinator in coordinators:
        if first is None:
            first = coordinator
        if entry_id and str(getattr(coordinator, "entry_id", "")) == entry_id:
            return coordinator
    return first if entry_id is None else None


def _appliance_detail_payload(
    coordinator: Any,
    detail: ApplianceDetail,
    *,
    requested_circuit_id: str | None,
    requested_assignment_id: str | None,
    requested_entry_id: str | None,
) -> dict[str, Any]:
    appliance_key = detail.appliance_key or f"circuit:{detail.circuit_id}"
    preferences_by_appliance = getattr(
        coordinator.store_data,
        "appliance_notification_preferences",
        {},
    )
    raw_preferences = (
        preferences_by_appliance.get(appliance_key, {})
        if isinstance(preferences_by_appliance, Mapping)
        else {}
    )
    schedule_settings_by_appliance = getattr(
        coordinator.store_data,
        "appliance_schedule_settings",
        {},
    )
    raw_schedule_settings = (
        schedule_settings_by_appliance.get(appliance_key, {})
        if isinstance(schedule_settings_by_appliance, Mapping)
        else {}
    )
    schedule_contexts = getattr(
        coordinator.state,
        "expected_schedule_by_appliance",
        {},
    )
    schedule_context = (
        schedule_contexts.get(appliance_key)
        if isinstance(schedule_contexts, Mapping)
        else None
    )
    detail_payload = detail.as_dict()
    explanation = energy_change_explanation(detail)
    detail_payload["energy_change_explanation"] = (
        explanation.as_dict() if explanation is not None else None
    )
    return {
        "status": "ok",
        "requested_circuit_id": requested_circuit_id,
        "requested_assignment_id": requested_assignment_id,
        "requested_entry_id": requested_entry_id,
        "detail": detail_payload,
        "history": _appliance_detail_history_payload(coordinator, detail),
        "notification_preferences": preferences_from_dict(
            raw_preferences,
            appliance_key=appliance_key,
        ).as_dict(),
        "expected_schedule": {
            "settings": schedule_settings_from_dict(
                raw_schedule_settings,
                appliance_key=appliance_key,
            ).as_dict(),
            "context": (
                dict(schedule_context)
                if isinstance(schedule_context, Mapping)
                else None
            ),
            "schedule_entities": _schedule_entity_options(coordinator),
        },
        "actions": _appliance_detail_actions(coordinator, detail),
    }


def _schedule_entity_options(coordinator: Any) -> list[dict[str, str]]:
    states = getattr(getattr(coordinator, "hass", None), "states", None)
    async_all = getattr(states, "async_all", None)
    if not callable(async_all):
        return []
    try:
        entity_states = async_all("schedule")
    except TypeError:
        entity_states = async_all()
    options = []
    for state in entity_states:
        entity_id = str(getattr(state, "entity_id", "") or "")
        if not entity_id.startswith("schedule."):
            continue
        options.append(
            {
                "entity_id": entity_id,
                "name": str(getattr(state, "name", "") or entity_id),
            }
        )
    return sorted(options, key=lambda item: item["name"].casefold())[:100]


def _appliance_detail_actions(
    coordinator: Any,
    detail: ApplianceDetail,
) -> dict[str, dict[str, Any]]:
    actions: dict[str, dict[str, Any]] = {}
    if detail.source_type == "nilm_estimate" and detail.assignment_id:
        active_alert = detail.active_alerts[0] if detail.active_alerts else None
        alert_id = active_alert.alert_id if active_alert else None
        if active_alert and active_alert.evidence_path:
            actions["open_evidence"] = {
                "type": "navigate",
                "path": active_alert.evidence_path,
            }
        session_id = (
            str((detail.current_session or {}).get(ATTR_SESSION_ID) or "")
            or str((detail.last_matched_session or {}).get(ATTR_SESSION_ID) or "")
        )
        adjustable_session_id = (
            str((detail.last_matched_session or {}).get(ATTR_SESSION_ID) or "")
            if (detail.last_matched_session or {}).get("end")
            else ""
        )
        action_data = {
            ATTR_CIRCUIT_ID: detail.circuit_id,
            ATTR_ASSIGNMENT_ID: detail.assignment_id,
        }
        if session_id:
            action_data[ATTR_SESSION_ID] = session_id
            actions["mark_correct"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_SESSION,
                "data": dict(action_data),
            }
            actions["mark_wrong"] = {
                "domain": DOMAIN,
                "service": SERVICE_REJECT_NILM_SESSION,
                "data": dict(action_data),
            }
        if adjustable_session_id:
            adjust_query = urlencode(
                {
                    ATTR_CIRCUIT_ID: detail.circuit_id,
                    ATTR_ASSIGNMENT_ID: detail.assignment_id,
                    ATTR_SESSION_ID: adjustable_session_id,
                    "nilm_workspace": "1",
                    "adjust_interval": "1",
                }
            )
            actions["adjust_interval"] = {
                "type": "navigate",
                "path": f"/{PANEL_URL_PATH}?{adjust_query}",
            }
        if alert_id:
            actions["mark_correct"] = {
                "domain": DOMAIN,
                "service": SERVICE_MARK_NILM_APPLIANCE_CORRECT,
                "data": {ATTR_ALERT_ID: alert_id},
            }
            actions["mark_wrong"] = {
                "domain": DOMAIN,
                "service": SERVICE_MARK_NILM_APPLIANCE_WRONG,
                "data": {ATTR_ALERT_ID: alert_id},
            }
            for key, service in (
                ("mark_expected", SERVICE_MARK_ALERT_EXPECTED),
                ("mark_unhelpful", SERVICE_MARK_ALERT_UNHELPFUL),
            ):
                actions[key] = {
                    "domain": DOMAIN,
                    "service": service,
                    "data": {ATTR_ALERT_ID: alert_id},
                }
        review_query = urlencode(
            {
                **action_data,
                "nilm_workspace": "1",
            }
        )
        actions["review_nilm_assignment"] = {
            "type": "navigate",
            "path": f"/{PANEL_URL_PATH}?{review_query}",
            "data": action_data,
        }
        return actions

    config = _config_for_circuit(coordinator, detail.circuit_id)
    latest_alert = _latest_alert_for_circuit(coordinator, detail.circuit_id)
    alert_id = (
        notification_id_for_alert(latest_alert)
        if latest_alert
        else (detail.active_alerts[0].alert_id if detail.active_alerts else None)
    )
    if alert_id and detail.evidence_path:
        actions["open_evidence"] = {
            "type": "navigate",
            "path": detail.evidence_path,
        }
    actions.update(
        _actions_for_context(
            coordinator,
            config=config,
            alert_id=alert_id,
            circuit_id=detail.circuit_id,
        )
    )
    return actions


def _appliance_detail_history_payload(
    coordinator: Any,
    detail: ApplianceDetail,
) -> dict[str, Any]:
    config = _config_for_circuit(coordinator, detail.circuit_id)
    entity_series = (
        _source_history_series(config)
        if config is not None and detail.source_type != "nilm_estimate"
        else _nilm_history_series(coordinator, detail.assignment_id)
    )
    embedded_series = (
        _nilm_embedded_history_series(coordinator, detail)
        if detail.source_type == "nilm_estimate" and not entity_series
        else []
    )
    if embedded_series:
        entity_series = [
            {"entity_id": embedded_series[0][0]["entity_id"], "unit": "W"}
        ]
    payload = {
        "entities": [item["entity_id"] for item in entity_series],
        "entity_series": entity_series,
        "default_hours": DEFAULT_APPLIANCE_DETAIL_HISTORY_HOURS,
        "period_hours": list(APPLIANCE_DETAIL_HISTORY_PERIOD_HOURS),
    }
    if embedded_series:
        payload["embedded_series"] = embedded_series
    return payload


def _source_history_series(config: Any) -> list[dict[str, str]]:
    series: list[dict[str, str]] = []
    for sensor in getattr(config, "sensors", ()) or ():
        entity_id = str(getattr(sensor, "entity_id", "") or "").strip()
        if not entity_id:
            continue
        role = getattr(sensor, "role", None)
        try:
            role = role if isinstance(role, SensorRole) else SensorRole(role)
        except (TypeError, ValueError):
            role = None
        unit = str(getattr(sensor, "unit", "") or _HISTORY_UNIT_BY_ROLE.get(role, ""))
        series.append({"entity_id": entity_id, "unit": unit})
    return series


def _nilm_history_series(
    coordinator: Any,
    assignment_id: str | None,
) -> list[dict[str, str]]:
    if not assignment_id:
        return []
    states = getattr(getattr(coordinator, "hass", None), "states", None)
    async_all = getattr(states, "async_all", None)
    if not callable(async_all):
        return []
    try:
        entity_states = async_all("sensor")
    except TypeError:
        entity_states = async_all()
    series: list[dict[str, str]] = []
    for state in entity_states:
        attributes = getattr(state, "attributes", {})
        if not isinstance(attributes, Mapping):
            continue
        if str(attributes.get("assignment_id") or "") != assignment_id:
            continue
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        entity_id = str(getattr(state, "entity_id", "") or "").strip()
        if entity_id and unit:
            series.append({"entity_id": entity_id, "unit": unit})
    return series


def _nilm_embedded_history_series(
    coordinator: Any,
    detail: ApplianceDetail,
) -> list[list[dict[str, str]]]:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    sessions_by_circuit = getattr(store_data, "nilm_session_history_by_circuit", {})
    if not isinstance(assignments_by_circuit, Mapping) or not isinstance(
        sessions_by_circuit,
        Mapping,
    ):
        return []
    assignment = next(
        (
            item
            for item in _iter_items(assignments_by_circuit.get(detail.circuit_id))
            if isinstance(item, Mapping)
            and str(item.get("assignment_id") or "") == detail.assignment_id
        ),
        None,
    )
    if assignment is None:
        return []
    session_ids = {
        str(value or "")
        for key in ("session_ids", "confirmed_session_ids")
        for value in _iter_items(assignment.get(key))
        if str(value or "")
    }
    appliance_id = re.sub(
        r"[^a-z0-9_]+",
        "_",
        str(assignment.get("appliance_id") or detail.assignment_id).lower(),
    ).strip("_")
    entity_id = f"sensor.{appliance_id}_estimated_power"
    rows: list[dict[str, str]] = []
    for session in _iter_items(sessions_by_circuit.get(detail.circuit_id)):
        if not isinstance(session, Mapping):
            continue
        session_owner = str(session.get("assignment_id") or "").strip()
        matches = (
            session_owner == detail.assignment_id
            if session_owner
            else str(session.get("session_id") or "") in session_ids
        )
        start = _datetime_from_iso(session.get("start"))
        if not matches or start is None:
            continue
        try:
            power = max(float(session.get("median_power_w") or 0.0), 0.0)
        except (TypeError, ValueError):
            continue
        end = _datetime_from_iso(session.get("end"))
        rows.extend(
            [
                _history_row(entity_id, 0.0, start - timedelta(milliseconds=1)),
                _history_row(entity_id, power, start),
            ]
        )
        if end is not None:
            rows.extend(
                [
                    _history_row(entity_id, power, end),
                    _history_row(entity_id, 0.0, end + timedelta(milliseconds=1)),
                ]
            )
    rows.sort(key=lambda row: row["last_changed"])
    return [rows] if rows else []


def _history_row(entity_id: str, value: float, timestamp: datetime) -> dict[str, str]:
    return {
        "entity_id": entity_id,
        "state": f"{value:g}",
        "last_changed": timestamp.isoformat(),
    }


def nilm_workspace_payload(
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None = None,
    hours: Any = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return bounded NILM workspace data for one mains NILM circuit."""

    target = _nilm_workspace_target(
        tuple(coordinators),
        circuit_id,
        entry_id=entry_id,
    )
    if target is None:
        return {
            "status": "not_found",
            "requested_circuit_id": circuit_id or None,
            "message": _panel_text("nilm_workspace", "no_mains_circuit"),
        }

    coordinator, config = target
    selected_entry_id = str(getattr(coordinator, "entry_id", "") or "")
    edges = _nilm_edges_for_circuit(coordinator, config.circuit_id)
    recent_edges = sorted(edges, key=lambda edge: edge.timestamp)[
        -MAX_NILM_WORKSPACE_EDGES:
    ]
    signatures = _nilm_workspace_signatures(coordinator, config.circuit_id)
    known_load_overlays = _nilm_known_load_overlays(
        coordinator,
        config.circuit_id,
    )
    solar_overlays = _nilm_solar_overlays(coordinator, config.circuit_id)
    all_label_intervals = _nilm_label_intervals_for_circuit(
        coordinator,
        config.circuit_id,
        limit=None,
    )
    label_intervals = all_label_intervals[:MAX_NILM_WORKSPACE_LABEL_INTERVALS]
    assignments = _nilm_assignments_for_circuit(
        coordinator,
        config.circuit_id,
        label_intervals=all_label_intervals,
    )
    assignment_options = _nilm_assignment_options(assignments)
    session_display_labels = _nilm_session_display_labels(signatures, assignments)
    reviewed_session_ids = _nilm_reviewed_session_ids_by_assignment(assignments)
    stored_sessions = _nilm_session_history_for_circuit(
        coordinator,
        config.circuit_id,
        reviewed_session_ids=reviewed_session_ids,
    )
    all_generated_sessions = _nilm_workspace_sessions(
        edges,
        config.circuit_id,
        signatures=signatures,
        assignments=assignments,
        reviewed_session_ids=reviewed_session_ids,
        limit=None,
    )
    all_sessions = _nilm_workspace_visible_sessions(
        _merge_nilm_session_payloads(all_generated_sessions, stored_sessions),
        signatures,
        assignments,
    )
    all_sessions = _add_nilm_session_display_labels(
        all_sessions,
        session_display_labels,
    )
    sessions = _add_nilm_session_display_labels(
        _nilm_workspace_visible_sessions(
            _merge_nilm_session_payloads(
                _nilm_workspace_sessions(
                    recent_edges,
                    config.circuit_id,
                    signatures=signatures,
                    assignments=assignments,
                    reviewed_session_ids=reviewed_session_ids,
                ),
                stored_sessions,
            ),
            signatures,
            assignments,
        ),
        session_display_labels,
    )[:MAX_NILM_WORKSPACE_SESSIONS]
    _add_nilm_assignment_options(signatures, assignment_options)
    _add_nilm_assignment_options(label_intervals, assignment_options)
    _add_nilm_assignment_options(sessions, assignment_options)
    virtual_appliances = _nilm_virtual_appliances_for_assignments(
        assignments,
        sessions,
        edges,
    )
    validation = _nilm_validation_payload(
        all_label_intervals,
        all_sessions,
        assignments,
    )
    lanes = _nilm_workspace_lanes(signatures, assignments, label_intervals)
    return {
        "status": "ok",
        "circuit": _circuit_payload(config),
        "history": _nilm_workspace_history_payload(
            config,
            known_load_overlays,
            solar_overlays,
            hours=hours,
            entry_id=selected_entry_id,
        ),
        "known_load_overlays": known_load_overlays,
        "solar_overlays": solar_overlays,
        "signatures": signatures,
        "signature_count": len(signatures),
        "label_intervals": label_intervals,
        "label_interval_count": len(label_intervals),
        "assignments": assignments,
        "assignment_count": len(assignments),
        "virtual_appliances": virtual_appliances,
        "virtual_appliance_count": len(virtual_appliances),
        "validation": validation,
        "lanes": lanes,
        "lane_counts": {
            key: sum(
                len(value[item_key])
                for item_key in ("assignment_ids", "signature_ids", "interval_ids")
            )
            for key, value in lanes.items()
        },
        "selection_guidance": _nilm_selection_guidance(),
        "actions": {
            "label_interval": _nilm_label_interval_action(config),
        },
        "edges": [
            _nilm_edge_payload(edge)
            for edge in recent_edges
        ],
        "edge_count": len(edges),
        "sessions": sessions,
        "session_count": len(all_sessions),
    }


def _payload_for_alert(
    status: str,
    coordinator: Any,
    alert: AlertEvidence,
    *,
    requested_alert_id: str | None,
    requested_circuit_id: str | None,
    requested_feature: str | None,
    requested_recommendation_id: str | None,
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
            "text": alert_evidence_panel_text(),
        },
        requested_feature,
        requested_recommendation_id=requested_recommendation_id,
    )


def _with_requested_feature(
    payload: dict[str, Any],
    requested_feature: str | None,
    *,
    requested_recommendation_id: str | None = None,
) -> dict[str, Any]:
    if requested_feature:
        payload["requested_feature"] = requested_feature
    if requested_recommendation_id:
        payload["requested_recommendation_id"] = requested_recommendation_id
        selected = _selected_recommendation(
            payload.get("setting_recommendations"),
            requested_recommendation_id,
        )
        if selected is not None:
            payload["selected_recommendation"] = selected
    return payload


def _selected_recommendation(
    recommendations: Any,
    recommendation_id: str,
) -> dict[str, Any] | None:
    for recommendation in _iter_items(recommendations):
        if not isinstance(recommendation, Mapping):
            continue
        if recommendation.get(ATTR_RECOMMENDATION_ID) == recommendation_id:
            return dict(recommendation)
    return None


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
        actions.update(
            {
                "pause_alerts": _pause_alerts_action(
                    coordinator,
                    circuit_id,
                    data=circuit_data,
                ),
                "relearn_baseline": {
                    "domain": DOMAIN,
                    "service": SERVICE_RELEARN_BASELINE,
                    "data": circuit_data,
                },
                "open_appliance_detail": {
                    "type": "navigate",
                    "label": _panel_text("actions", "labels", "open_appliance_detail"),
                    "path": _circuit_appliance_detail_panel_path(circuit_id),
                },
                "open_advanced_circuit_settings": (
                    _advanced_circuit_settings_action(coordinator, config)
                ),
            }
        )

    recommendations = _setting_recommendations_for_circuit(
        coordinator,
        circuit_id,
    )
    recommendation_id = _first_pending_recommendation_id(recommendations)
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


def _circuit_appliance_detail_panel_path(circuit_id: str) -> str:
    return (
        f"/{PANEL_URL_PATH}?"
        f"{urlencode({ATTR_CIRCUIT_ID: circuit_id, 'appliance_detail': '1'})}"
    )


def _advanced_circuit_settings_path(
    coordinator: Any,
    config: CircuitConfig | None,
) -> str:
    del coordinator, config
    return f"/config/integrations/integration/{DOMAIN}"


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


def _pending_setting_recommendations(coordinator: Any) -> list[dict[str, Any]]:
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {})
    if not isinstance(by_circuit, Mapping):
        return []
    pending = []
    for recommendations in by_circuit.values():
        for item in _iter_items(recommendations):
            payload = _recommendation_payload(item, coordinator=coordinator)
            if str(payload.get("status") or "pending") == "pending":
                pending.append(payload)
    return pending


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
    _add_setting_impact_preview(payload, coordinator)
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
    return _panel_text("recommendations", "suggested_setting")


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
            "unavailable_label": _panel_text("recommendations", "not_pending"),
        },
        "dismiss": {
            "domain": DOMAIN,
            "service": SERVICE_DISMISS_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_pending,
            "unavailable_reason": "not_pending",
            "unavailable_label": _panel_text("recommendations", "not_pending"),
        },
        "undo": {
            "domain": DOMAIN,
            "service": SERVICE_UNDO_SETTING_RECOMMENDATION,
            "data": dict(data),
            "enabled": is_applied,
            "unavailable_reason": "not_applied",
            "unavailable_label": _panel_text("recommendations", "not_applied"),
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
    control_text = recommendation_setting_control_text(setting_key)
    if control_text:
        payload["what_this_controls"] = control_text
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
    payload["setting_explanation"] = _recommendation_setting_explanation(payload)


def _recommendation_setting_explanation(payload: Mapping[str, Any]) -> dict[str, Any]:
    explanation = {
        "what_this_controls": payload.get("what_this_controls"),
        "current_value": payload.get("current_value"),
        "default_value": payload.get("default_value"),
        "suggested_value": payload.get("suggested_value"),
        "why_suggestion_exists": payload.get("reason"),
        "expected_effect": payload.get("expected_effect"),
        "reset_to_default": True,
    }
    return {key: value for key, value in explanation.items() if value is not None}


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
        if isinstance(value, (Mapping, list, tuple, set)):
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


def _first_pending_recommendation_id(
    recommendations: list[dict[str, Any]],
) -> str | None:
    for recommendation in recommendations:
        if str(recommendation.get("status") or "pending") != "pending":
            continue
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
    workspace_paths = _nilm_workspace_paths(coordinator, circuit_id)
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
        **workspace_paths,
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
                "unavailable_label": _panel_text(
                    "nilm_workspace",
                    "no_merge_target_action",
                ),
            }
        )
    return {
        "label": {
            "domain": DOMAIN,
            "service": SERVICE_LABEL_NILM_SIGNATURE,
            "data": dict(data),
            "requires": [ATTR_LABEL],
        },
        "assign": {
            "domain": DOMAIN,
            "service": SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
            "data": dict(data),
            "requires": [ATTR_LABEL],
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
    payload["source_type"] = "nilm_estimate"
    payload["source_label"] = _panel_text("source_labels", "nilm_estimate")
    if "typical_watts" in signature:
        payload["typical_power_w"] = signature["typical_watts"]
    payload["why_grouped"] = _nilm_signature_explanation(signature)
    review_state = _nilm_review_state(signature)
    if review_state:
        payload["review_state"] = review_state
    return payload


def _nilm_signature_explanation(signature: Mapping[str, Any]) -> str:
    typical_watts = _clamped_float(signature.get("typical_watts"), default=0.0)
    if typical_watts > 0:
        power = _format_power_label(typical_watts)
        return f"Grouped by similar NILM on/off edges around {power}."
    return "Grouped by similar NILM on/off edges from mains power."


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


def _nilm_workspace_target(
    coordinators: Iterable[Any],
    circuit_id: str | None,
    *,
    entry_id: str | None = None,
) -> tuple[Any, Any] | None:
    requested_circuit_id = str(circuit_id or "").strip()
    requested_entry_id = str(entry_id or "").strip()
    sensor_fallback: tuple[Any, Any] | None = None
    for coordinator in coordinators:
        if requested_entry_id and str(
            getattr(coordinator, "entry_id", "") or ""
        ) != requested_entry_id:
            continue
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            config_circuit_id = str(getattr(config, "circuit_id", "") or "").strip()
            if not config_circuit_id:
                continue
            if requested_circuit_id and config_circuit_id != requested_circuit_id:
                continue
            if _is_explicit_nilm_config(config):
                return coordinator, config
            if sensor_fallback is None and _is_sensor_backed_mains_config(config):
                sensor_fallback = (coordinator, config)
    return sensor_fallback


def _is_explicit_nilm_config(config: Any) -> bool:
    mode = getattr(config, "mode", None)
    appliance_profile = getattr(config, "appliance_profile", None)
    return (
        mode is CircuitMode.MAINS_NILM
        or appliance_profile is ApplianceProfile.MAINS_NILM
        or str(mode) == CircuitMode.MAINS_NILM.value
        or str(appliance_profile) == ApplianceProfile.MAINS_NILM.value
    )


def _is_sensor_backed_mains_config(config: Any) -> bool:
    return (
        str(getattr(config, "circuit_id", "") or "").strip() == "mains"
        and bool(_sensor_entity_ids(config))
    )


async def nilm_workspace_history_payload(
    hass: Any,
    coordinators: Iterable[Any],
    *,
    circuit_id: str | None = None,
    hours: Any = None,
    entry_id: str | None = None,
) -> list[list[dict[str, Any]]]:
    """Return capped HA history rows for the NILM workspace."""

    target = _nilm_workspace_target(
        tuple(coordinators),
        circuit_id,
        entry_id=entry_id,
    )
    if target is None:
        return []
    coordinator, config = target
    known_load_overlays = _nilm_known_load_overlays(
        coordinator,
        config.circuit_id,
    )
    solar_overlays = _nilm_solar_overlays(coordinator, config.circuit_id)
    history = _nilm_workspace_history_payload(
        config,
        known_load_overlays,
        solar_overlays,
        hours=hours,
        entry_id=str(getattr(coordinator, "entry_id", "") or ""),
    )
    return await _async_history_rows(
        hass,
        history["start"],
        history["end"],
        history["entities"],
    )


def _nilm_workspace_signatures(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    signatures = _nilm_signatures_for_circuit(coordinator, circuit_id)
    return [
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
                include_all_nilm=True,
            ),
        }
        for signature in signatures
        if signature.get(ATTR_SIGNATURE_ID)
    ]


def _nilm_label_intervals_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    limit: int | None = MAX_NILM_WORKSPACE_LABEL_INTERVALS,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    intervals_by_circuit = getattr(store_data, "nilm_label_intervals_by_circuit", {})
    intervals = (
        [
            dict(item)
            for item in _iter_items(intervals_by_circuit.get(circuit_id, ()))
            if isinstance(item, dict)
        ]
        if isinstance(intervals_by_circuit, Mapping)
        else []
    )
    payloads = [
        _nilm_label_interval_payload(circuit_id, interval)
        for interval in intervals
    ]
    return payloads if limit is None else payloads[:limit]


def _nilm_label_interval_payload(
    circuit_id: str,
    interval: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        str(key): value
        for key, value in interval.items()
        if key != "actions"
    }
    interval_id = str(payload.get(ATTR_INTERVAL_ID) or "").strip()
    if interval_id:
        payload["actions"] = {
            "delete": {
                "domain": DOMAIN,
                "service": SERVICE_DELETE_NILM_LABEL_INTERVAL,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_INTERVAL_ID: interval_id,
                },
            },
            "assign": {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_INTERVAL_ID: interval_id,
                },
                "requires": [ATTR_LABEL],
            },
        }
    return payload


def _nilm_label_interval_action(config: CircuitConfig) -> dict[str, Any]:
    data = {ATTR_CIRCUIT_ID: config.circuit_id}
    entity_ids = _sensor_entity_ids(config)
    if entity_ids:
        data[ATTR_MAINS_ENTITY_ID] = entity_ids[0]
    return {
        "domain": DOMAIN,
        "service": SERVICE_LABEL_NILM_INTERVAL,
        "data": data,
        "requires": [ATTR_START, ATTR_END, ATTR_LABEL, ATTR_APPLIANCE_PROFILE],
        "profile_options": _nilm_appliance_profile_options(),
    }


def _nilm_sensor_label_interval_action(
    config: CircuitConfig,
    known_load_overlays: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    action = _nilm_label_interval_action(config)
    action["service"] = SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS
    action["requires"] = [
        ATTR_START,
        ATTR_END,
        ATTR_LABEL,
        ATTR_GROUND_TRUTH_ENTITY_ID,
    ]
    ground_truth_options = []
    seen_circuits: set[str] = set()
    for overlay in known_load_overlays:
        label = str(overlay.get("name") or overlay.get("circuit_id") or "").strip()
        circuit_id = str(overlay.get("circuit_id") or "").strip()
        entity_text = next(
            (
                str(entity_id or "").strip()
                for entity_id in _iter_items(overlay.get("entity_ids"))
                if str(entity_id or "").strip()
            ),
            "",
        )
        key = circuit_id or entity_text
        if not key or key in seen_circuits or not entity_text:
            continue
        seen_circuits.add(key)
        ground_truth_options.append(
            {"value": entity_text, "label": label or entity_text},
        )
    if ground_truth_options:
        action["ground_truth_options"] = ground_truth_options
    return action


def _nilm_assignments_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return []
    assignments = [
        item
        for item in _iter_items(assignments_by_circuit.get(circuit_id, ()))
        if isinstance(item, dict)
    ]
    direct_circuit_options = _nilm_direct_circuit_options(
        coordinator,
        circuit_id,
    )
    return [
        _nilm_assignment_payload(
            circuit_id,
            item,
            assignments,
            label_intervals=label_intervals,
            direct_circuit_options=direct_circuit_options,
        )
        for item in assignments
    ]


def _nilm_assignment_options(
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if (
            not assignment_id
            or str(assignment.get("lifecycle_state") or "").lower() == "retired"
        ):
            continue
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment_id,
        ).strip()
        options.append({"value": assignment_id, "label": label})
    return options


def _add_nilm_assignment_options(
    items: Iterable[dict[str, Any]],
    assignment_options: list[dict[str, str]],
) -> None:
    if not assignment_options:
        return
    for item in items:
        actions = item.get("actions")
        assign = actions.get("assign") if isinstance(actions, dict) else None
        if isinstance(assign, dict):
            assign["assignment_options"] = list(assignment_options)


def _nilm_assignment_payload(
    circuit_id: str,
    assignment: Mapping[str, Any],
    assignments: Iterable[Mapping[str, Any]] = (),
    *,
    label_intervals: Iterable[Mapping[str, Any]] = (),
    direct_circuit_options: Iterable[Mapping[str, str]] = (),
) -> dict[str, Any]:
    payload = {
        str(key): value
        for key, value in assignment.items()
        if key != "actions"
    }
    assignment_id = str(payload.get(ATTR_ASSIGNMENT_ID) or "").strip()
    if not assignment_id:
        return payload

    payload["appliance_detail_path"] = _nilm_appliance_detail_panel_path(
        assignment_id
    )
    state = str(payload.get("lifecycle_state") or "").strip().lower()
    action_data = {ATTR_CIRCUIT_ID: circuit_id, ATTR_ASSIGNMENT_ID: assignment_id}
    actions: dict[str, dict[str, Any]] = {}
    if state != "retired":
        actions["rename"] = {
            "domain": DOMAIN,
            "service": SERVICE_RENAME_NILM_APPLIANCE,
            "data": dict(action_data),
            "requires": [ATTR_LABEL],
        }
        actions["change_profile"] = {
            "domain": DOMAIN,
            "service": SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
            "data": dict(action_data),
            "requires": [ATTR_APPLIANCE_PROFILE],
        }
        actions["change_profile"]["profile_options"] = (
            _nilm_appliance_profile_options(payload.get(ATTR_APPLIANCE_PROFILE))
        )
        direct_options = [dict(option) for option in direct_circuit_options]
        if direct_options and payload.get("conversion_state") != "direct_meter":
            actions["convert_to_direct_meter"] = {
                "domain": DOMAIN,
                "service": SERVICE_CONVERT_NILM_APPLIANCE_TO_DIRECT_METER,
                "data": dict(action_data),
                "requires": ["direct_circuit_id"],
                "target_options": direct_options,
            }
        if _nilm_assignment_has_ground_truth_intervals(payload, label_intervals):
            actions["validate_history"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
                "data": dict(action_data),
            }
        target_options = _nilm_assignment_target_options(assignment_id, assignments)
        if target_options:
            actions["merge"] = {
                "domain": DOMAIN,
                "service": SERVICE_MERGE_NILM_ASSIGNMENTS,
                "data": {
                    ATTR_CIRCUIT_ID: circuit_id,
                    ATTR_SOURCE_ASSIGNMENT_ID: assignment_id,
                },
                "requires": [ATTR_TARGET_ASSIGNMENT_ID],
                "target_options": target_options,
            }
        if payload.get("publish_entities") is True or state == "published":
            actions["unpublish"] = {
                "domain": DOMAIN,
                "service": SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
                "data": dict(action_data),
            }
        elif (
            state not in {"expected", "ignored"}
            and payload.get("conversion_state") != "direct_meter"
        ):
            actions["publish"] = {
                "domain": DOMAIN,
                "service": SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
                "data": dict(action_data),
            }
        actions["retire"] = {
            "domain": DOMAIN,
            "service": SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
            "data": dict(action_data),
        }
    if actions:
        payload["actions"] = actions
    return payload


def _add_setting_impact_preview(payload: dict[str, Any], coordinator: Any) -> None:
    setting_key = str(payload.get("setting_key") or "").strip()
    circuit_id = str(payload.get("circuit_id") or "").strip()
    if (
        not setting_key
        or not circuit_id
        or "current_value" not in payload
        or "suggested_value" not in payload
    ):
        return
    clock = getattr(coordinator, "current_time", None)
    now = clock() if callable(clock) else datetime.now(UTC)
    preview = build_setting_impact_preview(
        setting_key,
        payload["current_value"],
        payload["suggested_value"],
        setting_preview_observations(
            getattr(coordinator, "store_data", None),
            circuit_id,
            setting_key,
        ),
        now=now,
    )
    payload["impact_preview"] = preview.as_dict()


def _nilm_direct_circuit_options(
    coordinator: Any,
    mains_circuit_id: str,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if not isinstance(config, CircuitConfig):
            continue
        if config.circuit_id == mains_circuit_id or config.mode in {
            CircuitMode.MAINS_NILM,
            CircuitMode.MIXED,
        } or config.appliance_profile in {
            ApplianceProfile.MAINS_NILM,
            ApplianceProfile.MIXED,
            ApplianceProfile.SOLAR_INVERTER,
        }:
            continue
        options.append({"value": config.circuit_id, "label": config.name})
    return options


def _nilm_assignment_has_ground_truth_intervals(
    assignment: Mapping[str, Any],
    label_intervals: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        isinstance(interval, Mapping)
        and str(interval.get("ground_truth_entity_id") or "").strip()
        and _nilm_validation_assignment_matches(interval, assignment)
        for interval in label_intervals
    )


def _nilm_assignment_target_options(
    assignment_id: str,
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for assignment in assignments:
        target_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not target_id or target_id == assignment_id:
            continue
        if str(assignment.get("lifecycle_state") or "").strip().lower() == "retired":
            continue
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or target_id
        ).strip()
        options.append({"value": target_id, "label": label})
    return options


def _nilm_virtual_appliances_for_assignments(
    assignments: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    edges: list[NilmEdge],
) -> list[dict[str, Any]]:
    reference_date = _nilm_workspace_reference_date(edges, sessions)
    virtual_appliances = []
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        if not assignment_id:
            continue
        assignment_session_ids = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("session_ids"))
            if str(value or "").strip()
        }
        assignment_sessions = [
            session
            for session in sessions
            if session.get("assignment_id") == assignment_id
            or str(session.get("session_id") or "").strip() in assignment_session_ids
        ]
        open_session = _latest_nilm_session(
            session for session in assignment_sessions if not session.get("end")
        )
        latest_session = open_session or _latest_nilm_session(assignment_sessions)
        virtual_appliances.append(
            {
                "appliance_key": f"nilm:{assignment_id}",
                "appliance_id": str(
                    assignment.get("appliance_id") or assignment_id
                ),
                "assignment_id": assignment_id,
                "display_name": str(
                    assignment.get("display_name")
                    or assignment.get("appliance_id")
                    or assignment_id
                ),
                "is_running": open_session is not None,
                "estimated_power_w": (
                    _round_float(open_session.get("median_power_w"))
                    if open_session
                    else 0.0
                ),
                "estimated_energy_kwh_today": _nilm_daily_energy(
                    assignment_sessions,
                    reference_date,
                ),
                "confidence": _clamped_float(
                    assignment.get("confidence"),
                    default=0.0,
                    upper=1.0,
                ),
                "last_seen": _nilm_session_last_seen(latest_session),
                "active_signature_id": (
                    str(open_session.get("signature_fingerprint") or "")
                    if open_session
                    else None
                ),
                "active_session_id": (
                    str(open_session.get("session_id") or "")
                    if open_session
                    else None
                ),
                "model_status": str(
                    assignment.get("lifecycle_state") or "candidate"
                ),
                "source_type": "nilm_estimate",
                "source_label": _panel_text("source_labels", "nilm_estimate"),
                "estimated": True,
                "mains_circuit_id": str(
                    assignment.get("mains_circuit_id") or ""
                ),
                "appliance_detail_api_path": (
                    f"{APPLIANCE_DETAIL_API_PATH}?"
                    f"{urlencode({ATTR_ASSIGNMENT_ID: assignment_id})}"
                ),
                "appliance_detail_path": _nilm_appliance_detail_panel_path(
                    assignment_id
                ),
            }
        )
    return virtual_appliances


def _nilm_appliance_detail_panel_path(assignment_id: str) -> str:
    return (
        f"/{PANEL_URL_PATH}?"
        f"{urlencode({ATTR_ASSIGNMENT_ID: assignment_id, 'appliance_detail': '1'})}"
    )


def _nilm_appliance_profile_options(
    current_profile: Any = None,
) -> list[dict[str, str]]:
    values = (
        str(current_profile or "").strip(),
        *(
            item.value
            for item in ApplianceProfile
            if item is not ApplianceProfile.MAINS_NILM
        ),
    )
    return [
        {"value": profile, "label": friendly_feature_name(profile)}
        for index, profile in enumerate(values)
        if profile and profile not in values[:index]
    ]


def _nilm_workspace_lanes(
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    label_intervals: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    lanes = {
        "needs_review": _nilm_lane("Needs Review"),
        "assigned": _nilm_lane("Assigned"),
        "published": _nilm_lane("Published"),
        "ignored_expected": _nilm_lane("Ignored / Expected"),
    }
    assigned_signature_ids = _nilm_assigned_signature_ids(assignments)
    for signature in signatures:
        signature_id = str(signature.get(ATTR_SIGNATURE_ID) or "").strip()
        if not signature_id:
            continue
        if _nilm_signature_hidden(signature):
            lanes["ignored_expected"]["signature_ids"].append(signature_id)
        elif _nilm_signature_identifiers(signature).isdisjoint(
            assigned_signature_ids,
        ):
            lanes["needs_review"]["signature_ids"].append(signature_id)

    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        state = str(assignment.get("lifecycle_state") or "").strip().lower()
        confidence = _clamped_float(assignment.get("confidence"), default=0.0)
        if _nilm_assignment_hidden(assignment):
            lane = "ignored_expected"
        elif assignment.get("publish_entities") is True or state == "published":
            lane = "published"
        elif state in {
            "needs_validation",
            "conflict",
            "low_confidence",
            "validated",
            "ready_to_publish",
        } or confidence < 0.8:
            lane = "needs_review"
        else:
            lane = "assigned"
        lanes[lane]["assignment_ids"].append(assignment_id)
    assigned_interval_ids = {
        str(value or "").strip()
        for assignment in assignments
        for value in _iter_items(assignment.get("label_interval_ids"))
        if str(value or "").strip()
    }
    for interval in label_intervals:
        interval_id = str(interval.get(ATTR_INTERVAL_ID) or "").strip()
        if (
            interval_id
            and interval_id not in assigned_interval_ids
            and not str(interval.get(ATTR_ASSIGNMENT_ID) or "").strip()
        ):
            lanes["needs_review"]["interval_ids"].append(interval_id)
    return lanes


def _nilm_lane(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "assignment_ids": [],
        "signature_ids": [],
        "interval_ids": [],
    }


def _nilm_assignment_hidden(assignment: Mapping[str, Any]) -> bool:
    return str(assignment.get("lifecycle_state") or "").strip().lower() in {
        "ignored",
        "expected",
        "retired",
    }


def _nilm_signature_hidden(signature: Mapping[str, Any]) -> bool:
    state = str(signature.get("review_state") or "").strip().lower()
    return bool(
        signature.get("ignored")
        or signature.get("expected")
        or state in {"ignored", "expected", "merged"}
    )


def _nilm_assigned_signature_ids(
    assignments: Iterable[Mapping[str, Any]],
) -> set[str]:
    signature_ids: set[str] = set()
    for assignment in assignments:
        for key in ("signature_fingerprints", "signature_ids"):
            signature_ids.update(
                str(value or "").strip()
                for value in _iter_items(assignment.get(key))
                if str(value or "").strip()
            )
        for key in ("feedback_fingerprint", "signature_fingerprint", "fingerprint"):
            value = str(assignment.get(key) or "").strip()
            if value:
                signature_ids.add(value)
    return signature_ids


def _nilm_signature_identifiers(signature: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for key in (
        ATTR_SIGNATURE_ID,
        "signature_id",
        "fingerprint",
        "feedback_fingerprint",
        "signature_fingerprint",
    ):
        value = str(signature.get(key) or "").strip()
        if value:
            identifiers.add(value)
    for key in ("signature_fingerprints", "signature_ids"):
        identifiers.update(
            str(value or "").strip()
            for value in _iter_items(signature.get(key))
            if str(value or "").strip()
        )
    return identifiers


def _nilm_selection_guidance() -> dict[str, Any]:
    return {
        "snap_to_edges": True,
        "show_likely_paired_off_edge": True,
        "preview_interval_kwh": True,
        "show_known_load_overlap": True,
    }


def _nilm_validation_payload(
    label_intervals: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    ground_truth_intervals = [
        interval
        for interval in label_intervals
        if str(interval.get("ground_truth_entity_id") or "").strip()
    ]
    predictions = [
        session
        for session in sessions
        if session.get("end") and str(session.get("assignment_id") or "").strip()
    ]
    assignment_by_id = {
        str(assignment.get("assignment_id") or "").strip(): assignment
        for assignment in assignments
        if str(assignment.get("assignment_id") or "").strip()
    }
    matched_prediction_ids: set[str] = set()
    preview = []
    for interval in ground_truth_intervals:
        session, overlap = _nilm_validation_best_match(
            interval,
            predictions,
            assignment_by_id,
            matched_prediction_ids,
        )
        if session is not None:
            matched_prediction_ids.add(str(session.get("session_id") or ""))
        preview.append(
            {
                "interval_id": interval.get("interval_id"),
                "label": interval.get("label") or interval.get("appliance_id"),
                "ground_truth_entity_id": interval.get("ground_truth_entity_id"),
                "source": interval.get("source") or "manual",
                "prediction_status": "matched" if session is not None else "missed",
                "matched_assignment_id": (
                    str(session.get("assignment_id") or "") if session else None
                ),
                "matched_session_id": (
                    str(session.get("session_id") or "") if session else None
                ),
                "overlap_seconds": overlap,
                "prediction_confidence": session.get("confidence") if session else None,
            }
        )

    matched_ground_truth_count = sum(
        1 for item in preview if item["prediction_status"] == "matched"
    )
    matched_prediction_count = len(
        {value for value in matched_prediction_ids if value}
    )
    prediction_count = len(predictions)
    ground_truth_count = len(ground_truth_intervals)
    return {
        "metrics": {
            "ground_truth_interval_count": ground_truth_count,
            "prediction_count": prediction_count,
            "matched_ground_truth_count": matched_ground_truth_count,
            "matched_prediction_count": matched_prediction_count,
            "missed_ground_truth_count": (
                ground_truth_count - matched_ground_truth_count
            ),
            "precision": _nilm_validation_ratio(
                matched_prediction_count,
                prediction_count,
            ),
            "recall": _nilm_validation_ratio(
                matched_ground_truth_count,
                ground_truth_count,
            ),
        },
        "prediction_preview": preview,
    }


def _nilm_validation_best_match(
    interval: Mapping[str, Any],
    sessions: list[dict[str, Any]],
    assignment_by_id: Mapping[str, Mapping[str, Any]],
    matched_prediction_ids: set[str],
) -> tuple[dict[str, Any] | None, float]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for session in sessions:
        session_id = str(session.get("session_id") or "")
        if session_id and session_id in matched_prediction_ids:
            continue
        assignment = assignment_by_id.get(str(session.get("assignment_id") or ""))
        if assignment is None or not _nilm_validation_assignment_matches(
            interval,
            assignment,
        ):
            continue
        overlap = _nilm_validation_overlap_seconds(interval, session)
        if overlap > 0:
            candidates.append((overlap, session))
    if not candidates:
        return None, 0.0
    candidates.sort(key=lambda item: item[0], reverse=True)
    overlap, session = candidates[0]
    return session, overlap


def _nilm_validation_assignment_matches(
    interval: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    interval_id = str(interval.get("interval_id") or "").strip()
    if interval_id and interval_id in {
        str(value or "").strip()
        for value in _iter_items(assignment.get("label_interval_ids"))
    }:
        return True
    interval_appliance = str(
        interval.get("appliance_id") or interval.get("label") or ""
    ).strip().casefold()
    if not interval_appliance:
        return False
    return interval_appliance in {
        str(assignment.get("appliance_id") or "").strip().casefold(),
        str(assignment.get("display_name") or "").strip().casefold(),
    }


def _nilm_validation_overlap_seconds(
    interval: Mapping[str, Any],
    session: Mapping[str, Any],
) -> float:
    interval_start = _datetime_from_iso(interval.get("start"))
    interval_end = _datetime_from_iso(interval.get("end"))
    session_start = _datetime_from_iso(session.get("start"))
    session_end = _datetime_from_iso(session.get("end"))
    if not all((interval_start, interval_end, session_start, session_end)):
        return 0.0
    overlap_start = max(interval_start, session_start)
    overlap_end = min(interval_end, session_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def _nilm_validation_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _latest_nilm_session(
    sessions: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    latest: Mapping[str, Any] | None = None
    latest_seen: datetime | None = None
    for session in sessions:
        seen = _nilm_session_seen_datetime(session)
        if seen is None:
            continue
        if latest_seen is None or seen > latest_seen:
            latest = session
            latest_seen = seen
    return latest


def _nilm_session_seen_datetime(session: Mapping[str, Any]) -> datetime | None:
    return _datetime_from_iso(session.get("end")) or _datetime_from_iso(
        session.get("start")
    )


def _nilm_session_last_seen(session: Mapping[str, Any] | None) -> str | None:
    if session is None:
        return None
    seen = _nilm_session_seen_datetime(session)
    return seen.isoformat() if seen else None


def _nilm_workspace_reference_date(
    edges: list[NilmEdge],
    sessions: list[dict[str, Any]],
) -> Any:
    latest_edge = max((edge.timestamp for edge in edges), default=None)
    if latest_edge is not None:
        return latest_edge.date()
    latest_session = _latest_nilm_session(sessions)
    seen = _nilm_session_seen_datetime(latest_session) if latest_session else None
    return seen.date() if seen else None


def _nilm_daily_energy(
    sessions: list[dict[str, Any]],
    reference_date: Any,
) -> float:
    if reference_date is None:
        return 0.0
    return round(
        sum(
            _clamped_float(session.get("estimated_energy_kwh"), default=0.0)
            for session in sessions
            if (
                (start := _datetime_from_iso(session.get("start"))) is not None
                and start.date() == reference_date
            )
        ),
        3,
    )


def _round_float(value: Any) -> float:
    return round(_clamped_float(value, default=0.0), 3)


def _clamped_float(value: Any, *, default: float, upper: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    if upper is not None:
        return min(number, upper)
    return number


def _nilm_workspace_paths(coordinator: Any, circuit_id: str) -> dict[str, str]:
    target = _nilm_workspace_target((coordinator,), circuit_id)
    if target is None:
        return {}
    _target_coordinator, config = target
    query = urlencode({"circuit_id": config.circuit_id})
    return {
        "workspace_api_path": f"{NILM_WORKSPACE_API_PATH}?{query}",
        "workspace_call_api_path": f"{DOMAIN}/nilm_workspace?{query}",
    }


def _nilm_known_load_overlays(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    circuit_registry = getattr(coordinator, "circuit_registry", None)
    known_load_ids = {
        str(value)
        for value in _iter_items(
            getattr(circuit_registry, "known_load_circuit_ids", ())
        )
    }
    overlays: list[dict[str, Any]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if not isinstance(config, CircuitConfig) or config.circuit_id == circuit_id:
            continue
        if known_load_ids and config.circuit_id not in known_load_ids:
            continue
        entity_ids = _sensor_entity_ids(config)
        if not entity_ids:
            continue
        overlays.append(
            {
                "circuit_id": config.circuit_id,
                "name": config.name,
                "entity_ids": entity_ids,
            }
        )
        if len(overlays) >= MAX_NILM_WORKSPACE_KNOWN_LOADS:
            break
    return overlays


def _nilm_solar_overlays(
    coordinator: Any,
    circuit_id: str,
) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if (
            not isinstance(config, CircuitConfig)
            or config.circuit_id == circuit_id
            or str(config.appliance_profile) != ApplianceProfile.SOLAR_INVERTER.value
        ):
            continue
        entity_ids = _sensor_entity_ids(config)
        if entity_ids:
            overlays.append(
                {
                    "circuit_id": config.circuit_id,
                    "name": config.name,
                    "entity_ids": entity_ids,
                }
            )
        if len(overlays) >= MAX_NILM_WORKSPACE_KNOWN_LOADS:
            break
    return overlays


def _nilm_workspace_history_payload(
    config: CircuitConfig,
    known_load_overlays: list[dict[str, Any]],
    solar_overlays: list[dict[str, Any]],
    *,
    hours: Any,
    entry_id: str | None = None,
) -> dict[str, Any]:
    requested_hours = _bounded_float(
        hours,
        default=DEFAULT_NILM_WORKSPACE_HISTORY_HOURS,
        upper=MAX_NILM_WORKSPACE_HISTORY_HOURS,
    )
    end = datetime.now(UTC)
    start = end - timedelta(hours=requested_hours)
    entities = _nilm_workspace_history_entities(
        config,
        known_load_overlays,
        solar_overlays,
    )
    history_query_values = {
        "circuit_id": config.circuit_id,
        "hours": str(requested_hours),
    }
    if entry_id:
        history_query_values[ATTR_ENTRY_ID] = entry_id
    history_query = urlencode(history_query_values)
    recorder_query = urlencode(
        {
            "filter_entity_id": ",".join(entities),
            "end_time": end.isoformat(),
            "minimal_response": "1",
            "no_attributes": "1",
        }
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "hours": requested_hours,
        "max_hours": MAX_NILM_WORKSPACE_HISTORY_HOURS,
        "entities": entities,
        "entity_count": len(entities),
        "max_entities": MAX_NILM_WORKSPACE_HISTORY_ENTITIES,
        "api_path": f"{DOMAIN}/nilm_workspace_history?{history_query}",
        "fetch_path": f"{NILM_WORKSPACE_HISTORY_API_PATH}?{history_query}",
        "recorder_api_path": (
            f"history/period/{quote(start.isoformat(), safe='')}?{recorder_query}"
        ),
        "max_points_per_entity": MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY,
    }


def _nilm_workspace_history_entities(
    config: CircuitConfig,
    known_load_overlays: list[dict[str, Any]],
    solar_overlays: list[dict[str, Any]],
) -> list[str]:
    entity_ids = [*_sensor_entity_ids(config)]
    for overlay in [*known_load_overlays, *solar_overlays]:
        entity_ids.extend(
            str(entity_id)
            for entity_id in _iter_items(overlay.get("entity_ids"))
            if str(entity_id).strip()
        )
    return _unique_strings(entity_ids)[:MAX_NILM_WORKSPACE_HISTORY_ENTITIES]


def _sensor_entity_ids(config: Any) -> list[str]:
    return _unique_strings(
        sensor.entity_id
        for sensor in getattr(config, "sensors", ()) or ()
        if getattr(sensor, "entity_id", None)
    )


def _nilm_edges_for_circuit(coordinator: Any, circuit_id: str) -> list[NilmEdge]:
    edges_by_circuit = getattr(coordinator, "_nilm_unmatched_edges", {})
    if not isinstance(edges_by_circuit, Mapping):
        return []
    return [
        edge
        for edge in _iter_items(edges_by_circuit.get(circuit_id, ()))
        if isinstance(edge, NilmEdge)
    ]


def _nilm_edge_payload(edge: NilmEdge) -> dict[str, Any]:
    return {
        "timestamp": edge.timestamp.isoformat(),
        "direction": edge.direction,
        "delta_w": edge.delta_w,
        "delta_var": edge.delta_var,
        "delta_va": edge.delta_va,
        "delta_pf": edge.delta_pf,
        "dominant_leg": edge.dominant_leg,
        "split_phase_type": edge.split_phase_type,
    }


def _nilm_workspace_sessions(
    edges: list[NilmEdge],
    circuit_id: str,
    *,
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
    limit: int | None = MAX_NILM_WORKSPACE_SESSIONS,
) -> list[dict[str, Any]]:
    sessions: list[NilmSession] = []
    signature_by_id = {
        key: signature
        for signature in signatures
        for key in _nilm_signature_lookup_keys(signature)
    }
    for signature_fingerprint, assignment_id in _nilm_workspace_session_specs(
        signatures,
        assignments,
    ):
        signature = signature_by_id.get(signature_fingerprint)
        session_edges = (
            _nilm_edges_matching_signature(edges, signature)
            if signature is not None
            else edges
        )
        sessions.extend(
            pair_nilm_sessions(
                session_edges,
                mains_circuit_id=circuit_id,
                signature_fingerprint=signature_fingerprint,
                assignment_id=assignment_id,
            )
        )
        if limit is not None and len(sessions) >= limit:
            break
    payloads = [
        _nilm_session_payload(
            session,
            reviewed_session_ids=reviewed_session_ids,
        )
        for session in sessions
    ]
    return payloads if limit is None else payloads[:limit]


def _nilm_workspace_session_specs(
    signatures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> list[tuple[str, str | None]]:
    specs: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    seen_fingerprints: set[str] = set()
    hidden_fingerprints: set[str] = set()
    for assignment in assignments:
        assignment_id = str(assignment.get("assignment_id") or "").strip() or None
        fingerprints = {
            str(value or "").strip()
            for value in _iter_items(assignment.get("signature_fingerprints"))
            if str(value or "").strip()
        }
        if _nilm_assignment_hidden(assignment):
            hidden_fingerprints.update(fingerprints)
            continue
        for fingerprint in fingerprints:
            key = (fingerprint, assignment_id)
            if fingerprint and key not in seen:
                specs.append(key)
                seen.add(key)
                seen_fingerprints.add(fingerprint)
    for signature in signatures:
        fingerprint = _nilm_signature_session_fingerprint(signature)
        key = (fingerprint, None)
        if (
            fingerprint
            and not _nilm_signature_hidden(signature)
            and fingerprint not in hidden_fingerprints
            and fingerprint not in seen_fingerprints
            and key not in seen
        ):
            specs.append(key)
            seen.add(key)
    if specs or signatures or assignments:
        return specs
    return [(_nilm_workspace_signature_fingerprint(signatures), None)]


def _nilm_workspace_visible_sessions(
    sessions: Iterable[Mapping[str, Any]],
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    hidden_assignment_ids = {
        str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        for assignment in assignments
        if _nilm_assignment_hidden(assignment)
        if str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
    }
    hidden_fingerprints = {
        str(value or "").strip()
        for assignment in assignments
        if _nilm_assignment_hidden(assignment)
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    }
    visible_assignment_fingerprints = {
        str(value or "").strip()
        for assignment in assignments
        if not _nilm_assignment_hidden(assignment)
        for value in _iter_items(assignment.get("signature_fingerprints"))
        if str(value or "").strip()
    }
    hidden_fingerprints.update(
        fingerprint
        for signature in signatures
        if _nilm_signature_hidden(signature)
        if (fingerprint := _nilm_signature_session_fingerprint(signature))
        if str(signature.get("review_state") or "").strip().lower() != "merged"
        or fingerprint not in visible_assignment_fingerprints
    )
    return [
        dict(session)
        for session in sessions
        if str(session.get(ATTR_ASSIGNMENT_ID) or "").strip()
        not in hidden_assignment_ids
        and str(session.get("signature_fingerprint") or "").strip()
        not in hidden_fingerprints
    ]


def _nilm_signature_lookup_keys(signature: Mapping[str, Any]) -> list[str]:
    return [
        value
        for value in (
            str(signature.get(ATTR_SIGNATURE_ID) or "").strip(),
            str(signature.get("feedback_fingerprint") or "").strip(),
            str(signature.get("signature_fingerprint") or "").strip(),
        )
        if value
    ]


def _nilm_signature_session_fingerprint(signature: Mapping[str, Any]) -> str:
    return str(
        signature.get("feedback_fingerprint")
        or signature.get("signature_fingerprint")
        or signature.get(ATTR_SIGNATURE_ID)
        or ""
    ).strip()


def _nilm_session_history_for_circuit(
    coordinator: Any,
    circuit_id: str,
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    store_data = getattr(coordinator, "store_data", None)
    sessions_by_circuit = getattr(store_data, "nilm_session_history_by_circuit", {})
    if not isinstance(sessions_by_circuit, Mapping):
        return []
    return [
        _nilm_session_payload_with_actions(
            dict(session),
            reviewed_session_ids=reviewed_session_ids,
        )
        for session in _iter_items(sessions_by_circuit.get(circuit_id))
        if isinstance(session, Mapping)
    ]


def _nilm_reviewed_session_ids_by_assignment(
    assignments: Iterable[Mapping[str, Any]],
) -> dict[str, set[str]]:
    reviewed: dict[str, set[str]] = {}
    for assignment in assignments:
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if not assignment_id:
            continue
        reviewed_ids = reviewed.setdefault(assignment_id, set())
        for key in ("confirmed_session_ids", "rejected_session_ids"):
            for value in _iter_items(assignment.get(key)):
                session_id = str(value or "").strip()
                if session_id:
                    reviewed_ids.add(session_id)
    return reviewed


def _nilm_session_display_labels(
    signatures: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for signature in signatures:
        label = str(
            signature.get("display_label")
            or signature.get("display_name")
            or signature.get("likely_type")
            or signature.get(ATTR_SIGNATURE_ID)
            or ""
        ).strip()
        if not label:
            continue
        for key in _nilm_signature_lookup_keys(signature):
            labels.setdefault(key, label)
    for assignment in assignments:
        label = str(
            assignment.get("display_name")
            or assignment.get("appliance_id")
            or assignment.get(ATTR_ASSIGNMENT_ID)
            or ""
        ).strip()
        if not label:
            continue
        assignment_id = str(assignment.get(ATTR_ASSIGNMENT_ID) or "").strip()
        if assignment_id:
            labels[assignment_id] = label
        for field in ("signature_fingerprints", "session_ids"):
            for value in _iter_items(assignment.get(field)):
                key = str(value or "").strip()
                if key:
                    labels[key] = label
    return labels


def _add_nilm_session_display_labels(
    sessions: Iterable[Mapping[str, Any]],
    labels: Mapping[str, str],
) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for session in sessions:
        payload = dict(session)
        label = str(payload.get("display_label") or "").strip()
        for field in ("assignment_id", "signature_fingerprint", "session_id"):
            key = str(payload.get(field) or "").strip()
            if not label and key:
                label = labels.get(key, "")
        if label:
            payload["display_label"] = label
        labeled.append(payload)
    return labeled


def _merge_nilm_session_payloads(
    primary: Iterable[Mapping[str, Any]],
    fallback: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in (*list(primary), *list(fallback)):
        session_id = str(session.get("session_id") or "").strip()
        if not session_id or session_id in seen:
            continue
        merged.append(dict(session))
        seen.add(session_id)
    return merged


def _nilm_edges_matching_signature(
    edges: list[NilmEdge],
    signature: Mapping[str, Any],
) -> list[NilmEdge]:
    typical_watts = _clamped_float(signature.get("typical_watts"), default=0.0)
    split_phase_type = str(signature.get("split_phase_type") or "").strip()
    return [
        edge
        for edge in edges
        if (
            not typical_watts
            or abs(abs(edge.delta_w) - typical_watts) <= max(typical_watts * 0.25, 50.0)
        )
        and (
            not split_phase_type
            or split_phase_type == "unknown"
            or edge.split_phase_type in {split_phase_type, "unknown"}
        )
    ]


def _nilm_session_payload(
    session: NilmSession,
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    return _nilm_session_payload_with_actions(
        nilm_session_to_dict(session),
        reviewed_session_ids=reviewed_session_ids,
    )


def _nilm_session_payload_with_actions(
    payload: dict[str, Any],
    *,
    reviewed_session_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    circuit_id = str(payload.get("mains_circuit_id") or "").strip()
    if session_id and circuit_id:
        data = {
            ATTR_CIRCUIT_ID: circuit_id,
            ATTR_SESSION_ID: session_id,
        }
        signature_fingerprint = str(
            payload.get("signature_fingerprint") or ""
        ).strip()
        if signature_fingerprint:
            data[ATTR_SIGNATURE_FINGERPRINT] = signature_fingerprint
        payload["actions"] = {
            "assign": {
                "domain": DOMAIN,
                "service": SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
                "data": data,
                "requires": [ATTR_LABEL],
            }
        }
        assignment_id = str(payload.get("assignment_id") or "").strip()
        if (
            assignment_id
            and (
                reviewed_session_ids is None
                or (
                    assignment_id in reviewed_session_ids
                    and all(
                        session_id not in ids
                        for ids in reviewed_session_ids.values()
                    )
                )
            )
        ):
            action_data = {
                ATTR_CIRCUIT_ID: circuit_id,
                ATTR_SESSION_ID: session_id,
                ATTR_ASSIGNMENT_ID: assignment_id,
            }
            payload["actions"]["validate"] = {
                "domain": DOMAIN,
                "service": SERVICE_VALIDATE_NILM_SESSION,
                "data": dict(action_data),
            }
            payload["actions"]["reject"] = {
                "domain": DOMAIN,
                "service": SERVICE_REJECT_NILM_SESSION,
                "data": dict(action_data),
            }
    return payload


async def _async_history_rows(
    hass: Any,
    start: str,
    end: str,
    entity_ids: list[str],
) -> list[list[dict[str, Any]]]:
    if not entity_ids:
        return []
    history_helper = _history_get_significant_states()
    if history_helper is None:
        return []
    start_dt = _datetime_from_iso(start)
    end_dt = _datetime_from_iso(end)
    if start_dt is None or end_dt is None:
        return []
    recorder = _recorder_get_instance(hass)
    if recorder is None:
        return []
    job = partial(
        history_helper,
        hass,
        start_dt,
        end_time=end_dt,
        entity_ids=entity_ids,
        minimal_response=True,
        no_attributes=True,
    )
    try:
        rows = recorder.async_add_executor_job(job)
        if inspect.isawaitable(rows):
            rows = await rows
    except Exception:
        return []
    return _bounded_history_rows(rows)


def _recorder_get_instance(hass: Any) -> Any:
    try:
        from homeassistant.components.recorder import get_instance
    except ModuleNotFoundError:
        return None
    try:
        return get_instance(hass)
    except Exception:
        return None


def _history_get_significant_states() -> Any:
    try:
        from homeassistant.components.recorder.history import get_significant_states
    except ModuleNotFoundError:
        return None
    return get_significant_states


def _bounded_history_rows(rows: Any) -> list[list[dict[str, Any]]]:
    series_rows: Iterable[tuple[str | None, Any]]
    if isinstance(rows, Mapping):
        series_rows = ((str(key), value) for key, value in rows.items())
    else:
        series_rows = ((None, value) for value in _iter_items(rows))
    bounded = []
    for entity_id, series in series_rows:
        payload = _bounded_history_series(series, entity_id=entity_id)
        if payload:
            bounded.append(payload)
    return bounded


def _bounded_history_series(
    series: Any,
    *,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    items = []
    for state in _iter_items(series):
        payload = _history_state_payload(state, fallback_entity_id=entity_id)
        if payload is not None:
            items.append(payload)
    if len(items) <= MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY:
        return items
    step = max(len(items) // MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY, 1)
    return items[::step][:MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY]


def _history_state_payload(
    state: Any,
    *,
    fallback_entity_id: str | None,
) -> dict[str, Any] | None:
    if isinstance(state, Mapping):
        entity_id = state.get("entity_id") or fallback_entity_id
        value = state.get("state")
        changed = state.get("last_changed") or state.get("last_updated")
    else:
        entity_id = getattr(state, "entity_id", None) or fallback_entity_id
        value = getattr(state, "state", None)
        changed = getattr(state, "last_changed", None) or getattr(
            state,
            "last_updated",
            None,
        )
    if not entity_id or value is None or changed is None:
        return None
    changed_text = (
        changed.isoformat() if hasattr(changed, "isoformat") else str(changed)
    )
    return {
        "entity_id": str(entity_id),
        "state": str(value),
        "last_changed": changed_text,
    }


def _nilm_workspace_signature_fingerprint(signatures: list[dict[str, Any]]) -> str:
    for signature in signatures:
        signature_id = _nilm_signature_session_fingerprint(signature)
        if signature_id:
            return signature_id
    return "unassigned"


def _bounded_float(
    value: Any,
    *,
    default: float,
    upper: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, upper)


def _datetime_from_iso(value: Any) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
    data: dict[str, str],
) -> dict[str, Any]:
    paused = _alerts_paused(coordinator, circuit_id)
    return {
        "domain": DOMAIN,
        "service": SERVICE_END_MAINTENANCE if paused else SERVICE_START_MAINTENANCE,
        "label": _panel_text(
            "actions",
            "labels",
            "resume_alerts" if paused else "pause_alerts",
        ),
        "data": data,
    }


def _alerts_paused(coordinator: Any, circuit_id: str) -> bool:
    paused_circuits = getattr(coordinator, "paused_circuits", ())
    return circuit_id in paused_circuits or _maintenance_active(coordinator, circuit_id)


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
        register_view(ApplianceDetailView())
        register_view(ApplianceInsightsView())
        register_view(SetupHealthView())
        register_view(NilmWorkspaceView())
        register_view(NilmWorkspaceHistoryView())


async def _async_register_panel(hass: Any) -> bool:
    module_url = f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v={PANEL_MODULE_VERSION}"
    config = {
        "api_path": EVIDENCE_API_PATH,
        "domain": DOMAIN,
        "text": alert_evidence_panel_text(),
    }
    custom_panel_config = {
        "name": PANEL_ELEMENT_NAME,
        "embed_iframe": False,
        "trust_external": False,
        "module_url": module_url,
    }
    try:
        frontend = _frontend_registration_component(hass)
        register_built_in_panel = getattr(
            frontend,
            "async_register_built_in_panel",
            None,
        )
        if register_built_in_panel is not None:
            try:
                await _async_call_component_helper(
                    register_built_in_panel,
                    hass,
                    component_name="custom",
                    sidebar_title=None,
                    sidebar_icon=None,
                    frontend_url_path=PANEL_URL_PATH,
                    config={**config, "_panel_custom": custom_panel_config},
                    require_admin=False,
                    config_panel_domain=None,
                )
                return True
            except AttributeError:
                pass

        panel_custom = _panel_custom_component(hass)
        register_panel = getattr(panel_custom, "async_register_panel", None)
        if register_panel is None:
            return False
        await _async_call_component_helper(
            register_panel,
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_ELEMENT_NAME,
            # Keep the evidence page available for notification links without
            # adding a standalone entry to the Home Assistant sidebar.
            module_url=module_url,
            config=config,
            embed_iframe=False,
            require_admin=False,
        )
    except ValueError:
        return False
    return True


def _frontend_registration_component(hass: Any) -> Any:
    frontend = _frontend_component(hass)
    if getattr(frontend, "async_register_built_in_panel", None) is not None:
        return frontend
    try:
        from homeassistant.components import frontend as frontend_module

        return frontend_module
    except ModuleNotFoundError:
        return frontend


async def _async_remove_existing_panel(hass: Any) -> None:
    frontend = _frontend_component(hass)
    panel_exists = getattr(frontend, "async_panel_exists", None)
    remove_panel = getattr(frontend, "async_remove_panel", None)
    if remove_panel is None:
        return
    if panel_exists is not None and not await _async_call_component_helper(
        panel_exists,
        hass,
        PANEL_URL_PATH,
    ):
        return
    await _async_call_component_helper(
        remove_panel,
        hass,
        PANEL_URL_PATH,
        warn_if_unknown=False,
    )


async def _async_call_component_helper(
    helper: Callable[..., Any],
    hass: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return await _maybe_await(helper(hass, *args, **kwargs))
    except TypeError as err:
        message = str(err)
        if (
            "multiple values for argument" not in message
            and "positional argument" not in message
        ):
            raise
    return await _maybe_await(helper(*args, **kwargs))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _panel_custom_component(hass: Any) -> Any:
    components = getattr(hass, "components", None)
    component = getattr(components, "panel_custom", None)
    if getattr(component, "async_register_panel", None) is not None:
        return component
    if components is None:
        return None
    try:
        from homeassistant.components import panel_custom

        return panel_custom
    except ModuleNotFoundError:
        return getattr(getattr(hass, "components", None), "panel_custom", None)


def _frontend_component(hass: Any) -> Any:
    try:
        from homeassistant.components import frontend
    except ModuleNotFoundError:
        frontend = None

    components = getattr(hass, "components", None)
    if components is None:
        return frontend
    if type(components).__module__.startswith("homeassistant."):
        return frontend
    if (
        type(components).__module__ == "types"
        and type(components).__name__ == "SimpleNamespace"
    ):
        return getattr(components, "frontend", frontend)
    if frontend is None:
        return getattr(components, "frontend", None)
    return frontend
