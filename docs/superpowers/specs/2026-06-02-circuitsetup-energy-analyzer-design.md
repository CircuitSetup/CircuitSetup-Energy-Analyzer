# CircuitSetup Energy Analyzer Design

## Goal

Build a HACS-installable Home Assistant custom integration that analyzes power-quality and appliance-behavior changes from CircuitSetup 6 Channel Energy Meter data exposed through ESPHome's ATM90E32 component.

The integration should help users understand when an individual monitored circuit has changed from its learned normal behavior. It should be conservative: it reports evidence of changed behavior and possible issues, not definitive appliance diagnoses.

## Current Context

This repository is greenfield. The integration will be built as a Home Assistant custom integration under `custom_components/circuitsetup_energy_analyzer` and packaged so users can install and update it through HACS.

The source energy data is expected to come from ESPHome entities created by the ATM90E32 component on CircuitSetup 6 Channel Energy Meter hardware. Useful values include voltage, current, real power, reactive power, apparent power, power factor, energy, and frequency where available.

Power, reactive power, power factor, and energy readings depend on correct voltage-phase and CT/current-channel pairing. The integration must treat missing, inverted, stale, or phase-mismatched data as a data-quality problem before attempting appliance-health analysis.

## Architecture

The project will use a Home Assistant-native architecture:

- A UI config flow for selecting ESPHome/ATM90E32 sensor entities, confirming channel mappings, setting circuit mode, and assigning appliance profiles.
- An analyzer engine that validates incoming sensor data, detects events, learns circuit baselines, and scores deviations.
- A compact integration-owned event and feature store for learned behavior and alert evidence.
- Home Assistant output entities for continuous diagnostic state, persistent notifications for important feed or appliance-behavior events, and Repairs/issues only for integration or source-data problems.

HACS is the distribution and update mechanism, not a separate runtime architecture. The repository should satisfy HACS integration layout requirements from the beginning: one integration under `custom_components/`, valid `manifest.json`, `hacs.json`, README, release metadata, and issue links.

## Circuit Model

Each configured circuit has a mode:

- Single-phase appliance: one CT/channel mapped to one primary appliance profile, such as a refrigerator, freezer, sump pump, or small motor load.
- Dual-phase appliance: two CT/channels treated as one appliance, such as HVAC, water heater, pool pump, oven, dryer, or large pump. Combined power behavior is analyzed while each leg is still checked for imbalance and data quality.
- Mixed or unprofiled circuit: lights, plugs, or general branch circuits where appliance-health analysis is skipped. These circuits can still receive feed-quality, availability, and large-change diagnostics.

The setup flow should auto-suggest dual-phase channel pairings, then require user confirmation. Suggestions may use entity/device names, available phase metadata, correlated load changes, similar voltage behavior, and sensor availability. The user must also be able to manually set or override all channel mappings.

## Data Flow

The integration should subscribe to selected sensor state changes where possible, using event-driven updates instead of fixed polling for high-frequency HA state changes. Incoming values are normalized into a timestamped circuit sample with:

- Voltage
- Current
- Real power in watts
- Reactive power in VAR
- Apparent power in VA
- Power factor
- Frequency, if available
- Source entity availability and freshness

For each configured circuit, the analyzer should:

- Validate units, numeric state, freshness, sign, sensor availability, and expected channel pairing.
- Smooth readings lightly enough to reduce noise without erasing appliance events.
- Detect transitions such as off-to-on, on-to-off, startup spike, steady operation, idle draw, voltage sag, voltage swell, and sustained leg imbalance.
- Store derived events and feature summaries instead of retaining endless raw samples.
- Learn baselines per circuit, appliance profile, circuit mode, and operating state.
- Score deviations against robust baseline distributions.
- Require enough learning data and repeated evidence before appliance-health alerts.

Dual-phase circuits should calculate combined W, VAR, VA, and current while preserving leg-level measurements for:

- Leg-to-leg power imbalance
- Voltage difference
- One-leg-only behavior on loads expected to use both legs
- Suspected bad pairing
- Suspected CT inversion or voltage/current phase mismatch

## Appliance Profiles

Profiles define which features are learned, which changes can alert, and which changes remain informational.

### Refrigerator And Freezer

