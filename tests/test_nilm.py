from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import combinations as stdlib_combinations
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer import nilm as nilm_domain
from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
    CircuitSample,
    EventType,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmEdge,
    NilmEdgeDetector,
    NilmHelperCandidate,
    NilmSignature,
    attribute_known_loads,
    build_nilm_assignment_model,
    classify_signature,
    cluster_recurring_signatures,
    discover_nilm_helper_candidates,
    mask_known_loads,
    nilm_assignment_model_is_compound_eligible,
    nilm_helper_candidate_to_dict,
    pair_nilm_sessions_for_signatures,
    score_nilm_helper_candidate,
    unmatched_load_percentage,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
    _nilm_session_specs,
)

BASE_TIME = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
_DEFAULT_DELTA_VA = object()


def test_assignment_model_uses_interval_plateau_for_running_state() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["one"]},
        [],
        label_intervals=[
            {
                "interval_id": "one",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": True,
                "start_transition_w": 70.0,
                "stop_transition_eligible": True,
                "stop_transition_w": -70.0,
                "plateau_eligible": True,
                "median_power_w": 100.0,
                "power_coverage": 1.0,
                "evidence_confidence": 0.9,
            }
        ],
    )
    assert model["states"][1]["power_w"] == 100.0
    assert model["transition_prototypes"][0]["delta_w"] == 70.0


def test_assignment_model_builds_energy_profile_without_using_energy_as_edge() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["one"]},
        [],
        label_intervals=[
            {
                "interval_id": "one",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": True,
                "start_transition_w": 80.0,
                "plateau_eligible": True,
                "median_power_w": 90.0,
                "measured_energy_kwh": 0.15,
                "duration_s": 600,
                "power_coverage": 1.0,
                "evidence_confidence": 0.9,
            }
        ],
    )
    assert model["run_profile"]["energy_kwh"]["median"] == 0.15
    assert model["transition_prototypes"][0]["delta_w"] == 80.0


def test_assignment_model_profiles_measured_and_estimated_session_energy() -> None:
    """Estimated complete-run energy is retained but measured energy is favored."""
    model = build_nilm_assignment_model(
        {
            "assignment_id": "pump",
            "confirmed_session_ids": ["estimated", "measured"],
        },
        [
            {
                "session_id": "estimated",
                "assignment_id": "pump",
                "start": "2026-06-01T10:00:00+00:00",
                "end": "2026-06-01T10:10:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "estimated_energy_kwh": 0.8,
                "confidence": 1.0,
            },
            {
                "session_id": "measured",
                "assignment_id": "pump",
                "start": "2026-06-02T10:00:00+00:00",
                "end": "2026-06-02T10:10:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "measured_energy_kwh": 0.2,
                "estimated_energy_kwh": 9.0,
                "confidence": 0.6,
            },
        ],
    )

    energy = model["run_profile"]["energy_kwh"]
    assert energy["sample_count"] == 2
    assert energy["measured_count"] == 1
    assert energy["estimated_count"] == 1
    assert energy["source"] == "mixed"
    assert energy["median"] == 0.2


def test_assignment_model_flags_power_energy_disagreement_without_broadening_state(  # noqa: E501
) -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["one", "two"]},
        [],
        label_intervals=[
            {
                "interval_id": "one",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "plateau_eligible": True,
                "median_power_w": 100.0,
                "measured_energy_kwh": 0.5,
                "duration_s": 600,
                "power_coverage": 1.0,
                "evidence_confidence": 1.0,
            },
            {
                "interval_id": "two",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "plateau_eligible": True,
                "median_power_w": 100.0,
                "power_coverage": 1.0,
                "evidence_confidence": 1.0,
            },
        ],
    )
    assert model["states"][1]["power_w"] == 100.0
    assert "power_energy_disagreement" in model["evidence_summary"]["quality_issues"]


def test_assignment_model_keeps_asymmetric_directional_prototypes() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["one"]},
        [
            {
                "session_id": "one",
                "assignment_id": "pump",
                "start": "2026-06-01T10:00:00+00:00",
                "end": "2026-06-01T10:05:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -65.0,
                "confidence": 1.0,
            }
        ],
    )
    assert [prototype["delta_w"] for prototype in model["transition_prototypes"]] == [
        80.0,
        -65.0,
    ]


def test_assignment_model_marks_legacy_stop_inferred_and_lower_effective_support() -> (
    None
):
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["one"]},
        [],
        label_intervals=[
            {
                "interval_id": "one",
                "assignment_id": "pump",
                "observed_transition_w": 80.0,
                "confidence": 1.0,
            }
        ],
    )
    on, off = model["transition_prototypes"]
    assert on["evidence_kind"] == "observed"
    assert off["evidence_kind"] == "inferred_legacy_stop"
    assert off["effective_support"] < on["effective_support"]


def test_assignment_model_selects_distinct_days_over_recent_same_day_burst() -> None:
    ids = ["old"] + [f"new-{index}" for index in range(40)]
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ids},
        [
            {
                "session_id": "old",
                "assignment_id": "pump",
                "end": "2026-06-01T10:00:00+00:00",
                "on_delta_w": 50.0,
                "off_delta_w": -50.0,
                "confidence": 1.0,
            }
        ]
        + [
            {
                "session_id": f"new-{index}",
                "assignment_id": "pump",
                "end": f"2026-07-02T10:{index:02d}:00+00:00",
                "on_delta_w": 100.0,
                "off_delta_w": -100.0,
                "confidence": 0.8,
            }
            for index in range(40)
        ],
    )
    assert model["transition_prototypes"][0]["delta_w"] == 100.0
    assert model["evidence_summary"]["positive_distinct_days"] == 2


def test_assignment_model_confidence_uses_support_days_and_dispersion() -> None:
    def build(values: list[float]) -> dict[str, object]:
        return build_nilm_assignment_model(
            {
                "assignment_id": "pump",
                "confirmed_session_ids": [str(index) for index in range(len(values))],
            },
            [
                {
                    "session_id": str(index),
                    "assignment_id": "pump",
                    "end": f"2026-06-{index + 1:02d}T10:00:00+00:00",
                    "on_delta_w": value,
                    "off_delta_w": -value,
                    "confidence": 1.0,
                }
                for index, value in enumerate(values)
            ],
        )

    assert (
        build([80.0] * 5)["evidence_confidence"]
        > build([80.0] * 3)["evidence_confidence"]
    )
    assert (
        build([40.0, 80.0, 120.0, 160.0, 200.0])["evidence_confidence"]
        < build([80.0] * 5)["evidence_confidence"]
    )


def test_assignment_model_rejected_evidence_does_not_shift_positive_or_adds_conflict(  # noqa: E501
) -> None:
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["good"],
        "rejected_session_ids": ["bad"],
    }
    sessions = [
        {
            "session_id": "good",
            "assignment_id": "pump",
            "end": "2026-06-01T10:00:00+00:00",
            "on_delta_w": 80.0,
            "off_delta_w": -80.0,
            "confidence": 1.0,
        },
        {
            "session_id": "bad",
            "assignment_id": "pump",
            "end": "2026-06-02T10:00:00+00:00",
            "on_delta_w": 82.0,
            "off_delta_w": -82.0,
            "confidence": 1.0,
        },
    ]
    model = build_nilm_assignment_model(assignment, sessions)
    assert model["transition_prototypes"][0]["delta_w"] == 80.0
    assert model["evidence_summary"]["close_rejected_conflicts"] == 1


def test_assignment_model_rejecting_final_positive_updates_empty_model() -> None:
    """Removing the last positive still canonicalizes negative-only model content."""
    sessions = [
        {
            "session_id": "only",
            "assignment_id": "pump",
            "end": "2026-06-01T10:00:00+00:00",
            "on_delta_w": 80.0,
            "off_delta_w": -80.0,
            "confidence": 1.0,
        }
    ]
    first = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["only"]}, sessions
    )
    second = build_nilm_assignment_model(
        {
            "assignment_id": "pump",
            "confirmed_session_ids": [],
            "rejected_session_ids": ["only"],
            **first,
        },
        sessions,
    )

    assert second["power_states_w"] == []
    assert second["evidence_summary"]["negative_count"] == 1
    assert second["evidence_summary"]["close_rejected_conflicts"] == 0
    assert second["model_fingerprint"]
    assert second["model_fingerprint"] != first["model_fingerprint"]
    assert second["model_revision"] == first["model_revision"] + 1


def test_assignment_model_uses_transition_fallback_without_steady_state() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["one"]},
        [
            {
                "session_id": "one",
                "assignment_id": "pump",
                "end": "2026-06-01T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -70.0,
                "confidence": 1.0,
            }
        ],
    )
    assert model["states"][1]["power_source"] == "transition_fallback"
    assert model["states"][1]["power_w"] == 80.0


def test_assignment_model_transition_only_evidence_is_not_compound_eligible() -> None:
    session_ids = [str(index) for index in range(8)]
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": session_ids},
        [
            {
                "session_id": session_id,
                "assignment_id": "pump",
                "end": f"2026-06-{index + 1:02d}T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "confidence": 1.0,
            }
            for index, session_id in enumerate(session_ids)
        ],
    )

    assert model["evidence_summary"]["state_support"] == 0.0
    assert model["model_confidence"] < 0.7
    assert nilm_assignment_model_is_compound_eligible(model) is False


def test_assignment_model_marks_session_power_as_edge_derived_plateau() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["one"]},
        [
            {
                "session_id": "one",
                "assignment_id": "pump",
                "end": "2026-06-01T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "median_power_w": 80.0,
                "confidence": 1.0,
            }
        ],
    )

    assert model["states"][1]["power_source"] == "edge_derived_plateau"
    assert model["run_profile"]["plateau_w"]["source_counts"] == {
        "edge_derived": 1
    }


def test_assignment_model_invalid_optional_values_do_not_consume_selection_capacity(  # noqa: E501
) -> None:
    intervals = [
        {
            "interval_id": f"bad-{index}",
            "assignment_id": "pump",
            "evidence_schema_version": 2,
            "plateau_eligible": True,
            "median_power_w": float("nan"),
            "power_coverage": 1.0,
        }
        for index in range(100)
    ] + [
        {
            "interval_id": "good",
            "assignment_id": "pump",
            "evidence_schema_version": 2,
            "plateau_eligible": True,
            "median_power_w": 90.0,
            "power_coverage": 1.0,
            "evidence_confidence": 1.0,
        }
    ]
    model = build_nilm_assignment_model(
        {
            "assignment_id": "pump",
            "label_interval_ids": [item["interval_id"] for item in intervals],
        },
        [],
        label_intervals=intervals,
    )
    assert model["states"][1]["power_w"] == 90.0


def test_normalize_assignment_model_v1_is_stable_binary_v2_projection() -> None:
    assignment = {
        "power_states_w": [0.0, 80.0],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0.0,
                "to_state_w": 80.0,
                "delta_w": 80.0,
                "spread_w": 1.0,
                "sample_count": 3,
            }
        ],
        "model_confidence": 0.8,
    }
    normalized = nilm_domain.normalize_nilm_assignment_model(assignment)
    rebuilt = build_nilm_assignment_model(
        {**assignment, **normalized, "assignment_id": "pump"}, []
    )
    assert normalized["model_schema_version"] == 2
    assert normalized["model_kind"] == "binary"
    assert normalized["states"][1]["id"] == "running"
    assert rebuilt["model_revision"] == normalized["model_revision"]


def test_assignment_model_caps_source_before_daily_representatives() -> None:
    ids = [str(index) for index in range(70)]
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ids},
        [
            {
                "session_id": value,
                "assignment_id": "pump",
                "end": f"2026-05-{index + 1:02d}T00:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "confidence": 1.0,
            }
            for index, value in enumerate(ids)
        ],
    )
    assert model["transition_prototypes"][0]["sample_count"] == 64


def test_assignment_model_keeps_legacy_on_when_modern_stop_exists() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["old", "new"]},
        [],
        label_intervals=[
            {
                "interval_id": "old",
                "assignment_id": "pump",
                "observed_transition_w": 80.0,
                "confidence": 1.0,
            },
            {
                "interval_id": "new",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "stop_transition_eligible": True,
                "stop_transition_w": -70.0,
                "power_coverage": 1.0,
                "evidence_confidence": 1.0,
            },
        ],
    )
    assert [item["delta_w"] for item in model["transition_prototypes"]] == [80.0, -70.0]
    assert model["transition_prototypes"][1]["evidence_kind"] == "observed"
    assert model["evidence_summary"]["inferred_stop_count"] == 0


def test_assignment_model_keeps_inferred_legacy_stop_without_observed_stop() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["legacy", "modern"]},
        [],
        label_intervals=[
            {
                "interval_id": "legacy",
                "assignment_id": "pump",
                "observed_transition_w": 80.0,
                "confidence": 1.0,
            },
            {
                "interval_id": "modern",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": True,
                "start_transition_w": 90.0,
                "power_coverage": 1.0,
                "evidence_confidence": 1.0,
            },
        ],
    )

    assert [item["direction"] for item in model["transition_prototypes"]] == [
        "on",
        "off",
    ]
    assert model["transition_prototypes"][0]["delta_w"] == 90.0
    assert model["transition_prototypes"][1]["delta_w"] == -80.0
    assert (
        model["transition_prototypes"][1]["evidence_kind"]
        == "inferred_legacy_stop"
    )
    assert model["evidence_summary"]["inferred_stop_count"] == 1


def test_assignment_model_profiles_duration_and_energy_without_state_evidence() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["one"]},
        [],
        label_intervals=[
            {
                "interval_id": "one",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "duration_s": 600,
                "measured_energy_kwh": 0.15,
                "power_coverage": 1.0,
                "evidence_confidence": 1.0,
            }
        ],
    )
    assert model["power_states_w"] != [0.0, 0.0]
    assert model["run_profile"]["duration_s"]["median"] == 600.0
    assert model["run_profile"]["energy_kwh"]["median"] == 0.15


def test_assignment_model_emits_complete_weighted_profile_contract() -> None:
    intervals = [
        {
            "interval_id": "high-a",
            "assignment_id": "pump",
            "start": "2026-06-01T10:00:00+00:00",
            "duration_s": 100.0,
            "evidence_schema_version": 2,
            "start_transition_eligible": True,
            "start_transition_w": 100.0,
            "stop_transition_eligible": True,
            "stop_transition_w": -100.0,
            "plateau_eligible": True,
            "median_power_w": 100.0,
            "measured_energy_kwh": 0.0028,
            "power_coverage": 1.0,
            "evidence_confidence": 1.0,
        },
        {
            "interval_id": "high-b",
            "assignment_id": "pump",
            "start": "2026-06-02T10:00:00+00:00",
            "duration_s": 110.0,
            "evidence_schema_version": 2,
            "start_transition_eligible": True,
            "start_transition_w": 110.0,
            "stop_transition_eligible": True,
            "stop_transition_w": -110.0,
            "plateau_eligible": True,
            "median_power_w": 110.0,
            "measured_energy_kwh": 0.0034,
            "power_coverage": 1.0,
            "evidence_confidence": 1.0,
        },
        {
            "interval_id": "legacy-low-weight",
            "assignment_id": "pump",
            "start": "2026-06-03T10:00:00+00:00",
            "duration_s": 10_000.0,
            "observed_transition_w": 500.0,
            "measured_energy_kwh": 9.0,
            "confidence": 1.0,
        },
    ]
    model = build_nilm_assignment_model(
        {
            "assignment_id": "pump",
            "label_interval_ids": [item["interval_id"] for item in intervals],
        },
        [],
        label_intervals=intervals,
    )

    duration = model["run_profile"]["duration_s"]
    assert duration["sample_count"] == 3
    assert duration["distinct_days"] == 3
    assert duration["median_seconds"] == 110.0
    assert duration["p10_seconds"] == 100.0
    assert duration["p90_seconds"] == 110.0
    assert duration["median_log_seconds"] == pytest.approx(4.7, abs=0.001)
    assert duration["mad_log_seconds"] == pytest.approx(0.095, abs=0.001)
    assert duration["median"] == duration["median_seconds"]
    assert duration["p90"] == duration["p90_seconds"]

    energy = model["run_profile"]["energy_kwh"]
    assert energy["sample_count"] == 3
    assert energy["distinct_days"] == 3
    assert energy["weighted_median_kwh"] == 0.0034
    assert energy["weighted_mad_kwh"] == 0.0006
    assert energy["weighted_p10_kwh"] == 0.0028
    assert energy["weighted_p90_kwh"] == 0.0034
    assert energy["measured_count"] == 3
    assert energy["estimated_count"] == 0

    assert model["evidence_summary"]["source_counts"] == {
        "interval": 2,
        "legacy_interval": 1,
    }
    assert model["evidence_summary"]["inferred_stop_count"] == 0


def test_assignment_model_off_dispersion_reduces_confidence() -> None:
    def build(off: list[float]) -> dict[str, object]:
        return build_nilm_assignment_model(
            {
                "assignment_id": "pump",
                "confirmed_session_ids": [str(i) for i in range(4)],
            },
            [
                {
                    "session_id": str(i),
                    "assignment_id": "pump",
                    "end": f"2026-06-{i + 1:02d}T00:00:00+00:00",
                    "on_delta_w": 80.0,
                    "off_delta_w": value,
                    "confidence": 1.0,
                }
                for i, value in enumerate(off)
            ],
        )

    assert (
        build([-80.0, -80.0, -80.0, -160.0])["evidence_confidence"]
        < build([-80.0] * 4)["evidence_confidence"]
    )


