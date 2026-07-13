from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

from .baseline import build_baseline
from .local_time import TimeZone, as_ha_local, local_date
from .models import ApplianceProfile, CircuitConfig, PowerFlowMode
from .normalize import NormalizedCircuitSample

FALLBACK_SPECIFICITY_WEIGHT = {
    "exact_context": 1.0,
    "progress_context": 0.9,
    "temperature_context": 0.85,
    "seasonal_context": 0.75,
    "time_context": 0.75,
    "profile_context": 0.7,
    "global_circuit": 0.65,
    "global_profile": 0.6,
}

DAILY_ENERGY_FEATURE = "daily_energy_kwh"
DAY_PROGRESS_FEATURES = {
    DAILY_ENERGY_FEATURE,
    "peak_demand_w",
    "runtime_today_seconds",
    "run_cycle_daily_start_count",
    "cost_today",
}
CONTEXT_FINGERPRINT_SCHEMA_VERSION = "context:v2"
DEFAULT_RAIN_INTENSITY_UNIT = "mm/h"
RAIN_ACTIVITY_CONFLICT = "rain_activity_conflict"
RAIN_INTENSITY_UNIT_MISSING = "rain_intensity_unit_missing"
RAIN_INTENSITY_UNIT_UNSUPPORTED = "rain_intensity_unit_unsupported"
RAIN_INTENSITY_INVALID = "rain_intensity_invalid"


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
        dimensions = "|".join(
            f"{dimension.name}={dimension.value}"
            for dimension in self.dimensions
        )
        if not dimensions:
            return CONTEXT_FINGERPRINT_SCHEMA_VERSION
        return f"{CONTEXT_FINGERPRINT_SCHEMA_VERSION}|{dimensions}"

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
    sample_count: int | float
    median: float
    mad: float
    p10: float
    p90: float
    confidence: float
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    fallback_level: str = "exact_context"


@dataclass(frozen=True, slots=True)
class RainContext:
    state: str
    intensity_bin: str
    intensity_mm_per_hour: float | None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _WeightedContextualStats:
    sample_count: int | float
    median: float
    mad: float
    p10: float
    p90: float


def season_for_datetime(dt: datetime, *, time_zone: TimeZone = None) -> str:
    """Return Northern Hemisphere meteorological season."""
    month = _calendar_datetime(dt, time_zone).month
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "fall"


def day_type_for_datetime(dt: datetime, *, time_zone: TimeZone = None) -> str:
    calendar_dt = _calendar_datetime(dt, time_zone)
    return "weekend" if calendar_dt.weekday() >= 5 else "weekday"


def time_of_day_bucket(dt: datetime, *, time_zone: TimeZone = None) -> str:
    hour = _calendar_datetime(dt, time_zone).hour
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def day_progress_bucket(dt: datetime, *, time_zone: TimeZone = None) -> str:
    """Return a ten-percent Home Assistant local-day progress bucket."""
    local_dt = _calendar_datetime(dt, time_zone)
    elapsed_seconds = (
        local_dt.hour * 3600 + local_dt.minute * 60 + local_dt.second
    )
    lower = min(int(elapsed_seconds / 86400 * 10) * 10, 90)
    return f"{lower}-{lower + 10}%"


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


def normalize_rain_intensity_per_hour(
    intensity_per_hour: float | None,
    *,
    unit: str | None = DEFAULT_RAIN_INTENSITY_UNIT,
) -> tuple[float | None, tuple[str, ...]]:
    if intensity_per_hour is None:
        return None, ()
    intensity = _float_or_none(intensity_per_hour)
    if intensity is None or not isfinite(intensity):
        return None, (RAIN_INTENSITY_INVALID,)
    intensity = max(float(intensity), 0.0)
    if intensity == 0.0:
        return 0.0, ()
    normalized_unit = _normalize_rain_intensity_unit(unit)
    if normalized_unit is None:
        return None, (RAIN_INTENSITY_UNIT_MISSING,)
    if normalized_unit == DEFAULT_RAIN_INTENSITY_UNIT:
        return intensity, ()
    if normalized_unit == "in/h":
        return intensity * 25.4, ()
    return None, (RAIN_INTENSITY_UNIT_UNSUPPORTED,)


