from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

try:
    import voluptuous as vol
except ModuleNotFoundError:

    class _Schema:
        def __init__(self, schema: Mapping[Any, Any]) -> None:
            self.schema = schema

        def __call__(self, value: Any) -> Any:
            return value

    class _Marker:
        def __init__(self, key: str, default: Any = None) -> None:
            self.key = key
            self.default = default

        def __hash__(self) -> int:
            return hash((self.key, self.default))

        def __eq__(self, other: object) -> bool:
            return (
                isinstance(other, _Marker)
                and self.key == other.key
                and self.default == other.default
            )

    class _VoluptuousFallback:
        Schema = _Schema

        @staticmethod
        def Required(key: str, default: Any = None) -> _Marker:
            return _Marker(key, default)

        @staticmethod
        def Optional(key: str, default: Any = None) -> _Marker:
            return _Marker(key, default)

    vol = _VoluptuousFallback()

try:
    from homeassistant import config_entries
    from homeassistant.core import callback
    from homeassistant.helpers.selector import selector as ha_selector
except ModuleNotFoundError:

    def callback(func: Any) -> Any:
        return func

    class _ConfigFlow:
        def __init_subclass__(cls, **kwargs: Any) -> None:
            super().__init_subclass__()

        def async_create_entry(
            self,
            *,
            title: str,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

        def async_show_menu(
            self,
            *,
            step_id: str,
            menu_options: list[str],
            description_placeholders: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "menu",
                "step_id": step_id,
                "menu_options": menu_options,
                "description_placeholders": description_placeholders or {},
            }

    class _OptionsFlow(_ConfigFlow):
        pass

    config_entries = SimpleNamespace(
        ConfigEntry=Any,
        ConfigFlow=_ConfigFlow,
        ConfigFlowResult=dict[str, Any],
        OptionsFlow=_OptionsFlow,
        OptionsFlowWithReload=_OptionsFlow,
    )
    ha_selector = None

from .const import (
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .discovery import (
    ENERGY_SOURCE_DEVICE_CLASSES,
    async_discover_energy_source_entities,
    async_discover_energy_source_entities_for_devices,
    async_discover_sensors,
    infer_sensor_role,
)
from .mapping import DualPhaseSuggestion, suggest_dual_phase_pairs
from .models import ApplianceProfile, CircuitMode, RetentionMode, SensorRole

TITLE = "CircuitSetup Energy Analyzer"
ERROR_NO_SOURCE_ENTITIES = "no_source_entities"
ERROR_INVALID_SOURCE_ENTITIES = "invalid_source_entities"
ERROR_INVALID_CIRCUIT_ASSIGNMENTS = "invalid_circuit_assignments"
_VALID_RETENTION_MODES = {mode.value for mode in RetentionMode}
_SENSITIVITY_OPTIONS = ("standard", "high", "low")
FIELD_INCLUDE_CIRCUIT = "include_circuit"
FIELD_CIRCUIT_NAME = "circuit_name"
FIELD_APPLIANCE_PROFILE = "appliance_profile"
FIELD_CIRCUIT_MODE = "circuit_mode"
_ASSIGNMENT_PROFILE_OPTIONS = (
    "exclude",
    ApplianceProfile.REFRIGERATOR.value,
    ApplianceProfile.FREEZER.value,
    ApplianceProfile.HVAC.value,
    ApplianceProfile.HVAC_COMPRESSOR.value,
    ApplianceProfile.HVAC_BLOWER.value,
    ApplianceProfile.ELECTRIC_HEAT.value,
    ApplianceProfile.WATER_HEATER.value,
    ApplianceProfile.OVEN.value,
    ApplianceProfile.DRYER.value,
    ApplianceProfile.POOL_PUMP.value,
    ApplianceProfile.WATER_PUMP.value,
    ApplianceProfile.SUMP_PUMP.value,
    ApplianceProfile.EV_CHARGER.value,
    ApplianceProfile.SOLAR_INVERTER.value,
    ApplianceProfile.MOTOR_LOAD.value,
    ApplianceProfile.RESISTIVE_LOAD.value,
    ApplianceProfile.MIXED.value,
)
_GUIDED_ASSIGNMENT_PROFILE_OPTIONS = tuple(
    option for option in _ASSIGNMENT_PROFILE_OPTIONS if option != "exclude"
)
_ASSIGNMENT_MODE_OPTIONS = {
    CircuitMode.SINGLE_PHASE.value,
    CircuitMode.DUAL_PHASE.value,
    CircuitMode.MIXED.value,
    CircuitMode.MAINS_NILM.value,
}
_DEMO_SOURCE_METRICS = (
    "energy",
    "active_power",
    "current",
    "power_factor",
    "reactive_power",
)
_DEMO_SOURCE_ENTITY_IDS = tuple(
    f"sensor.cs_energy_analyzer_demo_{leg}_{metric}"
    for leg in ("mains_l1", "mains_l2")
    for metric in (*_DEMO_SOURCE_METRICS, "voltage")
) + tuple(
    f"sensor.cs_energy_analyzer_demo_{circuit}_{metric}"
    for circuit in ("refrigerator", "pool_pump")
    for metric in _DEMO_SOURCE_METRICS
) + tuple(
    f"sensor.cs_energy_analyzer_demo_{circuit}_{leg}_{metric}"
    for circuit in ("hvac", "water_heater", "car_charger")
    for leg in ("l1", "l2")
    for metric in _DEMO_SOURCE_METRICS
)
_OPTIONS_FLOW_BASE = getattr(
    config_entries,
    "OptionsFlowWithReload",
    config_entries.OptionsFlow,
)


class SetupValidationError(ValueError):
    """Setup validation error with a Home Assistant translation key."""

    def __init__(self, error_key: str) -> None:
        super().__init__(error_key)
        self.error_key = error_key


def format_mapping_suggestions(suggestions: Iterable[DualPhaseSuggestion]) -> str:
    """Format auto-suggested dual-phase mappings for user confirmation."""
    suggestion_list = list(suggestions)
    if not suggestion_list:
        return (
            "No dual-phase mapping suggestions were found yet. Continue with "
            "source sensors; the analyzer can still learn from selected inputs."
        )

    lines = [
        "Suggested dual-phase channel pairs are listed below. Review each pair, "
        "then confirm or manually override the mapping before saving. You can "
        "accept, edit, mark as mixed, or exclude each suggested circuit. "
        "Confidence may use naming, phase pairing, correlated changes, "
        "required metric availability, and optional metric availability."
    ]
    for suggestion in suggestion_list:
        reasons = ", ".join(suggestion.reasons) if suggestion.reasons else "no reasons"
        lines.append(
            f"- {suggestion.left.name} ({suggestion.left.entity_id}) + "
            f"{suggestion.right.name} ({suggestion.right.entity_id}): "
            f"{suggestion.confidence:.0%} confidence; reasons: {reasons}."
        )
    return "\n".join(lines)


def validate_setup_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize setup data without requiring Home Assistant."""
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    legacy_source_entities = _strict_string_list(
        user_input.get(CONF_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    source_entities = list(
        dict.fromkeys([*extra_source_entities, *legacy_source_entities])
    )
    if not source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    retention_mode = _validate_retention_mode(user_input)

    return {
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: source_entities,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _strict_string_list(
            user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
            invalid_error_key="invalid_mains_source_entities",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: retention_mode,
    }


def validate_options_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize options flow data without requiring Home Assistant."""
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    validated = {
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _strict_string_list(
            user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
            invalid_error_key="invalid_mains_source_entities",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: _validate_retention_mode(user_input),
    }
    merged_source_entities = list(extra_source_entities)
    if CONF_SOURCE_ENTITIES in user_input:
        source_entities = _strict_string_list(
            user_input.get(CONF_SOURCE_ENTITIES),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
        merged_source_entities.extend(source_entities)
    merged_source_entities = list(dict.fromkeys(merged_source_entities))
    if not merged_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)
    validated[CONF_SOURCE_ENTITIES] = merged_source_entities
    return validated


def _strict_string_list(value: Any, *, invalid_error_key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: list[str] = []
        for raw_item in re.split(r"[\n,]+", value):
            item = raw_item.strip()
            if item:
                items.append(item)
        return items
    if isinstance(value, Mapping) or not isinstance(value, (list, tuple, set)):
        raise SetupValidationError(invalid_error_key)

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SetupValidationError(invalid_error_key)
        if item:
            items.append(item)
    return items


def _validate_retention_mode(user_input: Mapping[str, Any]) -> str:
    retention_mode = str(user_input.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE))
    if retention_mode not in _VALID_RETENTION_MODES:
        raise SetupValidationError("invalid_retention_mode")
    return retention_mode


def _selector(config: dict[str, Any], fallback: Any) -> Any:
    if ha_selector is None:
        return fallback
    return ha_selector(config)


def _energy_entity_selector_config(
    include_entities: Iterable[str] | None = None,
) -> dict[str, Any]:
    entity_ids = list(dict.fromkeys(include_entities or ()))
    config: dict[str, Any] = {
        "entity": {
            "multiple": True,
            "filter": [
                {
                    "domain": "sensor",
                    "device_class": sorted(ENERGY_SOURCE_DEVICE_CLASSES),
                }
            ],
        }
    }
    if entity_ids:
        config["entity"]["include_entities"] = entity_ids

    return config


def _energy_entity_list_selector(
    include_entities: Iterable[str] | None = None,
) -> Any:
    return _selector(_energy_entity_selector_config(include_entities), str)


def _source_device_selector() -> Any:
    return _selector(_source_device_selector_config(), str)


def _source_device_selector_config() -> dict[str, Any]:
    return {
        "device": {
            "multiple": True,
            "filter": [{"integration": "esphome"}],
            "entity": [
                {
                    "domain": "sensor",
                    "device_class": sorted(ENERGY_SOURCE_DEVICE_CLASSES),
                }
            ],
        }
    }


def _assignment_text_selector() -> Any:
    return _selector({"text": {"multiline": True, "multiple": False}}, str)


def _select_selector(options: Iterable[str]) -> Any:
    return _selector({"select": {"options": list(options)}}, vol.In(tuple(options)))


def _selectable_source_entity_ids(
    source_entity_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys([*list(source_entity_ids or ()), *_DEMO_SOURCE_ENTITY_IDS])
    )


def _setup_schema(source_entity_ids: Iterable[str] | None = None) -> Any:
    return vol.Schema(
        {
            vol.Optional(CONF_SOURCE_DEVICES, default=[]): _source_device_selector(),
            vol.Optional(
                CONF_EXTRA_SOURCE_ENTITIES,
                default=[],
            ): _energy_entity_list_selector(
                _selectable_source_entity_ids(source_entity_ids)
            ),
            vol.Optional(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                default=DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            ): bool,
            vol.Optional(
                CONF_MAINS_SOURCE_ENTITIES,
                default=[],
            ): _energy_entity_list_selector(
                _selectable_source_entity_ids(source_entity_ids)
            ),
            vol.Optional(
                CONF_SENSITIVITY,
                default=DEFAULT_SENSITIVITY,
            ): _select_selector(_SENSITIVITY_OPTIONS),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=DEFAULT_RETENTION_MODE,
            ): _select_selector(sorted(_VALID_RETENTION_MODES)),
        }
    )


DATA_SCHEMA = _setup_schema()


def _assignment_schema(group: Mapping[str, Any]) -> Any:
    return vol.Schema(
        {
            vol.Required(
                FIELD_INCLUDE_CIRCUIT,
                default=True,
            ): bool,
            vol.Required(
                FIELD_CIRCUIT_NAME,
                default=str(group.get("name") or ""),
            ): str,
            vol.Required(
                FIELD_APPLIANCE_PROFILE,
                default=str(group.get("appliance_profile") or ApplianceProfile.MIXED),
            ): _select_selector(_GUIDED_ASSIGNMENT_PROFILE_OPTIONS),
            vol.Required(
                FIELD_CIRCUIT_MODE,
                default=str(group.get("mode") or CircuitMode.MIXED),
            ): _select_selector(sorted(_ASSIGNMENT_MODE_OPTIONS)),
        }
    )


def assignment_groups_from_sources(
    source_entities: Iterable[str],
    *,
    mains_source_entities: Iterable[str] = (),
    existing_circuits: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build guided assignment groups with automatic or saved classification."""
    source_entity_list = list(dict.fromkeys(source_entities))
    mains_entities = set(mains_source_entities)
    non_mains_entities = [
        entity_id for entity_id in source_entity_list if entity_id not in mains_entities
    ]
    grouped_entities = non_mains_entities or source_entity_list
    existing_circuit_list = [
        circuit for circuit in existing_circuits if isinstance(circuit, Mapping)
    ]

    groups: dict[str, list[str]] = {}
    for entity_id in grouped_entities:
        circuit_id = _assignment_circuit_id_from_entity_id(entity_id)
        groups.setdefault(circuit_id, []).append(entity_id)

    assignment_groups: list[dict[str, Any]] = []
    for circuit_id, entity_ids in groups.items():
        profile, mode = _suggest_assignment_profile_mode(circuit_id, entity_ids)
        group = {
            "group_id": circuit_id,
            "entity_ids": tuple(entity_ids),
            "name": _friendly_name_from_id(circuit_id),
            "appliance_profile": profile,
            "mode": mode,
        }
        saved_circuit = _saved_circuit_for_group(group, existing_circuit_list)
        if saved_circuit is not None:
            group.update(
                {
                    "name": str(saved_circuit.get("name") or group["name"]),
                    "appliance_profile": _normalize_assignment_profile(
                        str(
                            saved_circuit.get(
                                "appliance_profile",
                                group["appliance_profile"],
                            )
                        )
                    ),
                    "mode": _normalize_assignment_mode(
                        str(saved_circuit.get("mode", group["mode"]))
                    ),
                }
            )
        assignment_groups.append(group)
    return assignment_groups


def _saved_circuit_for_group(
    group: Mapping[str, Any],
    existing_circuits: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    group_entities = set(group.get("entity_ids", ()))
    group_id = str(group.get("group_id") or "")
    for circuit in existing_circuits:
        sensor_entities = {
            str(sensor.get("entity_id"))
            for sensor in circuit.get("sensors", ())
            if isinstance(sensor, Mapping) and sensor.get("entity_id")
        }
        if group_entities and group_entities <= sensor_entities:
            return circuit
        if str(circuit.get("circuit_id") or circuit.get("id") or "") == group_id:
            return circuit
    return None


def _assignment_review_form(
    flow: Any,
    *,
    errors: dict[str, str] | None = None,
) -> config_entries.ConfigFlowResult:
    groups = list(getattr(flow, "_assignment_groups", []) or [])
    index = int(getattr(flow, "_assignment_index", 0) or 0)
    if not groups or index >= len(groups):
        return flow.async_show_form(
            step_id="assign",
            data_schema=_assignment_schema(
                {
                    "name": "Circuit",
                    "appliance_profile": ApplianceProfile.MIXED.value,
                    "mode": CircuitMode.MIXED.value,
                    "entity_ids": (),
                }
            ),
            errors=errors or {"base": ERROR_NO_SOURCE_ENTITIES},
            description_placeholders=_assignment_description_placeholders(
                {
                    "name": "Circuit",
                    "appliance_profile": ApplianceProfile.MIXED.value,
                    "mode": CircuitMode.MIXED.value,
                    "entity_ids": (),
                },
                index=0,
                total=0,
            ),
        )
    group = groups[index]
    return flow.async_show_form(
        step_id="assign",
        data_schema=_assignment_schema(group),
        errors=errors or {},
        description_placeholders=_assignment_description_placeholders(
            group,
            index=index,
            total=len(groups),
        ),
    )


def _assignment_description_placeholders(
    group: Mapping[str, Any],
    *,
    index: int,
    total: int,
) -> dict[str, str]:
    return {
        "assignment_progress": f"{index + 1} of {total}" if total else "0 of 0",
        "circuit_name": str(group.get("name") or ""),
        "appliance_profile": str(group.get("appliance_profile") or ""),
        "circuit_mode": str(group.get("mode") or ""),
        "current_sensors": "\n".join(
            str(entity_id) for entity_id in group.get("entity_ids", ())
        ),
    }


def _start_assignment_review(
    flow: Any,
    pending_config: Mapping[str, Any],
    *,
    existing_circuits: Iterable[Mapping[str, Any]] = (),
) -> config_entries.ConfigFlowResult:
    groups = assignment_groups_from_sources(
        pending_config.get(CONF_SOURCE_ENTITIES, []),
        mains_source_entities=pending_config.get(CONF_MAINS_SOURCE_ENTITIES, []),
        existing_circuits=existing_circuits,
    )
    flow._pending_config = dict(pending_config)
    flow._assignment_groups = groups
    flow._assignment_index = 0
    flow._reviewed_circuits = []
    return _assignment_review_form(flow)


def _handle_assignment_review_submission(
    flow: Any,
    user_input: Mapping[str, Any],
) -> config_entries.ConfigFlowResult | dict[str, Any]:
    groups = list(getattr(flow, "_assignment_groups", []) or [])
    index = int(getattr(flow, "_assignment_index", 0) or 0)
    if not groups or index >= len(groups):
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    reviewed_circuits = list(getattr(flow, "_reviewed_circuits", []) or [])
    try:
        circuit = _circuit_from_assignment_group(groups[index], user_input)
    except SetupValidationError:
        raise
    if circuit is not None:
        reviewed_circuits.append(circuit)
    flow._reviewed_circuits = reviewed_circuits
    flow._assignment_index = index + 1

    if flow._assignment_index < len(groups):
        return _assignment_review_form(flow)
    return _final_config_from_reviewed_circuits(
        getattr(flow, "_pending_config", {}) or {},
        reviewed_circuits,
    )


def _circuit_from_assignment_group(
    group: Mapping[str, Any],
    user_input: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not bool(user_input.get(FIELD_INCLUDE_CIRCUIT, True)):
        return None

    name = str(user_input.get(FIELD_CIRCUIT_NAME) or group.get("name") or "").strip()
    if not name:
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
    profile = _normalize_assignment_profile(
        str(
            user_input.get(FIELD_APPLIANCE_PROFILE)
            or group.get("appliance_profile")
            or ApplianceProfile.MIXED.value
        )
    )
    mode = _normalize_assignment_mode(
        str(
            user_input.get(FIELD_CIRCUIT_MODE)
            or group.get("mode")
            or CircuitMode.MIXED.value
        )
    )
    if profile not in _GUIDED_ASSIGNMENT_PROFILE_OPTIONS:
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)

    entity_ids = [str(entity_id) for entity_id in group.get("entity_ids", ())]
    sensors = [
        {
            "entity_id": entity_id,
            "role": _assignment_sensor_role(entity_id).value,
            "leg": _assignment_leg_hint(entity_id),
        }
        for entity_id in entity_ids
    ]
    return {
        "circuit_id": _slugify(name),
        "name": name,
        "appliance_profile": profile,
        "mode": mode,
        "sensors": sensors,
    }


def _final_config_from_reviewed_circuits(
    pending_config: Mapping[str, Any],
    circuits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    circuit_list = [dict(circuit) for circuit in circuits]
    assigned_source_entities = list(
        dict.fromkeys(
            str(sensor.get("entity_id"))
            for circuit in circuit_list
            for sensor in circuit.get("sensors", ())
            if isinstance(sensor, Mapping) and sensor.get("entity_id")
        )
    )
    if not assigned_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    final_config = dict(pending_config)
    final_config[CONF_SOURCE_ENTITIES] = assigned_source_entities
    final_config[CONF_CIRCUITS] = circuit_list
    final_config[CONF_CIRCUIT_ASSIGNMENTS] = _assignment_text_from_circuits(
        circuit_list
    )
    return final_config


def _assignment_text_from_circuits(circuits: Iterable[Mapping[str, Any]]) -> str:
    lines = [
        "# Format: Circuit name | appliance_type | mode | entity_id, entity_id",
        "# Generated from guided circuit assignment review.",
    ]
    for circuit in circuits:
        lines.append(
            " | ".join(
                (
                    str(circuit.get("name") or circuit.get("circuit_id") or "Circuit"),
                    str(circuit.get("appliance_profile") or ApplianceProfile.MIXED),
                    str(circuit.get("mode") or CircuitMode.MIXED),
                    ", ".join(
                        str(sensor.get("entity_id"))
                        for sensor in circuit.get("sensors", ())
                        if isinstance(sensor, Mapping) and sensor.get("entity_id")
                    ),
                )
            )
        )
    return "\n".join(lines)


def default_assignment_text(source_entities: Iterable[str]) -> str:
    """Build editable non-JSON circuit assignment lines from source entities."""
    groups: dict[str, list[str]] = {}
    for entity_id in source_entities:
        circuit_id = _assignment_circuit_id_from_entity_id(entity_id)
        groups.setdefault(circuit_id, []).append(entity_id)

    lines = [
        "# Format: Circuit name | appliance_type | mode | entity_id, entity_id",
        "# Use appliance_type 'exclude' to leave a detected group out.",
    ]
    for circuit_id, entity_ids in groups.items():
        profile, mode = _suggest_assignment_profile_mode(circuit_id, entity_ids)
        lines.append(
            " | ".join(
                (
                    _friendly_name_from_id(circuit_id),
                    profile,
                    mode,
                    ", ".join(entity_ids),
                )
            )
        )
    return "\n".join(lines)


def build_config_from_assignment_input(
    pending_config: Mapping[str, Any],
    assignment_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Build final config/options data from source selection and assignment text."""
    circuits, assigned_source_entities = _circuits_from_assignment_text(
        str(assignment_input.get(CONF_CIRCUIT_ASSIGNMENTS, ""))
    )
    if not assigned_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    final_config = dict(pending_config)
    final_config[CONF_SOURCE_ENTITIES] = assigned_source_entities
    final_config[CONF_CIRCUITS] = circuits
    final_config[CONF_CIRCUIT_ASSIGNMENTS] = str(
        assignment_input.get(CONF_CIRCUIT_ASSIGNMENTS, "")
    )
    return final_config


def _circuits_from_assignment_text(
    assignment_text: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    circuits: list[dict[str, Any]] = []
    assigned_source_entities: list[str] = []
    for raw_line in assignment_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4 or not parts[0] or not parts[1] or not parts[3]:
            raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
        name, raw_profile, raw_mode, raw_entities = parts
        profile = _normalize_assignment_profile(raw_profile)
        mode = _normalize_assignment_mode(raw_mode)
        entity_ids = _strict_string_list(
            raw_entities,
            invalid_error_key=ERROR_INVALID_CIRCUIT_ASSIGNMENTS,
        )
        if profile == "exclude":
            continue
        if profile not in _ASSIGNMENT_PROFILE_OPTIONS:
            raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
        sensors = [
            {
                "entity_id": entity_id,
                "role": _assignment_sensor_role(entity_id).value,
                "leg": _assignment_leg_hint(entity_id),
            }
            for entity_id in entity_ids
        ]
        circuits.append(
            {
                "circuit_id": _slugify(name),
                "name": name,
                "appliance_profile": profile,
                "mode": mode,
                "sensors": sensors,
            }
        )
        assigned_source_entities.extend(entity_ids)
    return circuits, list(dict.fromkeys(assigned_source_entities))


def _normalize_assignment_profile(raw_profile: str) -> str:
    normalized = _slugify(raw_profile)
    aliases = {
        "ac_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "a_c_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "air_conditioner": ApplianceProfile.HVAC_COMPRESSOR.value,
        "heat_pump": ApplianceProfile.HVAC_COMPRESSOR.value,
        "compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "air_handler": ApplianceProfile.HVAC_BLOWER.value,
        "hvac_air_handler": ApplianceProfile.HVAC_BLOWER.value,
        "blower": ApplianceProfile.HVAC_BLOWER.value,
        "aux_heat": ApplianceProfile.ELECTRIC_HEAT.value,
        "electric_aux_heat": ApplianceProfile.ELECTRIC_HEAT.value,
        "heat_strip": ApplianceProfile.ELECTRIC_HEAT.value,
        "well_pump": ApplianceProfile.WATER_PUMP.value,
        "booster_pump": ApplianceProfile.WATER_PUMP.value,
        "car_charger": ApplianceProfile.EV_CHARGER.value,
    }
    return aliases.get(normalized, normalized)


def _normalize_assignment_mode(raw_mode: str) -> str:
    normalized = _slugify(raw_mode)
    aliases = {
        "single": CircuitMode.SINGLE_PHASE.value,
        "single_phase": CircuitMode.SINGLE_PHASE.value,
        "dual": CircuitMode.DUAL_PHASE.value,
        "dual_phase": CircuitMode.DUAL_PHASE.value,
        "split_phase": CircuitMode.DUAL_PHASE.value,
        "mixed": CircuitMode.MIXED.value,
        "mains": CircuitMode.MAINS_NILM.value,
        "mains_nilm": CircuitMode.MAINS_NILM.value,
    }
    mode = aliases.get(normalized, normalized)
    if mode not in _ASSIGNMENT_MODE_OPTIONS:
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
    return mode


def _assignment_sensor_role(entity_id: str) -> SensorRole:
    role = infer_sensor_role(entity_id, entity_id)
    return role if role is not None else SensorRole.REAL_POWER


def _assignment_leg_hint(entity_id: str) -> str | None:
    object_id = str(entity_id).split(".")[-1].lower()
    if re.search(r"(?:^|_)(?:l1|leg_a|line_a|phase_a|ct1)(?:_|$)", object_id):
        return "a"
    if re.search(r"(?:^|_)(?:l2|leg_b|line_b|phase_b|ct2)(?:_|$)", object_id):
        return "b"
    return None


def _assignment_circuit_id_from_entity_id(entity_id: str) -> str:
    object_id = str(entity_id).split(".")[-1].strip().lower()
    for suffix in (
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
    ):
        if object_id.endswith(suffix):
            object_id = object_id[: -len(suffix)]
            break
    for suffix in (
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
        "_l1",
        "_l2",
    ):
        if object_id.endswith(suffix):
            return object_id[: -len(suffix)]
    return object_id


def _suggest_assignment_profile_mode(
    circuit_id: str,
    entity_ids: Iterable[str],
) -> tuple[str, str]:
    text = f"_{circuit_id}_{' '.join(entity_ids)}_".lower()
    is_dual = any(
        _assignment_leg_hint(entity_id) in {"a", "b"} for entity_id in entity_ids
    ) and any(_assignment_leg_hint(entity_id) == "b" for entity_id in entity_ids)
    if any(token in text for token in ("_air_handler_", "_blower_")):
        return ApplianceProfile.HVAC_BLOWER.value, CircuitMode.SINGLE_PHASE.value
    if any(
        token in text for token in ("_aux_heat_", "_electric_heat_", "_heat_strip_")
    ):
        return ApplianceProfile.ELECTRIC_HEAT.value, CircuitMode.DUAL_PHASE.value
    if any(
        token in text
        for token in ("_compressor_", "_heat_pump_", "_air_conditioner_", "_ac_")
    ):
        return ApplianceProfile.HVAC_COMPRESSOR.value, CircuitMode.DUAL_PHASE.value
    if "_hvac_" in text:
        return ApplianceProfile.HVAC.value, (
            CircuitMode.DUAL_PHASE.value if is_dual else CircuitMode.SINGLE_PHASE.value
        )
    if "_water_pump_" in text or "_well_pump_" in text or "_booster_pump_" in text:
        return ApplianceProfile.WATER_PUMP.value, CircuitMode.SINGLE_PHASE.value
    if "_sump_pump_" in text:
        return ApplianceProfile.SUMP_PUMP.value, CircuitMode.SINGLE_PHASE.value
    if "_pool_pump_" in text:
        return ApplianceProfile.POOL_PUMP.value, CircuitMode.SINGLE_PHASE.value
    for token, profile, mode in (
        (
            "_fridge_",
            ApplianceProfile.REFRIGERATOR.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        (
            "_refrigerator_",
            ApplianceProfile.REFRIGERATOR.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        ("_freezer_", ApplianceProfile.FREEZER.value, CircuitMode.SINGLE_PHASE.value),
        (
            "_water_heater_",
            ApplianceProfile.WATER_HEATER.value,
            CircuitMode.DUAL_PHASE.value,
        ),
        ("_oven_", ApplianceProfile.OVEN.value, CircuitMode.DUAL_PHASE.value),
        ("_dryer_", ApplianceProfile.DRYER.value, CircuitMode.DUAL_PHASE.value),
        (
            "_solar_",
            ApplianceProfile.SOLAR_INVERTER.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        (
            "_inverter_",
            ApplianceProfile.SOLAR_INVERTER.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        ("_charger_", ApplianceProfile.EV_CHARGER.value, CircuitMode.DUAL_PHASE.value),
        ("_charging_", ApplianceProfile.EV_CHARGER.value, CircuitMode.DUAL_PHASE.value),
        ("_vehicle_", ApplianceProfile.EV_CHARGER.value, CircuitMode.DUAL_PHASE.value),
        ("_evse_", ApplianceProfile.EV_CHARGER.value, CircuitMode.DUAL_PHASE.value),
    ):
        if token in text:
            return profile, mode
    return ApplianceProfile.MIXED.value, CircuitMode.MIXED.value


def _friendly_name_from_id(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "circuit"


class CircuitSetupEnergyAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for CircuitSetup Energy Analyzer."""

    VERSION = 1
    MINOR_VERSION = 1
    _pending_config: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CircuitSetupEnergyAnalyzerOptionsFlow:
        """Create the options flow."""
        return CircuitSetupEnergyAnalyzerOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle user setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                validated = validate_setup_input(
                    await _async_source_selection_with_device_entities(
                        getattr(self, "hass", None),
                        user_input,
                    )
                )
            except SetupValidationError as err:
                errors["base"] = err.error_key
            else:
                return _start_assignment_review(self, validated)

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema(
                await _async_discover_energy_source_entities(
                    getattr(self, "hass", None),
                )
            ),
            errors=errors,
        )

    async def async_step_assign(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm or edit circuit assignments."""
        if user_input is not None:
            try:
                assignment_result = _handle_assignment_review_submission(
                    self,
                    user_input,
                )
            except SetupValidationError as err:
                return _assignment_review_form(self, errors={"base": err.error_key})
            if assignment_result.get("type") == "form":
                return assignment_result
            final_config = assignment_result
            return self.async_create_entry(title=TITLE, data=final_config)

        return _assignment_review_form(self)


class CircuitSetupEnergyAnalyzerOptionsFlow(_OPTIONS_FLOW_BASE):
    """Options flow for CircuitSetup Energy Analyzer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending_config: dict[str, Any] | None = None
        self._assignment_groups: list[dict[str, Any]] = []
        self._assignment_index = 0
        self._reviewed_circuits: list[dict[str, Any]] = []

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is None:
            return self.async_show_menu(
                step_id="init",
                menu_options=["assign", "sources"],
            )

        return await self.async_step_sources(user_input)

    async def async_step_sources(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit source devices and source sensors before reviewing assignments."""
        if user_input is not None:
            try:
                validated = validate_options_input(
                    await _async_source_selection_with_device_entities(
                        getattr(self, "hass", None),
                        user_input,
                    )
                )
            except SetupValidationError as err:
                return await self._async_show_options_form({"base": err.error_key})
            return _start_assignment_review(
                self,
                validated,
                existing_circuits=_options_existing_circuits(self._config_entry),
            )

        return await self._async_show_options_form()

    async def async_step_assign(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm or edit circuit assignments in options."""
        if user_input is None and not self._assignment_groups:
            try:
                pending_config = _options_source_payload(self._config_entry)
            except SetupValidationError as err:
                return await self._async_show_options_form({"base": err.error_key})
            return _start_assignment_review(
                self,
                pending_config,
                existing_circuits=_options_existing_circuits(self._config_entry),
            )

        if user_input is not None:
            try:
                assignment_result = _handle_assignment_review_submission(
                    self,
                    user_input,
                )
            except SetupValidationError as err:
                return _assignment_review_form(self, errors={"base": err.error_key})
            if assignment_result.get("type") == "form":
                return assignment_result
            final_config = assignment_result
            return self.async_create_entry(title="", data=final_config)

        return _assignment_review_form(self)

    async def _async_show_options_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        source_entity_ids = await _async_discover_energy_source_entities(
            getattr(self, "hass", None),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self._config_entry, source_entity_ids),
            errors=errors or {},
        )


def _options_schema(
    config_entry: config_entries.ConfigEntry,
    source_entity_ids: Iterable[str] | None = None,
) -> Any:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    source_entities = options.get(
        CONF_SOURCE_ENTITIES,
        data.get(CONF_SOURCE_ENTITIES, []),
    )
    source_devices = options.get(
        CONF_SOURCE_DEVICES,
        data.get(CONF_SOURCE_DEVICES, []),
    )
    extra_source_entities = options.get(
        CONF_EXTRA_SOURCE_ENTITIES,
        data.get(CONF_EXTRA_SOURCE_ENTITIES, source_entities),
    )
    mains_source_entities = options.get(
        CONF_MAINS_SOURCE_ENTITIES,
        data.get(CONF_MAINS_SOURCE_ENTITIES, []),
    )
    selectable_source_entities = [
        *list(source_entity_ids or ()),
        *_DEMO_SOURCE_ENTITY_IDS,
        *_strict_string_list(
            source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        ),
        *_strict_string_list(
            mains_source_entities,
            invalid_error_key="invalid_mains_source_entities",
        ),
    ]
    return vol.Schema(
        {
            vol.Optional(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                default=options.get(
                    CONF_ENABLE_EXPERIMENTAL_NILM,
                    data.get(
                        CONF_ENABLE_EXPERIMENTAL_NILM,
                        DEFAULT_ENABLE_EXPERIMENTAL_NILM,
                    ),
                ),
            ): bool,
            vol.Optional(
                CONF_SOURCE_DEVICES,
                default=source_devices,
            ): _source_device_selector(),
            vol.Optional(
                CONF_EXTRA_SOURCE_ENTITIES,
                default=extra_source_entities,
            ): _energy_entity_list_selector(selectable_source_entities),
            vol.Optional(
                CONF_MAINS_SOURCE_ENTITIES,
                default=mains_source_entities,
            ): _energy_entity_list_selector(selectable_source_entities),
            vol.Optional(
                CONF_SENSITIVITY,
                default=options.get(
                    CONF_SENSITIVITY,
                    data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
                ),
            ): _select_selector(_SENSITIVITY_OPTIONS),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=options.get(
                    CONF_RETENTION_MODE,
                    data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
                ),
            ): _select_selector(sorted(_VALID_RETENTION_MODES)),
        }
    )


def _options_source_payload(config_entry: config_entries.ConfigEntry) -> dict[str, Any]:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    source_entities = _strict_string_list(
        options.get(CONF_SOURCE_ENTITIES, data.get(CONF_SOURCE_ENTITIES, [])),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    extra_source_entities = _strict_string_list(
        options.get(
            CONF_EXTRA_SOURCE_ENTITIES,
            data.get(CONF_EXTRA_SOURCE_ENTITIES, source_entities),
        ),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    merged_source_entities = list(
        dict.fromkeys([*extra_source_entities, *source_entities])
    )
    if not merged_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    return {
        CONF_SOURCE_DEVICES: _strict_string_list(
            options.get(CONF_SOURCE_DEVICES, data.get(CONF_SOURCE_DEVICES, [])),
            invalid_error_key="invalid_source_devices",
        ),
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: merged_source_entities,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            options.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                data.get(
                    CONF_ENABLE_EXPERIMENTAL_NILM,
                    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
                ),
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _strict_string_list(
            options.get(
                CONF_MAINS_SOURCE_ENTITIES,
                data.get(CONF_MAINS_SOURCE_ENTITIES, []),
            ),
            invalid_error_key="invalid_mains_source_entities",
        ),
        CONF_SENSITIVITY: str(
            options.get(
                CONF_SENSITIVITY,
                data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        ),
        CONF_RETENTION_MODE: _validate_retention_mode(
            {
                CONF_RETENTION_MODE: options.get(
                    CONF_RETENTION_MODE,
                    data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
                )
            }
        ),
    }


def _options_existing_circuits(
    config_entry: config_entries.ConfigEntry,
) -> Iterable[Mapping[str, Any]]:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    return options.get(CONF_CIRCUITS, data.get(CONF_CIRCUITS, []))


async def _async_format_mapping_suggestions(hass: Any) -> str:
    if hass is None:
        return format_mapping_suggestions([])
    try:
        discovered = await async_discover_sensors(hass)
    except Exception:
        discovered = []
    return format_mapping_suggestions(suggest_dual_phase_pairs(discovered))


async def _async_source_selection_with_device_entities(
    hass: Any,
    user_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Return source selection with selected devices expanded to source entities."""
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    legacy_source_entities = _strict_string_list(
        user_input.get(CONF_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    device_source_entities = await _async_discover_energy_source_entities_for_devices(
        hass,
        source_devices,
    )
    merged = list(
        dict.fromkeys(
            [
                *device_source_entities,
                *extra_source_entities,
                *legacy_source_entities,
            ]
        )
    )
    return {
        **dict(user_input),
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: merged,
    }


async def _async_discover_energy_source_entities(hass: Any) -> list[str]:
    if hass is None:
        return []
    try:
        return await async_discover_energy_source_entities(hass)
    except Exception:
        return []


async def _async_discover_energy_source_entities_for_devices(
    hass: Any,
    source_devices: Iterable[str],
) -> list[str]:
    if hass is None:
        return []
    try:
        return await async_discover_energy_source_entities_for_devices(
            hass,
            tuple(source_devices),
        )
    except Exception:
        return []
