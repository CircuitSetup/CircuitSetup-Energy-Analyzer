from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .state import circuit_is_learning


@dataclass(frozen=True, slots=True)
class DigestItem:
    appliance_key: str
    display_name: str
    energy_kwh: float
    normal_energy_kwh: float
    change_ratio: float
    confidence: float
    status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WeeklyApplianceDigest:
    week_start: date
    week_end: date
    biggest_changes: tuple[DigestItem, ...]
    top_energy_users: tuple[DigestItem, ...]
    observed_alerts: tuple[DigestItem, ...]
    unresolved_items: tuple[DigestItem, ...]
    nilm_review_items: tuple[DigestItem, ...]
    load_shift_opportunities: tuple[DigestItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "biggest_changes": [item.as_dict() for item in self.biggest_changes],
            "top_energy_users": [item.as_dict() for item in self.top_energy_users],
            "observed_alerts": [item.as_dict() for item in self.observed_alerts],
            "unresolved_items": [item.as_dict() for item in self.unresolved_items],
            "nilm_review_items": [item.as_dict() for item in self.nilm_review_items],
            "load_shift_opportunities": [
                item.as_dict() for item in self.load_shift_opportunities
            ],
        }


def build_weekly_digest(
    items: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    time_zone: tzinfo,
) -> WeeklyApplianceDigest:
    """Build a bounded, appliance-relative digest for the local week."""
    week_start, week_end = completed_week_bounds(now, time_zone)
    raw_items = tuple(items)
    parsed = tuple(item for raw in raw_items if (item := _digest_item(raw)) is not None)
    active = tuple(item for item in parsed if item.status != "resolved")
    expected_keys = {
        str(raw.get("appliance_key") or "")
        for raw in raw_items
        if isinstance(raw, Mapping) and raw.get("expected_context") is True
    }
    comparable_keys = {
        str(raw.get("appliance_key") or "")
        for raw in raw_items
        if isinstance(raw, Mapping) and raw.get("comparable_energy") is not False
    }
    changes = tuple(
        sorted(
            (
                item
                for item in active
                if item.appliance_key not in expected_keys
                and item.appliance_key in comparable_keys
                and item.normal_energy_kwh > 0.0
                and item.change_ratio != 0.0
            ),
            key=lambda item: (
                abs(item.change_ratio) * item.confidence,
                item.energy_kwh,
            ),
            reverse=True,
        )[:5]
    )
    return WeeklyApplianceDigest(
        week_start=week_start,
        week_end=week_end,
        biggest_changes=changes,
        top_energy_users=tuple(
            sorted(
                (
                    item
                    for item in active
                    if item.appliance_key in comparable_keys
                ),
                key=lambda item: item.energy_kwh,
                reverse=True,
            )[:5]
        ),
        observed_alerts=tuple(item for item in active if item.status == "observed")[:5],
        unresolved_items=tuple(item for item in active if item.status == "unresolved")[
            :5
        ],
        nilm_review_items=tuple(
            item for item in active if item.status == "nilm_review_needed"
        )[:5],
        load_shift_opportunities=tuple(
            item for item in active if item.status == "load_shift_opportunity"
        )[:5],
    )


def digest_idempotence_key(digest: WeeklyApplianceDigest) -> str:
    return f"weekly_appliance_digest:{digest.week_start.isoformat()}"


def completed_week_bounds(now: datetime, time_zone: tzinfo) -> tuple[date, date]:
    """Return the most recently ended local Monday-Sunday reporting week."""
    local_date = now.astimezone(time_zone).date()
    week_end = local_date - timedelta(days=local_date.weekday() + 1)
    return week_end - timedelta(days=6), week_end


