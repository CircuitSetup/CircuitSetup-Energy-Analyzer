from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .nilm import NilmEdge, NilmSignature

MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.5


def estimate_unknown_load(signature: NilmSignature) -> dict[str, Any]:
    """Return a conservative user-facing estimate for an unknown NILM signature."""

    typical_watts = _rounded_abs(signature.median_delta_w)
    typical_var = _rounded_abs(signature.median_delta_var)
    typical_va = _rounded_abs(signature.median_delta_va)
    typical_power_factor = _typical_power_factor(typical_watts, typical_va)
    voltage_class = _voltage_class(signature.split_phase_type)
    likely_type = _likely_type(
        signature,
        typical_watts=typical_watts,
        typical_var=typical_var,
        typical_va=typical_va,
        typical_power_factor=typical_power_factor,
        voltage_class=voltage_class,
    )

    return {
        "signature_id": signature.signature_id,
        "display_name": _display_name(likely_type, voltage_class),
        "likely_type": likely_type,
        "voltage_class": voltage_class,
        "split_phase_type": signature.split_phase_type,
        "dominant_leg": signature.dominant_leg,
        "typical_watts": typical_watts,
        "typical_var": typical_var,
        "typical_va": typical_va,
        "typical_power_factor": typical_power_factor,
        "confidence": signature.confidence,
        "occurrence_count": signature.occurrence_count,
        "evidence": _evidence(
            signature,
            likely_type=likely_type,
            voltage_class=voltage_class,
            typical_watts=typical_watts,
            typical_var=typical_var,
            typical_va=typical_va,
            typical_power_factor=typical_power_factor,
        ),
    }


