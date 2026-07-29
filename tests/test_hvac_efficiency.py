from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.hvac_efficiency import (
    HvacResponseEpisode,
    ThermostatObservation,
    advance_episode,
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
) -> tuple[HvacResponseEpisode | None, HvacResponseEpisode | None]:
    return advance_episode(
        current,
        observation,
        now=now,
        circuit_id="heat_pump",
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
    )


def test_episode_starts_only_with_capable_active_driver_and_one_degree_gap() -> None:
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
    assert current.participant_signature == ("heat_pump",)
    assert current.supporting_blower_ids == ("blower",)

    for observation in (
        _observation(actual=None, target=72.0),
        _observation(actual=72.8, target=72.0),
    ):
        assert _advance(None, observation)[0] is None
    assert _advance(
        None,
        _observation(actual=78.0, target=72.0),
        driver_active=False,
    )[0] is None


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

    assert episode_from_dict(episode_to_dict(episode)) == episode
    assert episode_from_dict(episode_to_dict(excluded)) == excluded
    assert episode_from_dict({**episode_to_dict(episode), "complete": False}) is None
    assert (
        episode_from_dict(
            {**episode_to_dict(episode), "elapsed_minutes": float("nan")}
        )
        is None
    )


@pytest.mark.parametrize(
    ("recent_minutes_per_degree", "finding", "score", "change"),
    [
        (12.5, "slower", 80.0, 0.25),
        (7.5, "faster", 133.33333333333334, -0.25),
    ],
)
def test_efficiency_reports_exact_25_percent_boundaries(
    recent_minutes_per_degree: float,
    finding: str,
    score: float,
    change: float,
) -> None:
    evaluation = evaluate_efficiency(
        [
            *[
                _completed_episode(index, minutes_per_degree=10.0)
                for index in range(9)
            ],
            *[
                _completed_episode(
                    index,
                    minutes_per_degree=recent_minutes_per_degree,
                )
                for index in range(9, 12)
            ],
        ],
        threshold_pct=25.0,
    )

    assert evaluation.status == "ready"
    assert evaluation.finding == finding
    assert evaluation.change_ratio == pytest.approx(change)
    assert evaluation.score == pytest.approx(score)
    assert evaluation.reference_count == 9
    assert evaluation.recent_count == 3


def test_efficiency_uses_comparable_medians_and_ignores_excluded_records() -> None:
    episodes = [
        *[_completed_episode(index, minutes_per_degree=10.0) for index in range(9)],
        replace(
            _completed_episode(9, minutes_per_degree=99.0),
            excluded_from_baseline=True,
        ),
        _completed_episode(10, minutes_per_degree=12.0),
        _completed_episode(11, minutes_per_degree=12.0),
        _completed_episode(12, minutes_per_degree=120.0),
        _completed_episode(
            13,
            minutes_per_degree=1.0,
            thermostat="climate.upstairs",
        ),
        _completed_episode(14, minutes_per_degree=1.0, mode="heating"),
        _completed_episode(
            15,
            minutes_per_degree=1.0,
            temperature_bin="mild",
        ),
        _completed_episode(16, minutes_per_degree=1.0, gap_bin="6-8F"),
        _completed_episode(
            17,
            minutes_per_degree=1.0,
            participants=("heat_pump", "electric_heat"),
        ),
        replace(
            _completed_episode(18, minutes_per_degree=1.0),
            complete=False,
        ),
    ]

    evaluation = evaluate_efficiency(episodes, threshold_pct=25.0)

    assert evaluation.status == "ready"
    assert evaluation.recent_minutes_per_degree == pytest.approx(12.0)
    assert evaluation.baseline_minutes_per_degree == pytest.approx(10.0)
    assert evaluation.finding is None
    assert evaluation.context["thermostat_entity_id"] == "climate.downstairs"


def test_efficiency_returns_bounded_score_and_learning_status() -> None:
    learning = evaluate_efficiency(
        [_completed_episode(0, minutes_per_degree=10.0)],
        threshold_pct=25.0,
    )
    assert learning.status == "learning"
    assert learning.score is None

    ready = evaluate_efficiency(
        [
            *[_completed_episode(index, minutes_per_degree=10.0) for index in range(9)],
            *[
                _completed_episode(index, minutes_per_degree=1.0)
                for index in range(9, 12)
            ],
        ],
        threshold_pct=25.0,
    )
    assert ready.score == 200.0


def test_persistent_response_change_does_not_age_into_reference_baseline() -> None:
    evaluation = evaluate_efficiency(
        [
            *[_completed_episode(index, minutes_per_degree=10.0) for index in range(9)],
            *[
                _completed_episode(index, minutes_per_degree=12.5)
                for index in range(9, 21)
            ],
        ],
        threshold_pct=25.0,
    )

    assert evaluation.reference_count == 9
    assert evaluation.baseline_minutes_per_degree == pytest.approx(10.0)
    assert evaluation.recent_minutes_per_degree == pytest.approx(12.5)
    assert evaluation.finding == "slower"
