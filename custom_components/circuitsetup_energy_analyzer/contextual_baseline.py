from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .baseline import build_baseline
from .models import ApplianceProfile, CircuitConfig, PowerFlowMode
from .normalize import NormalizedCircuitSample

FALLBACK_SPECIFICITY_WEIGHT = {
    "exact_context": 1.0,
    "temperature_context": 0.85,
    "seasonal_context": 0.75,
    "time_context": 0.75,
    "profile_context": 0.7,
    "global_circuit": 0.65,
    "global_profile": 0.6,
}

DAILY_ENERGY_FEATURE = "daily_energy_kwh"


@dataclass(frozen=True, slots=True)
class ContextDimension:
    """One normalized contextual dimension."""

    name: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_token(self.name))
        object.__setattr__(self, "value", _normalize_token(self.value))


@dataclass(frozen=True, slots=True)
class ContextKey:
    """Stable set of contextual dimensions."""

    dimensions: tuple[ContextDimension, ...]

    def __post_init__(self) -> None:
        normalized = {
            dimension.name: dimension.value
            for dimension in self.dimensions
            if dimension.name and dimension.value
        }
        object.__setattr__(
            self,
            "dimensions",
            tuple(
                ContextDimension(name, normalized[name])
                for name in sorted(normalized)
            ),
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> ContextKey:
        return cls(
            tuple(
                ContextDimension(str(name), str(value))
                for name, value in values.items()
                if value is not None and str(value).strip()
            )
        )

    def fingerprint(self) -> str:
        return "|".join(
            f"{dimension.name}={dimension.value}"
            for dimension in self.dimensions
        )

    def as_dict(self) -> dict[str, str]:
        return {
            dimension.name: dimension.value
            for dimension in self.dimensions
        }

    def contains(self, other: ContextKey) -> bool:
        values = self.as_dict()
        return all(values.get(name) == value for name, value in other.as_dict().items())


@dataclass(frozen=True, slots=True)
class ContextualBaselineSample:
    """One retained feature sample with contextual dimensions."""

    timestamp: datetime
    circuit_id: str
    feature: str
    value: float
    context: ContextKey
    source: str = "processor"
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class ContextualBaselineStats:
    """Robust stats for one feature under one context."""

    circuit_id: str
    feature: str
    context_fingerprint: str
    context: dict[str, str]
    sample_count: int
    median: float
    mad: float
    p10: float
    p90: float
    confidence: float
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    fallback_level: str = "exact_context"


def season_for_datetime(dt: datetime) -> str:
    """Return Northern Hemisphere meteorological season."""
    month = dt.month
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "fall"


def month_for_datetime(dt: datetime) -> str:
    return f"{dt.month:02d}"


def day_type_for_datetime(dt: datetime) -> str:
    return "weekend" if dt.weekday() >= 5 else "weekday"


def time_of_day_bucket(dt: datetime) -> str:
    hour = dt.hour
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def temperature_bin(temperature_f: float | None) -> str:
    if temperature_f is None:
        return "unknown"
    temperature = float(temperature_f)
    if temperature < 32.0:
        return "very_cold"
    if temperature < 45.0:
        return "cold"
    if temperature < 55.0:
        return "cool"
    if temperature < 70.0:
        return "mild"
    if temperature < 80.0:
        return "warm"
    if temperature < 90.0:
        return "hot"
    return "very_hot"


def weather_mode_for_temperature(temperature_f: float | None) -> str:
    if temperature_f is None:
        return "unknown"
    temperature = float(temperature_f)
    if temperature <= 55.0:
        return "heating"
    if temperature >= 75.0:
        return "cooling"
    return "neutral"


def rain_intensity_bin(intensity_per_hour: float | None) -> str:
    if intensity_per_hour is None:
        return "unknown"
    intensity = max(float(intensity_per_hour), 0.0)
    if intensity == 0.0:
        return "none"
    if intensity < 0.1:
        return "light"
    if intensity < 0.5:
        return "moderate"
    return "heavy"


def rain_state(active: bool | None, intensity_per_hour: float | None) -> str:
    if active is None and intensity_per_hour is None:
        return "unknown"
    if not active:
        return "dry"
    if rain_intensity_bin(intensity_per_hour) == "heavy":
        return "heavy_rain"
    return "raining"


def water_flow_state(active: bool | None, active_minutes: float | None) -> str:
    minutes = max(_float_or_default(active_minutes, 0.0), 0.0)
    if active is None and active_minutes is None:
        return "unknown"
    if active or minutes >= 5.0:
        return "active_flow"
    if minutes > 0.0:
        return "recent_flow"
    return "no_flow"


def solar_flow_state(status: str | None, surplus_status: str | None = None) -> str:
    normalized_surplus = _normalize_token(surplus_status or "")
    normalized_status = _normalize_token(status or "")
    if normalized_surplus == "high_surplus":
        return "high_surplus"
    if normalized_status in {
        "importing",
        "self_powered",
        "exporting",
        "no_generation",
    }:
        return normalized_status
    return "unknown"


def build_contextual_baseline(
    *,
    circuit_id: str,
    feature: str,
    context: ContextKey,
    samples: Iterable[ContextualBaselineSample],
    fallback_level: str,
    required_samples: int,
) -> ContextualBaselineStats | None:
    """Build robust stats for samples matching this context."""
    matching = [
        sample
        for sample in samples
        if sample.circuit_id == circuit_id
        and sample.feature == feature
        and sample.context.contains(context)
    ]
    if len(matching) < required_samples:
        return None

    baseline = build_baseline(feature, [sample.value for sample in matching])
    timestamps = sorted(sample.timestamp for sample in matching)
    sample_confidence = min(1.0, len(matching) / max(required_samples, 1))
    specificity = FALLBACK_SPECIFICITY_WEIGHT.get(fallback_level, 0.65)
    confidence = round(sample_confidence * specificity, 3)
    return ContextualBaselineStats(
        circuit_id=circuit_id,
        feature=feature,
        context_fingerprint=context.fingerprint(),
        context=context.as_dict(),
        sample_count=len(matching),
        median=baseline.median,
        mad=baseline.mad,
        p10=baseline.p10,
        p90=baseline.p90,
        confidence=confidence,
        first_seen=timestamps[0] if timestamps else None,
        last_seen=timestamps[-1] if timestamps else None,
        fallback_level=fallback_level,
    )


def select_contextual_baseline(
    *,
    circuit_id: str,
    feature: str,
    samples: Iterable[ContextualBaselineSample],
    fallback_contexts: Sequence[tuple[str, ContextKey, int]],
) -> ContextualBaselineStats | None:
    """Return the first reliable contextual baseline in fallback order."""
    sample_list = list(samples)
    for fallback_level, context, required_samples in fallback_contexts:
        stats = build_contextual_baseline(
            circuit_id=circuit_id,
            feature=feature,
            context=context,
            samples=sample_list,
            fallback_level=fallback_level,
            required_samples=required_samples,
        )
        if stats is not None:
            return stats
    return None


def daily_energy_fallback_contexts(
    context: ContextKey,
) -> list[tuple[str, ContextKey, int]]:
    """Build a conservative daily-energy fallback chain."""
    values = context.as_dict()
    fallbacks: list[tuple[str, ContextKey, int]] = [("exact_context", context, 7)]
    temperature_context = {
        key: values[key]
        for key in ("temperature_bin", "weather_mode")
        if key in values
    }
    if temperature_context:
        fallbacks.append(
            (
                "temperature_context",
                ContextKey.from_mapping(temperature_context),
                10,
            )
        )
    if "season" in values:
        fallbacks.append(
            (
                "seasonal_context",
                ContextKey.from_mapping({"season": values["season"]}),
                10,
            )
        )
    if "time_of_day" in values:
        fallbacks.append(
            (
                "time_context",
                ContextKey.from_mapping({"time_of_day": values["time_of_day"]}),
                10,
            )
        )
    profile = values.get("appliance_profile")
    if profile:
        fallbacks.append(
            (
                "profile_context",
                ContextKey.from_mapping({"appliance_profile": profile}),
                12,
            )
        )
    return fallbacks


def build_context_for_sample(
    *,
    circuit_config: CircuitConfig,
    sample: NormalizedCircuitSample,
    state: Any,
    store_data: Any,
    now: datetime,
    feature: str,
) -> ContextKey:
    """Build stable contextual dimensions from existing analyzer state."""
    del sample, feature
    circuit_id = circuit_config.circuit_id
    values: dict[str, str] = {
        "appliance_profile": circuit_config.appliance_profile.value,
        "circuit_mode": circuit_config.mode.value,
        "season": season_for_datetime(now),
        "time_of_day": time_of_day_bucket(now),
    }
    if circuit_config.power_flow is not PowerFlowMode.LOAD:
        values["power_flow_mode"] = circuit_config.power_flow.value

    weather = _mapping_for(
        getattr(state, "weather_context_by_circuit", {}),
        circuit_id,
    )
    temperature = _float_or_none(weather.get("temperature_f"))
    if temperature is not None:
        values["temperature_bin"] = temperature_bin(temperature)
        values["weather_mode"] = _normalize_weather_mode(
            weather.get("mode"),
            temperature,
        )

    rain = _mapping_for(
        getattr(state, "rain_pump_context_by_circuit", {}),
        circuit_id,
    )
    rain_active = _bool_or_none(rain.get("rain_sensor_active"))
    rain_intensity = _float_or_none(rain.get("rain_intensity_per_hour"))
    if rain_active is not None or rain_intensity is not None:
        values["rain_state"] = rain_state(rain_active, rain_intensity)
        values["rain_intensity_bin"] = rain_intensity_bin(rain_intensity)

    water = _mapping_for(
        getattr(state, "water_flow_context_by_circuit", {}),
        circuit_id,
    )
    flow_active = _bool_or_none(water.get("flow_sensor_active"))
    flow_minutes = _float_or_none(water.get("flow_active_minutes"))
    if flow_active is not None or flow_minutes is not None:
        values["water_flow_state"] = water_flow_state(flow_active, flow_minutes)

    solar_status = getattr(state, "solar_flow_status_by_circuit", {}).get(circuit_id)
    solar_evidence = _mapping_for(
        getattr(state, "solar_flow_evidence_by_circuit", {}),
        circuit_id,
    )
    solar_surplus = solar_evidence.get("solar_surplus_status")
    if solar_status is not None or solar_surplus is not None:
        values["solar_flow_state"] = solar_flow_state(solar_status, solar_surplus)

    maintenance = _mapping_for(
        getattr(store_data, "maintenance_by_circuit", {}),
        circuit_id,
    )
    if maintenance.get("active") is True:
        values["maintenance_state"] = "active"

    return ContextKey.from_mapping(_filter_context_for_profile(circuit_config, values))


def contextual_sample_to_dict(sample: ContextualBaselineSample) -> dict[str, Any]:
    return {
        "timestamp": sample.timestamp.isoformat(),
        "feature": sample.feature,
        "value": float(sample.value),
        "context": sample.context.as_dict(),
        "source": sample.source,
    }


def contextual_sample_from_dict(
    circuit_id: str,
    raw: Mapping[str, Any],
) -> ContextualBaselineSample | None:
    try:
        timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        feature = str(raw["feature"])
        value = float(raw["value"])
        context_raw = raw["context"]
    except (KeyError, TypeError, ValueError):
        return None
    if not feature or not isinstance(context_raw, Mapping):
        return None
    return ContextualBaselineSample(
        timestamp=timestamp,
        circuit_id=circuit_id,
        feature=feature,
        value=value,
        context=ContextKey.from_mapping(context_raw),
        source=str(raw.get("source") or "processor"),
        weight=_float_or_default(raw.get("weight"), 1.0),
    )


def contextual_stats_to_dict(stats: ContextualBaselineStats) -> dict[str, Any]:
    return {
        "feature": stats.feature,
        "context_fingerprint": stats.context_fingerprint,
        "context": dict(stats.context),
        "sample_count": stats.sample_count,
        "median": stats.median,
        "mad": stats.mad,
        "p10": stats.p10,
        "p90": stats.p90,
        "confidence": stats.confidence,
        "first_seen": stats.first_seen.isoformat() if stats.first_seen else None,
        "last_seen": stats.last_seen.isoformat() if stats.last_seen else None,
        "fallback_level": stats.fallback_level,
    }


def contextual_stats_storage_key(stats: ContextualBaselineStats) -> str:
    return f"{stats.feature}|{stats.context_fingerprint}"


def stored_contextual_samples(
    circuit_id: str,
    raw_samples: Iterable[Mapping[str, Any]],
) -> list[ContextualBaselineSample]:
    samples: list[ContextualBaselineSample] = []
    for raw in raw_samples:
        sample = contextual_sample_from_dict(circuit_id, raw)
        if sample is not None:
            samples.append(sample)
    return samples


def upsert_contextual_sample(
    samples: list[dict[str, Any]],
    sample: ContextualBaselineSample,
) -> None:
    """Insert or replace one feature sample for the same local date/context."""
    payload = contextual_sample_to_dict(sample)
    fingerprint = sample.context.fingerprint()
    sample_date = sample.timestamp.date()
    for index, existing in enumerate(samples):
        existing_sample = contextual_sample_from_dict(sample.circuit_id, existing)
        if existing_sample is None:
            continue
        if (
            existing_sample.feature == sample.feature
            and existing_sample.timestamp.date() == sample_date
            and existing_sample.context.fingerprint() == fingerprint
        ):
            samples[index] = payload
            return
    samples.append(payload)


def _filter_context_for_profile(
    circuit_config: CircuitConfig,
    values: Mapping[str, str],
) -> dict[str, str]:
    profile = circuit_config.appliance_profile
    allowed = {
        "appliance_profile",
        "circuit_mode",
        "maintenance_state",
        "power_flow_mode",
        "season",
    }
    if profile in {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
    }:
        allowed.update({"temperature_bin", "time_of_day", "weather_mode"})
    elif profile in {
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
    }:
        allowed.update({"rain_intensity_bin", "rain_state", "water_flow_state"})
    elif profile is ApplianceProfile.WATER_HEATER:
        allowed.update({"day_type", "time_of_day", "water_flow_state"})
    elif profile in {ApplianceProfile.EV_CHARGER, ApplianceProfile.POOL_PUMP}:
        allowed.update({"day_type", "solar_flow_state", "time_of_day"})
    elif profile in {ApplianceProfile.SOLAR_INVERTER, ApplianceProfile.MAINS_NILM}:
        allowed.update({"solar_flow_state", "time_of_day"})
    elif profile in {ApplianceProfile.REFRIGERATOR, ApplianceProfile.FREEZER}:
        allowed.update({"time_of_day"})
    else:
        allowed.update({"time_of_day"})

    filtered = {key: value for key, value in values.items() if key in allowed}
    if "day_type" in allowed:
        filtered["day_type"] = values.get("day_type", "")
    return {key: value for key, value in filtered.items() if value}


def _mapping_for(values: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    item = values.get(key, {})
    return item if isinstance(item, Mapping) else {}


def _normalize_weather_mode(value: Any, temperature: float | None) -> str:
    normalized = _normalize_token(value or "")
    if normalized in {"heating", "cooling", "neutral"}:
        return normalized
    return weather_mode_for_temperature(temperature)


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "on", "1", "yes"}:
        return True
    if normalized in {"false", "off", "0", "no"}:
        return False
    return None
