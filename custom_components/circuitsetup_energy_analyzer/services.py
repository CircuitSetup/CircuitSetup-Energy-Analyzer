from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from functools import partial
from typing import Any

from . import notifications
from .const import DOMAIN
from .ux import FRIENDLY_SENSITIVITY_ALIASES

try:
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:

    class HomeAssistantError(Exception):
        """Fallback Home Assistant service error for tests without HA installed."""

try:
    from homeassistant.helpers import entity_registry as er
except ModuleNotFoundError:
    er = None

SERVICE_RELEARN_BASELINE = "relearn_baseline"
SERVICE_PAUSE_ALERTS = "pause_alerts"
SERVICE_ACKNOWLEDGE_ALERT = "acknowledge_alert"
SERVICE_EXPORT_DIAGNOSTICS = "export_diagnostics"
SERVICE_EXPORT_HISTORY_CSV = "export_history_csv"
SERVICE_RUN_MAPPING_CHECKS = "run_mapping_checks"
SERVICE_LABEL_NILM_SIGNATURE = "label_nilm_signature"
SERVICE_IGNORE_NILM_SIGNATURE = "ignore_nilm_signature"
SERVICE_LABEL_NILM_INTERVAL = "label_nilm_interval"
SERVICE_DELETE_NILM_LABEL_INTERVAL = "delete_nilm_label_interval"
SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS = "generate_nilm_sensor_label_intervals"
SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE = "assign_signature_to_appliance"
SERVICE_ASSIGN_SESSION_TO_APPLIANCE = "assign_session_to_appliance"
SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE = "assign_interval_to_appliance"
SERVICE_VALIDATE_NILM_SESSION = "validate_nilm_session"
SERVICE_REJECT_NILM_SESSION = "reject_nilm_session"
SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY = "validate_nilm_assignment_history"
SERVICE_RENAME_NILM_APPLIANCE = "rename_nilm_appliance"
SERVICE_CHANGE_NILM_APPLIANCE_PROFILE = "change_nilm_appliance_profile"
SERVICE_MERGE_NILM_ASSIGNMENTS = "merge_nilm_assignments"
SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT = "publish_nilm_appliance_assignment"
SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT = "unpublish_nilm_appliance_assignment"
SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT = "retire_nilm_appliance_assignment"
SERVICE_SET_CIRCUIT_SENSITIVITY = "set_circuit_sensitivity"
SERVICE_SET_ENERGY_USAGE_SETTINGS = "set_energy_usage_settings"
SERVICE_SET_ENERGY_GOAL_SETTINGS = "set_energy_goal_settings"
SERVICE_SET_ACTIVITY_ALERT_SETTINGS = "set_activity_alert_settings"
SERVICE_SET_BILLING_CYCLE_SETTINGS = "set_billing_cycle_settings"
SERVICE_SET_COST_SETTINGS = "set_cost_settings"
SERVICE_SET_DEMAND_SETTINGS = "set_demand_settings"
SERVICE_SET_CAPACITY_SETTINGS = "set_capacity_settings"
SERVICE_SET_LEG_IMBALANCE_SETTINGS = "set_leg_imbalance_settings"
SERVICE_SET_METRIC_CONSISTENCY_SETTINGS = "set_metric_consistency_settings"
SERVICE_SET_MAINS_BALANCE_SETTINGS = "set_mains_balance_settings"
SERVICE_SET_SOLAR_FLOW_SETTINGS = "set_solar_flow_settings"
SERVICE_SET_STANDBY_SETTINGS = "set_standby_settings"
SERVICE_SET_UTILITY_COMPARISON_SETTINGS = "set_utility_comparison_settings"
SERVICE_START_MAINTENANCE = "start_maintenance"
SERVICE_END_MAINTENANCE = "end_maintenance"
SERVICE_MARK_ALERT_EXPECTED = "mark_alert_expected"
SERVICE_MARK_ALERT_UNHELPFUL = "mark_alert_unhelpful"
SERVICE_MARK_NILM_APPLIANCE_CORRECT = "mark_nilm_appliance_correct"
SERVICE_MARK_NILM_APPLIANCE_WRONG = "mark_nilm_appliance_wrong"
SERVICE_MARK_NILM_SIGNATURE_EXPECTED = "mark_nilm_signature_expected"
SERVICE_MERGE_NILM_SIGNATURES = "merge_nilm_signatures"
SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS = "recalculate_setting_recommendations"
SERVICE_APPLY_SETTING_RECOMMENDATION = "apply_setting_recommendation"
SERVICE_DENY_SETTING_RECOMMENDATION = "deny_setting_recommendation"
SERVICE_DISMISS_SETTING_RECOMMENDATION = "dismiss_setting_recommendation"
SERVICE_UNDO_SETTING_RECOMMENDATION = "undo_setting_recommendation"
SERVICE_RESET_SETTING_RECOMMENDATION = "reset_setting_recommendation"

ATTR_CIRCUIT_ID = "circuit_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_DURATION = "duration"
ATTR_ALERT_ID = "alert_id"
ATTR_SIGNATURE_ID = "signature_id"
ATTR_SIGNATURE_FINGERPRINT = "signature_fingerprint"
ATTR_INTERVAL_ID = "interval_id"
ATTR_SESSION_ID = "session_id"
ATTR_ASSIGNMENT_ID = "assignment_id"
ATTR_LABEL = "label"
ATTR_APPLIANCE_PROFILE = "appliance_profile"
ATTR_START = "start"
ATTR_END = "end"
ATTR_APPLIANCE_ID = "appliance_id"
ATTR_MAINS_ENTITY_ID = "mains_entity_id"
ATTR_GROUND_TRUTH_ENTITY_ID = "ground_truth_entity_id"
ATTR_SOURCE = "source"
ATTR_CONFIDENCE = "confidence"
ATTR_THRESHOLD_W = "threshold_w"
ATTR_PRESET = "preset"
ATTR_WINDOW_DAYS = "window_days"
ATTR_DAILY_SPIKE_RATIO = "daily_spike_ratio"
ATTR_DAILY_GOAL_KWH = "daily_goal_kwh"
ATTR_GOAL_ALERT_RATIO = "goal_alert_ratio"
ATTR_MAX_ACTIVE_MINUTES = "max_active_minutes"
ATTR_MAX_IDLE_MINUTES = "max_idle_minutes"
ATTR_CYCLE_START_DAY = "cycle_start_day"
ATTR_BUDGET_KWH = "budget_kwh"
ATTR_BUDGET_ALERT_RATIO = "budget_alert_ratio"
ATTR_DEFAULT_RATE_PER_KWH = "default_rate_per_kwh"
ATTR_TOU_RATE_PER_KWH = "tou_rate_per_kwh"
ATTR_TOU_START = "tou_start"
ATTR_TOU_END = "tou_end"
ATTR_TOU_WEEKDAYS = "tou_weekdays"
ATTR_TOU_NAME = "tou_name"
ATTR_WINDOW_MINUTES = "window_minutes"
ATTR_DEMAND_LIMIT_W = "demand_limit_w"
ATTR_BREAKER_AMPS = "breaker_amps"
ATTR_WARNING_RATIO = "warning_ratio"
ATTR_MINIMUM_TOTAL_POWER_W = "minimum_total_power_w"
ATTR_APPARENT_POWER_TOLERANCE_PERCENT = "apparent_power_tolerance_percent"
ATTR_POWER_FACTOR_TOLERANCE = "power_factor_tolerance"
ATTR_MINIMUM_APPARENT_POWER_VA = "minimum_apparent_power_va"
ATTR_NEGATIVE_TOLERANCE_W = "negative_tolerance_w"
ATTR_EXPORT_TOLERANCE_W = "export_tolerance_w"
ATTR_SOLAR_SURPLUS_THRESHOLD_W = "solar_surplus_threshold_w"
ATTR_HIGH_SOLAR_SURPLUS_THRESHOLD_W = "high_solar_surplus_threshold_w"
ATTR_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W = "flexible_load_running_threshold_w"
ATTR_WINDOW_HOURS = "window_hours"
ATTR_STANDBY_THRESHOLD_W = "standby_threshold_w"
ATTR_ALWAYS_ON_ALERT_W = "always_on_alert_w"
ATTR_UTILITY_ENERGY_ENTITY = "utility_energy_entity"
ATTR_UTILITY_STATISTIC_ID = "utility_statistic_id"
ATTR_UTILITY_SOURCE_TYPE = "utility_source_type"
ATTR_UTILITY_STATISTIC_PERIOD = "utility_statistic_period"
ATTR_MEASURED_ENERGY_ENTITIES = "measured_energy_entities"
ATTR_TOLERANCE_PERCENT = "tolerance_percent"
ATTR_NOTE = "note"
ATTR_RELEARN = "relearn"
ATTR_RELEARN_ON_END = "relearn_on_end"
ATTR_SOURCE_SIGNATURE_ID = "source_signature_id"
ATTR_TARGET_SIGNATURE_ID = "target_signature_id"
ATTR_SOURCE_ASSIGNMENT_ID = "source_assignment_id"
ATTR_TARGET_ASSIGNMENT_ID = "target_assignment_id"
ATTR_RECOMMENDATION_ID = "recommendation_id"
ATTR_ENTRY_ID = "entry_id"

