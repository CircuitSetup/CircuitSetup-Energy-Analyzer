# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, mixed circuits, and opt-in experimental mains NILM discovery. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Installation

This repository is structured for HACS as a custom integration. The integration files live under `custom_components/circuitsetup_energy_analyzer`.

To install with HACS:

1. Open HACS.
2. Add this repository as a custom repository with category `Integration`.
3. Install CircuitSetup Energy Analyzer.
4. Restart Home Assistant.
5. Add the integration from Settings > Devices & services.

## Circuit Modes

CircuitSetup Energy Analyzer supports four analysis modes:

- Single-phase circuits monitor one CT/channel mapped to one primary appliance, such as a refrigerator, freezer, pump, or other 120 V load.
- Dual-phase circuits combine two CT/channels into one appliance model for 240 V loads. The analyzer keeps leg-level context so it can surface suspicious imbalance or phase-pairing problems without treating each leg as an unrelated appliance.
- Mixed circuits are useful when one branch circuit feeds multiple small loads. The integration reports data quality, large changes, and recurring evidence conservatively instead of pretending the circuit is a clean appliance signature.
- Mains NILM circuits are whole-home aggregate inputs. Experimental NILM can look for recurring aggregate signatures after known directly monitored circuits are masked out.

## Power Flow

CircuitSetup real-power sensors may report negative watts when a CT is reversed
or when a source, such as a solar inverter, is exporting power. The analyzer
tracks the raw watts separately from the analysis watts so those cases can be
handled differently:

- Load circuits treat sustained negative real power as a data-quality problem and raise a Repair suggesting CT orientation review or a different power-flow setting.
- Solar inverter circuits treat negative real power as exported generation and analyze the export magnitude.
- Mains NILM circuits keep signed net power so import and export behavior can be disaggregated without losing direction.

## Energy Usage Spikes

For circuits with cumulative energy sensors, the analyzer derives daily kWh
usage from the positive delta between readings. By default it compares today's
usage with the previous 7 full days. If today uses more than 25% of that
7-day total, the integration records usage-spike evidence and sends a possible
issue notification only after the condition repeats.

For example, if a refrigerator circuit used 50 kWh over the previous 7 days,
the default daily spike threshold is 12.5 kWh. If today's derived usage rises
above that threshold, the alert evidence includes today's kWh, the baseline
total, the threshold, and the percentage of the learned window used today.

The `set_energy_usage_settings` service can adjust the rolling window and daily
spike ratio for a specific circuit.

## Billing Cycle Forecasts

The analyzer can also track circuit usage against a utility-style billing
cycle. By default the cycle starts on the first day of the month. For circuits
with cumulative energy sensors, diagnostic entities show current-cycle kWh,
projected end-of-cycle kWh, budget usage percentage, and billing-cycle status.

Use the `set_billing_cycle_settings` service to set a cycle start day and an
optional kWh budget for a circuit. When a budget is configured, projected
over-budget notifications require repeated evidence and include the current
usage, projected usage, configured budget, and billing-cycle dates.

## Cost And Time-of-Use Tracking

For circuits with cumulative energy sensors, the analyzer can estimate
billing-cycle cost from a configured electricity rate. The v1 cost model
supports a default per-kWh rate and one optional Time-of-Use period with a
different rate, time window, weekday list, and friendly name.

Use the `set_cost_settings` service to configure rates for a circuit. Cost
diagnostics show the active rate, current-cycle cost, projected end-of-cycle
cost, and whether the circuit is currently in the TOU period. These values are
estimates and do not include fixed fees, demand charges, taxes, tiered rates,
or every utility billing rule.

## Peak Demand Tracking

The analyzer also tracks rolling power demand for each circuit with real-power
data. The default demand window is 15 minutes, matching a common utility and
energy-monitoring view for peak demand. Diagnostic entities show current rolling
demand and today's peak demand even when no alert limit is configured.

