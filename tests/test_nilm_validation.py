"""Pure tests for NILM history-validation matching."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.circuitsetup_energy_analyzer.nilm_validation import (
    NilmValidationPolicy,
    match_nilm_validation_intervals,
)


def _timestamp(hour: int, minute: int = 0) -> str:
    return datetime(2026, 6, 2, hour, minute, tzinfo=UTC).isoformat()


def _session(
    session_id: str,
    start: str,
    end: str | None,
    **extra: object,
) -> dict[str, object]:
    return {"session_id": session_id, "start": start, "end": end, **extra}


def _interval(
    interval_id: str | None,
    start: str,
    end: str,
    **extra: object,
) -> dict[str, object]:
    data = {
        "ground_truth_entity_id": "sensor.dishwasher_power",
        "start": start,
        "end": end,
        **extra,
    }
    if interval_id is not None:
        data["interval_id"] = interval_id
    return data


def test_exact_prediction_and_truth_produce_perfect_temporal_match() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(12), _timestamp(12, 30))],
        [_interval("interval-1", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert len(result.matches) == 1
    match = result.matches[0]
    assert (match.session_id, match.interval_id) == ("session-1", "interval-1")
    assert match.iou == pytest.approx(1.0)
    assert match.start_error_seconds == 0
    assert match.end_error_seconds == 0
    assert result.false_positive_session_ids == ()
    assert result.false_negative_interval_ids == ()


def test_one_second_overlap_is_not_a_match() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(12, 29), _timestamp(13))],
        [
            _interval(
                "interval-1",
                _timestamp(12),
                _timestamp(12, 30),
                validation_start=_timestamp(12),
                validation_end=_timestamp(13),
            )
        ],
        circuit_id="mains",
    )

    assert result.matches == ()
    assert result.false_positive_session_ids == ("session-1",)
    assert result.false_negative_interval_ids == ("interval-1",)


def test_large_prediction_containing_short_truth_is_rejected() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(10), _timestamp(14))],
        [
            _interval(
                "interval-1",
                _timestamp(12),
                _timestamp(12, 15),
                validation_start=_timestamp(10),
                validation_end=_timestamp(14),
            )
        ],
        circuit_id="mains",
    )

    assert result.matches == ()
    assert result.false_positive_session_ids == ("session-1",)
    assert result.false_negative_interval_ids == ("interval-1",)


def test_small_prediction_coverage_of_truth_is_rejected() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(12), _timestamp(12, 10))],
        [_interval("interval-1", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert result.matches == ()
    assert result.false_positive_session_ids == ("session-1",)
    assert result.false_negative_interval_ids == ("interval-1",)


def test_two_predictions_can_claim_only_one_ground_truth_interval() -> None:
    result = match_nilm_validation_intervals(
        [
            _session("session-lower-score", _timestamp(12), _timestamp(12, 35)),
            _session("session-exact", _timestamp(12), _timestamp(12, 30)),
        ],
        [_interval("interval-1", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert [(match.session_id, match.interval_id) for match in result.matches] == [
        ("session-exact", "interval-1")
    ]
    assert result.false_positive_session_ids == ("session-lower-score",)


def test_one_prediction_can_claim_only_one_ground_truth_interval() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(12, 5), _timestamp(12, 30))],
        [
            _interval("interval-1", _timestamp(12), _timestamp(12, 30)),
            _interval("interval-2", _timestamp(12, 5), _timestamp(12, 35)),
        ],
        circuit_id="mains",
        policy=NilmValidationPolicy(
            min_iou=0.4,
            min_ground_truth_coverage=0.7,
            min_prediction_coverage=0.4,
        ),
    )

    assert len(result.matches) == 1
    assert result.false_negative_interval_ids == ("interval-2",)


def test_competing_pairs_use_maximum_total_score_not_local_greedy_choice() -> None:
    result = match_nilm_validation_intervals(
        [
            _session("session-1", _timestamp(12), _timestamp(12, 30)),
            _session("session-2", _timestamp(12, 30), _timestamp(13)),
        ],
        [
            _interval("interval-1", _timestamp(12), _timestamp(12, 25)),
            _interval("interval-2", _timestamp(12, 25), _timestamp(13)),
        ],
        circuit_id="mains",
        policy=NilmValidationPolicy(
            min_iou=0.1,
            min_ground_truth_coverage=0.5,
            min_prediction_coverage=0.1,
        ),
    )

    assert [(match.session_id, match.interval_id) for match in result.matches] == [
        ("session-1", "interval-1"),
        ("session-2", "interval-2"),
    ]


def test_prediction_outside_validation_coverage_is_unevaluated() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-outside", _timestamp(14), _timestamp(14, 30))],
        [
            _interval(
                "interval-1",
                _timestamp(12),
                _timestamp(12, 30),
                validation_start=_timestamp(12),
                validation_end=_timestamp(13),
            )
        ],
        circuit_id="mains",
    )

    assert result.false_positive_session_ids == ()
    assert result.unevaluated_session_ids == ("session-outside",)


def test_prediction_barely_touching_validation_coverage_is_unevaluated() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-edge", _timestamp(12, 59), _timestamp(13, 59))],
        [
            _interval(
                "interval-1",
                _timestamp(12),
                _timestamp(12, 30),
                validation_start=_timestamp(12),
                validation_end=_timestamp(13),
            )
        ],
        circuit_id="mains",
    )

    assert result.false_positive_session_ids == ()
    assert result.unevaluated_session_ids == ("session-edge",)


def test_no_predictions_marks_every_valid_interval_as_false_negative() -> None:
    result = match_nilm_validation_intervals(
        [],
        [
            _interval("interval-1", _timestamp(12), _timestamp(12, 30)),
            _interval("interval-2", _timestamp(13), _timestamp(13, 30)),
        ],
        circuit_id="mains",
    )

    assert result.matches == ()
    assert result.false_negative_interval_ids == ("interval-1", "interval-2")


def test_open_and_invalid_predictions_are_skipped() -> None:
    result = match_nilm_validation_intervals(
        [
            _session("session-open", _timestamp(12), None),
            _session("session-invalid", "not-a-time", _timestamp(12, 30)),
            _session("session-reversed", _timestamp(12, 30), _timestamp(12)),
        ],
        [_interval("interval-1", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert result.skipped_session_ids == (
        "session-invalid",
        "session-open",
        "session-reversed",
    )
    assert result.false_negative_interval_ids == ("interval-1",)


def test_endpoint_only_contact_has_zero_overlap() -> None:
    result = match_nilm_validation_intervals(
        [_session("session-1", _timestamp(12, 30), _timestamp(13))],
        [_interval("interval-1", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert result.matches == ()


def test_shuffled_inputs_produce_identical_result() -> None:
    sessions = [
        _session("session-2", _timestamp(13), _timestamp(13, 30)),
        _session("session-1", _timestamp(12), _timestamp(12, 30)),
    ]
    intervals = [
        _interval("interval-2", _timestamp(13), _timestamp(13, 30)),
        _interval("interval-1", _timestamp(12), _timestamp(12, 30)),
    ]

    first = match_nilm_validation_intervals(sessions, intervals, circuit_id="mains")
    second = match_nilm_validation_intervals(
        list(reversed(sessions)),
        list(reversed(intervals)),
        circuit_id="mains",
    )

    assert first == second


def test_equal_score_tie_uses_stable_pair_ids() -> None:
    result = match_nilm_validation_intervals(
        [
            _session("session-b", _timestamp(12), _timestamp(12, 30)),
            _session("session-a", _timestamp(12), _timestamp(12, 30)),
        ],
        [_interval("interval-a", _timestamp(12), _timestamp(12, 30))],
        circuit_id="mains",
    )

    assert result.matches[0].session_id == "session-a"
    assert result.false_positive_session_ids == ("session-b",)


def test_mixed_timezone_offsets_are_normalized_before_matching() -> None:
    result = match_nilm_validation_intervals(
        [
            _session(
                "session-1",
                "2026-06-02T08:00:00-04:00",
                "2026-06-02T08:30:00-04:00",
            )
        ],
        [
            _interval(
                "interval-1",
                "2026-06-02T12:00:00+00:00",
                "2026-06-02T12:30:00+00:00",
            )
        ],
        circuit_id="mains",
    )

    assert result.matches[0].iou == pytest.approx(1.0)


def test_legacy_interval_id_is_stable_and_durable() -> None:
    interval = _interval(None, _timestamp(12), _timestamp(12, 30))
    first = match_nilm_validation_intervals([], [interval], circuit_id="mains")
    second = match_nilm_validation_intervals([], [dict(interval)], circuit_id="mains")

    assert first.false_negative_interval_ids == second.false_negative_interval_ids
    assert first.false_negative_interval_ids[0].startswith("legacy:")
