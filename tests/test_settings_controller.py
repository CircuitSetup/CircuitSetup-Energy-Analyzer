from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

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
        )
        self.now = datetime(2026, 6, 30, 12, 5, tzinfo=UTC)
        self.set_values: list[tuple[str, str, object]] = []
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

    def _set_recommendation_setting_value(
        self,
        circuit_id: str,
        setting_key: str,
        value: object,
    ) -> None:
        self.set_values.append((circuit_id, setting_key, value))

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
    assert coordinator.set_values == [
        ("fridge", "daily_spike_ratio", 0.35),
        ("fridge", "daily_spike_ratio", 0.25),
        ("fridge", "daily_spike_ratio", 0.25),
    ]
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
