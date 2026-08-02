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

    if not any(
        config.mode is CircuitMode.MAINS_NILM
        or config.circuit_id == "mains"
        for config in configs
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
    existing_sensor_refs = [sensor for config in configs for sensor in config.sensors]
    existing_source_entity_list = list(
        dict.fromkeys(sensor.entity_id for sensor in existing_sensor_refs)
    )
    existing_source_entities = set(existing_source_entity_list)
    source_circuit_ids = source_circuit_ids_from_entity_ids(
        [*existing_source_entity_list, *source_entities],
        sensor_roles={sensor.entity_id: sensor.role for sensor in existing_sensor_refs},
    )
    for entity_id in source_entities:
        if (
            entity_id in mains_entities
            or entity_id in existing_source_entities
            or untyped_source_entity_excluded(entity_id)
        ):
            continue
        config_index_value = config_index.get(source_circuit_ids[entity_id])
        if config_index_value is None:
            continue
        config = configs[config_index_value]
        configs[config_index_value] = replace(
            config,
            sensors=(
                *config.sensors,
                SensorRef(
                    entity_id=entity_id,
                    role=sensor_role_from_entity_id(entity_id),
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


def _automatic_source_entity_excluded(entity_id: str) -> bool:
    tokens = set(_entity_object_id(entity_id).split("_"))
    return bool(tokens & {"harmonic", "total"})


def untyped_source_entity_excluded(entity_id: str) -> bool:
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
    harmonic_measurement = any(
        re.search(harmonic_pattern, candidate) is not None
        for candidate in (
            harmonic_object_id,
            re.sub(r"_[ab]$", "", harmonic_object_id),
        )
    )
    reactive_energy_measurement = (
        re.search(r"(?:^|_)reactive_energy(?:_|$)", object_id) is not None
        or re.search(r"(?:^|_)(?:kvarh|varh)(?:_|$)", object_id) is not None
    )
    terminal_reactive_energy = _has_metric_suffix(
        object_id,
        ("reactive_energy", "kvarh", "varh"),
    )
    return harmonic_measurement or (
        reactive_energy_measurement
        and (
            terminal_reactive_energy
            or explicit_sensor_role_from_entity_id(entity_id) is None
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
                role=sensor_role_from_entity_id(entity_id),
                leg=_entity_id_leg_hint(entity_id),
            )
            for entity_id in mains_entities
            if not untyped_source_entity_excluded(entity_id)
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
        if untyped_source_entity_excluded(raw_sensor):
            return None
        return SensorRef(
            entity_id=raw_sensor,
            role=sensor_role_from_entity_id(raw_sensor),
            leg=_entity_id_leg_hint(raw_sensor),
        )
    if not isinstance(raw_sensor, dict):
        return None

    entity_id = raw_sensor.get("entity_id")
    if not entity_id:
        return None
    raw_role = raw_sensor.get("role")
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


def _source_circuit_id_from_entity_id(entity_id: str) -> str:
    object_id = _entity_object_id(entity_id)
    return _canonical_source_circuit_id(
        strip_trailing_source_detail_tokens(object_id)
    )


def source_circuit_ids_from_entity_ids(
    entity_ids: Iterable[str],
    *,
    sensor_roles: Mapping[str, SensorRole | str] | None = None,
) -> dict[str, str]:
    """Return circuit IDs without collapsing duplicate role measurements."""
    entity_id_list = list(dict.fromkeys(entity_ids))
    circuit_ids = {
        entity_id: _source_circuit_id_from_entity_id(entity_id)
        for entity_id in entity_id_list
    }
    entities_by_collision: dict[tuple[str, SensorRole, str | None], list[str]] = {}
    for entity_id in entity_id_list:
        try:
            role = SensorRole((sensor_roles or {})[entity_id])
        except (KeyError, ValueError):
            role = sensor_role_from_entity_id(entity_id)
        entities_by_collision.setdefault(
            (
                circuit_ids[entity_id],
                role,
                _entity_id_leg_hint(entity_id),
            ),
            [],
        ).append(entity_id)

    metric_priority = {
        suffix.removeprefix("_"): index
        for index, suffix in enumerate(_SOURCE_METRIC_SUFFIXES)
    }
    reserved_circuit_ids = set(circuit_ids.values())
    for (base_circuit_id, _, _), collided_entities in entities_by_collision.items():
        if len(collided_entities) < 2:
            continue
        qualifiers = {
            entity_id: _source_value_qualifier_from_entity_id(entity_id)
            for entity_id in collided_entities
        }
        metrics = {
            entity_id: _source_metric_suffix_from_entity_id(entity_id)
            for entity_id in collided_entities
        }
        primary_entity = min(
            collided_entities,
            key=lambda entity_id: (
                bool(qualifiers[entity_id]),
                metric_priority.get(metrics[entity_id], len(metric_priority)),
                entity_id,
            ),
        )
        for entity_id in collided_entities:
            if entity_id == primary_entity:
                continue
            detail = qualifiers[entity_id] or metrics[entity_id]
            candidate_base = f"{base_circuit_id}_{detail or 'source'}"
            candidate = candidate_base
            suffix = 2
            while candidate in reserved_circuit_ids:
                candidate = f"{candidate_base}_{suffix}"
                suffix += 1
            circuit_ids[entity_id] = candidate
            reserved_circuit_ids.add(candidate)
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
    stripped = _strip_trailing_source_qualifiers(object_id)
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
