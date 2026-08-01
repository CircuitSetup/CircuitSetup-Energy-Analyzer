from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence, Set
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from statistics import linear_regression, median
from typing import Any

from .local_time import TimeZone, local_date

_COMPLETION_TOLERANCE_F = 0.5
_MINIMUM_START_GAP_F = 1.0
_MINIMUM_CALL_GAP_F = 0.1
_MINIMUM_CALL_PROGRESS_F = 0.1
_INACTIVE_TIMEOUT_MINUTES = 30.0
_EPISODE_TIMEOUT_MINUTES = 8.0 * 60.0
_MIN_CORE_DAY_RUNTIME_MINUTES = 30.0
_PROVISIONAL_CORE_DAY_COUNT = 30
_REFERENCE_CORE_DAY_COUNT = 50
_RECENT_CORE_DAY_COUNT = 5
_MIN_ABNORMAL_RECENT_DAYS = 3
_MIN_REFERENCE_SPAN_DAYS = 42
_MIN_OUTDOOR_TEMPERATURE_BINS = 3
_OUTDOOR_TEMPERATURE_BIN_F = 5.0
_MODEL_VERSION = 2
_LIGHTWEIGHT_RETENTION_DAYS = 18
_LIGHTWEIGHT_REFERENCE_CORE_DAY_COUNT = 12


@dataclass(frozen=True, slots=True)
class ThermostatObservation:
    thermostat_entity_id: str
    temperature_entity_id: str | None
    actual_temperature_f: float | None
    target_temperature_f: float | None
    mode: str | None
    action: str | None
    available_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HvacResponseEpisode:
    stream_id: str
    circuit_id: str
    thermostat_entity_id: str
    mode: str
    started_at: datetime
    ended_at: datetime | None
    start_temperature_f: float
    target_temperature_f: float
    latest_temperature_f: float
    elapsed_minutes: float
    active_minutes: float
    outdoor_temperature_f: float | None
    season: str | None
    weather_mode: str | None
    temperature_bin: str | None
    gap_bin: str
    participant_signature: tuple[str, ...]
    supporting_blower_ids: tuple[str, ...]
    complete: bool
    excluded_from_baseline: bool = False
    inactive_since: datetime | None = None
    temperature_entity_id: str | None = None
    appliance_profile: str | None = None
    episode_kind: str = "setpoint_response"
    outdoor_temperature_minutes: float = 0.0
    model_version: int = _MODEL_VERSION


@dataclass(frozen=True, slots=True)
class HvacEfficiencyEvaluation:
    status: str
    score: float | None
    change_ratio: float | None
    baseline_runtime_minutes: float | None
    recent_runtime_minutes: float | None
    reference_count: int
    recent_count: int
    required_reference_count: int
    required_recent_count: int
    finding: str | None
    context: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _CoreDay:
    day: date
    runtime_minutes: float
    indoor_temperature_f: float
    outdoor_temperature_f: float
    episode_ids: tuple[str, ...]


