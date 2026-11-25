from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from .alert_links import (
    DEFAULT_ALERT_EVIDENCE_PATH,
    NILM_MODEL_VALIDATION_FEATURES,
    appliance_detail_path,
)
from .appliance_detail import (
    ApplianceDetail,
    ApplianceExpectation,
    appliance_detail_for_assignment,
    appliance_detail_for_circuit,
)
from .models import CircuitMode
from .nilm_virtual import nilm_virtual_appliance_states


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

    entry_id: str = ""
    alert_ids: tuple[str, ...] = ()
    action: dict[str, str] | None = None
    actions: tuple[dict[str, str], ...] = ()
    evidence_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


def circuit_can_have_finding(coordinator: Any, config: Any) -> bool:
    """Skip building a whole-home detail unless the feed has a current warning."""
    if getattr(config, "mode", None) != CircuitMode.MAINS_NILM:
        return True
    active = getattr(
        getattr(coordinator, "state", None), "active_alerts_by_circuit", {}
    )
    return any(
        alert.severity in {"warning", "error"}
        and not alert.features.get("assignment_id")
        for alert in active.get(config.circuit_id, ())
    )


def attention_items_for_coordinators(
    coordinators: Iterable[Any],
    *,
    limit: int = 50,
) -> tuple[AttentionItem, ...]:
    """Build a bounded, deduplicated Needs Attention list."""
    items: list[AttentionItem] = []
    for coordinator in coordinators:
        seen: set[str] = set()
        for config in getattr(coordinator, "circuit_configs", ()) or ():
            if not circuit_can_have_finding(coordinator, config):
                continue
            detail = appliance_detail_for_circuit(coordinator, config.circuit_id)
            if detail is None or not detail.appliance_key:
                continue
            item = attention_item_for_detail(coordinator, detail)
            if item is not None and item.appliance_key not in seen:
                seen.add(item.appliance_key)
                items.append(item)
        for state in nilm_virtual_appliance_states(
            coordinator,
            published_only=False,
        ):
            if str(getattr(state, "model_status", "") or "").strip().casefold() in {
                "ignored",
                "expected",
                "retired",
            }:
                continue
            detail = appliance_detail_for_assignment(coordinator, state.assignment_id)
            if detail is None or not detail.appliance_key:
                continue
            item = attention_item_for_detail(coordinator, detail)
            if item is not None and item.appliance_key not in seen:
                seen.add(item.appliance_key)
                items.append(item)
    items.sort(key=_attention_sort_key)
    return tuple(items[: max(0, min(int(limit), 100))])


def attention_item_for_detail(
    coordinator: Any, detail: ApplianceDetail
) -> AttentionItem | None:
    """Classify the current detail once, retaining each distinct follow-up action."""
    entry_id = str(getattr(coordinator, "entry_id", "") or "")
    state = getattr(coordinator, "state", None)
    maintenance = getattr(state, "maintenance_by_circuit", {})
    paused = maintenance.get(detail.circuit_id, {}).get("active") is True
    now = _coordinator_now(coordinator)
    path = appliance_detail_path(
        entry_id, circuit_id=detail.circuit_id, assignment_id=detail.assignment_id
    )
    detail_action = {
        "kind": "open_detail",
        "label": "Open Appliance Detail",
        "path": path,
    }
    display_name = detail.display_name
    if detail.source_type == "mains":
        registry = getattr(getattr(coordinator, "hass", None), "config_entries", None)
        entry = registry.async_get_entry(entry_id) if registry and entry_id else None
        display_name = getattr(entry, "title", None) or display_name
    candidates = []
    if getattr(detail, "model_status", None) in {"ignored", "expected", "retired"}:
        return None
    for expectation in getattr(detail, "expectations", ()):
        if detail.source_type == "mains" or not _expectation_is_actionable(expectation):
            continue
        item = _expectation_item(detail, expectation, now=now, entry_id=entry_id)
        action = detail_action
        if item.category == "fix_setup_or_data":
            action = _source_action(coordinator, detail, entry_id)
        elif paused:
            continue
        elif item.category == "validate_nilm":
            action = _verify_match_action(
                entry_id, detail.circuit_id, detail.assignment_id
            )
        candidates.append(replace(item, entry_id=entry_id, action=action))

    if not paused:
        for alert in getattr(detail, "active_alerts", ()):
            if alert.severity not in {"warning", "error"} or alert.feature in {
                "finished_running",
                "nilm_appliance_finished",
                "learning_completed",
                "maintenance_completed",
            }:
                continue
            action = {
                "kind": "review_evidence",
                "label": "Review evidence",
                "path": alert.evidence_path or path,
            }
            evidence = action
            validation = alert.feature in NILM_MODEL_VALIDATION_FEATURES
            if validation:
                action = _verify_match_action(
                    entry_id, alert.circuit_id, alert.assignment_id
                )
            candidates.append(
                AttentionItem(
                    item_id=f"{detail.appliance_key}:{alert.alert_id}",
                    appliance_key=detail.appliance_key,
                    entry_id=entry_id,
                    display_name=display_name,
                    source_type=detail.source_type,
                    category="validate_nilm"
                    if validation
                    else "review_appliance_behavior",
                    status="possible_issue",
                    reason=alert.message,
                    confidence=None,
                    severity="high" if alert.severity == "error" else "medium",
                    next_step=action["label"],
                    action_path=path,
                    updated_at=now,
                    alert_ids=(alert.alert_id,),
                    evidence_at=alert.last_seen,
                    action=action,
                    actions=(evidence,),
                )
            )
    if not candidates:
        return None
    candidates.sort(key=_attention_sort_key)
    primary = candidates[0]
    actions = []
    for item in candidates:
        for action in (item.action, *item.actions):
            if action and action not in actions:
                actions.append(action)
    return replace(
        primary,
        actions=tuple(actions),
        alert_ids=tuple(dict.fromkeys(a for i in candidates for a in i.alert_ids)),
    )


