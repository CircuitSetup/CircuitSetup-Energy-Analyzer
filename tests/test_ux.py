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


def test_normalize_sensitivity_accepts_current_names() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_policy_name_for_sensitivity,
        normalize_sensitivity,
    )

    assert normalize_sensitivity("quiet") == "quiet"
    assert normalize_sensitivity("balanced") == "balanced"
    assert normalize_sensitivity("sensitive") == "sensitive"
    assert normalize_sensitivity("surprising") == "balanced"
    assert alert_policy_name_for_sensitivity("quiet") == "low"
    assert alert_policy_name_for_sensitivity("balanced") == "standard"
    assert alert_policy_name_for_sensitivity("sensitive") == "high"


def test_friendly_feature_name_formats_machine_keys_for_display() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import friendly_feature_name

    assert friendly_feature_name("demand_monthly_peak") == "Demand Monthly Peak"
    assert friendly_feature_name("reactive_to_real_ratio") == "Reactive To Real Ratio"
    assert friendly_feature_name("nilm_leg_mismatch") == "NILM Leg Mismatch"
    assert friendly_feature_name("") == "Alert"
    assert friendly_feature_name(None) == "Alert"


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
        value_metric="reactive_to_real_ratio",
        observed_value=0.42,
        baseline_value=0.24,
        change_ratio=0.75,
        repeated_count=4,
        first_seen=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        features={"reactive_power": 2.1, "power_factor": 1.2},
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_reactive_power", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.fridge_power_factor", SensorRole.POWER_FACTOR),
        ),
    )

    detail = alert_evidence_detail(alert, config=config)

    assert detail["alert_id"] == notification_id_for_alert(alert)
    assert detail["circuit_id"] == "fridge"
    assert detail["feature"] == "reactive_to_real_ratio"
    assert detail["feature_name"] == "Reactive To Real Ratio"
    assert detail["value_metric"] == "reactive_to_real_ratio"
    assert detail["value_label"] == "Reactive-to-real power ratio"
    assert detail["value_unit"] == "%"
    assert detail["value_format"] == "percentage"
    assert detail["severity"] == "warning"
    assert detail["message"] == "Possible issue"
    assert detail["what_happened"] == (
        "Reactive-to-real power ratio changed from the learned or configured "
        "expectation. Observed 42.000% compared with baseline 24.000%."
    )
    assert "VAR" in detail["why_it_matters"]
    assert "watts, VAR, VA" in detail["what_to_check_first"]
    assert detail["baseline_value"] == 0.24
    assert detail["expected_value"] == 0.24
    assert detail["observed_value"] == 0.42
    assert detail["threshold"] is None
    assert detail["sample_count"] is None
    assert detail["change_ratio"] == 0.75
    assert detail["percent_change"] == 75.0
    assert detail["repeated_count"] == 4
    assert detail["first_seen"] == "2026-06-02T10:00:00+00:00"
    assert detail["last_seen"] == "2026-06-02T12:30:00+00:00"
    assert detail["time_window"] == (
        "2026-06-02T10:00:00+00:00 to 2026-06-02T12:30:00+00:00"
    )
    assert detail["contributing_metrics"] == {
        "power_factor": 1.2,
        "reactive_power": 2.1,
    }
    assert detail["evidence_path"].startswith(
        "/circuitsetup-energy-analyzer-evidence?"
    )
    assert detail["graph_entities"] == [
        "sensor.fridge_reactive_power",
        "sensor.fridge_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["source_entities"] == [
        "sensor.fridge_power",
        "sensor.fridge_reactive_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["source_entities_count"] == 3
    assert detail["source_entities_has_more"] is False
    assert detail["source_entities_omitted_count"] == 0
    assert detail["graph_window_start"] == "2026-06-02T09:50:00+00:00"
    assert detail["graph_window_end"] == "2026-06-02T12:40:00+00:00"
    assert detail == {
        "alert_id": notification_id_for_alert(alert),
        "circuit_id": "fridge",
        "feature": "reactive_to_real_ratio",
        "feature_name": "Reactive To Real Ratio",
        "value_metric": "reactive_to_real_ratio",
        "value_label": "Reactive-to-real power ratio",
        "value_unit": "%",
        "value_format": "percentage",
        "severity": "warning",
        "message": "Possible issue",
        "what_happened": detail["what_happened"],
        "why_it_matters": detail["why_it_matters"],
        "what_to_check_first": detail["what_to_check_first"],
        "baseline_value": 0.24,
        "expected_value": 0.24,
        "observed_value": 0.42,
        "threshold": None,
        "sample_count": None,
        "change_ratio": 0.75,
        "percent_change": 75.0,
        "repeated_count": 4,
        "first_seen": "2026-06-02T10:00:00+00:00",
        "last_seen": "2026-06-02T12:30:00+00:00",
        "time_window": (
            "2026-06-02T10:00:00+00:00 to 2026-06-02T12:30:00+00:00"
        ),
        "contributing_metrics": {"power_factor": 1.2, "reactive_power": 2.1},
        "contributing_metrics_count": 2,
        "contributing_metrics_has_more": False,
        "contributing_metrics_omitted_count": 0,
        "evidence_path": detail["evidence_path"],
        "graph_entities": [
            "sensor.fridge_reactive_power",
            "sensor.fridge_power",
            "sensor.fridge_power_factor",
        ],
        "source_entities": [
            "sensor.fridge_power",
            "sensor.fridge_reactive_power",
            "sensor.fridge_power_factor",
        ],
        "source_entities_count": 3,
        "source_entities_has_more": False,
        "source_entities_omitted_count": 0,
        "graph_window_start": "2026-06-02T09:50:00+00:00",
        "graph_window_end": "2026-06-02T12:40:00+00:00",
    }


def test_alert_evidence_detail_labels_known_and_fallback_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_evidence_detail,
    )

    expected = {
        "real_power": ("Real power", "W", "number"),
        "reactive_power": ("Reactive power", "VAR", "number"),
        "apparent_power": ("Apparent power", "VA", "number"),
        "power_factor": ("Power factor", "", "decimal"),
        "activity_inactive_too_long": (
            "Activity inactive too long",
            "min",
            "number",
        ),
        "always_on_power": ("Always on power", "W", "number"),
        "circuit_capacity": ("Circuit capacity", "A", "number"),
        "billing_cycle_budget": ("Billing cycle budget", "kWh", "number"),
        "daily_energy_goal": ("Daily energy goal", "kWh", "number"),
        "daily_energy_usage_spike": (
            "Daily energy usage spike",
            "kWh",
            "number",
        ),
        "demand_limit": ("Demand limit", "W", "number"),
        "demand_monthly_peak": ("Demand monthly peak", "W", "number"),
        "dual_phase_leg_imbalance": (
            "Dual phase leg imbalance",
            "%",
            "percentage",
        ),
        "nilm_appliance_unusual_energy": (
            "NILM appliance unusual energy",
            "kWh",
            "number",
        ),
        "nilm_appliance_confidence": ("NILM confidence", "%", "percentage"),
        "nilm_appliance_unusual_runtime": (
            "NILM appliance unusual runtime",
            "min",
            "number",
        ),
        "rain_pump_correlation": ("Rain pump correlation", "min", "number"),
        "run_cycle_daily_duty_cycle_percent": (
            "Run cycle daily duty cycle",
            "%",
            "number",
        ),
        "run_cycle_daily_start_count": (
            "Run cycle daily start count",
            "starts",
            "number",
        ),
        "run_cycle_duration_s": ("Run cycle duration", "s", "number"),
        "utility_energy_mismatch": (
            "Utility energy mismatch",
            "kWh",
            "number",
        ),
        "water_flow_correlation": ("Water flow correlation", "min", "number"),
        "activity_left_on": ("Activity left on", "min", "number"),
        "unknown_metric": ("Unknown Metric", "", "number"),
    }
    for metric, metadata in expected.items():
        alert = AlertEvidence(
            timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
            circuit_id="panel",
            severity=Severity.WARNING,
            message="Possible issue",
            feature="relationship_changed",
            value_metric=metric,
        )

        detail = alert_evidence_detail(alert)

        assert (
            detail["value_label"],
            detail["value_unit"],
            detail["value_format"],
        ) == metadata




