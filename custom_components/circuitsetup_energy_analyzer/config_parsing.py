from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from .const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SOURCE_ENTITIES,
    DEFAULT_RETENTION_MODE,
)
from .context_sources import (
    string_list_from_sources as _string_list_from_sources,
)
from .discovery import friendly_source_name
from .managers.source_samples import (
    entity_id_leg_hint as _entity_id_leg_hint,
)
from .models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    RetentionMode,
    SensorRef,
    SensorRole,
)


def retention_mode_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> RetentionMode:
    options = options or {}
    raw = options.get(
        CONF_RETENTION_MODE,
        entry_data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
    )
    try:
        return RetentionMode(str(raw))
    except ValueError:
        return RetentionMode.STANDARD


def circuit_configs_from_entry_data(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[CircuitConfig, ...]:
    configs: list[CircuitConfig] = []
    options = options or {}
    default_retention_mode = retention_mode_from_sources(entry_data, options)
    raw_circuits = (
        options[CONF_CIRCUITS]
        if CONF_CIRCUITS in options
        else entry_data.get(CONF_CIRCUITS, [])
    )
    for raw_circuit in raw_circuits:
        config = _circuit_config_from_raw(raw_circuit, default_retention_mode)
        if config is not None:
            configs.append(config)

    configs = _configs_with_merged_source_entity_refs(
        entry_data,
        options,
        configs,
    )
    configs.extend(
        _source_entity_configs_from_sources(
            entry_data,
            options,
            default_retention_mode,
            configs,
        )
    )

    if (
        _experimental_nilm_enabled(entry_data, options)
        and not any(config.mode is CircuitMode.MAINS_NILM for config in configs)
    ):
        mains_config = mains_context_config_from_sources(entry_data, options)
        if mains_config is not None:
            configs.append(mains_config)
    return tuple(configs)


def _configs_with_merged_source_entity_refs(
    entry_data: dict[str, Any],
    options: dict[str, Any],
    existing_configs: Iterable[CircuitConfig],
) -> list[CircuitConfig]:
    configs = list(existing_configs)
    if not configs:
        return configs

    source_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_SOURCE_ENTITIES,
    )
    if not source_entities:
        return configs

    mains_entities = set(
        _string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
    config_index = _config_index_by_source_circuit_id(configs)
    existing_source_entities = {
        sensor.entity_id for config in configs for sensor in config.sensors
    }
    for entity_id in source_entities:
        if entity_id in mains_entities or entity_id in existing_source_entities:
            continue
        config_index_value = config_index.get(
            _source_circuit_id_from_entity_id(entity_id)
        )
        if config_index_value is None:
            continue
        config = configs[config_index_value]
        configs[config_index_value] = replace(
            config,
            sensors=(
                *config.sensors,
                SensorRef(
                    entity_id=entity_id,
                    role=_sensor_role_from_entity_id(entity_id),
                    leg=_entity_id_leg_hint(entity_id),
                ),
            ),
        )
        existing_source_entities.add(entity_id)
    return configs


def _config_index_by_source_circuit_id(
    configs: Iterable[CircuitConfig],
) -> dict[str, int]:
    config_index: dict[str, int] = {}
    for index, config in enumerate(configs):
        for value in (config.circuit_id, config.name):
            circuit_id = _canonical_source_circuit_id(value)
            if circuit_id:
                config_index.setdefault(circuit_id, index)
    return config_index


def _source_entity_configs_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    retention_mode: RetentionMode,
    existing_configs: Iterable[CircuitConfig],
) -> tuple[CircuitConfig, ...]:
    source_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_SOURCE_ENTITIES,
    )
    if not source_entities:
        return ()

    mains_entities = set(
        _string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
    existing_circuit_ids = {config.circuit_id for config in existing_configs}
    existing_source_entities = {
        sensor.entity_id
        for config in existing_configs
        for sensor in config.sensors
    }
    sensors_by_circuit_id: dict[str, list[SensorRef]] = {}
    for entity_id in source_entities:
        if entity_id in mains_entities or entity_id in existing_source_entities:
            continue
        circuit_id = _source_circuit_id_from_entity_id(entity_id)
        if not circuit_id or circuit_id in existing_circuit_ids:
            continue
        sensors_by_circuit_id.setdefault(circuit_id, []).append(
            SensorRef(
                entity_id=entity_id,
                role=_sensor_role_from_entity_id(entity_id),
                leg=_entity_id_leg_hint(entity_id),
            )
        )

    configs: list[CircuitConfig] = []
    for circuit_id, sensors in sensors_by_circuit_id.items():
        appliance_profile, mode = _appliance_profile_mode_from_circuit_id(circuit_id)
        configs.append(
            CircuitConfig(
                circuit_id=circuit_id,
                name=_friendly_name_from_circuit_id(circuit_id),
                appliance_profile=appliance_profile,
                mode=mode,
                sensors=tuple(sensors),
                retention_mode=retention_mode,
            )
        )
    return tuple(configs)


def _experimental_nilm_enabled(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> bool:
    options = options or {}
    return bool(
        options.get(
            CONF_ENABLE_EXPERIMENTAL_NILM,
            entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
        )
    )


def mains_context_config_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> CircuitConfig | None:
    mains_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_MAINS_SOURCE_ENTITIES,
    )
    if not mains_entities:
        return None

    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=tuple(
            SensorRef(
                entity_id=entity_id,
                role=_sensor_role_from_entity_id(entity_id),
                leg=_entity_id_leg_hint(entity_id),
            )
            for entity_id in mains_entities
        ),
        retention_mode=retention_mode_from_sources(entry_data, options),
        power_flow=PowerFlowMode.MAINS_NET,
    )


