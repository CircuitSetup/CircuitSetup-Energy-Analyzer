from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_SENSITIVITY,
    CONF_UTILITY_COMPARISON_SETTINGS,
)
from custom_components.circuitsetup_energy_analyzer.cycles import (
    RUN_CYCLE_DURATION_FEATURE,
)
from custom_components.circuitsetup_energy_analyzer.managers import (
    settings_controller,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitMode,
    EventType,
    PowerFlowMode,
)
from custom_components.circuitsetup_energy_analyzer.settings_advisor import (
    RecommendationStatus,
    SettingRecommendation,
)


def _recommendation(**overrides: Any) -> SettingRecommendation:
    values = {
        "recommendation_id": "fridge:daily_spike_ratio:v1",
        "unique_key": "fridge:daily_spike_ratio",
        "circuit_id": "fridge",
        "circuit_name": "Kitchen Fridge",
        "setting_key": "daily_spike_ratio",
        "setting_label": "Daily Spike Ratio",
        "current_value": 0.25,
        "suggested_value": 0.35,
        "unit": "ratio",
        "feature": "energy_usage_spikes",
        "group": "Energy Usage",
        "confidence": 0.82,
        "reason": "Observed daily variation.",
        "evidence": {"observed_days": 14},
        "apply_payload": {"daily_spike_ratio": 0.35},
        "status": RecommendationStatus.PENDING,
        "created_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SettingRecommendation(**values)


class _SettingsCoordinator:
    def __init__(self, recommendation: SettingRecommendation) -> None:
        self.state = SimpleNamespace(
            cost_current_rate_by_circuit={},
            utility_cost_rate_by_circuit={},
            leg_imbalance_evidence_by_circuit={},
            metric_consistency_evidence_by_circuit={},
            balance_evidence_by_circuit={},
            solar_flow_evidence_by_circuit={},
            learning_by_circuit={"fridge": False},
        )
        self.entry_data = {
            CONF_ADVANCED_SETTINGS: {
                "fridge": {
                    "preset": "quiet",
                    "daily_spike_ratio": 0.2,
                    "option_only": "from_entry",
                }
            }
        }
        self.store_data = SimpleNamespace(
            settings_recommendations={
                recommendation.recommendation_id: recommendation
            },
            settings_recommendation_decisions={},
            alert_feedback={},
            sensitivity_by_circuit={},
            energy_usage_settings_by_circuit={
                "fridge": {"daily_spike_ratio": 0.25}
            },
            energy_goal_settings_by_circuit={},
            activity_alert_settings_by_circuit={},
            billing_settings_by_circuit={},
            cost_settings_by_circuit={},
            demand_settings_by_circuit={},
            capacity_settings_by_circuit={},
            utility_comparison_settings_by_circuit={},
            standby_settings_by_circuit={},
            leg_imbalance_settings_by_circuit={},
            metric_consistency_settings_by_circuit={},
            balance_settings_by_circuit={},
            solar_flow_settings_by_circuit={},
            operating_detection_settings_by_circuit={},
            energy_usage_by_circuit={},
            events=[],
            standby_by_circuit={},
            demand_by_circuit={},
        )
        self.options = {
            CONF_ADVANCED_SETTINGS: {"fridge": {"daily_spike_ratio": 0.25}}
        }
        self.now = datetime(2026, 6, 30, 12, 5, tzinfo=UTC)
        self.persist_count = 0
        self.dirty_count = 0
        self.refreshed_recommendations: list[datetime] = []
        self.refreshed_circuits: list[tuple[str, datetime]] = []
        self.refreshed_cost_estimates = 0
        self.updated: list[object] = []
        self.saved: list[datetime] = []
        self.notified = 0
        self.episode_keys: list[tuple[tuple[str, ...], ...]] = []
        self.store_persistence = SimpleNamespace(
            async_save_if_dirty=self._record_store_save,
            mark_dirty=self._record_store_dirty,
        )
        self.config_entry_controller = SimpleNamespace(
            async_persist_options=self._record_config_entry_persist,
        )
        self.notification_controller = SimpleNamespace(
            async_notify_settings_recommendations_if_needed=(
                self._record_settings_recommendation_notification
            ),
            set_settings_recommendation_notification_episode_key=(
                self._record_settings_recommendation_episode_key
            ),
        )
        self.processor_runtime = SimpleNamespace(
            learning_mature=lambda config, now: True,
        )
        self.circuit_configs = [
            SimpleNamespace(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                power_flow=PowerFlowMode.LOAD,
                daily_energy_spike_ratio=0.25,
                cost_cycle_start_day=1,
                default_rate_per_kwh=None,
                tou_rate_per_kwh=None,
                tou_start="",
                tou_end="",
                tou_weekdays=(),
                tou_name="Peak",
            )
        ]
        self.circuit_registry = SimpleNamespace(
            config_for_circuit=self._lookup_config_for_circuit,
        )
        self.goal_context = SimpleNamespace(name="goal_context")
        self.goal_result = SimpleNamespace(name="goal_result")
        self.energy_goal_refreshes: list[
            tuple[str, SimpleNamespace, SimpleNamespace]
        ] = []
        self.context_calls: list[datetime] = []
        self.applied_feature_results: list[SimpleNamespace] = []
        self.context_builder = SimpleNamespace(
            build=self._record_processing_context,
            time_zone=self._context_time_zone,
        )

    def current_time(self) -> datetime:
        return self.now

    async def _record_config_entry_persist(self) -> None:
        self.persist_count += 1

    def _record_store_dirty(self) -> None:
        self.dirty_count += 1

    def _refresh_settings_recommendation_state(self, now: datetime) -> None:
        self.refreshed_recommendations.append(now)

    def _record_settings_recommendation_episode_key(
        self,
        episode_key: tuple[tuple[str, ...], ...],
    ) -> None:
        self.episode_keys.append(episode_key)

    def refresh_ux_state_for_circuit(self, circuit_id: str, now: datetime) -> None:
        self.refreshed_circuits.append((circuit_id, now))

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    def refresh_cost_estimates(self) -> None:
        self.refreshed_cost_estimates += 1

    async def _record_store_save(self, now: datetime) -> None:
        self.saved.append(now)

    async def _record_settings_recommendation_notification(self) -> None:
        self.notified += 1

    def _lookup_config_for_circuit(self, circuit_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            circuit_id=circuit_id,
            energy_usage_window_days=7,
            daily_energy_spike_ratio=0.25,
            daily_energy_goal_kwh=None,
            energy_goal_alert_ratio=1.0,
            billing_cycle_start_day=1,
            billing_cycle_budget_kwh=None,
            billing_cycle_budget_alert_ratio=1.0,
            billing_cycle_min_elapsed_days=3,
            cost_cycle_start_day=1,
            default_rate_per_kwh=None,
            tou_rate_per_kwh=None,
            tou_start="",
            tou_end="",
            tou_weekdays=(),
            tou_name="Peak",
            demand_window_minutes=15,
            demand_limit_w=None,
            standby_window_hours=12,
            standby_threshold_w=5.0,
            always_on_alert_w=None,
            standby_min_samples=24,
        )

    def _record_processing_context(self, now: datetime) -> SimpleNamespace:
        self.context_calls.append(now)
        return self.goal_context

    def _refresh_energy_goal_state(
        self,
        circuit_id: str,
        config: SimpleNamespace,
        context: SimpleNamespace,
    ) -> SimpleNamespace:
        self.energy_goal_refreshes.append((circuit_id, config, context))
        return self.goal_result

    def refresh_energy_goal_state(
        self,
        circuit_id: str,
        config: SimpleNamespace,
        context: SimpleNamespace,
    ) -> SimpleNamespace:
        return self._refresh_energy_goal_state(circuit_id, config, context)

    async def async_apply_feature_result(self, result: SimpleNamespace) -> None:
        self.applied_feature_results.append(result)

    def _context_time_zone(self) -> str:
        return "UTC"


@pytest.mark.asyncio
async def test_settings_controller_applies_undoes_and_resets_recommendation() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_apply_setting_recommendation(
        recommendation.recommendation_id,
    )
    applied = coordinator.store_data.settings_recommendations[
        recommendation.recommendation_id
    ]
    undo_result = await controller.async_undo_setting_recommendation(
        recommendation.recommendation_id,
    )
    reset_result = await controller.async_reset_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert applied.status is RecommendationStatus.APPLIED
    assert undo_result is True
    assert reset_result is True
    assert coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"] == {
        "daily_spike_ratio": 0.25
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.25
    }
    assert coordinator.persist_count == 3
    assert coordinator.dirty_count == 3
    assert coordinator.updated == [
        coordinator.state,
        coordinator.state,
        coordinator.state,
    ]


