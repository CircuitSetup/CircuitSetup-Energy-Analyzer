from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH, alert_evidence_path
from .appliance_detail_models import (
    ApplianceAlertSummary,
    ApplianceDetail,
    ApplianceExpectation,
    ComparisonMode,
    ExpectationStatus,
    MetricComparison,
    MetricStatus,
    SourceType,
)
from .baseline import build_baseline
from .cold_storage import COLD_STORAGE_SIGNATURE_FEATURE
from .local_time import as_ha_local, local_date, local_day_time
from .models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
)
from .nilm_virtual import (
    NILM_FINISHED_CONFIDENCE_THRESHOLD,
    NILM_REVIEW_MODEL_STATES,
    NilmVirtualApplianceState,
    nilm_virtual_appliance_states,
)
from .notifications import notification_id_for_alert
from .profiles import get_profile_definition
from .sensor import (
    activity_summary_value,
    electrical_health_attributes,
    energy_summary_value,
    health_summary_attributes,
    health_summary_value,
)
from .session_timeline import (
    direct_appliance_timeline,
    nilm_appliance_timeline,
)
from .water_correlations import MIN_COMPARABLE_WINDOWS

ComparisonBaseline = tuple[float | None, float | None, float | None, float | None, str]
ProfileExpectationRecipe = tuple[str, str, str, tuple[str, ...]]

_PROFILE_EXPECTATION_RECIPES: dict[ApplianceProfile, ProfileExpectationRecipe] = {
    ApplianceProfile.DISHWASHER: (
        "Dishwasher cycle check",
        "Dishwasher activity should stay within a bounded wash and dry cycle.",
        "Unexpected runtime can point to a paused cycle, water problem, or "
        "heating issue.",
        ("Check cycle completion, water flow, and the dishwasher filter.",),
    ),
    ApplianceProfile.THREE_D_PRINTER: (
        "3D printer session check",
        "3D printer sessions should show preheat and heater cycling, then "
        "return to idle.",
        "Unexpected power loss or extended heating can interrupt a print or "
        "waste energy.",
        (
            "Check print status, heater state, and whether the printer returned "
            "to idle.",
        ),
    ),
    ApplianceProfile.MINI_SPLIT: (
        "Mini-Split operation check",
        "Mini-Split power should modulate with outdoor temperature and demand.",
        "Low-load operation and brief defrost changes can be normal for an "
        "inverter heat pump.",
        (
            "Compare outdoor temperature, operating mode, and recent defrost "
            "behavior.",
        ),
    ),
    ApplianceProfile.WASHER: (
        "Washer cycle check",
        "Washer activity should stay within a bounded cycle duration.",
        "Washer cycles that do not end can waste energy or hide a stuck load.",
        ("Check whether the washer actually finished its cycle.",),
    ),
    ApplianceProfile.DRYER: (
        "Dryer cycle check",
        "Dryers should draw high power while active, then stop.",
        "Unexpected dryer behavior can indicate a stuck cycle or heating issue.",
        ("Check lint path, vent airflow, and whether the cycle ended.",),
    ),
    ApplianceProfile.WATER_HEATER: (
        "Water heating check",
        "Water heating should follow household hot-water use.",
        "Unexpected water-heater runtime can point to demand changes or leaks.",
        ("Check recent hot-water use and water-flow context.",),
    ),
    ApplianceProfile.OVEN: (
        "Oven heat check",
        "Ovens should show high heat draw only while cooking.",
        "Unexpected heat loads can raise demand and capacity risk.",
        ("Check whether the oven or electric heat was intentionally on.",),
    ),
    ApplianceProfile.MICROWAVE: (
        "Microwave run check",
        "Microwaves should show short high-power runs.",
        "Long or repeated microwave runs are usually usage context, not a fault.",
        ("Review recent kitchen activity.",),
    ),
    ApplianceProfile.POOL_PUMP: (
        "Pool pump schedule check",
        "Pool pumps should follow scheduled pump runtime.",
        "Schedule drift can add avoidable daily energy use.",
        ("Check the pump schedule and recent manual overrides.",),
    ),
    ApplianceProfile.EV_CHARGER: (
        "EV charging check",
        "EV chargers should stay within configured circuit capacity.",
        "Charging can dominate demand if it exceeds expected limits.",
        ("Check charger current limit and charging schedule.",),
    ),
    ApplianceProfile.SOLAR_INVERTER: (
        "Solar generation check",
        "Solar generation should align with daylight and source direction.",
        "Sign or daylight mismatches can indicate CT direction or source issues.",
        ("Check daylight context and solar CT direction.",),
    ),
    ApplianceProfile.MIXED: (
        "Mixed circuit check",
        "Mixed circuit behavior should be treated as grouped load context.",
        "Several appliances can change together on a mixed circuit.",
        ("Review the largest loads sharing this circuit.",),
    ),
    ApplianceProfile.MAINS_NILM: (
        "Whole-home NILM check",
        "Whole-home mains NILM should separate known load from unknown load.",
        "Mains estimates are context for review, not a direct appliance fault.",
        ("Review NILM signatures before acting on appliance-level guesses.",),
    ),
}


def appliance_detail_for_circuit(
    coordinator: Any,
    circuit_id: str,
) -> ApplianceDetail | None:
    """Build Appliance Detail for a configured direct/mixed/mains circuit."""
    config = _config_for_circuit(coordinator, circuit_id)
    if config is None:
        return None

    state = _coordinator_state(coordinator)
    source_type = _source_type_for_config(config)
    health_attrs = health_summary_attributes(state, config.circuit_id)
    electrical_attrs = electrical_health_attributes(state, config.circuit_id)
    active_alerts = _active_alert_summaries(
        state,
        config.circuit_id,
        config=config,
    )
    first_checks = _first_checks(electrical_attrs.get("what_to_check_first"))
    quality = _mapping_for_circuit(
        state,
        "data_quality_checklist_by_circuit",
        config.circuit_id,
    )
    if (
        electrical_attrs.get("metric_consistency_status") == "missing_metrics"
        and _metric_comparison_sources_complete(quality)
    ):
        first_checks = ()
    comparisons = metric_comparisons_for_circuit(coordinator, config, state)
    expectations = appliance_expectations_for_circuit(
        coordinator,
        config,
        state,
        comparisons=comparisons,
        source_type=source_type,
        evidence_path=_evidence_path(circuit_id=config.circuit_id),
    )
    converted_assignment = _converted_nilm_assignment(coordinator, circuit_id)
    return ApplianceDetail(
        circuit_id=config.circuit_id,
        display_name=str(
            (converted_assignment or {}).get("display_name") or config.name
        ),
        appliance_profile=config.appliance_profile.value,
        source_type=source_type,
        confidence=None,
        model_status=None,
        activity_state=activity_summary_value(state, config.circuit_id),
        health_state=health_summary_value(state, config.circuit_id),
        energy_state=energy_summary_value(state, config.circuit_id),
        current_power_w=_state_number(
            state,
            "latest_real_power_w_by_circuit",
            config.circuit_id,
        ),
        daily_energy_kwh=_state_number(
            state,
            "daily_energy_usage_by_circuit",
            config.circuit_id,
        ),
        runtime_today_seconds=_state_number(
            state,
            "run_cycle_runtime_seconds_by_circuit",
            config.circuit_id,
        ),
        run_count_today=_state_int(
            state,
            "run_cycle_count_by_circuit",
            config.circuit_id,
        ),
        cost_today=_estimated_cost_today(state, config.circuit_id),
        cost_today_status=_cost_today_status(state, config.circuit_id),
        average_kwh_per_day=_state_number(
            state,
            "average_kwh_per_day_by_circuit",
            config.circuit_id,
        ),
        average_cost_per_day=_state_number(
            state,
            "average_cost_per_day_by_circuit",
            config.circuit_id,
        ),
        today_vs_normal=comparisons,
        expectations=expectations,
        recent_timeline=_recent_timeline(state, config.circuit_id),
        active_alerts=active_alerts,
        next_step=str(health_attrs.get("next_step") or "") or None,
        what_to_check_first=first_checks,
        evidence_path=_evidence_path(circuit_id=config.circuit_id),
        appliance_health=health_attrs["appliance_health_evidence"] or None,
        hvac_efficiency=_hvac_efficiency_detail(state, config),
        water_flow_context=_water_flow_context_detail(state, config),
        source_quality=_direct_source_quality(config, state),
        learning_readiness=_learning_readiness(state, config.circuit_id, config),
        assignment_id=(
            str(converted_assignment.get("assignment_id") or "") or None
            if converted_assignment
            else None
        ),
        appliance_key=(
            str(converted_assignment.get("appliance_key") or "")
            or f"nilm:{converted_assignment.get('assignment_id')}"
            if converted_assignment
            else f"circuit:{config.circuit_id}"
        ),
        appliance_id=(
            str(converted_assignment.get("appliance_id") or "") or config.circuit_id
            if converted_assignment
            else config.circuit_id
        ),
        mains_circuit_id=(
            str(converted_assignment.get("mains_circuit_id") or "") or None
            if converted_assignment
            else config.circuit_id
            if source_type == "mains"
            else None
        ),
        session_timeline=direct_appliance_timeline(
            coordinator,
            config.circuit_id,
        ),
    )


