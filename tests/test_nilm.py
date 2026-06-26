from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
    CircuitSample,
    EventType,
)
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmEdge,
    NilmEdgeDetector,
    NilmSession,
    NilmSignature,
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
    pair_nilm_sessions,
    unmatched_load_percentage,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)

BASE_TIME = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


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


def edge(
    seconds: int,
    delta_w: float,
    *,
    delta_var: float = 0.0,
    delta_va: float | None = None,
    delta_pf: float = 0.0,
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
        delta_va=delta_va if delta_va is not None else delta_w,
        delta_pf=delta_pf,
        direction=direction or ("on" if delta_w > 0 else "off"),
        leg_a_delta_w=leg_a_delta_w,
        leg_b_delta_w=leg_b_delta_w,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
    )


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
    assert classify_signature(
        NilmSignature("resistive", 500.0, 10.0, 501.0, 0.0, 4, 0.7)
    ) == "possible resistive load"
    assert classify_signature(
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
    ) == "possible 240 V resistive load"
    assert classify_signature(
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
    ) == "possible 120 V motor-like load"
    assert classify_signature(
        NilmSignature("motor", 500.0, 220.0, 548.0, -0.18, 4, 0.7)
    ) == "possible motor-like load"
    assert classify_signature(
        NilmSignature("electronics", 80.0, 90.0, 125.0, -0.25, 4, 0.7)
    ) == "possible power-electronics load"
    assert classify_signature(
        NilmSignature("unknown", 120.0, 30.0, 124.0, 0.01, 4, 0.7)
    ) == "unknown recurring load"


def test_unmatched_load_percentage_returns_zero_for_zero_total() -> None:
    assert unmatched_load_percentage(0, 4) == 0.0
    assert unmatched_load_percentage(10, 3) == 30.0


def test_pair_nilm_sessions_pairs_simple_on_off_edges() -> None:
    sessions = pair_nilm_sessions(
        [edge(0, 820.0, delta_var=120.0), edge(2700, -810.0, delta_var=-115.0)],
        mains_circuit_id="mains",
        signature_fingerprint="dishwasher",
    )

    assert len(sessions) == 1
    session = sessions[0]
    assert isinstance(session, NilmSession)
    assert session.mains_circuit_id == "mains"
    assert session.signature_fingerprint == "dishwasher"
    assert session.start == BASE_TIME
    assert session.end == BASE_TIME + timedelta(seconds=2700)
    assert session.duration_seconds == 2700.0
    assert session.median_power_w == 815.0
    assert session.estimated_energy_kwh == 0.611
    assert session.confidence > 0.85
    assert session.off_edge_id is not None


def test_pair_nilm_sessions_leaves_missing_off_edge_open() -> None:
    sessions = pair_nilm_sessions(
        [edge(0, 600.0)],
        mains_circuit_id="mains",
        signature_fingerprint="pump",
    )

    assert len(sessions) == 1
    session = sessions[0]
    assert session.end is None
    assert session.off_edge_id is None
    assert session.duration_seconds is None
    assert session.estimated_energy_kwh == 0.0
    assert session.confidence < 0.5


def test_pair_nilm_sessions_ignores_orphan_off_edge() -> None:
    assert (
        pair_nilm_sessions(
            [edge(0, -600.0)],
            mains_circuit_id="mains",
            signature_fingerprint="pump",
        )
        == []
    )


