# Compact Entity Model

CircuitSetup Energy Analyzer creates a compact Home Assistant entity set by
default. The analyzer still calculates the same feature data internally; this
model changes which results are exposed as standalone Home Assistant entities.

## Detail Levels

| Detail level | What it creates | Typical use |
|---|---|---|
| Simple | Summary entities, Running when applicable, Daily Energy Usage and Goal when cumulative energy is available, Alert Sensitivity, Relearn Baseline, and Maintenance. | Normal appliance dashboards and automations. |
| Standard | Simple plus configured canonical feature entities such as billing usage, cost cycle, standby status, weather/water context, capacity, and leg imbalance. | Feature-rich appliances without diagnostic clutter. |
| Expert | Standard plus only the diagnostic or graph groups selected in options. | Custom dashboards, graphing, and troubleshooting. |

Expert does not automatically recreate every historical diagnostic entity.
Choose groups explicitly from the Entity Detail Level options screen.

## Expert Groups

| Group | Examples |
|---|---|
| Cycle Metrics | Run Cycle Count, Run Cycle Runtime, Run Cycle Duty Cycle |
| Electrical Scores | Power Quality Score, Metric Consistency Score |
| Power Quality Drift | Reactive Power Drift, Apparent Power Drift, Power Factor Drift |
| Energy Detail | Energy Usage Share and energy-goal status/detail entities |
| Billing Forecasts | Billing Cycle Forecast and Cost Cycle Forecast |
| Demand Detail | Current Demand, Peak Demand, Demand Limit Usage, demand/capacity status |
| Mains and Solar Detail | Balance, solar-flow, and utility-comparison detail |
| NILM Detail | NILM signature and unknown-load detail |
| Weather Detail | Weather-context detail when configured |
| Water Detail | Water-flow mismatch minutes |
| Developer Diagnostics | Learning, data quality, recent activity, suggestions, anomaly score, circuit mode, power flow, and pause alerts |

## Replacement Surfaces

| Legacy standalone entity | Compact replacement |
|---|---|
| Sensitivity sensor | `select.<circuit>_alert_sensitivity` |
| Readiness, Learning Progress | `sensor.<circuit>_health_summary` attributes |
| Data Quality Checklist | Health Summary, Setup Health, and Repairs |
| Alert Evidence, Last Event | Dynamic Alert Evidence panel and retained diagnostics |
| Power-quality evidence/status text | `sensor.<circuit>_electrical_health` attributes and evidence panel |
| Run Cycle Status | `sensor.<circuit>_activity_summary` and `binary_sensor.<circuit>_running` |
| Cycle numeric metrics | Expert Cycle Metrics group |
| Billing/cost status and budget details | `sensor.<circuit>_billing_cycle_usage` and `sensor.<circuit>_cost_cycle` attributes |
| Standby Threshold sensor | Advanced Circuit Settings and Standby Status attributes |
| Outdoor Temperature mirror | Configured outdoor temperature source entity and Weather Context attributes |
| Secondary solar-flow mirrors | Solar Flow Status attributes and the evidence panel |
| Solar load-shift detail mirrors | Solar Surplus sensors and load-shift evidence |
| Utility comparison difference | Utility Comparison Status attributes |
| Start/End Maintenance buttons | `switch.<circuit>_maintenance` |

## Count Evidence

Local count reports can be regenerated with:

```powershell
python scripts/report_entity_inventory.py
```

Generated development artifacts are local-only and are not checked in.

In the representative matrix, Simple creates 10 or fewer per-circuit entities
and Standard creates 17 or fewer. Expert creates only explicitly selected
groups; even selecting every group stays at or below 50 per-circuit entities.
