from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer import contextual_baseline
from custom_components.circuitsetup_energy_analyzer.contextual_baseline import (
    ContextDimension,
    ContextKey,
    ContextualBaselineSample,
    build_context_for_sample,
    build_contextual_baseline,
    contextual_sample_from_dict,
    contextual_sample_to_dict,
    day_type_for_datetime,
    rain_intensity_bin,
    rain_state,
    season_for_datetime,
    select_contextual_baseline,
    solar_flow_state,
    temperature_bin,
    time_of_day_bucket,
    upsert_contextual_sample,
    water_flow_state,
    weather_mode_for_temperature,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_context_fingerprint_stable_and_order_independent() -> None:
    first = ContextKey(
        (
            ContextDimension("season", "summer"),
            ContextDimension("temperature_bin", "very_hot"),
            ContextDimension("weather_mode", "cooling"),
        )
    )
    second = ContextKey.from_mapping(
        {
            "weather_mode": "cooling",
            "temperature_bin": "very_hot",
            "season": "summer",
        }
    )

    assert first.fingerprint() == (
        "context:v2|season=summer|temperature_bin=very_hot|weather_mode=cooling"
    )
    assert second.fingerprint() == first.fingerprint()
    assert second.as_dict() == {
        "season": "summer",
        "temperature_bin": "very_hot",
        "weather_mode": "cooling",
    }


def test_context_bucket_helpers() -> None:
    assert season_for_datetime(datetime(2026, 1, 15, tzinfo=UTC)) == "winter"
    assert season_for_datetime(datetime(2026, 4, 15, tzinfo=UTC)) == "spring"
    assert season_for_datetime(datetime(2026, 7, 15, tzinfo=UTC)) == "summer"
    assert season_for_datetime(datetime(2026, 10, 15, tzinfo=UTC)) == "fall"
    assert time_of_day_bucket(datetime(2026, 6, 17, 3, tzinfo=UTC)) == "night"
    assert time_of_day_bucket(datetime(2026, 6, 17, 9, tzinfo=UTC)) == "morning"
    assert time_of_day_bucket(datetime(2026, 6, 17, 15, tzinfo=UTC)) == "afternoon"
    assert time_of_day_bucket(datetime(2026, 6, 17, 21, tzinfo=UTC)) == "evening"
    assert day_type_for_datetime(datetime(2026, 6, 20, tzinfo=UTC)) == "weekend"
    assert temperature_bin(20.0) == "very_cold"
    assert temperature_bin(50.0) == "cool"
    assert temperature_bin(62.0) == "mild"
    assert temperature_bin(92.0) == "very_hot"
    assert weather_mode_for_temperature(50.0) == "heating"
    assert weather_mode_for_temperature(62.0) == "neutral"
    assert weather_mode_for_temperature(80.0) == "cooling"
    assert rain_intensity_bin(None) == "unknown"
    assert rain_intensity_bin(0.0) == "none"
    assert rain_intensity_bin(0.08) == "light"
    assert rain_intensity_bin(0.4) == "moderate"
    assert rain_intensity_bin(0.9) == "heavy"
    assert rain_state(False, None) == "dry"
    assert rain_state(True, 0.9) == "heavy_rain"
    assert rain_state(None, 0.4) == "raining"
    assert rain_state(None, 0.9) == "heavy_rain"
    assert rain_state(False, 0.4) == "ambiguous"
    assert rain_state(False, 0.0) == "dry"
    assert water_flow_state(True, 12.0) == "active_flow"
    assert water_flow_state(False, 3.0) == "recent_flow"
    assert water_flow_state(False, 0.0) == "no_flow"
    assert solar_flow_state("exporting", "high_surplus") == "high_surplus"
    assert solar_flow_state("exporting", "no_surplus") == "exporting"


def test_context_bucket_helpers_accept_ha_local_timezone() -> None:
    timestamp = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)

    assert season_for_datetime(timestamp, time_zone="America/New_York") == "spring"
    assert day_type_for_datetime(timestamp, time_zone="America/New_York") == "weekend"
    assert time_of_day_bucket(timestamp, time_zone="America/New_York") == "evening"


