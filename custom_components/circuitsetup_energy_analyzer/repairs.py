from __future__ import annotations

import inspect
import json
import re
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from .const import DOMAIN
from .models import Severity

REPAIR_OPEN_PATH = "/config/integrations/integration/circuitsetup_energy_analyzer"

_REPAIR_FIXES: dict[str, str] = {
    "missing_source_entities": "Add at least one source sensor in integration options.",
    "missing_required_sensor": (
        "Review circuit assignments and replace the missing source sensor."
    ),
    "phase_mismatch": "Review the selected split-phase channels and CT orientation.",
    "stale_source_sensor": "Restore updates from the stale source sensor.",
    "missing_energy_source": "Add a cumulative kWh source for this circuit.",
    "missing_mains_source": "Add aggregate mains or whole-home source sensors.",
    "missing_electrical_metrics": (
        "Add the supporting watts, amps, voltage, apparent power, or power factor "
        "inputs for this circuit."
    ),
    "check_ct_direction": "Review CT direction and the configured power-flow mode.",
    "dual_phase_missing_leg": "Review the selected leg A and leg B source sensors.",
    "missing_rain_context_source": (
        "Add a rain source or disable rain-pump context for this circuit."
    ),
    "missing_water_flow_source": (
        "Add a water-flow source or disable water-flow context for this circuit."
    ),
    "utility_comparison_source_mismatch": (
        "Review utility comparison source and measured kWh settings."
    ),
    "utility_comparison_missing_utility_source": (
        "Add or repair the utility, Opower, or recorder statistics kWh source."
    ),
    "utility_comparison_missing_measured_source": (
        "Add or repair the local measured cumulative kWh source."
    ),
    "unexpected_negative_real_power": (
        "Check CT orientation or change the circuit power-flow mode if export is "
        "expected."
    ),
    "missing_mains_nilm_sensor": "Review mains NILM source sensors.",
    "low_nilm_confidence": (
        "Review overlapping NILM events before acting on signatures."
    ),
}


def issue_id_for_circuit_problem(circuit_id: str, problem: str) -> str:
    """Return a stable Repairs issue id for a circuit setup/data-quality problem."""
    return _tuple_id(DOMAIN, circuit_id, problem)


async def async_create_data_quality_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
    severity: Severity | str = Severity.WARNING,
    source_entities: Iterable[str] = (),
) -> None:
    """Create a Home Assistant Repairs issue for data quality/config problems."""
    await async_create_circuit_issue(
        hass,
        circuit_id,
        problem,
        severity=severity,
        source_entities=source_entities,
    )


async def async_create_circuit_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
    severity: Severity | str = Severity.WARNING,
    source_entities: Iterable[str] = (),
    data: Mapping[str, Any] | None = None,
) -> None:
    """Create a Home Assistant Repairs issue for one circuit problem."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except ModuleNotFoundError:
        return

    create_issue = getattr(ir, "async_create_issue", None)
    if create_issue is None:
        return

    issue_severity = _ha_issue_severity(ir, severity)
    issue_data = _repair_issue_data(
        circuit_id,
        problem,
        source_entities=source_entities,
        data=data,
    )
    kwargs: dict[str, Any] = {
        "is_fixable": False,
        "is_persistent": True,
        "severity": issue_severity,
        "translation_key": problem,
        "data": issue_data,
    }
    if _call_accepts_keyword(create_issue, "translation_placeholders"):
        kwargs["translation_placeholders"] = _repair_translation_placeholders(
            issue_data
        )

    create_issue(
        hass,
        DOMAIN,
        issue_id_for_circuit_problem(circuit_id, problem),
        **kwargs,
    )


async def async_delete_data_quality_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
) -> None:
    """Delete a Home Assistant Repairs issue for a resolved data-quality problem."""
    await async_delete_circuit_issue(hass, circuit_id, problem)


async def async_delete_circuit_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
) -> None:
    """Delete a Home Assistant Repairs issue for a resolved circuit problem."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except ModuleNotFoundError:
        return

    delete_issue = getattr(ir, "async_delete_issue", None)
    if delete_issue is None:
        return

    delete_issue(hass, DOMAIN, issue_id_for_circuit_problem(circuit_id, problem))


def _ha_issue_severity(issue_registry: Any, severity: Severity | str) -> Any:
    issue_severity = getattr(issue_registry, "IssueSeverity", None)
    value = severity.value if isinstance(severity, Severity) else str(severity)
    if value not in {Severity.WARNING.value, Severity.ERROR.value}:
        value = Severity.WARNING.value
    if issue_severity is None:
        return value

    return getattr(issue_severity, value.upper(), value)


def _repair_issue_data(
    circuit_id: str,
    problem: str,
    *,
    source_entities: Iterable[str] = (),
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fix = _REPAIR_FIXES.get(
        problem,
        "Review this circuit in integration options.",
    )
    issue_data = {
        "circuit_id": circuit_id,
        "circuit_name": circuit_id,
        "problem": problem,
        "fix": fix,
        "open_path": REPAIR_OPEN_PATH,
        "recommended_action": fix,
        "source_entities": _dedupe_strings(source_entities),
    }
    if data is not None:
        issue_data.update(dict(data))
    return issue_data


def _repair_translation_placeholders(issue_data: Mapping[str, Any]) -> dict[str, str]:
    source_entities = issue_data.get("source_entities", ())
    source_text = (
        ", ".join(str(entity_id) for entity_id in source_entities)
        if source_entities
        else "none"
    )
    return {
        "circuit_id": str(issue_data.get("circuit_id", "")),
        "circuit_name": str(issue_data.get("circuit_name", "")),
        "fix": str(issue_data.get("fix", "")),
        "open_path": str(issue_data.get("open_path", "")),
        "recommended_action": str(issue_data.get("recommended_action", "")),
        "source_entities": source_text,
    }


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _call_accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    try:
        parameters = inspect.signature(callable_obj).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == keyword
        for parameter in parameters
    )


def _tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(_readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def _readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"
