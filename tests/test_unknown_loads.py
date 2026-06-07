from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
from custom_components.circuitsetup_energy_analyzer.nilm import NilmSignature
from custom_components.circuitsetup_energy_analyzer.unknown_loads import (
    build_unknown_load_inventory,
    estimate_unknown_load,
)


BASE_TIME = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def signature(
    signature_id: str,
    watts: float,
    var: float,
    va: float,
    *,
    delta_pf: float = 0.0,
    occurrence_count: int = 4,
    confidence: float = 0.7,
    split_phase_type: str = "unknown",
    dominant_leg: str = "unknown",
) -> NilmSignature:
    return NilmSignature(
        signature_id=signature_id,
        median_delta_w=watts,
        median_delta_var=var,
        median_delta_va=va,
        median_delta_pf=delta_pf,
        occurrence_count=occurrence_count,
        confidence=confidence,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
    )


def edge(
    minutes: int,
    watts: float,
    *,
    var: float = 0.0,
    direction: str = "on",
    split_phase_type: str = "single_leg_a",
    dominant_leg: str = "a",
) -> NilmEdge:
    return NilmEdge(
        timestamp=BASE_TIME + timedelta(minutes=minutes),
        delta_w=watts,
        delta_var=var,
        delta_va=(watts**2 + var**2) ** 0.5,
        delta_pf=0.0,
        direction=direction,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
    )


def test_estimate_unknown_load_marks_single_leg_reactive_signature_as_possible_motor() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-motor-b",
            520.0,
            330.0,
            616.0,
            delta_pf=-0.14,
            occurrence_count=5,
            confidence=0.74,
            split_phase_type="single_leg_b",
            dominant_leg="b",
        )
    )

    assert {
        "signature_id",
        "display_name",
        "likely_type",
        "voltage_class",
        "split_phase_type",
        "dominant_leg",
        "typical_watts",
        "typical_var",
        "typical_va",
        "typical_power_factor",
        "confidence",
        "occurrence_count",
        "evidence",
    } <= result.keys()
    assert result["signature_id"] == "sig-motor-b"
    assert result["likely_type"] == "motor"
    assert result["voltage_class"] == "120 V"
    assert result["split_phase_type"] == "single_leg_b"
    assert result["dominant_leg"] == "b"
    assert result["typical_watts"] == 520.0
    assert result["typical_var"] == 330.0
    assert result["typical_va"] == 616.0
    assert result["typical_power_factor"] == 0.844
    assert result["confidence"] == 0.74
    assert result["occurrence_count"] == 5
    assert "possible" in " ".join(result["evidence"]).lower()
    assert "diagnosis" not in result["display_name"].lower()


def test_estimate_unknown_load_marks_balanced_high_watt_low_var_signature_as_heating_candidate() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-heat",
            4300.0,
            90.0,
            4310.0,
            delta_pf=0.01,
            occurrence_count=6,
            confidence=0.86,
            split_phase_type="balanced_240v",
            dominant_leg="balanced",
        )
    )

    assert result["likely_type"] == "heating_element_candidate"
    assert result["voltage_class"] == "240 V"
    assert result["dominant_leg"] == "balanced"
    assert result["typical_power_factor"] == 0.998
    assert "candidate" in result["display_name"].lower()
    assert "candidate" in " ".join(result["evidence"]).lower()


def test_estimate_unknown_load_marks_high_va_reactive_non_motor_signature_as_power_electronics() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-electronics",
            180.0,
            190.0,
            265.0,
            delta_pf=-0.22,
            occurrence_count=4,
            confidence=0.66,
            split_phase_type="imbalanced_240v_or_mixed",
            dominant_leg="mixed",
        )
    )

    assert result["likely_type"] == "power_electronics"
    assert result["voltage_class"] == "mixed"
    assert result["typical_watts"] == 180.0
    assert result["typical_var"] == 190.0
    assert result["typical_va"] == 265.0
    assert result["typical_power_factor"] == 0.679
    assert "possible" in " ".join(result["evidence"]).lower()


def test_estimate_unknown_load_leaves_low_evidence_signature_unknown() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-low-evidence",
            420.0,
            260.0,
            500.0,
            delta_pf=-0.18,
            occurrence_count=1,
            confidence=0.35,
            split_phase_type="single_leg_a",
            dominant_leg="a",
        )
    )

    assert result["likely_type"] == "unknown"
    assert result["voltage_class"] == "120 V"
    assert result["confidence"] == 0.35
    assert result["occurrence_count"] == 1
    assert "limited" in " ".join(result["evidence"]).lower()


def test_build_unknown_load_inventory_tracks_multiple_loads_separately() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature(
                "sig-resistive",
                300.0,
                15.0,
                301.0,
                occurrence_count=5,
                confidence=0.8,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            signature(
                "sig-motor",
                900.0,
                520.0,
                1040.0,
                delta_pf=-0.2,
                occurrence_count=6,
                confidence=0.85,
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        edges=[
            edge(0, 300.0, direction="on"),
            edge(30, -300.0, direction="off"),
            edge(
                60,
                900.0,
                var=520.0,
                direction="on",
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
            edge(
                120,
                -900.0,
                var=-520.0,
                direction="off",
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        now=BASE_TIME + timedelta(hours=3),
        existing_state={},
    )

    assert inventory["unknown_load_count"] == 2
    assert inventory["active_unknown_load_count"] == 0
    assert inventory["ambiguous_unknown_load_count"] == 0
    assert inventory["unknown_estimated_energy_today_kwh"] == 1.05
    by_id = {load["signature_id"]: load for load in inventory["unknown_loads"]}
    assert by_id["sig-resistive"]["voltage_class"] == "120 V"
    assert by_id["sig-resistive"]["runtime_today_minutes"] == 30.0
    assert by_id["sig-resistive"]["estimated_energy_today_kwh"] == 0.15
    assert by_id["sig-motor"]["dominant_leg"] == "b"
    assert by_id["sig-motor"]["runtime_today_minutes"] == 60.0
    assert by_id["sig-motor"]["estimated_energy_today_kwh"] == 0.9
    assert by_id["sig-motor"]["running_state"] == "probably_off"


def test_build_unknown_load_inventory_tracks_currently_running_load() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature(
                "sig-running",
                600.0,
                360.0,
                700.0,
                occurrence_count=5,
                confidence=0.8,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            )
        ],
        edges=[edge(0, 600.0, var=360.0, direction="on")],
        now=BASE_TIME + timedelta(minutes=45),
        existing_state={},
    )

    load = inventory["unknown_loads"][0]
    assert inventory["active_unknown_load_count"] == 1
    assert load["running_state"] == "probably_on"
    assert load["current_runtime_minutes"] == 45.0
    assert load["estimated_energy_today_kwh"] == 0.45


def test_build_unknown_load_inventory_marks_overlapping_events_ambiguous() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("sig-a", 500.0, 100.0, 510.0),
            signature("sig-b", 540.0, 110.0, 551.0),
        ],
        edges=[edge(0, 500.0), edge(0, 540.0)],
        now=BASE_TIME + timedelta(minutes=10),
        existing_state={},
    )

    assert inventory["unknown_load_count"] == 2
    assert inventory["ambiguous_unknown_load_count"] == 2
    assert inventory["simultaneous_unknown_event_count"] == 2
    assert all(
        load["separation_status"] == "ambiguous"
        for load in inventory["unknown_loads"]
    )
    assert all(
        load["running_state"] == "unknown" for load in inventory["unknown_loads"]
    )
    assert all(
        load["estimated_energy_today_kwh"] == 0.0
        for load in inventory["unknown_loads"]
    )
