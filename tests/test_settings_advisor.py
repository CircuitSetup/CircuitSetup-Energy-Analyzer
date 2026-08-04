from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

import pytest


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


def test_stored_watt_suffix_label_migrates_to_power_name() -> None:
    advisor = _advisor()
    recommendation = _recommendation(
        advisor,
        setting_key="standby_threshold_w",
        setting_label="Standby Threshold W",
    )

    restored = advisor.recommendation_from_dict(
        advisor.recommendation_to_dict(recommendation)
    )

    assert restored.setting_label == "Standby Power Threshold"


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


@pytest.mark.parametrize(
    "status",
    [
        "APPLIED",
        "DISMISSED",
        "DENIED",
    ],
)
def test_active_decision_cooldown_ignores_candidate_drift(status: str) -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    decision = advisor.RecommendationDecision(
        unique_key="dryer:operating_on_threshold_w",
        status=getattr(advisor.RecommendationStatus, status),
        decided_at=now - timedelta(days=1),
        denied_value=1510.0,
        evidence_fingerprint="old",
    )

    assert advisor.should_suppress_recommendation(
        decision,
        now=now,
        suggested_value=1400.0,
        evidence_fingerprint="new",
        evidence={"latest_cycle_at": now.isoformat()},
    )


@pytest.mark.parametrize(
    ("status", "age_days"),
    [
        ("APPLIED", 31),
        ("DISMISSED", 31),
        ("DENIED", 91),
    ],
)
def test_decision_cooldown_expiry_requires_fresh_completed_cycle_evidence(
    status: str,
    age_days: int,
) -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    decided_at = now - timedelta(days=age_days)
    decision = advisor.RecommendationDecision(
        unique_key="dryer:operating_on_threshold_w",
        status=getattr(advisor.RecommendationStatus, status),
        decided_at=decided_at,
        denied_value=1510.0,
        evidence_fingerprint="old",
    )
    call = {
        "decision": decision,
        "now": now,
        "suggested_value": 1400.0,
        "evidence_fingerprint": "new",
    }

    for latest_cycle_at in (None, "not-a-date", decided_at.isoformat()):
        evidence = {"calculation_basis": "completed_operating_cycles"}
        if latest_cycle_at is not None:
            evidence["latest_cycle_at"] = latest_cycle_at
        assert advisor.should_suppress_recommendation(**call, evidence=evidence)

    assert not advisor.should_suppress_recommendation(
        **call,
        evidence={
            "calculation_basis": "completed_operating_cycles",
            "latest_cycle_at": (decided_at + timedelta(seconds=1)).isoformat(),
        },
    )
    assert not advisor.should_suppress_recommendation(
        **call,
        evidence={"calculation_basis": "other"},
    )


def test_naive_decided_at_is_normalized_for_cooldown_and_freshness() -> None:
    advisor = _advisor()
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    recent = advisor.RecommendationDecision(
        unique_key="dryer:operating_on_threshold_w",
        status=advisor.RecommendationStatus.APPLIED,
        decided_at=(now - timedelta(days=1)).replace(tzinfo=None),
    )
    assert advisor.should_suppress_recommendation(
        recent,
        now=now,
        suggested_value=1400.0,
        evidence_fingerprint="new",
    )

    decided_at = (now - timedelta(days=31)).replace(tzinfo=None)
    expired = advisor.RecommendationDecision(
        unique_key="dryer:operating_on_threshold_w",
        status=advisor.RecommendationStatus.APPLIED,
        decided_at=decided_at,
    )
    call = {
        "decision": expired,
        "now": now,
        "suggested_value": 1400.0,
        "evidence_fingerprint": "new",
    }
    assert advisor.should_suppress_recommendation(
        **call,
        evidence={
            "calculation_basis": "completed_operating_cycles",
            "latest_cycle_at": decided_at.replace(tzinfo=UTC).isoformat(),
        },
    )
    assert not advisor.should_suppress_recommendation(
        **call,
        evidence={
            "calculation_basis": "completed_operating_cycles",
            "latest_cycle_at": (
                decided_at.replace(tzinfo=UTC) + timedelta(seconds=1)
            ).isoformat(),
        },
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


def _operating_cycle_inputs(
    advisor: Any,
    *,
    cycle_count: int = 20,
    distinct_days: int = 7,
    idle_upper_w: float = 12.0,
    running_lower_w: float = 100.0,
    advanced_settings: dict[str, Any] | None = None,
    appliance_profile: str = "refrigerator",
) -> Any:
    base = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    cycles = [
        {
            "timestamp": (base + timedelta(days=index % distinct_days)).isoformat(),
            "date": (base + timedelta(days=index % distinct_days)).date().isoformat(),
            "idle_upper_w": idle_upper_w,
            "running_lower_w": running_lower_w,
            "idle_sample_count": 30,
            "running_sample_count": 30,
        }
        for index in range(cycle_count)
    ]
    return advisor.AdvisorInputs(
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="fridge",
            circuit_name="Fridge",
            appliance_profile=appliance_profile,
            circuit_mode="single_phase",
            power_flow="load",
            advanced_settings=advanced_settings or {},
        ),
        feature_history={"operating_cycles": cycles},
    )