def _circuit_config_from_raw(
    raw_circuit: Any,
    default_retention_mode: RetentionMode = RetentionMode.STANDARD,
) -> CircuitConfig | None:
    if isinstance(raw_circuit, CircuitConfig):
        return raw_circuit
    if not isinstance(raw_circuit, dict):
        return None

    circuit_id = raw_circuit.get("circuit_id")
    if not circuit_id:
        return None

    try:
        appliance_profile = _appliance_profile_from_raw_value(
            raw_circuit.get("appliance_profile", ApplianceProfile.MIXED.value)
        )
        mode = CircuitMode(raw_circuit.get("mode", CircuitMode.MIXED.value))
        if appliance_profile is ApplianceProfile.SOLAR_INVERTER:
            mode = CircuitMode.DUAL_PHASE
        retention_mode = RetentionMode(
            raw_circuit.get("retention_mode", default_retention_mode.value)
        )
    except ValueError:
        return None

    return CircuitConfig(
        circuit_id=str(circuit_id),
        name=str(raw_circuit.get("name") or circuit_id),
        appliance_profile=appliance_profile,
        mode=mode,
        sensors=_sensor_refs_from_raw(raw_circuit),
        retention_mode=retention_mode,
        power_flow=_power_flow_mode_from_raw(raw_circuit, appliance_profile, mode),
        energy_usage_window_days=_positive_int_from_raw(
            raw_circuit,
            "energy_usage_window_days",
            default=7,
        ),
        daily_energy_spike_ratio=_positive_float_from_raw(
            raw_circuit,
            "daily_energy_spike_ratio",
            default=0.25,
        ),
        daily_energy_goal_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "daily_energy_goal_kwh",
        ),
        energy_goal_alert_ratio=_positive_float_from_raw(
            raw_circuit,
            "energy_goal_alert_ratio",
            default=1.0,
        ),
        billing_cycle_start_day=_positive_int_from_raw(
            raw_circuit,
            "billing_cycle_start_day",
            default=1,
        ),
        billing_cycle_budget_kwh=_optional_positive_float_from_raw(
            raw_circuit,
            "billing_cycle_budget_kwh",
        ),
        billing_cycle_budget_alert_ratio=_positive_float_from_raw(
            raw_circuit,
            "billing_cycle_budget_alert_ratio",
            default=1.0,
        ),
        billing_cycle_min_elapsed_days=_positive_int_from_raw(
            raw_circuit,
            "billing_cycle_min_elapsed_days",
            default=3,
        ),
        cost_cycle_start_day=_positive_int_from_raw(
            raw_circuit,
            "cost_cycle_start_day",
            default=1,
        ),
        demand_window_minutes=_positive_int_from_raw(
            raw_circuit,
            "demand_window_minutes",
            default=15,
        ),
        demand_limit_w=_optional_positive_float_from_raw(
            raw_circuit,
            "demand_limit_w",
        ),
        standby_window_hours=_positive_int_from_raw(
            raw_circuit,
            "standby_window_hours",
            default=48,
        ),
        standby_threshold_w=_positive_float_from_raw(
            raw_circuit,
            "standby_threshold_w",
            default=8.0,
        ),
        always_on_alert_w=_optional_positive_float_from_raw(
            raw_circuit,
            "always_on_alert_w",
        ),
        standby_min_samples=_positive_int_from_raw(
            raw_circuit,
            "standby_min_samples",
            default=24,
        ),
    )


def _appliance_profile_from_raw_value(value: Any) -> ApplianceProfile:
    normalized = str(value or ApplianceProfile.MIXED.value).strip().lower()
    return ApplianceProfile(normalized)


