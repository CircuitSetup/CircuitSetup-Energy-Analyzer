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
        "on", "off"
    ]
    assert model["transition_prototypes"][0]["sample_count"] == 32
    assert model["transition_prototypes"][0]["spread_w"] == 1.0
    assert model["model_confidence"] == 0.9
    assert nilm_assignment_model_is_compound_eligible(model) is True


def test_assignment_model_falls_back_to_legacy_power_and_stable_revision() -> None:
    assignment = {"assignment_id": "pump", "confirmed_session_ids": ["one"]}
    sessions = [{
        "session_id": "one", "assignment_id": "pump",
        "start": "2026-06-01T10:00:00+00:00",
        "end": "2026-06-01T10:05:00+00:00",
        "median_power_w": 83.0, "confidence": 0.8,
    }]

    first = build_nilm_assignment_model(assignment, sessions)
    second = build_nilm_assignment_model({**assignment, **first}, sessions)

    assert first["power_states_w"] == [0.0, 83.0]
    assert first["transition_prototypes"][1]["delta_w"] == -83.0
    assert first["model_confidence"] == 0.267
    assert nilm_assignment_model_is_compound_eligible(first) is False
    assert first["model_revision"] == second["model_revision"] == 1


def test_assignment_model_discards_invalid_before_recent_cap() -> None:
    ids = [f"bad-{index}" for index in range(35)] + ["good"]
    assignment = {"assignment_id": "pump", "confirmed_session_ids": ids}
    sessions = [{
        "session_id": value, "assignment_id": "pump",
        "end": "2026-07-01T10:00:00+00:00", "confidence": 1.0,
    } for value in ids[:-1]] + [{
        "session_id": "good", "assignment_id": "pump",
        "end": "2026-06-01T10:00:00+00:00", "on_delta_w": 80.0,
        "off_delta_w": -80.0, "confidence": 0.9,
    }]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["transition_prototypes"][0]["sample_count"] == 1
    assert model["model_confidence"] == 0.3


def test_assignment_model_tolerates_malformed_optional_fields() -> None:
    assignment = {
        "assignment_id": "pump", "confirmed_session_ids": ["one"],
        "model_revision": 10**10_000, "model_confidence": float("nan"),
        "transition_prototypes": [{"direction": "on", "sample_count": "bad"}],
    }
    model = build_nilm_assignment_model(assignment, [{
        "session_id": "one", "assignment_id": "pump",
        "end": "2026-06-01T10:00:00+00:00", "on_delta_w": 80.0,
        "off_delta_w": -80.0, "confidence": float("nan"),
    }])

    assert model["model_revision"] == 1
    assert model["model_confidence"] == 0.0
    assert nilm_assignment_model_is_compound_eligible(assignment) is False


def test_assignment_model_requires_directional_evidence_and_conservative_confidence(
) -> None:
    session_ids = ["wrong-on", "wrong-off", "valid-a", "valid-b", "valid-c"]
    assignment = {"assignment_id": "pump", "confirmed_session_ids": session_ids}
    sessions = [
        {
            "session_id": "wrong-on", "assignment_id": "pump",
            "end": "2026-07-02T10:00:00+00:00", "on_delta_w": -80.0,
            "off_delta_w": -80.0, "confidence": 1.0,
        },
        {
            "session_id": "wrong-off", "assignment_id": "pump",
            "end": "2026-07-01T10:00:00+00:00", "on_delta_w": 80.0,
            "off_delta_w": 80.0, "confidence": 1.0,
        },
        *[
            {
                "session_id": f"valid-{suffix}", "assignment_id": "pump",
                "end": f"2026-06-0{index}T10:00:00+00:00",
                "on_delta_w": 80.0, "off_delta_w": -80.0,
                **({"confidence": 0.9} if index == 1 else {}),
            }
            for index, suffix in enumerate(("a", "b", "c"), start=1)
        ],
    ]

    model = build_nilm_assignment_model(assignment, sessions)

    assert model["transition_prototypes"][0]["sample_count"] == 3
    assert model["model_confidence"] == 0.0


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
        edge(0, 100), [a, b], {"a": 0.0, "b": 0.0},
        helpers={"a": 0.9, "b": 0.9}, helper_conflict=True,
    )
    assert not result.accepted and result.reason == "helper_conflict"


