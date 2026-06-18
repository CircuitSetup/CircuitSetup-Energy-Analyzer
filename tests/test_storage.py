from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    BaselineStats,
    CircuitEvent,
    EventType,
    RetentionMode,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import (
    FeatureStoreData,
    alert_from_dict,
    alert_to_dict,
    baseline_from_dict,
    baseline_to_dict,
    event_from_dict,
    event_to_dict,
    feature_store_data_from_dict,
    feature_store_data_to_dict,
    prune_events,
)


def test_prune_events_uses_retention_mode_and_preserves_other_data() -> None:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    old = CircuitEvent(
        timestamp=now - timedelta(days=45),
        circuit_id="fridge",
        event_type=EventType.START,
    )
    recent = CircuitEvent(
        timestamp=now - timedelta(days=5),
        circuit_id="fridge",
        event_type=EventType.STOP,
    )
    baseline = BaselineStats("startup_power_w", 4, 100.0, 5.0, 90.0, 110.0, 0.7)
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
    )
    signatures = {"mains": [{"label": "unknown", "confidence": 0.5}]}
    sensitivity_by_circuit = {"fridge": "quiet"}
    maintenance_by_circuit = {"fridge": {"active": True}}
    alert_feedback = {"fridge:reactive_power": {"action": "expected"}}
    energy_usage_settings_by_circuit = {
        "fridge": {"window_days": 14, "daily_spike_ratio": 0.2}
    }
    energy_goal_settings_by_circuit = {
        "fridge": {"daily_goal_kwh": 12.0, "goal_alert_ratio": 1.0}
    }
    demand_settings_by_circuit = {
        "hvac": {"window_minutes": 15, "demand_limit_w": 4500.0}
    }
    capacity_settings_by_circuit = {
        "ev": {"breaker_amps": 40.0, "warning_ratio": 0.8}
    }
    utility_comparison_settings_by_circuit = {
        "mains": {
            "utility_energy_entity": "sensor.opower_current_bill_usage",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 10.0,
        }
    }
    standby_settings_by_circuit = {
        "office": {
            "window_hours": 24,
            "standby_threshold_w": 8.0,
            "always_on_alert_w": 25.0,
        }
    }
    standby_by_circuit = {
        "office": {
            "samples": [
                {"timestamp": now.isoformat(), "real_power_w": 6.0},
            ],
        }
    }
    demand_by_circuit = {
        "hvac": {
            "samples": [
                {"timestamp": now.isoformat(), "real_power_w": 3200.0},
            ],
            "daily_peaks": [{"date": "2026-06-02", "peak_demand_w": 3200.0}],
        }
    }
    energy_usage_by_circuit = {
        "fridge": {
            "last_energy_kwh": 112.5,
            "last_sample_at": now.isoformat(),
            "days": [{"date": "2026-06-02", "usage_kwh": 8.5}],
        }
    }
    data = FeatureStoreData(
        events=[old, recent],
        baselines={"fridge:startup_power_w": baseline},
        alerts=[alert],
        nilm_signatures=signatures,
        sensitivity_by_circuit=sensitivity_by_circuit,
        maintenance_by_circuit=maintenance_by_circuit,
        alert_feedback=alert_feedback,
        energy_usage_settings_by_circuit=energy_usage_settings_by_circuit,
        energy_goal_settings_by_circuit=energy_goal_settings_by_circuit,
        energy_usage_by_circuit=energy_usage_by_circuit,
        demand_settings_by_circuit=demand_settings_by_circuit,
        demand_by_circuit=demand_by_circuit,
        capacity_settings_by_circuit=capacity_settings_by_circuit,
        utility_comparison_settings_by_circuit=(
            utility_comparison_settings_by_circuit
        ),
        standby_settings_by_circuit=standby_settings_by_circuit,
        standby_by_circuit=standby_by_circuit,
    )

    pruned = prune_events(data, RetentionMode.LIGHTWEIGHT, now)

    assert pruned.events == [recent]
    assert pruned.baselines is data.baselines
    assert pruned.alerts is data.alerts
    assert pruned.nilm_signatures is data.nilm_signatures
    assert pruned.sensitivity_by_circuit is data.sensitivity_by_circuit
    assert pruned.maintenance_by_circuit is data.maintenance_by_circuit
    assert pruned.alert_feedback is data.alert_feedback
    assert (
        pruned.energy_usage_settings_by_circuit
        is data.energy_usage_settings_by_circuit
    )
    assert (
        pruned.energy_goal_settings_by_circuit
        is data.energy_goal_settings_by_circuit
    )
    assert pruned.energy_usage_by_circuit is data.energy_usage_by_circuit
    assert pruned.demand_settings_by_circuit is data.demand_settings_by_circuit
    assert pruned.demand_by_circuit is data.demand_by_circuit
    assert pruned.capacity_settings_by_circuit is data.capacity_settings_by_circuit
    assert (
        pruned.utility_comparison_settings_by_circuit
        is data.utility_comparison_settings_by_circuit
    )
    assert pruned.standby_settings_by_circuit is data.standby_settings_by_circuit
    assert pruned.standby_by_circuit is data.standby_by_circuit
    assert data.events == [old, recent]


