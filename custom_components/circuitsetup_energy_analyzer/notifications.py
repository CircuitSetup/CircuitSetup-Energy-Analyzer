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
from .safety import ELECTRICAL_SAFETY_NOTICE, feature_needs_electrical_safety_notice

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
_POWER_QUALITY_VALUE_FORMATS = {
    "reactive_to_real_ratio": ("Reactive-to-real power ratio", "%", "percentage"),
    "apparent_to_real_ratio": ("Apparent-to-real power ratio", "%", "percentage"),
    "power_factor": ("Power factor", "", "decimal"),
    "power_factor_deficit": ("Power factor deficit", "", "decimal"),
    "reactive_power": ("Reactive power", "VAR", "number"),
    "apparent_power": ("Apparent power", "VA", "number"),
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
    lines = [f"**{display_name}**", "", alert.message]
    lines.extend(_power_quality_notice_lines(alert))
    lines.extend(_nilm_source_lines(alert))
    lines.extend(
        [
            "",
            f"- {_notification_value_label(
                alert, _notification_text('alert', 'observed_value')
            )}: "
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
                f"{ELECTRICAL_SAFETY_NOTICE}",
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
        "This is a repeated change from the learned electrical pattern, not an "
        "electrical safety diagnosis.",
    ]


def _notification_value_label(alert: AlertEvidence, label: str) -> str:
    value_format = _POWER_QUALITY_VALUE_FORMATS.get(alert.value_metric)
    if value_format is None:
        return label
    return f"{label} ({value_format[0]})"


def _format_notification_value(alert: AlertEvidence, value: float) -> str:
    value_format = _POWER_QUALITY_VALUE_FORMATS.get(alert.value_metric)
    if value_format is None:
        return str(value)
    _, unit, format_kind = value_format
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
        lines.append(f"{confidence_label}: {round(confidence * 100)}%.")
    return lines


def _is_nilm_estimated_alert(alert: AlertEvidence) -> bool:
    source = str(alert.features.get("source") or "").strip().lower()
    source_type = str(alert.features.get("source_type") or "").strip().lower()
    if source == "nilm" or source_type == "nilm_estimate":
        return True
    assignment_id = str(alert.features.get("assignment_id") or "").strip()
    return bool(assignment_id and alert.features.get("estimated") is True)


def _nilm_confidence(alert: AlertEvidence) -> float | None:
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
    lines = [
        f"Appliance summary for {digest.week_start} through {digest.week_end}.",
        "",
        "**Largest changes from normal**",
        *(
            [
                f"- {item.display_name}: {round(item.change_ratio * 100)}%"
                for item in biggest
            ]
            or ["- No meaningful changes from learned normal.".strip()]
        ),
        "",
        "**Top energy users**",
        *(
            [f"- {item.display_name}: {item.energy_kwh} kWh" for item in top_energy]
            or ["- No retained appliance energy data.".strip()]
        ),
    ]
    try:
        create(
            hass,
            "\n".join(lines),
            title="Weekly Appliance Digest",
            notification_id=f"{DOMAIN}_weekly_appliance_digest",
        )
    except (AttributeError, TypeError):
        return


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
        f"Appliance notifications queued for {summary_date}.",
        "",
        *[f"- {alert.message}" for alert in alerts[:20]],
    ]
    try:
        create(
            hass,
            "\n".join(lines),
            title="Daily Appliance Summary",
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
    query = urlencode(
        {"review_suggested_settings": "1", "entry_id": entry_id}
    )
    return f"{DEFAULT_ALERT_EVIDENCE_PATH}?{query}"


def _comparison_value_label(alert: AlertEvidence) -> str:
    if alert.feature in {"demand_limit", "demand_monthly_peak"}:
        return _notification_text("alert", "comparison_value")
    return _notification_text("alert", "baseline_value")


def _notification_text(*keys: str) -> str:
    return translation_text("notifications", *keys)
