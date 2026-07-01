from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_ADVANCED_SETTINGS
from custom_components.circuitsetup_energy_analyzer.managers import (
    settings_controller,
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
        self.state = SimpleNamespace()
        self.store_data = SimpleNamespace(
            settings_recommendations={
                recommendation.recommendation_id: recommendation
            },
            settings_recommendation_decisions={},
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
            standby_settings_by_circuit={},
            leg_imbalance_settings_by_circuit={},
            metric_consistency_settings_by_circuit={},
            balance_settings_by_circuit={},
            solar_flow_settings_by_circuit={},
            operating_detection_settings_by_circuit={},
        )
        self.options = {
            CONF_ADVANCED_SETTINGS: {"fridge": {"daily_spike_ratio": 0.25}}
        }
        self.now = datetime(2026, 6, 30, 12, 5, tzinfo=UTC)
        self.persist_count = 0
        self.dirty_count = 0
        self.refreshed_recommendations: list[datetime] = []
        self.refreshed_circuits: list[tuple[str, datetime]] = []
        self.updated: list[object] = []
        self.saved: list[datetime] = []
        self.notified = 0
        self.rebuild_calls: list[tuple[datetime, str | None]] = []

    def _now_fn(self) -> datetime:
        return self.now

    async def _async_persist_config_entry_options(self) -> None:
        self.persist_count += 1

    def _mark_store_dirty(self) -> None:
        self.dirty_count += 1

    def _refresh_settings_recommendation_state(self, now: datetime) -> None:
        self.refreshed_recommendations.append(now)

    def _refresh_ux_state_for_circuit(self, circuit_id: str, now: datetime) -> None:
        self.refreshed_circuits.append((circuit_id, now))

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    async def _async_save_store(self, now: datetime) -> None:
        self.saved.append(now)

    async def _notify_settings_recommendations_if_needed(self) -> None:
        self.notified += 1

    def _rebuild_setting_recommendations(
        self,
        now: datetime,
        *,
        circuit_id: str | None = None,
    ) -> bool:
        self.rebuild_calls.append((now, circuit_id))
        return True


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


@pytest.mark.asyncio
async def test_settings_controller_recalculates_and_records_decisions() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_recalculate_setting_recommendations("fridge")
    await controller.async_dismiss_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert coordinator.rebuild_calls == [(coordinator.now, "fridge")]
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
    assert decision.denied_value == recommendation.suggested_value
    assert coordinator.refreshed_recommendations[-1] == coordinator.now


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


def test_settings_controller_clears_advanced_setting_aliases() -> None:
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