def _converted_nilm_assignment(
    coordinator: Any,
    circuit_id: str,
) -> Mapping[str, Any] | None:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return None
    for assignments in assignments_by_circuit.values():
        for assignment in _iter_items(assignments):
            if (
                isinstance(assignment, Mapping)
                and assignment.get("conversion_state") == "direct_meter"
                and str(assignment.get("direct_circuit_id") or "") == circuit_id
            ):
                return assignment
    return None


def appliance_detail_for_assignment(
    coordinator: Any,
    assignment_id: str,
) -> ApplianceDetail | None:
    """Build Appliance Detail for a stored NILM appliance assignment."""
    requested_id = str(assignment_id or "").strip()
    if not requested_id:
        return None

    stored_assignment = _stored_nilm_assignment(coordinator, requested_id)
    if (
        stored_assignment is not None
        and stored_assignment.get("conversion_state") == "direct_meter"
    ):
        direct_circuit_id = str(
            stored_assignment.get("direct_circuit_id") or ""
        ).strip()
        if direct_circuit_id:
            return appliance_detail_for_circuit(coordinator, direct_circuit_id)

    for state in nilm_virtual_appliance_states(coordinator, published_only=False):
        if state.assignment_id != requested_id:
            continue
        return _nilm_detail(coordinator, state)
    return None


def _nilm_detail(
    coordinator: Any,
    state: NilmVirtualApplianceState,
) -> ApplianceDetail:
    analyzer_state = _coordinator_state(coordinator)
    evidence_path = _nilm_evidence_path(state)
    validation_ready = bool(
        state.validation_readiness and state.validation_readiness.get("ready")
    )
    review_needed = (
        state.confidence < NILM_FINISHED_CONFIDENCE_THRESHOLD
        or state.model_status in NILM_REVIEW_MODEL_STATES
        or not validation_ready
    )
    needs_history = (
        not validation_ready
        and state.confidence >= NILM_FINISHED_CONFIDENCE_THRESHOLD
        and state.model_status not in NILM_REVIEW_MODEL_STATES
    )
    comparisons = _nilm_metric_comparisons(coordinator, state)
    return ApplianceDetail(
        circuit_id=state.mains_circuit_id,
        display_name=state.display_name,
        appliance_profile=state.appliance_profile or "nilm_virtual",
        source_type="nilm_estimate",
        confidence=state.confidence,
        model_status=state.model_status,
        activity_state="Estimated Running" if state.is_running else "Idle",
        health_state="Needs validation" if review_needed else "Estimated",
        energy_state="Estimated",
        current_power_w=state.estimated_power_w,
        daily_energy_kwh=state.estimated_energy_kwh_today,
        runtime_today_seconds=state.runtime_today_seconds,
        run_count_today=state.run_count_today,
        cost_today=None,
        cost_today_status="unavailable",
        average_kwh_per_day=None,
        average_cost_per_day=None,
        today_vs_normal=comparisons,
        expectations=_nilm_expectations(
            state,
            review_needed=review_needed,
            evidence_path=evidence_path,
            comparisons=comparisons,
        ),
        recent_timeline=_nilm_session_timeline(state),
        active_alerts=_active_alert_summaries(
            analyzer_state,
            state.mains_circuit_id,
            config=None,
            assignment_id=state.assignment_id,
        ),
        next_step=(
            "Confirm more NILM sessions"
            if needs_history
            else "Review NILM assignment"
            if review_needed
            else "No action needed"
        ),
        what_to_check_first=(
            ("Confirm this appliance across more days before using comparisons.",)
            if needs_history
            else ("Validate this estimated appliance before relying on alerts.",)
            if review_needed
            else ("Review NILM confidence before acting on appliance alerts.",)
        ),
        evidence_path=evidence_path,
        source_quality={
            "status": "estimated",
            "label": "Estimated from mains",
            "available_source_count": 1 if state.mains_source else 0,
            "stale_source_count": 0,
            "missing_required_roles": [],
        },
        learning_readiness={
            "status": "needs_validation" if review_needed else "ready",
            "label": (
                "Not enough confirmed history"
                if needs_history
                else "Needs validation"
                if review_needed
                else "Ready"
            ),
        },
        assignment_id=state.assignment_id,
        mains_source=state.mains_source,
        appliance_key=state.appliance_key,
        appliance_id=state.appliance_id,
        mains_circuit_id=state.mains_circuit_id,
        current_session_duration_seconds=state.current_session_duration_seconds,
        current_session=_nilm_session_detail(state, state.current_session_id),
        last_matched_session=_nilm_session_detail(
            state,
            state.last_matched_session_id,
        ),
        session_timeline=nilm_appliance_timeline(
            state,
            (
                getattr(analyzer_state, "active_alerts_by_circuit", {}).get(
                    state.mains_circuit_id,
                    (),
                )
            ),
            maintenance=(
                getattr(
                    getattr(coordinator, "store_data", None),
                    "maintenance_by_circuit",
                    {},
                ).get(state.mains_circuit_id, {})
            ),
        ),
    )


def _nilm_metric_comparisons(
    coordinator: Any,
    state: NilmVirtualApplianceState,
) -> tuple[MetricComparison, ...]:
    readiness = state.validation_readiness or {}
    if not readiness.get("ready") or state.model_status not in {
        "published",
        "validated",
    }:
        return ()
    specs = (
        (
            "daily_energy_kwh",
            "Energy so far",
            "kWh",
            state.estimated_energy_kwh_today,
        ),
        (
            "runtime_today_seconds",
            "Runtime so far",
            "s",
            state.runtime_today_seconds,
        ),
        (
            "run_count_today",
            "Runs so far",
            "count",
            float(state.run_count_today),
        ),
    )
    comparisons: list[MetricComparison] = []
    for metric_id, label, unit, current in specs:
        baseline = _nilm_session_baseline(state, metric_id)
        comparison = _metric_comparison(
            metric_id=metric_id,
            label=label,
            unit=unit,
            current=current,
            baseline=baseline,
            comparison_mode=ComparisonMode.SAME_TIME_OF_DAY,
            as_of=state.reference_time,
            explanation="Validated assignment-specific NILM session history.",
        )
        if comparison is not None:
            comparisons.append(comparison)
    return tuple(comparisons)


