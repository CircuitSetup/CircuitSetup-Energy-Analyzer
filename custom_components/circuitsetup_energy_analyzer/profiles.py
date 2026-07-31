from __future__ import annotations

from dataclasses import dataclass

from .const import MIN_LEARNING_DAYS
from .models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    SensorRole,
)


def supports_direct_appliance_analysis(config: CircuitConfig) -> bool:
    """Return whether aggregate measurements represent one direct appliance."""
    if isinstance(config, dict):
        mode = config.get("mode", CircuitMode.SINGLE_PHASE)
        profile = config.get("appliance_profile", ApplianceProfile.MIXED)
        power_flow = config.get("power_flow", PowerFlowMode.LOAD)
    else:
        mode = getattr(config, "mode", CircuitMode.SINGLE_PHASE)
        profile = config.appliance_profile
        power_flow = getattr(config, "power_flow", PowerFlowMode.LOAD)
    return (
        mode not in {CircuitMode.MIXED, CircuitMode.MAINS_NILM}
        and profile not in {ApplianceProfile.MIXED, ApplianceProfile.MAINS_NILM}
        and power_flow == PowerFlowMode.LOAD
    )


@dataclass(frozen=True, slots=True)
class ProfileDefinition:
    """Static analysis requirements for an appliance profile."""

    appliance_profile: ApplianceProfile
    supported_modes: frozenset[CircuitMode]
    required_roles: frozenset[SensorRole]
    recommended_roles: frozenset[SensorRole]
    features: frozenset[str]
    minimum_cycles: int = 0
    minimum_learning_days: int = MIN_LEARNING_DAYS
    experimental: bool = False


_SINGLE_PHASE_POWER = frozenset({CircuitMode.SINGLE_PHASE})
_BASIC_POWER_ROLES = frozenset({SensorRole.REAL_POWER, SensorRole.CURRENT})
_POWER_CONTEXT = frozenset({
    SensorRole.VOLTAGE,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.ENERGY,
})
_MOTOR_FEATURES = frozenset({
    "start_signature",
    "stop_signature",
    "steady_window",
    "duty_cycle",
})
_RESISTIVE_FEATURES = frozenset({
    "thermal_cycle",
    "steady_window",
    "large_persistent_change",
})


