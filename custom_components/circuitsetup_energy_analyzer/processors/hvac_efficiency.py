from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from ..alerting import Observation
from ..const import (
    CONF_ADVANCED_SETTINGS,
    CONF_BLOWER_REPRESENTS_GAS_HEAT,
    CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
    DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
)
from ..context_sources import (
    thermostat_entities_for_settings,
    thermostat_mappings_for_settings,
)
from ..contextual_baseline import season_for_datetime
from ..hvac_efficiency import (
    HvacEfficiencyEvaluation,
    HvacResponseEpisode,
    ThermostatObservation,
    advance_episode,
    compact_completed_core_days,
    episode_from_dict,
    episode_to_dict,
    evaluate_efficiency,
    observation_response_mode,
    response_comparison_token,
)
from ..local_time import local_date
from ..models import AlertEvidence, ApplianceProfile
from ..operating_detection import operating_state_is_running
from ..profiles import supports_direct_appliance_analysis
from .base import FeatureResult, ProcessingContext, StateUpdate

_COOLING_DRIVER_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
    }
)
_HEATING_DRIVER_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)
_CORRELATION_HISTORY_LIMIT = 256
_SETUP_ISSUE_LIMIT = 8
HVAC_EFFICIENCY_FEATURE = "hvac_thermostat_efficiency"
_INITIAL_BASELINE_ERA = "initial"
_CONTEXT_SWITCH_DAYS = 3

type HvacAlertPolicyProvider = Callable[[str], Any]
type RetentionDaysProvider = Callable[[str], int]