def test_nilm_independent_helpers_may_support_a_compound() -> None:
    a = assignment_model("a", transition("a", 60))
    b = assignment_model("b", transition("b", 40))

    result = reconcile(
        edge(0, 100), [a, b], {"a": 0.0, "b": 0.0},
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


def test_nilm_three_transition_edge_remains_unknown_and_blocks_allocation() -> None:
    models = [
        assignment_model(name, transition(name, watts))
        for name, watts in (("a", 40), ("b", 30), ("c", 30))
    ]
    result = reconcile(
        edge(0, 100), models, {model.assignment_id: 0.0 for model in models}
    )
    assert not result.accepted and result.reason == "compound_unknown"
    assert result.consistent is False and result.energy_allocation_allowed is False


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


def test_nilm_compound_unknown_check_never_enumerates_beyond_triples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_sizes: list[int] = []

    def bounded_combinations(iterable, size):
        checked_sizes.append(size)
        if size > 3:
            raise AssertionError("compound diagnostics exceeded the three-load bound")
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
    assert max(checked_sizes) == 3


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

    edges = detector.process_many([
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
    ])

    assert len(edges) == 1
    assert edges[0].delta_var == 0.0


def test_confirmed_edge_uses_final_sample_for_delayed_auxiliary_evidence() -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many([
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
    ])

    assert len(edges) == 1
    assert edges[0].timestamp == BASE_TIME + timedelta(seconds=10)
    assert edges[0].delta_w == 195.0
    assert edges[0].delta_var == 45.0
    assert edges[0].delta_va == 105.0
    assert edges[0].delta_pf == pytest.approx(0.95)


def test_edge_detector_discards_auxiliary_evidence_outside_confirmation_window(
) -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_samples=2,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many([
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
    ])

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_var is None
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_derives_va_and_pf_from_synchronized_voltage_current() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many([
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
    ])

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_va == pytest.approx(120.0)
    assert edges[0].delta_pf == pytest.approx(round(200.0 / 240.0, 3))


def test_edge_detector_rejects_derived_evidence_when_voltage_is_out_of_window(
) -> None:
    detector = NilmEdgeDetector(
        min_delta_w=100.0,
        confirmation_max_interval=timedelta(seconds=15),
    )

    edges = detector.process_many([
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
    ])

    assert len(edges) == 1
    assert edges[0].delta_w == 200.0
    assert edges[0].delta_va is None
    assert edges[0].delta_pf is None


def test_edge_detector_does_not_use_conflicting_va_as_strong_evidence() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many([
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
    ])

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
    assert result.matched_edges[0].confidence > 0.9
    assert result.unmatched_edges == (edge(40, 325.0),)


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
    assert signatures[0].confidence >= 0.6


def test_cluster_recurring_signatures_separates_same_w_by_apparent_power() -> None:
    signatures = cluster_recurring_signatures([
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
    ])

    assert len(signatures) == 2
    assert {signature.median_delta_va for signature in signatures} == {320.0, 600.0}


def test_cluster_recurring_signatures_does_not_bridge_distinct_reactive_loads(
) -> None:
    signatures = cluster_recurring_signatures([
        *[
            edge(index * 30, 500.0, delta_var=100.0)
            for index in range(3)
        ],
        *[
            edge(100 + index * 30, 500.0, delta_var=150.0)
            for index in range(3)
        ],
        *[
            edge(200 + index * 30, 500.0, delta_var=225.0)
            for index in range(3)
        ],
    ])

    assert [signature.occurrence_count for signature in signatures] == [6, 3]
    assert [signature.median_delta_var for signature in signatures] == [125.0, 225.0]


def test_w_only_signatures_keep_missing_features_and_still_pair() -> None:
    signatures = cluster_recurring_signatures([
        edge(index * 30, 300.0, delta_var=None, delta_va=None, delta_pf=None)
        for index in range(3)
    ])

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
        signature_specs=[{
            "signature_fingerprint": "w-only",
            "median_delta_w": 300.0,
        }],
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
            edge(60, 144.0, delta_var=12.0),
        ]
    )
    second_order = cluster_recurring_signatures(
        [
            edge(30, 100.0, delta_var=8.0),
            edge(60, 144.0, delta_var=12.0),
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
        median_delta_var=151.0,
        median_delta_va=638.0,
        median_delta_pf=-0.02,
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
        == "possible resistive load"
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


def test_global_session_pairing_keeps_assigned_off_signature() -> None:
    sessions = pair_nilm_sessions_for_signatures(
        [edge(0, 500.0), edge(300, -500.0)],
        mains_circuit_id="mains",
        signature_specs=[
            {
                "signature_fingerprint": "off-500",
                "median_delta_w": -500.0,
                "assignment_id": "dryer",
            },
            {
                "signature_fingerprint": "on-500",
                "median_delta_w": 500.0,
            },
        ],
    )

    assert len(sessions) == 1
    assert sessions[0].signature_fingerprint == "off-500"
    assert sessions[0].assignment_id == "dryer"


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
