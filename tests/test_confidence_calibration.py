from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.circuitsetup_energy_analyzer.models import EventType
from tests.helpers.calibration import (
    CALIBRATION_CONFIDENCE_BINS,
    assert_fixture_expectations,
    evaluate_replay_result,
    load_calibration_fixture,
    replay_fixture_processors,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "calibration"


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
    assert "| Fixtures | 16 |" in report
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
        - {event_type: stop, around_t: 180, tolerance_seconds: 5}
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
    assert metrics.component_metrics["pump"].edge_precision == 1.0
    assert metrics.component_metrics["pump"].session_f1 == 1.0
    assert metrics.component_metrics["pump"].median_start_error_seconds == 2.0
    assert metrics.component_metrics["pump"].energy_absolute_error_kwh == 0.001
    assert metrics.component_metrics["pump"].energy_percentage_error == 10.0
    assert metrics.residual_energy_kwh == 0.002
    assert metrics.ambiguous_event_rate == 0.25
    assert metrics.conservation_violations == 0


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
