from __future__ import annotations

from datetime import UTC, datetime
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


def test_mini_split_weather_context_separates_heating_history() -> None:
    config = SimpleNamespace(appliance_profile=ApplianceProfile.MINI_SPLIT)
    assert environmental_context._weather_context_mode(config, 45.0) == "heating"

    coordinator = SimpleNamespace(
        store_data=SimpleNamespace(
            weather_context_history_by_circuit={
                "mini_split": [
                    {
                        "timestamp": "2026-01-01T12:00:00+00:00",
                        "temperature": 40.0,
                        "runtime_minutes": 90.0,
                        "duty_cycle_percent": 25.0,
                    },
                    {
                        "timestamp": "2026-07-01T12:00:00+00:00",
                        "temperature": 90.0,
                        "runtime_minutes": 180.0,
                        "duty_cycle_percent": 50.0,
                    },
                ]
            }
        ),
        context_builder=SimpleNamespace(time_zone=lambda: None),
    )

    samples = EnvironmentalContextManager(coordinator).weather_context_history_samples(
        "mini_split",
        datetime(2026, 7, 27, tzinfo=UTC),
        mode="heating",
    )

    assert [sample.temperature for sample in samples] == [40.0]