def test_settings_controller_builds_advisor_inputs() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    config = coordinator.circuit_configs[0]
    coordinator.store_data.energy_usage_by_circuit["fridge"] = {
        "days": [{"date": "2026-06-30"}]
    }

    inputs = controller.advisor_inputs_for_config(config, coordinator.now)

    assert inputs.now == coordinator.now
    assert inputs.context.circuit_id == "fridge"
    assert inputs.context.circuit_name == "Kitchen Fridge"
    assert inputs.context.appliance_profile == "refrigerator"
    assert inputs.context.circuit_mode == "single_phase"
    assert inputs.context.power_flow == "load"
    assert dict(inputs.context.advanced_settings) == {
        "daily_spike_ratio": 0.25,
        "option_only": "from_entry",
        "preset": "quiet",
    }
    assert inputs.feature_history["energy_usage_days"] == [{"date": "2026-06-30"}]
    assert (
        dict(inputs.decisions)
        == coordinator.store_data.settings_recommendation_decisions
    )


def test_settings_controller_builds_advisor_feature_history(monkeypatch) -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    coordinator.store_data.energy_usage_by_circuit["fridge"] = {
        "days": [{"date": "2026-06-30", "energy_kwh": 1.8}]
    }
    coordinator.store_data.standby_by_circuit["fridge"] = {
        "samples": [
            {
                "timestamp": coordinator.now.isoformat(),
                "real_power_w": "4.5",
                "sample_count": 3,
            },
            {"real_power_w": "bad"},
        ]
    }
    coordinator.store_data.demand_by_circuit["fridge"] = {
        "capacity_current_samples": [{"current_amps": "7.25", "sample_count": 4}],
        "samples": [{"current_a": "8.5"}],
    }
    coordinator.store_data.events = [
        SimpleNamespace(
            circuit_id="fridge",
            event_type=EventType.START,
            timestamp=coordinator.now,
            features={"startup_power_w": "610"},
        )
    ]
    coordinator.state.leg_imbalance_evidence_by_circuit = {
        "fridge": {
            "leg_imbalance_ratio": "0.12",
            "left_real_power_w": -400,
            "right_real_power_w": 380,
        }
    }
    coordinator.state.metric_consistency_evidence_by_circuit = {
        "fridge": {
            "apparent_power_difference_percent": "3.5",
            "power_factor_difference": "0.04",
            "reported_apparent_power_va": "720",
        }
    }
    coordinator.state.balance_evidence_by_circuit = {
        "fridge": {"balance_power_w": "-120"}
    }
    coordinator.state.solar_flow_evidence_by_circuit = {
        "fridge": {"grid_export_w": "250"}
    }
    config = coordinator.circuit_configs[0]

    monkeypatch.setattr(
        settings_controller,
        "cycle_baseline_feature_values",
        lambda events, **kwargs: {RUN_CYCLE_DURATION_FEATURE: [900]},
        raising=False,
    )

    history = settings_controller.SettingsController(
        coordinator
    ).advisor_feature_history_for_circuit(config, coordinator.now)

    assert history["energy_usage_days"] == [
        {"date": "2026-06-30", "energy_kwh": 1.8}
    ]
    assert history["cycles"] == [{"duration_minutes": 15.0}]
    assert history["standby_samples_w"] == [4.5]
    assert history["standby_sample_counts"] == [3]
    assert history["current_samples"] == [7.25, 8.5]
    assert history["current_sample_counts"] == [4, 1]
    assert history["operating_start_samples"] == [
        {"timestamp": coordinator.now.isoformat(), "power_w": 610.0}
    ]
    assert history["leg_imbalance_ratios"] == [0.12]
    assert history["dual_phase_total_power_w"] == [780]
    assert history["apparent_power_residual_percent"] == [3.5]
    assert history["power_factor_residual"] == [0.04]
    assert history["apparent_power_samples_va"] == [720.0]
    assert history["negative_balance_w"] == [-120.0]
    assert history["solar_export_w"] == [250.0]


