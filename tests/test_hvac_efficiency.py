from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.hvac_efficiency import (
    HvacResponseEpisode,
    ThermostatObservation,
    advance_episode,
    compact_completed_core_days,
    episode_from_dict,
    episode_to_dict,
    evaluate_efficiency,
)

START = datetime(2026, 7, 1, 12, tzinfo=UTC)
HOT_CONTEXT = {
    "outdoor_temperature_f": 92.0,
    "season": "summer",
    "weather_mode": "cooling",
    "temperature_bin": "very_hot",
}


def _observation(
    *,
    actual: float | None,
    target: float | None,
    mode: str = "cool",
    action: str | None = "cooling",
) -> ThermostatObservation:
    return ThermostatObservation(
        thermostat_entity_id="climate.downstairs",
        temperature_entity_id="sensor.downstairs_temperature",
        actual_temperature_f=actual,
        target_temperature_f=target,
        mode=mode,
        action=action,
        available_capabilities=(
            "current_temperature",
            "temperature",
            "hvac_action",
        ),
    )


def _advance(
    current: HvacResponseEpisode | None,
    observation: ThermostatObservation,
    *,
    now: datetime = START,
    driver_active: bool = True,
    active_minutes_delta: float = 0.0,
    appliance_profile: str = "heat_pump",
) -> tuple[HvacResponseEpisode | None, HvacResponseEpisode | None]:
    return advance_episode(
        current,
        observation,
        now=now,
        circuit_id="heat_pump",
        appliance_profile=appliance_profile,
        driver_active=driver_active,
        active_minutes_delta=active_minutes_delta,
        participant_signature=("heat_pump",),
        supporting_blower_ids=("blower",),
        environmental_context=HOT_CONTEXT,
    )


def _completed_episode(
    index: int,
    *,
    minutes_per_degree: float,
    thermostat: str = "climate.downstairs",
    mode: str = "cooling",
    temperature_bin: str = "very_hot",
    gap_bin: str = "4-6F",
    participants: tuple[str, ...] = ("heat_pump",),
) -> HvacResponseEpisode:
    started = START + timedelta(days=index)
    degrees = 5.0
    return HvacResponseEpisode(
        stream_id=f"heat_pump|{thermostat}|{mode}",
        circuit_id="heat_pump",
        thermostat_entity_id=thermostat,
        mode=mode,
        started_at=started,
        ended_at=started + timedelta(minutes=minutes_per_degree * degrees),
        start_temperature_f=77.0 if mode == "cooling" else 65.0,
        target_temperature_f=72.0 if mode == "cooling" else 70.0,
        latest_temperature_f=72.0 if mode == "cooling" else 70.0,
        elapsed_minutes=minutes_per_degree * degrees,
        active_minutes=minutes_per_degree * degrees,
        outdoor_temperature_f=92.0,
        season="summer",
        weather_mode=mode,
        temperature_bin=temperature_bin,
        gap_bin=gap_bin,
        participant_signature=participants,
        supporting_blower_ids=("blower",),
        complete=True,
        appliance_profile="heat_pump",
    )


def _core_day_episode(
    index: int,
    *,
    outdoor_temperature_f: float | None,
    runtime_minutes: float,
    mode: str = "cooling",
    episode_kind: str = "setpoint_response",
    model_version: int = 2,
) -> HvacResponseEpisode:
    episode = _completed_episode(
        index,
        minutes_per_degree=runtime_minutes / 5.0,
        mode=mode,
    )
    changes = {
        "elapsed_minutes": runtime_minutes,
        "active_minutes": runtime_minutes,
        "outdoor_temperature_f": outdoor_temperature_f,
        "outdoor_temperature_minutes": (
            runtime_minutes if outdoor_temperature_f is not None else 0.0
        ),
        "episode_kind": episode_kind,
        "model_version": model_version,
    }
    if episode_kind == "thermostat_call":
        changes.update(
            start_temperature_f=75.8,
            target_temperature_f=75.2,
            latest_temperature_f=75.3,
            gap_bin="0-1F",
        )
    return replace(
        episode,
        **changes,
    )


