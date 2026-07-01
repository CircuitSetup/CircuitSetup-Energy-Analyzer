from __future__ import annotations

from typing import Any

from ..models import ApplianceProfile, PowerFlowMode


class ProcessingPipeline:
    """Run per-circuit feature processors in their established order."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_process_circuit(
        self,
        config: Any,
        sample: Any,
        context: Any,
    ) -> tuple[list[Any], list[Any]]:
        coordinator = self._coordinator
        events: list[Any] = []
        alerts: list[Any] = []

        event_result = coordinator._event_processor.process(sample, config, context)
        new_events, _ = await coordinator._apply_feature_result(event_result)
        events.extend(new_events)

        power_quality_result = coordinator._power_quality_processor.process(
            sample,
            config,
            context,
        )
        if power_quality_result.clear_power_quality_state is not None:
            coordinator._clear_power_quality_state(
                power_quality_result.clear_power_quality_state
            )
        _, power_quality_alerts = await coordinator._apply_feature_result(
            power_quality_result
        )
        alerts.extend(power_quality_alerts)

        usage_result = coordinator._energy_usage_processor.process(
            sample,
            config,
            context,
        )
        _, usage_alerts = await coordinator._apply_feature_result(usage_result)
        alerts.extend(usage_alerts)

        goal_result = coordinator._energy_goal_processor.process(
            sample,
            config,
            context,
        )
        _, goal_alerts = await coordinator._apply_feature_result(goal_result)
        alerts.extend(goal_alerts)

        cycle_result = coordinator._run_cycle_processor.process(sample, config, context)
        _, cycle_alerts = await coordinator._apply_feature_result(cycle_result)
        alerts.extend(cycle_alerts)

        activity_result = coordinator._activity_alert_processor.process(
            sample,
            config,
            context,
        )
        _, activity_alerts = await coordinator._apply_feature_result(activity_result)
        alerts.extend(activity_alerts)

        billing_result = coordinator._billing_cycle_processor.process(
            sample,
            config,
            context,
        )
        _, billing_alerts = await coordinator._apply_feature_result(billing_result)
        alerts.extend(billing_alerts)

        cost_result = coordinator._cost_processor.process(sample, config, context)
        await coordinator._apply_feature_result(cost_result)

        demand_result = coordinator._demand_processor.process(sample, config, context)
        _, demand_alerts = await coordinator._apply_feature_result(demand_result)
        alerts.extend(demand_alerts)

        capacity_result = coordinator._capacity_processor.process(
            sample,
            config,
            context,
        )
        _, capacity_alerts = await coordinator._apply_feature_result(capacity_result)
        alerts.extend(capacity_alerts)

        leg_imbalance_result = coordinator._leg_imbalance_processor.process(
            sample,
            config,
            context,
        )
        _, leg_imbalance_alerts = await coordinator._apply_feature_result(
            leg_imbalance_result
        )
        alerts.extend(leg_imbalance_alerts)

        metric_consistency_result = coordinator._metric_consistency_processor.process(
            sample,
            config,
            context,
        )
        await coordinator._apply_feature_result(metric_consistency_result)

        if (
            config.power_flow is PowerFlowMode.GENERATION
            or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
        ):
            coordinator._clear_standby_state(config.circuit_id)
        else:
            standby_result = coordinator._standby_processor.process(
                sample,
                config,
                context,
            )
            _, standby_alerts = await coordinator._apply_feature_result(standby_result)
            alerts.extend(standby_alerts)

        return events, alerts

    async def async_process_cross_circuit(
        self,
        samples: list[tuple[Any, Any]],
        now: Any,
    ) -> list[Any]:
        coordinator = self._coordinator

        balance_result = coordinator._mains_balance_processor.process(
            samples,
            coordinator._build_processing_context(now),
        )
        for update in balance_result.state_updates:
            coordinator.state_reducer.apply_update(
                coordinator.state,
                update.path,
                update.value,
            )

        solar_result = coordinator._solar_flow_processor.process(
            samples,
            coordinator._build_processing_context(now),
        )
        for update in solar_result.state_updates:
            coordinator.state_reducer.apply_update(
                coordinator.state,
                update.path,
                update.value,
            )

        alerts: list[Any] = []
        utility_context = coordinator._build_processing_context(now)
        for circuit_id in coordinator.store_data.utility_comparison_settings_by_circuit:
            config = coordinator._config_for_circuit(circuit_id)
            if config is None:
                continue
            result = await coordinator._utility_comparison_processor.process(
                config,
                utility_context,
            )
            _, new_alerts = await coordinator._apply_feature_result(result)
            await coordinator._sync_setup_health_repairs(circuit_id)
            alerts.extend(new_alerts)
        return alerts