Use the `set_demand_settings` service to set a per-circuit demand window and an
optional demand limit in watts. When a limit is configured, the analyzer sends a
possible issue notification only after repeated rolling-demand observations stay
above that limit.

## Mains Balance

For mains/NILM circuits, the analyzer calculates an Emporia-style Balance view:
mains real power minus the sum of directly monitored load circuits. This helps
show how much power is currently unmonitored or unexplained by the circuits you
mapped. A positive balance often represents normal unmonitored lighting or plug
loads. A strongly negative balance can point to CT direction, phase pairing,
solar configuration, or multiplier problems.

Generation circuits, such as solar inverter channels, are excluded from the
monitored load sum so they do not look like household consumption.

## Always On And Standby Tracking

For circuits with real-power sensors, the analyzer estimates an Always On load
from the low-power portion of the recent sample window. The default window is
24 hours, with an 8 W standby threshold used to label the latest state as off,
standby, or on.

Always On diagnostics are exposed for every configured load circuit. Alerts are
optional: set an `always_on_alert_w` limit with the `set_standby_settings`
service when a circuit has a known acceptable standby load. If the estimated
Always On load repeatedly exceeds that configured limit, the notification
reports the observed watts, window, and configured limit as possible-issue
evidence.

## Experimental NILM

Experimental NILM is opt-in. It can be enabled for mains aggregate channels or mixed circuits to discover recurring load signatures, but it should be treated as a hinting system rather than a diagnostic authority. Unknown signatures stay unknown until a user confirms and labels them.

## Alert Philosophy

The analyzer is evidence-first. It learns for at least 7 days or enough profile-specific cycles before sending appliance-behavior alerts. Alerts require repeated evidence and are phrased as a possible issue or behavior change, not a diagnosis.

This means a refrigerator alert might say that cycle duration appears unusual compared with its learned baseline. It should not claim that a compressor, fan, seal, or refrigerant problem has been diagnosed.

## Notifications And Repairs

Persistent notifications are reserved for important evidence about appliance behavior, such as repeated anomaly evidence after the learning period.

Home Assistant Repairs are used for setup, configuration, and data-quality problems: missing required sensors, stale source sensors, phase mismatch, missing mains NILM sensors, or low NILM confidence. Repairs should help fix the integration inputs before appliance analysis continues.

## Standard Entities

The integration exposes standard Home Assistant diagnostic entities per configured circuit:

- `sensor.<circuit>_anomaly_score`
- `sensor.<circuit>_last_event`
- `binary_sensor.<circuit>_learning`
- `binary_sensor.<circuit>_data_quality_problem`
- `sensor.<circuit>_nilm_discovered_signatures`
- `sensor.<circuit>_nilm_unmatched_load_percentage`
- `sensor.<circuit>_daily_energy_usage`
- `sensor.<circuit>_energy_usage_share`
- `sensor.<circuit>_energy_usage_status`
- `sensor.<circuit>_billing_cycle_usage`
- `sensor.<circuit>_billing_cycle_forecast`
- `sensor.<circuit>_billing_cycle_budget_usage`
- `sensor.<circuit>_billing_cycle_status`
- `sensor.<circuit>_cost_current_rate`
- `sensor.<circuit>_cost_cycle`
- `sensor.<circuit>_cost_cycle_forecast`
- `sensor.<circuit>_cost_status`
- `sensor.<circuit>_current_demand`
- `sensor.<circuit>_peak_demand`
- `sensor.<circuit>_demand_limit_usage`
- `sensor.<circuit>_demand_status`
- `sensor.<circuit>_balance_power`
- `sensor.<circuit>_monitored_power`
- `sensor.<circuit>_monitored_coverage`
- `sensor.<circuit>_balance_status`
- `sensor.<circuit>_always_on_power`
- `sensor.<circuit>_standby_threshold`
- `sensor.<circuit>_standby_status`
- `sensor.<circuit>_always_on_limit_usage`

See `docs/dashboard-example.yaml` for a starting dashboard with Refrigerator, HVAC, and Mains NILM cards.
