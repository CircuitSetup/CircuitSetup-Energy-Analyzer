from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_EXPECTS_WATER_FLOW,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
)
from ..entity import circuit_info_from_config
from ..models import ApplianceProfile, CircuitMode, SensorRole
from ..profiles import get_profile_definition

SETUP_HEALTH_OPEN_PATH = "/config/integrations/integration/circuitsetup_energy_analyzer"

_WEATHER_CONTEXT_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.HVAC_BLOWER,
    ApplianceProfile.ELECTRIC_HEAT,
}
_HIGH_POWER_PROFILES = {
    ApplianceProfile.HVAC,
    ApplianceProfile.HVAC_COMPRESSOR,
    ApplianceProfile.ELECTRIC_HEAT,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.OVEN,
    ApplianceProfile.MICROWAVE,
    ApplianceProfile.DRYER,
    ApplianceProfile.POOL_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.EV_CHARGER,
    ApplianceProfile.SOLAR_INVERTER,
    ApplianceProfile.MAINS_NILM,
}
_PUMP_WATER_CONTEXT_PROFILES = {
    ApplianceProfile.SUMP_PUMP,
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
}
_FLOW_WATER_CONTEXT_PROFILES = {
    ApplianceProfile.WATER_PUMP,
    ApplianceProfile.WELL_PUMP,
    ApplianceProfile.WATER_HEATER,
    ApplianceProfile.WASHER,
}
_UTILITY_COMPARISON_SETUP_STATUSES = {
    "unconfigured",
    "missing_utility",
    "missing_measured",
}


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
            "attributes": _setup_health_attributes_for_issues(issues, primary),
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
        "attributes": _setup_health_attributes_for_issues([], primary),
    }


