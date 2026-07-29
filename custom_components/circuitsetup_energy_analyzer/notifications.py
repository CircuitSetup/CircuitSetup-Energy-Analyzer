from __future__ import annotations

from math import isfinite
from typing import Any
from urllib.parse import urlencode

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
from .const import DOMAIN
from .ids import readable_component as _readable_component
from .ids import tuple_id as _tuple_id
from .localized_text import translation_text
from .models import AlertEvidence, CircuitConfig
from .safety import feature_needs_electrical_safety_notice

POWER_QUALITY_ALERT_FEATURES = frozenset(
    {
        "reactive_shift_under_stable_real_power",
        "power_factor_shift_under_load",
        "apparent_power_shift",
        "motor_relationship_changed",
        "split_phase_relationship_changed",
        "resistive_load_became_reactive",
    }
)
APPLIANCE_HEALTH_ALERT_FEATURES = frozenset(
    {
        "efficiency_degradation",
        "hvac_response_faster",
        "hvac_response_slower",
        "repeated_short_cycle",
    }
)
_ALERT_VALUE_FORMATS = {
    "activity_inactive_too_long": ("minutes", "number"),
    "activity_left_on": ("minutes", "number"),
    "always_on_power": ("power", "number"),
    "reactive_to_real_ratio": ("percent", "percentage"),
    "apparent_to_real_ratio": ("percent", "percentage"),
    "power_factor": (None, "decimal"),
    "power_factor_deficit": (None, "decimal"),
    "real_power": ("power", "number"),
    "reactive_power": ("reactive_power", "number"),
    "apparent_power": ("apparent_power", "number"),
    "billing_cycle_budget": ("energy", "number"),
    "circuit_capacity": ("current", "number"),
    "daily_energy_goal": ("energy", "number"),
    "daily_energy_usage_spike": ("energy", "number"),
    "demand_limit": ("power", "number"),
    "demand_monthly_peak": ("power", "number"),
    "dual_phase_leg_imbalance": ("percent", "percentage"),
    "energy_per_runtime_hour": ("energy_per_hour", "number"),
    "energy_per_completed_cycle": ("energy_per_cycle", "number"),
    "average_cycle_duration": ("seconds", "number"),
    "starts_per_runtime_hour": ("starts_per_hour", "number"),
    "session_duration_seconds": ("seconds", "number"),
    "minutes_per_degree": ("minutes_per_degree", "number"),
    "nilm_appliance_unusual_energy": ("energy", "number"),
    "nilm_appliance_confidence": ("percent", "percentage"),
    "nilm_appliance_unusual_runtime": ("minutes", "number"),
    "rain_pump_correlation": ("minutes", "number"),
    "run_cycle_daily_duty_cycle_percent": ("percent", "number"),
    "run_cycle_daily_start_count": ("starts", "number"),
    "run_cycle_duration_s": ("seconds", "number"),
    "utility_energy_mismatch": ("energy", "number"),
    "water_flow_correlation": ("minutes", "number"),
}


def _notification_text(*keys: str) -> str:
    return translation_text("notifications", *keys)


def _notification_text_format(*keys: str, **values: Any) -> str:
    return _notification_text(*keys).format(**values)


ALERT_VALUE_METADATA = {
    key: (
        _notification_text("alert", "value_metrics", key),
        _notification_text("alert", "units", unit_key) if unit_key else "",
        format_kind,
    )
    for key, (unit_key, format_kind) in _ALERT_VALUE_FORMATS.items()
}


def notification_id_for_alert(alert: AlertEvidence) -> str:
    """Return a stable persistent-notification id for alert evidence."""
    feature = alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
    notification_key = alert.features.get("notification_key")
    if isinstance(notification_key, str) and notification_key.strip():
        return _tuple_id(
            f"{DOMAIN}_alert",
            alert.circuit_id,
            feature,
            notification_key.strip(),
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

    nilm_display_name = str(alert.features.get("display_name") or "").strip()
    display_name = nilm_display_name or (
        config.name if config is not None and config.name else alert.circuit_id
    )
    if alert.features.get("notification_type") == "lifecycle_update":
        return "\n".join(
            (
                f"**{display_name}**",
                "",
                alert.message,
                "",
                f"[{_notification_text('alert', 'open_appliance_evidence')}]"
                f"({alert_evidence_path(alert, dashboard_path=dashboard_path)})",
            )
        )
    lines = [f"**{display_name}**", "", alert.message]
    lines.extend(_power_quality_notice_lines(alert))
    lines.extend(_nilm_source_lines(alert))
    lines.extend(_appliance_health_notice_lines(alert))
    observed_label = _notification_text(
        "alert",
        (
            "recent_value"
            if alert.feature in APPLIANCE_HEALTH_ALERT_FEATURES
            else "observed_value"
        ),
    )
    lines.extend(
        [
            "",
            f"- {
                _notification_value_label(
                    alert, observed_label
                )
            }: "
            f"{_format_notification_value(alert, alert.observed_value)}",
            f"- {_notification_value_label(alert, _comparison_value_label(alert))}: "
            f"{_format_notification_value(alert, alert.baseline_value)}",
            f"- {_notification_text('alert', 'repeated_observations')}: "
            f"{alert.repeated_count}",
        ]
    )
    if feature_needs_electrical_safety_notice(alert.feature):
        lines.extend(
            (
                "",
                f"{_notification_text('alert', 'safety_notice')}: "
                f"{translation_text('safety', 'electrical_notice')}",
            )
        )
    lines.extend(
        [
            "",
            f"[{_notification_text('alert', 'open_evidence')}]"
            f"({alert_evidence_path(alert, dashboard_path=dashboard_path)})",
        ]
    )
    return "\n".join(lines)


