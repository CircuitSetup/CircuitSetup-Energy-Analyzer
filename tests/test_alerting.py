from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
    Observation,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    Severity,
)


def test_policy_waits_for_repeated_observations() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert (
        policy.observe(Observation("fridge", "cycle_duration", 1.6, 0.8, now))
        is None
    )
    assert (
        policy.observe(
            Observation("fridge", "cycle_duration", 1.7, 0.8, now + timedelta(hours=1))
        )
        is None
    )

    alert = policy.observe(
        Observation("fridge", "cycle_duration", 1.8, 0.8, now + timedelta(hours=2))
    )

    assert alert is not None
    assert alert.repeated_count == 3
    assert "Possible issue" in alert.message
    assert "Cycle Duration shows evidence" in alert.message
    assert "cycle_duration" not in alert.message
    assert "evidence of a learned-baseline change" in alert.message


def test_policy_blocks_low_confidence_baseline() -> None:
    policy = ConservativeAlertPolicy(min_repeated=2, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert (
        policy.observe(Observation("fridge", "cycle_duration", 6.0, 0.2, now))
        is None
    )
    assert (
        policy.observe(
            Observation("fridge", "cycle_duration", 6.2, 0.2, now + timedelta(hours=1))
        )
        is None
    )


def test_policy_blocks_repeated_weak_scores() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert (
        policy.observe(Observation("fridge", "cycle_duration", 1.0, 0.8, now))
        is None
    )
    assert (
        policy.observe(
            Observation("fridge", "cycle_duration", 1.0, 0.8, now + timedelta(hours=1))
        )
        is None
    )
    assert (
        policy.observe(
            Observation("fridge", "cycle_duration", 1.0, 0.8, now + timedelta(hours=2))
        )
        is None
    )


def test_alert_evidence_features_are_readable_but_immutable() -> None:
    features = {"cycle_duration": 1.8}
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        features=features,
    )

    features["cycle_duration"] = 9.9

    assert alert.features["cycle_duration"] == 1.8
    with pytest.raises(TypeError):
        alert.features["cycle_duration"] = 2.0


def test_policy_preserves_custom_power_quality_evidence() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)
    message = (
        "Possible issue: reactive power increased while real power stayed near "
        "baseline across recent observations."
    )
    features = {
        "real_power": 0.4,
        "reactive_power": 4.2,
        "reactive_to_real_ratio": 3.8,
        "relationship_rms": 3.4,
    }

    for index in range(2):
        assert policy.observe(
            Observation(
                circuit_id="fridge",
                feature="reactive_shift_under_stable_real_power",
                score=3.4,
                baseline_confidence=1.0,
                observed_at=now + timedelta(minutes=index),
                observed_value=0.44,
                baseline_value=0.16,
                message=message,
                features=features,
            )
        ) is None

    alert = policy.observe(
        Observation(
            circuit_id="fridge",
            feature="reactive_shift_under_stable_real_power",
            score=3.5,
            baseline_confidence=1.0,
            observed_at=now + timedelta(minutes=2),
            observed_value=0.45,
            baseline_value=0.16,
            message=message,
            features=features,
        )
    )

    assert alert is not None
    assert alert.message == message
    assert alert.feature == "reactive_shift_under_stable_real_power"
    assert alert.features["reactive_power"] == 4.2
    assert alert.features["relationship_rms"] == 3.4
