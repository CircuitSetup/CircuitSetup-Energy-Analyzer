from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_BLOWER_REPRESENTS_GAS_HEAT,
    DOMAIN,
)
from .context_sources import thermostat_mappings_for_settings
from .entities.setup_health import (
    setup_health_attributes,
    setup_health_panel_text,
    setup_health_value,
)
from .expected_schedule import schedule_settings_from_dict
from .local_time import local_date
from .localized_text import translation_section
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    SensorRole,
)
from .notifications import notification_id_for_alert
from .panel_common import (
    _add_setting_impact_preview,
    _circuit_payload,
    _datetime_from_iso,
    _iter_items,
    _panel_text,
)
from .panel_contracts import (
    EVIDENCE_API_PATH,
    PANEL_ELEMENT_NAME,
    PANEL_MODULE_NAME,
    PANEL_MODULE_VERSION,
    PANEL_URL_PATH,
    STATIC_URL_PATH,
)
from .panel_nilm import (
    MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY,
    _nilm_known_load_overlays,
    _nilm_payload_for_circuit,
    _nilm_solar_overlays,
    _nilm_workspace_history_payload,
    _nilm_workspace_target,
)
from .panel_views import (
    AlertEvidenceView,
    ApplianceDetailView,
    ApplianceInsightsView,
    HvacAssociationsView,
    NilmWorkspaceHistoryView,
    NilmWorkspaceView,
    SetupHealthView,
)
from .recommendation_guidance import (
    is_hidden_recommendation_evidence_key,
    recommendation_evidence_preview,
    recommendation_setting_control_text,
    recommendation_setting_default_value,
    recommendation_setting_expected_effect,
)
from .services import (
    ATTR_ALERT_ID,
    ATTR_ASSIGNMENT_ID,
    ATTR_CIRCUIT_ID,
    ATTR_ENTRY_ID,
    ATTR_RECOMMENDATION_ID,
    ATTR_SESSION_ID,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_APPLY_SETTING_RECOMMENDATION,
    SERVICE_DISMISS_SETTING_RECOMMENDATION,
    SERVICE_END_MAINTENANCE,
    SERVICE_MARK_ALERT_CONFIRMED,
    SERVICE_MARK_ALERT_EXPECTED,
    SERVICE_MARK_ALERT_UNHELPFUL,
    SERVICE_MARK_NILM_APPLIANCE_CORRECT,
    SERVICE_MARK_NILM_APPLIANCE_WRONG,
    SERVICE_REJECT_NILM_SESSION,
    SERVICE_RELEARN_BASELINE,
    SERVICE_RESET_SETTING_RECOMMENDATION,
    SERVICE_START_MAINTENANCE,
    SERVICE_UNDO_SETTING_RECOMMENDATION,
    SERVICE_VALIDATE_NILM_SESSION,
)
from .settings_advisor import SETTING_LABELS
from .state import circuit_is_learning
from .ux import alert_evidence_detail, friendly_feature_name

DEFAULT_APPLIANCE_DETAIL_HISTORY_HOURS = 168
APPLIANCE_DETAIL_HISTORY_PERIOD_HOURS = (24, 168, 720)
_HISTORY_UNIT_BY_ROLE = {
    SensorRole.VOLTAGE: "V",
    SensorRole.CURRENT: "A",
    SensorRole.PEAK_CURRENT: "A",
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


try:
    from aiohttp import web
    from homeassistant.components.http import KEY_HASS
except ModuleNotFoundError:
    KEY_HASS = "hass"

    class _FallbackWeb:
        @staticmethod
        def json_response(data: dict[str, Any]) -> dict[str, Any]:
            return data

    web = _FallbackWeb()  # type: ignore[assignment]


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
                {"requested_entry_id": requested_entry_id} if requested_entry_id else {}
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
        **({"requested_entry_id": requested_entry_id} if requested_entry_id else {}),
        "detail": None,
        "actions": {},
        "message": _panel_text("appliance_detail", "fallback_message"),
        "next_step": _panel_text("appliance_detail", "fallback_next_step"),
    }


