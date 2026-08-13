from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class EstimatedLoadIdentification:
    likely_type: str
    display_name: str
    review_label: str
    evidence_reason: str
    voltage_class: str
    typical_watts: float
    typical_var: float | None
    typical_va: float | None
    typical_power_factor: float | None
    reactive_ratio: float | None
    has_enough_evidence: bool


def identify_estimated_load(
    *,
    median_delta_w: Any,
    median_delta_var: Any = None,
    median_delta_va: Any = None,
    median_delta_pf: Any = None,
    split_phase_type: str = "unknown",
    occurrence_count: int = 0,
    confidence: float = 0.0,
    user_label: str | None = None,
) -> EstimatedLoadIdentification:
    typical_watts = _rounded_abs(median_delta_w) or 0.0
    typical_var = _rounded_abs(median_delta_var)
    typical_va = _rounded_abs(median_delta_va)
    pf_delta = _finite_float(median_delta_pf)
    typical_power_factor = _typical_power_factor(typical_watts, typical_va)
    voltage_class = _voltage_class(split_phase_type)
    has_enough_evidence = (
        occurrence_count >= MIN_OCCURRENCES and confidence >= MIN_CONFIDENCE
    )
    reactive_ratio = (
        typical_var / max(typical_watts, 1.0)
        if typical_var is not None
        else None
    )
    likely_type = (
        _likely_type(
            split_phase_type=split_phase_type,
            voltage_class=voltage_class,
            typical_watts=typical_watts,
            typical_var=typical_var,
            typical_va=typical_va,
            typical_power_factor=typical_power_factor,
            pf_delta=pf_delta,
            reactive_ratio=reactive_ratio,
        )
        if has_enough_evidence
        else "unknown"
    )
    return EstimatedLoadIdentification(
        likely_type=likely_type,
        display_name=_display_name(likely_type),
        review_label=user_label or _review_label(likely_type, voltage_class),
        evidence_reason=_evidence_reason(likely_type, has_enough_evidence),
        voltage_class=voltage_class,
        typical_watts=typical_watts,
        typical_var=typical_var,
        typical_va=typical_va,
        typical_power_factor=typical_power_factor,
        reactive_ratio=reactive_ratio,
        has_enough_evidence=has_enough_evidence,
    )


def _likely_type(
    *,
    split_phase_type: str,
    voltage_class: str,
    typical_watts: float,
    typical_var: float | None,
    typical_va: float | None,
    typical_power_factor: float | None,
    pf_delta: float | None,
    reactive_ratio: float | None,
) -> str:
    if typical_var is None or reactive_ratio is None:
        return "unknown"
    near_unity_pf = (
        typical_power_factor >= 0.95
        if typical_power_factor is not None
        else abs(pf_delta) <= 0.08
        if pf_delta is not None
        else False
    )
    looks_resistive = reactive_ratio <= 0.12 and near_unity_pf
    if (
        voltage_class == "240 V"
        and split_phase_type == "balanced_240v"
        and typical_watts >= 1000.0
        and looks_resistive
    ):
        return "heating_element_candidate"
    if typical_watts >= 200.0 and looks_resistive:
        return "resistive"
    if (
        voltage_class == "120 V"
        and split_phase_type in {"single_leg_a", "single_leg_b"}
        and typical_watts >= 150.0
        and reactive_ratio >= 0.25
        and (typical_power_factor is None or typical_power_factor <= 0.9)
    ):
        return "motor"
    if (
        typical_va is not None
        and typical_va >= 100.0
        and typical_var >= 75.0
        and reactive_ratio >= 0.75
    ):
        return "power_electronics"
    return "unknown"


def _display_name(likely_type: str) -> str:
    if likely_type == "heating_element_candidate":
        return "Estimated heating load"
    if likely_type == "resistive":
        return "Estimated resistive load"
    if likely_type == "motor":
        return "Estimated motor load"
    if likely_type == "power_electronics":
        return "Estimated electronics load"
    return "Estimated unknown load"


def _review_label(likely_type: str, voltage_class: str) -> str:
    if likely_type == "heating_element_candidate":
        return _split_phase_label(voltage_class, "heating load")
    if likely_type == "resistive":
        return _split_phase_label(voltage_class, "resistive load")
    if likely_type == "motor":
        return _split_phase_label(voltage_class, "motor load")
    if likely_type == "power_electronics":
        return _split_phase_label(voltage_class, "electronics load")
    return "unknown recurring load"


def _split_phase_label(voltage_class: str, label: str) -> str:
    if voltage_class == "240 V":
        return f"possible 240 V {label}"
    if voltage_class == "120 V":
        return f"possible 120 V {label}"
    return (
        f"possible {label}"
        if label != "electronics load"
        else "possible electronics load"
    )


def _evidence_reason(likely_type: str, has_enough_evidence: bool) -> str:
    if not has_enough_evidence:
        return (
            "Limited recurring evidence; keep this as unknown until more samples "
            "are observed."
        )
    if likely_type == "heating_element_candidate":
        return (
            "Possible heating load candidate: balanced 240 V, high W, low VAR, "
            "and PF near unity."
        )
    if likely_type == "resistive":
        return (
            "Possible resistive load: watts and VA are nearly the same, VAR is "
            "low, and PF is near unity."
        )
    if likely_type == "motor":
        return (
            "Possible motor load: single-leg 120 V, meaningful reactive power, "
            "and lower estimated PF."
        )
    if likely_type == "power_electronics":
        return (
            "Possible electronics load: VA and VAR are high versus real power "
            "without the single-leg motor pattern."
        )
    return "No conservative helper pattern matched; keep this as unknown."


def _voltage_class(split_phase_type: str) -> str:
    if split_phase_type == "balanced_240v":
        return "240 V"
    if split_phase_type in {"single_leg_a", "single_leg_b"}:
        return "120 V"
    if split_phase_type == "imbalanced_240v_or_mixed":
        return "mixed"
    return "unknown"


def _rounded_abs(value: Any) -> float | None:
    finite = _finite_float(value)
    return round(abs(finite), 3) if finite is not None else None


def _typical_power_factor(watts: float, va: float | None) -> float | None:
    if va is None or va <= 0:
        return None
    return round(min(1.0, abs(watts) / va), 3)


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if isfinite(candidate) else None
