from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.nilm_load_identification import (
    identify_estimated_load,
)


def test_identifies_heating_before_generic_resistive_for_large_balanced_240v() -> None:
    result = identify_estimated_load(
        median_delta_w=4300.0,
        median_delta_var=90.0,
        median_delta_va=4310.0,
        median_delta_pf=0.01,
        split_phase_type="balanced_240v",
        occurrence_count=6,
        confidence=0.86,
    )

    assert result.likely_type == "heating_element_candidate"
    assert result.display_name == "Estimated heating load"
    assert result.review_label == "possible 240 V heating load"
    assert result.typical_power_factor == 0.998
    assert "heating" in result.evidence_reason


def test_identifies_resistive_when_va_confirms_near_unity_pf() -> None:
    result = identify_estimated_load(
        median_delta_w=500.0,
        median_delta_var=20.0,
        median_delta_va=501.0,
        median_delta_pf=0.0,
        split_phase_type="single_leg_a",
        occurrence_count=4,
        confidence=0.7,
    )

    assert result.likely_type == "resistive"
    assert result.display_name == "Estimated resistive load"
    assert result.review_label == "possible 120 V resistive load"
    assert result.typical_power_factor == 0.998
    assert "VAR is low" in result.evidence_reason


def test_identifies_resistive_when_va_missing_but_pf_delta_is_stable() -> None:
    result = identify_estimated_load(
        median_delta_w=500.0,
        median_delta_var=20.0,
        median_delta_va=None,
        median_delta_pf=0.02,
        split_phase_type="single_leg_b",
        occurrence_count=4,
        confidence=0.7,
    )

    assert result.likely_type == "resistive"
    assert result.display_name == "Estimated resistive load"
    assert result.review_label == "possible 120 V resistive load"
    assert result.typical_power_factor is None
    assert " VA " not in result.evidence_reason
    assert "estimated PF" not in result.evidence_reason


def test_identifies_motor_without_requiring_va_when_reactive_topology_matches() -> None:
    result = identify_estimated_load(
        median_delta_w=520.0,
        median_delta_var=330.0,
        median_delta_va=None,
        median_delta_pf=-0.14,
        split_phase_type="single_leg_b",
        occurrence_count=5,
        confidence=0.74,
    )

    assert result.likely_type == "motor"
    assert result.display_name == "Estimated motor load"
    assert result.review_label == "possible 120 V motor load"
    assert result.typical_power_factor is None
    assert " VA " not in result.evidence_reason
    assert "estimated PF" not in result.evidence_reason


def test_missing_va_motor_candidate_requires_pf_delta_evidence() -> None:
    result = identify_estimated_load(
        median_delta_w=520.0,
        median_delta_var=330.0,
        median_delta_va=None,
        median_delta_pf=None,
        split_phase_type="single_leg_b",
        occurrence_count=5,
        confidence=0.74,
    )

    assert result.likely_type == "unknown"


def test_missing_va_motor_candidate_rejects_neutral_pf_delta() -> None:
    result = identify_estimated_load(
        median_delta_w=520.0,
        median_delta_var=330.0,
        median_delta_va=None,
        median_delta_pf=0.0,
        split_phase_type="single_leg_b",
        occurrence_count=5,
        confidence=0.74,
    )

    assert result.likely_type == "unknown"


def test_identifies_electronics_only_when_va_supports_high_reactive_signature() -> None:
    result = identify_estimated_load(
        median_delta_w=180.0,
        median_delta_var=190.0,
        median_delta_va=265.0,
        median_delta_pf=-0.22,
        split_phase_type="imbalanced_240v_or_mixed",
        occurrence_count=4,
        confidence=0.66,
    )

    assert result.likely_type == "power_electronics"
    assert result.display_name == "Estimated electronics load"
    assert result.review_label == "possible electronics load"
    assert result.typical_power_factor == 0.679


def test_low_evidence_remains_unknown_even_with_reactive_shape() -> None:
    result = identify_estimated_load(
        median_delta_w=520.0,
        median_delta_var=330.0,
        median_delta_va=616.0,
        median_delta_pf=-0.14,
        split_phase_type="single_leg_b",
        occurrence_count=1,
        confidence=0.35,
    )

    assert result.likely_type == "unknown"
    assert result.display_name == "Estimated unknown load"
    assert result.review_label == "unknown recurring load"
    assert "Limited recurring evidence" in result.evidence_reason


def test_user_label_overrides_review_label_preserves_estimated_name() -> None:
    result = identify_estimated_load(
        median_delta_w=120.0,
        median_delta_var=5.0,
        median_delta_va=121.0,
        median_delta_pf=0.0,
        split_phase_type="unknown",
        occurrence_count=3,
        confidence=0.6,
        user_label="Dehumidifier",
    )

    assert result.review_label == "Dehumidifier"
    assert result.display_name == "Estimated unknown load"
