from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any


def _advisor() -> Any:
    return import_module(
        "custom_components.circuitsetup_energy_analyzer.settings_advisor"
    )


def _recommendation(advisor: Any, **overrides: Any) -> Any:
    values = {
        "recommendation_id": "rec-hvac-daily-spike",
        "unique_key": "hvac:daily_spike_ratio",
        "circuit_id": "hvac",
        "circuit_name": "HVAC",
        "setting_key": "daily_spike_ratio",
        "setting_label": "Daily Spike Ratio",
        "current_value": 0.25,
        "suggested_value": 0.35,
        "unit": "ratio",
        "feature": "daily_energy_spike_ratio",
        "group": "energy_usage",
        "confidence": 0.82,
        "reason": "Recent usage is consistently above the configured threshold.",
        "evidence": {"observed_ratio": 0.43, "sample_days": 14},
        "apply_payload": {"daily_spike_ratio": 0.35},
        "status": advisor.RecommendationStatus.PENDING,
        "created_at": datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return advisor.SettingRecommendation(**values)


def test_setting_recommendation_round_trips_preserving_storage_fields() -> None:
    advisor = _advisor()
    recommendation = _recommendation(advisor)

    raw = advisor.recommendation_to_dict(recommendation)
    restored = advisor.recommendation_from_dict(raw)

    assert restored == recommendation
    assert raw["setting_label"] == "Daily Spike Ratio"
    assert raw["evidence"] == {"observed_ratio": 0.43, "sample_days": 14}
    assert raw["apply_payload"] == {"daily_spike_ratio": 0.35}
    assert raw["advisor_version"] == advisor.ADVISOR_VERSION


def test_recommendation_unique_key_uses_circuit_and_setting() -> None:
    advisor = _advisor()

    assert advisor.recommendation_unique_key("hvac", "daily_spike_ratio") == (
        "hvac:daily_spike_ratio"
    )


def test_recommendation_id_uses_unique_key_and_advisor_version() -> None:
    advisor = _advisor()

    assert advisor.recommendation_id_for("hvac", "daily_spike_ratio") == (
        "hvac:daily_spike_ratio:v1"
    )
    assert advisor.recommendation_id_for(
        "hvac",
        "daily_spike_ratio",
        advisor_version=2,
    ) == "hvac:daily_spike_ratio:v2"


def test_should_suppress_recommendation_respects_denial_cooldown_and_changes() -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    evidence_fingerprint = "observed-ratio-043"
    recent_denial = advisor.RecommendationDecision(
        unique_key="hvac:daily_spike_ratio",
        status=advisor.RecommendationStatus.DENIED,
        decided_at=now - timedelta(days=10),
        denied_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )

    assert advisor.should_suppress_recommendation(
        recent_denial,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )

    recent_dismissal = advisor.RecommendationDecision(
        unique_key="hvac:daily_spike_ratio",
        status=advisor.RecommendationStatus.DISMISSED,
        decided_at=now - timedelta(days=10),
        denied_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert advisor.should_suppress_recommendation(
        recent_dismissal,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )

    old_dismissal = advisor.RecommendationDecision(
        unique_key="hvac:daily_spike_ratio",
        status=advisor.RecommendationStatus.DISMISSED,
        decided_at=now - advisor.DEFAULT_RECOMMENDATION_TTL,
        denied_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert not advisor.should_suppress_recommendation(
        old_dismissal,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )

    older_denial = advisor.RecommendationDecision(
        unique_key="hvac:daily_spike_ratio",
        status=advisor.RecommendationStatus.DENIED,
        decided_at=now - advisor.DEFAULT_RECOMMENDATION_TTL,
        denied_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert advisor.should_suppress_recommendation(
        older_denial,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )

    assert not advisor.should_suppress_recommendation(
        None,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert not advisor.should_suppress_recommendation(
        advisor.RecommendationDecision(
            unique_key="hvac:daily_spike_ratio",
            status=advisor.RecommendationStatus.APPLIED,
            decided_at=now - timedelta(days=10),
            denied_value=0.35,
            evidence_fingerprint=evidence_fingerprint,
        ),
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert not advisor.should_suppress_recommendation(
        advisor.RecommendationDecision(
            unique_key="hvac:daily_spike_ratio",
            status=advisor.RecommendationStatus.DENIED,
            decided_at=now - advisor.DENIAL_COOLDOWN,
            denied_value=0.35,
            evidence_fingerprint=evidence_fingerprint,
        ),
        now=now,
        suggested_value=0.35,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert not advisor.should_suppress_recommendation(
        recent_denial,
        now=now,
        suggested_value=0.4,
        evidence_fingerprint=evidence_fingerprint,
    )
    assert not advisor.should_suppress_recommendation(
        recent_denial,
        now=now,
        suggested_value=0.35,
        evidence_fingerprint="different",
    )


def _only_setting(recommendations: list[Any], setting_key: str) -> Any:
    matches = [
        recommendation
        for recommendation in recommendations
        if recommendation.setting_key == setting_key
    ]
    assert len(matches) == 1
    return matches[0]


def _setting_keys(recommendations: list[Any]) -> set[str]:
    return {recommendation.setting_key for recommendation in recommendations}


def _energy_usage_inputs(
    advisor: Any,
    *,
    now: datetime | None = None,
    advanced_settings: dict[str, Any] | None = None,
    decisions: dict[str, Any] | None = None,
) -> Any:
    return advisor.AdvisorInputs(
        now=now or datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="hvac",
            circuit_name="HVAC",
            appliance_profile="hvac",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings=(
                {"daily_spike_ratio": 0.25}
                if advanced_settings is None
                else advanced_settings
            ),
        ),
        feature_history={
            "energy_usage_days": [
                {"usage_kwh": 5.8},
                {"usage_kwh": 6.1},
                {"usage_kwh": 7.4},
                {"usage_kwh": 6.7},
                {"usage_kwh": 8.9},
                {"usage_kwh": 9.8},
                {"usage_kwh": 7.9},
            ],
        },
        decisions=decisions,
    )


def _operating_detection_inputs(
    advisor: Any,
    *,
    advanced_settings: dict[str, Any] | None = None,
    appliance_profile: str = "refrigerator",
    circuit_mode: str = "single_phase",
    power_flow: str = "load",
    idle_samples: list[float] | None = None,
    idle_sample_counts: list[int] | None = None,
    start_samples: list[float] | None = None,
) -> Any:
    base = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    idle_values = (
        idle_samples
        if idle_samples is not None
        else [4.2, 4.8, 5.1, 5.4, 5.8, 6.0, 6.2, 6.4, 6.5, 6.7, 6.8, 6.9, 7.0, 7.2]
    )
    start_values = (
        start_samples
        if start_samples is not None
        else [84.5, 88.0, 90.0, 92.0, 96.0, 101.0]
    )
    return advisor.AdvisorInputs(
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="fridge",
            circuit_name="Fridge",
            appliance_profile=appliance_profile,
            circuit_mode=circuit_mode,
            power_flow=power_flow,
            advanced_settings=advanced_settings or {},
        ),
        feature_history={
            "operating_idle_samples": [
                {
                    "timestamp": (base + timedelta(hours=index * 16)).isoformat(),
                    "real_power_w": value,
                    **(
                        {"sample_count": idle_sample_counts[index]}
                        if idle_sample_counts is not None
                        else {}
                    ),
                }
                for index, value in enumerate(idle_values)
            ],
            "operating_start_samples": [
                {
                    "timestamp": (base + timedelta(days=index + 1)).isoformat(),
                    "power_w": value,
                }
                for index, value in enumerate(start_values)
            ],
        },
    )


def test_energy_usage_recommendation_uses_7_day_pattern() -> None:
    advisor = _advisor()
    inputs = _energy_usage_inputs(advisor)

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "daily_spike_ratio",
    )

    assert recommendation.suggested_value == 0.3
    assert recommendation.setting_label == "Daily Spike Ratio"
    assert recommendation.group == "Energy Usage"
    assert recommendation.feature == "energy_usage_spikes"
    assert recommendation.confidence >= 0.75
    assert recommendation.evidence["observed_days"] == 7
    assert recommendation.evidence["p95_daily_kwh"] == 9.8
    assert advisor.recommendation_evidence_fingerprint(recommendation) == (
        "energy_usage_spikes:days=7;p95=9.8"
    )
    assert "7 complete days" in recommendation.reason


def test_unhelpful_alert_recommendation_fingerprint_uses_feedback_evidence() -> None:
    advisor = _advisor()
    recommendation = _recommendation(
        advisor,
        evidence={
            "source": "unhelpful_alert_feedback",
            "feedback_fingerprint": "fridge|daily_energy_usage_spike|ratio=25-50pct",
            "suggested_daily_spike_ratio": 0.6,
        },
    )

    assert advisor.recommendation_evidence_fingerprint(recommendation) == (
        "unhelpful_alert_feedback:"
        "fridge|daily_energy_usage_spike|ratio=25-50pct;suggested=0.6"
    )


def test_energy_usage_recommendation_uses_default_for_flat_usage() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="hvac",
            circuit_name="HVAC",
            appliance_profile="hvac",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings={},
        ),
        feature_history={
            "energy_usage_days": [
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
                {"usage_kwh": 8.0},
            ],
        },
    )

    setting_keys = [
        recommendation.setting_key
        for recommendation in advisor.build_settings_recommendations(inputs)
    ]

    assert "daily_spike_ratio" not in setting_keys


def test_operating_detection_recommendations_use_idle_and_start_separation() -> None:
    advisor = _advisor()
    inputs = _operating_detection_inputs(advisor)

    recommendations = advisor.build_settings_recommendations(inputs)
    on_recommendation = _only_setting(
        recommendations,
        "operating_on_threshold_w",
    )
    off_recommendation = _only_setting(
        recommendations,
        "operating_off_threshold_w",
    )

    assert on_recommendation.setting_label == "Turn-On Power"
    assert on_recommendation.current_value == 25.0
    assert on_recommendation.suggested_value == 45.0
    assert on_recommendation.unit == "W"
    assert on_recommendation.group == "Operating Detection"
    assert on_recommendation.feature == "operating_detection_thresholds"
    assert on_recommendation.evidence["idle_sample_count"] == 14
    assert on_recommendation.evidence["running_sample_count"] == 6
    assert on_recommendation.evidence["distinct_run_sessions"] == 6
    assert on_recommendation.evidence["learning_days"] == 9
    assert on_recommendation.evidence["idle_p95_w"] == 7.2
    assert on_recommendation.evidence["running_p10_w"] == 84.5
    assert on_recommendation.evidence["suggested_on_threshold_w"] == 45.0
    assert on_recommendation.evidence["suggested_off_threshold_w"] == 15.0
    assert "confirmed starts" in on_recommendation.reason
    assert advisor.recommendation_evidence_fingerprint(on_recommendation) == (
        "operating_detection_thresholds:days=9;idle_p95=7.2;running_p10=84.5"
    )
    assert on_recommendation.apply_payload == {
        "operating_on_threshold_w": 45.0,
        "operating_off_threshold_w": 15.0,
    }

    assert off_recommendation.setting_label == "Turn-Off Power"
    assert off_recommendation.current_value == 10.0
    assert off_recommendation.suggested_value == 15.0
    assert off_recommendation.apply_payload == {
        "operating_on_threshold_w": 45.0,
        "operating_off_threshold_w": 15.0,
    }


def test_operating_detection_counts_compacted_idle_samples() -> None:
    advisor = _advisor()
    inputs = _operating_detection_inputs(
        advisor,
        idle_samples=[5.0, 7.0],
        idle_sample_counts=[9, 1],
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "operating_on_threshold_w",
    )

    assert recommendation.evidence["idle_sample_count"] == 10
    assert recommendation.evidence["idle_p95_w"] == 7.0


def test_operating_detection_recommendations_require_clear_separation() -> None:
    advisor = _advisor()
    inputs = _operating_detection_inputs(
        advisor,
        idle_samples=[12.0, 13.0, 14.5, 15.0, 16.0, 17.0, 18.0, 18.5, 19.0],
        start_samples=[25.0, 26.0, 27.0, 28.0, 29.0, 30.0],
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "operating_on_threshold_w" not in setting_keys
    assert "operating_off_threshold_w" not in setting_keys


def test_operating_detection_recommendations_skip_near_optimal_settings() -> None:
    advisor = _advisor()
    inputs = _operating_detection_inputs(
        advisor,
        advanced_settings={
            "operating_on_threshold_w": 45.0,
            "operating_off_threshold_w": 15.0,
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "operating_on_threshold_w" not in setting_keys
    assert "operating_off_threshold_w" not in setting_keys


def test_energy_usage_recommendation_uses_window_total_fraction() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="hvac",
            circuit_name="HVAC",
            appliance_profile="hvac",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings={"daily_spike_ratio": 0.25},
        ),
        feature_history={
            "energy_usage_days": [
                {"usage_kwh": 1.0},
                {"usage_kwh": 1.0},
                {"usage_kwh": 1.0},
                {"usage_kwh": 1.0},
                {"usage_kwh": 1.0},
                {"usage_kwh": 1.0},
                {"usage_kwh": 4.0},
            ],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "daily_spike_ratio",
    )

    assert recommendation.suggested_value == 0.5


def test_cycle_recommendation_uses_observed_runtime_pattern() -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    inputs = advisor.AdvisorInputs(
        now=now,
        context=advisor.AdvisorCircuitContext(
            circuit_id="washer",
            circuit_name="Washer",
            appliance_profile="washer",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={},
        ),
        feature_history={
            "cycles": [
                {"duration_minutes": 39, "idle_minutes": 12},
                {"duration_minutes": 42, "idle_minutes": 9},
                {"duration_minutes": 44, "idle_minutes": 10},
                {"duration_minutes": 41, "idle_minutes": 11},
                {"duration_minutes": 47, "idle_minutes": 8},
                {"duration_minutes": 43, "idle_minutes": 9},
                {"duration_minutes": 45, "idle_minutes": 10},
                {"duration_minutes": 46, "idle_minutes": 7},
            ],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "max_active_minutes",
    )

    assert recommendation.suggested_value == 65
    assert recommendation.setting_label == "Max Active Minutes"
    assert recommendation.group == "Run Cycle"
    assert recommendation.evidence["observed_cycles"] == 8
    assert recommendation.evidence["p95_active_minutes"] == 47
    assert "observed run cycles" in recommendation.reason


def test_standby_recommendation_uses_low_power_distribution() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="refrigerator",
            circuit_name="Refrigerator",
            appliance_profile="refrigerator",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={"standby_threshold_w": 8.0},
        ),
        feature_history={
            "standby_samples_w": [3.8, 4.1, 4.0, 5.2, 4.8, 4.4, 5.0, 4.6],
            "always_on_w": [4.2, 4.4, 4.6, 4.8, 5.0, 5.1, 5.2],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "standby_threshold_w",
    )

    assert recommendation.suggested_value == 7.0
    assert recommendation.group == "Standby"
    assert recommendation.evidence["p95_standby_w"] == 5.2


def test_advisor_uses_compacted_sample_counts() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="ev",
            circuit_name="EV Charger",
            appliance_profile="ev_charger",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={"warning_ratio": 0.9},
        ),
        feature_history={
            "current_samples": [24.0, 32.0],
            "current_sample_counts": [6, 1],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "warning_ratio",
    )

    assert recommendation.evidence == {
        "observed_samples": 7,
        "p95_current_amps": 32.0,
    }


def test_standby_recommendation_uses_compacted_sample_counts() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="refrigerator",
            circuit_name="Refrigerator",
            appliance_profile="refrigerator",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={"standby_threshold_w": 8.0},
        ),
        feature_history={
            "standby_samples_w": [4.0, 5.0],
            "standby_sample_counts": [6, 1],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "standby_threshold_w",
    )

    assert recommendation.evidence == {
        "observed_samples": 7,
        "median_standby_w": 4.0,
        "p95_standby_w": 5.0,
    }


def test_dual_phase_recommendation_uses_observed_leg_balance() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="water_heater",
            circuit_name="Water Heater",
            appliance_profile="water_heater",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings={"leg_imbalance_warning_ratio": 0.5},
        ),
        feature_history={
            "leg_imbalance_ratios": [0.02, 0.03, 0.02, 0.04, 0.03, 0.03, 0.02],
            "dual_phase_total_power_w": [4200, 4300, 4150, 4350, 4250, 4210, 4190],
        },
    )
    recommendations = advisor.build_settings_recommendations(inputs)

    imbalance = _only_setting(recommendations, "leg_imbalance_warning_ratio")
    minimum_power = _only_setting(
        recommendations,
        "leg_imbalance_min_total_power_w",
    )

    assert imbalance.suggested_value == 0.15
    assert minimum_power.suggested_value == 4000


