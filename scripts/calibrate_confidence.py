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
        load_calibration_fixture,
        replay_fixture_processors,
    )

    fixture_paths = _fixture_paths(fixtures_path, fixture_name)
    metrics_list: list[CalibrationMetrics] = []
    for fixture_path in fixture_paths:
        fixture = load_calibration_fixture(fixture_path)
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
    generated_at = generated_at or datetime.now(UTC)
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
        f"Generated: {generated_at.isoformat()}",
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
        "",
        "## Fixtures",
        "",
        "| Fixture | TP | FP | FN | Precision | Recall | Latency seconds |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        (
            "| "
            f"{metrics.fixture_id} | "
            f"{metrics.true_positive_alerts} | "
            f"{metrics.false_positive_alerts} | "
            f"{metrics.false_negative_alerts} | "
            f"{_format_metric(metrics.precision)} | "
            f"{_format_metric(metrics.recall)} | "
            f"{_format_metric(metrics.detection_latency_seconds)} |"
        )
        for metrics in metrics_list
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


if __name__ == "__main__":
    raise SystemExit(main())
