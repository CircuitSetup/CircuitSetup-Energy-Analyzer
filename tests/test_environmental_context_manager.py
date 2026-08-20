from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import (
    environmental_context,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
)

EnvironmentalContextManager = environmental_context.EnvironmentalContextManager


def test_mixed_water_context_clears_stale_direct_state() -> None:
    cleared: list[str] = []

    def clear(name):
        return lambda _state, _store, circuit_id: (
            cleared.append(f"{name}:{circuit_id}") or True
        )

    coordinator = SimpleNamespace(
        state=SimpleNamespace(),
        store_data=SimpleNamespace(),
        settings_controller=SimpleNamespace(
            advanced_settings_for_circuit=lambda _circuit_id: {}
        ),
        state_reducer=SimpleNamespace(
            clear_rain_pump_context_state=clear("rain"),
            clear_water_flow_context_state=clear("flow"),
            clear_water_context_history=clear("history"),
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )

    EnvironmentalContextManager(coordinator).refresh_water_context_state(
        CircuitConfig(
            circuit_id="pump",
            name="Pump",
            appliance_profile=ApplianceProfile.WATER_PUMP,
            mode=CircuitMode.MIXED,
        ),
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert cleared == ["rain:pump", "flow:pump", "history:pump"]


def test_environmental_context_profile_boundaries_are_explicit() -> None:
    assert ApplianceProfile.HVAC in environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    assert (
        ApplianceProfile.HEAT_PUMP
        in environmental_context.HVAC_WEATHER_CONTEXT_PROFILES
    )
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
    assert ApplianceProfile.SUMP_PUMP not in (
        environmental_context.FLOW_WATER_CONTEXT_PROFILES
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


def test_hvac_compressor_context_includes_bidirectional_refrigerant_runtime() -> None:
    coordinator = SimpleNamespace(
        circuit_configs=[
            SimpleNamespace(
                circuit_id="mini_split",
                appliance_profile=ApplianceProfile.MINI_SPLIT,
            ),
            SimpleNamespace(
                circuit_id="heat_pump",
                appliance_profile=ApplianceProfile.HEAT_PUMP,
            ),
        ],
        state=SimpleNamespace(
            run_cycle_runtime_seconds_by_circuit={
                "mini_split": 1800.0,
                "heat_pump": 1200.0,
            },
            run_cycle_duty_cycle_by_circuit={
                "mini_split": 25.0,
                "heat_pump": 40.0,
            },
        ),
    )

    context = EnvironmentalContextManager(coordinator).hvac_compressor_context()

    assert context["circuit_ids"] == ["mini_split", "heat_pump"]
    assert context["runtime_minutes"] == 50.0
    assert context["duty_cycle_percent"] == 40.0


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


def test_heat_pump_weather_context_keeps_heating_history_separate() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    coordinator = SimpleNamespace(
        state=SimpleNamespace(
            run_cycle_runtime_seconds_by_circuit={"heat_pump": 1800.0},
            run_cycle_duty_cycle_by_circuit={"heat_pump": 25.0},
            run_cycle_count_by_circuit={"heat_pump": 2},
            weather_context_by_circuit={},
        ),
        store_data=SimpleNamespace(
            weather_context_history_by_circuit={},
            weather_context_by_circuit={},
        ),
        context_builder=SimpleNamespace(
            outdoor_temperature_entity=lambda: "sensor.outdoor_temperature",
            temperature_reading_for_entity=lambda _entity_id: {
                "temperature_f": 40.0,
                "display_temperature": 40.0,
                "display_unit": "°F",
                "source_unit": "°F",
            },
            time_zone=lambda: None,
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    manager = EnvironmentalContextManager(coordinator)

    manager.refresh_weather_context_state(
        SimpleNamespace(
            circuit_id="heat_pump",
            appliance_profile=ApplianceProfile.HEAT_PUMP,
        ),
        now,
    )

    evidence = coordinator.store_data.weather_context_by_circuit["heat_pump"]
    history = coordinator.store_data.weather_context_history_by_circuit["heat_pump"]
    assert evidence["mode"] == "heating"
    assert history[0]["mode"] == "heating"


def test_mini_split_weather_history_keeps_per_mode_runtime() -> None:
    coordinator = SimpleNamespace(
        store_data=SimpleNamespace(weather_context_history_by_circuit={}),
        context_builder=SimpleNamespace(time_zone=lambda: None),
        state=SimpleNamespace(run_cycle_count_by_circuit={"mini_split": 3}),
    )
    manager = EnvironmentalContextManager(coordinator)

    for hour, temperature, runtime, duty, mode in (
        (9, 45.0, 30.0, 50.0, "heating"),
        (10, 80.0, 45.0, 25.0, "cooling"),
        (11, 45.0, 55.0, 50.0, "heating"),
    ):
        manager.append_weather_context_history(
            "mini_split",
            datetime(2026, 1, 1, hour, tzinfo=UTC),
            temperature=temperature,
            runtime_minutes=runtime,
            duty_cycle_percent=duty,
            mode=mode,
        )

    history = coordinator.store_data.weather_context_history_by_circuit["mini_split"]
    assert [(sample["mode"], sample["runtime_minutes"]) for sample in history] == [
        ("cooling", 15.0),
        ("heating", 40.0),
    ]
    heating = next(sample for sample in history if sample["mode"] == "heating")
    assert heating["_mode_elapsed_minutes"] == 120.0
    runtime, _, _ = environmental_context._weather_context_mode_metrics(
        history,
        datetime(2026, 1, 1, 11, tzinfo=UTC),
        None,
        mode="heating",
        runtime_minutes=55.0,
        duty_cycle_percent=50.0,
    )
    assert runtime == 40.0


def test_mini_split_weather_history_keeps_zero_runtime_elapsed_time() -> None:
    coordinator = SimpleNamespace(
        store_data=SimpleNamespace(weather_context_history_by_circuit={}),
        context_builder=SimpleNamespace(time_zone=lambda: None),
        state=SimpleNamespace(run_cycle_count_by_circuit={"mini_split": 0}),
    )
    manager = EnvironmentalContextManager(coordinator)

    for hour, temperature, runtime, duty, mode in (
        (9, 45.0, 0.0, 0.0, "heating"),
        (10, 45.0, 0.0, 0.0, "heating"),
        (11, 80.0, 10.0, 1.0, "cooling"),
    ):
        manager.append_weather_context_history(
            "mini_split",
            datetime(2026, 1, 1, hour, tzinfo=UTC),
            temperature=temperature,
            runtime_minutes=runtime,
            duty_cycle_percent=duty,
            mode=mode,
        )

    history = coordinator.store_data.weather_context_history_by_circuit["mini_split"]
    heating = next(sample for sample in history if sample["mode"] == "heating")
    assert heating["_mode_elapsed_minutes"] == 60.0
