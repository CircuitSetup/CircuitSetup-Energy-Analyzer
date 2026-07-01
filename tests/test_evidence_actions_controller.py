from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.alerting import (
    alert_feedback_fingerprint,
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
        self.state = SimpleNamespace()
        self.store_data = SimpleNamespace(
            maintenance_by_circuit={},
            alert_feedback={},
            alerts=[],
        )
        self.paused_circuits: set[str] = set()
        self.refreshed: list[tuple[str, datetime] | datetime] = []
        self.updated: list[object] = []
        self.saved: list[datetime] = []
        self.dirty_count = 0
        self.relearned: list[str] = []
        self.now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    def _now_fn(self) -> datetime:
        return self.now

    def _refresh_ux_state_for_circuit(
        self,
        circuit_id: str,
        now: datetime,
    ) -> None:
        self.refreshed.append((circuit_id, now))

    def _refresh_all_ux_state(self, now: datetime) -> None:
        self.refreshed.append(now)

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    async def _async_save_store(self, now: datetime) -> None:
        self.saved.append(now)

    def _mark_store_dirty(self) -> None:
        self.dirty_count += 1

    def _config_for_circuit(self, circuit_id: str) -> None:
        del circuit_id
        return None

    def _apply_nilm_alert_feedback(
        self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        del alert, action, now

    async def async_relearn_baseline(self, circuit_id: str) -> None:
        self.relearned.append(circuit_id)


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
    assert "fridge" not in coordinator.paused_circuits
    assert coordinator.dirty_count == 2


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
