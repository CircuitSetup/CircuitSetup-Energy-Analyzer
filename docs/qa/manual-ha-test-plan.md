# Manual Home Assistant QA Test Plan

Date: 2026-06-12
Integration: `circuitsetup_energy_analyzer`
Version under test: 0.7.5
Python target: >=3.12
Home Assistant target: >=2025.1.0

## Scope

This plan covers the user-visible and runtime surfaces of the CircuitSetup Energy Analyzer custom integration:

- Installation by placing `custom_components/circuitsetup_energy_analyzer` in a Home Assistant config directory.
- Config flow, options flow, advanced settings, entity detail level, suggested settings, dashboard/evidence panel, and repairs paths.
- Platforms: `sensor`, `binary_sensor`, `button`, `select`, and `number`.
- Services in `services.yaml`, including valid calls, missing data, invalid IDs, and backward-compatible actions.
- Processor/runtime features: activity alerts, billing, capacity, cost, cycles, demand, energy goals, energy usage, events, leg imbalance, mains balance, metric consistency, NILM, power quality, solar flow, standby, utility comparison, water context, and weather context.
- Reload, restart, unload, removal, persistence, and log hygiene.

HACS is not required for this plan. HACS validates distribution and update installation. Runtime QA should use a copied or symlinked custom component in a disposable Home Assistant Core config directory.

## Test Environment

Preferred:

- Linux, macOS, WSL, or containerized Home Assistant Core.
- Python 3.12 or 3.13 compatible with the selected Home Assistant version.
- Home Assistant Core 2025.1.x or newer.
- Disposable config directory, not the user's production Home Assistant config.

Local native Windows can be used only for partial validation. Native Windows Home Assistant Core is not supported by Home Assistant and may require process-local shims for `os.fchmod`, event-loop policy, signal handling, and aiohttp DNS resolver behavior.

## Setup

1. Create a clean Python virtual environment.
2. Install the project and tests:

   ```powershell
   python -m pip install -e ".[test]"
   ```

3. Create a disposable Home Assistant config directory.
4. Copy or symlink `custom_components/circuitsetup_energy_analyzer` into `CONFIG/custom_components/circuitsetup_energy_analyzer`.
5. Add a minimal `configuration.yaml` with `homeassistant`, `http`, `api`, `frontend`, `config`, `logger`, and template fake source entities.
6. Start Home Assistant with the disposable config directory.
7. Tail `home-assistant.log` for the whole test.

## Fake Source Entities

Create template or helper entities for:

- Single-phase appliance: power W, energy kWh, current A, voltage V, power factor, apparent power VA, reactive power VAR.
- Dual-phase appliance: L1/L2 power, current, voltage, and energy.
- Mains: L1 power, L2 power, total/net power, total energy.
- Solar: generation power, generation energy, and signed mains/net power.
- Weather/rain/water: outdoor temperature, rain binary sensor, rain intensity sensor, water-flow binary sensor, and water-flow numeric sensor.

## Workflows

### A. Fresh Install And Setup

1. Start Home Assistant with the custom component present.
2. Confirm no import-time errors, manifest errors, or platform discovery errors.
3. Start the integration config flow.
4. Select fake source devices/entities or use the demo path if present.
5. Review circuit assignments and save.
6. Confirm setup-health/global summary entities exist.
7. Confirm default entity detail level is Simple.
8. Confirm diagnostic/expert entities are disabled by default unless Expert is selected.
9. Review logs for tracebacks, setup errors, duplicate unique IDs, duplicate services, and blocking warnings.

### B. Single-Phase Appliance

1. Configure a refrigerator-like circuit with power and energy sensors.
2. Verify Health Summary, Activity Summary, Electrical Health, Energy Summary, Daily Energy Usage, and Running binary sensor.
3. Simulate power below and above running threshold.
4. Simulate energy increasing.
5. Verify state changes and no log errors.

### C. Dual-Phase Appliance

