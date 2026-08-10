"""NILM known-load topology processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..alerting import Observation
from ..models import CircuitConfig, CircuitMode
from ..nilm import (
    KnownLoadMatch,
    _nilm_edge_id,
    evaluate_known_load_topology,
    expected_known_load_dominant_legs,
    known_load_topology_for_config,
    observed_known_load_leg,
)
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE = 0.5


type KnownConfigProvider = Callable[[str], CircuitConfig | None]
type TopologyAlertPolicyProvider = Callable[[str], AlertPolicy]


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

        if match.selection_method == "topology_rejected":
            evidence.update(
                {
                    "attribution_rejected": True,
                    "aggregate_edge_retained": True,
                    "rejection_reason": match.topology_status,
                }
            )

        match_confidence = float(evidence["match_confidence"])
        if (
            match.selection_method != "topology_rejected"
            and match_confidence < MIN_NILM_TOPOLOGY_MATCH_CONFIDENCE
        ):
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
    topology = known_load_topology_for_config(known_config)
    expected_types = topology.expected_split_phase_types
    observed_type = str(match.edge.split_phase_type or "unknown")
    configured_leg = topology.configured_leg
    observed_leg = observed_known_load_leg(match.edge)
    suggested_leg = (
        observed_leg if known_config.mode is CircuitMode.SINGLE_PHASE else None
    )
    status = match.topology_status or evaluate_known_load_topology(match.edge, topology)

    evidence = {
        "status": status,
        "matched_mains_circuit_id": mains_config.circuit_id,
        "event_type": "start" if match.edge.direction == "on" else "stop",
        "configured_mode": known_config.mode.value,
        "configured_leg": configured_leg,
        "expected_split_phase_types": list(expected_types),
        "expected_dominant_legs": list(expected_known_load_dominant_legs(topology)),
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
        "source_aggregate_delta_w": _round_number(match.edge.delta_w),
        "explained_delta_w": _round_number(match.explained_delta_w),
        "residual_delta_w": _round_number(match.residual_delta_w),
        "residual_emitted": match.residual_edge is not None,
        "residual_edge_id": (
            _nilm_edge_id(match.residual_edge) if match.residual_edge else None
        ),
        "match_time_offset_seconds": _round_optional_number(
            match.time_offset_seconds
        ),
        "magnitude_score": _round_optional_number(match.magnitude_score),
        "time_score": _round_optional_number(match.time_score),
        "topology_score": _round_optional_number(match.topology_score),
        "selection_method": match.selection_method,
        "known_power_source": match.power_source,
        "match_confidence": _round_number(match.confidence),
    }
    if match.selection_status is not None:
        evidence["selection_status"] = match.selection_status
    if match.known_power_source is not None:
        evidence["known_selected_power_source"] = match.known_power_source
    if match.known_transition_delta_w is not None:
        evidence["known_transition_delta_w"] = _round_number(
            match.known_transition_delta_w
        )
    if match.known_transition_spread_w is not None:
        evidence["known_transition_spread_w"] = _round_number(
            match.known_transition_spread_w
        )
    if match.power_match_confidence is not None:
        evidence["pre_topology_power_match_confidence"] = _round_number(
            match.power_match_confidence
        )
    if match.time_distance_seconds is not None:
        evidence["synchronized_time_distance_seconds"] = _round_number(
            match.time_distance_seconds
        )
    if match.time_offset_seconds is not None:
        evidence["synchronized_time_offset_seconds"] = _round_number(
            match.time_offset_seconds
        )
    if match.transition_timing_uncertainty_s is not None:
        evidence["transition_timing_uncertainty_s"] = _round_number(
            match.transition_timing_uncertainty_s
        )
    return evidence


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
    rejected = bool(evidence.get("attribution_rejected"))
    if evidence.get("status") == "leg_mismatch":
        configured_leg = evidence.get("configured_leg", "unknown")
        observed_leg = evidence.get("observed_leg", "unknown")
        observation = (
            "rejected a known-load attribution because it was observed"
            if rejected
            else "repeatedly matched it"
        )
        return (
            f"Possible issue: {config.name} is configured on leg "
            f"{configured_leg}, but mains NILM "
            f"{observation} on leg "
            f"{observed_leg}. Verify circuit mapping, CT orientation, and "
            "whether another appliance changed at the same time before "
            "treating this as an appliance problem."
        )

    observed_type = evidence.get("observed_split_phase_type", "unknown")
    expected = ", ".join(evidence.get("expected_split_phase_types") or [])
    observation = (
        "rejected a known-load attribution because it was observed"
        if rejected
        else "repeatedly matched it"
    )
    return (
        f"Possible issue: {config.name} is configured as "
        f"{_circuit_mode_phrase(config.mode)}, but mains NILM "
        f"{observation} as "
        f"{observed_type}. Expected {expected or 'no topology check'} from "
        "the configured circuit mode. Verify circuit mapping, CT orientation, "
        "and whether another appliance changed at the same time before treating "
        "this as an appliance problem."
    )


def _circuit_mode_phrase(mode: CircuitMode) -> str:
    return str(mode.value).replace("_", " ")


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
