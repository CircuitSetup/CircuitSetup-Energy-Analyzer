from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
    Observation,
)
from custom_components.circuitsetup_energy_analyzer.managers.alert_policies import (
    AlertPolicyManager,
)


def test_coordinator_wires_alert_policy_manager_callbacks() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace(data={}))

    assert isinstance(coordinator.alert_policies, AlertPolicyManager)
    assert (
        coordinator._energy_usage_processor._alert_policy_for_circuit.__self__
        is coordinator.alert_policies
    )
    assert (
        coordinator._water_context_alert_processor._alert_policy_for_circuit.__self__
        is coordinator.alert_policies
    )


def test_feedback_aware_policy_forwards_episode_reset() -> None:
    manager = AlertPolicyManager(
        SimpleNamespace(
            evidence_actions=SimpleNamespace(
                adjusted_min_repeated_for_observation=lambda _observation, base: base
            )
        )
    )
    policy = manager.feedback_aware_alert_policy(
        ConservativeAlertPolicy(min_repeated=3)
    )
    now = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    for offset in range(2):
        assert policy.observe(
            Observation(
                "fridge",
                "cold_storage_cycle_signature_change",
                2.0,
                1.0,
                now + timedelta(minutes=30 * offset),
            )
        ) is None

    policy.reset_episode("fridge", "cold_storage_cycle_signature_change")

    assert policy.observe(
        Observation(
            "fridge",
            "cold_storage_cycle_signature_change",
            2.0,
            1.0,
            now + timedelta(minutes=60),
        )
    ) is None