def test_day_progress_bucket_uses_home_assistant_local_time() -> None:
    helper = getattr(contextual_baseline, "day_progress_bucket", None)
    assert callable(helper), "day_progress_bucket is required for partial-day baselines"

    timestamp = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    assert helper(timestamp, time_zone="America/New_York") == "30-40%"


def test_contextual_baseline_builds_robust_stats() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, day, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=value,
            context=context,
        )
        for day, value in enumerate([7.0, 8.0, 8.0, 9.0, 40.0], start=1)
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=context,
        samples=samples,
        fallback_level="exact_context",
        required_samples=5,
    )

    assert stats is not None
    assert stats.context_fingerprint == "context:v2|season=summer"
    assert stats.sample_count == 5
    assert stats.median == 8.0
    assert stats.p90 == 40.0
    assert stats.confidence == 1.0
    assert stats.first_seen == datetime(2026, 6, 1, tzinfo=UTC)
    assert stats.last_seen == datetime(2026, 6, 5, tzinfo=UTC)


def test_contextual_baseline_fallback_prefers_reliable_context() -> None:
    exact = ContextKey.from_mapping(
        {"season": "summer", "temperature_bin": "very_hot"}
    )
    temperature = ContextKey.from_mapping({"temperature_bin": "very_hot"})
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=offset),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=8.0 + offset,
            context=exact if offset < 3 else temperature,
        )
        for offset in range(11)
    ]

    selected = select_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        samples=samples,
        fallback_contexts=[
            ("exact_context", exact, 7),
            ("temperature_context", temperature, 8),
        ],
    )

    assert selected is not None
    assert selected.fallback_level == "temperature_context"
    assert selected.sample_count == 11
    assert selected.context == {"temperature_bin": "very_hot"}


def test_contextual_baseline_excludes_maintenance_samples_from_fallback() -> None:
    requested = ContextKey.from_mapping({"season": "summer"})
    maintenance_context = ContextKey.from_mapping(
        {
            "maintenance_state": "active",
            "season": "summer",
        }
    )
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=offset),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=12.0 + offset,
            context=maintenance_context,
        )
        for offset in range(7)
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=requested,
        samples=samples,
        fallback_level="seasonal_context",
        required_samples=7,
    )

    assert stats is None


def test_contextual_baseline_uses_sample_weight_for_reliability_and_stats() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 1, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=100.0,
            context=context,
            weight=0.0,
        ),
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 2, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=10.0,
            context=context,
            weight=3.0,
        ),
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 3, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=20.0,
            context=context,
        ),
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=30.0,
            context=context,
        ),
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=context,
        samples=samples,
        fallback_level="exact_context",
        required_samples=5,
    )

    assert stats is not None
    assert stats.sample_count == 5
    assert stats.median == 10.0
    assert stats.p90 == 30.0
    assert stats.first_seen == datetime(2026, 6, 2, tzinfo=UTC)


def test_contextual_baseline_weighted_stats_match_expanded_samples() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 1, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=10.0,
            context=context,
            weight=2.0,
        ),
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 2, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=20.0,
            context=context,
            weight=2.0,
        ),
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=context,
        samples=samples,
        fallback_level="exact_context",
        required_samples=4,
    )

    assert stats is not None
    assert stats.sample_count == 4
    assert stats.median == 15.0
    assert stats.mad == 5.0


def test_contextual_baseline_supports_subunit_fractional_weights() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, day, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=float(day * 10),
            context=context,
            weight=0.25,
        )
        for day in range(1, 5)
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=context,
        samples=samples,
        fallback_level="exact_context",
        required_samples=1,
    )

    assert stats is not None
    assert stats.sample_count == 1
    assert stats.median == 25.0
    assert stats.mad == 10.0
    assert stats.p10 == 10.0
    assert stats.p90 == 40.0


