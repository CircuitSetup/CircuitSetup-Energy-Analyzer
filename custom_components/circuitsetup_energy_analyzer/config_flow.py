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

from .balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
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
    async_discover_utility_energy_entities,
    async_discover_utility_statistic_ids,
    infer_sensor_role,
)
from .load_shift import FLEXIBLE_LOAD_RUNNING_THRESHOLD_W
from .mapping import DualPhaseSuggestion, suggest_dual_phase_pairs
from .metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from .models import (
    ApplianceProfile,
    CircuitMode,
    PowerFlowMode,
    RetentionMode,
    SensorRole,
)
from .phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from .solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from .utility_comparison import (
    DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
    DEFAULT_UTILITY_SOURCE_TYPE,
    DEFAULT_UTILITY_STATISTIC_PERIOD,
    VALID_UTILITY_SOURCE_TYPES,
    VALID_UTILITY_STATISTIC_PERIODS,
)

TITLE = "CircuitSetup Energy Analyzer"
ERROR_NO_SOURCE_ENTITIES = "no_source_entities"
ERROR_INVALID_SOURCE_ENTITIES = "invalid_source_entities"
ERROR_INVALID_CIRCUIT_ASSIGNMENTS = "invalid_circuit_assignments"
_VALID_RETENTION_MODES = {mode.value for mode in RetentionMode}
_SENSITIVITY_OPTIONS = ("standard", "high", "low")
_SENSITIVITY_LABELS = {
    "standard": "Standard",
    "high": "High",
    "low": "Low",
}
FIELD_INCLUDE_CIRCUIT = "include_circuit"
FIELD_INCLUDED_SENSORS = "included_sensors"
FIELD_SELECTED_ASSIGNMENT = "selected_assignment"
FIELD_CIRCUIT_NAME = "circuit_name"
FIELD_APPLIANCE_PROFILE = "appliance_profile"
FIELD_CIRCUIT_MODE = "circuit_mode"
FIELD_POWER_FLOW = "power_flow"
FIELD_CIRCUIT_RETENTION_MODE = "circuit_retention_mode"
FIELD_ENABLE_UTILITY_COMPARISON = "enable_utility_comparison"
FIELD_CIRCUIT_ID = "circuit_id"
FIELD_UTILITY_ENERGY_ENTITY = "utility_energy_entity"
FIELD_UTILITY_STATISTIC_ID = "utility_statistic_id"
FIELD_UTILITY_SOURCE_TYPE = "utility_source_type"
FIELD_UTILITY_STATISTIC_PERIOD = "utility_statistic_period"
FIELD_MEASURED_ENERGY_ENTITIES = "measured_energy_entities"
FIELD_TOLERANCE_PERCENT = "tolerance_percent"
FIELD_PRESET = "preset"
FIELD_WINDOW_DAYS = "window_days"
FIELD_DAILY_SPIKE_RATIO = "daily_spike_ratio"
FIELD_DAILY_GOAL_KWH = "daily_goal_kwh"
FIELD_GOAL_ALERT_RATIO = "goal_alert_ratio"
FIELD_MAX_ACTIVE_MINUTES = "max_active_minutes"
FIELD_MAX_IDLE_MINUTES = "max_idle_minutes"
FIELD_CYCLE_START_DAY = "cycle_start_day"
FIELD_BUDGET_KWH = "budget_kwh"
FIELD_BUDGET_ALERT_RATIO = "budget_alert_ratio"
FIELD_BILLING_MIN_ELAPSED_DAYS = "billing_min_elapsed_days"
FIELD_DEFAULT_RATE_PER_KWH = "default_rate_per_kwh"
FIELD_TOU_RATE_PER_KWH = "tou_rate_per_kwh"
FIELD_TOU_START = "tou_start"
FIELD_TOU_END = "tou_end"
FIELD_TOU_WEEKDAYS = "tou_weekdays"
FIELD_TOU_NAME = "tou_name"
FIELD_WINDOW_MINUTES = "window_minutes"
FIELD_DEMAND_LIMIT_W = "demand_limit_w"
FIELD_BREAKER_AMPS = "breaker_amps"
FIELD_WARNING_RATIO = "warning_ratio"
FIELD_WINDOW_HOURS = "window_hours"
FIELD_STANDBY_THRESHOLD_W = "standby_threshold_w"
FIELD_ALWAYS_ON_ALERT_W = "always_on_alert_w"
FIELD_STANDBY_MIN_SAMPLES = "standby_min_samples"
FIELD_LEG_IMBALANCE_WARNING_RATIO = "leg_imbalance_warning_ratio"
FIELD_LEG_IMBALANCE_MIN_TOTAL_POWER_W = "leg_imbalance_min_total_power_w"
FIELD_APPARENT_POWER_TOLERANCE_PERCENT = "apparent_power_tolerance_percent"
FIELD_POWER_FACTOR_TOLERANCE = "power_factor_tolerance"
FIELD_MINIMUM_APPARENT_POWER_VA = "minimum_apparent_power_va"
FIELD_BALANCE_NEGATIVE_TOLERANCE_W = "balance_negative_tolerance_w"
FIELD_SOLAR_EXPORT_TOLERANCE_W = "solar_export_tolerance_w"
FIELD_SOLAR_SURPLUS_THRESHOLD_W = "solar_surplus_threshold_w"
FIELD_HIGH_SOLAR_SURPLUS_THRESHOLD_W = "high_solar_surplus_threshold_w"
FIELD_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W = "flexible_load_running_threshold_w"
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
    ApplianceProfile.WASHER.value,
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
_APPLIANCE_PROFILE_LABELS = {
    "exclude": "Exclude",
    ApplianceProfile.HVAC.value: "HVAC",
    ApplianceProfile.HVAC_COMPRESSOR.value: "HVAC Compressor",
    ApplianceProfile.HVAC_BLOWER.value: "HVAC Blower",
    ApplianceProfile.EV_CHARGER.value: "EV Charger",
    ApplianceProfile.MAINS_NILM.value: "Mains NILM",
}
_ASSIGNMENT_MODE_OPTIONS = {
    CircuitMode.SINGLE_PHASE.value,
    CircuitMode.DUAL_PHASE.value,
    CircuitMode.MIXED.value,
    CircuitMode.MAINS_NILM.value,
}
_RETENTION_MODE_OPTIONS = (
    RetentionMode.STANDARD.value,
    RetentionMode.LIGHTWEIGHT.value,
    RetentionMode.DIAGNOSTIC.value,
)
_RETENTION_MODE_LABELS = {
    RetentionMode.STANDARD.value: "Standard",
    RetentionMode.LIGHTWEIGHT.value: "Lightweight",
    RetentionMode.DIAGNOSTIC.value: "Diagnostic",
}
_UTILITY_SOURCE_TYPE_OPTIONS = (
    {"value": "auto", "label": "Auto"},
    {"value": "entity", "label": "Entity"},
    {"value": "statistics", "label": "Statistics"},
)
_UTILITY_STATISTIC_PERIOD_OPTIONS = (
    {"value": "hour", "label": "Hour"},
    {"value": "day", "label": "Day"},
    {"value": "month", "label": "Month"},
)
_CIRCUIT_MODE_LABELS = {
    CircuitMode.SINGLE_PHASE.value: "Single Phase",
    CircuitMode.DUAL_PHASE.value: "Dual Phase",
    CircuitMode.MIXED.value: "Mixed",
    CircuitMode.MAINS_NILM.value: "Mains NILM",
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


def _energy_kwh_entity_selector_config(
    include_entities: Iterable[str] | None = None,
    *,
    multiple: bool = True,
) -> dict[str, Any]:
    entity_ids = list(dict.fromkeys(include_entities or ()))
    config: dict[str, Any] = {
        "entity": {
            "multiple": multiple,
            "filter": [{"domain": "sensor", "device_class": "energy"}],
        }
    }
    if entity_ids:
        config["entity"]["include_entities"] = entity_ids
    return config


def _energy_entity_list_selector(
    include_entities: Iterable[str] | None = None,
) -> Any:
    return _selector(_energy_entity_selector_config(include_entities), str)


def _energy_kwh_entity_list_selector(
    include_entities: Iterable[str] | None = None,
) -> Any:
    return _selector(_energy_kwh_entity_selector_config(include_entities), str)


def _single_energy_kwh_entity_selector(
    include_entities: Iterable[str] | None = None,
) -> Any:
    return _selector(
        _energy_kwh_entity_selector_config(include_entities, multiple=False),
        str,
    )


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


def _select_selector(options: Iterable[Any]) -> Any:
    option_list = list(options)
    values = [
        str(option.get("value"))
        if isinstance(option, Mapping)
        else str(option)
        for option in option_list
    ]
    return _selector({"select": {"options": option_list}}, vol.In(tuple(values)))


def _multi_select_selector(options: Iterable[Mapping[str, str]]) -> Any:
    return _selector(
        {
            "select": {
                "multiple": True,
                "mode": "dropdown",
                "options": list(options),
            }
        },
        list,
    )


def _number_selector(
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | str = "any",
) -> Any:
    config: dict[str, Any] = {"number": {"mode": "box", "step": step}}
    if minimum is not None:
        config["number"]["min"] = minimum
    if maximum is not None:
        config["number"]["max"] = maximum
    return _selector(config, float)


def _text_selector() -> Any:
    return _selector({"text": {"multiple": False}}, str)


def sensitivity_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": _SENSITIVITY_LABELS[value]}
        for value in _SENSITIVITY_OPTIONS
    ]