def test_dual_phase_recommendation_does_not_loosen_imbalance_ratio() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="water_heater",
            circuit_name="Water Heater",
            appliance_profile="water_heater",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings={"leg_imbalance_warning_ratio": 0.15},
        ),
        feature_history={
            "leg_imbalance_ratios": [0.18, 0.2, 0.22, 0.19, 0.24, 0.21, 0.23],
            "dual_phase_total_power_w": [4200, 4300, 4150, 4350, 4250, 4210, 4190],
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "leg_imbalance_warning_ratio" not in setting_keys
    assert "leg_imbalance_min_total_power_w" in setting_keys


def test_metric_consistency_recommendation_uses_residual_distribution() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="pool_pump",
            circuit_name="Pool Pump",
            appliance_profile="pool_pump",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={"apparent_power_tolerance_percent": 15.0},
        ),
        feature_history={
            "apparent_power_residual_percent": [2.0, 2.4, 3.1, 2.8, 3.0, 3.4, 3.2],
            "power_factor_residual": [0.01, 0.02, 0.02, 0.03, 0.02, 0.02, 0.01],
            "apparent_power_samples_va": [700, 720, 710, 705, 715, 718, 709],
        },
    )
    recommendations = advisor.build_settings_recommendations(inputs)

    apparent_power = _only_setting(
        recommendations,
        "apparent_power_tolerance_percent",
    )
    power_factor = _only_setting(recommendations, "power_factor_tolerance")

    assert apparent_power.suggested_value == 7.0
    assert power_factor.suggested_value == 0.05


