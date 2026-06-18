from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from .metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from .standby import DEFAULT_STANDBY_THRESHOLD_W
from .usage import DEFAULT_DAILY_USAGE_SPIKE_RATIO

ADVISOR_VERSION = 1
MIN_ADVISOR_DAYS = 7
DAILY_SPIKE_RATIO_SAFETY_MARGIN = 0.10
DEFAULT_RECOMMENDATION_TTL = timedelta(days=30)
DENIAL_COOLDOWN = timedelta(days=90)
DISMISSAL_COOLDOWN = DEFAULT_RECOMMENDATION_TTL
SETTING_LABELS = {
    "daily_spike_ratio": "Daily Spike Ratio",
    "max_active_minutes": "Max Active Minutes",
    "warning_ratio": "Capacity Warning Ratio",
    "standby_threshold_w": "Standby Threshold W",
    "always_on_alert_w": "Always On Alert W",
    "leg_imbalance_warning_ratio": "Leg Imbalance Warning Ratio",
    "leg_imbalance_min_total_power_w": "Leg Imbalance Minimum Total Power W",
    "apparent_power_tolerance_percent": "Apparent Power Tolerance Percent",
    "power_factor_tolerance": "Power Factor Tolerance",
    "minimum_apparent_power_va": "Minimum Apparent Power VA",
    "balance_negative_tolerance_w": "Balance Negative Tolerance W",
    "solar_surplus_threshold_w": "Solar Surplus Threshold W",
    "high_solar_surplus_threshold_w": "High Solar Surplus Threshold W",
    "flexible_load_running_threshold_w": "Flexible Load Running Threshold W",
    "circuit_retention_mode": "Circuit Retention Mode",
}


class RecommendationStatus(StrEnum):
    """Lifecycle state for a settings recommendation."""

    PENDING = "pending"
    APPLIED = "applied"
    DENIED = "denied"
    DISMISSED = "dismissed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SettingRecommendation:
    """A recommendation to tune one analyzer setting."""

    recommendation_id: str
    unique_key: str
    circuit_id: str
    circuit_name: str
    setting_key: str
    setting_label: str
    current_value: Any
    suggested_value: Any
    unit: str | None
    feature: str
    group: str
    confidence: float
    reason: str
    evidence: Mapping[str, Any]
    apply_payload: Mapping[str, Any]
    status: RecommendationStatus
    created_at: datetime
    expires_at: datetime
    advisor_version: int = ADVISOR_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(
            self,
            "apply_payload",
            MappingProxyType(dict(self.apply_payload)),
        )


@dataclass(frozen=True, slots=True)
class RecommendationDecision:
    """A user's decision for a recommendation unique key."""

    unique_key: str
    status: RecommendationStatus
    decided_at: datetime
    denied_value: Any = None
    evidence_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class AdvisorCircuitContext:
    """Circuit metadata and current settings available to advisor rules."""

    circuit_id: str
    circuit_name: str
    appliance_profile: str
    circuit_mode: str
    power_flow: str
    advanced_settings: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "advanced_settings",
            MappingProxyType(dict(self.advanced_settings)),
        )


@dataclass(frozen=True, slots=True)
class AdvisorInputs:
    """Inputs used to build evidence-based settings recommendations."""

    now: datetime
    context: AdvisorCircuitContext
    feature_history: Mapping[str, Any]
    decisions: Mapping[str, RecommendationDecision] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_history",
            MappingProxyType(dict(self.feature_history)),
        )
        if self.decisions is not None:
            object.__setattr__(
                self,
                "decisions",
                MappingProxyType(dict(self.decisions)),
            )


def recommendation_unique_key(circuit_id: str, setting_key: str) -> str:
    """Return the stable per-setting recommendation key."""
    return f"{circuit_id}:{setting_key}"


def recommendation_id_for(
    circuit_id: str,
    setting_key: str,
    *,
    advisor_version: int = ADVISOR_VERSION,
) -> str:
    """Return the stable advisor-versioned recommendation id."""
    return f"{recommendation_unique_key(circuit_id, setting_key)}:v{advisor_version}"