def test_settings_controller_builds_unhelpful_feedback_recommendation() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    coordinator.store_data.alert_feedback = {
        "daily_spike": {
            "status": "unhelpful",
            "circuit_id": "fridge",
            "feature": "daily_energy_usage_spike",
            "fingerprint": "alert-123",
            "evidence_count": 3,
            "change_ratio": 0.31,
            "observed_value": "2.4",
            "baseline_value": "1.6",
        }
    }
    controller = settings_controller.SettingsController(coordinator)
    config = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        daily_energy_spike_ratio=0.25,
    )

    recommendations = controller.unhelpful_alert_setting_recommendations(
        config,
        coordinator.now,
        existing_recommendation_ids=set(),
    )

    assert len(recommendations) == 1
    generated = recommendations[0]
    assert generated.recommendation_id == "fridge:daily_spike_ratio:v1"
    assert generated.unique_key == "fridge:daily_spike_ratio"
    assert generated.current_value == 0.25
    assert generated.suggested_value == 0.4
    assert generated.evidence["source"] == "unhelpful_alert_feedback"
    assert generated.evidence["unhelpful_feedback_count"] == 3
    assert generated.evidence["change_ratio"] == 0.31
    assert generated.evidence["observed_value"] == 2.4
    assert generated.evidence["baseline_value"] == 1.6
    assert generated.apply_payload == {"daily_spike_ratio": 0.4}
    assert generated.expires_at > generated.created_at


def test_settings_controller_selects_repeated_unhelpful_feedback() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    config = SimpleNamespace(circuit_id="fridge")
    older = datetime(2026, 6, 30, 10, 0, tzinfo=UTC).isoformat()
    newer = datetime(2026, 6, 30, 11, 0, tzinfo=UTC).isoformat()
    coordinator.store_data.alert_feedback = {
        "wrong_status": {
            "status": "expected",
            "circuit_id": "fridge",
            "feature": "daily_energy_usage_spike",
            "evidence_count": 5,
        },
        "too_few": {
            "status": "unhelpful",
            "circuit_id": "fridge",
            "feature": "daily_energy_usage_spike",
            "evidence_count": 1,
        },
        "wrong_circuit": {
            "status": "unhelpful",
            "circuit_id": "hvac",
            "feature": "daily_energy_usage_spike",
            "evidence_count": 4,
        },
        "older": {
            "status": "unhelpful",
            "circuit_id": "fridge",
            "feature": "daily_energy_usage_spike",
            "evidence_count": 2,
            "last_seen": older,
        },
        "newer": {
            "action": "unhelpful",
            "circuit_id": "fridge",
            "feature": "daily_energy_usage_spike",
            "evidence_count": 2,
            "last_seen": newer,
            "expires_at": datetime(2026, 7, 1, 12, 0, tzinfo=UTC).isoformat(),
        },
    }

    selected = controller.repeated_unhelpful_daily_spike_feedback(
        config,
        coordinator.now,
    )

    assert selected is coordinator.store_data.alert_feedback["newer"]


def test_settings_controller_rebuilds_setting_recommendations(monkeypatch) -> None:
    stale = _recommendation(
        recommendation_id="fridge:old_threshold:v1",
        unique_key="fridge:old_threshold",
        setting_key="old_threshold",
        setting_label="Old Threshold",
    )
    generated = _recommendation(
        recommendation_id="fridge:new_threshold:v1",
        unique_key="fridge:new_threshold",
        setting_key="new_threshold",
        setting_label="New Threshold",
        current_value=1.0,
        suggested_value=2.0,
        apply_payload={"new_threshold": 2.0},
    )
    coordinator = _SettingsCoordinator(stale)
    controller = settings_controller.SettingsController(coordinator)

    monkeypatch.setattr(
        settings_controller,
        "build_settings_recommendations",
        lambda inputs: [generated],
        raising=False,
    )

    changed = controller.rebuild_setting_recommendations(coordinator.now)

    assert changed is True
    assert (
        coordinator.store_data.settings_recommendations[stale.recommendation_id].status
        is RecommendationStatus.STALE
    )
    assert (
        coordinator.store_data.settings_recommendations[generated.recommendation_id]
        == generated
    )
    assert coordinator.state.settings_recommendation_count_by_circuit == {"fridge": 1}
    assert [
        item["recommendation_id"]
        for item in coordinator.state.settings_recommendations_by_circuit["fridge"]
    ] == [generated.recommendation_id]


