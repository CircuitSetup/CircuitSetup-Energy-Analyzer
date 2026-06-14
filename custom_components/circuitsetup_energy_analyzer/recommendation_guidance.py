from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from .capacity import DEFAULT_CAPACITY_WARNING_RATIO
from .metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from .solar_flow import (
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from .standby import DEFAULT_STANDBY_THRESHOLD_W, DEFAULT_STANDBY_WINDOW_HOURS
from .usage import DEFAULT_DAILY_USAGE_SPIKE_RATIO
from .ux import friendly_feature_name

_SETTING_DEFAULTS: dict[str, Any] = {
    "daily_spike_ratio": DEFAULT_DAILY_USAGE_SPIKE_RATIO,
    "max_active_minutes": None,
    "max_idle_minutes": None,
    "warning_ratio": DEFAULT_CAPACITY_WARNING_RATIO,
    "window_hours": DEFAULT_STANDBY_WINDOW_HOURS,
    "standby_threshold_w": DEFAULT_STANDBY_THRESHOLD_W,
    "always_on_alert_w": 0.0,
    "standby_min_samples": 24,
    "leg_imbalance_warning_ratio": DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    "leg_imbalance_min_total_power_w": DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    "apparent_power_tolerance_percent": (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
    ),
    "power_factor_tolerance": DEFAULT_POWER_FACTOR_TOLERANCE,
    "minimum_apparent_power_va": DEFAULT_MIN_APPARENT_POWER_VA,
    "balance_negative_tolerance_w": DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    "solar_surplus_threshold_w": SOLAR_SURPLUS_THRESHOLD_W,
    "high_solar_surplus_threshold_w": HIGH_SOLAR_SURPLUS_THRESHOLD_W,
}

_SETTING_EXPECTED_EFFECTS = {
    "daily_spike_ratio": (
        "Tune this setting toward the observed history without requiring manual "
        "threshold math."
    ),
    "max_active_minutes": (
        "Reduce false long-run alerts while still flagging unusually long cycles."
    ),
    "max_idle_minutes": (
        "Reduce idle-runtime noise while keeping extended idle runs visible."
    ),
    "warning_ratio": (
        "Warn earlier when usage approaches capacity, without changing breaker "
        "or safety assumptions."
    ),
    "window_hours": (
        "Use enough standby history to distinguish normal idle draw from "
        "short-lived power changes."
    ),
    "standby_threshold_w": (
        "Separate normal standby draw from runs so idle alerts are less noisy."
    ),
    "always_on_alert_w": (
        "Surface unusually high Always On draw without changing run-cycle or "
        "standby detection."
    ),
    "standby_min_samples": (
        "Require enough standby samples before changing idle detection behavior."
    ),
    "leg_imbalance_warning_ratio": (
        "Tune split-phase imbalance alerts toward observed paired-leg behavior."
    ),
    "leg_imbalance_min_total_power_w": (
        "Avoid imbalance alerts when the circuit is below meaningful total load."
    ),
    "apparent_power_tolerance_percent": (
        "Tune metric consistency checks for W, VA, current, and power-factor "
        "relationships toward this circuit's observed sensor residuals."
    ),
    "power_factor_tolerance": (
        "Tune power-factor relationship checks to this circuit's observed "
        "sensor behavior without hiding larger metric mismatches."
    ),
    "minimum_apparent_power_va": (
        "Ignore low apparent-power samples where sensor noise can dominate "
        "metric consistency checks."
    ),
    "balance_negative_tolerance_w": (
        "Tune mains-minus-load balance checks while still surfacing mapping, "
        "solar, or CT-orientation problems."
    ),
    "solar_surplus_threshold_w": (
        "Start solar surplus guidance near typical observed export so load "
        "shifting prompts are less noisy."
    ),
    "high_solar_surplus_threshold_w": (
        "Reserve high solar surplus guidance for the upper end of observed "
        "export events."
    ),
}


def recommendation_setting_default_value(setting_key: str) -> Any:
    """Return the built-in default shown beside a suggested setting."""
    return _SETTING_DEFAULTS.get(setting_key)


def recommendation_setting_expected_effect(setting_key: str) -> str:
    """Return the user-facing effect summary for a suggested setting."""
    return _SETTING_EXPECTED_EFFECTS.get(
        setting_key,
        (
            "Tune this setting toward the observed history without requiring "
            "manual threshold math."
        ),
    )


def recommendation_evidence_preview(evidence: Any, *, limit: int = 4) -> str:
    """Return a short, bounded evidence preview for recommendation cards."""
    if not isinstance(evidence, Mapping):
        return ""

    parts: list[str] = []
    for key, value in evidence.items():
        key_text = str(key)
        if is_hidden_recommendation_evidence_key(key_text):
            continue
        if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
            continue
        parts.append(
            f"{friendly_feature_name(key_text)}: {_format_recommendation_value(value)}"
        )
        if len(parts) >= limit:
            break
    return "; ".join(parts)


def is_hidden_recommendation_evidence_key(key: str) -> bool:
    """Return true when evidence should stay out of compact user summaries."""
    normalized = key.lower()
    return (
        "entity" in normalized
        or normalized in {"source_entities", "entity_ids", "entities"}
    )


def _format_recommendation_value(value: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