def _nilm_session_baseline(
    state: NilmVirtualApplianceState,
    metric_id: str,
) -> ComparisonBaseline | None:
    if state.reference_time is None:
        return None
    current_local = as_ha_local(state.reference_time, state.time_zone)
    current_date = current_local.date()
    as_of_clock = current_local.time().replace(tzinfo=None)
    daily: dict[Any, dict[str, float]] = {}
    for session in state.sessions:
        session_id = str(session.get("session_id") or "").strip()
        if session_id not in state.confirmed_session_ids or not session.get("end"):
            continue
        start = _datetime_or_none(session.get("start"))
        end = _datetime_or_none(session.get("end"))
        if start is None or end is None:
            continue
        total_duration = max(
            (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds(),
            0.0,
        )
        session_energy = max(
            _number_or_none(session.get("estimated_energy_kwh")) or 0.0,
            0.0,
        )
        day = local_date(start, state.time_zone)
        final_day = local_date(end, state.time_zone)
        while day <= final_day and day < current_date:
            day_start = local_day_time(day, datetime.min.time(), state.time_zone)
            day_cutoff = local_day_time(day, as_of_clock, state.time_zone)
            overlap_start = max(start, day_start)
            overlap_end = min(end, day_cutoff)
            if overlap_end > overlap_start:
                values = daily.setdefault(day, _empty_nilm_daily_metrics())
                overlap_seconds = (
                    overlap_end.astimezone(UTC) - overlap_start.astimezone(UTC)
                ).total_seconds()
                values["runtime_today_seconds"] += overlap_seconds
                if total_duration > 0:
                    values["daily_energy_kwh"] += session_energy * (
                        overlap_seconds / total_duration
                    )
            if local_date(start, state.time_zone) == day and start < day_cutoff:
                daily.setdefault(day, _empty_nilm_daily_metrics())[
                    "run_count_today"
                ] += 1.0
            day += timedelta(days=1)
    samples = [values[metric_id] for values in daily.values() if metric_id in values]
    if len(samples) < 3:
        return None
    baseline = build_baseline(metric_id, samples)
    return (
        baseline.p10,
        baseline.p90,
        baseline.median,
        baseline.confidence,
        "validated_nilm_sessions",
    )


def _empty_nilm_daily_metrics() -> dict[str, float]:
    return {
        "daily_energy_kwh": 0.0,
        "runtime_today_seconds": 0.0,
        "run_count_today": 0.0,
    }


def _nilm_session_detail(
    state: NilmVirtualApplianceState,
    session_id: str | None,
) -> dict[str, Any] | None:
    if not session_id:
        return None
    for session in state.sessions:
        if str(session.get("session_id") or "") != session_id:
            continue
        duration = _number_or_none(session.get("duration_seconds"))
        if not session.get("end"):
            duration = state.current_session_duration_seconds
        return {
            "session_id": session_id,
            "signature_fingerprint": str(session.get("signature_fingerprint") or "")
            or None,
            "start": _iso_value(session.get("start")),
            "end": _iso_value(session.get("end")),
            "duration_seconds": duration,
            "estimated_energy_kwh": _number_or_none(
                session.get("estimated_energy_kwh")
            ),
            "confidence": _number_or_none(session.get("confidence")),
            "validation_result": _nilm_session_validation_result(
                state,
                session_id,
            ),
        }
    return None


def _stored_nilm_assignment(
    coordinator: Any,
    assignment_id: str,
) -> Mapping[str, Any] | None:
    store_data = getattr(coordinator, "store_data", None)
    assignments_by_circuit = getattr(
        store_data,
        "nilm_appliance_assignments_by_circuit",
        {},
    )
    if not isinstance(assignments_by_circuit, Mapping):
        return None
    for assignments in assignments_by_circuit.values():
        for assignment in _iter_items(assignments):
            if (
                isinstance(assignment, Mapping)
                and str(assignment.get("assignment_id") or "") == assignment_id
            ):
                return assignment
    return None


def _nilm_session_validation_result(
    state: NilmVirtualApplianceState,
    session_id: str,
) -> str | None:
    if session_id in state.confirmed_session_ids:
        return "confirmed"
    if session_id in state.rejected_session_ids:
        return "rejected"
    if session_id in state.adjusted_session_ids:
        return "adjusted"
    return None


def _nilm_session_timeline(
    state: NilmVirtualApplianceState,
) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    for session in reversed(state.sessions[-20:]):
        detail = _nilm_session_detail(
            state,
            str(session.get("session_id") or "") or None,
        )
        if detail is None:
            continue
        running = not detail.get("end")
        items.append(
            {
                **detail,
                "timestamp": detail.get("start"),
                "kind": "running" if running else "completed",
                "title": "Estimated run in progress" if running else "Estimated run",
                "detail": (
                    "Estimated from the assigned NILM signature on the mains source."
                ),
            }
        )
    return {"status": "activity", "items": items} if items else None


def metric_comparisons_for_circuit(
    coordinator: Any,
    config: CircuitConfig,
    state: Any,
) -> tuple[MetricComparison, ...]:
    """Return Today vs Normal comparisons from existing state and baselines."""
    specs = (
        (
            "daily_energy_kwh",
            "Energy today",
            "kWh",
            "daily_energy_usage_by_circuit",
            ("daily_energy_kwh", "daily_energy_usage_kwh"),
        ),
        (
            "runtime_today_seconds",
            "Runtime today",
            "s",
            "run_cycle_runtime_seconds_by_circuit",
            ("runtime_today_seconds", "run_cycle_runtime_seconds"),
        ),
        (
            "run_count_today",
            "Runs today",
            "count",
            "run_cycle_count_by_circuit",
            ("run_cycle_daily_start_count", "run_count_today"),
        ),
        (
            "current_power_w",
            "Current power",
            "W",
            "latest_real_power_w_by_circuit",
            ("real_power", "current_power_w"),
        ),
        (
            "cost_today",
            "Cost today",
            "currency",
            "",
            ("daily_energy_kwh", "daily_energy_usage_kwh"),
        ),
        (
            "current_demand_w",
            "Current demand",
            "W",
            "current_demand_w_by_circuit",
            ("current_demand_w",),
        ),
        (
            "demand_peak_w",
            "Demand peak",
            "W",
            "peak_demand_w_by_circuit",
            ("demand_peak_w", "peak_demand_w"),
        ),
        (
            "capacity_usage_percent",
            "Capacity usage",
            "%",
            "capacity_usage_by_circuit",
            ("capacity_usage_percent", "capacity_usage"),
        ),
        (
            "solar_covered_share_percent",
            "Solar-covered share",
            "%",
            "solar_flexible_load_coverage_percent_by_circuit",
            (
                "solar_covered_share_percent",
                "solar_flexible_load_coverage_percent",
            ),
        ),
    )
    comparisons: list[MetricComparison] = []
    for metric_id, label, unit, field, baseline_features in specs:
        if (
            metric_id == "capacity_usage_percent"
            and _mapping_status(
                state,
                "capacity_status_by_circuit",
                config.circuit_id,
            )
            == "unconfigured"
        ):
            continue
        if metric_id == "current_power_w":
            if config.mode is CircuitMode.MIXED:
                continue
            operating_status = _mapping_status(
                state,
                "run_cycle_status_by_circuit",
                config.circuit_id,
            )
            if operating_status == "running":
                comparison_mode = ComparisonMode.RUNNING_STATE
            elif operating_status in {"idle", "no_activity"}:
                comparison_mode = ComparisonMode.CURRENT_STATE
                baseline_features = ("standby_power_w",)
            else:
                comparison_mode = ComparisonMode.CURRENT_STATE
                baseline_features = ()
        else:
            comparison_mode = _comparison_mode(metric_id)
            if comparison_mode is ComparisonMode.SAME_TIME_OF_DAY:
                label = {
                    "daily_energy_kwh": "Energy so far",
                    "runtime_today_seconds": "Runtime so far",
                    "run_count_today": "Runs so far",
                    "cost_today": "Cost so far",
                    "demand_peak_w": "Demand peak so far",
                }.get(metric_id, label)
        evidence: Mapping[str, Any] = {}
        if metric_id == "daily_energy_kwh":
            evidence = _mapping_for_circuit(
                state,
                "energy_usage_evidence_by_circuit",
                config.circuit_id,
            )
            if evidence.get("comparison_mode") == ComparisonMode.SAME_TIME_OF_DAY:
                comparison_mode = ComparisonMode.SAME_TIME_OF_DAY
                label = "Energy so far"
        elif metric_id == "cost_today":
            evidence = _mapping_for_circuit(
                state,
                "cost_evidence_by_circuit",
                config.circuit_id,
            )
        elif metric_id in {"runtime_today_seconds", "run_count_today"}:
            evidence = _mapping_for_circuit(
                state,
                "run_cycle_evidence_by_circuit",
                config.circuit_id,
            )
            prefix = (
                "runtime_today" if metric_id == "runtime_today_seconds" else "run_count"
            )
            evidence = {
                **evidence,
                "projection_value": evidence.get(f"{prefix}_projection_value"),
                "projection_low": evidence.get(f"{prefix}_projection_low"),
                "projection_high": evidence.get(f"{prefix}_projection_high"),
                "projection_confidence": evidence.get(
                    f"{prefix}_projection_confidence"
                ),
            }
        elif metric_id == "demand_peak_w":
            evidence = _mapping_for_circuit(
                state,
                "demand_evidence_by_circuit",
                config.circuit_id,
            )
        elif metric_id == "capacity_usage_percent":
            evidence = _mapping_for_circuit(
                state,
                "capacity_evidence_by_circuit",
                config.circuit_id,
            )
        current = (
            _estimated_cost_today(state, config.circuit_id)
            if metric_id == "cost_today"
            else _state_number(state, field, config.circuit_id)
        )
        baseline = _comparison_baseline(
            coordinator,
            state,
            config.circuit_id,
            metric_id=metric_id,
            baseline_features=baseline_features,
        )
        full_period = (
            _stored_baseline(coordinator, config.circuit_id, baseline_features)
            if metric_id
            in {
                "daily_energy_kwh",
                "runtime_today_seconds",
                "run_count_today",
                "demand_peak_w",
            }
            else None
        )
        comparison = _metric_comparison(
            metric_id=metric_id,
            label=label,
            unit=unit,
            current=current,
            baseline=baseline,
            comparison_mode=comparison_mode,
            as_of=_datetime_or_none(evidence.get("as_of")),
            projection_value=_number_or_none(evidence.get("projection_value")),
            projection_low=_number_or_none(evidence.get("projection_low")),
            projection_high=_number_or_none(evidence.get("projection_high")),
            projection_confidence=_number_or_none(
                evidence.get("projection_confidence")
            ),
            full_period_normal_low=_number_or_none(
                evidence.get("full_period_normal_low")
            )
            if evidence.get("full_period_normal_low") is not None
            else full_period[0]
            if full_period is not None
            else None,
            full_period_normal_high=_number_or_none(
                evidence.get("full_period_normal_high")
            )
            if evidence.get("full_period_normal_high") is not None
            else full_period[1]
            if full_period is not None
            else None,
            full_period_normal_median=_number_or_none(
                evidence.get("full_period_normal_median")
            )
            if evidence.get("full_period_normal_median") is not None
            else full_period[2]
            if full_period is not None
            else None,
            configured_warning_value=(
                _number_or_none(evidence.get("warning_ratio")) * 100.0
                if metric_id == "capacity_usage_percent"
                and _number_or_none(evidence.get("warning_ratio")) is not None
                else None
            ),
            configured_limit_value=(
                100.0
                if metric_id == "capacity_usage_percent"
                else _number_or_none(evidence.get("demand_limit_w"))
                if metric_id == "demand_peak_w"
                else None
            ),
            limit_unit=(
                "%"
                if metric_id == "capacity_usage_percent"
                else "W"
                if metric_id == "demand_peak_w"
                and _number_or_none(evidence.get("demand_limit_w")) is not None
                else None
            ),
            explanation=str(evidence.get("comparison_explanation") or ""),
        )
        if comparison is not None:
            comparisons.append(comparison)
    return tuple(comparisons)


def appliance_expectations_for_circuit(
    coordinator: Any,
    config: CircuitConfig,
    state: Any,
    *,
    comparisons: tuple[MetricComparison, ...],
    source_type: SourceType,
    evidence_path: str,
) -> tuple[ApplianceExpectation, ...]:
    """Return up to three ranked, semantically distinct findings."""
    primary = _primary_appliance_expectations_for_circuit(
        coordinator,
        config,
        state,
        comparisons=comparisons,
        source_type=source_type,
        evidence_path=evidence_path,
    )
    maintenance = _mapping_for_circuit(
        state,
        "maintenance_by_circuit",
        config.circuit_id,
    )
    candidates = list(primary)
    if maintenance.get("active") is True:
        checklist = _mapping_for_circuit(
            state,
            "data_quality_checklist_by_circuit",
            config.circuit_id,
        )
        if checklist and _data_quality_problem(checklist):
            candidates.append(
                _expectation(
                    config,
                    title="Source data needs review",
                    status="not_enough_data",
                    source_type=source_type,
                    observed="Analyzer source data is missing, stale, or invalid.",
                    expected="Reliable checks need fresh numeric source data.",
                    why_it_matters="Maintenance still requires trustworthy inputs.",
                    what_to_check_first=("Review source sensor data.",),
                    evidence_path=evidence_path,
                )
            )
        return _ranked_distinct_expectations(candidates)

    runtime_is_context_explained = bool(primary and primary[0].status == "expected")
    electrical_attrs = electrical_health_attributes(state, config.circuit_id)
    if (
        _mapping_status(
            state,
            "leg_imbalance_status_by_circuit",
            config.circuit_id,
        )
        == "imbalanced"
    ):
        candidates.append(
            _expectation(
                config,
                title="Electrical balance needs review",
                status="possible_issue",
                source_type=source_type,
                observed="A dual-phase load has meaningful leg-to-leg imbalance.",
                expected="Both legs should stay within the learned balance range.",
                why_it_matters=(
                    "Imbalance can indicate CT pairing, wiring, or load issues."
                ),
                what_to_check_first=_first_checks(
                    electrical_attrs.get("what_to_check_first")
                ),
                evidence_path=evidence_path,
            )
        )
    for metric_id, title, observed, first_check in (
        (
            "daily_energy_kwh",
            "Energy is above normal",
            f"{config.name} energy is above normal today.",
            "Review recent use and source data.",
        ),
        (
            "runtime_today_seconds",
            "Runtime is above normal",
            f"{config.name} runtime is above the learned range.",
            "Check whether the appliance is still running or ran longer than expected.",
        ),
    ):
        if metric_id == "runtime_today_seconds" and runtime_is_context_explained:
            continue
        comparison = _comparison_by_id(comparisons, metric_id)
        if not _is_higher(comparison):
            continue
        candidates.append(
            _expectation(
                config,
                title=title,
                status="watch",
                source_type=source_type,
                observed=observed,
                expected=_normal_range_text(comparison),
                why_it_matters=(
                    "Repeated changes from this appliance's own normal may need review."
                ),
                what_to_check_first=(first_check,),
                evidence_path=evidence_path,
            )
        )
    return _ranked_distinct_expectations(candidates)


def _ranked_distinct_expectations(
    candidates: list[ApplianceExpectation],
) -> tuple[ApplianceExpectation, ...]:
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (_expectation_rank(item[1]), item[0]),
    )
    selected: list[ApplianceExpectation] = []
    groups: set[str] = set()
    for _, candidate in ranked:
        group = _expectation_semantic_group(candidate)
        if group in groups:
            continue
        groups.add(group)
        selected.append(candidate)
        if len(selected) == 3:
            break
    return tuple(selected)