def test_settings_controller_waits_for_live_learning_state(monkeypatch) -> None:
    stale = _recommendation()
    generated = _recommendation(
        recommendation_id="fridge:new_threshold:v1",
        unique_key="fridge:new_threshold",
        setting_key="new_threshold",
        setting_label="New Threshold",
    )
    coordinator = _SettingsCoordinator(stale)
    coordinator.state.learning_by_circuit["fridge"] = True
    controller = settings_controller.SettingsController(coordinator)
    monkeypatch.setattr(
        settings_controller,
        "build_settings_recommendations",
        lambda inputs: [generated],
    )

    changed = controller.rebuild_setting_recommendations(coordinator.now)

    assert changed is True
    assert generated.recommendation_id not in (
        coordinator.store_data.settings_recommendations
    )
    assert (
        coordinator.store_data.settings_recommendations[stale.recommendation_id].status
        is RecommendationStatus.STALE
    )
    assert coordinator.state.settings_recommendation_count_by_circuit == {}


@pytest.mark.asyncio
async def test_settings_controller_recalculates_and_records_decisions(
    monkeypatch,
) -> None:
    recommendation = _recommendation()
    updated_recommendation = _recommendation(
        suggested_value=0.4,
        apply_payload={"daily_spike_ratio": 0.4},
        reason="Updated recommendation.",
    )
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    monkeypatch.setattr(
        settings_controller,
        "build_settings_recommendations",
        lambda inputs: [updated_recommendation],
    )

    await controller.async_recalculate_setting_recommendations("fridge")
    await controller.async_dismiss_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert coordinator.dirty_count == 2
    assert coordinator.saved == [coordinator.now, coordinator.now]
    assert coordinator.notified == 1
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is RecommendationStatus.DISMISSED
    )
    decision = coordinator.store_data.settings_recommendation_decisions[
        recommendation.unique_key
    ]
    assert decision.status is RecommendationStatus.DISMISSED
    assert decision.denied_value == updated_recommendation.suggested_value
    assert coordinator.state.settings_recommendations_by_circuit == {}
    assert coordinator.state.settings_recommendation_count_by_circuit == {}
    assert coordinator.episode_keys == [()]


def test_settings_controller_writes_recommendation_setting_values() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    controller.set_recommendation_setting_value(
        "fridge",
        "daily_spike_ratio",
        0.35,
    )
    controller.set_recommendation_setting_value(
        "fridge",
        "daily_spike_ratio",
        None,
    )

    assert coordinator.options[CONF_ADVANCED_SETTINGS] == {}
    assert coordinator.store_data.energy_usage_settings_by_circuit == {}


def test_settings_controller_refreshes_recommendation_state() -> None:
    recommendation = _recommendation()
    applied = _recommendation(
        recommendation_id="fridge:standby_threshold_w:v1",
        unique_key="fridge:standby_threshold_w",
        setting_key="standby_threshold_w",
        setting_label="Standby Threshold",
        status=RecommendationStatus.APPLIED,
    )
    expired = _recommendation(
        recommendation_id="fridge:expired:v1",
        unique_key="fridge:expired",
        setting_key="expired",
        setting_label="Expired",
        expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    dismissed = _recommendation(
        recommendation_id="fridge:dismissed:v1",
        unique_key="fridge:dismissed",
        setting_key="dismissed",
        setting_label="Dismissed",
        status=RecommendationStatus.DISMISSED,
    )
    coordinator = _SettingsCoordinator(recommendation)
    coordinator.store_data.settings_recommendations = {
        recommendation.recommendation_id: recommendation,
        applied.recommendation_id: applied,
        expired.recommendation_id: expired,
        dismissed.recommendation_id: dismissed,
    }
    controller = settings_controller.SettingsController(coordinator)

    controller.refresh_settings_recommendation_state(coordinator.now)

    visible_ids = {
        item.recommendation_id
        for item in controller.visible_settings_recommendations(coordinator.now)
    }
    pending_ids = {
        item.recommendation_id
        for item in controller.pending_settings_recommendations(coordinator.now)
    }
    payloads = coordinator.state.settings_recommendations_by_circuit["fridge"]

    assert visible_ids == {
        recommendation.recommendation_id,
        applied.recommendation_id,
    }
    assert pending_ids == {recommendation.recommendation_id}
    assert coordinator.state.settings_recommendation_count_by_circuit == {"fridge": 1}
    assert {item["recommendation_id"] for item in payloads} == visible_ids


def test_settings_controller_replaces_advanced_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    controller.replace_advanced_settings(
        "fridge",
        {
            "preset": "sensitive",
            "daily_spike_ratio": 0.4,
            "min_samples": 12,
            "leg_imbalance_warning_ratio": 0.35,
            "leg_imbalance_min_total_power_w": 700.0,
            "balance_negative_tolerance_w": 250.0,
            "solar_export_tolerance_w": 120.0,
        },
    )

    assert coordinator.store_data.sensitivity_by_circuit["fridge"] == "sensitive"
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.store_data.standby_settings_by_circuit["fridge"] == {
        "min_samples": 12
    }
    assert coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] == {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    assert coordinator.store_data.balance_settings_by_circuit["fridge"] == {
        "negative_tolerance_w": 250.0
    }
    assert coordinator.store_data.solar_flow_settings_by_circuit["fridge"] == {
        "export_tolerance_w": 120.0
    }


def test_settings_controller_applies_config_entry_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.entry_data[CONF_UTILITY_COMPARISON_SETTINGS] = {
        "mains": {"utility_energy_entity": "sensor.old_utility"},
        "remove_me": {"utility_energy_entity": "sensor.remove"},
    }
    coordinator.options[CONF_UTILITY_COMPARISON_SETTINGS] = {
        "mains": {"utility_energy_entity": "sensor.new_utility"},
        "remove_me": {},
    }
    coordinator.store_data.utility_comparison_settings_by_circuit["remove_me"] = {
        "utility_energy_entity": "sensor.remove"
    }
    coordinator.options[CONF_ADVANCED_SETTINGS] = {
        "fridge": {"preset": "sensitive", "daily_spike_ratio": 0.4}
    }

    controller.apply_config_entry_settings()

    assert coordinator.store_data.utility_comparison_settings_by_circuit == {
        "mains": {"utility_energy_entity": "sensor.new_utility"}
    }
    assert coordinator.store_data.sensitivity_by_circuit["fridge"] == "sensitive"
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.4
    }


