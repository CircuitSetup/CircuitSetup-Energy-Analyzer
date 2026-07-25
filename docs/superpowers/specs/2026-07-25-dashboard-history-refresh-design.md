# Dashboard History Refresh Design

## Goal

Keep dashboard totals and activity current without repeatedly loading growing
raw Recorder history ranges.

## Scope

This change covers the dashboard findings introduced by PR #367:

- remove overlapping House Flow raw-history requests;
- bound live graph refreshes;
- refresh selected activity timelines after real state transitions.

It preserves shared date controls, retained daily totals, graph tooltips,
comparison ranges, and existing entity identity and unit contracts.

## House Flow Totals

House Flow will continue loading retained completed-day totals from the
appliance insights endpoint. For a selected range containing today, it will
merge those rows with the current `daily_energy_usage` and `cost_today` entity
states already included in each dashboard payload.

The card will no longer request power or cost history or integrate power in
the browser. Current entity states will be read during render, so normal Home
Assistant state updates refresh today's contribution without another API
request. Missing live entities produce unavailable values rather than a
whole-day time-of-use estimate.

## Graph History

Ranges longer than one day will use Recorder statistics. A one-day range will
keep raw history for Home Assistant-style detail.

For a live one-day range, the first request loads the selected day. Later
refreshes request only a short overlapping tail beginning at the latest loaded
timestamp. Returned rows are merged by entity and timestamp so the overlap
cannot duplicate points. Completed comparison ranges remain cached, and stale
responses cannot replace data for a newer range.

This keeps the high-resolution default view while bounding each subsequent
Recorder request and browser parse.

## Activity Timeline

The timeline request key will include the selected activity entities'
`last_changed` values. Area and explicit-appliance selections therefore reload
only when one of their activity states actually transitions. Range or
selection changes retain their existing invalidation behavior.

## Cache Version And Documentation

`PANEL_MODULE_VERSION` will be incremented because shipped JavaScript changes.
`README.md` will be reviewed; no setup or workflow documentation change is
expected.

## Error Handling

Insights, statistics, and history failures retain the current unavailable-data
fallbacks. A failed incremental request leaves the last successful graph
visible and remains eligible for a later refresh.

## Verification

Playwright coverage will prove:

- House Flow does not request raw history and uses live daily entity states;
- multi-day graphs use statistics;
- repeated live one-day refreshes request only a bounded tail and merge it;
- selected activity timelines request new history after `last_changed`
  changes;
- desktop and mobile dashboard layouts still render without overlap.

Focused Python tests will verify the dashboard payload still provides the
daily energy, cost, and activity entities required by the frontend.