def test_setpoint_episode_starts_with_capable_active_driver_and_one_degree_gap(
) -> None:
    current, completed = _advance(
        None,
        _observation(actual=78.0, target=72.0),
        active_minutes_delta=1.0,
    )

    assert completed is None
    assert current is not None
    assert current.mode == "cooling"
    assert current.gap_bin == "6-8F"
    assert current.active_minutes == 1.0
    assert current.temperature_entity_id == "sensor.downstairs_temperature"
    assert current.participant_signature == ("heat_pump",)
    assert current.supporting_blower_ids == ("blower",)

    for observation in (
        _observation(actual=None, target=72.0),
        _observation(actual=72.8, target=72.0, action=None),
    ):
        assert _advance(None, observation)[0] is None
    assert _advance(
        None,
        _observation(actual=78.0, target=72.0),
        driver_active=False,
    )[0] is None


def test_subdegree_thermostat_call_completes_when_action_ends() -> None:
    current, completed = _advance(
        None,
        _observation(actual=75.8, target=75.2),
        active_minutes_delta=1.0,
    )

    assert completed is None
    assert current is not None
    assert current.episode_kind == "thermostat_call"

    current, completed = _advance(
        current,
        _observation(actual=75.6, target=75.2),
        now=START + timedelta(minutes=10),
        active_minutes_delta=9.0,
    )

    assert current is not None
    assert completed is None

    current, completed = _advance(
        current,
        _observation(actual=75.3, target=75.2, action="idle"),
        now=START + timedelta(minutes=20),
        driver_active=False,
        active_minutes_delta=10.0,
    )

    assert current is None
    assert completed is not None
    assert completed.complete is True
    assert completed.active_minutes == 20.0
    assert completed.latest_temperature_f == 75.3
    assert episode_from_dict(episode_to_dict(completed)) == completed


def test_exact_tenth_degree_thermostat_call_starts() -> None:
    current, completed = _advance(
        None,
        _observation(actual=75.3, target=75.2),
    )

    assert current is not None
    assert current.episode_kind == "thermostat_call"
    assert completed is None


def test_subtenth_active_call_creates_excluded_date_marker() -> None:
    current, marker = _advance(
        None,
        _observation(actual=75.25, target=75.2),
    )

    assert current is None
    assert marker is not None
    assert marker.ended_at == START
    assert marker.complete is False
    assert marker.excluded_from_baseline is True


def test_nominal_one_degree_gap_starts_setpoint_response() -> None:
    current, completed = _advance(
        None,
        _observation(actual=64.1, target=63.1),
    )

    assert current is not None
    assert current.episode_kind == "setpoint_response"
    assert completed is None


def test_subdegree_thermostat_call_without_progress_is_excluded() -> None:
    current, _ = _advance(
        None,
        _observation(actual=75.8, target=75.2),
    )

    active, completed = _advance(
        current,
        _observation(actual=75.8, target=75.2, action="idle"),
        now=START + timedelta(minutes=10),
        driver_active=False,
        active_minutes_delta=10.0,
    )

    assert active is None
    assert completed is not None
    assert completed.complete is False
    assert completed.excluded_from_baseline is True


def test_subdegree_call_completes_when_action_disappears_and_driver_stops() -> None:
    current, _ = _advance(
        None,
        _observation(actual=75.8, target=75.2),
    )

    active, completed = _advance(
        current,
        _observation(actual=75.3, target=75.2, action=None),
        now=START + timedelta(minutes=10),
        driver_active=False,
        active_minutes_delta=10.0,
    )

    assert active is None
    assert completed is not None
    assert completed.complete is True


def test_temperature_source_change_excludes_the_active_episode() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))
    changed_source = replace(
        _observation(actual=77.0, target=72.0),
        temperature_entity_id="sensor.replacement_temperature",
    )

    active, excluded = _advance(
        current,
        changed_source,
        now=START + timedelta(minutes=5),
        active_minutes_delta=5.0,
    )

    assert active is None
    assert excluded is not None
    assert excluded.excluded_from_baseline is True