def test_standard_retention_keeps_at_least_month_of_events() -> None:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    event = CircuitEvent(
        timestamp=now - timedelta(days=31),
        circuit_id="fridge",
        event_type=EventType.START,
    )
    data = FeatureStoreData(
        events=[event],
        baselines={},
        alerts=[],
        nilm_signatures={},
    )

    pruned = prune_events(data, RetentionMode.STANDARD, now)

    assert pruned.events == [event]


def test_storage_migrates_legacy_sensitivity_names_on_load_and_save() -> None:
    restored = feature_store_data_from_dict(
        {
            "sensitivity_by_circuit": {
                "freezer": "low",
                "fridge": "standard",
                "dryer": "high",
                "mystery": "surprising",
            }
        }
    )

    assert restored.sensitivity_by_circuit == {
        "freezer": "quiet",
        "fridge": "balanced",
        "dryer": "sensitive",
        "mystery": "balanced",
    }

    raw = feature_store_data_to_dict(
        FeatureStoreData(
            sensitivity_by_circuit={
                "freezer": "low",
                "fridge": "standard",
                "dryer": "high",
                "mystery": "surprising",
            }
        )
    )

    assert raw["sensitivity_by_circuit"] == {
        "freezer": "quiet",
        "fridge": "balanced",
        "dryer": "sensitive",
        "mystery": "balanced",
    }


def test_feature_store_round_trips_unknown_load_inventory() -> None:
    data = FeatureStoreData(
        nilm_unknown_loads_by_circuit={
            "mains": {
                "unknown_load_count": 1,
                "unknown_loads": [
                    {
                        "signature_id": "on-1",
                        "likely_type": "motor",
                        "estimated_energy_today_kwh": 0.42,
                    }
                ],
            }
        }
    )

    restored = feature_store_data_from_dict(feature_store_data_to_dict(data))

    assert restored.nilm_unknown_loads_by_circuit == data.nilm_unknown_loads_by_circuit


def test_feature_store_round_trips_weather_context() -> None:
    data = FeatureStoreData(
        weather_context_by_circuit={
            "hvac": {
                "status": "weather_correlated",
                "current_outdoor_temperature": 91.0,
            }
        },
        weather_context_history_by_circuit={
            "hvac": [
                {
                    "timestamp": "2026-06-02T12:00:00+00:00",
                    "temperature": 91.0,
                    "runtime_minutes": 180.0,
                    "duty_cycle_percent": 45.0,
                }
            ]
        },
    )

    restored = feature_store_data_from_dict(feature_store_data_to_dict(data))

    assert restored.weather_context_by_circuit == data.weather_context_by_circuit
    assert (
        restored.weather_context_history_by_circuit
        == data.weather_context_history_by_circuit
    )