def test_metric_consistency_recommendations_do_not_loosen_tolerances() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="pool_pump",
            circuit_name="Pool Pump",
            appliance_profile="pool_pump",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={
                "apparent_power_tolerance_percent": 7.0,
                "power_factor_tolerance": 0.05,
            },
        ),
        feature_history={
            "apparent_power_residual_percent": [
                9.0,
                10.5,
                11.0,
                12.0,
                13.5,
                14.0,
                15.0,
            ],
            "power_factor_residual": [0.07, 0.08, 0.09, 0.11, 0.12, 0.1, 0.13],
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "apparent_power_tolerance_percent" not in setting_keys
    assert "power_factor_tolerance" not in setting_keys


def test_metric_consistency_does_not_raise_minimum_apparent_power_default() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="pool_pump",
            circuit_name="Pool Pump",
            appliance_profile="pool_pump",
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings={},
        ),
        feature_history={
            "apparent_power_samples_va": [700, 720, 710, 705, 715, 718, 709],
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "minimum_apparent_power_va" not in setting_keys


def test_mains_and_solar_recommendations_use_aggregate_patterns() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="mains",
            circuit_name="Mains",
            appliance_profile="mains_nilm",
            circuit_mode="mains_nilm",
            power_flow="mains_net",
            advanced_settings={
                "balance_negative_tolerance_w": 250,
                "solar_surplus_threshold_w": 500,
                "high_solar_surplus_threshold_w": 1500,
            },
        ),
        feature_history={
            "negative_balance_w": [90, 120, 150, 130, 110, 160, 145],
            "solar_export_w": [0, 250, 600, 900, 1200, 2100, 2600],
        },
    )
    recommendations = advisor.build_settings_recommendations(inputs)

    balance = _only_setting(recommendations, "balance_negative_tolerance_w")
    surplus = _only_setting(recommendations, "solar_surplus_threshold_w")
    high_surplus = _only_setting(
        recommendations,
        "high_solar_surplus_threshold_w",
    )

    assert balance.suggested_value == 200.0
    assert surplus.suggested_value == 900.0
    assert high_surplus.suggested_value == 2600.0