def test_normalize_assignment_model_preserves_valid_v2_nested_fields() -> None:
    normalized = nilm_domain.normalize_nilm_assignment_model(
        {
            "model_kind": "binary",
            "power_states_w": [0, 80],
            "states": [
                {"id": "off", "kind": "off", "power_w": 0},
                {"id": "running", "kind": "running", "power_w": 80, "spread_w": 2},
            ],
            "run_profile": {
                "duration_s": {"median": 600, "mad": 20, "p10": 570, "p90": 640}
            },
            "evidence_summary": {"positive_count": 4, "quality_issues": ["x", 4]},
        }
    )
    assert normalized["states"][1]["spread_w"] == 2.0
    assert normalized["run_profile"]["duration_s"]["median"] == 600.0
    assert normalized["evidence_summary"]["quality_issues"] == ["x"]


def test_assignment_model_fingerprint_tracks_reactive_and_confidence_fields() -> None:
    base = {
        "power_states_w": [0, 80],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0,
                "to_state_w": 80,
                "delta_w": 80,
                "spread_w": 1,
                "delta_var": 10,
                "spread_var": 1,
                "sample_count": 3,
            }
        ],
        "model_confidence": 0.7,
    }
    changed = {
        **base,
        "transition_prototypes": [
            {**base["transition_prototypes"][0], "delta_var": 20}
        ],
    }
    assert (
        nilm_domain.normalize_nilm_assignment_model(base)["model_fingerprint"]
        != nilm_domain.normalize_nilm_assignment_model(changed)["model_fingerprint"]
    )


def test_normalize_assignment_model_orders_prototypes_and_backfills_power_states() -> (
    None
):
    prototypes = [
        {
            "direction": "off",
            "from_state_w": 80,
            "to_state_w": 0,
            "delta_w": -80,
            "spread_w": 1,
            "sample_count": 3,
        },
        {
            "direction": "on",
            "from_state_w": 0,
            "to_state_w": 80,
            "delta_w": 80,
            "spread_w": 1,
            "sample_count": 3,
        },
    ]
    first = nilm_domain.normalize_nilm_assignment_model(
        {
            "states": [{"id": "running", "power_w": 80}, {"id": "off", "power_w": 0}],
            "transition_prototypes": prototypes,
        }
    )
    second = nilm_domain.normalize_nilm_assignment_model(
        {
            "states": [{"id": "off", "power_w": 0}, {"id": "running", "power_w": 80}],
            "transition_prototypes": list(reversed(prototypes)),
        }
    )
    assert first["power_states_w"] == [0.0, 80.0]
    assert first == second


def test_assignment_model_uses_midpoint_for_two_equal_weight_transitions() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["a", "b"]},
        [
            {
                "session_id": "a",
                "assignment_id": "pump",
                "end": "2026-06-01T00:00:00+00:00",
                "on_delta_w": 100.0,
                "off_delta_w": -100.0,
                "confidence": 0.9,
            },
            {
                "session_id": "b",
                "assignment_id": "pump",
                "end": "2026-06-02T00:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "confidence": 0.9,
            },
        ],
    )
    assert model["power_states_w"] == [0.0, 90.0]


def test_assignment_model_uses_recent_confirmed_complete_sessions() -> None:
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": [f"session-{index}" for index in range(35)],
    }
    sessions = [
        {
            "session_id": f"session-{index}",
            "assignment_id": "pump",
            "start": f"2026-06-{index + 1:02d}T10:00:00+00:00",
            "end": f"2026-06-{index + 1:02d}T10:05:00+00:00",
            "on_delta_w": 10.0 if index < 3 else 80.0 + index % 3,
            "off_delta_w": -10.0 if index < 3 else -82.0 + index % 3,
            "confidence": 0.9,
            "ambiguous": False,
        }
        for index in range(35)
    ]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["role"] == "component"
    assert model["power_states_w"] == [0.0, 81.0]
    assert [item["direction"] for item in model["transition_prototypes"]] == [
        "on",
        "off",
    ]
    assert model["transition_prototypes"][0]["sample_count"] == 35
    assert model["transition_prototypes"][0]["spread_w"] == 1.0
    assert 0.0 < model["model_confidence"] < 1.0
    assert nilm_assignment_model_is_compound_eligible(model) is False


def test_assignment_model_falls_back_to_one_legacy_manual_label_interval() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "observed_transition_w": 84.0,
                "confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == [0.0, 84.0]
    assert [item["delta_w"] for item in model["transition_prototypes"]] == [
        84.0,
        -84.0,
    ]
    assert model["transition_prototypes"][0]["sample_count"] == 1
    assert "delta_var" not in model["transition_prototypes"][0]
    assert model["model_confidence"] <= 0.25


def test_assignment_model_reviewed_session_transitions_outrank_legacy_intervals() -> (
    None
):
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["session-1"],
        "label_interval_ids": ["interval-1", "interval-2"],
    }
    sessions = [
        {
            "session_id": "session-1",
            "assignment_id": "pump",
            "end": "2026-06-01T10:00:00+00:00",
            "on_delta_w": 60.0,
            "off_delta_w": -60.0,
            "confidence": 0.9,
        }
    ]
    intervals = [
        {
            "interval_id": "interval-1",
            "assignment_id": "pump",
            "end": "2026-06-02T10:00:00+00:00",
            "observed_transition_w": 90.0,
            "confidence": 0.8,
        },
        {
            "interval_id": "interval-2",
            "assignment_id": "pump",
            "end": "2026-06-03T10:00:00+00:00",
            "observed_transition_w": 120.0,
            "confidence": 1.0,
        },
    ]

    sessions_only = build_nilm_assignment_model(assignment, sessions)
    combined = build_nilm_assignment_model(
        assignment, sessions, label_intervals=intervals
    )

    assert sessions_only["power_states_w"] == [0.0, 60.0]
    assert combined["power_states_w"] == [0.0, 60.0]
    assert combined["transition_prototypes"][0]["sample_count"] == 1
    assert 0.0 < combined["model_confidence"] < 1.0


def test_assignment_model_schema_2_start_only_adds_only_an_on_prototype() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": True,
                "start_transition_w": 120.0,
                "stop_transition_eligible": False,
                "stop_transition_w": -120.0,
                "plateau_eligible": False,
                "power_coverage": 0.5,
                "evidence_confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == [0.0, 120.0]
    assert [item["direction"] for item in model["transition_prototypes"]] == ["on"]
    assert model["transition_prototypes"][0]["delta_w"] == 120.0
    assert 0.0 < model["model_confidence"] < 1.0


def test_assignment_model_schema_2_stop_only_adds_only_an_off_prototype() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": False,
                "start_transition_w": 140.0,
                "stop_transition_eligible": True,
                "stop_transition_w": -140.0,
                "plateau_eligible": False,
                "power_coverage": 1.0,
                "evidence_confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == [0.0, 140.0]
    assert [item["direction"] for item in model["transition_prototypes"]] == ["off"]
    assert model["transition_prototypes"][0]["delta_w"] == -140.0


def test_assignment_model_schema_2_ineligible_boundaries_add_no_transitions() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "observed_transition_w": 110.0,
                "start_transition_eligible": False,
                "start_transition_w": 110.0,
                "stop_transition_eligible": False,
                "stop_transition_w": -110.0,
                "plateau_eligible": False,
                "power_coverage": 1.0,
                "evidence_confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == []
    assert model["transition_prototypes"] == []


def test_assignment_model_schema_2_eligible_plateau_adds_active_state_power() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": False,
                "stop_transition_eligible": False,
                "plateau_eligible": True,
                "median_power_w": 95.0,
                "average_power_w": 92.0,
                "power_coverage": 0.95,
                "power_confidence": 0.8,
            }
        ],
    )

    assert model["power_states_w"] == [0.0, 95.0]
    assert model["transition_prototypes"] == []
    assert 0.0 < model["model_confidence"] < 1.0


def test_assignment_model_schema_2_low_coverage_plateau_is_not_active_evidence() -> (
    None
):
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["interval-1"]},
        [],
        label_intervals=[
            {
                "interval_id": "interval-1",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "observed_transition_w": 95.0,
                "start_transition_eligible": False,
                "stop_transition_eligible": False,
                "plateau_eligible": True,
                "median_power_w": 95.0,
                "partial_energy_kwh": 0.08,
                "measured_energy_kwh": None,
                "power_coverage": 0.5,
                "power_confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == []
    assert model["transition_prototypes"] == []


def test_assignment_model_schema_2_transitions_outrank_matching_legacy_direction() -> (
    None
):
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["legacy", "schema-2"]},
        [],
        label_intervals=[
            {
                "interval_id": "legacy",
                "assignment_id": "pump",
                "observed_transition_w": 75.0,
                "confidence": 1.0,
            },
            {
                "interval_id": "schema-2",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": True,
                "start_transition_w": 120.0,
                "stop_transition_eligible": False,
                "plateau_eligible": False,
                "power_coverage": 1.0,
                "evidence_confidence": 0.9,
            },
        ],
    )

    assert [item["delta_w"] for item in model["transition_prototypes"]] == [
        120.0,
        -75.0,
    ]
    assert model["transition_prototypes"][1]["evidence_kind"] == (
        "inferred_legacy_stop"
    )
    assert model["power_states_w"] == [0.0, 120.0]


def test_assignment_model_uses_legacy_transitions_when_schema_2_has_only_plateau() -> (
    None
):
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "label_interval_ids": ["legacy", "schema-2"]},
        [],
        label_intervals=[
            {
                "interval_id": "legacy",
                "assignment_id": "pump",
                "observed_transition_w": 80.0,
                "confidence": 0.9,
            },
            {
                "interval_id": "schema-2",
                "assignment_id": "pump",
                "evidence_schema_version": 2,
                "start_transition_eligible": False,
                "stop_transition_eligible": False,
                "plateau_eligible": True,
                "median_power_w": 95.0,
                "power_coverage": 0.95,
                "power_confidence": 0.8,
            },
        ],
    )

    assert model["power_states_w"] == [0.0, 95.0]
    assert [item["delta_w"] for item in model["transition_prototypes"]] == [
        80.0,
        -80.0,
    ]


def test_assignment_model_keeps_reviewed_session_transition_behavior() -> None:
    model = build_nilm_assignment_model(
        {"assignment_id": "pump", "confirmed_session_ids": ["session-1"]},
        [
            {
                "session_id": "session-1",
                "assignment_id": "pump",
                "end": "2026-06-01T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "confidence": 0.9,
            }
        ],
    )

    assert model["power_states_w"] == [0.0, 80.0]
    assert [item["delta_w"] for item in model["transition_prototypes"]] == [
        80.0,
        -80.0,
    ]
    assert 0.0 < model["model_confidence"] < 1.0


def test_assignment_model_caps_confidence_for_multiple_legacy_intervals() -> None:
    model = build_nilm_assignment_model(
        {
            "assignment_id": "pump",
            "label_interval_ids": ["legacy-1", "legacy-2", "legacy-3"],
        },
        [],
        label_intervals=[
            {
                "interval_id": interval_id,
                "assignment_id": "pump",
                "observed_transition_w": 84.0,
                "confidence": 1.0,
            }
            for interval_id in ("legacy-1", "legacy-2", "legacy-3")
        ],
    )

    assert model["transition_prototypes"][0]["sample_count"] == 3
    assert model["model_confidence"] <= 0.25


def test_assignment_model_retains_reviewed_session_var_prototypes() -> None:
    assignment = {
        "assignment_id": "blower",
        "confirmed_session_ids": ["one", "two", "three"],
    }
    sessions = [
        {
            "session_id": session_id,
            "assignment_id": "blower",
            "end": f"2026-06-0{index}T10:00:00+00:00",
            "on_delta_w": 320.0,
            "off_delta_w": -320.0,
            "on_delta_var": on_var,
            "off_delta_var": -on_var,
            "confidence": 0.9,
        }
        for index, (session_id, on_var) in enumerate(
            (("one", 118.0), ("two", 120.0), ("three", 122.0)),
            start=1,
        )
    ]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["transition_prototypes"][0]["delta_var"] == 120.0
    assert model["transition_prototypes"][0]["spread_var"] == 2.0
    assert model["transition_prototypes"][1]["delta_var"] == -120.0


def test_assignment_model_falls_back_to_legacy_power_and_stable_revision() -> None:
    assignment = {"assignment_id": "pump", "confirmed_session_ids": ["one"]}
    sessions = [
        {
            "session_id": "one",
            "assignment_id": "pump",
            "start": "2026-06-01T10:00:00+00:00",
            "end": "2026-06-01T10:05:00+00:00",
            "median_power_w": 83.0,
            "confidence": 0.8,
        }
    ]

    first = build_nilm_assignment_model(assignment, sessions)
    second = build_nilm_assignment_model({**assignment, **first}, sessions)

    assert first["power_states_w"] == [0.0, 83.0]
    assert first["transition_prototypes"][1]["delta_w"] == -83.0
    assert 0.0 < first["model_confidence"] < 1.0
    assert nilm_assignment_model_is_compound_eligible(first) is False
    assert first["model_revision"] == second["model_revision"] == 1


def test_assignment_model_discards_invalid_before_recent_cap() -> None:
    ids = [f"bad-{index}" for index in range(35)] + ["good"]
    assignment = {"assignment_id": "pump", "confirmed_session_ids": ids}
    sessions = [
        {
            "session_id": value,
            "assignment_id": "pump",
            "end": "2026-07-01T10:00:00+00:00",
            "confidence": 1.0,
        }
        for value in ids[:-1]
    ] + [
        {
            "session_id": "good",
            "assignment_id": "pump",
            "end": "2026-06-01T10:00:00+00:00",
            "on_delta_w": 80.0,
            "off_delta_w": -80.0,
            "confidence": 0.9,
        }
    ]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["transition_prototypes"][0]["sample_count"] == 1
    assert 0.0 < model["model_confidence"] < 1.0


def test_assignment_model_tolerates_malformed_optional_fields() -> None:
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["one"],
        "model_revision": 10**10_000,
        "model_confidence": float("nan"),
        "transition_prototypes": [{"direction": "on", "sample_count": "bad"}],
    }
    model = build_nilm_assignment_model(
        assignment,
        [
            {
                "session_id": "one",
                "assignment_id": "pump",
                "end": "2026-06-01T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                "confidence": float("nan"),
            }
        ],
    )

    assert model["model_revision"] == 1
    assert model["model_confidence"] == 0.0
    assert nilm_assignment_model_is_compound_eligible(assignment) is False


def test_assignment_model_requires_directional_evidence_and_conservative_confidence(  # noqa: E501
) -> None:
    session_ids = ["wrong-on", "wrong-off", "valid-a", "valid-b", "valid-c"]
    assignment = {"assignment_id": "pump", "confirmed_session_ids": session_ids}
    sessions = [
        {
            "session_id": "wrong-on",
            "assignment_id": "pump",
            "end": "2026-07-02T10:00:00+00:00",
            "on_delta_w": -80.0,
            "off_delta_w": -80.0,
            "confidence": 1.0,
        },
        {
            "session_id": "wrong-off",
            "assignment_id": "pump",
            "end": "2026-07-01T10:00:00+00:00",
            "on_delta_w": 80.0,
            "off_delta_w": 80.0,
            "confidence": 1.0,
        },
        *[
            {
                "session_id": f"valid-{suffix}",
                "assignment_id": "pump",
                "end": f"2026-06-0{index}T10:00:00+00:00",
                "on_delta_w": 80.0,
                "off_delta_w": -80.0,
                **({"confidence": 0.9} if index == 1 else {}),
            }
            for index, suffix in enumerate(("a", "b", "c"), start=1)
        ],
    ]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["transition_prototypes"][0]["sample_count"] == 4
    assert 0.0 < model["model_confidence"] < 0.5


def sample(
    seconds: int,
    watts: float,
    *,
    circuit_id: str = "mains",
    reactive_power: float = 0.0,
    apparent_power: float | None = None,
    power_factor: float | None = 1.0,
) -> CircuitSample:
    return CircuitSample(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        circuit_id=circuit_id,
        real_power=watts,
        current=watts / 120.0 if watts else 0.0,
        voltage=120.0,
        reactive_power=reactive_power,
        apparent_power=apparent_power if apparent_power is not None else watts,
        power_factor=power_factor,
        frequency=60.0,
        energy=0.0,
    )


def split_sample(
    seconds: int,
    leg_a_w: float | None,
    leg_b_w: float | None,
    *,
    reactive_power: float = 0.0,
    apparent_power: float | None = None,
    power_factor: float | None = 1.0,
) -> NormalizedCircuitSample:
    watts = None
    if leg_a_w is not None or leg_b_w is not None:
        watts = float(leg_a_w or 0.0) + float(leg_b_w or 0.0)
    return NormalizedCircuitSample(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        circuit_id="mains",
        real_power=watts,
        current=None,
        voltage=None,
        reactive_power=reactive_power,
        apparent_power=apparent_power if apparent_power is not None else watts,
        power_factor=power_factor,
        frequency=60.0,
        energy=0.0,
        leg_a_real_power=leg_a_w,
        leg_b_real_power=leg_b_w,
    )