def digest_items_for_coordinator(
    coordinator: Any,
    *,
    now: datetime,
    time_zone: tzinfo,
) -> list[dict[str, Any]]:
    """Collect bounded direct and NILM appliance inputs from coordinator state."""
    items: list[dict[str, Any]] = []
    state = getattr(coordinator, "state", None)
    store_data = getattr(coordinator, "store_data", None)
    energy_history = getattr(store_data, "energy_usage_by_circuit", {})
    active_alerts = getattr(state, "active_alerts_by_circuit", {})
    learning = getattr(state, "learning_progress_by_circuit", {})
    energy_evidence = getattr(state, "energy_usage_evidence_by_circuit", {})
    week_start, week_end = completed_week_bounds(now, time_zone)
    prior_start = week_start - timedelta(days=7)
    prior_end = week_start - timedelta(days=1)
    for config in getattr(coordinator, "circuit_configs", ()):
        circuit_id = str(getattr(config, "circuit_id", "") or "")
        mode = str(getattr(getattr(config, "mode", ""), "value", ""))
        if not circuit_id or mode == "mains_nilm":
            continue
        history = (
            energy_history.get(circuit_id, {})
            if isinstance(energy_history, Mapping)
            else {}
        )
        days = history.get("days", ()) if isinstance(history, Mapping) else ()
        week_values = _complete_daily_values_between(days, week_start, week_end)
        prior_values = _complete_daily_values_between(days, prior_start, prior_end)
        if circuit_is_learning(state, circuit_id):
            continue
        has_active_alert = bool(
            isinstance(active_alerts, Mapping)
            and active_alerts.get(circuit_id)
        )
        comparable_energy = len(week_values) == 7 and len(prior_values) == 7
        if not comparable_energy and not has_active_alert:
            continue
        progress = learning.get(circuit_id, {}) if isinstance(learning, Mapping) else {}
        evidence = (
            energy_evidence.get(circuit_id, {})
            if isinstance(energy_evidence, Mapping)
            else {}
        )
        item = {
            "appliance_key": f"circuit:{circuit_id}",
            "display_name": str(getattr(config, "name", "") or circuit_id),
            "energy_kwh": sum(week_values.values()) if comparable_energy else 0.0,
            "normal_energy_kwh": (
                sum(prior_values.values()) if comparable_energy else 0.0
            ),
            "confidence": 1.0
            if isinstance(progress, Mapping) and progress.get("alert_ready")
            else 0.6,
            "status": "unresolved" if has_active_alert else "normal",
            "expected_context": (
                isinstance(evidence, Mapping)
                and evidence.get("status") == "context_explained"
            ),
        }
        if not comparable_energy:
            item["comparable_energy"] = False
        items.append(item)
    items_by_key = {item["appliance_key"]: item for item in items}
    load_shift_evidence = getattr(state, "solar_load_shift_evidence_by_circuit", {})
    candidate_budget = 100
    if isinstance(load_shift_evidence, Mapping):
        for index, evidence in enumerate(load_shift_evidence.values()):
            if index >= 100 or candidate_budget == 0:
                break
            if (
                not isinstance(evidence, Mapping)
                or evidence.get("status") != "surplus_candidate"
            ):
                continue
            candidates = evidence.get("candidate_loads")
            for candidate in (
                candidates[:candidate_budget] if isinstance(candidates, list) else ()
            ):
                candidate_budget -= 1
                if (
                    not isinstance(candidate, Mapping)
                    or candidate.get("state") != "idle"
                ):
                    continue
                circuit_id = str(candidate.get("circuit_id") or "").strip()
                if not circuit_id:
                    continue
                appliance_key = f"circuit:{circuit_id}"
                item = items_by_key.get(appliance_key)
                if item is not None:
                    if item["status"] == "normal":
                        item["status"] = "load_shift_opportunity"
                    continue
                item = {
                    "appliance_key": appliance_key,
                    "display_name": str(candidate.get("name") or circuit_id),
                    "energy_kwh": 0.0,
                    "normal_energy_kwh": 0.0,
                    "confidence": 1.0,
                    "status": "load_shift_opportunity",
                    "comparable_energy": False,
                }
                items.append(item)
                items_by_key[appliance_key] = item
    assignments = getattr(store_data, "nilm_appliance_assignments_by_circuit", {})
    session_history = getattr(store_data, "nilm_session_history_by_circuit", {})
    if isinstance(assignments, Mapping):
        for circuit_id, circuit_assignments in assignments.items():
            sessions = (
                session_history.get(circuit_id, ())
                if isinstance(session_history, Mapping)
                else ()
            )
            for assignment in (
                circuit_assignments if isinstance(circuit_assignments, list) else ()
            ):
                if not isinstance(assignment, Mapping):
                    continue
                assignment_id = str(assignment.get("assignment_id") or "")
                if not assignment_id:
                    continue
                week_energy = sum(
                    _number(session.get("estimated_energy_kwh"))
                    for session in sessions
                    if isinstance(session, Mapping)
                    and str(session.get("assignment_id") or "") == assignment_id
                    and _date_between(
                        session.get("start"),
                        week_start,
                        week_end,
                        time_zone,
                    )
                )
                expected_daily = _number(
                    assignment.get("expected_daily_energy_kwh")
                )
                items.append(
                    {
                        "appliance_key": str(
                            assignment.get("appliance_key") or f"nilm:{assignment_id}"
                        ),
                        "display_name": str(
                            assignment.get("display_name") or assignment_id
                        ),
                        "energy_kwh": week_energy,
                        "normal_energy_kwh": expected_daily * 7.0,
                        "confidence": _number(assignment.get("confidence"), 0.0),
                        "status": "nilm_review_needed"
                        if str(assignment.get("lifecycle_state") or "")
                        not in {"validated", "confirmed"}
                        else "normal",
                    }
                )
    return items[:100]


def _digest_item(raw: Mapping[str, Any]) -> DigestItem | None:
    appliance_key = str(raw.get("appliance_key") or "").strip()
    if not appliance_key:
        return None
    energy = _number(raw.get("energy_kwh"))
    normal = _number(raw.get("normal_energy_kwh"))
    change = (energy - normal) / normal if normal > 0.0 else 0.0
    return DigestItem(
        appliance_key=appliance_key,
        display_name=str(raw.get("display_name") or appliance_key),
        energy_kwh=round(energy, 3),
        normal_energy_kwh=round(normal, 3),
        change_ratio=round(change, 3),
        confidence=min(max(_number(raw.get("confidence"), 1.0), 0.0), 1.0),
        status=str(raw.get("status") or "normal"),
    )


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _complete_daily_values_between(
    days: Any,
    start: date,
    end: date,
) -> dict[date, float]:
    values: dict[date, float] = {}
    for item in days if isinstance(days, list | tuple) else ():
        if not isinstance(item, Mapping):
            continue
        try:
            item_date = date.fromisoformat(str(item.get("date") or ""))
        except ValueError:
            continue
        if (
            start <= item_date <= end
            and item.get("complete") is True
            and item.get("baseline_eligible") is not False
        ):
            values[item_date] = _number(item.get("usage_kwh"))
    return values


def _date_between(
    value: Any,
    start: date,
    end: date,
    time_zone: tzinfo,
) -> bool:
    try:
        timestamp = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=time_zone)
    return start <= timestamp.astimezone(time_zone).date() <= end
