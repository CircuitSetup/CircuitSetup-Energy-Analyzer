from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from ..const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_EXTRA_SOURCE_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
)
from ..entity import circuit_info_from_config
from ..localized_text import translation_section
from ..models import ApplianceProfile, CircuitMode, SensorRole
from ..profiles import get_profile_definition
from ..state import circuit_is_learning

SETUP_HEALTH_OPEN_PATH = "/config/integrations/integration/circuitsetup_energy_analyzer"
SETUP_HEALTH_OPTIONS_PATH = "/config/integrations/dashboard"

_HIGH_POWER_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.MINI_SPLIT,
    ApplianceProfile.ELECTRIC_HEAT,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.OVEN,
    ApplianceProfile.MICROWAVE,
    ApplianceProfile.DISHWASHER,
    ApplianceProfile.DRYER,
    ApplianceProfile.POOL_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.EV_CHARGER,
    ApplianceProfile.SOLAR_INVERTER,
    ApplianceProfile.MAINS_NILM,
}
_UTILITY_COMPARISON_SETUP_STATUSES = {
    "unconfigured",
    "missing_utility",
    "missing_measured",
}
_UTILITY_COMPARISON_SETUP_ISSUES = {
    "utility_comparison_source_mismatch",
    "utility_comparison_missing_utility_source",
    "utility_comparison_missing_measured_source",
}
_MAX_SETUP_HEALTH_LIST_ITEMS = 3
_MAX_SETUP_HEALTH_ISSUES = 3
_MAX_SETUP_HEALTH_SOURCE_ENTITIES_PER_ISSUE = 2
_MAX_SETUP_HEALTH_ATTRIBUTE_STRING_LENGTH = 80
_MAX_SETUP_HEALTH_CHECKLIST_AFFECTED_CIRCUITS = 3
_SETUP_HEALTH_CHECKLIST_OPTION_STEPS = {
    "source_data_found": "sources",
    "circuit_assignments_reviewed": "assign",
    "ct_direction_valid": "assign",
    "cumulative_kwh_sources_found": "sources",
    "appliance_profiles_selected": "assign",
    "entity_detail_level_selected": "entity_detail",
    "dashboard_created": "dashboard",
    "nilm_enabled": "mains",
}
_SETUP_HEALTH_ISSUE_OPTION_STEPS = {
    "missing_circuit_assignments": "assign",
    "missing_energy_source": "sources",
    "missing_temperature_source": "sources",
    "circuit_mode_mismatch": "assign",
    "missing_electrical_metrics": "assign",
    "missing_mains_source": "mains",
    "check_ct_direction": "assign",
    "missing_rain_context_source": "sources",
    "missing_water_flow_source": "sources",
    "missing_source_entities": "sources",
    "stale_source": "sources",
    "missing_source_sensor": "assign",
    "invalid_source_state": "sources",
    "source_data_quality": "assign",
    "utility_comparison_missing_utility_source": "utility",
    "utility_comparison_missing_measured_source": "utility",
    "utility_comparison_source_mismatch": "utility",
}


def setup_health_panel_text() -> dict[str, Any]:
    """Return English setup-health panel text from Home Assistant translations."""
    return dict(translation_section("panel", "setup_health"))


def _setup_health_checklist_text(item_id: str) -> Mapping[str, Any]:
    checklist = setup_health_panel_text().get("checklist", {})
    if not isinstance(checklist, Mapping):
        return {}
    item = checklist.get(item_id, {})
    return item if isinstance(item, Mapping) else {}


def _setup_health_checklist_value(item_id: str, key: str) -> str:
    value = _setup_health_checklist_text(item_id).get(key, "")
    return str(value) if value is not None else ""


def setup_health_value(coordinator: Any) -> str:
    """Return the highest-priority setup next step for the whole integration."""
    return str(_setup_health_summary(coordinator)["state"])


def setup_health_attributes(coordinator: Any) -> dict[str, Any]:
    """Return actionable setup-health attributes for dashboards and automations."""
    return dict(_setup_health_summary(coordinator)["attributes"])


def _setup_health_summary(coordinator: Any) -> dict[str, Any]:
    issues = _setup_health_issues(coordinator)
    if issues:
        primary = issues[0]
        return {
            "state": primary["state"],
            "attributes": _setup_health_attributes_for_issues(
                coordinator,
                issues,
                primary,
            ),
        }

    primary = {
        "state": "Ready",
        "recommended_action": "No setup action needed",
        "affected_circuit": None,
        "affected_circuit_name": None,
        "open_path": SETUP_HEALTH_OPEN_PATH,
        "reason": (
            "Configured circuits have enough setup data for their current checks."
        ),
    }
    return {
        "state": "Ready",
        "attributes": _setup_health_attributes_for_issues(
            coordinator,
            [],
            primary,
        ),
    }


