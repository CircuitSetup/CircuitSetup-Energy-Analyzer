from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.managers import (
    notification_controller,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
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


def test_settings_recommendation_notification_opens_panel_review() -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    assert notifications._settings_recommendations_options_path("entry-1") == (
        "/circuitsetup-energy-analyzer-evidence?"
        "review_suggested_settings=1&entry_id=entry-1"
    )


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


@pytest.mark.asyncio
async def test_notification_preferences_gate_and_defer_alerts(monkeypatch) -> None:
    sent: list[AlertEvidence] = []

    async def create_notification(hass, alert_to_create, *, config=None) -> None:
        del hass, config
        sent.append(alert_to_create)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )
    now = datetime(2026, 7, 14, 3, 30, tzinfo=UTC)
    alerts = [
        AlertEvidence(
            timestamp=now,
            circuit_id="dryer",
            severity=Severity.WARNING,
            message="Electrical issue",
            feature="voltage_sag",
        ),
        AlertEvidence(
            timestamp=now,
            circuit_id="dryer",
            severity=Severity.WARNING,
            message="Runtime issue",
            feature="run_cycle_duration_s",
        ),
    ]
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={
            "circuit:dryer": {
                "electrical_issue": False,
                "quiet_hours_start": time(22).isoformat(timespec="minutes"),
                "quiet_hours_end": time(7).isoformat(timespec="minutes"),
            }
        },
        notification_delivery_state={},
        alerts=alerts,
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        current_time=lambda: now,
        evidence_actions=SimpleNamespace(
            alerts_paused=lambda circuit_id: False,
            has_suppressed_alert_feedback=lambda alert: False,
        ),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    await controller.async_notify_alert(alerts[0])
    await controller.async_notify_alert(alerts[1])

    assert sent == []
    assert len(store_data.notification_delivery_state["deferred"]) == 1
    assert store_data.notification_delivery_state["deferred"][0][
        "defer_until"
    ] == "2026-07-14T07:00:00-04:00"


@pytest.mark.asyncio
async def test_finished_run_notifications_use_distinct_ids(monkeypatch) -> None:
    notification_ids: list[str] = []

    async def create_notification(hass, alert, *, config=None) -> None:
        del hass, config
        notification_ids.append(notification_id_for_alert(alert))

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )
    first_stop = datetime(2026, 7, 13, 12, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=first_stop,
            circuit_id="dryer",
            event_type=EventType.STOP,
        ),
        CircuitEvent(
            timestamp=first_stop + timedelta(hours=1),
            circuit_id="dryer",
            event_type=EventType.STOP,
        ),
    ]
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={
            "circuit:dryer": {"finished_running": True}
        },
        notification_delivery_state={},
        alerts=[],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        evidence_actions=SimpleNamespace(
            alerts_paused=lambda circuit_id: False,
            has_suppressed_alert_feedback=lambda alert: False,
        ),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    alerts = await controller.async_notify_finished_events(
        events,
        first_stop + timedelta(hours=1),
    )

    assert len(alerts) == 2
    assert len(notification_ids) == 2
    assert notification_ids[0] != notification_ids[1]


@pytest.mark.asyncio
async def test_weekly_queue_builds_digest_when_global_digest_is_disabled() -> None:
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={},
        notification_delivery_state={
            "weekly": [
                {
                    "alert_id": "runtime-change",
                    "appliance_key": "circuit:dryer",
                    "category": "unusual_runtime",
                    "queued_at": "2026-07-08T12:00:00+00:00",
                }
            ]
        },
        weekly_digest_settings={"enabled": False, "delivery": "panel_only"},
        energy_usage_by_circuit={
            "dryer": {
                "days": [
                    {"date": f"2026-07-{day:02d}", "usage_kwh": 1.0}
                    for day in range(6, 13)
                ]
            }
        },
        nilm_appliance_assignments_by_circuit={},
        nilm_session_history_by_circuit={},
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        circuit_configs=(
            SimpleNamespace(
                circuit_id="dryer",
                name="Dryer",
                mode=SimpleNamespace(value="single_phase"),
            ),
        ),
        state=SimpleNamespace(
            active_alerts_by_circuit={},
            learning_progress_by_circuit={"dryer": {"alert_ready": True}},
        ),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    await controller.async_refresh_weekly_digest(
        datetime(2026, 7, 13, 12, tzinfo=UTC)
    )

    assert store_data.weekly_digest_settings["latest_report"]["week_start"] == (
        "2026-07-06"
    )
    assert store_data.weekly_digest_settings["latest_report"]["unresolved_items"][
        0
    ]["appliance_key"] == "circuit:dryer"
    assert store_data.notification_delivery_state["weekly"] == []


@pytest.mark.asyncio
async def test_weekly_queue_waits_until_its_local_week_has_completed() -> None:
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={},
        notification_delivery_state={
            "weekly": [
                {
                    "alert_id": "runtime-change",
                    "appliance_key": "circuit:dryer",
                    "category": "unusual_runtime",
                    "queued_at": "2026-07-14T12:00:00+00:00",
                }
            ]
        },
        weekly_digest_settings={"enabled": False, "delivery": "panel_only"},
        energy_usage_by_circuit={},
        nilm_appliance_assignments_by_circuit={},
        nilm_session_history_by_circuit={},
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        circuit_configs=(),
        state=SimpleNamespace(
            active_alerts_by_circuit={},
            learning_progress_by_circuit={},
        ),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    await controller.async_refresh_weekly_digest(
        datetime(2026, 7, 15, 12, tzinfo=UTC)
    )

    assert "latest_report" not in store_data.weekly_digest_settings
    assert len(store_data.notification_delivery_state["weekly"]) == 1


@pytest.mark.asyncio
async def test_daily_queue_waits_for_next_home_assistant_local_day(monkeypatch) -> None:
    summaries: list[str] = []

    async def create_summary(hass, alerts, *, summary_date) -> None:
        del hass, alerts
        summaries.append(summary_date)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_daily_summary_notification",
        create_summary,
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 13, 23, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Runtime changed",
        feature="run_cycle_duration_s",
    )
    alert_id = notification_id_for_alert(alert)
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        notification_delivery_state={
            "daily": [
                {
                    "alert_id": alert_id,
                    "queued_at": "2026-07-13T23:00:00+00:00",
                }
            ]
        },
        alerts=[alert],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
        material_evidence_key=lambda feature, evidence: tuple(evidence.items()),
    )

    await controller.async_dispatch_due(datetime(2026, 7, 14, 1, tzinfo=UTC))

    assert summaries == []
    assert store_data.notification_delivery_state["daily"]