def test_pair_nilm_sessions_rejects_low_confidence_watt_mismatch() -> None:
    sessions = pair_nilm_sessions(
        [edge(0, 900.0), edge(1800, -420.0)],
        mains_circuit_id="mains",
        signature_fingerprint="dryer",
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is None
    assert sessions[0].confidence < 0.5


def test_pair_nilm_sessions_rejects_present_reactive_mismatch() -> None:
    sessions = pair_nilm_sessions(
        [
            edge(0, 800.0, delta_var=500.0, delta_va=943.0),
            edge(1800, -800.0, delta_var=0.0, delta_va=-943.0),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="reactive-mismatch",
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is None
    assert sessions[0].confidence < 0.5


def test_pair_nilm_sessions_rejects_watt_boundary_without_optional_support() -> None:
    sessions = pair_nilm_sessions(
        [
            edge(0, 800.0, delta_va=0.0),
            edge(1800, -600.0, delta_va=0.0),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="weak-match",
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is None
    assert sessions[0].confidence < 0.5


def test_pair_nilm_sessions_prefers_close_before_next_on() -> None:
    sessions = pair_nilm_sessions(
        [
            edge(0, 800.0),
            edge(300, -780.0),
            edge(600, 800.0),
            edge(900, -800.0),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="repeated-cycle",
    )

    assert len(sessions) == 2
    assert sessions[0].end == BASE_TIME + timedelta(seconds=300)
    assert sessions[1].end == BASE_TIME + timedelta(seconds=900)
    assert all(session.off_edge_id is not None for session in sessions)


def test_pair_nilm_sessions_requires_compatible_split_phase_topology() -> None:
    sessions = pair_nilm_sessions(
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
                900,
                -610.0,
                leg_a_delta_w=0.0,
                leg_b_delta_w=-610.0,
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="single-leg-load",
    )

    assert len(sessions) == 1
    assert sessions[0].off_edge_id is None


def test_pair_nilm_sessions_counts_overlapping_sessions() -> None:
    sessions = pair_nilm_sessions(
        [
            edge(0, 800.0),
            edge(300, 450.0),
            edge(900, -805.0),
            edge(1200, -455.0),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="overlap",
    )

    assert len(sessions) == 2
    assert sessions[0].overlap_count == 1
    assert sessions[1].overlap_count == 1
    assert all(session.off_edge_id is not None for session in sessions)


def test_pair_nilm_sessions_counts_open_session_overlap() -> None:
    sessions = pair_nilm_sessions(
        [
            edge(0, 800.0),
            edge(300, 450.0),
            edge(900, -455.0),
        ],
        mains_circuit_id="mains",
        signature_fingerprint="open-overlap",
    )

    assert len(sessions) == 2
    assert sessions[0].off_edge_id is None
    assert sessions[0].overlap_count == 1
    assert sessions[1].off_edge_id is not None
    assert sessions[1].overlap_count == 1


def test_pair_nilm_sessions_reduces_confidence_for_ambiguous_off_candidates() -> None:
    simple = pair_nilm_sessions(
        [edge(0, 800.0), edge(900, -805.0)],
        mains_circuit_id="mains",
        signature_fingerprint="simple",
    )[0]
    ambiguous = pair_nilm_sessions(
        [edge(0, 800.0), edge(900, -805.0), edge(960, -790.0)],
        mains_circuit_id="mains",
        signature_fingerprint="ambiguous",
    )[0]

    assert ambiguous.off_edge_id is not None
    assert ambiguous.ambiguous is True
    assert ambiguous.alternate_match_count == 1
    assert simple.ambiguous is False
    assert ambiguous.confidence < simple.confidence


def test_pair_nilm_sessions_marks_known_load_masking_uncertainty() -> None:
    unmasked = pair_nilm_sessions(
        [edge(0, 820.0), edge(1800, -815.0)],
        mains_circuit_id="mains",
        signature_fingerprint="washer",
    )[0]
    masked_low_confidence = pair_nilm_sessions(
        [edge(0, 820.0), edge(1800, -815.0)],
        mains_circuit_id="mains",
        signature_fingerprint="washer",
        known_load_masked=True,
        known_load_confidence=0.2,
    )[0]
    masked_high_confidence = pair_nilm_sessions(
        [edge(0, 820.0), edge(1800, -815.0)],
        mains_circuit_id="mains",
        signature_fingerprint="washer",
        known_load_masked=True,
        known_load_confidence=0.9,
    )[0]

    assert masked_low_confidence.known_load_masked is True
    assert masked_low_confidence.known_load_confidence == 0.2
    assert masked_high_confidence.known_load_confidence == 0.9
    assert masked_low_confidence.confidence < unmasked.confidence
    assert masked_high_confidence.confidence < masked_low_confidence.confidence


def test_pair_nilm_sessions_uses_stable_ids_for_same_edges() -> None:
    edges = [edge(0, 820.0), edge(1800, -815.0)]
    original = pair_nilm_sessions(
        edges,
        mains_circuit_id="mains",
        signature_fingerprint="washer",
    )[0]
    reordered = pair_nilm_sessions(
        list(reversed(edges)),
        mains_circuit_id="mains",
        signature_fingerprint="washer",
    )[0]

    assert reordered.session_id == original.session_id
    assert reordered.on_edge_id == original.on_edge_id
    assert reordered.off_edge_id == original.off_edge_id
