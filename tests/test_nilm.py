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
    NilmSignature,
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
    unmatched_load_percentage,
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


def edge(
    seconds: int,
    delta_w: float,
    *,
    delta_var: float = 0.0,
    delta_va: float | None = None,
    delta_pf: float = 0.0,
    direction: str | None = None,
) -> NilmEdge:
    return NilmEdge(
        timestamp=BASE_TIME + timedelta(seconds=seconds),
        delta_w=delta_w,
        delta_var=delta_var,
        delta_va=delta_va if delta_va is not None else delta_w,
        delta_pf=delta_pf,
        direction=direction or ("on" if delta_w > 0 else "off"),
    )


def test_edge_detector_emits_on_and_off_edges_from_current_sample_fields() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            sample(0, 80.0, reactive_power=10.0, apparent_power=82.0, power_factor=0.98),
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


def test_edge_detector_ignores_missing_real_power_and_small_changes() -> None:
    detector = NilmEdgeDetector(min_delta_w=100.0)

    edges = detector.process_many(
        [
            sample(0, 50.0),
            CircuitSample(timestamp=BASE_TIME + timedelta(seconds=5), circuit_id="mains"),
            sample(10, 120.0),
            sample(15, 180.0),
            sample(20, 20.0),
        ]
    )

    assert edges == [edge(20, -160.0)]


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
    assert result.unmatched_edges == [edge(40, 325.0)]


def test_mask_known_loads_supports_stop_power_features() -> None:
    known_event = CircuitEvent(
        timestamp=BASE_TIME + timedelta(seconds=30),
        circuit_id="pump",
        event_type=EventType.STOP,
        features={"stop_power_w": 150.0},
    )

    result = mask_known_loads([edge(30, -155.0)], [known_event])

    assert result.matched_edges[0].known_circuit_id == "pump"
    assert result.unmatched_edges == []


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
