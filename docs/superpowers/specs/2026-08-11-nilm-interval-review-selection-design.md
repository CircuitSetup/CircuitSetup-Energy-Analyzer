# NILM Interval Review Selection

## Goal

Allow a closed, non-ambiguous NILM session interval to be selected for review and approval without automatically entering interval-edit mode.

## Behavior contract

- Selecting a non-ambiguous session review item selects its review card and focuses the same interval on the graph.
- Selection keeps the interval editor closed.
- The selected session's existing approval and rejection actions remain available.
- Ambiguous sessions are not exposed as individual user-facing session items.
- Ambiguous session records remain internal, bounded reconciliation evidence only.
- Editing starts only from an explicit **Adjust interval** or **Edit interval** action.
- Draft intervals and saved label intervals retain their current selection and editing behavior.

## Design

Separate session focus from session editing in the NILM workspace frontend.

The review-item path will call a focus-only helper for session items. That helper will load the session's graph window, clear stale signature focus, and set the focused interval without creating an interval draft or opening the editor.

The existing explicit adjustment path will continue to call the edit helper. It will populate the draft, preserve the associated assignment, and open the editor.

The panel API will filter ambiguous sessions out of its user-facing session payload. This keeps them out of Needs Review, validation cards, session lists, graph bands, and targeted session navigation without adding frontend-only hiding rules.

Ambiguous records will continue to be retained internally under the existing 45-day and 2,000-record-per-circuit caps. They replace stale open or assigned interpretations for the same ON edge when later evidence conflicts. They remain excluded from assignment, learning, primary-evidence binding, and unknown-load energy calculations. Removing them at creation would require a separate tombstone or atomic invalidation mechanism and is outside this change.

No backend schema or persisted-data migration is required.

## Error handling

Invalid, open, ambiguous, or filtered intervals will not become focused or editable through the panel. A failed focused-history request will leave the prior graph and editor state intact. Explicit editing will retain the current error handling.

## Verification

Browser regressions will cover:

1. Selecting a closed, non-ambiguous session review item selects the card and graph interval while the editor remains closed.
2. The selected interval retains its approval/rejection actions.
3. Ambiguous sessions are absent from the panel session payload and all review/list surfaces.
4. Clicking **Adjust interval** explicitly opens the editor.
5. Existing signature, draft, and saved-label interval selection behavior remains intact.
6. Processor regressions continue to prove that retained ambiguous records replace stale open or assigned interpretations.

Because shipped frontend JavaScript changes, the panel module cache version will be bumped.