def advance_episode(
    current: HvacResponseEpisode | None,
    observation: ThermostatObservation,
    *,
    now: datetime,
    circuit_id: str,
    appliance_profile: str,
    driver_active: bool,
    active_minutes_delta: float,
    participant_signature: tuple[str, ...],
    supporting_blower_ids: tuple[str, ...],
    environmental_context: Mapping[str, Any],
) -> tuple[HvacResponseEpisode | None, HvacResponseEpisode | None]:
    actual = _finite_float(observation.actual_temperature_f)
    target = _finite_float(observation.target_temperature_f)
    action = str(observation.action or "").lower()
    action_active = action in {"heating", "cooling"}
    range_capabilities = set(observation.available_capabilities)
    preserved_target = False
    if (
        current is not None
        and target is None
        and (
            action == "idle"
            or (
                not action
                and {"target_temp_low", "target_temp_high"}
                <= range_capabilities
            )
        )
    ):
        target = current.target_temperature_f
        preserved_target = True
    call_ended = (
        current is not None
        and current.episode_kind == "thermostat_call"
        and (
            (bool(action) and action != current.mode)
            or (not action and not driver_active)
        )
    )
    if call_ended:
        target = current.target_temperature_f
        preserved_target = True
    mode = _response_mode(observation, actual=actual, target=target)
    if call_ended:
        mode = current.mode
    if (
        current is not None
        and actual is not None
        and target is not None
        and (mode is None or preserved_target)
        and _target_reached(current.mode, actual=actual, target=target)
    ):
        mode = current.mode

    if current is None:
        if not driver_active or actual is None or target is None or mode is None:
            return None, None
        gap = _directional_gap(mode, actual=actual, target=target)
        episode_kind = "setpoint_response"
        if not _meets_minimum(gap, _MINIMUM_START_GAP_F):
            if not action_active or not _meets_minimum(gap, _MINIMUM_CALL_GAP_F):
                return None, None
            episode_kind = "thermostat_call"
        outdoor_temperature = _finite_float(
            environmental_context.get("outdoor_temperature_f")
        )
        initial_active_minutes = _valid_duration(active_minutes_delta)
        episode = HvacResponseEpisode(
            stream_id=(
                f"{circuit_id}|{observation.thermostat_entity_id}|{mode}"
            ),
            circuit_id=circuit_id,
            thermostat_entity_id=observation.thermostat_entity_id,
            mode=mode,
            started_at=now,
            ended_at=None,
            start_temperature_f=actual,
            target_temperature_f=target,
            latest_temperature_f=actual,
            elapsed_minutes=0.0,
            active_minutes=initial_active_minutes,
            outdoor_temperature_f=outdoor_temperature,
            season=_optional_text(environmental_context.get("season")),
            weather_mode=_optional_text(
                environmental_context.get("weather_mode")
            ),
            temperature_bin=_optional_text(
                environmental_context.get("temperature_bin")
            ),
            gap_bin="0-1F" if episode_kind == "thermostat_call" else _gap_bin(gap),
            participant_signature=_sorted_unique(participant_signature),
            supporting_blower_ids=_sorted_unique(supporting_blower_ids),
            complete=False,
            temperature_entity_id=observation.temperature_entity_id,
            appliance_profile=_optional_text(appliance_profile),
            episode_kind=episode_kind,
            outdoor_temperature_minutes=(
                initial_active_minutes
                if outdoor_temperature is not None
                else 0.0
            ),
        )
        return episode, None

    elapsed = _elapsed_minutes(current.started_at, now)
    if (
        actual is None
        or target is None
        or mode is None
        or observation.thermostat_entity_id != current.thermostat_entity_id
        or observation.temperature_entity_id != current.temperature_entity_id
        or circuit_id != current.circuit_id
        or appliance_profile != current.appliance_profile
        or mode != current.mode
        or not math.isclose(target, current.target_temperature_f, abs_tol=0.01)
    ):
        return None, _exclude_episode(current, now, elapsed)

    previous_interval_active = current.inactive_since is None
    active_delta = (
        _valid_duration(active_minutes_delta) if previous_interval_active else 0.0
    )
    outdoor_temperature = _finite_float(
        environmental_context.get("outdoor_temperature_f")
    )
    outdoor_minutes = current.outdoor_temperature_minutes + (
        active_delta if outdoor_temperature is not None else 0.0
    )
    outdoor_average = current.outdoor_temperature_f
    if outdoor_temperature is not None:
        outdoor_average = (
            (
                (current.outdoor_temperature_f or 0.0)
                * current.outdoor_temperature_minutes
                + outdoor_temperature * active_delta
            )
            / outdoor_minutes
            if outdoor_minutes > 0.0
            else outdoor_temperature
        )
    inactive_since = None if driver_active else current.inactive_since or now
    updated = replace(
        current,
        latest_temperature_f=actual,
        elapsed_minutes=elapsed,
        active_minutes=(
            current.active_minutes + active_delta
        ),
        outdoor_temperature_f=outdoor_average,
        outdoor_temperature_minutes=outdoor_minutes,
        participant_signature=_sorted_unique(
            (*current.participant_signature, *participant_signature)
        ),
        supporting_blower_ids=_sorted_unique(
            (*current.supporting_blower_ids, *supporting_blower_ids)
        ),
        inactive_since=inactive_since,
    )
    if call_ended:
        complete = _has_minimum_progress(updated)
        return None, replace(
            updated,
            ended_at=now,
            complete=complete,
            excluded_from_baseline=not complete,
            inactive_since=None,
        )
    if (
        current.episode_kind == "setpoint_response"
        and _target_reached(mode, actual=actual, target=target)
    ):
        return None, replace(
            updated,
            ended_at=now,
            complete=True,
            excluded_from_baseline=False,
            inactive_since=None,
        )
    if elapsed >= _EPISODE_TIMEOUT_MINUTES or (
        inactive_since is not None
        and _elapsed_minutes(inactive_since, now) >= _INACTIVE_TIMEOUT_MINUTES
    ):
        return None, _exclude_episode(updated, now, elapsed)
    return updated, None