_PROFILE_DEFINITIONS: dict[ApplianceProfile, ProfileDefinition] = {
    ApplianceProfile.REFRIGERATOR: ProfileDefinition(
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=frozenset({
            SensorRole.REACTIVE_POWER,
            SensorRole.APPARENT_POWER,
            SensorRole.POWER_FACTOR,
            SensorRole.ENERGY,
        }),
        features=frozenset({
            "compressor_cycle",
            "cold_storage_cycle_signature_change",
            "defrost_cycle",
            "door_open_hint",
        }),
        minimum_cycles=20,
    ),
    ApplianceProfile.FREEZER: ProfileDefinition(
        appliance_profile=ApplianceProfile.FREEZER,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=frozenset({
            SensorRole.REACTIVE_POWER,
            SensorRole.APPARENT_POWER,
            SensorRole.POWER_FACTOR,
            SensorRole.ENERGY,
        }),
        features=frozenset({
            "compressor_cycle",
            "cold_storage_cycle_signature_change",
            "defrost_cycle",
            "temperature_drift_hint",
        }),
        minimum_cycles=20,
    ),
    ApplianceProfile.HVAC: ProfileDefinition(
        appliance_profile=ApplianceProfile.HVAC,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT,
        features=frozenset({
            "compressor_start",
            "aux_heat_stage",
            "fan_only",
            "leg_imbalance",
            "short_cycle",
        }),
        minimum_cycles=12,
    ),
    ApplianceProfile.HVAC_COMPRESSOR: ProfileDefinition(
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT | frozenset({SensorRole.CURRENT}),
        features=_MOTOR_FEATURES
        | frozenset({"compressor_start", "leg_imbalance", "short_cycle"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.HEAT_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.HEAT_PUMP,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT | frozenset({SensorRole.CURRENT}),
        features=frozenset({
            "compressor_start",
            "aux_heat_stage",
            "leg_imbalance",
            "short_cycle",
        }),
        minimum_cycles=12,
    ),
    ApplianceProfile.MINI_SPLIT: ProfileDefinition(
        appliance_profile=ApplianceProfile.MINI_SPLIT,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT | frozenset({SensorRole.CURRENT}),
        features=frozenset({"inverter_cycle"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.HVAC_BLOWER: ProfileDefinition(
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES | frozenset({"fan_only", "airflow_load_hint"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.ELECTRIC_HEAT: ProfileDefinition(
        appliance_profile=ApplianceProfile.ELECTRIC_HEAT,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({SensorRole.VOLTAGE, SensorRole.ENERGY}),
        features=_RESISTIVE_FEATURES | frozenset({"aux_heat_stage"}),
        minimum_cycles=8,
    ),
    ApplianceProfile.WATER_HEATER: ProfileDefinition(
        appliance_profile=ApplianceProfile.WATER_HEATER,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({SensorRole.VOLTAGE, SensorRole.ENERGY}),
        features=frozenset(
            {"element_cycle", "recovery_window", "large_persistent_change"}
        ),
        minimum_cycles=10,
    ),
    ApplianceProfile.OVEN: ProfileDefinition(
        appliance_profile=ApplianceProfile.OVEN,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({SensorRole.VOLTAGE, SensorRole.ENERGY}),
        features=frozenset({"preheat", "temperature_hold", "element_cycle"}),
        minimum_cycles=8,
    ),
    ApplianceProfile.MICROWAVE: ProfileDefinition(
        appliance_profile=ApplianceProfile.MICROWAVE,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({
            SensorRole.CURRENT,
            SensorRole.VOLTAGE,
            SensorRole.POWER_FACTOR,
            SensorRole.ENERGY,
        }),
        features=frozenset({
            "cook_cycle",
            "short_cycle",
            "door_open_hint",
            "large_persistent_change",
        }),
        minimum_cycles=8,
    ),
    ApplianceProfile.DISHWASHER: ProfileDefinition(
        appliance_profile=ApplianceProfile.DISHWASHER,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=frozenset({"wash_cycle"}),
        minimum_cycles=8,
    ),
    ApplianceProfile.THREE_D_PRINTER: ProfileDefinition(
        appliance_profile=ApplianceProfile.THREE_D_PRINTER,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT | frozenset({SensorRole.CURRENT}),
        features=frozenset({"print_session"}),
        minimum_cycles=5,
    ),
    ApplianceProfile.WASHER: ProfileDefinition(
        appliance_profile=ApplianceProfile.WASHER,
        supported_modes=_SINGLE_PHASE_POWER,
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES
        | frozenset({
            "wash_motor",
            "drain_pump",
            "spin_motor",
            "fill_valve_cycle",
            "unbalanced_load_hint",
        }),
        minimum_cycles=8,
    ),
    ApplianceProfile.DRYER: ProfileDefinition(
        appliance_profile=ApplianceProfile.DRYER,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset(
            {SensorRole.CURRENT, SensorRole.VOLTAGE, SensorRole.ENERGY}
        ),
        features=frozenset({"heat_cycle", "motor_signature", "end_of_cycle"}),
        minimum_cycles=8,
    ),
    ApplianceProfile.POOL_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.POOL_PUMP,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES | frozenset({"schedule_adherence"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.WATER_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.WATER_PUMP,
        supported_modes=frozenset({
            CircuitMode.SINGLE_PHASE,
            CircuitMode.DUAL_PHASE,
        }),
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES | frozenset({"pressure_cycle_hint"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.WELL_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.WELL_PUMP,
        supported_modes=frozenset({
            CircuitMode.SINGLE_PHASE,
            CircuitMode.DUAL_PHASE,
        }),
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES | frozenset({"pressure_cycle_hint"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.SUMP_PUMP: ProfileDefinition(
        appliance_profile=ApplianceProfile.SUMP_PUMP,
        supported_modes=frozenset({
            CircuitMode.SINGLE_PHASE,
            CircuitMode.DUAL_PHASE,
        }),
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES | frozenset({"storm_frequency_hint"}),
        minimum_cycles=12,
    ),
    ApplianceProfile.EV_CHARGER: ProfileDefinition(
        appliance_profile=ApplianceProfile.EV_CHARGER,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset(
            {SensorRole.CURRENT, SensorRole.VOLTAGE, SensorRole.ENERGY}
        ),
        features=frozenset({"charge_session", "ramp_rate", "leg_imbalance"}),
        minimum_cycles=5,
    ),
    ApplianceProfile.SOLAR_INVERTER: ProfileDefinition(
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        supported_modes=frozenset({CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=_POWER_CONTEXT,
        features=frozenset({
            "export_profile",
            "production_ramp",
            "voltage_coupling",
            "inverter_power_factor",
        }),
        minimum_cycles=0,
        minimum_learning_days=max(MIN_LEARNING_DAYS, 7),
    ),
    ApplianceProfile.MOTOR_LOAD: ProfileDefinition(
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=_BASIC_POWER_ROLES,
        recommended_roles=_POWER_CONTEXT,
        features=_MOTOR_FEATURES,
        minimum_cycles=12,
    ),
    ApplianceProfile.RESISTIVE_LOAD: ProfileDefinition(
        appliance_profile=ApplianceProfile.RESISTIVE_LOAD,
        supported_modes=frozenset({CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({SensorRole.VOLTAGE, SensorRole.ENERGY}),
        features=_RESISTIVE_FEATURES,
        minimum_cycles=8,
    ),
    ApplianceProfile.MIXED: ProfileDefinition(
        appliance_profile=ApplianceProfile.MIXED,
        supported_modes=frozenset(
            {CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE, CircuitMode.MIXED}
        ),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({
            SensorRole.CURRENT,
            SensorRole.VOLTAGE,
            SensorRole.REACTIVE_POWER,
            SensorRole.APPARENT_POWER,
            SensorRole.POWER_FACTOR,
            SensorRole.ENERGY,
        }),
        features=frozenset({
            "large_persistent_change",
            "feed_quality",
            "recurring_signature_hint",
            "unknown_load_cluster",
        }),
        minimum_cycles=20,
    ),
    ApplianceProfile.MAINS_NILM: ProfileDefinition(
        appliance_profile=ApplianceProfile.MAINS_NILM,
        supported_modes=frozenset({CircuitMode.MAINS_NILM}),
        required_roles=frozenset({SensorRole.REAL_POWER}),
        recommended_roles=frozenset({
            SensorRole.CURRENT,
            SensorRole.VOLTAGE,
            SensorRole.REACTIVE_POWER,
            SensorRole.APPARENT_POWER,
            SensorRole.POWER_FACTOR,
            SensorRole.ENERGY,
        }),
        features=frozenset({
            "aggregate_edge",
            "known_load_match",
            "unmatched_event",
            "recurring_signature",
            "possible_load_class",
        }),
        minimum_cycles=30,
        minimum_learning_days=max(MIN_LEARNING_DAYS, 7),
        experimental=True,
    ),
}


def get_profile_definition(profile: ApplianceProfile) -> ProfileDefinition:
    """Return the static definition for an appliance profile."""
    return _PROFILE_DEFINITIONS[profile]
