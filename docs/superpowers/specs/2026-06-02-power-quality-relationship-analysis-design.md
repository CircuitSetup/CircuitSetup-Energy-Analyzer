# Power Quality Relationship Analysis Design

## Goal

Extend CircuitSetup Energy Analyzer so each configured circuit learns and scores
reactive power, apparent power, power factor, and the relationships among real
power, reactive power, apparent power, and power factor.

The feature should be advanced internally but conservative externally. It should
produce evidence that a circuit's electrical relationship changed, not diagnose
an appliance failure.

## Context

The current analyzer already normalizes real power, reactive power, apparent
power, and power factor. Dual-phase aggregation and experimental NILM also use
these values. The missing behavior is per-circuit learned baseline analysis for
non-real-power metrics and relationship-aware evidence.

The existing alert path is centered on `real_power`. This feature replaces that
single-feature observation with a feature set that can learn and score:

- Real power in watts
- Reactive power in VAR
- Apparent power in VA
- Power factor
- Reactive-to-real ratio
- Apparent-to-real ratio
- Power factor under comparable load
- Relationship drift, such as reactive power changing while real power remains
  near baseline

## Evidence Basis

The analyzer should align its terminology and derived features with established
power-quality concepts:

- IEEE 1459-2025 defines measurement terminology for active, reactive,
  apparent power, and power factor under sinusoidal, nonsinusoidal, balanced,
  and unbalanced conditions.
- NIST TN 2249 models heat-pump real and reactive power by stage and phase. It
  shows that reactive power can exhibit nonlinear transient behavior, that
  split-phase legs can have different reactive behavior, and that total
  split-phase behavior must be interpreted as the sum of both legs.
- Shaw, Norford, Luo, and Leeb show that electrical load monitoring can detect
  HVAC faults through power correlations and motor startup behavior.
- Khodapanah, Zobaa, and Abbod show that induction-motor power factor changes
  with loading and that active/reactive power relationships matter for motor
  monitoring.
- NILM and load-identification literature commonly treats active power,
  reactive power, apparent power, and power factor as multivariate appliance
  signature features.

The integration should use these references to shape evidence labels, not to
make medical-style or technician-style diagnoses. A refrigerator alert can say
"reactive power increased under similar real-power load"; it should not say
"compressor motor is failing."

## Architecture

Add a pure-Python `power_quality.py` module with no Home Assistant dependency.
It owns feature extraction, relationship scoring, and evidence selection.

The coordinator will replace `_observe_real_power` with a more general
power-quality observation step. This step will:

1. Extract all available power-quality features from a normalized circuit
   sample.
2. Learn robust baselines for each feature.
3. Learn relationship baselines for derived ratios.
4. Wait for existing maturity requirements: at least seven days or the
   profile-specific cycle count.
5. Score individual feature deviations and combined vector deviation.
6. Build concise evidence for the strongest changed relationships.
7. Send the evidence through the existing conservative repeated-observation
   alert policy.

Existing storage can continue using `BaselineStats` keyed by
`circuit_id:feature`. No raw high-frequency sample retention is required for
this feature.

## Feature Extraction

For each sample, extract directly measured values when present:

- `real_power`
- `reactive_power`
- `apparent_power`
- `power_factor`

Extract derived features only when their inputs are valid:

- `reactive_to_real_ratio = reactive_power / abs(real_power)` when real power
  is above a minimum load floor.
- `apparent_to_real_ratio = apparent_power / abs(real_power)` when real power
  is above a minimum load floor.
- `power_factor_deficit = 1 - abs(power_factor)` when power factor is known.
- `apparent_power_residual = apparent_power - sqrt(real_power^2 +
  reactive_power^2)` when W, VAR, and VA are available. This should be
  diagnostic evidence of meter/definition/measurement mismatch rather than an
  appliance-health alert, because apparent power definitions and harmonic
  effects can vary.

Use a load floor so idle noise does not create misleading ratios. The default
floor should be 80 W, matching the existing run/start threshold, with profile
specific overrides allowed later.

## Relationship Scoring

Each extracted feature gets a robust deviation score using the existing median
and MAD baseline approach.

Add a multivariate relationship score:

- Collect the available scored features for the sample.
- Use only features with confident baselines.
- Compute a robust RMS score across the feature vector.
- Require at least two non-real-power relationship features before calling the
  alert a relationship anomaly.
- Preserve individual scores so evidence can say which relationship changed.

This keeps the analysis advanced enough to detect combined behavior changes
without hiding the reason from the user.

## Evidence Selection

Evidence should be generated from relationship patterns:

- `reactive_shift_under_stable_real_power`: reactive power or
  reactive-to-real ratio changes while real power remains near baseline.
- `power_factor_shift_under_load`: power factor drops or rises materially while
  real power is in the learned operating range.
