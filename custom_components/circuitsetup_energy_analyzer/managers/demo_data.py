from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from ..demo import (
    DEMO_HISTORY_SEED_VERSION,
    demo_baseline,
    demo_circuit_key,
    demo_prior_usage,
    demo_today_usage,
    is_demo_config,
)
from ..local_time import local_date, local_day_time
from ..models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    EventType,
    PowerFlowMode,
)
from ..profiles import get_profile_definition
from ..standby import STANDBY_SAMPLE_FORMAT

if TYPE_CHECKING:
    from ..processors.base import ProcessingContext
    from ..standby import StandbySettings
    from ..usage import EnergyUsageSettings


_DEMO_WEATHER_CONTEXT_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)


class DemoDataSeeder:
    """Seed representative history for bundled demo circuits."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def seed_event_history(
        self,
        config: CircuitConfig,
        now: datetime,
    ) -> None:
        if not is_demo_config(config):
            return

        store_data = self._coordinator.store_data
        profile = get_profile_definition(config.appliance_profile)
        minimum_starts = max(profile.minimum_cycles, 8)
        circuit_events = [
            event
            for event in store_data.events
            if event.circuit_id == config.circuit_id
        ]
        start_count = sum(
            1 for event in circuit_events if event.event_type is EventType.START
        )
        oldest = min((event.timestamp for event in circuit_events), default=None)
        mature_by_count = start_count >= minimum_starts
        mature_by_age = oldest is not None and now - oldest >= timedelta(
            days=profile.minimum_learning_days,
        )
        if mature_by_count and mature_by_age:
            return

        store_data.events = [
            event
            for event in store_data.events
            if not (
                event.circuit_id == config.circuit_id
                and event.features.get("demo_seed_version")
                == DEMO_HISTORY_SEED_VERSION
            )
        ]
        base = now - timedelta(days=max(profile.minimum_learning_days, 7), hours=1)
        seeded: list[CircuitEvent] = []
        for index in range(minimum_starts):
            start = base + timedelta(hours=index * 4)
            stop = start + timedelta(minutes=45)
            seeded.append(
                CircuitEvent(
                    timestamp=start,
                    circuit_id=config.circuit_id,
                    event_type=EventType.START,
                    features={
                        "demo_seed_version": DEMO_HISTORY_SEED_VERSION,
                        "cycle_index": index,
                    },
                )
            )
            seeded.append(
                CircuitEvent(
                    timestamp=stop,
                    circuit_id=config.circuit_id,
                    event_type=EventType.STOP,
                    features={
                        "demo_seed_version": DEMO_HISTORY_SEED_VERSION,
                        "cycle_index": index,
                    },
                )
            )
        store_data.events.extend(seeded)
        self._mark_store_dirty()

    def seed_power_quality_baselines(
        self,
        config: CircuitConfig,
        features: Mapping[str, float],
    ) -> None:
        if not is_demo_config(config):
            return

        changed = False
        store_data = self._coordinator.store_data
        for feature, value in features.items():
            key = _baseline_key(config.circuit_id, feature)
            if key in store_data.baselines:
                continue
            store_data.baselines[key] = demo_baseline(feature, value)
            changed = True
        if changed:
            self._mark_store_dirty()

    def seed_energy_usage_history(
        self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
        settings: EnergyUsageSettings,
    ) -> None:
        if not is_demo_config(config) or sample.energy is None:
            return

        energy_kwh = _float_or_none(sample.energy)
        if energy_kwh is None or energy_kwh <= 0.0:
            return

        window_days = max(int(settings.window_days), 1)
        time_zone = self._coordinator.context_builder.time_zone()
        today_date = _ha_local_date(now, time_zone)
        today = today_date.isoformat()
        history = self._coordinator.store_data.energy_usage_by_circuit.setdefault(
            config.circuit_id,
            {},
        )
        seed_version = history.get("_demo_seed_version")
        known_demo_history = (
            isinstance(seed_version, int)
            and not isinstance(seed_version, bool)
            and 1 <= seed_version <= DEMO_HISTORY_SEED_VERSION
        )
        if history and not known_demo_history:
            return

        days = history.get("days")
        complete_prior_day_count = (
            sum(
                1
                for day in days
                if (
                    isinstance(day, Mapping)
                    and str(day.get("date", "")) < today
                    and day.get("complete") is True
                )
            )
            if isinstance(days, list)
            else 0
        )
        if (
            seed_version == DEMO_HISTORY_SEED_VERSION
            and complete_prior_day_count >= window_days
            and _float_or_none(history.get("last_energy_kwh")) is not None
        ):
            return

        circuit_key = demo_circuit_key(config)
        prior_usage = demo_prior_usage(circuit_key, window_days)
        today_usage = demo_today_usage(circuit_key, energy_kwh)
        start_date = today_date - timedelta(days=window_days)
        history["days"] = [
            {
                "date": (start_date + timedelta(days=index)).isoformat(),
                "usage_kwh": round(float(usage), 3),
                "complete": True,
            }
            for index, usage in enumerate(prior_usage)
        ]
        history["last_energy_kwh"] = round(max(energy_kwh - today_usage, 0.0), 3)
        history["last_sample_at"] = (now - timedelta(minutes=5)).isoformat()
        history["_demo_seed_version"] = DEMO_HISTORY_SEED_VERSION
        history["_demo_seed_date"] = today
        self._mark_store_dirty()

    def seed_weather_context_history(
        self,
        config: CircuitConfig,
        now: datetime,
        *,
        outdoor_temperature: float | None,
    ) -> None:
        if (
            not is_demo_config(config)
            or config.appliance_profile not in _DEMO_WEATHER_CONTEXT_PROFILES
            or outdoor_temperature is None
        ):
            return

        time_zone = self._coordinator.context_builder.time_zone()
        raw_history = (
            self._coordinator.store_data.weather_context_history_by_circuit.setdefault(
                config.circuit_id,
                [],
            )
        )
        comparable_count = 0
        for sample in raw_history:
            if not isinstance(sample, Mapping):
                continue
            sample_time = _datetime_or_none(sample.get("timestamp"))
            sample_temp = _float_or_none(sample.get("temperature"))
            if (
                sample_time is not None
                and _ha_local_date(sample_time, time_zone)
                < _ha_local_date(now, time_zone)
                and sample_temp is not None
                and abs(sample_temp - outdoor_temperature) <= 3.0
            ):
                comparable_count += 1
        if comparable_count >= 3:
            return

        current_date = _ha_local_date(now, time_zone)
        self._coordinator.store_data.weather_context_history_by_circuit[
            config.circuit_id
        ] = [
            {
                "timestamp": local_day_time(
                    current_date - timedelta(days=7 - index),
                    time(12, 0),
                    time_zone,
                ).isoformat(),
                "temperature": round(float(outdoor_temperature) + offset, 3),
                "runtime_minutes": runtime,
                "duty_cycle_percent": duty,
                "energy_kwh": round(runtime * 0.055, 3),
                "start_count": 3 + (index % 2),
                "_demo_seed_version": DEMO_HISTORY_SEED_VERSION,
            }
            for index, (offset, runtime, duty) in enumerate(
                (
                    (-2.0, 78.0, 12.5),
                    (-1.0, 84.0, 13.8),
                    (0.0, 92.0, 15.0),
                    (1.0, 97.0, 15.7),
                    (2.0, 104.0, 16.9),
                )
            )
        ]
        self._mark_store_dirty()

    def seed_standby_history(
        self,
        config: CircuitConfig,
        sample: Any,
        context: ProcessingContext,
        settings: StandbySettings,
    ) -> None:
        if not is_demo_config(config):
            return

        power_w = _demand_power_w(sample)
        if power_w is None:
            return

        min_samples = max(int(settings.min_samples), 1)
        history = self._coordinator.store_data.standby_by_circuit.setdefault(
            config.circuit_id,
            {},
        )
        samples = history.get("samples")
        cutoff = context.now - timedelta(hours=max(int(settings.window_hours), 1))
        existing_count = (
            sum(
                1
                for raw_sample in samples
                if isinstance(raw_sample, Mapping)
                and (
                    sample_time := _datetime_or_none(raw_sample.get("timestamp"))
                )
                is not None
                and sample_time >= cutoff
            )
            if isinstance(samples, list)
            else 0
        )
        if existing_count >= min_samples:
            return

        window_hours = max(int(settings.window_hours), 1)
        sample_spacing_minutes = max(
            int((window_hours * 60) / max(min_samples + 1, 2)),
            5,
        )
        low_power_w = max(float(settings.standby_threshold_w) + 4.0, power_w * 0.04)
        seeded: list[dict[str, Any]] = []
        for index in range(max(min_samples - 1, 0)):
            timestamp = context.now - timedelta(
                minutes=sample_spacing_minutes * (min_samples - index),
            )
            seeded.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "real_power_w": round(
                        low_power_w + ((index % 4) * 1.5),
                        3,
                    ),
                    "_demo_seed_version": DEMO_HISTORY_SEED_VERSION,
                }
            )
        history["samples"] = seeded
        history["standby_sample_format"] = STANDBY_SAMPLE_FORMAT
        self._mark_store_dirty()

    def _mark_store_dirty(self) -> None:
        self._coordinator.store_persistence.mark_dirty()


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _ha_local_date(value: datetime, time_zone: str | None) -> Any:
    if time_zone is None or value.tzinfo is None:
        return value.date()
    return local_date(value, time_zone)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _demand_power_w(sample: Any) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    if power_flow is PowerFlowMode.MAINS_NET:
        return max(float(power), 0.0)
    return max(float(power), 0.0)
