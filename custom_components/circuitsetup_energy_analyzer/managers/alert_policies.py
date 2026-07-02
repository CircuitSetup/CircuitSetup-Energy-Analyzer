from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ..alerting import ConservativeAlertPolicy, Observation
from ..models import AlertEvidence


class FeedbackAwareAlertPolicy:
    """Apply persisted alert feedback before delegating to the scoring policy."""

    def __init__(
        self,
        manager: AlertPolicyManager,
        policy: ConservativeAlertPolicy,
    ) -> None:
        self._manager = manager
        self._policy = policy

    @property
    def min_repeated(self) -> int:
        return self._policy.min_repeated

    @property
    def min_total_score(self) -> float:
        return self._policy.min_total_score

    @property
    def min_average_score(self) -> float:
        return self._policy.min_average_score

    @property
    def min_baseline_confidence(self) -> float:
        return self._policy.min_baseline_confidence

    def observe(self, observation: Observation) -> AlertEvidence | None:
        min_repeated = self._manager.adjusted_min_repeated_for_observation(
            observation,
            self._policy.min_repeated,
        )
        alert = self._policy.observe(observation, min_repeated=min_repeated)
        if alert is None or min_repeated == self._policy.min_repeated:
            return alert
        return replace(alert, adjusted_min_repeated=min_repeated)


class AlertPolicyManager:
    """Provide feedback-aware alert policies for processors."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def feedback_aware_alert_policy(
        self,
        policy: ConservativeAlertPolicy,
    ) -> FeedbackAwareAlertPolicy:
        return FeedbackAwareAlertPolicy(self, policy)

    def adjusted_min_repeated_for_observation(
        self,
        observation: Observation,
        base_min_repeated: int,
    ) -> int:
        return self._coordinator.evidence_actions.adjusted_min_repeated_for_observation(
            observation,
            base_min_repeated,
        )

    def alert_policy_for_circuit(self, circuit_id: str) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.alert_policy_for_circuit(circuit_id)
        )

    def usage_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.usage_alert_policy_for_circuit(
                circuit_id
            )
        )

    def goal_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.goal_alert_policy_for_circuit(
                circuit_id
            )
        )

    def billing_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.billing_alert_policy_for_circuit(
                circuit_id
            )
        )

    def demand_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.demand_alert_policy_for_circuit(
                circuit_id
            )
        )

    def capacity_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.capacity_alert_policy_for_circuit(
                circuit_id
            )
        )

    def leg_imbalance_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.leg_imbalance_alert_policy_for_circuit(
                circuit_id
            )
        )

    def standby_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.standby_alert_policy_for_circuit(
                circuit_id
            )
        )

    def utility_comparison_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.utility_comparison_alert_policy_for_circuit(
                circuit_id
            )
        )

    def nilm_topology_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.nilm_topology_alert_policy_for_circuit(
                circuit_id
            )
        )

    def cycle_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.cycle_alert_policy_for_circuit(
                circuit_id
            )
        )

    def activity_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.activity_alert_policy_for_circuit(
                circuit_id
            )
        )

    def water_context_alert_policy_for_circuit(
        self,
        circuit_id: str,
        feature: str,
    ) -> FeedbackAwareAlertPolicy:
        return self.feedback_aware_alert_policy(
            self._coordinator.settings_controller.water_context_alert_policy_for_circuit(
                circuit_id,
                feature,
            )
        )

    def apply_nilm_alert_feedback(
        self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        self._coordinator.nilm_controller.apply_alert_feedback(alert, action, now)