def test_settings_controller_clears_mapped_advanced_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "min_samples": 12
    }
    coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] = {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    coordinator.store_data.balance_settings_by_circuit["fridge"] = {
        "negative_tolerance_w": 250.0
    }
    coordinator.store_data.solar_flow_settings_by_circuit["fridge"] = {
        "export_tolerance_w": 120.0
    }

    controller.clear_advanced_setting_value("fridge", "standby_min_samples")
    controller.clear_advanced_setting_value("fridge", "leg_imbalance_warning_ratio")
    controller.clear_advanced_setting_value(
        "fridge",
        "leg_imbalance_min_total_power_w",
    )
    controller.clear_advanced_setting_value("fridge", "balance_negative_tolerance_w")
    controller.clear_advanced_setting_value("fridge", "solar_export_tolerance_w")

    assert "fridge" not in coordinator.store_data.standby_settings_by_circuit
    assert "fridge" not in coordinator.store_data.leg_imbalance_settings_by_circuit
    assert "fridge" not in coordinator.store_data.balance_settings_by_circuit
    assert "fridge" not in coordinator.store_data.solar_flow_settings_by_circuit


@pytest.mark.asyncio
async def test_settings_controller_async_replaces_advanced_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_replace_advanced_settings(
        "fridge",
        {"daily_spike_ratio": 0.4},
    )

    assert coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.dirty_count == 1
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)]
    assert coordinator.updated == [coordinator.state]
    assert coordinator.saved == [coordinator.now]


def test_settings_controller_reads_advanced_settings_for_circuit() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "min_samples": 12
    }
    coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] = {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    coordinator.store_data.balance_settings_by_circuit["fridge"] = {
        "negative_tolerance_w": 250.0
    }
    coordinator.store_data.solar_flow_settings_by_circuit["fridge"] = {
        "export_tolerance_w": 120.0,
        "solar_surplus_threshold_w": 500.0,
    }

    settings = controller.advanced_settings_for_circuit("fridge")

    assert settings["preset"] == "quiet"
    assert settings["option_only"] == "from_entry"
    assert settings["daily_spike_ratio"] == 0.25
    assert settings["min_samples"] == 12
    assert settings["leg_imbalance_warning_ratio"] == 0.35
    assert settings["leg_imbalance_min_total_power_w"] == 700.0
    assert settings["balance_negative_tolerance_w"] == 250.0
    assert settings["solar_export_tolerance_w"] == 120.0
    assert settings["solar_surplus_threshold_w"] == 500.0


@pytest.mark.asyncio
async def test_settings_controller_sets_threshold_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_leg_imbalance_settings("hvac", 0.4, 800.0)
    await controller.async_set_metric_consistency_settings("hvac", 12.0, 0.08, 120.0)
    await controller.async_set_mains_balance_settings("mains", 250.0)
    await controller.async_set_solar_flow_settings(
        "mains",
        100.0,
        500.0,
        1200.0,
        350.0,
    )

    assert coordinator.store_data.leg_imbalance_settings_by_circuit["hvac"] == {
        "warning_ratio": 0.4,
        "minimum_total_power_w": 800.0,
    }
    assert coordinator.store_data.metric_consistency_settings_by_circuit["hvac"] == {
        "apparent_power_tolerance_percent": 12.0,
        "power_factor_tolerance": 0.08,
        "minimum_apparent_power_va": 120.0,
    }
    assert coordinator.store_data.balance_settings_by_circuit["mains"] == {
        "negative_tolerance_w": 250.0
    }
    assert coordinator.store_data.solar_flow_settings_by_circuit["mains"] == {
        "export_tolerance_w": 100.0,
        "solar_surplus_threshold_w": 500.0,
        "high_solar_surplus_threshold_w": 1200.0,
        "flexible_load_running_threshold_w": 350.0,
    }
    assert coordinator.dirty_count == 4
    assert coordinator.refreshed_circuits == [
        ("hvac", coordinator.now),
        ("hvac", coordinator.now),
        ("mains", coordinator.now),
        ("mains", coordinator.now),
    ]
    assert coordinator.updated == [coordinator.state] * 4
    assert coordinator.saved == [coordinator.now] * 4


@pytest.mark.asyncio
async def test_settings_controller_sets_usage_and_load_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_energy_usage_settings("fridge", 14, 0.2)
    await controller.async_set_demand_settings("fridge", 30, 4500.0)
    await controller.async_set_capacity_settings("fridge", 20.0, 0.8)
    await controller.async_set_standby_settings("fridge", 24, 8.0, 25.0)

    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "window_days": 14,
        "daily_spike_ratio": 0.2,
    }
    assert coordinator.store_data.demand_settings_by_circuit["fridge"] == {
        "window_minutes": 30,
        "demand_limit_w": 4500.0,
    }
    assert coordinator.store_data.capacity_settings_by_circuit["fridge"] == {
        "warning_ratio": 0.8,
        "breaker_amps": 20.0,
    }
    assert coordinator.store_data.standby_settings_by_circuit["fridge"] == {
        "window_hours": 24,
        "standby_threshold_w": 8.0,
        "always_on_alert_w": 25.0,
    }
    assert coordinator.dirty_count == 4
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)] * 4
    assert coordinator.updated == [coordinator.state] * 4
    assert coordinator.saved == [coordinator.now] * 4


