from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from .appliance_detail import (
    ApplianceDetail,
    ApplianceExpectation,
    appliance_detail_for_assignment,
    appliance_detail_for_circuit,
)
from .models import CircuitMode
from .nilm_virtual import nilm_virtual_appliance_states

PANEL_PATH = "/circuitsetup-energy-analyzer-evidence"


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One actionable appliance finding for the integration watchlist."""

    item_id: str
    appliance_key: str
    display_name: str
    source_type: str
    category: str
    status: str
    reason: str
    confidence: float | None
    severity: str
    next_step: str
    action_path: str | None
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


def attention_items_for_coordinators(
    coordinators: Iterable[Any],
) -> tuple[AttentionItem, ...]:
    """Build a bounded, deduplicated Needs Attention list."""
    items: list[AttentionItem] = []
    seen: set[str] = set()
    for coordinator in coordinators:
        now = _coordinator_now(coordinator)
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            if getattr(config, "mode", None) == CircuitMode.MAINS_NILM:
                continue
            detail = appliance_detail_for_circuit(coordinator, config.circuit_id)
            if detail is None or not detail.appliance_key:
                continue
            item = _attention_item(detail, now=now)
            if item is not None and item.appliance_key not in seen:
                seen.add(item.appliance_key)
                items.append(item)
        for state in nilm_virtual_appliance_states(
            coordinator,
            published_only=False,
        ):
            detail = appliance_detail_for_assignment(coordinator, state.assignment_id)
            if detail is None or not detail.appliance_key:
                continue
            item = _attention_item(detail, now=now)
            if item is not None and item.appliance_key not in seen:
                seen.add(item.appliance_key)
                items.append(item)
    items.sort(key=_attention_sort_key)
    return tuple(items[:50])


def _attention_item(
    detail: ApplianceDetail,
    *,
    now: datetime,
) -> AttentionItem | None:
    expectation = next(
        (
            item
            for item in detail.expectations
            if _expectation_is_actionable(item)
        ),
        None,
    )
    if expectation is None:
        return None
    category = _attention_category(detail, expectation)
    severity = _attention_severity(category, expectation)
    appliance_key = detail.appliance_key or f"circuit:{detail.circuit_id}"
    return AttentionItem(
        item_id=f"{appliance_key}:{expectation.expectation_id}",
        appliance_key=appliance_key,
        display_name=detail.display_name,
        source_type=detail.source_type,
        category=category,
        status=expectation.status,
        reason=expectation.observed or expectation.title,
        confidence=expectation.confidence,
        severity=severity,
        next_step=(
            expectation.what_to_check_first[0]
            if expectation.what_to_check_first
            else detail.next_step
            or "Open appliance detail."
        ),
        action_path=_detail_path(detail),
        updated_at=now,
    )


def _expectation_is_actionable(expectation: ApplianceExpectation) -> bool:
    if expectation.status in {"ok", "expected", "not_applicable"}:
        return False
    if expectation.status != "not_enough_data":
        return True
    text = f"{expectation.expectation_id} {expectation.title}".lower()
    return "source data" in text or "data_quality" in text


def _attention_category(
    detail: ApplianceDetail,
    expectation: ApplianceExpectation,
) -> str:
    text = f"{expectation.expectation_id} {expectation.title}".lower()
    if "source data" in text or "data_quality" in text:
        return "fix_setup_or_data"
    if "nilm" in text or "validation" in text:
        return "validate_nilm"
    return "review_appliance_behavior"


def _attention_severity(
    category: str,
    expectation: ApplianceExpectation,
) -> str:
    if category == "fix_setup_or_data" or expectation.status == "possible_issue":
        return "high"
    if category == "validate_nilm" or expectation.status == "watch":
        return "medium"
    return "low"


def _detail_path(detail: ApplianceDetail) -> str:
    query: dict[str, str] = {"appliance_detail": "1"}
    if detail.assignment_id:
        query["assignment_id"] = detail.assignment_id
    else:
        query["circuit_id"] = detail.circuit_id
    return f"{PANEL_PATH}?{urlencode(query)}"


def _attention_sort_key(item: AttentionItem) -> tuple[int, int, str]:
    if item.category == "fix_setup_or_data":
        finding_rank = 0
    elif item.category == "review_appliance_behavior" and item.severity == "high":
        finding_rank = 1
    elif (
        item.category == "review_appliance_behavior"
        and item.confidence is not None
        and item.confidence >= 0.8
    ):
        finding_rank = 2
    elif item.category == "validate_nilm":
        finding_rank = 3
    else:
        finding_rank = 4
    severity_rank = {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3)
    return finding_rank, severity_rank, item.display_name.casefold()


def _coordinator_now(coordinator: Any) -> datetime:
    current_time = getattr(coordinator, "current_time", None)
    value = current_time() if callable(current_time) else datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