def appliance_insights_payload(
    coordinators: Iterable[Any],
) -> dict[str, Any]:
    """Return the integration-level appliance index payload."""
    coordinator_list = tuple(coordinators)
    items = appliance_insights_for_coordinators(coordinator_list)
    coordinators_by_entry = {
        str(getattr(coordinator, "entry_id", "") or ""): coordinator
        for coordinator in coordinator_list
    }
    payload_items = []
    for item in items:
        payload_item = item.as_dict()
        coordinator = coordinators_by_entry.get(item.entry_id)
        detail = (
            appliance_detail_for_assignment(coordinator, item.assignment_id)
            if coordinator is not None and item.assignment_id
            else (
                appliance_detail_for_circuit(coordinator, item.circuit_id)
                if coordinator is not None
                else None
            )
        )
        payload_item["daily_totals"] = (
            _appliance_daily_totals(coordinator, detail, limit=None)
            if coordinator is not None and detail is not None
            else []
        )
        payload_items.append(payload_item)
    whole_house = []
    for coordinator in coordinator_list:
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            detail = appliance_detail_for_circuit(
                coordinator,
                str(getattr(config, "circuit_id", "") or ""),
            )
            if detail is None or detail.source_type != "mains":
                continue
            whole_house.append(
                {
                    "entry_id": str(getattr(coordinator, "entry_id", "") or ""),
                    "circuit_id": detail.circuit_id,
                    "display_name": detail.display_name,
                    "daily_totals": _appliance_daily_totals(
                        coordinator,
                        detail,
                        limit=None,
                    ),
                }
            )
            break
    return {
        "status": "ok",
        "count": len(items),
        "items": payload_items,
        "whole_house": whole_house,
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
        existing = coordinator.store_data.appliance_schedule_settings.get(appliance_key)
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
        "daily_totals": _appliance_daily_totals(coordinator, detail),
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


def _appliance_daily_totals(
    coordinator: Any,
    detail: ApplianceDetail,
    *,
    limit: int | None = 30,
) -> list[dict[str, Any]]:
    if detail.source_type == "nilm_estimate":
        return []
    histories = getattr(coordinator.store_data, "energy_usage_by_circuit", {})
    history = (
        histories.get(detail.circuit_id, {}) if isinstance(histories, Mapping) else {}
    )
    days = history.get("days", []) if isinstance(history, Mapping) else []
    clock = getattr(coordinator, "current_time", None)
    now = clock() if callable(clock) else datetime.now(UTC)
    time_zone = getattr(
        getattr(coordinator, "context_builder", None),
        "time_zone",
        None,
    )
    time_zone = time_zone() if callable(time_zone) else None
    today = (
        local_date(now, time_zone)
        if time_zone is not None and now.tzinfo is not None
        else now.date()
    )
    rate = getattr(
        coordinator.state,
        "effective_electricity_rate_by_circuit",
        {},
    ).get(detail.circuit_id)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = None
    cost_histories = getattr(coordinator.store_data, "cost_by_circuit", {})
    cost_history = (
        cost_histories.get(detail.circuit_id, {})
        if isinstance(cost_histories, Mapping)
        else {}
    )
    cost_by_date: dict[str, float] = {}
    for cost_day in (
        cost_history.get("days", []) if isinstance(cost_history, Mapping) else []
    ):
        if not isinstance(cost_day, Mapping) or cost_day.get("complete") is not True:
            continue
        try:
            cost_by_date[str(cost_day.get("date") or "")] = round(
                max(float(cost_day["cost"]), 0.0),
                2,
            )
        except (KeyError, TypeError, ValueError):
            continue
    complete = []
    for day in days:
        if (
            not isinstance(day, Mapping)
            or day.get("complete") is not True
        ):
            continue
        date_text = str(day.get("date") or "")
        try:
            day_date = date.fromisoformat(date_text)
        except ValueError:
            continue
        if day_date.isoformat() != date_text or day_date >= today:
            continue
        try:
            energy_kwh = round(max(float(day["usage_kwh"]), 0.0), 3)
        except (KeyError, TypeError, ValueError):
            continue
        recorded_cost = cost_by_date.get(date_text)
        estimated_cost = (
            round(energy_kwh * rate, 2)
            if recorded_cost is None and rate is not None and rate > 0
            else None
        )
        complete.append(
            {
                "date": date_text,
                "energy_kwh": energy_kwh,
                "cost": (
                    recorded_cost
                    if recorded_cost is not None
                    else estimated_cost
                ),
                "cost_source": (
                    "recorded"
                    if recorded_cost is not None
                    else "estimated"
                    if estimated_cost is not None
                    else "unavailable"
                ),
            }
        )
    complete = sorted(complete, key=lambda item: item["date"])
    return complete if limit is None else complete[-limit:]


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
        session_id = str(
            (detail.current_session or {}).get(ATTR_SESSION_ID) or ""
        ) or str((detail.last_matched_session or {}).get(ATTR_SESSION_ID) or "")
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
        entity_series = [{"entity_id": embedded_series[0][0]["entity_id"], "unit": "W"}]
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
                "mark_confirmed": {
                    "domain": DOMAIN,
                    "service": SERVICE_MARK_ALERT_CONFIRMED,
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


def hvac_associations_payload(
    coordinators: Iterable[Any], *, entry_id: str | None = None
) -> dict[str, Any]:
    """Return configured HVAC thermostat mappings with bounded evaluation state."""
    items: list[dict[str, Any]] = []
    for coordinator in coordinators:
        coordinator_entry_id = _coordinator_entry_id(coordinator)
        if entry_id and coordinator_entry_id != entry_id:
            continue
        entry_data = getattr(coordinator, "entry_data", {})
        options = getattr(coordinator, "options", {})
        if not isinstance(entry_data, Mapping) or not isinstance(options, Mapping):
            continue
        entry_settings = entry_data.get(CONF_ADVANCED_SETTINGS, {})
        option_settings = options.get(CONF_ADVANCED_SETTINGS, {})
        state = getattr(coordinator, "state", None)
        efficiency = getattr(state, "hvac_efficiency_by_circuit", {})
        issues = getattr(state, "hvac_thermostat_setup_issues_by_circuit", {})
        for config in getattr(coordinator, "circuit_configs", ()):
            if config.appliance_profile not in _HVAC_ASSOCIATION_PROFILES:
                continue
            settings = (
                dict(entry_settings.get(config.circuit_id, {}))
                if isinstance(entry_settings, Mapping)
                else {}
            )
            if isinstance(option_settings, Mapping):
                override = option_settings.get(config.circuit_id, {})
                if isinstance(override, Mapping):
                    settings.update(override)
            mappings = thermostat_mappings_for_settings(entry_data, options, settings)
            retained = (
                efficiency.get(config.circuit_id, {})
                if isinstance(efficiency, Mapping)
                else {}
            )
            streams = (
                retained.get("streams", {}) if isinstance(retained, Mapping) else {}
            )
            circuit_issues = (
                issues.get(config.circuit_id, ()) if isinstance(issues, Mapping) else ()
            )
            for thermostat_entity_id, temperature_entity_id in mappings.items():
                modes = {
                    mode: _hvac_association_mode(
                        streams, config, thermostat_entity_id, mode
                    )
                    for mode in _hvac_association_modes(config, settings)
                }
                status = (
                    "needs_attention"
                    if circuit_issues
                    else (
                        "ready"
                        if any(mode["status"] == "ready" for mode in modes.values())
                        else "learning"
                    )
                )
                items.append(
                    {
                        "entry_id": coordinator_entry_id,
                        "circuit_id": config.circuit_id,
                        "appliance_name": config.name,
                        "appliance_profile": config.appliance_profile.value,
                        "detail_path": _circuit_appliance_detail_panel_path(
                            config.circuit_id
                        ),
                        "thermostat_entity_id": thermostat_entity_id,
                        "thermostat_name": _entity_id_name(thermostat_entity_id),
                        "temperature_entity_id": temperature_entity_id,
                        "temperature_name": _entity_id_name(temperature_entity_id)
                        if temperature_entity_id
                        else None,
                        "status": status,
                        "modes": modes,
                    }
                )
    items.sort(
        key=lambda item: (
            item["appliance_name"],
            item["circuit_id"],
            item["thermostat_entity_id"],
        )
    )
    return {"status": "ok", "count": len(items), "items": items}


_HVAC_ASSOCIATION_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)


def _hvac_association_modes(
    config: CircuitConfig, settings: Mapping[str, Any]
) -> tuple[str, ...]:
    profile = config.appliance_profile
    modes: list[str] = []
    if profile in {
        ApplianceProfile.HVAC,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.ELECTRIC_HEAT,
    } or (
        profile is ApplianceProfile.HVAC_BLOWER
        and settings.get(CONF_BLOWER_REPRESENTS_GAS_HEAT)
    ):
        modes.append("heating")
    if profile in {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
    }:
        modes.append("cooling")
    return tuple(modes)


def _hvac_association_mode(
    streams: Any, config: CircuitConfig, thermostat_entity_id: str, mode: str
) -> dict[str, Any]:
    raw = (
        streams.get(f"{config.circuit_id}|{thermostat_entity_id}|{mode}", {})
        if isinstance(streams, Mapping)
        else {}
    )
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "applicable": True,
        "status": str(raw.get("status") or "learning"),
        "score": raw.get("score"),
        "trend": str(raw.get("finding") or "") or None,
        "change_percent": raw.get("change_percent", raw.get("change_ratio")),
        "baseline_minutes_per_degree_f": raw.get("baseline_minutes_per_degree"),
        "recent_minutes_per_degree_f": raw.get("recent_minutes_per_degree"),
        "reference_count": int(raw.get("reference_count") or 0),
        "recent_count": int(raw.get("recent_count") or 0),
        "attribution": "gas_furnace_proxy"
        if config.appliance_profile is ApplianceProfile.HVAC_BLOWER
        else "direct",
    }


