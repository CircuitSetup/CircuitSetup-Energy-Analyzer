# Load Separation UI Cleanup and Typed NILM Confidence Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`-\`) syntax for tracking.

**Goal:** Update the Load Separation/NILM workspace presentation and remove the obsolete \`legacy_mixed\` confidence semantic from runtime, persistence, notifications, appliance detail, panel payloads, translations, and tests.

**Architecture:** Keep typed confidence ownership in the existing NILM domain and confidence migration helpers. The frontend will reuse small workspace render helpers for formatted times, typed confidence lines, edge metadata, session power summaries, publication readiness, and disclosure sections; backend payloads will no longer create generic legacy-confidence fallbacks.

**Tech Stack:** Python 3.12, pytest, Ruff, vanilla JavaScript modules, Node-based render tests, Playwright, Home Assistant panel contracts.

## Global Constraints

- Preserve typed semantics: sessions use \`pairing_confidence\`, signatures use \`evidence_strength\`, assignments use \`feedback_evidence_score\`, and model quality uses \`model_fit\`.
- Do not use generic assignment \`confidence\` as a fallback for publication readiness, notifications, appliance detail, or workspace labels.
- Remove \`legacy_mixed\`, “Legacy confidence (mixed semantics)”, and \`legacy_confidence_after\` from runtime/user-facing confidence paths; unrelated fixture identifiers named \`legacy_mixed\` remain.
- Open Session Validation cards must never render estimated kWh.
- Publication readiness gates must render expanded by default and no publication “Reason” text may render.
- Bump \`custom_components/circuitsetup_energy_analyzer/panel_contracts.py::PANEL_MODULE_VERSION\` for frontend changes.
- Use \`apply_patch\` for source edits and force-add the ignored \`docs/superpowers\` spec/plan files when committing documentation.

---

### Task 1: Replace legacy confidence migration with typed-only cleanup

**Files:**
- Modify: \`custom_components/circuitsetup_energy_analyzer/nilm_confidence.py\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/storage.py\` only if the load-time migration contract needs its field list updated
- Test: \`tests/test_nilm_confidence.py\`
- Test: \`tests/test_storage.py\`

**Interfaces:**
- Preserve \`migrate_nilm_confidence_semantics(assignments_by_circuit, signatures_by_circuit, sessions_by_circuit) -> bool\` as the load-time entrypoint.
- Preserve \`apply_nilm_feedback_evidence(assignment, *, feedback_id, correct, timestamp) -> bool\` for typed feedback updates.
- Produce records where signatures expose \`evidence_strength\`, sessions expose \`pairing_confidence\`, assignments expose \`feedback_evidence_score\` only when available, and no record contains \`confidence_kind == "legacy_mixed"\` or an event key \`legacy_confidence_after\`.

- [ ] **Step 1: Write failing migration tests.**

Add assertions to the existing migration tests that:

~~~python
def test_migration_removes_legacy_assignment_confidence_and_event_mirror():
    assignments = {"mains": [{
        "assignment_id": "dryer",
        "confidence": 0.72,
        "confidence_kind": "legacy_mixed",
        "feedback_evidence_events": [{
            "feedback_id": "session:one",
            "outcome": "correct",
            "score_after": 0.05,
            "legacy_confidence_after": 0.77,
        }],
    }]}
    changed = migrate_nilm_confidence_semantics(assignments, {}, {})
    record = assignments["mains"][0]
    assert changed is True
    assert "confidence" not in record
    assert "confidence_kind" not in record
    assert "legacy_confidence_after" not in record["feedback_evidence_events"][0]
    assert record["feedback_evidence_events"][0]["score_after"] == 0.05
~~~

Also add the inverse typed-preservation cases for a signature with \`confidence\`, a session with \`confidence\`, and an assignment with \`feedback_evidence_score\`.

- [ ] **Step 2: Run the focused tests and verify the expected failure.**

Run:

~~~powershell
rtk pytest tests/test_nilm_confidence.py tests/test_storage.py -q
~~~

Expected: FAIL because the current migration preserves \`legacy_mixed\`, generic assignment confidence, and \`legacy_confidence_after\`.

- [ ] **Step 3: Implement the minimal migration changes.**

Update \`_migrate_assignment\`, \`_migrate_signature\`, \`_migrate_session\`, \`_feedback_events\`, and the feedback-update event construction so that:

~~~python
event.pop("legacy_confidence_after", None)
~~~

is applied while parsing old events; assignment migration deletes obsolete generic confidence/semantic fields when no typed feedback score exists; signature/session migration copies a finite old value into their typed field before deleting the generic value; and typed feedback assignments retain \`confidence_kind == "feedback_evidence"\` without a legacy mirror.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run:

~~~powershell
rtk pytest tests/test_nilm_confidence.py tests/test_storage.py -q
~~~

Expected: PASS with no legacy semantic fields in migrated records and typed values preserved.

- [ ] **Step 5: Commit the typed migration slice.**

~~~powershell
git add custom_components/circuitsetup_energy_analyzer/nilm_confidence.py custom_components/circuitsetup_energy_analyzer/storage.py tests/test_nilm_confidence.py tests/test_storage.py
git commit -m "refactor: remove legacy NILM confidence semantics"
~~~

### Task 2: Remove backend confidence fallbacks from readiness, alerts, detail, and panel labels

**Files:**
- Modify: \`custom_components/circuitsetup_energy_analyzer/nilm.py\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/nilm_virtual.py\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/managers/nilm_controller.py\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/appliance_detail.py\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/panel_nilm.py\`
- Test: \`tests/test_nilm.py\`
- Test: \`tests/test_nilm_controller.py\`
- Test: \`tests/test_coordinator.py\`
- Test: \`tests/test_panel.py\`
- Test: \`tests/test_appliance_detail.py\`
- Test: \`tests/test_services.py\`
- Test: \`tests/test_entities.py\`

**Interfaces:**
- \`evaluate_nilm_validation_readiness()\` must use typed feedback evidence for the confidence gate and report an unmet gate when no typed feedback score exists.
- \`_nilm_confidence_label()\` and \`_nilm_confidence_kind()\` must return only typed labels/kinds or an empty/absent result.
- \`_nilm_signature_label()\` must omit confidence text when no \`evidence_strength\` exists.
- NILM virtual appliance and appliance-detail payloads must omit \`confidence_kind\` when no typed assignment score exists.

- [ ] **Step 1: Write failing backend regression assertions.**

Update existing expectations and add cases asserting that:

~~~python
readiness = evaluate_nilm_validation_readiness(
    {"assignment_id": "dryer", "confidence": 0.95},
    [],
)
assert readiness["publication_readiness"]["gates"]["feedback_evidence"] == "missing"
~~~

and that panel labels, alerts, appliance detail expectations, entity attributes, and service notifications contain no “Legacy confidence (mixed semantics)” text. Add a typed-feedback case proving “Feedback evidence score” remains visible.

- [ ] **Step 2: Run the focused tests and verify the expected failure.**

Run:

~~~powershell
rtk pytest tests/test_nilm.py tests/test_nilm_controller.py tests/test_panel.py tests/test_appliance_detail.py tests/test_services.py tests/test_entities.py tests/test_coordinator.py -q
~~~

Expected: FAIL at the old fallback assertions and readiness fallback behavior.

- [ ] **Step 3: Remove legacy fallback branches.**

Change the readiness compatibility-confidence calculation to use only \`feedback_evidence_score\`; remove \`setdefault(..., "legacy_mixed")\` calls from the controller; make virtual appliance state derive its displayed confidence from a typed feedback score only; remove the legacy branch from \`_nilm_confidence_label()\` and \`_nilm_confidence_kind()\`; update appliance-detail confidence wording to use typed feedback evidence or omit the confidence clause; and remove the panel signature-label fallback.

- [ ] **Step 4: Run the focused backend tests and verify they pass.**

Run the same focused pytest command. Expected: PASS, with typed confidence behavior retained and legacy text absent.

- [ ] **Step 5: Commit the backend consumer slice.**

~~~powershell
git add custom_components/circuitsetup_energy_analyzer/nilm.py custom_components/circuitsetup_energy_analyzer/nilm_virtual.py custom_components/circuitsetup_energy_analyzer/managers/nilm_controller.py custom_components/circuitsetup_energy_analyzer/appliance_detail.py custom_components/circuitsetup_energy_analyzer/panel_nilm.py tests/test_nilm.py tests/test_nilm_controller.py tests/test_panel.py tests/test_appliance_detail.py tests/test_services.py tests/test_entities.py tests/test_coordinator.py
git commit -m "refactor: use typed NILM confidence consumers"
~~~

### Task 3: Add shared Load Separation session/edge render helpers and UI behavior

**Files:**
- Modify: \`custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/translations/en.json\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/panel_contracts.py\`
- Test: \`tests/test_user_facing_text.py\`

**Interfaces:**
- Add a workspace-local session-time renderer that uses \`_formatDateTime()\` and exposes separate start/end spans.
- Add a session-summary renderer that omits energy when \`session.end\` is absent.
- Keep \`_nilmConfidenceDescriptor()\` typed-only; it returns \`null\` when no typed value is available.
- Edge rows receive \`workspace.source.source_kind\` so dominant-leg metadata is only rendered for Mains NILM.

- [ ] **Step 1: Write failing Node-render tests.**

Extend the existing \`test_user_facing_text.py\` Node script cases to assert:

~~~javascript
const html = panel._renderNilmSecondaryCollections(makeWorkspace({
  source: { source_kind: "mains" },
  sessions: [{
    session_id: "open",
    start: "2026-06-24T18:12:00Z",
    end: null,
    display_label: "Dryer",
    pairing_confidence: 0.82,
    median_power_w: 720,
    actions: { assign: {} },
  }],
  edges: [{ timestamp: "2026-06-24T18:12:00Z", direction: "on", delta_w: 720.126, split_phase_type: "unknown", dominant_leg: "L1" }],
}));
assert.ok(html.includes("2026-06-24"));
assert.ok(html.includes("Pairing confidence: 82%"));
assert.ok(html.includes("720.13 W"));
assert.ok(html.includes("Dominant leg: L1"));
assert.ok(!html.includes("unknown ·"));
~~~

Add completed-session assertions for separate start/end elements and open Session Validation assertions that omit \`kWh\` after the watt value.

- [ ] **Step 2: Run the focused Node-render tests and verify the expected failure.**

Run:

~~~powershell
rtk pytest tests/test_user_facing_text.py -q
~~~

Expected: FAIL because session rows use raw ISO strings, edge rows show the raw topology field, and open validation rows include the energy placeholder.

- [ ] **Step 3: Implement the minimal render helpers and translations.**

Update \`_renderNilmSecondaryCollections()\`, \`_renderNilmSessionValidationCard()\`, and \`_formatNilmSessionRange()\` callers to use formatted local times, separate start/end spans, typed pairing-confidence lines, two-decimal watts, and the open-session power-only summary. Remove the split-phase field from edge rows and conditionally render dominant-leg metadata for \`source_kind === "mains"\`.

Add translations for the separate session time labels/error lines/helper-description/session-rendering copy and update the helper selector copy. Remove \`legacy_mixed_confidence\`, \`session_legacy_confidence\`, and other legacy confidence display strings.

- [ ] **Step 4: Run the focused Node-render tests and verify they pass.**

Run \`rtk pytest tests/test_user_facing_text.py -q\`. Expected: PASS for the updated render contract.

- [ ] **Step 5: Bump the frontend cache version and commit the UI slice.**

Update \`PANEL_MODULE_VERSION\` from its current value to the next unique build value, then run:

~~~powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js custom_components/circuitsetup_energy_analyzer/translations/en.json custom_components/circuitsetup_energy_analyzer/panel_contracts.py tests/test_user_facing_text.py
git commit -m "fix: clean up NILM session and edge presentation"
~~~

### Task 4: Update published interval details and technical-detail disclosure grouping

**Files:**
- Modify: \`custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel-shell.js\` only if the shared disclosure styling needs a selector adjustment
- Modify: \`custom_components/circuitsetup_energy_analyzer/translations/en.json\`
- Test: \`tests/test_user_facing_text.py\`
- Test: \`tests/e2e/panel.spec.js\`

**Interfaces:**
- \`_renderNilmPublicationReadiness()\` renders status plus an open \`<details>\` gate list and no reason text.
- \`_renderNilmHelperEvidence()\` renders its description immediately below “Helper circuit evidence”.
- \`_renderNilmEvidenceDetails()\` and \`_renderNilmAmbiguityAudit()\` render within the \`data-nilm-secondary-collections\` technical-details section, while existing data attributes and lazy-load event handlers remain valid.

- [ ] **Step 1: Write failing UI assertions.**

Add Node-render and Playwright expectations that a selected assignment inspector contains:

~~~javascript
expect(html).toContain("Median power error");
expect(html).toContain("Energy error");
expect(html).toContain("Publication readiness");
expect(html).not.toContain("Reason:");
expect(html).toContain("<details open");
expect(html).toContain("A helper circuit is a separately monitored circuit");
expect(html).toContain("Choose a helper circuit");
~~~

Assert that “Review uncertain events” is inside the same disclosure-summary structure as “Evidence quality and attribution”, and that both sections occur under \`data-nilm-secondary-collections\`.

- [ ] **Step 2: Run the focused UI tests and verify the expected failure.**

Run:

~~~powershell
rtk pytest tests/test_user_facing_text.py -q
npx playwright test tests/e2e/panel.spec.js --grep "NILM workspace|Session Validation|published|uncertain|evidence quality"
~~~

Expected: FAIL on current reason text, collapsed gates, helper copy, button styling, and section order.

- [ ] **Step 3: Implement the inspector and disclosure changes.**

Render power/energy error lines separately; remove both publication reason outputs; add \`open\` to the gates details; add helper description copy; convert the ambiguity review control to the existing evidence disclosure-summary presentation without changing its \`data-nilm-ambiguity-toggle\` hook or async focus restoration; and compose both detail sections inside the technical-details container.

- [ ] **Step 4: Run the focused UI tests and verify they pass.**

Run the same pytest and Playwright commands. Expected: PASS, including no accessibility regressions in the touched panel flows.

- [ ] **Step 5: Commit the published-inspector slice.**

~~~powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel-shell.js custom_components/circuitsetup_energy_analyzer/translations/en.json tests/test_user_facing_text.py tests/e2e/panel.spec.js
git commit -m "fix: clarify NILM publication and evidence details"
~~~

### Task 5: Remove remaining legacy confidence strings and update all regression contracts

**Files:**
- Modify: \`custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-appliance-views.js\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-evidence-views.js\`
- Modify: \`custom_components/circuitsetup_energy_analyzer/translations/en.json\`
- Modify: all tests identified by \`rg -n -i 'legacy[ _-]confidence|legacy_mixed|session_legacy' custom_components tests tests_homeassistant\`

- [ ] **Step 1: Write a repository-wide absence check.**

Add/update test assertions so only unrelated fixture/circuit/profile identifiers remain. The semantic output check must reject:

~~~powershell
rg -n -i 'Legacy confidence \(mixed semantics\)|legacy_confidence_after|confidence_kind["'': ]+legacy_mixed|session_legacy_confidence|legacy_mixed_confidence' custom_components tests tests_homeassistant
~~~

- [ ] **Step 2: Run the focused absence and frontend tests.**

Run the command above plus:

~~~powershell
rtk pytest tests/test_user_facing_text.py tests/test_panel.py tests/test_services.py -q
~~~

Expected: FAIL only at stale contracts and old frontend fallback branches.

- [ ] **Step 3: Remove stale frontend fallback branches and update tests.**

In \`_applianceInsightConfidenceText()\` and graph session titles, return typed labels only (\`feedback_evidence_score\` and \`pairing_confidence\`); remove obsolete translation keys; update all old assertions to typed/no-label expectations; preserve fixture names that describe mixed circuits rather than confidence semantics.

- [ ] **Step 4: Run the focused absence and frontend tests again.**

Expected: no semantic matches outside explicitly permitted fixture identifiers, and all focused tests pass.

- [ ] **Step 5: Commit the cleanup slice.**

~~~powershell
git add custom_components tests tests_homeassistant
git commit -m "test: remove legacy NILM confidence contracts"
~~~

### Task 6: Run full verification and inspect the final diff

**Files:**
- Verify: all changed files and the committed spec/plan

- [ ] **Step 1: Run repository checks.**

~~~powershell
rtk git diff --check HEAD~5..HEAD
rtk ruff check .
rtk pytest -q
~~~

- [ ] **Step 2: Run Home Assistant contract checks because panel behavior changed.**

~~~powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_control_entities.py tests\\test_config_flow.py tests_homeassistant -q
~~~

- [ ] **Step 3: Run the targeted static-browser suite.**

~~~powershell
npx playwright test tests/e2e/panel.spec.js --grep "NILM workspace|Session Validation|published|uncertain|evidence quality"
~~~

- [ ] **Step 4: Inspect status, diff, and semantic absence.**

~~~powershell
git status --short --branch
git diff HEAD~5..HEAD --stat
git diff HEAD~5..HEAD --check
rg -n -i 'Legacy confidence \(mixed semantics\)|legacy_confidence_after|confidence_kind["'': ]+legacy_mixed|session_legacy_confidence|legacy_mixed_confidence' custom_components tests tests_homeassistant
~~~

Expected: clean diff check, all verification commands exit 0, no forbidden semantic matches, and only the intended fix-branch commits are present.

- [ ] **Step 5: Commit any final test-only corrections, if required, then report exact verification evidence.**