def _setup_health_attributes_for_issues(
    issues: list[dict[str, Any]],
    primary: Mapping[str, Any],
) -> dict[str, Any]:
    affected_circuits = _setup_health_issue_circuits(issues)
    ready = not issues
    return {
        "blocking_issue_count": len(issues),
        "issue_count": len(issues),
        "warning_count": _setup_health_severity_count(issues, "warning"),
        "ready": ready,
        "next_step": primary["recommended_action"],
        "recommended_action": primary["recommended_action"],
        "primary_issue": primary.get("issue"),
        "primary_severity": primary.get("severity"),
        "issue_summary": _setup_health_issue_summary(issues, primary),
        "affected_circuit": primary["affected_circuit"],
        "affected_circuit_name": primary["affected_circuit_name"],
        "affected_circuits": affected_circuits,
        "open_path": primary["open_path"],
        "reason": primary["reason"],
        "learning_circuits": _setup_health_issue_circuits(
            issues,
            states={"Let analyzer learn"},
        ),
        "stale_sources": _setup_health_issue_source_entities(
            issues,
            states={"Fix stale source sensor"},
        ),
        "stale_source_circuits": _setup_health_issue_circuits(
            issues,
            states={"Fix stale source sensor"},
        ),
        "stale_source_entities": _setup_health_issue_source_entities(
            issues,
            states={"Fix stale source sensor"},
        ),
        "missing_energy_sources": _setup_health_issue_circuits(
            issues,
            states={"Add cumulative kWh source"},
        ),
        "negative_power_loads": _setup_health_issue_circuits(
            issues,
            states={"Check CT direction"},
        ),
        "dual_phase_missing_legs": _setup_health_issue_circuits(
            issues,
            issue_keys={"dual_phase_missing_leg"},
        ),
        "missing_rain_sources": _setup_health_issue_circuits(
            issues,
            issue_keys={"missing_rain_context_source"},
        ),
        "missing_water_flow_sources": _setup_health_issue_circuits(
            issues,
            issue_keys={"missing_water_flow_source"},
        ),
        "utility_comparison_setup_issues": _setup_health_issue_circuits(
            issues,
            issue_keys={"utility_comparison_source_mismatch"},
        ),
        "issues": issues,
    }


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
    return f"{count} {severity}{suffix}: {primary['recommended_action']}{more}"


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

        energy_status = _setup_health_status(
            state,
            "energy_dashboard_status_by_circuit",
            circuit_id,
        )
        if energy_status in {"needs_energy_source", "power_ready"}:
            issues.append(
                _setup_health_issue(
                    "Add cumulative kWh source",
                    f"Add a cumulative kWh sensor to {circuit.name}",
                    circuit,
                    "Daily Energy Usage needs a cumulative energy source.",
                    issue="missing_energy_source",
                )
            )

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

        if _setup_health_needs_temperature_source(coordinator, raw_circuit):
            issues.append(
                _setup_health_issue(
                    "Add outdoor temperature source",
                    f"Add an outdoor temperature source for {circuit.name}",
                    circuit,
                    "HVAC weather context needs an outdoor temperature source.",
                    issue="missing_temperature_source",
                )
            )

        if _setup_health_status(
            state,
            "leg_imbalance_status_by_circuit",
            circuit_id,
        ) == "not_dual_phase":
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

        if _setup_health_status(
            state,
            "metric_consistency_status_by_circuit",
            circuit_id,
        ) == "missing_metrics":
            issues.append(
                _setup_health_issue(
                    "Review circuit assignments",
                    f"Add matching electrical metrics for {circuit.name}",
                    circuit,
                    (
                        "Power Metric Consistency needs matching real power, apparent "
                        "power, voltage, current, or power factor sensors."
                    ),
                    issue="missing_electrical_metrics",
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

        if _setup_health_needs_rain_context_source(coordinator, raw_circuit):
            issues.append(
                _setup_health_issue(
                    "Add rain source",
                    f"Add a rain sensor for {circuit.name}",
                    circuit,
                    (
                        "Rain-pump context is enabled, but no rain or rain-intensity "
                        "source is configured."
                    ),
                    issue="missing_rain_context_source",
                )
            )

        if _setup_health_needs_water_flow_source(coordinator, raw_circuit):
            issues.append(
                _setup_health_issue(
                    "Add water-flow source",
                    f"Add a water-flow sensor for {circuit.name}",
                    circuit,
                    (
                        "Water-flow context is enabled, but no linked or global "
                        "flow source is configured."
                    ),
                    issue="missing_water_flow_source",
                )
            )

        if _setup_health_has_utility_comparison_setup_status(coordinator, circuit_id):
            issues.append(
                _setup_health_issue(
                    "Review utility comparison",
                    f"Review utility comparison source settings for {circuit.name}",
                    circuit,
                    (
                        "Utility comparison is enabled, but the utility source, "
                        "measured kWh source, or recorder period cannot be compared."
                    ),
                    issue="utility_comparison_source_mismatch",
                )
            )

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
            checklist.get("quality_issues", []) if checklist is not None else []
        )
    ]
    issue_text = " ".join([data_quality, *quality_issues]).lower()

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
    if (
        checklist.get("required_sensors_present") is False
        or "missing" in issue_text
    ):
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
        getattr(circuit, "name", "")
        or getattr(circuit, "circuit_id", "this circuit")
    )
    if energy_usage_status == "waiting_for_delta":
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
    has_capacity_input = SensorRole.CURRENT in roles or (
        SensorRole.REAL_POWER in roles and SensorRole.VOLTAGE in roles
    )
    capacity_relevant = (
        mode is CircuitMode.DUAL_PHASE or profile in _HIGH_POWER_PROFILES
    )
    return (
        has_capacity_input
        and capacity_relevant
        and not _stored_settings(coordinator, "capacity_settings_by_circuit", circuit)
    )


def _setup_health_needs_temperature_source(coordinator: Any, circuit: Any) -> bool:
    profile = _appliance_profile(circuit)
    return profile in _WEATHER_CONTEXT_PROFILES and not _has_temperature_source(
        coordinator,
    )


def _setup_health_needs_rain_context_source(coordinator: Any, circuit: Any) -> bool:
    profile = _appliance_profile(circuit)
    return (
        profile in _PUMP_WATER_CONTEXT_PROFILES
        and _advanced_setting_bool(
            coordinator,
            circuit,
            CONF_RAIN_PUMP_CORRELATION_ENABLED,
            default=True,
        )
        and not _has_any_configured_entity(
            coordinator,
            CONF_RAIN_SENSOR_ENTITY,
            CONF_RAIN_INTENSITY_ENTITY,
        )
    )


def _setup_health_needs_water_flow_source(coordinator: Any, circuit: Any) -> bool:
    profile = _appliance_profile(circuit)
    return (
        profile in _FLOW_WATER_CONTEXT_PROFILES
        and _advanced_setting_bool(
            coordinator,
            circuit,
            CONF_WATER_FLOW_CORRELATION_ENABLED,
            default=True,
        )
        and _advanced_setting_bool(
            coordinator,
            circuit,
            CONF_EXPECTS_WATER_FLOW,
            default=True,
        )
        and not _has_any_configured_entity(
            coordinator,
            CONF_LINKED_FLOW_SENSOR_ENTITIES,
            CONF_WATER_FLOW_SENSOR_ENTITIES,
        )
    )


