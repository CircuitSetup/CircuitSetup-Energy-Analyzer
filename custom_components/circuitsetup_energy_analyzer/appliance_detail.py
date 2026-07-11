from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlencode

from .alert_links import DEFAULT_ALERT_EVIDENCE_PATH
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
from .sensor import (
    activity_summary_value,
    electrical_health_attributes,
    electrical_health_value,
    energy_summary_value,
    health_summary_attributes,
    health_summary_value,
)
from .utility_comparison import effective_electricity_rate

SourceType = Literal["direct_meter", "nilm_estimate", "mixed", "mains", "unknown"]
ExpectationStatus = Literal[
    "ok",
    "watch",
    "possible_issue",
    "expected",
    "not_enough_data",
    "not_applicable",
]
MetricStatus = Literal["normal", "higher", "lower", "learning", "missing_data"]
ComparisonBaseline = tuple[float | None, float | None, float | None, float | None, str]
ProfileExpectationRecipe = tuple[str, str, str, tuple[str, ...]]

_PROFILE_EXPECTATION_RECIPES: dict[ApplianceProfile, ProfileExpectationRecipe] = {
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


@dataclass(slots=True)
class MetricComparison:
    """One Today vs Normal comparison for an appliance."""

    metric_id: str
    label: str
    unit: str
    current_value: float | None
    normal_low: float | None
    normal_high: float | None
    normal_median: float | None
    status: MetricStatus
    confidence: float | None
    source: str


@dataclass(slots=True)
class ApplianceExpectation:
    """Plain-language expectation derived from existing analyzer state."""

    expectation_id: str
    circuit_id: str
    title: str
    status: ExpectationStatus
    source_type: SourceType
    confidence: float | None
    observed: str
    expected: str
    why_it_matters: str
    what_to_check_first: tuple[str, ...]
    evidence_path: str | None


@dataclass(slots=True)
class ApplianceAlertSummary:
    """Bounded alert details for appliance-centered payloads."""

    alert_id: str
    feature: str
    message: str
    severity: str
    observed_value: float | None
    baseline_value: float | None
    change_ratio: float | None
    repeated_count: int
    first_seen: str | None
    last_seen: str | None
    evidence_path: str | None


@dataclass(slots=True)
class ApplianceDetail:
    """Appliance-centered read model for panel, dashboard, and diagnostics."""

    circuit_id: str
    display_name: str
    appliance_profile: str
    source_type: SourceType
    confidence: float | None
    model_status: str | None
    activity_state: str
    health_state: str
    electrical_state: str
    energy_state: str
    current_power_w: float | None
    daily_energy_kwh: float | None
    runtime_today_seconds: float | None
    run_count_today: int | None
    cost_today: float | None
    today_vs_normal: tuple[MetricComparison, ...]
    expectations: tuple[ApplianceExpectation, ...]
    recent_timeline: dict[str, Any] | None
    active_alerts: tuple[ApplianceAlertSummary, ...]
    next_step: str | None
    what_to_check_first: tuple[str, ...]
    evidence_path: str | None
    assignment_id: str | None = None
    mains_source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-friendly data."""
        return _jsonable(asdict(self))


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
    comparisons = metric_comparisons_for_circuit(coordinator, config, state)
    expectations = appliance_expectations_for_circuit(
        coordinator,
        config,
        state,
        comparisons=comparisons,
        source_type=source_type,
        evidence_path=_evidence_path(circuit_id=config.circuit_id),
    )
    return ApplianceDetail(
        circuit_id=config.circuit_id,
        display_name=config.name,
        appliance_profile=config.appliance_profile.value,
        source_type=source_type,
        confidence=None,
        model_status=None,
        activity_state=activity_summary_value(state, config.circuit_id),
        health_state=health_summary_value(state, config.circuit_id),
        electrical_state=electrical_health_value(state, config.circuit_id),
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
        today_vs_normal=comparisons,
        expectations=expectations,
        recent_timeline=_recent_timeline(state, config.circuit_id),
        active_alerts=active_alerts,
        next_step=str(health_attrs.get("next_step") or "") or None,
        what_to_check_first=first_checks,
        evidence_path=_evidence_path(circuit_id=config.circuit_id),
    )


def appliance_detail_for_assignment(
    coordinator: Any,
    assignment_id: str,
) -> ApplianceDetail | None:
    """Build Appliance Detail for a stored NILM appliance assignment."""
    requested_id = str(assignment_id or "").strip()
    if not requested_id:
        return None

    for state in nilm_virtual_appliance_states(coordinator, published_only=False):
        if state.assignment_id != requested_id:
            continue
        return _nilm_detail(_coordinator_state(coordinator), state)
    return None


def _nilm_detail(
    analyzer_state: Any,
    state: NilmVirtualApplianceState,
) -> ApplianceDetail:
    evidence_path = _nilm_evidence_path(state)
    review_needed = (
        state.confidence < NILM_FINISHED_CONFIDENCE_THRESHOLD
        or state.model_status in NILM_REVIEW_MODEL_STATES
    )
    return ApplianceDetail(
        circuit_id=state.mains_circuit_id,
        display_name=state.display_name,
        appliance_profile=state.appliance_profile or "nilm_virtual",
        source_type="nilm_estimate",
        confidence=state.confidence,
        model_status=state.model_status,
        activity_state="Estimated Running" if state.is_running else "Idle",
        health_state="Needs validation" if review_needed else "Estimated",
        electrical_state="Estimated by NILM",
        energy_state="Estimated",
        current_power_w=state.estimated_power_w,
        daily_energy_kwh=state.estimated_energy_kwh_today,
        runtime_today_seconds=None,
        run_count_today=None,
        cost_today=_estimated_cost(
            state.estimated_energy_kwh_today,
            _positive_state_number(
                analyzer_state,
                "cost_current_rate_by_circuit",
                state.mains_circuit_id,
            ),
        ),
        today_vs_normal=(),
        expectations=_nilm_expectations(
            state,
            review_needed=review_needed,
            evidence_path=evidence_path,
        ),
        recent_timeline=_recent_timeline(analyzer_state, state.mains_circuit_id),
        active_alerts=_active_alert_summaries(
            analyzer_state,
            state.mains_circuit_id,
            config=None,
            assignment_id=state.assignment_id,
        ),
        next_step="Review NILM assignment" if review_needed else "No action needed",
        what_to_check_first=(
            ("Validate this estimated appliance before relying on alerts.",)
            if review_needed
            else ("Review NILM confidence before acting on appliance alerts.",)
        ),
        evidence_path=evidence_path,
        assignment_id=state.assignment_id,
        mains_source=state.mains_source,
    )


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
            "$",
            "",
            ("daily_energy_kwh", "daily_energy_usage_kwh"),
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
        comparison = _metric_comparison(
            metric_id=metric_id,
            label=label,
            unit=unit,
            current=current,
            baseline=baseline,
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
    """Return one bounded behavior expectation for a direct appliance."""
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
                expected="Issue language is suppressed while work is expected.",
                why_it_matters=(
                    "This prevents maintenance work from looking like a new fault."
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
        if _is_higher(daily):
            return (
                _expectation(
                    config,
                    title="Energy is above normal",
                    status="watch",
                    source_type=expectation_source,
                    observed=f"{config.name} energy is above normal today.",
                    expected=_normal_range_text(daily),
                    why_it_matters=(
                        "Cold appliances should cycle and return to idle."
                    ),
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

    if profile in {ApplianceProfile.HVAC, ApplianceProfile.HVAC_SYSTEM} and _is_higher(
        runtime
    ):
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
                    what_to_check_first=(
                        "No action needed unless comfort is poor.",
                    ),
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
                    what_to_check_first=("No action needed right now.",),
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
                    "Unexpected pump activity can point to water intrusion "
                    "or leaks."
                ),
                what_to_check_first=(
                    "Check for water flow, rain, or a stuck pump.",
                ),
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
            recipe[3]
            if recipe
            else ("Review recent activity and source data.",)
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
            what_to_check_first=("No action needed right now.",),
            evidence_path=evidence_path,
        ),
    )


def _nilm_expectations(
    state: NilmVirtualApplianceState,
    *,
    review_needed: bool,
    evidence_path: str,
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
    return (
        ApplianceExpectation(
            expectation_id=f"{state.assignment_id}:nilm_validation",
            circuit_id=state.mains_circuit_id,
            title=title,
            status=status,
            source_type="nilm_estimate",
            confidence=state.confidence,
            observed=observed,
            expected="Estimated appliances should be validated before fault alerts.",
            why_it_matters=(
                "NILM is an estimate from mains power, not a direct measurement."
            ),
            what_to_check_first=(first_check,),
            evidence_path=evidence_path,
        ),
    )


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
                evidence_path=_evidence_path(
                    circuit_id=circuit_id,
                    alert_id=notification_id_for_alert(alert),
                    feature=alert.feature,
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

    if metric_id == "cost_today":
        rate = _positive_state_number(state, "cost_current_rate_by_circuit", circuit_id)
        energy_baseline = _comparison_baseline(
            coordinator,
            state,
            circuit_id,
            metric_id="daily_energy_kwh",
            baseline_features=baseline_features,
        )
        if rate is None or energy_baseline is None:
            return None
        low, high, median, confidence, source = energy_baseline
        return (
            _round_money(low * rate) if low is not None else None,
            _round_money(high * rate) if high is not None else None,
            _round_money(median * rate) if median is not None else None,
            confidence,
            f"{source}_cost_estimate",
        )

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
) -> MetricComparison | None:
    if baseline is None:
        if current is None:
            return None
        return MetricComparison(
            metric_id=metric_id,
            label=label,
            unit=unit,
            current_value=current,
            normal_low=None,
            normal_high=None,
            normal_median=None,
            status="learning",
            confidence=None,
            source="current_state",
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
    )


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


def _state_number(state: Any, field: str, key: str) -> float | None:
    mapping = getattr(state, field, {})
    if not isinstance(mapping, Mapping) or key not in mapping:
        return None
    return _number_or_none(mapping.get(key))


def _positive_state_number(state: Any, field: str, key: str) -> float | None:
    value = _state_number(state, field, key)
    if value is None or value <= 0.0:
        return None
    return value


def _estimated_cost_today(state: Any, circuit_id: str) -> float | None:
    daily_kwh = _state_number(state, "daily_energy_usage_by_circuit", circuit_id)
    rate = effective_electricity_rate(
        getattr(state, "utility_cost_rate_by_circuit", {}),
        _positive_state_number(state, "cost_current_rate_by_circuit", circuit_id),
    )
    return _estimated_cost(daily_kwh, rate or None)


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


def _iter_items(value: Any) -> tuple[Any, ...]:
    if value is None or isinstance(value, str | bytes):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return ()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value
