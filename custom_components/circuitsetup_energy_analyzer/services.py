from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .const import DOMAIN
from .ux import normalize_sensitivity

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
SERVICE_MARK_NILM_SIGNATURE_EXPECTED = "mark_nilm_signature_expected"
SERVICE_MERGE_NILM_SIGNATURES = "merge_nilm_signatures"
SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS = "recalculate_setting_recommendations"
SERVICE_APPLY_SETTING_RECOMMENDATION = "apply_setting_recommendation"
SERVICE_DENY_SETTING_RECOMMENDATION = "deny_setting_recommendation"
SERVICE_DISMISS_SETTING_RECOMMENDATION = "dismiss_setting_recommendation"

ATTR_CIRCUIT_ID = "circuit_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_DURATION = "duration"
ATTR_ALERT_ID = "alert_id"
ATTR_SIGNATURE_ID = "signature_id"
ATTR_LABEL = "label"
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
ATTR_RECOMMENDATION_ID = "recommendation_id"
ATTR_ENTRY_ID = "entry_id"

_SERVICES_KEY = "_services_setup"


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
RECOMMENDATION_ACTION_SERVICE_SCHEMA = _schema(
    required=(ATTR_RECOMMENDATION_ID,),
    optional=(ATTR_ENTRY_ID,),
)

_SERVICE_SCHEMAS: dict[str, Callable | None] = {
    SERVICE_RELEARN_BASELINE: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_PAUSE_ALERTS: _circuit_schema(ATTR_DURATION),
    SERVICE_ACKNOWLEDGE_ALERT: _schema(required=(ATTR_ALERT_ID,)),
    SERVICE_EXPORT_DIAGNOSTICS: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_EXPORT_HISTORY_CSV: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_RUN_MAPPING_CHECKS: None,
    SERVICE_LABEL_NILM_SIGNATURE: NILM_LABEL_SERVICE_SCHEMA,
    SERVICE_IGNORE_NILM_SIGNATURE: NILM_SIGNATURE_SERVICE_SCHEMA,
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
    SERVICE_MARK_NILM_SIGNATURE_EXPECTED: NILM_SIGNATURE_SERVICE_SCHEMA,
    SERVICE_MERGE_NILM_SIGNATURES: NILM_MERGE_SERVICE_SCHEMA,
    SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS: (
        RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA
    ),
    SERVICE_APPLY_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_DENY_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    SERVICE_DISMISS_SETTING_RECOMMENDATION: RECOMMENDATION_ACTION_SERVICE_SCHEMA,
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
        recommendation_id = data.get(ATTR_RECOMMENDATION_ID)
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
        recommendation_id = data.get(ATTR_RECOMMENDATION_ID)
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
        recommendation_id = data.get(ATTR_RECOMMENDATION_ID)
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
                normalize_sensitivity(data.get(ATTR_PRESET)),
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
    registry = async_get(hass)
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

    return {
        *SENSOR_ENTITY_TIER_BY_KEY,
        *BINARY_SENSOR_ENTITY_TIER_BY_KEY,
        *(description.key for description in CIRCUIT_BUTTON_DESCRIPTIONS),
        *(description.key for description in CIRCUIT_SELECT_DESCRIPTIONS),
        *(description.key for description in CIRCUIT_NUMBER_DESCRIPTIONS),
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
        if callable(has_circuit) and has_circuit(circuit_id):
            matched.append(coordinator)
        elif circuit_id in known_circuit_ids:
            matched.append(coordinator)
        elif not callable(has_circuit) and not known_circuit_ids:
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
        return None
    normalized = alert_id.strip()
    return normalized or None


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


async def _call_if_present(target: Any, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if method is None:
        return None
    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result