def recommendation_to_dict(
    recommendation: SettingRecommendation,
) -> dict[str, Any]:
    """Serialize a setting recommendation for JSON storage."""
    return {
        "recommendation_id": recommendation.recommendation_id,
        "unique_key": recommendation.unique_key,
        "circuit_id": recommendation.circuit_id,
        "circuit_name": recommendation.circuit_name,
        "setting_key": recommendation.setting_key,
        "setting_label": recommendation.setting_label,
        "current_value": recommendation.current_value,
        "suggested_value": recommendation.suggested_value,
        "unit": recommendation.unit,
        "feature": recommendation.feature,
        "group": recommendation.group,
        "confidence": recommendation.confidence,
        "reason": recommendation.reason,
        "evidence": dict(recommendation.evidence),
        "apply_payload": dict(recommendation.apply_payload),
        "status": recommendation.status.value,
        "created_at": recommendation.created_at.isoformat(),
        "expires_at": recommendation.expires_at.isoformat(),
        "advisor_version": recommendation.advisor_version,
    }


def recommendation_from_dict(raw: Mapping[str, Any]) -> SettingRecommendation:
    """Deserialize a setting recommendation from JSON storage."""
    return SettingRecommendation(
        recommendation_id=str(raw["recommendation_id"]),
        unique_key=str(raw["unique_key"]),
        circuit_id=str(raw["circuit_id"]),
        circuit_name=str(raw["circuit_name"]),
        setting_key=str(raw["setting_key"]),
        setting_label=str(raw["setting_label"]),
        current_value=raw.get("current_value"),
        suggested_value=raw.get("suggested_value"),
        unit=raw.get("unit"),
        feature=str(raw["feature"]),
        group=str(raw["group"]),
        confidence=float(raw["confidence"]),
        reason=str(raw["reason"]),
        evidence=dict(raw.get("evidence", {})),
        apply_payload=dict(raw.get("apply_payload", {})),
        status=RecommendationStatus(raw.get("status", RecommendationStatus.PENDING)),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        expires_at=datetime.fromisoformat(str(raw["expires_at"])),
        advisor_version=int(raw.get("advisor_version", ADVISOR_VERSION)),
    )


def decision_to_dict(decision: RecommendationDecision) -> dict[str, Any]:
    """Serialize a recommendation decision for JSON storage."""
    return {
        "unique_key": decision.unique_key,
        "status": decision.status.value,
        "decided_at": decision.decided_at.isoformat(),
        "denied_value": decision.denied_value,
        "evidence_fingerprint": decision.evidence_fingerprint,
    }


def decision_from_dict(raw: Mapping[str, Any]) -> RecommendationDecision:
    """Deserialize a recommendation decision from JSON storage."""
    return RecommendationDecision(
        unique_key=str(raw["unique_key"]),
        status=RecommendationStatus(raw["status"]),
        decided_at=datetime.fromisoformat(str(raw["decided_at"])),
        denied_value=raw.get("denied_value"),
        evidence_fingerprint=str(raw.get("evidence_fingerprint", "")),
    )


def should_suppress_recommendation(
    decision: RecommendationDecision | None,
    *,
    now: datetime,
    suggested_value: Any,
    evidence_fingerprint: str,
) -> bool:
    """Return true when a recent denial still applies to the same suggestion."""
    if decision is None:
        return False
    if decision.status is RecommendationStatus.DENIED:
        cooldown = DENIAL_COOLDOWN
    elif decision.status is RecommendationStatus.DISMISSED:
        cooldown = DISMISSAL_COOLDOWN
    else:
        return False
    if now - decision.decided_at >= cooldown:
        return False
    if decision.denied_value != suggested_value:
        return False
    return decision.evidence_fingerprint == evidence_fingerprint


def recommendation_evidence_fingerprint(
    recommendation: SettingRecommendation,
) -> str:
    """Return the evidence fingerprint used for recommendation suppression."""
    return _evidence_fingerprint(recommendation.feature, recommendation.evidence)


def build_settings_recommendations(
    inputs: AdvisorInputs,
) -> list[SettingRecommendation]:
    """Build current settings recommendations from observed circuit evidence."""
    candidates: list[SettingRecommendation] = []
    for rule in (
        _energy_usage_recommendations,
        _cycle_recommendations,
        _capacity_recommendations,
        _standby_recommendations,
        _dual_phase_recommendations,
        _metric_consistency_recommendations,
        _mains_balance_recommendations,
        _solar_flow_recommendations,
        _retention_recommendations,
    ):
        candidates.extend(rule(inputs))

    decisions = inputs.decisions or {}
    recommendations: list[SettingRecommendation] = []
    for recommendation in candidates:
        evidence_fingerprint = recommendation_evidence_fingerprint(recommendation)
        if should_suppress_recommendation(
            decisions.get(recommendation.unique_key),
            now=inputs.now,
            suggested_value=recommendation.suggested_value,
            evidence_fingerprint=evidence_fingerprint,
        ):
            continue
        recommendations.append(recommendation)
    return recommendations