def test_appliance_profile_change_excludes_the_active_episode() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))

    active, excluded = _advance(
        current,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=5),
        active_minutes_delta=5.0,
        appliance_profile="electric_heat",
    )

    assert active is None
    assert excluded is not None
    assert excluded.excluded_from_baseline is True


def test_explicit_idle_action_does_not_start_an_episode() -> None:
    active, completed = _advance(
        None,
        _observation(actual=78.0, target=72.0, action="idle"),
    )

    assert active is None
    assert completed is None


@pytest.mark.parametrize(
    ("action", "actual", "target", "expected_mode"),
    [
        ("heating", 65.0, 70.0, "heating"),
        ("cooling", 78.0, 72.0, "cooling"),
        (None, 65.0, 70.0, "heating"),
        (None, 78.0, 72.0, "cooling"),
    ],
)
def test_heat_cool_observation_resolves_direction(
    action: str | None,
    actual: float,
    target: float,
    expected_mode: str,
) -> None:
    current, _ = _advance(
        None,
        _observation(
            actual=actual,
            target=target,
            mode="heat_cool",
            action=action,
        ),
    )

    assert current is not None
    assert current.mode == expected_mode


def test_cooling_episode_completes_within_half_degree_of_target() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))

    active, completed = _advance(
        current,
        _observation(actual=72.4, target=72.0),
        now=START + timedelta(minutes=36),
        active_minutes_delta=5.0,
    )

    assert active is None
    assert completed is not None
    assert completed.complete is True
    assert completed.ended_at == START + timedelta(minutes=36)
    assert completed.elapsed_minutes == 36.0
    assert completed.latest_temperature_f == 72.4


def test_first_driver_off_interval_counts_toward_completed_episode() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))

    active, completed = _advance(
        current,
        _observation(actual=72.0, target=72.0, action="idle"),
        now=START + timedelta(minutes=20),
        driver_active=False,
        active_minutes_delta=20.0,
    )

    assert active is None
    assert completed is not None
    assert completed.active_minutes == 20.0
    assert episode_to_dict(completed)["active_minutes"] == 20.0


def test_episode_tracks_active_runtime_weighted_outdoor_temperature() -> None:
    current, _ = _advance(
        None,
        _observation(actual=78.0, target=72.0),
        active_minutes_delta=10.0,
    )

    updated, _ = advance_episode(
        current,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=30),
        circuit_id="heat_pump",
        appliance_profile="heat_pump",
        driver_active=True,
        active_minutes_delta=20.0,
        participant_signature=("heat_pump",),
        supporting_blower_ids=("blower",),
        environmental_context={**HOT_CONTEXT, "outdoor_temperature_f": 80.0},
    )

    assert updated is not None
    assert updated.outdoor_temperature_minutes == 30.0
    assert updated.outdoor_temperature_f == pytest.approx(84.0)


def test_actionless_range_thermostat_completes_at_active_boundary() -> None:
    range_capabilities = (
        "current_temperature",
        "target_temp_high",
        "target_temp_low",
    )
    current, _ = _advance(
        None,
        replace(
            _observation(
                actual=65.0,
                target=68.0,
                mode="heat_cool",
                action=None,
            ),
            available_capabilities=range_capabilities,
        ),
    )

    active, completed = _advance(
        current,
        replace(
            _observation(
                actual=68.2,
                target=None,
                mode="heat_cool",
                action=None,
            ),
            available_capabilities=range_capabilities,
        ),
        now=START + timedelta(minutes=20),
        driver_active=False,
        active_minutes_delta=20.0,
    )

    assert active is None
    assert completed is not None
    assert completed.complete is True
    assert completed.mode == "heating"


def test_inactive_intervals_are_not_charged_when_driver_restarts() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))
    inactive, _ = _advance(
        current,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=10),
        driver_active=False,
        active_minutes_delta=10.0,
    )
    still_inactive, _ = _advance(
        inactive,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=20),
        driver_active=False,
        active_minutes_delta=10.0,
    )

    restarted, _ = _advance(
        still_inactive,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=30),
        driver_active=True,
        active_minutes_delta=10.0,
    )

    assert restarted is not None
    assert restarted.active_minutes == 10.0