def retention_mode_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": _RETENTION_MODE_LABELS[value]}
        for value in _RETENTION_MODE_OPTIONS
    ]


def appliance_profile_options() -> list[dict[str, str]]:
    return [
        {
            "value": value,
            "label": _APPLIANCE_PROFILE_LABELS.get(
                value,
                _friendly_name_from_id(value),
            ),
        }
        for value in _GUIDED_ASSIGNMENT_PROFILE_OPTIONS
    ]


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
            ): _select_selector(sensitivity_options()),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=DEFAULT_RETENTION_MODE,
            ): _select_selector(retention_mode_options()),
        }
    )


DATA_SCHEMA = _setup_schema()


def _assignment_schema(group: Mapping[str, Any]) -> Any:
    entity_ids = [str(entity_id) for entity_id in group.get("entity_ids", ())]
    return vol.Schema(
        {
            vol.Required(
                FIELD_INCLUDE_CIRCUIT,
                default=True,
            ): bool,
            vol.Required(
                FIELD_INCLUDED_SENSORS,
                default=_selected_entity_ids_for_group(group),
            ): _multi_select_selector(_assignment_sensor_options(entity_ids)),
            vol.Required(
                FIELD_CIRCUIT_NAME,
                default=str(group.get("name") or ""),
            ): str,
            vol.Required(
                FIELD_APPLIANCE_PROFILE,
                default=str(group.get("appliance_profile") or ApplianceProfile.MIXED),
            ): _select_selector(appliance_profile_options()),
            vol.Required(
                FIELD_CIRCUIT_MODE,
                default=str(group.get("mode") or CircuitMode.MIXED),
            ): _select_selector(circuit_mode_options()),
            vol.Required(
                FIELD_POWER_FLOW,
                default=_default_assignment_power_flow(group),
            ): _select_selector(power_flow_options()),
            vol.Required(
                FIELD_CIRCUIT_RETENTION_MODE,
                default=str(
                    group.get("retention_mode") or DEFAULT_RETENTION_MODE
                ),
            ): _select_selector(retention_mode_options()),
        }
    )


def _assignment_picker_schema(groups: Iterable[Mapping[str, Any]]) -> Any:
    options = assignment_picker_options(groups)
    default = options[0]["value"] if options else ""
    return vol.Schema(
        {
            vol.Required(
                FIELD_SELECTED_ASSIGNMENT,
                default=default,
            ): _select_selector(options),
        }
    )


def _mains_schema(
    config_entry: config_entries.ConfigEntry,
    source_entity_ids: Iterable[str] | None = None,
) -> Any:
    mains_source_entities = _entry_value(
        config_entry,
        CONF_MAINS_SOURCE_ENTITIES,
        [],
    )
    source_entities = _entry_value(config_entry, CONF_SOURCE_ENTITIES, [])
    selectable_source_entities = [
        *list(source_entity_ids or ()),
        *_DEMO_SOURCE_ENTITY_IDS,
        *_strict_string_list(
            source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        ),
    ]
    return vol.Schema(
        {
            vol.Optional(
                CONF_MAINS_SOURCE_ENTITIES,
                default=mains_source_entities,
            ): _energy_entity_list_selector(selectable_source_entities),
        }
    )