def _energy_usage_recommendations(
    inputs: AdvisorInputs,
) -> list[SettingRecommendation]:
    days = _numeric_values(
        inputs.feature_history.get("energy_usage_days"),
        key="usage_kwh",
    )
    if len(days) < MIN_ADVISOR_DAYS:
        return []

    observed_days = days[-MIN_ADVISOR_DAYS:]
    total_window_kwh = sum(observed_days)
    if total_window_kwh <= 0:
        return []

    p95_daily_kwh = round(_percentile(observed_days, 95), 1)
    suggested_value = _round_ratio(
        (p95_daily_kwh / total_window_kwh) + DAILY_SPIKE_RATIO_SAFETY_MARGIN
    )
    current_value = _float_setting(
        inputs.context.advanced_settings,
        "daily_spike_ratio",
        DEFAULT_DAILY_USAGE_SPIKE_RATIO,
    )
    if suggested_value <= current_value:
        return []

    return [
        _make_recommendation(
            inputs,
            setting_key="daily_spike_ratio",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="ratio",
            feature="energy_usage_spikes",
            group="Energy Usage",
            confidence=0.78,
            reason=(
                f"Observed {len(observed_days)} complete days of energy usage; "
                f"the 95th percentile daily usage was {p95_daily_kwh:g} kWh."
            ),
            evidence={
                "observed_days": len(observed_days),
                "p95_daily_kwh": p95_daily_kwh,
            },
        )
    ]


def _cycle_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    durations = _numeric_values(
        inputs.feature_history.get("cycles"),
        key="duration_minutes",
    )
    if len(durations) < 5:
        return []

    p95_active_minutes = int(_percentile(durations, 95))
    suggested_value = _round_to_nearest(p95_active_minutes + 20, 5)
    current_value = _optional_float_setting(
        inputs.context.advanced_settings,
        "max_active_minutes",
    )
    if current_value is not None and suggested_value <= current_value:
        return []

    return [
        _make_recommendation(
            inputs,
            setting_key="max_active_minutes",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="min",
            feature="run_cycle_runtime",
            group="Run Cycle",
            confidence=0.8,
            reason=(
                f"Based on {len(durations)} observed run cycles, the 95th "
                f"percentile active runtime was {p95_active_minutes} minutes."
            ),
            evidence={
                "observed_cycles": len(durations),
                "p95_active_minutes": p95_active_minutes,
            },
        )
    ]


def _capacity_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    current_samples = _numeric_values(inputs.feature_history.get("current_samples"))
    if (
        inputs.context.appliance_profile != "ev_charger"
        or len(current_samples) < 7
    ):
        return []

    suggested_value = 0.75
    current_value = _optional_float_setting(
        inputs.context.advanced_settings,
        "warning_ratio",
    )
    if current_value is not None and suggested_value >= current_value:
        return []

    return [
        _make_recommendation(
            inputs,
            setting_key="warning_ratio",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="ratio",
            feature="capacity_warning_ratio",
            group="Safety",
            confidence=0.76,
            reason=(
                "Observed sustained EV charger current samples; lower the "
                "warning ratio without inferring breaker size."
            ),
            evidence={
                "observed_samples": len(current_samples),
                "p95_current_amps": round(_percentile(current_samples, 95), 1),
            },
        )
    ]


