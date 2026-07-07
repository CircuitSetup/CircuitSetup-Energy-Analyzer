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


def test_recommended_v1_appliance_profiles_have_distinct_analysis_contexts() -> None:
    compressor = get_profile_definition(ApplianceProfile.HVAC_COMPRESSOR)
    blower = get_profile_definition(ApplianceProfile.HVAC_BLOWER)
    electric_heat = get_profile_definition(ApplianceProfile.ELECTRIC_HEAT)
    water_pump = get_profile_definition(ApplianceProfile.WATER_PUMP)
    pool_pump = get_profile_definition(ApplianceProfile.POOL_PUMP)
    sump_pump = get_profile_definition(ApplianceProfile.SUMP_PUMP)

    assert CircuitMode.DUAL_PHASE in compressor.supported_modes
    assert "compressor_start" in compressor.features
    assert "short_cycle" in compressor.features
    assert SensorRole.POWER_FACTOR in compressor.recommended_roles

    assert blower.supported_modes == {CircuitMode.SINGLE_PHASE}
    assert "fan_only" in blower.features
    assert SensorRole.REACTIVE_POWER in blower.recommended_roles

    assert CircuitMode.DUAL_PHASE in electric_heat.supported_modes
    assert "aux_heat_stage" in electric_heat.features
    assert "large_persistent_change" in electric_heat.features

    assert water_pump.appliance_profile is ApplianceProfile.WATER_PUMP
    assert "pressure_cycle_hint" in water_pump.features
    assert "schedule_adherence" in pool_pump.features
    assert "storm_frequency_hint" in sump_pump.features


def test_washer_profile_supports_single_phase_motor_analysis_context() -> None:
    washer_profile = next(
        (profile for profile in ApplianceProfile if profile.value == "washer"),
        None,
    )

    assert washer_profile is not None

    definition = get_profile_definition(washer_profile)

    assert definition.supported_modes == {CircuitMode.SINGLE_PHASE}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert SensorRole.CURRENT in definition.required_roles
    assert SensorRole.REACTIVE_POWER in definition.recommended_roles
    assert SensorRole.APPARENT_POWER in definition.recommended_roles
    assert SensorRole.POWER_FACTOR in definition.recommended_roles
    assert SensorRole.ENERGY in definition.recommended_roles
    assert "spin_motor" in definition.features
    assert "unbalanced_load_hint" in definition.features
    assert definition.minimum_cycles >= 8


def test_microwave_profile_supports_short_single_phase_cycles() -> None:
    definition = get_profile_definition(ApplianceProfile.MICROWAVE)

    assert definition.supported_modes == {CircuitMode.SINGLE_PHASE}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert SensorRole.CURRENT in definition.recommended_roles
    assert SensorRole.ENERGY in definition.recommended_roles
    assert "cook_cycle" in definition.features
    assert "short_cycle" in definition.features
    assert definition.minimum_cycles >= 8


def test_ev_charger_profile_supports_car_charger_analysis_context() -> None:
    definition = get_profile_definition(ApplianceProfile.EV_CHARGER)

    assert definition.supported_modes == {
        CircuitMode.SINGLE_PHASE,
        CircuitMode.DUAL_PHASE,
    }
    assert SensorRole.REAL_POWER in definition.required_roles
    assert SensorRole.CURRENT in definition.recommended_roles
    assert SensorRole.VOLTAGE in definition.recommended_roles
    assert SensorRole.ENERGY in definition.recommended_roles
    assert "charge_session" in definition.features
    assert "ramp_rate" in definition.features
    assert "leg_imbalance" in definition.features


def test_mains_nilm_profile_is_experimental_aggregate_mode() -> None:
    definition = get_profile_definition(ApplianceProfile.MAINS_NILM)

    assert definition.supported_modes == {CircuitMode.MAINS_NILM}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert "recurring_signature" in definition.features
    assert definition.minimum_learning_days >= 7


def test_solar_inverter_profile_supports_generation_power_quality() -> None:
    definition = get_profile_definition(ApplianceProfile.SOLAR_INVERTER)

    assert definition.supported_modes == {CircuitMode.DUAL_PHASE}
    assert SensorRole.REAL_POWER in definition.required_roles
    assert SensorRole.VOLTAGE in definition.recommended_roles
    assert SensorRole.POWER_FACTOR in definition.recommended_roles
    assert "export_profile" in definition.features


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
