from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .capacity import DEFAULT_CAPACITY_WARNING_RATIO
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from .usage import DEFAULT_DAILY_USAGE_SPIKE_RATIO
from .ux import friendly_feature_name

_SETTING_DEFAULTS: dict[str, Any] = {
    "daily_spike_ratio": DEFAULT_DAILY_USAGE_SPIKE_RATIO,
    "max_active_minutes": None,
    "max_idle_minutes": None,
    "warning_ratio": DEFAULT_CAPACITY_WARNING_RATIO,
    "standby_threshold_w": 8.0,
    "standby_min_samples": 24,
    "leg_imbalance_warning_ratio": DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    "leg_imbalance_min_total_power_w": DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
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
    "standby_threshold_w": (
        "Separate normal standby draw from runs so idle alerts are less noisy."
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
