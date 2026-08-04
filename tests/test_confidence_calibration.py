from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from custom_components.circuitsetup_energy_analyzer.models import EventType
from custom_components.circuitsetup_energy_analyzer.profiles import nilm_source_kind
from tests.helpers.calibration import (
    CALIBRATION_CONFIDENCE_BINS,
    CalibrationFixtureError,
    assert_fixture_expectations,
    evaluate_replay_result,
    load_calibration_fixture,
    load_calibration_scenarios,
    replay_fixture_processors,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "calibration"


def test_mixed_fixture_parser_expands_scenarios_and_entry_blocks(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "mixed.yaml"
    fixture_path.write_text(
        """schema_version: 1
id: mixed
description: mixed scenarios
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
scenarios:
  - id: one
    source_kind: pure_mixed
    circuits:
      - circuit_id: mixed
        name: Mixed
        appliance_profile: mixed
        circuit_mode: mixed
        sources: {power: sensor.mixed}
    assignments:
      mixed:
        - assignment_id: pump
          lifecycle_state: validated
          power_states_w: [0, 80]
          transition_prototypes: []
    samples: [{t: 0, states: {sensor.mixed: 0}}]
    labels: {}
    calibration_expectations: {}
  - id: isolated
    source_kind: mains
    min_delta_w: 20
    entries:
      - entry_id: first
        circuits:
          - circuit_id: shared
            name: First
            appliance_profile: mains_nilm
            circuit_mode: mains_nilm
            sources: {power: sensor.first}
        assignments:
          shared:
            - assignment_id: first_load
              lifecycle_state: validated
              power_states_w: [0, 80]
              model_confidence: 0.9
              transition_prototypes: &first_transitions
                - {direction: "on", delta_w: 80, spread_w: 2, sample_count: 3}
                - {direction: "off", delta_w: -80, spread_w: 2, sample_count: 3}
        samples:
          - {t: 0, states: {sensor.first: 0}}
          - {t: 10, states: {sensor.first: 80}}
          - {t: 20, states: {sensor.first: 80}}
          - {t: 30, states: {sensor.first: 80}}
          - {t: 40, states: {sensor.first: 0}}
          - {t: 50, states: {sensor.first: 0}}
      - entry_id: second
        circuits:
          - circuit_id: shared
            name: Second
            appliance_profile: mains_nilm
            circuit_mode: mains_nilm
            sources: {power: sensor.second}
        assignments:
          shared:
            - assignment_id: second_load
              lifecycle_state: validated
              power_states_w: [0, 120]
              model_confidence: 0.9
              transition_prototypes:
                - {direction: "on", delta_w: 120, spread_w: 2, sample_count: 3}
                - {direction: "off", delta_w: -120, spread_w: 2, sample_count: 3}
        samples:
          - {t: 0, states: {sensor.second: 0}}
          - {t: 10, states: {sensor.second: 120}}
          - {t: 20, states: {sensor.second: 120}}
          - {t: 30, states: {sensor.second: 120}}
          - {t: 40, states: {sensor.second: 0}}
          - {t: 50, states: {sensor.second: 0}}
    labels: {}
    calibration_expectations: {}
labels: {}
calibration_expectations: {}
""",
        encoding="utf-8",
    )

    scenarios = load_calibration_scenarios(fixture_path)

    assert [scenario.id for scenario in scenarios] == [
        "mixed.one",
        "mixed.isolated.first",
        "mixed.isolated.second",
    ]
    assert scenarios[0].assignments_by_circuit["mixed"][0]["assignment_id"] == "pump"
    assert [scenario.entry_id for scenario in scenarios[1:]] == ["first", "second"]
    assert scenarios[1].circuits[0].circuit_id == scenarios[2].circuits[0].circuit_id
    assert scenarios[1].circuits[0].sensors != scenarios[2].circuits[0].sensors
    first_result, second_result = map(replay_fixture_processors, scenarios[1:])
    assert first_result.store_data is not second_result.store_data
    first_runtime = first_result.final_state.nilm_component_runtime_by_circuit
    second_runtime = second_result.final_state.nilm_component_runtime_by_circuit
    assert set(first_runtime["shared"]) == {"first_load"}
    assert set(second_runtime["shared"]) == {"second_load"}
    assert "second_load" not in str(first_result.store_data)
    assert "first_load" not in str(second_result.store_data)


@pytest.mark.parametrize(
    "scenario_ids",
    [("''", "valid"), ("duplicate", "duplicate")],
)
def test_mixed_fixture_rejects_empty_or_duplicate_scenario_ids(
    tmp_path: Path, scenario_ids: tuple[str, str]
) -> None:
    first, second = scenario_ids
    path = tmp_path / "invalid.yaml"
    path.write_text(
        f"""schema_version: 1
id: invalid
description: invalid ids
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
scenarios:
  - id: {first}
  - id: {second}
labels: {{}}
calibration_expectations: {{}}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scenario IDs must be nonempty and unique"):
        load_calibration_scenarios(path)


@pytest.mark.parametrize(
    "entry_ids",
    [("''", "valid"), ("duplicate", "duplicate")],
)
def test_mixed_fixture_rejects_empty_or_duplicate_entry_ids(
    tmp_path: Path, entry_ids: tuple[str, str]
) -> None:
    first, second = entry_ids
    path = tmp_path / "invalid.yaml"
    path.write_text(
        f"""schema_version: 1
id: invalid
description: invalid ids
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
scenarios:
  - id: isolation
    entries:
      - entry_id: {first}
      - entry_id: {second}
    labels: {{}}
    calibration_expectations: {{}}
labels: {{}}
calibration_expectations: {{}}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entry IDs must be nonempty and unique"):
        load_calibration_scenarios(path)


def test_mixed_replay_seeds_models_and_runs_production_source_classifier(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "mixed.yaml"
    fixture_path.write_text(
        """schema_version: 1
id: mixed_replay
description: mixed replay
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
source_kind: pure_mixed
min_delta_w: 20
circuits:
  - circuit_id: mixed
    name: Mixed
    appliance_profile: mixed
    circuit_mode: mixed
    sources: {power: sensor.mixed}
assignments:
  mixed:
    - assignment_id: pump
      lifecycle_state: validated
      power_states_w: [0, 80]
      model_confidence: 0.9
      transition_prototypes:
        - direction: "on"
          from_state_w: 0
          to_state_w: 80
          delta_w: 80
          spread_w: 2
          sample_count: 3
        - direction: "off"
          from_state_w: 80
          to_state_w: 0
          delta_w: -80
          spread_w: 2
          sample_count: 3
samples:
  - {t: 0, states: {sensor.mixed: 0}}
  - {t: 10, states: {sensor.mixed: 80}}
  - {t: 20, states: {sensor.mixed: 80}}
  - {t: 30, states: {sensor.mixed: 80}}
  - {t: 40, states: {sensor.mixed: 0}}
  - {t: 50, states: {sensor.mixed: 0}}
  - {t: 60, states: {sensor.mixed: 0}}
labels:
  component_truth:
    pump:
      edges:
        - {event_type: start, around_t: 10, tolerance_seconds: 0}
        - {event_type: stop, around_t: 40, tolerance_seconds: 0}
      sessions: [{start_t: 10, end_t: 40, tolerance_seconds: 0}]
      energy_kwh: 0.000667
calibration_expectations: {}
""",
        encoding="utf-8",
    )

    fixture = load_calibration_fixture(fixture_path)
    result = replay_fixture_processors(fixture)

    assert (
        result.store_data.nilm_session_history_by_circuit["mixed"][0]["assignment_id"]
        == "pump"
    )
    assert result.metrics is not None
    assert result.metrics.component_metrics["pump"].session_f1 == 1.0
    assert result.metrics.component_metrics["pump"].median_stop_error_seconds == 0.0
    energy_error = result.metrics.component_metrics["pump"].energy_absolute_error_kwh
    assert energy_error == pytest.approx(0.0, abs=0.000001)
    runtime = result.final_state.nilm_component_runtime_by_circuit["mixed"]["pump"]
    reconciliation = result.final_state.nilm_reconciliation_by_circuit["mixed"]
    assert runtime["status"] == "off"
    assert reconciliation["conflict"] is None
    assert reconciliation["source_power_w"] == pytest.approx(
        reconciliation["standby_w"]
        + reconciliation["allocated_power_w"]
        + reconciliation["residual_w"]
    )


@pytest.mark.parametrize(
    ("scenario_name", "source_kind"),
    [
        ("pure_mixed", "pure_mixed"),
        ("primary_unrelated_pump", "primary_mixed"),
        ("pump_starts_while_blower_on", "pure_mixed"),
        ("blower_starts_while_pump_on", "pure_mixed"),
        ("learned_compound_edge", "pure_mixed"),
        ("ambiguous_equal_power", "pure_mixed"),
        ("over_allocation_rejected", "pure_mixed"),
        ("restart_unknown", "pure_mixed"),
    ],
)
def test_independent_mixed_replay_scenarios(
    scenario_name: str,
    source_kind: str,
) -> None:
    scenarios = {
        fixture.id.rsplit(".", 1)[-1]: fixture
        for fixture in load_calibration_scenarios(
            FIXTURE_DIR / "nilm_mixed_independent.yaml"
        )
    }

    assert set(scenarios) == {
        "pure_mixed",
        "primary_unrelated_pump",
        "pump_starts_while_blower_on",
        "blower_starts_while_pump_on",
        "learned_compound_edge",
        "ambiguous_equal_power",
        "over_allocation_rejected",
        "restart_unknown",
    }
    fixture = scenarios[scenario_name]
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)

    assert fixture.source_kind == source_kind
    reconciliation = result.final_state.nilm_reconciliation_by_circuit["mixed"]
    assert reconciliation["source_power_w"] == pytest.approx(
        reconciliation["standby_w"]
        + reconciliation["allocated_power_w"]
        + reconciliation["residual_w"]
    )
    if scenario_name in {
        "pure_mixed",
        "primary_unrelated_pump",
        "pump_starts_while_blower_on",
        "blower_starts_while_pump_on",
        "learned_compound_edge",
    }:
        assert all(
            component.session_f1 == 1.0
            and component.edge_precision == 1.0
            and component.edge_recall == 1.0
            and component.energy_absolute_error_kwh
            == pytest.approx(0.0, abs=0.000001)
            for component in metrics.component_metrics.values()
        )
        assert metrics.residual_energy_kwh == pytest.approx(0.0)
        assert metrics.conservation_violations == 0
    elif scenario_name == "ambiguous_equal_power":
        runtime = result.final_state.nilm_component_runtime_by_circuit["mixed"]
        assert all(component["status"] == "off" for component in runtime.values())
        assert not result.store_data.nilm_session_history_by_circuit.get("mixed")
        assert reconciliation["allocated_power_w"] == 0
        assert reconciliation["residual_w"] == 80
        assert metrics.ambiguous_event_rate == 1.0
    elif scenario_name == "over_allocation_rejected":
        reconciliations = [
            snapshot["nilm_reconciliation_by_circuit"].get("mixed", {})
            for snapshot in result.state_snapshots
        ]
        conflict_index = next(
            index
            for index, item in enumerate(reconciliations)
            if item.get("conflict") == "over_allocation"
        )
        assert metrics.conservation_violations == 1
        assert metrics.ambiguous_event_rate == 0.0
        assert reconciliations[conflict_index]["energy_allocation_allowed"] is False
        assert reconciliations[conflict_index]["component_energy_kwh"] == pytest.approx(
            reconciliations[conflict_index - 1]["component_energy_kwh"]
        )
        assert reconciliation["conflict"] is None
        assert reconciliation["conservation_violations"] == 1
        component_energy = [
            item["component_energy_kwh"] for item in reconciliations if item
        ]
        assert component_energy == sorted(component_energy)
        assert component_energy[-1] == pytest.approx(
            reconciliations[conflict_index]["component_energy_kwh"]
        )
        assert not result.store_data.nilm_session_history_by_circuit.get("mixed")
    else:
        restart_index = next(
            index
            for index, sample in enumerate(fixture.samples)
            if sample.restart_before_sample
        )
        before_restart = result.state_snapshots[restart_index - 1]
        after_restart = result.state_snapshots[restart_index]
        first_reconciliation = result.state_snapshots[0][
            "nilm_reconciliation_by_circuit"
        ]["mixed"]
        first_runtime = result.state_snapshots[0][
            "nilm_component_runtime_by_circuit"
        ]["mixed"]
        assert first_reconciliation["conflict"] == "source_unavailable"
        assert all(
            component["status"] == "unknown" for component in first_runtime.values()
        )
        assert after_restart["state_id"] != before_restart["state_id"]
        assert after_restart["nilm_processor_id"] != before_restart[
            "nilm_processor_id"
        ]
        assert after_restart["store_id"] == before_restart["store_id"]
        assert after_restart["store_id"] == id(result.store_data)
        assert [
            item["assignment_id"]
            for item in result.store_data.nilm_appliance_assignments_by_circuit[
                "mixed"
            ]
        ] == ["restored_a", "restored_b"]
        runtime = result.final_state.nilm_component_runtime_by_circuit["mixed"]
        assert all(component["status"] == "unknown" for component in runtime.values())
        assert reconciliation["allocated_power_w"] == 0
        assert reconciliation["residual_w"] == 80

    if scenario_name == "learned_compound_edge":
        assert all(
            prototype["sample_count"] >= 3
            for assignment in fixture.assignments_by_circuit["mixed"]
            for prototype in assignment["transition_prototypes"]
        )
    if scenario_name == "primary_unrelated_pump":
        assignments = fixture.assignments_by_circuit["mixed"]
        assert assignments[0]["assignment_id"] == "mixed-configured-primary"
        assert assignments[0]["role"] == "primary"
        assert assignments[1]["assignment_id"] == "pump"


def test_helper_association_rate_uses_completed_session_evidence() -> None:
    fixture = load_calibration_scenarios(
        FIXTURE_DIR / "nilm_mixed_helpers.yaml"
    )[0]
    result = replay_fixture_processors(fixture)
    session = result.store_data.nilm_session_history_by_circuit["mixed"][0]

    assert result.metrics is not None
    assert result.metrics.false_helper_association_rate == 0.0
    session["helper_evidence"] = [{
        "helper_circuit_id": "wrong-helper",
        "relationship": "corroborates",
        "status": "confirmed",
    }]

    from tests.helpers.calibration import evaluate_replay_result

    assert evaluate_replay_result(
        fixture, result
    ).false_helper_association_rate == 1.0

    session["helper_evidence"] = fixture.assignments_by_circuit["mixed"][0][
        "helper_links"
    ][:1]
    result.store_data.nilm_session_history_by_circuit["mixed"].append(dict(session))
    assert evaluate_replay_result(
        fixture, result
    ).false_helper_association_rate == 0.5


def test_mixed_helper_replay_scenarios() -> None:
    scenarios = load_calibration_scenarios(
        FIXTURE_DIR / "nilm_mixed_helpers.yaml"
    )

    assert len(scenarios) == 4
    assert all(
        scenario.source_kind
        == nilm_source_kind(
            next(c for c in scenario.circuits if c.circuit_id == "mixed")
        ).value
        for scenario in scenarios
    )
    for fixture in scenarios:
        result = replay_fixture_processors(fixture)
        metrics = assert_fixture_expectations(fixture, result)
        assert not any(
            alert.feature.startswith(("electrical_", "control_"))
            for alert in result.alerts
        )
        if fixture.id.endswith((
            "helper_timing_drift",
            "direct_component_counted_once",
        )):
            assert metrics.false_helper_association_rate is None
        else:
            assert metrics.false_helper_association_rate == 0.0
        assert metrics.conservation_violations == 0

        if fixture.id.endswith("helper_unavailable_return"):
            sessions = result.store_data.nilm_session_history_by_circuit["mixed"]
            assert len(sessions) == 2
            unavailable, recovered = sorted(sessions, key=lambda item: item["start"])
            assert unavailable["helper_evidence"] == []
            assert recovered["helper_evidence"][0]["helper_circuit_id"] == "ac2"
            component = metrics.component_metrics["blower"]
            assert component.session_f1 == 1.0
            assert component.edge_precision == component.edge_recall == 1.0
            assert component.energy_absolute_error_kwh == pytest.approx(0.0)
            assert metrics.residual_energy_kwh == pytest.approx(0.0)
        elif fixture.id.endswith("helper_timing_drift"):
            assert not result.store_data.nilm_session_history_by_circuit.get("mixed")
        elif fixture.id.endswith("ac2_distinct_lag_disambiguates"):
            sessions = result.store_data.nilm_session_history_by_circuit["mixed"]
            assert [item["assignment_id"] for item in sessions] == ["blower"]
            assert metrics.component_metrics["blower"].session_f1 == 1.0

    direct = replay_fixture_processors(scenarios[-1])
    sessions = direct.store_data.nilm_session_history_by_circuit["mixed"]
    assert len(sessions) == 1
    assert sessions[0]["helper_evidence"][0]["relationship"] == "direct_component"
    assert direct.metrics is not None
    assert direct.metrics.component_metrics["pump"].session_f1 == 1.0
    assert direct.metrics.component_metrics["pump"].energy_absolute_error_kwh == 0.0
    assert all(
        snapshot["nilm_reconciliation_by_circuit"]["mixed"][
            "conservation_violations"
        ]
        == 0
        for snapshot in direct.state_snapshots
    )


def test_mixed_compatibility_replays_are_isolated_and_reported() -> None:
    from scripts.calibrate_confidence import build_markdown_report, run_calibration

    fixture_path = FIXTURE_DIR / "nilm_mixed_compatibility.yaml"
    raw = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    fixtures = load_calibration_scenarios(fixture_path)

    assert len(raw["scenarios"]) == 2
    assert [fixture.id for fixture in fixtures] == [
        "nilm_mixed_compatibility.legacy_mixed_encoding",
        "nilm_mixed_compatibility.shared_circuit_entries.pure_entry",
        "nilm_mixed_compatibility.shared_circuit_entries.primary_entry",
    ]
    assert [fixture.source_kind for fixture in fixtures] == [
        "pure_mixed",
        "pure_mixed",
        "primary_mixed",
    ]
    assert fixtures[0].circuits[0].appliance_profile.value == "mixed"
    assert fixtures[0].circuits[0].mode.value == "single_phase"
    assert all(
        nilm_source_kind(fixture.circuits[0]).value == fixture.source_kind
        for fixture in fixtures
    )

    pure_entry, primary_entry = fixtures[1:]
    assert pure_entry.entry_id == "pure_entry"
    assert primary_entry.entry_id == "primary_entry"
    assert pure_entry.circuits[0].circuit_id == "shared"
    assert primary_entry.circuits[0].circuit_id == "shared"
    assert pure_entry.circuits[0].sensors != primary_entry.circuits[0].sensors

    results = [replay_fixture_processors(fixture) for fixture in fixtures]
    assert len({id(result.final_state) for result in results}) == 3
    assert len({id(result.store_data) for result in results}) == 3

    expected_assignments = ["legacy_load", "pure_load", "primary_load"]
    for fixture, result, assignment_id in zip(
        fixtures, results, expected_assignments, strict=True
    ):
        circuit_id = fixture.circuits[0].circuit_id
        runtime = result.final_state.nilm_component_runtime_by_circuit[circuit_id]
        assert set(runtime) == {assignment_id}
        assert [
            item["assignment_id"]
            for item in result.store_data.nilm_appliance_assignments_by_circuit[
                circuit_id
            ]
        ] == [assignment_id]
        assert [
            item["assignment_id"]
            for item in result.store_data.nilm_session_history_by_circuit[circuit_id]
        ] == [assignment_id]

    pure_result, primary_result = results[1:]
    pure_runtime = pure_result.final_state.nilm_component_runtime_by_circuit["shared"]
    primary_runtime = primary_result.final_state.nilm_component_runtime_by_circuit[
        "shared"
    ]
    assert "primary_load" not in pure_runtime
    assert "pure_load" not in primary_runtime
    assert {
        item["assignment_id"]
        for item in pure_result.store_data.nilm_session_history_by_circuit["shared"]
    } == {"pure_load"}
    assert {
        item["assignment_id"]
        for item in primary_result.store_data.nilm_session_history_by_circuit["shared"]
    } == {"primary_load"}

    metrics = run_calibration(
        FIXTURE_DIR, fixture_name="nilm_mixed_compatibility"
    )
    report = build_markdown_report(
        metrics, generated_at=datetime(2026, 8, 3, tzinfo=UTC)
    )
    assert len(metrics) == 3
    assert len({metric.fixture_id for metric in metrics}) == 3
    assert [metric.source_kind for metric in metrics] == [
        "pure_mixed",
        "pure_mixed",
        "primary_mixed",
    ]
    assert "| Fixtures | 3 |" in report
    assert (
        "| nilm_mixed_compatibility.legacy_mixed_encoding | pure_mixed | "
        "legacy_load |"
    ) in report
    assert (
        "| nilm_mixed_compatibility.shared_circuit_entries.pure_entry | "
        "pure_mixed | pure_load |"
    ) in report
    assert (
        "| nilm_mixed_compatibility.shared_circuit_entries.primary_entry | "
        "primary_mixed | primary_load |"
    ) in report


def test_calibration_fixture_loader_expands_compact_segments() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_refrigerator_week.yaml")

    assert fixture.schema_version == 1
    assert fixture.id == "normal_refrigerator_week"
    assert fixture.circuits[0].circuit_id == "refrigerator"
    assert fixture.circuits[0].name == "Refrigerator"
    assert fixture.samples[0].timestamp == datetime(
        2026,
        1,
        1,
        0,
        0,
        tzinfo=UTC,
    )
    assert fixture.samples[-1].states["sensor.refrigerator_energy"] == pytest.approx(
        110.0
    )
    assert len(fixture.samples) == 15


def test_nilm_signal_integrity_fixture_replays_optional_and_w_only_signatures() -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "nilm_signal_integrity.yaml"
    )
    result = replay_fixture_processors(fixture)

    mixed_on = [
        signature
        for signature in result.store_data.nilm_signatures["mixed"]
        if signature["signature_id"].startswith("on-")
    ]
    assert {signature["median_delta_var"] for signature in mixed_on} == {40.0, 160.0}

    w_only = result.store_data.nilm_signatures["w_only"]
    assert w_only
    assert all(
        signature[field] is None
        for signature in w_only
        for field in ("median_delta_var", "median_delta_va", "median_delta_pf")
    )


def test_nilm_multi_state_fixture_attributes_two_appliances_across_three_states(
) -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "nilm_multi_state_components.yaml"
    )
    result = replay_fixture_processors(fixture)

    reconciliation = result.final_state.nilm_reconciliation_by_circuit["hvac_2"]
    assert reconciliation["conflict"] is None
    assert reconciliation["component_energy_kwh"] == pytest.approx(
        reconciliation["source_energy_kwh"]
    )
    runtime = result.final_state.nilm_component_runtime_by_circuit["hvac_2"]
    assert set(runtime) == {"blower", "pump"}
    assert {item["status"] for item in runtime.values()} == {"off"}
    sessions = result.store_data.nilm_session_history_by_circuit["hvac_2"]
    assert {item["assignment_id"] for item in sessions} == {"blower", "pump"}


@pytest.mark.parametrize(
    "fixture_name",
    [
        "normal_refrigerator_week",
        "refrigerator_cycle_signature_change",
        "refrigerator_energy_drift",
        "normal_washer_cycle",
        "normal_dishwasher_cycle",
        "normal_microwave_cycle",
        "normal_kettle_cycle",
        "normal_sump_pump_cycle",
        "normal_solar_overlap_cycle",
        "normal_overlapping_unknown_loads",
        "normal_direct_meter_validation",
        "normal_ev_charger_session",
        "normal_dryer_heat_cycle",
        "refrigerator_non_finite_power",
        "refrigerator_stale_power",
        "hvac_voltage_sag",
    ],
)
def test_calibration_fixture_replay_meets_expectations(fixture_name: str) -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / f"{fixture_name}.yaml")
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)

    assert metrics.fixture_id == fixture_name
    assert set(metrics.confidence_bins) == set(CALIBRATION_CONFIDENCE_BINS)