def test_contextual_sample_serialization_preserves_non_default_weight() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    sample = ContextualBaselineSample(
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        circuit_id="hvac",
        feature="daily_energy_kwh",
        value=12.0,
        context=context,
        weight=2.5,
    )

    payload = contextual_sample_to_dict(sample)
    restored = contextual_sample_from_dict("hvac", payload)

    assert payload["weight"] == 2.5
    assert restored is not None
    assert restored.weight == 2.5


def test_contextual_sample_serialization_normalizes_invalid_weight() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    sample = ContextualBaselineSample(
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        circuit_id="hvac",
        feature="daily_energy_kwh",
        value=12.0,
        context=context,
        weight=float("nan"),
    )

    payload = contextual_sample_to_dict(sample)
    restored = contextual_sample_from_dict("hvac", payload)

    assert payload["weight"] == 0.0
    assert restored is not None
    assert restored.weight == 0.0


def test_stored_contextual_samples_reuses_update_cache(monkeypatch) -> None:
    raw_samples = [
        {
            "timestamp": datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
            "feature": "daily_energy_kwh",
            "value": 12.0,
            "context": {"season": "summer"},
        }
    ]
    calls = 0
    original = contextual_baseline.contextual_sample_from_dict

    def counting_sample_from_dict(circuit_id: str, raw: dict[str, object]):
        nonlocal calls
        calls += 1
        return original(circuit_id, raw)

    monkeypatch.setattr(
        contextual_baseline,
        "contextual_sample_from_dict",
        counting_sample_from_dict,
    )
    cache = {}

    first = contextual_baseline.stored_contextual_samples(
        "hvac",
        raw_samples,
        cache=cache,
    )
    second = contextual_baseline.stored_contextual_samples(
        "hvac",
        raw_samples,
        cache=cache,
    )

    assert first == second
    assert calls == 1


def test_upsert_contextual_sample_keeps_update_cache_synchronized(
    monkeypatch,
) -> None:
    raw_samples = [
        {
            "timestamp": datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
            "feature": "daily_energy_kwh",
            "value": 12.0,
            "context": {"season": "summer"},
        }
    ]
    calls = 0
    original = contextual_baseline.contextual_sample_from_dict

    def counting_sample_from_dict(circuit_id: str, raw: dict[str, object]):
        nonlocal calls
        calls += 1
        return original(circuit_id, raw)

    monkeypatch.setattr(
        contextual_baseline,
        "contextual_sample_from_dict",
        counting_sample_from_dict,
    )
    cache = {}
    contextual_baseline.stored_contextual_samples(
        "hvac",
        raw_samples,
        cache=cache,
    )

    contextual_baseline.upsert_contextual_sample(
        raw_samples,
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 2, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=13.0,
            context=ContextKey.from_mapping({"season": "summer"}),
        ),
        cache=cache,
    )
    after_append = contextual_baseline.stored_contextual_samples(
        "hvac",
        raw_samples,
        cache=cache,
    )

    contextual_baseline.upsert_contextual_sample(
        raw_samples,
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 2, tzinfo=UTC),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=14.0,
            context=ContextKey.from_mapping({"season": "summer"}),
        ),
        cache=cache,
    )
    after_replace = contextual_baseline.stored_contextual_samples(
        "hvac",
        raw_samples,
        cache=cache,
    )

    assert calls == 1
    assert [sample.value for sample in after_append] == [12.0, 13.0]
    assert [sample.value for sample in after_replace] == [12.0, 14.0]
    assert len(cache) == 1


def test_exact_context_requires_matching_dimension_set() -> None:
    less_specific = ContextKey.from_mapping({"season": "summer"})
    more_specific = ContextKey.from_mapping(
        {"season": "summer", "temperature_bin": "very_hot"}
    )
    samples = [
        ContextualBaselineSample(
            timestamp=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(days=offset),
            circuit_id="hvac",
            feature="daily_energy_kwh",
            value=12.0 + offset,
            context=more_specific,
        )
        for offset in range(7)
    ]

    stats = build_contextual_baseline(
        circuit_id="hvac",
        feature="daily_energy_kwh",
        context=less_specific,
        samples=samples,
        fallback_level="exact_context",
        required_samples=7,
    )

    assert stats is None


