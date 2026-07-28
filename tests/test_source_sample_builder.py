from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
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


def test_source_sample_builder_uses_registered_demo_sources_for_dual_phase() -> None:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    canonical_l1 = "sensor.cs_energy_analyzer_demo_dryer_l1_active_power"
    registered_l1 = "sensor.cs_energy_analyzer_demo_dryer_l1_active_power_2"
    l2 = "sensor.cs_energy_analyzer_demo_dryer_l2_active_power"
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef(canonical_l1, SensorRole.REAL_POWER, leg="l1"),
            SensorRef(l2, SensorRole.REAL_POWER, leg="l2"),
        ),
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                registered_l1: "1200",
                l2: "900",
            }
            if entity_id not in values:
                return None
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    registry = SimpleNamespace(
        entities={
            registered_l1: SimpleNamespace(
                entity_id=registered_l1,
                unique_id=(
                    "entry-1_demo_source_exact_"
                    "cs_energy_analyzer_demo_dryer_l1_active_power"
                ),
                config_entry_id="entry-1",
                platform=DOMAIN,
            )
        }
    )
    builder = SourceSampleBuilder(
        SimpleNamespace(states=FakeStates(), entity_registry=registry),
        entry_id="entry-1",
    )

    sample = builder.sample_for_config(config, now)

    assert sample.real_power == 2100
    assert sample.raw_real_power == 2100
    assert sample.leg_a_real_power == 1200
    assert sample.leg_b_real_power == 900
    assert not sample.quality_issues


def test_source_sample_builder_skips_demo_registry_for_regular_sources() -> None:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )

    class FakeStates:
        def get(self, entity_id: str):
            if entity_id != "sensor.fridge_power":
                return None
            return SimpleNamespace(
                state="125",
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    builder = SourceSampleBuilder(
        SimpleNamespace(states=FakeStates(), entity_registry=object()),
        entry_id="entry-1",
    )

    def fail_if_called() -> dict[str, str]:
        raise AssertionError("demo registry lookup should not run")

    builder.registered_demo_source_entity_ids = fail_if_called

    states = builder.source_states_for(config, now)

    assert states["sensor.fridge_power"].state == "125"


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

    builder = SourceSampleBuilder(
        SimpleNamespace(states=FakeStates()),
        entry_id="entry-1",
    )

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

    builder = SourceSampleBuilder(
        SimpleNamespace(states=FakeStates()),
        entry_id="entry-1",
    )

    sample = builder.sample_for_config(
        config,
        now,
        inactive_power_threshold_w=50.0,
    )

    assert sample.real_power == 40.0
    assert sample.current is None
    assert "sensor.mains_current stale" not in sample.quality_issues
