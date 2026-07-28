from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .. import notifications
from ..appliance_notifications import (
    alert_notification_category,
    decide_notification_delivery,
    preferences_from_dict,
)
from ..models import AlertEvidence, CircuitEvent, EventType, Severity
from ..nilm_virtual import nilm_virtual_appliance_alerts
from ..state import circuit_is_learning
from ..weekly_digest import (
    build_weekly_digest,
    completed_week_bounds,
    digest_idempotence_key,
    digest_items_for_coordinator,
)
from .recommendation_episodes import compact_settings_recommendation_episode_key

_LIFECYCLE_MESSAGES = {
    "learning_completed": "{appliance} finished learning its normal behavior.",
    "alert_recovered": "{appliance} returned to its expected behavior.",
}


class NotificationController:
    """Coordinate persistent notifications and duplicate suppression."""

    def __init__(
        self,
        coordinator: Any,
    ) -> None:
        self._coordinator = coordinator
        self._compact_settings_recommendation_episode_key = (
            compact_settings_recommendation_episode_key
        )
        self.notified_alert_ids: set[str] = set()
        self._managed_alert_notification_ids: set[str] = set()
        self._alert_notifications_initialized = False
        self.settings_recommendation_notification_episode_key = (
            self._stored_settings_recommendation_episode_key()
        )
        store_data = self._coordinator.store_data
        store_data.settings_recommendation_notification_episode_key = (
            self.settings_recommendation_notification_episode_key
        )

    async def async_notify_alert(self, alert: AlertEvidence) -> None:
        """Create one persistent alert notification when it is not suppressed."""
        if not self.learning_allows_alert(alert):
            return
        if self._coordinator.evidence_actions.alerts_paused(alert.circuit_id):
            return
        if self._coordinator.evidence_actions.has_suppressed_alert_feedback(alert):
            return
        alert_id = notifications.notification_id_for_alert(alert)
        if alert_id in self.notified_alert_ids:
            return
        decision, appliance_key, category = self._delivery_decision(alert)
        if decision.action == "suppress":
            return
        if decision.action != "send":
            self.notified_alert_ids.add(alert_id)
            self._queue_notification(
                alert_id=alert_id,
                appliance_key=appliance_key,
                category=category,
                action=decision.action,
                defer_until=decision.defer_until,
            )
            return
        self.notified_alert_ids.add(alert_id)
        await notifications.async_create_alert_notification(
            self._coordinator.hass,
            alert,
            config=self._coordinator.circuit_registry.config_for_circuit(
                alert.circuit_id
            ),
        )
        self._managed_alert_notification_ids.add(alert_id)
        self._record_delivery(
            appliance_key,
            category,
            self._current_time(alert.timestamp),
        )

    def learning_allows_alert(self, alert: AlertEvidence) -> bool:
        """Return whether learned evidence is ready for this alert."""
        return self._is_lifecycle_alert(alert) or not self._circuit_is_learning(
            alert.circuit_id
        )

    def _circuit_is_learning(self, circuit_id: str) -> bool:
        return circuit_is_learning(
            getattr(self._coordinator, "state", None),
            circuit_id,
        )

    async def async_sync_alert_notifications(self) -> None:
        """Dismiss alert notifications whose evidence is no longer active."""
        recoverable_ids = set(self._managed_alert_notification_ids)
        if not self._alert_notifications_initialized:
            self._managed_alert_notification_ids.update(
                notifications.notification_id_for_alert(alert)
                for alert in getattr(self._coordinator.store_data, "alerts", ())
                if not self._is_lifecycle_alert(alert)
            )
            self._alert_notifications_initialized = True
        active_alert_ids = self._active_alert_ids()
        alerts_by_id = {
            notifications.notification_id_for_alert(alert): alert
            for alert in getattr(self._coordinator.store_data, "alerts", ())
        }
        for alert_id in sorted(
            self._managed_alert_notification_ids - active_alert_ids
        ):
            recovered_alert = (
                alerts_by_id.get(alert_id) if alert_id in recoverable_ids else None
            )
            await self.async_dismiss_alert_notification(alert_id)
            if (
                recovered_alert is not None
                and not self._coordinator.evidence_actions.alerts_paused(
                    recovered_alert.circuit_id
                )
                and not self._circuit_is_learning(recovered_alert.circuit_id)
            ):
                await self.async_notify_lifecycle_update(
                    recovered_alert.circuit_id,
                    feature="alert_recovered",
                    message=self._lifecycle_message(
                        recovered_alert.circuit_id,
                        "alert_recovered",
                    ),
                    episode_key=(
                        f"alert_recovered:{alert_id}:"
                        f"{recovered_alert.timestamp.isoformat()}"
                    ),
                    now=self._current_time(),
                )
        self._managed_alert_notification_ids.intersection_update(active_alert_ids)
        self.notified_alert_ids.intersection_update(active_alert_ids)

    async def async_notify_learning_transitions(
        self,
        previous_learning: dict[str, bool],
        now: datetime,
    ) -> None:
        """Retain and optionally notify one completion per learning epoch."""
        for circuit_id, was_learning in previous_learning.items():
            if not was_learning or self._circuit_is_learning(circuit_id):
                continue
            epoch = getattr(
                self._coordinator.store_data,
                "learning_started_at_by_circuit",
                {},
            ).get(circuit_id, "initial")
            await self.async_notify_lifecycle_update(
                circuit_id,
                feature="learning_completed",
                message=self._lifecycle_message(
                    circuit_id,
                    "learning_completed",
                ),
                episode_key=f"learning_completed:{epoch}",
                now=now,
            )

    async def async_notify_lifecycle_update(
        self,
        circuit_id: str,
        *,
        feature: str,
        message: str,
        episode_key: str,
        now: datetime,
    ) -> None:
        """Retain and deliver one opt-in appliance lifecycle update."""
        if not self._remember_lifecycle_episode(
            circuit_id,
            feature,
            episode_key,
        ):
            return
        alert = AlertEvidence(
            timestamp=now,
            circuit_id=circuit_id,
            severity=Severity.INFO,
            message=message,
            feature=feature,
            features={
                "notification_type": "lifecycle_update",
                "notification_key": episode_key,
                "appliance_key": f"circuit:{circuit_id}",
            },
        )
        self._coordinator.store_data.alerts.append(alert)
        self._mark_store_dirty()
        alerts_paused = getattr(
            getattr(self._coordinator, "evidence_actions", None),
            "alerts_paused",
            None,
        )
        if callable(alerts_paused) and alerts_paused(circuit_id):
            return
        decision, appliance_key, category = self._delivery_decision(alert)
        if decision.action == "suppress":
            return
        alert_id = notifications.notification_id_for_alert(alert)
        if decision.action != "send":
            self._queue_notification(
                alert_id=alert_id,
                appliance_key=appliance_key,
                category=category,
                action=decision.action,
                defer_until=decision.defer_until,
            )
            return
        await notifications.async_create_alert_notification(
            self._coordinator.hass,
            alert,
            config=self._coordinator.circuit_registry.config_for_circuit(
                circuit_id
            ),
        )
        self._record_delivery(appliance_key, category, now)

    async def async_dismiss_alert_notification(self, alert_id: str) -> None:
        """Dismiss one managed alert notification by its evidence id."""
        await notifications.async_dismiss_persistent_notification(
            self._coordinator.hass,
            alert_id,
        )
        self._managed_alert_notification_ids.discard(alert_id)
        self.notified_alert_ids.discard(alert_id)

    async def async_dismiss_circuit_alert_notifications(
        self,
        circuit_id: str,
    ) -> None:
        """Dismiss retained and active alert notifications for one circuit."""
        alerts = list(getattr(self._coordinator.store_data, "alerts", ()))
        alerts.extend(
            getattr(
                self._coordinator.state,
                "active_alerts_by_circuit",
                {},
            ).get(circuit_id, ())
        )
        alert_ids = {
            notifications.notification_id_for_alert(alert)
            for alert in alerts
            if alert.circuit_id == circuit_id
        }
        for alert_id in sorted(alert_ids):
            await self.async_dismiss_alert_notification(alert_id)

    def _active_alert_ids(self) -> set[str]:
        state = getattr(self._coordinator, "state", None)
        return {
            notifications.notification_id_for_alert(alert)
            for alerts in getattr(state, "active_alerts_by_circuit", {}).values()
            for alert in alerts
        }

    async def async_dispatch_due(self, now: datetime) -> None:
        """Deliver deferred alerts whose local quiet window has ended."""
        state = self._delivery_state()
        pending = state.get("deferred", [])
        if not isinstance(pending, list):
            pending = []
        daily_queue = state.get("daily", [])
        if not pending and (not isinstance(daily_queue, list) or not daily_queue):
            return
        remaining: list[dict[str, Any]] = []
        alerts_by_id = {
            notifications.notification_id_for_alert(alert): alert
            for alert in getattr(self._coordinator.store_data, "alerts", ())
        }
        active_alert_ids = self._active_alert_ids()
        for item in pending:
            if not isinstance(item, dict):
                continue
            due = _datetime_or_none(item.get("defer_until"))
            alert_id = str(item.get("alert_id") or "")
            alert = alerts_by_id.get(alert_id)
            if due is None or alert is None or due > now:
                remaining.append(item)
                continue
            if (
                (
                    alert_id not in active_alert_ids
                    and not self._is_lifecycle_alert(alert)
                )
                or not self.learning_allows_alert(alert)
            ):
                continue
            await notifications.async_create_alert_notification(
                self._coordinator.hass,
                alert,
                config=self._coordinator.circuit_registry.config_for_circuit(
                    alert.circuit_id
                ),
            )
            if not self._is_lifecycle_alert(alert):
                self._managed_alert_notification_ids.add(alert_id)
            self._record_delivery(
                str(item.get("appliance_key") or f"circuit:{alert.circuit_id}"),
                str(item.get("category") or "unusual_runtime"),
                now,
            )
        if remaining != pending:
            state["deferred"] = remaining
            self._mark_store_dirty()
        await self._async_dispatch_daily_summary(now, alerts_by_id)

    async def async_refresh_weekly_digest(self, now: datetime) -> None:
        """Build at most one opt-in digest per local week."""
        settings = getattr(
            self._coordinator.store_data,
            "weekly_digest_settings",
            {},
        )
        state = self._delivery_state()
        weekly_queue = state.get("weekly", [])
        if not isinstance(settings, dict):
            settings = {}
            self._coordinator.store_data.weekly_digest_settings = settings
        configured_zone = str(
            getattr(getattr(self._coordinator.hass, "config", None), "time_zone", "UTC")
            or "UTC"
        )
        try:
            time_zone = ZoneInfo(configured_zone)
        except (KeyError, ValueError):
            time_zone = ZoneInfo("UTC")
        _, week_end = completed_week_bounds(now, time_zone)
        due_weekly: list[dict[str, Any]] = []
        pending_weekly: list[dict[str, Any]] = []
        blocked_weekly = False
        alerts_by_id = {
            notifications.notification_id_for_alert(alert): alert
            for alert in getattr(self._coordinator.store_data, "alerts", ())
        }
        for item in weekly_queue if isinstance(weekly_queue, list) else ():
            if not isinstance(item, dict):
                continue
            queued_at = _datetime_or_none(item.get("queued_at"))
            if (
                queued_at is not None
                and self._local_time(queued_at).date() <= week_end
            ):
                alert = alerts_by_id.get(str(item.get("alert_id") or ""))
                if alert is None or not self.learning_allows_alert(alert):
                    blocked_weekly = True
                    continue
                due_weekly.append(item)
            else:
                pending_weekly.append(item)
        has_due_weekly = bool(due_weekly)
        if settings.get("enabled") is not True and not has_due_weekly:
            if blocked_weekly:
                state["weekly"] = pending_weekly
                self._mark_store_dirty()
            return
        digest_items = digest_items_for_coordinator(
            self._coordinator,
            now=now,
            time_zone=time_zone,
        )
        digest = build_weekly_digest(
            _items_with_weekly_queue(digest_items, due_weekly),
            now=now,
            time_zone=time_zone,
        )
        digest_key = digest_idempotence_key(digest)
        if state.get("last_weekly_digest_key") == digest_key and not has_due_weekly:
            return
        state["last_weekly_digest_key"] = digest_key
        settings["latest_report"] = digest.as_dict()
        delivery = str(settings.get("delivery") or "panel_only")
        if delivery == "persistent_notification":
            await notifications.async_create_weekly_digest_notification(
                self._coordinator.hass,
                digest,
            )
        elif delivery == "mobile_notification":
            await self._async_send_mobile_digest(digest, settings)
        if has_due_weekly or blocked_weekly:
            state["weekly"] = pending_weekly
        self._mark_store_dirty()

    async def _async_dispatch_daily_summary(
        self,
        now: datetime,
        alerts_by_id: dict[str, AlertEvidence],
    ) -> None:
        state = self._delivery_state()
        queue = state.get("daily", [])
        if not isinstance(queue, list) or not queue:
            return
        local_now = self._local_time(now)
        ready: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for item in queue:
            queued_at = (
                _datetime_or_none(item.get("queued_at"))
                if isinstance(item, dict)
                else None
            )
            if (
                queued_at is not None
                and self._local_time(queued_at).date() < local_now.date()
            ):
                ready.append(item)
            elif isinstance(item, dict):
                pending.append(item)
        alerts_by_ready_id = {
            alert_id: alerts_by_id[alert_id]
            for item in ready
            if (alert_id := str(item.get("alert_id") or "")) in alerts_by_id
            and self.learning_allows_alert(alerts_by_id[alert_id])
        }
        alerts = list(alerts_by_ready_id.values())
        if alerts:
            await notifications.async_create_daily_summary_notification(
                self._coordinator.hass,
                alerts,
                summary_date=(local_now.date() - timedelta(days=1)).isoformat(),
            )
            state["last_daily_summary_date"] = local_now.date().isoformat()
        if pending != queue:
            state["daily"] = pending
            self._mark_store_dirty()

    async def async_notify_nilm_virtual_appliances(
        self,
        now: Any,
    ) -> list[AlertEvidence]:
        """Create notifications for published NILM virtual appliance alerts."""
        active_alerts: list[AlertEvidence] = []
        for alert in nilm_virtual_appliance_alerts(self._coordinator, now=now):
            if not self.learning_allows_alert(alert):
                continue
            alert = self._coordinator.evidence_actions.alert_with_feedback(alert)
            alert_id = notifications.notification_id_for_alert(alert)
            if alert.feedback_status != "expected":
                active_alerts.append(alert)
            if alert_id in self.notified_alert_ids:
                continue
            if not any(
                notifications.notification_id_for_alert(stored_alert) == alert_id
                for stored_alert in self._coordinator.store_data.alerts
            ):
                self._coordinator.store_data.alerts.append(alert)
                self._coordinator.store_persistence.mark_dirty()
            await self.async_notify_alert(alert)
        return active_alerts

    async def async_notify_finished_events(
        self,
        events: list[CircuitEvent],
        now: datetime,
    ) -> list[AlertEvidence]:
        """Notify opted-in direct appliances when a retained run stops."""
        alerts: list[AlertEvidence] = []
        for event in events:
            if event.event_type is not EventType.STOP:
                continue
            if str(event.features.get("transition_reason") or "") == (
                "source_data_unavailable"
            ):
                continue
            alert = AlertEvidence(
                timestamp=event.timestamp,
                circuit_id=event.circuit_id,
                severity=Severity.INFO,
                message=(
                    f"{event.circuit_id.replace('_', ' ').title()} finished running."
                ),
                event_type=event.event_type,
                feature="finished_running",
                features={
                    "source_type": "direct_meter",
                    "appliance_key": f"circuit:{event.circuit_id}",
                    "notification_type": "finished_running",
                    "notification_key": event.timestamp.isoformat(),
                    "evaluated_at": now.isoformat(),
                },
            )
            if not self.learning_allows_alert(alert):
                continue
            decision, _, _ = self._delivery_decision(alert)
            if decision.action == "suppress":
                continue
            self._coordinator.store_data.alerts.append(alert)
            self._mark_store_dirty()
            alerts.append(alert)
            await self.async_notify_alert(alert)
        return alerts

    async def async_notify_settings_recommendations_if_needed(self) -> None:
        """Notify again only when the pending set gains a new recommendation."""
        counts = self._coordinator.state.settings_recommendation_count_by_circuit
        total_pending = sum(
            count
            for circuit_id, count in counts.items()
            if not self._circuit_is_learning(circuit_id)
        )
        if total_pending <= 0:
            await notifications.async_dismiss_persistent_notification(
                self._coordinator.hass,
                notifications.settings_recommendation_notification_id(
                    self._coordinator.entry_id
                ),
            )
            if sum(counts.values()) <= 0:
                self.set_settings_recommendation_notification_episode_key(())
            return

        episode_key = self.settings_recommendation_episode_key()
        if episode_key == self.settings_recommendation_notification_episode_key:
            return
        recommendation_ids = _recommendation_ids(episode_key)
        notified_ids = _recommendation_ids(
            self.settings_recommendation_notification_episode_key
        )
        if (
            recommendation_ids is not None
            and notified_ids is not None
            and recommendation_ids <= notified_ids
        ):
            return

        self.set_settings_recommendation_notification_episode_key(episode_key)
        await notifications.async_create_settings_recommendation_notification(
            self._coordinator.hass,
            self._coordinator.entry_id,
            total_pending=total_pending,
        )
        self._coordinator.store_persistence.mark_dirty()
        await self._coordinator.store_persistence.async_save_if_dirty(
            self._coordinator.current_time()
        )

    def settings_recommendation_episode_key(
        self,
    ) -> tuple[tuple[str, ...], ...]:
        """Return the duplicate-suppression key for pending recommendations."""
        parts: list[tuple[str, ...]] = []
        pending_recommendations = (
            self._coordinator.settings_controller.pending_settings_recommendations
        )
        for recommendation in pending_recommendations(self._coordinator.current_time()):
            if self._circuit_is_learning(recommendation.circuit_id):
                continue
            parts.append((str(recommendation.recommendation_id),))
        return self._compact_settings_recommendation_episode_key(tuple(sorted(parts)))

    def set_settings_recommendation_notification_episode_key(
        self,
        episode_key: tuple[tuple[str, ...], ...],
    ) -> None:
        """Persist the latest settings recommendation notification episode key."""
        if episode_key == self.settings_recommendation_notification_episode_key:
            return
        self.settings_recommendation_notification_episode_key = episode_key
        store_data = self._coordinator.store_data
        store_data.settings_recommendation_notification_episode_key = episode_key
        self._coordinator.store_persistence.mark_dirty()

    def _stored_settings_recommendation_episode_key(
        self,
    ) -> tuple[tuple[str, ...], ...]:
        store_data = self._coordinator.store_data
        return self._compact_settings_recommendation_episode_key(
            tuple(
                tuple(str(item) for item in part)
                for part in (
                    store_data.settings_recommendation_notification_episode_key
                )
            )
        )

    def _delivery_decision(self, alert: AlertEvidence) -> tuple[Any, str, str]:
        features = dict(alert.features)
        appliance_key = str(
            features.get("appliance_key") or f"circuit:{alert.circuit_id}"
        )
        notification_type = str(features.get("notification_type") or "")
        category = (
            "lifecycle_update"
            if notification_type == "lifecycle_update"
            else (
                "finished_running"
                if "finished" in notification_type or "finished" in alert.feature
                else alert_notification_category(alert.feature)
            )
        )
        preferences_by_appliance = getattr(
            self._coordinator.store_data,
            "appliance_notification_preferences",
            {},
        )
        raw = (
            preferences_by_appliance.get(appliance_key, {})
            if isinstance(preferences_by_appliance, dict)
            else {}
        )
        source_type = str(features.get("source_type") or "direct_meter")
        if (
            not raw
            and category == "finished_running"
            and source_type == "nilm_estimate"
        ):
            raw = {"finished_running": True}
        preferences = preferences_from_dict(raw, appliance_key=appliance_key)
        now = self._local_time(self._current_time(alert.timestamp))
        cooldowns = self._delivery_state().get("cooldowns", {})
        last_sent = (
            _datetime_or_none(cooldowns.get(f"{appliance_key}|{category}"))
            if isinstance(cooldowns, dict)
            else None
        )
        confidence = _float_or_none(features.get("confidence"))
        decision = decide_notification_delivery(
            preferences,
            category=category,
            now=now,
            source_type=source_type,
            confidence=confidence,
            last_sent_at=last_sent,
        )
        if str(getattr(alert.severity, "value", alert.severity)) == "error":
            decision = type(decision)("send", "critical")
        return decision, appliance_key, category

    def _delivery_state(self) -> dict[str, Any]:
        store_data = self._coordinator.store_data
        state = getattr(store_data, "notification_delivery_state", None)
        if not isinstance(state, dict):
            state = {}
            store_data.notification_delivery_state = state
        return state

    def _remember_lifecycle_episode(
        self,
        circuit_id: str,
        feature: str,
        episode_key: str,
    ) -> bool:
        state = self._delivery_state()
        episodes = state.setdefault("lifecycle_episodes", [])
        if not isinstance(episodes, list):
            episodes = []
            state["lifecycle_episodes"] = episodes
        stored_key = f"{circuit_id}|{episode_key}"
        if stored_key in episodes:
            return False
        if feature == "learning_completed":
            prefix = f"{circuit_id}|learning_completed:"
            episodes[:] = [
                item
                for item in episodes
                if not str(item).startswith(prefix)
            ]
        episodes.append(stored_key)
        del episodes[:-100]
        return True

    @staticmethod
    def _is_lifecycle_alert(alert: AlertEvidence) -> bool:
        return alert.features.get("notification_type") == "lifecycle_update"

    def _lifecycle_message(self, circuit_id: str, feature: str) -> str:
        registry = getattr(self._coordinator, "circuit_registry", None)
        config_for_circuit = getattr(registry, "config_for_circuit", None)
        config = (
            config_for_circuit(circuit_id)
            if callable(config_for_circuit)
            else None
        )
        display_name = str(getattr(config, "name", "") or circuit_id)
        return _LIFECYCLE_MESSAGES[feature].format(
            appliance=display_name
        )

    def _queue_notification(
        self,
        *,
        alert_id: str,
        appliance_key: str,
        category: str,
        action: str,
        defer_until: datetime | None,
    ) -> None:
        state = self._delivery_state()
        queue_key = {
            "defer": "deferred",
            "queue_daily": "daily",
            "queue_weekly": "weekly",
        }[action]
        queue = state.setdefault(queue_key, [])
        if not isinstance(queue, list):
            queue = []
            state[queue_key] = queue
        queue.append(
            {
                "alert_id": alert_id,
                "appliance_key": appliance_key,
                "category": category,
                "queued_at": self._current_time().isoformat(),
                "defer_until": defer_until.isoformat() if defer_until else None,
            }
        )
        del queue[:-100]
        self._mark_store_dirty()

    def _record_delivery(
        self,
        appliance_key: str,
        category: str,
        now: datetime,
    ) -> None:
        state = self._delivery_state()
        cooldowns = state.setdefault("cooldowns", {})
        if not isinstance(cooldowns, dict):
            cooldowns = {}
            state["cooldowns"] = cooldowns
        cooldowns[f"{appliance_key}|{category}"] = now.isoformat()
        if len(cooldowns) > 100:
            oldest = next(iter(cooldowns))
            cooldowns.pop(oldest, None)
        self._mark_store_dirty()

    def _mark_store_dirty(self) -> None:
        persistence = getattr(self._coordinator, "store_persistence", None)
        mark_dirty = getattr(persistence, "mark_dirty", None)
        if callable(mark_dirty):
            mark_dirty()

    async def _async_send_mobile_digest(
        self,
        digest: Any,
        settings: dict[str, Any],
    ) -> None:
        service = str(settings.get("notify_service") or "").strip()
        if not service.startswith("notify."):
            return
        services = getattr(self._coordinator.hass, "services", None)
        call = getattr(services, "async_call", None)
        if not callable(call):
            return
        counts = [
            (len(digest.biggest_changes), "meaningful changes"),
            (len(digest.top_energy_users), "top energy users"),
            (len(digest.observed_alerts), "observed alerts"),
            (len(digest.unresolved_items), "unresolved items"),
            (len(digest.nilm_review_items), "NILM review items"),
            (len(digest.load_shift_opportunities), "load-shifting opportunities"),
        ]
        message = "; ".join(
            f"{count} {label}" for count, label in counts if count
        )
        await call(
            "notify",
            service.split(".", 1)[1],
            {
                "title": "Weekly Appliance Digest",
                "message": f"{message}." if message else "No digest items.",
            },
        )

    def _current_time(self, fallback: datetime | None = None) -> datetime:
        clock = getattr(self._coordinator, "current_time", None)
        if callable(clock):
            return clock()
        return fallback or datetime.now().astimezone()

    def _local_time(self, value: datetime) -> datetime:
        configured_zone = str(
            getattr(
                getattr(self._coordinator.hass, "config", None),
                "time_zone",
                "UTC",
            )
            or "UTC"
        )
        try:
            return value.astimezone(ZoneInfo(configured_zone))
        except (KeyError, ValueError):
            return value.astimezone(ZoneInfo("UTC"))