_SERVICES_KEY = "_services_setup"
_SENSITIVITY_SERVICE_OPTIONS = ("quiet", "balanced", "sensitive")


class _FallbackSchema:
    def __init__(
        self,
        required: tuple[str, ...] = (),
        optional: tuple[str, ...] = (),
    ) -> None:
        self.required = required
        self.optional = optional

    def __call__(self, data: Mapping[str, Any] | None) -> dict[str, Any]:
        values = dict(data or {})
        missing = [field for field in self.required if field not in values]
        if missing:
            raise ValueError(f"Missing required field: {', '.join(missing)}")
        return values


def _schema(required: tuple[str, ...] = (), optional: tuple[str, ...] = ()) -> Callable:
    try:
        import voluptuous as vol
    except ModuleNotFoundError:
        return _FallbackSchema(required, optional)

    fields: dict[Any, Any] = {}
    for field in required:
        fields[vol.Required(field)] = str
    for field in optional:
        fields[vol.Optional(field)] = object
    return vol.Schema(fields, extra=vol.ALLOW_EXTRA)


def _circuit_schema(*optional: str) -> Callable:
    return _schema(optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID, *optional))


CIRCUIT_SERVICE_SCHEMA = _circuit_schema()
SENSITIVITY_SERVICE_SCHEMA = _schema(
    required=(ATTR_PRESET,),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
ENERGY_USAGE_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_WINDOW_DAYS,
        ATTR_DAILY_SPIKE_RATIO,
    ),
)
ENERGY_GOAL_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_DAILY_GOAL_KWH,
        ATTR_GOAL_ALERT_RATIO,
    ),
)
ACTIVITY_ALERT_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_MAX_ACTIVE_MINUTES,
        ATTR_MAX_IDLE_MINUTES,
    ),
)
BILLING_CYCLE_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_CYCLE_START_DAY,
        ATTR_BUDGET_KWH,
        ATTR_BUDGET_ALERT_RATIO,
    ),
)
COST_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_CYCLE_START_DAY,
        ATTR_DEFAULT_RATE_PER_KWH,
        ATTR_TOU_RATE_PER_KWH,
        ATTR_TOU_START,
        ATTR_TOU_END,
        ATTR_TOU_WEEKDAYS,
        ATTR_TOU_NAME,
    ),
)
DEMAND_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_WINDOW_MINUTES,
        ATTR_DEMAND_LIMIT_W,
    ),
)
CAPACITY_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_BREAKER_AMPS,
        ATTR_WARNING_RATIO,
    ),
)
LEG_IMBALANCE_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_WARNING_RATIO,
        ATTR_MINIMUM_TOTAL_POWER_W,
    ),
)
METRIC_CONSISTENCY_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_APPARENT_POWER_TOLERANCE_PERCENT,
        ATTR_POWER_FACTOR_TOLERANCE,
        ATTR_MINIMUM_APPARENT_POWER_VA,
    ),
)
MAINS_BALANCE_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID, ATTR_NEGATIVE_TOLERANCE_W),
)
SOLAR_FLOW_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_EXPORT_TOLERANCE_W,
        ATTR_SOLAR_SURPLUS_THRESHOLD_W,
        ATTR_HIGH_SOLAR_SURPLUS_THRESHOLD_W,
        ATTR_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    ),
)
STANDBY_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_WINDOW_HOURS,
        ATTR_STANDBY_THRESHOLD_W,
        ATTR_ALWAYS_ON_ALERT_W,
    ),
)
UTILITY_COMPARISON_SETTINGS_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_UTILITY_ENERGY_ENTITY,
        ATTR_UTILITY_STATISTIC_ID,
        ATTR_UTILITY_SOURCE_TYPE,
        ATTR_UTILITY_STATISTIC_PERIOD,
        ATTR_MEASURED_ENERGY_ENTITIES,
        ATTR_TOLERANCE_PERCENT,
    ),
)
MAINTENANCE_START_SERVICE_SCHEMA = _schema(
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_NOTE,
        ATTR_DURATION,
        ATTR_RELEARN_ON_END,
    ),
)
MAINTENANCE_END_SERVICE_SCHEMA = _schema(
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID, ATTR_RELEARN),
)
ALERT_FEEDBACK_SERVICE_SCHEMA = _schema(optional=(ATTR_ALERT_ID, ATTR_ENTITY_ID))
NILM_LABEL_SERVICE_SCHEMA = _schema(
    required=(ATTR_SIGNATURE_ID, ATTR_LABEL),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_LABEL_INTERVAL_SERVICE_SCHEMA = _schema(
    required=(ATTR_LABEL, ATTR_START, ATTR_END),
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_INTERVAL_ID,
        ATTR_APPLIANCE_ID,
        ATTR_MAINS_ENTITY_ID,
        ATTR_GROUND_TRUTH_ENTITY_ID,
        ATTR_SOURCE,
        ATTR_CONFIDENCE,
    ),
)
NILM_DELETE_LABEL_INTERVAL_SERVICE_SCHEMA = _schema(
    required=(ATTR_INTERVAL_ID,),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA = _schema(
    required=(ATTR_LABEL, ATTR_START, ATTR_END, ATTR_GROUND_TRUTH_ENTITY_ID),
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_APPLIANCE_ID,
        ATTR_MAINS_ENTITY_ID,
        ATTR_THRESHOLD_W,
        ATTR_CONFIDENCE,
    ),
)
NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA = _schema(
    required=(ATTR_SIGNATURE_ID, ATTR_LABEL),
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_ASSIGNMENT_ID,
        ATTR_APPLIANCE_ID,
        ATTR_APPLIANCE_PROFILE,
    ),
)
NILM_ASSIGN_SESSION_SERVICE_SCHEMA = _schema(
    required=(ATTR_SESSION_ID, ATTR_LABEL),
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_ASSIGNMENT_ID,
        ATTR_SIGNATURE_FINGERPRINT,
        ATTR_APPLIANCE_ID,
        ATTR_APPLIANCE_PROFILE,
    ),
)
NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA = _schema(
    required=(ATTR_INTERVAL_ID, ATTR_LABEL),
    optional=(
        ATTR_CIRCUIT_ID,
        ATTR_ENTITY_ID,
        ATTR_ASSIGNMENT_ID,
        ATTR_APPLIANCE_ID,
        ATTR_APPLIANCE_PROFILE,
    ),
)
NILM_SESSION_VALIDATION_SERVICE_SCHEMA = _schema(
    required=(ATTR_SESSION_ID,),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID, ATTR_ASSIGNMENT_ID),
)
NILM_RENAME_APPLIANCE_SERVICE_SCHEMA = _schema(
    required=(ATTR_ASSIGNMENT_ID, ATTR_LABEL),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_CHANGE_APPLIANCE_PROFILE_SERVICE_SCHEMA = _schema(
    required=(ATTR_ASSIGNMENT_ID, ATTR_APPLIANCE_PROFILE),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_MERGE_ASSIGNMENTS_SERVICE_SCHEMA = _schema(
    required=(ATTR_SOURCE_ASSIGNMENT_ID, ATTR_TARGET_ASSIGNMENT_ID),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA = _schema(
    required=(ATTR_ASSIGNMENT_ID,),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_SIGNATURE_SERVICE_SCHEMA = _schema(
    required=(ATTR_SIGNATURE_ID,),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
NILM_MERGE_SERVICE_SCHEMA = _schema(
    required=(ATTR_SOURCE_SIGNATURE_ID, ATTR_TARGET_SIGNATURE_ID),
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)
RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA = _schema(
    optional=(ATTR_CIRCUIT_ID, ATTR_ENTITY_ID),
)


def _recommendation_action_schema() -> Callable:
    base_schema = _schema(
        optional=(ATTR_RECOMMENDATION_ID, ATTR_ENTRY_ID, ATTR_ENTITY_ID),
    )

    def validate(data: Mapping[str, Any] | None) -> dict[str, Any]:
        values = base_schema(data)
        if values.get(ATTR_RECOMMENDATION_ID) or values.get(ATTR_ENTITY_ID):
            return values
        try:
            import voluptuous as vol
        except ModuleNotFoundError as err:
            raise ValueError(
                "Missing recommendation_id or entity_id.",
            ) from err
        raise vol.Invalid("Missing recommendation_id or entity_id.")

    return validate


RECOMMENDATION_ACTION_SERVICE_SCHEMA = _recommendation_action_schema()

_SERVICE_SCHEMAS: dict[str, Callable | None] = {
    SERVICE_RELEARN_BASELINE: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_PAUSE_ALERTS: _circuit_schema(ATTR_DURATION),
    SERVICE_ACKNOWLEDGE_ALERT: ALERT_FEEDBACK_SERVICE_SCHEMA,
    SERVICE_EXPORT_DIAGNOSTICS: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_EXPORT_HISTORY_CSV: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_RUN_MAPPING_CHECKS: None,
    SERVICE_LABEL_NILM_SIGNATURE: NILM_LABEL_SERVICE_SCHEMA,
    SERVICE_IGNORE_NILM_SIGNATURE: NILM_SIGNATURE_SERVICE_SCHEMA,
    SERVICE_LABEL_NILM_INTERVAL: NILM_LABEL_INTERVAL_SERVICE_SCHEMA,
    SERVICE_DELETE_NILM_LABEL_INTERVAL: NILM_DELETE_LABEL_INTERVAL_SERVICE_SCHEMA,
    SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS: (
        NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA
    ),
    SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE: NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA,
    SERVICE_ASSIGN_SESSION_TO_APPLIANCE: NILM_ASSIGN_SESSION_SERVICE_SCHEMA,
    SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE: NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA,
    SERVICE_VALIDATE_NILM_SESSION: NILM_SESSION_VALIDATION_SERVICE_SCHEMA,
    SERVICE_REJECT_NILM_SESSION: NILM_SESSION_VALIDATION_SERVICE_SCHEMA,
    SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY: NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA,
    SERVICE_RENAME_NILM_APPLIANCE: NILM_RENAME_APPLIANCE_SERVICE_SCHEMA,
    SERVICE_CHANGE_NILM_APPLIANCE_PROFILE: (
        NILM_CHANGE_APPLIANCE_PROFILE_SERVICE_SCHEMA
    ),
    SERVICE_MERGE_NILM_ASSIGNMENTS: NILM_MERGE_ASSIGNMENTS_SERVICE_SCHEMA,
    SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT: (
        NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA
    ),
    SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT: (
        NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA
    ),
    SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT: (
        NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA
    ),
    SERVICE_SET_CIRCUIT_SENSITIVITY: SENSITIVITY_SERVICE_SCHEMA,
    SERVICE_SET_ENERGY_USAGE_SETTINGS: ENERGY_USAGE_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_ENERGY_GOAL_SETTINGS: ENERGY_GOAL_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_ACTIVITY_ALERT_SETTINGS: ACTIVITY_ALERT_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_BILLING_CYCLE_SETTINGS: BILLING_CYCLE_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_COST_SETTINGS: COST_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_DEMAND_SETTINGS: DEMAND_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_CAPACITY_SETTINGS: CAPACITY_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_LEG_IMBALANCE_SETTINGS: LEG_IMBALANCE_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_METRIC_CONSISTENCY_SETTINGS: (
        METRIC_CONSISTENCY_SETTINGS_SERVICE_SCHEMA
    ),
    SERVICE_SET_MAINS_BALANCE_SETTINGS: MAINS_BALANCE_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_SOLAR_FLOW_SETTINGS: SOLAR_FLOW_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_STANDBY_SETTINGS: STANDBY_SETTINGS_SERVICE_SCHEMA,
    SERVICE_SET_UTILITY_COMPARISON_SETTINGS: (
        UTILITY_COMPARISON_SETTINGS_SERVICE_SCHEMA
    ),
    SERVICE_START_MAINTENANCE: MAINTENANCE_START_SERVICE_SCHEMA,
    SERVICE_END_MAINTENANCE: MAINTENANCE_END_SERVICE_SCHEMA,
    SERVICE_MARK_ALERT_EXPECTED: ALERT_FEEDBACK_SERVICE_SCHEMA,
    SERVICE_MARK_ALERT_UNHELPFUL: ALERT_FEEDBACK_SERVICE_SCHEMA,
    SERVICE_MARK_NILM_APPLIANCE_CORRECT: ALERT_FEEDBACK_SERVICE_SCHEMA,
    SERVICE_MARK_NILM_APPLIANCE_WRONG: ALERT_FEEDBACK_SERVICE_SCHEMA,
    SERVICE_MARK_NILM_SIGNATURE_EXPECTED: NILM_SIGNATURE_SERVICE_SCHEMA,
    SERVICE_MERGE_NILM_SIGNATURES: NILM_MERGE_SERVICE_SCHEMA,
    SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS: (
        RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA
    ),
    SERVICE_APPLY_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_DENY_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_DISMISS_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_UNDO_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_RESET_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
}


async def async_setup_services(hass: Any) -> None:
    """Register integration services when a HA-like service registry is present."""
    services = getattr(hass, "services", None)
    register = getattr(services, "async_register", None)
    if register is None:
        return
    if not hasattr(hass, "data"):
        hass.data = {}
    if hass.data.get(DOMAIN, {}).get(_SERVICES_KEY) is True:
        return

    for service, schema in _SERVICE_SCHEMAS.items():
        register(DOMAIN, service, _service_handler(hass, service), schema=schema)

    hass.data.setdefault(DOMAIN, {})[_SERVICES_KEY] = True


async def async_unload_services(hass: Any) -> None:
    """Remove registered integration services."""
    services = getattr(hass, "services", None)
    remove = getattr(services, "async_remove", None)
    if remove is None:
        return

    for service in _SERVICE_SCHEMAS:
        remove(DOMAIN, service)

    domain_data = getattr(hass, "data", {}).get(DOMAIN)
    if isinstance(domain_data, dict):
        domain_data.pop(_SERVICES_KEY, None)


def _service_handler(hass: Any, service: str) -> Callable[[Any], Any]:
    async def handler(call: Any) -> None:
        data = dict(getattr(call, "data", {}) or {})
        await _dispatch_service(hass, service, data)
        bus = getattr(hass, "bus", None)
        fire = getattr(bus, "async_fire", None)
        if fire is None:
            return
        fire(f"{DOMAIN}_{service}", data)

    return handler


async def _dispatch_service(hass: Any, service: str, data: dict[str, Any]) -> None:
    if service == SERVICE_RUN_MAPPING_CHECKS:
        for coordinator in _loaded_coordinators(hass):
            await _call_if_present(coordinator, "async_run_mapping_checks")
        return

    if service == SERVICE_ACKNOWLEDGE_ALERT:
        await _dispatch_alert_id_action(
            hass,
            data,
            method_name="async_acknowledge_alert",
        )
        return

    if service == SERVICE_MARK_ALERT_EXPECTED:
        await _dispatch_alert_id_action(
            hass,
            data,
            method_name="async_mark_alert_expected",
        )
        return

    if service == SERVICE_MARK_ALERT_UNHELPFUL:
        await _dispatch_alert_id_action(
            hass,
            data,
            method_name="async_mark_alert_unhelpful",
        )
        return

    if service == SERVICE_MARK_NILM_APPLIANCE_CORRECT:
        await _dispatch_alert_id_action(
            hass,
            data,
            method_name="async_mark_nilm_appliance_correct",
        )
        return

    if service == SERVICE_MARK_NILM_APPLIANCE_WRONG:
        await _dispatch_alert_id_action(
            hass,
            data,
            method_name="async_mark_nilm_appliance_wrong",
        )
        return

    if service == SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS:
        circuit_id = _service_circuit_id(hass, data, required=False)
        coordinators = (
            _target_coordinators(hass, circuit_id)
            if circuit_id is not None
            else _loaded_coordinators(hass)
        )
        for coordinator in coordinators:
            await _call_if_present(
                coordinator,
                "async_recalculate_setting_recommendations",
                circuit_id,
            )
        return

    if service == SERVICE_APPLY_SETTING_RECOMMENDATION:
        recommendation_id = _service_recommendation_id(hass, data)
        for coordinator in _target_recommendation_coordinators(
            hass,
            recommendation_id,
            data.get(ATTR_ENTRY_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_apply_setting_recommendation",
                recommendation_id,
            )
        return

    if service == SERVICE_DENY_SETTING_RECOMMENDATION:
        recommendation_id = _service_recommendation_id(hass, data)
        for coordinator in _target_recommendation_coordinators(
            hass,
            recommendation_id,
            data.get(ATTR_ENTRY_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_deny_setting_recommendation",
                recommendation_id,
            )
        return

    if service == SERVICE_DISMISS_SETTING_RECOMMENDATION:
        recommendation_id = _service_recommendation_id(hass, data)
        for coordinator in _target_recommendation_coordinators(
            hass,
            recommendation_id,
            data.get(ATTR_ENTRY_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_dismiss_setting_recommendation",
                recommendation_id,
            )
        return

    if service == SERVICE_UNDO_SETTING_RECOMMENDATION:
        recommendation_id = _service_recommendation_id(hass, data)
        handled = False
        for coordinator in _target_recommendation_coordinators(
            hass,
            recommendation_id,
            data.get(ATTR_ENTRY_ID),
        ):
            result = await _call_if_present(
                coordinator,
                "async_undo_setting_recommendation",
                recommendation_id,
            )
            handled = handled or result is True
        if not handled:
            raise HomeAssistantError(
                f"Recommendation '{recommendation_id}' could not be changed. "
                "Refresh the evidence panel and try again."
            )
        return

    if service == SERVICE_RESET_SETTING_RECOMMENDATION:
        recommendation_id = _service_recommendation_id(hass, data)
        handled = False
        for coordinator in _target_recommendation_coordinators(
            hass,
            recommendation_id,
            data.get(ATTR_ENTRY_ID),
        ):
            result = await _call_if_present(
                coordinator,
                "async_reset_setting_recommendation",
                recommendation_id,
            )
            handled = handled or result is True
        if not handled:
            raise HomeAssistantError(
                f"Recommendation '{recommendation_id}' could not be changed. "
                "Refresh the evidence panel and try again."
            )
        return

    if service == SERVICE_LABEL_NILM_SIGNATURE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_signature_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_SIGNATURE_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_label_nilm_signature",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
                data.get(ATTR_LABEL),
            )
        return

    if service == SERVICE_IGNORE_NILM_SIGNATURE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_signature_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_SIGNATURE_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_ignore_nilm_signature",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
        )
        return

    if service == SERVICE_LABEL_NILM_INTERVAL:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_label_nilm_interval",
                circuit_id,
                label=data.get(ATTR_LABEL),
                start=data.get(ATTR_START),
                end=data.get(ATTR_END),
                appliance_id=data.get(ATTR_APPLIANCE_ID),
                mains_entity_id=data.get(ATTR_MAINS_ENTITY_ID),
                ground_truth_entity_id=data.get(ATTR_GROUND_TRUTH_ENTITY_ID),
                interval_id=data.get(ATTR_INTERVAL_ID),
                source=data.get(ATTR_SOURCE, "manual"),
                confidence=data.get(ATTR_CONFIDENCE, 1.0),
            )
        return

    if service == SERVICE_DELETE_NILM_LABEL_INTERVAL:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_delete_nilm_label_interval",
                circuit_id,
                data.get(ATTR_INTERVAL_ID),
        )
        return

    if service == SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS:
        circuit_id = _service_circuit_id(hass, data)
        start_dt = _service_datetime(data.get(ATTR_START), ATTR_START)
        end_dt = _service_datetime(data.get(ATTR_END), ATTR_END)
        if end_dt <= start_dt:
            raise HomeAssistantError("NILM sensor label end must be after start")
        ground_truth_entity_id = str(
            data.get(ATTR_GROUND_TRUTH_ENTITY_ID) or ""
        ).strip()
        rows = await _async_nilm_sensor_history_rows(
            hass,
            ground_truth_entity_id,
            start_dt,
            end_dt,
        )
        intervals = _nilm_sensor_label_intervals_from_history(
            rows,
            ground_truth_entity_id,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            threshold_w=data.get(ATTR_THRESHOLD_W, 0.0),
        )
        if not intervals:
            raise HomeAssistantError(
                "No active ground-truth sensor intervals were found."
            )
        for coordinator in _target_coordinators(hass, circuit_id):
            for interval in intervals:
                await _call_if_present(
                    coordinator,
                    "async_label_nilm_interval",
                    circuit_id,
                    label=data.get(ATTR_LABEL),
                    start=interval[ATTR_START],
                    end=interval[ATTR_END],
                    appliance_id=data.get(ATTR_APPLIANCE_ID),
                    mains_entity_id=data.get(ATTR_MAINS_ENTITY_ID),
                    ground_truth_entity_id=ground_truth_entity_id,
                    source="sensor",
                    confidence=data.get(ATTR_CONFIDENCE, 1.0),
                )
        return

    if service == SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_signature_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_SIGNATURE_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_assign_nilm_signature",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
                label=data.get(ATTR_LABEL),
                appliance_id=data.get(ATTR_APPLIANCE_ID),
                appliance_profile=data.get(ATTR_APPLIANCE_PROFILE),
                assignment_id=data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_ASSIGN_SESSION_TO_APPLIANCE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_assign_nilm_session",
                circuit_id,
                data.get(ATTR_SESSION_ID),
                label=data.get(ATTR_LABEL),
                signature_fingerprint=data.get(ATTR_SIGNATURE_FINGERPRINT),
                appliance_id=data.get(ATTR_APPLIANCE_ID),
                appliance_profile=data.get(ATTR_APPLIANCE_PROFILE),
                assignment_id=data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_interval_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_INTERVAL_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_assign_nilm_interval",
                circuit_id,
                data.get(ATTR_INTERVAL_ID),
                label=data.get(ATTR_LABEL),
                appliance_id=data.get(ATTR_APPLIANCE_ID),
                appliance_profile=data.get(ATTR_APPLIANCE_PROFILE),
                assignment_id=data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_VALIDATE_NILM_SESSION:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_validate_nilm_session",
                circuit_id,
                data.get(ATTR_SESSION_ID),
                assignment_id=data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_REJECT_NILM_SESSION:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_reject_nilm_session",
                circuit_id,
                data.get(ATTR_SESSION_ID),
                assignment_id=data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_validate_nilm_assignment_history",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_RENAME_NILM_APPLIANCE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_rename_nilm_appliance",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
                label=data.get(ATTR_LABEL),
            )
        return

    if service == SERVICE_CHANGE_NILM_APPLIANCE_PROFILE:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_change_nilm_appliance_profile",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
                appliance_profile=data.get(ATTR_APPLIANCE_PROFILE),
            )
        return

    if service == SERVICE_MERGE_NILM_ASSIGNMENTS:
        source_assignment_id = str(data.get(ATTR_SOURCE_ASSIGNMENT_ID) or "").strip()
        target_assignment_id = str(data.get(ATTR_TARGET_ASSIGNMENT_ID) or "").strip()
        if source_assignment_id == target_assignment_id:
            raise HomeAssistantError(
                "source_assignment_id and target_assignment_id must be different"
            )
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_merge_nilm_assignments",
                circuit_id,
                source_assignment_id,
                target_assignment_id,
            )
        return

    if service == SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_publish_nilm_appliance_assignment",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_unpublish_nilm_appliance_assignment",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_coordinators(hass, circuit_id):
            await _call_if_present(
                coordinator,
                "async_retire_nilm_appliance_assignment",
                circuit_id,
                data.get(ATTR_ASSIGNMENT_ID),
            )
        return

    if service == SERVICE_MARK_NILM_SIGNATURE_EXPECTED:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_signature_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_SIGNATURE_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_mark_nilm_signature_expected",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
            )
        return

    if service == SERVICE_MERGE_NILM_SIGNATURES:
        circuit_id = _service_circuit_id(hass, data)
        for coordinator in _target_nilm_signature_coordinators(
            hass,
            circuit_id,
            data.get(ATTR_SOURCE_SIGNATURE_ID),
            data.get(ATTR_TARGET_SIGNATURE_ID),
        ):
            await _call_if_present(
                coordinator,
                "async_merge_nilm_signatures",
                circuit_id,
                data.get(ATTR_SOURCE_SIGNATURE_ID),
                data.get(ATTR_TARGET_SIGNATURE_ID),
            )
        return

    circuit_id = _service_circuit_id(hass, data)
    for coordinator in _target_coordinators(hass, circuit_id):
        if service == SERVICE_RELEARN_BASELINE:
            await _call_if_present(coordinator, "async_relearn_baseline", circuit_id)
        elif service == SERVICE_PAUSE_ALERTS:
            await _call_if_present(
                coordinator,
                "async_pause_alerts",
                circuit_id,
                data.get(ATTR_DURATION),
            )
        elif service == SERVICE_EXPORT_DIAGNOSTICS:
            await _call_if_present(coordinator, "async_export_diagnostics", circuit_id)
        elif service == SERVICE_EXPORT_HISTORY_CSV:
            await _call_if_present(coordinator, "async_export_history_csv", circuit_id)
        elif service == SERVICE_SET_CIRCUIT_SENSITIVITY:
            await _call_if_present(
                coordinator,
                "async_set_circuit_sensitivity",
                circuit_id,
                _service_sensitivity_preset(data.get(ATTR_PRESET)),
            )
        elif service == SERVICE_SET_ENERGY_USAGE_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_energy_usage_settings",
                circuit_id,
                data.get(ATTR_WINDOW_DAYS),
                data.get(ATTR_DAILY_SPIKE_RATIO),
            )
        elif service == SERVICE_SET_ENERGY_GOAL_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_energy_goal_settings",
                circuit_id,
                data.get(ATTR_DAILY_GOAL_KWH),
                data.get(ATTR_GOAL_ALERT_RATIO),
            )
        elif service == SERVICE_SET_DEMAND_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_demand_settings",
                circuit_id,
                data.get(ATTR_WINDOW_MINUTES),
                data.get(ATTR_DEMAND_LIMIT_W),
            )
        elif service == SERVICE_SET_CAPACITY_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_capacity_settings",
                circuit_id,
                data.get(ATTR_BREAKER_AMPS),
                data.get(ATTR_WARNING_RATIO),
            )
        elif service == SERVICE_SET_LEG_IMBALANCE_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_leg_imbalance_settings",
                circuit_id,
                data.get(ATTR_WARNING_RATIO),
                data.get(ATTR_MINIMUM_TOTAL_POWER_W),
            )
        elif service == SERVICE_SET_METRIC_CONSISTENCY_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_metric_consistency_settings",
                circuit_id,
                data.get(ATTR_APPARENT_POWER_TOLERANCE_PERCENT),
                data.get(ATTR_POWER_FACTOR_TOLERANCE),
                data.get(ATTR_MINIMUM_APPARENT_POWER_VA),
            )
        elif service == SERVICE_SET_MAINS_BALANCE_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_mains_balance_settings",
                circuit_id,
                data.get(ATTR_NEGATIVE_TOLERANCE_W),
            )
        elif service == SERVICE_SET_SOLAR_FLOW_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_solar_flow_settings",
                circuit_id,
                data.get(ATTR_EXPORT_TOLERANCE_W),
                data.get(ATTR_SOLAR_SURPLUS_THRESHOLD_W),
                data.get(ATTR_HIGH_SOLAR_SURPLUS_THRESHOLD_W),
                data.get(ATTR_FLEXIBLE_LOAD_RUNNING_THRESHOLD_W),
            )
        elif service == SERVICE_SET_ACTIVITY_ALERT_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_activity_alert_settings",
                circuit_id,
                data.get(ATTR_MAX_ACTIVE_MINUTES),
                data.get(ATTR_MAX_IDLE_MINUTES),
            )
        elif service == SERVICE_SET_BILLING_CYCLE_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_billing_cycle_settings",
                circuit_id,
                data.get(ATTR_CYCLE_START_DAY),
                data.get(ATTR_BUDGET_KWH),
                data.get(ATTR_BUDGET_ALERT_RATIO),
            )
        elif service == SERVICE_SET_COST_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_cost_settings",
                circuit_id,
                data.get(ATTR_CYCLE_START_DAY),
                data.get(ATTR_DEFAULT_RATE_PER_KWH),
                data.get(ATTR_TOU_RATE_PER_KWH),
                data.get(ATTR_TOU_START),
                data.get(ATTR_TOU_END),
                data.get(ATTR_TOU_WEEKDAYS),
                data.get(ATTR_TOU_NAME),
            )
        elif service == SERVICE_SET_STANDBY_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_standby_settings",
                circuit_id,
                data.get(ATTR_WINDOW_HOURS),
                data.get(ATTR_STANDBY_THRESHOLD_W),
                data.get(ATTR_ALWAYS_ON_ALERT_W),
            )
        elif service == SERVICE_SET_UTILITY_COMPARISON_SETTINGS:
            await _call_if_present(
                coordinator,
                "async_set_utility_comparison_settings",
                circuit_id,
                data.get(ATTR_UTILITY_ENERGY_ENTITY),
                data.get(ATTR_MEASURED_ENERGY_ENTITIES),
                data.get(ATTR_TOLERANCE_PERCENT),
                data.get(ATTR_UTILITY_STATISTIC_ID),
                data.get(ATTR_UTILITY_SOURCE_TYPE),
                data.get(ATTR_UTILITY_STATISTIC_PERIOD),
            )
        elif service == SERVICE_START_MAINTENANCE:
            await _call_if_present(
                coordinator,
                "async_start_maintenance",
                circuit_id,
                data.get(ATTR_NOTE, ""),
                data.get(ATTR_DURATION),
                data.get(ATTR_RELEARN_ON_END, False),
            )
        elif service == SERVICE_END_MAINTENANCE:
            await _call_if_present(
                coordinator,
                "async_end_maintenance",
                circuit_id,
                data.get(ATTR_RELEARN, False),
            )


