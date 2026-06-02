from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)


def test_normalize_sensitivity_accepts_friendly_and_legacy_names() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_policy_name_for_sensitivity,
        normalize_sensitivity,
    )

    assert normalize_sensitivity("quiet") == "quiet"
    assert normalize_sensitivity("low") == "quiet"
    assert normalize_sensitivity("balanced") == "balanced"
    assert normalize_sensitivity("standard") == "balanced"
    assert normalize_sensitivity("sensitive") == "sensitive"
    assert normalize_sensitivity("high") == "sensitive"
    assert normalize_sensitivity("surprising") == "balanced"
    assert alert_policy_name_for_sensitivity("quiet") == "low"
    assert alert_policy_name_for_sensitivity("balanced") == "standard"
    assert alert_policy_name_for_sensitivity("sensitive") == "high"


def test_alert_evidence_detail_is_json_safe_and_explains_change() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_evidence_detail,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        event_type=EventType.STEADY_WINDOW,
        feature="reactive_to_real_ratio",
        observed_value=0.42,
        baseline_value=0.24,
        change_ratio=0.75,
        repeated_count=4,
        first_seen=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        features={"reactive_power": 2.1, "power_factor": 1.2},
    )

    assert alert_evidence_detail(alert) == {
        "alert_id": notification_id_for_alert(alert),
        "circuit_id": "fridge",
        "feature": "reactive_to_real_ratio",
        "severity": "warning",
        "message": "Possible issue",
        "baseline_value": 0.24,
        "observed_value": 0.42,
        "change_ratio": 0.75,
        "percent_change": 75.0,
        "repeated_count": 4,
        "first_seen": "2026-06-02T10:00:00+00:00",
        "last_seen": "2026-06-02T12:30:00+00:00",
        "time_window": (
            "2026-06-02T10:00:00+00:00 to 2026-06-02T12:30:00+00:00"
        ),
        "contributing_metrics": {"power_factor": 1.2, "reactive_power": 2.1},
    }


def test_data_quality_checklist_reports_required_optional_and_sample_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import (
        data_quality_checklist,
    )

    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_w", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_var", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.fridge_pf", SensorRole.POWER_FACTOR),
        ),
    )
    sample = NormalizedCircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        real_power=120.0,
        reactive_power=35.0,
        power_factor=0.91,
        source_entity_ids=(
            "sensor.fridge_w",
            "sensor.fridge_var",
            "sensor.fridge_pf",
        ),
    )

    checklist = data_quality_checklist(config, sample)

    assert checklist["required_sensors_present"] is True
    assert checklist["optional_sensors_present"] is True
    assert checklist["numeric_states_valid"] is True
    assert checklist["source_data_fresh"] is True
    assert checklist["quality_issues"] == []
    assert checklist["metric_roles_present"] == [
        "power_factor",
        "reactive_power",
        "real_power",
    ]


def test_learning_progress_counts_age_cycles_and_baseline_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.models import BaselineStats
    from custom_components.circuitsetup_energy_analyzer.ux import learning_progress

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    events = [
        CircuitEvent(now - timedelta(days=8), "fridge", EventType.START),
        CircuitEvent(now - timedelta(days=7), "fridge", EventType.STOP),
        CircuitEvent(now - timedelta(days=1), "fridge", EventType.START),
    ]
    baselines = {
        "fridge:real_power": BaselineStats(
            "real_power",
            18,
            100.0,
            5.0,
            90.0,
            110.0,
            0.8,
        ),
        "other:real_power": BaselineStats(
            "real_power",
            18,
            50.0,
            4.0,
            45.0,
            55.0,
            0.9,
        ),
    }

    progress = learning_progress(
        config,
        events=events,
        baselines=baselines,
        baseline_buffer_counts={"fridge:reactive_power": 4},
        now=now,
        learning=True,
        suppression_reason="waiting_for_optional_metrics",
    )

    assert progress["baseline_age_days"] == 8.0
    assert progress["cycle_count"] == 2
    assert progress["baseline_confidence"] == 0.8
    assert progress["learned_feature_count"] == 1
    assert progress["learning"] is True
    assert progress["alert_ready"] is False
    assert progress["suppression_reason"] == "waiting_for_optional_metrics"
    assert progress["pending_feature_samples"] == {"reactive_power": 4}


def test_health_status_priority_order_is_dashboard_friendly() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import health_summary

    assert health_summary(data_quality_problem=True) == ("needs_data", "Needs data")
    assert health_summary(paused=True) == ("paused", "Paused")
    assert health_summary(active_alerts=True) == ("possible_issue", "Possible issue")
    assert health_summary(nilm_review_count=2) == ("nilm_review", "NILM review")
    assert health_summary(mixed=True) == ("mixed_observation", "Mixed observation")
    assert health_summary(learning=True) == ("learning", "Learning")
    assert health_summary() == ("ready", "Ready")
