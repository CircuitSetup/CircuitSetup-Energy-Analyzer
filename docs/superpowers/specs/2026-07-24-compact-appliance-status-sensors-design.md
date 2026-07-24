# Compact Appliance Status Sensors

## Goal

Reduce redundant per-appliance entities while preserving the existing
`Activity Summary` and `Health Summary` entity identities.

## Entity Contract

### Activity Summary

Keep `sensor.<circuit>_activity_summary` as the single activity entity.

- Preserve its current state values: `Running`, `Idle`, `Standby`, `On`, `Off`,
  `No Activity`, and `Unavailable`.
- Preserve the current run-cycle and standby attributes.
- Add an `is_running` boolean attribute using the same operating-state logic as
  the removed Running binary sensor.
- Stop creating `binary_sensor.<circuit>_running`.
- Stop creating `sensor.<circuit>_standby_status`.

Automations that used the removed binary sensor must use the Activity Summary
state or its `is_running` attribute.

### Health Summary

Keep `sensor.<circuit>_health_summary` as the single health entity.

- Preserve its current overall readiness and attention state.
- Add the complete Electrical Health detail as attributes, including the
  electrical summary, metric-consistency state and score, leg-imbalance state
  and percentage, power-quality score and evidence, explanations, confirmation
  flags, and first-check guidance.
- Stop creating `sensor.<circuit>_electrical_health`.

Automations that used Electrical Health must use the corresponding Health
Summary attributes.

### Leg Imbalance

Keep `sensor.<circuit>_leg_imbalance` as a numeric feature entity because its
recorded percentage remains useful for history and automations.

- Create and enable it for applicable dual-phase circuits at Standard and
  Expert detail levels.
- Do not create it at Simple detail.
- Remove stale integration-disabled registry rows when the active detail level
  does not create the entity.
- Preserve user-disabled rows when the entity is otherwise applicable.

## Pause Alerts Icon

Keep the existing `mdi:bell-pause-outline` icon on the Pause Alerts switch and
show the same icon on the evidence-panel Pause Alerts action. Other action
buttons are unchanged.

## Registry And Consumers

Remove the retired keys from entity descriptions and the compact entity
catalog. Existing registry pruning removes their stale rows without a separate
migration layer. Dashboard generation, examples, notification-blueprint tests,
and documentation must reference the surviving summary entities and their
attributes.

## Appliance Detail

Apply the same consolidation to every direct and NILM appliance detail page.

- Show one Activity metric sourced from Activity Summary rather than separate
  Running or Standby metrics or sections.
- Show one Health metric sourced from Health Summary rather than separate
  Health and Electrical metrics or sections.
- Remove the duplicate `electrical_state` appliance-detail payload field.
- Keep electrical detail available through Health Summary attributes and the
  existing evidence, expectation, and first-check content rather than repeating
  it as another top-level status.
- Keep distinct numeric measurements, history graphs, timelines, energy/cost
  data, and evidence sections when they add information beyond the two summary
  states.

The panel JavaScript cache version must be bumped because the rendered action
markup changes.

## Verification

Use focused regression tests first:

- Activity Summary exposes running and standby detail while the retired
  entities are not created.
- Health Summary exposes the former electrical-health detail while Electrical
  Health is not created.
- Direct and NILM appliance detail pages render one Activity status and one
  Health status without a separate Electrical status.
- Applicable Standard/Expert dual-phase Leg Imbalance entities are enabled;
  Simple does not retain a disabled row.
- Pause Alerts renders the bell-pause icon.
- Registry pruning, dashboard, blueprint, and documentation contracts reference
  only current entities.

Then run the normal PR verification and Home Assistant contract verification.