def _service_circuit_id(
    hass: Any,
    data: Mapping[str, Any],
    *,
    required: bool = True,
) -> str | None:
    circuit_id = data.get(ATTR_CIRCUIT_ID)
    normalized_circuit_id = None
    if isinstance(circuit_id, str):
        normalized = circuit_id.strip()
        if normalized:
            normalized_circuit_id = normalized

    entity_ids = _service_entity_ids(data)
    if entity_ids:
        entity_circuit_id = _circuit_id_from_service_entity_ids(hass, entity_ids)
        if (
            normalized_circuit_id is not None
            and normalized_circuit_id != entity_circuit_id
        ):
            raise HomeAssistantError(
                f"circuit_id '{normalized_circuit_id}' does not match "
                f"entity_id target circuit '{entity_circuit_id}'."
            )
        return entity_circuit_id

    if normalized_circuit_id is not None:
        return normalized_circuit_id

    if required:
        raise HomeAssistantError("Missing circuit_id.")
    return None


def _service_sensitivity_preset(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in FRIENDLY_SENSITIVITY_ALIASES:
        return FRIENDLY_SENSITIVITY_ALIASES[normalized]

    choices = ", ".join(_SENSITIVITY_SERVICE_OPTIONS)
    raise HomeAssistantError(
        f"Cannot set alert sensitivity to {value!r}. Choose one of: {choices}."
    )


def _service_entity_ids(data: Mapping[str, Any]) -> tuple[str, ...]:
    entity_id = data.get(ATTR_ENTITY_ID)
    if isinstance(entity_id, str):
        normalized = entity_id.strip()
        return (normalized,) if normalized else ()
    if isinstance(entity_id, Iterable) and not isinstance(entity_id, (str, bytes)):
        values = [
            str(value).strip()
            for value in entity_id
            if str(value).strip()
        ]
        return tuple(dict.fromkeys(values))
    return ()


def _circuit_id_from_service_entity_ids(hass: Any, entity_ids: Iterable[str]) -> str:
    resolved_circuit_ids = {
        _circuit_id_from_analyzer_entity_id(hass, entity_id)
        for entity_id in entity_ids
    }
    if len(resolved_circuit_ids) == 1:
        return next(iter(resolved_circuit_ids))
    if resolved_circuit_ids:
        ordered = ", ".join(sorted(resolved_circuit_ids))
        raise HomeAssistantError(
            "entity_id target resolved to multiple circuits: "
            f"{ordered}. Pass circuit_id explicitly."
        )
    raise HomeAssistantError("Missing circuit_id.")


def _circuit_id_from_analyzer_entity_id(hass: Any, entity_id: str) -> str:
    registry_circuit_id = _circuit_id_from_entity_registry(hass, entity_id)
    if registry_circuit_id is not None:
        return registry_circuit_id

    object_id = str(entity_id).strip().split(".", 1)[-1]
    if not object_id:
        raise HomeAssistantError(
            f"Could not derive circuit_id from entity_id '{entity_id}'."
        )

    known_suffixes = _known_analyzer_entity_suffixes()
    matches: list[str] = []
    for circuit_id in sorted(
        _all_known_circuit_ids(hass),
        key=lambda value: (-len(value), value),
    ):
        prefix = f"{circuit_id}_"
        if not object_id.startswith(prefix):
            continue
        suffix = object_id[len(prefix) :]
        if suffix in known_suffixes:
            matches.append(circuit_id)

    if len(matches) == 1:
        return matches[0]
    raise HomeAssistantError(
        f"Could not derive circuit_id from entity_id '{entity_id}'."
    )


def _circuit_id_from_entity_registry(hass: Any, entity_id: str) -> str | None:
    if er is None:
        return None
    async_get = getattr(er, "async_get", None)
    if async_get is None:
        return None
    try:
        registry = async_get(hass)
    except TypeError:
        return None
    entry = getattr(registry, "async_get", lambda _entity_id: None)(entity_id)
    if entry is None or getattr(entry, "platform", None) != DOMAIN:
        return None

    unique_id = str(getattr(entry, "unique_id", "") or "")
    return _circuit_id_from_unique_id(unique_id)


def _circuit_id_from_unique_id(unique_id: str) -> str | None:
    known_suffixes = _known_analyzer_entity_suffixes()
    for suffix in sorted(known_suffixes, key=len, reverse=True):
        marker = f"_{suffix}"
        if unique_id.endswith(marker):
            entry_and_circuit = unique_id[: -len(marker)]
            _entry_id, separator, circuit_id = entry_and_circuit.partition("_")
            if separator and circuit_id:
                return circuit_id
    return None


def _all_known_circuit_ids(hass: Any) -> set[str]:
    return {
        known_circuit_id
        for coordinator in _loaded_coordinators(hass)
        for known_circuit_id in _known_circuit_ids(coordinator)
    }


def _known_analyzer_entity_suffixes() -> set[str]:
    from .binary_sensor import BINARY_SENSOR_ENTITY_TIER_BY_KEY
    from .button import CIRCUIT_BUTTON_DESCRIPTIONS
    from .number import CIRCUIT_NUMBER_DESCRIPTIONS
    from .select import CIRCUIT_SELECT_DESCRIPTIONS
    from .sensor import SENSOR_ENTITY_TIER_BY_KEY
    from .switch import CIRCUIT_SWITCH_DESCRIPTIONS

    return {
        *SENSOR_ENTITY_TIER_BY_KEY,
        *BINARY_SENSOR_ENTITY_TIER_BY_KEY,
        *(description.key for description in CIRCUIT_BUTTON_DESCRIPTIONS),
        *(description.key for description in CIRCUIT_SELECT_DESCRIPTIONS),
        *(description.key for description in CIRCUIT_NUMBER_DESCRIPTIONS),
        *(description.key for description in CIRCUIT_SWITCH_DESCRIPTIONS),
    }


def _target_coordinators(hass: Any, circuit_id: Any) -> list[Any]:
    coordinators = _loaded_coordinators(hass)
    if not isinstance(circuit_id, str):
        return coordinators
    if not coordinators:
        return []

    matched = []
    for coordinator in coordinators:
        known_circuit_ids = _known_circuit_ids(coordinator)
        has_circuit = getattr(coordinator, "has_circuit", None)
        if (
            (callable(has_circuit) and has_circuit(circuit_id))
            or circuit_id in known_circuit_ids
            or (not callable(has_circuit) and not known_circuit_ids)
        ):
            matched.append(coordinator)
    if matched:
        return matched
    raise HomeAssistantError(_unknown_circuit_message(circuit_id, coordinators))


def _unknown_circuit_message(circuit_id: str, coordinators: list[Any]) -> str:
    known_circuit_ids = sorted(
        {
            known_circuit_id
            for coordinator in coordinators
            for known_circuit_id in _known_circuit_ids(coordinator)
        }
    )
    if known_circuit_ids:
        return (
            f"Unknown circuit_id '{circuit_id}'. Known circuit IDs: "
            f"{', '.join(known_circuit_ids)}."
        )
    return f"Unknown circuit_id '{circuit_id}'."


def _known_circuit_ids(coordinator: Any) -> set[str]:
    circuit_ids = {
        str(config.circuit_id)
        for config in getattr(coordinator, "circuit_configs", ())
        if getattr(config, "circuit_id", None)
    }
    store_data = getattr(coordinator, "store_data", None)
    if store_data is None:
        return circuit_ids
    for attr in (
        "energy_usage_by_circuit",
        "demand_by_circuit",
        "standby_by_circuit",
        "weather_context_by_circuit",
        "weather_context_history_by_circuit",
        "water_context_history_by_circuit",
        "nilm_signatures",
        "nilm_unknown_loads_by_circuit",
        "nilm_label_intervals_by_circuit",
        "nilm_appliance_assignments_by_circuit",
        "maintenance_by_circuit",
    ):
        values = getattr(store_data, attr, None)
        if isinstance(values, Mapping):
            circuit_ids.update(str(key) for key in values)
    baselines = getattr(store_data, "baselines", None)
    if isinstance(baselines, Mapping):
        circuit_ids.update(str(key).split(":", 1)[0] for key in baselines)
    alerts = getattr(store_data, "alerts", ())
    if not isinstance(alerts, (str, bytes)):
        try:
            iterator = iter(alerts)
        except TypeError:
            iterator = iter(())
        for alert in iterator:
            alert_circuit_id = getattr(alert, "circuit_id", None)
            if alert_circuit_id:
                circuit_ids.add(str(alert_circuit_id))
    return circuit_ids


def _loaded_coordinators(hass: Any) -> list[Any]:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return []
    return [
        value
        for key, value in domain_data.items()
        if key != _SERVICES_KEY and hasattr(value, "async_set_updated_data")
    ]


async def _dispatch_alert_id_action(
    hass: Any,
    data: Mapping[str, Any],
    *,
    method_name: str,
) -> None:
    alert_id = data.get(ATTR_ALERT_ID)
    target_coordinators = _loaded_coordinators(hass)
    if isinstance(alert_id, str):
        alert_id = alert_id.strip()
    if not isinstance(alert_id, str) or not alert_id:
        circuit_id = _service_circuit_id(hass, data)
        target_coordinators = _target_coordinators(hass, circuit_id)
        alert_id = _single_active_alert_id_for_circuit(
            circuit_id,
            target_coordinators,
        )

    handled = False
    for coordinator in target_coordinators:
        result = await _call_if_present(coordinator, method_name, alert_id)
        handled = handled or result is True

    if not handled:
        raise HomeAssistantError(
            f"Unknown alert_id '{alert_id}'. Open a newer notification or "
            "review the evidence panel for the current alert."
        )


def _single_active_alert_id_for_circuit(
    circuit_id: str,
    coordinators: Iterable[Any],
) -> str:
    alert_ids = sorted(
        {
            alert_id
            for coordinator in coordinators
            for alert_id in _active_alert_ids_for_circuit(coordinator, circuit_id)
        }
    )
    if len(alert_ids) == 1:
        return alert_ids[0]
    if alert_ids:
        raise HomeAssistantError(
            f"entity_id target for circuit_id '{circuit_id}' has multiple "
            f"active alerts: {', '.join(alert_ids)}. Pass alert_id explicitly."
        )
    raise HomeAssistantError(
        f"entity_id target for circuit_id '{circuit_id}' has no active alerts. "
        "Pass alert_id explicitly."
    )


def _active_alert_ids_for_circuit(coordinator: Any, circuit_id: str) -> set[str]:
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "active_alerts_by_circuit", {})
    alerts = by_circuit.get(circuit_id, ()) if isinstance(by_circuit, Mapping) else ()
    if isinstance(alerts, (str, bytes)):
        return set()
    try:
        iterator = iter(alerts)
    except TypeError:
        return set()
    return {
        alert_id
        for alert in iterator
        if (alert_id := _alert_id_from_alert(alert))
    }