def _entity_id_name(entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return entity_id.rsplit(".", 1)[-1].replace("_", " ").title()


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
            "circuit_name",
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
    circuit_id = str(payload.get("circuit_id") or "").strip()
    if circuit_id and not str(payload.get("circuit_name") or "").strip():
        config = _config_for_circuit(coordinator, circuit_id)
        if config is not None:
            payload["circuit_name"] = config.name
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
    label = ""
    for key in ("title", "summary"):
        value = str(payload.get(key) or "").strip()
        if value:
            label = value
            break
    if not label:
        setting_key = str(payload.get("setting_key") or "").strip()
        label = SETTING_LABELS.get(
            setting_key,
            str(payload.get("setting_label") or "").strip(),
        )
    if not label:
        feature = str(payload.get("feature") or "").strip()
        label = (
            friendly_feature_name(feature)
            if feature
            else _panel_text("recommendations", "suggested_setting")
        )
    circuit_name = str(payload.get("circuit_name") or "").strip()
    if not circuit_name:
        circuit_id = str(payload.get("circuit_id") or "").strip()
        circuit_name = friendly_feature_name(circuit_id) if circuit_id else ""
    if circuit_name and not label.casefold().startswith(circuit_name.casefold()):
        return f"{circuit_name} {label}"
    return label


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
        "icon": "mdi:bell-pause-outline",
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


def _truthy_query(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "all"}


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
    if circuit_is_learning(state, circuit_id):
        return None
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
    state = getattr(coordinator, "state", None)
    return tuple(
        alert
        for alert in alerts
        if isinstance(alert, AlertEvidence)
        and not circuit_is_learning(state, alert.circuit_id)
    )


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
        register_view(HvacAssociationsView())
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