def _power_quality_notice_lines(alert: AlertEvidence) -> list[str]:
    if alert.feature not in POWER_QUALITY_ALERT_FEATURES:
        return []
    return [
        "",
        _notification_text("alert", "power_quality_notice"),
    ]


def _appliance_health_notice_lines(alert: AlertEvidence) -> list[str]:
    if alert.feature not in APPLIANCE_HEALTH_ALERT_FEATURES:
        return []
    lines = [""]
    confidence = _alert_confidence(alert)
    if confidence is not None:
        lines.append(
            _notification_text_format(
                "alert",
                "confidence_line",
                confidence=round(confidence * 100),
            )
        )
    if "not a component diagnosis or safety control" not in alert.message.lower():
        lines.append(_notification_text("alert", "health_notice"))
    return lines


def _notification_value_label(alert: AlertEvidence, label: str) -> str:
    value_format = ALERT_VALUE_METADATA.get(alert.value_metric or alert.feature)
    if value_format is None:
        return label
    return f"{label} ({value_format[0]})"


def _format_notification_value(alert: AlertEvidence, value: float) -> str:
    value_format = ALERT_VALUE_METADATA.get(alert.value_metric or alert.feature)
    if value_format is None:
        return str(value)
    _, unit, format_kind = value_format
    return format_alert_value(value, unit, format_kind)


def format_alert_value(value: float, unit: str, format_kind: str) -> str:
    """Format one alert value consistently across notification and panel views."""
    if format_kind == "percentage":
        return f"{value * 100.0:.3f}%"
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{formatted}{f' {unit}' if unit else ''}"


def _nilm_source_lines(alert: AlertEvidence) -> list[str]:
    if not _is_nilm_estimated_alert(alert):
        return []

    lines: list[str] = []
    nilm_estimated = _notification_text("alert", "nilm_estimated")
    if nilm_estimated not in alert.message:
        lines.append(nilm_estimated)

    confidence = _nilm_confidence(alert)
    confidence_label = _notification_text("alert", "confidence")
    if confidence is not None and f"{confidence_label}:" not in alert.message:
        lines.append(
            _notification_text_format(
                "alert",
                "confidence_line",
                confidence=round(confidence * 100),
            )
        )
    return lines


def _is_nilm_estimated_alert(alert: AlertEvidence) -> bool:
    source = str(alert.features.get("source") or "").strip().lower()
    source_type = str(alert.features.get("source_type") or "").strip().lower()
    if source == "nilm" or source_type == "nilm_estimate":
        return True
    assignment_id = str(alert.features.get("assignment_id") or "").strip()
    return bool(assignment_id and alert.features.get("estimated") is True)


def _nilm_confidence(alert: AlertEvidence) -> float | None:
    return _alert_confidence(alert)


def _alert_confidence(alert: AlertEvidence) -> float | None:
    for key in ("confidence", "nilm_confidence", "assignment_confidence"):
        raw = alert.features.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        if value < 0:
            continue
        if value > 1.0:
            value /= 100.0
        return min(value, 1.0)
    return None


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

    try:
        create(
            hass,
            alert_notification_message(
                alert,
                config=config,
                dashboard_path=dashboard_path,
            ),
            title=_notification_text("alert", "title"),
            notification_id=notification_id_for_alert(alert),
        )
    except (AttributeError, TypeError):
        return


async def async_dismiss_persistent_notification(
    hass: Any,
    notification_id: str,
) -> None:
    """Dismiss a persistent notification if Home Assistant is available."""
    try:
        from homeassistant.components import persistent_notification
    except ModuleNotFoundError:
        return

    dismiss = getattr(persistent_notification, "async_dismiss", None)
    if dismiss is None:
        return

    try:
        dismiss(hass, notification_id)
    except (AttributeError, TypeError):
        return


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

    try:
        create(
            hass,
            _settings_recommendation_message(total_pending, entry_id),
            title=_notification_text("settings_recommendations", "title"),
            notification_id=settings_recommendation_notification_id(entry_id),
        )
    except (AttributeError, TypeError):
        return


