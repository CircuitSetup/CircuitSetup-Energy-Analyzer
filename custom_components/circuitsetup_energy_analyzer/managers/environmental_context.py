from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from ..const import (
    CONF_EXPECTS_WATER_FLOW,
    CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    CONF_RAIN_INTENSITY_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_RAIN_RESPONSE_WINDOW_MINUTES,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
    DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
    DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
    DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
    DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
)
from ..context_sources import (
    flow_entities_for_settings,
    has_rain_context_source_configured,
    strings_from_any,
)
from ..contextual_baseline import rain_context, weather_mode_for_temperature
from ..local_time import local_date
from ..models import AlertEvidence, ApplianceProfile, CircuitConfig
from ..water_correlations import (
    FlowCorrelationInput,
    RainPumpCorrelationInput,
    evaluate_flow_correlation,
    evaluate_rain_pump_correlation,
)
from ..weather_context import WeatherContextSample, evaluate_weather_context

WEATHER_CONTEXT_HISTORY_MAX_SAMPLES = 1008
WATER_CONTEXT_HISTORY_MAX_SAMPLES = 1008
HVAC_WEATHER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)
MODE_PARTITIONED_HVAC_PROFILES = frozenset(
    {ApplianceProfile.HEAT_PUMP, ApplianceProfile.MINI_SPLIT}
)
PUMP_WATER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
    }
)
FLOW_WATER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.WASHER,
        ApplianceProfile.DISHWASHER,
    }
)