Learn compressor cycle duration, off interval, duty cycle, steady W/VAR/PF, startup spike, idle draw, and defrost-like longer resistive events where visible.

Potential alerts:

- Repeated short cycling
- Repeated unusually long compressor runs
- Duty cycle drift
- Steady-state real power drift
- Reactive power or power-factor drift across repeated cycles
- Startup behavior that changes materially from baseline

### HVAC, Heat Pump, And AC Compressor

Support single-phase or dual-phase setups. Learn compressor and fan stages where visible, start events, run duration, steady W/VAR/PF, voltage sag during start, and behavior relative to optional indoor/outdoor temperature entities.

Potential alerts:

- Repeated short cycling
- Repeated unusually long runs after accounting for optional temperature context
- Reactive power or power-factor drift
- Voltage sag during start
- Leg imbalance on dual-phase loads
- One-leg-only operation when both legs are expected

### Water Heater, Oven, Dryer, And Resistive Appliances

Focus on real-power behavior and high-power-factor expectations. Learn element duty patterns, combined dual-phase power, leg behavior, and unexpectedly reactive behavior.

Potential alerts:

- Unexpected one-leg imbalance
- Repeated stuck-on or stuck-off style behavior
- Significant change in expected real-power draw
- Meaningful reactive power where the profile expects mostly resistive behavior

### Pool Pump, Well Pump, Sump Pump, And Motor Loads

Learn motor start behavior, steady W/VAR/PF, run duration, run frequency, and voltage sag at start.

Potential alerts:

- Runtime or frequency changes
- Reactive power drift
- Power-factor drift
- Startup current/power change
- Voltage sag at start
- Evidence of changed motor load behavior, phrased conservatively

### EV Charger And Power Electronics Loads

Learn long high-load sessions, ramp behavior, voltage stability, current stability, real-power consistency, and PF/reactive behavior where available.

Potential alerts:

- Sustained voltage sag under load
- Unexpected power ramp or derating pattern
- Significant PF/reactive behavior change
- Session behavior that changes materially from baseline

### Mixed Or Unprofiled Circuits

Do not attempt appliance-health analysis. Provide data-quality, feed-quality, availability, and large persistent change diagnostics only.

## Baseline And Alert Policy

The integration should be conservative by default.

Appliance-health alerts require:

- At least 7 days of learning data or a profile-specific minimum cycle count.
- Enough valid samples from required sensors.
- Repeated anomaly evidence, not a single unusual cycle.
- Baseline confidence above a configured minimum.
- Evidence-first wording that explains what changed.

Feed-quality and setup/data-quality alerts may trigger sooner because they are not learned appliance-health claims.

Alert wording should avoid definitive diagnosis. For example, it should prefer "compressor run time is 38% longer than its learned baseline across 5 recent cycles" over "compressor is failing."

Users should be able to tune sensitivity, pause alerts, relearn a baseline, acknowledge an alert, and export diagnostics.

## Storage And Retention

Home Assistant recorder/statistics should be used where they are useful, but the integration should not rely on default HA history for appliance diagnostics. Home Assistant may purge raw state history and short-term statistics after the configured retention period, while long-term statistics are hourly summaries. Hourly summaries are useful for slow trends but too coarse for cycle and startup diagnostics.

The integration-owned store should keep compact derived records:

- Short rolling sample buffer for event detection
- Starts, stops, steady-state windows, voltage sags/swells, and leg imbalance events
- Learned baseline summaries: median, robust spread, percentiles, cycle counts, and confidence score
- Alert evidence: changed features, magnitude, affected cycles, and timestamps

Retention modes:

- Lightweight: shortest event history and minimal trend context.
- Standard default: enough event history for stable appliance baselines.
- Diagnostic: longer event and feature retention for troubleshooting and export.

The storage design should allow future export to InfluxDB, Prometheus, CSV, or a separate add-on, but v1 should not require external storage.

## Home Assistant UX

The integration is configured through the Home Assistant UI.

Setup flow:

1. Select or auto-detect CircuitSetup/ESPHome meter entities.
2. Review suggested channel groups.
3. Choose circuit mode: single-phase appliance, dual-phase appliance, or mixed/unprofiled.
4. Assign appliance profile.
5. Confirm required and optional sensors.
6. Choose sensitivity and retention mode.
7. Start in learning mode.

Outputs:

