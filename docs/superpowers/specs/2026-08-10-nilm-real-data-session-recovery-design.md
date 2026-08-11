# NILM Real-Data Session Recovery Design

Date: 2026-08-10

## Goal

Recover valid NILM runtime and energy evidence that the unknown-load inventory currently discards, while preserving conservative ambiguity handling. The change must work with persisted data produced before and after the expanded v2 signature fingerprint introduced in PR 454.

## Evidence from the Home Assistant installation

The deployed integration is version 0.13.16, and the deployed `unknown_loads.py`, `nilm.py`, and `processors/nilm_sample.py` Git blob hashes match the current repository implementation. The behavior is therefore not caused by a stale deployment.

The live store showed:

- all current unknown loads reported zero runtime and energy;
- 2,000 mains sessions, 357 HVAC 2 sessions, and 64 pressure sessions were available;
- current v2 signature fingerprints matched only 91 mains sessions and 68 HVAC 2 sessions, while legacy v1 fingerprints matched another 940 mains and 176 HVAC 2 sessions;
- after excluding sessions already marked ambiguous or known-load-masked, strict unique ownership could safely recover about 197 mains, 176 HVAC 2, and 37 pressure sessions;
- raw edge ambiguity was usually sparse: each affected connected component had only one ambiguous edge, and many had substantially more clear edges.

Fresh Home Assistant logs contained no NILM exception explaining the zero values. Inspection instead found three deterministic ownership and gating defects.

## Root causes

### Incomplete v2 signature hydration

`unknown_loads._signature_from_payload()` reconstructs a `NilmSignature` without `median_leg_a_delta_w`, `median_leg_b_delta_w`, or `leg_balance_ratio`. The v2 `nilm_signature_fingerprint()` includes those fields. When inventory migration rebuilds a component from persisted signature payloads, its recomputed fingerprint therefore differs from the fingerprint stored on an otherwise valid session.

### No conservative v1 alias fallback

Session-owner resolution recognizes current component IDs, signature IDs, and v2 fingerprints, but it does not compute the legacy v1 fingerprint for current components. Persisted sessions using v1 identities become unowned. The general signature resolver is not appropriate here because it may rank candidates after a legacy alias collision; unknown-load energy attribution must stop at collision rather than choose a best match.

### Raw edge ambiguity overrides independent session evidence

The session-backed payload starts from the raw edge-derived payload and treats its `separation_status == "ambiguous"` as a hard gate. One close or simultaneous edge can consequently zero runtime and energy from separately persisted, explicitly non-ambiguous sessions with a unique owner.

## Approved behavior

### Complete fingerprint reconstruction

Hydrate all v2 fingerprint inputs from a persisted signature payload:

- `median_leg_a_delta_w`
- `median_leg_b_delta_w`
- `leg_balance_ratio`

Missing fields remain `None`, preserving compatibility with older payloads. A payload written with v2 leg fields must reproduce its original v2 fingerprint exactly.

### Strict legacy identity compatibility

For every current unknown-load component, build an ownership identity set containing its existing identifiers, current v2 fingerprint, and computed v1 fingerprint. A session may contribute only when its identity resolves to exactly one current component.

If a v1 alias matches two or more current components, no winner is selected. All candidates involved in that session-identity collision remain ambiguous for session-backed attribution. No wattage, topology, confidence, or similarity heuristic may break the collision.

Existing exclusions remain in force: sessions explicitly marked ambiguous or known-load-masked cannot contribute runtime or energy.

### Separate raw-edge diagnostics from session attribution

The raw edge allocator remains unchanged for edge-only estimates and continues to expose counts and separation diagnostics. For a session-backed component, however, raw edge ambiguity alone does not invalidate uniquely owned, explicitly non-ambiguous sessions.

Two conditions remain hard ambiguity gates and zero session-backed runtime and energy:

1. the signature component itself has an ambiguous ON/OFF pairing; or
2. session identity resolves to multiple current components, including v1 alias collisions or duplicate session ownership.

Thus edge ambiguity is diagnostic when independent session evidence is available, but pair and identity ambiguity still prevent attribution.

## Data flow

1. Persisted signatures are fully hydrated into `NilmSignature` objects.
2. Unknown-load components are built with their exact v2 fingerprint and a calculated legacy v1 alias.
3. Eligible persisted sessions are normalized without changing existing ambiguity and known-load masking exclusions.
4. Owner candidates are determined only by explicit identity equality.
5. Exactly one owner permits session aggregation; zero owners contributes nothing; multiple owners mark the candidates ambiguous.
6. The session-backed payload retains raw edge counts for diagnosis but bases its hard ambiguity status on pair ambiguity and session-evidence ambiguity.
7. Runtime, window energy, duty cycle, operating state, and energy confidence continue to use the existing aggregation formulas.

## Scope boundaries

This change does not:

- alter signature clustering, ON/OFF pairing, raw edge allocation, confidence formulas, or assignment scoring;
- infer ownership from wattage or timestamps;
- rehabilitate sessions already marked ambiguous or known-load-masked;
- rewrite persisted store records;
- add new settings or tune numerical thresholds.

These boundaries isolate the fix to lost identity fidelity and an incorrect interaction between two independent evidence sources.

## Verification

Regression tests will first demonstrate the current failures:

1. a migrated v2 payload with non-null leg fields must reproduce its exact fingerprint and retain the uniquely owned session's runtime and energy;
2. a session identified only by a unique computed v1 fingerprint must be retained;
3. a v1 fingerprint shared by two current components must attribute to neither and must remain ambiguous;
4. a uniquely owned, non-ambiguous session must retain runtime and energy when the component also has a raw ambiguous edge;
5. ambiguous ON/OFF pairing and session identity collisions must still zero runtime and energy.

After implementation, run the focused unknown-load tests, the repository's normal PR verification, and Home Assistant contract tests if the change affects platform behavior.

## Delivery and live validation

The verified branch will be committed, pushed, reviewed, and merged through the repository's protected `master` workflow. Deployment will use an archive of the exact merged GitHub commit, validated before extraction. Through the authenticated Home Assistant Terminal & SSH add-on only, the existing integration directory will be preserved under `/config/.csea-backups`, the archive will replace `/config/custom_components/circuitsetup_energy_analyzer`, and Home Assistant will be restarted.

Live verification must confirm:

- Home Assistant and the integration recover after restart;
- deployed core file hashes match the merged commit;
- fresh logs contain no new setup, migration, or NILM errors;
- newly rebuilt unknown-load inventory uses safely recoverable session evidence without attributing collided identities.

Rollback is the preserved pre-deployment integration directory under `/config/.csea-backups`.
