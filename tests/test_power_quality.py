from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.power_quality import (
    MIN_RELATIONSHIP_SCORE,
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)

NOW = datetime(2026, 6, 2, tzinfo=UTC)
RELATIONSHIP_EVIDENCE_FEATURES = {
    "reactive_shift_under_stable_real_power",
    "power_factor_shift_under_load",
    "apparent_power_shift",
    "motor_relationship_changed",
    "split_phase_relationship_changed",
    "resistive_load_became_reactive",
}


def sample(
    *,
    real_power: float | None = 500.0,
    reactive_power: float | None = 80.0,
    apparent_power: float | None = 506.0,
    power_factor: float | None = 0.98,
) -> CircuitSample:
    return CircuitSample(
        timestamp=NOW,
        circuit_id="fridge",
        real_power=real_power,
        reactive_power=reactive_power,
        apparent_power=apparent_power,
        power_factor=power_factor,
    )


def baseline(
    feature: str,
    median: float,
    mad: float = 5.0,
    confidence: float = 1.0,
) -> BaselineStats:
    return BaselineStats(
        feature=feature,
        sample_count=20,
        median=median,
        mad=mad,
        p10=median - 10.0,
        p90=median + 10.0,
        confidence=confidence,
    )


def config(
    profile: ApplianceProfile = ApplianceProfile.REFRIGERATOR,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=profile,
        mode=mode,
    )


def test_extract_power_quality_features_calculates_loaded_relationships() -> None:
    features = extract_power_quality_features(
        sample(
            real_power=500.0,
            reactive_power=100.0,
            apparent_power=510.0,
            power_factor=0.96,
        )
    )

    assert features["real_power"] == 500.0
    assert features["reactive_power"] == 100.0
    assert features["apparent_power"] == 510.0
    assert features["power_factor"] == 0.96
    assert features["reactive_to_real_ratio"] == 0.2
    assert features["apparent_to_real_ratio"] == 1.02
    assert round(features["power_factor_deficit"], 3) == 0.04
    assert "apparent_power_residual" in features


def test_extract_power_quality_features_suppresses_relationships_below_load_floor() -> (
    None
):
    features = extract_power_quality_features(
        sample(
            real_power=25.0, reactive_power=40.0, apparent_power=47.0, power_factor=0.53
        )
    )

    assert features["real_power"] == 25.0
    assert features["reactive_power"] == 40.0
    assert "reactive_to_real_ratio" not in features
    assert "apparent_to_real_ratio" not in features
    assert "power_factor" not in features
    assert "power_factor_deficit" not in features


def test_extract_power_quality_features_suppresses_invalid_power_factor() -> None:
    features = extract_power_quality_features(
        sample(
            real_power=500.0,
            reactive_power=100.0,
            apparent_power=510.0,
            power_factor=1.08,
        )
    )

    assert features["real_power"] == 500.0
    assert features["reactive_power"] == 100.0
    assert features["apparent_power"] == 510.0
    assert features["reactive_to_real_ratio"] == 0.2
    assert "power_factor" not in features
    assert "power_factor_deficit" not in features


def test_extract_power_quality_features_suppresses_negative_apparent_power() -> None:
    features = extract_power_quality_features(
        sample(
            real_power=500.0,
            reactive_power=80.0,
            apparent_power=-506.0,
            power_factor=0.98,
        )
    )

    assert features["real_power"] == 500.0
    assert features["reactive_power"] == 80.0
    assert features["power_factor"] == 0.98
    assert features["reactive_to_real_ratio"] == 0.16
    assert "apparent_power" not in features
    assert "apparent_to_real_ratio" not in features
    assert "apparent_power_residual" not in features


def test_score_power_quality_features_handles_missing_optional_baselines() -> None:
    features = extract_power_quality_features(
        sample(
            real_power=510.0,
            reactive_power=180.0,
            apparent_power=None,
            power_factor=None,
        )
    )
    scores = score_power_quality_features(
        features,
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
        },
    )

    by_feature = {score.feature: score for score in scores}
    assert set(by_feature) == {"real_power", "reactive_power", "reactive_to_real_ratio"}
    assert by_feature["real_power"].score < 1.0
    assert by_feature["reactive_power"].score > 3.0
    assert relationship_rms_score(scores) > 2.0


