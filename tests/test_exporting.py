import csv
from io import StringIO

from custom_components.circuitsetup_energy_analyzer.exporting import (
    build_circuit_history_csv,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_build_circuit_history_csv_exports_retained_analyzer_history() -> None:
    data = FeatureStoreData(
        energy_usage_by_circuit={
            "fridge": {"days": [{"date": "2026-06-01", "usage_kwh": 8.5}]}
        },
        demand_by_circuit={
            "fridge": {
                "daily_peaks": [
                    {"date": "2026-06-01", "peak_demand_w": 3200.0}
                ]
            }
        },
        standby_by_circuit={
            "fridge": {
                "samples": [
                    {
                        "timestamp": "2026-06-01T12:00:00+00:00",
                        "real_power_w": 6.0,
                    }
                ]
            }
        },
        billing_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_end": "2026-07-01",
                "cycle_usage_kwh": 42.0,
            }
        },
        cost_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_end": "2026-07-01",
                "cycle_cost": 18.0,
            }
        },
    )

    rows = list(csv.DictReader(StringIO(build_circuit_history_csv(data, "fridge"))))

    assert rows == [
        {
            "circuit_id": "fridge",
            "timestamp": "2026-06-01",
            "period_start": "2026-06-01",
            "period_end": "2026-06-01",
            "metric": "daily_energy_usage",
            "value": "8.5",
            "unit": "kWh",
            "source": "energy_usage",
        },
        {
            "circuit_id": "fridge",
            "timestamp": "2026-06-01",
            "period_start": "2026-06-01",
            "period_end": "2026-06-01",
            "metric": "peak_demand",
            "value": "3200",
            "unit": "W",
            "source": "demand",
        },
        {
            "circuit_id": "fridge",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "period_start": "",
            "period_end": "",
            "metric": "standby_real_power",
            "value": "6",
            "unit": "W",
            "source": "standby",
        },
        {
            "circuit_id": "fridge",
            "timestamp": "2026-06-01",
            "period_start": "2026-06-01",
            "period_end": "2026-07-01",
            "metric": "billing_cycle_usage",
            "value": "42",
            "unit": "kWh",
            "source": "billing",
        },
        {
            "circuit_id": "fridge",
            "timestamp": "2026-06-01",
            "period_start": "2026-06-01",
            "period_end": "2026-07-01",
            "metric": "cost_cycle",
            "value": "18",
            "unit": "currency",
            "source": "cost",
        },
    ]


def test_build_circuit_history_csv_returns_header_for_empty_circuit() -> None:
    csv_text = build_circuit_history_csv(FeatureStoreData(), "unknown")

    assert csv_text == (
        "circuit_id,timestamp,period_start,period_end,metric,value,unit,source\r\n"
    )