def test_alert_evidence_detail_bounds_large_contributing_metric_attributes() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_evidence_detail,
    )

    features = {f"metric_{index:02d}": float(index) for index in range(12)}
    features["sample_count"] = 42
    features["threshold_w"] = 1500.0
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="panel",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="metric_11",
        observed_value=85.0,
        baseline_value=80.0,
        features=features,
    )

    detail = alert_evidence_detail(alert)

    assert detail["threshold"] == 1500.0
    assert detail["sample_count"] == 42
    assert detail["contributing_metrics"] == {
        "metric_11": 11.0,
        "metric_00": 0.0,
        "metric_01": 1.0,
        "metric_02": 2.0,
        "metric_03": 3.0,
    }
    assert detail["contributing_metrics_count"] == 14
    assert detail["contributing_metrics_has_more"] is True
    assert detail["contributing_metrics_omitted_count"] == 9


def test_alert_evidence_detail_bounds_large_source_entity_previews() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_evidence_detail,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="panel",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="metric_consistency",
        observed_value=85.0,
        baseline_value=80.0,
        features={"metric_consistency": 0.42},
    )
    config = CircuitConfig(
        circuit_id="panel",
        name="Panel",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=tuple(
            SensorRef(f"sensor.panel_source_{index:02d}", SensorRole.REAL_POWER)
            for index in range(9)
        ),
    )

    detail = alert_evidence_detail(alert, config=config)

    assert detail["source_entities"] == [
        "sensor.panel_source_00",
        "sensor.panel_source_01",
        "sensor.panel_source_02",
        "sensor.panel_source_03",
        "sensor.panel_source_04",
    ]
    assert detail["source_entities_count"] == 9
    assert detail["source_entities_has_more"] is True
    assert detail["source_entities_omitted_count"] == 4