def build_unknown_load_inventory(
    *,
    circuit_id: str,
    signatures: Iterable[NilmSignature],
    edges: Iterable[NilmEdge],
    now: datetime,
    existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consolidated inventory of recurring unknown NILM loads."""

    signature_list = list(signatures)
    edge_list = sorted(edges, key=lambda edge: edge.timestamp)
    ambiguous_ids = _ambiguous_signature_ids(signature_list, edge_list)
    loads = [
        _unknown_load_payload(
            signature,
            edge_list,
            now=now,
            ambiguous=signature.signature_id in ambiguous_ids,
            existing_state=existing_state or {},
        )
        for signature in signature_list
    ]
    loads.sort(
        key=lambda load: (
            load["separation_status"] != "ambiguous",
            -float(load.get("estimated_energy_today_kwh", 0.0)),
            -float(load.get("confidence", 0.0)),
            str(load.get("signature_id", "")),
        )
    )
    active_count = sum(1 for load in loads if load["running_state"] == "probably_on")
    ambiguous_count = sum(
        1 for load in loads if load["separation_status"] == "ambiguous"
    )

    return {
        "circuit_id": circuit_id,
        "unknown_load_count": len(loads),
        "active_unknown_load_count": active_count,
        "ambiguous_unknown_load_count": ambiguous_count,
        "simultaneous_unknown_event_count": _simultaneous_unknown_event_count(
            edge_list
        ),
        "unknown_estimated_energy_today_kwh": _sum_loads(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_estimated_energy_7_days_kwh": _sum_loads(
            loads,
            "estimated_energy_7_days_kwh",
        ),
        "unknown_estimated_energy_30_days_kwh": _sum_loads(
            loads,
            "estimated_energy_30_days_kwh",
        ),
        "largest_unknown_load": _largest_load(loads, "typical_watts"),
        "highest_unknown_energy_load": _largest_load(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_loads": loads,
    }


def _unknown_load_payload(
    signature: NilmSignature,
    edges: list[NilmEdge],
    *,
    now: datetime,
    ambiguous: bool,
    existing_state: Mapping[str, Any],
) -> dict[str, Any]:
    estimate = estimate_unknown_load(signature)
    matching_edges = _matching_edges(signature, edges)
    first_seen = min((edge.timestamp for edge in matching_edges), default=None)
    last_seen = max((edge.timestamp for edge in matching_edges), default=None)
    runtime_minutes, running_state, last_start, last_stop = _runtime_state(
        matching_edges,
        now,
    )
    if ambiguous:
        runtime_minutes = 0.0
        running_state = "unknown"

    energy_today = _estimated_kwh(estimate["typical_watts"], runtime_minutes)
    existing_load = _existing_load_state(existing_state, signature.signature_id)
    review_state = str(existing_load.get("review_state") or "new")
    if review_state == "merged":
        review_state = "merged"

    return {
        **estimate,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "review_state": review_state,
        "separation_status": "ambiguous" if ambiguous else "separable",
        "running_state": running_state,
        "last_start": last_start.isoformat() if last_start else None,
        "last_stop": last_stop.isoformat() if last_stop else None,
        "current_runtime_minutes": runtime_minutes
        if running_state == "probably_on"
        else 0.0,
        "runtime_today_minutes": runtime_minutes,
        "runtime_7_days_minutes": runtime_minutes,
        "runtime_30_days_minutes": runtime_minutes,
        "estimated_energy_today_kwh": energy_today,
        "estimated_energy_7_days_kwh": energy_today,
        "estimated_energy_30_days_kwh": energy_today,
        "energy_estimate_confidence": 0.0
        if ambiguous
        else float(estimate["confidence"]),
    }


def _matching_edges(signature: NilmSignature, edges: list[NilmEdge]) -> list[NilmEdge]:
    target_watts = abs(float(signature.median_delta_w))
    target_var = abs(float(signature.median_delta_var))
    matches: list[NilmEdge] = []
    for edge in edges:
        watts_match = _within_tolerance(abs(edge.delta_w), target_watts, 0.2, 50.0)
        var_match = _within_tolerance(abs(edge.delta_var), target_var, 0.35, 75.0)
        topology_match = (
            signature.split_phase_type == "unknown"
            or edge.split_phase_type == "unknown"
            or signature.split_phase_type == edge.split_phase_type
        )
        if watts_match and var_match and topology_match:
            matches.append(edge)
    return matches


def _runtime_state(
    edges: list[NilmEdge],
    now: datetime,
) -> tuple[float, str, datetime | None, datetime | None]:
    running = False
    last_start: datetime | None = None
    last_stop: datetime | None = None
    runtime_minutes = 0.0

    for edge in edges:
        if edge.direction == "on" and not running:
            running = True
            last_start = edge.timestamp
            continue
        if edge.direction == "off" and running and last_start is not None:
            runtime_minutes += max(
                0.0,
                (edge.timestamp - last_start).total_seconds() / 60.0,
            )
            running = False
            last_stop = edge.timestamp

    if running and last_start is not None:
        runtime_minutes += max(0.0, (now - last_start).total_seconds() / 60.0)

    return (
        round(runtime_minutes, 3),
        "probably_on" if running else "probably_off",
        last_start,
        last_stop,
    )


def _ambiguous_signature_ids(
    signatures: list[NilmSignature],
    edges: list[NilmEdge],
) -> set[str]:
    simultaneous_timestamps = _simultaneous_timestamps(edges)
    if not simultaneous_timestamps:
        return set()

    ambiguous_ids: set[str] = set()
    for signature in signatures:
        if any(
            edge.timestamp in simultaneous_timestamps
            and _watts_topology_match(signature, edge)
            for edge in edges
        ):
            ambiguous_ids.add(signature.signature_id)
    return ambiguous_ids


def _watts_topology_match(signature: NilmSignature, edge: NilmEdge) -> bool:
    target_watts = abs(float(signature.median_delta_w))
    topology_match = (
        signature.split_phase_type == "unknown"
        or edge.split_phase_type == "unknown"
        or signature.split_phase_type == edge.split_phase_type
    )
    return (
        _within_tolerance(abs(edge.delta_w), target_watts, 0.2, 50.0)
        and topology_match
    )


def _simultaneous_timestamps(edges: list[NilmEdge]) -> set[datetime]:
    counts: dict[datetime, int] = {}
    for edge in edges:
        counts[edge.timestamp] = counts.get(edge.timestamp, 0) + 1
    return {timestamp for timestamp, count in counts.items() if count > 1}


def _simultaneous_unknown_event_count(edges: list[NilmEdge]) -> int:
    simultaneous = _simultaneous_timestamps(edges)
    return sum(1 for edge in edges if edge.timestamp in simultaneous)


def _estimated_kwh(watts: float, runtime_minutes: float) -> float:
    return round((float(watts) * float(runtime_minutes)) / 60000.0, 3)


def _sum_loads(loads: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(load.get(key, 0.0)) for load in loads), 3)


def _largest_load(loads: list[dict[str, Any]], key: str) -> str | None:
    if not loads:
        return None
    return str(max(loads, key=lambda load: float(load.get(key, 0.0)))["signature_id"])


def _existing_load_state(
    existing_state: Mapping[str, Any],
    signature_id: str,
) -> Mapping[str, Any]:
    loads = existing_state.get("unknown_loads") if existing_state else None
    if not isinstance(loads, list):
        return {}
    for load in loads:
        if isinstance(load, Mapping) and load.get("signature_id") == signature_id:
            return load
    return {}


def _within_tolerance(
    value: float,
    reference: float,
    ratio: float,
    floor: float,
) -> bool:
    return abs(value - reference) <= max(abs(reference) * ratio, floor)


def _likely_type(
    signature: NilmSignature,
    *,
    typical_watts: float,
    typical_var: float,
    typical_va: float,
    typical_power_factor: float,
    voltage_class: str,
) -> str:
    if not _has_enough_evidence(signature):
        return "unknown"

    reactive_ratio = typical_var / max(typical_watts, 1.0)
    if (
        voltage_class == "240 V"
        and signature.split_phase_type == "balanced_240v"
        and typical_watts >= 1000.0
        and reactive_ratio <= 0.12
        and typical_power_factor >= 0.95
    ):
        return "heating_element_candidate"

    if (
        voltage_class == "120 V"
        and signature.split_phase_type in {"single_leg_a", "single_leg_b"}
        and typical_watts >= 150.0
        and reactive_ratio >= 0.25
        and typical_power_factor <= 0.9
    ):
        return "motor"

    if typical_va >= 100.0 and typical_var >= 75.0 and reactive_ratio >= 0.75:
        return "power_electronics"

    return "unknown"


def _has_enough_evidence(signature: NilmSignature) -> bool:
    return (
        signature.occurrence_count >= MIN_OCCURRENCES
        and signature.confidence >= MIN_CONFIDENCE
    )


def _voltage_class(split_phase_type: str) -> str:
    if split_phase_type == "balanced_240v":
        return "240 V"
    if split_phase_type in {"single_leg_a", "single_leg_b"}:
        return "120 V"
    if split_phase_type == "imbalanced_240v_or_mixed":
        return "mixed"
    return "unknown"


def _display_name(likely_type: str, voltage_class: str) -> str:
    if likely_type == "heating_element_candidate":
        return "Estimated 240 V heating element candidate"
    if likely_type == "motor":
        voltage = "120 V" if voltage_class == "120 V" else "unknown-voltage"
        return f"Estimated possible {voltage} motor-like unknown load"
    if likely_type == "power_electronics":
        return "Estimated possible power-electronics unknown load"
    return "Estimated unknown load"


def _evidence(
    signature: NilmSignature,
    *,
    likely_type: str,
    voltage_class: str,
    typical_watts: float,
    typical_var: float,
    typical_va: float,
    typical_power_factor: float,
) -> list[str]:
    evidence = [
        (
            f"Estimated from {signature.occurrence_count} recurring unmatched events "
            f"with confidence {signature.confidence:.2f}."
        ),
        (
            "Split-phase evidence suggests "
            f"{_voltage_label(voltage_class)} topology "
            f"({signature.split_phase_type}, dominant leg {signature.dominant_leg})."
        ),
        (
            f"Typical median change is {typical_watts:.1f} W, "
            f"{typical_var:.1f} VAR, {typical_va:.1f} VA, "
            f"estimated PF {typical_power_factor:.3f}."
        ),
    ]

    if not _has_enough_evidence(signature):
        evidence.append(
            "Limited recurring evidence; keep this as unknown until more samples "
            "are observed."
        )
    elif likely_type == "heating_element_candidate":
        evidence.append(
            "Possible heating element candidate: balanced 240 V, high W, "
            "low VAR, and PF near unity."
        )
    elif likely_type == "motor":
        evidence.append(
            "Possible motor-like pattern: single-leg 120 V, meaningful "
            "reactive power, and lower estimated PF."
        )
    elif likely_type == "power_electronics":
        evidence.append(
            "Possible power-electronics pattern: VA and VAR are high versus "
            "real power without the single-leg motor pattern."
        )
    else:
        evidence.append("No conservative helper pattern matched; keep this as unknown.")

    return evidence


def _voltage_label(voltage_class: str) -> str:
    if voltage_class == "120 V":
        return "possible 120 V"
    if voltage_class == "240 V":
        return "possible 240 V"
    if voltage_class == "mixed":
        return "mixed"
    return "unknown-voltage"


def _typical_power_factor(typical_watts: float, typical_va: float) -> float:
    if typical_va <= 0.0:
        return 0.0
    return round(min(typical_watts / typical_va, 1.0), 3)


def _rounded_abs(value: float) -> float:
    return round(abs(float(value)), 3)
