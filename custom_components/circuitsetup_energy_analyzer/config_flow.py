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

try:
    from homeassistant.data_entry_flow import section
except (ImportError, ModuleNotFoundError):

    def section(
        schema: Any,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        return schema

from .balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUIT_ASSIGNMENTS,
    CONF_CIRCUITS,
    CONF_DASHBOARD_LAYOUT,
    CONF_DEMO_SOURCE_BUNDLE_ENABLED,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_EXPECTS_WATER_FLOW,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_RAIN_RESPONSE_WINDOW_MINUTES,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_DEVICES,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
    DEFAULT_DASHBOARD_LAYOUT,
    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
    DEFAULT_ENTITY_DETAIL_LEVEL,
    DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
    DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
    DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from .dashboard import normalize_dashboard_layout
from .demo import DEMO_SOURCE_ENTITY_IDS as _DEMO_SOURCE_ENTITY_IDS
from .discovery import (
    ENERGY_SOURCE_DEVICE_CLASSES,
    async_discover_energy_source_entities,
    async_discover_energy_source_entities_for_devices,
    async_discover_sensors,
    async_discover_utility_energy_entities,
    async_discover_utility_statistic_ids,
    infer_sensor_role,
)
from .entity import (
    apply_entity_profile_to_registry,
    normalize_entity_detail_level,
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
from .recommendation_guidance import (
    is_hidden_recommendation_evidence_key,
    recommendation_setting_default_value,
    recommendation_setting_expected_effect,
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
from .ux import SENSITIVITY_LABELS, normalize_sensitivity

TITLE = "CircuitSetup Energy Analyzer"
ERROR_NO_SOURCE_ENTITIES = "no_source_entities"
ERROR_INVALID_SOURCE_ENTITIES = "invalid_source_entities"
ERROR_INVALID_CIRCUIT_ASSIGNMENTS = "invalid_circuit_assignments"
_VALID_RETENTION_MODES = {mode.value for mode in RetentionMode}
_SENSITIVITY_OPTIONS = ("quiet", "balanced", "sensitive")
_SENSITIVITY_LABELS = SENSITIVITY_LABELS
_DASHBOARD_LAYOUT_OPTIONS = (
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUT_EXPERT,
)
_DASHBOARD_LAYOUT_LABELS = {
    DASHBOARD_LAYOUT_SIMPLE: "Simple",
    DASHBOARD_LAYOUT_STANDARD: "Standard",
    DASHBOARD_LAYOUT_EXPERT: "Expert",
}
FIELD_INCLUDE_CIRCUIT = "include_circuit"
FIELD_REMOVE_FROM_ANALYSIS = "remove_from_analysis"
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
_SOURCE_METRIC_SUFFIXES = (
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
    "_l1",
    "_l2",
)
_ANALYZER_SOURCE_ENTITY_PREFIXES = (
    "circuitsetup_energy_analyzer_",
    "cs_energy_analyzer_",
)
_PRESERVED_ANALYZER_SOURCE_ENTITY_PREFIXES = ("cs_energy_analyzer_demo_",)
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
FIELD_SETTING_SUGGESTION_IDS = "setting_suggestion_ids"
FIELD_RECOMMENDATION_ID = "recommendation_id"
FIELD_RECOMMENDATION_ACTION = "recommendation_action"
FIELD_APPLY_ENTITY_DETAIL_PROFILE = "apply_entity_detail_profile"
FIELD_RESET_ADVANCED_SETTINGS_TO_DEFAULTS = "reset_advanced_settings_to_defaults"
RECOMMENDATION_ACTION_APPLY = "apply"
RECOMMENDATION_ACTION_DENY = "deny"
RECOMMENDATION_ACTION_DISMISS = "dismiss"
ERROR_INVALID_RECOMMENDATION = "invalid_recommendation"
ERROR_RECOMMENDATIONS_NOT_LOADED = "recommendations_not_loaded"
SECTION_ANALYSIS_SETTINGS = "analysis_settings"
SECTION_ENERGY_SETTINGS = "energy_settings"
SECTION_ACTIVITY_SETTINGS = "activity_settings"
SECTION_BILLING_COST_SETTINGS = "billing_cost_settings"
SECTION_DEMAND_CAPACITY_SETTINGS = "demand_capacity_settings"
SECTION_STANDBY_SETTINGS = "standby_settings"
SECTION_DUAL_PHASE_SETTINGS = "dual_phase_settings"
SECTION_POWER_QUALITY_SETTINGS = "power_quality_settings"
SECTION_MAINS_BALANCE_SETTINGS = "mains_balance_settings"
SECTION_SOLAR_FLOW_SETTINGS = "solar_flow_settings"
SECTION_WATER_CONTEXT_SETTINGS = "water_context_settings"
_ADVANCED_SECTION_RESET_FIELDS = {
    SECTION_ENERGY_SETTINGS: "reset_energy_settings_to_defaults",
    SECTION_ACTIVITY_SETTINGS: "reset_activity_settings_to_defaults",
    SECTION_BILLING_COST_SETTINGS: "reset_billing_cost_settings_to_defaults",
    SECTION_DEMAND_CAPACITY_SETTINGS: "reset_demand_capacity_settings_to_defaults",
    SECTION_STANDBY_SETTINGS: "reset_standby_settings_to_defaults",
    SECTION_WATER_CONTEXT_SETTINGS: "reset_water_context_settings_to_defaults",
    SECTION_DUAL_PHASE_SETTINGS: "reset_dual_phase_settings_to_defaults",
    SECTION_POWER_QUALITY_SETTINGS: "reset_power_quality_settings_to_defaults",
    SECTION_MAINS_BALANCE_SETTINGS: "reset_mains_balance_settings_to_defaults",
    SECTION_SOLAR_FLOW_SETTINGS: "reset_solar_flow_settings_to_defaults",
}
_ADVANCED_RESET_SETTING_KEYS = {
    "reset_analysis_settings_to_defaults": (FIELD_PRESET,),
    "reset_energy_settings_to_defaults": (
        FIELD_WINDOW_DAYS,
        FIELD_DAILY_SPIKE_RATIO,
        FIELD_DAILY_GOAL_KWH,
        FIELD_GOAL_ALERT_RATIO,
    ),
    "reset_activity_settings_to_defaults": (
        FIELD_MAX_ACTIVE_MINUTES,
        FIELD_MAX_IDLE_MINUTES,
    ),
    "reset_billing_cost_settings_to_defaults": (
        FIELD_CYCLE_START_DAY,
        FIELD_BUDGET_KWH,
        FIELD_BUDGET_ALERT_RATIO,
        "min_elapsed_days",
        FIELD_DEFAULT_RATE_PER_KWH,
        FIELD_TOU_RATE_PER_KWH,
        FIELD_TOU_START,
        FIELD_TOU_END,
        FIELD_TOU_WEEKDAYS,
        FIELD_TOU_NAME,
    ),
    "reset_demand_capacity_settings_to_defaults": (
        FIELD_WINDOW_MINUTES,
        FIELD_DEMAND_LIMIT_W,
        FIELD_BREAKER_AMPS,
        FIELD_WARNING_RATIO,
    ),
    "reset_standby_settings_to_defaults": (
        FIELD_WINDOW_HOURS,
        FIELD_STANDBY_THRESHOLD_W,
        FIELD_ALWAYS_ON_ALERT_W,
        "min_samples",
    ),
    "reset_water_context_settings_to_defaults": (
        CONF_RAIN_PUMP_CORRELATION_ENABLED,
        CONF_RAIN_RESPONSE_WINDOW_MINUTES,
        CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
        CONF_WATER_FLOW_CORRELATION_ENABLED,
        CONF_LINKED_FLOW_SENSOR_ENTITIES,
        CONF_EXPECTS_WATER_FLOW,
        CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
    ),
    "reset_dual_phase_settings_to_defaults": (
        FIELD_LEG_IMBALANCE_WARNING_RATIO,
        FIELD_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    ),
    "reset_power_quality_settings_to_defaults": (
        FIELD_APPARENT_POWER_TOLERANCE_PERCENT,
        FIELD_POWER_FACTOR_TOLERANCE,
        FIELD_MINIMUM_APPARENT_POWER_VA,
    ),
    "reset_mains_balance_settings_to_defaults": (FIELD_BALANCE_NEGATIVE_TOLERANCE_W,),
    "reset_solar_flow_settings_to_defaults": (
        FIELD_SOLAR_EXPORT_TOLERANCE_W,
        FIELD_SOLAR_SURPLUS_THRESHOLD_W,
        FIELD_HIGH_SOLAR_SURPLUS_THRESHOLD_W,
        FIELD_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    ),
}
_ADVANCED_SECTION_KEYS = {
    SECTION_ANALYSIS_SETTINGS,
    SECTION_ENERGY_SETTINGS,
    SECTION_ACTIVITY_SETTINGS,
    SECTION_BILLING_COST_SETTINGS,
    SECTION_DEMAND_CAPACITY_SETTINGS,
    SECTION_STANDBY_SETTINGS,
    SECTION_DUAL_PHASE_SETTINGS,
    SECTION_POWER_QUALITY_SETTINGS,
    SECTION_MAINS_BALANCE_SETTINGS,
    SECTION_SOLAR_FLOW_SETTINGS,
    SECTION_WATER_CONTEXT_SETTINGS,
}
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
    ApplianceProfile.MICROWAVE.value,
    ApplianceProfile.WASHER.value,
    ApplianceProfile.DRYER.value,
    ApplianceProfile.POOL_PUMP.value,
    ApplianceProfile.WATER_PUMP.value,
    ApplianceProfile.WELL_PUMP.value,
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
_RECOMMENDATION_ACTION_OPTIONS = (
    {"value": RECOMMENDATION_ACTION_APPLY, "label": "Apply Suggestion"},
    {"value": RECOMMENDATION_ACTION_DENY, "label": "Deny Suggestion"},
    {"value": RECOMMENDATION_ACTION_DISMISS, "label": "Dismiss For Now"},
)
_CIRCUIT_MODE_LABELS = {
    CircuitMode.SINGLE_PHASE.value: "Single Phase",
    CircuitMode.DUAL_PHASE.value: "Dual Phase",
    CircuitMode.MIXED.value: "Mixed",
    CircuitMode.MAINS_NILM.value: "Mains NILM",
}
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


_DEMO_SOURCE_ENTITY_PREFIX = "sensor.cs_energy_analyzer_demo_"
_DEMO_CURRENT_SOURCE_ENTITY_IDS = set(_DEMO_SOURCE_ENTITY_IDS)
_DEMO_SPLIT_SOURCE_CIRCUITS = {"hvac", "water_heater", "dryer", "car_charger"}
_DEMO_SOURCE_METRIC_ALIASES = {
    "power": "active_power",
    "real_power": "active_power",
}
_DEMO_SPLIT_SOURCE_METRICS = {
    "energy",
    "active_power",
    "current",
    "power_factor",
    "reactive_power",
    "apparent_power",
}


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


def _normalize_demo_source_entity_ids(entity_ids: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for entity_id in entity_ids:
        replacements = _current_demo_source_entity_ids(entity_id)
        if replacements:
            normalized.extend(replacements)
        elif not str(entity_id).startswith(_DEMO_SOURCE_ENTITY_PREFIX):
            normalized.append(str(entity_id))
    return list(dict.fromkeys(normalized))


def _resolve_discovered_demo_source_entity_ids(
    entity_ids: Iterable[str],
    discovered_entity_ids: Iterable[str] | None,
) -> list[str]:
    discovered_lookup: dict[str, list[str]] = {}
    for entity_id in discovered_entity_ids or ():
        if not _is_demo_source_entity_id(str(entity_id)):
            continue
        discovered_lookup.setdefault(
            _demo_unsuffixed_source_entity_id(str(entity_id)),
            [],
        ).append(str(entity_id))

    resolved: list[str] = []
    for entity_id in entity_ids:
        entity_id = str(entity_id)
        if not _is_demo_source_entity_id(entity_id):
            resolved.append(entity_id)
            continue
        unsuffixed_id = _demo_unsuffixed_source_entity_id(entity_id)
        discovered_matches = discovered_lookup.get(unsuffixed_id, ())
        if entity_id in discovered_matches or not discovered_matches:
            resolved.append(entity_id)
        elif len(discovered_matches) == 1:
            resolved.append(discovered_matches[0])
        else:
            resolved.append(entity_id)
    return list(dict.fromkeys(resolved))


def _is_demo_source_entity_id(entity_id: str) -> bool:
    return str(entity_id).startswith(_DEMO_SOURCE_ENTITY_PREFIX)


def _with_demo_source_bundle(entity_ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*entity_ids, *_DEMO_SOURCE_ENTITY_IDS]))


def _without_demo_source_bundle(entity_ids: Iterable[str]) -> list[str]:
    return [
        entity_id
        for entity_id in entity_ids
        if not _is_demo_source_entity_id(entity_id)
    ]


def _has_demo_source_entity_ids(*entity_id_groups: Iterable[str]) -> bool:
    return any(
        _is_demo_source_entity_id(entity_id)
        for entity_ids in entity_id_groups
        for entity_id in entity_ids
    )


def _demo_source_entity_ids_from_circuits(
    circuits: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    return tuple(
        str(sensor.get("entity_id"))
        for circuit in circuits
        if isinstance(circuit, Mapping)
        for sensor in circuit.get("sensors", ())
        if isinstance(sensor, Mapping)
        and sensor.get("entity_id")
        and _is_demo_source_entity_id(str(sensor.get("entity_id")))
    )


def _demo_source_bundle_enabled_for_entry_values(
    options: Mapping[str, Any],
    data: Mapping[str, Any],
    *,
    source_entities: Iterable[str] = (),
    extra_source_entities: Iterable[str] = (),
    mains_source_entities: Iterable[str] = (),
) -> bool:
    explicitly_enabled = False
    if CONF_DEMO_SOURCE_BUNDLE_ENABLED in options:
        explicitly_enabled = bool(options[CONF_DEMO_SOURCE_BUNDLE_ENABLED])
    elif CONF_DEMO_SOURCE_BUNDLE_ENABLED in data:
        explicitly_enabled = bool(data[CONF_DEMO_SOURCE_BUNDLE_ENABLED])
    circuits = options.get(CONF_CIRCUITS, data.get(CONF_CIRCUITS, []))
    return explicitly_enabled or _has_demo_source_entity_ids(
        source_entities,
        extra_source_entities,
        mains_source_entities,
        _demo_source_entity_ids_from_circuits(circuits),
    )


def _current_demo_source_entity_ids(entity_id: str) -> tuple[str, ...]:
    entity_id = str(entity_id).strip()
    if entity_id in _DEMO_CURRENT_SOURCE_ENTITY_IDS:
        return (entity_id,)
    if not entity_id.startswith(_DEMO_SOURCE_ENTITY_PREFIX):
        return ()
    if _demo_unsuffixed_source_entity_id(entity_id) in _DEMO_CURRENT_SOURCE_ENTITY_IDS:
        return (entity_id,)

    object_id = entity_id.removeprefix(_DEMO_SOURCE_ENTITY_PREFIX)
    if replacement := _demo_power_alias_source_entity_id(object_id):
        return (replacement,)
    if replacement := _demo_split_source_entity_ids(object_id):
        return replacement
    if replacement := _demo_voltage_source_entity_ids(object_id):
        return replacement
    return ()


def _demo_unsuffixed_source_entity_id(entity_id: str) -> str:
    return re.sub(r"_\d+$", "", entity_id)


def _demo_power_alias_source_entity_id(object_id: str) -> str:
    for suffix, replacement_suffix in _DEMO_SOURCE_METRIC_ALIASES.items():
        if not object_id.endswith(f"_{suffix}"):
            continue
        replacement = (
            f"{_DEMO_SOURCE_ENTITY_PREFIX}"
            f"{object_id[: -len(suffix)]}{replacement_suffix}"
        )
        if replacement in _DEMO_CURRENT_SOURCE_ENTITY_IDS:
            return replacement
    return ""


def _demo_split_source_entity_ids(object_id: str) -> tuple[str, ...]:
    for circuit in _DEMO_SPLIT_SOURCE_CIRCUITS:
        prefix = f"{circuit}_"
        if not object_id.startswith(prefix):
            continue
        metric = object_id.removeprefix(prefix)
        metric = _DEMO_SOURCE_METRIC_ALIASES.get(metric, metric)
        if metric not in _DEMO_SPLIT_SOURCE_METRICS:
            return ()
        replacements = tuple(
            f"{_DEMO_SOURCE_ENTITY_PREFIX}{circuit}_{leg}_{metric}"
            for leg in ("l1", "l2")
        )
        return tuple(
            replacement
            for replacement in replacements
            if replacement in _DEMO_CURRENT_SOURCE_ENTITY_IDS
        )
    return ()


def _demo_voltage_source_entity_ids(object_id: str) -> tuple[str, ...]:
    if not object_id.endswith("_voltage"):
        return ()
    circuit = object_id.removesuffix("_voltage")
    replacements = (
        "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
        "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
    )
    if circuit in _DEMO_SPLIT_SOURCE_CIRCUITS:
        return replacements
    return replacements[:1]


def validate_setup_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize setup data without requiring Home Assistant."""
    demo_source_bundle_enabled = bool(
        user_input.get(CONF_DEMO_SOURCE_BUNDLE_ENABLED, False)
    )
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    extra_source_entities = _normalize_demo_source_entity_ids(extra_source_entities)
    if demo_source_bundle_enabled:
        extra_source_entities = _with_demo_source_bundle(extra_source_entities)
    legacy_source_entities = _strict_string_list(
        user_input.get(CONF_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    legacy_source_entities = _normalize_demo_source_entity_ids(legacy_source_entities)
    source_entities = list(
        dict.fromkeys([*extra_source_entities, *legacy_source_entities])
    )
    if demo_source_bundle_enabled:
        source_entities = _with_demo_source_bundle(source_entities)
    if not source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    retention_mode = _validate_retention_mode(user_input)

    outdoor_temperature_entity = str(
        user_input.get(CONF_OUTDOOR_TEMPERATURE_ENTITY) or ""
    ).strip()
    rain_sensor_entity = str(user_input.get(CONF_RAIN_SENSOR_ENTITY) or "").strip()
    rain_intensity_entity = str(
        user_input.get(CONF_RAIN_INTENSITY_ENTITY) or ""
    ).strip()
    water_flow_sensor_entities = _strict_string_list(
        user_input.get(CONF_WATER_FLOW_SENSOR_ENTITIES, []),
        invalid_error_key="invalid_water_flow_sensor_entities",
    )
    water_flow_sensor_entities = [
        entity_id.strip()
        for entity_id in water_flow_sensor_entities
        if entity_id.strip()
    ]

    validated = {
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: source_entities,
        CONF_DEMO_SOURCE_BUNDLE_ENABLED: demo_source_bundle_enabled,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_ENTITY_DETAIL_LEVEL: normalize_entity_detail_level(
            user_input.get(CONF_ENTITY_DETAIL_LEVEL, DEFAULT_ENTITY_DETAIL_LEVEL)
        ),
        CONF_MAINS_SOURCE_ENTITIES: _normalize_demo_source_entity_ids(
            _strict_string_list(
                user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
                invalid_error_key="invalid_mains_source_entities",
            )
        ),
        CONF_SENSITIVITY: normalize_sensitivity(
            user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)
        ),
        CONF_RETENTION_MODE: retention_mode,
    }
    if outdoor_temperature_entity:
        validated[CONF_OUTDOOR_TEMPERATURE_ENTITY] = outdoor_temperature_entity
    if rain_sensor_entity:
        validated[CONF_RAIN_SENSOR_ENTITY] = rain_sensor_entity
    if rain_intensity_entity:
        validated[CONF_RAIN_INTENSITY_ENTITY] = rain_intensity_entity
    if water_flow_sensor_entities:
        validated[CONF_WATER_FLOW_SENSOR_ENTITIES] = water_flow_sensor_entities
    return validated


def validate_options_input(
    user_input: Mapping[str, Any],
    *,
    remove_demo_source_bundle: bool = False,
    allow_empty_sources: bool = False,
) -> dict[str, Any]:
    """Validate and normalize options flow data without requiring Home Assistant."""
    demo_source_bundle_enabled = bool(
        user_input.get(CONF_DEMO_SOURCE_BUNDLE_ENABLED, False)
    )
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    extra_source_entities = _normalize_demo_source_entity_ids(extra_source_entities)
    if demo_source_bundle_enabled:
        extra_source_entities = _with_demo_source_bundle(extra_source_entities)
    elif remove_demo_source_bundle:
        extra_source_entities = _without_demo_source_bundle(extra_source_entities)
    outdoor_temperature_entity = str(
        user_input.get(CONF_OUTDOOR_TEMPERATURE_ENTITY) or ""
    ).strip()
    rain_sensor_entity = str(user_input.get(CONF_RAIN_SENSOR_ENTITY) or "").strip()
    rain_intensity_entity = str(
        user_input.get(CONF_RAIN_INTENSITY_ENTITY) or ""
    ).strip()
    water_flow_sensor_entities = _strict_string_list(
        user_input.get(CONF_WATER_FLOW_SENSOR_ENTITIES, []),
        invalid_error_key="invalid_water_flow_sensor_entities",
    )
    water_flow_sensor_entities = [
        entity_id.strip()
        for entity_id in water_flow_sensor_entities
        if entity_id.strip()
    ]
    validated = {
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_DEMO_SOURCE_BUNDLE_ENABLED: demo_source_bundle_enabled,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_ENTITY_DETAIL_LEVEL: normalize_entity_detail_level(
            user_input.get(CONF_ENTITY_DETAIL_LEVEL, DEFAULT_ENTITY_DETAIL_LEVEL)
        ),
        CONF_MAINS_SOURCE_ENTITIES: _normalize_demo_source_entity_ids(
            _strict_string_list(
                user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
                invalid_error_key="invalid_mains_source_entities",
            )
        ),
        CONF_SENSITIVITY: normalize_sensitivity(
            user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)
        ),
        CONF_RETENTION_MODE: _validate_retention_mode(user_input),
    }
    validated[CONF_OUTDOOR_TEMPERATURE_ENTITY] = outdoor_temperature_entity
    validated[CONF_RAIN_SENSOR_ENTITY] = rain_sensor_entity
    validated[CONF_RAIN_INTENSITY_ENTITY] = rain_intensity_entity
    if water_flow_sensor_entities:
        validated[CONF_WATER_FLOW_SENSOR_ENTITIES] = water_flow_sensor_entities
    merged_source_entities = list(extra_source_entities)
    if CONF_SOURCE_ENTITIES in user_input:
        source_entities = _strict_string_list(
            user_input.get(CONF_SOURCE_ENTITIES),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
        source_entities = _normalize_demo_source_entity_ids(source_entities)
        if demo_source_bundle_enabled:
            source_entities = _with_demo_source_bundle(source_entities)
        elif remove_demo_source_bundle:
            source_entities = _without_demo_source_bundle(source_entities)
        merged_source_entities.extend(source_entities)
    merged_source_entities = list(dict.fromkeys(merged_source_entities))
    if demo_source_bundle_enabled:
        merged_source_entities = _with_demo_source_bundle(merged_source_entities)
    elif remove_demo_source_bundle:
        merged_source_entities = _without_demo_source_bundle(merged_source_entities)
    if not merged_source_entities and not allow_empty_sources:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)
    validated[CONF_SOURCE_ENTITIES] = merged_source_entities
    if remove_demo_source_bundle:
        validated[CONF_MAINS_SOURCE_ENTITIES] = _without_demo_source_bundle(
            validated[CONF_MAINS_SOURCE_ENTITIES]
        )
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


def _time_selector() -> Any:
    return _selector({"time": {}}, str)


def _weekday_select_selector() -> Any:
    return _multi_select_selector(
        [
            {"value": "0", "label": "Monday"},
            {"value": "1", "label": "Tuesday"},
            {"value": "2", "label": "Wednesday"},
            {"value": "3", "label": "Thursday"},
            {"value": "4", "label": "Friday"},
            {"value": "5", "label": "Saturday"},
            {"value": "6", "label": "Sunday"},
        ]
    )


def _optional_entity_marker(key: str, default: Any = None) -> vol.Optional:
    """Return an optional selector marker without invalid blank entity defaults."""
    value = str(default or "").strip()
    if value:
        return vol.Optional(key, default=value)
    return vol.Optional(key)


def _temperature_entity_selector() -> Any:
    return _selector(
        {
            "entity": {
                "multiple": False,
                "filter": [{"domain": "sensor", "device_class": "temperature"}],
            }
        },
        str,
    )


def _binary_sensor_entity_selector(*, multiple: bool = False) -> Any:
    return _selector(
        {
            "entity": {
                "multiple": multiple,
                "filter": [{"domain": "binary_sensor"}],
            }
        },
        str,
    )


def _water_flow_entity_selector_config(*, multiple: bool = True) -> dict[str, Any]:
    return {
        "entity": {
            "multiple": multiple,
            "filter": [
                {"domain": "binary_sensor"},
                {"domain": "sensor"},
            ],
        }
    }


def _water_flow_entity_selector(*, multiple: bool = True) -> Any:
    return _selector(_water_flow_entity_selector_config(multiple=multiple), str)


def _single_sensor_entity_selector() -> Any:
    return _selector(
        {
            "entity": {
                "multiple": False,
                "filter": [{"domain": "sensor"}],
            }
        },
        str,
    )


def _checklist_select_selector(options: Iterable[Mapping[str, str]]) -> Any:
    return _selector(
        {
            "select": {
                "multiple": True,
                "mode": "list",
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


def dashboard_layout_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": _DASHBOARD_LAYOUT_LABELS[value]}
        for value in _DASHBOARD_LAYOUT_OPTIONS
    ]


def retention_mode_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": _RETENTION_MODE_LABELS[value]}
        for value in _RETENTION_MODE_OPTIONS
    ]


def entity_detail_level_options() -> list[dict[str, str]]:
    return [
        {
            "value": ENTITY_DETAIL_SIMPLE,
            "label": "Simple",
        },
        {
            "value": ENTITY_DETAIL_STANDARD,
            "label": "Standard",
        },
        {
            "value": ENTITY_DETAIL_EXPERT,
            "label": "Expert",
        },
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
    *selected_entity_ids: Iterable[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            [
                *list(source_entity_ids or ()),
                *_DEMO_SOURCE_ENTITY_IDS,
                *[
                    entity_id
                    for values in selected_entity_ids
                    for entity_id in _strict_string_list(
                        values,
                        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
                    )
                ],
            ]
        )
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
                CONF_DEMO_SOURCE_BUNDLE_ENABLED,
                default=False,
            ): bool,
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
            _optional_entity_marker(
                CONF_OUTDOOR_TEMPERATURE_ENTITY,
            ): _temperature_entity_selector(),
            _optional_entity_marker(
                CONF_RAIN_SENSOR_ENTITY,
            ): _binary_sensor_entity_selector(),
            _optional_entity_marker(
                CONF_RAIN_INTENSITY_ENTITY,
            ): _single_sensor_entity_selector(),
            vol.Optional(
                CONF_WATER_FLOW_SENSOR_ENTITIES,
                default=[],
            ): _water_flow_entity_selector(multiple=True),
            vol.Optional(
                CONF_SENSITIVITY,
                default=normalize_sensitivity(DEFAULT_SENSITIVITY),
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
    schema: dict[Any, Any] = {
        vol.Required(
            FIELD_INCLUDE_CIRCUIT,
            default=True,
        ): bool,
    }
    if bool(group.get("allow_remove_from_analysis", False)):
        schema[
            vol.Optional(
                FIELD_REMOVE_FROM_ANALYSIS,
                default=False,
            )
        ] = bool
    schema.update(
        {
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
                FIELD_CIRCUIT_RETENTION_MODE,
                default=str(group.get("retention_mode") or DEFAULT_RETENTION_MODE),
            ): _select_selector(retention_mode_options()),
        }
    )
    return vol.Schema(schema)


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
    mains_source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            _entry_value(
                config_entry,
                CONF_MAINS_SOURCE_ENTITIES,
                [],
            ),
            invalid_error_key="invalid_mains_source_entities",
        )
    )
    mains_source_entities = _resolve_discovered_demo_source_entity_ids(
        mains_source_entities,
        source_entity_ids,
    )
    source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            _entry_value(config_entry, CONF_SOURCE_ENTITIES, []),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
    )
    source_entities = _resolve_discovered_demo_source_entity_ids(
        source_entities,
        source_entity_ids,
    )
    selectable_source_entities = _selectable_source_entity_ids(
        source_entity_ids,
        source_entities,
        mains_source_entities,
    )
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


def _recommendations_schema(
    recommendations: Iterable[Any],
) -> Any:
    recommendation_options = _recommendation_select_options(recommendations)
    if not recommendation_options:
        return vol.Schema({})
    return vol.Schema(
        {
            vol.Required(
                FIELD_SETTING_SUGGESTION_IDS,
                default=[],
            ): _checklist_select_selector(recommendation_options),
            vol.Required(
                FIELD_RECOMMENDATION_ACTION,
                default=RECOMMENDATION_ACTION_APPLY,
            ): _select_selector(_recommendation_action_options()),
        }
    )


def _advanced_settings_schema(
    current_settings: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> Any:
    settings = dict(current_settings or {})
    circuit_context = _advanced_circuit_context(context)
    schema: dict[Any, Any] = {
        vol.Optional(FIELD_RESET_ADVANCED_SETTINGS_TO_DEFAULTS, default=False): bool
    }

    _add_advanced_section(
        schema,
        SECTION_ANALYSIS_SETTINGS,
        {
            vol.Optional(
                FIELD_PRESET,
                default=normalize_sensitivity(
                    settings.get(FIELD_PRESET, DEFAULT_SENSITIVITY)
                ),
            ): _select_selector(sensitivity_options()),
        },
        collapsed=False,
    )
    if _advanced_show_energy_settings(circuit_context):
        _add_advanced_section(schema, SECTION_ENERGY_SETTINGS, _energy_fields(settings))
    if _advanced_show_activity_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_ACTIVITY_SETTINGS,
            _activity_fields(settings),
        )
    if _advanced_show_billing_cost_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_BILLING_COST_SETTINGS,
            _billing_cost_fields(settings),
        )
    if _advanced_show_demand_capacity_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_DEMAND_CAPACITY_SETTINGS,
            _demand_capacity_fields(settings),
        )
    if _advanced_show_standby_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_STANDBY_SETTINGS,
            _standby_fields(settings),
        )
    if _advanced_show_water_context_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_WATER_CONTEXT_SETTINGS,
            _water_context_fields(settings, circuit_context),
        )
    if _advanced_show_dual_phase_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_DUAL_PHASE_SETTINGS,
            _dual_phase_fields(settings),
        )
    _add_advanced_section(
        schema,
        SECTION_POWER_QUALITY_SETTINGS,
        _power_quality_fields(settings),
    )
    if _advanced_show_mains_settings(circuit_context):
        _add_advanced_section(
            schema,
            SECTION_MAINS_BALANCE_SETTINGS,
            _mains_balance_fields(settings),
        )
        _add_advanced_section(
            schema,
            SECTION_SOLAR_FLOW_SETTINGS,
            _solar_flow_fields(settings),
        )

    return vol.Schema(schema)


def _add_advanced_section(
    schema: dict[Any, Any],
    key: str,
    fields: Mapping[Any, Any],
    *,
    collapsed: bool = True,
) -> None:
    if not fields:
        return
    section_fields: dict[Any, Any] = {}
    if reset_field := _ADVANCED_SECTION_RESET_FIELDS.get(key):
        section_fields[vol.Optional(reset_field, default=False)] = bool
    section_fields.update(fields)
    schema[vol.Optional(key)] = section(
        vol.Schema(section_fields),
        {"collapsed": collapsed},
    )


def _energy_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
    }


def _activity_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            FIELD_MAX_ACTIVE_MINUTES,
            default=int(settings.get(FIELD_MAX_ACTIVE_MINUTES, 0)),
        ): _number_selector(minimum=0, step=1),
        vol.Optional(
            FIELD_MAX_IDLE_MINUTES,
            default=int(settings.get(FIELD_MAX_IDLE_MINUTES, 0)),
        ): _number_selector(minimum=0, step=1),
    }


def _billing_cost_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
        ): _time_selector(),
        vol.Optional(
            FIELD_TOU_END,
            default=str(settings.get(FIELD_TOU_END) or ""),
        ): _time_selector(),
        vol.Optional(
            FIELD_TOU_WEEKDAYS,
            default=_tou_weekday_selection(settings.get(FIELD_TOU_WEEKDAYS)),
        ): _weekday_select_selector(),
        vol.Optional(
            FIELD_TOU_NAME,
            default=str(settings.get(FIELD_TOU_NAME) or "Peak"),
        ): _text_selector(),
    }


def _demand_capacity_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
    }


def _standby_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
    }


def _water_context_fields(
    settings: Mapping[str, Any],
    context: Mapping[str, str],
) -> dict[Any, Any]:
    profile = context.get("profile", "")
    expects_flow_default = profile in {
        ApplianceProfile.WATER_PUMP.value,
        ApplianceProfile.WELL_PUMP.value,
        ApplianceProfile.WATER_HEATER.value,
        ApplianceProfile.WASHER.value,
    }
    fields: dict[Any, Any] = {
        vol.Optional(
            CONF_RAIN_PUMP_CORRELATION_ENABLED,
            default=bool(
                settings.get(
                    CONF_RAIN_PUMP_CORRELATION_ENABLED,
                    DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
                )
            ),
        ): bool,
        vol.Optional(
            CONF_RAIN_RESPONSE_WINDOW_MINUTES,
            default=int(
                settings.get(
                    CONF_RAIN_RESPONSE_WINDOW_MINUTES,
                    DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
                )
            ),
        ): _number_selector(minimum=15, maximum=360, step=1),
        vol.Optional(
            CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
            default=float(
                settings.get(
                    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                    DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                )
            ),
        ): _number_selector(minimum=5.0, maximum=200.0, step=1),
    }
    if profile in {
        ApplianceProfile.WATER_PUMP.value,
        ApplianceProfile.WELL_PUMP.value,
        ApplianceProfile.WATER_HEATER.value,
        ApplianceProfile.WASHER.value,
    }:
        fields.update(
            {
                vol.Optional(
                    CONF_WATER_FLOW_CORRELATION_ENABLED,
                    default=bool(
                        settings.get(
                            CONF_WATER_FLOW_CORRELATION_ENABLED,
                            DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
                        )
                    ),
                ): bool,
                vol.Optional(
                    CONF_LINKED_FLOW_SENSOR_ENTITIES,
                    default=list(settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES, [])),
                ): _water_flow_entity_selector(multiple=True),
                vol.Optional(
                    CONF_EXPECTS_WATER_FLOW,
                    default=bool(
                        settings.get(CONF_EXPECTS_WATER_FLOW, expects_flow_default)
                    ),
                ): bool,
                vol.Optional(
                    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
                    default=int(
                        settings.get(
                            CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
                            DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
                        )
                    ),
                ): _number_selector(minimum=1, maximum=120, step=1),
            }
        )
    return fields


def _dual_phase_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
    }


def _power_quality_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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
    }


def _mains_balance_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            FIELD_BALANCE_NEGATIVE_TOLERANCE_W,
            default=float(
                settings.get(
                    FIELD_BALANCE_NEGATIVE_TOLERANCE_W,
                    DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                )
            ),
        ): _number_selector(minimum=0.0, step=1),
    }


def _solar_flow_fields(settings: Mapping[str, Any]) -> dict[Any, Any]:
    return {
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


def _advanced_circuit_context(
    context: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    raw_context = dict(context or {})
    circuit_id = str(raw_context.get("circuit_id") or "selected").strip()
    if not circuit_id:
        circuit_id = "selected"
    profile = _safe_appliance_profile(
        raw_context.get("appliance_profile"),
        ApplianceProfile.MOTOR_LOAD.value,
    )
    mode = _safe_circuit_mode(
        raw_context.get("mode"),
        CircuitMode.SINGLE_PHASE.value,
    )
    if circuit_id == "mains":
        profile = ApplianceProfile.MAINS_NILM.value
        mode = CircuitMode.MAINS_NILM.value
    power_flow = _normalize_power_flow(str(raw_context.get("power_flow") or ""))
    if _is_advanced_mains_context(
        {"circuit_id": circuit_id, "profile": profile, "mode": mode}
    ):
        power_flow = PowerFlowMode.MAINS_NET.value
    name = str(raw_context.get("name") or circuit_id).strip() or circuit_id
    return {
        "circuit_id": circuit_id,
        "name": name,
        "profile": profile,
        "mode": mode,
        "power_flow": power_flow,
    }


def _advanced_context_display(context: Mapping[str, str]) -> str:
    circuit_id = context.get("circuit_id", "selected")
    name = context.get("name") or circuit_id
    return f"{name} ({circuit_id})"


def _advanced_show_energy_settings(context: Mapping[str, str]) -> bool:
    return not _is_advanced_solar_only_context(context)


def _advanced_show_activity_settings(context: Mapping[str, str]) -> bool:
    return _is_advanced_load_appliance_context(context)


def _advanced_show_billing_cost_settings(context: Mapping[str, str]) -> bool:
    return not _is_advanced_solar_only_context(context)


def _advanced_show_demand_capacity_settings(context: Mapping[str, str]) -> bool:
    return not _is_advanced_solar_only_context(context)


def _advanced_show_standby_settings(context: Mapping[str, str]) -> bool:
    return _is_advanced_load_appliance_context(context)


def _advanced_show_water_context_settings(context: Mapping[str, str]) -> bool:
    return context.get("profile") in {
        ApplianceProfile.SUMP_PUMP.value,
        ApplianceProfile.WATER_PUMP.value,
        ApplianceProfile.WELL_PUMP.value,
        ApplianceProfile.WATER_HEATER.value,
        ApplianceProfile.WASHER.value,
    }


def _advanced_show_dual_phase_settings(context: Mapping[str, str]) -> bool:
    return context.get("mode") == CircuitMode.DUAL_PHASE.value


def _advanced_show_mains_settings(context: Mapping[str, str]) -> bool:
    return _is_advanced_mains_context(context)


def _is_advanced_load_appliance_context(context: Mapping[str, str]) -> bool:
    return not (
        _is_advanced_mains_context(context)
        or _is_advanced_mixed_context(context)
        or _is_advanced_solar_only_context(context)
    )


def _is_advanced_mains_context(context: Mapping[str, str]) -> bool:
    return (
        context.get("circuit_id") == "mains"
        or context.get("profile") == ApplianceProfile.MAINS_NILM.value
        or context.get("mode") == CircuitMode.MAINS_NILM.value
    )


def _is_advanced_mixed_context(context: Mapping[str, str]) -> bool:
    return (
        context.get("profile") == ApplianceProfile.MIXED.value
        or context.get("mode") == CircuitMode.MIXED.value
    )


def _is_advanced_solar_only_context(context: Mapping[str, str]) -> bool:
    return (
        context.get("profile") == ApplianceProfile.SOLAR_INVERTER.value
        and not _is_advanced_mains_context(context)
    )


def _safe_appliance_profile(value: Any, default: str) -> str:
    normalized = _normalize_assignment_profile(str(value or "")).strip()
    try:
        return ApplianceProfile(normalized).value
    except ValueError:
        return default


def _safe_circuit_mode(value: Any, default: str) -> str:
    try:
        return _normalize_assignment_mode(str(value or ""))
    except SetupValidationError:
        return default


def _profile_label(value: Any) -> str:
    normalized = _normalize_assignment_profile(str(value or "")).strip()
    if normalized in _APPLIANCE_PROFILE_LABELS:
        return _APPLIANCE_PROFILE_LABELS[normalized]
    return normalized.replace("_", " ").title() if normalized else "Appliance"


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
    profile = str(group.get("appliance_profile") or "").strip()
    mode = str(group.get("mode") or "").strip()
    return _default_power_flow_for_assignment(profile, mode)


def _default_power_flow_for_assignment(profile: str, mode: str = "") -> str:
    if profile == ApplianceProfile.SOLAR_INVERTER.value:
        return PowerFlowMode.GENERATION.value
    if (
        profile == ApplianceProfile.MAINS_NILM.value
        or mode == CircuitMode.MAINS_NILM.value
    ):
        return PowerFlowMode.MAINS_NET.value
    return PowerFlowMode.LOAD.value


def _default_mode_for_assignment_profile(profile: str) -> str:
    if profile == ApplianceProfile.MAINS_NILM.value:
        return CircuitMode.MAINS_NILM.value
    if profile == ApplianceProfile.MIXED.value:
        return CircuitMode.MIXED.value
    if profile in {
        ApplianceProfile.HVAC.value,
        ApplianceProfile.HVAC_COMPRESSOR.value,
        ApplianceProfile.ELECTRIC_HEAT.value,
        ApplianceProfile.WATER_HEATER.value,
        ApplianceProfile.OVEN.value,
        ApplianceProfile.DRYER.value,
        ApplianceProfile.POOL_PUMP.value,
        ApplianceProfile.EV_CHARGER.value,
    }:
        return CircuitMode.DUAL_PHASE.value
    return CircuitMode.SINGLE_PHASE.value


def _assignment_mode_for_profile_and_entities(
    profile: str,
    entity_ids: Iterable[str],
) -> str:
    default_mode = _default_mode_for_assignment_profile(profile)
    if default_mode != CircuitMode.DUAL_PHASE.value:
        return default_mode
    return (
        CircuitMode.DUAL_PHASE.value
        if _assignment_entities_have_both_legs(entity_ids)
        else CircuitMode.SINGLE_PHASE.value
    )


def _assignment_entities_have_both_legs(entity_ids: Iterable[str]) -> bool:
    legs = {
        leg
        for leg in (_assignment_leg_hint(entity_id) for entity_id in entity_ids)
        if leg in {"a", "b"}
    }
    return legs == {"a", "b"}


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
            saved_profile = _normalize_assignment_profile(
                str(
                    saved_circuit.get(
                        "appliance_profile",
                        group["appliance_profile"],
                    )
                )
            )
            stable_circuit_id = str(
                saved_circuit.get("circuit_id")
                or saved_circuit.get("id")
                or ""
            ).strip()
            group.update(
                {
                    "circuit_id": stable_circuit_id or group["group_id"],
                    "name": str(saved_circuit.get("name") or group["name"]),
                    "appliance_profile": saved_profile,
                    "mode": _assignment_mode_for_profile_and_entities(
                        saved_profile,
                        selected_entity_ids,
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
    group_id = _canonical_assignment_circuit_id(group.get("group_id"))
    for circuit in existing_circuits:
        sensor_entities = set(_sensor_entity_ids_from_circuit(circuit))
        if group_entities and group_entities <= sensor_entities:
            return circuit
        circuit_id = _canonical_assignment_circuit_id(
            circuit.get("circuit_id") or circuit.get("id")
        )
        circuit_name = _canonical_assignment_circuit_id(circuit.get("name"))
        if group_id in {circuit_id, circuit_name}:
            return circuit
        if group_entities and sensor_entities and group_entities & sensor_entities:
            return circuit
    return None


def _sensor_entity_ids_from_circuit(circuit: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        entity_id
        for sensor in circuit.get("sensors", ())
        if (entity_id := _sensor_entity_id_from_raw(sensor))
    )


def _sensor_entity_id_from_raw(sensor: Any) -> str:
    if isinstance(sensor, str):
        return sensor
    if isinstance(sensor, Mapping) and sensor.get("entity_id"):
        return str(sensor["entity_id"])
    return ""


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
    profile = str(group.get("appliance_profile") or "")
    mode = str(group.get("mode") or _default_mode_for_assignment_profile(profile))
    power_flow = _default_power_flow_for_assignment(profile, mode)
    return {
        "circuit_name": str(group.get("name") or ""),
        "appliance_profile": profile,
        "circuit_mode": mode,
        "power_flow": power_flow,
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
        _assignment_review_source_entities(pending_config),
        mains_source_entities=pending_config.get(CONF_MAINS_SOURCE_ENTITIES, []),
        existing_circuits=existing_circuit_list,
    )
    if update_existing:
        groups = [
            {**group, "allow_remove_from_analysis": True}
            for group in groups
        ]
    flow._pending_config = dict(pending_config)
    flow._assignment_groups = groups
    flow._assignment_index = 0
    flow._reviewed_circuits = []
    flow._assignment_update_existing = bool(update_existing)
    flow._assignment_existing_circuits = existing_circuit_list
    flow._assignment_selected_circuit_id = None
    if update_existing and len(groups) == 1:
        flow._assignment_selected_circuit_id = _assignment_group_value(groups[0])
    if show_picker:
        return _assignment_picker_form(flow)
    return _assignment_review_form(flow)


def _assignment_review_source_entities(config: Mapping[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *_strict_string_list(
                    config.get(CONF_SOURCE_ENTITIES, []),
                    invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
                ),
                *_strict_string_list(
                    config.get(CONF_EXTRA_SOURCE_ENTITIES, []),
                    invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
                ),
            ]
        )
    )


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
            groups[index],
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
    if bool(group.get("allow_remove_from_analysis", False)) and bool(
        user_input.get(FIELD_REMOVE_FROM_ANALYSIS, False)
    ):
        return None
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
    mode = _assignment_mode_for_profile_and_entities(profile, entity_ids)
    power_flow = _default_power_flow_for_assignment(profile, mode)
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
    selected_group: Mapping[str, Any],
    reviewed_circuits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    reviewed = [dict(circuit) for circuit in reviewed_circuits]
    replacement = reviewed[0] if reviewed else None
    selected_entity_ids = _assignment_entity_ids_from_group(selected_group)
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
    if not final_circuits:
        return _final_config_from_empty_assignment_update(
            pending_config,
            removed_source_entities=selected_entity_ids,
        )

    final_config = dict(pending_config)
    final_config[CONF_SOURCE_ENTITIES] = _source_entities_after_assignment_update(
        pending_config,
        final_circuits,
        removed_source_entities=selected_entity_ids,
    )
    final_config[CONF_CIRCUITS] = final_circuits
    circuit_ids = {
        str(circuit.get("circuit_id") or circuit.get("id") or "")
        for circuit in final_circuits
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
        final_circuits
    )
    return final_config


def _final_config_from_empty_assignment_update(
    pending_config: Mapping[str, Any],
    *,
    removed_source_entities: Iterable[str] = (),
) -> dict[str, Any]:
    final_config = dict(pending_config)
    removed = {str(entity_id) for entity_id in removed_source_entities}
    if removed:
        source_entities = _strict_string_list(
            final_config.get(CONF_SOURCE_ENTITIES, []),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
        final_config[CONF_SOURCE_ENTITIES] = [
            entity_id for entity_id in source_entities if entity_id not in removed
        ]
    final_config[CONF_CIRCUITS] = []
    final_config[CONF_CIRCUIT_ASSIGNMENTS] = _assignment_text_from_circuits([])
    if CONF_KNOWN_LOAD_CIRCUITS in final_config:
        final_config[CONF_KNOWN_LOAD_CIRCUITS] = []
    return final_config


def _source_entities_after_assignment_update(
    pending_config: Mapping[str, Any],
    circuits: Iterable[Mapping[str, Any]],
    *,
    removed_source_entities: Iterable[str] = (),
) -> list[str]:
    removed = {str(entity_id) for entity_id in removed_source_entities}
    active_source_entities = [
        entity_id
        for entity_id in _strict_string_list(
            pending_config.get(CONF_SOURCE_ENTITIES, []),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
        if entity_id not in removed
    ]
    circuit_source_entities = [
        entity_id
        for circuit in circuits
        for entity_id in _sensor_entity_ids_from_circuit(circuit)
    ]
    return list(dict.fromkeys([*active_source_entities, *circuit_source_entities]))


def _assignment_entity_ids_from_group(group: Mapping[str, Any]) -> tuple[str, ...]:
    entity_ids = tuple(str(entity_id) for entity_id in group.get("entity_ids", ()))
    if entity_ids:
        return entity_ids
    return _sensor_entity_ids_from_circuit(group)


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
                    ", ".join(_sensor_entity_ids_from_circuit(circuit)),
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
        "microwave_oven": ApplianceProfile.MICROWAVE.value,
        "kitchen_microwave": ApplianceProfile.MICROWAVE.value,
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
    return _canonical_assignment_circuit_id(
        _strip_trailing_source_detail_tokens(object_id)
    )


def _canonical_assignment_circuit_id(value: Any) -> str:
    circuit_id = _slugify(str(value or ""))
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


def _suggest_assignment_profile_mode(
    circuit_id: str,
    entity_ids: Iterable[str],
) -> tuple[str, str]:
    entity_id_list = list(entity_ids)
    text = f"_{circuit_id}_{' '.join(entity_id_list)}_".lower()
    if any(token in text for token in ("_air_handler_", "_blower_")):
        return ApplianceProfile.HVAC_BLOWER.value, CircuitMode.SINGLE_PHASE.value
    if any(
        token in text for token in ("_aux_heat_", "_electric_heat_", "_heat_strip_")
    ):
        profile = ApplianceProfile.ELECTRIC_HEAT.value
        return profile, _assignment_mode_for_profile_and_entities(
            profile,
            entity_id_list,
        )
    if any(
        token in text
        for token in ("_compressor_", "_heat_pump_", "_air_conditioner_", "_ac_")
    ):
        profile = ApplianceProfile.HVAC_COMPRESSOR.value
        return profile, _assignment_mode_for_profile_and_entities(
            profile,
            entity_id_list,
        )
    if "_hvac_" in text:
        profile = ApplianceProfile.HVAC.value
        return profile, _assignment_mode_for_profile_and_entities(
            profile,
            entity_id_list,
        )
    if "_water_pump_" in text or "_well_pump_" in text or "_booster_pump_" in text:
        return ApplianceProfile.WATER_PUMP.value, CircuitMode.SINGLE_PHASE.value
    if "_sump_pump_" in text:
        return ApplianceProfile.SUMP_PUMP.value, CircuitMode.SINGLE_PHASE.value
    if "_pool_pump_" in text:
        return ApplianceProfile.POOL_PUMP.value, CircuitMode.SINGLE_PHASE.value
    for token, profile, _mode in (
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
        (
            "_microwave_",
            ApplianceProfile.MICROWAVE.value,
            CircuitMode.SINGLE_PHASE.value,
        ),
        (
            "_microwave_oven_",
            ApplianceProfile.MICROWAVE.value,
            CircuitMode.SINGLE_PHASE.value,
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
            return profile, _assignment_mode_for_profile_and_entities(
                profile,
                entity_id_list,
            )
    return ApplianceProfile.MIXED.value, CircuitMode.MIXED.value


def _friendly_name_from_id(value: str) -> str:
    text = str(value).removeprefix("cs_energy_analyzer_demo_")
    return text.replace("_", " ").strip().title()


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
                    "sources",
                    "mains",
                    "assign",
                    "nilm",
                    "utility",
                    "dashboard",
                    "entity_detail",
                    "recommendations",
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
            source_input = dict(user_input)
            if CONF_MAINS_SOURCE_ENTITIES not in source_input:
                source_input[CONF_MAINS_SOURCE_ENTITIES] = _entry_value(
                    self._config_entry,
                    CONF_MAINS_SOURCE_ENTITIES,
                    [],
                )
            if CONF_ENTITY_DETAIL_LEVEL not in source_input:
                source_input[CONF_ENTITY_DETAIL_LEVEL] = _entry_value(
                    self._config_entry,
                    CONF_ENTITY_DETAIL_LEVEL,
                    DEFAULT_ENTITY_DETAIL_LEVEL,
                )
            remove_demo_source_bundle = (
                CONF_DEMO_SOURCE_BUNDLE_ENABLED in source_input
                and not bool(source_input.get(CONF_DEMO_SOURCE_BUNDLE_ENABLED))
                and _demo_source_bundle_enabled_for_config_entry(self._config_entry)
            )
            try:
                validated = validate_options_input(
                    await _async_source_selection_with_device_entities(
                        getattr(self, "hass", None),
                        source_input,
                    ),
                    remove_demo_source_bundle=remove_demo_source_bundle,
                    allow_empty_sources=remove_demo_source_bundle,
                )
            except SetupValidationError as err:
                return await self._async_show_options_form({"base": err.error_key})
            updated_options = _options_with_updates(self._config_entry, validated)
            if remove_demo_source_bundle:
                updated_options = _remove_demo_source_bundle_from_config(
                    updated_options,
                    fallback_config=_entry_config(self._config_entry),
                )
            updated_options = _options_with_merged_source_circuit_sensors(
                self._config_entry,
                updated_options,
            )
            return self.async_create_entry(
                title="",
                data=updated_options,
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
            if bool(getattr(self, "_assignment_update_existing", False)):
                return self.async_create_entry(title="", data=final_config)
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
            coordinator = _options_flow_coordinator(self)
            if coordinator is not None:
                replace_settings = getattr(
                    coordinator,
                    "async_replace_advanced_settings",
                    None,
                )
                if callable(replace_settings):
                    result = replace_settings(circuit_id, settings)
                    if hasattr(result, "__await__"):
                        await result
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_ADVANCED_SETTINGS: settings_by_circuit},
                ),
            )

        return await self._async_show_advanced_settings_form(circuit_id)

    async def async_step_recommendations(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Review pending advanced-setting recommendations."""
        coordinator = _options_flow_coordinator(self)
        if coordinator is None:
            return self.async_show_form(
                step_id="recommendations",
                data_schema=_recommendations_schema(()),
                errors={"base": ERROR_RECOMMENDATIONS_NOT_LOADED},
                description_placeholders={
                    "recommendations": (
                        "The analyzer is not loaded yet. Start the integration, "
                        "then come back here to review suggested settings."
                    )
                },
            )

        await _async_refresh_setting_recommendations(coordinator)
        recommendations = _pending_setting_recommendations(coordinator)
        if user_input is not None:
            recommendation_ids = {
                str(_recommendation_value(recommendation, FIELD_RECOMMENDATION_ID))
                for recommendation in recommendations
            }
            selected_recommendation_ids = _selected_setting_suggestion_ids(user_input)
            if (
                not selected_recommendation_ids
                or not set(selected_recommendation_ids) <= recommendation_ids
            ):
                return _recommendations_form(
                    self,
                    recommendations,
                    errors={"base": ERROR_INVALID_RECOMMENDATION},
                )

            action = str(user_input.get(FIELD_RECOMMENDATION_ACTION) or "")
            if action == RECOMMENDATION_ACTION_APPLY:
                for recommendation_id in selected_recommendation_ids:
                    await coordinator.async_apply_setting_recommendation(
                        recommendation_id
                    )
            elif action == RECOMMENDATION_ACTION_DENY:
                for recommendation_id in selected_recommendation_ids:
                    await coordinator.async_deny_setting_recommendation(
                        recommendation_id
                    )
            elif action == RECOMMENDATION_ACTION_DISMISS:
                for recommendation_id in selected_recommendation_ids:
                    await coordinator.async_dismiss_setting_recommendation(
                        recommendation_id
                    )
            else:
                return _recommendations_form(
                    self,
                    recommendations,
                    errors={"base": ERROR_INVALID_RECOMMENDATION},
                )

            return self.async_create_entry(
                title="",
                data=_options_after_recommendation_action(
                    self._config_entry,
                    coordinator,
                    action,
                ),
            )

        return _recommendations_form(self, recommendations)

    async def async_step_entity_detail(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit entity detail level and optionally apply it to existing entities."""
        if user_input is not None:
            detail_level = normalize_entity_detail_level(
                user_input.get(CONF_ENTITY_DETAIL_LEVEL)
            )
            if bool(user_input.get(FIELD_APPLY_ENTITY_DETAIL_PROFILE, False)):
                _apply_entity_detail_profile_to_existing_entities(
                    getattr(self, "hass", None),
                    self._config_entry,
                    detail_level,
                )
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_ENTITY_DETAIL_LEVEL: detail_level},
                ),
            )

        return self.async_show_form(
            step_id="entity_detail",
            data_schema=_entity_detail_schema(self._config_entry),
            errors={},
        )

    async def async_step_dashboard(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Create or update the recommended dashboard."""
        if user_input is not None:
            layout = normalize_dashboard_layout(
                user_input.get(CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT)
            )
            coordinator = _options_flow_coordinator(self)
            if coordinator is not None:
                set_layout = getattr(coordinator, "async_set_dashboard_layout", None)
                if callable(set_layout):
                    result = set_layout(layout)
                    if hasattr(result, "__await__"):
                        await result
                create_dashboard = getattr(coordinator, "async_create_dashboard", None)
                if callable(create_dashboard):
                    dashboard_result = create_dashboard()
                    if hasattr(dashboard_result, "__await__"):
                        dashboard_result = await dashboard_result
                    if _dashboard_creation_unavailable(
                        dashboard_result,
                        coordinator,
                    ):
                        return self.async_show_form(
                            step_id="dashboard",
                            data_schema=_dashboard_schema(self._config_entry),
                            errors={"base": "dashboard_creation_unavailable"},
                        )
            return self.async_create_entry(
                title="",
                data=_options_with_updates(
                    self._config_entry,
                    {CONF_DASHBOARD_LAYOUT: layout},
                ),
            )

        return self.async_show_form(
            step_id="dashboard",
            data_schema=_dashboard_schema(self._config_entry),
            errors={},
        )

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
        config = _entry_config(self._config_entry)
        context = _advanced_circuit_context_from_config(config, circuit_id)
        settings = _settings_map_for_entry(self._config_entry, CONF_ADVANCED_SETTINGS)
        return self.async_show_form(
            step_id="advanced_settings",
            data_schema=_advanced_settings_schema(
                settings.get(circuit_id, {}),
                context,
            ),
            errors=errors or {},
            description_placeholders={
                "circuit_id": circuit_id,
                "circuit_name": _advanced_context_display(context),
                "appliance_profile": _profile_label(context.get("profile")),
                "circuit_mode": _CIRCUIT_MODE_LABELS.get(
                    context.get("mode", ""),
                    "Single Phase",
                ),
                "power_flow": _power_flow_label(context.get("power_flow")),
            },
        )


def _options_flow_coordinator(flow: Any) -> Any | None:
    hass = getattr(flow, "hass", None)
    data = getattr(hass, "data", {}) or {}
    domain_data = data.get(DOMAIN, {}) if isinstance(data, Mapping) else {}
    if not isinstance(domain_data, Mapping):
        return None
    entry_id = getattr(getattr(flow, "_config_entry", None), "entry_id", None)
    return domain_data.get(entry_id)


def _dashboard_creation_unavailable(result: Any, coordinator: Any) -> bool:
    if isinstance(result, Mapping):
        return result.get("action") == "unavailable"
    last_request = getattr(coordinator, "last_dashboard_create_request", None)
    return (
        isinstance(last_request, Mapping)
        and last_request.get("action") == "unavailable"
    )


async def _async_refresh_setting_recommendations(coordinator: Any) -> None:
    recalculate = getattr(
        coordinator,
        "async_recalculate_setting_recommendations",
        None,
    )
    if not callable(recalculate):
        return
    result = recalculate(None)
    if hasattr(result, "__await__"):
        await result


def _pending_setting_recommendations(coordinator: Any) -> list[Any]:
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {}) or {}
    if not isinstance(by_circuit, Mapping):
        return []

    recommendations: list[Any] = []
    for circuit_recommendations in by_circuit.values():
        if not isinstance(circuit_recommendations, Iterable) or isinstance(
            circuit_recommendations,
            (str, bytes),
        ):
            continue
        for recommendation in circuit_recommendations:
            if _recommendation_status(recommendation) == "pending":
                recommendations.append(recommendation)
    return recommendations


def _recommendation_select_options(
    recommendations: Iterable[Any],
) -> list[dict[str, str]]:
    return [
        {
            "value": str(
                _recommendation_value(recommendation, FIELD_RECOMMENDATION_ID)
            ),
            "label": _recommendation_label(recommendation),
        }
        for recommendation in recommendations
        if _recommendation_value(recommendation, FIELD_RECOMMENDATION_ID)
    ]


def _recommendation_action_options() -> list[dict[str, str]]:
    return [dict(option) for option in _RECOMMENDATION_ACTION_OPTIONS]


def _selected_setting_suggestion_ids(user_input: Mapping[str, Any]) -> list[str]:
    raw_value = user_input.get(FIELD_SETTING_SUGGESTION_IDS)
    if raw_value is None:
        raw_value = user_input.get(FIELD_RECOMMENDATION_ID)
    if isinstance(raw_value, str):
        raw_items: Iterable[Any] = (raw_value,)
    elif isinstance(raw_value, Iterable):
        raw_items = raw_value
    else:
        raw_items = ()

    selected: list[str] = []
    for item in raw_items:
        suggestion_id = str(item or "").strip()
        if suggestion_id and suggestion_id not in selected:
            selected.append(suggestion_id)
    return selected


def _recommendations_form(
    flow: Any,
    recommendations: Iterable[Any],
    *,
    errors: dict[str, str] | None = None,
) -> config_entries.ConfigFlowResult:
    recommendation_list = list(recommendations)
    return flow.async_show_form(
        step_id="recommendations",
        data_schema=_recommendations_schema(recommendation_list),
        errors=errors or {},
        description_placeholders={
            "recommendations": _recommendation_summary(recommendation_list),
        },
    )


def _recommendation_summary(recommendations: Iterable[Any]) -> str:
    recommendation_list = list(recommendations)
    if not recommendation_list:
        return (
            "There are no pending suggestions yet. The analyzer will show "
            "evidence-based setting ideas here after it has enough history."
        )

    lines = [
        "Settings Suggestions:",
    ]
    for recommendation in recommendation_list:
        lines.append(f"- {_recommendation_label(recommendation)}")
        unit = _recommendation_value(recommendation, "unit")
        current_value = _recommendation_value(recommendation, "current_value")
        suggested_value = _recommendation_value(recommendation, "suggested_value")
        lines.append(
            "  Current value: "
            f"{_format_recommendation_value(current_value, unit)}"
        )
        default_value = _recommendation_default_value(recommendation)
        if default_value is not None:
            lines.append(
                "  Default value: "
                f"{_format_recommendation_value(default_value, unit)}"
            )
        lines.append(
            "  Suggested value: "
            f"{_format_recommendation_value(suggested_value, unit)}"
        )
        reason = str(_recommendation_value(recommendation, "reason") or "").strip()
        if reason:
            lines.append(f"  Reason: {reason}")
        expected_effect = _recommendation_expected_effect(recommendation)
        if expected_effect:
            lines.append(f"  Expected effect: {expected_effect}")
        evidence = _recommendation_evidence_text(recommendation)
        if evidence:
            lines.append(f"  Evidence: {evidence}")
    return "\n".join(lines)


def _recommendation_label(recommendation: Any) -> str:
    circuit = _recommendation_circuit_label(recommendation)
    setting = _recommendation_setting_label(recommendation)
    current = _format_recommendation_value(
        _recommendation_value(recommendation, "current_value"),
        _recommendation_value(recommendation, "unit"),
    )
    suggested = _format_recommendation_value(
        _recommendation_value(recommendation, "suggested_value"),
        _recommendation_value(recommendation, "unit"),
    )
    label = f"{circuit} - {setting}: {current} -> {suggested}"
    confidence = _recommendation_value(recommendation, "confidence")
    if confidence is not None:
        label = f"{label} ({_format_confidence(confidence)} confidence)"
    return label


def _recommendation_circuit_label(recommendation: Any) -> str:
    name = str(_recommendation_value(recommendation, "circuit_name") or "").strip()
    if name:
        return name
    circuit_id = str(_recommendation_value(recommendation, "circuit_id") or "").strip()
    return _friendly_name_from_id(circuit_id) if circuit_id else "Selected circuit"


def _recommendation_setting_label(recommendation: Any) -> str:
    label = str(_recommendation_value(recommendation, "setting_label") or "").strip()
    if label:
        return label
    setting_key = str(_recommendation_value(recommendation, "setting_key") or "")
    return _friendly_name_from_id(setting_key) if setting_key else "Setting"


def _recommendation_evidence_text(recommendation: Any) -> str:
    evidence = _recommendation_value(recommendation, "evidence")
    if not isinstance(evidence, Mapping):
        return ""

    parts: list[str] = []
    for key, value in evidence.items():
        key_text = str(key)
        if _is_hidden_recommendation_evidence_key(key_text):
            continue
        if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
            continue
        parts.append(
            f"{_friendly_name_from_id(key_text)}: "
            f"{_format_recommendation_value(value, None)}"
        )
        if len(parts) >= 4:
            break
    return "; ".join(parts)


def _recommendation_default_value(recommendation: Any) -> Any:
    setting_key = str(_recommendation_value(recommendation, "setting_key") or "")
    return recommendation_setting_default_value(setting_key)


def _recommendation_expected_effect(recommendation: Any) -> str:
    setting_key = str(_recommendation_value(recommendation, "setting_key") or "")
    return recommendation_setting_expected_effect(setting_key)


def _is_hidden_recommendation_evidence_key(key: str) -> bool:
    return is_hidden_recommendation_evidence_key(key)


def _format_recommendation_value(value: Any, unit: Any) -> str:
    if value is None:
        return "not set"
    if isinstance(value, bool):
        text = "on" if value else "off"
    elif isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)

    unit_text = str(unit or "").strip()
    return f"{text} {unit_text}" if unit_text else text


def _format_confidence(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return str(value)
    if 0.0 <= confidence <= 1.0:
        confidence *= 100.0
    return f"{confidence:.0f}%"


def _recommendation_status(recommendation: Any) -> str:
    status = _recommendation_value(recommendation, "status")
    if status is None:
        return "pending"
    status_value = getattr(status, "value", status)
    return str(status_value).lower().split(".")[-1]


def _recommendation_value(recommendation: Any, key: str) -> Any:
    if isinstance(recommendation, Mapping):
        return recommendation.get(key)
    return getattr(recommendation, key, None)


def _options_after_recommendation_action(
    config_entry: config_entries.ConfigEntry,
    coordinator: Any,
    action: str,
) -> dict[str, Any]:
    if action == RECOMMENDATION_ACTION_APPLY:
        options = getattr(coordinator, "options", None)
        if isinstance(options, Mapping):
            return dict(options)
    return dict(getattr(config_entry, "options", {}) or {})


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
    source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
    )
    source_entities = _resolve_discovered_demo_source_entity_ids(
        source_entities,
        source_entity_ids,
    )
    source_devices = options.get(
        CONF_SOURCE_DEVICES,
        data.get(CONF_SOURCE_DEVICES, []),
    )
    mains_source_entities = options.get(
        CONF_MAINS_SOURCE_ENTITIES,
        data.get(CONF_MAINS_SOURCE_ENTITIES, []),
    )
    mains_source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            mains_source_entities,
            invalid_error_key="invalid_mains_source_entities",
        )
    )
    mains_source_entities = _resolve_discovered_demo_source_entity_ids(
        mains_source_entities,
        source_entity_ids,
    )
    outdoor_temperature_entity = options.get(
        CONF_OUTDOOR_TEMPERATURE_ENTITY,
        data.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, ""),
    )
    rain_sensor_entity = options.get(
        CONF_RAIN_SENSOR_ENTITY,
        data.get(CONF_RAIN_SENSOR_ENTITY, ""),
    )
    rain_intensity_entity = options.get(
        CONF_RAIN_INTENSITY_ENTITY,
        data.get(CONF_RAIN_INTENSITY_ENTITY, ""),
    )
    water_flow_sensor_entities = options.get(
        CONF_WATER_FLOW_SENSOR_ENTITIES,
        data.get(CONF_WATER_FLOW_SENSOR_ENTITIES, []),
    )
    extra_source_entities = options.get(
        CONF_EXTRA_SOURCE_ENTITIES,
        data.get(CONF_EXTRA_SOURCE_ENTITIES, source_entities),
    )
    extra_source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            extra_source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
    )
    extra_source_entities = _resolve_discovered_demo_source_entity_ids(
        extra_source_entities,
        source_entity_ids,
    )
    demo_source_bundle_enabled = _demo_source_bundle_enabled_for_entry_values(
        options,
        data,
        source_entities=source_entities,
        extra_source_entities=extra_source_entities,
        mains_source_entities=mains_source_entities,
    )
    selectable_source_entities = _selectable_source_entity_ids(
        source_entity_ids,
        source_entities,
        extra_source_entities,
        mains_source_entities,
    )
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
                CONF_DEMO_SOURCE_BUNDLE_ENABLED,
                default=demo_source_bundle_enabled,
            ): bool,
            _optional_entity_marker(
                CONF_OUTDOOR_TEMPERATURE_ENTITY,
                outdoor_temperature_entity,
            ): _temperature_entity_selector(),
            _optional_entity_marker(
                CONF_RAIN_SENSOR_ENTITY,
                rain_sensor_entity,
            ): _binary_sensor_entity_selector(),
            _optional_entity_marker(
                CONF_RAIN_INTENSITY_ENTITY,
                rain_intensity_entity,
            ): _single_sensor_entity_selector(),
            vol.Optional(
                CONF_WATER_FLOW_SENSOR_ENTITIES,
                default=water_flow_sensor_entities,
            ): _water_flow_entity_selector(multiple=True),
            vol.Optional(
                CONF_SENSITIVITY,
                default=normalize_sensitivity(
                    options.get(
                        CONF_SENSITIVITY,
                        data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
                    )
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


def _entity_detail_schema(config_entry: config_entries.ConfigEntry) -> Any:
    detail_level = normalize_entity_detail_level(
        _entry_value(
            config_entry,
            CONF_ENTITY_DETAIL_LEVEL,
            DEFAULT_ENTITY_DETAIL_LEVEL,
        )
    )
    return vol.Schema(
        {
            vol.Optional(
                CONF_ENTITY_DETAIL_LEVEL,
                default=detail_level,
            ): _select_selector(entity_detail_level_options()),
            vol.Optional(
                FIELD_APPLY_ENTITY_DETAIL_PROFILE,
                default=False,
            ): bool,
        }
    )


def _dashboard_schema(config_entry: config_entries.ConfigEntry) -> Any:
    layout = normalize_dashboard_layout(
        _entry_value(config_entry, CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT)
    )
    return vol.Schema(
        {
            vol.Optional(
                CONF_DASHBOARD_LAYOUT,
                default=layout,
            ): _select_selector(dashboard_layout_options()),
        }
    )


def _options_source_payload(config_entry: config_entries.ConfigEntry) -> dict[str, Any]:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    source_entities = _strict_string_list(
        options.get(CONF_SOURCE_ENTITIES, data.get(CONF_SOURCE_ENTITIES, [])),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    source_entities = _normalize_demo_source_entity_ids(source_entities)
    extra_source_entities = _strict_string_list(
        options.get(
            CONF_EXTRA_SOURCE_ENTITIES,
            data.get(CONF_EXTRA_SOURCE_ENTITIES, source_entities),
        ),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    extra_source_entities = _normalize_demo_source_entity_ids(extra_source_entities)
    demo_source_bundle_enabled = bool(
        options.get(
            CONF_DEMO_SOURCE_BUNDLE_ENABLED,
            data.get(CONF_DEMO_SOURCE_BUNDLE_ENABLED, False),
        )
    )
    if demo_source_bundle_enabled:
        extra_source_entities = _with_demo_source_bundle(extra_source_entities)
    merged_source_entities = list(
        dict.fromkeys([*extra_source_entities, *source_entities])
    )
    if demo_source_bundle_enabled:
        merged_source_entities = _with_demo_source_bundle(merged_source_entities)
    if not merged_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    return {
        CONF_SOURCE_DEVICES: _strict_string_list(
            options.get(CONF_SOURCE_DEVICES, data.get(CONF_SOURCE_DEVICES, [])),
            invalid_error_key="invalid_source_devices",
        ),
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: source_entities,
        CONF_DEMO_SOURCE_BUNDLE_ENABLED: demo_source_bundle_enabled,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            options.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                data.get(
                    CONF_ENABLE_EXPERIMENTAL_NILM,
                    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
                ),
            )
        ),
        CONF_ENTITY_DETAIL_LEVEL: normalize_entity_detail_level(
            options.get(
                CONF_ENTITY_DETAIL_LEVEL,
                data.get(CONF_ENTITY_DETAIL_LEVEL, DEFAULT_ENTITY_DETAIL_LEVEL),
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _normalize_demo_source_entity_ids(
            _strict_string_list(
                options.get(
                    CONF_MAINS_SOURCE_ENTITIES,
                    data.get(CONF_MAINS_SOURCE_ENTITIES, []),
                ),
                invalid_error_key="invalid_mains_source_entities",
            )
        ),
        CONF_KNOWN_LOAD_CIRCUITS: _strict_string_list(
            options.get(
                CONF_KNOWN_LOAD_CIRCUITS,
                data.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            ),
            invalid_error_key="invalid_known_load_circuits",
        ),
        CONF_OUTDOOR_TEMPERATURE_ENTITY: str(
            options.get(
                CONF_OUTDOOR_TEMPERATURE_ENTITY,
                data.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, ""),
            )
            or ""
        ).strip(),
        CONF_RAIN_SENSOR_ENTITY: str(
            options.get(
                CONF_RAIN_SENSOR_ENTITY,
                data.get(CONF_RAIN_SENSOR_ENTITY, ""),
            )
            or ""
        ).strip(),
        CONF_RAIN_INTENSITY_ENTITY: str(
            options.get(
                CONF_RAIN_INTENSITY_ENTITY,
                data.get(CONF_RAIN_INTENSITY_ENTITY, ""),
            )
            or ""
        ).strip(),
        CONF_WATER_FLOW_SENSOR_ENTITIES: _strict_string_list(
            options.get(
                CONF_WATER_FLOW_SENSOR_ENTITIES,
                data.get(CONF_WATER_FLOW_SENSOR_ENTITIES, []),
            ),
            invalid_error_key="invalid_water_flow_sensor_entities",
        ),
        CONF_SENSITIVITY: normalize_sensitivity(
            options.get(
                CONF_SENSITIVITY,
                data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        ),
        CONF_DASHBOARD_LAYOUT: normalize_dashboard_layout(
            options.get(
                CONF_DASHBOARD_LAYOUT,
                data.get(CONF_DASHBOARD_LAYOUT, DEFAULT_DASHBOARD_LAYOUT),
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


def _options_with_merged_source_circuit_sensors(
    config_entry: config_entries.ConfigEntry,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    updated_options = dict(options)
    merged_circuits = _circuits_with_merged_source_circuit_sensors(
        updated_options,
        updated_options.get(CONF_CIRCUITS, _options_existing_circuits(config_entry)),
    )
    if merged_circuits is None:
        return updated_options

    updated_options[CONF_CIRCUITS] = merged_circuits
    updated_options[CONF_CIRCUIT_ASSIGNMENTS] = _assignment_text_from_circuits(
        merged_circuits
    )
    return updated_options


def _circuits_with_merged_source_circuit_sensors(
    config: Mapping[str, Any],
    existing_circuits: Iterable[Any],
) -> list[dict[str, Any]] | None:
    circuits = [
        {**circuit, "sensors": _copied_circuit_sensors(circuit)}
        for circuit in existing_circuits
        if isinstance(circuit, Mapping)
    ]
    if not circuits:
        return None

    circuit_index = _circuit_index_by_assignment_id(circuits)
    assigned_source_entities = {
        entity_id
        for circuit in circuits
        for entity_id in _sensor_entity_ids_from_circuit(circuit)
    }
    mains_source_entities = set(
        _strict_string_list(
            config.get(CONF_MAINS_SOURCE_ENTITIES, []),
            invalid_error_key="invalid_mains_source_entities",
        )
    )
    changed = False
    for entity_id in _strict_string_list(
        config.get(CONF_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    ):
        if entity_id in mains_source_entities or entity_id in assigned_source_entities:
            continue
        circuit_index_value = circuit_index.get(
            _assignment_circuit_id_from_entity_id(entity_id)
        )
        if circuit_index_value is None:
            continue
        circuits[circuit_index_value]["sensors"].append(
            _source_sensor_dict_from_entity_id(entity_id)
        )
        assigned_source_entities.add(entity_id)
        changed = True

    return circuits if changed else None


def _copied_circuit_sensors(circuit: Mapping[str, Any]) -> list[Any]:
    sensors: list[Any] = []
    for sensor in circuit.get("sensors", ()):
        if isinstance(sensor, str) and sensor:
            sensors.append(sensor)
        elif isinstance(sensor, Mapping) and sensor.get("entity_id"):
            sensors.append(dict(sensor))
    return sensors


def _circuit_index_by_assignment_id(
    circuits: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    circuit_index: dict[str, int] = {}
    for index, circuit in enumerate(circuits):
        for value in (
            circuit.get("circuit_id"),
            circuit.get("id"),
            circuit.get("name"),
        ):
            circuit_id = _canonical_assignment_circuit_id(value)
            if circuit_id:
                circuit_index.setdefault(circuit_id, index)
    return circuit_index


def _source_sensor_dict_from_entity_id(entity_id: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "role": _assignment_sensor_role(entity_id).value,
        "leg": _assignment_leg_hint(entity_id),
    }


def _demo_source_bundle_enabled_for_config_entry(
    config_entry: config_entries.ConfigEntry,
) -> bool:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            options.get(CONF_SOURCE_ENTITIES, data.get(CONF_SOURCE_ENTITIES, [])),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
    )
    extra_source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            options.get(
                CONF_EXTRA_SOURCE_ENTITIES,
                data.get(CONF_EXTRA_SOURCE_ENTITIES, source_entities),
            ),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
    )
    mains_source_entities = _normalize_demo_source_entity_ids(
        _strict_string_list(
            options.get(
                CONF_MAINS_SOURCE_ENTITIES,
                data.get(CONF_MAINS_SOURCE_ENTITIES, []),
            ),
            invalid_error_key="invalid_mains_source_entities",
        )
    )
    return _demo_source_bundle_enabled_for_entry_values(
        options,
        data,
        source_entities=source_entities,
        extra_source_entities=extra_source_entities,
        mains_source_entities=mains_source_entities,
    )


def _remove_demo_source_bundle_from_config(
    config: Mapping[str, Any],
    *,
    fallback_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pruned_config = dict(config)
    fallback_config = fallback_config or {}
    for key, invalid_error_key in (
        (CONF_SOURCE_ENTITIES, ERROR_INVALID_SOURCE_ENTITIES),
        (CONF_EXTRA_SOURCE_ENTITIES, ERROR_INVALID_SOURCE_ENTITIES),
        (CONF_MAINS_SOURCE_ENTITIES, "invalid_mains_source_entities"),
    ):
        pruned_config[key] = _without_demo_source_bundle(
            _strict_string_list(
                pruned_config.get(key, []),
                invalid_error_key=invalid_error_key,
            )
        )

    pruned_circuits = _circuits_without_demo_source_bundle(
        pruned_config.get(CONF_CIRCUITS, fallback_config.get(CONF_CIRCUITS, []))
    )
    pruned_config[CONF_CIRCUITS] = pruned_circuits
    circuit_ids = {
        str(circuit.get("circuit_id") or circuit.get("id") or "")
        for circuit in pruned_circuits
    }
    if CONF_KNOWN_LOAD_CIRCUITS in pruned_config:
        pruned_config[CONF_KNOWN_LOAD_CIRCUITS] = [
            circuit_id
            for circuit_id in _strict_string_list(
                pruned_config.get(CONF_KNOWN_LOAD_CIRCUITS, []),
                invalid_error_key="invalid_known_load_circuits",
            )
            if circuit_id in circuit_ids
        ]
    elif CONF_KNOWN_LOAD_CIRCUITS in fallback_config:
        pruned_config[CONF_KNOWN_LOAD_CIRCUITS] = [
            circuit_id
            for circuit_id in _strict_string_list(
                fallback_config.get(CONF_KNOWN_LOAD_CIRCUITS, []),
                invalid_error_key="invalid_known_load_circuits",
            )
            if circuit_id in circuit_ids
        ]
    if CONF_CIRCUIT_ASSIGNMENTS in pruned_config or CONF_CIRCUITS in pruned_config:
        pruned_config[CONF_CIRCUIT_ASSIGNMENTS] = _assignment_text_from_circuits(
            pruned_circuits
        )
    pruned_config[CONF_DEMO_SOURCE_BUNDLE_ENABLED] = False
    return pruned_config


def _circuits_without_demo_source_bundle(
    circuits: Iterable[Any],
) -> list[dict[str, Any]]:
    pruned_circuits: list[dict[str, Any]] = []
    for circuit in circuits:
        if not isinstance(circuit, Mapping):
            continue
        circuit_id = str(circuit.get("circuit_id") or circuit.get("id") or "")
        if circuit_id.startswith("cs_energy_analyzer_demo_"):
            continue

        sensors = [
            dict(sensor)
            for sensor in circuit.get("sensors", ())
            if isinstance(sensor, Mapping)
            and not _is_demo_source_entity_id(str(sensor.get("entity_id") or ""))
        ]
        if not sensors:
            continue

        pruned_circuit = dict(circuit)
        pruned_circuit["sensors"] = sensors
        pruned_circuits.append(pruned_circuit)
    return pruned_circuits


async def _async_save_assignment_edit_and_return_to_picker(
    flow: Any,
    final_config: Mapping[str, Any],
) -> config_entries.ConfigFlowResult:
    """Persist one edited assignment and reopen the assignment picker."""
    saved_config = dict(final_config)
    await _async_save_options_flow_config(flow, saved_config)
    return _start_assignment_review(
        flow,
        saved_config,
        existing_circuits=saved_config.get(CONF_CIRCUITS, []) or [],
        show_picker=True,
        update_existing=True,
    )


async def _async_save_options_flow_config(
    flow: Any,
    options: Mapping[str, Any],
) -> None:
    """Save options during an in-progress options flow when possible."""
    config_entry = getattr(flow, "_config_entry", None)
    if config_entry is None:
        return
    hass = getattr(flow, "hass", None)
    config_entries_manager = getattr(hass, "config_entries", None)
    update_entry = getattr(config_entries_manager, "async_update_entry", None)
    if callable(update_entry):
        update_entry(config_entry, options=dict(options))
        reload_entry = getattr(config_entries_manager, "async_reload", None)
        if callable(reload_entry):
            reload_result = reload_entry(getattr(config_entry, "entry_id", ""))
            if hasattr(reload_result, "__await__"):
                await reload_result
        return
    try:
        config_entry.options = dict(options)
    except AttributeError:
        pass


def _apply_entity_detail_profile_to_existing_entities(
    hass: Any,
    config_entry: config_entries.ConfigEntry,
    detail_level: str,
) -> dict[str, Any]:
    if hass is None:
        return {
            "profile": normalize_entity_detail_level(detail_level),
            "will_enable": 0,
            "will_disable": 0,
            "unchanged": 0,
            "left_user_disabled": 0,
            "total": 0,
        }

    from .binary_sensor import BINARY_SENSOR_ENTITY_TIER_BY_KEY
    from .sensor import SENSOR_ENTITY_TIER_BY_KEY

    entry_id = getattr(config_entry, "entry_id", "")
    sensor_plan = apply_entity_profile_to_registry(
        hass,
        entry_id=entry_id,
        entity_domain="sensor",
        tier_by_unique_id_suffix=SENSOR_ENTITY_TIER_BY_KEY,
        detail_level=detail_level,
    )
    binary_plan = apply_entity_profile_to_registry(
        hass,
        entry_id=entry_id,
        entity_domain="binary_sensor",
        tier_by_unique_id_suffix=BINARY_SENSOR_ENTITY_TIER_BY_KEY,
        detail_level=detail_level,
    )
    return {
        "profile": normalize_entity_detail_level(detail_level),
        "will_enable": int(sensor_plan["will_enable"])
        + int(binary_plan["will_enable"]),
        "will_disable": int(sensor_plan["will_disable"])
        + int(binary_plan["will_disable"]),
        "unchanged": int(sensor_plan["unchanged"]) + int(binary_plan["unchanged"]),
        "left_user_disabled": int(sensor_plan["left_user_disabled"])
        + int(binary_plan["left_user_disabled"]),
        "total": int(sensor_plan["total"]) + int(binary_plan["total"]),
    }


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


def _advanced_circuit_context_from_config(
    config: Mapping[str, Any],
    circuit_id: str,
) -> dict[str, str]:
    for circuit in config.get(CONF_CIRCUITS, []) or []:
        if not isinstance(circuit, Mapping):
            continue
        current_id = str(circuit.get("circuit_id") or circuit.get("id") or "").strip()
        if current_id != circuit_id:
            continue
        return _advanced_circuit_context(
            {
                "circuit_id": current_id,
                "name": str(circuit.get("name") or current_id),
                "appliance_profile": str(
                    circuit.get("appliance_profile")
                    or ApplianceProfile.MOTOR_LOAD.value
                ),
                "mode": str(circuit.get("mode") or CircuitMode.SINGLE_PHASE.value),
                "power_flow": str(
                    circuit.get("power_flow") or PowerFlowMode.LOAD.value
                ),
            }
        )
    if circuit_id == "mains":
        return _advanced_circuit_context(
            {
                "circuit_id": "mains",
                "name": "Mains NILM",
                "appliance_profile": ApplianceProfile.MAINS_NILM.value,
                "mode": CircuitMode.MAINS_NILM.value,
                "power_flow": PowerFlowMode.MAINS_NET.value,
            }
        )
    return _advanced_circuit_context(
        {
            "circuit_id": circuit_id,
            "name": circuit_id,
            "appliance_profile": ApplianceProfile.MOTOR_LOAD.value,
            "mode": CircuitMode.SINGLE_PHASE.value,
            "power_flow": PowerFlowMode.LOAD.value,
        }
    )


def _power_flow_label(value: Any) -> str:
    normalized = _normalize_power_flow(str(value or ""))
    for option in power_flow_options():
        if option.get("value") == normalized:
            return str(option.get("label") or normalized)
    return normalized.replace("_", " ").title()


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
    user_input = _flatten_advanced_settings_input(user_input)
    if bool(user_input.get(FIELD_RESET_ADVANCED_SETTINGS_TO_DEFAULTS, False)):
        return {}
    settings: dict[str, Any] = {}
    preset = normalize_sensitivity(user_input.get(FIELD_PRESET) or DEFAULT_SENSITIVITY)
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
    _set_optional_tou_weekdays(settings, user_input)
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
    _set_optional_bool(settings, user_input, CONF_RAIN_PUMP_CORRELATION_ENABLED)
    _set_optional_bool(settings, user_input, CONF_WATER_FLOW_CORRELATION_ENABLED)
    _set_optional_bool(settings, user_input, CONF_EXPECTS_WATER_FLOW)
    _set_optional_int(settings, user_input, CONF_RAIN_RESPONSE_WINDOW_MINUTES)
    _set_optional_float(settings, user_input, CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT)
    _set_optional_int(settings, user_input, CONF_FLOW_MISMATCH_THRESHOLD_MINUTES)
    _set_optional_string_list(
        settings,
        user_input,
        CONF_LINKED_FLOW_SENSOR_ENTITIES,
        invalid_error_key="invalid_water_flow_sensor_entities",
    )
    _reset_advanced_setting_sections(settings, user_input)
    return settings


def _reset_advanced_setting_sections(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
) -> None:
    for reset_field, setting_keys in _ADVANCED_RESET_SETTING_KEYS.items():
        if not bool(user_input.get(reset_field, False)):
            continue
        for setting_key in setting_keys:
            settings.pop(setting_key, None)


def _flatten_advanced_settings_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in _ADVANCED_SECTION_KEYS and isinstance(value, Mapping):
            flattened.update(value)
            continue
        flattened[str(key)] = value
    return flattened


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


def _tou_weekday_selection(value: Any) -> list[str]:
    selected = _weekday_values(value)
    return selected


def _set_optional_tou_weekdays(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
) -> None:
    if FIELD_TOU_WEEKDAYS not in user_input:
        return
    selected = _weekday_values(user_input.get(FIELD_TOU_WEEKDAYS))
    if selected:
        settings[FIELD_TOU_WEEKDAYS] = ",".join(selected)


def _weekday_values(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: Iterable[Any]
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raise SetupValidationError("invalid_advanced_settings")

    selected: list[str] = []
    for raw_item in raw_items:
        item = str(raw_item).strip()
        if not item:
            continue
        if item not in {"0", "1", "2", "3", "4", "5", "6"}:
            raise SetupValidationError("invalid_advanced_settings")
        if item not in selected:
            selected.append(item)
    return selected


def _set_optional_bool(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    key: str,
) -> None:
    if key in user_input:
        settings[key] = bool(user_input[key])


def _set_optional_string_list(
    settings: dict[str, Any],
    user_input: Mapping[str, Any],
    key: str,
    *,
    invalid_error_key: str,
) -> None:
    if key not in user_input:
        return
    settings[key] = _strict_string_list(
        user_input.get(key, []),
        invalid_error_key=invalid_error_key,
    )


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