def test_feature_store_round_trips_water_correlation_state() -> None:
    data = FeatureStoreData(
        rain_pump_context_by_circuit={
            "sump_pump": {
                "status": "rain_explained",
                "pump_runtime_minutes": 18.0,
            }
        },
        water_flow_context_by_circuit={
            "washer": {
                "status": "possible_flow_without_load",
                "mismatch_minutes": 14.0,
            }
        },
        water_context_history_by_circuit={
            "sump_pump": [
                {
                    "timestamp": "2026-06-10T12:00:00+00:00",
                    "rain_status": "rain_explained",
                }
            ]
        },
    )

    restored = feature_store_data_from_dict(feature_store_data_to_dict(data))

    assert restored.rain_pump_context_by_circuit == data.rain_pump_context_by_circuit
    assert restored.water_flow_context_by_circuit == data.water_flow_context_by_circuit
    assert (
        restored.water_context_history_by_circuit
        == data.water_context_history_by_circuit
    )


def test_feature_store_loads_without_contextual_baselines() -> None:
    restored = feature_store_data_from_dict({"events": []})

    assert restored.contextual_baseline_samples_by_circuit == {}
    assert restored.contextual_baselines_by_circuit == {}


def test_feature_store_round_trips_contextual_baselines() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    data = FeatureStoreData(
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": now.isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": 8.4,
                    "context": {
                        "season": "summer",
                        "temperature_bin": "very_hot",
                    },
                    "source": "energy_usage",
                }
            ]
        },
        contextual_baselines_by_circuit={
            "hvac": {
                "daily_energy_kwh|season=summer|temperature_bin=very_hot": {
                    "feature": "daily_energy_kwh",
                    "context_fingerprint": (
                        "season=summer|temperature_bin=very_hot"
                    ),
                    "context": {
                        "season": "summer",
                        "temperature_bin": "very_hot",
                    },
                    "sample_count": 12,
                    "median": 7.8,
                    "mad": 0.9,
                    "p10": 6.4,
                    "p90": 9.2,
                    "confidence": 0.8,
                    "fallback_level": "exact_context",
                    "first_seen": "2026-06-01T00:00:00+00:00",
                    "last_seen": now.isoformat(),
                }
            }
        },
    )

    restored = feature_store_data_from_dict(feature_store_data_to_dict(data))

    assert restored.contextual_baseline_samples_by_circuit == (
        data.contextual_baseline_samples_by_circuit
    )
    assert restored.contextual_baselines_by_circuit == (
        data.contextual_baselines_by_circuit
    )


def test_prune_events_prunes_contextual_samples_and_enforces_cap() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    samples = [
        {
            "timestamp": (now - timedelta(days=day)).isoformat(),
            "feature": "daily_energy_kwh",
            "value": float(day),
            "context": {"season": "summer"},
        }
        for day in range(20, -1, -1)
    ]
    data = FeatureStoreData(
        contextual_baseline_samples_by_circuit={"hvac": samples},
        contextual_baselines_by_circuit={"hvac": {"old": {"feature": "x"}}},
    )

    pruned = prune_events(
        data,
        RetentionMode.LIGHTWEIGHT,
        now,
        contextual_sample_cap_per_circuit=5,
    )

    retained = pruned.contextual_baseline_samples_by_circuit["hvac"]
    assert len(retained) == 5
    assert [sample["value"] for sample in retained] == [4.0, 3.0, 2.0, 1.0, 0.0]
    assert (
        pruned.contextual_baselines_by_circuit
        is data.contextual_baselines_by_circuit
    )