def _expectation_rank(expectation: ApplianceExpectation) -> int:
    group = _expectation_semantic_group(expectation)
    if group == "data_quality":
        return 0
    if group in {"electrical", "capacity"}:
        return 1
    if expectation.status == "possible_issue":
        return 2
    if group == "nilm":
        return 3
    if expectation.status == "watch":
        return 4
    if expectation.status == "expected":
        return 6
    return 7


def _expectation_semantic_group(expectation: ApplianceExpectation) -> str:
    text = f"{expectation.expectation_id} {expectation.title}".lower()
    for group, tokens in (
        ("data_quality", ("source data", "data_quality", "missing", "stale")),
        ("electrical", ("electrical", "imbalance", "leg balance")),
        ("capacity", ("capacity", "demand limit")),
        ("nilm", ("nilm", "validation")),
        ("runtime", ("runtime", "cycle")),
        ("energy", ("energy", "usage")),
        ("context", ("weather", "rain", "schedule", "maintenance")),
    ):
        if any(token in text for token in tokens):
            return group
    return expectation.expectation_id


def _primary_appliance_expectations_for_circuit(
    coordinator: Any,
    config: CircuitConfig,
    state: Any,
    *,
    comparisons: tuple[MetricComparison, ...],
    source_type: SourceType,
    evidence_path: str,
) -> tuple[ApplianceExpectation, ...]:
    """Return the established primary behavior expectation."""
    circuit_id = config.circuit_id
    expectation_source = source_type
    maintenance = _mapping_for_circuit(state, "maintenance_by_circuit", circuit_id)
    if maintenance.get("active") is True:
        return (
            _expectation(
                config,
                title="Maintenance mode active",
                status="expected",
                source_type=expectation_source,
                observed="Maintenance is active for this appliance.",
                expected="Alert language is suppressed while work is expected.",
                why_it_matters=(
                    "This prevents maintenance work from looking like a new concern."
                ),
                what_to_check_first=(
                    "Finish maintenance and resume alerts when work is complete.",
                ),
                evidence_path=evidence_path,
            ),
        )

    checklist = _mapping_for_circuit(
        state,
        "data_quality_checklist_by_circuit",
        circuit_id,
    )
    if checklist and _data_quality_problem(checklist):
        return (
            _expectation(
                config,
                title="Source data needs review",
                status="not_enough_data",
                source_type=expectation_source,
                observed="Analyzer source data is missing, stale, or invalid.",
                expected="Reliable appliance checks need fresh numeric source data.",
                why_it_matters=(
                    "Behavior guidance is only useful when inputs are valid."
                ),
                what_to_check_first=("Review source sensor data.",),
                evidence_path=evidence_path,
            ),
        )

    if config.mode is CircuitMode.MIXED:
        return (
            _expectation(
                config,
                title="Shared circuit measurement",
                status="not_enough_data",
                source_type=expectation_source,
                observed="This measurement covers the whole shared circuit.",
                expected=(
                    "Reviewed Experimental NILM is required for "
                    "appliance-specific evidence."
                ),
                why_it_matters=(
                    "Direct appliance classifications do not apply to shared loads."
                ),
                what_to_check_first=("Review Experimental NILM assignments.",),
                evidence_path=evidence_path,
            ),
        )

    electrical_attrs = electrical_health_attributes(state, circuit_id)
    if _mapping_status(state, "leg_imbalance_status_by_circuit", circuit_id) == (
        "imbalanced"
    ):
        return (
            _expectation(
                config,
                title="Electrical balance needs review",
                status="possible_issue",
                source_type=expectation_source,
                observed="A dual-phase load has meaningful leg-to-leg imbalance.",
                expected="Both legs should stay within the learned balance range.",
                why_it_matters=(
                    "Imbalance can indicate CT pairing, wiring, or load issues."
                ),
                what_to_check_first=_first_checks(
                    electrical_attrs.get("what_to_check_first")
                ),
                evidence_path=evidence_path,
            ),
        )

    daily = _comparison_by_id(comparisons, "daily_energy_kwh")
    runtime = _comparison_by_id(comparisons, "runtime_today_seconds")
    profile = config.appliance_profile
    if profile in {ApplianceProfile.REFRIGERATOR, ApplianceProfile.FREEZER}:
        signature_alert = next(
            (
                alert
                for alert in _active_alert_summaries(
                    state,
                    circuit_id,
                    config=config,
                )
                if alert.feature == COLD_STORAGE_SIGNATURE_FEATURE
            ),
            None,
        )
        if signature_alert is not None:
            return (
                _expectation(
                    config,
                    title="Compressor pattern changed",
                    status="possible_issue",
                    source_type=expectation_source,
                    observed=signature_alert.message,
                    expected=(
                        "The learned PF, power, and current pulse pattern should "
                        "recur while workload stays near its normal range."
                    ),
                    why_it_matters=(
                        "A missing compressor signature plus higher workload can "
                        "point to a door, seal, airflow, or cooling problem."
                    ),
                    what_to_check_first=(
                        "Check that doors are fully closed, seals and vents are "
                        "clear, and temperatures are normal.",
                    ),
                    evidence_path=evidence_path,
                ),
            )
        if _is_higher(daily):
            return (
                _expectation(
                    config,
                    title="Energy is above normal",
                    status="watch",
                    source_type=expectation_source,
                    observed=f"{config.name} energy is above normal today.",
                    expected=_normal_range_text(daily),
                    why_it_matters=("Cold appliances should cycle and return to idle."),
                    what_to_check_first=("Check the door seal, coils, and airflow.",),
                    evidence_path=evidence_path,
                ),
            )
        return (
            _expectation(
                config,
                title="Cycling looks normal",
                status=_ok_or_learning(daily),
                source_type=expectation_source,
                observed="Daily energy is within the learned range."
                if _is_normal(daily)
                else "The analyzer is still learning this appliance.",
                expected="Cold appliances should cycle and return to idle.",
                why_it_matters="Continuous running can point to cooling problems.",
                what_to_check_first=("No appliance check is needed right now.",),
                evidence_path=evidence_path,
            ),
        )

    if profile in {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_SYSTEM,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
    } and _is_higher(runtime):
        weather_status = _mapping_status(
            state,
            "weather_context_by_circuit",
            circuit_id,
        )
        if weather_status in {
            "weather_correlated",
            "hot_weather",
            "expected",
            "context_explained",
        }:
            return (
                _expectation(
                    config,
                    title="Runtime fits weather context",
                    status="expected",
                    source_type=expectation_source,
                    observed="Longer runtime is explained by weather context.",
                    expected=_normal_range_text(runtime),
                    why_it_matters=(
                        "HVAC runtime should change with outdoor temperature."
                    ),
                    what_to_check_first=("No action needed unless comfort is poor.",),
                    evidence_path=evidence_path,
                ),
            )
        return (
            _expectation(
                config,
                title="Runtime is above normal",
                status="watch",
                source_type=expectation_source,
                observed="HVAC runtime is above the learned range.",
                expected=_normal_range_text(runtime),
                why_it_matters=(
                    "Long runtime on mild days may indicate efficiency issues."
                ),
                what_to_check_first=("Check filters, vents, and setpoints.",),
                evidence_path=evidence_path,
            ),
        )

    if profile in {
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
    } and _is_higher(runtime):
        rain_status = _mapping_status(
            state,
            "rain_pump_context_by_circuit",
            circuit_id,
        )
        if rain_status in {"rain_explained", "weather_explained", "expected"}:
            return (
                _expectation(
                    config,
                    title="Pump activity fits rain context",
                    status="expected",
                    source_type=expectation_source,
                    observed="Recent rain explains the pump runtime.",
                    expected=_normal_range_text(runtime),
                    why_it_matters="Pump activity often follows rain or water use.",
                    what_to_check_first=(),
                    evidence_path=evidence_path,
                ),
            )
        return (
            _expectation(
                config,
                title="Pump runtime is above normal",
                status="watch",
                source_type=expectation_source,
                observed="Pump runtime is above the learned range without context.",
                expected=_normal_range_text(runtime),
                why_it_matters=(
                    "Unexpected pump activity can point to water intrusion or leaks."
                ),
                what_to_check_first=("Check for water flow, rain, or a stuck pump.",),
                evidence_path=evidence_path,
            ),
        )

    recipe = _PROFILE_EXPECTATION_RECIPES.get(profile)

    if _is_higher(daily) or _is_higher(runtime):
        expected = (
            recipe[1]
            if recipe
            else "Usage should stay within the learned normal range."
        )
        why_it_matters = recipe[2] if recipe else "A change in use may need review."
        first_checks = (
            recipe[3] if recipe else ("Review recent activity and source data.",)
        )
        return (
            _expectation(
                config,
                title="Usage is above normal",
                status="watch",
                source_type=expectation_source,
                observed="One or more usage metrics are above the learned range.",
                expected=expected,
                why_it_matters=why_it_matters,
                what_to_check_first=first_checks,
                evidence_path=evidence_path,
            ),
        )

    if recipe is not None:
        title, expected, why_it_matters, first_checks = recipe
        return (
            _expectation(
                config,
                title=title,
                status="ok",
                source_type=expectation_source,
                observed="No profile-specific behavior issue is currently visible.",
                expected=expected,
                why_it_matters=why_it_matters,
                what_to_check_first=first_checks,
                evidence_path=evidence_path,
            ),
        )

    return (
        _expectation(
            config,
            title="Behavior looks normal",
            status="ok",
            source_type=expectation_source,
            observed="No appliance behavior issue is currently visible.",
            expected="Usage and activity should stay within learned ranges.",
            why_it_matters="This is the baseline appliance check.",
            what_to_check_first=(),
            evidence_path=evidence_path,
        ),
    )