@pytest.mark.asyncio
async def test_settings_controller_sets_billing_cost_and_utility_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_billing_cycle_settings("fridge", 15, 300.0, 0.9)
    await controller.async_set_cost_settings("fridge", 1)
    await controller.async_set_utility_comparison_settings(
        "mains",
        utility_energy_entity="sensor.opower_current_bill_usage",
        utility_statistic_id="opower:utility_elec_consumption",
        utility_source_type="auto",
        utility_statistic_period="day",
        measured_energy_entities=["sensor.panel_import_energy"],
        tolerance_percent=8.5,
        utility_cost_entity="sensor.opower_current_bill_cost",
    )

    assert coordinator.store_data.billing_settings_by_circuit["fridge"] == {
        "cycle_start_day": 15,
        "budget_kwh": 300.0,
        "budget_alert_ratio": 0.9,
    }
    assert coordinator.store_data.cost_settings_by_circuit["fridge"] == {
        "cycle_start_day": 1,
    }
    assert coordinator.store_data.utility_comparison_settings_by_circuit["mains"] == {
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_cost_entity": "sensor.opower_current_bill_cost",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_type": "auto",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 8.5,
    }
    assert coordinator.dirty_count == 3
    assert coordinator.refreshed_circuits == [
        ("fridge", coordinator.now),
        ("fridge", coordinator.now),
        ("mains", coordinator.now),
    ]
    assert coordinator.updated == [coordinator.state] * 3
    assert coordinator.saved == [coordinator.now] * 3


@pytest.mark.asyncio
async def test_removing_utility_rate_sources_clears_the_last_known_rate() -> None:
    coordinator = _SettingsCoordinator(_recommendation())
    coordinator.state.utility_cost_rate_by_circuit["mains"] = 0.25
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_utility_comparison_settings(
        "mains",
        utility_energy_entity="",
        utility_cost_entity="",
    )

    assert "mains" not in coordinator.state.utility_cost_rate_by_circuit
    assert coordinator.refreshed_cost_estimates == 1


@pytest.mark.parametrize(
    "replacement",
    [
        {"utility_energy_entity": "sensor.opower_replacement_usage"},
        {"utility_cost_entity": "sensor.opower_replacement_cost"},
    ],
)
@pytest.mark.asyncio
async def test_replacing_utility_rate_source_clears_the_last_known_rate(
    replacement: dict[str, str],
) -> None:
    coordinator = _SettingsCoordinator(_recommendation())
    controller = settings_controller.SettingsController(coordinator)
    await controller.async_set_utility_comparison_settings(
        "mains",
        utility_energy_entity="sensor.opower_current_bill_usage",
        utility_cost_entity="sensor.opower_current_bill_cost",
    )
    coordinator.refreshed_cost_estimates = 0
    coordinator.state.utility_cost_rate_by_circuit["mains"] = 0.25

    await controller.async_set_utility_comparison_settings("mains", **replacement)

    assert "mains" not in coordinator.state.utility_cost_rate_by_circuit
    assert coordinator.refreshed_cost_estimates == 1


@pytest.mark.asyncio
async def test_settings_controller_sets_goal_and_activity_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_energy_goal_settings("fridge", 12.0, 1.0)
    await controller.async_set_activity_alert_settings("fridge", 45.0, 120.0)

    assert coordinator.store_data.energy_goal_settings_by_circuit["fridge"] == {
        "daily_goal_kwh": 12.0,
        "goal_alert_ratio": 1.0,
    }
    assert coordinator.store_data.activity_alert_settings_by_circuit["fridge"] == {
        "max_active_minutes": 45.0,
        "max_idle_minutes": 120.0,
    }
    assert coordinator.context_calls == [coordinator.now]
    assert coordinator.applied_feature_results == [coordinator.goal_result]
    assert len(coordinator.energy_goal_refreshes) == 1
    circuit_id, config, context = coordinator.energy_goal_refreshes[0]
    assert circuit_id == "fridge"
    assert config.circuit_id == "fridge"
    assert context is coordinator.goal_context
    assert coordinator.dirty_count == 2
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)] * 2
    assert coordinator.updated == [coordinator.state] * 2
    assert coordinator.saved == [coordinator.now] * 2


@pytest.mark.asyncio
async def test_settings_controller_sets_circuit_sensitivity() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_circuit_sensitivity("fridge", "sensitive")

    assert coordinator.store_data.sensitivity_by_circuit["fridge"] == "sensitive"
    assert coordinator.dirty_count == 1
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)]
    assert coordinator.updated == [coordinator.state]
    assert coordinator.saved == [coordinator.now]