def _alert_id_from_alert(alert: Any) -> str | None:
    if isinstance(alert, Mapping):
        alert_id = alert.get(ATTR_ALERT_ID)
    else:
        alert_id = getattr(alert, ATTR_ALERT_ID, None)
    if not isinstance(alert_id, str):
        try:
            alert_id = notifications.notification_id_for_alert(alert)
        except AttributeError:
            return None
    normalized = alert_id.strip()
    return normalized or None


def _service_recommendation_id(hass: Any, data: Mapping[str, Any]) -> str:
    recommendation_id = data.get(ATTR_RECOMMENDATION_ID)
    if isinstance(recommendation_id, str):
        recommendation_id = recommendation_id.strip()
    if isinstance(recommendation_id, str) and recommendation_id:
        return recommendation_id

    circuit_id = _service_circuit_id(hass, data)
    target_coordinators = _target_coordinators(hass, circuit_id)
    recommendation_ids = sorted(
        {
            recommendation_id
            for coordinator in target_coordinators
            for recommendation_id in _recommendation_ids_for_circuit(
                coordinator,
                circuit_id,
            )
        },
    )
    if len(recommendation_ids) == 1:
        return recommendation_ids[0]
    if recommendation_ids:
        raise HomeAssistantError(
            f"entity_id target for circuit_id '{circuit_id}' has multiple "
            "setting recommendations: "
            f"{', '.join(recommendation_ids)}. Pass recommendation_id explicitly."
        )
    raise HomeAssistantError(
        f"entity_id target for circuit_id '{circuit_id}' has no setting "
        "recommendations. Pass recommendation_id explicitly."
    )


