# NILM External Trainer Spike

This is a design note only. The deterministic NILM session, assignment, virtual
appliance, feedback, and validation workflow must continue to work without an
external trainer.

## Recommendation

Do not add a mandatory trainer dependency.

If external training is added later, prefer this order:

1. Local export/import contract.
2. Optional Home Assistant add-on that implements that contract.
3. Optional user-provided trainer URL only after auth, TLS, privacy, and failure
   behavior are defined.

The integration should treat imported trainer output as one more confidence
signal, not as an authoritative replacement for directly metered circuits,
smart plugs, or user-confirmed labels.

## Questions

### Should the integration support an external trainer URL?

Not in the first implementation. A URL setting makes network, auth, retention,
and privacy behavior part of the integration contract. Start with an explicit
local export/import format so users can train offline or through an add-on
without the integration making outbound calls.

If a URL is added later, it should be disabled by default, require an explicit
local-network URL, use Home Assistant-managed credentials or a dedicated token,
and fail closed back to deterministic NILM behavior.

### Should there be a Home Assistant add-on?

An add-on is the safest future packaging target because it keeps training local,
gives users visible lifecycle control, and avoids adding heavy ML dependencies
to the custom integration. The integration should not require the add-on to be
installed.

### Can trainer concepts be reused without a heavy dependency?

Yes. Reuse concepts, not packages:

- edge/session feature extraction;
- supervised label intervals;
- direct-meter validation intervals;
- train/validation splits by time;
- confidence calibration from prediction agreement;
- model-card style artifact metadata.

The integration should own the stable export schema. Any trainer should adapt to
that schema instead of importing the integration internals.

## Export Data

The export should be a bounded local bundle with a manifest and line-oriented
records. It should prefer normalized events and labels over raw waveform dumps.

Recommended bundle contents:

- manifest: integration version, export schema version, generated timestamp, and
  selected mains circuit IDs;
- circuit metadata: circuit IDs, appliance profiles, sensor roles, and units;
- NILM edges: timestamp, direction, W/VAR/VA/PF deltas, topology, and known-load
  mask metadata;
- paired sessions: session ID, signature fingerprint, start/end, duration,
  energy estimate, confidence, ambiguity, and assignment ID when present;
- label intervals: interval ID, label, appliance ID, source, confidence, and
  optional ground-truth entity ID;
- validation summaries: direct-meter agreement, missed labels, false positives,
  and calibration windows.

Raw history samples should be optional, time-bounded, downsampled, and exported
only from an explicit diagnostics-style action.

## Artifact Versioning

Imported artifacts need a manifest. Minimum fields:

- artifact schema version;
- integration version and export schema version used for training;
- trainer name and trainer version;
- model type and feature schema hash;
- training time range and validation time range;
- mains circuit IDs and label set;
- calibration metrics;
- created timestamp.

The integration should reject incompatible major schema versions and ignore
unknown optional fields. Model artifacts should never create devices or publish
entities automatically; they should first appear as reviewable assignment or
confidence evidence.

## Privacy And Local-Only Behavior

External training must be opt-in and local by default.

Guardrails:

- no outbound trainer calls unless the user explicitly configures a trainer;
- no full waveform histories in logs;
- no labels, appliance names, or entity IDs in debug logs unless redacted;
- export bundles stay on the Home Assistant host unless the user downloads them;
- imported artifacts must not override direct-meter evidence;
- deleting an assignment should also remove any imported evidence tied only to
  that assignment.

## Future Acceptance Gates

Do not implement trainer support until these are true:

- deterministic NILM assignment remains usable without the trainer;
- export/import schemas have unit tests and old-schema compatibility tests;
- all payloads are bounded by circuit, time range, and record count;
- Home Assistant auth protects any trainer-related API;
- failure, timeout, and incompatible-artifact behavior is covered by tests;
- documentation states that trainer output is estimated and reviewable.

## Deferred Work

- Define the export bundle schema in code.
- Add an explicit export service or panel action.
- Build an add-on proof of concept outside the integration.
- Add artifact import review UI.
- Add calibration metrics that compare imported predictions with direct sensors.