def _nilm_expectations(
    state: NilmVirtualApplianceState,
    *,
    review_needed: bool,
    evidence_path: str,
    comparisons: tuple[MetricComparison, ...] = (),
) -> tuple[ApplianceExpectation, ...]:
    if review_needed:
        status: ExpectationStatus = "watch"
        observed = (
            f"NILM confidence is {round(state.confidence * 100)}% and status is "
            f"{state.model_status}."
        )
        title = "NILM assignment needs validation"
        first_check = "Validate this estimated appliance before relying on alerts."
    else:
        status = "ok"
        observed = "The NILM assignment is validated with sufficient confidence."
        title = "NILM estimate is validated"
        first_check = "No validation action is needed right now."
    candidates = [
        ApplianceExpectation(
            expectation_id=f"{state.assignment_id}:nilm_validation",
            circuit_id=state.mains_circuit_id,
            title=title,
            status=status,
            source_type="nilm_estimate",
            confidence=state.confidence,
            observed=observed,
            expected="Estimated appliances should be validated before alerts.",
            why_it_matters=(
                "NILM is an estimate from mains power, not a direct measurement."
            ),
            what_to_check_first=(first_check,),
            evidence_path=evidence_path,
        )
    ]
    energy = _comparison_by_id(comparisons, "daily_energy_kwh")
    if _is_higher(energy):
        candidates.append(
            ApplianceExpectation(
                expectation_id=f"{state.assignment_id}:energy",
                circuit_id=state.mains_circuit_id,
                title="Estimated energy is above normal",
                status="watch",
                source_type="nilm_estimate",
                confidence=state.confidence,
                observed="Estimated energy is above the validated learned range.",
                expected=_normal_range_text(energy),
                why_it_matters="This estimate should be reviewed with its sessions.",
                what_to_check_first=(
                    "Confirm the assignment and recent NILM intervals.",
                ),
                evidence_path=evidence_path,
            )
        )
    return _ranked_distinct_expectations(candidates)


