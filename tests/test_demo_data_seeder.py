from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.demo_data import (
    DemoDataSeeder,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.standby import StandbySettings
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData
from custom_components.circuitsetup_energy_analyzer.usage import EnergyUsageSettings


class _DirtyTracker:
    def __init__(self) -> None:
        self.dirty = False

    def mark_dirty(self) -> None:
        self.dirty = True


class _ContextBuilder:
    def __init__(self, time_zone: str | None) -> None:
        self._time_zone = time_zone

    def time_zone(self) -> str | None:
        return self._time_zone


class _Coordinator:
    def __init__(self, *, time_zone: str | None = "UTC") -> None:
        self.store_data = FeatureStoreData()
        self.context_builder = _ContextBuilder(time_zone)
        self.store_persistence = _DirtyTracker()


def _demo_config(
    circuit_key: str,
    *,
    profile: ApplianceProfile = ApplianceProfile.REFRIGERATOR,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
    sensor_role: SensorRole = SensorRole.ENERGY,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id=f"cs_energy_analyzer_demo_{circuit_key}",
        name=f"Demo {circuit_key}",
        appliance_profile=profile,
        mode=mode,
        sensors=(
            SensorRef(
                entity_id=(
                    "sensor.cs_energy_analyzer_demo_"
                    f"{circuit_key}_{sensor_role.value}"
                ),
                role=sensor_role,
            ),
        ),
    )


def test_demo_data_seeder_energy_usage_history_uses_ha_local_seed_dates() -> None:
    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = _Coordinator(time_zone="America/New_York")
    seeder = DemoDataSeeder(coordinator)
    config = _demo_config("refrigerator")

    seeder.seed_energy_usage_history(
        config,
        SimpleNamespace(energy=52.6),
        now,
        EnergyUsageSettings(window_days=7),
    )

    history = coordinator.store_data.energy_usage_by_circuit[config.circuit_id]
    assert history["_demo_seed_date"] == "2026-05-31"
    assert [day["date"] for day in history["days"]] == [
        "2026-05-24",
        "2026-05-25",
        "2026-05-26",
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
        "2026-05-30",
    ]
    assert coordinator.store_persistence.dirty is True


def test_demo_data_seeder_weather_context_history_uses_ha_local_prior_days() -> None:
    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    coordinator = _Coordinator(time_zone="America/New_York")
    seeder = DemoDataSeeder(coordinator)
    config = _demo_config(
        "hvac",
        profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensor_role=SensorRole.REAL_POWER,
    )

    seeder.seed_weather_context_history(
        config,
        now,
        outdoor_temperature=86.0,
    )

    history = coordinator.store_data.weather_context_history_by_circuit[
        config.circuit_id
    ]
    assert [item["timestamp"] for item in history] == [
        "2026-05-24T16:00:00+00:00",
        "2026-05-25T16:00:00+00:00",
        "2026-05-26T16:00:00+00:00",
        "2026-05-27T16:00:00+00:00",
        "2026-05-28T16:00:00+00:00",
    ]
    assert coordinator.store_persistence.dirty is True


def test_demo_data_seeder_standby_history_uses_processor_context() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = _Coordinator()
    seeder = DemoDataSeeder(coordinator)
    config = _demo_config(
        "refrigerator",
        sensor_role=SensorRole.REAL_POWER,
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id=config.circuit_id,
        real_power=185.0,
        power_flow=PowerFlowMode.LOAD,
    )

    seeder.seed_standby_history(
        config,
        sample,
        SimpleNamespace(now=now),
        StandbySettings(window_hours=24, min_samples=6, standby_threshold_w=9.0),
    )

    samples = coordinator.store_data.standby_by_circuit[config.circuit_id]["samples"]
    assert len(samples) == 5
    assert samples[0]["timestamp"] < samples[-1]["timestamp"]
    assert samples[0]["real_power_w"] >= 13.0
    assert coordinator.store_persistence.dirty is True


def test_coordinator_wires_demo_data_seeder_to_processor_callbacks() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace(data={}))

    assert (
        coordinator._power_quality_processor._seed_demo_event_history.__self__
        is coordinator.demo_data
    )
    assert (
        coordinator._power_quality_processor._seed_demo_power_quality_baselines.__self__
        is coordinator.demo_data
    )
    assert (
        coordinator._energy_usage_processor._seed_demo_history.__self__
        is coordinator.demo_data
    )
    assert (
        coordinator._standby_processor._seed_demo_history.__self__
        is coordinator.demo_data
    )
