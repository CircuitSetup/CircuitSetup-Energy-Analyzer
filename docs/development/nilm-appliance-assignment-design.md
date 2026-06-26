# NILM Appliance Assignment Design

This is the staged design for NILM Appliance Assignment. PR 1 implements only the session model and deterministic on/off pairing needed by later assignment work.

## Goals

- Turn recurring unknown mains signatures into supervised, user-assigned estimated appliances.
- Keep all behavior local to Home Assistant.
- Keep estimates explicitly labeled as estimated and confidence-scored.
- Reuse existing NILM signatures, evidence panel, feedback, notifications, and compact entity patterns.
- Avoid mandatory external ML, large `.storage` waveform blobs, and automatic device creation.

## PR 1 Scope

Implemented in PR 1:

- current-state audit
- design doc
- `NilmSession`
- deterministic on/off edge pairing
- session confidence
- unit tests

Explicitly deferred:

- recorder/history graph APIs
- frontend NILM Workspace
- manual interval labels
- assignment registry
- storage migration for session history
- virtual appliance devices/entities
- notification integration
- sensor-based ground-truth labeling
- external trainer support

## Architecture

The expanded system has five layers.

1. Candidate discovery: existing edge detection, known-load masking, and signature clustering.
2. Session reconstruction: pair compatible on/off edges into `NilmSession` records.
3. Supervised assignment: map signatures, sessions, or intervals to appliances.
4. Virtual appliance state: compute estimated running, power, energy, confidence, and status.
5. Home Assistant publication: optional estimated device/entities and notifications.

PR 1 only adds layer 2 as reusable analytics logic.

## Session Model

`NilmSession` records a probable appliance run:

- stable session ID
- mains circuit ID
- stable signature fingerprint
- on/off edge IDs
- start/end timestamps
- duration
- median estimated power
- estimated energy
- confidence
- overlap count
- ambiguity flag and alternate match count
- known-load masking flag
- known-load match confidence when available
- optional assignment ID

Session IDs are derived from the circuit, signature fingerprint, and paired edge IDs. Later storage should preserve IDs after reload, but PR 1 does not persist sessions.

## Pairing Rules

The first implementation is deliberately conservative.

- Only `on` edges can start sessions.
- Only later `off` edges can close sessions.
- Off magnitude must be compatible with on magnitude.
- VAR, VA, and PF similarity improve confidence when present.
- Split-phase type and dominant leg must stay compatible.
- Very low-confidence matches are rejected; the on edge remains open.
- If multiple off candidates are close, the best match is used with reduced confidence.
- Ambiguous matches keep explicit ambiguity metadata for later review UI.
- Overlapping sessions are counted and reduce confidence.
- Open sessions are allowed when the off edge has not arrived yet, and they overlap later observed sessions until closed.

This is a deterministic template/session layer, not appliance classification.

## Confidence

Session confidence is separate from appliance identity.

Signals:

- real-power match
- reactive/apparent/PF match
- split-phase topology compatibility
- duration bounds
- overlap count
- ambiguous close off matches
- known-load masking uncertainty and known-load match confidence

Confidence is clamped to `0.0..1.0`. Published appliance behavior in later PRs must add stricter gates before notifications or entities are created.

## Storage Plan

PR 1 does not add storage fields.

Later storage should add bounded structures only after assignment workflows need durable state:

- label intervals by mains circuit
- appliance assignments by circuit
- virtual appliance state by assignment/appliance ID
- model feedback by assignment
- session history by circuit

Session history should be capped by count and age. Assignments should not be pruned when old session history is pruned.

## Panel And API Plan

PR 1 does not add panel routes or write actions.

Later graph APIs should:

- require Home Assistant authentication
- validate time range
- cap maximum range and point count
- downsample server-side
- handle missing Recorder gracefully
- never return unbounded raw history

The first NILM Workspace UI should be read-only. Assignment, interval labeling, and publishing actions should be added only after the read-only graph is tested.

## Direct-Meter Priority

Directly metered circuits stay authoritative.

Priority order:

1. direct CT/submeter
2. smart plug or real appliance sensor
3. NILM virtual estimate
4. unknown signature

Direct sensors should train and validate NILM, not be replaced by NILM.

## Test Strategy

PR 1 tests cover:

- simple on/off pairing
- open session when off edge is missing
- orphan off edge ignored
- low-confidence mismatch rejected
- topology mismatch rejected
- overlapping sessions counted
- ambiguous off candidates reduce confidence
- known-load masking lowers confidence
- energy estimate from paired duration and median power

Later PRs add API, storage, frontend, lifecycle, notification, and replay tests as those surfaces are introduced.
