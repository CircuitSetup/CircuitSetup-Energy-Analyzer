"""Integration-level appliance insights and conservative energy explanations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any
from urllib.parse import urlencode

from .appliance_detail import (
    ApplianceDetail,
    MetricComparison,
    appliance_detail_for_assignment,
    appliance_detail_for_circuit,
)
from .attention import attention_items_for_coordinators
from .models import CircuitMode
from .nilm_virtual import nilm_virtual_appliance_states

NILM_EXPLANATION_CONFIDENCE_THRESHOLD = 0.8
MAX_APPLIANCE_INSIGHTS = 100
PANEL_PATH = "/circuitsetup-energy-analyzer-evidence"


@dataclass(frozen=True, slots=True)
class EnergyChangeExplanation:
    """Bounded factorization of one appliance's same-time energy change."""

    appliance_key: str
    current_energy_kwh: float
    normal_energy_kwh: float
    total_change_percent: float
    runtime_contribution_percent: float | None
    running_power_contribution_percent: float | None
    cycle_count_contribution_percent: float | None
    usage_event_contribution_percent: float | None
    unexplained_percent: float | None
    confidence: float
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ApplianceInsight:
    """One filter-ready appliance row for the integration index."""

    appliance_key: str
    entry_id: str
    display_name: str
    circuit_id: str
    assignment_id: str | None
    source_type: str
    activity_state: str
    current_power_w: float | None
    daily_energy_kwh: float | None
    today_vs_normal_percent: float | None
    source_quality: dict[str, Any]
    learning_readiness: dict[str, Any]
    confidence: float | None
    needs_attention: bool
    is_running: bool
    is_learning: bool
    has_data_problem: bool
    is_nilm: bool
    detail_path: str
    source_path: str
    energy_change_explanation: EnergyChangeExplanation | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def energy_change_explanation(
    detail: ApplianceDetail | Any,
) -> EnergyChangeExplanation | None:
    """Explain an energy delta without claiming unsupported causality."""
    energy = _comparison(detail, "daily_energy_kwh")
    current_energy = _positive_or_zero(getattr(energy, "current_value", None))
    normal_energy = _positive(getattr(energy, "normal_median", None))
    if current_energy is None or normal_energy is None:
        return None

    total_change = (current_energy / normal_energy - 1.0) * 100.0
    appliance_key = str(
        getattr(detail, "appliance_key", None)
        or f"circuit:{getattr(detail, 'circuit_id', '')}"
    )
    runtime = _comparison(detail, "runtime_today_seconds")
    runs = _comparison(detail, "run_count_today")
    confidence = _explanation_confidence(detail, (energy, runtime, runs))
    if confidence < NILM_EXPLANATION_CONFIDENCE_THRESHOLD:
        is_nilm = str(getattr(detail, "source_type", "")) == "nilm_estimate"
        reason = (
            "This is an estimated NILM change; confidence is not high enough "
            "to separate the causes."
            if is_nilm
            else "Baseline confidence is not high enough to separate the causes."
        )
        return _unexplained_change(
            appliance_key=appliance_key,
            current_energy=current_energy,
            normal_energy=normal_energy,
            total_change=total_change,
            confidence=confidence,
            reason=reason,
        )

    current_runtime = _positive_or_zero(getattr(runtime, "current_value", None))
    normal_runtime = _positive(getattr(runtime, "normal_median", None))
    current_runs = _positive_or_zero(getattr(runs, "current_value", None))
    normal_runs = _positive(getattr(runs, "normal_median", None))
    if None in (current_runtime, normal_runtime, current_runs, normal_runs):
        return _unexplained_change(
            appliance_key=appliance_key,
            current_energy=current_energy,
            normal_energy=normal_energy,
            total_change=total_change,
            confidence=confidence,
            reason=(
                "There is not enough evidence to separate runtime, running "
                "power, and cycle-count effects."
            ),
        )

    runtime_ratio = current_runtime / normal_runtime
    run_count_ratio = current_runs / normal_runs
    energy_ratio = current_energy / normal_energy
    raw = {
        "cycle": (run_count_ratio - 1.0) * 100.0,
        "runtime": (runtime_ratio - run_count_ratio) * 100.0,
        "power": (energy_ratio - runtime_ratio) * 100.0,
    }
    if any(value * total_change < 0.0 for value in raw.values()):
        return _unexplained_change(
            appliance_key=appliance_key,
            current_energy=current_energy,
            normal_energy=normal_energy,
            total_change=total_change,
            confidence=confidence,
            reason=(
                "Runtime, running power, and cycle count moved in opposing "
                "directions, so the net change cannot be separated reliably."
            ),
        )
    allocated, unexplained = _bounded_contributions(total_change, raw)
    explanation = _factor_explanation(total_change, allocated, unexplained)
    if _has_weather_context(detail):
        explanation += " Outdoor-temperature context may explain some HVAC runtime."
    return EnergyChangeExplanation(
        appliance_key=appliance_key,
        current_energy_kwh=current_energy,
        normal_energy_kwh=normal_energy,
        total_change_percent=total_change,
        runtime_contribution_percent=allocated["runtime"],
        running_power_contribution_percent=allocated["power"],
        cycle_count_contribution_percent=allocated["cycle"],
        usage_event_contribution_percent=None,
        unexplained_percent=unexplained,
        confidence=confidence,
        explanation=explanation,
    )


