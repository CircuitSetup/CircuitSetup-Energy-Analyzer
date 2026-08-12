from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.helpers.calibration import CalibrationMetrics

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def run_calibration(
    fixtures_path: Path,
    *,
    fixture_name: str | None = None,
) -> list[CalibrationMetrics]:
    from tests.helpers.calibration import (
        evaluate_replay_result,
        fixture_expectation_failures,
        load_calibration_scenarios,
        replay_fixture_processors,
    )

    fixture_paths = _fixture_paths(fixtures_path, fixture_name)
    metrics_list: list[CalibrationMetrics] = []
    for fixture_path in fixture_paths:
        for fixture in load_calibration_scenarios(fixture_path):
            result = replay_fixture_processors(fixture)
            metrics = evaluate_replay_result(fixture, result)
            metrics.expectation_failures = fixture_expectation_failures(
                fixture,
                metrics,
            )
            metrics_list.append(metrics)
    return metrics_list


def build_markdown_report(
    metrics_list: list[CalibrationMetrics],
    *,
    generated_at: datetime | None = None,
) -> str:
    passed = sum(1 for metrics in metrics_list if not metrics.expectation_failures)
    failed = len(metrics_list) - passed
    true_positive_alerts = sum(metrics.true_positive_alerts for metrics in metrics_list)
    false_positive_alerts = sum(
        metrics.false_positive_alerts for metrics in metrics_list
    )
    false_negative_alerts = sum(
        metrics.false_negative_alerts for metrics in metrics_list
    )
    precision = _ratio_or_none(
        true_positive_alerts,
        true_positive_alerts + false_positive_alerts,
    )
    recall = _ratio_or_none(
        true_positive_alerts,
        true_positive_alerts + false_negative_alerts,
    )
    latencies = [
        metrics.detection_latency_seconds
        for metrics in metrics_list
        if metrics.detection_latency_seconds is not None
    ]
    median_latency = _median(latencies)
    lines = [
        "# Confidence Calibration Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Fixtures | {len(metrics_list)} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Precision | {_format_metric(precision)} |",
        f"| Recall | {_format_metric(recall)} |",
        f"| Median detection latency seconds | {_format_metric(median_latency)} |",
        f"| False positives | {false_positive_alerts} |",
        f"| False negatives | {false_negative_alerts} |",
        "| Stale subtraction incidents | "
        f"{sum(metrics.stale_subtraction_incidents for metrics in metrics_list)} |",
        "",
        "## Fixtures",
        "",
        "| Fixture | TP | FP | FN | Precision | Recall | Latency seconds | "
        "Trace plateau MAE W | Session energy MAE kWh | Stale prevented | "
        "Measured/partial/fallback (%) | Replay work units |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if generated_at is not None:
        lines[2:2] = [f"Generated: {generated_at.astimezone(UTC).isoformat()}", ""]
    lines.extend(
        (
            "| "
            f"{metrics.fixture_id} | "
            f"{metrics.true_positive_alerts} | "
            f"{metrics.false_positive_alerts} | "
            f"{metrics.false_negative_alerts} | "
            f"{_format_metric(metrics.precision)} | "
            f"{_format_metric(metrics.recall)} | "
            f"{_format_metric(metrics.detection_latency_seconds)} | "
            f"{_format_metric(metrics.residual_plateau_mae_w)} | "
            f"{_format_metric(metrics.session_energy_mae_kwh)} | "
            f"{metrics.stale_subtraction_incidents} | "
            f"{_format_percent(metrics.measured_session_percentage)}/"
            f"{_format_percent(metrics.partial_session_percentage)}/"
            f"{_format_percent(metrics.fallback_session_percentage)} | "
            f"{metrics.replay_processing_work_units} |"
        )
        for metrics in metrics_list
    )
    component_metrics = [
        (metrics, component_id, component)
        for metrics in metrics_list
        for component_id, component in metrics.component_metrics.items()
    ]
    if component_metrics:
        lines.extend(
            [
                "",
                "## Component replay metrics",
                "",
                "| Fixture | Source kind | Component | Edge P/R | Session P/R/F1 | "
                "Start/stop/duration error s | Interval IoU | State accuracy/count | "
                "Energy abs/% error | Residual kWh | Assignment FP rate | "
                "Helper FP rate | Ambiguous rate | Conservation violations |",
                "|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|",
            ]
        )
        lines.extend(_component_row(*item) for item in component_metrics)

    decision_metrics = [
        (metrics.fixture_id, "duration", metrics.decision_impacts.duration)
        for metrics in metrics_list
    ] + [
        (metrics.fixture_id, "validation", metrics.decision_impacts.validation)
        for metrics in metrics_list
    ]
    if decision_metrics:
        lines.extend(
            [
                "",
                "## NILM score decision impact",
                "",
                "| Fixture | Channel | Changed/correct | "
                "Incorrect | Neutral | Unscored |",
                "|---|---|---:|---:|---:|---:|",
                *(
                    "| "
                    f"{fixture_id} | {channel} | "
                    f"{impact.changed_count}/{impact.changed_correct_count} | "
                    f"{impact.changed_incorrect_count} | "
                    f"{impact.changed_neutral_count} | "
                    f"{impact.changed_unscored_count} |"
                    for fixture_id, channel, impact in decision_metrics
                ),
            ]
        )

    nilm_confidence_rows = [
        (metrics.fixture_id, label, values)
        for metrics in metrics_list
        for label, values in metrics.nilm_confidence_bins.items()
        if values.get("prediction_count", 0.0)
    ]
    if nilm_confidence_rows:
        lines.extend(
            [
                "",
                "## NILM prediction confidence calibration",
                "",
                "| Fixture | Score band | Predictions | Accuracy | Average score |",
                "|---|---|---:|---:|---:|",
                *(
                    "| "
                    f"{fixture_id} | {label} | "
                    f"{values['prediction_count']:g} | "
                    f"{values['observed_accuracy']:g} | "
                    f"{values['average_score']:g} |"
                    for fixture_id, label, values in nilm_confidence_rows
                ),
            ]
        )

    failures = [metrics for metrics in metrics_list if metrics.expectation_failures]
    if failures:
        lines.extend(["", "## Failed Fixtures", ""])
        for metrics in failures:
            lines.append(f"### {metrics.fixture_id}")
            lines.append("")
            lines.extend(f"- {failure}" for failure in metrics.expectation_failures)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay calibration fixtures and summarize alert confidence.",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures/calibration"),
        help="Directory containing calibration YAML fixtures.",
    )
    parser.add_argument(
        "--fixture",
        help="Fixture id or YAML filename to run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional markdown output path. Defaults to stdout.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional JSON metrics output path.",
    )
    args = parser.parse_args()

    metrics = run_calibration(args.fixtures, fixture_name=args.fixture)
    report = build_markdown_report(metrics)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([_metrics_to_json(metric) for metric in metrics], indent=2),
            encoding="utf-8",
        )

    return 1 if any(metric.expectation_failures for metric in metrics) else 0