def test_score_power_quality_features_uses_unitless_spread_floor() -> None:
    scores = score_power_quality_features(
        {
            "power_factor": 0.93,
            "reactive_to_real_ratio": 0.24,
            "real_power": 510.0,
        },
        {
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "real_power": baseline("real_power", 500.0, 20.0),
        },
    )

    by_feature = {score.feature: score for score in scores}
    assert by_feature["power_factor"].score > MIN_RELATIONSHIP_SCORE
    assert by_feature["reactive_to_real_ratio"].score > MIN_RELATIONSHIP_SCORE
    assert by_feature["real_power"].score < 1.0


def test_relationship_rms_score_excludes_apparent_power_residual() -> None:
    scores = score_power_quality_features(
        {
            "real_power": 500.0,
            "apparent_power_residual": 100.0,
        },
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "apparent_power_residual": baseline(
                "apparent_power_residual",
                0.0,
                1.0,
            ),
        },
    )

    assert relationship_rms_score(scores) == 0.0


def test_select_evidence_finds_reactive_shift_under_stable_real_power() -> None:
    features = extract_power_quality_features(
        sample(
            real_power=510.0,
            reactive_power=220.0,
            apparent_power=560.0,
            power_factor=0.91,
        )
    )
    scores = score_power_quality_features(
        features,
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "apparent_power": baseline("apparent_power", 506.0, 12.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "apparent_to_real_ratio": baseline("apparent_to_real_ratio", 1.01, 0.01),
            "power_factor_deficit": baseline("power_factor_deficit", 0.02, 0.01),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert evidence is not None
    assert evidence.feature == "reactive_shift_under_stable_real_power"
    assert "reactive power" in evidence.message
    assert "real power stayed" in evidence.message
    assert evidence.features["relationship_rms"] > 2.0


def test_select_evidence_requires_multiple_relationship_contributors() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=None,
                power_factor=None,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert relationship_rms_score(scores) > 0.0
    assert evidence is None or evidence.feature not in RELATIONSHIP_EVIDENCE_FEATURES


def test_select_evidence_requires_two_material_relationship_contributors() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=None,
                power_factor=0.98,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert relationship_rms_score(scores) > 0.0
    assert evidence is None or evidence.feature not in RELATIONSHIP_EVIDENCE_FEATURES


def test_select_evidence_counts_pf_family_once() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=None,
                apparent_power=None,
                power_factor=0.90,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "power_factor_deficit": baseline("power_factor_deficit", 0.02, 0.01),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert relationship_rms_score(scores) > MIN_RELATIONSHIP_SCORE
    assert evidence is None or evidence.feature != "power_factor_shift_under_load"


def test_select_evidence_counts_reactive_family_once() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=None,
                power_factor=None,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert relationship_rms_score(scores) > MIN_RELATIONSHIP_SCORE
    assert evidence is None or evidence.feature not in RELATIONSHIP_EVIDENCE_FEATURES


def test_select_evidence_still_allows_real_power_fallback() -> None:
    scores = score_power_quality_features(
        {"real_power": 700.0},
        {"real_power": baseline("real_power", 500.0, 20.0)},
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert relationship_rms_score(scores) == 0.0
    assert evidence is not None
    assert evidence.feature == "real_power"


def test_real_power_fallback_uses_active_threshold() -> None:
    scores = score_power_quality_features(
        {"real_power": 560.0},
        {"real_power": baseline("real_power", 500.0, 20.0)},
    )

    evidence = select_power_quality_evidence(
        config(),
        scores,
        min_relationship_score=3.0,
    )

    assert relationship_rms_score(scores) == 0.0
    assert evidence is None


def test_select_evidence_requires_scored_real_power_for_stable_shift() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=560.0,
                power_factor=0.91,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0, confidence=0.4),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "power_factor_deficit": baseline("power_factor_deficit", 0.02, 0.01),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert evidence is not None
    assert evidence.feature != "reactive_shift_under_stable_real_power"


def test_select_evidence_confidence_uses_lowest_contributor() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=560.0,
                power_factor=0.91,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0, confidence=0.72),
            "reactive_power": baseline("reactive_power", 80.0, 10.0, confidence=0.9),
            "power_factor": baseline("power_factor", 0.98, 0.01, confidence=0.86),
            "reactive_to_real_ratio": baseline(
                "reactive_to_real_ratio", 0.16, 0.02, confidence=0.93
            ),
            "power_factor_deficit": baseline(
                "power_factor_deficit", 0.02, 0.01, confidence=0.81
            ),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert evidence is not None
    assert evidence.feature == "reactive_shift_under_stable_real_power"
    assert evidence.baseline_confidence == 0.72


def test_evidence_confidence_ignores_noncontributing_low_confidence_scores() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=506.0,
                power_factor=0.91,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0, confidence=0.9),
            "reactive_power": baseline(
                "reactive_power", 80.0, 10.0, confidence=0.95
            ),
            "reactive_to_real_ratio": baseline(
                "reactive_to_real_ratio", 0.16, 0.02, confidence=0.94
            ),
            "power_factor": baseline("power_factor", 0.98, 0.01, confidence=0.93),
            "power_factor_deficit": baseline(
                "power_factor_deficit", 0.02, 0.01, confidence=0.92
            ),
            "apparent_power": baseline("apparent_power", 506.0, 12.0, confidence=0.6),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert evidence is not None
    assert evidence.feature == "reactive_shift_under_stable_real_power"
    assert evidence.baseline_confidence == 0.9