def test_prune_events_caps_contextual_stats_per_feature_by_strength() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)

    def stats_payload(
        key: str,
        *,
        feature: str = "daily_energy_kwh",
        sample_count: int,
        last_seen: datetime,
    ) -> tuple[str, dict[str, object]]:
        context = dict(part.split("=", 1) for part in key.split("|"))
        return (
            f"{feature}|{key}",
            {
                "feature": feature,
                "context_fingerprint": key,
                "context": context,
                "sample_count": sample_count,
                "median": 8.0,
                "mad": 0.5,
                "p10": 7.0,
                "p90": 9.0,
                "confidence": 0.8,
                "fallback_level": "exact_context",
                "first_seen": (last_seen - timedelta(days=7)).isoformat(),
                "last_seen": last_seen.isoformat(),
            },
        )

    weak_key, weak_stats = stats_payload(
        "season=summer|temperature_bin=warm",
        sample_count=3,
        last_seen=now,
    )
    strong_key, strong_stats = stats_payload(
        "season=summer|temperature_bin=hot",
        sample_count=12,
        last_seen=now - timedelta(days=2),
    )
    recent_tie_key, recent_tie_stats = stats_payload(
        "season=summer|temperature_bin=mild",
        sample_count=12,
        last_seen=now,
    )
    demand_key, demand_stats = stats_payload(
        "season=summer|time_of_day=afternoon",
        feature="demand_peak_w",
        sample_count=2,
        last_seen=now,
    )
    data = FeatureStoreData(
        contextual_baselines_by_circuit={
            "hvac": {
                weak_key: weak_stats,
                strong_key: strong_stats,
                recent_tie_key: recent_tie_stats,
                demand_key: demand_stats,
            }
        }
    )

    pruned = prune_events(
        data,
        RetentionMode.LIGHTWEIGHT,
        now,
        contextual_bucket_cap_per_feature=2,
    )

    assert set(pruned.contextual_baselines_by_circuit["hvac"]) == {
        recent_tie_key,
        strong_key,
        demand_key,
    }


def test_feature_store_drops_malformed_contextual_baseline_entries() -> None:
    restored = feature_store_data_from_dict(
        {
            "contextual_baseline_samples_by_circuit": {
                "hvac": [
                    {
                        "timestamp": "not-a-date",
                        "feature": "daily_energy_kwh",
                        "value": "bad",
                        "context": [],
                    },
                    {
                        "timestamp": "2026-06-17T12:00:00+00:00",
                        "feature": "daily_energy_kwh",
                        "value": 8.4,
                        "context": {"season": "summer"},
                    },
                ]
            },
            "contextual_baselines_by_circuit": {
                "hvac": {
                    "bad": [],
                    "good": {
                        "feature": "daily_energy_kwh",
                        "context_fingerprint": "season=summer",
                        "context": {"season": "summer"},
                        "sample_count": 7,
                        "median": 8.0,
                        "mad": 1.0,
                        "p10": 6.0,
                        "p90": 10.0,
                        "confidence": 0.8,
                    },
                }
            },
        }
    )

    assert restored.contextual_baseline_samples_by_circuit == {
        "hvac": [
            {
                "timestamp": "2026-06-17T12:00:00+00:00",
                "feature": "daily_energy_kwh",
                "value": 8.4,
                "context": {"season": "summer"},
            }
        ]
    }
    assert list(restored.contextual_baselines_by_circuit["hvac"]) == ["good"]


def test_event_round_trip_serialization_uses_current_shape() -> None:
    event = CircuitEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        event_type=EventType.VOLTAGE_SAG,
        severity=Severity.WARNING,
        features={"startup_power_w": 412.4, "voltage_drop_ratio": 0.12},
    )

    raw = event_to_dict(event)
    restored = event_from_dict(raw)

    assert raw == {
        "timestamp": "2026-06-02T12:00:00+00:00",
        "circuit_id": "fridge",
        "event_type": "voltage_sag",
        "severity": "warning",
        "features": {"startup_power_w": 412.4, "voltage_drop_ratio": 0.12},
    }
    assert restored == event
    assert isinstance(restored.features, MappingProxyType)