def timed_sample(
    seconds: int,
    watts: float,
    *,
    reactive_power: float | None,
    apparent_power: float | None,
    power_factor: float | None,
    updated_at: dict[SensorRole, int],
) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        circuit_id="mains",
        real_power=watts,
        reactive_power=reactive_power,
        apparent_power=apparent_power,
        power_factor=power_factor,
        source_updated_at_by_role=tuple(
            (
                role,
                BASE_TIME + timedelta(seconds=source_seconds),
            )
            for role, source_seconds in updated_at.items()
        ),
    )


def edge(
    seconds: int,
    delta_w: float,
    *,
    delta_var: float | None = 0.0,
    delta_va: float | None | object = _DEFAULT_DELTA_VA,
    delta_pf: float | None = 0.0,
    direction: str | None = None,
    leg_a_delta_w: float | None = None,
    leg_b_delta_w: float | None = None,
    split_phase_type: str = "unknown",
    dominant_leg: str = "unknown",
) -> NilmEdge:
    return NilmEdge(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        delta_w=delta_w,
        delta_var=delta_var,
        delta_va=delta_w if delta_va is _DEFAULT_DELTA_VA else delta_va,
        delta_pf=delta_pf,
        direction=direction or ("on" if delta_w > 0 else "off"),
        leg_a_delta_w=leg_a_delta_w,
        leg_b_delta_w=leg_b_delta_w,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
    )


def transition(
    assignment_id: str,
    delta_w: float,
    *,
    spread_w: float = 5.0,
    sample_count: int = 3,
    delta_var: float | None = None,
    spread_var: float | None = None,
    prototype_id: str = "",
    transition_kind: str = "",
    from_state_id: str = "",
    to_state_id: str = "",
) -> nilm_domain.NilmTransitionPrototype:
    on = delta_w > 0
    return nilm_domain.NilmTransitionPrototype(
        assignment_id=assignment_id,
        direction="on" if on else "off",
        from_state_w=0.0 if on else abs(delta_w),
        to_state_w=abs(delta_w) if on else 0.0,
        delta_w=delta_w,
        spread_w=spread_w,
        sample_count=sample_count,
        delta_var=delta_var,
        spread_var=spread_var,
        prototype_id=prototype_id,
        transition_kind=transition_kind,
        from_state_id=from_state_id,
        to_state_id=to_state_id,
    )


def assignment_model(
    assignment_id: str,
    *prototypes: nilm_domain.NilmTransitionPrototype,
    lifecycle_state: str = "validated",
    last_observed: datetime | None = BASE_TIME,
    model_confidence: float = 0.9,
) -> nilm_domain.NilmAssignmentModel:
    return nilm_domain.NilmAssignmentModel(
        assignment_id=assignment_id,
        power_states_w=(0.0, abs(prototypes[0].delta_w)),
        transition_prototypes=tuple(prototypes),
        model_confidence=model_confidence,
        lifecycle_state=lifecycle_state,
        last_observed=last_observed,
    )


def reconcile(
    candidate_edge: NilmEdge,
    models: list[nilm_domain.NilmAssignmentModel],
    states: dict[str, float | None],
    *,
    helpers: dict[str, float | None] | None = None,
    durations: dict[str, float | None] | None = None,
    validations: dict[str, float | None] | None = None,
    helper_conflict: bool = False,
) -> nilm_domain.NilmReconciliationResult:
    return nilm_domain.reconcile_nilm_edge(
        candidate_edge,
        models,
        states,
        helpers or {},
        durations or {},
        validations or {},
        helper_conflict=helper_conflict,
    )


def test_nilm_transition_tolerance_and_conservation_tolerance_are_exact() -> None:
    assert (
        nilm_domain.nilm_transition_tolerance_w(transition("a", 50, spread_w=2)) == 15
    )
    assert (
        nilm_domain.nilm_transition_tolerance_w(transition("a", 100, spread_w=8)) == 24
    )
    assert (
        nilm_domain.nilm_transition_tolerance_w(transition("a", -200, spread_w=4)) == 40
    )
    assert nilm_domain.conservation_tolerance_w(100, 2) == 25
    assert nilm_domain.conservation_tolerance_w(400, 10) == 40


def test_nilm_transition_score_uses_electrical_fit_and_renormalizes() -> None:
    prototype = transition("a", 100, spread_w=5)
    assert (
        nilm_domain.score_nilm_transition(
            edge(0, 120),
            prototype,
            helper_score=None,
            duration_state_score=None,
            validation_score=None,
        )
        == 0.0
    )
    assert nilm_domain.score_nilm_transition(
        edge(0, 110),
        prototype,
        helper_score=0.8,
        duration_state_score=0.5,
        validation_score=1.0,
    ) == pytest.approx(0.55 * 0.5 + 0.25 * 0.8 + 0.1 * 0.5 + 0.1)
    assert nilm_domain.score_nilm_transition(
        edge(0, 100),
        prototype,
        helper_score=None,
        duration_state_score=None,
        validation_score=None,
        optional_electrical_fit=0.0,
    ) == pytest.approx(0.7)


def test_nilm_score_breakdown_preserves_missing_channel_renormalization() -> None:
    prototype = transition("pump", 100, prototype_id="pump-start")

    breakdown = nilm_domain.score_nilm_transition_breakdown(
        edge(0, 100),
        prototype,
        helper_score=None,
        duration_state_score=None,
        validation_score=None,
    )

    assert breakdown.total == 1.0
    assert breakdown.electrical_fit == 1.0
    assert breakdown.helper_score is None
    assert breakdown.duration_state_score is None
    assert breakdown.validation_score is None
    assert breakdown.available_weight == 0.55
    assert breakdown.electrical_contribution == 1.0
    assert breakdown.helper_contribution is None
    assert breakdown.duration_contribution is None
    assert breakdown.validation_contribution is None


def test_nilm_prototype_score_lookup_wins_over_assignment_fallback() -> None:
    preferred = assignment_model(
        "a", transition("a", 100, prototype_id="a-start")
    )
    other = assignment_model("b", transition("b", 100, prototype_id="b-start"))

    result = reconcile(
        edge(0, 100),
        [other, preferred],
        {"a": 0.0, "b": 0.0},
        validations={"a-start": 1.0, "a": 0.0, "b-start": 0.0, "b": 1.0},
    )

    assert result.accepted is True
    assert result.transitions == preferred.transition_prototypes
    assert result.accepted_prototype_ids == ("a-start",)
    assert result.accepted_score == 1.0
    assert result.runner_up_score == pytest.approx(0.55 / 0.65)
    assert result.score_margin == pytest.approx(1.0 - (0.55 / 0.65))
    assert result.unavailable_channels == ("helper", "duration")
    assert tuple(item.prototype_id for item in result.score_breakdowns) == (
        "a-start",
        "b-start",
    )


def test_nilm_equal_candidates_are_separated_by_duration_soft_evidence() -> None:
    short = assignment_model(
        "short", transition("short", -100, prototype_id="short-stop")
    )
    long = assignment_model("long", transition("long", -100, prototype_id="long-stop"))

    result = reconcile(
        edge(0, -100),
        [long, short],
        {"short": 100.0, "long": 100.0},
        durations={"short-stop": 1.0, "long-stop": 0.0},
    )

    assert result.accepted is True
    assert result.transitions == short.transition_prototypes
    assert result.score_margin == pytest.approx(1.0 - (0.55 / 0.65))


def test_nilm_duration_score_uses_full_age_only_for_supported_stop_to_off() -> None:
    stop = transition(
        "dryer",
        -100,
        prototype_id="dryer-stop",
        transition_kind="stop",
        from_state_id="running",
        to_state_id="off",
    )
    assignment = {
        "run_profile": {
            "duration_s": {
                "effective_support": 5.0,
                "distinct_days": 3,
                "median_seconds": 100.0,
                "p10_seconds": 90.0,
                "p90_seconds": 110.0,
                "median_log_seconds": 4.605,
                "mad_log_seconds": 0.1,
            }
        }
    }

    assert nilm_domain.duration_state_score_for_transition(
        stop,
        assignment,
        {"session_started_at": (BASE_TIME - timedelta(seconds=100)).isoformat()},
        BASE_TIME.replace(tzinfo=None),
    ) == 1.0
    tapered = nilm_domain.duration_state_score_for_transition(
        stop,
        assignment,
        {"session_started_at": BASE_TIME - timedelta(seconds=150)},
        BASE_TIME,
    )
    assert tapered is not None and 0.0 < tapered < 1.0

    start = transition(
        "dryer",
        100,
        transition_kind="start",
        from_state_id="off",
        to_state_id="running",
    )
    active = transition(
        "dryer",
        20,
        transition_kind="state_change",
        from_state_id="low",
        to_state_id="high",
    )
    assert nilm_domain.duration_state_score_for_transition(
        start, assignment, {}, BASE_TIME
    ) is None
    assert nilm_domain.duration_state_score_for_transition(
        active, assignment, {}, BASE_TIME
    ) is None
    assert nilm_domain.duration_state_score_for_transition(
        stop,
        {"run_profile": {"duration_s": {"effective_support": "bad"}}},
        {"session_started_at": "not-a-time"},
        BASE_TIME,
    ) is None


def test_nilm_validation_feedback_is_smoothed_and_revision_gated() -> None:
    assignment = {"model_revision": 7, "model_fingerprint": "model-seven"}
    sparse = [
        {
            "outcome": "correct",
            "timestamp": BASE_TIME.isoformat(),
            "model_revision": 7,
        }
    ]

    sparse_profile = nilm_domain.build_nilm_validation_profile(
        assignment, session_outcomes=sparse
    )
    assert sparse_profile["sample_count"] == 1
    assert 0.5 < sparse_profile["reliability"] < 1.0
    assert sparse_profile["runtime_score"] is None

    eligible = [
        {
            "outcome": "wrong" if index == 4 else "correct",
            "timestamp": (BASE_TIME + timedelta(days=index % 3)).isoformat(),
            "model_revision": 7,
        }
        for index in range(5)
    ]
    eligible.append(
        {
            "outcome": "wrong",
            "timestamp": (BASE_TIME + timedelta(days=4)).isoformat(),
            "model_revision": 6,
        }
    )
    profile = nilm_domain.build_nilm_validation_profile(
        assignment, session_outcomes=reversed(eligible)
    )

    assert profile["sample_count"] == 5
    assert profile["correct_count"] == 4
    assert profile["wrong_count"] == 1
    assert profile["distinct_days"] == 3
    assert profile["runtime_eligible"] is True
    assert profile["runtime_score"] == pytest.approx(6 / 9)


def test_nilm_validation_accepts_only_trusted_ground_truth_and_held_out_data() -> None:
    overlap_only = {
        "model_revision": 2,
        "validation_schema_version": 1,
        "validation_method": "overlap",
        "validation_outcomes": [
            {
                "outcome": "correct",
                "timestamp": (BASE_TIME + timedelta(days=index % 3)).isoformat(),
                "model_revision": 2,
            }
            for index in range(5)
        ],
    }
    assert nilm_domain.build_nilm_validation_profile(overlap_only)["sample_count"] == 0

    trusted = {
        **overlap_only,
        "validation_schema_version": 2,
        "validation_method": "one_to_one_iou",
    }
    ground_truth = nilm_domain.build_nilm_validation_profile(trusted)
    assert ground_truth["runtime_eligible"] is True

    held_out = nilm_domain.build_nilm_validation_profile(
        {"model_fingerprint": "current"},
        held_out_replay=[
            {
                "outcome": "correct",
                "timestamp": (BASE_TIME + timedelta(days=index % 3)).isoformat(),
                "model_fingerprint": "current",
            }
            for index in range(5)
        ],
    )
    assert held_out["source_counts"] == {"held_out_replay": 5}
    assert held_out["runtime_score"] is not None


def test_nilm_compound_uses_each_component_prototype_evidence_deterministically(
) -> None:
    a = assignment_model("a", transition("a", 60, prototype_id="a-start"))
    b = assignment_model("b", transition("b", 40, prototype_id="b-start"))
    states = {"a": 0.0, "b": 0.0}
    scores = {"a-start": 1.0, "a": 0.0, "b-start": 0.5, "b": 0.0}

    forward = reconcile(
        edge(0, 100), [a, b], states, durations=scores, validations=scores
    )
    reverse = reconcile(
        edge(0, 100), [b, a], states, durations=scores, validations=scores
    )

    assert forward == reverse
    assert forward.accepted is True and forward.compound is True
    assert forward.accepted_prototype_ids == ("a-start", "b-start")
    assert len(forward.component_breakdowns) == 2
    assert [item.duration_state_score for item in forward.component_breakdowns] == [
        1.0,
        0.5,
    ]
    assert [item.validation_score for item in forward.component_breakdowns] == [
        1.0,
        0.5,
    ]


def test_reconciliation_uses_var_to_separate_equal_w_components() -> None:
    resistive = assignment_model(
        "heater",
        transition("heater", 100.0, delta_var=0.0, spread_var=5.0),
    )
    motor = assignment_model(
        "motor",
        transition("motor", 100.0, delta_var=80.0, spread_var=5.0),
    )

    result = reconcile(
        edge(0, 100.0, delta_var=78.0),
        [resistive, motor],
        {"heater": 0.0, "motor": 0.0},
    )

    assert result.accepted is True
    assert [item.assignment_id for item in result.transitions] == ["motor"]

    missing_var = reconcile(
        edge(0, 100.0, delta_var=None),
        [resistive, motor],
        {"heater": 0.0, "motor": 0.0},
    )
    assert missing_var.accepted is False
    assert missing_var.reason == "ambiguous"


def test_nilm_single_candidate_applies_threshold_and_lead_gates() -> None:
    strong = assignment_model("strong", transition("strong", 100))
    weak = assignment_model("weak", transition("weak", 111))
    result = reconcile(edge(0, 100), [strong, weak], {"strong": 0.0, "weak": 0.0})
    assert result.accepted and result.reason == "single"
    assert result.transitions == strong.transition_prototypes
    tied = assignment_model("tied", transition("tied", 101))
    result = reconcile(edge(0, 100), [strong, tied], {"strong": 0.0, "tied": 0.0})
    assert not result.accepted and result.reason == "ambiguous"
    result = reconcile(edge(0, 110), [strong], {"strong": 0.0})
    assert not result.accepted and result.reason == "below_threshold"


def test_nilm_candidate_masks_lifecycle_and_illegal_state_but_allows_retired_stop() -> (
    None
):
    on = transition("a", 100)
    off = transition("a", -100)
    for lifecycle in ("hidden", "rejected", "ignored", "converted"):
        result = reconcile(
            edge(0, 100),
            [assignment_model("a", on, lifecycle_state=lifecycle)],
            {"a": 0.0},
        )
        assert not result.accepted
    assert not reconcile(
        edge(0, 100), [assignment_model("a", on)], {"a": 100.0}
    ).accepted
    retired = assignment_model("a", on, off, lifecycle_state="retired")
    assert not reconcile(edge(0, 100), [retired], {"a": 0.0}).accepted
    assert reconcile(edge(0, -100), [retired], {"a": 100.0}).reason == "single"


def test_nilm_helper_unavailability_and_explicit_conflict() -> None:
    a = assignment_model("a", transition("a", 100))
    b = assignment_model("b", transition("b", 101))
    result = reconcile(edge(0, 100), [a], {"a": 0.0}, helpers={"a": None})
    assert result.reason == "single"
    result = reconcile(
        edge(0, 100),
        [a, b],
        {"a": 0.0, "b": 0.0},
        helpers={"a": 0.9, "b": 0.9},
        helper_conflict=True,
    )
    assert not result.accepted and result.reason == "helper_conflict"


def test_nilm_independent_helpers_may_support_a_compound() -> None:
    a = assignment_model("a", transition("a", 60))
    b = assignment_model("b", transition("b", 40))

    result = reconcile(
        edge(0, 100),
        [a, b],
        {"a": 0.0, "b": 0.0},
        helpers={"a": 0.9, "b": 0.9},
    )

    assert result.accepted and result.reason == "compound"


def test_nilm_compound_requires_two_different_learned_assignments_and_improvement() -> (
    None
):
    a = assignment_model("a", transition("a", 60))
    b = assignment_model("b", transition("b", 40))
    result = reconcile(edge(0, 100), [a, b], {"a": 0.0, "b": 0.0})
    assert result.accepted and result.compound and result.reason == "compound"
    assert {item.assignment_id for item in result.transitions} == {"a", "b"}
    unlearned = assignment_model("b", transition("b", 40, sample_count=2))
    assert not reconcile(edge(0, 100), [a, unlearned], {"a": 0.0, "b": 0.0}).accepted


def test_nilm_compound_is_bounded_to_twenty_recent_models() -> None:
    old = assignment_model("old", transition("old", 40), last_observed=BASE_TIME)
    recent = [
        assignment_model(
            f"recent-{index}",
            transition(f"recent-{index}", 5),
            last_observed=BASE_TIME + timedelta(seconds=index + 1),
        )
        for index in range(20)
    ]
    result = reconcile(
        edge(0, 100),
        [old, *recent],
        {model.assignment_id: 0.0 for model in [old, *recent]},
    )
    assert not result.accepted


def test_nilm_three_transition_edge_reconciles_unique_components() -> None:
    models = [
        assignment_model(name, transition(name, watts))
        for name, watts in (("a", 40), ("b", 30), ("c", 30))
    ]
    result = reconcile(
        edge(0, 100), models, {model.assignment_id: 0.0 for model in models}
    )
    assert result.accepted and result.reason == "compound"
    assert {item.assignment_id for item in result.transitions} == {"a", "b", "c"}
    assert result.compound is True
    assert result.consistent is True and result.energy_allocation_allowed is True


