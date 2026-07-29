from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from statistics import median
from typing import Any

_COMPLETION_TOLERANCE_F = 0.5
_MINIMUM_START_GAP_F = 1.0
_INACTIVE_TIMEOUT_MINUTES = 30.0
_EPISODE_TIMEOUT_MINUTES = 8.0 * 60.0
_RECENT_EPISODE_COUNT = 3
_REFERENCE_EPISODE_COUNT = 9


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


@dataclass(frozen=True, slots=True)
class HvacEfficiencyEvaluation:
    status: str
    score: float | None
    change_ratio: float | None
    baseline_minutes_per_degree: float | None
    recent_minutes_per_degree: float | None
    reference_count: int
    recent_count: int
    finding: str | None
    context: Mapping[str, Any]


def advance_episode(
    current: HvacResponseEpisode | None,
    observation: ThermostatObservation,
    *,
    now: datetime,
    circuit_id: str,
    driver_active: bool,
    active_minutes_delta: float,
    participant_signature: tuple[str, ...],
    supporting_blower_ids: tuple[str, ...],
    environmental_context: Mapping[str, Any],
) -> tuple[HvacResponseEpisode | None, HvacResponseEpisode | None]:
    actual = _finite_float(observation.actual_temperature_f)
    target = _finite_float(observation.target_temperature_f)
    mode = _response_mode(observation, actual=actual, target=target)
    if (
        current is not None
        and mode is None
        and actual is not None
        and target is not None
        and _target_reached(current.mode, actual=actual, target=target)
    ):
        mode = current.mode

    if current is None:
        if not driver_active or actual is None or target is None or mode is None:
            return None, None
        gap = _directional_gap(mode, actual=actual, target=target)
        if gap < _MINIMUM_START_GAP_F:
            return None, None
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
            active_minutes=_valid_duration(active_minutes_delta),
            outdoor_temperature_f=_finite_float(
                environmental_context.get("outdoor_temperature_f")
            ),
            season=_optional_text(environmental_context.get("season")),
            weather_mode=_optional_text(
                environmental_context.get("weather_mode")
            ),
            temperature_bin=_optional_text(
                environmental_context.get("temperature_bin")
            ),
            gap_bin=_gap_bin(gap),
            participant_signature=_sorted_unique(participant_signature),
            supporting_blower_ids=_sorted_unique(supporting_blower_ids),
            complete=False,
        )
        return episode, None

    elapsed = _elapsed_minutes(current.started_at, now)
    if (
        actual is None
        or target is None
        or mode is None
        or observation.thermostat_entity_id != current.thermostat_entity_id
        or circuit_id != current.circuit_id
        or mode != current.mode
        or not math.isclose(target, current.target_temperature_f, abs_tol=0.01)
    ):
        return None, _exclude_episode(current, now, elapsed)

    previous_interval_active = current.inactive_since is None
    inactive_since = None if driver_active else current.inactive_since or now
    updated = replace(
        current,
        latest_temperature_f=actual,
        elapsed_minutes=elapsed,
        active_minutes=(
            current.active_minutes
            + (
                _valid_duration(active_minutes_delta)
                if previous_interval_active
                else 0.0
            )
        ),
        participant_signature=_sorted_unique(
            (*current.participant_signature, *participant_signature)
        ),
        supporting_blower_ids=_sorted_unique(
            (*current.supporting_blower_ids, *supporting_blower_ids)
        ),
        inactive_since=inactive_since,
    )
    if _target_reached(mode, actual=actual, target=target):
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
) -> HvacEfficiencyEvaluation:
    groups: dict[tuple[Any, ...], list[tuple[HvacResponseEpisode, float]]] = (
        defaultdict(list)
    )
    for episode in episodes:
        metric = _minutes_per_degree(episode)
        if metric is None:
            continue
        groups[_comparison_key(episode)].append((episode, metric))

    if not groups:
        return _empty_evaluation("no_data")

    required_count = _REFERENCE_EPISODE_COUNT + _RECENT_EPISODE_COUNT
    mature_groups = [
        values for values in groups.values() if len(values) >= required_count
    ]
    if mature_groups:
        comparable = max(
            mature_groups,
            key=lambda values: max(
                _episode_sort_time(item[0]) for item in values
            ),
        )
    else:
        comparable = max(
            groups.values(),
            key=lambda values: (
                len(values),
                max(_episode_sort_time(item[0]) for item in values),
            ),
        )
    comparable.sort(key=lambda item: _episode_sort_time(item[0]))
    context = _evaluation_context(comparable[-1][0])
    if len(comparable) < required_count:
        return _empty_evaluation(
            "learning",
            context=context,
            reference_count=max(0, len(comparable) - _RECENT_EPISODE_COUNT),
            recent_count=min(len(comparable), _RECENT_EPISODE_COUNT),
        )

    reference = comparable[:_REFERENCE_EPISODE_COUNT]
    recent = comparable[-_RECENT_EPISODE_COUNT:]
    context.update(
        {
            "reference_episode_ids": [
                _episode_identifier(item[0]) for item in reference
            ],
            "recent_episode_ids": [
                _episode_identifier(item[0]) for item in recent
            ],
        }
    )
    baseline_metric = median(item[1] for item in reference)
    recent_metric = median(item[1] for item in recent)
    change_ratio = recent_metric / baseline_metric - 1.0
    threshold_ratio = max(0.0, float(threshold_pct)) / 100.0
    finding = None
    if change_ratio >= threshold_ratio:
        finding = "slower"
    elif change_ratio <= -threshold_ratio:
        finding = "faster"
    score = min(200.0, max(0.0, 100.0 * baseline_metric / recent_metric))
    return HvacEfficiencyEvaluation(
        status="ready",
        score=score,
        change_ratio=change_ratio,
        baseline_minutes_per_degree=baseline_metric,
        recent_minutes_per_degree=recent_metric,
        reference_count=len(reference),
        recent_count=len(recent),
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
        episode.thermostat_entity_id,
        episode.mode,
        episode.temperature_bin,
        episode.season,
        episode.weather_mode,
        episode.gap_bin,
        episode.participant_signature,
    )


