from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import (
    Observation,
    alert_feedback_fingerprint,
    alert_feedback_fingerprint_candidates,
    alert_feedback_fingerprint_for_observation,
)
from custom_components.circuitsetup_energy_analyzer.managers.evidence_actions import (
    EvidenceActionController,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
)


class _ActionCoordinator:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            hvac_current_episode_by_stream={},
            hvac_efficiency_by_circuit={},
            hvac_association_revision_by_circuit={},
        )
        self.store_data = SimpleNamespace(
            maintenance_by_circuit={},
            alert_feedback={},
            alerts=[],
            hvac_baseline_era_by_stream={},
            hvac_response_history_by_stream={},
            learning_started_at_by_circuit={},
        )
        self.paused_circuits: set[str] = set()
        self.refreshed: list[tuple[str, datetime] | datetime] = []
        self.updated: list[object] = []
        self.saved: list[datetime] = []
        self.dirty_count = 0
        self.relearned: list[str] = []
        self.lifecycle_features: list[str] = []
        self.lifecycle_sequence: list[str] = []
        self.dismissed_alert_ids: list[str] = []
        self.now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
        self.store_persistence = SimpleNamespace(
            async_save_if_dirty=self._record_store_save,
            mark_dirty=self._record_store_dirty,
        )
        self.circuit_registry = SimpleNamespace(
            config_for_circuit=self._lookup_config_for_circuit,
        )
        self.notification_controller = SimpleNamespace(
            async_dismiss_alert_notification=self._dismiss_alert_notification,
            async_notify_lifecycle_update=self._notify_lifecycle_update,
        )

    def current_time(self) -> datetime:
        return self.now

    def refresh_ux_state_for_circuit(
        self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        self.refreshed.append((circuit_id, now))

    def refresh_all_ux_state(self, now: datetime) -> None:
        self.refreshed.append(now)

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    async def _record_store_save(self, now: datetime) -> None:
        self.saved.append(now)

    async def _dismiss_alert_notification(self, alert_id: str) -> None:
        self.dismissed_alert_ids.append(alert_id)

    async def _notify_lifecycle_update(self, circuit_id: str, **kwargs: object) -> None:
        del circuit_id
        feature = str(kwargs["feature"])
        self.lifecycle_features.append(feature)
        self.lifecycle_sequence.append(feature)

    def _record_store_dirty(self) -> None:
        self.dirty_count += 1

    def _lookup_config_for_circuit(self, circuit_id: str) -> None:
        del circuit_id
        return None

    def apply_nilm_alert_feedback(
        self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        del alert, action, now

    async def async_relearn_baseline(self, circuit_id: str) -> None:
        self.relearned.append(circuit_id)
        self.lifecycle_sequence.append("baseline_reset")
        self.store_data.learning_started_at_by_circuit[circuit_id] = (
            self.now.isoformat()
        )


def _alert(circuit_id: str, feature: str) -> AlertEvidence:
    return AlertEvidence(
        timestamp=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        circuit_id=circuit_id,
        severity=Severity.WARNING,
        message="Possible issue",
        feature=feature,
        change_ratio=0.25,
    )


def test_evidence_action_controller_owns_alert_lookup_and_retirement() -> None:
    persisted = _alert("fridge", "daily_energy")
    active = _alert("hvac", "runtime")
    coordinator = _ActionCoordinator()
    coordinator.store_data.alerts = [persisted]
    coordinator.state.active_alerts_by_circuit = {"hvac": [active]}
    coordinator.state.anomaly_score_by_circuit = {"hvac": 0.25}
    controller = EvidenceActionController(coordinator)

    assert controller.alert_for_id(notification_id_for_alert(persisted)) == persisted
    assert controller.alert_for_id(notification_id_for_alert(active)) == active

    controller.retire_alert_id(notification_id_for_alert(active))

    assert coordinator.store_data.alerts == [persisted]
    assert coordinator.state.active_alerts_by_circuit == {}
    assert coordinator.state.anomaly_score_by_circuit == {}
    assert coordinator.dirty_count == 1


def test_evidence_action_controller_retirement_clears_only_matching_cache() -> None:
    active = _alert("hvac", "runtime")
    active_id = notification_id_for_alert(active)
    coordinator = _ActionCoordinator()
    coordinator.store_data.alerts = [active]
    coordinator.state.active_alerts_by_circuit = {"hvac": [active]}
    coordinator.state.anomaly_score_by_circuit = {"hvac": 0.25}
    coordinator.state.alert_evidence_by_circuit = {
        "hvac": {"alert_id": active_id, "feature": "runtime"},
        "fridge": {"alert_id": "newer-alert", "feature": "daily_energy"},
    }
    controller = EvidenceActionController(coordinator)

    controller.retire_alert_id(active_id)

    assert coordinator.state.alert_evidence_by_circuit == {
        "fridge": {"alert_id": "newer-alert", "feature": "daily_energy"},
    }


def test_evidence_action_controller_retirement_keeps_newer_cached_alert() -> None:
    active = _alert("hvac", "runtime")
    coordinator = _ActionCoordinator()
    coordinator.store_data.alerts = [active]
    coordinator.state.active_alerts_by_circuit = {"hvac": [active]}
    coordinator.state.anomaly_score_by_circuit = {"hvac": 0.25}
    coordinator.state.alert_evidence_by_circuit = {
        "hvac": {"alert_id": "newer-alert", "feature": "runtime"},
    }
    controller = EvidenceActionController(coordinator)

    controller.retire_alert_id(notification_id_for_alert(active))

    assert coordinator.state.alert_evidence_by_circuit["hvac"]["alert_id"] == (
        "newer-alert"
    )


@pytest.mark.asyncio
async def test_evidence_action_controller_pauses_and_acknowledges_alerts() -> None:
    coordinator = _ActionCoordinator()
    alert = _alert("fridge", "daily_energy")
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts = [alert]
    coordinator.state.active_alerts_by_circuit = {"fridge": [alert]}
    controller = EvidenceActionController(coordinator)

    await controller.async_pause_alerts("fridge")
    missing = await controller.async_acknowledge_alert("missing")
    acknowledged = await controller.async_acknowledge_alert(alert_id)

    assert "fridge" in coordinator.paused_circuits
    assert missing is False
    assert acknowledged is True
    assert coordinator.store_data.alerts == []
    assert coordinator.state.active_alerts_by_circuit == {}
    assert coordinator.saved == [coordinator.now]
    assert coordinator.updated == [coordinator.state, coordinator.state]


@pytest.mark.asyncio
async def test_evidence_action_controller_maintenance_and_feedback() -> None:
    coordinator = _ActionCoordinator()
    controller = EvidenceActionController(coordinator)

    await controller.async_start_maintenance(
        "fridge",
        note="Changed filter",
        duration="02:00:00",
        relearn_on_end=True,
    )
    await controller.async_end_maintenance("fridge")

    assert coordinator.store_data.maintenance_by_circuit["fridge"]["active"] is False
    assert coordinator.store_data.maintenance_by_circuit["fridge"]["note"] == (
        "Changed filter"
    )
    assert coordinator.relearned == ["fridge"]
    assert coordinator.lifecycle_features == [
        "maintenance_completed",
        "relearning_started",
    ]
    assert coordinator.lifecycle_sequence == [
        "baseline_reset",
        "maintenance_completed",
        "relearning_started",
    ]
    assert "fridge" not in coordinator.paused_circuits
    assert coordinator.dirty_count == 2


@pytest.mark.asyncio
async def test_ending_inactive_maintenance_does_not_emit_completion() -> None:
    coordinator = _ActionCoordinator()
    controller = EvidenceActionController(coordinator)

    await controller.async_end_maintenance("fridge")

    assert coordinator.lifecycle_features == []


@pytest.mark.asyncio
async def test_timed_maintenance_expiry_honors_relearn_on_end() -> None:
    coordinator = _ActionCoordinator()
    controller = EvidenceActionController(coordinator)

    await controller.async_start_maintenance(
        "fridge",
        duration="01:30:00",
        relearn_on_end=True,
    )
    await controller.async_start_maintenance(
        "freezer",
        duration="02:00:00",
    )

    maintenance = coordinator.store_data.maintenance_by_circuit["fridge"]
    assert maintenance["active"] is True
    assert maintenance["expires_at"] == "2026-06-30T13:30:00+00:00"
    assert "fridge" in coordinator.paused_circuits

    coordinator.now = datetime(2026, 6, 30, 13, 30, tzinfo=UTC)

    assert controller.alerts_paused("fridge") is True

    expired = await controller.async_expire_maintenance_if_due()

    assert expired == ("fridge",)
    assert coordinator.relearned == ["fridge"]
    assert coordinator.store_data.maintenance_by_circuit["fridge"]["active"] is False
    assert coordinator.store_data.maintenance_by_circuit["freezer"]["active"] is True
    assert controller.alerts_paused("fridge") is False
    assert "fridge" not in coordinator.paused_circuits


@pytest.mark.asyncio
async def test_evidence_action_controller_timed_pause_uses_maintenance_expiry() -> None:
    coordinator = _ActionCoordinator()
    controller = EvidenceActionController(coordinator)

    await controller.async_pause_alerts("fridge", duration="00:30:00")

    maintenance = coordinator.store_data.maintenance_by_circuit["fridge"]
    assert maintenance["active"] is True
    assert maintenance["expires_at"] == "2026-06-30T12:30:00+00:00"
    assert maintenance["source"] == "pause_alerts"


@pytest.mark.asyncio
async def test_evidence_action_controller_stores_feedback_and_retires_alert() -> None:
    coordinator = _ActionCoordinator()
    alert = _alert("fridge", "reactive_power")
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts = [alert]
    coordinator.state.active_alerts_by_circuit = {"fridge": [alert]}
    controller = EvidenceActionController(coordinator)

    result = await controller.async_mark_alert_expected(alert_id)

    fingerprint = alert_feedback_fingerprint(alert)
    feedback = coordinator.store_data.alert_feedback[fingerprint]
    assert result is True
    assert feedback["fingerprint"] == fingerprint
    assert feedback["action"] == "expected"
    assert feedback["alert_id"] == alert_id
    assert feedback["evidence_count"] == 1
    assert feedback["expires_at"] == "2026-09-28T12:00:00+00:00"
    assert coordinator.store_data.alerts == []
    assert coordinator.state.active_alerts_by_circuit == {}
    assert coordinator.refreshed == [coordinator.now]
    assert coordinator.updated == [coordinator.state]
    assert coordinator.saved == [coordinator.now]


@pytest.mark.asyncio
async def test_expected_hvac_feedback_starts_new_baseline_era() -> None:
    coordinator = _ActionCoordinator()
    stream_id = "heat_pump|climate.downstairs|cooling"
    alert = replace(
        _alert("heat_pump", "hvac_response_slower"),
        features={
            "health_feature": "hvac_thermostat_efficiency",
            "stream_id": stream_id,
            "recent_episode_ids": ["episode-10", "episode-11", "episode-12"],
        },
    )
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts = [alert]
    coordinator.state.active_alerts_by_circuit = {"heat_pump": [alert]}
    coordinator.state.hvac_current_episode_by_stream[stream_id] = {
        "complete": False
    }
    coordinator.state.hvac_efficiency_by_circuit["heat_pump"] = {
        "finding": "slower"
    }

    result = await EvidenceActionController(
        coordinator
    ).async_mark_alert_expected(alert_id)

    assert result is True
    assert coordinator.store_data.hvac_baseline_era_by_stream[stream_id] == (
        coordinator.now.isoformat()
    )
    assert coordinator.state.hvac_current_episode_by_stream == {}
    assert coordinator.state.hvac_efficiency_by_circuit == {}
    assert coordinator.state.hvac_association_revision_by_circuit == {"heat_pump": 1}


@pytest.mark.asyncio
async def test_confirmed_hvac_feedback_excludes_recent_episode_range() -> None:
    coordinator = _ActionCoordinator()
    stream_id = "heat_pump|climate.downstairs|cooling"
    recent_ids = ["episode-10", "episode-11", "episode-12"]
    coordinator.store_data.hvac_response_history_by_stream[stream_id] = [
        {"started_at": episode_id, "excluded_from_baseline": False}
        for episode_id in ["episode-9", *recent_ids]
    ]
    alert = replace(
        _alert("heat_pump", "hvac_response_slower"),
        features={
            "health_feature": "hvac_thermostat_efficiency",
            "stream_id": stream_id,
            "recent_episode_ids": recent_ids,
        },
    )
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts = [alert]
    coordinator.state.active_alerts_by_circuit = {"heat_pump": [alert]}

    await EvidenceActionController(coordinator).async_mark_alert_confirmed(alert_id)

    history = coordinator.store_data.hvac_response_history_by_stream[stream_id]
    assert history[0]["excluded_from_baseline"] is False
    assert all(
        episode["excluded_from_baseline"] is True for episode in history[1:]
    )


@pytest.mark.asyncio
async def test_feedback_action_carries_v2_evidence_count_into_v3() -> None:
    coordinator = _ActionCoordinator()
    alert = replace(
        _alert("fridge", "daily_energy_spike"),
        observed_value=2.61,
        baseline_value=2.0,
        change_ratio=0.305,
    )
    alert_id = notification_id_for_alert(alert)
    coordinator.store_data.alerts = [alert]
    coordinator.state.active_alerts_by_circuit = {"fridge": [alert]}
    legacy_key = next(
        key
        for key in alert_feedback_fingerprint_candidates(alert)
        if key.startswith("alert:v2|")
    )
    coordinator.store_data.alert_feedback[legacy_key] = {
        "action": "unhelpful",
        "evidence_count": 2,
        "expires_at": (coordinator.now + timedelta(days=1)).isoformat(),
    }

    await EvidenceActionController(coordinator).async_mark_alert_unhelpful(alert_id)

    current_key = alert_feedback_fingerprint(alert)
    assert current_key.startswith("alert:v3|")
    assert coordinator.store_data.alert_feedback[current_key]["evidence_count"] == 3
    assert legacy_key not in coordinator.store_data.alert_feedback


def test_evidence_action_controller_annotates_suppressed_feedback() -> None:
    coordinator = _ActionCoordinator()
    alert = _alert("fridge", "reactive_power")
    fingerprint = alert_feedback_fingerprint(alert)
    coordinator.store_data.alert_feedback[fingerprint] = {
        "action": "expected",
        "expires_at": (coordinator.now + timedelta(days=1)).isoformat(),
    }
    controller = EvidenceActionController(coordinator)

    found_fingerprint, feedback = controller.alert_feedback_for(alert)
    annotated = controller.alert_with_feedback(alert)

    assert found_fingerprint == fingerprint
    assert feedback["action"] == "expected"
    assert controller.has_suppressed_alert_feedback(alert) is True
    assert annotated.feedback_status == "expected"
    assert annotated.feedback_effect == (
        "Notifications suppressed for this expected pattern"
    )
    assert annotated.matching_feedback_fingerprint == fingerprint


def test_evidence_action_controller_adjusts_repeated_count_for_unhelpful() -> None:
    coordinator = _ActionCoordinator()
    observation = Observation(
        circuit_id="fridge",
        feature="reactive_power",
        score=1.0,
        baseline_confidence=1.0,
        observed_at=coordinator.now,
    )
    fingerprint = alert_feedback_fingerprint_for_observation(observation)
    coordinator.store_data.alert_feedback[fingerprint] = {
        "action": "unhelpful",
        "expires_at": (coordinator.now + timedelta(days=1)).isoformat(),
    }
    controller = EvidenceActionController(coordinator)

    assert controller.adjusted_min_repeated_for_observation(observation, 3) == 5