def evaluate_efficiency(
    episodes: Sequence[HvacResponseEpisode],
    *,
    threshold_pct: float,
    time_zone: TimeZone = None,
    excluded_dates: Set[date] = frozenset(),
    current_date: date | None = None,
    retention_days: int | None = None,
) -> HvacEfficiencyEvaluation:
    reference_required = _reference_core_day_count(retention_days)
    reference_span_required = min(
        _MIN_REFERENCE_SPAN_DAYS,
        reference_required - 1,
    )
    current_model = [
        episode
        for episode in episodes
        if episode.model_version >= _MODEL_VERSION
        and _is_valid_completed_episode(episode)
        and not episode.excluded_from_baseline
        and (
            current_date is None
            or local_date(episode.started_at, time_zone) < current_date
        )
    ]
    if not current_model:
        return _empty_evaluation(
            "no_data",
            required_reference_count=reference_required,
        )
    weather_ready = [
        episode
        for episode in current_model
        if episode.outdoor_temperature_f is not None
        and _meets_minimum(
            episode.outdoor_temperature_minutes,
            episode.active_minutes,
        )
    ]
    if not weather_ready:
        return _empty_evaluation(
            "no_weather_data",
            required_reference_count=reference_required,
        )

    groups: dict[tuple[Any, ...], list[HvacResponseEpisode]] = defaultdict(list)
    for episode in current_model:
        if local_date(episode.started_at, time_zone) not in excluded_dates:
            groups[_comparison_key(episode)].append(episode)
    core_by_key = {
        key: days
        for key, group in groups.items()
        if (days := _core_days(group, time_zone=time_zone))
    }
    if not core_by_key:
        return _empty_evaluation(
            "learning",
            required_reference_count=reference_required,
        )
    comparison_key = max(
        core_by_key,
        key=lambda key: (len(core_by_key[key]), core_by_key[key][-1].day),
    )
    comparable = core_by_key[comparison_key]
    latest_episode = max(groups[comparison_key], key=_episode_sort_time)
    context = _evaluation_context(latest_episode)
    if len(comparable) < reference_required:
        return _empty_evaluation(
            "provisional"
            if len(comparable) >= min(
                _PROVISIONAL_CORE_DAY_COUNT,
                reference_required,
            )
            else "learning",
            context=context,
            reference_count=len(comparable),
            required_reference_count=reference_required,
        )

    reference = comparable[:reference_required]
    if (
        len(comparable) >= reference_required + _RECENT_CORE_DAY_COUNT
        and not _reference_window_ready(
            reference,
            span_days=reference_span_required,
            mode=latest_episode.mode,
        )
    ):
        reference = comparable[
            -(_RECENT_CORE_DAY_COUNT + reference_required) :
            -_RECENT_CORE_DAY_COUNT
        ]
    reference_span = (reference[-1].day - reference[0].day).days
    outdoor_bins = {
        math.floor(day.outdoor_temperature_f / _OUTDOOR_TEMPERATURE_BIN_F)
        for day in reference
    }
    if not _reference_window_ready(
        reference,
        span_days=reference_span_required,
        mode=latest_episode.mode,
    ):
        context.update(
            {
                "reference_span_days": reference_span,
                "outdoor_temperature_bin_count": len(outdoor_bins),
            }
        )
        return _empty_evaluation(
            "provisional",
            context=context,
            reference_count=len(reference),
            required_reference_count=reference_required,
        )
    if len(comparable) < reference_required + _RECENT_CORE_DAY_COUNT:
        return _empty_evaluation(
            "provisional",
            context=context,
            reference_count=len(reference),
            recent_count=len(comparable) - len(reference),
            required_reference_count=reference_required,
        )

    recent = comparable[-_RECENT_CORE_DAY_COUNT:]
    reference_load = [_thermal_demand(day, latest_episode.mode) for day in reference]
    reference_runtime = [day.runtime_minutes for day in reference]
    if len({round(load, 6) for load in reference_load}) < 2:
        return _empty_evaluation(
            "provisional",
            context=context,
            reference_count=len(reference),
            recent_count=len(recent),
            required_reference_count=reference_required,
        )
    slope, intercept = linear_regression(reference_load, reference_runtime)
    if slope <= 0.0:
        return _empty_evaluation(
            "provisional",
            context=context,
            reference_count=len(reference),
            recent_count=len(recent),
            required_reference_count=reference_required,
        )
    recent_load = [_thermal_demand(day, latest_episode.mode) for day in recent]
    predicted = [max(1.0, intercept + slope * load) for load in recent_load]
    ratios = [
        day.runtime_minutes / expected - 1.0
        for day, expected in zip(recent, predicted, strict=True)
    ]
    prediction_margins = _prediction_margins(
        reference_load,
        reference_runtime,
        recent_load,
        slope=slope,
        intercept=intercept,
    )
    threshold_ratio = max(0.0, float(threshold_pct)) / 100.0
    slower = [
        _meets_minimum(ratio, threshold_ratio)
        and _meets_minimum(day.runtime_minutes, expected + margin)
        for day, expected, ratio, margin in zip(
            recent,
            predicted,
            ratios,
            prediction_margins,
            strict=True,
        )
    ]
    faster = [
        _meets_minimum(-ratio, threshold_ratio)
        and (
            day.runtime_minutes <= expected - margin
            or math.isclose(day.runtime_minutes, expected - margin, abs_tol=1e-6)
        )
        for day, expected, ratio, margin in zip(
            recent,
            predicted,
            ratios,
            prediction_margins,
            strict=True,
        )
    ]
    finding = (
        "slower"
        if sum(slower) >= _MIN_ABNORMAL_RECENT_DAYS
        else (
            "faster" if sum(faster) >= _MIN_ABNORMAL_RECENT_DAYS else None
        )
    )
    expected_runtime = median(predicted)
    observed_runtime = median(day.runtime_minutes for day in recent)
    change_ratio = median(ratios)
    context.update(
        {
            "reference_core_dates": [day.day.isoformat() for day in reference],
            "recent_core_dates": [day.day.isoformat() for day in recent],
            "reference_episode_ids": [
                identifier for day in reference for identifier in day.episode_ids
            ],
            "recent_episode_ids": [
                identifier for day in recent for identifier in day.episode_ids
            ],
            "reference_span_days": reference_span,
            "outdoor_temperature_bin_count": len(outdoor_bins),
            "outdoor_temperature_f": median(
                day.outdoor_temperature_f for day in recent
            ),
            "abnormal_recent_days": max(sum(slower), sum(faster)),
            "normal_streak": _trailing_false_count(slower),
            "prediction_margin_minutes": median(prediction_margins),
        }
    )
    return HvacEfficiencyEvaluation(
        status="ready",
        score=min(200.0, max(0.0, 100.0 * expected_runtime / observed_runtime)),
        change_ratio=change_ratio,
        baseline_runtime_minutes=expected_runtime,
        recent_runtime_minutes=observed_runtime,
        reference_count=len(reference),
        recent_count=len(recent),
        required_reference_count=reference_required,
        required_recent_count=_RECENT_CORE_DAY_COUNT,
        finding=finding,
        context=context,
    )


