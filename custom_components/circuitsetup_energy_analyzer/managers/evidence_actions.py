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
    alert_feedback_fingerprint_for_observation,
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
        del duration
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
        coordinator.store_data.maintenance_by_circuit[circuit_id] = payload
        coordinator.paused_circuits.add(circuit_id)
        coordinator.store_persistence.mark_dirty()
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
        should_relearn = bool(relearn or current.get("relearn_on_end"))
        current.update({"active": False, "ended_at": now.isoformat()})
        coordinator.store_data.maintenance_by_circuit[circuit_id] = current
        coordinator.paused_circuits.discard(circuit_id)
        coordinator.store_persistence.mark_dirty()
        if should_relearn:
            await coordinator.async_relearn_baseline(circuit_id)
            return
        coordinator.refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

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
        existing = coordinator.store_data.alert_feedback.get(fingerprint, {})
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
        coordinator._apply_nilm_alert_feedback(alert, action, now)
        self.retire_alert_id(alert_id)
        coordinator.refresh_all_ux_state(now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        return True

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
        candidates = (
            alert_feedback_fingerprint_for_observation(
                observation,
                config=coordinator.circuit_registry.config_for_circuit(
                    observation.circuit_id
                ),
            ),
            alert_feedback_fingerprint_for_observation(observation),
            _legacy_alert_feedback_key_for_observation(observation),
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
        candidates = (
            _alert_feedback_key(
                alert,
                config=coordinator.circuit_registry.config_for_circuit(
                    alert.circuit_id
                ),
            ),
            _alert_feedback_key(alert),
            _legacy_alert_feedback_key(alert),
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


def _alert_feedback_key(
    alert: AlertEvidence,
    *,
    config: Any = None,
) -> str:
    return alert_feedback_fingerprint(alert, config=config)


def _legacy_alert_feedback_key(alert: AlertEvidence) -> str:
    return f"{alert.circuit_id}:{_alert_feature(alert)}"


def _legacy_alert_feedback_key_for_observation(observation: Observation) -> str:
    return f"{observation.circuit_id}:{observation.feature or 'alert'}"


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


def _positive_int_value(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
