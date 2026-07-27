from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import (
    environmental_context,
)
from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile

EnvironmentalContextManager = environmental_context.EnvironmentalContextManager


def test_environmental_context_profile_boundaries_are_explicit() -> None:
    assert ApplianceProfile.HVAC in environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    assert (
        ApplianceProfile.MINI_SPLIT
        in environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.WATER_HEATER not in (
        environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.SUMP_PUMP in (
        environmental_context.PUMP_WATER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.WATER_HEATER in (
        environmental_context.FLOW_WATER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.DISHWASHER in (
        environmental_context.FLOW_WATER_CONTEXT_PROFILES
    )
    assert ApplianceProfile.THREE_D_PRINTER not in (
        environmental_context.FLOW_WATER_CONTEXT_PROFILES
    )


def test_coordinator_wires_environmental_context_manager() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace(data={}))

    assert isinstance(coordinator.environment_context, EnvironmentalContextManager)


def test_hvac_compressor_context_includes_mini_split_runtime() -> None:
    coordinator = SimpleNamespace(
        circuit_configs=[
            SimpleNamespace(
                circuit_id="mini_split",
                appliance_profile=ApplianceProfile.MINI_SPLIT,
            )
        ],
        state=SimpleNamespace(
            run_cycle_runtime_seconds_by_circuit={"mini_split": 1800.0},
            run_cycle_duty_cycle_by_circuit={"mini_split": 25.0},
        ),
    )

    context = EnvironmentalContextManager(coordinator).hvac_compressor_context()

    assert context["circuit_ids"] == ["mini_split"]
    assert context["runtime_minutes"] == 30.0
    assert context["duty_cycle_percent"] == 25.0
