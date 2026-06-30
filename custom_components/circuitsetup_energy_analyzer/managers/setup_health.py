from __future__ import annotations

from typing import Any

from .. import repairs

_DATA_QUALITY_REPAIR_PROBLEMS = frozenset(
    {
        "missing_required_sensor",
        "stale_source_sensor",
        "unexpected_negative_real_power",
    }
)
_SETUP_HEALTH_REPAIR_PROBLEMS = frozenset(
    {
        "missing_source_entities",
        "missing_energy_source",
        "missing_mains_source",
        "missing_electrical_metrics",
        "check_ct_direction",
        "dual_phase_missing_leg",
        "missing_rain_context_source",
        "missing_water_flow_source",
        "utility_comparison_source_mismatch",
        "utility_comparison_missing_utility_source",
        "utility_comparison_missing_measured_source",
    }
)


class SetupHealthAggregator:
    """Own setup-health repair issue lifecycle side effects."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self.active_repair_issues: set[tuple[str, str]] = set()

    async def async_sync_data_quality_repairs(
        self,
        circuit_id: str,
        sample_or_problem: Any,
    ) -> None:
        """Create/delete data-quality repair issues for one circuit."""
        coordinator = self._coordinator
        desired: set[tuple[str, str]] = set()
        if isinstance(sample_or_problem, str):
            coordinator.state.data_quality_by_circuit[circuit_id] = sample_or_problem
            desired.add((circuit_id, sample_or_problem))
        elif sample_or_problem.quality_issues:
            issue = sample_or_problem.quality_issues[0]
            problem = data_quality_problem(issue)
            coordinator.state.data_quality_by_circuit[circuit_id] = issue
            desired.add((circuit_id, problem))
        else:
            coordinator.state.data_quality_by_circuit.pop(circuit_id, None)

        current = {
            issue
            for issue in self.active_repair_issues
            if issue[0] == circuit_id and issue[1] in _DATA_QUALITY_REPAIR_PROBLEMS
        }
        for issue in current - desired:
            await repairs.async_delete_data_quality_issue(
                coordinator.hass,
                issue[0],
                issue[1],
            )
            self.active_repair_issues.discard(issue)

        for issue in desired - self.active_repair_issues:
            source_entities = (
                sample_or_problem.source_entity_ids
                if not isinstance(sample_or_problem, str)
                else coordinator._data_quality_repair_source_entities(issue[0])
            )
            await repairs.async_create_data_quality_issue(
                coordinator.hass,
                issue[0],
                issue[1],
                source_entities=source_entities,
                data=coordinator._data_quality_repair_data(
                    issue[0],
                    issue[1],
                    source_entities,
                ),
            )
            self.active_repair_issues.add(issue)

    async def async_sync_setup_health_repairs(self, circuit_id: str) -> None:
        """Create/delete setup-health repair issues for one circuit."""
        coordinator = self._coordinator
        desired: set[tuple[str, str]] = set()
        missing_source_entities = coordinator._setup_health_has_missing_source_entities(
            circuit_id,
        )
        if missing_source_entities:
            desired.add((circuit_id, "missing_source_entities"))
            utility_comparison_problem = None
        else:
            dashboard_status = coordinator.state.energy_dashboard_status_by_circuit.get(
                circuit_id
            )
            if dashboard_status in {"needs_energy_source", "power_ready"}:
                desired.add((circuit_id, "missing_energy_source"))
            if (
                coordinator._setup_health_has_missing_mains_status(circuit_id)
                and not coordinator._has_mains_source_configured()
            ):
                desired.add((circuit_id, "missing_mains_source"))
            if (
                coordinator.state.metric_consistency_status_by_circuit.get(circuit_id)
                == "missing_metrics"
            ):
                desired.add((circuit_id, "missing_electrical_metrics"))
            if coordinator._setup_health_has_ct_direction_status(circuit_id):
                desired.add((circuit_id, "check_ct_direction"))
            if (
                coordinator.state.leg_imbalance_status_by_circuit.get(circuit_id)
                == "missing_leg_power"
            ):
                desired.add((circuit_id, "dual_phase_missing_leg"))
            if coordinator._setup_health_has_missing_rain_context_source(circuit_id):
                desired.add((circuit_id, "missing_rain_context_source"))
            if coordinator._setup_health_has_missing_water_flow_source(circuit_id):
                desired.add((circuit_id, "missing_water_flow_source"))
            utility_comparison_problem = (
                coordinator._setup_health_utility_comparison_repair_problem(circuit_id)
            )
            if utility_comparison_problem is not None:
                desired.add((circuit_id, utility_comparison_problem))

        current = {
            issue
            for issue in self.active_repair_issues
            if issue[0] == circuit_id and issue[1] in _SETUP_HEALTH_REPAIR_PROBLEMS
        }
        if (
            utility_comparison_problem
            in {
                "utility_comparison_missing_utility_source",
                "utility_comparison_missing_measured_source",
            }
            and (circuit_id, utility_comparison_problem)
            not in self.active_repair_issues
        ):
            current.add((circuit_id, "utility_comparison_source_mismatch"))
        for issue in sorted(current - desired):
            await repairs.async_delete_circuit_issue(
                coordinator.hass,
                issue[0],
                issue[1],
            )
            self.active_repair_issues.discard(issue)

        for issue in sorted(desired - self.active_repair_issues):
            await repairs.async_create_circuit_issue(
                coordinator.hass,
                issue[0],
                issue[1],
                data=coordinator._setup_health_repair_data(issue[0], issue[1]),
            )
            self.active_repair_issues.add(issue)


def data_quality_problem(issue: str) -> str:
    issue_text = issue.lower()
    if "negative_real_power_load" in issue_text:
        return "unexpected_negative_real_power"
    if "stale" in issue_text:
        return "stale_source_sensor"
    return "missing_required_sensor"