def _unexplained_change(
    *,
    appliance_key: str,
    current_energy: float,
    normal_energy: float,
    total_change: float,
    confidence: float,
    reason: str,
) -> EnergyChangeExplanation:
    return EnergyChangeExplanation(
        appliance_key=appliance_key,
        current_energy_kwh=current_energy,
        normal_energy_kwh=normal_energy,
        total_change_percent=total_change,
        runtime_contribution_percent=None,
        running_power_contribution_percent=None,
        cycle_count_contribution_percent=None,
        usage_event_contribution_percent=None,
        unexplained_percent=total_change,
        confidence=confidence,
        explanation=f"{_change_summary(total_change)} {reason}",
    )


def appliance_insights_for_coordinators(
    coordinators: Iterable[Any],
) -> tuple[ApplianceInsight, ...]:
    """Return a bounded, deduplicated appliance index in action-first order."""
    coordinators = tuple(coordinators)
    attention_keys: set[tuple[str, str]] = set()
    for coordinator in coordinators:
        entry_id = str(getattr(coordinator, "entry_id", "") or "")
        attention_keys.update(
            (entry_id, item.appliance_key)
            for item in attention_items_for_coordinators(
                (coordinator,),
                limit=MAX_APPLIANCE_INSIGHTS,
            )
        )
    insights: list[ApplianceInsight] = []
    seen: set[tuple[str, str]] = set()
    for coordinator in coordinators:
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            if getattr(config, "mode", None) == CircuitMode.MAINS_NILM:
                continue
            detail = appliance_detail_for_circuit(coordinator, config.circuit_id)
            _append_insight(
                insights,
                seen,
                coordinator,
                detail,
                attention_keys,
            )
        for state in nilm_virtual_appliance_states(
            coordinator,
            published_only=False,
        ):
            detail = appliance_detail_for_assignment(
                coordinator,
                state.assignment_id,
            )
            _append_insight(
                insights,
                seen,
                coordinator,
                detail,
                attention_keys,
            )
    insights.sort(key=_insight_sort_key)
    return tuple(insights[:MAX_APPLIANCE_INSIGHTS])


def _append_insight(
    insights: list[ApplianceInsight],
    seen: set[tuple[str, str]],
    coordinator: Any,
    detail: ApplianceDetail | Any | None,
    attention_keys: set[tuple[str, str]],
) -> None:
    if detail is None:
        return
    appliance_key = str(
        getattr(detail, "appliance_key", None)
        or f"circuit:{getattr(detail, 'circuit_id', '')}"
    )
    entry_id = str(getattr(coordinator, "entry_id", "") or "")
    identity = (entry_id, appliance_key)
    if not appliance_key or identity in seen:
        return
    seen.add(identity)
    source_quality = _mapping_copy(getattr(detail, "source_quality", None))
    readiness = _mapping_copy(getattr(detail, "learning_readiness", None))
    explanation = energy_change_explanation(detail)
    source_type = str(getattr(detail, "source_type", "direct_meter"))
    assignment_id = str(getattr(detail, "assignment_id", "") or "") or None
    activity_state = str(getattr(detail, "activity_state", "Unknown"))
    insights.append(
        ApplianceInsight(
            appliance_key=appliance_key,
            entry_id=entry_id,
            display_name=str(getattr(detail, "display_name", appliance_key)),
            circuit_id=str(getattr(detail, "circuit_id", "")),
            assignment_id=assignment_id,
            source_type=source_type,
            activity_state=activity_state,
            current_power_w=_number_or_none(getattr(detail, "current_power_w", None)),
            daily_energy_kwh=_number_or_none(
                getattr(detail, "daily_energy_kwh", None)
            ),
            today_vs_normal_percent=(
                explanation.total_change_percent if explanation else None
            ),
            source_quality=source_quality,
            learning_readiness=readiness,
            confidence=_number_or_none(getattr(detail, "confidence", None)),
            needs_attention=identity in attention_keys,
            is_running="running" in activity_state.casefold(),
            is_learning=_is_learning(readiness, detail),
            has_data_problem=_has_data_problem(source_quality),
            is_nilm=source_type == "nilm_estimate",
            detail_path=_detail_path(coordinator, detail),
            source_path=_source_path(coordinator, detail),
            energy_change_explanation=explanation,
        )
    )


