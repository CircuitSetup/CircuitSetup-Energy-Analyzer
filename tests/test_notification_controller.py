from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.managers import (
    notification_controller,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    Severity,
)


def test_notification_controller_episode_key_uses_public_current_time() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    seen: list[datetime] = []
    recommendation = SimpleNamespace(
        recommendation_id="rec-1",
        circuit_id="fridge",
        setting_key="daily_spike_ratio",
        current_value=0.25,
        suggested_value=0.35,
        apply_payload={},
        reason="Observed variation.",
        feature="energy_usage",
        evidence={"days": 7},
    )

    def pending_recommendations(timestamp: datetime) -> list[object]:
        seen.append(timestamp)
        return [recommendation]

    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
        ),
        settings_controller=SimpleNamespace(
            pending_settings_recommendations=pending_recommendations,
        ),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    key = controller.settings_recommendation_episode_key()

    assert seen == [now]
    assert key


def test_notification_controller_owns_episode_key_compaction() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    recommendations = [
        SimpleNamespace(
            recommendation_id=f"rec-{index}",
            circuit_id="fridge",
            setting_key="daily_spike_ratio",
            current_value=0.25,
            suggested_value=0.35,
            apply_payload={},
            reason="Observed variation.",
            feature="energy_usage",
            evidence={"index": index},
        )
        for index in range(101)
    ]
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
        ),
        settings_controller=SimpleNamespace(
            pending_settings_recommendations=lambda timestamp: recommendations,
        ),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    key = controller.settings_recommendation_episode_key()

    assert key == (
        ("version", "sha256:v1"),
        ("pending_count", "101"),
        ("fingerprint", key[2][1]),
    )
    assert len(key[2][1]) == 64


@pytest.mark.asyncio
async def test_notification_controller_uses_pause_controller_before_suppressing(
    monkeypatch,
) -> None:
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="runtime",
    )
    created: list[AlertEvidence] = []

    async def create_notification(hass, alert_to_create, *, config=None) -> None:
        del hass, config
        created.append(alert_to_create)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )

    class _EvidenceActions:
        def alerts_paused(self, circuit_id: str) -> bool:
            coordinator.paused_circuits.discard(circuit_id)
            return False

        def has_suppressed_alert_feedback(self, alert_to_check: AlertEvidence) -> bool:
            del alert_to_check
            return False

    coordinator = SimpleNamespace(
        hass=SimpleNamespace(),
        paused_circuits={"fridge"},
        evidence_actions=_EvidenceActions(),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=SimpleNamespace(settings_recommendation_notification_episode_key=()),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    await controller.async_notify_alert(alert)

    assert created == [alert]
