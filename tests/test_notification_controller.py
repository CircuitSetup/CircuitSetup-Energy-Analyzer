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


@pytest.mark.asyncio
async def test_alert_notifications_are_dismissed_when_evidence_is_no_longer_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_alert = AlertEvidence(
        timestamp=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Dryer runtime changed.",
        feature="run_cycle_duration_s",
    )
    resolved_alert = AlertEvidence(
        timestamp=datetime(2026, 7, 22, 11, 0, tzinfo=UTC),
        circuit_id="washer",
        severity=Severity.WARNING,
        message="Washer energy use changed.",
        feature="daily_energy_usage_spike",
    )
    dismissed: list[str] = []

    async def dismiss_notification(hass: object, notification_id: str) -> None:
        del hass
        dismissed.append(notification_id)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_dismiss_persistent_notification",
        dismiss_notification,
        raising=False,
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(),
        state=SimpleNamespace(
            active_alerts_by_circuit={"dryer": [active_alert]},
        ),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
            alerts=[resolved_alert, active_alert],
        ),
    )
    controller = notification_controller.NotificationController(coordinator)
    controller.notified_alert_ids.update(
        {
            notification_id_for_alert(resolved_alert),
            notification_id_for_alert(active_alert),
        }
    )

    await controller.async_sync_alert_notifications()

    assert dismissed == [notification_id_for_alert(resolved_alert)]
    assert controller.notified_alert_ids == {notification_id_for_alert(active_alert)}


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
        state=SimpleNamespace(learning_by_circuit={"fridge": False}),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
        ),
        settings_controller=SimpleNamespace(
            pending_settings_recommendations=pending_recommendations,
        ),
    )
    controller = notification_controller.NotificationController(
        coordinator,
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
        state=SimpleNamespace(learning_by_circuit={"fridge": False}),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
        ),
        settings_controller=SimpleNamespace(
            pending_settings_recommendations=lambda timestamp: recommendations,
        ),
    )
    controller = notification_controller.NotificationController(
        coordinator,
    )

    key = controller.settings_recommendation_episode_key()

    assert key == (
        ("version", "sha256:v1"),
        ("pending_count", "101"),
        ("fingerprint", key[2][1]),
    )
    assert len(key[2][1]) == 64


@pytest.mark.asyncio
async def test_settings_notification_repeats_only_for_new_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)

    def recommendation(recommendation_id: str, *, evidence: int) -> SimpleNamespace:
        return SimpleNamespace(
            recommendation_id=recommendation_id,
            circuit_id="fridge",
            setting_key="daily_spike_ratio",
            current_value=0.25,
            suggested_value=0.35,
            apply_payload={},
            reason=f"Observed variation {evidence}.",
            feature="energy_usage",
            evidence={"days": evidence},
        )

    pending = [recommendation("rec-1", evidence=7)]
    notifications_created: list[int] = []

    async def create_notification(hass, entry_id, *, total_pending):
        del hass, entry_id
        notifications_created.append(total_pending)

    async def save_if_dirty(timestamp):
        assert timestamp == now

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_settings_recommendation_notification",
        create_notification,
    )
    state = SimpleNamespace(
        settings_recommendation_count_by_circuit={"fridge": 1},
        learning_by_circuit={"fridge": True},
    )
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        hass=SimpleNamespace(),
        entry_id="entry-1",
        state=state,
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
        ),
        settings_controller=SimpleNamespace(
            pending_settings_recommendations=lambda timestamp: pending,
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=save_if_dirty,
        ),
    )
    controller = notification_controller.NotificationController(
        coordinator,
    )

    await controller.async_notify_settings_recommendations_if_needed()
    assert notifications_created == []

    state.learning_by_circuit["fridge"] = False
    state.energy_usage_evidence_by_circuit = {
        "fridge": {"status": "learning"},
    }
    await controller.async_notify_settings_recommendations_if_needed()
    assert notifications_created == []

    state.energy_usage_evidence_by_circuit["fridge"]["status"] = "tracking"
    await controller.async_notify_settings_recommendations_if_needed()
    pending[0] = recommendation("rec-1", evidence=8)
    await controller.async_notify_settings_recommendations_if_needed()
    pending.append(recommendation("rec-2", evidence=7))
    state.settings_recommendation_count_by_circuit = {"fridge": 2}
    await controller.async_notify_settings_recommendations_if_needed()
    pending.pop(0)
    state.settings_recommendation_count_by_circuit = {"fridge": 1}
    await controller.async_notify_settings_recommendations_if_needed()

    assert notifications_created == [1, 2]