def test_settings_controller_reads_circuit_sensitivity() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.sensitivity_by_circuit["fridge"] = "sensitive"
    coordinator.options[CONF_SENSITIVITY] = "quiet"

    assert controller.sensitivity_for_circuit("fridge") == "sensitive"
    assert controller.sensitivity_for_circuit("hvac") == "quiet"


def test_settings_controller_builds_sensitivity_alert_policies() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.sensitivity_by_circuit["fridge"] = "sensitive"
    coordinator.store_data.sensitivity_by_circuit["hvac"] = "quiet"

    assert controller.alert_policy_for_circuit("fridge").min_repeated == 3
    assert controller.alert_policy_for_circuit("hvac").min_repeated == 4
    assert (
        controller.alert_policy_for_circuit("fridge")
        is controller.alert_policy_for_circuit("fridge")
    )


def test_settings_controller_builds_feature_alert_policies() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.sensitivity_by_circuit["fridge"] = "quiet"

    usage_policy = controller.usage_alert_policy_for_circuit("fridge")
    cycle_policy = controller.cycle_alert_policy_for_circuit("fridge")
    short_cycle_policy = (
        controller.appliance_health_short_cycle_alert_policy_for_circuit("fridge")
    )
    water_policy = controller.water_context_alert_policy_for_circuit(
        "fridge",
        "pump_without_flow",
    )

    assert usage_policy.min_repeated == 4
    assert usage_policy.min_baseline_confidence == pytest.approx(0.8)
    assert cycle_policy.min_total_score == pytest.approx(6.0)
    assert short_cycle_policy.min_repeated == 1
    assert short_cycle_policy.min_total_score == pytest.approx(1.5)
    assert water_policy.min_baseline_confidence == pytest.approx(0.7)


def test_settings_controller_returns_nilm_min_delta_for_sensitivity() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.sensitivity_by_circuit["fridge"] = "sensitive"
    coordinator.store_data.sensitivity_by_circuit["hvac"] = "quiet"

    assert controller.nilm_min_delta_w("fridge") == pytest.approx(75.0)
    assert controller.nilm_min_delta_w("hvac") == pytest.approx(150.0)
    assert controller.nilm_min_delta_w("unknown") == pytest.approx(100.0)


def test_settings_controller_reads_runtime_setting_defaults() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    config = SimpleNamespace(
        energy_usage_window_days=7,
        daily_energy_spike_ratio=0.25,
        daily_energy_goal_kwh=2.5,
        energy_goal_alert_ratio=0.9,
        billing_cycle_start_day=15,
        billing_cycle_budget_kwh=90.0,
        billing_cycle_budget_alert_ratio=0.85,
        billing_cycle_min_elapsed_days=5,
        cost_cycle_start_day=10,
        demand_window_minutes=30,
        demand_limit_w=1200.0,
        standby_window_hours=72,
        standby_threshold_w=6.0,
        always_on_alert_w=12.0,
        standby_min_samples=36,
    )
    coordinator.store_data.activity_alert_settings_by_circuit["fridge"] = {
        "max_active_minutes": "45"
    }
    coordinator.store_data.energy_usage_settings_by_circuit["fridge"] = {
        "window_days": "14",
        "daily_spike_ratio": "0.35",
    }
    coordinator.store_data.billing_settings_by_circuit["fridge"] = {
        "budget_kwh": "95.0"
    }
    coordinator.store_data.cost_settings_by_circuit["__global__"] = {
        "default_rate_per_kwh": 0.18,
        "tou_rate_per_kwh": 0.35,
        "tou_start": "16:00",
        "tou_end": "20:00",
        "tou_weekdays": "1,3,5",
        "tou_name": "Critical Peak",
    }
    coordinator.store_data.demand_settings_by_circuit["fridge"] = {
        "demand_limit_w": "1500"
    }
    coordinator.store_data.capacity_settings_by_circuit["fridge"] = {
        "breaker_amps": "20",
        "warning_ratio": "0.75",
    }
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "always_on_alert_w": "15"
    }
    coordinator.store_data.utility_comparison_settings_by_circuit["fridge"] = {
        "utility_energy_entity": "sensor.utility_energy",
        "measured_energy_entities": "sensor.panel_energy,sensor.solar_energy",
        "utility_statistic_period": "hour",
        "tolerance_percent": "8.5",
    }

    assert (
        controller.activity_alert_settings_for_config(
            config,
            "fridge",
        ).max_active_minutes
        == 45.0
    )
    assert (
        controller.activity_alert_settings_for_config(config, "fridge").max_idle_minutes
        is None
    )
    energy_usage = controller.energy_usage_settings_for_config(config, "fridge")
    assert energy_usage.window_days == 14
    assert energy_usage.daily_spike_ratio == 0.35
    energy_goal = controller.energy_goal_settings_for_config(config, "fridge")
    assert energy_goal.daily_goal_kwh == 2.5
    assert energy_goal.goal_alert_ratio == 0.9
    billing = controller.billing_cycle_settings_for_config(config, "fridge")
    assert billing.cycle_start_day == 15
    assert billing.budget_kwh == 95.0
    assert billing.budget_alert_ratio == 0.85
    assert billing.min_elapsed_days == 5
    cost = controller.cost_settings_for_config(config, "fridge")
    assert cost.cycle_start_day == 10
    assert cost.default_rate_per_kwh == 0.18
    assert cost.tou_rate_per_kwh == 0.35
    assert cost.tou_weekdays == (1, 3, 5)
    assert cost.tou_name == "Critical Peak"
    demand = controller.demand_settings_for_config(config, "fridge")
    assert demand.window_minutes == 30
    assert demand.demand_limit_w == 1500.0
    capacity = controller.capacity_settings_for_config("fridge")
    assert capacity.breaker_amps == 20.0
    assert capacity.warning_ratio == 0.75
    standby = controller.standby_settings_for_config(config, "fridge")
    assert standby.window_hours == 72
    assert standby.standby_threshold_w == 6.0
    assert standby.always_on_alert_w == 15.0
    assert standby.min_samples == 36
    utility = controller.utility_comparison_settings_for_circuit("fridge")
    assert utility.utility_energy_entity == "sensor.utility_energy"
    assert utility.utility_statistic_period == "hour"
    assert utility.measured_energy_entities == (
        "sensor.panel_energy",
        "sensor.solar_energy",
    )
    assert utility.tolerance_percent == 8.5