def test_normal_fixture_has_no_false_positive_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_refrigerator_week.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)

    assert result.alerts == []
    assert metrics.false_positive_alerts == 0
    assert metrics.true_negative_windows == 1


def test_abnormal_fixture_detects_expected_alert_with_latency() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)

    assert [alert.feature for alert in result.alerts] == ["daily_energy_usage_spike"]
    assert metrics.true_positive_alerts == 1
    assert metrics.false_negative_alerts == 0
    assert metrics.detection_latency_seconds == 172800.0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_washer_fixture_exercises_pause_without_split_cycle() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_washer_cycle.yaml")
    pause_samples = [
        sample
        for sample in fixture.samples
        if 60 < sample.t < 300
        and float(sample.states.get("sensor.washer_power", 0.0)) < 8.0
    ]

    result = replay_fixture_processors(fixture)
    event_types = [
        event.event_type for event in result.events if event.circuit_id == "washer"
    ]

    assert pause_samples
    assert event_types == [EventType.START, EventType.STOP]


def test_dishwasher_fixture_exercises_wash_and_dry_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_dishwasher_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    events = [event for event in result.events if event.circuit_id == "dishwasher"]

    assert fixture.circuits[0].circuit_id == "dishwasher"
    assert fixture.circuits[0].name == "Dishwasher"
    assert [event.event_type for event in events] == [EventType.START, EventType.STOP]
    assert [
        int((event.timestamp - fixture.start_time).total_seconds()) for event in events
    ] == [60, 3600]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_microwave_fixture_exercises_short_heat_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_microwave_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "microwave"
    ]

    assert fixture.circuits[0].appliance_profile == "microwave"
    assert event_offsets == [60, 180]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_kettle_fixture_exercises_short_resistive_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_kettle_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "kettle"
    ]

    assert fixture.circuits[0].name == "Kettle"
    assert fixture.circuits[0].appliance_profile == "resistive_load"
    assert event_offsets == [60, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_sump_pump_fixture_exercises_short_pump_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_sump_pump_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "sump_pump"
    ]

    assert fixture.circuits[0].appliance_profile == "sump_pump"
    assert event_offsets == [60, 180]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_solar_overlap_fixture_exercises_load_and_generation_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_solar_overlap_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    events_by_circuit = {
        circuit_id: [
            int((event.timestamp - fixture.start_time).total_seconds())
            for event in result.events
            if event.circuit_id == circuit_id
        ]
        for circuit_id in ("kettle", "rooftop_solar")
    }

    assert [circuit.name for circuit in fixture.circuits] == ["Kettle", "Rooftop Solar"]
    assert events_by_circuit == {"kettle": [60, 240], "rooftop_solar": [60, 300]}
    assert result.alerts == []
    assert result.setup_issues == []
    assert metrics.false_positive_alerts == 0