def _verify_match_action(
    entry_id: str, circuit_id: str | None, assignment_id: str | None
) -> dict[str, str]:
    query = urlencode(
        {
            "entry_id": entry_id,
            "nilm_workspace": "1",
            "circuit_id": circuit_id,
            "assignment_id": assignment_id,
        }
    )
    return {
        "kind": "verify_appliance_match",
        "label": "Verify appliance match",
        "path": f"{DEFAULT_ALERT_EVIDENCE_PATH}?{query}",
    }


def _source_action(
    coordinator: Any, detail: ApplianceDetail, entry_id: str
) -> dict[str, str]:
    config = next(
        (c for c in coordinator.circuit_configs if c.circuit_id == detail.circuit_id),
        None,
    )
    checklist = getattr(
        getattr(coordinator, "state", None), "data_quality_checklist_by_circuit", {}
    ).get(detail.circuit_id, {})
    issues = (
        checklist.get("quality_issues_full") or checklist.get("quality_issues") or ()
    )
    sensors = {s.entity_id for s in getattr(config, "sensors", ())}
    affected = set()
    for issue in issues:
        words = str(issue).replace(":", " ").split()
        if "stale" in words:
            affected.update(word for word in words if word.startswith("sensor."))
    if len(affected) == 1 and affected <= sensors:
        entity_id = affected.pop()
        states = getattr(getattr(coordinator, "hass", None), "states", None)
        if states is None or states.get(entity_id) is not None:
            return {
                "kind": "open_sensor",
                "label": "Open sensor",
                "entity_id": entity_id,
            }
    query = urlencode(
        {"setup_health": "1", "entry_id": entry_id, "circuit_id": detail.circuit_id}
    )
    return {
        "kind": "open_setup_health",
        "label": "Open Setup Health",
        "path": f"{DEFAULT_ALERT_EVIDENCE_PATH}?{query}",
    }


def _expectation_item(
    detail: ApplianceDetail,
    expectation: ApplianceExpectation,
    *,
    now: datetime,
    entry_id: str,
) -> AttentionItem:
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
            else detail.next_step or "Open appliance detail."
        ),
        action_path=appliance_detail_path(
            entry_id, circuit_id=detail.circuit_id, assignment_id=detail.assignment_id
        ),
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


def _attention_sort_key(item: AttentionItem) -> tuple:
    if item.category == "fix_setup_or_data":
        finding_rank = 0
    elif item.category == "review_appliance_behavior" and item.severity == "high":
        finding_rank = 1
    elif item.category == "review_appliance_behavior" and (
        item.alert_ids or (item.confidence is not None and item.confidence >= 0.8)
    ):
        finding_rank = 2
    elif item.category == "validate_nilm":
        finding_rank = 3
    else:
        finding_rank = 4
    severity_rank = {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3)
    timestamp = (
        datetime.fromisoformat(item.evidence_at).timestamp() if item.evidence_at else 0
    )
    return (
        finding_rank,
        severity_rank,
        -timestamp,
        item.display_name.casefold(),
        item.entry_id,
        item.item_id,
    )


def _coordinator_now(coordinator: Any) -> datetime:
    current_time = getattr(coordinator, "current_time", None)
    value = current_time() if callable(current_time) else datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