def _target_recommendation_coordinators(
    hass: Any,
    recommendation_id: Any,
    entry_id: Any = None,
) -> list[Any]:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return []
    if not isinstance(recommendation_id, str) or not recommendation_id:
        raise HomeAssistantError("Missing recommendation_id.")

    if isinstance(entry_id, str) and entry_id:
        coordinator = domain_data.get(entry_id)
        if coordinator is None or not hasattr(coordinator, "async_set_updated_data"):
            raise HomeAssistantError(f"Unknown entry_id '{entry_id}'.")
        if not _coordinator_has_recommendation(coordinator, recommendation_id):
            raise HomeAssistantError(
                f"Unknown recommendation_id '{recommendation_id}' "
                f"for entry_id '{entry_id}'."
            )
        return [coordinator]

    matches = [
        coordinator
        for coordinator in _loaded_coordinators(hass)
        if _coordinator_has_recommendation(coordinator, recommendation_id)
    ]
    if len(matches) == 1:
        return matches
    if len(matches) > 1:
        raise HomeAssistantError(
            f"recommendation_id '{recommendation_id}' matched multiple loaded "
            "analyzer entries; pass entry_id."
        )
    raise HomeAssistantError(f"Unknown recommendation_id '{recommendation_id}'.")


def _target_nilm_signature_coordinators(
    hass: Any,
    circuit_id: Any,
    *signature_ids: Any,
) -> list[Any]:
    if not isinstance(circuit_id, str) or not circuit_id:
        raise HomeAssistantError("Missing circuit_id.")
    target_coordinators = _target_coordinators(hass, circuit_id)
    required_signature_ids = [
        signature_id
        for signature_id in signature_ids
        if isinstance(signature_id, str) and signature_id
    ]
    if not required_signature_ids:
        raise HomeAssistantError("Missing signature_id.")
    if (
        len(required_signature_ids) > 1
        and len(set(required_signature_ids)) != len(required_signature_ids)
    ):
        raise HomeAssistantError(
            "source_signature_id and target_signature_id must be different."
        )

    matches = [
        coordinator
        for coordinator in target_coordinators
        if all(
            signature_id in _known_nilm_signature_ids(coordinator, circuit_id)
            for signature_id in required_signature_ids
        )
    ]
    if matches:
        return matches

    missing_signature_id = next(
        (
            signature_id
            for signature_id in required_signature_ids
            if not any(
                signature_id in _known_nilm_signature_ids(coordinator, circuit_id)
                for coordinator in target_coordinators
            )
        ),
        required_signature_ids[0],
    )
    raise HomeAssistantError(
        _unknown_nilm_signature_message(
            circuit_id,
            missing_signature_id,
            target_coordinators,
        )
    )