async def async_create_weekly_digest_notification(
    hass: Any,
    digest: Any,
) -> None:
    """Create one idempotent persistent notification for a weekly digest."""
    try:
        from homeassistant.components import persistent_notification
    except ModuleNotFoundError:
        return
    create = getattr(persistent_notification, "async_create", None)
    if create is None:
        return
    biggest = list(getattr(digest, "biggest_changes", ()))
    top_energy = list(getattr(digest, "top_energy_users", ()))
    observed = list(getattr(digest, "observed_alerts", ()))
    unresolved = list(getattr(digest, "unresolved_items", ()))
    nilm_review = list(getattr(digest, "nilm_review_items", ()))
    load_shift = list(getattr(digest, "load_shift_opportunities", ()))
    lines = [
        _notification_text_format(
            "weekly_digest",
            "intro",
            week_start=digest.week_start,
            week_end=digest.week_end,
        ),
        "",
        f"**{_notification_text('weekly_digest', 'largest_changes')}**",
        *(
            [
                _notification_text_format(
                    "weekly_digest",
                    "change_item",
                    display_name=item.display_name,
                    change_percent=round(item.change_ratio * 100),
                )
                for item in biggest
            ]
            or [_notification_text("weekly_digest", "no_changes")]
        ),
        "",
        f"**{_notification_text('weekly_digest', 'top_energy_users')}**",
        *(
            [
                _notification_text_format(
                    "weekly_digest",
                    "energy_item",
                    display_name=item.display_name,
                    energy_kwh=item.energy_kwh,
                )
                for item in top_energy
            ]
            or [_notification_text("weekly_digest", "no_energy_data")]
        ),
    ]
    lines.extend(
        _digest_section_lines(
            _notification_text("weekly_digest", "observed_alerts"),
            observed,
        )
    )
    lines.extend(
        _digest_section_lines(
            _notification_text("weekly_digest", "unresolved_items"),
            unresolved,
        )
    )
    lines.extend(
        _digest_section_lines(
            _notification_text("weekly_digest", "nilm_review"),
            nilm_review,
        )
    )
    lines.extend(
        _digest_section_lines(
            _notification_text("weekly_digest", "load_shift_opportunities"),
            load_shift,
        )
    )
    try:
        create(
            hass,
            "\n".join(lines),
            title=_notification_text("weekly_digest", "title"),
            notification_id=f"{DOMAIN}_weekly_appliance_digest",
        )
    except (AttributeError, TypeError):
        return


def _digest_section_lines(
    title: str,
    items: list[Any],
    *,
    limit: int = 5,
) -> list[str]:
    if not items:
        return []
    return [
        "",
        f"**{title}**",
        *[f"- {item.display_name}" for item in items[:limit]],
    ]


async def async_create_daily_summary_notification(
    hass: Any,
    alerts: list[AlertEvidence],
    *,
    summary_date: str,
) -> None:
    """Create one bounded daily appliance-notification summary."""
    if not alerts:
        return
    try:
        from homeassistant.components import persistent_notification
    except ModuleNotFoundError:
        return
    create = getattr(persistent_notification, "async_create", None)
    if create is None:
        return
    lines = [
        _notification_text_format(
            "daily_summary",
            "intro",
            summary_date=summary_date,
        ),
        "",
        *[
            _notification_text_format(
                "daily_summary",
                "alert_item",
                message=alert.message,
            )
            for alert in alerts[:20]
        ],
    ]
    try:
        create(
            hass,
            "\n".join(lines),
            title=_notification_text("daily_summary", "title"),
            notification_id=f"{DOMAIN}_daily_appliance_summary",
        )
    except (AttributeError, TypeError):
        return


def _settings_recommendation_message(total_pending: int, entry_id: str) -> str:
    if total_pending == 1:
        template = _notification_text("settings_recommendations", "singular_message")
    else:
        template = _notification_text("settings_recommendations", "plural_message")
    return template.format(
        total_pending=total_pending,
        settings_url=_settings_recommendations_options_path(entry_id),
    )


def _settings_recommendations_options_path(entry_id: str) -> str:
    query = urlencode({"review_suggested_settings": "1", "entry_id": entry_id})
    return f"{DEFAULT_ALERT_EVIDENCE_PATH}?{query}"


def _comparison_value_label(alert: AlertEvidence) -> str:
    if alert.feature in APPLIANCE_HEALTH_ALERT_FEATURES:
        return _notification_text("alert", "reference_value")
    if alert.feature in {"demand_limit", "demand_monthly_peak"}:
        return _notification_text("alert", "comparison_value")
    return _notification_text("alert", "baseline_value")
