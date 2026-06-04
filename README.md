# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, mixed circuits, and opt-in experimental mains NILM discovery. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Home Assistant Energy Dashboard Boundary

Use Home Assistant's built-in Energy Dashboard for normal energy history,
individual-device energy charts, device hierarchies, tariffs, cost display, and
energy dashboard cards. This integration should not recreate those views.

CircuitSetup Energy Analyzer adds behavior around that foundation: circuit and
appliance diagnostics, CircuitSetup/ATM90E32 data-quality checks, power-quality
relationship evidence, conservative repeated notifications, and optional
CircuitSetup-specific exports.

The `energy_dashboard_status` diagnostic sensor checks whether a circuit's
configured energy or power source has metadata that Home Assistant's Energy
Dashboard can use. Its attributes list ready entities, metadata issues, and the
recommended handoff action.

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

## Daily Energy Goals

For circuits with cumulative energy sensors, the analyzer can add a repeated
notification layer around a user-defined daily kWh goal. Use Home Assistant's
Energy Dashboard for the normal chart/history view; this feature is only for
per-circuit goal evidence and notices.

Use the `set_energy_goal_settings` service to set a `daily_goal_kwh` and an
optional `goal_alert_ratio`. By default, goal notices trigger at 100% of the
daily goal after repeated observations. Setting the ratio below 1.0 can warn
before the goal is reached, while setting the daily goal to 0 clears the goal.

## Run Cycle Diagnostics

For appliance-style circuits, the analyzer derives today's run-cycle count,
runtime, duty cycle, and current run status from retained START/STOP event
evidence. This is intended for appliance behavior diagnostics, such as whether
a refrigerator, pump, or HVAC circuit is cycling more often or staying on longer
than expected.

These diagnostics do not replace Home Assistant's Energy Dashboard history,
energy charts, tariffs, or cost views. They are event-derived activity evidence
that can be reviewed alongside power-quality and data-quality diagnostics.

After the circuit has enough learned cycle evidence, unusually long active
runs, unusually high daily duty cycle, or unusually high starts-per-day can
create possible-issue notifications. The alert evidence reports the observed
timing, learned baseline, sample count, and confidence. It does not diagnose a
specific failed part.

For user-defined activity alerts, use the `set_activity_alert_settings` service
to set `max_active_minutes` and/or `max_idle_minutes` values. This is useful
for appliance-style "left on too long" notices, such as a pump, oven, dryer, or
refrigerator compressor run that exceeds a user-selected duration, and for
"no activity for too long" notices when an expected cycling load has not run.

## Recent Activity Timeline

Each configured circuit exposes a compact recent-activity timeline from the
integration's retained analyzer evidence. It merges START/STOP/steady-window
events with retained possible-issue alert evidence from the last 24 hours,
sorted newest first.

Use the `recent_activity` diagnostic sensor for the latest activity title and
the sensor attributes for the detailed timeline items. The `recent_activity_count`
sensor shows how much activity was retained in the recent window. These entities
are intended for quick operational review and dashboard cards, not as a
replacement for Home Assistant recorder history or Energy Dashboard graphs.

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

## History CSV Export

Use the `export_history_csv` service to build a CSV snapshot of retained
analyzer history for one configured circuit. The v1 export includes daily kWh
usage rows, daily demand peaks, standby samples, billing-cycle usage, and
cost-cycle rows when those features have retained data for the selected
circuit.

The export is generated from the integration's retained analyzer history, not
from Home Assistant's full recorder database. The current service stores the
latest CSV snapshot in runtime state so future UI, diagnostics, or download
surfaces can reuse the same export builder without writing arbitrary files from
a service call.

## Peak Demand Tracking

The analyzer also tracks rolling power demand for each circuit with real-power
data. The default demand window is 15 minutes, matching a common utility and
energy-monitoring view for peak demand. Diagnostic entities show current rolling
demand and today's peak demand even when no alert limit is configured.

Use the `set_demand_settings` service to set a per-circuit demand window and an
optional demand limit in watts. When a limit is configured, the analyzer sends a
possible issue notification only after repeated rolling-demand observations stay
above that limit.

The demand tracker also ranks the current rolling window against retained
monthly peak-demand windows. This provides Emporia-style peak-demand awareness:
the diagnostic rank/status entities show when a circuit is near the month's top
three demand windows, and repeated near-peak observations can create a
possible-issue notification with the current demand, monthly cutoff, rank, and
window length. This is demand evidence, not a replacement for Home Assistant's
Energy Dashboard energy graphs.

## Circuit Capacity Tracking

For circuits with current sensors, the analyzer can compare measured amps with
a user-configured breaker or circuit rating. This is useful for EV chargers,
HVAC, pool pumps, water heaters, ovens, workshops, and other loads where amps
are easier to reason about than watts. If a current sensor is unavailable, the
analyzer can estimate current from real power and voltage when both are present.

Use the `set_capacity_settings` service to set `breaker_amps` and an optional
`warning_ratio` for a circuit. The default warning ratio is 0.8, so a 40 A
circuit warns at 32 A after repeated observations. Diagnostic entities show
capacity usage percentage and status. Alerts report the observed amps, the
configured circuit rating, the warning threshold, and whether the value came
from a current sensor or a power/voltage estimate.

