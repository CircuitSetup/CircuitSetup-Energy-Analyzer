# Environmental Correlation Design

## Scope

Keep the existing sensor-to-appliance associations unchanged:

- Outdoor temperature: HVAC, HVAC compressor, HVAC blower, and electric heat.
- Rainfall: sump pump, water pump, and well pump.
- Water flow: water pump, well pump, water heater, and washer.

No new configuration fields, profiles, background polling, or history schema are added.

## Corrections

### Water flow

Flow correlation will use each sensor's active state correctly for binary and numeric sources. A positive numeric flow rate is active.

The correlation will use current or recently completed run-cycle evidence instead of total runtime for the current day. When a flow source is shared, any compatible appliance that is configured to use that same source counts as a matching load before "possible flow without load" evidence is raised. Explicit linked sensors remain scoped to their existing circuit definitions.

An appliance without an available configured flow source remains unconfigured; it does not produce a flow-sensor fault alert.

### Rainfall

The configured rain response window will retain rain context after a sensor reports dry. The correlation records when active rain was last observed and expires that context after the configured window. It continues to report the raw rain-sensor state separately from the effective response-window context.

### Weather

Weather context remains limited to the existing HVAC profiles. No new weather-to-appliance associations are inferred.

## Data Flow And Failure Handling

The environmental context manager remains the sole owner of evidence. It reads configured sources through the existing context builder, retains only a small response-window timestamp in existing evidence, and feeds the existing correlation evaluators and alert processor.

Unavailable, zero, or unmapped flow sources produce unconfigured evidence rather than mismatch alerts. Invalid or unavailable rain readings do not extend the response window.

## Tests

Add focused regression tests for positive numeric flow, shared-flow appliance activity, absent flow sources, current-cycle rather than daily runtime, and rain response-window expiry. Preserve existing weather-profile coverage.
