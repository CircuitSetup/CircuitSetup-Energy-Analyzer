from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import (
    notification_controller,
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