class HvacEfficiencyProcessor:
    """Track thermostat response without recorder or external I/O."""

    def __init__(
        self,
        *,
        alert_policy_for_circuit: HvacAlertPolicyProvider | None = None,
        retention_days_for_circuit: RetentionDaysProvider | None = None,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._retention_days_for_circuit = retention_days_for_circuit or (
            lambda _circuit_id: 180
        )

    def process(
        self,
        samples: list[tuple[Any, Any]],
        context: ProcessingContext,
    ) -> FeatureResult:
        configs = {
            config.circuit_id: config
            for config, _sample in samples
            if supports_direct_appliance_analysis(config)
            and config.appliance_profile
            in _COOLING_DRIVER_PROFILES
            | _HEATING_DRIVER_PROFILES
            | {ApplianceProfile.HVAC_BLOWER}
        }
        if not configs:
            return FeatureResult()

        advanced_by_circuit = _advanced_settings(context)
        result = FeatureResult()
        _collect_hvac_correlation(result, context, configs)
        linked_by_thermostat: dict[str, list[Any]] = {}
        for config in configs.values():
            settings = advanced_by_circuit.get(config.circuit_id, {})
            mappings = thermostat_mappings_for_settings(
                context.entry_data,
                context.options,
                settings,
            )
            result.state_updates.append(
                StateUpdate(
                    path=(
                        "hvac_thermostat_setup_issues_by_circuit",
                        config.circuit_id,
                    ),
                    value=_thermostat_setup_issues(
                        context,
                        config,
                        mappings,
                    ),
                )
            )
            for thermostat_id in mappings:
                linked_by_thermostat.setdefault(thermostat_id, []).append(config)

        processed_streams: set[str] = set()
        circuit_streams: dict[str, dict[str, dict[str, Any]]] = {}
        for thermostat_id, linked_configs in linked_by_thermostat.items():
            observation = _first_observation(
                context,
                linked_configs,
                thermostat_id,
            )
            if observation is None:
                continue
            mode = _current_response_mode(
                context,
                linked_configs,
                thermostat_id,
            ) or observation_response_mode(observation)
            active_ids = {
                config.circuit_id
                for config in linked_configs
                if _circuit_running(context, config.circuit_id)
            }
            if mode is None:
                _store_unresolved_active_call_markers(
                    result,
                    context,
                    linked_configs,
                    thermostat_id,
                    observation,
                    active_ids,
                    advanced_by_circuit,
                )
                continue
            (
                direct_profiles,
                drivers,
                gas_blower_ids,
                supporting_blower_ids,
            ) = _active_response_equipment(
                context,
                linked_configs,
                thermostat_id,
                mode,
                active_ids,
                advanced_by_circuit,
            )
            participant_signature = tuple(sorted(drivers))

            for config in linked_configs:
                is_gas_blower = config.circuit_id in gas_blower_ids
                eligible = (
                    config.appliance_profile in direct_profiles or is_gas_blower
                )
                if not eligible or mode is None:
                    continue
                stream_id = (
                    f"{config.circuit_id}|{thermostat_id}|{mode}"
                )
                processed_streams.add(stream_id)
                current = _current_episode(context, stream_id)
                active_delta = _active_minutes_delta(current, context.now)
                current_observation = _observation_for(
                    context,
                    config.circuit_id,
                    thermostat_id,
                ) or observation
                next_episode, finalized = advance_episode(
                    current,
                    current_observation,
                    now=context.now,
                    circuit_id=config.circuit_id,
                    appliance_profile=config.appliance_profile.value,
                    driver_active=config.circuit_id in drivers,
                    active_minutes_delta=active_delta,
                    participant_signature=participant_signature,
                    supporting_blower_ids=supporting_blower_ids,
                    environmental_context=_environmental_context(
                        context,
                        config.circuit_id,
                    ),
                )
                if next_episode is not None:
                    payload = episode_to_dict(
                        next_episode,
                        allow_incomplete=True,
                    )
                    payload["attribution"] = (
                        "gas_furnace_proxy"
                        if is_gas_blower
                        else (
                            "assisted_system"
                            if len(participant_signature) > 1
                            else "direct"
                        )
                    )
                    result.state_updates.append(
                        StateUpdate(
                            path=(
                                "hvac_current_episode_by_stream",
                                stream_id,
                            ),
                            value=payload,
                        )
                    )
                    circuit_streams.setdefault(config.circuit_id, {})[
                        stream_id
                    ] = payload
                elif current is not None:
                    result.state_updates.append(
                        StateUpdate(
                            path=(
                                "hvac_current_episode_by_stream",
                                stream_id,
                            ),
                            value={},
                        )
                    )
                if finalized is not None:
                    _store_finalized_episode(result, context, finalized)

        for stream_id, raw in getattr(
            context.state,
            "hvac_current_episode_by_stream",
            {},
        ).items():
            if (
                raw
                and stream_id not in processed_streams
                and stream_id.split("|", 1)[0] in configs
            ):
                marker = dict(raw)
                marker.update(
                    ended_at=context.now.isoformat(),
                    complete=False,
                    excluded_from_baseline=True,
                    inactive_since=None,
                    baseline_era=(
                        context.store_data.hvac_baseline_era_by_stream.get(
                            stream_id,
                            _INITIAL_BASELINE_ERA,
                        )
                    ),
                )
                if episode_from_dict(marker, allow_incomplete=True) is not None:
                    context.store_data.hvac_response_history_by_stream.setdefault(
                        stream_id,
                        [],
                    ).append(marker)
                    result.store_dirty = True
                result.state_updates.append(
                    StateUpdate(
                        path=("hvac_current_episode_by_stream", stream_id),
                        value={},
                    )
                )

        date_history_snapshot = {
            stream_id: tuple(history)
            for stream_id, history in (
                context.store_data.hvac_response_history_by_stream.items()
            )
        }
        for circuit_id in configs:
            retention_days = self._retention_days_for_circuit(circuit_id)
            if _compact_circuit_response_history(
                context,
                circuit_id,
                retention_days=retention_days,
                date_history_by_stream=date_history_snapshot,
            ):
                result.store_dirty = True
            payload = _circuit_efficiency_payload(
                context,
                configs[circuit_id],
                circuit_streams.get(circuit_id, {}),
                advanced_by_circuit.get(circuit_id, {}),
                retention_days=retention_days,
            )
            result.state_updates.append(
                StateUpdate(
                    path=("hvac_efficiency_by_circuit", circuit_id),
                    value=payload,
                )
            )
            _append_evaluation_alerts(
                result,
                context,
                configs[circuit_id],
                payload,
                self._alert_policy_for_circuit,
            )
        return result


def _active_response_equipment(
    context: ProcessingContext,
    linked_configs: list[Any],
    thermostat_id: str,
    mode: str,
    active_ids: set[str],
    advanced_by_circuit: Mapping[str, Mapping[str, Any]],
) -> tuple[frozenset[ApplianceProfile], set[str], set[str], tuple[str, ...]]:
    direct_profiles = (
        _COOLING_DRIVER_PROFILES if mode == "cooling" else _HEATING_DRIVER_PROFILES
    )
    drivers = {
        config.circuit_id
        for config in linked_configs
        if config.appliance_profile in direct_profiles
        and config.circuit_id in active_ids
    }
    gas_blower_ids: set[str] = set()
    if mode == "heating" and not drivers:
        gas_blower_ids = {
            config.circuit_id
            for config in linked_configs
            if config.appliance_profile is ApplianceProfile.HVAC_BLOWER
            and bool(
                advanced_by_circuit.get(config.circuit_id, {}).get(
                    CONF_BLOWER_REPRESENTS_GAS_HEAT,
                    False,
                )
            )
            and (
                config.circuit_id in active_ids
                or _current_episode(
                    context,
                    f"{config.circuit_id}|{thermostat_id}|heating",
                )
                is not None
            )
        }
        drivers.update(gas_blower_ids & active_ids)
    supporting_blower_ids = tuple(
        sorted(
            config.circuit_id
            for config in linked_configs
            if config.appliance_profile is ApplianceProfile.HVAC_BLOWER
            and config.circuit_id in active_ids
            and config.circuit_id not in gas_blower_ids
        )
    )
    return direct_profiles, drivers, gas_blower_ids, supporting_blower_ids


def _store_unresolved_active_call_markers(
    result: FeatureResult,
    context: ProcessingContext,
    linked_configs: list[Any],
    thermostat_id: str,
    observation: ThermostatObservation,
    active_ids: set[str],
    advanced_by_circuit: Mapping[str, Mapping[str, Any]],
) -> None:
    if observation.action or "hvac_action" in observation.available_capabilities:
        return
    for config in linked_configs:
        if config.circuit_id not in active_ids:
            continue
        if config.appliance_profile in _COOLING_DRIVER_PROFILES:
            mode = "cooling"
        elif config.appliance_profile in _HEATING_DRIVER_PROFILES or (
            config.appliance_profile is ApplianceProfile.HVAC_BLOWER
            and bool(
                advanced_by_circuit.get(config.circuit_id, {}).get(
                    CONF_BLOWER_REPRESENTS_GAS_HEAT,
                    False,
                )
            )
        ):
            mode = "heating"
        else:
            continue
        direct_profiles, drivers, gas_blower_ids, supporting_blower_ids = (
            _active_response_equipment(
                context,
                linked_configs,
                thermostat_id,
                mode,
                active_ids,
                advanced_by_circuit,
            )
        )
        if (
            config.appliance_profile not in direct_profiles
            and config.circuit_id not in gas_blower_ids
        ):
            continue
        current_observation = _observation_for(
            context,
            config.circuit_id,
            thermostat_id,
        ) or observation
        _current, marker = advance_episode(
            None,
            replace(
                current_observation,
                mode="cool" if mode == "cooling" else "heat",
                action=None,
            ),
            now=context.now,
            circuit_id=config.circuit_id,
            appliance_profile=config.appliance_profile.value,
            driver_active=True,
            active_minutes_delta=0.0,
            participant_signature=tuple(sorted(drivers)),
            supporting_blower_ids=supporting_blower_ids,
            environmental_context=_environmental_context(
                context,
                config.circuit_id,
            ),
        )
        if marker is not None:
            _store_finalized_episode(result, context, marker)


def _store_finalized_episode(
    result: FeatureResult,
    context: ProcessingContext,
    finalized: HvacResponseEpisode,
) -> None:
    stream_id = finalized.stream_id
    history = context.store_data.hvac_response_history_by_stream.setdefault(
        stream_id,
        [],
    )
    stored_episode = episode_to_dict(finalized, allow_incomplete=True)
    stored_episode["baseline_era"] = (
        context.store_data.hvac_baseline_era_by_stream.get(
            stream_id,
            _INITIAL_BASELINE_ERA,
        )
    )
    instant_excluded = (
        finalized.excluded_from_baseline
        and not finalized.complete
        and finalized.ended_at == finalized.started_at
    )
    already_marked = instant_excluded and any(
        episode.excluded_from_baseline
        and local_date(episode.started_at, context.time_zone)
        == local_date(finalized.started_at, context.time_zone)
        for raw in history
        if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA))
        == stored_episode["baseline_era"]
        if (
            episode := episode_from_dict(
                raw,
                allow_incomplete=True,
            )
        )
        is not None
        if response_comparison_token(episode) == response_comparison_token(finalized)
    )
    if not already_marked:
        history.append(stored_episode)
        result.store_dirty = True


