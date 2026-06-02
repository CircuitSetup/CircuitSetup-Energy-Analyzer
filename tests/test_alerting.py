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