1. Configure an HVAC/EV-style dual-phase circuit with L1 and L2 power.
2. Simulate balanced load.
3. Simulate imbalanced load.
4. Remove or make one leg unavailable.
5. Verify leg imbalance/electrical health behavior and setup-health or repair messaging.

### D. Mixed Circuit

1. Configure a mixed circuit with multiple source entities.
2. Verify appliance-specific claims are conservative.
3. Confirm no inappropriate Running binary sensor is created.
4. Confirm summaries remain useful and logs are clean.

### E. Mains And NILM

1. Configure mains source entities.
2. Enable experimental NILM if available.
3. Simulate known and unknown loads.
4. Verify NILM entities, panel data, and API paths do not crash.
5. Confirm normal UI paths do not require users to type `signature_id`.

### F. Solar Flow

1. Configure solar/generation source.
2. Simulate import, export, and inconsistent export.
3. Verify solar status, Electrical Health, and Energy Summary behavior.
4. Confirm sign/mapping scenarios do not crash.

### G. Weather, Rain, And Water Context

1. Configure outdoor temperature for HVAC-like circuits.
2. Simulate hot and mild conditions.
3. Configure rain sensor, rain intensity, and water-flow sensors.
4. Simulate pump/flow mismatch and expected flow.
5. Verify summaries and context entities behave without errors.

### H. Advanced Circuit Settings

For each applicable section, open the form, verify defaults, try invalid values, save valid values, reload, and restart:

- Energy usage
- Daily goals
- Billing cycle
- Cost / TOU
- Demand
- Capacity
- Leg imbalance
- Metric consistency
- Mains balance
- Solar flow
- Standby / Always On
- Activity sensitivity
- Rain/pump context
- Water-flow context
- Utility comparison
- NILM settings

### I. Entity Detail Level

1. Set Simple and verify only summary/default entities are enabled.
2. Set Standard and verify feature-status entities.
3. Set Expert and verify diagnostic entities are available as designed.
4. Apply profile to existing entities.
5. Confirm manually disabled entities are not unexpectedly re-enabled unless explicitly requested.

### J. Control Entities

Test all button/select/number entities:

- Relearn Baseline
- Start Maintenance
- End Maintenance
- Pause Alerts
- Recalculate Suggestions
- Run Mapping Checks
- Alert Sensitivity select
- Daily Energy Goal number

Verify valid actions work, invalid state is handled, and persistence matches the entity purpose.

### K. Services

Call every service in `services.yaml` with valid data, missing data, wrong types, invalid `circuit_id`, invalid `alert_id`, invalid `signature_id`, invalid `recommendation_id`, and boundary values.

Expected result:

- Valid calls work.
- Invalid calls raise validation errors or clear `HomeAssistantError`.
- No silent broad targeting.
- Backward-compatible service names remain registered.

### L. Evidence Panel And HTTP API

1. Open the evidence panel or call authenticated endpoints directly.
2. Confirm authentication is required.
3. Confirm valid IDs return data.
4. Confirm invalid IDs return safe errors.
5. Test acknowledge, mark expected, mark unhelpful, pause alerts, maintenance, relearn baseline, suggestion apply/dismiss, and NILM actions where present.
6. Confirm normal user flows avoid typed IDs.

### M. Persistence, Reload, Restart, And Unload

1. Configure several circuits.
2. Generate events, baselines, alerts, maintenance state, settings, and suggestions.
3. Reload the config entry.
4. Restart Home Assistant.
5. Unload and remove the config entry.
6. Confirm no duplicate listeners/entities/services/panels and no orphaned storage behavior.

### N. Performance Smoke

Simulate 6, 12, and 24 circuits where feasible. Track update duration, warnings, event-loop blocking, memory/storage growth, and recorder/entity churn.

## Log Failure Standard

Fail a workflow if logs contain an unhandled exception, traceback, import error, platform setup error, service registration error, entity duplicate error, or async blocking warning. Warnings are acceptable only when documented and justified.