def _collect_hvac_correlation(
    result: FeatureResult,
    context: ProcessingContext,
    configs: Mapping[str, Any],
) -> None:
    thermostat_ids = thermostat_entities_for_settings(
        context.entry_data,
        context.options,
    )
    if not thermostat_ids:
        return
    active_by_pair = getattr(
        context.state,
        "hvac_correlation_active_by_pair",
        {},
    )
    for config in configs.values():
        for thermostat_id in thermostat_ids:
            observation = context.thermostat_observations.get(thermostat_id)
            if observation is None:
                continue
            pair_id = f"{config.circuit_id}|{thermostat_id}"
            raw_current = active_by_pair.get(pair_id, {})
            current = (
                dict(raw_current) if isinstance(raw_current, Mapping) else {}
            )
            mode = str(observation.action or "").lower()
            if mode not in {"heating", "cooling"}:
                if current:
                    current = _advance_hvac_correlation(
                        context,
                        configs,
                        config,
                        observation,
                        str(current.get("mode") or ""),
                        current,
                    )
                    _finalize_hvac_correlation(
                        result,
                        context,
                        config,
                        current,
                    )
                    result.state_updates.append(
                        StateUpdate(
                            path=(
                                "hvac_correlation_active_by_pair",
                                pair_id,
                            ),
                            value={},
                        )
                    )
                continue
            if current and current.get("mode") != mode:
                current = _advance_hvac_correlation(
                    context,
                    configs,
                    config,
                    observation,
                    str(current.get("mode") or ""),
                    current,
                )
                _finalize_hvac_correlation(
                    result,
                    context,
                    config,
                    current,
                )
                current = {}
            result.state_updates.append(
                StateUpdate(
                    path=("hvac_correlation_active_by_pair", pair_id),
                    value=_advance_hvac_correlation(
                        context,
                        configs,
                        config,
                        observation,
                        mode,
                        current,
                    ),
                )
            )