These diagnostics are operational evidence only. They do not verify breaker,
wire, plug, appliance, or electrical-code suitability; use a qualified
electrician for circuit sizing and safety decisions.

## Dual-Phase Leg Imbalance

For dual-phase circuits with leg A and leg B real-power sensors, the analyzer
tracks how far apart the two legs are while the appliance is drawing meaningful
power. This is useful for HVAC, water heaters, pool pumps, ovens, EV chargers,
and other 240 V loads where a large persistent difference can point to CT
pairing/orientation mistakes, phase mapping problems, or a load behavior change.

The default threshold is 50% imbalance and the default minimum observed load is
500 W total, so small control-board or idle draw is tracked but does not create
alerts. Diagnostic entities expose the current imbalance percentage, status,
dominant leg, both leg wattages, optional currents/voltages, and the threshold
used. Notifications are created only after repeated over-threshold observations
and are labeled as possible issues.

## Power Metric Consistency

When a circuit has voltage, current, apparent power, real power, and/or power
factor sensors, the analyzer compares the reported metrics with the
relationships expected from AC power measurement. It checks whether measured VA
matches voltage times current, and whether reported power factor agrees with
real power divided by apparent power. For dual-phase circuits with per-leg
voltage and current, it sums each leg's V x A instead of relying only on the
combined current.

This is a CircuitSetup/ATM90E32 data-quality diagnostic, not an energy chart.
A mismatch can point to source-entity mixups, CT/channel pairing mistakes,
incorrect units, stale/missing optional sensors, or calibration problems. The
diagnostic entities expose the expected VA, reported VA, VA percent difference,
expected PF, reported PF, PF difference, and tolerance values.

## Mains Balance

For mains/NILM circuits, the analyzer calculates an Emporia-style Balance view:
mains real power minus the sum of directly monitored load circuits. This helps
show how much power is currently unmonitored or unexplained by the circuits you
mapped. A positive balance often represents normal unmonitored lighting or plug
loads. A strongly negative balance can point to CT direction, phase pairing,
solar configuration, or multiplier problems.

Generation circuits, such as solar inverter channels, are excluded from the
monitored load sum so they do not look like household consumption.

## Solar Flow Diagnostics

For homes with a signed mains/net power circuit and one or more solar inverter
circuits, the analyzer calculates instantaneous solar-flow evidence. It uses
the same convention as common solar monitoring tools: grid import is positive,
grid export is negative, and site consumption is solar generation plus signed
grid power.

Diagnostic entities expose current solar generation, estimated site
consumption, grid import, grid export, solar self-consumption percentage, and
the percentage of current site load powered by solar. This is intended as
CircuitSetup setup and sign-convention evidence. Use Home Assistant's Energy
Dashboard solar cards for normal historical solar, return-to-grid, and
self-sufficiency views.

The analyzer also exposes instantaneous solar surplus and load-shift
opportunity diagnostics. By default, exported solar at or above 500 W is
reported as `surplus_available`, and exported solar at or above 1500 W is
reported as `high_surplus`. This is inspired by solar diverter and home energy
management tools, but it is read-only: use ordinary Home Assistant automations
if you want to turn on an EV charger, water heater, pool pump, or other
flexible load.

For configured EV charger, HVAC, pool pump, and water heater circuits, the
analyzer also estimates instantaneous net solar support for active flexible
loads and whether idle flexible loads are surplus candidates. The evidence
lists candidate circuits, active/idle/unavailable state, current power,
estimated solar coverage, and status such as `active_solar_supported`,
`active_grid_supported`, `surplus_candidate`, `solar_flow_unavailable`, or
`waiting_for_surplus`.

If export is much larger than measured solar generation, the solar-flow status
reports `inconsistent_export`, which can point to CT orientation, missing
generation channels, battery export, or a solar/mains mapping problem.

## Utility And Opower Comparison

For aggregate circuits, the analyzer can compare utility-reported kWh with a
measured same-period kWh source. This is intended for sanity-check evidence,
not normal energy history. Use Home Assistant's Energy Dashboard for standard
long-term energy charts, tariffs, costs, and device energy rollups.

Use the `set_utility_comparison_settings` service on a mains or aggregate
circuit. Set `utility_energy_entity` to a current-bill or utility kWh sensor,
or set `utility_statistic_id` and `utility_source_type: statistics` to compare
an Opower statistic from Developer Tools > Statistics. For Opower statistics,
the default `utility_statistic_period` is `day`; use `month` if your utility
only provides monthly data.

If you also set `measured_energy_entities`, those mains kWh sensors are summed
and compared with the utility value. When an Opower/statistics source is used,
the measured sensors are read from recorder statistics over the same utility
period. If measured entities are left empty, the analyzer sums configured
load-circuit energy sensors and excludes mains and generation circuits such as
solar inverters.

