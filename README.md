# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration that turns circuit-level energy-meter data into useful appliance and circuit diagnostics.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=CircuitSetup&repository=CircuitSetup-Energy-Analyzer&category=Integration)

It is designed for the [CircuitSetup Expandable 6 Channel ESP32 Energy Meter Main Board](https://circuitsetup.us/index.php/product/expandable-6-channel-esp32-energy-meter/) exposed through [ESPHome ATM90E32](https://esphome.io/components/sensor/atm90e32/) sensors, but it can also work with other meters when they expose compatible Home Assistant sensor entities for:

- Power
- Current
- Voltage
- Energy
- Frequency
- Reactive power
- Apparent power
- Power factor

**CircuitSetup-first, not CircuitSetup-only:** the integration is optimized for the CircuitSetup meter layout, but other compatible meters can be used when they expose power, current, voltage, energy, frequency, reactive power, apparent power, or power factor entities with usable Home Assistant metadata.

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
- For CircuitSetup meters, ESPHome entities from an ATM90E32-based meter are the expected source (uncomment [power quality](https://github.com/CircuitSetup/Expandable-6-Channel-ESP32-Energy-Meter/blob/63c6f8935700eeee3c033c74a1d3ebdd15e706b3/Software/ESPHome/6chan_energy_meter_main_board.yaml#L80) in your config)
- Cumulative kWh sensors if you want daily energy, goals, billing-cycle, cost, utility comparison, or Energy Dashboard readiness checks.
- Current sensors, or power plus voltage, if you want capacity/amp checks.
- Mains or aggregate sensors if you want mains balance, experimental Mains NILM, solar-flow, or utility comparison features.
- An outdoor temperature sensor if you want HVAC weather context.
- A rain sensor if you want sump, well, or water-pump activity compared with rainfall and HVAC condensate context.
- A binary water-flow sensor or numeric flow-rate sensor if you want water movement compared with washer, water-heater, well-pump, or water-pump activity. Numeric flow sensors are treated as off at `0` and active when greater than `0`.

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

The setup flow is designed so you do not need to hand-write JSON or edit YAML for normal configuration.

![CircuitSetup Energy Analyzer options menu with setup actions](docs/images/readme/options-menu.png)

During setup, you choose:

| Setup item | What it is for |
|---|---|
| **Source Devices** | ESPHome meter devices, such as a CircuitSetup ATM90E32 meter. The integration expands selected devices into matching electrical sensors. |
| **Extra Source Entities** | Individual sensors that are not attached to a selected source device, or sensors you want to add manually. |
| **Mains Source Entities** | Optional whole-panel or aggregate sensors used for mains balance, experimental Mains NILM, solar-flow, and utility comparison. |
| **Outdoor Temperature Entity** | Optional outdoor temperature source used only for HVAC weather context. |
| **Rain Sensor** | Optional boolean rain sensor used to explain expected sump, well-pump, or water-pump activity. |
| **Rain Intensity Sensor** | Optional numeric precipitation-rate sensor. If available, heavier rain can raise expected pump activity more than light rain. |
| **Water Flow Sensors** | Optional binary or numeric water-flow sensors used to compare water movement with washer, water-heater, well-pump, or water-pump activity. Binary sensors are active when on; numeric flow-rate sensors are active when greater than `0`. |
| **Circuit Assignments** | The review step where you confirm which sensors belong together and how each circuit should be analyzed. |
| **Advanced Circuit Settings** | The screen used to tune thresholds, goals, billing, demand, capacity, standby, solar, and other per-circuit options after setup. |

![Source selection panel showing Source Devices and Extra Source Entities](docs/images/readme/source-selection.png)

![Circuit assignment editor showing automatic classification, included sensors, and retention controls](docs/images/readme/assignment-editor.png)

## Using The Integration

Use the integration in this order:

- **First-time setup checklist**: add the integration from **Settings > Devices & services**, select source devices/entities, then use **Appliance Circuit Assignments**.
- **Check setup health first**: `sensor.circuitsetup_energy_analyzer_setup_health` gives one next step, such as adding a cumulative kWh source, fixing stale sensors, adding rain/water-flow context, reviewing utility comparison setup, checking CT direction, or letting the analyzer learn.
- **Classify circuits deliberately**: choose the appliance type and source sensors, then review the automatically derived circuit mode and power-flow mode before trusting appliance evidence.
- **Use it day to day**: start with Health Summary, Activity Summary, Electrical Health, Energy Summary, Daily Energy Usage, and the Running binary sensor.
- **Configure the optional features you actually need**: open **Advanced Circuit Settings** for the appliance. The form only shows settings that apply to the selected appliance or circuit.
- **Practical examples**: Washer or dryer running automation, Refrigerator monitoring, HVAC or 240 V appliance review, EV charger or high-current circuit tracking, and Utility or Opower comparison.
- **When an alert appears**: read the notification, open the evidence view, compare observed and expected values, and verify source data before treating it as an appliance problem.
- **Common setup states**: learning, waiting for energy change, missing metrics, not dual phase, missing mains, and unconfigured optional checks usually mean the analyzer needs more data or a better assignment.

You do not need to enable every diagnostic entity. For behavior alerts, let the analyzer learn for at least 7 days or enough appliance cycles before tuning thresholds.

## Appliance-centered views

The generated dashboard and evidence panel are organized around appliance
questions instead of raw diagnostic entity lists:

- **Appliance Detail** combines current activity, health, electrical state,
  energy state, Today vs Normal comparisons, behavior expectations, active
  alerts, first checks, and actions for one appliance or circuit.
- **Appliance Status** keeps activity, electrical health, energy state, and
  daily usage together for each appliance without duplicate watchlist cards.
- **Today vs Normal** compares current daily energy, runtime, run count,
  estimated cost, power, demand peak, configured capacity usage, and
  solar-covered share against learned normal ranges when enough baseline data
  exists.
- **Direct meter vs Estimated by NILM** labels show whether a value is directly
  measured or inferred from mains power. NILM appliances show confidence and
  validation state; low-confidence NILM asks for review instead of implying a
  confirmed appliance fault.
- **Setup Health checklist** adds onboarding checklist attributes for source
  data, assignments, CT direction, cumulative kWh, appliance profiles,
  dashboard creation, notifications, NILM, and learning progress.
- **Advanced setting suggestions** show current value, default value, suggested
  value, what the setting controls, why the suggestion exists, expected effect,
  and reset/apply/dismiss actions.
- **Alert Evidence** starts with a visual comparison, then keeps graph-first
  evidence beside the plain-language explanation and moves technical details
  into a disclosure for deeper review.

![Appliance detail panel showing refrigerator health, activity, energy, and recent evidence](docs/images/readme/appliance-detail.png)

![Alert Evidence panel showing the observed, expected, and threshold comparison above the evidence graph](docs/images/readme/alert-evidence.png)

## First-time setup checklist

1. Install the integration, restart Home Assistant, and add it from **Settings > Devices & services**.
2. In **Source Devices**, select the ESPHome meter device or other meter device that owns your CT/channel sensors.
3. Use **Extra Source Entities** only for sensors that are not already included through a selected source device.
4. Leave **Mains Source Entities** empty unless you have whole-panel or aggregate measurements.
5. Add mains sources if you want Mains NILM, mains balance, solar-flow, or utility/Opower comparison.
6. Add an outdoor temperature entity if you want HVAC activity compared with outdoor conditions.
7. Add a rain sensor if you want sump, well, or water-pump activity adjusted for rainfall.
8. Add water-flow sensors if you want leak-style mismatch checks against water-using appliances.
9. Open **Appliance Circuit Assignments**.
10. For each detected group, confirm:
   - Whether to include the circuit.
   - The circuit name.
   - The appliance type.
   - The selected source sensors.
   - The automatically derived circuit mode and power-flow mode shown in the review text.
11. Save the configuration.
12. Let the analyzer learn before acting on behavior alerts. Most behavior checks need at least 7 days or enough appliance cycles.
13. Use **Advanced Circuit Settings** later if you need to tune thresholds, goals, billing, demand, capacity, standby, solar-flow, water context, or other feature settings.

![Setup Health checklist showing recommended setup actions for configured circuits](docs/images/readme/setup-health.png)

## Classify circuits carefully

Correct circuit classification is the most important part of setup.

In **Appliance Circuit Assignments**, you choose the appliance type and source
sensors. The integration derives circuit mode and power-flow mode from that
selection.

| Mode | Use for | Notes |
|---|---|---|
| **Single Phase** | One CT/channel tracking one main 120 V load, such as a refrigerator, washer, sump pump, microwave, or water pump. | Best for dedicated appliance circuits. |
| **Dual Phase** | Two CT/channels that are the two legs of one 240 V appliance, such as HVAC, electric heat, water heater, dryer, oven, pool pump, EV charger, or solar inverter. | Enables leg-balance and combined-appliance analysis. |
| **Mixed** | A branch circuit with multiple unrelated loads, such as plugs and lights. | The analyzer stays conservative and avoids appliance-specific claims. |
| **Mains NILM** | Whole-home mains or feed circuits. | Required for experimental whole-home load-signature discovery. |

## Review the derived power-flow mode

Power-flow mode tells the analyzer how to interpret signed watts. It is selected
automatically during guided assignment.

| Power flow | Use for | How negative watts are treated |
|---|---|---|
| **Load** | Normal consuming circuits. | Sustained negative watts usually mean CT orientation or configuration should be checked. |
| **Generation / Solar Export** | Solar inverter or generation circuits. | Negative power can be expected export/generation behavior. |
| **Mains / Net** | Signed whole-home mains measurements. | Import and export direction are preserved. |

If a normal load circuit shows sustained negative watts, check CT orientation before using that data as appliance evidence.

## Supported appliance profiles

Supported profile values include:

| Profile | Default phase/topology | Default power flow |
|---|---|---|
| `refrigerator` | Single phase | Load |
| `freezer` | Single phase | Load |
| `hvac` | Dual phase when both legs are selected; otherwise single phase | Load |
| `hvac_compressor` | Dual phase when both legs are selected; otherwise single phase | Load |
| `hvac_blower` | Single phase | Load |
| `electric_heat` | Dual phase when both legs are selected; otherwise single phase | Load |
| `water_heater` | Dual phase when both legs are selected; otherwise single phase | Load |
| `oven` | Dual phase when both legs are selected; otherwise single phase | Load |
| `microwave` | Single phase | Load |
| `washer` | Single phase | Load |
| `dryer` | Dual phase when both legs are selected; otherwise single phase | Load |
| `pool_pump` | Dual phase when both legs are selected; otherwise single phase | Load |
| `water_pump` | Dual phase when both legs are selected; otherwise single phase | Load |
| `well_pump` | Dual phase when both legs are selected; otherwise single phase | Load |
| `sump_pump` | Dual phase when both legs are selected; otherwise single phase | Load |
| `ev_charger` | Dual phase when both legs are selected; otherwise single phase | Load |
| `solar_inverter` | Dual phase | Generation |
| `mains_nilm` | Mains NILM | Mains/net |
| `motor_load` | Single phase | Load |
| `resistive_load` | Single phase | Load |
| `mixed` | Mixed | Load |

Choose the closest profile. The profile controls which checks are useful, which sensors are recommended, and how learning works. `mains_nilm` is for whole-home mains/NILM sources, not a normal appliance circuit.

## Summary-First Diagnostics

Most users should build dashboards from the summary entities first. Detailed diagnostic entities are still available, but advanced troubleshooting entities are disabled by default so Home Assistant does not record unnecessary state history unless you opt in.

The integration has an **Entity Detail Level** option under **Settings > Devices & services > CircuitSetup Energy Analyzer > Configure**:

- **Simple**: default for most homes. Enables the main summary entities, Daily Energy Usage when usable, and appliance Running sensors.
- **Standard**: also enables configured feature-status entities, such as energy goals, billing/cost, weather context, water-flow context, and other features you turned on.
- **Expert**: creates only the diagnostic or graph groups you select under **Expert Entity Groups**, useful for troubleshooting and custom diagnostic dashboards.

Changing **Entity Detail Level** reloads the integration so the entity set matches the selected profile. Expert creates only the diagnostic or graph groups you select, such as Developer Diagnostics, Energy Detail, Demand and Capacity, Mains and Solar Detail, NILM Detail, Cycle Metrics, Electrical Scores, Power Quality Drift, Billing Forecasts, Standby, Weather, and Water. Existing manual entity-registry customizations are respected; use **Migrate To Compact Entity Model** when you want to remove preserved legacy rows.

![Entity Detail Level options showing Simple, Standard, and Expert entity profiles](docs/images/readme/entity-detail-level.png)

For a configured circuit ID such as `refrigerator`, `hvac`, or `car_charger`, the main entities follow this pattern:

| Entity | Example | What it tells you |
|---|---|---|
| **Setup Health / Next Step** | `sensor.circuitsetup_energy_analyzer_setup_health` | The highest-priority setup action across the integration, with attributes for the reason, affected circuit, blocking issue count, and configuration path. |
| **Health Summary** | `sensor.<circuit>_health_summary` | Whether the circuit is ready, learning, missing data, paused, or showing a possible issue. |
| **Activity Summary** | `sensor.<circuit>_activity_summary` | What the appliance appears to be doing now: running, idle, standby, on, off, or no recent activity. |
| **Electrical Health** | `sensor.<circuit>_electrical_health` | Combined electrical condition, including power-quality, metric-consistency, and leg-balance evidence when available. |
| **Energy Summary** | `sensor.<circuit>_energy_summary` | Combined daily usage, goal, billing, cost, and high-usage evidence. |
| **Daily Energy Usage** | `sensor.<circuit>_daily_energy_usage` | Today's derived kWh when a cumulative energy source is available. |
| **Running** | `binary_sensor.<circuit>_running` | Simple on/off running state for automations. |
| **Settings Suggestions** | `sensor.<circuit>_settings_suggestions` | Count of pending advanced-setting recommendations. Available from the Expert Developer Diagnostics group or by enabling the entity. |

Use summary sensors for dashboards and automations. When a summary changes, open the entity attributes or the alert evidence page from the notification. The evidence page leads with a visual observed-versus-expected comparison and graph-first evidence, then explains what happened, why it matters, sample count, first/last seen times, and what to check first. Power-quality comparisons name the measured metric and show W, VAR, VA, power factor, or a percentage as appropriate. Use advanced detail entities only when you are investigating deeper setup or data-quality evidence.

For power-meter interpretation:

- **Watts**: what the circuit is doing right now.
- **kWh**: how much energy it used over time.
- **Amps**: how hard the circuit is loaded.
- **Power factor, reactive power, and apparent power**: electrical evidence used for health and consistency checks.

## Build a useful dashboard

The fastest path is to let the integration create a starter dashboard:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Create Or Update Dashboard**

Choose one layout:

1. **Simple**: compact appliance status, mains rollup, and energy tracking sections built from summary entities.
2. **Standard**: Simple plus feature-level mains, HVAC, solar, utility, weather, water, billing, and cost cards when matching Standard entities exist.
3. **Expert**: Standard plus the diagnostics/evidence section for appliance evidence navigation. It does not add diagnostic/detail entity cards automatically.

The dashboard form has three setup paths:

1. Create or update the recommended dashboard with the selected **Dashboard Layout**.
2. Check **Match Entity Detail Level To Layout** when the selected layout needs more analyzer entities than your current Entity Detail Level creates.
3. Check **Remove Existing Dashboard** when you want to delete the stored recommended dashboard instead of updating it.

You can also choose the preferred layout from `select.circuitsetup_energy_analyzer_dashboard_layout`, but the dashboard action still runs from Configure > Create Or Update Dashboard; there is no dashboard action button entity.

The generated dashboard uses Home Assistant's current entity registry IDs, so renamed analyzer entities are respected. It now presents a visual appliance story with Household Overview, Today's Energy, Appliance Status, Mains/Solar/NILM, Energy Tracking, Appliance Run Timeline, NILM Review, and optional weather or Diagnostics and Evidence sections when data exists. It uses registry-resolved summary and graph entities plus expert evidence links and NILM buttons instead of service-control cards. NILM review lanes use tabs to summarize Needs Review, Assigned, Published, and Ignored / Expected work; selecting a review card opens its focused inspector without repeating controls, and each decision is committed with a single **Apply** action. The dynamic dashboard NILM card can show the same lane counts when it is available. When the registry is available, absent analyzer entities are notes instead of guessed IDs. Missing, disabled, or unavailable entities are shown as dashboard notes instead of broken cards. Existing starter dashboards are matched before update so the integration does not create duplicate dashboard entries when Home Assistant returns storage items in a different shape.

For manual dashboards, start with one simple card per important appliance:

1. Activity Summary
2. Electrical Health
3. Energy Summary
4. Daily Energy Usage

Add the Running binary sensor where you want automations, such as washer finished, dryer finished, pump running, or microwave activity.

For YAML reference, an example dashboard is still included:

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

### Appliance Drilldown Pattern

When a single appliance needs review, use this pattern:

1. **Appliance status card**: Health Summary, Activity Summary, Electrical Health, Energy Summary, and Daily Energy Usage.
2. **Appliance history**: Appliance Detail starts with the configured source history for the past 7 days. Choose 24 hours, 7 days, or 30 days, hover a point for its value and timestamp, and use the graph controls to zoom or pan.
3. **Appliance automations**: Running binary sensor for washer, dryer, pump, microwave, or appliance-complete automations.
4. **Energy tracking**: Daily Energy Usage, Energy Usage Status, goals, billing, and cost where those features are enabled.
5. **Electrical review**: power-quality, metric-consistency, leg-imbalance, and capacity entities only when the summary points there.
6. **Setup and data quality**: advanced diagnostic entities, Repairs, source entity attributes, and `status_explanation`.

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

## Retained analyzer data

CircuitSetup Energy Analyzer keeps compact diagnostic evidence for its own
analysis. It does not try to replace Home Assistant's recorder, statistics, or
Energy Dashboard history.

Retention modes control time-based circuit evidence:

| Retention mode | Time window |
|---|---:|
| Lightweight | 14 days |
| Standard | 45 days |
| Diagnostic | 180 days |

Additional persisted structures have hard caps so storage cannot grow without
bound:

| Stored structure | Cap |
|---|---:|
| Alert history | 500 items or 180 days |
| Alert feedback | 500 items or 365 days; expected alert feedback expires after about 90 days, not-helpful feedback after about 45 days |
| Weather context history | 1,008 samples per circuit plus the retention window |
| Rain/water-flow context history | 1,008 samples per circuit plus the retention window |
| NILM signatures | 64 signatures per mains circuit |
| NILM unknown-load inventory | 32 unknown loads per mains circuit |
| Settings suggestions | 200 recommendations or 180 days, pending suggestions kept first |
| Settings suggestion decisions | 500 decisions or 365 days |
| Settings suggestion notification history | 100 notification episode keys |

## Optional features

Enable and tune optional features from the integration options screen. Manual YAML editing is not required.

Go to:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

![Advanced circuit settings panel showing circuit-specific sensitivity and applicable tuning sections](docs/images/readme/advanced-settings.png)

Use **Advanced Circuit Settings** to configure circuit-specific options such as:

- Energy-usage spike thresholds
- Daily energy goals
- Billing-cycle settings
- Cost and Time-of-Use estimates
- Demand settings
- Circuit capacity limits
- Dual-phase leg-imbalance settings
- Metric-consistency tolerances
- Mains-balance settings
- Solar-flow thresholds
- Standby and Always On settings
- Activity-alert sensitivity
- Rain, pump, and water-flow context

Alert sensitivity uses the same names everywhere: **Quiet**, **Balanced**, and **Sensitive**. Older stored presets are automatically migrated to those names.

Most users should configure these options from the Home Assistant UI. Developer Tools actions are available for automations, scripts, dashboards, backups, and advanced workflows, but they are not required for normal setup.

Daily actions are exposed as Home Assistant entities so you do not need to copy IDs into service calls. Use the circuit buttons and controls for normal actions. If you do call a circuit service from an automation, you can target a renamed analyzer entity instead of typing the circuit ID.

- `button.<circuit>_relearn_baseline`
- `select.<circuit>_alert_sensitivity`
- `number.<circuit>_daily_energy_goal`
- `switch.<circuit>_maintenance`

Integration-level controls are grouped on the CircuitSetup Energy Analyzer device:

- `button.circuitsetup_energy_analyzer_run_mapping_checks`
- `button.circuitsetup_energy_analyzer_recalculate_suggestions`
- `select.circuitsetup_energy_analyzer_entity_detail_level`
- `select.circuitsetup_energy_analyzer_dashboard_layout`

Dashboard create, update, and remove actions are available from **Configure > Create Or Update Dashboard**, not from a button entity.

## Normal User Paths

The integration still exposes service actions for scripts, blueprints, dashboards, backups, and Developer Tools. Those actions intentionally keep fields such as `circuit_id`, `alert_id`, `signature_id`, and `recommendation_id` for backwards compatibility and automation use.

For day-to-day use, prefer these paths instead:

| User intent | Normal path |
|---|---|
| Circuit action | Circuit action -> button/select/number entity |
| Alert action | Alert action -> evidence panel button |
| NILM signature action | NILM signature action -> NILM/evidence panel button |
| Recommendation action | Recommendation action -> Suggested Settings UI button |
| Setup/data-quality fix | Setup/data-quality fix -> Repairs flow |

This keeps IDs inside the integration wherever possible. You should not need to copy `circuit_id`, `alert_id`, `signature_id`, or `recommendation_id` from attributes into Developer Tools for ordinary setup, tuning, alert review, or appliance maintenance.

### Feedback teaches the analyzer

When you mark an alert as expected, the analyzer remembers that evidence pattern by a stable local fingerprint. Future matching evidence under similar conditions is retained for review, but it is shown as an expected pattern instead of repeatedly creating a new active possible-issue alert or notification. Expected alert feedback expires after about 90 days unless refreshed.

When you mark an alert as not helpful, the analyzer records that pattern separately from acknowledgement. Future matching evidence must repeat more times before it can become a new alert, and the evidence panel shows the adjusted repeated-evidence requirement when it applies. If the same daily energy spike pattern is repeatedly marked not helpful, the analyzer can suggest a safer daily spike ratio change for you to approve, undo, or reset to the built-in default. Not-helpful feedback expires after about 45 days unless refreshed. Acknowledgement only clears the current alert episode; it does not permanently suppress future alerts after conditions clear and recur.

When you label, ignore, mark expected, or merge an experimental NILM signature, the analyzer preserves that review decision in local storage and reflects it in the evidence panel and unknown-load inventory. Review decisions follow a stable electrical fingerprint across future reclustering when the direction, value buckets, and split-phase topology still match; substantially different signatures are treated as new review items.

Suggested settings remember apply, deny, and dismiss decisions. Denying a suggestion suppresses the same value for the same evidence during its cooldown. Dismissing hides it until the evidence changes or the recommendation expires.

| Feature | What it does | Needs |
|---|---|---|
| **Energy usage spikes** | Compares today's kWh with a learned rolling window and reports repeated high-usage evidence. | Cumulative energy sensor. |
| **Daily energy goals** | Lets you set a per-circuit daily kWh goal and receive repeated goal notices. | Cumulative energy sensor. |
| **Run-cycle diagnostics** | Tracks start count, runtime, duty cycle, and running state for appliance-style circuits. | Real-power data and enough cycles. |
| **HVAC weather context** | Compares HVAC runtime with similar outdoor temperatures before treating runtime as unusual. | HVAC-like circuit plus outdoor temperature sensor. |
| **Rain and pump correlation** | Compares pump runtime with rain, optional rain intensity, and HVAC compressor activity before flagging unusual pump behavior. | Sump pump, water pump, or well pump plus rain sensor. |
| **Water-flow correlation** | Compares binary or numeric water-flow sensors with water-using appliance activity to find unexplained flow or missing expected flow. | Water-flow sensor plus washer, water heater, water pump, or well pump. |
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
| **Experimental NILM** | Looks for recurring unknown whole-home load signatures, pairs likely on/off sessions, and lets you review or publish user-confirmed estimated appliances. | Mains aggregate source; optional known-load circuits improve results. |

## Feature notes

### Energy usage spikes

For circuits with cumulative kWh sensors, the analyzer derives daily usage from positive energy deltas. By default, it compares today's usage with a learned rolling window and treats a large repeated increase as possible issue evidence.

Use this for appliances where daily usage should usually stay within a predictable range, such as refrigerators, freezers, water heaters, HVAC, pumps, or EV charging circuits.

Configure this from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Use the energy-usage settings to adjust the comparison window and spike threshold without editing YAML.

### Seasonal and contextual baselines

Some appliances behave differently depending on weather, season, time of day, rain, water use, and solar production. The analyzer keeps compact contextual samples and compares a circuit with the most relevant learned baseline when enough similar history exists. If there is not enough matching context yet, it falls back to the existing broader rolling baseline.

This helps avoid noisy alerts when context explains the usage, such as HVAC energy on very hot summer afternoons, while still preserving conservative possible-issue evidence when behavior is unusual for the current context.

### Daily energy goals

Daily goals add a notification layer around a kWh target. Use Home Assistant's Energy Dashboard for normal energy charts; use this feature when you want per-circuit goal evidence.

Configure this from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Set a daily kWh goal for the circuit. Set the goal back to `0` to clear it.
The daily goal control is only created when the circuit has usable energy data,
so stale saved goals do not add a confusing control before a cumulative kWh
source is configured.

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

### Rain and pump correlation

Rain and pump correlation applies to `sump_pump`, `water_pump`, and `well_pump` circuits. It compares recent pump runtime with the learned dry-weather baseline, current rain state, optional rain intensity, and recent HVAC compressor activity.

This matters because a sump pump may run more during rain, and it may also run more when an AC compressor is removing humidity and sending condensate to a drain or sump. When both rain and AC activity are present, higher pump activity can be expected instead of automatically becoming a possible issue.

Configure the global rain source during setup or later from **Configure**. Tune the per-circuit rain response window and activity threshold from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

The analyzer can report weather-explained pump activity, possible excess pump activity, or possible missing pump activity. Treat those as prompts to inspect the pump, sensor mapping, discharge path, or recent weather conditions.

### Water-flow correlation

Water-flow correlation applies to `water_pump`, `well_pump`, `water_heater`, and `washer` circuits when at least one global or circuit-linked binary water-flow sensor or numeric flow-rate sensor is configured. Numeric flow-rate sensors are treated as off at `0` and active when greater than `0`.

The analyzer compares how long the water-flow sensor has been active with recent mapped appliance runtime. It can report:

- Flow without a matching water-using appliance, which can point to an unmapped load, leak, running faucet, irrigation, or sensor mapping problem.
- Appliance activity without expected flow, which can point to a stuck sensor, closed valve, dry-running pump, or assignment problem.
- A likely sensor problem when both mismatch directions repeat.

Configure global flow sensors during setup or later from **Configure**. Use **Advanced Circuit Settings** to link specific flow sensors to a specific appliance, turn off flow expectations for an appliance, or adjust the mismatch-minute threshold.

### Billing, cost, and Time-of-Use

Billing and cost features estimate usage and cost from analyzer-retained data. When matching Opower or utility current-bill usage and cost sensors are configured, the analyzer divides cost by kWh and uses that shared rate for every appliance. The read-only global **Electricity Rate** sensor shows the active rate. Without matching Opower data, it shows the value from the editable global **Fallback Electricity Rate** number on the CircuitSetup Energy Analyzer device. These estimates do not include every possible utility billing rule, such as taxes, fixed fees, tiered rates, or demand charges.

Configure per-circuit billing settings from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Configure the shared fallback rate and Time-of-Use rate, start/end times, weekdays, and label from the **CircuitSetup Energy Analyzer** device entities.

Configure matching Opower/utility usage and cost sensors from **Configure > Utility / Opower Comparison**. Use these estimates for household awareness and alerts, not for exact utility-bill reproduction.

Time-of-use settings use a time picker for the peak start/end times and a weekday selector for peak days, so normal setup does not require typing comma-separated weekday numbers.

### Demand and capacity

Demand tracking uses rolling average watts. Capacity tracking compares amps with a configured breaker or circuit rating.

Configure this from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Use the demand and capacity settings to set the breaker or circuit rating, warning threshold, and demand-window behavior.

Capacity diagnostics are operational evidence only. They do not verify breaker, wire, plug, appliance, or code suitability.

### Dual-phase leg imbalance

For 240 V loads, the analyzer can compare leg A and leg B while the appliance is drawing meaningful power. Repeated imbalance can point to:

- CT pairing mistakes
- CT orientation problems
- Phase mapping problems
- Appliance behavior changes

Configure leg-imbalance settings from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

A leg imbalance alert means "review the evidence," not "replace the appliance."

### Power metric consistency

When voltage, current, watts, VA, and power factor are available, the analyzer checks whether the reported values agree with expected AC power relationships.

A mismatch can point to:

- Source-entity mixups
- CT/channel pairing mistakes
- Incorrect units
- Stale sensors
- Calibration problems

Configure metric-consistency tolerances from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

This is especially useful with CircuitSetup/ATM90E32 data because multiple electrical measurements are available per channel.

### Mains balance

Mains balance compares whole-home mains power with the sum of directly monitored load circuits.

A positive balance often represents ordinary unmonitored loads, such as lights or plug loads. A strongly negative balance can suggest CT direction, phase pairing, solar configuration, multiplier, or double-counting problems.

Configure mains-balance settings from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

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

Configure solar-flow thresholds from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

This feature is read-only. Use ordinary Home Assistant automations if you want to turn on an EV charger, water heater, pool pump, or other flexible load when solar surplus is available.

### Utility / Opower comparison

Utility comparison checks whether utility-reported kWh roughly agrees with measured kWh over the same period.

Configure it on a mains or aggregate circuit. You can use a utility/Opower entity, a recorder statistic ID, or let the analyzer choose automatically when possible.

Utility comparison settings are available from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Before acting on a mismatch, verify that the utility and measured sources cover the same time period. Utility integrations can update late.

### Always On and standby

For load circuits with real-power data, the analyzer estimates an Always On load from the lowest retained power level in the standby window. It can also classify the current state as off, standby, or on.

Configure this from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

Use the standby and Always On settings to set standby thresholds, Always On alert limits, and related sensitivity options.

### Experimental NILM

Experimental NILM is opt-in. It can look for recurring unknown load signatures from mains or mixed circuits, especially when known directly monitored circuits are masked out. With a mains source, the NILM workspace can also pair compatible on/off edges, show known-load overlays, and turn graph interval selections directly into appliance assignments for review.

On generated Standard and Expert dashboards, use **Open NILM Graph & Review** in the **Mains, Solar, and NILM** section to open the mains NILM workspace. The compact summary shows the circuit, needs-review count, and review progress without repeating the lane inventory. Start with the graph, move between lane tabs, select a review card, and make the decision in the focused inspector. Assignment edits enable **Save** only after the name or type changes, while **Merge** remains a separate action. Successful interval, assignment, and session actions refresh beside the graph without moving you away from the current graph window or resulting review lane.

![NILM workspace showing needs-review signatures, review lanes, and load labeling actions](docs/images/readme/experimental-nilm.png)

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

Open the separate NILM workspace route from the evidence panel to label signatures, drag across the graph to select one or more appliance intervals, merge duplicate signatures, and create an estimated Home Assistant device for a confirmed assignment. **Label appliance interval** collects the appliance name and type, highlights the active graph selection and matching time fields, and sends the saved evidence directly to Needs Review. Assignment cards show confirmed/rejected sessions, false-positive and false-negative rates, and power/energy error when matching data is available. The workspace groups work into four lanes: Needs Review, Assigned, Published, and Ignored / Expected. Lane tabs keep the queue scannable while the selected review card's focused inspector owns its choices and single **Apply** decision. The dynamic dashboard NILM card can show the same lane counts when it is available. Published NILM appliances are marked as estimated and can expose estimated running, power, daily energy, health, activity, and energy summaries. Keep assignments unpublished until the workspace evidence looks trustworthy; use **Remove HA Device** or **Retire** when an estimate should stop creating entities. NILM estimates are inferred from aggregate power and are not safety evidence.

## Suggested settings

After enough history, the analyzer can suggest advanced settings based on observed evidence. These are tuning recommendations for thresholds and windows, not appliance diagnoses.

Review them from:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Review Suggested Settings**

![Suggested settings review panel showing evidence-backed advanced-setting recommendations](docs/images/readme/suggested-settings.png)

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
4. Use the **Open evidence** link to review the visual comparison, evidence graph, explanation, and response choices.
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

Persistent notifications include one final Markdown link to **Open evidence** when the analyzer has enough context. The link uses the `evidence_path` attribute and opens the dynamic Alert Evidence panel at `/circuitsetup-energy-analyzer-evidence`.

The dynamic Alert Evidence panel reads the alert payload, including `graph_entities`, and dynamically selects graph entities for appliance, mains, nilm, weather-context, and energy-overview cards. It presents a visual comparison before graph-first evidence and the explanation, then keeps the three response choices together behind one **Apply** action. Companion App notifications can use the same target through `clickAction`.

The analyzer can also notify when suggested Advanced Circuit Settings are ready for review. Those notifications link directly to **Review Suggested Settings** in the evidence panel.

For a dashboard-first view of the same concepts, see `docs/dashboard-example.yaml`.

![Home Assistant notification drawer showing an appliance-first Energy Analyzer alert with one final evidence link](docs/images/readme/notifications-panel.png)

![Dynamic Energy Analyzer alert evidence opened from a notification link](docs/images/readme/alert-evidence.png)

![Alert evidence panel showing observed and expected metrics with investigation context](docs/images/readme/notifications-repairs.png)

## Alert automation blueprint

The repository includes a Home Assistant automation blueprint:

```text
blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml
```

Use it to create persistent notifications or custom follow-up actions when selected analyzer entities report possible issue states.

Companion App mobile notifications can use the `evidence_path` template variable for `data.url` and Android `data.clickAction`, so tapping the notification opens the same Home Assistant evidence view.

## Practical automations

Automations can be created from the Home Assistant automation editor. Manual YAML editing is not required for normal setup or advanced circuit settings.

The examples below show the underlying automation/action structure for users who prefer YAML or want to copy service calls into scripts, blueprints, or Developer Tools.

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

Use the circuit Pause alerts switch before servicing an appliance, replacing equipment, moving CTs, or making wiring changes that could make analyzer evidence temporarily misleading.

```yaml
action: circuitsetup_energy_analyzer.start_maintenance
data:
  circuit_id: refrigerator
  note: Cleaned coils
  duration: "02:00:00"
  relearn_on_end: false
```

Resume alerts and optionally relearn:

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

## Optional Developer Tools actions

Most users should configure the analyzer from the Home Assistant UI:

**Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Advanced Circuit Settings**

The service actions below are optional. They are useful when you want to call analyzer functions from Home Assistant automations, scripts, dashboards, blueprints, or Developer Tools.

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
| Experimental NILM | `label_nilm_signature`, `ignore_nilm_signature`, `mark_nilm_signature_expected`, `merge_nilm_signatures`, `label_nilm_interval`, `delete_nilm_label_interval`, `generate_nilm_sensor_label_intervals`, `assign_signature_to_appliance`, `assign_session_to_appliance`, `assign_interval_to_appliance`, `validate_nilm_session`, `reject_nilm_session`, `validate_nilm_assignment_history`, `rename_nilm_appliance`, `change_nilm_appliance_profile`, `merge_nilm_assignments`, `publish_nilm_appliance_assignment`, `unpublish_nilm_appliance_assignment`, `retire_nilm_appliance_assignment` |
| Suggested settings | `recalculate_setting_recommendations`, `apply_setting_recommendation`, `deny_setting_recommendation`, `dismiss_setting_recommendation` |
| Export and diagnostics | `export_diagnostics`, `export_history_csv`, `run_mapping_checks` |

When calling actions manually or from an automation, set `circuit_id` to the configured circuit ID, such as `refrigerator`, `hvac`, `car_charger`, or `mains`.

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

Example source entity names commonly look like this:

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| Energy | `sensor.<appliance>_energy` | Cumulative kWh source used for daily usage, billing, goals, and utility comparison. | Source entity selected by the user. | Increasing kWh total |
| Active Power | `sensor.<appliance>_active_power` or `sensor.<appliance>_watts` | Instantaneous real power used for activity, demand, NILM, balance, and run-cycle checks. | Source entity selected by the user. | Watts, including signed watts when the meter reports export |

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

Use **Entity Detail Level** for normal entity creation: Simple keeps the core summary set, Standard adds configured feature entities, and Expert creates only the selected diagnostic or graph groups. You can still use Home Assistant's entity registry for one-off manual entity changes.

## Compact entity model

The analyzer uses a compact entity model so Home Assistant gets appliance-focused
entities instead of every intermediate calculation as a standalone entity.

- **Simple** creates summary entities, Running, Daily Energy Usage when available,
  and the small daily control set.
- **Standard** adds canonical status and graph entities for features you configured.
- **Expert** adds only the diagnostic or graph groups you explicitly select.

See `docs/entity-model.md` for the full compact model and migration notes.

Existing installs can keep enabled legacy entities for one compatibility release
so dashboards and automations do not break during upgrade. To migrate explicitly,
open **Settings > Devices & services > CircuitSetup Energy Analyzer > Configure >
Migrate To Compact Entity Model**. The preview lists entities that will be
removed, replacements, entities that will remain, the new maintenance switch,
before/after counts, and any customization warning.

Legacy replacement highlights:

| Legacy replacement | Compact location |
|---|---|
| Sensitivity sensor | `select.<circuit>_alert_sensitivity` |
| Readiness and learning progress | `sensor.<circuit>_health_summary` attributes |
| Data quality checklist | Setup Health, Repairs, and Health Summary attributes |
| Alert evidence and last event | Dynamic Alert Evidence panel and recent activity |
| Power-quality evidence and metric/leg status | `sensor.<circuit>_electrical_health` attributes |
| Run-cycle status | `sensor.<circuit>_activity_summary` and `binary_sensor.<circuit>_running` |
| Billing and cost forecast/status details | `sensor.<circuit>_billing_cycle_usage` and `sensor.<circuit>_cost_cycle` attributes |
| Standby threshold | Advanced Circuit Settings and `sensor.<circuit>_standby_status` attributes |
| Outdoor temperature mirror | configured outdoor temperature source entity and Weather Context attributes |
| Pause/Resume Alerts controls | `switch.<circuit>_maintenance` |

## Sensor reference

The analyzer creates entities based on the circuit mode, appliance profile, source sensors, enabled feature settings, and the selected **Entity Detail Level**. Not every circuit will have every entity.

In the **Visibility** column:

- **Core/default visible** means created in Simple, Standard, and Expert when the circuit has the required source data.
- **Standard feature entity** means created in Standard and Expert when the related feature, circuit type, and source data apply.
- **Expert group** means created only when Entity Detail Level is Expert and that Expert Entity Group is selected.
- **Legacy compatibility** means preserved for existing installs during the compatibility window; new dashboards should use the listed replacement.

In the patterns below, `<circuit>` is the configured circuit ID, such as `refrigerator`, `hvac`, `car_charger`, `solar`, or `mains`.

### Core Appliance Status Sensors

Start with these on dashboards.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| Setup Health / Next Step | `sensor.circuitsetup_energy_analyzer_setup_health` | One integration-level next step for setup, source-data quality, context-source setup, utility comparison setup, and learning readiness. Attributes include `ready`, `issue_count`, `next_step`, `recommended_action`, `affected_circuits`, `stale_sources`, `stale_source_circuits`, grouped issue lists, `open_path`, `reason`, and the full issue list with `circuit_id`, `issue`, `fix`, and `source_entities`. | Core/default visible. | `Ready`, `Review circuit assignments`, `Add cumulative kWh source`, `Fix stale source sensor`, `Check CT direction`, `Let analyzer learn`, `Configure breaker amps`, `Add mains source`, `Add outdoor temperature source`, `Add rain source`, `Add water-flow source`, `Review utility comparison` |
| Health Summary | `sensor.<circuit>_health_summary` | One short state for the circuit or appliance. It rolls learning, readiness, data quality, maintenance, and possible issue evidence into one dashboard-friendly value. | Core/default visible for configured circuits. | `Ready`, `Learning`, `Needs data`, `Possible issue`, `Paused`, `Mixed observation`, `NILM review` |
| Activity Summary | `sensor.<circuit>_activity_summary` | Human-readable activity state with run-cycle and standby context in attributes. | Core/default visible for configured circuits. | `Running`, `Idle`, `Standby`, `On`, `Off`, `No Activity` |
| Electrical Health | `sensor.<circuit>_electrical_health` | Combined electrical condition for power quality, metric consistency, dual-phase balance, mains balance, and solar flow. | Core/default visible for configured circuits. | `Normal`, `Needs Metrics`, `Possible Imbalance`, `Possible Metric Mismatch`, `Possible Power Quality Change` |
| Energy Summary | `sensor.<circuit>_energy_summary` | Combined daily usage, goals, billing, cost, and high-usage evidence. | Core/default visible for configured circuits. | `Normal`, `Learning`, `Needs Energy Data`, `Watch`, `High Usage` |
| Daily Energy Usage | `sensor.<circuit>_daily_energy_usage` | Today's kWh derived from a cumulative energy source. | Core/default visible when usable energy data exists. | `0.0 kWh` and higher daily totals |
| Running | `binary_sensor.<circuit>_running` | Simple appliance-running state for automations. | Core/default visible for appliance circuits with active-power sensors. | `on`, `off` |

Daily Energy Usage can show 0 kWh for two different reasons: true zero usage, or `Waiting For Energy Change` / `waiting_for_delta` when the analyzer has not observed a cumulative kWh increase yet.

### Running Vs Observations Vs Alerts

- Running is the current operating state used for automations.
- Observation recorded means the analyzer noticed something unusual, but one observation alone is not an alert.
- Possible issue means repeated evidence crossed the alert threshold.

### Core diagnostic and evidence sensors

These help explain why a summary changed. They are useful for troubleshooting, automations, and temporary diagnostic dashboards.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Anomaly Score** | `sensor.<circuit>_anomaly_score` | Numeric summary of current repeated anomaly evidence. | Expert Developer Diagnostics group. | `0.0` when quiet; higher values as evidence accumulates |
| **Energy Dashboard Status** | `sensor.<circuit>_energy_dashboard_status` | Whether the configured energy or power source has metadata that Home Assistant's Energy Dashboard can use. | Expert Energy Detail group. | `ready`, `needs_energy_source`, or metadata issue states |
| **Recent Activity** | `sensor.<circuit>_recent_activity` | Latest retained start, stop, steady-window, or possible-issue event. Attributes show a bounded preview of up to five recent items; use the evidence panel or diagnostics for the full retained timeline. | Expert Developer Diagnostics group. | `No recent activity`, `start`, `stop`, issue summary text |
| **Settings Suggestions** | `sensor.<circuit>_settings_suggestions` | Count of pending advanced-setting recommendations. Attributes show a bounded preview of up to five suggestions with IDs, setting labels, current values, and suggested values. Open Review Suggested Settings or the evidence panel for full evidence and actions. | Expert Developer Diagnostics group. | `0`, `1`, or higher counts |

### Appliance behavior and power-quality sensors

These are most useful for dedicated appliance circuits such as refrigerators, freezers, HVAC, electric heat, water heaters, ovens, washers, dryers, pumps, EV chargers, motor loads, and resistive loads. Mixed circuits may expose fewer appliance-specific signals.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Power Quality Score** | `sensor.<circuit>_power_quality_score` | Numeric score for observed voltage, current, PF, VAR, or VA relationship changes. | Expert Electrical Scores group. | `0.0` when quiet; higher values when relationships drift |
| **Reactive Power Drift** | `sensor.<circuit>_reactive_power_drift` | Ratio-style drift in VAR behavior compared with the learned baseline. | Expert Power Quality Drift group. | `0.0` or positive drift values |
| **Apparent Power Drift** | `sensor.<circuit>_apparent_power_drift` | Ratio-style drift in VA behavior compared with the learned baseline. | Expert Power Quality Drift group. | `0.0` or positive drift values |
| **Power Factor Drift** | `sensor.<circuit>_power_factor_drift` | Ratio-style drift in power factor compared with the learned baseline. | Expert Power Quality Drift group. | `0.0` or positive drift values |
| **Run Cycle Count** | `sensor.<circuit>_run_cycle_count` | Today's retained start count for cyclic appliances. | Expert Cycle Metrics group. | Integer cycle counts |
| **Run Cycle Runtime** | `sensor.<circuit>_run_cycle_runtime` | Today's total active runtime from retained start/stop evidence. | Expert Cycle Metrics group. | Seconds |
| **Run Cycle Duty Cycle** | `sensor.<circuit>_run_cycle_duty_cycle` | Percent of today spent active. | Expert Cycle Metrics group. | `0` to `100%` |
| **Weather Context** | `sensor.<circuit>_weather_context` | HVAC weather-adjusted activity state. Attributes can include outdoor temperature, temperature bin, observed runtime, duty cycle, expected range, and explanation. | Standard feature entity for HVAC-like circuits when outdoor temperature context is configured. | `No Temperature Source`, `Learning`, `Weather Correlated`, `Above Weather-Adjusted Range` |
| **Rain Pump Correlation** | `sensor.<circuit>_rain_pump_correlation` | Pump runtime compared with rain, optional rain intensity, HVAC compressor context, and learned dry-weather runtime. Attributes include rain source, rain activity, compressor context, observed runtime, dry baseline, and explanation. | Standard feature entity for sump pump, water pump, and well pump circuits when a rain source is configured. | `Unconfigured`, `Learning`, `Normal`, `Rain Explained`, `Compressor Explained`, `Weather Explained`, `Possible Excess Pump Activity`, `Possible Missing Pump Activity` |
| **Water Flow Correlation** | `sensor.<circuit>_water_flow_correlation` | Boolean water-flow activity compared with mapped water-using appliance runtime. Attributes include flow sources, active-flow minutes, appliance runtime, mismatch minutes, and explanation. | Standard feature entity for water pump, well pump, water heater, and washer circuits when a global or circuit-linked flow sensor is configured. | `Unconfigured`, `Learning`, `Normal`, `Possible Flow Without Load`, `Possible Load Without Flow`, `Possible Sensor Problem`, `Sensor Unavailable` |
| **Water Flow Mismatch Minutes** | `sensor.<circuit>_water_flow_mismatch_minutes` | Current minutes of unexplained flow or water-using appliance activity. | Expert Water group. | Minutes |
| **Metric Consistency Score** | `sensor.<circuit>_metric_consistency_score` | Largest W/VA/PF consistency mismatch. | Expert Electrical Scores group. | Percentage mismatch |

### Energy usage, goals, billing, and cost sensors

These require cumulative energy inputs. Use Home Assistant's Energy Dashboard for normal energy history; these entities exist for analyzer evidence, alerts, and per-circuit summaries.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Daily Energy Usage** | `sensor.<circuit>_daily_energy_usage` | Today's kWh derived from positive cumulative-energy deltas. | Core/default visible when energy data exists. | `kWh` |
| **Energy Usage Share** | `sensor.<circuit>_energy_usage_share` | Today's usage as a percent of the learned rolling energy window. | Expert Energy Detail group. | Percentage values |
| **Energy Usage Status** | `sensor.<circuit>_energy_usage_status` | Daily kWh tracker state. Use this to tell true zero usage from "waiting for first kWh increase." | Expert Energy Detail group. | `waiting_for_delta`, `learning`, `tracking`, `over_threshold` |
| **Energy Goal Usage** | `sensor.<circuit>_energy_goal_usage` | Today's usage as a percent of the configured daily goal. | Expert Energy Detail group. | Percentage values |
| **Energy Goal Status** | `sensor.<circuit>_energy_goal_status` | Daily goal tracker state. | Expert Energy Detail group. | `unconfigured`, `tracking`, `near_goal`, `over_goal` |
| **Billing Cycle Usage** | `sensor.<circuit>_billing_cycle_usage` | Current billing-cycle kWh for the circuit. | Standard feature entity when billing tracking exists. | `kWh` |
| **Cost Cycle** | `sensor.<circuit>_cost_cycle` | Current cycle cost estimate. | Standard feature entity when cost tracking exists. | Numeric cost estimates |

### Demand, capacity, and dual-phase sensors

These are aimed at high-power circuits such as HVAC, electric heat, water heaters, ovens, dryers, pool pumps, water pumps, sump pumps, EV chargers, mains feeds, and similar loads.

Capacity sensors require either current sensors or real power plus voltage, and a configured breaker or capacity value.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Current Demand** | `sensor.<circuit>_current_demand` | Current rolling average demand. | Expert Demand and Capacity group. | Watts |
| **Peak Demand** | `sensor.<circuit>_peak_demand` | Highest rolling demand observed today. | Expert Demand and Capacity group. | Watts |
| **Demand Limit Usage** | `sensor.<circuit>_demand_limit_usage` | Current demand as a percent of a configured demand limit. | Expert Demand and Capacity group. | Percentage values |
| **Demand Peak Rank** | `sensor.<circuit>_demand_peak_rank` | Rank of the current rolling demand among retained monthly peak windows. | Expert Demand and Capacity group. | `0` when unavailable; integer ranks such as `1`, `2`, `3` |
| **Demand Peak Status** | `sensor.<circuit>_demand_peak_status` | Whether current demand is notable for the month. | Expert Demand and Capacity group. | `unavailable`, `below_monthly_peak`, `near_monthly_peak`, `monthly_peak` |
| **Demand Status** | `sensor.<circuit>_demand_status` | Demand tracker state. | Expert Demand and Capacity group. | `unconfigured`, `tracking`, over-limit evidence states |
| **Circuit Capacity Usage** | `sensor.<circuit>_capacity_usage` | Current amps as a percent of configured circuit capacity. | Standard feature entity when capacity is configured. | Percentage values |
| **Circuit Capacity Status** | `sensor.<circuit>_capacity_status` | Capacity tracker state. | Expert Demand and Capacity group. | `unconfigured`, `missing_current`, `tracking`, `over_limit` |
| **Leg Imbalance** | `sensor.<circuit>_leg_imbalance` | Difference between dual-phase legs while the load is meaningful. | Standard feature entity for dual-phase circuits. | Percentage imbalance |

### Mains NILM, balance, solar, and utility comparison sensors

These apply mainly to whole-home mains circuits, Mains NILM circuits, homes with solar generation, and homes using utility or Opower comparison data.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **NILM Discovered Signatures** | `sensor.<circuit>_nilm_discovered_signatures` | Count of recurring aggregate NILM signatures. | Expert NILM Detail group. | Integer counts |
| **NILM Unknown Loads** | `sensor.<circuit>_nilm_unknown_loads` | Count of recurring unknown mains NILM virtual loads. Attributes show a bounded preview of up to five unknown loads with signature ID, display name, likely type, typical watts, confidence, and first seen time. Open the evidence panel for the full review inventory and actions. | Expert NILM Detail group. | `0`, `1`, or higher counts |
| **NILM Unmatched Load Percentage** | `sensor.<circuit>_nilm_unmatched_load_percentage` | Share of current aggregate mains power not matched to known loads. | Expert NILM Detail group. | Percentage values |
| **NILM Topology Status** | `sensor.<circuit>_nilm_topology_status` | Mains topology evidence for known-load matches. | Expert NILM Detail group. | `no_match`, `topology_match`, `topology_mismatch`, `leg_mismatch` |
| **Balance Power** | `sensor.<circuit>_balance_power` | Mains real power minus summed monitored load power. Positive values usually mean unmonitored load; strongly negative values can suggest mapping or sign issues. | Expert Mains and Solar Detail group. | Watts |
| **Monitored Power** | `sensor.<circuit>_monitored_power` | Sum of directly monitored non-generation load circuits. | Expert Mains and Solar Detail group. | Watts |
| **Known Load Share** | `sensor.<circuit>_monitored_coverage` | Shows how much of current mains power is explained by selected monitored load circuits. Low values usually mean normal unmonitored loads; values over `100%` can indicate CT sign, double-counting, solar/export, or mapping issues. | Expert Mains and Solar Detail group. | Percentage values |
| **Balance Status** | `sensor.<circuit>_balance_status` | Mains balance state. | Expert Mains and Solar Detail group. | `missing_mains`, `tracking`, `negative_balance` |
| **Solar Generation Power** | `sensor.<circuit>_solar_generation_power` | Instantaneous solar generation. | Expert Mains and Solar Detail group. | Watts |
| **Solar Site Consumption Power** | `sensor.<circuit>_solar_site_consumption_power` | Estimated site consumption from solar generation plus signed grid power. | Legacy compatibility; use Solar Flow Status attributes and the evidence panel. | Watts |
| **Solar Grid Import Power** | `sensor.<circuit>_solar_grid_import_power` | Current grid import. | Legacy compatibility; use Solar Flow Status attributes and the evidence panel. | Watts |
| **Solar Grid Export Power** | `sensor.<circuit>_solar_grid_export_power` | Current grid export. | Legacy compatibility; use Solar Flow Status attributes and the evidence panel. | Watts |
| **Solar Self Consumption** | `sensor.<circuit>_solar_self_consumption` | Percent of generated solar consumed on site. | Legacy compatibility; use Solar Flow Status attributes and the evidence panel. | Percentage values |
| **Solar Powered** | `sensor.<circuit>_solar_powered` | Percent of current site load powered by solar. | Legacy compatibility; use Solar Flow Status attributes and the evidence panel. | Percentage values |
| **Solar Flow Status** | `sensor.<circuit>_solar_flow_status` | Instantaneous solar-flow state. | Expert Mains and Solar Detail group. | `missing_mains`, `missing_generation`, `no_generation`, `importing`, `exporting`, `self_powered`, `inconsistent_export` |
| **Solar Surplus Power** | `sensor.<circuit>_solar_surplus_power` | Exported solar available as surplus. | Expert Mains and Solar Detail group. | Watts |
| **Solar Load Shift Power** | `sensor.<circuit>_solar_load_shift_power` | Surplus power above the configured load-shift threshold. Attributes show a bounded preview of up to five flexible-load candidates with counts for hidden candidates. | Legacy compatibility; use Solar Surplus Power and the evidence panel. | Watts |
| **Solar Flexible Load Power** | `sensor.<circuit>_solar_flexible_load_power` | Current power used by flexible loads such as EV chargers, water heaters, HVAC, or pool pumps. | Legacy compatibility; use load-shift evidence. | Watts |
| **Solar Flexible Load Coverage** | `sensor.<circuit>_solar_flexible_load_coverage` | Percent of active flexible-load power estimated to be solar-covered. | Legacy compatibility; use load-shift evidence. | Percentage values |
| **Solar Load Shift Status** | `sensor.<circuit>_solar_load_shift_status` | Flexible-load solar support state. Attributes show the same bounded flexible-load candidate preview as Solar Load Shift Power. | Legacy compatibility; use Solar Surplus Status and the evidence panel. | `not_applicable`, `waiting_for_surplus`, `surplus_candidate`, `active_solar_supported`, `active_grid_supported` |
| **Solar Surplus Status** | `sensor.<circuit>_solar_surplus_status` | Solar surplus state. | Expert Mains and Solar Detail group. | `missing_mains`, `missing_generation`, `no_generation`, `no_surplus`, `surplus_available`, `high_surplus`, `inconsistent_export` |
| **Utility Comparison Difference** | `sensor.<circuit>_utility_comparison_difference` | Difference between measured kWh and utility/Opower kWh. | Legacy compatibility; use Utility Comparison Status attributes. | Percentage difference |
| **Utility Comparison Status** | `sensor.<circuit>_utility_comparison_status` | Utility comparison state. | Expert Mains and Solar Detail group. | `unconfigured`, `missing_utility`, `missing_measured`, `tracking`, `mismatch` |

### Standby and Always On sensors

These apply to non-mains load circuits with real-power data. They are useful for refrigerators, freezers, pumps, HVAC blower circuits, motor loads, electronics, and appliances with known standby behavior.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Always On Power** | `sensor.<circuit>_always_on_power` | Lowest retained power level in the standby window. | Standard feature entity for non-mains load circuits. | Watts |
| **Standby Status** | `sensor.<circuit>_standby_status` | Current standby state. | Standard feature entity for non-mains load circuits. | `learning`, `off`, `standby`, `on` |
| **Always On Limit Usage** | `sensor.<circuit>_always_on_limit_usage` | Always-on estimate as a percent of the configured limit. | Expert Standby group. | Percentage values |

### Binary sensors

Diagnostic binary sensors are created for configured circuits. Operational binary sensors appear only when the circuit has the required profile and source data.

| Friendly name | Entity pattern | Purpose | Visibility | Possible outputs |
|---|---|---|---|---|
| **Learning** | `binary_sensor.<circuit>_learning` | On while the circuit is still learning baseline evidence. | Expert Developer Diagnostics group. | `on`, `off` |
| **Data Quality Problem** | `binary_sensor.<circuit>_data_quality_problem` | On when the circuit has a current source-data quality issue. | Expert Developer Diagnostics group. | `on`, `off` |
| **Maintenance** | `binary_sensor.<circuit>_maintenance` | Legacy diagnostic state for maintenance; use `switch.<circuit>_maintenance` for normal maintenance control. | Expert Developer Diagnostics group. | `on`, `off` |
| **Running** | `binary_sensor.<circuit>_running` | On when watts exceed the appliance running threshold or the cycle analyzer reports `running`. Not created for mixed circuits, Mains NILM, or solar inverter feeds. | Core/default visible for appliance circuits. | `on`, `off` |
| **Water Flow Mismatch** | `binary_sensor.<circuit>_water_flow_mismatch` | On when water-flow correlation currently has possible flow/load mismatch evidence. | Standard feature entity for water pump, well pump, water heater, and washer circuits when a global or circuit-linked flow sensor is configured. | `on`, `off` |

## Status Glossary

Common status values include:

| Display label | Raw status | Meaning |
|---|---|---|
| Active Grid Supported | `active_grid_supported` | A flexible load is running, but current solar surplus does not cover it. |
| Active Solar Supported | `active_solar_supported` | A flexible load is running and appears to be covered by current solar surplus. |
| Apparent Power Mismatch | `apparent_power_mismatch` | Reported VA does not match the relationship expected from voltage, current, and real power. |
| Consistent | `consistent` | The available measurements are internally consistent. |
| Exporting | `exporting` | Signed mains power currently indicates grid export. |
| High Surplus | `high_surplus` | Solar export is above the configured high-surplus threshold. |
| Idle | `idle` | The circuit is below the active-load threshold for this check. |
| Imbalanced | `imbalanced` | Dual-phase leg difference is repeatedly above the warning threshold. |
| Importing | `importing` | Signed mains power currently indicates grid import. |
| Inconsistent Export | `inconsistent_export` | Grid export is larger than measured generation; check solar/mains mapping. |
| Leg Mismatch | `leg_mismatch` | Mains NILM evidence repeatedly points to a different split-phase leg than the assignment. |
| Metric Mismatch | `metric_mismatch` | One or more power relationships changed beyond tolerance. |
| Missing Current | `missing_current` | The check needs a current sensor, or enough power and voltage data to estimate current. |
| Missing Generation | `missing_generation` | Solar-flow checks need at least one generation circuit. |
| Missing Mains | `missing_mains` | The check needs a mains, whole-home, or aggregate source. |
| Missing Measured | `missing_measured` | Utility comparison needs a measured kWh source. |
| Missing Metrics | `missing_metrics` | The check needs more matching voltage, current, real power, apparent power, or power factor sensors. |
| Missing Utility | `missing_utility` | Utility comparison needs a utility or Opower source. |
| Mismatch | `mismatch` | The measured value differs from the comparison source beyond tolerance. |
| Monthly Peak | `monthly_peak` | The current rolling demand is the highest retained monthly demand window. |
| Near Goal | `near_goal` | Daily energy usage is near the configured goal threshold. |
| Near Monthly Peak | `near_monthly_peak` | The current rolling demand is near the highest retained monthly demand windows. |
| Negative Balance | `negative_balance` | Monitored load power is higher than mains power beyond tolerance; check mapping, signs, solar, or CT orientation. |
| No Activity | `no_activity` | No recent run-cycle activity has been observed. |
| No Budget | `no_budget` | No billing-cycle budget is configured. |
| No Generation | `no_generation` | No solar generation is currently being measured. |
| No Match | `no_match` | No matching NILM event has been observed yet. |
| No Monitored Circuits | `no_monitored_circuits` | Mains balance needs at least one monitored load circuit. |
| No Surplus | `no_surplus` | No solar export surplus is currently available. |
| Not Applicable | `not_applicable` | The check does not apply to the current circuit configuration. |
| Not Dual Phase | `not_dual_phase` | The check only applies to dual-phase circuits. |
| Off | `off` | Latest power is below the configured standby threshold. |
| On | `on` | Latest power is above the standby range. |
| Over Budget | `over_budget` | Billing-cycle usage is over the configured budget. |
| Over Goal | `over_goal` | Daily energy usage is over the configured goal. |
| Over Limit | `over_limit` | The measured value is above a configured limit. |
| Over Threshold | `over_threshold` | The measured value is above a configured threshold. |
| Possible Excess Pump Activity | `possible_excess_pump_activity` | Pump activity is above the weather-adjusted expected range. |
| Possible Flow Without Load | `possible_flow_without_load` | Water flow has been active without matching mapped appliance activity. |
| Possible Issue | `possible_issue` | Repeated evidence crossed an alert threshold. |
| Possible Load Without Flow | `possible_load_without_flow` | A mapped water-using appliance appears active without matching water-flow sensor activity. |
| Possible Missing Pump Activity | `possible_missing_pump_activity` | Rain or HVAC condensate context suggests pump activity may be expected but has not been observed. |
| Possible Sensor Problem | `possible_sensor_problem` | Flow and appliance evidence conflict in both directions, so the flow sensor or mapping may need review. |
| Power Factor Mismatch | `power_factor_mismatch` | Reported power factor does not match real power divided by apparent power. |
| Projected Over Budget | `projected_over_budget` | Current usage projects above the billing-cycle budget. |
| Ready | `ready` | The analyzer has enough data for this check. |
| Running | `running` | The circuit is currently above the active-load threshold. |
| Self Powered | `self_powered` | Solar generation is approximately covering current site load. |
| Standby | `standby` | Latest power is within the configured standby range. |
| Surplus Available | `surplus_available` | Solar export is above the configured surplus threshold. |
| Surplus Candidate | `surplus_candidate` | An idle flexible load could be a candidate while solar surplus is available. |
| Rain Explained | `rain_explained` | Pump activity is higher than dry baseline and rain context explains the increase. |
| Compressor Explained | `compressor_explained` | Pump activity is higher than dry baseline and HVAC compressor condensate context explains the increase. |
| Weather Explained | `weather_explained` | Pump activity is higher than dry baseline and combined rain/HVAC context explains the increase. |
| Topology Match | `topology_match` | Mains NILM evidence matches the configured circuit mode. |
| Topology Mismatch | `topology_mismatch` | Mains NILM evidence conflicts with the configured circuit mode. |
| TOU Peak | `tou_peak` | Current time is inside the configured time-of-use peak period. |
| Tracking | `tracking` | The analyzer has enough inputs and is tracking this check. |
| Unavailable | `unavailable` | This check does not have enough retained data yet. |
| Unconfigured | `unconfigured` | This optional check has not been configured. |
| Waiting For Energy Change | `waiting_for_delta` | A cumulative kWh source is present, but no positive energy increase has been observed. |
| Waiting For Surplus | `waiting_for_surplus` | No idle flexible load currently has enough solar surplus. |

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
9. Tune advanced settings from **Configure > Advanced Circuit Settings** when the evidence shows the defaults do not fit your system.
10. Use Home Assistant's Energy Dashboard for long-term energy charts and this integration for behavior, data quality, and circuit diagnostics.