def _standby_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    standby_samples = _numeric_values(
        inputs.feature_history.get("standby_samples_w"),
    )
    if len(standby_samples) < MIN_ADVISOR_DAYS:
        return []

    p95 = _percentile(standby_samples, 95)
    suggested_value = float(_round_to_nearest(max(5.0, p95 * 1.3), 1))
    current_value = _float_setting(
        inputs.context.advanced_settings,
        "standby_threshold_w",
        DEFAULT_STANDBY_THRESHOLD_W,
    )
    if math.isclose(suggested_value, current_value):
        return []

    return [
        _make_recommendation(
            inputs,
            setting_key="standby_threshold_w",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="W",
            feature="always_on_standby",
            group="Standby",
            confidence=0.78,
            reason=(
                f"{inputs.context.circuit_name} has a stable low-power pattern. "
                "The suggested standby threshold leaves margin above the observed "
                "low-power cluster."
            ),
            evidence={
                "observed_samples": len(standby_samples),
                "median_standby_w": round(_median(standby_samples), 1),
                "p95_standby_w": round(p95, 1),
            },
        )
    ]


def _dual_phase_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    if inputs.context.circuit_mode != "dual_phase":
        return []

    ratios = _numeric_values(
        inputs.feature_history.get("leg_imbalance_ratios"),
    )
    totals = _numeric_values(
        inputs.feature_history.get("dual_phase_total_power_w"),
    )
    if len(ratios) < MIN_ADVISOR_DAYS or len(totals) < MIN_ADVISOR_DAYS:
        return []

    p95_ratio = _percentile(ratios, 95)
    p25_total = _percentile(totals, 25)
    suggested_ratio = round(_clamp(max(0.15, p95_ratio * 3), 0.15, 0.5), 2)
    suggested_minimum = float(
        _round_to_nearest(max(250.0, p25_total * 0.95), 250)
    )
    recommendations: list[SettingRecommendation] = []

    current_ratio = _float_setting(
        inputs.context.advanced_settings,
        "leg_imbalance_warning_ratio",
        DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    )
    if suggested_ratio < current_ratio - 0.05:
        recommendations.append(
            _make_recommendation(
                inputs,
                setting_key="leg_imbalance_warning_ratio",
                current_value=current_ratio,
                suggested_value=suggested_ratio,
                unit=None,
                feature="dual_phase_leg_imbalance",
                group="Dual Phase",
                confidence=0.82,
                reason=(
                    "The paired legs have repeatedly run with a tighter balance "
                    "than the current warning threshold. The suggestion stays "
                    "above the observed high-end imbalance."
                ),
                evidence={
                    "observed_samples": len(ratios),
                    "p95_imbalance_ratio": round(p95_ratio, 3),
                    "p25_total_power_w": round(p25_total, 1),
                },
            )
        )

    current_minimum = _float_setting(
        inputs.context.advanced_settings,
        "leg_imbalance_min_total_power_w",
        DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    )
    if abs(current_minimum - suggested_minimum) >= 250:
        recommendations.append(
            _make_recommendation(
                inputs,
                setting_key="leg_imbalance_min_total_power_w",
                current_value=current_minimum,
                suggested_value=suggested_minimum,
                unit="W",
                feature="dual_phase_leg_imbalance",
                group="Dual Phase",
                confidence=0.8,
                reason=(
                    "Dual-phase imbalance should be evaluated when the appliance "
                    "is genuinely active, not while it is idle or lightly loaded."
                ),
                evidence={
                    "observed_samples": len(totals),
                    "p25_total_power_w": round(p25_total, 1),
                    "median_total_power_w": round(_median(totals), 1),
                },
            )
        )
    return recommendations


