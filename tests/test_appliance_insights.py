from __future__ import annotations

from datetime import UTC, datetime
from math import inf, nan
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer import appliance_insights
from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
    ComparisonMode,
    MetricComparison,
)
from custom_components.circuitsetup_energy_analyzer.attention import AttentionItem
from custom_components.circuitsetup_energy_analyzer.models import CircuitMode

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _comparison(
    metric_id: str,
    current: float | None,
    normal: float | None,
    confidence: float | None = 0.9,
) -> MetricComparison:
    status = (
        "missing_data"
        if current is None
        else "learning"
        if normal is None
        else "higher"
        if current > normal
        else "lower"
        if current < normal
        else "normal"
    )
    return MetricComparison(
        metric_id=metric_id,
        label=metric_id,
        unit="kWh" if metric_id == "daily_energy_kwh" else "count",
        current_value=current,
        normal_low=normal,
        normal_high=normal,
        normal_median=normal,
        status=status,
        confidence=confidence,
        source="test_baseline",
        comparison_mode=ComparisonMode.SAME_TIME_OF_DAY,
        as_of=NOW,
    )


def _detail(
    circuit_id: str = "washer",
    display_name: str = "Washer",
    *,
    appliance_key: str | None = None,
    assignment_id: str | None = None,
    source_type: str = "direct_meter",
    activity_state: str = "Idle",
    energy: tuple[float | None, float | None] = (15.0, 10.0),
    runtime: tuple[float | None, float | None] = (150.0, 100.0),
    runs: tuple[float | None, float | None] = (3.0, 2.0),
    confidence: float | None = None,
    source_status: str = "fresh",
    readiness_status: str = "ready",
    appliance_profile: str = "washer",
    expectations: tuple[SimpleNamespace, ...] = (),
    energy_confidence: float | None = 0.9,
    runtime_confidence: float | None = 0.9,
    runs_confidence: float | None = 0.9,
) -> SimpleNamespace:
    return SimpleNamespace(
        appliance_key=appliance_key or f"circuit:{circuit_id}",
        circuit_id=circuit_id,
        display_name=display_name,
        appliance_profile=appliance_profile,
        source_type=source_type,
        confidence=confidence,
        model_status="validated" if source_type == "nilm_estimate" else None,
        activity_state=activity_state,
        daily_energy_kwh=energy[0],
        today_vs_normal=(
            _comparison("daily_energy_kwh", *energy, energy_confidence),
            _comparison("runtime_today_seconds", *runtime, runtime_confidence),
            _comparison("run_count_today", *runs, runs_confidence),
        ),
        source_quality={"status": source_status, "label": source_status.title()},
        learning_readiness={
            "status": readiness_status,
            "label": readiness_status.title(),
        },
        assignment_id=assignment_id,
        mains_circuit_id="mains" if assignment_id else None,
        expectations=expectations,
        active_alerts=(),
        evidence_path=f"/evidence/{circuit_id}",
    )


@pytest.mark.parametrize(
    ("energy", "runtime", "runs", "expected"),
    [
        ((15.0, 10.0), (150.0, 100.0), (2.0, 2.0), (50.0, 0.0, 0.0)),
        ((15.0, 10.0), (100.0, 100.0), (2.0, 2.0), (0.0, 50.0, 0.0)),
        ((20.0, 10.0), (200.0, 100.0), (4.0, 2.0), (0.0, 0.0, 100.0)),
    ],
    ids=("runtime-only", "power-only", "cycle-count-only"),
)
def test_energy_change_decomposes_single_factor_changes(
    energy: tuple[float, float],
    runtime: tuple[float, float],
    runs: tuple[float, float],
    expected: tuple[float, float, float],
) -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(energy=energy, runtime=runtime, runs=runs)
    )

    assert explanation is not None
    actual = (
        explanation.runtime_contribution_percent or 0.0,
        explanation.running_power_contribution_percent or 0.0,
        explanation.cycle_count_contribution_percent or 0.0,
    )
    assert actual == pytest.approx(expected)
    assert explanation.total_change_percent == pytest.approx(
        (energy[0] / energy[1] - 1.0) * 100.0
    )


def test_energy_change_mixed_contributions_are_bounded_and_sum_to_total() -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            energy=(20.0, 10.0),
            runtime=(180.0, 100.0),
            runs=(3.0, 2.0),
        )
    )

    assert explanation is not None
    assert explanation.cycle_count_contribution_percent == pytest.approx(50.0)
    assert explanation.runtime_contribution_percent == pytest.approx(30.0)
    assert explanation.running_power_contribution_percent == pytest.approx(20.0)
    contributions = (
        explanation.runtime_contribution_percent,
        explanation.running_power_contribution_percent,
        explanation.cycle_count_contribution_percent,
        explanation.usage_event_contribution_percent,
        explanation.unexplained_percent,
    )
    assert all(
        abs(value) <= abs(explanation.total_change_percent)
        for value in contributions
        if value is not None
    )
    assert sum(value or 0.0 for value in contributions) == pytest.approx(
        explanation.total_change_percent
    )