def _power_flow_mode_from_raw(
    raw_circuit: dict[str, Any],
    appliance_profile: ApplianceProfile,
    mode: CircuitMode,
) -> PowerFlowMode:
    raw_power_flow = raw_circuit.get("power_flow")
    if raw_power_flow is not None:
        value = str(raw_power_flow).strip().lower()
        try:
            return PowerFlowMode(value)
        except ValueError:
            return PowerFlowMode.LOAD
    if (
        appliance_profile is ApplianceProfile.MAINS_NILM
        or mode is CircuitMode.MAINS_NILM
    ):
        return PowerFlowMode.MAINS_NET
    if appliance_profile is ApplianceProfile.SOLAR_INVERTER:
        return PowerFlowMode.GENERATION
    return PowerFlowMode.LOAD


def _sensor_refs_from_raw(raw_circuit: dict[str, Any]) -> tuple[SensorRef, ...]:
    refs: list[SensorRef] = []
    for raw_sensor in raw_circuit.get("sensors", []):
        ref = _sensor_ref_from_raw(raw_sensor)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _positive_int_from_raw(
    raw: dict[str, Any],
    *keys: str,
    default: int,
) -> int:
    for key in keys:
        if key not in raw:
            continue
        try:
            value = int(raw[key])
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


def _positive_float_from_raw(
    raw: dict[str, Any],
    *keys: str,
    default: float,
) -> float:
    for key in keys:
        if key not in raw:
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return default


def _optional_positive_float_from_raw(
    raw: dict[str, Any],
    *keys: str,
) -> float | None:
    for key in keys:
        if key not in raw:
            continue
        value = _optional_positive_float_value(raw[key], default=None)
        if value is not None:
            return value
    return None


def _optional_positive_float_value(
    value: Any,
    *,
    default: float | None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _sensor_ref_from_raw(raw_sensor: Any) -> SensorRef | None:
    if isinstance(raw_sensor, SensorRef):
        return raw_sensor
    if isinstance(raw_sensor, str):
        return SensorRef(
            entity_id=raw_sensor,
            role=_sensor_role_from_entity_id(raw_sensor),
            leg=_entity_id_leg_hint(raw_sensor),
        )
    if not isinstance(raw_sensor, dict):
        return None

    entity_id = raw_sensor.get("entity_id")
    if not entity_id:
        return None
    try:
        role = SensorRole(raw_sensor.get("role", SensorRole.REAL_POWER.value))
    except ValueError:
        return None
    return SensorRef(
        entity_id=str(entity_id),
        role=role,
        leg=raw_sensor.get("leg"),
        unit=raw_sensor.get("unit"),
    )


_SOURCE_METRIC_SUFFIXES = (
    "_peak_current",
    "_peak_amps",
    "_peak_amp",
    "_peak_a",
    "_reactive_power",
    "_apparent_power",
    "_power_factor",
    "_line_frequency",
    "_real_power",
    "_active_power",
    "_frequency",
    "_current",
    "_voltage",
    "_energy",
    "_watts",
    "_watt",
    "_amps",
    "_amp",
    "_power",
    "_kwh",
    "_mwh",
    "_wh",
    "_var",
    "_va",
    "_pf",
    "_hz",
)
_SOURCE_LEG_SUFFIXES = (
    "_leg_a",
    "_leg_b",
    "_line_a",
    "_line_b",
    "_phase_a",
    "_phase_b",
    "_leg_1",
    "_leg_2",
    "_line_1",
    "_line_2",
    "_phase_1",
    "_phase_2",
    "_leg1",
    "_leg2",
    "_line1",
    "_line2",
    "_phase1",
    "_phase2",
    "_l1",
    "_l2",
)
_ANALYZER_SOURCE_ENTITY_PREFIXES = (
    "circuitsetup_energy_analyzer_",
    "cs_energy_analyzer_",
)
_PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES = ("cs_energy_analyzer_demo_",)


def _sensor_role_from_entity_id(entity_id: str) -> SensorRole:
    object_id = _entity_object_id(entity_id)
    if _has_metric_suffix(
        object_id,
        ("peak_current", "peak_amps", "peak_amp", "peak_a"),
    ):
        return SensorRole.PEAK_CURRENT
    if _has_metric_suffix(object_id, ("power_factor", "pf")):
        return SensorRole.POWER_FACTOR
    if _has_metric_suffix(object_id, ("reactive_power", "reactive", "var")):
        return SensorRole.REACTIVE_POWER
    if _has_metric_suffix(object_id, ("apparent_power", "apparent", "va")):
        return SensorRole.APPARENT_POWER
    if _has_metric_suffix(object_id, ("frequency", "line_frequency", "hz")):
        return SensorRole.FREQUENCY
    if _has_metric_suffix(object_id, ("current", "amps", "amp", "a")):
        return SensorRole.CURRENT
    if _has_metric_suffix(object_id, ("voltage", "volts", "volt", "v")):
        return SensorRole.VOLTAGE
    if _has_metric_suffix(object_id, ("energy", "kwh", "wh", "mwh")):
        return SensorRole.ENERGY
    return SensorRole.REAL_POWER


def _source_circuit_id_from_entity_id(entity_id: str) -> str:
    object_id = _entity_object_id(entity_id)
    return _canonical_source_circuit_id(
        _strip_trailing_source_detail_tokens(object_id)
    )


def _canonical_source_circuit_id(value: Any) -> str:
    circuit_id = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    for preserved_prefix in _PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(preserved_prefix):
            return circuit_id
    for prefix in _ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(prefix):
            return circuit_id.removeprefix(prefix) or circuit_id
    return circuit_id


def _strip_trailing_source_detail_tokens(object_id: str) -> str:
    stripped = object_id
    while True:
        for suffix in (*_SOURCE_METRIC_SUFFIXES, *_SOURCE_LEG_SUFFIXES):
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        else:
            return stripped or object_id


def _strip_trailing_leg_token(object_id: str) -> str:
    for suffix in _SOURCE_LEG_SUFFIXES:
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _entity_object_id(entity_id: str) -> str:
    return str(entity_id).split(".")[-1].strip().lower()


def _has_metric_suffix(object_id: str, metric_suffixes: Iterable[str]) -> bool:
    normalized = _strip_trailing_leg_token(object_id.strip().lower())
    return any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in metric_suffixes
    )