def _active_alert_summaries(
    state: Any,
    circuit_id: str,
    *,
    config: CircuitConfig | None,
    assignment_id: str | None = None,
) -> tuple[ApplianceAlertSummary, ...]:
    alerts_by_circuit = getattr(state, "active_alerts_by_circuit", {})
    alerts = (
        alerts_by_circuit.get(circuit_id, ())
        if isinstance(alerts_by_circuit, Mapping)
        else ()
    )
    summaries: list[ApplianceAlertSummary] = []
    for alert in alerts:
        if not isinstance(alert, AlertEvidence):
            continue
        if assignment_id is not None and (
            str(alert.features.get("assignment_id") or "").strip() != assignment_id
        ):
            continue
        summaries.append(
            ApplianceAlertSummary(
                alert_id=notification_id_for_alert(alert),
                feature=alert.feature,
                message=alert.message,
                severity=str(alert.severity.value),
                observed_value=_number_or_none(alert.observed_value),
                baseline_value=_number_or_none(alert.baseline_value),
                change_ratio=_number_or_none(alert.change_ratio),
                repeated_count=int(alert.repeated_count),
                first_seen=_iso(alert.first_seen),
                last_seen=_iso(alert.last_seen),
                evidence_path=(
                    alert_evidence_path(alert)
                    if assignment_id is not None
                    else _evidence_path(
                        circuit_id=circuit_id,
                        alert_id=notification_id_for_alert(alert),
                        feature=alert.feature,
                    )
                )
                if config is not None or assignment_id is not None
                else None,
            )
        )
    return tuple(summaries)


def _comparison_baseline(
    coordinator: Any,
    state: Any,
    circuit_id: str,
    *,
    metric_id: str,
    baseline_features: tuple[str, ...],
) -> ComparisonBaseline | None:
    if metric_id == "daily_energy_kwh":
        evidence = _mapping_for_circuit(
            state,
            "energy_usage_evidence_by_circuit",
            circuit_id,
        )
        contextual_range = evidence.get("contextual_expected_range")
        if isinstance(contextual_range, list | tuple) and len(contextual_range) >= 2:
            low = _number_or_none(contextual_range[0])
            high = _number_or_none(contextual_range[1])
            if low is not None or high is not None:
                return (
                    low,
                    high,
                    _number_or_none(evidence.get("contextual_baseline_median_kwh")),
                    _number_or_none(evidence.get("contextual_baseline_confidence")),
                    "contextual_baseline",
                )

    if metric_id == "demand_peak_w":
        evidence = _mapping_for_circuit(
            state,
            "demand_evidence_by_circuit",
            circuit_id,
        )
        contextual_range = evidence.get("contextual_expected_range_w")
        if isinstance(contextual_range, list | tuple) and len(contextual_range) >= 2:
            low = _number_or_none(contextual_range[0])
            high = _number_or_none(contextual_range[1])
            if low is not None or high is not None:
                return (
                    low,
                    high,
                    _number_or_none(evidence.get("contextual_baseline_median_w")),
                    _number_or_none(evidence.get("contextual_baseline_confidence")),
                    "contextual_baseline",
                )

    if metric_id == "runtime_today_seconds":
        return _evidence_baseline(
            _mapping_for_circuit(
                state,
                "run_cycle_evidence_by_circuit",
                circuit_id,
            ),
            range_key="runtime_today_contextual_expected_range_seconds",
            median_key="runtime_today_contextual_baseline_median_seconds",
            confidence_key="runtime_today_contextual_baseline_confidence",
        )

    if metric_id == "run_count_today":
        return _evidence_baseline(
            _mapping_for_circuit(
                state,
                "run_cycle_evidence_by_circuit",
                circuit_id,
            ),
            range_key="run_count_contextual_expected_range",
            median_key="run_count_contextual_baseline_median",
            confidence_key="run_count_contextual_baseline_confidence",
        )

    if metric_id == "cost_today":
        return _evidence_baseline(
            _mapping_for_circuit(
                state,
                "cost_evidence_by_circuit",
                circuit_id,
            ),
            range_key="contextual_expected_range",
            median_key="contextual_baseline_median_cost",
            confidence_key="contextual_baseline_confidence",
        )

    if metric_id in {
        "daily_energy_kwh",
        "runtime_today_seconds",
        "run_count_today",
        "cost_today",
        "demand_peak_w",
    }:
        # Open-period values may only use explicitly same-time evidence above.
        return None

    return _stored_baseline(coordinator, circuit_id, baseline_features)


def _evidence_baseline(
    evidence: Mapping[str, Any],
    *,
    range_key: str,
    median_key: str,
    confidence_key: str,
) -> ComparisonBaseline | None:
    contextual_range = evidence.get(range_key)
    if not isinstance(contextual_range, list | tuple) or len(contextual_range) < 2:
        return None
    low = _number_or_none(contextual_range[0])
    high = _number_or_none(contextual_range[1])
    if low is None and high is None:
        return None
    return (
        low,
        high,
        _number_or_none(evidence.get(median_key)),
        _number_or_none(evidence.get(confidence_key)),
        "contextual_baseline",
    )


def _stored_baseline(
    coordinator: Any,
    circuit_id: str,
    baseline_features: tuple[str, ...],
) -> ComparisonBaseline | None:
    store_data = getattr(coordinator, "store_data", None)
    baselines = getattr(store_data, "baselines", {})
    if not isinstance(baselines, Mapping):
        return None
    for feature in baseline_features:
        for key in (f"{circuit_id}:{feature}", feature):
            baseline = baselines.get(key)
            if isinstance(baseline, BaselineStats):
                return (
                    baseline.p10,
                    baseline.p90,
                    baseline.median,
                    baseline.confidence,
                    "baseline",
                )
    return None


