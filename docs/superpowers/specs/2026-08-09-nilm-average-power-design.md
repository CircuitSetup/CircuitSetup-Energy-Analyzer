# NILM average-power display design

## Problem

Published NILM assignments can display `Unknown W` even when their assigned
recorded label intervals contain valid `median_power_w` readings. The existing
workspace payload derives `typical_power_w` only from an interval's
`observed_transition_w`. Label intervals recorded on different boundaries can
therefore be useful evidence without supplying a display value.

## Decision

The NILM workspace payload will preserve an existing valid
`typical_power_w`. If it has no such value, it will retain the current
transition-watt fallback. If neither is available, it will calculate the
arithmetic mean of the valid `median_power_w` readings from intervals assigned
to that appliance.

The derived field is response-only: it is not written back to the stored
assignment and does not affect publication eligibility, model training,
confidence, or validation error metrics. This keeps recorded evidence and
runtime lifecycle state unchanged.

When the arithmetic-mean fallback is used, the payload will mark the value as
an average. The NILM workspace card will render it as `Average power: <value>
W`, rather than presenting it as a single measured or modeled wattage. Existing
typical-power displays keep their current wording.

## Scope and data flow

1. `panel_nilm._nilm_assignment_payload` gathers only intervals that are
   explicitly assigned to the appliance or listed in its `label_interval_ids`.
2. It ignores missing, non-numeric, non-finite, and negative readings.
3. It computes an arithmetic mean only after the existing `typical_power_w`
   and `observed_transition_w` sources have both failed.
4. It returns the calculated wattage plus an explicit display-source flag.
5. `energy-analyzer-nilm-workspace.js` uses that flag to label the card
   `Average power`; the panel module version is bumped for the shipped
   JavaScript.

## Testing

- Add a panel-payload regression test using differently sized recorded label
  intervals with valid `median_power_w` and no transition wattage; assert the
  arithmetic mean and average-source flag.
- Assert existing valid typical power and transition-watt fallback retain their
  current precedence.
- Add a frontend rendering test that asserts the average label is visible and
  is not used for a normal typical-power value.
- Run focused panel tests, the normal lint/test suite, and the Home Assistant
  contract verification required for panel behavior.
