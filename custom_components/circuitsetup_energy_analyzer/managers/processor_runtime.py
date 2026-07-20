from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..activity_alerts import ActivityAlertSettings
from ..billing import BillingCycleSettings
from ..capacity import CapacitySettings
from ..cost import CostSettings
from ..demand import DemandSettings
from ..goals import EnergyGoalSettings
from ..models import CircuitConfig, EventType
from ..profiles import get_profile_definition
from ..standby import StandbySettings
from ..usage import EnergyUsageSettings
from ..utility_comparison import UtilityComparisonSettings


class ProcessorRuntimeManager:
    """Provide processor-facing settings and runtime policy callbacks."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def activity_alert_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> ActivityAlertSettings:
        return self._coordinator.settings_controller.activity_alert_settings_for_config(
            config,
            circuit_id,
        )

    def energy_usage_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyUsageSettings:
        return self._coordinator.settings_controller.energy_usage_settings_for_config(
            config,
            circuit_id,
        )

    def energy_goal_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> EnergyGoalSettings:
        return self._coordinator.settings_controller.energy_goal_settings_for_config(
            config,
            circuit_id,
        )

    def billing_cycle_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> BillingCycleSettings:
        return self._coordinator.settings_controller.billing_cycle_settings_for_config(
            config,
            circuit_id,
        )

    def cost_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> CostSettings:
        return self._coordinator.settings_controller.cost_settings_for_config(
            config,
            circuit_id,
        )

    def demand_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> DemandSettings:
        return self._coordinator.settings_controller.demand_settings_for_config(
            config,
            circuit_id,
        )

    def capacity_settings_for_config(self, circuit_id: str) -> CapacitySettings:
        return self._coordinator.settings_controller.capacity_settings_for_config(
            circuit_id
        )

    def standby_settings_for_config(
        self,
        config: CircuitConfig | None,
        circuit_id: str,
    ) -> StandbySettings:
        return self._coordinator.settings_controller.standby_settings_for_config(
            config,
            circuit_id,
        )

    def utility_comparison_settings_for_circuit(
        self,
        circuit_id: str,
    ) -> UtilityComparisonSettings:
        return (
            self._coordinator.settings_controller.utility_comparison_settings_for_circuit(
                circuit_id
            )
        )

    def clear_nilm_topology_state(self, circuit_id: str) -> None:
        self._coordinator.nilm_controller.clear_topology_state(circuit_id)

    def learning_mature(self, config: CircuitConfig, now: datetime) -> bool:
        profile = get_profile_definition(config.appliance_profile)
        raw_learning_started_at = (
            self._coordinator.store_data.learning_started_at_by_circuit.get(
                config.circuit_id
            )
        )
        learning_started_at = None
        if raw_learning_started_at:
            try:
                learning_started_at = datetime.fromisoformat(raw_learning_started_at)
            except ValueError:
                pass
            if learning_started_at is not None and learning_started_at.tzinfo is None:
                learning_started_at = learning_started_at.replace(tzinfo=now.tzinfo)
        circuit_events = [
            event
            for event in self._coordinator.store_data.events
            if event.circuit_id == config.circuit_id
            and (
                learning_started_at is None
                or event.timestamp >= learning_started_at
            )
        ]
        cycle_count = sum(
            1 for event in circuit_events if event.event_type is EventType.START
        )
        if profile.minimum_cycles > 0 and cycle_count >= profile.minimum_cycles:
            return True

        if not circuit_events:
            return False

        first_seen = min(event.timestamp for event in circuit_events)
        return now - first_seen >= timedelta(days=profile.minimum_learning_days)