def test_global_cost_settings_are_used_for_each_circuit() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    config = SimpleNamespace(
        cost_cycle_start_day=1,
    )
    coordinator.store_data.cost_settings_by_circuit = {
        "__global__": {
            "default_rate_per_kwh": 0.31,
            "tou_rate_per_kwh": 0.42,
            "tou_start": "16:00",
            "tou_end": "21:00",
            "tou_weekdays": "0,1,2,3,4",
            "tou_name": "Peak",
        },
    }

    cost = controller.cost_settings_for_config(config, "fridge")

    assert cost.default_rate_per_kwh == 0.31
    assert cost.tou_rate_per_kwh == 0.42
    assert cost.tou_start == "16:00"
    assert cost.tou_end == "21:00"
    assert cost.tou_weekdays == (0, 1, 2, 3, 4)
    assert cost.tou_name == "Peak"


@pytest.mark.asyncio
async def test_global_cost_rate_refreshes_estimates_without_a_utility_rate() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        StateReducer,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    coordinator = _SettingsCoordinator(_recommendation())
    coordinator.state = AnalyzerState()
    coordinator.state.daily_energy_usage_by_circuit["fridge"] = 2.0
    coordinator.state.average_kwh_per_day_by_circuit["fridge"] = 1.2
    controller = settings_controller.SettingsController(coordinator)
    processor = CostProcessor(
        settings_for_config=controller.cost_settings_for_config,
        utility_rate_for_circuit=lambda _circuit_id: None,
    )

    def refresh_cost_estimates() -> None:
        coordinator.refreshed_cost_estimates += 1
        StateReducer().apply_updates(
            coordinator.state,
            processor.estimate_state_updates(
                coordinator.circuit_configs,
                coordinator.state,
            ),
        )

    coordinator.refresh_cost_estimates = refresh_cost_estimates

    await controller.async_set_global_cost_rate(0.25)

    assert coordinator.state.effective_electricity_rate_by_circuit["fridge"] == 0.25
    assert coordinator.state.estimated_cost_today_by_circuit["fridge"] == 0.5
    assert coordinator.state.average_cost_per_day_by_circuit["fridge"] == 0.3

    await controller.async_set_global_cost_rate(0.31)

    assert coordinator.state.effective_electricity_rate_by_circuit["fridge"] == 0.31
    assert coordinator.state.estimated_cost_today_by_circuit["fridge"] == 0.62
    assert coordinator.state.average_cost_per_day_by_circuit["fridge"] == 0.37


@pytest.mark.asyncio
async def test_global_cost_rate_keeps_retained_utility_rate_precedence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        StateReducer,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    coordinator = _SettingsCoordinator(_recommendation())
    coordinator.state = AnalyzerState()
    coordinator.state.daily_energy_usage_by_circuit["fridge"] = 2.0
    coordinator.state.average_kwh_per_day_by_circuit["fridge"] = 1.2
    coordinator.state.utility_cost_rate_by_circuit["mains"] = 0.4
    controller = settings_controller.SettingsController(coordinator)
    processor = CostProcessor(
        settings_for_config=controller.cost_settings_for_config,
        utility_rate_for_circuit=lambda _circuit_id: (
            coordinator.state.utility_cost_rate_by_circuit.get("mains")
        ),
    )

    def refresh_cost_estimates() -> None:
        coordinator.refreshed_cost_estimates += 1
        StateReducer().apply_updates(
            coordinator.state,
            processor.estimate_state_updates(
                coordinator.circuit_configs,
                coordinator.state,
            ),
        )

    coordinator.refresh_cost_estimates = refresh_cost_estimates

    await controller.async_set_global_cost_rate(0.25)

    assert coordinator.state.cost_current_rate_by_circuit["fridge"] == 0.25
    assert coordinator.state.effective_electricity_rate_by_circuit["fridge"] == 0.4
    assert coordinator.state.estimated_cost_today_by_circuit["fridge"] == 0.8
    assert coordinator.state.average_cost_per_day_by_circuit["fridge"] == 0.48




@pytest.mark.asyncio
async def test_global_tou_controls_persist_one_shared_tariff() -> None:
    coordinator = _SettingsCoordinator(_recommendation())
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_global_tou_rate(0.42)
    await controller.async_set_global_tou_time("tou_start", "16:00")
    await controller.async_set_global_tou_time("tou_end", "21:00")
    await controller.async_set_global_tou_weekday(0, True)
    await controller.async_set_global_tou_weekday(2, True)
    await controller.async_set_global_tou_name("Critical Peak")

    assert coordinator.store_data.cost_settings_by_circuit["__global__"] == {
        "tou_rate_per_kwh": 0.42,
        "tou_start": "16:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,2",
        "tou_name": "Critical Peak",
    }
