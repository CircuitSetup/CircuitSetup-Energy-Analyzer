"""Stable read models for appliance-centered panel and diagnostic payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from .session_timeline import ApplianceTimelineSession

SourceType = Literal["direct_meter", "nilm_estimate", "mixed", "mains", "unknown"]
ExpectationStatus = Literal[
    "ok",
    "watch",
    "possible_issue",
    "expected",
    "not_enough_data",
    "not_applicable",
]
MetricStatus = Literal["normal", "higher", "lower", "learning", "missing_data"]


class ComparisonMode(StrEnum):
    """Declare which concepts one appliance comparison relates."""

    SAME_TIME_OF_DAY = "same_time_of_day"
    FULL_PERIOD_OBSERVED = "full_period_observed"
    PROJECTED_END_OF_PERIOD = "projected_end_of_period"
    CURRENT_STATE = "current_state"
    RUNNING_STATE = "running_state"


@dataclass(slots=True)
class MetricComparison:
    """One Today vs Normal comparison for an appliance."""

    metric_id: str
    label: str
    unit: str
    current_value: float | None
    normal_low: float | None
    normal_high: float | None
    normal_median: float | None
    status: MetricStatus
    confidence: float | None
    source: str
    comparison_mode: ComparisonMode = ComparisonMode.CURRENT_STATE
    as_of: datetime | None = None
    projection_value: float | None = None
    projection_low: float | None = None
    projection_high: float | None = None
    projection_confidence: float | None = None
    full_period_normal_low: float | None = None
    full_period_normal_high: float | None = None
    full_period_normal_median: float | None = None
    configured_warning_value: float | None = None
    configured_limit_value: float | None = None
    limit_unit: str | None = None
    explanation: str = ""


@dataclass(slots=True)
class ApplianceExpectation:
    """Plain-language expectation derived from existing analyzer state."""

    expectation_id: str
    circuit_id: str
    title: str
    status: ExpectationStatus
    source_type: SourceType
    confidence: float | None
    observed: str
    expected: str
    why_it_matters: str
    what_to_check_first: tuple[str, ...]
    evidence_path: str | None


@dataclass(slots=True)
class ApplianceAlertSummary:
    """Bounded alert details for appliance-centered payloads."""

    alert_id: str
    feature: str
    message: str
    severity: str
    observed_value: float | None
    baseline_value: float | None
    change_ratio: float | None
    repeated_count: int
    first_seen: str | None
    last_seen: str | None
    evidence_path: str | None


@dataclass(slots=True)
class ApplianceDetail:
    """Appliance-centered read model for panel, dashboard, and diagnostics."""

    circuit_id: str
    display_name: str
    appliance_profile: str
    source_type: SourceType
    confidence: float | None
    model_status: str | None
    activity_state: str
    health_state: str
    electrical_state: str
    energy_state: str
    current_power_w: float | None
    daily_energy_kwh: float | None
    runtime_today_seconds: float | None
    run_count_today: int | None
    cost_today: float | None
    average_kwh_per_day: float | None
    average_cost_per_day: float | None
    today_vs_normal: tuple[MetricComparison, ...]
    expectations: tuple[ApplianceExpectation, ...]
    recent_timeline: dict[str, Any] | None
    active_alerts: tuple[ApplianceAlertSummary, ...]
    next_step: str | None
    what_to_check_first: tuple[str, ...]
    evidence_path: str | None
    source_quality: dict[str, Any] | None = None
    learning_readiness: dict[str, Any] | None = None
    assignment_id: str | None = None
    mains_source: str | None = None
    appliance_key: str | None = None
    appliance_id: str | None = None
    mains_circuit_id: str | None = None
    current_session_duration_seconds: float | None = None
    current_session: dict[str, Any] | None = None
    last_matched_session: dict[str, Any] | None = None
    session_timeline: tuple[ApplianceTimelineSession, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-friendly data."""
        return _jsonable(asdict(self))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