@pytest.mark.asyncio
async def test_settings_notification_is_dismissed_when_no_suggestions_are_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismissed: list[str] = []

    async def dismiss_notification(hass: object, notification_id: str) -> None:
        del hass
        dismissed.append(notification_id)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_dismiss_persistent_notification",
        dismiss_notification,
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(),
        entry_id="entry-1",
        state=SimpleNamespace(
            settings_recommendation_count_by_circuit={},
            learning_by_circuit={},
        ),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(("rec-1",),),
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(coordinator)

    await controller.async_notify_settings_recommendations_if_needed()

    assert dismissed == [
        notification_controller.notifications.settings_recommendation_notification_id(
            "entry-1"
        )
    ]
    assert controller.settings_recommendation_notification_episode_key == ()


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
        state=SimpleNamespace(learning_by_circuit={"fridge": False}),
        evidence_actions=_EvidenceActions(),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=SimpleNamespace(settings_recommendation_notification_episode_key=()),
    )
    controller = notification_controller.NotificationController(
        coordinator,
    )

    await controller.async_notify_alert(alert)

    assert created == [alert]


@pytest.mark.asyncio
async def test_alert_notifications_wait_for_live_learning_state(
    monkeypatch,
) -> None:
    created: list[AlertEvidence] = []

    async def create_notification(hass, alert, *, config=None) -> None:
        del hass, config
        created.append(alert)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )
    now = datetime(2026, 7, 20, 12, tzinfo=UTC)
    routine_alert = AlertEvidence(
        timestamp=now,
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Runtime changed",
        feature="run_cycle_duration_s",
    )
    obvious_alert = AlertEvidence(
        timestamp=now,
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Circuit capacity exceeded",
        feature="circuit_capacity",
    )
    error_alert = AlertEvidence(
        timestamp=now,
        circuit_id="dryer",
        severity=Severity.ERROR,
        message="Critical issue",
        feature="critical_issue",
    )
    state = SimpleNamespace(learning_by_circuit={})
    config = SimpleNamespace(circuit_id="dryer")
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        current_time=lambda: now,
        state=state,
        processor_runtime=SimpleNamespace(
            learning_mature=lambda circuit_config, timestamp: True,
        ),
        evidence_actions=SimpleNamespace(
            alerts_paused=lambda circuit_id: False,
            has_suppressed_alert_feedback=lambda alert: False,
        ),
        circuit_registry=SimpleNamespace(
            config_for_circuit=lambda circuit_id: config,
        ),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
            appliance_notification_preferences={},
            notification_delivery_state={},
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(coordinator)

    await controller.async_notify_alert(routine_alert)
    assert created == []

    state.learning_by_circuit["dryer"] = True
    await controller.async_notify_alert(obvious_alert)
    await controller.async_notify_alert(error_alert)
    assert created == []

    state.learning_by_circuit["dryer"] = False
    await controller.async_notify_alert(routine_alert)
    await controller.async_notify_alert(obvious_alert)
    await controller.async_notify_alert(error_alert)
    assert created == [routine_alert, obvious_alert, error_alert]


