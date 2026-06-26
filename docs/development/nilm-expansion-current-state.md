# NILM Expansion Current State

Baseline for `feature/nilm-appliance-assignment` PR 1.

- Baseline commit: `221b5739a52cfd64e901cbbb449a1ac92e46b0e3`
- Integration version: `0.9.4`
- Baseline verification: `rtk pytest -q` -> 1089 passed; `rtk ruff check .` -> no issues
- Codegraph: regenerated with `.codex/scripts/update-codegraph.ps1`

## Ownership Map

The current NILM runtime is intentionally small.

- `custom_components/circuitsetup_energy_analyzer/nilm.py` owns raw mains edge detection, known-load masking, recurring signature clustering, classification, and stable signature fingerprints.
- `custom_components/circuitsetup_energy_analyzer/unknown_loads.py` turns recurring signatures and unmatched edges into a compact unknown-load inventory.
- `custom_components/circuitsetup_energy_analyzer/processors/nilm_sample.py` wires NILM analytics into one normalized sample, store updates, and state updates.
- `custom_components/circuitsetup_energy_analyzer/processors/nilm_topology.py` checks whether matched known-load edges agree with configured circuit topology.
- `custom_components/circuitsetup_energy_analyzer/entities/nilm.py` exposes compact sensor values and bounded attributes.
- `custom_components/circuitsetup_energy_analyzer/panel.py` and `frontend/energy-analyzer-panel.js` expose the existing review workflow.
- `custom_components/circuitsetup_energy_analyzer/storage.py` persists signatures and unknown-load inventory only.

## Current Detection Flow

`NilmEdgeDetector` keeps one previous sample per mains NILM circuit. Missing `real_power` clears the previous sample. Otherwise, deltas below the configured threshold are ignored; larger deltas produce one `NilmEdge` with real, reactive, apparent, PF, leg, dominant-leg, and split-phase fields.

Coordinator thresholds are sensitivity-based:

- quiet: 150 W
- balanced: 100 W
- sensitive: 75 W

Split-phase topology is inferred from leg deltas as `single_leg_a`, `single_leg_b`, `balanced_240v`, `imbalanced_240v_or_mixed`, `missing_leg_data`, or `unknown`.

## Known-Load Masking

`mask_known_loads()` compares aggregate mains edges to known circuit START/STOP events.

- START can only mask `on` edges; STOP can only mask `off` edges.
- The default time window is 15 seconds.
- The default real-power tolerance is 25 percent.
- Each known event and each mains edge can be used once.
- Candidates are selected by highest confidence, then closest timestamp.

`NilmSampleProcessor` masks `existing_unmatched + new_edges`, which lets a delayed known event remove a prior unmatched edge.

## Signature Clustering

`cluster_recurring_signatures()` greedily clusters unmatched edges.

- Clusters require at least 3 edges.
- Matching requires the same direction, compatible split-phase type, W within 20 percent, and VAR within 35 percent.
- Stored signature fields are median W/VAR/VA/PF, occurrence count, confidence, leg fields, dominant leg, and split-phase type.
- Confidence is count-based and capped at 0.95.
- `nilm_signature_fingerprint()` gives review metadata a stable key independent of cluster-order IDs such as `on-1`.

## Unknown-Load Inventory

`build_unknown_load_inventory()` builds a user-facing inventory from signatures and matching edges.

Inventory-level fields include counts, active/ambiguous counts, simultaneous event count, estimated energy totals, largest load IDs, and an `unknown_loads` list.

Per-load fields include:

- signature ID, display name, likely type, voltage class, topology, typical W/VAR/VA/PF, confidence, occurrence count, and evidence
- first/last seen
- review state
- separation status
- running state
- last start/stop
- runtime and estimated energy windows

Runtime is currently inferred by matching absolute W/VAR/topology and walking `on`/`off` edges. There is no explicit NILM session model yet.

## Existing Review Actions

The existing user workflow is signature review, not appliance assignment.

- `label_nilm_signature` stores `user_label`.
- `ignore_nilm_signature` stores `ignored`.
- `mark_nilm_signature_expected` stores `expected` plus `review_state=expected`.
- `merge_nilm_signatures` stores `review_state=merged`, `merged_into`, and optionally `merged_into_fingerprint`.

Service validation rejects missing circuit IDs, unknown signature IDs, and self-merges.

## Entity Surface

NILM entities are compact and only apply where NILM is relevant.

- `nilm_signature_count`
- `nilm_unknown_loads`
- `nilm_unmatched_load_percentage`
- `nilm_topology_status`

Unknown-load attributes are bounded to 5 preview items and a small allowlist of fields.

## Evidence Panel And Frontend

The evidence API is a `HomeAssistantView` with `requires_auth = True`. It returns a top-level `nilm` object with `signatures`, counts, omission metadata, and per-signature actions.

The frontend renders `NILM Review` with:

- per-signature display labels and review state
- label text input
- merge target chips
- Save Label, Ignore, Mark Expected, and Merge buttons

Writes are standard Home Assistant service calls, not panel POST endpoints. The current frontend is not read-only because it already supports signature-review writes.

## Storage And Retention

`FeatureStoreData` persists:

- `nilm_signatures`
- `nilm_unknown_loads_by_circuit`

The storage schema version is `2`. The existing migration path only migrates v1 alert feedback and contextual baselines. NILM fields use tolerant dict/list loading.

Storage-level `prune_events()` keeps NILM fields unchanged. Runtime coordinator pruning caps NILM signatures at 64 and unknown loads at 32 per circuit.

There is no persisted session history, label interval registry, appliance assignment registry, virtual appliance state, or NILM feedback-by-assignment field.

## Current Tests

Relevant coverage exists in:

- `tests/test_nilm.py` for edge detection, known-load masking, clustering, fingerprinting, classification, and unmatched percentage.
- `tests/test_unknown_loads.py` for unknown-load estimates, inferred runtime, active state, ambiguity, and review-state preservation.
- `tests/test_processors.py` for NILM sample processor signature/inventory updates and delayed known-event masking.
- `tests/test_panel.py` for NILM review actions, merge targets, saved review-state overlays, bounded payloads, and expanded `include_all_nilm`.
- `tests/test_services.py` for NILM signature service schemas, entity targets, fail-fast validation, and coordinator dispatch.
- `tests/test_entities.py` for NILM entity helper values and bounded unknown-load attributes.
- `tests/test_storage.py` for NILM signature and unknown-load storage round trips.
- `tests_homeassistant/test_lifecycle_gate.py` for opt-in mains NILM lifecycle setup.

## Gaps And Risks

- No `NilmSession` exists.
- Explicit on/off pairing does not exist; runtime is inferred inside `unknown_loads.py`.
- Unmatched edge history is runtime-only.
- Storage has no session-history field or migration coverage for one.
- Current signatures are directional, while unknown-load runtime matching uses absolute values across on/off edges.
- Session IDs should not depend only on cluster-order signature IDs because those can change after reclustering.
- Pairing should not change existing unknown-load inventory semantics in PR 1.
- PR 1 should add the model, pairing, confidence, docs, and tests only; graph APIs, manual labels, assignment registry, virtual entities, and notifications belong in later PRs.