def _metric_comparison(
    *,
    metric_id: str,
    label: str,
    unit: str,
    current: float | None,
    baseline: ComparisonBaseline | None,
    comparison_mode: ComparisonMode,
    as_of: datetime | None = None,
    projection_value: float | None = None,
    projection_low: float | None = None,
    projection_high: float | None = None,
    projection_confidence: float | None = None,
    full_period_normal_low: float | None = None,
    full_period_normal_high: float | None = None,
    full_period_normal_median: float | None = None,
    configured_warning_value: float | None = None,
    configured_limit_value: float | None = None,
    limit_unit: str | None = None,
    explanation: str = "",
) -> MetricComparison | None:
    if baseline is None:
        has_full_period_baseline = any(
            value is not None
            for value in (
                full_period_normal_low,
                full_period_normal_high,
                full_period_normal_median,
            )
        )
        if current is None and not has_full_period_baseline:
            return None
        return MetricComparison(
            metric_id=metric_id,
            label=label,
            unit=unit,
            current_value=current,
            normal_low=None,
            normal_high=None,
            normal_median=None,
            status="missing_data" if current is None else "learning",
            confidence=None,
            source="current_state",
            comparison_mode=comparison_mode,
            as_of=as_of,
            projection_value=projection_value,
            projection_low=projection_low,
            projection_high=projection_high,
            projection_confidence=projection_confidence,
            full_period_normal_low=full_period_normal_low,
            full_period_normal_high=full_period_normal_high,
            full_period_normal_median=full_period_normal_median,
            configured_warning_value=configured_warning_value,
            configured_limit_value=configured_limit_value,
            limit_unit=limit_unit,
            explanation=explanation,
        )

    low, high, median, confidence, source = baseline
    if current is None:
        status: MetricStatus = "missing_data"
    elif high is not None and current > high:
        status = "higher"
    elif low is not None and current < low:
        status = "lower"
    else:
        status = "normal"
    return MetricComparison(
        metric_id=metric_id,
        label=label,
        unit=unit,
        current_value=current,
        normal_low=low,
        normal_high=high,
        normal_median=median,
        status=status,
        confidence=confidence,
        source=source,
        comparison_mode=comparison_mode,
        as_of=as_of,
        projection_value=projection_value,
        projection_low=projection_low,
        projection_high=projection_high,
        projection_confidence=projection_confidence,
        full_period_normal_low=full_period_normal_low,
        full_period_normal_high=full_period_normal_high,
        full_period_normal_median=full_period_normal_median,
        configured_warning_value=configured_warning_value,
        configured_limit_value=configured_limit_value,
        limit_unit=limit_unit,
        explanation=explanation,
    )


def _comparison_mode(metric_id: str) -> ComparisonMode:
    if metric_id in {
        "daily_energy_kwh",
        "runtime_today_seconds",
        "run_count_today",
        "cost_today",
        "demand_peak_w",
    }:
        return ComparisonMode.SAME_TIME_OF_DAY
    return ComparisonMode.CURRENT_STATE


def _expectation(
    config: CircuitConfig,
    *,
    title: str,
    status: ExpectationStatus,
    source_type: SourceType,
    observed: str,
    expected: str,
    why_it_matters: str,
    what_to_check_first: tuple[str, ...],
    evidence_path: str | None,
) -> ApplianceExpectation:
    return ApplianceExpectation(
        expectation_id=f"{config.circuit_id}:{_slug(title)}",
        circuit_id=config.circuit_id,
        title=title,
        status=status,
        source_type=source_type,
        confidence=None,
        observed=observed,
        expected=expected,
        why_it_matters=why_it_matters,
        what_to_check_first=what_to_check_first,
        evidence_path=evidence_path,
    )


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)


def _mapping_for_circuit(state: Any, field: str, circuit_id: str) -> dict[str, Any]:
    values = getattr(state, field, {})
    if not isinstance(values, Mapping):
        return {}
    value = values.get(circuit_id)
    return dict(value) if isinstance(value, Mapping) else {}


def _water_flow_context_detail(
    state: Any,
    config: CircuitConfig,
) -> dict[str, Any] | None:
    retained = _mapping_for_circuit(
        state,
        "water_flow_context_by_circuit",
        config.circuit_id,
    )
    if not retained:
        return None

    source_ids = retained.get("flow_sensor_entities", [])
    if not isinstance(source_ids, list):
        source_ids = []
    sources = sorted(
        {str(entity_id) for entity_id in source_ids if str(entity_id)}
    )
    detail = {
        "status": str(retained.get("status") or "unconfigured"),
        "flow_sensors": [
            {
                "entity_id": entity_id,
                "name": _entity_display_name(entity_id),
            }
            for entity_id in sources
        ],
        "learning": {
            "comparable_window_count": max(
                int(retained.get("comparable_window_count") or 0),
                0,
            ),
            "required_comparable_windows": MIN_COMPARABLE_WINDOWS,
        },
    }
    for field in (
        "confidence",
        "flow_sensor_active",
        "flow_active_minutes",
        "appliance_runtime_minutes",
        "mapped_appliance_count",
        "mapped_appliance_runtime_minutes",
        "recent_related_runtime_minutes",
        "recent_flow_explains_activity",
        "mismatch_minutes",
        "flow_mismatch_threshold_minutes",
    ):
        if (value := retained.get(field)) is not None:
            detail[field] = value
    if summary := str(retained.get("friendly_summary") or ""):
        detail["friendly_summary"] = summary
    return detail


_HVAC_EFFICIENCY_PROFILES = frozenset(
    {
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.ELECTRIC_HEAT,
    }
)


def _hvac_efficiency_detail(
    state: Any,
    config: CircuitConfig,
) -> dict[str, Any] | None:
    if config.appliance_profile not in _HVAC_EFFICIENCY_PROFILES:
        return None
    retained = _mapping_for_circuit(
        state,
        "hvac_efficiency_by_circuit",
        config.circuit_id,
    )
    modes: dict[str, list[dict[str, Any]]] = {
        "heating": [],
        "cooling": [],
    }
    streams = retained.get("streams", {})
    if isinstance(streams, Mapping):
        for stream_id, raw in streams.items():
            if not isinstance(raw, Mapping):
                continue
            context = raw.get("context", {})
            context = context if isinstance(context, Mapping) else {}
            mode = str(
                context.get("mode") or str(stream_id).rsplit("|", 1)[-1]
            )
            if mode not in modes:
                continue
            thermostat_id = str(
                context.get("thermostat_entity_id")
                or str(stream_id).split("|")[1]
            )
            participants = sorted(
                {
                    str(item)
                    for item in context.get("participant_signature", ())
                    if str(item)
                }
            )
            modes[mode].append(
                {
                    "thermostat_entity_id": thermostat_id,
                    "thermostat_name": _entity_display_name(thermostat_id),
                    "status": str(raw.get("status") or "learning"),
                    "score": _rounded_number(raw.get("score")),
                    "trend": str(raw.get("finding") or "") or None,
                    "change_percent": _rounded_percent(raw.get("change_ratio")),
                    "baseline_minutes_per_degree": _rounded_number(
                        raw.get("baseline_minutes_per_degree")
                    ),
                    "recent_minutes_per_degree": _rounded_number(
                        raw.get("recent_minutes_per_degree")
                    ),
                    "reference_count": int(raw.get("reference_count") or 0),
                    "recent_count": int(raw.get("recent_count") or 0),
                    "outdoor_temperature_f": _rounded_number(
                        context.get("outdoor_temperature_f")
                    ),
                    "season": str(context.get("season") or "") or None,
                    "weather_mode": (
                        str(context.get("weather_mode") or "") or None
                    ),
                    "temperature_bin": (
                        str(context.get("temperature_bin") or "") or None
                    ),
                    "gap_bin": str(context.get("gap_bin") or "") or None,
                    "participant_signature": participants,
                    "supporting_blower_ids": sorted(
                        {
                            str(item)
                            for item in context.get("supporting_blower_ids", ())
                            if str(item)
                        }
                    ),
                    "attribution": (
                        "gas_furnace_proxy"
                        if config.appliance_profile
                        is ApplianceProfile.HVAC_BLOWER
                        else "assisted_system"
                        if len(participants) > 1
                        else "direct"
                    ),
                }
            )
    for rows in modes.values():
        rows.sort(key=lambda row: row["thermostat_entity_id"])
    all_rows = [*modes["heating"], *modes["cooling"]]
    score = _rounded_number(retained.get("score"))
    return {
        "status": str(retained.get("status") or "learning"),
        "summary_score": score,
        "trend": (
            str(retained.get("finding") or "")
            or ("stable" if score is not None else None)
        ),
        "threshold_pct": (
            _rounded_number(retained.get("threshold_pct")) or 25.0
        ),
        **modes,
        "learning": {
            "reference_count": max(
                (row["reference_count"] for row in all_rows),
                default=0,
            ),
            "recent_count": max(
                (row["recent_count"] for row in all_rows),
                default=0,
            ),
            "required_reference": 9,
            "required_recent": 3,
        },
    }


def _entity_display_name(entity_id: str) -> str:
    return entity_id.rsplit(".", 1)[-1].replace("_", " ").title()


def _rounded_number(value: Any) -> float | None:
    parsed = _number_or_none(value)
    return (
        round(parsed, 2)
        if parsed is not None and math.isfinite(parsed)
        else None
    )


