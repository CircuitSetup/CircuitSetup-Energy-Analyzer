"""NILM known-load topology processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..alerting import Observation
from ..models import AlertEvidence, CircuitConfig, CircuitMode
from ..nilm import KnownLoadMatch
from .base import FeatureResult, ProcessingContext, StateUpdate

MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE = 0.5


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type KnownConfigProvider = Callable[[str], CircuitConfig | None]
type TopologyAlertPolicyProvider = Callable[[str], _AlertPolicy]


class NilmTopologyProcessor:
    """Track whether mains NILM matches agree with known-load circuit topology."""

    name = "nilm_topology"

    def __init__(
        self,
        *,
        known_config_for_circuit: KnownConfigProvider,
        alert_policy_for_circuit: TopologyAlertPolicyProvider,
    ) -> None:
        self._known_config_for_circuit = known_config_for_circuit
        self._alert_policy_for_circuit = alert_policy_for_circuit

    def process(
        self,
        mains_config: CircuitConfig,
        match: KnownLoadMatch,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return state updates and possible alerts for a known-load match."""
        del context
        known_config = self._known_config_for_circuit(match.known_circuit_id)
        if known_config is None:
            return FeatureResult()

        evidence = nilm_topology_evidence_payload(
            mains_config=mains_config,
            known_config=known_config,
            match=match,
        )
        if not evidence:
            return FeatureResult()

        if match.confidence < MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE:
            evidence["status"] = "low_confidence_match"
            evidence["minimum_match_confidence"] = (
                MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE
            )
        status = str(evidence["status"])
        circuit_id = known_config.circuit_id
        state_updates = [
            StateUpdate(("nilm_topology_status_by_circuit", circuit_id), status),
            StateUpdate(
                ("nilm_topology_evidence_by_circuit", circuit_id),
                evidence,
            ),
        ]
        if status not in {"topology_mismatch", "leg_mismatch"}:
            return FeatureResult(state_updates=state_updates)

        policy = self._alert_policy_for_circuit(circuit_id)
        alert = policy.observe(
            Observation(
                circuit_id=circuit_id,
                feature=nilm_topology_alert_feature(status),
                score=1.0,
                baseline_confidence=1.0,
                observed_at=match.edge.timestamp,
                observed_value=1.0,
                baseline_value=0.0,
                message=nilm_topology_mismatch_message(known_config, evidence),
                features={
                    "match_confidence": float(evidence["match_confidence"]),
                    "matched_delta_w": float(evidence["matched_delta_w"]),
                    "known_event_power_w": float(evidence["known_event_power_w"]),
                    "observed_leg_balance_ratio": float(
                        evidence.get("observed_leg_balance_ratio") or 0.0
                    ),
                },
            ),
        )
        alerts = [alert] if alert is not None else []
        return FeatureResult(
            alerts=alerts,
            notifications=list(alerts),
            state_updates=state_updates,
        )


def nilm_topology_evidence_payload(
    *,
    mains_config: CircuitConfig,
    known_config: CircuitConfig,
    match: KnownLoadMatch,
) -> dict[str, Any]:
    """Build state evidence for a known-load NILM topology match."""
    expected_types = _expected_nilm_split_phase_types(known_config)
    observed_type = str(match.edge.split_phase_type or "unknown")
    configured_leg = _configured_single_phase_leg(known_config)
    observed_leg = _observed_single_phase_leg(observed_type, match.edge.dominant_leg)
    suggested_leg = (
        observed_leg if known_config.mode is CircuitMode.SINGLE_PHASE else None
    )
    if not expected_types:
        status = "not_evaluated"
    elif observed_type in {"unknown", "missing_leg_data"}:
        status = "unknown_topology"
    elif observed_type in expected_types:
        status = "consistent"
    else:
        status = "topology_mismatch"
    if (
        status == "consistent"
        and configured_leg is not None
        and observed_leg is not None
        and configured_leg != observed_leg
    ):
        status = "leg_mismatch"

    return {
        "status": status,
        "matched_mains_circuit_id": mains_config.circuit_id,
        "event_type": "start" if match.edge.direction == "on" else "stop",
        "configured_mode": known_config.mode.value,
        "configured_leg": configured_leg,
        "expected_split_phase_types": list(expected_types),
        "expected_dominant_legs": list(
            _expected_nilm_dominant_legs(known_config, configured_leg)
        ),
        "observed_split_phase_type": observed_type,
        "observed_dominant_leg": match.edge.dominant_leg,
        "observed_leg": observed_leg,
        "suggested_leg": suggested_leg,
        "observed_leg_a_delta_w": _round_optional_number(match.edge.leg_a_delta_w),
        "observed_leg_b_delta_w": _round_optional_number(match.edge.leg_b_delta_w),
        "observed_leg_balance_ratio": _round_optional_number(
            match.edge.leg_balance_ratio
        ),
        "matched_delta_w": _round_number(match.edge.delta_w),
        "known_event_power_w": _round_number(match.known_power_w),
        "match_confidence": _round_number(match.confidence),
    }