def _metric_consistency_recommendations(
    inputs: AdvisorInputs,
) -> list[SettingRecommendation]:
    residuals = _numeric_values(
        inputs.feature_history.get("apparent_power_residual_percent"),
    )
    pf_residuals = _numeric_values(
        inputs.feature_history.get("power_factor_residual"),
    )
    va_samples = _numeric_values(
        inputs.feature_history.get("apparent_power_samples_va"),
    )
    recommendations: list[SettingRecommendation] = []

    if len(residuals) >= MIN_ADVISOR_DAYS:
        p95 = _percentile(residuals, 95)
        suggested_value = float(
            _round_to_nearest(_clamp(p95 * 2, 5.0, 25.0), 1)
        )
        current_value = _float_setting(
            inputs.context.advanced_settings,
            "apparent_power_tolerance_percent",
            DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
        )
        if suggested_value < current_value - 3:
            recommendations.append(
                _make_recommendation(
                    inputs,
                    setting_key="apparent_power_tolerance_percent",
                    current_value=current_value,
                    suggested_value=suggested_value,
                    unit="%",
                    feature="power_metric_consistency",
                    group="Power Quality",
                    confidence=0.78,
                    reason=(
                        "Observed W, VA, current, and power-factor residuals are "
                        "stable enough to tune the metric consistency tolerance."
                    ),
                    evidence={
                        "observed_samples": len(residuals),
                        "p95_apparent_power_residual_percent": round(p95, 2),
                    },
                )
            )

    if len(pf_residuals) >= MIN_ADVISOR_DAYS:
        p95_pf = _percentile(pf_residuals, 95)
        suggested_pf = round(_clamp(p95_pf + 0.02, 0.05, 0.2), 2)
        current_pf = _float_setting(
            inputs.context.advanced_settings,
            "power_factor_tolerance",
            DEFAULT_POWER_FACTOR_TOLERANCE,
        )
        if suggested_pf < current_pf - 0.02:
            recommendations.append(
                _make_recommendation(
                    inputs,
                    setting_key="power_factor_tolerance",
                    current_value=current_pf,
                    suggested_value=suggested_pf,
                    unit=None,
                    feature="power_metric_consistency",
                    group="Power Quality",
                    confidence=0.76,
                    reason=(
                        "Power-factor relationship checks have a stable residual "
                        "pattern, so the tolerance can be tuned to the observed "
                        "sensor behavior."
                    ),
                    evidence={
                        "observed_samples": len(pf_residuals),
                        "p95_power_factor_residual": round(p95_pf, 3),
                    },
                )
            )

    if len(va_samples) >= MIN_ADVISOR_DAYS:
        p10_va = _percentile(va_samples, 10)
        minimum_va = float(_round_to_nearest(max(50.0, p10_va * 0.5), 25))
        current_va = _float_setting(
            inputs.context.advanced_settings,
            "minimum_apparent_power_va",
            DEFAULT_MIN_APPARENT_POWER_VA,
        )
        if minimum_va < current_va and current_va - minimum_va >= 50:
            recommendations.append(
                _make_recommendation(
                    inputs,
                    setting_key="minimum_apparent_power_va",
                    current_value=current_va,
                    suggested_value=minimum_va,
                    unit="VA",
                    feature="power_metric_consistency",
                    group="Power Quality",
                    confidence=0.72,
                    reason=(
                        "The observed apparent-power range supports a circuit "
                        "specific minimum before metric consistency is evaluated."
                    ),
                    evidence={
                        "observed_samples": len(va_samples),
                        "p10_apparent_power_va": round(p10_va, 1),
                    },
                )
            )

    return recommendations


def _mains_balance_recommendations(
    inputs: AdvisorInputs,
) -> list[SettingRecommendation]:
    if inputs.context.circuit_mode != "mains_nilm":
        return []

    values = _numeric_values(inputs.feature_history.get("negative_balance_w"))
    if len(values) < MIN_ADVISOR_DAYS:
        return []

    p95 = _percentile(values, 95)
    suggested_value = float(
        _round_to_nearest(_clamp(p95 * 1.25, 100.0, 1500.0), 50)
    )
    current_value = _float_setting(
        inputs.context.advanced_settings,
        "balance_negative_tolerance_w",
        DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    )
    if suggested_value >= current_value or current_value - suggested_value < 50:
        return []

    return [
        _make_recommendation(
            inputs,
            setting_key="balance_negative_tolerance_w",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="W",
            feature="mains_balance",
            group="Mains Balance",
            confidence=0.76,
            reason=(
                "Measured mains-minus-load balance has enough history to tune "
                "the negative balance tolerance while still surfacing mapping, "
                "solar, or CT-orientation problems."
            ),
            evidence={
                "observed_samples": len(values),
                "p95_negative_balance_w": round(p95, 1),
            },
        )
    ]


