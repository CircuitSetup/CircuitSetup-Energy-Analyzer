from __future__ import annotations

from typing import Any

from .. import repairs
from ..context_sources import has_mains_source_configured
from ..state import circuit_is_learning

_DATA_QUALITY_REPAIR_PROBLEMS = frozenset(
    {
        "invalid_source_sensor",
        "invalid_source_timestamp",
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
_UTILITY_COMPARISON_SETUP_REPAIR_PROBLEM_BY_STATUS = {
    "unconfigured": "utility_comparison_source_mismatch",
    "missing_utility": "utility_comparison_missing_utility_source",
    "missing_measured": "utility_comparison_missing_measured_source",
}
class SetupHealthAggregator:
    """Own setup-health repair issue lifecycle side effects."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self.active_repair_issues: set[tuple[str, str]] = set()

    async def async_run_mapping_checks(self) -> None:
        """Run lightweight source mapping checks and refresh setup UX state."""
        coordinator = self._coordinator
        coordinator.mapping_checks_run += 1
        now = coordinator.current_time()
        for config in coordinator.circuit_configs:
            if not config.sensors:
                coordinator.state.data_quality_by_circuit[config.circuit_id] = (
                    "missing_required_sensor"
                )
                await self.async_sync_data_quality_repairs(
                    config.circuit_id,
                    "missing_required_sensor",
                )
            coordinator.ux_state.refresh_config(config, None, now)
        coordinator.async_set_updated_data(coordinator.state)

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
            coordinator.state.data_quality_by_circuit[circuit_id] = issue
            desired.update(
                (circuit_id, data_quality_problem(current_issue))
                for current_issue in sample_or_problem.quality_issues
            )
        else:
            coordinator.state.data_quality_by_circuit.pop(circuit_id, None)
        stale_issue = (circuit_id, "stale_source_sensor")
        if stale_issue in desired and circuit_is_learning(
            coordinator.state,
            circuit_id,
        ):
            desired.discard(stale_issue)

        current = {
            issue
            for issue in self.active_repair_issues
            if issue[0] == circuit_id and issue[1] in _DATA_QUALITY_REPAIR_PROBLEMS
        }
        current.update(
            repairs.existing_circuit_problem_issues(
                coordinator.hass,
                circuit_id,
                _DATA_QUALITY_REPAIR_PROBLEMS,
            )
        )
        for issue in current - desired:
            await repairs.async_delete_data_quality_issue(
                coordinator.hass,
                issue[0],
                issue[1],
            )
            self.active_repair_issues.discard(issue)

        issues_to_create = desired - self.active_repair_issues
        issues_to_create.update(
            issue
            for issue in desired
            if issue[1]
            in {
                "invalid_source_sensor",
                "invalid_source_timestamp",
                "stale_source_sensor",
                "unexpected_negative_real_power",
            }
        )
        for issue in issues_to_create:
            source_entities = (
                self.data_quality_issue_source_entities(
                    sample_or_problem,
                    issue[1],
                )
                if not isinstance(sample_or_problem, str)
                else self.data_quality_repair_source_entities(issue[0])
            )
            await repairs.async_create_data_quality_issue(
                coordinator.hass,
                issue[0],
                issue[1],
                source_entities=source_entities,
                data=self.data_quality_repair_data(
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
        missing_source_entities = self.has_missing_source_entities(circuit_id)
        if missing_source_entities:
            desired.add((circuit_id, "missing_source_entities"))
            utility_comparison_problem = None
        else:
            if (
                self.has_missing_mains_status(circuit_id)
                and not has_mains_source_configured(
                    coordinator.entry_data,
                    coordinator.options,
                )
            ):
                desired.add((circuit_id, "missing_mains_source"))
            if self.has_ct_direction_status(circuit_id):
                desired.add((circuit_id, "check_ct_direction"))
            if (
                coordinator.state.leg_imbalance_status_by_circuit.get(circuit_id)
                == "missing_leg_power"
            ):
                desired.add((circuit_id, "dual_phase_missing_leg"))
            utility_comparison_problem = self.utility_comparison_repair_problem(
                circuit_id
            )
            if utility_comparison_problem is not None:
                desired.add((circuit_id, utility_comparison_problem))

        current = {
            issue
            for issue in self.active_repair_issues
            if issue[0] == circuit_id and issue[1] in _SETUP_HEALTH_REPAIR_PROBLEMS
        }
        current.update(
            repairs.existing_circuit_problem_issues(
                coordinator.hass,
                circuit_id,
                _SETUP_HEALTH_REPAIR_PROBLEMS,
            )
        )
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
                data=self.repair_data(issue[0], issue[1]),
            )
            self.active_repair_issues.add(issue)

    def data_quality_repair_data(
        self,
        circuit_id: str,
        problem: str,
        source_entities: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        return {
            "circuit_name": str(circuit_name),
            "reason": self.data_quality_repair_reason(problem),
            "recommended_action": self.data_quality_repair_action(
                circuit_name,
                problem,
            ),
            "source_entities": list(dict.fromkeys(source_entities)),
        }

    def data_quality_repair_reason(self, problem: str) -> str:
        reasons = {
            "missing_required_sensor": (
                "A configured circuit is missing a required source sensor."
            ),
            "invalid_source_sensor": (
                "One or more selected source sensors are unavailable or invalid."
            ),
            "invalid_source_timestamp": (
                "One or more selected source sensors report an invalid update "
                "timestamp."
            ),
            "missing_source_entities": (
                "The integration has no configured source sensors."
            ),
            "stale_source_sensor": (
                "One or more selected source sensors have not updated recently."
            ),
            "unexpected_negative_real_power": (
                "A load circuit is reporting sustained negative real power."
            ),
        }
        return reasons.get(problem, "A configured circuit has source-data issues.")

    def data_quality_repair_action(self, circuit_name: str, problem: str) -> str:
        actions = {
            "missing_required_sensor": f"Review source sensors for {circuit_name}",
            "invalid_source_sensor": (
                f"Fix unavailable or invalid source data for {circuit_name}"
            ),
            "invalid_source_timestamp": (
                f"Fix source sensor timestamps for {circuit_name}"
            ),
            "missing_source_entities": (
                f"Add at least one source sensor for {circuit_name}"
            ),
            "stale_source_sensor": f"Fix stale source sensor data for {circuit_name}",
            "unexpected_negative_real_power": (
                f"Check CT direction or power-flow mode for {circuit_name}"
            ),
        }
        return actions.get(problem, f"Review source data for {circuit_name}")

    def data_quality_repair_source_entities(self, circuit_id: str) -> list[str]:
        return self.source_entities(circuit_id)

    def data_quality_issue_source_entities(
        self,
        sample: Any,
        problem: str,
    ) -> list[str]:
        source_entities = list(sample.source_entity_ids)
        matching_entities = {
            issue.split(" ", 1)[0]
            for issue in sample.quality_issues
            if data_quality_problem(issue) == problem
        }
        return [
            entity_id for entity_id in source_entities if entity_id in matching_entities
        ] or source_entities

    def repair_data(self, circuit_id: str, problem: str) -> dict[str, Any]:
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        recommended_actions = {
            "missing_energy_source": (
                f"Add a cumulative kWh sensor to {circuit_name}"
            ),
            "missing_source_entities": (
                f"Add at least one source sensor to {circuit_name}"
            ),
            "missing_mains_source": "Add a mains or whole-home source",
            "missing_electrical_metrics": (
                f"Add matching electrical metrics for {circuit_name}"
            ),
            "check_ct_direction": (
                f"Check CT direction or power-flow mode for {circuit_name}"
            ),
            "dual_phase_missing_leg": (
                f"Review leg A and leg B source sensors for {circuit_name}"
            ),
            "missing_rain_context_source": f"Add a rain sensor for {circuit_name}",
            "missing_water_flow_source": f"Add a water-flow sensor for {circuit_name}",
            "utility_comparison_source_mismatch": (
                f"Review utility comparison source settings for {circuit_name}"
            ),
            "utility_comparison_missing_utility_source": (
                f"Add utility comparison source for {circuit_name}"
            ),
            "utility_comparison_missing_measured_source": (
                f"Add measured kWh source for {circuit_name}"
            ),
        }
        return {
            "circuit_name": str(circuit_name),
            "reason": self.repair_reason(circuit_id, problem),
            "recommended_action": recommended_actions.get(
                problem,
                f"Review setup for {circuit_name}",
            ),
            "source_entities": self.repair_source_entities(circuit_id, problem),
        }

    def repair_reason(self, circuit_id: str, problem: str) -> str:
        config = self._coordinator.circuit_registry.config_for_circuit(circuit_id)
        circuit_name = getattr(config, "name", None) or circuit_id
        reasons = {
            "missing_energy_source": (
                "Daily Energy Usage needs a cumulative energy source."
            ),
            "missing_source_entities": (
                "No source sensors are configured for this circuit."
            ),
            "missing_mains_source": (
                "Mains balance, NILM, or solar-flow checks need a mains source."
            ),
            "missing_electrical_metrics": (
                "Power Metric Consistency needs matching supporting sensors."
            ),
            "check_ct_direction": (
                "Signed power evidence suggests export, reversed CT orientation, "
                "or a mapping mismatch."
            ),
            "dual_phase_missing_leg": (
                "One side of this dual-phase circuit is missing real-power data."
            ),
            "missing_rain_context_source": (
                "Rain-pump context is enabled, but no rain source is configured."
            ),
            "missing_water_flow_source": (
                "Water-flow context is enabled, but no flow source is configured."
            ),
            "utility_comparison_source_mismatch": (
                "Utility comparison sources or recorder periods cannot be compared."
            ),
            "utility_comparison_missing_utility_source": (
                "Utility comparison is enabled, but utility kWh has no data."
            ),
            "utility_comparison_missing_measured_source": (
                "Utility comparison is enabled, but measured kWh has no data."
            ),
        }
        return reasons.get(problem, f"Review setup for {circuit_name}.")

    def has_missing_source_entities(self, circuit_id: str) -> bool:
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        if config is not None and not self.source_entities(circuit_id):
            return True
        return (
            str(coordinator.state.data_quality_by_circuit.get(circuit_id, ""))
            == "missing_source_entities"
        )

    def source_entities(self, circuit_id: str) -> list[str]:
        config = self._coordinator.circuit_registry.config_for_circuit(circuit_id)
        if config is None:
            return []
        return [
            sensor.entity_id
            for sensor in getattr(config, "sensors", ())
            if isinstance(getattr(sensor, "entity_id", None), str)
            and sensor.entity_id
        ]

    def repair_source_entities(self, circuit_id: str, problem: str) -> list[str]:
        source_entities = self.source_entities(circuit_id)
        if problem == "dual_phase_missing_leg":
            return source_entities
        if problem in {
            "missing_energy_source",
            "missing_electrical_metrics",
            "check_ct_direction",
        }:
            return source_entities
        return []

    def has_missing_mains_status(self, circuit_id: str) -> bool:
        for field_name in (
            "balance_status_by_circuit",
            "solar_flow_status_by_circuit",
            "solar_surplus_status_by_circuit",
        ):
            if getattr(self._coordinator.state, field_name, {}).get(
                circuit_id
            ) == "missing_mains":
                return True
        return False

    def has_ct_direction_status(self, circuit_id: str) -> bool:
        for field_name in (
            "balance_status_by_circuit",
            "solar_flow_status_by_circuit",
            "solar_surplus_status_by_circuit",
        ):
            if getattr(self._coordinator.state, field_name, {}).get(circuit_id) in {
                "inconsistent_export",
                "negative_balance",
            }:
                return True
        return False

    def utility_comparison_repair_problem(self, circuit_id: str) -> str | None:
        status = self._coordinator.state.utility_comparison_status_by_circuit.get(
            circuit_id
        )
        return _UTILITY_COMPARISON_SETUP_REPAIR_PROBLEM_BY_STATUS.get(str(status))


def data_quality_problem(issue: str) -> str:
    issue_parts = str(issue).strip().lower().rsplit(maxsplit=1)
    issue_kind = issue_parts[-1] if issue_parts else ""
    return {
        "missing": "missing_required_sensor",
        "unavailable": "invalid_source_sensor",
        "non_numeric": "invalid_source_sensor",
        "non_finite": "invalid_source_sensor",
        "naive_timestamp": "invalid_source_timestamp",
        "future_timestamp": "invalid_source_timestamp",
        "stale": "stale_source_sensor",
        "negative_real_power_load": "unexpected_negative_real_power",
    }.get(issue_kind, "missing_required_sensor")
