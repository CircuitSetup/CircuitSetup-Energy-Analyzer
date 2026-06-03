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
    demand_settings_by_circuit = {
        "hvac": {"window_minutes": 15, "demand_limit_w": 4500.0}
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
        energy_usage_by_circuit=energy_usage_by_circuit,
        demand_settings_by_circuit=demand_settings_by_circuit,
        demand_by_circuit=demand_by_circuit,
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
    assert pruned.energy_usage_by_circuit is data.energy_usage_by_circuit
    assert pruned.demand_settings_by_circuit is data.demand_settings_by_circuit
    assert pruned.demand_by_circuit is data.demand_by_circuit
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
        demand_settings_by_circuit={
            "hvac": {"window_minutes": 15, "demand_limit_w": 4500.0}
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
    assert restored.demand_settings_by_circuit["hvac"] == {
        "window_minutes": 15,
        "demand_limit_w": 4500.0,
    }
    assert restored.demand_by_circuit["hvac"]["daily_peaks"] == [
        {"date": "2026-06-02", "peak_demand_w": 3200.0}
    ]
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
