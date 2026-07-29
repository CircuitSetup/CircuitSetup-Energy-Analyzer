"""Evidence, alert-feedback, and maintenance actions for the coordinator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from .. import notifications
from ..alert_feedback import (
    alert_feedback_is_expired,
    alert_feedback_status,
    mapping_datetime,
)
from ..alerting import (
    Observation,
    alert_anomaly_score,
    alert_feedback_fingerprint,
    alert_feedback_fingerprint_candidates,
    alert_feedback_fingerprint_candidates_for_observation,
)
from ..models import AlertEvidence

ALERT_EXPECTED_FEEDBACK_TTL = timedelta(days=90)
ALERT_UNHELPFUL_FEEDBACK_TTL = timedelta(days=45)
ALERT_UNHELPFUL_EXTRA_REPEATED = 2


class EvidenceActionController:
    """Own user-triggered evidence and alert lifecycle actions."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_pause_alerts(
        self,
        circuit_id: str,
        duration: str | None = None,
    ) -> None:
        """Pause alert notifications for a circuit."""
        if duration is not None:
            await self.async_start_maintenance(
                circuit_id,
                duration=duration,
                source="pause_alerts",
            )
            return
        coordinator = self._coordinator
        coordinator.paused_circuits.add(circuit_id)
        coordinator.refresh_ux_state_for_circuit(
            circuit_id,
            coordinator.current_time(),
        )
        coordinator.async_set_updated_data(coordinator.state)

    async def async_acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an active alert evidence item."""
        coordinator = self._coordinator
        if self.alert_for_id(alert_id) is None:
            return False
        await coordinator.notification_controller.async_dismiss_alert_notification(
            alert_id
        )
        self.retire_alert_id(alert_id)
        now = coordinator.current_time()
        coordinator.refresh_all_ux_state(now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        return True

    async def async_start_maintenance(
        self,
        circuit_id: str,
        note: str = "",
        duration: str | None = None,
        relearn_on_end: bool = False,
        source: str = "maintenance",
    ) -> None:
        """Mark one circuit in maintenance and pause appliance notifications."""
        coordinator = self._coordinator
        now = coordinator.current_time()
        payload: dict[str, Any] = {
            "active": True,
            "note": str(note),
            "started_at": now.isoformat(),
            "relearn_on_end": bool(relearn_on_end),
        }
        if duration is not None:
            payload["duration"] = str(duration)
            expires_at = _duration_expires_at(duration, now)
            if expires_at is not None:
                payload["expires_at"] = expires_at.isoformat()
        if source != "maintenance":
            payload["source"] = source
        coordinator.store_data.maintenance_by_circuit[circuit_id] = payload
        coordinator.paused_circuits.add(circuit_id)
        coordinator.store_persistence.mark_dirty()
        refresh_expiry = getattr(
            coordinator,
            "refresh_maintenance_expiry_listener",
            None,
        )
        if refresh_expiry is not None:
            refresh_expiry()
        coordinator.refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

    async def async_end_maintenance(
        self,
        circuit_id: str,
        relearn: bool = False,
    ) -> None:
        """Clear maintenance state and optionally relearn the circuit baseline."""
        coordinator = self._coordinator
        now = coordinator.current_time()
        current = dict(
            coordinator.store_data.maintenance_by_circuit.get(circuit_id, {}),
        )
        was_active = current.get("active") is True
        should_relearn = bool(relearn or (was_active and current.get("relearn_on_end")))
        current.update({"active": False, "ended_at": now.isoformat()})
        coordinator.store_data.maintenance_by_circuit[circuit_id] = current
        coordinator.paused_circuits.discard(circuit_id)
        coordinator.store_persistence.mark_dirty()
        if not should_relearn:
            coordinator.refresh_ux_state_for_circuit(circuit_id, now)
            coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        started_at = str(current.get("started_at") or now.isoformat())
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        display_name = str(
            getattr(config, "name", "") or circuit_id.replace("_", " ").title()
        )
        learning_epoch = None
        if should_relearn:
            await coordinator.async_relearn_baseline(circuit_id)
            learning_epoch = coordinator.store_data.learning_started_at_by_circuit.get(
                circuit_id,
                now.isoformat(),
            )
        if was_active:
            await coordinator.notification_controller.async_notify_lifecycle_update(
                circuit_id,
                feature="maintenance_completed",
                message=f"{display_name} maintenance ended.",
                episode_key=f"maintenance_completed:{started_at}",
                now=now,
            )
        if learning_epoch is not None:
            await coordinator.notification_controller.async_notify_lifecycle_update(
                circuit_id,
                feature="relearning_started",
                message=f"{display_name} started relearning its normal behavior.",
                episode_key=f"relearning_started:{learning_epoch}",
                now=now,
            )
        await coordinator.store_persistence.async_save_if_dirty(now)

    def alerts_paused(self, circuit_id: str, now: datetime | None = None) -> bool:
        """Return whether circuit alerts are currently paused."""
        del now
        return circuit_id in self._coordinator.paused_circuits

    async def async_expire_maintenance_if_due(
        self,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Complete every timed maintenance window whose expiry has passed."""
        coordinator = self._coordinator
        now = now or coordinator.current_time()
        expired: list[str] = []
        for circuit_id, raw in tuple(
            coordinator.store_data.maintenance_by_circuit.items()
        ):
            maintenance = dict(raw)
            expires_at = mapping_datetime(maintenance.get("expires_at"))
            if (
                maintenance.get("active") is True
                and expires_at is not None
                and expires_at <= _datetime_for_comparison(now, expires_at)
            ):
                await self.async_end_maintenance(circuit_id)
                expired.append(circuit_id)
        refresh_expiry = getattr(
            coordinator,
            "refresh_maintenance_expiry_listener",
            None,
        )
        if refresh_expiry is not None:
            refresh_expiry()
        return tuple(expired)

    def next_maintenance_expiry(self) -> datetime | None:
        """Return the earliest active timed-maintenance expiry."""
        expiries = [
            expires_at
            for raw in self._coordinator.store_data.maintenance_by_circuit.values()
            if isinstance(raw, Mapping)
            and raw.get("active") is True
            and (expires_at := mapping_datetime(raw.get("expires_at"))) is not None
        ]
        return min(expiries, default=None)

    async def async_mark_alert_expected(self, alert_id: str) -> bool:
        """Mark an alert pattern as expected for future notifications."""
        return await self.async_store_alert_feedback(alert_id, "expected")

    async def async_mark_alert_unhelpful(self, alert_id: str) -> bool:
        """Mark an alert pattern as unhelpful for future notifications."""
        return await self.async_store_alert_feedback(alert_id, "unhelpful")

    async def async_mark_nilm_appliance_correct(self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as correct."""
        return await self.async_store_alert_feedback(alert_id, "correct")

    async def async_mark_nilm_appliance_wrong(self, alert_id: str) -> bool:
        """Mark an estimated NILM appliance notification as the wrong appliance."""
        return await self.async_store_alert_feedback(
            alert_id,
            "wrong_appliance",
        )

    async def async_store_alert_feedback(self, alert_id: str, action: str) -> bool:
        """Store one alert-feedback decision and retire the visible alert."""
        coordinator = self._coordinator
        alert = self.alert_for_id(alert_id)
        if alert is None:
            return False
        now = coordinator.current_time()
        fingerprint = alert_feedback_fingerprint(
            alert,
            config=coordinator.circuit_registry.config_for_circuit(alert.circuit_id),
        )
        matched_fingerprint, existing = self.alert_feedback_for(alert)
        evidence_count = (
            _positive_int_value(existing.get("evidence_count"), default=0) + 1
        )
        expires_at = _alert_feedback_expires_at(action, now)
        coordinator.store_data.alert_feedback[fingerprint] = {
            "fingerprint": fingerprint,
            "status": action,
            "action": action,
            "source_alert_id": alert_id,
            "alert_id": alert_id,
            "decided_at": now.isoformat(),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "last_seen": now.isoformat(),
            "circuit_id": alert.circuit_id,
            "feature": _alert_feature(alert),
            "change_ratio": alert.change_ratio,
            "observed_value": alert.observed_value,
            "baseline_value": alert.baseline_value,
            "evidence_count": evidence_count,
        }
        if matched_fingerprint is not None and matched_fingerprint != fingerprint:
            coordinator.store_data.alert_feedback.pop(matched_fingerprint, None)
        coordinator.apply_nilm_alert_feedback(alert, action, now)
        self.apply_hvac_alert_feedback(alert, action, now)
        await coordinator.notification_controller.async_dismiss_alert_notification(
            alert_id
        )
        self.retire_alert_id(alert_id)
        coordinator.refresh_all_ux_state(now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        return True

    def apply_hvac_alert_feedback(
        self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        """Apply existing alert feedback to the affected HVAC baseline stream."""
        if alert.features.get("health_feature") != "hvac_thermostat_efficiency":
            return
        stream_id = str(alert.features.get("stream_id") or "")
        if not stream_id.startswith(f"{alert.circuit_id}|"):
            return
        store_data = self._coordinator.store_data
        if action in {"expected", "corrected", "improved"}:
            store_data.hvac_baseline_era_by_stream[stream_id] = now.isoformat()
            state = self._coordinator.state
            getattr(state, "hvac_current_episode_by_stream", {}).pop(
                stream_id,
                None,
            )
            getattr(state, "hvac_efficiency_by_circuit", {}).pop(
                alert.circuit_id,
                None,
            )
            return
        if action != "confirmed":
            return
        episode_ids = {
            str(episode_id)
            for episode_id in alert.features.get("recent_episode_ids", ())
            if episode_id
        }
        for episode in store_data.hvac_response_history_by_stream.get(
            stream_id,
            (),
        ):
            if str(episode.get("started_at") or "") in episode_ids:
                episode["excluded_from_baseline"] = True

    def adjusted_min_repeated_for_observation(
        self,
        observation: Observation,
        base_min_repeated: int,
    ) -> int:
        """Return adjusted repeated-evidence threshold after feedback."""
        _fingerprint, feedback = self.alert_feedback_for_observation(observation)
        if alert_feedback_status(feedback) != "unhelpful":
            return base_min_repeated
        return base_min_repeated + ALERT_UNHELPFUL_EXTRA_REPEATED

    def alert_feedback_for_observation(
        self,
        observation: Observation,
    ) -> tuple[str | None, Mapping[str, Any]]:
        """Return matching retained feedback for an observation."""
        coordinator = self._coordinator
        candidates = alert_feedback_fingerprint_candidates_for_observation(
            observation,
            config=coordinator.circuit_registry.config_for_circuit(
                observation.circuit_id
            ),
        )
        return self._first_current_feedback(candidates)

    def has_suppressed_alert_feedback(self, alert: AlertEvidence) -> bool:
        """Return whether feedback suppresses this alert pattern."""
        _fingerprint, feedback = self.alert_feedback_for(alert)
        return alert_feedback_status(feedback) == "expected"

    def alert_feedback_for(
        self,
        alert: AlertEvidence,
    ) -> tuple[str | None, Mapping[str, Any]]:
        """Return matching retained feedback for an alert."""
        coordinator = self._coordinator
        candidates = alert_feedback_fingerprint_candidates(
            alert,
            config=coordinator.circuit_registry.config_for_circuit(
                alert.circuit_id
            ),
        )
        return self._first_current_feedback(candidates)

    def alert_with_feedback(self, alert: AlertEvidence) -> AlertEvidence:
        """Return alert evidence annotated with matching feedback state."""
        fingerprint, feedback = self.alert_feedback_for(alert)
        status = alert_feedback_status(feedback)
        if fingerprint is None or status is None:
            return alert
        return replace(
            alert,
            feedback_status=status,
            feedback_effect=_alert_feedback_effect(status),
            feedback_expires_at=mapping_datetime(feedback.get("expires_at")),
            matching_feedback_fingerprint=fingerprint,
        )

    def _first_current_feedback(
        self,
        candidates: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, Any]]:
        now = self._coordinator.current_time()
        for fingerprint in candidates:
            feedback = self._coordinator.store_data.alert_feedback.get(fingerprint)
            if not isinstance(feedback, Mapping):
                continue
            if alert_feedback_is_expired(feedback, now):
                continue
            return fingerprint, feedback
        return None, {}

    def retire_alert_id(self, alert_id: str) -> None:
        """Remove an alert from stored and active evidence after user action."""
        coordinator = self._coordinator
        retired = self.alert_for_id(alert_id)
        coordinator.store_data.alerts = [
            alert
            for alert in coordinator.store_data.alerts
            if notifications.notification_id_for_alert(alert) != alert_id
        ]
        active_alerts_by_circuit = getattr(
            coordinator.state,
            "active_alerts_by_circuit",
            {},
        )
        coordinator.state.active_alerts_by_circuit = {
            circuit_id: [
                alert
                for alert in alerts
                if notifications.notification_id_for_alert(alert) != alert_id
            ]
            for circuit_id, alerts in active_alerts_by_circuit.items()
        }
        coordinator.state.active_alerts_by_circuit = {
            circuit_id: alerts
            for circuit_id, alerts in coordinator.state.active_alerts_by_circuit.items()
            if alerts
        }
        coordinator.state.anomaly_score_by_circuit = {
            circuit_id: max(alert_anomaly_score(alert) for alert in alerts)
            for circuit_id, alerts in coordinator.state.active_alerts_by_circuit.items()
        }
        if retired is not None:
            cached_evidence = getattr(
                coordinator.state,
                "alert_evidence_by_circuit",
                {},
            )
            cached = cached_evidence.get(retired.circuit_id)
            if not isinstance(cached, Mapping) or cached.get("alert_id") in {
                None,
                alert_id,
            }:
                cached_evidence.pop(retired.circuit_id, None)
        coordinator.store_persistence.mark_dirty()

    def alert_for_id(self, alert_id: str) -> AlertEvidence | None:
        """Return a stored or active alert by notification id."""
        alerts = list(self._coordinator.store_data.alerts)
        for active_alerts in getattr(
            self._coordinator.state,
            "active_alerts_by_circuit",
            {},
        ).values():
            alerts.extend(active_alerts)
        for alert in alerts:
            if notifications.notification_id_for_alert(alert) == alert_id:
                return alert
        return None


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _alert_feedback_effect(status: str) -> str:
    if status == "expected":
        return "Notifications suppressed for this expected pattern"
    if status == "unhelpful":
        return "Future matching alerts require stronger repeated evidence"
    return "Feedback recorded for this alert pattern"


def _alert_feedback_expires_at(action: str, now: datetime) -> datetime | None:
    if action == "expected":
        return now + ALERT_EXPECTED_FEEDBACK_TTL
    if action == "unhelpful":
        return now + ALERT_UNHELPFUL_FEEDBACK_TTL
    return None


def _duration_expires_at(duration: Any, now: datetime) -> datetime | None:
    delta = _duration_delta(duration)
    if delta is None or delta.total_seconds() <= 0:
        return None
    return now + delta


def _duration_delta(duration: Any) -> timedelta | None:
    if isinstance(duration, timedelta):
        return duration
    text = str(duration or "").strip()
    if not text:
        return None
    try:
        parts = [float(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0.0
        minutes, seconds = parts
    elif len(parts) == 1:
        hours = 0.0
        minutes = 0.0
        seconds = parts[0]
    else:
        return None
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _datetime_for_comparison(now: datetime, target: datetime) -> datetime:
    if now.tzinfo is None and target.tzinfo is not None:
        return now.replace(tzinfo=target.tzinfo)
    if now.tzinfo is not None and target.tzinfo is None:
        return now.replace(tzinfo=None)
    return now


def _positive_int_value(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