def _utility_schema(
    config: Mapping[str, Any],
    *,
    utility_energy_entities: Iterable[str] = (),
    utility_statistic_ids: Iterable[str] = (),
    measured_energy_entities: Iterable[str] = (),
    current_settings: Mapping[str, Any] | None = None,
) -> Any:
    settings = dict(current_settings or {})
    circuit_options = _circuit_options_from_config(config, include_mains=True)
    default_circuit = _default_circuit_id(circuit_options)
    selectable_utility_entities = list(
        dict.fromkeys(
            [
                *utility_energy_entities,
                settings.get(FIELD_UTILITY_ENERGY_ENTITY, ""),
            ]
        )
    )
    selectable_measured_entities = list(
        dict.fromkeys(
            [
                *measured_energy_entities,
                *_strict_string_list(
                    config.get(CONF_MAINS_SOURCE_ENTITIES, []),
                    invalid_error_key="invalid_mains_source_entities",
                ),
                *settings.get(FIELD_MEASURED_ENERGY_ENTITIES, []),
            ]
        )
    )
    statistic_options = [
        {"value": statistic_id, "label": statistic_id}
        for statistic_id in dict.fromkeys(
            [
                *utility_statistic_ids,
                settings.get(FIELD_UTILITY_STATISTIC_ID, ""),
            ]
        )
        if statistic_id
    ]
    statistic_selector = (
        _select_selector(statistic_options) if statistic_options else _text_selector()
    )
    return vol.Schema(
        {
            vol.Required(
                FIELD_ENABLE_UTILITY_COMPARISON,
                default=bool(settings),
            ): bool,
            vol.Required(
                FIELD_CIRCUIT_ID,
                default=str(settings.get(FIELD_CIRCUIT_ID) or default_circuit),
            ): _select_selector(circuit_options),
            vol.Optional(
                FIELD_UTILITY_ENERGY_ENTITY,
                default=str(
                    settings.get(FIELD_UTILITY_ENERGY_ENTITY)
                    or _first_or_empty(selectable_utility_entities)
                ),
            ): _single_energy_kwh_entity_selector(selectable_utility_entities),
            vol.Optional(
                FIELD_UTILITY_STATISTIC_ID,
                default=str(
                    settings.get(FIELD_UTILITY_STATISTIC_ID)
                    or _first_or_empty(utility_statistic_ids)
                ),
            ): statistic_selector,
            vol.Optional(
                FIELD_UTILITY_SOURCE_TYPE,
                default=str(
                    settings.get(
                        FIELD_UTILITY_SOURCE_TYPE,
                        DEFAULT_UTILITY_SOURCE_TYPE,
                    )
                ),
            ): _select_selector(_UTILITY_SOURCE_TYPE_OPTIONS),
            vol.Optional(
                FIELD_UTILITY_STATISTIC_PERIOD,
                default=str(
                    settings.get(
                        FIELD_UTILITY_STATISTIC_PERIOD,
                        DEFAULT_UTILITY_STATISTIC_PERIOD,
                    )
                ),
            ): _select_selector(_UTILITY_STATISTIC_PERIOD_OPTIONS),
            vol.Optional(
                FIELD_MEASURED_ENERGY_ENTITIES,
                default=list(settings.get(FIELD_MEASURED_ENERGY_ENTITIES, [])),
            ): _energy_kwh_entity_list_selector(selectable_measured_entities),
            vol.Optional(
                FIELD_TOLERANCE_PERCENT,
                default=float(
                    settings.get(
                        FIELD_TOLERANCE_PERCENT,
                        DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
                    )
                ),
            ): _number_selector(minimum=0.0, maximum=100.0, step=0.1),
        }
    )


def _advanced_circuit_schema(config: Mapping[str, Any]) -> Any:
    circuit_options = _circuit_options_from_config(config, include_mains=True)
    return vol.Schema(
        {
            vol.Required(
                FIELD_CIRCUIT_ID,
                default=_default_circuit_id(circuit_options),
            ): _select_selector(circuit_options),
        }
    )


def _nilm_schema(
    config: Mapping[str, Any],
    known_load_circuits: Iterable[str] = (),
) -> Any:
    return vol.Schema(
        {
            vol.Optional(
                CONF_KNOWN_LOAD_CIRCUITS,
                default=list(known_load_circuits),
            ): _multi_select_selector(_known_load_circuit_options_from_config(config)),
        }
    )


