from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import (
    environmental_context,
)

EnvironmentalContextManager = environmental_context.EnvironmentalContextManager


def test_coordinator_wires_environmental_context_manager() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace(data={}))

    assert isinstance(coordinator.environment_context, EnvironmentalContextManager)