def test_alert_evidence_detail_includes_safety_notice_for_capacity_alerts() -> None:
    from custom_components.circuitsetup_energy_analyzer.safety import (
        ELECTRICAL_SAFETY_NOTICE,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_evidence_detail,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="car_charger",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="capacity_usage",
        observed_value=85.0,
        baseline_value=80.0,
    )

    detail = alert_evidence_detail(alert)

    assert detail["safety_notice"] == ELECTRICAL_SAFETY_NOTICE


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

    assert checklist["sample_observed"] is True
    assert checklist["required_sensors_present"] is True
    assert checklist["optional_sensors_present"] is True
    assert checklist["numeric_states_valid"] is True
    assert checklist["source_data_fresh"] is True
    assert checklist["quality_issues"] == []
    assert checklist["quality_issue_count"] == 0
    assert checklist["quality_issues_has_more"] is False
    assert checklist["quality_issues_omitted_count"] == 0
    assert checklist["metric_roles_present"] == [
        "power_factor",
        "reactive_power",
        "real_power",
    ]


def test_data_quality_checklist_bounds_large_quality_issue_attributes() -> None:
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import (
        data_quality_checklist,
    )

    config = CircuitConfig(
        circuit_id="panel",
        name="Panel",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.panel_w", SensorRole.REAL_POWER),),
    )
    issues = tuple(
        f"sensor.panel_source_{index:02d} stale unavailable non_numeric"
        for index in range(8)
    )
    sample = NormalizedCircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="panel",
        real_power=120.0,
        source_entity_ids=("sensor.panel_w",),
        quality_issues=issues,
    )

    checklist = data_quality_checklist(config, sample)

    assert checklist["quality_issues"] == [
        "sensor.panel_source_00 stale unavailable non_numeric",
        "sensor.panel_source_01 stale unavailable non_numeric",
        "sensor.panel_source_02 stale unavailable non_numeric",
        "sensor.panel_source_03 stale unavailable non_numeric",
        "sensor.panel_source_04 stale unavailable non_numeric",
    ]
    assert checklist["quality_issue_count"] == 8
    assert checklist["quality_issues_has_more"] is True
    assert checklist["quality_issues_omitted_count"] == 3
    assert checklist["quality_issues_full"] == list(issues)
    assert checklist["numeric_states_valid"] is False
    assert checklist["source_data_fresh"] is False


def test_data_quality_checklist_flags_non_finite_numeric_issue() -> None:
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
        sensors=(SensorRef("sensor.fridge_w", SensorRole.REAL_POWER),),
    )
    sample = NormalizedCircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        source_entity_ids=("sensor.fridge_w",),
        quality_issues=("sensor.fridge_w non_finite",),
    )

    checklist = data_quality_checklist(config, sample)

    assert checklist["numeric_states_valid"] is False
    assert checklist["source_data_fresh"] is True


def test_data_quality_checklist_flags_invalid_timestamp_as_not_fresh() -> None:
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
        sensors=(SensorRef("sensor.fridge_w", SensorRole.REAL_POWER),),
    )
    sample = NormalizedCircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        source_entity_ids=("sensor.fridge_w",),
        quality_issues=(
            "sensor.fridge_w future_timestamp",
            "sensor.fridge_backup_w naive_timestamp",
        ),
    )

    checklist = data_quality_checklist(config, sample)

    assert checklist["numeric_states_valid"] is True
    assert checklist["source_data_fresh"] is False


def test_learning_progress_counts_age_cycles_and_baseline_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.models import BaselineStats
    from custom_components.circuitsetup_energy_analyzer.profiles import (
        get_profile_definition,
    )
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
    assert progress["days_required"] == get_profile_definition(
        config.appliance_profile
    ).minimum_learning_days


def test_health_status_priority_order_is_dashboard_friendly() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import health_summary

    assert health_summary(data_quality_problem=True) == ("needs_data", "Needs data")
    assert health_summary(paused=True) == ("paused", "Paused")
    assert health_summary(active_alerts=True) == ("possible_issue", "Possible issue")
    assert health_summary(observations=True) == (
        "observation",
        "Observation recorded",
    )
    assert health_summary(nilm_review_count=2) == ("nilm_review", "NILM review")
    assert health_summary(mixed=True) == ("mixed_observation", "Mixed observation")
    assert health_summary(learning=True) == ("learning", "Learning")
    assert health_summary() == ("ready", "Ready")
