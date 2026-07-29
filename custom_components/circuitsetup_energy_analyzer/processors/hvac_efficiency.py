from __future__ import annotations

from collections.abc import Mapping
from statistics import median
from typing import Any

from ..const import (
    CONF_ADVANCED_SETTINGS,
    CONF_BLOWER_REPRESENTS_GAS_HEAT,
    CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
    DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
)
from ..context_sources import thermostat_mappings_for_settings
from ..contextual_baseline import season_for_datetime
from ..hvac_efficiency import (
    HvacEfficiencyEvaluation,
    HvacResponseEpisode,
    ThermostatObservation,
    advance_episode,
    episode_from_dict,
    episode_to_dict,
    evaluate_efficiency,
    observation_response_mode,
)
from ..models import ApplianceProfile
from ..operating_detection import operating_state_is_running
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
_HISTORY_LIMIT = 256


class HvacEfficiencyProcessor:
    """Track thermostat response without recorder or external I/O."""

    def process(
        self,
        samples: list[tuple[Any, Any]],
        context: ProcessingContext,
    ) -> FeatureResult:
        configs = {
            config.circuit_id: config
            for config, _sample in samples
            if config.appliance_profile
            in _COOLING_DRIVER_PROFILES
            | _HEATING_DRIVER_PROFILES
            | {ApplianceProfile.HVAC_BLOWER}
        }
        if not configs:
            return FeatureResult()

        advanced_by_circuit = _advanced_settings(context)
        linked_by_thermostat: dict[str, list[Any]] = {}
        for config in configs.values():
            settings = advanced_by_circuit.get(config.circuit_id, {})
            for thermostat_id in thermostat_mappings_for_settings(
                context.entry_data,
                context.options,
                settings,
            ):
                linked_by_thermostat.setdefault(thermostat_id, []).append(config)

        result = FeatureResult()
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
            mode = observation_response_mode(observation)
            active_ids = {
                config.circuit_id
                for config in linked_configs
                if _circuit_running(context, config.circuit_id)
            }
            direct_profiles = (
                _COOLING_DRIVER_PROFILES
                if mode == "cooling"
                else _HEATING_DRIVER_PROFILES
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
                    and config.circuit_id in active_ids
                    and bool(
                        advanced_by_circuit.get(config.circuit_id, {}).get(
                            CONF_BLOWER_REPRESENTS_GAS_HEAT,
                            False,
                        )
                    )
                }
                drivers.update(gas_blower_ids)
            supporting_blower_ids = tuple(
                sorted(
                    config.circuit_id
                    for config in linked_configs
                    if config.appliance_profile is ApplianceProfile.HVAC_BLOWER
                    and config.circuit_id in active_ids
                    and config.circuit_id not in gas_blower_ids
                )
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
                if finalized is not None and finalized.complete:
                    history = (
                        context.store_data.hvac_response_history_by_stream.setdefault(
                            stream_id,
                            [],
                        )
                    )
                    history.append(episode_to_dict(finalized))
                    del history[:-_HISTORY_LIMIT]
                    result.store_dirty = True

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
                result.state_updates.append(
                    StateUpdate(
                        path=("hvac_current_episode_by_stream", stream_id),
                        value={},
                    )
                )

        for circuit_id in configs:
            payload = _circuit_efficiency_payload(
                context,
                circuit_id,
                circuit_streams.get(circuit_id, {}),
                advanced_by_circuit.get(circuit_id, {}),
            )
            result.state_updates.append(
                StateUpdate(
                    path=("hvac_efficiency_by_circuit", circuit_id),
                    value=payload,
                )
            )
        return result


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


def _circuit_efficiency_payload(
    context: ProcessingContext,
    circuit_id: str,
    current_streams: Mapping[str, dict[str, Any]],
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = float(
        settings.get(
            CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
            DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
        )
    )
    evaluations: dict[str, dict[str, Any]] = {}
    history_by_stream = getattr(
        context.store_data,
        "hvac_response_history_by_stream",
        {},
    )
    for stream_id, raw_history in history_by_stream.items():
        if not stream_id.startswith(f"{circuit_id}|"):
            continue
        episodes = [
            episode
            for raw in raw_history[-_HISTORY_LIMIT:]
            if (episode := episode_from_dict(raw)) is not None
        ]
        evaluations[stream_id] = _evaluation_to_dict(
            evaluate_efficiency(episodes, threshold_pct=threshold)
        )
    ready_scores = [
        float(evaluation["score"])
        for evaluation in evaluations.values()
        if evaluation.get("score") is not None
    ]
    return {
        "status": (
            "ready"
            if ready_scores
            else ("tracking" if current_streams else "learning")
        ),
        "score": median(ready_scores) if ready_scores else None,
        "threshold_pct": threshold,
        "current_streams": dict(current_streams),
        "streams": evaluations,
    }


def _evaluation_to_dict(
    evaluation: HvacEfficiencyEvaluation,
) -> dict[str, Any]:
    return {
        "status": evaluation.status,
        "score": evaluation.score,
        "change_ratio": evaluation.change_ratio,
        "baseline_minutes_per_degree": (
            evaluation.baseline_minutes_per_degree
        ),
        "recent_minutes_per_degree": evaluation.recent_minutes_per_degree,
        "reference_count": evaluation.reference_count,
        "recent_count": evaluation.recent_count,
        "finding": evaluation.finding,
        "context": dict(evaluation.context),
    }
