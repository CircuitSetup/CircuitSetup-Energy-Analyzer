# Task 5 report: lazy NILM panel reads

## Outcome

Replaced the eager generic workspace context with a request-local
`_NilmWorkspaceReadSource`. Generic collection routes now ask it for one named,
whitelisted collection, and exact-item routes resolve through the source mapped
to the requested item kind. Prepared signatures, intervals, assignments, and
merged sessions are cached only within that request.

The specialized ambiguity collection route remains unchanged. The main
`nilm_workspace_payload` path retains its existing bounded previews.

## RED proof

Before production changes:

```text
rtk pytest tests/test_panel.py -q
Pytest: 197 passed, 3 failed
```

The three expected structural failures were:

- exact signature lookup called `_nilm_workspace_sessions`;
- the signatures collection called `_nilm_workspace_sessions`;
- exact assignment lookup called
  `_nilm_known_load_attributions_for_circuit`.

All failures were raised by structural spies at the eager
`_nilm_workspace_collection_context` call path, demonstrating the intended
isolation regression rather than a fixture or syntax error.

## GREEN proof

```text
rtk pytest tests/test_panel.py -q
Pytest: 200 passed

rtk pytest tests/test_panel.py tests/e2e -q
Pytest: 200 passed

rtk git diff --check
exit 0

rtk ruff check custom_components/circuitsetup_energy_analyzer/panel_nilm.py tests/test_panel.py
Ruff: No issues found
```

## Benchmark and executor decision

Command:

```text
.\.venv\Scripts\python.exe scripts\benchmark_nilm_performance.py
```

Environment: Python 3.12.10, Windows 10, 16 logical CPUs, AMD64 Family 23.
The benchmark performs five repetitions. Its maximum bounded panel fixture has
100 retained sessions (the collection response remains capped by the route
limit).

| Panel request | Median | Minimum | Serialized bytes |
| --- | ---: | ---: | ---: |
| Main workspace | 5.917 ms | 5.831 ms | 35,151 |
| Sessions collection | 5.479 ms | 5.457 ms | 27,798 |
| Exact signature item | 0.978 ms | 0.970 ms | 2,972 |

No executor offload was added. The maximum panel reads visited 100 retained
session rows, below the greater-than-500-row threshold, and every median was
below 10 ms across five runs. Keeping these reads on the event loop also avoids
introducing live coordinator access or mutation from an executor.

## Contract checks

- Collection limit validation, signed cursor generation/validation, stable
  ordering, pagination metadata, error envelopes, and entry-scoped actions
  continue through the existing helpers.
- Exact item payload fields and retired-assignment status remain unchanged.
- Timestamp-less assignment focus lazily consults related sessions and then
  label intervals; timestamp-less signature focus consults persisted sessions
  without generating edge-derived workspace sessions.
- Exact ambiguous-session links retain read-only `open_on_graph` actions.
- The dedicated ambiguity grouping and occurrence behavior was not folded into
  the generic source.
- No frontend files changed, so `PANEL_MODULE_VERSION` was not bumped.

## Changed files

- `custom_components/circuitsetup_energy_analyzer/panel_nilm.py`
- `tests/test_panel.py`
- `.superpowers/sdd/2026-08-12-nilm-ha-performance-mitigation/task-5-report.md`

## Review fix round 1

The original benchmark conclusion above was invalid because its panel fixture
used 100 retained sessions, not the 2,000-row retention maximum. The benchmark
fixture now uses `max(SESSION_COUNTS)` (2,000), requests the maximum collection
page limit of 50, and measures both signature and session exact-item routes.

### Executor implementation

The collection and exact-item HTTP views now capture a bounded, detached
snapshot on the event loop and submit the pure synchronous payload builder via
`hass.async_add_executor_job`. The snapshot contains only the selected circuit's
signatures, 2,000-row-capped session history, intervals, attributions, inventory,
and unmatched edges, plus configured-circuit assignment data needed for helper
semantics. Referenced HA states and reference-option rows are copied on the
event loop. Executor code does not retain or access the live coordinator, HA
state machine, or persistence objects. Direct synchronous payload helpers remain
available for pure callers and benchmarks.

No background worker, persisted cache, or writer was added. Request
cancellation naturally cancels the awaiting view, and a regression test proves
that no JSON response is published after cancellation.

### Corrected maximum-retention benchmark

Command:

```text
.\.venv\Scripts\python.exe scripts\benchmark_nilm_performance.py
```

Five-run measurements on the same Python 3.12.10 / Windows / AMD64 environment:

| Panel request, 2,000 retained sessions | Median | Minimum | Serialized bytes |
| --- | ---: | ---: | ---: |
| Main workspace | 106.662 ms | 101.582 ms | 35,275 |
| Sessions collection, limit 50 | 102.725 ms | 100.482 ms | 69,351 |
| Exact session | 93.847 ms | 92.157 ms | 1,558 |
| Exact signature | 15.581 ms | 15.478 ms | 2,972 |

Both binding gates are exceeded: the session-backed reads visit 2,000 retained
rows (>500), and all maximum-retention panel medians exceed 10 ms. Consequently,
collection and item HTTP construction is executor-offloaded from immutable
snapshots. The main workspace keeps its existing bounded preview behavior as
allowed by the Task 5 brief; this review specifically binds async collection and
item construction to the snapshot builder.

