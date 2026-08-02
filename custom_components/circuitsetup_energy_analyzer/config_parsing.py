from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from .const import (
    CONF_CIRCUITS,
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
from .managers.source_samples import normalized_leg
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
    *,
    mains_sensor_roles: Mapping[str, SensorRole | str | None] | None = None,
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
    configs = _configs_with_merged_mains_entity_refs(
        entry_data,
        options,
        configs,
        mains_sensor_roles=mains_sensor_roles,
    )
    configs.extend(
        _source_entity_configs_from_sources(
            entry_data,
            options,
            default_retention_mode,
            configs,
        )
    )

    if not any(
        config.mode is CircuitMode.MAINS_NILM
        or config.circuit_id == "mains"
        for config in configs
    ):
        mains_config = mains_context_config_from_sources(
            entry_data,
            options,
            mains_sensor_roles=mains_sensor_roles,
        )
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
    mains_entities = set(
        _string_list_from_sources(entry_data, options, CONF_MAINS_SOURCE_ENTITIES)
    )
    if not source_entities and not mains_entities:
        return configs

    eligible_source_entities = [
        entity_id
        for entity_id in source_entities
        if entity_id not in mains_entities
        and not untyped_source_entity_excluded(entity_id)
    ]
    config_index = _config_index_by_source_circuit_id(configs)
    existing_sensor_refs = [
        sensor
        for config in configs
        if config.mode is not CircuitMode.MAINS_NILM and config.circuit_id != "mains"
        for sensor in config.sensors
        if sensor.entity_id not in mains_entities
        and not untyped_source_entity_excluded(sensor.entity_id)
    ]
    existing_source_entity_list = list(
        dict.fromkeys(sensor.entity_id for sensor in existing_sensor_refs)
    )
    existing_source_entities = set(existing_source_entity_list)
    owned_source_entities = {
        sensor.entity_id
        for config in configs
        if config.mode is not CircuitMode.MAINS_NILM and config.circuit_id != "mains"
        for sensor in config.sensors
        if not untyped_source_entity_excluded(sensor.entity_id)
    }
    source_candidates = [*existing_source_entity_list, *eligible_source_entities]
    auto_base_ids = {
        owned_id
        for config in configs
        if config.mode is not CircuitMode.MAINS_NILM and config.circuit_id != "mains"
        if (owned_id := _canonical_source_circuit_id(config.circuit_id))
        if (
            any(
                sensor.entity_id in owned_source_entities
                and _source_circuit_id_from_entity_id(sensor.entity_id) == owned_id
                for sensor in config.sensors
            )
            or (
                not config.sensors
                and any(
                    _source_circuit_id_from_entity_id(entity_id) == owned_id
                    for entity_id in source_candidates
                )
            )
        )
    }
    reusable_variant_ids = {
        owned_id
        for config in configs
        if (owned_id := _canonical_source_circuit_id(config.circuit_id))
        if (
            any(
                _source_circuit_id_from_entity_id(sensor.entity_id) in auto_base_ids
                and source_entity_matches_variant_circuit_id(
                    sensor.entity_id,
                    owned_id,
                )
                for sensor in config.sensors
                if sensor.entity_id in owned_source_entities
            )
            or (
                not config.sensors
                and any(
                    _source_circuit_id_from_entity_id(entity_id) in auto_base_ids
                    and source_entity_matches_variant_circuit_id(entity_id, owned_id)
                    for entity_id in source_candidates
                )
            )
        )
    }
    source_circuit_ids = source_circuit_ids_from_entity_ids(
        [*existing_source_entity_list, *eligible_source_entities],
        sensor_roles={sensor.entity_id: sensor.role for sensor in existing_sensor_refs},
        sensor_legs={sensor.entity_id: sensor.leg for sensor in existing_sensor_refs},
        reserved_circuit_ids=(
            circuit_id
            for circuit_id in config_index
            if circuit_id not in reusable_variant_ids
        ),
    )
    auto_templates = {
        owned_id: config
        for config in configs
        if config.mode is not CircuitMode.MAINS_NILM and config.circuit_id != "mains"
        if (owned_id := _canonical_source_circuit_id(config.circuit_id))
        if owned_id in auto_base_ids
    }

    def ensure_target(desired_id: str, template: CircuitConfig) -> int:
        target_index = config_index.get(desired_id)
        if target_index is not None:
            return target_index
        target_index = len(configs)
        configs.append(
            replace(
                template,
                circuit_id=desired_id,
                name=friendly_source_name(desired_id),
                sensors=(),
            )
        )
        config_index[desired_id] = target_index
        return target_index

    displaced_refs: list[tuple[SensorRef, str, CircuitConfig]] = []
    for index, config in enumerate(tuple(configs)):
        if config.mode is CircuitMode.MAINS_NILM or config.circuit_id == "mains":
            continue
        current_ids = {
            _canonical_source_circuit_id(value)
            for value in (config.circuit_id, config.name)
        }
        owned_id = _canonical_source_circuit_id(config.circuit_id)
        retained_refs = []
        for sensor in config.sensors:
            if sensor.entity_id in mains_entities:
                continue
            if sensor.entity_id not in source_circuit_ids:
                retained_refs.append(sensor)
                continue
            desired_id = source_circuit_ids[sensor.entity_id]
            natural_id = _source_circuit_id_from_entity_id(sensor.entity_id)
            automatic_owner = natural_id == owned_id or (
                natural_id in auto_base_ids
                and source_entity_matches_variant_circuit_id(
                    sensor.entity_id,
                    owned_id,
                )
            )
            if desired_id in current_ids or not automatic_owner:
                retained_refs.append(sensor)
            else:
                displaced_refs.append((sensor, desired_id, config))
        if len(retained_refs) != len(config.sensors):
            configs[index] = replace(config, sensors=tuple(retained_refs))
    for sensor, desired_id, template in displaced_refs:
        target_index = ensure_target(desired_id, template)
        target = configs[target_index]
        if sensor.entity_id not in {ref.entity_id for ref in target.sensors}:
            configs[target_index] = replace(
                target,
                sensors=(*target.sensors, sensor),
            )
    for entity_id in eligible_source_entities:
        if entity_id in existing_source_entities:
            continue
        desired_id = source_circuit_ids[entity_id]
        config_index_value = config_index.get(desired_id)
        if config_index_value is None:
            template = auto_templates.get(_source_circuit_id_from_entity_id(entity_id))
            if template is None:
                continue
            config_index_value = ensure_target(desired_id, template)
        config = configs[config_index_value]
        configs[config_index_value] = replace(
            config,
            sensors=(
                *config.sensors,
                SensorRef(
                    entity_id=entity_id,
                    role=sensor_role_from_entity_id(entity_id),
                    leg=source_entity_leg_hint(entity_id),
                ),
            ),
        )
        existing_source_entities.add(entity_id)
    return [
        config
        for config in configs
        if config.sensors
        or _canonical_source_circuit_id(config.circuit_id)
        not in reusable_variant_ids
    ]


def _config_index_by_source_circuit_id(
    configs: Iterable[CircuitConfig],
) -> dict[str, int]:
    config_list = list(configs)
    config_index: dict[str, int] = {}
    for values in (
        (config.circuit_id for config in config_list),
        (config.name for config in config_list),
    ):
        for index, value in enumerate(values):
            circuit_id = _canonical_source_circuit_id(value)
            if circuit_id:
                config_index.setdefault(circuit_id, index)
    return config_index


def _configs_with_merged_mains_entity_refs(
    entry_data: dict[str, Any],
    options: dict[str, Any],
    configs: list[CircuitConfig],
    *,
    mains_sensor_roles: Mapping[str, SensorRole | str | None] | None = None,
) -> list[CircuitConfig]:
    mains_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_MAINS_SOURCE_ENTITIES,
    )
    if not mains_entities:
        return configs
    mains_index = next(
        (
            index
            for index, config in enumerate(configs)
            if config.mode is CircuitMode.MAINS_NILM
        ),
        None,
    )
    if mains_index is None:
        mains_index = next(
            (
                index
                for index, config in enumerate(configs)
                if config.circuit_id == "mains"
            ),
            None,
        )
    if mains_index is None:
        return configs

    config = configs[mains_index]
    existing_refs = tuple(
        resolved
        for sensor in config.sensors
        if (
            resolved := _mains_sensor_ref(
                sensor.entity_id,
                mains_sensor_roles,
                existing=sensor,
            )
        )
        is not None
    )
    existing_entities = {sensor.entity_id for sensor in existing_refs}
    additions = tuple(
        sensor
        for entity_id in mains_entities
        if (sensor := _mains_sensor_ref(entity_id, mains_sensor_roles)) is not None
        if entity_id not in existing_entities
    )
    sensors = _deduplicated_sensor_refs((*existing_refs, *additions))
    if sensors != config.sensors:
        configs[mains_index] = replace(
            config,
            sensors=sensors,
        )
    return configs