def test_energy_change_with_opposing_factors_is_fully_unexplained() -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            energy=(11.0, 10.0),
            runtime=(50.0, 100.0),
            runs=(4.0, 2.0),
        )
    )

    assert explanation is not None
    assert explanation.total_change_percent == pytest.approx(10.0)
    assert explanation.runtime_contribution_percent is None
    assert explanation.running_power_contribution_percent is None
    assert explanation.cycle_count_contribution_percent is None
    assert explanation.unexplained_percent == pytest.approx(10.0)


def test_energy_change_requires_a_positive_normal_energy_baseline() -> None:
    assert (
        appliance_insights.energy_change_explanation(
            _detail(energy=(4.0, None))
        )
        is None
    )
    assert (
        appliance_insights.energy_change_explanation(_detail(energy=(4.0, 0.0)))
        is None
    )


@pytest.mark.parametrize("invalid", (nan, inf, -inf))
def test_energy_change_treats_non_finite_energy_as_missing(invalid: float) -> None:
    assert (
        appliance_insights.energy_change_explanation(
            _detail(energy=(invalid, 10.0))
        )
        is None
    )


def test_low_confidence_nilm_reports_change_without_claiming_causes() -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            source_type="nilm_estimate",
            assignment_id="dishwasher",
            appliance_key="nilm:dishwasher",
            confidence=0.72,
        )
    )

    assert explanation is not None
    assert explanation.total_change_percent == pytest.approx(50.0)
    assert explanation.confidence == pytest.approx(0.72)
    assert explanation.runtime_contribution_percent is None
    assert explanation.running_power_contribution_percent is None
    assert explanation.cycle_count_contribution_percent is None
    assert explanation.usage_event_contribution_percent is None
    assert explanation.unexplained_percent == pytest.approx(50.0)
    assert "estimated" in explanation.explanation.casefold()


def test_lowest_factor_confidence_suppresses_causal_breakdown() -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            source_type="nilm_estimate",
            assignment_id="dishwasher",
            appliance_key="nilm:dishwasher",
            confidence=0.95,
            energy_confidence=0.9,
            runtime_confidence=0.4,
            runs_confidence=0.8,
        )
    )

    assert explanation is not None
    assert explanation.confidence == pytest.approx(0.4)
    assert explanation.runtime_contribution_percent is None
    assert explanation.running_power_contribution_percent is None
    assert explanation.cycle_count_contribution_percent is None
    assert explanation.unexplained_percent == pytest.approx(
        explanation.total_change_percent
    )


@pytest.mark.parametrize("appliance_profile", ("hvac", "mini_split"))
def test_weather_context_is_presented_as_context_not_precise_causality(
    appliance_profile: str,
) -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            appliance_profile=appliance_profile,
            expectations=(
                SimpleNamespace(
                    expectation_id="weather_context",
                    title="Runtime fits weather context",
                    observed="Longer runtime is explained by outdoor temperature.",
                    expected="Runtime changes with weather.",
                ),
            ),
        )
    )

    assert explanation is not None
    assert (
        "outdoor-temperature context may explain"
        in explanation.explanation.casefold()
    )
    assert explanation.usage_event_contribution_percent is None


def test_mini_split_recipe_does_not_claim_weather_context() -> None:
    explanation = appliance_insights.energy_change_explanation(
        _detail(
            appliance_profile="mini_split",
            expectations=(
                SimpleNamespace(
                    expectation_id="mini_split:operation_check",
                    title="Mini-Split operation check",
                    observed="Runtime is above normal.",
                    expected="Power should modulate with outdoor temperature.",
                ),
            ),
        )
    )

    assert explanation is not None
    assert "outdoor-temperature context" not in explanation.explanation.casefold()


