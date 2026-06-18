from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
    Observation,
    alert_feedback_fingerprint,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    SensorRef,
    SensorRole,
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


def test_policy_supports_adjusted_min_repeated_requirement() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)

    for index in range(4):
        assert (
            policy.observe(
                Observation(
                    "fridge",
                    "cycle_duration",
                    2.0,
                    0.8,
                    now + timedelta(hours=index),
                ),
                min_repeated=5,
            )
            is None
        )

    alert = policy.observe(
        Observation(
            "fridge",
            "cycle_duration",
            2.0,
            0.8,
            now + timedelta(hours=4),
        ),
        min_repeated=5,
    )

    assert alert is not None
    assert alert.repeated_count == 5
    assert alert.first_seen == now
    assert alert.last_seen == now + timedelta(hours=4)


def test_policy_does_not_combine_expired_observations() -> None:
    policy = ConservativeAlertPolicy(
        min_repeated=3,
        min_baseline_confidence=0.6,
        max_observation_age=timedelta(hours=1),
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert (
        policy.observe(Observation("fridge", "cycle_duration", 2.0, 0.8, now))
        is None
    )
    assert (
        policy.observe(
            Observation(
                "fridge",
                "cycle_duration",
                2.0,
                0.8,
                now + timedelta(minutes=30),
            )
        )
        is None
    )

    alert = policy.observe(
        Observation(
            "fridge",
            "cycle_duration",
            2.0,
            0.8,
            now + timedelta(hours=2),
        )
    )

    assert alert is None


def test_policy_starts_new_episode_after_large_observation_gap() -> None:
    policy = ConservativeAlertPolicy(
        min_repeated=3,
        min_baseline_confidence=0.6,
        max_episode_gap=timedelta(hours=1),
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)

    assert (
        policy.observe(Observation("fridge", "cycle_duration", 2.0, 0.8, now))
        is None
    )
    assert (
        policy.observe(
            Observation(
                "fridge",
                "cycle_duration",
                2.0,
                0.8,
                now + timedelta(minutes=30),
            )
        )
        is None
    )
    assert (
        policy.observe(
            Observation(
                "fridge",
                "cycle_duration",
                2.0,
                0.8,
                now + timedelta(hours=2),
            )
        )
        is None
    )
    assert (
        policy.observe(
            Observation(
                "fridge",
                "cycle_duration",
                2.0,
                0.8,
                now + timedelta(hours=2, minutes=30),
            )
        )
        is None
    )
    alert = policy.observe(
        Observation(
            "fridge",
            "cycle_duration",
            2.0,
            0.8,
            now + timedelta(hours=3),
        )
    )

    assert alert is not None
    assert alert.repeated_count == 3
    assert alert.first_seen == now + timedelta(hours=2)


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


def test_alert_feedback_fingerprint_is_stable_across_alert_timestamps() -> None:
    first = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_spike",
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
    )
    repeated = AlertEvidence(
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue again",
        feature="daily_energy_spike",
        observed_value=2.64,
        baseline_value=2.0,
        change_ratio=0.32,
    )

    assert alert_feedback_fingerprint(first) == alert_feedback_fingerprint(repeated)


def test_alert_feedback_fingerprint_uses_context_without_timestamps() -> None:
    config = CircuitConfig(
        circuit_id="fridge",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.LOAD,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
        ),
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_spike",
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
        features={"outdoor_temperature_f": 94.2},
    )
    cooler_context = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="daily_energy_spike",
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
        features={"outdoor_temperature_f": 61.0},
    )

    fingerprint = alert_feedback_fingerprint(alert, config=config)

    assert fingerprint.startswith("fridge|daily_energy_spike|")
    assert "sources=energy+real_power" in fingerprint
    assert "profile=refrigerator" in fingerprint
    assert "mode=single_phase" in fingerprint
    assert "power_flow=load" in fingerprint
    assert "observed=2.5-3.0" in fingerprint
    assert "ratio=25-50pct" in fingerprint
    assert "temp=90-95f" in fingerprint
    assert fingerprint != alert_feedback_fingerprint(cooler_context, config=config)