def _mains_sensor_ref(
    entity_id: str,
    sensor_roles: Mapping[str, SensorRole | str | None] | None,
    *,
    existing: SensorRef | None = None,
) -> SensorRef | None:
    if _harmonic_source_entity_excluded(entity_id):
        return None
    if sensor_roles is not None and entity_id in sensor_roles:
        if sensor_roles[entity_id] is None:
            return None
        try:
            role = SensorRole(sensor_roles[entity_id])
        except (TypeError, ValueError):
            return existing
    elif existing is not None:
        return existing
    else:
        if untyped_source_entity_excluded(entity_id):
            return None
        role = sensor_role_from_entity_id(entity_id)
    if existing is not None:
        return replace(existing, role=role)
    return SensorRef(
        entity_id=entity_id,
        role=role,
        leg=source_entity_leg_hint(entity_id),
    )


def _source_entity_configs_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    retention_mode: RetentionMode,
    existing_configs: Iterable[CircuitConfig],
) -> tuple[CircuitConfig, ...]:
    if any(existing_configs):
        return ()

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
    eligible_entities = [
        entity_id
        for entity_id in source_entities
        if entity_id not in mains_entities
        and not _automatic_source_entity_excluded(entity_id)
        and not untyped_source_entity_excluded(entity_id)
    ]
    source_circuit_ids = source_circuit_ids_from_entity_ids(eligible_entities)
    sensors_by_circuit_id: dict[str, list[SensorRef]] = {}
    for entity_id in eligible_entities:
        circuit_id = source_circuit_ids[entity_id]
        if not circuit_id:
            continue
        sensors_by_circuit_id.setdefault(circuit_id, []).append(
            SensorRef(
                entity_id=entity_id,
                role=sensor_role_from_entity_id(entity_id),
                leg=source_entity_leg_hint(entity_id),
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


def _automatic_source_entity_excluded(entity_id: str) -> bool:
    tokens = set(_entity_object_id(entity_id).split("_"))
    return bool(tokens & {"harmonic", "total"})


def untyped_source_entity_excluded(entity_id: str) -> bool:
    object_id = re.sub(r"[^a-z0-9]+", "_", _entity_object_id(entity_id)).strip("_")
    reactive_energy_measurement = (
        re.search(r"(?:^|_)reactive_energy(?:_|$)", object_id) is not None
        or re.search(r"(?:^|_)(?:kvarh|varh)(?:_|$)", object_id) is not None
    )
    terminal_reactive_energy = _has_metric_suffix(
        object_id,
        ("reactive_energy", "kvarh", "varh"),
    )
    return _harmonic_source_entity_excluded(entity_id) or (
        reactive_energy_measurement
        and (
            terminal_reactive_energy
            or explicit_sensor_role_from_entity_id(entity_id) is None
        )
    )


def _harmonic_source_entity_excluded(entity_id: str) -> bool:
    object_id = re.sub(r"[^a-z0-9]+", "_", _entity_object_id(entity_id)).strip("_")
    harmonic_object_id = re.sub(
        r"_\d+$", "", _strip_trailing_source_qualifiers(object_id)
    )
    harmonic_pattern = (
        r"(?:^|_)(?:total_)?harmonic(?:_\d+)?(?:_(?:"
        r"(?:active|reactive|apparent|real)_power"
        r"|peak_(?:current|amps?|a)|power_factor|line_frequency"
        r"|distortion|energy|frequency|current|voltage|power"
        r"|watts?|amps?|volts?|[km]?(?:w|wh|var|va|a|v)|hz))?$"
    )
    return any(
        re.search(harmonic_pattern, candidate) is not None
        for candidate in (
            harmonic_object_id,
            re.sub(r"_[ab]$", "", harmonic_object_id),
        )
    )


def mains_context_config_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    *,
    mains_sensor_roles: Mapping[str, SensorRole | str | None] | None = None,
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
        sensors=_deduplicated_sensor_refs(
            sensor
            for entity_id in mains_entities
            if (sensor := _mains_sensor_ref(entity_id, mains_sensor_roles)) is not None
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
    return _deduplicated_sensor_refs(refs)


def _deduplicated_sensor_refs(refs: Iterable[SensorRef]) -> tuple[SensorRef, ...]:
    ref_list = list(refs)
    circuit_ids = source_circuit_ids_from_entity_ids(
        (ref.entity_id for ref in ref_list),
        sensor_roles={ref.entity_id: ref.role for ref in ref_list},
        sensor_legs={ref.entity_id: ref.leg for ref in ref_list},
    )
    seen: set[str] = set()
    deduplicated: list[SensorRef] = []
    for ref in ref_list:
        if ref.entity_id in seen:
            continue
        seen.add(ref.entity_id)
        if circuit_ids[ref.entity_id] == _source_circuit_id_from_entity_id(
            ref.entity_id
        ):
            deduplicated.append(ref)
    return tuple(deduplicated)


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
        if untyped_source_entity_excluded(raw_sensor):
            return None
        return SensorRef(
            entity_id=raw_sensor,
            role=sensor_role_from_entity_id(raw_sensor),
            leg=source_entity_leg_hint(raw_sensor),
        )
    if not isinstance(raw_sensor, dict):
        return None

    entity_id = raw_sensor.get("entity_id")
    if not entity_id:
        return None
    if _harmonic_source_entity_excluded(str(entity_id)):
        return None
    raw_role = raw_sensor.get("role")
    if raw_role == SensorRole.REAL_POWER.value and untyped_source_entity_excluded(
        str(entity_id)
    ):
        return None
    if raw_role is None:
        if untyped_source_entity_excluded(str(entity_id)):
            return None
        role = sensor_role_from_entity_id(str(entity_id))
    else:
        try:
            role = SensorRole(raw_role)
        except ValueError:
            return None
    return SensorRef(
        entity_id=str(entity_id),
        role=role,
        leg=raw_sensor.get("leg"),
        unit=raw_sensor.get("unit"),
    )


_REAL_POWER_METRIC_SUFFIXES = (
    "active_power",
    "real_power",
    "power",
    "watts",
    "watt",
    "kw",
    "mw",
    "w",
)
_SOURCE_METRIC_SUFFIXES = (
    "_peak_current",
    "_peak_amps",
    "_peak_amp",
    "_peak_a",
    "_reactive_power",
    "_apparent_power",
    "_kvarh",
    "_kvar",
    "_mvar",
    "_kva",
    "_mva",
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
    "_ka",
    "_ma",
    "_kv",
    "_mv",
    "_power",
    "_kw",
    "_mw",
    "_kwh",
    "_mwh",
    "_wh",
    "_var",
    "_varh",
    "_va",
    "_pf",
    "_hz",
)
_SOURCE_VALUE_QUALIFIER_SUFFIXES = (
    "_rms",
    "_average",
    "_avg",
    "_mean",
    "_minimum",
    "_maximum",
    "_min",
    "_max",
    "_today",
    "_import",
    "_export",
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


def sensor_role_from_entity_id(entity_id: str) -> SensorRole:
    return explicit_sensor_role_from_entity_id(entity_id) or SensorRole.REAL_POWER


def explicit_sensor_role_from_entity_id(entity_id: str) -> SensorRole | None:
    """Return a role only when the entity ID exposes a terminal metric."""
    object_id = _strip_terminal_phase_letter(_entity_object_id(entity_id))
    if _has_metric_suffix(
        object_id,
        ("peak_current", "peak_amps", "peak_amp", "peak_a"),
    ):
        return SensorRole.PEAK_CURRENT
    if _has_metric_suffix(object_id, ("power_factor", "pf")):
        return SensorRole.POWER_FACTOR
    if _has_metric_suffix(
        object_id,
        ("reactive_power", "reactive", "kvar", "mvar", "var"),
    ):
        return SensorRole.REACTIVE_POWER
    if _has_metric_suffix(
        object_id,
        ("apparent_power", "apparent", "kva", "mva", "va"),
    ):
        return SensorRole.APPARENT_POWER
    if _has_metric_suffix(object_id, ("frequency", "line_frequency", "hz")):
        return SensorRole.FREQUENCY
    if _has_metric_suffix(object_id, ("current", "amps", "amp", "ka", "ma", "a")):
        return SensorRole.CURRENT
    if _has_metric_suffix(
        object_id,
        ("voltage", "volts", "volt", "kv", "mv", "v"),
    ):
        return SensorRole.VOLTAGE
    if _has_metric_suffix(
        object_id,
        ("energy", "kwh", "mwh", "wh"),
    ):
        return SensorRole.ENERGY
    if _has_metric_suffix(
        object_id,
        _REAL_POWER_METRIC_SUFFIXES,
    ):
        return SensorRole.REAL_POWER
    return None


def source_entity_leg_hint(entity_id: str) -> str | None:
    """Return explicit leg metadata, including terminal metric A/B aliases."""
    hint = _entity_id_leg_hint(entity_id)
    if hint is not None:
        return hint
    object_id = _entity_object_id(entity_id)
    if _strip_terminal_phase_letter(object_id) == object_id:
        return None
    return "a" if object_id.endswith("_a") else "b"


def _source_circuit_id_from_entity_id(entity_id: str) -> str:
    object_id = _entity_object_id(entity_id)
    return _canonical_source_circuit_id(
        strip_trailing_source_detail_tokens(object_id)
    )


def source_entity_matches_variant_circuit_id(
    entity_id: str,
    circuit_id: str,
) -> bool:
    """Return whether a saved circuit ID is an automatic source variant."""
    detail = _source_value_qualifier_from_entity_id(
        entity_id
    ) or _source_metric_suffix_from_entity_id(entity_id)
    if not detail:
        return False
    prefix = f"{_source_circuit_id_from_entity_id(entity_id)}_{detail}"
    canonical_id = _canonical_source_circuit_id(circuit_id)
    if canonical_id == prefix:
        return True
    ordinal = canonical_id.removeprefix(f"{prefix}_")
    return ordinal != canonical_id and ordinal.isdigit() and int(ordinal) >= 2


def source_circuit_ids_from_entity_ids(
    entity_ids: Iterable[str],
    *,
    sensor_roles: Mapping[str, SensorRole | str] | None = None,
    sensor_legs: Mapping[str, str | None] | None = None,
    reserved_circuit_ids: Iterable[str] = (),
) -> dict[str, str]:
    """Return circuit IDs without collapsing duplicate role measurements."""
    entity_id_list = list(dict.fromkeys(entity_ids))
    circuit_ids = {
        entity_id: _source_circuit_id_from_entity_id(entity_id)
        for entity_id in entity_id_list
    }
    buckets_by_base: dict[
        str,
        dict[tuple[SensorRole, str | None], list[str]],
    ] = {}
    for entity_id in entity_id_list:
        try:
            role = SensorRole((sensor_roles or {})[entity_id])
        except (KeyError, TypeError, ValueError):
            role = sensor_role_from_entity_id(entity_id)
        buckets_by_base.setdefault(circuit_ids[entity_id], {}).setdefault(
            (
                role,
                normalized_leg((sensor_legs or {}).get(entity_id))
                or source_entity_leg_hint(entity_id),
            ),
            [],
        ).append(entity_id)

    metric_priority = {
        suffix.removeprefix("_"): index
        for index, suffix in enumerate(_SOURCE_METRIC_SUFFIXES)
    }
    qualifier_priority = {
        suffix.removeprefix("_"): index
        for index, suffix in enumerate(_SOURCE_VALUE_QUALIFIER_SUFFIXES)
    }
    qualifiers = {
        entity_id: _source_value_qualifier_from_entity_id(entity_id)
        for entity_id in entity_id_list
    }
    metrics = {
        entity_id: _source_metric_suffix_from_entity_id(entity_id)
        for entity_id in entity_id_list
    }
    variant_by_entity: dict[str, tuple[str, str, int]] = {}
    for base_circuit_id, buckets in sorted(buckets_by_base.items()):
        base_qualifier = min(
            {
                qualifiers[entity_id]
                for entities in buckets.values()
                for entity_id in entities
            },
            key=lambda qualifier: (
                bool(qualifier),
                qualifier_priority.get(qualifier, len(qualifier_priority)),
                qualifier,
            ),
        )
        for _, bucket_entities in sorted(
            buckets.items(),
            key=lambda item: (item[0][0].value, item[0][1] or ""),
        ):
            entities_by_qualifier: dict[str, list[str]] = {}
            for entity_id in bucket_entities:
                entities_by_qualifier.setdefault(qualifiers[entity_id], []).append(
                    entity_id
                )
            for qualifier, qualified_entities in sorted(
                entities_by_qualifier.items(),
                key=lambda item: (
                    qualifier_priority.get(item[0], len(qualifier_priority)),
                    item[0],
                ),
            ):
                ordered_entities = sorted(
                    qualified_entities,
                    key=lambda entity_id: (
                        metric_priority.get(metrics[entity_id], len(metric_priority)),
                        entity_id,
                    ),
                )
                variants = (
                    ordered_entities[1:]
                    if qualifier == base_qualifier
                    else ordered_entities
                )
                if qualifier:
                    for ordinal, entity_id in enumerate(variants):
                        variant_by_entity[entity_id] = (
                            base_circuit_id,
                            qualifier,
                            ordinal,
                        )
                    continue
                occurrences: dict[str, int] = {}
                for entity_id in variants:
                    detail = metrics[entity_id] or "source"
                    ordinal = occurrences.get(detail, 0)
                    occurrences[detail] = ordinal + 1
                    variant_by_entity[entity_id] = (
                        base_circuit_id,
                        detail,
                        ordinal,
                    )

    reserved_ids = set(circuit_ids.values()) | {
        _canonical_source_circuit_id(circuit_id)
        for circuit_id in reserved_circuit_ids
    }
    variant_ids: dict[tuple[str, str, int], str] = {}
    for variant_key in sorted(set(variant_by_entity.values())):
        base_circuit_id, detail, _ = variant_key
        candidate_base = f"{base_circuit_id}_{detail}"
        candidate = candidate_base
        suffix = 2
        while candidate in reserved_ids:
            candidate = f"{candidate_base}_{suffix}"
            suffix += 1
        variant_ids[variant_key] = candidate
        reserved_ids.add(candidate)
    for entity_id, variant_key in variant_by_entity.items():
        circuit_ids[entity_id] = variant_ids[variant_key]
    return circuit_ids


def _canonical_source_circuit_id(value: Any) -> str:
    circuit_id = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    for preserved_prefix in _PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(preserved_prefix):
            return circuit_id
    for prefix in _ANALYZER_SOURCE_ENTITY_PREFIXES:
        if circuit_id.startswith(prefix):
            return circuit_id.removeprefix(prefix) or circuit_id
    return circuit_id


def strip_trailing_source_detail_tokens(object_id: str) -> str:
    stripped = _strip_terminal_phase_letter(
        _strip_trailing_source_qualifiers(object_id)
    )
    direction = next(
        (
            token
            for token in object_id.removeprefix(stripped).split("_")
            if token in {"import", "export"}
        ),
        "",
    )
    for suffix in _SOURCE_METRIC_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    while (without_leg := _strip_trailing_leg_token(stripped)) != stripped:
        stripped = without_leg
    if direction and explicit_sensor_role_from_entity_id(object_id) in {
        SensorRole.ENERGY,
        SensorRole.REAL_POWER,
    }:
        stripped = f"{stripped}_{direction}"
    return stripped or object_id


def _strip_trailing_leg_token(object_id: str) -> str:
    for suffix in _SOURCE_LEG_SUFFIXES:
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _strip_trailing_source_qualifiers(object_id: str) -> str:
    stripped = object_id
    while True:
        without_leg = _strip_trailing_leg_token(stripped)
        if without_leg != stripped:
            stripped = without_leg
            continue
        without_value_qualifier = _strip_trailing_value_qualifier(stripped)
        normalized_value = _strip_terminal_phase_letter(without_value_qualifier)
        if without_value_qualifier != stripped and _source_metric_suffix_exposed(
            normalized_value
        ):
            stripped = normalized_value
            continue
        without_index = re.sub(r"_\d+$", "", stripped)
        normalized_index = _strip_terminal_phase_letter(without_index)
        if without_index != stripped and _source_metric_suffix_exposed(
            normalized_index
        ):
            stripped = normalized_index
            continue
        return stripped


def _strip_trailing_value_qualifier(object_id: str) -> str:
    for suffix in _SOURCE_VALUE_QUALIFIER_SUFFIXES:
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _source_value_qualifier_from_entity_id(entity_id: str) -> str:
    object_id = _entity_object_id(entity_id)
    stripped = _strip_trailing_source_qualifiers(object_id)
    removed_tokens = object_id.removeprefix(stripped).split("_")
    return next(
        (
            suffix.removeprefix("_")
            for suffix in _SOURCE_VALUE_QUALIFIER_SUFFIXES
            if suffix.removeprefix("_") in removed_tokens
        ),
        "",
    )


def _source_metric_suffix_from_entity_id(entity_id: str) -> str:
    object_id = _strip_terminal_phase_letter(_entity_object_id(entity_id))
    normalized = _strip_trailing_source_qualifiers(object_id)
    return next(
        (
            suffix.removeprefix("_")
            for suffix in _SOURCE_METRIC_SUFFIXES
            if normalized.endswith(suffix)
        ),
        "",
    )


def _source_metric_suffix_exposed(object_id: str) -> bool:
    probe = object_id
    while True:
        normalized = _strip_trailing_leg_token(probe)
        if normalized == probe:
            normalized = _strip_trailing_value_qualifier(probe)
        if normalized == probe:
            return any(
                probe == suffix.removeprefix("_") or probe.endswith(suffix)
                for suffix in _SOURCE_METRIC_SUFFIXES
            )
        probe = normalized


def _strip_terminal_phase_letter(object_id: str) -> str:
    without_phase = re.sub(r"_[ab]$", "", object_id)
    return (
        without_phase
        if _source_metric_suffix_exposed(without_phase)
        else object_id
    )


def _entity_object_id(entity_id: str) -> str:
    return str(entity_id).split(".")[-1].strip().lower()


def _has_metric_suffix(object_id: str, metric_suffixes: Iterable[str]) -> bool:
    normalized = _strip_trailing_source_qualifiers(object_id.strip().lower())
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
                "_mini_split_",
                "_minisplit_",
                "_ductless_heat_pump_",
                "_ductless_ac_",
            ),
            ApplianceProfile.MINI_SPLIT,
            CircuitMode.DUAL_PHASE,
        ),
        (
            ("_heat_pump_",),
            ApplianceProfile.HEAT_PUMP,
            CircuitMode.DUAL_PHASE,
        ),
        (
            (
                "_ac_compressor_",
                "_a_c_compressor_",
                "_compressor_",
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
            ("_dishwasher_", "_dish_washer_"),
            ApplianceProfile.DISHWASHER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_3d_printer_", "_3dprinter_", "_3_d_printer_"),
            ApplianceProfile.THREE_D_PRINTER,
            CircuitMode.SINGLE_PHASE,
        ),
        (
            ("_washer_", "_clothes_washer_", "_laundry_washer_", "_washing_machine_"),
            ApplianceProfile.WASHER,
            CircuitMode.SINGLE_PHASE,
        ),
        (("_gas_dryer_",), ApplianceProfile.DRYER, CircuitMode.SINGLE_PHASE),
        (
            ("_dryer_", "_clothes_dryer_", "_electric_dryer_"),
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