def _advance_hvac_correlation(
    context: ProcessingContext,
    configs: Mapping[str, Any],
    config: Any,
    observation: ThermostatObservation,
    mode: str,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = _correlation_temperature_candidates(
        context,
        observation.thermostat_entity_id,
    )
    if not current:
        environmental = _environmental_context(context, config.circuit_id)
        return {
            "circuit_id": config.circuit_id,
            "thermostat_entity_id": observation.thermostat_entity_id,
            "mode": mode,
            "started_at": context.now.isoformat(),
            "observed_at": context.now.isoformat(),
            "active_minutes": 0.0,
            "electrical_driver_minutes": 0.0,
            "circuit_running": _circuit_running(context, config.circuit_id),
            "electrical_driver_running": _electrical_driver_running(
                context,
                configs,
                mode,
            ),
            "climate_has_current_temperature": (
                "current_temperature" in observation.available_capabilities
            ),
            "candidate_start_temperatures": candidates,
            "candidate_latest_temperatures": candidates,
            "weather_mode": environmental.get("weather_mode"),
            "temperature_bin": environmental.get("temperature_bin"),
        }

    updated = dict(current)
    observed_at = _correlation_datetime(current.get("observed_at"))
    delta = (
        max(0.0, (context.now - observed_at).total_seconds() / 60.0)
        if observed_at is not None
        else 0.0
    )
    if bool(current.get("circuit_running")):
        updated["active_minutes"] = float(
            current.get("active_minutes", 0.0)
        ) + delta
    if bool(current.get("electrical_driver_running")):
        updated["electrical_driver_minutes"] = float(
            current.get("electrical_driver_minutes", 0.0)
        ) + delta
    updated["circuit_running"] = _circuit_running(
        context,
        config.circuit_id,
    )
    updated["electrical_driver_running"] = _electrical_driver_running(
        context,
        configs,
        mode,
    )
    updated["candidate_latest_temperatures"] = {
        **dict(current.get("candidate_latest_temperatures", {})),
        **candidates,
    }
    updated["observed_at"] = context.now.isoformat()
    return updated


def _finalize_hvac_correlation(
    result: FeatureResult,
    context: ProcessingContext,
    config: Any,
    current: Mapping[str, Any],
) -> None:
    started_at = _correlation_datetime(current.get("started_at"))
    if started_at is None:
        return
    elapsed = (context.now - started_at).total_seconds() / 60.0
    if elapsed <= 0.0:
        return
    mode = str(current.get("mode") or "")
    start_temperatures = dict(
        current.get("candidate_start_temperatures", {})
    )
    latest_temperatures = dict(
        current.get("candidate_latest_temperatures", {})
    )
    candidate_id = None
    candidate_progress = 0.0
    for entity_id, start in start_temperatures.items():
        latest = latest_temperatures.get(entity_id)
        if not _finite_correlation_number(start) or not _finite_correlation_number(
            latest
        ):
            continue
        progress = (
            float(latest) - float(start)
            if mode == "heating"
            else float(start) - float(latest)
        )
        if candidate_id is None or progress > candidate_progress:
            candidate_id = str(entity_id)
            candidate_progress = progress
    active_minutes = max(0.0, float(current.get("active_minutes", 0.0)))
    electrical_minutes = max(
        0.0,
        float(current.get("electrical_driver_minutes", 0.0)),
    )
    history = (
        context.store_data.hvac_correlation_history_by_circuit.setdefault(
            config.circuit_id,
            [],
        )
    )
    history.append(
        {
            "observed_at": context.now.isoformat(),
            "appliance_profile": config.appliance_profile.value,
            "thermostat_entity_id": str(
                current.get("thermostat_entity_id") or ""
            ),
            "thermostat_name": str(
                current.get("thermostat_entity_id") or ""
            ).replace("climate.", "").replace("_", " ").title(),
            "temperature_entity_id": candidate_id,
            "mode": mode,
            "driver_mode": (
                mode
                if _profile_drives_mode(config.appliance_profile, mode)
                else None
            ),
            "overlap_ratio": min(1.0, active_minutes / elapsed),
            "candidate_moved_toward_target": candidate_progress > 0.0,
            "climate_has_current_temperature": bool(
                current.get("climate_has_current_temperature")
            ),
            "electrical_driver_present": (
                config.appliance_profile is not ApplianceProfile.HVAC_BLOWER
                or electrical_minutes / elapsed >= 0.8
            ),
            "weather_mode": current.get("weather_mode"),
            "temperature_bin": current.get("temperature_bin"),
        }
    )
    del history[:-_CORRELATION_HISTORY_LIMIT]
    result.store_dirty = True


def _correlation_temperature_candidates(
    context: ProcessingContext,
    thermostat_id: str,
) -> dict[str, float]:
    candidates: dict[str, float] = {}
    for observation in context.thermostat_observations.values():
        entity_id = observation.temperature_entity_id
        value = observation.actual_temperature_f
        if (
            observation.thermostat_entity_id == thermostat_id
            and entity_id
            and _finite_correlation_number(value)
        ):
            candidates[entity_id] = float(value)
    return candidates


def _profile_drives_mode(profile: ApplianceProfile, mode: str) -> bool:
    profiles = (
        _COOLING_DRIVER_PROFILES
        if mode == "cooling"
        else _HEATING_DRIVER_PROFILES
    )
    return profile in profiles or profile is ApplianceProfile.HVAC_BLOWER


def _electrical_driver_running(
    context: ProcessingContext,
    configs: Mapping[str, Any],
    mode: str,
) -> bool:
    profiles = (
        _COOLING_DRIVER_PROFILES
        if mode == "cooling"
        else _HEATING_DRIVER_PROFILES
    )
    return any(
        config.appliance_profile in profiles
        and _circuit_running(context, config.circuit_id)
        for config in configs.values()
    )


def _correlation_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _finite_correlation_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _thermostat_setup_issues(
    context: ProcessingContext,
    config: Any,
    mappings: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    configured = thermostat_entities_for_settings(
        context.entry_data,
        context.options,
    )
    if not configured and not mappings:
        return []
    if len(configured) > 1 and not mappings:
        return [
            _thermostat_setup_issue(
                config,
                (
                    f"{config.name} has multiple configured thermostats; choose a "
                    "thermostat in Advanced Settings before response learning can "
                    "start."
                ),
                configured,
            )
        ]

    issues: list[dict[str, Any]] = []
    for thermostat_id, temperature_id in mappings.items():
        observation = _observation_for(
            context,
            config.circuit_id,
            thermostat_id,
        )
        sources = tuple(
            source
            for source in (thermostat_id, temperature_id)
            if source
        )
        if observation is None or observation.mode is None:
            reason = (
                f"{config.name} cannot use {thermostat_id} because the selected "
                "thermostat is missing or unavailable."
            )
        elif observation.actual_temperature_f is None:
            reason = (
                f"{config.name} cannot use {thermostat_id} because no current "
                "temperature is available."
            )
        elif observation.target_temperature_f is None and (
            str(observation.action or "").lower() in {"heating", "cooling"}
            or not {
                "temperature",
                "target_temp_low",
                "target_temp_high",
            }.intersection(observation.available_capabilities)
        ):
            reason = (
                f"{config.name} cannot use {thermostat_id} because no active "
                "temperature setpoint is available."
            )
        elif (
            observation.temperature_entity_id
            and "temperature_override"
            not in observation.available_capabilities
        ):
            reason = (
                f"{config.name} cannot use the selected temperature override "
                f"{observation.temperature_entity_id}."
            )
        else:
            continue
        issues.append(_thermostat_setup_issue(config, reason, sources))
    return issues[:_SETUP_ISSUE_LIMIT]


def _thermostat_setup_issue(
    config: Any,
    reason: str,
    source_entities: Any,
) -> dict[str, Any]:
    return {
        "issue_kind": "missing_required_sensor",
        "circuit_id": config.circuit_id,
        "circuit_name": config.name,
        "reason": reason,
        "source_entities": list(dict.fromkeys(source_entities)),
    }


def _advanced_settings(
    context: ProcessingContext,
) -> dict[str, Mapping[str, Any]]:
    raw = context.options.get(
        CONF_ADVANCED_SETTINGS,
        context.entry_data.get(CONF_ADVANCED_SETTINGS, {}),
    )
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(circuit_id): settings
        for circuit_id, settings in raw.items()
        if isinstance(settings, Mapping)
    }


def _observation_for(
    context: ProcessingContext,
    circuit_id: str,
    thermostat_id: str,
) -> ThermostatObservation | None:
    return context.thermostat_observations.get(
        f"{circuit_id}|{thermostat_id}"
    ) or context.thermostat_observations.get(thermostat_id)


def _first_observation(
    context: ProcessingContext,
    configs: list[Any],
    thermostat_id: str,
) -> ThermostatObservation | None:
    return next(
        (
            observation
            for config in configs
            if (
                observation := _observation_for(
                    context,
                    config.circuit_id,
                    thermostat_id,
                )
            )
            is not None
        ),
        None,
    )


def _current_response_mode(
    context: ProcessingContext,
    configs: list[Any],
    thermostat_id: str,
) -> str | None:
    modes = {
        episode.mode
        for config in configs
        if (
            episode := _current_episode(
                context,
                f"{config.circuit_id}|{thermostat_id}|heating",
            )
        )
        is not None
    } | {
        episode.mode
        for config in configs
        if (
            episode := _current_episode(
                context,
                f"{config.circuit_id}|{thermostat_id}|cooling",
            )
        )
        is not None
    }
    return next(iter(modes)) if len(modes) == 1 else None


def _circuit_running(context: ProcessingContext, circuit_id: str) -> bool:
    snapshot = context.state.operating_state_snapshot_by_circuit.get(circuit_id)
    return operating_state_is_running(snapshot) is True


def _current_episode(
    context: ProcessingContext,
    stream_id: str,
) -> HvacResponseEpisode | None:
    raw = context.state.hvac_current_episode_by_stream.get(stream_id)
    return (
        episode_from_dict(raw, allow_incomplete=True)
        if isinstance(raw, Mapping)
        else None
    )


def _active_minutes_delta(
    current: HvacResponseEpisode | None,
    now: Any,
) -> float:
    if current is None:
        return 0.0
    elapsed = max(0.0, (now - current.started_at).total_seconds() / 60.0)
    return max(0.0, elapsed - current.elapsed_minutes)


def _environmental_context(
    context: ProcessingContext,
    circuit_id: str,
) -> dict[str, Any]:
    raw = context.state.weather_context_by_circuit.get(circuit_id, {})
    if not isinstance(raw, Mapping):
        raw = {}
    return {
        "outdoor_temperature_f": raw.get("temperature_f"),
        "temperature_bin": raw.get("temperature_bin"),
        "weather_mode": raw.get("mode"),
        "season": season_for_datetime(
            context.now,
            time_zone=context.time_zone,
        ),
    }


def _compact_circuit_response_history(
    context: ProcessingContext,
    circuit_id: str,
    *,
    retention_days: int,
    date_history_by_stream: Mapping[str, Any] | None = None,
) -> bool:
    history_by_stream = context.store_data.hvac_response_history_by_stream
    date_histories = date_history_by_stream or history_by_stream
    decoded_by_stream: dict[
        str,
        list[tuple[Mapping[str, Any], HvacResponseEpisode]],
    ] = {}
    dates_by_mode: dict[str, set[Any]] = {"heating": set(), "cooling": set()}
    target_thermostats = {
        parts[1]
        for stream_id in date_histories
        if len(parts := stream_id.split("|")) == 3 and parts[0] == circuit_id
    }
    for stream_id, raw_history in history_by_stream.items():
        parts = stream_id.split("|")
        if (
            len(parts) != 3
            or parts[0] != circuit_id
            or parts[-1] not in dates_by_mode
        ):
            continue
        decoded = [
            (raw, episode)
            for raw in raw_history
            if (
                episode := episode_from_dict(raw, allow_incomplete=True)
            ) is not None
        ]
        decoded_by_stream[stream_id] = decoded

    for stream_id, raw_history in date_histories.items():
        parts = stream_id.split("|")
        if (
            len(parts) != 3
            or parts[1] not in target_thermostats
            or parts[-1] not in dates_by_mode
        ):
            continue
        for raw in raw_history:
            episode = episode_from_dict(raw, allow_incomplete=True)
            if episode is None:
                continue
            started = local_date(episode.started_at, context.time_zone)
            ended = local_date(
                episode.ended_at or episode.started_at,
                context.time_zone,
            )
            dates_by_mode[parts[-1]].update(
                started + timedelta(days=offset)
                for offset in range(max(0, (ended - started).days) + 1)
            )

    changed = False
    current_date = local_date(context.now, context.time_zone)
    active_dates: set[Any] = set()
    for stream_id, raw in getattr(
        context.state,
        "hvac_current_episode_by_stream",
        {},
    ).items():
        parts = stream_id.split("|")
        if (
            len(parts) != 3
            or parts[1] not in target_thermostats
            or parts[-1] not in dates_by_mode
            or not isinstance(raw, Mapping)
            or (episode := episode_from_dict(raw, allow_incomplete=True)) is None
        ):
            continue
        started = local_date(episode.started_at, context.time_zone)
        touched = {
            started + timedelta(days=offset)
            for offset in range(max(0, (current_date - started).days) + 1)
        }
        dates_by_mode[parts[-1]].update(touched)
        active_dates.update(touched)
    for stream_id, decoded in decoded_by_stream.items():
        mode = stream_id.rsplit("|", 1)[-1]
        opposing_mode = "heating" if mode == "cooling" else "cooling"
        current_era = context.store_data.hvac_baseline_era_by_stream.get(
            stream_id,
            _INITIAL_BASELINE_ERA,
        )
        prior_era_disqualified_dates: set[Any] = set()
        for raw, episode in decoded:
            if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA)) == current_era:
                continue
            started = local_date(episode.started_at, context.time_zone)
            ended = local_date(
                episode.ended_at or episode.started_at,
                context.time_zone,
            )
            prior_era_disqualified_dates.update(
                started + timedelta(days=offset)
                for offset in range(max(0, (ended - started).days) + 1)
            )
        pending_old_era = [
            (raw, episode)
            for raw, episode in decoded
            if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA)) != current_era
            and max(
                local_date(episode.started_at, context.time_zone),
                local_date(
                    episode.ended_at or episode.started_at,
                    context.time_zone,
                ),
            )
            >= current_date
        ]
        episodes = [
            episode
            for raw, episode in decoded
            if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA)) == current_era
            and (
                local_date(episode.started_at, context.time_zone) >= current_date
                or local_date(episode.started_at, context.time_zone)
                not in dates_by_mode[opposing_mode]
            )
        ]
        contexts: dict[str, list[HvacResponseEpisode]] = {}
        for episode in episodes:
            if episode.complete and not episode.excluded_from_baseline:
                contexts.setdefault(response_comparison_token(episode), []).append(
                    episode
                )
        context_by_stream = context.store_data.hvac_response_context_by_stream
        raw_context = context_by_stream.get(stream_id, {})
        observed = str(raw_context.get("observed") or "")
        observed_at = str(raw_context.get("observed_at") or "")
        try:
            previous_observed_at = datetime.fromisoformat(observed_at)
        except ValueError:
            previous_observed_at = None
        latest_observed = max(
            episodes,
            key=lambda episode: episode.ended_at or episode.started_at,
            default=None,
        )
        if latest_observed is not None and (
            previous_observed_at is None
            or previous_observed_at.tzinfo is None
            or (latest_observed.ended_at or latest_observed.started_at)
            > previous_observed_at
        ):
            observed = response_comparison_token(latest_observed)
            observed_at = (
                latest_observed.ended_at or latest_observed.started_at
            ).isoformat()
        if contexts:
            selected = str(raw_context.get("selected") or "")
            known = {
                str(token)
                for token in raw_context.get("known", ())
                if str(token)
            }
            new_contexts = set(contexts) - known
            latest_context = max(
                contexts,
                key=lambda token: max(
                    episode.ended_at or episode.started_at
                    for episode in contexts[token]
                ),
            )
            candidate = str(raw_context.get("candidate") or "")
            candidate_dates = {
                str(day)
                for day in raw_context.get("candidate_dates", ())
                if str(day)
            }
            if new_contexts:
                selected = max(
                    new_contexts,
                    key=lambda token: max(
                        episode.ended_at or episode.started_at
                        for episode in contexts[token]
                    ),
                )
                candidate = ""
                candidate_dates.clear()
            elif selected not in contexts:
                selected = latest_context
                candidate = ""
                candidate_dates.clear()
            elif latest_context != selected:
                if candidate != latest_context:
                    candidate = latest_context
                    candidate_dates.clear()
                candidate_dates.update(
                    local_date(episode.started_at, context.time_zone).isoformat()
                    for episode in contexts[latest_context]
                )
                if len(candidate_dates) >= _CONTEXT_SWITCH_DAYS:
                    selected = latest_context
                    candidate = ""
                    candidate_dates.clear()
            elif candidate and max(
                local_date(episode.started_at, context.time_zone).isoformat()
                for episode in contexts[selected]
            ) > max(candidate_dates, default=""):
                candidate = ""
                candidate_dates.clear()
            updated_context = {
                "selected": selected,
                "known": sorted(known | set(contexts)),
            }
            if observed:
                updated_context["observed"] = observed
                updated_context["observed_at"] = observed_at
            if candidate:
                updated_context.update(
                    candidate=candidate,
                    candidate_dates=sorted(candidate_dates),
                )
            if updated_context != raw_context:
                context_by_stream[stream_id] = updated_context
                changed = True
            episodes = [
                (
                    episode
                    if response_comparison_token(episode) == selected
                    else replace(
                        episode,
                        complete=False,
                        excluded_from_baseline=True,
                    )
                )
                for episode in episodes
            ]
        elif observed and (
            raw_context.get("observed") != observed
            or raw_context.get("observed_at") != observed_at
        ):
            context_by_stream[stream_id] = {
                **raw_context,
                "observed": observed,
                "observed_at": observed_at,
            }
            changed = True
        compacted = pending_old_era
        for episode in compact_completed_core_days(
            episodes,
            time_zone=context.time_zone,
            current_date=current_date,
            retention_days=retention_days,
            disqualified_dates=prior_era_disqualified_dates
            | {day for day in active_dates if day < current_date},
        ):
            raw = episode_to_dict(episode, allow_incomplete=True)
            raw["baseline_era"] = current_era
            compacted.append((raw, episode))
        retained = [
            raw
            for raw, _episode in sorted(
                compacted,
                key=lambda item: item[1].started_at,
            )
        ]
        if retained != history_by_stream[stream_id]:
            history_by_stream[stream_id] = retained
            changed = True
    return changed


