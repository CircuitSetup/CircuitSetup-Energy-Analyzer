from datetime import UTC, datetime

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitEvent,
    CircuitMode,
    EventType,
    RetentionMode,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.profiles import (
    get_profile_definition,
)


def test_domain_is_stable() -> None:
    assert DOMAIN == "circuitsetup_energy_analyzer"


def test_refrigerator_profile_requires_single_phase_power_roles() -> None:
    definition = get_profile_definition(ApplianceProfile.REFRIGERATOR)

    assert definition.appliance_profile is ApplianceProfile.REFRIGERATOR
    assert definition.supported_modes == {CircuitMode.SINGLE_PHASE}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert SensorRole.CURRENT in definition.required_roles
    assert SensorRole.REACTIVE_POWER in definition.recommended_roles
    assert definition.minimum_cycles >= 20


def test_profile_definition_collections_cannot_be_mutated() -> None:
    definition = get_profile_definition(ApplianceProfile.REFRIGERATOR)

    with pytest.raises(AttributeError):
        definition.supported_modes.add(CircuitMode.DUAL_PHASE)

    with pytest.raises(AttributeError):
        definition.features.add("unexpected_feature")


def test_hvac_profile_supports_dual_phase_and_voltage_context() -> None:
    definition = get_profile_definition(ApplianceProfile.HVAC)

    assert CircuitMode.DUAL_PHASE in definition.supported_modes
    assert SensorRole.VOLTAGE in definition.recommended_roles
    assert "leg_imbalance" in definition.features


def test_mains_nilm_profile_is_experimental_aggregate_mode() -> None:
    definition = get_profile_definition(ApplianceProfile.MAINS_NILM)

    assert definition.supported_modes == {CircuitMode.MAINS_NILM}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert "recurring_signature" in definition.features
    assert definition.minimum_learning_days >= 7


def test_circuit_event_features_are_readable_but_immutable() -> None:
    event = CircuitEvent(
        timestamp=datetime(2026, 6, 2, tzinfo=UTC),
        circuit_id="kitchen_refrigerator",
        event_type=EventType.START,
        features={"startup_power_w": 725.0},
    )

    assert event.features["startup_power_w"] == 725.0
    assert event.features.get("startup_power_w") == 725.0

    with pytest.raises(TypeError):
        event.features["startup_power_w"] = 800.0


def test_retention_mode_values_are_stable() -> None:
    assert {mode.value for mode in RetentionMode} == {
        "lightweight",
        "standard",
        "diagnostic",
    }
