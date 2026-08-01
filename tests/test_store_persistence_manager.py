from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.store_persistence import (
    StorePersistenceManager,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.settings_advisor import (
    RecommendationStatus,
    SettingRecommendation,
)
from custom_components.circuitsetup_energy_analyzer.storage import (
    BaselineStats,
    FeatureStoreData,
)


def test_store_persistence_resets_circuit_baselines_and_alerts() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": BaselineStats(
                "real_power",
                4,
                120.0,
                10.0,
                100.0,
                140.0,
                0.8,
            ),
            "washer:real_power": BaselineStats(
                "real_power",
                4,
                400.0,
                25.0,
                350.0,
                450.0,
                0.8,
            ),
        },
        alerts=[
            AlertEvidence(
                timestamp=now,
                circuit_id="fridge",
                severity=Severity.WARNING,
                message="Fridge alert.",
                feature="energy_usage",
            ),
            AlertEvidence(
                timestamp=now,
                circuit_id="washer",
                severity=Severity.WARNING,
                message="Washer alert.",
                feature="energy_usage",
            ),
        ],
        events=[
            CircuitEvent(now, "fridge", EventType.START),
            CircuitEvent(now, "washer", EventType.START),
        ],
        hvac_response_history_by_stream={
            "fridge|climate.kitchen|cooling": [{"complete": True}],
            "washer|climate.laundry|cooling": [{"complete": True}],
        },
        hvac_response_context_by_stream={
            "fridge|climate.kitchen|cooling": {"selected": "fridge"},
            "washer|climate.laundry|cooling": {"selected": "washer"},
        },
        hvac_baseline_era_by_stream={
            "fridge|climate.kitchen|cooling": "era-1",
            "washer|climate.laundry|cooling": "era-2",
        },
    )
    baseline_values = defaultdict(list)
    baseline_values["fridge:real_power"].append(120.0)
    baseline_values["washer:real_power"].append(400.0)
    manager = object.__new__(StorePersistenceManager)
    manager._coordinator = SimpleNamespace(store_data=store_data)
    manager._dirty_generation = 0
    manager.dirty = False

    manager.reset_baseline_for_circuit("fridge", baseline_values, now)

    assert store_data.baselines == {
        "washer:real_power": BaselineStats(
            "real_power",
            4,
            400.0,
            25.0,
            350.0,
            450.0,
            0.8,
        )
    }
    assert [alert.circuit_id for alert in store_data.alerts] == ["washer"]
    assert [event.circuit_id for event in store_data.events] == ["fridge", "washer"]
    assert store_data.hvac_response_history_by_stream == {
        "washer|climate.laundry|cooling": [{"complete": True}]
    }
    assert store_data.hvac_response_context_by_stream == {
        "washer|climate.laundry|cooling": {"selected": "washer"}
    }
    assert store_data.hvac_baseline_era_by_stream == {
        "washer|climate.laundry|cooling": "era-2"
    }
    assert store_data.learning_started_at_by_circuit == {
        "fridge": "2026-06-30T12:00:00+00:00"
    }
    assert dict(baseline_values) == {"washer:real_power": [400.0]}
    assert manager.dirty is True