def _circuit_efficiency_payload(
    context: ProcessingContext,
    config: Any,
    current_streams: Mapping[str, dict[str, Any]],
    settings: Mapping[str, Any],
    *,
    retention_days: int,
) -> dict[str, Any]:
    circuit_id = config.circuit_id
    threshold = _response_change_threshold(settings)
    evaluations: dict[str, dict[str, Any]] = {}
    history_by_stream = getattr(
        context.store_data,
        "hvac_response_history_by_stream",
        {},
    )
    thermostat_mappings = thermostat_mappings_for_settings(
        context.entry_data,
        context.options,
        settings,
    )
    episodes_by_stream: dict[str, list[HvacResponseEpisode]] = {}
    baseline_eras: dict[str, str] = {}
    for stream_id, raw_history in history_by_stream.items():
        stream_parts = stream_id.split("|")
        if (
            len(stream_parts) != 3
            or stream_parts[0] != circuit_id
            or stream_parts[1] not in thermostat_mappings
        ):
            continue
        mode = stream_parts[-1]
        if mode not in {"heating", "cooling"}:
            continue
        if config.appliance_profile is ApplianceProfile.HVAC_BLOWER and (
            mode == "cooling"
            or not bool(settings.get(CONF_BLOWER_REPRESENTS_GAS_HEAT, False))
        ):
            continue
        baseline_era = context.store_data.hvac_baseline_era_by_stream.get(
            stream_id,
            _INITIAL_BASELINE_ERA,
        )
        episodes = [
            episode
            for raw in raw_history
            if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA))
            == baseline_era
            if str(raw.get("appliance_profile") or "")
            == config.appliance_profile.value
            if (str(raw.get("temperature_entity_id") or "").strip() or None)
            == thermostat_mappings[stream_parts[1]]
            if (episode := episode_from_dict(raw)) is not None
        ]
        episodes_by_stream[stream_id] = episodes
        baseline_eras[stream_id] = baseline_era
    dates_by_mode: dict[str, set[Any]] = {"heating": set(), "cooling": set()}
    for stream_id, episodes in episodes_by_stream.items():
        dates_by_mode[stream_id.rsplit("|", 1)[-1]].update(
            local_date(episode.started_at, context.time_zone)
            for episode in episodes
        )
    for stream_id, episodes in episodes_by_stream.items():
        mode = stream_id.rsplit("|", 1)[-1]
        opposing_mode = "heating" if mode == "cooling" else "cooling"
        response_context = context.store_data.hvac_response_context_by_stream.get(
            stream_id,
            {},
        )
        observed_context = str(response_context.get("observed") or "")
        selected_context = str(response_context.get("selected") or "")
        fingerprint_context = observed_context or selected_context
        evaluation_episodes = (
            []
            if observed_context
            and selected_context
            and observed_context != selected_context
            else episodes
        )
        configured_temperature = thermostat_mappings[stream_id.split("|")[1]] or ""
        evaluations[stream_id] = {
            **_evaluation_to_dict(
                evaluate_efficiency(
                    evaluation_episodes,
                    threshold_pct=threshold,
                    time_zone=context.time_zone,
                    excluded_dates=dates_by_mode[opposing_mode],
                    current_date=local_date(context.now, context.time_zone),
                    retention_days=retention_days,
                )
            ),
            "baseline_era": baseline_eras[stream_id],
            "response_context_fingerprint": hashlib.sha256(
                (
                    f"{config.appliance_profile.value}\0{fingerprint_context}"
                    f"\0{configured_temperature}"
                ).encode()
            ).hexdigest(),
        }
    ready_scores = [
        float(evaluation["score"])
        for evaluation in evaluations.values()
        if evaluation.get("score") is not None
    ]
    findings = [
        evaluation.get("finding")
        for evaluation in evaluations.values()
        if evaluation.get("finding") in {"slower", "faster"}
    ]
    finding = "slower" if "slower" in findings else (
        "faster" if "faster" in findings else None
    )
    stream_statuses = {
        str(evaluation.get("status") or "learning")
        for evaluation in evaluations.values()
    }
    learning_status = next(
        (
            status
            for status in ("provisional", "no_weather_data", "no_data")
            if status in stream_statuses
        ),
        "tracking" if current_streams else "learning",
    )
    return {
        "status": (
            "ready"
            if ready_scores
            else learning_status
        ),
        "score": median(ready_scores) if ready_scores else None,
        "finding": finding,
        "threshold_pct": threshold,
        "current_streams": dict(current_streams),
        "streams": evaluations,
    }