def _minutes_per_degree(episode: HvacResponseEpisode) -> float | None:
    if episode.excluded_from_baseline or not _is_valid_completed_episode(episode):
        return None
    degrees_closed = _degrees_closed(episode)
    return episode.elapsed_minutes / degrees_closed


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
    target_gap = _directional_gap(
        episode.mode,
        actual=episode.start_temperature_f,
        target=episode.target_temperature_f,
    )
    degrees_closed = _degrees_closed(episode)
    return target_gap >= _MINIMUM_START_GAP_F and degrees_closed > 0.0


def _is_valid_runtime_episode(episode: HvacResponseEpisode) -> bool:
    if (
        not episode.stream_id
        or not episode.circuit_id
        or not episode.thermostat_entity_id
        or episode.mode not in {"heating", "cooling"}
        or not episode.participant_signature
    ):
        return False
    numeric_values = (
        episode.start_temperature_f,
        episode.target_temperature_f,
        episode.latest_temperature_f,
        episode.elapsed_minutes,
        episode.active_minutes,
    )
    return bool(
        all(math.isfinite(value) for value in numeric_values)
        and episode.elapsed_minutes >= 0.0
        and episode.active_minutes >= 0.0
        and _directional_gap(
            episode.mode,
            actual=episode.start_temperature_f,
            target=episode.target_temperature_f,
        )
        >= _MINIMUM_START_GAP_F
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


def _evaluation_context(episode: HvacResponseEpisode) -> dict[str, Any]:
    return {
        "stream_id": episode.stream_id,
        "circuit_id": episode.circuit_id,
        "thermostat_entity_id": episode.thermostat_entity_id,
        "mode": episode.mode,
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
) -> HvacEfficiencyEvaluation:
    return HvacEfficiencyEvaluation(
        status=status,
        score=None,
        change_ratio=None,
        baseline_minutes_per_degree=None,
        recent_minutes_per_degree=None,
        reference_count=reference_count,
        recent_count=recent_count,
        finding=None,
        context=dict(context or {}),
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