@pytest.mark.asyncio
async def test_alert_notifications_wait_for_energy_learning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[AlertEvidence] = []

    async def create_notification(hass, alert, *, config=None) -> None:
        del hass, config
        created.append(alert)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Runtime changed",
        feature="run_cycle_duration_s",
    )
    state = SimpleNamespace(
        learning_by_circuit={"hvac": False},
        energy_usage_evidence_by_circuit={
            "hvac": {"status": "learning"},
        },
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        current_time=lambda: now,
        state=state,
        evidence_actions=SimpleNamespace(
            alerts_paused=lambda circuit_id: False,
            has_suppressed_alert_feedback=lambda alert: False,
        ),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=SimpleNamespace(
            settings_recommendation_notification_episode_key=(),
            appliance_notification_preferences={},
            notification_delivery_state={},
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(coordinator)

    await controller.async_notify_alert(alert)
    assert created == []

    state.energy_usage_evidence_by_circuit["hvac"]["status"] = "tracking"
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
        state=SimpleNamespace(learning_by_circuit={"dryer": False}),
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
    )

    await controller.async_notify_alert(alerts[0])
    await controller.async_notify_alert(alerts[1])

    assert sent == []
    assert len(store_data.notification_delivery_state["deferred"]) == 1
    assert store_data.notification_delivery_state["deferred"][0][
        "defer_until"
    ] == "2026-07-14T07:00:00-04:00"

    coordinator.state.learning_by_circuit["dryer"] = True
    await controller.async_dispatch_due(datetime(2026, 7, 14, 12, tzinfo=UTC))
    assert sent == []
    assert store_data.notification_delivery_state["deferred"] == []


@pytest.mark.asyncio
async def test_deferred_alert_is_dropped_after_its_evidence_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[AlertEvidence] = []

    async def create_notification(hass, alert, *, config=None) -> None:
        del hass, config
        sent.append(alert)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_alert_notification",
        create_notification,
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 14, 3, 30, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Runtime issue",
        feature="run_cycle_duration_s",
    )
    alert_id = notification_id_for_alert(alert)
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        notification_delivery_state={
            "deferred": [
                {
                    "alert_id": alert_id,
                    "defer_until": "2026-07-14T07:00:00+00:00",
                }
            ]
        },
        alerts=[alert],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        state=SimpleNamespace(
            learning_by_circuit={"dryer": False},
            active_alerts_by_circuit={},
        ),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(coordinator)

    await controller.async_dispatch_due(datetime(2026, 7, 14, 8, tzinfo=UTC))

    assert sent == []
    assert store_data.notification_delivery_state["deferred"] == []


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
        state=SimpleNamespace(learning_by_circuit={"dryer": False}),
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
    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 8, 12, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Runtime changed",
        feature="run_cycle_duration_s",
    )
    active_alert = AlertEvidence(
        timestamp=datetime(2026, 7, 9, 12, tzinfo=UTC),
        circuit_id="washer",
        severity=Severity.WARNING,
        message="Washer energy changed",
        feature="daily_energy_spike",
    )
    completed_days = [
        {
            "date": (
                datetime(2026, 6, 29, tzinfo=UTC) + timedelta(days=offset)
            ).date().isoformat(),
            "usage_kwh": 1.0,
            "complete": True,
        }
        for offset in range(14)
    ]
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={},
        notification_delivery_state={
            "weekly": [
                {
                    "alert_id": notification_id_for_alert(alert),
                    "appliance_key": "circuit:dryer",
                    "category": "unusual_runtime",
                    "queued_at": "2026-07-08T12:00:00+00:00",
                },
                {
                    "alert_id": notification_id_for_alert(active_alert),
                    "appliance_key": "circuit:washer",
                    "category": "unusual_energy",
                    "queued_at": "2026-07-09T12:00:00+00:00",
                }
            ]
        },
        weekly_digest_settings={"enabled": False, "delivery": "panel_only"},
        energy_usage_by_circuit={
            "dryer": {"days": completed_days},
            "washer": {"days": completed_days},
        },
        nilm_appliance_assignments_by_circuit={},
        nilm_session_history_by_circuit={},
        alerts=[alert, active_alert],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="America/New_York")),
        circuit_configs=(
            SimpleNamespace(
                circuit_id="dryer",
                name="Dryer",
                mode=SimpleNamespace(value="single_phase"),
            ),
            SimpleNamespace(
                circuit_id="washer",
                name="Washer",
                mode=SimpleNamespace(value="single_phase"),
            ),
        ),
        state=SimpleNamespace(
            active_alerts_by_circuit={"washer": [active_alert]},
            learning_by_circuit={"dryer": False, "washer": False},
            learning_progress_by_circuit={
                "dryer": {"alert_ready": True},
                "washer": {"alert_ready": True},
            },
        ),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
    )

    await controller.async_refresh_weekly_digest(
        datetime(2026, 7, 13, 12, tzinfo=UTC)
    )

    assert store_data.weekly_digest_settings["latest_report"]["week_start"] == (
        "2026-07-06"
    )
    report = store_data.weekly_digest_settings["latest_report"]
    assert [item["appliance_key"] for item in report["observed_alerts"]] == [
        "circuit:dryer"
    ]
    assert [item["appliance_key"] for item in report["unresolved_items"]] == [
        "circuit:washer"
    ]
    assert store_data.notification_delivery_state["weekly"] == []