def test_baseline_and_alert_serialization_are_json_safe() -> None:
    baseline = BaselineStats(
        feature="cycle_duration_s",
        sample_count=15,
        median=360.0,
        mad=12.0,
        p10=330.0,
        p90=390.0,
        confidence=1.0,
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        event_type=EventType.STEADY_WINDOW,
        features={"cycle_duration_s": 2.4},
        feature="cycle_duration_s",
        observed_value=420.0,
        baseline_value=360.0,
        change_ratio=0.1667,
        repeated_count=3,
        first_seen=datetime(2026, 6, 2, 10, 30, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
    )

    baseline_raw = baseline_to_dict(baseline)
    alert_raw = alert_to_dict(alert)

    assert baseline_from_dict(baseline_raw) == baseline
    assert alert_from_dict(alert_raw) == alert
    assert alert_raw["features"] == {"cycle_duration_s": 2.4}
    assert isinstance(alert_raw["features"], dict)


def test_feature_store_round_trips_user_experience_state() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    data = FeatureStoreData(
        sensitivity_by_circuit={"fridge": "quiet"},
        maintenance_by_circuit={
            "fridge": {
                "active": True,
                "note": "Cleaned coils",
                "started_at": now.isoformat(),
                "relearn_on_end": True,
            }
        },
        alert_feedback={
            "fridge:reactive_power": {
                "action": "expected",
                "alert_id": "alert-1",
                "created_at": now.isoformat(),
                "change_ratio": 0.42,
            }
        },
        energy_usage_settings_by_circuit={
            "fridge": {"window_days": 14, "daily_spike_ratio": 0.2}
        },
        energy_goal_settings_by_circuit={
            "fridge": {"daily_goal_kwh": 12.0, "goal_alert_ratio": 1.0}
        },
        activity_alert_settings_by_circuit={
            "fridge": {"max_active_minutes": 45.0, "max_idle_minutes": 120.0}
        },
        billing_settings_by_circuit={
            "fridge": {
                "cycle_start_day": 15,
                "budget_kwh": 300.0,
                "budget_alert_ratio": 0.9,
            }
        },
        billing_by_circuit={
            "fridge": {
                "cycle_start": "2026-05-15",
                "cycle_end": "2026-06-15",
                "cycle_usage_kwh": 42.0,
                "last_energy_kwh": 112.5,
                "last_sample_at": now.isoformat(),
            }
        },
        cost_settings_by_circuit={
            "fridge": {
                "cycle_start_day": 1,
                "default_rate_per_kwh": 0.2,
                "tou_rate_per_kwh": 0.3,
                "tou_start": "17:00",
                "tou_end": "21:00",
                "tou_weekdays": "0,1,2,3,4",
                "tou_name": "Peak",
            }
        },
        cost_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_end": "2026-07-01",
                "cycle_cost": 18.0,
                "last_energy_kwh": 112.5,
                "last_sample_at": now.isoformat(),
            }
        },
        demand_settings_by_circuit={
            "hvac": {"window_minutes": 15, "demand_limit_w": 4500.0}
        },
        capacity_settings_by_circuit={
            "ev": {"breaker_amps": 40.0, "warning_ratio": 0.8}
        },
        utility_comparison_settings_by_circuit={
            "mains": {
                "utility_energy_entity": "sensor.opower_current_bill_usage",
                "measured_energy_entities": ["sensor.panel_import_energy"],
                "tolerance_percent": 10.0,
            }
        },
        standby_settings_by_circuit={
            "office": {
                "window_hours": 24,
                "standby_threshold_w": 8.0,
                "always_on_alert_w": 25.0,
            }
        },
        standby_by_circuit={
            "office": {
                "samples": [{"timestamp": now.isoformat(), "real_power_w": 6.0}],
            }
        },
        demand_by_circuit={
            "hvac": {
                "samples": [{"timestamp": now.isoformat(), "real_power_w": 3200.0}],
                "daily_peaks": [{"date": "2026-06-02", "peak_demand_w": 3200.0}],
            }
        },
        nilm_signatures={
            "mains": [
                {
                    "signature_id": "on-1",
                    "review_state": "expected",
                    "user_label": "Microwave",
                }
            ]
        },
        energy_usage_by_circuit={
            "fridge": {
                "last_energy_kwh": 112.5,
                "last_sample_at": now.isoformat(),
                "days": [{"date": "2026-06-02", "usage_kwh": 8.5}],
            }
        },
    )

    raw = feature_store_data_to_dict(data)
    restored = feature_store_data_from_dict(raw)

    assert restored.sensitivity_by_circuit == {"fridge": "quiet"}
    assert restored.maintenance_by_circuit["fridge"]["note"] == "Cleaned coils"
    assert restored.alert_feedback["fridge:reactive_power"]["action"] == "expected"
    assert restored.energy_usage_settings_by_circuit["fridge"] == {
        "window_days": 14,
        "daily_spike_ratio": 0.2,
    }
    assert restored.energy_goal_settings_by_circuit["fridge"] == {
        "daily_goal_kwh": 12.0,
        "goal_alert_ratio": 1.0,
    }
    assert restored.activity_alert_settings_by_circuit["fridge"] == {
        "max_active_minutes": 45.0,
        "max_idle_minutes": 120.0,
    }
    assert restored.billing_settings_by_circuit["fridge"] == {
        "cycle_start_day": 15,
        "budget_kwh": 300.0,
        "budget_alert_ratio": 0.9,
    }
    assert restored.billing_by_circuit["fridge"]["cycle_usage_kwh"] == 42.0
    assert restored.cost_settings_by_circuit["fridge"] == {
        "cycle_start_day": 1,
        "default_rate_per_kwh": 0.2,
        "tou_rate_per_kwh": 0.3,
        "tou_start": "17:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,1,2,3,4",
        "tou_name": "Peak",
    }
    assert restored.cost_by_circuit["fridge"]["cycle_cost"] == 18.0
    assert restored.demand_settings_by_circuit["hvac"] == {
        "window_minutes": 15,
        "demand_limit_w": 4500.0,
    }
    assert restored.demand_by_circuit["hvac"]["daily_peaks"] == [
        {"date": "2026-06-02", "peak_demand_w": 3200.0}
    ]
    assert restored.capacity_settings_by_circuit["ev"] == {
        "breaker_amps": 40.0,
        "warning_ratio": 0.8,
    }
    assert restored.utility_comparison_settings_by_circuit["mains"] == {
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 10.0,
    }
    assert restored.standby_settings_by_circuit["office"] == {
        "window_hours": 24,
        "standby_threshold_w": 8.0,
        "always_on_alert_w": 25.0,
    }
    assert restored.standby_by_circuit["office"]["samples"] == [
        {"timestamp": now.isoformat(), "real_power_w": 6.0}
    ]
    assert restored.nilm_signatures["mains"][0]["review_state"] == "expected"
    assert restored.energy_usage_by_circuit["fridge"]["days"] == [
        {"date": "2026-06-02", "usage_kwh": 8.5}
    ]