def test_learned_watt_settings_require_more_than_five_watts_and_ten_percent() -> None:
    advisor = _advisor()

    dryer = _operating_cycle_inputs(
        advisor,
        cycle_count=8,
        distinct_days=7,
        idle_upper_w=240.0,
        running_lower_w=2780.0,
        appliance_profile="dryer",
        advanced_settings={"operating_on_threshold_w": 1515.0},
    )
    assert "operating_on_threshold_w" not in _setting_keys(
        advisor.build_settings_recommendations(dryer)
    )

    exact_ten_percent = _operating_cycle_inputs(
        advisor,
        idle_upper_w=20.0,
        running_lower_w=200.0,
        advanced_settings={"operating_on_threshold_w": 100.0},
    )
    assert "operating_on_threshold_w" not in _setting_keys(
        advisor.build_settings_recommendations(exact_ten_percent)
    )

    off_and_standby_boundaries = _operating_cycle_inputs(
        advisor,
        idle_upper_w=34.6,
        running_lower_w=200.0,
        advanced_settings={
            "operating_on_threshold_w": 80.0,
            "operating_off_threshold_w": 50.0,
            "standby_threshold_w": 50.0,
        },
    )
    boundary_keys = _setting_keys(
        advisor.build_settings_recommendations(off_and_standby_boundaries)
    )
    assert "operating_off_threshold_w" not in boundary_keys
    assert "standby_threshold_w" not in boundary_keys

    material = _operating_cycle_inputs(
        advisor,
        idle_upper_w=20.0,
        running_lower_w=220.0,
        advanced_settings={
            "operating_on_threshold_w": 100.0,
            "operating_off_threshold_w": 50.0,
            "standby_threshold_w": 50.0,
        },
    )
    material_keys = _setting_keys(advisor.build_settings_recommendations(material))
    assert {
        "operating_on_threshold_w",
        "operating_off_threshold_w",
        "standby_threshold_w",
    } <= material_keys


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


def _hvac_advisor_inputs(
    advisor: Any,
    *,
    appliance_profile: str = "heat_pump",
    advanced_settings: dict[str, Any] | None = None,
    calls: list[dict[str, Any]] | None = None,
    episodes: list[dict[str, Any]] | None = None,
) -> Any:
    return advisor.AdvisorInputs(
        now=datetime(2026, 7, 29, 12, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="heat_pump",
            circuit_name="Downstairs Heat Pump",
            appliance_profile=appliance_profile,
            circuit_mode="dual_phase",
            power_flow="load",
            advanced_settings=advanced_settings or {},
        ),
        feature_history={
            "hvac_correlation_calls": calls or [],
            "hvac_response_episodes": episodes or [],
        },
    )


def _hvac_calls(
    *,
    thermostat: str = "climate.downstairs",
    temperature_entity: str | None = None,
    climate_has_current: bool = True,
    matching: int = 8,
    total: int = 10,
    mode: str = "cooling",
    driver_mode: str | None = None,
    electrical_driver_present: bool = True,
) -> list[dict[str, Any]]:
    return [
        {
            "thermostat_entity_id": thermostat,
            "thermostat_name": thermostat.replace("climate.", "").title(),
            "temperature_entity_id": temperature_entity,
            "mode": mode,
            "driver_mode": driver_mode or mode,
            "overlap_ratio": 0.9 if index < matching else 0.2,
            "candidate_moved_toward_target": index < matching,
            "climate_has_current_temperature": climate_has_current,
            "electrical_driver_present": electrical_driver_present,
            "weather_mode": mode,
            "temperature_bin": "very_hot",
        }
        for index in range(total)
    ]