### Review RED/GREEN and contract evidence

RED before async route implementation:

```text
rtk pytest tests/test_panel.py -q -k "workspace_collection_view_forwards or workspace_item_view_forwards"
Pytest: 0 passed, 2 failed
```

Both failures were the expected missing async collection/item builder symbols.

GREEN after implementation:

```text
rtk pytest tests/test_panel.py -q -k "workspace_collection_view_forwards or workspace_item_view_forwards"
Pytest: 2 passed

rtk pytest tests/test_panel.py -q -k "detached_snapshot or cancelled_nilm_collection"
Pytest: 2 passed

rtk pytest tests/test_panel.py -q
Pytest: 202 passed

rtk ruff check custom_components/circuitsetup_energy_analyzer/panel_nilm.py custom_components/circuitsetup_energy_analyzer/panel_views.py tests/test_panel.py scripts/benchmark_nilm_performance.py
Ruff: No issues found

rtk git diff --check
exit 0
```

Additional changed files in this review round:

- `custom_components/circuitsetup_energy_analyzer/panel_views.py`
- `scripts/benchmark_nilm_performance.py`

## Review fix round 2

Async collection and item reads now retain an event-loop-owned source identity
across snapshot construction and executor execution. The identity is derived
without comparing retained-history contents: it uses coordinator/config/data
object identity plus selected collection container identity, length, and tail
identity. It also covers configured helper-assignment containers and the small
set of referenced HA state rows used by assignment payloads.

The shared async read loop performs three event-loop checks:

1. capture identity;
2. build the detached immutable snapshot and revalidate before dispatch;
3. await the pure executor builder and revalidate before returning.

If either revalidation fails, the stale snapshot/payload is discarded and the
read retries from current live state. The executor continues to receive only a
detached snapshot and never accesses live coordinator or HA objects. Await
cancellation still propagates before any view can call `json_response`.

RED evidence:

```text
rtk pytest tests/test_panel.py -q -k "async_read_retries_stale_snapshot"
Pytest: 0 passed, 1 failed
assert hass.executor_calls == 2
E assert 1 == 2
```

The failure proved the previous implementation returned the first completed
executor payload even after retained history advanced while it was pending.

GREEN and verification evidence:

```text
rtk pytest tests/test_panel.py -q -k "async_read_retries_stale_snapshot or detached_snapshot or cancelled_nilm_collection"
Pytest: 3 passed

rtk ruff check custom_components/circuitsetup_energy_analyzer/panel_nilm.py tests/test_panel.py
Ruff: No issues found

rtk pytest tests/test_panel.py tests/e2e -q
Pytest: 203 passed

rtk git diff --check
exit 0
```

The stale-result regression test advances retained session identity after the
first executor payload is built. It proves the first payload is not returned,
the builder is dispatched a second time, and the public response contains both
current sessions.

## Review fix round 3

The endpoint/tail identity heuristic was replaced with Task 2's exact tracked
collection revisions. `processors/nilm_sample.py` now exposes two small runtime
helpers: one installs the existing tracked-list/tracked-dictionary wrapper at a
collection boundary, and the other reads its exact O(1) mutation revision.

Before snapshot capture, the panel event loop installs tracking for the selected
circuit's session history, signatures, label intervals, known-load
attributions, unknown-load inventory rows, and unmatched edges, plus assignment
collections for configured helper circuits. Nested dictionaries and lists use
Task 2's existing forwarding wrappers, so in-place scalar edits and non-tail
replacements increment the same collection-local revision.

Identity revalidation now uses collection object identity and exact mutation
revision, not retained row scanning, hashing, length, or endpoint sampling. If a
tracked source is externally replaced by a plain list while the executor runs,
its revision becomes `None`; this uncertain identity cannot match the captured
tracked revision. The stale payload is discarded, and the next event-loop retry
installs tracking on the replacement before snapshotting. Snapshot conversion
copies tracked runtime values into detached plain dictionaries/lists, keeping
the executor pure and preventing live coordinator/HA access.

RED evidence:

```text
rtk pytest tests/test_panel.py -q -k "retries_exact_tracked_mutations"
Pytest: 0 passed, 2 failed
assert hass.executor_calls == 2
E assert 1 == 2
```

The two failures covered an in-place `median_power_w` edit on the first retained
row and replacement of that same non-tail row. Both previously returned the
first stale executor payload.

GREEN and verification evidence:

```text
rtk pytest tests/test_panel.py -q -k "retries_exact_tracked_mutations or retries_stale_snapshot or detached_snapshot or cancelled_nilm_collection"
Pytest: 5 passed

rtk pytest tests/test_panel.py tests/e2e -q
Pytest: 205 passed

rtk pytest tests/test_processors.py -q -k "unchanged_session_history_does_not_resanitize_ingress or nilm_input_row_mutations_invalidate_session_rebuild"
Pytest: 2 passed

rtk ruff check custom_components/circuitsetup_energy_analyzer/processors/nilm_sample.py custom_components/circuitsetup_energy_analyzer/panel_nilm.py tests/test_panel.py
Ruff: No issues found

rtk git diff --check
exit 0
```

Cancellation behavior and public collection/item response contracts remain
unchanged. No persisted revision, cache, writer, worker, or executor-side live
read was introduced.