class EnvironmentalContextManager:
    """Refresh runtime weather, rain, and water-flow context state."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def refresh_weather_context_state(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        coordinator = self._coordinator
        circuit_id = config.circuit_id
        if config.appliance_profile not in HVAC_WEATHER_CONTEXT_PROFILES:
            if coordinator.state_reducer.clear_weather_context_state(
                coordinator.state,
                coordinator.store_data,
                circuit_id,
            ):
                self._mark_store_dirty()
            return

        outdoor_entity = coordinator.context_builder.outdoor_temperature_entity()
        if not outdoor_entity:
            if coordinator.state_reducer.clear_weather_context_state(
                coordinator.state,
                coordinator.store_data,
                circuit_id,
            ):
                self._mark_store_dirty()
            return

        outdoor_temperature_reading = (
            coordinator.context_builder.temperature_reading_for_entity(outdoor_entity)
        )
        outdoor_temperature = (
            outdoor_temperature_reading["temperature_f"]
            if outdoor_temperature_reading is not None
            else None
        )
        runtime_minutes = (
            coordinator.state.run_cycle_runtime_seconds_by_circuit.get(circuit_id, 0.0)
            / 60.0
        )
        duty_cycle_percent = coordinator.state.run_cycle_duty_cycle_by_circuit.get(
            circuit_id,
            0.0,
        )
        coordinator.demo_data.seed_weather_context_history(
            config,
            now,
            outdoor_temperature=outdoor_temperature,
        )
        weather_mode = _weather_context_mode(config, outdoor_temperature)
        history = self.weather_context_history_samples(
            circuit_id,
            now,
            mode=(
                weather_mode
                if config.appliance_profile in MODE_PARTITIONED_HVAC_PROFILES
                else None
            ),
        )
        weather_runtime_minutes = runtime_minutes
        weather_duty_cycle_percent = duty_cycle_percent
        if config.appliance_profile in MODE_PARTITIONED_HVAC_PROFILES:
            (
                weather_runtime_minutes,
                weather_duty_cycle_percent,
                _,
            ) = _weather_context_mode_metrics(
                coordinator.store_data.weather_context_history_by_circuit.get(
                    circuit_id,
                    [],
                ),
                now,
                coordinator.context_builder.time_zone(),
                mode=weather_mode,
                runtime_minutes=runtime_minutes,
                duty_cycle_percent=duty_cycle_percent,
            )
        evidence = evaluate_weather_context(
            outdoor_temperature=outdoor_temperature,
            current_runtime_minutes=weather_runtime_minutes,
            current_duty_cycle_percent=weather_duty_cycle_percent,
            history=history,
            mode=weather_mode,
            display_temperature=(
                outdoor_temperature_reading["display_temperature"]
                if outdoor_temperature_reading is not None
                else None
            ),
            display_temperature_unit=(
                outdoor_temperature_reading["display_unit"]
                if outdoor_temperature_reading is not None
                else "°F"
            ),
            observed_at=now,
            time_zone=coordinator.context_builder.time_zone(),
        )
        if outdoor_temperature_reading is not None:
            evidence["temperature_source_entity"] = outdoor_entity
            evidence["temperature_source_unit"] = outdoor_temperature_reading[
                "source_unit"
            ]
        if coordinator.store_data.weather_context_by_circuit.get(circuit_id) != (
            evidence
        ):
            coordinator.store_data.weather_context_by_circuit[circuit_id] = evidence
            self._mark_store_dirty()
        coordinator.state.weather_context_by_circuit[circuit_id] = dict(evidence)
        if outdoor_temperature is not None:
            changed = self.append_weather_context_history(
                circuit_id,
                now,
                temperature=outdoor_temperature,
                runtime_minutes=runtime_minutes,
                duty_cycle_percent=duty_cycle_percent,
                mode=(
                    weather_mode
                    if config.appliance_profile in MODE_PARTITIONED_HVAC_PROFILES
                    else None
                ),
            )
            if changed:
                self._mark_store_dirty()

    def refresh_water_context_state(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        coordinator = self._coordinator
        circuit_id = config.circuit_id
        settings_controller = coordinator.settings_controller
        advanced_settings = settings_controller.advanced_settings_for_circuit(
            circuit_id
        )
        profile = config.appliance_profile
        changed = False

        if profile in PUMP_WATER_CONTEXT_PROFILES and bool(
            advanced_settings.get(
                CONF_RAIN_PUMP_CORRELATION_ENABLED,
                DEFAULT_RAIN_PUMP_CORRELATION_ENABLED,
            )
        ) and has_rain_context_source_configured(
            coordinator.entry_data,
            coordinator.options,
        ):
            rain_evidence = self.rain_pump_context_evidence(
                config,
                advanced_settings,
                now,
            )
            if coordinator.store_data.rain_pump_context_by_circuit.get(
                circuit_id
            ) != rain_evidence:
                coordinator.store_data.rain_pump_context_by_circuit[circuit_id] = (
                    rain_evidence
                )
                changed = True
            coordinator.state.rain_pump_context_by_circuit[circuit_id] = dict(
                rain_evidence
            )
        else:
            changed = (
                coordinator.state_reducer.clear_rain_pump_context_state(
                    coordinator.state,
                    coordinator.store_data,
                    circuit_id,
                )
                or changed
            )

        if profile in FLOW_WATER_CONTEXT_PROFILES and bool(
            advanced_settings.get(
                CONF_WATER_FLOW_CORRELATION_ENABLED,
                DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
            )
        ) and flow_entities_for_settings(
            coordinator.entry_data,
            coordinator.options,
            advanced_settings,
        ):
            flow_evidence = self.water_flow_context_evidence(
                config,
                advanced_settings,
                now,
            )
            if coordinator.store_data.water_flow_context_by_circuit.get(
                circuit_id
            ) != flow_evidence:
                coordinator.store_data.water_flow_context_by_circuit[circuit_id] = (
                    flow_evidence
                )
                changed = True
            coordinator.state.water_flow_context_by_circuit[circuit_id] = dict(
                flow_evidence
            )
        else:
            changed = (
                coordinator.state_reducer.clear_water_flow_context_state(
                    coordinator.state,
                    coordinator.store_data,
                    circuit_id,
                )
                or changed
            )

        if profile in PUMP_WATER_CONTEXT_PROFILES | FLOW_WATER_CONTEXT_PROFILES:
            if self.append_water_context_history(circuit_id, now):
                changed = True
        else:
            changed = (
                coordinator.state_reducer.clear_water_context_history(
                    coordinator.state,
                    coordinator.store_data,
                    circuit_id,
                )
                or changed
            )

        if changed:
            self._mark_store_dirty()

    def observe_water_context(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> AlertEvidence | None:
        coordinator = self._coordinator
        result = coordinator._water_context_alert_processor.process(
            config,
            coordinator.context_builder.build(now),
        )
        return result.alerts[0] if result.alerts else None

    def rain_pump_context_evidence(
        self,
        config: CircuitConfig,
        advanced_settings: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        coordinator = self._coordinator
        rain_entity = coordinator.context_builder.configured_context_entity(
            CONF_RAIN_SENSOR_ENTITY
        )
        rain_intensity_entity = coordinator.context_builder.configured_context_entity(
            CONF_RAIN_INTENSITY_ENTITY
        )
        rain_active = coordinator.context_builder.binary_entity_active(rain_entity)
        rain_reading = coordinator.context_builder.precipitation_reading_for_entity(
            rain_intensity_entity or rain_entity
        )
        rain_intensity = (
            float(rain_reading["value"]) if rain_reading is not None else None
        )
        rain_intensity_unit = (
            str(rain_reading["unit"]) if rain_reading and rain_reading["unit"] else None
        )
        rain_intensity_source = (
            rain_intensity_entity or rain_entity if rain_reading is not None else ""
        )
        outdoor_entity = coordinator.context_builder.outdoor_temperature_entity()
        outdoor_temperature_reading = (
            coordinator.context_builder.temperature_reading_for_entity(outdoor_entity)
            if outdoor_entity
            else None
        )
        outdoor_temperature = (
            float(outdoor_temperature_reading["temperature_f"])
            if outdoor_temperature_reading is not None
            else None
        )
        outdoor_humidity = coordinator.context_builder.humidity_percent_for_entity(
            outdoor_entity
        )
        response_window_minutes = max(
            int(
                advanced_settings.get(
                    CONF_RAIN_RESPONSE_WINDOW_MINUTES,
                    DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES,
                )
            ),
            0,
        )
        (
            effective_rain_active,
            rain_response_active,
            rain_last_active_at,
            rain_response_expires_at,
        ) = self._rain_response_context(
            config.circuit_id,
            now,
            rain_entity,
            rain_intensity_source,
            rain_active,
            rain_intensity,
            rain_intensity_unit,
            response_window_minutes,
        )
        compressor_context = self.hvac_compressor_context()
        runtime_minutes = self.runtime_minutes_for_circuit(config.circuit_id)
        baseline = self.dry_weather_pump_baseline(config.circuit_id, now)
        evidence = evaluate_rain_pump_correlation(
            RainPumpCorrelationInput(
                circuit_id=config.circuit_id,
                appliance_profile=config.appliance_profile.value,
                pump_runtime_minutes=runtime_minutes,
                dry_baseline_minutes=baseline["dry_baseline_minutes"],
                comparable_window_count=baseline["comparable_window_count"],
                rain_active=effective_rain_active,
                rain_intensity_per_hour=rain_intensity,
                rain_intensity_unit=rain_intensity_unit,
                compressor_runtime_minutes=compressor_context["runtime_minutes"],
                compressor_duty_cycle_percent=compressor_context[
                    "duty_cycle_percent"
                ],
                outdoor_temperature_f=outdoor_temperature,
                outdoor_humidity_percent=outdoor_humidity,
                sensitivity_delta_threshold_pct=float(
                    advanced_settings.get(
                        CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                        DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT,
                    )
                ),
            )
        )
        evidence["rain_sensor_entity"] = rain_entity
        evidence["rain_sensor_active"] = rain_active
        evidence["rain_intensity_entity"] = rain_intensity_source
        evidence["rain_intensity_per_hour"] = rain_intensity
        evidence["rain_intensity_unit"] = rain_intensity_unit
        evidence["outdoor_temperature_source_entity"] = (
            outdoor_entity if outdoor_temperature is not None else ""
        )
        evidence["outdoor_humidity_source_entity"] = (
            outdoor_entity if outdoor_humidity is not None else ""
        )
        evidence["rain_response_window_minutes"] = response_window_minutes
        evidence["rain_response_active"] = rain_response_active
        evidence["rain_last_active_at"] = _isoformat_or_none(
            rain_last_active_at
        )
        evidence["rain_response_expires_at"] = _isoformat_or_none(
            rain_response_expires_at
        )
        evidence["hvac_compressor_runtime_minutes"] = compressor_context[
            "runtime_minutes"
        ]
        evidence["hvac_compressor_duty_cycle_percent"] = compressor_context[
            "duty_cycle_percent"
        ]
        evidence["hvac_compressor_circuits"] = compressor_context["circuit_ids"]
        return evidence

    def _rain_response_context(
        self,
        circuit_id: str,
        now: datetime,
        rain_entity: str,
        rain_intensity_entity: str,
        rain_active: bool | None,
        rain_intensity: float | None,
        rain_intensity_unit: str | None,
        response_window_minutes: int,
    ) -> tuple[bool | None, bool, datetime | None, datetime | None]:
        rain_info = rain_context(
            rain_active,
            rain_intensity,
            unit=rain_intensity_unit,
        )
        current_rain = rain_info.state in {"raining", "heavy_rain"}
        confirmed_dry = rain_info.state == "dry"
        previous = self._coordinator.state.rain_pump_context_by_circuit.get(
            circuit_id,
            {},
        )
        previous_waiting_for_dry = (
            str(previous.get("rain_state") or "")
            in {"raining", "heavy_rain", "ambiguous"}
            and not bool(previous.get("rain_response_active"))
        )
        rain_stopped_at = self._latest_context_state_change(
            rain_entity,
            rain_intensity_entity,
        )
        last_active_at = (
            now
            if current_rain
            else rain_stopped_at
            if (
                previous_waiting_for_dry
                and confirmed_dry
                and rain_stopped_at is not None
            )
            else _datetime_or_none(previous.get("rain_last_active_at"))
        )
        expires_at = (
            last_active_at + timedelta(minutes=response_window_minutes)
            if last_active_at is not None
            else None
        )
        rain_response_active = bool(
            not current_rain
            and confirmed_dry
            and expires_at is not None
            and now <= expires_at
        )
        return (
            True if current_rain or rain_response_active else rain_active,
            rain_response_active,
            last_active_at,
            expires_at,
        )

    def _latest_context_state_change(
        self,
        *entity_ids: str,
    ) -> datetime | None:
        changes = [
            _datetime_or_none(getattr(raw_state, "last_changed", None))
            for entity_id in entity_ids
            if entity_id
            and (
                raw_state := self._coordinator.context_builder.raw_state_for_entity(
                    entity_id
                )
            )
            is not None
        ]
        return max(
            (changed for changed in changes if changed is not None),
            default=None,
        )

    def water_flow_context_evidence(
        self,
        config: CircuitConfig,
        advanced_settings: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        coordinator = self._coordinator
        flow_entities = flow_entities_for_settings(
            coordinator.entry_data,
            coordinator.options,
            advanced_settings,
        )
        threshold_minutes = int(
            advanced_settings.get(
                CONF_FLOW_MISMATCH_THRESHOLD_MINUTES,
                DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES,
            )
        )
        flow_active_minutes = coordinator.context_builder.max_flow_active_minutes(
            flow_entities,
            now,
        )
        appliance_runtime_minutes = self.active_runtime_minutes_for_circuit(
            config.circuit_id
        )
        mapped_appliance_count, mapped_appliance_runtime_minutes = (
            self.mapped_water_appliance_context(
                config,
                advanced_settings,
                flow_entities,
            )
        )
        recent_related_runtime_minutes = (
            coordinator.context_builder.recent_flow_context_minutes(
                flow_entities,
                now,
                threshold_minutes,
            )
            if appliance_runtime_minutes > 0
            else 0.0
        )
        history_count = sum(
            1
            for sample in coordinator.store_data.water_context_history_by_circuit.get(
                config.circuit_id,
                [],
            )
            if isinstance(sample, Mapping)
            and isinstance(sample.get("flow_status"), str)
            and sample["flow_status"] != "unconfigured"
        )
        evidence = evaluate_flow_correlation(
            FlowCorrelationInput(
                circuit_id=config.circuit_id,
                appliance_profile=config.appliance_profile.value,
                flow_active_minutes=flow_active_minutes,
                appliance_runtime_minutes=appliance_runtime_minutes,
                recent_related_runtime_minutes=recent_related_runtime_minutes,
                mapped_appliance_count=mapped_appliance_count,
                mapped_appliance_runtime_minutes=mapped_appliance_runtime_minutes,
                threshold_minutes=threshold_minutes,
                expects_water_flow=bool(
                    advanced_settings.get(CONF_EXPECTS_WATER_FLOW, True)
                ),
                comparable_window_count=history_count,
                flow_source_configured=bool(flow_entities),
            )
        )
        evidence["flow_sensor_entities"] = list(flow_entities)
        flow_states = tuple(
            coordinator.context_builder.flow_entity_active(entity_id)
            for entity_id in flow_entities
        )
        flow_sensor_active = (
            True
            if True in flow_states
            else False
            if flow_states and None not in flow_states
            else None
        )
        evidence["flow_sensor_active"] = flow_sensor_active
        if flow_entities and flow_sensor_active is None:
            evidence["status"] = "sensor_unavailable"
            evidence["friendly_summary"] = (
                "Configured water-flow sensors are currently unavailable."
            )
        evidence["flow_mismatch_threshold_minutes"] = threshold_minutes
        return evidence

    def runtime_minutes_for_circuit(self, circuit_id: str) -> float:
        return round(
            self._coordinator.state.run_cycle_runtime_seconds_by_circuit.get(
                circuit_id,
                0.0,
            )
            / 60.0,
            3,
        )

    def active_runtime_minutes_for_circuit(self, circuit_id: str) -> float:
        evidence = self._coordinator.state.run_cycle_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        if not isinstance(evidence, Mapping) or evidence.get("status") != "running":
            return 0.0
        return round(
            float(evidence.get("active_cycle_seconds", 0.0)) / 60.0,
            3,
        )

    def hvac_compressor_context(self) -> dict[str, Any]:
        coordinator = self._coordinator
        circuit_ids: list[str] = []
        runtime_minutes = 0.0
        duty_cycle_percent = 0.0
        for config in coordinator.circuit_configs:
            if config.appliance_profile not in {
                ApplianceProfile.HVAC,
                ApplianceProfile.HVAC_COMPRESSOR,
                ApplianceProfile.HEAT_PUMP,
                ApplianceProfile.MINI_SPLIT,
            }:
                continue
            circuit_ids.append(config.circuit_id)
            runtime_minutes += self.runtime_minutes_for_circuit(config.circuit_id)
            duty_cycle_percent = max(
                duty_cycle_percent,
                coordinator.state.run_cycle_duty_cycle_by_circuit.get(
                    config.circuit_id,
                    0.0,
                ),
            )
        return {
            "circuit_ids": circuit_ids,
            "runtime_minutes": round(runtime_minutes, 3),
            "duty_cycle_percent": round(duty_cycle_percent, 3),
        }

    def dry_weather_pump_baseline(
        self,
        circuit_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        dry_samples: list[float] = []
        time_zone = self._coordinator.context_builder.time_zone()
        for sample in self._coordinator.store_data.water_context_history_by_circuit.get(
            circuit_id,
            [],
        ):
            if not isinstance(sample, Mapping):
                continue
            sample_time = _datetime_or_none(sample.get("timestamp"))
            if sample_time is not None and _ha_local_date(
                sample_time,
                time_zone,
            ) >= _ha_local_date(now, time_zone):
                continue
            if not _water_context_history_sample_is_dry(sample):
                continue
            if _float_or_none(sample.get("compressor_runtime_minutes")) not in (
                None,
                0.0,
            ):
                continue
            runtime = _float_or_none(sample.get("pump_runtime_minutes"))
            if runtime is not None:
                dry_samples.append(runtime)
        return {
            "dry_baseline_minutes": (
                round(float(median(dry_samples)), 3) if dry_samples else None
            ),
            "comparable_window_count": len(dry_samples),
        }

    def mapped_water_appliance_context(
        self,
        current_config: CircuitConfig,
        current_settings: Mapping[str, Any],
        flow_entities: Iterable[str],
    ) -> tuple[int, float]:
        source_entities = set(flow_entities)
        if not source_entities:
            return 0, 0.0
        if strings_from_any(
            current_settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES)
        ):
            return 1, self.active_runtime_minutes_for_circuit(
                current_config.circuit_id
            )
        count = 0
        runtime_minutes = 0.0
        for config in self._coordinator.circuit_configs:
            if config.appliance_profile not in FLOW_WATER_CONTEXT_PROFILES:
                continue
            settings_controller = self._coordinator.settings_controller
            settings = settings_controller.advanced_settings_for_circuit(
                config.circuit_id
            )
            flow_correlation_enabled = bool(
                settings.get(
                    CONF_WATER_FLOW_CORRELATION_ENABLED,
                    DEFAULT_WATER_FLOW_CORRELATION_ENABLED,
                )
            )
            expects_water_flow = bool(
                settings.get(CONF_EXPECTS_WATER_FLOW, True)
            )
            if not flow_correlation_enabled or not expects_water_flow:
                continue
            if strings_from_any(settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES)):
                continue
            configured_entities = flow_entities_for_settings(
                self._coordinator.entry_data,
                self._coordinator.options,
                settings,
            )
            if not source_entities.intersection(configured_entities):
                continue
            count += 1
            runtime_minutes += self.active_runtime_minutes_for_circuit(
                config.circuit_id
            )
        return count, round(runtime_minutes, 3)

    def append_water_context_history(
        self,
        circuit_id: str,
        now: datetime,
    ) -> bool:
        coordinator = self._coordinator
        rain_evidence = coordinator.state.rain_pump_context_by_circuit.get(
            circuit_id,
            {},
        )
        flow_evidence = coordinator.state.water_flow_context_by_circuit.get(
            circuit_id,
            {},
        )
        if not rain_evidence and not flow_evidence:
            return False
        sample = {
            "timestamp": now.isoformat(),
            "rain_status": rain_evidence.get("status"),
            "flow_status": flow_evidence.get("status"),
            "pump_runtime_minutes": rain_evidence.get("pump_runtime_minutes"),
            "flow_active_minutes": flow_evidence.get("flow_active_minutes"),
            "mismatch_minutes": flow_evidence.get("mismatch_minutes"),
            "rain_active": rain_evidence.get("rain_sensor_active"),
            "compressor_runtime_minutes": rain_evidence.get(
                "hvac_compressor_runtime_minutes"
            ),
        }
        for key in (
            "rain_state",
            "rain_intensity_mm_per_hour",
            "rain_intensity_bin",
            "rain_context_issues",
            "outdoor_temperature_f",
            "temperature_bin",
            "outdoor_humidity_bin",
            "outdoor_humidity_percent",
        ):
            if key in rain_evidence:
                sample[key] = rain_evidence[key]
        history = coordinator.store_data.water_context_history_by_circuit.setdefault(
            circuit_id,
            [],
        )
        time_zone = coordinator.context_builder.time_zone()
        for index in range(len(history) - 1, -1, -1):
            existing_time = _datetime_or_none(history[index].get("timestamp"))
            if existing_time is not None and _ha_local_date(
                existing_time,
                time_zone,
            ) == _ha_local_date(now, time_zone):
                if history[index] == sample:
                    return False
                history[index] = sample
                coordinator.state.water_context_history_by_circuit[circuit_id] = [
                    dict(item) for item in history
                ]
                return True

        history.append(sample)
        del history[:-WATER_CONTEXT_HISTORY_MAX_SAMPLES]
        coordinator.state.water_context_history_by_circuit[circuit_id] = [
            dict(item) for item in history
        ]
        return True

    def weather_context_history_samples(
        self,
        circuit_id: str,
        now: datetime,
        *,
        mode: str | None = None,
    ) -> list[WeatherContextSample]:
        samples: list[WeatherContextSample] = []
        raw_samples = (
            self._coordinator.store_data.weather_context_history_by_circuit.get(
                circuit_id,
                [],
            )
        )
        time_zone = self._coordinator.context_builder.time_zone()
        for raw_sample in raw_samples:
            if not isinstance(raw_sample, Mapping):
                continue
            sample_time = _datetime_or_none(raw_sample.get("timestamp"))
            if sample_time is None or _ha_local_date(
                sample_time,
                time_zone,
            ) >= _ha_local_date(now, time_zone):
                continue
            temperature = _float_or_none(raw_sample.get("temperature"))
            runtime = _float_or_none(raw_sample.get("runtime_minutes"))
            duty = _float_or_none(raw_sample.get("duty_cycle_percent"))
            if temperature is None or runtime is None or duty is None:
                continue
            if mode is not None and _weather_context_sample_mode(raw_sample) != mode:
                continue
            samples.append(
                WeatherContextSample(
                    temperature=temperature,
                    runtime_minutes=runtime,
                    duty_cycle_percent=duty,
                    timestamp=sample_time,
                    energy_kwh=_float_or_none(raw_sample.get("energy_kwh")),
                    start_count=(
                        int(start_count)
                        if (start_count := _float_or_none(
                            raw_sample.get("start_count"),
                        ))
                        is not None
                        else None
                    ),
                )
            )
        return samples

    def append_weather_context_history(
        self,
        circuit_id: str,
        now: datetime,
        *,
        temperature: float,
        runtime_minutes: float,
        duty_cycle_percent: float,
        mode: str | None = None,
    ) -> bool:
        coordinator = self._coordinator
        history = coordinator.store_data.weather_context_history_by_circuit.setdefault(
            circuit_id,
            [],
        )
        time_zone = coordinator.context_builder.time_zone()
        if mode is not None:
            same_day = [
                item
                for item in history
                if (
                    (sample_time := _datetime_or_none(item.get("timestamp")))
                    is not None
                    and _ha_local_date(sample_time, time_zone)
                    == _ha_local_date(now, time_zone)
                )
            ]
            existing = next(
                (
                    item
                    for item in same_day
                    if _weather_context_sample_mode(item) == mode
                ),
                None,
            )
            mode_runtime, mode_duty, mode_elapsed = _weather_context_mode_metrics(
                history,
                now,
                time_zone,
                mode=mode,
                runtime_minutes=runtime_minutes,
                duty_cycle_percent=duty_cycle_percent,
            )
            sample = {
                "timestamp": now.isoformat(),
                "temperature": round(float(temperature), 3),
                "mode": mode,
                "runtime_minutes": round(mode_runtime, 3),
                "duty_cycle_percent": round(mode_duty, 3),
                "start_count": coordinator.state.run_cycle_count_by_circuit.get(
                    circuit_id,
                    0,
                ),
                "_mode_elapsed_minutes": round(mode_elapsed, 3),
            }
            if existing is not None:
                if existing == sample and history[-1] is existing:
                    return False
                history.remove(existing)
            history.append(sample)
            del history[:-WEATHER_CONTEXT_HISTORY_MAX_SAMPLES]
            return True

        sample = {
            "timestamp": now.isoformat(),
            "temperature": round(float(temperature), 3),
            "runtime_minutes": round(float(runtime_minutes), 3),
            "duty_cycle_percent": round(float(duty_cycle_percent), 3),
            "start_count": coordinator.state.run_cycle_count_by_circuit.get(
                circuit_id,
                0,
            ),
        }
        for index in range(len(history) - 1, -1, -1):
            existing_time = _datetime_or_none(history[index].get("timestamp"))
            if existing_time is not None and _ha_local_date(
                existing_time,
                time_zone,
            ) == _ha_local_date(now, time_zone):
                if history[index] == sample:
                    return False
                history[index] = sample
                return True

        history.append(sample)
        del history[:-WEATHER_CONTEXT_HISTORY_MAX_SAMPLES]
        return True

    def _mark_store_dirty(self) -> None:
        self._coordinator.store_persistence.mark_dirty()


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ha_local_date(value: datetime, time_zone: str | None) -> Any:
    if time_zone is None or value.tzinfo is None:
        return value.date()
    return local_date(value, time_zone)


def _water_context_history_sample_is_dry(sample: Mapping[str, Any]) -> bool:
    raw_issues = sample.get("rain_context_issues")
    if isinstance(raw_issues, str) and raw_issues.strip():
        return False
    if isinstance(raw_issues, (list, tuple, set)) and raw_issues:
        return False
    intensity = _float_or_none(sample.get("rain_intensity_mm_per_hour"))
    if intensity is not None and intensity > 0.0:
        return False
    rain_state = str(sample.get("rain_state") or "").strip().lower()
    if rain_state:
        return rain_state == "dry"
    return sample.get("rain_active") is False


def _weather_context_mode(
    config: CircuitConfig,
    outdoor_temperature: float | None = None,
) -> str:
    if config.appliance_profile is ApplianceProfile.ELECTRIC_HEAT:
        return "heating"
    if config.appliance_profile in MODE_PARTITIONED_HVAC_PROFILES:
        return weather_mode_for_temperature(outdoor_temperature)
    return "cooling"


def _weather_context_sample_mode(sample: Mapping[str, Any]) -> str:
    mode = str(sample.get("mode") or "").casefold()
    return mode or weather_mode_for_temperature(
        _float_or_none(sample.get("temperature")),
    )


def _weather_context_sample_elapsed(sample: Mapping[str, Any]) -> float:
    elapsed = _float_or_none(sample.get("_mode_elapsed_minutes"))
    if elapsed is not None:
        return elapsed
    runtime = _float_or_none(sample.get("runtime_minutes")) or 0.0
    duty = _float_or_none(sample.get("duty_cycle_percent")) or 0.0
    return runtime * 100.0 / duty if duty > 0.0 else 0.0


def _weather_context_mode_metrics(
    history: Iterable[Mapping[str, Any]],
    now: datetime,
    time_zone: str | None,
    *,
    mode: str,
    runtime_minutes: float,
    duty_cycle_percent: float,
) -> tuple[float, float, float]:
    same_day = [
        (sample, sample_time)
        for sample in history
        if (
            (sample_time := _datetime_or_none(sample.get("timestamp"))) is not None
            and _ha_local_date(sample_time, time_zone)
            == _ha_local_date(now, time_zone)
        )
    ]
    other_samples = [
        sample
        for sample, _ in same_day
        if _weather_context_sample_mode(sample) != mode
    ]
    mode_runtime = max(
        float(runtime_minutes)
        - sum(
            _float_or_none(sample.get("runtime_minutes")) or 0.0
            for sample in other_samples
        ),
        0.0,
    )
    existing = next(
        (
            sample
            for sample, _ in same_day
            if _weather_context_sample_mode(sample) == mode
        ),
        None,
    )
    latest_time = max(
        (sample_time for _, sample_time in same_day),
        default=None,
    )
    mode_elapsed = (
        _weather_context_sample_elapsed(existing)
        if existing is not None
        else (
            float(runtime_minutes) * 100.0 / duty_cycle_percent
            if not same_day and duty_cycle_percent > 0.0
            else 0.0
        )
    ) + (
        max((now - latest_time).total_seconds() / 60.0, 0.0)
        if latest_time is not None
        else 0.0
    )
    mode_duty = (
        mode_runtime * 100.0 / mode_elapsed
        if mode_elapsed > 0.0
        else float(duty_cycle_percent)
    )
    return mode_runtime, mode_duty, mode_elapsed


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
