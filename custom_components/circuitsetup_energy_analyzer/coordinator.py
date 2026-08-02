from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Self

from .activity_timeline import (
    DEFAULT_TIMELINE_WINDOW_HOURS,
)
from .appliance_notifications import mixed_circuit_allows_alert
from .config_parsing import (
    circuit_configs_from_entry_data as _circuit_configs_from_entry_data,
)
from .config_parsing import (
    mains_context_config_from_sources,
)
from .const import (
    CONF_CIRCUITS,
    DOMAIN,
    EVENT_HVAC_ASSOCIATION_UPDATED,
)
from .discovery import discovered_sensor_roles
from .expected_schedule import (
    expected_schedule_circuit_ids,
    refresh_expected_schedule_contexts,
)
from .managers.source_samples import normalized_leg
from .managers.utility_energy_sources import (
    _ha_recorder_get_instance,
    _ha_statistics_during_period,
)
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    RetentionMode,
    SensorRole,
)
from .normalize import NormalizedCircuitSample, SourceState
from .notifications import notification_id_for_alert
from .operating_detection import resolve_operating_detection_from_settings
from .processors import (
    FeatureResult,
)
from .runtime_factory import initialize_runtime
from .state import (
    AnalyzerState,
    circuit_is_learning,
    process_events_into_state,
)
from .storage import (
    FeatureStoreData,
)
from .ux import (
    canonicalize_sensitivity_config,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS = 0.5
SOURCE_STATE_UPDATE_MAX_BATCH_SECONDS = 5.0
SETTINGS_RECOMMENDATION_SOURCE_REFRESH_INTERVAL = timedelta(minutes=5)
_EXPECTED_SCHEDULE_ALERT_FEATURES = frozenset(
    {"expected_schedule_missed", "running_outside_expected_schedule"}
)
_UTILITY_COMPARISON_ALERT_FEATURES = frozenset({"utility_energy_mismatch"})
try:
    from homeassistant.helpers.event import (
        async_track_point_in_time,
        async_track_state_change_event,
        async_track_time_interval,
    )
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
except ModuleNotFoundError:
    async_track_state_change_event = None
    async_track_point_in_time = None
    async_track_time_interval = None

    class DataUpdateCoordinator:
        """Small fallback so helper tests can import without Home Assistant."""

        def __init__(
            self,
            hass: Any,
            logger: logging.Logger | None = None,
            *,
            name: str | None = None,
            **_: Any,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.data: Any = None

        def async_set_updated_data(self, data: Any) -> None:
            self.data = data


def _normalized_entity_ids(entity_ids: Iterable[str] | None) -> set[str]:
    if entity_ids is None:
        return set()
    return {
        entity_id
        for entity_id in (str(entity_id).strip() for entity_id in entity_ids)
        if entity_id
    }


def _alerts_outside_cross_circuit_features(
    state: Any,
    *,
    utility_circuit_ids: set[str],
    schedule_circuit_ids: set[str],
) -> list[AlertEvidence]:
    active_alerts = getattr(state, "active_alerts_by_circuit", {})
    preserved: list[AlertEvidence] = []
    for circuit_id in utility_circuit_ids | schedule_circuit_ids:
        evaluated_features = (
            _UTILITY_COMPARISON_ALERT_FEATURES
            if circuit_id in utility_circuit_ids
            else frozenset()
        ) | (
            _EXPECTED_SCHEDULE_ALERT_FEATURES
            if circuit_id in schedule_circuit_ids
            else frozenset()
        )
        preserved.extend(
            alert
            for alert in active_alerts.get(circuit_id, ())
            if alert.feature not in evaluated_features
        )
    return preserved


def _source_circuit_ids_by_entity(
    circuit_configs: Iterable[CircuitConfig],
) -> dict[str, tuple[str, ...]]:
    circuit_ids_by_entity: defaultdict[str, list[str]] = defaultdict(list)
    for config in circuit_configs:
        for sensor in config.sensors:
            entity_id = str(sensor.entity_id).strip()
            if entity_id:
                circuit_ids_by_entity[entity_id].append(config.circuit_id)
    return {
        entity_id: tuple(circuit_ids)
        for entity_id, circuit_ids in circuit_ids_by_entity.items()
    }


class EnergyAnalyzerCoordinator(DataUpdateCoordinator):
    """Runtime coordinator for source sensor updates and analyzer state."""

    def __init__(
        self: Self,
        hass: Any,
        *,
        entry_id: str = "default",
        entry_data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        store: Any | None = None,
        store_data: FeatureStoreData | None = None,
        config_entry: Any | None = None,
        now_fn: Any | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry_id = entry_id
        self.entry_data = canonicalize_sensitivity_config(entry_data or {})
        self.options = canonicalize_sensitivity_config(options or {})
        self._config_entry = config_entry
        self._store = store
        self.store_data = store_data or FeatureStoreData()
        candidate_configs = _circuit_configs_from_entry_data(
            self.entry_data,
            self.options,
        )
        mains_sensor_roles = discovered_sensor_roles(
            hass,
            (
                sensor.entity_id
                for config in candidate_configs
                if config.mode is CircuitMode.MAINS_NILM
                or config.circuit_id == "mains"
                for sensor in config.sensors
            ),
        )
        self.circuit_configs = _circuit_configs_from_entry_data(
            self.entry_data,
            self.options,
            mains_sensor_roles=mains_sensor_roles,
        )
        self._mains_context_config = mains_context_config_from_sources(
            self.entry_data,
            self.options,
            mains_sensor_roles=mains_sensor_roles,
        )
        self._mains_voltage_entity_ids = frozenset(
            sensor.entity_id
            for sensor in (
                self._mains_context_config.sensors
                if self._mains_context_config is not None
                else ()
            )
            if sensor.role is SensorRole.VOLTAGE
        )
        self._source_circuit_ids_by_entity = _source_circuit_ids_by_entity(
            self.circuit_configs
        )
        self._known_source_entity_ids = frozenset(self._source_circuit_ids_by_entity)
        initialize_runtime(
            self,
            hass=hass,
            entry_id=entry_id,
            now_fn=now_fn,
            statistics_during_period=_ha_statistics_during_period,
            recorder_get_instance=_ha_recorder_get_instance,
            track_state_change_event=async_track_state_change_event,
            debounce_seconds=SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS,
            max_batch_seconds=SOURCE_STATE_UPDATE_MAX_BATCH_SECONDS,
        )
        self._mixed_startup_store_dirty = False
        self._mixed_startup_direct_alert_ids: set[str] = set()
        for config in self.circuit_configs:
            if (
                config.mode is CircuitMode.MIXED
                or config.appliance_profile is ApplianceProfile.MIXED
            ):
                self._mixed_startup_direct_alert_ids.update(
                    notification_id_for_alert(alert)
                    for alert in self.store_data.alerts
                    if alert.circuit_id == config.circuit_id
                    and not mixed_circuit_allows_alert(alert.feature)
                )
                self._mixed_startup_store_dirty |= (
                    self.store_persistence.clear_direct_appliance_state_for_circuit(
                        config.circuit_id, self._baseline_values
                    )
                )
        self._hydrate_state_from_store()
        self.async_set_updated_data(self.state)

    def async_set_updated_data(self: Self, data: Any) -> None:
        """Publish coordinator data and signal HVAC association revisions."""
        revisions = dict(
            getattr(data, "hvac_association_revision_by_circuit", {}) or {}
        )
        previous = getattr(self, "_published_hvac_association_revisions", None)
        super().async_set_updated_data(data)
        self._published_hvac_association_revisions = revisions
        if previous is None or previous == revisions:
            return
        fire = getattr(getattr(self.hass, "bus", None), "async_fire", None)
        if fire is not None:
            fire(EVENT_HVAC_ASSOCIATION_UPDATED, {"entry_id": self.entry_id})

    async def async_start(self: Self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        await self.evidence_actions.async_expire_maintenance_if_due(
            self.current_time()
        )
        if self._mixed_startup_direct_alert_ids:
            await self.notification_controller.async_dismiss_alert_notification_ids(
                self._mixed_startup_direct_alert_ids
            )
            self._mixed_startup_direct_alert_ids.clear()
        if self._mixed_startup_store_dirty:
            await self._async_save_store(self.current_time())
            self._mixed_startup_store_dirty = False
        entities = [
            str(entity_id)
            for entity_id in source_entities
            if str(entity_id) and not str(entity_id).startswith("schedule.")
        ]
        schedule_settings = getattr(
            self.store_data,
            "appliance_schedule_settings",
            {},
        )
        for raw in (
            schedule_settings.values()
            if isinstance(schedule_settings, Mapping)
            else ()
        ):
            if not isinstance(raw, Mapping) or raw.get("enabled") is not True:
                continue
            entity_id = str(raw.get("schedule_entity_id") or "").strip()
            if entity_id.startswith("schedule."):
                entities.append(entity_id)
        await self.source_updates.async_start(tuple(dict.fromkeys(entities)))
        self._refresh_expected_schedule_interval_listener()

    async def async_stop(self: Self) -> None:
        """Stop listening to source entity state changes."""
        if self._unsub_maintenance_expiry is not None:
            self._unsub_maintenance_expiry()
            self._unsub_maintenance_expiry = None
        if self._unsub_expected_schedule_interval is not None:
            self._unsub_expected_schedule_interval()
            self._unsub_expected_schedule_interval = None
        await self.source_updates.async_stop()

    def refresh_maintenance_expiry_listener(self: Self) -> None:
        """Schedule the next timed maintenance expiry."""
        if self._unsub_maintenance_expiry is not None:
            self._unsub_maintenance_expiry()
            self._unsub_maintenance_expiry = None
        expires_at = self.evidence_actions.next_maintenance_expiry()
        if async_track_point_in_time is None or expires_at is None:
            return
        self._unsub_maintenance_expiry = async_track_point_in_time(
            self.hass,
            self._async_handle_maintenance_expiry,
            expires_at,
        )

    async def _async_handle_maintenance_expiry(self: Self, now: datetime) -> None:
        """Expire maintenance from Home Assistant's event-loop timer."""
        self._unsub_maintenance_expiry = None
        await self.evidence_actions.async_expire_maintenance_if_due(now)

    def _refresh_expected_schedule_interval_listener(self: Self) -> None:
        """Refresh periodic evaluation for local expected-schedule windows."""
        if self._unsub_expected_schedule_interval is not None:
            self._unsub_expected_schedule_interval()
            self._unsub_expected_schedule_interval = None
        if async_track_time_interval is None or not self._has_local_schedule_windows():
            return
        self._unsub_expected_schedule_interval = async_track_time_interval(
            self.hass,
            self.async_refresh_expected_schedules,
            timedelta(minutes=5),
        )

    def _has_local_schedule_windows(self: Self) -> bool:
        """Return whether any enabled schedule uses locally configured windows."""
        schedule_settings = getattr(
            self.store_data,
            "appliance_schedule_settings",
            {},
        )
        for raw in (
            schedule_settings.values()
            if isinstance(schedule_settings, Mapping)
            else ()
        ):
            if not isinstance(raw, Mapping) or raw.get("enabled") is not True:
                continue
            if str(raw.get("schedule_entity_id") or "").strip():
                continue
            windows = raw.get("windows")
            if isinstance(windows, list) and bool(windows):
                return True
        return False

    async def async_refresh_expected_schedules(self: Self, now: datetime) -> None:
        """Evaluate local schedule boundaries without a source state change."""
        await self.evidence_actions.async_expire_maintenance_if_due(now)
        schedule_circuit_ids = expected_schedule_circuit_ids(self)
        alerts = _alerts_outside_cross_circuit_features(
            self.state,
            utility_circuit_ids=set(),
            schedule_circuit_ids=schedule_circuit_ids,
        )
        alerts.extend(await self._async_apply_expected_schedule_contexts(now))
        if schedule_circuit_ids or alerts:
            process_events_into_state(
                self.state,
                (),
                alerts,
                evaluated_circuit_ids=schedule_circuit_ids,
            )
        if schedule_circuit_ids:
            await self.notification_controller.async_sync_alert_notifications(
                schedule_circuit_ids
            )
        self.async_set_updated_data(self.state)
        await self._async_save_store(now, force=False)

    async def _async_apply_expected_schedule_contexts(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        """Evaluate schedule context and persist any new evidence."""
        active_alerts: list[AlertEvidence] = []
        for schedule_alert in refresh_expected_schedule_contexts(self, now):
            if not self.notification_controller.learning_allows_alert(schedule_alert):
                continue
            schedule_alert = self.evidence_actions.alert_with_feedback(schedule_alert)
            if schedule_alert.feedback_status != "expected":
                active_alerts.append(schedule_alert)
            self.store_data.alerts.append(schedule_alert)
            self._mark_store_dirty()
            await self._notify_alert(schedule_alert)
        current_appliance_keys = {
            str(alert.features.get("appliance_key") or "")
            for alert in active_alerts
        }
        contexts = getattr(self.state, "expected_schedule_by_appliance", {})
        for circuit_alerts in getattr(
            self.state,
            "active_alerts_by_circuit",
            {},
        ).values():
            for alert in circuit_alerts:
                appliance_key = str(alert.features.get("appliance_key") or "")
                context = (
                    contexts.get(appliance_key, {})
                    if isinstance(contexts, Mapping)
                    else {}
                )
                if (
                    alert.feature not in _EXPECTED_SCHEDULE_ALERT_FEATURES
                    or appliance_key in current_appliance_keys
                    or not isinstance(context, Mapping)
                    or context.get("alert_ready") is not True
                    or not self.notification_controller.learning_allows_alert(alert)
                ):
                    continue
                alert = self.evidence_actions.alert_with_feedback(alert)
                if alert.feedback_status != "expected":
                    active_alerts.append(alert)
                    current_appliance_keys.add(appliance_key)
        return active_alerts

    @property
    def source_entities(self: Self) -> tuple[str, ...]:
        """Configured source entities currently watched by the coordinator."""
        return self.source_updates.source_entities

    @source_entities.setter
    def source_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.source_entities = tuple(value)

    @property
    def pending_source_update_entities(self: Self) -> tuple[str, ...]:
        """Source entities queued for the next debounced update."""
        return self.source_updates.pending_source_update_entities

    @pending_source_update_entities.setter
    def pending_source_update_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.pending_source_update_entities = tuple(value)

    @property
    def last_source_update_entities(self: Self) -> tuple[str, ...]:
        """Source entities included in the most recent debounced update."""
        return self.source_updates.last_source_update_entities

    @last_source_update_entities.setter
    def last_source_update_entities(self: Self, value: Iterable[str]) -> None:
        self.source_updates.last_source_update_entities = tuple(value)

    def current_time(self: Self) -> datetime:
        """Return the coordinator's current runtime timestamp."""
        return self._now_fn()

    def _processing_configs_for_changed_entities(
        self: Self,
        changed_entities: Iterable[str] | None,
    ) -> tuple[CircuitConfig, ...]:
        """Return circuit configs that need expensive per-circuit processing."""
        changed = _normalized_entity_ids(changed_entities)
        if not changed:
            return tuple(self.circuit_configs)

        if changed & self._mains_voltage_entity_ids:
            return tuple(self.circuit_configs)

        if not changed.issubset(self._known_source_entity_ids):
            return tuple(self.circuit_configs)

        selected_circuit_ids = {
            circuit_id
            for entity_id in changed
            for circuit_id in self._source_circuit_ids_by_entity.get(entity_id, ())
        }
        if not selected_circuit_ids:
            return tuple(self.circuit_configs)

        selected_configs = [
            config
            for config in self.circuit_configs
            if config.circuit_id in selected_circuit_ids
        ]
        if any(
            not self.nilm_controller.enabled_for_config(config)
            for config in selected_configs
        ):
            selected_circuit_ids.update(
                config.circuit_id
                for config in self.circuit_configs
                if self.nilm_controller.enabled_for_config(config)
            )

        return tuple(
            config
            for config in self.circuit_configs
            if config.circuit_id in selected_circuit_ids
        )

    def _settings_recommendation_refresh_due(
        self: Self,
        now: datetime,
        *,
        changed_entities: Iterable[str] | None,
        force: bool,
    ) -> bool:
        if changed_entities is None:
            return True
        if force or self._last_settings_recommendation_source_refresh_at is None:
            self._last_settings_recommendation_source_refresh_at = now
            return True
        if (
            now - self._last_settings_recommendation_source_refresh_at
            >= SETTINGS_RECOMMENDATION_SOURCE_REFRESH_INTERVAL
        ):
            self._last_settings_recommendation_source_refresh_at = now
            return True
        return False

    def refresh_energy_goal_state(
        self: Self,
        circuit_id: str,
        config: CircuitConfig,
        context: Any,
    ) -> FeatureResult:
        """Refresh daily energy-goal state through the configured processor."""
        return self._energy_goal_processor.refresh_state(circuit_id, config, context)

    async def async_process_update(
        self: Self,
        *,
        changed_entities: Iterable[str] | None = None,
    ) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        processing_configs = self._processing_configs_for_changed_entities(
            changed_entities
        )
        previous_learning = {
            config.circuit_id: circuit_is_learning(
                self.state,
                config.circuit_id,
            )
            for config in processing_configs
        }
        await self.evidence_actions.async_expire_maintenance_if_due(now)
        context = self.context_builder.build(now)
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []
        processing_circuit_ids = {
            config.circuit_id for config in processing_configs
        }
        utility_settings = getattr(
            self.store_data,
            "utility_comparison_settings_by_circuit",
            {},
        )
        utility_comparison_circuit_ids = (
            {
                circuit_id
                for raw_circuit_id in utility_settings
                if (circuit_id := str(raw_circuit_id).strip())
                and self.circuit_registry.config_for_circuit(circuit_id) is not None
            }
            if isinstance(utility_settings, Mapping)
            else set()
        )
        schedule_circuit_ids = expected_schedule_circuit_ids(self)
        mains_context_sample = self._mains_context_sample(now)
        self.state_reducer.prune_recent_observations(
            self.state,
            now,
            window_hours=DEFAULT_TIMELINE_WINDOW_HOURS,
        )

        for config in self.circuit_configs:
            sample = self._sample_for_config(
                config,
                now,
                mains_context_sample=mains_context_sample,
            )
            samples.append((config, sample))
            self.state_reducer.refresh_config_metadata_state(self.state, config)
            self.state_reducer.refresh_latest_real_power_state(
                self.state,
                config,
                sample,
            )
            if config.circuit_id not in processing_circuit_ids:
                continue
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            new_events, new_alerts = await self.pipeline.async_process_circuit(
                config,
                sample,
                context,
            )
            events.extend(new_events)
            alerts.extend(new_alerts)

        for config, sample in samples:
            if config.circuit_id not in processing_circuit_ids:
                continue
            for nilm_alert in self.nilm_controller.process_sample(
                config,
                sample,
                events,
                context,
            ):
                if not self.notification_controller.learning_allows_alert(nilm_alert):
                    continue
                nilm_alert = self.evidence_actions.alert_with_feedback(nilm_alert)
                if nilm_alert.feedback_status != "expected":
                    alerts.append(nilm_alert)
                self.store_data.alerts.append(nilm_alert)
                self._mark_store_dirty()
                await self._notify_alert(nilm_alert)
            await asyncio.sleep(0)
        alerts.extend(await self._notify_nilm_virtual_appliances(now))
        alerts.extend(await self.pipeline.async_process_cross_circuit(samples, context))
        alerts.extend(
            await self.notification_controller.async_notify_finished_events(
                events,
                now,
            )
        )

        intermediate_alerts = [
            *alerts,
            *_alerts_outside_cross_circuit_features(
                self.state,
                utility_circuit_ids=(
                    utility_comparison_circuit_ids - processing_circuit_ids
                ),
                schedule_circuit_ids=(
                    schedule_circuit_ids - processing_circuit_ids
                ),
            ),
        ]
        active_alerts_by_circuit = getattr(
            self.state,
            "active_alerts_by_circuit",
            {},
        )
        intermediate_alerts.extend(
            alert
            for circuit_id in schedule_circuit_ids
            for alert in active_alerts_by_circuit.get(circuit_id, ())
            if alert.feature in _EXPECTED_SCHEDULE_ALERT_FEATURES
        )
        process_events_into_state(
            self.state,
            events,
            intermediate_alerts,
            evaluated_circuit_ids=processing_circuit_ids,
        )
        events_by_circuit = _items_by_circuit(self.store_data.events)
        alerts_by_circuit = _items_by_circuit(self.store_data.alerts)
        for config, sample in samples:
            self._refresh_ux_state(
                config,
                sample,
                now,
                context,
                circuit_events=events_by_circuit.get(config.circuit_id, ()),
                circuit_alerts=alerts_by_circuit.get(config.circuit_id, ()),
            )
            await asyncio.sleep(0)
            if config.circuit_id not in processing_circuit_ids:
                continue
            await self._sync_setup_health_repairs(config.circuit_id)
            water_context_alert = self.environment_context.observe_water_context(
                config,
                now,
            )
            if (
                water_context_alert is not None
                and self.notification_controller.learning_allows_alert(
                    water_context_alert
                )
            ):
                water_context_alert = self.evidence_actions.alert_with_feedback(
                    water_context_alert
                )
                if water_context_alert.feedback_status != "expected":
                    alerts.append(water_context_alert)
                self.store_data.alerts.append(water_context_alert)
                self._mark_store_dirty()
                await self._notify_alert(water_context_alert)
        alerts.extend(
            _alerts_outside_cross_circuit_features(
                self.state,
                utility_circuit_ids=(
                    utility_comparison_circuit_ids - processing_circuit_ids
                ),
                schedule_circuit_ids=(
                    schedule_circuit_ids - processing_circuit_ids
                ),
            )
        )
        alerts.extend(await self._async_apply_expected_schedule_contexts(now))
        evaluated_alert_circuit_ids = (
            processing_circuit_ids
            | utility_comparison_circuit_ids
            | schedule_circuit_ids
        )
        if alerts or utility_comparison_circuit_ids or schedule_circuit_ids:
            process_events_into_state(
                self.state,
                events,
                alerts,
                evaluated_circuit_ids=evaluated_alert_circuit_ids,
            )
        recommendation_refresh_due = self._settings_recommendation_refresh_due(
            now,
            changed_entities=changed_entities,
            force=bool(alerts),
        )
        if recommendation_refresh_due and self._rebuild_setting_recommendations(now):
            self._mark_store_dirty()
        await self.notification_controller.async_notify_learning_transitions(
            previous_learning,
            now,
        )
        await self.notification_controller.async_sync_alert_notifications(
            evaluated_alert_circuit_ids
        )
        await self.notification_controller.async_dispatch_due(now)
        await self.notification_controller.async_refresh_weekly_digest(now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now, force=False)
        if recommendation_refresh_due:
            await (
                self.notification_controller.async_notify_settings_recommendations_if_needed()
            )
        return self.state

    async def async_relearn_baseline(self: Self, circuit_id: str) -> None:
        """Clear learned baselines and alert state for one circuit."""
        now = self._now_fn()
        hvac_prefix = f"{circuit_id}|"
        active_hvac_markers = {
            stream_id: {
                **raw,
                "ended_at": now.isoformat(),
                "complete": False,
                "excluded_from_baseline": True,
                "inactive_since": None,
                "baseline_era": self.store_data.hvac_baseline_era_by_stream.get(
                    stream_id,
                    "initial",
                ),
            }
            for stream_id, raw in self.state.hvac_current_episode_by_stream.items()
            if stream_id.startswith(hvac_prefix) and isinstance(raw, Mapping) and raw
        }
        await self.notification_controller.async_dismiss_circuit_alert_notifications(
            circuit_id
        )
        self.store_persistence.reset_baseline_for_circuit(
            circuit_id,
            self._baseline_values,
            now,
        )
        for stream_id, marker in active_hvac_markers.items():
            self.store_data.hvac_response_history_by_stream.setdefault(
                stream_id,
                [],
            ).append(marker)
        self._run_cycle_processor.reset_cold_storage_state(circuit_id)
        self.settings_controller.clear_cycle_alert_policies(circuit_id)
        self.state_reducer.reset_learning_state(self.state, circuit_id)
        self._clear_nilm_topology_state(circuit_id)
        self.refresh_ux_state_for_circuit(circuit_id, now)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)

    async def async_pause_alerts(
        self: Self,
        circuit_id: str,
        duration: str | None = None,
    ) -> None:
        """Pause alert notifications for a circuit."""
        await self.evidence_actions.async_pause_alerts(circuit_id, duration)

    async def async_acknowledge_alert(self: Self, alert_id: str) -> bool:
        """Acknowledge an active alert evidence item."""
        return await self.evidence_actions.async_acknowledge_alert(alert_id)

    async def async_set_circuit_sensitivity(
        self: Self,
        circuit_id: str,
        preset: str,
    ) -> None:
        """Persist an alert sensitivity preset for one circuit."""
        await self.settings_controller.async_set_circuit_sensitivity(
            circuit_id,
            preset,
        )

    async def async_mark_circuit_mixed(self, circuit_id: str) -> None:
        """Persist a user-confirmed shared circuit and reconcile direct state."""
        config = self.circuit_registry.config_for_circuit(circuit_id)
        if (
            config is None
            or config.mode in (CircuitMode.MAINS_NILM, CircuitMode.DUAL_PHASE)
            or config.power_flow.value != "load"
        ):
            raise ValueError(f"Circuit cannot be marked mixed: {circuit_id}")
        if config.mode is not CircuitMode.MIXED:
            circuits = [dict(item) for item in self.options.get(
                CONF_CIRCUITS, self.entry_data.get(CONF_CIRCUITS, [])
            )]
            found = False
            for item in circuits:
                if item.get("circuit_id") == circuit_id:
                    item["mode"] = CircuitMode.MIXED.value
                    found = True
                    break
            if not found:
                raise ValueError(f"Circuit is not explicitly configured: {circuit_id}")
            await self.config_entry_controller.async_update_options(
                {CONF_CIRCUITS: circuits}
            )

        cleanup_error: BaseException | None = None
        try:
            await (
                self.notification_controller.async_dismiss_circuit_alert_notifications(
                    circuit_id
                )
            )
            self.store_persistence.clear_direct_appliance_state_for_circuit(
                circuit_id, self._baseline_values
            )
            self.state_reducer.clear_direct_appliance_state(self.state, circuit_id)
            now = self.current_time()
            self.state_reducer.refresh_recent_activity_state(
                self.state, self.store_data, circuit_id, now
            )
            self.refresh_ux_state_for_circuit(circuit_id, now)
            self.async_set_updated_data(self.state)
            await self._async_save_store(now)
        except BaseException as err:
            cleanup_error = err
        try:
            await self.config_entry_controller.async_reload()
        except BaseException as reload_error:
            if cleanup_error is not None:
                raise cleanup_error from reload_error
            raise
        if cleanup_error is not None:
            raise cleanup_error

    async def async_set_entity_detail_level(self: Self, detail_level: str) -> None:
        """Persist the entity detail level and reload desired entities."""
        await self.entity_profile_controller.async_set_entity_detail_level(
            detail_level,
        )

    async def async_replace_advanced_settings(
        self: Self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace store-backed advanced settings for one circuit."""
        await self.settings_controller.async_replace_advanced_settings(
            circuit_id,
            settings,
        )

    async def async_set_energy_usage_settings(
        self: Self,
        circuit_id: str,
        window_days: Any = None,
        daily_spike_ratio: Any = None,
    ) -> None:
        """Persist daily energy usage spike settings for one circuit."""
        await self.settings_controller.async_set_energy_usage_settings(
            circuit_id,
            window_days,
            daily_spike_ratio,
        )

    async def async_recalculate_setting_recommendations(
        self: Self,
        circuit_id: str | None = None,
    ) -> None:
        """Rebuild pending advanced-setting recommendations from retained data."""
        await self.settings_controller.async_recalculate_setting_recommendations(
            circuit_id,
        )

    def _rebuild_setting_recommendations(
        self: Self,
        now: datetime,
        *,
        circuit_id: str | None = None,
    ) -> bool:
        """Rebuild pending recommendations without saving or notifying."""
        return self.settings_controller.rebuild_setting_recommendations(
            now,
            circuit_id=circuit_id,
        )

    async def async_apply_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Apply one pending setting recommendation to advanced settings."""
        await self.settings_controller.async_apply_setting_recommendation(
            recommendation_id,
        )

    async def async_undo_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> bool:
        """Restore the value recorded before an applied recommendation."""
        return await self.settings_controller.async_undo_setting_recommendation(
            recommendation_id,
        )

    async def async_reset_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> bool:
        """Reset a recommendation-backed setting to its built-in default."""
        return await self.settings_controller.async_reset_setting_recommendation(
            recommendation_id,
        )

    async def async_deny_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Record a denial for one pending setting recommendation."""
        await self.settings_controller.async_deny_setting_recommendation(
            recommendation_id,
        )

    async def async_dismiss_setting_recommendation(
        self: Self,
        recommendation_id: str,
    ) -> None:
        """Record a dismissal for one pending setting recommendation."""
        await self.settings_controller.async_dismiss_setting_recommendation(
            recommendation_id,
        )

    def _refresh_settings_recommendation_state(self: Self, now: datetime) -> None:
        self.settings_controller.refresh_settings_recommendation_state(now)

    async def async_set_energy_goal_settings(
        self: Self,
        circuit_id: str,
        daily_goal_kwh: Any = None,
        goal_alert_ratio: Any = None,
    ) -> None:
        """Persist daily energy goal settings for one circuit."""
        await self.settings_controller.async_set_energy_goal_settings(
            circuit_id,
            daily_goal_kwh,
            goal_alert_ratio,
        )

    async def async_set_activity_alert_settings(
        self: Self,
        circuit_id: str,
        max_active_minutes: Any = None,
        max_idle_minutes: Any = None,
    ) -> None:
        """Persist user-configured activity alert settings for one circuit."""
        await self.settings_controller.async_set_activity_alert_settings(
            circuit_id,
            max_active_minutes,
            max_idle_minutes,
        )

    async def async_set_billing_cycle_settings(
        self: Self,
        circuit_id: str,
        cycle_start_day: Any = None,
        budget_kwh: Any = None,
        budget_alert_ratio: Any = None,
    ) -> None:
        """Persist billing-cycle usage forecast settings for one circuit."""
        await self.settings_controller.async_set_billing_cycle_settings(
            circuit_id,
            cycle_start_day,
            budget_kwh,
            budget_alert_ratio,
        )

    async def async_set_cost_settings(
        self: Self,
        circuit_id: str,
        cycle_start_day: Any = None,
    ) -> None:
        """Persist the cost-cycle start day for one circuit."""
        await self.settings_controller.async_set_cost_settings(
            circuit_id,
            cycle_start_day,
        )

    async def async_set_global_cost_rate(
        self: Self,
        rate_per_kwh: Any,
    ) -> None:
        """Persist the analyzer-wide electricity rate."""
        await self.settings_controller.async_set_global_cost_rate(rate_per_kwh)

    async def async_set_global_tou_rate(
        self: Self,
        rate_per_kwh: Any,
    ) -> None:
        """Persist the analyzer-wide Time-of-Use rate."""
        await self.settings_controller.async_set_global_tou_rate(rate_per_kwh)

    async def async_set_global_tou_time(
        self: Self,
        field: str,
        value: Any,
    ) -> None:
        """Persist one Time-of-Use boundary time."""
        await self.settings_controller.async_set_global_tou_time(field, value)

    async def async_set_global_tou_weekday(
        self: Self,
        weekday: int,
        enabled: bool,
    ) -> None:
        """Persist one Time-of-Use weekday toggle."""
        await self.settings_controller.async_set_global_tou_weekday(weekday, enabled)

    async def async_set_global_tou_name(self: Self, value: str) -> None:
        """Persist the analyzer-wide Time-of-Use label."""
        await self.settings_controller.async_set_global_tou_name(value)

    async def async_set_demand_settings(
        self: Self,
        circuit_id: str,
        window_minutes: Any = None,
        demand_limit_w: Any = None,
    ) -> None:
        """Persist rolling demand settings for one circuit."""
        await self.settings_controller.async_set_demand_settings(
            circuit_id,
            window_minutes,
            demand_limit_w,
        )

    async def async_set_capacity_settings(
        self: Self,
        circuit_id: str,
        breaker_amps: Any = None,
        warning_ratio: Any = None,
    ) -> None:
        """Persist circuit capacity settings for one circuit."""
        await self.settings_controller.async_set_capacity_settings(
            circuit_id,
            breaker_amps,
            warning_ratio,
        )

    async def async_set_leg_imbalance_settings(
        self: Self,
        circuit_id: str,
        warning_ratio: Any = None,
        minimum_total_power_w: Any = None,
    ) -> None:
        """Persist dual-phase leg imbalance thresholds for one circuit."""
        await self.settings_controller.async_set_leg_imbalance_settings(
            circuit_id,
            warning_ratio,
            minimum_total_power_w,
        )

    async def async_set_metric_consistency_settings(
        self: Self,
        circuit_id: str,
        apparent_power_tolerance_percent: Any = None,
        power_factor_tolerance: Any = None,
        minimum_apparent_power_va: Any = None,
    ) -> None:
        """Persist W/VA/PF consistency thresholds for one circuit."""
        await self.settings_controller.async_set_metric_consistency_settings(
            circuit_id,
            apparent_power_tolerance_percent,
            power_factor_tolerance,
            minimum_apparent_power_va,
        )

    async def async_set_mains_balance_settings(
        self: Self,
        circuit_id: str,
        negative_tolerance_w: Any = None,
    ) -> None:
        """Persist mains-minus-monitored balance thresholds."""
        await self.settings_controller.async_set_mains_balance_settings(
            circuit_id,
            negative_tolerance_w,
        )

    async def async_set_solar_flow_settings(
        self: Self,
        circuit_id: str,
        export_tolerance_w: Any = None,
        solar_surplus_threshold_w: Any = None,
        high_solar_surplus_threshold_w: Any = None,
        flexible_load_running_threshold_w: Any = None,
    ) -> None:
        """Persist solar flow and flexible-load thresholds."""
        await self.settings_controller.async_set_solar_flow_settings(
            circuit_id,
            export_tolerance_w,
            solar_surplus_threshold_w,
            high_solar_surplus_threshold_w,
            flexible_load_running_threshold_w,
        )

    async def async_set_standby_settings(
        self: Self,
        circuit_id: str,
        window_hours: Any = None,
        standby_threshold_w: Any = None,
        always_on_alert_w: Any = None,
    ) -> None:
        """Persist Always On and standby settings for one circuit."""
        await self.settings_controller.async_set_standby_settings(
            circuit_id,
            window_hours,
            standby_threshold_w,
            always_on_alert_w,
        )

    async def async_set_utility_comparison_settings(
        self: Self,
        circuit_id: str,
        utility_energy_entity: Any = None,
        measured_energy_entities: Any = None,
        tolerance_percent: Any = None,
        utility_statistic_id: Any = None,
        utility_source_type: Any = None,
        utility_statistic_period: Any = None,
        utility_cost_entity: Any = None,
    ) -> None:
        """Persist utility-vs-measured kWh comparison settings."""
        await self.settings_controller.async_set_utility_comparison_settings(
            circuit_id,
            utility_energy_entity,
            measured_energy_entities,
            tolerance_percent,
            utility_statistic_id,
            utility_source_type,
            utility_statistic_period,
            utility_cost_entity,
        )

    async def async_start_maintenance(
        self: Self,
        circuit_id: str,
        note: str = "",
        duration: str | None = None,
        relearn_on_end: bool = False,
    ) -> None:
        """Mark one circuit in maintenance and pause appliance notifications."""
        await self.evidence_actions.async_start_maintenance(
            circuit_id,
            note=note,
            duration=duration,
            relearn_on_end=relearn_on_end,
        )

    async def async_end_maintenance(
        self: Self,
        circuit_id: str,
        relearn: bool = False,
    ) -> None:
        """Clear maintenance state and optionally relearn the circuit baseline."""
        await self.evidence_actions.async_end_maintenance(circuit_id, relearn=relearn)
        self.refresh_maintenance_expiry_listener()

    async def async_mark_alert_expected(self: Self, alert_id: str) -> bool:
        """Mark an alert pattern as expected for future notifications."""
        return await self.evidence_actions.async_mark_alert_expected(alert_id)

    async def async_mark_alert_confirmed(self: Self, alert_id: str) -> bool:
        """Confirm an alert as a real issue."""
        return await self.evidence_actions.async_mark_alert_confirmed(alert_id)

    async def async_mark_alert_unhelpful(self: Self, alert_id: str) -> bool:
        """Mark an alert pattern as unhelpful for future notifications."""
        return await self.evidence_actions.async_mark_alert_unhelpful(alert_id)

    async def async_mark_nilm_appliance_correct(self: Self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as correct."""
        return await self.evidence_actions.async_mark_nilm_appliance_correct(alert_id)

    async def async_mark_nilm_appliance_wrong(self: Self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as the wrong appliance."""
        return await self.evidence_actions.async_mark_nilm_appliance_wrong(alert_id)

    async def async_export_diagnostics(self: Self, circuit_id: str) -> None:
        """Store a lightweight diagnostics export snapshot for a circuit."""
        await self.export_manager.async_export_diagnostics(circuit_id)

    async def async_export_history_csv(self: Self, circuit_id: str) -> None:
        """Store retained analyzer history for one circuit as CSV text."""
        await self.export_manager.async_export_history_csv(circuit_id)

    async def async_run_mapping_checks(self: Self) -> None:
        """Run lightweight source mapping checks."""
        await self.setup_health.async_run_mapping_checks()

    async def async_create_dashboard(self: Self) -> dict[str, Any]:
        """Create or update the recommended Home Assistant dashboard."""
        return await self.dashboard_controller.async_create_dashboard()

    async def async_remove_dashboard(self: Self) -> dict[str, Any]:
        """Remove the recommended Home Assistant dashboard."""
        return await self.dashboard_controller.async_remove_dashboard()

    async def async_set_dashboard_layout(self: Self, layout: str) -> None:
        """Persist the selected recommended-dashboard layout."""
        await self.dashboard_controller.async_set_dashboard_layout(layout)

    async def async_label_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        label: str,
    ) -> None:
        """Persist a user-confirmed label for a NILM signature."""
        await self.nilm_controller.async_label_nilm_signature(
            circuit_id,
            signature_id,
            label,
        )

    async def async_label_nilm_interval(
        self: Self,
        circuit_id: str,
        *,
        label: str,
        start: Any,
        end: Any,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
        mains_entity_id: str | None = None,
        ground_truth_entity_id: str | None = None,
        validation_start: Any = None,
        validation_end: Any = None,
        interval_id: str | None = None,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Persist a user-labeled NILM graph interval."""
        return await self.nilm_controller.async_label_nilm_interval(
            circuit_id,
            label=label,
            start=start,
            end=end,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            mains_entity_id=mains_entity_id,
            ground_truth_entity_id=ground_truth_entity_id,
            validation_start=validation_start,
            validation_end=validation_end,
            interval_id=interval_id,
            source=source,
            confidence=confidence,
        )

    async def async_delete_nilm_label_interval(
        self: Self,
        circuit_id: str,
        interval_id: str,
    ) -> bool:
        """Delete a user-labeled NILM graph interval."""
        return await self.nilm_controller.async_delete_nilm_label_interval(
            circuit_id,
            interval_id,
        )

    async def async_assign_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM signature to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_signature(
            circuit_id,
            signature_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_assign_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        label: str,
        signature_fingerprint: str | None = None,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM session to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_session(
            circuit_id,
            session_id,
            label=label,
            signature_fingerprint=signature_fingerprint,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_assign_nilm_interval(
        self: Self,
        circuit_id: str,
        interval_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM label interval to a durable appliance assignment."""
        return await self.nilm_controller.async_assign_nilm_interval(
            circuit_id,
            interval_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
        )

    async def async_validate_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session matched its appliance assignment."""
        return await self.nilm_controller.async_validate_nilm_session(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
        )

    async def async_reject_nilm_session(
        self: Self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session did not match its appliance assignment."""
        return await self.nilm_controller.async_reject_nilm_session(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
        )

    async def async_validate_nilm_assignment_history(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Confirm assigned NILM sessions that overlap ground-truth intervals."""
        return await self.nilm_controller.async_validate_nilm_assignment_history(
            circuit_id,
            assignment_id,
        )

    async def async_rename_nilm_appliance(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        """Rename a NILM appliance assignment without changing its stable ID."""
        return await self.nilm_controller.async_rename_nilm_appliance(
            circuit_id,
            assignment_id,
            label=label,
        )

    async def async_change_nilm_appliance_profile(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        appliance_profile: str,
    ) -> dict[str, Any]:
        """Change the appliance profile hint for a NILM assignment."""
        return await self.nilm_controller.async_change_nilm_appliance_profile(
            circuit_id,
            assignment_id,
            appliance_profile=appliance_profile,
        )

    async def async_convert_nilm_assignment_to_direct_meter(
        self: Self,
        circuit_id: str,
        assignment_id: str,
        *,
        direct_circuit_id: str,
        keep_assignment_for_masking: bool = True,
        keep_published_estimate: bool = False,
    ) -> dict[str, Any]:
        """Link a NILM appliance to a configured direct-meter circuit."""
        return await self.nilm_controller.async_convert_nilm_assignment_to_direct_meter(
            circuit_id,
            assignment_id,
            direct_circuit_id=direct_circuit_id,
            keep_assignment_for_masking=keep_assignment_for_masking,
            keep_published_estimate=keep_published_estimate,
        )

    async def async_merge_nilm_assignments(
        self: Self,
        circuit_id: str,
        source_assignment_id: str,
        target_assignment_id: str,
    ) -> dict[str, Any]:
        """Merge one NILM appliance assignment into another."""
        return await self.nilm_controller.async_merge_nilm_assignments(
            circuit_id,
            source_assignment_id,
            target_assignment_id,
        )

    async def async_publish_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Publish estimated HA entities for a NILM assignment."""
        return await self.nilm_controller.async_publish_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_unpublish_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Stop publishing estimated HA entities for a NILM assignment."""
        return await self.nilm_controller.async_unpublish_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_retire_nilm_appliance_assignment(
        self: Self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Retire a NILM assignment and stop publishing entities."""
        return await self.nilm_controller.async_retire_nilm_appliance_assignment(
            circuit_id,
            assignment_id,
        )

    async def async_ignore_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an ignored NILM signature marker."""
        await self.nilm_controller.async_ignore_nilm_signature(
            circuit_id,
            signature_id,
        )

    async def async_mark_nilm_signature_expected(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an expected NILM signature review decision."""
        await self.nilm_controller.async_mark_nilm_signature_expected(
            circuit_id,
            signature_id,
        )

    async def async_merge_nilm_signatures(
        self: Self,
        circuit_id: str,
        source_signature_id: str,
        target_signature_id: str,
    ) -> None:
        """Persist that one NILM signature should be treated as another."""
        await self.nilm_controller.async_merge_nilm_signatures(
            circuit_id,
            source_signature_id,
            target_signature_id,
        )

    def has_circuit(self: Self, circuit_id: str) -> bool:
        """Return whether this coordinator owns a circuit id."""
        return any(config.circuit_id == circuit_id for config in self.circuit_configs)

    def _hydrate_state_from_store(self: Self) -> None:
        self.ux_state.hydrate_state_from_store()

    def refresh_all_ux_state(self: Self, now: datetime) -> None:
        self.ux_state.refresh_all(now)

    def refresh_ux_state_for_circuit(
        self: Self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        self.ux_state.refresh_for_circuit(circuit_id, now)

    def _refresh_ux_state(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample | None,
        now: datetime,
        context: Any | None = None,
        *,
        circuit_events: Iterable[CircuitEvent] | None = None,
        circuit_alerts: Iterable[AlertEvidence] | None = None,
    ) -> None:
        self.ux_state.refresh_config(
            config,
            sample,
            now,
            context,
            circuit_events=circuit_events,
            circuit_alerts=circuit_alerts,
        )

    def _latest_alert_for_circuit(self: Self, circuit_id: str) -> AlertEvidence | None:
        return self.ux_state.latest_alert_for_circuit(circuit_id)

    def _sample_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
        *,
        mains_context_sample: NormalizedCircuitSample | None = None,
    ) -> NormalizedCircuitSample:
        off_threshold_w = resolve_operating_detection_from_settings(
            config,
            self.store_data.operating_detection_settings_by_circuit.get(
                config.circuit_id,
                {},
            ),
        ).profile.off_threshold_w
        sample = self.source_samples.sample_for_config(
            config,
            now,
            inactive_power_threshold_w=off_threshold_w,
        )
        if config.mode is CircuitMode.MAINS_NILM:
            return sample
        mains_sample = mains_context_sample or self._mains_context_sample(now)
        if mains_sample is None:
            return sample
        circuit_legs = {
            leg
            for sensor in config.sensors
            if (leg := normalized_leg(sensor.leg)) is not None
        }
        shared_voltage = mains_sample.voltage
        if config.mode is not CircuitMode.DUAL_PHASE and len(circuit_legs) == 1:
            leg = next(iter(circuit_legs))
            leg_voltage = getattr(mains_sample, f"leg_{leg}_voltage", None)
            if leg_voltage is not None:
                shared_voltage = leg_voltage
        return replace(
            sample,
            voltage=sample.voltage if sample.voltage is not None else shared_voltage,
            leg_a_voltage=(
                sample.leg_a_voltage
                if sample.leg_a_voltage is not None
                else (
                    mains_sample.leg_a_voltage
                    if mains_sample.leg_a_voltage is not None
                    else mains_sample.voltage
                )
            ),
            leg_b_voltage=(
                sample.leg_b_voltage
                if sample.leg_b_voltage is not None
                else (
                    mains_sample.leg_b_voltage
                    if mains_sample.leg_b_voltage is not None
                    else mains_sample.voltage
                )
            ),
        )

    def _mains_context_sample(
        self: Self,
        now: datetime,
    ) -> NormalizedCircuitSample | None:
        if self._mains_context_config is None:
            return None
        return self.source_samples.sample_for_config(self._mains_context_config, now)

    async def _sync_data_quality_repairs(
        self: Self,
        circuit_id: str,
        sample_or_problem: NormalizedCircuitSample | str,
    ) -> None:
        await self.setup_health.async_sync_data_quality_repairs(
            circuit_id,
            sample_or_problem,
        )

    async def _sync_setup_health_repairs(self: Self, circuit_id: str) -> None:
        await self.setup_health.async_sync_setup_health_repairs(circuit_id)

    def _nilm_signature_payloads(
        self: Self,
        circuit_id: str,
        signatures: Iterable[Any],
    ) -> list[dict[str, Any]]:
        return self.nilm_controller.signature_payloads(circuit_id, signatures)

    def apply_nilm_alert_feedback(
        self: Self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        self.alert_policies.apply_nilm_alert_feedback(alert, action, now)

    def _mark_store_dirty(self: Self) -> None:
        self.store_persistence.mark_dirty()

    @property
    def _store_dirty(self: Self) -> bool:
        return self.store_persistence.dirty

    @_store_dirty.setter
    def _store_dirty(self: Self, value: bool) -> None:
        self.store_persistence.dirty = bool(value)

    @property
    def _active_repair_issues(self: Self) -> set[tuple[str, str]]:
        return self.setup_health.active_repair_issues

    async def async_apply_feature_result(
        self: Self,
        result: FeatureResult,
    ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
        """Apply processor output to coordinator-owned state and side effects."""
        self.state_reducer.apply_updates(self.state, result.state_updates)

        def allows(alert: AlertEvidence) -> bool:
            config = next(
                (
                    config
                    for config in self.circuit_configs
                    if config.circuit_id == alert.circuit_id
                ),
                None,
            )
            is_mixed = config is not None and (
                config.mode is CircuitMode.MIXED
                or config.appliance_profile is ApplianceProfile.MIXED
            )
            return not is_mixed or mixed_circuit_allows_alert(alert.feature)

        result = replace(
            result,
            state_updates=[],
            alerts=[
                alert
                for alert in result.alerts
                if allows(alert)
                and self.notification_controller.learning_allows_alert(alert)
            ],
            preserved_alerts=[
                alert
                for alert in result.preserved_alerts
                if allows(alert)
                and self.notification_controller.learning_allows_alert(alert)
            ],
            notifications=[
                alert
                for alert in result.notifications
                if allows(alert)
                and self.notification_controller.learning_allows_alert(alert)
            ],
        )
        applied = self.state_reducer.apply_feature_result(
            self.state,
            self.store_data,
            result,
            alert_feedback=self.evidence_actions.alert_with_feedback,
        )
        for alert in applied.notifications:
            await self._notify_alert(alert)
        if applied.store_dirty:
            self._mark_store_dirty()
        return applied.events, applied.active_alerts

    def refresh_cost_estimates(self: Self) -> None:
        """Synchronize rate-derived cost views without recording a sample."""
        self.state_reducer.apply_updates(
            self.state,
            self._cost_processor.estimate_state_updates(
                self.circuit_configs,
                self.state,
                self.store_data.cost_by_circuit,
            ),
        )

    async def _async_save_store(
        self: Self,
        now: datetime,
        *,
        force: bool = True,
    ) -> None:
        await self.store_persistence.async_save_if_dirty(now, force=force)

    def _apply_retention(self: Self, now: datetime) -> None:
        self.store_persistence.apply_retention(now)

    def _retention_mode_for_circuit(self: Self, circuit_id: str) -> RetentionMode:
        for config in self.circuit_configs:
            if config.circuit_id == circuit_id:
                return config.retention_mode
        return self._entry_retention_mode

    def _source_states_for(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, SourceState]:
        return self.source_samples.source_states_for(config, now)

    def _registered_demo_source_entity_ids(self: Self) -> dict[str, str]:
        return self.source_samples.registered_demo_source_entity_ids()


    def _clear_nilm_topology_state(self: Self, circuit_id: str) -> None:
        self.processor_runtime.clear_nilm_topology_state(circuit_id)

    def _learning_mature(self: Self, config: CircuitConfig, now: datetime) -> bool:
        return self.processor_runtime.learning_mature(config, now)

    async def _notify_alert(self: Self, alert: AlertEvidence) -> None:
        await self.notification_controller.async_notify_alert(alert)

    async def _notify_nilm_virtual_appliances(
        self: Self,
        now: datetime,
    ) -> list[AlertEvidence]:
        return await self.notification_controller.async_notify_nilm_virtual_appliances(
            now
        )


def _items_by_circuit(items: Iterable[Any]) -> dict[str, list[Any]]:
    grouped: defaultdict[str, list[Any]] = defaultdict(list)
    for item in items:
        grouped[item.circuit_id].append(item)
    return dict(grouped)