def _target_nilm_interval_coordinators(
    hass: Any,
    circuit_id: Any,
    interval_id: Any,
) -> list[Any]:
    if not isinstance(circuit_id, str) or not circuit_id:
        raise HomeAssistantError("Missing circuit_id.")
    if not isinstance(interval_id, str) or not interval_id:
        raise HomeAssistantError("Missing interval_id.")
    target_coordinators = _target_coordinators(hass, circuit_id)
    matches = [
        coordinator
        for coordinator in target_coordinators
        if interval_id in _known_nilm_interval_ids(coordinator, circuit_id)
    ]
    if matches:
        return matches
    known_interval_ids = sorted(
        {
            known_interval_id
            for coordinator in target_coordinators
            for known_interval_id in _known_nilm_interval_ids(
                coordinator,
                circuit_id,
            )
        }
    )
    if known_interval_ids:
        raise HomeAssistantError(
            f"Unknown interval_id '{interval_id}'. Known interval IDs for "
            f"{circuit_id}: {', '.join(known_interval_ids)}."
        )
    raise HomeAssistantError(
        f"Unknown interval_id '{interval_id}' for circuit_id '{circuit_id}'."
    )


def _unknown_nilm_signature_message(
    circuit_id: str,
    signature_id: str,
    coordinators: list[Any],
) -> str:
    known_signature_ids = sorted(
        {
            known_signature_id
            for coordinator in coordinators
            for known_signature_id in _known_nilm_signature_ids(
                coordinator,
                circuit_id,
            )
        }
    )
    if known_signature_ids:
        return (
            f"Unknown signature_id '{signature_id}'. Known signature IDs for "
            f"{circuit_id}: {', '.join(known_signature_ids)}."
        )
    return f"Unknown signature_id '{signature_id}' for circuit_id '{circuit_id}'."


