"""Regression coverage for typed NILM confidence compatibility."""

from __future__ import annotations

from copy import deepcopy

from custom_components.circuitsetup_energy_analyzer.nilm_confidence import (
    NILM_CONFIDENCE_SEMANTICS_VERSION,
    apply_nilm_feedback_evidence,
    migrate_nilm_confidence_semantics,
)


def test_migration_is_idempotent_and_preserves_typed_semantics() -> None:
    assignments = {
        "mains": [
            {
                "assignment_id": "legacy-load",
                "lifecycle_state": "published",
                "confidence": 0.83,
            }
        ]
    }
    signatures = {"mains": [{"signature_id": "legacy-signature", "confidence": 0.7}]}
    sessions = {
        "mains": [
            {
                "session_id": "legacy-session",
                "confidence": 0.62,
                "energy_estimate_confidence": 0.45,
            }
        ]
    }

    assert migrate_nilm_confidence_semantics(assignments, signatures, sessions) is True
    assignment = assignments["mains"][0]
    signature = signatures["mains"][0]
    session = sessions["mains"][0]
    assert assignment["lifecycle_state"] == "published"
    assert "confidence" not in assignment
    assert "confidence_kind" not in assignment
    assert "feedback_evidence_score" not in assignment
    assert signature["confidence_kind"] == "evidence_strength"
    assert signature["evidence_strength"] == 0.7
    assert session["confidence_kind"] == "pairing_confidence"
    assert session["pairing_confidence"] == 0.62
    assert session["energy_estimate_confidence"] == 0.45
    assert all(
        value["confidence_semantics_version"] == NILM_CONFIDENCE_SEMANTICS_VERSION
        for value in (assignment, signature, session)
    )

    migrated = deepcopy((assignments, signatures, sessions))
    assert migrate_nilm_confidence_semantics(assignments, signatures, sessions) is False
    assert (assignments, signatures, sessions) == migrated


def test_migration_does_not_keep_a_feedback_label_without_typed_evidence() -> None:
    assignments = {
        "mains": [
            {
                "assignment_id": "stale-feedback-label",
                "confidence": 0.83,
                "confidence_kind": "feedback_evidence",
            }
        ]
    }

    assert migrate_nilm_confidence_semantics(assignments, {}, {}) is True
    assert "confidence" not in assignments["mains"][0]
    assert "confidence_kind" not in assignments["mains"][0]


def test_migration_labels_existing_typed_feedback_evidence() -> None:
    assignments = {
        "mains": [
            {
                "assignment_id": "feedback-evidence",
                "confidence": 0.83,
                "feedback_evidence_score": 0.45,
            }
        ]
    }

    assert migrate_nilm_confidence_semantics(assignments, {}, {}) is True
    assert assignments["mains"][0]["confidence_kind"] == "feedback_evidence"
    assert "confidence" not in assignments["mains"][0]


def test_migration_removes_legacy_confidence_event_mirrors() -> None:
    assignments = {
        "mains": [
            {
                "assignment_id": "legacy-events",
                "confidence": 0.72,
                "confidence_kind": "legacy_mixed",
                "feedback_evidence_events": [
                    {
                        "feedback_id": "session:one",
                        "outcome": "correct",
                        "score_after": 0.05,
                        "legacy_confidence_after": 0.77,
                    }
                ],
            }
        ]
    }

    assert migrate_nilm_confidence_semantics(assignments, {}, {}) is True
    record = assignments["mains"][0]
    assert "confidence" not in record
    assert "confidence_kind" not in record
    assert record["feedback_evidence_events"] == [
        {
            "feedback_id": "session:one",
            "outcome": "correct",
            "delta": 0.05,
            "timestamp": "",
            "score_after": 0.05,
        }
    ]


def test_feedback_evidence_is_idempotent_and_auditable() -> None:
    assignment: dict[str, object] = {
        "confidence": 0.7,
        "lifecycle_state": "validated",
    }

    assert apply_nilm_feedback_evidence(
        assignment,
        feedback_id="session:one",
        correct=True,
        timestamp="2026-08-01T12:00:00+00:00",
    ) is True
    assert "confidence" not in assignment
    assert assignment["feedback_evidence_score"] == 0.05
    assert assignment["feedback_confirmed_count"] == 1
    assert assignment["feedback_rejected_count"] == 0
    assert apply_nilm_feedback_evidence(
        assignment,
        feedback_id="session:one",
        correct=True,
        timestamp="2026-08-01T12:00:00+00:00",
    ) is False
    assert "confidence" not in assignment
    assert assignment["feedback_evidence_events"] == [
        {
            "feedback_id": "session:one",
            "outcome": "correct",
            "delta": 0.05,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "score_after": 0.05,
        }
    ]

    assert apply_nilm_feedback_evidence(
        assignment,
        feedback_id="session:one",
        correct=False,
        timestamp="2026-08-01T12:01:00+00:00",
    ) is True
    assert "confidence" not in assignment
    assert assignment["feedback_evidence_score"] == 0.0
    assert assignment["feedback_confirmed_count"] == 0
    assert assignment["feedback_rejected_count"] == 1
    assert assignment["feedback_evidence_events"] == [
        {
            "feedback_id": "session:one",
            "outcome": "correct",
            "delta": 0.05,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "score_after": 0.05,
        },
        {
            "feedback_id": "session:one",
            "outcome": "wrong",
            "delta": -0.15,
            "timestamp": "2026-08-01T12:01:00+00:00",
            "score_after": 0.0,
        },
    ]


def test_feedback_idempotency_and_audit_survive_many_distinct_events() -> None:
    """A retained feedback decision must not become replayable after compaction."""
    assignment: dict[str, object] = {"confidence": 0.0}

    for index in range(65):
        assert apply_nilm_feedback_evidence(
            assignment,
            feedback_id=f"session:{index}",
            correct=True,
            timestamp=f"2026-08-01T12:{index:02d}:00+00:00",
        ) is True

    assert len(assignment["feedback_evidence_events"]) == 65
    assert assignment["feedback_confirmed_count"] == 65
    assert apply_nilm_feedback_evidence(
        assignment,
        feedback_id="session:0",
        correct=True,
        timestamp="2026-08-02T12:00:00+00:00",
    ) is False
    assert len(assignment["feedback_evidence_events"]) == 65
    assert assignment["feedback_confirmed_count"] == 65