def test_target_change_inactivity_and_timeout_exclude_episode() -> None:
    current, _ = _advance(None, _observation(actual=78.0, target=72.0))

    active, changed = _advance(
        current,
        _observation(actual=77.0, target=70.0),
        now=START + timedelta(minutes=5),
    )
    assert active is None
    assert changed is not None
    assert changed.complete is False
    assert changed.excluded_from_baseline is True

    current, _ = _advance(None, _observation(actual=78.0, target=72.0))
    inactive, completed = _advance(
        current,
        _observation(actual=77.0, target=72.0),
        now=START + timedelta(minutes=10),
        driver_active=False,
    )
    assert inactive is not None
    assert completed is None
    active, timed_out = _advance(
        inactive,
        _observation(actual=76.5, target=72.0),
        now=START + timedelta(minutes=40),
        driver_active=False,
    )
    assert active is None
    assert timed_out is not None
    assert timed_out.excluded_from_baseline is True

    current, _ = _advance(None, _observation(actual=78.0, target=72.0))
    active, timed_out = _advance(
        current,
        _observation(actual=74.0, target=72.0),
        now=START + timedelta(hours=8),
    )
    assert active is None
    assert timed_out is not None
    assert timed_out.excluded_from_baseline is True


def test_episode_serialization_round_trip_rejects_invalid_records() -> None:
    episode = _completed_episode(0, minutes_per_degree=10.0)
    excluded = replace(episode, excluded_from_baseline=True)
    legacy_payload = episode_to_dict(episode)
    legacy_payload.pop("episode_kind")
    previous_model_payload = episode_to_dict(episode)
    previous_model_payload.pop("model_version")

    assert episode_from_dict(episode_to_dict(episode)) == episode
    assert episode_from_dict(episode_to_dict(excluded)) == excluded
    assert episode_from_dict(legacy_payload) == episode
    assert episode_from_dict(previous_model_payload).model_version == 1
    assert episode_from_dict({**episode_to_dict(episode), "complete": False}) is None
    assert (
        episode_from_dict(
            {**episode_to_dict(episode), "elapsed_minutes": float("nan")}
        )
        is None
    )


def test_efficiency_aggregates_calls_by_local_day_before_learning() -> None:
    episodes = [
        replace(
            _core_day_episode(
                index,
                outdoor_temperature_f=80.0,
                runtime_minutes=10.0,
                episode_kind="thermostat_call",
            ),
            started_at=START + timedelta(days=index, hours=hour),
            ended_at=START + timedelta(days=index, hours=hour, minutes=10),
        )
        for index in range(30)
        for hour in (0, 4, 8)
    ]

    evaluation = evaluate_efficiency(
        episodes,
        threshold_pct=25.0,
        time_zone="America/New_York",
    )

    assert evaluation.status == "provisional"
    assert evaluation.reference_count == 30
    assert evaluation.recent_count == 0
    assert evaluation.score is None
    assert evaluation.finding is None


def test_efficiency_requires_complete_outdoor_temperature_coverage() -> None:
    episodes = [
        _core_day_episode(
            index,
            outdoor_temperature_f=None,
            runtime_minutes=45.0,
        )
        for index in range(60)
    ]

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "no_weather_data"
    assert evaluation.score is None
    assert evaluation.finding is None


def test_efficiency_rejects_partially_covered_weather_days() -> None:
    episodes = _weather_normalized_history()
    episodes[0] = replace(
        episodes[0],
        outdoor_temperature_minutes=episodes[0].active_minutes - 1.0,
    )

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "provisional"
    assert evaluation.reference_count == 50
    assert evaluation.recent_count == 4


def test_efficiency_ignores_legacy_episode_model_records() -> None:
    episodes = [
        _core_day_episode(
            index,
            outdoor_temperature_f=75.0 + 5.0 * (index % 5),
            runtime_minutes=30.0 + 10.0 * (index % 5),
            model_version=1,
        )
        for index in range(60)
    ]

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "no_data"
    assert evaluation.reference_count == 0


