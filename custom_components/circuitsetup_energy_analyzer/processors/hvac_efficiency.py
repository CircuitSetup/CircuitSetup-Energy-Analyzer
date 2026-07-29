from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
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
    episode_from_dict,
    episode_to_dict,
    evaluate_efficiency,
    observation_response_mode,
)
from ..models import AlertEvidence, ApplianceProfile, Severity
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
_SETUP_ISSUE_LIMIT = 8
HVAC_EFFICIENCY_FEATURE = "hvac_thermostat_efficiency"
_INITIAL_BASELINE_ERA = "initial"

type HvacAlertPolicyProvider = Callable[[str], Any]


class HvacEfficiencyProcessor:
    """Track thermostat response without recorder or external I/O."""

    def __init__(
        self,
        *,
        alert_policy_for_circuit: HvacAlertPolicyProvider | None = None,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit

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
            mode = observation_response_mode(observation)
            if mode is None:
                mode = _current_response_mode(
                    context,
                    linked_configs,
                    thermostat_id,
                )
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
                            (
                                f"{config.circuit_id}|{thermostat_id}|"
                                "heating"
                            ),
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
                    stored_episode = episode_to_dict(finalized)
                    stored_episode["temperature_entity_id"] = (
                        current_observation.temperature_entity_id
                    )
                    stored_episode["baseline_era"] = (
                        context.store_data.hvac_baseline_era_by_stream.get(
                            stream_id,
                            _INITIAL_BASELINE_ERA,
                        )
                    )
                    history.append(stored_episode)
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
                configs[circuit_id],
                circuit_streams.get(circuit_id, {}),
                advanced_by_circuit.get(circuit_id, {}),
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
    if _circuit_running(context, config.circuit_id):
        updated["active_minutes"] = float(
            current.get("active_minutes", 0.0)
        ) + delta
    if _electrical_driver_running(context, configs, mode):
        updated["electrical_driver_minutes"] = float(
            current.get("electrical_driver_minutes", 0.0)
        ) + delta
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
    del history[:-_HISTORY_LIMIT]
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
        elif observation.target_temperature_f is None:
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


def _circuit_efficiency_payload(
    context: ProcessingContext,
    config: Any,
    current_streams: Mapping[str, dict[str, Any]],
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    circuit_id = config.circuit_id
    threshold = _response_change_threshold(settings)
    evaluations: dict[str, dict[str, Any]] = {}
    history_by_stream = getattr(
        context.store_data,
        "hvac_response_history_by_stream",
        {},
    )
    for stream_id, raw_history in history_by_stream.items():
        if not stream_id.startswith(f"{circuit_id}|"):
            continue
        mode = stream_id.rsplit("|", 1)[-1]
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
            for raw in raw_history[-_HISTORY_LIMIT:]
            if str(raw.get("baseline_era", _INITIAL_BASELINE_ERA))
            == baseline_era
            if (episode := episode_from_dict(raw)) is not None
        ]
        evaluations[stream_id] = {
            **_evaluation_to_dict(
            evaluate_efficiency(episodes, threshold_pct=threshold)
            ),
            "baseline_era": baseline_era,
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
    return {
        "status": (
            "ready"
            if ready_scores
            else ("tracking" if current_streams else "learning")
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
        if finding not in {"slower", "faster"}:
            continue
        feature = f"hvac_response_{finding}"
        evaluation_context = dict(evaluation.get("context", {}))
        recent_ids = list(evaluation_context.get("recent_episode_ids", ()))
        observation = Observation(
            circuit_id=config.circuit_id,
            feature=feature,
            score=max(
                abs(float(evaluation["change_ratio"])) / (threshold / 100.0),
                1.5,
            ),
            baseline_confidence=min(
                1.0,
                (
                    int(evaluation["reference_count"])
                    + int(evaluation["recent_count"])
                )
                / 12.0,
            ),
            observed_at=context.now,
            observed_value=float(evaluation["recent_minutes_per_degree"]),
            baseline_value=float(evaluation["baseline_minutes_per_degree"]),
            value_metric="minutes_per_degree",
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
        if finding == "faster":
            alert = replace(alert, severity=Severity.INFO)
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
        "threshold_pct": threshold,
        "reference_value": evaluation["baseline_minutes_per_degree"],
        "recent_value": evaluation["recent_minutes_per_degree"],
        "change_percent": float(evaluation["change_ratio"]) * 100.0,
        "confidence": min(
            1.0,
            (
                int(evaluation["reference_count"])
                + int(evaluation["recent_count"])
            )
            / 12.0,
        ),
        "reference_episode_count": evaluation["reference_count"],
        "recent_episode_count": evaluation["recent_count"],
        "baseline_context": ", ".join(
            f"{key}={value}"
            for key, value in sorted(context.items())
            if key not in {"reference_episode_ids", "recent_episode_ids"}
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
        f"{config.name} took {percent}% {direction} time per degree than its "
        "weather-comparable learned response across three recent thermostat "
        "episodes."
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