def _fixture_paths(fixtures_path: Path, fixture_name: str | None) -> list[Path]:
    if fixture_name:
        candidate = Path(fixture_name)
        if candidate.suffix not in {".yaml", ".yml"}:
            candidate = candidate.with_suffix(".yaml")
        if not candidate.is_absolute():
            candidate = fixtures_path / candidate
        return [candidate]
    return sorted(fixtures_path.glob("*.yaml"))


def _metrics_to_json(metrics: CalibrationMetrics) -> dict[str, Any]:
    return asdict(metrics)


def _component_row(
    metrics: CalibrationMetrics, component_id: str, component: Any
) -> str:
    values = (
        metrics.fixture_id,
        metrics.source_kind or "n/a",
        component_id,
        f"{_format_metric(component.edge_precision)}/{_format_metric(component.edge_recall)}",
        f"{_format_metric(component.session_precision)}/{_format_metric(component.session_recall)}/{_format_metric(component.session_f1)}",
        "/".join(
            _format_metric(value)
            for value in (
                component.median_start_error_seconds,
                component.median_stop_error_seconds,
                component.median_duration_error_seconds,
            )
        ),
        _format_metric(component.interval_iou),
        f"{_format_metric(component.state_accuracy)}/{component.observed_active_state_count}",
        f"{_format_metric(component.energy_absolute_error_kwh)}/{_format_metric(component.energy_percentage_error)}",
        f"{metrics.residual_energy_kwh:g}",
        _format_metric(metrics.false_assignment_rate),
        _format_metric(metrics.false_helper_association_rate),
        f"{metrics.ambiguous_event_rate:g}",
        str(metrics.conservation_violations),
    )
    return "| " + " | ".join(values) + " |"


def _ratio_or_none(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return round((values[middle - 1] + values[middle]) / 2, 3)


def _format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:g}"


def _format_percent(value: float | None) -> str:
    """Format an optional percentage without inventing a no-session value."""
    return "n/a" if value is None else f"{value:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
