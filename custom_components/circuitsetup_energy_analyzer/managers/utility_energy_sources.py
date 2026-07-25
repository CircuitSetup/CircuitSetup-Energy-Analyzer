from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from ..models import (
    ApplianceProfile,
    CircuitMode,
    PowerFlowMode,
    SensorRole,
)
from ..utility_comparison import (
    DEFAULT_UTILITY_STATISTIC_PERIOD,
    select_latest_statistics_energy,
    select_statistics_energy_for_period,
)

_LOGGER = logging.getLogger(__name__)
_UNSET = object()
UTILITY_STATISTICS_CACHE_INTERVAL = timedelta(minutes=15)

try:
    from homeassistant.components.recorder import (
        get_instance as _ha_recorder_get_instance,
    )
    from homeassistant.components.recorder.statistics import (
        statistics_during_period as _ha_statistics_during_period,
    )
except ModuleNotFoundError:
    _ha_recorder_get_instance = None
    _ha_statistics_during_period = None


class UtilityEnergySourceManager:
    """Read live and recorder-backed energy sources for utility comparison."""

    def __init__(
        self,
        coordinator: Any,
        *,
        statistics_during_period: Any = _UNSET,
        recorder_get_instance: Any = _UNSET,
    ) -> None:
        self._coordinator = coordinator
        self._statistics_during_period = (
            _ha_statistics_during_period
            if statistics_during_period is _UNSET
            else statistics_during_period
        )
        self._recorder_get_instance = (
            _ha_recorder_get_instance
            if recorder_get_instance is _UNSET
            else recorder_get_instance
        )
        self._statistics_cache: dict[
            tuple[Any, ...],
            tuple[datetime, Any],
        ] = {}

    @property
    def hass(self) -> Any:
        return self._coordinator.hass

    def energy_kwh_sum_for_entities(
        self,
        entity_ids: Iterable[str],
        now: datetime,
    ) -> tuple[float | None, tuple[str, ...]]:
        values: list[float] = []
        valid_entity_ids: list[str] = []
        for entity_id in entity_ids:
            value = self.energy_kwh_for_entity(entity_id, now)
            if value is None:
                continue
            values.append(value)
            valid_entity_ids.append(entity_id)
        if not values:
            return None, ()
        return round(sum(values), 3), tuple(valid_entity_ids)

    def energy_kwh_for_entity(
        self,
        entity_id: str,
        now: datetime,
    ) -> float | None:
        del now
        if not entity_id:
            return None
        hass_states = getattr(self.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return None
        raw_state = get_state(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip()
        if state.lower() in {"unknown", "unavailable", ""}:
            return None
        try:
            value = float(state)
        except ValueError:
            return None
        attributes = getattr(raw_state, "attributes", {}) or {}
        unit = attributes.get("unit_of_measurement")
        return _energy_value_kwh(value, unit)

    async def statistics_kwh_for_id(
        self,
        statistic_id: str,
        now: datetime,
        period: str,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Any:
        if not statistic_id:
            return select_latest_statistics_energy("", {}, now)
        normalized_period = _utility_statistic_period_value(period)
        cache_key = (
            "single",
            statistic_id,
            normalized_period,
            start_time,
            end_time,
        )
        cached = self._cached_statistics_value(cache_key, now)
        if cached is not _UNSET:
            return cached
        statistics = await self.recorder_statistics_during_period(
            statistic_ids={statistic_id},
            start_time=start_time
            or _statistics_lookback_start(now, normalized_period),
            end_time=end_time or now,
            period=normalized_period,
        )
        reading = select_latest_statistics_energy(statistic_id, statistics, now)
        self._statistics_cache[cache_key] = (now, reading)
        return reading

    async def statistics_kwh_sum_for_entities(
        self,
        entity_ids: Iterable[str],
        now: datetime,
        period: str,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[float | None, tuple[str, ...]]:
        ids = tuple(entity_id for entity_id in entity_ids if entity_id)
        if not ids:
            return None, ()
        normalized_period = _utility_statistic_period_value(period)
        cache_key = (
            "sum",
            tuple(sorted(ids)),
            normalized_period,
            start_time,
            end_time,
        )
        cached = self._cached_statistics_value(cache_key, now)
        if cached is not _UNSET:
            return cached
        statistics = await self.recorder_statistics_during_period(
            statistic_ids=set(ids),
            start_time=start_time,
            end_time=end_time,
            period=normalized_period,
        )
        values: list[float] = []
        valid_entity_ids: list[str] = []
        for entity_id in ids:
            reading = select_statistics_energy_for_period(
                entity_id,
                statistics,
                now,
                period_start=start_time,
                period_end=end_time,
            )
            if reading.energy_kwh is None:
                continue
            values.append(reading.energy_kwh)
            valid_entity_ids.append(entity_id)
        if not values:
            result = (None, ())
        else:
            result = (round(sum(values), 3), tuple(valid_entity_ids))
        self._statistics_cache[cache_key] = (now, result)
        return result

    async def recorder_statistics_during_period(
        self,
        *,
        statistic_ids: set[str],
        start_time: datetime,
        end_time: datetime | None,
        period: str,
    ) -> dict[str, list[dict[str, Any]]]:
        if self._statistics_during_period is None or not statistic_ids:
            return {}

        normalized_period = _utility_statistic_period_value(period)

        try:
            return await _async_recorder_executor_job(
                self.hass,
                self._recorder_get_instance,
                self._statistics_during_period,
                self.hass,
                start_time,
                end_time,
                statistic_ids,
                normalized_period,
                {"energy": "kWh"},
                {"change", "sum", "state"},
            )
        except Exception as err:
            _LOGGER.debug(
                "Recorder statistics unavailable for %s: %s",
                sorted(statistic_ids),
                err,
            )
            return {}

    def load_energy_entity_ids_for_sum(self, circuit_id: str) -> tuple[str, ...]:
        entity_ids: list[str] = []
        for config in self._coordinator.circuit_configs:
            if config.circuit_id == circuit_id:
                continue
            if (
                config.mode is CircuitMode.MAINS_NILM
                or config.appliance_profile is ApplianceProfile.MAINS_NILM
            ):
                continue
            if (
                config.power_flow is PowerFlowMode.GENERATION
                or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
            ):
                continue
            entity_ids.extend(
                sensor.entity_id
                for sensor in config.sensors
                if sensor.role is SensorRole.ENERGY
            )
        return tuple(entity_ids)

    def _cached_statistics_value(
        self,
        key: tuple[Any, ...],
        now: datetime,
    ) -> Any:
        cached = self._statistics_cache.get(key)
        if cached is None:
            return _UNSET
        cached_at, value = cached
        if (
            cached_at <= now
            and now - cached_at < UTILITY_STATISTICS_CACHE_INTERVAL
        ):
            return value
        self._statistics_cache.pop(key, None)
        return _UNSET


def _utility_statistic_period_value(value: Any) -> str:
    normalized = str(value or DEFAULT_UTILITY_STATISTIC_PERIOD).strip().lower()
    if normalized not in {"hour", "day", "month"}:
        return DEFAULT_UTILITY_STATISTIC_PERIOD
    return normalized


def _statistics_lookback_start(now: datetime, period: str) -> datetime:
    if period == "hour":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=400)
    return now - timedelta(days=45)


def _energy_value_kwh(value: float, unit: Any) -> float:
    normalized = str(unit or "kWh").strip().lower()
    if normalized == "wh":
        return round(value / 1000.0, 3)
    if normalized == "mwh":
        return round(value * 1000.0, 3)
    return round(value, 3)


async def _async_recorder_executor_job(
    hass: Any,
    recorder_get_instance: Any,
    target: Any,
    *args: Any,
) -> Any:
    if recorder_get_instance is not None:
        try:
            recorder = recorder_get_instance(hass)
        except Exception:
            recorder = None
        add_recorder_job = getattr(recorder, "async_add_executor_job", None)
        if callable(add_recorder_job):
            return await add_recorder_job(target, *args)

    raise RuntimeError("recorder executor is not available")