def test_recommendation_guidance_covers_advanced_setting_families() -> None:
    from custom_components.circuitsetup_energy_analyzer.balance import (
        DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    )
    from custom_components.circuitsetup_energy_analyzer.load_shift import (
        FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    )
    from custom_components.circuitsetup_energy_analyzer.metric_consistency import (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
        DEFAULT_MIN_APPARENT_POWER_VA,
        DEFAULT_POWER_FACTOR_TOLERANCE,
    )
    from custom_components.circuitsetup_energy_analyzer.recommendation_guidance import (
        recommendation_setting_default_value,
        recommendation_setting_expected_effect,
    )
    from custom_components.circuitsetup_energy_analyzer.solar_flow import (
        EXPORT_TOLERANCE_W,
        HIGH_SOLAR_SURPLUS_THRESHOLD_W,
        SOLAR_SURPLUS_THRESHOLD_W,
    )
    from custom_components.circuitsetup_energy_analyzer.standby import (
        DEFAULT_STANDBY_WINDOW_HOURS,
    )

    expected_defaults = {
        "apparent_power_tolerance_percent": (
            DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
        ),
        "power_factor_tolerance": DEFAULT_POWER_FACTOR_TOLERANCE,
        "minimum_apparent_power_va": DEFAULT_MIN_APPARENT_POWER_VA,
        "balance_negative_tolerance_w": DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
        "window_hours": DEFAULT_STANDBY_WINDOW_HOURS,
        "always_on_alert_w": 0.0,
        "solar_export_tolerance_w": EXPORT_TOLERANCE_W,
        "solar_surplus_threshold_w": SOLAR_SURPLUS_THRESHOLD_W,
        "high_solar_surplus_threshold_w": HIGH_SOLAR_SURPLUS_THRESHOLD_W,
        "flexible_load_running_threshold_w": FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    }

    expected_effect_phrases = {
        "apparent_power_tolerance_percent": "metric consistency",
        "power_factor_tolerance": "power-factor",
        "minimum_apparent_power_va": "low apparent-power",
        "balance_negative_tolerance_w": "mains-minus-load",
        "window_hours": "standby history",
        "always_on_alert_w": "always on",
        "solar_export_tolerance_w": "export",
        "solar_surplus_threshold_w": "solar surplus",
        "high_solar_surplus_threshold_w": "high solar surplus",
        "flexible_load_running_threshold_w": "flexible load",
    }

    for setting_key, default_value in expected_defaults.items():
        assert recommendation_setting_default_value(setting_key) == default_value
        assert expected_effect_phrases[setting_key] in (
            recommendation_setting_expected_effect(setting_key).lower()
        )