def test_store_persistence_clears_direct_state_idempotently() -> None:
    now = datetime(2026, 7, 31, tzinfo=UTC)

    def recommendation(key, status, *, circuit_id="fridge"):
        return SettingRecommendation(
            recommendation_id=f"{circuit_id}:{key}:{status.value}",
            unique_key=f"{circuit_id}:{key}", circuit_id=circuit_id,
            circuit_name=circuit_id, setting_key=key, setting_label=key,
            current_value=1, suggested_value=2, unit=None, feature=key,
            group="test", confidence=1, reason="test", evidence={},
            apply_payload={}, status=status, created_at=now,
            expires_at=now + timedelta(days=1),
        )

    recommendations = {
        "pending-direct": recommendation(
            "standby_threshold_w", RecommendationStatus.PENDING
        ),
        "pending-pq": recommendation(
            "power_factor_tolerance", RecommendationStatus.PENDING
        ),
        "pending-aggregate": recommendation(
            "daily_spike_ratio", RecommendationStatus.PENDING
        ),
        "applied": recommendation("standby_threshold_w", RecommendationStatus.APPLIED),
        "dismissed": recommendation(
            "standby_threshold_w", RecommendationStatus.DISMISSED
        ),
        "denied": recommendation("standby_threshold_w", RecommendationStatus.DENIED),
        "stale": recommendation("standby_threshold_w", RecommendationStatus.STALE),
        "other": recommendation(
            "standby_threshold_w", RecommendationStatus.PENDING,
            circuit_id="washer",
        ),
    }
    store_data = FeatureStoreData(
        baselines={
            "fridge:run_cycle": BaselineStats("run_cycle", 1, 1, 0, 1, 1, 1),
            "washer:run_cycle": BaselineStats("run_cycle", 1, 1, 0, 1, 1, 1),
        },
        standby_by_circuit={"fridge": {"samples": []}, "washer": {"samples": []}},
        alerts=[
            AlertEvidence(
                now, "fridge", Severity.WARNING, "direct",
                feature="cycle_duration_change",
            ),
            AlertEvidence(
                now, "fridge", Severity.WARNING, "aggregate",
                feature="circuit_capacity",
            ),
            AlertEvidence(
                now, "washer", Severity.WARNING, "other",
                feature="cycle_duration_change",
            ),
        ],
        events=[
            CircuitEvent(now, "fridge", EventType.START),
            CircuitEvent(now, "washer", EventType.START),
        ],
        contextual_baseline_samples_by_circuit={
            "fridge": [
                {"feature": "run_cycle_duration_s", "value": 10},
                {"feature": "runtime_today_seconds", "value": 20},
                {"feature": "daily_energy_kwh", "value": 2},
            ],
            "washer": [{"feature": "standby_power_w", "value": 3}],
        },
        contextual_baselines_by_circuit={
            "fridge": {
                "cycle|x": {"feature": "run_cycle_daily_start_count"},
                "runtime|x": {"feature": "runtime_today_seconds"},
                "energy|x": {"feature": "daily_energy_kwh"},
            },
            "washer": {"standby|x": {"feature": "standby_power_w"}},
        },
        hvac_response_history_by_stream={
            "fridge|climate.x|cool": [{}], "washer|climate.x|cool": [{}]
        },
        hvac_baseline_era_by_stream={
            "fridge|climate.x|cool": "a", "washer|climate.x|cool": "b"
        },
        hvac_correlation_history_by_circuit={"fridge": [{}], "washer": [{}]},
        weather_context_by_circuit={"fridge": {}, "washer": {}},
        weather_context_history_by_circuit={"fridge": [{}], "washer": [{}]},
        rain_pump_context_by_circuit={"fridge": {}, "washer": {}},
        water_flow_context_by_circuit={"fridge": {}, "washer": {}},
        water_context_history_by_circuit={"fridge": [{}], "washer": [{}]},
        operating_detection_settings_by_circuit={"fridge": {}, "washer": {}},
        activity_alert_settings_by_circuit={"fridge": {}, "washer": {}},
        appliance_schedule_settings={
            "fridge": {},
            "circuit:fridge": {"start": "08:00"},
            "washer": {},
            "circuit:washer": {"start": "09:00"},
        },
        appliance_schedule_evidence={
            "fridge": {},
            "circuit:fridge": {"status": "due"},
            "washer": {},
            "circuit:washer": {"status": "normal"},
        },
        settings_recommendations=recommendations,
        energy_usage_by_circuit={"fridge": {"days": [{"date": "2026-07-31"}]}},
        billing_by_circuit={"fridge": {"usage": 1}},
        cost_by_circuit={"fridge": {"cost": 1}},
        demand_by_circuit={"fridge": {"peak": 1}},
        maintenance_by_circuit={"fridge": {"active": True}},
        alert_feedback={"fingerprint": {"circuit_id": "fridge"}},
    )
    manager = object.__new__(StorePersistenceManager)
    manager._coordinator = SimpleNamespace(store_data=store_data)
    manager._dirty_generation = 0
    manager.dirty = False
    baseline_values = {"fridge:run_cycle": [1.0], "washer:run_cycle": [1.0]}

    assert manager.clear_direct_appliance_state_for_circuit("fridge", baseline_values)
    assert not manager.clear_direct_appliance_state_for_circuit(
        "fridge", baseline_values
    )
    assert set(store_data.baselines) == {"washer:run_cycle"}
    assert set(baseline_values) == {"washer:run_cycle"}
    assert store_data.standby_by_circuit == {"washer": {"samples": []}}
    assert "fridge" in store_data.energy_usage_by_circuit
    assert [alert.feature for alert in store_data.alerts] == [
        "circuit_capacity", "cycle_duration_change"
    ]
    assert [event.circuit_id for event in store_data.events] == ["washer"]
    assert store_data.contextual_baseline_samples_by_circuit["fridge"] == [
        {"feature": "daily_energy_kwh", "value": 2}
    ]
    assert set(store_data.contextual_baselines_by_circuit["fridge"]) == {"energy|x"}
    for name in (
        "hvac_correlation_history_by_circuit", "weather_context_by_circuit",
        "weather_context_history_by_circuit", "rain_pump_context_by_circuit",
        "water_flow_context_by_circuit", "water_context_history_by_circuit",
        "operating_detection_settings_by_circuit", "activity_alert_settings_by_circuit",
        "appliance_schedule_settings", "appliance_schedule_evidence",
    ):
        expected = (
            {"washer", "circuit:washer"}
            if name.startswith("appliance_schedule_")
            else {"washer"}
        )
        assert set(getattr(store_data, name)) == expected
    statuses = {
        key: recommendation.status
        for key, recommendation in store_data.settings_recommendations.items()
    }
    assert statuses == {
        "pending-direct": RecommendationStatus.STALE,
        "pending-pq": RecommendationStatus.STALE,
        "pending-aggregate": RecommendationStatus.PENDING,
        "applied": RecommendationStatus.APPLIED,
        "dismissed": RecommendationStatus.DISMISSED,
        "denied": RecommendationStatus.DENIED,
        "stale": RecommendationStatus.STALE,
        "other": RecommendationStatus.PENDING,
    }
    assert store_data.billing_by_circuit and store_data.cost_by_circuit
    assert store_data.demand_by_circuit and store_data.maintenance_by_circuit
    assert store_data.alert_feedback


