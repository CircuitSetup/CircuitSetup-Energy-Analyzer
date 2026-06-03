from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from .storage import FeatureStoreData

CSV_HEADER = (
    "circuit_id",
    "timestamp",
    "period_start",
    "period_end",
    "metric",
    "value",
    "unit",
    "source",
)


def build_circuit_history_csv(data: FeatureStoreData, circuit_id: str) -> str:
    """Return retained analyzer history for one circuit as CSV text."""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADER)
    writer.writeheader()
    for row in _history_rows(data, circuit_id):
        writer.writerow(row)
    return output.getvalue()


def _history_rows(
    data: FeatureStoreData,
    circuit_id: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rows.extend(_daily_energy_rows(data, circuit_id))
    rows.extend(_demand_rows(data, circuit_id))
    rows.extend(_standby_rows(data, circuit_id))
    rows.extend(_billing_rows(data, circuit_id))
    rows.extend(_cost_rows(data, circuit_id))
    return rows


def _daily_energy_rows(
    data: FeatureStoreData,
    circuit_id: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    history = data.energy_usage_by_circuit.get(circuit_id, {})
    days = history.get("days", [])
    if not isinstance(days, list):
        return rows
    for day in days:
        if not isinstance(day, dict):
            continue
        date = str(day.get("date") or "")
        value = _number_text(day.get("usage_kwh"))
        if not date or value == "":
            continue
        rows.append(
            _row(
                circuit_id,
                timestamp=date,
                period_start=date,
                period_end=date,
                metric="daily_energy_usage",
                value=value,
                unit="kWh",
                source="energy_usage",
            )
        )
    return rows


def _demand_rows(data: FeatureStoreData, circuit_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    history = data.demand_by_circuit.get(circuit_id, {})
    peaks = history.get("daily_peaks", [])
    if not isinstance(peaks, list):
        return rows
    for peak in peaks:
        if not isinstance(peak, dict):
            continue
        date = str(peak.get("date") or "")
        value = _number_text(peak.get("peak_demand_w"))
        if not date or value == "":
            continue
        rows.append(
            _row(
                circuit_id,
                timestamp=date,
                period_start=date,
                period_end=date,
                metric="peak_demand",
                value=value,
                unit="W",
                source="demand",
            )
        )
    return rows


def _standby_rows(data: FeatureStoreData, circuit_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    history = data.standby_by_circuit.get(circuit_id, {})
    samples = history.get("samples", [])
    if not isinstance(samples, list):
        return rows
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        timestamp = str(sample.get("timestamp") or "")
        value = _number_text(sample.get("real_power_w"))
        if not timestamp or value == "":
            continue
        rows.append(
            _row(
                circuit_id,
                timestamp=timestamp,
                metric="standby_real_power",
                value=value,
                unit="W",
                source="standby",
            )
        )
    return rows


def _billing_rows(data: FeatureStoreData, circuit_id: str) -> list[dict[str, str]]:
    history = data.billing_by_circuit.get(circuit_id, {})
    if not history:
        return []
    cycle_start = str(history.get("cycle_start") or "")
    cycle_end = str(history.get("cycle_end") or "")
    value = _number_text(history.get("cycle_usage_kwh"))
    if not cycle_start or value == "":
        return []
    return [
        _row(
            circuit_id,
            timestamp=cycle_start,
            period_start=cycle_start,
            period_end=cycle_end,
            metric="billing_cycle_usage",
            value=value,
            unit="kWh",
            source="billing",
        )
    ]


def _cost_rows(data: FeatureStoreData, circuit_id: str) -> list[dict[str, str]]:
    history = data.cost_by_circuit.get(circuit_id, {})
    if not history:
        return []
    cycle_start = str(history.get("cycle_start") or "")
    cycle_end = str(history.get("cycle_end") or "")
    value = _number_text(history.get("cycle_cost"))
    if not cycle_start or value == "":
        return []
    return [
        _row(
            circuit_id,
            timestamp=cycle_start,
            period_start=cycle_start,
            period_end=cycle_end,
            metric="cost_cycle",
            value=value,
            unit="currency",
            source="cost",
        )
    ]


def _row(
    circuit_id: str,
    *,
    timestamp: str,
    metric: str,
    value: str,
    unit: str,
    source: str,
    period_start: str = "",
    period_end: str = "",
) -> dict[str, str]:
    return {
        "circuit_id": circuit_id,
        "timestamp": timestamp,
        "period_start": period_start,
        "period_end": period_end,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source": source,
    }


def _number_text(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{parsed:.6f}".rstrip("0").rstrip(".")