def test_build_context_for_hvac_sample_uses_existing_weather_evidence() -> None:
    now = datetime(2026, 6, 17, 15, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    state = AnalyzerState(
        weather_context_by_circuit={
            "hvac": {
                "temperature_f": 94.0,
                "mode": "cooling",
            }
        }
    )

    context = build_context_for_sample(
        circuit_config=config,
        sample=_sample("hvac", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="daily_energy_kwh",
    )

    assert context.as_dict() == {
        "appliance_profile": "hvac",
        "circuit_mode": "dual_phase",
        "day_progress": "60-70%",
        "season": "summer",
        "temperature_bin": "very_hot",
        "time_of_day": "afternoon",
        "weather_mode": "cooling",
    }


def test_build_context_for_sample_uses_sample_local_calendar() -> None:
    sample_time = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    now = datetime(2026, 6, 2, 15, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )

    context = build_context_for_sample(
        circuit_config=config,
        sample=_sample("ev", sample_time),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        now=now,
        feature="peak_demand_w",
        time_zone="America/New_York",
    )

    values = context.as_dict()
    assert values["season"] == "spring"
    assert values["day_type"] == "weekend"
    assert values["time_of_day"] == "evening"


def test_build_context_for_sample_accepts_rollup_calendar_timestamp() -> None:
    sample_time = datetime(2026, 5, 30, 15, 30, tzinfo=UTC)
    rollup_time = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )

    context = build_context_for_sample(
        circuit_config=config,
        sample=_sample("ev", sample_time),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        now=rollup_time,
        feature="peak_demand_w",
        time_zone="America/New_York",
        calendar_timestamp=rollup_time,
    )

    values = context.as_dict()
    assert values["season"] == "spring"
    assert values["day_type"] == "weekend"
    assert values["time_of_day"] == "evening"


def test_build_context_for_sample_carries_rain_context_issue() -> None:
    now = datetime(2026, 6, 17, 15, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="sump",
        name="Sump Pump",
        appliance_profile=ApplianceProfile.SUMP_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
    )
    state = AnalyzerState(
        rain_pump_context_by_circuit={
            "sump": {
                "rain_sensor_active": False,
                "rain_intensity_mm_per_hour": 0.35,
                "rain_context_issues": ["rain_activity_conflict"],
            }
        }
    )

    context = build_context_for_sample(
        circuit_config=config,
        sample=_sample("sump", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="daily_energy_kwh",
    )

    assert context.as_dict() == {
        "appliance_profile": "sump_pump",
        "circuit_mode": "single_phase",
        "day_progress": "60-70%",
        "rain_context_issue": "rain_activity_conflict",
        "rain_intensity_bin": "moderate",
        "rain_state": "ambiguous",
        "season": "summer",
    }


def test_build_context_preserves_raw_rain_conflict_when_unit_unknown() -> None:
    now = datetime(2026, 6, 17, 15, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="sump",
        name="Sump Pump",
        appliance_profile=ApplianceProfile.SUMP_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
    )
    state = AnalyzerState(
        rain_pump_context_by_circuit={
            "sump": {
                "rain_sensor_active": False,
                "rain_intensity_per_hour": 0.35,
                "rain_intensity_unit": None,
                "rain_intensity_mm_per_hour": None,
                "rain_context_issues": ["rain_intensity_unit_missing"],
            }
        }
    )

    context = build_context_for_sample(
        circuit_config=config,
        sample=_sample("sump", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="daily_energy_kwh",
    )

    assert context.as_dict() == {
        "appliance_profile": "sump_pump",
        "circuit_mode": "single_phase",
        "day_progress": "60-70%",
        "rain_context_issue": "rain_activity_conflict",
        "rain_intensity_bin": "unknown",
        "rain_state": "unknown",
        "season": "summer",
    }


def test_upsert_contextual_sample_replaces_same_ha_local_date() -> None:
    context = ContextKey.from_mapping({"season": "summer"})
    samples: list[dict[str, object]] = []
    first = ContextualBaselineSample(
        timestamp=datetime(2026, 6, 2, 23, 30, tzinfo=UTC),
        circuit_id="hvac",
        feature="daily_energy_kwh",
        value=8.0,
        context=context,
    )
    second = ContextualBaselineSample(
        timestamp=datetime(2026, 6, 3, 3, 30, tzinfo=UTC),
        circuit_id="hvac",
        feature="daily_energy_kwh",
        value=9.0,
        context=context,
    )

    upsert_contextual_sample(samples, first, time_zone="America/New_York")
    upsert_contextual_sample(samples, second, time_zone="America/New_York")

    assert len(samples) == 1
    assert samples[0]["timestamp"] == "2026-06-03T03:30:00+00:00"
    assert samples[0]["value"] == 9.0




def test_build_context_for_water_and_solar_state() -> None:
    now = datetime(2026, 6, 17, 21, tzinfo=UTC)
    water_config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    solar_config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    state = AnalyzerState(
        water_flow_context_by_circuit={
            "water_heater": {
                "flow_sensor_active": True,
                "flow_active_minutes": 8.0,
            }
        },
        solar_flow_status_by_circuit={"mains": "exporting"},
        solar_flow_evidence_by_circuit={
            "mains": {"solar_surplus_status": "high_surplus"}
        },
    )

    water_context = build_context_for_sample(
        circuit_config=water_config,
        sample=_sample("water_heater", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="runtime_minutes",
    )
    solar_context = build_context_for_sample(
        circuit_config=solar_config,
        sample=_sample("mains", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="grid_export_power",
    )

    assert water_context.as_dict()["water_flow_state"] == "active_flow"
    assert water_context.as_dict()["day_type"] == "weekday"
    assert water_context.as_dict()["time_of_day"] == "evening"
    assert solar_context.as_dict()["solar_flow_state"] == "high_surplus"
    assert solar_context.as_dict()["power_flow_mode"] == "mains_net"


def test_load_context_uses_site_solar_flow_state() -> None:
    now = datetime(2026, 6, 20, 14, tzinfo=UTC)
    ev_config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    state = AnalyzerState(
        solar_flow_status_by_circuit={"mains": "exporting"},
        solar_flow_evidence_by_circuit={
            "mains": {"solar_surplus_status": "high_surplus"}
        },
    )

    context = build_context_for_sample(
        circuit_config=ev_config,
        sample=_sample("ev", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="peak_demand_w",
    )

    assert context.as_dict()["day_type"] == "weekend"
    assert context.as_dict()["solar_flow_state"] == "high_surplus"


def test_load_context_prefers_explicit_mains_site_solar_context() -> None:
    now = datetime(2026, 6, 20, 14, tzinfo=UTC)
    ev_config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    state = AnalyzerState(
        solar_flow_status_by_circuit={
            "solar_array": "no_generation",
            "mains": "exporting",
        },
        solar_flow_evidence_by_circuit={
            "solar_array": {"solar_surplus_status": "no_surplus"},
            "mains": {"solar_surplus_status": "high_surplus"},
        },
    )

    context = build_context_for_sample(
        circuit_config=ev_config,
        sample=_sample("ev", now),
        state=state,
        store_data=FeatureStoreData(),
        now=now,
        feature="peak_demand_w",
    )

    assert context.as_dict()["solar_flow_state"] == "high_surplus"


def _sample(circuit_id: str, timestamp: datetime) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=timestamp,
        circuit_id=circuit_id,
        real_power=120.0,
        current=1.0,
        voltage=120.0,
        energy=10.0,
    )