def test_nilm_multi_transition_rejects_equal_decompositions() -> None:
    models = [
        assignment_model(name, transition(name, watts))
        for name, watts in (
            ("a", 40),
            ("b", 30),
            ("c", 30),
            ("d", 50),
            ("e", 25),
            ("f", 25),
        )
    ]

    result = reconcile(
        edge(0, 100), models, {model.assignment_id: 0.0 for model in models}
    )

    assert result.accepted is False
    assert result.reason == "ambiguous"


def test_nilm_reconciliation_requires_a_known_finite_current_state() -> None:
    model = assignment_model("a", transition("a", 100))
    for states in ({}, {"a": None}, {"a": float("nan")}, {"a": float("inf")}):
        result = reconcile(edge(0, 100), [model], states)
        assert not result.accepted


def test_nilm_retired_stop_is_single_only_and_never_compound() -> None:
    retired = assignment_model(
        "retired", transition("retired", -60), lifecycle_state="retired"
    )
    active = assignment_model("active", transition("active", 100))
    states = {"retired": 60.0, "active": 0.0}

    assert reconcile(edge(0, -60), [retired], states).reason == "single"
    result = reconcile(edge(0, 40), [retired, active], states)
    assert not result.accepted
    assert result.reason != "compound"


def test_nilm_retired_models_do_not_consume_recent_compound_slots() -> None:
    components = [
        assignment_model(
            name,
            transition(name, watts),
            last_observed=BASE_TIME,
        )
        for name, watts in (("component-a", 60), ("component-b", 40))
    ]
    decoys = [
        assignment_model(
            f"decoy-{index:02d}",
            transition(f"decoy-{index:02d}", 5),
            last_observed=BASE_TIME + timedelta(seconds=index + 1),
        )
        for index in range(18)
    ]
    retired = assignment_model(
        "retired",
        transition("retired", -5),
        lifecycle_state="retired",
        last_observed=BASE_TIME + timedelta(minutes=1),
    )
    models = [retired, *decoys, *components]

    result = reconcile(
        edge(0, 100),
        models,
        {model.assignment_id: 0.0 for model in models},
    )

    assert result.reason == "compound"
    assert {item.assignment_id for item in result.transitions} == {
        "component-a",
        "component-b",
    }


def test_nilm_recent_cutoff_and_equal_error_prototypes_are_order_independent() -> None:
    first = assignment_model("a-first", transition("a-first", 60))
    second = assignment_model("b-second", transition("b-second", 40))
    decoys = [
        assignment_model(f"z-{index:02d}", transition(f"z-{index:02d}", 5))
        for index in range(19)
    ]
    models = [first, second, *decoys]
    states = {model.assignment_id: 0.0 for model in models}
    forward = reconcile(edge(0, 100), models, states)
    reverse = reconcile(edge(0, 100), list(reversed(models)), states)
    assert forward == reverse
    assert forward.reason == "compound"

    low = transition("equal", 90)
    high = transition("equal", 110)
    equal = nilm_domain.NilmAssignmentModel(
        assignment_id="equal",
        power_states_w=(0.0, 90.0, 110.0),
        transition_prototypes=(low, high),
        model_confidence=0.9,
        lifecycle_state="validated",
        last_observed=BASE_TIME,
    )
    partner = assignment_model("partner", transition("partner", 10))
    normal = reconcile(edge(0, 100), [equal, partner], {"equal": 0.0, "partner": 0.0})
    reversed_equal = nilm_domain.NilmAssignmentModel(
        assignment_id="equal",
        power_states_w=equal.power_states_w,
        transition_prototypes=tuple(reversed(equal.transition_prototypes)),
        model_confidence=equal.model_confidence,
        lifecycle_state=equal.lifecycle_state,
        last_observed=equal.last_observed,
    )
    reversed_result = reconcile(
        edge(0, 100), [reversed_equal, partner], {"equal": 0.0, "partner": 0.0}
    )
    assert normal == reversed_result
    assert [item.delta_w for item in normal.transitions] == [90, 10]


def test_nilm_compound_search_never_enumerates_beyond_four_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_sizes: list[int] = []

    def bounded_combinations(iterable, size):
        checked_sizes.append(size)
        if size > 4:
            raise AssertionError("compound search exceeded the four-load bound")
        return stdlib_combinations(iterable, size)

    monkeypatch.setattr(nilm_domain, "combinations", bounded_combinations)
    models = [
        assignment_model(f"load-{index:02d}", transition(f"load-{index:02d}", 1))
        for index in range(20)
    ]
    result = reconcile(
        edge(0, 100), models, {model.assignment_id: 0.0 for model in models}
    )
    assert not result.accepted and result.reason == "below_threshold"
    assert max(checked_sizes) == 4


def helper_event(seconds: int, event_type: EventType) -> CircuitEvent:
    return CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        circuit_id="helper",
        event_type=event_type,
    )


def test_nilm_helper_candidate_scores_one_to_one_directional_pairs() -> None:
    candidates = discover_nilm_helper_candidates(
        [
            edge(0, 500),
            edge(100, 500),
            edge(200, 500),
            edge(300, -500),
            edge(400, -500),
            edge(500, -500),
            edge(2000, 500),
        ],
        {
            "helper": [
                helper_event(10, EventType.START),
                helper_event(130, EventType.START),
                helper_event(250, EventType.START),
                helper_event(320, EventType.STOP),
                helper_event(420, EventType.STOP),
                helper_event(520, EventType.STOP),
                helper_event(900, EventType.START),
            ],
        },
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.matched_on_count == candidate.matched_off_count == 3
    assert candidate.unmatched_source_count == candidate.unmatched_helper_count == 1
    assert candidate.source_coverage == pytest.approx(6 / 7)
    assert candidate.start_coverage == 0.75
    assert candidate.stop_coverage == 1.0
    assert candidate.helper_precision == pytest.approx(6 / 7)
    assert candidate.start_lag_seconds == 30.0
    assert candidate.stop_lag_seconds == 20.0
    assert candidate.start_lag_mad_seconds == 20.0
    assert candidate.stop_lag_mad_seconds == 0.0
    assert candidate.confidence == pytest.approx(0.869047619)
    assert nilm_helper_candidate_to_dict(candidate)["suggested"] is True


def test_nilm_helper_candidate_uses_exact_window_and_diagnostic_gate() -> None:
    source_edges = [
        edge(0, 500),
        edge(2000, 500),
        edge(4000, 500),
        edge(6000, -500),
        edge(8000, -500),
        edge(10000, -500),
    ]
    candidates = discover_nilm_helper_candidates(
        source_edges,
        {
            "inside": [
                helper_event(600, EventType.START),
                helper_event(2600, EventType.START),
                helper_event(4600, EventType.START),
                helper_event(6600, EventType.STOP),
                helper_event(8600, EventType.STOP),
                helper_event(10600, EventType.STOP),
            ],
            "outside": [
                helper_event(601, EventType.START),
                helper_event(2601, EventType.START),
                helper_event(4601, EventType.START),
                helper_event(6601, EventType.STOP),
                helper_event(8601, EventType.STOP),
                helper_event(10601, EventType.STOP),
            ],
            "few": [
                helper_event(1, EventType.START),
                helper_event(2001, EventType.START),
                helper_event(6001, EventType.STOP),
                helper_event(8001, EventType.STOP),
            ],
        },
    )

    by_id = {candidate.helper_circuit_id: candidate for candidate in candidates}
    assert by_id["inside"].confidence == 1.0
    assert nilm_helper_candidate_to_dict(by_id["inside"])["suggested"] is True
    assert by_id["outside"].matched_on_count == by_id["outside"].matched_off_count == 0
    assert by_id["few"].confidence == 0.0
    assert nilm_helper_candidate_to_dict(by_id["few"])["suggested"] is False
    assert score_nilm_helper_candidate(0.9, 0.8, 30.0) == pytest.approx(0.835)
    assert score_nilm_helper_candidate(1.0, 1.0, 0.0) == 1.0
    threshold = NilmHelperCandidate(
        helper_circuit_id="threshold",
        matched_on_count=3,
        matched_off_count=3,
        unmatched_source_count=0,
        unmatched_helper_count=0,
        source_event_count=6,
        helper_event_count=6,
        source_coverage=1.0,
        start_coverage=1.0,
        stop_coverage=1.0,
        helper_precision=1.0,
        start_lag_seconds=0.0,
        stop_lag_seconds=0.0,
        start_lag_mad_seconds=0.0,
        stop_lag_mad_seconds=0.0,
        confidence=0.75,
        last_observed=BASE_TIME,
    )
    assert nilm_helper_candidate_to_dict(threshold)["suggested"] is True


def test_nilm_helper_candidates_sort_and_cap_by_confidence_then_recency() -> None:
    source_edges = [edge(index * 1000, 500) for index in range(3)] + [
        edge((index + 3) * 1000, -500) for index in range(3)
    ]
    events = {
        f"helper-{index}": [
            helper_event(
                int((edge_.timestamp - BASE_TIME).total_seconds()) + index,
                EventType.START if edge_.direction == "on" else EventType.STOP,
            )
            for edge_ in source_edges
        ]
        for index in range(9)
    }
    candidates = discover_nilm_helper_candidates(source_edges, events)

    assert len(candidates) == 8
    assert [candidate.helper_circuit_id for candidate in candidates] == [
        f"helper-{index}" for index in range(8, 0, -1)
    ]


def test_edge_detector_emits_on_and_off_edges_from_current_sample_fields() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            sample(
                0,
                80.0,
                reactive_power=10.0,
                apparent_power=82.0,
                power_factor=0.98,
            ),
            sample(
                10,
                260.0,
                reactive_power=55.0,
                apparent_power=266.0,
                power_factor=0.91,
            ),
            sample(
                20,
                95.0,
                reactive_power=12.0,
                apparent_power=98.0,
                power_factor=0.97,
            ),
        ]
    )

    assert [candidate.direction for candidate in edges] == ["on", "off"]
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 180.0
    assert edges[0].delta_var == 45.0
    assert edges[0].delta_va == 184.0
    assert round(edges[0].delta_pf, 2) == -0.07
    assert edges[1].delta_w == -165.0


def test_edge_detector_keeps_missing_auxiliary_evidence_unavailable() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            CircuitSample(
                timestamp=BASE_TIME,
                circuit_id="mains",
                real_power=0.0,
            ),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=10),
                circuit_id="mains",
                real_power=220.0,
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 220.0
    assert edges[0].delta_var is None
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_preserves_measured_zero_auxiliary_delta() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            CircuitSample(
                timestamp=BASE_TIME,
                circuit_id="mains",
                real_power=100.0,
                reactive_power=10.0,
                apparent_power=120.0,
                power_factor=0.833,
            ),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=10),
                circuit_id="mains",
                real_power=220.0,
                reactive_power=10.0,
                apparent_power=240.0,
                power_factor=0.917,
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_var == 0.0


def test_confirmed_edge_uses_final_sample_for_delayed_auxiliary_evidence() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [
            timed_sample(
                0,
                0.0,
                reactive_power=10.0,
                apparent_power=100.0,
                power_factor=0.0,
                updated_at={
                    SensorRole.REAL_POWER: 0,
                    SensorRole.REACTIVE_POWER: 0,
                    SensorRole.APPARENT_POWER: 0,
                    SensorRole.POWER_FACTOR: 0,
                },
            ),
            timed_sample(
                10,
                200.0,
                reactive_power=10.0,
                apparent_power=200.0,
                power_factor=1.0,
                updated_at={
                    SensorRole.REAL_POWER: 10,
                    SensorRole.REACTIVE_POWER: 0,
                    SensorRole.APPARENT_POWER: 0,
                    SensorRole.POWER_FACTOR: 0,
                },
            ),
            timed_sample(
                20,
                195.0,
                reactive_power=55.0,
                apparent_power=205.0,
                power_factor=0.95,
                updated_at={
                    SensorRole.REAL_POWER: 20,
                    SensorRole.REACTIVE_POWER: 20,
                    SensorRole.APPARENT_POWER: 20,
                    SensorRole.POWER_FACTOR: 20,
                },
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 195.0
    assert edges[0].delta_var == 45.0
    assert edges[0].delta_va == 105.0
    assert edges[0].delta_pf == pytest.approx(0.95)


def test_sensitive_50w_edge_requires_a_second_nearby_sample() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=50.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [
            CircuitSample(BASE_TIME, "mains", real_power=0.0),
            CircuitSample(BASE_TIME + timedelta(seconds=10), "mains", real_power=55.0),
            CircuitSample(BASE_TIME + timedelta(seconds=20), "mains", real_power=52.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 52.0


def test_sensitive_50w_edge_rejects_a_single_sample_excursion() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=50.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [
            CircuitSample(BASE_TIME, "mains", real_power=0.0),
            CircuitSample(BASE_TIME + timedelta(seconds=10), "mains", real_power=55.0),
            CircuitSample(BASE_TIME + timedelta(seconds=20), "mains", real_power=0.0),
        ]
    )

    assert edges == []


def test_edge_detector_discards_auxiliary_evidence_outside_confirmation_window() -> (
    None
):
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [
            timed_sample(
                0,
                0.0,
                reactive_power=10.0,
                apparent_power=100.0,
                power_factor=0.0,
                updated_at={
                    SensorRole.REAL_POWER: 0,
                    SensorRole.REACTIVE_POWER: 0,
                    SensorRole.APPARENT_POWER: 0,
                    SensorRole.POWER_FACTOR: 0,
                },
            ),
            timed_sample(
                10,
                200.0,
                reactive_power=10.0,
                apparent_power=200.0,
                power_factor=1.0,
                updated_at={
                    SensorRole.REAL_POWER: 10,
                    SensorRole.REACTIVE_POWER: 0,
                    SensorRole.APPARENT_POWER: 0,
                    SensorRole.POWER_FACTOR: 0,
                },
            ),
            timed_sample(
                20,
                200.0,
                reactive_power=55.0,
                apparent_power=205.0,
                power_factor=0.95,
                updated_at={
                    SensorRole.REAL_POWER: 20,
                    SensorRole.REACTIVE_POWER: 0,
                    SensorRole.APPARENT_POWER: 0,
                    SensorRole.POWER_FACTOR: 0,
                },
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_var is None
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_derives_va_and_pf_from_synchronized_voltage_current() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            CircuitSample(
                timestamp=BASE_TIME,
                circuit_id="mains",
                real_power=0.0,
                voltage=120.0,
                current=1.0,
            ),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=10),
                circuit_id="mains",
                real_power=200.0,
                voltage=120.0,
                current=2.0,
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_va == pytest.approx(120.0)
    assert edges[0].delta_pf == pytest.approx(round(200.0 / 240.0, 3))


def test_edge_detector_rejects_derived_evidence_when_voltage_is_out_of_window() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [
            NormalizedCircuitSample(
                timestamp=BASE_TIME,
                circuit_id="mains",
                real_power=0.0,
                voltage=120.0,
                current=1.0,
                source_updated_at_by_role=(
                    (SensorRole.REAL_POWER, BASE_TIME),
                    (SensorRole.VOLTAGE, BASE_TIME - timedelta(seconds=30)),
                    (SensorRole.CURRENT, BASE_TIME),
                ),
            ),
            NormalizedCircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=10),
                circuit_id="mains",
                real_power=200.0,
                voltage=120.0,
                current=2.0,
                source_updated_at_by_role=(
                    (SensorRole.REAL_POWER, BASE_TIME + timedelta(seconds=10)),
                    (SensorRole.VOLTAGE, BASE_TIME - timedelta(seconds=20)),
                    (SensorRole.CURRENT, BASE_TIME + timedelta(seconds=10)),
                ),
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_does_not_use_conflicting_va_as_strong_evidence() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            CircuitSample(
                timestamp=BASE_TIME,
                circuit_id="mains",
                real_power=100.0,
                apparent_power=120.0,
                voltage=120.0,
                current=1.0,
            ),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=10),
                circuit_id="mains",
                real_power=220.0,
                apparent_power=100.0,
                voltage=120.0,
                current=2.0,
            ),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 120.0
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_infers_balanced_split_phase_transition() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            split_sample(0, 100.0, 95.0),
            split_sample(10, 400.0, 405.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 610.0
    assert edges[0].leg_a_delta_w == 300.0
    assert edges[0].leg_b_delta_w == 310.0
    assert edges[0].split_phase_type == "balanced_240v"
    assert edges[0].dominant_leg == "balanced"
    assert edges[0].leg_balance_ratio == 0.033


def test_edge_detector_infers_single_leg_transition() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            split_sample(0, 100.0, 95.0),
            split_sample(10, 455.0, 100.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].delta_w == 360.0
    assert edges[0].leg_a_delta_w == 355.0
    assert edges[0].leg_b_delta_w == 5.0
    assert edges[0].split_phase_type == "single_leg_a"
    assert edges[0].dominant_leg == "a"


def test_edge_detector_treats_borderline_secondary_leg_as_mixed() -> None:
    detector = NilmEdgeDetector(min_delta_w=50.0)

    edges = detector.process_many(
        [
            split_sample(0, 0.0, 0.0),
            split_sample(10, 75.0, 50.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].split_phase_type == "imbalanced_240v_or_mixed"
    assert edges[0].dominant_leg == "a"


def test_edge_detector_treats_opposing_leg_changes_as_mixed() -> None:
    detector = NilmEdgeDetector(min_delta_w=50.0)

    edges = detector.process_many(
        [
            split_sample(0, 100.0, 100.0),
            split_sample(10, 220.0, 40.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].leg_a_delta_w == 120.0
    assert edges[0].leg_b_delta_w == -60.0
    assert edges[0].split_phase_type == "imbalanced_240v_or_mixed"
    assert edges[0].dominant_leg == "mixed"


def test_edge_detector_treats_small_opposing_leg_change_as_mixed() -> None:
    detector = NilmEdgeDetector(min_delta_w=50.0)

    edges = detector.process_many(
        [
            split_sample(0, 100.0, 100.0),
            split_sample(10, 220.0, 90.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].leg_a_delta_w == 120.0
    assert edges[0].leg_b_delta_w == -10.0
    assert edges[0].split_phase_type == "imbalanced_240v_or_mixed"
    assert edges[0].dominant_leg == "mixed"


def test_edge_detector_ignores_missing_real_power_and_small_changes() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            sample(0, 50.0),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=5),
                circuit_id="mains",
            ),
            sample(10, 120.0),
            sample(15, 180.0),
            sample(20, 20.0),
        ]
    )

    assert edges == [edge(20, -160.0)]


def test_edge_detector_invalidates_previous_sample_across_missing_real_power() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            sample(0, 50.0),
            CircuitSample(
                timestamp=BASE_TIME + timedelta(seconds=5),
                circuit_id="mains",
            ),
            sample(10, 180.0),
        ]
    )

    assert edges == []


def test_edge_detector_rejects_one_sample_excursion_with_confirmation() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0, confirmation_samples=2)

    edges = detector.process_many(
        [
            sample(0, 0.0),
            sample(10, 1_000.0),
            sample(20, 0.0),
        ]
    )

    assert edges == []


def test_edge_detector_honors_confirmation_tolerance_near_threshold() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_tolerance_ratio=0.15,
    )

    edges = detector.process_many([sample(0, 0.0), sample(10, 100.0), sample(20, 51.0)])

    assert edges == []


def test_edge_detector_keeps_original_timestamp_for_confirmed_level() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0, confirmation_samples=2)

    edges = detector.process_many(
        [
            sample(0, 0.0),
            sample(10, 1_000.0),
            sample(20, 980.0),
        ]
    )

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 980.0