The default tolerance is 10%. When the measured value repeatedly differs from
the utility value by more than the configured tolerance, the analyzer sends a
possible-issue notification with the utility kWh, measured kWh, difference,
percent difference, source entities, and tolerance. Before acting on the alert,
verify that the utility and measured sensors represent the same period; utility
integrations can update on a delay. The diagnostic evidence includes the utility
source type, statistic ID when used, measured source type, comparison period,
and utility data lag.

## Always On And Standby Tracking

For circuits with real-power sensors, the analyzer estimates an Always On load
from the lowest measured power in the recent sample window. The default window
is 48 hours, with an 8 W standby threshold used to label the latest state as
off, standby, or on.

Always On diagnostics are exposed for every configured load circuit. Alerts are
optional: set an `always_on_alert_w` limit with the `set_standby_settings`
service when a circuit has a known acceptable standby load. If the estimated
Always On load repeatedly exceeds that configured limit, the notification
reports the observed watts, window, and configured limit as possible-issue
evidence.

## Experimental NILM

Experimental NILM is opt-in. It can be enabled for mains aggregate channels or mixed circuits to discover recurring load signatures, but it should be treated as a hinting system rather than a diagnostic authority. Unknown signatures stay unknown until a user confirms and labels them.

When mains NILM has two real-power source channels that can be mapped to
split-phase legs, such as L1/L2 or leg A/B entity names, the analyzer keeps leg
context on recurring signatures. This lets review evidence separate likely
single-leg 120 V transitions from balanced 240 V transitions and mixed or
overlapping events. Signature payloads include leg A/B median delta watts,
dominant leg, leg balance ratio, and split-phase type such as `single_leg_a`,
`single_leg_b`, `balanced_240v`, or `imbalanced_240v_or_mixed`. These are
review clues for mapping, CT orientation, or unknown-load investigation rather
than appliance diagnoses.

When a mains NILM edge matches a configured circuit start/stop event, the
analyzer also records topology consistency evidence on that known circuit. A
single-phase circuit is expected to match one leg, while a dual-phase circuit is
expected to look like a balanced 240 V transition. Repeated conflicts create a
possible-issue alert with the observed mains topology, leg deltas, match
confidence, and configured circuit mode so the user can check mapping,
overlapping loads, or CT orientation.

For single-phase known loads, the same evidence records the observed mains leg
and a suggested leg. If the circuit already has a configured leg and repeated
high-confidence mains matches point to the other leg, the status becomes
`leg_mismatch`. The integration does not rewrite the circuit mapping; it exposes
evidence for user confirmation.

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
- `sensor.<circuit>_recent_activity`
- `sensor.<circuit>_recent_activity_count`
- `binary_sensor.<circuit>_learning`
- `binary_sensor.<circuit>_data_quality_problem`
- `sensor.<circuit>_energy_dashboard_status`
- `sensor.<circuit>_nilm_discovered_signatures`
- `sensor.<circuit>_nilm_unmatched_load_percentage`
- `sensor.<circuit>_daily_energy_usage`
- `sensor.<circuit>_energy_usage_share`
- `sensor.<circuit>_energy_usage_status`
- `sensor.<circuit>_energy_goal_usage`
- `sensor.<circuit>_energy_goal_status`
- `sensor.<circuit>_run_cycle_count`
- `sensor.<circuit>_run_cycle_runtime`
- `sensor.<circuit>_run_cycle_duty_cycle`
- `sensor.<circuit>_run_cycle_status`
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
- `sensor.<circuit>_demand_peak_rank`
- `sensor.<circuit>_demand_peak_status`
- `sensor.<circuit>_demand_status`
- `sensor.<circuit>_capacity_usage`
- `sensor.<circuit>_capacity_status`
- `sensor.<circuit>_leg_imbalance`
- `sensor.<circuit>_leg_imbalance_status`
- `sensor.<circuit>_metric_consistency_score`
- `sensor.<circuit>_metric_consistency_status`
- `sensor.<circuit>_balance_power`
- `sensor.<circuit>_monitored_power`
- `sensor.<circuit>_monitored_coverage`
- `sensor.<circuit>_balance_status`
- `sensor.<circuit>_solar_generation_power`
- `sensor.<circuit>_solar_site_consumption_power`
- `sensor.<circuit>_solar_grid_import_power`
- `sensor.<circuit>_solar_grid_export_power`
- `sensor.<circuit>_solar_self_consumption`
- `sensor.<circuit>_solar_powered`
- `sensor.<circuit>_solar_flow_status`
- `sensor.<circuit>_solar_surplus_power`
- `sensor.<circuit>_solar_load_shift_power`
- `sensor.<circuit>_solar_flexible_load_power`
- `sensor.<circuit>_solar_flexible_load_coverage`
- `sensor.<circuit>_solar_load_shift_status`
- `sensor.<circuit>_solar_surplus_status`
- `sensor.<circuit>_utility_comparison_difference`
- `sensor.<circuit>_utility_comparison_status`
- `sensor.<circuit>_always_on_power`
- `sensor.<circuit>_standby_threshold`
- `sensor.<circuit>_standby_status`
- `sensor.<circuit>_always_on_limit_usage`

See `docs/dashboard-example.yaml` for a starting dashboard with Refrigerator, HVAC, and Mains NILM cards.
