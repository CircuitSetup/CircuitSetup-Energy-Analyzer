# NILM Real-Data Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover valid persisted NILM session runtime and energy when exact v2 or uniquely identifying v1 fingerprints are available, without weakening pair or identity-collision safety.

**Architecture:** Keep unknown-load ownership inside `unknown_loads.py`: restore every field consumed by the v2 fingerprint, add the v1 fingerprint only as an explicit identity alias, and require exactly one owner. Keep raw edge allocation unchanged, but make the session-backed payload gate on component pairing and session ownership rather than unrelated raw-edge ambiguity.

**Tech Stack:** Python 3.12, Home Assistant custom integration models, pytest, Ruff, PowerShell repository verification scripts.

## Global Constraints

- Missing v2 leg fields remain `None` for older persisted payloads.
- Session ownership uses explicit identity equality only; never infer ownership from watts, timestamps, topology, confidence, or similarity.
- A v1 identity must match exactly one current component; collisions attribute to no component and remain ambiguous.
- Sessions marked ambiguous or known-load-masked remain excluded.
- Ambiguous ON/OFF pairing and session-identity collisions zero session-backed runtime and energy.
- Raw edge allocation, edge-only estimates, confidence formulas, assignment scoring, storage schema, and numeric thresholds remain unchanged.
- Do not use HACS.
- Deploy only an archive of the exact merged GitHub commit through the authenticated Home Assistant Terminal & SSH add-on.
- Preserve the replaced integration under `/config/.csea-backups`, restart Home Assistant, then verify service recovery and fresh logs.

---

## File structure

- Modify `custom_components/circuitsetup_energy_analyzer/unknown_loads.py`: hydrate complete signatures, construct strict v1 ownership aliases, and separate session ambiguity from edge diagnostics.
- Modify `tests/test_unknown_loads.py`: add real-data-shaped regression fixtures for v2 migration, unique and collided v1 aliases, raw-edge/session evidence interaction, and pair ambiguity.
- No new production modules, configuration settings, dependencies, or storage fields.

### Task 1: Preserve the complete v2 fingerprint during migration

**Files:**
- Modify: `tests/test_unknown_loads.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/unknown_loads.py:514-532`

**Interfaces:**
- Consumes: persisted signature mappings accepted by `_signature_from_payload(payload: Mapping[str, Any])`.
- Produces: a reconstructed `NilmSignature` whose `nilm_signature_fingerprint()` exactly matches the producer-side v2 fingerprint when leg fields were persisted.

- [ ] **Step 1: Add a failing migration regression**

Import `nilm_signature_fingerprint` in `tests/test_unknown_loads.py`. Create `test_migration_preserves_v2_leg_fingerprint_for_session_ownership` with a producer-side `NilmSignature` containing `median_leg_a_delta_w=480.0`, `median_leg_b_delta_w=20.0`, and `leg_balance_ratio=0.04`. Pass the corresponding full signature payload to `migrate_unknown_load_inventory`, and pass one closed session whose only current identity is `signature_fingerprint=nilm_signature_fingerprint(producer_signature)` and whose `component_id` is `legacy-component-id`. Assert the rebuilt load has that exact `component_fingerprint`, `runtime_today_minutes == 60.0`, `estimated_energy_today_kwh == 0.5`, and `runtime_windows["today"]["included_session_count"] == 1`.

```python
producer_signature = NilmSignature(
    signature_id="sig-v2-legs",
    median_delta_w=500.0,
    median_delta_var=100.0,
    median_delta_va=510.0,
    median_delta_pf=0.0,
    occurrence_count=4,
    confidence=0.7,
    dominant_leg="a",
    split_phase_type="single_leg_a",
    median_leg_a_delta_w=480.0,
    median_leg_b_delta_w=20.0,
    leg_balance_ratio=0.04,
)
fingerprint = nilm_signature_fingerprint(producer_signature)
```