def test_edge_detector_does_not_debounce_sparse_samples() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many([sample(0, 0.0), sample(30, 1_000.0)])

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=30)


def test_edge_detector_keeps_pending_transition_after_delayed_confirmation() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [sample(0, 0.0), sample(10, 1_000.0), sample(30, 1_000.0)]
    )

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 1_000.0


def test_edge_detector_drops_timed_out_reversion_to_baseline() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many(
        [sample(0, 0.0), sample(10, 1_000.0), sample(30, 0.0)]
    )

    assert edges == []


def test_mask_known_loads_uses_event_timestamp_and_current_feature_names() -> None:
    known_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=11),
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 205.0},
    )

    result = mask_known_loads(
        [edge(10, 200.0), edge(40, 325.0)],
        [known_event],
        time_window=timedelta(seconds=15),
        watt_tolerance_ratio=0.25,
    )

    assert len(result.matched_edges) == 1
    assert result.matched_edges[0].edge == edge(10, 200.0)
    assert result.matched_edges[0].known_circuit_id == "fridge"
    assert result.matched_edges[0].magnitude_score > 0.9
    assert result.matched_edges[0].confidence == pytest.approx(0.8482520325)
    assert result.unmatched_edges == (edge(40, 325.0),)


def test_attribute_known_loads_prefers_transition_delta_and_records_provenance() -> (
    None
):
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="heater",
        event_type=EventType.START,
        features={
            "startup_power_w": 120.0,
            "transition_delta_w": 100.0,
            "transition_spread_w": 4.0,
        },
    )

    result = attribute_known_loads([edge(10, 120.0), edge(10, 100.0)], [event])

    assert [match.edge.delta_w for match in result.matched_edges] == [100.0]
    match = result.matched_edges[0]
    assert match.known_power_w == 100.0
    assert match.known_power_source == "transition_delta_w"
    assert match.known_transition_delta_w == 100.0
    assert match.known_transition_spread_w == 4.0
    assert match.power_match_confidence == 1.0
    assert match.selection_status == "matched"


def test_attribute_known_loads_uses_signed_transition_delta_for_stop() -> None:
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="heater",
        event_type=EventType.STOP,
        features={"stop_power_w": 120.0, "transition_delta_w": -100.0},
    )

    result = attribute_known_loads([edge(10, -120.0), edge(10, -100.0)], [event])

    match = result.matched_edges[0]
    assert match.edge.delta_w == -100.0
    assert match.known_power_source == "transition_delta_w"
    assert match.known_transition_delta_w == -100.0
    assert match.explained_delta_w == -100.0


@pytest.mark.parametrize("transition_delta_w", [100.0, -100.0])
def test_attribute_known_loads_uses_power_transition_signed_delta_and_direction(
    transition_delta_w: float,
) -> None:
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="variable-speed-load",
        event_type=EventType.POWER_TRANSITION,
        features={
            "transition_delta_w": transition_delta_w,
            "startup_power_w": 1200.0,
            "stop_power_w": 1200.0,
        },
    )
    matching_edge = edge(10, transition_delta_w)
    opposite_edge = edge(10, -transition_delta_w)

    result = attribute_known_loads([matching_edge, opposite_edge], [event])

    assert [match.edge for match in result.matched_edges] == [matching_edge]
    match = result.matched_edges[0]
    assert match.known_power_source == "transition_delta_w"
    assert match.explained_delta_w == transition_delta_w
    assert result.unmatched_edges == (opposite_edge,)


@pytest.mark.parametrize("transition_delta_w", [None, 0.0, float("inf"), float("nan")])
def test_attribute_known_loads_never_falls_back_for_invalid_power_transition_delta(
    transition_delta_w: float | None,
) -> None:
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="variable-speed-load",
        event_type=EventType.POWER_TRANSITION,
        features={
            "transition_delta_w": transition_delta_w,
            "startup_power_w": 100.0,
            "stop_power_w": 100.0,
            "state_power_w": 100.0,
        },
    )
    aggregate = edge(10, 100.0)

    result = attribute_known_loads([aggregate], [event])

    assert result.matched_edges == ()
    assert result.unmatched_edges == (aggregate,)


def test_attribute_known_loads_retains_power_transition_topology_rejection() -> None:
    aggregate = edge(10, 100.0, split_phase_type="balanced_240v")
    event = CircuitEvent(
        aggregate.timestamp,
        "variable-speed-load",
        EventType.POWER_TRANSITION,
        features={"transition_delta_w": 100.0},
    )

    result = attribute_known_loads(
        [aggregate],
        [event],
        topology_by_circuit={
            "variable-speed-load": nilm_domain.KnownLoadTopology(("single_leg_a",))
        },
    )

    assert result.matched_edges == ()
    assert result.unmatched_edges == (aggregate,)
    assert result.topology_rejections[0].event_type is EventType.POWER_TRANSITION
    assert result.topology_rejections[0].explained_delta_w == 100.0


@pytest.mark.parametrize(
    "transition_delta_w",
    [-100.0, 0.0, None, float("inf"), float("nan")],
)
def test_attribute_known_loads_falls_back_when_transition_delta_is_invalid(
    transition_delta_w: float | None,
) -> None:
    features: dict[str, float | None] = {
        "startup_power_w": 120.0,
        "transition_delta_w": transition_delta_w,
    }
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="heater",
        event_type=EventType.START,
        features=features,
    )

    result = attribute_known_loads([edge(10, 120.0), edge(10, 100.0)], [event])

    match = result.matched_edges[0]
    assert match.edge.delta_w == 120.0
    assert match.known_power_source == "startup_power_w"
    assert match.known_transition_delta_w is None


def test_attribute_known_loads_scores_edges_inside_transition_window_at_zero_distance(  # noqa: E501
) -> None:
    interval_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=40),
        circuit_id="heater",
        event_type=EventType.START,
        features={
            "startup_power_w": 100.0,
            "transition_window_start": "2026-06-02T12:00:10+00:00",
            "transition_window_end": "2026-06-02T12:00:20+00:00",
            "transition_timestamp": "2026-06-02T12:00:15+00:00",
            "transition_timing_uncertainty_s": 2.5,
        },
    )
    legacy_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=11),
        circuit_id="legacy",
        event_type=EventType.START,
        features={"startup_power_w": 100.0},
    )

    interval_result = attribute_known_loads(
        [edge(15, 100.0)], [interval_event], time_window=timedelta(seconds=15)
    )
    legacy_result = attribute_known_loads(
        [edge(10, 100.0)], [legacy_event], time_window=timedelta(seconds=15)
    )

    interval_match = interval_result.matched_edges[0]
    legacy_match = legacy_result.matched_edges[0]
    assert interval_match.time_distance_seconds == 0.0
    assert interval_match.time_offset_seconds == 0.0
    assert interval_match.transition_timing_uncertainty_s == 2.5
    assert legacy_match.time_distance_seconds == 1.0
    assert legacy_match.time_offset_seconds == 1.0


def test_attribute_known_loads_transition_delta_conserves_residual() -> None:
    features = {"startup_power_w": 120.0, "transition_delta_w": 100.0}
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=10),
        circuit_id="heater",
        event_type=EventType.START,
        features=features,
    )
    original = edge(10, 120.0)

    result = attribute_known_loads([original], [event], residual_min_delta_w=10.0)

    match = result.matched_edges[0]
    assert match.explained_delta_w == 100.0
    assert match.residual_delta_w == 20.0
    assert original.delta_w == match.explained_delta_w + match.residual_delta_w
    assert result.residual_edges[0].delta_w == 20.0
    assert dict(event.features) == features


@pytest.mark.parametrize(
    ("aggregate_delta_w", "transition_delta_w", "expected_residual_w"),
    ((120.0, 100.0, 20.0), (-120.0, -100.0, -20.0)),
)
def test_power_transition_conserves_signed_nonzero_residual_with_provenance(
    aggregate_delta_w: float,
    transition_delta_w: float,
    expected_residual_w: float,
) -> None:
    aggregate = edge(10, aggregate_delta_w)
    event = CircuitEvent(
        timestamp=aggregate.timestamp,
        circuit_id="variable-speed-load",
        event_type=EventType.POWER_TRANSITION,
        features={"transition_delta_w": transition_delta_w},
    )

    result = attribute_known_loads([aggregate], [event], residual_min_delta_w=10.0)

    match = result.matched_edges[0]
    residual = result.residual_edges[0]
    assert match.edge.delta_w == aggregate_delta_w
    assert match.explained_delta_w == transition_delta_w
    assert match.edge.delta_w == match.explained_delta_w + match.residual_delta_w
    assert residual.delta_w == expected_residual_w
    assert residual.direction == ("on" if expected_residual_w > 0.0 else "off")
    assert residual.origin == "known_load_residual"
    assert residual.parent_edge_id == nilm_domain._nilm_edge_id(aggregate)
    assert residual.explained_known_circuit_ids == ("variable-speed-load",)


@pytest.mark.parametrize(
    (
        "aggregate_delta_w",
        "event_type",
        "feature",
        "expected_explained",
        "expected_residual",
    ),
    [
        (1200.0, EventType.START, {"startup_power_w": 1000.0}, 1000.0, 200.0),
        (-1200.0, EventType.STOP, {"stop_power_w": 1000.0}, -1000.0, -200.0),
    ],
)
def test_attribute_known_loads_consumes_aggregate_and_emits_conserving_residual(
    aggregate_delta_w: float,
    event_type: EventType,
    feature: dict[str, float],
    expected_explained: float,
    expected_residual: float,
) -> None:
    original = edge(10, aggregate_delta_w, delta_var=250.0, delta_va=1250.0)
    event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=11),
        circuit_id="water_heater",
        event_type=event_type,
        features=feature,
    )

    result = attribute_known_loads([original], [event], residual_min_delta_w=100.0)

    assert result.unmatched_edges == (result.residual_edges[0],)
    assert result.matched_edges[0].edge == original
    assert result.matched_edges[0].explained_delta_w == expected_explained
    assert result.matched_edges[0].residual_delta_w == expected_residual
    assert original.delta_w == (
        result.matched_edges[0].explained_delta_w
        + result.matched_edges[0].residual_delta_w
    )
    residual = result.residual_edges[0]
    assert residual.delta_w == expected_residual
    assert residual.direction == ("on" if expected_residual > 0 else "off")
    assert residual.origin == "known_load_residual"
    assert residual.parent_edge_id == nilm_domain._nilm_edge_id(original)
    assert residual.explained_known_circuit_ids == ("water_heater",)
    assert residual.timestamp == original.timestamp
    assert (residual.delta_var, residual.delta_va, residual.delta_pf) == (
        None,
        None,
        None,
    )
    assert (residual.leg_a_delta_w, residual.leg_b_delta_w) == (None, None)


def test_nilm_edge_id_distinguishes_known_load_residual_provenance() -> None:
    aggregate = edge(10, 200.0)
    residual = NilmEdge(
        timestamp=aggregate.timestamp,
        delta_w=aggregate.delta_w,
        delta_var=aggregate.delta_var,
        delta_va=aggregate.delta_va,
        delta_pf=aggregate.delta_pf,
        direction=aggregate.direction,
        origin="known_load_residual",
        parent_edge_id="aggregate-edge",
        explained_known_circuit_ids=("fridge",),
    )

    assert nilm_domain._nilm_edge_id(aggregate) != nilm_domain._nilm_edge_id(residual)


@pytest.mark.parametrize("aggregate_delta_w", [1005.0, -1005.0])
def test_attribute_known_loads_skips_residual_below_threshold(
    aggregate_delta_w: float,
) -> None:
    event_type = EventType.START if aggregate_delta_w > 0 else EventType.STOP
    feature = "startup_power_w" if aggregate_delta_w > 0 else "stop_power_w"

    result = attribute_known_loads(
        [edge(10, aggregate_delta_w)],
        [
            CircuitEvent(
                BASE_TIME + timedelta(seconds=10),
                "dryer",
                event_type,
                features={feature: 1000.0},
            )
        ],
        residual_min_delta_w=100.0,
    )

    assert result.matched_edges[0].residual_delta_w == (
        aggregate_delta_w - (1000.0 if aggregate_delta_w > 0 else -1000.0)
    )
    assert result.residual_edges == ()
    assert result.unmatched_edges == ()


def test_attribute_known_loads_derives_residual_direction_from_its_sign() -> None:
    result = attribute_known_loads(
        [edge(10, 800.0)],
        [
            CircuitEvent(
                BASE_TIME + timedelta(seconds=10),
                "heater",
                EventType.START,
                features={"startup_power_w": 1000.0},
            )
        ],
        residual_min_delta_w=100.0,
    )

    assert result.residual_edges[0].delta_w == -200.0
    assert result.residual_edges[0].direction == "off"


@pytest.mark.parametrize("known_power_w", [0.0, float("inf"), float("nan")])
def test_attribute_known_loads_rejects_nonpositive_or_nonfinite_known_power(
    known_power_w: float,
) -> None:
    original = edge(10, 1000.0)

    result = attribute_known_loads(
        [original],
        [
            CircuitEvent(
                BASE_TIME + timedelta(seconds=10),
                "heater",
                EventType.START,
                features={"startup_power_w": known_power_w},
            )
        ],
    )

    assert result.matched_edges == ()
    assert result.unmatched_edges == (original,)


def test_attribute_known_loads_only_consumes_aggregate_edges() -> None:
    residual = NilmEdge(
        timestamp=BASE_TIME + timedelta(seconds=10),
        delta_w=1000.0,
        direction="on",
        origin="known_load_residual",
    )

    result = attribute_known_loads(
        [residual],
        [
            CircuitEvent(
                BASE_TIME + timedelta(seconds=10),
                "heater",
                EventType.START,
                features={"startup_power_w": 1000.0},
            )
        ],
    )

    assert result.matched_edges == ()
    assert result.unmatched_edges == (residual,)


def test_mask_known_loads_supports_stop_power_features() -> None:
    known_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=30),
        circuit_id="pump",
        event_type=EventType.STOP,
        features={"stop_power_w": 150.0},
    )

    result = mask_known_loads([edge(30, -155.0)], [known_event])

    assert result.matched_edges[0].known_circuit_id == "pump"
    assert result.unmatched_edges == ()


def test_mask_known_loads_uses_each_known_event_once_with_closest_tie_break() -> None:
    known_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=30),
        circuit_id="dishwasher",
        event_type=EventType.START,
        features={"startup_power_w": 200.0},
    )

    result = mask_known_loads(
        [edge(20, 200.0), edge(29, 200.0)],
        [known_event],
        time_window=timedelta(seconds=15),
    )

    assert tuple(match.edge for match in result.matched_edges) == (edge(29, 200.0),)
    assert result.unmatched_edges == (edge(20, 200.0),)


