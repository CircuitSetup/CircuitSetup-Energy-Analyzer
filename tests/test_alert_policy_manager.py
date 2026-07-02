from __future__ import annotations

from types import SimpleNamespace

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