- [ ] **Step 2: Run the new test and verify the expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_migration_preserves_v2_leg_fingerprint_for_session_ownership -q
```

Expected: FAIL because the migrated component fingerprint contains unknown leg values, the session has no owner, and runtime is `0.0` instead of `60.0`.

- [ ] **Step 3: Hydrate all v2 fingerprint fields**

Add these keyword arguments to the `NilmSignature` returned by `_signature_from_payload`:

```python
median_leg_a_delta_w=_optional_float(payload.get("median_leg_a_delta_w")),
median_leg_b_delta_w=_optional_float(payload.get("median_leg_b_delta_w")),
leg_balance_ratio=_optional_float(payload.get("leg_balance_ratio")),
```

- [ ] **Step 4: Verify the regression and focused suite are green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_migration_preserves_v2_leg_fingerprint_for_session_ownership -q
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py -q
```

Expected: both commands exit 0; the focused test reports one pass and the file suite has no failures.

- [ ] **Step 5: Commit the independently verified hydration fix**

```powershell
git add -- custom_components/circuitsetup_energy_analyzer/unknown_loads.py tests/test_unknown_loads.py
git commit -m "fix: preserve NILM v2 session fingerprints"
```

### Task 2: Resolve legacy v1 identities only when unique

**Files:**
- Modify: `tests/test_unknown_loads.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/unknown_loads.py:20-45,1059-1100`

**Interfaces:**
- Consumes: `_NormalizedUnknownLoadSession.identities` and current `_UnknownLoadComponent` instances.
- Produces: `_session_owner_candidates(...) -> tuple[str, ...]` containing every exact current candidate; `_session_inventory_evidence` remains responsible for accepting exactly one candidate and flagging collisions.

- [ ] **Step 1: Add failing unique-v1 and collision regressions**

Import `nilm_signature_fingerprint_v1`. Create `test_session_ownership_accepts_unique_computed_v1_fingerprint`. Build one component with non-null leg deltas, pass a closed session with `component_id="retired-component-id"` and `signature_fingerprint=nilm_signature_fingerprint_v1(component)`, and provide no existing-state identity bridge. Assert `runtime_today_minutes == 60.0`, `estimated_energy_today_kwh == 0.5`, and `separation_status == "separable"`.

Create `test_session_ownership_rejects_collided_v1_fingerprint`. Construct two ON signatures with identical v1 fields and `leg_balance_ratio`, but different leg deltas so their v2 fingerprints differ. Pass one closed session identified only by their shared v1 fingerprint. Assert both loads have `separation_status == "ambiguous"`, `runtime_today_minutes == 0.0`, `estimated_energy_today_kwh == 0.0`, and `runtime_windows["today"]["included_session_count"] == 0`.

```python
first = signature(
    "sig-v1-collision-a",
    500.0,
    100.0,
    510.0,
    split_phase_type="single_leg_a",
    dominant_leg="a",
    median_leg_a_delta_w=480.0,
    median_leg_b_delta_w=20.0,
    leg_balance_ratio=0.04,
)
second = signature(
    "sig-v1-collision-b",
    500.0,
    100.0,
    510.0,
    split_phase_type="single_leg_a",
    dominant_leg="a",
    median_leg_a_delta_w=430.0,
    median_leg_b_delta_w=70.0,
    leg_balance_ratio=0.04,
)
assert nilm_signature_fingerprint_v1(first) == nilm_signature_fingerprint_v1(second)
assert nilm_signature_fingerprint(first) != nilm_signature_fingerprint(second)
```

Extend the local `signature()` test helper with optional `median_leg_a_delta_w`, `median_leg_b_delta_w`, and `leg_balance_ratio` keyword arguments and forward them into `NilmSignature` so fixtures mirror persisted data.

