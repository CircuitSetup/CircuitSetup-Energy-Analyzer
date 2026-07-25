# Usage Pipeline Blocking Design

## Goal

Keep source-driven usage updates responsive while preserving the current
analysis, persistence, and utility-comparison results.

## Scope

This change covers four backend findings:

- prevent a store mutation made during a save from being marked clean;
- move full feature-store serialization off the Home Assistant event loop;
- stop querying utility statistics on every source batch;
- stop rescanning all retained events and alerts for every circuit refresh.

It does not change learning rules, retained-data limits, entity contracts,
utility comparison calculations, or notification behavior.

## Persistence

`FeatureStore.async_save()` will retain its async interface but schedule the
write with Home Assistant's native `Store.async_delay_save(..., delay=0)`.
The delayed callback will serialize the latest `FeatureStoreData` in Home
Assistant's storage executor rather than building the full dictionary on the
event loop.

Scheduling is synchronous from the coordinator's perspective: no task switch
can occur between scheduling the write and clearing the dirty flag. A mutation
that happens later calls `mark_dirty()` after the flag was cleared and remains
due for the next save. Home Assistant owns write serialization and final-write
handling, so no custom worker or lock is added.

## Utility Comparison Cadence

The processing pipeline will remember the last comparison time and a copied
settings value for each configured circuit. A comparison runs when:

- the circuit has not been compared in this process;
- its settings differ from the last observed settings; or
- 15 minutes have elapsed since the last comparison.

Skipped batches retain the previously published comparison state. Removed
circuits are removed from the cadence maps. Query failures are also throttled
to avoid turning Recorder failure into a source-update loop.

## UX Refresh Indexes

Each coordinator update will group retained events by circuit and determine
the latest alert per circuit once. The existing per-circuit UX refresh will
accept those prefiltered values and pass them to learning, cycle, alert, and
recent-activity calculations.

All circuits will still refresh because cross-circuit processors can affect
whole-house and appliance state. The change removes repeated global scans
without introducing dependency tracking or risking stale cross-circuit data.

## Error Handling

Home Assistant storage remains responsible for logging delayed-write failures
and completing a final write during shutdown. Utility query exceptions keep
their current fallback behavior. Prefiltered UX data is optional so direct
test and service callers retain the current behavior.

## Verification

Tests will prove:

- feature-store serialization is deferred through `async_delay_save`;
- a later dirty mark remains due after a scheduled save;
- repeated source batches inside 15 minutes use one utility query set;
- settings changes and interval expiry force a new utility comparison;
- one coordinator update groups retained evidence once rather than once per
  circuit;
- existing coordinator, persistence, utility, learning, and Home Assistant
  contract tests still pass.

`README.md` will be reviewed, but no documentation change is expected because
the user-facing contracts and setup remain unchanged.