def _weather_normalized_history(
    recent_multipliers: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0),
) -> list[HvacResponseEpisode]:
    episodes = []
    for index in range(55):
        outdoor = 75.0 + 5.0 * (index % 5)
        expected_runtime = 30.0 + 2.0 * (outdoor - 75.0)
        multiplier = recent_multipliers[index - 50] if index >= 50 else 1.0
        episodes.append(
            _core_day_episode(
                index,
                outdoor_temperature_f=outdoor,
                runtime_minutes=expected_runtime * multiplier,
            )
        )
    return episodes


def test_weather_normalization_does_not_flag_hotter_normal_days() -> None:
    episodes = _weather_normalized_history()
    episodes[-5:] = [
        replace(
            episode,
            outdoor_temperature_f=95.0,
            outdoor_temperature_minutes=70.0,
            elapsed_minutes=70.0,
            active_minutes=70.0,
            ended_at=episode.started_at + timedelta(minutes=70),
        )
        for episode in episodes[-5:]
    ]

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "ready"
    assert evaluation.finding is None
    assert evaluation.score == pytest.approx(100.0)
    assert evaluation.reference_count == 50
    assert evaluation.recent_count == 5
    assert evaluation.baseline_runtime_minutes == pytest.approx(70.0)
    assert evaluation.recent_runtime_minutes == pytest.approx(70.0)


def test_efficiency_rejects_weather_extrapolation_beyond_reference_loads() -> None:
    episodes = _weather_normalized_history()
    episodes[-5:] = [
        replace(
            episode,
            outdoor_temperature_f=70.0,
            outdoor_temperature_minutes=30.0,
            elapsed_minutes=30.0,
            active_minutes=30.0,
            ended_at=episode.started_at + timedelta(minutes=30),
        )
        for episode in episodes[-5:]
    ]

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "provisional"
    assert evaluation.finding is None


def test_efficiency_requires_three_abnormal_days_in_recent_five() -> None:
    two_slow = evaluate_efficiency(
        _weather_normalized_history((1.3, 1.3, 1.0, 1.0, 1.0)),
        threshold_pct=25.0,
    )
    three_slow = evaluate_efficiency(
        _weather_normalized_history((1.3, 1.3, 1.3, 1.0, 1.0)),
        threshold_pct=25.0,
    )

    assert two_slow.finding is None
    assert three_slow.finding == "slower"
    assert three_slow.context["abnormal_recent_days"] == 3
    assert three_slow.context["normal_streak"] == 2


def test_late_weather_diversity_can_complete_the_reference_window() -> None:
    episodes = [
        _core_day_episode(
            index,
            outdoor_temperature_f=(
                75.0 if index < 50 else 80.0 + 5.0 * (index % 3)
            ),
            runtime_minutes=(
                30.0
                if index < 50
                else 30.0 + 2.0 * (5.0 + 5.0 * (index % 3))
            ),
        )
        for index in range(60)
    ]

    compacted = compact_completed_core_days(
        episodes,
        time_zone="UTC",
        current_date=(START + timedelta(days=61)).date(),
        retention_days=45,
    )
    evaluation = evaluate_efficiency(compacted, threshold_pct=25.0)

    assert len(compacted) == 55
    assert evaluation.status == "ready"
    assert evaluation.context["outdoor_temperature_bin_count"] >= 3


def test_lightweight_retention_uses_twelve_reference_core_days() -> None:
    episodes = _weather_normalized_history()[:17]

    evaluation = evaluate_efficiency(
        episodes,
        threshold_pct=25.0,
        retention_days=18,
    )

    assert evaluation.status == "ready"
    assert evaluation.reference_count == 12
    assert evaluation.recent_count == 5
    assert evaluation.required_reference_count == 12
    assert evaluation.finding is None


def test_efficiency_excludes_the_current_local_day() -> None:
    episodes = _weather_normalized_history()

    evaluation = evaluate_efficiency(
        episodes,
        threshold_pct=25.0,
        current_date=episodes[-1].started_at.date(),
    )

    assert evaluation.status == "provisional"
    assert evaluation.reference_count == 50
    assert evaluation.recent_count == 4