def _rounded_percent(value: Any) -> float | None:
    parsed = _number_or_none(value)
    return (
        round(parsed * 100.0, 1)
        if parsed is not None and math.isfinite(parsed)
        else None
    )


def _recent_timeline(state: Any, circuit_id: str) -> dict[str, Any] | None:
    timeline = _mapping_for_circuit(
        state,
        "recent_activity_timeline_by_circuit",
        circuit_id,
    )
    return timeline or None


def _mapping_status(state: Any, field: str, circuit_id: str) -> str:
    values = getattr(state, field, {})
    if not isinstance(values, Mapping):
        return ""
    value = values.get(circuit_id)
    if isinstance(value, Mapping):
        return str(value.get("status") or "").strip()
    return str(value or "").strip()


def _data_quality_problem(checklist: Mapping[str, Any]) -> bool:
    if checklist.get("quality_issues"):
        return True
    if checklist.get("required_sensors_present") is False:
        return True
    for key in ("numeric_states_valid", "source_data_fresh"):
        if checklist.get(key) is False:
            return True
    return False


def _comparison_by_id(
    comparisons: tuple[MetricComparison, ...],
    metric_id: str,
) -> MetricComparison | None:
    for comparison in comparisons:
        if comparison.metric_id == metric_id:
            return comparison
    return None


def _is_higher(comparison: MetricComparison | None) -> bool:
    return comparison is not None and comparison.status == "higher"


def _is_normal(comparison: MetricComparison | None) -> bool:
    return comparison is not None and comparison.status == "normal"


def _ok_or_learning(comparison: MetricComparison | None) -> ExpectationStatus:
    if comparison is None or comparison.status in {"learning", "missing_data"}:
        return "not_enough_data"
    return "ok"


def _normal_range_text(comparison: MetricComparison | None) -> str:
    if (
        comparison is None
        or comparison.normal_low is None
        or comparison.normal_high is None
    ):
        return "Normal range is still learning."
    return (
        f"Normal is {comparison.normal_low:g}-{comparison.normal_high:g} "
        f"{comparison.unit}."
    )


def _config_for_circuit(coordinator: Any, circuit_id: str) -> CircuitConfig | None:
    for config in getattr(coordinator, "circuit_configs", ()) or ():
        if isinstance(config, CircuitConfig) and config.circuit_id == circuit_id:
            return config
    return None


def _coordinator_state(coordinator: Any) -> Any:
    return getattr(coordinator, "state", None) or getattr(coordinator, "data", None)


def _source_type_for_config(config: CircuitConfig) -> SourceType:
    if (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    ):
        return "mains"
    if (
        config.mode is CircuitMode.MIXED
        or config.appliance_profile is ApplianceProfile.MIXED
    ):
        return "mixed"
    return "direct_meter"


def _evidence_path(
    *,
    circuit_id: str,
    alert_id: str | None = None,
    feature: str | None = None,
) -> str:
    params = {"circuit_id": circuit_id}
    if alert_id:
        params["alert_id"] = alert_id
    if feature:
        params["feature"] = feature
    return f"{DEFAULT_ALERT_EVIDENCE_PATH}?{urlencode(params)}"


def _nilm_evidence_path(state: NilmVirtualApplianceState) -> str:
    query = urlencode(
        {
            "circuit_id": state.mains_circuit_id,
            "assignment_id": state.assignment_id,
            "nilm_workspace": "1",
            "appliance_detail": "1",
        }
    )
    return f"{DEFAULT_ALERT_EVIDENCE_PATH}?{query}"


def _first_checks(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    return tuple(str(item).strip() for item in _iter_items(value) if str(item).strip())


def _metric_comparison_sources_complete(checklist: Mapping[str, Any]) -> bool:
    roles = {str(role) for role in checklist.get("metric_roles_present") or ()}
    has_expected_apparent_power = {"voltage", "current"} <= roles
    has_reported_apparent_power = "apparent_power" in roles
    has_apparent_power_comparison = (
        has_expected_apparent_power and has_reported_apparent_power
    )
    has_power_factor_comparison = {
        "real_power",
        "power_factor",
    } <= roles and (has_expected_apparent_power or has_reported_apparent_power)
    return has_apparent_power_comparison or has_power_factor_comparison


def _state_number(state: Any, field: str, key: str) -> float | None:
    mapping = getattr(state, field, {})
    if not isinstance(mapping, Mapping) or key not in mapping:
        return None
    return _number_or_none(mapping.get(key))


def _direct_source_quality(config: CircuitConfig, state: Any) -> dict[str, Any]:
    checklist = _mapping_for_circuit(
        state,
        "data_quality_checklist_by_circuit",
        config.circuit_id,
    )
    missing_roles = list(checklist.get("missing_required_metric_roles") or [])
    roles_present = list(checklist.get("metric_roles_present") or [])
    if not checklist:
        status = "unavailable"
        label = "Unavailable"
    elif checklist.get("required_sensors_present") is False or missing_roles:
        status = "missing_metric"
        label = "Missing metric"
    elif checklist.get("source_data_fresh") is False:
        status = "stale"
        label = "Stale"
    elif checklist.get("numeric_states_valid") is False:
        status = "unavailable"
        label = "Unavailable"
    else:
        status = "fresh"
        label = "Fresh"
    return {
        "status": status,
        "label": label,
        "available_source_count": len(roles_present),
        "configured_source_count": len(config.sensors),
        "stale_source_count": 1 if status == "stale" else 0,
        "missing_required_roles": missing_roles,
    }


def _learning_readiness(
    state: Any,
    circuit_id: str,
    config: CircuitConfig,
) -> dict[str, Any]:
    progress = _mapping_for_circuit(
        state,
        "learning_progress_by_circuit",
        circuit_id,
    )
    energy = _mapping_for_circuit(
        state,
        "energy_usage_evidence_by_circuit",
        circuit_id,
    )
    if progress.get("alert_ready") is True:
        status, label = "ready", "Ready"
    elif energy.get("status") == "waiting_for_delta":
        status, label = "waiting_for_delta", "Waiting for first kWh delta"
    else:
        status, label = "learning", "Learning"
    days_required = max(
        get_profile_definition(config.appliance_profile).minimum_learning_days,
        1,
    )
    baseline_age_days = _number_or_none(progress.get("baseline_age_days"))
    days_complete = min(int(baseline_age_days or 0), days_required)
    return {
        "status": status,
        "label": label,
        "baseline_age_days": baseline_age_days,
        "days_complete": days_complete,
        "days_required": days_required,
        "cycle_count": _state_int_value(progress.get("cycle_count")),
        "learned_feature_count": _state_int_value(
            progress.get("learned_feature_count")
        ),
        "pending_feature_samples": _state_int_value(
            progress.get("pending_feature_samples")
        ),
    }


def _state_int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _estimated_cost_today(state: Any, circuit_id: str) -> float | None:
    status = _mapping_status(
        state,
        "cost_today_status_by_circuit",
        circuit_id,
    )
    if status == "actual":
        actual = _state_number(state, "cost_today_by_circuit", circuit_id)
        if actual is not None:
            return actual
    estimated = _state_number(state, "estimated_cost_today_by_circuit", circuit_id)
    if estimated is not None:
        return estimated
    if status == "unavailable":
        return None
    evidence = _mapping_for_circuit(
        state,
        "cost_evidence_by_circuit",
        circuit_id,
    )
    if evidence.get("cost_today_status") == "unavailable":
        return None
    return _state_number(state, "cost_today_by_circuit", circuit_id)


def _cost_today_status(state: Any, circuit_id: str) -> str:
    status = _mapping_status(state, "cost_today_status_by_circuit", circuit_id)
    if status == "actual":
        return "recorded"
    if _state_number(state, "estimated_cost_today_by_circuit", circuit_id) is not None:
        return "estimated"
    return "unavailable"


def _estimated_cost(energy_kwh: float | None, rate: float | None) -> float | None:
    if energy_kwh is None or rate is None:
        return None
    return _round_money(energy_kwh * rate)


def _state_int(state: Any, field: str, key: str) -> int | None:
    mapping = getattr(state, field, {})
    if not isinstance(mapping, Mapping) or key not in mapping:
        return None
    try:
        return int(mapping[key])
    except (TypeError, ValueError):
        return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _iso_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    return _iso(value)


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iter_items(value: Any) -> tuple[Any, ...]:
    if value is None or isinstance(value, str | bytes):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()