def test_hvac_thermostat_association_suggestion_uses_80_percent_boundary() -> None:
    advisor = _advisor()
    recommendation = _only_setting(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(advisor, calls=_hvac_calls())
        ),
        "linked_thermostat_entities",
    )

    assert recommendation.current_value == []
    assert recommendation.suggested_value == ["climate.downstairs"]
    assert recommendation.apply_payload == {
        "linked_thermostat_entities": ["climate.downstairs"]
    }
    assert recommendation.evidence["observation_count"] == 10
    assert recommendation.evidence["confidence"] == pytest.approx(0.8)
    assert recommendation.evidence["circuit_name"] == "Downstairs Heat Pump"
    assert recommendation.evidence["thermostat_name"] == "Downstairs"
    assert recommendation.evidence["mode"] == "cooling"
    assert recommendation.evidence["weather_mode"] == "cooling"
    assert advisor.recommendation_evidence_fingerprint(recommendation) == (
        "hvac_thermostat_correlation:"
        "thermostat=climate.downstairs;calls=10;confidence=0.8;mode=cooling"
    )


def test_hvac_thermostat_association_suggests_each_zone_separately() -> None:
    advisor = _advisor()
    recommendation = _only_setting(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                advanced_settings={
                    "linked_thermostat_entities": ["climate.downstairs"]
                },
                calls=[
                    *_hvac_calls(),
                    *_hvac_calls(thermostat="climate.upstairs"),
                ],
            )
        ),
        "linked_thermostat_entities",
    )

    assert recommendation.current_value == ["climate.downstairs"]
    assert recommendation.suggested_value == [
        "climate.downstairs",
        "climate.upstairs",
    ]
    assert recommendation.evidence["thermostat_entity_id"] == "climate.upstairs"


def test_hvac_thermostat_association_skips_low_confidence_or_cross_mode() -> None:
    advisor = _advisor()
    low_confidence = _setting_keys(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                calls=_hvac_calls(matching=7),
            )
        )
    )
    cross_mode = _setting_keys(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                calls=_hvac_calls(driver_mode="heating"),
            )
        )
    )

    assert "linked_thermostat_entities" not in low_confidence
    assert "linked_thermostat_entities" not in cross_mode


def test_hvac_candidate_temperature_and_gas_blower_suggestions() -> None:
    advisor = _advisor()
    temperature = _only_setting(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                calls=_hvac_calls(
                    temperature_entity="sensor.downstairs_temperature",
                    climate_has_current=False,
                ),
            )
        ),
        "thermostat_temperature_sensor_map",
    )
    gas_blower = _only_setting(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                appliance_profile="hvac_blower",
                calls=_hvac_calls(
                    mode="heating",
                    electrical_driver_present=False,
                ),
            )
        ),
        "blower_represents_gas_heat",
    )

    assert temperature.suggested_value == {
        "climate.downstairs": "sensor.downstairs_temperature"
    }
    assert temperature.evidence["observation_count"] == 10
    assert gas_blower.current_value is False
    assert gas_blower.suggested_value is True
    assert gas_blower.evidence["mode"] == "heating"

    has_climate_temperature = _setting_keys(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                calls=_hvac_calls(
                    temperature_entity="sensor.downstairs_temperature",
                    climate_has_current=True,
                ),
            )
        )
    )
    assert "thermostat_temperature_sensor_map" not in has_climate_temperature


def test_hvac_efficiency_threshold_is_not_auto_recommended() -> None:
    advisor = _advisor()
    keys = _setting_keys(
        advisor.build_settings_recommendations(
            _hvac_advisor_inputs(
                advisor,
                advanced_settings={"hvac_efficiency_change_threshold_pct": 25.0},
                episodes=[{"absolute_deviation_percent": 99.0}] * 100,
            )
        )
    )

    assert "hvac_efficiency_change_threshold_pct" not in keys


def test_legacy_hvac_threshold_evidence_hides_internal_context_key() -> None:
    from custom_components.circuitsetup_energy_analyzer.recommendation_guidance import (
        recommendation_evidence_preview,
    )

    advisor = _advisor()
    recommendation = _recommendation(
        advisor,
        recommendation_id="legacy",
        unique_key="ac2:hvac_efficiency_change_threshold_pct",
        circuit_id="ac2",
        setting_key="hvac_efficiency_change_threshold_pct",
        setting_label="HVAC Slower Response Threshold",
        current_value=25.0,
        suggested_value=50.0,
        unit="%",
        feature="hvac_efficiency_threshold",
        group="HVAC",
        confidence=1.0,
        reason="Legacy recommendation",
        evidence={
            "weather_context": (
                "ac2|hvac_compressor|climate.upstairs||cooling|"
                "thermostat_call|warm|summer|cooling|0-1F|ac2|hvac_2"
            )
        },
        apply_payload={"hvac_efficiency_change_threshold_pct": 50.0},
    )

    fingerprint = advisor.recommendation_evidence_fingerprint(recommendation)

    assert fingerprint == "legacy_hvac_efficiency_threshold"
    assert "ac2|hvac_compressor" not in fingerprint
    assert recommendation_evidence_preview(recommendation.evidence) == ""