def _advanced_settings_schema(current_settings: Mapping[str, Any] | None = None) -> Any:
    settings = dict(current_settings or {})
    return vol.Schema(
        {
            vol.Optional(
                FIELD_PRESET,
                default=str(settings.get(FIELD_PRESET, DEFAULT_SENSITIVITY)),
            ): _select_selector(sensitivity_options()),
            vol.Optional(
                FIELD_WINDOW_DAYS,
                default=int(settings.get(FIELD_WINDOW_DAYS, 7)),
            ): _number_selector(minimum=1, maximum=90, step=1),
            vol.Optional(
                FIELD_DAILY_SPIKE_RATIO,
                default=float(settings.get(FIELD_DAILY_SPIKE_RATIO, 0.25)),
            ): _number_selector(minimum=0.01, maximum=5.0, step=0.01),
            vol.Optional(
                FIELD_DAILY_GOAL_KWH,
                default=float(settings.get(FIELD_DAILY_GOAL_KWH, 0.0)),
            ): _number_selector(minimum=0.0, step=0.1),
            vol.Optional(
                FIELD_GOAL_ALERT_RATIO,
                default=float(settings.get(FIELD_GOAL_ALERT_RATIO, 1.0)),
            ): _number_selector(minimum=0.0, maximum=5.0, step=0.01),
            vol.Optional(
                FIELD_MAX_ACTIVE_MINUTES,
                default=int(settings.get(FIELD_MAX_ACTIVE_MINUTES, 0)),
            ): _number_selector(minimum=0, step=1),
            vol.Optional(
                FIELD_MAX_IDLE_MINUTES,
                default=int(settings.get(FIELD_MAX_IDLE_MINUTES, 0)),
            ): _number_selector(minimum=0, step=1),
            vol.Optional(
                FIELD_CYCLE_START_DAY,
                default=int(settings.get(FIELD_CYCLE_START_DAY, 1)),
            ): _number_selector(minimum=1, maximum=31, step=1),
            vol.Optional(
                FIELD_BUDGET_KWH,
                default=float(settings.get(FIELD_BUDGET_KWH, 0.0)),
            ): _number_selector(minimum=0.0, step=0.1),
            vol.Optional(
                FIELD_BUDGET_ALERT_RATIO,
                default=float(settings.get(FIELD_BUDGET_ALERT_RATIO, 1.0)),
            ): _number_selector(minimum=0.0, maximum=5.0, step=0.01),
            vol.Optional(
                FIELD_BILLING_MIN_ELAPSED_DAYS,
                default=int(settings.get("min_elapsed_days", 3)),
            ): _number_selector(minimum=1, maximum=31, step=1),
            vol.Optional(
                FIELD_DEFAULT_RATE_PER_KWH,
                default=float(settings.get(FIELD_DEFAULT_RATE_PER_KWH, 0.0)),
            ): _number_selector(minimum=0.0, step="any"),
            vol.Optional(
                FIELD_TOU_RATE_PER_KWH,
                default=float(settings.get(FIELD_TOU_RATE_PER_KWH, 0.0)),
            ): _number_selector(minimum=0.0, step="any"),
            vol.Optional(
                FIELD_TOU_START,
                default=str(settings.get(FIELD_TOU_START) or ""),
            ): _text_selector(),
            vol.Optional(
                FIELD_TOU_END,
                default=str(settings.get(FIELD_TOU_END) or ""),
            ): _text_selector(),
            vol.Optional(
                FIELD_TOU_WEEKDAYS,
                default=str(settings.get(FIELD_TOU_WEEKDAYS) or ""),
            ): _text_selector(),
            vol.Optional(
                FIELD_TOU_NAME,
                default=str(settings.get(FIELD_TOU_NAME) or "Peak"),
            ): _text_selector(),
            vol.Optional(
                FIELD_WINDOW_MINUTES,
                default=int(settings.get(FIELD_WINDOW_MINUTES, 15)),
            ): _number_selector(minimum=1, maximum=240, step=1),
            vol.Optional(
                FIELD_DEMAND_LIMIT_W,
                default=float(settings.get(FIELD_DEMAND_LIMIT_W, 0.0)),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_BREAKER_AMPS,
                default=float(settings.get(FIELD_BREAKER_AMPS, 0.0)),
            ): _number_selector(minimum=0.0, step=0.1),
            vol.Optional(
                FIELD_WARNING_RATIO,
                default=float(settings.get(FIELD_WARNING_RATIO, 0.8)),
            ): _number_selector(minimum=0.0, maximum=1.0, step=0.01),
            vol.Optional(
                FIELD_WINDOW_HOURS,
                default=int(settings.get(FIELD_WINDOW_HOURS, 48)),
            ): _number_selector(minimum=1, maximum=720, step=1),
            vol.Optional(
                FIELD_STANDBY_THRESHOLD_W,
                default=float(settings.get(FIELD_STANDBY_THRESHOLD_W, 8.0)),
            ): _number_selector(minimum=0.0, step=0.1),
            vol.Optional(
                FIELD_ALWAYS_ON_ALERT_W,
                default=float(settings.get(FIELD_ALWAYS_ON_ALERT_W, 0.0)),
            ): _number_selector(minimum=0.0, step=0.1),
            vol.Optional(
                FIELD_STANDBY_MIN_SAMPLES,
                default=int(settings.get("min_samples", 24)),
            ): _number_selector(minimum=1, maximum=720, step=1),
            vol.Optional(
                FIELD_LEG_IMBALANCE_WARNING_RATIO,
                default=float(
                    settings.get(
                        FIELD_LEG_IMBALANCE_WARNING_RATIO,
                        DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
                    )
                ),
            ): _number_selector(minimum=0.01, maximum=2.0, step=0.01),
            vol.Optional(
                FIELD_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                default=float(
                    settings.get(
                        FIELD_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                        DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_APPARENT_POWER_TOLERANCE_PERCENT,
                default=float(
                    settings.get(
                        FIELD_APPARENT_POWER_TOLERANCE_PERCENT,
                        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
                    )
                ),
            ): _number_selector(minimum=0.1, maximum=100.0, step=0.1),
            vol.Optional(
                FIELD_POWER_FACTOR_TOLERANCE,
                default=float(
                    settings.get(
                        FIELD_POWER_FACTOR_TOLERANCE,
                        DEFAULT_POWER_FACTOR_TOLERANCE,
                    )
                ),
            ): _number_selector(minimum=0.001, maximum=1.0, step=0.001),
            vol.Optional(
                FIELD_MINIMUM_APPARENT_POWER_VA,
                default=float(
                    settings.get(
                        FIELD_MINIMUM_APPARENT_POWER_VA,
                        DEFAULT_MIN_APPARENT_POWER_VA,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_BALANCE_NEGATIVE_TOLERANCE_W,
                default=float(
                    settings.get(
                        FIELD_BALANCE_NEGATIVE_TOLERANCE_W,
                        DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_SOLAR_EXPORT_TOLERANCE_W,
                default=float(
                    settings.get(
                        FIELD_SOLAR_EXPORT_TOLERANCE_W,
                        EXPORT_TOLERANCE_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_SOLAR_SURPLUS_THRESHOLD_W,
                default=float(
                    settings.get(
                        FIELD_SOLAR_SURPLUS_THRESHOLD_W,
                        SOLAR_SURPLUS_THRESHOLD_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                default=float(
                    settings.get(
                        FIELD_HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                        HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
            vol.Optional(
                FIELD_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                default=float(
                    settings.get(
                        FIELD_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                        FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                    )
                ),
            ): _number_selector(minimum=0.0, step=1),
        }
    )


def circuit_mode_options() -> list[dict[str, str]]:
    return [
        {"value": CircuitMode.SINGLE_PHASE.value, "label": "Single Phase"},
        {"value": CircuitMode.DUAL_PHASE.value, "label": "Dual Phase"},
        {"value": CircuitMode.MIXED.value, "label": "Mixed"},
        {"value": CircuitMode.MAINS_NILM.value, "label": "Mains NILM"},
    ]


def power_flow_options() -> list[dict[str, str]]:
    """Return real-power sign convention options with readable labels."""
    return [
        {"value": PowerFlowMode.LOAD.value, "label": "Load"},
        {
            "value": PowerFlowMode.GENERATION.value,
            "label": "Generation / Solar Export",
        },
        {
            "value": PowerFlowMode.MAINS_NET.value,
            "label": "Mains Net / Import-Export",
        },
    ]


def assignment_picker_options(
    groups_or_circuits: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    groups = [group for group in groups_or_circuits if isinstance(group, Mapping)]
    name_counts: dict[str, int] = {}
    for group in groups:
        name = str(group.get("name") or _assignment_group_value(group))
        name_counts[name] = name_counts.get(name, 0) + 1

    options: list[dict[str, str]] = []
    for group in groups:
        value = _assignment_group_value(group)
        if not value:
            continue
        name = str(group.get("name") or value)
        label_name = f"{name} ({value})" if name_counts.get(name, 0) > 1 else name
        mode = friendly_circuit_mode_label(str(group.get("mode") or ""))
        sensor_count = _assignment_group_sensor_count(group)
        sensor_label = "sensor" if sensor_count == 1 else "sensors"
        options.append(
            {
                "value": value,
                "label": f"{label_name} - {mode} - {sensor_count} {sensor_label}",
            }
        )
    return options


def friendly_circuit_mode_label(mode: str) -> str:
    return _CIRCUIT_MODE_LABELS.get(mode, _friendly_name_from_id(mode))


def _default_assignment_power_flow(group: Mapping[str, Any]) -> str:
    raw = str(group.get("power_flow") or "").strip()
    if raw:
        return _normalize_power_flow(raw)
    profile = str(group.get("appliance_profile") or "").strip()
    mode = str(group.get("mode") or "").strip()
    if profile == ApplianceProfile.SOLAR_INVERTER.value:
        return PowerFlowMode.GENERATION.value
    if (
        profile == ApplianceProfile.MAINS_NILM.value
        or mode == CircuitMode.MAINS_NILM.value
    ):
        return PowerFlowMode.MAINS_NET.value
    return PowerFlowMode.LOAD.value


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
            saved_sensor_entities = _sensor_entity_ids_from_circuit(saved_circuit)
            selected_entity_ids = tuple(
                entity_id
                for entity_id in entity_ids
                if entity_id in saved_sensor_entities
            ) or tuple(entity_ids)
            stable_circuit_id = str(
                saved_circuit.get("circuit_id")
                or saved_circuit.get("id")
                or ""
            ).strip()
            group.update(
                {
                    "circuit_id": stable_circuit_id or group["group_id"],
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
                    "power_flow": _normalize_power_flow(
                        str(saved_circuit.get("power_flow") or "")
                    ),
                    "retention_mode": _normalize_retention_mode(
                        str(
                            saved_circuit.get(
                                "retention_mode",
                                DEFAULT_RETENTION_MODE,
                            )
                        )
                    ),
                    "selected_entity_ids": selected_entity_ids,
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
        sensor_entities = set(_sensor_entity_ids_from_circuit(circuit))
        if group_entities and group_entities <= sensor_entities:
            return circuit
        if str(circuit.get("circuit_id") or circuit.get("id") or "") == group_id:
            return circuit
        if group_entities and sensor_entities and group_entities & sensor_entities:
            return circuit
    return None


def _sensor_entity_ids_from_circuit(circuit: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(sensor.get("entity_id"))
        for sensor in circuit.get("sensors", ())
        if isinstance(sensor, Mapping) and sensor.get("entity_id")
    )


def _assignment_group_value(group: Mapping[str, Any]) -> str:
    return str(
        group.get("circuit_id")
        or group.get("group_id")
        or group.get("id")
        or ""
    )


def _assignment_group_sensor_count(group: Mapping[str, Any]) -> int:
    sensor_entities = _sensor_entity_ids_from_circuit(group)
    if sensor_entities:
        return len(sensor_entities)
    return len(tuple(group.get("entity_ids", ()) or ()))


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


def _assignment_picker_form(
    flow: Any,
    *,
    errors: dict[str, str] | None = None,
) -> config_entries.ConfigFlowResult:
    groups = list(getattr(flow, "_assignment_groups", []) or [])
    return flow.async_show_form(
        step_id="select_assignment",
        data_schema=_assignment_picker_schema(groups),
        errors=errors or {},
        description_placeholders={"assignment_count": str(len(groups))},
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
    show_picker: bool = False,
    update_existing: bool = False,
) -> config_entries.ConfigFlowResult:
    existing_circuit_list = [
        circuit for circuit in existing_circuits if isinstance(circuit, Mapping)
    ]
    groups = assignment_groups_from_sources(
        pending_config.get(CONF_SOURCE_ENTITIES, []),
        mains_source_entities=pending_config.get(CONF_MAINS_SOURCE_ENTITIES, []),
        existing_circuits=existing_circuit_list,
    )
    flow._pending_config = dict(pending_config)
    flow._assignment_groups = groups
    flow._assignment_index = 0
    flow._reviewed_circuits = []
    flow._assignment_update_existing = bool(update_existing)
    flow._assignment_existing_circuits = existing_circuit_list
    flow._assignment_selected_circuit_id = None
    if update_existing and len(groups) == 1:
        flow._assignment_selected_circuit_id = _assignment_group_value(groups[0])
    if show_picker and len(groups) > 1:
        return _assignment_picker_form(flow)
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
    if bool(getattr(flow, "_assignment_update_existing", False)):
        return _final_config_from_single_assignment_update(
            getattr(flow, "_pending_config", {}) or {},
            getattr(flow, "_assignment_existing_circuits", []) or [],
            str(getattr(flow, "_assignment_selected_circuit_id", "") or ""),
            reviewed_circuits,
        )
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
    power_flow = _normalize_power_flow(
        str(
            user_input.get(FIELD_POWER_FLOW)
            or group.get("power_flow")
            or _default_assignment_power_flow(group)
        )
    )
    retention_mode = _normalize_retention_mode(
        str(
            user_input.get(FIELD_CIRCUIT_RETENTION_MODE)
            or group.get("retention_mode")
            or DEFAULT_RETENTION_MODE
        )
    )
    if profile not in _GUIDED_ASSIGNMENT_PROFILE_OPTIONS:
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)

    entity_ids = _included_entity_ids_for_assignment(group, user_input)
    sensors = [
        {
            "entity_id": entity_id,
            "role": _assignment_sensor_role(entity_id).value,
            "leg": _assignment_leg_hint(entity_id),
        }
        for entity_id in entity_ids
    ]
    return {
        "circuit_id": str(group.get("circuit_id") or "").strip() or _slugify(name),
        "name": name,
        "appliance_profile": profile,
        "mode": mode,
        "power_flow": power_flow,
        "retention_mode": retention_mode,
        "sensors": sensors,
    }


def _included_entity_ids_for_assignment(
    group: Mapping[str, Any],
    user_input: Mapping[str, Any],
) -> list[str]:
    allowed_entity_ids = [str(entity_id) for entity_id in group.get("entity_ids", ())]
    allowed = set(allowed_entity_ids)
    raw_selected = user_input.get(
        FIELD_INCLUDED_SENSORS,
        _selected_entity_ids_for_group(group),
    )
    selected = _strict_string_list(
        raw_selected,
        invalid_error_key=ERROR_INVALID_CIRCUIT_ASSIGNMENTS,
    )
    if not selected:
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
    if any(entity_id not in allowed for entity_id in selected):
        raise SetupValidationError(ERROR_INVALID_CIRCUIT_ASSIGNMENTS)
    selected_set = set(selected)
    return [entity_id for entity_id in allowed_entity_ids if entity_id in selected_set]


def _selected_entity_ids_for_group(group: Mapping[str, Any]) -> list[str]:
    selected = group.get("selected_entity_ids", group.get("entity_ids", ()))
    return [str(entity_id) for entity_id in selected]


def _assignment_sensor_options(entity_ids: Iterable[str]) -> list[dict[str, str]]:
    return [
        {
            "value": entity_id,
            "label": (
                f"{_friendly_name_from_id(entity_id.split('.')[-1])} "
                f"({entity_id})"
            ),
        }
        for entity_id in entity_ids
    ]


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
    circuit_ids = {
        str(circuit.get("circuit_id") or circuit.get("id") or "")
        for circuit in circuit_list
    }
    known_loads = [
        circuit_id
        for circuit_id in _strict_string_list(
            final_config.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            invalid_error_key="invalid_known_load_circuits",
        )
        if circuit_id in circuit_ids
    ]
    if known_loads or CONF_KNOWN_LOAD_CIRCUITS in final_config:
        final_config[CONF_KNOWN_LOAD_CIRCUITS] = known_loads
    final_config[CONF_CIRCUIT_ASSIGNMENTS] = _assignment_text_from_circuits(
        circuit_list
    )
    return final_config


def _final_config_from_single_assignment_update(
    pending_config: Mapping[str, Any],
    existing_circuits: Iterable[Mapping[str, Any]],
    selected_circuit_id: str,
    reviewed_circuits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    reviewed = [dict(circuit) for circuit in reviewed_circuits]
    replacement = reviewed[0] if reviewed else None
    final_circuits: list[dict[str, Any]] = []
    replaced = False
    for circuit in existing_circuits:
        current_id = str(circuit.get("circuit_id") or circuit.get("id") or "")
        if current_id == selected_circuit_id:
            replaced = True
            if replacement is not None:
                final_circuits.append(replacement)
            continue
        final_circuits.append(dict(circuit))
    if replacement is not None and not replaced:
        final_circuits.append(replacement)
    return _final_config_from_reviewed_circuits(pending_config, final_circuits)


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
        "clothes_washer": ApplianceProfile.WASHER.value,
        "laundry_washer": ApplianceProfile.WASHER.value,
        "washing_machine": ApplianceProfile.WASHER.value,
        "clothes_dryer": ApplianceProfile.DRYER.value,
        "electric_dryer": ApplianceProfile.DRYER.value,
        "gas_dryer": ApplianceProfile.DRYER.value,
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


def _normalize_power_flow(raw_power_flow: str) -> str:
    normalized = _slugify(raw_power_flow)
    aliases = {
        "bidirectional": PowerFlowMode.MAINS_NET.value,
        "net": PowerFlowMode.MAINS_NET.value,
        "mains": PowerFlowMode.MAINS_NET.value,
        "mains_net": PowerFlowMode.MAINS_NET.value,
        "import_export": PowerFlowMode.MAINS_NET.value,
        "solar": PowerFlowMode.GENERATION.value,
        "export": PowerFlowMode.GENERATION.value,
        "generation": PowerFlowMode.GENERATION.value,
        "generator": PowerFlowMode.GENERATION.value,
        "load": PowerFlowMode.LOAD.value,
    }
    value = aliases.get(normalized, normalized)
    if value not in {mode.value for mode in PowerFlowMode}:
        return PowerFlowMode.LOAD.value
    return value


def _normalize_retention_mode(raw_retention_mode: str) -> str:
    value = str(raw_retention_mode or DEFAULT_RETENTION_MODE).strip().lower()
    if value not in _VALID_RETENTION_MODES:
        return DEFAULT_RETENTION_MODE
    return value


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
        (
            "_clothes_washer_",
            ApplianceProfile.WASHER.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        (
            "_laundry_washer_",
            ApplianceProfile.WASHER.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        (
            "_washing_machine_",
            ApplianceProfile.WASHER.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        ("_washer_", ApplianceProfile.WASHER.value, CircuitMode.SINGLE_PHASE.value),
        (
            "_clothes_dryer_",
            ApplianceProfile.DRYER.value,
            CircuitMode.DUAL_PHASE.value,
        ),
        (
            "_electric_dryer_",
            ApplianceProfile.DRYER.value,
            CircuitMode.DUAL_PHASE.value,
        ),
        (
            "_gas_dryer_",
            ApplianceProfile.DRYER.value,
            CircuitMode.DUAL_PHASE.value,
        ),
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
            self._pending_final_config = final_config
            if _should_show_setup_nilm_step(final_config):
                return await self.async_step_nilm()
            return await self.async_step_utility()

        return _assignment_review_form(self)

    async def async_step_nilm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Optionally choose known-load circuits for experimental NILM."""
        final_config = dict(
            getattr(
                self,
                "_pending_final_config",
                None,
            )
            or getattr(self, "_pending_config", None)
            or {}
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                final_config[CONF_KNOWN_LOAD_CIRCUITS] = (
                    _known_load_circuits_from_input(user_input, final_config)
                )
            except SetupValidationError as err:
                errors["base"] = err.error_key
            else:
                self._pending_final_config = final_config
                return await self.async_step_utility()

        return self.async_show_form(
            step_id="nilm",
            data_schema=_nilm_schema(
                final_config,
                final_config.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            ),
            errors=errors,
        )

    async def async_step_utility(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Optionally configure Utility / Opower comparison during setup."""
        final_config = dict(
            getattr(
                self,
                "_pending_final_config",
                None,
            )
            or getattr(self, "_pending_config", None)
            or {}
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                circuit_id, settings = _utility_settings_from_input(user_input)
            except SetupValidationError as err:
                errors["base"] = err.error_key
            else:
                if settings:
                    final_config.setdefault(CONF_UTILITY_COMPARISON_SETTINGS, {})[
                        circuit_id
                    ] = settings
                return self.async_create_entry(title=TITLE, data=final_config)

        return self.async_show_form(
            step_id="utility",
            data_schema=_utility_schema(
                final_config,
                utility_energy_entities=(
                    await _async_discover_utility_energy_entities(
                        getattr(self, "hass", None)
                    )
                ),
                utility_statistic_ids=(
                    await _async_discover_utility_statistic_ids(
                        getattr(self, "hass", None)
                    )
                ),
                measured_energy_entities=(
                    await _async_discover_energy_source_entities(
                        getattr(self, "hass", None)
                    )
                ),
            ),
            errors=errors,
        )


class CircuitSetupEnergyAnalyzerOptionsFlow(_OPTIONS_FLOW_BASE):
    """Options flow for CircuitSetup Energy Analyzer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending_config: dict[str, Any] | None = None
        self._advanced_circuit_id: str | None = None
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
                menu_options=[
                    "assign",
                    "sources",
                    "mains",
                    "nilm",
                    "utility",
                    "advanced",
                ],
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
                show_picker=True,
                update_existing=True,
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

    async def async_step_select_assignment(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select one existing assignment to edit."""
        groups = list(getattr(self, "_assignment_groups", []) or [])
        if user_input is None:
            if not groups:
                return await self.async_step_assign()
            return _assignment_picker_form(self)

        selected = str(user_input.get(FIELD_SELECTED_ASSIGNMENT) or "")
        for group in groups:
            if _assignment_group_value(group) == selected:
                self._assignment_groups = [group]
                self._assignment_index = 0
                self._reviewed_circuits = []
                self._assignment_update_existing = True
                self._assignment_selected_circuit_id = selected
                return _assignment_review_form(self)
        return _assignment_picker_form(
            self,
            errors={"base": ERROR_INVALID_CIRCUIT_ASSIGNMENTS},
        )

    async def async_step_mains(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit aggregate mains source sensors."""
        if user_input is not None:
            try:
                mains_source_entities = _strict_string_list(
                    user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
                    invalid_error_key="invalid_mains_source_entities",
                )
            except SetupValidationError as err:
                return await self._async_show_mains_form({"base": err.error_key})
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_MAINS_SOURCE_ENTITIES: mains_source_entities},
                ),
            )

        return await self._async_show_mains_form()

    async def async_step_nilm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit experimental NILM known-load settings."""
        config = _entry_config(self._config_entry)
        if user_input is not None:
            try:
                known_load_circuits = _known_load_circuits_from_input(
                    user_input,
                    config,
                )
            except SetupValidationError as err:
                return self.async_show_form(
                    step_id="nilm",
                    data_schema=_nilm_schema(
                        config,
                        _known_load_circuits_from_entry(self._config_entry),
                    ),
                    errors={"base": err.error_key},
                )
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_KNOWN_LOAD_CIRCUITS: known_load_circuits},
                ),
            )

        return self.async_show_form(
            step_id="nilm",
            data_schema=_nilm_schema(
                config,
                _known_load_circuits_from_entry(self._config_entry),
            ),
            errors={},
        )

    async def async_step_utility(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit Utility / Opower comparison settings."""
        if user_input is not None:
            try:
                circuit_id, settings = _utility_settings_from_input(user_input)
            except SetupValidationError as err:
                return await self._async_show_utility_form({"base": err.error_key})
            settings_by_circuit = _settings_map_for_entry(
                self._config_entry,
                CONF_UTILITY_COMPARISON_SETTINGS,
            )
            settings_by_circuit[circuit_id] = settings
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_UTILITY_COMPARISON_SETTINGS: settings_by_circuit},
                ),
            )

        return await self._async_show_utility_form()

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Choose a circuit for advanced settings."""
        if user_input is not None:
            return await self.async_step_select_advanced_circuit(user_input)

        return self.async_show_form(
            step_id="select_advanced_circuit",
            data_schema=_advanced_circuit_schema(_entry_config(self._config_entry)),
            errors={},
        )

    async def async_step_select_advanced_circuit(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select a circuit before editing advanced circuit settings."""
        if user_input is None:
            return await self.async_step_advanced()

        self._advanced_circuit_id = str(user_input.get(FIELD_CIRCUIT_ID) or "mains")
        return await self.async_step_advanced_settings()

    async def async_step_advanced_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit advanced per-circuit settings exposed through services."""
        circuit_id = self._advanced_circuit_id or "mains"
        if user_input is not None:
            try:
                settings = _advanced_settings_from_input(user_input)
            except SetupValidationError as err:
                return await self._async_show_advanced_settings_form(
                    circuit_id,
                    {"base": err.error_key},
                )
            settings_by_circuit = _settings_map_for_entry(
                self._config_entry,
                CONF_ADVANCED_SETTINGS,
            )
            settings_by_circuit[circuit_id] = settings
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_ADVANCED_SETTINGS: settings_by_circuit},
                ),
            )

        return await self._async_show_advanced_settings_form(circuit_id)

    async def _async_show_options_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        source_entity_ids = await _async_discover_energy_source_entities(
            getattr(self, "hass", None),
        )
        return self.async_show_form(
            step_id="sources",
            data_schema=_options_schema(self._config_entry, source_entity_ids),
            errors=errors or {},
        )

    async def _async_show_mains_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        source_entity_ids = await _async_discover_energy_source_entities(
            getattr(self, "hass", None),
        )
        return self.async_show_form(
            step_id="mains",
            data_schema=_mains_schema(self._config_entry, source_entity_ids),
            errors=errors or {},
        )

    async def _async_show_utility_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        config = _entry_config(self._config_entry)
        settings_by_circuit = _settings_map_for_entry(
            self._config_entry,
            CONF_UTILITY_COMPARISON_SETTINGS,
        )
        default_circuit = _default_circuit_id(
            _circuit_options_from_config(config, include_mains=True)
        )
        current_settings = dict(settings_by_circuit.get(default_circuit, {}))
        current_settings.setdefault(FIELD_CIRCUIT_ID, default_circuit)
        return self.async_show_form(
            step_id="utility",
            data_schema=_utility_schema(
                config,
                utility_energy_entities=(
                    await _async_discover_utility_energy_entities(
                        getattr(self, "hass", None)
                    )
                ),
                utility_statistic_ids=(
                    await _async_discover_utility_statistic_ids(
                        getattr(self, "hass", None)
                    )
                ),
                measured_energy_entities=(
                    await _async_discover_energy_source_entities(
                        getattr(self, "hass", None)
                    )
                ),
                current_settings=current_settings,
            ),
            errors=errors or {},
        )

    async def _async_show_advanced_settings_form(
        self,
        circuit_id: str,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        settings = _settings_map_for_entry(self._config_entry, CONF_ADVANCED_SETTINGS)
        return self.async_show_form(
            step_id="advanced_settings",
            data_schema=_advanced_settings_schema(settings.get(circuit_id, {})),
            errors=errors or {},
            description_placeholders={
                "circuit_id": circuit_id,
                "circuit_name": _circuit_label_from_config(
                    _entry_config(self._config_entry),
                    circuit_id,
                ),
            },
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
    selectable_source_entities = [
        *list(source_entity_ids or ()),
        *_DEMO_SOURCE_ENTITY_IDS,
        *_strict_string_list(
            source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
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
                CONF_SENSITIVITY,
                default=options.get(
                    CONF_SENSITIVITY,
                    data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
                ),
            ): _select_selector(sensitivity_options()),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=options.get(
                    CONF_RETENTION_MODE,
                    data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
                ),
            ): _select_selector(retention_mode_options()),
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
        CONF_KNOWN_LOAD_CIRCUITS: _strict_string_list(
            options.get(
                CONF_KNOWN_LOAD_CIRCUITS,
                data.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            ),
            invalid_error_key="invalid_known_load_circuits",
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


def _entry_value(
    config_entry: config_entries.ConfigEntry,
    key: str,
    default: Any,
) -> Any:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    return options.get(key, data.get(key, default))


def _entry_config(config_entry: config_entries.ConfigEntry) -> dict[str, Any]:
    data = getattr(config_entry, "data", {}) or {}
    options = getattr(config_entry, "options", {}) or {}
    return {**data, **options}


def _options_with_updates(
    config_entry: config_entries.ConfigEntry,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    options = dict(getattr(config_entry, "options", {}) or {})
    options.update(dict(updates))
    return options


def _settings_map_for_entry(
    config_entry: config_entries.ConfigEntry,
    key: str,
) -> dict[str, dict[str, Any]]:
    settings: dict[str, dict[str, Any]] = {}
    data = getattr(config_entry, "data", {}) or {}
    options = getattr(config_entry, "options", {}) or {}
    for source in (data.get(key, {}), options.get(key, {})):
        if not isinstance(source, Mapping):
            continue
        for circuit_id, value in source.items():
            if isinstance(value, Mapping):
                settings[str(circuit_id)] = dict(value)
    return settings


def _circuit_options_from_config(
    config: Mapping[str, Any],
    *,
    include_mains: bool = False,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for circuit in config.get(CONF_CIRCUITS, []) or []:
        if not isinstance(circuit, Mapping):
            continue
        circuit_id = str(circuit.get("circuit_id") or circuit.get("id") or "").strip()
        if not circuit_id or circuit_id in seen:
            continue
        name = str(circuit.get("name") or circuit_id)
        options.append({"value": circuit_id, "label": f"{name} ({circuit_id})"})
        seen.add(circuit_id)
    if include_mains and "mains" not in seen:
        options.insert(0, {"value": "mains", "label": "Mains NILM (mains)"})
    if not options:
        options.append({"value": "mains", "label": "Mains NILM (mains)"})
    return options


def _known_load_circuit_options_from_config(
    config: Mapping[str, Any],
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for circuit in config.get(CONF_CIRCUITS, []) or []:
        if not isinstance(circuit, Mapping):
            continue
        circuit_id = str(circuit.get("circuit_id") or circuit.get("id") or "").strip()
        if not circuit_id or circuit_id in seen:
            continue
        mode = str(circuit.get("mode") or "").strip()
        profile = str(circuit.get("appliance_profile") or "").strip()
        if (
            circuit_id == "mains"
            or mode == CircuitMode.MAINS_NILM.value
            or profile == ApplianceProfile.MAINS_NILM.value
        ):
            continue
        name = str(circuit.get("name") or circuit_id)
        options.append({"value": circuit_id, "label": f"{name} ({circuit_id})"})
        seen.add(circuit_id)
    return options


def _default_circuit_id(options: Iterable[Mapping[str, str]]) -> str:
    option_list = list(options)
    for option in option_list:
        if option.get("value") == "mains":
            return "mains"
    if option_list:
        return str(option_list[0].get("value") or "mains")
    return "mains"


def _circuit_label_from_config(config: Mapping[str, Any], circuit_id: str) -> str:
    for option in _circuit_options_from_config(config, include_mains=True):
        if option.get("value") == circuit_id:
            return str(option.get("label") or circuit_id)
    return circuit_id


def _first_or_empty(values: Iterable[Any]) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def _utility_settings_from_input(
    user_input: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    circuit_id = str(user_input.get(FIELD_CIRCUIT_ID) or "mains").strip() or "mains"
    if not bool(user_input.get(FIELD_ENABLE_UTILITY_COMPARISON, False)):
        return circuit_id, {}

    source_type = str(
        user_input.get(FIELD_UTILITY_SOURCE_TYPE, DEFAULT_UTILITY_SOURCE_TYPE)
    ).strip().lower()
    if source_type not in VALID_UTILITY_SOURCE_TYPES:
        raise SetupValidationError("invalid_utility_source_type")

    statistic_period = str(
        user_input.get(
            FIELD_UTILITY_STATISTIC_PERIOD,
            DEFAULT_UTILITY_STATISTIC_PERIOD,
        )
    ).strip().lower()
    if statistic_period not in VALID_UTILITY_STATISTIC_PERIODS:
        raise SetupValidationError("invalid_utility_statistic_period")

    settings: dict[str, Any] = {}
    utility_energy_entity = str(
        user_input.get(FIELD_UTILITY_ENERGY_ENTITY) or ""
    ).strip()
    utility_statistic_id = str(
        user_input.get(FIELD_UTILITY_STATISTIC_ID) or ""
    ).strip()
    if utility_energy_entity:
        settings[FIELD_UTILITY_ENERGY_ENTITY] = utility_energy_entity
    if utility_statistic_id:
        settings[FIELD_UTILITY_STATISTIC_ID] = utility_statistic_id
    settings[FIELD_UTILITY_SOURCE_TYPE] = source_type
    settings[FIELD_UTILITY_STATISTIC_PERIOD] = statistic_period
    measured_entities = _strict_string_list(
        user_input.get(FIELD_MEASURED_ENERGY_ENTITIES, []),
        invalid_error_key="invalid_measured_energy_entities",
    )
    if measured_entities:
        settings[FIELD_MEASURED_ENERGY_ENTITIES] = measured_entities
    settings[FIELD_TOLERANCE_PERCENT] = _nonnegative_float_from_input(
        user_input.get(FIELD_TOLERANCE_PERCENT),
        default=DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
    )
    return circuit_id, settings


def _known_load_circuits_from_input(
    user_input: Mapping[str, Any],
    config: Mapping[str, Any],
) -> list[str]:
    selected = _strict_string_list(
        user_input.get(CONF_KNOWN_LOAD_CIRCUITS, []),
        invalid_error_key="invalid_known_load_circuits",
    )
    allowed = {
        str(option["value"])
        for option in _known_load_circuit_options_from_config(config)
    }
    if any(circuit_id not in allowed for circuit_id in selected):
        raise SetupValidationError("invalid_known_load_circuits")
    return list(dict.fromkeys(selected))


def _known_load_circuits_from_entry(
    config_entry: config_entries.ConfigEntry,
) -> list[str]:
    return _strict_string_list(
        _entry_value(config_entry, CONF_KNOWN_LOAD_CIRCUITS, []),
        invalid_error_key="invalid_known_load_circuits",
    )


def _should_show_setup_nilm_step(config: Mapping[str, Any]) -> bool:
    return bool(config.get(CONF_ENABLE_EXPERIMENTAL_NILM, False))


def _advanced_settings_from_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    preset = str(user_input.get(FIELD_PRESET) or DEFAULT_SENSITIVITY).strip()
    if preset not in _SENSITIVITY_OPTIONS:
        raise SetupValidationError("invalid_sensitivity")
    settings[FIELD_PRESET] = preset

    _set_optional_int(settings, user_input, FIELD_WINDOW_DAYS)
    _set_optional_float(settings, user_input, FIELD_DAILY_SPIKE_RATIO)
    _set_optional_float(settings, user_input, FIELD_DAILY_GOAL_KWH)
    _set_optional_float(settings, user_input, FIELD_GOAL_ALERT_RATIO)
    _set_optional_int(settings, user_input, FIELD_MAX_ACTIVE_MINUTES)
    _set_optional_int(settings, user_input, FIELD_MAX_IDLE_MINUTES)
    _set_optional_int(settings, user_input, FIELD_CYCLE_START_DAY)
    _set_optional_float(settings, user_input, FIELD_BUDGET_KWH)
    _set_optional_float(settings, user_input, FIELD_BUDGET_ALERT_RATIO)
    _set_optional_int_as(
        settings,
        user_input,
        FIELD_BILLING_MIN_ELAPSED_DAYS,
        "min_elapsed_days",
    )
    _set_optional_float(settings, user_input, FIELD_DEFAULT_RATE_PER_KWH)
    _set_optional_float(settings, user_input, FIELD_TOU_RATE_PER_KWH)
    _set_optional_string(settings, user_input, FIELD_TOU_START)
    _set_optional_string(settings, user_input, FIELD_TOU_END)
    _set_optional_string(settings, user_input, FIELD_TOU_WEEKDAYS)
    _set_optional_string(settings, user_input, FIELD_TOU_NAME)
    _set_optional_int(settings, user_input, FIELD_WINDOW_MINUTES)
    _set_optional_float(settings, user_input, FIELD_DEMAND_LIMIT_W)
    _set_optional_float(settings, user_input, FIELD_BREAKER_AMPS)
    _set_optional_float(settings, user_input, FIELD_WARNING_RATIO)
    _set_optional_int(settings, user_input, FIELD_WINDOW_HOURS)
    _set_optional_float(settings, user_input, FIELD_STANDBY_THRESHOLD_W)
    _set_optional_float(settings, user_input, FIELD_ALWAYS_ON_ALERT_W)
    _set_optional_int_as(
        settings,
        user_input,
        FIELD_STANDBY_MIN_SAMPLES,
        "min_samples",
    )
    _set_optional_float(settings, user_input, FIELD_LEG_IMBALANCE_WARNING_RATIO)
    _set_optional_float(settings, user_input, FIELD_LEG_IMBALANCE_MIN_TOTAL_POWER_W)
    _set_optional_float(settings, user_input, FIELD_APPARENT_POWER_TOLERANCE_PERCENT)
    _set_optional_float(settings, user_input, FIELD_POWER_FACTOR_TOLERANCE)
    _set_optional_float(settings, user_input, FIELD_MINIMUM_APPARENT_POWER_VA)
    _set_optional_float(settings, user_input, FIELD_BALANCE_NEGATIVE_TOLERANCE_W)
    _set_optional_float(settings, user_input, FIELD_SOLAR_EXPORT_TOLERANCE_W)
    _set_optional_float(settings, user_input, FIELD_SOLAR_SURPLUS_THRESHOLD_W)
    _set_optional_float(settings, user_input, FIELD_HIGH_SOLAR_SURPLUS_THRESHOLD_W)
    _set_optional_float(settings, user_input, FIELD_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W)
    return settings


def _set_optional_string(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    key: str,
) -> None:
    value = user_input.get(key)
    if value is None:
        return
    text = str(value).strip()
    if text:
        settings[key] = text


def _set_optional_int(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    key: str,
) -> None:
    value = user_input.get(key)
    if value is None or value == "":
        return
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise SetupValidationError("invalid_advanced_settings") from None
    if parsed >= 0:
        settings[key] = parsed


def _set_optional_int_as(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    input_key: str,
    output_key: str,
) -> None:
    before = set(settings)
    _set_optional_int(settings, user_input, input_key)
    if input_key in settings and input_key not in before:
        settings[output_key] = settings.pop(input_key)


def _set_optional_float(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    key: str,
) -> None:
    value = user_input.get(key)
    if value is None or value == "":
        return
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise SetupValidationError("invalid_advanced_settings") from None
    if parsed >= 0.0:
        settings[key] = parsed


def _nonnegative_float_from_input(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


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


async def _async_discover_utility_energy_entities(hass: Any) -> list[str]:
    if hass is None:
        return []
    try:
        return await async_discover_utility_energy_entities(hass)
    except Exception:
        return []


async def _async_discover_utility_statistic_ids(hass: Any) -> list[str]:
    if hass is None:
        return []
    try:
        return await async_discover_utility_statistic_ids(hass)
    except Exception:
        return []