def _install_index_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    direct: tuple[SimpleNamespace, ...],
    nilm: tuple[SimpleNamespace, ...],
    attention: tuple[AttentionItem, ...] = (),
) -> SimpleNamespace:
    direct_by_id = {detail.circuit_id: detail for detail in direct}
    nilm_by_id = {detail.assignment_id: detail for detail in nilm}
    coordinator = SimpleNamespace(
        entry_id="entry-1",
        circuit_configs=(
            *(
                SimpleNamespace(
                    circuit_id=detail.circuit_id,
                    mode=CircuitMode.SINGLE_PHASE,
                )
                for detail in direct
            ),
            SimpleNamespace(circuit_id="mains", mode=CircuitMode.MAINS_NILM),
        ),
    )
    monkeypatch.setattr(
        appliance_insights,
        "appliance_detail_for_circuit",
        lambda _coordinator, circuit_id: direct_by_id.get(circuit_id),
    )
    monkeypatch.setattr(
        appliance_insights,
        "nilm_virtual_appliance_states",
        lambda _coordinator, published_only=False: tuple(
            SimpleNamespace(assignment_id=assignment_id)
            for assignment_id in nilm_by_id
        ),
    )
    monkeypatch.setattr(
        appliance_insights,
        "appliance_detail_for_assignment",
        lambda _coordinator, assignment_id: nilm_by_id.get(assignment_id),
    )
    monkeypatch.setattr(
        appliance_insights,
        "attention_items_for_coordinators",
        lambda _coordinators, **_kwargs: attention,
    )
    return coordinator


def test_appliance_index_lists_direct_and_nilm_with_filter_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = _detail(
        "dryer",
        "Dryer",
        energy=(11.0, 10.0),
        source_status="stale",
    )
    running = _detail(
        "hvac",
        "HVAC",
        activity_state="Running",
        energy=(12.0, 10.0),
    )
    learning = _detail(
        "fridge",
        "Refrigerator",
        energy=(14.0, 10.0),
        readiness_status="learning",
    )
    dishwasher = _detail(
        "mains",
        "Dishwasher",
        appliance_key="nilm:dishwasher",
        assignment_id="dishwasher",
        source_type="nilm_estimate",
        energy=(15.0, 10.0),
        confidence=0.9,
        source_status="estimated",
    )
    setup_attention = AttentionItem(
        item_id="circuit:dryer:data",
        appliance_key="circuit:dryer",
        display_name="Dryer",
        source_type="direct_meter",
        category="fix_setup_or_data",
        status="not_enough_data",
        reason="Source data is stale.",
        confidence=0.9,
        severity="high",
        next_step="Review source entities.",
        action_path="/detail/dryer",
        updated_at=NOW,
    )
    coordinator = _install_index_sources(
        monkeypatch,
        direct=(learning, running, setup),
        nilm=(dishwasher,),
        attention=(setup_attention,),
    )

    items = appliance_insights.appliance_insights_for_coordinators((coordinator,))
    by_key = {item.appliance_key: item.as_dict() for item in items}

    assert set(by_key) == {
        "circuit:dryer",
        "circuit:fridge",
        "circuit:hvac",
        "nilm:dishwasher",
    }
    assert by_key["circuit:dryer"]["needs_attention"] is True
    assert by_key["circuit:dryer"]["has_data_problem"] is True
    assert by_key["circuit:dryer"]["is_nilm"] is False
    assert by_key["circuit:hvac"]["is_running"] is True
    assert by_key["circuit:fridge"]["is_learning"] is True
    assert by_key["nilm:dishwasher"]["is_nilm"] is True
    assert by_key["nilm:dishwasher"]["has_data_problem"] is False


def test_appliance_index_treats_waiting_for_delta_as_learning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = _detail(
        "fridge",
        "Refrigerator",
        readiness_status="waiting_for_delta",
    )
    coordinator = _install_index_sources(
        monkeypatch,
        direct=(waiting,),
        nilm=(),
    )

    (item,) = appliance_insights.appliance_insights_for_coordinators((coordinator,))

    assert item.is_learning is True


def test_appliance_index_deduplicates_conversion_and_uses_default_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attention = _detail("dryer", "Dryer", energy=(11.0, 10.0))
    running = _detail(
        "hvac",
        "HVAC",
        activity_state="Running",
        energy=(12.0, 10.0),
    )
    largest = _detail("fridge", "Refrigerator", energy=(14.0, 10.0))
    converted = _detail(
        "washer_direct",
        "Converted Washer",
        appliance_key="nilm:converted",
        assignment_id="converted",
        source_type="direct_meter",
        energy=(13.0, 10.0),
    )
    old_nilm = _detail(
        "mains",
        "Old Washer Estimate",
        appliance_key="nilm:converted",
        assignment_id="converted",
        source_type="nilm_estimate",
        energy=(19.0, 10.0),
        confidence=0.9,
        source_status="estimated",
    )
    attention_item = AttentionItem(
        item_id="circuit:dryer:energy",
        appliance_key="circuit:dryer",
        display_name="Dryer",
        source_type="direct_meter",
        category="review_appliance_behavior",
        status="watch",
        reason="Energy is above normal.",
        confidence=0.9,
        severity="medium",
        next_step="Open appliance detail.",
        action_path="/detail/dryer",
        updated_at=NOW,
    )
    coordinator = _install_index_sources(
        monkeypatch,
        direct=(largest, converted, running, attention),
        nilm=(old_nilm,),
        attention=(attention_item,),
    )

    items = appliance_insights.appliance_insights_for_coordinators((coordinator,))

    assert [item.appliance_key for item in items] == [
        "circuit:dryer",
        "circuit:hvac",
        "circuit:fridge",
        "nilm:converted",
    ]
    converted_items = [item for item in items if item.appliance_key == "nilm:converted"]
    assert len(converted_items) == 1
    assert converted_items[0].source_type == "direct_meter"
    assert converted_items[0].display_name == "Converted Washer"