def _known_nilm_signature_ids(coordinator: Any, circuit_id: str) -> set[str]:
    signature_ids: set[str] = set()
    store_data = getattr(coordinator, "store_data", None)
    signatures_by_circuit = getattr(store_data, "nilm_signatures", {})
    _collect_signature_ids(signatures_by_circuit, circuit_id, signature_ids)

    state = getattr(coordinator, "state", None)
    unknown_loads_by_circuit = getattr(state, "nilm_unknown_loads_by_circuit", {})
    inventory = (
        unknown_loads_by_circuit.get(circuit_id)
        if isinstance(unknown_loads_by_circuit, Mapping)
        else None
    )
    if isinstance(inventory, Mapping):
        _collect_signature_ids(
            {circuit_id: inventory.get("unknown_loads", ())},
            circuit_id,
            signature_ids,
        )
    return signature_ids


def _known_nilm_interval_ids(coordinator: Any, circuit_id: str) -> set[str]:
    store_data = getattr(coordinator, "store_data", None)
    intervals_by_circuit = getattr(store_data, "nilm_label_intervals_by_circuit", {})
    if not isinstance(intervals_by_circuit, Mapping):
        return set()
    intervals = intervals_by_circuit.get(circuit_id, ())
    if isinstance(intervals, (str, bytes)):
        return set()
    try:
        iterator = iter(intervals)
    except TypeError:
        return set()
    return {
        str(interval.get("interval_id"))
        for interval in iterator
        if isinstance(interval, Mapping) and interval.get("interval_id")
    }