- [ ] **Step 2: Run both v1 tests and verify the expected failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_session_ownership_accepts_unique_computed_v1_fingerprint tests\test_unknown_loads.py::test_session_ownership_rejects_collided_v1_fingerprint -q
```

Expected: FAIL because `_session_owner_candidates` does not include the computed v1 alias: the unique session has zero runtime, and the collided identity is unowned instead of explicitly ambiguous.

- [ ] **Step 3: Add the explicit v1 alias to owner candidate identities**

Import `nilm_signature_fingerprint_v1` beside `nilm_signature_fingerprint`, then extend the local identity set:

```python
identities = {
    component.component_id,
    component.component_fingerprint,
    component.on_signature.signature_id,
    nilm_signature_fingerprint(component.on_signature),
    nilm_signature_fingerprint_v1(component.on_signature),
}
```

Do not call `resolve_nilm_signature_fingerprint`; candidate enumeration must retain all exact v1 collisions so the existing `len(candidates) != 1` gate can reject them.

- [ ] **Step 4: Run both v1 tests and verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_session_ownership_accepts_unique_computed_v1_fingerprint tests\test_unknown_loads.py::test_session_ownership_rejects_collided_v1_fingerprint -q
```

Expected: both tests pass: unique ownership is recovered and collisions remain excluded.

- [ ] **Step 5: Run the focused suite and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py -q
git add -- custom_components/circuitsetup_energy_analyzer/unknown_loads.py tests/test_unknown_loads.py
git commit -m "fix: recover uniquely owned legacy NILM sessions"
```

Expected: the test suite exits 0 before the commit.

### Task 3: Keep raw edge conflicts diagnostic for session-backed estimates

**Files:**
- Modify: `tests/test_unknown_loads.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/unknown_loads.py:1315-1370`

**Interfaces:**
- Consumes: `_UnknownLoadComponent.pair_status`, `_UnknownLoadAllocation` diagnostics, and `_SessionInventoryEvidence.ambiguous_component_ids`.
- Produces: session-backed load payloads where `ambiguous_edge_count` remains observable but hard ambiguity derives only from pairing and session evidence.

- [ ] **Step 1: Add the failing edge/session regression and pair-safety guardrail**

Create `test_unique_session_survives_raw_edge_component_ambiguity`. Use two similar ON-only signatures (`500 W` and `520 W`), one `510 W` ON edge that is close enough to mark both raw allocations ambiguous, and one closed session explicitly owned by the `500 W` component from 10:00 to 11:00. Assert that component retains `ambiguous_edge_count == 1`, but has `separation_status == "separable"`, `runtime_today_minutes == 60.0`, `estimated_energy_today_kwh == 0.5`, `running_state == "probably_off"`, and one included today session.

Create `test_session_evidence_does_not_override_ambiguous_signature_pairing` with one ON signature and two similarly scored OFF signatures, plus one closed session explicitly owned by the ON component. Assert `pair_status == "ambiguous"`, `separation_status == "ambiguous"`, zero today runtime and energy, and zero included sessions. This guardrail documents the existing hard safety boundary that the production change must preserve.

- [ ] **Step 2: Run the edge/session test and verify the expected failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_unique_session_survives_raw_edge_component_ambiguity tests\test_unknown_loads.py::test_session_evidence_does_not_override_ambiguous_signature_pairing -q
```

Expected: the edge/session test FAILS because the current session payload copies raw `separation_status == "ambiguous"` into its hard ambiguity gate and zeroes the session; the pair-safety guardrail PASSES.

- [ ] **Step 3: Change only the session-backed hard ambiguity gate**

Replace the raw payload status check in `_unknown_component_session_payload` with the component's pairing status:

```python
ambiguous = (
    component.pair_status == "ambiguous"
    or component.component_id in evidence.ambiguous_component_ids
)
```

Leave `_allocate_unknown_edges` and `_unknown_component_payload` unchanged. The later assignment of `payload["separation_status"]` will report session-backed separability, while `ambiguous_edge_count` remains copied from the raw allocation for diagnosis.