def _solar_flow_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    if inputs.context.power_flow not in {"mains_net", "generation"}:
        return []

    exports = _numeric_values(inputs.feature_history.get("solar_export_w"))
    if len(exports) < MIN_ADVISOR_DAYS:
        return []

    positive_exports = [value for value in exports if value > 0]
    if len(positive_exports) < 3:
        return []

    p50 = _percentile(positive_exports, 50)
    p95 = _percentile(positive_exports, 95)
    suggestions = (
        (
            "solar_surplus_threshold_w",
            float(_round_to_nearest(_clamp(p50, 250.0, 5000.0), 100)),
            "Solar surplus should start near the middle of observed export events.",
        ),
        (
            "high_solar_surplus_threshold_w",
            float(_round_to_nearest(_clamp(p95, 750.0, 10000.0), 100)),
            "High solar surplus should represent the upper end of observed "
            "export events.",
        ),
    )
    recommendations: list[SettingRecommendation] = []
    for setting_key, suggested_value, reason in suggestions:
        current_value = _optional_float_setting(
            inputs.context.advanced_settings,
            setting_key,
        )
        if current_value is not None and abs(current_value - suggested_value) < 250:
            continue
        recommendations.append(
            _make_recommendation(
                inputs,
                setting_key=setting_key,
                current_value=current_value,
                suggested_value=suggested_value,
                unit="W",
                feature="solar_flow",
                group="Solar Flow",
                confidence=0.74,
                reason=reason,
                evidence={
                    "observed_export_samples": len(positive_exports),
                    "median_export_w": round(p50, 1),
                    "p95_export_w": round(p95, 1),
                },
            )
        )
    return recommendations


def _retention_recommendations(inputs: AdvisorInputs) -> list[SettingRecommendation]:
    return []


def _make_recommendation(
    inputs: AdvisorInputs,
    *,
    setting_key: str,
    current_value: Any,
    suggested_value: Any,
    unit: str | None,
    feature: str,
    group: str,
    confidence: float,
    reason: str,
    evidence: Mapping[str, Any],
) -> SettingRecommendation:
    context = inputs.context
    return SettingRecommendation(
        recommendation_id=recommendation_id_for(context.circuit_id, setting_key),
        unique_key=recommendation_unique_key(context.circuit_id, setting_key),
        circuit_id=context.circuit_id,
        circuit_name=context.circuit_name,
        setting_key=setting_key,
        setting_label=SETTING_LABELS.get(
            setting_key,
            setting_key.replace("_", " ").capitalize(),
        ),
        current_value=current_value,
        suggested_value=suggested_value,
        unit=unit,
        feature=feature,
        group=group,
        confidence=_clamp(confidence, 0.0, 1.0),
        reason=reason,
        evidence=evidence,
        apply_payload={setting_key: suggested_value},
        status=RecommendationStatus.PENDING,
        created_at=inputs.now,
        expires_at=inputs.now + DEFAULT_RECOMMENDATION_TTL,
    )


def _numeric_values(values: Any, *, key: str | None = None) -> list[float]:
    if values is None:
        return []

    numbers: list[float] = []
    for item in values:
        raw_value = item.get(key) if key and isinstance(item, Mapping) else item
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            numbers.append(value)
    return numbers


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = math.ceil((percentile / 100) * len(sorted_values)) - 1
    return sorted_values[int(_clamp(rank, 0, len(sorted_values) - 1))]


def _float_setting(
    settings: Mapping[str, Any],
    setting_key: str,
    default: float,
) -> float:
    value = _optional_float_setting(settings, setting_key)
    if value is None:
        return default
    return value


def _optional_float_setting(
    settings: Mapping[str, Any],
    setting_key: str,
) -> float | None:
    raw_value = settings.get(setting_key)
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _round_ratio(value: float) -> float:
    return _clamp(round(value, 1), 0.05, 1.0)


def _round_to_nearest(value: float, increment: int) -> int:
    return int(round(value / increment) * increment)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _evidence_fingerprint(
    feature: str,
    evidence: Mapping[str, Any],
) -> str:
    if evidence.get("source") == "unhelpful_alert_feedback":
        return (
            "unhelpful_alert_feedback:"
            f"{evidence.get('feedback_fingerprint')};"
            f"suggested={evidence.get('suggested_daily_spike_ratio')}"
        )
    if feature == "energy_usage_spikes":
        return (
            "energy_usage_spikes:"
            f"days={evidence.get('observed_days')};"
            f"p95={evidence.get('p95_daily_kwh')}"
        )
    if feature == "run_cycle_runtime":
        return (
            "run_cycle_runtime:"
            f"cycles={evidence.get('observed_cycles')};"
            f"p95={evidence.get('p95_active_minutes')}"
        )
    if feature == "capacity_warning_ratio":
        return (
            "capacity_warning_ratio:"
            f"samples={evidence.get('observed_samples')};"
            f"p95={evidence.get('p95_current_amps')}"
        )
    return feature
