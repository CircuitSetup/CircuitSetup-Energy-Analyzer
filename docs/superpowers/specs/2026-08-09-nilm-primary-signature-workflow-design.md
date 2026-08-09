# NILM primary appliance signature workflow

## Problem

A configured primary appliance and a NILM signature are currently separate
concepts.  Saving confirmed interval labels adds interval evidence to the
configured-primary assignment, but does not bind a recurring signature.  The
workspace therefore displays the misleading message "No signature has been
confirmed for this primary appliance" even when the appliance has confirmed
interval evidence.

The review lanes also suppress a signature review card when an unassigned
auto-detected session refers to that signature.  The session card exposes only
an appliance-assignment field, not the signature's Identify, Ignore, or Merge
decisions.  This strands the detection in review without a complete decision
path.

## Goals

1. Make the configured-primary card distinguish its configured appliance,
   confirmed interval evidence, established signature, and active detection
   attribution.
2. Automatically establish a primary's signature binding when saved confirmed
   interval evidence identifies one safe, unambiguous signature.
3. Give every auto-detected session that represents a signature access to that
   signature's full review decisions.
4. Remove the NILM Expected state and reopen every existing Expected item for
   review.
5. Preserve manual control: automatic linking must never guess, replace a
   different binding, or take a decision intended for a human reviewer.

## Definitions and states

| Concept | Meaning | Source of truth |
| --- | --- | --- |
| Configured primary | The configured circuit appliance and its primary assignment exist. | Circuit configuration and primary assignment |
| Confirmed interval evidence | User-confirmed interval labels attached to that assignment. | `label_interval_ids` and stored interval records |
| Established signature | A retained, assignable recurring signature is bound to the primary assignment. | Assignment `signature_fingerprints` and the signature's `assignment_id` |
| Active detection attribution | New detected sessions resolving to the established signature receive the primary assignment. | NILM session-history attribution |

The card must show these states independently.  In particular, it must say
that interval evidence exists but a signature is not yet established when that
is the true state; it must not describe the appliance as unassigned.

## Automatic primary signature linking

The interval-save path, including single-interval labeling and the bulk
interval editor, will reconcile a configured primary after storing its labels.
It will use the same domain mutation rules as an explicit signature assignment
and persist the result in the same save transaction.

An automatic link is allowed only when all of the following are true:

1. The newly saved confirmed primary evidence corresponds to complete,
   unambiguous, non-masked retained detection session(s).
2. Those session(s) resolve to exactly one eligible, assignable recurring
   signature fingerprint.
3. That signature is not owned by another appliance.
4. The primary has no different established signature.

If the primary already has that same signature, reconciliation is a no-op.  If
there is no candidate, more than one candidate, masked or ambiguous evidence,
a non-resolvable/retired signature, another signature owner, or a conflicting
primary binding, no automatic link is made.  The evidence remains saved and
the page makes the remaining review work visible.  Replacing an established
signature always requires an explicit reviewer action.

When a link is made, the assignment's signature fingerprints, the retained
signature's assignment ownership/state, assignment model, and session history
are rebuilt together.  A failed save leaves all of them as they were before the
interval edit; partial linkage is not permitted.

## Workspace payload and primary-card UI

The configured-primary payload will provide explicit status data rather than
forcing the renderer to infer it from a nullable `current_binding`:

- configured appliance identity and primary assignment;
- confirmed interval-evidence count;
- signature state (`not_established` or `established`), with its display label
  and recurrence/detection count when established; and
- attribution state, including the number of matching detected sessions
  currently assigned to the primary.

The card will render a concise lifecycle summary:

1. **Configured:** HVAC 2 is the primary appliance.
2. **Evidence:** N confirmed intervals are saved.
3. **Signature:** either "Not established yet" with a truthful explanation, or
   the linked signature and its recurrence count.
4. **Attribution:** either "Matching detections are assigned automatically" and
   a count, or "No matching detections are currently assigned."

This replaces the current ambiguous sentence.  Empty evidence and no signature
will be stated plainly, and a configured appliance will never be labelled as
unassigned merely because it lacks a signature.

## Remove the NILM Expected state

Expected is removed from NILM rather than hidden.  New NILM reviews will have
no Expected decision, no Expected lane, no Expected signature or assignment
state, no service dispatch, and no translation or renderer branch for it.

During controller initialization, persisted NILM records that previously used
Expected will be normalized before the workspace is served:

1. An Expected signature becomes a new, unassigned signature.  Its retained
   signature/model evidence remains intact; its `expected` marker and Expected
   review state are cleared.
2. The synthetic Expected assignment created solely to own that signature is
   removed.  Its matching stored sessions are detached from that removed
   assignment so they re-enter review with the signature.
3. A malformed legacy Expected assignment with no surviving signature is also
   removed.  A non-Expected assignment is never altered by this migration.
4. The normalized state is saved once only when a record actually changed.

The migration deliberately does not convert Expected to ignored/dismissed:
every previously Expected signature returns to Needs Review, where the user
can identify it, dismiss it, or merge it.  Requests for the removed service
are not supported after this change.

## Auto-detection review workflow

For every review-lane session with a resolvable signature fingerprint, the
backend will expose its signature decision target and permitted signature
actions.  The session inspector will identify that relationship, for example:
"This detection matches Signature A; this decision applies to the signature
and future matching detections."

It will render the signature decisions in that session context:

- **Identify / assign** the signature to an appliance, including the configured
  primary;
- **Ignore** (the current dismissal equivalent); and
- **Merge** where the signature supports it.

The action executes against the referenced signature, then refreshes the
workspace so the session moves to the appropriate lane.  Sessions without a
resolvable signature retain the direct appliance-assignment workflow; they do
not claim to support signature decisions.  This removes the dead-end caused by
suppressing the separate signature card while keeping the session as the
context the user was reviewing.

## Error handling and compatibility

- The panel keeps accepting older payloads that lack the new optional status
  fields, rendering conservative, truthful fallback text.
- Domain reconciliation validates IDs and ownership before mutation, skips
  malformed/missing session or signature records, and logs no false success.
- Automatic linking changes no other appliance assignment and does not create a
  signature from a lone interval.
- Existing explicit assignment, ignore, merge, and interval-edit endpoints
  retain their current authorization and persistence behavior; the Expected
  endpoint is removed.
- The frontend module version is bumped with the JavaScript change so Home
  Assistant clients receive the new UI.

## Test plan

Write failing regression tests before implementation that cover:

1. Labeling a configured-primary interval whose complete, unambiguous session
   maps to one free recurring signature establishes that primary binding and
   yields automatic attribution for matching sessions.
2. Ambiguous, masked, unmatched, multi-signature, already-owned, and
   conflicting-binding cases save evidence but do not auto-link.
3. The workspace payload distinguishes configured appliance, evidence,
   established/not-established signature, and attribution counts.
4. A review-lane session that stands in for a signature exposes the signature
   decision target/actions, while a session with no resolvable signature does
   not.
5. Legacy Expected signatures and their synthetic assignments normalize to new,
   unassigned review data exactly once; Expected cannot appear in a new payload
   or action set.
6. Existing explicit primary confirmation and review-decision behavior remains
   covered by the focused NILM controller and panel tests.

After implementation, run the focused regression tests, then the repository's
normal lint/test verification and a whitespace diff check.