- Diagnostic sensor entities for each configured circuit.
- Binary sensors for alert, learning, and data-quality states.
- Persistent notifications for important feed or appliance-behavior changes.
- Repairs/issues only for integration and data-quality problems.
- Services/actions for relearn baseline, pause alerts, acknowledge alert, export diagnostics, and run mapping checks.
- Documentation with example dashboard YAML/cards, but no custom Lovelace card in v1.

Example entities:

- `sensor.fridge_energy_analyzer_anomaly_score`
- `sensor.fridge_energy_analyzer_cycle_health`
- `sensor.fridge_energy_analyzer_reactive_power_drift`
- `binary_sensor.fridge_energy_analyzer_learning`
- `binary_sensor.hvac_energy_analyzer_voltage_sag`
- `sensor.hvac_energy_analyzer_leg_imbalance`

## Repairs, Notifications, And Entities

Diagnostic entities should always be available when a circuit is configured and has enough source data.

Persistent notifications should be used for important appliance or feed-quality events, such as repeated cycle drift, voltage sag under load, or repeated reactive power drift.

Repairs/issues should be limited to integration problems:

- Missing required sensors
- Unavailable or stale entities
- Likely CT inversion
- Likely phase mismatch
- Suspicious dual-phase pairing
- Not enough valid data to learn after a reasonable period
- Integration store or migration problems

## Error Handling

The integration should fail softly and transparently:

- If required sensors are missing, create a Repair and mark the circuit data-quality status as bad.
- If optional sensors are missing, degrade analysis and explain which features are unavailable.
- If source values become unavailable or stale, pause appliance-health scoring for the affected circuit.
- If a baseline is not confident, stay in learning mode and expose why.
- If storage migration fails, preserve existing data where possible and surface a Repair.

## Testing Strategy

Use test-driven development around focused units:

- Config flow validation and manual/auto channel mapping.
- Entity discovery from ESPHome-style sensor names and device metadata.
- Sample normalization, unit handling, stale-data detection, and sign validation.
- Dual-phase aggregation and leg imbalance checks.
- Event detection for compressor-like cycles, resistive loads, motor starts, voltage sag, and mixed circuits.
- Baseline learning and confidence thresholds.
- Conservative alert gating and repeated-evidence requirements.
- HA entity state output, persistent notification creation, and Repair creation.
- Store retention and migration behavior.

Synthetic fixtures should model common household loads and data-quality failures so the analyzer can be tested without real hardware.

## Non-Goals For V1

- Full NILM disaggregation on mixed circuits.
- Definitive appliance failure diagnosis.
- High-frequency waveform or harmonic analysis beyond the values exposed as HA entities.
- A custom Lovelace card.
- Required external databases.
- Required cloud services.
- Direct ESPHome firmware changes.

## References

- ESPHome ATM90E32 documentation: `https://esphome.io/components/sensor/atm90e32/`
- Home Assistant statistics documentation: `https://data.home-assistant.io/docs/statistics/`
- Home Assistant integration file structure: `https://developers.home-assistant.io/docs/creating_integration_file_structure/`
- Home Assistant DataUpdateCoordinator/fetching-data documentation: `https://developers.home-assistant.io/docs/integration_fetching_data/`
- Home Assistant integration manifest documentation: `https://developers.home-assistant.io/docs/creating_integration_manifest/`
- HACS overview: `https://www.hacs.dev/`
- HACS integration publishing requirements: `https://hacs.xyz/docs/publish/integration/`
- IEEE 1459-2025 standard overview: `https://standards.ieee.org/ieee/1459/7578/`
- Rashid et al., appliance anomaly detection using AC and refrigerator power traces: `https://loneharoon.github.io/files/papers/appliedEnergy19.pdf`
- Shaw, Norford, Leeb, and Luo, HVAC fault detection via electrical load monitoring: `https://emsg.mit.edu/wp-content/uploads/2016/07/21_Detection-and-Diagnosis-of-HVAC-Faults-via-Electrical-Load-Monitoring.pdf`
- Khodapanah, Zobaa, and Abbod, induction motor power factor estimation: `https://link.springer.com/article/10.1007/s00202-018-0723-7`
- ORNL water heater anomaly detection publication: `https://www.ornl.gov/publication/anomaly-detection-mpc-forecast-fleet-water-heaters`