def rain_intensity_bin(
    intensity_per_hour: float | None,
    *,
    unit: str | None = DEFAULT_RAIN_INTENSITY_UNIT,
) -> str:
    intensity, _issues = normalize_rain_intensity_per_hour(
        intensity_per_hour,
        unit=unit,
    )
    return _rain_intensity_bin_from_mm(intensity)


def rain_state(
    active: bool | None,
    intensity_per_hour: float | None,
    *,
    unit: str | None = DEFAULT_RAIN_INTENSITY_UNIT,
) -> str:
    return rain_context(active, intensity_per_hour, unit=unit).state


def rain_context(
    active: bool | None,
    intensity_per_hour: float | None,
    *,
    unit: str | None = DEFAULT_RAIN_INTENSITY_UNIT,
) -> RainContext:
    intensity, issues = normalize_rain_intensity_per_hour(
        intensity_per_hour,
        unit=unit,
    )
    raw_intensity = _float_or_none(intensity_per_hour)
    raw_positive = (
        raw_intensity is not None
        and isfinite(raw_intensity)
        and float(raw_intensity) > 0.0
    )
    active_state = _bool_or_none(active)
    intensity_bin = _rain_intensity_bin_from_mm(intensity)
    context_issues = list(issues)

    if active_state is None:
        if intensity is None:
            state = "unknown" if raw_positive or raw_intensity is None else "dry"
        elif intensity > 0.0:
            state = _rain_state_from_intensity_bin(intensity_bin)
        else:
            state = "dry"
    elif active_state is False:
        if raw_positive:
            context_issues.append(RAIN_ACTIVITY_CONFLICT)
            state = (
                "ambiguous"
                if intensity is not None and intensity > 0.0
                else "unknown"
            )
        else:
            state = "dry"
    elif intensity is not None and intensity == 0.0:
        context_issues.append(RAIN_ACTIVITY_CONFLICT)
        state = "raining"
    else:
        state = _rain_state_from_intensity_bin(intensity_bin)

    return RainContext(
        state=state,
        intensity_bin=intensity_bin,
        intensity_mm_per_hour=intensity,
        issues=_unique_issue_tuple(context_issues),
    )


def _rain_intensity_bin_from_mm(intensity_per_hour: float | None) -> str:
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