@pytest.mark.parametrize(
    ("topology", "candidate", "expected"),
    [
        (
            {"expected_split_phase_types": ("single_leg_a", "single_leg_b")},
            {"split_phase_type": "single_leg_a"},
            "consistent",
        ),
        (
            {"expected_split_phase_types": ("single_leg_a", "single_leg_b")},
            {"split_phase_type": "unknown"},
            "unknown_topology",
        ),
        ({}, {"split_phase_type": "balanced_240v"}, "not_evaluated"),
        (
            {"expected_split_phase_types": ("balanced_240v",)},
            {"split_phase_type": "single_leg_a"},
            "topology_mismatch",
        ),
        (
            {
                "expected_split_phase_types": ("single_leg_a", "single_leg_b"),
                "configured_leg": "a",
            },
            {"split_phase_type": "single_leg_b"},
            "leg_mismatch",
        ),
    ],
)
def test_known_load_topology_evaluator_returns_shared_statuses(
    topology: dict[str, object],
    candidate: dict[str, object],
    expected: str,
) -> None:
    expectation = nilm_domain.KnownLoadTopology(**topology)
    candidate_edge = edge(0, 1000.0, **candidate)

    assert (
        nilm_domain.evaluate_known_load_topology(candidate_edge, expectation)
        == expected
    )


def test_attribute_known_loads_prefers_closer_time_for_equal_magnitude() -> None:
    aggregate = edge(30, 1000.0)
    farther = CircuitEvent(
        BASE_TIME + timedelta(seconds=16),
        "farther",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    closer = CircuitEvent(
        BASE_TIME + timedelta(seconds=29),
        "closer",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )

    result = attribute_known_loads([aggregate], [farther, closer])

    assert [match.known_circuit_id for match in result.matched_edges] == ["closer"]
    match = result.matched_edges[0]
    assert match.time_offset_seconds == -1.0
    assert match.time_score == pytest.approx(14 / 15)
    assert match.magnitude_score == 1.0
    assert match.power_source == "startup_power_w"
    assert match.topology_status == "not_evaluated"
    assert match.selection_method == "global_assignment"


def test_attribute_known_loads_scores_exact_time_above_fourteen_seconds() -> None:
    expectation = {"load": nilm_domain.KnownLoadTopology(("single_leg_a",), None)}
    aggregate = edge(30, 1000.0, split_phase_type="single_leg_a")
    exact = CircuitEvent(
        aggregate.timestamp,
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    fourteen_seconds = CircuitEvent(
        aggregate.timestamp - timedelta(seconds=14),
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )

    exact_result = attribute_known_loads(
        [aggregate], [exact], topology_by_circuit=expectation
    )
    delayed_result = attribute_known_loads(
        [aggregate], [fourteen_seconds], topology_by_circuit=expectation
    )

    assert exact_result.matched_edges[0].confidence == 1.0
    assert delayed_result.matched_edges[0].time_score == pytest.approx(1 / 15)
    assert delayed_result.matched_edges[0].confidence == pytest.approx(
        0.65 + (0.20 / 15) + 0.15
    )
    assert exact_result.matched_edges[0].confidence > (
        delayed_result.matched_edges[0].confidence
    )
    assert (
        nilm_domain.KNOWN_LOAD_MAGNITUDE_WEIGHT
        + nilm_domain.KNOWN_LOAD_TIME_WEIGHT
        + nilm_domain.KNOWN_LOAD_TOPOLOGY_WEIGHT
        == pytest.approx(1.0)
    )


def test_attribute_known_loads_enforces_time_and_magnitude_cutoffs() -> None:
    aggregate = edge(30, 1000.0)
    too_late = CircuitEvent(
        aggregate.timestamp + timedelta(seconds=15, microseconds=1),
        "late",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    too_different = CircuitEvent(
        aggregate.timestamp,
        "different",
        EventType.START,
        features={"startup_power_w": 799.9},
    )

    assert attribute_known_loads([aggregate], [too_late]).matched_edges == ()
    assert attribute_known_loads([aggregate], [too_different]).matched_edges == ()

    boundary = attribute_known_loads(
        [aggregate],
        [
            CircuitEvent(
                aggregate.timestamp + timedelta(seconds=15),
                "boundary",
                EventType.START,
                features={"startup_power_w": 800.0},
            )
        ],
    )
    assert len(boundary.matched_edges) == 1
    assert boundary.matched_edges[0].time_score == 0.0
    assert boundary.matched_edges[0].magnitude_score == 0.0


@pytest.mark.parametrize(
    ("candidate_edge", "topology_values", "expected_status"),
    [
        (
            edge(0, 1000.0, split_phase_type="balanced_240v"),
            (("single_leg_a", "single_leg_b"), None),
            "topology_mismatch",
        ),
        (
            edge(0, 1000.0, split_phase_type="single_leg_b"),
            (("single_leg_a", "single_leg_b"), "a"),
            "leg_mismatch",
        ),
    ],
)
def test_attribute_known_loads_retains_rejected_topology_evidence(
    candidate_edge: NilmEdge,
    topology_values: tuple[tuple[str, ...], str | None],
    expected_status: str,
) -> None:
    event = CircuitEvent(
        candidate_edge.timestamp,
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    topology = nilm_domain.KnownLoadTopology(*topology_values)

    result = attribute_known_loads(
        [candidate_edge], [event], topology_by_circuit={"load": topology}
    )

    assert result.matched_edges == ()
    assert result.unmatched_edges == (candidate_edge,)
    assert result.residual_edges == ()
    assert len(result.rejected_topology_candidates) == 1
    rejection = result.rejected_topology_candidates[0]
    assert rejection.edge == candidate_edge
    assert rejection.topology_status == expected_status
    assert rejection.topology_score == 0.0
    assert rejection.magnitude_score == 1.0
    assert rejection.time_score == 1.0
    assert rejection.confidence == pytest.approx(0.85)


def test_attribute_known_loads_bounds_topology_rejections_after_assignment() -> None:
    """A wrong selection/suppression branch would retain noisy diagnostics."""
    topology = {"load": nilm_domain.KnownLoadTopology(("single_leg_a",))}
    rejected_exact = edge(0, 1000.0, split_phase_type="balanced_240v")
    rejected_weaker = edge(1, 900.0, split_phase_type="balanced_240v")
    selected = edge(2, 1000.0, split_phase_type="single_leg_a")
    load_event = CircuitEvent(
        BASE_TIME,
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    result = attribute_known_loads(
        [rejected_exact, rejected_weaker, selected],
        [load_event],
        topology_by_circuit=topology,
    )

    assert [match.known_circuit_id for match in result.matched_edges] == ["load"]
    assert result.unmatched_edges == (rejected_exact, rejected_weaker)
    assert result.rejected_topology_candidates == ()
    assert result.topology_rejections == result.rejected_topology_candidates


def test_attribute_known_loads_retains_strongest_unsuppressed_rejection() -> None:
    """Removing power/time/identity ordering would report a noisy mismatch."""
    first = edge(0, 1000.0, split_phase_type="balanced_240v")
    equal = edge(0, 1000.0, split_phase_type="balanced_240v")
    weaker = edge(1, 900.0, split_phase_type="balanced_240v")
    event = CircuitEvent(
        BASE_TIME,
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )

    result = attribute_known_loads(
        [first, equal, weaker],
        [event],
        topology_by_circuit={"load": nilm_domain.KnownLoadTopology(("single_leg_a",))},
    )

    assert result.unmatched_edges == (first, equal, weaker)
    assert result.topology_rejections == (result.rejected_topology_candidates[0],)
    assert result.topology_rejections[0].edge is first
    assert result.topology_rejections[0].selection_status == "rejected_topology"


def test_attribute_known_loads_prefers_closest_equal_power_rejection() -> None:
    """Removing time ordering would retain the farther same-event rejection."""
    farther = edge(4, 1000.0, split_phase_type="balanced_240v")
    closer = edge(1, 1000.0, split_phase_type="balanced_240v")
    event = CircuitEvent(
        BASE_TIME,
        "load",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )

    result = attribute_known_loads(
        [farther, closer],
        [event],
        topology_by_circuit={"load": nilm_domain.KnownLoadTopology(("single_leg_a",))},
    )

    assert result.topology_rejections == (result.rejected_topology_candidates[0],)
    assert result.topology_rejections[0].edge is closer
    assert result.topology_rejections[0].time_distance_seconds == 1.0


def test_attribute_known_loads_suppresses_rejection_for_selected_edge() -> None:
    """A rejected candidate must not diagnose an edge matched to another load."""
    candidate = edge(0, 1000.0, split_phase_type="single_leg_a")
    result = attribute_known_loads(
        [candidate],
        [
            CircuitEvent(
                BASE_TIME,
                "dual",
                EventType.START,
                features={"startup_power_w": 1000.0},
            ),
            CircuitEvent(
                BASE_TIME,
                "single",
                EventType.START,
                features={"startup_power_w": 1000.0},
            ),
        ],
        topology_by_circuit={
            "dual": nilm_domain.KnownLoadTopology(("balanced_240v",)),
            "single": nilm_domain.KnownLoadTopology(("single_leg_a",)),
        },
    )

    assert [match.known_circuit_id for match in result.matched_edges] == ["single"]
    assert result.unmatched_edges == ()
    assert result.topology_rejections == ()


def test_attribute_known_loads_global_assignment_beats_greedy() -> None:
    topology = nilm_domain.KnownLoadTopology(("single_leg_a",))
    edge_one = edge(0, 961.5384615, split_phase_type="single_leg_a")
    edge_two = edge(0, 1057.6923077, split_phase_type="single_leg_a")
    event_a = CircuitEvent(
        BASE_TIME,
        "a",
        EventType.START,
        features={"startup_power_w": 1000.0},
    )
    event_b = CircuitEvent(
        BASE_TIME,
        "b",
        EventType.START,
        features={"startup_power_w": 892.8571429},
    )

    result = attribute_known_loads(
        [edge_one, edge_two],
        [event_a, event_b],
        topology_by_circuit={"a": topology, "b": topology},
    )

    assert [(match.edge, match.known_circuit_id) for match in result.matched_edges] == [
        (edge_one, "b"),
        (edge_two, "a"),
    ]
    assert [match.confidence for match in result.matched_edges] == pytest.approx(
        [0.80, 0.85]
    )


def test_attribute_known_loads_never_reuses_an_edge_or_event() -> None:
    topology = nilm_domain.KnownLoadTopology(("single_leg_a",))
    edges = [
        edge(0, 961.5384615, split_phase_type="single_leg_a"),
        edge(0, 1057.6923077, split_phase_type="single_leg_a"),
    ]
    events = [
        CircuitEvent(
            BASE_TIME,
            "a",
            EventType.START,
            features={"startup_power_w": 1000.0},
        ),
        CircuitEvent(
            BASE_TIME,
            "b",
            EventType.START,
            features={"startup_power_w": 892.8571429},
        ),
    ]

    matches = attribute_known_loads(
        edges,
        events,
        topology_by_circuit={"a": topology, "b": topology},
    ).matched_edges

    assert len({match.edge for match in matches}) == len(matches)
    assert len({match.known_circuit_id for match in matches}) == len(matches)


def test_attribute_known_loads_ambiguity_retains_only_common_pairs() -> None:
    stable = edge(0, 1000.0)
    ambiguous = edge(14, 1000.0)
    events = [
        CircuitEvent(
            BASE_TIME,
            "stable",
            EventType.START,
            features={"startup_power_w": 1000.0},
        ),
        CircuitEvent(
            BASE_TIME + timedelta(seconds=14),
            "choice-a",
            EventType.START,
            features={"startup_power_w": 1000.0},
        ),
        CircuitEvent(
            BASE_TIME + timedelta(seconds=15),
            "choice-b",
            EventType.START,
            features={"startup_power_w": 1000.0},
        ),
    ]

    result = attribute_known_loads([stable, ambiguous], events)

    assert [match.known_circuit_id for match in result.matched_edges] == ["stable"]
    assert result.unmatched_edges == (ambiguous,)
    assert result.ambiguous_edge_count == 1


def test_attribute_known_loads_preserves_stable_edge_order() -> None:
    later = edge(100, 2000.0)
    earlier = edge(0, 1000.0)
    events = [
        CircuitEvent(
            BASE_TIME,
            "earlier",
            EventType.START,
            features={"startup_power_w": 1000.0},
        ),
        CircuitEvent(
            BASE_TIME + timedelta(seconds=100),
            "later",
            EventType.START,
            features={"startup_power_w": 2000.0},
        ),
    ]

    result = attribute_known_loads([later, earlier], events)

    assert [match.edge for match in result.matched_edges] == [later, earlier]
    assert [match.known_circuit_id for match in result.matched_edges] == [
        "later",
        "earlier",
    ]
    assert {match.selection_method for match in result.matched_edges} == {
        "global_assignment"
    }


def test_attribute_known_loads_marks_large_component_greedy_fallback() -> None:
    edges = [edge(index * 15, 1000.0) for index in range(13)]
    events = [
        CircuitEvent(
            BASE_TIME + timedelta(seconds=index * 15),
            f"load-{index}",
            EventType.START,
            features={"startup_power_w": 1000.0},
        )
        for index in range(13)
    ]

    result = attribute_known_loads(edges, events)

    assert len(result.matched_edges) == 13
    assert {match.selection_method for match in result.matched_edges} == {
        "greedy_fallback"
    }
    assert result.ambiguous_edge_count == 0


def test_attribute_known_loads_fallback_rejects_local_candidate_ambiguity() -> None:
    edges = [edge(index * 15, 1000.0) for index in range(13)]
    events = [
        CircuitEvent(
            BASE_TIME + timedelta(seconds=index * 15),
            f"load-{index}",
            EventType.START,
            features={"startup_power_w": 1000.0},
        )
        for index in range(13)
    ]
    events.append(
        CircuitEvent(
            BASE_TIME + timedelta(seconds=1),
            "load-ambiguous",
            EventType.START,
            features={"startup_power_w": 1000.0},
        )
    )

    result = attribute_known_loads(edges, events)

    assert result.unmatched_edges == (edges[0],)
    assert result.ambiguous_edge_count == 1
    assert len(result.matched_edges) == 12
    assert {match.selection_method for match in result.matched_edges} == {
        "greedy_fallback"
    }


def test_cluster_recurring_signatures_groups_similar_edges_conservatively() -> None:
    signatures = cluster_recurring_signatures(
        [
            edge(0, 300.0, delta_var=35.0, direction="on"),
            edge(30, 315.0, delta_var=38.0, direction="on"),
            edge(60, 288.0, delta_var=31.0, direction="on"),
            edge(90, -300.0, delta_var=-35.0, direction="off"),
            edge(120, 900.0, delta_var=300.0, direction="on"),
        ]
    )

    assert len(signatures) == 1
    assert signatures[0].occurrence_count == 3
    assert signatures[0].median_delta_w == 300.0
    assert signatures[0].median_delta_var == 35.0
    assert signatures[0].confidence_kind == "evidence"
    assert 0.0 <= signatures[0].confidence <= 0.75


def test_cluster_recurring_signatures_separates_same_w_by_apparent_power() -> None:
    signatures = cluster_recurring_signatures(
        [
            *[
                edge(
                    index * 30,
                    300.0,
                    delta_var=40.0,
                    delta_va=320.0,
                )
                for index in range(3)
            ],
            *[
                edge(
                    100 + index * 30,
                    300.0,
                    delta_var=40.0,
                    delta_va=600.0,
                )
                for index in range(3)
            ],
        ]
    )

    assert len(signatures) == 2
    assert {signature.median_delta_va for signature in signatures} == {320.0, 600.0}


def test_cluster_recurring_signatures_prevents_reactive_chain_bridge() -> None:
    signatures = cluster_recurring_signatures(
        [
            *[edge(index * 30, 500.0, delta_var=100.0) for index in range(3)],
            *[edge(100 + index * 30, 500.0, delta_var=150.0) for index in range(3)],
            *[edge(200 + index * 30, 500.0, delta_var=225.0) for index in range(3)],
        ]
    )

    assert [signature.occurrence_count for signature in signatures] == [3, 3, 3]
    assert [signature.median_delta_var for signature in signatures] == [
        100.0,
        150.0,
        225.0,
    ]


def test_cluster_recurring_signatures_keeps_ambiguous_w_only_edges_uncertain() -> None:
    signatures = cluster_recurring_signatures(
        [
            *[edge(index * 30, 500.0, delta_var=25.0) for index in range(3)],
            *[edge(100 + index * 30, 500.0, delta_var=125.0) for index in range(3)],
            *[
                edge(
                    200 + index * 30,
                    500.0,
                    delta_var=None,
                    delta_va=None,
                    delta_pf=None,
                )
                for index in range(3)
            ],
        ]
    )

    assert [signature.median_delta_var for signature in signatures] == [
        25.0,
        125.0,
        None,
    ]
    assert [signature.occurrence_count for signature in signatures] == [3, 3, 3]


def test_cluster_recurring_signatures_uses_nearest_unique_candidate() -> None:
    signatures = cluster_recurring_signatures(
        [
            *[edge(index * 30, 500.0, delta_var=25.0) for index in range(3)],
            *[edge(100 + index * 30, 500.0, delta_var=125.0) for index in range(3)],
            *[edge(200 + index * 30, 500.0, delta_var=30.0) for index in range(3)],
        ]
    )

    assert [(item.median_delta_var, item.occurrence_count) for item in signatures] == [
        (27.5, 6),
        (125.0, 3),
    ]


def test_signature_confidence_uses_days_dispersion_and_on_off_support() -> None:
    one_day = cluster_recurring_signatures(
        [edge(index * 60, 300.0, delta_var=20.0) for index in range(3)]
    )[0]
    multi_day = cluster_recurring_signatures(
        [edge(index * 86_400, 300.0, delta_var=20.0) for index in range(3)]
    )[0]
    dispersed = cluster_recurring_signatures(
        [
            edge(0, 288.0, delta_var=20.0),
            edge(60, 300.0, delta_var=20.0),
            edge(120, 315.0, delta_var=20.0),
        ]
    )[0]
    paired = cluster_recurring_signatures(
        [
            event
            for index in range(3)
            for event in (
                edge(index * 86_400, 300.0, delta_var=20.0),
                edge(index * 86_400 + 3_600, -300.0, delta_var=-20.0),
            )
        ]
    )
    paired_on = next(item for item in paired if item.signature_id.startswith("on-"))

    assert one_day.unique_day_count == 1
    assert one_day.confidence <= 0.65
    assert multi_day.confidence > one_day.confidence
    assert dispersed.normalized_cluster_radius > multi_day.normalized_cluster_radius
    assert dispersed.confidence < multi_day.confidence
    assert paired_on.paired_occurrence_count == 3
    assert paired_on.on_off_support == 1.0
    assert paired_on.confidence > multi_day.confidence
    assert all(0.0 <= item.confidence <= 0.95 for item in paired)


def test_w_only_signatures_keep_missing_features_and_still_pair() -> None:
    signatures = cluster_recurring_signatures(
        [
            edge(index * 30, 300.0, delta_var=None, delta_va=None, delta_pf=None)
            for index in range(3)
        ]
    )

    assert len(signatures) == 1
    assert signatures[0].median_delta_var is None
    assert signatures[0].median_delta_va is None
    assert signatures[0].median_delta_pf is None
    assert "var=unknown" in nilm_domain.nilm_signature_fingerprint(signatures[0])

    sessions = pair_nilm_sessions_for_signatures(
        [
            edge(0, 300.0, delta_var=None, delta_va=None, delta_pf=None),
            edge(60, -300.0, delta_var=None, delta_va=None, delta_pf=None),
        ],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "w-only",
                "median_delta_w": 300.0,
            }
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is not None


def test_expected_assignments_are_modeled_but_ignored_assignments_are_not() -> None:
    signatures = [
        {"signature_id": "expected", "median_delta_w": 300.0},
        {"signature_id": "ignored", "median_delta_w": 300.0},
    ]
    assignments = [
        {
            "assignment_id": "expected-assignment",
            "lifecycle_state": "expected",
            "signature_fingerprints": ["expected"],
        },
        {
            "assignment_id": "ignored-assignment",
            "lifecycle_state": "ignored",
            "signature_fingerprints": ["ignored"],
        },
    ]

    assert _nilm_session_specs(signatures, assignments) == [
        ("expected", "expected-assignment")
    ]

    expected = assignment_model(
        "expected-assignment",
        transition("expected-assignment", 300.0),
        lifecycle_state="expected",
    )
    ignored = assignment_model(
        "ignored-assignment",
        transition("ignored-assignment", 300.0),
        lifecycle_state="ignored",
    )
    assert reconcile(edge(0, 300.0), [expected], {"expected-assignment": 0.0}).accepted
    assert not reconcile(
        edge(0, 300.0), [ignored], {"ignored-assignment": 0.0}
    ).accepted


def test_cluster_recurring_signatures_keeps_split_phase_topologies_separate() -> None:
    signatures = cluster_recurring_signatures(
        [
            edge(
                0,
                600.0,
                leg_a_delta_w=600.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                30,
                610.0,
                leg_a_delta_w=610.0,
                leg_b_delta_w=5.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                60,
                590.0,
                leg_a_delta_w=590.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                90,
                600.0,
                leg_a_delta_w=300.0,
                leg_b_delta_w=300.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                120,
                620.0,
                leg_a_delta_w=310.0,
                leg_b_delta_w=310.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                150,
                580.0,
                leg_a_delta_w=290.0,
                leg_b_delta_w=290.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
        ]
    )

    by_topology = {signature.split_phase_type: signature for signature in signatures}
    assert set(by_topology) == {"single_leg_a", "balanced_240v"}
    assert by_topology["single_leg_a"].median_leg_a_delta_w == 600.0
    assert by_topology["single_leg_a"].median_leg_b_delta_w == 0.0
    assert by_topology["balanced_240v"].median_leg_a_delta_w == 300.0
    assert by_topology["balanced_240v"].median_leg_b_delta_w == 300.0


def test_cluster_recurring_signatures_does_not_let_unknown_bridge_topologies() -> None:
    signatures = cluster_recurring_signatures(
        [
            edge(
                0,
                600.0,
                leg_a_delta_w=600.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                30,
                605.0,
                split_phase_type="unknown",
                dominant_leg="unknown",
            ),
            edge(
                60,
                590.0,
                leg_a_delta_w=590.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                90,
                600.0,
                leg_a_delta_w=300.0,
                leg_b_delta_w=300.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                120,
                610.0,
                leg_a_delta_w=305.0,
                leg_b_delta_w=305.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                150,
                580.0,
                leg_a_delta_w=290.0,
                leg_b_delta_w=290.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
        ]
    )

    by_topology = {signature.split_phase_type: signature for signature in signatures}
    assert set(by_topology) == {"balanced_240v"}
    assert by_topology["balanced_240v"].median_leg_a_delta_w == 300.0
    assert by_topology["balanced_240v"].median_leg_b_delta_w == 300.0


def test_cluster_recurring_signatures_blocks_unknown_seed_bridge() -> None:
    signatures = cluster_recurring_signatures(
        [
            edge(
                0,
                605.0,
                split_phase_type="unknown",
                dominant_leg="unknown",
            ),
            edge(
                30,
                600.0,
                leg_a_delta_w=600.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                60,
                590.0,
                leg_a_delta_w=590.0,
                leg_b_delta_w=0.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                90,
                610.0,
                leg_a_delta_w=610.0,
                leg_b_delta_w=5.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            edge(
                120,
                600.0,
                leg_a_delta_w=300.0,
                leg_b_delta_w=300.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                150,
                610.0,
                leg_a_delta_w=305.0,
                leg_b_delta_w=305.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
            edge(
                180,
                580.0,
                leg_a_delta_w=290.0,
                leg_b_delta_w=290.0,
                split_phase_type="balanced_240v",
                dominant_leg="balanced",
            ),
        ]
    )

    by_topology = {signature.split_phase_type: signature for signature in signatures}
    assert set(by_topology) == {"single_leg_a", "balanced_240v"}
    assert by_topology["single_leg_a"].occurrence_count == 3
    assert by_topology["balanced_240v"].occurrence_count == 3


def test_cluster_recurring_signatures_is_stable_for_permuted_similar_edges() -> None:
    first_order = cluster_recurring_signatures(
        [
            edge(0, 121.0, delta_var=10.0),
            edge(30, 100.0, delta_var=8.0),
            edge(60, 125.0, delta_var=12.0),
        ]
    )
    second_order = cluster_recurring_signatures(
        [
            edge(30, 100.0, delta_var=8.0),
            edge(60, 125.0, delta_var=12.0),
            edge(0, 121.0, delta_var=10.0),
        ]
    )

    assert first_order == second_order
    assert len(first_order) == 1
    assert first_order[0].median_delta_w == 121.0


def test_nilm_signature_fingerprint_ignores_cluster_order_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        nilm_signature_fingerprint,
    )

    first = NilmSignature(
        signature_id="on-1",
        median_delta_w=612.0,
        median_delta_var=142.0,
        median_delta_va=628.0,
        median_delta_pf=-0.03,
        occurrence_count=3,
        confidence=0.7,
        median_leg_a_delta_w=610.0,
        median_leg_b_delta_w=15.0,
        leg_balance_ratio=0.95,
        dominant_leg="a",
        split_phase_type="single_leg_a",
    )
    reordered = NilmSignature(
        signature_id="on-2",
        median_delta_w=625.0,
        median_delta_var=148.0,
        median_delta_va=638.0,
        median_delta_pf=-0.03,
        occurrence_count=6,
        confidence=0.9,
        median_leg_a_delta_w=625.0,
        median_leg_b_delta_w=18.0,
        leg_balance_ratio=0.94,
        dominant_leg="a",
        split_phase_type="single_leg_a",
    )
    off_signature = NilmSignature(
        signature_id="off-1",
        median_delta_w=-618.0,
        median_delta_var=-146.0,
        median_delta_va=-632.0,
        median_delta_pf=0.03,
        occurrence_count=3,
        confidence=0.7,
        dominant_leg="a",
        split_phase_type="single_leg_a",
    )

    assert nilm_signature_fingerprint(first) == nilm_signature_fingerprint(reordered)
    assert nilm_signature_fingerprint(first) != nilm_signature_fingerprint(
        off_signature
    )


def test_nilm_signature_fingerprint_v2_splits_legacy_reactive_collision() -> None:
    first = NilmSignature("on-1", 500.0, 100.0, occurrence_count=3)
    second = NilmSignature("on-2", 500.0, 150.0, occurrence_count=3)

    assert nilm_domain.nilm_signature_fingerprint_v1(first) == (
        nilm_domain.nilm_signature_fingerprint_v1(second)
    )
    assert nilm_domain.nilm_signature_fingerprint(first) != (
        nilm_domain.nilm_signature_fingerprint(second)
    )
    assert "revision=2" in nilm_domain.nilm_signature_fingerprint(first)


def test_legacy_fingerprint_resolves_unique_w_direction_despite_var_drift() -> None:
    current = NilmSignature(
        "off-1",
        -84.0,
        -145.0,
        -168.0,
        0.12,
        8,
        0.9,
    )
    current_fingerprint = nilm_domain.nilm_signature_fingerprint(current)

    resolved = nilm_domain.resolve_nilm_signature_fingerprint(
        "direction=off|watts=0-100|var=0-100|va=0-100|pf=0.00-0.05|"
        "split=unknown|leg=unknown|balance=unknown",
        [
            {
                "signature_id": "off-1",
                "feedback_fingerprint": current_fingerprint,
                "signature_fingerprint": current_fingerprint,
            }
        ],
    )

    assert resolved == current_fingerprint


def test_legacy_fingerprint_does_not_cross_known_split_phase_topology() -> None:
    assert (
        nilm_domain.resolve_nilm_signature_fingerprint(
            "direction=on|watts=0-100|var=unknown|va=unknown|pf=unknown|"
            "split=single_leg_a|leg=a|balance=unknown",
            [
                {
                    "signature_id": "on-1",
                    "feedback_fingerprint": (
                        "direction=on|watts=0-100|var=100-200|va=unknown|pf=unknown|"
                        "split=single_leg_b|leg=b|balance=unknown"
                    ),
                }
            ],
        )
        is None
    )


def test_legacy_fingerprint_does_not_resolve_ambiguous_same_w_components() -> None:
    signatures = [
        NilmSignature("on-1", 84.0, 20.0, 86.0, 0.0, 8, 0.9),
        NilmSignature("on-2", 83.0, 95.0, 126.0, 0.0, 8, 0.9),
    ]
    payloads = [
        {
            "signature_id": signature.signature_id,
            "feedback_fingerprint": nilm_domain.nilm_signature_fingerprint(signature),
        }
        for signature in signatures
    ]

    assert (
        nilm_domain.resolve_nilm_signature_fingerprint(
            "direction=on|watts=0-100|var=unknown|va=unknown|pf=unknown|"
            "split=unknown|leg=unknown|balance=unknown",
            payloads,
        )
        is None
    )


def test_session_specs_reject_off_only_assignment_fingerprint() -> None:
    current = NilmSignature("off-1", -84.0, -145.0, -168.0, 0.12, 8, 0.9)
    current_fingerprint = nilm_domain.nilm_signature_fingerprint(current)

    assert (
        _nilm_session_specs(
            [
                {
                    "signature_id": "off-1",
                    "feedback_fingerprint": current_fingerprint,
                    "median_delta_w": -84.0,
                }
            ],
            [
                {
                    "assignment_id": "pump",
                    "lifecycle_state": "published",
                    "signature_fingerprints": [
                        "direction=off|watts=0-100|var=0-100|va=0-100|"
                        "pf=0.00-0.05|split=unknown|leg=unknown|balance=unknown"
                    ],
                }
            ],
        )
        == []
    )


def test_virtual_assignment_sessions_resolve_unique_legacy_fingerprint() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        _nilm_assignment_sessions,
    )

    signature = NilmSignature("on-1", 300.0, 20.0, occurrence_count=3)
    fingerprint = nilm_domain.nilm_signature_fingerprint(signature)
    legacy = nilm_domain.nilm_signature_fingerprint_v1(signature)
    payload = {
        "signature_id": signature.signature_id,
        "feedback_fingerprint": fingerprint,
        "legacy_feedback_fingerprint": legacy,
        "median_delta_w": signature.median_delta_w,
        "median_delta_var": signature.median_delta_var,
    }

    sessions = _nilm_assignment_sessions(
        "mains",
        [{"assignment_id": "pump", "signature_fingerprints": [legacy]}],
        [edge(0, 300.0, delta_var=20.0), edge(60, -300.0, delta_var=-20.0)],
        {signature.signature_id: payload, fingerprint: payload},
    )

    assert len(sessions) == 1
    assert sessions[0].assignment_id == "pump"
    assert sessions[0].signature_fingerprint == fingerprint


def test_classify_signature_is_conservative_and_allows_user_label_override() -> None:
    assert (
        classify_signature(
            NilmSignature(
                signature_id="custom",
                median_delta_w=120.0,
                median_delta_var=5.0,
                median_delta_va=121.0,
                median_delta_pf=0.0,
                occurrence_count=3,
                confidence=0.6,
                user_label="Dehumidifier",
            )
        )
        == "Dehumidifier"
    )
    assert (
        classify_signature(NilmSignature("resistive", 500.0, 10.0, 501.0, 0.0, 4, 0.7))
        == "possible resistive load"
    )
    assert (
        classify_signature(
            NilmSignature(
                signature_id="watts-only",
                median_delta_w=500.0,
                occurrence_count=4,
                confidence=0.7,
            )
        )
        == "unknown recurring load"
    )
    assert (
        classify_signature(
            NilmSignature(
                "balanced",
                500.0,
                10.0,
                501.0,
                0.0,
                4,
                0.7,
                split_phase_type="balanced_240v",
            )
        )
        == "possible 240 V resistive load"
    )
    assert (
        classify_signature(
            NilmSignature(
                "single",
                500.0,
                220.0,
                548.0,
                -0.18,
                4,
                0.7,
                split_phase_type="single_leg_b",
            )
        )
        == "possible 120 V motor-like load"
    )
    assert (
        classify_signature(NilmSignature("motor", 500.0, 220.0, 548.0, -0.18, 4, 0.7))
        == "possible motor-like load"
    )
    assert (
        classify_signature(
            NilmSignature("electronics", 80.0, 90.0, 125.0, -0.25, 4, 0.7)
        )
        == "possible power-electronics load"
    )
    assert (
        classify_signature(NilmSignature("unknown", 120.0, 30.0, 124.0, 0.01, 4, 0.7))
        == "unknown recurring load"
    )


def test_unmatched_load_percentage_returns_zero_for_zero_total() -> None:
    assert unmatched_load_percentage(0, 4) == 0.0
    assert unmatched_load_percentage(10, 3) == 30.0


def test_global_session_pairing_assigns_each_edge_pair_once() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 150.0), edge(300, -150.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {"signature_fingerprint": "120-w", "typical_watts": 120.0},
            {"signature_fingerprint": "187-w", "typical_watts": 187.0},
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].signature_fingerprint == "120-w"
    assert sessions[0].off_edge_id is not None


def test_global_session_pairing_records_close_signature_match_as_ambiguous() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 125.0), edge(300, -125.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {"signature_fingerprint": "120-w", "typical_watts": 120.0},
            {"signature_fingerprint": "130-w", "typical_watts": 130.0},
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is not None
    assert sessions[0].ambiguous is True
    assert sessions[0].assignment_id is None


def test_global_session_pairing_does_not_replace_better_unassigned_match() -> None:
    signature_specs = [
        {"signature_fingerprint": "unassigned-500", "typical_watts": 500.0},
        {
            "signature_fingerprint": "assigned-510",
            "typical_watts": 510.0,
            "assignment_id": "dryer",
        },
    ]
    closed = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0)],
        mains_circuit_id="mains",
        signature_specs=signature_specs,
    )[0]
    opened = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0)],
        mains_circuit_id="mains",
        signature_specs=signature_specs,
    )[0]

    assert closed.signature_fingerprint == "unassigned-500"
    assert closed.ambiguous is True
    assert closed.assignment_id is None
    assert opened.signature_fingerprint == "unassigned-500"
    assert opened.ambiguous is True
    assert opened.assignment_id is None


