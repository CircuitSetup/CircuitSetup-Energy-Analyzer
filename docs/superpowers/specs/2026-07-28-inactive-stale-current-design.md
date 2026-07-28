# Inactive Stale Current Suppression Design

**Date:** 2026-07-28
**Status:** Approved

## Summary

Do not report a stale-source problem when the only stale metric is optional
current and a fresh real-power reading shows that the circuit is off. Continue
to discard the stale current value from analysis.

## Problem

Some ESPHome energy meters publish real power every five seconds but do not
republish an unchanged near-zero current value. The analyzer currently treats
every configured metric older than ten minutes as actionable, so an inactive
circuit can show `Needs data` and create a stale-source repair even though its
fresh real-power source confirms that the load is off.

Using ESPHome `force_update` would create unnecessary Home Assistant state and
recorder traffic for every unchanged reading.

## Behavior

Suppress a stale issue only when all of these conditions are true:

- The stale source has the optional `current` role.
- The circuit has a fresh, finite real-power value.
- The absolute real power is at or below the circuit's resolved operating
  turn-off threshold.

The stale current value remains `None` in the normalized sample and is not used
by processors, metrics, or learning.

The stale issue becomes actionable immediately when fresh real power rises above
the turn-off threshold. Stale required real power, stale non-current metrics,
missing states, unavailable states, invalid values, and timestamp errors keep
their existing behavior.

## Threshold

Reuse the existing resolved operating-detection turn-off threshold, including a
saved user override when present. Do not add a new stale-data threshold or
configuration control.

## Implementation

Apply the suppression while building the normalized sample so repairs, Setup
Health, data-quality sensors, and other consumers see one consistent result.
Pass the resolved turn-off threshold from the coordinator's existing settings
state into source-sample normalization.

For dual-phase circuits, evaluate each leg against the same circuit threshold
before aggregating quality issues. For parallel mains inputs, preserve existing
behavior because current is not needed for NILM source quality.

## Verification

Add focused regression coverage proving:

- inactive fresh power suppresses only stale optional current;
- stale current remains excluded from the sample;
- active fresh power reports stale current;
- stale real power and other stale optional roles still report problems;
- a saved operating turn-off override controls the boundary.

Run the normal PR verification and the Home Assistant contract verification
because the user-visible Setup Health and repair lifecycle change.

## Non-Goals

- Enabling ESPHome `force_update`.
- Treating an unchanged value as a fresh reading.
- Suppressing stale required sensors.
- Adding a general-purpose stale policy or new UI setting.