def test_store_persistence_manager_owns_retention_helper_behavior() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        nilm_signatures={
            "mains": [
                {"signature_id": "old", "last_seen": "2026-06-01T12:00:00+00:00"},
                {"signature_id": "new", "last_seen": "2026-06-30T12:00:00+00:00"},
            ],
        },
        nilm_session_history_by_circuit={
            "mains": [
                {"session_id": "stale", "end": "2026-05-01T12:00:00+00:00"},
                {"session_id": "fresh", "end": "2026-06-30T12:00:00+00:00"},
            ],
        },
    )
    coordinator = SimpleNamespace(store_data=store_data)
    manager = StorePersistenceManager(
        coordinator,
        retention_mode_for_circuit=lambda circuit_id: object(),
        ha_time_zone=lambda: "UTC",
        weather_context_history_max_samples=10,
        water_context_history_max_samples=10,
        alert_history_max_age=timedelta(days=180),
        alert_history_max_items=100,
        alert_feedback_max_age=timedelta(days=365),
        alert_feedback_max_items=100,
        nilm_signatures_max_items=1,
        nilm_unknown_loads_max_items=1,
        nilm_session_history_max_age=timedelta(days=45),
        nilm_session_history_max_items=10,
        recommendation_history_max_age=timedelta(days=180),
        recommendation_history_max_items=100,
        recommendation_decisions_max_age=timedelta(days=180),
        recommendation_decisions_max_items=100,
    )

    manager.prune_nilm_history(now)

    assert store_data.nilm_signatures["mains"] == [
        {"signature_id": "new", "last_seen": "2026-06-30T12:00:00+00:00"},
    ]
    assert store_data.nilm_session_history_by_circuit["mains"] == [
        {"session_id": "fresh", "end": "2026-06-30T12:00:00+00:00"},
    ]