def _setup_health_has_utility_comparison_setup_status(
    coordinator: Any,
    circuit_id: str,
) -> bool:
    state = getattr(coordinator, "data", None)
    status = _setup_health_status(
        state,
        "utility_comparison_status_by_circuit",
        circuit_id,
    )
    return (
        status in _UTILITY_COMPARISON_SETUP_STATUSES
        and _utility_comparison_configured(coordinator, circuit_id)
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

    if getattr(state, "learning_by_circuit", {}).get(circuit_id) is True:
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
    sensors = circuit.get("sensors", ()) if isinstance(circuit, Mapping) else getattr(
        circuit,
        "sensors",
        (),
    )
    source_entities: list[str] = []
    for sensor in sensors or ():
        entity_id = sensor.get("entity_id") if isinstance(sensor, Mapping) else getattr(
            sensor,
            "entity_id",
            None,
        )
        if (
            isinstance(entity_id, str)
            and entity_id
            and entity_id not in source_entities
        ):
            source_entities.append(entity_id)
    return source_entities


def _sensor_roles(circuit: Any) -> set[SensorRole]:
    sensors = circuit.get("sensors", ()) if isinstance(circuit, Mapping) else getattr(
        circuit,
        "sensors",
        (),
    )
    roles: set[SensorRole] = set()
    for sensor in sensors or ():
        role = sensor.get("role") if isinstance(sensor, Mapping) else getattr(
            sensor,
            "role",
            None,
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
    raw_profile = _appliance_profile_alias(str(raw_profile or ""))
    try:
        return ApplianceProfile(raw_profile)
    except (TypeError, ValueError):
        return None


def _appliance_profile_alias(raw_profile: str) -> str:
    normalized = raw_profile.strip().lower()
    aliases = {
        "hvac_system": ApplianceProfile.HVAC.value,
        "ac": ApplianceProfile.HVAC_COMPRESSOR.value,
        "a_c": ApplianceProfile.HVAC_COMPRESSOR.value,
        "ac_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "a_c_compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "air_conditioner": ApplianceProfile.HVAC_COMPRESSOR.value,
        "compressor": ApplianceProfile.HVAC_COMPRESSOR.value,
        "heat_pump": ApplianceProfile.HVAC_COMPRESSOR.value,
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
        "vehicle_charger": ApplianceProfile.EV_CHARGER.value,
        "vehicle_charging": ApplianceProfile.EV_CHARGER.value,
        "level2_charger": ApplianceProfile.EV_CHARGER.value,
        "level_2_charger": ApplianceProfile.EV_CHARGER.value,
        "wall_connector": ApplianceProfile.EV_CHARGER.value,
    }
    return aliases.get(normalized, normalized)


def _circuit_mode(circuit: Any) -> CircuitMode | None:
    raw_mode = circuit.get("mode") if isinstance(circuit, Mapping) else getattr(
        circuit,
        "mode",
        None,
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


def _advanced_settings(coordinator: Any, circuit: Any) -> Mapping[str, Any]:
    circuit_id = _circuit_id(circuit)
    settings = _coordinator_config_value(coordinator, CONF_ADVANCED_SETTINGS)
    if isinstance(settings, Mapping):
        circuit_settings = settings.get(circuit_id, {})
        if isinstance(circuit_settings, Mapping):
            return circuit_settings
    return {}


def _advanced_setting_bool(
    coordinator: Any,
    circuit: Any,
    key: str,
    *,
    default: bool,
) -> bool:
    value = _advanced_settings(coordinator, circuit).get(key, default)
    return bool(value)


def _has_temperature_source(coordinator: Any) -> bool:
    value = _coordinator_config_value(coordinator, CONF_OUTDOOR_TEMPERATURE_ENTITY)
    return value is not None and bool(str(value).strip())


def _has_mains_source(coordinator: Any) -> bool:
    value = _coordinator_config_value(coordinator, CONF_MAINS_SOURCE_ENTITIES)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(bool(str(item).strip()) for item in value)
    return False


def _has_any_configured_entity(coordinator: Any, *keys: str) -> bool:
    for key in keys:
        value = _coordinator_config_value(coordinator, key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, tuple, set)) and any(
            bool(str(item).strip()) for item in value
        ):
            return True
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
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        if isinstance(container, Mapping) and container.get(key):
            return container[key]
    return None
