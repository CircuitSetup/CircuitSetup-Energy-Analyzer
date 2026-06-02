from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
    Observation,
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
    assert "changed from its learned baseline" in alert.message


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