def test_mains_balance_recommendation_does_not_raise_tolerance() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="mains",
            circuit_name="Mains",
            appliance_profile="mains_nilm",
            circuit_mode="mains_nilm",
            power_flow="mains_net",
            advanced_settings={"balance_negative_tolerance_w": 250.0},
        ),
        feature_history={
            "negative_balance_w": [300, 350, 400, 450, 500, 550, 600],
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "balance_negative_tolerance_w" not in setting_keys


def test_mains_balance_uses_actual_default_before_recommending() -> None:
    advisor = _advisor()
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="mains",
            circuit_name="Mains",
            appliance_profile="mains_nilm",
            circuit_mode="mains_nilm",
            power_flow="mains_net",
            advanced_settings={},
        ),
        feature_history={
            "negative_balance_w": [90, 120, 150, 130, 110, 160, 145],
        },
    )

    setting_keys = _setting_keys(advisor.build_settings_recommendations(inputs))

    assert "balance_negative_tolerance_w" not in setting_keys


def test_safety_advisor_does_not_infer_breaker_size() -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    inputs = advisor.AdvisorInputs(
        now=now,
        context=advisor.AdvisorCircuitContext(
            circuit_id="car_charger",
            circuit_name="Car Charger",
            appliance_profile="ev_charger",
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings={},
        ),
        feature_history={
            "current_samples": [31.0, 31.2, 30.8, 31.1, 31.4, 31.0, 30.9],
        },
    )

    recommendations = advisor.build_settings_recommendations(inputs)
    recommendation = _only_setting(recommendations, "warning_ratio")
    setting_keys = {item.setting_key for item in recommendations}

    assert "breaker_amps" not in setting_keys
    assert "warning_ratio" in setting_keys
    assert recommendation.setting_label == "Capacity Warning Ratio"


def test_previous_denial_suppresses_same_recommendation() -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    initial_inputs = _energy_usage_inputs(advisor, now=now)
    initial_recommendation = _only_setting(
        advisor.build_settings_recommendations(initial_inputs),
        "daily_spike_ratio",
    )
    evidence_fingerprint = advisor.recommendation_evidence_fingerprint(
        initial_recommendation
    )
    assert evidence_fingerprint == "energy_usage_spikes:days=7;p95=9.8"

    inputs = _energy_usage_inputs(
        advisor,
        now=now,
        decisions={
            "hvac:daily_spike_ratio": advisor.RecommendationDecision(
                unique_key="hvac:daily_spike_ratio",
                status=advisor.RecommendationStatus.DENIED,
                decided_at=now - timedelta(days=3),
                denied_value=initial_recommendation.suggested_value,
                evidence_fingerprint=evidence_fingerprint,
            )
        },
    )

    setting_keys = [
        recommendation.setting_key
        for recommendation in advisor.build_settings_recommendations(inputs)
    ]

    assert "daily_spike_ratio" not in setting_keys