def test_select_evidence_flags_resistive_load_that_became_reactive() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=4400.0,
                reactive_power=900.0,
                apparent_power=4492.0,
                power_factor=0.88,
            )
        ),
        {
            "real_power": baseline("real_power", 4400.0, 80.0),
            "reactive_power": baseline("reactive_power", 20.0, 8.0),
            "power_factor": baseline("power_factor", 0.99, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.005, 0.002),
            "power_factor_deficit": baseline("power_factor_deficit", 0.01, 0.005),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.WATER_HEATER, CircuitMode.DUAL_PHASE),
        scores,
    )

    assert evidence is not None
    assert evidence.feature == "resistive_load_became_reactive"
    assert "resistive" in evidence.message


def test_select_evidence_treats_electric_heat_as_resistive_load() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=9500.0,
                reactive_power=1400.0,
                apparent_power=9602.0,
                power_factor=0.92,
            )
        ),
        {
            "real_power": baseline("real_power", 9500.0, 120.0),
            "reactive_power": baseline("reactive_power", 30.0, 8.0),
            "power_factor": baseline("power_factor", 0.99, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.003, 0.002),
            "power_factor_deficit": baseline("power_factor_deficit", 0.01, 0.005),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.ELECTRIC_HEAT, CircuitMode.DUAL_PHASE),
        scores,
    )

    assert evidence is not None
    assert evidence.feature == "resistive_load_became_reactive"


def test_select_evidence_treats_hvac_compressor_as_motor_load() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=3200.0,
                reactive_power=1100.0,
                apparent_power=3384.0,
                power_factor=0.88,
            )
        ),
        {
            "real_power": baseline("real_power", 2600.0, 90.0),
            "reactive_power": baseline("reactive_power", 520.0, 40.0),
            "apparent_power": baseline("apparent_power", 3223.0, 50.0),
            "power_factor": baseline("power_factor", 0.96, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "apparent_to_real_ratio": baseline("apparent_to_real_ratio", 1.01, 0.01),
            "power_factor_deficit": baseline("power_factor_deficit", 0.04, 0.01),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.HVAC_COMPRESSOR, CircuitMode.SINGLE_PHASE),
        scores,
    )

    assert evidence is not None
    assert evidence.feature == "motor_relationship_changed"


def test_select_evidence_ignores_raw_var_when_real_power_changed() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=4000.0,
                reactive_power=400.0,
                apparent_power=None,
                power_factor=None,
            )
        ),
        {
            "real_power": baseline("real_power", 2000.0, 40.0),
            "reactive_power": baseline("reactive_power", 200.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.10, 0.01),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.WATER_HEATER, CircuitMode.DUAL_PHASE),
        scores,
    )

    assert evidence is not None
    assert evidence.feature != "resistive_load_became_reactive"


def test_select_evidence_suppresses_proportional_motor_load_scaling() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=1000.0,
                reactive_power=160.0,
                apparent_power=1012.0,
                power_factor=0.98,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "apparent_power": baseline("apparent_power", 506.0, 12.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "apparent_to_real_ratio": baseline("apparent_to_real_ratio", 1.012, 0.01),
            "power_factor_deficit": baseline("power_factor_deficit", 0.02, 0.01),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.MOTOR_LOAD),
        scores,
    )

    assert evidence is not None
    assert evidence.feature == "real_power"


def test_select_evidence_suppresses_mixed_circuit_appliance_alerts() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(
                real_power=510.0,
                reactive_power=220.0,
                apparent_power=560.0,
                power_factor=0.91,
            )
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
        },
    )

    assert (
        select_power_quality_evidence(
            config(ApplianceProfile.MIXED, CircuitMode.MIXED),
            scores,
        )
        is None
    )
