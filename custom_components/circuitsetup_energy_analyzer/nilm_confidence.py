"""Compatibility helpers for typed NILM confidence fields.

The legacy ``confidence`` value remains persisted for existing consumers, but
is never treated as a generic correctness probability. Signatures use evidence
strength, sessions use pairing confidence, and assignments retain auditable
feedback evidence separately from their legacy compatibility value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from math import isfinite
from typing import Any

NILM_CONFIDENCE_SEMANTICS_VERSION = 1


def migrate_nilm_confidence_semantics(
    assignments_by_circuit: Mapping[str, Any],
    signatures_by_circuit: Mapping[str, Any],
    sessions_by_circuit: Mapping[str, Any],
) -> bool:
    """Add typed confidence aliases to persisted NILM records idempotently.

    This is called during feature-store loading, never from the per-sample
    processor.  It leaves lifecycle state and the legacy value unchanged.
    """
    changed = False
    for record in _records(assignments_by_circuit):
        changed |= _migrate_assignment(record)
    for record in _records(signatures_by_circuit):
        changed |= _migrate_signature(record)
    for record in _records(sessions_by_circuit):
        changed |= _migrate_session(record)
    return changed


def apply_nilm_feedback_evidence(
    assignment: MutableMapping[str, Any],
    *,
    feedback_id: str,
    correct: bool,
    timestamp: str,
) -> bool:
    """Apply one idempotent, auditable +0.05/-0.15 feedback observation.

    Replaying an unchanged feedback event is a no-op. A changed decision is
    retained as a later revision, so both the typed score and the legacy
    mirror can be reconstructed from the audit trail.
    """
    normalized_id = str(feedback_id or "").strip()
    if not normalized_id:
        raise ValueError("feedback_id is required")
    outcome = "correct" if correct else "wrong"
    delta = 0.05 if correct else -0.15
    normalized_timestamp = str(timestamp or "").strip()

    events = _feedback_events(assignment.get("feedback_evidence_events"))
    current_score = _feedback_evidence_score(assignment, events)
    legacy_score = _legacy_confidence_score(assignment, current_score)
    previous = next(
        (
            event
            for event in reversed(events)
            if event["feedback_id"] == normalized_id
        ),
        None,
    )
    if previous is not None:
        if previous["outcome"] == outcome:
            return False
    score = round(_clamp(current_score + delta), 3)
    legacy_score_after = round(_clamp(legacy_score + delta), 3)
    events.append(
        {
            "feedback_id": normalized_id,
            "outcome": outcome,
            "delta": delta,
            "timestamp": normalized_timestamp,
            "score_after": score,
            "legacy_confidence_after": legacy_score_after,
        }
    )
    current_outcomes = _latest_feedback_events(events)

    changed = False
    # ``confidence`` remains the legacy compatibility mirror and deliberately
    # follows its historical adjustment path. The typed score starts from
    # auditable feedback only; a legacy mixed value is never its provenance.
    changed |= _set_if_changed(
        assignment,
        "confidence",
        legacy_score_after,
    )
    changed |= _set_if_changed(assignment, "feedback_evidence_score", score)
    changed |= _set_if_changed(assignment, "feedback_evidence_events", events)
    changed |= _set_if_changed(
        assignment,
        "feedback_confirmed_count",
        sum(event["outcome"] == "correct" for event in current_outcomes.values()),
    )
    changed |= _set_if_changed(
        assignment,
        "feedback_rejected_count",
        sum(event["outcome"] == "wrong" for event in current_outcomes.values()),
    )
    changed |= _set_if_changed(assignment, "confidence_kind", "feedback_evidence")
    changed |= _set_if_changed(
        assignment,
        "confidence_semantics_version",
        NILM_CONFIDENCE_SEMANTICS_VERSION,
    )
    return changed


def _migrate_assignment(record: MutableMapping[str, Any]) -> bool:
    legacy_confidence = _number(record.get("confidence"))
    feedback_evidence_score = _number(record.get("feedback_evidence_score"))
    model_fit = _number(record.get("model_confidence"))
    if (
        legacy_confidence is None
        and model_fit is None
        and not any(
            key in record
            for key in (
                "feedback_evidence_score",
                "model_fit",
                "confidence_kind",
                "confidence_semantics_version",
            )
        )
    ):
        return False
    changed = _ensure_semantics_version(record)
    if feedback_evidence_score is not None:
        changed |= _set_if_changed(record, "confidence_kind", "feedback_evidence")
    elif (
        str(record.get("confidence_kind") or "").strip().lower()
        == "feedback_evidence"
    ):
        changed |= _set_if_changed(record, "confidence_kind", "legacy_mixed")
    else:
        changed |= _set_if_missing(record, "confidence_kind", "legacy_mixed")
    if model_fit is not None:
        changed |= _set_if_missing(record, "model_fit", round(_clamp(model_fit), 3))
    return changed


def _migrate_signature(record: MutableMapping[str, Any]) -> bool:
    evidence_strength = _number(record.get("evidence_strength"))
    if evidence_strength is None:
        evidence_strength = _number(record.get("confidence"))
    if (
        evidence_strength is None
        and not any(
            key in record
            for key in ("confidence_kind", "confidence_semantics_version")
        )
    ):
        return False
    changed = _ensure_semantics_version(record)
    if evidence_strength is not None:
        changed |= _set_if_changed(
            record,
            "evidence_strength",
            round(_clamp(evidence_strength), 3),
        )
    if evidence_strength is not None:
        changed |= _set_if_changed(record, "confidence_kind", "evidence_strength")
    else:
        changed |= _set_if_missing(record, "confidence_kind", "legacy_mixed")
    return changed


def _migrate_session(record: MutableMapping[str, Any]) -> bool:
    pairing_confidence = _number(record.get("pairing_confidence"))
    if pairing_confidence is None:
        pairing_confidence = _number(record.get("confidence"))
    if (
        pairing_confidence is None
        and not any(
            key in record
            for key in ("confidence_kind", "confidence_semantics_version")
        )
    ):
        return False
    changed = _ensure_semantics_version(record)
    if pairing_confidence is not None:
        changed |= _set_if_changed(
            record,
            "pairing_confidence",
            round(_clamp(pairing_confidence), 3),
        )
    if pairing_confidence is not None:
        changed |= _set_if_changed(record, "confidence_kind", "pairing_confidence")
    else:
        changed |= _set_if_missing(record, "confidence_kind", "legacy_mixed")
    return changed


def _records(
    records_by_circuit: Mapping[str, Any],
) -> Iterable[MutableMapping[str, Any]]:
    values = (
        records_by_circuit.values()
        if isinstance(records_by_circuit, Mapping)
        else ()
    )
    for records in values:
        if not isinstance(records, Iterable) or isinstance(
            records, (str, bytes, Mapping)
        ):
            continue
        for record in records:
            if isinstance(record, MutableMapping):
                yield record


def _ensure_semantics_version(record: MutableMapping[str, Any]) -> bool:
    current = _positive_int(record.get("confidence_semantics_version"))
    if current is not None and current >= NILM_CONFIDENCE_SEMANTICS_VERSION:
        return False
    return _set_if_changed(
        record,
        "confidence_semantics_version",
        NILM_CONFIDENCE_SEMANTICS_VERSION,
    )


def _feedback_evidence_score(
    assignment: Mapping[str, Any], events: Iterable[Mapping[str, Any]]
) -> float:
    value = _number(assignment.get("feedback_evidence_score"))
    if value is not None:
        return _clamp(value)
    score = 0.0
    for event in events:
        recorded_score = _number(event.get("score_after"))
        score = (
            _clamp(recorded_score)
            if recorded_score is not None
            else _clamp(score + float(event["delta"]))
        )
    return score


def _legacy_confidence_score(
    assignment: Mapping[str, Any], feedback_evidence_score: float
) -> float:
    value = _number(assignment.get("confidence"))
    return _clamp(value if value is not None else feedback_evidence_score)


def _latest_feedback_events(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {str(event["feedback_id"]): event for event in events}


def _feedback_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    events: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        feedback_id = str(item.get("feedback_id") or "").strip()
        outcome = str(item.get("outcome") or "").strip().lower()
        if feedback_id and outcome in {"correct", "wrong"}:
            event = {
                "feedback_id": feedback_id,
                "outcome": outcome,
                "delta": 0.05 if outcome == "correct" else -0.15,
                "timestamp": str(item.get("timestamp") or "").strip(),
            }
            score_after = _number(item.get("score_after"))
            if score_after is not None:
                event["score_after"] = round(_clamp(score_after), 3)
            legacy_confidence_after = _number(item.get("legacy_confidence_after"))
            if legacy_confidence_after is not None:
                event["legacy_confidence_after"] = round(
                    _clamp(legacy_confidence_after), 3
                )
            events.append(event)
    # Feedback is an operator action, not a per-sample path. Keep its source
    # decisions so an old feedback ID remains idempotent and the current
    # evidence counts remain replayable; a truncated audit would make an
    # evicted decision apply its +0.05/-0.15 adjustment again.
    return events


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _set_if_changed(record: MutableMapping[str, Any], key: str, value: Any) -> bool:
    if key in record and record[key] == value:
        return False
    record[key] = value
    return True


def _set_if_missing(record: MutableMapping[str, Any], key: str, value: Any) -> bool:
    if key in record:
        return False
    record[key] = value
    return True
