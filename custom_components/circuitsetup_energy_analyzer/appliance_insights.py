"""Integration-level appliance insights and conservative energy explanations."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any
from urllib.parse import urlencode

from .alert_links import appliance_detail_path
from .appliance_detail import (
    ApplianceDetail,
    MetricComparison,
    appliance_detail_for_assignment,
    appliance_detail_for_circuit,
    appliance_detail_for_virtual_state,
)
from .attention import (
    attention_item_for_detail,
    attention_sort_key,
    circuit_can_have_finding,
)
from .const import DOMAIN
from .entity import registry_device_for_identifier
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
    cost_today: float | None
    cost_today_status: str
    average_kwh_per_day: float | None
    average_cost_per_day: float | None
    today_vs_normal_percent: float | None
    source_quality: dict[str, Any]
    learning_readiness: dict[str, Any]
    confidence: float | None
    confidence_kind: str | None
    feedback_evidence_score: float | None
    finding: dict[str, Any] | None
    needs_attention: bool
    is_running: bool
    is_learning: bool
    has_data_problem: bool
    is_nilm: bool
    detail_path: str
    source_path: str
    energy_change_explanation: EnergyChangeExplanation | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.is_nilm or self.confidence_kind is None:
            payload.pop("confidence_kind", None)
        if not self.is_nilm or self.feedback_evidence_score is None:
            payload.pop("feedback_evidence_score", None)
        return payload


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
            "This is an estimated NILM change; validated evidence is not yet "
            "enough to separate the causes."
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
    insights: list[ApplianceInsight] = []
    seen: set[tuple[str, str]] = set()
    for coordinator in coordinators:
        for detail in _index_details(coordinator, compact=False):
            _append_insight(insights, seen, coordinator, detail)
    insights.sort(key=_insight_sort_key)
    return tuple(insights[:MAX_APPLIANCE_INSIGHTS])


def _index_details(coordinator: Any, *, compact: bool) -> Iterator[ApplianceDetail]:
    converted = set()
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if not compact and not circuit_can_have_finding(coordinator, config):
            continue
        detail = (
            appliance_detail_for_circuit(
                coordinator, config.circuit_id, include_timeline=False
            )
            if compact
            else appliance_detail_for_circuit(coordinator, config.circuit_id)
        )
        if detail is not None:
            if detail.assignment_id:
                converted.add(detail.assignment_id)
            yield detail
    states = (
        nilm_virtual_appliance_states(coordinator, exclude_converted=True)
        if compact
        else nilm_virtual_appliance_states(coordinator, published_only=False)
    )
    for state in states:
        if state.assignment_id in converted or getattr(state, "model_status", None) in {
            "ignored",
            "expected",
            "retired",
        }:
            continue
        detail = (
            appliance_detail_for_virtual_state(coordinator, state)
            if compact
            else appliance_detail_for_assignment(coordinator, state.assignment_id)
        )
        if detail is not None:
            yield detail


def attention_projection(
    coordinators: Mapping[str, Any],
    labels: Mapping[str, str],
    *,
    entry_id: str | None,
    offset: int,
    sort: str,
    running: bool,
    nilm_estimated: bool,
    learning: bool,
    data_problem: bool,
) -> dict[str, Any]:
    """Count all scoped sources before filtering and paging current findings."""
    coverage = dict.fromkeys(
        (
            "direct_monitored",
            "shared_circuits",
            "whole_home_feeds",
            "identified_estimates",
            "estimates_awaiting_verification",
            "learning",
            "unavailable",
        ),
        0,
    )
    coverage_key = {
        "direct_meter": "direct_monitored",
        "mixed": "shared_circuits",
        "mains": "whole_home_feeds",
        "nilm_estimate": "identified_estimates",
    }
    total = 0
    matches = []
    for owner, coordinator in coordinators.items():
        if entry_id is not None and entry_id != owner:
            continue
        seen = set()
        for detail in _index_details(coordinator, compact=True):
            if detail.appliance_key in seen:
                continue
            seen.add(detail.appliance_key)
            readiness = detail.learning_readiness or {}
            quality = detail.source_quality or {}
            is_learning = _is_learning(readiness, detail)
            is_nilm = detail.source_type == "nilm_estimate"
            has_problem = _has_data_problem(quality)
            coverage[coverage_key[detail.source_type]] += 1
            coverage["learning"] += int(is_learning)
            coverage["estimates_awaiting_verification"] += int(
                is_nilm and readiness.get("status") == "needs_validation"
            )
            coverage["unavailable"] += int(
                has_problem or (not is_nilm and detail.current_power_w is None)
            )
            finding = attention_item_for_detail(coordinator, detail)
            if finding is None:
                continue
            total += 1
            if (
                (running and "running" not in detail.activity_state.casefold())
                or (nilm_estimated and not is_nilm)
                or (learning and not is_learning)
                or (data_problem and not has_problem)
            ):
                continue
            order = attention_sort_key(finding)
            if sort == "name":
                order = (finding.display_name.casefold(), *order)
            elif sort in {"highest_energy", "largest_change"}:
                value = detail.daily_energy_kwh
                if sort == "largest_change":
                    explanation = energy_change_explanation(detail)
                    value = (
                        abs(explanation.total_change_percent) if explanation else None
                    )
                order = (value is None, -(value or 0), *order)
            matches.append((order, finding, detail.circuit_id, detail.assignment_id))
    matches.sort(key=lambda match: match[0])
    end = offset + MAX_APPLIANCE_INSIGHTS
    rows = []
    for _, finding, circuit, assignment in matches[offset:end]:
        owner = finding.entry_id
        row = {
            **finding.as_dict(),
            "meter_label": labels[owner],
            "circuit_id": circuit,
            "assignment_id": assignment,
        }
        if finding.source_type == "mains":
            row["display_name"] = labels[owner]
        device_key = (
            f"nilm_{assignment}" if finding.source_type == "nilm_estimate" else circuit
        )
        area = _device_area(coordinators[owner], owner, device_key)
        if area:
            row["area"] = area
        rows.append(row)
    return {
        "status": "not_found"
        if entry_id is not None and entry_id not in coordinators
        else "ok",
        "meters": [
            {"entry_id": owner, "label": label} for owner, label in labels.items()
        ],
        "coverage": coverage,
        "total_affected": total,
        "matching_count": len(matches),
        "next_offset": end if end < len(matches) else None,
        "items": rows,
    }


def _device_area(coordinator: Any, entry_id: str, device_key: str) -> str | None:
    hass = getattr(coordinator, "hass", None)
    if not hasattr(hass, "data"):
        return None
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    device = registry_device_for_identifier(
        dr.async_get(hass), (DOMAIN, f"{entry_id}_{device_key}"), entry_id
    )
    if device and device.area_id:
        area = ar.async_get(hass).async_get_area(device.area_id)
        return area.name if area else None
    return None


def _append_insight(
    insights: list[ApplianceInsight],
    seen: set[tuple[str, str]],
    coordinator: Any,
    detail: ApplianceDetail | Any | None,
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
    finding = attention_item_for_detail(coordinator, detail)
    if detail.source_type == "mains" and finding is None:
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
            display_name=finding.display_name
            if finding
            else str(getattr(detail, "display_name", appliance_key)),
            circuit_id=str(getattr(detail, "circuit_id", "")),
            assignment_id=assignment_id,
            source_type=source_type,
            activity_state=activity_state,
            current_power_w=_number_or_none(getattr(detail, "current_power_w", None)),
            daily_energy_kwh=_number_or_none(getattr(detail, "daily_energy_kwh", None)),
            cost_today=_number_or_none(getattr(detail, "cost_today", None)),
            cost_today_status=str(getattr(detail, "cost_today_status", "unavailable")),
            average_kwh_per_day=_number_or_none(
                getattr(detail, "average_kwh_per_day", None)
            ),
            average_cost_per_day=_number_or_none(
                getattr(detail, "average_cost_per_day", None)
            ),
            today_vs_normal_percent=(
                explanation.total_change_percent if explanation else None
            ),
            source_quality=source_quality,
            learning_readiness=readiness,
            confidence=_number_or_none(getattr(detail, "confidence", None)),
            confidence_kind=(str(getattr(detail, "confidence_kind", "") or "") or None),
            feedback_evidence_score=_number_or_none(
                getattr(detail, "feedback_evidence_score", None)
            ),
            needs_attention=finding is not None,
            finding=finding.as_dict() if finding else None,
            is_running="running" in activity_state.casefold(),
            is_learning=_is_learning(readiness, detail),
            has_data_problem=_has_data_problem(source_quality),
            is_nilm=source_type == "nilm_estimate",
            detail_path=appliance_detail_path(
                getattr(coordinator, "entry_id", None),
                circuit_id=detail.circuit_id,
                assignment_id=detail.assignment_id,
            ),
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
    return any(
        "weather_context"
        in str(getattr(item, "expectation_id", "")).casefold()
        for item in getattr(detail, "expectations", ()) or ()
    )


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
    return f"/config/integrations/integration/{DOMAIN}"


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