def test_direct_source_path_opens_sources_step_for_the_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    washer = _detail("washer", "Washer")
    coordinator = _install_index_sources(
        monkeypatch,
        direct=(washer,),
        nilm=(),
    )

    item = appliance_insights.appliance_insights_for_coordinators((coordinator,))[0]
    source_url = urlparse(item.source_path)

    assert source_url.path == "/config/integrations/dashboard"
    assert parse_qs(source_url.fragment) == {
        "config_entry": ["entry-1"],
        "options_step": ["sources"],
        "circuit_id": ["washer"],
    }


def test_nilm_source_path_preserves_entry_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dishwasher = _detail(
        "mains",
        "Dishwasher",
        appliance_key="nilm:assignment-dishwasher",
        assignment_id="assignment-dishwasher",
        source_type="nilm_estimate",
        confidence=0.9,
    )
    coordinator = _install_index_sources(
        monkeypatch,
        direct=(),
        nilm=(dishwasher,),
    )

    item = appliance_insights.appliance_insights_for_coordinators((coordinator,))[0]

    assert parse_qs(urlparse(item.source_path).query) == {
        "nilm_workspace": ["1"],
        "circuit_id": ["mains"],
        "assignment_id": ["assignment-dishwasher"],
        "entry_id": ["entry-1"],
    }


def test_duplicate_circuit_ids_across_entries_have_distinct_detail_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details_by_entry = {
        "entry-1": _detail("hvac", "Upstairs HVAC"),
        "entry-2": _detail("hvac", "Downstairs HVAC"),
    }
    coordinators = tuple(
        SimpleNamespace(
            entry_id=entry_id,
            circuit_configs=(
                SimpleNamespace(circuit_id="hvac", mode=CircuitMode.SINGLE_PHASE),
            ),
        )
        for entry_id in details_by_entry
    )
    monkeypatch.setattr(
        appliance_insights,
        "appliance_detail_for_circuit",
        lambda coordinator, _circuit_id: details_by_entry[coordinator.entry_id],
    )
    monkeypatch.setattr(
        appliance_insights,
        "nilm_virtual_appliance_states",
        lambda _coordinator, published_only=False: (),
    )
    monkeypatch.setattr(
        appliance_insights,
        "attention_items_for_coordinators",
        lambda _coordinators, **_kwargs: (),
    )

    items = appliance_insights.appliance_insights_for_coordinators(coordinators)

    assert {item.display_name for item in items} == {
        "Upstairs HVAC",
        "Downstairs HVAC",
    }
    assert len({item.detail_path for item in items}) == 2
    assert {
        parse_qs(urlparse(item.detail_path).query)["entry_id"][0] for item in items
    } == {"entry-1", "entry-2"}


def test_index_requests_attention_for_every_bounded_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = tuple(
        _detail(f"load-{index:02}", f"Load {index:02}")
        for index in range(1, 52)
    )
    attention = tuple(
        AttentionItem(
            item_id=f"{detail.appliance_key}:energy",
            appliance_key=detail.appliance_key,
            display_name=detail.display_name,
            source_type="direct_meter",
            category="review_appliance_behavior",
            status="watch",
            reason="Energy is above normal.",
            confidence=0.9,
            severity="medium",
            next_step="Open appliance detail.",
            action_path=f"/detail/{detail.circuit_id}",
            updated_at=NOW,
        )
        for detail in details
    )
    coordinator = _install_index_sources(
        monkeypatch,
        direct=details,
        nilm=(),
    )
    requested_limits = []

    def attention_items(_coordinators, *, limit: int = 50):
        requested_limits.append(limit)
        return attention[:limit]

    monkeypatch.setattr(
        appliance_insights,
        "attention_items_for_coordinators",
        attention_items,
    )

    items = appliance_insights.appliance_insights_for_coordinators((coordinator,))
    last = next(item for item in items if item.appliance_key == "circuit:load-51")

    assert requested_limits == [appliance_insights.MAX_APPLIANCE_INSIGHTS]
    assert last.needs_attention is True
