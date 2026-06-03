from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from .const import DOMAIN

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
SERVICE_SET_STANDBY_SETTINGS = "set_standby_settings"
SERVICE_SET_UTILITY_COMPARISON_SETTINGS = "set_utility_comparison_settings"
SERVICE_START_MAINTENANCE = "start_maintenance"
SERVICE_END_MAINTENANCE = "end_maintenance"
SERVICE_MARK_ALERT_EXPECTED = "mark_alert_expected"
SERVICE_MARK_ALERT_UNHELPFUL = "mark_alert_unhelpful"
SERVICE_MARK_NILM_SIGNATURE_EXPECTED = "mark_nilm_signature_expected"
SERVICE_MERGE_NILM_SIGNATURES = "merge_nilm_signatures"

ATTR_CIRCUIT_ID = "circuit_id"
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
ATTR_WINDOW_HOURS = "window_hours"
ATTR_STANDBY_THRESHOLD_W = "standby_threshold_w"
ATTR_ALWAYS_ON_ALERT_W = "always_on_alert_w"
ATTR_UTILITY_ENERGY_ENTITY = "utility_energy_entity"
ATTR_MEASURED_ENERGY_ENTITIES = "measured_energy_entities"
ATTR_TOLERANCE_PERCENT = "tolerance_percent"
ATTR_NOTE = "note"
ATTR_RELEARN = "relearn"
ATTR_RELEARN_ON_END = "relearn_on_end"
ATTR_SOURCE_SIGNATURE_ID = "source_signature_id"
ATTR_TARGET_SIGNATURE_ID = "target_signature_id"

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


CIRCUIT_SERVICE_SCHEMA = _schema(required=(ATTR_CIRCUIT_ID,))
SENSITIVITY_SERVICE_SCHEMA = _schema(required=(ATTR_CIRCUIT_ID, ATTR_PRESET))
ENERGY_USAGE_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_WINDOW_DAYS, ATTR_DAILY_SPIKE_RATIO),
)
ENERGY_GOAL_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_DAILY_GOAL_KWH, ATTR_GOAL_ALERT_RATIO),
)
ACTIVITY_ALERT_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_MAX_ACTIVE_MINUTES, ATTR_MAX_IDLE_MINUTES),
)
BILLING_CYCLE_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_CYCLE_START_DAY, ATTR_BUDGET_KWH, ATTR_BUDGET_ALERT_RATIO),
)
COST_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(
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
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_WINDOW_MINUTES, ATTR_DEMAND_LIMIT_W),
)
CAPACITY_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_BREAKER_AMPS, ATTR_WARNING_RATIO),
)
STANDBY_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_WINDOW_HOURS, ATTR_STANDBY_THRESHOLD_W, ATTR_ALWAYS_ON_ALERT_W),
)
UTILITY_COMPARISON_SETTINGS_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(
        ATTR_UTILITY_ENERGY_ENTITY,
        ATTR_MEASURED_ENERGY_ENTITIES,
        ATTR_TOLERANCE_PERCENT,
    ),
)
MAINTENANCE_START_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_NOTE, ATTR_DURATION, ATTR_RELEARN_ON_END),
)
MAINTENANCE_END_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID,),
    optional=(ATTR_RELEARN,),
)
ALERT_FEEDBACK_SERVICE_SCHEMA = _schema(required=(ATTR_ALERT_ID,))
NILM_LABEL_SERVICE_SCHEMA = _schema(
    required=(ATTR_CIRCUIT_ID, ATTR_SIGNATURE_ID, ATTR_LABEL)
)
NILM_SIGNATURE_SERVICE_SCHEMA = _schema(required=(ATTR_CIRCUIT_ID, ATTR_SIGNATURE_ID))
NILM_MERGE_SERVICE_SCHEMA = _schema(
    required=(
        ATTR_CIRCUIT_ID,
        ATTR_SOURCE_SIGNATURE_ID,
        ATTR_TARGET_SIGNATURE_ID,
    )
)

_SERVICE_SCHEMAS: dict[str, Callable | None] = {
    SERVICE_RELEARN_BASELINE: CIRCUIT_SERVICE_SCHEMA,
    SERVICE_PAUSE_ALERTS: _schema(
        required=(ATTR_CIRCUIT_ID,),
        optional=(ATTR_DURATION,),
    ),
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
    circuit_id = data.get(ATTR_CIRCUIT_ID)

    if service == SERVICE_RUN_MAPPING_CHECKS:
        for coordinator in _loaded_coordinators(hass):
            await _call_if_present(coordinator, "async_run_mapping_checks")
        return

    if service == SERVICE_ACKNOWLEDGE_ALERT:
        alert_id = data.get(ATTR_ALERT_ID)
        for coordinator in _loaded_coordinators(hass):
            await _call_if_present(coordinator, "async_acknowledge_alert", alert_id)
        return

    if service == SERVICE_MARK_ALERT_EXPECTED:
        alert_id = data.get(ATTR_ALERT_ID)
        for coordinator in _loaded_coordinators(hass):
            await _call_if_present(coordinator, "async_mark_alert_expected", alert_id)
        return

    if service == SERVICE_MARK_ALERT_UNHELPFUL:
        alert_id = data.get(ATTR_ALERT_ID)
        for coordinator in _loaded_coordinators(hass):
            await _call_if_present(coordinator, "async_mark_alert_unhelpful", alert_id)
        return

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
        elif service == SERVICE_LABEL_NILM_SIGNATURE:
            await _call_if_present(
                coordinator,
                "async_label_nilm_signature",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
                data.get(ATTR_LABEL),
            )
        elif service == SERVICE_IGNORE_NILM_SIGNATURE:
            await _call_if_present(
                coordinator,
                "async_ignore_nilm_signature",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
            )
        elif service == SERVICE_SET_CIRCUIT_SENSITIVITY:
            await _call_if_present(
                coordinator,
                "async_set_circuit_sensitivity",
                circuit_id,
                data.get(ATTR_PRESET),
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
        elif service == SERVICE_MARK_NILM_SIGNATURE_EXPECTED:
            await _call_if_present(
                coordinator,
                "async_mark_nilm_signature_expected",
                circuit_id,
                data.get(ATTR_SIGNATURE_ID),
            )
        elif service == SERVICE_MERGE_NILM_SIGNATURES:
            await _call_if_present(
                coordinator,
                "async_merge_nilm_signatures",
                circuit_id,
                data.get(ATTR_SOURCE_SIGNATURE_ID),
                data.get(ATTR_TARGET_SIGNATURE_ID),
            )


def _target_coordinators(hass: Any, circuit_id: Any) -> list[Any]:
    coordinators = _loaded_coordinators(hass)
    if not isinstance(circuit_id, str):
        return coordinators

    matched = [
        coordinator
        for coordinator in coordinators
        if not hasattr(coordinator, "has_circuit")
        or coordinator.has_circuit(circuit_id)
    ]
    return matched or coordinators


def _loaded_coordinators(hass: Any) -> list[Any]:
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return []
    return [
        value
        for key, value in domain_data.items()
        if key != _SERVICES_KEY and hasattr(value, "async_set_updated_data")
    ]


async def _call_if_present(target: Any, method_name: str, *args: Any) -> None:
    method = getattr(target, method_name, None)
    if method is None:
        return
    result = method(*args)
    if inspect.isawaitable(result):
        await result