def nilm_topology_alert_feature(status: str) -> str:
    """Return the alert feature name for a NILM topology status."""
    if status == "leg_mismatch":
        return "nilm_leg_mismatch"
    return "nilm_topology_mismatch"


def nilm_topology_mismatch_message(
    config: CircuitConfig,
    evidence: dict[str, Any],
) -> str:
    """Build the user-facing NILM topology mismatch message."""
    if evidence.get("status") == "leg_mismatch":
        configured_leg = evidence.get("configured_leg", "unknown")
        observed_leg = evidence.get("observed_leg", "unknown")
        return (
            f"Possible issue: {config.name} is configured on leg "
            f"{configured_leg}, but mains NILM repeatedly matched it on leg "
            f"{observed_leg}. Verify circuit mapping, CT orientation, and "
            "whether another appliance changed at the same time before "
            "treating this as an appliance problem."
        )

    observed_type = evidence.get("observed_split_phase_type", "unknown")
    expected = ", ".join(evidence.get("expected_split_phase_types") or [])
    return (
        f"Possible issue: {config.name} is configured as "
        f"{_circuit_mode_phrase(config.mode)}, but mains NILM repeatedly matched "
        f"it as {observed_type}. Expected {expected or 'no topology check'} from "
        "the configured circuit mode. Verify circuit mapping, CT orientation, "
        "and whether another appliance changed at the same time before treating "
        "this as an appliance problem."
    )


def _expected_nilm_split_phase_types(config: CircuitConfig) -> tuple[str, ...]:
    if config.mode is CircuitMode.SINGLE_PHASE:
        return ("single_leg_a", "single_leg_b")
    if config.mode is CircuitMode.DUAL_PHASE:
        return ("balanced_240v",)
    return ()


def _expected_nilm_dominant_legs(
    config: CircuitConfig,
    configured_leg: str | None,
) -> tuple[str, ...]:
    if config.mode is CircuitMode.SINGLE_PHASE:
        if configured_leg is not None:
            return (configured_leg,)
        return ("a", "b")
    if config.mode is CircuitMode.DUAL_PHASE:
        return ("balanced",)
    return ()


def _configured_single_phase_leg(config: CircuitConfig) -> str | None:
    if config.mode is not CircuitMode.SINGLE_PHASE:
        return None
    legs = {
        normalized
        for sensor in config.sensors
        if (normalized := _normalized_leg(sensor.leg)) is not None
    }
    if len(legs) == 1:
        return next(iter(legs))
    return None


def _observed_single_phase_leg(
    observed_type: str,
    dominant_leg: str,
) -> str | None:
    del dominant_leg
    if observed_type == "single_leg_a":
        return "a"
    if observed_type == "single_leg_b":
        return "b"
    return None


def _circuit_mode_phrase(mode: CircuitMode) -> str:
    return str(mode.value).replace("_", " ")


def _normalized_leg(leg: str | None) -> str | None:
    if leg is None:
        return None
    value = leg.strip().lower()
    if value in {"a", "left", "l1", "line1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "line2", "2"}:
        return "b"
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_number(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return round(parsed, 3)


def _round_optional_number(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return round(parsed, 3)