def _recommendation_ids(
    episode_key: tuple[tuple[str, ...], ...],
) -> set[str] | None:
    """Return recommendation IDs when the stored key is not compacted."""
    if episode_key and episode_key[0][:1] == ("version",):
        return None
    return {part[0] for part in episode_key if part}


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _items_with_weekly_queue(
    items: list[dict[str, Any]],
    queued_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark queued appliance findings in the completed-week digest inputs."""
    combined = [dict(item) for item in items]
    by_key = {
        str(item.get("appliance_key") or ""): item
        for item in combined
        if item.get("appliance_key")
    }
    for queued in queued_items:
        appliance_key = str(queued.get("appliance_key") or "").strip()
        if not appliance_key:
            continue
        category = str(queued.get("category") or "")
        status = "nilm_review_needed" if category.startswith("nilm") else "observed"
        item = by_key.get(appliance_key)
        if item is not None:
            if str(item.get("status") or "normal") == "normal":
                item["status"] = status
            continue
        item = {
            "appliance_key": appliance_key,
            "display_name": appliance_key.split(":", 1)[-1].replace("_", " ").title(),
            "energy_kwh": 0.0,
            "normal_energy_kwh": 0.0,
            "confidence": 1.0,
            "status": status,
        }
        combined.append(item)
        by_key[appliance_key] = item
    return combined
