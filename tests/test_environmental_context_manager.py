from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import (
    environmental_context,
)
from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile

EnvironmentalContextManager = environmental_context.EnvironmentalContextManager


def test_environmental_context_profile_boundaries_are_explicit() -> None:
    assert ApplianceProfile.HVAC in environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    assert ApplianceProfile.WATER_HEATER not in (
        environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.SUMP_PUMP in (
        environmental_context.PUMP_WATER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.WATER_HEATER in (
        environmental_context.FLOW_WATER_CONTEXT_PROFILES
    )


def test_coordinator_wires_environmental_context_manager() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace(data={}))

    assert isinstance(coordinator.environment_context, EnvironmentalContextManager)