def _response_change_threshold(settings: Mapping[str, Any]) -> float:
    try:
        value = float(
            settings.get(
                CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
                DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
    return (
        value
        if math.isfinite(value) and 5.0 <= value <= 100.0
        else DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
    )


def _append_evaluation_alerts(
    result: FeatureResult,
    context: ProcessingContext,
    config: Any,
    payload: Mapping[str, Any],
    policy_provider: HvacAlertPolicyProvider | None,
) -> None:
    if policy_provider is None:
        return
    threshold = float(payload["threshold_pct"])
    for stream_id, evaluation in payload["streams"].items():
        finding = evaluation.get("finding")
        if finding != "slower":
            active_alert = _matching_active_alert_for_stream(
                context,
                config.circuit_id,
                "hvac_response_slower",
                stream_id,
            )
            normal_streak = int(
                dict(evaluation.get("context", {})).get("normal_streak", 0)
            )
            evaluation_context = dict(evaluation.get("context", {}))
            selected_context = str(
                evaluation.get("response_context_fingerprint") or ""
            )
            alert_context = str(
                active_alert.features.get("response_context_fingerprint")
                if active_alert is not None
                else ""
            )
            context_changed = (
                bool(selected_context and alert_context)
                and selected_context != alert_context
            ) or any(
                key in evaluation_context
                and active_alert is not None
                and active_alert.features.get(key) != evaluation_context[key]
                for key in (
                    "appliance_profile",
                    "temperature_entity_id",
                    "participant_signature",
                    "supporting_blower_ids",
                )
            )
            if active_alert is not None and (
                not context_changed
                and (
                    evaluation.get("status") != "ready" or normal_streak < 3
                )
            ):
                result.preserved_alerts.append(active_alert)
            continue
        feature = f"hvac_response_{finding}"
        evaluation_context = dict(evaluation.get("context", {}))
        recent_ids = list(evaluation_context.get("recent_episode_ids", ()))
        observation = Observation(
            circuit_id=config.circuit_id,
            feature=feature,
            score=max(
                abs(float(evaluation["change_ratio"])) / (threshold / 100.0),
                1.0,
            ),
            baseline_confidence=min(
                1.0,
                (
                    int(evaluation["reference_count"])
                    + int(evaluation["recent_count"])
                )
                / (
                    int(evaluation["required_reference_count"])
                    + int(evaluation["required_recent_count"])
                ),
            ),
            observed_at=context.now,
            observed_value=float(evaluation["recent_runtime_minutes"]),
            baseline_value=float(evaluation["baseline_runtime_minutes"]),
            value_metric="weather_normalized_runtime_minutes",
            message=_finding_message(config, finding, evaluation),
            observation_key=f"{feature}:{stream_id}:{','.join(recent_ids)}",
            features=_finding_features(
                stream_id,
                threshold,
                evaluation,
            ),
        )
        result.observations.append(observation)
        alert = policy_provider(config.circuit_id).observe(observation)
        if alert is None:
            active_alert = _matching_active_alert(
                context,
                config.circuit_id,
                feature,
                observation.features["health_evidence_key"],
            )
            if active_alert is not None:
                result.preserved_alerts.append(active_alert)
            continue
        result.alerts.append(alert)
        result.notifications.append(alert)


def _finding_features(
    stream_id: str,
    threshold: float,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    context = dict(evaluation.get("context", {}))
    recent_ids = list(context.get("recent_episode_ids", ()))
    return {
        "notification_type": "appliance_health_issue",
        "health_feature": HVAC_EFFICIENCY_FEATURE,
        "health_evidence_key": recent_ids[-1] if recent_ids else stream_id,
        "stream_id": stream_id,
        "response_context_fingerprint": evaluation.get(
            "response_context_fingerprint"
        ),
        "threshold_pct": threshold,
        "reference_value": evaluation["baseline_runtime_minutes"],
        "recent_value": evaluation["recent_runtime_minutes"],
        "change_percent": float(evaluation["change_ratio"]) * 100.0,
        "confidence": min(
            1.0,
            (
                int(evaluation["reference_count"])
                + int(evaluation["recent_count"])
            )
            / (
                int(evaluation["required_reference_count"])
                + int(evaluation["required_recent_count"])
            ),
        ),
        "reference_core_day_count": evaluation["reference_count"],
        "recent_core_day_count": evaluation["recent_count"],
        "required_reference_core_day_count": evaluation[
            "required_reference_count"
        ],
        "required_recent_core_day_count": evaluation["required_recent_count"],
        "baseline_context": (
            f"{context.get('mode', 'HVAC')}, "
            f"{context.get('thermostat_entity_id', 'thermostat')}, "
            f"weather-normalized over {evaluation['reference_count']} core days"
        ),
        **context,
    }


def _finding_message(
    config: Any,
    finding: str,
    evaluation: Mapping[str, Any],
) -> str:
    percent = round(abs(float(evaluation["change_ratio"])) * 100.0)
    direction = "longer" if finding == "slower" else "less"
    return (
        f"{config.name} took {percent}% {direction} runtime than its "
        "weather-normalized response on at least three of five recent HVAC "
        "core days."
    )


def _matching_active_alert(
    context: ProcessingContext,
    circuit_id: str,
    feature: str,
    evidence_key: Any,
) -> AlertEvidence | None:
    for alert in getattr(
        context.state,
        "active_alerts_by_circuit",
        {},
    ).get(circuit_id, ()):
        if (
            alert.feature == feature
            and alert.features.get("health_evidence_key") == evidence_key
        ):
            return alert
    return None


def _matching_active_alert_for_stream(
    context: ProcessingContext,
    circuit_id: str,
    feature: str,
    stream_id: str,
) -> AlertEvidence | None:
    for alert in getattr(
        context.state,
        "active_alerts_by_circuit",
        {},
    ).get(circuit_id, ()):
        if (
            alert.feature == feature
            and alert.features.get("stream_id") == stream_id
        ):
            return alert
    return None


def _evaluation_to_dict(
    evaluation: HvacEfficiencyEvaluation,
) -> dict[str, Any]:
    return {
        "status": evaluation.status,
        "score": evaluation.score,
        "change_ratio": evaluation.change_ratio,
        "baseline_runtime_minutes": evaluation.baseline_runtime_minutes,
        "recent_runtime_minutes": evaluation.recent_runtime_minutes,
        "reference_count": evaluation.reference_count,
        "recent_count": evaluation.recent_count,
        "required_reference_count": evaluation.required_reference_count,
        "required_recent_count": evaluation.required_recent_count,
        "finding": evaluation.finding,
        "context": dict(evaluation.context),
    }
