from __future__ import annotations

from typing import Any

from ..models import ApplianceProfile, PowerFlowMode


class ProcessingPipeline:
    """Run per-circuit feature processors in their established order."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def configure_processors(
        self,
        *,
        event_processor: Any,
        power_quality_processor: Any,
        energy_usage_processor: Any,
        energy_goal_processor: Any,
        run_cycle_processor: Any,
        activity_alert_processor: Any,
        billing_cycle_processor: Any,
        cost_processor: Any,
        demand_processor: Any,
        capacity_processor: Any,
        leg_imbalance_processor: Any,
        metric_consistency_processor: Any,
        standby_processor: Any,
        mains_balance_processor: Any,
        solar_flow_processor: Any,
        utility_comparison_processor: Any,
        clear_power_quality_state: Any,
        clear_standby_state: Any,
        sync_setup_health_repairs: Any,
    ) -> None:
        self._event_processor = event_processor
        self._power_quality_processor = power_quality_processor
        self._energy_usage_processor = energy_usage_processor
        self._energy_goal_processor = energy_goal_processor
        self._run_cycle_processor = run_cycle_processor
        self._activity_alert_processor = activity_alert_processor
        self._billing_cycle_processor = billing_cycle_processor
        self._cost_processor = cost_processor
        self._demand_processor = demand_processor
        self._capacity_processor = capacity_processor
        self._leg_imbalance_processor = leg_imbalance_processor
        self._metric_consistency_processor = metric_consistency_processor
        self._standby_processor = standby_processor
        self._mains_balance_processor = mains_balance_processor
        self._solar_flow_processor = solar_flow_processor
        self._utility_comparison_processor = utility_comparison_processor
        self._clear_power_quality_state = clear_power_quality_state
        self._clear_standby_state = clear_standby_state
        self._sync_setup_health_repairs = sync_setup_health_repairs

    async def async_process_circuit(
        self,
        config: Any,
        sample: Any,
        context: Any,
    ) -> tuple[list[Any], list[Any]]:
        coordinator = self._coordinator
        events: list[Any] = []
        alerts: list[Any] = []

        event_result = self._event_processor.process(sample, config, context)
        new_events, _ = await coordinator.async_apply_feature_result(event_result)
        events.extend(new_events)

        power_quality_result = self._power_quality_processor.process(
            sample,
            config,
            context,
        )
        if power_quality_result.clear_power_quality_state is not None:
            self._clear_power_quality_state(power_quality_result.clear_power_quality_state)
        _, power_quality_alerts = await coordinator.async_apply_feature_result(
            power_quality_result
        )
        alerts.extend(power_quality_alerts)

        usage_result = self._energy_usage_processor.process(
            sample,
            config,
            context,
        )
        _, usage_alerts = await coordinator.async_apply_feature_result(usage_result)
        alerts.extend(usage_alerts)

        goal_result = self._energy_goal_processor.process(
            sample,
            config,
            context,
        )
        _, goal_alerts = await coordinator.async_apply_feature_result(goal_result)
        alerts.extend(goal_alerts)

        cycle_result = self._run_cycle_processor.process(sample, config, context)
        _, cycle_alerts = await coordinator.async_apply_feature_result(cycle_result)
        alerts.extend(cycle_alerts)

        activity_result = self._activity_alert_processor.process(
            sample,
            config,
            context,
        )
        _, activity_alerts = await coordinator.async_apply_feature_result(
            activity_result
        )
        alerts.extend(activity_alerts)

        billing_result = self._billing_cycle_processor.process(
            sample,
            config,
            context,
        )
        _, billing_alerts = await coordinator.async_apply_feature_result(billing_result)
        alerts.extend(billing_alerts)

        cost_result = self._cost_processor.process(sample, config, context)
        await coordinator.async_apply_feature_result(cost_result)

        demand_result = self._demand_processor.process(sample, config, context)
        _, demand_alerts = await coordinator.async_apply_feature_result(demand_result)
        alerts.extend(demand_alerts)

        capacity_result = self._capacity_processor.process(
            sample,
            config,
            context,
        )
        _, capacity_alerts = await coordinator.async_apply_feature_result(
            capacity_result
        )
        alerts.extend(capacity_alerts)

        leg_imbalance_result = self._leg_imbalance_processor.process(
            sample,
            config,
            context,
        )
        _, leg_imbalance_alerts = await coordinator.async_apply_feature_result(
            leg_imbalance_result
        )
        alerts.extend(leg_imbalance_alerts)

        metric_consistency_result = self._metric_consistency_processor.process(
            sample,
            config,
            context,
        )
        await coordinator.async_apply_feature_result(metric_consistency_result)

        if (
            config.power_flow is PowerFlowMode.GENERATION
            or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
        ):
            self._clear_standby_state(config.circuit_id)
        else:
            standby_result = self._standby_processor.process(
                sample,
                config,
                context,
            )
            _, standby_alerts = await coordinator.async_apply_feature_result(
                standby_result
            )
            alerts.extend(standby_alerts)

        return events, alerts

    async def async_process_cross_circuit(
        self,
        samples: list[tuple[Any, Any]],
        now: Any,
    ) -> list[Any]:
        coordinator = self._coordinator

        balance_result = self._mains_balance_processor.process(
            samples,
            coordinator.context_builder.build(now),
        )
        coordinator.state_reducer.apply_updates(
            coordinator.state,
            balance_result.state_updates,
        )

        solar_result = self._solar_flow_processor.process(
            samples,
            coordinator.context_builder.build(now),
        )
        coordinator.state_reducer.apply_updates(
            coordinator.state,
            solar_result.state_updates,
        )

        alerts: list[Any] = []
        utility_context = coordinator.context_builder.build(now)
        for circuit_id in coordinator.store_data.utility_comparison_settings_by_circuit:
            config = coordinator.circuit_registry.config_for_circuit(circuit_id)
            if config is None:
                continue
            result = await self._utility_comparison_processor.process(
                config,
                utility_context,
            )
            _, new_alerts = await coordinator.async_apply_feature_result(result)
            await self._sync_setup_health_repairs(circuit_id)
            alerts.extend(new_alerts)
        return alerts
