# NILM interval graph focus design

## Goal

Selecting an identified NILM interval must load a graph window around the full
interval and render that interval's band as selected. The same behavior must
apply when the NILM workspace first opens from a URL that targets an interval,
session, or assignment.

## Current behavior and root cause

The graph renderer already marks a band selected when
`_nilmFocusedInterval` matches its start and end timestamps. The focus loader
also already fetches a padded history window and records that state.

However, the review-card click handler in `energy-analyzer-panel-shell.js`
handles assignments and signature fingerprints only. An `interval` card falls
through to a generic history refresh, leaving `_nilmFocusedInterval` unset.
On first load, `_loadNilmWorkspace` restores only a `session_id` query
parameter, even though NILM links can carry `assignment_id` and intervals have
stable `interval_id` values.

## Design

Add one NILM-workspace focus path that resolves a selected review item or
route target and delegates to existing graph loaders:

- An interval invokes `_loadNilmIntervalOnGraph(interval, { edit: false })`.
- An assignment resolves its latest completed interval with
  `_nilmAssignmentFocusInterval` and loads it without opening the editor.
- A signature continues to use `_focusNilmSignatureOnGraph`.
- If no completed interval exists, retain the existing explanatory message and
  normal history behavior rather than synthesizing a selection.

The review-card click handler calls this shared path after updating the selected
review key. On workspace load, route resolution will prefer a specific
`interval_id`, then `session_id`, then `assignment_id`; it will select the
matching review item and lane when one exists, then use the same focus path.
Unknown or stale route identifiers leave the normal workspace graph intact.

The change remains frontend-only. It reuses the current workspace payload,
history API, graph intent tokens, and selected-band rendering rather than
adding an API field or persistence state.

## Testing

Extend the existing Playwright NILM workspace coverage to prove:

1. Clicking an identified interval loads its padded history window and gives
   the full interval band `data-nilm-selected="true"`.
2. Opening the workspace with a targeted route produces the same selected band
   and focused interval without user interaction.
3. The existing assignment and signature focus behaviors still use their
   current loaders.

Update the panel module-version contract because shipped frontend JavaScript
changes.

## Scope boundaries

No NILM detection, storage, API payload, URL-generation, or visual-style
changes are included. The existing selected-band style remains the user-facing
highlight.
