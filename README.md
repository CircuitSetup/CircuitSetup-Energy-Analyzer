# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration that turns circuit-level energy-meter data into useful appliance and circuit diagnostics.

It is designed for the [CircuitSetup Expandable 6 Channel ESP32 Energy Meter Main Board](https://circuitsetup.us/index.php/product/expandable-6-channel-esp32-energy-meter/) exposed through ESPHome ATM90E32 sensors, but it can also work with other meters when they expose compatible Home Assistant sensor entities for:

- Power
- Current
- Voltage
- Energy
- Frequency
- Reactive power
- Apparent power
- Power factor

The integration does **not** replace Home Assistant's Energy Dashboard. Use the Energy Dashboard for long-term energy history, tariffs, costs, device hierarchies, and normal energy cards. Use CircuitSetup Energy Analyzer when you want to understand what your circuits and appliances are doing, whether their behavior has changed, and whether your meter data looks trustworthy.

## What you can use it for

Use this integration when you want answers like:

- Is this appliance running, idle, on standby, or not showing recent activity?
- Is today's energy use unusually high for this circuit?
- Is my refrigerator, washer, dryer, pump, HVAC, water heater, or EV charger behaving differently from its learned baseline?
- Is a 240 V appliance balanced across both legs?
- Are watts, amps, volts, VA, and power factor internally consistent?
- Is a circuit approaching a configured breaker or capacity limit?
- Which monitored circuits explain my mains power, and how much power is still unmonitored?
- Is solar being exported, self-consumed, or available for flexible loads?
- Do my measured kWh totals roughly agree with utility or Opower data?
- Are there recurring unknown whole-home load signatures worth investigating?

The analyzer is intentionally conservative. It learns before alerting, requires repeated evidence, and reports a **possible issue** or **behavior change** instead of claiming to diagnose a failed appliance part.

## What this integration is not

CircuitSetup Energy Analyzer is not:

- A replacement for Home Assistant's Energy Dashboard.
- A substitute for an electrician, appliance technician, or code-compliance review.
- A guarantee that a breaker, wire, CT, panel, or appliance is safe.
- A definitive appliance-failure diagnosis tool.
- A full NILM system that can always identify every unknown load automatically.

Treat alerts as evidence to review. Check the source entities, CT orientation, phase mapping, units, and appliance assignment before assuming the appliance is the problem.

## Requirements

You need:

- Home Assistant `2025.1.0` or newer.
- HACS, if installing through the recommended method.
- One or more energy-meter sensors already available in Home Assistant.
- For CircuitSetup meters, ESPHome entities from an ATM90E32-based meter are the expected source.
- Cumulative kWh sensors if you want daily energy, goals, billing-cycle, cost, utility comparison, or Energy Dashboard readiness checks.
- Current sensors, or power plus voltage, if you want capacity/amp checks.
- Mains or aggregate sensors if you want mains balance, experimental Mains NILM, solar-flow, or utility comparison features.
- An outdoor temperature sensor if you want HVAC weather context.

The integration works best when each important appliance or circuit has a clean group of related source sensors.

## Installation

This repository is structured as a HACS custom integration. The integration files live under:

```text
custom_components/circuitsetup_energy_analyzer
```

![CircuitSetup Energy Analyzer integration overview in Home Assistant Devices and services](docs/images/readme/integration-overview.png)

### Install with HACS

1. Open **HACS**.
2. Add this repository as a custom repository.
3. Choose category **Integration**.
4. Install **CircuitSetup Energy Analyzer**.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services**.
7. Add **CircuitSetup Energy Analyzer**.

## Setup overview

The setup flow is designed so you do not need to hand-write JSON.

![CircuitSetup Energy Analyzer options menu with setup actions](docs/images/readme/options-menu.png)

During setup, you choose:

| Setup item | What it is for |
|---|---|
| **Source Devices** | ESPHome meter devices, such as a CircuitSetup ATM90E32 meter. The integration expands selected devices into matching electrical sensors. |
| **Extra Source Entities** | Individual sensors that are not attached to a selected source device, or sensors you want to add manually. |
| **Mains Source Entities** | Optional whole-panel or aggregate sensors used for mains balance, experimental Mains NILM, solar-flow, and utility comparison. |
| **Outdoor Temperature Entity** | Optional outdoor temperature source used only for HVAC weather context. |
| **Circuit Assignments** | The review step where you confirm which sensors belong together and how each circuit should be analyzed. |

![Source selection panel showing Source Devices and Extra Source Entities](docs/images/readme/source-selection.png)

![Circuit assignment editor showing circuit mode and power flow controls](docs/images/readme/assignment-editor.png)

## First-time setup checklist

1. Install the integration, restart Home Assistant, and add it from **Settings > Devices & services**.
2. In **Source Devices**, select the ESPHome meter device or other meter device that owns your CT/channel sensors.
3. Use **Extra Source Entities** only for sensors that are not already included through a selected source device.
4. Leave **Mains Source Entities** empty unless you have whole-panel or aggregate measurements.
5. Add mains sources if you want Mains NILM, mains balance, solar-flow, or utility/Opower comparison.
6. Add an outdoor temperature entity if you want HVAC activity compared with outdoor conditions.
7. Open **Review Circuit Assignments**.
8. For each detected group, confirm:
   - Whether to include the circuit.
   - The circuit name.
   - The appliance type.
   - The circuit mode.
   - The power-flow mode.
   - The selected source sensors.
9. Save the configuration.
10. Let the analyzer learn before acting on behavior alerts. Most behavior checks need at least 7 days or enough appliance cycles.

## Classify circuits carefully

Correct circuit classification is the most important part of setup.

| Mode | Use for | Notes |
|---|---|---|
| **Single Phase** | One CT/channel tracking one main 120 V load, such as a refrigerator, washer, sump pump, microwave, or water pump. | Best for dedicated appliance circuits. |
| **Dual Phase** | Two CT/channels that are the two legs of one 240 V appliance, such as HVAC, electric heat, water heater, dryer, oven, pool pump, or EV charger. | Enables leg-balance and combined-appliance analysis. |
| **Mixed** | A branch circuit with multiple unrelated loads, such as plugs and lights. | The analyzer stays conservative and avoids appliance-specific claims. |
| **Mains NILM** | Whole-home mains or feed circuits. | Required for experimental whole-home load-signature discovery. |

## Choose the right power-flow mode

Power-flow mode tells the analyzer how to interpret signed watts.

| Power flow | Use for | How negative watts are treated |
|---|---|---|
| **Load** | Normal consuming circuits. | Sustained negative watts usually mean CT orientation or configuration should be checked. |
| **Generation / Solar Export** | Solar inverter or generation circuits. | Negative power can be expected export/generation behavior. |
| **Mains / Net** | Signed whole-home mains measurements. | Import and export direction are preserved. |

If a normal load circuit shows sustained negative watts, check CT orientation before using that data as appliance evidence.

## Supported appliance profiles

Recommended appliance types include:

- `refrigerator`
- `freezer`
- `hvac`
- `hvac_compressor`
- `hvac_blower`
- `electric_heat`
- `water_heater`
- `oven`
- `microwave`
- `washer`
- `dryer`
- `pool_pump`
- `water_pump`
- `sump_pump`
- `ev_charger`
- `solar_inverter`
- `motor_load`
- `resistive_load`
- `mixed`

`well_pump` is accepted as a legacy alias for `water_pump`.

Choose the closest profile. The profile controls which checks are useful, which sensors are recommended, and how learning works.

## Start with the summary entities

Most users should build dashboards from the summary entities first. Detailed diagnostic entities are still available, but many are hidden by default so dashboards stay readable.

For a configured circuit ID such as `refrigerator`, `hvac`, or `car_charger`, the main entities follow this pattern:

| Entity | Example | What it tells you |
|---|---|---|
| **Health Summary** | `sensor.<circuit>_health_summary` | Whether the circuit is ready, learning, missing data, paused, or showing a possible issue. |
| **Activity Summary** | `sensor.<circuit>_activity_summary` | What the appliance appears to be doing now: running, idle, standby, on, off, or no recent activity. |
| **Electrical Health** | `sensor.<circuit>_electrical_health` | Combined electrical condition, including power-quality, metric-consistency, and leg-balance evidence when available. |
| **Energy Summary** | `sensor.<circuit>_energy_summary` | Combined daily usage, goal, billing, cost, and high-usage evidence. |
| **Daily Energy Usage** | `sensor.<circuit>_daily_energy_usage` | Today's derived kWh when a cumulative energy source is available. |
| **Running** | `binary_sensor.<circuit>_running` | Simple on/off running state for automations. |
| **Settings Suggestions** | `sensor.<circuit>_settings_suggestions` | Count of pending advanced-setting recommendations. Hidden by default. |

For power-meter interpretation:

- **Watts**: what the circuit is doing right now.
- **kWh**: how much energy it used over time.
- **Amps**: how hard the circuit is loaded.
- **Power factor, reactive power, and apparent power**: electrical evidence used for health and consistency checks.

## Build a useful dashboard

Start with one simple card per important appliance:

1. Activity Summary
2. Electrical Health
3. Energy Summary
4. Daily Energy Usage

Add the Running binary sensor where you want automations, such as washer finished, dryer finished, pump running, or microwave activity.

For more detail, use the included example dashboard:

```text
docs/dashboard-example.yaml
```

![Appliance-first Energy Analyzer dashboard with appliance status rollups and mains analysis cards](docs/images/readme/demo-dashboard.png)

A good dashboard order is:

1. **Appliance status**: Activity Summary, Electrical Health, Energy Summary, Daily Energy Usage.
2. **Automations**: Running binary sensors for appliance-complete notifications.
3. **Energy tracking**: Daily Energy Usage and Energy Summary.
4. **Electrical review**: Electrical Health, plus detailed diagnostics only when needed.
5. **Setup/data quality**: Repairs, notifications, and entity attributes.

## Let the analyzer learn

During the first week, expect many entities to say `Learning`, `Needs data`, or `Waiting For Energy Change`.

The analyzer learns conservative baselines before sending behavior alerts. Depending on the feature, it needs:

- At least 7 days of retained history.
- Enough run cycles.
- Enough daily kWh samples.
- Enough steady samples for standby, demand, or power-quality checks.

If something looks confusing, open the entity details and review attributes such as:

- `status_explanation`
- `observed_evidence`
- `source_entities`
- `threshold`
- `sample_count`
- `first_seen`
- `last_seen`

Do this before changing thresholds or assuming an appliance has failed.

## Optional features

Enable and tune only the features you need. Most settings are available from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

![Advanced circuit settings panel with sensitivity and energy window controls](docs/images/readme/advanced-settings.png)

| Feature | What it does | Needs |
|---|---|---|
| **Energy usage spikes** | Compares today's kWh with a learned rolling window and reports repeated high-usage evidence. | Cumulative energy sensor. |
| **Daily energy goals** | Lets you set a per-circuit daily kWh goal and receive repeated goal notices. | Cumulative energy sensor. |
| **Run-cycle diagnostics** | Tracks start count, runtime, duty cycle, and running state for appliance-style circuits. | Real-power data and enough cycles. |
| **HVAC weather context** | Compares HVAC runtime with similar outdoor temperatures before treating runtime as unusual. | HVAC-like circuit plus outdoor temperature sensor. |
| **Recent activity timeline** | Keeps recent start/stop/steady-window events and recent possible-issue evidence. | Configured circuit with retained evidence. |
| **Billing-cycle forecasts** | Tracks current-cycle kWh and projected end-of-cycle usage. | Cumulative energy sensor. |
| **Cost and Time-of-Use estimates** | Estimates current-cycle and projected cost from configured rates. | Cumulative energy sensor and configured rates. |
| **History CSV export** | Exports retained analyzer history for one circuit. | Retained analyzer history. |
| **Peak demand tracking** | Tracks rolling demand and today's peak demand. | Real-power data. |
| **Circuit capacity tracking** | Compares amps with a configured breaker/circuit rating. | Current sensor, or power plus voltage. |
| **Dual-phase leg imbalance** | Checks whether both legs of a 240 V appliance are behaving as expected. | Dual-phase circuit with leg A/B power. |
| **Power metric consistency** | Checks whether W, VA, V, A, and PF relationships make sense. | Voltage/current/apparent power/power factor where available. |
| **Mains balance** | Compares mains power with the sum of monitored load circuits. | Mains or aggregate source. |
| **Solar flow** | Shows solar generation, grid import/export, site consumption, surplus, and flexible-load hints. | Signed mains/net source plus solar generation circuit. |
| **Utility / Opower comparison** | Compares utility-reported kWh with measured kWh for the same period. | Utility/Opower entity or statistic plus measured energy. |
| **Always On and standby** | Estimates the low-power always-on load and current standby/on/off state. | Real-power data. |
| **Experimental NILM** | Looks for recurring unknown whole-home load signatures. | Mains aggregate source; optional known-load circuits improve results. |

## Feature notes

### Energy usage spikes

For circuits with cumulative kWh sensors, the analyzer derives daily usage from positive energy deltas. By default, it compares today's usage with the previous 7 full days and treats a large repeated increase as possible issue evidence.

Use this for appliances where daily usage should usually stay within a predictable range, such as refrigerators, freezers, water heaters, HVAC, pumps, or EV charging circuits.

Tune it with:

```yaml
action: circuitsetup_energy_analyzer.set_energy_usage_settings
data:
  circuit_id: refrigerator
  window_days: 7
  daily_spike_ratio: 0.25
```

### Daily energy goals

Daily goals add a notification layer around a kWh target. Use Home Assistant's Energy Dashboard for normal energy charts; use this feature when you want per-circuit goal evidence.

```yaml
action: circuitsetup_energy_analyzer.set_energy_goal_settings
data:
  circuit_id: hvac
  daily_goal_kwh: 12
  goal_alert_ratio: 1.0
```

Set `daily_goal_kwh` to `0` to clear the goal.

### Run-cycle diagnostics

For appliance-style circuits, the analyzer tracks today's:

- Run-cycle count
- Runtime
- Duty cycle
- Current running state

This is useful for refrigerators, freezers, pumps, HVAC, washers, dryers, and other loads where cycling behavior matters.

### HVAC weather context

HVAC runtime depends strongly on outdoor temperature. A compressor running longer on a very hot afternoon may be normal, while the same runtime on a mild day may deserve review.

Add an outdoor temperature entity during setup or later from **Configure**. Use a real outdoor sensor, weather-station sensor, or reliable outdoor helper. Indoor thermostat temperature is usually not a good source for this feature.

### Billing, cost, and Time-of-Use

Billing and cost features estimate usage and cost from analyzer-retained data. They do not include every possible utility billing rule, such as taxes, fixed fees, tiered rates, or demand charges.

Use them for household awareness and alerts, not for exact utility-bill reproduction.

### Demand and capacity

Demand tracking uses rolling average watts. Capacity tracking compares amps with a configured breaker or circuit rating.

```yaml
action: circuitsetup_energy_analyzer.set_capacity_settings
data:
  circuit_id: car_charger
  breaker_amps: 50
  warning_ratio: 0.8
```

Capacity diagnostics are operational evidence only. They do not verify breaker, wire, plug, appliance, or code suitability.

### Dual-phase leg imbalance

For 240 V loads, the analyzer can compare leg A and leg B while the appliance is drawing meaningful power. Repeated imbalance can point to:

- CT pairing mistakes
- CT orientation problems
- Phase mapping problems
- Appliance behavior changes

A leg imbalance alert means "review the evidence," not "replace the appliance."

### Power metric consistency

When voltage, current, watts, VA, and power factor are available, the analyzer checks whether the reported values agree with expected AC power relationships.

A mismatch can point to:

- Source-entity mixups
- CT/channel pairing mistakes
- Incorrect units
- Stale sensors
- Calibration problems

This is especially useful with CircuitSetup/ATM90E32 data because multiple electrical measurements are available per channel.

### Mains balance

Mains balance compares whole-home mains power with the sum of directly monitored load circuits.

A positive balance often represents ordinary unmonitored loads, such as lights or plug loads. A strongly negative balance can suggest CT direction, phase pairing, solar configuration, multiplier, or double-counting problems.

### Solar flow

For homes with a signed mains/net source and solar generation circuits, the analyzer can estimate:

- Solar generation
- Site consumption
- Grid import
- Grid export
- Solar self-consumption
- Solar-powered share
- Solar surplus
- Flexible-load solar support

This feature is read-only. Use ordinary Home Assistant automations if you want to turn on an EV charger, water heater, pool pump, or other flexible load when solar surplus is available.

### Utility / Opower comparison

Utility comparison checks whether utility-reported kWh roughly agrees with measured kWh over the same period.

Configure it on a mains or aggregate circuit. You can use a utility/Opower entity, a recorder statistic ID, or let the analyzer choose automatically when possible.

Before acting on a mismatch, verify that the utility and measured sources cover the same time period. Utility integrations can update late.

### Always On and standby

For load circuits with real-power data, the analyzer estimates an Always On load from the lowest retained power level in the standby window. It can also classify the current state as off, standby, or on.

```yaml
action: circuitsetup_energy_analyzer.set_standby_settings
data:
  circuit_id: refrigerator
  standby_threshold_w: 12
  always_on_alert_w: 35
```

### Experimental NILM

Experimental NILM is opt-in. It can look for recurring unknown load signatures from mains or mixed circuits, especially when known directly monitored circuits are masked out.

Unknown load estimates may include:

- Likely load type
- 120 V versus 240 V hint
- Dominant leg
- Typical W/VAR/VA
- Power factor
- Confidence
- First seen / last seen
- Running state
- Estimated runtime and kWh

These are clues, not confirmed appliance names. If multiple loads overlap, the analyzer should keep the evidence ambiguous instead of forcing a guess.

## Suggested settings

After enough history, the analyzer can suggest advanced settings based on observed evidence. These are tuning recommendations for thresholds and windows, not appliance diagnoses.

Review them from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Review Suggested Settings**

For each suggestion, you can:

| Action | Meaning |
|---|---|
| **Apply Suggestion** | Update the circuit's advanced setting. |
| **Deny Suggestion** | Suppress the same suggestion for the same evidence. |
| **Dismiss For Now** | Hide it until the evidence changes or the recommendation expires. |

You can also expose `sensor.<circuit>_settings_suggestions` if you want a dashboard-visible count of pending recommendations.

## Alerts and evidence

The analyzer uses two different Home Assistant surfaces:

| Surface | Used for |
|---|---|
| **Persistent notifications** | Important repeated evidence about appliance or circuit behavior. |
| **Repairs** | Setup, source-data, configuration, stale-sensor, CT orientation, or data-quality problems. |

When an alert appears:

1. Read the notification and related summary entity first.
2. Open the entity details.
3. Review `status_explanation`, observed values, thresholds, sample counts, source entities, and timestamps.
4. Use the **Open evidence graph** link when available.
5. Check easy setup causes before appliance causes:
   - CT direction
   - Phase pairing
   - Stale sensors
   - Wrong units
   - Missing voltage/current/PF/VA sensors
   - Wrong appliance type
   - Wrong circuit mode
   - Wrong power-flow mode
6. Use Repairs for configuration and data-quality problems.
7. If work is planned on an appliance or circuit, use maintenance or pause-alert actions before service begins.

![Home Assistant notification drawer showing a CircuitSetup Energy Analyzer possible-issue notification](docs/images/readme/notifications-panel.png)

![Dynamic Energy Analyzer evidence graph opened from a notification link](docs/images/readme/notifications-repairs.png)

## Alert automation blueprint

The repository includes a Home Assistant automation blueprint:

```text
blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml
```

Use it to create persistent notifications or custom follow-up actions when selected analyzer entities report possible issue states.

Companion App mobile notifications can use the `evidence_path` template variable for `data.url` and Android `data.clickAction`, so tapping the notification opens the same Home Assistant evidence view.

## Practical automations

### Washer finished notification

Use the Running binary sensor for simple appliance-finished notifications.

```yaml
alias: Washer finished
trigger:
  - platform: state
    entity_id: binary_sensor.washer_running
    from: "on"
    to: "off"
    for: "00:03:00"
action:
  - service: notify.mobile_app_phone
    data:
      message: Washer cycle appears finished.
```

### Pause alerts during service

```yaml
action: circuitsetup_energy_analyzer.start_maintenance
data:
  circuit_id: refrigerator
  note: Cleaned coils
  duration: "02:00:00"
  relearn_on_end: false
```

End maintenance and optionally relearn:

```yaml
action: circuitsetup_energy_analyzer.end_maintenance
data:
  circuit_id: refrigerator
  relearn: true
```

### Relearn a circuit baseline

Use this after maintenance, appliance replacement, CT remapping, or any other change that makes the old learned baseline no longer useful.

```yaml
action: circuitsetup_energy_analyzer.relearn_baseline
data:
  circuit_id: refrigerator
```

## Developer Tools actions

Most users should use the integration options screens. Developer Tools actions are available for scripts, automations, and advanced workflows.

Useful action families include:

| Purpose | Actions |
|---|---|
| Usage and goals | `set_energy_usage_settings`, `set_energy_goal_settings` |
| Billing, cost, utility comparison | `set_billing_cycle_settings`, `set_cost_settings`, `set_utility_comparison_settings` |
| Demand and capacity | `set_demand_settings`, `set_capacity_settings` |
| Dual-phase and electrical checks | `set_leg_imbalance_settings`, `set_metric_consistency_settings` |
| Mains and solar | `set_mains_balance_settings`, `set_solar_flow_settings` |
| Appliance behavior | `set_activity_alert_settings`, `set_standby_settings` |
| Alert handling | `pause_alerts`, `acknowledge_alert`, `mark_alert_expected`, `mark_alert_unhelpful` |
| Maintenance | `start_maintenance`, `end_maintenance`, `relearn_baseline` |
| Experimental NILM | `label_nilm_signature`, `ignore_nilm_signature`, `mark_nilm_signature_expected`, `merge_nilm_signatures` |
| Suggested settings | `recalculate_setting_recommendations`, `apply_setting_recommendation`, `deny_setting_recommendation`, `dismiss_setting_recommendation` |
| Export and diagnostics | `export_diagnostics`, `export_history_csv`, `run_mapping_checks` |

When calling services, set `circuit_id` to the configured circuit ID, such as `refrigerator`, `hvac`, `car_charger`, or `mains`.

## Common setup states

| State | Meaning |
|---|---|
| `Needs data` | Required source sensors are missing, stale, unavailable, or not producing usable samples. |
| `Learning` | The analyzer has data but does not yet have enough retained samples or cycles. |
| `Waiting For Energy Change` | A cumulative kWh sensor exists, but the analyzer has not yet observed a positive energy increase. |
| `Missing Metrics` | Optional electrical metrics needed for a check are not available. |
| `Possible issue` | Repeated evidence crossed a configured or learned threshold. Review evidence before making a diagnosis. |
| Negative watts on a load | Usually export power or reversed CT orientation. Check power-flow mode and CT direction. |

Daily Energy Usage can show `0 kWh` for two different reasons:

1. The circuit truly has not used energy today.
2. The analyzer is still waiting to observe the first positive increase from the cumulative kWh source.

Use `sensor.<circuit>_energy_usage_status` and the `status_explanation` attribute to tell the difference.

## Source measurement inputs

These are the sensors you select during setup. The analyzer does not require every role for every appliance, but additional roles improve the evidence it can produce.

| Source role | Used for |
|---|---|
| **Energy** | Daily kWh, billing-cycle usage, goals, utility comparison, Energy Dashboard readiness. |
| **Active Power / Watts** | Appliance state, demand, cycles, NILM, balance, solar flow, negative-power checks. |
| **Current** | Capacity checks, dual-phase evidence, metric consistency. |
| **Voltage** | Metric consistency and current estimation. Split-phase mains L1/L2 voltage can help appliance circuits. |
| **Frequency** | Line-frequency context from the meter. |
| **Power Factor** | Motor/load behavior and metric consistency evidence. |
| **Reactive Power** | Motor, compressor, pump, and power-quality drift evidence. |
| **Apparent Power** | VA relationship checks with watts and power factor. |

For single-phase appliances, use one matching set of source entities.

For dual-phase appliances, use L1/L2 or leg A/B source entities where possible.

For mains, use aggregate L1/L2 sources.

For solar inverters, set circuit Power Flow to **Generation / Solar Export**.

## Output entity groups

Entity IDs use your configured circuit ID. For example, a circuit named `refrigerator` may expose entities such as:

```text
sensor.refrigerator_health_summary
sensor.refrigerator_activity_summary
sensor.refrigerator_electrical_health
sensor.refrigerator_energy_summary
sensor.refrigerator_daily_energy_usage
binary_sensor.refrigerator_running
```

| Group | Examples | Use |
|---|---|---|
| Summary | `health_summary`, `activity_summary`, `electrical_health`, `energy_summary` | Everyday dashboard state. |
| Learning and evidence | `readiness`, `learning_progress`, `alert_evidence`, `recent_activity` | Troubleshooting and advanced dashboards. |
| Data quality | `data_quality_checklist`, `energy_dashboard_status` | Setup and source-data review. |
| Energy | `daily_energy_usage`, `energy_usage_status`, `energy_goal_status` | Daily usage, spikes, and goals. |
| Billing and cost | `billing_cycle_usage`, `billing_cycle_forecast`, `cost_cycle`, `cost_status` | Cycle forecasting and cost estimates. |
| Run cycle | `run_cycle_count`, `run_cycle_runtime`, `run_cycle_duty_cycle`, `run_cycle_status` | Appliance behavior and running patterns. |
| Demand and capacity | `current_demand`, `peak_demand`, `capacity_usage`, `capacity_status` | High-load circuit awareness. |
| Dual-phase | `leg_imbalance`, `leg_imbalance_status` | 240 V appliance leg review. |
| Electrical metrics | `metric_consistency_score`, `metric_consistency_status` | W/VA/PF/V/A consistency checks. |
| Mains | `balance_power`, `monitored_power`, `monitored_coverage`, `balance_status` | Whole-home monitored versus unmonitored load. |
| Solar | `solar_generation_power`, `solar_grid_import_power`, `solar_grid_export_power`, `solar_surplus_status` | Solar flow and surplus evidence. |
| Utility | `utility_comparison_difference`, `utility_comparison_status` | Measured kWh versus utility/Opower sanity check. |
| Standby | `always_on_power`, `standby_threshold`, `standby_status`, `always_on_limit_usage` | Always-on and standby review. |
| Experimental NILM | `nilm_discovered_signatures`, `nilm_unknown_loads`, `nilm_topology_status` | Unknown whole-home load evidence. |
| Binary sensors | `learning`, `data_quality_problem`, `maintenance`, `running` | Automations and state checks. |

Advanced diagnostic entities are often hidden by default. Enable them only when you want more detail or need them for automations.

## Status glossary

Common status values include:

| Display label | Raw status | Meaning |
|---|---|---|
| Ready | `ready` | The analyzer has enough data for this check. |
| Learning | `learning` | More history or cycles are needed. |
| Needs data | `needs_data` | Required source data is missing or unusable. |
| Missing Metrics | `missing_metrics` | The check needs more electrical measurements. |
| Waiting For Energy Change | `waiting_for_delta` | A cumulative kWh source is present, but no positive increase has been observed. |
| Running | `running` | The circuit is currently above the active-load threshold. |
| Idle | `idle` | The circuit is below the active-load threshold for this check. |
| Standby | `standby` | Latest power is within the configured standby range. |
| Over Goal | `over_goal` | Daily energy usage is over the configured goal. |
| Projected Over Budget | `projected_over_budget` | Current usage projects above the billing-cycle budget. |
| Over Limit | `over_limit` | The measured value is above a configured limit. |
| Imbalanced | `imbalanced` | Dual-phase leg difference is repeatedly above the warning threshold. |
| Metric Mismatch | `metric_mismatch` | One or more power relationships changed beyond tolerance. |
| Negative Balance | `negative_balance` | Monitored load power is higher than mains power beyond tolerance. |
| Exporting | `exporting` | Signed mains power currently indicates grid export. |
| Importing | `importing` | Signed mains power currently indicates grid import. |
| Surplus Available | `surplus_available` | Solar export is above the configured surplus threshold. |
| High Surplus | `high_surplus` | Solar export is above the configured high-surplus threshold. |
| Inconsistent Export | `inconsistent_export` | Grid export is larger than measured generation; check solar/mains mapping. |
| Possible Issue | `possible_issue` | Repeated evidence crossed an alert threshold. |

For automations and debugging, status sensors may expose:

- `raw_status`
- `status_label`
- `status_explanation`

Use `raw_status` for automations because it is more stable than the display label.

## Recommended workflow

1. Get your meter data into Home Assistant first.
2. Install CircuitSetup Energy Analyzer.
3. Select source devices and any extra source entities.
4. Add mains and outdoor temperature only if you need those features.
5. Review every circuit assignment before saving.
6. Start with the four summary entities on dashboards.
7. Let the analyzer learn.
8. Use alerts as evidence, not diagnoses.
9. Tune advanced settings only when the evidence shows the defaults do not fit your system.
10. Use Home Assistant's Energy Dashboard for long-term energy charts and this integration for behavior, data quality, and circuit diagnostics.
