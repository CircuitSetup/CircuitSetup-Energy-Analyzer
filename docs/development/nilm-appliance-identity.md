# NILM Appliance Identity

## Identity contract

Every NILM appliance has a stable logical key:

```text
nilm:<assignment_id>
```

The appliance key, assignment ID, appliance ID, mains circuit ID, and mains
source entity remain separate fields. Renaming an appliance or changing its
profile does not change its appliance key.

Direct-meter circuits use `circuit:<circuit_id>` in appliance-centered read
models. A NILM-to-direct conversion retains the original NILM key and history
as provenance while linking it to the direct circuit.

## Session ownership

NILM Appliance Detail gives an explicit session `assignment_id` precedence.
Only ownerless legacy sessions may fall back to a `session_id` explicitly
retained by the assignment. It never uses the whole mains activity timeline as
appliance history.

The bounded feature store retains assignment sessions with their start, end,
duration, estimated energy, confidence, validation state, and signature
fingerprint. Appliance Detail derives runtime today, run count, current session
duration, last completed match, and the recent timeline from that history.

## Validation gate

Today vs Normal is enabled only when the assignment is validated or published
and has all of the following:

- at least three confirmed sessions;
- confirmed sessions on at least three distinct local dates;
- confidence of at least 80 percent; and
- a false-positive rate no greater than 20 percent.

Before the gate is met, the UI reports that validation or confirmed history is
still needed and does not present learned NILM comparisons as normal behavior.
After the gate, energy, runtime, and run-count comparisons use validated
assignment sessions clipped to the same local time of day. NILM cost remains
unavailable until tariff-aware interval accumulation can support it.

## Alerts and evidence

NILM alerts retain the mains circuit as measurement context, but carry
`primary_target: nilm:<assignment_id>`. Evidence includes the assignment,
session, signature fingerprint, mains circuit, and mains source entity. Opening
the notification routes to that NILM appliance's detail view rather than the
generic mains detail.

Appliance Detail offers Correct, Wrong appliance, Adjust interval, Mark
expected, and Not helpful in the session or alert context where each action is
valid. A review deep link carries the active or last session into the NILM
workspace.

## Direct-meter conversion

The NILM workspace offers conversion when a configured direct-meter circuit is
available. Conversion preserves the friendly name, profile, signatures,
session IDs, label intervals, validation decisions, and original appliance key.
Estimated entities are unpublished by default to avoid duplicate appliance
readings. The assignment may remain as historical provenance and masking
context, or be retired.

Storage schema version 6 backfills `appliance_key` for older assignments during
load and serialization. Existing session history and unrelated optional store
sections remain unchanged.
