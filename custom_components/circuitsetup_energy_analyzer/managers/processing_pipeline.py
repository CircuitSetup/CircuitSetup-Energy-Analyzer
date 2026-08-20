from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from typing import Any

from ..models import ApplianceProfile, PowerFlowMode, SensorRole
from ..usage import derive_cumulative_energy_from_power


class ProcessingPipeline:
    """Run per-circuit feature processors in their established order."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def configure_processors(
        self,
        *,
        event_processor: Any,
        mains_power_quality_processor: Any,
        power_quality_processor: Any,
        energy_usage_processor: Any,
        energy_goal_processor: Any,
        run_cycle_processor: Any,
        appliance_health_processor: Any,
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
        hvac_efficiency_processor: Any | None = None,
    ) -> None:
        self._event_processor = event_processor
        self._mains_power_quality_processor = mains_power_quality_processor
        self._power_quality_processor = power_quality_processor
        self._energy_usage_processor = energy_usage_processor
        self._energy_goal_processor = energy_goal_processor
        self._run_cycle_processor = run_cycle_processor
        self._appliance_health_processor = appliance_health_processor
        self._activity_alert_processor = activity_alert_processor
        self._billing_cycle_processor = billing_cycle_processor
        self._cost_processor = cost_processor
        self._demand_processor = demand_processor
        self._capacity_processor = capacity_processor
        self._leg_imbalance_processor = leg_imbalance_processor
        self._metric_consistency_processor = metric_consistency_processor
        self._standby_processor = standby_processor
        self._hvac_efficiency_processor = hvac_efficiency_processor
        self._mains_balance_processor = mains_balance_processor
        self._solar_flow_processor = solar_flow_processor
        self._utility_comparison_processor = utility_comparison_processor
        self._clear_power_quality_state = clear_power_quality_state
        self._clear_standby_state = clear_standby_state
        self._sync_setup_health_repairs = sync_setup_health_repairs

    async def _async_apply_feature_result(
        self,
        result: Any,
    ) -> tuple[list[Any], list[Any]]:
        applied = await self._coordinator.async_apply_feature_result(result)
        await asyncio.sleep(0)
        return applied

    async def _async_process(self, name: str, processor: Any, *args: Any) -> Any:
        started_at = monotonic()
        try:
            add_executor_job = getattr(
                getattr(self._coordinator, "hass", None),
                "async_add_executor_job",
                None,
            )
            if add_executor_job is not None:
                return await add_executor_job(processor.process, *args)
            return await asyncio.to_thread(processor.process, *args)
        finally:
            record_performance = getattr(
                self._coordinator, "_record_runtime_performance", None
            )
            if record_performance is not None:
                record_performance(f"processor:{name}", monotonic() - started_at)

    async def async_process_circuit(
        self,
        config: Any,
        sample: Any,
        context: Any,
    ) -> tuple[list[Any], list[Any]]:
        events: list[Any] = []
        alerts: list[Any] = []
        energy_history = context.store_data.energy_usage_by_circuit.setdefault(
            config.circuit_id,
            {},
        )
        if not _has_usable_energy_sensor(config):
            sample = replace(
                sample,
                energy=derive_cumulative_energy_from_power(
                    energy_history,
                    timestamp=sample.timestamp,
                    power_w=sample.real_power,
                ),
            )
            energy_history["energy_source"] = "derived_from_power"

        event_result = await self._async_process(
            "events", self._event_processor, sample, config, context
        )
        new_events, _ = await self._async_apply_feature_result(event_result)
        events.extend(new_events)

        mains_quality_result = await self._async_process(
            "mains_power_quality",
            self._mains_power_quality_processor,
            sample,
            config,
            context,
        )
        mains_quality_events, mains_quality_alerts = (
            await self._async_apply_feature_result(mains_quality_result)
        )
        events.extend(mains_quality_events)
        alerts.extend(mains_quality_alerts)

        power_quality_result = await self._async_process(
            "power_quality", self._power_quality_processor, sample, config, context
        )
        if power_quality_result.clear_power_quality_state is not None:
            self._clear_power_quality_state(power_quality_result.clear_power_quality_state)
        _, power_quality_alerts = await self._async_apply_feature_result(
            power_quality_result
        )
        alerts.extend(power_quality_alerts)

        usage_result = await self._async_process(
            "energy_usage", self._energy_usage_processor, sample, config, context
        )
        _, usage_alerts = await self._async_apply_feature_result(usage_result)
        alerts.extend(usage_alerts)

        goal_result = await self._async_process(
            "energy_goal", self._energy_goal_processor, sample, config, context
        )
        _, goal_alerts = await self._async_apply_feature_result(goal_result)
        alerts.extend(goal_alerts)

        cycle_result = await self._async_process(
            "run_cycle", self._run_cycle_processor, sample, config, context
        )
        _, cycle_alerts = await self._async_apply_feature_result(cycle_result)
        alerts.extend(cycle_alerts)

        health_result = await self._async_process(
            "appliance_health",
            self._appliance_health_processor,
            sample,
            config,
            context,
        )
        _, health_alerts = await self._async_apply_feature_result(health_result)
        alerts.extend(health_alerts)

        activity_result = await self._async_process(
            "activity_alert",
            self._activity_alert_processor,
            sample,
            config,
            context,
        )
        _, activity_alerts = await self._async_apply_feature_result(
            activity_result
        )
        alerts.extend(activity_alerts)

        billing_result = await self._async_process(
            "billing_cycle",
            self._billing_cycle_processor,
            sample,
            config,
            context,
        )
        _, billing_alerts = await self._async_apply_feature_result(billing_result)
        alerts.extend(billing_alerts)

        cost_result = await self._async_process(
            "cost", self._cost_processor, sample, config, context
        )
        await self._async_apply_feature_result(cost_result)

        demand_result = await self._async_process(
            "demand", self._demand_processor, sample, config, context
        )
        _, demand_alerts = await self._async_apply_feature_result(demand_result)
        alerts.extend(demand_alerts)

        capacity_result = await self._async_process(
            "capacity", self._capacity_processor, sample, config, context
        )
        _, capacity_alerts = await self._async_apply_feature_result(
            capacity_result
        )
        alerts.extend(capacity_alerts)

        leg_imbalance_result = await self._async_process(
            "leg_imbalance",
            self._leg_imbalance_processor,
            sample,
            config,
            context,
        )
        _, leg_imbalance_alerts = await self._async_apply_feature_result(
            leg_imbalance_result
        )
        alerts.extend(leg_imbalance_alerts)

        metric_consistency_result = await self._async_process(
            "metric_consistency",
            self._metric_consistency_processor,
            sample,
            config,
            context,
        )
        await self._async_apply_feature_result(metric_consistency_result)

        if (
            config.power_flow is PowerFlowMode.GENERATION
            or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
        ):
            self._clear_standby_state(config.circuit_id)
        else:
            standby_result = await self._async_process(
                "standby", self._standby_processor, sample, config, context
            )
            _, standby_alerts = await self._async_apply_feature_result(
                standby_result
            )
            alerts.extend(standby_alerts)

        return events, alerts

    async def async_process_cross_circuit(
        self,
        samples: list[tuple[Any, Any]],
        context: Any,
    ) -> list[Any]:
        coordinator = self._coordinator
        alerts: list[Any] = []

        if self._hvac_efficiency_processor is not None:
            hvac_result = await self._async_process(
                "hvac_efficiency", self._hvac_efficiency_processor, samples, context
            )
            _, hvac_alerts = await self._async_apply_feature_result(hvac_result)
            alerts.extend(hvac_alerts)

        balance_result = await self._async_process(
            "mains_balance", self._mains_balance_processor, samples, context
        )
        _, balance_alerts = await self._async_apply_feature_result(balance_result)
        alerts.extend(balance_alerts)

        solar_result = await self._async_process(
            "solar_flow", self._solar_flow_processor, samples, context
        )
        _, solar_alerts = await self._async_apply_feature_result(solar_result)
        alerts.extend(solar_alerts)

        for circuit_id in coordinator.store_data.utility_comparison_settings_by_circuit:
            config = coordinator.circuit_registry.config_for_circuit(circuit_id)
            if config is None:
                continue
            result = await self._utility_comparison_processor.process(
                config,
                context,
            )
            _, new_alerts = await self._async_apply_feature_result(result)
            if any(
                update.path[0] == "utility_cost_rate_by_circuit"
                for update in result.state_updates
            ):
                coordinator.refresh_cost_estimates()
            await self._sync_setup_health_repairs(circuit_id)
            alerts.extend(new_alerts)
        return alerts


def _has_usable_energy_sensor(config: Any) -> bool:
    for sensor in config.sensors:
        if sensor.role is not SensorRole.ENERGY:
            continue
        unit = str(sensor.unit or "").strip().lower()
        if not unit or unit in {"kwh", "wh", "mwh"}:
            return True
    return False