def episode_to_dict(
    episode: HvacResponseEpisode,
    *,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    if not (
        _is_valid_runtime_episode(episode)
        if allow_incomplete
        else _is_valid_completed_episode(episode)
    ):
        raise ValueError("Only valid completed HVAC response episodes can be stored")
    payload = asdict(episode)
    for key in ("started_at", "ended_at", "inactive_since"):
        value = payload[key]
        payload[key] = value.isoformat() if isinstance(value, datetime) else None
    payload["participant_signature"] = list(episode.participant_signature)
    payload["supporting_blower_ids"] = list(episode.supporting_blower_ids)
    return payload


def episode_from_dict(
    raw: Mapping[str, Any],
    *,
    allow_incomplete: bool = False,
) -> HvacResponseEpisode | None:
    try:
        episode = HvacResponseEpisode(
            stream_id=str(raw["stream_id"]),
            circuit_id=str(raw["circuit_id"]),
            thermostat_entity_id=str(raw["thermostat_entity_id"]),
            mode=str(raw["mode"]),
            started_at=_required_datetime(raw.get("started_at")),
            ended_at=_optional_datetime(raw.get("ended_at")),
            start_temperature_f=float(raw["start_temperature_f"]),
            target_temperature_f=float(raw["target_temperature_f"]),
            latest_temperature_f=float(raw["latest_temperature_f"]),
            elapsed_minutes=float(raw["elapsed_minutes"]),
            active_minutes=float(raw["active_minutes"]),
            outdoor_temperature_f=_finite_float(
                raw.get("outdoor_temperature_f")
            ),
            season=_optional_text(raw.get("season")),
            weather_mode=_optional_text(raw.get("weather_mode")),
            temperature_bin=_optional_text(raw.get("temperature_bin")),
            gap_bin=str(raw["gap_bin"]),
            participant_signature=_sorted_unique(
                _string_sequence(raw.get("participant_signature"))
            ),
            supporting_blower_ids=_sorted_unique(
                _string_sequence(raw.get("supporting_blower_ids"))
            ),
            complete=bool(raw.get("complete", False)),
            excluded_from_baseline=bool(
                raw.get("excluded_from_baseline", False)
            ),
            inactive_since=_optional_datetime(raw.get("inactive_since")),
            temperature_entity_id=_optional_text(
                raw.get("temperature_entity_id")
            ),
            appliance_profile=_optional_text(raw.get("appliance_profile")),
            episode_kind=str(raw.get("episode_kind", "setpoint_response")),
            outdoor_temperature_minutes=float(
                raw.get("outdoor_temperature_minutes", 0.0)
            ),
            model_version=int(raw.get("model_version", 1)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    valid = (
        _is_valid_runtime_episode(episode)
        if allow_incomplete
        else _is_valid_completed_episode(episode)
    )
    return episode if valid else None


def observation_response_mode(
    observation: ThermostatObservation,
) -> str | None:
    """Return the normalized heating/cooling direction for one observation."""
    return _response_mode(
        observation,
        actual=_finite_float(observation.actual_temperature_f),
        target=_finite_float(observation.target_temperature_f),
    )


def _response_mode(
    observation: ThermostatObservation,
    *,
    actual: float | None,
    target: float | None,
) -> str | None:
    action = str(observation.action or "").lower()
    if action in {"heating", "cooling"}:
        return action
    if action:
        return None
    mode = str(observation.mode or "").lower()
    if mode in {"heat", "heating"}:
        return "heating"
    if mode in {"cool", "cooling"}:
        return "cooling"
    if mode in {"auto", "heat_cool"} and actual is not None and target is not None:
        if target > actual:
            return "heating"
        if target < actual:
            return "cooling"
    return None


def _directional_gap(mode: str, *, actual: float, target: float) -> float:
    return target - actual if mode == "heating" else actual - target


def _target_reached(mode: str, *, actual: float, target: float) -> bool:
    if mode == "heating":
        return actual >= target - _COMPLETION_TOLERANCE_F
    return actual <= target + _COMPLETION_TOLERANCE_F


def _gap_bin(gap: float) -> str:
    lower = math.floor(gap / 2.0) * 2.0
    return f"{lower:g}-{lower + 2.0:g}F"


def _exclude_episode(
    episode: HvacResponseEpisode,
    now: datetime,
    elapsed_minutes: float,
) -> HvacResponseEpisode:
    return replace(
        episode,
        ended_at=now,
        elapsed_minutes=elapsed_minutes,
        complete=False,
        excluded_from_baseline=True,
    )


def _comparison_key(episode: HvacResponseEpisode) -> tuple[Any, ...]:
    return (
        episode.circuit_id,
        episode.appliance_profile,
        episode.thermostat_entity_id,
        episode.temperature_entity_id,
        episode.mode,
        episode.participant_signature,
        episode.supporting_blower_ids,
    )


def compact_completed_core_days(
    episodes: Sequence[HvacResponseEpisode],
    *,
    time_zone: TimeZone,
    current_date: date,
    retention_days: int | None = None,
) -> list[HvacResponseEpisode]:
    """Replace closed raw calls with bounded daily model evidence."""
    pending: list[HvacResponseEpisode] = []
    by_day: dict[tuple[tuple[Any, ...], date], list[HvacResponseEpisode]] = (
        defaultdict(list)
    )
    for episode in episodes:
        day = local_date(episode.started_at, time_zone)
        end_day = local_date(episode.ended_at or episode.started_at, time_zone)
        if max(day, end_day) >= current_date:
            pending.append(episode)
        elif (
            episode.model_version >= _MODEL_VERSION
            and _is_valid_completed_episode(episode)
            and not episode.excluded_from_baseline
        ):
            by_day[(_comparison_key(episode), day)].append(episode)

    summaries = [
        summary
        for group in by_day.values()
        if (summary := _compact_core_day(group, time_zone=time_zone)) is not None
    ]
    reference_required = _reference_core_day_count(retention_days)
    bounded: list[HvacResponseEpisode] = []
    by_comparison: dict[tuple[Any, ...], list[HvacResponseEpisode]] = defaultdict(
        list
    )
    for summary in summaries:
        by_comparison[_comparison_key(summary)].append(summary)
    for group in by_comparison.values():
        ordered = sorted(group, key=_episode_sort_time)
        if len(ordered) > reference_required + _RECENT_CORE_DAY_COUNT:
            recent = ordered[-_RECENT_CORE_DAY_COUNT:]
            candidate_pool = ordered[:-_RECENT_CORE_DAY_COUNT]
            reference = candidate_pool[:reference_required]
            if not _reference_window_ready(
                _core_days(reference, time_zone=time_zone),
                span_days=min(
                    _MIN_REFERENCE_SPAN_DAYS,
                    reference_required - 1,
                ),
                mode=reference[0].mode,
            ):
                reference = candidate_pool[-reference_required:]
            ordered = [
                *reference,
                *recent,
            ]
        bounded.extend(ordered)
    return sorted([*bounded, *pending], key=_episode_sort_time)


def _core_days(
    episodes: Sequence[HvacResponseEpisode],
    *,
    time_zone: TimeZone,
) -> list[_CoreDay]:
    by_date: dict[date, list[HvacResponseEpisode]] = defaultdict(list)
    for episode in episodes:
        day = local_date(episode.started_at, time_zone)
        if episode.ended_at is not None and local_date(
            episode.ended_at,
            time_zone,
        ) != day:
            continue
        by_date[day].append(episode)
    days = []
    for day, day_episodes in by_date.items():
        runtime = sum(episode.active_minutes for episode in day_episodes)
        weather_minutes = sum(
            episode.outdoor_temperature_minutes for episode in day_episodes
        )
        if (
            runtime < _MIN_CORE_DAY_RUNTIME_MINUTES
            or not _meets_minimum(weather_minutes, runtime)
        ):
            continue
        outdoor = sum(
            float(episode.outdoor_temperature_f)
            * episode.outdoor_temperature_minutes
            for episode in day_episodes
            if episode.outdoor_temperature_f is not None
        ) / weather_minutes
        indoor = sum(
            (episode.start_temperature_f + episode.latest_temperature_f)
            / 2.0
            * episode.active_minutes
            for episode in day_episodes
        ) / runtime
        days.append(
            _CoreDay(
                day=day,
                runtime_minutes=runtime,
                indoor_temperature_f=indoor,
                outdoor_temperature_f=outdoor,
                episode_ids=tuple(
                    _episode_identifier(episode)
                    for episode in sorted(
                        day_episodes,
                        key=_episode_sort_time,
                    )
                ),
            )
        )
    return sorted(days, key=lambda item: item.day)


def _compact_core_day(
    episodes: Sequence[HvacResponseEpisode],
    *,
    time_zone: TimeZone,
) -> HvacResponseEpisode | None:
    days = _core_days(episodes, time_zone=time_zone)
    if len(days) != 1:
        return None
    day = days[0]
    representative = max(episodes, key=_episode_sort_time)
    first = min(episodes, key=lambda item: item.started_at)
    last = max(episodes, key=_episode_sort_time)
    indoor = day.indoor_temperature_f
    if representative.mode == "cooling":
        start_temperature, target_temperature = indoor + 1.0, indoor - 1.0
    else:
        start_temperature, target_temperature = indoor - 1.0, indoor + 1.0
    return replace(
        representative,
        started_at=first.started_at,
        ended_at=last.ended_at,
        start_temperature_f=start_temperature,
        target_temperature_f=target_temperature,
        latest_temperature_f=target_temperature,
        elapsed_minutes=max(
            day.runtime_minutes,
            _elapsed_minutes(first.started_at, last.ended_at or last.started_at),
        ),
        active_minutes=day.runtime_minutes,
        outdoor_temperature_f=day.outdoor_temperature_f,
        outdoor_temperature_minutes=day.runtime_minutes,
        gap_bin="daily",
        complete=True,
        excluded_from_baseline=False,
        inactive_since=None,
        episode_kind="core_day",
    )


def _thermal_demand(day: _CoreDay, mode: str) -> float:
    return max(
        0.0,
        (
            day.outdoor_temperature_f - day.indoor_temperature_f
            if mode == "cooling"
            else day.indoor_temperature_f - day.outdoor_temperature_f
        ),
    )


def _reference_window_ready(
    days: Sequence[_CoreDay],
    *,
    span_days: int,
    mode: str,
) -> bool:
    if (
        not days
        or (days[-1].day - days[0].day).days < span_days
        or len(
            {
                math.floor(
                    day.outdoor_temperature_f / _OUTDOOR_TEMPERATURE_BIN_F
                )
                for day in days
            }
        )
        < _MIN_OUTDOOR_TEMPERATURE_BINS
    ):
        return False
    loads = [_thermal_demand(day, mode) for day in days]
    return len(set(loads)) >= 2 and linear_regression(
        loads,
        [day.runtime_minutes for day in days],
    ).slope > 0.0


def _prediction_margins(
    loads: Sequence[float],
    runtimes: Sequence[float],
    recent_loads: Sequence[float],
    *,
    slope: float,
    intercept: float,
) -> list[float]:
    if len(loads) <= 2:
        return [0.0] * len(recent_loads)
    squared_error = sum(
        (runtime - (intercept + slope * load)) ** 2
        for load, runtime in zip(loads, runtimes, strict=True)
    )
    standard_error = math.sqrt(squared_error / (len(loads) - 2))
    mean_load = sum(loads) / len(loads)
    load_variation = sum((load - mean_load) ** 2 for load in loads)
    return [
        1.96
        * standard_error
        * math.sqrt(
            1.0
            + 1.0 / len(loads)
            + (load - mean_load) ** 2 / load_variation
        )
        for load in recent_loads
    ]


def _trailing_false_count(values: Sequence[bool]) -> int:
    count = 0
    for value in reversed(values):
        if value:
            break
        count += 1
    return count


def _is_valid_completed_episode(episode: HvacResponseEpisode) -> bool:
    if not _is_valid_runtime_episode(episode):
        return False
    if (
        not episode.complete
        or episode.ended_at is None
    ):
        return False
    if episode.elapsed_minutes <= 0.0 or episode.active_minutes <= 0.0:
        return False
    if episode.episode_kind == "core_day":
        return True
    target_gap = _directional_gap(
        episode.mode,
        actual=episode.start_temperature_f,
        target=episode.target_temperature_f,
    )
    degrees_closed = _degrees_closed(episode)
    return (
        _valid_start_gap(episode, target_gap)
        and (
            _has_minimum_progress(episode)
            if episode.episode_kind == "thermostat_call"
            else degrees_closed > 0.0
        )
    )


def _is_valid_runtime_episode(episode: HvacResponseEpisode) -> bool:
    if (
        not episode.stream_id
        or not episode.circuit_id
        or not episode.thermostat_entity_id
        or episode.mode not in {"heating", "cooling"}
        or episode.episode_kind
        not in {"setpoint_response", "thermostat_call", "core_day"}
        or not episode.participant_signature
    ):
        return False
    numeric_values = (
        episode.start_temperature_f,
        episode.target_temperature_f,
        episode.latest_temperature_f,
        episode.elapsed_minutes,
        episode.active_minutes,
        episode.outdoor_temperature_minutes,
    )
    return bool(
        all(math.isfinite(value) for value in numeric_values)
        and episode.elapsed_minutes >= 0.0
        and episode.active_minutes >= 0.0
        and episode.outdoor_temperature_minutes >= 0.0
        and episode.model_version >= 1
        and _valid_start_gap(
            episode,
            _directional_gap(
                episode.mode,
                actual=episode.start_temperature_f,
                target=episode.target_temperature_f,
            ),
        )
    )


def _degrees_closed(episode: HvacResponseEpisode) -> float:
    target_gap = _directional_gap(
        episode.mode,
        actual=episode.start_temperature_f,
        target=episode.target_temperature_f,
    )
    closed = (
        episode.latest_temperature_f - episode.start_temperature_f
        if episode.mode == "heating"
        else episode.start_temperature_f - episode.latest_temperature_f
    )
    return min(target_gap, closed)


def _valid_start_gap(episode: HvacResponseEpisode, gap: float) -> bool:
    if episode.episode_kind == "thermostat_call":
        return _meets_minimum(gap, _MINIMUM_CALL_GAP_F) and not _meets_minimum(
            gap, _MINIMUM_START_GAP_F
        )
    return _meets_minimum(gap, _MINIMUM_START_GAP_F)


def _has_minimum_progress(episode: HvacResponseEpisode) -> bool:
    return _meets_minimum(_degrees_closed(episode), _MINIMUM_CALL_PROGRESS_F)


def _meets_minimum(value: float, minimum: float) -> bool:
    return value >= minimum or math.isclose(value, minimum, abs_tol=1e-6)


def _evaluation_context(episode: HvacResponseEpisode) -> dict[str, Any]:
    return {
        "stream_id": episode.stream_id,
        "circuit_id": episode.circuit_id,
        "appliance_profile": episode.appliance_profile,
        "thermostat_entity_id": episode.thermostat_entity_id,
        "temperature_entity_id": episode.temperature_entity_id,
        "mode": episode.mode,
        "episode_kind": episode.episode_kind,
        "temperature_bin": episode.temperature_bin,
        "season": episode.season,
        "weather_mode": episode.weather_mode,
        "gap_bin": episode.gap_bin,
        "participant_signature": list(episode.participant_signature),
        "supporting_blower_ids": list(episode.supporting_blower_ids),
        "outdoor_temperature_f": episode.outdoor_temperature_f,
    }


def _episode_identifier(episode: HvacResponseEpisode) -> str:
    return episode.started_at.isoformat()


def _empty_evaluation(
    status: str,
    *,
    context: Mapping[str, Any] | None = None,
    reference_count: int = 0,
    recent_count: int = 0,
    required_reference_count: int = _REFERENCE_CORE_DAY_COUNT,
    required_recent_count: int = _RECENT_CORE_DAY_COUNT,
    recent_runtime_minutes: float | None = None,
) -> HvacEfficiencyEvaluation:
    return HvacEfficiencyEvaluation(
        status=status,
        score=None,
        change_ratio=None,
        baseline_runtime_minutes=None,
        recent_runtime_minutes=recent_runtime_minutes,
        reference_count=reference_count,
        recent_count=recent_count,
        required_reference_count=required_reference_count,
        required_recent_count=required_recent_count,
        finding=None,
        context=dict(context or {}),
    )


def _reference_core_day_count(retention_days: int | None) -> int:
    return (
        _LIGHTWEIGHT_REFERENCE_CORE_DAY_COUNT
        if retention_days is not None
        and retention_days <= _LIGHTWEIGHT_RETENTION_DAYS
        else _REFERENCE_CORE_DAY_COUNT
    )


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _valid_duration(value: Any) -> float:
    parsed = _finite_float(value)
    return parsed if parsed is not None and parsed >= 0.0 else 0.0


def _elapsed_minutes(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60.0)


def _episode_sort_time(episode: HvacResponseEpisode) -> datetime:
    return episode.ended_at or episode.started_at


def _sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if str(value)}))


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_datetime(value: Any) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError("datetime required")
    return parsed


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