- [ ] **Step 4: Run both regressions and verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_unique_session_survives_raw_edge_component_ambiguity tests\test_unknown_loads.py::test_session_evidence_does_not_override_ambiguous_signature_pairing -q
```

Expected: both tests pass, proving session evidence survives only raw-edge ambiguity while pair ambiguity remains a hard gate.

- [ ] **Step 5: Run focused regressions and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py::test_unique_session_survives_raw_edge_component_ambiguity tests\test_unknown_loads.py::test_session_evidence_does_not_override_ambiguous_signature_pairing tests\test_unknown_loads.py::test_session_ownership_rejects_collided_v1_fingerprint -q
.\.venv\Scripts\python.exe -m pytest tests\test_unknown_loads.py -q
git add -- custom_components/circuitsetup_energy_analyzer/unknown_loads.py tests/test_unknown_loads.py
git commit -m "fix: preserve independent NILM session evidence"
```

Expected: both pytest commands exit 0 before the commit.

### Task 4: Verify, review, merge, and validate on real Home Assistant data

**Files:**
- Verify: all intended branch changes
- Deploy: `custom_components/circuitsetup_energy_analyzer` from the exact merged commit archive

**Interfaces:**
- Consumes: the three independently committed behavior changes and repository verification scripts.
- Produces: a merged GitHub commit whose archive is deployed byte-for-byte to the Home Assistant custom-component directory, with a rollback copy and post-restart evidence.

- [ ] **Step 1: Review the complete branch diff and requirements**

```powershell
git status --short --branch
git diff origin/master...HEAD --check
git diff --stat origin/master...HEAD
git diff origin/master...HEAD -- custom_components/circuitsetup_energy_analyzer/unknown_loads.py tests/test_unknown_loads.py
```

Confirm only the design/plan, production fix, and regression tests are present. Check every global constraint against the diff.

- [ ] **Step 2: Run repository verification**

```powershell
.\.codex\scripts\verify-pr.ps1
```

Expected: diff check, Ruff, and the full pytest suite all exit 0. If platform/entity behavior is touched unexpectedly, also run:

```powershell
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
```

- [ ] **Step 3: Obtain an independent code review**

Use `superpowers:requesting-code-review` against `origin/master...HEAD`. Resolve every correctness or safety finding, add a failing regression before any behavioral fix, and rerun Step 2 after changes.

- [ ] **Step 4: Commit any verification-only plan tracking changes separately**

```powershell
git status --short
```

If the checklist itself was updated, stage only this plan and commit it as `docs: record NILM recovery verification`; otherwise make no empty commit.

- [ ] **Step 5: Push and open a draft pull request**

```powershell
git push -u origin fix/nilm-real-data-recovery
gh pr create --draft --title "Recover NILM session evidence from real stored data" --body "Recovers safely owned persisted NILM sessions observed on the live Home Assistant installation. Restores complete v2 fingerprint hydration, supports only uniquely identifying v1 aliases, and keeps pair and identity collisions ambiguous. Includes red/green regression coverage and repository verification."
```

The PR body must summarize the live evidence, root causes, conservative safety gates, red/green regressions, and verification commands. Poll required checks and thread-aware reviews, address actionable feedback, then mark ready and merge only when all required checks and review threads are resolved.

- [ ] **Step 6: Build and validate the exact merged archive**

Record the merged commit SHA from GitHub, download that commit's archive, and verify the archive SHA and expected integration paths before deployment. Compare Git blob hashes for `unknown_loads.py`, `nilm.py`, and `processors/nilm_sample.py` to the merged commit.

- [ ] **Step 7: Deploy through the authenticated Terminal & SSH add-on**

At `https://home.degster.com:8123/core_ssh`, create a timestamped directory under `/config/.csea-backups`, move the current `/config/custom_components/circuitsetup_energy_analyzer` into it, extract the validated exact-commit archive to `/config/custom_components/circuitsetup_energy_analyzer`, and verify deployed hashes before restart. Do not use HACS.

- [ ] **Step 8: Restart and verify fresh real-data behavior**

Restart Home Assistant from the authenticated add-on. After service recovery, verify integration entities and inventory are available; collect only logs written after the restart boundary; confirm there are no new setup, migration, or NILM errors; and re-query the live store to confirm uniquely owned sessions produce nonzero runtime/energy while collided identities remain excluded. If recovery fails, restore the timestamped backup and restart again.