def test_global_session_pairing_keeps_open_below_ambiguous_pair_confidence() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0)] + [edge(seconds, -500.0) for seconds in range(300, 1801, 300)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "load-a",
                "typical_watts": 500.0,
                "assignment_id": "load-a",
            },
            {
                "signature_fingerprint": "load-b",
                "typical_watts": 500.0,
                "assignment_id": "load-b",
            },
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].end is None
    assert sessions[0].assignment_id is None


def test_global_session_pairing_preserves_earlier_owner_ambiguous_pair() -> None:
    session = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0), edge(600, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "load-a",
                "typical_watts": 500.0,
                "assignment_id": "load-a",
            },
            {
                "signature_fingerprint": "load-b",
                "typical_watts": 500.0,
                "assignment_id": "load-b",
                "max_duration_seconds": 400.0,
            },
        ],
    )[0]

    assert session.end == BASE_TIME + timedelta(seconds=300)
    assert session.ambiguous is True
    assert session.assignment_id is None


def test_global_session_pairing_rejects_assigned_off_signature() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "off-500",
                "assignment_id": "dryer",
            },
            {
                "signature_fingerprint": "on-500",
                "median_delta_w": 500.0,
            },
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].signature_fingerprint == "on-500"
    assert sessions[0].assignment_id is None