- `apparent_power_shift`: apparent power increases while real power changes
  little, suggesting more current or non-real-power burden for the same useful
  power.
- `resistive_load_became_reactive`: a resistive profile such as water heater,
  oven, dryer element, or resistive load shows repeated unexpected VAR/PF
  behavior.
- `motor_relationship_changed`: a motor profile such as refrigerator, HVAC,
  pool pump, well pump, sump pump, or generic motor load shows repeated
  VAR/PF/reactive-ratio drift under comparable real-power load.
- `split_phase_relationship_changed`: a dual-phase circuit shows changed
  combined W/VAR/VA/PF relationship, with leg-level evidence when available.

Alert messages should prefer concrete evidence:

- "Possible issue: reactive power increased 38% while real power stayed within
  5% of its learned baseline across 4 recent observations."
- "Possible issue: power factor changed from 0.94 to 0.78 under a similar
  920 W load across 3 recent observations."
- "Possible issue: apparent power increased while real power stayed near
  baseline, suggesting the circuit is drawing more non-real-power burden for
  similar useful power."

## Appliance Profiles

Motor-like profiles should prioritize W/VAR/PF relationship drift:

- Refrigerator and freezer
- HVAC and heat pump
- Pool pump
- Well pump
- Sump pump
- Generic motor load

Resistive profiles should prioritize unexpected reactive behavior:

- Water heater
- Oven
- Dryer element behavior
- Generic resistive load

Mixed circuits should expose diagnostic relationship scores but avoid
appliance-health notifications unless the user has assigned a specific profile
or confirmed a NILM signature label.

Mains NILM signatures should include W/VAR/VA/PF deltas and relationship hints,
but v1 experimental NILM should continue to avoid firm appliance labels.

## Data Quality And Guardrails

The analysis must not alert when required source data is stale, unavailable, or
non-numeric.

Do not create relationship alerts when only one metric is available. A circuit
with only real power should keep existing real-power baseline behavior.

Do not treat apparent power residuals as appliance-health evidence by default.
They can indicate a measurement-definition issue, harmonic effects, or meter
configuration issue.

Do not compare power factor at idle against loaded operation. PF and ratios
should be scored only when the load is above the configured floor and near a
learned operating state.

Dual-phase loads must be scored from the aggregated sample while keeping
leg-level quality evidence. A single leg with surprising reactive sign should
not be treated as a circuit-level issue if the combined split-phase behavior is
normal.

## Home Assistant Output

Keep standard entities first.

Existing anomaly score entities should reflect the strongest active alert score.
Add diagnostic sensors for the strongest current power-quality evidence when
the entity model supports it:

- Power Quality Score
- Reactive Power Drift
- Apparent Power Drift
- Power Factor Drift
- Power Quality Evidence

These entities should be diagnostic by default. Persistent notifications should
only be created for mature, repeated evidence after the conservative alert
policy fires. Repairs remain limited to setup, configuration, and data-quality
issues.

## Testing Strategy

Use test-driven development.

Add unit tests for:

- Feature extraction with full W/VAR/VA/PF data.
- Derived ratio suppression below the load floor.
- Reactive-power drift under stable real power.
- Power-factor drift under similar load.
- Resistive profile unexpected VAR/PF evidence.
- Motor profile relationship drift evidence.
- Multivariate scoring with missing optional metrics.
- Coordinator persistence of multiple baselines per circuit.
- Coordinator alert maturity and repeated-evidence gates for relationship
  alerts.
- Dual-phase aggregation feeding relationship scoring.
- Mixed circuits exposing diagnostics without appliance-health notifications.

Run the full test suite and ruff after implementation.

## References

- IEEE 1459-2025, Standard Definitions for the Measurement of Electric Power
  Quantities Under Sinusoidal, Nonsinusoidal, Balanced, or Unbalanced
  Conditions: `https://standards.ieee.org/ieee/1459/7578/`
- NIST TN 2249, A Gray-Box Model of a Two-Stage Heat Pump for Electrical Load
  Forecasting in a Single-Family Residence:
  `https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2249.pdf`
- Shaw, Norford, Luo, and Leeb, Detection and Diagnosis of HVAC Faults via
  Electrical Load Monitoring:
  `https://emsg.mit.edu/wp-content/uploads/2024/05/21_Detection-and-Diagnosis-of-HVAC-Faults-via-Electrical-Load-Monitoring.pdf`
- Khodapanah, Zobaa, and Abbod, Estimating power factor of induction motors at
  any loading conditions using support vector regression:
  `https://bura.brunel.ac.uk/handle/2438/16671`
- Non-Intrusive Load Identification Based on Multivariate Features and
  Information Entropy-Weighted Ensemble:
  `https://www.mdpi.com/1996-1073/18/9/2369`
