from __future__ import annotations

import pytest

from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
    MetricComparison,
    _nilm_expectations,
    appliance_expectations_for_circuit,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
)
from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
    NilmVirtualApplianceState,
)


def _config(
    profile: ApplianceProfile = ApplianceProfile.DRYER,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id="appliance",
        name="Test Appliance",
        appliance_profile=profile,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(),
    )


def _comparison(metric_id: str, *, label: str | None = None) -> MetricComparison:
    unit = "kWh" if metric_id == "daily_energy_kwh" else "s"
    return MetricComparison(
        metric_id=metric_id,
        label=label or metric_id,
        unit=unit,
        current_value=20.0,
        normal_low=1.0,
        normal_high=10.0,
        normal_median=5.0,
        status="higher",
        confidence=0.9,
        source="test",
    )


def _expectations(
    state: AnalyzerState,
    *comparisons: MetricComparison,
    profile: ApplianceProfile = ApplianceProfile.DRYER,
):
    config = _config(profile)
    return appliance_expectations_for_circuit(
        None,
        config,
        state,
        comparisons=tuple(comparisons),
        source_type="direct_meter",
        evidence_path="/evidence?circuit_id=appliance",
    )


def test_ranked_expectations_are_bounded_and_semantically_deduplicated() -> None:
    state = AnalyzerState()
    state.data_quality_checklist_by_circuit["appliance"] = {
        "required_sensors_present": False,
    }
    state.leg_imbalance_status_by_circuit["appliance"] = "imbalanced"

    expectations = _expectations(
        state,
        _comparison("daily_energy_kwh", label="Daily energy"),
        _comparison("daily_energy_kwh", label="Energy summary"),
        _comparison("runtime_today_seconds", label="Runtime"),
    )

    assert len(expectations) == 3
    assert expectations[0].title == "Source data needs review"
    assert expectations[1].title == "Electrical balance needs review"
    assert len({item.expectation_id for item in expectations}) == len(expectations)
    assert sum("energy" in item.title.casefold() for item in expectations) <= 1


def test_data_quality_outranks_behavior_watch() -> None:
    state = AnalyzerState()
    state.data_quality_checklist_by_circuit["appliance"] = {
        "numeric_states_valid": False,
    }

    expectations = _expectations(state, _comparison("runtime_today_seconds"))

    assert expectations[0].title == "Source data needs review"
    assert expectations[1].status == "watch"
    assert "runtime" in expectations[1].title.casefold()


def test_electrical_issue_outranks_energy_and_runtime_watches() -> None:
    state = AnalyzerState()
    state.leg_imbalance_status_by_circuit["appliance"] = "imbalanced"

    expectations = _expectations(
        state,
        _comparison("daily_energy_kwh"),
        _comparison("runtime_today_seconds"),
    )

    assert expectations[0].title == "Electrical balance needs review"
    assert any(item.status == "watch" for item in expectations[1:])


def test_nilm_validation_outranks_low_priority_energy_watch() -> None:
    state = NilmVirtualApplianceState(
        appliance_id="dishwasher",
        assignment_id="assignment-dishwasher",
        display_name="Dishwasher",
        is_running=False,
        estimated_power_w=0.0,
        estimated_energy_kwh_today=2.0,
        confidence=0.86,
        last_seen=None,
        active_signature_id=None,
        active_session_id=None,
        latest_session_id=None,
        model_status="conflict",
        mains_circuit_id="mains",
    )

    expectations = _nilm_expectations(
        state,
        review_needed=True,
        evidence_path="/evidence?assignment_id=assignment-dishwasher",
        comparisons=(_comparison("daily_energy_kwh"),),
    )

    assert expectations[0].title == "NILM assignment needs validation"
    assert expectations[1].status == "watch"
    assert "energy" in expectations[1].title.casefold()


@pytest.mark.parametrize(
    ("profile", "state_field", "status", "expected_title"),
    [
        (
            ApplianceProfile.HVAC,
            "weather_context_by_circuit",
            "weather_correlated",
            "Runtime fits weather context",
        ),
        (
            ApplianceProfile.HEAT_PUMP,
            "weather_context_by_circuit",
            "weather_correlated",
            "Runtime fits weather context",
        ),
        (
            ApplianceProfile.SUMP_PUMP,
            "rain_pump_context_by_circuit",
            "rain_explained",
            "Pump activity fits rain context",
        ),
    ],
)
def test_expected_context_is_shown_when_no_issue_is_active(
    profile: ApplianceProfile,
    state_field: str,
    status: str,
    expected_title: str,
) -> None:
    state = AnalyzerState()
    getattr(state, state_field)["appliance"] = {"status": status}

    expectations = _expectations(
        state,
        _comparison("runtime_today_seconds"),
        profile=profile,
    )

    assert expectations[0].title == expected_title
    assert expectations[0].status == "expected"


def test_maintenance_suppresses_appliance_fault_wording() -> None:
    state = AnalyzerState()
    state.maintenance_by_circuit["appliance"] = {"active": True}
    state.leg_imbalance_status_by_circuit["appliance"] = "imbalanced"

    expectations = _expectations(
        state,
        _comparison("daily_energy_kwh"),
        _comparison("runtime_today_seconds"),
    )

    assert [item.title for item in expectations] == ["Maintenance mode active"]
    wording = " ".join(
        (
            expectations[0].title,
            expectations[0].observed,
            expectations[0].expected,
            expectations[0].why_it_matters,
        )
    ).casefold()
    assert "fault" not in wording
    assert "issue" not in wording


def test_maintenance_keeps_blocking_source_data_finding() -> None:
    state = AnalyzerState()
    state.maintenance_by_circuit["appliance"] = {"active": True}
    state.data_quality_checklist_by_circuit["appliance"] = {
        "source_data_fresh": False,
    }

    expectations = _expectations(state)

    assert [item.title for item in expectations] == [
        "Source data needs review",
        "Maintenance mode active",
    ]