def _setup_health_attributes_for_issues(
    coordinator: Any,
    issues: list[dict[str, Any]],
    primary: Mapping[str, Any],
) -> dict[str, Any]:
    affected_circuits = _setup_health_issue_circuits(issues)
    learning_circuits = _setup_health_issue_circuits(
        issues,
        states={"Let analyzer learn"},
    )
    stale_sources = _setup_health_issue_source_entities(
        issues,
        states={"Fix stale source sensor"},
    )
    stale_source_circuits = _setup_health_issue_circuits(
        issues,
        states={"Fix stale source sensor"},
    )
    missing_energy_sources = _setup_health_issue_circuits(
        issues,
        states={"Add cumulative kWh source"},
    )
    negative_power_loads = _setup_health_issue_circuits(
        issues,
        states={"Check CT direction"},
    )
    dual_phase_missing_legs = _setup_health_issue_circuits(
        issues,
        issue_keys={"dual_phase_missing_leg"},
    )
    missing_rain_sources = _setup_health_issue_circuits(
        issues,
        issue_keys={"missing_rain_context_source"},
    )
    missing_water_flow_sources = _setup_health_issue_circuits(
        issues,
        issue_keys={"missing_water_flow_source"},
    )
    utility_comparison_setup_issues = _setup_health_issue_circuits(
        issues,
        issue_keys=_UTILITY_COMPARISON_SETUP_ISSUES,
    )
    bounded_issues = _bounded_setup_health_issues(coordinator, issues)
    checklist = _setup_health_checklist(coordinator, issues)
    ready = not issues
    return {
        "blocking_issue_count": len(issues),
        "issue_count": len(issues),
        "warning_count": _setup_health_severity_count(issues, "warning"),
        "ready": ready,
        "next_step": _bounded_setup_health_value(primary["recommended_action"]),
        "recommended_action": _bounded_setup_health_value(
            primary["recommended_action"],
        ),
        "primary_issue": _bounded_setup_health_value(primary.get("issue")),
        "primary_severity": _bounded_setup_health_value(primary.get("severity")),
        "issue_summary": _bounded_setup_health_string(
            _setup_health_issue_summary(issues, primary),
        ),
        "affected_circuit": _bounded_setup_health_value(primary["affected_circuit"]),
        "affected_circuit_name": _bounded_setup_health_value(
            primary["affected_circuit_name"],
        ),
        "affected_circuits": _bounded_setup_health_list(affected_circuits),
        "affected_circuits_truncated_count": _truncated_count(affected_circuits),
        "open_path": _bounded_setup_health_value(primary["open_path"]),
        "reason": _bounded_setup_health_value(primary["reason"]),
        "learning_circuits": _bounded_setup_health_list(learning_circuits),
        "learning_circuits_truncated_count": _truncated_count(learning_circuits),
        "stale_sources": _bounded_setup_health_list(stale_sources),
        "stale_sources_truncated_count": _truncated_count(stale_sources),
        "stale_source_circuits": _bounded_setup_health_list(stale_source_circuits),
        "stale_source_circuits_truncated_count": _truncated_count(
            stale_source_circuits,
        ),
        "stale_source_entities": _bounded_setup_health_list(stale_sources),
        "stale_source_entities_truncated_count": _truncated_count(stale_sources),
        "missing_energy_sources": _bounded_setup_health_list(missing_energy_sources),
        "missing_energy_sources_truncated_count": _truncated_count(
            missing_energy_sources,
        ),
        "negative_power_loads": _bounded_setup_health_list(negative_power_loads),
        "negative_power_loads_truncated_count": _truncated_count(
            negative_power_loads,
        ),
        "dual_phase_missing_legs": _bounded_setup_health_list(
            dual_phase_missing_legs,
        ),
        "dual_phase_missing_legs_truncated_count": _truncated_count(
            dual_phase_missing_legs,
        ),
        "missing_rain_sources": _bounded_setup_health_list(missing_rain_sources),
        "missing_rain_sources_truncated_count": _truncated_count(
            missing_rain_sources,
        ),
        "missing_water_flow_sources": _bounded_setup_health_list(
            missing_water_flow_sources,
        ),
        "missing_water_flow_sources_truncated_count": _truncated_count(
            missing_water_flow_sources,
        ),
        "utility_comparison_setup_issues": _bounded_setup_health_list(
            utility_comparison_setup_issues,
        ),
        "utility_comparison_setup_issues_truncated_count": _truncated_count(
            utility_comparison_setup_issues,
        ),
        "issues": bounded_issues,
        "issues_truncated_count": len(issues) - len(bounded_issues),
        "checklist": checklist,
        "checklist_ready_count": sum(
            1 for item in checklist if item["status"] in {"ok", "optional"}
        ),
        "checklist_total_count": len(checklist),
    }


