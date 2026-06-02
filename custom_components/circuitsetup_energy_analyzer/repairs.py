from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from .const import DOMAIN
from .models import Severity


def issue_id_for_circuit_problem(circuit_id: str, problem: str) -> str:
    """Return a stable Repairs issue id for a circuit setup/data-quality problem."""
    return _tuple_id(DOMAIN, circuit_id, problem)


async def async_create_data_quality_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
    severity: Severity | str = Severity.WARNING,
) -> None:
    """Create a Home Assistant Repairs issue for data quality/config problems."""
    try:
        from homeassistant.helpers import issue_registry as ir
    except ModuleNotFoundError:
        return

    create_issue = getattr(ir, "async_create_issue", None)
    if create_issue is None:
        return

    issue_severity = _ha_issue_severity(ir, severity)
    create_issue(
        hass,
        DOMAIN,
        issue_id_for_circuit_problem(circuit_id, problem),
        is_fixable=False,
        is_persistent=True,
        severity=issue_severity,
        translation_key=problem,
        data={"circuit_id": circuit_id},
    )


async def async_delete_data_quality_issue(
    hass: Any,
    circuit_id: str,
    problem: str,
) -> None:
    """Delete a Home Assistant Repairs issue for a resolved data-quality problem."""
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


def _tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(_readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def _readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"
