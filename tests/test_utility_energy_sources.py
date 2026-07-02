from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.managers import (
    utility_energy_sources,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    SensorRef,
    SensorRole,
)

UtilityEnergySourceManager = utility_energy_sources.UtilityEnergySourceManager


class _FakeStates:
    def __init__(self, states: dict[str, tuple[str, str]]) -> None:
        self._states = states

    def get(self, entity_id: str) -> Any:
        if entity_id not in self._states:
            return None
        state, unit = self._states[entity_id]
        return SimpleNamespace(
            state=state,
            attributes={"unit_of_measurement": unit},
        )


def _coordinator(
    *,
    states: dict[str, tuple[str, str]] | None = None,
    configs: tuple[CircuitConfig, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        hass=SimpleNamespace(states=_FakeStates(states or {}), data={}),
        circuit_configs=configs,
    )


def test_energy_entity_reader_normalizes_units_and_skips_invalid_states() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    manager = UtilityEnergySourceManager(
        _coordinator(
            states={
                "sensor.kwh": ("12.3456", "kWh"),
                "sensor.wh": ("1500", "Wh"),
                "sensor.mwh": ("0.25", "MWh"),
                "sensor.bad": ("unavailable", "kWh"),
            }
        )
    )

    assert manager.energy_kwh_for_entity("sensor.kwh", now) == 12.346
    assert manager.energy_kwh_for_entity("sensor.wh", now) == 1.5
    assert manager.energy_kwh_for_entity("sensor.mwh", now) == 250.0
    assert manager.energy_kwh_for_entity("sensor.bad", now) is None
    assert manager.energy_kwh_sum_for_entities(
        ("sensor.kwh", "sensor.bad", "sensor.wh"),
        now,
    ) == (13.846, ("sensor.kwh", "sensor.wh"))


def test_load_energy_entity_ids_for_sum_excludes_mains_generation_and_target() -> None:
    configs = (
        CircuitConfig(
            circuit_id="mains",
            name="Mains",
            appliance_profile=ApplianceProfile.MAINS_NILM,
            mode=CircuitMode.MAINS_NILM,
            sensors=(
                SensorRef(
                    entity_id="sensor.mains_energy",
                    role=SensorRole.ENERGY,
                ),
            ),
        ),
        CircuitConfig(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef(
                    entity_id="sensor.fridge_energy",
                    role=SensorRole.ENERGY,
                ),
            ),
        ),
        CircuitConfig(
            circuit_id="solar",
            name="Solar",
            appliance_profile=ApplianceProfile.SOLAR_INVERTER,
            mode=CircuitMode.SINGLE_PHASE,
            power_flow=PowerFlowMode.GENERATION,
            sensors=(
                SensorRef(
                    entity_id="sensor.solar_energy",
                    role=SensorRole.ENERGY,
                ),
            ),
        ),
    )
    manager = UtilityEnergySourceManager(_coordinator(configs=configs))

    assert manager.load_energy_entity_ids_for_sum("mains") == (
        "sensor.fridge_energy",
    )
    assert manager.load_energy_entity_ids_for_sum("fridge") == ()


@pytest.mark.asyncio
async def test_recorder_statistics_use_recorder_executor() -> None:
    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    recorder_jobs: list[tuple[object, tuple[object, ...]]] = []

    def fake_statistics_during_period(
        hass: object,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str],
        types: set[str],
    ) -> dict[str, list[dict[str, float]]]:
        del hass, start_time, end_time, statistic_ids, period, units, types
        return {"sensor.energy": [{"sum": 12.3}]}

    class FakeRecorder:
        async def async_add_executor_job(self, target, *args):
            recorder_jobs.append((target, args))
            return target(*args)

    manager = UtilityEnergySourceManager(
        _coordinator(),
        statistics_during_period=fake_statistics_during_period,
        recorder_get_instance=lambda _hass: FakeRecorder(),
    )

    statistics = await manager.recorder_statistics_during_period(
        statistic_ids={"sensor.energy"},
        start_time=now - timedelta(days=1),
        end_time=now,
        period="day",
    )

    assert recorder_jobs
    target, args = recorder_jobs[0]
    assert target is fake_statistics_during_period
    assert args == (
        manager.hass,
        now - timedelta(days=1),
        now,
        {"sensor.energy"},
        "day",
        {"energy": "kWh"},
        {"change", "sum", "state"},
    )
    assert statistics == {"sensor.energy": [{"sum": 12.3}]}


@pytest.mark.asyncio
async def test_statistics_kwh_sum_for_entities_matches_requested_period() -> None:
    now = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    period_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 3, 0, 0, tzinfo=UTC)
    calls: list[dict[str, object]] = []

    def timestamp_ms(value: datetime) -> int:
        return int(value.timestamp() * 1000)

    def fake_statistics_during_period(
        hass: object,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str],
        types: set[str],
    ) -> dict[str, list[dict[str, float]]]:
        del hass, units, types
        calls.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "statistic_ids": statistic_ids,
                "period": period,
            }
        )
        return {
            "sensor.fridge_energy": [
                {
                    "start": timestamp_ms(period_start),
                    "end": timestamp_ms(period_end),
                    "change": 20.0,
                }
            ],
            "sensor.hvac_energy": [
                {
                    "start": timestamp_ms(period_start),
                    "end": timestamp_ms(period_end),
                    "change": 32.0,
                }
            ],
        }

    class FakeRecorder:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    manager = UtilityEnergySourceManager(
        _coordinator(),
        statistics_during_period=fake_statistics_during_period,
        recorder_get_instance=lambda _hass: FakeRecorder(),
    )

    result = await manager.statistics_kwh_sum_for_entities(
        ("sensor.fridge_energy", "sensor.hvac_energy"),
        now,
        "day",
        period_start,
        period_end,
    )

    assert result == (52.0, ("sensor.fridge_energy", "sensor.hvac_energy"))
    assert calls == [
        {
            "start_time": period_start,
            "end_time": period_end,
            "statistic_ids": {"sensor.fridge_energy", "sensor.hvac_energy"},
            "period": "day",
        }
    ]


@pytest.mark.asyncio
async def test_recorder_statistics_skip_generic_executor_fallback() -> None:
    generic_jobs: list[object] = []
    statistics_calls = 0

    def fake_statistics_during_period(*args, **kwargs):
        nonlocal statistics_calls
        del args, kwargs
        statistics_calls += 1
        return {"sensor.energy": [{"sum": 12.3}]}

    async def async_add_executor_job(target, *args):
        generic_jobs.append(target)
        return target(*args)

    manager = UtilityEnergySourceManager(
        SimpleNamespace(
            hass=SimpleNamespace(
                data={},
                states=_FakeStates({}),
                async_add_executor_job=async_add_executor_job,
            ),
            circuit_configs=(),
        ),
        statistics_during_period=fake_statistics_during_period,
        recorder_get_instance=lambda _hass: None,
    )

    statistics = await manager.recorder_statistics_during_period(
        statistic_ids={"sensor.energy"},
        start_time=datetime(2026, 6, 4, tzinfo=UTC),
        end_time=datetime(2026, 6, 5, tzinfo=UTC),
        period="day",
    )

    assert statistics == {}
    assert generic_jobs == []
    assert statistics_calls == 0