def test_feature_store_preserves_settings_recommendations() -> None:
    raw = {
        "settings_recommendations": {
            "rec-hvac-daily-spike": {
                "recommendation_id": "rec-hvac-daily-spike",
                "unique_key": "hvac:daily_spike_ratio",
                "circuit_id": "hvac",
                "circuit_name": "HVAC",
                "setting_key": "daily_spike_ratio",
                "setting_label": "Daily spike ratio",
                "current_value": 0.25,
                "suggested_value": 0.35,
                "unit": "ratio",
                "feature": "daily_energy_spike_ratio",
                "group": "energy_usage",
                "confidence": 0.82,
                "reason": "Recent usage is above the configured threshold.",
                "evidence": {"observed_ratio": 0.43, "sample_days": 14},
                "apply_payload": {"daily_spike_ratio": 0.35},
                "status": "pending",
                "created_at": "2026-06-02T12:00:00+00:00",
                "expires_at": "2026-07-02T12:00:00+00:00",
                "advisor_version": 1,
            }
        },
        "settings_recommendation_decisions": {
            "hvac:daily_spike_ratio": {
                "unique_key": "hvac:daily_spike_ratio",
                "status": "denied",
                "decided_at": "2026-06-03T12:00:00+00:00",
                "denied_value": 0.35,
                "evidence_fingerprint": "observed-ratio-043",
            }
        },
        "settings_recommendation_notification_episode_key": [
            [
                "rec-hvac-daily-spike",
                "hvac",
                "daily_spike_ratio",
                "0.25",
                "0.35",
                "[('daily_spike_ratio', 0.35)]",
                "Recent usage is above the configured threshold.",
                "(('observed_ratio', 0.43), ('sample_days', 14))",
            ]
        ],
    }

    restored = feature_store_data_from_dict(raw)
    serialized = feature_store_data_to_dict(restored)

    assert serialized["settings_recommendations"] == raw["settings_recommendations"]
    assert (
        serialized["settings_recommendation_decisions"]
        == raw["settings_recommendation_decisions"]
    )
    assert (
        serialized["settings_recommendation_notification_episode_key"]
        == raw["settings_recommendation_notification_episode_key"]
    )