def _friendly_name_from_circuit_id(circuit_id: str) -> str:
    return friendly_source_name(
        str(circuit_id).removeprefix("cs_energy_analyzer_demo_")
    )


def _appliance_profile_mode_from_circuit_id(
    circuit_id: str,
) -> tuple[ApplianceProfile, CircuitMode]:
    normalized = f"_{str(circuit_id).strip().lower()}_"
    for tokens, profile, mode in (
        (
            ("_refrigerator_", "_fridge_"),
            ApplianceProfile.REFRIGERATOR,
            CircuitMode.SINGLE_PHASE,
        ),
        (("_freezer_",), ApplianceProfile.FREEZER, CircuitMode.SINGLE_PHASE),
        (
            (
                "_ac_compressor_",
                "_a_c_compressor_",
                "_compressor_",
                "_heat_pump_",
                "_air_conditioner_",
                "_ac_",
            ),
            ApplianceProfile.HVAC_COMPRESSOR,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_air_handler_", "_hvac_air_handler_", "_blower_"),
            ApplianceProfile.HVAC_BLOWER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_aux_heat_", "_electric_heat_", "_electric_aux_heat_", "_heat_strip_"),
            ApplianceProfile.ELECTRIC_HEAT,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_hvac_",),
            ApplianceProfile.HVAC,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_water_heater_", "_waterheater_"),
            ApplianceProfile.WATER_HEATER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_microwave_", "_microwave_oven_"),
            ApplianceProfile.MICROWAVE,
            CircuitMode.SINGLE_PHASE,
        ),
        (("_oven_", "_range_"), ApplianceProfile.OVEN, CircuitMode.DUAL_PHASE),
        (
            ("_washer_", "_clothes_washer_", "_laundry_washer_", "_washing_machine_"),
            ApplianceProfile.WASHER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_dryer_", "_clothes_dryer_", "_electric_dryer_", "_gas_dryer_"),
            ApplianceProfile.DRYER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_pool_pump_", "_poolpump_"),
            ApplianceProfile.POOL_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            (
                "_well_pump_",
                "_wellpump_",
                "_water_pump_",
                "_waterpump_",
                "_booster_pump_",
                "_pressure_pump_",
            ),
            ApplianceProfile.WATER_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_sump_pump_", "_sumppump_"),
            ApplianceProfile.SUMP_PUMP,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            (
                "_ev_",
                "_evse_",
                "_charger_",
                "_ev_charging_",
                "_car_charger_",
                "_car_charging_",
                "_vehicle_charger_",
                "_vehicle_charging_",
                "_level2_charger_",
                "_level_2_charger_",
                "_wall_connector_",
            ),
            ApplianceProfile.EV_CHARGER,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_solar_", "_inverter_", "_pv_"),
            ApplianceProfile.SOLAR_INVERTER,
            CircuitMode.DUAL_PHASE,
        ),
    ):
        if any(token in normalized for token in tokens):
            return profile, mode
    return ApplianceProfile.MIXED, CircuitMode.MIXED