def _bounded_contributions(
    total: float,
    raw: Mapping[str, float],
) -> tuple[dict[str, float], float]:
    remaining = total
    allocated: dict[str, float] = {}
    for key in ("cycle", "runtime", "power"):
        value = raw[key]
        if total == 0.0 or value * total <= 0.0:
            allocated[key] = 0.0
            continue
        bounded = min(abs(value), abs(remaining))
        contribution = bounded if total > 0.0 else -bounded
        allocated[key] = contribution
        remaining -= contribution
    if abs(remaining) < 1e-9:
        remaining = 0.0
    return allocated, remaining


def _factor_explanation(
    total: float,
    contributions: Mapping[str, float],
    unexplained: float,
) -> str:
    phrases = []
    labels = {
        "runtime": "runtime",
        "power": "running power",
        "cycle": "cycle count",
    }
    for key in ("runtime", "power", "cycle"):
        value = contributions[key]
        if abs(value) >= 0.05:
            phrases.append(f"{abs(value):.0f}% from {labels[key]}")
    if not phrases:
        return _change_summary(total) + " The change is too small to separate reliably."
    explained = abs(total - unexplained)
    qualifier = (
        "mostly explained by"
        if explained >= abs(total) * 0.75
        else "partly explained by"
    )
    return f"{_change_summary(total)} It is {qualifier} {', '.join(phrases)}."


def _change_summary(total: float) -> str:
    if abs(total) < 0.05:
        return "Energy today is close to normal."
    direction = "above" if total > 0.0 else "below"
    return f"Energy today is {abs(total):.0f}% {direction} normal."


def _comparison(detail: Any, metric_id: str) -> MetricComparison | Any | None:
    return next(
        (
            item
            for item in getattr(detail, "today_vs_normal", ()) or ()
            if getattr(item, "metric_id", None) == metric_id
        ),
        None,
    )


def _explanation_confidence(
    detail: Any,
    comparisons: Iterable[Any],
) -> float:
    values = [
        _number_or_none(getattr(comparison, "confidence", None))
        for comparison in comparisons
    ]
    if str(getattr(detail, "source_type", "")) == "nilm_estimate":
        values.append(_number_or_none(getattr(detail, "confidence", None)))
    if not values or any(value is None for value in values):
        return 0.0
    return max(0.0, min(min(value for value in values if value is not None), 1.0))


def _has_weather_context(detail: Any) -> bool:
    if "hvac" not in str(getattr(detail, "appliance_profile", "")).casefold():
        return False
    for item in getattr(detail, "expectations", ()) or ():
        text = " ".join(
            str(getattr(item, field, ""))
            for field in ("expectation_id", "title", "observed", "expected")
        ).casefold()
        if "weather" in text or "temperature" in text:
            return True
    return False


def _is_learning(readiness: Mapping[str, Any], detail: Any) -> bool:
    status = str(readiness.get("status") or "").casefold()
    model_status = str(getattr(detail, "model_status", "") or "").casefold()
    return status in {
        "learning",
        "needs_history",
        "needs_validation",
        "not_ready",
        "waiting_for_delta",
    } or model_status in {"learning", "candidate", "needs_review"}


def _has_data_problem(source_quality: Mapping[str, Any]) -> bool:
    status = str(source_quality.get("status") or "unknown").casefold()
    return status not in {"fresh", "ready", "ok", "estimated"}


def _detail_path(coordinator: Any, detail: Any) -> str:
    query = {
        "entry_id": str(getattr(coordinator, "entry_id", "") or ""),
        "appliance_detail": "1",
    }
    assignment_id = str(getattr(detail, "assignment_id", "") or "")
    if assignment_id:
        query["assignment_id"] = assignment_id
    else:
        query["circuit_id"] = str(getattr(detail, "circuit_id", ""))
    return f"{PANEL_PATH}?{urlencode(query)}"


def _source_path(coordinator: Any, detail: Any) -> str:
    assignment_id = str(getattr(detail, "assignment_id", "") or "")
    if str(getattr(detail, "source_type", "")) == "nilm_estimate" and assignment_id:
        query = {
            "entry_id": str(getattr(coordinator, "entry_id", "") or ""),
            "nilm_workspace": "1",
            "circuit_id": getattr(detail, "circuit_id", ""),
            "assignment_id": assignment_id,
        }
        return f"{PANEL_PATH}?{urlencode(query)}"
    query = {
        "config_entry": str(getattr(coordinator, "entry_id", "") or ""),
        "options_step": "sources",
        "circuit_id": str(getattr(detail, "circuit_id", "") or ""),
    }
    return f"/config/integrations/dashboard#{urlencode(query)}"


def _mapping_copy(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _number_or_none(value)
    return number if number is not None and number > 0.0 else None


def _positive_or_zero(value: Any) -> float | None:
    number = _number_or_none(value)
    return number if number is not None and number >= 0.0 else None


def _insight_sort_key(item: ApplianceInsight) -> tuple[bool, bool, float, str]:
    change = item.today_vs_normal_percent
    return (
        not item.needs_attention,
        not item.is_running,
        -abs(change) if change is not None else float("inf"),
        item.display_name.casefold(),
    )
