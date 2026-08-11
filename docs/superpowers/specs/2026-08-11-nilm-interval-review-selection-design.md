# NILM Interval Review Selection

## Goal

Allow a closed, non-ambiguous NILM session interval to be selected for review and approval without automatically entering interval-edit mode.

## Behavior contract

- Selecting a non-ambiguous session review item selects its review card and focuses the same interval on the graph.
- Selection keeps the interval editor closed.
- The selected session's existing approval and rejection actions remain available.
- Ambiguous sessions remain ineligible for approval.
- Editing starts only from an explicit **Adjust interval** or **Edit interval** action.
- Draft intervals and saved label intervals retain their current selection and editing behavior.

## Design

Separate session focus from session editing in the NILM workspace frontend.

The review-item path will call a focus-only helper for session items. That helper will load the session's graph window, clear stale signature focus, and set the focused interval without creating an interval draft or opening the editor.

The existing explicit adjustment path will continue to call the edit helper. It will populate the draft, preserve the associated assignment, and open the editor.

No backend schema or persisted data changes are required. The existing session index and session payload contain the identity, ambiguity, assignment, and action data needed by both paths.

## Error handling

Invalid or open intervals will not become focused or editable. A failed focused-history request will leave the prior graph and editor state intact. Explicit editing will retain the current error handling.

## Verification

Browser regressions will cover:

1. Selecting a closed, non-ambiguous session review item selects the card and graph interval while the editor remains closed.
2. The selected interval retains its approval/rejection actions.
3. Selecting an ambiguous interval does not expose approval.
4. Clicking **Adjust interval** explicitly opens the editor.
5. Existing signature, draft, and saved-label interval selection behavior remains intact.

Because shipped frontend JavaScript changes, the panel module cache version will be bumped.