def test_completed_calls_compact_to_one_record_per_core_day() -> None:
    calls = [
        replace(
            _core_day_episode(
                day,
                outdoor_temperature_f=75.0 + 5.0 * (day % 5),
                runtime_minutes=10.0,
                episode_kind="thermostat_call",
            ),
            started_at=START + timedelta(days=day, hours=hour),
            ended_at=START + timedelta(days=day, hours=hour, minutes=10),
        )
        for day in range(56)
        for hour in (0, 2, 4, 6, 8)
    ]

    compacted = compact_completed_core_days(
        calls,
        time_zone="UTC",
        current_date=(START + timedelta(days=57)).date(),
        retention_days=45,
    )

    assert len(compacted) == 55
    assert all(episode.episode_kind == "core_day" for episode in compacted)
    assert compacted[:50] == sorted(compacted, key=lambda item: item.started_at)[:50]
    assert compacted[-1].started_at == calls[-5].started_at
    assert compact_completed_core_days(
        compacted,
        time_zone="UTC",
        current_date=(START + timedelta(days=57)).date(),
        retention_days=45,
    ) == compacted

    lightweight = compact_completed_core_days(
        calls,
        time_zone="UTC",
        current_date=(START + timedelta(days=57)).date(),
        retention_days=18,
    )
    assert len(lightweight) == 17
    assert lightweight[-5:] == compacted[-5:]


def test_incomplete_same_mode_call_disqualifies_core_day() -> None:
    calls = [
        replace(
            _core_day_episode(
                0,
                outdoor_temperature_f=90.0,
                runtime_minutes=10.0,
                episode_kind="thermostat_call",
            ),
            started_at=START + timedelta(hours=hour),
            ended_at=START + timedelta(hours=hour, minutes=10),
        )
        for hour in (0, 2, 4, 6)
    ]
    incomplete = replace(
        calls[-1],
        started_at=START + timedelta(hours=8),
        ended_at=START + timedelta(hours=8, minutes=10),
        complete=False,
        excluded_from_baseline=True,
    )

    compacted = compact_completed_core_days(
        [*calls, incomplete],
        time_zone="UTC",
        current_date=(START + timedelta(days=1)).date(),
        retention_days=45,
    )

    assert compacted == []


def test_compaction_bounds_multiple_equipment_contexts_per_stream() -> None:
    episodes = [
        replace(
            _core_day_episode(
                index,
                outdoor_temperature_f=75.0 + 5.0 * (index % 5),
                runtime_minutes=40.0,
            ),
            participant_signature=("heat_pump", ("old", "new")[index % 2]),
        )
        for index in range(112)
    ]

    compacted = compact_completed_core_days(
        episodes,
        time_zone="UTC",
        current_date=(START + timedelta(days=117)).date(),
        retention_days=45,
    )

    assert len(compacted) == 55
    assert {episode.participant_signature for episode in compacted} == {
        ("heat_pump", "new")
    }


def test_cross_midnight_call_disqualifies_every_touched_date() -> None:
    ending_day_calls = [
        replace(
            _core_day_episode(
                1,
                outdoor_temperature_f=90.0,
                runtime_minutes=10.0,
                episode_kind="thermostat_call",
            ),
            started_at=START + timedelta(days=1, hours=hour),
            ended_at=START + timedelta(days=1, hours=hour, minutes=10),
        )
        for hour in (2, 4, 6, 8)
    ]
    spanning = replace(
        ending_day_calls[0],
        started_at=START.replace(hour=23, minute=30),
        ended_at=(START + timedelta(days=1)).replace(hour=0, minute=10),
        elapsed_minutes=40.0,
        active_minutes=40.0,
        outdoor_temperature_minutes=40.0,
    )

    compacted = compact_completed_core_days(
        [spanning, *ending_day_calls],
        time_zone="UTC",
        current_date=(START + timedelta(days=2)).date(),
        retention_days=45,
    )

    assert compacted == []