def test_global_session_pairing_deduplicates_same_assignment_signatures() -> None:
    signature_specs = [
        {
            "signature_fingerprint": "on-500",
            "median_delta_w": 500.0,
            "assignment_id": "dryer",
        },
        {
            "signature_fingerprint": "off-500",
            "median_delta_w": -500.0,
            "assignment_id": "dryer",
        },
    ]
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0)],
        mains_circuit_id="mains",
        signature_specs=signature_specs,
    )

    assert len(sessions) == 1
    assert sessions[0].assignment_id == "dryer"
    assert sessions[0].ambiguous is False

    open_sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0)],
        mains_circuit_id="mains",
        signature_specs=signature_specs,
    )

    assert len(open_sessions) == 1
    assert open_sessions[0].assignment_id == "dryer"


def test_global_session_pairing_marks_alternate_off_edge_ambiguity() -> None:
    spec = {
        "signature_fingerprint": "dryer",
        "typical_watts": 500.0,
        "assignment_id": "dryer",
    }
    simple = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[spec],
    )[0]
    ambiguous = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0), edge(600, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[spec],
    )[0]

    assert ambiguous.ambiguous is True
    assert ambiguous.alternate_match_count == 1
    assert ambiguous.confidence < simple.confidence


def test_global_session_pairing_clears_owner_across_assignment_alternates() -> None:
    session = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0), edge(600, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "load-a",
                "typical_watts": 500.0,
                "assignment_id": "load-a",
                "max_duration_seconds": 400.0,
            },
            {
                "signature_fingerprint": "load-b",
                "typical_watts": 500.0,
                "assignment_id": "load-b",
                "min_duration_seconds": 500.0,
            },
        ],
    )[0]

    assert session.ambiguous is True
    assert session.assignment_id is None


def test_global_session_pairing_keeps_open_below_penalized_confidence() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0)] + [edge(seconds, -500.0) for seconds in range(300, 1801, 300)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "dryer",
                "typical_watts": 500.0,
                "assignment_id": "dryer",
            }
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].assignment_id == "dryer"
    assert sessions[0].end is None


def test_global_session_pairing_opens_on_edge_after_off_edge_is_consumed() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, 500.0), edge(600, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "dryer",
                "typical_watts": 500.0,
                "assignment_id": "dryer",
            }
        ],
    )

    assert len(sessions) == 2
    assert sessions[0].start == BASE_TIME
    assert sessions[0].end == BASE_TIME + timedelta(seconds=600)
    assert sessions[1].start == BASE_TIME + timedelta(seconds=300)
    assert sessions[1].end is None


def test_global_session_pairing_closes_overlapping_runs() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [
            edge(0, 500.0),
            edge(300, 500.0),
            edge(600, -500.0),
            edge(900, -500.0),
        ],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "dryer",
                "typical_watts": 500.0,
                "assignment_id": "dryer",
            }
        ],
    )

    assert [(session.start, session.end) for session in sessions] == [
        (BASE_TIME, BASE_TIME + timedelta(seconds=600)),
        (
            BASE_TIME + timedelta(seconds=300),
            BASE_TIME + timedelta(seconds=900),
        ),
    ]


def test_global_session_pairing_overlapping_different_assignments_have_no_penalty() -> (
    None
):
    sessions = pair_nilm_sessions_for_signatures(
        [
            edge(0, 450.0),
            edge(300, 800.0),
            edge(600, -450.0),
            edge(900, -800.0),
        ],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "blower-450",
                "typical_watts": 450.0,
                "assignment_id": "blower",
            },
            {
                "signature_fingerprint": "condensate-pump-800",
                "typical_watts": 800.0,
                "assignment_id": "condensate-pump",
            },
        ],
    )

    assert [(session.assignment_id, session.overlap_count) for session in sessions] == [
        ("blower", 0),
        ("condensate-pump", 0),
    ]


def test_global_session_pairing_overlapping_same_assignment_keeps_penalty() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [
            edge(0, 500.0),
            edge(300, 500.0),
            edge(600, -500.0),
            edge(900, -500.0),
        ],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "dryer",
                "typical_watts": 500.0,
                "assignment_id": "dryer",
            }
        ],
    )

    assert [session.overlap_count for session in sessions] == [1, 1]
    assert [session.confidence for session in sessions] == [0.765, 0.9]


def test_global_session_pairing_opens_session_beyond_learned_duration() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(3600, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "dryer",
                "typical_watts": 500.0,
                "assignment_id": "dryer",
                "max_duration_seconds": 600.0,
            }
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].assignment_id == "dryer"
    assert sessions[0].end is None


def test_global_session_pairing_rejects_short_closed_transition() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(20, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {"signature_fingerprint": "heater", "typical_watts": 500.0},
        ],
    )

    assert sessions == []


def test_global_session_pairing_uses_reactive_signature_to_choose_owner() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [
            edge(0, 500.0, delta_var=300.0, delta_va=600.0),
            edge(300, -500.0, delta_var=-300.0, delta_va=-600.0),
        ],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "resistive",
                "typical_watts": 500.0,
                "median_delta_var": 0.0,
                "median_delta_va": 500.0,
            },
            {
                "signature_fingerprint": "motor",
                "typical_watts": 500.0,
                "median_delta_var": 300.0,
                "median_delta_va": 600.0,
            },
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].signature_fingerprint == "motor"


def _required_nilm_api(name: str):
    api = getattr(nilm_domain, name, None)
    assert api is not None, f"nilm.{name} is required for canonical appliance identity"
    return api


def _dishwasher_assignment() -> dict[str, object]:
    return {
        "assignment_id": "assignment-dishwasher",
        "appliance_id": "dishwasher",
        "display_name": "Dishwasher",
        "appliance_profile": "dishwasher",
        "mains_circuit_id": "mains",
        "session_ids": ["session-1", "session-2"],
        "confirmed_session_ids": ["session-1"],
        "rejected_session_ids": [],
        "adjusted_session_ids": [],
        "confidence": 0.84,
        "publish_entities": True,
    }


def test_nilm_appliance_identity_keeps_logical_assignment_and_source_ids_separate() -> (
    None
):
    identity_type = _required_nilm_api("NilmApplianceIdentity")
    build_identity = _required_nilm_api("build_nilm_appliance_identity")

    identity = build_identity(
        _dishwasher_assignment(),
        mains_source_entity_id="sensor.panel_mains_power",
    )

    assert isinstance(identity, identity_type)
    assert identity.appliance_key == "nilm:assignment-dishwasher"
    assert identity.assignment_id == "assignment-dishwasher"
    assert identity.appliance_id == "dishwasher"
    assert identity.display_name == "Dishwasher"
    assert identity.appliance_profile == "dishwasher"
    assert identity.mains_circuit_id == "mains"
    assert identity.mains_source_entity_id == "sensor.panel_mains_power"


def test_nilm_assignment_session_summary_excludes_the_mains_and_other_assignments() -> (
    None
):
    summarize_sessions = _required_nilm_api("summarize_nilm_assignment_sessions")
    now = datetime(2026, 7, 13, 16, 0, tzinfo=UTC)
    sessions = [
        {
            "session_id": "session-1",
            "assignment_id": "assignment-dishwasher",
            "start": "2026-07-13T10:00:00+00:00",
            "end": "2026-07-13T10:30:00+00:00",
            "duration_seconds": 1800.0,
            "median_power_w": 800.0,
            "estimated_energy_kwh": 0.4,
            "confidence": 0.88,
        },
        {
            "session_id": "session-2",
            "start": "2026-07-13T14:00:00+00:00",
            "end": "2026-07-13T14:15:00+00:00",
            "duration_seconds": 900.0,
            "median_power_w": 600.0,
            "estimated_energy_kwh": 0.15,
            "confidence": 0.82,
        },
        {
            "session_id": "other-session",
            "assignment_id": "assignment-dryer",
            "start": "2026-07-13T11:00:00+00:00",
            "end": "2026-07-13T12:00:00+00:00",
            "duration_seconds": 3600.0,
            "estimated_energy_kwh": 4.0,
        },
        {
            "session_id": "mains-session",
            "start": "2026-07-13T08:00:00+00:00",
            "end": "2026-07-13T16:00:00+00:00",
            "duration_seconds": 28800.0,
            "estimated_energy_kwh": 20.0,
        },
    ]

    summary = summarize_sessions(
        _dishwasher_assignment(),
        sessions,
        now=now,
        time_zone="UTC",
    )

    assert [item["session_id"] for item in summary["sessions"]] == [
        "session-1",
        "session-2",
    ]
    assert summary["runtime_today_seconds"] == 2700.0
    assert summary["run_count_today"] == 2
    assert summary["estimated_energy_today_kwh"] == 0.55
    assert summary["last_matched_session_id"] == "session-2"


def test_rejected_nilm_session_stays_in_history_but_not_attributed_metrics() -> None:
    summarize_sessions = _required_nilm_api("summarize_nilm_assignment_sessions")
    assignment = _dishwasher_assignment()
    assignment["session_ids"] = ["session-rejected", "session-confirmed"]
    assignment["rejected_session_ids"] = ["session-rejected"]
    sessions = [
        {
            "session_id": "session-rejected",
            "assignment_id": "assignment-dishwasher",
            "start": "2026-07-13T10:00:00+00:00",
            "end": None,
            "median_power_w": 2000.0,
        },
        {
            "session_id": "session-confirmed",
            "assignment_id": "assignment-dishwasher",
            "start": "2026-07-13T08:00:00+00:00",
            "end": "2026-07-13T08:30:00+00:00",
            "estimated_energy_kwh": 0.4,
        },
    ]

    summary = summarize_sessions(
        assignment,
        sessions,
        now=datetime(2026, 7, 13, 11, 0, tzinfo=UTC),
        time_zone="UTC",
    )

    assert {item["session_id"] for item in summary["sessions"]} == {
        "session-rejected",
        "session-confirmed",
    }
    assert summary["runtime_today_seconds"] == 1800.0
    assert summary["run_count_today"] == 1
    assert summary["estimated_energy_today_kwh"] == 0.4
    assert summary["current_session_id"] is None
    assert summary["last_matched_session_id"] == "session-confirmed"


def test_nilm_assignment_runtime_clips_sessions_at_local_midnight() -> None:
    summarize_sessions = _required_nilm_api("summarize_nilm_assignment_sessions")
    assignment = _dishwasher_assignment()
    assignment["session_ids"] = ["session-midnight"]

    summary = summarize_sessions(
        assignment,
        [
            {
                "session_id": "session-midnight",
                "assignment_id": "assignment-dishwasher",
                "start": "2026-07-12T23:50:00+00:00",
                "end": "2026-07-13T00:10:00+00:00",
                "duration_seconds": 1200.0,
                "estimated_energy_kwh": 0.2,
            }
        ],
        now=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        time_zone="UTC",
    )

    assert summary["runtime_today_seconds"] == 600.0
    assert summary["run_count_today"] == 0
    assert summary["estimated_energy_today_kwh"] == 0.1


def test_nilm_open_session_estimates_energy_from_power_and_elapsed_time() -> None:
    summarize_sessions = _required_nilm_api("summarize_nilm_assignment_sessions")
    assignment = _dishwasher_assignment()
    assignment["session_ids"] = ["session-open"]

    summary = summarize_sessions(
        assignment,
        [
            {
                "session_id": "session-open",
                "assignment_id": "assignment-dishwasher",
                "start": "2026-07-13T10:00:00+00:00",
                "end": None,
                "median_power_w": 1000.0,
                "estimated_energy_kwh": 0.0,
            }
        ],
        now=datetime(2026, 7, 13, 11, 0, tzinfo=UTC),
        time_zone="UTC",
    )

    assert summary["runtime_today_seconds"] == 3600.0
    assert summary["estimated_energy_today_kwh"] == 1.0
    assert summary["current_session_duration_seconds"] == 3600.0


@pytest.mark.parametrize(
    ("start", "end", "now", "expected_seconds"),
    [
        (
            "2026-03-08T05:00:00+00:00",
            None,
            datetime(2026, 3, 9, 3, 59, tzinfo=UTC),
            82_740.0,
        ),
        (
            "2026-11-01T04:00:00+00:00",
            None,
            datetime(2026, 11, 2, 4, 59, tzinfo=UTC),
            89_940.0,
        ),
    ],
)
def test_nilm_runtime_uses_elapsed_time_across_dst_days(
    start: str,
    end: str | None,
    now: datetime,
    expected_seconds: float,
) -> None:
    summarize_sessions = _required_nilm_api("summarize_nilm_assignment_sessions")
    assignment = _dishwasher_assignment()
    assignment["session_ids"] = ["session-dst"]

    summary = summarize_sessions(
        assignment,
        [
            {
                "session_id": "session-dst",
                "assignment_id": "assignment-dishwasher",
                "start": start,
                "end": end,
                "estimated_energy_kwh": 1.0,
            }
        ],
        now=now,
        time_zone="America/New_York",
    )

    assert summary["runtime_today_seconds"] == expected_seconds


def test_nilm_alert_payload_targets_appliance_and_keeps_source_evidence_context() -> (
    None
):
    build_identity = _required_nilm_api("build_nilm_appliance_identity")
    build_alert_payload = _required_nilm_api("build_nilm_appliance_alert_payload")
    detail_path = _required_nilm_api("nilm_appliance_detail_path")
    identity = build_identity(
        _dishwasher_assignment(),
        mains_source_entity_id="sensor.panel_mains_power",
    )

    payload = build_alert_payload(
        identity,
        session_id="session-2",
        signature_fingerprint="dishwasher|800w",
    )

    assert payload["primary_target"] == "nilm:assignment-dishwasher"
    assert payload["source_context"] == {
        "mains_circuit_id": "mains",
        "mains_source_entity_id": "sensor.panel_mains_power",
    }
    assert payload["evidence_context"] == {
        "assignment_id": "assignment-dishwasher",
        "session_id": "session-2",
        "signature_fingerprint": "dishwasher|800w",
    }
    assert payload["appliance_detail_path"] == detail_path(identity)


def test_nilm_appliance_detail_route_targets_assignment_instead_of_mains_detail() -> (
    None
):
    build_identity = _required_nilm_api("build_nilm_appliance_identity")
    detail_path = _required_nilm_api("nilm_appliance_detail_path")
    identity = build_identity(
        _dishwasher_assignment(),
        mains_source_entity_id="sensor.panel_mains_power",
    )

    path = detail_path(identity)
    query = parse_qs(urlparse(path).query)

    assert urlparse(path).path == "/circuitsetup-energy-analyzer-evidence"
    assert query == {
        "circuit_id": ["mains"],
        "assignment_id": ["assignment-dishwasher"],
        "nilm_workspace": ["1"],
        "appliance_detail": ["1"],
    }


def test_nilm_today_vs_normal_stays_blocked_below_validation_thresholds() -> None:
    evaluate_readiness = _required_nilm_api("evaluate_nilm_validation_readiness")
    assignment = _dishwasher_assignment()
    assignment.update(
        {
            "confirmed_session_ids": ["session-1", "session-2", "session-3"],
            "rejected_session_ids": ["session-4", "session-5"],
            "confidence": 0.72,
        }
    )
    sessions = [
        {
            "session_id": f"session-{index}",
            "start": f"2026-07-{10 + (index % 2):02d}T12:00:00+00:00",
        }
        for index in range(1, 6)
    ]

    readiness = evaluate_readiness(
        assignment,
        sessions,
        min_confirmed_sessions=5,
        min_distinct_days=3,
        max_false_positive_rate=0.2,
        min_confidence=0.75,
        time_zone="UTC",
    )

    assert readiness["ready"] is False
    assert readiness["today_vs_normal_enabled"] is False
    assert readiness["status"] == "needs_validation"
    assert readiness["confirmed_sessions"] == 3
    assert readiness["distinct_confirmed_days"] == 2
    assert readiness["false_positive_rate"] == 0.4


def test_nilm_today_vs_normal_enables_only_after_all_validation_thresholds() -> None:
    evaluate_readiness = _required_nilm_api("evaluate_nilm_validation_readiness")
    assignment = _dishwasher_assignment()
    assignment.update(
        {
            "confirmed_session_ids": [
                "session-1",
                "session-2",
                "session-3",
                "session-4",
                "session-5",
            ],
            "rejected_session_ids": ["session-6"],
            "confidence": 0.84,
        }
    )
    sessions = [
        {
            "session_id": f"session-{index}",
            "start": f"2026-07-{10 + ((index - 1) % 3):02d}T12:00:00+00:00",
        }
        for index in range(1, 7)
    ]

    readiness = evaluate_readiness(
        assignment,
        sessions,
        min_confirmed_sessions=5,
        min_distinct_days=3,
        max_false_positive_rate=0.2,
        min_confidence=0.75,
        time_zone="UTC",
    )

    assert readiness["ready"] is True
    assert readiness["today_vs_normal_enabled"] is True
    assert readiness["status"] == "ready"
    assert readiness["confirmed_sessions"] == 5
    assert readiness["distinct_confirmed_days"] == 3
    assert readiness["false_positive_rate"] == 0.167