def test_overlapping_unknown_load_fixture_reconstructs_nilm_sessions() -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "normal_overlapping_unknown_loads.yaml"
    )
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)
    sessions = result.store_data.nilm_session_history_by_circuit["mains"]
    overlapping_sessions = [
        session
        for session in sessions
        if session.get("end") is not None and session.get("overlap_count") == 1
    ]

    assert len(result.nilm_signatures) >= 4
    signature_watts = {
        round(abs(signature["median_delta_w"])) for signature in result.nilm_signatures
    }

    assert signature_watts >= {
        450,
        800,
    }
    assert {
        round(float(session["median_power_w"]) / 50.0) * 50
        for session in overlapping_sessions
    } >= {450, 800}
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_direct_meter_validation_fixture_masks_known_load_from_nilm() -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "normal_direct_meter_validation.yaml"
    )
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)
    dishwasher_events = [
        event.event_type for event in result.events if event.circuit_id == "dishwasher"
    ]

    assert dishwasher_events == [
        EventType.START,
        EventType.STOP,
        EventType.START,
        EventType.STOP,
        EventType.START,
        EventType.STOP,
    ]
    assert result.nilm_signatures == []
    assert result.store_data.nilm_session_history_by_circuit.get("mains", []) == []
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_ev_charger_fixture_exercises_long_session_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_ev_charger_session.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_types = [
        event.event_type for event in result.events if event.circuit_id == "ev_charger"
    ]
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "ev_charger"
    ]

    assert fixture.circuits[0].appliance_profile == "ev_charger"
    assert fixture.circuits[0].mode == "dual_phase"
    assert event_types == [EventType.START, EventType.STOP]
    assert event_offsets == [60, 3660]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_dryer_fixture_exercises_heat_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_dryer_heat_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_types = [
        event.event_type for event in result.events if event.circuit_id == "dryer"
    ]
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "dryer"
    ]

    assert fixture.circuits[0].appliance_profile == "dryer"
    assert fixture.circuits[0].mode == "dual_phase"
    assert event_types == [EventType.START, EventType.STOP]
    assert event_offsets == [60, 3660]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_non_finite_fixture_records_quality_issue_without_alerts() -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "refrigerator_non_finite_power.yaml"
    )
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "refrigerator_non_finite"
    ]

    assert result.setup_issues == [
        {
            "timestamp": fixture.start_time.isoformat(),
            "circuit_id": "refrigerator_non_finite",
            "issue": "sensor.refrigerator_non_finite_power non_finite",
        }
    ]
    assert event_offsets == [120, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_stale_numeric_fixture_records_quality_issue_and_recovers() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_stale_power.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "refrigerator_stale"
    ]

    assert result.setup_issues == [
        {
            "timestamp": (fixture.start_time + timedelta(seconds=60)).isoformat(),
            "circuit_id": "refrigerator_stale",
            "issue": "sensor.refrigerator_stale_power stale",
        }
    ]
    assert event_offsets == [120, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_voltage_sag_fixture_emits_power_quality_event_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "hvac_voltage_sag.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    events = [event for event in result.events if event.circuit_id == "hvac"]

    assert [event.event_type for event in events] == [
        EventType.START,
        EventType.VOLTAGE_SAG,
        EventType.STOP,
    ]
    assert [
        int((event.timestamp - fixture.start_time).total_seconds()) for event in events
    ] == [60, 180, 300]
    assert events[1].features["voltage"] == pytest.approx(220.0)
    assert events[1].features["nominal_voltage"] == pytest.approx(240.0)
    assert events[1].features["real_power_w"] == pytest.approx(3600.0)
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_duplicate_expected_feature_alert_counts_as_false_positive() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    result.alerts.append(result.alerts[0])

    metrics = evaluate_replay_result(fixture, result)

    assert metrics.true_positive_alerts == 1
    assert metrics.false_positive_alerts == 1
    assert metrics.precision == 0.5


def test_out_of_window_expected_feature_alert_counts_as_false_positive() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    expected = fixture.labels.expected_alerts[0]
    result.alerts.append(
        replace(
            result.alerts[0],
            timestamp=fixture.start_time + timedelta(seconds=expected.latest_t + 60),
        )
    )

    metrics = evaluate_replay_result(fixture, result)

    assert metrics.true_positive_alerts == 1
    assert metrics.false_positive_alerts == 1
    assert metrics.precision == 0.5


def test_calibration_report_markdown_lists_fixture_metrics() -> None:
    from scripts.calibrate_confidence import build_markdown_report, run_calibration

    metrics = run_calibration(FIXTURE_DIR)
    report = build_markdown_report(
        metrics,
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
    )

    assert "# Confidence Calibration Report" in report
    assert "| Fixtures | 33 |" in report
    assert "normal_refrigerator_week" in report
    assert "refrigerator_cycle_signature_change" in report
    assert "refrigerator_energy_drift" in report
    assert "normal_washer_cycle" in report
    assert "normal_dishwasher_cycle" in report
    assert "normal_microwave_cycle" in report
    assert "normal_kettle_cycle" in report
    assert "normal_sump_pump_cycle" in report
    assert "normal_solar_overlap_cycle" in report
    assert "normal_overlapping_unknown_loads" in report
    assert "normal_direct_meter_validation" in report
    assert "normal_ev_charger_session" in report
    assert "normal_dryer_heat_cycle" in report
    assert "refrigerator_non_finite_power" in report
    assert "refrigerator_stale_power" in report
    assert "hvac_voltage_sag" in report
    assert "nilm_mixed_compatibility.legacy_mixed_encoding" in report
    assert "nilm_mixed_helpers.ac2_distinct_lag_disambiguates" in report
    assert "Helper FP rate" in report


def test_calibration_report_script_runs_directly() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/calibrate_confidence.py",
            "--fixtures",
            str(FIXTURE_DIR),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "# Confidence Calibration Report" in completed.stdout


def test_component_truth_is_optional_and_evaluates_reconciliation_metrics(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "mixed.yaml"
    fixture_path.write_text(
        """schema_version: 1
id: mixed_metrics
description: component metric contract
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
source_kind: pure_mixed
circuits:
  - circuit_id: mixed
    name: Mixed
    appliance_profile: mixed
    circuit_mode: mixed
    sources: {power: sensor.mixed}
samples:
  - {t: 0, states: {sensor.mixed: 0}}
labels:
  component_truth:
    pump:
      edges:
        - {event_type: start, around_t: 60, tolerance_seconds: 5}
        - {event_type: start, around_t: 120, tolerance_seconds: 5}
      sessions:
        - {start_t: 60, end_t: 180, tolerance_seconds: 5}
      energy_kwh: 0.01
calibration_expectations: {}
""",
        encoding="utf-8",
    )
    fixture = load_calibration_fixture(fixture_path)
    result = replay_fixture_processors(fixture)
    result.store_data.nilm_session_history_by_circuit["mixed"] = [
        {
            "assignment_id": "pump",
            "start": (fixture.start_time + timedelta(seconds=62)).isoformat(),
            "end": (fixture.start_time + timedelta(seconds=179)).isoformat(),
            "energy_kwh": 0.009,
        }
    ]
    result.final_state.nilm_reconciliation_by_circuit["mixed"] = {
        "residual_energy_kwh": 0.002,
        "ambiguous_event_count": 1,
        "total_event_count": 4,
        "conservation_violations": 0,
    }

    metrics = evaluate_replay_result(fixture, result)

    assert fixture.source_kind == "pure_mixed"
    assert metrics.component_metrics["pump"].edge_precision == 0.5
    assert metrics.component_metrics["pump"].edge_recall == 0.5
    assert metrics.component_metrics["pump"].session_f1 == 1.0
    assert metrics.component_metrics["pump"].median_start_error_seconds == 2.0
    assert metrics.component_metrics["pump"].energy_absolute_error_kwh == 0.001
    assert metrics.component_metrics["pump"].energy_percentage_error == 10.0
    assert metrics.residual_energy_kwh == 0.002
    assert metrics.ambiguous_event_rate == 0.25
    assert metrics.conservation_violations == 0


def test_component_edge_metrics_include_open_runtime_starts(tmp_path: Path) -> None:
    fixture_path = tmp_path / "mixed.yaml"
    fixture_path.write_text(
        """schema_version: 1
id: mixed_open_start
description: open runtime start counts as a predicted edge
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
source_kind: pure_mixed
circuits:
  - circuit_id: mixed
    name: Mixed
    appliance_profile: mixed
    circuit_mode: mixed
    sources: {power: sensor.mixed}
samples: [{t: 0, states: {sensor.mixed: 0}}]
labels:
  component_truth:
    pump:
      edges:
        - {event_type: start, around_t: 60, tolerance_seconds: 5}
        - {event_type: stop, around_t: 180, tolerance_seconds: 5}
      sessions: [{start_t: 60, end_t: 180, tolerance_seconds: 5}]
calibration_expectations: {}
""",
        encoding="utf-8",
    )
    fixture = load_calibration_fixture(fixture_path)
    result = replay_fixture_processors(fixture)
    result.store_data.nilm_session_history_by_circuit["mixed"] = [{
        "assignment_id": "pump",
        "start": (fixture.start_time + timedelta(seconds=60)).isoformat(),
        "end": (fixture.start_time + timedelta(seconds=180)).isoformat(),
    }]
    open_start = (fixture.start_time + timedelta(seconds=240)).isoformat()
    result.state_snapshots.extend([
        {"nilm_component_runtime_by_circuit": {
            "mixed": {"pump": {"session_start": open_start}}
        }},
        {"nilm_component_runtime_by_circuit": {
            "mixed": {"pump": {"session_start": open_start}}
        }},
    ])

    component = evaluate_replay_result(fixture, result).component_metrics["pump"]

    assert component.session_f1 == 1.0
    assert component.edge_precision == pytest.approx(2 / 3, abs=0.001)
    assert component.edge_recall == 1.0


def test_declared_source_kind_must_match_production_source_kind(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "mismatch.yaml"
    fixture_path.write_text(
        """schema_version: 1
id: mismatch
description: mismatched source kind
scenario_type: normal
start_time: 2026-01-01T00:00:00Z
source_kind: mains
circuits:
  - circuit_id: mixed
    name: Mixed
    appliance_profile: mixed
    circuit_mode: mixed
    sources: {power: sensor.mixed}
samples: [{t: 0, states: {sensor.mixed: 0}}]
labels: {}
calibration_expectations: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(CalibrationFixtureError, match="source_kind"):
        load_calibration_fixture(fixture_path)


def test_calibration_schema_allows_root_scenarios_and_entries() -> None:
    import json

    schema = json.loads((FIXTURE_DIR / "schema.json").read_text(encoding="utf-8"))
    fixture = yaml.safe_load(
        (FIXTURE_DIR / "nilm_mixed_compatibility.yaml").read_text(encoding="utf-8")
    )

    assert "circuits" not in schema["required"]
    assert schema["anyOf"] == [
        {"required": ["circuits"]},
        {"required": ["scenarios"]},
        {"required": ["entries"]},
    ]
    assert any(key in fixture for key in ("circuits", "scenarios", "entries"))


def test_old_fixture_report_header_is_unchanged() -> None:
    from scripts.calibrate_confidence import build_markdown_report

    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_kettle_cycle.yaml")
    report = build_markdown_report(
        [evaluate_replay_result(fixture, replay_fixture_processors(fixture))]
    )

    assert "| Fixture | TP | FP | FN | Precision | Recall | Latency seconds |" in report
    assert "Source kind" not in report


def test_repository_keeps_appliance_qa_docs_local_only() -> None:
    repo_root = Path(__file__).parents[1]
    ignore_text = (repo_root / ".gitignore").read_text(encoding="utf-8")

    assert "/docs/qa/" in ignore_text
    assert "/docs/development/" in ignore_text

    completed = subprocess.run(
        ["git", "ls-files", "docs/qa", "docs/development"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == ""
