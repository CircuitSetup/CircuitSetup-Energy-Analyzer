# Contextual Baselines Review

## Current Baseline Behavior

- `baseline.py` builds deterministic robust baseline stats from retained values with median, MAD, p10, p90, sample count, and confidence.
- Existing processors store ordinary feature baselines in `FeatureStoreData.baselines` under compact circuit/feature keys.
- `score_deviation()` uses the robust baseline spread rather than a simple average, which should remain the default scoring primitive for contextual stats.

## Current Weather Context Behavior

- `weather_context.py` evaluates HVAC runtime and duty cycle against history with outdoor temperatures within 3 degrees of the current temperature.
- If fewer than three comparable samples exist, it returns a learning status.
- Existing output includes status, current temperature, temperature bin, mode, expected ranges, observed runtime/duty cycle, and a human explanation.
- The current implementation is temperature-aware but not season-, time-, or fallback-chain-aware.

## Current Water And Rain Context Behavior

- `water_correlations.py` evaluates rain-adjusted pump runtime and water-flow/load mismatches.
- Rain/pump evidence uses dry baseline minutes, comparable window count, rain activity, optional rain intensity, and HVAC compressor context.
- Water-flow evidence compares flow-active minutes with mapped appliance runtime and recent related runtime.
- `WaterContextAlertProcessor` converts actionable rain/water statuses into repeated-evidence alert observations.

## Current History Storage

- `FeatureStoreData` persists compact histories for weather and water context:
  - `weather_context_history_by_circuit`
  - `water_context_history_by_circuit`
- It also stores current weather, rain-pump, and water-flow context evidence dictionaries.
- Daily energy history is stored per circuit in `energy_usage_by_circuit`, with cumulative kWh tracking and retained daily usage rows.
- Store loading already tolerates missing fields by defaulting to empty dictionaries.

## Context-Aware Evidence Today

- `EnergyUsageProcessor` emits daily usage evidence through `energy_usage_evidence_by_circuit`, but it compares against a rolling window only.
- `weather_context.py` emits temperature-adjusted HVAC evidence, but only through similar-temperature sample filtering.
- `evaluate_rain_pump_correlation()` and `evaluate_flow_correlation()` emit context-aware water evidence.
- `SolarFlowProcessor` emits instantaneous solar/import/export evidence that can feed future solar context buckets.

## Current Alert Policy Behavior

- Processors submit `Observation` objects to alert policies rather than creating alerts directly.
- Alert messages use conservative "Possible issue" language.
- Daily energy alerts use rolling-window score, baseline confidence based on learned day count, and repeated-evidence policy.
- Water-context alerts also pass through repeated-evidence policy.

## Gaps This Work Fills

- Add reusable context keys, stable fingerprints, bucket helpers, contextual robust stats, and fallback selection.
- Store contextual samples/stats in bounded, backward-compatible fields.
- Build context keys from existing circuit profile, topology, time, weather, rain/water, and solar state.
- Attach contextual comparison metadata to existing evidence surfaces rather than adding noisy default entities.
- Preserve existing weather, water, and rolling baseline behavior as fallback paths.