def test_operating_recommendations_require_profile_cycles_and_seven_days() -> None:
    advisor = _advisor()

    assert advisor.build_settings_recommendations(
        _operating_cycle_inputs(advisor, cycle_count=19, distinct_days=7)
    ) == []
    assert advisor.build_settings_recommendations(
        _operating_cycle_inputs(advisor, cycle_count=20, distinct_days=6)
    ) == []


def test_operating_and_standby_use_completed_cycle_boundaries() -> None:
    advisor = _advisor()
    recommendations = advisor.build_settings_recommendations(
        _operating_cycle_inputs(advisor)
    )

    on = _only_setting(recommendations, "operating_on_threshold_w")
    off = _only_setting(recommendations, "operating_off_threshold_w")
    standby = _only_setting(recommendations, "standby_threshold_w")

    assert on.suggested_value == 55.0
    assert off.suggested_value == 20.0
    assert standby.suggested_value == 16.0
    assert on.evidence["completed_cycle_count"] == 20
    assert on.evidence["distinct_learning_days"] == 7
    assert on.evidence["idle_ceiling_w"] == 12.0
    assert on.evidence["running_floor_w"] == 100.0
    assert on.evidence["separation_w"] == 88.0
    assert on.evidence["latest_cycle_at"] == "2026-05-31T12:00:00+00:00"
    assert on.evidence["calculation_basis"] == "completed_operating_cycles"
    assert standby.evidence == {
        key: on.evidence[key]
        for key in (
            "completed_cycle_count",
            "distinct_learning_days",
            "idle_ceiling_w",
            "running_floor_w",
            "separation_w",
            "latest_cycle_at",
            "calculation_basis",
        )
    }
    assert advisor.recommendation_evidence_fingerprint(on) == (
        "operating_detection_thresholds:cycles=20;days=7;"
        "idle_ceiling=12.0;running_floor=100.0"
    )
    assert advisor.recommendation_evidence_fingerprint(standby) == (
        "always_on_standby:cycles=20;days=7;"
        "idle_ceiling=12.0;running_floor=100.0"
    )
    assert "20 qualified completed cycles" in on.reason
    assert "7 distinct days" in standby.reason


def test_operating_cycles_are_not_weighted_by_sample_count() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(advisor)
    inputs.feature_history["operating_cycles"][-1].update(
        idle_upper_w=90.0,
        idle_sample_count=100_000,
        running_sample_count=100_000,
    )

    recommendations = advisor.build_settings_recommendations(inputs)

    assert _only_setting(
        recommendations, "operating_on_threshold_w"
    ).suggested_value == 55.0
    assert _only_setting(recommendations, "standby_threshold_w").suggested_value == 16.0


def test_operating_and_standby_require_clear_cycle_separation() -> None:
    advisor = _advisor()

    assert advisor.build_settings_recommendations(
        _operating_cycle_inputs(advisor, idle_upper_w=90.0, running_lower_w=100.0)
    ) == []


def test_unclassified_standby_samples_do_not_change_cycle_recommendation() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(advisor)
    inputs = advisor.AdvisorInputs(
        now=inputs.now,
        context=inputs.context,
        feature_history={
            **inputs.feature_history,
            "standby_samples_w": [1_000.0] * 100,
            "standby_sample_counts": [1_000] * 100,
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs), "standby_threshold_w"
    )

    assert recommendation.suggested_value == 16.0
    assert recommendation.evidence["idle_ceiling_w"] == 12.0


def test_legacy_operating_inputs_do_not_produce_recommendations() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(advisor)
    base = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    inputs = advisor.AdvisorInputs(
        now=inputs.now,
        context=inputs.context,
        feature_history={
            "operating_idle_samples": [
                {
                    "timestamp": (base + timedelta(days=index % 7)).isoformat(),
                    "real_power_w": 12.0,
                }
                for index in range(20)
            ],
            "operating_start_samples": [
                {
                    "timestamp": (base + timedelta(days=index % 7)).isoformat(),
                    "power_w": 100.0,
                }
                for index in range(20)
            ],
        },
    )

    assert advisor.build_settings_recommendations(inputs) == []


