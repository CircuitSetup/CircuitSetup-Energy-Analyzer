from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.source_samples import (
    SourceSampleBuilder,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


def test_dual_phase_stale_current_uses_combined_power_threshold() -> None:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    stale = now - timedelta(minutes=30)
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.dryer_l1_power", SensorRole.REAL_POWER, leg="l1"),
            SensorRef("sensor.dryer_l1_current", SensorRole.CURRENT, leg="l1"),
            SensorRef("sensor.dryer_l2_power", SensorRole.REAL_POWER, leg="l2"),
            SensorRef("sensor.dryer_l2_current", SensorRole.CURRENT, leg="l2"),
        ),
    )

    class FakeStates:
        def get(self, entity_id: str):
            value, unit, updated = {
                "sensor.dryer_l1_power": ("150", "W", now),
                "sensor.dryer_l1_current": ("0.001", "A", stale),
                "sensor.dryer_l2_power": ("150", "W", now),
                "sensor.dryer_l2_current": ("0.001", "A", stale),
            }[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=updated,
            )

    builder = SourceSampleBuilder(SimpleNamespace(states=FakeStates()))

    sample = builder.sample_for_config(
        config,
        now,
        inactive_power_threshold_w=200.0,
    )

    assert sample.real_power == 300.0
    assert sample.current is None
    assert "sensor.dryer_l1_current stale" in sample.quality_issues
    assert "sensor.dryer_l2_current stale" in sample.quality_issues


def test_mains_nilm_suppresses_stale_current_while_aggregate_power_is_inactive() -> (
    None
):
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_current", SensorRole.CURRENT),
        ),
    )

    class FakeStates:
        def get(self, entity_id: str):
            value, unit, updated = {
                "sensor.mains_power": ("40", "W", now),
                "sensor.mains_current": (
                    "0.001",
                    "A",
                    now - timedelta(minutes=30),
                ),
            }[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=updated,
            )

    builder = SourceSampleBuilder(SimpleNamespace(states=FakeStates()))

    sample = builder.sample_for_config(
        config,
        now,
        inactive_power_threshold_w=50.0,
    )

    assert sample.real_power == 40.0
    assert sample.current is None
    assert "sensor.mains_current stale" not in sample.quality_issues


def test_mains_nilm_uses_live_metadata_role_for_parallel_sources() -> None:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    older = now - timedelta(seconds=5)
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_l1_power", SensorRole.REAL_POWER, leg="l1"),
            SensorRef("sensor.mains_l2_power", SensorRole.REAL_POWER, leg="l2"),
            SensorRef("sensor.mains_var", SensorRole.REAL_POWER),
        ),
    )

    class FakeStates:
        def get(self, entity_id: str):
            value, unit, updated = {
                "sensor.mains_l1_power": ("100", "W", older),
                "sensor.mains_l2_power": ("90", "W", now),
                "sensor.mains_var": ("20", "var", now),
            }[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=updated,
            )

    sample = SourceSampleBuilder(
        SimpleNamespace(states=FakeStates())
    ).sample_for_config(config, now)

    assert sample.real_power == 190.0
    assert sample.reactive_power == 20.0
    assert dict(sample.source_updated_at_by_role)[SensorRole.REAL_POWER] == older