@pytest.mark.parametrize("retain_alert", [False, True])
@pytest.mark.asyncio
async def test_weekly_queue_drops_routine_alert_when_circuit_reenters_learning(
    monkeypatch,
    retain_alert: bool,
) -> None:
    notifications_created: list[object] = []

    async def create_notification(hass, digest) -> None:
        del hass
        notifications_created.append(digest)

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_weekly_digest_notification",
        create_notification,
    )
    now = datetime(2026, 7, 8, 12, tzinfo=UTC)
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Runtime changed",
        feature="run_cycle_duration_s",
    )
    alert_id = notification_id_for_alert(alert)
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        appliance_notification_preferences={},
        notification_delivery_state={
            "weekly": [
                {
                    "alert_id": alert_id,
                    "appliance_key": "circuit:dryer",
                    "category": "unusual_runtime",
                    "queued_at": now.isoformat(),
                }
            ]
        },
        weekly_digest_settings={
            "enabled": False,
            "delivery": "persistent_notification",
        },
        alerts=[alert] if retain_alert else [],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        state=SimpleNamespace(learning_by_circuit={"dryer": True}),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(coordinator)

    await controller.async_refresh_weekly_digest(
        datetime(2026, 7, 13, 12, tzinfo=UTC)
    )

    assert notifications_created == []
    assert store_data.notification_delivery_state["weekly"] == []
    assert "latest_report" not in store_data.weekly_digest_settings


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
    )

    await controller.async_dispatch_due(datetime(2026, 7, 14, 1, tzinfo=UTC))

    assert summaries == []
    assert store_data.notification_delivery_state["daily"]


@pytest.mark.asyncio
async def test_daily_queue_deduplicates_observed_alerts_by_id(monkeypatch) -> None:
    created_summaries: list[list[AlertEvidence]] = []

    async def create_summary(hass, alerts, *, summary_date) -> None:
        del hass
        assert summary_date == "2026-07-13"
        created_summaries.append(list(alerts))

    monkeypatch.setattr(
        notification_controller.notifications,
        "async_create_daily_summary_notification",
        create_summary,
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 13, 12, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Dryer energy changed",
        feature="daily_energy_spike",
    )
    alert_id = notification_id_for_alert(alert)
    queued = {
        "alert_id": alert_id,
        "queued_at": "2026-07-13T12:00:00+00:00",
    }
    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        notification_delivery_state={"daily": [queued, dict(queued)]},
        alerts=[alert],
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        state=SimpleNamespace(
            active_alerts_by_circuit={},
            learning_by_circuit={"dryer": False},
        ),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )

    await notification_controller.NotificationController(
        coordinator
    ).async_dispatch_due(datetime(2026, 7, 14, 1, tzinfo=UTC))

    assert len(created_summaries) == 1
    assert [alert.feature for alert in created_summaries[0]] == [
        "daily_energy_spike"
    ]
    assert store_data.notification_delivery_state["daily"] == []


@pytest.mark.asyncio
async def test_dispatch_due_skips_alert_history_when_queues_are_empty() -> None:
    class AlertHistory:
        def __iter__(self):
            raise AssertionError("alert history should not be scanned")

    store_data = SimpleNamespace(
        settings_recommendation_notification_episode_key=(),
        notification_delivery_state={},
        alerts=AlertHistory(),
    )
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC")),
        circuit_registry=SimpleNamespace(config_for_circuit=lambda circuit_id: None),
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: None),
    )
    controller = notification_controller.NotificationController(
        coordinator,
    )

    await controller.async_dispatch_due(datetime(2026, 7, 14, 1, tzinfo=UTC))