def _setup_health_checklist(
    coordinator: Any,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    circuits = _setup_health_circuits(coordinator)
    has_circuits = bool(circuits)
    has_sources = any(
        getattr(circuit, "sensors", ()) for _, circuit in circuits
    ) or any(
        _setup_health_config_value(coordinator, key)
        for key in (
            CONF_SOURCE_ENTITIES,
            CONF_EXTRA_SOURCE_ENTITIES,
            CONF_MAINS_SOURCE_ENTITIES,
        )
    )
    source_circuits = _setup_health_issue_circuits(
        issues,
        issue_keys={
            "missing_source_entities",
            "missing_source_sensor",
            "stale_source",
            "invalid_source_state",
            "source_data_quality",
        },
    )
    energy_circuits = _setup_health_issue_circuits(
        issues,
        issue_keys={"missing_energy_source"},
    )
    ct_circuits = _setup_health_issue_circuits(
        issues,
        issue_keys={"check_ct_direction"},
    )
    learning_circuits = _setup_health_issue_circuits(
        issues,
        issue_keys={"learning"},
    )
    dashboard_request = getattr(coordinator, "last_dashboard_create_request", None)
    if not isinstance(dashboard_request, Mapping):
        dashboard_request = getattr(coordinator, "dashboard_status", None)
    if not isinstance(dashboard_request, Mapping):
        store_data = getattr(coordinator, "store_data", None)
        dashboard_request = getattr(store_data, "dashboard_status", None)
    dashboard_action = (
        str(dashboard_request.get("action") or "")
        if isinstance(dashboard_request, Mapping)
        else ""
    )
    nilm_enabled = bool(
        _setup_health_config_value(coordinator, CONF_ENABLE_EXPERIMENTAL_NILM)
    )
    entity_detail_level = _setup_health_config_value(
        coordinator,
        CONF_ENTITY_DETAIL_LEVEL,
    )
    compact = len(issues) > _MAX_SETUP_HEALTH_ISSUES

    items = [
        _setup_health_checklist_item(
            "source_data_found",
            _setup_health_checklist_value("source_data_found", "title"),
            "ok" if has_sources and not source_circuits else "needs_attention",
            _setup_health_checklist_value("source_data_found", "why_it_matters"),
            affected_circuits=source_circuits,
            fix=(
                _setup_health_checklist_value("source_data_found", "fix")
                if has_circuits
                else _setup_health_checklist_value(
                    "circuit_assignments_reviewed",
                    "fix",
                )
            ),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "circuit_assignments_reviewed",
            _setup_health_checklist_value("circuit_assignments_reviewed", "title"),
            "ok" if has_circuits else "needs_attention",
            _setup_health_checklist_value(
                "circuit_assignments_reviewed",
                "why_it_matters",
            ),
            fix=_setup_health_checklist_value("circuit_assignments_reviewed", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "ct_direction_valid",
            _setup_health_checklist_value(
                "ct_direction_valid",
                "title_attention" if ct_circuits else "title",
            ),
            "ok" if not ct_circuits else "needs_attention",
            _setup_health_checklist_value("ct_direction_valid", "why_it_matters"),
            affected_circuits=ct_circuits,
            fix=_setup_health_checklist_value("ct_direction_valid", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "cumulative_kwh_sources_found",
            _setup_health_checklist_value("cumulative_kwh_sources_found", "title"),
            "ok" if has_circuits and not energy_circuits else "needs_attention",
            _setup_health_checklist_value(
                "cumulative_kwh_sources_found",
                "why_it_matters",
            ),
            affected_circuits=energy_circuits,
            fix=_setup_health_checklist_value("cumulative_kwh_sources_found", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "appliance_profiles_selected",
            _setup_health_checklist_value("appliance_profiles_selected", "title"),
            "ok" if has_circuits else "needs_attention",
            _setup_health_checklist_value(
                "appliance_profiles_selected",
                "why_it_matters",
            ),
            fix=_setup_health_checklist_value("appliance_profiles_selected", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "entity_detail_level_selected",
            _setup_health_checklist_value("entity_detail_level_selected", "title"),
            "ok" if entity_detail_level else "needs_attention",
            _setup_health_checklist_value(
                "entity_detail_level_selected",
                "why_it_matters",
            ),
            fix=_setup_health_checklist_value("entity_detail_level_selected", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "dashboard_created",
            _setup_health_checklist_value("dashboard_created", "title"),
            "ok" if dashboard_action in {"created", "updated"} else "needs_attention",
            _setup_health_checklist_value("dashboard_created", "why_it_matters"),
            fix=_setup_health_checklist_value("dashboard_created", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "notifications_enabled",
            _setup_health_checklist_value("notifications_enabled", "title"),
            "ok",
            _setup_health_checklist_value("notifications_enabled", "why_it_matters"),
            fix=_setup_health_checklist_value("notifications_enabled", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "nilm_enabled",
            _setup_health_checklist_value("nilm_enabled", "title"),
            "ok" if nilm_enabled else "optional",
            _setup_health_checklist_value("nilm_enabled", "why_it_matters"),
            fix=_setup_health_checklist_value("nilm_enabled", "fix"),
            compact=compact,
        ),
        _setup_health_checklist_item(
            "learning_progress",
            _setup_health_checklist_value("learning_progress", "title"),
            (
                "learning"
                if learning_circuits
                else ("ok" if has_circuits else "needs_attention")
            ),
            _setup_health_checklist_value("learning_progress", "why_it_matters"),
            affected_circuits=learning_circuits,
            fix=_setup_health_checklist_value("learning_progress", "fix"),
            compact=compact,
        ),
    ]
    return [_setup_health_checklist_with_open_path(coordinator, item) for item in items]


def _setup_health_checklist_item(
    item_id: str,
    title: str,
    status: str,
    why_it_matters: str,
    *,
    affected_circuits: list[str] | None = None,
    fix: str,
    compact: bool,
) -> dict[str, Any]:
    item = {
        "item_id": item_id,
        "status": status,
    }
    if compact:
        if status not in {"ok", "optional"}:
            item["fix"] = _bounded_setup_health_string(fix)
        if affected_circuits:
            item["affected_count"] = len(affected_circuits)
        return item

    item["title"] = _bounded_setup_health_string(title)
    item["why_it_matters"] = _bounded_setup_health_string(why_it_matters)
    if affected_circuits:
        item["affected_circuits"] = _bounded_setup_health_list(
            affected_circuits[:_MAX_SETUP_HEALTH_CHECKLIST_AFFECTED_CIRCUITS],
        )
        item["affected_circuits_truncated_count"] = max(
            len(affected_circuits) - _MAX_SETUP_HEALTH_CHECKLIST_AFFECTED_CIRCUITS,
            0,
        )
    if status not in {"ok", "optional"}:
        item["fix"] = _bounded_setup_health_string(fix)
    return item


def _setup_health_checklist_with_open_path(
    coordinator: Any,
    item: dict[str, Any],
) -> dict[str, Any]:
    if "fix" not in item:
        return item
    step = _SETUP_HEALTH_CHECKLIST_OPTION_STEPS.get(str(item.get("item_id") or ""))
    path = _setup_health_options_path(coordinator, step)
    if path is not None:
        item["open_path"] = path
    return item


def _setup_health_issue_open_path(
    coordinator: Any,
    issue: Mapping[str, Any],
) -> str | None:
    issue_key = str(issue.get("issue") or "")
    if issue_key == "missing_capacity_setting":
        return _setup_health_options_path(
            coordinator,
            "advanced_settings",
            circuit_id=issue.get("circuit_id") or issue.get("affected_circuit"),
        )
    return _setup_health_options_path(
        coordinator,
        _SETUP_HEALTH_ISSUE_OPTION_STEPS.get(issue_key),
    )


def _setup_health_options_path(
    coordinator: Any,
    options_step: str | None,
    *,
    circuit_id: Any | None = None,
) -> str | None:
    if not options_step:
        return None
    entry_id = getattr(coordinator, "entry_id", None)
    if not isinstance(entry_id, str) or not entry_id:
        return None
    params = {
        "config_entry": entry_id,
        "options_step": options_step,
    }
    if circuit_id:
        params["circuit_id"] = str(circuit_id)
    return f"{SETUP_HEALTH_OPTIONS_PATH}#{urlencode(params)}"


def _setup_health_config_value(coordinator: Any, key: str) -> Any:
    for source_name in ("options", "entry_data"):
        source = getattr(coordinator, source_name, {})
        if isinstance(source, Mapping) and key in source:
            return source[key]
    return None


def _bounded_setup_health_list(values: list[str]) -> list[str]:
    return [
        _bounded_setup_health_string(value)
        for value in values[:_MAX_SETUP_HEALTH_LIST_ITEMS]
    ]


def _truncated_count(values: list[str]) -> int:
    return max(len(values) - _MAX_SETUP_HEALTH_LIST_ITEMS, 0)


def _bounded_setup_health_issues(
    coordinator: Any,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _bounded_setup_health_issue(coordinator, issue)
        for issue in issues[:_MAX_SETUP_HEALTH_ISSUES]
    ]


def _bounded_setup_health_issue(
    coordinator: Any,
    issue: Mapping[str, Any],
) -> dict[str, Any]:
    bounded = {key: _bounded_setup_health_value(value) for key, value in issue.items()}
    path = _setup_health_issue_open_path(coordinator, bounded)
    if path is None:
        bounded.pop("open_path", None)
    else:
        bounded["open_path"] = path
    source_entities = [
        _bounded_setup_health_string(entity_id)
        for entity_id in bounded.get("source_entities", ())
        if isinstance(entity_id, str)
    ]
    bounded["source_entities"] = source_entities[
        :_MAX_SETUP_HEALTH_SOURCE_ENTITIES_PER_ISSUE
    ]
    bounded["source_entities_truncated_count"] = max(
        len(source_entities) - _MAX_SETUP_HEALTH_SOURCE_ENTITIES_PER_ISSUE,
        0,
    )
    return bounded


def _bounded_setup_health_value(value: Any) -> Any:
    if isinstance(value, str):
        return _bounded_setup_health_string(value)
    if isinstance(value, list):
        return [_bounded_setup_health_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_bounded_setup_health_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _bounded_setup_health_value(item) for key, item in value.items()}
    return value


def _bounded_setup_health_string(
    value: str,
    max_length: int = _MAX_SETUP_HEALTH_ATTRIBUTE_STRING_LENGTH,
) -> str:
    if len(value) <= max_length:
        return value
    suffix = "..."
    if max_length <= len(suffix):
        return suffix[:max_length]
    return value[: max_length - len(suffix)] + suffix


def _setup_health_issue_circuits(
    issues: Iterable[Mapping[str, Any]],
    *,
    states: set[str] | None = None,
    issue_keys: set[str] | None = None,
) -> list[str]:
    circuits: list[str] = []
    for issue in issues:
        if states is not None and issue.get("state") not in states:
            continue
        if issue_keys is not None and issue.get("issue") not in issue_keys:
            continue
        circuit_id = issue.get("affected_circuit")
        if circuit_id is not None and circuit_id not in circuits:
            circuits.append(str(circuit_id))
    return circuits


def _setup_health_issue_source_entities(
    issues: Iterable[Mapping[str, Any]],
    *,
    states: set[str] | None = None,
    issue_keys: set[str] | None = None,
) -> list[str]:
    source_entities: list[str] = []
    for issue in issues:
        if states is not None and issue.get("state") not in states:
            continue
        if issue_keys is not None and issue.get("issue") not in issue_keys:
            continue
        for entity_id in issue.get("source_entities", ()):
            if isinstance(entity_id, str) and entity_id not in source_entities:
                source_entities.append(entity_id)
    return source_entities


def _setup_health_severity_count(
    issues: Iterable[Mapping[str, Any]],
    severity: str,
) -> int:
    return sum(1 for issue in issues if issue.get("severity") == severity)


def _setup_health_issue_summary(
    issues: list[dict[str, Any]],
    primary: Mapping[str, Any],
) -> str:
    if not issues:
        return "Ready"
    severity = str(primary.get("severity") or "issue")
    count = len(issues)
    suffix = "" if count == 1 else "s"
    more = "" if count == 1 else f" (+{count - 1} more)"
    prefix = f"{count} {severity}{suffix}: "
    action_length = _MAX_SETUP_HEALTH_ATTRIBUTE_STRING_LENGTH - len(prefix) - len(more)
    action = _bounded_setup_health_string(
        str(primary["recommended_action"]),
        max_length=action_length,
    )
    return f"{prefix}{action}{more}"


def _setup_health_issues(coordinator: Any) -> list[dict[str, Any]]:
    state = getattr(coordinator, "data", None)
    circuits = _setup_health_circuits(coordinator)
    if not circuits:
        return [
            _setup_health_issue(
                "Review circuit assignments",
                "Review circuit assignments",
                None,
                "No circuit assignments are configured.",
                issue="missing_circuit_assignments",
            )
        ]

    issues: list[dict[str, Any]] = []
    for raw_circuit, circuit in circuits:
        circuit_id = circuit.circuit_id
        quality_issue = _setup_health_data_quality_issue(state, circuit)
        if quality_issue is not None:
            issues.append(quality_issue)

        energy_usage_status = _setup_health_status(
            state,
            "energy_usage_evidence_by_circuit",
            circuit_id,
        )
        if energy_usage_status == "waiting_for_delta":
            issues.append(
                _setup_health_learning_issue(
                    state,
                    circuit,
                    energy_usage_status=energy_usage_status,
                )
            )
        else:
            readiness = (
                _readiness_value(state, circuit_id) if state is not None else "ready"
            )
            if readiness == "learning" or _setup_health_learning_in_progress(
                state,
                circuit_id,
            ):
                issues.append(
                    _setup_health_learning_issue(
                        state,
                        circuit,
                        energy_usage_status=energy_usage_status,
                    )
                )

        if _setup_health_needs_capacity_settings(coordinator, raw_circuit):
            issues.append(
                _setup_health_issue(
                    "Configure breaker amps",
                    f"Configure breaker amps for {circuit.name}",
                    circuit,
                    "Capacity tracking needs the circuit breaker or capacity value.",
                    issue="missing_capacity_setting",
                )
            )

        if (
            _setup_health_status(
                state,
                "leg_imbalance_status_by_circuit",
                circuit_id,
            )
            == "not_dual_phase"
        ):
            issues.append(
                _setup_health_issue(
                    "Review circuit assignments",
                    f"Review the circuit mode for {circuit.name}",
                    circuit,
                    (
                        "A dual-phase check is running on a circuit that is not "
                        "dual phase."
                    ),
                    issue="circuit_mode_mismatch",
                )
            )

        if _setup_health_has_missing_mains_status(
            state,
            circuit_id,
        ) and not _has_mains_source(coordinator):
            issues.append(
                _setup_health_issue(
                    "Add mains source",
                    "Add a mains or whole-home source",
                    circuit,
                    "Mains balance, NILM, or solar-flow checks need a mains source.",
                    issue="missing_mains_source",
                )
            )

        if _setup_health_has_ct_direction_status(state, circuit_id):
            issues.append(
                _setup_health_issue(
                    "Check CT direction",
                    f"Check CT direction or power-flow mode for {circuit.name}",
                    circuit,
                    (
                        "Signed power evidence suggests export, reversed CT "
                        "orientation, or a mapping mismatch."
                    ),
                    issue="check_ct_direction",
                )
            )

        utility_comparison_issue = _setup_health_utility_comparison_issue(
            coordinator,
            circuit,
        )
        if utility_comparison_issue is not None:
            issues.append(utility_comparison_issue)

    return _dedupe_setup_health_issues(issues)


def _setup_health_circuits(coordinator: Any) -> tuple[tuple[Any, Any], ...]:
    raw_circuits = tuple(getattr(coordinator, "circuit_configs", ()) or ())
    if not raw_circuits:
        entry_data = getattr(coordinator, "entry_data", {})
        if isinstance(entry_data, Mapping):
            raw_circuits = tuple(entry_data.get(CONF_CIRCUITS, ()) or ())

    circuits: list[tuple[Any, Any]] = []
    for raw_circuit in raw_circuits:
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is not None:
            circuits.append((raw_circuit, circuit))
    return tuple(circuits)


def _setup_health_issue(
    state: str,
    recommended_action: str,
    circuit: Any | None,
    reason: str,
    *,
    issue: str | None = None,
    severity: str = "warning",
    source_entities: Iterable[str] = (),
) -> dict[str, Any]:
    circuit_id = getattr(circuit, "circuit_id", None)
    return {
        "state": state,
        "recommended_action": recommended_action,
        "affected_circuit": circuit_id,
        "affected_circuit_name": getattr(circuit, "name", None),
        "circuit_id": circuit_id,
        "issue": issue or _setup_health_issue_key(state),
        "severity": severity,
        "fix": recommended_action,
        "open_path": SETUP_HEALTH_OPEN_PATH,
        "reason": reason,
        "source_entities": list(dict.fromkeys(source_entities)),
    }


def _setup_health_issue_key(state: str) -> str:
    return str(state).strip().lower().replace(" ", "_").replace("-", "_")


def _setup_health_data_quality_issue(
    state: Any,
    circuit: Any,
) -> dict[str, Any] | None:
    checklist = _setup_health_mapping(
        state,
        "data_quality_checklist_by_circuit",
        circuit.circuit_id,
    )
    data_quality = str(
        getattr(state, "data_quality_by_circuit", {}).get(circuit.circuit_id, "")
        if state is not None
        else ""
    )
    quality_issues = [
        str(issue)
        for issue in (
            checklist.get("quality_issues_full") or checklist.get("quality_issues", [])
            if checklist is not None
            else []
        )
    ]
    issue_text = " ".join([data_quality, *quality_issues]).lower()

    if "missing_source_entities" in issue_text:
        return _setup_health_issue(
            "Add source sensor",
            f"Add at least one source sensor to {circuit.name}",
            circuit,
            "No source sensors are configured for this circuit.",
            issue="missing_source_entities",
        )
    if "negative_real_power_load" in issue_text:
        return _setup_health_issue(
            "Check CT direction",
            f"Check CT direction or power-flow mode for {circuit.name}",
            circuit,
            (
                "A load circuit is reporting sustained negative real power. "
                "That can mean export or a reversed CT."
            ),
            issue="check_ct_direction",
        )
    if checklist is None:
        return None
    if checklist.get("source_data_fresh") is False or "stale" in issue_text:
        return _setup_health_issue(
            "Fix stale source sensor",
            f"Fix stale source sensor data for {circuit.name}",
            circuit,
            "One or more selected source sensors have not updated recently.",
            issue="stale_source",
            source_entities=_source_entities_mentioned_in_issues(
                circuit,
                issue_text,
            ),
        )
    if checklist.get("required_sensors_present") is False or "missing" in issue_text:
        return _setup_health_issue(
            "Review circuit assignments",
            f"Review source sensors for {circuit.name}",
            circuit,
            "A configured circuit is missing a required source sensor.",
            issue="missing_source_sensor",
        )
    if (
        checklist.get("numeric_states_valid") is False
        or "non_numeric" in issue_text
        or "unavailable" in issue_text
    ):
        return _setup_health_issue(
            "Fix stale source sensor",
            f"Fix unavailable or non-numeric source data for {circuit.name}",
            circuit,
            "One or more selected source sensors are unavailable or non-numeric.",
            issue="invalid_source_state",
        )
    if quality_issues:
        return _setup_health_issue(
            "Review circuit assignments",
            f"Review source data for {circuit.name}",
            circuit,
            "A configured circuit has source-data quality issues.",
            issue="source_data_quality",
        )
    return None


def _setup_health_status(state: Any, field_name: str, circuit_id: str) -> str | None:
    value = _setup_health_mapping_value(state, field_name, circuit_id)
    if isinstance(value, Mapping):
        status = value.get("status") or value.get("raw_status")
        return str(status) if status else None
    if value is None:
        return None
    return str(value)


def _setup_health_mapping(
    state: Any,
    field_name: str,
    circuit_id: str,
) -> dict[str, Any] | None:
    value = _setup_health_mapping_value(state, field_name, circuit_id)
    return dict(value) if isinstance(value, Mapping) else None


def _setup_health_mapping_value(state: Any, field_name: str, circuit_id: str) -> Any:
    mapping = getattr(state, field_name, {}) if state is not None else {}
    if not isinstance(mapping, Mapping) or circuit_id not in mapping:
        return None
    return mapping.get(circuit_id)


def _setup_health_learning_in_progress(state: Any, circuit_id: str) -> bool:
    progress = _setup_health_mapping(state, "learning_progress_by_circuit", circuit_id)
    return progress is not None and progress.get("alert_ready") is False


def _setup_health_learning_issue(
    state: Any,
    circuit: Any,
    *,
    energy_usage_status: str | None = None,
) -> dict[str, Any]:
    recommended_action, reason = _setup_health_learning_guidance(
        state,
        circuit,
        energy_usage_status=energy_usage_status,
    )
    return _setup_health_issue(
        "Let analyzer learn",
        recommended_action,
        circuit,
        reason,
        issue="learning",
    )


def _setup_health_learning_guidance(
    state: Any,
    circuit: Any,
    *,
    energy_usage_status: str | None = None,
) -> tuple[str, str]:
    circuit_name = str(
        getattr(circuit, "name", "") or getattr(circuit, "circuit_id", "this circuit")
    )
    if energy_usage_status == "waiting_for_delta":
        energy_evidence = _setup_health_mapping(
            state,
            "energy_usage_evidence_by_circuit",
            getattr(circuit, "circuit_id", ""),
        )
        if (
            isinstance(energy_evidence, Mapping)
            and energy_evidence.get("energy_source") == "derived_from_power"
        ):
            return (
                f"Waiting for another power sample on {circuit_name}",
                (
                    "The automatic kWh helper needs consecutive power samples "
                    "before it can calculate energy use."
                ),
            )
        return (
            f"Waiting for first positive kWh increase on {circuit_name}",
            (
                "A cumulative kWh source is present, but no increase has "
                "been observed yet."
            ),
        )

    progress = _setup_health_mapping(
        state,
        "learning_progress_by_circuit",
        getattr(circuit, "circuit_id", ""),
    )
    if isinstance(progress, Mapping):
        baseline_age_days = _numeric_count(progress.get("baseline_age_days"))
        minimum_days = _minimum_learning_days_for_circuit(circuit)
        if baseline_age_days > 0 and baseline_age_days < minimum_days:
            completed_days = min(int(baseline_age_days), minimum_days)
            return (
                (
                    f"Learning: {completed_days} of {minimum_days} days complete "
                    f"for {circuit_name}"
                ),
                (
                    f"The analyzer has observed {completed_days} of {minimum_days} "
                    "minimum learning days so far."
                ),
            )

        cycle_count = int(_numeric_count(progress.get("cycle_count")))
        minimum_cycles = _minimum_cycles_for_circuit(circuit)
        if cycle_count > 0 and cycle_count < minimum_cycles:
            remaining_cycles = minimum_cycles - cycle_count
            return (
                (
                    f"Learning: {remaining_cycles} more run cycles needed for "
                    f"{circuit_name}"
                ),
                (
                    f"The analyzer has observed {cycle_count} of {minimum_cycles} "
                    "minimum run cycles so far."
                ),
            )

    return (
        f"Let analyzer learn {circuit_name}",
        "The analyzer is still collecting baseline evidence.",
    )


def _minimum_learning_days_for_circuit(circuit: Any) -> int:
    profile = _appliance_profile(circuit)
    if profile is None:
        return 7
    try:
        return max(get_profile_definition(profile).minimum_learning_days, 1)
    except KeyError:
        return 7


def _minimum_cycles_for_circuit(circuit: Any) -> int:
    profile = _appliance_profile(circuit)
    if profile is None:
        return 0
    try:
        return max(get_profile_definition(profile).minimum_cycles, 0)
    except KeyError:
        return 0


def _setup_health_needs_capacity_settings(coordinator: Any, circuit: Any) -> bool:
    roles = _sensor_roles(circuit)
    profile = _appliance_profile(circuit)
    mode = _circuit_mode(circuit)
    has_capacity_input = bool(
        roles & {SensorRole.CURRENT, SensorRole.PEAK_CURRENT}
    ) or (
        SensorRole.REAL_POWER in roles
        and (
            SensorRole.VOLTAGE in roles
            or bool(getattr(coordinator, "_mains_voltage_entity_ids", ()))
        )
    )
    capacity_relevant = (
        mode is CircuitMode.DUAL_PHASE or profile in _HIGH_POWER_PROFILES
    )
    return (
        has_capacity_input
        and capacity_relevant
        and not _stored_settings(coordinator, "capacity_settings_by_circuit", circuit)
    )


def _setup_health_utility_comparison_setup_status(
    coordinator: Any,
    circuit_id: str,
) -> str | None:
    state = getattr(coordinator, "data", None)
    status = _setup_health_status(
        state,
        "utility_comparison_status_by_circuit",
        circuit_id,
    )
    if (
        status not in _UTILITY_COMPARISON_SETUP_STATUSES
        or not _utility_comparison_configured(coordinator, circuit_id)
    ):
        return None
    return status


def _setup_health_utility_comparison_issue(
    coordinator: Any,
    circuit: Any,
) -> dict[str, Any] | None:
    status = _setup_health_utility_comparison_setup_status(
        coordinator,
        circuit.circuit_id,
    )
    if status is None:
        return None
    if status == "missing_utility":
        return _setup_health_issue(
            "Add utility comparison source",
            f"Add utility comparison source for {circuit.name}",
            circuit,
            ("Utility comparison is enabled, but utility kWh has no data."),
            issue="utility_comparison_missing_utility_source",
        )
    if status == "missing_measured":
        return _setup_health_issue(
            "Add measured kWh source",
            f"Add measured kWh source for {circuit.name}",
            circuit,
            ("Utility comparison is enabled, but measured kWh has no data."),
            issue="utility_comparison_missing_measured_source",
        )
    return _setup_health_issue(
        "Review utility comparison",
        f"Review utility comparison source settings for {circuit.name}",
        circuit,
        (
            "Utility comparison is enabled, but the utility source, "
            "measured kWh source, or recorder period cannot be compared."
        ),
        issue="utility_comparison_source_mismatch",
    )


def _setup_health_has_missing_mains_status(state: Any, circuit_id: str) -> bool:
    for field_name in (
        "balance_status_by_circuit",
        "solar_flow_status_by_circuit",
        "solar_surplus_status_by_circuit",
    ):
        if _setup_health_status(state, field_name, circuit_id) == "missing_mains":
            return True
    return False


def _setup_health_has_ct_direction_status(state: Any, circuit_id: str) -> bool:
    for field_name in (
        "balance_status_by_circuit",
        "solar_flow_status_by_circuit",
        "solar_surplus_status_by_circuit",
    ):
        if _setup_health_status(state, field_name, circuit_id) in {
            "inconsistent_export",
            "negative_balance",
        }:
            return True
    return False


def _dedupe_setup_health_issues(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for issue in issues:
        key = (
            issue.get("state"),
            issue.get("affected_circuit"),
            issue.get("reason"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _readiness_value(state: Any, circuit_id: str) -> str:
    readiness = getattr(state, "readiness_by_circuit", {}).get(circuit_id, {})
    if isinstance(readiness, Mapping) and readiness.get("health_status"):
        return str(readiness["health_status"])

    status = getattr(state, "health_status_by_circuit", {}).get(circuit_id)
    if status:
        return str(status)

    if circuit_is_learning(state, circuit_id, default=False):
        return "learning"
    return "ready"


def _numeric_count(value: Any) -> float:
    if isinstance(value, int | float):
        return max(float(value), 0.0)
    return 0.0


def _source_entities_mentioned_in_issues(circuit: Any, issue_text: str) -> list[str]:
    source_entities = _source_entities(circuit)
    mentioned = [
        entity_id for entity_id in source_entities if entity_id.lower() in issue_text
    ]
    return mentioned or source_entities


def _source_entities(circuit: Any) -> list[str]:
    sensors = (
        circuit.get("sensors", ())
        if isinstance(circuit, Mapping)
        else getattr(
            circuit,
            "sensors",
            (),
        )
    )
    source_entities: list[str] = []
    for sensor in sensors or ():
        entity_id = (
            sensor.get("entity_id")
            if isinstance(sensor, Mapping)
            else getattr(
                sensor,
                "entity_id",
                None,
            )
        )
        if (
            isinstance(entity_id, str)
            and entity_id
            and entity_id not in source_entities
        ):
            source_entities.append(entity_id)
    return source_entities


def _sensor_roles(circuit: Any) -> set[SensorRole]:
    sensors = (
        circuit.get("sensors", ())
        if isinstance(circuit, Mapping)
        else getattr(
            circuit,
            "sensors",
            (),
        )
    )
    roles: set[SensorRole] = set()
    for sensor in sensors or ():
        role = (
            sensor.get("role")
            if isinstance(sensor, Mapping)
            else getattr(
                sensor,
                "role",
                None,
            )
        )
        try:
            roles.add(SensorRole(role))
        except (TypeError, ValueError):
            continue
    return roles


def _appliance_profile(circuit: Any) -> ApplianceProfile | None:
    raw_profile = (
        circuit.get("appliance_profile")
        if isinstance(circuit, Mapping)
        else getattr(circuit, "appliance_profile", None)
    )
    raw_profile = str(raw_profile or "").strip().lower()
    try:
        return ApplianceProfile(raw_profile)
    except (TypeError, ValueError):
        return None


def _circuit_mode(circuit: Any) -> CircuitMode | None:
    raw_mode = (
        circuit.get("mode")
        if isinstance(circuit, Mapping)
        else getattr(
            circuit,
            "mode",
            None,
        )
    )
    try:
        return CircuitMode(raw_mode)
    except (TypeError, ValueError):
        return None


def _circuit_id(circuit: Any) -> str:
    if isinstance(circuit, Mapping):
        return str(circuit.get("circuit_id") or circuit.get("id") or "")
    return str(getattr(circuit, "circuit_id", "") or "")


def _stored_settings(coordinator: Any, field_name: str, circuit: Any) -> bool:
    store_data = getattr(coordinator, "store_data", None)
    settings_by_circuit = getattr(store_data, field_name, {}) if store_data else {}
    settings = settings_by_circuit.get(_circuit_id(circuit), {})
    return isinstance(settings, Mapping) and bool(settings)


def _has_mains_source(coordinator: Any) -> bool:
    value = _coordinator_config_value(coordinator, CONF_MAINS_SOURCE_ENTITIES)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(bool(str(item).strip()) for item in value)
    return False


def _utility_comparison_configured(coordinator: Any, circuit_id: str) -> bool:
    store_data = getattr(coordinator, "store_data", None)
    stored_settings = getattr(
        store_data,
        "utility_comparison_settings_by_circuit",
        {},
    )
    if isinstance(stored_settings, Mapping) and stored_settings.get(circuit_id):
        return True

    configured_settings = _coordinator_config_value(
        coordinator,
        CONF_UTILITY_COMPARISON_SETTINGS,
    )
    return isinstance(configured_settings, Mapping) and bool(
        configured_settings.get(circuit_id)
    )


def _coordinator_config_value(coordinator: Any, key: str) -> Any:
    if key == CONF_UTILITY_COMPARISON_SETTINGS:
        merged: dict[str, Any] = {}
        for field_name in ("entry_data", "options"):
            container = getattr(coordinator, field_name, {})
            value = container.get(key) if isinstance(container, Mapping) else None
            if isinstance(value, Mapping):
                merged.update(value)
        if merged:
            return merged
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        if isinstance(container, Mapping) and container.get(key):
            return container[key]
    return None