def _collect_signature_ids(
    signatures_by_circuit: Any,
    circuit_id: str,
    signature_ids: set[str],
) -> None:
    if not isinstance(signatures_by_circuit, Mapping):
        return
    signatures = signatures_by_circuit.get(circuit_id, ())
    if isinstance(signatures, (str, bytes)):
        return
    try:
        iterator = iter(signatures)
    except TypeError:
        return
    for signature in iterator:
        if isinstance(signature, Mapping):
            signature_id = signature.get(ATTR_SIGNATURE_ID)
        else:
            signature_id = getattr(signature, ATTR_SIGNATURE_ID, None)
        if signature_id:
            signature_ids.add(str(signature_id))


def _coordinator_has_recommendation(coordinator: Any, recommendation_id: str) -> bool:
    store_data = getattr(coordinator, "store_data", None)
    recommendations = getattr(store_data, "settings_recommendations", {})
    if isinstance(recommendations, Mapping) and recommendation_id in recommendations:
        return True

    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {})
    if not isinstance(by_circuit, Mapping):
        return False
    for circuit_recommendations in by_circuit.values():
        if isinstance(circuit_recommendations, (str, bytes)):
            continue
        try:
            iterator = iter(circuit_recommendations)
        except TypeError:
            continue
        for recommendation in iterator:
            if isinstance(recommendation, Mapping):
                current_id = recommendation.get(ATTR_RECOMMENDATION_ID)
            else:
                current_id = getattr(recommendation, ATTR_RECOMMENDATION_ID, None)
            if current_id == recommendation_id:
                return True
    return False


def _recommendation_ids_for_circuit(coordinator: Any, circuit_id: str) -> set[str]:
    recommendation_ids: set[str] = set()
    state = getattr(coordinator, "state", None)
    by_circuit = getattr(state, "settings_recommendations_by_circuit", {})
    if isinstance(by_circuit, Mapping):
        _collect_recommendation_ids(
            by_circuit.get(circuit_id, ()),
            recommendation_ids,
            coordinator=coordinator,
        )

    store_data = getattr(coordinator, "store_data", None)
    stored = getattr(store_data, "settings_recommendations", {})
    if isinstance(stored, Mapping):
        for recommendation_id, recommendation in stored.items():
            if _recommendation_matches_circuit(
                recommendation_id,
                recommendation,
                circuit_id,
            ) and _recommendation_is_pending(coordinator, recommendation):
                recommendation_ids.add(str(recommendation_id))
    return recommendation_ids


def _collect_recommendation_ids(
    recommendations: Any,
    recommendation_ids: set[str],
    *,
    coordinator: Any | None = None,
) -> None:
    for recommendation in _iter_items(recommendations):
        if coordinator is not None and not _recommendation_is_pending(
            coordinator,
            recommendation,
        ):
            continue
        if isinstance(recommendation, Mapping):
            recommendation_id = recommendation.get(ATTR_RECOMMENDATION_ID)
        else:
            recommendation_id = getattr(recommendation, ATTR_RECOMMENDATION_ID, None)
        if isinstance(recommendation_id, str) and recommendation_id.strip():
            recommendation_ids.add(recommendation_id.strip())


def _recommendation_matches_circuit(
    recommendation_id: Any,
    recommendation: Any,
    circuit_id: str,
) -> bool:
    item_circuit_id = (
        recommendation.get(ATTR_CIRCUIT_ID)
        if isinstance(recommendation, Mapping)
        else getattr(recommendation, ATTR_CIRCUIT_ID, None)
    )
    if isinstance(item_circuit_id, str) and item_circuit_id:
        return item_circuit_id == circuit_id
    return isinstance(recommendation_id, str) and recommendation_id.startswith(
        f"{circuit_id}:",
    )


def _recommendation_is_pending(coordinator: Any, recommendation: Any) -> bool:
    status = (
        recommendation.get("status")
        if isinstance(recommendation, Mapping)
        else getattr(recommendation, "status", None)
    )
    if status is None:
        return True
    status_value = getattr(status, "value", status)
    if str(status_value) != "pending":
        return False

    expires_at = (
        recommendation.get("expires_at")
        if isinstance(recommendation, Mapping)
        else getattr(recommendation, "expires_at", None)
    )
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
    if not isinstance(expires_at, datetime):
        return True
    now_fn = getattr(coordinator, "_now_fn", None)
    now = now_fn() if callable(now_fn) else datetime.now(UTC)
    if expires_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return expires_at > now


def _nilm_sensor_label_intervals_from_history(
    rows: Any,
    ground_truth_entity_id: str,
    *,
    start: Any,
    end: Any,
    threshold_w: Any = 0.0,
) -> list[dict[str, str]]:
    entity_id = str(ground_truth_entity_id or "").strip()
    start_dt = _service_datetime(start, ATTR_START)
    end_dt = _service_datetime(end, ATTR_END)
    try:
        threshold = float(threshold_w)
    except (TypeError, ValueError):
        threshold = 0.0

    samples: list[tuple[datetime, float]] = []
    for state in _iter_history_states(rows):
        state_entity_id = _state_value(state, "entity_id")
        if entity_id and state_entity_id and str(state_entity_id) != entity_id:
            continue
        timestamp = _state_timestamp(state)
        value = _float_or_none(_state_value(state, "state"))
        if timestamp is not None and value is not None:
            samples.append((timestamp, value))
    samples.sort(key=lambda item: item[0])

    intervals: list[dict[str, str]] = []
    active_start: datetime | None = None
    for timestamp, value in samples:
        if timestamp < start_dt or timestamp > end_dt:
            continue
        active = value > threshold
        if active and active_start is None:
            active_start = timestamp
        elif not active and active_start is not None:
            if timestamp > active_start:
                intervals.append(
                    {
                        ATTR_START: active_start.isoformat(),
                        ATTR_END: timestamp.isoformat(),
                    }
                )
            active_start = None
    if active_start is not None and end_dt > active_start:
        intervals.append(
            {
                ATTR_START: active_start.isoformat(),
                ATTR_END: end_dt.isoformat(),
            }
        )
    return intervals


async def _async_nilm_sensor_history_rows(
    hass: Any,
    entity_id: str,
    start: datetime,
    end: datetime,
) -> Any:
    history_helper = _history_get_significant_states()
    recorder = _recorder_get_instance(hass)
    if history_helper is None or recorder is None:
        return []
    job = partial(
        history_helper,
        hass,
        start,
        end_time=end,
        entity_ids=[entity_id],
        minimal_response=True,
        no_attributes=True,
    )
    try:
        rows = recorder.async_add_executor_job(job)
        if inspect.isawaitable(rows):
            rows = await rows
        return rows
    except Exception:
        return []


def _history_get_significant_states() -> Any:
    try:
        from homeassistant.components.recorder.history import get_significant_states
    except ModuleNotFoundError:
        return None
    return get_significant_states


def _recorder_get_instance(hass: Any) -> Any:
    try:
        from homeassistant.components.recorder import get_instance
    except ModuleNotFoundError:
        return None
    try:
        return get_instance(hass)
    except Exception:
        return None


def _iter_history_states(rows: Any) -> Iterable[Any]:
    if isinstance(rows, Mapping):
        rows = rows.values()
    for series in _iter_items(rows):
        yield from _iter_items(series)


def _state_value(state: Any, key: str) -> Any:
    if isinstance(state, Mapping):
        return state.get(key)
    return getattr(state, key, None)


def _state_timestamp(state: Any) -> datetime | None:
    for key in ("last_changed", "last_updated"):
        value = _state_value(state, key)
        if value is None:
            continue
        try:
            return _service_datetime(value, key)
        except HomeAssistantError:
            continue
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _service_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as err:
        raise HomeAssistantError(f"Invalid {field_name}") from err
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iter_items(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return value.values()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return value
    return (value,)


async def _call_if_present(
    target: Any,
    method_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    method = getattr(target, method_name, None)
    if method is None:
        return None
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
