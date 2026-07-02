from __future__ import annotations

from datetime import UTC, datetime
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