def test_malformed_operating_cycle_does_not_satisfy_profile_minimum() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(advisor, cycle_count=19)
    inputs.feature_history["operating_cycles"].append(
        {
            "timestamp": "not-a-timestamp",
            "date": "2026-06-01",
            "idle_upper_w": 12.0,
            "running_lower_w": 100.0,
            "idle_sample_count": 30,
            "running_sample_count": 30,
        }
    )

    assert advisor.build_settings_recommendations(inputs) == []


def test_operating_cycle_requires_a_learning_date() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(advisor, cycle_count=19)
    inputs.feature_history["operating_cycles"].append(
        {
            "timestamp": "2026-06-01T12:00:00+00:00",
            "date": None,
            "idle_upper_w": 12.0,
            "running_lower_w": 100.0,
            "idle_sample_count": 30,
            "running_sample_count": 30,
        }
    )

    assert advisor.build_settings_recommendations(inputs) == []


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


def test_standby_recommendation_ignores_one_watt_change() -> None:
    advisor = _advisor()
    inputs = _operating_cycle_inputs(
        advisor,
        idle_upper_w=190.0,
        running_lower_w=300.0,
        advanced_settings={
            "standby_threshold_w": 248.0,
            "operating_on_threshold_w": 245.0,
            "operating_off_threshold_w": 200.0,
        },
    )

    assert "standby_threshold_w" not in _setting_keys(
        advisor.build_settings_recommendations(inputs)
    )


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
            "current_samples": [24.0, 32.0, 40.0],
            "current_sample_counts": [100, 1, 1],
        },
    )

    recommendation = _only_setting(
        advisor.build_settings_recommendations(inputs),
        "warning_ratio",
    )

    assert recommendation.evidence == {
        "observed_samples": 102,
        "p95_current_amps": 40.0,
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
    assert minimum_power.setting_label == "Leg Imbalance Minimum Total Power"


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
    assert balance.setting_label == "Negative Balance Power Tolerance"
    assert surplus.suggested_value == 900.0
    assert surplus.setting_label == "Solar Surplus Power Threshold"
    assert high_surplus.suggested_value == 2600.0
    assert high_surplus.setting_label == "High Solar Surplus Power Threshold"


def test_mixed_mode_runs_only_aggregate_safe_recommendation_rules(
    monkeypatch,
) -> None:
    advisor = _advisor()
    called: list[str] = []
    safe = {
        "_energy_usage_recommendations",
        "_capacity_recommendations",
        "_retention_recommendations",
    }
    rule_names = (
        "_energy_usage_recommendations",
        "_cycle_recommendations",
        "_capacity_recommendations",
        "_operating_detection_recommendations",
        "_standby_recommendations",
        "_dual_phase_recommendations",
        "_metric_consistency_recommendations",
        "_mains_balance_recommendations",
        "_solar_flow_recommendations",
        "_hvac_efficiency_recommendations",
        "_retention_recommendations",
    )
    for name in rule_names:
        monkeypatch.setattr(
            advisor,
            name,
            lambda _inputs, name=name: called.append(name) or [],
        )
    inputs = advisor.AdvisorInputs(
        now=datetime(2026, 7, 31, tzinfo=UTC),
        context=advisor.AdvisorCircuitContext(
            circuit_id="mixed",
            circuit_name="Mixed",
            appliance_profile="refrigerator",
            circuit_mode="mixed",
            power_flow="load",
            advanced_settings={},
        ),
        feature_history={},
    )

    assert advisor.build_settings_recommendations(inputs) == []
    assert set(called) == safe


def test_recommendation_guidance_covers_advanced_setting_families() -> None:
    from custom_components.circuitsetup_energy_analyzer.balance import (
        DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    )
    from custom_components.circuitsetup_energy_analyzer.const import (
        DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
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
        "linked_thermostat_entities": [],
        "thermostat_temperature_sensor_map": {},
        "blower_represents_gas_heat": False,
        "hvac_efficiency_change_threshold_pct": (
            DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
        ),
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
        "linked_thermostat_entities": "thermostat zones",
        "thermostat_temperature_sensor_map": "indoor sensor",
        "blower_represents_gas_heat": "gas heat",
        "hvac_efficiency_change_threshold_pct": "weather-normalized",
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