def _rain_state_from_intensity_bin(intensity_bin: str) -> str:
    return "heavy_rain" if intensity_bin == "heavy" else "raining"


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
        and context_allows_baseline_learning(sample.context)
        and _sample_weight(sample) > 0.0
        and _context_matches_fallback(sample.context, context, fallback_level)
    ]
    effective_sample_count = sum(_sample_weight(sample) for sample in matching)
    if effective_sample_count < required_samples:
        return None

    baseline = _build_weighted_contextual_stats(feature, matching)
    timestamps = sorted(sample.timestamp for sample in matching)
    sample_confidence = min(1.0, effective_sample_count / max(required_samples, 1))
    specificity = FALLBACK_SPECIFICITY_WEIGHT.get(fallback_level, 0.65)
    confidence = round(sample_confidence * specificity, 3)
    return ContextualBaselineStats(
        circuit_id=circuit_id,
        feature=feature,
        context_fingerprint=context.fingerprint(),
        context=context.as_dict(),
        sample_count=baseline.sample_count,
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
    progress = values.get("day_progress")
    if progress:
        progress_context = {"day_progress": progress}
        for key in ("appliance_profile", "day_type"):
            if key in values:
                progress_context[key] = values[key]
        fallbacks.append(
            (
                "progress_context",
                ContextKey.from_mapping(progress_context),
                7,
            )
        )
    required_progress = {"day_progress": progress} if progress else {}
    temperature_context = {
        key: values[key]
        for key in ("temperature_bin", "weather_mode")
        if key in values
    }
    if temperature_context:
        temperature_context.update(required_progress)
        fallbacks.append(
            (
                "temperature_context",
                ContextKey.from_mapping(temperature_context),
                10,
            )
        )
    if "season" in values:
        seasonal_context = {"season": values["season"], **required_progress}
        fallbacks.append(
            (
                "seasonal_context",
                ContextKey.from_mapping(seasonal_context),
                10,
            )
        )
    if "time_of_day" in values:
        time_context = {"time_of_day": values["time_of_day"], **required_progress}
        fallbacks.append(
            (
                "time_context",
                ContextKey.from_mapping(time_context),
                10,
            )
        )
    profile = values.get("appliance_profile")
    if profile:
        profile_context = {"appliance_profile": profile, **required_progress}
        fallbacks.append(
            (
                "profile_context",
                ContextKey.from_mapping(profile_context),
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
    time_zone: TimeZone = None,
    calendar_timestamp: datetime | None = None,
) -> ContextKey:
    """Build stable contextual dimensions from existing analyzer state."""
    circuit_id = circuit_config.circuit_id
    context_timestamp = calendar_timestamp or sample.timestamp
    values: dict[str, str] = {
        "appliance_profile": circuit_config.appliance_profile.value,
        "circuit_mode": circuit_config.mode.value,
        "day_type": day_type_for_datetime(context_timestamp, time_zone=time_zone),
        "season": season_for_datetime(context_timestamp, time_zone=time_zone),
        "time_of_day": time_of_day_bucket(context_timestamp, time_zone=time_zone),
    }
    if feature in DAY_PROGRESS_FEATURES:
        values["day_progress"] = day_progress_bucket(
            context_timestamp,
            time_zone=time_zone,
        )
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
    rain_intensity, rain_unit = _rain_intensity_for_context(rain)
    rain_issues = _rain_issues_for_context(rain)
    if rain_active is not None or rain_intensity is not None or rain_issues:
        rain_info = rain_context(rain_active, rain_intensity, unit=rain_unit)
        issues = _unique_issue_tuple((*rain_issues, *rain_info.issues))
        values["rain_state"] = rain_info.state
        values["rain_intensity_bin"] = rain_info.intensity_bin
        if issues:
            values["rain_context_issue"] = _primary_rain_issue(issues)

    water = _mapping_for(
        getattr(state, "water_flow_context_by_circuit", {}),
        circuit_id,
    )
    flow_active = _bool_or_none(water.get("flow_sensor_active"))
    flow_minutes = _float_or_none(water.get("flow_active_minutes"))
    if flow_active is not None or flow_minutes is not None:
        values["water_flow_state"] = water_flow_state(flow_active, flow_minutes)

    raw_solar_status_by_circuit = getattr(state, "solar_flow_status_by_circuit", {})
    raw_solar_evidence_by_circuit = getattr(state, "solar_flow_evidence_by_circuit", {})
    solar_status_by_circuit = (
        raw_solar_status_by_circuit
        if isinstance(raw_solar_status_by_circuit, Mapping)
        else {}
    )
    solar_evidence_by_circuit = (
        raw_solar_evidence_by_circuit
        if isinstance(raw_solar_evidence_by_circuit, Mapping)
        else {}
    )
    solar_context_circuit_id = _solar_context_circuit_id(
        solar_status_by_circuit,
        solar_evidence_by_circuit,
        circuit_id,
    )
    solar_status = solar_status_by_circuit.get(solar_context_circuit_id)
    solar_evidence = _mapping_for(
        solar_evidence_by_circuit,
        solar_context_circuit_id,
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
    payload = {
        "timestamp": sample.timestamp.isoformat(),
        "feature": sample.feature,
        "value": float(sample.value),
        "context": sample.context.as_dict(),
        "source": sample.source,
    }
    weight = _sample_weight(sample)
    if weight != 1.0:
        payload["weight"] = weight
    return payload


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
    *,
    time_zone: TimeZone = None,
) -> None:
    """Insert or replace one feature sample for the same local date/context."""
    payload = contextual_sample_to_dict(sample)
    fingerprint = sample.context.fingerprint()
    sample_date = _sample_calendar_date(sample.timestamp, time_zone)
    for index, existing in enumerate(samples):
        existing_sample = contextual_sample_from_dict(sample.circuit_id, existing)
        if existing_sample is None:
            continue
        if (
            existing_sample.feature == sample.feature
            and _sample_calendar_date(existing_sample.timestamp, time_zone)
            == sample_date
            and existing_sample.context.fingerprint() == fingerprint
        ):
            samples[index] = payload
            return
    samples.append(payload)


def context_allows_baseline_learning(context: ContextKey) -> bool:
    return context.as_dict().get("maintenance_state") != "active"


def _build_weighted_contextual_stats(
    feature: str,
    samples: Sequence[ContextualBaselineSample],
) -> _WeightedContextualStats:
    weighted_values = [
        (float(sample.value), _sample_weight(sample))
        for sample in samples
        if _sample_weight(sample) > 0.0
    ]
    if not weighted_values:
        raise ValueError(f"{feature} baseline requires positive sample weight")
    if all(weight.is_integer() for _value, weight in weighted_values):
        expanded_values = [
            value
            for value, weight in weighted_values
            for _index in range(int(weight))
        ]
        baseline = build_baseline(
            feature,
            expanded_values,
        )
        return _WeightedContextualStats(
            sample_count=baseline.sample_count,
            median=baseline.median,
            mad=baseline.mad,
            p10=baseline.p10,
            p90=baseline.p90,
        )
    weighted_values.sort(key=lambda item: item[0])
    median_value = _weighted_median(weighted_values)
    weighted_deviations = sorted(
        (
            (abs(value - median_value), weight)
            for value, weight in weighted_values
        ),
        key=lambda item: item[0],
    )
    return _WeightedContextualStats(
        sample_count=_effective_weighted_sample_count(weighted_values),
        median=median_value,
        mad=_continuous_weighted_percentile(weighted_deviations, 0.50),
        p10=_continuous_weighted_percentile(weighted_values, 0.10),
        p90=_continuous_weighted_percentile(weighted_values, 0.90),
    )


def _effective_weighted_sample_count(
    weighted_values: Sequence[tuple[float, float]],
) -> int | float:
    total_weight = sum(weight for _value, weight in weighted_values)
    if total_weight.is_integer():
        return int(total_weight)
    return round(total_weight, 3)


def _weighted_median(weighted_values: Sequence[tuple[float, float]]) -> float:
    total_weight = sum(weight for _value, weight in weighted_values)
    if total_weight <= 0.0:
        raise ValueError("weighted median requires positive total weight")
    return _continuous_weighted_percentile(weighted_values, 0.50)


def _continuous_weighted_percentile(
    weighted_values: Sequence[tuple[float, float]],
    percentile: float,
) -> float:
    total_weight = sum(weight for _value, weight in weighted_values)
    if total_weight <= 0.0:
        raise ValueError("weighted percentile requires positive total weight")
    target = total_weight * min(max(percentile, 0.0), 1.0)
    centers: list[tuple[float, float]] = []
    cumulative = 0.0
    for value, weight in weighted_values:
        centers.append((cumulative + weight / 2.0, value))
        cumulative += weight
    if target <= centers[0][0]:
        return float(centers[0][1])
    for index in range(1, len(centers)):
        left_position, left_value = centers[index - 1]
        right_position, right_value = centers[index]
        if target <= right_position:
            if right_position == left_position:
                return float(right_value)
            ratio = (target - left_position) / (right_position - left_position)
            return float(left_value + (right_value - left_value) * ratio)
    return float(centers[-1][1])


def _sample_weight(sample: ContextualBaselineSample) -> float:
    try:
        weight = float(sample.weight)
    except (TypeError, ValueError):
        return 0.0
    return weight if isfinite(weight) and weight > 0.0 else 0.0


def _context_matches_fallback(
    sample_context: ContextKey,
    requested_context: ContextKey,
    fallback_level: str,
) -> bool:
    if fallback_level == "exact_context":
        return sample_context.fingerprint() == requested_context.fingerprint()
    return sample_context.contains(requested_context)


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
        allowed.update(
            {
                "rain_context_issue",
                "rain_intensity_bin",
                "rain_state",
                "water_flow_state",
            }
        )
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

    if "day_progress" in values:
        allowed.add("day_progress")

    filtered = {key: value for key, value in values.items() if key in allowed}
    if "day_type" in allowed:
        filtered["day_type"] = values.get("day_type", "")
    return {key: value for key, value in filtered.items() if value}


def _solar_context_circuit_id(
    solar_status_by_circuit: Mapping[Any, Any],
    solar_evidence_by_circuit: Mapping[Any, Any],
    circuit_id: str,
) -> str:
    if circuit_id in solar_status_by_circuit:
        return circuit_id
    if circuit_id in solar_evidence_by_circuit:
        return circuit_id

    site_candidates = [
        candidate
        for candidate in _solar_context_candidate_ids(
            solar_status_by_circuit,
            solar_evidence_by_circuit,
        )
        if _is_site_solar_context_candidate(candidate)
    ]
    if site_candidates:
        return site_candidates[0]

    candidate_ids = _solar_context_candidate_ids(
        solar_status_by_circuit,
        solar_evidence_by_circuit,
    )
    return candidate_ids[0] if candidate_ids else circuit_id


def _solar_context_candidate_ids(
    solar_status_by_circuit: Mapping[Any, Any],
    solar_evidence_by_circuit: Mapping[Any, Any],
) -> list[str]:
    candidate_ids: list[str] = []
    candidate_ids.extend(str(key) for key in solar_status_by_circuit)
    candidate_ids.extend(
        str(key)
        for key in solar_evidence_by_circuit
        if str(key) not in candidate_ids
    )
    return candidate_ids


def _is_site_solar_context_candidate(candidate_id: str) -> bool:
    normalized = _normalize_token(candidate_id)
    return normalized in {"mains", "main", "site", "grid", "whole_home"}


def _mapping_for(values: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    item = values.get(key, {})
    return item if isinstance(item, Mapping) else {}


def _calendar_datetime(dt: datetime, time_zone: TimeZone) -> datetime:
    if time_zone is None or _is_naive_datetime(dt):
        return dt
    return as_ha_local(dt, time_zone)


def _sample_calendar_date(dt: datetime, time_zone: TimeZone) -> date:
    if time_zone is None or _is_naive_datetime(dt):
        return dt.date()
    return local_date(dt, time_zone)


def _is_naive_datetime(dt: datetime) -> bool:
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def _normalize_weather_mode(value: Any, temperature: float | None) -> str:
    normalized = _normalize_token(value or "")
    if normalized in {"heating", "cooling", "neutral"}:
        return normalized
    return weather_mode_for_temperature(temperature)


def _rain_intensity_for_context(
    rain: Mapping[str, Any],
) -> tuple[float | None, str | None]:
    normalized_intensity = _float_or_none(rain.get("rain_intensity_mm_per_hour"))
    if normalized_intensity is not None:
        return normalized_intensity, DEFAULT_RAIN_INTENSITY_UNIT
    return _float_or_none(rain.get("rain_intensity_per_hour")), rain.get(
        "rain_intensity_unit",
        DEFAULT_RAIN_INTENSITY_UNIT,
    )


def _rain_issues_for_context(rain: Mapping[str, Any]) -> tuple[str, ...]:
    raw_issues = rain.get("rain_context_issues")
    if isinstance(raw_issues, str):
        return _unique_issue_tuple([raw_issues])
    if not isinstance(raw_issues, Sequence):
        return ()
    return _unique_issue_tuple(str(issue) for issue in raw_issues if issue)


def _normalize_rain_intensity_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    normalized = str(unit).strip().lower()
    if not normalized:
        return None
    compact = normalized.replace(" ", "")
    if compact in {
        "mm/h",
        "mm/hr",
        "mmperhour",
        "millimeter/hour",
        "millimeters/hour",
        "millimeterperhour",
        "millimetersperhour",
    }:
        return DEFAULT_RAIN_INTENSITY_UNIT
    if compact in {
        "in/h",
        "in/hr",
        "inperhour",
        "inch/hour",
        "inches/hour",
        "inchperhour",
        "inchesperhour",
    }:
        return "in/h"
    return compact


def _unique_issue_tuple(issues: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    for issue in issues:
        normalized = _normalize_token(issue)
        if normalized and normalized not in values:
            values.append(normalized)
    return tuple(values)


def _primary_rain_issue(issues: Sequence[str]) -> str:
    if RAIN_ACTIVITY_CONFLICT in issues:
        return RAIN_ACTIVITY_CONFLICT
    return str(issues[0])


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
