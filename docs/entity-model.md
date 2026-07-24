# Compact Entity Model

CircuitSetup Energy Analyzer creates a compact Home Assistant entity set by
default. The analyzer still calculates the same feature data internally; this
model changes which results are exposed as standalone Home Assistant entities.

## Detail Levels

| Detail level | What it creates | Typical use |
|---|---|---|
| Simple | Summary entities, Daily Energy Usage and Goal when cumulative energy is available, Alert Sensitivity, Relearn Baseline, and Maintenance. | Normal appliance dashboards and automations. |
| Standard | Simple plus configured canonical feature entities such as billing usage, cost cycle, weather/water context, capacity, and leg imbalance. | Feature-rich appliances without diagnostic clutter. |
| Expert | Standard plus only the diagnostic or graph groups selected in options. | Custom dashboards, graphing, and troubleshooting. |

Choose Expert groups explicitly from the Entity Detail Level options screen.

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

## Count Evidence

In the representative matrix, Simple creates 10 or fewer per-circuit entities
and Standard creates 17 or fewer. Expert creates only explicitly selected
groups; even selecting every group stays at or below 50 per-circuit entities.
The compact model uses one `switch.<circuit>_maintenance` entity per circuit.
